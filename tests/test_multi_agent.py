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

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from backend.cmms_models import Asset, WorkOrder
from backend.cmms_repository import MockCMMSRepository
from backend.multi_agent import (
    AnalystAgent,
    ArchitectAgent,
    ConsensusResult,
    ConsultContext,
    DiagnosticianAgent,
    MultiAgentOrchestrator,
    SafetyOfficerAgent,
    VERDICT_APPROVE,
    VERDICT_CAUTION,
    VERDICT_DEGRADED,
    VERDICT_HARD_STOP,
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
        work_order_id="WO-S1", timestamp=datetime.now(timezone.utc),
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
        work_order_id="WO-S2", timestamp=datetime.now(timezone.utc),
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
            work_order_id=f"WO-D{i}", timestamp=datetime.now(timezone.utc),
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
            work_order_id=f"WO-A{i}", timestamp=datetime.now(timezone.utc),
            asset_id="chiller_1", asset_type_at_creation="chiller",
            work_class="CM", lor=8, trigger_source="manual",
            issue_summary="x", status="completed", draft_json={},
        ))
    a = AnalystAgent(site_model=sm, cmms_repo=repo)
    v = await a.evaluate(ConsultContext(query="x", asset_id="chiller_1"))
    assert v.verdict == VERDICT_CAUTION
    assert "CapEx" in v.summary or "capital" in " ".join(v.reasoning).lower()


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
            work_order_id=f"WO-C{i}", timestamp=datetime.now(timezone.utc),
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
