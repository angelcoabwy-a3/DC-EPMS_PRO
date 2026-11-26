"""L4 -- backend/ups_bypass.py (UPS bank system breakers, external
maintenance bypass, SKRU key interlock, QF1) and its integration in the
device controller, alarms, the /api/ups-systems route and DRILL-08."""

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
    training as tr,
    ups_bypass as ub,
)
from backend.auth.jwt_handler import issue_token, seed_demo_users  # noqa: E402
from backend.ledger import ForensicLedger  # noqa: E402
from backend.ledger.forensic_ledger import InMemoryPersistence  # noqa: E402

DESIGN = PROJECT_ROOT / "config" / "power_plant.yml"
DRILLS = PROJECT_ROOT / "config" / "training_drills"
FORWARD = ["SYSTEM_TO_BYPASS", "SKRU_RELEASE", "UNLOCK_MBB", "CLOSE_Q3", "OPEN_Q4", "LOCK_MIB",
           "SKRU_CAPTURE", "OPEN_QF1", "OPEN_Q1", "OPEN_Q2", "PADLOCK_QF1"]


def ctx(mode=ub.STATIC_BYPASS, bus=True):
    return ub.UpsContext(mode=mode, bus_live=bus, actor="op")


# ── Pure ────────────────────────────────────────────────────────────
class TestKeysAndInterlocks:
    def test_normal_keys(self):
        s = ub.UpsSystem(path="a")
        assert (s.mib_key, s.mbb_key, s.skru_keys, s.hand_keys) == (True, False, 1, 0)
        assert "locked open" in ub.interlock(s, "CLOSE_Q3", ctx())

    def test_skru_releases_only_on_static_bypass(self):
        s = ub.UpsSystem(path="a")
        assert "lamp off" in ub.interlock(s, "SKRU_RELEASE", ctx(mode=ub.INVERTER))
        assert ub.interlock(s, "SKRU_RELEASE", ctx()) is None
        s.q2 = False
        assert "lamp off" in ub.interlock(s, "SKRU_RELEASE", ctx())

    def test_mib_cannot_open_before_mbb_closes(self):
        s = ub.UpsSystem(path="a")
        assert "make before break" in ub.interlock(s, "OPEN_Q4", ctx())

    def test_inverter_refused_with_mbb_closed_or_key_out(self):
        s = ub.UpsSystem(path="a", q3=True)
        assert "parallel" in ub.interlock(s, "SYSTEM_TO_INVERTER", ctx())
        s = ub.UpsSystem(path="a", skru_keys=0, hand_keys=1)
        assert "SKRU" in ub.interlock(s, "SYSTEM_TO_INVERTER", ctx())

    def test_full_forward_and_park(self):
        s = ub.UpsSystem(path="a")
        c = ctx()
        effects = []
        for a in FORWARD[1:]:
            reason = ub.interlock(s, a, c)
            assert reason is None, (a, reason)
            effects.append(ub.apply(s, a, c))
        assert "park" in effects
        assert (s.q3, s.q4, s.q1, s.q2, s.qf1) == (True, False, False, False, False)
        assert (s.mbb_key, s.mib_key, s.skru_keys, s.hand_keys) == (True, False, 1, 0)
        assert s.qf1_padlock == "op"
        assert "padlocked" in ub.interlock(s, "CLOSE_QF1", c)

    def test_mbb_cannot_open_without_ups_output(self):
        s = ub.UpsSystem(path="a", q3=True, q4=False, mbb_key=True)
        assert "drop the critical load" in ub.interlock(s, "OPEN_Q3", ctx(mode=ub.OFF))

    def test_padlock_owner(self):
        s = ub.UpsSystem(path="a", qf1=False, qf1_padlock="alice")
        assert "alice" in ub.interlock(s, "UNPADLOCK_QF1", ctx())


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


def us(ctl, path="a"):
    return ctl.path_summary(path)["ups_system"]


