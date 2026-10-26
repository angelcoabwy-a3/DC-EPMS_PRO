"""Shift Copilot - facility shift assistant loop.

Pipeline:
    ingest incidents -> correlate into stories -> triage by criticality
    -> draft MOP-style log entries -> shift handover report.

Self-contained: keeps its own in-memory incident store so the copilot
works in Tier 1 (no Postgres required). All state is demo-local and
resets on process restart.

Mount: ``app.include_router(router)`` in backend/main.py
(see the agent_copilot mount block for the pattern).
"""

from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/copilot", tags=["shift-copilot"])

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

_SEVERITY_ALIASES = {
    "info": "info",
    "warning": "warning",
    "warn": "warning",
    "critical": "critical",
    "crit": "critical",
}

_SEVERITY_WEIGHT = {"info": 1, "warning": 2, "critical": 3}

# Correlation window: alarms from the same source inside this window
# are treated as one incident story (alarm flood -> single narrative).
CORRELATION_WINDOW = timedelta(minutes=15)

# Keyword -> procedure reference for the MOP log draft. These IDs match
# the procedure library loaded by procedure_engine at boot.
PROCEDURE_MAP = [
    ("chiller", "T4-MOP-CHI-001"),
    ("crah", "EOP-COOLING-LOSS-001"),
    ("cooling", "EOP-COOLING-LOSS-001"),
    ("ups", "T4-MOP-UPS-001"),
    ("battery", "T4-MOP-UPS-001"),
    ("ats", "MOP-ATS-MONTHLY-001"),
    ("generator", "NFPA 110 Type 10 - emergency power"),
    ("rectifier", "DEMO-RECTIFIER-UNDER-PPE"),
    ("fire", "EOP - fire response"),
    ("vesda", "EOP - fire response"),
]


class IncidentIn(BaseModel):
    incident_id: str | None = None
    source: str = "UNKNOWN"
    title: str = "untitled"
    detail: str = ""
    severity: str = Field(default="info")
    status: str = Field(default="OPEN")
    # minutes_ago lets the demo injector backdate incidents realistically
    minutes_ago: float = Field(default=0.0, ge=0.0)


class SimulateIn(BaseModel):
    scenario: str = Field(
        default="utility_failure",
        pattern="^(utility_failure|chiller_fail|random_burst)$",
    )
    count: int = Field(default=8, ge=1, le=40)


@dataclass
class Incident:
    incident_id: str
    source: str
    title: str
    detail: str
    severity: str  # info | warning | critical (normalized)
    status: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Store (thread-safe, in-memory)
# ---------------------------------------------------------------------------

_store: list[Incident] = []
_store_lock = threading.Lock()
_last_handover: dict | None = None


def _normalize_severity(raw: str) -> str:
    return _SEVERITY_ALIASES.get(str(raw).strip().lower(), "info")


def ingest(payload: IncidentIn) -> Incident:
    inc = Incident(
        incident_id=payload.incident_id or f"INC-{uuid.uuid4().hex[:8].upper()}",
        source=payload.source.strip().upper() or "UNKNOWN",
        title=payload.title.strip() or "untitled",
        detail=payload.detail,
        severity=_normalize_severity(payload.severity),
        status=payload.status.strip().upper() or "OPEN",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=payload.minutes_ago),
    )
    with _store_lock:
        _store.append(inc)
    return inc


def list_incidents(severity: str | None = None) -> list[Incident]:
    with _store_lock:
        rows = list(_store)
    if severity:
        sev = _normalize_severity(severity)
        rows = [r for r in rows if r.severity == sev]
    return sorted(rows, key=lambda r: r.created_at)


def clear_incidents() -> int:
    with _store_lock:
        n = len(_store)
        _store.clear()
    return n


# ---------------------------------------------------------------------------
# Correlation: alarm flood -> one incident story
# ---------------------------------------------------------------------------

def correlate(rows: list[Incident]) -> list[dict]:
    """Group incidents from the same source inside CORRELATION_WINDOW."""
    stories: list[dict] = []
    for inc in sorted(rows, key=lambda r: r.created_at):
        placed = False
        for story in stories:
            same_source = story["source"] == inc.source
            within_window = inc.created_at - story["last_at"] <= CORRELATION_WINDOW
            if same_source and within_window:
                story["incidents"].append(inc)
                story["last_at"] = inc.created_at
                placed = True
                break
        if not placed:
            stories.append(
                {
                    "story_id": f"STY-{len(stories) + 1:03d}",
                    "source": inc.source,
                    "incidents": [inc],
                    "first_at": inc.created_at,
                    "last_at": inc.created_at,
                }
            )
    return stories


# ---------------------------------------------------------------------------
# Triage: criticality scoring -> P1/P2/P3
# ---------------------------------------------------------------------------

