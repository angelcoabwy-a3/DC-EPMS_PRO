"""
tests/test_device_control.py
============================
Release R3-A / R3-B -- backend/device_control.py.

  * Roster and capacity come from the closed design
    (config/power_plant.yml): 8 UPS and 9 generators per path.
  * Losses use P_out * (1 / eta - 1).
  * Authority, select-before-operate, interlocks.
  * MV bay switching only through forced procedures, two-person rule.
  * Routes: role from the session token, ledger chaining.
  * ADR-006: the agent stack never imports the control modules.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
# Same import path as tests/test_smoke.py (DC-EPMS-008 class).
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import (  # noqa: E402
    device_control as dc,
    mv_switching as mv,
)
from backend.auth.jwt_handler import issue_token, seed_demo_users  # noqa: E402
from backend.ledger import ForensicLedger  # noqa: E402
from backend.ledger.forensic_ledger import InMemoryPersistence  # noqa: E402

DESIGN_PATH = PROJECT_ROOT / "config" / "power_plant.yml"


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def tick(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def design() -> dict:
    return dc.load_design(DESIGN_PATH)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def ctl(design, clock) -> dc.DeviceController:
    return dc.DeviceController.from_design(design, clock=clock, wall_clock=clock)


def run(ctl, device_id: str, command: str, actor: str = "manager"):
    sel = ctl.select(device_id, command, actor)
    return ctl.operate(device_id, sel["select_token"], actor)


def remote(ctl, *ids: str) -> None:
    for device_id in ids:
        ctl.set_authority(device_id, dc.AUTH_REMOTE, "manager")


def start(ctl, clock, *ids: str) -> None:
    remote(ctl, *ids)
    for device_id in ids:
        run(ctl, device_id, "START")
    clock.tick(dc.CRANK_TIME_S + 0.1)
    ctl.snapshot_all()


def readings(ctl, device_id: str) -> dict:
    return {r["label"]: r["value"] for r in ctl.snapshot(device_id)["readings"]}


def isolate(ctl, bay_id: str) -> None:
    proc = ctl.start_procedure(bay_id, mv.GOAL_ISOLATE, "manager")
    for item in proc["steps"]:
        if item["two_person"]:
            ctl.witness_step(proc["procedure_id"], item["step"], "safety_a")
        ctl.execute_step(proc["procedure_id"], item["step"], "manager")


GENS_A = [f"genset_a_{n:02d}" for n in range(1, 10)]


class TestClosedDesign:
    def test_roster_matches_the_operator_decision(self, ctl):
        kinds = [d.kind for d in ctl.devices.values()]
        assert kinds.count(dc.KIND_UPS) == 16
        assert kinds.count(dc.KIND_GENERATOR) == 18
        assert kinds.count(dc.KIND_TRANSFER) == 2
        assert ctl.devices["ups_a_01"].model == "Trinergy 2500"
        assert ctl.devices["genset_b_09"].voltage_v == 13800
        assert set(ctl.bays) == {d.device_id for d in ctl.devices.values()
                                 if d.kind == dc.KIND_GENERATOR}

    def test_no_480v_ats_in_the_roster(self, ctl):
        assert not any(i.startswith("ats") for i in ctl.devices)
        labels = [i["label"] for i in ctl.snapshot("mvtc_a")["indications"]]
        assert labels == ["52-U utility incomer", "52-GM generator main", "ANSI 27 incomer undervoltage",
                          "52-U cubicle", "52-GM cubicle"]

    def test_ups_n_plus_1_inside_the_path(self, ctl):
        s = ctl.path_summary("a")
        assert s["ups_capacity_kw"] == 20000
        assert s["ups_n_ok"]
        assert s["ups_n_plus_1_ok"]

    def test_normal_2n_losses_use_the_correct_formula(self, ctl):
        # 8380 kW * (1 / 0.97 - 1) = 259.2 kW (operator doc: about 259 kW)
        assert ctl.path_summary("a")["ups_losses_kw"] == 259
        assert readings(ctl, "ups_a_01")["Losses (model)"] == pytest.approx(32.4, abs=0.1)
        assert readings(ctl, "ups_a_01")["Output load"] == pytest.approx(1048, abs=1)

    def test_full_path_losses_are_about_518_kw(self, ctl):
        ctl.inject_path_loss("a")
        s = ctl.path_summary("b")
        assert s["it_load_kw"] == 16760
        assert s["ups_losses_kw"] == 518
        assert readings(ctl, "ups_b_01")["Load"] == pytest.approx(83.8, abs=0.1)
        assert ctl.path_summary("a")["it_load_kw"] == 0

    def test_dynamic_online_cuts_the_losses(self, ctl):
        ids = [f"ups_a_{n:02d}" for n in range(1, 9)]
        remote(ctl, *ids)
        for device_id in ids:
            run(ctl, device_id, "ENTER_DYNAMIC_ONLINE")
        # 8380 kW * (1 / 0.99 - 1) = 84.6 kW (operator doc: about 85 kW)
        assert ctl.path_summary("a")["ups_losses_kw"] == 85
        assert ctl.path_summary("a")["ups_protected"] is True

    def test_generation_n_plus_1_with_total_load(self, ctl):
        """DC-EPMS-066 / -067 (operator decision 2026-11-14): 9 x 2.75 MW.
        With one set out, 8 x 2.75 = 22.0 MW covers the 21.5 MW design
        total (IT + 25 percent overhead). The computed full-path demand
        is 21468 kW, so the operator's 21.5 MW figure governs."""
        s = ctl.path_summary("a")
        assert s["gen_available_kw"] == 24750
        assert s["design_demand_kw"] == pytest.approx(21468, abs=2)
        assert s["design_total_kw"] == 21500
        assert s["generation_floor_kw"] == 21500
        assert s["gen_n_ok"] is True
        assert s["gen_n_plus_1_ok"] is True
        assert s["gen_n_plus_1_it_only_ok"] is True

    def test_superseded_design_would_fail_the_total_load_rule(self, design, clock):
        old = {**design, "generators": {**design["generators"], "rated_kw": 2500}}
        s = dc.DeviceController.from_design(old, clock=clock, wall_clock=clock).path_summary("a")
        assert s["gen_n_ok"] is True
        assert s["gen_n_plus_1_ok"] is False          # 20.0 MW < 21.5 MW
        assert s["gen_n_plus_1_it_only_ok"] is True   # what the old rule saw

    def test_floor_follows_a_load_above_the_design_figure(self, design, clock):
        heavy = {**design, "design_basis": {**design["design_basis"], "cooling_and_aux_fraction": 0.40}}
        s = dc.DeviceController.from_design(heavy, clock=clock, wall_clock=clock).path_summary("a")
        # 16760 * 1.40 + 518 = 23982 kW > 21500 kW
        assert s["generation_floor_kw"] == pytest.approx(23982, abs=2)
        assert s["gen_n_plus_1_ok"] is False

    def test_design_validation(self, design):
        bad = {**design, "ups": {**design["ups"], "rated_kw": 0}}
        with pytest.raises(ValueError, match=r"ups\.rated_kw"):
            dc.validate_design(bad)
        with pytest.raises(ValueError, match="design invalid"):
            dc.validate_design({})

    def test_snapshot_is_labelled_simulated(self, ctl):
        snap = ctl.snapshot_all()
        assert snap["quality"] == "simulated"
        assert "No field equipment is connected" in snap["notice"]
        assert "Arc-flash energy is not calculated" in snap["notice"]
        assert [p["path"] for p in snap["paths"]] == ["a", "b"]
        assert len(snap["devices"]) == 36


