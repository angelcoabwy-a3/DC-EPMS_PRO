"""
backend/training_instructor.py
==============================
AI-1 (2026-11-26) -- Instructor debrief of a finished training drill.

The debrief reads the drill report (outcome, score, steps, violations,
reverted steps, sequence of events, the drill's own references) and
explains it to the trainee. Two sources, always labelled:

  deterministic  built here from the report; always available
  meta           Meta Muse Spark (backend/llm_providers.MetaProvider),
                 only when META_API_KEY is set and the instructor's
                 daily cap is not reached; any failure falls back to the
                 deterministic debrief

Rules (ADR-006 and the operator's decisions of 2026-11-26):
- READ-ONLY: never touches the plant; the score, outcome and rubric are
  deterministic and are never changed by the model.
- The model sees a brief built from the report with the operator's name
  replaced by "trainee"; no session token, no ledger key.
- The model may cite only the references listed in the drill; any other
  standard it names is returned as an unverified citation.
- Cost: one call per report and language (cached by SHA-256), max 4000
  output tokens (Muse Spark reasoning tokens count against the cap), a
  daily cap of its own: META_INSTRUCTOR_DAILY_CAP, default 20.

The pricing of the Meta API and the credit balance are not known to
this module; the cap is a count of calls, not a currency amount.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any

DAILY_CAP_ENV = "META_INSTRUCTOR_DAILY_CAP"
DAILY_CAP_DEFAULT = 20
MAX_TOKENS = 4000
DEFAULT_MODEL = "muse-spark-1.3"           # same model as MOP Verification
CACHE_SIZE = 64
SOE_LINES = 40
TEXT_MAX = 6000
LANGS = ("en", "es")
SYSTEM_ACTORS = {"training", "controller", "protection", "auto", "plant", "recorder"}

SYSTEM_PROMPT = (
    "You are a training instructor for critical-facility power operators. The plant is a "
    "SIMULATOR (DC-EPMS PRO). Write a debrief of ONE drill attempt using ONLY the JSON brief "
    "you are given. Rules: (1) Use only facts in the brief; never invent events, values, "
    "times or equipment. (2) Cite only the references listed under drill.references, by their "
    "short name; if none applies to a point, say so. (3) Do not change, recompute or dispute "
    "the score or the outcome: the rubric is deterministic. (4) Never give instructions for "
    "operating real equipment; refer the trainee to the site procedure. (5) Structure, plain "
    "text with these four headings: Summary (two sentences); What went well (bullets); What to "
    "correct (one bullet per error: what happened, why it matters, the reference); Next "
    "practice (one drill id from the brief or one skill). (6) At most 250 words. "
    "(7) Write in {language}."
)

_CITE_RE = re.compile(r"\b(IEEE|NFPA|OSHA|IEC|CSA|ANSI|NEC|IFC|UL)\s*(?:Std\.?\s*)?([A-Z]?\d[\w.\-/()]*)",
                      re.IGNORECASE)

_lock = threading.Lock()
_daily: dict[str, int] = {}
_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()


# ── Brief ───────────────────────────────────────────────────────────
def _scrub(text: Any, name: str) -> str:
    s = str(text if text is not None else "")
    if name:
        s = re.sub(rf"\b{re.escape(name)}\b", "trainee", s)
    return s


def build_brief(report: dict[str, Any], drill_ids: list[str] | None = None) -> dict[str, Any]:
    """What the model sees. The operator's name becomes "trainee"."""
    name = str(report.get("operator") or "")
    drill = report.get("drill") or {}
    t0 = None
    soe = []
    for e in report.get("soe") or []:
        ms = e.get("ts_ms")
        if ms is not None and t0 is None:
            t0 = ms
        if e.get("source") == "alarm":
            what = f"alarm {e.get('alarm_id', '')} {e.get('state', e.get('event', ''))}"
        else:
            what = " ".join(str(x) for x in (e.get("event"), e.get("command") or e.get("step") or "",
                                             e.get("relay") or "") if x)
        detail = _scrub(e.get("detail") or "", name)[:120]
        t = (ms - t0) / 1000 if (ms is not None and t0 is not None) else None
        soe.append(f"{'' if t is None else f'+{t:.1f}s '}{_scrub(what, name)}{(' - ' + detail) if detail else ''}")
    violations = [{
        "kind": v.get("violation") or v.get("event"),
        "command": v.get("command"),
        "detail": _scrub(v.get("detail") or ("switching outside the drill procedure"
                                             if v.get("violation") == "unplanned_switching" else ""), name),
    } for v in report.get("violations") or []]
    target = float(drill.get("target_s") or 0)
    dur = float(report.get("duration_ms") or 0) / 1000
    return {
        "drill": {
            "id": drill.get("id"), "title": drill.get("title"), "summary": drill.get("summary"),
            "target_s": target, "time_limit_s": drill.get("time_limit_s"),
            "steps": [{"id": s.get("id"), "text": s.get("text")} for s in drill.get("steps") or []],
            "references": list(drill.get("references") or []),
        },
        "result": {
            "outcome": report.get("outcome"), "reason": _scrub(report.get("reason") or "", name),
            "score": report.get("score"), "duration_s": round(dur, 1),
            "late_s": round(max(0.0, dur - target), 1) if target else 0.0,
            "steps_done": [{"id": s.get("id"), "t_s": round(float(s.get("t_ms") or 0) / 1000, 1)}
                           for s in report.get("steps") or []],
            "step_reverts": [{"step": r.get("step"), "event": r.get("event")}
                             for r in report.get("step_reverts") or []],
            "violations": violations,
        },
        "rubric": (report.get("rubric") or {}).get("name"),
        "soe": soe[:SOE_LINES],
        "other_drills": list(drill_ids or []),
        "simulated": True,
    }


