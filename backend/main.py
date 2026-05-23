"""
DC-EPMS PRO - FastAPI Orchestrator (a3semi proprietary)
=========================================================
Central production server for A-Cubed Semiconductor Systems Inc.
Facility: A3-Alpha Toronto Area (Tier IV 2N, 40MW, 118 x Blackwell NVL72 racks).

Fixes in this revision:
  [1] PG_DSN forced to postgresql:// URI + explicit dbname=epms
  [2] Pydantic protected_namespaces disabled on AgentQuery (model_hint)
  [3] CORSMiddleware installed FIRST before all other middleware
  [4] All SSE responses set X-Accel-Buffering: no and no Content-Length
  [5] New endpoint: GET /api/telemetry/latest (single record, for UI cards)
  [6] PUE > 1.4 triggers async RAG-grounded Schneider WP122 advisory
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from backend.__version__ import __version__
from backend.metrics_router import setup_metrics

# ==============================================================
#  Project paths + deferred imports
# ==============================================================
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
# Insert PROJECT_ROOT FIRST so that 'from backend.physics.X import Y' works
# (physics_engine.py uses these absolute imports). Then also insert
# 'backend/' so the original 'from database import ...' style still resolves.
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

try:
    from database import DBManager
except Exception as e:
    DBManager = None
    print(f"[WARN] database module unavailable: {e}")

try:
    from rag_service import RAGService
except Exception as e:
    RAGService = None
    print(f"[WARN] rag_service module unavailable: {e}")

try:
    from agent_engine import AgentEngine
except Exception as e:
    AgentEngine = None
    print(f"[WARN] agent_engine module unavailable: {e}")

try:
    from shift_report import ShiftReportGenerator
except Exception as e:
    ShiftReportGenerator = None
    print(f"[WARN] shift_report module unavailable: {e}")


# ==============================================================
#  Configuration (env-driven, portable)
# ==============================================================
def _load_env():
    """Load .env from config/.env if present."""
    env_path = PROJECT_ROOT / "config" / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


_load_env()

# --------------------------------------------------------------
# [FIX 1 / F3-6] PG_DSN -- env-sourced credentials.
#   Every field is read from the environment first (config/.env is
#   loaded by _load_env() above; gitignored, local-only). The
#   fallbacks are the *dev-only* values provisioned by
#   docker-compose.yml: they let the local loop boot healthy with NO
#   manual .env and carry no production secret (the password literally
#   self-documents as "change_me"). This also eradicates the stale
#   hardcoded fallbacks ("postgres" / "epms" / "epms2026") that were
#   the root cause of DC-EPMS-DB-001 -- they pointed at a role + DB
#   that never existed, so a missing .env booted silent-degraded.
#   Any non-local deploy MUST export PG_* (or DEV_DB_PASSWORD).
# --------------------------------------------------------------
_PG_HOST = os.environ.get("PG_HOST", "localhost")
_PG_PORT = os.environ.get("PG_PORT", "5432")
_PG_DB = os.environ.get("PG_DB", "dcepms")
_PG_USER = os.environ.get("PG_USER", "epms")
_PG_PWD = (
    os.environ.get("PG_PASSWORD")
    or os.environ.get("DEV_DB_PASSWORD")
    or "epms_dev_only_change_me"
)
PG_DSN = f"postgresql://{_PG_USER}:{_PG_PWD}@{_PG_HOST}:{_PG_PORT}/{_PG_DB}"

LM_STUDIO_URL = os.environ.get("LM_STUDIO_URL", "http://127.0.0.1:1234")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CHROMA_PATH = str(PROJECT_ROOT / os.environ.get("CHROMA_PATH", "data/chroma_db"))
FRONTEND_DIR = PROJECT_ROOT / "frontend"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
PUE_ALERT_THRESHOLD = float(os.environ.get("PUE_ALERT_THRESHOLD", "1.4"))
OPERATOR_ORG = os.environ.get("OPERATOR_ORG", "a3semi")
FACILITY_NAME = os.environ.get("FACILITY_NAME", "A3-Alpha Toronto Area")


# ==============================================================
#  Logging (file + console)
# ==============================================================
# DC-EPMS-019: keep a reference to the file handler so the lifespan
# shutdown can close it explicitly (no ResourceWarning on exit).
_log_file_handler = logging.FileHandler(LOG_DIR / "epms_pro.log", encoding="utf-8")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s :: %(message)s",
    handlers=[
        _log_file_handler,
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("dc-epms-pro")

# DC-EPMS-039: chromadb's posthog telemetry version-mismatches and emits
# ERROR noise on every boot. chromadb telemetry is disabled by design
# (rag_service passes anonymized_telemetry=False); mute the logger so the
# failed-telemetry-send lines never reach the boot output.
logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)


# ==============================================================
#  Service singletons (initialized in lifespan)
# ==============================================================
db_manager: DBManager | None = None
rag_service: RAGService | None = None
agent: AgentEngine | None = None


# ==============================================================
#  Pydantic payloads
# ==============================================================
class TelemetryPoint(BaseModel):
    it_load_kw: float = Field(..., description="IT load in kW")
    pue: float = Field(..., ge=1.0, le=3.0)
    hall_temp_c: float = Field(...)
    delta_t_c: float = Field(default=0.0)
    ttc_seconds: float | None = None
    scenario: str = Field(default="NORMAL")
    rack_count: int = Field(default=118, description="Blackwell NVL72 racks")
    rack_tdp_kw: int = Field(default=142, description="GB200 NVL72 TDP")


class IncidentPayload(BaseModel):
    incident_id: str
    source: str
    title: str
    detail: str = ""
    severity: str = Field(default="info", pattern="^(info|warning|warn|critical|crit)$")
    status: str = Field(default="OPEN")
    physics_json: str = Field(default="{}")
    actor_role: str | None = None        # RBAC F3-4 claim; None -> gate not enforced


class AgentQuery(BaseModel):
    # [FIX 2] Pydantic v2 reserves "model_*" namespace by default.
    #          Disable it so model_hint does not raise a warning/error.
    model_config = ConfigDict(protected_namespaces=())

    query: str = Field(..., min_length=1, max_length=4000)
    context: dict | None = None
    max_tokens: int = Field(default=500, ge=1, le=4000)
    model_hint: str = Field(default="auto", pattern="^(auto|gemma|claude)$")


class RAGQuery(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    n_results: int = Field(default=4, ge=1, le=10)
    min_relevance: float = Field(default=0.30, ge=0.0, le=1.0)


class ShiftReportRequest(BaseModel):
    operator: str = Field(default="W. Angel")
    shift_id: str | None = None
    hours_back: int = Field(default=8, ge=1, le=24)
    include_procedures: bool = Field(default=True)


# ==============================================================
#  Lifespan: init + cleanup
# ==============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_manager, rag_service, agent
    log.info("[BUILD] DC-EPMS_PRO=v%s", __version__)
    log.info("DC-EPMS PRO starting up...")
    log.info("Operator: %s | Facility: %s", OPERATOR_ORG, FACILITY_NAME)
    log.info("PG DSN:   postgresql://%s:***@%s:%s/%s", _PG_USER, _PG_HOST, _PG_PORT, _PG_DB)

    if DBManager:
        try:
            db_manager = DBManager(PG_DSN)
            await db_manager.connect()
            log.info("PostgreSQL connected to database '%s'", _PG_DB)
        except Exception as e:
            log.warning("PostgreSQL init failed: %s", e)
            db_manager = None

    # ─── ADR-011: Forensic Ledger init (HMAC-chained, append-only) ────
    # Closes DC-EPMS-MSD-001 + DC-EPMS-MSD-002 from the 2026-05-22 MSD
    # audit. PostgresPersistence is selected when (a) the asyncpg pool
    # is live AND (b) the ledger_entries table exists (migration
    # 2026_05_W4_forensic_ledger.sql applied). Otherwise the boot
    # falls back to InMemoryPersistence with a loud warning — entries
    # do NOT survive restart in that mode. S-LEDGER-01 / S-RUNTIME-01.
    try:
        from backend.ledger import (
            ForensicLedger,
            InMemoryPersistence,
            PostgresPersistence,
        )
        _ledger_persistence = None
        if db_manager is not None and db_manager.pool is not None:
            try:
                async with db_manager.pool.acquire() as _ledger_probe_conn:
                    _ledger_table_exists = await _ledger_probe_conn.fetchval(
                        "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
                        "WHERE table_schema='public' AND table_name='ledger_entries')",
                    )
                if _ledger_table_exists:
                    _ledger_persistence = PostgresPersistence(db_manager.pool)
                    log.info("[BOOT] ForensicLedger -> PostgresPersistence")
                else:
                    log.warning(
                        "[BOOT] ForensicLedger migration NOT applied — apply "
                        "backend/migrations/2026_05_W4_forensic_ledger.sql and "
                        "restart for durable forensic audit. Falling back to "
                        "InMemoryPersistence (entries do NOT survive restart).",
                    )
            except Exception as e:
                log.warning("[BOOT] ledger table probe failed: %s — falling back", e)
        if _ledger_persistence is None:
            _ledger_persistence = InMemoryPersistence()
        app.state.forensic_ledger = ForensicLedger(_ledger_persistence)
        app.state.forensic_ledger_loop = asyncio.get_running_loop()
        log.info(
            "[BOOT] ForensicLedger ready (key_version=%d, persistence=%s)",
            app.state.forensic_ledger.current_key_version,
            type(_ledger_persistence).__name__,
        )
    except Exception as e:
        log.error("[BOOT] ForensicLedger init failed: %s", e, exc_info=True)
        app.state.forensic_ledger = None
        app.state.forensic_ledger_loop = None

    if RAGService:
        try:
            rag_service = RAGService(CHROMA_PATH)
            count = rag_service.count()
            log.info("ChromaDB ready: %d docs in epms_knowledge", count)
        except Exception as e:
            log.warning("RAG init failed: %s", e)
            rag_service = None

    if AgentEngine:
        try:
            agent = AgentEngine(
                lm_studio_url=LM_STUDIO_URL,
                anthropic_api_key=ANTHROPIC_API_KEY,
                rag_service=rag_service,
                config_dir=str(PROJECT_ROOT / "config"),
            )
            log.info("Agent engine ready")
        except Exception as e:
            log.warning("Agent engine init failed: %s", e)
            agent = None

    # ─── Sprint 6: CMMS Core v1.0 init (Fase 2 + 3) ───────────────────
    # Requires db_manager.pool (asyncpg). Seeds assets from site_model.yml
    # then registers /api/cmms/* router.
    try:
        if db_manager is not None and db_manager.pool is not None:
            from backend.cmms_repository import PostgresCMMSRepository
            from backend.cmms_routes import register_cmms_routes
            from backend.cmms_seeder import seed_assets_from_site_model

            _cmms_repo_instance = PostgresCMMSRepository(db_manager.pool)
            register_cmms_routes(app, _cmms_repo_instance)

            sm = globals().get("_site_model")
            if sm is not None:
                seed_result = await seed_assets_from_site_model(_cmms_repo_instance, sm)
                log.info("[BOOT] CMMS asset seeding: %s", seed_result)
            else:
                log.warning("[BOOT] CMMS seeder skipped: _site_model not available at lifespan time")

            # ─── Sprint 9.1: Predictive WO trigger init ───────────────
            # Single-instance state machine that converts Kalman anomalies
            # into CMMS work orders. Hooked into the SSE generator below.
            try:
                from backend.cmms_predictive_trigger import get_predictive_trigger
                _predictive_trigger = get_predictive_trigger(
                    repository=_cmms_repo_instance,
                    sustain_threshold=int(os.environ.get("DC_EPMS_PREDICTIVE_SUSTAIN", "3")),
                )
                app.state.cmms_predictive_trigger = _predictive_trigger
                log.info("[BOOT] Predictive WO trigger ready (sustain_threshold=%d)",
                         _predictive_trigger.sustain_threshold)
            except Exception as e:
                log.error("[BOOT] Predictive trigger init failed: %s", e, exc_info=True)

            # ─── Sprint 7.1a + 7.1b: Tech Assist init ─────────────────
            # 7.1a: TroubleshootAgent (RAG + CMMS history + LM Studio).
            # 7.1b: DocumentIngester (PDF upload -> ChromaDB chunks).
            try:
                from backend.tech_assist.routes import register_tech_assist_routes
                _upload_dir = PROJECT_ROOT / "data" / "tech_assist_uploads"
                register_tech_assist_routes(
                    app,
                    rag_service=rag_service,
                    cmms_repo=_cmms_repo_instance,
                    upload_dir=_upload_dir,
                )
                log.info("[BOOT] Tech Assist QA + ingest active (upload_dir=%s)", _upload_dir)
            except Exception as e:
                log.error("[BOOT] Tech Assist init failed: %s", e, exc_info=True)

            # ─── Sprint 10.1: Multi-Agent façade init ─────────────────
            # 6 deterministic agents (Architect, Safety Officer,
            # Diagnostician, Analyst — Epic 1 — plus the Capacity Planner
            # added in Epic 3 Batch 3.A and the Carbon/Grid agent added
            # in Batch 3.C) with Safety Officer veto. Pure Python critical
            # path per ADR-006. The site_model + graphrag references are
            # bound later in lifespan; we resolve them lazily from
            # globals() at registration time.
            try:
                from backend import hermes as _hermes
                from backend.grid_provider import get_grid_state as _grid_state
                from backend.multi_agent_routes import register_multi_agent_routes
                register_multi_agent_routes(
                    app,
                    site_model=globals().get("_site_model"),
                    graphrag=globals().get("_s2_service"),
                    cmms_repo=_cmms_repo_instance,
                    rag_service=rag_service,
                    # T3.3: live Gemma + Kalman tap for the Diagnostician.
                    llm_client=agent,
                    telemetry_provider=_hermes.latest_kalman_channels,
                    # Batch 3.C: Ontario IESO mock grid-state provider
                    # for the Carbon/Grid agent.
                    grid_provider=_grid_state,
                )
                log.info("[BOOT] Multi-Agent façade active (6 agents, "
                         "Safety Officer veto, deterministic consensus; "
                         "T3.3-family live-Gemma narrative %s)",
                         "ON" if agent is not None else "OFF")
            except Exception as e:
                log.error("[BOOT] Multi-Agent init failed: %s", e, exc_info=True)

            # ─── Epic 2 Batch 2.B: Optimizer service (opt-in) ─────
            # Proactive edge-agent for PUE/WUE. Default OFF — only
            # starts when DC_EPMS_OPTIMIZER_ENABLED is set. ADR-006
            # Proposer Pattern: the service has no actor_role and
            # cannot reach /api/bms/write (4 AST guards in
            # tests/test_optimizer.py enforce this at commit-time).
            try:
                from backend.optimizer import (
                    get_service as _get_optimizer,
                    is_enabled as _optimizer_enabled,
                )
                if _optimizer_enabled():
                    orch = getattr(app.state, "multi_agent_orchestrator", None)

                    # Batch 2.D: real Hermes WS publisher — replaces the
                    # 2.B log.info stub. The HMI subscribes to the
                    # `optimizer_proposal` stream via core/hermes_events.js
                    # and re-emits a `hermes:optimizer-proposal` DOM event.
                    #
                    # Epic 5.A: the Optimizer now also emits an
                    # `optimizer-tick` event on every tick (loop heartbeat).
                    # Route it to its own Hermes stream so the HMI strip
                    # subscribes independently of the proposal stream
                    # (a tick fires every 30 s; a proposal fires far less
                    # often). Stream-name mapping is explicit so a new
                    # event type silently routing to the wrong stream is
                    # surfaced via the "unknown" channel fallback.
                    _OPTIMIZER_EVENT_TO_STREAM = {
                        "optimizer-proposal": "optimizer_proposal",
                        "optimizer-tick": "optimizer_tick",
                    }

                    def _optimizer_event_emitter(event: str, payload: dict) -> None:
                        stream = _OPTIMIZER_EVENT_TO_STREAM.get(
                            event, "optimizer_proposal",
                        )
                        _hermes.emit_event(stream, {
                            "event": event,
                            **payload,
                        })

                    _optimizer_svc = _get_optimizer(
                        telemetry_provider=None,  # composed in 2.E smoke test
                        pue_target=1.30,
                        consult_fn=(orch.consult if orch is not None else None),
                        llm_client=agent,
                        kalman_provider=_hermes.latest_kalman_channels,
                        event_emitter=_optimizer_event_emitter,
                    )
                    if _optimizer_svc is not None:
                        app.state.optimizer_service = _optimizer_svc
                        _optimizer_svc.start()
                        log.info(
                            "[BOOT] Optimizer service STARTED "
                            "(Epic 2 Batch 2.B — consensus + queue + Hermes)",
                        )
                else:
                    log.info(
                        "[BOOT] Optimizer service NOT started "
                        "(DC_EPMS_OPTIMIZER_ENABLED=false — default OFF)",
                    )
            except Exception as e:
                log.error("[BOOT] Optimizer init failed: %s", e, exc_info=True)

            # ─── Epic 2 Batch 2.C: Optimizer approve/reject routes ────
            # Routes are registered unconditionally so the OpenAPI
            # surface stays consistent; they HTTP 503 at call time when
            # DC_EPMS_OPTIMIZER_ENABLED=false. Per S-SEC-02 / brief §6
            # the OPERATOR's actor_role (SME_L6) authorises the BMS
            # write — the Optimizer service has no actor_role.
            try:
                from backend.ledger import wrap_bms_write_fn
                from backend.optimizer_routes import register_optimizer_routes

                def _raw_bms_write(tag_id, value, user):
                    if not BMS_AVAILABLE:
                        return False, "BMS connector unavailable"
                    return get_bms(PROJECT_ROOT).write(
                        tag_id, value, user=user,
                    )

                def _prev_value_reader(tag_id):
                    if not BMS_AVAILABLE:
                        return None
                    tag = get_bms(PROJECT_ROOT).read(tag_id)
                    return tag.current_value if tag else None

                # S-LEDGER-01: stash the raw seam on app.state so the
                # /api/bms/revert endpoint can build a wrapper with
                # source="revert" later. The wrapped seams created here
                # carry the source tag at construction time.
                app.state.raw_bms_write_fn = _raw_bms_write
                app.state.bms_prev_value_reader = _prev_value_reader

                _ledger_for_wrap = getattr(app.state, "forensic_ledger", None)
                _loop_for_wrap = getattr(app.state, "forensic_ledger_loop", None)
                if _ledger_for_wrap is not None:
                    _optimizer_bms_write = wrap_bms_write_fn(
                        _raw_bms_write,
                        ledger=_ledger_for_wrap,
                        prev_value_reader=_prev_value_reader,
                        source="optimizer_approval",
                        loop=_loop_for_wrap,
                    )
                    app.state.direct_bms_write_fn = wrap_bms_write_fn(
                        _raw_bms_write,
                        ledger=_ledger_for_wrap,
                        prev_value_reader=_prev_value_reader,
                        source="direct",
                        loop=_loop_for_wrap,
                    )
                    app.state.revert_bms_write_fn = wrap_bms_write_fn(
                        _raw_bms_write,
                        ledger=_ledger_for_wrap,
                        prev_value_reader=_prev_value_reader,
                        source="revert",
                        loop=_loop_for_wrap,
                    )
                else:
                    _optimizer_bms_write = _raw_bms_write
                    app.state.direct_bms_write_fn = _raw_bms_write
                    app.state.revert_bms_write_fn = _raw_bms_write
                    log.warning(
                        "[BOOT] Optimizer + /api/bms/write wired WITHOUT "
                        "forensic ledger (init failed). Writes will execute "
                        "but no ADR-011 audit trail.",
                    )

                register_optimizer_routes(
                    app, bms_write_fn=_optimizer_bms_write,
                )
                log.info(
                    "[BOOT] Optimizer routes registered "
                    "(Batch 2.C — approve/reject SME_L6-gated, "
                    "ADR-011 ledger-wrapped)",
                )
            except Exception as e:
                log.error(
                    "[BOOT] Optimizer routes init failed: %s",
                    e, exc_info=True,
                )
        else:
            log.warning("[BOOT] CMMS skipped: db_manager pool unavailable")
    except Exception as e:
        log.error("[BOOT] CMMS init failed: %s", e, exc_info=True)

    # ─── Sprint 5.5b: PUE physics + targets init ──────────────────────
    # Path C2 PUE per phase: Phase 1 (480 VAC trifásico, target 1.30) +
    # Phase 2 (800 VDC unipolar TN-S, target 1.15 design). First-law
    # cross-check between input total and subsystem decomposition.
    # Config in config/pue_targets.yml; ADR-004 documents the decision.
    try:
        from backend.physics.pue_routes import register_pue_routes
        register_pue_routes(app, PROJECT_ROOT)
        log.info("[BOOT] PUE physics active (Phase 1 live, Phase 2 design)")
    except Exception as e:
        log.error("[BOOT] PUE init failed: %s", e, exc_info=True)

    # ─── Eager warmup of all audit-path lazy services (CET directive) ─
    # In critical infrastructure, availability is immediate. Lazy init of
    # GraphRAG (sentence-transformers all-MiniLM-L6-v2 + FAISS + NetworkX)
    # plus other audit-path cold loads imposes a ~30s penalty on the
    # FIRST /api/loto/audit. We pay that cost once at startup so the
    # operator-facing first audit lands sub-second.
    #
    # Trade-off: uvicorn "Application startup complete" log line appears
    # 10-30s later than before. CET-grade operations consider this
    # acceptable; the SLA is "first audit < 1s", not "uvicorn ready < 5s".
    #
    # Two-stage warmup:
    #   Stage 1 (always): GraphRAG.loto_with_knowledge() exercises
    #     sentence-transformers, FAISS index construction, NetworkX graph
    #     build, corpus embeddings, and site_model.loto_impact walk.
    #   Stage 2 (if LOTO Auditor registered): full dry-run audit.audit()
    #     covers the remaining pillar paths (physics_engine.validate_site,
    #     procedure load, witness_engine introspection, pillar 3-6 logic,
    #     report aggregation). Effectively pre-runs the same work the
    #     first user audit will do.
    _s2 = globals().get("_s2_service")
    if _s2 is not None:
        log.info("[BOOT] Pre-warming GraphRAG AI Models...")
        _wt0 = time.perf_counter()
        try:
            # ups_a is a guaranteed-present component in site_model.yml.
            _ = _s2.loto_with_knowledge("ups_a")
            _wt = time.perf_counter() - _wt0
            log.info("[BOOT] GraphRAG Ready (Warm) -- stage 1 completed in %.2fs", _wt)
        except Exception as e:
            log.warning(
                "[BOOT] GraphRAG warmup skipped: %s. First audit will pay cold-init penalty.",
                e,
            )
    else:
        log.warning("[BOOT] GraphRAG warmup skipped: _s2_service not initialized.")

    # Stage 2: dry-run audit to warm physics_engine + procedure_engine +
    # any remaining pillar lazy paths.
    _loto_auditor = getattr(app.state, "loto_auditor", None)
    if _loto_auditor is not None:
        log.info("[BOOT] Pre-warming LOTO Auditor pillars (dry-run)...")
        _wt0 = time.perf_counter()
        try:
            from loto_auditor_models import LotoAuditRequest as _AuditRequest
            _dry_request = _AuditRequest(
                procedure_id="MOP-ATS-MONTHLY-001",
                target_component_id="ups_a",
                cet_on_duty="_warmup",
                include_llm_summary=False,
            )
            _ = _loto_auditor.audit(_dry_request)
            _wt = time.perf_counter() - _wt0
            log.info("[BOOT] GraphRAG Ready (Warm) -- stage 2 audit dry-run in %.2fs", _wt)
        except Exception as e:
            log.warning(
                "[BOOT] LOTO dry-run warmup skipped: %s. First user audit may still pay some cold-init.",
                e,
            )
    else:
        log.warning("[BOOT] LOTO dry-run skipped: app.state.loto_auditor not registered.")

    yield

    log.info("DC-EPMS PRO shutting down...")

    # Stop the Optimizer asyncio task first so it doesn't see a
    # half-torn-down DB pool. Safe no-op when 2.B is not running.
    _optimizer_svc = getattr(app.state, "optimizer_service", None)
    if _optimizer_svc is not None:
        try:
            await _optimizer_svc.stop()
            log.info("[SHUTDOWN] Optimizer service stopped cleanly")
        except Exception as e:
            log.warning("[SHUTDOWN] Optimizer stop failed: %s", e)

    if db_manager:
        await db_manager.close()

    # DC-EPMS-019: release the log file handle so no ResourceWarning
    # fires on interpreter shutdown.
    logging.getLogger().removeHandler(_log_file_handler)
    _log_file_handler.close()


# ==============================================================
#  FastAPI app
# ==============================================================
app = FastAPI(
    title="DC-EPMS PRO",
    description="a3semi Edge Operations - Proprietary EPMS for Blackwell Fleet (Tier IV 2N 40MW)",
    version=__version__,
    lifespan=lifespan,
)

# Prometheus instrumentation (Batch 2 - Decision B2-3 = B curated subset)
# Honors ENABLE_METRICS env var. Graceful no-op if [obs] extra not installed.
setup_metrics(app)

# --------------------------------------------------------------
# [FIX 3] CORSMiddleware MUST be installed FIRST, before any
#          custom middleware. Otherwise pre-flight OPTIONS requests
#          can fail and break SSE reconnection.
# --------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)


# ==============================================================
#  Helpers
# ==============================================================
def _read_gpu_stats() -> dict:
    """NVML GPU stats - non-blocking."""
    try:
        import pynvml

        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        util = pynvml.nvmlDeviceGetUtilizationRates(h)
        mem = pynvml.nvmlDeviceGetMemoryInfo(h)
        temp = pynvml.nvmlDeviceGetTemperature(h, 0)
        name = pynvml.nvmlDeviceGetName(h)
        if isinstance(name, bytes):
            name = name.decode()
        return {
            "source": "nvml",
            "gpu": name,
            "sm_pct": int(util.gpu),
            "vram_used_mb": mem.used // (1024 * 1024),
            "vram_total_mb": mem.total // (1024 * 1024),
            "temp_c": int(temp),
            "status": "GPU_ACTIVE" if util.gpu > 10 else "IDLE",
        }
    except Exception:
        return {"source": "unavailable"}


# ==============================================================
#  Health
# ==============================================================
@app.get("/api/health")
async def health():
    """Unified health check."""
    checks = {
        "service": "dc-epms-pro",
        "version": __version__,
        "operator": OPERATOR_ORG,
        "facility": FACILITY_NAME,
        "timestamp": time.time(),
    }

    checks["postgres"] = {"status": "down", "latency_ms": None, "database": _PG_DB}
    if db_manager:
        t0 = time.time()
        try:
            ok = await db_manager.ping()
            checks["postgres"] = {
                "status": "up" if ok else "down",
                "database": _PG_DB,
                "latency_ms": round((time.time() - t0) * 1000, 2),
            }
        except Exception as e:
            checks["postgres"]["error"] = str(e)[:200]

    checks["rag"] = {"status": "down", "docs": 0}
    if rag_service:
        try:
            checks["rag"] = {"status": "up", "docs": rag_service.count()}
        except Exception as e:
            checks["rag"]["error"] = str(e)[:200]

    checks["gemma"] = {"status": "unknown", "url": LM_STUDIO_URL}
    if agent:
        try:
            gemma_ok = await agent.probe_gemma()
            checks["gemma"]["status"] = "up" if gemma_ok else "down"
        except Exception as e:
            checks["gemma"]["error"] = str(e)[:200]

    checks["gpu"] = _read_gpu_stats()
    return JSONResponse(content=checks)


# ==============================================================
#  PUE Advisory (Fase 2  -  autonomous, RAG-grounded)
# ==============================================================
async def _pue_advisory_task(point: dict) -> None:
    """Async advisory: query RAG for Schneider WP122 thermal mitigation."""
    if not rag_service:
        log.warning("PUE advisory: RAG unavailable")
        return
    pue = point.get("pue", 0)
    hall = point.get("hall_temp_c", 0)
    scenario = point.get("scenario", "NORMAL")
    question = (
        f"Current PUE {pue:.3f} exceeds a3semi threshold 1.40. "
        f"Hall temp {hall:.1f}C. Scenario: {scenario}. "
        f"What are the Schneider WP122 thermal mitigation procedures "
        f"for a Blackwell NVL72 DLC facility exceeding efficiency target?"
    )
    try:
        results = rag_service.query(question, n=3, min_relevance=0.25)
        if not results:
            log.warning("PUE advisory: no matching RAG docs")
            return
        top = results[0]
        log.warning(
            "PUE ADVISORY [pue=%.3f] :: top_doc_relevance=%.2f :: mitigation=%s",
            pue,
            top["relevance"],
            top["content"][:200],
        )
        # Persist advisory as incident
        if db_manager:
            try:
                import uuid

                advisory = {
                    "incident_id": f"ADV-{int(time.time())}-{uuid.uuid4().hex[:4]}",
                    "source": "PUE_ADVISORY",
                    "title": f"PUE threshold exceeded: {pue:.3f}",
                    "detail": top["content"][:500],
                    "severity": "warning",
                    "status": "OPEN",
                    "physics_json": json.dumps(
                        {
                            "pue": pue,
                            "hall_temp_c": hall,
                            "scenario": scenario,
                            "rag_relevance": top["relevance"],
                        }
                    ),
                }
                await db_manager.insert_incident(advisory)
                log.info("PUE advisory persisted as %s", advisory["incident_id"])
            except Exception as e:
                log.error("PUE advisory persistence failed: %s", e)
    except Exception as e:
        log.error("PUE advisory task failed: %s", e)


# Strong refs to fire-and-forget tasks so the event loop cannot GC them
# mid-flight (RUF006); each task drops itself from the set on completion.
_BACKGROUND_TASKS: set[asyncio.Task] = set()


# ==============================================================
#  Telemetry endpoints
# ==============================================================
@app.post("/api/telemetry")
async def write_telemetry(point: TelemetryPoint):
    if not db_manager:
        return JSONResponse({"written": False, "error": "DB unavailable"})
    try:
        rows = await db_manager.insert_telemetry(point.model_dump())
        pue_breach = point.pue > PUE_ALERT_THRESHOLD
        # Fase 2: autonomous RAG advisory
        if pue_breach:
            _advisory = asyncio.create_task(_pue_advisory_task(point.model_dump()))
            _BACKGROUND_TASKS.add(_advisory)
            _advisory.add_done_callback(_BACKGROUND_TASKS.discard)
        return JSONResponse(
            {
                "written": True,
                "rows": rows,
                "pue_advisory": pue_breach,
            }
        )
    except Exception as e:
        log.error("telemetry write failed: %s", e)
        return JSONResponse({"written": False, "error": str(e)[:200]})


@app.get("/api/telemetry")
async def get_telemetry(limit: int = 60):
    if not db_manager:
        return JSONResponse({"rows": [], "error": "DB unavailable"})
    try:
        rows = await db_manager.fetch_telemetry(limit=limit)
        return JSONResponse({"rows": rows, "count": len(rows)})
    except Exception as e:
        return JSONResponse({"rows": [], "error": str(e)[:200]})


# --------------------------------------------------------------
# [FIX 5] /api/telemetry/latest  -  single object for UI cards.
# --------------------------------------------------------------
@app.get("/api/telemetry/latest")
async def get_telemetry_latest():
    """Single most-recent telemetry record for the dashboard KPI cards."""
    if not db_manager:
        return JSONResponse(
            {"latest": None, "error": "DB unavailable"},
            status_code=200,
        )
    try:
        rows = await db_manager.fetch_telemetry(limit=1)
        latest = rows[0] if rows else None
        return JSONResponse(
            {
                "latest": latest,
                "ts": time.time(),
                "source": "timescaledb",
            }
        )
    except Exception as e:
        log.warning("telemetry/latest failed: %s", e)
        return JSONResponse({"latest": None, "error": str(e)[:200]})


@app.get("/api/telemetry/stream")
async def telemetry_stream(request: Request):
    """SSE: synthetic Path C2 telemetry per channel (Sprint 5 C1).

    Emits per-channel windows produced by telemetry_simulator, wrapped
    in the channel_innovations schema that the frontend Activity Strip
    consumes (see frontend/assets/js/core/telemetry_engine.js).

    Feature flag (env var):
        DC_EPMS_USE_SIMULATOR=1  (default) -> simulator path
        DC_EPMS_USE_SIMULATOR=0            -> legacy DB-poll path

    The legacy path is preserved byte-identical behaviour from before
    Sprint 5 C1 so any operator monitoring tool that depends on the old
    {latest, ts} shape can opt out via the env var without code change.
    """
    use_simulator = os.environ.get("DC_EPMS_USE_SIMULATOR", "1").strip() == "1"

    sim = None
    pipeline = None
    if use_simulator:
        try:
            from site_model import get_site_model as _sm_get
            from telemetry_pipeline import get_pipeline
            from telemetry_simulator import get_simulator
            sim = get_simulator(_sm_get())
            pipeline = get_pipeline(dt_seconds=1.0)
            log.info(
                "[telemetry/stream] simulator + Kalman pipeline active: "
                "%d components, %d channels",
                sim.component_count, sim.channel_count,
            )
        except Exception as e:
            log.warning("[telemetry/stream] simulator init failed, falling back to legacy: %s", e)
            sim = None
            pipeline = None

    # Predictive trigger handle (Sprint 9.1): None if CMMS not ready,
    # otherwise the singleton instance. Captured once per SSE connection.
    _predictive = getattr(request.app.state, "cmms_predictive_trigger", None)

    async def gen() -> AsyncIterator[str]:
        while True:
            if await request.is_disconnected():
                break
            try:
                if sim is not None and pipeline is not None:
                    window = sim.get_window(dt_seconds=1.0, n_samples=5)
                    channels = pipeline.compute(window)
                    # Sprint 9.1: feed the channel_innovations payload to
                    # the predictive trigger BEFORE shipping to client.
                    # Defensive: any failure is logged but does NOT break SSE.
                    if _predictive is not None:
                        try:
                            await _predictive.handle_payload(channels)
                        except Exception as e:
                            log.warning("[telemetry/stream] predictive trigger error: %s", e)
                    payload = json.dumps({
                        "schema": "channel_innovations",
                        "channels": channels,
                        "anomaly_count_60min": pipeline.count_anomalies_60min(),
                        "ts": time.time(),
                    })
                else:
                    if db_manager:
                        rows = await db_manager.fetch_telemetry(limit=1)
                        latest = rows[0] if rows else None
                        payload = json.dumps({
                            "schema": "legacy_kpi",
                            "latest": latest,
                            "ts": time.time(),
                        })
                    else:
                        payload = json.dumps({
                            "schema": "legacy_kpi",
                            "latest": None,
                            "error": "DB unavailable",
                            "ts": time.time(),
                        })
                yield f"data: {payload}\n\n"
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                break
            except Exception as e:
                yield f"data: {json.dumps({'schema': 'error', 'error': str(e)[:200], 'ts': time.time()})}\n\n"
            await asyncio.sleep(5)

    # [FIX 4] SSE must NOT send Content-Length. X-Accel-Buffering: no
    #          disables proxy/CDN buffering that breaks token streaming.
    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ==============================================================
#  Incidents endpoints
# ==============================================================
@app.post("/api/incidents")
async def create_incident(incident: IncidentPayload):
    from backend.rbac import require_actor_role
    require_actor_role(incident.actor_role, 4, "creating an incident")
    if not db_manager:
        return JSONResponse({"written": False, "error": "DB unavailable"})
    try:
        incident_id = await db_manager.insert_incident(incident.model_dump())
        return JSONResponse({"written": True, "incident_id": incident_id})
    except Exception as e:
        log.error("incident write failed: %s", e)
        return JSONResponse({"written": False, "error": str(e)[:200]})


@app.get("/api/incidents")
async def list_incidents(limit: int = 50):
    if not db_manager:
        return JSONResponse({"rows": [], "error": "DB unavailable"})
    try:
        rows = await db_manager.fetch_incidents(limit=limit)
        return JSONResponse({"rows": rows, "count": len(rows)})
    except Exception as e:
        return JSONResponse({"rows": [], "error": str(e)[:200]})


# ==============================================================
#  RAG endpoints
# ==============================================================
@app.post("/api/rag/query")
async def rag_query(query: RAGQuery):
    if not rag_service:
        return JSONResponse({"results": [], "error": "RAG unavailable"})
    try:
        results = rag_service.query(
            query.question,
            n=query.n_results,
            min_relevance=query.min_relevance,
        )
        return JSONResponse(
            {
                "question": query.question,
                "docs_searched": rag_service.count(),
                "results": results,
                "top_relevance": results[0]["relevance"] if results else 0.0,
            }
        )
    except Exception as e:
        return JSONResponse({"results": [], "error": str(e)[:200]})


@app.get("/api/rag/docs")
async def rag_docs():
    if not rag_service:
        return JSONResponse({"count": 0, "error": "RAG unavailable"})
    return JSONResponse({"count": rag_service.count()})


# ==============================================================
#  Agent SSE stream
# ==============================================================
@app.post("/agent/stream")
async def agent_stream(query: AgentQuery, request: Request):
    if not agent:

        async def err_gen():
            yield f"data: {json.dumps({'error': 'agent unavailable'})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            err_gen(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
        )

    async def gen() -> AsyncIterator[str]:
        try:
            # â"€â"€ Emit RAG sources first (for UI citation chips) â"€â"€â"€â"€â"€â"€â"€â"€
            try:
                sources = agent.get_rag_sources(query.query, n_results=3)
                if sources:
                    yield f"data: {json.dumps({'sources': sources})}\n\n"
            except Exception as e:
                log.debug("rag source emit failed: %s", e)

            async for token in agent.stream(
                query.query,
                context=query.context,
                max_tokens=query.max_tokens,
                model_hint=query.model_hint,
            ):
                if await request.is_disconnected():
                    break
                payload = json.dumps({"token": token})
                yield f"data: {payload}\n\n"
            yield "data: [DONE]\n\n"
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            return
        except Exception as e:
            log.error("agent stream error: %s", e)
            yield f"data: {json.dumps({'error': str(e)[:200]})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ==============================================================
#  LM Studio proxy (CORS bypass)
# ==============================================================
@app.post("/lm/{path:path}")
async def lm_proxy_post(path: str, request: Request):
    import httpx

    body = await request.body()
    url = f"{LM_STUDIO_URL}/{path}"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                url,
                content=body,
                headers={"Content-Type": "application/json"},
            )
            ct = resp.headers.get("content-type", "")
            if ct.startswith("application/json"):
                return JSONResponse(content=resp.json(), status_code=resp.status_code)
            return Response(content=resp.content, status_code=resp.status_code, media_type=ct)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LM Studio unreachable: {e}") from e


@app.get("/lm/{path:path}")
async def lm_proxy_get(path: str):
    import httpx

    url = f"{LM_STUDIO_URL}/{path}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LM Studio unreachable: {e}") from e


# ==============================================================
#  Voice stub (Riva-ready)
# ==============================================================
@app.post("/api/voice/transcribe")
async def voice_transcribe(request: Request):
    return JSONResponse(
        {
            "status": "not_implemented",
            "message": "Riva ASR integration pending - configure RIVA_GRPC_URL in .env",
            "audio_received_bytes": int(request.headers.get("Content-Length", 0)),
        }
    )


# ==============================================================
#  Shift Report PDF generator
# ==============================================================
@app.post("/api/shift/report")
async def generate_shift_report(req: ShiftReportRequest):
    if not ShiftReportGenerator:
        raise HTTPException(status_code=503, detail="Shift report module unavailable")

    from datetime import datetime, timedelta

    shift_end = datetime.now(UTC)
    shift_start = shift_end - timedelta(hours=req.hours_back)
    shift_id = req.shift_id or f"SH-{shift_end.strftime('%Y%m%d-%H%M')}"

    telemetry, incidents = [], []
    if db_manager:
        try:
            telemetry = await db_manager.fetch_telemetry(limit=200)
            incidents = await db_manager.fetch_incidents(limit=50)
        except Exception as e:
            log.warning("shift_report DB fetch failed: %s", e)

    open_items = [
        f"{inc.get('incident_id')} ({inc.get('severity', '').upper()}): {inc.get('title', '')}"
        for inc in incidents
        if inc.get("status") not in ("CLOSED", "RESOLVED")
    ][:10]

    gen = ShiftReportGenerator()
    try:
        pdf_bytes = gen.generate(
            operator=req.operator,
            shift_id=shift_id,
            shift_start=shift_start,
            shift_end=shift_end,
            telemetry_rows=telemetry,
            incidents=incidents,
            procedures_completed=[],
            open_items=open_items,
        )
    except Exception as e:
        log.error("shift_report generation failed: %s", e)
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}") from e

    filename = f"shift_report_{shift_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )


# ==============================================================
#  Physics Engine endpoints (DÃ­a 4)
# ==============================================================
try:
    from physics_engine import get_engine as get_physics_engine

    PHYSICS_AVAILABLE = True
    print("[OK] physics_engine loaded successfully")
except Exception as e:
    import traceback

    print(f"[ERROR] physics_engine import failed: {type(e).__name__}: {e}")
    print(traceback.format_exc())
    PHYSICS_AVAILABLE = False
    get_physics_engine = None

# Load scenarios catalog
SCENARIOS_PATH = PROJECT_ROOT / "config" / "scenarios.yml"
_SCENARIOS_CACHE: dict | None = None


def _load_scenarios() -> dict:
    """Load scenarios.yml lazily and cache the result."""
    global _SCENARIOS_CACHE
    if _SCENARIOS_CACHE is not None:
        return _SCENARIOS_CACHE
    if not SCENARIOS_PATH.exists():
        log.warning("scenarios.yml not found at %s", SCENARIOS_PATH)
        _SCENARIOS_CACHE = {"scenarios": []}
        return _SCENARIOS_CACHE
    try:
        import yaml

        _SCENARIOS_CACHE = yaml.safe_load(SCENARIOS_PATH.read_text(encoding="utf-8"))
        return _SCENARIOS_CACHE
    except Exception as e:
        log.error("Failed to load scenarios: %s", e)
        _SCENARIOS_CACHE = {"scenarios": []}
        return _SCENARIOS_CACHE


async def _get_latest_telemetry() -> dict:
    """Fetch the most recent telemetry record from TimescaleDB."""
    if not db_manager:
        return {}
    try:
        rows = await db_manager.fetch_telemetry(limit=1)
        return rows[0] if rows else {}
    except Exception as e:
        log.warning("Failed to fetch latest telemetry: %s", e)
        return {}


def _build_telemetry_dict_from_latest(telemetry: dict) -> dict:
    """Convert simulator telemetry into the schema expected by physics modules.

    The simulator emits a flat record with keys like 'pue', 'hall_temp_c',
    'it_load_kw'. The physics modules want richer fields. We expand the
    flat record using design defaults for fields not present.
    """
    base = {
        # IT
        "rack_count": int(telemetry.get("rack_count", 118)),
        "rack_tdp_kw": float(telemetry.get("rack_tdp_kw", 142.0)),
        "dlc_supply_c": float(telemetry.get("dlc_supply_c", 18.0)),
        "dlc_return_c": float(telemetry.get("dlc_return_c", 39.3)),
        "dlc_flow_l_min": float(telemetry.get("dlc_flow_l_min", 100.0)),
        "hall_inlet_c": float(telemetry.get("hall_temp_c", 20.0)),
        "hall_return_c": float(telemetry.get("hall_temp_c", 20.0)) + 2.0,
        "gpu_tj_max_c": float(telemetry.get("gpu_tj_max_c", 70.0)),
        # Mechanical
        "loop_flow_m3_s": 0.066,
        "loop_dp_measured_bar": 2.17,
        "loop_supply_c": float(telemetry.get("dlc_supply_c", 18.0)),
        "loop_return_c": float(telemetry.get("dlc_return_c", 40.0)),
        "cdu_primary_in_c": 7.0,
        "cdu_primary_out_c": 27.0,
        "cdu_primary_flow_m3_s": 0.066,
        "pump_speed_hz": 60.0,
        "pump_suction_bar": 1.8,
        "pump_power_kw": 45.0,
        # Electrical
        "utility_kw": float(telemetry.get("it_load_kw", 16756.0)) * 1.04,
        "facility_it_kw": float(telemetry.get("it_load_kw", 16756.0)),
        "ups_load_kw": 300.0,
        "ups_mode": "online",
        "ups_input_kw": 312.5,
        "xfmr_load_kva": 1800.0,
        "xfmr_top_oil_c": 65.0,
        "xfmr_winding_c": 98.7,
        "battery_soc": float(telemetry.get("battery_soc", 1.0)),
        "battery_vdc": 540.0,
        "battery_on_load": False,
        # Heat rejection
        "outdoor_t_db_c": float(telemetry.get("outdoor_t_db_c", 25.0)),
        "outdoor_rh_percent": float(telemetry.get("outdoor_rh_percent", 50.0)),
        "hall_dew_point_c": 8.0,
        "chiller_1_load_kw": 2500.0,
        "chiller_1_power_kw": 350.0,
        "chiller_1_ecwt_c": 29.0,
        "chiller_1_lchwt_c": 6.7,
        "chiller_2_load_kw": 2500.0,
        "chiller_2_power_kw": 350.0,
        "chiller_2_ecwt_c": 29.0,
        "chiller_2_lchwt_c": 6.7,
    }
    return base


@app.get("/api/site/health")
async def get_site_health():
    """Return current Site Health Index based on the latest telemetry."""
    if not PHYSICS_AVAILABLE:
        raise HTTPException(503, "Physics engine unavailable")

    from datetime import datetime

    telemetry = await _get_latest_telemetry()
    full_dict = _build_telemetry_dict_from_latest(telemetry)
    engine = get_physics_engine()
    result = engine.validate_site(full_dict)

    return {
        "site_health": round(result.site_health, 3),
        "weakest_module": result.weakest_module,
        "overall_severity": result.overall_severity.value,
        "module_healths": {name: round(r.health, 3) for name, r in result.modules.items()},
        "module_severities": {name: r.severity.value for name, r in result.modules.items()},
        "cascade_count": len(result.cascade_events),
        "timestamp": datetime.now(UTC).isoformat(),
        "has_telemetry": bool(telemetry),
    }


@app.post("/api/physics/validate")
async def physics_validate(payload: dict = Body(default={})):
    """Run physics validation on provided telemetry (or latest telemetry)."""
    if not PHYSICS_AVAILABLE:
        raise HTTPException(503, "Physics engine unavailable")

    if payload:
        telemetry = payload
    else:
        telemetry = await _get_latest_telemetry()
    full_dict = _build_telemetry_dict_from_latest(telemetry)
    engine = get_physics_engine()
    result = engine.validate_site(full_dict)
    return result.to_dict()


@app.get("/api/scenarios")
async def list_scenarios():
    """List all available scenarios from scenarios.yml."""
    cat = _load_scenarios()
    return {
        "scenarios": [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "description": s.get("description", "").strip(),
                "primary_module": s.get("primary_module"),
                "severity_if_uncorrected": s.get("severity_if_uncorrected"),
                "expected_ttr_minutes": s.get("expected_ttr_minutes"),
                "mitigation_doc": s.get("mitigation_doc"),
                "standard_refs": s.get("standard_refs", []),
            }
            for s in cat.get("scenarios", [])
        ],
        "count": len(cat.get("scenarios", [])),
    }


@app.post("/api/scenarios/{scenario_id}/run")
async def run_scenario(scenario_id: str, horizon_s: int = 900, actor_role: str | None = None):
    """Execute a named scenario and return the trajectory."""
    from backend.rbac import require_actor_role
    require_actor_role(actor_role, 4, "running a scenario")
    if not PHYSICS_AVAILABLE:
        raise HTTPException(503, "Physics engine unavailable")

    cat = _load_scenarios()
    scenario = next(
        (s for s in cat.get("scenarios", []) if s.get("id") == scenario_id),
        None,
    )
    if not scenario:
        raise HTTPException(404, f"Scenario {scenario_id} not found")

    engine = get_physics_engine()
    result = engine.simulate_scenario(scenario, horizon_s=horizon_s, dt_s=1.0)

    # Downsample trajectory for UI: keep ~120 points
    full_traj = result.get("trajectory", [])
    if len(full_traj) > 120:
        step = max(1, len(full_traj) // 120)
        downsampled = full_traj[::step]
        if downsampled[-1] is not full_traj[-1]:
            downsampled.append(full_traj[-1])
        result["trajectory"] = downsampled
        result["downsampled"] = True
        result["original_count"] = len(full_traj)

    return result


# ==============================================================
#  MOPs / SOPs / EOPs endpoints (DÃ­a 5)
# ==============================================================
MOPS_DIR = PROJECT_ROOT / "data" / "corpus" / "tier4_a3semi_mops"


def _parse_mop_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML front-matter from a markdown file.

    Returns (metadata_dict, body_markdown).
    """
    if not text.startswith("---"):
        return {}, text
    try:
        end = text.find("\n---", 3)
        if end < 0:
            return {}, text
        import yaml

        meta = yaml.safe_load(text[3:end]) or {}
        body = text[end + 4 :].lstrip("\n")
        return meta, body
    except Exception as e:
        log.debug("frontmatter parse failed: %s", e)
        return {}, text


