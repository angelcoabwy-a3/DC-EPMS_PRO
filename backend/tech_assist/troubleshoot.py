"""
backend/tech_assist/troubleshoot.py
====================================
Sprint 7.1a — Real-time troubleshooting QA (MaintainX-AI lineage).

Combines three knowledge sources to answer a technician's free-form
question:

  1. Knowledge corpus (rag_service.py, ChromaDB, 20 docs across Tier 1
     Safety / Tier 2 Vendor / Tier 3 Standards / Tier 4 a3semi MOPs)
  2. Asset failure history (cmms_repository: WOs for the asset_id in
     the configured lookback window, ranked by recency)
  3. Asset metadata (criticality, linked_mop_id, redundancy_pillar,
     telemetry channels) — feeds LOTO and PPE awareness into the
     prompt

The prompt is the one designed in the Vision Deck v1.0 appendix #3
(CLAUDE.md). LLM dispatch:
  Primary: LM Studio gemma-4-e2b-it (local, edge-first ADR-006)
  Fallback: passthrough mode returning structured retrieval context
            without LLM synthesis (when LM Studio is down or use_llm=
            False)

Architecture decisions:
  * Sync method core (gather_context) for testability; async wrapper
    for FastAPI route handler (LLM HTTP call requires async-safe).
  * Citations format inline in answer: [manual:DOC_ID p47] /
    [WO:WO-...] / [asset:ups_a]. Operators can cross-check.
  * Safety keyword detection mirrors rag_service.SAFETY_KEYWORDS so
    the response surfaces matching keywords for HMI banner rendering.
  * NO autonomous action — output is advisory; ADR-006 sandbox.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from backend.cmms_models import Asset
from backend.cmms_repository import (
    AssetNotFoundError,
    CMMSRepositoryError,
    PostgresCMMSRepository,
)
from backend.tech_assist.models import (
    HistoricalWO,
    ManualChunk,
    TroubleshootRequest,
    TroubleshootResponse,
)

log = logging.getLogger(__name__)


# ─── LLM dispatch config ───────────────────────────────────────────────
LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"
LM_STUDIO_MODEL = "gemma-4-e2b-it"
LM_STUDIO_TIMEOUT_S = 12.0   # gemma 400 tokens ~5-15s on RTX 3060

SAFETY_KEYWORDS = frozenset({
    "loto", "lockout", "tagout", "arc flash", "arc-flash", "arcflash",
    "energized", "ppe", "shock", "isolation", "epo",
    "emergency", "evacuation", "hazard", "refrigerant", "leak",
})


SYSTEM_PROMPT = """\
You are a CET (Critical Environment Technician) field assistant for a
Tier IV AI-factory data center. You speak directly to the technician
who is at the equipment. Answer in EXACTLY 3 sections, in this order:

  1. ERROR CODE / ISSUE MEANING
     One paragraph. Manufacturer-defined behaviour or standard
     interpretation. Cite manual page/doc when possible.

  2. RANKED CAUSES
     Top 2-3 likely causes ordered by historical incidence on this
     specific asset. Cite past WO IDs when matches exist.

  3. STEP-BY-STEP FIX
     Numbered actions referencing manual page/doc IDs. Mark any step
     requiring LOTO with "[REQUIRES LOTO]" and link to the relevant
     T1-SAF or T4-MOP document. Mark Cat 2+ arc flash steps with
     "[REQUIRES PPE Cat 2]".

Hard rules:
  - Never invent details not in the provided context.
  - If history conflicts with manual, FLAG IT explicitly.
  - If unsafe (arc flash > Cat 2, refrigerant leak > 0.5 kg, magnetic-
    bearing fault, EPO triggered), refuse step-by-step and respond ONLY
    with "ESCALATE TO OEM / T2-VEN-{vendor}".
  - Cite sources inline as [manual:DOC_ID] or [WO:WO-...] or [asset:id].
  - Be terse. The technician has gloves on and a multimeter ready.
"""

USER_PROMPT_TEMPLATE = """\
ASSET CONTEXT:
{asset_context}

ERROR CODE: {error_code}
QUERY:      {query}

MANUAL EXCERPTS (top {n_chunks} matches):
{manual_chunks}

FAILURE HISTORY (last {history_months} months on this asset):
{history_lines}

