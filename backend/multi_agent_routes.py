"""
backend/multi_agent_routes.py
=============================
Sprint 10.1 — REST surface for the Multi-Agent façade.

Endpoints:
  POST /api/multi-agent/consult     run all 4 agents and return consensus
  GET  /api/multi-agent/health      router probe + agent inventory

Per ADR-006: returns advisory output. The consensus is informational;
state mutations remain gated behind the existing CMMS approve/reject
flow.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.multi_agent import (
    ConsultContext,
    MultiAgentOrchestrator,
    get_orchestrator,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/multi-agent", tags=["multi-agent"])


# ─── Schemas ───────────────────────────────────────────────────────────
class ConsultRequest(BaseModel):
    """Body for POST /api/multi-agent/consult."""
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=3, max_length=600,
                       description="Operator's question or proposed action.")
    asset_id: str | None = Field(default=None, max_length=64,
                                  description="Canonical asset id for "
                                              "topology / history evaluation.")
    procedure_id: str | None = Field(default=None, max_length=120,
                                      description="MOP / SOP id for safety check.")
    work_order_id: str | None = Field(default=None, max_length=64,
                                       description="Existing WO id to evaluate.")
    cet_id: str | None = Field(default=None, max_length=120,
                                description="Operator id (audit trail only).")


def _get_orchestrator_from_state(request: Request) -> MultiAgentOrchestrator:
    orch = getattr(request.app.state, "multi_agent_orchestrator", None)
    if orch is None:
        raise HTTPException(
            status_code=503,
            detail="Multi-Agent orchestrator not initialized",
        )
    return orch


# ─── Endpoints ─────────────────────────────────────────────────────────
@router.get("/health")
async def multi_agent_health(request: Request) -> dict[str, Any]:
    """Router probe + per-agent dependency status."""
    orch = getattr(request.app.state, "multi_agent_orchestrator", None)
    if orch is None:
        return {"status": "uninitialized", "agents": []}
    return {
        "status": "up",
        "agents": [
            {"name": a.name, "class": type(a).__name__}
            for a in orch.agents
        ],
        "consensus_protocol": (
            "Safety Officer hard_stop -> hard_stop (VETO); "
            "any agent hard_stop -> hard_stop; "
            "any agent caution -> caution; else approve"
        ),
    }


@router.post("/consult")
async def multi_agent_consult(
    request: Request, body: ConsultRequest,
) -> dict[str, Any]:
    """Run the five agents in parallel and return consensus.

    Each agent evaluates from a single perspective:
      - Architect        topology + 2N redundancy impact
      - Safety Officer   LOTO/PPE compliance (VETO power)
      - Diagnostician    recurrence + corpus history
      - Analyst          CapEx-vs-OpEx retrospective framing
      - Capacity Planner forward-looking IT-load / cooling headroom (3.A)

    Returns consensus + per-agent verdicts + decision_time_ms.
    Pure deterministic critical path; no LLM in the consensus rule.
    """
    orch = _get_orchestrator_from_state(request)
    ctx = ConsultContext(
        query=body.query,
        asset_id=body.asset_id,
        procedure_id=body.procedure_id,
        work_order_id=body.work_order_id,
        cet_id=body.cet_id,
    )
    try:
        result = await orch.consult(ctx)
        # T3.1 EDA: stream the consensus on the Hermes agent_consensus
        # channel. Fire-and-forget -- never affects the HTTP response.
        try:
            from backend import hermes
            hermes.emit_event("agent_consensus", {
                "agent": "consensus",
                "event": "resolved",
                "content": getattr(result, "rationale", result.consensus),
                "veto_active": bool(result.safety_officer_veto),
            })
        except Exception:
            pass
        return result.to_dict()
    except Exception as e:
        log.exception("multi-agent consult failed: %s", e)
        raise HTTPException(status_code=500, detail=f"consult error: {e}") from e


# ─── Registration ──────────────────────────────────────────────────────
def register_multi_agent_routes(
    app: FastAPI,
    site_model: Any | None = None,
    graphrag: Any | None = None,
    cmms_repo: Any | None = None,
    rag_service: Any | None = None,
    llm_client: Any | None = None,
    telemetry_provider: Any | None = None,
) -> None:
    """Mount the router and stash a singleton orchestrator on app.state.

    T3.3: ``llm_client`` (local Gemma) and ``telemetry_provider`` (live
    Hermes Kalman tap) are forwarded to the Diagnostician for its advisory
    narrative. Both optional -- absent them the agents stay deterministic.
    """
    orchestrator = get_orchestrator(
        site_model=site_model,
        graphrag=graphrag,
        cmms_repo=cmms_repo,
        rag_service=rag_service,
        llm_client=llm_client,
        telemetry_provider=telemetry_provider,
    )
    app.state.multi_agent_orchestrator = orchestrator
    if not getattr(app.state, "_multi_agent_router_registered", False):
        app.include_router(router)
        app.state._multi_agent_router_registered = True
    log.info(
        "Multi-Agent routes registered: 2 endpoints under /api/multi-agent "
        "(orchestrator has %d agents)",
        len(orchestrator.agents),
    )
