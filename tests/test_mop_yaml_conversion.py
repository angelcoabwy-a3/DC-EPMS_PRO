"""Tests for the 2 MOP MD->YAML conversions (Sprint 5 Decision 4-B closure).

Verifies that T4-MOP-CHI-001.yml and T4-MOP-UPS-001.yml:
  1. Parse as valid YAML.
  2. Conform to the procedure_engine schema (procedure_id, title,
     work_class, procedure_class, default_lor, steps, etc.).
  3. Reference the expected source markdown files.
  4. Use only valid step types (notification, read_verify, write_verify,
     dwell, read_dwell, cmms_finalize).
  5. Include an abort_sequence with at least one entry per the high
     LOR=3 risk profile.
  6. Have all step ids unique within their procedure.
  7. Cite the right standards.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCEDURES_DIR = PROJECT_ROOT / "config" / "procedures"
MOPS_MD_DIR = PROJECT_ROOT / "data" / "corpus" / "tier4_a3semi_mops"

VALID_STEP_TYPES = frozenset({
    "notification",
    "read_verify",
    "write_verify",
    "dwell",
    "read_dwell",
    "cmms_finalize",
})

VALID_FAILURE_ACTIONS = frozenset({"ABORT", "WARN"})

REQUIRED_TOP_KEYS = frozenset({
    "procedure_id",
    "title",
    "work_class",
    "procedure_class",
    "default_lor",
    "estimated_duration_min",
    "applicable_standards",
    "pre_conditions",
    "steps",
})


@pytest.fixture(params=["T4-MOP-CHI-001.yml", "T4-MOP-UPS-001.yml"])
def mop(request):
    path = PROCEDURES_DIR / request.param
    assert path.exists(), f"MOP YAML missing: {path}"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f), request.param


# ─────────────────────────────────────────────────────────────────────
#  Schema conformance
# ─────────────────────────────────────────────────────────────────────
def test_yaml_parses_clean(mop):
    data, name = mop
    assert isinstance(data, dict), f"{name}: top-level not a mapping"


def test_required_top_keys_present(mop):
    data, name = mop
    missing = REQUIRED_TOP_KEYS - set(data.keys())
    assert not missing, f"{name}: missing required keys {missing}"


def test_procedure_id_matches_filename(mop):
    data, name = mop
    expected_id = name.replace(".yml", "")
    assert data["procedure_id"] == expected_id, (
        f"{name}: procedure_id={data['procedure_id']} but filename suggests {expected_id}"
    )


def test_high_risk_lor3_classification(mop):
    """Both MOPs are LOR=3 (high risk: critical infrastructure offline)."""
    data, name = mop
    assert data["default_lor"] == 3, f"{name}: default_lor should be 3, got {data['default_lor']}"


def test_procedure_class_is_mop(mop):
    data, name = mop
    assert data["procedure_class"] == "MOP", (
        f"{name}: procedure_class should be MOP, got {data['procedure_class']}"
    )


# ─────────────────────────────────────────────────────────────────────
#  Pre-conditions
# ─────────────────────────────────────────────────────────────────────
def test_pre_conditions_well_formed(mop):
    data, name = mop
    pre = data["pre_conditions"]
    assert isinstance(pre, list) and len(pre) >= 3, (
        f"{name}: expected >=3 pre_conditions, got {len(pre)}"
    )
    for i, cond in enumerate(pre):
        assert "id" in cond, f"{name}: pre_condition[{i}] missing id"
        assert "description" in cond, f"{name}: pre_condition[{i}] missing description"
        assert "check" in cond, f"{name}: pre_condition[{i}] missing check"
        assert cond.get("failure_action") in VALID_FAILURE_ACTIONS, (
            f"{name}: pre_condition[{i}] invalid failure_action {cond.get('failure_action')}"
        )


# ─────────────────────────────────────────────────────────────────────
#  Steps
# ─────────────────────────────────────────────────────────────────────
def test_steps_well_formed(mop):
    data, name = mop
    steps = data["steps"]
    assert isinstance(steps, list) and len(steps) >= 10, (
        f"{name}: expected >=10 steps, got {len(steps)}"
    )
    for i, step in enumerate(steps):
        assert "id" in step, f"{name}: step[{i}] missing id"
        assert "title" in step, f"{name}: step[{i}] missing title"
        assert "type" in step, f"{name}: step[{i}] missing type"
        assert step["type"] in VALID_STEP_TYPES, (
            f"{name}: step[{i}] id={step.get('id')} invalid type {step['type']}; "
            f"valid: {sorted(VALID_STEP_TYPES)}"
        )


def test_step_ids_unique_within_procedure(mop):
    data, name = mop
    ids = [s["id"] for s in data["steps"]]
    assert len(ids) == len(set(ids)), f"{name}: duplicate step ids: {sorted(ids)}"


def test_at_least_one_witnessed_step(mop):
    """LOR=3 procedures must have at least one requires_witness=true step."""
    data, name = mop
    witnessed = [s for s in data["steps"] if s.get("requires_witness") is True]
    assert len(witnessed) >= 3, (
        f"{name}: LOR=3 should have >=3 witnessed steps, got {len(witnessed)}"
    )


def test_at_least_one_cmms_finalize_step(mop):
    """Every MOP must close with cmms_finalize for procedure tracking."""
    data, name = mop
    finalize = [s for s in data["steps"] if s["type"] == "cmms_finalize"]
    assert len(finalize) >= 1, f"{name}: missing cmms_finalize step"


# ─────────────────────────────────────────────────────────────────────
#  Abort sequence
# ─────────────────────────────────────────────────────────────────────
def test_abort_sequence_present_for_high_risk(mop):
    """LOR=3 procedures must define at least one abort_sequence entry."""
    data, name = mop
    abort_seq = data.get("abort_sequence", [])
    assert isinstance(abort_seq, list) and len(abort_seq) >= 1, (
        f"{name}: high-risk MOP must define abort_sequence with >=1 entry"
    )


# ─────────────────────────────────────────────────────────────────────
#  Source provenance
# ─────────────────────────────────────────────────────────────────────
def test_md_source_exists(mop):
    """Both YAMLs must have a corresponding markdown source for traceability."""
    data, name = mop
    procedure_id = data["procedure_id"]
    md_files = list(MOPS_MD_DIR.glob(f"{procedure_id}_*.md"))
    assert md_files, f"{name}: no markdown source found in {MOPS_MD_DIR} for {procedure_id}"


# ─────────────────────────────────────────────────────────────────────
#  Specific MOP assertions (chiller / UPS)
# ─────────────────────────────────────────────────────────────────────
def test_chiller_mop_cites_ashrae_and_ahri():
    with open(PROCEDURES_DIR / "T4-MOP-CHI-001.yml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    standards = data["applicable_standards"]
    assert any("ASHRAE" in s for s in standards), f"chiller MOP missing ASHRAE: {standards}"
    assert any("AHRI" in s for s in standards), f"chiller MOP missing AHRI: {standards}"


def test_ups_mop_cites_arc_flash_and_battery_standards():
    with open(PROCEDURES_DIR / "T4-MOP-UPS-001.yml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    standards = data["applicable_standards"]
    assert any("70E" in s for s in standards), f"UPS MOP missing NFPA 70E: {standards}"
    assert any("CSA_Z462" in s for s in standards), f"UPS MOP missing CSA Z462: {standards}"
    assert any("IEEE_1188" in s for s in standards), f"UPS MOP missing IEEE 1188: {standards}"
