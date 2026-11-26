"""
backend/mv_cubicle.py
=====================
L1 (2026-11-15) -- Draw-out vacuum circuit breaker cubicles for the
two 13.8 kV mains of each path: 52-U (utility incomer) and 52-GM
(generator main).

Each cubicle has the mechanical state an operator handles at the
switchgear: racking position (CONNECTED / TEST / DISCONNECTED), the
stored-energy closing spring (motor charged, or manual charging with
the pump handle), the ANSI 86 lockout relay that opens the close
circuit, and a personal padlock on the racking mechanism.

The breaker's OPEN / CLOSED state in CONNECTED is not stored here: it
is the transfer controller's state (52-U closed on UTILITY, 52-GM
closed on GENERATORS), so the drawing, the alarms and the drills keep
one source of truth. In TEST the breaker is off its primary contacts
(control power on, bus isolated) and can be closed and opened to test
it or to discharge its springs: that state lives here.

PURE: no clock, no I/O. The device controller supplies the context.

Interlocks (fail-safe):
  C1  never rack a closed breaker (in or out)
  C2  never close with the closing spring discharged
  C3  never close with the 86 lockout tripped (it opens the close
      circuit); the 86 also trips the breaker when operated
  C4  in DISCONNECTED the secondary contacts are parted: no control
      power, so no electrical close and no motor charging. The push
      buttons on the breaker front then act MECHANICALLY (manual close
      and trip, as on common draw-out breakers; verify against the
      vendor manual): the breaker can be cycled off the bus to release
      its springs after the lock is on (OSHA 1910.147(d)(5)(i): stored
      energy is relieved after the lockout devices are applied)
  C5  never rack in a padlocked breaker
  C6  the padlock goes on the racking mechanism in DISCONNECTED only
  C7  only the person who applied a padlock removes it
  C8  operations at the switchgear need the transfer controller in
      LOCAL (the remote and automatic controls are then blocked);
      tripping the 86 is the exception: it is always available

The lockout practice follows OSHA 29 CFR 1910.147 (stored energy
relieved after isolation, removal by the employee who applied the
device). Paragraph numbers are quoted in the drill texts from memory
and should be checked against the current regulation.

HONEST SCOPE: supervisory training model. Spring charging time and
pump count are model values, not a vendor's. No arc-flash study
exists for this switchgear: the label says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CONNECTED = "CONNECTED"
TEST = "TEST"
DISCONNECTED = "DISCONNECTED"
POSITIONS = (CONNECTED, TEST, DISCONNECTED)

BREAKER_U = "52-U"
BREAKER_GM = "52-GM"
BREAKERS = (BREAKER_U, BREAKER_GM)

SPRING_PUMPS_TO_CHARGE = 5        # model value
SPRING_MOTOR_CHARGE_S = 6.0       # model value

RACK_OUT = "RACK_OUT"
RACK_IN = "RACK_IN"
MOTOR_ON = "MOTOR_ON"
MOTOR_OFF = "MOTOR_OFF"
PUMP_SPRING = "PUMP_SPRING"
LOCAL_CLOSE = "LOCAL_CLOSE"
LOCAL_OPEN = "LOCAL_OPEN"
TRIP_86 = "TRIP_86"
RESET_86 = "RESET_86"
PADLOCK = "PADLOCK"
UNPADLOCK = "UNPADLOCK"

ACTIONS = (RACK_OUT, RACK_IN, MOTOR_ON, MOTOR_OFF, PUMP_SPRING, LOCAL_CLOSE,
           LOCAL_OPEN, TRIP_86, RESET_86, PADLOCK, UNPADLOCK)

ACTION_LABELS = {
    RACK_OUT: "Rack out one position",
    RACK_IN: "Rack in one position",
    MOTOR_ON: "Spring-charging motor ON",
    MOTOR_OFF: "Spring-charging motor OFF",
    PUMP_SPRING: "Pump the manual charging handle",
    LOCAL_CLOSE: "Push to close (local)",
    LOCAL_OPEN: "Push to open (local)",
    TRIP_86: "Trip the 86 lockout relay",
    RESET_86: "Reset the 86 lockout relay",
    PADLOCK: "Apply personal padlock (racking)",
    UNPADLOCK: "Remove personal padlock",
}

NAMEPLATES = {
    BREAKER_U: {"title": "UTILITY INCOMER", "function": "Main from XFMR 27.5/13.8 kV"},
    BREAKER_GM: {"title": "GENERATOR MAIN", "function": "Main from the 13.8 kV generator bus"},
}
RATING = {
    "class": "15 kV class vacuum breaker, draw-out (model)",
    "voltage": "13.8 kV, 60 Hz",
    "continuous": "1200 A frame (model assumption, not a design value)",
    "control": "125 VDC close and trip",
}
ARC_FLASH = {
    "study": None,
    "label": "ARC FLASH STUDY NOT PERFORMED",
    "note": ("Simulated equipment: no incident energy, arc-flash boundary or PPE "
             "category exists. A real label comes from an engineering study "
             "(NFPA 70E 130.5, CSA Z462)."),
    "shock": "13.8 kV AC: approach boundaries per NFPA 70E Table 130.4(E)(a)",
}


@dataclass
class Cubicle:
    breaker: str
    racking: str = CONNECTED
    test_closed: bool = False
    spring_charged: bool = True
    motor_on: bool = True
    pumps: int = 0
    charge_at: float | None = None
    lockout_86: bool = False
    padlock: str | None = None

    def copy(self) -> Cubicle:
        return Cubicle(**self.__dict__)


@dataclass(frozen=True)
class CubicleContext:
    """Facts the controller supplies for one evaluation."""
    now: float
    local_authority: bool
    main_closed: bool
    # Why the breaker cannot close onto the bus in CONNECTED (plant
    # interlock: the other main, no voltage, generation short), or None.
    plant_close_reason: str | None = None
    actor: str = ""


def is_closed(c: Cubicle, main_closed: bool) -> bool:
    return main_closed if c.racking == CONNECTED else c.test_closed


def tick(c: Cubicle, now: float) -> bool:
    """Advance the charging motor. True when the spring just charged."""
    if (c.charge_at is not None and c.motor_on and c.racking != DISCONNECTED
            and now >= c.charge_at):
        c.charge_at = None
        c.spring_charged = True
        c.pumps = 0
        return True
    return False


def interlock(c: Cubicle, action: str, ctx: CubicleContext) -> str | None:
    """Why ``action`` is not permitted now (None when it is)."""
    if action not in ACTIONS:
        return f"unknown switchgear action {action!r}"
    if action != TRIP_86 and not ctx.local_authority:
        return "C8: take local control first (transfer controller to LOCAL)."
    closed = is_closed(c, ctx.main_closed)
    b = c.breaker
    if action in (RACK_OUT, RACK_IN):
        if closed:
            return f"C1: {b} is closed: the racking mechanism is blocked. Open it first."
        if action == RACK_OUT and c.racking == DISCONNECTED:
            return f"{b} is already DISCONNECTED."
        if action == RACK_IN:
            if c.padlock:
                return f"C5: {b} racking is padlocked by {c.padlock}."
            if c.racking == CONNECTED:
                return f"{b} is already CONNECTED."
        return None
    if action == MOTOR_ON:
        return "Charging motor is already ON." if c.motor_on else None
    if action == MOTOR_OFF:
        return "Charging motor is already OFF." if not c.motor_on else None
    if action == PUMP_SPRING:
        return "Closing spring is already charged." if c.spring_charged else None
    if action == LOCAL_CLOSE:
        if closed:
            return f"{b} is already closed."
        if c.lockout_86 and c.racking != DISCONNECTED:
            return f"C3: 86 lockout tripped: the {b} close circuit is open. Reset the 86 first."
        if not c.spring_charged:
            return f"C2: {b} closing spring is discharged."
        if c.racking == CONNECTED and ctx.plant_close_reason:
            return ctx.plant_close_reason
        return None
    if action == LOCAL_OPEN:
        return None if closed else f"{b} is already open."
    if action == TRIP_86:
        return "86 lockout is already tripped." if c.lockout_86 else None
    if action == RESET_86:
        return None if c.lockout_86 else "86 lockout is not tripped."
    if action == PADLOCK:
        if c.padlock:
            return f"Racking is already padlocked by {c.padlock}."
        if c.racking != DISCONNECTED:
            return f"C6: rack {b} to DISCONNECTED before applying the padlock."
        return None
    if action == UNPADLOCK:
        if not c.padlock:
            return "No padlock is applied."
        if ctx.actor and c.padlock != ctx.actor:
            return f"C7: only {c.padlock}, who applied the padlock, may remove it."
        return None
    return None


def apply(c: Cubicle, action: str, ctx: CubicleContext) -> str | None:
    """Apply a permitted action. Returns the effect on the in-service
    breaker for the controller: "main_close", "main_open" or None."""
    closed = is_closed(c, ctx.main_closed)
    if action == RACK_OUT:
        c.racking = TEST if c.racking == CONNECTED else DISCONNECTED
        c.test_closed = False
        _control_power_changed(c, ctx.now)
    elif action == RACK_IN:
        c.racking = TEST if c.racking == DISCONNECTED else CONNECTED
        c.test_closed = False
        _control_power_changed(c, ctx.now)
    elif action == MOTOR_ON:
        c.motor_on = True
        if not c.spring_charged and c.racking != DISCONNECTED:
            c.charge_at = ctx.now + SPRING_MOTOR_CHARGE_S
    elif action == MOTOR_OFF:
        c.motor_on = False
        c.charge_at = None
    elif action == PUMP_SPRING:
        c.pumps += 1
        if c.pumps >= SPRING_PUMPS_TO_CHARGE:
            c.spring_charged, c.pumps, c.charge_at = True, 0, None
    elif action == LOCAL_CLOSE:
        discharge(c, ctx.now)
        if c.racking == CONNECTED:
            return "main_close"
        c.test_closed = True
    elif action == LOCAL_OPEN:
        if c.racking == CONNECTED:
            return "main_open"
        c.test_closed = False
    elif action == TRIP_86:
        c.lockout_86 = True
        if closed:
            if c.racking == CONNECTED:
                return "main_open"
            c.test_closed = False
    elif action == RESET_86:
        c.lockout_86 = False
    elif action == PADLOCK:
        c.padlock = ctx.actor or "operator"
    elif action == UNPADLOCK:
        c.padlock = None
    return None


def discharge(c: Cubicle, now: float) -> None:
    """A close releases the closing spring; the motor recharges it
    when it has control power (not in DISCONNECTED)."""
    c.spring_charged = False
    c.pumps = 0
    c.charge_at = (now + SPRING_MOTOR_CHARGE_S
                   if c.motor_on and c.racking != DISCONNECTED else None)


def _control_power_changed(c: Cubicle, now: float) -> None:
    """Racking moved the secondary contacts: the charging motor stops
    in DISCONNECTED and resumes (if ON and needed) in TEST / CONNECTED."""
    if c.racking == DISCONNECTED:
        c.charge_at = None
    elif c.motor_on and not c.spring_charged and c.charge_at is None:
        c.charge_at = now + SPRING_MOTOR_CHARGE_S


def close_reason(c: Cubicle) -> str | None:
    """Why the in-service breaker cannot be closed by any control
    (remote, automatic or local), from the cubicle alone."""
    if c.racking != CONNECTED:
        return f"{c.breaker} is racked to {c.racking}: rack it in to CONNECTED first."
    if c.lockout_86:
        return f"86 lockout on {c.breaker} is tripped: reset it at the switchgear."
    if not c.spring_charged:
        state = "charging" if c.motor_on and c.charge_at is not None else "motor OFF"
        return f"{c.breaker} closing spring is discharged ({state})."
    return None


def describe(c: Cubicle, ctx: CubicleContext) -> dict[str, Any]:
    closed = is_closed(c, ctx.main_closed)
    return {
        "breaker": c.breaker,
        "nameplate": NAMEPLATES[c.breaker],
        "rating": RATING,
        "arc_flash": ARC_FLASH,
        "racking": c.racking,
        "closed": closed,
        "on_bus": c.racking == CONNECTED,
        "spring_charged": c.spring_charged,
        "motor_on": c.motor_on,
        "pumps": c.pumps,
        "pumps_needed": SPRING_PUMPS_TO_CHARGE,
        "charging_s_left": (round(max(0.0, c.charge_at - ctx.now), 1)
                            if c.charge_at is not None else None),
        "lockout_86": c.lockout_86,
        "padlock": c.padlock,
        "control_power": c.racking != DISCONNECTED,
        "actions": [
            {"action": a, "label": ACTION_LABELS[a],
             "permitted": (r := interlock(c, a, ctx)) is None, "blocked_reason": r}
            for a in ACTIONS
        ],
    }
