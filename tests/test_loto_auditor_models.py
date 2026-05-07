"""
tests/test_loto_auditor_models.py
==================================
Unit tests for LOTO Auditor Pydantic models (Batch 4.A).

Coverage:
  - Default value sanity
  - Field validation rules
  - LotoAuditRequest field_validator (component_id)
  - LotoAuditReport.aggregate_outcomes() correctness
  - Audit ID format and uniqueness
  - Status enum transitions
  - Edge cases (zero hard fails, all hard fails, mixed)

These tests do NOT exercise pillar logic (deferred to Batch 4.B/C tests).
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from loto_auditor_models import (  # noqa: E402
    AuditStatus,
    CapacitorDischargeCheck,
    ImpactRadius,
    LotoAuditReport,
    LotoAuditRequest,
    LotoLevel,
    PillarOutcome,
    PPECategory,
    PPECategoryCheck,
    RedundancyAssessment,
    SequentialOrderCheck,
    WitnessGateCheck,
)


# =============================================================================
#  LotoAuditRequest tests
# =============================================================================

class TestLotoAuditRequest:
    def test_minimal_request_valid(self):
        req = LotoAuditRequest(
            procedure_id="MOP-ATS-MONTHLY-001",
            target_component_id="ats_a",
            cet_on_duty="wilmer",
        )
        assert req.procedure_id == "MOP-ATS-MONTHLY-001"
        assert req.target_component_id == "ats_a"
        assert req.cet_on_duty == "wilmer"
        assert req.as_of_timestamp is None
        assert req.include_llm_summary is False

    def test_component_id_lowercased_and_stripped(self):
        req = LotoAuditRequest(
            procedure_id="MOP-001",
            target_component_id="  UPS_A  ",
            cet_on_duty="cet01",
        )
        assert req.target_component_id == "ups_a"

    def test_component_id_rejects_whitespace_internal(self):
        with pytest.raises(ValidationError) as exc:
            LotoAuditRequest(
                procedure_id="MOP-001",
                target_component_id="ups a",
                cet_on_duty="cet01",
            )
        assert "whitespace" in str(exc.value).lower()

    def test_component_id_rejects_slashes(self):
        with pytest.raises(ValidationError):
            LotoAuditRequest(
                procedure_id="MOP-001",
                target_component_id="ups/a",
                cet_on_duty="cet01",
            )

    def test_explicit_timestamp_preserved(self):
        ts = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)
        req = LotoAuditRequest(
            procedure_id="MOP-001",
            target_component_id="ats_a",
            cet_on_duty="cet01",
            as_of_timestamp=ts,
        )
        assert req.as_of_timestamp == ts


# =============================================================================
#  Pillar models default value tests
# =============================================================================

class TestPillarDefaults:
    def test_impact_radius_defaults(self):
        ir = ImpactRadius()
        assert ir.affected_components == []
        assert ir.blast_radius_racks == 0
        assert ir.blast_radius_kw == 0.0
        assert ir.outcome == PillarOutcome.PASS
        assert ir.graphrag_consistency_check is True

    def test_redundancy_defaults_pass(self):
        ra = RedundancyAssessment()
        assert ra.shi_pre_loto == 1.0
        assert ra.shi_post_loto == 1.0
        assert ra.shi_threshold == 0.7
        assert ra.outcome == PillarOutcome.PASS
        assert ra.hard_fail_reasons == []

    def test_redundancy_shi_bounds(self):
        with pytest.raises(ValidationError):
            RedundancyAssessment(shi_pre_loto=1.5)
        with pytest.raises(ValidationError):
            RedundancyAssessment(shi_post_loto=-0.1)

    def test_capacitor_check_defaults(self):
        cd = CapacitorDischargeCheck()
        assert cd.required is False
        assert cd.found_in_procedure is False
        assert cd.minimum_required_s == 60
        assert cd.target_threshold_v == 50.0
        assert cd.citation == "NEC 460.6"

    def test_witness_gate_defaults(self):
        wg = WitnessGateCheck()
        assert wg.loto_level == LotoLevel.LEVEL_1_BASIC
        assert wg.witness_required is False
        assert wg.witness_steps == []

    def test_ppe_category_defaults_with_citations(self):
        ppe = PPECategoryCheck()
        assert ppe.computed_category == PPECategory.CAT_0
        assert "NFPA 70E Section 130" in ppe.citations
        assert "CSA Z462-24" in ppe.citations


# =============================================================================
#  LotoAuditReport aggregate logic tests
# =============================================================================

class TestLotoAuditReportAggregation:
    def _build_report(self, overrides=None) -> LotoAuditReport:
        report = LotoAuditReport(
            procedure_id="MOP-ATS-MONTHLY-001",
            target_component_id="ats_a",
            cet_on_duty="wilmer",
            as_of_timestamp=datetime.now(timezone.utc),
            impact_radius=ImpactRadius(),
            redundancy=RedundancyAssessment(),
            capacitor_discharge=CapacitorDischargeCheck(),
            witness_gate=WitnessGateCheck(),
            sequential_order=SequentialOrderCheck(),
            ppe_category=PPECategoryCheck(),
        )
        for path, value in (overrides or {}).items():
            obj = report
            keys = path.split(".")
            for key in keys[:-1]:
                obj = getattr(obj, key)
            setattr(obj, keys[-1], value)
        return report

    def test_audit_id_format(self):
        report = self._build_report()
        # Format: LOTO-AUDIT-YYYYMMDD-HHMMSS-uuidshort
        assert report.audit_id.startswith("LOTO-AUDIT-")
        parts = report.audit_id.split("-")
        # LOTO, AUDIT, YYYYMMDD, HHMMSS, uuidshort
        assert len(parts) == 5
        assert len(parts[2]) == 8  # YYYYMMDD
        assert len(parts[3]) == 6  # HHMMSS
        assert len(parts[4]) == 8  # uuid hex prefix

    def test_audit_ids_unique_across_instances(self):
        ids = {self._build_report().audit_id for _ in range(20)}
        # All 20 should be unique due to uuid suffix
        assert len(ids) == 20

    def test_initial_status_is_pending_approval(self):
        report = self._build_report()
        assert report.status == AuditStatus.PENDING_APPROVAL

    def test_aggregate_all_pass(self):
        report = self._build_report()
        report.aggregate_outcomes()
        assert report.overall_outcome == PillarOutcome.PASS
        assert report.pass_count == 6
        assert report.hard_fail_count == 0
        assert report.warn_count == 0

    def test_aggregate_one_warning_promotes_to_warn(self):
        report = self._build_report({
            "ppe_category.outcome": PillarOutcome.WARN,
        })
        report.aggregate_outcomes()
        assert report.overall_outcome == PillarOutcome.WARN
        assert report.warn_count == 1
        assert report.pass_count == 5

    def test_aggregate_one_hard_fail_promotes_to_hard_fail(self):
        report = self._build_report({
            "redundancy.outcome": PillarOutcome.HARD_FAIL,
        })
        report.aggregate_outcomes()
        assert report.overall_outcome == PillarOutcome.HARD_FAIL
        assert report.hard_fail_count == 1
        assert report.pass_count == 5

    def test_aggregate_hard_fail_dominates_warn(self):
        report = self._build_report({
            "redundancy.outcome": PillarOutcome.HARD_FAIL,
            "ppe_category.outcome": PillarOutcome.WARN,
        })
        report.aggregate_outcomes()
        # Hard fail wins even if warns also present
        assert report.overall_outcome == PillarOutcome.HARD_FAIL
        assert report.hard_fail_count == 1
        assert report.warn_count == 1

    def test_aggregate_not_applicable_counted_separately(self):
        report = self._build_report({
            "capacitor_discharge.outcome": PillarOutcome.NOT_APPLICABLE,
        })
        report.aggregate_outcomes()
        # NOT_APPLICABLE does not trigger HARD_FAIL or WARN promotion
        assert report.overall_outcome == PillarOutcome.PASS
        assert report.not_applicable_count == 1
        assert report.pass_count == 5

    def test_aggregate_all_hard_fail(self):
        outcomes = {
            "impact_radius.outcome": PillarOutcome.HARD_FAIL,
            "redundancy.outcome": PillarOutcome.HARD_FAIL,
            "capacitor_discharge.outcome": PillarOutcome.HARD_FAIL,
            "witness_gate.outcome": PillarOutcome.HARD_FAIL,
            "sequential_order.outcome": PillarOutcome.HARD_FAIL,
            "ppe_category.outcome": PillarOutcome.HARD_FAIL,
        }
        report = self._build_report(outcomes)
        report.aggregate_outcomes()
        assert report.overall_outcome == PillarOutcome.HARD_FAIL
        assert report.hard_fail_count == 6
        assert report.pass_count == 0


# =============================================================================
#  Standards citation defaults
# =============================================================================

class TestStandardsCitations:
    def test_default_standards_include_nfpa_70e(self):
        report = LotoAuditReport(
            procedure_id="MOP-001",
            target_component_id="ups_a",
            cet_on_duty="wilmer",
            as_of_timestamp=datetime.now(timezone.utc),
            impact_radius=ImpactRadius(),
            redundancy=RedundancyAssessment(),
            capacitor_discharge=CapacitorDischargeCheck(),
            witness_gate=WitnessGateCheck(),
            sequential_order=SequentialOrderCheck(),
            ppe_category=PPECategoryCheck(),
        )
        assert "NFPA 70E Section 130" in report.standards_cited
        assert "CSA Z462-24" in report.standards_cited
        assert "Ontario Electrical Safety Code 28th Edition" in report.standards_cited
        assert "NEC 460.6" in report.standards_cited
