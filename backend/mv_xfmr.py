"""
backend/mv_xfmr.py
==================
L2 (2026-11-26) -- Utility transformer of each path, 27.5 kV delta /
13.8 kV wye-grounded, as an operator handles it in the substation:
primary circuit switcher 52-T, de-energized tap changer (DETC) under a
Kirk-type key interlock, the marshalling-box instruments (top oil and
winding temperature, liquid level, nitrogen blanket) and the
protection that removes it from service (63 sudden pressure, 87T
differential, 86T lockout, 26 / 49 temperature trips).

PURE: no clock, no I/O. The device controller supplies the context
(grid present, 52-U open or closed, load in MVA, time step).

Key interlock (trapped-key chain, normal service in brackets):
  K1  [in the 52-U lock]  turning it locks 52-U OPEN and frees K1
  L-T 52-T lock: takes K1, and only with 52-T OPEN, locks 52-T open,
      traps K1 and releases K2       [K2 trapped here in service]
  L-D DETC handle lock: K2 unlocks the handle and stays trapped until
      the handle is locked again on a detent
So the DETC handle can only move with 52-U locked open and the primary
open: the transformer is de-energized from both sides. IEEE C57.131
scope: a DETC "may be operated only while the transformer is not
energized" (verified on the ANSI webstore abstract, 2026-11-26).

Training hazard (off unless a drill or instructor injects it): a SPARE
DETC key left in the marshalling box defeats the chain. Moving the
handle on an energized transformer is modelled as an internal arc:
63 and 87T operate, 86T locks out, 52-T and 52-U trip, and the
transformer is declared damaged (re-energizing needs testing that is
not simulated: DGA, turns ratio, insulation resistance).

Thermal model: IEEE C57.91 Clause 7 form (exponential top-oil rise,
hot-spot gradient as a power of load). The exponents, time constants,
loss ratio and the 15/20/25 MVA ONAN/ONAF1/ONAF2 ratings are TYPICAL
VALUES, not this unit's test report, and the exponents were not
checked against the text of the standard. Hot-spot rise 80 C at rated
load is the IEEE C57.12.00 limit for 65 C rise transformers (quoted in
the IEEE Std 1538 introduction). Thermal time runs THERMAL_TIME_SCALE
times faster than the wall clock so a drill can show it; the UI says
so. Liquid level and nitrogen pressure are illustrative linear gauges.

ANSI / IEEE C37.2 numbers used: 26 apparatus thermal device, 49
transformer thermal relay, 52 AC breaker, 63 pressure switch, 86
lockout relay, 87 differential relay.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# ── Nameplate (model) ────────────────────────────────────────────────
PRIMARY_KV = 27.5
SECONDARY_KV = 13.8
VECTOR = "27.5 kV delta / 13.8 kV wye, solidly grounded (model)"
LIQUID = "natural ester (FR3 type), sealed tank, nitrogen blanket (model)"
STAGES = ("ONAN", "ONAF1", "ONAF2")
RATING_MVA = {"ONAN": 15.0, "ONAF1": 20.0, "ONAF2": 25.0}    # typical 15/20/25
# DETC: 5 positions on the HV winding. Position 1 = 105 % primary tap.
TAPS = {1: 5.0, 2: 2.5, 3: 0.0, 4: -2.5, 5: -5.0}
NOMINAL_TAP = 3

# ── Thermal (typical values, see the module docstring) ───────────────
AMBIENT_C = 30.0
TOP_OIL_RISE_R = 55.0          # C over ambient at the stage rating
HOT_SPOT_GRAD_R = 25.0         # C hot spot over top oil at rating (55 + 25 = 80)
LOSS_RATIO_R = 4.5             # load loss / no-load loss at rating
EXP_N = {"ONAN": 0.8, "ONAF1": 0.9, "ONAF2": 0.9}
EXP_M = 0.8
TAU_OIL_MIN = {"ONAN": 180.0, "ONAF1": 120.0, "ONAF2": 120.0}
TAU_WINDING_MIN = 7.0
THERMAL_TIME_SCALE = 60.0      # 1 s of wall clock = 1 min of thermal time
# Fan control on winding temperature (on / off, hysteresis), model values
FAN1_ON_C, FAN1_OFF_C = 75.0, 60.0
FAN2_ON_C, FAN2_OFF_C = 90.0, 75.0
# Spec of the operator master document for the oil monitor; winding
# settings are model values.
OIL_ALARM_C, OIL_TRIP_C = 85.0, 95.0
WINDING_ALARM_C, WINDING_TRIP_C = 110.0, 130.0

# ── Keys ─────────────────────────────────────────────────────────────
KEY_IN_52U = "L-U"
KEY_IN_52T = "L-T"
KEY_IN_DETC = "L-D"
KEY_HAND = "HAND"

FANS_AUTO, FANS_ON, FANS_OFF = "AUTO", "ON", "OFF"
FAN_MODES = (FANS_AUTO, FANS_ON, FANS_OFF)

OPEN_52T = "OPEN_52T"
CLOSE_52T = "CLOSE_52T"
KEY_LOCK_52U = "KEY_LOCK_52U"
KEY_UNLOCK_52U = "KEY_UNLOCK_52U"
KEY_LOCK_52T = "KEY_LOCK_52T"
KEY_UNLOCK_52T = "KEY_UNLOCK_52T"
DETC_UNLOCK = "DETC_UNLOCK"
DETC_LOCK = "DETC_LOCK"
DETC_POS_UP = "DETC_POS_UP"        # position number + 1 (lower HV tap)
DETC_POS_DOWN = "DETC_POS_DOWN"    # position number - 1 (higher HV tap)
DETC_SPARE_KEY = "DETC_SPARE_KEY"
RESET_63 = "RESET_63"
RESET_87T = "RESET_87T"
RESET_86T = "RESET_86T"
SET_FANS_AUTO = "FANS_AUTO"
SET_FANS_ON = "FANS_ON"
SET_FANS_OFF = "FANS_OFF"

ACTIONS = (OPEN_52T, CLOSE_52T, KEY_LOCK_52U, KEY_UNLOCK_52U, KEY_LOCK_52T,
           KEY_UNLOCK_52T, DETC_UNLOCK, DETC_LOCK, DETC_POS_UP, DETC_POS_DOWN,
           DETC_SPARE_KEY, RESET_63, RESET_87T, RESET_86T,
           SET_FANS_AUTO, SET_FANS_ON, SET_FANS_OFF)

ACTION_LABELS = {
    OPEN_52T: "Open primary circuit switcher 52-T",
    CLOSE_52T: "Close primary circuit switcher 52-T",
    KEY_LOCK_52U: "Kirk lock 52-U open and remove key K1",
    KEY_UNLOCK_52U: "Return key K1 to 52-U (free to close)",
    KEY_LOCK_52T: "Insert K1 at 52-T, lock it open, take K2",
    KEY_UNLOCK_52T: "Return K2 to 52-T, take K1 (52-T free)",
    DETC_UNLOCK: "Unlock the DETC handle with K2",
    DETC_LOCK: "Lock the DETC handle on its detent, remove the key",
    DETC_POS_UP: "DETC handle to the next position number",
    DETC_POS_DOWN: "DETC handle to the previous position number",
    DETC_SPARE_KEY: "Unlock the DETC handle with the spare key (defeats the interlock)",
    RESET_63: "Reset the 63 sudden-pressure relay target",
    RESET_87T: "Reset the 87T differential relay target",
    RESET_86T: "Reset the 86T lockout relay",
    SET_FANS_AUTO: "Cooling fans selector to AUTO",
    SET_FANS_ON: "Cooling fans selector to HAND (both stages ON)",
    SET_FANS_OFF: "Cooling fans selector to OFF",
}


@dataclass
class Transformer:
    path: str
    primary_closed: bool = True       # 52-T
    tap: int = NOMINAL_TAP
    k1: str = KEY_IN_52U
    k2: str = KEY_IN_52T
    detc_unlocked_by: str | None = None    # "K2" | "SPARE" | None
    spare_key_available: bool = False      # training hazard
    fan_mode: str = FANS_AUTO
    fan1: bool = False
    fan2: bool = False
    top_oil_c: float | None = None        # None until the first tick
    winding_c: float | None = None
    load_mva: float = 0.0
    flag_63: bool = False
    flag_87t: bool = False
    lockout_86t: bool = False
    trip_cause: str | None = None
    damaged: bool = False
    oil_alarm: bool = False
    winding_alarm: bool = False

    def copy(self) -> Transformer:
        return Transformer(**self.__dict__)


@dataclass(frozen=True)
class XfmrContext:
    """Facts the controller supplies for one evaluation."""
    grid_ok: bool                 # utility 27.5 kV present upstream of 52-T
    main_u_closed: bool           # 52-U closed on the 13.8 kV side
    grid_kv: float = PRIMARY_KV
    actor: str = ""


# ── State helpers ────────────────────────────────────────────────────
def energized(t: Transformer, grid_ok: bool) -> bool:
    return grid_ok and t.primary_closed and not t.lockout_86t and not t.damaged


def stage(t: Transformer) -> str:
    return "ONAF2" if t.fan2 else ("ONAF1" if t.fan1 else "ONAN")


def secondary_kv(t: Transformer, grid_ok: bool, grid_kv: float = PRIMARY_KV) -> float:
    """13.8 kV side voltage at no load: more HV turns (position 1)
    lowers it. Standard DETC convention; verify on the nameplate."""
    if not energized(t, grid_ok):
        return 0.0
    return SECONDARY_KV * (grid_kv / PRIMARY_KV) / (1.0 + TAPS[t.tap] / 100.0)


def _ultimate(load_mva: float, stg: str, live: bool) -> tuple[float, float]:
    """Steady-state top-oil rise and hot-spot gradient (C)."""
    if not live:
        return 0.0, 0.0
    k = load_mva / RATING_MVA[stg]
    r = LOSS_RATIO_R
    oil = TOP_OIL_RISE_R * ((k * k * r + 1.0) / (r + 1.0)) ** EXP_N[stg]
    grad = HOT_SPOT_GRAD_R * k ** (2.0 * EXP_M) if k > 0 else 0.0
    return oil, grad


def _fans(t: Transformer) -> None:
    if t.fan_mode == FANS_ON:
        t.fan1 = t.fan2 = True
        return
    if t.fan_mode == FANS_OFF:
        t.fan1 = t.fan2 = False
        return
    w = t.winding_c if t.winding_c is not None else AMBIENT_C
    if w >= FAN1_ON_C:
        t.fan1 = True
    elif w < FAN1_OFF_C:
        t.fan1 = False
    if w >= FAN2_ON_C:
        t.fan2 = True
    elif w < FAN2_OFF_C:
        t.fan2 = False


def settle(t: Transformer, load_mva: float, live: bool, ambient_c: float = AMBIENT_C) -> None:
    """Start from steady state (first evaluation, or a reset)."""
    t.load_mva = load_mva if live else 0.0
    t.fan1 = t.fan2 = False
    for _ in range(4):        # let AUTO fans find their stage
        oil, grad = _ultimate(t.load_mva, stage(t), live)
        t.top_oil_c, t.winding_c = ambient_c + oil, ambient_c + oil + grad
        before = (t.fan1, t.fan2)
        _fans(t)
        if (t.fan1, t.fan2) == before:
            break


def tick(t: Transformer, dt_s: float, load_mva: float, live: bool,
         ambient_c: float = AMBIENT_C) -> list[dict[str, Any]]:
    """Advance the thermal state by ``dt_s`` seconds of WALL clock.
    Returns events: alarm raised / cleared, thermal trip."""
    if t.top_oil_c is None or t.winding_c is None:
        settle(t, load_mva, live, ambient_c)
        return []
    t.load_mva = load_mva if live else 0.0
    _fans(t)
    stg = stage(t)
    oil_u, grad_u = _ultimate(t.load_mva, stg, live)
    minutes = max(0.0, dt_s) * THERMAL_TIME_SCALE / 60.0
    oil_rise = t.top_oil_c - ambient_c
    grad = t.winding_c - t.top_oil_c
    oil_rise = oil_u + (oil_rise - oil_u) * math.exp(-minutes / TAU_OIL_MIN[stg])
    grad = grad_u + (grad - grad_u) * math.exp(-minutes / TAU_WINDING_MIN)
    t.top_oil_c = ambient_c + oil_rise
    t.winding_c = t.top_oil_c + grad
    _fans(t)
    events: list[dict[str, Any]] = []
    for name, value, alarm_at, attr in (
        ("oil", t.top_oil_c, OIL_ALARM_C, "oil_alarm"),
        ("winding", t.winding_c, WINDING_ALARM_C, "winding_alarm"),
    ):
        on = value >= alarm_at
        if on != getattr(t, attr):
            setattr(t, attr, on)
            events.append({"event": "xfmr_temperature_alarm" if on else "xfmr_temperature_normal",
                           "sensor": name, "value_c": round(value, 1), "setpoint_c": alarm_at})
    if not t.lockout_86t and live:
        if t.top_oil_c >= OIL_TRIP_C:
            events.append(_lockout(t, "26 top-oil temperature trip"))
        elif t.winding_c >= WINDING_TRIP_C:
            events.append(_lockout(t, "49 winding temperature trip"))
    return events


def _lockout(t: Transformer, cause: str) -> dict[str, Any]:
    t.lockout_86t = True
    t.trip_cause = cause
    return {"event": "xfmr_lockout", "relay": "86T", "cause": cause}


# ── Interlocks ───────────────────────────────────────────────────────
def interlock(t: Transformer, action: str, ctx: XfmrContext) -> str | None:
    """Why ``action`` is not permitted now (None when it is)."""
    if action not in ACTIONS:
        return f"unknown transformer action {action!r}"
    if action == OPEN_52T:
        if not t.primary_closed:
            return "52-T is already open."
        return None
    if action == CLOSE_52T:
        if t.primary_closed:
            return "52-T is already closed."
        if t.k1 == KEY_IN_52T:
            return "Key interlock: 52-T is locked open (K1 trapped). Return K2 to release it."
        if t.damaged:
            return ("Transformer out of service after an internal fault: re-energizing needs "
                    "DGA, turns-ratio and insulation tests (not simulated).")
        if t.lockout_86t:
            return "86T lockout is tripped: its contacts hold 52-T open. Investigate and reset it."
        if t.detc_unlocked_by:
            return "DETC handle is unlocked: lock it on a detent before energizing."
        return None
    if action == KEY_LOCK_52U:
        if t.k1 != KEY_IN_52U:
            return "Key K1 is not in the 52-U lock."
        if ctx.main_u_closed:
            return "52-U is closed: the K1 lock bolt cannot be thrown. Open 52-U first."
        return None
    if action == KEY_UNLOCK_52U:
        return None if t.k1 == KEY_HAND else "You do not hold key K1."
    if action == KEY_LOCK_52T:
        if t.k1 != KEY_HAND:
            return "The 52-T lock needs key K1 (released by locking 52-U open)."
        if t.primary_closed:
            return "52-T is closed: the lock bolt cannot be thrown. Open 52-T first."
        return None
    if action == KEY_UNLOCK_52T:
        if t.k1 != KEY_IN_52T:
            return "52-T is not key-locked."
        if t.k2 != KEY_HAND:
            return "The 52-T lock needs key K2 back (it is trapped in the DETC lock)."
        return None
    if action == DETC_UNLOCK:
        if t.detc_unlocked_by:
            return "DETC handle is already unlocked."
        if t.k2 != KEY_HAND:
            return ("The DETC lock needs key K2: it is released only by locking 52-T open "
                    "with K1 (52-U locked open first).")
        return None
    if action == DETC_SPARE_KEY:
        if t.detc_unlocked_by:
            return "DETC handle is already unlocked."
        if not t.spare_key_available:
            return "No spare DETC key: the key cabinet is controlled."
        return None
    if action == DETC_LOCK:
        return None if t.detc_unlocked_by else "DETC handle is already locked."
    if action in (DETC_POS_UP, DETC_POS_DOWN):
        if not t.detc_unlocked_by:
            return "DETC handle is locked (key interlock)."
        if t.damaged:
            return "Transformer damaged: the tap changer is out of service."
        nxt = t.tap + (1 if action == DETC_POS_UP else -1)
        if nxt not in TAPS:
            return f"DETC is at position {t.tap}: end stop."
        return None
    if action == RESET_63:
        return None if t.flag_63 else "63 target is not raised."
    if action == RESET_87T:
        return None if t.flag_87t else "87T target is not raised."
    if action == RESET_86T:
        if not t.lockout_86t:
            return "86T lockout is not tripped."
        if t.flag_63 or t.flag_87t:
            return "Record and reset the 63 / 87T targets before resetting 86T."
        if t.oil_alarm or t.winding_alarm:
            return "Temperature still above the alarm setting: let the transformer cool."
        return None
    if action == SET_FANS_AUTO:
        return None if t.fan_mode != FANS_AUTO else "Fans selector is already AUTO."
    if action == SET_FANS_ON:
        return None if t.fan_mode != FANS_ON else "Fans selector is already HAND."
    if action == SET_FANS_OFF:
        return None if t.fan_mode != FANS_OFF else "Fans selector is already OFF."
    return None


def apply(t: Transformer, action: str, ctx: XfmrContext) -> str | None:
    """Apply a permitted action. Returns an effect for the controller:
    "primary_open", "primary_close", "internal_fault" or None."""
    if action == OPEN_52T:
        t.primary_closed = False
        return "primary_open"
    if action == CLOSE_52T:
        t.primary_closed = True
        return "primary_close"
    if action == KEY_LOCK_52U:
        t.k1 = KEY_HAND
    elif action == KEY_UNLOCK_52U:
        t.k1 = KEY_IN_52U
    elif action == KEY_LOCK_52T:
        t.k1, t.k2 = KEY_IN_52T, KEY_HAND
    elif action == KEY_UNLOCK_52T:
        t.k1, t.k2 = KEY_HAND, KEY_IN_52T
    elif action == DETC_UNLOCK:
        t.k2, t.detc_unlocked_by = KEY_IN_DETC, "K2"
    elif action == DETC_SPARE_KEY:
        t.detc_unlocked_by = "SPARE"
    elif action == DETC_LOCK:
        if t.detc_unlocked_by == "K2":
            t.k2 = KEY_HAND
        t.detc_unlocked_by = None
    elif action in (DETC_POS_UP, DETC_POS_DOWN):
        if energized(t, ctx.grid_ok):
            # Off-circuit contacts parting under voltage: arc in oil.
            t.flag_63 = t.flag_87t = True
            t.lockout_86t = True
            t.primary_closed = False
            t.damaged = True
            t.trip_cause = "63 sudden pressure + 87T differential (internal arc, DETC moved energized)"
            return "internal_fault"
        t.tap += 1 if action == DETC_POS_UP else -1
    elif action == RESET_63:
        t.flag_63 = False
    elif action == RESET_87T:
        t.flag_87t = False
    elif action == RESET_86T:
        t.lockout_86t = False
        t.trip_cause = None
    elif action == SET_FANS_AUTO:
        t.fan_mode = FANS_AUTO
    elif action == SET_FANS_ON:
        t.fan_mode = FANS_ON
    elif action == SET_FANS_OFF:
        t.fan_mode = FANS_OFF
    if action in (SET_FANS_AUTO, SET_FANS_ON, SET_FANS_OFF):
        _fans(t)
    return None


def lockout(t: Transformer, cause: str) -> dict[str, Any]:
    """86T operated by protection (controller use)."""
    return _lockout(t, cause)


def u_lock_reason(t: Transformer) -> str | None:
    """Why 52-U may not close because of this transformer's key lock."""
    if t.k1 != KEY_IN_52U:
        return "Key interlock: K1 is out of the 52-U lock, 52-U is locked open."
    return None


