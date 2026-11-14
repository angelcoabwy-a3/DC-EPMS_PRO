"""
tests/test_ot_security.py
=========================
Release R2-A -- backend/ot_security.py.

  * evaluate_checks is pure and deterministic; every rule is
    exercised in both its pass and fail posture.
  * A section that cannot be read yields a FAILING check, never a
    silent pass.
  * The endpoint is read-only, leaks no secret material, and reports
    the real state of the app object (gate, ledger, BMS, edge).
  * Honest-scope fence: the "no traffic inspection" finding and the
    disclaimer are always present.
"""

from __future__ import annotations

import copy
import json
import pathlib
import sys

import pytest

# Same import path as tests/test_smoke.py (DC-EPMS-008 class).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "backend"))

from fastapi.testclient import TestClient

from backend.auth.jwt_handler import ENV_JWT_SECRET, ENV_PASSWORD_PREFIX
from backend.auth.session_gate import ENV_REQUIRE_AUTH
from backend.ot_security import (
    DISCLAIMER,
    SEVERITY_ORDER,
    evaluate_checks,
    summarise,
)

_USERS = ("OPERATOR", "TECHNICIAN", "SAFETY_A", "SAFETY_B", "MANAGER")


def _hardened_facts() -> dict:
    """The best posture the platform can reach today."""
    return {
        "access": {
            "gate_enabled": True,
            "jwt_secret_from_env": True,
            "user_store_ready": True,
            "users": [
                {"username": "manager", "role": "FACILITY_MANAGER", "password_source": "environment"},
                {"username": "operator", "role": "L1_OPERATOR", "password_source": "environment"},
            ],
        },
        "ledger": {
            "available": True, "verified": True, "divergence_index": None,
            "reason": None, "key_version": 1, "hmac_key_from_env": True,
            "persistence": "postgres", "total_entries": 12,
        },
        "bms": {
            "available": True, "total_tags": 62, "writable_tags": 21,
            "by_protocol": {"BACnet": 55, "Modbus": 7},
            "writable_by_protocol": {"BACnet": 21},
            "audit_total": 3, "audit_denied": 1, "audit_accepted": 2, "audit_recent": [],
        },
        "edge": {
            "available": True, "channel_count": 4, "batches_accepted": 7,
            "envelopes_accepted": 28, "envelopes_rejected": 0,
            "last_ingest_ts": 1794600000.0, "device_authenticated": False,
        },
        "monitoring": {"traffic_inspection": False, "zones_and_conduits_modelled": False},
    }


def _by_id(checks: list[dict]) -> dict[str, dict]:
    ids = [c["id"] for c in checks]
    assert len(ids) == len(set(ids)), f"duplicate check ids: {ids}"
    return {c["id"]: c for c in checks}


class TestEvaluateChecksHardened:
    def test_is_deterministic_and_does_not_mutate_facts(self):
        facts = _hardened_facts()
        snapshot = copy.deepcopy(facts)
        first = evaluate_checks(facts)
        second = evaluate_checks(facts)
        assert first == second
        assert facts == snapshot

    def test_hardened_posture_passes_every_configurable_control(self):
        checks = _by_id(evaluate_checks(_hardened_facts()))
        for cid in ("OT-AUTH-01", "OT-AUTH-02", "OT-AUTH-03",
                    "OT-AUD-01", "OT-AUD-02", "OT-AUD-03", "OT-DEV-02"):
            assert checks[cid]["status"] == "pass", cid
            assert checks[cid]["severity"] is None
            assert checks[cid]["remediation"] == ""

    def test_honest_scope_gaps_remain_open_even_when_hardened(self):
        checks = _by_id(evaluate_checks(_hardened_facts()))
        assert checks["OT-NET-01"]["status"] == "fail"
        assert checks["OT-NET-01"]["severity"] == "medium"
        assert "Morpheus" in checks["OT-NET-01"]["detail"]
        assert checks["OT-NET-02"]["status"] == "fail"
        assert checks["OT-DEV-01"]["status"] == "fail"
        assert "SR 1.2" in checks["OT-DEV-01"]["reference"]
        summary = summarise(list(checks.values()))
        assert summary["by_severity"] == {"critical": 0, "high": 0, "medium": 2, "low": 1}
        assert summary["worst_severity"] == "medium"

    def test_every_check_has_the_full_shape_and_a_reference(self):
        for c in evaluate_checks(_hardened_facts()):
            assert set(c) == {"id", "status", "severity", "title", "detail",
                              "reference", "remediation"}
            assert c["status"] in {"pass", "fail", "info"}
            assert c["reference"].startswith("IEC 62443-3-3 SR ")
            assert c["title"]
            assert c["detail"]
            if c["status"] == "fail":
                assert c["severity"] in SEVERITY_ORDER
                assert c["remediation"]
            else:
                assert c["severity"] is None


