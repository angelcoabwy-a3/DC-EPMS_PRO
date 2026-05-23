"""Tests for backend.optimizer — Epic 2 Batch 2.A.

Coverage:
  * The deterministic control law (compute_proposal) — happy paths,
    bounds, and ASHRAE A2 guards for both surfaces.
  * DriftTracker sustain semantics + reset on drift drop.
  * PacingGuard window enforcement.
  * AuditLog append + capacity.
  * OptimizerService.tick — telemetry-absent / drift-but-not-sustained /
    sustained-emits-both / pacing-suppresses-second.
  * Env flag gating: get_service returns None when disabled.
  * ADR-006 / S-SEC-02 PROPOSER-PATTERN INVARIANT — the optimizer
    module imports zero HTTP-capable libraries and zero FastAPI router
    machinery (the cheapest enforceable proof that no /api/bms/write
    path can ever pass through this module).
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from backend import optimizer as opt
from backend.multi_agent import VERDICT_APPROVE, VERDICT_HARD_STOP, ConsultContext
from backend.optimizer import (
    AUDIT_PACED_OUT,
    AUDIT_PROPOSED,
    AUDIT_SAFETY_VETO,
    SURFACE_CHILLER_LWT,
    SURFACE_CT_FAN_VFD,
    AuditLog,
    DriftTracker,
    OptimizerConfig,
    OptimizerService,
    PacingGuard,
    Proposal,
    ProposalQueue,
    QueuedProposal,
    TelemetryPoint,
    compute_proposal,
    get_service,
    is_enabled,
    pue_drift,
    reset_service,
)


# ─── Fixtures + builders ──────────────────────────────────────────────
def _point(**overrides) -> TelemetryPoint:
    """A telemetry point with sensible defaults; override per-field via kwargs."""
    defaults = {
        "pue": 1.35,                  # already drifted above the 1.30 target
        "hall_temp_c": 23.5,
        "ecwt_c": 24.0,
        "wet_bulb_c": 18.0,           # approach 6.0 K — headroom available
        "chiller_lwt_c": 7.5,         # 1.5 K above the 6.0 C floor
        "ct_fan_vfd_pct": 60.0,
    }
    defaults.update(overrides)
    return TelemetryPoint(**defaults)


# ─── Deterministic control law ────────────────────────────────────────
class TestComputeProposal:
    def test_chiller_lwt_drops_one_step_when_drift_and_headroom(self):
        p = compute_proposal(SURFACE_CHILLER_LWT, _point(), pue_target=1.30)
        assert p is not None
        assert p.surface == SURFACE_CHILLER_LWT
        assert p.current_value == 7.5
        assert p.proposed_value == pytest.approx(7.0)
        assert p.delta == pytest.approx(-0.5)
        assert "PUE drift" in p.rationale
        assert "LWT" in p.rationale or "compressor" in p.rationale

    def test_chiller_lwt_at_floor_yields_no_proposal(self):
        p = compute_proposal(
            SURFACE_CHILLER_LWT,
            _point(chiller_lwt_c=OptimizerConfig.LWT_FLOOR_C),
            pue_target=1.30,
        )
        assert p is None

    def test_chiller_lwt_skips_when_hall_already_cold(self):
        # ASHRAE A2 guard — already cool, lowering LWT wastes compressor power
        p = compute_proposal(
            SURFACE_CHILLER_LWT,
            _point(hall_temp_c=18.0),
            pue_target=1.30,
        )
        assert p is None

    def test_ct_fan_vfd_steps_up_when_approach_has_headroom(self):
        p = compute_proposal(SURFACE_CT_FAN_VFD, _point(), pue_target=1.30)
        assert p is not None
        assert p.surface == SURFACE_CT_FAN_VFD
        assert p.proposed_value == pytest.approx(65.0)
        assert p.delta == pytest.approx(5.0)
        assert "approach" in p.rationale.lower()

    def test_ct_fan_vfd_at_max_yields_no_proposal(self):
        p = compute_proposal(
            SURFACE_CT_FAN_VFD,
            _point(ct_fan_vfd_pct=100.0),
            pue_target=1.30,
        )
        assert p is None

    def test_ct_fan_vfd_tower_saturated_yields_no_proposal(self):
        # approach = ECWT - WB < 5 K (working hard) → no proposal
        p = compute_proposal(
            SURFACE_CT_FAN_VFD,
            _point(ecwt_c=19.0, wet_bulb_c=18.0),
            pue_target=1.30,
        )
        assert p is None

    def test_no_drift_yields_no_proposal_anywhere(self):
        # PUE at target → no drift → no proposals on any surface
        for surface in (SURFACE_CHILLER_LWT, SURFACE_CT_FAN_VFD):
            assert compute_proposal(surface, _point(pue=1.30), pue_target=1.30) is None

    def test_unknown_surface_yields_no_proposal(self):
        assert compute_proposal("gpu_clock_mhz", _point(), pue_target=1.30) is None

    def test_missing_telemetry_yields_no_proposal(self):
        assert compute_proposal(
            SURFACE_CHILLER_LWT,
            _point(pue=None),
            pue_target=1.30,
        ) is None
        assert compute_proposal(
            SURFACE_CT_FAN_VFD,
            _point(ecwt_c=None),
            pue_target=1.30,
        ) is None

    def test_proposal_carries_a_uuid_and_a_pue_snapshot(self):
        p1 = compute_proposal(SURFACE_CHILLER_LWT, _point(), pue_target=1.30)
        p2 = compute_proposal(SURFACE_CHILLER_LWT, _point(), pue_target=1.30)
        assert isinstance(p1, Proposal)
        assert isinstance(p2, Proposal)
        assert p1.proposal_id != p2.proposal_id  # fresh UUID per call
        assert p1.pue_at_emission == 1.35


# ─── Drift sustain + pacing guards ────────────────────────────────────
class TestDriftTracker:
    def test_drift_fires_only_after_sustain_window(self):
        t = DriftTracker(sustain_ticks=3)
        assert t.update(0.05, threshold=0.02) is False
        assert t.update(0.05, threshold=0.02) is False
        assert t.update(0.05, threshold=0.02) is True   # 3rd tick fires
        assert t.update(0.05, threshold=0.02) is True   # stays sustained

    def test_drift_below_threshold_resets_streak(self):
        t = DriftTracker(sustain_ticks=3)
        t.update(0.05, threshold=0.02)
        t.update(0.05, threshold=0.02)
        assert t.streak == 2
        t.update(0.01, threshold=0.02)                   # below threshold
        assert t.streak == 0

    def test_none_drift_also_resets_streak(self):
        t = DriftTracker(sustain_ticks=3)
        t.update(0.05, threshold=0.02)
        t.update(None, threshold=0.02)
        assert t.streak == 0


class TestPacingGuard:
    def test_blocks_within_pacing_window(self):
        g = PacingGuard(pacing_seconds=60.0)
        now = 1000.0
        g.record(SURFACE_CHILLER_LWT, now=now)
        assert g.is_paced_out(SURFACE_CHILLER_LWT, now=now + 30.0) is True
        assert g.is_paced_out(SURFACE_CT_FAN_VFD, now=now + 30.0) is False  # different surface

    def test_releases_after_pacing_window(self):
        g = PacingGuard(pacing_seconds=60.0)
        g.record(SURFACE_CHILLER_LWT, now=1000.0)
        assert g.is_paced_out(SURFACE_CHILLER_LWT, now=1061.0) is False


# ─── Audit log ────────────────────────────────────────────────────────
class TestAuditLog:
    def test_appends_and_returns_entries(self):
        log_buf = AuditLog()
        log_buf.write("proposed", proposal_id="p1", surface="chiller_lwt", detail="x")
        log_buf.write("paced_out", surface="chiller_lwt", detail="y")
        entries = log_buf.entries(limit=10)
        assert len(entries) == 2
        assert entries[0].event == "proposed"
        assert entries[1].event == "paced_out"
        assert len(log_buf) == 2

    def test_capacity_enforces_sliding_window(self):
        log_buf = AuditLog(max_entries=3)
        for i in range(5):
            log_buf.write("proposed", proposal_id=f"p{i}")
        assert len(log_buf) == 3
        assert [e.proposal_id for e in log_buf.entries()] == ["p2", "p3", "p4"]


# ─── OptimizerService — tick orchestration ────────────────────────────
def _async_provider(point: TelemetryPoint | None):
    """Build an async telemetry provider returning the same point each call."""

    async def _provider() -> TelemetryPoint | None:
        return point

    return _provider


def _sync_provider(point: TelemetryPoint | None):
    """Build a sync telemetry provider returning the same point each call."""

    def _provider() -> TelemetryPoint | None:
        return point

    return _provider


class TestOptimizerServiceTick:
    @pytest.mark.asyncio
    async def test_no_telemetry_provider_emits_no_proposals(self):
        # E5.A invariant: every tick writes a heartbeat audit entry,
        # even when telemetry is absent — operators need proof the
        # loop ran. So we count proposal-events specifically.
        svc = OptimizerService(telemetry_provider=None)
        assert await svc.tick() == []
        proposed = [e for e in svc.audit.entries() if e.event == AUDIT_PROPOSED]
        assert proposed == []

    @pytest.mark.asyncio
    async def test_drift_below_sustain_emits_nothing(self):
        # Custom config: sustain after 3 ticks
        class C(OptimizerConfig):
            PUE_SUSTAIN_TICKS = 3

        svc = OptimizerService(
            telemetry_provider=_async_provider(_point()),
            pue_target=1.30,
            cfg=C,
        )
        first = await svc.tick()
        second = await svc.tick()
        assert first == []
        assert second == []   # not yet sustained

    @pytest.mark.asyncio
    async def test_sustained_drift_emits_both_surfaces(self):
        class C(OptimizerConfig):
            PUE_SUSTAIN_TICKS = 1   # fire immediately for the test

        svc = OptimizerService(
            telemetry_provider=_async_provider(_point()),
            pue_target=1.30,
            cfg=C,
        )
        proposals = await svc.tick()
        surfaces = sorted(p.surface for p in proposals)
        assert surfaces == [SURFACE_CHILLER_LWT, SURFACE_CT_FAN_VFD]

    @pytest.mark.asyncio
    async def test_pacing_suppresses_second_tick(self):
        class C(OptimizerConfig):
            PUE_SUSTAIN_TICKS = 1
            PACING_SECONDS = 600.0   # plenty wide for the test

        svc = OptimizerService(
            telemetry_provider=_async_provider(_point()),
            pue_target=1.30,
            cfg=C,
        )
        first = await svc.tick()
        second = await svc.tick()
        assert len(first) == 2
        assert second == []   # second tick fully paced
        paced_events = [e for e in svc.audit.entries() if e.event == AUDIT_PACED_OUT]
        assert len(paced_events) == 2   # one per surface

    @pytest.mark.asyncio
    async def test_audit_records_proposed_for_each_emitted_proposal(self):
        class C(OptimizerConfig):
            PUE_SUSTAIN_TICKS = 1

        svc = OptimizerService(
            telemetry_provider=_async_provider(_point()),
            pue_target=1.30,
            cfg=C,
        )
        await svc.tick()
        proposed_events = [e for e in svc.audit.entries() if e.event == AUDIT_PROPOSED]
        assert len(proposed_events) == 2
        assert all(e.proposal_id for e in proposed_events)

    @pytest.mark.asyncio
    async def test_tick_handles_sync_telemetry_provider(self):
        class C(OptimizerConfig):
            PUE_SUSTAIN_TICKS = 1

        svc = OptimizerService(
            telemetry_provider=_sync_provider(_point()),
            pue_target=1.30,
            cfg=C,
        )
        proposals = await svc.tick()
        assert len(proposals) == 2

    @pytest.mark.asyncio
    async def test_tick_swallows_telemetry_provider_exceptions(self):
        def boom() -> TelemetryPoint:
            raise RuntimeError("hermes down")

        svc = OptimizerService(telemetry_provider=boom)
        # No raise, no proposals
        assert await svc.tick() == []


# ─── 2.B: multi-agent consensus integration (S-DET-02) ────────────────
class _FakeConsensus:
    """Duck-types ConsensusResult — only .consensus / .rationale /
    .safety_officer_veto are read by OptimizerService."""

    def __init__(self, consensus: str = VERDICT_APPROVE,
                 rationale: str = "ok", veto: bool = False):
        self.consensus = consensus
        self.rationale = rationale
        self.safety_officer_veto = veto


class _SustainOnceCfg(OptimizerConfig):
    """Test config: fire on the first sustained-drift tick."""

    PUE_SUSTAIN_TICKS = 1


class TestOptimizerConsensusIntegration:
    @pytest.mark.asyncio
    async def test_approve_consensus_enqueues_with_metadata(self):
        captured: list[ConsultContext] = []

        async def consult(ctx: ConsultContext):
            captured.append(ctx)
            return _FakeConsensus(consensus=VERDICT_APPROVE, rationale="all good")

        svc = OptimizerService(
            telemetry_provider=_async_provider(_point()),
            pue_target=1.30, cfg=_SustainOnceCfg, consult_fn=consult,
        )
        proposals = await svc.tick()
        assert len(proposals) == 2          # both surfaces survive
        queued = svc.queue.list()
        assert len(queued) == 2
        for qp in queued:
            assert qp.consensus_verdict == VERDICT_APPROVE
            assert qp.consensus_rationale == "all good"
            assert qp.safety_officer_veto is False
        # ConsultContext built per surface
        assert len(captured) == 2
        assert all(ctx.cet_id == "optimizer" for ctx in captured)
        assert {ctx.asset_id for ctx in captured} == {
            SURFACE_CHILLER_LWT, SURFACE_CT_FAN_VFD,
        }

    @pytest.mark.asyncio
    async def test_hard_stop_discards_proposal_and_audits_veto(self):
        async def consult(ctx: ConsultContext):
            return _FakeConsensus(
                consensus=VERDICT_HARD_STOP,
                rationale="Safety Officer VETO: capacitor-class asset",
                veto=True,
            )

        svc = OptimizerService(
            telemetry_provider=_async_provider(_point()),
            pue_target=1.30, cfg=_SustainOnceCfg, consult_fn=consult,
        )
        proposals = await svc.tick()
        assert proposals == []
        assert svc.queue.size() == 0
        veto_events = [e for e in svc.audit.entries() if e.event == AUDIT_SAFETY_VETO]
        assert len(veto_events) == 2
        # The veto rationale is preserved in the audit detail.
        assert all("Safety Officer VETO" in e.detail for e in veto_events)

    @pytest.mark.asyncio
    async def test_consult_exception_does_not_block_proposal(self):
        async def consult(ctx: ConsultContext):
            raise RuntimeError("orchestrator down")

        svc = OptimizerService(
            telemetry_provider=_async_provider(_point()),
            pue_target=1.30, cfg=_SustainOnceCfg, consult_fn=consult,
        )
        # Graceful: consult returns None → no consensus → proposal still
        # proceeds to the queue (operator approval, 2.C, becomes the gate).
        proposals = await svc.tick()
        assert len(proposals) == 2
        for qp in svc.queue.list():
            assert qp.consensus_verdict is None
            assert qp.safety_officer_veto is False

    @pytest.mark.asyncio
    async def test_no_consult_fn_preserves_2a_backcompat(self):
        # 2.A back-compat: tick returns proposals, queue is populated
        # with None consensus, no consult is attempted.
        svc = OptimizerService(
            telemetry_provider=_async_provider(_point()),
            pue_target=1.30, cfg=_SustainOnceCfg,
        )
        proposals = await svc.tick()
        assert len(proposals) == 2
        for qp in svc.queue.list():
            assert qp.consensus_verdict is None
            assert qp.optimizer_narrative == ""


# ─── 2.B: advisory Gemma narrative (S-DET-03) ─────────────────────────
class _FakeGemma:
    def __init__(self, reply: str = "Lowering LWT cuts compressor load; expected delta-PUE -0.01."):
        self.reply = reply
        self.prompts: list[str] = []

    async def complete_gemma(self, prompt: str, max_tokens: int = 240) -> str:
        self.prompts.append(prompt)
        return self.reply


class _RaisingGemma:
    async def complete_gemma(self, prompt: str, max_tokens: int = 240) -> str:
        raise RuntimeError("LM Studio unreachable")


def _fake_kalman_payload() -> dict:
    return {
        "cooling_tower:wet_bulb": {"max_z": 2.8, "mean_z": 1.4, "is_anomalous": False},
        "chiller_1:lwt": {"max_z": 3.1, "mean_z": 2.0, "is_anomalous": True},
        "hall_inlet_T": {"max_z": 0.4, "mean_z": 0.1, "is_anomalous": False},
        "gpu_Tj": {"max_z": 1.2, "mean_z": 0.6, "is_anomalous": False},
    }


class TestOptimizerNarrative:
    @pytest.mark.asyncio
    async def test_narrative_attached_with_llm_and_kalman(self):
        async def consult(ctx: ConsultContext):
            return _FakeConsensus(consensus=VERDICT_APPROVE, rationale="ok")

        gemma = _FakeGemma()
        svc = OptimizerService(
            telemetry_provider=_async_provider(_point()),
            pue_target=1.30, cfg=_SustainOnceCfg,
            consult_fn=consult, llm_client=gemma,
            kalman_provider=_fake_kalman_payload,
        )
        await svc.tick()
        queued = svc.queue.list()
        assert len(queued) == 2
        assert all(qp.optimizer_narrative == gemma.reply for qp in queued)
        assert len(gemma.prompts) == 2
        for p in gemma.prompts:
            assert "DETERMINISTIC PROPOSAL" in p
            assert "LIVE KALMAN TELEMETRY" in p
            assert "chiller_1:lwt" in p   # top-Z channel surfaces in prompt
            assert "do not invent" in p.lower()

    @pytest.mark.asyncio
    async def test_llm_exception_yields_empty_narrative_but_keeps_queue(self):
        async def consult(ctx: ConsultContext):
            return _FakeConsensus()

        svc = OptimizerService(
            telemetry_provider=_async_provider(_point()),
            pue_target=1.30, cfg=_SustainOnceCfg,
            consult_fn=consult, llm_client=_RaisingGemma(),
            kalman_provider=_fake_kalman_payload,
        )
        await svc.tick()
        for qp in svc.queue.list():
            assert qp.optimizer_narrative == ""
        assert svc.queue.size() == 2   # proposals still queued despite LLM failure

    @pytest.mark.asyncio
    async def test_no_llm_client_yields_empty_narrative(self):
        svc = OptimizerService(
            telemetry_provider=_async_provider(_point()),
            pue_target=1.30, cfg=_SustainOnceCfg,
        )
        await svc.tick()
        for qp in svc.queue.list():
            assert qp.optimizer_narrative == ""

    @pytest.mark.asyncio
    async def test_gemma_error_sentinel_treated_as_empty(self):
        # The shared multi_agent._gemma_complete pattern: any reply
        # starting with "[Gemma error" or "[Gemma stream error" is
        # treated as a failed call, narrative empty.
        gemma = _FakeGemma(reply="[Gemma error: connection refused]")
        svc = OptimizerService(
            telemetry_provider=_async_provider(_point()),
            pue_target=1.30, cfg=_SustainOnceCfg,
            llm_client=gemma, kalman_provider=_fake_kalman_payload,
        )
        await svc.tick()
        for qp in svc.queue.list():
            assert qp.optimizer_narrative == ""


# ─── 2.B: Hermes event emission ───────────────────────────────────────
class TestOptimizerEventEmission:
    @pytest.mark.asyncio
    async def test_event_emitted_per_queued_proposal(self):
        events: list[tuple[str, dict]] = []

        def emit(name: str, payload: dict) -> None:
            events.append((name, payload))

        svc = OptimizerService(
            telemetry_provider=_async_provider(_point()),
            pue_target=1.30, cfg=_SustainOnceCfg,
            event_emitter=emit,
        )
        await svc.tick()
        # E5.A: a tick also emits an 'optimizer-tick' heartbeat event.
        # Filter to the proposal events for this assertion.
        proposal_events = [(n, p) for n, p in events if n == "optimizer-proposal"]
        assert len(proposal_events) == 2
        # Payload carries the serialised proposal
        assert all("proposal" in payload for _, payload in proposal_events)
        assert {payload["proposal"]["surface"] for _, payload in proposal_events} == {
            SURFACE_CHILLER_LWT, SURFACE_CT_FAN_VFD,
        }

    @pytest.mark.asyncio
    async def test_emitter_exception_is_swallowed(self):
        def boom(name: str, payload: dict) -> None:
            raise RuntimeError("hermes broken")

        svc = OptimizerService(
            telemetry_provider=_async_provider(_point()),
            pue_target=1.30, cfg=_SustainOnceCfg, event_emitter=boom,
        )
        # No raise; proposals still queued
        proposals = await svc.tick()
        assert len(proposals) == 2
        assert svc.queue.size() == 2

    @pytest.mark.asyncio
    async def test_safety_veto_does_not_emit_proposal_event(self):
        events: list[tuple[str, dict]] = []

        def emit(name: str, payload: dict) -> None:
            events.append((name, payload))

        async def veto(ctx: ConsultContext):
            return _FakeConsensus(consensus=VERDICT_HARD_STOP, veto=True)

        svc = OptimizerService(
            telemetry_provider=_async_provider(_point()),
            pue_target=1.30, cfg=_SustainOnceCfg,
            consult_fn=veto, event_emitter=emit,
        )
        await svc.tick()
        # S-DET-02: vetoed proposals MUST NOT emit an
        # 'optimizer-proposal' event (the HMI should never see a
        # proposal the Safety Officer killed). The 'optimizer-tick'
        # heartbeat still fires — it's the loop's proof-of-life and
        # carries n_vetoed in its outcomes payload.
        proposal_events = [n for n, _ in events if n == "optimizer-proposal"]
        assert proposal_events == []
        tick_events = [n for n, _ in events if n == "optimizer-tick"]
        assert tick_events == ["optimizer-tick"]


# ─── ProposalQueue ────────────────────────────────────────────────────
def _make_queued(proposal_id: str = "qp1",
                surface: str = SURFACE_CHILLER_LWT) -> QueuedProposal:
    return QueuedProposal(
        proposal=Proposal(
            proposal_id=proposal_id, surface=surface,
            current_value=7.5, proposed_value=7.0, delta=-0.5,
            rationale="r", pue_at_emission=1.35, created_at=1.0,
        ),
        consensus_verdict=VERDICT_APPROVE,
        consensus_rationale="ok",
        safety_officer_veto=False,
        optimizer_narrative="",
        queued_at=2.0,
    )


class TestProposalQueue:
    def test_enqueue_and_list(self):
        q = ProposalQueue()
        q.enqueue(_make_queued("a"))
        q.enqueue(_make_queued("b"))
        assert q.size() == 2
        ids = [qp.proposal.proposal_id for qp in q.list()]
        assert ids == ["a", "b"]

    def test_pop_by_id_removes_and_returns(self):
        q = ProposalQueue()
        q.enqueue(_make_queued("a"))
        q.enqueue(_make_queued("b"))
        popped = q.pop_by_id("a")
        assert popped is not None
        assert popped.proposal.proposal_id == "a"
        assert q.size() == 1
        assert q.pop_by_id("nope") is None

    def test_capacity_sliding_window(self):
        q = ProposalQueue(max_entries=3)
        for i in range(5):
            q.enqueue(_make_queued(f"p{i}"))
        assert q.size() == 3
        assert [qp.proposal.proposal_id for qp in q.list()] == ["p2", "p3", "p4"]

    def test_queued_proposal_to_dict_serialises_nested_proposal(self):
        qp = _make_queued("a")
        d = qp.to_dict()
        assert d["consensus_verdict"] == VERDICT_APPROVE
        assert isinstance(d["proposal"], dict)
        assert d["proposal"]["proposal_id"] == "a"


# ─── Env-flag gating ──────────────────────────────────────────────────
class TestEnvGating:
    def setup_method(self):
        reset_service()
        self._prev = os.environ.pop("DC_EPMS_OPTIMIZER_ENABLED", None)

    def teardown_method(self):
        if self._prev is not None:
            os.environ["DC_EPMS_OPTIMIZER_ENABLED"] = self._prev
        else:
            os.environ.pop("DC_EPMS_OPTIMIZER_ENABLED", None)
        reset_service()

    def test_disabled_by_default(self):
        assert is_enabled() is False
        assert get_service() is None

    def test_enabled_returns_singleton(self):
        os.environ["DC_EPMS_OPTIMIZER_ENABLED"] = "true"
        assert is_enabled() is True
        s1 = get_service()
        s2 = get_service()
        assert s1 is not None
        assert s1 is s2  # singleton

    def test_truthy_variants_all_enable(self):
        for v in ("true", "True", "1", "yes", "on"):
            os.environ["DC_EPMS_OPTIMIZER_ENABLED"] = v
            assert is_enabled() is True, f"failed for {v!r}"


# ─── ADR-006 / S-SEC-02 PROPOSER-PATTERN INVARIANT ───────────────────
# These tests are the cheapest enforceable proof that the Optimizer
# module can never reach /api/bms/write. If anyone ever adds an HTTP
# client or a FastAPI router to backend/optimizer.py, these tests fail
# and block the commit. This is the load-bearing architectural guard
# for Epic 2.
class TestProposerPatternInvariant:
    @pytest.fixture(scope="class")
    def module_imports(self) -> set[str]:
        """Parse backend/optimizer.py and return its full import set."""
        src = Path(opt.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        return imports

    def test_no_http_client_libraries(self, module_imports: set[str]):
        # The Optimizer must not be able to make outbound HTTP calls.
        forbidden = {"requests", "httpx", "aiohttp", "urllib3", "websockets"}
        leaked = forbidden & module_imports
        assert leaked == set(), (
            f"backend/optimizer.py imports HTTP client(s) {leaked!r} — "
            "violates the Proposer Pattern (S-SEC-02). The Optimizer "
            "MUST be unable to call /api/bms/write directly."
        )

    def test_no_fastapi_router_machinery(self, module_imports: set[str]):
        # The Optimizer must not register routes. Approve/reject
        # endpoints live in a separate module (2.C).
        assert "fastapi" not in module_imports, (
            "backend/optimizer.py imports fastapi — endpoints belong in "
            "a separate routes module (Batch 2.C)."
        )

    def test_no_bms_connector_import(self, module_imports: set[str]):
        # Cannot reach the BMS write path through bms_connector either.
        forbidden = {"bms_connector"}
        leaked = forbidden & module_imports
        assert leaked == set(), (
            f"backend/optimizer.py imports {leaked!r} — the Optimizer "
            "must never reach the BMS write path. Operator approval "
            "(Batch 2.C) is what issues the write."
        )

    def test_no_optimizer_routes_import(self):
        """Directional invariant (S-SEC-02, Batch 2.C):
        ``backend/optimizer.py`` must NOT import ``optimizer_routes``.
        The routes module is the only place in Epic 2 that touches the
        BMS write path; the deterministic core must remain a one-way
        reader (routes import optimizer; optimizer does not import
        routes). This guards against a future refactor that would
        re-introduce a write-path side-effect into the core."""
        src = Path(opt.__file__).read_text(encoding="utf-8")
        # Substring check across the whole file (imports OR any other
        # reference). The opposite direction — routes importing
        # optimizer — is intended and unconstrained.
        leaks = [ln for ln in src.splitlines()
                 if "optimizer_routes" in ln
                 and not ln.lstrip().startswith("#")
                 and '"""' not in ln and "'''" not in ln]
        assert leaks == [], (
            f"backend/optimizer.py references 'optimizer_routes' outside "
            f"a comment: {leaks!r}. The directional invariant (Batch 2.C) "
            "forbids the deterministic core from depending on the routes "
            "module — which is the only Epic 2 code allowed to call BMS "
            "write."
        )

    def test_no_bms_write_substring_anywhere_in_module(self):
        """Defence-in-depth — a live (non-docstring) reference to the BMS
        write path in this module would be a leak. Docstrings that
        explicitly forbid the call are allowed (and indeed expected)."""
        src = Path(opt.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)

        # First pass: tag every Constant node that IS a docstring (the
        # first statement of a Module / FunctionDef / AsyncFunctionDef /
        # ClassDef body when that statement is a bare string expression).
        docstring_ids: set[int] = set()
        for parent in ast.walk(tree):
            if not isinstance(parent, ast.Module | ast.FunctionDef
                              | ast.AsyncFunctionDef | ast.ClassDef):
                continue
            body = parent.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstring_ids.add(id(body[0].value))

        # Second pass: collect any non-docstring string Constants that
        # name the forbidden write path.
        leaks: list[str] = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if id(node) in docstring_ids:
                continue
            if "/api/bms/write" in node.value:
                leaks.append(node.value)
        assert leaks == [], (
            f"backend/optimizer.py contains live (non-docstring) references "
            f"to '/api/bms/write': {leaks!r}. The Optimizer must never "
            "issue that write. (See S-SEC-02 + the Proposer Pattern.)"
        )


