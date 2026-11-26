"""L5 -- backend/battery_room.py (strings of VRLA jars, infrared scan,
battery analyzer, string disconnects, mid-string links, H2 exhaust) and
its integration in the device controller, alarms, the
/api/battery-rooms route and DRILL-09."""

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
    battery_room as br,
    device_control as dc,
    training as tr,
)
from backend.auth.jwt_handler import issue_token, seed_demo_users  # noqa: E402
from backend.ledger import ForensicLedger  # noqa: E402
from backend.ledger.forensic_ledger import InMemoryPersistence  # noqa: E402

DESIGN = PROJECT_ROOT / "config" / "power_plant.yml"
DRILLS = PROJECT_ROOT / "config" / "training_drills"
REPAIR = ["OPEN_SB3", "PADLOCK_SB3", "BREAK_LINK_S3", "REPLACE_S3_J18", "MAKE_LINK_S3",
          "UNPADLOCK_SB3", "CLOSE_SB3"]


def ctx(**kw):
    return br.BatteryContext(**{"actor": "op", **kw})


def hot_room():
    room = br.BatteryRoom(path="a")
    br.inject_defect(room, **br.DEFAULT_DEFECT)
    return room


# ── Pure ────────────────────────────────────────────────────────────
class TestModel:
    def test_float_voltage_and_layout(self):
        room = br.BatteryRoom(path="a")
        assert len(room.strings) == 4
        assert all(len(s.jars) == 40 for s in room.strings)
        d = br.describe(room, ctx())
        assert d["bus_v"] == 542.1
        assert all(abs(s["voltage_v"] - 542.1) < 0.2 for s in d["strings"])
        assert d["strings_online"] == 4

    def test_parse(self):
        assert br.parse_action("measure_s3_j18") == ("MEASURE", 3, 18)
        assert br.parse_action("OPEN_SB2") == ("OPEN_SB", 2, 0)
        assert br.parse_action("EF2_HAND") == ("EF2_HAND", 0, 0)
        assert br.parse_action("MEASURE_S3_J41") is None
        assert br.parse_action("OPEN_SB5") is None
        assert br.is_inspection("IR_SCAN_S1")
        assert not br.is_inspection("OPEN_SB1")

    def test_shorted_cell_pushes_the_string_up(self):
        room = hot_room()
        st = br.string_of(room, 3)
        bad = br.jar_voltage(room, st, br.jar_of(room, 3, 18), ctx())
        good = br.jar_voltage(room, st, br.jar_of(room, 3, 1), ctx())
        assert bad == 10.4
        assert good == pytest.approx((542.1 - 10.4) / 39, abs=0.001)
        d = br.describe(room, ctx())
        assert d["strings"][2]["float_high"] is True
        assert d["strings"][0]["float_high"] is False

    def test_ir_scan_and_analyzer(self):
        room = hot_room()
        scan = br.apply(room, "IR_SCAN_S3", ctx())
        assert scan["hottest"] == "S3J18"
        assert scan["delta_c"] > br.DT_ALARM_C
        reading = br.apply(room, "MEASURE_S3_J18", ctx())
        assert reading["status"] == "REPLACE"
        assert reading["rise_pct"] > 50
        assert reading["v"] == 10.4
        ok = br.apply(room, "MEASURE_S1_J5", ctx())
        assert ok["status"] == "OK"
        assert room.scanned == [3]
        assert room.measured == ["S3J18", "S1J5"]

    def test_isolation_order(self):
        room = hot_room()
        assert "isolated" in br.interlock(room, "REPLACE_S3_J18", ctx())
        assert "first" in br.interlock(room, "BREAK_LINK_S3", ctx())
        assert "open it" in br.interlock(room, "PADLOCK_SB3", ctx())
        for a in REPAIR[:3]:
            assert br.interlock(room, a, ctx()) is None
            br.apply(room, a, ctx())
        assert br.interlock(room, "REPLACE_S3_J18", ctx()) is None
        assert "padlock" in br.interlock(room, "CLOSE_SB3", ctx())
        br.apply(room, "UNPADLOCK_SB3", ctx())
        assert "link" in br.interlock(room, "CLOSE_SB3", ctx())

    def test_padlock_owner(self):
        room = br.BatteryRoom(path="a")
        br.apply(room, "OPEN_SB1", ctx())
        br.apply(room, "PADLOCK_SB1", ctx())
        assert "owner" in br.interlock(room, "UNPADLOCK_SB1", ctx(actor="other"))
        assert "padlock" in br.interlock(room, "CLOSE_SB1", ctx())

    def test_hot_jar_runs_away_while_on_line(self):
        room = hot_room()
        events = []
        for _ in range(300):
            events += br.tick(room, 1.0, ctx())
        assert any(e["event"] == "thermal_runaway" for e in events)
        assert br.string_of(room, 3).closed is False
        assert "vented" in br.interlock(room, "CLOSE_SB3", ctx())

    def test_hot_jar_cools_when_isolated(self):
        room = hot_room()
        br.apply(room, "OPEN_SB3", ctx())
        for _ in range(300):
            br.tick(room, 1.0, ctx())
        assert br.jar_of(room, 3, 18).temp_c < 30.0
        assert not room.runaway

    def test_hydrogen_and_fans(self):
        room = br.BatteryRoom(path="a")
        for _ in range(400):
            br.tick(room, 1.0, ctx())
        assert room.h2_ppm < br.H2_ALARM_PPM
        room.fans["EF1"].failed = True
        events = []
        for _ in range(400):
            events += br.tick(room, 1.0, ctx())
        assert any(e["event"] == "fan_start" for e in events)       # EF-2 lag on 1 % LEL
        assert room.h2_ppm < br.H2_ALARM_PPM
        room.fans["EF2"].mode = "OFF"
        for _ in range(200):
            br.tick(room, 1.0, ctx())
        assert room.h2_ppm > br.H2_ALARM_PPM
        assert "no tripped" in br.interlock(room, "EF2_RESET", ctx())
        assert br.interlock(room, "EF1_RESET", ctx()) is None


