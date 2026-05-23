"""
backend/optimizer_routes.py
============================
Epic 2 Batch 2.C — operator approve / reject endpoints for the
Optimizer's proposal queue.

Design source-of-truth: ``docs/architecture/epic-2-optimizer.md``.

This module is the *only* place in the Epic 2 codebase that may reach
the BMS write path. The deterministic ``backend/optimizer.py`` core is
forbidden from doing so by four AST-invariant tests (Proposer Pattern).
Here, every actuation:

  * is authorised by the **OPERATOR's** claim, not the Optimizer's
    (the Optimizer has no actor_role). ``actor_role >= SME_L6`` is
    enforced by ``backend/rbac.require_actor_role`` (S-SEC-02).
  * cross-checks the Safety Officer's veto field on the queued
    proposal (defence in depth, S-DET-02). Even if Batch 2.B's tick
    drops vetoed proposals before queueing, a vetoed proposal that
    somehow reaches this module is refused with HTTP 409.
  * carries the same UUID as the queued proposal, joining the audit
    chain end-to-end: proposal → consensus → operator decision → BMS
    write log.

Endpoints (prefix ``/api/optimizer``)
-------------------------------------

  GET    /proposals               list the queued proposals
  GET    /approvals/{proposal_id} fetch the operator decision for a UUID
  POST   /approve/{proposal_id}   SME_L6: dequeue + issue BMS write
  POST   /reject/{proposal_id}    SME_L6: dequeue + record reason

The approval log is currently in-memory (matches the 2.A AuditLog
pattern). A PostgreSQL-backed table is the natural 2.C+ follow-up; the
``ApprovalLog`` interface is shaped for a drop-in swap.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from fastapi import APIRouter, Body, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from backend.optimizer import (
    SURFACE_CHILLER_LWT,
    SURFACE_CT_FAN_VFD,
    OptimizerService,
    QueuedProposal,
)
from backend.rbac import RANK_SME_L6, require_actor_role

log = logging.getLogger(__name__)


# ─── Surface → BMS tag mapping ─────────────────────────────────────────
# Maps the Optimizer's logical control surfaces onto the ISA-95 BMS tag
# registry (``config/bms_tags.yml``). Batch 2.E wired these to the live
# catalogue: ``chiller_lwt`` reuses the existing
# ``HVAC.CHILLER1.CW_SETPOINT`` (writable AO, "Chilled water leaving
# setpoint", 4-9 °C alarm band), and ``ct_fan_vfd`` was added to the
# catalogue in 2.E as ``HVAC.CTOWER1.FAN_VFD``. Adding a new surface
# here also requires extending the catalogue with a ``writable: true``
# entry — when a tag is missing or read-only, the BMS write returns
# success=False with a clear message; the approval row is still
# recorded with that failure (operator intent is auditable).
SURFACE_TO_BMS_TAG: dict[str, str] = {
    SURFACE_CHILLER_LWT: "HVAC.CHILLER1.CW_SETPOINT",
    SURFACE_CT_FAN_VFD: "HVAC.CTOWER1.FAN_VFD",
}


# ─── BMS-write seam (injected) ────────────────────────────────────────
# A callable that performs the BMS write. In production main.py wires
# this to a lambda over ``bms_connector.get_bms(...).write(...)``; in
# tests it is mocked. The return tuple matches ``bms.write`` exactly.
#
# NOTE — this module is the *only* import-time linkage between the
# Optimizer code path and the BMS write path. ``backend/optimizer.py``
# is forbidden from importing this module (a new AST invariant test
# in ``tests/test_optimizer.py`` enforces the directionality).
BmsWriteFn = Callable[[str, Any, str], tuple[bool, str]]


# ─── Approval record ───────────────────────────────────────────────────
@dataclass(frozen=True)
class OptimizerApproval:
    """One operator decision on a queued proposal. UUID joins this to
    the original ``Proposal``, the multi-agent ``ConsensusResult`` from
    Batch 2.B, and (when ``decision == "approved"``) the BMS write
    audit row."""

    proposal_id: str
    decision: str                       # "approved" | "rejected"
    operator_id: str
    actor_role: str
    decision_at: float
    reason: str = ""
    bms_write_success: bool | None = None
    bms_write_message: str | None = None
    bms_tag_id: str | None = None
    approval_id: str = ""               # UUID for the approval row itself

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DECISION_APPROVED = "approved"
DECISION_REJECTED = "rejected"


class ApprovalLog:
    """In-memory bounded log of operator decisions on Optimizer proposals.

    2.C+ swaps this for a PostgreSQL-backed table linked to the proposal
    queue by ``proposal_id``. The interface is intentionally shaped for
    a drop-in swap (``record`` / ``get`` / ``list`` / ``size``).
    """

    def __init__(self, max_entries: int = 500):
        self._items: list[OptimizerApproval] = []
        self._max = max(1, int(max_entries))

    def record(self, approval: OptimizerApproval) -> None:
        self._items.append(approval)
        if len(self._items) > self._max:
            self._items = self._items[-self._max:]

    def get(self, proposal_id: str) -> OptimizerApproval | None:
        # Newest first — if the same proposal_id was re-decided (shouldn't
        # happen in practice; the queue dequeues on first decision), the
        # latest row wins.
        for a in reversed(self._items):
            if a.proposal_id == proposal_id:
                return a
        return None

    def list(self, limit: int = 50) -> list[OptimizerApproval]:
        return list(self._items[-max(0, int(limit)):])

    def size(self) -> int:
        return len(self._items)

    def clear(self) -> None:
        self._items.clear()


# ─── Pydantic request models ──────────────────────────────────────────
class OptimizerApproveBody(BaseModel):
    """Operator approval payload. ``actor_role`` is the operator's
    claim, not the Optimizer's (the Optimizer has no claim)."""

    actor_role: str = Field(
        ...,
        description="The operator's role claim — must be SME_L6 or higher.",
    )
    operator_id: str = Field(
        ...,
        min_length=1,
        description="Operator identifier (CET handle) for audit linking.",
    )
    confirm_ashrae: bool = Field(
        False,
        description=(
            "The operator must explicitly confirm the projected ASHRAE "
            "distance is within tolerance before actuation. Brief §6."
        ),
    )


