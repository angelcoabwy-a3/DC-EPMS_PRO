"""Lot 12 (ADR-023): Building D simulated plant (backend/bldg_d.py), its
Power Controls integration, alarms, telemetry overlay and DRILL-11..13."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import (  # noqa: E402
    alarm_engine as ae,
    bldg_d as bd,
    design_model as dm,
    device_control as dc,
    training as tr,
)
from backend.auth.jwt_handler import issue_token, seed_demo_users  # noqa: E402

DESIGN = PROJECT_ROOT / "config" / "power_plant.yml"
DRILLS = PROJECT_ROOT / "config" / "training_drills"


class Clock:
    def __init__(self) -> None:
        self.t = 1_763_300_000.0

    def __call__(self) -> float:
        return self.t

    def tick(self, s: float) -> None:
        self.t += s


def params() -> bd.Params:
    return bd.params_from_sizing(dm.get_design()["sizing"])


def plant(now: float = 0.0) -> bd.BuildingD:
    return bd.BuildingD.create(params(), now)


def paths(pl: bd.BuildingD, now: float) -> dict[str, dict]:
    return {p["path"]: p for p in pl.summary(now)["paths"]}


# ── Pure plant model ────────────────────────────────────────────────
class TestParams:
    def test_numbers_come_from_the_adr021_design(self):
        p = params()
        assert p.it_kw == 50000.0
        assert (p.rect_units, p.rect_min_units, p.rect_unit_kw) == (14, 12, 5000.0)
        assert p.bess_kwh == 15000.0
        assert p.bess_conv_kw == 27500.0  # 11 converters x 2.5 MW per path
        assert (p.farm_sets, p.farm_set_kw) == (26, 3200.0)
        assert p.utility_kv == 35.0
        assert p.nominal_v == 800.0


class TestNormal:
    def test_two_paths_share_the_hall(self):
        pl = plant()
        pl.advance(5.0)
        s = paths(pl, 5.0)
        for k in ("a", "b"):
            assert s[k]["carrying_kw"] == 25000
            assert s[k]["bus_v"] == 800.0
            assert s[k]["sscb"] == bd.CLOSED
        assert pl.summary(5.0)["load_lost"] is False


class TestUtilityLoss:
    def test_auto_start_and_transfer_without_losing_the_hall(self):
        pl = plant()
        pl.utility_loss("a")
        pl.advance(1.0)
        s = paths(pl, 1.0)
        # path B picks the share up at once (rectifier-fed bus first)
        assert s["b"]["carrying_kw"] == 50000
        assert s["a"]["farm"] == bd.FARM_CRANKING
        pl.advance(1.0 + pl.params.farm_start_s + 0.5)
        assert paths(pl, 12.0)["a"]["source"] == bd.SRC_FARM
        # farm load acceptance: path A ramps back at the model rate
        pl.advance(14.0)
        a = paths(pl, 14.0)["a"]
        assert 0 < a["carrying_kw"] < 25000
        pl.advance(40.0)
        s = paths(pl, 40.0)
        assert s["a"]["carrying_kw"] == 25000
        assert s["a"]["farm"] == bd.FARM_ON_LOAD
        assert pl.load_lost is False
        events = [e["event"] for e in pl.drain_events()]
        assert events[:4] == [
            "utility_lost",
            "farm_auto_start",
            "farm_on_bus",
            "auto_transfer_to_farm",
        ]

    def test_farm_manual_stays_in_standby(self):
        pl = plant()
        pl.set_farm_auto("a", False)
        pl.utility_loss("a")
        pl.advance(60.0)
        assert paths(pl, 60.0)["a"]["farm"] == bd.FARM_STANDBY
        assert paths(pl, 60.0)["b"]["carrying_kw"] == 50000

    def test_retransfer_needs_the_utility(self):
        pl = plant()
        pl.utility_loss("a")
        pl.advance(20.0)
        assert "No utility" in pl.blocked(bd.KIND_RECT, "a", "RETRANSFER_TO_UTILITY")
        pl.utility_restore("a")
        assert pl.blocked(bd.KIND_RECT, "a", "RETRANSFER_TO_UTILITY") is None
        pl.operate(bd.KIND_RECT, "a", "RETRANSFER_TO_UTILITY", 20.0)
        assert pl.blocked(bd.KIND_FARM, "a", "STOP") is None
        pl.operate(bd.KIND_FARM, "a", "STOP", 20.0)
        pl.advance(20.0 + pl.params.farm_cooldown_s + 1)
        assert paths(pl, 60.0)["a"]["farm"] == bd.FARM_STANDBY


class TestBusFault:
    def test_fault_clears_path_a_and_hall_rides_on_b(self):
        pl = plant()
        pl.bus_fault("a")
        pl.advance(2.0)
        s = paths(pl, 2.0)
        assert s["a"]["sscb"] == bd.TRIPPED
        assert s["a"]["bess_breaker"] == bd.TRIPPED
        assert s["a"]["bus_energized"] is False
        assert s["b"]["carrying_kw"] == 50000
        assert pl.load_lost is False

    def test_restore_sequence_and_its_interlocks(self):
        pl = plant()
        pl.bus_fault("a")
        pl.advance(2.0)
        assert "fault" in pl.blocked(bd.KIND_SSCB, "a", "RESET").lower()
        assert "input" in pl.blocked(bd.KIND_SSCB, "a", "CLEAR_FAULT").lower()
        pl.operate(bd.KIND_RECT, "a", "OPEN_INPUT", 2.0)
        assert pl.blocked(bd.KIND_SSCB, "a", "CLEAR_FAULT") is None
        pl.operate(bd.KIND_SSCB, "a", "CLEAR_FAULT", 2.0)
        for kind, cmd in (
            (bd.KIND_SSCB, "RESET"),
            (bd.KIND_RECT, "CLOSE_INPUT"),
            (bd.KIND_SSCB, "CLOSE"),
            (bd.KIND_BESS, "RESET"),
            (bd.KIND_BESS, "CLOSE_BREAKER"),
        ):
            assert pl.blocked(kind, "a", cmd) is None, (kind, cmd)
            pl.operate(kind, "a", cmd, 2.0)
        pl.advance(5.0)
        s = paths(pl, 5.0)
        assert s["a"]["carrying_kw"] == 25000
        assert s["b"]["carrying_kw"] == 25000


class TestInterlocks:
    def test_cannot_open_the_last_bus_without_its_bess(self):
        pl = plant()
        pl.bus_fault("a")
        pl.set_bess_breaker("b", bd.OPEN)
        pl.advance(1.0)
        assert "drop the hall" in pl.blocked(bd.KIND_SSCB, "b", "OPEN")
        assert "drop the hall" in pl.blocked(bd.KIND_RECT, "b", "OPEN_INPUT")

    def test_open_sscb_with_bess_leaves_the_bus_on_bess_idle(self):
        pl = plant()
        pl.operate(bd.KIND_SSCB, "a", "OPEN", 0.0)
        s = paths(pl, 0.0)
        assert s["a"]["bus_energized"] is True  # BESS holds the bus
        assert s["a"]["carrying_kw"] == 0  # racks draw from B first
        assert s["b"]["carrying_kw"] == 50000

    def test_rectifier_units_floor(self):
        pl = plant()
        pl.operate(bd.KIND_RECT, "a", "UNIT_OUT", 0.0)
        pl.operate(bd.KIND_RECT, "a", "UNIT_OUT", 0.0)
        assert "below the 12" in pl.blocked(bd.KIND_RECT, "a", "UNIT_OUT")
        assert paths(pl, 0.0)["a"]["rect_n1_ok"] is False

    def test_unknown_command(self):
        assert "Unknown command" in plant().blocked(bd.KIND_SSCB, "a", "EXPLODE")


class TestLoadStep:
    def _single_path_on_farm(self, bess_open: bool) -> bd.BuildingD:
        pl = plant()
        pl.preset("a", 0.0, out_of_service=True)
        pl.preset("b", 0.0, on_farm=True)
        if bess_open:
            pl.set_bess_breaker("b", bd.OPEN)
        pl.advance(10.0)
        assert paths(pl, 10.0)["b"]["carrying_kw"] == 50000
        pl.schedule_load_step(10.0, 5.0, 12000.0, 20.0)
        return pl

    def test_without_bess_the_farm_cannot_follow_and_the_hall_is_lost(self):
        pl = self._single_path_on_farm(bess_open=True)
        pl.advance(16.0)
        assert pl.load_lost is True
        assert "hall_load_lost" in [e["event"] for e in pl.drain_events()]

    def test_with_bess_the_step_is_carried(self):
        pl = self._single_path_on_farm(bess_open=False)
        pl.advance(15.0)
        b = paths(pl, 15.0)["b"]
        assert b["carrying_kw"] == 62000
        assert b["bess_kw"] > 0  # BESS covers what the farm cannot yet
        pl.advance(17.0)
        assert paths(pl, 17.0)["b"]["soc_pct"] < 100.0
        pl.advance(60.0)
        assert pl.load_lost is False


class TestOverlayAndVocabulary:
    def test_overlay_follows_the_plant(self):
        pl = plant()
        pl.bus_fault("a")
        pl.advance(1.0)
        ov = pl.telemetry_overlay()
        assert ov["main_bus_dc_d:voltage_v_dc_bus"] == 0.0
        assert ov["main_bus_dc_d_b:voltage_v_dc_bus"] == 800.0
        assert ov["mv_rectifier_d_b:rect_load_mw"] == pytest.approx(50.0)
        assert ov["utility_feed_d:utility_voltage_kv"] == 35.0
        assert ov["bess_d_01:bess_soc_pct"] == 100.0
        # S-VOCAB-01: DC metric names never carry a phase suffix
        assert not [k for k in ov if "phase" in k]

    def test_dc_side_labels_have_no_phases(self):
        pl = plant()
        for kind in (bd.KIND_SSCB, bd.KIND_BESS):
            for r in pl.readings(kind, "a"):
                assert "phase" not in r["label"].lower(), r
        ac = [r["label"] for r in pl.readings(bd.KIND_RECT, "a")]
        assert "Input voltage (3-phase AC)" in ac


class TestSimulatorOverlay:
    def test_pinned_channels_follow_the_overlay_and_clear(self):
        from backend import site_model as sm, telemetry_simulator as ts

        sim = ts.TelemetrySimulator(sm.get_site_model(PROJECT_ROOT), seed=7)
        ts.set_state_overlay(
            lambda: {
                "main_bus_dc_d:voltage_v_dc_bus": 0.0,
                "main_bus_dc_d_b:voltage_v_dc_bus": 790.0,
            }
        )
        try:
            w = sim.get_window(n_samples=5)
            assert (w["main_bus_dc_d:voltage_v_dc_bus"] == 0.0).all()
            assert abs(float(w["main_bus_dc_d_b:voltage_v_dc_bus"].mean()) - 790.0) < 1e-6
        finally:
            ts.set_state_overlay(None)
        w = sim.get_window(n_samples=5)
        assert float(w["main_bus_dc_d:voltage_v_dc_bus"].mean()) > 700.0

    def test_a_failing_overlay_never_stops_telemetry(self):
        from backend import site_model as sm, telemetry_simulator as ts

        def boom():
            raise RuntimeError("plant offline")

        sim = ts.TelemetrySimulator(sm.get_site_model(PROJECT_ROOT), seed=7)
        ts.set_state_overlay(boom)
        try:
            assert sim.get_window(n_samples=2)
        finally:
            ts.set_state_overlay(None)


# ── Power Controls integration ──────────────────────────────────────
@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def ctl(clock):
    return dc.DeviceController.from_design(
        dc.load_design(DESIGN), clock=clock, wall_clock=clock, building_d=params()
    )


def run(ctl, device_id, command, actor="trainee"):
    sel = ctl.select(device_id, command, actor)
    return ctl.operate(device_id, sel["select_token"], actor)


class TestController:
    def test_eight_building_d_devices_on_top_of_phase_1(self, ctl):
        snap = ctl.snapshot_all()
        assert len(snap["devices"]) == 44
        d = [x for x in snap["devices"] if x["kind"] in bd.KINDS]
        assert sorted(x["id"] for x in d) == [
            "bess_d",
            "bess_d_b",
            "farm_d",
            "farm_d_b",
            "mv_rect_d",
            "mv_rect_d_b",
            "sscb_d",
            "sscb_d_b",
        ]
        assert {x["path"] for x in d} == {"da", "db"}
        assert snap["building_d"]["paths_carrying"] == 2

    def test_without_building_d_nothing_changes(self, clock):
        plain = dc.DeviceController.from_design(
            dc.load_design(DESIGN), clock=clock, wall_clock=clock
        )
        snap = plain.snapshot_all()
        assert len(snap["devices"]) == 36
        assert snap["building_d"] is None

    def test_select_before_operate_and_authority(self, ctl):
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.select("sscb_d", "OPEN", "op")
        assert "AUTO" in exc.value.detail
        ctl.set_authority("sscb_d", dc.AUTH_REMOTE, "op")
        ev = run(ctl, "sscb_d", "OPEN", "op")
        assert (ev["from_state"], ev["to_state"]) == ("CLOSED", "OPEN")
        assert ctl.snapshot_all()["building_d"]["paths"][1]["carrying_kw"] == 50000

    def test_injection_events_alarms_and_reset(self, ctl, clock):
        ctl.inject_bldg_d("bus_fault", "bench", path="a")
        clock.tick(1)
        snap = ctl.snapshot_all()
        conds = {c.alarm_id: c for c in ae.conditions_from_plant(snap)}
        assert conds["BLDG_DA_BUS_FAULT"].active
        assert conds["BLDG_DA_SSCB_TRIPPED"].active
        assert conds["BLDG_DA_BUS_DEAD"].active
        assert not conds["BLDG_D_HALL_LOAD_LOST"].active
        assert any(e["event"] == "protection_trip" for e in snap["events"])
        ctl.reset("bench")
        assert ctl.snapshot_all()["building_d"]["paths"][0]["sscb"] == "CLOSED"

    def test_bad_injection(self, ctl):
        with pytest.raises(dc.DeviceControlError):
            ctl.inject_bldg_d("meteor", "bench", path="a")
        with pytest.raises(dc.DeviceControlError):
            ctl.inject_bldg_d("bus_fault", "bench", path="z")

    def test_overlay_through_the_controller(self, ctl):
        assert ctl.bldg_d_overlay()["main_bus_dc_d:voltage_v_dc_bus"] == 800.0


class TestInjectRoute:
    def test_needs_a_session_and_injects(self, ctl):
        app = FastAPI()
        dc.register_device_control_routes(app, lambda: ctl)
        client = TestClient(app)
        r = client.post("/api/bldg-d/inject", json={"injection": "bus_fault", "path": "a"})
        assert r.status_code in (401, 403)
        token = issue_token(seed_demo_users().find_by_username("manager"))
        r = client.post(
            "/api/bldg-d/inject",
            json={"injection": "bus_fault", "path": "a"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["event"]["injection"] == "bus_fault"


# ── Drills ──────────────────────────────────────────────────────────
@pytest.fixture
def world(ctl, clock):
    return ctl, ae.AlarmEngine(clock=clock), tr.TrainingManager(tr.load_drills(DRILLS), clock=clock)


def done(view):
    return [s["id"] for s in view["session"]["steps"] if s["done"]]


class TestDrills:
    def test_drill11_farm_manual(self, world, clock):
        ctl, engine, mgr = world
        view = mgr.start("DRILL-11", "trainee", ctl, engine)
        assert view["active"]
        clock.tick(2)
        mgr.evaluate(ctl, engine)
        engine.ack_all("trainee")
        run(ctl, "farm_d", "START")
        assert done(mgr.evaluate(ctl, engine)) == ["ACK", "START"]
        clock.tick(11)
        mgr.evaluate(ctl, engine)
        run(ctl, "mv_rect_d", "TRANSFER_TO_FARM")
        clock.tick(3)
        assert done(mgr.evaluate(ctl, engine)) == ["ACK", "START", "TRANSFER", "SHARE"]
        run(ctl, "farm_d", "SET_AUTO")
        clock.tick(1)
        view = mgr.evaluate(ctl, engine)
        assert view["session"]["outcome"] == "PASS", view["session"]
        assert view["session"]["score"] == 100

    def test_drill12_bus_fault_restore(self, world, clock):
        ctl, engine, mgr = world
        mgr.start("DRILL-12", "trainee", ctl, engine)
        clock.tick(2)
        mgr.evaluate(ctl, engine)
        engine.ack_all("trainee")
        for dev, cmd in (
            ("mv_rect_d", "OPEN_INPUT"),
            ("sscb_d", "CLEAR_FAULT"),
            ("sscb_d", "RESET"),
            ("mv_rect_d", "CLOSE_INPUT"),
            ("sscb_d", "CLOSE"),
            ("bess_d", "RESET"),
            ("bess_d", "CLOSE_BREAKER"),
        ):
            run(ctl, dev, cmd)
            clock.tick(2)
            mgr.evaluate(ctl, engine)
        view = mgr.evaluate(ctl, engine)
        assert view["session"]["outcome"] == "PASS", view["session"]
        assert done(view) == ["ACK", "ISOLATE", "CLEAR", "RESET", "INPUT", "CLOSE", "BESS"]

    def test_drill12_unplanned_switching_costs_points(self, world, clock):
        ctl, engine, mgr = world
        mgr.start("DRILL-12", "trainee", ctl, engine)
        ctl.set_authority("farm_d", dc.AUTH_REMOTE, "trainee")
        run(ctl, "farm_d", "START")  # not in the procedure
        clock.tick(1)
        view = mgr.evaluate(ctl, engine)
        assert view["session"]["unplanned_switching"] == 1

    def test_drill13_fails_when_nothing_is_done(self, world, clock):
        ctl, engine, mgr = world
        mgr.start("DRILL-13", "trainee", ctl, engine)
        for _ in range(10):
            clock.tick(10)
            view = mgr.evaluate(ctl, engine)
        assert view["session"]["outcome"] == "FAIL"
        assert "hall" in view["session"]["reason"].lower()

    def test_drill13_passes_with_the_bess_back(self, world, clock):
        ctl, engine, mgr = world
        mgr.start("DRILL-13", "trainee", ctl, engine)
        clock.tick(5)
        mgr.evaluate(ctl, engine)
        engine.ack_all("trainee")
        run(ctl, "bess_d_b", "CLOSE_BREAKER")
        for _ in range(14):
            clock.tick(10)
            view = mgr.evaluate(ctl, engine)
            if not view["active"]:
                break
        assert view["session"]["outcome"] == "PASS", view["session"]
        assert done(view) == ["ACK", "BESS", "ABSORB"]
