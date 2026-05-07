"""
Tests for witness_engine.py — Sprint 3 of Opción B.

Covers:
  - WitnessRequest lifecycle (create, sign, reject, expire, supersede)
  - Identity separation (IEC 62443 SR 6.1) enforcement
  - WitnessGate async waiting behavior
  - Integration: procedure_engine pauses on requires_witness=true
  - Audit: execution metadata captures witness signatures

Run:
    pytest tests/test_witness_engine.py -v
"""
import sys
import pathlib
import pytest
import asyncio
import time

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from witness_engine import (
    WitnessStatus,
    WitnessStore,
    WitnessGate,
    WitnessRequest,
    IdentityCollisionError,
    WitnessRequestNotFoundError,
    WitnessRequestNotPendingError,
    DEFAULT_WITNESS_TTL_S,
    serialize_request,
)


# ═══════════════════════════════════════════════════════════════════════
#  WitnessStore — basic CRUD
# ═══════════════════════════════════════════════════════════════════════
class TestWitnessStoreBasic:

    def _make_store(self) -> WitnessStore:
        return WitnessStore()

    def test_create_request_returns_pending(self):
        store = self._make_store()
        req = store.create(
            execution_id="exec-1",
            procedure_id="MOP-001",
            step_id="step_03",
            step_title="Arm ATS",
            step_payload={"id": "step_03", "type": "write_verify"},
            initiator="alice",
        )
        assert req.status == WitnessStatus.PENDING
        assert req.initiator == "alice"
        assert req.witness is None

    def test_get_returns_existing_request(self):
        store = self._make_store()
        req = store.create("exec-1", "MOP-001", "step_03", "Arm",
                           {}, "alice")
        retrieved = store.get(req.request_id)
        assert retrieved.request_id == req.request_id
        assert retrieved.initiator == "alice"

    def test_get_unknown_request_raises(self):
        store = self._make_store()
        with pytest.raises(WitnessRequestNotFoundError):
            store.get("nonexistent_id")

    def test_list_pending_returns_only_pending(self):
        store = self._make_store()
        r1 = store.create("exec-1", "MOP-001", "step_03", "A", {}, "alice")
        r2 = store.create("exec-2", "MOP-001", "step_04", "B", {}, "alice")
        store.sign(r1.request_id, "bob")    # r1 now SIGNED

        pending = store.list_pending()
        assert len(pending) == 1
        assert pending[0].request_id == r2.request_id

    def test_list_for_execution_filters(self):
        store = self._make_store()
        r1 = store.create("exec-1", "MOP-001", "step_03", "A", {}, "alice")
        r2 = store.create("exec-2", "MOP-001", "step_04", "B", {}, "alice")
        r3 = store.create("exec-1", "MOP-001", "step_05", "C", {}, "alice")

        for_exec1 = store.list_for_execution("exec-1")
        assert len(for_exec1) == 2
        assert {r.request_id for r in for_exec1} == {r1.request_id, r3.request_id}


