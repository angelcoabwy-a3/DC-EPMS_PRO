"""
backend/cmms_routes.py
======================
FastAPI router for CMMS Core v1.0.

Endpoints (Sprint 6 Fase 3 + 7.1d-followup):
  GET   /api/cmms/assets                         List assets (filters)
  GET   /api/cmms/assets/{asset_id}              Single asset detail
  PATCH /api/cmms/assets/{asset_id}              Enrich with nameplate fields
  GET   /api/cmms/assets/health-aggregate        Per-path/pillar/type rollup
  GET   /api/cmms/work-orders                    List WOs (filters)
  GET   /api/cmms/work-orders/{wo_id}            Single WO detail
  POST  /api/cmms/work-orders                    Create WO from manual draft
  POST  /api/cmms/work-orders/{wo_id}/approve    CET approval transition
  POST  /api/cmms/work-orders/{wo_id}/reject     CET rejection transition
  POST  /api/cmms/trigger-maintenance            Convenience: WO from one call
  GET   /api/cmms/health                         Router health probe

The router uses app.state.cmms_repo (set in main.py lifespan) for the
backing repository. Routes never touch SQL directly.

Per ADR-006 Deterministic Sandbox: WO creation always lands in
'pending_approval'. Approval requires explicit POST.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request

from backend.cmms_classification import (
    compute_lor as _compute_lor,
    derive_priority as _derive_priority,
    derive_procedure_class as _derive_procedure_class,
    new_work_order_id as _wo_id,
)
from backend.cmms_models import (
    ApproveRejectRequest,
    AssetEnrichRequest,
    CreateWorkOrderRequest,
    RBACDeniedError,
    WorkOrder,
    assert_can_approve_work_order,
)
from backend.cmms_repository import (
    AssetNotFoundError,
    CMMSRepositoryError,
    PostgresCMMSRepository,
    WorkOrderNotFoundError,
    WorkOrderStateConflictError,
)
from backend.cmms_seeder import ASSET_TYPE_TO_MOP

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cmms", tags=["cmms"])


# ─── Internal helpers ────────────────────────────────────────────────
def _get_repo(request: Request) -> PostgresCMMSRepository:
    repo = getattr(request.app.state, "cmms_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="CMMS repository not initialized")
    return repo


# WO-classification helpers (_wo_id / _compute_lor / _derive_priority /
# _derive_procedure_class) consolidated into backend/cmms_classification.py
# (Phase 1 structural compaction) and imported above.


# ═══════════════════════════════════════════════════════════════════════
#  Health
# ═══════════════════════════════════════════════════════════════════════
@router.get("/health")
async def cmms_health(request: Request) -> dict[str, Any]:
    """Router liveness probe. Counts assets and open WOs."""
    repo = _get_repo(request)
    try:
        assets = await repo.list_assets_async(limit=10000)
        open_wos = await repo.list_work_orders_async(only_open=True, limit=10000)
        return {
            "status": "up",
            "asset_count": len(assets),
            "open_work_order_count": len(open_wos),
            "facility": "A3-Alpha Toronto Area",
        }
    except CMMSRepositoryError as e:
        return {"status": "degraded", "error": str(e)[:200]}


# ═══════════════════════════════════════════════════════════════════════
#  Assets
# ═══════════════════════════════════════════════════════════════════════
@router.get("/assets")
async def list_assets(
    request: Request,
    asset_type: str | None = Query(default=None),
    path: str | None = Query(default=None),
    criticality_class: str | None = Query(default=None),
    health_state: str | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=10000),
) -> dict[str, Any]:
    repo = _get_repo(request)
    try:
        assets = await repo.list_assets_async(
            asset_type=asset_type,
            path=path,
            criticality_class=criticality_class,
            health_state=health_state,
            limit=limit,
        )
    except CMMSRepositoryError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"count": len(assets), "assets": [a.model_dump(mode="json") for a in assets]}


@router.get("/assets/health-aggregate")
async def health_aggregate(request: Request) -> dict[str, Any]:
    """Per-path / pillar / asset_type health rollup. Drives HMI grid + SHI."""
    repo = _get_repo(request)
    try:
        rows = await repo.get_health_aggregate_async()
    except CMMSRepositoryError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"rows": [r.model_dump(mode="json") for r in rows]}


@router.get("/assets/{asset_id}")
async def get_asset(request: Request, asset_id: str) -> dict[str, Any]:
    repo = _get_repo(request)
    try:
        asset = await repo.get_asset_async(asset_id)
    except AssetNotFoundError:
        raise HTTPException(status_code=404, detail=f"asset '{asset_id}' not found") from None
    except CMMSRepositoryError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    open_wos = await repo.list_work_orders_async(asset_id=asset_id, only_open=True, limit=20)
    return {
        "asset": asset.model_dump(mode="json"),
        "open_work_orders": [w.model_dump(mode="json") for w in open_wos],
    }


@router.patch("/assets/{asset_id}")
async def enrich_asset(
    request: Request, asset_id: str, body: AssetEnrichRequest,
) -> dict[str, Any]:
    """Enrich an existing asset with nameplate-OCR'd fields.

    Sprint 7.1d-followup: closes the loop of the nameplate matcher.
    Operator extracts a nameplate, sees seed_new_asset because the
    target row has vendor=null/model=null, picks the canonical asset
    id, and writes the extracted data with this endpoint. After the
    write, re-running the nameplate matcher returns link_to_existing
    with a ~0.95 score.

    Only fields present in the body are written; the rest of the
    asset row is preserved. `serial` and `voltage_v` flow into
    `metadata_json` to align with the matcher's lookup keys.
    """
    from backend.rbac import require_actor_role
    require_actor_role(body.actor_role, 5, "enriching an asset")
    repo = _get_repo(request)
    try:
        asset = await repo.get_asset_async(asset_id)
    except AssetNotFoundError:
        raise HTTPException(status_code=404, detail=f"asset '{asset_id}' not found") from None
    except CMMSRepositoryError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    # Build the merge: copy existing asset, overlay only present fields
    # from the body, with serial + voltage_v going into metadata_json.
    updates: dict[str, Any] = {}
    if body.vendor is not None:
        updates["vendor"] = body.vendor.strip()
    if body.model is not None:
        updates["model"] = body.model.strip()
    if body.rated_capacity_kw is not None:
        updates["rated_capacity_kw"] = body.rated_capacity_kw
    if body.rated_capacity_unit is not None:
        updates["rated_capacity_unit"] = body.rated_capacity_unit.strip()

    new_metadata = dict(asset.metadata_json or {})
    if body.serial is not None:
        new_metadata["serial"] = body.serial.strip()
    if body.voltage_v is not None:
        new_metadata["voltage_nominal_v"] = body.voltage_v
    if body.enriched_by:
        new_metadata["enriched_by"] = body.enriched_by.strip()
    if new_metadata != (asset.metadata_json or {}):
        updates["metadata_json"] = new_metadata

    if not updates:
        # Nothing to write; return the asset as-is rather than failing.
        return {"asset": asset.model_dump(mode="json"), "fields_written": []}

    enriched = asset.model_copy(update=updates)
    try:
        await repo.upsert_asset_async(enriched)
    except CMMSRepositoryError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    log.info("Enriched %s with fields: %s",
             asset_id, sorted(updates.keys()))
    return {
        "asset": enriched.model_dump(mode="json"),
        "fields_written": sorted(updates.keys()),
    }


# ═══════════════════════════════════════════════════════════════════════
#  Work Orders
# ═══════════════════════════════════════════════════════════════════════
@router.get("/work-orders")
async def list_work_orders(
    request: Request,
    status: str | None = Query(default=None),
    asset_id: str | None = Query(default=None),
    trigger_source: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    lor_min: int | None = Query(default=None, ge=1, le=25),
    only_open: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    repo = _get_repo(request)
    try:
        wos = await repo.list_work_orders_async(
            status=status,
            asset_id=asset_id,
            trigger_source=trigger_source,
            priority=priority,
            lor_min=lor_min,
            only_open=only_open,
            limit=limit,
        )
    except CMMSRepositoryError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"count": len(wos), "work_orders": [w.model_dump(mode="json") for w in wos]}


@router.get("/work-orders/{wo_id}")
async def get_work_order(request: Request, wo_id: str) -> dict[str, Any]:
    repo = _get_repo(request)
    try:
        wo = await repo.get_work_order_async(wo_id)
    except WorkOrderNotFoundError:
        raise HTTPException(status_code=404, detail=f"work_order '{wo_id}' not found") from None
    except CMMSRepositoryError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return wo.model_dump(mode="json")


@router.post("/work-orders")
async def create_work_order(request: Request, body: CreateWorkOrderRequest) -> dict[str, Any]:
    """Create a new WO. Always lands in pending_approval (ADR-006)."""
    from backend.rbac import require_actor_role
    require_actor_role(body.actor_role, 4, "creating a work order")
    repo = _get_repo(request)

    # Resolve asset (validates asset_id exists)
    try:
        asset = await repo.get_asset_async(body.asset_id)
    except AssetNotFoundError:
        raise HTTPException(status_code=404, detail=f"asset '{body.asset_id}' not found") from None

    lor = _compute_lor(body.likelihood_idx, body.consequence_idx)
    priority = _derive_priority(lor, asset.criticality_class)
    proc_class = _derive_procedure_class(body.work_class_hint, body.requires_loto)
    linked_mop = asset.linked_mop_id or ASSET_TYPE_TO_MOP.get(asset.asset_type)
    mop_method = "hardcoded" if linked_mop else None

    now = datetime.now(UTC)
    wo = WorkOrder(
        work_order_id=_wo_id(),
        timestamp=now,
        asset_id=body.asset_id,
        asset_type_at_creation=asset.asset_type,
        work_class=body.work_class_hint,
        lor=lor,
        procedure_class=proc_class,
        linked_mop_id=linked_mop,
        linked_loto_audit_id=None,
        trigger_source=body.trigger_source,
        predictive_metadata=body.predictive_metadata,
        issue_summary=body.issue_summary,
        estimated_cost_usd=body.estimated_cost_usd,
        requires_loto=body.requires_loto,
        requires_oem_specialist=body.requires_oem_specialist,
        status="pending_approval",
        priority=priority,
        telemetry_snapshot_json=body.telemetry_snapshot_json,
        mop_resolution_method=mop_method,
        requested_by=body.requested_by,
        due_at=body.due_at,
        draft_json={
            "lor": lor,
            "lor_breakdown": {
                "likelihood_idx": body.likelihood_idx,
                "consequence_idx": body.consequence_idx,
                "asset_criticality": asset.criticality_class,
            },
            "linked_mop_id": linked_mop,
            "procedure_class": proc_class,
            "issue_summary": body.issue_summary,
        },
    )
    try:
        await repo.save_work_order_async(wo)
    except CMMSRepositoryError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    log.info("Created WO %s for %s (priority=%s, lor=%d)",
             wo.work_order_id, body.asset_id, priority, lor)
    return wo.model_dump(mode="json")


@router.post("/work-orders/{wo_id}/approve")
async def approve_wo(
    request: Request, wo_id: str, body: ApproveRejectRequest,
) -> dict[str, Any]:
    # F3-1: RBAC gate -- only SENIOR_TECH_L5 / SME_L6 may approve a WO.
    # The role is a client-supplied claim (no auth layer yet -- audit F3);
    # a missing / TECH_L4 actor_role is rejected with HTTP 403.
    try:
        assert_can_approve_work_order(body.actor_role)
    except RBACDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    repo = _get_repo(request)
    try:
        wo = await repo.transition_status_async(wo_id, "approved", body.cet_id)
    except WorkOrderNotFoundError:
        raise HTTPException(status_code=404, detail=f"work_order '{wo_id}' not found") from None
    except WorkOrderStateConflictError as e:
        # ADR-006: refuse to overwrite an existing CET signature.
        raise HTTPException(status_code=409, detail={
            "error": "state_conflict",
            "message": str(e),
            "current_status": e.current_status,
            "current_approved_by_cet": e.current_cet,
            "attempted": e.attempted,
        }) from e
    except CMMSRepositoryError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return wo.model_dump(mode="json")


@router.post("/work-orders/{wo_id}/reject")
async def reject_wo(
    request: Request, wo_id: str, body: ApproveRejectRequest,
) -> dict[str, Any]:
    # F3-1: RBAC gate -- rejecting a WO is an approval-authority decision,
    # gated to SENIOR_TECH_L5 / SME_L6 like approve.
    try:
        assert_can_approve_work_order(body.actor_role)
    except RBACDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    if not body.rejection_reason:
        raise HTTPException(status_code=400, detail="rejection_reason required for reject")
    repo = _get_repo(request)
    try:
        wo = await repo.transition_status_async(
            wo_id, "rejected", body.cet_id, rejection_reason=body.rejection_reason,
        )
    except WorkOrderNotFoundError:
        raise HTTPException(status_code=404, detail=f"work_order '{wo_id}' not found") from None
    except WorkOrderStateConflictError as e:
        raise HTTPException(status_code=409, detail={
            "error": "state_conflict",
            "message": str(e),
            "current_status": e.current_status,
            "attempted": e.attempted,
        }) from e
    except CMMSRepositoryError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return wo.model_dump(mode="json")


@router.post("/trigger-maintenance")
async def trigger_maintenance(
    request: Request, body: CreateWorkOrderRequest,
) -> dict[str, Any]:
    """Convenience endpoint: same as POST /work-orders but defaults to
    work_class=CM if user did not specify and the asset shows degraded
    health. Otherwise PM."""
    repo = _get_repo(request)
    try:
        asset = await repo.get_asset_async(body.asset_id)
    except AssetNotFoundError:
        raise HTTPException(status_code=404, detail=f"asset '{body.asset_id}' not found") from None

    if body.work_class_hint == "PM" and asset.health_state == "degraded":
        body = body.model_copy(update={"work_class_hint": "CM"})

    return await create_work_order(request, body)


# ═══════════════════════════════════════════════════════════════════════
#  Registration
# ═══════════════════════════════════════════════════════════════════════
def register_cmms_routes(
    app: FastAPI,
    repository: PostgresCMMSRepository,
) -> None:
    """Mount the router and stash the repo on app.state. Idempotent."""
    app.state.cmms_repo = repository
    if not getattr(app.state, "_cmms_router_registered", False):
        app.include_router(router)
        app.state._cmms_router_registered = True
    log.info("CMMS routes registered: 9 endpoints active under /api/cmms")
