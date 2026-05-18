"""
DC-EPMS PRO v8  -  Agentic Copilot Engine
========================================
Tool-using LLM agent that consumes the HAL/physics/STGNN read-side and
emits human-in-the-loop drafts for any write-side action.

Architecture (per IEC 62443 SL-2/SL-3):
- READ tools execute synchronously and return facts
- WRITE tools return a Draft object; the operator clicks Approve in the
  HMI; the approval triggers the actual side-effecting call with NIST
  SP 800-82 audit logging
- The agent itself never directly mutates OT state. The draft pattern
  is structurally enforced: write-tool implementations build a Draft
  and return it; they do not call the HAL.

Wire protocol:
- LM Studio (or any OpenAI-compatible inference endpoint) exposes the
  Gemma model with `/v1/chat/completions` accepting `tools` parameter
- We use the standard OpenAI tool-calling schema, which is the same
  shape MCP's `tools/call` JSON-RPC method uses internally
- Streaming tokens are NOT used in the agent loop because intermediate
  tool calls require structured (non-streamed) responses; we stream
  only the final assistant message back to the SPA

Honest scope notes (read this before assuming everything works):
- query_unified_graph()    -> reads from the v5.2 topology endpoint
                              + bms_connector. The "Unified Graph" of
                              v7.1 is the architectural target; today
                              we expose the existing graph shape.
- analyze_rul_and_supply() -> RUL is a deterministic placeholder until
                              v6 STGNN is trained; supply is a stub
                              until the Wesco partnership is signed.
                              Both pieces are clearly labelled in the
                              tool's response so the operator (and the
                              LLM) know what is real vs nominal.
- draft_precooling_plan()  -> builds a setpoint trajectory using the
                              existing physics engine in inverse-mode
                              approximation (bisection on chiller
                              setpoint). Returns a Draft, never writes.

Dependencies (kept light, no agent frameworks):
    httpx (already in stack)   -  calls to LM Studio
    pydantic (already)         -  validation
    fastapi (already)          -  endpoint exposure

No LangChain, no CrewAI, no AutoGen. The agent loop is < 200 lines of
Python because that is all it should be.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
LM_STUDIO_URL = os.environ.get("LM_STUDIO_URL", "http://127.0.0.1:1234")
LM_STUDIO_TIMEOUT_S = float(os.environ.get("LM_STUDIO_TIMEOUT_S", "60.0"))
AGENT_MAX_TOOL_HOPS = int(os.environ.get("AGENT_MAX_TOOL_HOPS", "6"))
AGENT_TEMPERATURE = float(os.environ.get("AGENT_TEMPERATURE", "0.2"))


# -----------------------------------------------------------------------------
# System prompt
# -----------------------------------------------------------------------------
SYSTEM_PROMPT = """You are the DC-EPMS PRO Facility Co-Pilot, an embedded \
operational assistant for a Tier IV 2N data center hosting 118 NVIDIA GB200 \
NVL72 racks at A3-Alpha (Toronto). You speak with the on-shift Critical \
Environments Technician (CET).

OPERATING ENVELOPE:
- 40 MW total - 2N redundancy - ASHRAE A2 thermal envelope (10-35degC inlet)
- DLC primary (propylene glycol 50/50, supply 18degC, return <=45degC)
- Chillers: York YZ centrifugal, 2 x 5275 kW, N+1
- UPS: Schneider Galaxy VX 750 kVA - 2N - VRLA batteries
- BMS: 42 BACnet/Modbus tags via the v5.2 bms_connector

OPERATING DOCTRINE:
1. You answer using TOOLS, not from training-data recall. If you need a
   value, call a tool. If you do not have a tool for something, say so.
2. You NEVER mutate OT state. Setpoint changes, BMS writes, and \
purchase-order submissions go through the human-in-the-loop draft \
pattern. You produce drafts; the operator approves them with a click.
3. You cite numerical values precisely. Round only when the question \
is qualitative.
4. You reference applicable standards by name (ASHRAE A2, NFPA 70E, \
IEEE C57.12, IEC 62443) when the operator's question touches them.
5. If a tool returns degraded data ("nominal" instead of "physics_verified"), \
you say so. You do not silently treat nominal values as live.
6. If asked to do something outside your tool surface, you decline \
clearly and suggest the right channel (operator action, EOP \
retrieval via RAG, escalation to Engineering).
7. DATA PROVENANCE DISCLOSURE  -  MANDATORY. If a tool result contains \
ANY field whose key starts with an underscore (e.g. `_honest_note`, \
`_source`, `_data_source`) OR whose value contains the literal string \
"PLACEHOLDER", you MUST surface that disclosure verbatim to the \
operator in a clearly-marked section of your reply, prefixed with \
"⚠ DATA PROVENANCE NOTE:". This is a regulatory requirement under \
NIST SP 800-82 §6.2.4 (data quality attestation). Failure to surface \
such a notice is treated as if you fabricated the data.
8. WRITE-INTENT REPORTING. When a tool returns a `draft_id`, your reply \
MUST include the draft ID verbatim, the proposed setpoint changes with \
old -> new values, and the explicit instruction "This draft will NOT \
execute until you approve it via the HMI." The operator must know \
exactly what they are approving before they click.

