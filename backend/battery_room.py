"""
backend/battery_room.py
=======================
L5 (2026-11-26) -- Battery room of the UPS bank of one path, as a
technician walks it: 4 parallel strings of 40 x 12 V VRLA jars behind
the battery breaker QF1, a DC string disconnect per string (SB1..SB4)
with a padlock hasp, a removable mid-string link per string, an
infrared camera, a battery analyzer (jar voltage + internal ohmic value)
and the hydrogen exhaust system (lead fan EF-1, lag fan EF-2, H2 sensor).

Grounding and model readings (checked 2026-11-26):
- 4 strings x 40 jars, 542.1 VDC float and the example defect (string 3,
  jar 18: 48.6 C, 14.2 mOhm, 10.4 V) come from the operator master
  specification. 542.1 V / 240 cells = 2.259 V per cell, inside the
  usual VRLA float band. The 4 strings are the specification's room;
  they are NOT sized to the 10 min runtime of the 20 MW bank (the energy
  model of the device controller keeps the design runtime and scales it
  by the fraction of strings on line).
- Ohmic value: a rise of 30 % to 50 % or more over the jar's baseline
  indicates aging and capacity loss (Battcon 2013, "Batteries die in
  thirds", citing IEEE battery standards and manufacturers). Model
  thresholds: WARN at +30 %, REPLACE at +50 %. IEEE 1188 itself was not
  read for this lot.
- Parallel strings share the bus voltage: a jar with a shorted cell
  drops to 10.4 V and the other 39 jars of that string float higher, so
  that string draws more float current and heats. The battery monitor
  sees the string float current, not the jar; finding the jar is the
  infrared scan plus the analyzer.
- Hydrogen: lower explosive limit 4 % by volume; fire codes limit a VRLA
  battery room to 1 % of the room volume (25 % LEL) by ventilation
  (IFC / NFPA 1 / NYC MC 502.4.1). Alarm at 1 % LEL (400 ppm, operator
  specification); high-high at 25 % LEL (10,000 ppm, code limit).
- Gas evolution, float currents, heating rate, the 60 C runaway limit
  and the ambient are MODEL values on an accelerated time base.

PURE: no clock, no I/O. ``tick`` receives dt and the electrical context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

STRINGS = 4
JARS = 40
FLOAT_BUS_V = 542.1
FLOAT_JAR_V = FLOAT_BUS_V / JARS          # 13.5525 V
OCV_JAR_V = 12.85                          # model: open-circuit, rested
DISCHARGE_FACTOR = 0.93                    # model: bus under discharge
AMBIENT_C = 24.0                           # model; rooms are kept at or below 25 C
BASE_R_MOHM = 3.6                          # model baseline ohmic value
OHMIC_WARN = 1.30                          # Battcon 2013: 30 % .. 50 % rise
OHMIC_REPLACE = 1.50
DT_WARN_C = 5.0                            # model: jar vs string median
DT_ALARM_C = 10.0
RUNAWAY_C = 60.0                           # model
HOT_RISE_C_S = 0.04                        # model: hot jar heating with current
COOL_TAU_S = 120.0                         # model, accelerated
FLOAT_A = 0.3                              # model: float current per string
HOT_FLOAT_A = 3.0                          # model: string with a shorted cell
FLOAT_A_ALARM = 1.0
H2_LEL_PPM = 40_000.0                      # 4 % by volume
H2_ALARM_PPM = 400.0                       # 1 % LEL (operator spec)
H2_HIHI_PPM = 10_000.0                     # 25 % LEL = 1 % vol (code limit)
H2_PER_STRING = 0.8                        # model ppm/s, float, string on line
H2_HOT_STRING = 3.0                        # model ppm/s extra, string with the defect
H2_RUNAWAY = 40.0                          # model ppm/s while a jar vents
FAN_K = 0.04                               # model removal per running fan, 1/s
FAN_MODES = ("AUTO", "OFF", "HAND")
FANS = ("EF1", "EF2")
DEFAULT_DEFECT = {"string": 3, "jar": 18, "temp_c": 48.6, "r_mohm": 14.2, "v": 10.4}

_ACTION_RE = re.compile(
    r"^(?:(IR_SCAN)_S([1-4])|(MEASURE|REPLACE)_S([1-4])_J(\d{1,2})"
    r"|(OPEN|CLOSE|PADLOCK|UNPADLOCK)_SB([1-4])|(BREAK_LINK|MAKE_LINK)_S([1-4])"
    r"|(EF[12])_(AUTO|OFF|HAND|RESET))$"
)
INSPECTIONS = ("IR_SCAN", "MEASURE")


def _wobble(s: int, j: int, salt: int) -> float:
    """Deterministic spread in [-0.5, 0.5) per jar (no randomness)."""
    return (((s * 41 + j) * 2654435761 + salt * 97) % 1000) / 1000.0 - 0.5


@dataclass
class Jar:
    string: int
    n: int
    r_base: float
    r: float
    temp_c: float
    t_base: float = AMBIENT_C           # resting temperature of this jar
    defect_v: float | None = None      # jar voltage held by a shorted cell
    hot: bool = False
    vented: bool = False                # reached the runaway limit
    replaced: bool = False

    @property
    def jid(self) -> str:
        return f"S{self.string}J{self.n}"


def _new_jar(s: int, j: int) -> Jar:
    r = round(BASE_R_MOHM + 0.3 * _wobble(s, j, 1), 2)
    # Middle of a rack runs slightly warmer than the ends (model).
    mid = 1.0 - abs(j - 20.5) / 20.0
    t = round(AMBIENT_C + 0.6 * mid + 0.3 * _wobble(s, j, 2), 2)
    return Jar(string=s, n=j, r_base=r, r=r, temp_c=t, t_base=t)


@dataclass
class BString:
    n: int
    jars: list[Jar]
    closed: bool = True
    padlock: str | None = None
    link: bool = True

    @property
    def online(self) -> bool:
        return self.closed and self.link


@dataclass
class Fan:
    name: str
    mode: str = "AUTO"
    failed: bool = False
    lag_on: bool = False


@dataclass
class BatteryRoom:
    path: str
    strings: list[BString] = field(default_factory=lambda: [
        BString(n=s, jars=[_new_jar(s, j) for j in range(1, JARS + 1)]) for s in range(1, STRINGS + 1)
    ])
    fans: dict[str, Fan] = field(default_factory=lambda: {f: Fan(name=f) for f in FANS})
    # Starts at the float equilibrium with EF-1 running (4 strings on line).
    h2_ppm: float = STRINGS * H2_PER_STRING / FAN_K
    scanned: list[int] = field(default_factory=list)
    measured: list[str] = field(default_factory=list)
    readings: list[dict[str, Any]] = field(default_factory=list)   # last analyzer readings
    replaced: list[str] = field(default_factory=list)
    runaway: list[str] = field(default_factory=list)


@dataclass
class BatteryContext:
    qf1: bool = True
    charging: bool = True
    discharging: bool = False
    actor: str = ""


def parse_action(action: str) -> tuple[str, int, int] | None:
    """("MEASURE", 3, 18) / ("OPEN_SB", 2, 0) / ("EF1_AUTO", 0, 0) or None."""
    m = _ACTION_RE.match(str(action or "").upper())
    if not m:
        return None
    g = m.groups()
    if g[0]:
        return (g[0], int(g[1]), 0)
    if g[2]:
        jar = int(g[4])
        return None if not 1 <= jar <= JARS else (g[2], int(g[3]), jar)
    if g[5]:
        return (f"{g[5]}_SB", int(g[6]), 0)
    if g[7]:
        return (g[7], int(g[8]), 0)
    return (f"{g[9]}_{g[10]}", 0, 0)


def is_inspection(action: str) -> bool:
    p = parse_action(action)
    return p is not None and p[0] in INSPECTIONS


def string_of(room: BatteryRoom, n: int) -> BString:
    return room.strings[n - 1]


def jar_of(room: BatteryRoom, s: int, j: int) -> Jar:
    return room.strings[s - 1].jars[j - 1]


def _current_flows(st: BString, ctx: BatteryContext) -> bool:
    return st.online and ctx.qf1 and (ctx.charging or ctx.discharging)


def strings_online(room: BatteryRoom) -> int:
    return sum(1 for st in room.strings if st.online)


def fan_running(room: BatteryRoom, name: str) -> bool:
    f = room.fans[name]
    if f.failed or f.mode == "OFF":
        return False
    if f.mode == "HAND" or name == "EF1":
        return True
    return f.lag_on


def jar_voltage(room: BatteryRoom, st: BString, jar: Jar, ctx: BatteryContext) -> float:
    """Jar terminal voltage (model). Parallel strings share the bus: a
    jar held low by a shorted cell pushes the rest of its string up."""
    if not _current_flows(st, ctx):
        return round(jar.defect_v * 0.98 if jar.defect_v is not None else OCV_JAR_V, 2)
    bus = FLOAT_BUS_V if ctx.charging else FLOAT_BUS_V * DISCHARGE_FACTOR
    if jar.defect_v is not None:
        return round(jar.defect_v if ctx.charging else jar.defect_v * DISCHARGE_FACTOR, 2)
    low = [x.defect_v for x in st.jars if x.defect_v is not None]
    held = sum(low) if ctx.charging else sum(low) * DISCHARGE_FACTOR
    return round((bus - held) / (JARS - len(low)), 3)


def string_voltage(room: BatteryRoom, st: BString, ctx: BatteryContext) -> float:
    if not st.link:
        return 0.0          # the string is open in the middle
    return round(sum(jar_voltage(room, st, j, ctx) for j in st.jars), 1)


def string_current(room: BatteryRoom, st: BString, ctx: BatteryContext) -> float:
    if not _current_flows(st, ctx):
        return 0.0
    if ctx.discharging:
        return -1.0         # sign only: the controller knows the load
    return HOT_FLOAT_A if any(j.defect_v is not None for j in st.jars) else FLOAT_A


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def jar_delta_t(st: BString, jar: Jar) -> float:
    return round(jar.temp_c - _median([j.temp_c for j in st.jars]), 2)


def ohmic_status(jar: Jar) -> str:
    ratio = jar.r / jar.r_base if jar.r_base else 1.0
    if ratio >= OHMIC_REPLACE:
        return "REPLACE"
    if ratio >= OHMIC_WARN:
        return "WARN"
    return "OK"


def inject_defect(room: BatteryRoom, string: int, jar: int, temp_c: float,
                  r_mohm: float, v: float) -> Jar:
    j = jar_of(room, string, jar)
    j.temp_c, j.r, j.defect_v, j.hot = float(temp_c), float(r_mohm), float(v), True
    j.vented = j.replaced = False
    return j


def interlock(room: BatteryRoom, action: str, ctx: BatteryContext) -> str | None:
    p = parse_action(action)
    if p is None:
        return f"unknown battery room action {action!r}"
    verb, s, j = p
    if verb in INSPECTIONS or verb.startswith("EF"):
        if verb.endswith("_RESET") and not room.fans[verb[:3]].failed:
            return f"{verb[:3]} has no tripped overload to reset"
        return None
    st = string_of(room, s)
    if verb == "OPEN_SB":
        return f"SB{s} is already open" if not st.closed else None
    if verb == "CLOSE_SB":
        if st.closed:
            return f"SB{s} is already closed"
        if st.padlock:
            return f"SB{s} carries the padlock of {st.padlock}: remove it first"
        if not st.link:
            return f"string {s} is open in the middle: put the mid-string link back first"
        bad = [x.jid for x in st.jars if x.vented]
        if bad:
            return f"string {s} has a vented jar ({bad[0]}): replace it before closing SB{s}"
        return None
    if verb == "PADLOCK_SB":
        if st.closed:
            return f"SB{s} is closed: open it before applying a padlock"
        return f"SB{s} already carries a padlock" if st.padlock else None
    if verb == "UNPADLOCK_SB":
        if not st.padlock:
            return f"SB{s} has no padlock"
        if ctx.actor and st.padlock != ctx.actor:
            return f"the padlock on SB{s} belongs to {st.padlock}: only its owner removes it"
        return None
    if verb == "BREAK_LINK":
        if not st.link:
            return f"the mid-string link of string {s} is already out"
        if st.closed or not st.padlock:
            return (f"isolate and lock string {s} first (SB{s} open and padlocked): "
                    "the link is removed with the string de-energized from the bus")
        return None
    if verb == "MAKE_LINK":
        if st.link:
            return f"the mid-string link of string {s} is already in"
        return f"SB{s} must stay open while the link goes back" if st.closed else None
    if verb == "REPLACE":
        if st.closed or not st.padlock or st.link:
            return (f"jar replacement needs string {s} isolated (SB{s} open), padlocked and "
                    "split at the mid-string link: the string is a 542 V source by itself")
        return None
    return None


def apply(room: BatteryRoom, action: str, ctx: BatteryContext) -> dict[str, Any] | None:
    """Apply a permitted action. Inspections return their reading."""
    verb, s, j = parse_action(action)  # type: ignore[misc]
    if verb == "IR_SCAN":
        if s not in room.scanned:
            room.scanned.append(s)
        st = string_of(room, s)
        hottest = max(st.jars, key=lambda x: x.temp_c)
        return {"string": s, "hottest": hottest.jid, "max_c": round(hottest.temp_c, 1),
                "delta_c": jar_delta_t(st, hottest),
                "median_c": round(_median([x.temp_c for x in st.jars]), 1)}
    if verb == "MEASURE":
        st, jar = string_of(room, s), jar_of(room, s, j)
        reading = {
            "jar": jar.jid, "v": jar_voltage(room, st, jar, ctx), "r_mohm": round(jar.r, 2),
            "r_base_mohm": jar.r_base, "rise_pct": round((jar.r / jar.r_base - 1.0) * 100, 1),
            "temp_c": round(jar.temp_c, 1), "status": ohmic_status(jar),
        }
        if jar.jid not in room.measured:
            room.measured.append(jar.jid)
        room.readings = [*room.readings, reading][-12:]
        return reading
    if verb.startswith("EF"):
        name, what = verb[:3], verb[4:]
        f = room.fans[name]
        if what == "RESET":
            f.failed = False
        else:
            f.mode = what
        return None
    st = string_of(room, s)
    if verb == "OPEN_SB":
        st.closed = False
    elif verb == "CLOSE_SB":
        st.closed = True
    elif verb == "PADLOCK_SB":
        st.padlock = ctx.actor or "operator"
    elif verb == "UNPADLOCK_SB":
        st.padlock = None
    elif verb == "BREAK_LINK":
        st.link = False
    elif verb == "MAKE_LINK":
        st.link = True
    elif verb == "REPLACE":
        old = jar_of(room, s, j)
        new = _new_jar(s, j)
        new.r_base = new.r = round(BASE_R_MOHM - 0.15, 2)     # model: new jar, lower ohmic value
        new.temp_c = new.t_base = AMBIENT_C
        new.replaced = True
        st.jars[j - 1] = new
        room.replaced.append(old.jid)
    return None


def tick(room: BatteryRoom, dt: float, ctx: BatteryContext) -> list[dict[str, Any]]:
    """Advance temperatures, hydrogen and fans by ``dt`` seconds."""
    events: list[dict[str, Any]] = []
    if dt <= 0:
        return events
    gen = 0.0
    for st in room.strings:
        flows = _current_flows(st, ctx)
        if flows and ctx.charging:
            gen += H2_PER_STRING
        for jar in st.jars:
            if jar.hot and flows:
                jar.temp_c += HOT_RISE_C_S * dt
                if ctx.charging:
                    gen += H2_HOT_STRING
                if jar.temp_c >= RUNAWAY_C and not jar.vented:
                    jar.vented = True
                    room.runaway.append(jar.jid)
                    st.closed = False     # model: the string monitor trips its disconnect
                    events.append({"event": "thermal_runaway", "jar": jar.jid,
                                   "detail": f"jar {jar.jid} reached {RUNAWAY_C:.0f} C and vented; "
                                             f"SB{st.n} tripped by the string monitor (model)"})
            elif jar.temp_c > jar.t_base:
                jar.temp_c += (jar.t_base - jar.temp_c) * min(1.0, dt / COOL_TAU_S)
            if jar.vented and jar.temp_c > 50.0:
                gen += H2_RUNAWAY
    lag = room.fans["EF2"]
    if room.h2_ppm >= H2_ALARM_PPM and not lag.lag_on:
        lag.lag_on = True
        if fan_running(room, "EF2"):
            events.append({"event": "fan_start", "fan": "EF2",
                           "detail": "lag exhaust fan EF-2 started on H2 alarm (1 % LEL)"})
    elif room.h2_ppm < H2_ALARM_PPM / 2 and lag.lag_on:
        lag.lag_on = False
    running = sum(1 for f in FANS if fan_running(room, f))
    room.h2_ppm = max(0.0, room.h2_ppm + (gen - FAN_K * running * room.h2_ppm) * dt)
    return events


def describe(room: BatteryRoom, ctx: BatteryContext) -> dict[str, Any]:
    strings = []
    for st in room.strings:
        cur = string_current(room, st, ctx)
        strings.append({
            "n": st.n, "closed": st.closed, "padlock": st.padlock, "link": st.link,
            "online": st.online, "voltage_v": string_voltage(room, st, ctx),
            "float_a": cur if cur >= 0 else None,
            "float_high": cur >= FLOAT_A_ALARM,
            "temps": [round(j.temp_c, 1) for j in st.jars],
            "vented": [j.n for j in st.jars if j.vented],
        })
    fans = [{"name": f, "mode": room.fans[f].mode, "failed": room.fans[f].failed,
             "running": fan_running(room, f)} for f in FANS]
    return {
        "strings": strings,
        "strings_online": strings_online(room),
        "bus_v": round(FLOAT_BUS_V if ctx.charging and ctx.qf1 and strings_online(room) else
                       FLOAT_BUS_V * DISCHARGE_FACTOR if ctx.discharging and strings_online(room) else 0.0, 1),
        "h2_ppm": round(room.h2_ppm, 1),
        "h2_pct_lel": round(room.h2_ppm / H2_LEL_PPM * 100.0, 2),
        "h2_alarm_ppm": H2_ALARM_PPM, "h2_hihi_ppm": H2_HIHI_PPM,
        "fans": fans,
        "scanned": list(room.scanned), "measured": list(room.measured),
        "readings": list(room.readings), "replaced": list(room.replaced),
        "runaway": list(room.runaway),
        "thresholds": {"ohmic_warn_pct": round((OHMIC_WARN - 1) * 100),
                       "ohmic_replace_pct": round((OHMIC_REPLACE - 1) * 100),
                       "dt_warn_c": DT_WARN_C, "dt_alarm_c": DT_ALARM_C, "runaway_c": RUNAWAY_C,
                       "ambient_c": AMBIENT_C},
    }