def triage(story: dict) -> dict:
    incidents = story["incidents"]
    max_weight = max(_SEVERITY_WEIGHT[i.severity] for i in incidents)
    count = len(incidents)
    # Recency boost: stories active in the last 30 min score higher.
    age_min = (datetime.now(timezone.utc) - story["last_at"]).total_seconds() / 60
    recency = 1.5 if age_min <= 30 else 1.0
    score = round(max_weight * (1 + 0.5 * (count - 1)) * recency, 2)
    priority = "P1" if score >= 6 else "P2" if score >= 3 else "P3"
    severities = sorted(
        {i.severity for i in incidents},
        key=lambda s: _SEVERITY_WEIGHT[s],
        reverse=True,
    )
    return {
        "story_id": story["story_id"],
        "source": story["source"],
        "priority": priority,
        "score": score,
        "incident_count": count,
        "top_severity": severities[0],
        "first_at": story["first_at"].isoformat(),
        "last_at": story["last_at"].isoformat(),
        "titles": [i.title for i in incidents],
    }


# ---------------------------------------------------------------------------
# MOP-style log draft
# ---------------------------------------------------------------------------

def _suggest_procedure(text: str) -> str:
    lowered = text.lower()
    for keyword, proc in PROCEDURE_MAP:
        if keyword in lowered:
            return proc
    return "SOP-DAILY-ROUNDS-001"


def _root_cause_hint(incidents: list[Incident]) -> str:
    words: dict[str, int] = {}
    stop = {"the", "a", "an", "on", "of", "to", "in", "and", "for", "with"}
    for inc in incidents:
        for tok in re.findall(r"[a-zA-Z][a-zA-Z0-9-]{2,}", inc.title.lower()):
            if tok not in stop:
                words[tok] = words.get(tok, 0) + 1
    top = sorted(words.items(), key=lambda kv: kv[1], reverse=True)[:3]
    return ", ".join(w for w, _ in top) if top else incidents[0].source.lower()


def draft_mop_log(triage_result: dict, story: dict) -> dict:
    incidents = story["incidents"]
    blob = " ".join(i.title + " " + i.detail for i in incidents)
    procedure = _suggest_procedure(blob)
    actions = []
    if triage_result["top_severity"] == "critical":
        actions.append("Acknowledge alarms and verify affected equipment in person.")
        actions.append("Follow the referenced procedure before any switching operation.")
    if triage_result["incident_count"] > 3:
        actions.append(
            "Alarm flood pattern: treat as a single event, avoid "
            "acknowledging alarms one by one."
        )
    actions.append("Log all actions taken with timestamps for the shift record.")
    return {
        "story_id": triage_result["story_id"],
        "priority": triage_result["priority"],
        "window": f"{triage_result['first_at']} -> {triage_result['last_at']}",
        "source": triage_result["source"],
        "summary": (
            f"{triage_result['incident_count']} alarms from {triage_result['source']} "
            f"correlated into one event (root-cause hint: "
            f"{_root_cause_hint(incidents)})."
        ),
        "incident_ids": [i.incident_id for i in incidents],
        "suggested_procedure": procedure,
        "recommended_actions": actions,
    }


# ---------------------------------------------------------------------------
# Handover report
# ---------------------------------------------------------------------------

def build_handover(analysis: dict) -> dict:
    now = datetime.now(timezone.utc)
    stories = analysis["stories"]
    p1 = [s for s in stories if s["triage"]["priority"] == "P1"]
    lines = [
        "# Shift Handover Report",
        f"Generated: {now.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"Incidents reviewed: {analysis['incident_count']}",
        f"Correlated stories: {len(stories)}",
        f"P1: {len(p1)} | "
        f"P2: {len([s for s in stories if s['triage']['priority'] == 'P2'])} | "
        f"P3: {len([s for s in stories if s['triage']['priority'] == 'P3'])}",
        "",
    ]
    if p1:
        lines.append("## Immediate attention (P1)")
        for s in p1:
            lines.append(
                f"- [{s['triage']['story_id']}] {s['mop_log']['summary']} "
                f"Procedure: {s['mop_log']['suggested_procedure']}"
            )
        lines.append("")
    lines.append("## Stories")
    for s in sorted(stories, key=lambda x: x["triage"]["score"], reverse=True):
        t = s["triage"]
        lines.append(
            f"- {t['story_id']} [{t['priority']}] {t['source']}: "
            f"{t['incident_count']} alarms, top severity {t['top_severity']}"
        )
    lines.append("")
    lines.append("## Carry-over")
    open_p1_p2 = [s for s in stories if s["triage"]["priority"] in ("P1", "P2")]
    if open_p1_p2:
        lines.append(
            f"{len(open_p1_p2)} stories need follow-up next shift "
            f"({', '.join(s['triage']['story_id'] for s in open_p1_p2)})."
        )
    else:
        lines.append("No pending critical items. Routine rounds continue.")
    return {
        "generated_at": now.isoformat(),
        "incident_count": analysis["incident_count"],
        "story_count": len(stories),
        "markdown": "\n".join(lines),
        "stories": [
            {
                "story_id": s["triage"]["story_id"],
                "priority": s["triage"]["priority"],
                "mop_log": s["mop_log"],
            }
            for s in stories
        ],
    }


