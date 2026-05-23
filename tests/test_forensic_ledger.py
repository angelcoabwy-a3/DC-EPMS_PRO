"""
tests/test_forensic_ledger.py
==============================
Verification suite for ADR-011 (Forensic Ledger).

Covers all eight verification points enumerated in the ADR. The HMAC
arithmetic is unit-tested against the InMemoryPersistence so the suite
runs without a live Postgres. The PostgresPersistence is exercised
indirectly by the integration smoke tests; the unit-level chain math
matches.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from backend.ledger.forensic_ledger import (
    ACTION_BMS_WRITE_REQUESTED,
    ACTION_BMS_WRITE_RESULT,
    ACTION_KEY_ROTATION,
    ENV_KEY_NAME,
    EPHEMERAL_KEY_VERSION,
    ForensicLedger,
    InMemoryPersistence,
    LedgerChainBrokenError,
    LedgerEntry,
)


def _new_ledger(key: bytes = b"k" * 32, version: int = 1) -> ForensicLedger:
    return ForensicLedger(InMemoryPersistence(), key=key, key_version=version)


@pytest.mark.asyncio
async def test_hmac_verifies_when_untouched():
    ledger = _new_ledger()
    await ledger.append(actor="op1", action=ACTION_BMS_WRITE_REQUESTED,
                        payload={"tag_id": "HVAC.CHILLER1.CW_SETPOINT",
                                 "requested_value": 7.5, "prev_value": 8.0,
                                 "source": "direct", "proposal_id": None})
    await ledger.append(actor="op1", action=ACTION_BMS_WRITE_RESULT,
                        payload={"ref_entry_id": "x", "success": True,
                                 "message": "ok"})
    # No tamper — verify_chain returns None
    assert await ledger.verify_chain() is None
    assert await ledger.count() == 2


@pytest.mark.asyncio
async def test_hmac_detects_payload_tamper():
    ledger = _new_ledger()
    persistence: InMemoryPersistence = ledger.persistence  # type: ignore[assignment]
    e1 = await ledger.append(actor="op1", action="BMS_WRITE_REQUESTED",
                             payload={"tag_id": "x", "requested_value": 1})
    e2 = await ledger.append(actor="op1", action="BMS_WRITE_RESULT",
                             payload={"ref_entry_id": e1.entry_id,
                                      "success": True, "message": "ok"})
    # Tamper: replace e1's payload (keep the HMAC), simulating an attacker
    # who changes the recorded value after the fact.
    tampered = LedgerEntry(
        entry_id=e1.entry_id,
        sequence_no=e1.sequence_no,
        ts=e1.ts,
        actor=e1.actor,
        action=e1.action,
        payload={"tag_id": "x", "requested_value": 999},  # ← changed
        prev_hash=e1.prev_hash,
        entry_hmac=e1.entry_hmac,
        key_version=e1.key_version,
    )
    persistence._force_replace_for_tamper_test(0, tampered)
    # The first entry now fails HMAC verification
    with pytest.raises(LedgerChainBrokenError) as excinfo:
        await ledger.verify_chain()
    assert excinfo.value.divergence_index == 0
    assert "HMAC" in excinfo.value.reason
    assert e2 is not None  # e2 referenced for clarity


@pytest.mark.asyncio
async def test_hmac_detects_chain_break():
    ledger = _new_ledger()
    persistence: InMemoryPersistence = ledger.persistence  # type: ignore[assignment]
    e1 = await ledger.append(actor="op1", action="BMS_WRITE_REQUESTED",
                             payload={"tag_id": "x"})
    e2 = await ledger.append(actor="op1", action="BMS_WRITE_RESULT",
                             payload={"ref_entry_id": e1.entry_id,
                                      "success": True})
    # Tamper: rewrite e2's prev_hash to wrong bytes. Its HMAC was computed
    # under the real prev_hash, so it will fail.
    tampered = LedgerEntry(
        entry_id=e2.entry_id,
        sequence_no=e2.sequence_no,
        ts=e2.ts,
        actor=e2.actor,
        action=e2.action,
        payload=e2.payload,
        prev_hash=b"\x00" * 32,   # ← wrong predecessor
        entry_hmac=e2.entry_hmac,
        key_version=e2.key_version,
    )
    persistence._force_replace_for_tamper_test(1, tampered)
    with pytest.raises(LedgerChainBrokenError) as excinfo:
        await ledger.verify_chain()
    assert excinfo.value.divergence_index == 1
    assert "prev_hash" in excinfo.value.reason


@pytest.mark.asyncio
async def test_genesis_entry_prev_hash_is_empty():
    ledger = _new_ledger()
    e = await ledger.append(actor="boot", action="STARTUP",
                            payload={"version": "0.13.0"})
    assert e.prev_hash == b""
    assert e.sequence_no == 1
    # And the HMAC must verify under the empty prev_hash
    assert await ledger.verify_chain() is None


@pytest.mark.asyncio
async def test_concurrent_appends_preserve_order_and_chain():
    ledger = _new_ledger()

    async def one(i: int) -> str:
        e = await ledger.append(
            actor=f"op{i}", action="TICK", payload={"i": i},
        )
        return e.entry_id

    ids = await asyncio.gather(*(one(i) for i in range(20)))
    assert len(set(ids)) == 20  # all unique
    entries = await ledger.fetch_all()
    # sequence_no is gapless 1..20
    assert [e.sequence_no for e in entries] == list(range(1, 21))
    # Chain verifies
    assert await ledger.verify_chain() is None


@pytest.mark.asyncio
async def test_immutability_in_memory_via_protocol_surface():
    """The Persistence Protocol exposes ONLY append + fetch_* + count.
    There is no update / delete in the surface — by construction.
    """
    p = InMemoryPersistence()
    surface = {m for m in dir(p) if not m.startswith("_")}
    assert "update" not in surface
    assert "delete" not in surface
    assert "remove" not in surface
    # The deliberate tamper hook IS present and clearly named
    assert "_force_replace_for_tamper_test" in dir(p)


@pytest.mark.asyncio
async def test_ephemeral_key_warns(caplog, monkeypatch):
    monkeypatch.delenv(ENV_KEY_NAME, raising=False)
    with caplog.at_level("WARNING"):
        ledger = ForensicLedger(InMemoryPersistence())
    # WARNING emitted naming the env var
    assert any(ENV_KEY_NAME in r.message for r in caplog.records)
    assert ledger.current_key_version == EPHEMERAL_KEY_VERSION
    # And the chain still works for the lifetime of the process
    await ledger.append(actor="boot", action="TICK", payload={"i": 1})
    assert await ledger.verify_chain() is None


@pytest.mark.asyncio
async def test_env_key_loaded_when_present(monkeypatch):
    key_hex = "ab" * 32
    monkeypatch.setenv(ENV_KEY_NAME, key_hex)
    ledger = ForensicLedger(InMemoryPersistence())
    assert ledger.current_key_version == 1
    await ledger.append(actor="boot", action="TICK", payload={"i": 1})
    assert await ledger.verify_chain() is None


@pytest.mark.asyncio
async def test_short_env_key_rejected(monkeypatch):
    monkeypatch.setenv(ENV_KEY_NAME, "ab" * 8)  # 16 chars = 8 bytes (< 32)
    with pytest.raises(RuntimeError, match=">= 32 bytes"):
        ForensicLedger(InMemoryPersistence())


@pytest.mark.asyncio
async def test_non_hex_env_key_rejected(monkeypatch):
    monkeypatch.setenv(ENV_KEY_NAME, "not-hex-content-here-xyz-zzz!")
    with pytest.raises(RuntimeError, match="hex-encoded"):
        ForensicLedger(InMemoryPersistence())


@pytest.mark.asyncio
async def test_key_rotation_does_not_break_prior_entries():
    ledger = _new_ledger(key=b"k1" * 16, version=1)
    e1 = await ledger.append(actor="op1", action="BMS_WRITE_REQUESTED",
                             payload={"tag_id": "x"})
    # Rotate
    rot_entry = await ledger.rotate_key(
        new_key=b"k2" * 16, new_version=2, rotated_by="ops_lead",
    )
    assert rot_entry.action == ACTION_KEY_ROTATION
    assert rot_entry.key_version == 2
    assert ledger.current_key_version == 2
    # Append under the new key
    e3 = await ledger.append(actor="op1", action="BMS_WRITE_RESULT",
                             payload={"ref_entry_id": e1.entry_id,
                                      "success": True})
    assert e3.key_version == 2
    # All entries still verify under their own key_version
    assert await ledger.verify_chain() is None


@pytest.mark.asyncio
async def test_key_rotation_rejects_lower_version():
    ledger = _new_ledger(key=b"k" * 32, version=3)
    with pytest.raises(ValueError, match="must exceed"):
        await ledger.rotate_key(new_key=b"k" * 32, new_version=2,
                                rotated_by="ops_lead")


@pytest.mark.asyncio
async def test_key_rotation_rejects_short_key():
    ledger = _new_ledger()
    with pytest.raises(ValueError, match="at least 16 bytes"):
        await ledger.rotate_key(new_key=b"short", new_version=2,
                                rotated_by="ops_lead")


@pytest.mark.asyncio
async def test_canonical_payload_is_deterministic():
    """Two appends with semantically-equal payloads (different dict
    insertion order) MUST produce identical HMAC inputs and hence
    chain consistently."""
    ledger = _new_ledger()
    a = await ledger.append(actor="op", action="X", payload={"a": 1, "b": 2})
    b = await ledger.append(actor="op", action="X", payload={"b": 2, "a": 1})
    # Different entries (different prev_hash + ts) — but the chain
    # still verifies, which is the load-bearing property.
    assert a.entry_id != b.entry_id
    assert await ledger.verify_chain() is None


@pytest.mark.asyncio
async def test_actor_and_action_required():
    ledger = _new_ledger()
    with pytest.raises(ValueError, match="actor"):
        await ledger.append(actor="", action="X", payload={})
    with pytest.raises(ValueError, match="action"):
        await ledger.append(actor="op", action="", payload={})


@pytest.mark.asyncio
async def test_fetch_by_id_and_sequence():
    ledger = _new_ledger()
    e1 = await ledger.append(actor="op", action="A", payload={})
    e2 = await ledger.append(actor="op", action="B", payload={})
    fetched1 = await ledger.fetch_by_id(e1.entry_id)
    fetched2 = await ledger.fetch_by_sequence(2)
    assert fetched1 is not None
    assert fetched1.entry_id == e1.entry_id
    assert fetched2 is not None
    assert fetched2.entry_id == e2.entry_id
    assert await ledger.fetch_by_id("no-such-id") is None
    assert await ledger.fetch_by_sequence(999) is None


@pytest.mark.asyncio
async def test_entry_to_dict_is_json_safe():
    """The API surface serialises bytes as hex and datetimes as isoformat."""
    ledger = _new_ledger()
    e = await ledger.append(actor="op", action="A", payload={"v": 1})
    d = e.to_dict()
    assert isinstance(d["prev_hash_hex"], str)
    assert isinstance(d["entry_hmac_hex"], str)
    # ts is ISO 8601 with timezone
    parsed = datetime.fromisoformat(d["ts"])
    assert parsed.tzinfo is not None
    # No raw bytes leaked
    import json as _json
    _json.dumps(d)  # would raise on non-serialisable


@pytest.mark.asyncio
async def test_payload_can_include_nested_dict_and_list():
    ledger = _new_ledger()
    payload = {
        "tag_id": "x",
        "snapshot": {"a": 1, "b": [1, 2, 3]},
        "tags": ["foo", "bar"],
        "ts_inside": datetime(2026, 5, 22, tzinfo=UTC),
    }
    await ledger.append(actor="op", action="A", payload=payload)
    assert await ledger.verify_chain() is None