class OptimizerRejectBody(BaseModel):
    """Operator rejection payload. The reason is required (feeds the
    optional 2.2 learning loop)."""

    actor_role: str = Field(
        ...,
        description="The operator's role claim — must be SME_L6 or higher.",
    )
    operator_id: str = Field(..., min_length=1)
    reason: str = Field(
        ...,
        min_length=1,
        description="Required rejection rationale; recorded in the audit.",
    )


# ─── Router ───────────────────────────────────────────────────────────
router = APIRouter(prefix="/api/optimizer", tags=["optimizer"])


def _get_optimizer_service(request: Request) -> OptimizerService:
    svc = getattr(request.app.state, "optimizer_service", None)
    if svc is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Optimizer service not running — set "
                "DC_EPMS_OPTIMIZER_ENABLED=true and restart the backend "
                "to enable Epic 2 Batches 2.B/2.C."
            ),
        )
    return svc


def _get_approval_log(request: Request) -> ApprovalLog:
    log_ = getattr(request.app.state, "optimizer_approval_log", None)
    if log_ is None:
        raise HTTPException(
            status_code=503,
            detail="Optimizer approval log not initialised.",
        )
    return log_


def _get_bms_write_fn(request: Request) -> BmsWriteFn:
    fn = getattr(request.app.state, "optimizer_bms_write_fn", None)
    if fn is None:
        raise HTTPException(
            status_code=503,
            detail="BMS write seam not wired on app.state.",
        )
    return fn


def _require_sme_l6(actor_role: str, action: str) -> None:
    """Stricter than ``require_actor_role`` — actor_role MUST be present
    AND rank ≥ SME_L6. The optimizer endpoints actuate critical control
    surfaces; the enforce-when-present policy is not appropriate here."""
    if not actor_role:
        raise HTTPException(
            status_code=400,
            detail=f"actor_role required for {action} (no enforce-when-present here)",
        )
    require_actor_role(actor_role, RANK_SME_L6, action)


