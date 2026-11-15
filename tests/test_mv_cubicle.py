"""L1 -- backend/mv_cubicle.py (pure interlocks of the 52-U / 52-GM
draw-out cubicles) and their integration in the device controller and
the /field route."""

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
    mv_cubicle as cub,
)
from backend.auth.jwt_handler import issue_token, seed_demo_users  # noqa: E402
from backend.ledger import ForensicLedger  # noqa: E402
from backend.ledger.forensic_ledger import InMemoryPersistence  # noqa: E402

DESIGN = PROJECT_ROOT / "config" / "power_plant.yml"


def ctx(now=0.0, local=True, main_closed=False, plant=None, actor="op"):
    return cub.CubicleContext(now=now, local_authority=local, main_closed=main_closed,
                              plant_close_reason=plant, actor=actor)


# ── Pure interlocks ─────────────────────────────────────────────────
class TestPure:
    def test_c8_local_authority_except_86_trip(self):
        c = cub.Cubicle(breaker="52-GM")
        assert "C8" in cub.interlock(c, cub.RACK_OUT, ctx(local=False))
        assert cub.interlock(c, cub.TRIP_86, ctx(local=False)) is None

    def test_c1_no_racking_while_closed(self):
        c = cub.Cubicle(breaker="52-U")
        assert "C1" in cub.interlock(c, cub.RACK_OUT, ctx(main_closed=True))
        assert cub.interlock(c, cub.RACK_OUT, ctx(main_closed=False)) is None

    def test_rack_sequence_and_limits(self):
        c = cub.Cubicle(breaker="52-GM")
        cub.apply(c, cub.RACK_OUT, ctx())
        assert c.racking == cub.TEST
        cub.apply(c, cub.RACK_OUT, ctx())
        assert c.racking == cub.DISCONNECTED
        assert "already DISCONNECTED" in cub.interlock(c, cub.RACK_OUT, ctx())
        cub.apply(c, cub.RACK_IN, ctx())
        assert c.racking == cub.TEST

    def test_close_in_test_discharges_spring_and_motor_recharges(self):
        c = cub.Cubicle(breaker="52-GM", racking=cub.TEST)
        assert cub.apply(c, cub.LOCAL_CLOSE, ctx(now=10)) is None
        assert (c.test_closed, c.spring_charged) == (True, False)
        assert "C1" in cub.interlock(c, cub.RACK_OUT, ctx())
        assert not cub.tick(c, 10 + cub.SPRING_MOTOR_CHARGE_S - 0.1)
        assert cub.tick(c, 10 + cub.SPRING_MOTOR_CHARGE_S)
        assert c.spring_charged

    def test_stored_energy_release_with_motor_off(self):
        c = cub.Cubicle(breaker="52-GM", racking=cub.TEST)
        cub.apply(c, cub.MOTOR_OFF, ctx())
        cub.apply(c, cub.LOCAL_CLOSE, ctx(now=1))
        cub.apply(c, cub.LOCAL_OPEN, ctx(now=2))
        assert not cub.tick(c, 1000)
        assert (c.spring_charged, c.test_closed) == (False, False)
        assert "C2" in cub.interlock(c, cub.LOCAL_CLOSE, ctx())

    def test_manual_pump_needs_five_strokes(self):
        c = cub.Cubicle(breaker="52-U", spring_charged=False, motor_on=False)
        for _ in range(cub.SPRING_PUMPS_TO_CHARGE - 1):
            cub.apply(c, cub.PUMP_SPRING, ctx())
        assert not c.spring_charged
        cub.apply(c, cub.PUMP_SPRING, ctx())
        assert (c.spring_charged, c.pumps) == (True, 0)
        assert "already charged" in cub.interlock(c, cub.PUMP_SPRING, ctx())

    def test_c3_86_blocks_close_and_trips_a_closed_breaker(self):
        c = cub.Cubicle(breaker="52-U")
        assert cub.apply(c, cub.TRIP_86, ctx(main_closed=True)) == "main_open"
        assert "C3" in cub.interlock(c, cub.LOCAL_CLOSE, ctx())
        cub.apply(c, cub.RESET_86, ctx())
        assert cub.interlock(c, cub.LOCAL_CLOSE, ctx()) is None

    def test_c4_no_electrical_close_when_disconnected(self):
        c = cub.Cubicle(breaker="52-U", racking=cub.DISCONNECTED)
        assert "C4" in cub.interlock(c, cub.LOCAL_CLOSE, ctx())

    def test_plant_reason_applies_only_on_the_bus(self):
        c = cub.Cubicle(breaker="52-U")
        assert cub.interlock(c, cub.LOCAL_CLOSE, ctx(plant="Interlock: 52-GM is closed")) \
            == "Interlock: 52-GM is closed"
        c.racking = cub.TEST
        assert cub.interlock(c, cub.LOCAL_CLOSE, ctx(plant="Interlock: 52-GM is closed")) is None

    def test_padlock_rules_c5_c6_c7(self):
        c = cub.Cubicle(breaker="52-GM", racking=cub.TEST)
        assert "C6" in cub.interlock(c, cub.PADLOCK, ctx())
        c.racking = cub.DISCONNECTED
        cub.apply(c, cub.PADLOCK, ctx(actor="ana"))
        assert c.padlock == "ana"
        assert "C5" in cub.interlock(c, cub.RACK_IN, ctx())
        assert "C7" in cub.interlock(c, cub.UNPADLOCK, ctx(actor="bob"))
        assert cub.interlock(c, cub.UNPADLOCK, ctx(actor="ana")) is None

    def test_close_reason_for_remote_and_auto(self):
        c = cub.Cubicle(breaker="52-GM", racking=cub.TEST)
        assert "rack it in" in cub.close_reason(c)
        c.racking, c.lockout_86 = cub.CONNECTED, True
        assert "86" in cub.close_reason(c)
        c.lockout_86, c.spring_charged, c.motor_on = False, False, False
        assert "motor OFF" in cub.close_reason(c)

    def test_describe_is_honest_about_arc_flash(self):
        d = cub.describe(cub.Cubicle(breaker="52-U"), ctx())
        assert d["arc_flash"]["study"] is None
        assert "NOT PERFORMED" in d["arc_flash"]["label"]
        assert {a["action"] for a in d["actions"]} == set(cub.ACTIONS)

    def test_unknown_action(self):
        assert "unknown" in cub.interlock(cub.Cubicle(breaker="52-U"), "FLY", ctx())