# ═══════════════════════════════════════════════════════════════════════
#  Identity separation (IEC 62443 SR 6.1)
# ═══════════════════════════════════════════════════════════════════════
class TestIdentitySeparation:
    """The single most important property of this module."""

    def test_different_identity_can_sign(self):
        store = WitnessStore()
        req = store.create("exec-1", "MOP-001", "step_03", "Arm",
                           {}, initiator="alice")
        signed = store.sign(req.request_id, witness="bob")
        assert signed.status == WitnessStatus.SIGNED
        assert signed.witness == "bob"

    def test_same_identity_cannot_sign(self):
        store = WitnessStore()
        req = store.create("exec-1", "MOP-001", "step_03", "Arm",
                           {}, initiator="alice")
        with pytest.raises(IdentityCollisionError):
            store.sign(req.request_id, witness="alice")

    def test_same_identity_cannot_reject(self):
        store = WitnessStore()
        req = store.create("exec-1", "MOP-001", "step_03", "Arm",
                           {}, initiator="alice")
        with pytest.raises(IdentityCollisionError):
            store.reject(req.request_id, witness="alice", reason="self-test")

    def test_empty_witness_identity_rejected(self):
        store = WitnessStore()
        req = store.create("exec-1", "MOP-001", "step_03", "Arm",
                           {}, initiator="alice")
        with pytest.raises(IdentityCollisionError):
            store.sign(req.request_id, witness="")

    def test_whitespace_witness_identity_rejected(self):
        store = WitnessStore()
        req = store.create("exec-1", "MOP-001", "step_03", "Arm",
                           {}, initiator="alice")
        with pytest.raises(IdentityCollisionError):
            store.sign(req.request_id, witness="   ")

    def test_request_status_unchanged_after_failed_sign(self):
        """If sign() raises, the request stays PENDING (not corrupted)."""
        store = WitnessStore()
        req = store.create("exec-1", "MOP-001", "step_03", "Arm",
                           {}, initiator="alice")
        try:
            store.sign(req.request_id, witness="alice")
        except IdentityCollisionError:
            pass
        assert store.get(req.request_id).status == WitnessStatus.PENDING


# ═══════════════════════════════════════════════════════════════════════
#  Rejection workflow
# ═══════════════════════════════════════════════════════════════════════
class TestRejection:

    def test_reject_with_reason(self):
        store = WitnessStore()
        req = store.create("exec-1", "MOP-001", "step_03", "Arm",
                           {}, initiator="alice")
        rejected = store.reject(
            req.request_id, witness="bob", reason="weather looks unsafe"
        )
        assert rejected.status == WitnessStatus.REJECTED
        assert rejected.witness == "bob"
        assert rejected.rejection_reason == "weather looks unsafe"

    def test_cannot_reject_already_signed(self):
        store = WitnessStore()
        req = store.create("exec-1", "MOP-001", "step_03", "Arm",
                           {}, initiator="alice")
        store.sign(req.request_id, "bob")
        with pytest.raises(WitnessRequestNotPendingError):
            store.reject(req.request_id, "carol", "changed my mind")

    def test_cannot_sign_already_rejected(self):
        store = WitnessStore()
        req = store.create("exec-1", "MOP-001", "step_03", "Arm",
                           {}, initiator="alice")
        store.reject(req.request_id, "bob", "no")
        with pytest.raises(WitnessRequestNotPendingError):
            store.sign(req.request_id, "carol")


# ═══════════════════════════════════════════════════════════════════════
#  Expiry & supersede
# ═══════════════════════════════════════════════════════════════════════
class TestExpiryAndSupersede:

    def test_expired_request_marked_on_get(self):
        store = WitnessStore()
        req = store.create("exec-1", "MOP-001", "step_03", "Arm",
                           {}, initiator="alice", ttl_s=1)
        time.sleep(1.2)
        retrieved = store.get(req.request_id)
        assert retrieved.status == WitnessStatus.EXPIRED

    def test_expired_excluded_from_list_pending(self):
        store = WitnessStore()
        store.create("exec-1", "MOP-001", "step_03", "Arm",
                     {}, initiator="alice", ttl_s=1)
        time.sleep(1.2)
        assert store.list_pending() == []

    def test_cannot_sign_expired(self):
        store = WitnessStore()
        req = store.create("exec-1", "MOP-001", "step_03", "Arm",
                           {}, initiator="alice", ttl_s=1)
        time.sleep(1.2)
        with pytest.raises(WitnessRequestNotPendingError):
            store.sign(req.request_id, "bob")

    def test_supersede_marks_pending_as_superseded(self):
        store = WitnessStore()
        r1 = store.create("exec-1", "MOP-001", "step_03", "A", {}, "alice")
        r2 = store.create("exec-1", "MOP-001", "step_04", "B", {}, "alice")
        r3 = store.create("exec-2", "MOP-001", "step_03", "C", {}, "alice")

        count = store.supersede_for_execution("exec-1")
        assert count == 2
        assert store.get(r1.request_id).status == WitnessStatus.SUPERSEDED
        assert store.get(r2.request_id).status == WitnessStatus.SUPERSEDED
        # r3 (different execution) untouched
        assert store.get(r3.request_id).status == WitnessStatus.PENDING

    def test_supersede_does_not_affect_signed_requests(self):
        store = WitnessStore()
        r1 = store.create("exec-1", "MOP-001", "step_03", "A", {}, "alice")
        store.sign(r1.request_id, "bob")
        store.supersede_for_execution("exec-1")
        # Still SIGNED, not SUPERSEDED
        assert store.get(r1.request_id).status == WitnessStatus.SIGNED


