"""
backend.ledger
==============
Forensic Ledger module — append-only, HMAC-chained audit trail for all
control-surface mutations. ADR-011 source-of-truth.

Public surface
--------------
* ``ForensicLedger``           — the orchestrator
* ``LedgerEntry``              — frozen dataclass for a chain entry
* ``Persistence`` protocol     — append / iter / fetch_last interface
* ``InMemoryPersistence``      — for unit tests
* ``PostgresPersistence``      — for production (asyncpg-backed)
* ``LedgerImmutabilityError``  — raised on any update/delete attempt
* ``LedgerChainBrokenError``   — raised by verify_chain() with the index
* ``wrap_bms_write_fn``        — wraps a BmsWriteFn with ledger pre/post
                                  entries (S-LEDGER-01)

Skills (binding):
    S-LEDGER-01  — every control-surface write goes through wrap_bms_write_fn
    S-PROPOSER-01 — AI-originated writes carry proposal_id linking to consensus
"""

from __future__ import annotations

from backend.ledger.forensic_ledger import (
    ACTION_BMS_REVERT,
    ACTION_BMS_WRITE_REQUESTED,
    ACTION_BMS_WRITE_RESULT,
    ACTION_KEY_ROTATION,
    ENV_KEY_NAME,
    EPHEMERAL_KEY_VERSION,
    ForensicLedger,
    InMemoryPersistence,
    LedgerChainBrokenError,
    LedgerEntry,
    LedgerImmutabilityError,
    Persistence,
    PostgresPersistence,
    reset_proposal_context,
    set_proposal_context,
    wrap_bms_write_fn,
)

__all__ = [
    "ACTION_BMS_REVERT",
    "ACTION_BMS_WRITE_REQUESTED",
    "ACTION_BMS_WRITE_RESULT",
    "ACTION_KEY_ROTATION",
    "ENV_KEY_NAME",
    "EPHEMERAL_KEY_VERSION",
    "ForensicLedger",
    "InMemoryPersistence",
    "LedgerChainBrokenError",
    "LedgerEntry",
    "LedgerImmutabilityError",
    "Persistence",
    "PostgresPersistence",
    "reset_proposal_context",
    "set_proposal_context",
    "wrap_bms_write_fn",
]