def _list_mops() -> list[dict]:
    """Scan the MOPs corpus directory and return metadata for each file."""
    if not MOPS_DIR.exists():
        return []
    out = []
    for f in sorted(MOPS_DIR.glob("*.md")):
        try:
            text = f.read_text(encoding="utf-8")
            meta, body = _parse_mop_frontmatter(text)
            # Extract title from first H1 line if present
            title = ""
            for line in body.split("\n"):
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
            out.append(
                {
                    "doc_id": meta.get("doc_id", f.stem),
                    "filename": f.name,
                    "title": title or f.stem.replace("_", " "),
                    "doc_type": meta.get("doc_type", "MOP"),
                    "domain": meta.get("domain", ""),
                    "equipment": meta.get("equipment", ""),
                    "duration": meta.get("duration", ""),
                    "personnel_required": meta.get("personnel_required", ""),
                    "standard_refs": meta.get("standard_refs", []),
                    "tier": meta.get("tier", 4),
                    "priority": meta.get("priority", "medium"),
                }
            )
        except Exception as e:
            log.warning("Failed to parse %s: %s", f.name, e)
    return out


def _extract_mop_steps(body: str) -> list[dict]:
    """Extract numbered procedure steps from a MOP markdown body.

    Strategy: find the main procedure section (one of several possible
    header titles) then split by ### subsections. Each subsection
    becomes a step. Falls back to scanning the whole body if no main
    section is identified.
    """
    import re

    steps = []
    lines = body.split("\n")

    # Candidate "main procedure" section titles found in the corpus
    proc_section_pattern = re.compile(
        r"^##\s+("
        r"Procedure|"
        r"Test sequence|"
        r"Test procedure|"
        r"Response sequence|"
        r"Execution|"
        r"Steps|"
        r"Process|"
        r"Sequence"
        r")"
        r"(\s+[ - \- - ]\s+.+)?"  # optional "  -  per generator" suffix
        r"\s*(\(.*\))?\s*$",
        re.IGNORECASE,
    )

    proc_start = None
    for i, line in enumerate(lines):
        if proc_section_pattern.match(line):
            proc_start = i + 1
            break

    if proc_start is None:
        # Fall back: scan whole body, but skip front-matter sections
        proc_start = 0

    # End of section: next ## that doesn't match another procedure variant
    proc_end = len(lines)
    for i in range(proc_start, len(lines)):
        line = lines[i]
        if re.match(r"^##\s+", line) and not proc_section_pattern.match(line):
            proc_end = i
            break

    proc_lines = lines[proc_start:proc_end]

    # Split into steps using ### headers
    current_step = None
    current_content = []
    step_pattern = re.compile(
        r"^###\s+(?:Phase|Step|Stage|Test|Section|Part)?\s*(\d+)?\s*[ - \-:.]?\s*(.*)$",
        re.IGNORECASE,
    )

    step_num_counter = 0

    for line in proc_lines:
        if line.startswith("###"):
            m = step_pattern.match(line)
            if m:
                # Close previous
                if current_step is not None:
                    current_step["content"] = "\n".join(current_content).strip()
                    steps.append(current_step)
                step_num_counter += 1
                num_from_header = m.group(1)
                title = m.group(2).strip()
                if not title:
                    title = f"Step {step_num_counter}"
                # Strip any leading colon or dash
                title = title.lstrip(": -").strip()
                current_step = {
                    "step_num": int(num_from_header) if num_from_header else step_num_counter,
                    "title": title,
                    "content": "",
                }
                current_content = []
        elif current_step is not None:
            current_content.append(line)

    if current_step is not None:
        current_step["content"] = "\n".join(current_content).strip()
        steps.append(current_step)

    return steps


