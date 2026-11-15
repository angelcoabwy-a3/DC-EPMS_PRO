"""T1 (2026-11-15) -- plant conditions for training on the simulated
Power Controls plant: utility loss with ANSI 27 trip, dead MV bus,
battery state of charge, load loss, AUTO transfer sequence, master
start, UPS inverter fault, reset."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from backend import (  # noqa: E402
    alarm_engine as ae,
    device_control as dc,
)

DESIGN_PATH = PROJECT_ROOT / "config" / "power_plant.yml"


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def tick(self, s: float) -> None:
        self.t += s


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def ctl(clock):
    return dc.DeviceController.from_design(dc.load_design(DESIGN_PATH), clock=clock, wall_clock=clock)


def remote(ctl, device_id):
    if ctl.devices[device_id].authority != dc.AUTH_REMOTE:
        ctl.set_authority(device_id, dc.AUTH_REMOTE, "op")


def run(ctl, device_id, command):
    remote(ctl, device_id)
    sel = ctl.select(device_id, command, "op")
    return ctl.operate(device_id, sel["select_token"], "op")


def summary(ctl, path="a"):
    """Path summary as the API serves it (time advanced first)."""
    return next(p for p in ctl.snapshot_all()["paths"] if p["path"] == path)


def manual_path(ctl, path="a"):
    """Training posture: transfer controller and sets out of AUTO."""
    remote(ctl, f"mvtc_{path}")
    for d in ctl._of(dc.KIND_GENERATOR, path):
        remote(ctl, d.device_id)


class TestUtilityLoss:
    def test_ansi27_trips_52u_and_kills_the_bus(self, ctl):
        manual_path(ctl)
        ctl.inject_utility_loss("a", "instructor")
        snap = ctl.snapshot("mvtc_a")
        assert snap["state"] == dc.XFER_OPEN
        assert [i["value"] for i in snap["indications"][:3]] == ["OPEN", "OPEN", "PICKED UP"]
        assert snap["status"]["tone"] == "crit"
        s = summary(ctl)
        assert (s["source"], s["bus_energized"], s["utility_ok"]) == ("NONE", False, False)
        assert summary(ctl, "b")["bus_energized"] is True
        assert "protection_trip" in [e["event"] for e in ctl._events]

    def test_double_injection_refused(self, ctl):
        ctl.inject_utility_loss("a", "i")
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.inject_utility_loss("a", "i")
        assert exc.value.status == 409

    def test_retransfer_refused_without_utility(self, ctl):
        manual_path(ctl)
        ctl.inject_utility_loss("a", "i")
        with pytest.raises(dc.DeviceControlError, match="ANSI 27"):
            ctl.select("mvtc_a", "RETRANSFER_TO_UTILITY", "op")


class TestBattery:
    def test_discharge_is_linear_in_energy_and_reaches_load_loss(self, ctl, clock):
        manual_path(ctl)
        ctl.inject_utility_loss("a", "i")
        # 8 x 2500 kW x 10 min = 3333 kWh at 8380 kW IT load -> ~23.9 min
        runtime = summary(ctl)["battery_runtime_min"]
        assert runtime == pytest.approx(8 * 2500 * 10 / 8380, rel=1e-3)
        clock.tick(600)
        s = summary(ctl)
        assert s["battery_soc_pct"] == pytest.approx(100 * (1 - 600 / (runtime * 60)), abs=0.2)
        assert s["load_lost"] is False
        for _ in range(20):
            clock.tick(60)
            s = summary(ctl)
        assert s["load_lost"] is True
        assert s["battery_soc_pct"] == 0.0
        assert ctl.snapshot("ups_a_01")["status"]["text"].startswith("Output lost")

    def test_bypass_with_dead_bus_drops_the_load_at_once(self, ctl):
        run(ctl, "ups_a_01", "TRANSFER_TO_BYPASS")
        manual_path(ctl)
        ctl.inject_utility_loss("a", "i")
        assert summary(ctl)["load_lost"] is True

    def test_recharge_after_recovery(self, ctl, clock):
        manual_path(ctl)
        ctl.inject_utility_loss("a", "i")
        clock.tick(300)
        low = summary(ctl)["battery_soc_pct"]
        ctl.restore_utility("a", "i")
        run(ctl, "mvtc_a", "RETRANSFER_TO_UTILITY")
        clock.tick(60)
        assert summary(ctl)["battery_soc_pct"] == pytest.approx(min(100, low + 10), abs=0.2)


class TestManualRecovery:
    def test_master_start_then_close_52gm(self, ctl, clock):
        manual_path(ctl)
        ctl.inject_utility_loss("a", "i")
        with pytest.raises(dc.DeviceControlError, match="synchronised"):
            ctl.select("mvtc_a", "TRANSFER_TO_GENERATORS", "op")
        out = run(ctl, "mvtc_a", "START_GENERATORS")
        assert len(out["started"]) == 9
        clock.tick(dc.CRANK_TIME_S + 0.1)
        run(ctl, "mvtc_a", "TRANSFER_TO_GENERATORS")
        s = summary(ctl)
        assert (s["source"], s["bus_energized"]) == ("GENERATORS", True)
        assert ctl.snapshot("genset_a_01")["state"] == dc.GEN_ON_LOAD

    def test_master_start_skips_local_sets(self, ctl):
        manual_path(ctl)
        ctl.set_authority("genset_a_01", dc.AUTH_LOCAL, "op")
        out = run(ctl, "mvtc_a", "START_GENERATORS")
        assert "genset_a_01" not in out["started"]


class TestAutoSequence:
    def test_auto_controller_starts_auto_sets_and_closes_52gm(self, ctl, clock):
        ctl.inject_utility_loss("a", "i")
        assert ctl.snapshot("genset_a_01")["state"] == dc.GEN_CRANKING
        clock.tick(dc.CRANK_TIME_S + 0.1)
        assert summary(ctl)["source"] == "GENERATORS"
        assert summary(ctl)["load_lost"] is False

    def test_auto_recloses_52u_when_utility_returns_first(self, ctl, clock):
        ctl.inject_utility_loss("a", "i")
        ctl.restore_utility("a", "i")
        assert ctl.snapshot("mvtc_a")["state"] == dc.XFER_UTILITY

    def test_auto_does_not_retransfer_from_generators(self, ctl, clock):
        ctl.inject_utility_loss("a", "i")
        clock.tick(dc.CRANK_TIME_S + 0.1)
        ctl.restore_utility("a", "i")
        clock.tick(5)
        assert ctl.snapshot("mvtc_a")["state"] == dc.XFER_GENERATORS


class TestUpsFault:
    def test_fault_blocks_inverter_commands_until_isolated(self, ctl):
        ctl.inject_ups_fault("ups_a_03", dc.UPS_FAULT_INVERTER_OVERTEMP, "i")
        snap = ctl.snapshot("ups_a_03")
        assert snap["fault"] == dc.UPS_FAULT_INVERTER_OVERTEMP
        assert snap["status"]["tone"] == "crit"
        run(ctl, "ups_a_03", "TRANSFER_TO_BYPASS")
        with pytest.raises(dc.DeviceControlError, match="over-temperature"):
            ctl.select("ups_a_03", "RETURN_TO_DOUBLE_CONVERSION", "op")
        run(ctl, "ups_a_03", "ISOLATE")
        assert ctl.snapshot("ups_a_03")["fault"] is None

    def test_fault_only_on_ups_on_inverter(self, ctl):
        with pytest.raises(dc.DeviceControlError):
            ctl.inject_ups_fault("mvtc_a", dc.UPS_FAULT_INVERTER_OVERTEMP, "i")
        with pytest.raises(dc.DeviceControlError):
            ctl.inject_ups_fault("ups_a_01", "BOGUS", "i")


class TestReset:
    def test_reset_returns_to_design_lineup(self, ctl, clock):
        manual_path(ctl)
        ctl.inject_utility_loss("a", "i")
        ctl.inject_ups_fault("ups_b_01", dc.UPS_FAULT_INVERTER_OVERTEMP, "i")
        clock.tick(120)
        ctl.reset("instructor")
        s = summary(ctl)
        assert (s["source"], s["battery_soc_pct"], s["utility_ok"]) == ("UTILITY", 100.0, True)
        assert ctl.faults == {}
        assert ctl.devices["mvtc_a"].authority == dc.AUTH_AUTO


class TestAlarmsFromPlant:
    def test_blackout_alarm_set(self, ctl, clock):
        manual_path(ctl)
        ctl.inject_utility_loss("a", "i")
        active = {c.alarm_id for c in ae.conditions_from_plant(ctl.snapshot_all()) if c.active}
        assert active == {"PATH_A_UTILITY_LOST", "PATH_A_MV_BUS_DEAD", "PATH_A_ON_BATTERY"}
        clock.tick(60 * 20)
        active = {c.alarm_id for c in ae.conditions_from_plant(ctl.snapshot_all()) if c.active}
        assert "PATH_A_BATTERY_LOW" in active
        clock.tick(60 * 10)
        active = {c.alarm_id for c in ae.conditions_from_plant(ctl.snapshot_all()) if c.active}
        assert "PATH_A_LOAD_LOST" in active
        assert "PATH_A_ON_BATTERY" not in active

    def test_inverter_fault_alarm(self, ctl):
        ctl.inject_ups_fault("ups_a_03", dc.UPS_FAULT_INVERTER_OVERTEMP, "i")
        active = {c.alarm_id for c in ae.conditions_from_plant(ctl.snapshot_all()) if c.active}
        assert active == {"DEV_ups_a_03_INVERTER_FAULT"}
