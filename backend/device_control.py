"""
backend/device_control.py
=========================
Release R3-A / R3-B -- Power plant supervisory control: UPS blocks,
medium-voltage transfer controllers and generators, with readings,
capacity checks and supervised switching.

Design source
-------------
``config/power_plant.yml``, closed by the operator on 2026-11-13:
8 x 2.5 MW double-conversion UPS per path (N+1 inside the path),
9 x 2.5 MW generators at 13.8 kV per path, transfer in medium voltage
(no 480 V ATS), 2N.

What this module IS
-------------------
A deterministic model. Per device: a state machine, a readings block,
a control AUTHORITY selector (AUTO / REMOTE / LOCAL) and a command set
with interlocks. Per path: capacity checks (UPS N and N+1, generation
N and N+1) and the UPS losses computed as ``P_out * (1 / eta - 1)``.
Per generator bay: medium-voltage switching through forced procedures
(``backend/mv_switching.py``).

What this module is NOT (honest scope)
--------------------------------------
  * No field device is behind it. Every value is ``simulated`` and
    the payload says so. The HAL adapters in ``backend/hal`` are not
    wired here.
  * Protection exists only as training logic (27 undervoltage, 25
    sync check, and for the utility transformer 26 / 49 / 63 / 87T /
    86T, L2 ``backend/mv_xfmr.py``): no settings study, no load-flow,
    no short-circuit or arc-flash calculation. The transformer thermal
    model uses typical constants, not a test report.
  * The interlocks are supervisory permissives. A real installation
    keeps its mechanical and hardwired interlocks.

Control discipline
------------------
  * ADR-006: commands are accepted only from an authenticated human.
    Nothing in the agent stack imports this module
    (``tests/test_device_control.py::TestAgentIsolation``).
  * Authority: remote commands are refused unless the device is in
    REMOTE. LOCAL models the key switch at the equipment and wins.
  * Select-before-operate for device commands: single-use token,
    bound to device and operator, interlocks evaluated twice.
  * MV bay switching only through a procedure: the next step is the
    only step; safety gates need a second person.
  * Everything is appended to the Forensic Ledger (ADR-011) when one
    is available.

Vocabulary fence (S-VOCAB-01): AC equipment only. The 800 VDC
unipolar TN-S side is out of scope here.
"""

from __future__ import annotations

import math
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request

from backend import mv_cubicle as cub, mv_switching as mv, mv_xfmr as xf

# ── Kinds ───────────────────────────────────────────────────────────
KIND_UPS = "ups"
KIND_TRANSFER = "transfer"
KIND_GENERATOR = "generator"
KINDS = (KIND_UPS, KIND_TRANSFER, KIND_GENERATOR)

# ── Authority ───────────────────────────────────────────────────────
AUTH_AUTO = "AUTO"
AUTH_REMOTE = "REMOTE"
AUTH_LOCAL = "LOCAL"
AUTHORITIES = (AUTH_AUTO, AUTH_REMOTE, AUTH_LOCAL)

# ── UPS block states (IEC 62040-3 wording) ──────────────────────────
UPS_DOUBLE_CONVERSION = "DOUBLE_CONVERSION"
UPS_DYNAMIC_ONLINE = "DYNAMIC_ONLINE"
UPS_STATIC_BYPASS = "STATIC_BYPASS"
UPS_ISOLATED = "ISOLATED"
_UPS_CARRYING = (UPS_DOUBLE_CONVERSION, UPS_DYNAMIC_ONLINE, UPS_STATIC_BYPASS)
_UPS_PROTECTING = (UPS_DOUBLE_CONVERSION, UPS_DYNAMIC_ONLINE)

# ── MV transfer controller positions ────────────────────────────────
XFER_UTILITY = "UTILITY"
XFER_GENERATORS = "GENERATORS"
# T1 (2026-11-15): both mains open, MV bus dead. Reached when ANSI 27
# undervoltage on the utility incomer trips 52-U.
XFER_OPEN = "OPEN"

# ── Generator run states (NFPA 110 sequence used by power_grid.js) ──
GEN_STANDBY = "STANDBY"
GEN_CRANKING = "CRANKING"
GEN_RUNNING = "RUNNING"
GEN_ON_LOAD = "ON_LOAD"
GEN_COOLDOWN = "COOLDOWN"

# ── Timing (simulation values, stated in the payload) ───────────────
SELECT_TTL_S = 30.0
CRANK_TIME_S = 8.0
COOLDOWN_TIME_S = 30.0

# ── Model constants (simulation, not vendor data) ───────────────────
NOMINAL_HZ = 60.0
POWER_FACTOR = 0.98
EFF_BYPASS = 0.995
STARTER_FLOAT_V = 25.6
STARTER_CRANK_V = 21.8
RATED_RPM = 1800

ACTION_DEVICE_AUTHORITY = "DEVICE_AUTHORITY_CHANGED"
ACTION_DEVICE_COMMAND_REQUESTED = "DEVICE_COMMAND_REQUESTED"
ACTION_DEVICE_COMMAND_RESULT = "DEVICE_COMMAND_RESULT"
ACTION_MV_PROCEDURE = "MV_SWITCHING_PROCEDURE"
ACTION_MV_STEP = "MV_SWITCHING_STEP"
ACTION_MV_WITNESS = "MV_SWITCHING_WITNESS"
ACTION_MV_FIELD = "MV_SWITCHGEAR_FIELD_ACTION"
ACTION_XFMR_FIELD = "XFMR_FIELD_ACTION"

SIMULATION_NOTICE = (
    "SIMULATED plant. No field equipment is connected: states and "
    "readings come from a deterministic model of the closed design "
    "(config/power_plant.yml). Interlocks are supervisory permissives, "
    "not protection. Arc-flash energy is not calculated."
)

EVENT_LOG_SIZE = 200

# ── T1 training model constants (simulation assumptions, not vendor data)
# Battery: usable energy per path = protecting blocks x rated_kw x
# runtime_full_load_min (power_plant.yml); discharge linear in energy
# at the IT load of the path; no Peukert / temperature / ageing (the
# design file does not state the chemistry). Recharge linear, full in
# BATTERY_RECHARGE_FULL_S once the MV bus is back.
BATTERY_RECHARGE_FULL_S = 600.0
BATTERY_LOW_FRACTION = 0.25
# T3 closed-transition training (OFF by default; the A3 design is open
# transition). Sync-check settings are training values, not a relay
# setting file: angle window, maximum slip, governor range and step.
UTILITY_HZ = 60.0
SECONDARY_KV_DEFAULT = 13.8
SYNC_MAX_ANGLE_DEG = 10.0
SYNC_MAX_SLIP_HZ = 0.10
GOVERNOR_MIN_HZ = 59.5
GOVERNOR_MAX_HZ = 60.5
GOVERNOR_MAX_STEP_HZ = 0.05
CLOSED_TRANSITION_OVERLAP_MS = 100   # model: 52-GM opens automatically
SYNC_CLOSE_TIMEOUT_S = 30.0          # supervised close waits this long
UPS_FAULT_INVERTER_OVERTEMP = "INVERTER_OVERTEMP"
UPS_FAULTS = {
    UPS_FAULT_INVERTER_OVERTEMP: "Inverter over-temperature",
}