# ── Deterministic debrief ───────────────────────────────────────────
_T = {
    "en": {
        "summary": "{outcome} with {score} / 100 in {dur} s (target {target} s).",
        "reason": "Reason: {reason}.",
        "all_steps": "All {n} procedure steps completed in order.",
        "some_steps": "{n} of {total} steps completed: {ids}.",
        "no_steps": "No procedure step was completed.",
        "no_errors": "No refused command and no switching outside the procedure.",
        "refused": "{command} was refused by the interlock: {detail}",
        "unplanned": "{command} is not part of this drill's procedure (unplanned switching).",
        "late": "Finished {late} s after the target time.",
        "revert": "Step {step} was undone after it was completed ({event}).",
        "next_repeat": "Repeat {id} until it passes with no violation.",
        "next_clean": "Repeat {id} aiming at 100 / 100.",
        "next_other": "Move on to {id}.",
        "h": ("Summary", "What went well", "What to correct", "Next practice", "References"),
    },
    "es": {
        "summary": "{outcome} con {score} / 100 en {dur} s (objetivo {target} s).",
        "reason": "Motivo: {reason}.",
        "all_steps": "Completaste los {n} pasos del procedimiento en orden.",
        "some_steps": "Completaste {n} de {total} pasos: {ids}.",
        "no_steps": "No completaste ningún paso del procedimiento.",
        "no_errors": "Ningún comando rechazado ni maniobras fuera del procedimiento.",
        "refused": "{command} fue rechazado por el enclavamiento: {detail}",
        "unplanned": "{command} no es parte del procedimiento de este drill (maniobra no planificada).",
        "late": "Terminaste {late} s después del tiempo objetivo.",
        "revert": "El paso {step} se deshizo después de completarlo ({event}).",
        "next_repeat": "Repite {id} hasta pasarlo sin violaciones.",
        "next_clean": "Repite {id} buscando 100 / 100.",
        "next_other": "Sigue con {id}.",
        "h": ("Resumen", "Lo que salió bien", "Qué corregir", "Siguiente práctica", "Referencias"),
    },
}


def deterministic_debrief(brief: dict[str, Any], lang: str = "en") -> dict[str, Any]:
    t = _T[lang if lang in _T else "en"]
    d, r = brief["drill"], brief["result"]
    summary = [t["summary"].format(outcome=r["outcome"], score=r["score"], dur=r["duration_s"],
                                   target=d["target_s"])]
    if r.get("reason"):
        summary.append(t["reason"].format(reason=r["reason"]))
    total = len(d["steps"])
    done = [s["id"] for s in r["steps_done"]]
    good = []
    if total and len(done) == total:
        good.append(t["all_steps"].format(n=total))
    elif done:
        good.append(t["some_steps"].format(n=len(done), total=total, ids=", ".join(done)))
    else:
        good.append(t["no_steps"])
    if not r["violations"]:
        good.append(t["no_errors"])
    fix = []
    for v in r["violations"]:
        key = "unplanned" if v["kind"] == "unplanned_switching" else "refused"
        fix.append(t[key].format(command=v["command"], detail=v["detail"]))
    for rv in r["step_reverts"]:
        fix.append(t["revert"].format(step=rv["step"], event=rv["event"]))
    if r["late_s"] > 0:
        fix.append(t["late"].format(late=r["late_s"]))
    others = [x for x in brief.get("other_drills") or [] if x != d["id"]]
    if r["outcome"] != "PASS" or r["violations"]:
        nxt = t["next_repeat"].format(id=d["id"])
    elif (r["score"] or 0) < 100 or not others:
        nxt = t["next_clean"].format(id=d["id"])
    else:
        later = [x for x in others if x > d["id"]]
        nxt = t["next_other"].format(id=(later or others)[0])
    h = t["h"]
    text = "\n".join(
        [f"{h[0]}: " + " ".join(summary), f"{h[1]}:"] + [f"- {x}" for x in good]
        + [f"{h[2]}:"] + ([f"- {x}" for x in fix] or ["- -"])
        + [f"{h[3]}: {nxt}", f"{h[4]}:"] + [f"- {x}" for x in d["references"]]
    )
    return {"summary": " ".join(summary), "went_well": good, "to_correct": fix, "next": nxt,
            "references": d["references"], "text": text}


