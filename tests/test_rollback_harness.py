"""
tests/test_rollback_harness.py
===============================
Verification suite for DC-EPMS-MSD-004 (Rollback Harness, ADR-011).

Covers:
  * Reverting a BMS_WRITE_REQUESTED restores the prev_value
  * The revert appends BOTH a BMS_REVERT marker AND its own
    BMS_WRITE_REQUESTED + BMS_WRITE_RESULT pair through the seam
  * A revert of a revert is allowed (creates a new entry chain)
  * SME_L6 gate on the revert endpoint
  * 404 on unknown entry_id
  * 422 when the referenced entry is not a write request
  * 422 when prev_value is missing (e.g. tag was unknown at write time)
"""

from __future__ import annotations

import asyncio
import uuid

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from backend.ledger import (
    ACTION_BMS_REVERT,
    ACTION_BMS_WRITE_REQUESTED,
    ACTION_BMS_WRITE_RESULT,
    ForensicLedger,
    InMemoryPersistence,
    reset_proposal_context,
    set_proposal_context,
    wrap_bms_write_fn,
)


class StubBMS:
    def __init__(self, initial: dict[str, float]) -> None:
        self.values = dict(initial)

    def read(self, tag_id: str):
        if tag_id not in self.values:
            return None
        return type("Tag", (), {"current_value": self.values[tag_id]})()

    def write(self, tag_id: str, value, user: str) -> tuple[bool, str]:
        if tag_id not in self.values:
            return False, f"unknown tag {tag_id}"
        self.values[tag_id] = value
        return True, f"wrote {value} to {tag_id}"


def _build_app() -> tuple[FastAPI, StubBMS, ForensicLedger]:
    bms = StubBMS({"HVAC.CHILLER1.CW_SETPOINT": 8.0})
    ledger = ForensicLedger(InMemoryPersistence(), key=b"k" * 32, key_version=1)

    def _raw(tag_id, value, user):
        return bms.write(tag_id, value, user)

    def _prev(tag_id):
        tag = bms.read(tag_id)
        return tag.current_value if tag else None

    app = FastAPI()
    app.state.forensic_ledger = ledger
    app.state.direct_bms_write_fn = wrap_bms_write_fn(
        _raw, ledger=ledger, prev_value_reader=_prev,
        source="direct", loop=None,
    )
    app.state.revert_bms_write_fn = wrap_bms_write_fn(
        _raw, ledger=ledger, prev_value_reader=_prev,
        source="revert", loop=None,
    )

    @app.post("/api/bms/write")
    async def write_bms_tag(request: Request, payload: dict = Body(...)):
        from backend.cmms_models import role_rank as _role_rank
        if _role_rank(payload.get("actor_role")) < 6:
            raise HTTPException(403, "SME_L6 required")
        tag_id = payload.get("tag_id")
        value = payload.get("value")
        user = payload.get("user", "op")
        if not tag_id:
            raise HTTPException(400, "tag_id required")
        token = set_proposal_context(payload.get("proposal_id"))
        try:
            success, message = await asyncio.to_thread(
                request.app.state.direct_bms_write_fn, tag_id, value, user,
            )
        finally:
            reset_proposal_context(token)
        if not success:
            raise HTTPException(400, message)
        return {"success": True, "message": message}

    @app.post("/api/bms/revert/{entry_id}")
    async def revert(entry_id: str, request: Request, payload: dict = Body(default={})):
        from backend.cmms_models import role_rank as _role_rank
        if _role_rank(payload.get("actor_role")) < 6:
            raise HTTPException(403, "SME_L6 required")
        ledger_ = request.app.state.forensic_ledger
        entry = await ledger_.fetch_by_id(entry_id)
        if entry is None:
            raise HTTPException(404, "entry not found")
        if entry.action != ACTION_BMS_WRITE_REQUESTED:
            raise HTTPException(
                422, f"action={entry.action!r} (not write-request)",
            )
        tag_id = entry.payload.get("tag_id")
        prev_value = entry.payload.get("prev_value")
        if not tag_id:
            raise HTTPException(422, "missing tag_id")
        if prev_value is None:
            raise HTTPException(422, "no prev_value to revert to")
        marker = await ledger_.append(
            actor=payload.get("user", "revert-op"),
            action=ACTION_BMS_REVERT,
            payload={
                "reverts_entry_id": entry_id,
                "tag_id": tag_id,
                "restoring_value": prev_value,
                "from_value": entry.payload.get("requested_value"),
                "reason": payload.get("reason", ""),
            },
        )
        success, message = await asyncio.to_thread(
            request.app.state.revert_bms_write_fn,
            tag_id, prev_value, payload.get("user", "revert-op"),
        )
        if not success:
            raise HTTPException(400, message)
        return {
            "success": True,
            "message": message,
            "restored_value": prev_value,
            "reverted_entry_id": entry_id,
            "revert_marker_entry_id": marker.entry_id,
        }

    return app, bms, ledger


