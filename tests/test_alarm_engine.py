"""HMI H4 -- backend/alarm_engine.py + backend/alarm_routes.py.

ISA-18.2 style states (NORM / UNACK / ACKED / RTNUN), conditions from
the simulated Power Controls plant, ms timestamps, ACK via session
token chained in the Forensic Ledger.
"""

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
)
from backend.alarm_routes import register_alarm_routes  # noqa: E402
from backend.auth.jwt_handler import issue_token, seed_demo_users  # noqa: E402
from backend.ledger import ForensicLedger  # noqa: E402
from backend.ledger.forensic_ledger import InMemoryPersistence  # noqa: E402

DESIGN_PATH = PROJECT_ROOT / "config" / "power_plant.yml"


class FakeClock:
    def __init__(self) -> None:
        self.t = 1_763_150_000.0

    def __call__(self) -> float:
        return self.t

    def tick(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def engine(clock) -> ae.AlarmEngine:
    return ae.AlarmEngine(clock=clock)


@pytest.fixture
def ctl(clock) -> dc.DeviceController:
    return dc.DeviceController.from_design(dc.load_design(DESIGN_PATH), clock=clock, wall_clock=clock)


def cond(active: bool, alarm_id: str = "X", priority: str = ae.HIGH) -> ae.Condition:
    return ae.Condition(alarm_id, active, priority, "test alarm", "src")


def run(ctl, device_id: str, command: str) -> None:
    if ctl.devices[device_id].authority != dc.AUTH_REMOTE:
        ctl.set_authority(device_id, dc.AUTH_REMOTE, "manager")
    sel = ctl.select(device_id, command, "manager")
    ctl.operate(device_id, sel["select_token"], "manager")


def ids(snapshot: dict) -> dict[str, str]:
    return {a["id"]: a["state"] for a in snapshot["alarms"]}


class TestStateMachine:
    def test_active_ack_clear(self, engine, clock):
        engine.evaluate([cond(True)])
        assert engine.alarms["X"].state == ae.UNACK
        clock.tick(1.234)
        engine.ack("X", "op")
        assert engine.alarms["X"].state == ae.ACKED
        engine.evaluate([cond(False)])
        assert engine.alarms["X"].state == ae.NORM
        assert engine.snapshot()["alarms"] == []

    def test_clear_before_ack_is_rtn_unack_then_ack_to_norm(self, engine):
        engine.evaluate([cond(True)])
        engine.evaluate([cond(False)])
        assert engine.alarms["X"].state == ae.RTNUN
        assert engine.snapshot()["unacked"] == 1
        engine.ack("X", "op")
        assert engine.alarms["X"].state == ae.NORM

    def test_reactivation_from_rtnun_and_occurrence_count(self, engine):
        engine.evaluate([cond(True)])
        engine.evaluate([cond(False)])
        engine.evaluate([cond(True)])
        a = engine.alarms["X"]
        assert (a.state, a.occurrences) == (ae.UNACK, 2)

    def test_absent_condition_counts_as_inactive(self, engine):
        engine.evaluate([cond(True)])
        engine.evaluate([])
        assert engine.alarms["X"].state == ae.RTNUN

    def test_ack_refusals(self, engine):
        with pytest.raises(ae.AlarmError) as exc:
            engine.ack("nope", "op")
        assert exc.value.status == 404
        engine.evaluate([cond(True)])
        engine.ack("X", "op")
        with pytest.raises(ae.AlarmError) as exc:
            engine.ack("X", "op")
        assert exc.value.status == 409

    def test_millisecond_timestamps(self, engine, clock):
        engine.evaluate([cond(True)])
        clock.tick(0.25)
        alarm = engine.ack("X", "op")
        assert alarm["activated"].endswith(".000+00:00")
        assert alarm["acked"].endswith(".250+00:00")
        assert alarm["acked_by"] == "op"
        assert [j["event"] for j in engine.snapshot()["journal"]] == ["ACK", "ACTIVE"]

    def test_sort_priority_then_unacked_first(self, engine, clock):
        engine.evaluate([cond(True, "L", ae.LOW), cond(True, "H1"), cond(True, "H2")])
        engine.ack("H1", "op")
        order = [a["id"] for a in engine.snapshot()["alarms"]]
        assert order == ["H2", "H1", "L"]

    def test_unknown_priority_rejected(self, engine):
        with pytest.raises(ValueError, match="unknown priority"):
            engine.evaluate([cond(True, priority="URGENT")])

    def test_ack_all(self, engine):
        engine.evaluate([cond(True, "A"), cond(True, "B")])
        engine.evaluate([cond(True, "A")])
        assert {a["id"] for a in engine.ack_all("op")} == {"A", "B"}
        assert engine.snapshot()["unacked"] == 0


class TestPlantConditions:
    def test_healthy_plant_raises_nothing(self, engine, ctl):
        engine.evaluate(ae.conditions_from_plant(ctl.snapshot_all()))
        assert engine.snapshot()["alarms"] == []

    def test_ups_bypass_then_isolation(self, engine, ctl):
        run(ctl, "ups_a_01", "TRANSFER_TO_BYPASS")
        engine.evaluate(ae.conditions_from_plant(ctl.snapshot_all()))
        assert ids(engine.snapshot()) == {"PATH_A_UNPROTECTED": ae.UNACK}
        run(ctl, "ups_a_01", "ISOLATE")
        engine.evaluate(ae.conditions_from_plant(ctl.snapshot_all()))
        assert ids(engine.snapshot()) == {
            "PATH_A_UNPROTECTED": ae.RTNUN, "PATH_A_UPS_N1_LOST": ae.UNACK,
        }

    def test_priorities_are_from_the_known_set(self, ctl):
        for c in ae.conditions_from_plant(ctl.snapshot_all()):
            assert c.priority in ae.PRIORITIES
            assert c.alarm_id.isascii()

    def test_path_on_generators_maps_from_source(self):
        plant = {"paths": [{"path": "b", "source": "GENERATORS"}], "devices": []}
        active = {c.alarm_id for c in ae.conditions_from_plant(plant) if c.active}
        assert active == {"PATH_B_ON_GENERATORS"}


# ── Routes ──────────────────────────────────────────────────────────
@pytest.fixture
def client(monkeypatch, ctl, engine):
    monkeypatch.delenv("DC_EPMS_REQUIRE_AUTH", raising=False)
    app = FastAPI()
    app.state.forensic_ledger = ForensicLedger(InMemoryPersistence(), key=b"k" * 32)
    register_alarm_routes(app, lambda: ctl, engine)
    with TestClient(app) as c:
        yield c, app


def _bearer(username: str) -> dict[str, str]:
    user = seed_demo_users().find_by_username(username)
    return {"Authorization": f"Bearer {issue_token(user)}"}


class TestRoutes:
    def test_list_and_ack_with_session_token(self, client, ctl):
        c, _ = client
        r = c.get("/api/alarms")
        assert r.status_code == 200
        assert r.json()["alarms"] == []
        assert r.json()["quality"] == "simulated"
        run(ctl, "ups_a_01", "TRANSFER_TO_BYPASS")
        body = c.get("/api/alarms").json()
        assert body["unacked"] == 1
        r = c.post("/api/alarms/PATH_A_UNPROTECTED/ack", headers=_bearer("manager"))
        assert r.status_code == 200
        assert r.json()["alarm"]["state"] == ae.ACKED
        assert r.json()["alarm"]["acked_by"] == "manager"
        assert r.json()["ledger_entry_id"]
        assert c.post("/api/alarms/PATH_A_UNPROTECTED/ack",
                      headers=_bearer("manager")).status_code == 409

    def test_console_operator_may_acknowledge(self, client, ctl):
        c, _ = client
        run(ctl, "ups_a_01", "TRANSFER_TO_BYPASS")
        c.get("/api/alarms")
        r = c.post("/api/alarms/PATH_A_UNPROTECTED/ack", headers=_bearer("operator"))
        assert r.status_code == 200
        assert r.json()["alarm"]["acked_by"] == "operator"

    def test_ack_needs_a_person(self, client, ctl, monkeypatch):
        c, _ = client
        run(ctl, "ups_a_01", "TRANSFER_TO_BYPASS")
        c.get("/api/alarms")
        assert c.post("/api/alarms/PATH_A_UNPROTECTED/ack", json={}).status_code == 403
        monkeypatch.setenv("DC_EPMS_REQUIRE_AUTH", "1")
        assert c.post("/api/alarms/PATH_A_UNPROTECTED/ack").status_code == 401

    def test_ack_all_route(self, client, ctl):
        c, _ = client
        run(ctl, "ups_a_01", "TRANSFER_TO_BYPASS")
        c.get("/api/alarms")
        r = c.post("/api/alarms/ack-all", headers=_bearer("manager"))
        assert [a["id"] for a in r.json()["acked"]] == ["PATH_A_UNPROTECTED"]

    def test_unavailable_without_design(self, engine):
        app = FastAPI()
        register_alarm_routes(app, lambda: None, engine)
        with TestClient(app) as c:
            assert c.get("/api/alarms").status_code == 503
