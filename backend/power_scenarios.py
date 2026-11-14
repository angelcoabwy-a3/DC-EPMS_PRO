"""
backend/power_scenarios.py
==========================
Release R3-B -- Executable scenario library for the power plant.

Each scenario is a versioned JSON file in ``config/power_scenarios``:
preconditions, a sequence of actions with the EXPECTED outcome of each
(``ok`` or ``blocked``, optionally with a fragment of the reason), and
success criteria checked on the final plant state.

A run happens in a SANDBOX: a fresh ``DeviceController`` built from
``config/power_plant.yml`` with a virtual clock. The live plant model
is never touched, so anyone signed in may run a scenario.

A scenario PASSES only if every step had the expected outcome and
every criterion holds. A scenario that expects an unsafe operation to
be blocked fails loudly if the plant ever allows it: the library is a
regression fence for the interlocks as much as a training aid.

HONEST SCOPE: outcomes come from the same deterministic model the
Power Controls view uses. There is no thermal model, no utility
outage dynamics, no battery discharge and no arc-flash consequence.
Scenario IDs of the operator's target library that need those
(TH-001, TH-002, COMB-001) are therefore NOT in the library yet.
"""

from __future__ import annotations

import fnmatch
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from backend.device_control import DeviceControlError, DeviceController

OPERATOR = "operator"
WITNESS = "witness"
ACTION_SCENARIO_RUN = "POWER_SCENARIO_RUN"
_REQUIRED = ("scenario_id", "version", "title", "category", "sequence", "success_criteria")


class ScenarioError(ValueError):
    """The scenario file itself is wrong (not a failed run)."""


def load_library(directory: Path) -> dict[str, dict[str, Any]]:
    library: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        with open(path, encoding="utf-8") as handle:
            scenario = json.load(handle)
        missing = [key for key in _REQUIRED if key not in scenario]
        if missing:
            raise ScenarioError(f"{path.name}: missing {missing}")
        if scenario["scenario_id"] != path.stem:
            raise ScenarioError(f"{path.name}: scenario_id must match the file name")
        library[scenario["scenario_id"]] = scenario
    return library


def describe(scenario: dict[str, Any]) -> dict[str, Any]:
    return {
        key: scenario.get(key)
        for key in ("scenario_id", "version", "title", "category", "severity",
                    "tier_iv_relevance", "safety_critical", "description")
    } | {"steps": len(scenario["sequence"]), "criteria": len(scenario["success_criteria"])}


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _targets(ctl: DeviceController, step: dict[str, Any]) -> list[str]:
    if "targets" in step:
        return list(step["targets"])
    pattern = str(step.get("target") or "")
    if "*" in pattern:
        matched = sorted(fnmatch.filter(ctl.devices, pattern))
        if not matched:
            raise ScenarioError(f"step {step.get('step')}: no device matches {pattern!r}")
        return matched
    return [pattern]


def _run_procedure(ctl: DeviceController, bay_id: str, goal: str) -> None:
    proc = ctl.start_procedure(bay_id, goal, OPERATOR)
    for item in proc["steps"]:
        if item["two_person"]:
            ctl.witness_step(proc["procedure_id"], item["step"], WITNESS)
        ctl.execute_step(proc["procedure_id"], item["step"], OPERATOR)


def _do(ctl: DeviceController, clock: _Clock, step: dict[str, Any], target: str) -> None:
    action = step.get("action")
    if action == "authority":
        ctl.set_authority(target, step["mode"], OPERATOR)
    elif action == "command":
        selection = ctl.select(target, step["command"], OPERATOR)
        ctl.operate(target, selection["select_token"], OPERATOR)
    elif action == "advance":
        clock.t += float(step["seconds"])
        ctl.snapshot_all()
    elif action == "procedure":
        _run_procedure(ctl, target, step["goal"])
    elif action == "procedure_start":
        ctl.start_procedure(target, step["goal"], OPERATOR)
    elif action == "procedure_step":
        proc = ctl._bay_procedure(target)
        if proc is None:
            raise ScenarioError(f"step {step.get('step')}: no procedure in progress on {target}")
        if step.get("witness"):
            ctl.witness_step(proc.procedure_id, int(step["number"]), str(step["witness"]))
        ctl.execute_step(proc.procedure_id, int(step["number"]), OPERATOR)
    elif action == "bay_attempt":
        ctl.bay_attempt(target, step["operation"], OPERATOR)
    elif action == "path_loss":
        ctl.inject_path_loss(step["path"])
    else:
        raise ScenarioError(f"step {step.get('step')}: unknown action {action!r}")


def _compare(actual: Any, criterion: dict[str, Any]) -> bool:
    if "equals" in criterion:
        return actual == criterion["equals"]
    ok = True
    if "at_least" in criterion:
        ok = ok and actual is not None and actual >= criterion["at_least"]
    if "at_most" in criterion:
        ok = ok and actual is not None and actual <= criterion["at_most"]
    return ok if ("at_least" in criterion or "at_most" in criterion) else False


