"""T1 -- backend/training.py + backend/training_routes.py: drills on the
simulated plant, step detection, scoring rubric, report, ledger."""

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
)
from backend.auth.jwt_handler import issue_token, seed_demo_users  # noqa: E402
from backend.ledger import ForensicLedger  # noqa: E402
from backend.ledger.forensic_ledger import InMemoryPersistence  # noqa: E402
from backend.training_routes import register_training_routes, report_sha256  # noqa: E402

DESIGN = PROJECT_ROOT / "config" / "power_plant.yml"
DRILLS = PROJECT_ROOT / "config" / "training_drills"


class Clock:
    def __init__(self) -> None:
        self.t = 1_763_200_000.0

    def __call__(self) -> float:
        return self.t

    def tick(self, s: float) -> None:
        self.t += s


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def world(clock):
    ctl = dc.DeviceController.from_design(dc.load_design(DESIGN), clock=clock, wall_clock=clock)
    engine = ae.AlarmEngine(clock=clock)
    mgr = tr.TrainingManager(tr.load_drills(DRILLS), clock=clock)
    return ctl, engine, mgr


def run(ctl, device_id, command, actor="trainee"):
    sel = ctl.select(device_id, command, actor)
    return ctl.operate(device_id, sel["select_token"], actor)


def steps_done(view):
    return [s["id"] for s in view["session"]["steps"] if s["done"]]


class TestLibrary:
    def test_three_valid_drills(self):
        drills = tr.load_drills(DRILLS)
        assert sorted(drills) == ["DRILL-01", "DRILL-02", "DRILL-03", "DRILL-04", "DRILL-05"]

    def test_validator_rejects_unknown_check(self):
        with pytest.raises(ValueError, match="unknown check"):
            tr.validate_drill({"id": "X", "title": "t", "summary": "s", "path": "a",
                               "target_s": 1, "time_limit_s": 1,
                               "steps": [{"id": "A", "text": "t", "check": {"type": "magic"}}]})


class TestDrill01Blackout:
    def test_full_recovery_passes_with_score(self, world, clock):
        ctl, engine, mgr = world
        view = mgr.start("DRILL-01", "trainee", ctl, engine)
        assert view["active"] is True
        assert ctl.snapshot("mvtc_a")["state"] == dc.XFER_OPEN
        assert ctl.devices["mvtc_a"].authority == dc.AUTH_REMOTE
        assert steps_done(view) == []
        clock.tick(5)
        engine.ack_all("trainee")
        assert steps_done(mgr.evaluate(ctl, engine)) == ["ACK"]
        run(ctl, "mvtc_a", "START_GENERATORS")
        assert steps_done(mgr.evaluate(ctl, engine)) == ["ACK", "START"]
        clock.tick(dc.CRANK_TIME_S + 1)
        assert steps_done(mgr.evaluate(ctl, engine)) == ["ACK", "START", "SYNC"]
        run(ctl, "mvtc_a", "TRANSFER_TO_GENERATORS")
        clock.tick(1)
        view = mgr.evaluate(ctl, engine)
        assert view["active"] is False
        assert view["session"]["outcome"] == "PASS"
        # 15 s < 60 s target, no violations
        assert view["session"]["score"] == 100
        report = view["last_report"]
        assert [s["id"] for s in report["steps"]] == ["ACK", "START", "SYNC", "CLOSE"]
        assert report["steps"][-1]["t_ms"] == 15000
        events = {r.get("event") for r in report["soe"]}
        assert {"utility_lost", "protection_trip", "step_done", "ACK"} <= events

    def test_refused_command_and_late_finish_cost_points(self, world, clock):
        ctl, engine, mgr = world
        mgr.start("DRILL-01", "trainee", ctl, engine)
        with pytest.raises(dc.DeviceControlError):
            ctl.select("mvtc_a", "TRANSFER_TO_GENERATORS", "trainee")
        ctl.refusal_event("mvtc_a", "trainee", "not enough generation")
        engine.ack_all("trainee")
        mgr.evaluate(ctl, engine)
        run(ctl, "mvtc_a", "START_GENERATORS")
        clock.tick(80)
        mgr.evaluate(ctl, engine)
        run(ctl, "mvtc_a", "TRANSFER_TO_GENERATORS")
        view = mgr.evaluate(ctl, engine)
        # 80 s: 20 s late -> -2; one refusal -> -10
        assert view["session"]["score"] == 88
        assert view["session"]["violations"] == 1

    def test_battery_runs_out_fails_with_zero(self, world, clock):
        ctl, engine, mgr = world
        mgr.start("DRILL-01", "trainee", ctl, engine)
        for _ in range(26):
            clock.tick(60)
            view = mgr.evaluate(ctl, engine)
        assert view["session"]["outcome"] == "FAIL"
        assert "load lost" in view["session"]["reason"]
        assert view["session"]["score"] == 0

    def test_one_drill_at_a_time_and_abort(self, world):
        ctl, engine, mgr = world
        mgr.start("DRILL-01", "trainee", ctl, engine)
        with pytest.raises(tr.TrainingError) as exc:
            mgr.start("DRILL-03", "trainee", ctl, engine)
        assert exc.value.status == 409
        view = mgr.abort("instructor", ctl, engine)
        assert view["session"]["outcome"] == "ABORTED"
        assert mgr.last_report["outcome"] == "ABORTED"