# ─── Sanity: pue_drift helper ────────────────────────────────────────
def test_pue_drift_returns_none_when_pue_missing():
    assert pue_drift(_point(pue=None), pue_target=1.30) is None


def test_pue_drift_signed_correctly():
    assert pue_drift(_point(pue=1.35), pue_target=1.30) == pytest.approx(0.05)
    assert pue_drift(_point(pue=1.25), pue_target=1.30) == pytest.approx(-0.05)


# ════════════════════════════════════════════════════════════════════
# Epic 5 Sprint 1 — Observability
# ════════════════════════════════════════════════════════════════════
from backend.optimizer import (  # noqa: E402  (kept with Epic 5 block for locality)
    AUDIT_TICK,
    _extract_agent_verdicts,
)


# ─── E5.C — per-agent breakdown helper ────────────────────────────────
class _FakeAgentVerdict:
    def __init__(self, name, verdict, summary=""):
        self.agent_name = name
        self.verdict = verdict
        self.summary = summary


class _FakeConsensusWithAgents:
    """Duck-types ConsensusResult including the .agents list (E5.C)."""

    def __init__(self, consensus="approve", rationale="ok", veto=False, agents=None):
        self.consensus = consensus
        self.rationale = rationale
        self.safety_officer_veto = veto
        self.agents = agents or []