def _write_and_get_request_entry_id(client, value: float = 7.5) -> str:
    r = client.post("/api/bms/write", json={
        "tag_id": "HVAC.CHILLER1.CW_SETPOINT",
        "value": value,
        "actor_role": "SME_L6",
        "user": "cet-01",
    })
    assert r.status_code == 200
    # The BMS_WRITE_REQUESTED entry is the first appended entry.
    return None  # caller fetches from ledger


async def test_revert_restores_prev_value():
    app, bms, ledger = _build_app()
    client = TestClient(app)
    # Initial: 8.0; write 7.5; revert; expect 8.0 back.
    assert bms.values["HVAC.CHILLER1.CW_SETPOINT"] == 8.0
    client.post("/api/bms/write", json={
        "tag_id": "HVAC.CHILLER1.CW_SETPOINT", "value": 7.5,
        "actor_role": "SME_L6",
    })
    assert bms.values["HVAC.CHILLER1.CW_SETPOINT"] == 7.5
    entries = await ledger.fetch_all()
    request_entry = next(e for e in entries if e.action == ACTION_BMS_WRITE_REQUESTED)
    r = client.post(f"/api/bms/revert/{request_entry.entry_id}", json={
        "actor_role": "SME_L6", "user": "cet-01", "reason": "test rollback",
    })
    assert r.status_code == 200
    assert r.json()["restored_value"] == 8.0
    assert bms.values["HVAC.CHILLER1.CW_SETPOINT"] == 8.0


async def test_revert_appends_marker_and_counter_write_entries():
    app, _, ledger = _build_app()
    client = TestClient(app)
    client.post("/api/bms/write", json={
        "tag_id": "HVAC.CHILLER1.CW_SETPOINT", "value": 7.5,
        "actor_role": "SME_L6",
    })
    entries_before = await ledger.fetch_all()
    n_before = len(entries_before)
    request_entry = next(e for e in entries_before if e.action == ACTION_BMS_WRITE_REQUESTED)
    r = client.post(f"/api/bms/revert/{request_entry.entry_id}", json={
        "actor_role": "SME_L6", "user": "cet-01",
    })
    assert r.status_code == 200
    entries_after = await ledger.fetch_all()
    # +3 entries: BMS_REVERT marker + counter-write's BMS_WRITE_REQUESTED + RESULT.
    assert len(entries_after) == n_before + 3
    marker = next(e for e in entries_after if e.action == ACTION_BMS_REVERT)
    assert marker.payload["reverts_entry_id"] == request_entry.entry_id
    assert marker.payload["restoring_value"] == 8.0
    # Chain still verifies
    assert await ledger.verify_chain() is None


async def test_revert_of_revert_is_allowed():
    app, bms, ledger = _build_app()
    client = TestClient(app)
    # 8.0 -> write 7.5 -> revert (back to 8.0) -> revert the counter-write (forward to 7.5).
    client.post("/api/bms/write", json={
        "tag_id": "HVAC.CHILLER1.CW_SETPOINT", "value": 7.5,
        "actor_role": "SME_L6",
    })
    entries = await ledger.fetch_all()
    original_request = next(e for e in entries if e.action == ACTION_BMS_WRITE_REQUESTED)
    client.post(f"/api/bms/revert/{original_request.entry_id}", json={
        "actor_role": "SME_L6",
    })
    assert bms.values["HVAC.CHILLER1.CW_SETPOINT"] == 8.0
    # The counter-write produced its own BMS_WRITE_REQUESTED with
    # source="revert" and prev_value=7.5 (the value seen just before
    # the counter-write executed). Revert THAT.
    entries = await ledger.fetch_all()
    counter_requests = [
        e for e in entries
        if e.action == ACTION_BMS_WRITE_REQUESTED
        and e.payload.get("source") == "revert"
    ]
    assert len(counter_requests) == 1
    counter_request = counter_requests[0]
    r = client.post(f"/api/bms/revert/{counter_request.entry_id}", json={
        "actor_role": "SME_L6",
    })
    assert r.status_code == 200
    # Back to 7.5
    assert bms.values["HVAC.CHILLER1.CW_SETPOINT"] == 7.5
    # Chain still verifies after the double-revert
    assert await ledger.verify_chain() is None