class TestController:
    def test_summary_carries_the_system(self, world):
        ctl, _ = world
        s = us(ctl)
        assert (s["mode"], s["load_source"], s["skru_lamp"]) == ("INVERTER", "INVERTER", False)

    def test_forward_keeps_the_load_and_ends_on_mbb(self, world):
        ctl, clock = world
        for a in FORWARD:
            clock.t += 2
            ctl.ups_action("a", a, "op")
        s = ctl.path_summary("a")
        assert s["load_lost"] is False
        assert s["load_feed"] == "maintenance bypass"
        assert all(d.state == dc.UPS_ISOLATED for d in ctl._of(dc.KIND_UPS, "a"))
        alarms = {c.alarm_id for c in ae.conditions_from_plant(ctl.snapshot_all()) if c.active}
        assert {"PATH_A_UPS_MAINT_BYPASS", "PATH_A_UPS_QF1_OPEN"} <= alarms

    def test_utility_loss_on_mbb_drops_the_load(self, world):
        ctl, clock = world
        for a in FORWARD[:5]:
            ctl.ups_action("a", a, "op")
        ctl.inject_utility_loss("a", "op")
        clock.t += 1
        assert ctl.path_summary("a")["load_lost"] is True

    def test_q1_open_puts_the_inverter_on_battery(self, world):
        ctl, clock = world
        ctl.ups_action("a", "OPEN_Q1", "op")
        clock.t += 1
        s = ctl.path_summary("a")
        assert s["on_battery"] is True
        assert "Q1" in s["load_feed"]
        assert ctl.snapshot("ups_a_01")["status"]["text"].startswith("On battery")

    def test_qf1_open_and_q1_open_loses_the_load(self, world):
        ctl, clock = world
        ctl.ups_action("a", "OPEN_QF1", "op")
        ctl.ups_action("a", "OPEN_Q1", "op")
        clock.t += 1
        assert ctl.path_summary("a")["load_lost"] is True

    def test_q2_open_with_blocks_on_static_bypass_loses_the_load(self, world):
        ctl, clock = world
        ctl.ups_action("a", "SYSTEM_TO_BYPASS", "op")
        ctl.ups_action("a", "OPEN_Q2", "op")
        clock.t += 1
        assert ctl.path_summary("a")["load_lost"] is True

    def test_return_to_normal(self, world):
        ctl, clock = world
        for a in FORWARD[:-1]:
            ctl.ups_action("a", a, "op")
        back = ["CLOSE_QF1", "CLOSE_Q2", "CLOSE_Q1", "SKRU_RELEASE", "UNLOCK_MIB", "CLOSE_Q4",
                "OPEN_Q3", "LOCK_MBB", "SKRU_CAPTURE", "SYSTEM_TO_INVERTER"]
        for a in back:
            clock.t += 2
            ctl.ups_action("a", a, "op")
        s = ctl.path_summary("a")
        assert (s["load_lost"], s["ups_system"]["mode"]) == (False, "INVERTER")
        assert s["ups_in_service"] == 8

    def test_block_commands_respect_the_system(self, world):
        ctl, _ = world
        ctl.ups_action("a", "SYSTEM_TO_BYPASS", "op")
        ctl.ups_action("a", "SKRU_RELEASE", "op")
        reason = ctl.blocked_reason(ctl.devices["ups_a_01"], "RETURN_TO_DOUBLE_CONVERSION")
        assert "SKRU" in reason

    def test_shunt_trip(self, world):
        ctl, _ = world
        ctl.inject_qf1_shunt_trip("a", "training")
        assert us(ctl)["breakers"]["QF1"] is False
        with pytest.raises(dc.DeviceControlError):
            ctl.ups_action("z", "OPEN_Q1", "op")


# ── DRILL-08 ────────────────────────────────────────────────────────
class TestDrill08:
    def _run(self, world, actions):
        ctl, clock = world
        tm = tr.TrainingManager(tr.load_drills(DRILLS), clock=clock)
        eng = ae.AlarmEngine()
        tm.start("DRILL-08", "op", ctl, eng)
        view = None
        for a in actions:
            clock.t += 3
            try:
                ctl.ups_action("a", a, "op")
            except dc.DeviceControlError as exc:
                ctl.ups_refusal("a", "op", exc.detail, a)
            view = tm.evaluate(ctl, eng)
        return view["session"]

    def test_pass(self, world):
        s = self._run(world, FORWARD)
        assert (s["outcome"], s["score"]) == ("PASS", 100)

    def test_out_of_order_is_refused_and_counted(self, world):
        s = self._run(world, ["OPEN_Q4", *FORWARD])
        assert s["outcome"] == "PASS"
        assert s["score"] == 90

    def test_fail_on_q2_with_static_bypass(self, world):
        s = self._run(world, ["SYSTEM_TO_BYPASS", "OPEN_Q2"])
        assert s["outcome"] == "FAIL"


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
        url = "/api/ups-systems/a/action"
        assert c.post(url, json={"action": "OPEN_Q1"}, headers=bearer("operator")).status_code == 403
        assert c.post(url, json={"action": "OPEN_Q4"}, headers=h).status_code == 409
        assert any(e["event"] == "refused" and e.get("command") == "OPEN_Q4@UPS_A" for e in ctl._events)
        r = c.post(url, json={"action": "SYSTEM_TO_BYPASS"}, headers=h)
        assert r.status_code == 200
        entries = c.app.state.forensic_ledger.persistence._entries
        last = next(e for e in entries if e.entry_id == r.json()["ledger_entry_id"])
        assert last.action == dc.ACTION_UPS_FIELD
        assert last.payload["mode"] == "STATIC_BYPASS"
