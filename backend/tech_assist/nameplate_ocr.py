"""
backend/tech_assist/nameplate_ocr.py
=====================================
Sprint 7.1d — Nameplate OCR + asset fuzzy match.

Pipeline (text-mode MVP; image-mode pluggable for V2):

    technician photo of equipment nameplate
            |
            v   OCREngine (V2: easyocr / tesseract / Claude vision)
    raw OCR text str
            |
            v   NameplateExtractor (regex-first, LLM fallback)
    structured fields {vendor, model, serial, rated_capacity,
                       voltage, frequency, manufacture_date, ...}
            |
            v   AssetMatcher (difflib SequenceMatcher, no new deps)
    ranked candidates [{asset_id, score, match_reasons}, ...]
            |
            v
    NameplateProcessor return:
       extracted_fields, top_candidates, suggested_action
       (link_to_existing | seed_new_asset)

Design choices:

  * Pluggable OCREngine ABC (StubOCR for tests, future EasyOCREngine
    when easyocr is installed). MVP defaults to None and only the
    text path works.
  * Regex-first extraction: fast, deterministic, covers the standard
    nameplate patterns (Schneider Galaxy VX, York YZ, Cummins genset,
    NVIDIA rack labels). LLM fallback only when regex misses a
    critical field (vendor + model). Keeps tests fast and avoids
    LM Studio dependency for the common path.
  * Asset matching uses stdlib difflib.SequenceMatcher; no new deps.
    Score thresholds:
      >= 0.80  near-exact match (auto-link candidate)
      >= 0.60  plausible match (operator confirms)
      <  0.60  weak match (suggest seed new asset)
  * Per ADR-006: extracted nameplate NEVER auto-modifies an asset
    row. The endpoint returns suggestions; the operator explicitly
    approves any registry update via a separate (V2) endpoint.
"""

from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

import httpx

from backend.cmms_models import Asset
from backend.cmms_repository import (
    CMMSRepositoryError,
    PostgresCMMSRepository,
)

log = logging.getLogger(__name__)


# ─── LLM dispatch (mirrors troubleshoot/voice_closure) ─────────────────
LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"
LM_STUDIO_MODEL = "gemma-4-e2b-it"
LM_STUDIO_TIMEOUT_S = 10.0


# ─── OCR Engine interface ──────────────────────────────────────────────
class OCREngine(ABC):
    """Pluggable image -> text. None in MVP (text-only mode)."""

    @abstractmethod
    def extract_text(self, image_bytes: bytes) -> str:
        ...


class StubOCR(OCREngine):
    """Test OCR: returns pre-supplied text regardless of image."""

    def __init__(self, output: str):
        self._output = output

    def extract_text(self, _image_bytes: bytes) -> str:
        return self._output


# Future (V2): EasyOCREngine using easyocr Python lib (~600MB model).
# Wired by env var DC_EPMS_OCR=easyocr|stub|none.


# ─── Nameplate field extraction ────────────────────────────────────────
@dataclass
class NameplateFields:
    """Structured nameplate metadata extracted from OCR text."""
    vendor: str | None = None
    model: str | None = None
    serial: str | None = None
    rated_capacity_value: float | None = None
    rated_capacity_unit: str | None = None
    voltage_nominal_v: float | None = None
    frequency_hz: float | None = None
    manufacture_date: str | None = None
    extra_fields: dict[str, Any] = field(default_factory=dict)
    extraction_method: str = "regex"  # "regex" | "llm" | "hybrid" | "fallback"
    extraction_confidence: float = 0.0  # 0..1
    raw_ocr_chars: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "vendor": self.vendor,
            "model": self.model,
            "serial": self.serial,
            "rated_capacity_value": self.rated_capacity_value,
            "rated_capacity_unit": self.rated_capacity_unit,
            "voltage_nominal_v": self.voltage_nominal_v,
            "frequency_hz": self.frequency_hz,
            "manufacture_date": self.manufacture_date,
            "extra_fields": dict(self.extra_fields),
            "extraction_method": self.extraction_method,
            "extraction_confidence": round(self.extraction_confidence, 2),
            "raw_ocr_chars": self.raw_ocr_chars,
        }