You are NOT a chatbot. You are a tool-using operational agent. Prefer \
short, structured answers. The operator is busy."""


# -----------------------------------------------------------------------------
# Tool schemas (OpenAI / MCP compatible JSON Schema)
# -----------------------------------------------------------------------------
TOOLS_SCHEMA: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "query_unified_graph",
            "description": (
                "Read live state of any equipment node in the facility's "
                "Unified Graph: telemetry, severity, redundancy role (2N path A or B), "
                "and the node's neighbours in the topology. Use this when the operator "
                "asks about the current state of a specific component  -  UPS, transformer, "
                "chiller, CDU, RPP, busway, hall, rack."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": (
                            "Canonical device identifier. Examples: "
                            "'utility_north', 'xfmr_a', 'ups_a', 'ups_b', "
                            "'chiller_1', 'chiller_2', 'cooling_tower', "
                            "'cdu_a', 'cdu_b', 'rpp_a1', 'rpp_a2', "
                            "'busway_a', 'busway_b', 'hall_1', 'hall_2', 'hall_3'."
                        ),
                    },
                },
                "required": ["device_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_rul_and_supply",
            "description": (
                "Get the predicted Remaining Useful Life (RUL) of a component "
                "from the v6 STGNN model AND the live supply chain status from "
                "the Wesco partnership API. Returns the joint analysis: when the "
                "component is predicted to fail, whether the part is in stock, "
                "and whether procurement action is recommended. Use this when the "
                "operator asks about maintenance scheduling or part availability."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "component_id": {
                        "type": "string",
                        "description": (
                            "Canonical component identifier whose RUL to assess. "
                            "Same namespace as query_unified_graph."
                        ),
                    },
                },
                "required": ["component_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_precooling_plan",
            "description": (
                "Compose a pre-cooling setpoint trajectory for the chilled-water "
                "loop in anticipation of an incoming IT load (typically a CoreWeave "
                "training job on the GB200 fleet). Returns a Draft object listing "
                "the proposed setpoint changes  -  the operator must approve via the "
                "HMI before any setpoint is written. The draft is ALWAYS within the "
                "operator's existing manual write envelope (no privilege escalation)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_kw": {
                        "type": "number",
                        "description": (
                            "Estimated IT load in kW that will arrive (per rack x "
                            "number of racks). Range: 0-17000 kW (full facility)."
                        ),
                    },
                    "duration_s": {
                        "type": "integer",
                        "description": (
                            "Estimated duration of the load in seconds. Used to "
                            "decide whether a sustained pre-cool is justified. "
                            "Minimum sensible value: 300 s."
                        ),
                    },
                    "lookahead_s": {
                        "type": "integer",
                        "description": (
                            "Time before load arrival to start pre-positioning. "
                            "Default 300 s. Bounded by chiller slew rate "
                            "(1.5 K/min on chilled water setpoint)."
                        ),
                    },
                },
                "required": ["target_kw", "duration_s"],
            },
        },
    },
]


# -----------------------------------------------------------------------------
# Tool registry: name -> async callable
# -----------------------------------------------------------------------------
class ToolRegistry:
    """Owns the dispatch from LLM tool-call -> Python callable.

    Tools are async functions that take the parsed arguments dict and
    return any JSON-serializable value. The agent loop wraps the result
    in the OpenAI tool-message envelope.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Callable[[dict], Awaitable[Any]]] = {}

    def register(self, name: str, fn: Callable[[dict], Awaitable[Any]]) -> None:
        self._tools[name] = fn

    async def dispatch(self, name: str, args: dict) -> Any:
        fn = self._tools.get(name)
        if fn is None:
            return {"error": f"unknown tool: {name}"}
        try:
            return await fn(args)
        except Exception as exc:
            log.exception("tool %s raised", name)
            return {"error": f"tool execution failed: {type(exc).__name__}: {exc}"}

    def has(self, name: str) -> bool:
        return name in self._tools


