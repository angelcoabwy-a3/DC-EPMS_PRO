"""
backend/gen_fuel.py
===================
L3 (2026-11-26) -- Field model of one diesel generator set and its fuel
system: the local engine control panel (ECS mode STOP / AUTO / RUN,
emergency stop), the jacket-water heater, the sub-base day tank with
its float levels, the duplex transfer pumps P-1 (lead) / P-2 (lag),
the duplex fuel filter / water separator and the rupture-basin leak
float; and the bulk tank of the path that feeds the day tanks.

PURE: no clock, no I/O. The device controller supplies the time step,
the engine state and its electrical output.

Grounding (checked 2026-11-26, secondary sources unless noted):
  * NFPA 110 Level 1: jacket-water heaters keep the coolant at 32 C
    (90 F) minimum (quoted in two generator manufacturers' manuals);
    the low coolant temperature alarm warns of a heater problem.
  * Fuel burn: Cummins DQLH 2750 kW standby, 60 Hz data sheet:
    239 / 391 / 542 / 694 L/h at 1/4, 1/2, 3/4 and full load. The
    no-load point (87 L/h) is a linear EXTRAPOLATION, not a datum.
  * Day tank practice (Phillips Pump guide specs): rupture basin with a
    float that alarms and stops the pumps, a Manual-Off-Auto selector
    per pump, a normally closed supply solenoid that opens with the
    pump.
  * Float levels 95 / 85 / 60 / 40 / 15 % and the 1,200 L day tank /
    50,000 L bulk tank come from the operator's master specification.

MODEL VALUES (not a vendor's): pump flow 1,200 L/h, heater setpoint
43 C, engine-room ambient 17.8 C (master spec), running coolant 85 C,
time constants, cold-start load-acceptance delay, filter pressure
drop curve and its alarm / starvation thresholds. Time runs
GEN_TIME_SCALE times faster than the wall clock; the payload says so.
The high-high float stops the pumps even in HAND (hardwired overfill
protection): verify against the panel drawing of a real installation.

The governor / AVR bias of each set for manual paralleling is NOT
modelled here: the bus-level governor of the synchroscope (T3) stays.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

# ── Spec values (operator master specification) ──────────────────────
DAY_TANK_L = 1200.0
BULK_TANK_L = 50000.0
LVL_HI_HI = 95.0          # overfill: pumps stop, solenoid closes
LVL_PUMP_STOP = 85.0
LVL_LEAD_START = 60.0
LVL_LAG_START = 40.0      # + low level alarm
LVL_CRITICAL = 15.0       # engine shutdown
ENGINE_ROOM_C = 17.8

# ── Grounded values ──────────────────────────────────────────────────
NFPA110_MIN_COOLANT_C = 32.0
# Cummins DQLH (2750 kW standby, 60 Hz) fuel curve, L/h by load fraction.
FUEL_CURVE = ((0.0, 87.0), (0.25, 239.0), (0.5, 391.0), (0.75, 542.0), (1.0, 694.0))

# ── Model values ─────────────────────────────────────────────────────
GEN_TIME_SCALE = 30.0            # 1 s wall clock = 30 s of fuel / coolant time
PUMP_FLOW_LPH = 1200.0
HEATER_SETPOINT_C = 43.0
RUNNING_COOLANT_C = 85.0
TAU_RUN_MIN = 4.0
TAU_HEATER_MIN = 40.0
TAU_COOL_MIN = 120.0
COLD_START_DELAY_S = 12.0        # extra crank-to-ready when the block is cold
DP_CLEAN_PSI = 0.6
DP_PER_CLOG_PSI = 7.0
DP_ALARM_PSI = 4.0
DP_STARVE_PSI = 7.5
WATER_ALARM_PCT = 50.0
BULK_LOW_PCT = 25.0
BULK_LOW_HOURS = 3.0             # remaining run time on the main tank

HAND, OFF, AUTO = "HAND", "OFF", "AUTO"
PUMP_MODES = (HAND, OFF, AUTO)
ECS_STOP, ECS_AUTO, ECS_RUN = "STOP", "AUTO", "RUN"
ECS_MODES = (ECS_STOP, ECS_AUTO, ECS_RUN)
FILTER_A, FILTER_BOTH, FILTER_B = "A", "BOTH", "B"

ACTIONS = (
    "ECS_STOP", "ECS_AUTO", "ECS_RUN", "ESTOP_PUSH", "ESTOP_RELEASE",
    "HEATER_ON", "HEATER_OFF",
    "P1_HAND", "P1_OFF", "P1_AUTO", "P2_HAND", "P2_OFF", "P2_AUTO",
    "RESET_P1_OL", "RESET_P2_OL",
    "FILTER_A", "FILTER_BOTH", "FILTER_B", "DRAIN_A", "DRAIN_B",
    "CHANGE_ELEMENT_A", "CHANGE_ELEMENT_B",
    "CLEAN_BASIN", "RESET_LEAK",
)
ACTION_LABELS = {
    "ECS_STOP": "Engine control to STOP / RESET",
    "ECS_AUTO": "Engine control to AUTO",
    "ECS_RUN": "Engine control to RUN (local start)",
    "ESTOP_PUSH": "Push the emergency stop",
    "ESTOP_RELEASE": "Twist to release the emergency stop",
    "HEATER_ON": "Jacket-water heater breaker ON",
    "HEATER_OFF": "Jacket-water heater breaker OFF",
    "P1_HAND": "Pump P-1 selector to HAND", "P1_OFF": "Pump P-1 selector to OFF",
    "P1_AUTO": "Pump P-1 selector to AUTO", "P2_HAND": "Pump P-2 selector to HAND",
    "P2_OFF": "Pump P-2 selector to OFF", "P2_AUTO": "Pump P-2 selector to AUTO",
    "RESET_P1_OL": "Reset the P-1 motor overload (49/OL)",
    "RESET_P2_OL": "Reset the P-2 motor overload (49/OL)",
    "FILTER_A": "Fuel filter selector to A", "FILTER_BOTH": "Fuel filter selector to BOTH",
    "FILTER_B": "Fuel filter selector to B",
    "DRAIN_A": "Drain water from filter bowl A", "DRAIN_B": "Drain water from filter bowl B",
    "CHANGE_ELEMENT_A": "Change filter element A", "CHANGE_ELEMENT_B": "Change filter element B",
    "CLEAN_BASIN": "Pump out and clean the rupture basin",
    "RESET_LEAK": "Reset the basin leak alarm",
}


@dataclass
class Pump:
    mode: str = AUTO
    running: bool = False
    overload: bool = False


@dataclass
class GenSet:
    device_id: str
    path: str
    ecs_mode: str = ECS_AUTO
    estop: bool = False
    shutdown: str | None = None          # latched shutdown cause
    heater_on: bool = True
    coolant_c: float = HEATER_SETPOINT_C
    day_l: float = DAY_TANK_L * 0.80
    p1: Pump = field(default_factory=Pump)
    p2: Pump = field(default_factory=Pump)
    solenoid_open: bool = False
    filter_sel: str = FILTER_BOTH
    clog: dict[str, float] = field(default_factory=lambda: {FILTER_A: 0.0, FILTER_B: 0.0})
    water: dict[str, float] = field(default_factory=lambda: {FILTER_A: 0.0, FILTER_B: 0.0})
    leak_present: bool = False
    leak_latched: bool = False
    burn_lph: float = 0.0
    dp_psi: float = 0.0
    crank_cold: bool | None = None
    low_alarm: bool = False

    @property
    def level_pct(self) -> float:
        return self.day_l / DAY_TANK_L * 100.0


@dataclass(frozen=True)
class GenContext:
    running: bool             # engine turning (cranking, running, on load)
    stopped: bool             # standby / cooldown finished
    bulk_l: float
    actor: str = ""


def burn_lph(load_fraction: float, running: bool) -> float:
    if not running:
        return 0.0
    x = max(0.0, min(1.0, load_fraction))
    for (x0, y0), (x1, y1) in pairwise(FUEL_CURVE):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return FUEL_CURVE[-1][1]


def available(g: GenSet) -> str | None:
    """Why the set cannot start now (None when it can)."""
    if g.estop:
        return "Emergency stop pushed in at the set."
    if g.shutdown:
        return f"Latched shutdown: {g.shutdown}. Put the engine control to STOP / RESET."
    if g.level_pct <= LVL_CRITICAL:
        return f"Day tank at {g.level_pct:.0f} %: critical low level, the engine will not run."
    return None


def cold(g: GenSet) -> bool:
    return g.coolant_c < NFPA110_MIN_COOLANT_C


def filter_dp(g: GenSet, flow_lph: float) -> float:
    """Pressure drop across the selected filter(s), model psi."""
    frac = flow_lph / FUEL_CURVE[-1][1]
    if g.filter_sel == FILTER_BOTH:
        clog = (g.clog[FILTER_A] + g.clog[FILTER_B]) / 2.0
        frac /= 2.0
    else:
        clog = g.clog[g.filter_sel]
    return (DP_CLEAN_PSI + DP_PER_CLOG_PSI * clog) * frac


def _pumps(g: GenSet) -> None:
    lvl = g.level_pct
    hihi = lvl >= LVL_HI_HI
    blocked = hihi or g.leak_latched
    for pump, start in ((g.p1, LVL_LEAD_START), (g.p2, LVL_LAG_START)):
        if pump.overload or pump.mode == OFF or blocked:
            pump.running = False
        elif pump.mode == HAND or lvl <= start:
            pump.running = True
        elif lvl >= LVL_PUMP_STOP:
            pump.running = False
    g.solenoid_open = g.p1.running or g.p2.running


def refresh(g: GenSet) -> None:
    """Re-evaluate the pump controller after an external change."""
    _pumps(g)


def tick(g: GenSet, dt_s: float, load_fraction: float, ctx: GenContext) -> tuple[list[dict[str, Any]], float]:
    """Advance by ``dt_s`` seconds of WALL clock. Returns (events, litres
    drawn from the bulk tank)."""
    events: list[dict[str, Any]] = []
    t = max(0.0, dt_s) * GEN_TIME_SCALE          # model seconds
    minutes = t / 60.0
    hours = t / 3600.0
    # coolant
    target, tau = ((RUNNING_COOLANT_C, TAU_RUN_MIN) if ctx.running else
                   (HEATER_SETPOINT_C, TAU_HEATER_MIN) if g.heater_on else
                   (ENGINE_ROOM_C, TAU_COOL_MIN))
    if minutes:
        g.coolant_c = target + (g.coolant_c - target) * math.exp(-minutes / tau)
    # basin
    if g.leak_present and not g.leak_latched:
        g.leak_latched = True
        events.append({"event": "gen_basin_leak", "detail": "fuel in the rupture basin: pumps stopped, solenoid closed"})
    _pumps(g)
    inflow = 0.0
    if ctx.bulk_l > 0:
        inflow = PUMP_FLOW_LPH * (int(g.p1.running) + int(g.p2.running)) * hours
        inflow = min(inflow, ctx.bulk_l, DAY_TANK_L - g.day_l)
    g.burn_lph = burn_lph(load_fraction, ctx.running)
    g.day_l = max(0.0, min(DAY_TANK_L, g.day_l + inflow - g.burn_lph * hours))
    _pumps(g)
    g.dp_psi = filter_dp(g, g.burn_lph)
    low = g.level_pct <= LVL_LAG_START
    if low != g.low_alarm:
        g.low_alarm = low
        events.append({"event": "gen_fuel_low" if low else "gen_fuel_normal",
                       "level_pct": round(g.level_pct, 1)})
    if ctx.running and not g.shutdown:
        if g.level_pct <= LVL_CRITICAL:
            g.shutdown = "LOW FUEL (day tank critical)"
        elif g.dp_psi >= DP_STARVE_PSI:
            g.shutdown = "LOW FUEL PRESSURE (filter restriction)"
        if g.shutdown:
            events.append({"event": "gen_shutdown", "cause": g.shutdown})
    return events, inflow


# ── Actions ──────────────────────────────────────────────────────────
def interlock(g: GenSet, action: str, ctx: GenContext) -> str | None:
    if action not in ACTIONS:
        return f"unknown generator action {action!r}"
    if action.startswith("ECS_"):
        mode = action[4:]
        if g.ecs_mode == mode:
            return f"Engine control is already in {mode}."
        if mode == ECS_RUN:
            return available(g) if not ctx.running else "Engine is already running."
        return None
    if action == "ESTOP_PUSH":
        return "Emergency stop is already pushed in." if g.estop else None
    if action == "ESTOP_RELEASE":
        return None if g.estop else "Emergency stop is not pushed in."
    if action in ("HEATER_ON", "HEATER_OFF"):
        on = action == "HEATER_ON"
        return f"Heater breaker is already {'ON' if on else 'OFF'}." if g.heater_on == on else None
    if action[:2] in ("P1", "P2") and action[2] == "_":
        pump = g.p1 if action.startswith("P1") else g.p2
        mode = action[3:]
        return f"{action[:2]} selector is already {mode}." if pump.mode == mode else None
    if action.startswith("RESET_P"):
        pump = g.p1 if action == "RESET_P1_OL" else g.p2
        return None if pump.overload else "The overload relay is not tripped."
    if action.startswith("FILTER_"):
        sel = action[7:]
        return f"Filter selector is already on {sel}." if g.filter_sel == sel else None
    if action.startswith(("DRAIN_", "CHANGE_ELEMENT_")):
        side = action[-1]
        if ctx.running and g.filter_sel in (side, FILTER_BOTH):
            return (f"Filter {side} is in service with the engine running: turn the selector "
                    f"to the other filter first.")
        if action.startswith("DRAIN_") and g.water[side] <= 0:
            return f"Bowl {side} shows no water."
        return None
    if action == "CLEAN_BASIN":
        return None if g.leak_present else "The basin is dry."
    if action == "RESET_LEAK":
        if not g.leak_latched:
            return "No leak alarm to reset."
        if g.leak_present:
            return "Fuel is still in the basin: clean it before resetting the float."
        return None
    return None


def apply(g: GenSet, action: str, ctx: GenContext) -> str | None:
    """Apply a permitted action. Returns an engine effect for the
    controller: "start", "stop", "estop" or None."""
    effect = None
    if action.startswith("ECS_"):
        g.ecs_mode = action[4:]
        if g.ecs_mode == ECS_STOP:
            if ctx.running:
                effect = "stop"
            if not g.estop and g.level_pct > LVL_CRITICAL:
                g.shutdown = None              # STOP / RESET clears latched faults
        elif g.ecs_mode == ECS_RUN:
            effect = "start"
    elif action == "ESTOP_PUSH":
        g.estop = True
        g.shutdown = "EMERGENCY STOP"
        effect = "estop"
    elif action == "ESTOP_RELEASE":
        g.estop = False
    elif action == "HEATER_ON":
        g.heater_on = True
    elif action == "HEATER_OFF":
        g.heater_on = False
    elif action[:2] in ("P1", "P2") and action[2] == "_":
        (g.p1 if action.startswith("P1") else g.p2).mode = action[3:]
    elif action.startswith("RESET_P"):
        (g.p1 if action == "RESET_P1_OL" else g.p2).overload = False
    elif action.startswith("FILTER_"):
        g.filter_sel = action[7:]
    elif action.startswith("DRAIN_"):
        g.water[action[-1]] = 0.0
    elif action.startswith("CHANGE_ELEMENT_"):
        g.clog[action[-1]] = 0.0
        g.water[action[-1]] = 0.0
    elif action == "CLEAN_BASIN":
        g.leak_present = False
    elif action == "RESET_LEAK":
        g.leak_latched = False
    _pumps(g)
    return effect


def describe(g: GenSet, ctx: GenContext) -> dict[str, Any]:
    return {
        "ecs_mode": g.ecs_mode, "estop": g.estop, "shutdown": g.shutdown,
        "heater_on": g.heater_on, "coolant_c": round(g.coolant_c, 1),
        "coolant_low": cold(g) and not ctx.running,
        "day_tank_l": round(g.day_l), "day_tank_pct": round(g.level_pct, 1),
        "day_tank_capacity_l": DAY_TANK_L,
        "levels": {"hi_hi": LVL_HI_HI, "pump_stop": LVL_PUMP_STOP, "lead_start": LVL_LEAD_START,
                   "lag_start_low": LVL_LAG_START, "critical": LVL_CRITICAL},
        "hi_hi": g.level_pct >= LVL_HI_HI, "low_alarm": g.low_alarm,
        "pumps": [
            {"id": "P-1", "role": "lead", "mode": g.p1.mode, "running": g.p1.running, "overload": g.p1.overload},
            {"id": "P-2", "role": "lag", "mode": g.p2.mode, "running": g.p2.running, "overload": g.p2.overload},
        ],
        "pump_flow_lph": PUMP_FLOW_LPH,
        "discharge_psig": 22.0 if g.solenoid_open and ctx.bulk_l > 0 else 0.0,
        "solenoid_open": g.solenoid_open,
        "filter": {"selected": g.filter_sel, "dp_psi": round(g.dp_psi, 2),
                   "dp_alarm_psi": DP_ALARM_PSI, "dp_starve_psi": DP_STARVE_PSI,
                   "water_pct": {k: round(v, 1) for k, v in g.water.items()},
                   "clog": {k: round(v, 2) for k, v in g.clog.items()}},
        "dp_alarm": g.dp_psi >= DP_ALARM_PSI,
        "water_alarm": any(w >= WATER_ALARM_PCT for w in g.water.values()),
        "leak": g.leak_latched, "leak_present": g.leak_present,
        "burn_lph": round(g.burn_lph, 1),
        "run_hours_left": (round(g.day_l / g.burn_lph, 2) if g.burn_lph > 0 else None),
        "available_reason": available(g),
        "time_scale": GEN_TIME_SCALE,
        "model_note": (f"Fuel and coolant time compressed x{GEN_TIME_SCALE:g}. Fuel curve from a "
                       "Cummins DQLH 2750 kW data sheet; pump flow, filter and heater values are model."),
        "actions": [
            {"action": a, "label": ACTION_LABELS[a],
             "permitted": (r := interlock(g, a, ctx)) is None, "blocked_reason": r}
            for a in ACTIONS
        ],
    }