# Known vendor patterns. Order matters: more-specific patterns first.
VENDOR_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Schneider Electric",  re.compile(r"\b(?:schneider|square[- ]?d|apc)\b", re.I)),
    ("Johnson Controls York", re.compile(r"\b(?:york|johnson[- ]?controls)\b", re.I)),
    ("Cummins",             re.compile(r"\bcummins\b", re.I)),
    ("Caterpillar",         re.compile(r"\b(?:caterpillar|\bcat\b)\b", re.I)),
    ("ASCO",                re.compile(r"\basco\b", re.I)),
    ("Russelectric",        re.compile(r"\brusselectric\b", re.I)),
    ("Eaton",               re.compile(r"\beaton\b", re.I)),
    ("ABB",                 re.compile(r"\babb\b", re.I)),
    ("Siemens",             re.compile(r"\bsiemens\b", re.I)),
    ("Carrier",             re.compile(r"\bcarrier\b", re.I)),
    ("Trane",               re.compile(r"\btrane\b", re.I)),
    ("NVIDIA",              re.compile(r"\bnvidia\b", re.I)),
    ("Dell",                re.compile(r"\bdell\b", re.I)),
    ("HP Enterprise",       re.compile(r"\b(?:hp[- ]?enterprise|hpe)\b", re.I)),
    ("Starline",            re.compile(r"\bstarline\b", re.I)),
]

# Pattern shortcuts
RE_MODEL          = re.compile(r"\b(?:model|type|catalog\s*(?:no\.?|num(?:ber)?)?)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-/.\s]{1,40}?)(?:\s|$|,|;)", re.I)
RE_SERIAL         = re.compile(r"\b(?:s/?n|serial(?:\s*(?:no|num(?:ber)?))?)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-]{3,40})", re.I)
RE_KVA            = re.compile(r"(\d+(?:[.,]\d+)?)\s*k\s*VA\b", re.I)
RE_KW             = re.compile(r"(\d+(?:[.,]\d+)?)\s*k\s*W\b", re.I)
RE_HP             = re.compile(r"(\d+(?:[.,]\d+)?)\s*HP\b", re.I)
RE_VOLTAGE        = re.compile(r"(\d{2,4})\s*V(?:\s*AC)?\b", re.I)
RE_HZ             = re.compile(r"(\d{2,3})\s*Hz\b", re.I)
RE_DATE_YYYY_MM   = re.compile(r"\b(20\d{2})[-/](0[1-9]|1[0-2])\b")
RE_DATE_MFG       = re.compile(r"\b(?:mfg|mfgd|manuf(?:actured)?)[:\s]*([A-Za-z0-9 /\-,.]{4,20})", re.I)


def _strip(text: str | None) -> str | None:
    if text is None:
        return None
    text = text.strip().rstrip(",.;:")
    return text or None


def regex_extract(ocr_text: str) -> NameplateFields:
    """Fast, deterministic extraction. Returns confidence based on
    how many critical fields were found."""
    fields = NameplateFields(raw_ocr_chars=len(ocr_text))

    # Vendor (first matching pattern wins)
    for vendor_name, pat in VENDOR_PATTERNS:
        if pat.search(ocr_text):
            fields.vendor = vendor_name
            break

    # Model
    m = RE_MODEL.search(ocr_text)
    if m:
        fields.model = _strip(m.group(1))

    # Serial
    m = RE_SERIAL.search(ocr_text)
    if m:
        fields.serial = _strip(m.group(1))

    # Rated capacity (kVA preferred over kW for UPS / transformer
    # nameplates; kW for chillers / gensets)
    m = RE_KVA.search(ocr_text)
    if m:
        try:
            fields.rated_capacity_value = float(m.group(1).replace(",", "."))
            fields.rated_capacity_unit = "kVA"
        except ValueError:
            pass
    if fields.rated_capacity_value is None:
        m = RE_KW.search(ocr_text)
        if m:
            try:
                fields.rated_capacity_value = float(m.group(1).replace(",", "."))
                fields.rated_capacity_unit = "kW"
            except ValueError:
                pass
    if fields.rated_capacity_value is None:
        m = RE_HP.search(ocr_text)
        if m:
            try:
                fields.rated_capacity_value = float(m.group(1).replace(",", ".")) * 0.7457
                fields.rated_capacity_unit = "kW"  # HP -> kW conversion
                fields.extra_fields["original_rating_hp"] = float(m.group(1).replace(",", "."))
            except ValueError:
                pass

    # Voltage (prefer the larger/non-trivial number; e.g. 480V over 24V battery)
    voltages = [int(g) for g in RE_VOLTAGE.findall(ocr_text)]
    if voltages:
        # Take the largest (typical line voltage) but cap at 35000 (35kV utility)
        plausible = [v for v in voltages if 100 <= v <= 35000]
        if plausible:
            fields.voltage_nominal_v = float(max(plausible))
        elif voltages:
            fields.voltage_nominal_v = float(max(voltages))

    # Frequency
    m = RE_HZ.search(ocr_text)
    if m:
        try:
            fields.frequency_hz = float(m.group(1))
        except ValueError:
            pass

    # Manufacture date (YYYY-MM preferred; fallback to "mfg ..." prose)
    m = RE_DATE_YYYY_MM.search(ocr_text)
    if m:
        fields.manufacture_date = f"{m.group(1)}-{m.group(2)}"
    else:
        m = RE_DATE_MFG.search(ocr_text)
        if m:
            fields.manufacture_date = _strip(m.group(1))

    # Confidence: 0.2 per critical field found (vendor, model,
    # rated_capacity, voltage, serial), capped at 1.0
    score = 0.0
    for v in (fields.vendor, fields.model, fields.serial,
              fields.rated_capacity_value, fields.voltage_nominal_v):
        if v is not None and v != "":
            score += 0.2
    fields.extraction_confidence = min(1.0, score)
    fields.extraction_method = "regex"
    return fields


