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
