"""
backend/tech_assist/voice_closure.py
=====================================
Sprint 7.1c — Voice / dictation-driven WO closure.

Pipeline (text-mode MVP; audio mode pluggable for V2):

    technician text or audio
            |
            v   Transcriber (V2: faster-whisper / OpenAI Whisper)
    raw transcript str
            |
            v   ClosureNormalizer  (gemma-4-e2b-it / Claude)
    structured JSON: {
        professional_report: markdown,
        primary_action: one-line summary,
        parts_used: [str],
        time_spent_min: int | null,
        safety_events: [str],
        follow_ups_recommended: [
            { summary, asset_id, severity, suggested_work_class }
        ]
    }
            |
            v
    ClosureProcessor:
       - work_orders.result_json    <- structured JSON
       - work_orders.status         <- 'completed' (with CET signature)
       - work_orders                <- INSERT one row per follow-up
                                       (trigger_source='voice_dictation',
                                        status='pending_approval' per ADR-006)

Design choices:

  * Pluggable Transcriber interface (StubTranscriber for tests today,
    WhisperTranscriber when faster-whisper installs in Sprint 7.1c-vox).
  * LLM produces JSON. Defensive parsing: any JSON malformation falls
    back to plain markdown without follow-up auto-create.
  * Follow-up WOs land in pending_approval per ADR-006. Operator
    explicitly approves them in the Maintenance view.
  * Original WO is NOT auto-completed unless caller passes
    complete_wo=true. Stricter default: dictation only updates
    result_json; explicit transition is a separate action.
  * No audio storage in MVP; audio_bytes are transcribed and discarded.
    V2 may persist for forensics.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import httpx

from backend.cmms_models import WorkOrder
from backend.cmms_repository import (
    AssetNotFoundError,
    CMMSRepositoryError,
    PostgresCMMSRepository,
    WorkOrderNotFoundError,
)

log = logging.getLogger(__name__)


# ─── LLM dispatch config (mirrors troubleshoot.py) ────────────────────
LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"
LM_STUDIO_MODEL = "gemma-4-e2b-it"
LM_STUDIO_TIMEOUT_S = 12.0


# ─── Transcriber interface ─────────────────────────────────────────────
class Transcriber(ABC):
    """Pluggable audio -> text. Default to None in MVP (text-only mode)."""

    @abstractmethod
    def transcribe(self, audio_bytes: bytes, language: str = "en") -> str:
        ...


class StubTranscriber(Transcriber):
    """Test transcriber: returns pre-supplied text regardless of audio."""

    def __init__(self, output: str):
        self._output = output

    def transcribe(self, _audio_bytes: bytes, language: str = "en") -> str:
        return self._output


# Future: backend/tech_assist/voice_closure_whisper.py would add:
#   class WhisperTranscriber(Transcriber):
#       def __init__(self, model_size='small', device='cpu'): ...
#       def transcribe(self, audio_bytes, language='en'): ...
# Wired by env var DC_EPMS_TRANSCRIBER=whisper|stub|none


# ─── LLM normalization ─────────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are a Tier IV data center field-report editor. The technician just
finished a maintenance work order and dictated informal notes. Your
job is to produce a STRUCTURED JSON object normalizing those notes
into a professional CET report suitable for the procedures table and
audit trail.

Output ONLY valid JSON, no preamble, no markdown fences. Schema:

{
  "professional_report": "<markdown 2-5 paragraphs, formal tone, past
                          tense, cite parts replaced and torque values
                          if dictated>",
  "primary_action": "<one sentence summary, e.g. 'Replaced bearing on
                     fan_coil_4 motor and verified vibration baseline'>",
  "parts_used": ["<part number or descriptor>", ...],
  "time_spent_min": <integer minutes or null if not mentioned>,
  "safety_events": ["<event>", ...] // empty array if none mentioned
                                    // (e.g. arc flash, refrigerant
                                    //  release, near-miss),
  "follow_ups_recommended": [
    {
      "summary": "<one sentence>",
      "asset_id": "<canonical asset id if mentioned, else null>",
      "severity": "info" | "warn" | "critical",
      "suggested_work_class": "PM" | "CM" | "EM"
    },
    ...
  ]
}

Hard rules:
- Output VALID JSON ONLY. No markdown code fences.
- Detect mentions of degradation that the technician did NOT fully
  fix (e.g. "noticed wear but left as is", "should monitor", "may
  need replacement next quarter") and emit them as follow_ups_
  recommended.
- "severity" mapping: info=minor wear, warn=visible degradation,
  critical=safety hazard or imminent failure.
- "suggested_work_class": PM if scheduled monitoring is enough, CM if
  the asset is degrading and needs corrective work, EM if imminent.
- If the technician mentions a safety event (arc flash, refrigerant
  release, fall, near-miss), include it in safety_events. NEVER
  silently drop safety events.
"""