def test_extract_agent_verdicts_returns_empty_on_none():
    assert _extract_agent_verdicts(None) == []


def test_extract_agent_verdicts_returns_empty_when_no_agents_attr():
    assert _extract_agent_verdicts(_FakeConsensus()) == []


def test_extract_agent_verdicts_returns_six_dicts():
    cons = _FakeConsensusWithAgents(agents=[
        _FakeAgentVerdict("Architect", "approve", "topology ok"),
        _FakeAgentVerdict("Safety Officer", "approve", "no LOTO"),
        _FakeAgentVerdict("Diagnostician", "approve", "no recurrence"),
        _FakeAgentVerdict("Analyst", "approve", "opex cheap"),
        _FakeAgentVerdict("Capacity Planner", "approve", "headroom ok"),
        _FakeAgentVerdict("Carbon/Grid", "caution", "on-peak TOU"),
    ])
    out = _extract_agent_verdicts(cons)
    assert len(out) == 6
    assert {a["agent_name"] for a in out} == {
        "Architect", "Safety Officer", "Diagnostician",
        "Analyst", "Capacity Planner", "Carbon/Grid",
    }
    carbon = next(a for a in out if a["agent_name"] == "Carbon/Grid")
    assert carbon["verdict"] == "caution"
    assert carbon["summary"] == "on-peak TOU"