class DeviceControlError(Exception):
    """A command, step or authority change was refused. ``status`` is
    the HTTP status the route reports."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


# Commands: kind -> name -> (label, description)
COMMANDS: dict[str, dict[str, tuple[str, str]]] = {
    KIND_UPS: {
        "ENTER_DYNAMIC_ONLINE": (
            "Enter Dynamic Online",
            "High-efficiency mode. The inverter stays ready and returns to "
            "double conversion on a mains disturbance.",
        ),
        "RETURN_TO_DOUBLE_CONVERSION": (
            "Return to double conversion",
            "Load is carried by the inverter (VFI).",
        ),
        "TRANSFER_TO_BYPASS": (
            "Transfer to static bypass",
            "This block feeds its share through the static bypass: not "
            "conditioned and not battery-backed.",
        ),
        "ISOLATE": (
            "Isolate block for maintenance",
            "Takes the block out of the parallel system. Allowed only from "
            "static bypass and only if the remaining blocks carry the "
            "design load.",
        ),
        "RETURN_TO_SERVICE": (
            "Return block to service",
            "Reconnects the block on static bypass.",
        ),
    },
    KIND_TRANSFER: {
        "START_GENERATORS": (
            "Start generator bus",
            "Master start: sends the start signal to every set of the path "
            "that is in standby, in service and not in LOCAL.",
        ),
        "TRANSFER_TO_GENERATORS": (
            "Transfer to generators",
            "Opens the utility incomer 52-U (if closed) and closes the "
            "generator main 52-GM (open transition).",
        ),
        "RETRANSFER_TO_UTILITY": (
            "Retransfer to utility",
            "Opens 52-GM (if closed) and closes 52-U (open transition). "
            "Needs utility voltage on the incomer.",
        ),
        "CLOSED_TRANSITION_RETRANSFER": (
            "Closed-transition retransfer (ANSI 25)",
            "Training mode only. Sync-check supervised close: 52-U closes "
            "in parallel with the generator bus at the instant angle and "
            "slip are inside the window (waits up to 30 s, then cancels); "
            "the controller then opens 52-GM after a momentary overlap.",
        ),
        "STOP_GENERATORS": (
            "Stop generator bus",
            "Opens 52-G of every running set of the path and starts the "
            "cooldown. Refused while the path is on generators.",
        ),
    },
    KIND_GENERATOR: {
        "START": (
            "Start engine",
            "Cranks the engine, brings it to rated voltage and frequency and "
            "closes 52-G onto the generator bus after synchronising.",
        ),
        "STOP": (
            "Stop engine",
            "Opens 52-G, runs the cooldown and stops. Refused if the "
            "remaining sets cannot carry the load.",
        ),
    },
}

_NEXT_STATE = {
    "ENTER_DYNAMIC_ONLINE": UPS_DYNAMIC_ONLINE,
    "RETURN_TO_DOUBLE_CONVERSION": UPS_DOUBLE_CONVERSION,
    "TRANSFER_TO_BYPASS": UPS_STATIC_BYPASS,
    "ISOLATE": UPS_ISOLATED,
    "RETURN_TO_SERVICE": UPS_STATIC_BYPASS,
    "TRANSFER_TO_GENERATORS": XFER_GENERATORS,
    "RETRANSFER_TO_UTILITY": XFER_UTILITY,
    "START": GEN_CRANKING,
    "STOP": GEN_COOLDOWN,
}


@dataclass
class Device:
    device_id: str
    kind: str
    display: str
    path: str
    vendor: str
    model: str
    rated_kw: float
    voltage_v: float
    authority: str = AUTH_AUTO
    state: str = ""
    state_since: float = 0.0


@dataclass
class _Selection:
    token: str
    device_id: str
    command: str
    actor: str
    expires_at: float


def load_design(path: Path) -> dict[str, Any]:
    """Read and validate ``config/power_plant.yml``. Raises ValueError
    on anything the model cannot run with."""
    import yaml

    with open(path, encoding="utf-8") as handle:
        design = yaml.safe_load(handle) or {}
    return validate_design(design)


def validate_design(design: dict[str, Any]) -> dict[str, Any]:
    basis = design.get("design_basis") or {}
    ups = design.get("ups") or {}
    gens = design.get("generators") or {}
    problems = []
    if _num(basis.get("it_load_per_path_kw")) <= 0:
        problems.append("design_basis.it_load_per_path_kw must be positive")
    if not 0 < _num(basis.get("normal_share")) <= 1:
        problems.append("design_basis.normal_share must be in (0, 1]")
    paths = basis.get("paths") or []
    if not paths or any(not (isinstance(p, str) and len(p) == 1 and p.isalpha()) for p in paths):
        problems.append("design_basis.paths must be single letters")
    for name, block in (("ups", ups), ("generators", gens)):
        if _num(block.get("rated_kw")) <= 0:
            problems.append(f"{name}.rated_kw must be positive")
        if int(_num(block.get("units_per_path"))) < 1:
            problems.append(f"{name}.units_per_path must be at least 1")
    eff = ups.get("efficiency") or {}
    for mode in ("double_conversion", "dynamic_online"):
        if not 0.5 < _num(eff.get(mode)) < 1:
            problems.append(f"ups.efficiency.{mode} must be in (0.5, 1)")
    if problems:
        raise ValueError("power plant design invalid: " + "; ".join(problems))
    return design


@dataclass
class DeviceController:
    """In-memory supervisory model. Thread-safe; time is injected."""

    design: dict[str, Any] = field(default_factory=dict)
    clock: Callable[[], float] = time.monotonic
    wall_clock: Callable[[], float] = time.time
    devices: dict[str, Device] = field(default_factory=dict)
    bays: dict[str, mv.Bay] = field(default_factory=dict)
    procedures: dict[str, mv.Procedure] = field(default_factory=dict)
    path_share: dict[str, float] = field(default_factory=dict)
    _selections: dict[str, _Selection] = field(default_factory=dict)
    _events: deque = field(default_factory=lambda: deque(maxlen=EVENT_LOG_SIZE))
    _lock: threading.RLock = field(default_factory=threading.RLock)
    # T1 plant conditions (per path unless noted)
    utility_ok: dict[str, bool] = field(default_factory=dict)
    battery_soc: dict[str, float] = field(default_factory=dict)
    load_lost: dict[str, bool] = field(default_factory=dict)
    faults: dict[str, str] = field(default_factory=dict)        # device_id -> fault
    _batt_at: float | None = None
    # T3 closed-transition training
    closed_transition: bool = False
    gen_hz: dict[str, float] = field(default_factory=dict)
    sync_angle: dict[str, float] = field(default_factory=dict)
    _sync_at: float | None = None
    # path -> {"device_id", "actor", "deadline"}: supervised close armed
    _sync_close: dict[str, dict[str, Any]] = field(default_factory=dict)
    # L1: draw-out cubicles of the two mains, key (path, breaker)
    cubicles: dict[tuple[str, str], cub.Cubicle] = field(default_factory=dict)
    _auto_blocked: dict[str, str] = field(default_factory=dict)
    # L2: utility transformer per path (52-T, DETC, keys, thermal)
    xfmrs: dict[str, xf.Transformer] = field(default_factory=dict)
    grid_kv: dict[str, float] = field(default_factory=dict)
    _xfmr_at: float | None = None

    # ── Construction ────────────────────────────────────────────────
    @classmethod
    def from_design(
        cls,
        design: dict[str, Any],
        *,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> DeviceController:
        design = validate_design(design)
        ctl = cls(design=design, clock=clock, wall_clock=wall_clock)
        now = clock()
        basis, ups, gens = design["design_basis"], design["ups"], design["generators"]
        xfer = design.get("transfer") or {}
        for path in basis["paths"]:
            path = path.lower()
            ctl.path_share[path] = float(basis["normal_share"])
            ctl.utility_ok[path] = True
            ctl.battery_soc[path] = 1.0
            ctl.load_lost[path] = False
            ctl.gen_hz[path] = UTILITY_HZ
            ctl.sync_angle[path] = 0.0
            for brk in cub.BREAKERS:
                ctl.cubicles[(path, brk)] = cub.Cubicle(breaker=brk)
            ctl.xfmrs[path] = xf.Transformer(path=path)
            ctl.grid_kv[path] = xf.PRIMARY_KV
            upper = path.upper()
            for n in range(1, int(ups["units_per_path"]) + 1):
                ctl._add(Device(
                    device_id=f"ups_{path}_{n:02d}", kind=KIND_UPS,
                    display=f"UPS {upper}{n}", path=path,
                    vendor=str(ups.get("vendor") or ""), model=str(ups.get("model") or ""),
                    rated_kw=_num(ups["rated_kw"]),
                    voltage_v=_num(ups.get("voltage_v")) or 480.0,
                    state=UPS_DOUBLE_CONVERSION, state_since=now,
                ))
            ctl._add(Device(
                device_id=f"mvtc_{path}", kind=KIND_TRANSFER,
                display=f"MV transfer controller {upper}", path=path,
                vendor="", model="", rated_kw=0.0,
                voltage_v=_num(xfer.get("voltage_v")) or _num(gens.get("voltage_v")) or 13800.0,
                state=XFER_UTILITY, state_since=now,
            ))
            for n in range(1, int(gens["units_per_path"]) + 1):
                device_id = f"genset_{path}_{n:02d}"
                ctl._add(Device(
                    device_id=device_id, kind=KIND_GENERATOR,
                    display=f"Generator {upper}{n}", path=path,
                    vendor=str(gens.get("vendor") or ""), model=str(gens.get("model") or ""),
                    rated_kw=_num(gens["rated_kw"]),
                    voltage_v=_num(gens.get("voltage_v")) or 13800.0,
                    state=GEN_STANDBY, state_since=now,
                ))
                ctl.bays[device_id] = mv.Bay(bay_id=device_id)
        return ctl

    def _add(self, dev: Device) -> None:
        self.devices[dev.device_id] = dev

    # ── Design shortcuts ────────────────────────────────────────────
    @property
    def _it_design_kw(self) -> float:
        return _num(self.design["design_basis"]["it_load_per_path_kw"])

    def _generation_floor_kw(self, path: str) -> float:
        """DC-EPMS-067 (operator decision 2026-11-14): generation that
        must remain available on a path. The larger of the current
        total path load (IT + cooling + auxiliaries + UPS losses), the
        computed full-path demand and the operator's design total."""
        return max(
            self._demand_kw(path),
            self._demand_kw(path, self._it_design_kw),
            _num(self.design["design_basis"].get("design_total_load_kw")),
        )

    @property
    def _aux_fraction(self) -> float:
        return _num(self.design["design_basis"].get("cooling_and_aux_fraction"))

    def _eff(self, state: str) -> float:
        eff = self.design["ups"]["efficiency"]
        if state == UPS_DOUBLE_CONVERSION:
            return float(eff["double_conversion"])
        if state == UPS_DYNAMIC_ONLINE:
            return float(eff["dynamic_online"])
        return EFF_BYPASS

    # ── Time evolution ──────────────────────────────────────────────
    def _advance(self) -> None:
        now = self.clock()
        for dev in self.devices.values():
            if dev.kind != KIND_GENERATOR:
                continue
            bay = self.bays[dev.device_id]
            elapsed = now - dev.state_since
            if dev.state == GEN_CRANKING and elapsed >= CRANK_TIME_S:
                dev.state, dev.state_since = GEN_RUNNING, dev.state_since + CRANK_TIME_S
                # Auto-synchroniser: 52-G closes only if every interlock
                # permits it (bay in service, engine at rated).
                ctx = mv.BayContext(now=now, engine_at_rated=True)
                if mv.interlock(bay, mv.OP_CLOSE_CB, ctx) is None:
                    mv.apply(bay, mv.OP_CLOSE_CB, now)
            elif dev.state == GEN_COOLDOWN and elapsed >= COOLDOWN_TIME_S:
                dev.state, dev.state_since = GEN_STANDBY, dev.state_since + COOLDOWN_TIME_S
        for dev in self.devices.values():
            if dev.kind != KIND_GENERATOR:
                continue
            on_bus = self.bays[dev.device_id].cb == mv.CLOSED
            carrying = self._path_on_generators(dev.path) and on_bus
            if dev.state == GEN_RUNNING and carrying:
                dev.state, dev.state_since = GEN_ON_LOAD, now
            elif dev.state == GEN_ON_LOAD and not carrying:
                dev.state, dev.state_since = GEN_RUNNING, now
        for (path, brk), c in self.cubicles.items():
            if cub.tick(c, now):
                xfer = next(iter(self._of(KIND_TRANSFER, path)), None)
                if xfer is not None:
                    self._event("spring_charged", xfer, "controller", breaker=brk, by="motor")
        self._advance_xfmrs(now)
        self._advance_auto_transfer(now)
        self._advance_battery(now)
        self._advance_sync(now)

    # ── L1: draw-out cubicles of 52-U / 52-GM ───────────────────────
    def _main_closed(self, path: str, brk: str) -> bool:
        xfer = next(iter(self._of(KIND_TRANSFER, path)), None)
        if xfer is None:
            return False
        return xfer.state == (XFER_UTILITY if brk == cub.BREAKER_U else XFER_GENERATORS)

    def _cubicle_reason(self, path: str, brk: str) -> str | None:
        c = self.cubicles.get((path, brk))
        if brk == cub.BREAKER_U and path in self.xfmrs:
            key = xf.u_lock_reason(self.xfmrs[path])
            if key:
                return key
        return cub.close_reason(c) if c is not None else None

    def _closed_main(self, path: str, brk: str) -> None:
        """A main breaker was just closed (any control): the closing
        spring is released and the motor, if ON, recharges it."""
        c = self.cubicles.get((path, brk))
        if c is not None:
            cub.discharge(c, self.clock())

    def _plant_close_reason(self, xfer: Device, brk: str) -> str | None:
        """Plant interlock for a LOCAL close of a main in CONNECTED."""
        path = xfer.path
        if brk == cub.BREAKER_U:
            if xfer.state == XFER_GENERATORS:
                return ("Interlock: 52-GM is closed. The A3 design never parallels the mains "
                        "from the switchgear: open 52-GM first (dead-bus transfer).")
            if path in self.xfmrs and xf.u_lock_reason(self.xfmrs[path]):
                return xf.u_lock_reason(self.xfmrs[path])
            if not self._incomer_live(path):
                return "No utility voltage on the incomer: ANSI 27 holds 52-U open."
            return None
        if xfer.state == XFER_UTILITY:
            return "Interlock: 52-U is closed (open-transition design): open 52-U first."
        on_bus = sum(d.rated_kw for d in self._gens_on_bus(path))
        demand = self._demand_kw(path)
        if on_bus < demand:
            return (f"Generator bus has {on_bus / 1000:.1f} MW synchronised, below the "
                    f"{demand / 1000:.1f} MW the path draws.")
        return None

    def _cubicle_ctx(self, xfer: Device, brk: str, actor: str = "") -> cub.CubicleContext:
        return cub.CubicleContext(
            now=self.clock(), local_authority=xfer.authority == AUTH_LOCAL,
            main_closed=self._main_closed(xfer.path, brk),
            plant_close_reason=self._plant_close_reason(xfer, brk), actor=actor,
        )

    def cubicles_of(self, xfer: Device) -> list[dict[str, Any]]:
        return [cub.describe(self.cubicles[(xfer.path, b)], self._cubicle_ctx(xfer, b))
                for b in cub.BREAKERS if (xfer.path, b) in self.cubicles]

    def field_action(self, device_id: str, breaker: str, action: str, actor: str) -> dict[str, Any]:
        """L1: an operation at the switchgear (racking, springs, local
        push buttons, 86 lockout, padlock). Recorded as a "command"
        event named ACTION@BREAKER, so drills can list or forbid it."""
        action = str(action or "").upper()
        breaker = str(breaker or "").upper()
        with self._lock:
            self._advance()
            xfer = self._get(device_id)
            if xfer.kind != KIND_TRANSFER:
                raise DeviceControlError(400, "switchgear actions apply to an MV transfer controller")
            c = self.cubicles.get((xfer.path, breaker))
            if c is None:
                raise DeviceControlError(404, f"no cubicle {breaker!r} on path {xfer.path.upper()}")
            if action not in cub.ACTIONS:
                raise DeviceControlError(400, f"action must be one of {list(cub.ACTIONS)}")
            ctx = self._cubicle_ctx(xfer, breaker, actor)
            reason = cub.interlock(c, action, ctx)
            if reason:
                raise DeviceControlError(409, reason)
            before = {"racking": c.racking, "closed": cub.is_closed(c, ctx.main_closed)}
            previous = xfer.state
            effect = cub.apply(c, action, ctx)
            now = self.clock()
            if effect == "main_open":
                xfer.state, xfer.state_since = XFER_OPEN, now
                self._drop_selections(xfer.device_id)
                if xfer.path in self._sync_close:
                    self._cancel_sync_close(xfer.path, f"{breaker} opened at the switchgear")
            elif effect == "main_close":
                xfer.state = XFER_UTILITY if breaker == cub.BREAKER_U else XFER_GENERATORS
                xfer.state_since = now
            self._advance()
            after = cub.is_closed(c, self._main_closed(xfer.path, breaker))
            return self._event(
                "command", xfer, actor, command=f"{action}@{breaker}", field=True,
                breaker=breaker, action=action, from_state=previous, to_state=xfer.state,
                racking=c.racking, racking_before=before["racking"],
                breaker_closed=after, spring_charged=c.spring_charged,
                lockout_86=c.lockout_86, padlock=c.padlock,
            )

    # ── L2: utility transformer (52-T, DETC, keys, thermal) ────────
    def _incomer_live(self, path: str) -> bool:
        """Voltage on the 13.8 kV side of 52-U: utility present AND the
        transformer energized (52-T closed, no 86T, not damaged)."""
        if not self.utility_ok.get(path, True):
            return False
        t = self.xfmrs.get(path)
        return True if t is None else xf.energized(t, True)

    def _xfmr_ctx(self, path: str, actor: str = "") -> xf.XfmrContext:
        return xf.XfmrContext(
            grid_ok=self.utility_ok.get(path, True),
            main_u_closed=self._main_closed(path, cub.BREAKER_U),
            grid_kv=self.grid_kv.get(path, xf.PRIMARY_KV), actor=actor,
        )

    def _incomer_kv(self, path: str) -> float:
        t = self.xfmrs.get(path)
        if t is None:
            return SECONDARY_KV_DEFAULT if self.utility_ok.get(path, True) else 0.0
        return xf.secondary_kv(t, self.utility_ok.get(path, True),
                               self.grid_kv.get(path, xf.PRIMARY_KV))

    def _bus_kv(self, dev: Device) -> float:
        if dev.state == XFER_UTILITY and dev.path in self.xfmrs:
            return self._incomer_kv(dev.path)
        return dev.voltage_v / 1000

    def _xfmr_load_mva(self, path: str) -> float:
        on_utility = any(d.state == XFER_UTILITY for d in self._of(KIND_TRANSFER, path))
        if not on_utility or not self._incomer_live(path) or self.load_lost.get(path):
            return 0.0
        return self._demand_kw(path) / POWER_FACTOR / 1000.0

    def _trip_incomer(self, path: str, relay: str, detail: str) -> None:
        """The 13.8 kV incomer lost its source (52-T opened, 86T): 52-U
        trips if it was closed and the MV bus goes dead."""
        for xfer in self._of(KIND_TRANSFER, path):
            if xfer.state == XFER_UTILITY:
                xfer.state, xfer.state_since = XFER_OPEN, self.clock()
                self._drop_selections(xfer.device_id)
                self._event("protection_trip", xfer, "protection", relay=relay,
                            breaker="52-U", detail=detail)

    def _advance_xfmrs(self, now: float) -> None:
        last = self._xfmr_at
        self._xfmr_at = now
        dt = 0.0 if last is None else max(0.0, now - last)
        for path, t in self.xfmrs.items():
            live = xf.energized(t, self.utility_ok.get(path, True))
            for ev in xf.tick(t, dt, self._xfmr_load_mva(path), live):
                xfer = next(iter(self._of(KIND_TRANSFER, path)), None)
                if ev["event"] == "xfmr_lockout":
                    t.primary_closed = False
                    if xfer is not None:
                        self._event("protection_trip", xfer, "protection", relay="86T",
                                    breaker="52-T", detail=ev["cause"])
                    self._trip_incomer(path, "86T", ev["cause"])
                elif xfer is not None:
                    self._event(ev["event"], xfer, "protection",
                                **{k: v for k, v in ev.items() if k != "event"})

    def _xfmr_indications(self, path: str) -> list[dict[str, str]]:
        t = self.xfmrs.get(path)
        if t is None:
            return []
        return [
            {"label": "52-T transformer primary", "value": mv.CLOSED if t.primary_closed else mv.OPEN},
            {"label": "86T transformer lockout", "value": "TRIPPED" if t.lockout_86t else "NORMAL"},
            {"label": "DETC position", "value": f"{t.tap} ({xf.TAPS[t.tap]:+.1f} %)"},
            {"label": "Key K1", "value": t.k1},
        ]

    def xfmr_action(self, device_id: str, action: str, actor: str) -> dict[str, Any]:
        """L2: an operation at the utility transformer of the path of
        transfer controller ``device_id`` (52-T, Kirk keys, DETC,
        relay targets, fans). Recorded as a "command" event named
        ACTION@XFMR; protection consequences follow as their own events."""
        action = str(action or "").upper()
        with self._lock:
            self._advance()
            xfer = self._get(device_id)
            if xfer.kind != KIND_TRANSFER:
                raise DeviceControlError(400, "transformer actions apply to an MV transfer controller")
            t = self.xfmrs.get(xfer.path)
            if t is None:
                raise DeviceControlError(404, f"no transformer on path {xfer.path.upper()}")
            if action not in xf.ACTIONS:
                raise DeviceControlError(400, f"action must be one of {list(xf.ACTIONS)}")
            ctx = self._xfmr_ctx(xfer.path, actor)
            reason = xf.interlock(t, action, ctx)
            if reason:
                raise DeviceControlError(409, reason)
            tap_from = t.tap
            was_live = xf.energized(t, ctx.grid_ok)
            effect = xf.apply(t, action, ctx)
            event = self._event(
                "command", xfer, actor, command=f"{action}@XFMR", field=True,
                equipment="xfmr", action=action, tap_from=tap_from, tap=t.tap,
                key_k1=t.k1, key_k2=t.k2, primary_closed=t.primary_closed,
                detc_locked=t.detc_unlocked_by is None, detc_unlocked_by=t.detc_unlocked_by,
                energized_before=was_live, energized=xf.energized(t, ctx.grid_ok),
                outcome=effect or "ok",
            )
            if action == xf.DETC_SPARE_KEY:
                self._event("interlock_defeated", xfer, actor, equipment="xfmr",
                            detail="DETC handle unlocked with a spare key: the K1 / K2 chain is bypassed")
            if effect == "internal_fault":
                self._event("xfmr_internal_fault", xfer, "protection", relay="63+87T",
                            detail=t.trip_cause)
                self._event("protection_trip", xfer, "protection", relay="86T",
                            breaker="52-T", detail=t.trip_cause)
                self._trip_incomer(xfer.path, "86T", t.trip_cause or "86T")
            elif effect == "primary_open":
                self._trip_incomer(xfer.path, "27", "52-T opened: transformer de-energized")
            self._advance()
            return event

    def set_spare_key(self, path: str, available: bool, actor: str) -> dict[str, Any]:
        """Training hazard: a spare DETC key in the marshalling box."""
        with self._lock:
            if path not in self.xfmrs:
                raise DeviceControlError(404, f"unknown path {path!r}")
            self.xfmrs[path].spare_key_available = bool(available)
            return self._plant_event("xfmr_spare_key", path, actor, available=bool(available))

    def set_grid_voltage(self, path: str, kv: float, actor: str) -> dict[str, Any]:
        """Training condition: steady utility voltage at the primary."""
        kv = _num(kv)
        if not 0.8 * xf.PRIMARY_KV <= kv <= 1.2 * xf.PRIMARY_KV:
            raise DeviceControlError(400, "utility voltage must be within 80 to 120 % of 27.5 kV")
        with self._lock:
            if path not in self.grid_kv:
                raise DeviceControlError(404, f"unknown path {path!r}")
            self.grid_kv[path] = kv
            return self._plant_event("utility_voltage", path, actor, kv=kv)

    # ── T3: generator bus vs utility (synchroscope model) ──────────
    def _islanded(self, path: str) -> bool:
        """Generator bus carrying the path with utility voltage present
        on the open incomer: the two sides can drift in phase."""
        return self._path_on_generators(path) and self._incomer_live(path) \
            and bool(self._gens_on_bus(path))

    def _advance_sync(self, now: float) -> None:
        last = self._sync_at
        self._sync_at = now
        dt = 0.0 if last is None else max(0.0, now - last)
        t0 = now - dt
        for path in self.path_share:
            pending = self._sync_close.get(path)
            if not self._islanded(path):
                if pending:
                    self._cancel_sync_close(path, "generator bus no longer islanded with utility present")
                continue
            slip = self.gen_hz.get(path, UTILITY_HZ) - UTILITY_HZ
            a0 = self.sync_angle.get(path, 0.0)
            if pending:
                # Supervised close: earliest instant inside [t0, now] and
                # before the deadline where angle AND slip are in window.
                tau = window_entry_s(a0, slip)
                limit = min(dt, pending["deadline"] - t0)
                if abs(slip) <= SYNC_MAX_SLIP_HZ and tau is not None and tau <= limit:
                    why = self._cubicle_reason(path, cub.BREAKER_U)
                    if why:
                        self._cancel_sync_close(path, why)
                        continue
                    self._sync_close_now(path, t0 + tau, a0 + 360.0 * slip * tau, slip, now)
                    continue
                if now >= pending["deadline"]:
                    self._cancel_sync_close(path, (
                        f"no synchronism within {SYNC_CLOSE_TIMEOUT_S:.0f} s "
                        f"(slip {slip:+.3f} Hz, max ±{SYNC_MAX_SLIP_HZ:.2f} Hz)"))
            if dt:
                angle = a0 + 360.0 * slip * dt
                self.sync_angle[path] = (angle + 180.0) % 360.0 - 180.0

    def _sync_close_now(self, path: str, at: float, angle: float, slip: float, now: float) -> None:
        pending = self._sync_close.pop(path)
        dev = self.devices[pending["device_id"]]
        previous = dev.state
        dev.state, dev.state_since = XFER_UTILITY, at
        self._closed_main(path, cub.BREAKER_U)
        self.gen_hz[path], self.sync_angle[path] = UTILITY_HZ, 0.0
        angle = (angle + 180.0) % 360.0 - 180.0
        event = self._event(
            "command", dev, pending["actor"], command="CLOSED_TRANSITION_RETRANSFER",
            from_state=previous, to_state=dev.state, closed_transition=True,
            supervised=True, angle_deg=round(angle, 1), slip_hz=round(slip, 3),
            overlap_ms=CLOSED_TRANSITION_OVERLAP_MS,
        )
        # Stamp the event at the computed close instant, not the poll.
        event["ts"] = round(self.wall_clock() - (now - at), 3)

    def _cancel_sync_close(self, path: str, reason: str) -> None:
        pending = self._sync_close.pop(path, None)
        if pending:
            self._event("sync_close_cancelled", self.devices[pending["device_id"]],
                        pending["actor"], detail=reason)

    def cancel_sync_close(self, device_id: str, actor: str) -> dict[str, Any]:
        with self._lock:
            self._advance()
            dev = self._get(device_id)
            if dev.kind != KIND_TRANSFER or dev.path not in self._sync_close:
                raise DeviceControlError(409, "no supervised close is armed on this controller")
            self._sync_close[dev.path]["actor"] = actor
            self._cancel_sync_close(dev.path, f"cancelled by {actor}")
            return {"device_id": device_id, "cancelled": True}

    def synchro(self, path: str) -> dict[str, Any]:
        gen_hz = self.gen_hz.get(path, UTILITY_HZ)
        slip = gen_hz - UTILITY_HZ
        angle = self.sync_angle.get(path, 0.0)
        live = self._islanded(path)
        ok_angle = abs(angle) <= SYNC_MAX_ANGLE_DEG
        ok_slip = abs(slip) <= SYNC_MAX_SLIP_HZ
        pending = self._sync_close.get(path)
        eta = window_entry_s(angle, slip) if live else None
        return {
            "close_armed": bool(pending),
            "close_remaining_s": (round(max(0.0, pending["deadline"] - self.clock()), 1)
                                  if pending else None),
            "window_eta_s": round(eta, 1) if eta is not None else None,
            "enabled": self.closed_transition,
            "live": live,
            "gen_hz": round(gen_hz, 3), "utility_hz": UTILITY_HZ,
            "slip_hz": round(slip, 3), "angle_deg": round(angle, 1),
            "max_angle_deg": SYNC_MAX_ANGLE_DEG, "max_slip_hz": SYNC_MAX_SLIP_HZ,
            "permissive": bool(live and ok_angle and ok_slip),
            "governor_min_hz": GOVERNOR_MIN_HZ, "governor_max_hz": GOVERNOR_MAX_HZ,
            "governor_max_step_hz": GOVERNOR_MAX_STEP_HZ,
            "note": "Training sync-check values, not a relay setting file.",
        }

    def set_closed_transition(self, enabled: bool, actor: str) -> dict[str, Any]:
        with self._lock:
            self._advance()
            self.closed_transition = bool(enabled)
            event = {"ts": round(self.wall_clock(), 3), "event": "closed_transition_mode",
                     "device_id": "plant", "actor": actor, "enabled": self.closed_transition}
            self._events.append(event)
            return event

    def set_sync(self, path: str, gen_hz: float, angle_deg: float, actor: str) -> dict[str, Any]:
        """Training preset of the generator bus frequency and angle."""
        with self._lock:
            self._advance()
            if path not in self.path_share:
                raise DeviceControlError(404, f"unknown path {path!r}")
            self.gen_hz[path] = min(GOVERNOR_MAX_HZ, max(GOVERNOR_MIN_HZ, float(gen_hz)))
            self.sync_angle[path] = (float(angle_deg) + 180.0) % 360.0 - 180.0
            return self._plant_event("sync_preset", path, actor,
                                     gen_hz=self.gen_hz[path], angle_deg=self.sync_angle[path])

    def adjust_governor(self, device_id: str, delta_hz: float, actor: str) -> dict[str, Any]:
        """Governor raise / lower from the synchronising panel. A direct
        control (no select-before-operate), as raise / lower switches
        are; bounded per step and in range."""
        with self._lock:
            self._advance()
            dev = self._get(device_id)
            if dev.kind != KIND_TRANSFER:
                raise DeviceControlError(400, "the governor is adjusted from the MV transfer controller")
            reason = self.authority_reason(dev)
            if reason:
                raise DeviceControlError(409, reason)
            if not self.closed_transition:
                raise DeviceControlError(409, "closed-transition training mode is off")
            if not self._islanded(dev.path):
                raise DeviceControlError(409, "generator bus is not carrying the path with utility present")
            try:
                delta = float(delta_hz)
            except (TypeError, ValueError):
                raise DeviceControlError(400, "delta_hz must be a number") from None
            if not math.isfinite(delta) or abs(delta) > GOVERNOR_MAX_STEP_HZ or delta == 0:
                raise DeviceControlError(400, f"delta_hz must be non-zero and within ±{GOVERNOR_MAX_STEP_HZ} Hz")
            path = dev.path
            before = self.gen_hz.get(path, UTILITY_HZ)
            self.gen_hz[path] = round(min(GOVERNOR_MAX_HZ, max(GOVERNOR_MIN_HZ, before + delta)), 3)
            return self._event("governor", dev, actor, from_hz=before, to_hz=self.gen_hz[path])

    # ── T1: AUTO transfer sequence, battery, load loss ──────────────
    def _start_candidates(self, path: str, *, auto_only: bool) -> list[Device]:
        out = []
        for d in self._of(KIND_GENERATOR, path):
            bay = self.bays[d.device_id]
            if d.state != GEN_STANDBY or bay.loto or not bay.in_service:
                continue
            if self._bay_procedure(d.device_id) is not None:
                continue
            if d.authority == AUTH_LOCAL or (auto_only and d.authority != AUTH_AUTO):
                continue
            out.append(d)
        return out

    def _advance_auto_transfer(self, now: float) -> None:
        """Transfer controller in AUTO with the MV bus dead: start the
        sets that are in AUTO, close 52-GM once the synchronised sets
        cover the path demand, or close 52-U again if the utility is
        back first. Retransfer from generators is NOT automatic here
        (manual, open transition)."""
        for xfer in self._of_kind(KIND_TRANSFER):
            if xfer.authority != AUTH_AUTO or xfer.state != XFER_OPEN:
                continue
            path = xfer.path
            u_block = self._cubicle_reason(path, cub.BREAKER_U)
            if self._incomer_live(path) and u_block:
                # Utility is there but its breaker cannot close (racked
                # out, 86 tripped, spring discharged): the controller
                # treats the normal source as unavailable and goes on
                # to the emergency source below.
                self._auto_block(xfer, u_block)
            elif self._incomer_live(path):
                xfer.state, xfer.state_since = XFER_UTILITY, now
                self._closed_main(path, cub.BREAKER_U)
                self._auto_blocked.pop(path, None)
                self._event("auto_transfer", xfer, "controller", to_state=XFER_UTILITY,
                            detail="utility voltage restored: 52-U reclosed")
                continue
            for gen in self._start_candidates(path, auto_only=True):
                gen.state, gen.state_since = GEN_CRANKING, now
                self._event("auto_start", gen, "controller", to_state=GEN_CRANKING)
            on_bus = sum(d.rated_kw for d in self._gens_on_bus(path))
            if on_bus > 0 and on_bus >= self._demand_kw(path):
                why = self._cubicle_reason(path, cub.BREAKER_GM)
                if why:
                    self._auto_block(xfer, why)
                    continue
                xfer.state, xfer.state_since = XFER_GENERATORS, now
                self._closed_main(path, cub.BREAKER_GM)
                self._auto_blocked.pop(path, None)
                self._event("auto_transfer", xfer, "controller", to_state=XFER_GENERATORS,
                            detail="generator bus ready: 52-GM closed")

    def _auto_block(self, xfer: Device, why: str) -> None:
        """Log once per reason: the automatic transfer is held by the
        switchgear (racked out, 86 tripped or spring discharged)."""
        if self._auto_blocked.get(xfer.path) != why:
            self._auto_blocked[xfer.path] = why
            self._event("auto_transfer_blocked", xfer, "controller", detail=why)

    def _running_sets(self, path: str) -> list[Device]:
        return [d for d in self._of(KIND_GENERATOR, path) if d.state in (GEN_RUNNING, GEN_ON_LOAD)]

    def preset_on_generators(self, path: str, actor: str) -> dict[str, Any]:
        """Training preset: every available set running and synchronised,
        52-GM closed. Skips the 8 s crank so a drill can start there."""
        with self._lock:
            self._advance()
            now = self.clock()
            for gen in self._gens_available(path):
                bay = self.bays[gen.device_id]
                gen.state, gen.state_since = GEN_RUNNING, now
                ctx = mv.BayContext(now=now, engine_at_rated=True)
                if bay.cb != mv.CLOSED and mv.interlock(bay, mv.OP_CLOSE_CB, ctx) is None:
                    mv.apply(bay, mv.OP_CLOSE_CB, now)
            for xfer in self._of(KIND_TRANSFER, path):
                xfer.state, xfer.state_since = XFER_GENERATORS, now
            self._advance()
            return self._plant_event("preset_on_generators", path, actor)

    def _of_kind(self, kind: str) -> list[Device]:
        return [d for d in self.devices.values() if d.kind == kind]

    def _bus_energized(self, path: str) -> bool:
        for xfer in self._of(KIND_TRANSFER, path):
            if xfer.state == XFER_UTILITY:
                return self._incomer_live(path)
            if xfer.state == XFER_GENERATORS:
                return bool(self._gens_on_bus(path))
        return False

    def _battery_energy_kwh(self, path: str) -> float:
        runtime_min = _num(self.design["ups"].get("runtime_full_load_min"))
        rated = sum(d.rated_kw for d in self._of(KIND_UPS, path) if d.state in _UPS_PROTECTING)
        return rated * runtime_min / 60.0

    def _battery_runtime_min(self, path: str) -> float:
        """Minutes left on battery at the present IT load (model)."""
        load = self._it_load_kw(path)
        energy = self._battery_energy_kwh(path) * self.battery_soc.get(path, 1.0)
        if load <= 0:
            return 0.0
        return energy / load * 60.0

    def _advance_battery(self, now: float) -> None:
        last = self._batt_at
        self._batt_at = now
        dt = 0.0 if last is None else max(0.0, now - last)
        for path in self.path_share:
            soc = self.battery_soc.get(path, 1.0)
            if self._bus_energized(path):
                if self.load_lost.get(path):
                    self.load_lost[path] = False
                    self._plant_event("load_restored", path, "controller")
                if dt:
                    self.battery_soc[path] = min(1.0, soc + dt / BATTERY_RECHARGE_FULL_S)
                continue
            if self.load_lost.get(path):
                continue
            carrying = self._ups_carrying(path)
            unprotected = [d for d in carrying if d.state not in _UPS_PROTECTING]
            if not carrying or unprotected:
                reason = ("no UPS block carrying the load" if not carrying else
                          f"{len(unprotected)} block(s) on static bypass with the MV bus dead")
                self._latch_load_lost(path, reason)
                continue
            energy = self._battery_energy_kwh(path)
            if dt and energy > 0:
                soc -= self._it_load_kw(path) * dt / 3600.0 / energy
            self.battery_soc[path] = max(0.0, soc)
            if soc <= 0:
                self._latch_load_lost(path, "battery exhausted (DC undervoltage)")

    def _latch_load_lost(self, path: str, reason: str) -> None:
        self.load_lost[path] = True
        self._plant_event("load_lost", path, "controller", detail=reason)

    def _plant_event(self, kind: str, path: str, actor: str, **extra: Any) -> dict[str, Any]:
        event = {
            "ts": round(self.wall_clock(), 3), "event": kind,
            "device_id": f"path_{path}", "actor": actor, **extra,
        }
        self._events.append(event)
        return event

    # ── T1: training injections (simulation only, never field) ─────
    def inject_utility_loss(self, path: str, actor: str) -> dict[str, Any]:
        """Utility undervoltage on the incomer of ``path``. If 52-U is
        closed, ANSI 27 trips it: the MV bus goes dead (state OPEN)."""
        with self._lock:
            self._advance()
            if path not in self.path_share:
                raise DeviceControlError(404, f"unknown path {path!r}")
            if not self.utility_ok[path]:
                raise DeviceControlError(409, "utility is already lost on this path")
            self.utility_ok[path] = False
            event = self._plant_event("utility_lost", path, actor, relay="27")
            for xfer in self._of(KIND_TRANSFER, path):
                if xfer.state == XFER_UTILITY:
                    xfer.state, xfer.state_since = XFER_OPEN, self.clock()
                    self._drop_selections(xfer.device_id)
                    self._event("protection_trip", xfer, "protection", relay="27",
                                breaker="52-U", detail="incomer undervoltage")
            self._advance()
            return event

    def restore_utility(self, path: str, actor: str) -> dict[str, Any]:
        with self._lock:
            self._advance()
            if path not in self.path_share:
                raise DeviceControlError(404, f"unknown path {path!r}")
            if self.utility_ok[path]:
                raise DeviceControlError(409, "utility is already available on this path")
            self.utility_ok[path] = True
            event = self._plant_event("utility_restored", path, actor)
            self._advance()
            return event

    def inject_ups_fault(self, device_id: str, fault: str, actor: str) -> dict[str, Any]:
        with self._lock:
            self._advance()
            dev = self._get(device_id)
            if dev.kind != KIND_UPS:
                raise DeviceControlError(400, "faults can only be injected on UPS blocks")
            if fault not in UPS_FAULTS:
                raise DeviceControlError(400, f"fault must be one of {list(UPS_FAULTS)}")
            if dev.state not in _UPS_PROTECTING:
                raise DeviceControlError(409, "block is not on the inverter")
            self.faults[device_id] = fault
            return self._event("fault", dev, actor, fault=fault, detail=UPS_FAULTS[fault])

    def reset(self, actor: str) -> dict[str, Any]:
        """Back to the design's normal lineup (training reset)."""
        with self._lock:
            fresh = DeviceController.from_design(
                self.design, clock=self.clock, wall_clock=self.wall_clock,
            )
            for name in ("devices", "bays", "procedures", "path_share", "utility_ok",
                         "battery_soc", "load_lost", "faults", "closed_transition",
                         "gen_hz", "sync_angle", "cubicles", "xfmrs", "grid_kv"):
                setattr(self, name, getattr(fresh, name))
            self._xfmr_at = None
            self._selections.clear()
            self._batt_at = None
            self._sync_at = None
            self._sync_close.clear()
            self._auto_blocked.clear()
            event = {
                "ts": round(self.wall_clock(), 3), "event": "plant_reset",
                "device_id": "plant", "actor": actor,
            }
            self._events.append(event)
            return event

    # ── Path physics ────────────────────────────────────────────────
    def _of(self, kind: str, path: str) -> list[Device]:
        return [d for d in self.devices.values() if d.kind == kind and d.path == path]

    def _path_on_generators(self, path: str) -> bool:
        return any(d.state == XFER_GENERATORS for d in self._of(KIND_TRANSFER, path))

    def _gens_on_bus(self, path: str) -> list[Device]:
        return [
            d for d in self._of(KIND_GENERATOR, path)
            if d.state in (GEN_RUNNING, GEN_ON_LOAD) and self.bays[d.device_id].cb == mv.CLOSED
        ]

    def _gens_available(self, path: str) -> list[Device]:
        """Sets that could be started: bay in service."""
        return [d for d in self._of(KIND_GENERATOR, path) if self.bays[d.device_id].in_service]

    def _it_load_kw(self, path: str) -> float:
        return self._it_design_kw * self.path_share.get(path, 0.0)

    def _ups_carrying(self, path: str) -> list[Device]:
        return [d for d in self._of(KIND_UPS, path) if d.state in _UPS_CARRYING]

    def _ups_block_load_kw(self, path: str) -> float:
        carrying = self._ups_carrying(path)
        return self._it_load_kw(path) / len(carrying) if carrying else 0.0

    def _ups_losses_kw(self, path: str) -> float:
        block = self._ups_block_load_kw(path)
        return sum(block * (1.0 / self._eff(d.state) - 1.0) for d in self._ups_carrying(path))

    def _demand_kw(self, path: str, it_kw: float | None = None) -> float:
        """What the source must deliver: IT + UPS losses + cooling and
        auxiliaries (design assumption, see power_plant.yml)."""
        if it_kw is None:
            return self._it_load_kw(path) * (1 + self._aux_fraction) + self._ups_losses_kw(path)
        eff = float(self.design["ups"]["efficiency"]["double_conversion"])
        return it_kw * (1 + self._aux_fraction) + it_kw * (1.0 / eff - 1.0)

    def path_summary(self, path: str) -> dict[str, Any]:
        ups_all = self._of(KIND_UPS, path)
        ups_cap = sum(d.rated_kw for d in self._ups_carrying(path))
        ups_unit = ups_all[0].rated_kw if ups_all else 0.0
        gens_all = self._of(KIND_GENERATOR, path)
        gen_unit = gens_all[0].rated_kw if gens_all else 0.0
        gen_avail = sum(d.rated_kw for d in self._gens_available(path))
        gen_on_bus = sum(d.rated_kw for d in self._gens_on_bus(path))
        design_demand = self._demand_kw(path, self._it_design_kw)
        floor = self._generation_floor_kw(path)
        return {
            "path": path,
            "source": (XFER_GENERATORS if self._path_on_generators(path) else
                       XFER_UTILITY if self._bus_energized(path) else "NONE"),
            "utility_ok": self.utility_ok.get(path, True),
            "incomer_live": self._incomer_live(path),
            "bus_energized": self._bus_energized(path),
            "load_lost": self.load_lost.get(path, False),
            "battery_soc_pct": round(self.battery_soc.get(path, 1.0) * 100, 1),
            "battery_runtime_min": round(self._battery_runtime_min(path), 2),
            "it_load_kw": round(self._it_load_kw(path)),
            "it_design_kw": round(self._it_design_kw),
            "ups_in_service": len(self._ups_carrying(path)),
            "ups_total": len(ups_all),
            "ups_capacity_kw": round(ups_cap),
            "ups_n_ok": ups_cap >= self._it_design_kw,
            "ups_n_plus_1_ok": ups_cap - ups_unit >= self._it_design_kw,
            "ups_losses_kw": round(self._ups_losses_kw(path)),
            "ups_protected": bool(self._ups_carrying(path)) and all(
                d.state in _UPS_PROTECTING for d in self._ups_carrying(path)
            ),
            "demand_kw": round(self._demand_kw(path)),
            "design_demand_kw": round(design_demand),
            "gen_available": len(self._gens_available(path)),
            "gen_total": len(gens_all),
            "gen_available_kw": round(gen_avail),
            "gen_on_bus_kw": round(gen_on_bus),
            "design_total_kw": round(_num(self.design["design_basis"].get("design_total_load_kw"))),
            "generation_floor_kw": round(floor),
            "gen_n_ok": gen_avail >= floor,
            "gen_n_plus_1_ok": gen_avail - gen_unit >= floor,
            # IT-only view, kept for comparison with the superseded rule.
            "gen_n_plus_1_it_only_ok": gen_avail - gen_unit >= self._it_design_kw,
        }

    # ── Interlocks for device commands ──────────────────────────────
    def blocked_reason(self, dev: Device, command: str) -> str | None:
        """Why ``command`` cannot run now, or None when permitted.
        Authority is checked separately (``authority_reason``)."""
        if dev.kind == KIND_UPS:
            fault = self.faults.get(dev.device_id)
            if fault and command in ("ENTER_DYNAMIC_ONLINE", "RETURN_TO_DOUBLE_CONVERSION"):
                return f"{UPS_FAULTS[fault]} active: the inverter cannot carry the load."
            if command == "ENTER_DYNAMIC_ONLINE":
                return None if dev.state == UPS_DOUBLE_CONVERSION else "Block is not in double conversion."
            if command == "RETURN_TO_DOUBLE_CONVERSION":
                if dev.state in (UPS_DYNAMIC_ONLINE, UPS_STATIC_BYPASS):
                    return None
                return "Block is not in Dynamic Online or on static bypass."
            if command == "TRANSFER_TO_BYPASS":
                return None if dev.state in _UPS_PROTECTING else "Block is not on the inverter."
            if command == "ISOLATE":
                if dev.state != UPS_STATIC_BYPASS:
                    return "Transfer the block to static bypass first."
                remaining = sum(
                    d.rated_kw for d in self._ups_carrying(dev.path) if d is not dev
                )
                if remaining < self._it_design_kw:
                    return (
                        f"Remaining blocks would carry {remaining / 1000:.1f} MW, below the "
                        f"{self._it_design_kw / 1000:.2f} MW design load of the path (N+1 already used)."
                    )
                return None
            if command == "RETURN_TO_SERVICE":
                return None if dev.state == UPS_ISOLATED else "Block is not isolated."
        elif dev.kind == KIND_TRANSFER:
            if command == "START_GENERATORS":
                if not self._start_candidates(dev.path, auto_only=False):
                    return "No set is in standby, in service and out of LOCAL."
                return None
            if command == "CLOSED_TRANSITION_RETRANSFER":
                if not self.closed_transition:
                    return ("Closed transition is a training mode and is off: the A3 design "
                            "retransfers in open transition.")
                if dev.state != XFER_GENERATORS:
                    return "Path is not on generators."
                if not self._incomer_live(dev.path):
                    return "No utility voltage on the incomer (ANSI 27 picked up)."
                if dev.path in self._sync_close:
                    return "A supervised close is already armed: wait or cancel it."
                return self._cubicle_reason(dev.path, cub.BREAKER_U)
            if command == "STOP_GENERATORS":
                if dev.state == XFER_GENERATORS:
                    return "Path is on generators: retransfer to utility first."
                if not self._running_sets(dev.path):
                    return "No set of this path is running."
                return None
            if command == "TRANSFER_TO_GENERATORS":
                if dev.state == XFER_GENERATORS:
                    return "Path is already on generators."
                on_bus = sum(d.rated_kw for d in self._gens_on_bus(dev.path))
                demand = self._demand_kw(dev.path)
                if on_bus < demand:
                    return (
                        f"Generator bus has {on_bus / 1000:.1f} MW synchronised, below the "
                        f"{demand / 1000:.1f} MW the path is drawing."
                    )
                return self._cubicle_reason(dev.path, cub.BREAKER_GM)
            if command == "RETRANSFER_TO_UTILITY":
                if dev.state == XFER_UTILITY:
                    return "Path is already on utility."
                if not self._incomer_live(dev.path):
                    return "No utility voltage on the incomer (ANSI 27 picked up)."
                return self._cubicle_reason(dev.path, cub.BREAKER_U)
        elif dev.kind == KIND_GENERATOR:
            bay = self.bays[dev.device_id]
            if command == "START":
                if dev.state != GEN_STANDBY:
                    return f"Engine is {dev.state.replace('_', ' ').lower()}, not in standby."
                if bay.loto:
                    return "Bay is under LOTO."
                if not bay.in_service:
                    return "Bay is isolated: return it to service first."
                if self._bay_procedure(dev.device_id) is not None:
                    return "A switching procedure is in progress on this bay."
                return None
            if command == "STOP":
                if dev.state not in (GEN_RUNNING, GEN_ON_LOAD):
                    return "Engine is not running."
                if dev.state == GEN_ON_LOAD:
                    remaining = sum(
                        d.rated_kw for d in self._gens_on_bus(dev.path) if d is not dev
                    )
                    demand = self._demand_kw(dev.path)
                    if remaining < demand:
                        return (
                            f"Remaining sets would supply {remaining / 1000:.1f} MW, below the "
                            f"{demand / 1000:.1f} MW the path is drawing. Retransfer to utility "
                            "or start another set first."
                        )
                return None
        return f"Unknown command {command!r} for a {dev.kind}."

    @staticmethod
    def authority_reason(dev: Device) -> str | None:
        if dev.authority == AUTH_LOCAL:
            return "Device is in LOCAL: operate it at the equipment panel."
        if dev.authority == AUTH_AUTO:
            return "Device is in AUTO: set authority to REMOTE to operate it from here."
        return None

    # ── Readings ────────────────────────────────────────────────────
    def _readings(self, dev: Device) -> list[dict[str, Any]]:
        if dev.kind == KIND_UPS:
            carrying = dev.state in _UPS_CARRYING
            load_kw = self._ups_block_load_kw(dev.path) if carrying else 0.0
            eff = self._eff(dev.state)
            runtime_full = _num(self.design["ups"].get("runtime_full_load_min"))
            runtime = 0.0
            soc = self.battery_soc.get(dev.path, 1.0)
            if dev.state in _UPS_PROTECTING and load_kw > 0:
                runtime = runtime_full * dev.rated_kw / load_kw * soc
            if self.load_lost.get(dev.path):
                carrying, load_kw = False, 0.0
            return [
                _r("Output load", load_kw, "kW", 0),
                _r("Load", load_kw / dev.rated_kw * 100 if dev.rated_kw else 0.0, "%", 1),
                _r("Output voltage", dev.voltage_v if carrying else 0.0, "V", 0),
                _r("Output frequency", NOMINAL_HZ if carrying else 0.0, "Hz", 1),
                _r("Efficiency (model)", eff * 100 if carrying else 0.0, "%", 1),
                _r("Losses (model)", load_kw * (1.0 / eff - 1.0) if carrying else 0.0, "kW", 1),
                _r("Battery state of charge (model)", soc * 100, "%", 1),
                _r("Battery runtime (estimate)", runtime, "min", 1),
            ]
        if dev.kind == KIND_TRANSFER:
            demand = self._demand_kw(dev.path)
            amps = demand * 1000 / (math.sqrt(3) * dev.voltage_v * POWER_FACTOR)
            on_bus = sum(d.rated_kw for d in self._gens_on_bus(dev.path))
            live = self._bus_energized(dev.path)
            if not live:
                amps = 0.0
            return [
                _r("Path demand", demand if live else 0.0, "kW", 0),
                _r("Bus current", amps, "A", 0),
                _r("Bus voltage", self._bus_kv(dev) if live else 0.0, "kV", 2),
                _r("Bus frequency",
                   (self.gen_hz.get(dev.path, NOMINAL_HZ) if self._path_on_generators(dev.path)
                    else NOMINAL_HZ) if live else 0.0, "Hz", 2),
                _r("Utility incomer voltage", self._incomer_kv(dev.path), "kV", 2),
                _r("Generators synchronised", len(self._gens_on_bus(dev.path)), "sets", 0),
                _r("Generation on bus", on_bus, "kW", 0),
            ]
        elapsed = max(0.0, self.clock() - dev.state_since)
        if dev.state == GEN_STANDBY:
            rpm, volts, hz, batt = 0.0, 0.0, 0.0, STARTER_FLOAT_V
        elif dev.state == GEN_CRANKING:
            ramp = min(1.0, elapsed / CRANK_TIME_S)
            rpm, volts, hz, batt = RATED_RPM * ramp, 0.0, NOMINAL_HZ * ramp, STARTER_CRANK_V
        else:
            rpm, volts, hz, batt = float(RATED_RPM), dev.voltage_v, NOMINAL_HZ, STARTER_FLOAT_V
        kw = 0.0
        if dev.state == GEN_ON_LOAD:
            kw = self._demand_kw(dev.path) / max(1, len(self._gens_on_bus(dev.path)))
        return [
            _r("Engine speed", rpm, "rpm", 0),
            _r("Output voltage", volts / 1000, "kV", 1),
            _r("Output frequency", hz, "Hz", 1),
            _r("Real power", kw, "kW", 0),
            _r("Load", (kw / dev.rated_kw * 100) if dev.rated_kw else 0.0, "%", 1),
            _r("Starter battery", batt, "V", 1),
        ]

    def _indications(self, dev: Device) -> list[dict[str, str]]:
        if dev.kind == KIND_TRANSFER:
            return [
                {"label": "52-U utility incomer",
                 "value": mv.CLOSED if dev.state == XFER_UTILITY else mv.OPEN},
                {"label": "52-GM generator main",
                 "value": mv.CLOSED if dev.state == XFER_GENERATORS else mv.OPEN},
                {"label": "ANSI 27 incomer undervoltage",
                 "value": "NORMAL" if self._incomer_live(dev.path) else "PICKED UP"},
            ] + self._xfmr_indications(dev.path) + [
                {"label": f"{b} cubicle", "value": _cubicle_text(self.cubicles[(dev.path, b)])}
                for b in cub.BREAKERS if (dev.path, b) in self.cubicles
            ]
        if dev.kind == KIND_GENERATOR:
            return self.bays[dev.device_id].indications()
        return []

    def _status(self, dev: Device) -> dict[str, str]:
        """Operator-facing condition: tone is ok / warn / crit / info."""
        if dev.kind == KIND_UPS:
            fault = self.faults.get(dev.device_id)
            if fault and dev.state in _UPS_PROTECTING:
                return {"tone": "crit", "text": f"{UPS_FAULTS[fault]}: transfer to bypass"}
            if self.load_lost.get(dev.path) and dev.state in _UPS_CARRYING:
                return {"tone": "crit", "text": "Output lost: critical load dropped"}
            if (dev.state in _UPS_PROTECTING and not self._bus_energized(dev.path)):
                return {"tone": "warn", "text": "On battery: MV bus dead"}
            if dev.state in _UPS_CARRYING and self._ups_block_load_kw(dev.path) > dev.rated_kw:
                return {"tone": "crit", "text": "OVERLOAD: block above its rating"}
            return {
                UPS_DOUBLE_CONVERSION: {"tone": "ok", "text": "Load protected (inverter, VFI)"},
                UPS_DYNAMIC_ONLINE: {"tone": "ok", "text": "Load protected (Dynamic Online)"},
                UPS_STATIC_BYPASS: {"tone": "warn", "text": "On static bypass, not battery-backed"},
                UPS_ISOLATED: {"tone": "info", "text": "Out of service for maintenance"},
            }[dev.state]
        if dev.kind == KIND_TRANSFER:
            if dev.state == XFER_UTILITY:
                return {"tone": "ok", "text": "Path on utility"}
            if dev.state == XFER_OPEN:
                t = self.xfmrs.get(dev.path)
                if t is not None and t.lockout_86t:
                    return {"tone": "crit", "text": "52-U tripped by 86T (transformer): MV bus dead"}
                if not self._incomer_live(dev.path):
                    return {"tone": "crit", "text": "52-U tripped (ANSI 27): MV bus dead"}
                return {"tone": "crit", "text": "Both mains open: MV bus dead"}
            return {"tone": "warn", "text": "Path on generators"}
        bay = self.bays[dev.device_id]
        if bay.loto:
            return {"tone": "info", "text": "Isolated, earthed and locked out"}
        if not bay.in_service:
            return {"tone": "warn", "text": "Bay not in service"}
        tone = {GEN_STANDBY: "ok", GEN_ON_LOAD: "warn"}.get(dev.state, "info")
        text = {
            GEN_STANDBY: "Ready to start",
            GEN_CRANKING: "Cranking",
            GEN_RUNNING: "Synchronised, unloaded" if bay.cb == mv.CLOSED else "Running, 52-G open",
            GEN_ON_LOAD: "Carrying load",
            GEN_COOLDOWN: "Cooldown run",
        }[dev.state]
        return {"tone": tone, "text": text}

    # ── Snapshots ───────────────────────────────────────────────────
    def _snapshot(self, dev: Device) -> dict[str, Any]:
        auth_reason = self.authority_reason(dev)
        commands = []
        for name, (label, description) in COMMANDS[dev.kind].items():
            # Authority first: it is the one thing the operator can
            # change from here, and it applies to every command.
            reason = auth_reason or self.blocked_reason(dev, name)
            commands.append({
                "command": name, "label": label, "description": description,
                "permitted": reason is None, "blocked_reason": reason,
            })
        snap: dict[str, Any] = {
            "id": dev.device_id, "kind": dev.kind, "display": dev.display,
            "path": dev.path, "vendor": dev.vendor, "model": dev.model,
            "rated_kw": dev.rated_kw, "authority": dev.authority,
            "state": dev.state,
            "state_age_s": round(max(0.0, self.clock() - dev.state_since), 1),
            "status": self._status(dev),
            "fault": self.faults.get(dev.device_id),
            "readings": self._readings(dev),
            "indications": self._indications(dev),
            "commands": commands,
            "quality": "simulated",
        }
        if dev.kind == KIND_GENERATOR:
            snap["switching"] = self._switching(dev)
        if dev.kind == KIND_TRANSFER:
            snap["synchro"] = self.synchro(dev.path)
            snap["cubicles"] = self.cubicles_of(dev)
            snap["auto_blocked"] = self._auto_blocked.get(dev.path)
            if dev.path in self.xfmrs:
                snap["transformer"] = xf.describe(self.xfmrs[dev.path], self._xfmr_ctx(dev.path))
        return snap

    def _switching(self, dev: Device) -> dict[str, Any]:
        proc = self._bay_procedure(dev.device_id)
        goals = []
        for goal in mv.GOALS:
            reason = self.authority_reason(dev) or self._goal_reason(dev, goal)
            goals.append({
                "goal": goal, "label": mv.GOAL_LABELS[goal],
                "permitted": reason is None, "blocked_reason": reason,
            })
        return {
            "procedure": proc.describe(self.clock()) if proc else None,
            "goals": [] if proc else goals,
        }

    def snapshot_all(self) -> dict[str, Any]:
        with self._lock:
            self._advance()
            devices = [self._snapshot(d) for d in self.devices.values()]
            paths = [self.path_summary(p) for p in sorted(self.path_share)]
        order = {k: i for i, k in enumerate(KINDS)}
        devices.sort(key=lambda d: (d["path"], order[d["kind"]], d["id"]))
        return {
            "notice": SIMULATION_NOTICE,
            "quality": "simulated",
            "authorities": list(AUTHORITIES),
            "select_ttl_s": SELECT_TTL_S,
            "timing": {"crank_s": CRANK_TIME_S, "cooldown_s": COOLDOWN_TIME_S},
            "paths": paths,
            "devices": devices,
            "events": list(self._events)[::-1][:30],
        }

    def snapshot(self, device_id: str) -> dict[str, Any]:
        with self._lock:
            self._advance()
            return self._snapshot(self._get(device_id))

    # ── Device mutations ────────────────────────────────────────────
    def _get(self, device_id: str) -> Device:
        dev = self.devices.get(device_id)
        if dev is None:
            raise DeviceControlError(404, f"device {device_id!r} is not controllable")
        return dev

    def _event(self, kind: str, dev: Device, actor: str, **extra: Any) -> dict[str, Any]:
        event = {
            "ts": round(self.wall_clock(), 3), "event": kind,
            "device_id": dev.device_id, "actor": actor, **extra,
        }
        self._events.append(event)
        return event

    def set_authority(self, device_id: str, mode: str, actor: str) -> dict[str, Any]:
        mode = str(mode or "").upper()
        if mode not in AUTHORITIES:
            raise DeviceControlError(400, f"authority must be one of {list(AUTHORITIES)}")
        with self._lock:
            self._advance()
            dev = self._get(device_id)
            previous = dev.authority
            if previous == mode:
                raise DeviceControlError(409, f"device is already in {mode}")
            dev.authority = mode
            # A pending selection never survives an authority change,
            # and neither does an armed supervised close.
            self._drop_selections(device_id)
            if dev.kind == KIND_TRANSFER and dev.path in self._sync_close:
                self._cancel_sync_close(dev.path, "authority changed")
            # LOCAL is a key switch at the equipment. Moving it from
            # this API is a bench simulation and is recorded as such.
            source = "bench_simulation" if AUTH_LOCAL in (previous, mode) else "remote"
            return self._event(
                "authority", dev, actor, previous=previous, authority=mode, source=source,
            )

    def _drop_selections(self, device_id: str) -> None:
        for token in [t for t, s in self._selections.items() if s.device_id == device_id]:
            del self._selections[token]

    def _check(self, dev: Device, command: str) -> None:
        if command not in COMMANDS[dev.kind]:
            raise DeviceControlError(400, f"unknown command {command!r} for a {dev.kind}")
        reason = self.authority_reason(dev) or self.blocked_reason(dev, command)
        if reason:
            raise DeviceControlError(409, reason)

    def select(self, device_id: str, command: str, actor: str) -> dict[str, Any]:
        command = str(command or "").upper()
        with self._lock:
            self._advance()
            dev = self._get(device_id)
            self._check(dev, command)
            self._drop_selections(device_id)
            token = secrets.token_urlsafe(24)
            self._selections[token] = _Selection(
                token=token, device_id=device_id, command=command, actor=actor,
                expires_at=self.clock() + SELECT_TTL_S,
            )
            label, description = COMMANDS[dev.kind][command]
            return {
                "select_token": token, "expires_in_s": SELECT_TTL_S,
                "device_id": device_id, "command": command, "label": label,
                "description": description, "from_state": dev.state,
            }

    def peek_command(self, token: str) -> str | None:
        """Command a pending selection refers to (for the ledger
        pre-entry). Never consumes the selection."""
        with self._lock:
            sel = self._selections.get(str(token or ""))
            return sel.command if sel is not None else None

    def operate(self, device_id: str, token: str, actor: str) -> dict[str, Any]:
        with self._lock:
            self._advance()
            dev = self._get(device_id)
            sel = self._selections.pop(str(token or ""), None)
            if sel is None or sel.device_id != device_id:
                raise DeviceControlError(409, "no matching selection: select the command again")
            if self.clock() > sel.expires_at:
                raise DeviceControlError(409, "selection expired: select the command again")
            if sel.actor != actor:
                raise DeviceControlError(403, "selection belongs to another operator")
            # Second interlock evaluation: the plant may have moved.
            self._check(dev, sel.command)
            previous = dev.state
            if sel.command == "START_GENERATORS":
                started = self._start_candidates(dev.path, auto_only=False)
                for gen in started:
                    gen.state, gen.state_since = GEN_CRANKING, self.clock()
                self._advance()
                return self._event(
                    "command", dev, actor, command=sel.command, from_state=previous,
                    to_state=dev.state, started=[g.device_id for g in started],
                )
            if sel.command == "CLOSED_TRANSITION_RETRANSFER":
                sync = self.synchro(dev.path)
                if not sync["permissive"]:
                    # Sync-check supervised close: the command waits for
                    # synchronism instead of being refused (as a real
                    # 25-supervised close does); timeout cancels it.
                    self._sync_close[dev.path] = {
                        "device_id": dev.device_id, "actor": actor,
                        "deadline": self.clock() + SYNC_CLOSE_TIMEOUT_S,
                    }
                    return self._event(
                        "command", dev, actor, command=sel.command, from_state=previous,
                        to_state=dev.state, sync_close_armed=True,
                        timeout_s=SYNC_CLOSE_TIMEOUT_S, angle_deg=sync["angle_deg"],
                        slip_hz=sync["slip_hz"],
                    )
                dev.state, dev.state_since = XFER_UTILITY, self.clock()
                self._closed_main(dev.path, cub.BREAKER_U)
                self.gen_hz[dev.path], self.sync_angle[dev.path] = UTILITY_HZ, 0.0
                self._advance()
                return self._event(
                    "command", dev, actor, command=sel.command, from_state=previous,
                    to_state=dev.state, closed_transition=True, angle_deg=sync["angle_deg"],
                    slip_hz=sync["slip_hz"], overlap_ms=CLOSED_TRANSITION_OVERLAP_MS,
                )
            if sel.command == "STOP_GENERATORS":
                stopped = self._running_sets(dev.path)
                for gen in stopped:
                    mv.apply(self.bays[gen.device_id], mv.OP_OPEN_CB, self.clock())
                    gen.state, gen.state_since = GEN_COOLDOWN, self.clock()
                self._advance()
                return self._event(
                    "command", dev, actor, command=sel.command, from_state=previous,
                    to_state=dev.state, stopped=[g.device_id for g in stopped],
                )
            dev.state = _NEXT_STATE[sel.command]
            dev.state_since = self.clock()
            if sel.command == "TRANSFER_TO_GENERATORS":
                self._closed_main(dev.path, cub.BREAKER_GM)
            elif sel.command == "RETRANSFER_TO_UTILITY":
                self._closed_main(dev.path, cub.BREAKER_U)
            if sel.command == "ISOLATE" and dev.device_id in self.faults:
                # Training assumption: the isolated block is repaired.
                del self.faults[dev.device_id]
            if sel.command == "STOP":
                mv.apply(self.bays[device_id], mv.OP_OPEN_CB, self.clock())
            self._advance()
            return self._event(
                "command", dev, actor, command=sel.command,
                from_state=previous, to_state=dev.state,
            )

    def refusal_event(self, device_id: str, actor: str, detail: str, **extra: Any) -> None:
        with self._lock:
            dev = self.devices.get(device_id)
            if dev is not None:
                self._event("refused", dev, actor, detail=detail, **extra)

    # ── MV bay switching ────────────────────────────────────────────
    def _bay_procedure(self, bay_id: str) -> mv.Procedure | None:
        for proc in self.procedures.values():
            if proc.bay_id == bay_id and not proc.complete:
                return proc
        return None

    def _bay_context(self, dev: Device) -> mv.BayContext:
        stopped = dev.state == GEN_STANDBY
        remaining = sum(
            d.rated_kw for d in self._gens_available(dev.path) if d is not dev
        )
        return mv.BayContext(
            now=self.clock(),
            engine_stopped=stopped,
            engine_at_rated=dev.state in (GEN_RUNNING, GEN_ON_LOAD),
            voltage_present=not stopped,
            # DC-EPMS-067: with this bay out the path must keep its
            # TOTAL load in available generation, not just the IT load.
            path_keeps_capacity=remaining >= self._generation_floor_kw(dev.path),
        )

    def _goal_reason(self, dev: Device, goal: str) -> str | None:
        bay = self.bays[dev.device_id]
        if goal == mv.GOAL_ISOLATE:
            if bay.loto or not bay.in_service:
                return "Bay is already out of service."
            if dev.state != GEN_STANDBY:
                return "Stop the generator first: the engine must be in standby."
            if not self._bay_context(dev).path_keeps_capacity:
                remaining = sum(
                    d.rated_kw for d in self._gens_available(dev.path) if d is not dev
                )
                return (
                    f"With this bay out the path keeps {remaining / 1000:.2f} MW of generation, "
                    f"below its {self._generation_floor_kw(dev.path) / 1000:.2f} MW total load "
                    "(IT + cooling + auxiliaries + UPS losses)."
                )
            return None
        if bay.in_service:
            return "Bay is already in service."
        return None

    def bay_attempt(self, bay_id: str, operation: str, actor: str) -> dict[str, Any]:
        """Evaluate and, if permitted, apply ONE raw bay operation.
        Not exposed over HTTP: live switching goes through procedures.
        Used by the scenario sandbox to rehearse unsafe attempts."""
        with self._lock:
            self._advance()
            dev = self._get(bay_id)
            if dev.kind != KIND_GENERATOR:
                raise DeviceControlError(404, f"{bay_id!r} has no medium-voltage bay")
            bay = self.bays[bay_id]
            reason = mv.interlock(bay, operation, self._bay_context(dev))
            if reason:
                self._event("bay_blocked", dev, actor, operation=operation, detail=reason)
                raise DeviceControlError(409, reason)
            mv.apply(bay, operation, self.clock())
            return self._event("bay_step", dev, actor, operation=operation,
                               label=mv.OP_LABELS[operation])

    def start_procedure(self, bay_id: str, goal: str, actor: str) -> dict[str, Any]:
        goal = str(goal or "").upper()
        with self._lock:
            self._advance()
            dev = self._get(bay_id)
            if dev.kind != KIND_GENERATOR:
                raise DeviceControlError(404, f"{bay_id!r} has no medium-voltage bay")
            if goal not in mv.GOALS:
                raise DeviceControlError(400, f"goal must be one of {list(mv.GOALS)}")
            if self._bay_procedure(bay_id) is not None:
                raise DeviceControlError(409, "a switching procedure is already in progress on this bay")
            reason = self.authority_reason(dev) or self._goal_reason(dev, goal)
            if reason:
                raise DeviceControlError(409, reason)
            proc = mv.Procedure(
                procedure_id=secrets.token_hex(6), bay_id=bay_id, goal=goal,
                operator=actor, started_at=self.clock(),
                steps=mv.plan(goal, self.bays[bay_id]),
            )
            self.procedures[proc.procedure_id] = proc
            self._event("procedure_started", dev, actor, goal=goal,
                        procedure_id=proc.procedure_id)
            return proc.describe(self.clock())

    def _procedure(self, procedure_id: str) -> mv.Procedure:
        proc = self.procedures.get(str(procedure_id or ""))
        if proc is None:
            raise DeviceControlError(404, "switching procedure not found")
        if proc.complete:
            raise DeviceControlError(409, "switching procedure is already complete")
        return proc

    def witness_step(self, procedure_id: str, step: int, witness: str) -> dict[str, Any]:
        with self._lock:
            proc = self._procedure(procedure_id)
            index = proc.next_index
            if int(step) != index + 1:
                raise DeviceControlError(409, f"only step {index + 1} can be witnessed now")
            if not proc.steps[index][2]:
                raise DeviceControlError(409, "this step does not need a second person")
            if witness == proc.operator:
                raise DeviceControlError(
                    403, "two-person rule: the witness must be a different person from the operator",
                )
            proc.witnesses[index] = (witness, self.clock())
            self._event("procedure_witness", self._get(proc.bay_id), witness,
                        procedure_id=proc.procedure_id, step=index + 1)
            return proc.describe(self.clock())

    def execute_step(self, procedure_id: str, step: int, actor: str) -> dict[str, Any]:
        with self._lock:
            self._advance()
            proc = self._procedure(procedure_id)
            dev = self._get(proc.bay_id)
            index = proc.next_index
            operation, _gate, two_person = proc.steps[index]

            def refuse(status: int, detail: str) -> None:
                proc.blocked_attempts += 1
                self._event("procedure_blocked", dev, actor, procedure_id=proc.procedure_id,
                            step=index + 1, operation=operation, detail=detail)
                raise DeviceControlError(status, detail)

            if actor != proc.operator:
                refuse(403, "this procedure belongs to another operator")
            if int(step) != index + 1:
                refuse(409, f"sequence deviation: step {index + 1} "
                            f"({mv.OP_LABELS[operation]}) is the only step permitted now")
            reason = self.authority_reason(dev)
            if reason:
                refuse(409, reason)
            if two_person and not proc.witness_ok(index, self.clock()):
                refuse(409, "two-person rule: a second person must approve this step first "
                            f"(approval valid for {mv.WITNESS_VALID_S:.0f} s)")
            reason = mv.interlock(self.bays[proc.bay_id], operation, self._bay_context(dev))
            if reason:
                refuse(409, reason)
            mv.apply(self.bays[proc.bay_id], operation, self.clock())
            proc.next_index += 1
            self._event(
                "procedure_step", dev, actor, procedure_id=proc.procedure_id,
                step=index + 1, operation=operation, label=mv.OP_LABELS[operation],
                witness=proc.witnesses.get(index, (None, 0.0))[0],
                complete=proc.complete,
            )
            return proc.describe(self.clock())

    def abort_procedure(self, procedure_id: str, actor: str) -> dict[str, Any]:
        """Stop a procedure where it is. Positions are NOT rolled back:
        the bay stays in the state the completed steps left it."""
        with self._lock:
            proc = self._procedure(procedure_id)
            dev = self._get(proc.bay_id)
            described = proc.describe(self.clock())
            del self.procedures[proc.procedure_id]
            self._event("procedure_aborted", dev, actor, procedure_id=proc.procedure_id,
                        at_step=proc.next_index + 1)
            return described

    # ── Simulation injection (scenario sandbox only) ────────────────
    def inject_path_loss(self, path: str) -> None:
        """One path lost: the survivors carry the whole IT load."""
        with self._lock:
            if path not in self.path_share:
                raise DeviceControlError(404, f"unknown path {path!r}")
            survivors = [p for p in self.path_share if p != path]
            self.path_share[path] = 0.0
            for other in survivors:
                self.path_share[other] = 1.0 / len(survivors)