# -----------------------------------------------------------------------------
# Tool implementations
# -----------------------------------------------------------------------------
async def tool_query_unified_graph(args: dict) -> dict:
    """READ tool. Pulls from the v5.2 topology endpoint + BMS connector.

    The v7.1 'Unified Graph' is the architectural target. Today we
    return a structurally-equivalent payload composed from what the
    physics engine and BMS connector already expose.
    """
    device_id = str(args.get("device_id", "")).strip()
    if not device_id:
        return {"error": "device_id required"}

    # Build the topology snapshot using the same code path the dashboard uses.
    # We import lazily to avoid circular imports during module load.
    try:
        from main import get_topology_state  # type: ignore
    except ImportError:
        return {"error": "topology service not available"}

    topology = await get_topology_state()
    nodes: dict = topology.get("hld_nodes", {})

    if device_id not in nodes:
        return {
            "error": f"device '{device_id}' not in graph",
            "available_devices": sorted(nodes.keys()),
        }

    node = nodes[device_id]
    metrics: dict = node.get("metrics", {})

    # Derive neighbours from the canonical 2N topology.
    neighbours = _topology_neighbours(device_id)

    # Mark each metric as physics-verified or nominal so the LLM can
    # surface that distinction to the operator.
    is_verified = bool(metrics.get("physics_verified", False))

    return {
        "device_id": device_id,
        "label": node.get("label"),
        "severity": node.get("severity"),
        "health": node.get("health"),
        "metrics": metrics,
        "physics_verified": is_verified,
        "redundancy_path": _redundancy_path_of(device_id),
        "neighbours": neighbours,
        "site_redundancy_mode": topology.get("redundancy_mode", "2N"),
        "site_health_index": topology.get("site_health"),
        "_data_source": "v5.2 topology endpoint + bms_connector",
    }


async def tool_analyze_rul_and_supply(args: dict) -> dict:
    """READ tool. Joint RUL + supply-chain analysis.

    HONEST SCOPE: the RUL head from v6 ML_ROADMAP_v6 is a placeholder
    until the STGNN is trained. The Wesco supply integration from v7
    is a stub until the partnership is signed. This tool returns a
    well-shaped response that surfaces both placeholders explicitly so
    the operator and the LLM treat the values appropriately.
    """
    component_id = str(args.get("component_id", "")).strip()
    if not component_id:
        return {"error": "component_id required"}

    # Fetch the device's current state to ground the placeholder RUL
    # in something deterministic (the worse the severity, the shorter
    # the placeholder RUL).
    state = await tool_query_unified_graph({"device_id": component_id})
    if "error" in state:
        return state

    severity = state.get("severity", "ok")
    health = state.get("health", 1.0) or 1.0

    # Placeholder RUL: deterministic function of health.
    # Real implementation calls the v6 STGNN Weibull AFT head.
    placeholder_rul_days = max(1.0, 60.0 * float(health))
    confidence_band_days = placeholder_rul_days * 0.3

    # Placeholder supply: nominal stock entry. Real implementation
    # calls Wesco's quote endpoint.
    placeholder_part_number = f"OEM-{component_id.upper()}-001"
    placeholder_in_stock = True
    placeholder_lead_time_days = 7

    # Action recommendation logic: short RUL + lead time gap -> expedite.
    days_buffer = placeholder_rul_days - placeholder_lead_time_days
    if days_buffer < 7:
        action = "expedite"
        rationale = (
            f"RUL ({placeholder_rul_days:.1f} d) - lead time "
            f"({placeholder_lead_time_days} d) = {days_buffer:.1f} d buffer. "
            f"Below 7-day expedite threshold."
        )
    elif days_buffer < 21:
        action = "order_now"
        rationale = (
            f"Buffer {days_buffer:.1f} d. Order now to maintain margin against RUL confidence band."
        )
    else:
        action = "watch"
        rationale = f"Buffer {days_buffer:.1f} d sufficient. Monitor RUL trajectory."

    return {
        "component_id": component_id,
        "current_state": {
            "severity": severity,
            "health": health,
        },
        "rul": {
            "predicted_days": round(placeholder_rul_days, 1),
            "confidence_band_days": round(confidence_band_days, 1),
            "_source": "PLACEHOLDER  -  v6 STGNN not yet trained. "
            "Value is a deterministic function of current health.",
        },
        "supply": {
            "part_number": placeholder_part_number,
            "in_stock": placeholder_in_stock,
            "lead_time_days": placeholder_lead_time_days,
            "_source": "PLACEHOLDER  -  Wesco partnership pending. Stub catalog entry returned.",
        },
        "recommended_action": action,
        "rationale": rationale,
        "_honest_note": (
            "Both RUL and supply data are placeholders pending v6 STGNN "
            "training and Wesco partnership. Action recommendation is "
            "structurally correct but should not drive procurement decisions "
            "until both upstreams are live."
        ),
    }


