"""Building D (Phase 2) simulated plant: 2N, 800 VDC unipolar TN-S.

Lot 12 (2026-11-27, ADR-023). One supervisory model per path (D-A, D-B):

    utility 35 kV (3-phase AC) --+
                                 +--> rectifier group input --> rectifier
    generator farm (13.8 kV,     |    breaker                   group
    step-up to 35 kV) -----------+                              (N units)
                                                                    |
                                           SSCB (bus main) ---------+
                                                |
                                     800 VDC bus (unipolar TN-S) --- BESS
                                                |
                                  rack feeds of BOTH paths (2N)

S-VOCAB-01: "3-phase" only upstream of the rectifiers. The DC side has
no phases; its voltage is ``voltage_v_dc_bus``.

What the model does, per path and per tick (seconds):
  - rectifier input live when its breaker is closed and the selected
    source is live (utility present, or the farm running / on load);
  - rectifier output follows demand within the ramp its AC source
    accepts: the generator farm takes load at a limited rate (block load
    acceptance, MODEL value), the utility at a much higher one (MODEL);
    whatever the source cannot follow yet is carried by the BESS;
  - BESS discharge limited by its converter rating and state of charge;
    it recharges at the design recharge rate through the rectifiers;
  - a bus whose sources cannot carry its share collapses: SSCB and BESS
    breaker trip on undervoltage, the share moves to the other path
    (which may collapse in turn: no load shedding in the model);
  - hall load lost (latched) when no bus carries it.

Farm: AUTO start on utility loss after the start delay (NFPA 110 Type 10
names 10 s; here a MODEL value), automatic transfer of the rectifier
input to the farm, manual retransfer, cooldown. One farm per path, as in
ADR-021 (the SLD still draws one farm block for both).

Interlocks marked "supervisory (model)" are this simulator's rules, not
a vendor's protection scheme. Every number not taken from
``config/design/building_d.yml`` through ``backend/design_model.py`` is
a MODEL value. Pure logic: no FastAPI, no I/O; time is injected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

KIND_RECT = "rectifier"
KIND_SSCB = "sscb"
KIND_BESS = "bess"
KIND_FARM = "farm"
KINDS = (KIND_RECT, KIND_SSCB, KIND_BESS, KIND_FARM)
PATHS = ("a", "b")


def device_path(path: str) -> str:
    """Device path label of a Building D path: 'a' -> 'da'."""
    return f"d{path}"


def device_ids(path: str) -> dict[str, str]:
    s = "" if path == "a" else "_b"
    return {
        KIND_RECT: f"mv_rect_d{s}",
        KIND_SSCB: f"sscb_d{s}",
        KIND_BESS: f"bess_d{s}",
        KIND_FARM: f"farm_d{s}",
    }


SRC_UTILITY = "UTILITY"
SRC_FARM = "FARM"

CLOSED, OPEN, TRIPPED = "CLOSED", "OPEN", "TRIPPED"

FARM_STANDBY = "STANDBY"
FARM_CRANKING = "CRANKING"
FARM_RUNNING = "RUNNING"
FARM_ON_LOAD = "ON_LOAD"
FARM_COOLDOWN = "COOLDOWN"
_FARM_LIVE = (FARM_RUNNING, FARM_ON_LOAD)

TRIP_UNDERVOLTAGE = "UNDERVOLTAGE"
TRIP_BUS_FAULT = "BUS_FAULT"

COMMANDS: dict[str, dict[str, tuple[str, str]]] = {
    KIND_RECT: {
        "OPEN_INPUT": (
            "Open input breaker",
            "Open the 35 kV input breaker of the rectifier group. The bus then rides "
            "on its BESS, or drops its share to the other path.",
        ),
        "CLOSE_INPUT": (
            "Close input breaker",
            "Close the 35 kV input breaker. The group soft-starts at the ramp limit; "
            "the BESS carries the difference meanwhile.",
        ),
        "TRANSFER_TO_FARM": (
            "Transfer input to the farm",
            "Open transition from the utility to the running generator farm. "
            "The BESS bridges the gap.",
        ),
        "RETRANSFER_TO_UTILITY": (
            "Retransfer input to utility",
            "Open transition back to the utility. The farm keeps running "
            "unloaded until stopped.",
        ),
        "UNIT_OUT": (
            "Take one rectifier out",
            "Remove one rectifier module from service (maintenance). Refused below the "
            "design minimum of the path.",
        ),
        "UNIT_IN": ("Return one rectifier", "Return one rectifier module to service."),
    },
    KIND_SSCB: {
        "OPEN": ("Open SSCB", "Open the bus main SSCB. The bus stays on its BESS while it can."),
        "CLOSE": ("Close SSCB", "Close the bus main SSCB (rectifier group onto the 800 VDC bus)."),
        "RESET": (
            "Reset trip",
            "Reset a tripped SSCB to OPEN. Refused while a bus fault is present.",
        ),
        "CLEAR_FAULT": (
            "Record fault cleared",
            "Training step: insulation test passed and the fault repaired. Needs the "
            "bus isolated (SSCB and BESS breaker not closed, rectifier input open).",
        ),
    },
    KIND_BESS: {
        "OPEN_BREAKER": (
            "Open BESS breaker",
            "Disconnect the BESS from the 800 VDC bus (no ride-through, no load-swing "
            "absorption on this path).",
        ),
        "CLOSE_BREAKER": ("Close BESS breaker", "Connect the BESS to the 800 VDC bus."),
        "RESET": ("Reset trip", "Reset a tripped BESS breaker to OPEN."),
    },
    KIND_FARM: {
        "START": ("Start farm", "Crank the generator farm of this path."),
        "STOP": ("Stop farm", "Cooldown run, then standby. Refused while the farm carries load."),
        "SET_AUTO": ("Auto start ON", "The farm starts by itself on utility loss."),
        "SET_MANUAL": ("Auto start OFF", "The farm only starts on an operator command."),
    },
}


@dataclass
class Params:
    """Plant numbers. Defaults mirror ADR-021 revision 3; MODEL values
    are marked."""

    it_kw: float = 50000.0  # DESIGN basis: 250 x 200 kW
    rect_units: int = 14  # per path (2 sections x 7)
    rect_min_units: int = 12  # 6 per section x 2 (N without the +1)
    rect_unit_kw: float = 5000.0
    farm_accept_kw_s: float = 2000.0  # MODEL: farm load acceptance per path
    utility_ramp_kw_s: float = 100000.0  # MODEL: utility follows within one tick
    bess_kwh: float = 15000.0  # per path, installed
    bess_conv_kw: float = 27500.0  # per path: 11 converters x 2.5 MW
    bess_recharge_kw: float = 4167.0  # per path, through the rectifiers
    farm_sets: int = 26
    farm_set_kw: float = 3200.0
    farm_start_s: float = 10.0  # MODEL (NFPA 110 Type 10 names 10 s)
    farm_cooldown_s: float = 30.0  # MODEL
    nominal_v: float = 800.0
    min_v: float = 640.0
    bess_droop_v: float = 10.0  # MODEL: bus 10 V low while on BESS
    utility_kv: float = 35.0


def params_from_sizing(sizing: dict[str, Any]) -> Params:
    """Build plant numbers from ``design_model.size(...)``."""
    p = Params()
    basis = sizing.get("basis") or {}
    chain = {c.get("id"): c for c in sizing.get("chain") or []}

    def v(obj: Any, default: float) -> float:
        if isinstance(obj, dict):
            obj = obj.get("value")
        try:
            return float(obj)
        except (TypeError, ValueError):
            return default

    p.it_kw = v(basis.get("it_kw"), p.it_kw)
    p.nominal_v = v(basis.get("dc_nominal_v"), p.nominal_v)
    p.bess_recharge_kw = v(basis.get("bess_recharge_kw"), p.bess_recharge_kw)
    r = chain.get("mv_rectifiers") or {}
    p.rect_units = int(v(r.get("per_path"), p.rect_units))
    p.rect_unit_kw = v(r.get("unit"), p.rect_unit_kw)
    per_sec, req_sec = int(v(r.get("per_section"), 7)), int(v(r.get("required_per_section"), 6))
    sections = max(1, p.rect_units // max(1, per_sec))
    p.rect_min_units = req_sec * sections
    b = chain.get("bess") or {}
    p.bess_kwh = v(b.get("installed"), p.bess_kwh / 1000.0) * 1000.0
    conv = int(v(b.get("converters"), 22)) // 2
    p.bess_conv_kw = conv * v(b.get("converter_unit"), 2500.0)
    g = chain.get("generators") or {}
    p.farm_sets = int(v(g.get("per_path"), p.farm_sets))
    p.farm_set_kw = v(g.get("unit"), p.farm_set_kw)
    u = chain.get("utility_feed") or {}
    p.utility_kv = v(u.get("voltage"), p.utility_kv)
    return p


@dataclass
class DPath:
    path: str
    utility_ok: bool = True
    input_closed: bool = True
    source: str = SRC_UTILITY
    units_out: int = 0
    rect_out_kw: float = 0.0  # delivered by the rectifiers (load + recharge)
    sscb: str = CLOSED
    sscb_trip: str | None = None
    bus_fault: bool = False
    bess_breaker: str = CLOSED
    bess_trip: str | None = None
    soc: float = 1.0
    bess_kw: float = 0.0  # + discharge, - charge
    farm: str = FARM_STANDBY
    farm_since: float = 0.0
    farm_auto: bool = True
    bus_v: float = 0.0
    carrying_kw: float = 0.0


@dataclass
class LoadStep:
    at: float
    kw: float
    until: float


@dataclass
class BuildingD:
    params: Params = field(default_factory=Params)
    paths: dict[str, DPath] = field(default_factory=dict)
    load_lost: bool = False
    step: LoadStep | None = None
    _at: float | None = None
    _pending: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def create(cls, params: Params | None = None, now: float = 0.0) -> BuildingD:
        plant = cls(params=params or Params())
        share = plant.params.it_kw / len(PATHS)
        for p in PATHS:
            plant.paths[p] = DPath(
                path=p,
                rect_out_kw=share,
                farm_since=now,
                bus_v=plant.params.nominal_v,
                carrying_kw=share,
            )
        plant._at = now
        return plant

    # ── Events ──────────────────────────────────────────────────────
    def _emit(self, event: str, path: str | None, kind: str | None, **extra: Any) -> None:
        ids = device_ids(path) if path else {}
        did = ids.get(kind, "building_d") if kind else "building_d"
        self._pending.append({"event": event, "device_id": did, "path": path, **extra})

    def drain_events(self) -> list[dict[str, Any]]:
        out, self._pending = self._pending, []
        return out

    # ── Derived quantities ──────────────────────────────────────────
    def units_in(self, p: DPath) -> int:
        return max(0, self.params.rect_units - p.units_out)

    def input_live(self, p: DPath) -> bool:
        if not p.input_closed:
            return False
        if p.source == SRC_UTILITY:
            return p.utility_ok
        return p.farm in _FARM_LIVE

    def rect_capacity_kw(self, p: DPath) -> float:
        return self.units_in(p) * self.params.rect_unit_kw if self.input_live(p) else 0.0

    def bess_available(self, p: DPath) -> bool:
        return p.bess_breaker == CLOSED and p.soc > 0.0 and not p.bus_fault

    def rect_feeds_bus(self, p: DPath) -> bool:
        return p.sscb == CLOSED and self.rect_capacity_kw(p) > 0.0 and not p.bus_fault

    def energized(self, p: DPath) -> bool:
        return p.bus_v > 0.0

    def demand_kw(self, now: float) -> float:
        extra = 0.0
        if self.step is not None and self.step.at <= now < self.step.until:
            extra = self.step.kw
        return self.params.it_kw + extra

    def ramp_kw_s(self, p: DPath) -> float:
        return (
            self.params.farm_accept_kw_s if p.source == SRC_FARM else self.params.utility_ramp_kw_s
        )

    def other(self, p: DPath) -> DPath:
        return self.paths["b" if p.path == "a" else "a"]

    # ── Time evolution ──────────────────────────────────────────────
    def advance(self, now: float) -> None:
        if self._at is None:
            self._at = now
        remaining = max(0.0, now - self._at)
        t = self._at
        steps = 0
        while remaining > 1e-9 and steps < 3600:
            dt = min(1.0, remaining)
            t += dt
            self._tick(dt, t)
            remaining -= dt
            steps += 1
        if remaining > 1e-9:  # long idle: settle once at the end
            self._tick(remaining, now)
        self._at = now

    def _tick(self, dt: float, t: float) -> None:
        if self.step is not None and t >= self.step.until:
            self._emit("load_step_end", None, None, kw=self.step.kw)
            self.step = None
        for p in self.paths.values():
            self._farm_tick(p, t)
        demand = self.demand_kw(t)
        if self.load_lost:
            for p in self.paths.values():
                self._idle(p, dt)
            return
        cands = [p for p in self.paths.values() if self.rect_feeds_bus(p) or self.bess_available(p)]
        rect_cap = {p.path: self._rect_capability(p, dt) for p in cands}
        bess_cap = {p.path: self._bess_capability(p) for p in cands}
        cap = {k: rect_cap[k] + bess_cap[k] for k in rect_cap}
        if not cands or sum(cap.values()) + 1e-6 < demand:
            # Not enough source behind the buses: every live bus sags
            # below its undervoltage limit and clears (no load shedding).
            for p in cands:
                self._collapse(
                    p,
                    f"sources {sum(cap.values()) / 1000:.1f} MW below hall "
                    f"demand {demand / 1000:.1f} MW",
                )
            for p in self.paths.values():
                self._idle(p, dt)
            self.load_lost = True
            self._emit("hall_load_lost", None, None, demand_kw=round(demand))
            return
        # Rectifier-fed buses sit at nominal voltage, a bus on its BESS
        # droops: the racks draw from the rectifiers first (equal share
        # within each bus's limit), the BESS only covers what is left.
        alloc = self._share(demand, cands, rect_cap)
        left = demand - sum(alloc.values())
        if left > 1e-6:
            extra = self._share(left, [p for p in cands if bess_cap[p.path] > 0], bess_cap)
            for k, v in extra.items():
                alloc[k] += v
        for p in self.paths.values():
            if p in cands:
                self._carry(p, alloc[p.path], dt)
            else:
                self._idle(p, dt)

    @staticmethod
    def _share(demand: float, cands: list[DPath], cap: dict[str, float]) -> dict[str, float]:
        """Dual-corded racks draw from both buses; a bus that cannot
        deliver its equal share (current limit, ramp) gives the rest to
        the other one (water-filling)."""
        alloc = {p.path: 0.0 for p in cands}
        active = list(cands)
        remaining = demand
        while active:
            share = remaining / len(active)
            limited = [p for p in active if cap[p.path] < share]
            if not limited:
                for p in active:
                    alloc[p.path] = share
                break
            for p in limited:
                alloc[p.path] = cap[p.path]
                remaining -= cap[p.path]
            active = [p for p in active if p not in limited]
        return alloc

    def _farm_tick(self, p: DPath, t: float) -> None:
        pr = self.params
        if p.farm == FARM_STANDBY and p.farm_auto and not p.utility_ok:
            p.farm, p.farm_since = FARM_CRANKING, t
            self._emit("farm_auto_start", p.path, KIND_FARM)
        elif p.farm == FARM_CRANKING and t - p.farm_since >= pr.farm_start_s:
            p.farm, p.farm_since = FARM_RUNNING, t
            self._emit("farm_on_bus", p.path, KIND_FARM, sets=pr.farm_sets)
        elif p.farm == FARM_COOLDOWN and t - p.farm_since >= pr.farm_cooldown_s:
            p.farm, p.farm_since = FARM_STANDBY, t
        if (
            p.farm == FARM_RUNNING
            and p.farm_auto
            and not p.utility_ok
            and p.source == SRC_UTILITY
            and p.input_closed
        ):
            p.source = SRC_FARM
            self._emit("auto_transfer_to_farm", p.path, KIND_RECT)
        if p.farm == FARM_RUNNING and p.source == SRC_FARM and p.input_closed:
            p.farm = FARM_ON_LOAD
        elif p.farm == FARM_ON_LOAD and not (p.source == SRC_FARM and p.input_closed):
            p.farm = FARM_RUNNING

    def _rect_capability(self, p: DPath, dt: float) -> float:
        """What the rectifiers can put on this bus within the next second:
        capacity, limited by the ramp the AC source accepts."""
        if not self.rect_feeds_bus(p):
            return 0.0
        return min(self.rect_capacity_kw(p), p.rect_out_kw + self.ramp_kw_s(p) * max(dt, 1.0))

    def _bess_capability(self, p: DPath) -> float:
        return self.params.bess_conv_kw if self.bess_available(p) else 0.0

    def _carry(self, p: DPath, share: float, dt: float) -> None:
        pr = self.params
        if self.rect_feeds_bus(p):
            want = share
            if p.soc < 1.0 and p.bess_breaker == CLOSED and not p.bus_fault:
                want += pr.bess_recharge_kw
            target = min(want, self.rect_capacity_kw(p))
            if target > p.rect_out_kw:
                p.rect_out_kw = min(target, p.rect_out_kw + self.ramp_kw_s(p) * max(dt, 1.0))
            else:
                p.rect_out_kw = target
        else:
            p.rect_out_kw = 0.0
        to_load = min(p.rect_out_kw, share)
        deficit = share - to_load
        if deficit > 1e-6:
            p.bess_kw = deficit
        elif p.rect_out_kw > share and p.bess_breaker == CLOSED and p.soc < 1.0:
            p.bess_kw = -min(p.rect_out_kw - share, pr.bess_recharge_kw)
        else:
            p.bess_kw = 0.0
        self._soc(p, dt)
        p.carrying_kw = share
        p.bus_v = pr.nominal_v - (pr.bess_droop_v if p.bess_kw > 1.0 else 0.0)
        if p.bess_kw > 1.0 and p.soc <= 0.0:
            self._collapse(p, "BESS empty")

    def _idle(self, p: DPath, dt: float) -> None:
        # Path not carrying: no output, no BESS flow, bus dead.
        del dt
        p.rect_out_kw, p.bess_kw, p.carrying_kw, p.bus_v = 0.0, 0.0, 0.0, 0.0

    def _soc(self, p: DPath, dt: float) -> None:
        if p.bess_kw == 0.0:
            return
        p.soc -= p.bess_kw * dt / 3600.0 / self.params.bess_kwh
        p.soc = max(0.0, min(1.0, p.soc))

    def _collapse(self, p: DPath, why: str) -> None:
        tripped = []
        if p.sscb == CLOSED:
            p.sscb, p.sscb_trip = TRIPPED, TRIP_UNDERVOLTAGE
            tripped.append("SSCB")
        if p.bess_breaker == CLOSED:
            p.bess_breaker, p.bess_trip = TRIPPED, TRIP_UNDERVOLTAGE
            tripped.append("BESS")
        p.bus_v, p.carrying_kw, p.bess_kw, p.rect_out_kw = 0.0, 0.0, 0.0, 0.0
        self._emit("bus_collapse", p.path, KIND_SSCB, detail=why, tripped=tripped)

    # ── Injections (training / bench) ───────────────────────────────
    def utility_loss(self, path: str) -> None:
        self.paths[path].utility_ok = False
        self._emit("utility_lost", path, KIND_RECT)

    def utility_restore(self, path: str) -> None:
        self.paths[path].utility_ok = True
        self._emit("utility_restored", path, KIND_RECT)

    def bus_fault(self, path: str) -> None:
        p = self.paths[path]
        p.bus_fault = True
        if p.sscb == CLOSED:
            p.sscb, p.sscb_trip = TRIPPED, TRIP_BUS_FAULT
        if p.bess_breaker == CLOSED:
            p.bess_breaker, p.bess_trip = TRIPPED, TRIP_BUS_FAULT
        p.bus_v, p.carrying_kw, p.bess_kw, p.rect_out_kw = 0.0, 0.0, 0.0, 0.0
        self._emit(
            "protection_trip",
            path,
            KIND_SSCB,
            relay="SSCB",
            detail="800 VDC bus fault: SSCB and BESS breaker cleared (1-100 us, IEC 60947-2 class)",
        )

    def set_bess_breaker(self, path: str, state: str) -> None:
        self.paths[path].bess_breaker = state
        self._emit("bess_breaker_set", path, KIND_BESS, state=state)

    def set_farm_auto(self, path: str, auto: bool) -> None:
        self.paths[path].farm_auto = bool(auto)
        self._emit("farm_auto_set", path, KIND_FARM, auto=bool(auto))

    def preset(
        self, path: str, now: float, *, out_of_service: bool = False, on_farm: bool = False
    ) -> None:
        """Training set-up of a settled lineup (no transient):
        out_of_service = path isolated for maintenance (input, SSCB and
        BESS breaker open); on_farm = utility lost, farm on load."""
        p = self.paths[path]
        if out_of_service:
            p.input_closed, p.sscb, p.bess_breaker = False, OPEN, OPEN
        if on_farm:
            p.utility_ok, p.source = False, SRC_FARM
            p.farm, p.farm_since = FARM_ON_LOAD, now
        self._settle(now)
        self._emit("preset", path, None, out_of_service=out_of_service, on_farm=on_farm)

    def _settle(self, now: float) -> None:
        cands = [p for p in self.paths.values() if self.rect_feeds_bus(p)]
        share = self.demand_kw(now) / len(cands) if cands else 0.0
        for p in self.paths.values():
            if p in cands:
                p.rect_out_kw, p.bess_kw, p.carrying_kw = share, 0.0, share
                p.bus_v = self.params.nominal_v
            else:
                self._idle(p, 0.0)

    def schedule_load_step(self, now: float, delay_s: float, kw: float, duration_s: float) -> None:
        self.step = LoadStep(
            at=now + max(0.0, delay_s),
            kw=float(kw),
            until=now + max(0.0, delay_s) + max(1.0, duration_s),
        )
        self._emit(
            "load_step_scheduled",
            None,
            None,
            kw=float(kw),
            in_s=float(delay_s),
            duration_s=float(duration_s),
        )

    # ── Commands ────────────────────────────────────────────────────
    def _drops_hall(self, p: DPath) -> bool:
        """True when this path going dark would leave no bus carrying."""
        o = self.other(p)
        return self.energized(p) and not self.energized(o)

    def blocked(self, kind: str, path: str, command: str) -> str | None:
        p = self.paths[path]
        pr = self.params
        if command not in COMMANDS.get(kind, {}):
            return f"Unknown command {command!r} for a {kind}."
        if self.load_lost and command not in (
            "RESET",
            "CLEAR_FAULT",
            "OPEN",
            "OPEN_BREAKER",
            "OPEN_INPUT",
            "STOP",
            "SET_AUTO",
            "SET_MANUAL",
        ):
            # Restoration after a total loss is a reset of the plant here.
            return "Hall load lost: reset the plant (training reset) before restoring."
        if kind == KIND_RECT:
            if command == "OPEN_INPUT":
                if not p.input_closed:
                    return "Input breaker is already open."
                if p.sscb == CLOSED and not self.bess_available(p) and self._drops_hall(p):
                    return (
                        "Supervisory interlock (model): no BESS on this bus and the other path "
                        "is dark; opening would drop the hall."
                    )
                return None
            if command == "CLOSE_INPUT":
                if p.input_closed:
                    return "Input breaker is already closed."
                if p.bus_fault:
                    return "Bus fault present: clear it before re-energising."
                return None
            if command == "TRANSFER_TO_FARM":
                if p.source == SRC_FARM:
                    return "Input is already on the farm."
                if p.farm not in _FARM_LIVE:
                    return f"Farm is {p.farm.lower().replace('_', ' ')}: start it first."
                return None
            if command == "RETRANSFER_TO_UTILITY":
                if p.source == SRC_UTILITY:
                    return "Input is already on the utility."
                if not p.utility_ok:
                    return "No utility voltage on the 35 kV incomer."
                return None
            if command == "UNIT_OUT":
                if self.units_in(p) - 1 < pr.rect_min_units:
                    return (
                        f"{self.units_in(p)} of {pr.rect_units} modules in service: one more out "
                        f"leaves {self.units_in(p) - 1}, below the {pr.rect_min_units} the path "
                        "needs (N+1 per section used)."
                    )
                return None
            if command == "UNIT_IN":
                return None if p.units_out > 0 else "Every module is in service."
        if kind == KIND_SSCB:
            if command == "OPEN":
                if p.sscb != CLOSED:
                    return "SSCB is not closed."
                if not self.bess_available(p) and self._drops_hall(p):
                    return (
                        "Supervisory interlock (model): no BESS on this bus and the other path "
                        "is dark; opening would drop the hall."
                    )
                return None
            if command == "CLOSE":
                if p.sscb == TRIPPED:
                    return "SSCB is tripped: reset it first."
                if p.sscb == CLOSED:
                    return "SSCB is already closed."
                if p.bus_fault:
                    return "Bus fault present."
                return None
            if command == "RESET":
                if p.sscb != TRIPPED:
                    return "SSCB is not tripped."
                if p.bus_fault:
                    return "Bus fault still present: isolate, test and record it cleared first."
                return None
            if command == "CLEAR_FAULT":
                if not p.bus_fault:
                    return "No bus fault recorded."
                if p.sscb == CLOSED or p.bess_breaker == CLOSED:
                    return "Bus not isolated: SSCB and BESS breaker must not be closed."
                if p.input_closed:
                    return "Rectifier input breaker still closed: open it to isolate the bus."
                return None
        if kind == KIND_BESS:
            if command == "OPEN_BREAKER":
                if p.bess_breaker != CLOSED:
                    return "BESS breaker is not closed."
                if not self.rect_feeds_bus(p) and self._drops_hall(p):
                    return (
                        "Supervisory interlock (model): the bus rides on this BESS and the other "
                        "path is dark; opening would drop the hall."
                    )
                return None
            if command == "CLOSE_BREAKER":
                if p.bess_breaker == TRIPPED:
                    return "BESS breaker is tripped: reset it first."
                if p.bess_breaker == CLOSED:
                    return "BESS breaker is already closed."
                if p.bus_fault:
                    return "Bus fault present."
                return None
            if command == "RESET":
                if p.bess_breaker != TRIPPED:
                    return "BESS breaker is not tripped."
                if p.bus_fault:
                    return "Bus fault still present."
                return None
        if kind == KIND_FARM:
            if command == "START":
                return (
                    None
                    if p.farm == FARM_STANDBY
                    else f"Farm is {p.farm.lower().replace('_', ' ')}."
                )
            if command == "STOP":
                if p.farm == FARM_ON_LOAD:
                    return "Farm carries the rectifier input: retransfer to utility first."
                return None if p.farm in (FARM_RUNNING, FARM_CRANKING) else "Farm is not running."
            if command == "SET_AUTO":
                return None if not p.farm_auto else "Auto start is already ON."
            if command == "SET_MANUAL":
                return None if p.farm_auto else "Auto start is already OFF."
        return None

    def operate(self, kind: str, path: str, command: str, now: float) -> dict[str, Any]:
        """Apply a permitted command. The caller checked ``blocked``."""
        p = self.paths[path]
        before = self.state_of(kind, path)
        if kind == KIND_RECT:
            if command == "OPEN_INPUT":
                p.input_closed = False
            elif command == "CLOSE_INPUT":
                p.input_closed = True
                p.rect_out_kw = 0.0  # soft start from zero
            elif command == "TRANSFER_TO_FARM":
                p.source = SRC_FARM
                p.rect_out_kw = 0.0
            elif command == "RETRANSFER_TO_UTILITY":
                p.source = SRC_UTILITY
                p.rect_out_kw = 0.0
            elif command == "UNIT_OUT":
                p.units_out += 1
            elif command == "UNIT_IN":
                p.units_out = max(0, p.units_out - 1)
        elif kind == KIND_SSCB:
            if command == "OPEN":
                p.sscb, p.sscb_trip = OPEN, None
            elif command == "CLOSE":
                p.sscb = CLOSED
            elif command == "RESET":
                p.sscb, p.sscb_trip = OPEN, None
            elif command == "CLEAR_FAULT":
                p.bus_fault = False
        elif kind == KIND_BESS:
            if command == "OPEN_BREAKER":
                p.bess_breaker, p.bess_trip = OPEN, None
            elif command == "CLOSE_BREAKER":
                p.bess_breaker = CLOSED
            elif command == "RESET":
                p.bess_breaker, p.bess_trip = OPEN, None
        elif kind == KIND_FARM:
            if command == "START":
                p.farm, p.farm_since = FARM_CRANKING, now
            elif command == "STOP":
                p.farm, p.farm_since = FARM_COOLDOWN, now
            elif command == "SET_AUTO":
                p.farm_auto = True
            elif command == "SET_MANUAL":
                p.farm_auto = False
        # Re-evaluate the bus at once (a breaker change is instantaneous).
        self._tick(0.0, now)
        return {"from_state": before, "to_state": self.state_of(kind, path)}

    # ── Views ───────────────────────────────────────────────────────
    def state_of(self, kind: str, path: str) -> str:
        p = self.paths[path]
        if kind == KIND_RECT:
            if not p.input_closed:
                return "INPUT_OPEN"
            return p.source if self.input_live(p) else "NO_INPUT"
        if kind == KIND_SSCB:
            return p.sscb
        if kind == KIND_BESS:
            if p.bess_breaker != CLOSED:
                return p.bess_breaker
            if p.bess_kw > 1.0:
                return "DISCHARGING"
            if p.bess_kw < -1.0:
                return "CHARGING"
            return "STANDBY"
        return p.farm

    def status(self, kind: str, path: str) -> dict[str, str]:
        p = self.paths[path]
        if kind == KIND_RECT:
            if not p.input_closed:
                return {"tone": "warn", "text": "Input breaker open"}
            if not self.input_live(p):
                return {"tone": "crit", "text": "No input: utility lost, farm not on bus"}
            if p.source == SRC_FARM:
                return {"tone": "warn", "text": "Input on the generator farm"}
            if p.units_out:
                return {"tone": "info", "text": f"{p.units_out} module(s) out of service"}
            return {"tone": "ok", "text": "Input on utility"}
        if kind == KIND_SSCB:
            if p.sscb == TRIPPED:
                return {
                    "tone": "crit",
                    "text": f"TRIPPED ({(p.sscb_trip or '').replace('_', ' ').lower()})",
                }
            if p.sscb == OPEN:
                return {"tone": "warn", "text": "Open: rectifiers off this bus"}
            if not self.energized(p):
                return {"tone": "crit", "text": "Closed, bus dead"}
            return {"tone": "ok", "text": "Closed, bus energised"}
        if kind == KIND_BESS:
            if p.bess_breaker == TRIPPED:
                return {
                    "tone": "crit",
                    "text": f"Breaker TRIPPED ({(p.bess_trip or '').replace('_', ' ').lower()})",
                }
            if p.bess_breaker == OPEN:
                return {"tone": "warn", "text": "Breaker open: no ride-through on this path"}
            if p.bess_kw > 1.0:
                return {"tone": "warn", "text": f"Discharging, SOC {p.soc * 100:.1f} %"}
            if p.soc < 0.25:
                return {"tone": "warn", "text": f"SOC low {p.soc * 100:.1f} %"}
            return {"tone": "ok", "text": "On the bus, ready"}
        if p.farm == FARM_ON_LOAD:
            return {"tone": "warn", "text": "Carrying the rectifier input"}
        if p.farm == FARM_STANDBY:
            return {
                "tone": "ok" if p.farm_auto else "warn",
                "text": "Standby, auto start ON" if p.farm_auto else "Standby, auto start OFF",
            }
        return {"tone": "info", "text": p.farm.replace("_", " ").capitalize()}

    def readings(self, kind: str, path: str) -> list[dict[str, Any]]:
        p = self.paths[path]
        pr = self.params

        def r(label: str, value: float, unit: str, digits: int) -> dict[str, Any]:
            return {"label": label, "value": round(float(value), digits), "unit": unit}

        if kind == KIND_RECT:
            kv = 0.0
            if p.input_closed and self.input_live(p):
                kv = pr.utility_kv
            return [
                r("Input voltage (3-phase AC)", kv, "kV", 1),
                r("Output to bus", p.rect_out_kw if self.rect_feeds_bus(p) else 0.0, "kW", 0),
                r("Modules in service", self.units_in(p), f"of {pr.rect_units}", 0),
                r("Capacity", self.rect_capacity_kw(p), "kW", 0),
                r("Source ramp limit (model)", self.ramp_kw_s(p), "kW/s", 0),
            ]
        if kind == KIND_SSCB:
            amps = (p.rect_out_kw * 1000 / p.bus_v) if (p.sscb == CLOSED and p.bus_v > 0) else 0.0
            return [
                r("Bus voltage (800 VDC unipolar)", p.bus_v, "V", 0),
                r("Through current (model)", amps, "A", 0),
                r("Path load", p.carrying_kw, "kW", 0),
            ]
        if kind == KIND_BESS:
            amps = p.bess_kw * 1000 / p.bus_v if p.bus_v > 0 else 0.0
            runtime = (p.soc * pr.bess_kwh / p.bess_kw * 60.0) if p.bess_kw > 1.0 else 0.0
            return [
                r("State of charge (model)", p.soc * 100, "%", 1),
                r("Power (+ discharge)", p.bess_kw, "kW", 0),
                r("DC current (+ discharge)", amps, "A", 0),
                r("Runtime at present draw", runtime, "min", 1),
                r("Converter rating", pr.bess_conv_kw, "kW", 0),
            ]
        on_load = p.farm == FARM_ON_LOAD
        return [
            r("Sets", pr.farm_sets, "sets", 0),
            r("Rated", pr.farm_sets * pr.farm_set_kw, "kW", 0),
            r("Output", p.rect_out_kw if on_load else 0.0, "kW", 0),
            r("Bus voltage (13.8 kV, 3-phase AC)", 13.8 if p.farm in _FARM_LIVE else 0.0, "kV", 1),
            r("Start delay (model)", pr.farm_start_s, "s", 0),
        ]

    def summary(self, now: float) -> dict[str, Any]:
        pr = self.params
        out = []
        for p in self.paths.values():
            out.append(
                {
                    "path": p.path,
                    "label": f"D-{p.path.upper()}",
                    "utility_ok": p.utility_ok,
                    "input_closed": p.input_closed,
                    "source": p.source,
                    "input_live": self.input_live(p),
                    "rect_units_in": self.units_in(p),
                    "rect_units": pr.rect_units,
                    "rect_n1_ok": self.units_in(p) > pr.rect_min_units,
                    "rect_capacity_kw": round(self.rect_capacity_kw(p)),
                    "rect_out_kw": round(p.rect_out_kw),
                    "sscb": p.sscb,
                    "sscb_trip": p.sscb_trip,
                    "bus_fault": p.bus_fault,
                    "bus_energized": self.energized(p),
                    "bus_v": round(p.bus_v, 1),
                    "bess_breaker": p.bess_breaker,
                    "bess_trip": p.bess_trip,
                    "soc_pct": round(p.soc * 100, 2),
                    "bess_kw": round(p.bess_kw),
                    "farm": p.farm,
                    "farm_auto": p.farm_auto,
                    "carrying_kw": round(p.carrying_kw),
                }
            )
        step = None
        if self.step is not None:
            step = {
                "kw": self.step.kw,
                "in_s": round(max(0.0, self.step.at - now), 1),
                "active": self.step.at <= now < self.step.until,
                "ends_in_s": round(max(0.0, self.step.until - now), 1),
            }
        return {
            "notice": "Building D is a DESIGN (Phase 2). Simulated plant, MODEL values; "
            "800 VDC unipolar TN-S downstream of the rectifiers.",
            "quality": "simulated",
            "demand_kw": round(self.demand_kw(now)),
            "it_design_kw": round(pr.it_kw),
            "load_lost": self.load_lost,
            "paths_carrying": sum(1 for p in self.paths.values() if p.carrying_kw > 0),
            "load_step": step,
            "paths": out,
        }

    def telemetry_overlay(self) -> dict[str, float]:
        """Values the telemetry simulator should show for Building D
        channels, so live numbers follow the plant."""
        out: dict[str, float] = {}
        pr = self.params
        farm_sets = 0
        farm_kv = 0.0
        for p in self.paths.values():
            s = "" if p.path == "a" else "_b"
            out[f"utility_feed_d{s}:utility_voltage_kv"] = pr.utility_kv if p.utility_ok else 0.0
            out[f"mv_rectifier_d{s}:rect_load_mw"] = (
                p.rect_out_kw / 1000.0 if self.rect_feeds_bus(p) else 0.0
            )
            out[f"main_bus_dc_d{s}:voltage_v_dc_bus"] = p.bus_v
            bess = f"bess_d{s}_01" if s else "bess_d_01"
            out[f"{bess}:bess_soc_pct"] = p.soc * 100.0
            out[f"{bess}:bess_dc_current_a"] = p.bess_kw * 1000.0 / p.bus_v if p.bus_v > 0 else 0.0
            sscb = f"sscb_d{s}_01" if s else "sscb_d_01"
            amps = p.rect_out_kw * 1000.0 / p.bus_v if (p.sscb == CLOSED and p.bus_v > 0) else 0.0
            # MODEL: junction 30 C ambient + 25 K at the 2N design current.
            nominal_a = (pr.it_kw / 2) * 1000.0 / pr.nominal_v
            out[f"{sscb}:sscb_junction_T_c"] = (
                30.0 + 25.0 * (amps / nominal_a) if nominal_a else 30.0
            )
            if p.farm in _FARM_LIVE:
                farm_sets += pr.farm_sets
                farm_kv = 13.8
        out["gen_farm_d:farm_units_online_count"] = float(farm_sets)
        out["gen_farm_d:farm_bus_voltage_kv"] = farm_kv
        return out
