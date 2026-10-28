"""Agentic investigator with tool loop, fixture, deterministic priority floor.

HACKATHON feature. The model investigates ONLY through five tools: four read
ONLY ``agent_fixture.py`` (never the incident store, never the network);
verify_photo checks an operator-uploaded panel photo against a MOP step via
the Meta API (bounded: 1 SAM + 5 crops + at most 5 retries, one daily-cap
attempt per use). Two loop limits are enforced in code: at least two
DIFFERENT tools before any final answer is accepted, and at most 8 model
calls per investigation.

The model never sets priority. Priority and suggested procedure come from
the fixed PRIORITY_TABLE below, raised by a severity floor computed in
code from the raw alarms the tools actually returned. Every cited
evidence id is validated against the tool results of THIS investigation;
anything else is marked unverified.

Real calls use the same Meta base URL and auth header as the probe
(``llm_providers.MetaProvider``) with model muse-spark-1.3,
reasoning_effort low, max_tokens 4000. No key is ever printed.
"""

from __future__ import annotations

import asyncio
import json

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

try:  # package import (backend.copilot_agent)
    from .agent_fixture import get_alarms, get_breaker, get_procedure, get_trend, list_scenarios
    from .copilot_limits import (
        MetaLimitError,
        check_limits,
        record_meta_attempt,
        retry_after_for_ip,
        seconds_until_utc_midnight,
    )
    from .llm_providers import MetaProvider
    from .mop_verify import (
        MopInputError,
        get_mop_steps,
        get_session,
        store_session_photo,
        validate_verify_inputs,
        verify_photo,
    )
except ImportError:  # top-level import, as backend/main.py does it
    from agent_fixture import (  # type: ignore[no-redef]  # type: ignore[no-redef]
        get_alarms,
        get_breaker,
        get_procedure,
        get_trend,
        list_scenarios,
    )
    from copilot_limits import (  # type: ignore[no-redef]
        MetaLimitError,
        check_limits,
        record_meta_attempt,
        retry_after_for_ip,
        seconds_until_utc_midnight,
    )
    from llm_providers import MetaProvider  # type: ignore[no-redef]
    from mop_verify import (  # type: ignore[no-redef]
        MopInputError,
        get_mop_steps,
        get_session,
        store_session_photo,
        validate_verify_inputs,
        verify_photo,
    )

MODEL = "muse-spark-1.3"
MAX_TOKENS = 4000
MAX_MODEL_CALLS = 8
MIN_DISTINCT_TOOLS = 2
TIMEOUT_S = 30.0

CLOSED_CAUSES = (
    "utility_loss",
    "ats_transfer_fault",
    "generator_fault",
    "ups_fault",
    "cooling_loss",
    "fire_event",
    "unknown",
)

# Fixed table: the model concludes a cause, this table decides the
# response. The severity floor below can only raise the priority,
# never lower it.
PRIORITY_TABLE: dict = {
    "utility_loss": ("P1", "MOP-ATS-MONTHLY-001"),
    "ats_transfer_fault": ("P2", "MOP-ATS-MONTHLY-001"),
    "generator_fault": ("P1", "NFPA110-TYPE10"),
    "ups_fault": ("P1", "T4-MOP-UPS-001"),
    "cooling_loss": ("P1", "EOP-COOLING-LOSS-001"),
    "fire_event": ("P1", "EOP-FIRE-001"),
    "unknown": ("P2", "SOP-DAILY-ROUNDS-001"),
}

_RANK = {"P1": 1, "P2": 2, "P3": 3}

SYSTEM_PROMPT = (
    "You are a forensic investigator for a data-center shift. "
    "You may ONLY use the tools provided: query_alarms, get_trend, "
    "get_breaker_state, lookup_procedure, verify_photo. verify_photo checks "
    "an operator-uploaded panel photo against one MOP step; it needs the "
    "session_id the photo was uploaded with and the step_id (0 means the "
    "initial state), and fails when no photo was uploaded for that session. "
    "Work only from what the tools "
    "return. Never invent alarms, readings, equipment, or times. "
    "Use at least two DIFFERENT tools before concluding. "
    "When the evidence supports a conclusion, answer with ONE JSON object "
    "and nothing else, using exactly these keys: probable_cause (one of "
    "utility_loss, ats_transfer_fault, generator_fault, ups_fault, "
    "cooling_loss, fire_event, unknown), confidence (high, medium, or low), "
    "claims (list of {text, evidence_ids}), unconfirmed (list of strings), "
    "verification_checklist (list of strings the operator must confirm "
    "in person). Every evidence id you cite must have appeared in a tool "
    "result; cite ids exactly as returned."
)