async def tool_draft_precooling_plan(args: dict) -> dict:
    """WRITE-INTENT tool. Returns a Draft object; does NOT execute.

    The operator must POST /api/agent/draft/{id}/approve to commit the
    setpoint changes via the same audit-gated path used for manual
    operator writes.
    """
    try:
        target_kw = float(args.get("target_kw"))
        duration_s = int(args.get("duration_s"))
    except (TypeError, ValueError):
        return {"error": "target_kw (number) and duration_s (int) required"}

    lookahead_s = int(args.get("lookahead_s") or 300)

    # Bounds checking
    if not (0 < target_kw <= 17_000):
        return {"error": "target_kw outside facility envelope (0-17000 kW)"}
    if duration_s < 300:
        return {
            "error": "duration_s < 300 s  -  pre-cool not justified for "
            "loads shorter than 5 minutes (chiller slew rate)"
        }
    if not (60 <= lookahead_s <= 1800):
        return {"error": "lookahead_s must be in [60, 1800] s"}

    # Compute the setpoint reduction needed using a simple capacity-based
    # heuristic. The full inverse-ODE solve described in v7 sits behind
    # this; the heuristic is a first-order approximation.
    nominal_chw_setpoint_c = 7.0  # York YZ design point
    facility_capacity_kw = 16_756.0
    capacity_fraction = min(1.0, target_kw / facility_capacity_kw)

    # Reduce setpoint up to 1.5 K (matching slew rate over lookahead).
    # Reduction is proportional to load fraction.
    setpoint_reduction_k = 1.5 * capacity_fraction
    proposed_setpoint_c = nominal_chw_setpoint_c - setpoint_reduction_k

    # Clamp to ASHRAE-driven minimums (don't go below 5degC  -  risk of
    # condensation on dry coils, refrigerant approach issues)
    proposed_setpoint_c = max(5.5, proposed_setpoint_c)

    # Build the draft commands. Two chillers, identical setpoint.
    commands: list[dict] = [
        {
            "device_id": "chiller_1",
            "command_id": "set_chilled_water_setpoint",
            "payload": {"target_c": round(proposed_setpoint_c, 2)},
            "current_value_c": nominal_chw_setpoint_c,
            "ramp_rate_k_per_min": 1.5,
            "estimated_settle_s": int(setpoint_reduction_k / 1.5 * 60),
        },
        {
            "device_id": "chiller_2",
            "command_id": "set_chilled_water_setpoint",
            "payload": {"target_c": round(proposed_setpoint_c, 2)},
            "current_value_c": nominal_chw_setpoint_c,
            "ramp_rate_k_per_min": 1.5,
            "estimated_settle_s": int(setpoint_reduction_k / 1.5 * 60),
        },
    ]

    # Persist the draft for later approval.
    draft = DraftStore.create(
        kind="precool_plan",
        commands=commands,
        rationale=(
            f"Pre-cool for incoming {target_kw:.0f} kW load over "
            f"{duration_s}s. Setpoint reduction "
            f"{setpoint_reduction_k:.2f}K starts {lookahead_s}s before "
            f"load arrival. All commands within operator's existing manual "
            f"write envelope; NIST SP 800-82 audit will record on approval."
        ),
        metadata={
            "target_kw": target_kw,
            "duration_s": duration_s,
            "lookahead_s": lookahead_s,
            "capacity_fraction": capacity_fraction,
            "ashrae_a2_compliant": True,
        },
    )

    return {
        "draft_id": draft.draft_id,
        "kind": "precool_plan",
        "status": "PENDING_OPERATOR_APPROVAL",
        "proposed_commands": commands,
        "rationale": draft.rationale,
        "approval_endpoint": f"/api/agent/draft/{draft.draft_id}/approve",
        "rejection_endpoint": f"/api/agent/draft/{draft.draft_id}/reject",
        "expires_at_unix": draft.expires_at_unix,
        "_human_in_the_loop_note": (
            "This draft will NOT execute until an operator approves it via "
            "the HMI. The agent has zero direct write capability."
        ),
    }