class TestEvaluateChecksFailures:
    def test_gate_off_is_high(self):
        facts = _hardened_facts()
        facts["access"]["gate_enabled"] = False
        c = _by_id(evaluate_checks(facts))["OT-AUTH-01"]
        assert (c["status"], c["severity"]) == ("fail", "high")
        assert "DC_EPMS_REQUIRE_AUTH" in c["remediation"]

    def test_ephemeral_jwt_secret_is_medium(self):
        facts = _hardened_facts()
        facts["access"]["jwt_secret_from_env"] = False
        c = _by_id(evaluate_checks(facts))["OT-AUTH-02"]
        assert (c["status"], c["severity"]) == ("fail", "medium")

    def test_repo_default_passwords_are_named(self):
        facts = _hardened_facts()
        facts["access"]["users"][1]["password_source"] = "repo_default"
        c = _by_id(evaluate_checks(facts))["OT-AUTH-03"]
        assert (c["status"], c["severity"]) == ("fail", "high")
        assert "operator" in c["detail"]
        assert "manager" not in c["detail"]
        assert "1 of 2" in c["detail"]

    def test_user_store_down_is_high(self):
        facts = _hardened_facts()
        facts["access"]["user_store_ready"] = False
        facts["access"]["users"] = []
        c = _by_id(evaluate_checks(facts))["OT-AUTH-03"]
        assert (c["status"], c["severity"]) == ("fail", "high")

    def test_unreadable_access_section_fails_closed(self):
        facts = _hardened_facts()
        facts["access"] = {"error": "boom"}
        checks = _by_id(evaluate_checks(facts))
        assert checks["OT-AUTH-00"]["status"] == "fail"
        assert "OT-AUTH-01" not in checks

    def test_broken_chain_is_critical_and_names_the_index(self):
        facts = _hardened_facts()
        facts["ledger"].update(verified=False, divergence_index=7, reason="hmac mismatch")
        checks = evaluate_checks(facts)
        c = _by_id(checks)["OT-AUD-01"]
        assert (c["status"], c["severity"]) == ("fail", "critical")
        assert "index 7" in c["detail"]
        assert "hmac mismatch" in c["detail"]
        assert summarise(checks)["worst_severity"] == "critical"

    def test_ephemeral_ledger_key_and_memory_store_are_medium(self):
        facts = _hardened_facts()
        facts["ledger"].update(hmac_key_from_env=False, key_version=0, persistence="memory")
        checks = _by_id(evaluate_checks(facts))
        assert (checks["OT-AUD-02"]["status"], checks["OT-AUD-02"]["severity"]) == ("fail", "medium")
        assert (checks["OT-AUD-03"]["status"], checks["OT-AUD-03"]["severity"]) == ("fail", "medium")

    def test_missing_ledger_is_high_and_skips_dependent_checks(self):
        facts = _hardened_facts()
        facts["ledger"] = {"available": False, "error": "init failed"}
        checks = _by_id(evaluate_checks(facts))
        assert (checks["OT-AUD-01"]["status"], checks["OT-AUD-01"]["severity"]) == ("fail", "high")
        assert "init failed" in checks["OT-AUD-01"]["detail"]
        assert "OT-AUD-02" not in checks
        assert "OT-AUD-03" not in checks

    def test_rejected_envelopes_are_low(self):
        facts = _hardened_facts()
        facts["edge"]["envelopes_rejected"] = 3
        c = _by_id(evaluate_checks(facts))["OT-DEV-02"]
        assert (c["status"], c["severity"]) == ("fail", "low")
        assert "3 envelope(s)" in c["detail"]

    def test_unavailable_bms_and_edge_are_informational(self):
        facts = _hardened_facts()
        facts["bms"] = {"available": False}
        facts["edge"] = {"available": False}
        checks = _by_id(evaluate_checks(facts))
        assert checks["OT-CTL-01"]["status"] == "info"
        assert "OT-CTL-02" not in checks
        assert checks["OT-DEV-01"]["status"] == "info"
        assert "OT-DEV-02" not in checks

    def test_empty_fact_sheet_never_raises_and_never_passes_silently(self):
        checks = evaluate_checks({})
        statuses = {c["id"]: c["status"] for c in checks}
        assert statuses["OT-AUTH-01"] == "fail"
        assert statuses["OT-AUD-01"] == "fail"
        assert statuses["OT-NET-01"] == "fail"
        assert "pass" not in set(statuses.values())


class TestSummarise:
    def test_counts(self):
        s = summarise(evaluate_checks(_hardened_facts()))
        assert s["failed"] == 3
        assert s["passed"] == 7
        assert s["info"] == 2
        assert sum(s["by_severity"].values()) == s["failed"]

    def test_no_failures_means_no_worst_severity(self):
        s = summarise([{"status": "pass", "severity": None}, {"status": "info", "severity": None}])
        assert s == {"failed": 0, "passed": 1, "info": 1,
                     "by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0},
                     "worst_severity": None}


