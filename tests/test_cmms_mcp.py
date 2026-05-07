"""
DC-EPMS PRO v8.1 — cmms_mcp pure-function tests
=================================================

Tests the 6 pure decision functions in cmms_mcp.py without the LLM in
the loop. These functions are the safety-critical core: LOR
computation, procedure class selection, THA generation, contractor
attachment decisions. They MUST be deterministic and auditable — the
tests below codify the contract.

Run:
    pytest tests/test_cmms_mcp.py -v
"""

import pathlib
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from cmms_mcp import (
    DEFAULT_COST_THRESHOLD_USD,
    DEFAULT_LOTO_LOR_THRESHOLD,
    THERMAL_CRITICAL_DT_K_PER_S,
    compute_lor,
    determine_contractor_attachments,
    generate_tha,
    select_procedure_class,
    sla_review_hours_for,
)


# ═══════════════════════════════════════════════════════════════════════
#  compute_lor
# ═══════════════════════════════════════════════════════════════════════
class TestComputeLor:
    """LOR formula: clamp((L*C)/5 + redundancy_modifier, 1, 5)."""

    def test_minimum_risk_in_2n_yields_lor_1(self):
        """L=1, C=1, 2N: raw=0.2, +(-1)=, clamped to 1."""
        lor, breakdown = compute_lor(1, 1, "2N")
        assert lor == 1
        assert breakdown["raw_score"] == 0.2
        assert breakdown["redundancy_modifier"] == -1

    def test_maximum_risk_in_n_yields_lor_5(self):
        """L=5, C=5, N: raw=5.0, +1, clamped to 5."""
        lor, breakdown = compute_lor(5, 5, "N")
        assert lor == 5
        assert breakdown["raw_score"] == 5.0
        assert breakdown["redundancy_modifier"] == 1

    def test_mid_risk_in_2n_reduces(self):
        """L=3, C=3, 2N: raw=1.8, -1=0.8, rounded=1."""
        lor, _ = compute_lor(3, 3, "2N")
        assert lor == 1

    def test_mid_risk_in_n_plus_1_neutral(self):
        """L=3, C=3, N+1: raw=1.8, +0=1.8, rounded=2."""
        lor, breakdown = compute_lor(3, 3, "N+1")
        assert lor == 2
        assert breakdown["redundancy_modifier"] == 0

    def test_mid_risk_in_n_escalates(self):
        """L=3, C=3, N: raw=1.8, +1=2.8, rounded=3."""
        lor, _ = compute_lor(3, 3, "N")
        assert lor == 3

    def test_high_risk_in_2n_does_not_drop_below_1(self):
        """L=4, C=4, 2N: raw=3.2, -1=2.2, rounded=2."""
        lor, _ = compute_lor(4, 4, "2N")
        assert lor == 2

    def test_unknown_redundancy_treated_as_neutral(self):
        """Unknown mode strings get redundancy_modifier 0."""
        lor, breakdown = compute_lor(3, 3, "UNKNOWN")
        assert breakdown["redundancy_modifier"] == 0

    def test_breakdown_includes_rationale_string(self):
        _, breakdown = compute_lor(2, 4, "N+1")
        assert "rationale" in breakdown
        assert "L=2" in breakdown["rationale"]
        assert "C=4" in breakdown["rationale"]
        assert "N+1" in breakdown["rationale"]

    def test_likelihood_below_range_raises(self):
        with pytest.raises(ValueError, match="likelihood_idx"):
            compute_lor(0, 3, "2N")

    def test_likelihood_above_range_raises(self):
        with pytest.raises(ValueError, match="likelihood_idx"):
            compute_lor(6, 3, "2N")

    def test_consequence_below_range_raises(self):
        with pytest.raises(ValueError, match="consequence_idx"):
            compute_lor(3, 0, "2N")

    def test_consequence_above_range_raises(self):
        with pytest.raises(ValueError, match="consequence_idx"):
            compute_lor(3, 6, "2N")


