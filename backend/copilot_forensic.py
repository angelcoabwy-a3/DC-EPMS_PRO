"""Shift Forensic Investigator agent.

BUILT DURING THE META GLOBAL AI DEVELOPER HACKATHON (Oct 26 - Nov 4, 2026).

This is the hackathon-built feature. It is deliberately separate from
the pre-existing deterministic Shift Copilot in ``shift_copilot.py``
(correlation, P1/P2/P3 triage, MOP-style log, handover, demo scenarios,
built before the hackathon).

A narrator only retells what happened. This investigator does the work
a shift operator normally does by hand after an alarm flood, but live,
during the shift:

    1. Collect evidence: every alarm in the burst, with source,
       severity, title, and timestamp.
    2. Rebuild the timeline in chronological order.
    3. Test hypotheses against that evidence and rule some out
       (for example, "generator did not start" is ruled out when a
       generator crank alarm is present).
    4. Name a probable cause, with a confidence level, and say
       explicitly what is still unconfirmed.
    5. Give a verification checklist for the operator to confirm
       in person. The agent never invents evidence, and it never
       changes the deterministic priority, score, or suggested
       procedure. The model investigates and explains; the
       deterministic triage decides.

If no Meta key is configured, or the API call fails, the agent
returns the deterministic investigation built only from the
evidence, and labels that source clearly.

Mount: ``app.include_router(forensic_router)`` in backend/main.py,
next to the existing shift-copilot mount.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse

try:  # package import (backend.copilot_forensic)
    from .llm_providers import MetaProvider
    from .shift_copilot import list_incidents, run_analysis
except ImportError:  # top-level import, as backend/main.py does it
    from llm_providers import MetaProvider
    from shift_copilot import list_incidents, run_analysis

forensic_router = APIRouter(prefix="/api/copilot", tags=["shift-forensic-investigator"])

SYSTEM_PROMPT = (
    "You are a forensic investigator for a data-center shift. "
    "Work ONLY from the evidence list given to you. Rebuild the "
    "timeline, test each hypothesis against the evidence, rule out "
    "what the evidence contradicts, and name a probable cause with "
    "a confidence level. Do not invent alarms, readings, equipment, "
    "or times. Do not change the priority or the suggested procedure. "
    "End with what the operator must verify in person, because an "
    "alarm alone is not proof. Keep it short, plain, and auditable."
)

# Hypothesis -> keywords that support it in alarm titles/sources.
_HYPOTHESES = [
    ("utility_loss", "Utility power loss", ["voltage loss", "utility"]),
    ("ats_transfer", "ATS transferred load to emergency source", ["ats transfer", "load transferred"]),
    ("generator_running", "Generator started and is carrying load", ["generator", "crank", "frequency"]),
    ("ups_on_battery", "UPS on battery", ["ups", "on battery"]),
    ("cooling_loss", "Cooling loss / chiller failure", ["chiller", "crah", "cooling", "outlet temp"]),
    # Note: "VESDA self-test" alone is NOT a fire event, so fire needs an
    # alarm/smoke phrase, not just the sensor name.
    ("fire_event", "Fire / smoke detection event", ["fire alarm", "smoke detected", "vesda alarm"]),
]


def collect_evidence() -> list[dict]:
    """All alarms in the burst, in chronological order, as evidence."""
    rows = sorted(list_incidents(), key=lambda r: r.created_at)
    return [
        {
            "incident_id": r.incident_id,
            "source": r.source,
            "severity": r.severity,
            "title": r.title,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


def test_hypotheses(evidence: list[dict]) -> list[dict]:
    """Test each hypothesis against the evidence."""
    tested = []
    for key, label, keywords in _HYPOTHESES:
        hits = [e["incident_id"] for e in evidence if any(k in (e["source"] + " " + e["title"]).lower() for k in keywords)]
        tested.append(
            {
                "key": key,
                "label": label,
                "status": "supported" if hits else "no_evidence",
                "evidence_ids": hits,
            }
        )
    return tested


def _verification_checklist(top_source: str, hypotheses: list[dict]) -> list[str]:
    checks = [
        "Verify in person before closing the story: an alarm alone is not proof.",
        "Log every verification with timestamps for the shift record.",
    ]
    supported = {h["key"] for h in hypotheses if h["status"] == "supported"}
    if "utility_loss" in supported or "ats_transfer" in supported:
        checks.append("ATS room: confirm utility feed state, ATS position, and load on emergency source.")
    if "generator_running" in supported:
        checks.append("Generator: confirm fuel, frequency, load, and coolant temperature in person.")
    if "ups_on_battery" in supported:
        checks.append("UPS room: confirm battery runtime remaining and battery voltage.")
    if "cooling_loss" in supported:
        checks.append("Cooling: confirm chiller pressure, CRAH outlet temperatures, and chilled water setpoint.")
    if "fire_event" in supported:
        checks.append("Fire safety: confirm VESDA status and that no fire panel is in alarm before resuming normal work.")
    if top_source:
        checks.append(f"Top story source to inspect first: {top_source}.")
    return checks


def deterministic_investigation(analysis: dict) -> dict:
    """Forensic investigation from evidence only, no model call."""
    evidence = collect_evidence()
    hypotheses = test_hypotheses(evidence)
    stories = analysis.get("stories") or []
    top = stories[0] if stories else None
    triage = top["triage"] if top else None
    mop = top["mop_log"] if top else None
    supported = [h for h in hypotheses if h["status"] == "supported"]
    probable = None
    for key in ("utility_loss", "cooling_loss", "fire_event", "ats_transfer", "generator_running", "ups_on_battery"):
        match = next((h for h in supported if h["key"] == key), None)
        if match:
            probable = match["label"]
            break
    if len(supported) >= 3:
        confidence = "high"
    elif len(supported) >= 1:
        confidence = "medium"
    else:
        confidence = "low"
    ruled_out = [h["label"] for h in hypotheses if h["status"] == "no_evidence"]
    return {
        "source": "deterministic_fallback",
        "timeline": evidence,
        "hypotheses": hypotheses,
        "probable_cause": probable or "Unconfirmed: evidence does not point to a single cause yet.",
        "ruled_out_or_no_evidence": ruled_out,
        "confidence": confidence,
        "priority": triage["priority"] if triage else None,
        "story_id": triage["story_id"] if triage else None,
        "suggested_procedure": mop["suggested_procedure"] if mop else None,
        "verification_checklist": _verification_checklist(triage["source"] if triage else "", hypotheses),
        "text": (
            f"Burst: {len(evidence)} alarms across {len(stories)} stories. "
            f"Top story: {triage['story_id'] if triage else 'none'} "
            f"[{triage['priority'] if triage else ''}] from {triage['source'] if triage else ''}. "
            f"Probable cause ({confidence} confidence): {probable or 'unconfirmed'}. "
            f"Follow {mop['suggested_procedure'] if mop else 'the standing procedure'} "
            "and verify in person before closing the story."
        ),
    }


def build_investigation_prompt(analysis: dict, evidence: list[dict], hypotheses: list[dict]) -> str:
    lines = ["Evidence, in chronological order (incident_id | source | severity | title | time):"]
    for e in evidence:
        lines.append(f"- {e['incident_id']} | {e['source']} | {e['severity']} | {e['title']} | {e['created_at']}")
    lines.append("")
    lines.append("Deterministic hypotheses already tested (do not contradict them without evidence):")
    for h in hypotheses:
        lines.append(f"- {h['label']}: {h['status']}, evidence: {', '.join(h['evidence_ids']) or 'none'}")
    top = (analysis.get("stories") or [None])[0]
    if top:
        lines.append(f"\nDeterministic priority: {top['triage']['priority']} (score {top['triage']['score']}).")
        lines.append(f"Deterministic suggested procedure: {top['mop_log']['suggested_procedure']}.")
    lines.append(
        "\nWrite a forensic investigation in five short parts, using ONLY the evidence above:\n"
        "1. Timeline: what happened first, next, last.\n"
        "2. Hypotheses tested: which are supported, which have no evidence.\n"
        "3. Probable cause, with a confidence level (high/medium/low).\n"
        "4. What is still unconfirmed.\n"
        "5. Verification checklist: what the operator must confirm in person."
    )
    return "\n".join(lines)


async def investigate(analysis: dict, provider: MetaProvider | None = None) -> dict:
    """Investigate the burst with Meta, or fall back deterministically."""
    evidence = collect_evidence()
    hypotheses = test_hypotheses(evidence)
    provider = provider or MetaProvider(system_prompt=SYSTEM_PROMPT)
    if not provider.is_configured:
        result = deterministic_investigation(analysis)
        result["meta_configured"] = False
        result["note"] = "Meta API key not configured; deterministic investigation used."
        return result

    prompt = build_investigation_prompt(analysis, evidence, hypotheses)
    chunks: list[str] = []
    async for token in provider.stream(prompt, max_tokens=800):
        chunks.append(token)
    text = "".join(chunks).strip()
    if not text or text.startswith("[Meta"):
        result = deterministic_investigation(analysis)
        result["meta_configured"] = True
        result["note"] = f"Meta call did not return usable text ({text[:80]}); deterministic investigation used."
        return result

    base = deterministic_investigation(analysis)
    base.update(
        {
            "source": "meta",
            "model": provider.model,
            "text": text,
            "meta_configured": True,
            "note": "AI investigation only. Priority, score, and suggested procedure are deterministic and unchanged.",
        }
    )
    return base


@forensic_router.post("/investigate")
async def copilot_investigate():
    """Run deterministic analysis, then forensically investigate the burst.

    The response labels its source clearly so judges can tell what the
    model did (investigation) from what the deterministic copilot did
    (correlation, triage, procedure suggestion).
    """
    analysis = run_analysis()
    result = await investigate(analysis)
    return JSONResponse(
        {
            "built_during_hackathon": True,
            "feature": "shift-forensic-investigator",
            "incident_count": analysis["incident_count"],
            "story_count": len(analysis.get("stories") or []),
            "investigation": result,
        }
    )


def investigate_sync(analysis: dict) -> dict:
    """Synchronous helper for scripts and tests."""
    return asyncio.run(investigate(analysis))