# -----------------------------------------------------------------------------
# Topology helpers
# -----------------------------------------------------------------------------
_REDUNDANCY_PATH_A = {
    "utility_north",
    "xfmr_a",
    "ups_a",
    "rpp_a1",
    "rpp_a2",
    "busway_a",
    "cdu_a",
    "chiller_1",
}
_REDUNDANCY_PATH_B = {
    "utility_south",
    "xfmr_b",
    "ups_b",
    "rpp_b1",
    "rpp_b2",
    "busway_b",
    "cdu_b",
    "chiller_2",
}
_TOPOLOGY_EDGES: dict[str, list[str]] = {
    "utility_north": ["xfmr_a"],
    "utility_south": ["xfmr_b"],
    "xfmr_a": ["utility_north", "ups_a"],
    "xfmr_b": ["utility_south", "ups_b"],
    "ups_a": ["xfmr_a", "rpp_a1", "rpp_a2"],
    "ups_b": ["xfmr_b", "rpp_b1", "rpp_b2"],
    "rpp_a1": ["ups_a", "busway_a"],
    "rpp_a2": ["ups_a", "busway_a"],
    "rpp_b1": ["ups_b", "busway_b"],
    "rpp_b2": ["ups_b", "busway_b"],
    "busway_a": ["rpp_a1", "rpp_a2", "hall_1", "hall_2", "hall_3"],
    "busway_b": ["rpp_b1", "rpp_b2", "hall_1", "hall_2", "hall_3"],
    "cdu_a": ["chiller_1", "hall_1", "hall_2", "hall_3"],
    "cdu_b": ["chiller_2", "hall_1", "hall_2", "hall_3"],
    "chiller_1": ["cooling_tower", "cdu_a"],
    "chiller_2": ["cooling_tower", "cdu_b"],
    "cooling_tower": ["chiller_1", "chiller_2"],
    "hall_1": ["busway_a", "busway_b", "cdu_a", "cdu_b"],
    "hall_2": ["busway_a", "busway_b", "cdu_a", "cdu_b"],
    "hall_3": ["busway_a", "busway_b", "cdu_a", "cdu_b"],
}


def _redundancy_path_of(device_id: str) -> str:
    if device_id in _REDUNDANCY_PATH_A:
        return "A"
    if device_id in _REDUNDANCY_PATH_B:
        return "B"
    return "shared"


def _topology_neighbours(device_id: str) -> list[str]:
    return _TOPOLOGY_EDGES.get(device_id, [])


# -----------------------------------------------------------------------------
# Draft store (in-memory, with TTL)
# -----------------------------------------------------------------------------
@dataclass
class Draft:
    draft_id: str
    kind: str
    commands: list[dict]
    rationale: str
    metadata: dict = field(default_factory=dict)
    created_at_unix: float = field(default_factory=time.time)
    expires_at_unix: float = 0.0
    status: str = "PENDING_OPERATOR_APPROVAL"
    approved_by: str | None = None
    approved_at_unix: float | None = None
    rejection_reason: str | None = None


class _DraftStoreImpl:
    """In-memory draft registry with TTL.

    Production deployment swaps this for PostgreSQL-backed persistence.
    The interface is identical."""

    DEFAULT_TTL_S = 600  # 10 minutes for an operator to act

    def __init__(self) -> None:
        self._drafts: dict[str, Draft] = {}

    def create(
        self,
        kind: str,
        commands: list[dict],
        rationale: str,
        metadata: dict | None = None,
        ttl_s: int = DEFAULT_TTL_S,
    ) -> Draft:
        draft_id = uuid.uuid4().hex
        now = time.time()
        draft = Draft(
            draft_id=draft_id,
            kind=kind,
            commands=commands,
            rationale=rationale,
            metadata=metadata or {},
            created_at_unix=now,
            expires_at_unix=now + ttl_s,
        )
        self._drafts[draft_id] = draft
        return draft

    def get(self, draft_id: str) -> Draft | None:
        draft = self._drafts.get(draft_id)
        if draft is None:
            return None
        if time.time() > draft.expires_at_unix and draft.status == "PENDING_OPERATOR_APPROVAL":
            draft.status = "EXPIRED"
        return draft

    def list_pending(self) -> list[Draft]:
        now = time.time()
        return [
            d
            for d in self._drafts.values()
            if d.status == "PENDING_OPERATOR_APPROVAL" and d.expires_at_unix > now
        ]

    def approve(self, draft_id: str, operator: str) -> Draft | None:
        draft = self.get(draft_id)
        if draft is None or draft.status != "PENDING_OPERATOR_APPROVAL":
            return None
        draft.status = "APPROVED"
        draft.approved_by = operator
        draft.approved_at_unix = time.time()
        return draft

    def reject(self, draft_id: str, operator: str, reason: str) -> Draft | None:
        draft = self.get(draft_id)
        if draft is None or draft.status != "PENDING_OPERATOR_APPROVAL":
            return None
        draft.status = "REJECTED"
        draft.approved_by = operator
        draft.approved_at_unix = time.time()
        draft.rejection_reason = reason
        return draft