NUDGE_MORE_EVIDENCE = (
    "Conclusion rejected: you have not used at least two different tools "
    "yet. Call more tools and gather evidence first; do not conclude now."
)

NUDGE_BAD_JSON = (
    "Your answer was not a single JSON object with the required keys. "
    "Answer again with exactly one JSON object and nothing else."
)

CHECKLIST_SYSTEM_PROMPT = (
    "You are planning a forensic investigation for a data-center shift. "
    "Before using any tool, write the investigation checklist. Answer with "
    "ONE JSON object and nothing else, using exactly these keys: "
    "working_hypothesis (one of utility_loss, ats_transfer_fault, "
    "generator_fault, ups_fault, cooling_loss, fire_event, unknown; "
    "a non-binding first guess) and checklist (4 to 6 items). Each item "
    "has exactly these keys: id (CHK-01, CHK-02, and so on), question, "
    "evidence_needed, is_counter_evidence (boolean). Every question must "
    "be answerable from ONLY these evidence sources: raw alarms (id, "
    "source, severity, title, timestamp), measurement trend series, "
    "breaker open/closed states with last-change times, or reference "
    "procedure texts. At least one item must be counter-evidence: a "
    "question whose answer could weaken or rule out the "
    "working_hypothesis. Do not use background knowledge. Do not invent "
    "alarms, readings, equipment, or times."
)

NUDGE_BAD_CHECKLIST = (
    "That checklist was invalid. I need exactly one JSON object with "
    "working_hypothesis from the closed list and 4 to 6 items, each with "
    "a unique id, a non-empty question and evidence_needed, and "
    "is_counter_evidence boolean, with at least one counter-evidence "
    "item true. Answer again with exactly one JSON object and nothing else."
)

TOOL_SCHEMAS: list = [
    {
        "type": "function",
        "function": {
            "name": "query_alarms",
            "description": "Raw alarms of one scenario inside a time window.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scenario_id": {"type": "string"},
                    "window_minutes": {"type": "number"},
                },
                "required": ["scenario_id", "window_minutes"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_trend",
            "description": "Short time series for one measurement point.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scenario_id": {"type": "string"},
                    "point_id": {"type": "string"},
                },
                "required": ["scenario_id", "point_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_breaker_state",
            "description": "Open/closed state and last change time of one breaker.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scenario_id": {"type": "string"},
                    "breaker_id": {"type": "string"},
                },
                "required": ["scenario_id", "breaker_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_procedure",
            "description": "Reference procedure text for one event type.",
            "parameters": {
                "type": "object",
                "properties": {"event_type": {"type": "string"}},
                "required": ["event_type"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify_photo",
            "description": (
                "Verify an operator-uploaded panel photo against one MOP step. "
                "Needs the session_id the photo was uploaded with and the step_id "
                "(0 means the initial state). Fails when no photo was uploaded."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "step_id": {"type": "integer"},
                    "operator_claim": {"type": "string"},
                },
                "required": ["session_id", "step_id"],
                "additionalProperties": False,
            },
        },
    },
]


class MetaAgentError(Exception):
    """Transport failure talking to the Meta API (key, HTTP, network)."""


class MetaAgentClient:
    """Synchronous tool-calling client (same URL/auth as the probe)."""

    def __init__(self, model: str = MODEL, max_tokens: int = MAX_TOKENS):
        provider = MetaProvider()
        if not provider.is_configured:
            raise MetaAgentError("Meta API key not configured")
        self.url = f"{provider.api_url}/chat/completions"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {provider.api_key}",
        }
        self.model = model
        self.max_tokens = max_tokens

    def chat(self, messages: list, tools: list | None) -> dict:
        """One POST, one attempt, no retries. Returns the decoded body.

        When tools is None the tools array (and tool_choice) is omitted:
        that shape is used only for the checklist call.
        """
        payload: dict = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "reasoning_effort": "low",
            "stream": False,
            "messages": messages,
        }
        if tools is not None:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            resp = httpx.post(self.url, json=payload, headers=self.headers, timeout=TIMEOUT_S)
        except Exception as e:
            raise MetaAgentError(f"{type(e).__name__}: {e}") from e
        if resp.status_code != 200:
            raise MetaAgentError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except Exception as e:
            raise MetaAgentError(f"non-JSON body: {e}") from e
        if not isinstance(data, dict):
            raise MetaAgentError("JSON body is not an object")
        return data