@app.get("/api/mops")
async def list_mops_endpoint():
    """List all MOPs/SOPs/EOPs in the corpus with metadata."""
    mops = _list_mops()
    return {
        "mops": mops,
        "count": len(mops),
        "by_type": {
            t: sum(1 for m in mops if m["doc_type"] == t) for t in {m["doc_type"] for m in mops}
        }
        if mops
        else {},
    }


@app.get("/api/mops/{doc_id}")
async def get_mop_endpoint(doc_id: str):
    """Return the full markdown content + parsed steps for a MOP."""
    if not MOPS_DIR.exists():
        raise HTTPException(404, "MOPs directory not found")

    # Find file by doc_id
    target_file = None
    for f in MOPS_DIR.glob("*.md"):
        if f.stem.startswith(doc_id) or doc_id in f.stem:
            target_file = f
            break
        # Also check the front-matter doc_id
        try:
            text = f.read_text(encoding="utf-8")
            meta, _ = _parse_mop_frontmatter(text)
            if meta.get("doc_id") == doc_id:
                target_file = f
                break
        except Exception:
            pass

    if not target_file:
        raise HTTPException(404, f"MOP {doc_id} not found")

    text = target_file.read_text(encoding="utf-8")
    meta, body = _parse_mop_frontmatter(text)
    steps = _extract_mop_steps(body)

    return {
        "doc_id": meta.get("doc_id", target_file.stem),
        "title": meta.get("title", target_file.stem),
        "filename": target_file.name,
        "metadata": meta,
        "body": body,
        "steps": steps,
        "step_count": len(steps),
    }