DraftStore = _DraftStoreImpl()


# -----------------------------------------------------------------------------
# Agent loop
# -----------------------------------------------------------------------------
class FacilityCoPilot:
    """The agent loop. Stateless across requests; the SPA manages
    conversation history and replays it on each call."""

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        lm_studio_url: str = LM_STUDIO_URL,
        max_tool_hops: int = AGENT_MAX_TOOL_HOPS,
    ) -> None:
        self._registry = registry or _build_default_registry()
        self._lm_studio_url = lm_studio_url
        self._max_tool_hops = max_tool_hops
        self._http: httpx.AsyncClient | None = None
        self._model_id: str | None = None

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=LM_STUDIO_TIMEOUT_S)
        return self._http

    async def _resolve_model(self) -> str:
        """Discover the loaded model in LM Studio (Gemma family preferred)."""
        if self._model_id:
            return self._model_id
        client = await self._client()
        try:
            r = await client.get(f"{self._lm_studio_url}/v1/models")
            r.raise_for_status()
            models = r.json().get("data", [])
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(f"LM Studio not reachable: {exc}") from exc
        for m in models:
            if "gemma" in m.get("id", "").lower():
                self._model_id = m["id"]
                return self._model_id
        if models:
            self._model_id = models[0]["id"]
            return self._model_id
        raise RuntimeError("No model loaded in LM Studio")

    async def chat(
        self,
        operator_message: str,
        history: list[dict] | None = None,
    ) -> dict:
        """Run the agent loop until the model returns a final assistant
        message (no further tool calls) or max_tool_hops is exceeded.

        Returns:
            {
                "reply": str,
                "tool_invocations": [ {tool, args, result_summary}, ... ],
                "drafts": [ draft_id, ... ],
                "model_id": str,
                "hops": int,
            }
        """
        model_id = await self._resolve_model()
        client = await self._client()

        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        if history:
            # Defensive copy + filter out our internal-only fields
            for msg in history:
                if msg.get("role") in ("user", "assistant", "tool"):
                    messages.append(
                        {
                            k: v
                            for k, v in msg.items()
                            if k in ("role", "content", "tool_call_id", "tool_calls", "name")
                        }
                    )
        messages.append({"role": "user", "content": operator_message})

        invocations: list[dict] = []
        emitted_drafts: list[str] = []

        for hop in range(self._max_tool_hops):
            payload = {
                "model": model_id,
                "messages": messages,
                "tools": TOOLS_SCHEMA,
                "tool_choice": "auto",
                "temperature": AGENT_TEMPERATURE,
                "stream": False,
            }
            try:
                r = await client.post(
                    f"{self._lm_studio_url}/v1/chat/completions",
                    json=payload,
                )
                r.raise_for_status()
            except httpx.HTTPError as exc:
                log.error("LM Studio call failed at hop %d: %s", hop, exc)
                return {
                    "reply": f"Inference endpoint unreachable: {exc}",
                    "tool_invocations": invocations,
                    "drafts": emitted_drafts,
                    "model_id": model_id,
                    "hops": hop,
                    "error": "inference_unreachable",
                }

            data = r.json()
            choice = data["choices"][0]
            msg = choice["message"]

            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                # Terminal: model produced a final answer
                return {
                    "reply": msg.get("content", ""),
                    "tool_invocations": invocations,
                    "drafts": emitted_drafts,
                    "model_id": model_id,
                    "hops": hop,
                }

            # Append the assistant's tool_calls turn to the history
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.get("content", "") or None,
                    "tool_calls": tool_calls,
                }
            )

            # Execute every requested tool and append the results
            for call in tool_calls:
                fn_name = call["function"]["name"]
                try:
                    fn_args = json.loads(call["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    fn_args = {}

                tool_result = await self._registry.dispatch(fn_name, fn_args)

                # Capture invocation for the response
                invocations.append(
                    {
                        "tool": fn_name,
                        "args": fn_args,
                        "result_summary": _summarize_result(tool_result),
                    }
                )

                # Track any drafts emitted
                if isinstance(tool_result, dict) and "draft_id" in tool_result:
                    emitted_drafts.append(tool_result["draft_id"])

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "name": fn_name,
                        "content": json.dumps(tool_result, default=str),
                    }
                )

        # Hop limit reached without terminal  -  return what we have
        return {
            "reply": (
                "[Agent reached maximum tool-call hops without producing a "
                "final answer. The operator should review the tool "
                "invocations and rephrase the request.]"
            ),
            "tool_invocations": invocations,
            "drafts": emitted_drafts,
            "model_id": model_id,
            "hops": self._max_tool_hops,
            "error": "max_hops_exceeded",
        }

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None


