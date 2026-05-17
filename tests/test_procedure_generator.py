"""
tests/test_procedure_generator.py -- Sprint Bite G2 verification.

Asserts the SOP and EMP factories emit valid procedure structures that
conform to the ProcedureClass constraints, and that the EMP factory's
NFPA 70E Arc Flash logic refuses to guess a PPE category when incident
energy data is absent.
"""
from __future__ import annotations

import yaml

from backend.cmms_models import PROCEDURE_CLASSES
from backend.procedure_generator import (
    generate_emp,
    generate_sop,
    ppe_category_for,
    write_procedure_yaml,
)


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
