"""
tests/test_loto_auditor_pillars_456.py
========================================
Unit tests for Pillars 4+5+6 implementations (Batch 4.C).

Test scope:
  - Pillar 4 (4 tests): witness gate compliance for LOTO Level 3+
  - Pillar 5 (5 tests): hybrid sequential order (Electrical to Hydraulic to Purge)
  - Pillar 6 (5 tests): PPE category per NFPA 70E section 130

Strategy:
  - Mock site_model with components covering Levels 1-4
  - Mock witness_engine with optional get_protection_status method
  - All tests deterministic, no I/O, no real config files
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from loto_auditor_agent import (  # noqa: E402
    LotoAuditorAgent,
    LotoAuditorError,
    ProcedureSpec,
)
from loto_auditor_models import (  # noqa: E402
    LotoAuditRequest,
    LotoLevel,
    LotoPhase,
    PillarOutcome,
    PPECategory,
)


# =============================================================================
#  Mock fixtures (extended from Batch 4.B with Levels 1-4 components)
# =============================================================================

@dataclass
class MockComponentInfo:
    canonical_id: str
    type: str
    metadata: dict = field(default_factory=dict)
    display: str = ""


@dataclass
class MockImpactSet:
    failed_node: str
    chain_type: str = "power"
    immediate: list = field(default_factory=list)
    transitive: list = field(default_factory=list)
    by_type: dict = field(default_factory=dict)


class MockSiteModel:
    """Site model with components covering all 4 LOTO Levels."""

    def __init__(self):
        self._components = {
            # Level 1 (basic, low voltage)
            "sensor_temp_01": MockComponentInfo(
                canonical_id="sensor_temp_01",
                type="sensor",
                metadata={"voltage_nominal": 24.0},
            ),
            # Level 2 (intermediate, 50-600V)
            "ats_a": MockComponentInfo(
                canonical_id="ats_a",
                type="ats",
                metadata={"voltage_nominal": 480.0, "path": "A"},
            ),
            "rpp_a_1": MockComponentInfo(
                canonical_id="rpp_a_1",
                type="rpp",
                metadata={"voltage_nominal": 480.0, "rated_kw": 200.0, "path": "A"},
            ),
            # Level 3 (cap discharge, UPS or DC link)
            "ups_a": MockComponentInfo(
                canonical_id="ups_a",
                type="ups",
                metadata={
                    "voltage_nominal": 480.0,
                    "rated_kw": 1500.0,
                    "path": "A",
                    "has_dc_link": True,
                },
            ),
            # Level 4 (arc flash, 800V Building D)
            "rectifier_d1": MockComponentInfo(
                canonical_id="rectifier_d1",
                type="rectifier",
                metadata={
                    "voltage_nominal": 800.0,
                    "has_dc_link": True,
                    "path": "A",
                },
            ),
            # Cooling components for Pillar 5 tests
            "chiller_1": MockComponentInfo(
                canonical_id="chiller_1",
                type="chiller",
                metadata={"voltage_nominal": 480.0},
            ),
            "cdu_a_01": MockComponentInfo(
                canonical_id="cdu_a_01",
                type="cdu",
                metadata={"voltage_nominal": 480.0},
            ),
            # MV component for Pillar 6 CAT 4 boundary
            "xfmr_mv": MockComponentInfo(
                canonical_id="xfmr_mv",
                type="transformer",
                metadata={"voltage_nominal": 13800.0},
            ),
        }
        self._impacts = {
            ("ats_a", "power"): MockImpactSet(
                failed_node="ats_a", chain_type="power",
                immediate=["rpp_a_1"], transitive=[],
            ),
            ("ats_a", "cooling"): MockImpactSet(
                failed_node="ats_a", chain_type="cooling",
            ),
            ("ups_a", "power"): MockImpactSet(
                failed_node="ups_a", chain_type="power",
                immediate=["ats_a"], transitive=["rpp_a_1"],
            ),
            ("ups_a", "cooling"): MockImpactSet(
                failed_node="ups_a", chain_type="cooling",
            ),
            ("rectifier_d1", "power"): MockImpactSet(
                failed_node="rectifier_d1", chain_type="power",
            ),
            ("rectifier_d1", "cooling"): MockImpactSet(
                failed_node="rectifier_d1", chain_type="cooling",
            ),
            ("chiller_1", "power"): MockImpactSet(
                failed_node="chiller_1", chain_type="power",
            ),
            ("chiller_1", "cooling"): MockImpactSet(
                failed_node="chiller_1", chain_type="cooling",
                immediate=["cdu_a_01"],
            ),
            ("cdu_a_01", "power"): MockImpactSet(
                failed_node="cdu_a_01", chain_type="power",
            ),
            ("cdu_a_01", "cooling"): MockImpactSet(
                failed_node="cdu_a_01", chain_type="cooling",
            ),
            ("sensor_temp_01", "power"): MockImpactSet(
                failed_node="sensor_temp_01", chain_type="power",
            ),
            ("sensor_temp_01", "cooling"): MockImpactSet(
                failed_node="sensor_temp_01", chain_type="cooling",
            ),
            ("xfmr_mv", "power"): MockImpactSet(
                failed_node="xfmr_mv", chain_type="power",
            ),
            ("xfmr_mv", "cooling"): MockImpactSet(
                failed_node="xfmr_mv", chain_type="cooling",
            ),
            ("rpp_a_1", "power"): MockImpactSet(
                failed_node="rpp_a_1", chain_type="power",
            ),
            ("rpp_a_1", "cooling"): MockImpactSet(
                failed_node="rpp_a_1", chain_type="cooling",
            ),
        }

    def get_component(self, canonical_id):
        if canonical_id not in self._components:
            raise KeyError(f"Component '{canonical_id}' not found")
        return self._components[canonical_id]

    def power_chain_for(self, canonical_id):
        return self._impacts.get(
            (canonical_id, "power"),
            MockImpactSet(failed_node=canonical_id, chain_type="power"),
        )

    def cooling_chain_for(self, canonical_id):
        return self._impacts.get(
            (canonical_id, "cooling"),
            MockImpactSet(failed_node=canonical_id, chain_type="cooling"),
        )


class MockGraphRAG:
    def query_topology(self, component_id):
        return {"affected_components": []}

    def query(self, query_text):
        return []


class MockPhysicsEngine:
    def validate_site(self, measurements):
        return {"site_health_index": 0.85}


class MockWitnessEngineWithProtection:
    """Witness engine with explicit identity collision protection method."""

    def get_protection_status(self):
        return {"identity_collision_protected": True}


class MockWitnessEngineNoProtection:
    """Witness engine without protection methods (Pillar 4 will WARN)."""
    pass


# =============================================================================
#  Test helpers
# =============================================================================

def make_agent(
    site_model: Optional[Any] = None,
    graphrag: Optional[Any] = None,
    physics: Optional[Any] = None,
    witness: Optional[Any] = None,
) -> LotoAuditorAgent:
    return LotoAuditorAgent(
        site_model=site_model or MockSiteModel(),
        graphrag_service=graphrag or MockGraphRAG(),
        physics_engine=physics or MockPhysicsEngine(),
        witness_engine=witness or MockWitnessEngineWithProtection(),
    )


def make_request(target: str, procedure: str = "MOP-TEST") -> LotoAuditRequest:
    return LotoAuditRequest(
        procedure_id=procedure,
        target_component_id=target,
        cet_on_duty="wilmer",
    )


def make_procedure(
    steps: Optional[list[dict]] = None,
    metadata: Optional[dict] = None,
    procedure_id: str = "MOP-TEST",
) -> ProcedureSpec:
    raw = {"steps": steps or []}
    if metadata:
        raw["metadata"] = metadata
    return ProcedureSpec(procedure_id, raw)


# =============================================================================
#  Pillar 4 tests (4)
# =============================================================================

class TestPillar4WitnessGate:
    """Pillar 4: witness gate compliance for LOTO Level 3+."""

    def test_pillar4_level1_low_voltage_no_witness_required(self):
        """Sensor at 24V is Level 1, no witness required, PASS."""
        agent = make_agent()
        request = make_request(target="sensor_temp_01")
        procedure = make_procedure(steps=[
            {"description": "Disconnect sensor lead"},
        ])

        result = agent._check_pillar_4_witness_gate(request, procedure, {})

        assert result.outcome == PillarOutcome.PASS
        assert result.loto_level == LotoLevel.LEVEL_1_BASIC
        assert result.witness_required is False
        assert result.witness_steps == []

    def test_pillar4_level3_ups_witness_missing_hard_fail(self):
        """UPS is Level 3 (cap discharge), no witness in procedure -> HARD_FAIL."""
        agent = make_agent()
        request = make_request(target="ups_a")
        procedure = make_procedure(steps=[
            {"description": "Open breaker"},
            {"description": "Wait 90s for capacitor discharge"},
        ])

        result = agent._check_pillar_4_witness_gate(request, procedure, {})

        assert result.loto_level == LotoLevel.LEVEL_3_CAP_DISCHARGE
        assert result.witness_required is True
        assert result.witness_steps == []
        assert result.outcome == PillarOutcome.HARD_FAIL

    def test_pillar4_level4_800vdc_witness_present_passes(self):
        """800VDC is Level 4 (arc flash), procedure has witness step -> PASS."""
        agent = make_agent()
        request = make_request(target="rectifier_d1")
        procedure = make_procedure(steps=[
            {
                "id": "step_open_dc_breaker",
                "description": "Open 800VDC main breaker",
                "requires_witness": True,
            },
            {"description": "Wait 120s for capacitor discharge"},
            {"description": "Verify zero voltage with CAT IV voltmeter"},
        ])

        result = agent._check_pillar_4_witness_gate(request, procedure, {})

        assert result.loto_level == LotoLevel.LEVEL_4_ARC_FLASH
        assert result.witness_required is True
        assert "step_open_dc_breaker" in result.witness_steps
        assert result.identity_collision_protected is True
        assert result.outcome == PillarOutcome.PASS

    def test_pillar4_witness_present_but_engine_unprotected_warns(self):
        """Witness steps present but engine has no protection method -> WARN."""
        agent = make_agent(witness=MockWitnessEngineNoProtection())
        request = make_request(target="ups_a")
        procedure = make_procedure(steps=[
            {
                "id": "step_witness_open",
                "description": "Open UPS breaker (witness required)",
                "requires_witness": "true",
            },
            {"description": "Wait 90s for capacitor discharge"},
        ])

        result = agent._check_pillar_4_witness_gate(request, procedure, {})

        assert result.witness_required is True
        assert "step_witness_open" in result.witness_steps
        assert result.identity_collision_protected is False
        assert result.outcome == PillarOutcome.WARN


# =============================================================================
#  Pillar 5 tests (5)
# =============================================================================

class TestPillar5SequentialOrder:
    """Pillar 5: hybrid sequential order ELECTRICAL to HYDRAULIC to PURGE."""

    def test_pillar5_correct_order_passes(self):
        """ATS LOTO with electrical-only steps in order -> PASS."""
        agent = make_agent()
        request = make_request(target="ats_a")
        procedure = make_procedure(steps=[
            {"description": "Open breaker upstream"},
            {"description": "Lockout breaker handle"},
            {"description": "Verify zero voltage with voltmeter"},
        ])

        result = agent._check_pillar_5_sequential_order(request, procedure, {})

        assert result.outcome == PillarOutcome.PASS
        assert result.purge_required is False
        assert result.purge_present is False
        assert result.phases_in_correct_order is True

    def test_pillar5_order_violation_warns(self):
        """Procedure with PURGE before HYDRAULIC -> WARN (no HARD_FAIL alone)."""
        agent = make_agent()
        request = make_request(target="ats_a")
        procedure = make_procedure(steps=[
            {"description": "Open breaker upstream"},
            {"description": "Purge nitrogen from line"},
            {"description": "Close coolant valve to isolate cooling"},
        ])

        result = agent._check_pillar_5_sequential_order(request, procedure, {})

        assert result.phases_in_correct_order is False
        assert result.outcome == PillarOutcome.WARN
        assert any("phase order" in w.lower() for w in result.warnings)

    def test_pillar5_cooling_target_no_purge_hard_fail(self):
        """Chiller LOTO without purge step -> HARD_FAIL (cooling involved)."""
        agent = make_agent()
        request = make_request(target="chiller_1")
        procedure = make_procedure(steps=[
            {"description": "Open electrical breaker"},
            {"description": "Stop pump"},
            {"description": "Close coolant valve"},
            # Note: no purge step
        ])

        result = agent._check_pillar_5_sequential_order(request, procedure, {})

        assert result.purge_required is True
        assert result.purge_present is False
        assert result.outcome == PillarOutcome.HARD_FAIL
        assert any(
            "purge" in r.lower()
            for r in result.hard_fail_reasons
        )

    def test_pillar5_cooling_target_with_purge_passes(self):
        """CDU LOTO with full sequential order -> PASS."""
        agent = make_agent()
        request = make_request(target="cdu_a_01")
        procedure = make_procedure(steps=[
            {"description": "Open electrical breaker upstream of CDU"},
            {"description": "Stop secondary pump"},
            {"description": "Close manifold valve"},
            {"description": "Purge coolant from CDU loop"},
            {"description": "Verify zero pressure"},
        ])

        result = agent._check_pillar_5_sequential_order(request, procedure, {})

        assert result.purge_required is True
        assert result.purge_present is True
        assert result.phases_in_correct_order is True
        assert result.outcome == PillarOutcome.PASS

    def test_pillar5_phase_classification_via_keywords(self):
        """Verify each step is classified into correct LotoPhase."""
        agent = make_agent()
        request = make_request(target="cdu_a_01")
        procedure = make_procedure(steps=[
            {"description": "Open breaker upstream"},
            {"description": "Close coolant valve to isolate"},
            {"description": "Vent the line and release pressure"},
            {"description": "Verify zero with voltmeter"},
        ])

        result = agent._check_pillar_5_sequential_order(request, procedure, {})

        assert result.phases_detected[0] == LotoPhase.ELECTRICAL_ISOLATION
        assert result.phases_detected[1] == LotoPhase.HYDRAULIC_ISOLATION
        assert result.phases_detected[2] == LotoPhase.PURGE
        assert result.phases_detected[3] == LotoPhase.VERIFICATION


# =============================================================================
#  Pillar 6 tests (5)
# =============================================================================

class TestPillar6PPECategory:
    """Pillar 6: PPE category per NFPA 70E section 130."""

    def test_pillar6_low_voltage_cat0(self):
        """24V sensor with no PPE specified - CAT 0 required, no PPE -> WARN."""
        agent = make_agent()
        request = make_request(target="sensor_temp_01")
        procedure = make_procedure(steps=[
            {"description": "Disconnect sensor lead"},
        ])

        result = agent._check_pillar_6_ppe_category(request, procedure, {})

        assert result.computed_category == PPECategory.CAT_0
        # No PPE specified -> WARN
        assert result.outcome == PillarOutcome.WARN

    def test_pillar6_480v_cat2_required_no_ppe_warns(self):
        """480V ATS with no PPE specified -> CAT 2 required, WARN."""
        agent = make_agent()
        request = make_request(target="ats_a")
        procedure = make_procedure(steps=[
            {"description": "Open breaker"},
        ])

        result = agent._check_pillar_6_ppe_category(request, procedure, {})

        assert result.computed_category == PPECategory.CAT_2
        assert result.procedure_specified_category is None
        assert result.outcome == PillarOutcome.WARN

    def test_pillar6_800vdc_cat3_specified_passes(self):
        """800VDC with CAT 3 specified -> matches matrix, PASS."""
        agent = make_agent()
        request = make_request(target="rectifier_d1")
        procedure = make_procedure(
            metadata={"ppe_category": 3},
            steps=[
                {"description": "Open 800VDC main breaker"},
                {"description": "Wait 120s for capacitor discharge"},
            ],
        )

        result = agent._check_pillar_6_ppe_category(request, procedure, {})

        assert result.computed_category == PPECategory.CAT_3
        assert result.procedure_specified_category == PPECategory.CAT_3
        assert result.voltage_nominal == 800.0
        assert result.outcome == PillarOutcome.PASS
        # IEEE 1584 deferred per ADR-009 V10
        assert result.incident_energy_cal_cm2 is None

    def test_pillar6_under_ppe_hard_fail(self):
        """800VDC procedure specifies CAT 1 -> below required CAT 3, HARD_FAIL."""
        agent = make_agent()
        request = make_request(target="rectifier_d1")
        procedure = make_procedure(
            metadata={"ppe_category": 1},
            steps=[
                {"description": "Open 800VDC main breaker"},
            ],
        )

        result = agent._check_pillar_6_ppe_category(request, procedure, {})

        assert result.computed_category == PPECategory.CAT_3
        assert result.procedure_specified_category == PPECategory.CAT_1
        assert result.outcome == PillarOutcome.HARD_FAIL
        assert any(
            "CAT 1" in r and "CAT 3" in r
            for r in result.hard_fail_reasons
        )

    def test_pillar6_mv_transformer_cat4_required(self):
        """13.8 kV transformer requires CAT 4."""
        agent = make_agent()
        request = make_request(target="xfmr_mv")
        procedure = make_procedure(steps=[
            {"description": "Cat-IV PPE arc flash suit"},
            {"description": "Open MV breaker"},
        ])

        result = agent._check_pillar_6_ppe_category(request, procedure, {})

        assert result.computed_category == PPECategory.CAT_4
        # The procedure mentions "Cat-IV" which should be parsed as CAT_4
        assert result.procedure_specified_category == PPECategory.CAT_4
        assert result.outcome == PillarOutcome.PASS