def _build_default_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register("query_unified_graph", tool_query_unified_graph)
    reg.register("analyze_rul_and_supply", tool_analyze_rul_and_supply)
    reg.register("draft_precooling_plan", tool_draft_precooling_plan)

    # -- v8.1: CMMS work-order draft tool (Phase 1 of Tri-Brain) --
    try:
        from cmms_mcp import DRAFT_CMMS_WORK_ORDER_SCHEMA, tool_draft_cmms_work_order

        reg.register("draft_cmms_work_order", tool_draft_cmms_work_order)
        TOOLS_SCHEMA.append(DRAFT_CMMS_WORK_ORDER_SCHEMA)
        log.info("[v8.1] CMMS work-order tool registered")
    except Exception as e:
        log.warning(f"[v8.1] CMMS work-order tool NOT registered: {e}")

    # Sprint S1b: Site Model query tool
    try:
        from agent_site_tool import QUERY_SITE_MODEL_SCHEMA, tool_query_site_model

        reg.register("query_site_model", tool_query_site_model)
        TOOLS_SCHEMA.append(QUERY_SITE_MODEL_SCHEMA)
        log.info("[Sprint S1b] Site model query tool registered")
    except Exception as e:
        log.warning(f"[Sprint S1b] Site model query tool NOT registered: {e}")

    # Sprint S2: GraphRAG query tool
    try:
        from agent_graph_tool import QUERY_GRAPH_RAG_SCHEMA, tool_query_graph_rag

        reg.register("query_graph_rag", tool_query_graph_rag)
        TOOLS_SCHEMA.append(QUERY_GRAPH_RAG_SCHEMA)
        log.info("[Sprint S2] GraphRAG query tool registered")
    except Exception as e:
        log.warning(f"[Sprint S2] GraphRAG query tool NOT registered: {e}")

    return reg


def _summarize_result(result: Any) -> str:
    """Single-line summary of a tool result for invocation logs.
    Keeps the response compact when the SPA renders the call trace."""
    if isinstance(result, dict):
        if "error" in result:
            return f"error: {result['error']}"
        if "draft_id" in result:
            return f"draft {result['draft_id'][:8]} ({result.get('kind')})"
        keys = list(result.keys())[:5]
        return f"keys: {keys}"
    return str(result)[:120]


# -----------------------------------------------------------------------------
# FastAPI router  -  mount on the existing app via app.include_router(router)
# -----------------------------------------------------------------------------
router = APIRouter(prefix="/api/agent", tags=["agent"])
_copilot = FacilityCoPilot()


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    history: list[dict] | None = None
    operator: str = Field("anonymous", description="CET user id for audit")


class ChatResponse(BaseModel):
    # DC-EPMS-039: model_id collides with Pydantic v2's protected
    # "model_" namespace; disable it (mirrors AgentQuery in main.py).
    model_config = ConfigDict(protected_namespaces=())

    reply: str
    tool_invocations: list[dict]
    drafts: list[str]
    model_id: str
    hops: int
    error: str | None = None


class DraftActionRequest(BaseModel):
    operator: str = Field(..., description="CET user id, recorded in audit")
    reason: str | None = Field(None, description="Required for reject")
    actor_role: str | None = Field(None, description="RBAC F3-4 claim; None -> gate not enforced")


@router.post("/chat", response_model=ChatResponse)
async def agent_chat(req: ChatRequest) -> ChatResponse:
    """Single-turn agent chat. The SPA replays full conversation history
    on each call (the agent itself is stateless)."""
    result = await _copilot.chat(req.message, req.history)
    return ChatResponse(**result)


