"""
Tests for procedure_engine.py — Sprint 1 of Opción B.

Covers state machine transitions, pre-condition evaluation, step
executor (with SimulatedAdapter), and full procedure run end-to-end.

Run:
    pytest tests/test_procedure_engine.py -v
"""

import pathlib
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from procedure_engine import (
    _VALID_TRANSITIONS,
    AdapterRegistry,
    InvalidTransitionError,
    PreConditionEvaluator,
    ProcedureExecution,
    ProcedureNotFoundError,
    ProcedureOrchestrator,
    ProcedureRegistry,
    ProcedureState,
    SimulatedAdapter,
    StateProvider,
    StepExecutor,
    build_default_orchestrator,
)


# ═══════════════════════════════════════════════════════════════════════
#  State machine
# ═══════════════════════════════════════════════════════════════════════
class TestStateMachine:
    def _new_execution(self) -> ProcedureExecution:
        return ProcedureExecution(
            execution_id="test_exec",
            procedure_id="TEST-001",
            procedure_title="Test",
            operator="test_op",
            state=ProcedureState.CREATED,
            created_at_unix=0.0,
        )

    def test_initial_state_is_created(self):
        ex = self._new_execution()
        assert ex.state == ProcedureState.CREATED

    def test_valid_transition_created_to_pre_condition_check(self):
        ex = self._new_execution()
        ex.transition_to(ProcedureState.PRE_CONDITION_CHECK)
        assert ex.state == ProcedureState.PRE_CONDITION_CHECK

    def test_invalid_transition_created_to_in_progress_raises(self):
        ex = self._new_execution()
        with pytest.raises(InvalidTransitionError):
            ex.transition_to(ProcedureState.IN_PROGRESS)

    def test_armed_can_go_to_in_progress_or_aborted(self):
        ex = self._new_execution()
        ex.transition_to(ProcedureState.PRE_CONDITION_CHECK)
        ex.transition_to(ProcedureState.ARMED)
        # Both transitions are valid; we just check the graph allows them.
        assert ProcedureState.IN_PROGRESS in _VALID_TRANSITIONS[ProcedureState.ARMED]
        assert ProcedureState.ABORTED in _VALID_TRANSITIONS[ProcedureState.ARMED]

    def test_terminal_states_have_no_transitions(self):
        assert _VALID_TRANSITIONS[ProcedureState.COMPLETED] == set()
        assert _VALID_TRANSITIONS[ProcedureState.ABORTED] == set()

    def test_completed_cannot_transition(self):
        ex = self._new_execution()
        ex.state = ProcedureState.COMPLETED
        with pytest.raises(InvalidTransitionError):
            ex.transition_to(ProcedureState.IN_PROGRESS)

    def test_aborted_cannot_transition(self):
        ex = self._new_execution()
        ex.state = ProcedureState.ABORTED
        with pytest.raises(InvalidTransitionError):
            ex.transition_to(ProcedureState.IN_PROGRESS)

    def test_in_progress_can_only_go_to_verifying_or_aborting(self):
        valid = _VALID_TRANSITIONS[ProcedureState.IN_PROGRESS]
        assert valid == {ProcedureState.VERIFYING, ProcedureState.ABORTING}

    def test_aborting_can_only_go_to_aborted(self):
        valid = _VALID_TRANSITIONS[ProcedureState.ABORTING]
        assert valid == {ProcedureState.ABORTED}


