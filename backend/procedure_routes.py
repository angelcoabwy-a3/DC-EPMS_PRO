"""
backend/procedure_routes.py
===========================
FastAPI router exposing the ProcedureGenerator over HTTP (Sprint Bite G5).

Endpoints (mounted under /api/procedures by main.py):

  POST /api/procedures/generate            Generate a SOP / MOP / EOP / EMP
                                           via the deterministic factory
                                           (compile_procedure, ADR-010).
  POST /api/procedures/{id}/activate       RBAC-gated DRAFT -> ACTIVE promotion

Epic 6 (LLM-narrative Procedure Architect, mounted under the same
prefix at a distinct sub-path to avoid colliding with G5's
deterministic /generate above):

  POST /api/procedures/architect/generate  LLM-authored SOP/MOP/EOP/EMP
                                           with deterministic Safety
                                           Officer audit pipeline.
  POST /api/procedures/architect/sign      Operator signs an approved
                                           draft into the forensic ledger.

/generate (G5) routes to the procedure_generator factories via
compile_procedure(). /activate routes to procedure_engine.promote_procedure
and maps its RBAC / state exceptions to clean HTTP status codes:
  RBACDeniedError             -> 403 Forbidden
  InvalidTransitionError -> 400 Bad Request
  ValueError (bad input) -> 400 Bad Request

/architect/* (Epic 6) routes to backend.agents.procedure_architect and
audits the result before returning. A MOP missing LOTO/PPE/CSA Z462
emits ``safety_audit.verdict == "hard_stop"``; the response carries
that verdict so the HMI can refuse to surface a Sign button.

HONEST: generated DRAFTs are not persisted server-side (there is no draft
store yet). /activate is therefore stateless -- the client round-trips
the DRAFT dict it received from /generate, and the {id} path segment is
cross-checked against it. A DB-backed draft store is future work.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.agents.procedure_architect import (
    DOC_TYPE_EMP,
    DOC_TYPE_EOP,
    DOC_TYPE_MOP,
    DOC_TYPE_SOP,
    ProcedureArchitectAgent,
    ProcedureDraft,
    audit_procedure_safety,
)
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


# ════════════════════════════════════════════════════════════════════
# Epic 6 — Procedure Architect (LLM-narrative + Safety Officer audit)
# ════════════════════════════════════════════════════════════════════
#
# Naming note: the spec asked for ``POST /api/procedures/generate``,
# but that path was already taken by the G5 deterministic factory
# above. To avoid breaking the existing route + its 14 tests, the
# Architect's narrative-generation endpoint lives at
# ``POST /api/procedures/architect/generate``. Same prefix, distinct
# sub-path. The two endpoints are functionally orthogonal — one
# compiles asset-graph-derived skeletons (no LLM), the other
# narrates per-template documents (LLM-driven). Operators choose
# which they need.

class ArchitectGenerateRequest(BaseModel):
    """Body for POST /api/procedures/architect/generate (Epic 6)."""

    doc_type: str = Field(
        ...,
        pattern="^(SOP|MOP|EOP|EMP)$",
        description="Procedure template to apply.",
    )
    context: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description=(
            "Free-form operator request describing the maintenance / "
            "operation / incident being documented. Becomes the "
            "CONTEXT field of the hermetic Architect prompt."
        ),
    )
    asset_id: str | None = Field(
        default=None,
        max_length=128,
        description="Optional canonical asset id this procedure targets.",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional LIVE OPERATING METADATA the operator pulled in "
            "from /api/telemetry — typically {pue, load_kw, criticality, "
            "battery_runtime_min, ...}. The Architect surfaces it as a "
            "labelled block in the hermetic prompt so the LLM grounds "
            "the document in current state rather than a static baseline. "
            "Persisted on the returned draft so the ledger entry can "
            "audit which snapshot informed the document."
        ),
    )


class ArchitectSignRequest(BaseModel):
    """Body for POST /api/procedures/architect/sign (Epic 6)."""

    draft_id: str = Field(..., min_length=1, max_length=128)
    doc_type: str = Field(..., pattern="^(SOP|MOP|EOP|EMP)$")
    content: str = Field(..., min_length=1, max_length=64_000)
    asset_id: str | None = Field(default=None, max_length=128)
    operator_id: str = Field(..., min_length=1, max_length=128)
    actor_role: str | None = Field(
        default=None,
        description="Operator role claim (mock until auth is wired).",
    )


def _get_architect_agent(request: Request) -> ProcedureArchitectAgent:
    """Pull the Architect agent off ``app.state``. Lazily constructs
    one when absent so the route works even without explicit wiring
    from main.py — the agent gracefully degrades to a deterministic
    skeleton when no llm_client is attached."""
    agent = getattr(request.app.state, "procedure_architect_agent", None)
    if agent is None:
        llm_client = getattr(request.app.state, "llm_client", None)
        model_router = getattr(request.app.state, "model_router", None)
        agent = ProcedureArchitectAgent(
            llm_client=llm_client, model_router=model_router,
        )
        request.app.state.procedure_architect_agent = agent
    return agent


@router.post("/architect/generate")
async def architect_generate(
    req: ArchitectGenerateRequest, request: Request,
) -> dict[str, Any]:
    """Epic 6 — Procedure Architect generation + Safety Officer audit.

    Pipeline:
      1. Build a hermetic Gemma prompt (H17) carrying the exact Epic 6
         system prompt + the operator's context + doc_type selector.
      2. The Architect renders a markdown document
         (deterministic skeleton if no LLM is wired).
      3. ``audit_procedure_safety()`` scans the result. A MOP missing
         LOTO / PPE / CSA Z462 callouts emits ``hard_stop``.
      4. Response carries BOTH the draft AND the audit verdict — the
         HMI uses the verdict to gate the Sign button.

    Even ``hard_stop`` drafts are returned (HTTP 200) so the operator
    can see WHY the Safety Officer refused — that signal drives the
    Architect to re-prompt with the missing terms. A 4xx would lose
    the diagnostic findings.
    """
    agent = _get_architect_agent(request)
    draft = await agent.generate(
        doc_type=req.doc_type,
        context=req.context,
        asset_id=req.asset_id,
        metadata=req.metadata,
    )
    audit = audit_procedure_safety(draft)
    log.info(
        "[procedure_routes] architect generated %s (draft=%s, "
        "audit=%s, llm=%s)",
        draft.doc_type, draft.draft_id, audit.verdict, draft.llm_present,
    )
    return {
        "draft": draft.to_dict(),
        "safety_audit": audit.to_dict(),
    }


@router.post("/architect/sign")
async def architect_sign(
    req: ArchitectSignRequest, request: Request,
) -> dict[str, Any]:
    """Epic 6 — operator signs an approved draft into the forensic ledger.

    Re-runs the audit server-side (defence in depth — a hostile HMI
    cannot forge an approved verdict). When the audit re-emits
    ``hard_stop``, the sign is refused with HTTP 403 (the operator
    cannot sign an unsafe procedure even by mistake).

    On success: appends a ``PROCEDURE_SIGNED`` action to the
    forensic ledger with the content sha256, operator_id, doc_type,
    and draft_id — the chain link that proves *this* operator
    approved *this* exact content at *this* time. Returns the ledger
    entry summary (entry_id + sequence_no + ts).
    """
    # Reconstruct a ProcedureDraft so the audit runs against the SAME
    # surface the HMI already saw — never trust client-supplied
    # verdicts.
    draft = ProcedureDraft(
        draft_id=req.draft_id,
        doc_type=req.doc_type,
        context="(replayed from sign request)",
        content=req.content,
        asset_id=req.asset_id,
        generated_at=0.0,
        llm_present=False,
    )
    audit = audit_procedure_safety(draft)
    if audit.is_blocking:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Safety Officer HARD_STOP on draft {req.draft_id!r}: "
                f"{'; '.join(audit.findings)}"
            ),
        )

    ledger = getattr(request.app.state, "forensic_ledger", None)
    if ledger is None:
        raise HTTPException(
            status_code=503,
            detail="ForensicLedger not initialised — cannot sign.",
        )

    content_sha = hashlib.sha256(req.content.encode("utf-8")).hexdigest()
    entry = await ledger.append(
        actor=req.operator_id,
        action="PROCEDURE_SIGNED",
        payload={
            "draft_id": req.draft_id,
            "doc_type": req.doc_type,
            "asset_id": req.asset_id,
            "actor_role": req.actor_role or "operator",
            "content_sha256": content_sha,
            "content_length": len(req.content),
            "safety_audit_verdict": audit.verdict,
        },
    )
    log.info(
        "[procedure_routes] architect draft %s signed by %s "
        "(ledger entry %s, seq=%s)",
        req.draft_id, req.operator_id, entry.entry_id, entry.sequence_no,
    )
    # Silence ruff for the unused-import noise during static analysis —
    # the doc-type constants are exported here for downstream callers.
    _ = (DOC_TYPE_SOP, DOC_TYPE_MOP, DOC_TYPE_EOP, DOC_TYPE_EMP, asyncio)
    return {
        "signed": True,
        "draft_id": req.draft_id,
        "entry_id": entry.entry_id,
        "sequence_no": entry.sequence_no,
        "ts": entry.ts,
        "content_sha256": content_sha,
        "safety_audit_verdict": audit.verdict,
    }
