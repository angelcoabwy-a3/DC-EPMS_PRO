"""
tests/test_bms_write_proposer_chain.py
=======================================
Verification suite for DC-EPMS-MSD-003 (Proposer-chain closure on
``/api/bms/write``) and the wrap_bms_write_fn seam (S-LEDGER-01).

Two layers of coverage:

1. **Wrapper unit tests** — exercise ``wrap_bms_write_fn`` directly with
   an in-memory ledger and a stub BMS write. No HTTP, no FastAPI. These
   confirm the ADR-011 invariants — pre + post entries, prev_value
   capture, proposal_id stamping, exception path.

2. **Endpoint smoke tests** — TestClient against a minimal app that
   mounts ``/api/bms/write`` with the same wiring main.py uses
   (ledger + approval_log + wrapped seam). These confirm the RBAC gate,
   the proposal_id Approval-Log cross-check, and the 4xx error paths.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass

import pytest
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from backend.ledger import (
    ACTION_BMS_WRITE_REQUESTED,
    ACTION_BMS_WRITE_RESULT,
    ForensicLedger,
    InMemoryPersistence,
    reset_proposal_context,
    set_proposal_context,
    wrap_bms_write_fn,
)


# ── Stub BMS used by all tests ───────────────────────────────────────
class StubBMS:
    """Minimal stand-in for BMSConnector for fast unit tests."""

    def __init__(self, initial: dict[str, float]) -> None:
        self.values = dict(initial)
        self.writes: list[tuple[str, float, str]] = []
        self.fail_on: set[str] = set()  # tag_ids that should fail

    def read(self, tag_id: str):
        if tag_id not in self.values:
            return None
        return type("Tag", (), {"current_value": self.values[tag_id]})()

    def write(self, tag_id: str, value, user: str) -> tuple[bool, str]:
        self.writes.append((tag_id, value, user))
        if tag_id in self.fail_on:
            return False, f"stub refuses {tag_id}"
        if tag_id not in self.values:
            return False, f"unknown tag {tag_id}"
        self.values[tag_id] = value
        return True, f"wrote {value} to {tag_id}"


# ── Wrapper unit tests (async — call sync wrapper via to_thread) ─────
def _make_wrapper(bms: StubBMS, source: str = "direct"):
    ledger = ForensicLedger(InMemoryPersistence(), key=b"k" * 32, key_version=1)

    def _raw(tag_id, value, user):
        return bms.write(tag_id, value, user)

    def _prev(tag_id):
        tag = bms.read(tag_id)
        return tag.current_value if tag else None

    wrapped = wrap_bms_write_fn(
        _raw, ledger=ledger, prev_value_reader=_prev,
        source=source, loop=None,
    )
    return ledger, wrapped


async def test_direct_write_appends_pre_and_post_ledger_entries():
    bms = StubBMS({"HVAC.CHILLER1.CW_SETPOINT": 8.0})
    ledger, wrapped = _make_wrapper(bms)

    success, message = await asyncio.to_thread(
        wrapped, "HVAC.CHILLER1.CW_SETPOINT", 7.5, "op-cet-01",
    )
    assert success is True
    entries = await ledger.fetch_all()
    assert len(entries) == 2
    assert entries[0].action == ACTION_BMS_WRITE_REQUESTED
    assert entries[0].payload["tag_id"] == "HVAC.CHILLER1.CW_SETPOINT"
    assert entries[0].payload["requested_value"] == 7.5
    assert entries[0].payload["prev_value"] == 8.0
    assert entries[0].payload["source"] == "direct"
    assert entries[0].payload["proposal_id"] is None
    assert entries[1].action == ACTION_BMS_WRITE_RESULT
    assert entries[1].payload["ref_entry_id"] == entries[0].entry_id
    assert entries[1].payload["success"] is True
    assert "wrote 7.5" in entries[1].payload["message"]


async def test_proposal_id_is_stamped_via_context():
    bms = StubBMS({"HVAC.CHILLER1.CW_SETPOINT": 8.0})
    ledger, wrapped = _make_wrapper(bms, source="optimizer_approval")
    pid = str(uuid.uuid4())

    def _call_with_ctx():
        token = set_proposal_context(pid)
        try:
            return wrapped("HVAC.CHILLER1.CW_SETPOINT", 7.5, "op-cet-01")
        finally:
            reset_proposal_context(token)

    await asyncio.to_thread(_call_with_ctx)

    entries = await ledger.fetch_all()
    assert entries[0].payload["proposal_id"] == pid
    assert entries[0].payload["source"] == "optimizer_approval"


async def test_failed_bms_write_still_appends_result_entry():
    bms = StubBMS({"HVAC.CHILLER1.CW_SETPOINT": 8.0})
    bms.fail_on.add("HVAC.CHILLER1.CW_SETPOINT")
    ledger, wrapped = _make_wrapper(bms)

    success, message = await asyncio.to_thread(
        wrapped, "HVAC.CHILLER1.CW_SETPOINT", 7.5, "op-cet-01",
    )
    assert success is False
    entries = await ledger.fetch_all()
    assert len(entries) == 2
    assert entries[1].payload["success"] is False
    assert "stub refuses" in entries[1].payload["message"]


async def test_inner_fn_exception_still_records_result_entry():
    bms = StubBMS({"HVAC.CHILLER1.CW_SETPOINT": 8.0})
    ledger = ForensicLedger(InMemoryPersistence(), key=b"k" * 32)

    def _explode(tag_id, value, user):
        raise RuntimeError("driver lost link")

    def _prev(tag_id):
        tag = bms.read(tag_id)
        return tag.current_value if tag else None

    wrapped = wrap_bms_write_fn(_explode, ledger=ledger, prev_value_reader=_prev,
                                source="direct", loop=None)
    with pytest.raises(RuntimeError, match="driver lost link"):
        await asyncio.to_thread(wrapped, "HVAC.CHILLER1.CW_SETPOINT", 7.5, "op")
    entries = await ledger.fetch_all()
    assert len(entries) == 2
    assert entries[1].payload["success"] is False
    assert "inner_fn raised" in entries[1].payload["message"]


async def test_prev_value_reader_failure_does_not_block_audit():
    """A flaky prev_value reader must not prevent the audit. The
    pre-entry simply records prev_value=None and the chain continues."""
    bms = StubBMS({"x": 1.0})
    ledger = ForensicLedger(InMemoryPersistence(), key=b"k" * 32)

    def _raw(tag_id, value, user):
        return bms.write(tag_id, value, user)

    def _prev_explodes(tag_id):
        raise RuntimeError("BMS read timeout")

    wrapped = wrap_bms_write_fn(_raw, ledger=ledger,
                                prev_value_reader=_prev_explodes,
                                source="direct", loop=None)
    success, _ = await asyncio.to_thread(wrapped, "x", 2.0, "op")
    assert success is True
    entries = await ledger.fetch_all()
    assert entries[0].payload["prev_value"] is None


async def test_deadlock_refusal_inside_running_loop():
    """When the wrapper is called from inside a running event loop on
    the same thread WITHOUT an explicit ``loop=`` reference, it must
    refuse to proceed instead of deadlocking."""
    bms = StubBMS({"x": 1.0})
    _, wrapped = _make_wrapper(bms)
    with pytest.raises(RuntimeError, match="deadlock|to_thread"):
        wrapped("x", 2.0, "op")


# ── Endpoint tests (TestClient + minimal app) ────────────────────────
@dataclass
class _StubApproval:
    proposal_id: str
    decision: str
    bms_tag_id: str | None
    bms_write_success: bool | None = True


class _StubApprovalLog:
    def __init__(self) -> None:
        self._by_id: dict[str, _StubApproval] = {}

    def add(self, a: _StubApproval) -> None:
        self._by_id[a.proposal_id] = a

    def get(self, proposal_id: str):
        return self._by_id.get(proposal_id)


def _build_test_app() -> tuple[FastAPI, StubBMS, ForensicLedger, _StubApprovalLog]:
    """Construct a minimal FastAPI app that mounts the /api/bms/write
    + /api/bms/revert + /api/ledger/* endpoints with the same wiring
    main.py uses. The full main.py app pulls in dozens of unrelated
    dependencies — this focused app keeps the test surface tight.
    """
    bms = StubBMS({
        "HVAC.CHILLER1.CW_SETPOINT": 8.0,
        "HVAC.CTOWER1.FAN_VFD": 60.0,
    })
    ledger = ForensicLedger(InMemoryPersistence(), key=b"k" * 32, key_version=1)
    approval_log = _StubApprovalLog()

    def _raw_bms_write(tag_id, value, user):
        return bms.write(tag_id, value, user)

    def _prev_value_reader(tag_id):
        tag = bms.read(tag_id)
        return tag.current_value if tag else None

    app = FastAPI()
    # The test app uses loop=None so the wrapper runs the coroutine
    # via asyncio.run inside the worker thread spawned by to_thread.
    app.state.forensic_ledger = ledger
    app.state.optimizer_approval_log = approval_log
    app.state.direct_bms_write_fn = wrap_bms_write_fn(
        _raw_bms_write, ledger=ledger, prev_value_reader=_prev_value_reader,
        source="direct", loop=None,
    )
    app.state.revert_bms_write_fn = wrap_bms_write_fn(
        _raw_bms_write, ledger=ledger, prev_value_reader=_prev_value_reader,
        source="revert", loop=None,
    )

    # Minimal port of /api/bms/write that mirrors main.py logic
    @app.post("/api/bms/write")
    async def write_bms_tag(request: Request, payload: dict = Body(...)):
        from backend.cmms_models import role_rank as _role_rank
        _bms_role = payload.get("actor_role")
        if _role_rank(_bms_role) < 6:
            raise HTTPException(403, f"BMS write requires SME_L6; actor_role={_bms_role!r}")
        tag_id = payload.get("tag_id")
        value = payload.get("value")
        user = payload.get("user", "dashboard-user")
        proposal_id = payload.get("proposal_id")
        if not tag_id:
            raise HTTPException(400, "tag_id required")
        if proposal_id is not None:
            approval = request.app.state.optimizer_approval_log.get(proposal_id)
            if approval is None:
                raise HTTPException(404, f"proposal_id={proposal_id!r} not found")
            if approval.decision != "approved":
                raise HTTPException(409, f"decision={approval.decision!r}")
            if approval.bms_tag_id and approval.bms_tag_id != tag_id:
                raise HTTPException(409, "tag mismatch")
        direct_fn = request.app.state.direct_bms_write_fn
        token = set_proposal_context(proposal_id)
        try:
            success, message = await asyncio.to_thread(direct_fn, tag_id, value, user)
        finally:
            reset_proposal_context(token)
        if not success:
            raise HTTPException(400, message)
        return {"success": True, "message": message, "tag_id": tag_id,
                "new_value": value, "proposal_id": proposal_id}

    return app, bms, ledger, approval_log


async def test_endpoint_rejects_non_sme_l6():
    app, _, _, _ = _build_test_app()
    with TestClient(app) as client:
        r = client.post("/api/bms/write", json={
        "tag_id": "HVAC.CHILLER1.CW_SETPOINT",
        "value": 7.5,
        "actor_role": "TECH",
    })
    assert r.status_code == 403


async def test_endpoint_direct_write_records_ledger_entries():
    app, bms, ledger, _ = _build_test_app()
    with TestClient(app) as client:
        r = client.post("/api/bms/write", json={
        "tag_id": "HVAC.CHILLER1.CW_SETPOINT",
        "value": 7.5,
        "actor_role": "SME_L6",
        "user": "cet-01",
    })
    assert r.status_code == 200
    assert r.json()["new_value"] == 7.5
    entries = await ledger.fetch_all()
    assert len(entries) == 2
    assert entries[0].payload["source"] == "direct"
    assert entries[0].payload["prev_value"] == 8.0
    assert bms.values["HVAC.CHILLER1.CW_SETPOINT"] == 7.5


async def test_endpoint_rejects_unknown_proposal_id():
    app, _, _, _ = _build_test_app()
    with TestClient(app) as client:
        r = client.post("/api/bms/write", json={
        "tag_id": "HVAC.CHILLER1.CW_SETPOINT",
        "value": 7.5,
        "actor_role": "SME_L6",
        "proposal_id": "nope-12345",
    })
    assert r.status_code == 404


async def test_endpoint_rejects_unapproved_proposal_id():
    app, _, _, approval_log = _build_test_app()
    pid = str(uuid.uuid4())
    approval_log.add(_StubApproval(proposal_id=pid, decision="rejected",
                                    bms_tag_id="HVAC.CHILLER1.CW_SETPOINT"))
    with TestClient(app) as client:
        r = client.post("/api/bms/write", json={
        "tag_id": "HVAC.CHILLER1.CW_SETPOINT",
        "value": 7.5,
        "actor_role": "SME_L6",
        "proposal_id": pid,
    })
    assert r.status_code == 409


async def test_endpoint_rejects_proposal_tag_mismatch():
    app, _, _, approval_log = _build_test_app()
    pid = str(uuid.uuid4())
    approval_log.add(_StubApproval(proposal_id=pid, decision="approved",
                                    bms_tag_id="HVAC.CTOWER1.FAN_VFD"))
    with TestClient(app) as client:
        r = client.post("/api/bms/write", json={
        "tag_id": "HVAC.CHILLER1.CW_SETPOINT",  # ← different tag
        "value": 7.5,
        "actor_role": "SME_L6",
        "proposal_id": pid,
    })
    assert r.status_code == 409


async def test_endpoint_accepts_approved_proposal_and_stamps_ledger():
    app, _, ledger, approval_log = _build_test_app()
    pid = str(uuid.uuid4())
    approval_log.add(_StubApproval(proposal_id=pid, decision="approved",
                                    bms_tag_id="HVAC.CHILLER1.CW_SETPOINT"))
    with TestClient(app) as client:
        r = client.post("/api/bms/write", json={
        "tag_id": "HVAC.CHILLER1.CW_SETPOINT",
        "value": 7.5,
        "actor_role": "SME_L6",
        "user": "cet-01",
        "proposal_id": pid,
    })
    assert r.status_code == 200
    entries = await ledger.fetch_all()
    assert entries[0].payload["proposal_id"] == pid
    assert await ledger.verify_chain() is None


async def test_endpoint_400_on_missing_tag_id():
    app, _, _, _ = _build_test_app()
    with TestClient(app) as client:
        r = client.post("/api/bms/write", json={
        "value": 7.5, "actor_role": "SME_L6",
    })
    assert r.status_code == 400


async def test_ts_field_present_and_recent_in_ledger_entry():
    """Belt-and-suspenders: confirm ts is captured monotonically."""
    app, _, ledger, _ = _build_test_app()
    client = TestClient(app)
    t0 = time.time()
    r = client.post("/api/bms/write", json={
        "tag_id": "HVAC.CHILLER1.CW_SETPOINT",
        "value": 7.0,
        "actor_role": "SME_L6",
    })
    t1 = time.time()
    assert r.status_code == 200
    entries = await ledger.fetch_all()
    assert t0 <= entries[0].ts.timestamp() <= t1