def _criterion(
    ctl: DeviceController, criterion: dict[str, Any], blocked: int,
) -> tuple[bool, Any]:
    check = criterion.get("check")
    if check == "device_state":
        actual = ctl.snapshot(criterion["target"])["state"]
        return _compare(actual, criterion), actual
    if check == "bay":
        bay = ctl.bays[criterion["target"]]
        actual = {"cb": bay.cb, "ds": bay.ds, "es": bay.es, "loto": bay.loto}
        return all(actual[k] == criterion[k] for k in actual if k in criterion), actual
    if check == "path":
        actual = ctl.path_summary(criterion["path"]).get(criterion["field"])
        return _compare(actual, criterion), actual
    if check == "reading":
        readings = ctl.snapshot(criterion["target"])["readings"]
        actual = next((r["value"] for r in readings if r["label"] == criterion["label"]), None)
        return _compare(actual, criterion), actual
    if check == "blocked_events":
        return _compare(blocked, criterion), blocked
    raise ScenarioError(f"unknown criterion check {check!r}")


def run_scenario(scenario: dict[str, Any], design: dict[str, Any]) -> dict[str, Any]:
    """Execute one scenario in a sandbox and report step by step."""
    clock = _Clock()
    ctl = DeviceController.from_design(design, clock=clock, wall_clock=clock)
    steps = []
    for step in scenario["sequence"]:
        expected = step.get("expect", "ok")
        fragment = str(step.get("reason_contains") or "")
        outcome, detail = "ok", ""
        targets = [""] if step.get("action") in ("advance", "path_loss") else _targets(ctl, step)
        for target in targets:
            try:
                _do(ctl, clock, step, target)
            except DeviceControlError as exc:
                outcome, detail = "blocked", exc.detail
                break
        as_expected = outcome == expected and (not fragment or fragment.lower() in detail.lower())
        steps.append({
            "step": step.get("step"), "action": step.get("action"),
            "target": step.get("target") or ", ".join(step.get("targets") or []) or step.get("path") or "",
            "what": step.get("command") or step.get("operation") or step.get("goal")
                    or step.get("mode") or (f"{step['seconds']} s" if "seconds" in step else "")
                    or (f"step {step['number']}" if "number" in step else ""),
            "expected": expected, "outcome": outcome, "detail": detail,
            "as_expected": as_expected,
        })
    blocked = sum(1 for s in steps if s["outcome"] == "blocked")
    criteria = []
    for criterion in scenario["success_criteria"]:
        ok, actual = _criterion(ctl, criterion, blocked)
        criteria.append({"criterion": criterion, "actual": actual, "passed": ok})
    events = list(ctl._events)
    return {
        "scenario_id": scenario["scenario_id"],
        "version": scenario["version"],
        "title": scenario["title"],
        "passed": all(s["as_expected"] for s in steps) and all(c["passed"] for c in criteria),
        "steps": steps,
        "criteria": criteria,
        "blocked_events": blocked,
        "events": len(events),
        "simulated_seconds": clock.t,
        "sandbox": True,
        "quality": "simulated",
    }


def register_power_scenario_routes(
    app: FastAPI,
    library_getter: Callable[[], dict[str, dict[str, Any]]],
    design_getter: Callable[[], dict[str, Any] | None],
) -> None:
    @app.get("/api/power-scenarios")
    async def list_power_scenarios() -> dict[str, Any]:
        """Scenario library metadata. Read-only."""
        library = library_getter()
        return {
            "scenarios": [describe(s) for s in library.values()],
            "sandbox_notice": (
                "Runs execute in a sandbox copy of the plant model. The live "
                "Power Controls state is never changed."
            ),
        }

    @app.post("/api/power-scenarios/{scenario_id}/run")
    async def run_power_scenario(scenario_id: str, request: Request) -> dict[str, Any]:
        """Run one scenario in a sandbox. Recorded in the ledger."""
        scenario = library_getter().get(scenario_id)
        if scenario is None:
            raise HTTPException(404, f"scenario {scenario_id!r} not found")
        design = design_getter()
        if design is None:
            raise HTTPException(503, "power plant design not loaded")
        try:
            result = run_scenario(scenario, design)
        except ScenarioError as exc:
            raise HTTPException(500, f"scenario definition error: {exc}") from exc
        ledger = getattr(request.app.state, "forensic_ledger", None)
        result["ledger_entry_id"] = None
        if ledger is not None:
            entry = await ledger.append(
                actor=_actor(request), action=ACTION_SCENARIO_RUN,
                payload={"scenario_id": scenario_id, "version": scenario["version"],
                         "passed": result["passed"], "blocked_events": result["blocked_events"]},
            )
            result["ledger_entry_id"] = getattr(entry, "entry_id", None)
        return result


def _actor(request: Request) -> str:
    from backend.auth.jwt_handler import TokenError, verify_token
    from backend.auth.session_gate import _extract_token

    token = _extract_token(request.scope)
    if token:
        try:
            return verify_token(token).username
        except TokenError:
            return "invalid-token"
    return "anonymous"