# ── Citation guard ──────────────────────────────────────────────────
def unverified_citations(text: str, references: list[str]) -> list[str]:
    """Standards named in ``text`` that the drill references do not
    mention (organisation and number both looked up, case-insensitive)."""
    refs = " ".join(references).lower()
    out = []
    for m in _CITE_RE.finditer(text or ""):
        org, num = m.group(1).lower(), m.group(2).lower().rstrip(".,;:)")
        base = re.split(r"[(]", num)[0]
        if org not in refs or base not in refs:
            cite = f"{m.group(1).upper()} {m.group(2)}".rstrip(".,;:")
            if cite not in out:
                out.append(cite)
    return out


# ── Limits and cache ────────────────────────────────────────────────
def daily_cap() -> int:
    try:
        return max(0, int(str(os.environ.get(DAILY_CAP_ENV, "")).strip()))
    except (ValueError, TypeError):
        return DAILY_CAP_DEFAULT


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def calls_today() -> int:
    with _lock:
        return _daily.get(_today(), 0)


def _reserve() -> bool:
    """Count one call if the cap allows it."""
    with _lock:
        day = _today()
        for k in [k for k in _daily if k != day]:
            del _daily[k]
        if _daily.get(day, 0) >= daily_cap():
            return False
        _daily[day] = _daily.get(day, 0) + 1
        return True


def reset_limits() -> None:
    """Tests only."""
    with _lock:
        _daily.clear()
        _cache.clear()


def cache_key(brief: dict[str, Any], lang: str) -> str:
    body = json.dumps({"brief": brief, "lang": lang}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# ── Debrief ─────────────────────────────────────────────────────────
async def debrief(report: dict[str, Any], lang: str = "en", *, provider: Any = None,
                  drill_ids: list[str] | None = None) -> dict[str, Any]:
    lang = lang if lang in LANGS else "en"
    brief = build_brief(report, drill_ids)
    det = deterministic_debrief(brief, lang)
    key = cache_key(brief, lang)
    with _lock:
        hit = _cache.get(key)
    if hit is not None:
        return {**hit, "cached": True, "calls_today": calls_today(), "daily_cap": daily_cap()}
    base = {
        "source": "deterministic", "model": None, "lang": lang, "text": det["text"],
        "deterministic": det, "unverified_citations": [], "cache_key": key,
        "cached": False, "label": "Deterministic debrief built from the drill report.",
    }
    if provider is None:
        from backend.llm_providers import MetaProvider
        # Explicit model: MetaProvider's own default is a placeholder.
        provider = MetaProvider(model=os.environ.get("META_MODEL") or DEFAULT_MODEL,
                                system_prompt=SYSTEM_PROMPT.format(
                                    language="Spanish" if lang == "es" else "English"))
    if not getattr(provider, "is_configured", False):
        base["note"] = "Meta API key not configured: deterministic debrief."
    elif not _reserve():
        base["note"] = f"Instructor daily cap reached ({daily_cap()} calls): deterministic debrief."
    else:
        prompt = ("Drill brief (JSON). Write the debrief now.\n"
                  + json.dumps(brief, ensure_ascii=False, separators=(",", ":")))
        chunks: list[str] = []
        try:
            async for token in provider.stream(prompt, max_tokens=MAX_TOKENS):
                chunks.append(token)
        except Exception as exc:     # network, provider bug: fall back
            chunks = [f"[Meta stream error: {exc}]"]
        text = "".join(chunks).strip()
        if not text or text.startswith("[Meta"):
            base["note"] = f"Meta call returned no usable text ({text[:80]}): deterministic debrief."
        else:
            text = text[:TEXT_MAX]
            base.update({
                "source": "meta", "model": getattr(provider, "model", None), "text": text,
                "unverified_citations": unverified_citations(text, brief["drill"]["references"]),
                "label": "AI-generated debrief (Meta). Verify it against the drill references; "
                         "the score and outcome are the deterministic rubric's.",
            })
            with _lock:
                _cache[key] = dict(base)
                while len(_cache) > CACHE_SIZE:
                    _cache.popitem(last=False)
    base["calls_today"] = calls_today()
    base["daily_cap"] = daily_cap()
    return base