# ── Gauges (illustrative) ────────────────────────────────────────────
def liquid_level_pct(t: Transformer) -> float:
    oil = t.top_oil_c if t.top_oil_c is not None else AMBIENT_C
    return max(0.0, min(100.0, 50.0 + 0.6 * (oil - 25.0)))


def nitrogen_psig(t: Transformer) -> float:
    oil = t.top_oil_c if t.top_oil_c is not None else AMBIENT_C
    return max(-8.0, min(10.0, 2.0 + 0.10 * (oil - 25.0)))


def describe(t: Transformer, ctx: XfmrContext) -> dict[str, Any]:
    live = energized(t, ctx.grid_ok)
    stg = stage(t)
    oil = t.top_oil_c if t.top_oil_c is not None else AMBIENT_C
    wdg = t.winding_c if t.winding_c is not None else AMBIENT_C
    return {
        "id": f"xfmr_{t.path}",
        "nameplate": {
            "title": f"UTILITY TRANSFORMER {t.path.upper()}",
            "rating": "15 / 20 / 25 MVA ONAN / ONAF1 / ONAF2 (typical, model)",
            "voltage": VECTOR, "liquid": LIQUID,
        },
        "energized": live,
        "primary_closed": t.primary_closed,
        "grid_ok": ctx.grid_ok,
        "grid_kv": round(ctx.grid_kv, 2),
        "secondary_kv": round(secondary_kv(t, ctx.grid_ok, ctx.grid_kv), 3),
        "tap": t.tap,
        "tap_pct": TAPS[t.tap],
        "taps": {str(k): v for k, v in TAPS.items()},
        "key_k1": t.k1,
        "key_k2": t.k2,
        "detc_locked": t.detc_unlocked_by is None,
        "detc_unlocked_by": t.detc_unlocked_by,
        "spare_key_available": t.spare_key_available,
        "fan_mode": t.fan_mode,
        "fan1": t.fan1,
        "fan2": t.fan2,
        "cooling_stage": stg,
        "rating_mva": RATING_MVA[stg],
        "load_mva": round(t.load_mva, 2),
        "load_pct": round(t.load_mva / RATING_MVA[stg] * 100.0, 1),
        "top_oil_c": round(oil, 1),
        "winding_c": round(wdg, 1),
        "ambient_c": AMBIENT_C,
        "liquid_level_pct": round(liquid_level_pct(t), 1),
        "nitrogen_psig": round(nitrogen_psig(t), 1),
        "oil_alarm": t.oil_alarm,
        "winding_alarm": t.winding_alarm,
        "flag_63": t.flag_63,
        "flag_87t": t.flag_87t,
        "lockout_86t": t.lockout_86t,
        "trip_cause": t.trip_cause,
        "damaged": t.damaged,
        "setpoints": {
            "oil_alarm_c": OIL_ALARM_C, "oil_trip_c": OIL_TRIP_C,
            "winding_alarm_c": WINDING_ALARM_C, "winding_trip_c": WINDING_TRIP_C,
            "fan1_on_c": FAN1_ON_C, "fan2_on_c": FAN2_ON_C,
        },
        "thermal_time_scale": THERMAL_TIME_SCALE,
        "model_note": ("Thermal model in the IEEE C57.91 Clause 7 form with typical constants, "
                       f"time compressed x{THERMAL_TIME_SCALE:g}. Gauges are illustrative."),
        "actions": [
            {"action": a, "label": ACTION_LABELS[a],
             "permitted": (r := interlock(t, a, ctx)) is None, "blocked_reason": r}
            for a in ACTIONS
        ],
    }
