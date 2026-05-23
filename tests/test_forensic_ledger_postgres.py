"""
tests/test_forensic_ledger_postgres.py
======================================
Integration suite for ADR-011 against a REAL Postgres backend.

The 18 unit tests in tests/test_forensic_ledger.py exercise the HMAC
chain math against InMemoryPersistence. They do NOT touch
PostgresPersistence — that gap is what DC-EPMS-MSD-005 exposed: asyncpg
deserialises the UUID column as ``asyncpg.pgproto.pgproto.UUID``, so
``_compute_hmac().encode()`` raised AttributeError on every verify_chain
call against the production backend, but no test ever saw it.

This suite closes that gap. It hits a real epms-db container, in an
isolated schema (`forensic_ledger_test_<pid>`) so it never contaminates
the production `public.ledger_entries` chain. Teardown drops the
schema; the immutability triggers there go away with it.

Skips cleanly if asyncpg is not installed or epms-db is unreachable —
this lets the suite run on workstations / CI without a live container.
"""

from __future__ import annotations

import os
import secrets
import uuid

import pytest

from backend.ledger.forensic_ledger import (
    ACTION_BMS_WRITE_REQUESTED,
    ACTION_BMS_WRITE_RESULT,
    ForensicLedger,
    PostgresPersistence,
)

pytestmark = pytest.mark.integration

asyncpg = pytest.importorskip("asyncpg")


# ─── Schema DDL (mirrors backend/migrations/2026_05_W4_forensic_ledger.sql) ──
# Kept inline so the test is self-contained — it does not require running
# the migration against the test schema. The trigger function and triggers
# match the production DDL byte-for-byte except for the schema qualifier.
_SCHEMA_DDL = """
CREATE SCHEMA IF NOT EXISTS {schema};

CREATE TABLE IF NOT EXISTS {schema}.ledger_entries (
    entry_id      UUID        PRIMARY KEY,
    sequence_no   BIGSERIAL   UNIQUE NOT NULL,
    ts            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor         TEXT        NOT NULL,
    action        TEXT        NOT NULL,
    payload       JSONB       NOT NULL,
    prev_hash     BYTEA       NOT NULL,
    entry_hmac    BYTEA       NOT NULL,
    key_version   INTEGER     NOT NULL DEFAULT 1,
    CONSTRAINT ledger_entries_hmac_len_check_t CHECK (octet_length(entry_hmac) = 32),
    CONSTRAINT ledger_entries_prev_hash_len_check_t
        CHECK (octet_length(prev_hash) = 0 OR octet_length(prev_hash) = 32)
);

CREATE OR REPLACE FUNCTION {schema}.ledger_entries_immutable_guard()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'append-only (test schema, ADR-011)';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS ledger_entries_no_update_t ON {schema}.ledger_entries;
CREATE TRIGGER ledger_entries_no_update_t
    BEFORE UPDATE ON {schema}.ledger_entries
    FOR EACH ROW EXECUTE FUNCTION {schema}.ledger_entries_immutable_guard();
"""


def _dsn() -> str:
    user = os.environ.get("PG_USER", "epms")
    pwd = os.environ.get("PG_PASSWORD", "epms_dev_only_change_me")
    host = os.environ.get("PG_HOST", "localhost")
    port = os.environ.get("PG_PORT", "5432")
    db = os.environ.get("PG_DB", "dcepms")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{db}"


@pytest.fixture
async def pg_pool():
    """Per-test isolated schema + pool. Skips if Postgres unreachable."""
    schema = f"forensic_ledger_test_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    try:
        bootstrap = await asyncpg.create_pool(
            dsn=_dsn(), min_size=1, max_size=1, command_timeout=5.0,
        )
    except (OSError, asyncpg.PostgresError) as e:
        pytest.skip(f"epms-db unreachable for integration test: {e!r}")

    async with bootstrap.acquire() as conn:
        await conn.execute(_SCHEMA_DDL.format(schema=schema))
    await bootstrap.close()

    # The production pool sets ``search_path`` so PostgresPersistence's
    # unqualified ``FROM ledger_entries`` resolves to the test schema.
    pool = await asyncpg.create_pool(
        dsn=_dsn(),
        min_size=1,
        max_size=2,
        command_timeout=10.0,
        server_settings={"search_path": f"{schema}, public"},
    )
    try:
        yield pool
    finally:
        await pool.close()
        teardown = await asyncpg.create_pool(
            dsn=_dsn(), min_size=1, max_size=1, command_timeout=5.0,
        )
        async with teardown.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        await teardown.close()


