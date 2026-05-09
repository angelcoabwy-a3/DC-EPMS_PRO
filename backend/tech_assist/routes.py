"""
backend/tech_assist/routes.py
=============================
FastAPI router for /api/tech-assist/*.

Sprint 7.1a: troubleshoot QA only. Future endpoints (PDF ingest,
voice closure, nameplate OCR) attach to this same router as separate
sub-bites.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request

from backend.tech_assist.models import TroubleshootRequest, TroubleshootResponse
from backend.tech_assist.troubleshoot import TroubleshootAgent

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tech-assist", tags=["tech-assist"])


def _get_agent(request: Request) -> TroubleshootAgent:
    agent = getattr(request.app.state, "tech_assist_agent", None)
    if agent is None:
        raise HTTPException(status_code=503, detail="Tech Assist agent not initialized")
    return agent


@router.get("/health")
async def tech_assist_health(request: Request) -> dict[str, Any]:
    agent = getattr(request.app.state, "tech_assist_agent", None)
    return {
        "status": "up" if agent is not None else "uninitialized",
        "rag_available":   agent.rag_service is not None if agent else False,
        "cmms_available":  agent.cmms_repo    is not None if agent else False,
        "lm_studio_url":   agent.lm_studio_url if agent else None,
        "lm_studio_model": agent.lm_studio_model if agent else None,
    }


@router.post("/troubleshoot", response_model=TroubleshootResponse)
async def troubleshoot(request: Request, body: TroubleshootRequest) -> TroubleshootResponse:
    """Real-time field assistance.

    Combines knowledge corpus retrieval (rag_service) + asset failure
    history (cmms_repository) + LLM synthesis (LM Studio gemma) into
    a structured 3-section answer with citations. ADR-006 compliant:
    advisory only, no autonomous action."""
    agent = _get_agent(request)
    try:
        return await agent.answer(body)
    except Exception as e:
        log.exception("troubleshoot failed: %s", e)
        raise HTTPException(status_code=500, detail=f"troubleshoot error: {e}")


def register_tech_assist_routes(
    app: FastAPI,
    rag_service: Any | None,
    cmms_repo: Any | None,
) -> None:
    """Mount the router on app.state with agent instance."""
    agent = TroubleshootAgent(rag_service=rag_service, cmms_repo=cmms_repo)
    app.state.tech_assist_agent = agent
    if not getattr(app.state, "_tech_assist_router_registered", False):
        app.include_router(router)
        app.state._tech_assist_router_registered = True
    log.info("Tech Assist routes registered: 2 endpoints active under /api/tech-assist")