# ── Controller ──────────────────────────────────────────────────────
class Clock:
    def __init__(self):
        self.t = 1_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def world():
    clock = Clock()
    ctl = dc.DeviceController.from_design(dc.load_design(DESIGN), clock=clock, wall_clock=clock)
    return ctl, clock


def room(ctl, path="a"):
    return ctl.path_summary(path)["battery_room"]


class TestController:
    def test_summary_and_alarm(self, world):
        ctl, clock = world
        assert room(ctl)["strings_online"] == 4
        ctl.inject_battery_condition("a", "hot_jar", "training")
        clock.t += 1
        alarms = {c.alarm_id for c in ae.conditions_from_plant(ctl.snapshot_all()) if c.active}
        assert "PATH_A_BATT_STRING_CURRENT" in alarms

    def test_inspection_is_not_a_command(self, world):
        ctl, _ = world
        ev = ctl.battery_action("a", "MEASURE_S1_J1", "op")
        assert ev["event"] == "inspection"
        assert ev["reading"]["jar"] == "S1J1"
        ev = ctl.battery_action("a", "OPEN_SB1", "op")
        assert ev["event"] == "command"
        assert ev["command"] == "OPEN_SB1@BATT_A"

    def test_strings_scale_battery_energy(self, world):
        ctl, _ = world
        full = ctl._battery_energy_kwh("a")
        ctl.battery_action("a", "OPEN_SB1", "op")
        assert ctl._battery_energy_kwh("a") == pytest.approx(full * 0.75)
        alarms = {c.alarm_id for c in ae.conditions_from_plant(ctl.snapshot_all()) if c.active}
        assert "PATH_A_BATT_STRING_OFFLINE" in alarms

    def test_all_strings_open_on_battery_loses_the_load(self, world):
        ctl, clock = world
        for n in (1, 2, 3, 4):
            ctl.battery_action("a", f"OPEN_SB{n}", "op")
        ctl.inject_utility_loss("a", "op")
        clock.t += 1
        assert ctl.path_summary("a")["load_lost"] is True

    def test_refusal_and_bad_input(self, world):
        ctl, _ = world
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.battery_action("a", "REPLACE_S1_J1", "op")
        assert exc.value.status == 409
        with pytest.raises(dc.DeviceControlError):
            ctl.battery_action("a", "SMASH_JAR", "op")
        with pytest.raises(dc.DeviceControlError):
            ctl.inject_battery_condition("a", "flood", "op")

    def test_reset_restores_the_room(self, world):
        ctl, _ = world
        ctl.battery_action("a", "OPEN_SB2", "op")
        ctl.reset("op")
        assert room(ctl)["strings_online"] == 4


# ── DRILL-09 ────────────────────────────────────────────────────────
class TestDrill09:
    def _run(self, world, actions, step_s=3):
        ctl, clock = world
        tm = tr.TrainingManager(tr.load_drills(DRILLS), clock=clock)
        eng = ae.AlarmEngine()
        tm.start("DRILL-09", "op", ctl, eng)
        view = tm.evaluate(ctl, eng)
        for a in actions:
            clock.t += step_s
            try:
                ctl.battery_action("a", a, "op")
            except dc.DeviceControlError as exc:
                ctl.battery_refusal("a", "op", exc.detail, a)
            view = tm.evaluate(ctl, eng)
        return view["session"]

    def test_pass(self, world):
        s = self._run(world, ["IR_SCAN_S3", "MEASURE_S3_J18", *REPAIR])
        assert (s["outcome"], s["score"]) == ("PASS", 100)

    def test_replace_before_isolation_is_refused(self, world):
        s = self._run(world, ["IR_SCAN_S3", "MEASURE_S3_J18", "REPLACE_S3_J18", *REPAIR])
        assert (s["outcome"], s["score"]) == ("PASS", 90)

    def test_runaway_fails(self, world):
        ctl, clock = world
        tm = tr.TrainingManager(tr.load_drills(DRILLS), clock=clock)
        eng = ae.AlarmEngine()
        tm.start("DRILL-09", "op", ctl, eng)
        for _ in range(60):
            clock.t += 5
            view = tm.evaluate(ctl, eng)
        assert view["session"]["outcome"] == "FAIL"
        assert "runaway" in view["session"]["reason"]


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
    def test_route_ledger_and_refusal(self, client):
        c, ctl = client
        h = bearer("manager")
        url = "/api/battery-rooms/a/action"
        assert c.post(url, json={"action": "OPEN_SB1"}, headers=bearer("operator")).status_code == 403
        assert c.post(url, json={"action": "CLOSE_SB1"}, headers=h).status_code == 409
        assert any(e["event"] == "refused" and e.get("command") == "CLOSE_SB1@BATT_A" for e in ctl._events)
        r = c.post(url, json={"action": "MEASURE_S2_J7"}, headers=h)
        assert r.status_code == 200
        entries = c.app.state.forensic_ledger.persistence._entries
        last = next(e for e in entries if e.entry_id == r.json()["ledger_entry_id"])
        assert last.action == dc.ACTION_BATT_FIELD
        assert last.payload["reading"]["jar"] == "S2J7"
