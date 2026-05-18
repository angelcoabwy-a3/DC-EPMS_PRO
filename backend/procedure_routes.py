"""
backend/procedure_routes.py
===========================
FastAPI router exposing the ProcedureGenerator over HTTP (Sprint Bite G5).

Endpoints (mounted under /api/procedures by main.py, alongside the
existing procedure-engine router):
  POST /api/procedures/generate            Generate a SOP / MOP / EOP / EMP
  POST /api/procedures/{id}/activate       RBAC-gated DRAFT -> ACTIVE promotion

/generate routes to the procedure_generator factories via
compile_procedure(). /activate routes to procedure_engine.promote_procedure
and maps its RBAC / state exceptions to clean HTTP status codes:
  RBACDeniedError             -> 403 Forbidden
  InvalidTransitionError -> 400 Bad Request
  ValueError (bad input) -> 400 Bad Request

HONEST: generated DRAFTs are not persisted server-side (there is no draft
store yet). /activate is therefore stateless -- the client round-trips
the DRAFT dict it received from /generate, and the {id} path segment is
cross-checked against it. A DB-backed draft store is future work.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.cmms_models import RBACDeniedError
from backend.procedure_engine import InvalidTransitionError, promote_procedure
from backend.procedure_generator import compile_procedure

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/procedures", tags=["procedure-generator"])


class GenerateRequest(BaseModel):
    """Body for POST /api/procedures/generate."""

    asset_id: str = Field(..., min_length=1, max_length=128)
    procedure_class: str = Field(..., pattern="^(SOP|MOP|EOP|EMP)$")
    anomaly_profile: str | None = Field(default=None, max_length=64)
    actor_role: str | None = Field(
        default=None,
        description="Compiling role (mock until auth is wired); defaults to TECH_L4.",
    )


class ActivateRequest(BaseModel):
    """Body for POST /api/procedures/{procedure_id}/activate."""

    actor_role: str = Field(..., min_length=1)
    procedure: dict[str, Any] = Field(
        ..., description="The generated DRAFT procedure dict to promote.",
    )


@router.post("/generate")
def generate_procedure(req: GenerateRequest) -> dict[str, Any]:
    """Generate a procedure via the corresponding factory.

    Returns the procedure JSON with HTTP 200. HTTP 400 on a bad request
    (unknown asset_id, or a missing anomaly_profile for an EOP).
    """
    try:
        proc = compile_procedure(
            req.asset_id,
            req.procedure_class,
            anomaly_profile=req.anomaly_profile,
            author_role=req.actor_role or "TECH_L4",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log.info("[procedure_routes] generated %s for %s",
             req.procedure_class, req.asset_id)
    return proc


@router.post("/{procedure_id}/activate")
def activate_procedure(procedure_id: str, req: ActivateRequest) -> dict[str, Any]:
    """RBAC-gated DRAFT -> ACTIVE promotion.

    HTTP 403 if the actor role is insufficient (a TECH_L4 cannot promote);
    HTTP 400 on an invalid state transition or a path/body id mismatch.
    """
    body_id = req.procedure.get("procedure_id")
    if body_id and body_id != procedure_id:
        raise HTTPException(
            status_code=400,
            detail=f"path procedure_id {procedure_id!r} does not match body {body_id!r}",
        )
    try:
        promoted = promote_procedure(req.procedure, req.actor_role)
    except RBACDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log.info("[procedure_routes] %s promoted to ACTIVE by %s",
             procedure_id, req.actor_role)
    return promoted
