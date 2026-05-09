"""Integration tests for CMMS Core v1.0 (Sprint 6 Fase 2+3).

Coverage:
  - DB schema: assets + work_orders tables exist with expected columns
  - Repository CRUD via MockCMMSRepository (fast, no live DB needed)
  - Asset seeder produces correct path, redundancy_pillar, telemetry_channels
  - Work order LOR / priority / procedure_class derivation
  - Asset → MOP linkage via hardcoded heuristic
  - Status transitions (pending_approval -> approved / rejected)
  - Filtering: by asset_type, status, priority, lor_min
  - Health aggregate view shape
  - Idempotent asset upsert
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.cmms_models import (
    Asset,
    CreateWorkOrderRequest,
    WorkOrder,
)
from backend.cmms_repository import (
    AssetNotFoundError,
    MockCMMSRepository,
    WorkOrderNotFoundError,
    WorkOrderStateConflictError,
)
from backend.cmms_seeder import (
    ASSET_TYPE_CRITICALITY,
    ASSET_TYPE_TO_MOP,
    _derive_path,
    _derive_redundancy_pillar,
    _derive_telemetry_channels,
    seed_assets_from_site_model,
)
from backend.site_model import SiteModel


PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ─────────────────────────────────────────────────────────────────────
#  Fixtures
# ─────────────────────────────────────────────────────────────────────
@pytest.fixture
def site_model() -> SiteModel:
    sm = SiteModel(PROJECT_ROOT / "config" / "site_model.yml")
    sm.load()
    return sm


@pytest.fixture
def repo() -> MockCMMSRepository:
    return MockCMMSRepository()


# ─────────────────────────────────────────────────────────────────────
#  Asset CRUD + Tesla/SpaceX Vision fields
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_asset_upsert_round_trip(repo):
    asset = Asset(
        asset_id="ups_a",
        display_name="UPS A",
        asset_type="ups",
        path="A",
        redundancy_pillar="2N",
        telemetry_channels=["ups_a:voltage_v_phase_ab", "ups_a:ups_soc_pct"],
        criticality_class="critical",
        linked_mop_id="T4-MOP-UPS-001",
    )
    await repo.upsert_asset_async(asset)
    fetched = await repo.get_asset_async("ups_a")
    assert fetched.asset_id == "ups_a"
    assert fetched.path == "A"
    assert fetched.redundancy_pillar == "2N"
    assert fetched.criticality_class == "critical"
    assert fetched.linked_mop_id == "T4-MOP-UPS-001"
    assert "ups_a:voltage_v_phase_ab" in fetched.telemetry_channels


@pytest.mark.asyncio
async def test_asset_not_found_raises(repo):
    with pytest.raises(AssetNotFoundError):
        await repo.get_asset_async("nonexistent")


@pytest.mark.asyncio
async def test_idempotent_upsert_does_not_duplicate(repo):
    asset = Asset(asset_id="chiller_1", display_name="Chiller 1", asset_type="chiller")
    await repo.upsert_asset_async(asset)
    await repo.upsert_asset_async(asset)  # second time
    listed = await repo.list_assets_async()
    assert sum(1 for a in listed if a.asset_id == "chiller_1") == 1


@pytest.mark.asyncio
async def test_list_assets_with_filter(repo):
    await repo.upsert_asset_async(Asset(
        asset_id="ups_a", display_name="UPS A", asset_type="ups",
        path="A", criticality_class="critical",
    ))
    await repo.upsert_asset_async(Asset(
        asset_id="rack_a_01", display_name="Rack A-01", asset_type="it_rack",
        path="A", criticality_class="medium",
    ))
    ups_only = await repo.list_assets_async(asset_type="ups")
    assert len(ups_only) == 1 and ups_only[0].asset_id == "ups_a"
    crit_only = await repo.list_assets_async(criticality_class="critical")
    assert len(crit_only) == 1


# ─────────────────────────────────────────────────────────────────────
#  Seeder: Tesla/SpaceX vision metadata
# ─────────────────────────────────────────────────────────────────────
def test_path_heuristic_a_b_phase2():
    assert _derive_path("ups_a", {}) == "A"
    assert _derive_path("ats_b", {}) == "B"
    assert _derive_path("rack_a_01_05", {}) == "A"
    assert _derive_path("rack_d_01_01", {}) == "C2-P2"
    assert _derive_path("utility_feed_a", {}) == "A"
    assert _derive_path("chiller_1", {}) is None  # facility-wide


def test_redundancy_pillar_heuristic():
    assert _derive_redundancy_pillar("ups", {}) == "2N"
    assert _derive_redundancy_pillar("chiller", {}) == "N+1"
    assert _derive_redundancy_pillar("it_rack", {}) == "2N"
    assert _derive_redundancy_pillar("workstation", {}) is None


def test_telemetry_channels_for_ups():
    chans = _derive_telemetry_channels("ups", "ups_a")
    assert "ups_a:voltage_v_phase_ab" in chans
    assert "ups_a:ups_soc_pct" in chans
    assert "ups_a:batt_runtime_min" in chans
    assert len(chans) == 5  # 3 phase + soc + runtime


def test_telemetry_channels_for_workstation_empty():
    """workstation is NOT an emitting type in telemetry_simulator."""
    assert _derive_telemetry_channels("workstation", "bms_master") == []


def test_criticality_for_ups_is_critical():
    assert ASSET_TYPE_CRITICALITY["ups"] == "critical"
    assert ASSET_TYPE_CRITICALITY["workstation"] == "low"
    assert ASSET_TYPE_CRITICALITY["chiller"] == "critical"


def test_mop_linkage_heuristic():
    assert ASSET_TYPE_TO_MOP["ups"] == "T4-MOP-UPS-001"
    assert ASSET_TYPE_TO_MOP["chiller"] == "T4-MOP-CHI-001"
    assert "workstation" not in ASSET_TYPE_TO_MOP  # no MOP for non-critical


@pytest.mark.asyncio
async def test_seeder_populates_from_site_model(repo, site_model):
    counters = await seed_assets_from_site_model(repo, site_model)
    assert counters["upserted"] >= 60, f"expected >=60 assets seeded, got {counters['upserted']}"
    # Verify a known asset got the expected vision fields
    ups_a = await repo.get_asset_async("ups_a")
    assert ups_a.asset_type == "ups"
    assert ups_a.path == "A"
    assert ups_a.redundancy_pillar == "2N"
    assert ups_a.criticality_class == "critical"
    assert ups_a.linked_mop_id == "T4-MOP-UPS-001"
    assert "ups_a:voltage_v_phase_ab" in ups_a.telemetry_channels


# ─────────────────────────────────────────────────────────────────────
#  WorkOrder lifecycle
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_work_order_save_and_retrieve(repo):
    await repo.upsert_asset_async(Asset(
        asset_id="ups_a", display_name="UPS A", asset_type="ups",
        criticality_class="critical",
    ))
    wo = WorkOrder(
        work_order_id="WO-20260509-test1",
        timestamp=datetime.now(timezone.utc),
        asset_id="ups_a",
        asset_type_at_creation="ups",
        work_class="CM",
        lor=15,
        trigger_source="manual",
        issue_summary="Test WO for unit tests",
        priority="P2",
        draft_json={"test": True},
    )
    await repo.save_work_order_async(wo)
    fetched = await repo.get_work_order_async("WO-20260509-test1")
    assert fetched.asset_id == "ups_a"
    assert fetched.lor == 15
    assert fetched.priority == "P2"
    assert fetched.status == "pending_approval"


@pytest.mark.asyncio
async def test_work_order_not_found(repo):
    with pytest.raises(WorkOrderNotFoundError):
        await repo.get_work_order_async("nonexistent")


@pytest.mark.asyncio
async def test_work_order_approve_transition(repo):
    wo = WorkOrder(
        work_order_id="WO-X", timestamp=datetime.now(timezone.utc),
        asset_id="ups_a", asset_type_at_creation="ups",
        work_class="CM", lor=10, trigger_source="manual",
        issue_summary="x", draft_json={},
    )
    await repo.save_work_order_async(wo)
    updated = await repo.transition_status_async("WO-X", "approved", "wilmer")
    assert updated.status == "approved"
    assert updated.approved_by_cet == "wilmer"


@pytest.mark.asyncio
async def test_work_order_reject_transition(repo):
    wo = WorkOrder(
        work_order_id="WO-Y", timestamp=datetime.now(timezone.utc),
        asset_id="ups_a", asset_type_at_creation="ups",
        work_class="EM", lor=20, trigger_source="manual",
        issue_summary="y", draft_json={},
    )
    await repo.save_work_order_async(wo)
    updated = await repo.transition_status_async(
        "WO-Y", "rejected", "wilmer", rejection_reason="needs more info",
    )
    assert updated.status == "rejected"
    assert updated.rejection_reason == "needs more info"


# ─── DC-EPMS-040: ADR-006 audit-trail integrity (re-approve guard) ────
@pytest.mark.asyncio
async def test_reapprove_already_approved_raises_conflict(repo):
    """ADR-006: re-approving a signed WO must NOT silently overwrite
    approved_by_cet. The state machine refuses with 409 Conflict so a
    second CET cannot hijack the audit trail."""
    wo = WorkOrder(
        work_order_id="WO-AT-1", timestamp=datetime.now(timezone.utc),
        asset_id="ups_a", asset_type_at_creation="ups",
        work_class="CM", lor=16, trigger_source="predictive_kalman",
        issue_summary="audit-trail probe", draft_json={},
    )
    await repo.save_work_order_async(wo)
    first = await repo.transition_status_async("WO-AT-1", "approved", "alice")
    assert first.approved_by_cet == "alice"

    with pytest.raises(WorkOrderStateConflictError) as excinfo:
        await repo.transition_status_async("WO-AT-1", "approved", "mallory")
    err = excinfo.value
    assert err.wo_id == "WO-AT-1"
    assert err.current_status == "approved"
    assert err.current_cet == "alice"
    assert err.attempted == "approved"

    fetched = await repo.get_work_order_async("WO-AT-1")
    assert fetched.approved_by_cet == "alice", \
        "original CET signature must be preserved across the failed re-approve"


@pytest.mark.asyncio
async def test_reject_already_approved_raises_conflict(repo):
    """Same guard for reject path — once a WO is approved, it cannot
    be rejected. (Cancellation is a separate transition.)"""
    wo = WorkOrder(
        work_order_id="WO-AT-2", timestamp=datetime.now(timezone.utc),
        asset_id="chiller_1", asset_type_at_creation="chiller",
        work_class="CM", lor=12, trigger_source="manual",
        issue_summary="audit-trail probe 2", draft_json={},
    )
    await repo.save_work_order_async(wo)
    await repo.transition_status_async("WO-AT-2", "approved", "alice")

    with pytest.raises(WorkOrderStateConflictError) as excinfo:
        await repo.transition_status_async(
            "WO-AT-2", "rejected", "mallory", rejection_reason="trying to undo",
        )
    assert excinfo.value.current_status == "approved"

    fetched = await repo.get_work_order_async("WO-AT-2")
    assert fetched.status == "approved"
    assert fetched.rejection_reason is None


@pytest.mark.asyncio
async def test_reapprove_after_reject_raises_conflict(repo):
    """A rejected WO is terminal — cannot be flipped back to approved."""
    wo = WorkOrder(
        work_order_id="WO-AT-3", timestamp=datetime.now(timezone.utc),
        asset_id="ups_b", asset_type_at_creation="ups",
        work_class="EM", lor=20, trigger_source="manual",
        issue_summary="audit-trail probe 3", draft_json={},
    )
    await repo.save_work_order_async(wo)
    await repo.transition_status_async(
        "WO-AT-3", "rejected", "alice", rejection_reason="duplicate",
    )

    with pytest.raises(WorkOrderStateConflictError):
        await repo.transition_status_async("WO-AT-3", "approved", "mallory")


@pytest.mark.asyncio
async def test_in_progress_does_not_overwrite_approved_cet(repo):
    """Latching invariant: subsequent state transitions must not touch
    approved_by_cet. Only the first 'approved' transition writes it."""
    wo = WorkOrder(
        work_order_id="WO-AT-4", timestamp=datetime.now(timezone.utc),
        asset_id="rpp_a_01", asset_type_at_creation="rpp",
        work_class="CM", lor=20, trigger_source="predictive_kalman",
        issue_summary="audit-trail probe 4", draft_json={},
    )
    await repo.save_work_order_async(wo)
    await repo.transition_status_async("WO-AT-4", "approved", "alice")
    await repo.transition_status_async("WO-AT-4", "in_progress", "bob")
    fetched = await repo.get_work_order_async("WO-AT-4")
    assert fetched.status == "in_progress"
    assert fetched.approved_by_cet == "alice"      # original approver preserved
    assert fetched.assigned_to_cet == "bob"         # technician latched separately


@pytest.mark.asyncio
async def test_list_work_orders_filtering(repo):
    for i, sev in enumerate([("P1", 25, "predictive_kalman"),
                             ("P2", 12, "manual"),
                             ("P3", 6, "scheduled_pm")]):
        prio, lor, src = sev
        await repo.save_work_order_async(WorkOrder(
            work_order_id=f"WO-{i}",
            timestamp=datetime.now(timezone.utc),
            asset_id="ups_a", asset_type_at_creation="ups",
            work_class="CM", lor=lor, trigger_source=src,
            issue_summary=f"#{i}", priority=prio, draft_json={},
        ))
    p1 = await repo.list_work_orders_async(priority="P1")
    assert len(p1) == 1
    high_lor = await repo.list_work_orders_async(lor_min=12)
    assert len(high_lor) == 2  # P1 and P2
    predictive = await repo.list_work_orders_async(trigger_source="predictive_kalman")
    assert len(predictive) == 1


# ─────────────────────────────────────────────────────────────────────
#  Health aggregate
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_health_aggregate_groups_by_path_pillar_type(repo):
    await repo.upsert_asset_async(Asset(
        asset_id="ups_a", display_name="UPS A", asset_type="ups",
        path="A", redundancy_pillar="2N", health_state="healthy",
    ))
    await repo.upsert_asset_async(Asset(
        asset_id="ups_b", display_name="UPS B", asset_type="ups",
        path="B", redundancy_pillar="2N", health_state="degraded",
    ))
    rows = await repo.get_health_aggregate_async()
    assert len(rows) == 2
    by_path = {r.path: r for r in rows}
    assert by_path["A"].healthy_count == 1
    assert by_path["B"].degraded_count == 1
