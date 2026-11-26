"""L3 -- backend/gen_fuel.py (generator set field model: engine control,
e-stop, jacket heater, day tank, duplex pumps, fuel filter, basin) and its
integration in the device controller, alarms, the /fuel route and DRILL-07."""

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
    device_control as dc,
    gen_fuel as gf,
    training as tr,
)
from backend.auth.jwt_handler import issue_token, seed_demo_users  # noqa: E402
from backend.ledger import ForensicLedger  # noqa: E402
from backend.ledger.forensic_ledger import InMemoryPersistence  # noqa: E402

DESIGN = PROJECT_ROOT / "config" / "power_plant.yml"
DRILLS = PROJECT_ROOT / "config" / "training_drills"
G = "genset_a_01"


def ctx(running=False, bulk=gf.BULK_TANK_L):
    return gf.GenContext(running=running, stopped=not running, bulk_l=bulk, actor="op")


def do(g, action, c=None):
    c = c or ctx()
    reason = gf.interlock(g, action, c)
    assert reason is None, reason
    return gf.apply(g, action, c)


# ── Pure: fuel curve and day tank ───────────────────────────────────
class TestFuelCurve:
    def test_data_sheet_points(self):
        assert gf.burn_lph(1.0, True) == pytest.approx(694.0)
        assert gf.burn_lph(0.5, True) == pytest.approx(391.0)
        assert gf.burn_lph(0.375, True) == pytest.approx((239 + 391) / 2)
        assert gf.burn_lph(0.5, False) == 0.0

    def test_float_levels_drive_lead_and_lag(self):
        g = gf.GenSet(device_id=G, path="a", day_l=gf.DAY_TANK_L * 0.70)
        gf.refresh(g)
        assert (g.p1.running, g.p2.running) == (False, False)
        g.day_l = gf.DAY_TANK_L * 0.55
        gf.refresh(g)
        assert (g.p1.running, g.p2.running) == (True, False)
        g.day_l = gf.DAY_TANK_L * 0.39
        gf.refresh(g)
        assert (g.p1.running, g.p2.running) == (True, True)
        g.day_l = gf.DAY_TANK_L * 0.86
        gf.refresh(g)
        assert (g.p1.running, g.p2.running, g.solenoid_open) == (False, False, False)

    def test_hi_hi_stops_even_hand(self):
        g = gf.GenSet(device_id=G, path="a", day_l=gf.DAY_TANK_L * 0.96)
        g.p1.mode = gf.HAND
        gf.refresh(g)
        assert g.p1.running is False
        g.day_l = gf.DAY_TANK_L * 0.90
        gf.refresh(g)
        assert g.p1.running is True

    def test_leak_latches_and_needs_clean_then_reset(self):
        g = gf.GenSet(device_id=G, path="a", day_l=gf.DAY_TANK_L * 0.5, leak_present=True)
        events, _ = gf.tick(g, 1.0, 0.0, ctx())
        assert events[0]["event"] == "gen_basin_leak"
        assert (g.p1.running, g.solenoid_open) == (False, False)
        assert "still in the basin" in gf.interlock(g, "RESET_LEAK", ctx())
        do(g, "CLEAN_BASIN")
        do(g, "RESET_LEAK")
        assert g.p1.running is True

    def test_running_engine_drains_and_shuts_down_at_critical(self):
        g = gf.GenSet(device_id=G, path="a", day_l=gf.DAY_TANK_L * 0.2)
        g.p1.mode = g.p2.mode = gf.OFF
        shut = []
        for _ in range(30):
            ev, _ = gf.tick(g, 5.0, 0.5, ctx(running=True))
            shut += [e for e in ev if e["event"] == "gen_shutdown"]
        assert shut
        assert g.shutdown.startswith("LOW FUEL")
        assert gf.available(g)

    def test_bulk_empty_means_no_refill(self):
        g = gf.GenSet(device_id=G, path="a", day_l=gf.DAY_TANK_L * 0.5)
        _, drawn = gf.tick(g, 5.0, 0.0, ctx(bulk=0.0))
        assert drawn == 0.0