def run_analysis() -> dict:
    rows = list_incidents()
    stories_raw = correlate(rows)
    stories = []
    for story in stories_raw:
        t = triage(story)
        stories.append(
            {"triage": t, "mop_log": draft_mop_log(t, story)}
        )
    stories.sort(key=lambda s: s["triage"]["score"], reverse=True)
    analysis = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "incident_count": len(rows),
        "correlation_window_min": int(CORRELATION_WINDOW.total_seconds() // 60),
        "stories": stories,
    }
    global _last_handover
    _last_handover = build_handover(analysis)
    analysis["handover"] = _last_handover
    return analysis


# ---------------------------------------------------------------------------
# Demo scenario injector
# ---------------------------------------------------------------------------

_DEMO_SCENARIOS: dict[str, list[tuple[str, str, str]]] = {
    # (source, severity, title)
    "utility_failure": [
        ("ATS", "critical", "Utility-A voltage loss detected"),
        ("ATS", "critical", "ATS transfer to generator initiated"),
        ("UPS", "warning", "UPS-A on battery, 12 min runtime estimated"),
        ("UPS", "warning", "UPS-B on battery, 12 min runtime estimated"),
        ("GENERATOR", "info", "Generator-1 crank started"),
        ("GENERATOR", "warning", "Generator-1 frequency stabilizing 59.8 Hz"),
        ("ATS", "info", "Load transferred to emergency source"),
        ("FIRE", "info", "VESDA self-test during transfer completed"),
    ],
    "chiller_fail": [
        ("PHYSICS", "critical", "Chiller-2 pressure drop >15 percent"),
        ("PHYSICS", "warning", "CRAH-03 outlet temp elevated 24.2C"),
        ("PHYSICS", "warning", "CRAH-04 outlet temp elevated 23.8C"),
        ("BMS", "info", "Chilled water setpoint adjusted +1C"),
        ("PHYSICS", "critical", "Chiller-2 compressor trip alarm"),
    ],
    "random_burst": [
        ("MORPHEUS", "info", "Modbus baseline traffic reset"),
        ("UPS", "warning", "UPS-B battery voltage deviation 2.3%"),
        ("FIRE", "info", "VESDA sensor array self-test passed"),
        ("GEMINI_ER16", "warning", "Robot detected cable management issue Rack-B12"),
    ],
}


def inject_scenario(scenario: str, count: int) -> list[Incident]:
    templates = _DEMO_SCENARIOS[scenario]
    injected = []
    # Spread the burst over the last ~12 minutes so correlation is realistic.
    for i in range(count):
        source, severity, title = templates[i % len(templates)]
        minutes_ago = round(12 * (1 - i / max(count, 1)), 1)
        injected.append(
            ingest(
                IncidentIn(
                    source=source,
                    title=title,
                    detail=f"Demo scenario '{scenario}' injected alarm {i + 1}/{count}.",
                    severity=severity,
                    minutes_ago=minutes_ago,
                )
            )
        )
    return injected


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/incidents")
def copilot_ingest(payload: IncidentIn):
    inc = ingest(payload)
    return JSONResponse(
        {
            "written": True,
            "incident_id": inc.incident_id,
            "severity": inc.severity,
            "created_at": inc.created_at.isoformat(),
        }
    )


@router.get("/incidents")
def copilot_list(severity: str | None = None, limit: int = 100):
    rows = list_incidents(severity)[:limit]
    return JSONResponse(
        {
            "count": len(rows),
            "rows": [
                {
                    "incident_id": r.incident_id,
                    "source": r.source,
                    "title": r.title,
                    "severity": r.severity,
                    "status": r.status,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ],
        }
    )


@router.delete("/incidents")
def copilot_clear():
    n = clear_incidents()
    return JSONResponse({"cleared": n})


@router.post("/simulate")
def copilot_simulate(payload: SimulateIn):
    injected = inject_scenario(payload.scenario, payload.count)
    return JSONResponse(
        {
            "scenario": payload.scenario,
            "injected": len(injected),
            "incident_ids": [i.incident_id for i in injected],
        }
    )


@router.post("/analyze")
def copilot_analyze():
    return JSONResponse(run_analysis())


@router.get("/handover")
def copilot_handover():
    if _last_handover is None:
        run_analysis()
    return JSONResponse(_last_handover or {"markdown": "No incidents recorded."})