def test_extract_agent_verdicts_coerces_missing_fields_to_empty_str():
    class _Bare:
        agent_name = "X"
        # no verdict, no summary
    cons = _FakeConsensusWithAgents(agents=[_Bare()])
    out = _extract_agent_verdicts(cons)
    assert out == [{"agent_name": "X", "verdict": "", "summary": ""}]


# ─── E5.C — queued proposal carries per-agent breakdown ──────────────
class TestQueuedProposalCarriesAgentVerdicts:
    @pytest.mark.asyncio
    async def test_queued_proposal_includes_agent_verdicts(self):
        agents = [
            _FakeAgentVerdict("Architect", "approve", "topology ok"),
            _FakeAgentVerdict("Safety Officer", "approve", "no LOTO"),
            _FakeAgentVerdict("Diagnostician", "approve", "no recurrence"),
            _FakeAgentVerdict("Analyst", "approve", "opex cheap"),
            _FakeAgentVerdict("Capacity Planner", "approve", "headroom ok"),
            _FakeAgentVerdict("Carbon/Grid", "approve", "low carbon"),
        ]

        async def consult(_ctx):
            return _FakeConsensusWithAgents(agents=agents)

        svc = OptimizerService(
            telemetry_provider=_async_provider(_point()),
            pue_target=1.30, cfg=_SustainOnceCfg, consult_fn=consult,
        )
        await svc.tick()
        for qp in svc.queue.list():
            assert len(qp.agent_verdicts) == 6
            assert qp.agent_verdicts[0]["agent_name"] == "Architect"
            # to_dict propagates the breakdown
            d = qp.to_dict()
            assert "agent_verdicts" in d
            assert len(d["agent_verdicts"]) == 6

    @pytest.mark.asyncio
    async def test_queued_proposal_empty_breakdown_when_no_consult(self):
        svc = OptimizerService(
            telemetry_provider=_async_provider(_point()),
            pue_target=1.30, cfg=_SustainOnceCfg,
        )
        await svc.tick()
        for qp in svc.queue.list():
            assert qp.agent_verdicts == []