# ── Pure helpers ────────────────────────────────────────────────────
def window_entry_s(angle_deg: float, slip_hz: float,
                   window_deg: float = SYNC_MAX_ANGLE_DEG) -> float | None:
    """Seconds until the phase angle is inside +/-window (0 if already
    inside), the needle turning at 360 x slip deg/s. None if it never
    gets there (no slip and outside the window)."""
    a = (float(angle_deg) + 180.0) % 360.0 - 180.0
    if abs(a) <= window_deg:
        return 0.0
    rate = 360.0 * float(slip_hz)
    if rate == 0:
        return None
    if rate > 0:
        target = math.ceil((a + window_deg) / 360.0) * 360.0 - window_deg
        return (target - a) / rate
    target = math.floor((a - window_deg) / 360.0) * 360.0 + window_deg
    return (a - target) / -rate


def _cubicle_text(c: cub.Cubicle) -> str:
    parts = [c.racking]
    parts.append("SPRING CHARGED" if c.spring_charged else "SPRING DISCHARGED")
    if c.lockout_86:
        parts.append("86 TRIPPED")
    if c.padlock:
        parts.append(f"PADLOCK {c.padlock}")
    return " · ".join(parts)


def _num(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _r(label: str, value: float, unit: str, digits: int) -> dict[str, Any]:
    return {"label": label, "value": round(float(value), digits), "unit": unit}


# ── Authorisation ───────────────────────────────────────────────────
def authorise(request: Request, body: dict[str, Any], *, minimum: str = "FACILITY_MANAGER") -> str:
    """Return the acting person's name, or raise 401 / 403.

    A session token (Authorization header or the gate cookie) is the
    source of truth when present: ``minimum`` role is required and the
    body's ``actor_role`` is ignored. Without a token, and only when
    the session gate is OFF (local development), the legacy
    ``actor_role == SME_L6`` rule of /api/bms/write applies.
    """
    from backend.auth.jwt_handler import TokenError, verify_token
    from backend.auth.models import Role, role_at_least
    from backend.auth.session_gate import _extract_token, gate_enabled

    token = _extract_token(request.scope)
    if token:
        try:
            claims = verify_token(token)
        except TokenError as exc:
            raise HTTPException(401, f"invalid token: {exc}") from exc
        if not role_at_least(claims.role, Role[minimum]):
            raise HTTPException(
                403, f"this action requires {minimum}; role {claims.role.value} is insufficient.",
            )
        return claims.username
    if gate_enabled():
        raise HTTPException(401, "authentication required")
    from backend.cmms_models import role_rank

    if role_rank(body.get("actor_role")) < 6:
        raise HTTPException(
            403, f"this action requires SME_L6; actor_role={body.get('actor_role')!r} is insufficient.",
        )
    return str(body.get("user") or "dashboard-operator")


async def _ledger_append(app: FastAPI, actor: str, action: str, payload: dict[str, Any]) -> str | None:
    ledger = getattr(app.state, "forensic_ledger", None)
    if ledger is None:
        return None
    entry = await ledger.append(actor=actor, action=action, payload=payload)
    return getattr(entry, "entry_id", None)


# ── Routes ──────────────────────────────────────────────────────────
def register_device_control_routes(
    app: FastAPI,
    controller_getter: Callable[[], DeviceController | None],
) -> None:
    def _controller() -> DeviceController:
        ctl = controller_getter()
        if ctl is None:
            raise HTTPException(503, "device control unavailable: power plant design not loaded")
        return ctl

    def _fail(exc: DeviceControlError) -> HTTPException:
        return HTTPException(exc.status, exc.detail)

    @app.get("/api/devices")
    async def list_devices() -> dict[str, Any]:
        """Readings, state, capacity checks and permitted commands of
        the whole plant. Read-only."""
        return _controller().snapshot_all()

    @app.get("/api/devices/{device_id}")
    async def get_device(device_id: str) -> dict[str, Any]:
        try:
            return _controller().snapshot(device_id)
        except DeviceControlError as exc:
            raise _fail(exc) from exc

    @app.post("/api/devices/{device_id}/authority")
    async def set_device_authority(
        device_id: str, request: Request, payload: dict = Body(...),
    ) -> dict[str, Any]:
        """Change the control authority (AUTO / REMOTE / LOCAL)."""
        actor = authorise(request, payload)
        ctl = _controller()
        try:
            event = ctl.set_authority(device_id, payload.get("authority"), actor)
        except DeviceControlError as exc:
            raise _fail(exc) from exc
        entry_id = await _ledger_append(
            request.app, actor, ACTION_DEVICE_AUTHORITY,
            {k: event[k] for k in ("device_id", "previous", "authority", "source")},
        )
        return {"success": True, "event": event, "ledger_entry_id": entry_id}

    @app.post("/api/devices/{device_id}/select")
    async def select_device_command(
        device_id: str, request: Request, payload: dict = Body(...),
    ) -> dict[str, Any]:
        """Step 1 of select-before-operate. Changes nothing."""
        actor = authorise(request, payload)
        ctl = _controller()
        try:
            return ctl.select(device_id, payload.get("command"), actor)
        except DeviceControlError as exc:
            ctl.refusal_event(device_id, actor, exc.detail,
                              command=str(payload.get("command") or ""))
            raise _fail(exc) from exc

    @app.post("/api/devices/{device_id}/operate")
    async def operate_device_command(
        device_id: str, request: Request, payload: dict = Body(...),
    ) -> dict[str, Any]:
        """Step 2 of select-before-operate. Ledger pre-entry before,
        result entry after."""
        actor = authorise(request, payload)
        ctl = _controller()
        token = str(payload.get("select_token") or "")
        requested_id = await _ledger_append(
            request.app, actor, ACTION_DEVICE_COMMAND_REQUESTED,
            {"device_id": device_id, "command": ctl.peek_command(token)},
        )
        try:
            event = ctl.operate(device_id, token, actor)
        except DeviceControlError as exc:
            ctl.refusal_event(device_id, actor, exc.detail)
            await _ledger_append(
                request.app, actor, ACTION_DEVICE_COMMAND_RESULT,
                {"device_id": device_id, "success": False, "detail": exc.detail,
                 "requested_entry_id": requested_id},
            )
            raise _fail(exc) from exc
        result_id = await _ledger_append(
            request.app, actor, ACTION_DEVICE_COMMAND_RESULT,
            {"device_id": device_id, "success": True, "command": event["command"],
             "from_state": event["from_state"], "to_state": event["to_state"],
             "requested_entry_id": requested_id},
        )
        return {"success": True, "event": event, "ledger_entry_id": result_id}

    @app.post("/api/devices/{device_id}/governor")
    async def adjust_governor(
        device_id: str, request: Request, payload: dict = Body(...),
    ) -> dict[str, Any]:
        """T3: governor raise / lower (closed-transition training mode).
        Direct control, recorded in the plant event log (not the
        Forensic Ledger: one entry per click would flood it)."""
        actor = authorise(request, payload)
        ctl = _controller()
        try:
            event = ctl.adjust_governor(device_id, payload.get("delta_hz"), actor)
        except DeviceControlError as exc:
            raise _fail(exc) from exc
        return {"success": True, "event": event, "synchro": ctl.synchro(ctl.devices[device_id].path)}

    @app.post("/api/devices/{device_id}/sync-cancel")
    async def cancel_sync_close(
        device_id: str, request: Request, payload: dict = Body(default={}),
    ) -> dict[str, Any]:
        """T3: cancel an armed sync-check supervised close."""
        actor = authorise(request, payload or {})
        ctl = _controller()
        try:
            out = ctl.cancel_sync_close(device_id, actor)
        except DeviceControlError as exc:
            raise _fail(exc) from exc
        return {"success": True, **out}

    @app.post("/api/devices/{device_id}/field")
    async def switchgear_field_action(
        device_id: str, request: Request, payload: dict = Body(...),
    ) -> dict[str, Any]:
        """L1: an operation at the 13.8 kV switchgear of a path
        (racking, closing spring, local push buttons, 86 lockout,
        personal padlock). One ledger entry per accepted action;
        refusals go to the plant event log (a drill counts them)."""
        actor = authorise(request, payload)
        ctl = _controller()
        breaker = str(payload.get("breaker") or "")
        action = str(payload.get("action") or "")
        try:
            event = ctl.field_action(device_id, breaker, action, actor)
        except DeviceControlError as exc:
            ctl.refusal_event(device_id, actor, exc.detail,
                              command=f"{action.upper()}@{breaker.upper()}")
            raise _fail(exc) from exc
        entry_id = await _ledger_append(
            request.app, actor, ACTION_MV_FIELD,
            {k: event.get(k) for k in ("device_id", "breaker", "action", "racking",
                                        "breaker_closed", "lockout_86", "padlock",
                                        "from_state", "to_state")},
        )
        return {"success": True, "event": event, "ledger_entry_id": entry_id}

    @app.post("/api/devices/{device_id}/xfmr")
    async def transformer_field_action(
        device_id: str, request: Request, payload: dict = Body(...),
    ) -> dict[str, Any]:
        """L2: an operation at the utility transformer of a path (52-T,
        Kirk keys, DETC handle, relay targets, fan selector)."""
        actor = authorise(request, payload)
        ctl = _controller()
        action = str(payload.get("action") or "")
        try:
            event = ctl.xfmr_action(device_id, action, actor)
        except DeviceControlError as exc:
            ctl.refusal_event(device_id, actor, exc.detail, command=f"{action.upper()}@XFMR")
            raise _fail(exc) from exc
        entry_id = await _ledger_append(
            request.app, actor, ACTION_XFMR_FIELD,
            {k: event.get(k) for k in ("device_id", "action", "tap_from", "tap", "key_k1",
                                        "key_k2", "primary_closed", "detc_unlocked_by",
                                        "energized_before", "energized", "outcome")},
        )
        return {"success": True, "event": event, "ledger_entry_id": entry_id}

    # ── MV switching procedures ─────────────────────────────────────
    @app.post("/api/mv/bays/{bay_id}/procedure")
    async def start_mv_procedure(
        bay_id: str, request: Request, payload: dict = Body(...),
    ) -> dict[str, Any]:
        """Start a forced switching procedure on a generator bay."""
        actor = authorise(request, payload)
        ctl = _controller()
        try:
            proc = ctl.start_procedure(bay_id, payload.get("goal"), actor)
        except DeviceControlError as exc:
            ctl.refusal_event(bay_id, actor, exc.detail, command=str(payload.get("goal") or ""))
            raise _fail(exc) from exc
        entry_id = await _ledger_append(
            request.app, actor, ACTION_MV_PROCEDURE,
            {"bay_id": bay_id, "goal": proc["goal"], "procedure_id": proc["procedure_id"],
             "event": "started"},
        )
        return {"success": True, "procedure": proc, "ledger_entry_id": entry_id}

    @app.post("/api/mv/procedures/{procedure_id}/witness")
    async def witness_mv_step(
        procedure_id: str, request: Request, payload: dict = Body(...),
    ) -> dict[str, Any]:
        """Second-person approval of the next step. The witness
        authenticates as THEMSELVES (own token, or own credentials
        typed at the operator's console), needs SAFETY_OFFICER or
        above, and must not be the operator."""
        if payload.get("witness_username"):
            # Second person at the same console: credentials are
            # checked here and never stored, logged or echoed. The
            # operator's own session is left untouched.
            witness = _witness_from_credentials(request, payload)
        else:
            witness = authorise(request, payload, minimum="SAFETY_OFFICER")
        ctl = _controller()
        step = _int(payload.get("step"))
        try:
            proc = ctl.witness_step(procedure_id, step, witness)
        except DeviceControlError as exc:
            raise _fail(exc) from exc
        entry_id = await _ledger_append(
            request.app, witness, ACTION_MV_WITNESS,
            {"procedure_id": procedure_id, "bay_id": proc["bay_id"], "step": step},
        )
        return {"success": True, "procedure": proc, "ledger_entry_id": entry_id}

    @app.post("/api/mv/procedures/{procedure_id}/step")
    async def execute_mv_step(
        procedure_id: str, request: Request, payload: dict = Body(...),
    ) -> dict[str, Any]:
        """Execute the next step. Any other step is a sequence
        deviation: blocked and recorded."""
        actor = authorise(request, payload)
        ctl = _controller()
        step = _int(payload.get("step"))
        try:
            proc = ctl.execute_step(procedure_id, step, actor)
        except DeviceControlError as exc:
            await _ledger_append(
                request.app, actor, ACTION_MV_STEP,
                {"procedure_id": procedure_id, "step": step, "success": False,
                 "detail": exc.detail},
            )
            raise _fail(exc) from exc
        done = proc["steps"][step - 1]
        entry_id = await _ledger_append(
            request.app, actor, ACTION_MV_STEP,
            {"procedure_id": procedure_id, "bay_id": proc["bay_id"], "step": step,
             "operation": done["operation"], "witness": done["witness"],
             "success": True, "complete": proc["complete"]},
        )
        return {"success": True, "procedure": proc, "ledger_entry_id": entry_id}

    @app.post("/api/mv/procedures/{procedure_id}/abort")
    async def abort_mv_procedure(
        procedure_id: str, request: Request, payload: dict = Body(...),
    ) -> dict[str, Any]:
        """Stop a procedure. Positions are not rolled back."""
        actor = authorise(request, payload)
        ctl = _controller()
        try:
            proc = ctl.abort_procedure(procedure_id, actor)
        except DeviceControlError as exc:
            raise _fail(exc) from exc
        entry_id = await _ledger_append(
            request.app, actor, ACTION_MV_PROCEDURE,
            {"bay_id": proc["bay_id"], "goal": proc["goal"],
             "procedure_id": procedure_id, "event": "aborted"},
        )
        return {"success": True, "procedure": proc, "ledger_entry_id": entry_id}


def _witness_from_credentials(request: Request, body: dict[str, Any]) -> str:
    from backend.auth.jwt_handler import LoginError, login
    from backend.auth.models import Role, role_at_least

    store = getattr(request.app.state, "user_store", None)
    if store is None:
        raise HTTPException(503, "user store not initialised")
    try:
        granted = login(
            store,
            username=str(body.get("witness_username") or ""),
            password=str(body.get("witness_password") or ""),
        )
    except LoginError as exc:
        raise HTTPException(401, "witness credentials rejected") from exc
    if not role_at_least(Role(str(granted["role"])), Role.SAFETY_OFFICER):
        raise HTTPException(
            403, f"a witness needs SAFETY_OFFICER; role {granted['role']} is insufficient.",
        )
    return str(granted["username"])


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
