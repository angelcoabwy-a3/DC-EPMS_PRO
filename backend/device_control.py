"""
backend/device_control.py
=========================
Release R3-A -- Power device control panels (UPS, transfer switch,
generator): readings + supervised manual / remote switching.

What this module IS
-------------------
A deterministic supervisory-control model, one instance per
controllable device found in ``config/site_model.yml`` (types
``ups``, ``ats`` and ``genset``). Each device has:

  * a state machine (UPS operating mode, transfer position, genset
    run state),
  * a readings block derived from that state and the site-model
    ratings,
  * a control AUTHORITY selector: AUTO / REMOTE / LOCAL,
  * a command set with interlocks.

What this module is NOT (honest scope)
--------------------------------------
  * No field device is behind it. Every value is ``simulated`` and
    the payload says so. The HAL adapters in ``backend/hal`` are not
    wired here; binding them is commissioning work (roadmap R3-C).
  * No protection functions (ANSI 27/59/81/25). The interlocks below
    are supervisory permissives only. A real installation keeps its
    hardwired interlocks regardless of what this layer allows.

Control discipline
------------------
  * ADR-006: commands are accepted only from an authenticated human.
    Nothing in the agent stack imports this module
    (``tests/test_device_control.py::TestAgentIsolation``).
  * Authority: remote commands are refused unless the device is in
    REMOTE. LOCAL models the key switch at the equipment and wins
    over everything; AUTO leaves the device to its own controller.
  * Select-before-operate: ``select`` returns a single-use token valid
    for ``SELECT_TTL_S`` seconds; ``operate`` executes only with that
    token and the same actor. Interlocks are evaluated twice.
  * Every authority change and every operate attempt is appended to
    the Forensic Ledger (ADR-011) when one is available.

Vocabulary fence (S-VOCAB-01): this module covers AC equipment only.
The 800 VDC unipolar TN-S side (MV rectifier, SSCB, BESS) is out of
scope and is never described here with phase wording.
"""

from __future__ import annotations

import math
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request

# ── Kinds ───────────────────────────────────────────────────────────
KIND_UPS = "ups"
KIND_TRANSFER = "transfer"
KIND_GENERATOR = "generator"
KINDS = (KIND_UPS, KIND_TRANSFER, KIND_GENERATOR)

_TYPE_TO_KIND = {"ups": KIND_UPS, "ats": KIND_TRANSFER, "genset": KIND_GENERATOR}

# ── Authority ───────────────────────────────────────────────────────
AUTH_AUTO = "AUTO"
AUTH_REMOTE = "REMOTE"
AUTH_LOCAL = "LOCAL"
AUTHORITIES = (AUTH_AUTO, AUTH_REMOTE, AUTH_LOCAL)

# ── UPS operating modes (IEC 62040-3 wording) ───────────────────────
UPS_DOUBLE_CONVERSION = "DOUBLE_CONVERSION"
UPS_STATIC_BYPASS = "STATIC_BYPASS"
UPS_MAINT_BYPASS = "MAINTENANCE_BYPASS"

# ── Transfer positions ──────────────────────────────────────────────
XFER_NORMAL = "NORMAL"
XFER_EMERGENCY = "EMERGENCY"

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
DEFAULT_VOLTAGE_V = 480.0
LOAD_FRACTION = 0.62
POWER_FACTOR = 0.98
EFF_DOUBLE_CONVERSION = 0.965
EFF_BYPASS = 0.99
STARTER_FLOAT_V = 25.6
STARTER_CRANK_V = 21.8
RATED_RPM = 1800

ACTION_DEVICE_AUTHORITY = "DEVICE_AUTHORITY_CHANGED"
ACTION_DEVICE_COMMAND_REQUESTED = "DEVICE_COMMAND_REQUESTED"
ACTION_DEVICE_COMMAND_RESULT = "DEVICE_COMMAND_RESULT"

SIMULATION_NOTICE = (
    "SIMULATED devices. No field equipment is connected: states and "
    "readings come from a deterministic model, and the interlocks are "
    "supervisory permissives, not protection."
)

EVENT_LOG_SIZE = 100