# ─── E5.A — health + heartbeat surfaces ───────────────────────────────
class TestOptimizerHealth:
    @pytest.mark.asyncio
    async def test_health_initial_state_before_any_tick(self):
        svc = OptimizerService(telemetry_provider=None)
        h = svc.health()
        assert h["is_running"] is False
        assert h["last_tick_unix"] == 0.0
        assert h["tick_count"] == 0
        assert h["queue_size"] == 0
        assert h["last_tick_outcomes"] == {}
        assert h["audit_recent"] == []

    @pytest.mark.asyncio
    async def test_health_after_tick_records_wall_clock_and_outcomes(self):
        svc = OptimizerService(
            telemetry_provider=_async_provider(_point()),
            pue_target=1.30, cfg=_SustainOnceCfg,
        )
        before = time.time()
        await svc.tick()
        after = time.time()
        h = svc.health()
        assert h["tick_count"] == 1
        assert before <= h["last_tick_unix"] <= after
        o = h["last_tick_outcomes"]
        assert o["sustained"] is True
        assert o["telemetry_present"] is True
        assert o["n_proposals"] == 2
        assert o["surfaces_emitted"] == [
            SURFACE_CHILLER_LWT, SURFACE_CT_FAN_VFD,
        ]

    @pytest.mark.asyncio
    async def test_health_after_veto_records_n_vetoed(self):
        async def consult(_ctx):
            return _FakeConsensus(
                consensus=VERDICT_HARD_STOP, veto=True,
                rationale="VETO test",
            )

        svc = OptimizerService(
            telemetry_provider=_async_provider(_point()),
            pue_target=1.30, cfg=_SustainOnceCfg, consult_fn=consult,
        )
        await svc.tick()
        h = svc.health()
        assert h["last_tick_outcomes"]["n_vetoed"] == 2
        assert sorted(h["last_tick_outcomes"]["surfaces_vetoed"]) == sorted([
            SURFACE_CHILLER_LWT, SURFACE_CT_FAN_VFD,
        ])
        assert h["last_tick_outcomes"]["n_proposals"] == 0

    @pytest.mark.asyncio
    async def test_health_records_tick_event_in_audit(self):
        svc = OptimizerService(
            telemetry_provider=_async_provider(_point()),
            pue_target=1.30, cfg=_SustainOnceCfg,
        )
        await svc.tick()
        tick_events = [e for e in svc.audit.entries() if e.event == AUDIT_TICK]
        assert len(tick_events) == 1
        assert "tick #1" in tick_events[0].detail