# ═══════════════════════════════════════════════════════════════════════
#  select_procedure_class
# ═══════════════════════════════════════════════════════════════════════
class TestSelectProcedureClass:
    """Decision tree: thermal_critical > LOTO/LOR>=3 > work_class default."""

    # Rule 1: thermal critical wins
    def test_thermal_critical_overrides_pm_to_eop(self):
        """Even a PM with low LOR becomes EOP if thermal derivative critical."""
        result = select_procedure_class(
            work_class="PM",
            lor=1,
            thermal_derivative_k_per_s=THERMAL_CRITICAL_DT_K_PER_S,
            requires_loto=False,
        )
        assert result == "EOP"

    def test_thermal_negative_critical_triggers_eop(self):
        """Negative dT/dt with same magnitude also triggers EOP (abs value)."""
        result = select_procedure_class(
            work_class="PM",
            lor=1,
            thermal_derivative_k_per_s=-THERMAL_CRITICAL_DT_K_PER_S,
            requires_loto=False,
        )
        assert result == "EOP"

    def test_thermal_below_critical_does_not_trigger_eop(self):
        """Sub-critical thermal does not auto-escalate."""
        result = select_procedure_class(
            work_class="PM",
            lor=1,
            thermal_derivative_k_per_s=THERMAL_CRITICAL_DT_K_PER_S - 0.01,
            requires_loto=False,
        )
        assert result == "SOP"

    # Rule 2: LOTO/LOR>=3 forces DMOP
    def test_loto_required_forces_dmop_regardless_of_class(self):
        result = select_procedure_class(
            work_class="PM",
            lor=1,
            thermal_derivative_k_per_s=None,
            requires_loto=True,
        )
        assert result == "DMOP"

    def test_lor_3_forces_dmop_for_pm(self):
        result = select_procedure_class(
            work_class="PM",
            lor=DEFAULT_LOTO_LOR_THRESHOLD,
            thermal_derivative_k_per_s=None,
            requires_loto=False,
        )
        assert result == "DMOP"

    def test_lor_5_forces_dmop_for_cm(self):
        result = select_procedure_class(
            work_class="CM",
            lor=5,
            thermal_derivative_k_per_s=None,
            requires_loto=False,
        )
        assert result == "DMOP"

    # Rules 3-5: work_class defaults
    def test_em_default_is_eop(self):
        result = select_procedure_class(
            work_class="EM",
            lor=1,
            thermal_derivative_k_per_s=None,
            requires_loto=False,
        )
        assert result == "EOP"

    def test_cm_default_is_mop(self):
        result = select_procedure_class(
            work_class="CM",
            lor=2,
            thermal_derivative_k_per_s=None,
            requires_loto=False,
        )
        assert result == "MOP"

    def test_pm_default_is_sop(self):
        result = select_procedure_class(
            work_class="PM",
            lor=1,
            thermal_derivative_k_per_s=None,
            requires_loto=False,
        )
        assert result == "SOP"

    def test_unknown_class_defaults_to_most_restrictive(self):
        """Unknown work_class falls through to DMOP (most restrictive
        non-emergency)."""
        result = select_procedure_class(
            work_class="UNKNOWN",
            lor=1,
            thermal_derivative_k_per_s=None,
            requires_loto=False,
        )
        assert result == "DMOP"

    def test_thermal_none_does_not_break_logic(self):
        """None thermal_derivative is the stub default; should fall through."""
        result = select_procedure_class(
            work_class="PM",
            lor=1,
            thermal_derivative_k_per_s=None,
            requires_loto=False,
        )
        assert result == "SOP"

    # Precedence chain — most restrictive wins even when many apply
    def test_precedence_thermal_beats_loto(self):
        """If both thermal critical AND LOTO required, thermal wins → EOP."""
        result = select_procedure_class(
            work_class="PM",
            lor=4,
            thermal_derivative_k_per_s=1.0,
            requires_loto=True,
        )
        assert result == "EOP"


