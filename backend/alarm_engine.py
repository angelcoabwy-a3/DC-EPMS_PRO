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
        self._journal.append(
            {
                "ts": iso_ms(ms),
                "ts_ms": ms,
                "alarm_id": alarm.alarm_id,
                "event": event,
                "state": alarm.state,
                "priority": alarm.priority,
                "message": alarm.message,
                "actor": actor,
            }
        )

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
            "id": a.alarm_id,
            "priority": a.priority,
            "message": a.message,
            "source": a.source,
            "state": a.state,
            "activated": iso_ms(a.activated_ms),
            "cleared": iso_ms(a.cleared_ms),
            "acked": iso_ms(a.acked_ms),
            "acked_by": a.acked_by,
            "changed_ms": a.changed_ms,
            "occurrences": a.occurrences,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            shown = [a for a in self.alarms.values() if a.state != NORM]
            shown.sort(
                key=lambda a: (
                    _PRIORITY_RANK[a.priority],
                    0 if a.state == UNACK else 1,
                    -a.changed_ms,
                )
            )
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
            Condition(
                f"PATH_{P}_UTILITY_LOST",
                p.get("utility_ok") is False,
                MEDIUM,
                f"Path {P} utility undervoltage (ANSI 27)",
                src,
            ),
            Condition(
                f"PATH_{P}_MV_BUS_DEAD",
                dead,
                HIGH,
                f"Path {P} 13.8 kV bus dead (52-U and 52-GM open)",
                src,
            ),
            Condition(
                f"PATH_{P}_ON_BATTERY",
                bool(p["on_battery"]) if "on_battery" in p else (dead and not lost),
                HIGH,
                f"Path {P} UPS on battery ({soc:.0f} % SOC, "
                f"{float(p.get('battery_runtime_min', 0.0)):.1f} min left, model)",
                src,
            ),
            Condition(
                f"PATH_{P}_BATTERY_LOW",
                dead and not lost and soc < 25.0,
                HIGH,
                f"Path {P} UPS battery below 25 %",
                src,
            ),
            Condition(f"PATH_{P}_LOAD_LOST", lost, HIGH, f"Path {P} CRITICAL LOAD LOST", src),
            Condition(
                f"PATH_{P}_ON_GENERATORS",
                p.get("source") == "GENERATORS",
                MEDIUM,
                f"Path {P} on generators",
                src,
            ),
            Condition(
                f"PATH_{P}_UNPROTECTED",
                not bool(p.get("ups_protected", True)),
                HIGH,
                f"Path {P} load not battery-backed (UPS not in VFI / Dynamic Online)",
                src,
            ),
            Condition(
                f"PATH_{P}_UPS_N_LOST",
                not ups_n,
                HIGH,
                f"Path {P} UPS capacity below N ({p.get('ups_in_service')} of "
                f"{p.get('ups_total')} blocks)",
                src,
            ),
            Condition(
                f"PATH_{P}_UPS_N1_LOST",
                ups_n and not bool(p.get("ups_n_plus_1_ok", True)),
                MEDIUM,
                f"Path {P} UPS bank lost N+1",
                src,
            ),
            Condition(
                f"PATH_{P}_GEN_N_LOST",
                not gen_n,
                HIGH,
                f"Path {P} generation below N ({p.get('gen_available')} of "
                f"{p.get('gen_total')} sets available)",
                src,
            ),
            Condition(
                f"PATH_{P}_GEN_N1_LOST",
                gen_n and not bool(p.get("gen_n_plus_1_ok", True)),
                LOW,
                f"Path {P} generation lost N+1",
                src,
            ),
        ]
        # L4: UPS bank system breakers and the maintenance bypass.
        us = p.get("ups_system")
        if us:
            brk = us.get("breakers") or {}
            out += [
                Condition(
                    f"PATH_{P}_UPS_MAINT_BYPASS",
                    bool(brk.get("Q3")),
                    MEDIUM,
                    f"Path {P} critical load on maintenance bypass (not UPS-protected)",
                    src,
                ),
                Condition(
                    f"PATH_{P}_UPS_OUTPUT_ISOLATED",
                    brk.get("Q4") is False,
                    LOW,
                    f"Path {P} UPS output isolated (MIB Q4 open)",
                    src,
                ),
                Condition(
                    f"PATH_{P}_UPS_QF1_OPEN",
                    brk.get("QF1") is False,
                    MEDIUM,
                    f"Path {P} UPS battery breaker QF1 open (no battery backup)",
                    src,
                ),
                Condition(
                    f"PATH_{P}_UPS_Q1_OPEN",
                    brk.get("Q1") is False,
                    LOW,
                    f"Path {P} UPS rectifier input Q1 open",
                    src,
                ),
                Condition(
                    f"PATH_{P}_UPS_Q2_OPEN",
                    brk.get("Q2") is False,
                    LOW,
                    f"Path {P} UPS static-bypass input Q2 open",
                    src,
                ),
                Condition(
                    f"PATH_{P}_UPS_SKRU_KEY_OUT",
                    int(us.get("skru_keys", 1)) == 0,
                    LOW,
                    f"Path {P} maintenance bypass key out of the SKRU",
                    src,
                ),
            ]
        # L5: battery room (string monitor, H2 sensor, exhaust fans).
        room = p.get("battery_room")
        if room:
            ppm = float(room.get("h2_ppm") or 0.0)
            lel = room.get("h2_pct_lel")
            fans = room.get("fans") or []
            strs = room.get("strings") or []
            high = [str(s_["n"]) for s_ in strs if s_.get("float_high")]
            opened = [str(s_["n"]) for s_ in strs if not s_.get("online")]
            out += [
                Condition(
                    f"PATH_{P}_BATT_STRING_CURRENT",
                    bool(high),
                    MEDIUM,
                    f"Path {P} battery string {', '.join(high)} float current high "
                    "(string monitor)",
                    src,
                ),
                Condition(
                    f"PATH_{P}_BATT_STRING_OFFLINE",
                    bool(opened),
                    LOW,
                    f"Path {P} battery string {', '.join(opened)} off line "
                    f"({room.get('strings_online')} of {len(strs)} on line)",
                    src,
                ),
                Condition(
                    f"PATH_{P}_BATT_H2_HIGH",
                    float(room.get("h2_alarm_ppm") or 400)
                    <= ppm
                    < float(room.get("h2_hihi_ppm") or 1e4),
                    MEDIUM,
                    f"Path {P} battery room H2 {ppm:.0f} ppm ({lel} % LEL)",
                    src,
                ),
                Condition(
                    f"PATH_{P}_BATT_H2_HIHI",
                    ppm >= float(room.get("h2_hihi_ppm") or 1e4),
                    HIGH,
                    f"Path {P} battery room H2 {ppm:.0f} ppm ({lel} % LEL): code limit",
                    src,
                ),
                Condition(
                    f"PATH_{P}_BATT_FAN_FAIL",
                    any(f.get("failed") for f in fans),
                    MEDIUM,
                    f"Path {P} battery room exhaust fan failed "
                    f"({', '.join(f['name'] for f in fans if f.get('failed'))})",
                    src,
                ),
                Condition(
                    f"PATH_{P}_BATT_FAN_NOT_AUTO",
                    any(f.get("mode") != "AUTO" for f in fans),
                    LOW,
                    f"Path {P} battery room exhaust fan not in AUTO",
                    src,
                ),
                Condition(
                    f"PATH_{P}_BATT_NO_VENT",
                    fans != [] and not any(f.get("running") for f in fans),
                    HIGH,
                    f"Path {P} battery room without exhaust ventilation",
                    src,
                ),
                Condition(
                    f"PATH_{P}_BATT_THERMAL_RUNAWAY",
                    bool(room.get("runaway")),
                    HIGH,
                    f"Path {P} battery jar vented ({', '.join(room.get('runaway') or [])})",
                    src,
                ),
            ]
        # L3: main (bulk) fuel tank of the path.
        if p.get("bulk_fuel_pct") is not None:
            hrs = p.get("bulk_hours_left")
            low = float(p["bulk_fuel_pct"]) < 25.0 or (hrs is not None and float(hrs) < 3.0)
            out.append(
                Condition(
                    f"PATH_{P}_BULK_FUEL_LOW",
                    low,
                    MEDIUM,
                    f"Path {P} main fuel tank low ({p['bulk_fuel_pct']} %"
                    + (f", {hrs} h left at the present burn)" if hrs is not None else ")"),
                    src,
                )
            )
    for d in plant.get("devices", []):
        status = d.get("status") or {}
        did = str(d.get("id"))
        if d.get("kind") == "ups":
            overload = str(status.get("text", "")).startswith("OVERLOAD")
            out.append(
                Condition(
                    f"DEV_{did}_OVERLOAD",
                    overload,
                    HIGH,
                    f"{d.get('display', did)}: block above its rating",
                    did,
                )
            )
            out.append(
                Condition(
                    f"DEV_{did}_INVERTER_FAULT",
                    bool(d.get("fault")),
                    HIGH,
                    f"{d.get('display', did)}: inverter fault "
                    f"({str(d.get('fault') or '').replace('_', ' ').lower()})",
                    did,
                )
            )
        elif d.get("kind") == "transfer":
            # L1: the two 13.8 kV mains as switchgear cubicles.
            name = d.get("display", did)
            for c in d.get("cubicles") or []:
                brk = str(c.get("breaker", "?"))
                key = brk.replace("-", "")
                src_txt = "utility incomer" if brk == "52-U" else "generator main"
                out += [
                    Condition(
                        f"DEV_{did}_{key}_UNAVAILABLE",
                        c.get("racking") != "CONNECTED",
                        MEDIUM,
                        f"{name}: {brk} racked to {c.get('racking')} ({src_txt} unavailable)",
                        did,
                    ),
                    Condition(
                        f"DEV_{did}_{key}_86",
                        bool(c.get("lockout_86")),
                        HIGH,
                        f"{name}: {brk} 86 lockout tripped (close circuit open)",
                        did,
                    ),
                    Condition(
                        f"DEV_{did}_{key}_SPRING",
                        c.get("racking") == "CONNECTED"
                        and not c.get("spring_charged")
                        and not c.get("motor_on"),
                        LOW,
                        f"{name}: {brk} closing spring discharged, charging motor OFF",
                        did,
                    ),
                ]
            # L2: utility transformer of the path.
            t = d.get("transformer")
            if t:
                P = str(d.get("path", "?")).upper()
                xs = f"xfmr_{d.get('path')}"
                out += [
                    Condition(
                        f"XFMR_{P}_86T",
                        bool(t.get("lockout_86t")),
                        HIGH,
                        f"XFMR {P}: 86T lockout tripped ({t.get('trip_cause') or 'cause not recorded'})",
                        xs,
                    ),
                    Condition(
                        f"XFMR_{P}_63",
                        bool(t.get("flag_63")),
                        HIGH,
                        f"XFMR {P}: 63 sudden-pressure relay operated",
                        xs,
                    ),
                    Condition(
                        f"XFMR_{P}_87T",
                        bool(t.get("flag_87t")),
                        HIGH,
                        f"XFMR {P}: 87T differential relay operated",
                        xs,
                    ),
                    Condition(
                        f"XFMR_{P}_OIL_HIGH",
                        bool(t.get("oil_alarm")),
                        MEDIUM,
                        f"XFMR {P}: top oil {t.get('top_oil_c')} C above alarm (26)",
                        xs,
                    ),
                    Condition(
                        f"XFMR_{P}_WINDING_HIGH",
                        bool(t.get("winding_alarm")),
                        MEDIUM,
                        f"XFMR {P}: winding {t.get('winding_c')} C above alarm (49)",
                        xs,
                    ),
                    Condition(
                        f"XFMR_{P}_DEENERGIZED",
                        not t.get("energized")
                        and bool(t.get("grid_ok"))
                        and not t.get("lockout_86t"),
                        LOW,
                        f"XFMR {P}: de-energized (52-T open)",
                        xs,
                    ),
                    Condition(
                        f"XFMR_{P}_DETC_UNLOCKED",
                        not t.get("detc_locked", True),
                        MEDIUM,
                        f"XFMR {P}: DETC handle unlocked",
                        xs,
                    ),
                    Condition(
                        f"XFMR_{P}_INTERLOCK_DEFEATED",
                        t.get("detc_unlocked_by") == "SPARE",
                        HIGH,
                        f"XFMR {P}: DETC unlocked with a spare key (key interlock defeated)",
                        xs,
                    ),
                    Condition(
                        f"XFMR_{P}_FANS_NOT_AUTO",
                        t.get("fan_mode") != "AUTO",
                        LOW,
                        f"XFMR {P}: cooling fans selector in {t.get('fan_mode')}",
                        xs,
                    ),
                ]
        elif d.get("kind") == "generator":
            out.append(
                Condition(
                    f"DEV_{did}_BAY_OOS",
                    status.get("text") == "Bay not in service",
                    LOW,
                    f"{d.get('display', did)}: bay not in service",
                    did,
                )
            )
            # L3: engine control panel and fuel system of the set.
            f = d.get("fuel")
            if f:
                name = d.get("display", did)
                pumps = f.get("pumps") or []
                filt = f.get("filter") or {}
                out += [
                    Condition(
                        f"DEV_{did}_ESTOP",
                        bool(f.get("estop")),
                        HIGH,
                        f"{name}: emergency stop pushed in",
                        did,
                    ),
                    Condition(
                        f"DEV_{did}_SHUTDOWN",
                        bool(f.get("shutdown")) and not f.get("estop"),
                        HIGH,
                        f"{name}: shutdown, {f.get('shutdown')}",
                        did,
                    ),
                    Condition(
                        f"DEV_{did}_NOT_AUTO",
                        f.get("ecs_mode") != "AUTO",
                        LOW,
                        f"{name}: engine control in {f.get('ecs_mode')}, not AUTO",
                        did,
                    ),
                    Condition(
                        f"DEV_{did}_FUEL_LOW",
                        bool(f.get("low_alarm")),
                        MEDIUM,
                        f"{name}: day tank low ({f.get('day_tank_pct')} %)",
                        did,
                    ),
                    Condition(
                        f"DEV_{did}_FUEL_HIHI",
                        bool(f.get("hi_hi")),
                        MEDIUM,
                        f"{name}: day tank high-high level, fill stopped",
                        did,
                    ),
                    Condition(
                        f"DEV_{did}_PUMP_OL",
                        any(p.get("overload") for p in pumps),
                        MEDIUM,
                        f"{name}: day-tank pump motor overload tripped",
                        did,
                    ),
                    Condition(
                        f"DEV_{did}_PUMP_NOT_AUTO",
                        any(p.get("mode") != "AUTO" for p in pumps),
                        LOW,
                        f"{name}: day-tank pump selector not in AUTO",
                        did,
                    ),
                    Condition(
                        f"DEV_{did}_BASIN_LEAK",
                        bool(f.get("leak")),
                        HIGH,
                        f"{name}: fuel in the rupture basin, pumps stopped",
                        did,
                    ),
                    Condition(
                        f"DEV_{did}_FILTER_DP",
                        bool(f.get("dp_alarm")),
                        MEDIUM,
                        f"{name}: fuel filter restriction ({filt.get('dp_psi')} psi, model)",
                        did,
                    ),
                    Condition(
                        f"DEV_{did}_WATER_IN_FUEL",
                        bool(f.get("water_alarm")),
                        MEDIUM,
                        f"{name}: water in the fuel filter bowl",
                        did,
                    ),
                    Condition(
                        f"DEV_{did}_LOW_COOLANT_TEMP",
                        bool(f.get("coolant_low")),
                        MEDIUM,
                        f"{name}: coolant {f.get('coolant_c')} C, below the NFPA 110 Level 1 "
                        "32 C minimum (check the jacket-water heater)",
                        did,
                    ),
                ]
    return out