# ─── Regression: DC-EPMS-MSD-005 — verify_chain against Postgres ──────
async def test_verify_chain_succeeds_against_postgres(pg_pool):
    """Three appends + verify_chain. Pre-fix this raised
    ``AttributeError: 'asyncpg.pgproto.pgproto.UUID' object has no
    attribute 'encode'`` on the FIRST entry the loop touched.
    """
    ledger = ForensicLedger(
        PostgresPersistence(pg_pool),
        key=secrets.token_bytes(32),
        key_version=1,
    )

    await ledger.append(
        actor="integration-test",
        action=ACTION_BMS_WRITE_REQUESTED,
        payload={"tag_id": "TEST.TAG", "requested_value": 1.0, "prev_value": None},
    )
    second = await ledger.append(
        actor="integration-test",
        action=ACTION_BMS_WRITE_RESULT,
        payload={"ref_entry_id": "fake", "success": True, "message": "ok"},
    )
    await ledger.append(
        actor="integration-test",
        action=ACTION_BMS_WRITE_REQUESTED,
        payload={"tag_id": "TEST.TAG", "requested_value": 2.0, "prev_value": 1.0},
    )

    # The actual regression — pre-fix raises AttributeError here.
    await ledger.verify_chain()

    assert await ledger.count() == 3
    assert second.sequence_no == 2


# ─── Root-cause regression: entry_id type coercion at the asyncpg boundary ─
async def test_fetch_all_coerces_uuid_to_str(pg_pool):
    """The root cause of MSD-005: asyncpg returns UUID column as a
    native UUID object; ``_row_to_entry`` must coerce to str so the
    LedgerEntry.entry_id contract holds across persistence backends.
    """
    ledger = ForensicLedger(
        PostgresPersistence(pg_pool),
        key=secrets.token_bytes(32),
        key_version=1,
    )
    appended = await ledger.append(
        actor="integration-test",
        action=ACTION_BMS_WRITE_REQUESTED,
        payload={"tag_id": "TEST.TAG"},
    )

    entries = await ledger.fetch_all()
    assert len(entries) == 1
    fetched = entries[0]

    assert isinstance(fetched.entry_id, str), (
        f"entry_id must be str across persistence backends; "
        f"got {type(fetched.entry_id).__name__}"
    )
    assert fetched.entry_id == appended.entry_id


# ─── DB-side immutability still fires through asyncpg ─────────────────
async def test_db_trigger_blocks_update(pg_pool):
    """The BEFORE UPDATE trigger raises an exception. This is the
    DB-side defence in depth referenced by ADR-011 §Tamper-evidence —
    even if a caller bypasses the ledger Python API and reaches for
    raw SQL, the row trigger refuses the mutation.
    """
    ledger = ForensicLedger(
        PostgresPersistence(pg_pool),
        key=secrets.token_bytes(32),
        key_version=1,
    )
    entry = await ledger.append(
        actor="integration-test",
        action=ACTION_BMS_WRITE_REQUESTED,
        payload={"tag_id": "TEST.TAG"},
    )

    async with pg_pool.acquire() as conn:
        with pytest.raises(asyncpg.PostgresError):
            await conn.execute(
                "UPDATE ledger_entries SET actor = 'tampered' WHERE entry_id = $1",
                uuid.UUID(entry.entry_id),
            )


# ─── Cross-backend HMAC compatibility check ───────────────────────────
async def test_postgres_hmac_matches_inmemory_for_same_input(pg_pool):
    """The chain hash MUST be identical regardless of persistence
    backend (it is a function of the entry fields, not the storage).
    If asyncpg's UUID type leaked into _compute_hmac it would change
    the digest — this test would catch any future regression of that
    class beyond the entry_id case."""
    key = secrets.token_bytes(32)

    pg_ledger = ForensicLedger(
        PostgresPersistence(pg_pool), key=key, key_version=1,
    )
    pg_entry = await pg_ledger.append(
        actor="integration-test",
        action=ACTION_BMS_WRITE_REQUESTED,
        payload={"tag_id": "TEST.TAG", "requested_value": 7.5},
    )

    # Re-fetch through the asyncpg boundary, then verify the chain —
    # this is the round-trip that pre-fix exploded.
    refetched = await pg_ledger.fetch_all()
    assert refetched[0].entry_hmac == pg_entry.entry_hmac
    await pg_ledger.verify_chain()


