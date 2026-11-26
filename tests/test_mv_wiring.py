"""L5 -- backend/mv_wiring.py (PT secondary fuses F-1A / F-1B, TB-1 and
the multimeter) and its integration in the device controller: loss of
utility sensing trips 52-U and starts a false emergency transfer;
generator bus sensing holds 52-GM; the /wiring route and DRILL-10."""

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
    mv_wiring as mw,
    training as tr,
)
from backend.auth.jwt_handler import issue_token, seed_demo_users  # noqa: E402
from backend.ledger import ForensicLedger  # noqa: E402
from backend.ledger.forensic_ledger import InMemoryPersistence  # noqa: E402

DESIGN = PROJECT_ROOT / "config" / "power_plant.yml"
DRILLS = PROJECT_ROOT / "config" / "training_drills"


def read(w, point, mode, **kw):
    w.meter = mode
    return mw.measure(w, point, mw.WiringContext(**kw))


# ── Pure ────────────────────────────────────────────────────────────
class TestMeter:
    def test_healthy_readings(self):
        w = mw.ControlWiring(path="a")
        assert read(w, "F1A_LINE", "VAC")["display"] == "120.0 V~"
        assert read(w, "F1A_LOAD", "VAC")["value"] == 120.0
        assert read(w, "F1A_FUSE", "VAC")["value"] == 0.0
        assert read(w, "P1_N1", "VDC")["value"] == mw.STATION_DC_V
        assert read(w, "P1_N1", "VAC")["value"] == 0.0

    def test_blown_fuse_in_circuit(self):
        w = mw.ControlWiring(path="a")
        w.fuses["F-1A"].ok = False
        assert read(w, "F1A_LINE", "VAC")["value"] == 120.0
        assert read(w, "F1A_LOAD", "VAC")["value"] == 0.0
        assert read(w, "F1A_FUSE", "VAC")["value"] == 120.0     # full voltage across a blown fuse
        live = read(w, "F1A_FUSE", "OHM")
        assert live["display"] == "LIVE"
        assert live["warning"]
        w.fuses["F-1A"].pulled = True
        assert read(w, "F1A_FUSE", "OHM")["display"] == "OL"
        w.fuses["F-1A"].ok = True
        r = read(w, "F1A_FUSE", "OHM")
        assert r["beep"] is True
        assert r["value"] == mw.FUSE_OHM

    def test_coil_circuits_and_start_contact(self):
        w = mw.ControlWiring(path="a")
        assert read(w, "TC_52U", "VDC", u_closed=True)["value"] == mw.STATION_DC_V
        assert read(w, "CC_52U", "VDC", u_closed=True, u_close_ok=True)["value"] == 0.0
        assert read(w, "CC_52GM", "VDC", gm_close_ok=True)["value"] == mw.STATION_DC_V
        assert read(w, "CC_52GM", "VDC", gm_close_ok=False)["value"] == 0.0     # 86 tripped
        assert read(w, "T73_74", "OHM", start_contact=False)["display"] == "OL"
        assert read(w, "T73_74", "OHM", start_contact=True)["beep"] is True

    def test_interlocks(self):
        w = mw.ControlWiring(path="a")
        ctx = mw.WiringContext()
        assert "OFF" in mw.interlock(w, "MEASURE_P1_N1", ctx)
        assert "pull" in mw.interlock(w, "REPLACE_F1A", ctx)
        assert "unknown" in mw.interlock(w, "BLOW_F1A", ctx)
        mw.apply(w, "PULL_F1A", ctx)
        assert "already out" in mw.interlock(w, "PULL_F1A", ctx)
        assert mw.utility_sensed(w, True) is False


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


def settle(ctl, clock, seconds=20):
    for _ in range(seconds):
        clock.t += 1
        ctl.snapshot_all()


