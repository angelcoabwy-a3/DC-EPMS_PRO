"""
backend/mv_wiring.py
====================
L5 (2026-11-26) -- Control compartment of the MV transfer lineup of one
path, as a technician troubleshoots it with the door open: the potential
transformer (PT) secondary fuses, terminal block TB-1 and a true-RMS
digital multimeter (Fluke 87V style: V AC, V DC, resistance with
continuity beep).

  F-1A  utility sensing PT secondary fuse: feeds the transfer controller
        and the ANSI 27 incomer undervoltage element
  F-1B  generator bus sensing PT secondary fuse: tells the controller the
        generator bus is live before 52-GM may close

Operator master specification (subsystem 2): if F-1A blows, the
controller reads 0 V AC on the utility PT secondary although the primary
is live, and starts a false emergency transfer: the classic field
diagnosis. Model readings of that text, flagged as such:
- F-1A also feeds the 27 element here, so a blown F-1A trips 52-U. Many
  real relays supervise their PT fuses (ANSI 60, loss of potential) and
  block the 27 trip instead; this model has no 60 element.
- F-1B as the generator bus sensing fuse is this model's reading of the
  "F-1A, F-1B" pair in the specification.
- Test points follow the specification: F-1A (120 V AC), P1-N1 (125 V DC
  station battery), 73-74 (two-wire engine start, dry contact) and the
  52CC / 52TC coil circuits. Readings are model values: 120 V AC nominal
  PT secondary, 132 V DC station battery float, contact and fuse
  resistances; the close circuit reads 0 V when the 86 lockout is
  tripped (it removes the positive from 52CC), the trip circuit reads
  battery voltage only with the breaker closed (52a in series).
- Measuring across a fuse in circuit: about 0 V if intact, about the
  supply voltage if blown. Resistance only with the holder pulled.
  Resistance on an energized point is flagged (the reading is invalid).

PURE: no clock, no I/O. The controller supplies the context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

FUSES = ("F-1A", "F-1B")
FUSE_KEY = {"F1A": "F-1A", "F1B": "F-1B"}
MODES = ("OFF", "VAC", "VDC", "OHM")
PT_SECONDARY_V = 120.0
STATION_DC_V = 132.0           # model: 125 V nominal station battery on float
FUSE_OHM = 0.1                 # model
CONTACT_OHM = 0.2              # model
POINTS = {
    "F1A_LINE": "F-1A line side to N (utility PT secondary)",
    "F1A_LOAD": "F-1A load side to N (to controller and ANSI 27)",
    "F1A_FUSE": "Across fuse F-1A",
    "F1B_LINE": "F-1B line side to N (generator bus PT secondary)",
    "F1B_LOAD": "F-1B load side to N (to controller)",
    "F1B_FUSE": "Across fuse F-1B",
    "P1_N1": "Station battery P1-N1 (125 V DC)",
    "T73_74": "Engine start contact 73-74 (two-wire, dry)",
    "CC_52U": "52-U close circuit 52CC to N1",
    "TC_52U": "52-U trip circuit 52TC to N1",
    "CC_52GM": "52-GM close circuit 52CC to N1",
    "TC_52GM": "52-GM trip circuit 52TC to N1",
}
FUSE_ACTIONS = ("PULL", "INSERT", "REPLACE")
ACTIONS = tuple(f"{v}_{k}" for k in FUSE_KEY for v in FUSE_ACTIONS) \
    + tuple(f"METER_{m}" for m in MODES) + tuple(f"MEASURE_{p}" for p in POINTS)


@dataclass
class Fuse:
    ok: bool = True
    pulled: bool = False

    @property
    def conducts(self) -> bool:
        return self.ok and not self.pulled


@dataclass
class ControlWiring:
    path: str
    fuses: dict[str, Fuse] = field(default_factory=lambda: {f: Fuse() for f in FUSES})
    meter: str = "OFF"
    measured: list[str] = field(default_factory=list)     # "POINT:MODE"
    readings: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class WiringContext:
    utility_pu: float = 1.0          # incomer voltage per unit (0 when dead)
    genbus_live: bool = False
    start_contact: bool = False
    u_closed: bool = True
    gm_closed: bool = False
    u_close_ok: bool = False         # close circuit healthy (86 reset)
    gm_close_ok: bool = True
    actor: str = ""


def utility_sensed(w: ControlWiring, utility_live: bool) -> bool:
    return utility_live and w.fuses["F-1A"].conducts


def genbus_sensed(w: ControlWiring, genbus_live: bool) -> bool:
    return genbus_live and w.fuses["F-1B"].conducts


def is_inspection(action: str) -> bool:
    return str(action).startswith(("METER_", "MEASURE_"))


def interlock(w: ControlWiring, action: str, ctx: WiringContext) -> str | None:
    if action not in ACTIONS:
        return f"unknown control wiring action {action!r}"
    if action.startswith("MEASURE_") and w.meter == "OFF":
        return "the meter is OFF: turn the selector to V AC, V DC or resistance first"
    verb, _, key = action.partition("_")
    if verb in FUSE_ACTIONS:
        f = w.fuses[FUSE_KEY[key]]
        name = FUSE_KEY[key]
        if verb == "PULL" and f.pulled:
            return f"the {name} fuse holder is already out"
        if verb in ("INSERT", "REPLACE") and not f.pulled:
            return f"pull the {name} fuse holder first"
    return None


def _ac(w: ControlWiring, point: str, ctx: WiringContext) -> float:
    src = {"F1A": PT_SECONDARY_V * ctx.utility_pu, "F1B": PT_SECONDARY_V if ctx.genbus_live else 0.0}
    key, _, side = point.partition("_")
    if key not in src:
        return 0.0
    f = w.fuses[FUSE_KEY[key]]
    if side == "LINE":
        return src[key]
    if side == "LOAD":
        return src[key] if f.conducts else 0.0
    # across the fuse: supply voltage when blown in circuit, ~0 otherwise
    return src[key] if (not f.ok and not f.pulled) else 0.0


def _dc(point: str, ctx: WiringContext) -> float:
    return {
        "P1_N1": STATION_DC_V,
        "CC_52U": STATION_DC_V if (ctx.u_close_ok and not ctx.u_closed) else 0.0,
        "TC_52U": STATION_DC_V if ctx.u_closed else 0.0,
        "CC_52GM": STATION_DC_V if (ctx.gm_close_ok and not ctx.gm_closed) else 0.0,
        "TC_52GM": STATION_DC_V if ctx.gm_closed else 0.0,
    }.get(point, 0.0)


def measure(w: ControlWiring, point: str, ctx: WiringContext) -> dict[str, Any]:
    mode = w.meter
    in_circuit_fuse = point.endswith("_FUSE") and not w.fuses[FUSE_KEY[point[:3]]].pulled
    live = _ac(w, point, ctx) > 1.0 or _dc(point, ctx) > 1.0 or (
        in_circuit_fuse and _ac(w, point.replace("_FUSE", "_LINE"), ctx) > 1.0)
    out: dict[str, Any] = {"point": point, "label": POINTS[point], "mode": mode,
                           "beep": False, "warning": None}
    if mode == "VAC":
        v = round(_ac(w, point, ctx), 1)
        out.update(value=v, unit="V AC", display=f"{v:.1f} V~")
    elif mode == "VDC":
        v = round(_dc(point, ctx), 1)
        out.update(value=v, unit="V DC", display=f"{v:.1f} V⎓")
    else:   # OHM
        fuse = point.endswith("_FUSE") and w.fuses[FUSE_KEY[point[:3]]]
        if point.endswith("_FUSE") and fuse and fuse.pulled:
            ok = fuse.ok
            out.update(value=FUSE_OHM if ok else None, unit="ohm",
                       display=f"{FUSE_OHM:.1f} Ω" if ok else "OL", beep=ok)
        elif point == "T73_74":
            closed = ctx.start_contact
            out.update(value=CONTACT_OHM if closed else None, unit="ohm",
                       display=f"{CONTACT_OHM:.1f} Ω" if closed else "OL", beep=closed)
        elif live:
            out.update(value=None, unit="ohm", display="LIVE",
                       warning="resistance on an energized circuit: the meter is protected, "
                               "the reading is not valid")
        else:
            out.update(value=None, unit="ohm", display="OL")
    return out


def apply(w: ControlWiring, action: str, ctx: WiringContext) -> dict[str, Any] | None:
    verb, _, rest = action.partition("_")
    if verb == "METER":
        w.meter = rest
        return {"meter": rest}
    if verb == "MEASURE":
        reading = measure(w, rest, ctx)
        tag = f"{rest}:{w.meter}"
        if tag not in w.measured:
            w.measured.append(tag)
        w.readings = [*w.readings, reading][-10:]
        return reading
    f = w.fuses[FUSE_KEY[rest]]
    if verb == "PULL":
        f.pulled = True
    elif verb == "INSERT":
        f.pulled = False
    elif verb == "REPLACE":
        f.ok = True
    return None


def describe(w: ControlWiring, ctx: WiringContext) -> dict[str, Any]:
    return {
        "fuses": {k: {"ok": f.ok, "pulled": f.pulled} for k, f in w.fuses.items()},
        "meter": w.meter, "measured": list(w.measured), "readings": list(w.readings),
        "points": POINTS,
        "start_contact": ctx.start_contact,
        "actions": [{"action": a, "permitted": (r := interlock(w, a, ctx)) is None,
                     "blocked_reason": r} for a in ACTIONS if not a.startswith("MEASURE_")],
    }