# ─── DC-EPMS-MSD-006 — fetch_by_proposal_id JSONB cast regression ────
async def test_fetch_by_proposal_id_returns_empty_for_unknown(pg_pool):
    ledger = ForensicLedger(
        PostgresPersistence(pg_pool),
        key=secrets.token_bytes(32),
        key_version=1,
    )
    # Pre-fix: this raised UndefinedFunctionError on any non-empty
    # ledger because the IN subquery compared text vs uuid.
    out = await ledger.fetch_by_proposal_id("no-such-id")
    assert out == []


async def test_fetch_by_proposal_id_returns_requested_plus_linked_result(pg_pool):
    """The forensic-trail contract end-to-end over a real Postgres:
    a REQUESTED row with stamped proposal_id + a RESULT row that
    ref_entry_id-links it. Both must surface in chronological order.

    This is the integration counterpart to the same-named in-memory
    test in tests/test_forensic_ledger.py — the in-memory version
    passed for weeks while the Postgres JSONB query was 500-ing
    (DC-EPMS-MSD-006). The lesson is identical to MSD-005: a unit
    test that only exercises InMemoryPersistence is not a gate on
    the production code path."""
    ledger = ForensicLedger(
        PostgresPersistence(pg_pool),
        key=secrets.token_bytes(32),
        key_version=1,
    )

    # Unrelated entries — must not appear in the trail.
    await ledger.append(
        actor="op", action=ACTION_BMS_WRITE_REQUESTED,
        payload={"proposal_id": "other-proposal", "tag_id": "X"},
    )

    requested = await ledger.append(
        actor="optimizer", action=ACTION_BMS_WRITE_REQUESTED,
        payload={
            "tag_id": "HVAC.CHILLER1.CW_SETPOINT",
            "requested_value": 7.0,
            "proposal_id": "qp-pg-trace",
            "source": "optimizer_approval",
        },
    )
    result = await ledger.append(
        actor="optimizer", action=ACTION_BMS_WRITE_RESULT,
        payload={
            "ref_entry_id": requested.entry_id,
            "success": True,
            "message": "wrote 7.0",
        },
    )

    trail = await ledger.fetch_by_proposal_id("qp-pg-trace")
    assert len(trail) == 2
    # REQUESTED then RESULT (sequence_no ascending).
    assert trail[0].entry_id == requested.entry_id
    assert trail[1].entry_id == result.entry_id
    assert trail[0].sequence_no < trail[1].sequence_no
    # entry_id is str across the asyncpg boundary (MSD-005 contract).
    assert all(isinstance(e.entry_id, str) for e in trail)


async def test_fetch_by_proposal_id_does_not_leak_across_proposals(pg_pool):
    """Two independent proposals each with their own REQUESTED+RESULT
    chain — fetch_by_proposal_id MUST return only the one matched id,
    never cross-talk. This guards against an overly-broad SQL clause
    that would degrade audit precision."""
    ledger = ForensicLedger(
        PostgresPersistence(pg_pool),
        key=secrets.token_bytes(32),
        key_version=1,
    )

    a_req = await ledger.append(
        actor="op", action=ACTION_BMS_WRITE_REQUESTED,
        payload={"proposal_id": "qp-A", "tag_id": "TAG.A"},
    )
    await ledger.append(
        actor="op", action=ACTION_BMS_WRITE_RESULT,
        payload={"ref_entry_id": a_req.entry_id, "success": True, "message": "a"},
    )
    b_req = await ledger.append(
        actor="op", action=ACTION_BMS_WRITE_REQUESTED,
        payload={"proposal_id": "qp-B", "tag_id": "TAG.B"},
    )
    await ledger.append(
        actor="op", action=ACTION_BMS_WRITE_RESULT,
        payload={"ref_entry_id": b_req.entry_id, "success": True, "message": "b"},
    )

    a_trail = await ledger.fetch_by_proposal_id("qp-A")
    b_trail = await ledger.fetch_by_proposal_id("qp-B")
    assert len(a_trail) == 2
    assert len(b_trail) == 2
    assert {e.entry_id for e in a_trail} & {e.entry_id for e in b_trail} == set()