# ── Controller integration ──────────────────────────────────────────
class Clock:
    def __init__(self):
        self.t = 1_763_200_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def world():
    clock = Clock()
    ctl = dc.DeviceController.from_design(dc.load_design(DESIGN), clock=clock, wall_clock=clock)
    return ctl, clock


def run(ctl, device_id, command, actor="op"):
    sel = ctl.select(device_id, command, actor)
    return ctl.operate(device_id, sel["select_token"], actor)


class TestController:
    def test_field_needs_local_and_rack_out_of_open_gm(self, world):
        ctl, _ = world
        with pytest.raises(dc.DeviceControlError, match="C8"):
            ctl.field_action("mvtc_a", "52-GM", cub.RACK_OUT, "op")
        ctl.set_authority("mvtc_a", dc.AUTH_LOCAL, "op")
        ev = ctl.field_action("mvtc_a", "52-GM", cub.RACK_OUT, "op")
        assert (ev["command"], ev["racking"], ev["field"]) == ("RACK_OUT@52-GM", cub.TEST, True)
        with pytest.raises(dc.DeviceControlError, match="C1"):
            ctl.field_action("mvtc_a", "52-U", cub.RACK_OUT, "op")

    def test_local_open_of_the_incomer_kills_the_bus(self, world):
        ctl, _ = world
        ctl.set_authority("mvtc_a", dc.AUTH_LOCAL, "op")
        ev = ctl.field_action("mvtc_a", "52-U", cub.LOCAL_OPEN, "op")
        assert ev["to_state"] == dc.XFER_OPEN
        assert ctl.path_summary("a")["bus_energized"] is False
        # Reclose locally: the spring was charged, so it closes and discharges.
        ev = ctl.field_action("mvtc_a", "52-U", cub.LOCAL_CLOSE, "op")
        assert ev["to_state"] == dc.XFER_UTILITY
        assert ctl.cubicles[("a", "52-U")].spring_charged is False

    def test_local_close_of_gm_onto_a_live_bus_is_interlocked(self, world):
        ctl, _ = world
        ctl.set_authority("mvtc_a", dc.AUTH_LOCAL, "op")
        with pytest.raises(dc.DeviceControlError, match="52-U is closed"):
            ctl.field_action("mvtc_a", "52-GM", cub.LOCAL_CLOSE, "op")

    def test_86_trip_opens_the_incomer_and_holds_auto(self, world):
        ctl, clock = world
        assert ctl.devices["mvtc_a"].authority == dc.AUTH_AUTO
        ctl.field_action("mvtc_a", "52-U", cub.TRIP_86, "op")      # allowed without LOCAL
        snap = ctl.snapshot("mvtc_a")
        # AUTO cannot reclose 52-U through the lockout: it treats the
        # utility as unavailable and starts the emergency source.
        assert snap["state"] == dc.XFER_OPEN
        assert "86" in snap["auto_blocked"]
        assert any(e["event"] == "auto_start" for e in ctl._events)
        clock.t += dc.CRANK_TIME_S + 1
        assert ctl.snapshot("mvtc_a")["state"] == dc.XFER_GENERATORS

    def test_remote_transfer_blocked_by_racked_out_gm(self, world):
        ctl, clock = world
        ctl.set_authority("mvtc_a", dc.AUTH_LOCAL, "op")
        ctl.field_action("mvtc_a", "52-GM", cub.RACK_OUT, "op")
        ctl.set_authority("mvtc_a", dc.AUTH_REMOTE, "op")
        run(ctl, "mvtc_a", "START_GENERATORS")
        clock.t += dc.CRANK_TIME_S + 1
        ctl.snapshot_all()
        reason = ctl.blocked_reason(ctl.devices["mvtc_a"], "TRANSFER_TO_GENERATORS")
        assert "racked to TEST" in reason

    def test_remote_close_discharges_the_spring_and_motor_recharges(self, world):
        ctl, clock = world
        ctl.set_authority("mvtc_a", dc.AUTH_REMOTE, "op")
        ctl.inject_utility_loss("a", "t")
        ctl.restore_utility("a", "t")
        run(ctl, "mvtc_a", "RETRANSFER_TO_UTILITY")
        c = ctl.cubicles[("a", "52-U")]
        assert c.spring_charged is False
        clock.t += cub.SPRING_MOTOR_CHARGE_S + 0.1
        ctl.snapshot_all()
        assert c.spring_charged is True
        assert any(e["event"] == "spring_charged" for e in ctl._events)

    def test_snapshot_and_alarms(self, world):
        ctl, _ = world
        ctl.set_authority("mvtc_a", dc.AUTH_LOCAL, "op")
        ctl.field_action("mvtc_a", "52-GM", cub.RACK_OUT, "op")
        ctl.field_action("mvtc_a", "52-GM", cub.TRIP_86, "op")
        plant = ctl.snapshot_all()
        x = next(d for d in plant["devices"] if d["id"] == "mvtc_a")
        gm = next(c for c in x["cubicles"] if c["breaker"] == "52-GM")
        assert (gm["racking"], gm["lockout_86"], gm["control_power"]) == (cub.TEST, True, True)
        ids = {c.alarm_id for c in ae.conditions_from_plant(plant) if c.active}
        assert "DEV_mvtc_a_52GM_UNAVAILABLE" in ids
        assert "DEV_mvtc_a_52GM_86" in ids

    def test_reset_restores_the_cubicles(self, world):
        ctl, _ = world
        ctl.set_authority("mvtc_a", dc.AUTH_LOCAL, "op")
        ctl.field_action("mvtc_a", "52-GM", cub.RACK_OUT, "op")
        ctl.reset("t")
        assert ctl.cubicles[("a", "52-GM")].racking == cub.CONNECTED

    def test_unknown_breaker_and_device(self, world):
        ctl, _ = world
        with pytest.raises(dc.DeviceControlError):
            ctl.field_action("mvtc_a", "52-X", cub.RACK_OUT, "op")
        with pytest.raises(dc.DeviceControlError):
            ctl.field_action("ups_a_01", "52-U", cub.RACK_OUT, "op")


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
    def test_field_route_ledger_and_refusal(self, client):
        c, ctl = client
        h = bearer("manager")
        assert c.post("/api/devices/mvtc_a/field", json={"breaker": "52-GM", "action": "RACK_OUT"},
                      headers=bearer("operator")).status_code == 403
        r = c.post("/api/devices/mvtc_a/field", json={"breaker": "52-GM", "action": "RACK_OUT"}, headers=h)
        assert r.status_code == 409                                  # not LOCAL
        assert any(e["event"] == "refused" and e.get("command") == "RACK_OUT@52-GM" for e in ctl._events)
        c.post("/api/devices/mvtc_a/authority", json={"authority": "LOCAL"}, headers=h)
        r = c.post("/api/devices/mvtc_a/field", json={"breaker": "52-GM", "action": "RACK_OUT"}, headers=h)
        assert r.status_code == 200
        body = r.json()
        assert body["ledger_entry_id"]
        entries = c.app.state.forensic_ledger.persistence._entries
        last = next(e for e in entries if e.entry_id == body["ledger_entry_id"])
        assert (last.action, last.payload["racking"]) == (dc.ACTION_MV_FIELD, cub.TEST)
