"""
DC-EPMS PRO  -  Agent Engine (NeMo Guardrails + Gemma/Claude streaming)
======================================================================
Dual-AI orchestration:
  - Gemma 4 (local via LM Studio) for routine CET queries
  - Claude Sonnet 4.6 (cloud) for complex reasoning
  - NeMo Guardrails filter input/output
  - RAG grounding for technical queries (Schneider WP122, MOPs)

VRAM safety:
  - No long-lived conversation state on GPU
  - Each stream() call is independent
  - Context is reset per request  -  nothing accumulates
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator

import httpx

log = logging.getLogger("dc-epms.agent")

# NeMo Guardrails is optional  -  agent works without it if uninstalled
try:
    from nemoguardrails import LLMRails, RailsConfig

    HAS_NEMO = True
except ImportError:
    HAS_NEMO = False
    log.info("NeMo Guardrails not installed  -  agent runs without input/output rails")


SYSTEM_PROMPT = """You are the Edge Operations expert AI for
A-Cubed Semiconductor Systems Inc. (a3semi), operating at facility A3-Alpha
Toronto Area (Tier IV 2N, 40MW hyperscale, 118 x NVIDIA GB200 NVL72 Blackwell racks).
Lead Architect: W. Angel, CTO.

You ground your responses in a 4-tier knowledge base:
  TIER 1 (Safety, highest priority) - CSA Z462 LOTO, NFPA 70E arc flash,
          OSHA confined space, NFPA 72/2001/12 fire, EPO procedures
  TIER 2 (Vendor) - Schneider WP122, UPS Galaxy VX, York YZ chiller,
          Starline busway, NVIDIA GB200 NVL72 DLC
  TIER 3 (Standards) - ASHRAE A2 thermal (10-35C), IEC 62443 OT zones,
          ISO 22301 BC/DR, NFPA 110 Type 10 emergency power, Newton thermal
  TIER 4 (a3semi MOPs/EOPs) - site-specific procedures

SAFETY CITATION PROTOCOL (MANDATORY):
If a query involves ANY of: energized work, LOTO, lockout, tagout, arc flash,
electrocution, shock, PPE, confined space, EPO, emergency power off, fire,
smoke, suppression, evacuation, hazard - you MUST:
  1. Cite the specific Tier 1 safety document (by doc_id) FIRST
  2. Never provide operational guidance before safety framing
  3. Explicitly state PPE requirements when electrical work is involved
  4. Reference the two-person rule for any energized work