class TestAuthority:
    def test_auto_and_local_refuse_remote_commands(self, ctl):
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.select("genset_a_01", "START", "manager")
        assert exc.value.status == 409
        assert "AUTO" in exc.value.detail
        ctl.set_authority("genset_a_01", dc.AUTH_LOCAL, "manager")
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.select("genset_a_01", "START", "manager")
        assert "LOCAL" in exc.value.detail

    def test_local_change_is_recorded_as_bench_simulation(self, ctl):
        assert ctl.set_authority("ups_a_01", dc.AUTH_LOCAL, "m")["source"] == "bench_simulation"
        assert ctl.set_authority("ups_a_01", dc.AUTH_REMOTE, "m")["source"] == "bench_simulation"
        assert ctl.set_authority("ups_a_01", dc.AUTH_AUTO, "m")["source"] == "remote"

    def test_invalid_and_repeated_authority(self, ctl):
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.set_authority("ups_a_01", "GOD", "manager")
        assert exc.value.status == 400
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.set_authority("ups_a_01", dc.AUTH_AUTO, "manager")
        assert exc.value.status == 409

    def test_authority_reason_takes_priority_over_interlocks(self, ctl):
        reasons = {c["blocked_reason"] for c in ctl.snapshot("ups_a_01")["commands"]}
        assert len(reasons) == 1
        assert "AUTO" in next(iter(reasons))

    def test_local_blocks_a_switching_procedure(self, ctl):
        ctl.set_authority("genset_a_01", dc.AUTH_LOCAL, "manager")
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.start_procedure("genset_a_01", mv.GOAL_ISOLATE, "manager")
        assert "LOCAL" in exc.value.detail