class TestDrill02Retransfer:
    def test_retransfer_and_stop(self, world, clock):
        ctl, engine, mgr = world
        view = mgr.start("DRILL-02", "trainee", ctl, engine)
        assert ctl.snapshot("mvtc_a")["state"] == dc.XFER_GENERATORS
        assert ctl.path_summary("a")["utility_ok"] is True
        engine.ack_all("trainee")
        run(ctl, "mvtc_a", "RETRANSFER_TO_UTILITY")
        clock.tick(3)
        run(ctl, "mvtc_a", "STOP_GENERATORS")
        clock.tick(2)
        view = mgr.evaluate(ctl, engine)
        assert view["session"]["outcome"] == "PASS"
        assert steps_done(view) == ["ACK", "RETRANSFER", "STOP"]

    def test_stop_refused_while_on_generators(self, world):
        ctl, engine, mgr = world
        mgr.start("DRILL-02", "trainee", ctl, engine)
        with pytest.raises(dc.DeviceControlError, match="retransfer"):
            ctl.select("mvtc_a", "STOP_GENERATORS", "trainee")


class TestDrill03UpsFault:
    def test_bypass_then_isolate(self, world, clock):
        ctl, engine, mgr = world
        mgr.start("DRILL-03", "trainee", ctl, engine)
        assert ctl.snapshot("ups_a_03")["fault"] == "INVERTER_OVERTEMP"
        mgr.evaluate(ctl, engine)
        engine.ack_all("trainee")
        run(ctl, "ups_a_03", "TRANSFER_TO_BYPASS")
        clock.tick(10)
        run(ctl, "ups_a_03", "ISOLATE")
        view = mgr.evaluate(ctl, engine)
        assert view["session"]["outcome"] == "PASS"
        assert steps_done(view) == ["ACK", "BYPASS", "ISOLATE"]


class TestWindowEntry:
    @pytest.mark.parametrize(("angle", "slip", "eta"), [
        (5, 0.1, 0.0), (-150, 0.02, 140 / 7.2), (150, 0.25, 200 / 90),
        (150, -0.25, 140 / 90), (-30, -0.05, 320 / 18), (90, 0.0, None),
    ])
    def test_eta(self, angle, slip, eta):
        got = dc.window_entry_s(angle, slip)
        if eta is None:
            assert got is None
        else:
            assert got == pytest.approx(eta, abs=1e-6)


class TestReportSource:
    def test_dc_epms_074_event_source_kept_as_origin(self, world):
        ctl, engine, mgr = world
        mgr.start("DRILL-04", "trainee", ctl, engine)
        report = mgr.abort("x", ctl, engine)["last_report"]
        auth = [r for r in report["soe"] if r.get("event") == "authority"]
        assert auth
        assert {r["source"] for r in auth} == {"plant"}
        assert {r["origin"] for r in auth} == {"remote"}


