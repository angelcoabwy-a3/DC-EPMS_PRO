"""
tests/test_procedure_generator.py -- Sprint Bite G2 verification.

Asserts the SOP and EMP factories emit valid procedure structures that
conform to the ProcedureClass constraints, and that the EMP factory's
NFPA 70E Arc Flash logic refuses to guess a PPE category when incident
energy data is absent.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from backend.cmms_models import PROCEDURE_CLASSES, RBACDenied, UserRole
from backend.procedure_engine import promote_procedure
from backend.procedure_generator import (
    generate_emp,
    generate_eop,
    generate_mop,
    generate_sop,
    ppe_category_for,
    write_procedure_yaml,
)
from backend.site_model import SiteModel

_SITE_YAML = Path(__file__).resolve().parent.parent / "config" / "site_model.yml"


# ── SOP Factory ───────────────────────────────────────────────────────
def test_sop_factory_emits_valid_5_step_draft():
    sop = generate_sop("chiller_1", "chiller", display_name="Chiller 1")
    assert sop["procedure_class"] == "SOP"
    assert sop["procedure_class"] in PROCEDURE_CLASSES
    assert sop["status"] == "DRAFT"
    assert sop["version"] == "1.0-draft"
    assert len(sop["steps"]) == 5
    assert sop["steps"][0]["id"] == "step_01_safety_gate"
    assert sop["steps"][-1]["type"] == "cmms_finalize"


def test_sop_factory_includes_nominal_telemetry_channels():
    sop = generate_sop("chiller_1", "chiller")
    verified_keys: set[str] = set()
    for step in sop["steps"]:
        if step["type"] == "read_verify":
            verified_keys |= set(step.get("expected", {}).keys())
    # chiller nominal channels per telemetry_simulator
    assert "chiller_LWT_c" in verified_keys
    assert "chiller_cop" in verified_keys


def test_sop_factory_rbac_tagged_for_l5_l6_approval():
    sop = generate_sop("ups_a", "ups")
    assert "SENIOR_TECH_L5" in sop["requires_approval_role"]
    assert "SME_L6" in sop["requires_approval_role"]


# ── EMP Factory ───────────────────────────────────────────────────────
def test_emp_factory_injects_arc_flash_step_with_known_incident_energy():
    emp = generate_emp("genset_a_01_24vdc_breaker", "breaker",
                       is_electrical=True, incident_energy_cal=0.3,
                       asset_level="component")
    assert emp["procedure_class"] == "EMP"
    assert emp["procedure_class"] in PROCEDURE_CLASSES
    arc = [s for s in emp["steps"] if "arc_flash" in s["id"]]
    assert len(arc) == 1
    assert arc[0]["id"] == "step_02_arc_flash_boundary"
    assert arc[0]["expected"]["ar_ppe_category"] == 0   # 0.3 cal/cm2 -> CAT_0
    assert arc[0]["requires_witness"] is True


def test_emp_factory_aborts_when_incident_energy_missing():
    emp = generate_emp("switchgear_a", "switchgear",
                       is_electrical=True, incident_energy_cal=None)
    arc = [s for s in emp["steps"] if "arc_flash" in s["id"]]
    assert len(arc) == 1
    assert arc[0]["id"] == "step_02_arc_flash_data_required"
    assert arc[0]["failure_action"] == "ABORT"
    assert arc[0]["abort_on_failure"] is True
    # the factory must NOT have guessed a numeric PPE category
    assert "ar_ppe_category" not in arc[0]["expected"]


def test_emp_factory_non_electrical_has_no_arc_flash_step():
    emp = generate_emp("cdu_a_01_secondary_filter", "filter",
                       is_electrical=False, asset_level="component")
    arc = [s for s in emp["steps"] if "arc_flash" in s["id"]]
    assert arc == []
    assert emp["steps"][-1]["type"] == "cmms_finalize"


# ── PPE mapping ───────────────────────────────────────────────────────
def test_ppe_category_mapping():
    assert ppe_category_for(0.5)["category"] == 0
    assert ppe_category_for(8.0)["category"] == 2
    assert ppe_category_for(25.0)["category"] == 3
    none_res = ppe_category_for(None)
    assert none_res["known"] is False
    assert none_res["category"] is None
    prohibited = ppe_category_for(55.0)
    assert prohibited["category"] is None
    assert "PROHIBITED" in prohibited["label"]


# ── YAML emission ─────────────────────────────────────────────────────
def test_generated_procedure_round_trips_as_yaml(tmp_path):
    sop = generate_sop("ups_a", "ups")
    path = write_procedure_yaml(sop, tmp_path)
    assert path.exists()
    reloaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert reloaded["procedure_id"] == sop["procedure_id"]
    assert reloaded["procedure_class"] in PROCEDURE_CLASSES
    assert len(reloaded["steps"]) == 5


# ── G3: Topological MOP Compiler ──────────────────────────────────────
def test_generate_mop_micro_isolation():
    """G3: targeting the G1 micro-component cdu_a_01_secondary_filter must
    isolate via its local parent valves -- NOT recommend a full CDU
    macro-shutdown."""
    site = SiteModel(_SITE_YAML)
    site.load()
    mop = generate_mop("cdu_a_01_secondary_filter", UserRole.TECH_L4,
                       site_model=site)

    assert mop["procedure_class"] == "MOP"
    assert mop["procedure_class"] in PROCEDURE_CLASSES
    assert mop["status"] == "DRAFT"
    assert mop["drafted_by_role"] == "TECH_L4"

    iso = mop["isolation_compile"]["isolation_points"]
    assert "cdu_a_01_isolation_valve_supply" in iso
    assert "cdu_a_01_isolation_valve_return" in iso
    assert mop["isolation_compile"]["boundary_found"] is True
    # the compiler must NOT have fallen back to a macro shutdown
    assert "cdu_a_01" not in iso

    # the isolation steps lock out the valves, never the macro CDU
    lockout_targets = [s["target"] for s in mop["steps"]
                       if s.get("command") == "OPEN_AND_LOCKOUT"]
    assert set(lockout_targets) == {"cdu_a_01_isolation_valve_supply",
                                    "cdu_a_01_isolation_valve_return"}
    assert "cdu_a_01" not in lockout_targets

    # vendor 3-phase supervision stages bracket the procedure
    vendor_stages = {s.get("vendor_stage") for s in mop["steps"]
                     if s.get("vendor_stage")}
    assert "PRE_WORK_BRIEFING_COMPLETED" in vendor_stages
    assert "POST_WORK_QA_SIGNOFF" in vendor_stages

    # zero-energy verification step present
    zev = [s for s in mop["steps"] if "zero_energy" in s["id"]]
    assert len(zev) == 1

    # IT Load Availability Guard: cdu_a_01 cools active racks -> HIGH severity
    assert mop["severity"] == "HIGH"
    assert mop["it_load_impact"]["impacted"] is True
    assert len(mop["it_load_impact"]["affected_racks"]) > 0


def test_generate_mop_electrical_target_injects_arc_flash_boundary():
    """G3: an electrical micro-component target gets a voltage zero-energy
    step carrying the Arc Flash boundary distance."""
    site = SiteModel(_SITE_YAML)
    site.load()
    mop = generate_mop("genset_a_01_24vdc_breaker", UserRole.SENIOR_TECH_L5,
                       site_model=site)
    assert mop["procedure_class"] == "MOP"
    assert mop["isolation_compile"]["domain"] == "electrical"
    zev = [s for s in mop["steps"] if "zero_energy" in s["id"]]
    assert len(zev) == 1
    assert zev[0]["arc_flash_boundary_m"] == 0.3
    assert "NFPA 70E" in zev[0]["title"]


# ── G4: Kalman EOP Factory ────────────────────────────────────────────
def test_eop_factory_output_shape():
    eop = generate_eop("gen_desync", "genset_a_01")
    assert eop["procedure_class"] == "EOP"
    assert eop["procedure_class"] in PROCEDURE_CLASSES
    assert eop["status"] == "DRAFT"
    assert eop["anomaly_profile"] == "gen_desync"
    assert eop["affected_asset"] == "genset_a_01"
    assert eop["severity"] == "CRITICAL"
    assert len(eop["steps"]) >= 4
    # the immediate-containment step carries the algorithmic action
    commands = [s.get("command") for s in eop["steps"]]
    assert "TRIP_GENERATOR_BREAKER" in commands
    assert eop["steps"][-1]["type"] == "cmms_finalize"


def test_eop_factory_notification_payload_structure():
    eop = generate_eop("cdu_flow_starvation", "cdu_a_01")
    payload = eop["notification_payload"]
    assert payload["anomaly_profile"] == "cdu_flow_starvation"
    assert payload["affected_asset"] == "cdu_a_01"
    assert "escalation_tier" in payload
    assert isinstance(payload["routing"], list) and len(payload["routing"]) >= 2
    for entry in payload["routing"]:
        assert {"role", "channel", "sla_min"} <= set(entry.keys())
    assert isinstance(payload["resource_coordination"], list)
    assert payload["resource_coordination"]


# ── G4: RBAC promotion gate ───────────────────────────────────────────
def test_rbac_promotion_gate_allows_l5_l6():
    draft = generate_sop("ups_a", "ups")
    assert draft["status"] == "DRAFT"
    active = promote_procedure(draft, UserRole.SME_L6)
    assert active["status"] == "ACTIVE"
    assert active["version"] == "1.0"
    assert active["activated_by_role"] == "SME_L6"
    # the input draft must not be mutated
    assert draft["status"] == "DRAFT"
    assert draft["version"] == "1.0-draft"


def test_rbac_promotion_gate_blocks_l4():
    draft = generate_eop("gen_desync", "genset_a_01")
    with pytest.raises(RBACDenied):
        promote_procedure(draft, UserRole.TECH_L4)
    # the draft is untouched after a blocked promotion
    assert draft["status"] == "DRAFT"