def tool_query_alarms(arguments: dict) -> dict:
    """Raw alarms with id, source, severity, title, timestamp."""
    scenario_id = arguments.get("scenario_id", "")
    try:
        window = float(arguments.get("window_minutes", 0))
    except (TypeError, ValueError):
        return {"error": "window_minutes must be a number"}
    rows = get_alarms(scenario_id, window)
    if not rows and scenario_id not in list_scenarios():
        return {"error": f"unknown scenario '{scenario_id}'"}
    return {"scenario_id": scenario_id, "alarms": rows}


def tool_get_trend(arguments: dict) -> dict:
    """Short time series for one point."""
    scenario_id = arguments.get("scenario_id", "")
    point_id = arguments.get("point_id", "")
    trend = get_trend(scenario_id, point_id)
    if not trend:
        return {"error": f"unknown scenario/point '{scenario_id}/{point_id}'"}
    return {"scenario_id": scenario_id, "point_id": point_id, **trend}


def tool_get_breaker_state(arguments: dict) -> dict:
    """Open/closed state and last change time of one breaker."""
    scenario_id = arguments.get("scenario_id", "")
    breaker_id = arguments.get("breaker_id", "")
    state = get_breaker(scenario_id, breaker_id)
    if not state:
        return {"error": f"unknown scenario/breaker '{scenario_id}/{breaker_id}'"}
    return {"scenario_id": scenario_id, "breaker_id": breaker_id, **state}


def tool_lookup_procedure(arguments: dict) -> dict:
    """Reference procedure text for one event type."""
    event_type = arguments.get("event_type", "")
    procedure = get_procedure(event_type)
    if not procedure:
        return {"error": f"unknown event type '{event_type}'"}
    return {"event_type": event_type, **procedure}


def tool_verify_photo(arguments: dict) -> dict:
    """Verify a session photo against one MOP step (verdict computed in code)."""
    session_id = arguments.get("session_id", "")
    session_id = session_id.strip() if isinstance(session_id, str) else ""
    if not session_id:
        return {"error": "session_id is required"}
    raw_step = arguments.get("step_id")
    if isinstance(raw_step, bool) or not isinstance(raw_step, int | float):
        return {"error": "step_id must be an integer 0-5"}
    step_id = int(raw_step)
    if float(raw_step) != step_id or step_id not in (0, 1, 2, 3, 4, 5):
        return {"error": "step_id must be an integer 0-5"}
    claim = arguments.get("operator_claim")
    claim = claim if isinstance(claim, str) and claim.strip() else None
    session = get_session(session_id)
    if not session.pending_image:
        return {"error": f"no photo stored for session '{session_id}'"}
    try:
        result = verify_photo(
            step_id, session.pending_image, operator_claim=claim, session_id=session_id
        )
    except MopInputError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        return {"error": f"verification failed: {exc}"}
    evidence_ids = [f"mop-step-{step_id}-{label}" for label in result["readings"]]
    return {
        "verdict": result["verdict"],
        "differing_labels": result["differing_labels"],
        "readings": {
            label: {"mapped": reading["mapped"], "crop_box": reading["crop_box"]}
            for label, reading in result["readings"].items()
        },
        "contradiction": result["contradiction"],
        "expected_state": result["expected_state"],
        "evidence_ids": evidence_ids,
        "session": result["session"],
        "meta_calls_made": result["meta_calls_made"],
    }


_TOOL_FNS = {
    "query_alarms": tool_query_alarms,
    "get_trend": tool_get_trend,
    "get_breaker_state": tool_get_breaker_state,
    "lookup_procedure": tool_lookup_procedure,
    "verify_photo": tool_verify_photo,
}