# ═══════════════════════════════════════════════════════════════════════
#  Procedure registry (loads YAML)
# ═══════════════════════════════════════════════════════════════════════
class TestProcedureRegistry:
    def test_load_real_procedure_yml(self):
        reg = ProcedureRegistry(PROJECT_ROOT / "config" / "procedures")
        reg.load_all()
        # The MOP-ATS-MONTHLY-001 YAML should have loaded
        assert "MOP-ATS-MONTHLY-001" in reg.list_ids()

    def test_get_summary_returns_metadata(self):
        reg = ProcedureRegistry(PROJECT_ROOT / "config" / "procedures")
        reg.load_all()
        summary = reg.get_summary("MOP-ATS-MONTHLY-001")
        assert summary["procedure_id"] == "MOP-ATS-MONTHLY-001"
        assert summary["work_class"] == "PM"
        assert summary["procedure_class"] == "MOP"
        assert summary["default_lor"] == 3
        assert summary["step_count"] == 9
        assert summary["pre_condition_count"] == 4
        assert summary["has_abort_sequence"] is True

    def test_get_unknown_procedure_raises(self):
        reg = ProcedureRegistry(PROJECT_ROOT / "config" / "procedures")
        reg.load_all()
        with pytest.raises(ProcedureNotFoundError):
            reg.get("NONEXISTENT-PROCEDURE")

    def test_missing_dir_does_not_crash(self, tmp_path):
        """Graceful degradation if procedures dir missing."""
        reg = ProcedureRegistry(tmp_path / "nonexistent")
        reg.load_all()
        assert reg.list_ids() == []


# ═══════════════════════════════════════════════════════════════════════
#  Pre-condition evaluator (Sprint 1 stub level)
# ═══════════════════════════════════════════════════════════════════════
class TestPreConditionEvaluator:
    @pytest.mark.asyncio
    async def test_redundancy_2n_passes(self):
        ev = PreConditionEvaluator(StateProvider())
        results = await ev.evaluate(
            [{"id": "test1", "check": "site_redundancy_mode == '2N'", "failure_action": "ABORT"}]
        )
        assert len(results) == 1
        assert results[0]["passed"] is True

    @pytest.mark.asyncio
    async def test_no_critical_incidents_passes(self):
        ev = PreConditionEvaluator(StateProvider())
        results = await ev.evaluate(
            [{"id": "test1", "check": "severity_max < CRITICAL", "failure_action": "ABORT"}]
        )
        assert len(results) == 1
        assert results[0]["passed"] is True

    @pytest.mark.asyncio
    async def test_unsupported_check_fails_closed(self):
        """Unsupported expressions must fail closed for safety."""
        ev = PreConditionEvaluator(StateProvider())
        results = await ev.evaluate(
            [{"id": "test1", "check": "outdoor_temp_c < 35", "failure_action": "WARN"}]
        )
        assert results[0]["passed"] is False
        assert "_sprint_5_TODO" in results[0] or "_unsupported_expression" in str(
            results[0]["observed"]
        )


# ═══════════════════════════════════════════════════════════════════════
#  Adapter registry + simulated adapter
# ═══════════════════════════════════════════════════════════════════════
class TestSimulatedAdapter:
    @pytest.mark.asyncio
    async def test_simulated_write_returns_ok(self):
        adapter = SimulatedAdapter()
        result = await adapter.write("genset_a", "TRANSFER", {"test": True})
        assert result["status"] == "SIMULATED_OK"
        assert "_note" in result

    @pytest.mark.asyncio
    async def test_simulated_verify_state_returns_true(self):
        adapter = SimulatedAdapter()
        ok, observed = await adapter.verify_state("ats_a", {"position": "NORMAL"})
        assert ok is True


class TestAdapterRegistry:
    def test_unknown_adapter_falls_back_to_simulated(self):
        reg = AdapterRegistry()
        reg.register("simulated", SimulatedAdapter())
        a = reg.get("cummins")  # not registered
        assert isinstance(a, SimulatedAdapter)

    def test_registered_adapter_is_returned(self):
        reg = AdapterRegistry()
        sim = SimulatedAdapter()
        reg.register("foo", sim)
        assert reg.get("foo") is sim


