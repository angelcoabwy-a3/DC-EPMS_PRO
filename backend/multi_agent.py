"""
backend/multi_agent.py
======================
Sprint 10.1 — Multi-Agent façade with Safety Officer veto.

Four specialized agents collaborate on operator queries about a target
asset / procedure / work order. Each agent evaluates from a single
perspective and produces a verdict + evidence trail. The orchestrator
runs them in parallel via ``asyncio.gather`` and computes consensus.

Agents
------

  Architect           Topology + 2N redundancy impact
                      reads: site_model, graphrag (loto_with_knowledge)
                      verdict basis: would the action drop redundancy
                      below 2N or N+1? Path-aware (Path A vs Path B).

  Safety Officer      LOTO/PPE compliance + audit-trail integrity
                      reads: site_model component metadata, work_orders
                      veto power: HARD_STOP outranks all other agents
                      (CSA Z462 / NFPA 70E §130 / NEC 460.6).

  Diagnostician       Recurrence + corpus-grounded historical context
                      reads: cmms_repository (WO history) + rag_service
                      (4-tier corpus). Flags accelerated wear patterns.
                      T3.3: also synthesizes an advisory diagnostic
                      narrative via the local Gemma model, grounded in
                      live Hermes Kalman Z-scores. The narrative is
                      advisory ONLY -- the verdict stays deterministic.

  Analyst             LOR-weighted KPIs + CapEx-vs-OpEx framing
                      reads: cmms_repository (asset + open WOs)
                      heuristic cost model per asset_type.

Consensus rule (deterministic)
------------------------------
  1. If Safety Officer == 'hard_stop'  -> consensus = 'hard_stop' (VETO).
  2. Else if any agent == 'hard_stop'  -> consensus = 'hard_stop'.
  3. Else if any agent == 'caution'    -> consensus = 'caution'.
  4. Else                              -> consensus = 'approve'.

Per ADR-006 Deterministic Sandbox: every agent VERDICT is computed by
pure-Python deterministic logic -- no LLM in the critical decision path.
The Diagnostician (T3.3) may attach a Gemma-generated narrative, but
that text is advisory only and never alters the verdict or the
consensus rule. The output is advisory; the operator remains the
approver. The orchestrator never mutates state.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

log = logging.getLogger(__name__)


# ─── Verdict types ─────────────────────────────────────────────────────
VERDICT_APPROVE = "approve"
VERDICT_CAUTION = "caution"
VERDICT_HARD_STOP = "hard_stop"
VERDICT_DEGRADED = "degraded"   # service unavailable, agent could not evaluate

VALID_VERDICTS = {VERDICT_APPROVE, VERDICT_CAUTION, VERDICT_HARD_STOP, VERDICT_DEGRADED}


# ─── Data classes ──────────────────────────────────────────────────────
@dataclass(frozen=True)
class ConsultContext:
    """Inputs to a multi-agent consultation."""
    query: str
    asset_id: str | None = None
    procedure_id: str | None = None
    work_order_id: str | None = None
    cet_id: str | None = None  # who is asking, recorded in audit


@dataclass
class AgentVerdict:
    """A single agent's findings."""
    agent_name: str
    verdict: str           # one of VALID_VERDICTS
    summary: str           # one-line headline
    reasoning: list[str]   # bullet points the operator can read
    evidence_refs: list[str]   # provenance markers (e.g. "site_model:ups_a")
    decision_time_ms: int
    # T3.3: optional advisory LLM narrative (Diagnostician only). Empty
    # for deterministic-only agents. NEVER an input to the verdict.
    llm_narrative: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConsensusResult:
    """Aggregate verdict over the four agents."""
    consensus: str
    safety_officer_veto: bool
    agents: list[AgentVerdict] = field(default_factory=list)
    decision_time_ms: int = 0
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "consensus": self.consensus,
            "safety_officer_veto": self.safety_officer_veto,
            "agents": [a.to_dict() for a in self.agents],
            "decision_time_ms": self.decision_time_ms,
            "rationale": self.rationale,
        }