class TestSelectBeforeOperate:
    def test_select_changes_nothing(self, ctl):
        remote(ctl, "genset_a_01")
        sel = ctl.select("genset_a_01", "START", "manager")
        assert sel["expires_in_s"] == dc.SELECT_TTL_S
        assert ctl.devices["genset_a_01"].state == dc.GEN_STANDBY

    def test_token_single_use_expiry_actor_and_device(self, ctl, clock):
        remote(ctl, "ups_a_01", "ups_a_02")
        sel = ctl.select("ups_a_01", "TRANSFER_TO_BYPASS", "manager")
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.operate("ups_a_02", sel["select_token"], "manager")
        assert exc.value.status == 409
        sel = ctl.select("ups_a_01", "TRANSFER_TO_BYPASS", "manager")
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.operate("ups_a_01", sel["select_token"], "intruder")
        assert exc.value.status == 403
        sel = ctl.select("ups_a_01", "TRANSFER_TO_BYPASS", "manager")
        clock.tick(dc.SELECT_TTL_S + 1)
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.operate("ups_a_01", sel["select_token"], "manager")
        assert "expired" in exc.value.detail
        sel = ctl.select("ups_a_01", "TRANSFER_TO_BYPASS", "manager")
        ctl.operate("ups_a_01", sel["select_token"], "manager")
        with pytest.raises(dc.DeviceControlError):
            ctl.operate("ups_a_01", sel["select_token"], "manager")
        assert ctl.devices["ups_a_01"].state == dc.UPS_STATIC_BYPASS

    def test_authority_change_drops_a_pending_selection(self, ctl):
        remote(ctl, "genset_a_01")
        sel = ctl.select("genset_a_01", "START", "manager")
        ctl.set_authority("genset_a_01", dc.AUTH_AUTO, "manager")
        ctl.set_authority("genset_a_01", dc.AUTH_REMOTE, "manager")
        with pytest.raises(dc.DeviceControlError):
            ctl.operate("genset_a_01", sel["select_token"], "manager")

    def test_interlocks_are_re_evaluated_at_operate(self, ctl, clock):
        start(ctl, clock, *GENS_A[:4])  # 11.0 MW against 10.73 MW
        remote(ctl, "mvtc_a")
        sel = ctl.select("mvtc_a", "TRANSFER_TO_GENERATORS", "manager")
        run(ctl, "genset_a_01", "STOP")  # bus drops to 8.25 MW after the select
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.operate("mvtc_a", sel["select_token"], "manager")
        assert "synchronised" in exc.value.detail
        assert ctl.devices["mvtc_a"].state == dc.XFER_UTILITY

    def test_unknown_command_and_device(self, ctl):
        remote(ctl, "ups_a_01")
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.select("ups_a_01", "START", "manager")
        assert exc.value.status == 400
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.select("rack_01", "START", "manager")
        assert exc.value.status == 404


class TestUpsBlocks:
    def test_isolation_needs_static_bypass_and_keeps_n(self, ctl):
        remote(ctl, "ups_a_01", "ups_a_02")
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.select("ups_a_01", "ISOLATE", "manager")
        assert "static bypass first" in exc.value.detail
        run(ctl, "ups_a_01", "TRANSFER_TO_BYPASS")
        assert ctl.path_summary("a")["ups_protected"] is False
        run(ctl, "ups_a_01", "ISOLATE")
        s = ctl.path_summary("a")
        assert (s["ups_in_service"], s["ups_capacity_kw"]) == (7, 17500)
        assert s["ups_n_ok"]
        assert not s["ups_n_plus_1_ok"]
        run(ctl, "ups_a_02", "TRANSFER_TO_BYPASS")
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.select("ups_a_02", "ISOLATE", "manager")
        assert "N+1 already used" in exc.value.detail

    def test_load_is_shared_by_the_blocks_in_service(self, ctl):
        remote(ctl, "ups_a_01")
        run(ctl, "ups_a_01", "TRANSFER_TO_BYPASS")
        run(ctl, "ups_a_01", "ISOLATE")
        assert readings(ctl, "ups_a_01")["Output load"] == 0
        assert readings(ctl, "ups_a_02")["Output load"] == pytest.approx(8380 / 7, abs=1)
        run(ctl, "ups_a_01", "RETURN_TO_SERVICE")
        run(ctl, "ups_a_01", "RETURN_TO_DOUBLE_CONVERSION")
        assert ctl.path_summary("a")["ups_n_plus_1_ok"] is True

    def test_overload_is_flagged(self, design, clock):
        small = {**design, "ups": {**design["ups"], "units_per_path": 3}}
        ctl = dc.DeviceController.from_design(small, clock=clock, wall_clock=clock)
        ctl.inject_path_loss("a")
        snap = ctl.snapshot("ups_b_01")
        assert snap["status"]["tone"] == "crit"
        assert "OVERLOAD" in snap["status"]["text"]
        assert ctl.path_summary("b")["ups_n_ok"] is False

    def test_runtime_estimate_follows_the_load(self, ctl):
        # 10 min at full load, block at 1047.5 of 2500 kW
        assert readings(ctl, "ups_a_01")["Battery runtime (estimate)"] == pytest.approx(23.9, abs=0.1)
        remote(ctl, "ups_a_01")
        run(ctl, "ups_a_01", "TRANSFER_TO_BYPASS")
        assert readings(ctl, "ups_a_01")["Battery runtime (estimate)"] == 0


