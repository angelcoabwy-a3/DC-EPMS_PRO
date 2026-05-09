"""Tests for backend.cmms_predictive_trigger (Sprint 9.1).

Coverage:
  - Sustain logic: counter increments per anomalous window, resets on
    non-anomalous window
  - Threshold trigger: WO created at sustain_threshold = 3
  - WO is NOT created before threshold
  - Dedup: second sustained anomaly on same asset does NOT create
    duplicate WO while first is still open
  - Channel -> asset_id resolution via "asset_id:metric" parsing
  - Unknown asset (no matching row): WO NOT created, sustain reset
  - Priority + LOR + procedure_class derivation from asset criticality
  - Telemetry snapshot fields populated
  - Stats reporting
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.cmms_models import Asset, WorkOrder
from backend.cmms_predictive_trigger import (
    PredictiveTrigger,
    get_predictive_trigger,
    reset_predictive_trigger,
)
from backend.cmms_repository import MockCMMSRepository


# ─────────────────────────────────────────────────────────────────────
#  Fixtures
# ─────────────────────────────────────────────────────────────────────
@pytest.fixture
def repo():
    return MockCMMSRepository()


@pytest.fixture
async def repo_with_assets(repo):
    """Mock repo seeded with the canonical Path C2 ups + chiller."""
    await repo.upsert_asset_async(Asset(
        asset_id="ups_a",
        display_name="UPS A",
        asset_type="ups",
        path="A",
        redundancy_pillar="2N",
        telemetry_channels=["ups_a:voltage_v_phase_ab", "ups_a:ups_soc_pct"],
        criticality_class="critical",
        linked_mop_id="T4-MOP-UPS-001",
    ))
    await repo.upsert_asset_async(Asset(
        asset_id="chiller_1",
        display_name="Chiller 1",
        asset_type="chiller",
        path=None,
        redundancy_pillar="N+1",
        telemetry_channels=["chiller_1:chiller_LWT_c", "chiller_1:chiller_cop"],
        criticality_class="critical",
        linked_mop_id="T4-MOP-CHI-001",
    ))
    await repo.upsert_asset_async(Asset(
        asset_id="bms_master",
        display_name="BMS Master",
        asset_type="workstation",
        criticality_class="low",
    ))
    return repo


@pytest.fixture
def trigger(repo_with_assets):
    return PredictiveTrigger(repo_with_assets, sustain_threshold=3)


def _anom(max_z=4.5, mean_z=3.2, last=482.0, n=5):
    return {
        "n_emissions": n,
        "max_z": max_z,
        "mean_z": mean_z,
        "is_anomalous": True,
        "last_emission": last,
    }


def _ok(last=480.0, n=5):
    return {
        "n_emissions": n,
        "max_z": 0.4,
        "mean_z": 0.2,
        "is_anomalous": False,
        "last_emission": last,
    }


# ─────────────────────────────────────────────────────────────────────
#  Sustain logic
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_no_wo_below_threshold(trigger, repo_with_assets):
    """1 and 2 sustained windows must NOT trigger WO yet."""
    await trigger.handle_payload({"ups_a:voltage_v_phase_ab": _anom()})
    await trigger.handle_payload({"ups_a:voltage_v_phase_ab": _anom()})
    wos = await repo_with_assets.list_work_orders_async(asset_id="ups_a")
    assert len(wos) == 0
    assert trigger.stats["wos_created"] == 0


@pytest.mark.asyncio
async def test_wo_created_at_threshold(trigger, repo_with_assets):
    """Exactly N=3 sustained windows triggers a WO."""
    for _ in range(3):
        await trigger.handle_payload({"ups_a:voltage_v_phase_ab": _anom(max_z=5.2)})
    wos = await repo_with_assets.list_work_orders_async(asset_id="ups_a")
    assert len(wos) == 1
    wo = wos[0]
    assert wo.trigger_source == "predictive_kalman"
    assert wo.status == "pending_approval"
    assert wo.work_class == "CM"
    assert "max_z=5.2" in wo.issue_summary or "max_z=5.20" in wo.issue_summary


@pytest.mark.asyncio
async def test_non_anomalous_resets_sustain(trigger, repo_with_assets):
    """is_anomalous=False resets the counter; subsequent anomaly starts at 1."""
    await trigger.handle_payload({"ups_a:voltage_v_phase_ab": _anom()})
    await trigger.handle_payload({"ups_a:voltage_v_phase_ab": _anom()})
    # Reset
    await trigger.handle_payload({"ups_a:voltage_v_phase_ab": _ok()})
    # Two more anomalies (would have been 4 total, threshold) — but counter reset
    await trigger.handle_payload({"ups_a:voltage_v_phase_ab": _anom()})
    await trigger.handle_payload({"ups_a:voltage_v_phase_ab": _anom()})
    wos = await repo_with_assets.list_work_orders_async(asset_id="ups_a")
    assert len(wos) == 0


# ─────────────────────────────────────────────────────────────────────
#  Dedup
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_dedup_does_not_create_second_open_wo(trigger, repo_with_assets):
    """Once a predictive WO is open for an asset, no duplicate is created."""
    for _ in range(3):
        await trigger.handle_payload({"ups_a:voltage_v_phase_ab": _anom()})
    assert (await repo_with_assets.list_work_orders_async(asset_id="ups_a")).__len__() == 1

    # New sustained anomaly (sustain reset to 0, builds back to 3)
    for _ in range(5):
        await trigger.handle_payload({"ups_a:voltage_v_phase_ab": _anom()})

    wos = await repo_with_assets.list_work_orders_async(asset_id="ups_a")
    assert len(wos) == 1, "dedup should prevent second WO while first is open"
    assert trigger.stats["dedup_skipped"] >= 1


@pytest.mark.asyncio
async def test_new_wo_after_first_closed(trigger, repo_with_assets):
    """If the first WO is closed (rejected/completed), a new one CAN form."""
    for _ in range(3):
        await trigger.handle_payload({"ups_a:voltage_v_phase_ab": _anom()})
    wos = await repo_with_assets.list_work_orders_async(asset_id="ups_a")
    first_id = wos[0].work_order_id

    # Close the first WO
    await repo_with_assets.transition_status_async(first_id, "completed", "wilmer")

    # New sustained anomaly should create a second WO
    for _ in range(3):
        await trigger.handle_payload({"ups_a:voltage_v_phase_ab": _anom(max_z=6.0)})

    all_wos = await repo_with_assets.list_work_orders_async(asset_id="ups_a")
    assert len(all_wos) == 2


# ─────────────────────────────────────────────────────────────────────
#  Channel -> asset
# ─────────────────────────────────────────────────────────────────────
def test_channel_to_asset_id_basic():
    assert PredictiveTrigger._channel_to_asset_id("ups_a:voltage_v_phase_ab") == "ups_a"
    assert PredictiveTrigger._channel_to_asset_id("rack_a_01_05:gpu_Tj_c") == "rack_a_01_05"
    assert PredictiveTrigger._channel_to_asset_id("chiller_1:chiller_LWT_c") == "chiller_1"


def test_channel_to_asset_id_malformed():
    assert PredictiveTrigger._channel_to_asset_id("no_colon_here") is None
    assert PredictiveTrigger._channel_to_asset_id(":metric_only") is None
    assert PredictiveTrigger._channel_to_asset_id("") is None


@pytest.mark.asyncio
async def test_unknown_asset_does_not_create_wo(trigger, repo_with_assets):
    """Channel pointing to nonexistent asset: WO not created, sustain reset."""
    for _ in range(3):
        await trigger.handle_payload({"phantom_asset:fake_metric": _anom()})
    wos = await repo_with_assets.list_work_orders_async()
    assert len(wos) == 0
    # Sustain should be reset post-attempt
    assert "phantom_asset:fake_metric" not in trigger.stats["currently_sustaining"]


# ─────────────────────────────────────────────────────────────────────
#  WO derivation (priority + LOR + telemetry snapshot)
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_critical_asset_escalates_priority(trigger, repo_with_assets):
    """ups_a is critical → P2 minimum."""
    for _ in range(3):
        await trigger.handle_payload({"ups_a:voltage_v_phase_ab": _anom()})
    wo = (await repo_with_assets.list_work_orders_async(asset_id="ups_a"))[0]
    assert wo.priority in ("P1", "P2"), f"got {wo.priority}"


@pytest.mark.asyncio
async def test_low_criticality_no_escalation_to_p1(repo_with_assets):
    """workstation (low criticality): NOT escalated to P1 even at LOR=16.

    LOR=16 lands at P2 baseline. Low criticality stays at P2; only
    critical assets escalate P2 -> P1 when LOR >= 15.
    """
    # Critical asset baseline check
    critical_trig = PredictiveTrigger(repo_with_assets, sustain_threshold=3)
    for _ in range(3):
        await critical_trig.handle_payload({"ups_a:voltage_v_phase_ab": _anom()})
    crit_wo = (await repo_with_assets.list_work_orders_async(asset_id="ups_a"))[0]
    # Critical + LOR=16 -> P1 (escalated)
    assert crit_wo.priority == "P1"

    # Low-criticality asset: same payload, NO escalation
    low_trig = PredictiveTrigger(repo_with_assets, sustain_threshold=3)
    for _ in range(3):
        await low_trig.handle_payload({"bms_master:metric": _anom()})
    low_wo = (await repo_with_assets.list_work_orders_async(asset_id="bms_master"))[0]
    # Low + LOR=16 -> P2 (LOR-derived, no escalation)
    assert low_wo.priority == "P2"
    assert low_wo.priority != crit_wo.priority, (
        "low criticality must NOT match critical asset priority for same LOR"
    )


@pytest.mark.asyncio
async def test_telemetry_snapshot_populated(trigger, repo_with_assets):
    for _ in range(3):
        await trigger.handle_payload({"ups_a:voltage_v_phase_ab": _anom(max_z=4.7, last=475.0)})
    wo = (await repo_with_assets.list_work_orders_async(asset_id="ups_a"))[0]
    snap = wo.telemetry_snapshot_json
    assert snap is not None
    assert snap["channel_id"] == "ups_a:voltage_v_phase_ab"
    assert snap["max_z"] == 4.7
    assert snap["last_emission"] == 475.0
    assert snap["sustained_for_windows"] == 3


@pytest.mark.asyncio
async def test_predictive_metadata_populated(trigger, repo_with_assets):
    for _ in range(3):
        await trigger.handle_payload({"chiller_1:chiller_LWT_c": _anom(max_z=8.0)})
    wo = (await repo_with_assets.list_work_orders_async(asset_id="chiller_1"))[0]
    md = wo.predictive_metadata
    assert md is not None
    assert md["channel_id"] == "chiller_1:chiller_LWT_c"
    assert md["metric"] == "chiller_LWT_c"
    assert md["max_z"] == 8.0
    assert md["sustain_threshold"] == 3
    assert md["asset_criticality"] == "critical"


@pytest.mark.asyncio
async def test_chiller_predictive_links_correct_mop(trigger, repo_with_assets):
    for _ in range(3):
        await trigger.handle_payload({"chiller_1:chiller_LWT_c": _anom()})
    wo = (await repo_with_assets.list_work_orders_async(asset_id="chiller_1"))[0]
    assert wo.linked_mop_id == "T4-MOP-CHI-001"
    assert wo.mop_resolution_method == "hardcoded"


@pytest.mark.asyncio
async def test_ups_predictive_requires_loto(trigger, repo_with_assets):
    """Predictive WOs on energized assets infer LOTO requirement."""
    for _ in range(3):
        await trigger.handle_payload({"ups_a:voltage_v_phase_ab": _anom()})
    wo = (await repo_with_assets.list_work_orders_async(asset_id="ups_a"))[0]
    assert wo.requires_loto is True
    assert wo.procedure_class == "DMOP"


# ─────────────────────────────────────────────────────────────────────
#  Singleton lifecycle
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_singleton_lifecycle(repo_with_assets):
    reset_predictive_trigger()
    t1 = get_predictive_trigger(repo_with_assets)
    t2 = get_predictive_trigger()  # second call without repo
    assert t1 is t2
    reset_predictive_trigger()
    t3 = get_predictive_trigger(repo_with_assets)
    assert t3 is not t1


@pytest.mark.asyncio
async def test_get_without_init_raises():
    reset_predictive_trigger()
    with pytest.raises(RuntimeError, match="not initialized"):
        get_predictive_trigger()


# ─────────────────────────────────────────────────────────────────────
#  Defensive: empty payload / non-anomaly batch
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_empty_payload_does_nothing(trigger, repo_with_assets):
    await trigger.handle_payload({})
    assert trigger.stats["anomalies_seen"] == 0


@pytest.mark.asyncio
async def test_all_clean_payload_does_nothing(trigger, repo_with_assets):
    payload = {f"ups_a:metric_{i}": _ok() for i in range(5)}
    for _ in range(5):
        await trigger.handle_payload(payload)
    wos = await repo_with_assets.list_work_orders_async()
    assert len(wos) == 0