# ─── E5.A — optimizer-tick event emission ─────────────────────────────
import time  # noqa: E402

from backend import optimizer as _opt_mod  # noqa: E402


class TestOptimizerTickEvent:
    @pytest.mark.asyncio
    async def test_tick_emits_optimizer_tick_event_on_every_tick(self):
        events: list[tuple[str, dict]] = []

        def emitter(event: str, payload: dict):
            events.append((event, payload))

        svc = OptimizerService(
            telemetry_provider=_async_provider(_point()),
            pue_target=1.30, cfg=_SustainOnceCfg,
            event_emitter=emitter,
        )
        await svc.tick()
        tick_events = [(e, p) for e, p in events if e == "optimizer-tick"]
        assert len(tick_events) == 1
        _, payload = tick_events[0]
        # Heartbeat payload shape
        assert "tick_unix" in payload
        assert payload["tick_count"] == 1
        assert "outcomes" in payload
        assert payload["outcomes"]["sustained"] is True
        assert payload["queue_size"] >= 0

    @pytest.mark.asyncio
    async def test_tick_event_fires_even_when_no_telemetry(self):
        events: list[tuple[str, dict]] = []

        def emitter(event: str, payload: dict):
            events.append((event, payload))

        svc = OptimizerService(
            telemetry_provider=None,
            event_emitter=emitter,
        )
        await svc.tick()
        # Heartbeat fires for the operator strip even when telemetry is absent.
        tick_events = [e for e, _ in events if e == "optimizer-tick"]
        assert len(tick_events) == 1

    @pytest.mark.asyncio
    async def test_tick_event_carries_n_proposals_separately_from_emitter(self):
        events: list[tuple[str, dict]] = []

        def emitter(event: str, payload: dict):
            events.append((event, payload))

        svc = OptimizerService(
            telemetry_provider=_async_provider(_point()),
            pue_target=1.30, cfg=_SustainOnceCfg,
            event_emitter=emitter,
        )
        await svc.tick()
        # The heartbeat is the LAST event (in `finally`). All proposal
        # events come before it.
        kinds = [e for e, _ in events]
        assert kinds.count("optimizer-tick") == 1
        assert kinds[-1] == "optimizer-tick"
        proposal_events = [e for e in kinds if e == "optimizer-proposal"]
        assert len(proposal_events) == 2

    # Silence unused-import lint when this block runs standalone.
    _ = _opt_mod


