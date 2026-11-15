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
        assert sorted(drills) == ["DRILL-01", "DRILL-02", "DRILL-03"]

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
        assert len(c.get("/api/training/drills").json()["drills"]) == 3
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