class TestGeneratorsAndTransfer:
    def test_start_sequence_closes_52g_after_synchronising(self, ctl, clock):
        remote(ctl, "genset_a_01")
        run(ctl, "genset_a_01", "START")
        clock.tick(dc.CRANK_TIME_S / 2)
        snap = ctl.snapshot("genset_a_01")
        assert snap["state"] == dc.GEN_CRANKING
        assert ctl.bays["genset_a_01"].cb == mv.OPEN
        clock.tick(dc.CRANK_TIME_S)
        snap = ctl.snapshot("genset_a_01")
        assert snap["state"] == dc.GEN_RUNNING
        assert ctl.bays["genset_a_01"].cb == mv.CLOSED
        assert readings(ctl, "genset_a_01")["Output voltage"] == 13.8

    def test_stop_opens_52g_then_cools_down(self, ctl, clock):
        start(ctl, clock, "genset_a_01")
        run(ctl, "genset_a_01", "STOP")
        assert ctl.bays["genset_a_01"].cb == mv.OPEN
        assert ctl.snapshot("genset_a_01")["state"] == dc.GEN_COOLDOWN
        clock.tick(dc.COOLDOWN_TIME_S + 0.1)
        assert ctl.snapshot("genset_a_01")["state"] == dc.GEN_STANDBY

    def test_transfer_needs_enough_generation_on_the_bus(self, ctl, clock):
        remote(ctl, "mvtc_a")
        start(ctl, clock, *GENS_A[:3])  # 8.25 MW against 10.73 MW
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.select("mvtc_a", "TRANSFER_TO_GENERATORS", "manager")
        assert "MW synchronised, below the 10.7 MW" in exc.value.detail
        start(ctl, clock, GENS_A[3])
        run(ctl, "mvtc_a", "TRANSFER_TO_GENERATORS")
        snap = ctl.snapshot("mvtc_a")
        assert snap["state"] == dc.XFER_GENERATORS
        assert [i["value"] for i in snap["indications"][:3]] == [mv.OPEN, mv.CLOSED, "NORMAL"]
        assert ctl.snapshot("genset_a_01")["state"] == dc.GEN_ON_LOAD
        # 10734 kW over 4 sets
        assert readings(ctl, "genset_a_01")["Real power"] == pytest.approx(2684, abs=1)

    def test_other_path_generation_does_not_count(self, ctl, clock):
        start(ctl, clock, *[g.replace("_a_", "_b_") for g in GENS_A])
        remote(ctl, "mvtc_a")
        with pytest.raises(dc.DeviceControlError):
            ctl.select("mvtc_a", "TRANSFER_TO_GENERATORS", "manager")

    def test_a_set_carrying_load_cannot_leave_the_path_short(self, ctl, clock):
        start(ctl, clock, *GENS_A[:4])
        remote(ctl, "mvtc_a")
        run(ctl, "mvtc_a", "TRANSFER_TO_GENERATORS")
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.select("genset_a_01", "STOP", "manager")
        assert "Remaining sets would supply" in exc.value.detail
        start(ctl, clock, GENS_A[4])
        run(ctl, "genset_a_01", "STOP")
        run(ctl, "mvtc_a", "RETRANSFER_TO_UTILITY")
        assert ctl.snapshot("genset_a_02")["state"] == dc.GEN_RUNNING