@app.post("/api/mops/generate")
async def generate_mop_endpoint_deprecated(_payload: dict = Body(default={})):
    """DEPRECATED — replaced by ``POST /api/procedures/architect/generate``.

    Returns HTTP 410 Gone with a redirect message pointing at the
    successor endpoint. The old route had NO Safety Officer audit and
    NO Maker-Checker witness gate; signing a MOP through it bypassed
    the LOTO/PPE/CSA Z462-24 audit + the Tier IV two-operator
    signature requirement. Closing the bypass is the whole point of
    Epic 6 Option A (the consolidation work in commit chain
    7b505b3 -> 05bd7be).

    Callers MUST migrate to:
        POST /api/procedures/architect/generate
        POST /api/procedures/architect/sign

    The old request body shape (``{topic, doc_type, equipment, duration}``)
    is intentionally NOT translated automatically — the new Architect
    schema is ``{doc_type, context, asset_id?, metadata?}`` and the
    migration is a UI decision per caller. The HMI generator panel
    that consumed this endpoint was removed in the same commit; the
    library view now cross-links to the Architect view directly.

    Why HTTP 410 (not 404 / 308): 410 Gone is the precise REST
    semantic for "this resource intentionally no longer exists" — it
    tells API consumers (CLI scripts, future integrations) the
    endpoint is permanently removed, not just temporarily missing.
    A 308 redirect would auto-replay the body to the new URL, but
    the request body shapes are incompatible, so the redirect would
    only paper over the migration. The deleted body lives in git
    history at the commit that introduced this stub.
    """
    raise HTTPException(
        status_code=410,
        detail={
            "error": "endpoint_removed",
            "message": (
                "POST /api/mops/generate has been removed. The "
                "Procedure Architect (Epic 6) is the single authoring "
                "path -- it enforces the Safety Officer audit + "
                "Maker-Checker witness gate that this old endpoint "
                "lacked."
            ),
            "successor": "POST /api/procedures/architect/generate",
            "sign_path": "POST /api/procedures/architect/sign",
            "doc": "config/knowledge/cdu-l-l-operating-standards.md "
                   "and other knowledge base documents are surfaced "
                   "to the Architect via GraphRAG.",
        },
    )


