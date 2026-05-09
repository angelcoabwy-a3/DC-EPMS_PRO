"""
tests/test_loto_auditor_pillars.py
====================================
Unit tests for Pillars 1+2+3 implementations (Batch 4.B).

Test scope:
  - Pillar 1 (5 tests): topology impact radius
  - Pillar 2 (6 tests): 2N redundancy survival
  - Pillar 3 (7 tests): capacitor discharge per NEC 460.6

Strategy:
  - Mock site_model with hand-crafted A3-Alpha-like topology
  - Mock graphrag_service for cross-check tests
  - Mock physics_engine with configurable SHI per call sequence
  - All tests deterministic, no I/O, no real config files

These tests do NOT exercise:
  - audit() entrypoint orchestration (covered in Batch 4.D integration)
  - Pillars 4+5+6 (deferred to Batch 4.C tests)
  - LLM summary path (Batch 4.D)
  - YAML procedure file loading (use ProcedureSpec directly)
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from loto_auditor_agent import (  # noqa: E402
    LotoAuditorAgent,
    ProcedureSpec,
)
from loto_auditor_models import (  # noqa: E402
    LotoAuditRequest,
    PillarOutcome,
)

# =============================================================================
#  Mock fixtures (in-memory deterministic stand-ins for real subsystems)
# =============================================================================


@dataclass
class MockComponentInfo:
    """Mirror of site_model.ComponentInfo for tests."""

    canonical_id: str
    type: str
    metadata: dict = field(default_factory=dict)
    display: str = ""


@dataclass
class MockImpactSet:
    """Mirror of site_model.ImpactSet for tests."""

    failed_node: str
    chain_type: str = "power"
    immediate: list = field(default_factory=list)
    transitive: list = field(default_factory=list)
    by_type: dict = field(default_factory=dict)


class MockSiteModel:
    """In-memory site_model with realistic A3-Alpha-like topology.

    Topology (selected):
      - ups_a  (UPS, Path A, 480V, has_dc_link)  -> ats_a -> rpp_a_1 -> rack_a_001/002
      - ups_b  (UPS, Path B, 480V, has_dc_link)  -> [no impact set defined: empty]
      - chiller_1 (chiller, no path) -> cooling chain affects rack_a_001/002
      - rectifier_d1 (rectifier, 800V, Path A, has_dc_link) -> rack_a_001
      - ats_a (ATS, 480V, Path A) -> rpp_a_1, rack_a_001, rack_a_002
      - isolated_node (sensor, 24V) -> empty chain
    """

    def __init__(self, components_override=None, impacts_override=None):
        self._components = {
            "ups_a": MockComponentInfo(
                canonical_id="ups_a",
                type="ups",
                metadata={
                    "voltage_nominal": 480.0,
                    "rated_kw": 1500.0,
                    "path": "A",
                    "has_dc_link": True,
                },
                display="UPS A Galaxy VX",
            ),
            "ups_b": MockComponentInfo(
                canonical_id="ups_b",
                type="ups",
                metadata={
                    "voltage_nominal": 480.0,
                    "rated_kw": 1500.0,
                    "path": "B",
                    "has_dc_link": True,
                },
                display="UPS B Galaxy VX",
            ),
            "ats_a": MockComponentInfo(
                canonical_id="ats_a",
                type="ats",
                metadata={
                    "voltage_nominal": 480.0,
                    "path": "A",
                },
                display="ATS A",
            ),
            "rpp_a_1": MockComponentInfo(
                canonical_id="rpp_a_1",
                type="rpp",
                metadata={
                    "voltage_nominal": 480.0,
                    "rated_kw": 200.0,
                    "path": "A",
                },
            ),
            "rack_a_001": MockComponentInfo(
                canonical_id="rack_a_001",
                type="gb200_rack",
                metadata={"rated_kw": 142.0},
            ),
            "rack_a_002": MockComponentInfo(
                canonical_id="rack_a_002",
                type="gb200_rack",
                metadata={"rated_kw": 142.0},
            ),
            "chiller_1": MockComponentInfo(
                canonical_id="chiller_1",
                type="chiller",
                metadata={"voltage_nominal": 480.0},
            ),
            "rectifier_d1": MockComponentInfo(
                canonical_id="rectifier_d1",
                type="rectifier",
                metadata={
                    "voltage_nominal": 800.0,
                    "has_dc_link": True,
                    "path": "A",
                },
            ),
            "isolated_node": MockComponentInfo(
                canonical_id="isolated_node",
                type="sensor",
                metadata={"voltage_nominal": 24.0},
            ),
        }
        if components_override:
            self._components.update(components_override)

        self._impacts = {
            ("ups_a", "power"): MockImpactSet(
                failed_node="ups_a",
                chain_type="power",
                immediate=["ats_a"],
                transitive=["rpp_a_1", "rack_a_001", "rack_a_002"],
                by_type={
                    "ats": ["ats_a"],
                    "rpp": ["rpp_a_1"],
                    "gb200_rack": ["rack_a_001", "rack_a_002"],
                },
            ),
            ("ups_a", "cooling"): MockImpactSet(
                failed_node="ups_a",
                chain_type="cooling",
            ),
            ("ups_b", "power"): MockImpactSet(
                failed_node="ups_b",
                chain_type="power",
            ),
            ("ups_b", "cooling"): MockImpactSet(
                failed_node="ups_b",
                chain_type="cooling",
            ),
            ("chiller_1", "power"): MockImpactSet(
                failed_node="chiller_1",
                chain_type="power",
            ),
            ("chiller_1", "cooling"): MockImpactSet(
                failed_node="chiller_1",
                chain_type="cooling",
                immediate=["rack_a_001", "rack_a_002"],
            ),
            ("isolated_node", "power"): MockImpactSet(
                failed_node="isolated_node",
                chain_type="power",
            ),
            ("isolated_node", "cooling"): MockImpactSet(
                failed_node="isolated_node",
                chain_type="cooling",
            ),
            ("rectifier_d1", "power"): MockImpactSet(
                failed_node="rectifier_d1",
                chain_type="power",
                immediate=["rack_a_001"],
            ),
            ("rectifier_d1", "cooling"): MockImpactSet(
                failed_node="rectifier_d1",
                chain_type="cooling",
            ),
            ("ats_a", "power"): MockImpactSet(
                failed_node="ats_a",
                chain_type="power",
                immediate=["rpp_a_1"],
                transitive=["rack_a_001", "rack_a_002"],
            ),
            ("ats_a", "cooling"): MockImpactSet(
                failed_node="ats_a",
                chain_type="cooling",
            ),
        }
        if impacts_override:
            self._impacts.update(impacts_override)

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
    """Returns configurable topology responses per component."""

    def __init__(self, topology_responses=None):
        self._responses = topology_responses or {}

    def query_topology(self, component_id):
        return self._responses.get(component_id, {"affected_components": []})

    def query(self, query_text):
        return []


class MockPhysicsEngine:
    """Returns configurable SHI for pre/post LOTO validation calls.

    First call returns shi_pre, all subsequent calls return shi_post.
    """

    def __init__(self, shi_pre: float = 0.95, shi_post: float = 0.85):
        self._shi_pre = shi_pre
        self._shi_post = shi_post
        self._call_count = 0

    def validate_site(self, measurements):
        self._call_count += 1
        if self._call_count == 1:
            return {"site_health_index": self._shi_pre}
        return {"site_health_index": self._shi_post}


class MockWitnessEngine:
    """Placeholder for witness_engine dependency in agent constructor."""


# =============================================================================
#  Helpers
# =============================================================================


def make_agent(
    site_model: Any | None = None,
    graphrag: Any | None = None,
    physics: Any | None = None,
    witness: Any | None = None,
) -> LotoAuditorAgent:
    """Construct an agent with default mocks unless overridden."""
    return LotoAuditorAgent(
        site_model=site_model or MockSiteModel(),
        graphrag_service=graphrag or MockGraphRAG(),
        physics_engine=physics or MockPhysicsEngine(),
        witness_engine=witness or MockWitnessEngine(),
    )


def make_request(
    target: str = "ups_a",
    procedure: str = "MOP-TEST",
) -> LotoAuditRequest:
    return LotoAuditRequest(
        procedure_id=procedure,
        target_component_id=target,
        cet_on_duty="wilmer",
    )


def make_procedure(
    steps: list[dict] | None = None,
    procedure_id: str = "MOP-TEST",
) -> ProcedureSpec:
    return ProcedureSpec(procedure_id, {"steps": steps or []})


# =============================================================================
#  Pillar 1 tests (5)
# =============================================================================


class TestPillar1Topology:
    """Pillar 1: topological impact radius."""

    def test_pillar1_happy_path_ups_a(self):
        """ups_a LOTO enumerates correct downstream and computes blast radius."""
        agent = make_agent()
        request = make_request(target="ups_a")
        procedure = make_procedure()

        result = agent._check_pillar_1_topology(request, procedure, {})

        assert result.outcome == PillarOutcome.PASS
        assert "ats_a" in result.immediate_loads
        assert "rack_a_001" in result.transitive_loads
        assert "rack_a_002" in result.transitive_loads
        assert "rpp_a_1" in result.transitive_loads
        # Two GB200 racks downstream of ups_a
        assert result.blast_radius_racks == 2
        # rack_a_001 (142) + rack_a_002 (142) + rpp_a_1 (200) = 484
        # ats_a has no rated_kw in metadata, so contributes 0
        assert abs(result.blast_radius_kw - 484.0) < 0.1

    def test_pillar1_isolated_component_warns(self):
        """Component with empty downstream chain is WARN not HARD_FAIL."""
        agent = make_agent()
        request = make_request(target="isolated_node")
        procedure = make_procedure()

        result = agent._check_pillar_1_topology(request, procedure, {})

        assert result.outcome == PillarOutcome.WARN
        assert result.affected_components == []
        assert result.blast_radius_racks == 0
        assert result.blast_radius_kw == 0.0
        assert any("isolated" in n.lower() or "leaf" in n.lower() for n in result.notes)

    def test_pillar1_graphrag_inconsistency_noted_not_failed(self):
        """GraphRAG mentions phantom component absent in site_model."""
        graphrag = MockGraphRAG(
            topology_responses={
                "ups_a": {
                    "affected_components": ["ats_a", "rack_phantom_999"],
                }
            }
        )
        agent = make_agent(graphrag=graphrag)
        request = make_request(target="ups_a")
        procedure = make_procedure()

        result = agent._check_pillar_1_topology(request, procedure, {})

        assert result.graphrag_consistency_check is False
        assert any("graphrag" in n.lower() for n in result.notes)
        # Inconsistency does NOT cause HARD_FAIL alone
        assert result.outcome == PillarOutcome.PASS

    def test_pillar1_cooling_chain_integration(self):
        """chiller_1 has empty power chain but populated cooling chain."""
        agent = make_agent()
        request = make_request(target="chiller_1")
        procedure = make_procedure()

        result = agent._check_pillar_1_topology(request, procedure, {})

        assert "rack_a_001" in result.cooling_chain_affected
        assert "rack_a_002" in result.cooling_chain_affected
        # Power chain empty -> WARN on isolated
        assert result.affected_components == []

    def test_pillar1_blast_kw_aggregation(self):
        """blast_radius_kw correctly sums rated_kw across affected components."""
        agent = make_agent()
        request = make_request(target="ats_a")
        procedure = make_procedure()

        result = agent._check_pillar_1_topology(request, procedure, {})

        # rpp_a_1 (200) + rack_a_001 (142) + rack_a_002 (142) = 484
        assert abs(result.blast_radius_kw - 484.0) < 0.1
        assert result.blast_radius_racks == 2


# =============================================================================
#  Pillar 2 tests (6)
# =============================================================================


class TestPillar2Redundancy:
    """Pillar 2: 2N redundancy survival via physics_engine simulation."""

    def test_pillar2_happy_path_path_a(self):
        """SHI stays above threshold, target on Path A, no SPOFs."""
        physics = MockPhysicsEngine(shi_pre=0.95, shi_post=0.85)
        agent = make_agent(physics=physics)
        request = make_request(target="ups_a")
        procedure = make_procedure()

        result = agent._check_pillar_2_redundancy(request, procedure, {})

        assert result.outcome == PillarOutcome.PASS
        assert result.target_path == "A"
        assert result.path_a_state == "loto_in_progress"
        assert result.path_b_state == "carrying_full_load"
        assert abs(result.shi_pre_loto - 0.95) < 0.01
        assert abs(result.shi_post_loto - 0.85) < 0.01
        assert result.shi_threshold == 0.7
        assert result.hard_fail_reasons == []

    def test_pillar2_shi_below_threshold_hard_fail(self):
        """Post-LOTO SHI dropping below 0.7 triggers HARD_FAIL."""
        physics = MockPhysicsEngine(shi_pre=0.95, shi_post=0.5)
        agent = make_agent(physics=physics)
        request = make_request(target="ups_a")
        procedure = make_procedure()

        result = agent._check_pillar_2_redundancy(request, procedure, {})

        assert result.outcome == PillarOutcome.HARD_FAIL
        assert any("SHI" in r and "below threshold" in r for r in result.hard_fail_reasons)
        assert result.path_b_state == "degraded"

    def test_pillar2_chiller_spof_with_strict_threshold(self):
        """chiller LOTO with N_PLUS_1 threshold of 3 detects SPOF."""
        physics = MockPhysicsEngine(shi_pre=0.9, shi_post=0.85)
        agent = make_agent(physics=physics)
        # Override threshold to 3 to force SPOF detection (post-LOTO chiller=2)
        agent.N_PLUS_1_CHILLER_THRESHOLD = 3
        request = make_request(target="chiller_1")
        procedure = make_procedure()

        result = agent._check_pillar_2_redundancy(request, procedure, {})

        assert result.outcome == PillarOutcome.HARD_FAIL
        assert len(result.single_points_of_failure) > 0
        assert any("chiller" in spof.lower() for spof in result.single_points_of_failure)

    def test_pillar2_no_path_metadata_unknown_states(self):
        """Component without path metadata returns unknown path states."""
        physics = MockPhysicsEngine(shi_pre=0.95, shi_post=0.85)
        agent = make_agent(physics=physics)
        request = make_request(target="chiller_1")
        procedure = make_procedure()

        result = agent._check_pillar_2_redundancy(request, procedure, {})

        assert result.target_path is None
        assert "unknown" in result.path_a_state.lower()
        assert "unknown" in result.path_b_state.lower()

    def test_pillar2_target_path_b_state_assignment(self):
        """ups_b on Path B assigns path_b_state to loto_in_progress."""
        physics = MockPhysicsEngine(shi_pre=0.95, shi_post=0.85)
        agent = make_agent(physics=physics)
        request = make_request(target="ups_b")
        procedure = make_procedure()

        result = agent._check_pillar_2_redundancy(request, procedure, {})

        assert result.target_path == "B"
        assert result.path_b_state == "loto_in_progress"
        assert result.path_a_state == "carrying_full_load"

    def test_pillar2_overlapping_maintenance_stub_returns_false(self):
        """Batch 4.B: overlapping_maintenance always False (Batch 4.D adds CMMS)."""
        physics = MockPhysicsEngine(shi_pre=0.95, shi_post=0.85)
        agent = make_agent(physics=physics)
        request = make_request(target="ups_a")
        procedure = make_procedure()

        result = agent._check_pillar_2_redundancy(request, procedure, {})

        assert result.overlapping_maintenance is False


# =============================================================================
#  Pillar 3 tests (7)
# =============================================================================


class TestPillar3CapacitorDischarge:
    """Pillar 3: capacitor discharge verification per NEC 460.6."""

    def test_pillar3_not_applicable_for_ats(self):
        """ATS at 480V is not UPS and has no DC link -> NOT_APPLICABLE."""
        agent = make_agent()
        request = make_request(target="ats_a")
        procedure = make_procedure()

        result = agent._check_pillar_3_capacitor_discharge(request, procedure, {})

        assert result.outcome == PillarOutcome.NOT_APPLICABLE
        assert result.required is False
        assert result.required_reason is None

    def test_pillar3_required_for_ups_missing_step_hard_fail(self):
        """UPS target requires discharge but procedure has none."""
        agent = make_agent()
        request = make_request(target="ups_a")
        procedure = make_procedure(
            steps=[
                {"description": "Open breaker", "action": "open_breaker"},
                {"description": "Tag out", "action": "tag_out"},
            ]
        )

        result = agent._check_pillar_3_capacitor_discharge(request, procedure, {})

        assert result.required is True
        assert result.found_in_procedure is False
        assert result.outcome == PillarOutcome.HARD_FAIL
        assert "UPS" in (result.required_reason or "")

    def test_pillar3_required_for_800vdc_rectifier(self):
        """800VDC rectifier requires discharge per Building D mandate."""
        agent = make_agent()
        request = make_request(target="rectifier_d1")
        procedure = make_procedure(
            steps=[
                {"description": "Open breaker", "action": "open"},
            ]
        )

        result = agent._check_pillar_3_capacitor_discharge(request, procedure, {})

        assert result.required is True
        assert "800" in (result.required_reason or "")
        # Discharge step missing -> HARD_FAIL
        assert result.outcome == PillarOutcome.HARD_FAIL

    def test_pillar3_wait_too_short_hard_fail(self):
        """30s wait violates NEC 460.6 minimum 60s."""
        agent = make_agent()
        request = make_request(target="ups_a")
        procedure = make_procedure(
            steps=[
                {"description": "Open breaker", "action": "open"},
                {
                    "description": "Wait 30 seconds for capacitor discharge",
                    "action": "wait",
                    "duration_s": 30,
                },
            ]
        )

        result = agent._check_pillar_3_capacitor_discharge(request, procedure, {})

        assert result.required is True
        assert result.found_in_procedure is True
        assert result.wait_duration_s == 30
        assert result.outcome == PillarOutcome.HARD_FAIL
        assert any(
            "60s" in n.lower() or "minimum" in n.lower() or "below" in n.lower()
            for n in result.notes
        )

    def test_pillar3_no_voltmeter_warn(self):
        """90s wait without voltmeter verification -> WARN not HARD_FAIL."""
        agent = make_agent()
        request = make_request(target="ups_a")
        procedure = make_procedure(
            steps=[
                {"description": "Open breaker", "action": "open"},
                {
                    "description": "Wait 90 seconds for capacitor discharge",
                    "duration_s": 90,
                },
            ]
        )

        result = agent._check_pillar_3_capacitor_discharge(request, procedure, {})

        assert result.required is True
        assert result.found_in_procedure is True
        assert result.wait_duration_s == 90
        assert result.voltmeter_verification is False
        assert result.outcome == PillarOutcome.WARN

    def test_pillar3_happy_path_all_compliant(self):
        """All elements present: discharge step + 120s wait + voltmeter."""
        agent = make_agent()
        request = make_request(target="ups_a")
        procedure = make_procedure(
            steps=[
                {"description": "Open breaker", "action": "open"},
                {
                    "description": "Wait 120 seconds for capacitor discharge",
                    "duration_s": 120,
                },
                {
                    "description": "Verify zero voltage with CAT IV voltmeter",
                    "action": "verify_voltage",
                },
            ]
        )

        result = agent._check_pillar_3_capacitor_discharge(request, procedure, {})

        assert result.required is True
        assert result.found_in_procedure is True
        assert result.wait_duration_s >= 120
        assert result.voltmeter_verification is True
        assert result.outcome == PillarOutcome.PASS

    def test_pillar3_keyword_extraction_from_text(self):
        """Wait duration extracted from text without explicit duration_s field."""
        agent = make_agent()
        request = make_request(target="ups_a")
        procedure = make_procedure(
            steps=[
                {"description": "Wait 60 seconds for capacitor discharge to complete"},
                {"description": "Verify with Fluke voltmeter that voltage is zero"},
            ]
        )

        result = agent._check_pillar_3_capacitor_discharge(request, procedure, {})

        assert result.found_in_procedure is True
        assert result.wait_duration_s == 60
        assert result.voltmeter_verification is True
        assert result.outcome == PillarOutcome.PASS
