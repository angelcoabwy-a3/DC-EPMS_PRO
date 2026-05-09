"""Tests for backend.tech_assist.nameplate_ocr (Sprint 7.1d).

Coverage:
  - StubOCR returns supplied text
  - regex_extract: vendor canonicalization, model, serial, kVA/kW/HP
    capacity, voltage selection (line vs battery), frequency,
    manufacture_date (YYYY-MM and prose forms), confidence scoring
  - LLM fallback parsing: valid JSON, fenced JSON, malformed
  - match_assets: serial exact match, vendor + model fuzzy, capacity
    within 5%, voltage within 5%, candidates ranked by score
  - suggest_action: link_to_existing (>=0.80), operator_confirm
    (>=0.60), seed_new_asset (<0.60 or empty)
  - NameplateProcessor.process: text mode happy path, image mode
    raises NotImplementedError without engine, regex bypass when
    confidence sufficient
  - Empty/short OCR text raises ValueError
  - Singleton lifecycle
"""

from __future__ import annotations

import pytest

from backend.cmms_models import Asset
from backend.cmms_repository import MockCMMSRepository
from backend.tech_assist.nameplate_ocr import (
    LLMNameplateFallback,
    NameplateFields,
    NameplateProcessor,
    StubOCR,
    get_nameplate_processor,
    match_assets,
    regex_extract,
    reset_nameplate_processor,
    suggest_action,
)


# ─── StubOCR ──────────────────────────────────────────────────────────
def test_stub_ocr_returns_supplied_text():
    o = StubOCR("Schneider Galaxy VX 750 kVA")
    assert o.extract_text(b"image bytes") == "Schneider Galaxy VX 750 kVA"


# ─── regex_extract ────────────────────────────────────────────────────
SCHNEIDER_TEXT = (
    "SCHNEIDER ELECTRIC GALAXY VX UPS\n"
    "Model: GVX750-N480\n"
    "Serial: SVX-2024-008812\n"
    "Rated 750 kVA / 675 kW\n"
    "Voltage: 480 VAC, 60 Hz\n"
    "Battery 24 V\n"
    "MFG 2024-03"
)

YORK_CHILLER_TEXT = (
    "York YZ Magnetic-Bearing Centrifugal Chiller\n"
    "Type YZ-1750-MB\n"
    "S/N: YK-2023-A04221\n"
    "1500 ton (5275 kW) capacity\n"
    "480V 3PH 60Hz\n"
    "Manufactured: 2023/06"
)

CUMMINS_GENSET_TEXT = (
    "CUMMINS POWER GENERATION\n"
    "Model QSK95-G24\n"
    "Serial: QSK-95-2024-22018\n"
    "Rated: 2750 kW Standby, 480V, 60 Hz\n"
    "Mfgd 2024/11"
)


def test_regex_extracts_schneider_ups():
    f = regex_extract(SCHNEIDER_TEXT)
    assert f.vendor == "Schneider Electric"
    assert "GVX750" in (f.model or "")
    assert f.serial == "SVX-2024-008812"
    assert f.rated_capacity_value == 750.0
    assert f.rated_capacity_unit == "kVA"
    assert f.voltage_nominal_v == 480.0
    assert f.frequency_hz == 60.0
    assert f.manufacture_date == "2024-03"
    assert f.extraction_confidence >= 0.8


def test_regex_extracts_york_chiller():
    f = regex_extract(YORK_CHILLER_TEXT)
    assert f.vendor == "Johnson Controls York"
    assert "YZ-1750" in (f.model or "")
    assert f.serial == "YK-2023-A04221"
    # Should pick kW (5275) since kVA not present
    assert f.rated_capacity_value == 5275.0
    assert f.rated_capacity_unit == "kW"
    assert f.voltage_nominal_v == 480.0
    assert f.manufacture_date == "2023-06"


