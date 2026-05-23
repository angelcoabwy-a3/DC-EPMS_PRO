"""
backend/ledger/forensic_ledger.py
=================================
Forensic Ledger — append-only, HMAC-chained audit of control-surface writes.

Source-of-truth: ``docs/adr/ADR-011-forensic-ledger.md``.

The chain construction (RFC 6962-inspired, single-tenant simplification):

    entry_hmac[n] = HMAC-SHA256(
        key[version],
        prev_hash[n] || entry_id[n] || ts_iso[n] || actor[n]
            || action[n] || sha256(canonical_json(payload[n]))
    )
    prev_hash[n+1] = entry_hmac[n]
    prev_hash[0]   = b""              (genesis convention)

Tamper-evidence
---------------
Any modification of any field of any prior entry invalidates that entry's
HMAC. Any modification of ``prev_hash`` invalidates the chain at that
entry. ``verify_chain()`` walks the persisted entries in order and
returns the index of the first divergence (or ``None`` if the chain is
clean).

Persistence
-----------
Two backends share the ``Persistence`` Protocol:

* ``InMemoryPersistence`` — unit-test backend. Still enforces append-only
  (its ``_force_update`` / ``_force_delete`` helpers exist *only* so tests
  can probe the chain's tamper-detection — they raise
  ``LedgerImmutabilityError`` when called via the public surface).
* ``PostgresPersistence`` — production backend. Reads/writes the
  ``ledger_entries`` hypertable defined by
  ``backend/migrations/2026_05_W4_forensic_ledger.sql``. DB-side
  immutability is enforced by ``BEFORE UPDATE / BEFORE DELETE`` triggers
  that ``RAISE EXCEPTION`` — Python never gets the chance to mutate.

Key management
--------------
Reads ``DC_EPMS_LEDGER_HMAC_KEY`` (hex-encoded, 32 bytes => 64 hex chars).
When absent, generates an ephemeral key and emits a loud ``WARNING`` log.
Ephemeral entries are tagged with ``key_version=0`` (reserved); a process
restart invalidates verification — by design, this forces production
deployments to set the env variable.

ADR-006 alignment
-----------------
The ledger is read by inspection / audit tooling and written by the
single ``wrap_bms_write_fn`` seam. AI agents have no API surface that
lets them ``append`` outside that seam — this is enforced by code
review, not by runtime — but the seam ALSO ensures pre-write +
post-write entries are emitted whether the caller is the Optimizer
approval flow or the direct ``/api/bms/write`` endpoint.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

log = logging.getLogger(__name__)


# ─── Action vocabulary ────────────────────────────────────────────────
ACTION_BMS_WRITE_REQUESTED = "BMS_WRITE_REQUESTED"
ACTION_BMS_WRITE_RESULT = "BMS_WRITE_RESULT"
ACTION_BMS_REVERT = "BMS_REVERT"
ACTION_KEY_ROTATION = "KEY_ROTATION"

# Key version 0 is reserved for the ephemeral dev key. Production keys
# start at 1 and increment on rotation.
EPHEMERAL_KEY_VERSION = 0
ENV_KEY_NAME = "DC_EPMS_LEDGER_HMAC_KEY"


# ─── Errors ───────────────────────────────────────────────────────────
class LedgerImmutabilityError(RuntimeError):
    """Raised when a caller attempts to update or delete a ledger entry."""


class LedgerChainBrokenError(RuntimeError):
    """Raised by ``verify_chain()`` when a tamper or chain break is detected.

    Attributes
    ----------
    divergence_index : int
        Zero-based index of the first entry that fails verification.
    reason : str
        Human-readable explanation (e.g. ``"HMAC mismatch"`` /
        ``"prev_hash does not match predecessor's entry_hmac"``).
    """

    def __init__(self, divergence_index: int, reason: str):
        super().__init__(f"chain broken at index {divergence_index}: {reason}")
        self.divergence_index = divergence_index
        self.reason = reason


# ─── Data classes ─────────────────────────────────────────────────────
@dataclass(frozen=True)
class LedgerEntry:
    """One immutable entry in the forensic chain.

    Field ordering MATTERS for the canonical HMAC input — do not reorder.
    """

    entry_id: str             # UUID v4 string
    sequence_no: int          # gapless monotonic (1, 2, 3, ...)
    ts: datetime              # timezone-aware UTC
    actor: str                # operator id, agent id, or "system"
    action: str               # one of the ACTION_* constants (or extension)
    payload: dict[str, Any]   # JSON-serialisable; canonicalised on hash
    prev_hash: bytes          # 32 bytes, b"" for genesis
    entry_hmac: bytes         # 32 bytes (HMAC-SHA256)
    key_version: int          # 0 = ephemeral; >=1 = configured

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe dict for API responses. Bytes are hex-encoded."""
        return {
            "entry_id": self.entry_id,
            "sequence_no": self.sequence_no,
            "ts": self.ts.isoformat(),
            "actor": self.actor,
            "action": self.action,
            "payload": self.payload,
            "prev_hash_hex": self.prev_hash.hex(),
            "entry_hmac_hex": self.entry_hmac.hex(),
            "key_version": self.key_version,
        }