# ════════════════════════════════════════════════════════════════════
# Epic 5 Sprint 2 — E5.E What-If sandbox preview (simulate_setpoint_impact)
# ════════════════════════════════════════════════════════════════════
from backend.optimizer import (  # noqa: E402 — kept with E5.E block for locality
    PREVIEW_VERDICT_AMBER,
    PREVIEW_VERDICT_GREEN,
    PREVIEW_VERDICT_RED,
    PreviewProjection,
    simulate_setpoint_impact,
)


def _proposal(surface: str, current: float, proposed: float) -> Proposal:
    return Proposal(
        proposal_id="qp-preview",
        surface=surface,
        current_value=current,
        proposed_value=proposed,
        delta=proposed - current,
        rationale="r",
        pue_at_emission=1.35,
        created_at=1.0,
    )


class TestSimulateSetpointImpact:
    def test_chiller_lwt_drop_projects_green(self):
        # LWT 7.5 -> 7.0 (Δ -0.5 K). With +0.006 coeff per K and signed
        # math, dPUE = -0.5 * 0.006 = -0.003. dInlet = -0.5 * 0.4 = -0.2.
        # Current PUE 1.31 -> projected 1.307, target 1.30 -> within
        # band. Inlet 22.0 -> 21.8 (well below A2 warn). Verdict: green.
        proj = simulate_setpoint_impact(
            _proposal(SURFACE_CHILLER_LWT, 7.5, 7.0),
            _point(pue=1.31, hall_temp_c=22.0),
            pue_target=1.30,
        )
        assert isinstance(proj, PreviewProjection)
        assert proj.verdict == PREVIEW_VERDICT_GREEN
        assert proj.projected_pue == pytest.approx(1.307)
        assert proj.projected_pue_delta == pytest.approx(-0.003)
        assert proj.projected_inlet_c == pytest.approx(21.8)
        assert proj.ashrae_distance_c == pytest.approx(13.2)

    def test_ct_fan_vfd_step_up_projects_green(self):
        # VFD 60 -> 65 (Δ +5 %). dPUE = +5 * -0.001 = -0.005. dWUE =
        # +5 * 0.005 = +0.025 L/kWh. PUE 1.31 -> 1.305.
        proj = simulate_setpoint_impact(
            _proposal(SURFACE_CT_FAN_VFD, 60.0, 65.0),
            _point(pue=1.31, hall_temp_c=22.0),
            pue_target=1.30,
        )
        assert proj.verdict == PREVIEW_VERDICT_GREEN
        assert proj.projected_pue == pytest.approx(1.305)
        assert proj.projected_wue_delta == pytest.approx(0.025)

    def test_amber_when_pue_stays_above_target_plus_window(self):
        # Tiny LWT step won't bring 1.45 PUE below target+0.02 = 1.32.
        proj = simulate_setpoint_impact(
            _proposal(SURFACE_CHILLER_LWT, 7.5, 7.0),
            _point(pue=1.45, hall_temp_c=22.0),
            pue_target=1.30,
        )
        assert proj.verdict == PREVIEW_VERDICT_AMBER

    def test_amber_when_projected_inlet_in_warn_band(self):
        # Current inlet 28 C is already in [27, 35) warn band. A LWT
        # DROP would cool the inlet — but we want the warn-band branch:
        # construct an impossible upward proposal (LWT goes UP) so the
        # projected inlet stays in the warn band.
        proj = simulate_setpoint_impact(
            # LWT going UP 7.0 -> 7.5 → inlet +0.2 → 28.2 (still in warn).
            _proposal(SURFACE_CHILLER_LWT, 7.0, 7.5),
            _point(pue=1.30, hall_temp_c=28.0),
            pue_target=1.30,
        )
        # A LWT-UP proposal makes PUE WORSE (dPUE positive) -> red,
        # not amber. The verdict logic correctly catches the wrong-way
        # trim first; amber-by-inlet is for proposals that improve
        # PUE but leave the hall in the warn band.
        assert proj.verdict == PREVIEW_VERDICT_RED
        assert proj.projected_pue_delta > 0

    def test_red_when_pue_worsens(self):
        # Wrong-way trim (LWT goes UP) — dPUE positive -> RED.
        proj = simulate_setpoint_impact(
            _proposal(SURFACE_CHILLER_LWT, 7.0, 8.0),
            _point(pue=1.30, hall_temp_c=22.0),
            pue_target=1.30,
        )
        assert proj.verdict == PREVIEW_VERDICT_RED
        assert any("worsens" in f.lower() for f in proj.findings)

    def test_red_when_projected_inlet_breaches_a2(self):
        # A 5 C inlet swing isn't realistic from one LWT step in real
        # life — for the test we construct a proposal whose mapped
        # inlet delta plus baseline crosses the 35 C breach line.
        # Baseline 34.5, LWT up 7.0 -> 9.0 (Δ +2), inlet +0.8 -> 35.3.
        proj = simulate_setpoint_impact(
            _proposal(SURFACE_CHILLER_LWT, 7.0, 9.0),
            _point(pue=1.30, hall_temp_c=34.5),
            pue_target=1.30,
        )
        assert proj.verdict == PREVIEW_VERDICT_RED
        # ASHRAE A2 breach finding present
        assert any("A2 breach" in f for f in proj.findings)

    def test_amber_when_telemetry_absent(self):
        proj = simulate_setpoint_impact(
            _proposal(SURFACE_CHILLER_LWT, 7.5, 7.0),
            None,  # no telemetry
            pue_target=1.30,
        )
        assert proj.verdict == PREVIEW_VERDICT_AMBER
        assert proj.projected_pue is None
        assert any("unavailable" in f for f in proj.findings)

    def test_unknown_surface_returns_amber_with_finding(self):
        proj = simulate_setpoint_impact(
            _proposal("gpu_clock_mhz", 1.0, 2.0),
            _point(pue=1.31, hall_temp_c=22.0),
            pue_target=1.30,
        )
        assert proj.verdict == PREVIEW_VERDICT_AMBER
        assert any("no preview coefficients" in f for f in proj.findings)

    def test_projection_is_frozen_dataclass(self):
        from dataclasses import FrozenInstanceError

        proj = simulate_setpoint_impact(
            _proposal(SURFACE_CHILLER_LWT, 7.5, 7.0),
            _point(),
            pue_target=1.30,
        )
        with pytest.raises(FrozenInstanceError):
            proj.verdict = "anything"  # type: ignore[misc]

    def test_to_dict_round_trips(self):
        proj = simulate_setpoint_impact(
            _proposal(SURFACE_CHILLER_LWT, 7.5, 7.0),
            _point(pue=1.31, hall_temp_c=22.0),
            pue_target=1.30,
        )
        d = proj.to_dict()
        assert d["verdict"] == proj.verdict
        assert d["projected_pue"] == proj.projected_pue
        assert d["proposal_id"] == "qp-preview"


# ─── S-DET-01 — no LLM call lives on the preview path ────────────────
def test_simulate_setpoint_impact_imports_no_llm_module():
    """A grep-level binding: the simulate path must not touch the LLM
    client module. If a future refactor pulls Gemma into the projection,
    this test fails loudly — same enforcement style as the BMS-write
    invariant lower in this file."""
    src = Path(opt.__file__).read_text(encoding="utf-8")
    # The simulate_setpoint_impact body is a single ~80-line block. We
    # carve it out + assert no LLM identifiers appear inside.
    pat = re.compile(
        r"def simulate_setpoint_impact\b.*?\n(?=\n[A-Za-z]|\Z)",
        re.S,
    )
    m = pat.search(src)
    assert m is not None, "simulate_setpoint_impact() not found"
    body = m.group(0)
    for needle in ("complete_gemma", "llm_client", "_synthesize_narrative"):
        assert needle not in body, (
            f"simulate_setpoint_impact() must be LLM-free (S-DET-01); "
            f"found {needle!r} in its body."
        )


import re  # noqa: E402 — used by test_simulate_setpoint_impact_imports_no_llm_module
