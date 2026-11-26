"""L2 -- backend/mv_xfmr.py (utility transformer: 52-T, Kirk key chain,
DETC, 63 / 87T / 86T, thermal model) and its integration in the device
controller, the alarm engine, the /xfmr route and DRILL-06."""

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
    mv_xfmr as xf,
    training as tr,
)
from backend.auth.jwt_handler import issue_token, seed_demo_users  # noqa: E402
from backend.ledger import ForensicLedger  # noqa: E402
from backend.ledger.forensic_ledger import InMemoryPersistence  # noqa: E402

DESIGN = PROJECT_ROOT / "config" / "power_plant.yml"
DRILLS = PROJECT_ROOT / "config" / "training_drills"
CHAIN = [xf.KEY_LOCK_52U, xf.OPEN_52T, xf.KEY_LOCK_52T, xf.DETC_UNLOCK]


def ctx(grid=True, u_closed=False, kv=xf.PRIMARY_KV):
    return xf.XfmrContext(grid_ok=grid, main_u_closed=u_closed, grid_kv=kv, actor="op")


def do(t, action, c=None):
    c = c or ctx()
    reason = xf.interlock(t, action, c)
    assert reason is None, reason
    return xf.apply(t, action, c)


# ── Pure: key chain and DETC ────────────────────────────────────────
class TestKeyChain:
    def test_normal_service_keys(self):
        t = xf.Transformer(path="a")
        assert (t.k1, t.k2, t.detc_unlocked_by) == (xf.KEY_IN_52U, xf.KEY_IN_52T, None)
        assert "K2" in xf.interlock(t, xf.DETC_UNLOCK, ctx())
        assert "locked" in xf.interlock(t, xf.DETC_POS_DOWN, ctx())

    def test_k1_needs_52u_open(self):
        t = xf.Transformer(path="a")
        assert "Open 52-U first" in xf.interlock(t, xf.KEY_LOCK_52U, ctx(u_closed=True))
        do(t, xf.KEY_LOCK_52U)
        assert t.k1 == xf.KEY_HAND
        assert xf.u_lock_reason(t)

    def test_52t_lock_needs_k1_and_52t_open(self):
        t = xf.Transformer(path="a")
        assert "K1" in xf.interlock(t, xf.KEY_LOCK_52T, ctx())
        do(t, xf.KEY_LOCK_52U)
        assert "Open 52-T first" in xf.interlock(t, xf.KEY_LOCK_52T, ctx())
        assert do(t, xf.OPEN_52T) == "primary_open"
        do(t, xf.KEY_LOCK_52T)
        assert (t.k1, t.k2) == (xf.KEY_IN_52T, xf.KEY_HAND)
        assert "locked open" in xf.interlock(t, xf.CLOSE_52T, ctx())

    def test_full_chain_moves_the_tap_dead(self):
        t = xf.Transformer(path="a")
        for a in CHAIN:
            do(t, a)
        assert not xf.energized(t, True)
        assert do(t, xf.DETC_POS_DOWN) is None
        assert t.tap == 2
        assert "K2 back" in xf.interlock(t, xf.KEY_UNLOCK_52T, ctx())
        assert "locked open" in xf.interlock(t, xf.CLOSE_52T, ctx())  # K1 still trapped
        do(t, xf.DETC_LOCK)
        assert t.k2 == xf.KEY_HAND
        do(t, xf.KEY_UNLOCK_52T)
        do(t, xf.CLOSE_52T)
        do(t, xf.KEY_UNLOCK_52U)
        assert xf.energized(t, True)
        assert xf.u_lock_reason(t) is None

    def test_end_stops(self):
        t = xf.Transformer(path="a", tap=1, detc_unlocked_by="K2", primary_closed=False)
        assert "end stop" in xf.interlock(t, xf.DETC_POS_DOWN, ctx())
        t.tap = 5
        assert "end stop" in xf.interlock(t, xf.DETC_POS_UP, ctx())

    def test_close_52t_refused_with_detc_unlocked(self):
        t = xf.Transformer(path="a", primary_closed=False, detc_unlocked_by="SPARE")
        assert "DETC handle is unlocked" in xf.interlock(t, xf.CLOSE_52T, ctx())

    def test_spare_key_only_when_present(self):
        t = xf.Transformer(path="a")
        assert "controlled" in xf.interlock(t, xf.DETC_SPARE_KEY, ctx())
        t.spare_key_available = True
        do(t, xf.DETC_SPARE_KEY)
        assert t.detc_unlocked_by == "SPARE"
        do(t, xf.DETC_LOCK)
        assert t.k2 == xf.KEY_IN_52T           # the spare does not release K2


