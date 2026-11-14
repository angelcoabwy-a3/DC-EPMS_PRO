"""
tests/test_power_scenarios.py
=============================
Release R3-B -- backend/power_scenarios.py + config/power_scenarios.

Every scenario of the library must PASS against the closed design:
the library doubles as a regression fence for the interlocks. A
scenario that expects a block must FAIL if the plant allows the
operation.
"""

from __future__ import annotations

import asyncio
import copy
import pathlib
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import power_scenarios as ps  # noqa: E402
from backend.device_control import DeviceController, load_design  # noqa: E402
from backend.ledger import ForensicLedger  # noqa: E402
from backend.ledger.forensic_ledger import InMemoryPersistence  # noqa: E402

DESIGN = load_design(PROJECT_ROOT / "config" / "power_plant.yml")
LIBRARY = ps.load_library(PROJECT_ROOT / "config" / "power_scenarios")


class TestLibrary:
    def test_library_content(self):
        assert sorted(LIBRARY) == [
            "COMB-002", "GEN-N1-001", "MV-SW-001", "MV-SW-002", "MV-SW-003", "MV-SW-004",
            "MV-SW-005", "UPS-2N-001", "UPS-N1-001",
        ]
        for scenario in LIBRARY.values():
            assert scenario["version"].count(".") == 2
            assert scenario["audit"]["required_logging"]

    @pytest.mark.parametrize("scenario_id", sorted(LIBRARY))
    def test_every_scenario_passes_on_the_closed_design(self, scenario_id):
        result = ps.run_scenario(LIBRARY[scenario_id], DESIGN)
        bad_steps = [s for s in result["steps"] if not s["as_expected"]]
        bad_criteria = [c for c in result["criteria"] if not c["passed"]]
        assert bad_steps == []
        assert bad_criteria == []
        assert result["passed"] is True
        assert result["sandbox"] is True

    def test_training_scenario_blocks_nine_unsafe_attempts(self):
        result = ps.run_scenario(LIBRARY["MV-SW-005"], DESIGN)
        assert result["blocked_events"] == 9
        rules = " ".join(s["detail"] for s in result["steps"] if s["outcome"] == "blocked")
        for rule in ("R1", "R2", "R3", "R4", "R8", "sequence deviation", "two-person", "different person"):
            assert rule in rules

    def test_runs_are_deterministic(self):
        a = ps.run_scenario(LIBRARY["MV-SW-004"], DESIGN)
        b = ps.run_scenario(LIBRARY["MV-SW-004"], DESIGN)
        assert a == b


class TestRunnerIsAFence:
    def test_fails_when_an_expected_block_does_not_happen(self):
        scenario = copy.deepcopy(LIBRARY["UPS-N1-001"])
        weak = copy.deepcopy(DESIGN)
        weak["design_basis"]["it_load_per_path_kw"] = 10000  # second isolation now allowed
        result = ps.run_scenario(scenario, weak)
        assert result["passed"] is False
        step6 = next(s for s in result["steps"] if s["step"] == 6)
        assert (step6["expected"], step6["outcome"]) == ("blocked", "ok")

    def test_fails_when_blocked_for_the_wrong_reason(self):
        scenario = copy.deepcopy(LIBRARY["MV-SW-003"])
        scenario["sequence"][1]["reason_contains"] = "some other reason"
        assert ps.run_scenario(scenario, DESIGN)["passed"] is False

    def test_fails_when_an_expected_success_is_blocked(self):
        scenario = copy.deepcopy(LIBRARY["MV-SW-001"])
        del scenario["sequence"][0]  # authority stays AUTO
        result = ps.run_scenario(scenario, DESIGN)
        assert result["passed"] is False
        assert "AUTO" in result["steps"][0]["detail"]

    def test_fails_on_a_wrong_criterion(self):
        scenario = copy.deepcopy(LIBRARY["UPS-2N-001"])
        scenario["success_criteria"].append(
            {"check": "path", "path": "b", "field": "ups_losses_kw", "at_most": 300})
        assert ps.run_scenario(scenario, DESIGN)["passed"] is False

    def test_definition_errors_are_not_failed_runs(self):
        scenario = copy.deepcopy(LIBRARY["UPS-2N-001"])
        scenario["sequence"] = [{"step": 1, "action": "teleport", "target": "ups_a_01"}]
        with pytest.raises(ps.ScenarioError):
            ps.run_scenario(scenario, DESIGN)
        scenario["sequence"] = [{"step": 1, "action": "authority", "target": "nope_*", "mode": "REMOTE"}]
        with pytest.raises(ps.ScenarioError):
            ps.run_scenario(scenario, DESIGN)

    def test_comparison_without_a_bound_is_false(self):
        assert ps._compare(5, {}) is False
        assert ps._compare(None, {"at_least": 1}) is False

    def test_library_loader_rejects_bad_files(self, tmp_path):
        (tmp_path / "X-1.json").write_text('{"scenario_id": "X-1"}', encoding="utf-8")
        with pytest.raises(ps.ScenarioError, match="missing"):
            ps.load_library(tmp_path)
        (tmp_path / "X-1.json").write_text(
            '{"scenario_id":"Y","version":"1.0.0","title":"t","category":"c",'
            '"sequence":[],"success_criteria":[]}', encoding="utf-8")
        with pytest.raises(ps.ScenarioError, match="file name"):
            ps.load_library(tmp_path)


class TestRoutes:
    @pytest.fixture
    def client(self, monkeypatch):
        monkeypatch.delenv("DC_EPMS_REQUIRE_AUTH", raising=False)
        app = FastAPI()
        app.state.forensic_ledger = ForensicLedger(InMemoryPersistence(), key=b"k" * 32)
        app.state.live = DeviceController.from_design(DESIGN)
        ps.register_power_scenario_routes(app, lambda: LIBRARY, lambda: DESIGN)
        with TestClient(app) as c:
            yield c, app

    def test_list(self, client):
        c, _app = client
        body = c.get("/api/power-scenarios").json()
        assert len(body["scenarios"]) == 9
        assert "sandbox" in body["sandbox_notice"]
        first = body["scenarios"][0]
        assert {"scenario_id", "version", "title", "steps", "criteria", "safety_critical"} <= set(first)

    def test_run_is_sandboxed_and_recorded(self, client):
        c, app = client
        before = app.state.live.snapshot_all()["paths"]
        result = c.post("/api/power-scenarios/UPS-2N-001/run").json()
        assert result["passed"] is True
        assert result["ledger_entry_id"]
        assert app.state.live.snapshot_all()["paths"] == before
        entries = asyncio.run(app.state.forensic_ledger.persistence.fetch_all())
        assert entries[-1].action == ps.ACTION_SCENARIO_RUN
        assert entries[-1].payload == {
            "scenario_id": "UPS-2N-001", "version": "1.0.0", "passed": True, "blocked_events": 0,
        }

    def test_unknown_scenario(self, client):
        c, _app = client
        assert c.post("/api/power-scenarios/NOPE/run").status_code == 404
