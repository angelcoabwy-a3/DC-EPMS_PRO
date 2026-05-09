"""Tests for backend.tech_assist.troubleshoot (Sprint 7.1a).

Coverage:
  - Context gathering: chunks, asset metadata, history (mocked)
  - Safety keyword detection per query content
  - LLM bypass mode (use_llm=False) returns retrieval context only
  - Asset not found: handled gracefully
  - History window filter (only recent WOs included)
  - Prompt building uses correct citations format
  - Response shape matches contract
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.cmms_models import Asset, WorkOrder
from backend.cmms_repository import AssetNotFoundError, MockCMMSRepository
from backend.tech_assist.models import TroubleshootRequest
from backend.tech_assist.troubleshoot import (
    TroubleshootAgent,
    get_troubleshoot_agent,
    reset_troubleshoot_agent,
)


# ─────────────────────────────────────────────────────────────────────
#  Fixtures
# ─────────────────────────────────────────────────────────────────────
@pytest.fixture
def fake_rag():
    rag = MagicMock()
    rag.query.return_value = {
        "results": [
            {
                "doc_id": "T2-VEN-YK-CHI-YZ",
                "text": "E-204: refrigerant low charge alarm. Triggered when pressure delta crosses -1.4 bar for >300s.",
                "tier": 2,
                "metadata": {"vendor": "York", "page": 47},
                "score": 0.85,
                "similarity": 0.85,
            },
            {
                "doc_id": "T1-SAF-LOTO-001",
                "text": "Lockout tagout procedure: open VSD disconnect, apply personal lock + tag.",
                "tier": 1,
                "metadata": {"safety_critical": True},
                "score": 0.72,
                "similarity": 0.42,
            },
        ],
    }
    return rag


@pytest.fixture
def fake_rag_error():
    rag = MagicMock()
    rag.query.return_value = {"results": [], "error": "ChromaDB unavailable"}
    return rag


@pytest.fixture
def cmms_repo_with_history():
    repo = MockCMMSRepository()
    return repo


@pytest.fixture
async def populated_repo(cmms_repo_with_history):
    repo = cmms_repo_with_history
    await repo.upsert_asset_async(Asset(
        asset_id="chiller_1",
        display_name="Chiller 1 (York YZ)",
        asset_type="chiller",
        vendor="York",
        model="YZ-1750-MB",
        path=None,
        redundancy_pillar="N+1",
        criticality_class="critical",
        linked_mop_id="T4-MOP-CHI-001",
    ))
    # Recent WO (within 12 months)
    await repo.save_work_order_async(WorkOrder(
        work_order_id="WO-20251105-a3b2",
        timestamp=datetime.now(timezone.utc) - timedelta(days=180),
        asset_id="chiller_1",
        asset_type_at_creation="chiller",
        work_class="CM",
        lor=12,
        trigger_source="manual",
        issue_summary="E-204 alarm during summer load",
        priority="P2",
        status="completed",
        result_json={"summary": "Topped off R-1233zd by 1.2kg, leak test clean"},
        draft_json={},
    ))
    # Old WO (outside default 12-month window)
    await repo.save_work_order_async(WorkOrder(
        work_order_id="WO-20240617-c1d4",
        timestamp=datetime.now(timezone.utc) - timedelta(days=400),
        asset_id="chiller_1",
        asset_type_at_creation="chiller",
        work_class="PM",
        lor=4,
        trigger_source="scheduled_pm",
        issue_summary="Quarterly chiller PM",
        priority="P3",
        status="completed",
        draft_json={},
    ))
    return repo


# ─────────────────────────────────────────────────────────────────────
#  Context gathering
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_chunks_retrieved_with_query_and_error_code(fake_rag):
    agent = TroubleshootAgent(rag_service=fake_rag, cmms_repo=None)
    req = TroubleshootRequest(query="how do I clear E-204?", error_code="E-204")
    chunks = agent._gather_chunks(req, sources={})
    assert len(chunks) == 2
    assert chunks[0].doc_id == "T2-VEN-YK-CHI-YZ"
    assert chunks[0].tier == 2
    # Verify the rag query receives concatenated error_code + query
    fake_rag.query.assert_called_once()
    call_text = fake_rag.query.call_args[0][0]
    assert "E-204" in call_text


@pytest.mark.asyncio
async def test_chunks_empty_when_rag_unavailable():
    agent = TroubleshootAgent(rag_service=None, cmms_repo=None)
    req = TroubleshootRequest(query="any question")
    chunks = agent._gather_chunks(req, sources={})
    assert chunks == []


@pytest.mark.asyncio
async def test_chunks_empty_when_rag_errors(fake_rag_error):
    agent = TroubleshootAgent(rag_service=fake_rag_error, cmms_repo=None)
    req = TroubleshootRequest(query="any question")
    sources = {}
    chunks = agent._gather_chunks(req, sources)
    assert chunks == []
    assert "error" in sources["rag_service"]


@pytest.mark.asyncio
async def test_asset_context_returned_with_recent_history(populated_repo, fake_rag):
    agent = TroubleshootAgent(rag_service=fake_rag, cmms_repo=populated_repo)
    req = TroubleshootRequest(query="E-204 troubleshooting", asset_id="chiller_1",
                              error_code="E-204", history_months=12)
    asset, history = await agent._gather_asset_context(req, sources={})
    assert asset is not None
    assert asset.asset_id == "chiller_1"
    assert asset.linked_mop_id == "T4-MOP-CHI-001"
    # Only the recent WO (180 days) within 12-month window
    assert len(history) == 1
    assert history[0].work_order_id == "WO-20251105-a3b2"
    assert history[0].closure_summary is not None  # extracted from result_json


@pytest.mark.asyncio
async def test_asset_not_found_returns_empty(populated_repo, fake_rag):
    agent = TroubleshootAgent(rag_service=fake_rag, cmms_repo=populated_repo)
    req = TroubleshootRequest(query="anything", asset_id="phantom_asset")
    sources = {}
    asset, history = await agent._gather_asset_context(req, sources)
    assert asset is None
    assert history == []
    assert "not found" in sources["asset_metadata"]


@pytest.mark.asyncio
async def test_no_asset_id_skips_history(fake_rag):
    agent = TroubleshootAgent(rag_service=fake_rag, cmms_repo=None)
    req = TroubleshootRequest(query="general question")
    sources = {}
    asset, history = await agent._gather_asset_context(req, sources)
    assert asset is None
    assert history == []


@pytest.mark.asyncio
async def test_history_window_filters_old_wos(populated_repo, fake_rag):
    agent = TroubleshootAgent(rag_service=fake_rag, cmms_repo=populated_repo)
    # 6-month window excludes the 180-day-old WO
    req = TroubleshootRequest(query="any text", asset_id="chiller_1", history_months=3)
    _, history = await agent._gather_asset_context(req, sources={})
    assert len(history) == 0  # 180 days > 90 days (3 months)


# ─────────────────────────────────────────────────────────────────────
#  Safety keyword detection
# ─────────────────────────────────────────────────────────────────────
def test_safety_keywords_detect_loto():
    kw = TroubleshootAgent._detect_safety_keywords("How do I apply LOTO to UPS A?")
    assert "loto" in kw


def test_safety_keywords_detect_arc_flash():
    kw = TroubleshootAgent._detect_safety_keywords("Arc-flash boundary question")
    assert "arc-flash" in kw


def test_safety_keywords_no_match_for_innocent_query():
    kw = TroubleshootAgent._detect_safety_keywords("What does the green LED mean?")
    assert kw == []


def test_safety_keywords_multiple():
    kw = TroubleshootAgent._detect_safety_keywords(
        "Refrigerant leak detected, need PPE for energized work"
    )
    assert "refrigerant" in kw
    assert "leak" in kw
    assert "ppe" in kw
    assert "energized" in kw


# ─────────────────────────────────────────────────────────────────────
#  Use_llm=False bypass
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_no_llm_call_when_use_llm_false(fake_rag, populated_repo):
    agent = TroubleshootAgent(rag_service=fake_rag, cmms_repo=populated_repo)
    req = TroubleshootRequest(
        query="E-204 issue", asset_id="chiller_1", error_code="E-204", use_llm=False,
    )
    resp = await agent.answer(req)
    assert resp.llm_synthesis_status == "skipped"
    assert resp.llm_answer is None
    assert resp.llm_model is None
    # But retrieval context IS populated
    assert len(resp.chunks_retrieved) == 2
    assert resp.history_count == 1
    assert resp.asset_metadata is not None


# ─────────────────────────────────────────────────────────────────────
#  Prompt building
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_prompt_includes_asset_context_and_history(populated_repo, fake_rag):
    agent = TroubleshootAgent(rag_service=fake_rag, cmms_repo=populated_repo)
    req = TroubleshootRequest(query="E-204", asset_id="chiller_1", error_code="E-204")
    chunks = agent._gather_chunks(req, sources={})
    asset, history = await agent._gather_asset_context(req, sources={})
    prompt = agent._build_user_prompt(req, chunks, history, asset)

    # Asset context
    assert "chiller_1" in prompt
    assert "York" in prompt
    assert "T4-MOP-CHI-001" in prompt
    assert "critical" in prompt
    # Manual chunks with citations
    assert "T2-VEN-YK-CHI-YZ" in prompt
    assert "Tier 2" in prompt
    # History
    assert "WO-20251105-a3b2" in prompt
    assert "summer load" in prompt
    # Error code surfaced
    assert "E-204" in prompt


@pytest.mark.asyncio
async def test_prompt_handles_no_asset_no_history(fake_rag):
    agent = TroubleshootAgent(rag_service=fake_rag, cmms_repo=None)
    req = TroubleshootRequest(query="general electrical question")
    chunks = agent._gather_chunks(req, sources={})
    prompt = agent._build_user_prompt(req, chunks, [], None)
    assert "no asset_id supplied" in prompt
    assert "no relevant history" in prompt


# ─────────────────────────────────────────────────────────────────────
#  Full answer() flow with LLM mocked
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_answer_full_flow_with_mocked_llm(fake_rag, populated_repo, monkeypatch):
    agent = TroubleshootAgent(rag_service=fake_rag, cmms_repo=populated_repo)

    async def fake_call(*args, **kwargs):
        return (
            "1. ERROR CODE MEANING\n"
            "E-204 is the refrigerant low-charge alarm [manual:T2-VEN-YK-CHI-YZ].\n\n"
            "2. RANKED CAUSES\n"
            "1. Charge depletion (matches [WO:WO-20251105-a3b2]).\n\n"
            "3. STEP-BY-STEP FIX\n"
            "1. [REQUIRES LOTO T1-SAF-LOTO-001] De-energize at VSD.\n"
        )
    monkeypatch.setattr(agent, "_call_lm_studio", fake_call)

    req = TroubleshootRequest(
        query="how do I clear E-204?",
        asset_id="chiller_1",
        error_code="E-204",
    )
    resp = await agent.answer(req)
    assert resp.llm_synthesis_status == "success"
    assert resp.llm_answer is not None
    assert "E-204" in resp.llm_answer
    assert "[WO:WO-20251105-a3b2]" in resp.llm_answer
    assert "REQUIRES LOTO" in resp.llm_answer
    assert resp.decision_time_ms >= 0
    assert resp.sources_consulted["lm_studio"] == "OK"


@pytest.mark.asyncio
async def test_answer_handles_llm_timeout_gracefully(fake_rag, monkeypatch):
    import httpx
    agent = TroubleshootAgent(rag_service=fake_rag, cmms_repo=None)

    async def raise_timeout(*args, **kwargs):
        raise httpx.TimeoutException("simulated")
    monkeypatch.setattr(agent, "_call_lm_studio", raise_timeout)

    req = TroubleshootRequest(query="anything")
    resp = await agent.answer(req)
    assert resp.llm_synthesis_status == "timeout"
    assert resp.llm_answer is None
    # Retrieval still populated
    assert len(resp.chunks_retrieved) == 2


# ─────────────────────────────────────────────────────────────────────
#  Singleton
# ─────────────────────────────────────────────────────────────────────
def test_singleton_lifecycle(fake_rag):
    reset_troubleshoot_agent()
    a1 = get_troubleshoot_agent(rag_service=fake_rag)
    a2 = get_troubleshoot_agent()
    assert a1 is a2
    reset_troubleshoot_agent()
    a3 = get_troubleshoot_agent(rag_service=fake_rag)
    assert a3 is not a1


def test_get_without_init_raises():
    reset_troubleshoot_agent()
    with pytest.raises(RuntimeError, match="not initialized"):
        get_troubleshoot_agent()
