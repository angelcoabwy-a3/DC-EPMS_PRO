"""
backend/procedure_generator.py -- Automated procedure authoring engine.

Sprint Bite G2 of the ProcedureGenerator sprint
(docs/architecture/C0-Procedure-Generator.md). A standalone module that
auto-authors procedure definitions conforming to the schema that
procedure_engine.ProcedureRegistry loads.

This bite ships two of the four C0 pipelines:
  - SOP Factory -- a 5-step preventive checklist built from an asset's
    nominal telemetry channels (resolved from telemetry_simulator).
  - EMP Factory -- an Equipment Maintenance Procedure for a (micro-)
    component, with NFPA 70E / CSA Z462 Arc Flash boundary injection.

The Topological MOP Compiler (G3) and the Kalman EOP Factory (G4) are
deferred per the C0 phasing.

RBAC: every generated procedure is emitted as status DRAFT / version
1.0-draft, tagged with the roles authorised to promote it to ACTIVE
(SENIOR_TECH_L5 or SME_L6). A TECH_L4 may trigger generation; the
DRAFT -> ACTIVE promotion gate itself lands in G4.

HONEST -- incident energy is NEVER computed here. The EMP factory only
consumes an incident_energy_cal value carried on the asset (from an
IEEE 1584 study). When it is missing, the factory emits a DATA_REQUIRED
step with failure_action ABORT -- it does not guess a PPE category from
voltage. Voltage sets shock-approach boundaries, not arc-flash PPE.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from backend.cmms_models import PROCEDURE_CLASSES, UserRole
from backend.site_model import ComponentNotFoundError, get_site_model
from backend.telemetry_simulator import (
    PHASE1_BASELINES,
    REGION_PROFILES,
    _GENERATORS,
)

log = logging.getLogger(__name__)

# ── DRAFT envelope + RBAC ─────────────────────────────────────────────
DRAFT_STATUS = "DRAFT"
DRAFT_VERSION = "1.0-draft"
# RBAC: roles permitted to promote a generated DRAFT to ACTIVE. The gate
# enforcement itself is G4; G2 only tags the draft. A TECH_L4 may trigger
# generation but cannot approve.
APPROVAL_ROLES: list[str] = [UserRole.SENIOR_TECH_L5.value, UserRole.SME_L6.value]


# ── NFPA 70E PPE -- incident energy to AR PPE category ────────────────
# Per NFPA 70E 130.7(C)(15): the selected category's arc rating must be
# at or above the incident energy at the working distance. Bands are
# (ceiling cal/cm2, category int, label).
_PPE_BANDS: list[tuple[float, int, str]] = [
    (1.2,  0, "CAT_0 - no arc-rated PPE required (incident energy at or below 1.2 cal/cm2)"),
    (4.0,  1, "CAT_1 - 4 cal/cm2 arc-rated PPE"),
    (8.0,  2, "CAT_2 - 8 cal/cm2 arc-rated PPE"),
    (25.0, 3, "CAT_3 - 25 cal/cm2 arc-rated PPE"),
    (40.0, 4, "CAT_4 - 40 cal/cm2 arc-rated PPE"),
]


def ppe_category_for(incident_energy_cal: float | None) -> dict[str, Any]:
    """Map incident energy (cal/cm2) to an AR PPE category.

    Returns {known, category, label}. `known` is False when the input is
    None -- the caller MUST then emit a DATA_REQUIRED step rather than
    proceed. A value above CAT_4 (40 cal/cm2) returns category None with
    a PROHIBITED label (energized work not permitted).
    """
    if incident_energy_cal is None:
        return {
            "known": False,
            "category": None,
            "label": "DATA_REQUIRED - asset carries no incident_energy_cal value",
        }
    ie = float(incident_energy_cal)
    for ceiling, category, label in _PPE_BANDS:
        if ie <= ceiling:
            return {"known": True, "category": category, "label": label}
    return {
        "known": True,
        "category": None,
        "label": f"PROHIBITED - {ie:g} cal/cm2 exceeds CAT_4; energized work not permitted",
    }


# ── telemetry channel lookup ──────────────────────────────────────────
def _nominal_channels(asset_type: str) -> list[str]:
    """Nominal telemetry channels for an asset type, per telemetry_simulator.

    Probes the simulator's per-type generator registry. Returns [] for
    types that emit no telemetry (most micro-components -- filters,
    breakers, valves).
    """
    generator = _GENERATORS.get(asset_type)
    if generator is None:
        return []
    try:
        sample = generator(None, 1, np.random.default_rng(0))
        return sorted(sample.keys())
    except Exception as exc:  # defensive: a generator needing a real component
        log.warning("[procedure_generator] channel probe failed for %s: %s",
                    asset_type, exc)
        return []


def _nominal_band(metric: str) -> str:
    """3-sigma nominal band text for a metric, for checklist step copy."""
    if metric in PHASE1_BASELINES:
        mean, std = PHASE1_BASELINES[metric]
        return f"{mean:g} +/- {3 * std:g}"
    for profile in REGION_PROFILES.values():
        if metric in profile:
            mean, std = profile[metric]
            return f"{mean:g} +/- {3 * std:g}"
    return "per calibration"


def _split2(items: list[str]) -> tuple[list[str], list[str]]:
    mid = (len(items) + 1) // 2
    return items[:mid], items[mid:]


def _draft_envelope(
    procedure_id: str,
    title: str,
    procedure_class: str,
    work_class: str,
    default_lor: int,
    applicable_standards: list[str],
) -> dict[str, Any]:
    """Common DRAFT header + RBAC tags shared by every generated procedure."""
    assert procedure_class in PROCEDURE_CLASSES, (
        f"generated procedure_class {procedure_class!r} not in {PROCEDURE_CLASSES}"
    )
    return {
        "procedure_id": procedure_id,
        "title": title,
        "work_class": work_class,
        "procedure_class": procedure_class,
        "status": DRAFT_STATUS,
        "version": DRAFT_VERSION,
        "generated_by": "procedure_generator",
        "requires_approval_role": list(APPROVAL_ROLES),
        "default_lor": default_lor,
        "applicable_standards": list(applicable_standards),
    }


def _verify_step(step_no: int, asset_id: str, title: str,
                 expected: dict[str, Any], abort: bool = False) -> dict[str, Any]:
    return {
        "id": f"step_{step_no:02d}_verify",
        "title": title,
        "type": "read_verify",
        "adapter": "simulated",
        "target": asset_id,
        "expected": expected,
        "timeout_s": 120,
        "requires_witness": False,
        "abort_on_failure": abort,
    }


# ── SOP Factory ───────────────────────────────────────────────────────
def generate_sop(asset_id: str, asset_type: str,
                 display_name: str | None = None) -> dict[str, Any]:
    """Generate a 5-step preventive SOP checklist for an asset.

    Step 1 is a safety gate; steps 2-3 verify the asset's nominal
    telemetry channels within their 3-sigma band (channels resolved from
    telemetry_simulator); step 4 is a visual inspection; step 5 logs to
    CMMS. Emitted as a DRAFT requiring L5/L6 approval.
    """
    display = display_name or asset_id
    pid = f"SOP-AUTO-{asset_id.upper()}-001"
    channels = _nominal_channels(asset_type)
    group_a, group_b = _split2(channels)

    proc = _draft_envelope(
        pid,
        f"Auto-generated SOP - {display} routine inspection",
        "SOP", "ROUNDS", 1,
        ["Uptime_Institute_Operations_Sustainability", "a3semi_OPS"],
    )
    proc["pre_conditions"] = [{
        "id": "operator_on_shift",
        "description": "Certified CET operator on shift",
        "check": "operator_certified == true",
        "failure_action": "WARN",
    }]

    def _channel_step(step_no: int, group: list[str], label: str) -> dict[str, Any]:
        if group:
            expected = {m: _nominal_band(m) for m in group}
            title = (f"Verify {label} telemetry within nominal band: "
                     f"{', '.join(group)}")
        else:
            expected = {}
            title = (f"Verify {label} indicators on {display} "
                     "(no live telemetry channels)")
        return _verify_step(step_no, asset_id, title, expected)

    proc["steps"] = [
        {
            "id": "step_01_safety_gate",
            "title": f"Confirm {display} is safe to inspect - no active alarms or LOTO",
            "type": "read_verify",
            "adapter": "simulated",
            "target": asset_id,
            "expected": {"active_critical_alarms": {"max": 0}},
            "timeout_s": 60,
            "requires_witness": False,
            "abort_on_failure": True,
        },
        _channel_step(2, group_a, "primary"),
        _channel_step(3, group_b, "secondary"),
        _verify_step(4, asset_id,
                     f"Visual inspection of {display} - leaks, corrosion, fastener torque",
                     {}),
        {
            "id": "step_05_finalize",
            "title": "Log inspection completion to CMMS",
            "type": "cmms_finalize",
            "target_procedure": pid,
        },
    ]
    return proc


# ── EMP Factory ───────────────────────────────────────────────────────
def generate_emp(asset_id: str, asset_type: str, *,
                 display_name: str | None = None,
                 asset_level: str | None = None,
                 is_electrical: bool = False,
                 incident_energy_cal: float | None = None) -> dict[str, Any]:
    """Generate an Equipment Maintenance Procedure for a (micro-)component.

    For an electrical component the factory injects a mandatory Arc Flash
    step: when incident_energy_cal is known it specifies the AR PPE
    category and boundary; when it is None it emits a DATA_REQUIRED step
    with failure_action ABORT -- never a voltage-based guess.
    """
    display = display_name or asset_id
    pid = f"EMP-AUTO-{asset_id.upper()}-001"
    proc = _draft_envelope(
        pid,
        f"Auto-generated EMP - {display} localized component maintenance",
        "EMP", "PM", 2,
        ["NFPA_70E_arc_flash", "CSA_Z462_electrical_safety", "a3semi_OPS"],
    )
    proc["pre_conditions"] = []
    proc["asset_level"] = asset_level or "component"

    steps: list[dict[str, Any]] = [{
        "id": "step_01_scope",
        "title": (f"Confirm localized work scope on {display} - "
                  "adjacent equipment stays in service"),
        "type": "read_verify",
        "adapter": "simulated",
        "target": asset_id,
        "expected": {},
        "timeout_s": 60,
        "requires_witness": False,
        "abort_on_failure": True,
    }]

    if is_electrical:
        ppe = ppe_category_for(incident_energy_cal)
        if ppe["known"]:
            steps.append({
                "id": "step_02_arc_flash_boundary",
                "title": ("Verify Arc Flash boundary and don arc-rated PPE - "
                          f"{ppe['label']} (NFPA 70E 130.7)"),
                "type": "read_verify",
                "adapter": "simulated",
                "target": asset_id,
                "expected": {
                    "incident_energy_cal": incident_energy_cal,
                    "ar_ppe_category": ppe["category"],
                },
                "timeout_s": 120,
                "requires_witness": True,
                "abort_on_failure": True,
            })
        else:
            steps.append({
                "id": "step_02_arc_flash_data_required",
                "title": ("ABORT - Arc Flash PPE category cannot be determined: "
                          "this asset carries no incident_energy_cal. An IEEE 1584 "
                          "study value is required. Voltage alone must NOT set the "
                          "PPE category."),
                "type": "read_verify",
                "adapter": "simulated",
                "target": asset_id,
                "expected": {"incident_energy_cal": "DATA_REQUIRED"},
                "timeout_s": 30,
                "requires_witness": True,
                "abort_on_failure": True,
                "failure_action": "ABORT",
            })

    next_no = len(steps) + 1
    steps.append({
        "id": f"step_{next_no:02d}_service",
        "title": (f"Perform localized maintenance on {display} - "
                  "torque and verification per OEM service sheet"),
        "type": "write_verify",
        "adapter": "simulated",
        "target": asset_id,
        "command": "COMPONENT_SERVICE",
        "verify_after": {"component_serviceable": True},
        "timeout_s": 600,
        "requires_witness": False,
        "abort_on_failure": True,
    })
    next_no += 1
    steps.append(_verify_step(
        next_no, asset_id,
        f"Localized verification - confirm {display} restored to service",
        {}, abort=True))
    next_no += 1
    steps.append({
        "id": f"step_{next_no:02d}_finalize",
        "title": "Log EMP completion to CMMS",
        "type": "cmms_finalize",
        "target_procedure": pid,
    })
    proc["steps"] = steps
    return proc


# ══════════════════════════════════════════════════════════════════════
#  G3 -- Topological MOP Compiler + recursive micro-LOTO traversal
# ══════════════════════════════════════════════════════════════════════
# Isolation-device types -- a node is an isolation point if it carries an
# explicit isolation_capable flag OR is one of these inherently-isolating
# component types.
_ISOLATION_TYPES = {"breaker", "sscb", "ats", "valve", "switchgear"}

# Electrical-domain types -- drives zero-energy verification wording
# (voltage vs hydraulic pressure) and the IT-load impact chain.
_ELECTRICAL_TYPES = {
    "ups", "genset", "transformer", "switchgear", "ats", "rpp", "busway",
    "utility_intake", "rectifier", "mv_rectifier", "sscb", "dc_bus", "bess",
    "breaker", "battery",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _is_isolation_capable(comp: Any) -> bool:
    """True for an isolation device -- a node flagged isolation_capable or
    a type that is inherently an isolation point (breaker / valve / ...)."""
    return comp.metadata.get("isolation_capable") is True or comp.type in _ISOLATION_TYPES


def _domain(comp: Any) -> str:
    """'electrical' or 'hydraulic' for a component."""
    return "electrical" if comp.type in _ELECTRICAL_TYPES else "hydraulic"


def _children_index(site: Any) -> dict[str, list[str]]:
    """parent_id -> [child_id, ...] from the ADR-010 containment tree."""
    index: dict[str, list[str]] = {}
    for comp in site.list_components():
        parent = comp.metadata.get("parent")
        if parent:
            index.setdefault(parent, []).append(comp.canonical_id)
    return index


def _parent_chain(site: Any, target_id: str, max_depth: int = 8) -> list[str]:
    """Containment ancestry, nearest first: [target, parent, grandparent, ...]."""
    chain = [target_id]
    node = target_id
    for _ in range(max_depth):
        try:
            comp = site.get_component(node)
        except ComponentNotFoundError:
            break
        parent = comp.metadata.get("parent")
        if not parent or parent in chain:
            break
        chain.append(parent)
        node = parent
    return chain


def _find_isolation_boundary(site: Any, target_id: str) -> dict[str, Any]:
    """Walk the containment tree upward from a (micro-)component to the
    NEAREST isolation-capable nodes.

    ADR-010: the G1 micro-components carry containment edges (parent), not
    flow edges -- so this upstream search runs on the containment tree.
    Returns isolation_points + scope_anchor (the macro-equipment whose IT
    load the guard sweeps) + boundary_found.
    """
    children = _children_index(site)
    chain = _parent_chain(site, target_id)

    for ancestor in chain:  # nearest ancestor first
        found: list[str] = []
        for child_id in children.get(ancestor, []):
            if child_id == target_id:
                continue
            try:
                child = site.get_component(child_id)
            except ComponentNotFoundError:
                continue
            if _is_isolation_capable(child):
                found.append(child_id)
        if found:
            return {"isolation_points": sorted(found),
                    "scope_anchor": ancestor, "boundary_found": True}

    # The target may itself be an isolation device (e.g. a branch breaker).
    try:
        target = site.get_component(target_id)
        if _is_isolation_capable(target):
            anchor = target.metadata.get("parent") or target_id
            return {"isolation_points": [target_id],
                    "scope_anchor": anchor, "boundary_found": True}
    except ComponentNotFoundError:
        pass

    # No local boundary -- fall back to a macro-equipment LOTO.
    macro = chain[-1] if len(chain) > 1 else target_id
    return {"isolation_points": [macro], "scope_anchor": macro,
            "boundary_found": False}


def _it_load_guard(site: Any, scope_anchor: str, domain: str) -> dict[str, Any]:
    """Downstream impact sweep from the scope anchor. Flags any active IT
    load (it_rack nodes) that loses its feed if the anchor's branch is
    isolated -- the IT Load Availability Guard."""
    chain = "cooling" if domain == "hydraulic" else "power"
    affected: list[str] = []
    try:
        impact = site.impact_set(scope_anchor, chain=chain)
        affected = sorted(impact.by_type.get("it_rack", []))
    except Exception as exc:  # defensive -- a node absent from the flow graph
        log.warning("[procedure_generator] IT-load sweep failed for %s: %s",
                    scope_anchor, exc)
    return {"impacted": bool(affected), "affected_racks": affected, "chain": chain}


def _compile_isolation_steps(asset_id: str, display: str, domain: str,
                             iso_points: list[str], target: Any,
                             pid: str) -> list[dict[str, Any]]:
    """Build the 4-group MOP step array: pre-work briefing -> sequential
    isolation -> zero-energy verification -> component work -> restoration
    + post-work QA sign-off."""
    steps: list[dict[str, Any]] = []
    counter = {"n": 0}

    def _sid(name: str) -> str:
        counter["n"] += 1
        return f"step_{counter['n']:02d}_{name}"

    iso_kind = "breaker" if domain == "electrical" else "valve"

    # Group 1 -- vendor pre-work briefing (3-phase supervision init).
    steps.append({
        "id": _sid("pre_work_briefing"),
        "title": (f"Vendor pre-work briefing - confirm scope, MSOW and the "
                  f"supervised isolation plan for {display}"),
        "type": "notification",
        "vendor_stage": "PRE_WORK_BRIEFING_COMPLETED",
        "payload": {"template": "vendor_pre_work_briefing", "target": asset_id},
        "timeout_s": 600,
        "requires_witness": False,
        "abort_on_failure": True,
    })

    # Group 2 -- sequential isolation, one step per boundary device.
    for iso_id in iso_points:
        steps.append({
            "id": _sid("isolate"),
            "title": (f"Open and lock out isolation {iso_kind} {iso_id} "
                      f"to isolate {asset_id}"),
            "type": "write_verify",
            "adapter": "simulated",
            "target": iso_id,
            "command": "OPEN_AND_LOCKOUT",
            "verify_after": {"state": "OPEN_LOCKED"},
            "timeout_s": 300,
            "requires_witness": True,
            "abort_on_failure": True,
        })

    # Group 3 -- zero-energy verification (NFPA 70E / CSA Z462).
    zev: dict[str, Any] = {
        "id": _sid("zero_energy_verify"),
        "type": "read_verify",
        "adapter": "simulated",
        "target": asset_id,
        "timeout_s": 180,
        "requires_witness": True,
        "abort_on_failure": True,
    }
    if domain == "electrical":
        afb = target.metadata.get("arc_flash_boundary_m")
        ie = target.metadata.get("incident_energy_cal")
        boundary_txt = f" Arc Flash boundary: {afb} m." if afb is not None else ""
        zev["title"] = (f"Verify ZERO electrical voltage at {asset_id} with a rated "
                        f"meter per NFPA 70E / CSA Z462.{boundary_txt}")
        zev["expected"] = {"voltage_v": 0}
        if afb is not None:
            zev["arc_flash_boundary_m"] = afb
        if ie is not None:
            zev["expected"]["ar_ppe_category"] = ppe_category_for(ie)["category"]
    else:
        zev["title"] = (f"Verify ZERO hydraulic pressure at {asset_id} - confirm the "
                        "isolated loop segment is drained and depressurized.")
        zev["expected"] = {"loop_pressure_bar": 0}
    steps.append(zev)

    # Localized component work.
    steps.append({
        "id": _sid("component_work"),
        "title": f"Perform localized maintenance on {display} per OEM service sheet",
        "type": "write_verify",
        "adapter": "simulated",
        "target": asset_id,
        "command": "COMPONENT_SERVICE",
        "verify_after": {"component_serviceable": True},
        "timeout_s": 1800,
        "requires_witness": False,
        "abort_on_failure": True,
    })

    # Group 4 -- restoration, reverse isolation order.
    for iso_id in reversed(iso_points):
        steps.append({
            "id": _sid("restore"),
            "title": (f"Remove lockout and restore isolation {iso_kind} {iso_id} "
                      "to service"),
            "type": "write_verify",
            "adapter": "simulated",
            "target": iso_id,
            "command": "RESTORE",
            "verify_after": {"state": "CLOSED_ACTIVE"},
            "timeout_s": 300,
            "requires_witness": True,
            "abort_on_failure": True,
        })

    # Post-work QA sign-off -- the vendor stage that closes the LOTO (L5+).
    steps.append({
        "id": _sid("post_work_qa"),
        "title": (f"Post-work QA sign-off - SENIOR_TECH_L5 or SME_L6 confirms "
                  f"{display} restored to service, then closes the LOTO"),
        "type": "read_verify",
        "adapter": "simulated",
        "target": asset_id,
        "vendor_stage": "POST_WORK_QA_SIGNOFF",
        "expected": {"system_restored": True},
        "timeout_s": 600,
        "requires_witness": True,
        "abort_on_failure": True,
    })
    steps.append({
        "id": _sid("finalize"),
        "title": "Log MOP completion to CMMS",
        "type": "cmms_finalize",
        "target_procedure": pid,
    })
    return steps


def generate_mop(asset_id: str, author_role: UserRole | str,
                 *, site_model: Any = None) -> dict[str, Any]:
    """Topological MOP Compiler (C0 Bite G3).

    Compiles a graph-aware, macro-to-micro isolation MOP for `asset_id`.
    Walks the ADR-010 containment tree upward to the nearest isolation
    boundary (valves / breakers), runs an IT-load availability guard via
    a downstream impact sweep, and emits a 4-group step sequence
    (pre-work briefing -> isolation -> zero-energy verification ->
    restoration + QA sign-off).

    Output is a DRAFT: a TECH_L4 may compile it; SENIOR_TECH_L5 or SME_L6
    must approve. If isolating the boundary would strand an active IT
    rack, a HIGH-severity warning flag is attached.
    """
    site = site_model if site_model is not None else get_site_model(
        project_root=_repo_root())
    role_str = (author_role.value if isinstance(author_role, UserRole)
                else str(author_role))

    try:
        target = site.get_component(asset_id)
    except ComponentNotFoundError as exc:
        raise ValueError(f"unknown asset_id: {asset_id}") from exc

    display = target.display or asset_id
    domain = _domain(target)
    boundary = _find_isolation_boundary(site, asset_id)
    guard = _it_load_guard(site, boundary["scope_anchor"], domain)

    pid = f"MOP-AUTO-{asset_id.upper()}-001"
    proc = _draft_envelope(
        pid,
        f"Auto-compiled MOP - localized isolation of {display}",
        "MOP", "PM", 3,
        ["NFPA_70E_arc_flash", "CSA_Z462_electrical_safety",
         "Uptime_Institute_Operations_Sustainability", "a3semi_OPS"],
    )
    proc["drafted_by_role"] = role_str
    proc["pre_conditions"] = []
    proc["isolation_compile"] = {
        "target": asset_id,
        "isolation_points": boundary["isolation_points"],
        "scope_anchor": boundary["scope_anchor"],
        "boundary_found": boundary["boundary_found"],
        "domain": domain,
    }

    # IT Load Availability Guard -- high-visibility flag if active load hit.
    proc["it_load_impact"] = guard
    if guard["impacted"]:
        proc["severity"] = "HIGH"
        proc["it_load_warning"] = (
            f"WARNING - isolating at {boundary['scope_anchor']} impacts "
            f"{len(guard['affected_racks'])} active IT rack(s): "
            f"{', '.join(guard['affected_racks'])}. Confirm N+1 / 2N redundancy "
            "or a coolant bypass BEFORE execution - risk of thermal trip."
        )
    else:
        proc["severity"] = "NORMAL"

    proc["steps"] = _compile_isolation_steps(
        asset_id, display, domain, boundary["isolation_points"], target, pid)
    return proc


# ══════════════════════════════════════════════════════════════════════
#  G4 -- Kalman-triggered EOP Factory
# ══════════════════════════════════════════════════════════════════════
# Containment playbook keyed by the anomaly-profile string emitted by the
# Kalman pipeline (telemetry_simulator.ANOMALY_PROFILES keys).
_EOP_PLAYBOOK: dict[str, dict[str, Any]] = {
    "gen_desync": {
        "title": "generator bus desynchronization",
        "triage": ("Confirm the generator bus desynchronization alarm cluster "
                   "- phase angle past 5 deg, frequency slip."),
        "containment_title": ("Trip the generator SSCB and hold facility load on "
                              "utility or the redundant path"),
        "containment_command": "TRIP_GENERATOR_BREAKER",
        "monitor": {"genset_phase_angle_deg": {"max": 5},
                    "genset_freq_hz": {"min": 59.5, "max": 60.5}},
    },
    "cdu_flow_starvation": {
        "title": "CDU secondary-loop flow starvation",
        "triage": ("Confirm CDU secondary-loop flow starvation - loop flow below "
                   "the GB200 spec, filter differential pressure rising."),
        "containment_title": ("Engage N+1 standby cooling and assess IT load shed "
                              "against the ASHRAE A2 limit"),
        "containment_command": "ENGAGE_STANDBY_COOLING",
        "monitor": {"cdu_flow_lpm": {"min": 160}, "rack_inlet_T_c": {"max": 32}},
    },
    "thermal_runaway": {
        "title": "IT thermal runaway",
        "triage": "Confirm GPU thermal runaway - gpu_Tj excursion, rack inlet rising.",
        "containment_title": ("Engage standby cooling and apply GPU power capping "
                              "or staged IT load shed"),
        "containment_command": "ENGAGE_STANDBY_COOLING",
        "monitor": {"gpu_Tj_c": {"max": 85}, "rack_inlet_T_c": {"max": 32}},
    },
    "ups_drain": {
        "title": "UPS battery drain",
        "triage": "Confirm UPS state-of-charge drop and runtime collapse.",
        "containment_title": ("Verify generator start and transfer; stage IT load "
                              "shed if runtime stays critical"),
        "containment_command": "VERIFY_GENERATOR_TRANSFER",
        "monitor": {"ups_soc_pct": {"min": 40}, "batt_runtime_min": {"min": 5}},
    },
}

_EOP_DEFAULT_PLAY: dict[str, Any] = {
    "title": "facility anomaly",
    "triage": "Confirm the anomaly alarm cluster and identify the affected sub-system.",
    "containment_title": ("Apply the standing containment action for the affected "
                          "asset and isolate the fault"),
    "containment_command": "CONTAIN_FAULT",
    "monitor": {},
}


def _eop_notification_payload(anomaly_profile: str,
                              affected_asset_id: str) -> dict[str, Any]:
    """Cross-functional alert + resource-coordination routing block.

    Structures the Level V/VI escalation chain: each tier carries a role,
    an alert channel and an SLA. Drives the EOP escalation step.
    """
    return {
        "incident_class": "EOP",
        "anomaly_profile": anomaly_profile,
        "affected_asset": affected_asset_id,
        "escalation_tier": 2,
        "routing": [
            {"role": "SHIFT_LEAD", "channel": "radio+page", "sla_min": 2},
            {"role": UserRole.SENIOR_TECH_L5.value, "channel": "page", "sla_min": 5},
            {"role": UserRole.SME_L6.value, "channel": "page+call", "sla_min": 10},
            {"role": "FACILITY_MANAGER", "channel": "call", "sla_min": 15},
        ],
        "resource_coordination": [
            "on-call OEM vendor", "critical-spares crib", "incident bridge line",
        ],
    }


def generate_eop(anomaly_profile: str, affected_asset_id: str) -> dict[str, Any]:
    """Kalman-triggered EOP Factory (C0 Bite G4).

    Ingests an active anomaly-profile string from the Kalman pipeline
    (telemetry_simulator.ANOMALY_PROFILES keys -- e.g. gen_desync,
    cdu_flow_starvation) and compiles a time-critical Emergency Operating
    Procedure: immediate triage -> algorithmic containment -> cross-
    functional escalation -> monitoring boundary -> recovery.

    Output is a DRAFT requiring SENIOR_TECH_L5 / SME_L6 promotion. EOPs
    use the procedure_engine fast-path graph (no manual ARMED gate).
    """
    play = _EOP_PLAYBOOK.get(anomaly_profile, _EOP_DEFAULT_PLAY)
    pid = f"EOP-AUTO-{anomaly_profile.upper()}-{affected_asset_id.upper()}-001"

    proc = _draft_envelope(
        pid,
        f"Auto-generated EOP - {play['title']} on {affected_asset_id}",
        "EOP", "EMERGENCY", 4,
        ["NFPA_70E_arc_flash", "Uptime_Institute_Operations_Sustainability",
         "a3semi_EOP"],
    )
    proc["pre_conditions"] = []          # EOP fast-path -- no manual approval gate
    proc["anomaly_profile"] = anomaly_profile
    proc["affected_asset"] = affected_asset_id
    proc["severity"] = "CRITICAL"

    notification = _eop_notification_payload(anomaly_profile, affected_asset_id)
    proc["notification_payload"] = notification

    monitor = play["monitor"]
    proc["steps"] = [
        {
            "id": "step_01_alarm_triage",
            "title": play["triage"],
            "type": "read_verify",
            "adapter": "simulated",
            "target": affected_asset_id,
            "expected": {"anomaly_alarm_active": True},
            "timeout_s": 30,
            "requires_witness": False,
            "abort_on_failure": False,
        },
        {
            "id": "step_02_immediate_containment",
            "title": play["containment_title"],
            "type": "write_verify",
            "adapter": "simulated",
            "target": affected_asset_id,
            "command": play["containment_command"],
            "verify_after": {"containment_engaged": True},
            "timeout_s": 60,
            "requires_witness": False,
            "abort_on_failure": False,
        },
        {
            "id": "step_03_escalation_notification",
            "title": ("Escalate - cross-functional alert and resource "
                      "coordination per the routing payload"),
            "type": "notification",
            "payload": notification,
            "timeout_s": 30,
            "requires_witness": False,
            "abort_on_failure": False,
        },
        {
            "id": "step_04_monitoring_boundary",
            "title": (f"Monitor containment within boundaries for "
                      f"{affected_asset_id} - hold until stabilized"),
            "type": "read_dwell",
            "adapter": "simulated",
            "target": affected_asset_id,
            "duration_s": 300,
            "monitor": monitor,
            "abort_on_failure": False,
        },
        {
            "id": "step_05_recovery_verify",
            "title": (f"Verify recovery - {affected_asset_id} stabilized within "
                      "the monitored boundaries"),
            "type": "read_verify",
            "adapter": "simulated",
            "target": affected_asset_id,
            "expected": monitor or {"system_restored": True},
            "timeout_s": 120,
            "requires_witness": False,
            "abort_on_failure": False,
        },
        {
            "id": "step_06_finalize",
            "title": "Log EOP execution to CMMS and the incident record",
            "type": "cmms_finalize",
            "target_procedure": pid,
        },
    ]
    return proc


# ══════════════════════════════════════════════════════════════════════
#  G5 -- API dispatch helper
# ══════════════════════════════════════════════════════════════════════
def compile_procedure(asset_id: str, procedure_class: str, *,
                      anomaly_profile: str | None = None,
                      author_role: UserRole | str = UserRole.TECH_L4,
                      site_model: Any = None) -> dict[str, Any]:
    """Dispatch an HTTP /generate request to the right factory.

    Resolves the asset from the site model and routes to generate_sop /
    generate_mop / generate_eop / generate_emp. Raises ValueError on a
    bad procedure_class, a missing anomaly_profile for an EOP, or an
    unknown asset_id -- the API layer maps ValueError to HTTP 400.
    """
    pclass = str(procedure_class).upper()
    if pclass not in {"SOP", "MOP", "EOP", "EMP"}:
        raise ValueError(f"unsupported procedure_class: {procedure_class!r}")

    if pclass == "EOP":
        if not anomaly_profile:
            raise ValueError("anomaly_profile is required to generate an EOP")
        return generate_eop(anomaly_profile, asset_id)

    site = site_model if site_model is not None else get_site_model(
        project_root=_repo_root())
    try:
        comp = site.get_component(asset_id)
    except ComponentNotFoundError as exc:
        raise ValueError(f"unknown asset_id: {asset_id}") from exc

    if pclass == "SOP":
        return generate_sop(asset_id, comp.type, display_name=comp.display)
    if pclass == "MOP":
        return generate_mop(asset_id, author_role, site_model=site)
    # EMP
    return generate_emp(
        asset_id, comp.type,
        display_name=comp.display,
        asset_level=comp.metadata.get("asset_level"),
        is_electrical=_domain(comp) == "electrical",
        incident_energy_cal=comp.metadata.get("incident_energy_cal"),
    )


# ── YAML emission ─────────────────────────────────────────────────────
def write_procedure_yaml(procedure: dict[str, Any], target_dir: str | Path) -> Path:
    """Write a generated procedure dict to <target_dir>/<procedure_id>.yml.

    Returns the written Path. The caller picks target_dir: production use
    passes config/procedures/, tests pass a tmp directory.
    """
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{procedure['procedure_id']}.yml"
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(procedure, fh, sort_keys=False, allow_unicode=True)
    log.info("[procedure_generator] wrote %s", path)
    return path