# ═══════════════════════════════════════════════════════════════════════
#  Step executor
# ═══════════════════════════════════════════════════════════════════════
class TestStepExecutor:
    @pytest.fixture
    def executor(self):
        reg = AdapterRegistry()
        reg.register("simulated", SimulatedAdapter())
        return StepExecutor(reg)

    @pytest.fixture
    def execution(self):
        return ProcedureExecution(
            execution_id="exec1",
            procedure_id="P1",
            procedure_title="T",
            operator="op",
            state=ProcedureState.IN_PROGRESS,
            created_at_unix=0.0,
        )

    @pytest.mark.asyncio
    async def test_notification_step_succeeds(self, executor, execution):
        step = {"id": "s1", "title": "Notify", "type": "notification", "payload": {}}
        result = await executor.execute_step(step, execution)
        assert result.status == "OK"
        assert result.adapter_response.get("status") == "STUBBED"

    @pytest.mark.asyncio
    async def test_write_verify_step_succeeds(self, executor, execution):
        step = {
            "id": "s2",
            "title": "Write",
            "type": "write_verify",
            "adapter": "simulated",
            "target": "ats_a",
            "command": "TRANSFER",
            "payload": {},
            "verify_after": {"position": "EMERGENCY"},
        }
        result = await executor.execute_step(step, execution)
        assert result.status == "OK"

    @pytest.mark.asyncio
    async def test_dwell_step_caps_at_dev_limit(self, executor, execution):
        """Dev mode caps dwell to 0.5s for fast tests."""
        import time

        step = {"id": "s3", "title": "Wait", "type": "dwell", "duration_s": 600}
        t0 = time.time()
        result = await executor.execute_step(step, execution)
        elapsed = time.time() - t0
        assert elapsed < 1.5  # capped well below 600s
        assert result.status == "OK"
        assert "_sprint_1_dev_note" in result.adapter_response

    @pytest.mark.asyncio
    async def test_unknown_step_type_fails(self, executor, execution):
        step = {"id": "s4", "title": "Unknown", "type": "magical_unicorn"}
        result = await executor.execute_step(step, execution)
        assert result.status == "FAILED"
        assert "magical_unicorn" in result.error