# ─── Persistence protocol ─────────────────────────────────────────────
@runtime_checkable
class Persistence(Protocol):
    """Storage seam for ``ForensicLedger``.

    Implementations MUST be append-only. ``update`` / ``delete`` of a
    persisted entry MUST raise ``LedgerImmutabilityError`` — even though
    the public ledger surface never calls them, defence-in-depth.
    """

    async def append(self, entry: LedgerEntry) -> None: ...

    async def fetch_all(self) -> list[LedgerEntry]: ...

    async def fetch_last(self) -> LedgerEntry | None: ...

    async def fetch_by_id(self, entry_id: str) -> LedgerEntry | None: ...

    async def fetch_by_sequence(self, sequence_no: int) -> LedgerEntry | None: ...

    async def fetch_by_proposal_id(
        self, proposal_id: str,
    ) -> list[LedgerEntry]: ...

    async def count(self) -> int: ...


# ─── In-memory persistence (tests) ────────────────────────────────────
class InMemoryPersistence:
    """List-backed persistence. Append-only via the public API.

    Tests that need to *simulate* tamper (to verify ``verify_chain()``
    catches it) reach into ``_force_replace_for_tamper_test`` — explicitly
    named so its purpose is unambiguous in grep / code review.
    """

    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []
        self._lock = threading.Lock()

    async def append(self, entry: LedgerEntry) -> None:
        # Genuine append-only: the public surface NEVER mutates an entry.
        with self._lock:
            self._entries.append(entry)

    async def fetch_all(self) -> list[LedgerEntry]:
        with self._lock:
            return list(self._entries)

    async def fetch_last(self) -> LedgerEntry | None:
        with self._lock:
            return self._entries[-1] if self._entries else None

    async def fetch_by_id(self, entry_id: str) -> LedgerEntry | None:
        with self._lock:
            for e in self._entries:
                if e.entry_id == entry_id:
                    return e
        return None

    async def fetch_by_sequence(self, sequence_no: int) -> LedgerEntry | None:
        with self._lock:
            for e in self._entries:
                if e.sequence_no == sequence_no:
                    return e
        return None

    async def fetch_by_proposal_id(
        self, proposal_id: str,
    ) -> list[LedgerEntry]:
        """E5.D — forensic-trail query. Returns every entry that links
        to ``proposal_id`` in chronological order:

          * ``BMS_WRITE_REQUESTED`` rows whose ``payload.proposal_id``
            matches (the proposer-pattern stamp from
            ``set_proposal_context``).
          * ``BMS_WRITE_RESULT`` rows whose ``payload.ref_entry_id``
            references one of those REQUESTED rows (joins the request
            to its outcome).
          * Any other entry kind (BMS_REVERT, KEY_ROTATION) whose
            payload directly carries the same ``proposal_id`` —
            forward-compatible with later actions.

        Returns an empty list when no entries match.
        """
        with self._lock:
            entries = list(self._entries)
        return _filter_proposal_chain(entries, proposal_id)

    async def count(self) -> int:
        with self._lock:
            return len(self._entries)

    # ── Tamper-test helpers (NOT part of the protocol) ──
    def _force_replace_for_tamper_test(
        self, index: int, replacement: LedgerEntry,
    ) -> None:
        """Bypass append-only for tamper-detection tests ONLY.

        Production code MUST NOT call this. The name is deliberately
        ugly so grep finds any misuse.
        """
        with self._lock:
            self._entries[index] = replacement


