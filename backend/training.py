"""T1 (2026-11-15): operator training drills on the simulated plant.

A drill (``config/training_drills/DRILL-NN.json``) declares a setup
(authorities, injections), ordered steps with machine-checkable
conditions on the plant and the alarm state, and failure conditions.
The trainee works with the normal HMI (alarm banner, Power SLD, Power
Controls). The engine only OBSERVES: each evaluation marks the next
step done when its condition holds and stamps the elapsed time.

Scoring rubric "DC-EPMS training rubric v2" (our own rubric, not an
industry standard such as NETA or Uptime Institute):
  - outcome FAIL (critical load lost or time limit) -> score 0;
  - otherwise 100, minus 10 per violation, minus 1 per started 10 s
    beyond the drill's target time, floor 0. A violation is a refused
    or blocked command, or (v2) a switching command outside the drill's
    procedure ("procedure_commands"): unplanned switching.
v2 also tracks steps whose "holds" condition stops being true after
they were done (e.g. back to generators after the close): reported as
reverted / restored, not scored (the switching that caused it is).

Honest scope: one drill at a time for the whole plant (the plant is a
single shared simulator); times come from the server clock at
evaluation (the UI polls every 1 to 3 s), so step times are accurate to
the poll, with ms resolution. Pure logic: no FastAPI here.
"""

from __future__ import annotations

import fnmatch
import json
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.alarm_engine import ACKED, NORM, AlarmEngine, conditions_from_plant, iso_ms

RUBRIC = {
    "name": "DC-EPMS training rubric v2",
    "not_an_industry_standard": True,
    "fail": "critical load lost or time limit exceeded -> 0",
    "violation": "refused or blocked command, or a switching command outside "
                 "the drill procedure (unplanned switching)",
    "violation_penalty": 10,
    "late_penalty_per_10_s": 1,
}
# Actors of automatic plant events: never counted as unplanned switching.
SYSTEM_ACTORS = frozenset({"training", "controller", "protection", "auto", "plant"})
VIOLATION_EVENTS = ("refused", "procedure_blocked", "bay_blocked")

CHECK_TYPES = (
    "alarms_acked", "gens_started_cover_demand", "gens_on_bus_cover_demand",
    "transfer_state", "device_state", "no_sets_running",
    "sync_slip_within", "event_seen", "cubicle", "device_authority", "xfmr", "gen_fuel", "ups_system",
    "battery_room", "wiring", "all",
)
FAIL_TYPES = ("load_lost", "command_used", "xfmr_internal_fault", "gen_shutdown", "battery_runaway")
INJECT_TYPES = ("utility_loss", "utility_restore", "preset_on_generators", "ups_fault",
                "closed_transition_mode", "synchro", "xfmr_spare_key", "utility_voltage",
                "gen_condition", "qf1_shunt_trip", "ups_mode", "battery_condition",
                "wiring_fault")


class TrainingError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


# ── Drill library ───────────────────────────────────────────────────
def validate_drill(d: dict[str, Any]) -> dict[str, Any]:
    problems = []
    for key in ("id", "title", "summary", "path", "steps"):
        if not d.get(key):
            problems.append(f"missing {key}")
    if float(d.get("target_s", 0)) <= 0 or float(d.get("time_limit_s", 0)) <= 0:
        problems.append("target_s and time_limit_s must be positive")
    ids = set()
    for step in d.get("steps") or []:
        if step.get("id") in ids:
            problems.append(f"duplicate step {step.get('id')}")
        ids.add(step.get("id"))
        if (step.get("check") or {}).get("type") not in CHECK_TYPES:
            problems.append(f"step {step.get('id')}: unknown check")
        if "holds" in step and (step.get("holds") or {}).get("type") not in CHECK_TYPES:
            problems.append(f"step {step.get('id')}: unknown holds condition")
    pc = d.get("procedure_commands")
    if pc is not None and (not isinstance(pc, list) or not pc
                           or not all(isinstance(c, str) and c for c in pc)):
        problems.append("procedure_commands must be a non-empty list of command names")
    for f in d.get("fail") or []:
        if f.get("type") not in FAIL_TYPES:
            problems.append(f"unknown fail condition {f.get('type')}")
    for inj in (d.get("setup") or {}).get("inject") or []:
        if inj.get("type") not in INJECT_TYPES:
            problems.append(f"unknown injection {inj.get('type')}")
    if problems:
        raise ValueError(f"drill {d.get('id')!r} invalid: " + "; ".join(problems))
    return d