class TestRubric:
    def test_score_floor_zero(self):
        s = tr.Session(drill={"target_s": 10}, operator="x", started_ms=0, events_mark=0,
                       outcome="PASS", ended_ms=10_000_000, violations=[{}] * 3)
        assert tr.score(s) == 0

    def test_rubric_declares_it_is_ours(self):
        assert tr.RUBRIC["not_an_industry_standard"] is True


# ── Routes ──────────────────────────────────────────────────────────
@pytest.fixture
def client(monkeypatch, world):
    monkeypatch.delenv("DC_EPMS_REQUIRE_AUTH", raising=False)
    ctl, engine, mgr = world
    app = FastAPI()
    app.state.forensic_ledger = ForensicLedger(InMemoryPersistence(), key=b"k" * 32)
    register_training_routes(app, lambda: ctl, engine, lambda: mgr)
    with TestClient(app) as c:
        yield c, ctl, engine, mgr


def bearer(name):
    user = seed_demo_users().find_by_username(name)
    return {"Authorization": f"Bearer {issue_token(user)}"}


class TestRoutes:
    def test_flow_and_ledger(self, client, clock):
        c, ctl, engine, _ = client
        assert len(c.get("/api/training/drills").json()["drills"]) == 5
        assert c.post("/api/training/start", json={"drill_id": "DRILL-03"}).status_code == 403
        r = c.post("/api/training/start", json={"drill_id": "DRILL-03"}, headers=bearer("manager"))
        assert r.status_code == 200
        assert c.get("/api/training/report").status_code == 404
        engine.ack_all("manager")
        run(ctl, "ups_a_03", "TRANSFER_TO_BYPASS", "manager")
        run(ctl, "ups_a_03", "ISOLATE", "manager")
        view = c.get("/api/training/session").json()
        assert view["session"]["outcome"] == "PASS"
        assert view["session"]["ledger_entry_id"]
        report = c.get("/api/training/report").json()
        assert report["outcome"] == "PASS"
        assert report["ledger_entry_id"] == view["session"]["ledger_entry_id"]
        assert len(report_sha256(report)) == 64
        # T4: the report carries the digest the ledger recorded, and the
        # digest is reproducible from the report minus the two late keys.
        integ = report["integrity"]
        body = {k: v for k, v in report.items() if k not in ("ledger_entry_id", "integrity")}
        assert integ["report_sha256"] == report_sha256(body)
        assert integ["ledger_entry_id"] == report["ledger_entry_id"]
        ledger = c.app.state.forensic_ledger
        entries = ledger.persistence._entries
        result = next(e for e in entries if e.entry_id == integ["ledger_entry_id"])
        assert result.payload["report_sha256"] == integ["report_sha256"]

    def test_operator_cannot_reset_the_plant(self, client):
        c, *_ = client
        assert c.post("/api/training/reset", headers=bearer("operator")).status_code == 403
        assert c.post("/api/training/reset", headers=bearer("manager")).status_code == 200

    def test_unknown_drill_404(self, client):
        c, *_ = client
        r = c.post("/api/training/start", json={"drill_id": "NOPE"}, headers=bearer("manager"))
        assert r.status_code == 404

    def test_reset_refused_during_drill(self, client):
        c, *_ = client
        c.post("/api/training/start", json={"drill_id": "DRILL-01"}, headers=bearer("manager"))
        assert c.post("/api/training/reset", headers=bearer("manager")).status_code == 409
        assert c.post("/api/training/abort", headers=bearer("manager")).json()["session"]["outcome"] == "ABORTED"


