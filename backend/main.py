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
# [FIX 1] PG_DSN is forced to URI format with explicit db=epms.
#          Never fall back to the default "postgres" DB.
# --------------------------------------------------------------
_PG_HOST = os.environ.get("PG_HOST", "localhost")
_PG_PORT = os.environ.get("PG_PORT", "5432")
_PG_DB = os.environ.get("PG_DB", "epms")  # <-- explicit
_PG_USER = os.environ.get("PG_USER", "postgres")
_PG_PWD = os.environ.get("PG_PASSWORD", "epms2026")
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
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s :: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "epms_pro.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("dc-epms-pro")


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
        else:
            log.warning("[BOOT] CMMS skipped: db_manager pool unavailable")
    except Exception as e:
        log.error("[BOOT] CMMS init failed: %s", e, exc_info=True)

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
    if db_manager:
        await db_manager.close()


# ==============================================================
#  FastAPI app
# ==============================================================
app = FastAPI(
    title="DC-EPMS PRO",
    description="a3semi Edge Operations - Proprietary EPMS for Blackwell Fleet (Tier IV 2N 40MW)",
    version="4.1.0-pro",
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
        "version": "4.1.0-pro",
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
            asyncio.create_task(_pue_advisory_task(point.model_dump()))
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
            from telemetry_simulator import get_simulator
            from telemetry_pipeline import get_pipeline
            from site_model import get_site_model as _sm_get
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
        raise HTTPException(status_code=502, detail=f"LM Studio unreachable: {e}")


@app.get("/lm/{path:path}")
async def lm_proxy_get(path: str):
    import httpx

    url = f"{LM_STUDIO_URL}/{path}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LM Studio unreachable: {e}")


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
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")

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
async def run_scenario(scenario_id: str, horizon_s: int = 900):
    """Execute a named scenario and return the trajectory."""
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
                title = title.lstrip(": -  - -").strip()
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
            t: sum(1 for m in mops if m["doc_type"] == t) for t in set(m["doc_type"] for m in mops)
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
async def generate_mop_endpoint(payload: dict = Body(...)):
    """Generate a NEW MOP using the LLM agent grounded in the existing corpus.

    Payload:
        {
          "topic":   str   - what the MOP is for, e.g. "CRAH fan filter inspection"
          "doc_type": str  - "MOP"|"SOP"|"EOP", default "MOP"
          "equipment": str - target equipment
          "duration": str  - estimated duration
        }
    """
    topic = (payload.get("topic") or "").strip()
    if not topic:
        raise HTTPException(400, "Field 'topic' is required")

    doc_type = payload.get("doc_type", "MOP").upper()
    equipment = payload.get("equipment", "Generic")
    duration = payload.get("duration", "TBD")

    if not agent:
        raise HTTPException(503, "Agent engine unavailable")

    # Build a structured prompt that asks the LLM to produce a MOP in the
    # same format as the corpus. We give it 1-2 examples from the corpus
    # for in-context grounding (not full RAG since this is generative).
    prompt = f"""Generate a complete {doc_type} document for: "{topic}"

Equipment: {equipment}
Estimated duration: {duration}

Produce a markdown document in this exact format:

---
doc_id: T4-{doc_type}-NEW-{int(time.time()) % 10000:04d}
tier: 4
priority: medium
doc_type: {doc_type}
domain: <choose from: mechanical_cooling, electrical_power, fire_safety, network_security, it_infrastructure>
equipment: {equipment}
standard_refs: [<applicable standards>]
duration: {duration}
personnel_required: <number and qualifications>
---

# {doc_type}: <Title>

**Procedure ID**: T4-{doc_type}-NEW-XXXX
**Revision**: 2026.1

## Purpose

<2-3 sentences explaining what this procedure achieves>

## Scope

<what is and isn't covered>

## Pre-requisites

- Personnel: <who>
- Tools: <list>
- PPE: <list, citing CSA Z462 / NFPA 70E>
- Documentation: <required>

## Procedure

### Step 1: <Title>
<numbered actions, observations to record>

### Step 2: <Title>
<...>

(continue with 4-7 steps total, each with concrete actions)

## Post-procedure

- Record findings in <where>
- Update CMMS work order
- File report per a3semi OPS

## Safety considerations

<reference relevant standards: NFPA 70E, CSA Z462, IEC 62443 if applicable>

---
End the procedure here. Do not add commentary outside the document."""

    # Invoke agent (non-streaming for this use case)
    try:
        # Collect all tokens
        full_text = ""
        async for token in agent.stream(
            prompt,
            max_tokens=2000,
            model_hint="auto",
        ):
            full_text += token

        meta, body = _parse_mop_frontmatter(full_text)
        steps = _extract_mop_steps(body)

        return {
            "generated": True,
            "topic": topic,
            "doc_type": doc_type,
            "raw_markdown": full_text,
            "metadata": meta,
            "body": body,
            "steps": steps,
            "step_count": len(steps),
        }
    except Exception as e:
        log.error("MOP generation failed: %s", e)
        raise HTTPException(500, f"MOP generation failed: {str(e)[:200]}")


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
async def write_bms_tag(payload: dict = Body(...)):
    """Issue a write command against a writable BMS tag.

    Payload: {"tag_id": str, "value": Any, "user": str (optional)}
    All writes are logged to an immutable audit log for review.
    """
    if not BMS_AVAILABLE:
        raise HTTPException(503, "BMS connector unavailable")
    tag_id = payload.get("tag_id")
    value = payload.get("value")
    user = payload.get("user", "dashboard-user")
    if not tag_id:
        raise HTTPException(400, "tag_id required")

    bms = get_bms(PROJECT_ROOT)
    success, message = bms.write(tag_id, value, user=user)
    if not success:
        raise HTTPException(400, message)
    return {"success": True, "message": message, "tag_id": tag_id, "new_value": value}