def test_regex_extracts_cummins_genset():
    f = regex_extract(CUMMINS_GENSET_TEXT)
    assert f.vendor == "Cummins"
    assert "QSK95" in (f.model or "")
    assert f.serial == "QSK-95-2024-22018"
    assert f.rated_capacity_value == 2750.0
    assert f.rated_capacity_unit == "kW"
    assert f.voltage_nominal_v == 480.0
    assert f.manufacture_date == "2024-11"


def test_regex_voltage_picks_line_not_battery():
    """Line voltage 480 should win over 24V battery rating."""
    f = regex_extract(SCHNEIDER_TEXT)
    assert f.voltage_nominal_v == 480.0


def test_regex_hp_converted_to_kw():
    text = "MOTOR Type ABC123 100 HP, 480V 60Hz"
    f = regex_extract(text)
    # 100 HP * 0.7457 = 74.57 kW
    assert f.rated_capacity_value is not None
    assert abs(f.rated_capacity_value - 74.57) < 0.1
    assert f.rated_capacity_unit == "kW"
    assert f.extra_fields.get("original_rating_hp") == 100.0


def test_regex_low_confidence_when_minimal_text():
    f = regex_extract("just some text with no useful fields")
    assert f.vendor is None
    assert f.extraction_confidence == 0.0


def test_regex_partial_extraction_partial_confidence():
    text = "Eaton model XYZ-100"  # vendor + model only
    f = regex_extract(text)
    assert f.vendor == "Eaton"
    assert "XYZ-100" in (f.model or "")
    # 0.2 vendor + 0.2 model = 0.4
    assert 0.35 <= f.extraction_confidence <= 0.45


# ─── LLM fallback parsing ─────────────────────────────────────────────
def test_llm_parse_valid_json():
    raw = (
        '{"vendor": "Eaton", "model": "ABC-100", "serial": null, '
        '"rated_capacity_value": 100, "rated_capacity_unit": "kW", '
        '"voltage_nominal_v": 480, "frequency_hz": 60, '
        '"manufacture_date": null, "extra_fields": {}}'
    )
    f = LLMNameplateFallback._parse_or_fallback(raw, "ocr text raw")
    assert f.vendor == "Eaton"
    assert f.model == "ABC-100"
    assert f.serial is None
    assert f.rated_capacity_value == 100.0
    assert f.rated_capacity_unit == "kW"
    assert f.voltage_nominal_v == 480.0
    assert f.extraction_method == "llm"


def test_llm_parse_fenced_json():
    raw = '```json\n{"vendor": "ABB", "model": null, "serial": null, "rated_capacity_value": null, "rated_capacity_unit": null, "voltage_nominal_v": null, "frequency_hz": null, "manufacture_date": null, "extra_fields": {}}\n```'
    f = LLMNameplateFallback._parse_or_fallback(raw, "ocr")
    assert f.vendor == "ABB"


def test_llm_parse_malformed_returns_empty_fields():
    raw = "Sorry I cannot produce JSON today"
    f = LLMNameplateFallback._parse_or_fallback(raw, "ocr text")
    assert f.vendor is None
    assert f.extraction_confidence == 0.0
    assert f.extraction_method == "fallback"


# ─── Asset matcher ────────────────────────────────────────────────────
@pytest.fixture
def sample_assets():
    return [
        Asset(
            asset_id="ups_a", display_name="UPS A", asset_type="ups",
            vendor="Schneider Electric", model="GVX750-N480",
            rated_capacity_kw=750.0, rated_capacity_unit="kVA",
            criticality_class="critical",
            metadata_json={"serial": "SVX-2024-008812", "voltage_nominal_v": 480},
        ),
        Asset(
            asset_id="ups_b", display_name="UPS B", asset_type="ups",
            vendor="Schneider Electric", model="GVX750-N480",
            rated_capacity_kw=750.0,
            criticality_class="critical",
            metadata_json={"serial": "SVX-2024-008813", "voltage_nominal_v": 480},
        ),
        Asset(
            asset_id="chiller_1", display_name="Chiller 1", asset_type="chiller",
            vendor="Johnson Controls York", model="YZ-1750-MB",
            rated_capacity_kw=5275.0, criticality_class="critical",
            metadata_json={"serial": "YK-2023-A04221"},
        ),
    ]