@pytest.fixture
def app_client(monkeypatch: pytest.MonkeyPatch):
    import main as main_mod

    monkeypatch.setattr(main_mod, "DBManager", None)
    monkeypatch.setattr(main_mod, "db_manager", None)
    monkeypatch.delenv(ENV_REQUIRE_AUTH, raising=False)
    monkeypatch.delenv(ENV_JWT_SECRET, raising=False)
    monkeypatch.delenv("DC_EPMS_LEDGER_HMAC_KEY", raising=False)
    for name in _USERS:
        monkeypatch.delenv(ENV_PASSWORD_PREFIX + name, raising=False)
    monkeypatch.setenv("DC_EPMS_SKIP_WARMUP", "1")  # DC-EPMS-069
    with TestClient(main_mod.app) as client:
        yield client


class TestPostureEndpoint:
    def test_default_local_posture_reports_the_real_state(self, app_client):
        res = app_client.get("/api/ot-security/posture")
        assert res.status_code == 200
        body = res.json()
        assert body["schema"] == "ot_security_posture_v1"
        assert body["disclaimer"] == DISCLAIMER
        checks = {c["id"]: c for c in body["checks"]}
        assert checks["OT-AUTH-01"]["status"] == "fail"       # gate off
        assert checks["OT-AUTH-02"]["status"] == "fail"       # ephemeral secret
        assert checks["OT-AUTH-03"]["status"] == "fail"       # repo defaults
        assert checks["OT-AUD-01"]["status"] == "pass"        # empty chain verifies
        assert checks["OT-AUD-03"]["status"] == "fail"        # in memory
        assert checks["OT-NET-01"]["status"] == "fail"
        facts = body["facts"]
        assert facts["access"]["gate_enabled"] is False
        assert len(facts["access"]["users"]) == 5
        assert facts["ledger"]["persistence"] == "memory"
        assert facts["bms"]["total_tags"] >= facts["bms"]["writable_tags"] > 0
        assert sum(facts["bms"]["by_protocol"].values()) == facts["bms"]["total_tags"]
        assert facts["edge"]["available"] is True
        assert body["summary"]["worst_severity"] == "high"

    def test_response_leaks_no_secret_material(self, app_client, monkeypatch):
        secret = "jwt-secret-that-must-never-appear-0123456789"
        monkeypatch.setenv(ENV_JWT_SECRET, secret)
        raw = app_client.get("/api/ot-security/posture").text
        assert secret not in raw
        lowered = raw.lower()
        for forbidden in ("password_hash", "password_salt", "access_token",
                          "manager-demo", "operator-demo", "safety-demo"):
            assert forbidden not in lowered
        body = json.loads(raw)
        assert body["facts"]["access"]["jwt_secret_from_env"] is True
        for user in body["facts"]["access"]["users"]:
            assert set(user) == {"username", "role", "password_source"}

    def test_endpoint_is_read_only(self, app_client):
        assert app_client.post("/api/ot-security/posture").status_code == 405
        assert app_client.delete("/api/ot-security/posture").status_code == 405

    def test_a_denied_bms_write_shows_up_in_the_audit_facts(self, app_client):
        before = app_client.get("/api/ot-security/posture").json()["facts"]["bms"]
        denied = app_client.post(
            "/api/bms/write",
            json={"tag_id": "HVAC.CHWP1.STATUS", "value": "Off", "user": "intruder"},
        )
        assert denied.status_code in (401, 403)
        after = app_client.get("/api/ot-security/posture").json()["facts"]["bms"]
        # The RBAC gate refuses before the connector is reached, so the
        # connector-side buffer must NOT grow: no write was attempted.
        assert after["audit_total"] == before["audit_total"]

    def test_gated_deployment_flips_the_access_checks(self, monkeypatch):
        import main as main_mod

        monkeypatch.setattr(main_mod, "DBManager", None)
        monkeypatch.setattr(main_mod, "db_manager", None)
        monkeypatch.setenv(ENV_REQUIRE_AUTH, "1")
        monkeypatch.setenv(ENV_JWT_SECRET, "a-private-signing-secret-0123456789abcdef")
        for name in _USERS:
            monkeypatch.delenv(ENV_PASSWORD_PREFIX + name, raising=False)
        monkeypatch.setenv(ENV_PASSWORD_PREFIX + "MANAGER", "a-long-private-passphrase")
        from backend.auth.jwt_handler import _reset_ephemeral_secret_for_tests

        _reset_ephemeral_secret_for_tests()
        monkeypatch.setenv("DC_EPMS_SKIP_WARMUP", "1")  # DC-EPMS-069
        with TestClient(main_mod.app) as c:
            assert c.get("/api/ot-security/posture").status_code == 401
            login = c.post(
                "/api/auth/login",
                json={"username": "manager", "password": "a-long-private-passphrase"},
            )
            assert login.status_code == 200
            body = c.get("/api/ot-security/posture").json()
            checks = {x["id"]: x for x in body["checks"]}
            assert checks["OT-AUTH-01"]["status"] == "pass"
            assert checks["OT-AUTH-02"]["status"] == "pass"
            assert checks["OT-AUTH-03"]["status"] == "pass"
            assert [u["username"] for u in body["facts"]["access"]["users"]] == ["manager"]