# ═══════════════════════════════════════════════════════════════════════
#  Full orchestrator integration
# ═══════════════════════════════════════════════════════════════════════
class TestOrchestrator:
    @pytest.fixture
    def orchestrator(self):
        """Sprint 1 orchestrator WITHOUT witness gate. Sprint 3 adds
        witness behavior in test_witness_engine.py — these tests verify
        the unwitnessed flow."""
        from procedure_engine import (
            AdapterRegistry,
            PreConditionEvaluator,
            ProcedureRegistry,
            SimulatedAdapter,
            StateProvider,
            StepExecutor,
        )

        registry = ProcedureRegistry(PROJECT_ROOT / "config" / "procedures")
        registry.load_all()
        adapters = AdapterRegistry()
        adapters.register("simulated", SimulatedAdapter())
        evaluator = PreConditionEvaluator(StateProvider())
        executor = StepExecutor(adapters)
        # Explicitly no witness_gate — Sprint 1 tests run unwitnessed flow
        return ProcedureOrchestrator(registry, evaluator, executor, witness_gate=None)

    @pytest.mark.asyncio
    async def test_start_procedure_with_passing_preconditions_arms(self, orchestrator):
        """Pre-conditions that fail with WARN should NOT abort.
        Only ABORT-level failures stop the procedure."""
        ex = await orchestrator.start_procedure(
            procedure_id="MOP-ATS-MONTHLY-001",
            operator="test_operator",
        )
        # Sprint 1 stubs report 2 ABORT-level conds passing (redundancy_2N, no_critical)
        # and 2 WARN-level conds failing (weather, time_window) — those are tolerated.
        assert ex.state == ProcedureState.ARMED
        # The pre_condition_results should record all 4 evaluations
        assert len(ex.pre_condition_results) == 4

    @pytest.mark.asyncio
    async def test_unknown_procedure_id_raises(self, orchestrator):
        with pytest.raises(ProcedureNotFoundError):
            await orchestrator.start_procedure(
                procedure_id="NOT-A-REAL-MOP",
                operator="test",
            )

    @pytest.mark.asyncio
    async def test_advance_from_armed_runs_steps_to_completion(self, orchestrator):
        ex = await orchestrator.start_procedure(
            procedure_id="MOP-ATS-MONTHLY-001",
            operator="test_operator",
        )
        assert ex.state == ProcedureState.ARMED

        ex2 = await orchestrator.advance_to_in_progress(
            exec_id=ex.execution_id,
            operator="test_operator",
        )
        # All 9 steps should have run on simulated adapters
        assert ex2.state == ProcedureState.COMPLETED
        assert len(ex2.execution_log) == 9
        # Every step should have OK status (SimulatedAdapter never fails)
        assert all(r.status == "OK" for r in ex2.execution_log)

    @pytest.mark.asyncio
    async def test_advance_from_wrong_state_raises(self, orchestrator):
        ex = await orchestrator.start_procedure(
            procedure_id="MOP-ATS-MONTHLY-001",
            operator="test_op",
        )
        # Move it manually to COMPLETED to test the guard
        ex.state = ProcedureState.COMPLETED
        with pytest.raises(RuntimeError):
            await orchestrator.advance_to_in_progress(ex.execution_id, "test_op")

    @pytest.mark.asyncio
    async def test_abort_now_from_armed_state(self, orchestrator):
        ex = await orchestrator.start_procedure(
            procedure_id="MOP-ATS-MONTHLY-001",
            operator="test_op",
        )
        ex2 = await orchestrator.abort_now(
            exec_id=ex.execution_id,
            operator="test_op",
            reason="manual_test_abort",
        )
        assert ex2.state == ProcedureState.ABORTED
        assert "manual_test_abort" in ex2.abort_reason

    @pytest.mark.asyncio
    async def test_abort_now_idempotent_after_completion(self, orchestrator):
        """Aborting an already-completed procedure should be a no-op."""
        ex = await orchestrator.start_procedure(
            procedure_id="MOP-ATS-MONTHLY-001",
            operator="test_op",
        )
        await orchestrator.advance_to_in_progress(ex.execution_id, "test_op")
        # Now COMPLETED
        ex2 = await orchestrator.abort_now(ex.execution_id, "test_op", "too late")
        assert ex2.state == ProcedureState.COMPLETED  # unchanged

    @pytest.mark.asyncio
    async def test_failed_step_triggers_abort_sequence(self, orchestrator, monkeypatch):
        """If a step fails with abort_on_failure=true, the orchestrator
        should run the abort_sequence then transition to ABORTED."""
        # Monkey-patch SimulatedAdapter.write to fail on a specific command
        original_write = SimulatedAdapter.write

        async def failing_write(self, target, command, payload=None):
            if command == "TRANSFER_TO_EMERGENCY":
                raise RuntimeError("simulated ATS transfer failure")
            return await original_write(self, target, command, payload)

        monkeypatch.setattr(SimulatedAdapter, "write", failing_write)

        ex = await orchestrator.start_procedure("MOP-ATS-MONTHLY-001", "op")
        ex2 = await orchestrator.advance_to_in_progress(ex.execution_id, "op")

        assert ex2.state == ProcedureState.ABORTED
        # Abort reason includes the step_id of the step that failed
        assert ex2.abort_reason and "step_04_initiate_transfer" in ex2.abort_reason
        # And the original error string is captured
        assert "simulated ATS transfer failure" in ex2.abort_reason
        # The failed step should have status FAILED in the log
        failed_steps = [s for s in ex2.execution_log if s.status == "FAILED"]
        assert len(failed_steps) >= 1


# ═══════════════════════════════════════════════════════════════════════
#  Smoke: factory builds without errors
# ═══════════════════════════════════════════════════════════════════════
def test_build_default_orchestrator_smoke():
    """Just confirm the factory can construct everything from disk."""
    orch = build_default_orchestrator(PROJECT_ROOT)
    assert orch.registry.list_ids()  # at least one procedure loaded
    assert orch.executor is not None
    assert orch.evaluator is not None