class TestMvProcedures:
    def test_isolation_runs_step_by_step_with_a_witness(self, ctl):
        remote(ctl, "genset_a_03")
        isolate(ctl, "genset_a_03")
        bay = ctl.bays["genset_a_03"]
        assert (bay.cb, bay.ds, bay.es, bay.loto) == (mv.OPEN, mv.OPEN, mv.CLOSED, True)
        assert ctl.path_summary("a")["gen_available"] == 8
        snap = ctl.snapshot("genset_a_03")
        assert snap["status"]["text"] == "Isolated, earthed and locked out"
        start_cmd = next(c for c in snap["commands"] if c["command"] == "START")
        assert start_cmd["blocked_reason"] == "Bay is under LOTO."

    def test_only_the_next_step_can_run(self, ctl):
        remote(ctl, "genset_a_03")
        proc = ctl.start_procedure("genset_a_03", mv.GOAL_ISOLATE, "manager")
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.execute_step(proc["procedure_id"], 4, "manager")
        assert "sequence deviation" in exc.value.detail
        assert ctl.bays["genset_a_03"].ds == mv.CLOSED
        described = ctl.snapshot("genset_a_03")["switching"]["procedure"]
        assert described["blocked_attempts"] == 1
        assert [s["status"] for s in described["steps"]] == ["next"] + ["locked"] * 4

    def test_two_person_rule(self, ctl, clock):
        remote(ctl, "genset_a_03")
        proc = ctl.start_procedure("genset_a_03", mv.GOAL_ISOLATE, "manager")
        pid = proc["procedure_id"]
        for step in (1, 2, 3):
            ctl.execute_step(pid, step, "manager")
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.execute_step(pid, 4, "manager")
        assert "two-person rule" in exc.value.detail
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.witness_step(pid, 4, "manager")
        assert exc.value.status == 403
        assert "different person" in exc.value.detail
        with pytest.raises(dc.DeviceControlError):
            ctl.witness_step(pid, 5, "safety_a")
        ctl.witness_step(pid, 4, "safety_a")
        clock.tick(mv.WITNESS_VALID_S + 1)
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.execute_step(pid, 4, "manager")
        assert "two-person rule" in exc.value.detail
        assert ctl.bays["genset_a_03"].es == mv.OPEN

    def test_stale_verification_blocks_the_earthing_switch(self, ctl, clock):
        remote(ctl, "genset_a_03")
        pid = ctl.start_procedure("genset_a_03", mv.GOAL_ISOLATE, "manager")["procedure_id"]
        for step in (1, 2, 3):
            ctl.execute_step(pid, step, "manager")
        clock.tick(mv.ABSENCE_VALID_S + 1)
        ctl.witness_step(pid, 4, "safety_a")
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.execute_step(pid, 4, "manager")
        assert exc.value.detail.startswith("R3")

    def test_another_operator_cannot_take_over(self, ctl):
        remote(ctl, "genset_a_03")
        pid = ctl.start_procedure("genset_a_03", mv.GOAL_ISOLATE, "manager")["procedure_id"]
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.execute_step(pid, 1, "someone_else")
        assert exc.value.status == 403

    def test_running_generator_cannot_be_isolated(self, ctl, clock):
        start(ctl, clock, "genset_a_03")
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.start_procedure("genset_a_03", mv.GOAL_ISOLATE, "manager")
        assert "Stop the generator first" in exc.value.detail

    def test_capacity_rule_uses_total_load(self, ctl):
        """DC-EPMS-067: one bay out leaves 22.0 MW (>= 21.5 MW total);
        a second would leave 19.25 MW. The superseded IT-only rule
        (16.76 MW) would have let three bays go out."""
        remote(ctl, "genset_a_01", "genset_a_02")
        isolate(ctl, "genset_a_01")
        assert ctl.path_summary("a")["gen_available_kw"] == 22000
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.start_procedure("genset_a_02", mv.GOAL_ISOLATE, "manager")
        assert "keeps 19.25 MW" in exc.value.detail
        assert "21.50 MW total load" in exc.value.detail
        goal = next(g for g in ctl.snapshot("genset_a_02")["switching"]["goals"]
                    if g["goal"] == mv.GOAL_ISOLATE)
        assert goal["permitted"] is False

    def test_the_other_path_is_independent(self, ctl):
        remote(ctl, "genset_a_01", "genset_b_01")
        isolate(ctl, "genset_a_01")
        isolate(ctl, "genset_b_01")
        assert ctl.path_summary("b")["gen_n_plus_1_ok"] is False

    def test_one_procedure_per_bay_and_no_start_meanwhile(self, ctl):
        remote(ctl, "genset_a_03")
        ctl.start_procedure("genset_a_03", mv.GOAL_ISOLATE, "manager")
        with pytest.raises(dc.DeviceControlError):
            ctl.start_procedure("genset_a_03", mv.GOAL_ISOLATE, "manager")
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.select("genset_a_03", "START", "manager")
        assert "procedure is in progress" in exc.value.detail

    def test_abort_keeps_positions_and_restore_recovers(self, ctl):
        remote(ctl, "genset_a_03")
        pid = ctl.start_procedure("genset_a_03", mv.GOAL_ISOLATE, "manager")["procedure_id"]
        ctl.execute_step(pid, 1, "manager")
        ctl.execute_step(pid, 2, "manager")
        ctl.abort_procedure(pid, "manager")
        assert ctl.bays["genset_a_03"].ds == mv.OPEN
        proc = ctl.start_procedure("genset_a_03", mv.GOAL_RESTORE, "manager")
        assert [s["operation"] for s in proc["steps"]] == [mv.OP_CLOSE_DS]
        ctl.execute_step(proc["procedure_id"], 1, "manager")
        assert ctl.bays["genset_a_03"].in_service
        assert ctl.snapshot("genset_a_03")["switching"]["procedure"] is None

    def test_isolated_bay_does_not_synchronise(self, ctl, clock):
        """Defence in depth: even if the engine ran, 52-G stays open."""
        ctl.bays["genset_a_03"].ds = mv.OPEN
        ctl.devices["genset_a_03"].state = dc.GEN_CRANKING
        clock.tick(dc.CRANK_TIME_S + 1)
        ctl.snapshot_all()
        assert ctl.bays["genset_a_03"].cb == mv.OPEN
        assert ctl.path_summary("a")["gen_on_bus_kw"] == 0

    def test_transfer_controller_has_no_bay(self, ctl):
        remote(ctl, "mvtc_a")
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.start_procedure("mvtc_a", mv.GOAL_ISOLATE, "manager")
        assert exc.value.status == 404


