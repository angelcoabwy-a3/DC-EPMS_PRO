"""HMI H4 (2026-11-14): alarm states for the simulated power plant.

Alarm lifecycle after the ANSI/ISA-18.2 state model (normal, active
unacknowledged, active acknowledged, returned to normal unacknowledged):

    NORM --active--> UNACK --ack--> ACKED --clear--> NORM
                       |                      ^
                     clear                    |
                       v                      |
                     RTNUN ------ack----------+
                       |
                     active again --> UNACK

Conditions come from the SIMULATED plant of the Power Controls view
(``DeviceController.snapshot_all()``): path source, UPS and generation
N / N+1, load protection, UPS overload, generator bays out of service.

Honest scope:
- Timestamps are server observation times with millisecond resolution
  (ISO 8601 UTC). They are NOT field sequence-of-events stamps: a
  condition is observed when the plant is evaluated (on every alarm
  read), so the time is accurate to the polling interval, not to 1 ms.
- Shelving, suppression by design and out-of-service alarms from
  ISA-18.2 are not implemented.
- Priorities (HIGH / MEDIUM / LOW) are a first rationalisation by the
  developer; ISA-18.2 expects them to come from the site's alarm
  philosophy and a rationalisation review.

Pure module: no FastAPI, no device_control import (ADR-006 fence stays
on device_control; this module only reads a snapshot dict).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

NORM = "NORM"
UNACK = "UNACK"
ACKED = "ACKED"
RTNUN = "RTNUN"
STATES = (NORM, UNACK, ACKED, RTNUN)

HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"
PRIORITIES = (HIGH, MEDIUM, LOW)
_PRIORITY_RANK = {HIGH: 0, MEDIUM: 1, LOW: 2}

JOURNAL_SIZE = 200


class AlarmError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class Condition:
    """One alarm condition evaluated against the plant."""

    alarm_id: str
    active: bool
    priority: str
    message: str
    source: str


@dataclass
class Alarm:
    alarm_id: str
    priority: str
    message: str
    source: str
    state: str = NORM
    activated_ms: int | None = None
    cleared_ms: int | None = None
    acked_ms: int | None = None
    acked_by: str | None = None
    changed_ms: int = 0
    occurrences: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def iso_ms(ms: int | None) -> str | None:
    """Epoch milliseconds -> ISO 8601 UTC with milliseconds."""
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat(timespec="milliseconds")


class AlarmEngine:
    """Thread-safe alarm state machine. ``clock`` returns epoch seconds."""

    def __init__(self, clock: Callable[[], float] = time.time):
        self.clock = clock
        self.alarms: dict[str, Alarm] = {}
        self._journal: deque[dict[str, Any]] = deque(maxlen=JOURNAL_SIZE)
        self._lock = threading.Lock()

    def reset(self) -> None:
        """Forget every alarm and the journal (training restart)."""
        with self._lock:
            self.alarms.clear()
            self._journal.clear()

    def journal_since(self, ms: int) -> list[dict[str, Any]]:
        with self._lock:
            return [j for j in self._journal if j["ts_ms"] >= ms]

    def _now_ms(self) -> int:
        return int(round(self.clock() * 1000))

    def _log(self, alarm: Alarm, event: str, ms: int, actor: str | None = None) -> None:
        self._journal.append({
            "ts": iso_ms(ms), "ts_ms": ms, "alarm_id": alarm.alarm_id,
            "event": event, "state": alarm.state, "priority": alarm.priority,
            "message": alarm.message, "actor": actor,
        })

    def evaluate(self, conditions: Iterable[Condition]) -> None:
        """Apply one evaluation. Known alarms absent from ``conditions``
        are treated as inactive."""
        now = self._now_ms()
        seen: set[str] = set()
        with self._lock:
            for c in conditions:
                if c.priority not in _PRIORITY_RANK:
                    raise ValueError(f"unknown priority {c.priority!r}")
                seen.add(c.alarm_id)
                a = self.alarms.get(c.alarm_id)
                if a is None:
                    a = Alarm(c.alarm_id, c.priority, c.message, c.source)
                    self.alarms[c.alarm_id] = a
                a.message, a.priority, a.source = c.message, c.priority, c.source
                self._step(a, c.active, now)
            for alarm_id, a in self.alarms.items():
                if alarm_id not in seen:
                    self._step(a, False, now)

    def _step(self, a: Alarm, active: bool, now: int) -> None:
        if active and a.state in (NORM, RTNUN):
            a.state = UNACK
            a.activated_ms, a.cleared_ms = now, None
            a.acked_ms, a.acked_by = None, None
            a.changed_ms = now
            a.occurrences += 1
            self._log(a, "ACTIVE", now)
        elif not active and a.state == UNACK:
            a.state, a.cleared_ms, a.changed_ms = RTNUN, now, now
            self._log(a, "CLEARED", now)
        elif not active and a.state == ACKED:
            a.state, a.cleared_ms, a.changed_ms = NORM, now, now
            self._log(a, "CLEARED", now)

    def ack(self, alarm_id: str, actor: str) -> dict[str, Any]:
        now = self._now_ms()
        with self._lock:
            a = self.alarms.get(alarm_id)
            if a is None:
                raise AlarmError(404, f"unknown alarm {alarm_id}")
            if a.state == UNACK:
                a.state = ACKED
            elif a.state == RTNUN:
                a.state = NORM
            else:
                raise AlarmError(409, f"alarm {alarm_id} is {a.state}: nothing to acknowledge")
            a.acked_ms, a.acked_by, a.changed_ms = now, actor, now
            self._log(a, "ACK", now, actor)
            return self._view(a)

    def ack_all(self, actor: str) -> list[dict[str, Any]]:
        with self._lock:
            pending = [a.alarm_id for a in self.alarms.values() if a.state in (UNACK, RTNUN)]
        return [self.ack(i, actor) for i in pending]

    @staticmethod
    def _view(a: Alarm) -> dict[str, Any]:
        return {
            "id": a.alarm_id, "priority": a.priority, "message": a.message,
            "source": a.source, "state": a.state,
            "activated": iso_ms(a.activated_ms), "cleared": iso_ms(a.cleared_ms),
            "acked": iso_ms(a.acked_ms), "acked_by": a.acked_by,
            "changed_ms": a.changed_ms, "occurrences": a.occurrences,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            shown = [a for a in self.alarms.values() if a.state != NORM]
            shown.sort(key=lambda a: (
                _PRIORITY_RANK[a.priority], 0 if a.state == UNACK else 1, -a.changed_ms))
            counts = {s: 0 for s in STATES if s != NORM}
            for a in shown:
                counts[a.state] += 1
            return {
                "alarms": [self._view(a) for a in shown],
                "counts": counts,
                "unacked": counts[UNACK] + counts[RTNUN],
                "journal": list(self._journal)[::-1][:50],
            }


# ── Conditions from the Power Controls plant snapshot ───────────────
def conditions_from_plant(plant: dict[str, Any]) -> list[Condition]:
    """Map ``DeviceController.snapshot_all()`` to alarm conditions."""
    out: list[Condition] = []
    for p in plant.get("paths", []):
        path = str(p.get("path", "?"))
        P = path.upper()
        src = f"path_{path}"
        ups_n = bool(p.get("ups_n_ok", True))
        gen_n = bool(p.get("gen_n_ok", True))
        dead = p.get("bus_energized") is False
        lost = bool(p.get("load_lost", False))
        soc = float(p.get("battery_soc_pct", 100.0))
        out += [
            Condition(f"PATH_{P}_UTILITY_LOST", p.get("utility_ok") is False, MEDIUM,
                      f"Path {P} utility undervoltage (ANSI 27)", src),
            Condition(f"PATH_{P}_MV_BUS_DEAD", dead, HIGH,
                      f"Path {P} 13.8 kV bus dead (52-U and 52-GM open)", src),
            Condition(f"PATH_{P}_ON_BATTERY", dead and not lost, HIGH,
                      f"Path {P} UPS on battery ({soc:.0f} % SOC, "
                      f"{float(p.get('battery_runtime_min', 0.0)):.1f} min left, model)", src),
            Condition(f"PATH_{P}_BATTERY_LOW", dead and not lost and soc < 25.0, HIGH,
                      f"Path {P} UPS battery below 25 %", src),
            Condition(f"PATH_{P}_LOAD_LOST", lost, HIGH,
                      f"Path {P} CRITICAL LOAD LOST", src),
            Condition(f"PATH_{P}_ON_GENERATORS", p.get("source") == "GENERATORS", MEDIUM,
                      f"Path {P} on generators", src),
            Condition(f"PATH_{P}_UNPROTECTED", not bool(p.get("ups_protected", True)), HIGH,
                      f"Path {P} load not battery-backed (UPS not in VFI / Dynamic Online)", src),
            Condition(f"PATH_{P}_UPS_N_LOST", not ups_n, HIGH,
                      f"Path {P} UPS capacity below N ({p.get('ups_in_service')} of "
                      f"{p.get('ups_total')} blocks)", src),
            Condition(f"PATH_{P}_UPS_N1_LOST", ups_n and not bool(p.get("ups_n_plus_1_ok", True)),
                      MEDIUM, f"Path {P} UPS bank lost N+1", src),
            Condition(f"PATH_{P}_GEN_N_LOST", not gen_n, HIGH,
                      f"Path {P} generation below N ({p.get('gen_available')} of "
                      f"{p.get('gen_total')} sets available)", src),
            Condition(f"PATH_{P}_GEN_N1_LOST", gen_n and not bool(p.get("gen_n_plus_1_ok", True)),
                      LOW, f"Path {P} generation lost N+1", src),
        ]
    for d in plant.get("devices", []):
        status = d.get("status") or {}
        did = str(d.get("id"))
        if d.get("kind") == "ups":
            overload = str(status.get("text", "")).startswith("OVERLOAD")
            out.append(Condition(f"DEV_{did}_OVERLOAD", overload, HIGH,
                                 f"{d.get('display', did)}: block above its rating", did))
            out.append(Condition(f"DEV_{did}_INVERTER_FAULT", bool(d.get("fault")), HIGH,
                                 f"{d.get('display', did)}: inverter fault "
                                 f"({str(d.get('fault') or '').replace('_', ' ').lower()})", did))
        elif d.get("kind") == "transfer":
            # L1: the two 13.8 kV mains as switchgear cubicles.
            name = d.get("display", did)
            for c in d.get("cubicles") or []:
                brk = str(c.get("breaker", "?"))
                key = brk.replace("-", "")
                src_txt = "utility incomer" if brk == "52-U" else "generator main"
                out += [
                    Condition(f"DEV_{did}_{key}_UNAVAILABLE", c.get("racking") != "CONNECTED", MEDIUM,
                              f"{name}: {brk} racked to {c.get('racking')} ({src_txt} unavailable)", did),
                    Condition(f"DEV_{did}_{key}_86", bool(c.get("lockout_86")), HIGH,
                              f"{name}: {brk} 86 lockout tripped (close circuit open)", did),
                    Condition(f"DEV_{did}_{key}_SPRING",
                              c.get("racking") == "CONNECTED" and not c.get("spring_charged")
                              and not c.get("motor_on"), LOW,
                              f"{name}: {brk} closing spring discharged, charging motor OFF", did),
                ]
        elif d.get("kind") == "generator":
            out.append(Condition(f"DEV_{did}_BAY_OOS", status.get("text") == "Bay not in service",
                                 LOW, f"{d.get('display', did)}: bay not in service", did))
    return out