# ─── Postgres persistence (production) ────────────────────────────────
class PostgresPersistence:
    """asyncpg-backed persistence against the ``ledger_entries`` table.

    The DDL lives in ``backend/migrations/2026_05_W4_forensic_ledger.sql``.
    Immutability is enforced DB-side by ``BEFORE UPDATE / BEFORE DELETE``
    triggers — this class has no update/delete methods because there is
    no legitimate need.
    """

    def __init__(self, pool: Any) -> None:
        """``pool`` is an ``asyncpg.Pool`` (typed loose to keep asyncpg
        an optional dependency at import time)."""
        self._pool = pool

    async def append(self, entry: LedgerEntry) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ledger_entries
                    (entry_id, sequence_no, ts, actor, action,
                     payload, prev_hash, entry_hmac, key_version)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9)
                """,
                entry.entry_id,
                entry.sequence_no,
                entry.ts,
                entry.actor,
                entry.action,
                json.dumps(entry.payload, sort_keys=True, default=_json_default),
                entry.prev_hash,
                entry.entry_hmac,
                entry.key_version,
            )

    async def fetch_all(self) -> list[LedgerEntry]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT entry_id, sequence_no, ts, actor, action,
                       payload, prev_hash, entry_hmac, key_version
                FROM ledger_entries
                ORDER BY sequence_no ASC
                """,
            )
            return [_row_to_entry(r) for r in rows]

    async def fetch_last(self) -> LedgerEntry | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT entry_id, sequence_no, ts, actor, action,
                       payload, prev_hash, entry_hmac, key_version
                FROM ledger_entries
                ORDER BY sequence_no DESC
                LIMIT 1
                """,
            )
            return _row_to_entry(row) if row else None

    async def fetch_by_id(self, entry_id: str) -> LedgerEntry | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT entry_id, sequence_no, ts, actor, action,
                       payload, prev_hash, entry_hmac, key_version
                FROM ledger_entries
                WHERE entry_id = $1
                """,
                entry_id,
            )
            return _row_to_entry(row) if row else None

    async def fetch_by_sequence(self, sequence_no: int) -> LedgerEntry | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT entry_id, sequence_no, ts, actor, action,
                       payload, prev_hash, entry_hmac, key_version
                FROM ledger_entries
                WHERE sequence_no = $1
                """,
                sequence_no,
            )
            return _row_to_entry(row) if row else None

    async def fetch_by_proposal_id(
        self, proposal_id: str,
    ) -> list[LedgerEntry]:
        """E5.D — forensic-trail query against the JSONB ``payload``
        column. Pulls the REQUESTED rows whose stamped ``proposal_id``
        matches, plus the RESULT rows that ``ref_entry_id``-link them,
        plus any other rows that directly carry the proposal_id (forward
        compatibility for revert / rotation events). Ordered by
        ``sequence_no`` (chronological).

        DC-EPMS-MSD-006: ``payload->>'ref_entry_id'`` returns ``text``
        (every ``jsonb->>`` operator does); the ``entry_id`` column is
        ``uuid``. The subquery casts ``entry_id::text`` so both sides
        of the ``IN`` are text — without the cast, Postgres raises
        ``UndefinedFunctionError: operator does not exist: text = uuid``.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT entry_id, sequence_no, ts, actor, action,
                       payload, prev_hash, entry_hmac, key_version
                FROM ledger_entries
                WHERE payload->>'proposal_id' = $1
                   OR payload->>'ref_entry_id' IN (
                        SELECT entry_id::text
                          FROM ledger_entries
                         WHERE payload->>'proposal_id' = $1
                   )
                ORDER BY sequence_no ASC
                """,
                proposal_id,
            )
            return [_row_to_entry(r) for r in rows]

    async def count(self) -> int:
        async with self._pool.acquire() as conn:
            n = await conn.fetchval("SELECT COUNT(*) FROM ledger_entries")
            return int(n or 0)


def _filter_proposal_chain(
    entries: list[LedgerEntry], proposal_id: str,
) -> list[LedgerEntry]:
    """In-memory equivalent of the Postgres JSONB query in
    :meth:`PostgresPersistence.fetch_by_proposal_id`.

    Returns the subset of ``entries`` that either:
      * carry ``proposal_id`` directly in their payload, or
      * reference (via ``ref_entry_id``) any entry from the first group.

    Preserves the chronological order of ``entries``.
    """
    if not proposal_id:
        return []
    primary_ids: set[str] = set()
    primary: list[LedgerEntry] = []
    for e in entries:
        if not isinstance(e.payload, dict):
            continue
        if e.payload.get("proposal_id") == proposal_id:
            primary_ids.add(e.entry_id)
            primary.append(e)
    if not primary_ids:
        return []
    secondary: list[LedgerEntry] = []
    for e in entries:
        if e in primary:
            continue
        if not isinstance(e.payload, dict):
            continue
        if e.payload.get("ref_entry_id") in primary_ids:
            secondary.append(e)
    # Re-sort by sequence_no for a single chronological stream.
    out = primary + secondary
    out.sort(key=lambda x: x.sequence_no)
    return out


def _json_default(o: Any) -> Any:
    if isinstance(o, datetime):
        return o.isoformat()
    if isinstance(o, bytes):
        return o.hex()
    raise TypeError(f"unserialisable type: {type(o).__name__}")


def _row_to_entry(row: Any) -> LedgerEntry:
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    ts = row["ts"]
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return LedgerEntry(
        # asyncpg deserialises the UUID column to ``asyncpg.pgproto.pgproto.UUID``
        # — coerce to str so _compute_hmac().encode() works and the dataclass
        # type contract (entry_id: str) holds across persistence backends.
        # DC-EPMS-MSD-005.
        entry_id=str(row["entry_id"]),
        sequence_no=int(row["sequence_no"]),
        ts=ts,
        actor=row["actor"],
        action=row["action"],
        payload=dict(payload),
        prev_hash=bytes(row["prev_hash"] or b""),
        entry_hmac=bytes(row["entry_hmac"]),
        key_version=int(row["key_version"]),
    )


# ─── ForensicLedger ───────────────────────────────────────────────────
class ForensicLedger:
    """The orchestrator. Holds the HMAC key + key_version + persistence.

    Thread/coroutine safety
    -----------------------
    ``append()`` is protected by an ``asyncio.Lock`` so that two concurrent
    appends produce a gapless ``sequence_no`` series and a valid chain.
    Reads are unlocked (snapshot-isolation semantics from the persistence).

    Verifying the chain
    -------------------
    ``await ledger.verify_chain()`` walks every persisted entry in
    sequence order. Returns ``None`` on success; raises
    ``LedgerChainBrokenError`` with the divergence index on the first
    failure.
    """

    def __init__(
        self,
        persistence: Persistence,
        *,
        key: bytes | None = None,
        key_version: int | None = None,
    ) -> None:
        # Key resolution: explicit > env var > ephemeral.
        if key is not None:
            self._keys: dict[int, bytes] = {key_version or 1: key}
            self._current_key_version = key_version or 1
        else:
            resolved_key, resolved_version = _resolve_key_from_env()
            self._keys = {resolved_version: resolved_key}
            self._current_key_version = resolved_version
        self._persistence = persistence
        self._append_lock = asyncio.Lock()
        log.info(
            "ForensicLedger ready (key_version=%d, persistence=%s)",
            self._current_key_version,
            type(persistence).__name__,
        )

    @property
    def current_key_version(self) -> int:
        return self._current_key_version

    @property
    def persistence(self) -> Persistence:
        return self._persistence

    # ── Core: append ──
    async def append(
        self,
        *,
        actor: str,
        action: str,
        payload: dict[str, Any],
    ) -> LedgerEntry:
        """Append one entry to the chain. Computes HMAC + prev_hash.

        ``payload`` MUST be JSON-serialisable. ``actor`` and ``action``
        MUST be non-empty strings. Returns the freshly persisted entry.
        """
        if not actor:
            raise ValueError("actor must be non-empty")
        if not action:
            raise ValueError("action must be non-empty")
        # Refuse non-JSON-serialisable payloads early — catches mistakes
        # at the call site instead of during verify_chain().
        canon_payload = _canonical_json(payload)

        async with self._append_lock:
            last = await self._persistence.fetch_last()
            prev_hash = last.entry_hmac if last else b""
            sequence_no = (last.sequence_no + 1) if last else 1

            entry_id = str(uuid.uuid4())
            ts = datetime.now(UTC)
            key = self._keys[self._current_key_version]
            entry_hmac = _compute_hmac(
                key=key,
                prev_hash=prev_hash,
                entry_id=entry_id,
                ts=ts,
                actor=actor,
                action=action,
                payload_canon=canon_payload,
            )
            entry = LedgerEntry(
                entry_id=entry_id,
                sequence_no=sequence_no,
                ts=ts,
                actor=actor,
                action=action,
                payload=dict(payload),
                prev_hash=prev_hash,
                entry_hmac=entry_hmac,
                key_version=self._current_key_version,
            )
            await self._persistence.append(entry)
            return entry

    # ── Verification ──
    async def verify_chain(self) -> None:
        """Walk the chain. Raise ``LedgerChainBrokenError`` on first
        divergence; return ``None`` on success."""
        entries = await self._persistence.fetch_all()
        expected_prev = b""
        for idx, e in enumerate(entries):
            if e.prev_hash != expected_prev:
                raise LedgerChainBrokenError(
                    idx,
                    "prev_hash does not match predecessor's entry_hmac",
                )
            key = self._keys.get(e.key_version)
            if key is None:
                raise LedgerChainBrokenError(
                    idx,
                    f"unknown key_version={e.key_version} — rotation history lost",
                )
            recomputed = _compute_hmac(
                key=key,
                prev_hash=e.prev_hash,
                entry_id=e.entry_id,
                ts=e.ts,
                actor=e.actor,
                action=e.action,
                payload_canon=_canonical_json(e.payload),
            )
            if not hmac.compare_digest(recomputed, e.entry_hmac):
                raise LedgerChainBrokenError(idx, "HMAC mismatch")
            expected_prev = e.entry_hmac

    # ── Convenience reads ──
    async def fetch_by_id(self, entry_id: str) -> LedgerEntry | None:
        return await self._persistence.fetch_by_id(entry_id)

    async def fetch_by_sequence(self, sequence_no: int) -> LedgerEntry | None:
        return await self._persistence.fetch_by_sequence(sequence_no)

    async def fetch_all(self) -> list[LedgerEntry]:
        return await self._persistence.fetch_all()

    async def fetch_by_proposal_id(
        self, proposal_id: str,
    ) -> list[LedgerEntry]:
        """E5.D — forensic-trail query. See
        :meth:`Persistence.fetch_by_proposal_id`."""
        return await self._persistence.fetch_by_proposal_id(proposal_id)

    async def count(self) -> int:
        return await self._persistence.count()

    # ── Key rotation ──
    async def rotate_key(
        self, new_key: bytes, *, new_version: int, rotated_by: str,
    ) -> LedgerEntry:
        """Register a new HMAC key and append a ``KEY_ROTATION`` entry.

        Old key versions remain registered in ``self._keys`` so that
        ``verify_chain()`` can still validate entries signed under them.
        """
        if new_version <= self._current_key_version:
            raise ValueError(
                f"new key_version ({new_version}) must exceed current "
                f"({self._current_key_version})",
            )
        if not new_key or len(new_key) < 16:
            raise ValueError("new_key must be at least 16 bytes")
        prior_version = self._current_key_version
        self._keys[new_version] = new_key
        self._current_key_version = new_version
        return await self.append(
            actor=rotated_by,
            action=ACTION_KEY_ROTATION,
            payload={
                "prior_key_version": prior_version,
                "new_key_version": new_version,
            },
        )


# ─── HMAC computation (canonical) ─────────────────────────────────────
def _canonical_json(payload: dict[str, Any]) -> bytes:
    """Deterministic JSON encoding. Keys sorted, no whitespace, UTF-8."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=_json_default,
    ).encode("utf-8")


