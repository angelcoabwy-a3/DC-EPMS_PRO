"""
tests/test_metrics.py v2 — Metrics endpoint and instrumentation tests.

v2 FIX: Added clear_prometheus_registry fixture that runs before each test
to prevent ValueError: Duplicated timeseries in CollectorRegistry. The
Prometheus client library uses a process-global REGISTRY, so creating
multiple FastAPI apps in the same test session collides on metric names.

Per pytest best practices for Prometheus testing
(https://prometheus.github.io/client_python/multiprocess/) — also relevant
for single-process testing when fixture scope reuses the registry.

Per V9 Rule 3 (Multi-Agente Lógica + QA en paralelo): delivered alongside
backend/metrics_router.py in the same batch.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

# Module under test
from backend.metrics_router import (
    EXCLUDED_PATHS,
    LATENCY_BUCKETS,
    setup_metrics,
)

# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_prometheus_registry():
    """
    Clear all collectors from the global Prometheus REGISTRY before each test.

    The prometheus_client library uses a process-global registry. Without
    this cleanup, the second test that calls setup_metrics() crashes with:
        ValueError: Duplicated timeseries in CollectorRegistry

    autouse=True ensures every test gets a fresh registry without explicit
    parameter declarations.
    """
    # Snapshot collectors to remove (avoid mutation during iteration)
    collectors_to_remove = list(REGISTRY._collector_to_names.keys())
    for collector in collectors_to_remove:
        try:
            REGISTRY.unregister(collector)
        except KeyError:
            # Collector already gone — skip
            pass
    return
    # Post-test cleanup is optional; next test's autouse handles it


@pytest.fixture
def fresh_app() -> FastAPI:
    """Minimal FastAPI app for instrumentation tests (no main.py side effects)."""
    app = FastAPI(title="metrics-test")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/echo/{value}")
    def echo(value: str):
        return {"echoed": value}

    @app.get("/static/style.css")
    def static_excluded():
        return {"should_not_be_instrumented": True}

    return app


@pytest.fixture
def instrumented_client(fresh_app: FastAPI) -> TestClient:
    """App with metrics instrumentation applied."""
    setup_metrics(fresh_app)
    return TestClient(fresh_app)


# ─── Tests: configuration ───────────────────────────────────────────────────


class TestConfiguration:
    """Validates module-level constants align with Decision B2-3 = B."""

    def test_latency_buckets_include_slo_thresholds(self):
        """SLO-critical thresholds must be explicit histogram buckets."""
        # SSCB software decision ceiling (5 ms) — SLO 3
        assert 0.005 in LATENCY_BUCKETS, "5ms bucket missing for SSCB SLO"
        # EOP abort ceiling (100 ms) — SLO 2
        assert 0.100 in LATENCY_BUCKETS, "100ms bucket missing for EOP SLO"
        # Briefing p95 ceiling (8 s) — SLO 1
        assert 8.000 in LATENCY_BUCKETS, "8s bucket missing for briefing SLO"

    def test_latency_buckets_monotonic(self):
        """Buckets must be monotonically increasing for valid histogram."""
        finite = [b for b in LATENCY_BUCKETS if b != float("inf")]
        assert finite == sorted(finite), "buckets not monotonic"

    def test_excluded_paths_includes_static(self):
        """High-cardinality paths must be excluded per Decision B2-3."""
        assert "/static" in EXCLUDED_PATHS
        assert "/metrics" in EXCLUDED_PATHS  # Self-recursion guard
        assert "/favicon.ico" in EXCLUDED_PATHS


# ─── Tests: endpoint exposure ───────────────────────────────────────────────


class TestMetricsEndpoint:
    """The /metrics endpoint must be exposed in Prometheus exposition format."""

    def test_metrics_endpoint_exists(self, instrumented_client: TestClient):
        response = instrumented_client.get("/metrics")
        assert response.status_code == 200

    def test_metrics_endpoint_returns_prometheus_format(self, instrumented_client: TestClient):
        """Response should match Prometheus text exposition format."""
        # Generate a sample by hitting an instrumented endpoint
        instrumented_client.get("/api/health")
        response = instrumented_client.get("/metrics")
        body = response.text
        # Prometheus format: # HELP, # TYPE, then metric lines
        assert "# HELP" in body, "missing HELP comment lines (Prometheus format)"
        assert "# TYPE" in body, "missing TYPE comment lines (Prometheus format)"

    def test_metrics_namespace_dc_epms(self, instrumented_client: TestClient):
        """Custom metrics must use 'dc_epms' namespace."""
        # Generate at least 1 sample
        instrumented_client.get("/api/health")
        response = instrumented_client.get("/metrics")
        assert "dc_epms_" in response.text, "no dc_epms_* metric found in output"


# ─── Tests: instrumentation behavior ────────────────────────────────────────


class TestInstrumentation:
    """Curated metric set captures the right paths and ignores the wrong ones."""

    def test_api_calls_appear_in_metrics(self, instrumented_client: TestClient):
        """Hit a real API endpoint, verify it shows up in /metrics."""
        instrumented_client.get("/api/health")
        instrumented_client.get("/api/health")
        instrumented_client.get("/api/echo/test")

        metrics = instrumented_client.get("/metrics").text
        # Look for the API path in metric output
        assert "/api/health" in metrics or "api_health" in metrics, (
            "API path should be captured by histogram labels"
        )

    def test_static_paths_excluded(self, instrumented_client: TestClient):
        """Static paths must NOT pollute the metric series."""
        # Hit excluded path multiple times
        for _ in range(5):
            instrumented_client.get("/static/style.css")

        metrics = instrumented_client.get("/metrics").text
        # No static metric series should exist
        assert "/static/style.css" not in metrics

    def test_metrics_endpoint_self_excluded(self, instrumented_client: TestClient):
        """The /metrics endpoint must not instrument itself (recursion safety)."""
        # Multiple metrics scrapes
        for _ in range(3):
            instrumented_client.get("/metrics")

        metrics = instrumented_client.get("/metrics").text
        # Should not see /metrics path in observed values
        bucket_lines = [line for line in metrics.split("\n") if "_bucket" in line]
        for line in bucket_lines:
            assert '"/metrics"' not in line, "/metrics endpoint should be self-excluded"


# ─── Tests: env var control ─────────────────────────────────────────────────


class TestEnvironmentControl:
    """ENABLE_METRICS env var gates instrumentation per spec."""

    def test_disabled_when_env_var_false(self, fresh_app: FastAPI):
        with patch.dict(os.environ, {"ENABLE_METRICS": "false"}):
            result = setup_metrics(fresh_app)
            assert result is False
            # /metrics should NOT exist
            client = TestClient(fresh_app)
            response = client.get("/metrics")
            assert response.status_code == 404

    def test_disabled_when_env_var_zero(self, fresh_app: FastAPI):
        with patch.dict(os.environ, {"ENABLE_METRICS": "0"}):
            result = setup_metrics(fresh_app)
            assert result is False

    def test_enabled_by_default(self, fresh_app: FastAPI):
        # Remove the var entirely to verify default behavior
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ENABLE_METRICS", None)
            result = setup_metrics(fresh_app)
            assert result is True