class _Investigation:
    """Mutable per-run state: evidence ids, severities, tool usage."""

    def __init__(self, scenario_id: str):
        self.scenario_id = scenario_id
        self.calls = 0
        self.tools_used: set = set()
        self.evidence_ids: set = set()
        self.severities: list = []
        self.early_rejections = 0
        self.checklist: dict | None = None

    def record_tool_result(self, name: str, result: dict) -> None:
        self.tools_used.add(name)
        if name == "query_alarms":
            for alarm in result.get("alarms", []):
                if alarm.get("id"):
                    self.evidence_ids.add(alarm["id"])
                if alarm.get("severity"):
                    self.severities.append(alarm["severity"])
        elif name == "get_trend" and result.get("point_id"):
            self.evidence_ids.add(result["point_id"])
        elif name == "get_breaker_state" and result.get("breaker_id"):
            self.evidence_ids.add(result["breaker_id"])
        elif name == "lookup_procedure" and result.get("procedure_id"):
            self.evidence_ids.add(result["procedure_id"])
        elif name == "verify_photo":
            for evidence_id in result.get("evidence_ids", []):
                if evidence_id:
                    self.evidence_ids.add(evidence_id)


def _severity_floor(severities: list) -> str:
    """P1 floor on any critical/high alarm, P2 on any medium, else P3."""
    lowered = {str(s).strip().lower() for s in severities}
    if lowered & {"critical", "high"}:
        return "P1"
    if "medium" in lowered:
        return "P2"
    return "P3"


def _higher_priority(first: str, second: str) -> str:
    """The more urgent of two priorities (P1 > P2 > P3)."""
    if _RANK.get(first, 3) <= _RANK.get(second, 3):
        return first
    return second


def _parse_final(text: str) -> dict | None:
    """Extract the single JSON object from a final-answer message."""
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _validate_checklist(data: dict | None) -> dict | None:
    """Validate a checklist response in code. Stored form or None.

    Rules: working_hypothesis in the closed list; 4 to 6 items; unique
    ids; every item with non-empty question and evidence_needed;
    is_counter_evidence strictly boolean; at least one counter-evidence
    item true. A probable_cause field, if present, is ignored.
    The checklist is never fabricated or auto-completed here.
    """
    if not isinstance(data, dict):
        return None
    if data.get("working_hypothesis") not in CLOSED_CAUSES:
        return None
    items = data.get("checklist")
    if not isinstance(items, list) or not 4 <= len(items) <= 6:
        return None
    seen: set = set()
    stored = []
    for item in items:
        if not isinstance(item, dict):
            return None
        item_id = item.get("id")
        question = item.get("question")
        needed = item.get("evidence_needed")
        counter = item.get("is_counter_evidence")
        if not isinstance(item_id, str) or not item_id or item_id in seen:
            return None
        if not isinstance(question, str) or not question.strip():
            return None
        if not isinstance(needed, str) or not needed.strip():
            return None
        if not isinstance(counter, bool):
            return None
        seen.add(item_id)
        stored.append(
            {
                "id": item_id,
                "question": question,
                "evidence_needed": needed,
                "is_counter_evidence": counter,
            }
        )
    if not any(entry["is_counter_evidence"] for entry in stored):
        return None
    return {"working_hypothesis": data["working_hypothesis"], "items": stored}


