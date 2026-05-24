"""
backend/agent_continuity.py
===========================
Harness H13 — Apply Continuity Harness (Gentle IA agent harness registry).

Goal
----
Long-running agent authoring tasks (e.g. ``ProcedureArchitectAgent.generate``)
must not lose work to a process crash, network blip, or LLM-server
disconnect mid-call. H13 persists the agent's intra-task state at named
phases so a subsequent process can pick up exactly where the previous one
stopped — without re-billing the LLM for work already done.

Design
------
* **Append-only JSONL** — same persistence shape as
  :class:`backend.agent_harness.AgentStateStore` (H05). Operators learn
  one storage discipline, not two. A partial write at process kill leaves
  at most one corrupt trailing line that the reader silently skips.
* **Phase contract** — two named phases:
    - :data:`PHASE_PRE_LLM` — captured before the (potentially expensive
      or fragile) LLM dispatch. Payload MUST carry every input the LLM
      call requires so a resume can re-dispatch deterministically.
    - :data:`PHASE_POST_LLM` — captured after the LLM resolves (or after
      the deterministic fallback fires). Payload carries the full draft
      so a resume returns a completed :class:`ProcedureDraft` with NO
      LLM call (idempotency property — critical for cost + safety).
* **Per-draft recovery** — :meth:`CheckpointStore.latest_for_draft`
  returns the most recent checkpoint for a given draft_id; recovery
  inspects ``.phase`` to decide whether to re-dispatch or short-circuit.

Why JSONL
---------
SQLite would be heavier and would require schema migrations. The
:class:`AgentStateStore` precedent (skill ``S-LEDGER-01`` lineage)
established JSONL as DC-EPMS's canonical "append-only audit trail"
shape — H13 inherits that discipline so a single ``cat *.jsonl`` is
enough to forensically reconstruct any agent's intra-task history.

Skill: ``S-CONTINUITY-01`` (added in this commit).
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ─── Phase vocabulary ─────────────────────────────────────────────────────
# Frozen set on purpose: the resume path branches on phase identity, so a
# typo in a future caller (``"pre-llm"`` vs ``"pre_llm"``) must raise
# instead of silently writing a row that recovery cannot interpret.
PHASE_PRE_LLM = "pre_llm"
PHASE_POST_LLM = "post_llm"

VALID_PHASES: frozenset[str] = frozenset({PHASE_PRE_LLM, PHASE_POST_LLM})


# ─── Data class ───────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Checkpoint:
    """A single recovery point. Frozen so consumers can pass instances
    through the resume pipeline without defensive copying.

    Fields
    ------
    checkpoint_id : str
        UUID-hex generated at write time. Used as a forensic correlation
        key — operators can grep the JSONL by checkpoint_id to locate a
        specific recovery point.
    draft_id : str
        The owning draft. Recovery queries by this key.
    phase : str
        One of :data:`PHASE_PRE_LLM` / :data:`PHASE_POST_LLM`.
    persisted_at_unix : float
        Wall-clock unix timestamp of write. Used by readers to break
        ties when multiple checkpoints share a phase (last-write-wins).
    payload : dict
        Phase-specific state. The schema is the caller's contract; H13
        does not validate beyond JSON-serialisability.
    """

    checkpoint_id: str
    draft_id: str
    phase: str
    persisted_at_unix: float
    payload: dict[str, Any] = field(default_factory=dict)


# ─── Store ────────────────────────────────────────────────────────────────
class CheckpointStore:
    """Append-only JSONL persistence of agent intra-task checkpoints.

    Thread-safe via a single :class:`threading.Lock` around all I/O.
    Asynchronous callers can wrap :meth:`record` in
    ``asyncio.to_thread`` if the event loop must stay unblocked; for
    sub-kilobyte payloads (which is the common case for procedure
    drafts) the synchronous path is sub-millisecond on local disk and
    not worth the indirection.

    The path's parent directory is created on construction so callers
    can pass any reasonable absolute :class:`Path` and not worry about
    pre-creating folders.

    Default location convention (recommended, not enforced): ``data/
    agent_state/checkpoints.jsonl`` alongside the H05 consultation log.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # ── Write path ──
    def record(
        self,
        *,
        draft_id: str,
        phase: str,
        payload: dict[str, Any] | None = None,
    ) -> str:
        """Append a single checkpoint. Returns the generated
        ``checkpoint_id`` for forensic correlation.

        Raises
        ------
        ValueError
            If ``phase`` is not one of :data:`VALID_PHASES`. A typo here
            would corrupt recovery, so it must be loud.
        """
        if phase not in VALID_PHASES:
            raise ValueError(
                f"unknown checkpoint phase {phase!r}; "
                f"must be one of {sorted(VALID_PHASES)}"
            )
        if not isinstance(draft_id, str) or not draft_id:
            raise ValueError("draft_id must be a non-empty string")

        entry: dict[str, Any] = {
            "checkpoint_id": uuid.uuid4().hex,
            "draft_id": draft_id,
            "phase": phase,
            "persisted_at_unix": time.time(),
            "payload": dict(payload) if payload else {},
        }
        line = json.dumps(entry, default=str, ensure_ascii=False)
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.write("\n")
        return entry["checkpoint_id"]

    # ── Read paths ──
    def iter_for_draft(self, draft_id: str) -> list[Checkpoint]:
        """Return all checkpoints for ``draft_id`` in chronological
        (write) order. Returns an empty list when the file is missing
        or the draft has no checkpoints. Corrupt lines are silently
        skipped (consistent with H05's tolerance for partial writes)."""
        rows = self._read_all_rows()
        return [
            self._row_to_checkpoint(r)
            for r in rows
            if r.get("draft_id") == draft_id
        ]

    def latest_for_draft(self, draft_id: str) -> Checkpoint | None:
        """Return the most recent checkpoint for ``draft_id``, or
        ``None`` when no checkpoints exist for that draft.

        Resolution rule: read all rows, filter by draft_id, return the
        last (= most recently written). Append-only file order is the
        canonical chronology — we do NOT sort by ``persisted_at_unix``
        because two checkpoints written in the same nanosecond would
        otherwise tie and the order would become non-deterministic.
        """
        history = self.iter_for_draft(draft_id)
        return history[-1] if history else None

    # ── Maintenance ──
    def clear(self) -> None:
        """Delete the backing file. Test-only hook — production callers
        should never wipe the audit trail mid-flight."""
        with self._lock:
            if self.path.exists():
                self.path.unlink()

    # ── Internals ──
    def _read_all_rows(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with self._lock, self.path.open("r", encoding="utf-8") as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rows.append(json.loads(ln))
                except json.JSONDecodeError:
                    # Skip a corrupt line; a partial write at process
                    # kill can leave one bad row at end-of-file. The
                    # next successful record() will append cleanly
                    # after it.
                    continue
        return rows

    @staticmethod
    def _row_to_checkpoint(row: dict[str, Any]) -> Checkpoint:
        return Checkpoint(
            checkpoint_id=str(row.get("checkpoint_id", "")),
            draft_id=str(row.get("draft_id", "")),
            phase=str(row.get("phase", "")),
            persisted_at_unix=float(row.get("persisted_at_unix", 0.0)),
            payload=dict(row.get("payload") or {}),
        )
