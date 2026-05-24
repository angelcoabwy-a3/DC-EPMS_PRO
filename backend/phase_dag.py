"""
backend/phase_dag.py
====================
Harness H06 -- Phase DAG (Gentle IA agent harness registry, Bloque 2).

Goal
----
Formalise the SDD lifecycle so autonomous flows cannot silently skip
phases. Without a Phase DAG, an agent could jump from Init straight to
Apply, shipping work that never passed Spec / Design review. With H06
operativo, any such attempt raises :class:`PhaseTransitionError` --
a deterministic refusal at the seam (`enforce_phase_dependency`
decorator) before the side-effect fires.

Lifecycle
---------
::

    Init -> Proposal -> Spec -> Design -> Task -> Apply -> Verify -> Archive

Two transition rules:

  1. **Sequential forward** -- each phase can move to its immediate
     successor in :data:`CANONICAL_PHASE_ORDER`. Skipping (e.g.
     Init -> Spec) raises :class:`PhaseTransitionError`.
  2. **Idempotent self-transition** -- re-entering the same phase is
     allowed (an Apply retry, a Spec amendment). History records the
     re-entry for forensic provenance.
  3. **Archive shortcut** -- any phase may transition directly to
     :data:`PhaseState.ARCHIVE`. This models early termination
     (rejected proposal, abandoned design, post-mortem after a failed
     Apply). Backward transitions OTHER than to ARCHIVE are denied.

The tracker is **in-memory** by design. Persistence would couple H06
to a storage backend; agents that need cross-process recovery should
combine a :class:`PhaseTracker` with :mod:`backend.agent_continuity`
(H13) -- the two harnesses compose, but each remains independently
useful.

Skill: ``S-PHASE-01`` (registered in this commit).
"""
from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from enum import IntEnum
from functools import wraps
from threading import Lock
from typing import Any, TypeVar


# ─── Enum + canonical sequence ────────────────────────────────────────────
class PhaseState(IntEnum):
    """The 8 canonical SDD phases. ``IntEnum`` so the integer value is
    also the position in :data:`CANONICAL_PHASE_ORDER` -- this lets
    callers do `next_phase = PhaseState(current + 1)` when iterating
    forward without indexing into the tuple."""

    INIT = 0
    PROPOSAL = 1
    SPEC = 2
    DESIGN = 3
    TASK = 4
    APPLY = 5
    VERIFY = 6
    ARCHIVE = 7


# Canonical order. The validator reads adjacency from this tuple, so a
# future re-ordering happens in exactly one place.
CANONICAL_PHASE_ORDER: tuple[PhaseState, ...] = (
    PhaseState.INIT,
    PhaseState.PROPOSAL,
    PhaseState.SPEC,
    PhaseState.DESIGN,
    PhaseState.TASK,
    PhaseState.APPLY,
    PhaseState.VERIFY,
    PhaseState.ARCHIVE,
)


# ─── Error ────────────────────────────────────────────────────────────────
class PhaseTransitionError(RuntimeError):
    """Raised when an agent attempts an illegal phase transition or
    invokes a phase-guarded function out of order. Inherits from
    :class:`RuntimeError` (not :class:`ValueError`) because the
    condition is a state-machine violation, not bad input."""