# ─── LLM fallback extractor (when regex misses critical fields) ────────
SYSTEM_PROMPT_LLM = """\
You are an industrial equipment nameplate OCR post-processor. Given
raw OCR text from a photo of a device nameplate, output a JSON object
with the structured fields below. Output ONLY valid JSON, no preamble,
no fences.

Schema:
{
  "vendor": "<canonical manufacturer name or null>",
  "model": "<model number/name or null>",
  "serial": "<serial number or null>",
  "rated_capacity_value": <float or null>,
  "rated_capacity_unit": "kVA" | "kW" | "HP" | "ton" | null,
  "voltage_nominal_v": <integer or null, line voltage>,
  "frequency_hz": <integer or null, 50 or 60 typical>,
  "manufacture_date": "<YYYY-MM string or null>",
  "extra_fields": {<any other observed fields>}
}

Hard rules:
- Output VALID JSON ONLY. No markdown.
- Never invent values. If a field is not visible in OCR, return null.
- Voltage: line voltage (480, 600, 4160, 13800, 35000), NOT battery.
- Vendor: canonicalize ("Square D" -> "Schneider Electric").
"""


class LLMNameplateFallback:
    """Used when regex extraction confidence is low."""

    def __init__(
        self,
        url: str = LM_STUDIO_URL,
        model: str = LM_STUDIO_MODEL,
        timeout_s: float = LM_STUDIO_TIMEOUT_S,
    ):
        self.url = url
        self.model = model
        self.timeout_s = timeout_s

    async def extract(self, ocr_text: str) -> NameplateFields:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT_LLM},
                {"role": "user",   "content": f"OCR TEXT:\n{ocr_text.strip()}"},
            ],
            "temperature": 0.05,
            "max_tokens": 400,
        }
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            resp = await client.post(self.url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"LLM response malformed: {e}") from e
        return self._parse_or_fallback(text, ocr_text)

    @staticmethod
    def _parse_or_fallback(text: str, raw: str) -> NameplateFields:
        text = re.sub(r"^```(?:json)?\s*", "", text.strip())
        text = re.sub(r"\s*```$", "", text)
        try:
            obj = json.loads(text)
            if not isinstance(obj, dict):
                raise ValueError("not a dict")
        except (json.JSONDecodeError, ValueError):
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if not m:
                # Total LLM failure -> empty fields
                return NameplateFields(
                    extraction_method="fallback",
                    extraction_confidence=0.0,
                    raw_ocr_chars=len(raw),
                )
            try:
                obj = json.loads(m.group(0))
            except json.JSONDecodeError:
                return NameplateFields(
                    extraction_method="fallback",
                    extraction_confidence=0.0,
                    raw_ocr_chars=len(raw),
                )

        fields = NameplateFields(
            vendor=obj.get("vendor") or None,
            model=obj.get("model") or None,
            serial=obj.get("serial") or None,
            rated_capacity_value=_safe_float(obj.get("rated_capacity_value")),
            rated_capacity_unit=obj.get("rated_capacity_unit") or None,
            voltage_nominal_v=_safe_float(obj.get("voltage_nominal_v")),
            frequency_hz=_safe_float(obj.get("frequency_hz")),
            manufacture_date=obj.get("manufacture_date") or None,
            extra_fields=dict(obj.get("extra_fields") or {}),
            extraction_method="llm",
            raw_ocr_chars=len(raw),
        )
        score = 0.0
        for v in (fields.vendor, fields.model, fields.serial,
                  fields.rated_capacity_value, fields.voltage_nominal_v):
            if v is not None and v != "":
                score += 0.2
        fields.extraction_confidence = min(1.0, score)
        return fields


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ─── Asset matcher (difflib stdlib, no new deps) ───────────────────────
def _similarity(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


@dataclass
class MatchCandidate:
    asset_id: str
    score: float
    match_reasons: list[str]
    asset_summary: dict[str, Any]


def match_assets(
    fields: NameplateFields,
    assets: list[Asset],
    top_k: int = 3,
) -> list[MatchCandidate]:
    """Score candidates by combined vendor/model/serial/capacity similarity.

    Heuristic:
      serial exact match     -> +0.50
      vendor canonical match -> +0.20
      model fuzzy >= 0.6     -> +0.20 * model_ratio
      capacity within 5%     -> +0.10
      voltage within 5%      -> +0.05
    Score capped at 1.0.
    """
    candidates: list[MatchCandidate] = []
    for a in assets:
        score = 0.0
        reasons: list[str] = []
        # Serial check (asset.metadata_json.serial if present)
        a_serial = (a.metadata_json or {}).get("serial")
        if fields.serial and a_serial and fields.serial.upper() == str(a_serial).upper():
            score += 0.50
            reasons.append("serial_exact")
        # Vendor
        if fields.vendor and a.vendor:
            v_ratio = _similarity(fields.vendor, a.vendor)
            if v_ratio >= 0.85:
                score += 0.20
                reasons.append(f"vendor_match({v_ratio:.2f})")
        # Model
        if fields.model and a.model:
            m_ratio = _similarity(fields.model, a.model)
            if m_ratio >= 0.60:
                score += 0.20 * m_ratio
                reasons.append(f"model_fuzzy({m_ratio:.2f})")
        # Capacity (if same unit)
        if (fields.rated_capacity_value is not None
                and a.rated_capacity_kw is not None
                and fields.rated_capacity_unit in ("kW", "kVA")):
            ratio = (
                fields.rated_capacity_value / a.rated_capacity_kw
                if a.rated_capacity_kw > 0 else 0.0
            )
            if 0.95 <= ratio <= 1.05:
                score += 0.10
                reasons.append("capacity_match")
        # Voltage (asset metadata_json.voltage_nominal_v)
        a_v = (a.metadata_json or {}).get("voltage_nominal_v") or (a.metadata_json or {}).get("voltage_v")
        if fields.voltage_nominal_v and a_v:
            try:
                a_v_f = float(a_v)
                if 0.95 <= fields.voltage_nominal_v / a_v_f <= 1.05:
                    score += 0.05
                    reasons.append("voltage_match")
            except (TypeError, ValueError):
                pass

        if score > 0:
            candidates.append(MatchCandidate(
                asset_id=a.asset_id,
                score=min(1.0, score),
                match_reasons=reasons,
                asset_summary={
                    "asset_id": a.asset_id,
                    "display_name": a.display_name,
                    "asset_type": a.asset_type,
                    "vendor": a.vendor,
                    "model": a.model,
                    "rated_capacity_kw": a.rated_capacity_kw,
                },
            ))
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:top_k]