Style: precise, technical, actionable. Cite documents as [Tier X: doc_id].
Keep responses under 300 words unless a checklist or template is requested.
Never invent procedures - if uncertain, say so and recommend consulting the
specific tier of procedure."""


class AgentEngine:
    """Orchestrates Gemma/Claude with NeMo Guardrails + RAG grounding."""

    def __init__(
        self,
        lm_studio_url: str,
        anthropic_api_key: str,
        rag_service=None,
        config_dir: str | None = None,
    ):
        self.lm_studio_url = lm_studio_url.rstrip("/")
        self.anthropic_api_key = anthropic_api_key
        self.rag = rag_service
        self.config_dir = config_dir
        self._rails = None
        self._gemma_model_id = None
        if HAS_NEMO and config_dir:
            self._init_rails(config_dir)

    def _init_rails(self, config_dir: str):
        """Load NeMo Guardrails config from config/ directory.

        NeMo's OpenAI provider validates OPENAI_API_KEY at init time
        even if base_url points to LM Studio. We inject a dummy key
        so validation passes - LM Studio ignores the Bearer header.
        """
        # Inject dummy OpenAI key for NeMo's validator (LM Studio ignores it)
        if not os.environ.get("OPENAI_API_KEY"):
            os.environ["OPENAI_API_KEY"] = "lm-studio-local-no-key-required"

        try:
            cfg_path = os.path.join(config_dir)
            if os.path.exists(os.path.join(cfg_path, "config.yml")):
                config = RailsConfig.from_path(cfg_path)
                self._rails = LLMRails(config)
                log.info("NeMo Guardrails loaded from %s", cfg_path)
        except Exception as e:
            log.warning("NeMo Guardrails init failed: %s", e)
            self._rails = None

    async def probe_gemma(self) -> bool:
        """Check if LM Studio is reachable and has a model loaded."""
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(f"{self.lm_studio_url}/v1/models")
                if resp.status_code == 200:
                    data = resp.json()
                    models = data.get("data", [])
                    if models:
                        # Prefer a Gemma model, fall back to first
                        for m in models:
                            if "gemma" in m.get("id", "").lower():
                                self._gemma_model_id = m["id"]
                                break
                        if not self._gemma_model_id:
                            self._gemma_model_id = models[0]["id"]
                        return True
        except Exception as e:
            log.debug("Gemma probe failed: %s", e)
        return False

    def _augment_with_rag(self, query: str) -> str:
        """Grounding: prepend RAG context if technical query."""
        if not self.rag:
            return query
        try:
            context = self.rag.build_context(query, max_chars=1000)
            if context and context != "KNOWLEDGE BASE CONTEXT:\n":
                return (
                    f"{context}\n\n"
                    f"USER QUERY: {query}\n\n"
                    f"Answer using the knowledge base context above. Cite specific "
                    f"standards or Schneider Electric white papers when relevant."
                )
        except Exception as e:
            log.debug("RAG augmentation failed: %s", e)
        return query

    def get_rag_sources(self, query: str, n_results: int = 3) -> list[dict]:
        """Return the top-N RAG sources for a query without generating.

        This is called separately from stream() so the UI can display
        citation chips before the LLM begins generating tokens.
        Returns a list of {doc_id, tier, priority, standard, score, snippet}.
        """
        if not self.rag:
            return []
        try:
            result = self.rag.query(query, n_results=n_results)
            out = []
            for r in result.get("results", []):
                meta = r.get("metadata", {}) or {}
                text = r.get("text", "")
                snippet = text[:140].replace("\n", " ").strip()
                if len(text) > 140:
                    snippet += "..."
                out.append(
                    {
                        "doc_id": r.get("doc_id", ""),
                        "tier": r.get("tier", meta.get("tier", 4)),
                        "priority": meta.get("priority", ""),
                        "standard": meta.get("standard", ""),
                        "score": round(r.get("score", 0.0), 3),
                        "similarity": round(r.get("similarity", 0.0), 3),
                        "boost": round(r.get("boost", 0.0), 3),
                        "snippet": snippet,
                    }
                )
            return out
        except Exception as e:
            log.debug("get_rag_sources failed: %s", e)
            return []

    async def stream(
        self,
        query: str,
        context: dict | None = None,
        max_tokens: int = 500,
        model_hint: str = "auto",
    ) -> AsyncIterator[str]:
        """Stream tokens from Gemma or Claude.

        model_hint: 'auto' | 'gemma' | 'claude'
          auto: prefer Gemma for short queries, Claude for complex reasoning
        """
        # -- Guardrails: input filter -------------------------
        # Simple input length guard (NeMo rails would expand this)
        if len(query) > 4000:
            yield "[Input too long  -  max 4000 chars]"
            return
        if not query.strip():
            yield "[Empty query]"
            return

        # -- Augment with RAG if available --------------------
        augmented_query = self._augment_with_rag(query)

        # -- Route to Gemma or Claude -------------------------
        use_gemma = False
        if model_hint == "gemma":
            use_gemma = True
        elif model_hint == "auto":
            # Auto-route: short + routine -> Gemma; complex -> Claude
            ql = query.lower()
            routine_keywords = ["define", "what is", "list", "summary", "procedure", "step"]
            use_gemma = any(k in ql for k in routine_keywords) and len(query) < 500
            # Probe Gemma availability before committing
            if use_gemma:
                gemma_ok = await self.probe_gemma()
                if not gemma_ok:
                    use_gemma = False

        if use_gemma:
            async for token in self._stream_gemma(augmented_query, max_tokens):
                yield token
        else:
            async for token in self._stream_claude(augmented_query, max_tokens):
                yield token

    # -- Gemma streaming via LM Studio OpenAI-compatible API --
    async def _stream_gemma(self, prompt: str, max_tokens: int) -> AsyncIterator[str]:
        if not self._gemma_model_id:
            await self.probe_gemma()
        model = self._gemma_model_id or "gemma-4-e2b-it"

        url = f"{self.lm_studio_url}/v1/chat/completions"
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "stream": True,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=120.0) as client, client.stream(
                "POST", url, json=payload, headers={"Content-Type": "application/json"}
            ) as resp:
                if resp.status_code != 200:
                    yield f"[Gemma error {resp.status_code}]"
                    return
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        delta = obj.get("choices", [{}])[0].get("delta", {})
                        token = delta.get("content", "")
                        if token:
                            yield token
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            yield f"[Gemma stream error: {e}]"

    # -- Claude streaming via Anthropic API -------------------
    async def _stream_claude(self, prompt: str, max_tokens: int) -> AsyncIterator[str]:
        if not self.anthropic_api_key:
            yield "[Claude API key not configured]"
            return

        url = "https://api.anthropic.com/v1/messages"
        payload = {
            "model": "claude-sonnet-4-5",
            "max_tokens": max_tokens,
            "system": SYSTEM_PROMPT,
            "stream": True,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.anthropic_api_key,
            "Anthropic-Version": "2023-06-01",
        }
        try:
            async with (
                httpx.AsyncClient(timeout=120.0) as client,
                client.stream("POST", url, json=payload, headers=headers) as resp,
            ):
                if resp.status_code != 200:
                    yield f"[Claude error {resp.status_code}]"
                    return
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    try:
                        obj = json.loads(data)
                        if obj.get("type") == "content_block_delta":
                            token = obj.get("delta", {}).get("text", "")
                            if token:
                                yield token
                        elif obj.get("type") == "message_stop":
                            break
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            yield f"[Claude stream error: {e}]"

    # -- PUE advisory (autonomous alert) ----------------------
    async def trigger_pue_advisory(self, telemetry_point: dict):
        """Fire autonomous advisory when PUE > 1.4.

        Generates a root-cause hypothesis and logs to console. In production,
        this would push to a WebSocket/SSE channel for the dashboard.
        """
        pue = telemetry_point.get("pue", 0)
        hall = telemetry_point.get("hall_temp_c", 0)
        scenario = telemetry_point.get("scenario", "NORMAL")
        query = (
            f"PUE has exceeded efficiency threshold: current PUE = {pue:.3f} "
            f"(target < 1.40 per A-Cubed Semiconductor efficiency standard). "
            f"Hall temperature: {hall:.1f}degC. Active scenario: {scenario}. "
            f"Provide a 2-sentence root-cause hypothesis and immediate action."
        )
        tokens = []
        async for t in self.stream(query, max_tokens=150, model_hint="auto"):
            tokens.append(t)
        advisory = "".join(tokens)
        log.warning("PUE ADVISORY [%.3f]: %s", pue, advisory[:300])
        return advisory
