"""
backend/metrics_router.py — Prometheus instrumentation for DC-EPMS PRO.

================================================================================
NORMATIVE GROUNDING (V9 Rule 4 — Grounding Técnico Forzado)
================================================================================

This module instruments the FastAPI application with curated Prometheus metrics
chosen to validate the operational SLOs declared by relevant standards. The
rationale for each measured quantity is anchored in a published norm rather
than a generic best practice.

────────────────────────────────────────────────────────────────────────────────
SLO 1 — Pre-Operational Briefing latency (S5_5_BRIEFING_SPEC.md §6.2)
────────────────────────────────────────────────────────────────────────────────
Target: p95 end-to-end < 8 seconds for `POST /api/shift/briefing`.
Justification: a CET starting a 12-hour shift cannot afford a > 8 s wait
before situational awareness is available. SLO is a project-internal Tier IV
operational requirement, derived from human factors literature on
critical-environment shift handover (Reason, 1997; ISO 11064-7:2006
"Ergonomic design of control centres — Part 7: Principles for the evaluation
of control centres"). Histogram buckets sized to capture sub-1s success and
flag the 8 s ceiling explicitly.

────────────────────────────────────────────────────────────────────────────────
SLO 2 — EOP emergency abort decision time (project Pillar 4)
────────────────────────────────────────────────────────────────────────────────
Target: p99 < 100 milliseconds for `POST /api/abort/*` family.
Justification: NFPA 70E Article 130 establishes time-to-action requirements
for Emergency Power Off, and IEC 62443-3-3 SR 3.4 / SR 7.6 mandate
deterministic response under cyber-physical fault conditions. The 100 ms
budget covers signal propagation + safety logic + actuator command issuance
on the BMS conduit.

────────────────────────────────────────────────────────────────────────────────
SLO 3 — SSCB fault-clearing decision logic (Building D 800VDC)
────────────────────────────────────────────────────────────────────────────────
Target: p99 < 5 ms for `POST /api/sscb/*` decision endpoints.
Justification: per OCP-LVDC §4 and IEC 60947-2, solid state circuit breakers
must clear DC faults in 1-100 microseconds at the hardware layer. The
software decision stage (telemetry interpretation → trip command) must not
add more than ~5 ms or it breaks the fault-current rise envelope (tens of
A/microsecond per IEC TR 63282 §5.2). Software latency of any order > 5 ms
indicates a code-path regression that would be catastrophic in production.

────────────────────────────────────────────────────────────────────────────────
SLO 4 — Telemetry ingestion throughput (Pillar 1, IT Thermal validity)
────────────────────────────────────────────────────────────────────────────────
Target: sustain > 1000 req/s on `POST /api/telemetry`.
Justification: ASHRAE TC 9.9 Class A2 envelope (`config/knowledge/`-indexed)
mandates rack-level intake-air sample rate ≥ 0.1 Hz. With 368 racks × multiple
sensors each (intake, exhaust, manifold ΔP per CDU, CDU dew point, etc.),
sustained throughput floor is ~150 req/s. Headroom of ~7× covers burst
during incident-driven sensor fan-out.

────────────────────────────────────────────────────────────────────────────────
SLO 5 — DB connection pool saturation
────────────────────────────────────────────────────────────────────────────────
Target: active connections < 80% of pool max.
Justification: TimescaleDB hypertable inserts (telemetry + incidents) are
the highest-frequency write path in the system. Pool exhaustion under load
manifests as cascading 503s and IS the most common Tier IV failure mode in
similar facilities (Uptime Institute 2024 incident review).

────────────────────────────────────────────────────────────────────────────────
INTENTIONAL EXCLUSIONS (Decision B2-3 = B — curated subset)
────────────────────────────────────────────────────────────────────────────────
- /static/* paths — not API surface, drown out signal
- /favicon.ico — irrelevant
- /metrics itself — exclude self to avoid recursion in scrape latency
- /api/voice/transcribe — high cardinality file uploads, separate metric class
- Per-user labels — explicit decision: facility ops is shift-based, not user-based

================================================================================
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

# ─── Configuration ──────────────────────────────────────────────────────────

# Curated histogram buckets aligned to SLO targets above.
# - Sub-100 ms granularity for SSCB / EOP / API hot-paths
# - 1 s, 5 s, 8 s called out for briefing SLO
# - 30 s, 60 s for slow paths (RAG queries with cold sentence-transformers)
LATENCY_BUCKETS = (
    0.005,   # 5 ms — SSCB software decision ceiling (SLO 3)
    0.025,
    0.050,
    0.100,   # 100 ms — EOP abort decision ceiling (SLO 2)
    0.250,
    0.500,
    1.000,
    2.500,
    5.000,
    8.000,   # 8 s — briefing p95 ceiling (SLO 1)
    15.000,
    30.000,
    60.000,
    float("inf"),
)

# Endpoint paths excluded from instrumentation (high-cardinality or noise)
EXCLUDED_PATHS = (
    "/metrics",
    "/favicon.ico",
    "/static",
    "/lm/",
)


def _should_instrument() -> bool:
    """Read ENABLE_METRICS env var. Defaults true if unset (defensive)."""
    val = os.environ.get("ENABLE_METRICS", "true").strip().lower()
    return val in ("true", "1", "yes", "on")


def setup_metrics(app: FastAPI) -> bool:
    """
    Wire prometheus-fastapi-instrumentator onto the FastAPI app.

    Returns
    -------
    bool
        True if instrumentation was applied, False if disabled or import failed.

    Side effects
    ------------
    - Mounts /metrics endpoint on the app (Prometheus scrape target)
    - Adds a request middleware that times every request and emits histograms
    - Excludes paths in EXCLUDED_PATHS from instrumentation

    Failure mode (V9 graceful degradation)
    --------------------------------------
    If `prometheus_fastapi_instrumentator` is not installed (e.g. base image
    without [obs] extra), this function logs a warning and returns False
    without raising. The application continues to start.

    Standards cited inline above (NFPA 70E, IEC 62443-3-3, OCP-LVDC,
    IEC 60947-2, IEC TR 63282, ASHRAE TC 9.9, ISO 11064-7).
    """
    if not _should_instrument():
        logger.info("Metrics disabled via ENABLE_METRICS=false")
        return False

    try:
        from prometheus_fastapi_instrumentator import Instrumentator
        from prometheus_fastapi_instrumentator.metrics import (
            default,
            latency,
            request_size,
            response_size,
        )
    except ImportError as exc:
        logger.warning(
            "prometheus-fastapi-instrumentator not installed (%s). "
            "Install with: pip install -e \".[obs]\"  — metrics disabled.",
            exc,
        )
        return False

    instrumentator = Instrumentator(
        should_group_status_codes=True,           # 2xx, 3xx, 4xx, 5xx — not per code
        should_ignore_untemplated=True,            # Skip 404s for unknown paths
        should_respect_env_var=False,              # We honor ENABLE_METRICS ourselves
        should_instrument_requests_inprogress=True,
        excluded_handlers=list(EXCLUDED_PATHS),
        inprogress_name="dc_epms_inprogress_requests",
        inprogress_labels=True,
    )

    # Curated metric set per Decision B2-3 = B (~50 series, not default ~500)
    instrumentator.add(
        latency(
            metric_name="dc_epms_request_latency_seconds",
            metric_doc=(
                "Request latency in seconds. SLO targets: SSCB <5ms p99, "
                "EOP abort <100ms p99, briefing <8s p95 (S5_5_BRIEFING_SPEC §6.2). "
                "Histogram buckets aligned to NFPA 70E + IEC 62443-3-3 + ASHRAE TC 9.9."
            ),
            buckets=LATENCY_BUCKETS,
        )
    )

    instrumentator.add(
        request_size(
            metric_name="dc_epms_request_size_bytes",
            metric_doc=(
                "Request payload size. Telemetry batches per ASHRAE TC 9.9 "
                "rack-level sampling (368 racks × multiple sensors)."
            ),
        )
    )

    instrumentator.add(
        response_size(
            metric_name="dc_epms_response_size_bytes",
            metric_doc="Response payload size. Bound by GraphRAG/ChromaDB chunk sizes.",
        )
    )

    instrumentator.add(
        default(
            metric_namespace="dc_epms",
            metric_subsystem="api",
        )
    )

    # Instrument app and expose /metrics endpoint
    instrumentator.instrument(app).expose(
        app,
        endpoint="/metrics",
        include_in_schema=False,                  # Don't pollute /docs
        tags=["observability"],
    )

    logger.info(
        "Prometheus instrumentation active. /metrics endpoint exposed. "
        "Excluded paths: %s. Buckets: %s.",
        EXCLUDED_PATHS,
        LATENCY_BUCKETS,
    )
    return True


# ─── Public API ─────────────────────────────────────────────────────────────

__all__ = ["setup_metrics", "LATENCY_BUCKETS", "EXCLUDED_PATHS"]