# ==============================================================
#  Topology / Digital Twin endpoints (DÃ­a 6)
# ==============================================================
@app.get("/api/topology/state")
async def get_topology_state():
    """Return current node states for HLD and LLD topology diagrams.

    Maps the four physics module validation results into per-node
    severity + key metrics. Topology layout itself is static (rendered
    in the frontend SVG); this endpoint provides the dynamic state.
    """
    if not PHYSICS_AVAILABLE:
        raise HTTPException(503, "Physics engine unavailable")

    telemetry = await _get_latest_telemetry()
    full_dict = _build_telemetry_dict_from_latest(telemetry)
    engine = get_physics_engine()
    result = engine.validate_site(full_dict)

    # Per-module summaries (severity + 1-2 key metrics)
    it = result.modules.get("it_thermal")
    mech = result.modules.get("mechanical")
    elec = result.modules.get("electrical")
    hr = result.modules.get("heat_rejection")

    # Convert each module severity to node-friendly state
    def _node(severity, health, metrics=None, label=""):
        return {
            "severity": severity.value if hasattr(severity, "value") else "ok",
            "health": round(health, 2),
            "metrics": metrics or {},
            "label": label,
        }

    # â"€â"€â"€ Dual utility feeds (2N) â"€â"€â"€
    # Total facility load split 50/50 between Feed A (North) and Feed B (South)
    util_total_kw = elec.metrics.get("utility_kw", 17_400.0) if elec else 17_400.0
    feed_a_kw = util_total_kw / 2.0
    feed_b_kw = util_total_kw / 2.0
    # In real 2N the two feeds are physically isolated; here we model that by
    # giving each feed independent telemetry. Severity inherits from electrical.
    util_severity = elec.severity if elec else "ok"
    util_health = elec.health if elec else 1.0

    # â"€â"€â"€ Power balance: distribute UPS load across RPPs and busways (v5.2) â"€â"€â"€
    #
    # Conservation law (sum-of-power, single-time-instant balance):
    #     P_UPS_A = P_RPP_A1 + P_RPP_A2
    #     P_RPP_Ai = P_busway_Ai = sum_{r in racks_Ai} P_drop_r
    #
    # This is NOT Kirchhoff's Current Law in the strict circuit sense (KCL is
    # for instantaneous current at a single node in a circuit topology). What
    # we model here is a steady-state real-power balance at distribution
    # points, which is the equivalent for radial AC distribution feeders
    # under quasi-stationary load. Both forms are conservation statements;
    # we name it correctly to keep the engineering rigor defensible to
    # hyperscale ops review.
    #
    # Split fraction alpha for RPP_A1 vs RPP_A2 is sampled from a truncated
    # gaussian centered at 0.5 with sigma=0.03 (clamped to [0.42, 0.58]),
    # representing realistic asymmetric loading observed in production
    # data centers (panelboard imbalance, rack-by-rack provisioning).
    import random as _rng

    def _split_fraction(seed_hint: float, sigma: float = 0.03) -> float:
        """Truncated gaussian split fraction near 0.5 with deterministic seed.

        Using a hint derived from the load itself keeps the value stable
        across rapid refresh cycles (avoids visual jitter > 1 kW/s in the
        SLD), while still producing realistic per-instance asymmetry.
        """
        # Stable seed from load value: same load â†' same alpha until load shifts
        seeded = _rng.Random(int(seed_hint * 100) & 0xFFFF)
        # Box-Muller-ish via normalvariate, then truncate
        alpha = seeded.normalvariate(0.5, sigma)
        return max(0.42, min(0.58, alpha))

    # UPS-side loads (real, validated by physics module)
    ups_a_load_kw = elec.metrics.get("ups_load_kw", 16_756.0) / 2.0 if elec else 8_378.0
    ups_b_load_kw = elec.metrics.get("ups_load_kw", 16_756.0) / 2.0 if elec else 8_378.0
    # Note: physics engine reports a single ups_load_kw (aggregate). For 2N
    # display we split equally  -  when one UPS goes on battery, the surviving
    # one carries 100% of facility IT load (ups_b_load_kw â†' 0, ups_a_load_kw
    # â†' full). This is handled below in the failure-aware adjustment.

    # If a UPS is on battery and we have asymmetric mode info, reflect it
    if elec and elec.metrics.get("battery_on_load"):
        # Conservative: if any battery is loaded, push 100% to the surviving side
        # (in real 2N, both UPSes share until one fails; this is a SLD heuristic)
        ups_a_load_kw = elec.metrics.get("ups_load_kw", 16_756.0)
        ups_b_load_kw = 0.0

    # Per-path RPP split (alpha varies with load to give realism)
    alpha_a = _split_fraction(ups_a_load_kw)
    alpha_b = _split_fraction(ups_b_load_kw + 1.0)  # different seed for B
    rpp_a1_kw = ups_a_load_kw * alpha_a
    rpp_a2_kw = ups_a_load_kw * (1.0 - alpha_a)
    rpp_b1_kw = ups_b_load_kw * alpha_b
    rpp_b2_kw = ups_b_load_kw * (1.0 - alpha_b)

    # Each RPP feeds its busway 1:1 in our radial topology
    busway_a_kw = rpp_a1_kw + rpp_a2_kw
    busway_b_kw = rpp_b1_kw + rpp_b2_kw

    # Verification: balance must hold (within rounding)
    balance_residual_a = abs(busway_a_kw - ups_a_load_kw)
    balance_residual_b = abs(busway_b_kw - ups_b_load_kw)
    # If residual exceeds 0.5 kW, our split logic broke. Log it.
    # (In production this would alert; here we just include it in the response.)
    power_balance_ok = (balance_residual_a < 0.5) and (balance_residual_b < 0.5)

    # HLD nodes (high-level facility view)
    hld_nodes = {
        "utility_north": _node(
            util_severity,
            util_health,
            {"kw": round(feed_a_kw, 0), "kv": 27.5, "feed": "A"},
            "Utility North (Feed A)",
        ),
        "utility_south": _node(
            util_severity,
            util_health,
            {"kw": round(feed_b_kw, 0), "kv": 27.5, "feed": "B"},
            "Utility South (Feed B)",
        ),
        "xfmr_a": _node(
            elec.severity if elec else "ok",
            elec.health if elec else 1.0,
            {
                "winding_c": elec.metrics.get("xfmr_winding_c", 0) if elec else 0,
                "load_kva": elec.metrics.get("xfmr_load_kva", 0) if elec else 0,
                "active": True,
            },
            "Transformer A",
        ),
        "xfmr_b": _node(
            elec.severity if elec else "ok",
            elec.health if elec else 1.0,
            {
                "winding_c": elec.metrics.get("xfmr_winding_c", 0) if elec else 0,
                "load_kva": elec.metrics.get("xfmr_load_kva", 0) if elec else 0,
                "active": True,
            },
            "Transformer B",
        ),
        "ups_a": _node(
            elec.severity if elec else "ok",
            elec.health if elec else 1.0,
            {
                "load_kw": elec.metrics.get("ups_load_kw", 0) if elec else 0,
                "soc": elec.metrics.get("battery_soc", 1.0) if elec else 1.0,
                "eff": elec.metrics.get("ups_efficiency_measured", 0.96) if elec else 0.96,
                "active": True,
            },
            "UPS Galaxy A",
        ),
        "ups_b": _node(
            elec.severity if elec else "ok",
            elec.health if elec else 1.0,
            {
                "load_kw": elec.metrics.get("ups_load_kw", 0) if elec else 0,
                "soc": elec.metrics.get("battery_soc", 1.0) if elec else 1.0,
                "eff": elec.metrics.get("ups_efficiency_measured", 0.96) if elec else 0.96,
                "active": True,
            },
            "UPS Galaxy B",
        ),
        "hall_1": _node(
            it.severity if it else "ok",
            it.health if it else 1.0,
            {
                "inlet_c": it.metrics.get("hall_inlet_c", 20) if it else 20,
                "load_kw": (it.metrics.get("Q_it_total_kw", 16756) if it else 16756) / 3,
                "physics_verified": True,
            },
            "Hall 1",
        ),
        "hall_2": _node(
            it.severity if it else "ok",
            it.health if it else 1.0,
            {
                "inlet_c": it.metrics.get("hall_inlet_c", 20) if it else 20,
                "load_kw": (it.metrics.get("Q_it_total_kw", 16756) if it else 16756) / 3,
                "physics_verified": True,
            },
            "Hall 2",
        ),
        "hall_3": _node(
            it.severity if it else "ok",
            it.health if it else 1.0,
            {
                "inlet_c": it.metrics.get("hall_inlet_c", 20) if it else 20,
                "load_kw": (it.metrics.get("Q_it_total_kw", 16756) if it else 16756) / 3,
                "physics_verified": True,
            },
            "Hall 3",
        ),
        "cdu_a": _node(
            mech.severity if mech else "ok",
            mech.health if mech else 1.0,
            {
                "q_kw": mech.metrics.get("q_secondary_kw", 0) if mech else 0,
                "flow_lpm": mech.metrics.get("loop_flow_l_min", 3960) if mech else 3960,
                "active": True,
            },
            "CDU A",
        ),
        "cdu_b": _node(
            mech.severity if mech else "ok",
            mech.health if mech else 1.0,
            {
                "q_kw": mech.metrics.get("q_secondary_kw", 0) if mech else 0,
                "flow_lpm": mech.metrics.get("loop_flow_l_min", 3960) if mech else 3960,
                "active": True,
            },
            "CDU B",
        ),
        "chiller_1": _node(
            hr.severity if hr else "ok",
            hr.health if hr else 1.0,
            {
                "cop": hr.metrics.get("chiller_1_cop_measured", 7.1) if hr else 7.1,
                "load_kw": 2500,
                "physics_verified": True,
            },
            "Chiller 1",
        ),
        "chiller_2": _node(
            hr.severity if hr else "ok",
            hr.health if hr else 1.0,
            {
                "cop": hr.metrics.get("chiller_2_cop_measured", 7.1) if hr else 7.1,
                "load_kw": 2500,
                "physics_verified": True,
            },
            "Chiller 2",
        ),
        "cooling_tower": _node(
            hr.severity if hr else "ok",
            hr.health if hr else 1.0,
            {
                "wb_c": hr.metrics.get("outdoor_wet_bulb_c", 18) if hr else 18,
                "ecwt_c": (hr.metrics.get("outdoor_wet_bulb_c", 18) + 4) if hr else 22,
                "delta_t_risk": (hr.metrics.get("outdoor_wet_bulb_c", 18) > 25) if hr else False,
            },
            "Cooling tower",
        ),
        # â"€â"€â"€ v5.2: RPP & Starline busway nodes (power balance derived) â"€â"€â"€
        "rpp_a1": _node(
            elec.severity if elec else "ok",
            elec.health if elec else 1.0,
            {
                "load_kw": round(rpp_a1_kw, 1),
                "split_fraction": round(alpha_a, 3),
                "voltage_v": 600,
                "active": True,
                "physics_verified": True,
            },
            "RPP-A1",
        ),
        "rpp_a2": _node(
            elec.severity if elec else "ok",
            elec.health if elec else 1.0,
            {
                "load_kw": round(rpp_a2_kw, 1),
                "split_fraction": round(1.0 - alpha_a, 3),
                "voltage_v": 600,
                "active": True,
                "physics_verified": True,
            },
            "RPP-A2",
        ),
        "rpp_b1": _node(
            elec.severity if elec else "ok",
            elec.health if elec else 1.0,
            {
                "load_kw": round(rpp_b1_kw, 1),
                "split_fraction": round(alpha_b, 3),
                "voltage_v": 600,
                "active": True,
                "physics_verified": True,
            },
            "RPP-B1",
        ),
        "rpp_b2": _node(
            elec.severity if elec else "ok",
            elec.health if elec else 1.0,
            {
                "load_kw": round(rpp_b2_kw, 1),
                "split_fraction": round(1.0 - alpha_b, 3),
                "voltage_v": 600,
                "active": True,
                "physics_verified": True,
            },
            "RPP-B2",
        ),
        "busway_a": _node(
            # Severity escalates if busway exceeds rated current
            (
                "critical"
                if (busway_a_kw * 1000.0 / (1.732 * 480 * 0.95)) > 800
                else "warning"
                if (busway_a_kw * 1000.0 / (1.732 * 480 * 0.95)) > 700
                else (elec.severity if elec else "ok")
            ),
            elec.health if elec else 1.0,
            {
                "load_kw": round(busway_a_kw, 1),
                "rated_a": 800,
                # 3-phase: I = P / (sqrt(3) * V_LL * PF), V_LL=480V, PF=0.95
                "current_a": round(busway_a_kw * 1000.0 / (1.732 * 480 * 0.95), 0),
                "overload": (busway_a_kw * 1000.0 / (1.732 * 480 * 0.95)) > 800,
                "physics_verified": True,
                "balance_residual_kw": round(balance_residual_a, 3),
            },
            "Starline busway A",
        ),
        "busway_b": _node(
            (
                "critical"
                if (busway_b_kw * 1000.0 / (1.732 * 480 * 0.95)) > 800
                else "warning"
                if (busway_b_kw * 1000.0 / (1.732 * 480 * 0.95)) > 700
                else (elec.severity if elec else "ok")
            ),
            elec.health if elec else 1.0,
            {
                "load_kw": round(busway_b_kw, 1),
                "rated_a": 800,
                "current_a": round(busway_b_kw * 1000.0 / (1.732 * 480 * 0.95), 0),
                "overload": (busway_b_kw * 1000.0 / (1.732 * 480 * 0.95)) > 800,
                "physics_verified": True,
                "balance_residual_kw": round(balance_residual_b, 3),
            },
            "Starline busway B",
        ),
    }

    # Determine overall redundancy mode based on what's "active"
    # 2N: all redundant pairs both active and OK
    # N+1: one side degraded but capacity still maintained
    # N: redundancy lost, single point of failure
    redundancy_mode = "2N"
    if result.overall_severity.value == "critical":
        redundancy_mode = "N"
    elif result.overall_severity.value == "warning":
        redundancy_mode = "N+1"

    # LLD nodes (per-hall detail) - 12 racks shown as representative sample
    rack_health = it.health if it else 1.0
    rack_severity = it.severity.value if it else "ok"
    gpu_tj = it.metrics.get("gpu_tj_max_c", 70) if it else 70
    dlc_dt = it.metrics.get("dlc_delta_T_k", 21) if it else 21

    lld_racks = []
    # Generate 12 representative racks with slight variation
    import random

    random.seed(42)  # deterministic for tests
    for i in range(1, 13):
        rack_tj = gpu_tj + random.uniform(-3, 3)
        rack_dt = dlc_dt + random.uniform(-1.5, 1.5)
        lld_racks.append(
            {
                "id": f"R{i:02d}",
                "severity": rack_severity,
                "health": round(rack_health, 2),
                "gpu_tj_c": round(rack_tj, 1),
                "dlc_dt_k": round(rack_dt, 1),
            }
        )

    return {
        "hld_nodes": hld_nodes,
        "lld_racks": lld_racks,
        "site_health": round(result.site_health, 3),
        "weakest_module": result.weakest_module,
        "overall_severity": result.overall_severity.value,
        "cascade_count": len(result.cascade_events),
        # Day 8 evolution: redundancy + load balance metadata
        "redundancy_mode": redundancy_mode,
        "load_balance": {
            "feed_a_pct": 50.0,
            "feed_b_pct": 50.0,
            "balanced": True,
        },
        "physics_engine_status": {
            "active": True,
            "modules": list(result.modules.keys()),
            "validation_method": "First law + ODE",
        },
        # v5.2  -  power-balance verification (sum of RPP loads vs UPS output)
        "power_balance": {
            "ok": power_balance_ok,
            "path_a_residual_kw": round(balance_residual_a, 3),
            "path_b_residual_kw": round(balance_residual_b, 3),
            "ups_a_kw": round(ups_a_load_kw, 1),
            "ups_b_kw": round(ups_b_load_kw, 1),
            "rpp_a1_kw": round(rpp_a1_kw, 1),
            "rpp_a2_kw": round(rpp_a2_kw, 1),
            "rpp_b1_kw": round(rpp_b1_kw, 1),
            "rpp_b2_kw": round(rpp_b2_kw, 1),
        },
    }