# ── Routes ──────────────────────────────────────────────────────────
@pytest.fixture
def app_client(monkeypatch, design):
    monkeypatch.delenv("DC_EPMS_REQUIRE_AUTH", raising=False)
    app = FastAPI()
    controller = dc.DeviceController.from_design(design)
    app.state.forensic_ledger = ForensicLedger(InMemoryPersistence(), key=b"k" * 32)
    dc.register_device_control_routes(app, lambda: controller)
    with TestClient(app) as client:
        yield client, app, controller


def _bearer(username: str) -> dict[str, str]:
    user = seed_demo_users().find_by_username(username)
    return {"Authorization": f"Bearer {issue_token(user)}"}


LEGACY = {"actor_role": "SME_L6", "user": "bench"}


class TestRoutes:
    def test_list_is_read_only(self, app_client):
        client, _app, _ctl = app_client
        body = client.get("/api/devices").json()
        assert len(body["devices"]) == 36
        assert len(body["paths"]) == 2
        assert client.get("/api/devices/ups_a_01").json()["id"] == "ups_a_01"
        assert client.get("/api/devices/rack_01").status_code == 404

    def test_legacy_role_rule_without_token(self, app_client):
        client, _app, _ctl = app_client
        url = "/api/devices/ups_a_01/authority"
        assert client.post(url, json={"authority": "REMOTE", "actor_role": "TECH_L4"}).status_code == 403
        assert client.post(url, json={"authority": "REMOTE", **LEGACY}).status_code == 200

    def test_token_role_wins_over_body_role(self, app_client):
        client, _app, ctl = app_client
        resp = client.post("/api/devices/ups_a_01/authority",
                           json={"authority": "REMOTE", **LEGACY}, headers=_bearer("technician"))
        assert resp.status_code == 403
        assert "FACILITY_MANAGER" in resp.json()["detail"]
        assert ctl.devices["ups_a_01"].authority == dc.AUTH_AUTO

    def test_bad_token_and_gated_deployment(self, app_client, monkeypatch):
        client, _app, _ctl = app_client
        url = "/api/devices/ups_a_01/authority"
        resp = client.post(url, json={"authority": "REMOTE", **LEGACY},
                           headers={"Authorization": "Bearer not-a-token"})
        assert resp.status_code == 401
        monkeypatch.setenv("DC_EPMS_REQUIRE_AUTH", "1")
        assert client.post(url, json={"authority": "REMOTE", **LEGACY}).status_code == 401

    def test_select_then_operate_over_http(self, app_client):
        client, _app, _ctl = app_client
        h = _bearer("manager")
        client.post("/api/devices/ups_a_01/authority", json={"authority": "REMOTE"}, headers=h)
        sel = client.post("/api/devices/ups_a_01/select",
                          json={"command": "ENTER_DYNAMIC_ONLINE"}, headers=h).json()
        done = client.post("/api/devices/ups_a_01/operate",
                           json={"select_token": sel["select_token"]}, headers=h)
        assert done.status_code == 200
        assert done.json()["ledger_entry_id"]
        assert client.get("/api/devices/ups_a_01").json()["state"] == dc.UPS_DYNAMIC_ONLINE

    def test_refusals_are_409_and_logged(self, app_client):
        client, _app, _ctl = app_client
        resp = client.post("/api/devices/mvtc_a/select",
                           json={"command": "TRANSFER_TO_GENERATORS", **LEGACY})
        assert resp.status_code == 409
        assert client.get("/api/devices").json()["events"][0]["event"] == "refused"

    def test_mv_procedure_over_http_with_two_people(self, app_client):
        client, app, ctl = app_client
        mgr, safety = _bearer("manager"), _bearer("safety_a")
        client.post("/api/devices/genset_a_03/authority", json={"authority": "REMOTE"}, headers=mgr)
        started = client.post("/api/mv/bays/genset_a_03/procedure",
                              json={"goal": "ISOLATE_FOR_MAINTENANCE"}, headers=mgr)
        assert started.status_code == 200
        pid = started.json()["procedure"]["procedure_id"]
        step = f"/api/mv/procedures/{pid}/step"
        witness = f"/api/mv/procedures/{pid}/witness"
        assert client.post(step, json={"step": 3}, headers=mgr).status_code == 409
        for n in (1, 2, 3):
            assert client.post(step, json={"step": n}, headers=mgr).status_code == 200
        assert client.post(step, json={"step": 4}, headers=mgr).status_code == 409
        # the operator cannot witness their own step; a technician lacks the role
        assert client.post(witness, json={"step": 4}, headers=mgr).status_code == 403
        assert client.post(witness, json={"step": 4}, headers=_bearer("technician")).status_code == 403
        assert client.post(witness, json={"step": 4}, headers=safety).status_code == 200
        assert client.post(step, json={"step": 4}, headers=mgr).status_code == 200
        assert client.post(witness, json={"step": 5}, headers=safety).status_code == 200
        done = client.post(step, json={"step": 5}, headers=mgr).json()
        assert done["procedure"]["complete"] is True
        assert ctl.bays["genset_a_03"].loto is True

        entries = asyncio.run(app.state.forensic_ledger.persistence.fetch_all())
        actions = [e.action for e in entries]
        assert actions.count(dc.ACTION_MV_STEP) == 7  # 5 done + 2 blocked
        assert actions.count(dc.ACTION_MV_WITNESS) == 2
        blocked = [e for e in entries if e.action == dc.ACTION_MV_STEP and not e.payload["success"]]
        assert len(blocked) == 2
        witnessed = [e for e in entries if e.action == dc.ACTION_MV_STEP and e.payload.get("witness")]
        assert {e.payload["witness"] for e in witnessed} == {"safety_a"}
        asyncio.run(app.state.forensic_ledger.verify_chain())

    def test_witness_with_credentials_at_the_same_console(self, app_client):
        client, app, ctl = app_client
        app.state.user_store = seed_demo_users()
        mgr = _bearer("manager")
        client.post("/api/devices/genset_a_03/authority", json={"authority": "REMOTE"}, headers=mgr)
        pid = client.post("/api/mv/bays/genset_a_03/procedure", json={"goal": "ISOLATE_FOR_MAINTENANCE"},
                          headers=mgr).json()["procedure"]["procedure_id"]
        for n in (1, 2, 3):
            client.post(f"/api/mv/procedures/{pid}/step", json={"step": n}, headers=mgr)
        url = f"/api/mv/procedures/{pid}/witness"

        def cred(user, pwd):
            return client.post(url, headers=mgr, json={
                "step": 4, "witness_username": user, "witness_password": pwd})

        assert cred("safety_a", "wrong").status_code == 401
        assert cred("technician", "technician-demo").status_code == 403
        assert cred("manager", "manager-demo").status_code == 403  # the operator
        ok = cred("safety_a", "safety-demo")
        assert ok.status_code == 200
        assert "safety-demo" not in ok.text
        assert client.post(f"/api/mv/procedures/{pid}/step", json={"step": 4}, headers=mgr).status_code == 200
        assert ctl.bays["genset_a_03"].es == mv.CLOSED
        entries = asyncio.run(app.state.forensic_ledger.persistence.fetch_all())
        assert all("password" not in str(e.payload).lower() for e in entries)

    def test_abort_over_http(self, app_client):
        client, _app, _ctl = app_client
        h = _bearer("manager")
        client.post("/api/devices/genset_a_03/authority", json={"authority": "REMOTE"}, headers=h)
        pid = client.post("/api/mv/bays/genset_a_03/procedure",
                          json={"goal": "ISOLATE_FOR_MAINTENANCE"}, headers=h).json()["procedure"]["procedure_id"]
        assert client.post(f"/api/mv/procedures/{pid}/abort", json={}, headers=h).status_code == 200
        assert client.post(f"/api/mv/procedures/{pid}/step", json={"step": 1}, headers=h).status_code == 404

    def test_every_device_action_is_chained(self, app_client):
        client, app, _ctl = app_client
        h = _bearer("manager")
        client.post("/api/devices/ups_a_01/authority", json={"authority": "REMOTE"}, headers=h)
        sel = client.post("/api/devices/ups_a_01/select",
                          json={"command": "TRANSFER_TO_BYPASS"}, headers=h).json()
        client.post("/api/devices/ups_a_01/operate", json={"select_token": sel["select_token"]}, headers=h)
        client.post("/api/devices/ups_a_01/operate", json={"select_token": "stale"}, headers=h)
        entries = asyncio.run(app.state.forensic_ledger.persistence.fetch_all())
        assert [e.action for e in entries] == [
            dc.ACTION_DEVICE_AUTHORITY,
            dc.ACTION_DEVICE_COMMAND_REQUESTED, dc.ACTION_DEVICE_COMMAND_RESULT,
            dc.ACTION_DEVICE_COMMAND_REQUESTED, dc.ACTION_DEVICE_COMMAND_RESULT,
        ]
        assert entries[1].payload["command"] == "TRANSFER_TO_BYPASS"
        assert entries[2].payload["success"] is True
        assert entries[4].payload["success"] is False
        assert all(e.actor == "manager" for e in entries)

    def test_no_select_token_in_the_public_payload(self, app_client):
        client, _app, _ctl = app_client
        client.post("/api/devices/ups_a_01/authority", json={"authority": "REMOTE", **LEGACY})
        client.post("/api/devices/ups_a_01/select", json={"command": "TRANSFER_TO_BYPASS", **LEGACY})
        assert "select_token" not in client.get("/api/devices").text