def load_drills(directory: Path) -> dict[str, dict[str, Any]]:
    drills = {}
    for path in sorted(directory.glob("DRILL-*.json")):
        drill = validate_drill(json.loads(path.read_text(encoding="utf-8")))
        drills[drill["id"]] = drill
    return drills


def drill_summary(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": d["id"], "version": d.get("version", 1), "title": d["title"],
        "summary": d["summary"], "path": d["path"], "target_s": d["target_s"],
        "time_limit_s": d["time_limit_s"],
        "references": list(d.get("references") or []),
        "steps": [{"id": s["id"], "text": s["text"]} for s in d["steps"]],
    }


# ── Conditions on the plant snapshot ────────────────────────────────
def _path(plant: dict[str, Any], path: str) -> dict[str, Any]:
    return next((p for p in plant.get("paths", []) if p.get("path") == path), {})


def _devices(plant: dict[str, Any], kind: str, path: str) -> list[dict[str, Any]]:
    return [d for d in plant.get("devices", []) if d.get("kind") == kind and d.get("path") == path]


def _events_since(events: list[dict[str, Any]], mark: float) -> list[dict[str, Any]]:
    return [e for e in events if e.get("ts", 0) >= mark]


def _dig(obj: Any, dotted: Any) -> Any:
    """Value at a dotted path ("pumps.0.mode"), None when absent."""
    for part in str(dotted or "").split("."):
        if isinstance(obj, list):
            try:
                obj = obj[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
    return obj


def _match(v: Any, cond: dict[str, Any]) -> bool:
    if "contains" in cond:
        # L5: a list (or text) that must hold a value, e.g. scanned strings
        return isinstance(v, list | str) and cond["contains"] in v
    if "lacks" in cond:
        return isinstance(v, list | str) and cond["lacks"] not in v
    if cond.get("truthy"):
        return bool(v)
    if "min" in cond or "max" in cond:
        try:
            x = float(v)
        except (TypeError, ValueError):
            return False
        return float(cond.get("min", float("-inf"))) <= x <= float(cond.get("max", float("inf")))
    wanted = cond.get("values") if "values" in cond else [cond.get("value")]
    return v in wanted


def check(cond: dict[str, Any], plant: dict[str, Any], engine: AlarmEngine,
          events: list[dict[str, Any]] | None = None) -> bool:
    kind = cond.get("type")
    path = cond.get("path")
    if kind == "sync_slip_within":
        xfer = next(iter(_devices(plant, "transfer", path)), {})
        sync = xfer.get("synchro") or {}
        return bool(sync.get("live")) and abs(float(sync.get("slip_hz", 99))) <= float(cond.get("max_hz", 0.1))
    if kind == "event_seen":
        # e.g. {"event": "command", "field": "closed_transition", "value": true}
        for e in events or []:
            if e.get("event") != cond.get("event"):
                continue
            if "field" in cond and e.get(cond["field"]) != cond.get("value"):
                continue
            # L1b: several fields at once, and fields that must be set
            if any(e.get(k) != v for k, v in (cond.get("match") or {}).items()):
                continue
            if not all(e.get(k) for k in cond.get("present") or []):
                continue
            return True
        return False
    if kind == "cubicle":
        # L1: {"path", "breaker", "field", "value"} or "values": [...]
        xfer = next(iter(_devices(plant, "transfer", path)), {})
        c = next((x for x in xfer.get("cubicles") or [] if x.get("breaker") == cond.get("breaker")), None)
        if c is None:
            return False
        if cond.get("truthy"):
            return bool(c.get(cond.get("field")))
        wanted = cond.get("values") if "values" in cond else [cond.get("value")]
        return c.get(cond.get("field")) in wanted
    if kind == "xfmr":
        # L2: {"path", "field", "value"} / "values" / "truthy" / "min" + "max"
        xfer = next(iter(_devices(plant, "transfer", path)), {})
        t = xfer.get("transformer")
        if not t:
            return False
        v = t.get(cond.get("field"))
        if cond.get("truthy"):
            return bool(v)
        if "min" in cond or "max" in cond:
            try:
                x = float(v)
            except (TypeError, ValueError):
                return False
            return float(cond.get("min", float("-inf"))) <= x <= float(cond.get("max", float("inf")))
        wanted = cond.get("values") if "values" in cond else [cond.get("value")]
        return v in wanted
    if kind == "gen_fuel":
        # L3: {"device", "field": "pumps.0.mode"} + value / values / truthy / min / max
        dev = next((d for d in plant.get("devices", []) if d.get("id") == cond.get("device")), {})
        return _match(_dig(dev.get("fuel"), cond.get("field")), cond)
    if kind == "ups_system":
        # L4: {"path", "field": "breakers.Q3"} + value / values / truthy / min / max
        return _match(_dig(_path(plant, path).get("ups_system"), cond.get("field")), cond)
    if kind == "battery_room":
        # L5: {"path", "field": "strings.2.closed"} + value / values / truthy / contains
        return _match(_dig(_path(plant, path).get("battery_room"), cond.get("field")), cond)
    if kind == "wiring":
        # L5: {"path", "field": "fuses.F-1A.ok"} on the transfer controller
        xfer = next(iter(_devices(plant, "transfer", path)), {})
        return _match(_dig(xfer.get("wiring"), cond.get("field")), cond)
    if kind == "all":
        return all(check(sub, plant, engine, events) for sub in cond.get("of") or [{}])
    if kind == "device_authority":
        return any(d.get("id") == cond.get("device") and d.get("authority") == cond.get("authority")
                   for d in plant.get("devices", []))
    if kind == "alarms_acked":
        prefix = str(cond.get("prefix", ""))
        mine = [a for a in engine.alarms.values() if a.alarm_id.startswith(prefix)]
        raised = [a for a in mine if a.occurrences > 0]
        return bool(raised) and all(a.state in (ACKED, NORM) for a in mine)
    if kind in ("gens_started_cover_demand", "gens_on_bus_cover_demand"):
        # demand_kw is what the path draws once a source is back
        # (IT + cooling + auxiliaries + UPS losses), dead bus or not.
        demand = float(_path(plant, path).get("demand_kw") or 0.0)
        gens = _devices(plant, "generator", path)
        if kind == "gens_started_cover_demand":
            kw = sum(g.get("rated_kw", 0) for g in gens if g.get("state") != "STANDBY"
                     and g.get("state") != "COOLDOWN")
        else:
            kw = float(_path(plant, path).get("gen_on_bus_kw") or 0.0)
        return demand > 0 and kw >= demand
    if kind == "transfer_state":
        return any(d.get("state") == cond.get("state") for d in _devices(plant, "transfer", path))
    if kind == "device_state":
        # "states" lists every state that proves the step was done (a
        # later state counts: the trainee may act between two polls).
        wanted = cond.get("states") or [cond.get("state")]
        return any(d.get("id") == cond.get("device") and d.get("state") in wanted
                   for d in plant.get("devices", []))
    if kind == "no_sets_running":
        return not any(g.get("state") in ("RUNNING", "ON_LOAD", "CRANKING")
                       for g in _devices(plant, "generator", path))
    return False


def unplanned_switching(drill: dict[str, Any],
                        events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Commands executed by a person that the drill procedure does not
    call for. A drill without "procedure_commands" checks nothing."""
    allowed = drill.get("procedure_commands")
    if not allowed:
        return []
    return [
        {**e, "violation": "unplanned_switching"}
        for e in events
        if e.get("event") == "command" and e.get("actor") not in SYSTEM_ACTORS
        and e.get("command") not in allowed
    ]


def failed(conds: list[dict[str, Any]], plant: dict[str, Any],
           events: list[dict[str, Any]] | None = None) -> str | None:
    for cond in conds:
        if cond.get("type") == "load_lost" and _path(plant, cond.get("path")).get("load_lost"):
            return f"critical load lost on path {str(cond.get('path')).upper()}"
        if cond.get("type") == "xfmr_internal_fault":
            for e in events or []:
                if e.get("event") == "xfmr_internal_fault" \
                        and e.get("device_id") == f"mvtc_{cond.get('path')}":
                    return cond.get("reason") or (
                        f"internal fault in XFMR {str(cond.get('path')).upper()}: "
                        "DETC moved with the transformer energized")
        if cond.get("type") == "gen_shutdown":
            for e in events or []:
                if e.get("event") == "protection_trip" and e.get("relay") == "SHUTDOWN" \
                        and e.get("device_id") == cond.get("device"):
                    return cond.get("reason") or f"{cond.get('device')} shut down: {e.get('detail')}"
        if cond.get("type") == "battery_runaway":
            for e in events or []:
                if e.get("event") == "thermal_runaway" \
                        and e.get("device_id") == f"battery_room_{cond.get('path')}":
                    return cond.get("reason") or f"thermal runaway: jar {e.get('jar')} vented"
        if cond.get("type") == "command_used":
            for e in events or []:
                if e.get("event") == "command" and e.get("command") == cond.get("command"):
                    return cond.get("reason") or f"{cond.get('command')} used"
    return None


# ── Session ─────────────────────────────────────────────────────────
@dataclass
class Session:
    drill: dict[str, Any]
    operator: str
    started_ms: int
    events_mark: float
    done: list[dict[str, Any]] = field(default_factory=list)
    outcome: str | None = None          # PASS | FAIL | ABORTED
    reason: str | None = None
    ended_ms: int | None = None
    violations: list[dict[str, Any]] = field(default_factory=list)
    reverts: list[dict[str, Any]] = field(default_factory=list)
    holding: dict[str, bool] = field(default_factory=dict)
    score: int | None = None
    ledger_entry_id: str | None = None

    @property
    def active(self) -> bool:
        return self.outcome is None


class TrainingManager:
    """Single drill at a time over one DeviceController + AlarmEngine."""

    def __init__(self, drills: dict[str, dict[str, Any]],
                 clock: Callable[[], float] = time.time):
        self.drills = drills
        self.clock = clock
        self.session: Session | None = None
        self.last_report: dict[str, Any] | None = None
        self._lock = threading.Lock()

    def _now_ms(self) -> int:
        return int(round(self.clock() * 1000))

    def start(self, drill_id: str, operator: str, ctl: Any, engine: AlarmEngine) -> dict[str, Any]:
        drill = self.drills.get(drill_id)
        if drill is None:
            raise TrainingError(404, f"unknown drill {drill_id!r}")
        with self._lock:
            if self.session is not None and self.session.active:
                raise TrainingError(409, f"drill {self.session.drill['id']} is running: abort it first")
            ctl.reset(operator)
            engine.reset()
            setup = drill.get("setup") or {}
            for pattern, mode in (setup.get("authority") or {}).items():
                for device_id in sorted(fnmatch.filter(ctl.devices, pattern)):
                    if ctl.devices[device_id].authority != mode:
                        ctl.set_authority(device_id, mode, "training")
            mark = ctl.wall_clock()
            for inj in setup.get("inject") or []:
                kind = inj["type"]
                if kind == "utility_loss":
                    ctl.inject_utility_loss(inj["path"], "training")
                elif kind == "utility_restore":
                    ctl.restore_utility(inj["path"], "training")
                elif kind == "preset_on_generators":
                    ctl.preset_on_generators(inj["path"], "training")
                elif kind == "ups_fault":
                    ctl.inject_ups_fault(inj["device"], inj["fault"], "training")
                elif kind == "closed_transition_mode":
                    ctl.set_closed_transition(bool(inj.get("enabled", True)), "training")
                elif kind == "synchro":
                    ctl.set_sync(inj["path"], inj["gen_hz"], inj["angle_deg"], "training")
                elif kind == "xfmr_spare_key":
                    ctl.set_spare_key(inj["path"], bool(inj.get("available", True)), "training")
                elif kind == "utility_voltage":
                    ctl.set_grid_voltage(inj["path"], inj["kv"], "training")
                elif kind == "qf1_shunt_trip":
                    ctl.inject_qf1_shunt_trip(inj["path"], "training")
                elif kind == "ups_mode":
                    ctl.ups_action(inj["path"], inj["action"], "training")
                elif kind == "wiring_fault":
                    ctl.inject_wiring_fault(inj["path"], inj["fuse"], "training")
                elif kind == "battery_condition":
                    params = {k: v for k, v in inj.items() if k not in ("type", "path", "condition")}
                    ctl.inject_battery_condition(inj["path"], inj["condition"], "training", **params)
                elif kind == "gen_condition":
                    params = {k: v for k, v in inj.items() if k not in ("type", "device", "condition")}
                    ctl.inject_gen_condition(inj["device"], inj["condition"], "training", **params)
            self.session = Session(drill=drill, operator=operator,
                                   started_ms=self._now_ms(), events_mark=mark)
            self.last_report = None
        return self.evaluate(ctl, engine)

    def evaluate(self, ctl: Any, engine: AlarmEngine) -> dict[str, Any]:
        with self._lock:
            s = self.session
            if s is None:
                return {"active": False, "session": None, "last_report": self.last_report}
            if not s.active:
                return self._view(s)
            plant = ctl.snapshot_all()
            engine.evaluate(conditions_from_plant(plant))
            now = self._now_ms()
            events = _events_since(list(ctl._events), s.events_mark)
            steps = s.drill["steps"]
            while len(s.done) < len(steps):
                step = steps[len(s.done)]
                if not check(step["check"], plant, engine, events):
                    break
                s.done.append({"id": step["id"], "text": step["text"], "t_ms": now - s.started_ms})
                if "holds" in step:
                    s.holding[step["id"]] = check(step["holds"], plant, engine, events)
            # v2: a done step whose "holds" condition stops being true.
            for step in steps[:len(s.done)]:
                if "holds" not in step:
                    continue
                ok = check(step["holds"], plant, engine, events)
                was = s.holding.get(step["id"], ok)
                if was != ok:
                    s.reverts.append({"step": step["id"], "event": "restored" if ok else "reverted",
                                      "t_ms": now - s.started_ms})
                s.holding[step["id"]] = ok
            s.violations = [
                e for e in events if e.get("event") in VIOLATION_EVENTS
            ] + unplanned_switching(s.drill, events)
            s.violations.sort(key=lambda e: e.get("ts", 0))
            reason = failed(s.drill.get("fail") or [], plant, events)
            if reason:
                self._finish(s, "FAIL", reason, now)
            elif len(s.done) == len(steps):
                self._finish(s, "PASS", None, now)
            elif now - s.started_ms > float(s.drill["time_limit_s"]) * 1000:
                self._finish(s, "FAIL", "time limit exceeded", now)
            view = self._view(s)
            if not s.active:
                self.last_report = self._report(s, ctl, engine)
                view["last_report"] = self.last_report
            return view

    def abort(self, actor: str, ctl: Any, engine: AlarmEngine) -> dict[str, Any]:
        with self._lock:
            s = self.session
            if s is None or not s.active:
                raise TrainingError(409, "no drill is running")
            self._finish(s, "ABORTED", f"aborted by {actor}", self._now_ms())
            self.last_report = self._report(s, ctl, engine)
            view = self._view(s)
            view["last_report"] = self.last_report
            return view

    def _finish(self, s: Session, outcome: str, reason: str | None, now: int) -> None:
        s.outcome, s.reason, s.ended_ms = outcome, reason, now
        s.score = score(s)

    @staticmethod
    def _view(s: Session) -> dict[str, Any]:
        now_ms = s.ended_ms
        steps = []
        for i, step in enumerate(s.drill["steps"]):
            done = s.done[i] if i < len(s.done) else None
            steps.append({
                "id": step["id"], "text": step["text"],
                "done": done is not None, "t_ms": done["t_ms"] if done else None,
                "current": done is None and i == len(s.done) and s.active,
                "reverted": done is not None and s.holding.get(step["id"]) is False,
            })
        return {
            "active": s.active,
            "session": {
                "drill": drill_summary(s.drill), "operator": s.operator,
                "started": iso_ms(s.started_ms), "started_ms": s.started_ms,
                "ended": iso_ms(now_ms), "outcome": s.outcome, "reason": s.reason,
                "score": s.score, "violations": len(s.violations),
                "unplanned_switching": sum(1 for v in s.violations
                                           if v.get("violation") == "unplanned_switching"),
                "steps": steps,
                "ledger_entry_id": s.ledger_entry_id,
            },
        }

    def _report(self, s: Session, ctl: Any, engine: AlarmEngine) -> dict[str, Any]:
        soe = []
        for e in list(ctl._events):
            if e.get("ts", 0) >= s.events_mark - 0.001:
                ms = int(round(float(e["ts"]) * 1000))
                rest = {k: v for k, v in e.items() if k != "ts"}
                # DC-EPMS-074: an event's own "source" (authority origin)
                # must not overwrite the report's source label.
                if "source" in rest:
                    rest["origin"] = rest.pop("source")
                soe.append({"ts": iso_ms(ms), "ts_ms": ms, "source": "plant", **rest})
        for j in engine.journal_since(s.started_ms - 5000):
            soe.append({"source": "alarm", **j})
        for d in s.done:
            ms = s.started_ms + d["t_ms"]
            soe.append({"ts": iso_ms(ms), "ts_ms": ms, "source": "training",
                        "event": "step_done", "step": d["id"]})
        for r in s.reverts:
            ms = s.started_ms + r["t_ms"]
            soe.append({"ts": iso_ms(ms), "ts_ms": ms, "source": "training",
                        "event": f"step_{r['event']}", "step": r["step"]})
        soe.sort(key=lambda r: r.get("ts_ms", 0))
        return {
            "report": "DC-EPMS operator training report",
            "simulated": True,
            "drill": drill_summary(s.drill),
            "operator": s.operator,
            "started": iso_ms(s.started_ms), "ended": iso_ms(s.ended_ms),
            "duration_ms": (s.ended_ms or s.started_ms) - s.started_ms,
            "outcome": s.outcome, "reason": s.reason, "score": s.score,
            "rubric": RUBRIC,
            "steps": [dict(d) for d in s.done],
            "violations": [dict(v) for v in s.violations],
            "step_reverts": [dict(r) for r in s.reverts],
            "soe": soe,
            "time_note": "Server observation times (ms resolution); steps are "
                         "stamped when the UI poll evaluated them.",
        }


def score(s: Session) -> int:
    if s.outcome != "PASS":
        return 0
    elapsed_s = ((s.ended_ms or s.started_ms) - s.started_ms) / 1000.0
    late = max(0.0, elapsed_s - float(s.drill["target_s"]))
    points = 100 - RUBRIC["violation_penalty"] * len(s.violations) \
        - RUBRIC["late_penalty_per_10_s"] * math.ceil(late / 10.0)
    return max(0, int(points))