async def test_revert_requires_sme_l6():
    app, _, ledger = _build_app()
    client = TestClient(app)
    client.post("/api/bms/write", json={
        "tag_id": "HVAC.CHILLER1.CW_SETPOINT", "value": 7.5,
        "actor_role": "SME_L6",
    })
    entries = await ledger.fetch_all()
    request_entry = next(e for e in entries if e.action == ACTION_BMS_WRITE_REQUESTED)
    r = client.post(f"/api/bms/revert/{request_entry.entry_id}", json={
        "actor_role": "TECH",
    })
    assert r.status_code == 403


async def test_revert_unknown_entry_id_returns_404():
    app, _, _ = _build_app()
    client = TestClient(app)
    r = client.post(f"/api/bms/revert/{uuid.uuid4()}", json={
        "actor_role": "SME_L6",
    })
    assert r.status_code == 404


async def test_revert_of_non_write_request_returns_422():
    app, _, ledger = _build_app()
    client = TestClient(app)
    # Append a non-write entry directly (e.g. simulate a KEY_ROTATION)
    e = await ledger.append(
        actor="ops", action="KEY_ROTATION",
        payload={"prior_key_version": 1, "new_key_version": 2},
    )
    r = client.post(f"/api/bms/revert/{e.entry_id}", json={
        "actor_role": "SME_L6",
    })
    assert r.status_code == 422
    assert "KEY_ROTATION" in r.json()["detail"]


async def test_revert_of_result_entry_returns_422():
    app, _, ledger = _build_app()
    client = TestClient(app)
    client.post("/api/bms/write", json={
        "tag_id": "HVAC.CHILLER1.CW_SETPOINT", "value": 7.5,
        "actor_role": "SME_L6",
    })
    entries = await ledger.fetch_all()
    result_entry = next(e for e in entries if e.action == ACTION_BMS_WRITE_RESULT)
    r = client.post(f"/api/bms/revert/{result_entry.entry_id}", json={
        "actor_role": "SME_L6",
    })
    assert r.status_code == 422


async def test_revert_missing_prev_value_returns_422():
    """If the original write had no prev_value (e.g. the tag was
    unknown at write time), revert refuses."""
    app, _, ledger = _build_app()
    # Hand-craft an entry whose payload has no prev_value
    e = await ledger.append(
        actor="op", action=ACTION_BMS_WRITE_REQUESTED,
        payload={
            "tag_id": "X.Y.Z",
            "requested_value": 1,
            "prev_value": None,
            "source": "direct",
            "proposal_id": None,
        },
    )
    client = TestClient(app)
    r = client.post(f"/api/bms/revert/{e.entry_id}", json={
        "actor_role": "SME_L6",
    })
    assert r.status_code == 422
    assert "prev_value" in r.json()["detail"]


async def test_revert_chain_links_marker_to_counter_write_via_payload():
    """The BMS_REVERT marker carries enough metadata to reconstruct the
    causal link without scanning the whole chain (audit-tool friendly).
    """
    app, _, ledger = _build_app()
    client = TestClient(app)
    client.post("/api/bms/write", json={
        "tag_id": "HVAC.CHILLER1.CW_SETPOINT", "value": 7.5,
        "actor_role": "SME_L6",
    })
    entries = await ledger.fetch_all()
    request_entry = next(e for e in entries if e.action == ACTION_BMS_WRITE_REQUESTED)
    r = client.post(f"/api/bms/revert/{request_entry.entry_id}", json={
        "actor_role": "SME_L6", "reason": "panel-driven rollback",
    })
    rj = r.json()
    marker_id = rj["revert_marker_entry_id"]
    marker = await ledger.fetch_by_id(marker_id)
    assert marker is not None
    assert marker.payload["reverts_entry_id"] == request_entry.entry_id
    assert marker.payload["restoring_value"] == 8.0
    assert marker.payload["from_value"] == 7.5
    assert marker.payload["reason"] == "panel-driven rollback"