# ═══════════════════════════════════════════════════════════════════════
#  generate_tha
# ═══════════════════════════════════════════════════════════════════════
class TestGenerateTha:
    """THA must produce structured output with PPE level derived
    deterministically from arc-flash hazards."""

    def test_ups_tha_includes_arc_flash_cat_2(self):
        tha = generate_tha("ups_a", "MOP", 2, "ups")
        assert "arc_flash_cat_2" in tha["hazards"]
        assert tha["ppe_level"] == "category_2"

    def test_xfmr_tha_includes_arc_flash_cat_4(self):
        tha = generate_tha("xfmr_a", "DMOP", 3, "xfmr")
        assert "arc_flash_cat_4" in tha["hazards"]
        assert tha["ppe_level"] == "category_4"

    def test_chiller_tha_no_arc_flash_minimum_ppe(self):
        """Chiller has rotating-equipment hazards but no arc-flash."""
        tha = generate_tha("chiller_1", "SOP", 2, "chiller")
        assert tha["ppe_level"] == "minimum"

    def test_dmop_adds_loto_hazards(self):
        tha = generate_tha("ups_a", "DMOP", 3, "ups")
        assert "loto_isolation_verification_required" in tha["hazards"]
        assert "residual_energy_dissipation_check" in tha["hazards"]

    def test_eop_adds_time_pressure_hazards(self):
        tha = generate_tha("chiller_1", "EOP", 4, "chiller")
        assert "time_pressure_decision_fatigue" in tha["hazards"]
        assert "post_event_review_mandatory" in tha["hazards"]

    def test_two_person_rule_required_for_dmop(self):
        tha = generate_tha("ups_a", "DMOP", 1, "ups")
        assert tha["two_person_rule_required"] is True

    def test_two_person_rule_required_for_eop(self):
        tha = generate_tha("chiller_1", "EOP", 1, "chiller")
        assert tha["two_person_rule_required"] is True

    def test_two_person_rule_required_for_high_lor_even_in_sop(self):
        """LOR >= 3 triggers two-person rule even for SOP."""
        tha = generate_tha("ups_a", "SOP", 3, "ups")
        assert tha["two_person_rule_required"] is True

    def test_two_person_not_required_for_low_risk_sop(self):
        tha = generate_tha("ups_a", "SOP", 1, "ups")
        assert tha["two_person_rule_required"] is False

    def test_unknown_component_kind_falls_back(self):
        tha = generate_tha("widget_42", "SOP", 1, "widget")
        assert "unknown_hazards_review_required" in tha["hazards"]

    def test_standards_always_listed(self):
        tha = generate_tha("ups_a", "SOP", 1, "ups")
        assert "NFPA_70E" in tha["standards"]
        assert "CSA_Z462" in tha["standards"]
        assert "OSHA_1910_269" in tha["standards"]

    def test_provenance_marked_deterministic(self):
        tha = generate_tha("ups_a", "SOP", 1, "ups")
        assert tha["_authoring_method"] == "deterministic_rule_based"


# ═══════════════════════════════════════════════════════════════════════
#  determine_contractor_attachments
# ═══════════════════════════════════════════════════════════════════════
class TestContractorAttachments:
    """Cost or OEM-specialist threshold triggers MSOW + EMPS."""

    def test_low_cost_no_oem_no_contractor_needed(self):
        result = determine_contractor_attachments(
            estimated_cost_usd=500.0,
            requires_oem_specialist=False,
            procedure_class="SOP",
        )
        assert result["contractor_required"] is False

    def test_high_cost_triggers_contractor(self):
        result = determine_contractor_attachments(
            estimated_cost_usd=DEFAULT_COST_THRESHOLD_USD + 1.0,
            requires_oem_specialist=False,
            procedure_class="MOP",
        )
        assert result["contractor_required"] is True
        assert result["msow_attached"] is True
        assert result["emps_attached"] is True

    def test_oem_required_triggers_contractor_even_at_low_cost(self):
        result = determine_contractor_attachments(
            estimated_cost_usd=100.0,
            requires_oem_specialist=True,
            procedure_class="SOP",
        )
        assert result["contractor_required"] is True

    def test_dmop_with_contractor_requires_pre_brief(self):
        result = determine_contractor_attachments(
            estimated_cost_usd=10000.0,
            requires_oem_specialist=False,
            procedure_class="DMOP",
        )
        assert result["pre_brief_required"] is True
        assert result["two_person_oversight"] is True

    def test_eop_with_contractor_requires_two_person(self):
        result = determine_contractor_attachments(
            estimated_cost_usd=10000.0,
            requires_oem_specialist=False,
            procedure_class="EOP",
        )
        assert result["two_person_oversight"] is True

    def test_sop_with_contractor_no_two_person(self):
        result = determine_contractor_attachments(
            estimated_cost_usd=10000.0,
            requires_oem_specialist=False,
            procedure_class="SOP",
        )
        assert result["two_person_oversight"] is False

    def test_mop_with_contractor_requires_pre_brief(self):
        result = determine_contractor_attachments(
            estimated_cost_usd=10000.0,
            requires_oem_specialist=False,
            procedure_class="MOP",
        )
        assert result["pre_brief_required"] is True

    def test_threshold_is_inclusive_at_5000(self):
        """Exactly $5000 should trigger contractor (>=)."""
        result = determine_contractor_attachments(
            estimated_cost_usd=DEFAULT_COST_THRESHOLD_USD,
            requires_oem_specialist=False,
            procedure_class="SOP",
        )
        assert result["contractor_required"] is True