class TestInternalFault:
    def test_tap_moved_energized_is_an_internal_arc(self):
        t = xf.Transformer(path="a", spare_key_available=True)
        do(t, xf.DETC_SPARE_KEY)
        assert do(t, xf.DETC_POS_DOWN) == "internal_fault"
        assert (t.flag_63, t.flag_87t, t.lockout_86t, t.damaged) == (True, True, True, True)
        assert (t.primary_closed, t.tap) == (False, xf.NOMINAL_TAP)
        assert "internal fault" in xf.interlock(t, xf.CLOSE_52T, ctx())

    def test_reset_order_targets_before_86t(self):
        t = xf.Transformer(path="a", flag_63=True, flag_87t=True, lockout_86t=True)
        assert "targets" in xf.interlock(t, xf.RESET_86T, ctx())
        do(t, xf.RESET_63)
        do(t, xf.RESET_87T)
        do(t, xf.RESET_86T)
        assert not t.lockout_86t

    def test_tap_moved_with_grid_lost_is_not_a_fault(self):
        t = xf.Transformer(path="a", spare_key_available=True)
        do(t, xf.DETC_SPARE_KEY)
        assert do(t, xf.DETC_POS_DOWN, ctx(grid=False)) is None
        assert (t.tap, t.damaged) == (2, False)


# ── Pure: voltage and thermal ───────────────────────────────────────
class TestVoltageAndThermal:
    def test_secondary_voltage_follows_the_tap(self):
        t = xf.Transformer(path="a")
        assert xf.secondary_kv(t, True) == pytest.approx(13.8)
        assert xf.secondary_kv(t, True, 28.1875) == pytest.approx(13.8 * 1.025)
        t.tap = 2
        assert xf.secondary_kv(t, True, 28.1875) == pytest.approx(13.8)
        t.tap = 1
        assert xf.secondary_kv(t, True) == pytest.approx(13.8 / 1.05)
        assert xf.secondary_kv(t, False) == 0.0

    def test_steady_state_matches_the_clause_7_form(self):
        t = xf.Transformer(path="a", fan_mode=xf.FANS_OFF)
        xf.settle(t, 15.0, True)        # rated ONAN load
        assert t.top_oil_c == pytest.approx(xf.AMBIENT_C + 55.0)
        assert t.winding_c == pytest.approx(xf.AMBIENT_C + 80.0)

    def test_auto_fans_pick_a_stage_and_cool(self):
        t = xf.Transformer(path="a")
        xf.settle(t, 11.0, True)
        assert xf.stage(t) == "ONAF1"
        off = xf.Transformer(path="a", fan_mode=xf.FANS_OFF)
        xf.settle(off, 11.0, True)
        assert off.winding_c > t.winding_c

    def test_deenergized_transformer_cools_to_ambient(self):
        t = xf.Transformer(path="a")
        xf.settle(t, 11.0, True)
        for _ in range(60):
            xf.tick(t, 60.0, 0.0, False)          # 60 thermal hours
        assert t.top_oil_c == pytest.approx(xf.AMBIENT_C, abs=0.1)

    def test_overload_with_fans_off_trips_86t(self):
        t = xf.Transformer(path="a", fan_mode=xf.FANS_OFF)
        xf.settle(t, 11.0, True)
        events = []
        for _ in range(40):
            events += xf.tick(t, 30.0, 24.0, True)
            if t.lockout_86t:
                break
        assert t.lockout_86t
        assert any(e["event"] == "xfmr_temperature_alarm" for e in events)
        assert "26" in t.trip_cause or "49" in t.trip_cause

    def test_describe_lists_actions_with_reasons(self):
        d = xf.describe(xf.Transformer(path="a"), ctx())
        acts = {a["action"]: a for a in d["actions"]}
        assert set(acts) == set(xf.ACTIONS)
        assert acts[xf.OPEN_52T]["permitted"]
        assert not acts[xf.DETC_UNLOCK]["permitted"]
        assert d["thermal_time_scale"] == xf.THERMAL_TIME_SCALE


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


