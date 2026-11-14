"""
backend/site_model_v2.py
========================
DC-EPMS-068 (step 1 and 2 of the operator plan of 2026-11-14): build
``config/site_model_v2.yml`` from two inputs, and validate it.

    config/site_model.yml   legacy model (buildings, cooling, racks,
                            Phase 2 / Building D, micro-components)
    config/power_plant.yml  the CLOSED Phase 1 power design
                            (8 x UPS and 9 x generators per path, MV)

Only the Phase 1 power train of paths A and B is replaced. Everything
else (cooling, racks, Building D, fuel, NOC) is carried over untouched.
The output is GENERATED: edit the two inputs and run
``python scripts/build_site_model_v2.py``. ``--check`` fails when the
committed file is stale, so the two sources of truth cannot drift.

Phase 1 topology per path p (new ids in brackets):

    utility_feed_p (27.5 kV)
      -> [mv_xfmr_p]  27.5 / 13.8 kV utility transformer
      -> [mvtc_p]     MV transfer controller (52-U utility incomer,
                      52-GM generator main; no 480 V ATS)
    genset_p_01..09 (13.8 kV)
      -> [gen_bus_p]  13.8 kV generator paralleling bus
      -> [mvtc_p]
    [mvtc_p] -> [mv_swgr_p] 13.8 kV main switchgear
      -> [unit_sub_p_NN]  13.8 kV / 480 V unit substation, one per UPS
      -> [lv_swbd_p_NN]   480 V UPS input switchboard
      -> [ups_p_NN]       double-conversion UPS block
      -> [ups_out_bus_p]  480 V UPS parallel output bus
      -> rpp_p_01, rpp_p_02 (legacy, unchanged) -> busways -> racks

HONEST SCOPE: unit-substation rating, switchboard rating and the
utility transformer rating are SIZING ASSUMPTIONS derived here (stated
next to each constant), not vendor selections. Building D is not
touched. Runtime consumers still read the legacy model; see the
migration inventory in docs/design/DC-EPMS-068_MIGRATION.md.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Iterable
from typing import Any

PATHS_FROM_DESIGN = "design_basis.paths"

# Legacy Phase 1 power ids replaced by the new train (per path letter).
LEGACY_REPLACED = ("ats_{p}", "xfmr_{p}", "switchgear_{p}", "ups_{p}")
LEGACY_GENSET_PREFIX = "genset_{p}_"

# ── Sizing assumptions (stated, not vendor data) ────────────────────
# Unit substation per UPS block: the block input at full load with
# battery recharge allowance, at 0.9 power factor, rounded up to the
# next standard 500 kVA step. 2500 kW / 0.97 * 1.10 / 0.9 = 3150 kVA
# -> 3500 kVA.
RECHARGE_ALLOWANCE = 1.10
SIZING_PF = 0.9
KVA_STEP = 500
# 480 V switchboard: continuous current of the unit substation
# secondary, next standard frame.
STANDARD_FRAMES_A = (1200, 1600, 2000, 2500, 3000, 4000, 5000, 6000)
LV_VOLTAGE_V = 480
# Utility transformer: full-path design total at 0.9 PF, next 5 MVA.
MVA_STEP_KVA = 5000


def _ceil_step(value: float, step: int) -> int:
    return int(math.ceil(value / step) * step)


def _frame(amps: float) -> int:
    for frame in STANDARD_FRAMES_A:
        if frame >= amps:
            return frame
    return _ceil_step(amps, 1000)


def phase1_ids(path: str, plant: dict[str, Any]) -> dict[str, list[str]]:
    """Canonical ids of the new Phase 1 train of one path."""
    n_ups = int(plant["ups"]["units_per_path"])
    n_gen = int(plant["generators"]["units_per_path"])
    p = path.lower()
    return {
        "mv_xfmr": [f"mv_xfmr_{p}"],
        "mvtc": [f"mvtc_{p}"],
        "gen_bus": [f"gen_bus_{p}"],
        "gensets": [f"genset_{p}_{n:02d}" for n in range(1, n_gen + 1)],
        "mv_swgr": [f"mv_swgr_{p}"],
        "unit_subs": [f"unit_sub_{p}_{n:02d}" for n in range(1, n_ups + 1)],
        "lv_swbds": [f"lv_swbd_{p}_{n:02d}" for n in range(1, n_ups + 1)],
        "ups": [f"ups_{p}_{n:02d}" for n in range(1, n_ups + 1)],
        "ups_out_bus": [f"ups_out_bus_{p}"],
    }


def sizing(plant: dict[str, Any]) -> dict[str, float]:
    ups = plant["ups"]
    eff = float(ups["efficiency"]["double_conversion"])
    unit_kva = _ceil_step(float(ups["rated_kw"]) / eff * RECHARGE_ALLOWANCE / SIZING_PF, KVA_STEP)
    lv_amps = unit_kva * 1000 / (math.sqrt(3) * LV_VOLTAGE_V)
    total_kw = float(plant["design_basis"].get("design_total_load_kw") or 0)
    return {
        "unit_sub_kva": unit_kva,
        "lv_swbd_amps": _frame(lv_amps),
        "lv_secondary_amps": round(lv_amps),
        "mv_xfmr_kva": _ceil_step(total_kw / SIZING_PF, MVA_STEP_KVA) if total_kw else 0,
    }


def build(legacy: dict[str, Any], plant: dict[str, Any]) -> dict[str, Any]:
    """Return the v2 model as a plain dict (no I/O)."""
    model = copy.deepcopy(legacy)
    paths = [p.lower() for p in plant["design_basis"]["paths"]]
    ups, gens = plant["ups"], plant["generators"]
    gen_kv = float(gens["voltage_v"]) / 1000.0
    size = sizing(plant)
    comps: dict[str, Any] = model["components"]

    removed: set[str] = set()
    for p in paths:
        removed.update(tmpl.format(p=p) for tmpl in LEGACY_REPLACED)
        removed.update(
            cid for cid, meta in comps.items()
            if cid.startswith(LEGACY_GENSET_PREFIX.format(p=p))
            and isinstance(meta, dict) and meta.get("type") == "genset"
        )

    # Micro-components of a kept genset survive (genset_a_01 exists in
    # both models); everything parented to a removed id is dropped.
    keep_gensets = {gid for p in paths for gid in phase1_ids(p, plant)["gensets"]}
    removed -= keep_gensets
    for cid in list(comps):
        if cid in removed:
            del comps[cid]
    orphans = {
        cid for cid, meta in comps.items()
        if isinstance(meta, dict) and meta.get("parent") in removed
    }
    for cid in orphans:
        del comps[cid]
    removed |= orphans

    for p in paths:
        ids = phase1_ids(p, plant)
        P = p.upper()
        comps[f"mv_xfmr_{p}"] = {
            "display": f"Utility Transformer {P} (27.5 / {gen_kv:g} kV)",
            "type": "transformer", "path": p,
            "rated_kva": size["mv_xfmr_kva"],
            "voltage_kv_primary": 27.5, "voltage_kv_secondary": gen_kv,
            "sizing": "assumption: design total load at 0.9 PF, next 5 MVA",
        }
        comps[f"mvtc_{p}"] = {
            "display": f"MV Transfer Controller {P} (52-U / 52-GM)",
            "type": "mv_transfer_controller", "path": p,
            "voltage_kv": gen_kv, "transition": "open",
            "breakers": ["52-U", "52-GM"],
        }
        comps[f"gen_bus_{p}"] = {
            "display": f"Generator Paralleling Bus {P} ({gen_kv:g} kV, ANSI 25)",
            "type": "mv_bus", "path": p, "voltage_kv": gen_kv,
        }
        comps[f"mv_swgr_{p}"] = {
            "display": f"MV Main Switchgear {P} ({gen_kv:g} kV)",
            "type": "mv_switchgear", "path": p, "voltage_kv": gen_kv,
        }
        for n, gid in enumerate(ids["gensets"], start=1):
            base = comps.get(gid) if isinstance(comps.get(gid), dict) else {}
            meta = {
                k: v for k, v in base.items()
                # 480 V protection data does not apply to a 13.8 kV set.
                if k not in ("voltage_v", "fault_current_ka", "incident_energy_cal",
                             "arc_flash_boundary_m", "vendor", "model", "rated_kw", "display")
            }
            meta.update({
                "display": f"Generator {P}{n} ({float(gens['rated_kw']) / 1000:g} MW, {gen_kv:g} kV)",
                "type": "genset", "path": p,
                "vendor": str(gens.get("vendor") or "not selected"),
                "model": str(gens.get("model") or "not selected"),
                "rated_kw": float(gens["rated_kw"]), "voltage_kv": gen_kv,
                "bay": {"breaker": "52-G", "disconnector": True, "earthing_switch": True},
            })
            comps[gid] = meta
        for n, (sub, swbd, uid) in enumerate(
            zip(ids["unit_subs"], ids["lv_swbds"], ids["ups"], strict=True), start=1,
        ):
            comps[sub] = {
                "display": f"Unit Substation {P}{n} ({gen_kv:g} kV / 480 V)",
                "type": "transformer", "path": p, "rated_kva": size["unit_sub_kva"],
                "voltage_kv_primary": gen_kv, "voltage_kv_secondary": LV_VOLTAGE_V / 1000,
                "sizing": "assumption: UPS input with 10 percent recharge at 0.9 PF",
            }
            comps[swbd] = {
                "display": f"UPS Input Switchboard {P}{n} (480 V, {size['lv_swbd_amps']} A)",
                "type": "switchgear", "path": p, "voltage_v": LV_VOLTAGE_V,
                "rated_amps": size["lv_swbd_amps"],
            }
            comps[uid] = {
                "display": f"UPS {P}{n} ({ups.get('vendor', '')} {ups.get('model', '')})".replace("  ", " "),
                "type": "ups", "path": p,
                "vendor": str(ups.get("vendor") or ""), "model": str(ups.get("model") or ""),
                "rated_kw": float(ups["rated_kw"]), "voltage_v": LV_VOLTAGE_V,
                "topology": "double_conversion",
                "runtime_full_load_min": float(ups.get("runtime_full_load_min") or 0),
            }
        comps[f"ups_out_bus_{p}"] = {
            "display": f"UPS Parallel Output Bus {P} (480 V)",
            "type": "switchgear", "path": p, "voltage_v": LV_VOLTAGE_V,
            "role": "ups_parallel_output",
        }

    # ── Power chains: drop every edge touching a removed id or the old
    # Phase 1 head (utility -> ats), then add the new train.
    chains = [
        e for e in model["power_chains"]
        if e["from"] not in removed and e["to"] not in removed
    ]
    for p in paths:
        ids = phase1_ids(p, plant)
        chains += [
            {"from": f"utility_feed_{p}", "to": f"mv_xfmr_{p}"},
            {"from": f"mv_xfmr_{p}", "to": f"mvtc_{p}"},
            *({"from": g, "to": f"gen_bus_{p}"} for g in ids["gensets"]),
            {"from": f"gen_bus_{p}", "to": f"mvtc_{p}"},
            {"from": f"mvtc_{p}", "to": f"mv_swgr_{p}"},
        ]
        for sub, swbd, uid in zip(ids["unit_subs"], ids["lv_swbds"], ids["ups"], strict=True):
            chains += [
                {"from": f"mv_swgr_{p}", "to": sub},
                {"from": sub, "to": swbd},
                {"from": swbd, "to": uid},
                {"from": uid, "to": f"ups_out_bus_{p}"},
            ]
        for rpp in sorted(c for c in comps if c.startswith(f"rpp_{p}_")):
            chains.append({"from": f"ups_out_bus_{p}", "to": rpp})
        tank = f"fuel_tank_{p}"
        if tank in comps:
            chains += [{"from": tank, "to": g} for g in ids["gensets"]]
    model["power_chains"] = _dedupe(chains)

    # ── Locations: put every new id in a room; drop removed ids.
    for building in model.get("buildings", []) or []:
        for room in building.get("rooms", []) or []:
            room_comps = [c for c in room.get("components", []) or [] if c not in removed]
            rid = room.get("id", "")
            for p in paths:
                ids = phase1_ids(p, plant)
                if rid == f"er-{p}":
                    room_comps += ids["unit_subs"] + ids["lv_swbds"] + ids["ups"] + ids["ups_out_bus"]
                    room["description"] = (
                        f"Path {p.upper()}: {len(ids['ups'])} UPS blocks with unit substations "
                        "and input switchboards, UPS output bus, RPPs. Walled compartment per Tier IV."
                    )
            if rid == "genset-bay":
                for p in paths:
                    ids = phase1_ids(p, plant)
                    room_comps += ids["gensets"] + ids["gen_bus"]
                room["description"] = (
                    f"{sum(len(phase1_ids(p, plant)['gensets']) for p in paths)} x "
                    f"{float(gens['rated_kw']) / 1000:g} MW generators at {gen_kv:g} kV, paths "
                    + " and ".join(p.upper() for p in paths)
                )
            if rid == "utility-substation":
                for p in paths:
                    ids = phase1_ids(p, plant)
                    room_comps += ids["mv_xfmr"] + ids["mvtc"] + ids["mv_swgr"]
                room["description"] = (
                    "27.5 kV utility intake, utility transformers to 13.8 kV, MV transfer "
                    "controllers and MV main switchgear"
                )
            if "components" in room or room_comps:
                room["components"] = _unique(room_comps)

    meta = model.setdefault("site", {})
    it_kw = float(plant["design_basis"]["it_load_per_path_kw"])
    meta["phase1_it_capacity_mw"] = round(it_kw / 1000, 2)
    meta["model_version"] = 2
    meta["generated_from"] = ["config/site_model.yml", "config/power_plant.yml"]
    return model


def _unique(items: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def _dedupe(edges: list[dict[str, str]]) -> list[dict[str, str]]:
    seen, out = set(), []
    for e in edges:
        key = (e["from"], e["to"])
        if key not in seen:
            seen.add(key)
            out.append({"from": e["from"], "to": e["to"]})
    return out


# ── Validation ──────────────────────────────────────────────────────
def _kv_in(meta: dict[str, Any]) -> float | None:
    for key in ("voltage_kv_primary", "voltage_kv"):
        if meta.get(key) is not None:
            return float(meta[key])
    if meta.get("voltage_v") is not None:
        return float(meta["voltage_v"]) / 1000
    return None


def _kv_out(meta: dict[str, Any]) -> float | None:
    if meta.get("voltage_kv_secondary") is not None:
        return float(meta["voltage_kv_secondary"])
    return _kv_in(meta)


def voltage_mismatches(model: dict[str, Any], node_ids: set[str]) -> list[str]:
    """Edges between AC nodes of ``node_ids`` whose voltages disagree.
    A transformer is compared on its primary at the input and its
    secondary at the output. Nodes without a voltage are skipped."""
    comps = model["components"]
    problems = []
    for e in model["power_chains"]:
        a, b = e["from"], e["to"]
        if a not in node_ids or b not in node_ids:
            continue
        va, vb = _kv_out(comps.get(a) or {}), _kv_in(comps.get(b) or {})
        if va is None or vb is None:
            continue
        if not math.isclose(va, vb, rel_tol=0.01):
            problems.append(f"{a} ({va:g} kV) -> {b} ({vb:g} kV)")
    return problems


def phase1_power_nodes(model: dict[str, Any]) -> set[str]:
    """Every node upstream of a Phase 1 RPP, paths A and B."""
    edges = model["power_chains"]
    parents: dict[str, set[str]] = {}
    for e in edges:
        parents.setdefault(e["to"], set()).add(e["from"])
    stack = [c for c in model["components"] if c.startswith(("rpp_a_", "rpp_b_"))]
    seen = set(stack)
    while stack:
        node = stack.pop()
        for up in parents.get(node, ()):
            if up not in seen and not up.startswith("fuel_tank"):
                seen.add(up)
                stack.append(up)
    return seen


def upstream(model: dict[str, Any], node: str) -> set[str]:
    parents: dict[str, set[str]] = {}
    for e in model["power_chains"]:
        parents.setdefault(e["to"], set()).add(e["from"])
    stack, seen = [node], set()
    while stack:
        for up in parents.get(stack.pop(), ()):
            if up not in seen:
                seen.add(up)
                stack.append(up)
    return seen


def validate(model: dict[str, Any], plant: dict[str, Any]) -> list[str]:
    """Problems with a v2 model; empty means it is consistent with the
    closed design."""
    problems: list[str] = []
    comps = model.get("components") or {}
    for e in model.get("power_chains") or []:
        for end in (e["from"], e["to"]):
            if end not in comps:
                problems.append(f"chain endpoint {end!r} is not a component")
    located = {
        c for b in model.get("buildings") or [] for r in b.get("rooms") or []
        for c in (r.get("components") or [])
    }
    paths = [p.lower() for p in plant["design_basis"]["paths"]]
    for p in paths:
        ids = phase1_ids(p, plant)
        for group, members in ids.items():
            for cid in members:
                if cid not in comps:
                    problems.append(f"path {p.upper()}: {group} {cid} missing")
                elif cid not in located:
                    problems.append(f"{cid} has no room")
        for tmpl in LEGACY_REPLACED:
            if tmpl.format(p=p) in comps:
                problems.append(f"legacy component {tmpl.format(p=p)} still present")
        ups_kw = sum(float(comps[u]["rated_kw"]) for u in ids["ups"] if u in comps)
        if ups_kw != float(plant["ups"]["rated_kw"]) * int(plant["ups"]["units_per_path"]):
            problems.append(f"path {p.upper()}: UPS capacity {ups_kw} kW does not match the design")
        gen_kw = sum(float(comps[g]["rated_kw"]) for g in ids["gensets"] if g in comps)
        floor = float(plant["design_basis"].get("design_total_load_kw") or 0)
        unit = float(plant["generators"]["rated_kw"])
        if gen_kw - unit < floor:
            problems.append(f"path {p.upper()}: generation N+1 {gen_kw - unit} kW below {floor} kW")
        if any(comps.get(g, {}).get("type") == "genset" and float(comps[g].get("voltage_kv") or 0) * 1000
               != float(plant["generators"]["voltage_v"]) for g in ids["gensets"]):
            problems.append(f"path {p.upper()}: a generator is not at the design voltage")
    problems += [f"voltage mismatch: {m}" for m in voltage_mismatches(model, phase1_power_nodes(model))]
    # 2N: every Phase 1 rack must be reachable from both transfer controllers.
    racks = {e["to"] for e in model.get("power_chains") or []
             if e["to"].startswith("rack_") and e["from"].startswith("busway_")}
    for rack in sorted(racks):
        up = upstream(model, rack)
        missing = [f"mvtc_{p}" for p in paths if f"mvtc_{p}" not in up]
        if missing:
            problems.append(f"{rack} is not fed through {', '.join(missing)} (2N broken)")
    return problems


# ── Telemetry mapping v2 (DC-EPMS-068 step 4, DC-EPMS-060) ──────────
# Point lists are SPECIFICATIONS: the telemetry simulator does not
# produce these channels yet. Every path gets the same instrumentation.
# AC voltages follow the vocabulary fence (phase_ab / bc / ca). Command
# points are NOT writable BMS tags: switching goes through
# /api/devices and /api/mv (authority, select-before-operate, ledger).
_AC_PHASE_V = ("V_PHASE_AB", "V_PHASE_BC", "V_PHASE_CA")
POINTS = {
    "ups": [("MODE", "enum"), ("LOAD_KW", "kW"), ("LOAD_PCT", "%"), ("EFFICIENCY", "%"),
            ("LOSSES_KW", "kW"), ("BATTERY_SOC", "%"), ("BATTERY_VDC", "V"),
            ("RUNTIME_MIN", "min"), ("INPUT_BRK_POS", "enum"), ("BYPASS_BRK_POS", "enum"),
            ("OUTPUT_BRK_POS", "enum"), *((v, "V") for v in _AC_PHASE_V)],
    "genset": [("STATE", "enum"), ("RPM", "rpm"), ("FREQ_HZ", "Hz"), ("P_KW", "kW"),
               ("FUEL_LEVEL", "%"), ("STARTER_VDC", "V"), ("CB_52G_POS", "enum"),
               ("DS_POS", "enum"), ("ES_POS", "enum"), ("LOTO", "bool"),
               *((v, "V") for v in _AC_PHASE_V)],
    "mv_transfer_controller": [("SOURCE", "enum"), ("CB_52U_POS", "enum"), ("CB_52GM_POS", "enum"),
                               ("BUS_FREQ_HZ", "Hz"), *((f"BUS_{v}", "V") for v in _AC_PHASE_V)],
    "transformer": [("LOAD_KVA", "kVA"), ("WINDING_TEMP", "degC")],
    "mv_switchgear": [("BUS_FREQ_HZ", "Hz"), *((f"BUS_{v}", "V") for v in _AC_PHASE_V)],
}

# Legacy BMS tag -> v2 tags (the legacy tag names one UPS or one ATS
# that no longer exists as a single device).
LEGACY_TAG_MAP = {
    "PWR.UPS_A.MODE": "PWR.UPS_A01..A08.MODE",
    "PWR.UPS_A.LOAD_KW": "PWR.UPS_A01..A08.LOAD_KW",
    "PWR.UPS_A.EFFICIENCY": "PWR.UPS_A01..A08.EFFICIENCY",
    "PWR.UPS_A.BATTERY_SOC": "PWR.UPS_A01..A08.BATTERY_SOC",
    "PWR.UPS_A.BATTERY_VDC": "PWR.UPS_A01..A08.BATTERY_VDC",
    "PWR.UPS_A.Q1_POS": "PWR.UPS_A01..A08.INPUT_BRK_POS (Galaxy Q-naming retired)",
    "PWR.UPS_A.Q2_POS": "PWR.UPS_A01..A08.OUTPUT_BRK_POS (Galaxy Q-naming retired)",
    "PWR.UPS_A.Q3_POS": "no equivalent: maintenance bypass is modelled per block state",
    "PWR.UPS_A.Q4_POS": "PWR.UPS_A01..A08.OUTPUT_BRK_POS (Galaxy Q-naming retired)",
    "PWR.UPS_A.Q5_POS": "PWR.UPS_A01..A08.BYPASS_BRK_POS (Galaxy Q-naming retired)",
    "PWR.UPS_B.Q1_POS": "PWR.UPS_B01..B08.INPUT_BRK_POS",
    "PWR.UPS_B.Q2_POS": "PWR.UPS_B01..B08.OUTPUT_BRK_POS",
    "PWR.UPS_B.Q3_POS": "no equivalent: maintenance bypass is modelled per block state",
    "PWR.UPS_B.Q4_POS": "PWR.UPS_B01..B08.OUTPUT_BRK_POS",
    "PWR.UPS_B.Q5_POS": "PWR.UPS_B01..B08.BYPASS_BRK_POS",
    "PWR.ATS_A.BREAKER": "PWR.MVTC_A.CB_52U_POS + PWR.MVTC_A.CB_52GM_POS (read-only)",
    "PWR.ATS_B.BREAKER": "PWR.MVTC_B.CB_52U_POS + PWR.MVTC_B.CB_52GM_POS (read-only)",
    "PWR.GEN1.STATUS": "PWR.GENSET_A01.STATE",
    "PWR.GEN1.FUEL_LEVEL": "PWR.GENSET_A01.FUEL_LEVEL",
    "PWR.XFMR_A.WINDING_TEMP": "PWR.MV_XFMR_A.WINDING_TEMP",
    "PWR.XFMR_A.LOAD_KVA": "PWR.MV_XFMR_A.LOAD_KVA",
    "PWR.XFMR_A.OIL_TEMP": "retired (DC-EPMS-061: oil temperature on a dry-type unit)",
}


def _tag_device(cid: str) -> str:
    # ups_a_01 -> UPS_A01, genset_b_09 -> GENSET_B09, mvtc_a -> MVTC_A
    parts = cid.upper().split("_")
    if len(parts) >= 3 and parts[-1].isdigit() and len(parts[-2]) == 1:
        return "_".join(parts[:-2]) + f"_{parts[-2]}{parts[-1]}"
    return cid.upper()


def telemetry_mapping(model: dict[str, Any], plant: dict[str, Any]) -> dict[str, Any]:
    comps = model["components"]
    devices = []
    for p in [x.lower() for x in plant["design_basis"]["paths"]]:
        for members in phase1_ids(p, plant).values():
            for cid in members:
                ctype = comps[cid]["type"]
                if cid.startswith(("lv_swbd_", "ups_out_bus_", "gen_bus_")):
                    continue
                points = POINTS.get(ctype)
                if not points:
                    continue
                devices.append({
                    "component": cid, "path": p, "type": ctype,
                    "points": [{"tag": f"PWR.{_tag_device(cid)}.{name}", "unit": unit, "writable": False}
                               for name, unit in points],
                })
    return {
        "version": 2,
        "status": "specification: the telemetry simulator does not produce these channels yet",
        "write_path": "commands go through /api/devices and /api/mv, never through BMS tag writes",
        "devices": devices,
        "legacy_tag_map": LEGACY_TAG_MAP,
    }