def _refuse_safety_veto(qp: QueuedProposal) -> None:
    """Defence in depth (S-DET-02). The 2.B tick() already drops
    `hard_stop` proposals before they reach the queue; if one shows up
    here anyway, refuse the actuation."""
    if qp.safety_officer_veto:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Proposal {qp.proposal.proposal_id} carries an active "
                "Safety Officer VETO — the uncrossable HARD_STOP "
                "outranks operator approval per ADR-006. The proposal "
                "should not have been in the queue; logging an anomaly."
            ),
        )


@router.get("/proposals")
async def list_proposals(request: Request, limit: int = 50) -> dict[str, Any]:
    """Return the queued proposals awaiting operator review."""
    svc = _get_optimizer_service(request)
    return {
        "proposals": [qp.to_dict() for qp in svc.queue.list(limit=limit)],
        "queue_size": svc.queue.size(),
    }


@router.get("/approvals/{proposal_id}")
async def get_approval(proposal_id: str, request: Request) -> dict[str, Any]:
    """Fetch the operator decision row for a given proposal UUID."""
    log_ = _get_approval_log(request)
    approval = log_.get(proposal_id)
    if approval is None:
        raise HTTPException(
            status_code=404,
            detail=f"No approval recorded for proposal {proposal_id!r}.",
        )
    return approval.to_dict()


@router.get("/approvals")
async def list_approvals(request: Request, limit: int = 50) -> dict[str, Any]:
    """Return recent operator decision rows (newest at the end)."""
    log_ = _get_approval_log(request)
    return {
        "approvals": [a.to_dict() for a in log_.list(limit=limit)],
        "total": log_.size(),
    }