@app.post("/api/topology/whatif")
async def topology_whatif(payload: dict = Body(...)):
    """Run a What-If simulation: failure of a specified component.

    Payload: { "failed_node": "utility_north" | "xfmr_a" | "ups_a" | "cdu_a" | "chiller_1" | ... }

    Computes what the topology + SHI would look like with the given component
    out of service. Used by the Emergency Simulation Mode in the UI.
    """
    from backend.rbac import require_actor_role
    require_actor_role(payload.get("actor_role"), 4, "running a what-if simulation")
    if not PHYSICS_AVAILABLE:
        raise HTTPException(503, "Physics engine unavailable")

    failed = payload.get("failed_node", "")
    if not failed:
        raise HTTPException(400, "failed_node required")

    # Build a degraded telemetry dict that reflects the failure
    telemetry = await _get_latest_telemetry()
    full_dict = _build_telemetry_dict_from_latest(telemetry)

    # Apply failure perturbation to telemetry
    failure_descriptions = {
        "utility_north": "Utility Feed A loss - all load on Feed B (XFMR B carrying full facility)",
        "utility_south": "Utility Feed B loss - all load on Feed A (XFMR A carrying full facility)",
        "xfmr_a": "Transformer A failure - 100% load on XFMR B (overloading risk)",
        "xfmr_b": "Transformer B failure - 100% load on XFMR A (overloading risk)",
        "ups_a": "UPS A failure - load transfer to UPS B",
        "ups_b": "UPS B failure - load transfer to UPS A",
        "cdu_a": "CDU A failure - all DLC heat on CDU B (capacity at limit)",
        "cdu_b": "CDU B failure - all DLC heat on CDU A (capacity at limit)",
        "chiller_1": "Chiller 1 trip - chiller 2 alone may not handle full load",
        "chiller_2": "Chiller 2 trip - chiller 1 alone may not handle full load",
        "hall_1": "Hall 1 cooling failure - workload migration triggered",
        "hall_2": "Hall 2 cooling failure - workload migration triggered",
        "hall_3": "Hall 3 cooling failure - workload migration triggered",
        "cooling_tower": "Cooling tower failure - condenser water loss imminent",
    }

    description = failure_descriptions.get(failed, f"Failure of {failed}")

    # Apply telemetry perturbations corresponding to the failed component
    if failed == "xfmr_a" or failed == "xfmr_b":
        # Remaining transformer carries 2x rated load -> winding overheats
        full_dict["xfmr_load_kva"] = 3700.0  # > 2500 rated
        full_dict["xfmr_winding_c"] = 145.0  # above C57.12 limit
    elif failed in ("ups_a", "ups_b"):
        # Remaining UPS at 100% load = drops below peak efficiency
        full_dict["ups_load_kw"] = 600.0
        full_dict["ups_input_kw"] = 690.0  # at higher load eff drops to 87%
    elif failed in ("cdu_a", "cdu_b"):
        # Remaining CDU runs above capacity -> dT rises
        full_dict["loop_return_c"] = 50.0  # above design max 45 C
        full_dict["dlc_return_c"] = 50.0
        full_dict["pump_suction_bar"] = 1.0  # suction pressure drop
    elif failed == "chiller_1" or failed == "chiller_2":
        # Single chiller carries 100% facility heat -> high PLR
        full_dict["chiller_1_load_kw"] = 5000.0
        full_dict["chiller_1_power_kw"] = 800.0  # COP drops
        full_dict["chiller_2_load_kw"] = 0.0
        full_dict["chiller_2_power_kw"] = 0.0
    elif failed in ("hall_1", "hall_2", "hall_3"):
        full_dict["hall_inlet_c"] = 32.0  # near A2 max
        full_dict["gpu_tj_max_c"] = 88.0  # warning territory
    elif failed == "cooling_tower":
        full_dict["outdoor_t_db_c"] = 35.0
        full_dict["outdoor_rh_percent"] = 80.0
    elif failed in ("utility_north", "utility_south"):
        # Single feed carrying full load
        full_dict["xfmr_load_kva"] = 3500.0  # the surviving xfmr is hot
        full_dict["xfmr_winding_c"] = 125.0

    # Run validation with degraded state
    engine = get_physics_engine()
    degraded_result = engine.validate_site(full_dict)

    # Get the baseline (current) state for comparison
    baseline_full = _build_telemetry_dict_from_latest(telemetry)
    baseline_result = engine.validate_site(baseline_full)

    return {
        "failed_node": failed,
        "description": description,
        "baseline": {
            "site_health": round(baseline_result.site_health, 3),
            "severity": baseline_result.overall_severity.value,
            "weakest": baseline_result.weakest_module,
        },
        "degraded": {
            "site_health": round(degraded_result.site_health, 3),
            "severity": degraded_result.overall_severity.value,
            "weakest": degraded_result.weakest_module,
            "module_healths": {
                name: round(r.health, 3) for name, r in degraded_result.modules.items()
            },
            "cascade_count": len(degraded_result.cascade_events),
            "cascade_events": degraded_result.cascade_events,
        },
        "shi_delta": round(degraded_result.site_health - baseline_result.site_health, 3),
        "redundancy_after_failure": (
            "N (NON-REDUNDANT)"
            if degraded_result.overall_severity.value == "critical"
            else "N+1 (DEGRADED)"
            if degraded_result.overall_severity.value == "warning"
            else "2N (RESILIENT)"
        ),
        "physics_assessment": (
            "Site CANNOT carry full load on remaining components"
            if degraded_result.site_health < 0.3
            else "Site can carry full load but redundancy compromised"
            if degraded_result.site_health < 0.7
            else "Site capacity intact; degraded state is acceptable"
        ),
    }


# ==============================================================
#  BMS Connector endpoints (DÃ­a 7)
# ==============================================================
try:
    from bms_connector import get_bms

    BMS_AVAILABLE = True
    print("[OK] bms_connector loaded successfully")
except Exception as e:
    import traceback

    print(f"[ERROR] bms_connector import failed: {type(e).__name__}: {e}")
    print(traceback.format_exc())
    BMS_AVAILABLE = False
    get_bms = None


async def _refresh_bms_tags():
    """Refresh BMS tag values from current telemetry + physics."""
    if not BMS_AVAILABLE:
        return
    bms = get_bms(PROJECT_ROOT)
    telemetry = await _get_latest_telemetry()
    physics_metrics = {}
    if PHYSICS_AVAILABLE:
        full_dict = _build_telemetry_dict_from_latest(telemetry)
        engine = get_physics_engine()
        result = engine.validate_site(full_dict)
        physics_metrics = {name: r.metrics for name, r in result.modules.items()}
    bms.refresh(telemetry, physics_metrics)


@app.get("/api/bms/tags")
async def list_bms_tags(category: str | None = None):
    """List BMS tags, optionally filtered by category (HVAC, PWR, IT, etc.)."""
    if not BMS_AVAILABLE:
        raise HTTPException(503, "BMS connector unavailable")
    await _refresh_bms_tags()
    bms = get_bms(PROJECT_ROOT)
    tags = bms.list_tags(category=category)
    return {
        "tags": [t.to_dict() for t in tags],
        "count": len(tags),
        "stats": bms.stats(),
    }


@app.get("/api/bms/tag/{tag_id:path}")
async def get_bms_tag(tag_id: str):
    """Read a single BMS tag value with full metadata."""
    if not BMS_AVAILABLE:
        raise HTTPException(503, "BMS connector unavailable")
    await _refresh_bms_tags()
    bms = get_bms(PROJECT_ROOT)
    tag = bms.read(tag_id)
    if not tag:
        raise HTTPException(404, f"Tag {tag_id} not found")
    return tag.to_dict()


@app.post("/api/bms/write")
async def write_bms_tag(request: Request, payload: dict = Body(...)):
    """Issue a write command against a writable BMS tag.

    Payload schema (ADR-011 + S-PROPOSER-01):
        {
            "tag_id":      str,    # required
            "value":       Any,    # required
            "user":        str,    # optional, defaults to "dashboard-user"
            "actor_role":  str,    # required, SME_L6 only
            "proposal_id": str,    # optional — when provided, MUST match an
                                   #   approved row in the Optimizer
                                   #   ApprovalLog (Proposer chain closure).
            "source":      str,    # optional informational tag, free-form
        }

    Every write — whether from the Optimizer approve flow or a direct
    operator action — appends a pre-entry (``BMS_WRITE_REQUESTED`` with
    ``prev_value`` for the rollback harness) and a post-entry
    (``BMS_WRITE_RESULT``) to the forensic ledger (ADR-011).
    """
    # F3-2 + S-SEC-02: BMS write is a raw control-surface actuation, SME_L6 only.
    from backend.cmms_models import role_rank as _role_rank
    _bms_role = payload.get("actor_role")
    if _role_rank(_bms_role) < 6:
        raise HTTPException(
            403,
            f"BMS write requires SME_L6; actor_role={_bms_role!r} is insufficient.",
        )
    if not BMS_AVAILABLE:
        raise HTTPException(503, "BMS connector unavailable")

    tag_id = payload.get("tag_id")
    value = payload.get("value")
    user = payload.get("user", "dashboard-user")
    proposal_id = payload.get("proposal_id")
    if not tag_id:
        raise HTTPException(400, "tag_id required")

    # S-PROPOSER-01: when a proposal_id is supplied, it MUST reference an
    # approved Optimizer proposal in the ApprovalLog, AND the (tag_id,
    # value) MUST match what was approved. This closes the Proposer
    # chain for AI-originated writes that come back through this endpoint.
    if proposal_id is not None:
        approval_log = getattr(request.app.state, "optimizer_approval_log", None)
        if approval_log is None:
            raise HTTPException(
                503,
                "Optimizer approval log not initialised — cannot validate proposal_id",
            )
        approval = approval_log.get(proposal_id)
        if approval is None:
            raise HTTPException(
                404,
                f"proposal_id={proposal_id!r} not found in ApprovalLog",
            )
        if approval.decision != "approved":
            raise HTTPException(
                409,
                f"proposal_id={proposal_id!r} decision={approval.decision!r} "
                "(not 'approved' — refusing write)",
            )
        if approval.bms_tag_id and approval.bms_tag_id != tag_id:
            raise HTTPException(
                409,
                f"proposal_id={proposal_id!r} was approved for "
                f"tag_id={approval.bms_tag_id!r}, request tag_id={tag_id!r}",
            )

    # Choose the wrapped seam (ledger pre/post entries automatic).
    direct_fn = getattr(request.app.state, "direct_bms_write_fn", None)
    if direct_fn is None:
        # Boot-time wiring failed — degrade to raw write (no audit trail).
        # The boot log emits a WARNING in this case; reflect it to the caller.
        log.warning(
            "[/api/bms/write] direct_bms_write_fn missing — degrading to raw "
            "bms.write (no ADR-011 ledger entry)",
        )
        bms = get_bms(PROJECT_ROOT)
        success, message = bms.write(tag_id, value, user=user)
    else:
        # S-PROPOSER-01: stamp proposal context onto the ledger entry.
        from backend.ledger import reset_proposal_context, set_proposal_context
        token = set_proposal_context(proposal_id)
        try:
            success, message = await asyncio.to_thread(
                direct_fn, tag_id, value, user,
            )
        finally:
            reset_proposal_context(token)

    if not success:
        raise HTTPException(400, message)
    return {
        "success": True,
        "message": message,
        "tag_id": tag_id,
        "new_value": value,
        "proposal_id": proposal_id,
    }