def xsnap(ctl, path="a"):
    return ctl.snapshot(f"mvtc_{path}")["transformer"]


class TestController:
    def test_snapshot_carries_the_transformer(self, world):
        ctl, _ = world
        t = xsnap(ctl)
        assert (t["energized"], t["tap"]) == (True, 3)
        assert t["secondary_kv"] == pytest.approx(13.8)
        assert t["load_mva"] > 10                 # path on utility, 2N share

    def test_opening_52t_under_load_trips_52u_and_auto_starts(self, world):
        ctl, clock = world
        ctl.xfmr_action("mvtc_a", xf.OPEN_52T, "op")
        assert ctl.devices["mvtc_a"].state == dc.XFER_OPEN
        assert ctl.path_summary("a")["utility_ok"] is True
        assert ctl.path_summary("a")["incomer_live"] is False
        assert any(e["event"] == "protection_trip" and e.get("relay") == "27" for e in ctl._events)
        assert any(e["event"] == "auto_start" for e in ctl._events)

    def test_k1_out_blocks_every_52u_close(self, world):
        ctl, clock = world
        ctl.preset_on_generators("a", "op")
        ctl.xfmr_action("mvtc_a", xf.KEY_LOCK_52U, "op")
        ctl.set_authority("mvtc_a", dc.AUTH_REMOTE, "op")
        reason = ctl.blocked_reason(ctl.devices["mvtc_a"], "RETRANSFER_TO_UTILITY")
        assert "K1" in reason

    def test_k1_refused_while_52u_closed(self, world):
        ctl, _ = world
        with pytest.raises(dc.DeviceControlError, match="Open 52-U first"):
            ctl.xfmr_action("mvtc_a", xf.KEY_LOCK_52U, "op")

    def test_auto_recloses_52u_after_52t_back(self, world):
        ctl, clock = world
        ctl.xfmr_action("mvtc_a", xf.OPEN_52T, "op")
        clock.t += 1
        ctl.xfmr_action("mvtc_a", xf.CLOSE_52T, "op")
        clock.t += 1
        ctl.snapshot_all()
        assert ctl.devices["mvtc_a"].state == dc.XFER_UTILITY

    def test_internal_fault_with_spare_key(self, world):
        ctl, _ = world
        ctl.set_spare_key("a", True, "training")
        ctl.xfmr_action("mvtc_a", xf.DETC_SPARE_KEY, "op")
        ctl.xfmr_action("mvtc_a", xf.DETC_POS_DOWN, "op")
        kinds = [e["event"] for e in ctl._events]
        assert {"interlock_defeated", "xfmr_internal_fault"} <= set(kinds)
        assert ctl.devices["mvtc_a"].state == dc.XFER_OPEN
        assert ctl.snapshot("mvtc_a")["status"]["text"].startswith("52-U tripped by 86T")
        alarms = {c.alarm_id for c in ae.conditions_from_plant(ctl.snapshot_all()) if c.active}
        assert {"XFMR_A_86T", "XFMR_A_63", "XFMR_A_87T", "XFMR_A_INTERLOCK_DEFEATED"} <= alarms

    def test_grid_voltage_reading(self, world):
        ctl, _ = world
        ctl.set_grid_voltage("a", 28.19, "training")
        reads = {r["label"]: r["value"] for r in ctl.snapshot("mvtc_a")["readings"]}
        assert reads["Utility incomer voltage"] == pytest.approx(14.15, abs=0.01)
        with pytest.raises(dc.DeviceControlError):
            ctl.set_grid_voltage("a", 40.0, "training")

    def test_reset_restores_the_transformer(self, world):
        ctl, _ = world
        ctl.xfmr_action("mvtc_a", xf.OPEN_52T, "op")
        ctl.reset("op")
        assert xsnap(ctl)["primary_closed"] is True

    def test_non_transfer_device_refused(self, world):
        ctl, _ = world
        with pytest.raises(dc.DeviceControlError):
            ctl.xfmr_action("ups_a_01", xf.OPEN_52T, "op")
        with pytest.raises(dc.DeviceControlError):
            ctl.xfmr_action("mvtc_a", "TAP_TO_9", "op")