# ─── Helpers ───────────────────────────────────────────────────────────
def _ms_since(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _verdict_rank(v: str) -> int:
    """Higher = more conservative. Used for non-veto agents only."""
    return {
        VERDICT_HARD_STOP: 3,
        VERDICT_CAUTION: 2,
        VERDICT_DEGRADED: 1,
        VERDICT_APPROVE: 0,
    }.get(v, 0)


# ─── T3.3+ shared live-Gemma advisory-narrative helpers ────────────────
# Used by the Diagnostician (T3.3) and the Safety Officer (T3.3b). Per
# ADR-006 the narrative is advisory ONLY: every agent's verdict is
# computed deterministically before either helper runs.
_KALMAN_TOP_N = 4


async def _collect_kalman_lines(
    telemetry_provider: Any | None,
    asset_id: str | None,
    top_n: int = _KALMAN_TOP_N,
) -> list[str]:
    """Render asset-relevant + site-anomalous live Kalman channels as
    human-readable Z-score lines for a Gemma grounding prompt.

    Best-effort: any provider failure / empty payload yields []. The
    injected telemetry_provider may be sync or async.
    """
    if telemetry_provider is None:
        return []
    try:
        payload = telemetry_provider()
        if inspect.isawaitable(payload):
            payload = await payload
    except Exception as e:
        log.debug("[multi_agent] telemetry provider failed: %s", e)
        return []
    if not isinstance(payload, dict) or not payload:
        return []

    def _maxz(ch: str) -> float:
        try:
            return float(payload.get(ch, {}).get("max_z", 0.0) or 0.0)
        except (TypeError, ValueError, AttributeError):
            return 0.0

    aid = (asset_id or "").lower()
    asset_chs = sorted(
        (c for c in payload if aid and aid in c.lower()),
        key=_maxz, reverse=True,
    )[:top_n]
    lines: list[str] = []
    for ch in asset_chs:
        f = payload[ch]
        flag = " ANOMALOUS" if f.get("is_anomalous") else ""
        mean_z = float(f.get("mean_z", 0.0) or 0.0)
        lines.append(
            f"[asset] {ch}: max_z={_maxz(ch):.2f} mean_z={mean_z:.2f}{flag}"
        )
    for ch in sorted(payload, key=_maxz, reverse=True)[:top_n]:
        if ch in asset_chs:
            continue
        f = payload[ch]
        flag = " ANOMALOUS" if f.get("is_anomalous") else ""
        lines.append(f"[site]  {ch}: max_z={_maxz(ch):.2f}{flag}")
    return lines


async def _gemma_complete(
    llm_client: Any | None, prompt: str, max_tokens: int = 240,
) -> str:
    """Call the local Gemma model with a pre-built prompt.

    Best-effort: returns "" on a missing / !complete_gemma client, any
    exception, or the LM Studio '[Gemma error ...]' sentinel string.
    """
    if llm_client is None or not hasattr(llm_client, "complete_gemma"):
        return ""
    try:
        text = (await llm_client.complete_gemma(prompt, max_tokens=max_tokens)) or ""
    except Exception as e:
        log.debug("[multi_agent] Gemma synthesis failed: %s", e)
        return ""
    text = text.strip()
    if not text or text.startswith(("[Gemma error", "[Gemma stream error")):
        return ""
    return text


# ─── Agent: Architect ──────────────────────────────────────────────────
class ArchitectAgent:
    """Topology + redundancy impact perspective.

    Verdict basis:
      - HARD_STOP  if action would leave site with NO redundant path on any
                   critical chain (would drop 2N to 1N AND the 1N is degraded)
      - CAUTION    if action would drop 2N to 1N temporarily on a critical
                   subsystem
      - APPROVE    otherwise
      - DEGRADED   if neither site_model nor cmms_repo is available

    Pulls redundancy_pillar / criticality_class / path from the CMMS
    asset row (authoritative for those fields) and falls back to
    site_model.metadata for testing scenarios where CMMS is mocked.
    """

    name = "Architect"

    def __init__(self, site_model: Any | None, graphrag: Any | None,
                 cmms_repo: Any | None = None):
        self._site = site_model
        self._graphrag = graphrag
        self._cmms_repo = cmms_repo

    async def evaluate(self, ctx: ConsultContext) -> AgentVerdict:
        t0 = time.perf_counter()
        evidence: list[str] = []
        reasoning: list[str] = []

        if self._site is None and self._cmms_repo is None:
            return AgentVerdict(
                agent_name=self.name, verdict=VERDICT_DEGRADED,
                summary="topology data unavailable — no site_model or CMMS",
                reasoning=["neither site_model nor cmms_repo injected; "
                           "Architect cannot reason about redundancy."],
                evidence_refs=[],
                decision_time_ms=_ms_since(t0),
            )

        if not ctx.asset_id:
            return AgentVerdict(
                agent_name=self.name, verdict=VERDICT_APPROVE,
                summary="No asset specified — no topology impact",
                reasoning=["query does not reference a specific asset; "
                           "Architect has no redundancy to evaluate."],
                evidence_refs=[],
                decision_time_ms=_ms_since(t0),
            )

        # Read CMMS asset row first — that's authoritative for
        # redundancy_pillar / criticality_class / path (Path A/B).
        pillar = "unknown"
        path = "unknown"
        criticality = "medium"
        comp_type = "unknown"
        if self._cmms_repo is not None:
            try:
                a = await self._cmms_repo.get_asset_async(ctx.asset_id)
                evidence.append(f"cmms:asset:{ctx.asset_id}")
                pillar = getattr(a, "redundancy_pillar", None) or pillar
                path = getattr(a, "path", None) or path
                criticality = getattr(a, "criticality_class", None) or criticality
                comp_type = getattr(a, "asset_type", None) or comp_type
            except Exception as e:
                reasoning.append(f"CMMS asset lookup failed: {e}")

        # site_model adds geographic location (location_path) and
        # validates the canonical_id exists in the YAML inventory.
        if self._site is not None:
            try:
                comp = self._site.get_component(ctx.asset_id)
                evidence.append(f"site_model:{ctx.asset_id}")
                if comp_type == "unknown":
                    comp_type = getattr(comp, "type", "unknown")
                # Fallback only if CMMS didn't have these fields (unit-test path)
                meta = getattr(comp, "metadata", {}) or {}
                if pillar == "unknown":
                    pillar = meta.get("redundancy_pillar") or meta.get("pillar") or pillar
                if path == "unknown":
                    path = meta.get("path") or meta.get("location_path") or path
                if criticality == "medium" and "criticality_class" in meta:
                    criticality = meta["criticality_class"]
                elif criticality == "medium" and "criticality" in meta:
                    criticality = meta["criticality"]
            except Exception as e:
                reasoning.append(f"site_model lookup failed: {e}")
        reasoning.append(
            f"Asset {ctx.asset_id} ({comp_type}) is on path={path}, "
            f"redundancy pillar={pillar}, criticality={criticality}."
        )

        verdict = VERDICT_APPROVE
        if pillar in ("2N",):
            reasoning.append(
                "Taking this asset offline drops 2N -> 1N for the duration "
                "of the LOTO. Acceptable if the redundant path is healthy."
            )
            if criticality == "critical":
                verdict = VERDICT_CAUTION
                reasoning.append(
                    "Asset is critical-class; recommend confirming the "
                    "B-side equivalent is healthy before locking out."
                )
        elif pillar in ("N+1",):
            reasoning.append(
                "Asset is on N+1 redundancy. Single offline event "
                "leaves site at N — no further fault tolerance."
            )
            if criticality == "critical":
                verdict = VERDICT_CAUTION
                reasoning.append(
                    "Critical N+1 component; schedule during off-peak "
                    "and verify no concurrent maintenance on siblings."
                )
        elif pillar in ("N", "single"):
            reasoning.append(
                f"Asset is on '{pillar}' redundancy — taking it offline "
                f"creates a single point of failure for downstream loads."
            )
            verdict = VERDICT_HARD_STOP if criticality == "critical" else VERDICT_CAUTION

        # Optional GraphRAG enrichment if we have it AND a procedure
        if self._graphrag is not None and ctx.procedure_id:
            try:
                topo = self._graphrag.loto_with_knowledge(ctx.asset_id)
                if topo:
                    reasoning.append(
                        f"GraphRAG impact set: {len(topo.get('impact_set', []))} "
                        f"downstream component(s) affected."
                    )
                    evidence.append(f"graphrag:loto_with_knowledge:{ctx.asset_id}")
            except Exception as e:
                reasoning.append(f"GraphRAG topology lookup failed: {e}")

        summary = (
            f"Path {path} {pillar} ({criticality}) — "
            f"{verdict.replace('_', ' ')}"
        )
        return AgentVerdict(
            agent_name=self.name, verdict=verdict,
            summary=summary, reasoning=reasoning,
            evidence_refs=evidence, decision_time_ms=_ms_since(t0),
        )


# ─── Agent: Safety Officer ─────────────────────────────────────────────
class SafetyOfficerAgent:
    """LOTO + PPE compliance perspective with VETO power.

    Conservative by design: any uncertainty about LOTO scope produces
    CAUTION; missing MOP linkage on a requires_loto WO produces HARD_STOP.

    Verdict basis:
      - HARD_STOP  if (a) WO requires_loto AND no linked_mop_id
                      (b) asset metadata indicates DC link / >600V AND
                          procedure not specified
      - CAUTION    if requires_loto AND linked_mop_id but no witness_gate
                   classification verifiable
      - APPROVE    otherwise
    """

    name = "Safety Officer"

    def __init__(
        self,
        site_model: Any | None,
        cmms_repo: Any | None,
        llm_client: Any | None = None,
        telemetry_provider: Any | None = None,
    ):
        self._site = site_model
        self._cmms_repo = cmms_repo
        # T3.3b: optional live-Gemma advisory layer. The verdict stays
        # deterministic (see _finalize). Both default None -> existing
        # call sites + unit tests unaffected.
        self._llm_client = llm_client
        self._telemetry_provider = telemetry_provider

    async def evaluate(self, ctx: ConsultContext) -> AgentVerdict:
        t0 = time.perf_counter()
        evidence: list[str] = []
        reasoning: list[str] = []

        # Path 1: WO-driven evaluation
        if ctx.work_order_id and self._cmms_repo is not None:
            try:
                wo = await self._cmms_repo.get_work_order_async(ctx.work_order_id)
                evidence.append(f"cmms:work_order:{ctx.work_order_id}")
                requires_loto = bool(getattr(wo, "requires_loto", False))
                linked_mop = getattr(wo, "linked_mop_id", None)
                priority = getattr(wo, "priority", "P3")
                reasoning.append(
                    f"WO {ctx.work_order_id} priority={priority}, "
                    f"requires_loto={requires_loto}, "
                    f"linked_mop_id={linked_mop or 'NONE'}."
                )
                if requires_loto and not linked_mop:
                    return await self._finalize(
                        ctx, t0, VERDICT_HARD_STOP,
                        "LOTO required but no MOP linked — VETO",
                        [*reasoning, "ADR-006 Deterministic Sandbox: requires_loto=true " "without a linked_mop_id is non-compliant; the WO " "cannot be approved until a MOP is attached and " "validated by the LOTO Auditor.", "Standard reference: CSA Z462-24 §4.2 + NFPA 70E §130."],
                        evidence,
                    )
            except Exception as e:
                reasoning.append(f"WO lookup failed: {e}")

        # Path 2: Asset-driven evaluation
        if ctx.asset_id and self._site is not None:
            try:
                comp = self._site.get_component(ctx.asset_id)
                evidence.append(f"site_model:{ctx.asset_id}")
                meta = comp.metadata or {}
                voltage = meta.get("voltage_v") or meta.get("voltage_nominal") or 0
                has_dc_link = bool(meta.get("has_dc_link") or meta.get("dc_link"))
                if has_dc_link or (isinstance(voltage, int | float) and voltage >= 600):
                    reasoning.append(
                        f"Asset has DC link or voltage >= 600V "
                        f"(voltage_v={voltage}, has_dc_link={has_dc_link}). "
                        f"NEC 460.6 capacitor discharge mandatory."
                    )
                    if not ctx.procedure_id:
                        return await self._finalize(
                            ctx, t0, VERDICT_HARD_STOP,
                            "Capacitor-class asset with no procedure — VETO",
                            [*reasoning, "No procedure_id supplied. CSA Z462 requires " "an approved MOP referencing capacitor discharge " "before any work on this class of asset."],
                            evidence,
                        )
                if voltage:
                    reasoning.append(
                        f"PPE category derived from {voltage} V nominal "
                        f"per NFPA 70E §130 voltage-distance matrix."
                    )
            except Exception as e:
                reasoning.append(f"Asset metadata lookup failed: {e}")

        # If we made it here, no veto fired. Default conservative.
        if ctx.work_order_id or ctx.procedure_id or ctx.asset_id:
            return await self._finalize(
                ctx, t0, VERDICT_CAUTION,
                "LOTO-eligible context — CET sign-off mandatory",
                [*reasoning, "No HARD_STOP triggers fired, but all energized work " "requires CET signature per ADR-006. Safety Officer " "never auto-approves."],
                evidence,
            )

        # No specific subject — generic advisory
        return await self._finalize(
            ctx, t0, VERDICT_APPROVE,
            "No safety-critical context in query",
            ["Query has no asset/procedure/WO subject; "
             "Safety Officer has no scope to evaluate."],
            evidence,
        )

    # ── T3.3b: advisory Gemma narrative + verdict finalizer ────────────
    async def _finalize(
        self,
        ctx: ConsultContext,
        t0: float,
        verdict: str,
        summary: str,
        reasoning: list[str],
        evidence: list[str],
    ) -> AgentVerdict:
        """Build the AgentVerdict, attaching an advisory Gemma narrative
        when an llm_client is configured.

        ADR-006: the narrative is advisory ONLY. The verdict — including
        any HARD_STOP veto, which outranks every other agent — is already
        decided by the caller and is never altered here.
        """
        llm_narrative = ""
        if self._llm_client is not None:
            kalman_lines = await _collect_kalman_lines(
                self._telemetry_provider, ctx.asset_id,
            )
            if kalman_lines:
                evidence = [*evidence, f"hermes:kalman_z ({len(kalman_lines)} ch)"]
            llm_narrative = await self._synthesize_narrative(
                ctx, verdict, summary, kalman_lines,
            )
            if llm_narrative:
                evidence = [*evidence, "gemma:safety_officer_narrative"]
                reasoning = [*reasoning, f"Gemma narrative: {llm_narrative}"]
        return AgentVerdict(
            agent_name=self.name, verdict=verdict, summary=summary,
            reasoning=reasoning, evidence_refs=evidence,
            decision_time_ms=_ms_since(t0), llm_narrative=llm_narrative,
        )

    async def _synthesize_narrative(
        self,
        ctx: ConsultContext,
        verdict: str,
        summary: str,
        kalman_lines: list[str],
    ) -> str:
        """Build the Safety Officer's Gemma prompt and call the model.

        ADR-006: advisory ONLY. ``verdict`` is already decided; the prompt
        explicitly forbids the model from overriding it.
        """
        kalman_block = (
            "\n".join(f"  {ln}" for ln in kalman_lines)
            if kalman_lines
            else "  (live Kalman tap unavailable this tick)"
        )
        prompt = (
            "You are the Safety Officer agent of a Tier IV AI-factory "
            "operations platform, governing LOTO and PPE compliance under "
            "CSA Z462 / NFPA 70E / NEC 460.6. In 2-3 sentences give an "
            "advisory safety narrative for the assessment below. Ground "
            "every claim strictly in the data provided; do not invent "
            "values. Be concise and factual.\n\n"
            f"ASSET: {ctx.asset_id or 'n/a'}\n"
            f"WORK ORDER: {ctx.work_order_id or 'n/a'}   "
            f"PROCEDURE: {ctx.procedure_id or 'n/a'}\n"
            f"DETERMINISTIC VERDICT (already decided, do not override): "
            f"{verdict}\n"
            f"VERDICT HEADLINE: {summary}\n"
            "LIVE KALMAN TELEMETRY (Z-score; |z|>=3 is a statistical "
            "anomaly):\n"
            f"{kalman_block}\n"
        )
        return await _gemma_complete(self._llm_client, prompt, max_tokens=240)


# ─── Agent: Diagnostician ──────────────────────────────────────────────
class DiagnosticianAgent:
    """Recurrence + corpus-grounded historical context.

    Verdict basis (deterministic):
      - CAUTION  if asset has 3+ completed WOs in trailing 18 months OR
                 if open WO count >= 2 already
      - APPROVE  otherwise (with the historical context surfaced)

    T3.3 -- when an ``llm_client`` (local Gemma) and a
    ``telemetry_provider`` (live Hermes Kalman tap) are injected, the
    agent additionally calls Gemma to synthesize an advisory diagnostic
    narrative grounded in the asset's live Kalman Z-scores. Per ADR-006
    that narrative is advisory ONLY: the ``verdict`` above is computed
    before the LLM is consulted and is never altered by it.
    """

    name = "Diagnostician"

    RECURRENCE_THRESHOLD = 3   # WOs in trailing 18 months
    OPEN_BACKLOG_THRESHOLD = 2
    KALMAN_TOP_N = 4           # channels surfaced into the Gemma prompt

    def __init__(
        self,
        cmms_repo: Any | None,
        rag_service: Any | None,
        llm_client: Any | None = None,
        telemetry_provider: Any | None = None,
    ):
        self._cmms_repo = cmms_repo
        self._rag = rag_service
        # T3.3: optional live-Gemma narrative layer. Both default to None
        # so every existing call site and unit test is unaffected.
        self._llm_client = llm_client
        self._telemetry_provider = telemetry_provider

    async def evaluate(self, ctx: ConsultContext) -> AgentVerdict:
        t0 = time.perf_counter()
        evidence: list[str] = []
        reasoning: list[str] = []

        if not ctx.asset_id:
            return AgentVerdict(
                agent_name=self.name, verdict=VERDICT_APPROVE,
                summary="No asset specified — no history to inspect",
                reasoning=["Diagnostician requires asset_id to query "
                           "WO history and recurrence patterns."],
                evidence_refs=[],
                decision_time_ms=_ms_since(t0),
            )

        if self._cmms_repo is None:
            return AgentVerdict(
                agent_name=self.name, verdict=VERDICT_DEGRADED,
                summary="cmms_repo unavailable — recurrence check skipped",
                reasoning=["CMMS repository was not injected; "
                           "Diagnostician cannot inspect WO history."],
                evidence_refs=[],
                decision_time_ms=_ms_since(t0),
            )

        # Recurrence check via WO history
        verdict = VERDICT_APPROVE
        total_wo = completed_wo = open_wo = 0
        try:
            history = await self._cmms_repo.list_work_orders_async(
                asset_id=ctx.asset_id, limit=50,
            )
            evidence.append(f"cmms:WO_history:{ctx.asset_id} ({len(history)} rows)")
            completed = [w for w in history
                         if getattr(w, "status", "") == "completed"]
            open_now = [w for w in history
                        if getattr(w, "status", "") in
                        ("pending_approval", "approved", "scheduled", "in_progress")]
            total_wo, completed_wo, open_wo = len(history), len(completed), len(open_now)
            reasoning.append(
                f"WO history for {ctx.asset_id}: {len(history)} total, "
                f"{len(completed)} completed, {len(open_now)} currently open."
            )
            if len(completed) >= self.RECURRENCE_THRESHOLD:
                verdict = VERDICT_CAUTION
                reasoning.append(
                    f"Recurrence pattern detected: {len(completed)} prior "
                    f"completed WOs (threshold {self.RECURRENCE_THRESHOLD}). "
                    f"Investigate root cause before another reactive fix."
                )
            if len(open_now) >= self.OPEN_BACKLOG_THRESHOLD:
                verdict = VERDICT_CAUTION
                reasoning.append(
                    f"Open backlog already at {len(open_now)} WOs on this "
                    f"asset. Sequence work to avoid double-LOTO conflicts."
                )
        except Exception as e:
            reasoning.append(f"WO history lookup failed: {e}")
            verdict = VERDICT_DEGRADED

        # Corpus context (best-effort)
        if self._rag is not None:
            try:
                # Lightweight: just check if the asset has tier-1/2 hits
                results = self._rag.query(
                    query=f"{ctx.asset_id} maintenance procedure", k=3,
                ) if hasattr(self._rag, "query") else None
                if results:
                    n_hits = len(results) if isinstance(results, list) else 0
                    evidence.append(f"rag:corpus_hits:{ctx.asset_id} ({n_hits})")
                    reasoning.append(
                        f"Corpus has {n_hits} relevant chunk(s) for this asset; "
                        f"retrievable via /api/tech-assist/troubleshoot."
                    )
            except Exception as e:
                reasoning.append(f"RAG lookup failed: {e}")

        # T3.3: advisory Gemma narrative grounded in live Kalman Z-scores.
        # Runs AFTER the deterministic verdict; never alters it (ADR-006).
        llm_narrative = ""
        if self._llm_client is not None and verdict != VERDICT_DEGRADED:
            kalman_lines = await _collect_kalman_lines(
                self._telemetry_provider, ctx.asset_id,
            )
            if kalman_lines:
                evidence.append(
                    f"hermes:kalman_z:{ctx.asset_id} ({len(kalman_lines)} ch)"
                )
            history_line = (
                f"{total_wo} total, {completed_wo} completed, {open_wo} open"
            )
            llm_narrative = await self._synthesize_narrative(
                ctx, verdict, history_line, kalman_lines,
            )
            if llm_narrative:
                evidence.append("gemma:diagnostician_narrative")
                reasoning.append(f"Gemma narrative: {llm_narrative}")

        summary = (
            "Recurrence detected — investigate root cause"
            if verdict == VERDICT_CAUTION
            else "No recurrence pattern in history"
        )
        return AgentVerdict(
            agent_name=self.name, verdict=verdict,
            summary=summary, reasoning=reasoning,
            evidence_refs=evidence, decision_time_ms=_ms_since(t0),
            llm_narrative=llm_narrative,
        )

    # ── T3.3: advisory Gemma narrative (verdict-independent) ───────────
    async def _synthesize_narrative(
        self,
        ctx: ConsultContext,
        verdict: str,
        history_line: str,
        kalman_lines: list[str],
    ) -> str:
        """Build the Diagnostician's Gemma prompt and call the model.

        ADR-006: advisory ONLY. ``verdict`` is already decided and is
        passed in purely as prompt context.
        """
        kalman_block = (
            "\n".join(f"  {ln}" for ln in kalman_lines)
            if kalman_lines
            else "  (live Kalman tap unavailable this tick)"
        )
        prompt = (
            "You are the Diagnostician agent of a Tier IV AI-factory "
            "operations platform. In 2-3 sentences give a maintenance-"
            "engineering diagnostic narrative for the asset below. Ground "
            "every claim strictly in the data provided; do not invent "
            "values. Be concise and factual.\n\n"
            f"ASSET: {ctx.asset_id}\n"
            f"DETERMINISTIC VERDICT (already decided, do not override): "
            f"{verdict}\n"
            f"WORK-ORDER HISTORY: {history_line}\n"
            "LIVE KALMAN TELEMETRY (Z-score; |z|>=3 is a statistical "
            "anomaly):\n"
            f"{kalman_block}\n"
        )
        return await _gemma_complete(self._llm_client, prompt, max_tokens=240)


# ─── Agent: Analyst ────────────────────────────────────────────────────
# Cost heuristics are illustrative for V9 façade — V10 will use vendor
# quotes from the asset registry. CapEx threshold per asset_type:
COST_HEURISTICS_USD = {
    "ups":            {"opex_repair": 8500,  "capex_replace": 250000},
    "chiller":        {"opex_repair": 12000, "capex_replace": 480000},
    "cdu":            {"opex_repair": 3500,  "capex_replace": 65000},
    "pump":           {"opex_repair": 1500,  "capex_replace": 18000},
    "genset":         {"opex_repair": 6500,  "capex_replace": 320000},
    "transformer":    {"opex_repair": 9000,  "capex_replace": 180000},
    "switchgear":     {"opex_repair": 7500,  "capex_replace": 220000},
    "ats":            {"opex_repair": 5500,  "capex_replace": 95000},
    "rpp":            {"opex_repair": 3200,  "capex_replace": 42000},
    "busway":         {"opex_repair": 2800,  "capex_replace": 38000},
    "cooling_tower":  {"opex_repair": 6500,  "capex_replace": 145000},
    "cooling_tower_field": {"opex_repair": 6500, "capex_replace": 145000},
    "fuel_tank":      {"opex_repair": 2200,  "capex_replace": 28000},
    "bms_panel":      {"opex_repair": 1800,  "capex_replace": 22000},
    "utility_intake": {"opex_repair": 11000, "capex_replace": 380000},
    "it_rack":        {"opex_repair": 950,   "capex_replace": 12500},
}
DEFAULT_COSTS = {"opex_repair": 2500, "capex_replace": 25000}


class AnalystAgent:
    """KPI + CapEx-vs-OpEx framing.

    Verdict basis:
      - CAUTION  if completed_count >= 3 (recommend replace consideration)
      - APPROVE  otherwise (repair is correct decision)
    """

    name = "Analyst"
    REPLACE_THRESHOLD_COUNT = 3   # 3+ completed WOs in lookback -> consider replace

    def __init__(self, site_model: Any | None, cmms_repo: Any | None):
        self._site = site_model
        self._cmms_repo = cmms_repo

    async def evaluate(self, ctx: ConsultContext) -> AgentVerdict:
        t0 = time.perf_counter()
        evidence: list[str] = []
        reasoning: list[str] = []

        if not ctx.asset_id:
            return AgentVerdict(
                agent_name=self.name, verdict=VERDICT_APPROVE,
                summary="No asset specified — no cost framing",
                reasoning=["Analyst requires asset_id to compute "
                           "CapEx vs OpEx framing."],
                evidence_refs=[],
                decision_time_ms=_ms_since(t0),
            )

        # Resolve asset type for cost heuristic
        asset_type = "unknown"
        if self._site is not None:
            try:
                comp = self._site.get_component(ctx.asset_id)
                asset_type = comp.type
                evidence.append(f"site_model:{ctx.asset_id}/type")
            except Exception:
                pass

        costs = COST_HEURISTICS_USD.get(asset_type, DEFAULT_COSTS)
        opex = costs["opex_repair"]
        capex = costs["capex_replace"]
        ratio = capex / max(opex, 1)
        reasoning.append(
            f"Asset class '{asset_type}': OpEx repair ~USD {opex:,}, "
            f"CapEx replace ~USD {capex:,} (ratio {ratio:.1f}x)."
        )

        # Recurrence -> replace recommendation
        verdict = VERDICT_APPROVE
        if self._cmms_repo is not None:
            try:
                history = await self._cmms_repo.list_work_orders_async(
                    asset_id=ctx.asset_id, limit=50,
                )
                evidence.append(f"cmms:WO_history:{ctx.asset_id}")
                completed = [w for w in history
                             if getattr(w, "status", "") == "completed"]
                if len(completed) >= self.REPLACE_THRESHOLD_COUNT:
                    cumulative_opex = len(completed) * opex
                    breakeven_pct = (cumulative_opex / capex) * 100
                    reasoning.append(
                        f"Cumulative OpEx across {len(completed)} prior "
                        f"repairs: ~USD {cumulative_opex:,} "
                        f"({breakeven_pct:.0f}% of CapEx replace). "
                        f"Replacement justified once breakeven approaches "
                        f"40-60% with degraded MTBF."
                    )
                    if breakeven_pct >= 40:
                        verdict = VERDICT_CAUTION
                        reasoning.append(
                            "Recommend escalating to capital planning review."
                        )
                else:
                    reasoning.append(
                        f"{len(completed)} prior repair(s) — repair-and-monitor "
                        f"is the correct decision; replacement not yet justified."
                    )
            except Exception as e:
                reasoning.append(f"History lookup failed: {e}")

        summary = (
            f"OpEx ${opex:,} vs CapEx ${capex:,} — "
            + ("escalate to CapEx review" if verdict == VERDICT_CAUTION
               else "OpEx repair correct")
        )
        return AgentVerdict(
            agent_name=self.name, verdict=verdict,
            summary=summary, reasoning=reasoning,
            evidence_refs=evidence, decision_time_ms=_ms_since(t0),
        )


# ─── Orchestrator ──────────────────────────────────────────────────────
class MultiAgentOrchestrator:
    """Runs the four agents in parallel and computes consensus."""

    def __init__(
        self,
        site_model: Any | None = None,
        graphrag: Any | None = None,
        cmms_repo: Any | None = None,
        rag_service: Any | None = None,
        llm_client: Any | None = None,
        telemetry_provider: Any | None = None,
    ):
        self._architect    = ArchitectAgent(site_model, graphrag, cmms_repo=cmms_repo)
        self._safety       = SafetyOfficerAgent(
            site_model, cmms_repo,
            llm_client=llm_client, telemetry_provider=telemetry_provider,
        )
        self._diagnostician = DiagnosticianAgent(
            cmms_repo, rag_service,
            llm_client=llm_client, telemetry_provider=telemetry_provider,
        )
        self._analyst      = AnalystAgent(site_model, cmms_repo)

    @property
    def agents(self) -> list[Any]:
        return [self._architect, self._safety, self._diagnostician, self._analyst]

    async def consult(self, ctx: ConsultContext) -> ConsensusResult:
        """Run all agents in parallel and aggregate."""
        t0 = time.perf_counter()
        # asyncio.gather with return_exceptions so one agent crash doesn't
        # take down the whole consultation. We convert exceptions to a
        # DEGRADED verdict with the error in reasoning.
        coros = [a.evaluate(ctx) for a in self.agents]
        results = await asyncio.gather(*coros, return_exceptions=True)

        verdicts: list[AgentVerdict] = []
        for agent, res in zip(self.agents, results, strict=False):
            if isinstance(res, Exception):
                log.warning("[multi_agent] %s crashed: %s", agent.name, res)
                verdicts.append(AgentVerdict(
                    agent_name=agent.name, verdict=VERDICT_DEGRADED,
                    summary=f"{agent.name} crashed during evaluation",
                    reasoning=[f"unhandled exception: {type(res).__name__}: {res}"],
                    evidence_refs=[],
                    decision_time_ms=0,
                ))
            else:
                verdicts.append(res)

        consensus, veto, rationale = self._compute_consensus(verdicts)
        return ConsensusResult(
            consensus=consensus,
            safety_officer_veto=veto,
            agents=verdicts,
            decision_time_ms=_ms_since(t0),
            rationale=rationale,
        )

    @staticmethod
    def _compute_consensus(
        verdicts: list[AgentVerdict],
    ) -> tuple[str, bool, str]:
        """Deterministic rule:
          1. Safety Officer hard_stop -> hard_stop (VETO).
          2. Any agent hard_stop -> hard_stop.
          3. Any agent caution -> caution.
          4. Else approve.
        """
        by_name = {v.agent_name: v for v in verdicts}
        safety = by_name.get(SafetyOfficerAgent.name)
        if safety and safety.verdict == VERDICT_HARD_STOP:
            return VERDICT_HARD_STOP, True, (
                f"Safety Officer VETO: {safety.summary}. "
                f"Per ADR-006, this outranks all other agents."
            )
        for v in verdicts:
            if v.verdict == VERDICT_HARD_STOP:
                return VERDICT_HARD_STOP, False, (
                    f"{v.agent_name} flagged hard_stop: {v.summary}."
                )
        cautions = [v for v in verdicts if v.verdict == VERDICT_CAUTION]
        if cautions:
            names = ", ".join(v.agent_name for v in cautions)
            return VERDICT_CAUTION, False, (
                f"Caution from {names}. Operator should review before approving."
            )
        return VERDICT_APPROVE, False, (
            "All agents converge on approve; no blockers detected. "
            "CET signature still required per ADR-006."
        )


# ─── Singleton helpers ─────────────────────────────────────────────────
_orchestrator: MultiAgentOrchestrator | None = None


def get_orchestrator(
    site_model: Any | None = None,
    graphrag: Any | None = None,
    cmms_repo: Any | None = None,
    rag_service: Any | None = None,
    llm_client: Any | None = None,
    telemetry_provider: Any | None = None,
) -> MultiAgentOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = MultiAgentOrchestrator(
            site_model=site_model, graphrag=graphrag,
            cmms_repo=cmms_repo, rag_service=rag_service,
            llm_client=llm_client, telemetry_provider=telemetry_provider,
        )
        log.info(
            "[multi_agent] orchestrator initialized "
            "(site=%s, graphrag=%s, cmms=%s, rag=%s)",
            site_model is not None, graphrag is not None,
            cmms_repo is not None, rag_service is not None,
        )
    return _orchestrator


def reset_orchestrator() -> None:
    global _orchestrator
    _orchestrator = None