Answer per the system instructions. Be terse.
"""


# ═══════════════════════════════════════════════════════════════════════
#  Agent
# ═══════════════════════════════════════════════════════════════════════
class TroubleshootAgent:
    """Composable agent: context gathering + LLM synthesis split for tests."""

    def __init__(
        self,
        rag_service: Any,
        cmms_repo: PostgresCMMSRepository | None,
        lm_studio_url: str = LM_STUDIO_URL,
        lm_studio_model: str = LM_STUDIO_MODEL,
        timeout_s: float = LM_STUDIO_TIMEOUT_S,
    ) -> None:
        self.rag_service = rag_service
        self.cmms_repo = cmms_repo
        self.lm_studio_url = lm_studio_url
        self.lm_studio_model = lm_studio_model
        self.timeout_s = timeout_s

    # ── Public async entry point ──────────────────────────────────────
    async def answer(self, req: TroubleshootRequest) -> TroubleshootResponse:
        t0 = time.perf_counter()
        sources: dict[str, str] = {}

        # 1. Retrieve manual chunks via RAG
        chunks = self._gather_chunks(req, sources)
        # 2. Asset metadata + failure history
        asset, history = await self._gather_asset_context(req, sources)
        # 3. Detect safety keywords
        safety_kw = self._detect_safety_keywords(req.query)

        # 4. LLM synthesis (optional)
        llm_answer: str | None = None
        llm_status = "skipped"
        llm_model_used: str | None = None
        if req.use_llm:
            try:
                llm_answer = await self._call_lm_studio(
                    req=req,
                    chunks=chunks,
                    history=history,
                    asset=asset,
                )
                llm_status = "success"
                llm_model_used = self.lm_studio_model
                sources["lm_studio"] = "OK"
            except httpx.TimeoutException:
                llm_status = "timeout"
                sources["lm_studio"] = f"timeout after {self.timeout_s}s"
            except Exception as e:
                llm_status = "error"
                sources["lm_studio"] = f"error: {type(e).__name__}: {str(e)[:100]}"
                log.warning("LLM call failed: %s", e)

        decision_ms = int((time.perf_counter() - t0) * 1000)

        return TroubleshootResponse(
            query=req.query,
            asset_id=req.asset_id,
            error_code=req.error_code,
            chunks_retrieved=chunks,
            history_count=len(history),
            historical_wos=history,
            asset_metadata=asset.model_dump(mode="json") if asset else None,
            llm_answer=llm_answer,
            llm_synthesis_status=llm_status,
            llm_model=llm_model_used,
            decision_time_ms=decision_ms,
            safety_keywords_detected=safety_kw,
            sources_consulted=sources,
        )

    # ── Context gathering (sync, testable in isolation) ───────────────
    def _gather_chunks(
        self,
        req: TroubleshootRequest,
        sources: dict[str, str],
    ) -> list[ManualChunk]:
        if self.rag_service is None:
            sources["rag_service"] = "unavailable"
            return []
        try:
            search_text = req.query
            if req.error_code:
                search_text = f"{req.error_code} {search_text}"
            raw = self.rag_service.query(search_text, n_results=req.k_chunks)
        except Exception as e:
            sources["rag_service"] = f"error: {type(e).__name__}"
            log.warning("RAG query failed: %s", e)
            return []

        if "error" in raw:
            sources["rag_service"] = f"error: {raw['error']}"
            return []

        sources["rag_service"] = f"OK ({len(raw.get('results', []))} chunks)"
        chunks = []
        for r in raw.get("results", [])[: req.k_chunks]:
            chunks.append(ManualChunk(
                doc_id=str(r.get("doc_id", "unknown")),
                score=float(r.get("score", 0.0)),
                tier=int(r.get("tier", 4)),
                metadata=r.get("metadata", {}) or {},
                text_excerpt=str(r.get("text", ""))[:500],
            ))
        return chunks

    async def _gather_asset_context(
        self,
        req: TroubleshootRequest,
        sources: dict[str, str],
    ) -> tuple[Asset | None, list[HistoricalWO]]:
        if not req.asset_id or self.cmms_repo is None:
            sources["cmms_repo"] = "skipped (no asset_id or repo)"
            return None, []

        # Asset
        asset: Asset | None = None
        try:
            asset = await self.cmms_repo.get_asset_async(req.asset_id)
            sources["asset_metadata"] = "OK"
        except AssetNotFoundError:
            sources["asset_metadata"] = f"not found: {req.asset_id}"
            return None, []
        except CMMSRepositoryError as e:
            sources["asset_metadata"] = f"error: {e}"
            return None, []

        # WO history
        cutoff = datetime.now(timezone.utc) - timedelta(days=30 * req.history_months)
        try:
            wos = await self.cmms_repo.list_work_orders_async(
                asset_id=req.asset_id,
                limit=200,
            )
        except CMMSRepositoryError as e:
            sources["wo_history"] = f"error: {e}"
            return asset, []

        recent_wos = [w for w in wos if w.timestamp >= cutoff]
        sources["wo_history"] = f"OK ({len(recent_wos)} of {len(wos)} within window)"

        history = []
        for w in recent_wos[:25]:  # cap for prompt size
            closure = None
            if w.result_json and isinstance(w.result_json, dict):
                closure = w.result_json.get("summary") or w.result_json.get("notes")
            history.append(HistoricalWO(
                work_order_id=w.work_order_id,
                timestamp=w.timestamp,
                work_class=w.work_class,
                status=w.status,
                priority=w.priority,
                issue_summary=w.issue_summary,
                closure_summary=closure,
            ))
        return asset, history

    @staticmethod
    def _detect_safety_keywords(query: str) -> list[str]:
        ql = query.lower()
        return sorted([k for k in SAFETY_KEYWORDS if k in ql])

    # ── LLM dispatch ──────────────────────────────────────────────────
    async def _call_lm_studio(
        self,
        req: TroubleshootRequest,
        chunks: list[ManualChunk],
        history: list[HistoricalWO],
        asset: Asset | None,
    ) -> str:
        """Build prompt + POST to LM Studio. Returns markdown text."""
        prompt = self._build_user_prompt(req, chunks, history, asset)

        payload = {
            "model": self.lm_studio_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            "temperature": 0.15,
            "max_tokens": 600,
        }

        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            resp = await client.post(self.lm_studio_url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"LM Studio response malformed: {e}") from e

    @staticmethod
    def _build_user_prompt(
        req: TroubleshootRequest,
        chunks: list[ManualChunk],
        history: list[HistoricalWO],
        asset: Asset | None,
    ) -> str:
        if asset:
            asset_ctx = (
                f"  asset_id:           {asset.asset_id}\n"
                f"  display:            {asset.display_name}\n"
                f"  type:               {asset.asset_type}\n"
                f"  vendor / model:     {asset.vendor or '-'} / {asset.model or '-'}\n"
                f"  location:           {asset.location_path or '-'}\n"
                f"  redundancy_pillar:  {asset.redundancy_pillar or '-'}\n"
                f"  criticality:        {asset.criticality_class}\n"
                f"  linked_mop_id:      {asset.linked_mop_id or '-'}\n"
            )
        else:
            asset_ctx = "  (no asset_id supplied; manual-only retrieval)"

        if chunks:
            chunk_lines = []
            for c in chunks:
                tier_label = {1: "Safety", 2: "Vendor", 3: "Standards", 4: "MOP"}.get(c.tier, "?")
                chunk_lines.append(
                    f"  [manual:{c.doc_id}] (Tier {c.tier} {tier_label}, score={c.score:.2f})\n"
                    f"    {c.text_excerpt[:300]}"
                )
            chunks_block = "\n".join(chunk_lines)
        else:
            chunks_block = "  (no manual chunks retrieved)"

        if history:
            hist_lines = []
            for h in history[:10]:
                date = h.timestamp.strftime("%Y-%m-%d")
                closure = f" -> {h.closure_summary[:80]}" if h.closure_summary else ""
                hist_lines.append(
                    f"  [WO:{h.work_order_id}] ({h.work_class}, {date}, {h.status}, {h.priority})\n"
                    f"    {h.issue_summary[:160]}{closure}"
                )
            history_block = "\n".join(hist_lines)
        else:
            history_block = "  (no relevant history)"

        return USER_PROMPT_TEMPLATE.format(
            asset_context=asset_ctx,
            error_code=req.error_code or "(none)",
            query=req.query,
            n_chunks=len(chunks),
            manual_chunks=chunks_block,
            history_months=req.history_months,
            history_lines=history_block,
        )


# ─── Module-level singleton ────────────────────────────────────────────
_agent: TroubleshootAgent | None = None


def get_troubleshoot_agent(
    rag_service: Any | None = None,
    cmms_repo: PostgresCMMSRepository | None = None,
) -> TroubleshootAgent:
    global _agent
    if _agent is None:
        if rag_service is None and cmms_repo is None:
            raise RuntimeError(
                "TroubleshootAgent not initialized; "
                "first call must pass rag_service and/or cmms_repo"
            )
        _agent = TroubleshootAgent(rag_service=rag_service, cmms_repo=cmms_repo)
        log.info("[tech_assist] TroubleshootAgent initialized")
    return _agent


def reset_troubleshoot_agent() -> None:
    global _agent
    _agent = None