# ─── Suggested action policy ───────────────────────────────────────────
def suggest_action(top: list[MatchCandidate]) -> dict[str, Any]:
    """Operator guidance: link existing or seed new asset."""
    if not top:
        return {
            "action": "seed_new_asset",
            "rationale": "No assets in registry matched the nameplate fields.",
        }
    best = top[0]
    if best.score >= 0.80:
        return {
            "action": "link_to_existing",
            "asset_id": best.asset_id,
            "confidence": best.score,
            "rationale": f"Near-exact match ({best.score:.2f}) via {', '.join(best.match_reasons)}",
        }
    if best.score >= 0.60:
        return {
            "action": "operator_confirm",
            "asset_id": best.asset_id,
            "confidence": best.score,
            "rationale": f"Plausible match ({best.score:.2f}); CET should verify before linking.",
        }
    return {
        "action": "seed_new_asset",
        "rationale": f"Best match score {best.score:.2f} below threshold; treat as new asset.",
    }


# ─── Processor (orchestrator) ──────────────────────────────────────────
class NameplateProcessor:
    def __init__(
        self,
        cmms_repo: PostgresCMMSRepository,
        ocr_engine: OCREngine | None = None,
        llm_fallback: LLMNameplateFallback | None = None,
    ):
        self.cmms_repo = cmms_repo
        self.ocr_engine = ocr_engine
        # If llm_fallback explicitly None, regex-only mode
        self.llm_fallback = llm_fallback

    async def process(
        self,
        ocr_text: str | None = None,
        image_bytes: bytes | None = None,
        asset_type_hint: str | None = None,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()

        # 1. Resolve OCR text
        if ocr_text is None and image_bytes is None:
            raise ValueError("either ocr_text or image_bytes is required")
        if image_bytes is not None:
            if self.ocr_engine is None:
                raise NotImplementedError(
                    "image mode unavailable: no OCREngine configured. "
                    "Use text mode (ocr_text) or install easyocr "
                    "(Sprint 7.1d-vision)."
                )
            ocr_text = self.ocr_engine.extract_text(image_bytes)
        if not ocr_text or len(ocr_text.strip()) < 5:
            raise ValueError("OCR text too short to extract nameplate fields")

        # 2. Regex extraction (fast path)
        fields = regex_extract(ocr_text)
        used_method = "regex"

        # 3. LLM fallback if regex confidence < 0.4 AND fallback configured
        if fields.extraction_confidence < 0.4 and self.llm_fallback is not None:
            try:
                llm_fields = await self.llm_fallback.extract(ocr_text)
                if llm_fields.extraction_confidence > fields.extraction_confidence:
                    fields = llm_fields
                    used_method = "llm"
                else:
                    used_method = "hybrid"
            except Exception as e:
                log.warning("[nameplate_ocr] LLM fallback failed: %s", e)
                used_method = "regex_only_llm_failed"
        fields.extraction_method = used_method

        # 4. Asset matching
        try:
            candidates_pool = await self.cmms_repo.list_assets_async(
                asset_type=asset_type_hint, limit=2000,
            )
        except CMMSRepositoryError as e:
            log.warning("[nameplate_ocr] asset list failed: %s", e)
            candidates_pool = []
        top = match_assets(fields, candidates_pool, top_k=3)
        action = suggest_action(top)

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "extracted_fields": fields.to_dict(),
            "candidates": [
                {
                    "asset_id": c.asset_id,
                    "score": round(c.score, 3),
                    "match_reasons": c.match_reasons,
                    "asset_summary": c.asset_summary,
                }
                for c in top
            ],
            "suggested_action": action,
            "raw_ocr_chars": len(ocr_text),
            "elapsed_ms": elapsed_ms,
        }


# ─── Singleton ─────────────────────────────────────────────────────────
_processor: NameplateProcessor | None = None


def get_nameplate_processor(
    cmms_repo: PostgresCMMSRepository | None = None,
    ocr_engine: OCREngine | None = None,
    llm_fallback: LLMNameplateFallback | None = None,
) -> NameplateProcessor:
    global _processor
    if _processor is None:
        if cmms_repo is None:
            raise RuntimeError(
                "NameplateProcessor not initialized; first call must pass cmms_repo"
            )
        _processor = NameplateProcessor(
            cmms_repo=cmms_repo, ocr_engine=ocr_engine, llm_fallback=llm_fallback,
        )
        log.info("[nameplate_ocr] NameplateProcessor initialized (ocr=%s, llm_fb=%s)",
                 type(ocr_engine).__name__ if ocr_engine else "none",
                 type(llm_fallback).__name__ if llm_fallback else "none")
    return _processor


def reset_nameplate_processor() -> None:
    global _processor
    _processor = None