USER_PROMPT_TEMPLATE = """\
WORK ORDER CONTEXT:
  work_order_id: {wo_id}
  asset_id:      {asset_id}
  work_class:    {work_class}
  procedure:     {procedure}
  cet_id:        {cet_id}

TECHNICIAN DICTATED NOTES (verbatim):
{notes}

Produce the JSON per the system instructions.
"""


class ClosureNormalizer:
    """LLM-driven normalization of free-form notes -> structured JSON."""

    def __init__(
        self,
        lm_studio_url: str = LM_STUDIO_URL,
        lm_studio_model: str = LM_STUDIO_MODEL,
        timeout_s: float = LM_STUDIO_TIMEOUT_S,
    ) -> None:
        self.lm_studio_url = lm_studio_url
        self.lm_studio_model = lm_studio_model
        self.timeout_s = timeout_s

    async def normalize(
        self,
        notes: str,
        wo_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Returns structured dict matching the system prompt schema.

        Defensive: if LLM returns malformed JSON, falls back to a
        minimal struct preserving the raw notes as professional_report
        WITHOUT follow_ups (so operators are not surprised by auto-
        generated WOs from invalid output).
        """
        prompt = USER_PROMPT_TEMPLATE.format(
            wo_id=wo_context.get("work_order_id", "(unknown)"),
            asset_id=wo_context.get("asset_id", "(unknown)"),
            work_class=wo_context.get("work_class", "(unknown)"),
            procedure=wo_context.get("linked_mop_id") or "(no MOP)",
            cet_id=wo_context.get("cet_id", "(unspecified)"),
            notes=notes.strip(),
        )

        payload = {
            "model": self.lm_studio_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 800,
        }

        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            resp = await client.post(self.lm_studio_url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"LM Studio response malformed: {e}") from e

        return self._parse_or_fallback(text, notes)

    @staticmethod
    def _parse_or_fallback(text: str, original_notes: str) -> dict[str, Any]:
        """Extract JSON from LLM response. Defensive against fences,
        trailing prose, partial output."""
        # Strip markdown fences if model added them despite instructions
        text = re.sub(r"^```(?:json)?\s*", "", text.strip())
        text = re.sub(r"\s*```$", "", text)
        # Try direct parse
        try:
            obj = json.loads(text)
            if not isinstance(obj, dict):
                raise ValueError("not a dict")
            return ClosureNormalizer._coerce_schema(obj)
        except (json.JSONDecodeError, ValueError):
            pass
        # Try extracting first {...} block via greedy match
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(0))
                if isinstance(obj, dict):
                    return ClosureNormalizer._coerce_schema(obj)
            except json.JSONDecodeError:
                pass
        # Fallback: synthesize a minimal report from raw notes
        log.warning("[voice_closure] LLM JSON malformed; using fallback")
        return {
            "professional_report": (
                "**Closure notes (unnormalized — LLM JSON parse failed):**\n\n"
                + original_notes.strip()
            ),
            "primary_action": original_notes.strip()[:200],
            "parts_used": [],
            "time_spent_min": None,
            "safety_events": [],
            "follow_ups_recommended": [],
            "_normalization_status": "fallback_unparsed",
        }

    @staticmethod
    def _coerce_schema(obj: dict[str, Any]) -> dict[str, Any]:
        """Normalize keys + types to match expected schema."""
        out = {
            "professional_report": str(obj.get("professional_report", "")).strip(),
            "primary_action":      str(obj.get("primary_action", "")).strip(),
            "parts_used":          list(obj.get("parts_used") or []),
            "time_spent_min":      obj.get("time_spent_min"),
            "safety_events":       list(obj.get("safety_events") or []),
            "follow_ups_recommended": [],
            "_normalization_status": "success",
        }
        for f in obj.get("follow_ups_recommended") or []:
            if not isinstance(f, dict):
                continue
            out["follow_ups_recommended"].append({
                "summary":      str(f.get("summary", "")).strip(),
                "asset_id":     f.get("asset_id"),
                "severity":     f.get("severity") if f.get("severity") in ("info", "warn", "critical") else "info",
                "suggested_work_class": f.get("suggested_work_class") if f.get("suggested_work_class") in ("PM", "CM", "EM") else "PM",
            })
        # Coerce time_spent_min to int or None
        try:
            if out["time_spent_min"] is not None:
                out["time_spent_min"] = int(out["time_spent_min"])
        except (TypeError, ValueError):
            out["time_spent_min"] = None
        return out


# ─── Closure processor (orchestrator) ──────────────────────────────────
def _wo_id() -> str:
    return f"WO-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"


class ClosureProcessor:
    """End-to-end: text/audio -> normalize -> persist closure +
    auto-draft follow-up WOs."""

    def __init__(
        self,
        cmms_repo: PostgresCMMSRepository,
        normalizer: ClosureNormalizer | None = None,
        transcriber: Transcriber | None = None,
    ) -> None:
        self.cmms_repo = cmms_repo
        self.normalizer = normalizer or ClosureNormalizer()
        self.transcriber = transcriber  # may be None in MVP text-only mode

    async def process(
        self,
        wo_id: str,
        cet_id: str,
        notes_text: str | None = None,
        audio_bytes: bytes | None = None,
        complete_wo: bool = False,
        auto_create_follow_ups: bool = True,
    ) -> dict[str, Any]:
        """Normalize closure notes + persist to WO + optional follow-ups."""
        t0 = time.perf_counter()

        if not notes_text and not audio_bytes:
            raise ValueError("either notes_text or audio_bytes is required")

        # 1. Transcribe if audio provided (V2 path)
        if audio_bytes is not None:
            if self.transcriber is None:
                raise NotImplementedError(
                    "audio mode unavailable: no transcriber configured "
                    "(install faster-whisper for V2)"
                )
            notes_text = self.transcriber.transcribe(audio_bytes)

        if not notes_text or not notes_text.strip():
            raise ValueError("empty notes after transcription")

        # 2. Fetch WO for context
        wo = await self.cmms_repo.get_work_order_async(wo_id)

        wo_context = {
            "work_order_id": wo.work_order_id,
            "asset_id": wo.asset_id,
            "work_class": wo.work_class,
            "linked_mop_id": wo.linked_mop_id,
            "cet_id": cet_id,
        }

        # 3. LLM normalize
        normalized = await self.normalizer.normalize(notes_text, wo_context)

        # 4. Update original WO
        result_json = {
            "raw_notes": notes_text.strip(),
            "normalized": normalized,
            "cet_id": cet_id,
            "dictated_at": datetime.now(timezone.utc).isoformat(),
            "complete_wo": complete_wo,
        }
        wo_updated = wo.model_copy(update={"result_json": result_json})
        await self.cmms_repo.save_work_order_async(wo_updated)

        # 5. Optional state transition
        new_status = wo.status
        if complete_wo and wo.status not in ("completed", "rejected", "cancelled"):
            updated = await self.cmms_repo.transition_status_async(
                wo_id, "completed", cet_id,
            )
            new_status = updated.status

        # 6. Auto-create follow-up WOs (pending_approval per ADR-006)
        follow_up_ids: list[str] = []
        skipped_followups: list[dict[str, Any]] = []
        if auto_create_follow_ups:
            for f in normalized.get("follow_ups_recommended", []):
                fwo_id = await self._create_follow_up(f, wo, cet_id)
                if fwo_id:
                    follow_up_ids.append(fwo_id)
                else:
                    skipped_followups.append(f)

        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        return {
            "work_order_id": wo_id,
            "status_after": new_status,
            "normalized": normalized,
            "raw_notes_chars": len(notes_text.strip()),
            "follow_ups_created": follow_up_ids,
            "follow_ups_skipped": skipped_followups,
            "elapsed_ms": elapsed_ms,
        }

    async def _create_follow_up(
        self,
        followup_spec: dict[str, Any],
        parent_wo: WorkOrder,
        cet_id: str,
    ) -> str | None:
        """Create a single follow-up WO. Returns id or None on skip."""
        target_asset_id = followup_spec.get("asset_id") or parent_wo.asset_id
        if not target_asset_id:
            return None

        # Resolve asset for criticality + linked_mop. If asset unknown,
        # skip rather than guess.
        try:
            asset = await self.cmms_repo.get_asset_async(target_asset_id)
        except AssetNotFoundError:
            log.info(
                "[voice_closure] follow-up asset %s not found; skipping",
                target_asset_id,
            )
            return None
        except CMMSRepositoryError as e:
            log.warning("[voice_closure] asset lookup failed: %s", e)
            return None

        wclass = followup_spec.get("suggested_work_class", "PM")
        # severity -> LOR mapping
        sev = followup_spec.get("severity", "info")
        likelihood, consequence = {
            "info":     (2, 2),
            "warn":     (3, 3),
            "critical": (4, 4),
        }.get(sev, (2, 2))
        lor = max(1, min(25, likelihood * consequence))

        priority = "P3"
        if lor >= 12:
            priority = "P2"
        if lor >= 20 or (asset.criticality_class == "critical" and lor >= 12):
            priority = "P1"

        proc_class = "EOP" if wclass == "EM" else ("MOP" if wclass == "CM" else "SOP")
        now = datetime.now(timezone.utc)

        new_wo = WorkOrder(
            work_order_id=_wo_id(),
            timestamp=now,
            asset_id=target_asset_id,
            asset_type_at_creation=asset.asset_type,
            work_class=wclass,
            lor=lor,
            procedure_class=proc_class,
            linked_mop_id=asset.linked_mop_id,
            linked_loto_audit_id=None,
            trigger_source="incident",  # per CHECK constraint;
                                        # voice_dictation as new value
                                        # would require migration
            predictive_metadata={
                "source": "voice_closure_followup",
                "parent_wo_id": parent_wo.work_order_id,
                "parent_cet": cet_id,
                "severity": sev,
            },
            issue_summary=followup_spec.get("summary", "(voice dictation follow-up)")[:240],
            estimated_cost_usd=0.0,
            requires_loto=False,
            requires_oem_specialist=False,
            status="pending_approval",
            priority=priority,
            telemetry_snapshot_json=None,
            mop_resolution_method="hardcoded" if asset.linked_mop_id else None,
            requested_by=f"voice_closure({cet_id})",
            draft_json={
                "lor": lor,
                "lor_breakdown": {
                    "likelihood_idx": likelihood,
                    "consequence_idx": consequence,
                    "asset_criticality": asset.criticality_class,
                    "trigger_basis": "voice_dictation_followup",
                    "severity_from_dictation": sev,
                },
                "linked_mop_id": asset.linked_mop_id,
                "procedure_class": proc_class,
                "issue_summary": followup_spec.get("summary", "")[:240],
                "auto_generated": True,
                "parent_wo_id": parent_wo.work_order_id,
            },
        )

        try:
            await self.cmms_repo.save_work_order_async(new_wo)
        except CMMSRepositoryError as e:
            log.error("[voice_closure] follow-up save failed: %s", e)
            return None

        log.info(
            "[voice_closure] follow-up WO %s created (parent=%s, severity=%s)",
            new_wo.work_order_id, parent_wo.work_order_id, sev,
        )
        return new_wo.work_order_id


# ─── Singleton ─────────────────────────────────────────────────────────
_processor: ClosureProcessor | None = None


def get_closure_processor(
    cmms_repo: PostgresCMMSRepository | None = None,
    normalizer: ClosureNormalizer | None = None,
    transcriber: Transcriber | None = None,
) -> ClosureProcessor:
    global _processor
    if _processor is None:
        if cmms_repo is None:
            raise RuntimeError(
                "ClosureProcessor not initialized; first call must pass cmms_repo"
            )
        _processor = ClosureProcessor(
            cmms_repo=cmms_repo, normalizer=normalizer, transcriber=transcriber,
        )
        log.info("[voice_closure] ClosureProcessor initialized")
    return _processor


def reset_closure_processor() -> None:
    global _processor
    _processor = None