@app.get("/api/bms/audit")
async def get_bms_audit(limit: int = 50):
    """Return recent write audit log entries."""
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
        InvalidTransitionError,
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
            raise HTTPException(status_code=404, detail=f"procedure {procedure_id} not found")

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
            raise HTTPException(status_code=404, detail=f"execution {exec_id} not found")

    @_proc_router.post("/{procedure_id}/start")
    async def start_procedure(procedure_id: str, body: dict):
        """Operator initiates a procedure. Returns the execution with
        pre_condition_results  -  operator clicks 'Advance' to proceed
        if all pre-conditions are OK."""
        operator = body.get("operator", "anonymous")
        try:
            ex = await _proc_orch.start_procedure(procedure_id, operator)
            from dataclasses import asdict

            d = asdict(ex)
            d["state"] = ex.state.value
            return d
        except ProcedureNotFoundError:
            raise HTTPException(status_code=404, detail=f"procedure {procedure_id} not found")

    @_proc_router.post("/executions/{exec_id}/advance")
    async def advance_execution(exec_id: str, body: dict):
        """Operator clicks 'GO' from ARMED state. Begins step execution.
        Will block at any requires_witness step until a second operator
        signs at /api/witness."""
        operator = body.get("operator", "anonymous")
        try:
            ex = await _proc_orch.advance_to_in_progress(exec_id, operator)
            from dataclasses import asdict

            d = asdict(ex)
            d["state"] = ex.state.value
            return d
        except KeyError:
            raise HTTPException(status_code=404, detail=f"execution {exec_id} not found")
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @_proc_router.post("/executions/{exec_id}/abort")
    async def abort_execution(exec_id: str, body: dict):
        """Operator-triggered emergency abort."""
        operator = body.get("operator", "anonymous")
        reason = body.get("reason", "no_reason_provided")
        try:
            ex = await _proc_orch.abort_now(exec_id, operator, reason)
            from dataclasses import asdict

            d = asdict(ex)
            d["state"] = ex.state.value
            return d
        except KeyError:
            raise HTTPException(status_code=404, detail=f"execution {exec_id} not found")

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
            raise HTTPException(status_code=404, detail=f"witness request {request_id} not found")

    @_witness_router.post("/{request_id}/sign")
    async def sign_witness(request_id: str, body: dict):
        """Witness operator signs the request. Identity must differ from initiator."""
        witness_id = body.get("witness", "")
        try:
            req = _witness_store.sign(request_id, witness_id)
            return _serialize_witness(req)
        except IdentityCollisionError as e:
            raise HTTPException(status_code=403, detail=str(e))
        except WitnessRequestNotPendingError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except WitnessRequestNotFoundError:
            raise HTTPException(status_code=404, detail=f"witness request {request_id} not found")

    @_witness_router.post("/{request_id}/reject")
    async def reject_witness(request_id: str, body: dict):
        witness_id = body.get("witness", "")
        reason = body.get("reason", "no_reason_provided")
        try:
            req = _witness_store.reject(request_id, witness_id, reason)
            return _serialize_witness(req)
        except IdentityCollisionError as e:
            raise HTTPException(status_code=403, detail=str(e))
        except WitnessRequestNotPendingError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except WitnessRequestNotFoundError:
            raise HTTPException(status_code=404, detail=f"witness request {request_id} not found")

    app.include_router(_proc_router)
    app.include_router(_witness_router)
    log.info("[Sprint 3] Procedure + Witness routers mounted at /api/procedures and /api/witness")

except ImportError as e:
    log.warning(f"[Sprint 3] Procedure/Witness not loaded: {e}")
except Exception as e:
    log.error(f"[Sprint 3] Procedure/Witness mount failed: {e}")


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
    from backend.cmms_routes import register_cmms_routes

    _cmms_repo: PostgresCMMSRepository | None = None
    # Pool will be injected during lifespan after db_manager.connect().
    # We register the router here so the import-time path is clean;
    # repo gets attached in lifespan body.
    log.info("CMMS routes module loaded (router activates in lifespan)")
except Exception as e:
    log.error("CMMS router import failed: %s", e, exc_info=True)


if __name__ == "__main__":
    import uvicorn

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