def test_match_serial_exact_wins(sample_assets):
    f = NameplateFields(
        vendor="Schneider Electric", model="GVX750-N480",
        serial="SVX-2024-008812",
        rated_capacity_value=750.0, rated_capacity_unit="kVA",
        voltage_nominal_v=480.0,
    )
    cands = match_assets(f, sample_assets, top_k=3)
    assert cands[0].asset_id == "ups_a"
    assert cands[0].score >= 0.80
    assert "serial_exact" in cands[0].match_reasons


def test_match_no_serial_uses_vendor_model_fuzzy(sample_assets):
    f = NameplateFields(
        vendor="Schneider Electric", model="GVX750-N480",
        rated_capacity_value=750.0, rated_capacity_unit="kVA",
        voltage_nominal_v=480.0,
    )
    cands = match_assets(f, sample_assets, top_k=3)
    # Both UPS share vendor+model -> high but tied scores
    assert len(cands) >= 2
    assert cands[0].score >= 0.45
    assert "vendor_match" in " ".join(cands[0].match_reasons)


def test_match_capacity_off_does_not_count(sample_assets):
    f = NameplateFields(
        vendor="Schneider Electric", model="GVX750-N480",
        rated_capacity_value=500.0, rated_capacity_unit="kVA",
    )
    cands = match_assets(f, sample_assets, top_k=3)
    # capacity 500 vs asset 750 -> ratio 0.66, NOT in [0.95, 1.05]
    for c in cands:
        assert "capacity_match" not in c.match_reasons


def test_match_chiller_canonical_vendor(sample_assets):
    f = NameplateFields(
        vendor="Johnson Controls York", model="YZ-1750-MB",
        serial="YK-2023-A04221",
    )
    cands = match_assets(f, sample_assets, top_k=3)
    assert cands[0].asset_id == "chiller_1"
    assert cands[0].score >= 0.80


def test_match_no_candidate_returns_empty(sample_assets):
    f = NameplateFields(vendor="UnknownVendor")
    cands = match_assets(f, sample_assets, top_k=3)
    assert cands == []


# ─── suggest_action policy ────────────────────────────────────────────
def test_suggest_link_when_high_confidence():
    from backend.tech_assist.nameplate_ocr import MatchCandidate
    cands = [MatchCandidate(asset_id="ups_a", score=0.85, match_reasons=["serial_exact"], asset_summary={})]
    a = suggest_action(cands)
    assert a["action"] == "link_to_existing"
    assert a["asset_id"] == "ups_a"


def test_suggest_confirm_when_medium():
    from backend.tech_assist.nameplate_ocr import MatchCandidate
    cands = [MatchCandidate(asset_id="ups_a", score=0.65, match_reasons=["vendor_match"], asset_summary={})]
    a = suggest_action(cands)
    assert a["action"] == "operator_confirm"


def test_suggest_seed_when_low():
    from backend.tech_assist.nameplate_ocr import MatchCandidate
    cands = [MatchCandidate(asset_id="ups_a", score=0.40, match_reasons=[], asset_summary={})]
    a = suggest_action(cands)
    assert a["action"] == "seed_new_asset"


def test_suggest_seed_when_empty():
    a = suggest_action([])
    assert a["action"] == "seed_new_asset"


# ─── NameplateProcessor.process ───────────────────────────────────────
@pytest.fixture
async def repo_seeded(sample_assets):
    repo = MockCMMSRepository()
    for a in sample_assets:
        await repo.upsert_asset_async(a)
    return repo