@router.post("/approve/{proposal_id}")
async def approve_proposal(
    proposal_id: str,
    body: OptimizerApproveBody = Body(...),
    request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Operator approves a queued proposal.

    Authorisation:
      * ``actor_role`` MUST be present AND rank ≥ SME_L6 (HTTP 403 else).
      * ``confirm_ashrae=true`` MUST be set (HTTP 400 else).
      * The proposal MUST be in the queue (HTTP 404 else).
      * The proposal MUST NOT carry an active Safety Officer veto
        (HTTP 409 else — defence in depth).
      * A BMS tag mapping for the surface MUST exist (HTTP 422 else).

    On success: the proposal is dequeued, a BMS write is issued with
    the operator's ``actor_role``, an ``OptimizerApproval`` row is
    recorded, and the approval (incl. the BMS write result) is returned.
    """
    _require_sme_l6(body.actor_role, "Optimizer approval")
    if not body.confirm_ashrae:
        raise HTTPException(
            status_code=400,
            detail=(
                "confirm_ashrae=true is required — the operator must "
                "confirm the sandbox-projected ASHRAE distance is "
                "within tolerance before actuation (brief §6)."
            ),
        )

    svc = _get_optimizer_service(request)
    log_ = _get_approval_log(request)
    bms_write_fn = _get_bms_write_fn(request)

    qp = svc.queue.pop_by_id(proposal_id)
    if qp is None:
        raise HTTPException(
            status_code=404,
            detail=f"Proposal {proposal_id!r} not in queue (already decided?).",
        )
    _refuse_safety_veto(qp)

    tag_id = SURFACE_TO_BMS_TAG.get(qp.proposal.surface)
    if tag_id is None:
        # Re-enqueue so the proposal isn't lost.
        svc.queue.enqueue(qp)
        raise HTTPException(
            status_code=422,
            detail=(
                f"No BMS tag mapping for surface {qp.proposal.surface!r}. "
                "Extend SURFACE_TO_BMS_TAG before approving."
            ),
        )

    # Critical actuation — the OPERATOR's claim authorises this, not the
    # Optimizer's. bms_write_fn is the only seam from the Optimizer code
    # path to the BMS write path (S-SEC-02).
    #
    # S-PROPOSER-01: stamp the proposal_id onto the forensic ledger entry
    # so the AI → consensus → operator → write chain is end-to-end
    # queryable by UUID (ADR-011). The seam is wrapped by
    # ``backend.ledger.wrap_bms_write_fn`` in main.py lifespan; here we
    # only set the context.
    import asyncio as _asyncio

    from backend.ledger import reset_proposal_context, set_proposal_context
    _ctx_token = set_proposal_context(proposal_id)
    try:
        success, message = await _asyncio.to_thread(
            bms_write_fn,
            tag_id, qp.proposal.proposed_value, body.operator_id,
        )
    except Exception as e:
        log.error("[optimizer] BMS write seam raised: %s", e, exc_info=True)
        success, message = False, f"BMS write seam exception: {e!r}"
    finally:
        reset_proposal_context(_ctx_token)

    approval = OptimizerApproval(
        proposal_id=proposal_id,
        decision=DECISION_APPROVED,
        operator_id=body.operator_id,
        actor_role=body.actor_role,
        decision_at=time.time(),
        reason="",
        bms_write_success=bool(success),
        bms_write_message=str(message),
        bms_tag_id=tag_id,
        approval_id=str(uuid.uuid4()),
    )
    log_.record(approval)
    log.info(
        "[optimizer] %s by %s (role %s): %s → write success=%s tag=%s",
        DECISION_APPROVED, body.operator_id, body.actor_role,
        proposal_id, success, tag_id,
    )
    return approval.to_dict()


@router.post("/reject/{proposal_id}")
async def reject_proposal(
    proposal_id: str,
    body: OptimizerRejectBody = Body(...),
    request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Operator rejects a queued proposal.

    Authorisation:
      * ``actor_role`` MUST be present AND rank ≥ SME_L6 (HTTP 403 else).
      * ``reason`` MUST be non-empty (HTTP 422 from Pydantic).
      * The proposal MUST be in the queue (HTTP 404 else).

    On success: the proposal is dequeued, an ``OptimizerApproval`` row
    (``decision="rejected"``) is recorded with the rationale. No BMS
    write is attempted.
    """
    _require_sme_l6(body.actor_role, "Optimizer rejection")

    svc = _get_optimizer_service(request)
    log_ = _get_approval_log(request)

    qp = svc.queue.pop_by_id(proposal_id)
    if qp is None:
        raise HTTPException(
            status_code=404,
            detail=f"Proposal {proposal_id!r} not in queue (already decided?).",
        )

    approval = OptimizerApproval(
        proposal_id=proposal_id,
        decision=DECISION_REJECTED,
        operator_id=body.operator_id,
        actor_role=body.actor_role,
        decision_at=time.time(),
        reason=body.reason.strip(),
        bms_write_success=None,
        bms_write_message=None,
        bms_tag_id=None,
        approval_id=str(uuid.uuid4()),
    )
    log_.record(approval)
    log.info(
        "[optimizer] %s by %s (role %s): %s — reason: %s",
        DECISION_REJECTED, body.operator_id, body.actor_role,
        proposal_id, approval.reason,
    )
    return approval.to_dict()


# ─── Wiring ──────────────────────────────────────────────────────────
def register_optimizer_routes(
    app: FastAPI,
    *,
    bms_write_fn: BmsWriteFn,
    approval_log: ApprovalLog | None = None,
) -> None:
    """Mount the optimizer routes onto ``app`` and inject the BMS-write
    seam + the approval log on ``app.state``.

    Idempotent: a second call updates the seams but does not double-
    mount the router. Per the Epic 2 brief and S-SEC-02 / ADR-006,
    the ``bms_write_fn`` is the ONLY linkage between the Optimizer
    code path and the BMS write path; main.py wires it to the live
    BMS connector, tests pass a mock.
    """
    app.state.optimizer_bms_write_fn = bms_write_fn
    if approval_log is None:
        approval_log = ApprovalLog()
    app.state.optimizer_approval_log = approval_log
    if not getattr(app.state, "_optimizer_routes_registered", False):
        app.include_router(router)
        app.state._optimizer_routes_registered = True
        log.info(
            "Optimizer routes registered: 4 endpoints under "
            "/api/optimizer (SME_L6 gate on approve+reject)",
        )