def _compute_hmac(
    *,
    key: bytes,
    prev_hash: bytes,
    entry_id: str,
    ts: datetime,
    actor: str,
    action: str,
    payload_canon: bytes,
) -> bytes:
    """HMAC-SHA256 over the canonical wire form. Field order is binding."""
    payload_digest = hashlib.sha256(payload_canon).digest()
    body = (
        prev_hash
        + entry_id.encode("utf-8")
        + ts.isoformat().encode("utf-8")
        + actor.encode("utf-8")
        + action.encode("utf-8")
        + payload_digest
    )
    return hmac.new(key, body, hashlib.sha256).digest()


def _resolve_key_from_env() -> tuple[bytes, int]:
    """Return ``(key_bytes, key_version)``.

    Environment variable ``DC_EPMS_LEDGER_HMAC_KEY`` is hex-encoded
    (>= 32 bytes => 64 hex chars). When absent, generates an ephemeral
    key, logs a WARNING, and tags entries with ``key_version=0``.
    """
    raw = os.environ.get(ENV_KEY_NAME)
    if not raw:
        ephemeral = secrets.token_bytes(32)
        log.warning(
            "%s not set — using ephemeral key with key_version=%d. "
            "Entries signed under this key cannot be verified after "
            "process restart. SET THE ENV VARIABLE IN PRODUCTION.",
            ENV_KEY_NAME, EPHEMERAL_KEY_VERSION,
        )
        return ephemeral, EPHEMERAL_KEY_VERSION
    try:
        key = bytes.fromhex(raw.strip())
    except ValueError as e:
        raise RuntimeError(
            f"{ENV_KEY_NAME} must be hex-encoded; got {len(raw)} chars",
        ) from e
    if len(key) < 32:
        raise RuntimeError(
            f"{ENV_KEY_NAME} must decode to >= 32 bytes; got {len(key)}",
        )
    return key, 1