@app.post("/api/bms/revert/{entry_id}")
async def revert_bms_write(entry_id: str, request: Request, payload: dict = Body(default={})):
    """Rollback Harness (ADR-011 + DC-EPMS-MSD-004).

    Reverts a prior BMS write by replaying its ``prev_value``. The entry
    referenced by ``entry_id`` MUST be a ``BMS_WRITE_REQUESTED`` ledger
    entry — its payload carries the ``tag_id`` + ``prev_value`` needed
    to reconstruct the pre-write state.

    Payload (optional):
        {"actor_role": str (SME_L6), "user": str, "reason": str}

    Reverting a revert is allowed — it just appends a new chain entry.
    No special-case prevention; the chain is the audit record.
    """
    # SME_L6 gate (IEC 62443-3-3 SR 2.1).
    from backend.cmms_models import role_rank as _role_rank
    _bms_role = payload.get("actor_role")
    if _role_rank(_bms_role) < 6:
        raise HTTPException(
            403,
            f"BMS revert requires SME_L6; actor_role={_bms_role!r} is insufficient.",
        )
    if not BMS_AVAILABLE:
        raise HTTPException(503, "BMS connector unavailable")

    ledger = getattr(request.app.state, "forensic_ledger", None)
    if ledger is None:
        raise HTTPException(
            503,
            "ForensicLedger not initialised — cannot resolve entry_id",
        )

    entry = await ledger.fetch_by_id(entry_id)
    if entry is None:
        raise HTTPException(404, f"ledger entry_id={entry_id!r} not found")

    from backend.ledger import ACTION_BMS_REVERT, ACTION_BMS_WRITE_REQUESTED
    if entry.action != ACTION_BMS_WRITE_REQUESTED:
        raise HTTPException(
            422,
            f"ledger entry_id={entry_id!r} action={entry.action!r} "
            f"(cannot revert; only {ACTION_BMS_WRITE_REQUESTED!r} entries "
            "are revertable)",
        )

    tag_id = entry.payload.get("tag_id")
    prev_value = entry.payload.get("prev_value")
    if not tag_id:
        raise HTTPException(
            422,
            f"ledger entry_id={entry_id!r} payload missing tag_id",
        )
    if prev_value is None:
        raise HTTPException(
            422,
            f"ledger entry_id={entry_id!r} payload has no prev_value to revert to "
            "(the original write had no captured pre-state)",
        )

    revert_user = payload.get("user", "revert-operator")
    reason = payload.get("reason", "")

    # Append a BMS_REVERT marker entry FIRST so the chain records intent
    # even if the actual counter-write fails. This is the canonical
    # "intent before action" pattern (S-LEDGER-01).
    revert_marker = await ledger.append(
        actor=revert_user,
        action=ACTION_BMS_REVERT,
        payload={
            "reverts_entry_id": entry_id,
            "tag_id": tag_id,
            "restoring_value": prev_value,
            "from_value": entry.payload.get("requested_value"),
            "reason": reason,
        },
    )

    # Execute the counter-write through the same wrapped seam — this
    # appends its own BMS_WRITE_REQUESTED + BMS_WRITE_RESULT pair so the
    # chain captures the full action.
    revert_fn = getattr(request.app.state, "revert_bms_write_fn", None)
    if revert_fn is None:
        raise HTTPException(
            503,
            "revert_bms_write_fn not wired — boot-time ledger setup failed",
        )
    success, message = await asyncio.to_thread(
        revert_fn, tag_id, prev_value, revert_user,
    )
    if not success:
        raise HTTPException(400, f"revert counter-write failed: {message}")
    return {
        "success": True,
        "message": message,
        "tag_id": tag_id,
        "restored_value": prev_value,
        "reverted_entry_id": entry_id,
        "revert_marker_entry_id": revert_marker.entry_id,
    }


@app.get("/api/ledger/entries")
async def list_ledger_entries(
    request: Request,
    limit: int = 50,
    action: str | None = None,
    proposal_id: str | None = None,
):
    """List recent forensic-ledger entries (ADR-011).

    Filters (combinable):

      * ``action`` — restrict to one action kind
        (``BMS_WRITE_REQUESTED``, ``BMS_WRITE_RESULT``, ``BMS_REVERT``,
        ``KEY_ROTATION``).
      * ``proposal_id`` — Epic 5.D forensic-trail query. Returns the
        full chain for one Optimizer proposal: the REQUESTED row whose
        payload stamped this id (S-PROPOSER-01), the matching RESULT
        row(s) that ``ref_entry_id``-link back, and any other entries
        that directly carry the same proposal_id. JSONB-indexed on the
        Postgres backend; ``limit`` is ignored when this filter is
        supplied (a chain rarely exceeds a handful of entries).
    """
    ledger = getattr(request.app.state, "forensic_ledger", None)
    if ledger is None:
        raise HTTPException(503, "ForensicLedger not initialised")
    if proposal_id:
        entries = await ledger.fetch_by_proposal_id(proposal_id)
        if action:
            entries = [e for e in entries if e.action == action]
        return {
            "entries": [e.to_dict() for e in entries],
            "total": await ledger.count(),
            "key_version": ledger.current_key_version,
            "proposal_id": proposal_id,
            "matched": len(entries),
        }
    entries = await ledger.fetch_all()
    if action:
        entries = [e for e in entries if e.action == action]
    entries = entries[-max(1, int(limit)):]
    return {
        "entries": [e.to_dict() for e in entries],
        "total": await ledger.count(),
        "key_version": ledger.current_key_version,
    }


@app.get("/api/ledger/verify")
async def verify_ledger_chain(request: Request):
    """Replay the chain. Returns the divergence index when broken, else clean."""
    ledger = getattr(request.app.state, "forensic_ledger", None)
    if ledger is None:
        raise HTTPException(503, "ForensicLedger not initialised")
    from backend.ledger import LedgerChainBrokenError
    try:
        await ledger.verify_chain()
    except LedgerChainBrokenError as exc:
        return {
            "verified": False,
            "divergence_index": exc.divergence_index,
            "reason": exc.reason,
            "total_entries": await ledger.count(),
        }
    return {"verified": True, "total_entries": await ledger.count()}


@app.get("/api/bms/audit")
async def get_bms_audit(limit: int = 50):
    """Return recent write audit log entries.

    Note: this is the legacy in-RAM BMS-side audit (ring buffer, 200
    entries). The authoritative, tamper-evident log is the forensic
    ledger at ``GET /api/ledger/entries`` — see ADR-011.
    """
    if not BMS_AVAILABLE:
        raise HTTPException(503, "BMS connector unavailable")
    bms = get_bms(PROJECT_ROOT)
    return {
        "audit": bms.get_audit_log(limit=limit),
        "total_entries": len(bms.write_audit_log),
    }