class TestWiring:
    def test_routes_are_mounted_on_the_real_app(self):
        import main

        paths = {getattr(r, "path", "") for r in main.app.routes}
        for expected in ("/api/devices", "/api/devices/{device_id}/operate",
                         "/api/mv/bays/{bay_id}/procedure",
                         "/api/mv/procedures/{procedure_id}/witness",
                         "/api/power-scenarios", "/api/power-scenarios/{scenario_id}/run"):
            assert expected in paths

    def test_no_raw_bay_operation_route(self):
        """Live MV switching exists only as procedures."""
        import main

        paths = {getattr(r, "path", "") for r in main.app.routes}
        assert not any("attempt" in p for p in paths)


class TestAgentIsolation:
    """ADR-006: AI has zero write authority. No agent, copilot,
    optimizer or MCP module may reference the control modules."""

    def test_agent_stack_never_references_the_control_modules(self):
        backend = PROJECT_ROOT / "backend"
        suspects = [
            *backend.glob("agent*.py"), *backend.glob("agents/*.py"),
            *backend.glob("optimizer*.py"), backend / "mcp_server.py",
            backend / "multi_agent.py", backend / "shift_copilot.py",
        ]
        assert len(suspects) > 5
        offenders = []
        for path in suspects:
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            if any(name in text for name in ("device_control", "mv_switching", "power_scenarios",
                                             "alarm_routes", "training_routes", "mv_cubicle")):
                offenders.append(path.name)
        assert offenders == []


class TestVocabularyFence:
    def test_dc_side_is_out_of_scope(self, ctl):
        assert not any("dc_bus" in i or "sscb" in i for i in ctl.devices)
        from backend import mv_cubicle
        for module in (dc, mv, mv_cubicle):
            text = pathlib.Path(module.__file__).read_text(encoding="utf-8").lower()
            assert "800 vdc trif" not in text
            assert "three-phase dc" not in text
        plant = DESIGN_PATH.read_text(encoding="utf-8").lower()
        assert "unipolar tn-s" in plant
        assert "vdc trif" not in plant