# ─── Tracker ──────────────────────────────────────────────────────────────
class PhaseTracker:
    """In-memory per-task phase state. Thread-safe via a single
    :class:`threading.Lock` around all read + write paths.

    Surface
    -------
    * :meth:`start` -- anchor a new task at :data:`PhaseState.INIT`.
    * :meth:`current_phase` -- read the latest phase for a task, or
      ``None`` for unknown tasks.
    * :meth:`history` -- read the ordered phase history for a task
      (every recorded entry, including idempotent re-entries).
    * :meth:`transition_to` -- validate + record a transition. Raises
      :class:`PhaseTransitionError` on illegal moves; on success the
      new phase appears in `current_phase` and is appended to
      `history`.
    """

    def __init__(self):
        self._history: dict[str, list[PhaseState]] = {}
        self._lock = Lock()

    def start(self, task_id: str) -> None:
        """Anchor ``task_id`` at :data:`PhaseState.INIT`. Idempotent --
        re-calling on an already-started task is a no-op."""
        if not task_id:
            raise PhaseTransitionError("task_id must be a non-empty string")
        with self._lock:
            if task_id not in self._history:
                self._history[task_id] = [PhaseState.INIT]

    def current_phase(self, task_id: str) -> PhaseState | None:
        with self._lock:
            hist = self._history.get(task_id)
            return hist[-1] if hist else None

    def history(self, task_id: str) -> list[PhaseState]:
        with self._lock:
            return list(self._history.get(task_id, []))

    def transition_to(self, task_id: str, target: PhaseState) -> None:
        """Move ``task_id`` to ``target``. Raises
        :class:`PhaseTransitionError` for any of:
        * the task was never started (no INIT anchor);
        * target is neither the current phase, nor its immediate
          successor, nor :data:`PhaseState.ARCHIVE`.
        """
        if not isinstance(target, PhaseState):
            raise PhaseTransitionError(
                f"target must be PhaseState, got {type(target).__name__}"
            )
        with self._lock:
            hist = self._history.get(task_id)
            if not hist:
                raise PhaseTransitionError(
                    f"task {task_id!r} never started -- "
                    "call start() before transition_to()"
                )
            current = hist[-1]

            allowed = self._allowed_targets(current)
            if target not in allowed:
                raise PhaseTransitionError(
                    f"cannot transition task {task_id!r} from "
                    f"{current.name} to {target.name}; allowed: "
                    f"{sorted(p.name for p in allowed)}"
                )
            hist.append(target)

    @staticmethod
    def _allowed_targets(current: PhaseState) -> set[PhaseState]:
        """Return the set of phases reachable from ``current`` in one
        legal transition."""
        allowed: set[PhaseState] = {current, PhaseState.ARCHIVE}
        # Immediate successor in the canonical sequence.
        next_index = current.value + 1
        if next_index < len(CANONICAL_PHASE_ORDER):
            allowed.add(CANONICAL_PHASE_ORDER[next_index])
        return allowed


# ─── enforce_phase_dependency decorator ───────────────────────────────────
F = TypeVar("F", bound=Callable[..., Any])


def enforce_phase_dependency(
    required: PhaseState,
    *,
    tracker: PhaseTracker,
) -> Callable[[F], F]:
    """Decorate a function so it raises :class:`PhaseTransitionError`
    when called against a ``task_id`` not currently in the required
    phase.

    Contract for the wrapped function:
      * MUST accept ``task_id`` as a keyword argument.
      * MAY be sync or async -- the wrapper dispatches the right
        flavour based on :func:`inspect.iscoroutinefunction`.

    Example::

        tracker = PhaseTracker()

        @enforce_phase_dependency(PhaseState.SPEC, tracker=tracker)
        async def emit_design_doc(*, task_id: str) -> str:
            ...

    Rationale: H06 protects against the "auto-pilot agent skips
    phases" risk surfaced in the 2026-05-24 Gap Analysis. Decorating
    the side-effecting seam (e.g. an Apply-phase action) means the
    refusal happens at the right layer -- the agent's
    decision-making code does not need to know about phase rules.
    """
    if not isinstance(required, PhaseState):
        raise TypeError(
            f"required must be PhaseState, got {type(required).__name__}"
        )

    def _decorate(fn: F) -> F:
        if inspect.iscoroutinefunction(fn):
            @wraps(fn)
            async def _async_wrapper(*args, **kwargs):
                _assert_phase(tracker, required, kwargs)
                return await fn(*args, **kwargs)
            return _async_wrapper  # type: ignore[return-value]

        @wraps(fn)
        def _sync_wrapper(*args, **kwargs):
            _assert_phase(tracker, required, kwargs)
            return fn(*args, **kwargs)
        return _sync_wrapper  # type: ignore[return-value]

    return _decorate


def _assert_phase(
    tracker: PhaseTracker,
    required: PhaseState,
    kwargs: dict[str, Any],
) -> None:
    """Helper -- shared by the sync and async wrappers."""
    task_id = kwargs.get("task_id")
    if not task_id:
        raise PhaseTransitionError(
            "enforce_phase_dependency requires a 'task_id' keyword argument"
        )
    current = tracker.current_phase(task_id)
    if current is not required:
        actual = current.name if current is not None else "<not started>"
        raise PhaseTransitionError(
            f"function requires phase {required.name} for task "
            f"{task_id!r}, but current phase is {actual}"
        )


# ─── Async coordination helper (optional) ─────────────────────────────────
# Some callers want to await a transition (e.g. "wait until the task
# reaches SPEC"). Out of scope for the H06 closure but the asyncio
# import keeps the door open for a future addition without an import
# churn commit.
_ = asyncio