# ─── BMS write seam (S-LEDGER-01) ─────────────────────────────────────
# Signatures intentionally match backend.optimizer_routes.BmsWriteFn so
# the wrapper is a drop-in replacement.
BmsWriteFn = Callable[[str, Any, str], tuple[bool, str]]
PrevValueReader = Callable[[str], Any]


def wrap_bms_write_fn(
    inner_fn: BmsWriteFn,
    *,
    ledger: ForensicLedger,
    prev_value_reader: PrevValueReader,
    source: str = "direct",
    loop: asyncio.AbstractEventLoop | None = None,
) -> BmsWriteFn:
    """Wrap a ``BmsWriteFn`` with forensic ledger pre- and post-entries.

    The wrapper preserves the synchronous ``(success, message)`` return
    shape of the existing seam, so callers in
    ``backend/optimizer_routes.py`` and ``backend/main.py`` need no
    refactor — they just receive the wrapped fn.

    Parameters
    ----------
    inner_fn
        The underlying BMS write callable. Typically a lambda over
        ``bms_connector.BMSConnector.write``.
    ledger
        The shared ``ForensicLedger`` instance.
    prev_value_reader
        Reads the current value of a tag (used to capture ``prev_value``
        for the revert harness). Typically a lambda over
        ``bms_connector.BMSConnector.read(tag_id).current_value``.
    source
        Tagged into the payload (``"direct"`` for ``/api/bms/write``,
        ``"optimizer_approval"`` for the Optimizer flow, ``"revert"``
        for the rollback endpoint). Helps audit queries.
    loop
        Optional event loop. When the wrapper is called from a sync
        context (FastAPI endpoint thread pool), it schedules the ledger
        coroutines on this loop. When called from an async context,
        leave as ``None`` — ``asyncio.get_event_loop()`` is used.

    Returns
    -------
    A new ``BmsWriteFn`` that:
      1. Reads prev_value
      2. Appends ``BMS_WRITE_REQUESTED`` with proposal_id (if any),
         tag_id, requested_value, prev_value, source.
      3. Calls ``inner_fn(tag_id, value, user)``
      4. Appends ``BMS_WRITE_RESULT`` with ref_entry_id, success, message
      5. Returns the underlying ``(success, message)`` tuple

    The seam buries proposal_id in a ``contextvars.ContextVar`` so
    callers that already have one (Optimizer approve flow) can stamp
    the ledger entry without changing the BmsWriteFn signature. See
    ``set_proposal_context``.
    """
    def wrapped(tag_id: str, value: Any, user: str) -> tuple[bool, str]:
        try:
            prev_value = prev_value_reader(tag_id)
        except Exception as exc:
            log.warning(
                "[ledger] prev_value_reader raised for tag=%s: %s",
                tag_id, exc,
            )
            prev_value = None

        proposal_id = _PROPOSAL_CONTEXT.get()
        request_payload = {
            "tag_id": tag_id,
            "requested_value": value,
            "prev_value": prev_value,
            "source": source,
            "proposal_id": proposal_id,
        }

        request_entry = _run_async(
            ledger.append(
                actor=user,
                action=ACTION_BMS_WRITE_REQUESTED,
                payload=request_payload,
            ),
            loop=loop,
        )

        try:
            success, message = inner_fn(tag_id, value, user)
        except Exception as exc:
            _run_async(
                ledger.append(
                    actor=user,
                    action=ACTION_BMS_WRITE_RESULT,
                    payload={
                        "ref_entry_id": request_entry.entry_id,
                        "success": False,
                        "message": f"inner_fn raised: {exc!r}",
                    },
                ),
                loop=loop,
            )
            raise

        _run_async(
            ledger.append(
                actor=user,
                action=ACTION_BMS_WRITE_RESULT,
                payload={
                    "ref_entry_id": request_entry.entry_id,
                    "success": bool(success),
                    "message": str(message),
                },
            ),
            loop=loop,
        )
        return success, message

    return wrapped