# ── DRILL-06 ────────────────────────────────────────────────────────
class TestDrill06:
    def _run(self, world, actions):
        ctl, clock = world
        tm = tr.TrainingManager(tr.load_drills(DRILLS), clock=clock)
        eng = ae.AlarmEngine()
        tm.start("DRILL-06", "op", ctl, eng)
        view = None
        for a in actions:
            clock.t += 5
            try:
                ctl.xfmr_action("mvtc_a", a, "op")
            except dc.DeviceControlError:
                ctl.refusal_event("mvtc_a", "op", "refused", command=f"{a}@XFMR")
            view = tm.evaluate(ctl, eng)
        return view["session"]

    def test_pass_following_the_chain(self, world):
        s = self._run(world, [*CHAIN, xf.DETC_POS_DOWN, xf.DETC_LOCK, xf.KEY_UNLOCK_52T,
                              xf.CLOSE_52T, xf.KEY_UNLOCK_52U])
        assert (s["outcome"], s["score"]) == ("PASS", 100)

    def test_fail_on_energized_tap_with_spare_key(self, world):
        s = self._run(world, [xf.DETC_SPARE_KEY, xf.DETC_POS_DOWN])
        assert s["outcome"] == "FAIL"
        assert "internal fault" in s["reason"]

    def test_spare_key_dead_is_a_violation_and_skips_the_chain(self, world):
        # Dead transformer, so no fault, but the spare key is unplanned
        # switching and the key-chain steps are never completed.
        s = self._run(world, [xf.KEY_LOCK_52U, xf.OPEN_52T, xf.DETC_SPARE_KEY, xf.DETC_POS_DOWN,
                              xf.DETC_LOCK, xf.CLOSE_52T, xf.KEY_UNLOCK_52U])
        assert s["outcome"] is None
        assert s["unplanned_switching"] == 1
        assert [st["id"] for st in s["steps"] if st["done"]] == ["LOCK_U", "DEENERGIZE"]


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
    def test_xfmr_route_ledger_and_refusal(self, client):
        c, ctl = client
        h = bearer("manager")
        url = "/api/devices/mvtc_a/xfmr"
        assert c.post(url, json={"action": "OPEN_52T"}, headers=bearer("operator")).status_code == 403
        r = c.post(url, json={"action": "KEY_LOCK_52U"}, headers=h)
        assert r.status_code == 409
        assert any(e["event"] == "refused" and e.get("command") == "KEY_LOCK_52U@XFMR"
                   for e in ctl._events)
        r = c.post(url, json={"action": "OPEN_52T"}, headers=h)
        assert r.status_code == 200
        body = r.json()
        entries = c.app.state.forensic_ledger.persistence._entries
        last = next(e for e in entries if e.entry_id == body["ledger_entry_id"])
        assert last.action == dc.ACTION_XFMR_FIELD
        assert last.payload["primary_closed"] is False
