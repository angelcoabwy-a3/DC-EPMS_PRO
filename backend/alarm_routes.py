"""HMI H4 routes: alarm list and acknowledgement for the simulated plant.

GET  /api/alarms               evaluate the plant, return active /
                               unacknowledged alarms + journal
POST /api/alarms/{id}/ack      acknowledge one alarm
POST /api/alarms/ack-all       acknowledge every pending alarm

Acknowledging changes no plant state; it records that a person saw
the alarm. Minimum role L1_OPERATOR (the alarm-handling duty of the
console operator), actor from the session token, every ACK chained in
the Forensic Ledger.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request

from backend.alarm_engine import AlarmEngine, AlarmError, conditions_from_plant
from backend.device_control import DeviceController, _ledger_append, authorise

ACTION_ALARM_ACK = "ALARM_ACK"
ACK_MIN_ROLE = "L1_OPERATOR"

SCOPE_NOTICE = (
    "Alarms of the SIMULATED Power Controls plant. Times are server "
    "observation times (ms resolution, accurate to the polling "
    "interval), not field sequence-of-events stamps. No shelving."
)


def register_alarm_routes(
    app: FastAPI,
    controller_getter: Callable[[], DeviceController | None],
    engine: AlarmEngine,
) -> None:
    def _evaluate() -> None:
        ctl = controller_getter()
        if ctl is None:
            raise HTTPException(503, "alarms unavailable: power plant design not loaded")
        engine.evaluate(conditions_from_plant(ctl.snapshot_all()))

    @app.get("/api/alarms")
    async def list_alarms() -> dict[str, Any]:
        _evaluate()
        return {"notice": SCOPE_NOTICE, "quality": "simulated", **engine.snapshot()}

    @app.post("/api/alarms/ack-all")
    async def ack_all_alarms(request: Request, payload: dict = Body(default={})) -> dict[str, Any]:
        actor = authorise(request, payload or {}, minimum=ACK_MIN_ROLE)
        _evaluate()
        acked = engine.ack_all(actor)
        entry = None
        if acked:
            entry = await _ledger_append(
                request.app, actor, ACTION_ALARM_ACK,
                {"alarm_ids": [a["id"] for a in acked], "acked": acked[0]["acked"]},
            )
        return {"success": True, "acked": acked, "ledger_entry_id": entry}

    @app.post("/api/alarms/{alarm_id}/ack")
    async def ack_alarm(
        alarm_id: str, request: Request, payload: dict = Body(default={}),
    ) -> dict[str, Any]:
        actor = authorise(request, payload or {}, minimum=ACK_MIN_ROLE)
        _evaluate()
        try:
            alarm = engine.ack(alarm_id, actor)
        except AlarmError as exc:
            raise HTTPException(exc.status, exc.detail) from exc
        entry = await _ledger_append(
            request.app, actor, ACTION_ALARM_ACK,
            {"alarm_ids": [alarm_id], "acked": alarm["acked"], "state": alarm["state"]},
        )
        return {"success": True, "alarm": alarm, "ledger_entry_id": entry}