# ─── Proposal context (S-PROPOSER-01) ─────────────────────────────────
# The proposal_id is associated with a BMS write via this ContextVar so
# the Optimizer approve path can stamp it without changing the
# BmsWriteFn signature (which would force every test fixture to update).
import contextvars  # noqa: E402 — kept near its only consumer

_PROPOSAL_CONTEXT: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "dc_epms_proposal_id", default=None,
)


def set_proposal_context(proposal_id: str | None) -> contextvars.Token:
    """Set the proposal_id for the current execution context.

    Returns a token that the caller can pass to ``reset_proposal_context``
    to restore the prior value (typically in a ``try/finally``).
    """
    return _PROPOSAL_CONTEXT.set(proposal_id)


def reset_proposal_context(token: contextvars.Token) -> None:
    _PROPOSAL_CONTEXT.reset(token)


# ─── Async-from-sync shim ─────────────────────────────────────────────
# Module-level dedicated worker loop for sync→async bridging when the
# caller did NOT provide an explicit ``loop=``. We spin this up lazily on
# first need and keep it alive for the process lifetime so successive
# wrapper calls don't churn ProactorEventLoops (a known Windows pain).
_WORKER_LOOP: asyncio.AbstractEventLoop | None = None
_WORKER_THREAD: threading.Thread | None = None
_WORKER_LOCK = threading.Lock()