class TestEngineAndFilter:
    def test_estop_needs_release_and_stop_reset(self):
        g = gf.GenSet(device_id=G, path="a")
        assert do(g, "ESTOP_PUSH", ctx(running=True)) == "estop"
        assert "Emergency stop" in gf.available(g)
        do(g, "ESTOP_RELEASE")
        assert "STOP / RESET" in gf.available(g)
        do(g, "ECS_STOP")
        assert gf.available(g) is None
        do(g, "ECS_AUTO")

    def test_heater_off_cools_below_nfpa_minimum(self):
        g = gf.GenSet(device_id=G, path="a")
        do(g, "HEATER_OFF")
        for _ in range(40):
            gf.tick(g, 10.0, 0.0, ctx())
        assert g.coolant_c < gf.NFPA110_MIN_COOLANT_C
        assert gf.cold(g)
        assert gf.describe(g, ctx())["coolant_low"] is True

    def test_filter_restriction_starves_the_engine(self):
        g = gf.GenSet(device_id=G, path="a", filter_sel=gf.FILTER_A)
        g.clog[gf.FILTER_A] = 1.0
        ev, _ = gf.tick(g, 1.0, 1.0, ctx(running=True))
        assert g.dp_psi >= gf.DP_STARVE_PSI
        assert any(e["event"] == "gen_shutdown" for e in ev)

    def test_service_only_the_isolated_filter(self):
        g = gf.GenSet(device_id=G, path="a", filter_sel=gf.FILTER_BOTH)
        g.water[gf.FILTER_A] = 70.0
        assert "in service" in gf.interlock(g, "DRAIN_A", ctx(running=True))
        do(g, "FILTER_B", ctx(running=True))
        do(g, "DRAIN_A", ctx(running=True))
        assert g.water[gf.FILTER_A] == 0.0

    def test_describe_lists_every_action(self):
        d = gf.describe(gf.GenSet(device_id=G, path="a"), ctx())
        assert {a["action"] for a in d["actions"]} == set(gf.ACTIONS)
        assert d["time_scale"] == gf.GEN_TIME_SCALE


# ── Controller ──────────────────────────────────────────────────────
class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def world():
    clock = Clock()
    ctl = dc.DeviceController.from_design(dc.load_design(DESIGN), clock=clock, wall_clock=clock)
    return ctl, clock


def alarms(ctl):
    return {c.alarm_id for c in ae.conditions_from_plant(ctl.snapshot_all()) if c.active}


class TestController:
    def test_snapshot_carries_fuel_and_bulk(self, world):
        ctl, _ = world
        f = ctl.snapshot(G)["fuel"]
        assert (f["ecs_mode"], f["day_tank_pct"]) == ("AUTO", 80.0)
        assert ctl.path_summary("a")["bulk_fuel_pct"] == 100.0

    def test_estop_on_load_trips_the_set_and_removes_it(self, world):
        ctl, _ = world
        ctl.preset_on_generators("a", "op")
        ctl.gen_action(G, "ESTOP_PUSH", "op")
        assert ctl.devices[G].state == dc.GEN_STANDBY
        assert ctl.bays[G].cb == "OPEN"
        assert ctl.path_summary("a")["gen_available"] == 8
        assert "DEV_genset_a_01_ESTOP" in alarms(ctl)
        assert ctl._bus_energized("a")            # 8 sets still carry the path

    def test_not_in_auto_excludes_from_auto_start(self, world):
        ctl, clock = world
        ctl.gen_action(G, "ECS_STOP", "op")
        ctl.inject_utility_loss("a", "op")
        assert ctl.devices[G].state == dc.GEN_STANDBY
        assert ctl.devices["genset_a_02"].state == dc.GEN_CRANKING
        assert "DEV_genset_a_01_NOT_AUTO" in alarms(ctl)

    def test_local_run_cranks_and_cold_block_delays(self, world):
        ctl, clock = world
        ctl.inject_gen_condition(G, "heater_off", "t", coolant_c=20.0)
        ctl.gen_action(G, "ECS_RUN", "op")
        assert ctl.devices[G].state == dc.GEN_CRANKING
        clock.t += dc.CRANK_TIME_S + 1
        ctl.snapshot_all()
        assert ctl.devices[G].state == dc.GEN_CRANKING          # cold: still not ready
        clock.t += gf.COLD_START_DELAY_S
        ctl.snapshot_all()
        assert ctl.devices[G].state in (dc.GEN_RUNNING, dc.GEN_ON_LOAD)

    def test_remote_start_refused_when_not_available(self, world):
        ctl, _ = world
        ctl.gen_action(G, "ESTOP_PUSH", "op")
        assert "Emergency stop" in ctl.blocked_reason(ctl.devices[G], "START")

    def test_overload_cascade_when_too_few_sets_remain(self, world):
        ctl, _ = world
        ctl.preset_on_generators("a", "op")
        for n in range(1, 7):                    # 3 sets x 2.75 MW < about 10.9 MW
            ctl.gen_action(f"genset_a_{n:02d}", "ESTOP_PUSH", "op")
        assert not ctl._gens_on_bus("a")
        assert any("OVERLOAD" in str(e.get("detail")) for e in ctl._events)
        assert ctl._bus_energized("a") is False

    def test_reset_restores_the_sets(self, world):
        ctl, _ = world
        ctl.gen_action(G, "ESTOP_PUSH", "op")
        ctl.reset("op")
        assert ctl.snapshot(G)["fuel"]["estop"] is False

    def test_conditions_validated(self, world):
        ctl, _ = world
        with pytest.raises(dc.DeviceControlError):
            ctl.inject_gen_condition(G, "volcano", "t")
        with pytest.raises(dc.DeviceControlError):
            ctl.gen_action("mvtc_a", "ECS_STOP", "op")


