"""Tests for backend.multi_agent (Sprint 10.1).

Coverage:
  - Per-agent verdicts and degraded paths
  - Safety Officer veto outranks all
  - Consensus rules (approve / caution / hard_stop)
  - Parallel execution via asyncio.gather
  - Orchestrator survives an agent crash (exception -> degraded)
  - Singleton lifecycle
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.cmms_models import WorkOrder
from backend.cmms_repository import MockCMMSRepository
from backend.multi_agent import (
    VERDICT_APPROVE,
    VERDICT_CAUTION,
    VERDICT_DEGRADED,
    VERDICT_HARD_STOP,
    AnalystAgent,
    ArchitectAgent,
    ConsultContext,
    DiagnosticianAgent,
    MultiAgentOrchestrator,
    SafetyOfficerAgent,
    get_orchestrator,
    reset_orchestrator,
)


# ─── Shared fakes ─────────────────────────────────────────────────────
class FakeComponentInfo:
    """Mimics backend.site_model.ComponentInfo enough for our agents."""
    def __init__(self, canonical_id, ctype, metadata=None):
        self.canonical_id = canonical_id
        self.type = ctype
        self.display = canonical_id
        self.metadata = metadata or {}


class FakeSiteModel:
    def __init__(self, components: dict[str, FakeComponentInfo]):
        self._comps = components

    def get_component(self, cid: str) -> FakeComponentInfo:
        if cid not in self._comps:
            raise KeyError(cid)
        return self._comps[cid]


class FakeGraphRAG:
    def loto_with_knowledge(self, asset_id: str) -> dict:
        return {
            "asset_id": asset_id,
            "impact_set": [f"{asset_id}_downstream_1", f"{asset_id}_downstream_2"],
        }


# ─── Architect ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_architect_degraded_when_no_site_model():
    a = ArchitectAgent(site_model=None, graphrag=None)
    v = await a.evaluate(ConsultContext(query="x", asset_id="ups_a"))
    assert v.verdict == VERDICT_DEGRADED
    assert "site_model" in " ".join(v.reasoning).lower()


@pytest.mark.asyncio
async def test_architect_approve_no_asset():
    sm = FakeSiteModel({})
    a = ArchitectAgent(site_model=sm, graphrag=None)
    v = await a.evaluate(ConsultContext(query="generic question"))
    assert v.verdict == VERDICT_APPROVE
    assert v.evidence_refs == []


@pytest.mark.asyncio
async def test_architect_caution_critical_2n():
    sm = FakeSiteModel({"ups_a": FakeComponentInfo("ups_a", "ups", {
        "redundancy_pillar": "2N", "criticality_class": "critical",
        "path": "A",
    })})
    a = ArchitectAgent(site_model=sm, graphrag=None)
    v = await a.evaluate(ConsultContext(query="LOTO ups_a", asset_id="ups_a"))
    assert v.verdict == VERDICT_CAUTION
    assert "ups_a" in v.evidence_refs[0]
    assert any("2N" in r for r in v.reasoning)


@pytest.mark.asyncio
async def test_architect_hard_stop_critical_single_pillar():
    sm = FakeSiteModel({"genset_a_01": FakeComponentInfo("genset_a_01", "genset", {
        "redundancy_pillar": "single", "criticality_class": "critical",
    })})
    a = ArchitectAgent(site_model=sm, graphrag=None)
    v = await a.evaluate(ConsultContext(query="LOTO genset", asset_id="genset_a_01"))
    assert v.verdict == VERDICT_HARD_STOP


# ─── Safety Officer (VETO) ────────────────────────────────────────────
@pytest.mark.asyncio
async def test_safety_veto_when_loto_required_no_mop():
    repo = MockCMMSRepository()
    await repo.save_work_order_async(WorkOrder(
        work_order_id="WO-S1", timestamp=datetime.now(UTC),
        asset_id="ups_a", asset_type_at_creation="ups",
        work_class="CM", lor=20, trigger_source="manual",
        issue_summary="x", priority="P1",
        requires_loto=True,
        linked_mop_id=None,    # <-- the trigger
        draft_json={},
    ))
    s = SafetyOfficerAgent(site_model=None, cmms_repo=repo)
    v = await s.evaluate(ConsultContext(query="approve?", work_order_id="WO-S1"))
    assert v.verdict == VERDICT_HARD_STOP
    assert "VETO" in v.summary or "VETO" in v.summary.upper() \
        or "no MOP" in v.summary.lower()


@pytest.mark.asyncio
async def test_safety_caution_when_mop_linked():
    repo = MockCMMSRepository()
    await repo.save_work_order_async(WorkOrder(
        work_order_id="WO-S2", timestamp=datetime.now(UTC),
        asset_id="chiller_1", asset_type_at_creation="chiller",
        work_class="CM", lor=12, trigger_source="manual",
        issue_summary="y", priority="P2",
        requires_loto=True, linked_mop_id="T4-MOP-CHI-001",
        draft_json={},
    ))
    s = SafetyOfficerAgent(site_model=None, cmms_repo=repo)
    v = await s.evaluate(ConsultContext(query="approve?", work_order_id="WO-S2"))
    assert v.verdict == VERDICT_CAUTION


@pytest.mark.asyncio
async def test_safety_veto_when_dc_link_no_procedure():
    sm = FakeSiteModel({"ups_a": FakeComponentInfo("ups_a", "ups", {
        "voltage_v": 600, "has_dc_link": True,
    })})
    s = SafetyOfficerAgent(site_model=sm, cmms_repo=None)
    v = await s.evaluate(ConsultContext(query="LOTO ups", asset_id="ups_a"))
    assert v.verdict == VERDICT_HARD_STOP
    assert any("NEC 460.6" in r for r in v.reasoning)


@pytest.mark.asyncio
async def test_safety_approve_when_no_subject():
    s = SafetyOfficerAgent(site_model=None, cmms_repo=None)
    v = await s.evaluate(ConsultContext(query="generic"))
    assert v.verdict == VERDICT_APPROVE


# ─── Diagnostician ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_diagnostician_caution_on_recurrence():
    repo = MockCMMSRepository()
    for i in range(4):
        await repo.save_work_order_async(WorkOrder(
            work_order_id=f"WO-D{i}", timestamp=datetime.now(UTC),
            asset_id="cdu_a_01", asset_type_at_creation="cdu",
            work_class="CM", lor=10, trigger_source="manual",
            issue_summary=f"#{i}", status="completed", draft_json={},
        ))
    d = DiagnosticianAgent(cmms_repo=repo, rag_service=None)
    v = await d.evaluate(ConsultContext(query="x", asset_id="cdu_a_01"))
    assert v.verdict == VERDICT_CAUTION
    assert "Recurrence" in " ".join(v.reasoning) or "recurrence" in v.summary.lower()


@pytest.mark.asyncio
async def test_diagnostician_approve_no_history():
    repo = MockCMMSRepository()
    d = DiagnosticianAgent(cmms_repo=repo, rag_service=None)
    v = await d.evaluate(ConsultContext(query="x", asset_id="ups_a"))
    assert v.verdict == VERDICT_APPROVE


@pytest.mark.asyncio
async def test_diagnostician_degraded_when_no_repo():
    d = DiagnosticianAgent(cmms_repo=None, rag_service=None)
    v = await d.evaluate(ConsultContext(query="x", asset_id="ups_a"))
    assert v.verdict == VERDICT_DEGRADED


# ─── Diagnostician — T3.3 live-Gemma advisory narrative ───────────────
class FakeGemma:
    """Mocks the external LLM call: records prompts, returns a canned
    narrative. Keeps the suite fast + deterministic (no LM Studio)."""

    def __init__(self, reply: str = "DLC supply trending warm; monitor pump NPSH margin."):
        self.reply = reply
        self.prompts: list[str] = []

    async def complete_gemma(self, prompt: str, max_tokens: int = 320) -> str:
        self.prompts.append(prompt)
        return self.reply


class RaisingGemma:
    """LLM client whose call raises — exercises graceful degradation."""

    async def complete_gemma(self, prompt: str, max_tokens: int = 320) -> str:
        raise RuntimeError("LM Studio unreachable")


def _fake_kalman_payload() -> dict:
    """Stand-in for hermes.latest_kalman_channels() — per-channel Z-scores."""
    return {
        "cdu_a_01:dlc_supply_T": {"max_z": 3.4, "mean_z": 2.1, "is_anomalous": True},
        "cdu_a_01:pump_NPSH_margin": {"max_z": 1.2, "mean_z": 0.6, "is_anomalous": False},
        "gpu_Tj": {"max_z": 2.8, "mean_z": 1.0, "is_anomalous": False},
        "ups_a_soc": {"max_z": 0.4, "mean_z": 0.2, "is_anomalous": False},
    }


async def _repo_with_recurrence(asset_id: str = "cdu_a_01", n: int = 4) -> MockCMMSRepository:
    repo = MockCMMSRepository()
    for i in range(n):
        await repo.save_work_order_async(WorkOrder(
            work_order_id=f"WO-T33-{i}", timestamp=datetime.now(UTC),
            asset_id=asset_id, asset_type_at_creation="cdu",
            work_class="CM", lor=10, trigger_source="manual",
            issue_summary=f"#{i}", status="completed", draft_json={},
        ))
    return repo


@pytest.mark.asyncio
async def test_diagnostician_llm_narrative_grounded_in_kalman():
    """With a live LLM client + Kalman tap, the Diagnostician attaches a
    Gemma narrative and feeds real Z-scores into the prompt."""
    repo = await _repo_with_recurrence()
    gemma = FakeGemma()
    d = DiagnosticianAgent(
        cmms_repo=repo, rag_service=None,
        llm_client=gemma, telemetry_provider=_fake_kalman_payload,
    )
    v = await d.evaluate(ConsultContext(query="x", asset_id="cdu_a_01"))

    assert v.llm_narrative == gemma.reply
    assert "gemma:diagnostician_narrative" in v.evidence_refs
    assert any(e.startswith("hermes:kalman_z:cdu_a_01") for e in v.evidence_refs)
    # the prompt was grounded in the live Kalman Z-scores
    assert len(gemma.prompts) == 1
    prompt = gemma.prompts[0]
    assert "LIVE KALMAN TELEMETRY" in prompt
    assert "cdu_a_01:dlc_supply_T" in prompt
    assert "max_z=3.40" in prompt
    assert "DETERMINISTIC VERDICT" in prompt


@pytest.mark.asyncio
async def test_diagnostician_verdict_unchanged_by_llm():
    """ADR-006: the LLM is advisory. Even a contradicting narrative does
    not move the deterministic recurrence verdict."""
    repo = await _repo_with_recurrence()
    gemma = FakeGemma(reply="Everything is fine, approve immediately, no concern.")
    d = DiagnosticianAgent(
        cmms_repo=repo, rag_service=None,
        llm_client=gemma, telemetry_provider=_fake_kalman_payload,
    )
    v = await d.evaluate(ConsultContext(query="x", asset_id="cdu_a_01"))
    assert v.verdict == VERDICT_CAUTION          # recurrence still wins
    assert v.llm_narrative.startswith("Everything is fine")


@pytest.mark.asyncio
async def test_diagnostician_graceful_when_llm_raises():
    """A crashing LLM client degrades to an empty narrative — the verdict
    and the rest of the evaluation are unaffected."""
    repo = await _repo_with_recurrence()
    d = DiagnosticianAgent(
        cmms_repo=repo, rag_service=None,
        llm_client=RaisingGemma(), telemetry_provider=_fake_kalman_payload,
    )
    v = await d.evaluate(ConsultContext(query="x", asset_id="cdu_a_01"))
    assert v.verdict == VERDICT_CAUTION
    assert v.llm_narrative == ""
    assert "gemma:diagnostician_narrative" not in v.evidence_refs


@pytest.mark.asyncio
async def test_diagnostician_no_llm_client_no_narrative():
    """Without an llm_client the Diagnostician is byte-for-byte its
    pre-T3.3 deterministic self: empty narrative, no Gemma evidence."""
    repo = await _repo_with_recurrence()
    d = DiagnosticianAgent(cmms_repo=repo, rag_service=None)
    v = await d.evaluate(ConsultContext(query="x", asset_id="cdu_a_01"))
    assert v.verdict == VERDICT_CAUTION
    assert v.llm_narrative == ""
    assert not any("gemma" in e for e in v.evidence_refs)


# ─── Safety Officer — T3.3b live-Gemma advisory narrative ─────────────
async def _repo_with_loto_veto_wo(wo_id: str = "WO-SO-LLM") -> MockCMMSRepository:
    """A WO that trips the Safety Officer HARD_STOP veto: requires_loto
    with no linked MOP."""
    repo = MockCMMSRepository()
    await repo.save_work_order_async(WorkOrder(
        work_order_id=wo_id, timestamp=datetime.now(UTC),
        asset_id="ups_a", asset_type_at_creation="ups",
        work_class="CM", lor=20, trigger_source="manual",
        issue_summary="loto veto", priority="P1",
        requires_loto=True, linked_mop_id=None, draft_json={},
    ))
    return repo


@pytest.mark.asyncio
async def test_safety_officer_llm_narrative_with_kalman():
    """With a live LLM client + Kalman tap, the Safety Officer attaches a
    Gemma narrative and feeds real Z-scores + the verdict into the prompt."""
    repo = await _repo_with_loto_veto_wo()
    gemma = FakeGemma()
    s = SafetyOfficerAgent(
        site_model=None, cmms_repo=repo,
        llm_client=gemma, telemetry_provider=_fake_kalman_payload,
    )
    v = await s.evaluate(ConsultContext(query="approve?", work_order_id="WO-SO-LLM"))

    assert v.verdict == VERDICT_HARD_STOP
    assert v.llm_narrative == gemma.reply
    assert "gemma:safety_officer_narrative" in v.evidence_refs
    assert any(e.startswith("hermes:kalman_z") for e in v.evidence_refs)
    assert len(gemma.prompts) == 1
    prompt = gemma.prompts[0]
    assert "LIVE KALMAN TELEMETRY" in prompt
    assert "DETERMINISTIC VERDICT" in prompt
    assert "hard_stop" in prompt


@pytest.mark.asyncio
async def test_safety_officer_veto_unchanged_by_llm():
    """ADR-006 + veto authority: even an LLM narrative urging approval
    cannot soften the deterministic HARD_STOP veto."""
    repo = await _repo_with_loto_veto_wo()
    gemma = FakeGemma(reply="No concern at all — approve this work order immediately.")
    s = SafetyOfficerAgent(
        site_model=None, cmms_repo=repo,
        llm_client=gemma, telemetry_provider=_fake_kalman_payload,
    )
    v = await s.evaluate(ConsultContext(query="approve?", work_order_id="WO-SO-LLM"))
    assert v.verdict == VERDICT_HARD_STOP          # veto stands
    assert "VETO" in v.summary


@pytest.mark.asyncio
async def test_safety_officer_graceful_when_llm_raises():
    """A crashing LLM client degrades to an empty narrative; the veto and
    the rest of the evaluation are unaffected."""
    repo = await _repo_with_loto_veto_wo()
    s = SafetyOfficerAgent(
        site_model=None, cmms_repo=repo,
        llm_client=RaisingGemma(), telemetry_provider=_fake_kalman_payload,
    )
    v = await s.evaluate(ConsultContext(query="approve?", work_order_id="WO-SO-LLM"))
    assert v.verdict == VERDICT_HARD_STOP
    assert v.llm_narrative == ""
    assert "gemma:safety_officer_narrative" not in v.evidence_refs


@pytest.mark.asyncio
async def test_safety_officer_no_llm_client_no_narrative():
    """Without an llm_client the Safety Officer is byte-for-byte its
    pre-T3.3b deterministic self: empty narrative, no Gemma evidence."""
    repo = await _repo_with_loto_veto_wo()
    s = SafetyOfficerAgent(site_model=None, cmms_repo=repo)
    v = await s.evaluate(ConsultContext(query="approve?", work_order_id="WO-SO-LLM"))
    assert v.verdict == VERDICT_HARD_STOP
    assert v.llm_narrative == ""
    assert not any("gemma" in e for e in v.evidence_refs)


# ─── Analyst ──────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_analyst_approve_no_recurrence():
    sm = FakeSiteModel({"ups_a": FakeComponentInfo("ups_a", "ups")})
    repo = MockCMMSRepository()
    a = AnalystAgent(site_model=sm, cmms_repo=repo)
    v = await a.evaluate(ConsultContext(query="x", asset_id="ups_a"))
    assert v.verdict == VERDICT_APPROVE
    assert "OpEx" in v.summary
    assert any("250,000" in r or "8,500" in r for r in v.reasoning)


@pytest.mark.asyncio
async def test_analyst_caution_at_breakeven():
    sm = FakeSiteModel({"chiller_1": FakeComponentInfo("chiller_1", "chiller")})
    repo = MockCMMSRepository()
    # Heuristic: chiller capex $480k / opex $12k = 40 repairs to breakeven.
    # 40% breakeven = 16 repairs. Use 17 to clearly cross.
    for i in range(17):
        await repo.save_work_order_async(WorkOrder(
            work_order_id=f"WO-A{i}", timestamp=datetime.now(UTC),
            asset_id="chiller_1", asset_type_at_creation="chiller",
            work_class="CM", lor=8, trigger_source="manual",
            issue_summary="x", status="completed", draft_json={},
        ))
    a = AnalystAgent(site_model=sm, cmms_repo=repo)
    v = await a.evaluate(ConsultContext(query="x", asset_id="chiller_1"))
    assert v.verdict == VERDICT_CAUTION
    assert "CapEx" in v.summary or "capital" in " ".join(v.reasoning).lower()


# ─── Analyst — T3.3c live-Gemma advisory narrative ────────────────────
async def _repo_with_chiller_repairs(
    asset_id: str = "chiller_1", n: int = 17,
) -> MockCMMSRepository:
    """A chiller with enough completed repairs to cross the 40% CapEx
    breakeven — the Analyst returns CAUTION."""
    repo = MockCMMSRepository()
    for i in range(n):
        await repo.save_work_order_async(WorkOrder(
            work_order_id=f"WO-AN-{i}", timestamp=datetime.now(UTC),
            asset_id=asset_id, asset_type_at_creation="chiller",
            work_class="CM", lor=8, trigger_source="manual",
            issue_summary=f"#{i}", status="completed", draft_json={},
        ))
    return repo


@pytest.mark.asyncio
async def test_analyst_llm_narrative_with_kalman():
    """With a live LLM client + Kalman tap, the Analyst attaches a Gemma
    CapEx/OpEx narrative grounded in the cost heuristics + Z-scores."""
    sm = FakeSiteModel({"chiller_1": FakeComponentInfo("chiller_1", "chiller")})
    repo = await _repo_with_chiller_repairs()
    gemma = FakeGemma(reply="Cumulative OpEx approaches the CapEx breakeven; escalate.")
    a = AnalystAgent(
        site_model=sm, cmms_repo=repo,
        llm_client=gemma, telemetry_provider=_fake_kalman_payload,
    )
    v = await a.evaluate(ConsultContext(query="x", asset_id="chiller_1"))

    assert v.llm_narrative == gemma.reply
    assert "gemma:analyst_narrative" in v.evidence_refs
    assert any(e.startswith("hermes:kalman_z:chiller_1") for e in v.evidence_refs)
    assert len(gemma.prompts) == 1
    prompt = gemma.prompts[0]
    assert "LIVE KALMAN TELEMETRY" in prompt
    assert "DETERMINISTIC VERDICT" in prompt
    assert "CAPEX REPLACE" in prompt
    assert "OPEX REPAIR" in prompt


@pytest.mark.asyncio
async def test_analyst_verdict_unchanged_by_llm():
    """ADR-006: the LLM is advisory. A contradicting narrative does not
    move the deterministic CapEx-breakeven verdict."""
    sm = FakeSiteModel({"chiller_1": FakeComponentInfo("chiller_1", "chiller")})
    repo = await _repo_with_chiller_repairs()
    gemma = FakeGemma(reply="Costs are negligible — keep repairing forever, approve.")
    a = AnalystAgent(
        site_model=sm, cmms_repo=repo,
        llm_client=gemma, telemetry_provider=_fake_kalman_payload,
    )
    v = await a.evaluate(ConsultContext(query="x", asset_id="chiller_1"))
    assert v.verdict == VERDICT_CAUTION          # breakeven still wins
    assert v.llm_narrative.startswith("Costs are negligible")


@pytest.mark.asyncio
async def test_analyst_graceful_when_llm_raises():
    """A crashing LLM client degrades to an empty narrative — the verdict
    and the cost framing are unaffected."""
    sm = FakeSiteModel({"chiller_1": FakeComponentInfo("chiller_1", "chiller")})
    repo = await _repo_with_chiller_repairs()
    a = AnalystAgent(
        site_model=sm, cmms_repo=repo,
        llm_client=RaisingGemma(), telemetry_provider=_fake_kalman_payload,
    )
    v = await a.evaluate(ConsultContext(query="x", asset_id="chiller_1"))
    assert v.verdict == VERDICT_CAUTION
    assert v.llm_narrative == ""
    assert "gemma:analyst_narrative" not in v.evidence_refs


@pytest.mark.asyncio
async def test_analyst_no_llm_client_no_narrative():
    """Without an llm_client the Analyst is byte-for-byte its pre-T3.3c
    deterministic self: empty narrative, no Gemma evidence."""
    sm = FakeSiteModel({"ups_a": FakeComponentInfo("ups_a", "ups")})
    repo = MockCMMSRepository()
    a = AnalystAgent(site_model=sm, cmms_repo=repo)
    v = await a.evaluate(ConsultContext(query="x", asset_id="ups_a"))
    assert v.verdict == VERDICT_APPROVE
    assert v.llm_narrative == ""
    assert not any("gemma" in e for e in v.evidence_refs)


# ─── Orchestrator + consensus ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_consensus_safety_veto_outranks_all():
    """Even if all other agents say APPROVE, Safety Officer hard_stop wins."""
    sm = FakeSiteModel({"ups_a": FakeComponentInfo("ups_a", "ups", {
        "redundancy_pillar": "2N", "criticality_class": "medium",
        "voltage_v": 600, "has_dc_link": True,
    })})
    repo = MockCMMSRepository()
    orch = MultiAgentOrchestrator(
        site_model=sm, graphrag=None,
        cmms_repo=repo, rag_service=None,
    )
    result = await orch.consult(
        ConsultContext(query="LOTO ups_a", asset_id="ups_a"),
    )
    assert result.consensus == VERDICT_HARD_STOP
    assert result.safety_officer_veto is True
    assert "VETO" in result.rationale or "ADR-006" in result.rationale


@pytest.mark.asyncio
async def test_consensus_caution_when_only_diagnostician_warns():
    sm = FakeSiteModel({"cdu_a_01": FakeComponentInfo("cdu_a_01", "cdu", {
        "redundancy_pillar": "N+1", "criticality_class": "medium",
        "voltage_v": 480,
    })})
    repo = MockCMMSRepository()
    for i in range(4):
        await repo.save_work_order_async(WorkOrder(
            work_order_id=f"WO-C{i}", timestamp=datetime.now(UTC),
            asset_id="cdu_a_01", asset_type_at_creation="cdu",
            work_class="CM", lor=8, trigger_source="manual",
            issue_summary="x", status="completed", draft_json={},
        ))
    orch = MultiAgentOrchestrator(
        site_model=sm, graphrag=None, cmms_repo=repo, rag_service=None,
    )
    result = await orch.consult(
        ConsultContext(query="LOTO cdu", asset_id="cdu_a_01"),
    )
    # Diagnostician + Analyst both caution at 4 prior completed; Architect
    # might also caution N+1 medium criticality. We assert at least caution.
    assert result.consensus == VERDICT_CAUTION
    assert result.safety_officer_veto is False


@pytest.mark.asyncio
async def test_consensus_approve_clean_state():
    sm = FakeSiteModel({"busway_a_01": FakeComponentInfo("busway_a_01", "busway", {
        "redundancy_pillar": "2N", "criticality_class": "medium",
        "voltage_v": 480,
    })})
    repo = MockCMMSRepository()
    orch = MultiAgentOrchestrator(
        site_model=sm, graphrag=None, cmms_repo=repo, rag_service=None,
    )
    result = await orch.consult(
        ConsultContext(query="busway scan", asset_id="busway_a_01"),
    )
    # Safety Officer will CAUTION any LOTO-eligible asset by design.
    # All other agents approve; consensus is caution (not hard_stop).
    assert result.consensus == VERDICT_CAUTION
    assert result.safety_officer_veto is False
    assert len(result.agents) == 4


@pytest.mark.asyncio
async def test_consensus_returns_4_agents_in_parallel():
    orch = MultiAgentOrchestrator()
    result = await orch.consult(ConsultContext(query="diagnostic"))
    assert len(result.agents) == 4
    names = sorted(a.agent_name for a in result.agents)
    assert names == ["Analyst", "Architect", "Diagnostician", "Safety Officer"]
    assert result.decision_time_ms >= 0


@pytest.mark.asyncio
async def test_orchestrator_survives_agent_crash():
    """If one agent throws, others still produce verdicts."""
    class ExplodingArchitect(ArchitectAgent):
        async def evaluate(self, ctx):
            raise RuntimeError("synthetic crash")
    orch = MultiAgentOrchestrator()
    orch._architect = ExplodingArchitect(site_model=None, graphrag=None)
    result = await orch.consult(ConsultContext(query="x"))
    arch = next(v for v in result.agents if v.agent_name == "Architect")
    assert arch.verdict == VERDICT_DEGRADED
    assert "synthetic crash" in " ".join(arch.reasoning)
    # Other agents still ran
    other_names = [v.agent_name for v in result.agents if v.agent_name != "Architect"]
    assert sorted(other_names) == ["Analyst", "Diagnostician", "Safety Officer"]


# ─── Singleton ────────────────────────────────────────────────────────
def test_singleton_lifecycle():
    reset_orchestrator()
    o1 = get_orchestrator()
    o2 = get_orchestrator()
    assert o1 is o2
    reset_orchestrator()
    o3 = get_orchestrator()
    assert o3 is not o1
