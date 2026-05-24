"""
tests/test_phase_dag.py
=======================
Tests for H06 -- Phase DAG Harness (Gentle IA Bloque 2).

Strict TDD discipline: RED phase. All tests fail until
`backend/phase_dag.py` exists with the documented surface.

Coverage:

  Block A -- PhaseState enum + canonical sequence constants.
  Block B -- PhaseTracker (per-task in-memory state).
  Block C -- Transition validation (sequential + ARCHIVE shortcut).
  Block D -- enforce_phase_dependency decorator (sync + async).
  Block E -- Acceptance: full lifecycle + skip-attempt blocked.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.phase_dag import (
    CANONICAL_PHASE_ORDER,
    PhaseState,
    PhaseTracker,
    PhaseTransitionError,
    enforce_phase_dependency,
)


# ─── Block A -- enum + sequence ────────────────────────────────────────────
class TestPhaseStateEnum:

    def test_enum_has_eight_canonical_phases(self):
        # The Gentle IA SDD lifecycle is:
        # Init -> Proposal -> Spec -> Design -> Task -> Apply -> Verify -> Archive.
        names = {p.name for p in PhaseState}
        assert names == {
            "INIT", "PROPOSAL", "SPEC", "DESIGN",
            "TASK", "APPLY", "VERIFY", "ARCHIVE",
        }

    def test_canonical_order_is_eight_phases(self):
        assert len(CANONICAL_PHASE_ORDER) == 8
        assert CANONICAL_PHASE_ORDER[0] is PhaseState.INIT
        assert CANONICAL_PHASE_ORDER[-1] is PhaseState.ARCHIVE

    def test_canonical_order_matches_enum_order(self):
        # The tuple is the source of truth for adjacency; the enum
        # values must align with it.
        for i, phase in enumerate(CANONICAL_PHASE_ORDER):
            assert phase.value == i


# ─── Block B -- PhaseTracker (per-task state) ─────────────────────────────
class TestPhaseTracker:

    def test_tracker_initial_phase_is_none(self):
        t = PhaseTracker()
        assert t.current_phase("task-001") is None

    def test_tracker_records_initial_phase(self):
        t = PhaseTracker()
        t.start("task-001")
        assert t.current_phase("task-001") is PhaseState.INIT

    def test_tracker_isolates_distinct_tasks(self):
        t = PhaseTracker()
        t.start("task-A")
        t.start("task-B")
        t.transition_to("task-A", PhaseState.PROPOSAL)
        # task-B is unaffected.
        assert t.current_phase("task-A") is PhaseState.PROPOSAL
        assert t.current_phase("task-B") is PhaseState.INIT

    def test_tracker_history_records_each_transition(self):
        t = PhaseTracker()
        t.start("task-001")
        t.transition_to("task-001", PhaseState.PROPOSAL)
        t.transition_to("task-001", PhaseState.SPEC)
        hist = t.history("task-001")
        assert hist == [PhaseState.INIT, PhaseState.PROPOSAL, PhaseState.SPEC]

    def test_tracker_history_returns_empty_for_unknown(self):
        t = PhaseTracker()
        assert t.history("never-started") == []


# ─── Block C -- transition validation ─────────────────────────────────────
class TestTransitionValidation:

    def test_sequential_transition_succeeds(self):
        t = PhaseTracker()
        t.start("task-001")
        # Init -> Proposal -> Spec is the canonical sequence.
        t.transition_to("task-001", PhaseState.PROPOSAL)
        t.transition_to("task-001", PhaseState.SPEC)
        assert t.current_phase("task-001") is PhaseState.SPEC

    def test_idempotent_self_transition_is_allowed(self):
        # Re-entering the same phase is a no-op (e.g. an Apply retry).
        t = PhaseTracker()
        t.start("task-001")
        t.transition_to("task-001", PhaseState.PROPOSAL)
        t.transition_to("task-001", PhaseState.PROPOSAL)  # idempotent
        assert t.current_phase("task-001") is PhaseState.PROPOSAL
        # History still records the re-entry for forensic provenance.
        assert t.history("task-001").count(PhaseState.PROPOSAL) == 2

    def test_skipping_phase_raises(self):
        # Init -> Spec (skipping Proposal) must raise.
        t = PhaseTracker()
        t.start("task-001")
        with pytest.raises(PhaseTransitionError, match="cannot transition"):
            t.transition_to("task-001", PhaseState.SPEC)

    def test_backward_transition_raises(self):
        # Spec -> Proposal must raise (SDD is forward-only except
        # ARCHIVE which can be reached from anywhere).
        t = PhaseTracker()
        t.start("task-001")
        t.transition_to("task-001", PhaseState.PROPOSAL)
        t.transition_to("task-001", PhaseState.SPEC)
        with pytest.raises(PhaseTransitionError, match="cannot transition"):
            t.transition_to("task-001", PhaseState.PROPOSAL)

    def test_archive_shortcut_from_any_phase_succeeds(self):
        # Any phase can transition directly to ARCHIVE (early
        # termination -- a Proposal that was rejected, a Design that
        # was abandoned, etc.).
        for source in (PhaseState.INIT, PhaseState.PROPOSAL,
                       PhaseState.SPEC, PhaseState.DESIGN,
                       PhaseState.TASK, PhaseState.APPLY,
                       PhaseState.VERIFY):
            t = PhaseTracker()
            t.start(f"task-{source.name}")
            # Walk forward to the source phase one step at a time
            # (the only path the validator allows beyond the start).
            for step in CANONICAL_PHASE_ORDER[1:source.value + 1]:
                t.transition_to(f"task-{source.name}", step)
            # Then the ARCHIVE shortcut must work.
            t.transition_to(f"task-{source.name}", PhaseState.ARCHIVE)
            assert t.current_phase(f"task-{source.name}") is PhaseState.ARCHIVE

    def test_transition_on_unstarted_task_raises(self):
        # A task that never went through start() cannot transition --
        # there is no INIT anchor.
        t = PhaseTracker()
        with pytest.raises(PhaseTransitionError, match="task.*never started"):
            t.transition_to("ghost-task", PhaseState.PROPOSAL)


# ─── Block D -- enforce_phase_dependency decorator ────────────────────────
class TestEnforcePhaseDependency:

    def test_decorator_passes_when_task_in_required_phase(self):
        tracker = PhaseTracker()
        tracker.start("task-001")
        tracker.transition_to("task-001", PhaseState.PROPOSAL)
        tracker.transition_to("task-001", PhaseState.SPEC)

        @enforce_phase_dependency(PhaseState.SPEC, tracker=tracker)
        def emit_design_doc(*, task_id: str) -> str:
            return f"design-{task_id}"

        assert emit_design_doc(task_id="task-001") == "design-task-001"

    def test_decorator_raises_when_task_not_in_required_phase(self):
        tracker = PhaseTracker()
        tracker.start("task-001")
        # Task is at INIT, but the decorator requires SPEC.

        @enforce_phase_dependency(PhaseState.SPEC, tracker=tracker)
        def emit_design_doc(*, task_id: str) -> str:
            return "should-not-fire"

        with pytest.raises(PhaseTransitionError, match="requires phase SPEC"):
            emit_design_doc(task_id="task-001")

    def test_decorator_raises_when_task_id_missing(self):
        tracker = PhaseTracker()

        @enforce_phase_dependency(PhaseState.SPEC, tracker=tracker)
        def f(*, task_id: str) -> int:
            return 1

        with pytest.raises(PhaseTransitionError, match="task_id"):
            f()  # no task_id kwarg

    def test_decorator_works_with_async_function(self):
        tracker = PhaseTracker()
        tracker.start("task-async")
        tracker.transition_to("task-async", PhaseState.PROPOSAL)

        @enforce_phase_dependency(PhaseState.PROPOSAL, tracker=tracker)
        async def async_op(*, task_id: str) -> str:
            await asyncio.sleep(0)
            return f"async-{task_id}"

        result = asyncio.run(async_op(task_id="task-async"))
        assert result == "async-task-async"

    def test_decorator_async_raises_on_missing_phase(self):
        tracker = PhaseTracker()
        tracker.start("task-async")
        # Stays at INIT; decorator demands APPLY.

        @enforce_phase_dependency(PhaseState.APPLY, tracker=tracker)
        async def async_op(*, task_id: str) -> str:
            return "should-not-fire"

        with pytest.raises(PhaseTransitionError, match="requires phase APPLY"):
            asyncio.run(async_op(task_id="task-async"))


# ─── Block E -- acceptance ────────────────────────────────────────────────
class TestPhaseLifecycleAcceptance:

    def test_full_sdd_lifecycle_walks_eight_phases(self):
        """Walk a task through the entire SDD lifecycle Init -> Archive,
        asserting current_phase + history at each step."""
        t = PhaseTracker()
        t.start("acceptance-001")
        assert t.current_phase("acceptance-001") is PhaseState.INIT

        for next_phase in CANONICAL_PHASE_ORDER[1:]:
            t.transition_to("acceptance-001", next_phase)
            assert t.current_phase("acceptance-001") is next_phase

        assert t.history("acceptance-001") == list(CANONICAL_PHASE_ORDER)

    def test_apply_attempt_skipping_proposal_and_design_is_blocked(self):
        """Acceptance for the 'auto-pilot agent skips phases' risk
        flagged in the 2026-05-24 Gap Analysis: an autonomous flow
        cannot jump from INIT straight to APPLY without first walking
        through PROPOSAL + SPEC + DESIGN + TASK."""
        t = PhaseTracker()
        t.start("auto-pilot")

        with pytest.raises(PhaseTransitionError, match="cannot transition"):
            t.transition_to("auto-pilot", PhaseState.APPLY)

        # Tracker state is unchanged after the failed transition --
        # the failed attempt does NOT record itself in history.
        assert t.current_phase("auto-pilot") is PhaseState.INIT
        assert t.history("auto-pilot") == [PhaseState.INIT]