# ── DRILL-07 ────────────────────────────────────────────────────────
class TestDrill07:
    def _run(self, world, actions, wait_s=5.0, ticks=12):
        ctl, clock = world
        tm = tr.TrainingManager(tr.load_drills(DRILLS), clock=clock)
        eng = ae.AlarmEngine()
        tm.start("DRILL-07", "op", ctl, eng)
        view = None
        for a in actions:
            clock.t += 2
            ctl.gen_action(G, a, "op")
            view = tm.evaluate(ctl, eng)
        for _ in range(ticks):
            clock.t += wait_s
            view = tm.evaluate(ctl, eng)
            if view["session"]["outcome"]:
                break
        return view["session"]

    def test_pass(self, world):
        s = self._run(world, ["P2_AUTO", "RESET_P1_OL"])
        assert (s["outcome"], s["score"]) == ("PASS", 100)

    def test_fail_when_nothing_is_done(self, world):
        s = self._run(world, [], wait_s=10.0, ticks=30)
        assert s["outcome"] == "FAIL"
        assert "shut down" in s["reason"]


# ── Route ───────────────────────────────────────────────────────────
@pytest.fixture
def client(monkeypatch, world):
    monkeypatch.delenv("DC_EPMS_REQUIRE_AUTH", raising=False)
    ctl, _ = world
    app = FastAPI()
    app.state.forensic_ledger = ForensicLedger(InMemoryPersistence(), key=b"k" * 32)
    dc.register_device_control_routes(app, lambda: ctl)
    with TestClient(app) as c:
        yield c, ctl


def bearer(name):
    user = seed_demo_users().find_by_username(name)
    return {"Authorization": f"Bearer {issue_token(user)}"}


class TestRoute:
    def test_fuel_route_ledger_and_refusal(self, client):
        c, ctl = client
        h = bearer("manager")
        url = f"/api/devices/{G}/fuel"
        assert c.post(url, json={"action": "ECS_STOP"}, headers=bearer("operator")).status_code == 403
        assert c.post(url, json={"action": "RESET_P1_OL"}, headers=h).status_code == 409
        assert any(e["event"] == "refused" and e.get("command") == "RESET_P1_OL@GENSET_A_01"
                   for e in ctl._events)
        r = c.post(url, json={"action": "HEATER_OFF"}, headers=h)
        assert r.status_code == 200
        entries = c.app.state.forensic_ledger.persistence._entries
        last = next(e for e in entries if e.entry_id == r.json()["ledger_entry_id"])
        assert last.action == dc.ACTION_GEN_FIELD
        assert last.payload["heater_on"] is False