class TestDrill04ClosedTransition:
    def _gov(self, ctl, delta, n=1):
        for _ in range(n):
            ctl.adjust_governor("mvtc_a", delta, "trainee")

    def test_trim_sync_close_stop_passes(self, world, clock):
        ctl, engine, mgr = world
        mgr.start("DRILL-04", "trainee", ctl, engine)
        sync = ctl.snapshot("mvtc_a")["synchro"]
        assert (sync["enabled"], sync["live"], sync["slip_hz"], sync["angle_deg"]) == (True, True, 0.25, 150.0)
        engine.ack_all("trainee")
        self._gov(ctl, -0.05, 4)                     # 60.25 -> 60.05 Hz
        view = mgr.evaluate(ctl, engine)
        assert [s["id"] for s in view["session"]["steps"] if s["done"]] == ["ACK", "TRIM"]
        # 0.05 Hz slip = 18 deg/s: wait until the needle reaches the window
        angle = ctl.snapshot("mvtc_a")["synchro"]["angle_deg"]
        clock.tick(((360 - angle) % 360) / 18.0)
        assert abs(ctl.snapshot("mvtc_a")["synchro"]["angle_deg"]) <= 10
        out = run(ctl, "mvtc_a", "CLOSED_TRANSITION_RETRANSFER")
        assert out["closed_transition"] is True
        assert ctl.snapshot("mvtc_a")["state"] == dc.XFER_UTILITY
        assert ctl.path_summary("a")["load_lost"] is False
        run(ctl, "mvtc_a", "STOP_GENERATORS")
        view = mgr.evaluate(ctl, engine)
        assert view["session"]["outcome"] == "PASS"

    def test_out_of_phase_execute_arms_and_closes_at_window_entry(self, world, clock):
        ctl, engine, mgr = world
        mgr.start("DRILL-04", "trainee", ctl, engine)
        self._gov(ctl, -0.05, 4)                     # 60.05 Hz: 18 deg/s
        a0 = ctl.synchro("a")["angle_deg"]
        eta = dc.window_entry_s(a0, 0.05)
        out = run(ctl, "mvtc_a", "CLOSED_TRANSITION_RETRANSFER")
        assert out["sync_close_armed"] is True
        assert ctl.snapshot("mvtc_a")["synchro"]["close_armed"] is True
        clock.tick(eta - 0.5)
        assert ctl.snapshot("mvtc_a")["state"] == dc.XFER_GENERATORS
        clock.tick(0.9)                              # crosses the window edge
        assert ctl.snapshot("mvtc_a")["state"] == dc.XFER_UTILITY
        close = [e for e in ctl._events if e.get("closed_transition")][-1]
        assert close["supervised"] is True
        assert abs(close["angle_deg"]) == pytest.approx(10.0, abs=0.01)
        # stamped at the computed instant, not at the poll
        assert close["ts"] == pytest.approx(clock.t - 0.4, abs=0.01)
        assert not [e for e in ctl._events if e["event"] == "refused"]

    def test_slip_too_high_waits_then_times_out(self, world, clock):
        ctl, engine, mgr = world
        mgr.start("DRILL-04", "trainee", ctl, engine)
        run(ctl, "mvtc_a", "CLOSED_TRANSITION_RETRANSFER")    # 0.25 Hz slip
        clock.tick(dc.SYNC_CLOSE_TIMEOUT_S + 1)
        snap = ctl.snapshot("mvtc_a")
        assert snap["state"] == dc.XFER_GENERATORS
        assert snap["synchro"]["close_armed"] is False
        cancel = [e for e in ctl._events if e["event"] == "sync_close_cancelled"][-1]
        assert "no synchronism" in cancel["detail"]

    def test_trim_while_armed_then_closes(self, world, clock):
        ctl, engine, mgr = world
        mgr.start("DRILL-04", "trainee", ctl, engine)
        run(ctl, "mvtc_a", "CLOSED_TRANSITION_RETRANSFER")
        self._gov(ctl, -0.05, 4)
        clock.tick(dc.window_entry_s(ctl.synchro("a")["angle_deg"], 0.05) + 0.2)
        assert ctl.snapshot("mvtc_a")["state"] == dc.XFER_UTILITY

    def test_cancel_and_authority_change(self, world, clock):
        ctl, engine, mgr = world
        mgr.start("DRILL-04", "trainee", ctl, engine)
        run(ctl, "mvtc_a", "CLOSED_TRANSITION_RETRANSFER")
        with pytest.raises(dc.DeviceControlError, match="already armed"):
            ctl.select("mvtc_a", "CLOSED_TRANSITION_RETRANSFER", "trainee")
        ctl.cancel_sync_close("mvtc_a", "trainee")
        assert ctl.synchro("a")["close_armed"] is False
        with pytest.raises(dc.DeviceControlError):
            ctl.cancel_sync_close("mvtc_a", "trainee")
        run(ctl, "mvtc_a", "CLOSED_TRANSITION_RETRANSFER")
        ctl.set_authority("mvtc_a", dc.AUTH_AUTO, "x")
        assert ctl.synchro("a")["close_armed"] is False

    def test_window_eta_in_snapshot(self, world):
        ctl, engine, mgr = world
        mgr.start("DRILL-04", "trainee", ctl, engine)
        sync = ctl.snapshot("mvtc_a")["synchro"]
        # 150 deg, +0.25 Hz (90 deg/s): next window edge at 350 deg -> 2.22 s
        assert sync["window_eta_s"] == pytest.approx(200 / 90, abs=0.05)

    def test_open_transition_fails_the_drill(self, world):
        ctl, engine, mgr = world
        mgr.start("DRILL-04", "trainee", ctl, engine)
        run(ctl, "mvtc_a", "RETRANSFER_TO_UTILITY")
        view = mgr.evaluate(ctl, engine)
        assert view["session"]["outcome"] == "FAIL"
        assert "open-transition" in view["session"]["reason"]


