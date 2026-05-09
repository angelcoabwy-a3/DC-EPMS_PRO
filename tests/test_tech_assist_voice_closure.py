"""Tests for backend.tech_assist.voice_closure (Sprint 7.1c).

Coverage:
  - StubTranscriber returns supplied text
  - ClosureNormalizer._parse_or_fallback handles:
      valid JSON, JSON in markdown fences, trailing prose, malformed
      JSON (fallback synthesizes from raw notes)
  - _coerce_schema enforces severity / work_class enums + types
  - ClosureProcessor.process happy path:
      result_json populated; status NOT auto-completed unless flag;
      follow-ups created with correct priority + severity mapping
  - Audio path raises NotImplementedError when transcriber is None
  - Empty input raises ValueError
  - WO not found raises WorkOrderNotFoundError
  - Critical-asset follow-up escalates priority
  - Unknown asset follow-up is skipped (not crashed)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from backend.cmms_models import Asset, WorkOrder
from backend.cmms_repository import (
    AssetNotFoundError,
    MockCMMSRepository,
    WorkOrderNotFoundError,
)
from backend.tech_assist.voice_closure import (
    ClosureNormalizer,
    ClosureProcessor,
    StubTranscriber,
    get_closure_processor,
    reset_closure_processor,
)


# ─── StubTranscriber ──────────────────────────────────────────────────
def test_stub_transcriber_returns_supplied_text():
    t = StubTranscriber("the quick brown fox")
    assert t.transcribe(b"any audio bytes") == "the quick brown fox"


# ─── ClosureNormalizer._parse_or_fallback ─────────────────────────────
def test_parse_valid_json_passthrough():
    raw = '{"professional_report": "Replaced bearing.", "primary_action": "OK", "parts_used": ["SKF-6308"], "time_spent_min": 45, "safety_events": [], "follow_ups_recommended": []}'
    out = ClosureNormalizer._parse_or_fallback(raw, original_notes="ignored")
    assert out["professional_report"] == "Replaced bearing."
    assert out["parts_used"] == ["SKF-6308"]
    assert out["time_spent_min"] == 45
    assert out["_normalization_status"] == "success"


def test_parse_strips_markdown_fences():
    raw = '```json\n{"professional_report": "Done.", "primary_action": "OK", "parts_used": [], "time_spent_min": null, "safety_events": [], "follow_ups_recommended": []}\n```'
    out = ClosureNormalizer._parse_or_fallback(raw, original_notes="x")
    assert out["professional_report"] == "Done."


def test_parse_extracts_first_json_block_from_prose():
    raw = (
        "Here is the JSON you requested:\n"
        '{"professional_report": "Done.", "primary_action": "OK", "parts_used": [], "time_spent_min": 30, "safety_events": [], "follow_ups_recommended": []}\n'
        "Hope this helps!"
    )
    out = ClosureNormalizer._parse_or_fallback(raw, original_notes="x")
    assert out["professional_report"] == "Done."
    assert out["time_spent_min"] == 30


def test_parse_malformed_falls_back_to_raw():
    raw = "Sorry I cannot produce JSON today."
    out = ClosureNormalizer._parse_or_fallback(raw, original_notes="raw notes here")
    assert out["_normalization_status"] == "fallback_unparsed"
    assert "raw notes here" in out["professional_report"]
    assert out["follow_ups_recommended"] == []


def test_coerce_schema_enforces_severity_enum():
    raw_obj = {
        "professional_report": "X",
        "primary_action": "Y",
        "parts_used": [],
        "time_spent_min": "fifteen",  # invalid int
        "safety_events": [],
        "follow_ups_recommended": [
            {"summary": "Belt wear", "asset_id": "fan_coil_4",
             "severity": "moderate", "suggested_work_class": "PM"},
            {"summary": "Critical", "severity": "critical",
             "suggested_work_class": "FOO"},  # invalid
        ],
    }
    out = ClosureNormalizer._coerce_schema(raw_obj)
    assert out["time_spent_min"] is None  # invalid coerced to None
    f1 = out["follow_ups_recommended"][0]
    assert f1["severity"] == "info"  # invalid moderate -> info
    f2 = out["follow_ups_recommended"][1]
    assert f2["severity"] == "critical"
    assert f2["suggested_work_class"] == "PM"  # invalid FOO -> PM


# ─── ClosureProcessor: full flow ──────────────────────────────────────
@pytest.fixture
def repo():
    return MockCMMSRepository()


@pytest.fixture
async def repo_with_wo(repo):
    await repo.upsert_asset_async(Asset(
        asset_id="fan_coil_4",
        display_name="Fan Coil 4",
        asset_type="cdu",  # closest match for fan coil
        criticality_class="medium",
        linked_mop_id=None,
    ))
    await repo.upsert_asset_async(Asset(
        asset_id="ups_a",
        display_name="UPS A",
        asset_type="ups",
        criticality_class="critical",
        linked_mop_id="T4-MOP-UPS-001",
    ))
    await repo.save_work_order_async(WorkOrder(
        work_order_id="WO-PARENT-1",
        timestamp=datetime.now(timezone.utc),
        asset_id="fan_coil_4",
        asset_type_at_creation="cdu",
        work_class="PM",
        lor=4,
        trigger_source="manual",
        issue_summary="Quarterly bearing PM",
        priority="P3",
        status="in_progress",
        draft_json={},
    ))
    return repo


@pytest.fixture
def stub_normalizer():
    """A normalizer that returns a fixed structured response without
    calling LM Studio. We override .normalize directly."""
    norm = ClosureNormalizer()

    async def fake_normalize(notes, wo_context):
        return {
            "professional_report": "## Maintenance Report\n\nReplaced bearing.",
            "primary_action": "Replaced bearing on fan_coil_4 motor.",
            "parts_used": ["SKF-6308-2RS"],
            "time_spent_min": 45,
            "safety_events": [],
            "follow_ups_recommended": [
                {
                    "summary": "Drive belt showing moderate wear, recommend replacement within 90 days.",
                    "asset_id": "fan_coil_4",
                    "severity": "warn",
                    "suggested_work_class": "PM",
                },
            ],
            "_normalization_status": "success",
        }
    norm.normalize = fake_normalize
    return norm


@pytest.mark.asyncio
async def test_process_persists_normalized_result(repo_with_wo, stub_normalizer):
    cp = ClosureProcessor(cmms_repo=repo_with_wo, normalizer=stub_normalizer)
    result = await cp.process(
        wo_id="WO-PARENT-1",
        cet_id="wilmer",
        notes_text="Cambie rodamiento. Note belt wear, dejado para proximo PM.",
        complete_wo=False,
    )

    assert result["work_order_id"] == "WO-PARENT-1"
    assert result["status_after"] == "in_progress"  # NOT auto-completed
    assert result["normalized"]["primary_action"].startswith("Replaced bearing")
    assert len(result["follow_ups_created"]) == 1
    assert result["raw_notes_chars"] > 30

    # Original WO updated with result_json
    wo = await repo_with_wo.get_work_order_async("WO-PARENT-1")
    assert wo.result_json is not None
    assert wo.result_json["cet_id"] == "wilmer"
    assert wo.result_json["normalized"]["parts_used"] == ["SKF-6308-2RS"]


@pytest.mark.asyncio
async def test_complete_wo_flag_transitions_status(repo_with_wo, stub_normalizer):
    cp = ClosureProcessor(cmms_repo=repo_with_wo, normalizer=stub_normalizer)
    result = await cp.process(
        wo_id="WO-PARENT-1",
        cet_id="wilmer",
        notes_text="All work done as expected, no issues to report at all.",
        complete_wo=True,
    )
    assert result["status_after"] == "completed"
    wo = await repo_with_wo.get_work_order_async("WO-PARENT-1")
    assert wo.status == "completed"


@pytest.mark.asyncio
async def test_follow_up_wo_created_with_correct_priority(repo_with_wo, stub_normalizer):
    cp = ClosureProcessor(cmms_repo=repo_with_wo, normalizer=stub_normalizer)
    result = await cp.process(
        wo_id="WO-PARENT-1",
        cet_id="wilmer",
        notes_text="Replaced part. Belt wear noted. Should monitor next quarter.",
    )
    fup_id = result["follow_ups_created"][0]
    fup = await repo_with_wo.get_work_order_async(fup_id)
    # severity=warn -> L=3,C=3 -> LOR=9 -> P3 (medium criticality, no escalation)
    assert fup.lor == 9
    assert fup.priority == "P3"
    assert fup.work_class == "PM"
    assert fup.status == "pending_approval"
    assert "belt" in fup.issue_summary.lower() or "wear" in fup.issue_summary.lower()
    assert fup.draft_json["parent_wo_id"] == "WO-PARENT-1"
    assert fup.draft_json["lor_breakdown"]["severity_from_dictation"] == "warn"


@pytest.mark.asyncio
async def test_follow_up_critical_severity_critical_asset_escalates(repo_with_wo):
    """Critical asset + critical severity -> P1."""
    cp = ClosureProcessor(cmms_repo=repo_with_wo, normalizer=ClosureNormalizer())

    async def fake_norm(*args, **kwargs):
        return {
            "professional_report": "Done.",
            "primary_action": "Done.",
            "parts_used": [],
            "time_spent_min": None,
            "safety_events": [],
            "follow_ups_recommended": [{
                "summary": "Critical electrical degradation observed",
                "asset_id": "ups_a",
                "severity": "critical",
                "suggested_work_class": "EM",
            }],
            "_normalization_status": "success",
        }
    cp.normalizer.normalize = fake_norm

    result = await cp.process(
        wo_id="WO-PARENT-1",
        cet_id="wilmer",
        notes_text="Found critical issue with UPS A during work.",
    )
    fup_id = result["follow_ups_created"][0]
    fup = await repo_with_wo.get_work_order_async(fup_id)
    # severity=critical (L=4, C=4 -> LOR=16) + critical asset -> P1
    assert fup.priority == "P1"
    assert fup.work_class == "EM"
    assert fup.procedure_class == "EOP"
    assert fup.linked_mop_id == "T4-MOP-UPS-001"


@pytest.mark.asyncio
async def test_follow_up_unknown_asset_skipped_not_crashed(repo_with_wo):
    cp = ClosureProcessor(cmms_repo=repo_with_wo, normalizer=ClosureNormalizer())

    async def fake_norm(*args, **kwargs):
        return {
            "professional_report": "Done.",
            "primary_action": "Done.",
            "parts_used": [],
            "time_spent_min": None,
            "safety_events": [],
            "follow_ups_recommended": [{
                "summary": "Recommend monitoring phantom_asset_999",
                "asset_id": "phantom_asset_999",
                "severity": "info",
                "suggested_work_class": "PM",
            }],
            "_normalization_status": "success",
        }
    cp.normalizer.normalize = fake_norm

    result = await cp.process(
        wo_id="WO-PARENT-1",
        cet_id="wilmer",
        notes_text="Mention a phantom asset; processor should not crash.",
    )
    assert result["follow_ups_created"] == []
    assert len(result["follow_ups_skipped"]) == 1


@pytest.mark.asyncio
async def test_auto_create_disabled_returns_suggestions_only(repo_with_wo, stub_normalizer):
    cp = ClosureProcessor(cmms_repo=repo_with_wo, normalizer=stub_normalizer)
    result = await cp.process(
        wo_id="WO-PARENT-1",
        cet_id="wilmer",
        notes_text="Replaced bearing, belt looked worn but I left it.",
        auto_create_follow_ups=False,
    )
    assert result["follow_ups_created"] == []
    # Suggestion still in normalized output
    assert len(result["normalized"]["follow_ups_recommended"]) == 1


@pytest.mark.asyncio
async def test_audio_without_transcriber_raises(repo_with_wo, stub_normalizer):
    cp = ClosureProcessor(cmms_repo=repo_with_wo, normalizer=stub_normalizer, transcriber=None)
    with pytest.raises(NotImplementedError, match="audio mode unavailable"):
        await cp.process(
            wo_id="WO-PARENT-1",
            cet_id="wilmer",
            audio_bytes=b"\x00\x01\x02",
        )


@pytest.mark.asyncio
async def test_audio_with_stub_transcriber_works(repo_with_wo, stub_normalizer):
    transcriber = StubTranscriber("Replaced bearing on fan_coil_4 successfully.")
    cp = ClosureProcessor(cmms_repo=repo_with_wo, normalizer=stub_normalizer, transcriber=transcriber)
    result = await cp.process(
        wo_id="WO-PARENT-1",
        cet_id="wilmer",
        audio_bytes=b"\x00fake_audio",
    )
    assert result["raw_notes_chars"] > 0
    wo = await repo_with_wo.get_work_order_async("WO-PARENT-1")
    assert "Replaced bearing on fan_coil_4" in wo.result_json["raw_notes"]


@pytest.mark.asyncio
async def test_empty_input_raises():
    repo = MockCMMSRepository()
    cp = ClosureProcessor(cmms_repo=repo)
    with pytest.raises(ValueError, match="notes_text or audio_bytes"):
        await cp.process(wo_id="ANY", cet_id="x")


@pytest.mark.asyncio
async def test_wo_not_found_raises(repo_with_wo, stub_normalizer):
    cp = ClosureProcessor(cmms_repo=repo_with_wo, normalizer=stub_normalizer)
    with pytest.raises(WorkOrderNotFoundError):
        await cp.process(wo_id="WO-DOES-NOT-EXIST", cet_id="x", notes_text="long enough text")


# ─── Singleton ────────────────────────────────────────────────────────
def test_singleton_lifecycle():
    repo = MockCMMSRepository()
    reset_closure_processor()
    p1 = get_closure_processor(cmms_repo=repo)
    p2 = get_closure_processor()
    assert p1 is p2
    reset_closure_processor()
    p3 = get_closure_processor(cmms_repo=repo)
    assert p3 is not p1


def test_get_without_init_raises():
    reset_closure_processor()
    with pytest.raises(RuntimeError, match="not initialized"):
        get_closure_processor()