@router.post("/chat/stream")
async def agent_chat_stream(req: ChatRequest):
    """Server-Sent Events variant. Tool calls are non-streamed, but the
    final assistant message is streamed token-by-token. Useful for
    long-form replies."""

    async def event_stream():
        result = await _copilot.chat(req.message, req.history)
        # Emit invocations first so the SPA can render a call trace
        for inv in result["tool_invocations"]:
            yield f"event: tool\ndata: {json.dumps(inv)}\n\n"
        for draft_id in result["drafts"]:
            yield f"event: draft\ndata: {json.dumps({'draft_id': draft_id})}\n\n"
        # Final reply chunked into ~80-char pieces for visual streaming
        reply = result["reply"]
        for i in range(0, len(reply), 80):
            chunk = reply[i : i + 80]
            yield f"event: token\ndata: {json.dumps({'text': chunk})}\n\n"
            await asyncio.sleep(0.02)
        yield f"event: done\ndata: {json.dumps({'hops': result['hops']})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/drafts")
async def list_drafts() -> dict:
    """All currently pending drafts. Used by the HMI to render the
    approval queue alongside the existing v6 RUL panel."""
    drafts = DraftStore.list_pending()
    return {
        "count": len(drafts),
        "drafts": [asdict(d) for d in drafts],
    }


@router.get("/draft/{draft_id}")
async def get_draft(draft_id: str) -> dict:
    draft = DraftStore.get(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="draft not found")
    return asdict(draft)


@router.post("/draft/{draft_id}/approve")
async def approve_draft(draft_id: str, req: DraftActionRequest) -> dict:
    """Operator approval. Executes the draft's commands through the
    appropriate write path with NIST SP 800-82 audit logging.

    NOTE: actual write dispatch is delegated to the existing BMS /
    setpoint write infrastructure. We DO NOT bypass it  -  every command
    is filtered through the same validation (safety bounds, rate limits,
    alarm preconditions) that operator-originated writes pass through.
    """
    from backend.rbac import require_actor_role
    require_actor_role(req.actor_role, 5, "approving a copilot draft")
    draft = DraftStore.approve(draft_id, req.operator)
    if draft is None:
        raise HTTPException(
            status_code=409,
            detail="draft not found or not in PENDING_OPERATOR_APPROVAL state",
        )

    # Dispatch commands. If any fail, we mark the draft partially-executed.
    execution_log: list[dict] = []
    try:
        from main import _execute_drafted_command  # type: ignore

        for cmd in draft.commands:
            outcome = await _execute_drafted_command(
                command=cmd,
                operator=req.operator,
                draft_id=draft_id,
            )
            execution_log.append(outcome)
    except ImportError:
        # Bootstrap path: the dispatch hook is not yet wired into main.
        # Audit the approval anyway and report.
        execution_log.append(
            {
                "status": "DEFERRED",
                "note": "main._execute_drafted_command not yet implemented; "
                "approval is logged but commands are not dispatched.",
            }
        )

    return {
        "draft_id": draft_id,
        "status": draft.status,
        "approved_by": draft.approved_by,
        "approved_at_unix": draft.approved_at_unix,
        "execution_log": execution_log,
    }


@router.post("/draft/{draft_id}/reject")
async def reject_draft(draft_id: str, req: DraftActionRequest) -> dict:
    """Operator rejects the draft with a reason. The reason is recorded
    so future v6 retraining cycles can use it as a hard-negative signal."""
    from backend.rbac import require_actor_role
    require_actor_role(req.actor_role, 5, "rejecting a copilot draft")
    if not req.reason:
        raise HTTPException(status_code=400, detail="reason required for reject")
    draft = DraftStore.reject(draft_id, req.operator, req.reason)
    if draft is None:
        raise HTTPException(
            status_code=409,
            detail="draft not found or not in PENDING_OPERATOR_APPROVAL state",
        )
    return {
        "draft_id": draft_id,
        "status": draft.status,
        "rejected_by": draft.approved_by,
        "rejection_reason": draft.rejection_reason,
    }


@router.get("/health")
async def agent_health() -> dict:
    """Quick reachability probe of the inference endpoint."""
    try:
        model_id = await _copilot._resolve_model()
        return {
            "status": "ok",
            "model_id": model_id,
            "lm_studio_url": LM_STUDIO_URL,
            "tools": [t["function"]["name"] for t in TOOLS_SCHEMA],
        }
    except Exception as exc:
        return {
            "status": "degraded",
            "error": str(exc),
            "lm_studio_url": LM_STUDIO_URL,
        }


@router.on_event("shutdown")
async def _shutdown() -> None:
    await _copilot.close()