def _finalize(state: _Investigation, final: dict) -> dict:
    """Validate the model conclusion in code and attach the safety layer."""
    cause = final.get("probable_cause")
    notes = []
    if cause not in CLOSED_CAUSES:
        notes.append(f"cause {cause!r} outside the closed list, mapped to unknown")
        cause = "unknown"
    confidence = final.get("confidence")
    if confidence not in ("high", "medium", "low"):
        notes.append(f"confidence {confidence!r} invalid, set to low")
        confidence = "low"
    claims = []
    for claim in final.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        ids = claim.get("evidence_ids") or []
        verified = bool(ids) and all(i in state.evidence_ids for i in ids)
        claims.append(
            {
                "text": claim.get("text", ""),
                "evidence_ids": list(ids),
                "verified": verified,
            }
        )
    checklist = final.get("verification_checklist") or []
    if not checklist:
        checklist = ["Verify the affected equipment in person before closing the story."]
    stored_items = (state.checklist or {}).get("items", [])
    stored_by_id = {item["id"]: item for item in stored_items}
    inv_list = []
    seen_ids: set = set()
    discarded = []
    for entry in final.get("investigation_checklist") or []:
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id")
        if entry_id in seen_ids:
            continue
        if entry_id not in stored_by_id:
            discarded.append(entry_id)
            continue
        seen_ids.add(entry_id)
        stored = stored_by_id[entry_id]
        raw_cited = entry.get("cited_evidence_ids") or []
        raw_cited = raw_cited if isinstance(raw_cited, list) else []
        valid = [i for i in raw_cited if i in state.evidence_ids]
        status = entry.get("status")
        if status not in ("settled", "contradicted", "not_settled"):
            status = "not_settled"
        if status in ("settled", "contradicted") and (not valid or len(valid) != len(raw_cited)):
            status = "not_settled"
        inv_list.append(
            {
                "id": entry_id,
                "question": stored["question"],
                "is_counter_evidence": stored["is_counter_evidence"],
                "status": status,
                "cited_evidence_ids": valid,
            }
        )
    for item in stored_items:
        if item["id"] not in seen_ids:
            inv_list.append(
                {
                    "id": item["id"],
                    "question": item["question"],
                    "is_counter_evidence": item["is_counter_evidence"],
                    "status": "not_settled",
                    "cited_evidence_ids": [],
                }
            )
    unconfirmed = list(final.get("unconfirmed") or [])
    rank = {"high": 3, "medium": 2, "low": 1}
    if rank.get(confidence, 1) > 2 and any(
        e["is_counter_evidence"] and e["status"] == "not_settled" for e in inv_list
    ):
        confidence = "medium"
        notes.append("confidence capped at medium: a counter-evidence item is not settled")
    contradicted = [e for e in inv_list if e["status"] == "contradicted"]
    if contradicted:
        confidence = "low"
        for entry in contradicted:
            unconfirmed.append(f"Contradicted checklist item {entry['id']}: {entry['question']}")
        notes.append("confidence capped at low: a checklist item was contradicted")
    working_hypothesis = (state.checklist or {}).get("working_hypothesis")
    notes.append(
        "working_hypothesis is non-binding: it never sets priority, procedure, or probable_cause"
    )
    table_priority, procedure = PRIORITY_TABLE[cause]
    floor = _severity_floor(state.severities)
    priority = _higher_priority(table_priority, floor)
    if priority != table_priority:
        notes.append(f"severity floor {floor} raised table priority {table_priority}")
    return {
        "scenario_id": state.scenario_id,
        "probable_cause": cause,
        "confidence": confidence,
        "priority": priority,
        "suggested_procedure": procedure,
        "claims": claims,
        "unconfirmed": unconfirmed,
        "verification_checklist": list(checklist),
        "investigation_checklist": inv_list,
        "working_hypothesis": working_hypothesis,
        "discarded_checklist_ids": discarded,
        "model_calls": state.calls,
        "tools_used": sorted(state.tools_used),
        "early_rejections": state.early_rejections,
        "notes": notes,
    }


def _checklist_view(state: _Investigation) -> tuple:
    """Stored checklist as not-settled entries, hypothesis, no discards."""
    stored = state.checklist or {"working_hypothesis": None, "items": []}
    inv_list = [
        {
            "id": item["id"],
            "question": item["question"],
            "is_counter_evidence": item["is_counter_evidence"],
            "status": "not_settled",
            "cited_evidence_ids": [],
        }
        for item in stored.get("items", [])
    ]
    return inv_list, stored.get("working_hypothesis"), []


def _cap_result(state: _Investigation) -> dict:
    """Iteration cap reached: stop with confidence low and cause unknown."""
    table_priority, procedure = PRIORITY_TABLE["unknown"]
    priority = _higher_priority(table_priority, _severity_floor(state.severities))
    inv_list, working_hypothesis, discarded = _checklist_view(state)
    return {
        "scenario_id": state.scenario_id,
        "probable_cause": "unknown",
        "confidence": "low",
        "priority": priority,
        "suggested_procedure": procedure,
        "claims": [],
        "unconfirmed": ["Investigation stopped at the iteration cap."],
        "verification_checklist": [
            "Verify the affected equipment in person before closing the story."
        ],
        "investigation_checklist": inv_list,
        "working_hypothesis": working_hypothesis,
        "discarded_checklist_ids": discarded,
        "model_calls": state.calls,
        "tools_used": sorted(state.tools_used),
        "early_rejections": state.early_rejections,
        "notes": [f"stopped after {MAX_MODEL_CALLS} model calls"],
    }