class TestClosedTransitionOffByDefault:
    def test_command_refused_outside_training(self, world):
        ctl, _, _ = world
        ctl.set_authority("mvtc_a", dc.AUTH_REMOTE, "op")
        cmd = next(c for c in ctl.snapshot("mvtc_a")["commands"]
                   if c["command"] == "CLOSED_TRANSITION_RETRANSFER")
        assert cmd["permitted"] is False
        assert "open transition" in cmd["blocked_reason"]
        assert ctl.snapshot("mvtc_a")["synchro"]["enabled"] is False

    def test_governor_bounds(self, world):
        ctl, engine, mgr = world
        mgr.start("DRILL-04", "trainee", ctl, engine)
        with pytest.raises(dc.DeviceControlError, match="within"):
            ctl.adjust_governor("mvtc_a", 0.2, "trainee")
        with pytest.raises(dc.DeviceControlError, match="number"):
            ctl.adjust_governor("mvtc_a", "fast", "trainee")
        for _ in range(20):
            ctl.adjust_governor("mvtc_a", 0.05, "trainee")
        assert ctl.synchro("a")["gen_hz"] == dc.GOVERNOR_MAX_HZ
        ctl.set_authority("mvtc_a", dc.AUTH_AUTO, "x")
        with pytest.raises(dc.DeviceControlError, match="REMOTE"):
            ctl.adjust_governor("mvtc_a", -0.05, "trainee")

    def test_reset_turns_the_mode_off(self, world):
        ctl, engine, mgr = world
        mgr.start("DRILL-04", "trainee", ctl, engine)
        mgr.abort("x", ctl, engine)
        ctl.reset("x")
        assert ctl.closed_transition is False
        assert ctl.synchro("a")["gen_hz"] == dc.UTILITY_HZ

    def test_governor_route(self, monkeypatch, world):
        monkeypatch.delenv("DC_EPMS_REQUIRE_AUTH", raising=False)
        ctl, engine, mgr = world
        app = FastAPI()
        dc.register_device_control_routes(app, lambda: ctl)
        mgr.start("DRILL-04", "manager", ctl, engine)
        with TestClient(app) as c:
            assert c.post("/api/devices/mvtc_a/governor", json={"delta_hz": -0.05}).status_code == 403
            r = c.post("/api/devices/mvtc_a/governor", json={"delta_hz": -0.05}, headers=bearer("manager"))
            assert r.status_code == 200
            assert r.json()["synchro"]["gen_hz"] == 60.2
            r = c.post("/api/devices/mvtc_a/governor", json={"delta_hz": 1}, headers=bearer("manager"))
            assert r.status_code == 400