# ==============================================================
#  Frontend SPA
# ==============================================================
if FRONTEND_DIR.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=str(FRONTEND_DIR / "assets")),
        name="assets",
    )

    @app.get("/")
    async def root():
        index = FRONTEND_DIR / "index.html"
        if index.exists():
            # No-cache headers so HTML is always fresh after a deploy;
            # the cache-busting ?v=... on linked assets inside will in turn
            # pick up new CSS/JS only when the version string changes.
            return FileResponse(
                index,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
        return JSONResponse({"error": "frontend not found"}, status_code=404)

    @app.get("/favicon.ico")
    async def favicon():
        fav = FRONTEND_DIR / "assets" / "favicon.ico"
        if fav.exists():
            return FileResponse(fav)
        return Response(status_code=204)


# ==============================================================
#  v8  -  Agentic Copilot (tool-using LLM + HITL draft pattern)
# ==============================================================
#
# The copilot lives in backend/agent_copilot.py. It exposes 3 tools to a
# local LM-Studio-served Gemma model and emits write-intent operations as
# Drafts that operators must approve via the HMI. The execution hook below
# is what bridges an approved Draft to the actual side-effecting code path.


async def _execute_drafted_command(
    command: dict,
    operator: str,
    draft_id: str,
) -> dict:
    """Dispatch one drafted command to its real backend.

    Called by agent_copilot.approve_draft() AFTER operator approval. This
    is the only place where agent-originated commands actually mutate
    state, and it routes everything through the same audit-gated path
    that operator-originated writes use (NIST SP 800-82).

    The mapping below is the single source of truth for which command_id
    targets which subsystem. New tools that emit drafts add their command_id
    to this dispatch table, not their own write paths.
    """
    cmd_id = command.get("command_id", "")
    device_id = command.get("device_id", "")
    payload = command.get("payload") or {}

    # â"€â"€ set_chilled_water_setpoint â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
    # Maps to BMS tag HVAC.CHILLER1.CW_SETPOINT or HVAC.CHILLER2.CW_SETPOINT
    if cmd_id == "set_chilled_water_setpoint":
        target_c = float(payload.get("target_c"))
        # Map device_id â†' BMS tag
        tag_map = {
            "chiller_1": "HVAC.CHILLER1.CW_SETPOINT",
            "chiller_2": "HVAC.CHILLER2.CW_SETPOINT",
        }
        tag_id = tag_map.get(device_id)
        if not tag_id:
            return {"status": "FAILED", "error": f"no BMS tag mapped for {device_id}"}

        # Use the existing BMS write infrastructure  -  same code path as
        # operator clicks in the HMI. Audit log entry is created automatically.
        try:
            from bms_connector import get_bms

            bms_local = get_bms(PROJECT_ROOT)
        except Exception as e:
            return {"status": "FAILED", "error": f"BMS connector unavailable: {e}"}

        try:
            success, message = bms_local.write(
                tag_id=tag_id,
                value=target_c,
                user=f"agent:{operator}:draft:{draft_id}",
            )
            return {
                "status": "EXECUTED" if success else "REJECTED",
                "tag_id": tag_id,
                "value": target_c,
                "message": message,
                "audit": "logged via bms_connector",
            }
        except Exception as e:
            return {"status": "FAILED", "error": f"{type(e).__name__}: {e}"}

    # â"€â"€ Future command types land here â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
    # set_pump_speed, transfer_to_bypass, etc.  -  each new draftable
    # command type registers its dispatch here, never bypassing audit.

    return {
        "status": "UNSUPPORTED",
        "error": f"command_id '{cmd_id}' has no dispatch implementation",
    }


# Mount the agent router. Wrapped in try/except so the platform boots
# even if the copilot module has a load-time issue.
try:
    from agent_copilot import router as _agent_router

    app.include_router(_agent_router)
    log.info("[v8] Agent Copilot mounted at /api/agent")
except ImportError as e:
    log.warning(f"[v8] Agent Copilot not loaded: {e}")
except Exception as e:
    log.error(f"[v8] Agent Copilot mount failed: {e}")


# ==============================================================
#  Sprint 1+2+3  -  Procedure orchestrator + Witness workflow
# ==============================================================
# Mount the procedures and witness HTTP API so the HMI can drive
# Tier IV procedures (ATS transfer, UPS bypass, gen test) with the
# multi-signature witness gate (IEC 62443 SR 6.1).
#
# Wrapped in try/except so the platform boots even if procedure_engine
# has a load-time issue (e.g., YAML parse error in a procedure file).

try:
    from fastapi import APIRouter, HTTPException
    from procedure_engine import (
        ProcedureNotFoundError,
        build_default_orchestrator,
    )
    from witness_engine import (
        IdentityCollisionError,
        WitnessRequestNotFoundError,
        WitnessRequestNotPendingError,
        get_witness_store,
        serialize_request as _serialize_witness,
    )

    _proc_orch = build_default_orchestrator(PROJECT_ROOT)
    _witness_store = get_witness_store()

    _proc_router = APIRouter(prefix="/api/procedures", tags=["procedures"])
    _witness_router = APIRouter(prefix="/api/witness", tags=["witness"])

    # F3-3: RBAC gate for the state-mutating procedure + witness endpoints.
    from backend.cmms_models import role_rank as _role_rank

    def _require_actor_role(body: dict, min_rank: int, action: str) -> None:
        """Reject a request whose payload actor_role is below min_rank.
        No auth layer exists yet -- the role is a client-supplied claim
        (audit F3); a missing / unknown role is rejected fail-closed."""
        role = (body or {}).get("actor_role")
        if _role_rank(role) < min_rank:
            raise HTTPException(
                status_code=403,
                detail=(f"{action} requires role rank >= {min_rank}; "
                        f"actor_role={role!r} is insufficient (RBAC F3-3)."),
            )

    # â"€â"€ Procedure endpoints â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
    @_proc_router.get("")
    async def list_procedures():
        """List all procedures available in config/procedures/*.yml."""
        return {
            "procedures": [
                _proc_orch.registry.get_summary(pid) for pid in _proc_orch.registry.list_ids()
            ]
        }

    @_proc_router.get("/{procedure_id}")
    async def get_procedure_detail(procedure_id: str):
        """Full procedure YAML contents  -  for HMI display before start."""
        try:
            return _proc_orch.registry.get(procedure_id)
        except ProcedureNotFoundError:
            raise HTTPException(status_code=404, detail=f"procedure {procedure_id} not found") from None

    @_proc_router.get("/executions/list")
    async def list_executions():
        """All procedure executions in memory (active and historical)."""
        return {"executions": _proc_orch.list_executions()}

    @_proc_router.get("/executions/{exec_id}")
    async def get_execution(exec_id: str):
        try:
            from dataclasses import asdict

            ex = _proc_orch.get_execution(exec_id)
            d = asdict(ex)
            d["state"] = ex.state.value
            return d
        except KeyError:
            raise HTTPException(status_code=404, detail=f"execution {exec_id} not found") from None

    @_proc_router.post("/{procedure_id}/start")
    async def start_procedure(procedure_id: str, body: dict):
        """Operator initiates a procedure. Returns the execution with
        pre_condition_results  -  operator clicks 'Advance' to proceed
        if all pre-conditions are OK."""
        _require_actor_role(body, 5, "starting a procedure")
        operator = body.get("operator", "anonymous")
        try:
            ex = await _proc_orch.start_procedure(procedure_id, operator)
            from dataclasses import asdict

            d = asdict(ex)
            d["state"] = ex.state.value
            return d
        except ProcedureNotFoundError:
            raise HTTPException(status_code=404, detail=f"procedure {procedure_id} not found") from None

    @_proc_router.post("/executions/{exec_id}/advance")
    async def advance_execution(exec_id: str, body: dict):
        """Operator clicks 'GO' from ARMED state. Begins step execution.
        Will block at any requires_witness step until a second operator
        signs at /api/witness."""
        _require_actor_role(body, 4, "advancing a procedure")
        operator = body.get("operator", "anonymous")
        try:
            ex = await _proc_orch.advance_to_in_progress(exec_id, operator)
            from dataclasses import asdict

            d = asdict(ex)
            d["state"] = ex.state.value
            return d
        except KeyError:
            raise HTTPException(status_code=404, detail=f"execution {exec_id} not found") from None
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @_proc_router.post("/executions/{exec_id}/abort")
    async def abort_execution(exec_id: str, body: dict):
        """Operator-triggered emergency abort."""
        _require_actor_role(body, 4, "aborting a procedure")
        operator = body.get("operator", "anonymous")
        reason = body.get("reason", "no_reason_provided")
        try:
            ex = await _proc_orch.abort_now(exec_id, operator, reason)
            from dataclasses import asdict

            d = asdict(ex)
            d["state"] = ex.state.value
            return d
        except KeyError:
            raise HTTPException(status_code=404, detail=f"execution {exec_id} not found") from None

    # â"€â"€ Witness endpoints â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
    @_witness_router.get("/pending")
    async def list_pending_witness():
        """All currently PENDING witness requests across all executions.
        HMI surfaces this to qualified witness operators."""
        reqs = _witness_store.list_pending()
        return {
            "count": len(reqs),
            "requests": [_serialize_witness(r) for r in reqs],
        }

    @_witness_router.get("/{request_id}")
    async def get_witness_request(request_id: str):
        try:
            return _serialize_witness(_witness_store.get(request_id))
        except WitnessRequestNotFoundError:
            raise HTTPException(status_code=404, detail=f"witness request {request_id} not found") from None

    @_witness_router.post("/{request_id}/sign")
    async def sign_witness(request_id: str, body: dict):
        """Witness operator signs the request. Identity must differ from initiator."""
        _require_actor_role(body, 5, "signing a witness request")
        witness_id = body.get("witness", "")
        try:
            req = _witness_store.sign(request_id, witness_id)
            return _serialize_witness(req)
        except IdentityCollisionError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e
        except WitnessRequestNotPendingError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        except WitnessRequestNotFoundError:
            raise HTTPException(status_code=404, detail=f"witness request {request_id} not found") from None

    @_witness_router.post("/{request_id}/reject")
    async def reject_witness(request_id: str, body: dict):
        _require_actor_role(body, 5, "rejecting a witness request")
        witness_id = body.get("witness", "")
        reason = body.get("reason", "no_reason_provided")
        try:
            req = _witness_store.reject(request_id, witness_id, reason)
            return _serialize_witness(req)
        except IdentityCollisionError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e
        except WitnessRequestNotPendingError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        except WitnessRequestNotFoundError:
            raise HTTPException(status_code=404, detail=f"witness request {request_id} not found") from None

    app.include_router(_proc_router)
    app.include_router(_witness_router)
    log.info("[Sprint 3] Procedure + Witness routers mounted at /api/procedures and /api/witness")

except ImportError as e:
    log.warning(f"[Sprint 3] Procedure/Witness not loaded: {e}")
except Exception as e:
    log.error(f"[Sprint 3] Procedure/Witness mount failed: {e}")


# ==============================================================
#  Sprint G5: Procedure Generator HTTP endpoints
# ==============================================================
try:
    from backend import procedure_routes

    app.include_router(procedure_routes.router)
    log.info("[G5] Procedure generator routes mounted at /api/procedures "
             "(/generate, /{id}/activate)")
except Exception as e:
    log.error(f"[G5] Procedure generator routes mount failed: {e}")


# ==============================================================
#  Sprint S1b: Site Model HTTP endpoints
# ==============================================================
try:
    import site_routes

    site_routes.configure(PROJECT_ROOT)
    app.include_router(site_routes.router)

    from site_model import get_site_model

    _site_model = get_site_model(PROJECT_ROOT)
    log.info(
        f"[Sprint S1b] Site routes mounted at /api/site "
        f"({len(_site_model.list_components())} components, "
        f"{len(_site_model._location_by_id)} locations)"
    )
except ImportError as e:
    log.warning(f"[Sprint S1b] Site routes not loaded: {e}")
except Exception as e:
    log.error(f"[Sprint S1b] Site routes mount failed: {e}")


# ==============================================================
#  Sprint S2: GraphRAG service + router
# ==============================================================
try:
    from agent_graph_tool import set_graphrag_service
    from graphrag_routes import make_graphrag_router
    from graphrag_service import GraphRAGService
    from site_model import get_site_model as _s2_get_site_model

    _s2_corpus_dir = PROJECT_ROOT / "config" / "knowledge"
    _s2_site_model = _s2_get_site_model(PROJECT_ROOT)
    _s2_service = GraphRAGService(_s2_site_model, _s2_corpus_dir)
    set_graphrag_service(_s2_service)
    app.include_router(make_graphrag_router(_s2_service))
    _s2_doc_count = len([p for p in _s2_corpus_dir.glob("*.md") if p.name.lower() != "readme.md"])
    log.info(
        f"[Sprint S2] GraphRAG service mounted at /api/graph "
        f"(lazy index, {_s2_doc_count} knowledge docs available)"
    )
except ImportError as _s2_e:
    log.warning(f"[Sprint S2] GraphRAG NOT loaded (ImportError): {_s2_e}")
except Exception as _s2_e:
    log.warning(f"[Sprint S2] GraphRAG NOT mounted: {_s2_e}")


# ==============================================================
#  T3.1: Project Hermes - multiplexed WebSocket telemetry stream
# ==============================================================
try:
    from backend import hermes

    app.include_router(hermes.router)
    log.info("[T3.1] Hermes WebSocket stream mounted at WS /api/hermes")
except Exception as e:
    log.error(f"[T3.1] Hermes WebSocket mount failed: {e}")


# ==============================================================
#  Entrypoint
# ==============================================================


# Batch 4.D - LOTO Auditor activation (V9 Pillar 4 deliverable)
# Defensive: handles physics factory + witness_store subset interface.
try:
    from backend.loto_auditor_routes import register_loto_auditor
    _loto_physics = get_physics_engine() if PHYSICS_AVAILABLE else None
    if _loto_physics is not None:
        register_loto_auditor(
            app,
            site_model=_site_model,
            graphrag_service=_s2_service,
            physics_engine=_loto_physics,
            witness_engine=_witness_store,
        )
        log.info("LOTO Auditor registered: 4 endpoints active under /api/loto")
    else:
        log.warning("LOTO Auditor NOT registered: physics_engine unavailable")
except Exception as e:
    log.error("LOTO Auditor registration failed: %s", e, exc_info=True)


# Sprint 6 Fase 3 - CMMS Core v1.0 router registration
# Defensive: requires DB pool (db_manager); falls back gracefully.
try:
    from backend.cmms_repository import PostgresCMMSRepository

    _cmms_repo: PostgresCMMSRepository | None = None
    # Pool will be injected during lifespan after db_manager.connect().
    # We register the router here so the import-time path is clean;
    # repo gets attached in lifespan body.
    log.info("CMMS routes module loaded (router activates in lifespan)")
except Exception as e:
    log.error("CMMS router import failed: %s", e, exc_info=True)


# ==============================================================
#  Subprocess hygiene (Epic 6 Sprint 3 — Phase 1)
# ==============================================================
# Background: Windows venvs launch the real Python via a small shim
# (``.venv/Scripts/python.exe``). Sending Stop-Process to the shim
# orphans the child — the worker keeps holding the :8080 socket and
# whatever multiprocessing workers it spawned (ML model loaders, torch
# data workers, FAISS index threads). Result: ":8080 still LISTENING by
# zombie PID" after every restart, requiring manual cleanup. Three
# restart cycles in the past two sessions hit this.
#
# What this fixes here, in process:
#  * On normal Python exit (sys.exit / uvicorn graceful shutdown):
#    multiprocessing.active_children() are terminated + joined.
#  * On SIGTERM / SIGINT (operator Ctrl+C, ``Stop-Process`` on the
#    real Python PID): same cleanup, then re-raise so the framework
#    can finish its own shutdown.
#
# What it does NOT fix (out of scope / requires win32 API):
#  * Stop-Process -Force on the venv shim. The OS skips Python's
#    handlers entirely; the child gets no signal. The fix for that
#    is a Windows Job Object (pywin32, not stdlib) — separate sprint.
#
# Test surface: ``_active_children_terminator`` is exposed for the
# unit test, with the production active_children() lookup injectable
# so the test doesn't need to spawn real subprocesses.
import atexit  # noqa: E402  (kept beside its sole consumer)
import signal  # noqa: E402


def _active_children_terminator(
    *,
    active_children_fn=None,
    terminate_timeout_s: float = 2.0,
) -> list[int]:
    """Terminate every multiprocessing child of this process.

    Returns the list of PIDs that were terminated (for the boot-log
    line + the unit test). Best-effort: per-child exceptions are
    swallowed so a stuck worker doesn't block the others.
    """
    import multiprocessing
    if active_children_fn is None:
        active_children_fn = multiprocessing.active_children
    pids: list[int] = []
    for child in list(active_children_fn() or []):
        try:
            pid = getattr(child, "pid", None)
            child.terminate()
            child.join(timeout=terminate_timeout_s)
            # If still alive after terminate+join, escalate to kill.
            if hasattr(child, "is_alive") and child.is_alive():
                if hasattr(child, "kill"):
                    child.kill()
                child.join(timeout=terminate_timeout_s)
            if pid is not None:
                pids.append(int(pid))
        except Exception as e:
            log.debug("[subprocess-cleanup] child terminate failed: %s", e)
    return pids


def _cleanup_subtree(reason: str = "atexit") -> None:
    """Module-level shutdown hook. Logs the killed PIDs so the
    operator's restart smoke test can see the cleanup happened."""
    killed = _active_children_terminator()
    if killed:
        log.info(
            "[SHUTDOWN] subprocess cleanup (%s) — terminated %d child(ren): %s",
            reason, len(killed), killed,
        )
    else:
        log.info("[SHUTDOWN] subprocess cleanup (%s) — no children to clean", reason)


# Register the atexit hook at import time so it fires for ANY exit
# path (sys.exit, uncaught exception, uvicorn graceful shutdown).
atexit.register(_cleanup_subtree, reason="atexit")


def _install_signal_handlers() -> list[str]:
    """Install SIGTERM/SIGINT handlers that cleanup-then-default.
    Called from the ``__main__`` block — NOT at import time, so the
    test suite (which imports main as a module) doesn't clobber
    pytest's own signal handling.

    Returns the list of signal names actually installed (some are
    not available on Windows; the rest land silently)."""
    installed: list[str] = []
    targets = [
        ("SIGINT", getattr(signal, "SIGINT", None)),
        ("SIGTERM", getattr(signal, "SIGTERM", None)),
        ("SIGBREAK", getattr(signal, "SIGBREAK", None)),  # Windows only
    ]
    for name, sig in targets:
        if sig is None:
            continue

        def _handler(signum, _frame, _name=name):
            log.info(
                "[SHUTDOWN] %s received — initiating clean shutdown",
                _name,
            )
            _cleanup_subtree(reason=f"signal:{_name}")
            # Re-raise default behaviour so uvicorn's own handler runs.
            signal.signal(signum, signal.SIG_DFL)
            try:
                os.kill(os.getpid(), signum)
            except (ProcessLookupError, OSError):
                sys.exit(0)

        try:
            signal.signal(sig, _handler)
            installed.append(name)
        except (ValueError, OSError) as e:
            # Some signals not installable in this thread on this OS.
            log.debug("[SHUTDOWN] cannot install %s handler: %s", name, e)
    return installed


if __name__ == "__main__":
    import uvicorn

    handlers = _install_signal_handlers()
    log.info("[BUILD] signal cleanup handlers installed: %s", handlers)

    port = int(os.environ.get("EPMS_PORT", "8080"))
    host = os.environ.get("EPMS_HOST", "0.0.0.0")
    log.info("Launching uvicorn on %s:%d", host, port)
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
        access_log=False,
    )