def _invalid_checklist_result(state: _Investigation) -> dict:
    """Checklist still invalid after regeneration: unknown and low."""
    table_priority, procedure = PRIORITY_TABLE["unknown"]
    priority = _higher_priority(table_priority, _severity_floor(state.severities))
    return {
        "scenario_id": state.scenario_id,
        "probable_cause": "unknown",
        "confidence": "low",
        "priority": priority,
        "suggested_procedure": procedure,
        "claims": [],
        "unconfirmed": ["Checklist invalid after regeneration."],
        "verification_checklist": [
            "Verify the affected equipment in person before closing the story."
        ],
        "investigation_checklist": [],
        "working_hypothesis": None,
        "discarded_checklist_ids": [],
        "model_calls": state.calls,
        "tools_used": sorted(state.tools_used),
        "early_rejections": state.early_rejections,
        "notes": ["checklist invalid after regeneration; stopped with cause unknown"],
    }


def _error_result(scenario_id: str, note: str) -> dict:
    """Transport failure: unknown/low without spending further calls."""
    return {
        "scenario_id": scenario_id,
        "probable_cause": "unknown",
        "confidence": "low",
        "priority": "P2",
        "suggested_procedure": PRIORITY_TABLE["unknown"][1],
        "claims": [],
        "unconfirmed": [note],
        "verification_checklist": [
            "Verify the affected equipment in person before closing the story."
        ],
        "investigation_checklist": [],
        "working_hypothesis": None,
        "discarded_checklist_ids": [],
        "model_calls": 0,
        "tools_used": [],
        "early_rejections": 0,
        "notes": [note],
    }


def _execute_tool_call(call: dict) -> dict:
    """Run one model-requested tool call against the fixture only."""
    func = call.get("function") or {}
    name = func.get("name", "")
    try:
        arguments = json.loads(func.get("arguments") or "{}")
    except (ValueError, TypeError):
        arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}
    handler = _TOOL_FNS.get(name)
    if handler is None:
        return {"error": f"unknown tool '{name}'"}
    return handler(arguments)


def run_investigation(scenario_id: str, client=None, max_calls: int = MAX_MODEL_CALLS) -> dict:
    """Run the tool loop for one scenario and return the validated answer.

    A fake client with the same ``chat(messages, tools)`` shape can be
    injected for offline tests (no network, no credits).
    """
    if scenario_id not in list_scenarios():
        return _error_result(scenario_id, f"unknown scenario '{scenario_id}'")
    if client is None:
        try:
            client = MetaAgentClient()
        except MetaAgentError as e:
            return _error_result(scenario_id, str(e))
    state = _Investigation(scenario_id)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Investigate scenario '{scenario_id}'. Start with query_alarms "
                "for the first 10 minutes, then follow the evidence."
            ),
        },
    ]
    checklist_messages = [
        {"role": "system", "content": CHECKLIST_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Write the investigation checklist for scenario '{scenario_id}'. "
                "Answer with exactly one JSON object and nothing else."
            ),
        },
    ]
    regenerated = False
    while True:
        if state.calls >= max_calls:
            return _invalid_checklist_result(state)
        try:
            checklist_response = client.chat(checklist_messages, None)
            content = checklist_response["choices"][0]["message"].get("content") or ""
        except (MetaAgentError, KeyError, IndexError, TypeError) as e:
            return _error_result(scenario_id, f"investigation failed: {e}")
        state.calls += 1
        validated = _validate_checklist(_parse_final(content))
        if validated is not None:
            state.checklist = validated
            break
        if regenerated:
            return _invalid_checklist_result(state)
        regenerated = True
        checklist_messages.append({"role": "user", "content": NUDGE_BAD_CHECKLIST})
    try:
        while state.calls < max_calls:
            response = client.chat(messages, TOOL_SCHEMAS)
            state.calls += 1
            message = response["choices"][0]["message"]
            tool_calls = message.get("tool_calls") or []
            if tool_calls:
                # The assistant message itself must travel with its tool
                # results, verbatim: Meta rejects a tool message whose
                # tool_call_id has no matching assistant tool_calls (400).
                messages.append(message)
                for call in tool_calls:
                    result = _execute_tool_call(call)
                    state.record_tool_result(call.get("function", {}).get("name", ""), result)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id", ""),
                            "content": json.dumps(result),
                        }
                    )
                continue
            final = _parse_final(message.get("content") or "")
            if final is None:
                messages.append({"role": "user", "content": NUDGE_BAD_JSON})
                continue
            if len(state.tools_used) < MIN_DISTINCT_TOOLS:
                state.early_rejections += 1
                messages.append({"role": "user", "content": NUDGE_MORE_EVIDENCE})
                continue
            return _finalize(state, final)
    except (MetaAgentError, KeyError, IndexError, TypeError) as e:
        return _error_result(scenario_id, f"investigation failed: {e}")
    return _cap_result(state)


