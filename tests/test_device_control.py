"""
tests/test_device_control.py
============================
Release R3-A -- backend/device_control.py.

  * Roster comes from the site model (ups / ats / genset only).
  * Authority: remote commands refused in AUTO and LOCAL.
  * Select-before-operate: single use, expiry, same actor, interlocks
    evaluated again at operate time.
  * Interlocks: no transfer to a dead emergency source, no stopping
    the only set carrying load, maintenance bypass only from static
    bypass.
  * Generator sequence is time-driven and deterministic.
  * Routes: role comes from the session token, body role ignored when
    a token is present; every action lands in the Forensic Ledger.
  * ADR-006: the agent stack never imports the module.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
# Same import path as tests/test_smoke.py (DC-EPMS-008 class).
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from site_model import SiteModel  # noqa: E402

from backend import device_control as dc  # noqa: E402
from backend.auth.jwt_handler import issue_token, seed_demo_users  # noqa: E402
from backend.ledger import ForensicLedger  # noqa: E402
from backend.ledger.forensic_ledger import InMemoryPersistence  # noqa: E402


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def tick(self, seconds: float) -> None:
        self.t += seconds


COMPONENTS = {
    "ups_a": {"type": "ups", "display": "UPS A", "rated_kw": 2500, "runtime_full_load_min": 7},
    "ats_a": {"type": "ats", "display": "ATS-A", "rated_amps": 4000, "voltage_v": 480},
    "genset_a_01": {"type": "genset", "display": "Genset A1", "rated_kw": 2750},
    "genset_a_02": {"type": "genset", "display": "Genset A2", "rated_kw": 2750},
    "ats_b": {"type": "ats", "display": "ATS-B", "rated_amps": 4000},
    "genset_b_01": {"type": "genset", "display": "Genset B1", "rated_kw": 2750},
    "rack_01": {"type": "it_rack", "display": "Rack 1"},
    "dc_bus_d": {"type": "dc_bus", "display": "800 VDC bus"},
}


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def ctl(clock: FakeClock) -> dc.DeviceController:
    return dc.DeviceController.from_components(COMPONENTS, clock=clock, wall_clock=clock)


def run(ctl: dc.DeviceController, device_id: str, command: str, actor: str = "manager"):
    sel = ctl.select(device_id, command, actor)
    return ctl.operate(device_id, sel["select_token"], actor)


def remote(ctl: dc.DeviceController, *ids: str) -> None:
    for device_id in ids:
        ctl.set_authority(device_id, dc.AUTH_REMOTE, "manager")


def start_and_settle(ctl, clock, device_id: str) -> None:
    remote(ctl, device_id)
    run(ctl, device_id, "START")
    clock.tick(dc.CRANK_TIME_S + 0.1)


class TestRoster:
    def test_only_ups_transfer_and_generators_are_controllable(self, ctl):
        assert set(ctl.devices) == {
            "ups_a", "ats_a", "genset_a_01", "genset_a_02", "ats_b", "genset_b_01",
        }

    def test_real_site_model_yields_every_kind(self):
        sm = SiteModel(yaml_path=PROJECT_ROOT / "config" / "site_model.yml")
        sm.load()
        real = dc.DeviceController.from_components(sm._raw["components"])
        kinds = {d.kind for d in real.devices.values()}
        assert kinds == set(dc.KINDS)
        assert all(d.path in ("a", "b") for d in real.devices.values())

    def test_path_is_derived_from_the_id(self):
        assert dc.path_of("ups_a") == "a"
        assert dc.path_of("genset_b_01") == "b"
        assert dc.path_of("chiller") == "-"

    def test_initial_states_and_authority(self, ctl):
        assert ctl.devices["ups_a"].state == dc.UPS_DOUBLE_CONVERSION
        assert ctl.devices["ats_a"].state == dc.XFER_NORMAL
        assert ctl.devices["genset_a_01"].state == dc.GEN_STANDBY
        assert all(d.authority == dc.AUTH_AUTO for d in ctl.devices.values())

    def test_snapshot_is_labelled_simulated(self, ctl):
        snap = ctl.snapshot_all()
        assert snap["quality"] == "simulated"
        assert "No field equipment is connected" in snap["notice"]
        assert all(d["quality"] == "simulated" for d in snap["devices"])
        assert next(d["kind"] for d in snap["devices"]) == dc.KIND_UPS


class TestAuthority:
    def test_auto_refuses_remote_commands(self, ctl):
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.select("genset_a_01", "START", "manager")
        assert exc.value.status == 409
        assert "AUTO" in exc.value.detail

    def test_local_refuses_remote_commands(self, ctl):
        ctl.set_authority("genset_a_01", dc.AUTH_LOCAL, "manager")
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.select("genset_a_01", "START", "manager")
        assert "LOCAL" in exc.value.detail

    def test_local_change_is_recorded_as_bench_simulation(self, ctl):
        event = ctl.set_authority("ups_a", dc.AUTH_LOCAL, "manager")
        assert event["source"] == "bench_simulation"
        event = ctl.set_authority("ups_a", dc.AUTH_REMOTE, "manager")
        assert event["source"] == "bench_simulation"
        event = ctl.set_authority("ups_a", dc.AUTH_AUTO, "manager")
        assert event["source"] == "remote"

    def test_invalid_and_repeated_authority(self, ctl):
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.set_authority("ups_a", "GOD", "manager")
        assert exc.value.status == 400
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.set_authority("ups_a", dc.AUTH_AUTO, "manager")
        assert exc.value.status == 409

    def test_authority_change_drops_a_pending_selection(self, ctl):
        remote(ctl, "genset_a_01")
        sel = ctl.select("genset_a_01", "START", "manager")
        ctl.set_authority("genset_a_01", dc.AUTH_AUTO, "manager")
        ctl.set_authority("genset_a_01", dc.AUTH_REMOTE, "manager")
        with pytest.raises(dc.DeviceControlError):
            ctl.operate("genset_a_01", sel["select_token"], "manager")
        assert ctl.devices["genset_a_01"].state == dc.GEN_STANDBY

    def test_snapshot_commands_carry_the_authority_reason(self, ctl):
        snap = ctl.snapshot("genset_a_01")
        start = next(c for c in snap["commands"] if c["command"] == "START")
        assert start["permitted"] is False
        assert "AUTO" in start["blocked_reason"]


    def test_authority_reason_takes_priority_over_interlocks(self, ctl):
        snap = ctl.snapshot("ups_a")
        reasons = {c["blocked_reason"] for c in snap["commands"]}
        assert len(reasons) == 1
        assert "AUTO" in next(iter(reasons))


class TestSelectBeforeOperate:
    def test_select_changes_nothing(self, ctl):
        remote(ctl, "genset_a_01")
        sel = ctl.select("genset_a_01", "START", "manager")
        assert sel["expires_in_s"] == dc.SELECT_TTL_S
        assert ctl.devices["genset_a_01"].state == dc.GEN_STANDBY

    def test_token_is_single_use(self, ctl):
        remote(ctl, "ups_a")
        sel = ctl.select("ups_a", "TRANSFER_TO_BYPASS", "manager")
        ctl.operate("ups_a", sel["select_token"], "manager")
        with pytest.raises(dc.DeviceControlError):
            ctl.operate("ups_a", sel["select_token"], "manager")

    def test_token_expires(self, ctl, clock):
        remote(ctl, "ups_a")
        sel = ctl.select("ups_a", "TRANSFER_TO_BYPASS", "manager")
        clock.tick(dc.SELECT_TTL_S + 1)
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.operate("ups_a", sel["select_token"], "manager")
        assert "expired" in exc.value.detail
        assert ctl.devices["ups_a"].state == dc.UPS_DOUBLE_CONVERSION

    def test_token_is_bound_to_the_actor(self, ctl):
        remote(ctl, "ups_a")
        sel = ctl.select("ups_a", "TRANSFER_TO_BYPASS", "manager")
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.operate("ups_a", sel["select_token"], "intruder")
        assert exc.value.status == 403
        assert ctl.devices["ups_a"].state == dc.UPS_DOUBLE_CONVERSION

    def test_token_is_bound_to_the_device(self, ctl):
        remote(ctl, "ups_a", "genset_a_01")
        sel = ctl.select("ups_a", "TRANSFER_TO_BYPASS", "manager")
        with pytest.raises(dc.DeviceControlError):
            ctl.operate("genset_a_01", sel["select_token"], "manager")

    def test_new_selection_replaces_the_previous_one(self, ctl):
        remote(ctl, "genset_a_01")
        first = ctl.select("genset_a_01", "START", "manager")
        ctl.select("genset_a_01", "START", "manager")
        with pytest.raises(dc.DeviceControlError):
            ctl.operate("genset_a_01", first["select_token"], "manager")

    def test_interlocks_are_re_evaluated_at_operate(self, ctl, clock):
        start_and_settle(ctl, clock, "genset_a_01")
        remote(ctl, "ats_a")
        sel = ctl.select("ats_a", "TRANSFER_TO_EMERGENCY", "manager")
        run(ctl, "genset_a_01", "STOP")  # source disappears after select
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.operate("ats_a", sel["select_token"], "manager")
        assert "Emergency source not available" in exc.value.detail
        assert ctl.devices["ats_a"].state == dc.XFER_NORMAL

    def test_unknown_command_and_device(self, ctl):
        remote(ctl, "ups_a")
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.select("ups_a", "START", "manager")
        assert exc.value.status == 400
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.select("rack_01", "START", "manager")
        assert exc.value.status == 404


class TestGenerator:
    def test_start_sequence_is_time_driven(self, ctl, clock):
        remote(ctl, "genset_a_01")
        run(ctl, "genset_a_01", "START")
        assert ctl.snapshot("genset_a_01")["state"] == dc.GEN_CRANKING
        clock.tick(dc.CRANK_TIME_S / 2)
        snap = ctl.snapshot("genset_a_01")
        assert snap["state"] == dc.GEN_CRANKING
        readings = {r["label"]: r["value"] for r in snap["readings"]}
        assert 0 < readings["Engine speed"] < dc.RATED_RPM
        assert readings["Output voltage"] == 0
        clock.tick(dc.CRANK_TIME_S)
        snap = ctl.snapshot("genset_a_01")
        assert snap["state"] == dc.GEN_RUNNING
        readings = {r["label"]: r["value"] for r in snap["readings"]}
        assert readings["Engine speed"] == dc.RATED_RPM
        assert readings["Output voltage"] == 480
        assert readings["Real power"] == 0

    def test_stop_runs_cooldown_then_standby(self, ctl, clock):
        start_and_settle(ctl, clock, "genset_a_01")
        run(ctl, "genset_a_01", "STOP")
        assert ctl.snapshot("genset_a_01")["state"] == dc.GEN_COOLDOWN
        clock.tick(dc.COOLDOWN_TIME_S + 0.1)
        assert ctl.snapshot("genset_a_01")["state"] == dc.GEN_STANDBY

    def test_cannot_start_twice_or_stop_in_standby(self, ctl, clock):
        remote(ctl, "genset_a_01")
        with pytest.raises(dc.DeviceControlError):
            ctl.select("genset_a_01", "STOP", "manager")
        run(ctl, "genset_a_01", "START")
        with pytest.raises(dc.DeviceControlError):
            ctl.select("genset_a_01", "START", "manager")

    def test_only_set_carrying_load_cannot_be_stopped(self, ctl, clock):
        start_and_settle(ctl, clock, "genset_a_01")
        remote(ctl, "ats_a")
        run(ctl, "ats_a", "TRANSFER_TO_EMERGENCY")
        assert ctl.snapshot("genset_a_01")["state"] == dc.GEN_ON_LOAD
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.select("genset_a_01", "STOP", "manager")
        assert "only source" in exc.value.detail

    def test_second_set_shares_load_and_frees_the_first(self, ctl, clock):
        start_and_settle(ctl, clock, "genset_a_01")
        remote(ctl, "ats_a")
        run(ctl, "ats_a", "TRANSFER_TO_EMERGENCY")
        solo = {r["label"]: r["value"] for r in ctl.snapshot("genset_a_01")["readings"]}
        start_and_settle(ctl, clock, "genset_a_02")
        both = {r["label"]: r["value"] for r in ctl.snapshot("genset_a_01")["readings"]}
        assert ctl.snapshot("genset_a_02")["state"] == dc.GEN_ON_LOAD
        assert both["Real power"] == pytest.approx(solo["Real power"] / 2, abs=1)
        run(ctl, "genset_a_01", "STOP")
        assert ctl.snapshot("genset_a_01")["state"] == dc.GEN_COOLDOWN


class TestTransfer:
    def test_no_transfer_to_a_dead_source(self, ctl):
        remote(ctl, "ats_a")
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.select("ats_a", "TRANSFER_TO_EMERGENCY", "manager")
        assert "Emergency source not available" in exc.value.detail

    def test_cranking_is_not_a_source(self, ctl):
        remote(ctl, "ats_a", "genset_a_01")
        run(ctl, "genset_a_01", "START")
        with pytest.raises(dc.DeviceControlError):
            ctl.select("ats_a", "TRANSFER_TO_EMERGENCY", "manager")

    def test_other_path_generator_does_not_count(self, ctl, clock):
        start_and_settle(ctl, clock, "genset_b_01")
        remote(ctl, "ats_a")
        with pytest.raises(dc.DeviceControlError):
            ctl.select("ats_a", "TRANSFER_TO_EMERGENCY", "manager")

    def test_transfer_and_retransfer(self, ctl, clock):
        start_and_settle(ctl, clock, "genset_a_01")
        remote(ctl, "ats_a")
        event = run(ctl, "ats_a", "TRANSFER_TO_EMERGENCY")
        assert (event["from_state"], event["to_state"]) == (dc.XFER_NORMAL, dc.XFER_EMERGENCY)
        snap = ctl.snapshot("ats_a")
        assert snap["status"]["tone"] == "warn"
        readings = {r["label"]: r["value"] for r in snap["readings"]}
        assert readings["Emergency source voltage"] == 480
        # 2500 kW * 0.62 / 0.965 / (sqrt(3) * 480 V * 0.98) = 1971 A
        assert readings["Load current"] == pytest.approx(1971, abs=2)
        run(ctl, "ats_a", "RETRANSFER_TO_NORMAL")
        assert ctl.snapshot("ats_a")["state"] == dc.XFER_NORMAL
        assert ctl.snapshot("genset_a_01")["state"] == dc.GEN_RUNNING


class TestUps:
    def test_maintenance_bypass_only_from_static_bypass(self, ctl):
        remote(ctl, "ups_a")
        with pytest.raises(dc.DeviceControlError) as exc:
            ctl.select("ups_a", "ENGAGE_MAINT_BYPASS", "manager")
        assert "static bypass first" in exc.value.detail

    def test_full_bypass_sequence_and_back(self, ctl):
        remote(ctl, "ups_a")
        run(ctl, "ups_a", "TRANSFER_TO_BYPASS")
        assert ctl.snapshot("ups_a")["status"]["tone"] == "warn"
        run(ctl, "ups_a", "ENGAGE_MAINT_BYPASS")
        snap = ctl.snapshot("ups_a")
        assert snap["state"] == dc.UPS_MAINT_BYPASS
        assert snap["status"]["tone"] == "crit"
        with pytest.raises(dc.DeviceControlError):
            ctl.select("ups_a", "RETURN_TO_INVERTER", "manager")
        run(ctl, "ups_a", "RELEASE_MAINT_BYPASS")
        run(ctl, "ups_a", "RETURN_TO_INVERTER")
        assert ctl.snapshot("ups_a")["state"] == dc.UPS_DOUBLE_CONVERSION

    def test_readings_follow_the_mode(self, ctl):
        on_inverter = {r["label"]: r["value"] for r in ctl.snapshot("ups_a")["readings"]}
        assert on_inverter["Output load"] == 1550
        assert on_inverter["Battery runtime (estimate)"] == pytest.approx(11.3, abs=0.1)
        remote(ctl, "ups_a")
        run(ctl, "ups_a", "TRANSFER_TO_BYPASS")
        on_bypass = {r["label"]: r["value"] for r in ctl.snapshot("ups_a")["readings"]}
        assert on_bypass["Battery runtime (estimate)"] == 0
        assert on_bypass["Losses (model)"] < on_inverter["Losses (model)"]


class TestEvents:
    def test_events_are_newest_first_and_bounded(self, ctl):
        remote(ctl, "ups_a")
        run(ctl, "ups_a", "TRANSFER_TO_BYPASS")
        events = ctl.snapshot_all()["events"]
        assert [e["event"] for e in events[:2]] == ["command", "authority"]
        assert events[0]["command"] == "TRANSFER_TO_BYPASS"


# ── Routes ──────────────────────────────────────────────────────────
@pytest.fixture
def app_client(monkeypatch):
    monkeypatch.delenv("DC_EPMS_REQUIRE_AUTH", raising=False)
    app = FastAPI()
    controller = dc.DeviceController.from_components(COMPONENTS)
    app.state.forensic_ledger = ForensicLedger(InMemoryPersistence(), key=b"k" * 32)
    dc.register_device_control_routes(app, lambda: controller)
    with TestClient(app) as client:
        yield client, app, controller


def _bearer(username: str) -> dict[str, str]:
    user = seed_demo_users().find_by_username(username)
    return {"Authorization": f"Bearer {issue_token(user)}"}


LEGACY = {"actor_role": "SME_L6", "user": "bench"}


class TestRoutes:
    def test_list_is_read_only_and_open(self, app_client):
        client, _app, _ctl = app_client
        body = client.get("/api/devices").json()
        assert len(body["devices"]) == 6
        assert client.get("/api/devices/ups_a").json()["id"] == "ups_a"
        assert client.get("/api/devices/rack_01").status_code == 404

    def test_legacy_role_rule_without_token(self, app_client):
        client, _app, _ctl = app_client
        resp = client.post("/api/devices/ups_a/authority",
                           json={"authority": "REMOTE", "actor_role": "TECH_L4"})
        assert resp.status_code == 403
        resp = client.post("/api/devices/ups_a/authority",
                           json={"authority": "REMOTE", **LEGACY})
        assert resp.status_code == 200
        assert resp.json()["device"]["authority"] == "REMOTE"

    def test_token_role_wins_over_body_role(self, app_client):
        client, _app, ctl = app_client
        resp = client.post("/api/devices/ups_a/authority",
                           json={"authority": "REMOTE", **LEGACY},
                           headers=_bearer("technician"))
        assert resp.status_code == 403
        assert "FACILITY_MANAGER" in resp.json()["detail"]
        assert ctl.devices["ups_a"].authority == dc.AUTH_AUTO

    def test_manager_token_is_accepted_and_names_the_actor(self, app_client):
        client, _app, _ctl = app_client
        resp = client.post("/api/devices/ups_a/authority",
                           json={"authority": "REMOTE"}, headers=_bearer("manager"))
        assert resp.status_code == 200
        assert resp.json()["event"]["actor"] == "manager"

    def test_bad_token_is_401(self, app_client):
        client, _app, _ctl = app_client
        resp = client.post("/api/devices/ups_a/authority",
                           json={"authority": "REMOTE", **LEGACY},
                           headers={"Authorization": "Bearer not-a-token"})
        assert resp.status_code == 401

    def test_gated_deployment_requires_a_token(self, app_client, monkeypatch):
        client, _app, _ctl = app_client
        monkeypatch.setenv("DC_EPMS_REQUIRE_AUTH", "1")
        resp = client.post("/api/devices/ups_a/authority",
                           json={"authority": "REMOTE", **LEGACY})
        assert resp.status_code == 401

    def test_select_then_operate_over_http(self, app_client):
        client, _app, _ctl = app_client
        headers = _bearer("manager")
        client.post("/api/devices/ups_a/authority", json={"authority": "REMOTE"}, headers=headers)
        sel = client.post("/api/devices/ups_a/select",
                          json={"command": "TRANSFER_TO_BYPASS"}, headers=headers)
        assert sel.status_code == 200
        done = client.post("/api/devices/ups_a/operate",
                           json={"select_token": sel.json()["select_token"]}, headers=headers)
        assert done.status_code == 200
        assert done.json()["device"]["state"] == dc.UPS_STATIC_BYPASS
        assert done.json()["ledger_entry_id"]

    def test_refusals_are_409_and_logged(self, app_client):
        client, _app, _ctl = app_client
        resp = client.post("/api/devices/ats_a/select",
                           json={"command": "TRANSFER_TO_EMERGENCY", **LEGACY})
        assert resp.status_code == 409
        events = client.get("/api/devices").json()["events"]
        assert events[0]["event"] == "refused"

    def test_every_action_is_chained_in_the_ledger(self, app_client):
        import asyncio

        client, app, _ctl = app_client
        headers = _bearer("manager")
        client.post("/api/devices/ups_a/authority", json={"authority": "REMOTE"}, headers=headers)
        sel = client.post("/api/devices/ups_a/select",
                          json={"command": "TRANSFER_TO_BYPASS"}, headers=headers).json()
        client.post("/api/devices/ups_a/operate",
                    json={"select_token": sel["select_token"]}, headers=headers)
        client.post("/api/devices/ups_a/operate", json={"select_token": "stale"}, headers=headers)

        ledger = app.state.forensic_ledger
        entries = asyncio.run(ledger.persistence.fetch_all())
        actions = [e.action for e in entries]
        assert actions == [
            dc.ACTION_DEVICE_AUTHORITY,
            dc.ACTION_DEVICE_COMMAND_REQUESTED, dc.ACTION_DEVICE_COMMAND_RESULT,
            dc.ACTION_DEVICE_COMMAND_REQUESTED, dc.ACTION_DEVICE_COMMAND_RESULT,
        ]
        assert entries[1].payload["command"] == "TRANSFER_TO_BYPASS"
        assert entries[2].payload["success"] is True
        assert entries[4].payload["success"] is False
        assert all(e.actor == "manager" for e in entries)
        asyncio.run(ledger.verify_chain())

    def test_no_secret_material_in_the_public_payload(self, app_client):
        client, _app, _ctl = app_client
        client.post("/api/devices/ups_a/authority", json={"authority": "REMOTE", **LEGACY})
        client.post("/api/devices/ups_a/select",
                    json={"command": "TRANSFER_TO_BYPASS", **LEGACY})
        assert "select_token" not in client.get("/api/devices").text


class TestWiring:
    def test_routes_are_mounted_on_the_real_app(self):
        import main

        paths = {getattr(r, "path", "") for r in main.app.routes}
        assert "/api/devices" in paths
        assert "/api/devices/{device_id}/operate" in paths


class TestAgentIsolation:
    """ADR-006: AI has zero write authority. No agent, copilot,
    optimizer or MCP module may reference the control module."""

    def test_agent_stack_never_references_device_control(self):
        backend = PROJECT_ROOT / "backend"
        suspects = [
            *backend.glob("agent*.py"), *backend.glob("agents/*.py"),
            *backend.glob("optimizer*.py"), backend / "mcp_server.py",
            backend / "multi_agent.py", backend / "shift_copilot.py",
        ]
        assert len(suspects) > 5
        offenders = [
            p.name for p in suspects
            if p.exists() and "device_control" in p.read_text(encoding="utf-8")
        ]
        assert offenders == []


class TestVocabularyFence:
    def test_dc_side_is_out_of_scope(self, ctl):
        assert "dc_bus_d" not in ctl.devices
        text = pathlib.Path(dc.__file__).read_text(encoding="utf-8").lower()
        assert "800 vdc trif" not in text
        assert "three-phase dc" not in text