class TestController:
    def test_blown_f1a_starts_a_false_transfer(self, world):
        ctl, clock = world
        ctl.inject_wiring_fault("a", "F-1A", "training")
        assert ctl.devices["mvtc_a"].state == dc.XFER_OPEN
        assert any(e["event"] == "protection_trip" and e.get("cause") == "loss_of_potential"
                   for e in ctl._events)
        settle(ctl, clock)
        s = ctl.path_summary("a")
        assert ctl.devices["mvtc_a"].state == dc.XFER_GENERATORS
        assert (s["incomer_live"], s["utility_sensed"], s["load_lost"]) == (True, False, False)

    def test_pulling_f1a_on_utility_trips_52u(self, world):
        ctl, _ = world
        ctl.wiring_action("mvtc_a", "PULL_F1A", "op")
        assert ctl.devices["mvtc_a"].state != dc.XFER_UTILITY

    def test_retransfer_needs_sensing_back(self, world):
        ctl, clock = world
        ctl.inject_wiring_fault("a", "F1A", "training")
        settle(ctl, clock)
        dev = ctl.devices["mvtc_a"]
        assert "ANSI 27" in ctl.blocked_reason(dev, "RETRANSFER_TO_UTILITY")
        for a in ("PULL_F1A", "REPLACE_F1A", "INSERT_F1A"):
            ctl.wiring_action("mvtc_a", a, "op")
        assert ctl.blocked_reason(dev, "RETRANSFER_TO_UTILITY") is None

    def test_blown_f1b_holds_52gm(self, world):
        ctl, clock = world
        ctl.inject_wiring_fault("a", "F-1B", "training")
        ctl.inject_utility_loss("a", "training")
        settle(ctl, clock, 30)
        assert ctl.devices["mvtc_a"].state == dc.XFER_OPEN
        held = [e for e in ctl._events if e["event"] == "auto_transfer_blocked"]
        assert held
        assert "not sensed" in held[-1]["detail"]

    def test_snapshot_and_bad_input(self, world):
        ctl, _ = world
        snap = ctl.snapshot("mvtc_a")
        assert snap["wiring"]["fuses"]["F-1A"] == {"ok": True, "pulled": False}
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.wiring_action("ups_a_01", "METER_VAC", "op")
        assert exc.value.status == 400
        with pytest.raises(dc.DeviceControlError):
            ctl.inject_wiring_fault("a", "F-9", "op")
        ev = ctl.wiring_action("mvtc_a", "METER_VDC", "op")
        assert ev["event"] == "inspection"


# ── DRILL-10 ────────────────────────────────────────────────────────
class TestDrill10:
    def _start(self, world):
        ctl, clock = world
        tm = tr.TrainingManager(tr.load_drills(DRILLS), clock=clock)
        eng = ae.AlarmEngine()
        tm.start("DRILL-10", "op", ctl, eng)
        for _ in range(10):
            clock.t += 2
            tm.evaluate(ctl, eng)
        return ctl, clock, tm, eng

    def _wire(self, ctl, clock, actions, tm=None, eng=None):
        for a in actions:
            if tm is not None:
                tm.evaluate(ctl, eng)
            clock.t += 2
            try:
                ctl.wiring_action("mvtc_a", a, "op")
            except dc.DeviceControlError as exc:
                ctl.refusal_event("mvtc_a", "op", exc.detail, command=f"{a}@MVTC_A")

    def _finish(self, ctl, clock, tm, eng):
        ctl.set_authority("mvtc_a", dc.AUTH_REMOTE, "op")
        for cmd in ("RETRANSFER_TO_UTILITY", "STOP_GENERATORS"):
            clock.t += 2
            tok = ctl.select("mvtc_a", cmd, "op")["select_token"]
            ctl.operate("mvtc_a", tok, "op")
            tm.evaluate(ctl, eng)
        for _ in range(40):
            clock.t += 2
            view = tm.evaluate(ctl, eng)
        return view["session"]

    DIAG = ("METER_VAC", "MEASURE_F1A_LINE", "MEASURE_F1A_LOAD", "PULL_F1A", "METER_OHM",
            "MEASURE_F1A_FUSE", "REPLACE_F1A", "INSERT_F1A")

    def test_pass(self, world):
        ctl, clock, tm, eng = self._start(world)
        assert ctl.devices["mvtc_a"].state == dc.XFER_GENERATORS
        self._wire(ctl, clock, self.DIAG, tm, eng)
        s = self._finish(ctl, clock, tm, eng)
        assert (s["outcome"], s["score"]) == ("PASS", 100), s

    def test_retransfer_before_the_fuse_is_refused(self, world):
        ctl, clock, tm, eng = self._start(world)
        ctl.set_authority("mvtc_a", dc.AUTH_REMOTE, "op")
        with pytest.raises(dc.DeviceControlError):
            ctl.select("mvtc_a", "RETRANSFER_TO_UTILITY", "op")


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
        url = "/api/devices/mvtc_a/wiring"
        assert c.post(url, json={"action": "METER_VAC"}, headers=bearer("operator")).status_code == 403
        assert c.post(url, json={"action": "INSERT_F1A"}, headers=h).status_code == 409
        assert any(e["event"] == "refused" and e.get("command") == "INSERT_F1A@MVTC_A" for e in ctl._events)
        c.post(url, json={"action": "METER_VAC"}, headers=h)
        r = c.post(url, json={"action": "MEASURE_F1A_LINE"}, headers=h)
        assert r.status_code == 200
        entries = c.app.state.forensic_ledger.persistence._entries
        last = next(e for e in entries if e.entry_id == r.json()["ledger_entry_id"])
        assert last.action == dc.ACTION_WIRING_FIELD
        assert last.payload["reading"]["value"] == 120.0