agent_router = APIRouter(prefix="/api/copilot", tags=["shift-agentic-investigator"])


class AgentInvestigateIn(BaseModel):
    scenario: str


class _CountingClient:
    """One daily-cap attempt per investigation plus the ordered tool trace.

    Records when the FIRST Meta call is about to happen; the remaining
    iterations of the same investigation record nothing (the 8-call
    iteration cap bounds the cost). The loop itself is untouched.
    """

    def __init__(self, inner):
        self._inner = inner
        self.counted = False
        self.trace: list = []

    def chat(self, messages: list, tools: list) -> dict:
        if not self.counted:
            record_meta_attempt()
            self.counted = True
        response: dict = self._inner.chat(messages, tools)
        message = (response.get("choices") or [{}])[0].get("message") or {}
        for call in message.get("tool_calls") or []:
            func = call.get("function") or {}
            try:
                arguments = json.loads(func.get("arguments") or "{}")
            except (ValueError, TypeError):
                arguments = {}
            self.trace.append({"tool": func.get("name"), "arguments": arguments})
        return response


@agent_router.post("/agent-investigate")
async def copilot_agent_investigate(payload: AgentInvestigateIn, request: Request):
    """Agentic investigation over the fixture, guarded like /investigate.

    Guard runs FIRST: unknown scenario -> 400, exceeded cap/rate -> 429
    with no Meta call. Missing key or Meta failure -> 503, never a
    fabricated investigation (the agent has no deterministic fallback).
    """
    scenario_id = (payload.scenario or "").strip()
    if scenario_id not in list_scenarios():
        return JSONResponse(
            status_code=400,
            content={
                "error": "unknown_scenario",
                "detail": f"Unknown scenario '{scenario_id}'.",
                "known_scenarios": list_scenarios(),
            },
        )
    client_ip = request.client.host if request.client else "unknown"
    try:
        check_limits(client_ip)
    except MetaLimitError as exc:
        if exc.limit == "daily_cap":
            retry_after_s = seconds_until_utc_midnight()
        else:
            retry_after_s = retry_after_for_ip(client_ip)
        return JSONResponse(
            status_code=429,
            content={
                "error": "limit_exceeded",
                "limit": exc.limit,
                "detail": exc.message,
                "daily_cap": exc.daily_cap,
                "meta_call_made": False,
                "retry_after_s": retry_after_s,
            },
            headers={"Retry-After": str(retry_after_s)},
        )
    try:
        inner = MetaAgentClient()
    except MetaAgentError as exc:
        return JSONResponse(
            status_code=503,
            content={
                "error": "meta_unavailable",
                "detail": str(exc),
                "meta_call_made": False,
            },
        )
    client = _CountingClient(inner)
    try:
        result = await asyncio.to_thread(run_investigation, scenario_id, client)
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={
                "error": "meta_unavailable",
                "detail": f"investigation failed: {exc}",
                "meta_call_made": client.counted,
            },
        )
    if result.get("model_calls", 0) == 0:
        reason = "; ".join(result.get("notes") or result.get("unconfirmed") or ["Meta call failed"])
        return JSONResponse(
            status_code=503,
            content={
                "error": "meta_unavailable",
                "detail": reason,
                "meta_call_made": client.counted,
            },
        )
    cited = sorted(
        {i for claim in result.get("claims", []) for i in (claim.get("evidence_ids") or [])}
    )
    return JSONResponse(
        {
            "feature": "shift-agentic-investigator",
            "built_during_hackathon": True,
            "source": "meta",
            "model": MODEL,
            "scenario": scenario_id,
            "probable_cause": result["probable_cause"],
            "confidence": result["confidence"],
            "priority": result["priority"],
            "suggested_procedure": result["suggested_procedure"],
            "verification_checklist": result["verification_checklist"],
            "investigation_checklist": result["investigation_checklist"],
            "working_hypothesis": result["working_hypothesis"],
            "discarded_checklist_ids": result["discarded_checklist_ids"],
            "tool_calls": client.trace,
            "evidence_ids_cited": cited,
            "model_calls": result["model_calls"],
            "meta_call_made": True,
            "investigation": result,
        }
    )