# ═══════════════════════════════════════════════════════════════════════
#  WitnessGate — async waiting
# ═══════════════════════════════════════════════════════════════════════
class TestWitnessGate:

    @pytest.mark.asyncio
    async def test_gate_returns_signed_when_witness_signs(self):
        store = WitnessStore()
        gate = WitnessGate(store, poll_interval_s=0.05, timeout_s=2.0)

        async def sign_after_delay():
            await asyncio.sleep(0.2)
            pending = store.list_pending()
            if pending:
                store.sign(pending[0].request_id, "bob")

        signer_task = asyncio.create_task(sign_after_delay())

        result = await gate.await_witness(
            execution_id="exec-1",
            procedure_id="MOP-001",
            step={"id": "step_03", "title": "Arm ATS"},
            initiator="alice",
        )

        await signer_task
        assert result.status == WitnessStatus.SIGNED
        assert result.witness == "bob"

    @pytest.mark.asyncio
    async def test_gate_returns_rejected_when_witness_rejects(self):
        store = WitnessStore()
        gate = WitnessGate(store, poll_interval_s=0.05, timeout_s=2.0)

        async def reject_after_delay():
            await asyncio.sleep(0.2)
            pending = store.list_pending()
            if pending:
                store.reject(pending[0].request_id, "bob", "unsafe conditions")

        rejecter_task = asyncio.create_task(reject_after_delay())

        result = await gate.await_witness(
            execution_id="exec-1",
            procedure_id="MOP-001",
            step={"id": "step_03", "title": "Arm ATS"},
            initiator="alice",
        )

        await rejecter_task
        assert result.status == WitnessStatus.REJECTED
        assert result.rejection_reason == "unsafe conditions"

    @pytest.mark.asyncio
    async def test_gate_returns_expired_on_timeout(self):
        store = WitnessStore()
        # Very short timeout so test is fast
        gate = WitnessGate(store, poll_interval_s=0.05, timeout_s=0.5)

        result = await gate.await_witness(
            execution_id="exec-1",
            procedure_id="MOP-001",
            step={"id": "step_03", "title": "Arm ATS"},
            initiator="alice",
        )

        assert result.status == WitnessStatus.EXPIRED