# ═══════════════════════════════════════════════════════════════════════
#  sla_review_hours_for
# ═══════════════════════════════════════════════════════════════════════
class TestSlaReviewHours:
    def test_pm_sla_72_hours(self):
        assert sla_review_hours_for("PM") == 72

    def test_cm_sla_24_hours(self):
        assert sla_review_hours_for("CM") == 24

    def test_em_sla_1_hour(self):
        assert sla_review_hours_for("EM") == 1

    def test_unknown_class_defaults_to_pm(self):
        assert sla_review_hours_for("UNKNOWN") == 72


# ═══════════════════════════════════════════════════════════════════════
#  Integration: end-to-end LOR → procedure → THA chain
# ═══════════════════════════════════════════════════════════════════════
class TestIntegrationChain:
    """Sanity check: the 4 pure decisions compose into a coherent WO."""

    def test_low_risk_pm_in_2n_yields_lightweight_workflow(self):
        """L=1, C=2, 2N, no LOTO, $500 cost → SOP, no contractor, no
        two-person rule, 72h SLA."""
        lor, _ = compute_lor(1, 2, "2N")
        proc = select_procedure_class("PM", lor, None, False)
        tha = generate_tha("ups_a", proc, lor, "ups")
        contr = determine_contractor_attachments(500.0, False, proc)
        sla = sla_review_hours_for("PM")

        assert proc == "SOP"
        assert tha["two_person_rule_required"] is False
        assert contr["contractor_required"] is False
        assert sla == 72

    def test_high_risk_loto_in_n_yields_strict_workflow(self):
        """L=4, C=5, N (degraded), LOTO required, $15k OEM-required →
        DMOP, contractor with MSOW+EMPS, two-person, 24h SLA."""
        lor, _ = compute_lor(4, 5, "N")
        proc = select_procedure_class("CM", lor, None, True)
        tha = generate_tha("xfmr_a", proc, lor, "xfmr")
        contr = determine_contractor_attachments(15000.0, True, proc)
        sla = sla_review_hours_for("CM")

        assert lor == 5
        assert proc == "DMOP"
        assert tha["two_person_rule_required"] is True
        assert tha["ppe_level"] == "category_4"
        assert contr["contractor_required"] is True
        assert contr["msow_attached"] is True
        assert contr["emps_attached"] is True
        assert contr["two_person_oversight"] is True
        assert sla == 24

    def test_thermal_emergency_overrides_pm_into_eop_chain(self):
        """Operator hint says PM, low LOR, low cost — but thermal
        derivative is critical. Procedure escalates to EOP, THA picks
        up time-pressure hazards."""
        lor, _ = compute_lor(2, 2, "2N")
        proc = select_procedure_class("PM", lor, 0.6, False)  # 0.6 K/s > 0.5 critical
        tha = generate_tha("chiller_1", proc, lor, "chiller")

        assert proc == "EOP"
        assert "time_pressure_decision_fatigue" in tha["hazards"]
        assert tha["two_person_rule_required"] is True