def _limit_exceeded_response(exc: MetaLimitError, client_ip: str) -> JSONResponse:
    """429 body identical to the agent endpoint (guard shared by MOP routes)."""
    if exc.limit == "daily_cap":
        retry_after_s = seconds_until_utc_midnight()
    else:
        retry_after_s = retry_after_for_ip(client_ip)
    return JSONResponse(
        status_code=429,
        content={
            "error": "limit_exceeded",
            "limit": exc.limit,
            "detail": exc.message,
            "daily_cap": exc.daily_cap,
            "meta_call_made": False,
            "retry_after_s": retry_after_s,
        },
        headers={"Retry-After": str(retry_after_s)},
    )


def _bad_verify_request(detail: str) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": "invalid_request", "detail": detail})


@agent_router.post("/mop/verify")
async def copilot_mop_verify(request: Request):
    """Verify a training-panel photo against one MOP step.

    Multipart fields: image (photo bytes), step_id (0-5, 0 is the initial
    state), session_id, optional operator_claim text. Guarded exactly
    like /agent-investigate: bad input -> 400 before the guard, exceeded
    cap/rate -> 429 with no Meta call, missing key or Meta failure ->
    503. One verify counts as one daily-cap Meta attempt, recorded
    right before the SAM call inside verify_photo.
    """
    form = await request.form()
    upload = form.get("image")
    if upload is None or isinstance(upload, str):
        return _bad_verify_request("multipart field 'image' with an uploaded photo is required")
    image_bytes = await upload.read()
    raw_step = form.get("step_id")
    try:
        step_id = int(str(raw_step).strip())
    except (TypeError, ValueError):
        return _bad_verify_request("step_id must be an integer 0-5")
    raw_session = form.get("session_id")
    if not isinstance(raw_session, str) or not raw_session.strip():
        return _bad_verify_request("session_id must be a non-empty string")
    session_id = raw_session.strip()
    raw_claim = form.get("operator_claim")
    if raw_claim is not None and not isinstance(raw_claim, str):
        return _bad_verify_request("operator_claim must be text when given")
    operator_claim = raw_claim.strip() if isinstance(raw_claim, str) and raw_claim.strip() else None
    try:
        validate_verify_inputs(step_id, image_bytes, session_id)
    except MopInputError as exc:
        return _bad_verify_request(str(exc))
    client_ip = request.client.host if request.client else "unknown"
    try:
        check_limits(client_ip)
    except MetaLimitError as exc:
        return _limit_exceeded_response(exc, client_ip)
    try:
        MetaAgentClient()  # key check only; mop_verify builds its own requests
    except MetaAgentError as exc:
        return JSONResponse(
            status_code=503,
            content={"error": "meta_unavailable", "detail": str(exc), "meta_call_made": False},
        )
    store_session_photo(session_id, image_bytes)
    try:
        result = await asyncio.to_thread(
            verify_photo, step_id, image_bytes, operator_claim, session_id
        )
    except MopInputError as exc:
        return _bad_verify_request(str(exc))
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={
                "error": "meta_unavailable",
                "detail": f"verification failed: {exc}",
                "meta_call_made": True,
            },
        )
    return JSONResponse({**result, "meta_call_made": True})


@agent_router.get("/mop/steps")
async def copilot_mop_steps(request: Request):
    """MOP steps for the UI. Same guard/429 as the agent endpoint.

    Static data: never records a daily-cap attempt and has no 503 path
    (nothing here depends on Meta).
    """
    client_ip = request.client.host if request.client else "unknown"
    try:
        check_limits(client_ip)
    except MetaLimitError as exc:
        return _limit_exceeded_response(exc, client_ip)
    return JSONResponse(get_mop_steps())
