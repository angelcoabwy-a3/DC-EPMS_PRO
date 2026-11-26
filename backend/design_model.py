"""Building D design model: 800 VDC unipolar TN-S hall sized end to end.

Pure module (no I/O besides reading the YAML inputs, no FastAPI at
import time beyond the route helper). ADR-021.

Inputs live in ``config/design/building_d.yml``. Every derived figure
(currents, unit counts, ratings, flows, capacitor sizes) is computed
here, so the 3D hall, a future 2D plan and the reports read ONE source.

Each value carries a provenance tag:

* ``DESIGN``  an input from the design file or the project documents;
* ``MODEL``   computed by this module from DESIGN values.

LIVE values come from the simulator and are attached by the caller,
never here.

Vocabulary fence (S-VOCAB-01): every element has ``domain`` "ac" or
"dc". AC elements carry ``phases: 3``; DC elements carry
``polarity: "unipolar"`` and never a phase count. "3-phase" appears
only upstream of the MV rectifiers.
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_DEFAULT = Path(__file__).resolve().parent.parent / "config" / "design" / "building_d.yml"


# ── helpers ─────────────────────────────────────────────────────────
def _next_rating(value: float, ratings: list[float]) -> float | None:
    """Smallest standard rating >= value; None if the list is too short."""
    for r in sorted(ratings):
        if r >= value - 1e-9:
            return r
    return None


def _r(x: float, nd: int = 1) -> float:
    return round(float(x), nd)


def _v(value: Any, unit: str, tag: str, note: str = "") -> dict[str, Any]:
    out = {"value": value, "unit": unit, "tag": tag}
    if note:
        out["note"] = note
    return out


def load_inputs(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else _DEFAULT
    with p.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError(f"{p.name}: expected a version 1 design file")
    return data


# ── sizing ──────────────────────────────────────────────────────────
def size(inp: dict[str, Any]) -> dict[str, Any]:
    """Size the Building D chain from the design inputs.

    Returns a dict with ``basis``, ``chain`` (one entry per equipment
    class, per path quantities), ``checks`` and ``totals``.
    """
    it, dc, lay = inp["it"], inp["dc"], inp["layout"]
    red, rules, std = inp["redundancy"], inp["rules"], inp["standard_ratings"]
    k_cont = float(rules["continuous_factor"])
    v_dc = float(dc["nominal_v"])
    paths = list(red["paths"])
    sections = int(red["sections_per_path"])

    racks = int(it["racks"])
    rack_kw = float(it["rack_kw"])
    rows, per_row = int(lay["rows"]), int(lay["racks_per_row"])
    bw_per_row = int(lay["busways_per_row_per_path"])
    it_kw = racks * rack_kw  # one path carries all of it
    row_kw = per_row * rack_kw
    rows_per_section = math.ceil(rows / sections)
    section_kw = rows_per_section * row_kw

    # Rack feed (one path at 100 percent)
    rack_a = rack_kw * 1000 / v_dc
    rack_brk = _next_rating(rack_a / k_cont, std["breaker_a"])

    # Half-row busway: the larger half carries ceil(per_row / n) racks
    bw_racks = math.ceil(per_row / bw_per_row)
    bw_a = bw_racks * rack_a
    bw_rating = _next_rating(bw_a / k_cont, std["breaker_a"])

    # DC bus section
    sec_a = section_kw * 1000 / v_dc
    sec_rating = _next_rating(sec_a / k_cont, std["breaker_a"])

    # MV rectifiers per section, N + r
    rect = inp["rectifier"]
    rect_kw = float(rect["unit_kw"])
    rect_n = math.ceil(section_kw / rect_kw)
    rect_inst = rect_n + int(rect["redundancy_per_section"])
    rect_out_a = rect_kw * 1000 / v_dc
    rect_in_kw = rect_kw / float(rect["efficiency"])
    rect_in_kva = rect_in_kw / float(rect["input_power_factor"])
    util_kv = float(inp["utility"]["voltage_kv"])
    rect_in_a = rect_in_kva / (math.sqrt(3) * util_kv)

    # Capacitor bank per row per path: E = P t = 1/2 C (V1^2 - V2^2)
    cap = inp["capacitor_bank"]
    e_j = row_kw * 1000 * float(cap["holdup_ms"]) / 1000.0
    v2 = float(cap["discharge_to_v"])
    cap_f = 2 * e_j / (v_dc**2 - v2**2)

    # BESS per path
    bess = inp["bess"]
    e_usable_mwh = it_kw / 1000 * float(bess["ride_through_min"]) / 60.0
    e_name_mwh = e_usable_mwh / float(bess["usable_fraction"])
    blocks = math.ceil(e_name_mwh / float(bess["block_mwh"]) - 1e-9)
    conv_n = math.ceil(it_kw / float(bess["converter_kw"]))
    conv_inst = conv_n + int(bess["converter_redundancy"])
    installed_mwh = blocks * float(bess["block_mwh"])
    ride_min_installed = installed_mwh * float(bess["usable_fraction"]) / (it_kw / 1000) * 60

    # Mechanical
    mech = inp["mechanical"]
    mech_kw = it_kw * float(mech["fraction_of_it"])
    mech_kva = mech_kw / float(mech["power_factor"])
    sub_n = math.ceil(mech_kva / float(mech["unit_sub_kva"]))
    sub_inst = sub_n + int(mech["unit_sub_redundancy"])
    crit_kw = it_kw * float(mech["critical_fraction_of_it"])
    cups_n = math.ceil(crit_kw / float(mech["critical_ups_kw"]))
    cups_inst = cups_n + int(mech["critical_ups_redundancy"])

    # Path MV demand: one path carries all IT (through rectifiers) + all mechanical
    rect_path_in_kw = it_kw / float(rect["efficiency"])
    path_kw = rect_path_in_kw + mech_kw
    path_kva = path_kw / float(inp["utility"]["power_factor"])
    util_required_mva = path_kva / 1000 / k_cont
    mv_bus_a_req = path_kva / (math.sqrt(3) * util_kv) / k_cont
    mv_bus_rating = _next_rating(mv_bus_a_req, std["mv_bus_a"])

    # Generators per path, N + r, stepped up to 35 kV
    gen = inp["generators"]
    gen_n = math.ceil(path_kw / float(gen["unit_kw"]))
    gen_inst = gen_n + int(gen["redundancy_per_path"])
    gen_kv = float(gen["voltage_kv"])
    gen_bus_a_req = path_kva / (math.sqrt(3) * gen_kv) / k_cont
    gen_bus_rating = _next_rating(gen_bus_a_req, std["mv_bus_a"])
    stx_mva = _next_rating(path_kva / 1000, std["transformer_mva"])
    stx_inst = 1 + int(inp["stepup_transformer"]["redundancy_per_path"])

    # Cooling: m = Q / (cp dT)
    cool = inp["cooling"]
    dT = float(cool["return_max_c"]) - float(cool["supply_c"])
    cp, rho = float(cool["cp_kj_per_kg_k"]), float(cool["density_kg_per_l"])
    rack_flow = rack_kw / (cp * dT) / rho * 60.0  # L/min
    cdu_n = math.ceil(row_kw / float(cool["cdu_kw"]))
    cdu_inst = cdu_n + int(cool["cdu_redundancy_per_row"])
    p1 = inp["phase1_dlc_check"]
    p1_dT = float(p1["rack_kw"]) / (cp * rho * float(p1["flow_l_min"]) / 60.0)

    P = len(paths)
    chain = [
        {
            "id": "utility_feed",
            "label": "Utility feed (35 kV, 3-phase AC)",
            "domain": "ac",
            "phases": 3,
            "per_path": 1,
            "total": P,
            "required": _v(
                _r(util_required_mva, 1),
                "MVA",
                "MODEL",
                "path demand / power factor / continuous factor",
            ),
            "voltage": _v(util_kv, "kV", "DESIGN"),
        },
        {
            "id": "mv_switchgear",
            "label": "35 kV switchgear (utility / generator transfer)",
            "domain": "ac",
            "phases": 3,
            "per_path": 1,
            "total": P,
            "required": _v(_r(mv_bus_a_req, 0), "A", "MODEL"),
            "rating": _v(mv_bus_rating, "A", "MODEL", "next standard bus rating"),
        },
        {
            "id": "generators",
            "label": "Generator sets (13.8 kV)",
            "domain": "ac",
            "phases": 3,
            "per_path": gen_inst,
            "total": gen_inst * P,
            "redundancy": f"N+{gen['redundancy_per_path']} per path, 2N",
            "unit": _v(float(gen["unit_kw"]), "kW", "DESIGN"),
            "required_units": gen_n,
            "installed_kw": _v(gen_inst * float(gen["unit_kw"]), "kW", "MODEL"),
            "with_one_out_kw": _v((gen_inst - 1) * float(gen["unit_kw"]), "kW", "MODEL"),
        },
        {
            "id": "gen_bus",
            "label": "13.8 kV generator paralleling bus",
            "domain": "ac",
            "phases": 3,
            "per_path": 1,
            "total": P,
            "required": _v(_r(gen_bus_a_req, 0), "A", "MODEL"),
            "rating": _v(gen_bus_rating, "A", "MODEL"),
        },
        {
            "id": "stepup_transformers",
            "label": "Step-up transformers 13.8 / 35 kV",
            "domain": "ac",
            "phases": 3,
            "per_path": stx_inst,
            "total": stx_inst * P,
            "redundancy": "1+1 per path",
            "unit": _v(stx_mva, "MVA", "MODEL", "next standard rating >= path demand"),
        },
        {
            "id": "mv_rectifiers",
            "label": "MV rectifiers (35 kV 3-phase AC in, 800 VDC out)",
            "domain": "ac_to_dc",
            "phases_in": 3,
            "polarity_out": "unipolar",
            "per_path": rect_inst * sections,
            "total": rect_inst * sections * P,
            "per_section": rect_inst,
            "required_per_section": rect_n,
            "redundancy": f"N+{rect['redundancy_per_section']} per section",
            "unit": _v(rect_kw, "kW", "DESIGN"),
            "dc_out_current": _v(_r(rect_out_a, 0), "A", "MODEL"),
            "ac_in_kva": _v(_r(rect_in_kva, 0), "kVA", "MODEL"),
            "ac_in_current": _v(_r(rect_in_a, 1), "A", "MODEL"),
        },
        {
            "id": "dc_bus_sections",
            "label": "800 VDC main bus sections (unipolar TN-S)",
            "domain": "dc",
            "polarity": "unipolar",
            "per_path": sections,
            "total": sections * P,
            "load": _v(section_kw, "kW", "MODEL"),
            "current": _v(_r(sec_a, 0), "A", "MODEL"),
            "rating": _v(sec_rating, "A", "MODEL"),
        },
        {
            "id": "bess",
            "label": "BESS on the 800 VDC bus (DC/DC, bidirectional)",
            "domain": "dc",
            "polarity": "unipolar",
            "per_path": blocks,
            "total": blocks * P,
            "required_usable": _v(_r(e_usable_mwh, 2), "MWh", "MODEL"),
            "required_nameplate": _v(_r(e_name_mwh, 2), "MWh", "MODEL"),
            "installed": _v(installed_mwh, "MWh", "MODEL"),
            "ride_through_installed": _v(_r(ride_min_installed, 1), "min", "MODEL"),
            "converters": conv_inst,
            "converter_unit": _v(float(bess["converter_kw"]), "kW", "DESIGN"),
            "redundancy": f"converters N+{bess['converter_redundancy']} per path",
        },
        {
            "id": "capacitor_banks",
            "label": "Row capacitor banks (load-swing buffer)",
            "domain": "dc",
            "polarity": "unipolar",
            "per_path": rows,
            "total": rows * P,
            "energy": _v(_r(e_j / 1e6, 2), "MJ", "MODEL"),
            "capacitance": _v(
                _r(cap_f, 2), "F", "MODEL", f"1/2 C ({int(v_dc)}^2 - {int(v2)}^2) = P t"
            ),
        },
        {
            "id": "row_busways",
            "label": "Overhead 800 VDC busways (half row)",
            "domain": "dc",
            "polarity": "unipolar",
            "per_path": rows * bw_per_row,
            "total": rows * bw_per_row * P,
            "racks": bw_racks,
            "current": _v(_r(bw_a, 0), "A", "MODEL"),
            "rating": _v(bw_rating, "A", "MODEL"),
        },
        {
            "id": "rack_feeds",
            "label": "Rack 800 VDC feeds (SSCB per feed)",
            "domain": "dc",
            "polarity": "unipolar",
            "per_path": racks,
            "total": racks * P,
            "current": _v(_r(rack_a, 1), "A", "MODEL", "full rack on one path"),
            "normal_current": _v(_r(rack_a * float(red["normal_share"]), 1), "A", "MODEL"),
            "rating": _v(rack_brk, "A", "MODEL"),
        },
        {
            "id": "racks",
            "label": it["rack_model"],
            "domain": "dc",
            "polarity": "unipolar",
            "per_path": racks,
            "total": racks,
            "unit": _v(rack_kw, "kW", "DESIGN"),
        },
        {
            "id": "mech_unit_subs",
            "label": "Mechanical unit substations 35 kV / 480 V",
            "domain": "ac",
            "phases": 3,
            "per_path": sub_inst,
            "total": sub_inst * P,
            "redundancy": f"N+{mech['unit_sub_redundancy']} per path",
            "unit": _v(float(mech["unit_sub_kva"]), "kVA", "DESIGN"),
            "load": _v(_r(mech_kva, 0), "kVA", "MODEL"),
        },
        {
            "id": "critical_mech_ups",
            "label": "Critical mechanical UPS (CDU pumps, controls, 480 V AC)",
            "domain": "ac",
            "phases": 3,
            "per_path": cups_inst,
            "total": cups_inst * P,
            "redundancy": f"N+{mech['critical_ups_redundancy']} per path",
            "unit": _v(float(mech["critical_ups_kw"]), "kW", "DESIGN"),
            "load": _v(_r(crit_kw, 0), "kW", "MODEL"),
        },
        {
            "id": "cdus",
            "label": "CDUs (DLC)",
            "domain": "liquid",
            "per_path": None,
            "total": cdu_inst * rows,
            "per_row": cdu_inst,
            "redundancy": f"N+{cool['cdu_redundancy_per_row']} per row",
            "unit": _v(float(cool["cdu_kw"]), "kW", "DESIGN"),
            "rack_flow": _v(_r(rack_flow, 1), "L/min", "MODEL", f"Q / (cp dT), dT {dT:g} K"),
            "row_flow": _v(_r(rack_flow * per_row, 0), "L/min", "MODEL"),
        },
    ]

    checks = _checks(
        it_kw=it_kw,
        section_kw=section_kw,
        sections=sections,
        rect=(rect_n, rect_inst, rect_kw),
        gen=(gen_n, gen_inst, float(gen["unit_kw"])),
        path_kw=path_kw,
        path_kva=path_kva,
        stx_mva=stx_mva,
        ratings={
            "rack": rack_brk,
            "busway": bw_rating,
            "section": sec_rating,
            "mv_bus": mv_bus_rating,
            "gen_bus": gen_bus_rating,
        },
        conv=(conv_inst, float(bess["converter_kw"])),
        ride=(ride_min_installed, float(bess["ride_through_min"])),
        cdu=(cdu_inst, float(cool["cdu_kw"]), row_kw),
        p1_dT=p1_dT,
        dT=dT,
        v_dc=v_dc,
        dc=dc,
    )

    return {
        "basis": {
            "it_kw": _v(it_kw, "kW", "MODEL", f"{racks} x {rack_kw:g} kW"),
            "row_kw": _v(row_kw, "kW", "MODEL"),
            "section_kw": _v(section_kw, "kW", "MODEL"),
            "mechanical_kw": _v(mech_kw, "kW", "MODEL"),
            "path_demand_kw": _v(
                _r(path_kw, 0), "kW", "MODEL", "IT through rectifiers + all mechanical, one path"
            ),
            "path_demand_kva": _v(_r(path_kva, 0), "kVA", "MODEL"),
            "dc_nominal_v": _v(v_dc, "V", "DESIGN"),
            "topology": red["topology"],
            "continuous_factor": k_cont,
        },
        "chain": chain,
        "checks": checks,
        "totals": {
            "rectifiers": rect_inst * sections * P,
            "generators": gen_inst * P,
            "bess_mwh": installed_mwh * P,
            "busways": rows * bw_per_row * P,
            "cdus": cdu_inst * rows,
        },
    }


def _checks(**k: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def add(cid: str, ok: bool, text: str, warn: bool = False) -> None:
        out.append(
            {"id": cid, "status": "PASS" if ok else ("WARN" if warn else "FAIL"), "detail": text}
        )

    rn, ri, rk = k["rect"]
    sec = k["section_kw"]
    add(
        "D-RECT-N1",
        (ri - 1) * rk >= sec,
        f"rectifiers per section with one out: {(ri - 1) * rk:,.0f} kW >= section load {sec:,.0f} kW",
    )
    gn, gi, gk = k["gen"]
    add(
        "D-GEN-N1",
        (gi - 1) * gk >= k["path_kw"],
        f"generators per path with one out: {(gi - 1) * gk:,.0f} kW >= path demand {k['path_kw']:,.0f} kW",
    )
    add(
        "D-STX",
        k["stx_mva"] is not None and k["stx_mva"] * 1000 >= k["path_kva"],
        f"step-up transformer {k['stx_mva']} MVA >= path demand {k['path_kva'] / 1000:,.1f} MVA (1+1)",
    )
    for name, rating in k["ratings"].items():
        add(
            f"D-RATING-{name.upper()}",
            rating is not None,
            f"{name}: standard rating found"
            if rating
            else f"{name}: above the largest standard rating",
        )
    ci, ck = k["conv"]
    add(
        "D-BESS-CONV",
        (ci - 1) * ck >= k["it_kw"],
        f"BESS converters with one out: {(ci - 1) * ck:,.0f} kW >= IT {k['it_kw']:,.0f} kW",
    )
    have, want = k["ride"]
    add("D-BESS-TIME", have >= want, f"ride-through {have:.1f} min >= target {want:g} min")
    cn, ck2, rkw = k["cdu"]
    add(
        "D-CDU-N1",
        (cn - 1) * ck2 >= rkw,
        f"CDUs per row with one out: {(cn - 1) * ck2:,.0f} kW >= row {rkw:,.0f} kW",
    )
    dc = k["dc"]
    add(
        "D-DC-BAND",
        dc["min_continuous_v"] < k["v_dc"] < dc["overvoltage_limit_v"],
        f"nominal {k['v_dc']:g} V inside {dc['min_continuous_v']}..{dc['overvoltage_limit_v']} V",
    )
    add(
        "P1-DLC-FLOW",
        k["p1_dT"] <= k["dT"] + 1e-9,
        f"Phase 1 README: 142 kW at 40 L/min implies dT {k['p1_dT']:.1f} K; "
        f"18 to 45 C allows {k['dT']:g} K. Flow or temperatures need review (DC-EPMS-075).",
        warn=True,
    )
    return out


# ── layout + racks (coordinates in mm, hall origin at the first rack) ─
def layout(inp: dict[str, Any]) -> dict[str, Any]:
    lay, it, red = inp["layout"], inp["it"], inp["redundancy"]
    v_dc = float(inp["dc"]["nominal_v"])
    rows, per_row = int(lay["rows"]), int(lay["racks_per_row"])
    w, d, h = int(lay["rack_width_mm"]), int(lay["rack_depth_mm"]), int(lay["rack_height_mm"])
    cold, hot = int(lay["cold_aisle_mm"]), int(lay["hot_aisle_mm"])
    sections = int(red["sections_per_path"])
    rows_per_section = math.ceil(rows / sections)
    bw_per_row = int(lay["busways_per_row_per_path"])
    bw_racks = math.ceil(per_row / bw_per_row)
    pair_pitch = 2 * d + hot + cold
    rack_kw = float(it["rack_kw"])
    racks: list[dict[str, Any]] = []
    row_list: list[dict[str, Any]] = []
    for r in range(rows):
        pair, side = divmod(r, 2)
        y = pair * pair_pitch + (0 if side == 0 else d + hot)
        row_id = f"D{r + 1:02d}"
        sec = r // rows_per_section + 1
        busways = []
        for b in range(bw_per_row):
            first, last = b * bw_racks + 1, min((b + 1) * bw_racks, per_row)
            for p in red["paths"]:
                busways.append(
                    {
                        "id": f"BW-{row_id}-{p.upper()}{b + 1}",
                        "path": p,
                        "section": f"{p.upper()}{sec}",
                        "racks": [first, last],
                        "x_mm": [(first - 1) * w, last * w],
                        "z_mm": int(lay["busway_height_mm"]),
                    }
                )
        row_list.append(
            {
                "id": row_id,
                "y_mm": y,
                "facing": "cold-aisle-south" if side == 0 else "cold-aisle-north",
                "section": sec,
                "busways": busways,
            }
        )
        for i in range(per_row):
            n = i + 1
            half = 1 if n <= bw_racks else 2
            racks.append(
                {
                    "id": f"DH1-{row_id}-{n:02d}",
                    "row": row_id,
                    "position": n,
                    "x_mm": i * w,
                    "y_mm": y,
                    "w_mm": w,
                    "d_mm": d,
                    "h_mm": h,
                    "facing": row_list[-1]["facing"],
                    "power_kw": _v(rack_kw, "kW", "DESIGN"),
                    "feeds": [
                        {
                            "path": p,
                            "busway": f"BW-{row_id}-{p.upper()}{half}",
                            "section": f"{p.upper()}{sec}",
                            "voltage": _v(v_dc, "V DC", "DESIGN"),
                            "current_full": _v(_r(rack_kw * 1000 / v_dc, 1), "A", "MODEL"),
                        }
                        for p in red["paths"]
                    ],
                }
            )
    return {
        "hall": inp["hall"],
        "rows": row_list,
        "racks": racks,
        "extent_mm": {"x": per_row * w, "y": (math.ceil(rows / 2)) * pair_pitch - cold},
    }


def rack_detail(inp: dict[str, Any], rack_id: str) -> dict[str, Any] | None:
    lay = layout(inp)
    rack = next((r for r in lay["racks"] if r["id"] == rack_id), None)
    if rack is None:
        return None
    cool = inp["cooling"]
    dT = float(cool["return_max_c"]) - float(cool["supply_c"])
    flow = (
        float(inp["it"]["rack_kw"])
        / (float(cool["cp_kj_per_kg_k"]) * dT)
        / float(cool["density_kg_per_l"])
        * 60
    )
    out = dict(rack)
    out["model"] = inp["it"]["rack_model"]
    out["cooling"] = {
        "supply": _v(float(cool["supply_c"]), "C", "DESIGN"),
        "return_max": _v(float(cool["return_max_c"]), "C", "DESIGN"),
        "flow": _v(_r(flow, 1), "L/min", "MODEL", f"Q / (cp dT), {cool['fluid']}"),
    }
    out["devices"] = {
        "modelled": [
            "800 VDC power entry A",
            "800 VDC power entry B",
            "DLC supply / return manifolds",
        ],
        "not_modelled": "compute and switch trays: vendor data is not in the repository",
    }
    return out


@lru_cache(maxsize=1)
def _cached(path: str) -> dict[str, Any]:
    inp = load_inputs(path)
    return {"inputs": inp, "sizing": size(inp), "layout": layout(inp)}


def get_design(path: str | Path | None = None) -> dict[str, Any]:
    return _cached(str(Path(path) if path else _DEFAULT))


def design_payload(path: str | Path | None = None) -> dict[str, Any]:
    d = get_design(path)
    inp = d["inputs"]
    return {
        "status": "DESIGN (simulated facility, A3-Alpha)",
        "site": inp["site"],
        "building": inp["building"],
        "hall": inp["hall"],
        "dc": {
            "nominal_v": inp["dc"]["nominal_v"],
            "polarity": "unipolar",
            "earthing": inp["dc"]["earthing"],
        },
        **d["sizing"],
        "layout": {k: v for k, v in d["layout"].items() if k != "racks"},
        "rack_count": len(d["layout"]["racks"]),
    }


def register_design_routes(app: Any) -> None:
    """Read-only routes (ADR-006)."""
    from fastapi import HTTPException

    @app.get("/api/design/building-d")
    async def get_building_d() -> dict[str, Any]:
        return design_payload()

    @app.get("/api/design/building-d/racks")
    async def get_building_d_racks() -> dict[str, Any]:
        return {"racks": get_design()["layout"]["racks"]}

    @app.get("/api/design/building-d/racks/{rack_id}")
    async def get_building_d_rack(rack_id: str) -> dict[str, Any]:
        r = rack_detail(get_design()["inputs"], rack_id)
        if r is None:
            raise HTTPException(404, "rack not found")
        return r