@pytest.mark.asyncio
async def test_process_text_mode_happy_path(repo_seeded):
    np = NameplateProcessor(cmms_repo=repo_seeded, ocr_engine=None, llm_fallback=None)
    result = await np.process(ocr_text=SCHNEIDER_TEXT)
    f = result["extracted_fields"]
    assert f["vendor"] == "Schneider Electric"
    assert f["serial"] == "SVX-2024-008812"
    assert f["rated_capacity_value"] == 750.0
    assert result["candidates"][0]["asset_id"] == "ups_a"
    assert result["suggested_action"]["action"] == "link_to_existing"
    assert result["elapsed_ms"] >= 0
    assert f["extraction_method"] == "regex"


@pytest.mark.asyncio
async def test_process_image_without_engine_raises(repo_seeded):
    np = NameplateProcessor(cmms_repo=repo_seeded, ocr_engine=None)
    with pytest.raises(NotImplementedError, match="image mode unavailable"):
        await np.process(image_bytes=b"\x00\x01")


@pytest.mark.asyncio
async def test_process_image_with_stub_ocr(repo_seeded):
    stub = StubOCR(SCHNEIDER_TEXT)
    np = NameplateProcessor(cmms_repo=repo_seeded, ocr_engine=stub, llm_fallback=None)
    result = await np.process(image_bytes=b"\x00fake_jpg")
    assert result["extracted_fields"]["vendor"] == "Schneider Electric"
    assert result["candidates"][0]["asset_id"] == "ups_a"


@pytest.mark.asyncio
async def test_process_low_confidence_falls_back_to_llm(repo_seeded):
    """When regex confidence < 0.4 AND llm_fallback configured, LLM runs."""
    fake_llm = LLMNameplateFallback()

    async def fake_extract(_ocr_text):
        return NameplateFields(
            vendor="Eaton", model="9PXM-PARTIAL", rated_capacity_value=20.0,
            rated_capacity_unit="kVA", voltage_nominal_v=208.0,
            extraction_method="llm", extraction_confidence=0.6,
        )
    fake_llm.extract = fake_extract

    np = NameplateProcessor(cmms_repo=repo_seeded, ocr_engine=None, llm_fallback=fake_llm)
    # OCR text with no recognizable patterns
    result = await np.process(ocr_text="totally garbled gibberish nameplate text")
    assert result["extracted_fields"]["extraction_method"] in ("llm", "hybrid")
    assert result["extracted_fields"]["vendor"] == "Eaton"


@pytest.mark.asyncio
async def test_process_llm_fallback_failure_keeps_regex(repo_seeded):
    fake_llm = LLMNameplateFallback()

    async def boom(_ocr_text):
        raise RuntimeError("LM Studio offline")
    fake_llm.extract = boom

    np = NameplateProcessor(cmms_repo=repo_seeded, ocr_engine=None, llm_fallback=fake_llm)
    result = await np.process(ocr_text="garbled text")
    assert result["extracted_fields"]["extraction_method"] == "regex_only_llm_failed"


@pytest.mark.asyncio
async def test_process_empty_text_raises(repo_seeded):
    np = NameplateProcessor(cmms_repo=repo_seeded)
    with pytest.raises(ValueError, match="OCR text too short"):
        await np.process(ocr_text="x")


@pytest.mark.asyncio
async def test_process_no_input_raises(repo_seeded):
    np = NameplateProcessor(cmms_repo=repo_seeded)
    with pytest.raises(ValueError, match="ocr_text or image_bytes"):
        await np.process()


# ─── Singleton ────────────────────────────────────────────────────────
def test_singleton_lifecycle():
    repo = MockCMMSRepository()
    reset_nameplate_processor()
    p1 = get_nameplate_processor(cmms_repo=repo)
    p2 = get_nameplate_processor()
    assert p1 is p2
    reset_nameplate_processor()
    p3 = get_nameplate_processor(cmms_repo=repo)
    assert p3 is not p1


def test_get_without_init_raises():
    reset_nameplate_processor()
    with pytest.raises(RuntimeError, match="not initialized"):
        get_nameplate_processor()