class DeviceControlError(Exception):
    """A command or authority change was refused. ``status`` is the
    HTTP status the route reports."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


# Commands: kind -> name -> (label, description)
COMMANDS: dict[str, dict[str, tuple[str, str]]] = {
    KIND_UPS: {
        "TRANSFER_TO_BYPASS": (
            "Transfer to static bypass",
            "Load moves from the inverter to the static bypass. The load is "
            "no longer conditioned or battery-backed.",
        ),
        "RETURN_TO_INVERTER": (
            "Return to inverter",
            "Load returns from static bypass to double conversion.",
        ),
        "ENGAGE_MAINT_BYPASS": (
            "Engage maintenance bypass",
            "Closes the maintenance bypass around the UPS. Allowed only from "
            "static bypass.",
        ),
        "RELEASE_MAINT_BYPASS": (
            "Release maintenance bypass",
            "Opens the maintenance bypass. The UPS returns to static bypass.",
        ),
    },
    KIND_TRANSFER: {
        "TRANSFER_TO_EMERGENCY": (
            "Transfer to emergency source",
            "Load transfers from the normal source to the generator source.",
        ),
        "RETRANSFER_TO_NORMAL": (
            "Retransfer to normal source",
            "Load returns to the normal source.",
        ),
    },
    KIND_GENERATOR: {
        "START": (
            "Start engine",
            "Cranks the engine and brings it to rated voltage and frequency, "
            "unloaded.",
        ),
        "STOP": (
            "Stop engine",
            "Starts the cooldown run and stops the engine. Refused while the "
            "set is the only source carrying load.",
        ),
    },
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
    rated_amps: float
    voltage_v: float
    runtime_full_load_min: float
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


@dataclass
class DeviceController:
    """In-memory supervisory model. Thread-safe; time is injected."""

    clock: Callable[[], float] = time.monotonic
    wall_clock: Callable[[], float] = time.time
    devices: dict[str, Device] = field(default_factory=dict)
    _selections: dict[str, _Selection] = field(default_factory=dict)
    _events: deque = field(default_factory=lambda: deque(maxlen=EVENT_LOG_SIZE))
    _lock: threading.RLock = field(default_factory=threading.RLock)

    # ── Construction ────────────────────────────────────────────────
    @classmethod
    def from_components(
        cls,
        components: dict[str, dict[str, Any]],
        *,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> DeviceController:
        ctl = cls(clock=clock, wall_clock=wall_clock)
        now = clock()
        for device_id in sorted(components):
            meta = components[device_id] or {}
            kind = _TYPE_TO_KIND.get(str(meta.get("type", "")))
            if kind is None:
                continue
            initial = {
                KIND_UPS: UPS_DOUBLE_CONVERSION,
                KIND_TRANSFER: XFER_NORMAL,
                KIND_GENERATOR: GEN_STANDBY,
            }[kind]
            ctl.devices[device_id] = Device(
                device_id=device_id,
                kind=kind,
                display=str(meta.get("display") or device_id),
                path=path_of(device_id),
                vendor=str(meta.get("vendor") or ""),
                model=str(meta.get("model") or ""),
                rated_kw=_num(meta.get("rated_kw")),
                rated_amps=_num(meta.get("rated_amps")),
                voltage_v=_num(meta.get("voltage_v")) or DEFAULT_VOLTAGE_V,
                runtime_full_load_min=_num(meta.get("runtime_full_load_min")),
                state=initial,
                state_since=now,
            )
        return ctl

    # ── Time evolution ──────────────────────────────────────────────
    def _advance(self) -> None:
        now = self.clock()
        for dev in self.devices.values():
            if dev.kind != KIND_GENERATOR:
                continue
            elapsed = now - dev.state_since
            if dev.state == GEN_CRANKING and elapsed >= CRANK_TIME_S:
                dev.state, dev.state_since = GEN_RUNNING, dev.state_since + CRANK_TIME_S
            elif dev.state == GEN_COOLDOWN and elapsed >= COOLDOWN_TIME_S:
                dev.state, dev.state_since = GEN_STANDBY, dev.state_since + COOLDOWN_TIME_S
        # ON_LOAD is derived from the path transfer position.
        for dev in self.devices.values():
            if dev.kind != KIND_GENERATOR:
                continue
            on_emergency = self._path_on_emergency(dev.path)
            if dev.state == GEN_RUNNING and on_emergency:
                dev.state, dev.state_since = GEN_ON_LOAD, now
            elif dev.state == GEN_ON_LOAD and not on_emergency:
                dev.state, dev.state_since = GEN_RUNNING, now

    # ── Path helpers ────────────────────────────────────────────────
    def _of(self, kind: str, path: str) -> list[Device]:
        return [d for d in self.devices.values() if d.kind == kind and d.path == path]

    def _path_on_emergency(self, path: str) -> bool:
        return any(d.state == XFER_EMERGENCY for d in self._of(KIND_TRANSFER, path))

    def _generators_ready(self, path: str) -> list[Device]:
        return [
            d for d in self._of(KIND_GENERATOR, path)
            if d.state in (GEN_RUNNING, GEN_ON_LOAD)
        ]

    def _path_load_kw(self, path: str) -> float:
        return sum(d.rated_kw * LOAD_FRACTION for d in self._of(KIND_UPS, path))

    def _path_input_kw(self, path: str) -> float:
        total = 0.0
        for d in self._of(KIND_UPS, path):
            eff = EFF_DOUBLE_CONVERSION if d.state == UPS_DOUBLE_CONVERSION else EFF_BYPASS
            total += d.rated_kw * LOAD_FRACTION / eff
        return total

    # ── Interlocks ──────────────────────────────────────────────────
    def blocked_reason(self, dev: Device, command: str) -> str | None:
        """Why ``command`` cannot run now, or None when permitted.
        Authority is checked separately (``authority_reason``)."""
        if dev.kind == KIND_UPS:
            if command == "TRANSFER_TO_BYPASS":
                if dev.state != UPS_DOUBLE_CONVERSION:
                    return "UPS is not in double conversion."
                return None
            if command == "RETURN_TO_INVERTER":
                if dev.state != UPS_STATIC_BYPASS:
                    return "UPS is not on static bypass."
                return None
            if command == "ENGAGE_MAINT_BYPASS":
                if dev.state != UPS_STATIC_BYPASS:
                    return "Transfer to static bypass first (make-before-break)."
                return None
            if command == "RELEASE_MAINT_BYPASS":
                if dev.state != UPS_MAINT_BYPASS:
                    return "Maintenance bypass is not engaged."
                return None
        elif dev.kind == KIND_TRANSFER:
            if command == "TRANSFER_TO_EMERGENCY":
                if dev.state != XFER_NORMAL:
                    return "Switch is already on the emergency source."
                if not self._generators_ready(dev.path):
                    return (
                        "Emergency source not available: no generator on path "
                        f"{dev.path.upper()} is at rated voltage and frequency."
                    )
                return None
            if command == "RETRANSFER_TO_NORMAL":
                if dev.state != XFER_EMERGENCY:
                    return "Switch is already on the normal source."
                return None
        elif dev.kind == KIND_GENERATOR:
            if command == "START":
                if dev.state != GEN_STANDBY:
                    return f"Engine is {dev.state.replace('_', ' ').lower()}, not in standby."
                return None
            if command == "STOP":
                if dev.state not in (GEN_RUNNING, GEN_ON_LOAD):
                    return "Engine is not running."
                if dev.state == GEN_ON_LOAD and len(self._generators_ready(dev.path)) <= 1:
                    return (
                        "This set is the only source carrying path "
                        f"{dev.path.upper()}. Retransfer to normal first."
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
            load_kw = dev.rated_kw * LOAD_FRACTION
            on_inverter = dev.state == UPS_DOUBLE_CONVERSION
            eff = EFF_DOUBLE_CONVERSION if on_inverter else EFF_BYPASS
            runtime = (
                dev.runtime_full_load_min / LOAD_FRACTION
                if dev.runtime_full_load_min and on_inverter else 0.0
            )
            return [
                _r("Output load", load_kw, "kW", 0),
                _r("Load", LOAD_FRACTION * 100, "%", 0),
                _r("Input voltage", dev.voltage_v, "V", 0),
                _r("Output voltage", dev.voltage_v, "V", 0),
                _r("Output frequency", NOMINAL_HZ, "Hz", 1),
                _r("Efficiency (model)", eff * 100, "%", 1),
                _r("Losses (model)", load_kw / eff - load_kw, "kW", 0),
                _r("Battery state of charge", 100.0, "%", 0),
                _r("Battery runtime (estimate)", runtime, "min", 1),
            ]
        if dev.kind == KIND_TRANSFER:
            gens_ready = bool(self._generators_ready(dev.path))
            amps = self._path_input_kw(dev.path) * 1000 / (
                math.sqrt(3) * dev.voltage_v * POWER_FACTOR
            )
            return [
                _r("Normal source voltage", dev.voltage_v, "V", 0),
                _r("Normal source frequency", NOMINAL_HZ, "Hz", 1),
                _r("Emergency source voltage", dev.voltage_v if gens_ready else 0.0, "V", 0),
                _r("Emergency source frequency", NOMINAL_HZ if gens_ready else 0.0, "Hz", 1),
                _r("Load current", amps, "A", 0),
                _r("Rated current", dev.rated_amps, "A", 0),
            ]
        # Generator
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
            ready = self._generators_ready(dev.path)
            kw = self._path_input_kw(dev.path) / max(1, len(ready))
        return [
            _r("Engine speed", rpm, "rpm", 0),
            _r("Output voltage", volts, "V", 0),
            _r("Output frequency", hz, "Hz", 1),
            _r("Real power", kw, "kW", 0),
            _r("Load", (kw / dev.rated_kw * 100) if dev.rated_kw else 0.0, "%", 0),
            _r("Starter battery", batt, "V", 1),
        ]

    def _status(self, dev: Device) -> dict[str, str]:
        """Operator-facing condition: tone is ok / warn / crit."""
        if dev.kind == KIND_UPS:
            if dev.state == UPS_DOUBLE_CONVERSION:
                return {"tone": "ok", "text": "Load protected (inverter)"}
            if dev.state == UPS_STATIC_BYPASS:
                return {"tone": "warn", "text": "Load on static bypass, not battery-backed"}
            return {"tone": "crit", "text": "Load on maintenance bypass, UPS out of circuit"}
        if dev.kind == KIND_TRANSFER:
            if dev.state == XFER_NORMAL:
                return {"tone": "ok", "text": "Load on normal source"}
            return {"tone": "warn", "text": "Load on emergency source"}
        tone = {GEN_STANDBY: "ok", GEN_ON_LOAD: "warn"}.get(dev.state, "info")
        text = {
            GEN_STANDBY: "Ready to start",
            GEN_CRANKING: "Cranking",
            GEN_RUNNING: "Running unloaded, at rated voltage and frequency",
            GEN_ON_LOAD: "Carrying load",
            GEN_COOLDOWN: "Cooldown run",
        }[dev.state]
        return {"tone": tone, "text": text}

    # ── Snapshots ───────────────────────────────────────────────────
    def _snapshot(self, dev: Device) -> dict[str, Any]:
        auth_reason = self.authority_reason(dev)
        commands = []
        for name, (label, description) in COMMANDS[dev.kind].items():
            interlock = self.blocked_reason(dev, name)
            # Authority first: it is the one thing the operator can
            # change from here, and it applies to every command.
            reason = auth_reason or interlock
            commands.append({
                "command": name,
                "label": label,
                "description": description,
                "permitted": reason is None,
                "blocked_reason": reason,
            })
        return {
            "id": dev.device_id,
            "kind": dev.kind,
            "display": dev.display,
            "path": dev.path,
            "vendor": dev.vendor,
            "model": dev.model,
            "rated_kw": dev.rated_kw,
            "authority": dev.authority,
            "state": dev.state,
            "state_age_s": round(max(0.0, self.clock() - dev.state_since), 1),
            "status": self._status(dev),
            "readings": self._readings(dev),
            "commands": commands,
            "quality": "simulated",
        }

    def snapshot_all(self) -> dict[str, Any]:
        with self._lock:
            self._advance()
            devices = [self._snapshot(d) for d in self.devices.values()]
        order = {k: i for i, k in enumerate(KINDS)}
        devices.sort(key=lambda d: (order[d["kind"]], d["path"], d["id"]))
        return {
            "notice": SIMULATION_NOTICE,
            "quality": "simulated",
            "authorities": list(AUTHORITIES),
            "select_ttl_s": SELECT_TTL_S,
            "timing": {"crank_s": CRANK_TIME_S, "cooldown_s": COOLDOWN_TIME_S},
            "devices": devices,
            "events": list(self._events)[::-1][:25],
        }

    def snapshot(self, device_id: str) -> dict[str, Any]:
        with self._lock:
            self._advance()
            return self._snapshot(self._get(device_id))

    # ── Mutations ───────────────────────────────────────────────────
    def _get(self, device_id: str) -> Device:
        dev = self.devices.get(device_id)
        if dev is None:
            raise DeviceControlError(404, f"device {device_id!r} is not controllable")
        return dev

    def _event(self, kind: str, dev: Device, actor: str, **extra: Any) -> dict[str, Any]:
        event = {
            "ts": round(self.wall_clock(), 3),
            "event": kind,
            "device_id": dev.device_id,
            "actor": actor,
            **extra,
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
            # A pending selection never survives an authority change.
            self._drop_selections(device_id)
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
            raise DeviceControlError(
                400, f"unknown command {command!r} for a {dev.kind}",
            )
        reason = self.authority_reason(dev)
        if reason:
            raise DeviceControlError(409, reason)
        reason = self.blocked_reason(dev, command)
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
                "select_token": token,
                "expires_in_s": SELECT_TTL_S,
                "device_id": device_id,
                "command": command,
                "label": label,
                "description": description,
                "from_state": dev.state,
            }

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
            dev.state = _NEXT_STATE[sel.command]
            dev.state_since = self.clock()
            self._advance()
            return self._event(
                "command", dev, actor, command=sel.command,
                from_state=previous, to_state=dev.state,
            )

    def peek_command(self, token: str) -> str | None:
        """Command a pending selection refers to (for the ledger
        pre-entry). Never consumes the selection."""
        with self._lock:
            sel = self._selections.get(str(token or ""))
            return sel.command if sel is not None else None

    def refusal_event(self, device_id: str, actor: str, detail: str, **extra: Any) -> None:
        with self._lock:
            dev = self.devices.get(device_id)
            if dev is not None:
                self._event("refused", dev, actor, detail=detail, **extra)


_NEXT_STATE = {
    "TRANSFER_TO_BYPASS": UPS_STATIC_BYPASS,
    "RETURN_TO_INVERTER": UPS_DOUBLE_CONVERSION,
    "ENGAGE_MAINT_BYPASS": UPS_MAINT_BYPASS,
    "RELEASE_MAINT_BYPASS": UPS_STATIC_BYPASS,
    "TRANSFER_TO_EMERGENCY": XFER_EMERGENCY,
    "RETRANSFER_TO_NORMAL": XFER_NORMAL,
    "START": GEN_CRANKING,
    "STOP": GEN_COOLDOWN,
}


# ── Pure helpers ────────────────────────────────────────────────────
def path_of(device_id: str) -> str:
    """Redundancy path from the id convention (``ups_a``,
    ``genset_b_01``). Unknown -> ``"-"`` (the device then pairs with
    nothing, which fails closed: no emergency source is ever found)."""
    for part in str(device_id).lower().split("_")[1:]:
        if len(part) == 1 and part.isalpha():
            return part
    return "-"


def _num(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _r(label: str, value: float, unit: str, digits: int) -> dict[str, Any]:
    return {"label": label, "value": round(float(value), digits), "unit": unit}


# ── Authorisation ───────────────────────────────────────────────────
def authorise(request: Request, body: dict[str, Any]) -> str:
    """Return the acting operator's name, or raise 401 / 403.

    A session token (Authorization header or the gate cookie) is the
    source of truth when present: FACILITY_MANAGER is required and the
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
        if not role_at_least(claims.role, Role.FACILITY_MANAGER):
            raise HTTPException(
                403,
                f"device control requires FACILITY_MANAGER; role "
                f"{claims.role.value} is insufficient.",
            )
        return claims.username
    if gate_enabled():
        raise HTTPException(401, "authentication required")
    from backend.cmms_models import role_rank

    if role_rank(body.get("actor_role")) < 6:
        raise HTTPException(
            403,
            f"device control requires SME_L6; actor_role="
            f"{body.get('actor_role')!r} is insufficient.",
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
            raise HTTPException(503, "device control unavailable: site model not loaded")
        return ctl

    @app.get("/api/devices")
    async def list_devices() -> dict[str, Any]:
        """Readings, state and permitted commands of every controllable
        device. Read-only."""
        return _controller().snapshot_all()

    @app.get("/api/devices/{device_id}")
    async def get_device(device_id: str) -> dict[str, Any]:
        try:
            return _controller().snapshot(device_id)
        except DeviceControlError as exc:
            raise HTTPException(exc.status, exc.detail) from exc

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
            raise HTTPException(exc.status, exc.detail) from exc
        entry_id = await _ledger_append(
            request.app, actor, ACTION_DEVICE_AUTHORITY,
            {k: event[k] for k in ("device_id", "previous", "authority", "source")},
        )
        return {"success": True, "event": event, "ledger_entry_id": entry_id,
                "device": ctl.snapshot(device_id)}

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
            raise HTTPException(exc.status, exc.detail) from exc

    @app.post("/api/devices/{device_id}/operate")
    async def operate_device_command(
        device_id: str, request: Request, payload: dict = Body(...),
    ) -> dict[str, Any]:
        """Step 2 of select-before-operate. Executes the selected
        command; ledger pre-entry before, result entry after."""
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
            raise HTTPException(exc.status, exc.detail) from exc
        result_id = await _ledger_append(
            request.app, actor, ACTION_DEVICE_COMMAND_RESULT,
            {"device_id": device_id, "success": True, "command": event["command"],
             "from_state": event["from_state"], "to_state": event["to_state"],
             "requested_entry_id": requested_id},
        )
        return {"success": True, "event": event, "ledger_entry_id": result_id,
                "device": ctl.snapshot(device_id)}