# ── Rubric v2: unplanned switching + reverted steps ─────────────────
class TestRubricV2:
    def _close_in_window(self, ctl, clock, mgr, engine):
        while ctl.synchro("a")["slip_hz"] > 0.06:
            ctl.adjust_governor("mvtc_a", -0.05, "trainee")
        mgr.evaluate(ctl, engine)                                # the UI poll sees TRIM
        run(ctl, "mvtc_a", "CLOSED_TRANSITION_RETRANSFER")       # arms
        clock.tick(dc.window_entry_s(ctl.synchro("a")["angle_deg"], ctl.synchro("a")["slip_hz"]) + 0.2)
        assert ctl.snapshot("mvtc_a")["state"] == dc.XFER_UTILITY

    def test_every_drill_declares_its_procedure(self):
        for drill in tr.load_drills(DRILLS).values():
            assert drill["procedure_commands"], drill["id"]

    def test_operator_report_replay_counts_the_extra_transfer(self, world, clock):
        """The operator's DRILL-04 run of 2026-11-15: close, back to
        generators, close again, stop. v1 scored 77; v2 adds one
        unplanned switching violation and records the CLOSE revert."""
        ctl, engine, mgr = world
        mgr.start("DRILL-04", "trainee", ctl, engine)
        engine.ack_all("trainee")
        self._close_in_window(ctl, clock, mgr, engine)
        view = mgr.evaluate(ctl, engine)
        assert steps_done(view) == ["ACK", "TRIM", "CLOSE"]
        clock.tick(5)
        run(ctl, "mvtc_a", "TRANSFER_TO_GENERATORS")
        view = mgr.evaluate(ctl, engine)
        close = next(s for s in view["session"]["steps"] if s["id"] == "CLOSE")
        assert close["reverted"] is True
        assert view["session"]["unplanned_switching"] == 1
        clock.tick(5)
        engine.ack_all("trainee")
        ctl.set_sync("a", 60.05, -40, "test")
        self._close_in_window(ctl, clock, mgr, engine)
        mgr.evaluate(ctl, engine)
        run(ctl, "mvtc_a", "STOP_GENERATORS")
        view = mgr.evaluate(ctl, engine)
        s = view["session"]
        assert s["outcome"] == "PASS"
        assert s["violations"] == 1
        assert next(x for x in s["steps"] if x["id"] == "CLOSE")["reverted"] is False
        report = mgr.last_report
        assert report["rubric"]["name"].endswith("v2")
        v = report["violations"][0]
        assert (v["violation"], v["command"]) == ("unplanned_switching", "TRANSFER_TO_GENERATORS")
        assert [r["event"] for r in report["step_reverts"]] == ["reverted", "restored"]
        soe = [r["event"] for r in report["soe"] if r["source"] == "training"]
        assert "step_reverted" in soe
        assert "step_restored" in soe
        elapsed = report["duration_ms"] / 1000
        late = max(0, elapsed - 90)
        assert report["score"] == max(0, 100 - 10 - -(-late // 10))

    def test_clean_run_has_no_violation(self, world, clock):
        ctl, engine, mgr = world
        mgr.start("DRILL-04", "trainee", ctl, engine)
        engine.ack_all("trainee")
        self._close_in_window(ctl, clock, mgr, engine)
        run(ctl, "mvtc_a", "STOP_GENERATORS")
        view = mgr.evaluate(ctl, engine)
        assert (view["session"]["outcome"], view["session"]["violations"]) == ("PASS", 0)
        assert mgr.last_report["step_reverts"] == []

    def test_automatic_commands_are_not_unplanned(self):
        drill = {"procedure_commands": ["STOP"]}
        events = [
            {"event": "command", "command": "TRANSFER_TO_GENERATORS", "actor": "controller"},
            {"event": "command", "command": "START_GENERATORS", "actor": "training"},
            {"event": "command", "command": "STOP", "actor": "op"},
            {"event": "command", "command": "ISOLATE", "actor": "op"},
        ]
        got = tr.unplanned_switching(drill, events)
        assert [e["command"] for e in got] == ["ISOLATE"]
        assert tr.unplanned_switching({}, events) == []

    def test_drill_validation_rejects_bad_procedure_and_holds(self):
        base = {"id": "X", "title": "t", "summary": "s", "path": "a", "target_s": 1, "time_limit_s": 2,
                "steps": [{"id": "A", "text": "a", "check": {"type": "event_seen"}}]}
        with pytest.raises(ValueError, match="procedure_commands"):
            tr.validate_drill({**base, "procedure_commands": []})
        bad = {**base, "steps": [{"id": "A", "text": "a", "check": {"type": "event_seen"},
                                  "holds": {"type": "nope"}}]}
        with pytest.raises(ValueError, match="holds"):
            tr.validate_drill(bad)


# ── L1: DRILL-05 (52-GM rack out and lockout) ──────────────────────
class TestDrill05RackOut:
    def fa(self, ctl, brk, action, actor="trainee"):
        return ctl.field_action("mvtc_a", brk, action, actor)

    def test_full_isolation_passes_clean_in_osha_order(self, world, clock):
        ctl, engine, mgr = world
        mgr.start("DRILL-05", "trainee", ctl, engine)
        ctl.set_authority("mvtc_a", dc.AUTH_LOCAL, "trainee")
        self.fa(ctl, "52-GM", "RACK_OUT")
        mgr.evaluate(ctl, engine)
        self.fa(ctl, "52-GM", "RACK_OUT")
        mgr.evaluate(ctl, engine)
        self.fa(ctl, "52-GM", "PADLOCK")
        mgr.evaluate(ctl, engine)
        self.fa(ctl, "52-GM", "LOCAL_CLOSE")                # mechanical, no control power
        self.fa(ctl, "52-GM", "LOCAL_OPEN")
        clock.tick(30)                                      # the motor cannot recharge
        view = mgr.evaluate(ctl, engine)
        s = view["session"]
        assert (s["outcome"], s["violations"]) == ("PASS", 0)
        assert steps_done(view) == ["LOCAL", "TEST", "DISCONNECT", "LOCK", "DISCHARGE"]
        refs = " ".join(mgr.last_report["drill"]["references"])
        assert "1910.147(d)(5)(i)" in refs
        assert "verified" in refs

    def test_discharge_before_the_lock_does_not_count(self, world, clock):
        """The old order (release in TEST, then lock) leaves the drill
        waiting: the release must follow the lockout device."""
        ctl, engine, mgr = world
        mgr.start("DRILL-05", "trainee", ctl, engine)
        ctl.set_authority("mvtc_a", dc.AUTH_LOCAL, "trainee")
        self.fa(ctl, "52-GM", "RACK_OUT")
        mgr.evaluate(ctl, engine)
        self.fa(ctl, "52-GM", "MOTOR_OFF")
        self.fa(ctl, "52-GM", "LOCAL_CLOSE")
        self.fa(ctl, "52-GM", "LOCAL_OPEN")
        self.fa(ctl, "52-GM", "RACK_OUT")
        mgr.evaluate(ctl, engine)
        self.fa(ctl, "52-GM", "PADLOCK")
        view = mgr.evaluate(ctl, engine)
        assert view["session"]["outcome"] is None
        assert steps_done(view) == ["LOCAL", "TEST", "DISCONNECT", "LOCK"]

    def test_racking_a_closed_breaker_is_refused_and_counted(self, client):
        c, ctl, engine, mgr = client
        dc.register_device_control_routes(c.app, lambda: ctl)
        h = bearer("manager")
        c.post("/api/training/start", json={"drill_id": "DRILL-05"}, headers=h)
        c.post("/api/devices/mvtc_a/authority", json={"authority": "LOCAL"}, headers=h)
        r = c.post("/api/devices/mvtc_a/field", json={"breaker": "52-U", "action": "RACK_OUT"}, headers=h)
        assert r.status_code == 409
        view = c.get("/api/training/session").json()
        assert view["session"]["violations"] == 1

    def test_opening_the_incomer_fails_the_drill(self, world):
        ctl, engine, mgr = world
        mgr.start("DRILL-05", "trainee", ctl, engine)
        ctl.set_authority("mvtc_a", dc.AUTH_LOCAL, "trainee")
        self.fa(ctl, "52-U", "LOCAL_OPEN")
        view = mgr.evaluate(ctl, engine)
        assert view["session"]["outcome"] == "FAIL"
        assert "wrong breaker" in view["session"]["reason"]