def _get_or_start_worker_loop() -> asyncio.AbstractEventLoop:
    """Return a long-lived background event loop running in its own thread.

    The wrapper schedules its async ledger work onto this loop via
    ``run_coroutine_threadsafe`` whenever no explicit ``loop=`` was
    provided at construction. Reusing a single loop avoids the
    Windows-specific ResourceWarning churn that comes with one
    transient ``asyncio.run()`` per write.
    """
    global _WORKER_LOOP, _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_LOOP is not None and _WORKER_LOOP.is_running():
            return _WORKER_LOOP
        new_loop = asyncio.new_event_loop()

        def _runner() -> None:
            asyncio.set_event_loop(new_loop)
            new_loop.run_forever()

        thread = threading.Thread(
            target=_runner, name="forensic-ledger-loop", daemon=True,
        )
        thread.start()
        _WORKER_LOOP = new_loop
        _WORKER_THREAD = thread
        return new_loop


def _run_async(
    coro: Iterable[Any] | Any,
    *,
    loop: asyncio.AbstractEventLoop | None,
) -> Any:
    """Run an awaitable to completion from a sync caller.

    ``wrap_bms_write_fn`` returns a SYNC callable (matching the existing
    ``BmsWriteFn`` shape). It internally awaits async ledger methods —
    this helper is the bridge. We tolerate three caller contexts:

    1. The wrapper was constructed with an explicit ``loop=`` referencing
       a loop running in a DIFFERENT thread (e.g. the FastAPI lifespan
       loop and we're called from ``asyncio.to_thread``): schedule with
       ``run_coroutine_threadsafe`` and block on ``.result()``. Fine.
    2. No explicit loop: schedule onto the module-level worker loop
       (started lazily on first call). Reuses the same loop across
       writes to avoid ProactorEventLoop churn on Windows.
    3. The wrapper is called from inside a running loop on the SAME
       thread without an explicit ``loop=`` — would deadlock. We refuse
       with a clear error so the caller offloads via
       ``await asyncio.to_thread(wrapped, ...)``.
    """
    if coro is None or not asyncio.iscoroutine(coro):
        return coro
    if loop is not None and loop.is_running():
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is not None:
        coro.close()
        raise RuntimeError(
            "wrap_bms_write_fn was invoked synchronously from inside a "
            "running event loop on the same thread — this would "
            "deadlock. Offload via `await asyncio.to_thread(wrapped, "
            "tag_id, value, user)` or construct the wrapper with an "
            "explicit `loop=` running in another thread.",
        )
    worker = _get_or_start_worker_loop()
    future = asyncio.run_coroutine_threadsafe(coro, worker)
    return future.result()
