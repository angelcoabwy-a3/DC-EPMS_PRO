"""T1 routes: operator training drills on the simulated plant.

GET  /api/training/drills      drill library (summaries)
POST /api/training/start       {"drill_id"}: reset the SIMULATED plant
                               and the alarm state, apply the drill
                               setup, start the clock
GET  /api/training/session     evaluate and return the running drill
POST /api/training/abort       stop the running drill
POST /api/training/reset       back to the design lineup (no drill)
GET  /api/training/report      last finished drill report (JSON)

Start / abort / reset need FACILITY_MANAGER (they reset the shared
simulated plant). Start, end and reset are chained in the Forensic
Ledger; the end entry carries the SHA-256 of the report.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request

from backend.alarm_engine import AlarmEngine
from backend.device_control import DeviceControlError, DeviceController, _ledger_append, authorise
from backend.training import TrainingError, TrainingManager, drill_summary

ACTION_TRAINING_START = "TRAINING_DRILL_STARTED"
ACTION_TRAINING_RESULT = "TRAINING_DRILL_RESULT"
ACTION_TRAINING_RESET = "TRAINING_PLANT_RESET"


def report_sha256(report: dict[str, Any]) -> str:
    body = json.dumps(report, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def register_training_routes(
    app: FastAPI,
    controller_getter: Callable[[], DeviceController | None],
    engine: AlarmEngine,
    manager_getter: Callable[[], TrainingManager | None],
) -> None:
    def _deps() -> tuple[DeviceController, TrainingManager]:
        ctl, mgr = controller_getter(), manager_getter()
        if ctl is None or mgr is None:
            raise HTTPException(503, "training unavailable: plant design or drill library not loaded")
        return ctl, mgr

    async def _close_out(request: Request, mgr: TrainingManager, view: dict[str, Any]) -> dict[str, Any]:
        """Ledger the result once, when the drill has just ended."""
        s = mgr.session
        if s is None or s.active or s.ledger_entry_id or mgr.last_report is None:
            return view
        report = mgr.last_report
        digest = report_sha256(report)
        entry = await _ledger_append(request.app, s.operator, ACTION_TRAINING_RESULT, {
            "drill": s.drill["id"], "version": s.drill.get("version", 1),
            "outcome": s.outcome, "score": s.score, "reason": s.reason,
            "duration_ms": report["duration_ms"], "report_sha256": digest,
        })
        s.ledger_entry_id = entry or "ledger-unavailable"
        report["ledger_entry_id"] = entry
        # T4: the printed / downloaded report carries the digest the
        # ledger recorded, and says what it covers (the two keys added
        # after hashing are excluded).
        report["integrity"] = {
            "report_sha256": digest,
            "covers": "this report without the ledger_entry_id and integrity keys "
                      "(JSON, sorted keys, compact separators)",
            "ledger_entry_id": entry,
        }
        view["session"]["ledger_entry_id"] = s.ledger_entry_id
        return view

    @app.get("/api/training/drills")
    async def list_drills() -> dict[str, Any]:
        _, mgr = _deps()
        return {"drills": [drill_summary(d) for d in mgr.drills.values()], "simulated": True}

    @app.post("/api/training/start")
    async def start_drill(request: Request, payload: dict = Body(default={})) -> dict[str, Any]:
        actor = authorise(request, payload or {})
        ctl, mgr = _deps()
        drill_id = str((payload or {}).get("drill_id") or "")
        try:
            view = mgr.start(drill_id, actor, ctl, engine)
        except (TrainingError, DeviceControlError) as exc:
            raise HTTPException(exc.status, exc.detail) from exc
        await _ledger_append(request.app, actor, ACTION_TRAINING_START, {
            "drill": drill_id, "version": mgr.session.drill.get("version", 1),
        })
        return view

    @app.get("/api/training/session")
    async def session(request: Request) -> dict[str, Any]:
        ctl, mgr = _deps()
        view = mgr.evaluate(ctl, engine)
        return await _close_out(request, mgr, view)

    @app.post("/api/training/abort")
    async def abort(request: Request, payload: dict = Body(default={})) -> dict[str, Any]:
        actor = authorise(request, payload or {})
        ctl, mgr = _deps()
        try:
            view = mgr.abort(actor, ctl, engine)
        except TrainingError as exc:
            raise HTTPException(exc.status, exc.detail) from exc
        return await _close_out(request, mgr, view)

    @app.post("/api/training/reset")
    async def reset(request: Request, payload: dict = Body(default={})) -> dict[str, Any]:
        actor = authorise(request, payload or {})
        ctl, mgr = _deps()
        if mgr.session is not None and mgr.session.active:
            raise HTTPException(409, "a drill is running: abort it first")
        ctl.reset(actor)
        engine.reset()
        entry = await _ledger_append(request.app, actor, ACTION_TRAINING_RESET, {"plant": "design lineup"})
        return {"success": True, "ledger_entry_id": entry}

    @app.get("/api/training/report")
    async def report() -> dict[str, Any]:
        _, mgr = _deps()
        if mgr.last_report is None:
            raise HTTPException(404, "no finished drill yet")
        return mgr.last_report