# ═══════════════════════════════════════════════════════════════════════
#  Integration: procedure_engine pauses on requires_witness
# ═══════════════════════════════════════════════════════════════════════
class TestProcedureIntegration:

    @pytest.fixture
    def orchestrator_with_witness(self):
        """Build orchestrator with a fresh WitnessStore + WitnessGate."""
        from procedure_engine import (
            ProcedureRegistry, PreConditionEvaluator, StateProvider,
            AdapterRegistry, SimulatedAdapter, StepExecutor, ProcedureOrchestrator,
        )
        registry = ProcedureRegistry(PROJECT_ROOT / "config" / "procedures")
        registry.load_all()

        adapters = AdapterRegistry()
        adapters.register("simulated", SimulatedAdapter())

        store = WitnessStore()
        # Timeout must accommodate 3 witness steps with 5s dwells between.
        # Keep relatively short so test failures don't hang for long.
        gate = WitnessGate(store, poll_interval_s=0.05, timeout_s=15.0)

        evaluator = PreConditionEvaluator(StateProvider())
        executor = StepExecutor(adapters)
        return ProcedureOrchestrator(
            registry, evaluator, executor, witness_gate=gate
        ), store

    @pytest.mark.asyncio
    async def test_procedure_pauses_at_witness_step_then_proceeds(
        self, orchestrator_with_witness
    ):
        from procedure_engine import ProcedureState
        orch, store = orchestrator_with_witness

        # Background task that signs witness requests as they appear.
        # Need to run long enough to cover all 3 witness steps in the MOP
        # (step_03, step_04, step_07) — there is a 5s dev-mode dwell
        # between them. Loop for ~30s with short polls.
        async def auto_sign_loop():
            deadline = time.time() + 30.0
            while time.time() < deadline:
                await asyncio.sleep(0.05)
                pending = store.list_pending()
                for req in pending:
                    if req.initiator != "operator_b":
                        try:
                            store.sign(req.request_id, "operator_b")
                        except WitnessRequestNotPendingError:
                            pass    # already signed by another iteration

        signer = asyncio.create_task(auto_sign_loop())

        ex = await orch.start_procedure("MOP-ATS-MONTHLY-001", "operator_a")
        ex2 = await orch.advance_to_in_progress(ex.execution_id, "operator_a")

        signer.cancel()
        try:
            await signer
        except asyncio.CancelledError:
            pass

        # All 9 steps should have completed; 3 of them requires_witness=true
        assert ex2.state == ProcedureState.COMPLETED
        sigs = ex2.metadata.get("witness_signatures", [])
        assert len(sigs) == 3
        for sig in sigs:
            assert sig["witness"] == "operator_b"

        # Audit trail: those 3 step results have witness_acknowledged_by set
        witnessed_steps = [
            r for r in ex2.execution_log
            if r.witness_acknowledged_by == "operator_b"
        ]
        assert len(witnessed_steps) == 3

    @pytest.mark.asyncio
    async def test_procedure_aborts_when_witness_rejects(
        self, orchestrator_with_witness
    ):
        from procedure_engine import ProcedureState
        orch, store = orchestrator_with_witness

        async def reject_loop():
            for _ in range(20):
                await asyncio.sleep(0.05)
                pending = store.list_pending()
                for req in pending:
                    if req.initiator != "operator_b":
                        store.reject(req.request_id, "operator_b", "unsafe right now")
                        return

        rejecter = asyncio.create_task(reject_loop())

        ex = await orch.start_procedure("MOP-ATS-MONTHLY-001", "operator_a")
        ex2 = await orch.advance_to_in_progress(ex.execution_id, "operator_a")

        rejecter.cancel()
        try:
            await rejecter
        except asyncio.CancelledError:
            pass

        # Procedure should have aborted at the first witness step
        assert ex2.state == ProcedureState.ABORTED
        assert "witness" in (ex2.abort_reason or "").lower()

    @pytest.mark.asyncio
    async def test_procedure_aborts_on_witness_timeout(
        self, orchestrator_with_witness
    ):
        from procedure_engine import ProcedureState
        orch, _store = orchestrator_with_witness

        # No signer task — witness will time out (2s in the fixture)
        ex = await orch.start_procedure("MOP-ATS-MONTHLY-001", "operator_a")
        ex2 = await orch.advance_to_in_progress(ex.execution_id, "operator_a")

        assert ex2.state == ProcedureState.ABORTED


# ═══════════════════════════════════════════════════════════════════════
#  Serialization helpers
# ═══════════════════════════════════════════════════════════════════════
class TestSerialization:

    def test_serialize_request_returns_json_safe_dict(self):
        store = WitnessStore()
        req = store.create("exec-1", "MOP-001", "step_03", "Arm",
                           {"id": "step_03", "type": "write_verify"}, "alice")

        d = serialize_request(req)
        assert isinstance(d, dict)
        assert d["status"] == "PENDING"      # enum converted to string
        assert d["initiator"] == "alice"
        assert d["request_id"] == req.request_id
        # Should be JSON-serializable
        import json
        json.dumps(d)
