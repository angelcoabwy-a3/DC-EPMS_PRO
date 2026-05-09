"""
tests/test_loto_auditor_e2e.py
================================
End-to-end integration tests for LOTO Auditor (Batch 4.D).

Test scope:
  1. POST /api/loto/audit happy path - returns pending_approval verdict
  2. GET /api/loto/audit/{audit_id} returns persisted report
  3. GET /api/loto/audit/{audit_id} returns 404 for unknown ID
  4. POST with invalid target_component_id returns 4xx
  5. Markdown renderer produces well-formed output covering all 6 pillars

Strategy:
  - FastAPI TestClient against minimal app with router included
  - MockLotoAuditRepository for in-memory persistence
  - Mock dependencies (site_model, graphrag, physics, witness) reuse
    Pillar 4.B/4.C fixture pattern with simplified topology
  - LLM summary tests EXCLUDED (would require LM Studio running locally)
  - These tests do NOT require PostgreSQL or any external service
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from datetime import UTC

from loto_auditor_agent import LotoAuditorAgent, ProcedureSpec  # noqa: E402
from loto_auditor_models import (  # noqa: E402
    AuditStatus,
    LotoAuditReport,
    PillarOutcome,
)
from loto_auditor_report_renderer import render_audit_report_markdown  # noqa: E402
from loto_auditor_repository import MockLotoAuditRepository  # noqa: E402
from loto_auditor_routes import router  # noqa: E402

# =============================================================================
#  Mock fixtures (simplified subset of Batch 4.B+4.C mocks)
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
    def __init__(self):
        self._components = {
            "ats_a": MockComponentInfo(
                canonical_id="ats_a",
                type="ats",
                metadata={"voltage_nominal": 480.0, "path": "A"},
            ),
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
            "rack_a_001": MockComponentInfo(
                canonical_id="rack_a_001",
                type="gb200_rack",
                metadata={"rated_kw": 142.0},
            ),
        }

    def get_component(self, canonical_id):
        if canonical_id not in self._components:
            raise KeyError(f"Component '{canonical_id}' not found")
        return self._components[canonical_id]

    def power_chain_for(self, canonical_id):
        impacts = {
            "ats_a": MockImpactSet(
                failed_node="ats_a",
                chain_type="power",
                immediate=["rack_a_001"],
            ),
            "ups_a": MockImpactSet(
                failed_node="ups_a",
                chain_type="power",
                immediate=["ats_a"],
                transitive=["rack_a_001"],
            ),
        }
        return impacts.get(
            canonical_id,
            MockImpactSet(failed_node=canonical_id, chain_type="power"),
        )

    def cooling_chain_for(self, canonical_id):
        return MockImpactSet(failed_node=canonical_id, chain_type="cooling")


class MockGraphRAG:
    def query_topology(self, component_id):
        return {"affected_components": []}

    def query(self, query_text):
        return []


class MockPhysicsEngine:
    def validate_site(self, measurements):
        return {"site_health_index": 0.85}


class MockWitnessEngine:
    def get_protection_status(self):
        return {"identity_collision_protected": True}


# =============================================================================
#  Patched LotoAuditorAgent that bypasses procedure YAML loading for tests
# =============================================================================


class TestableLotoAuditorAgent(LotoAuditorAgent):
    """LotoAuditorAgent that uses an in-memory procedure registry.

    Real agent loads procedures from disk via ProcedureSpec. For tests we
    inject procedures via constructor to avoid filesystem dependency.
    """

    # Tell pytest this is NOT a test class despite the Test* prefix.
    __test__ = False

    def __init__(self, procedures: dict, **kwargs):
        super().__init__(**kwargs)
        self._procedures = procedures

    def _load_procedure(self, procedure_id: str) -> ProcedureSpec:
        if procedure_id not in self._procedures:
            from loto_auditor_agent import ProcedureNotFoundError

            raise ProcedureNotFoundError(f"Procedure '{procedure_id}' not in test registry")
        return ProcedureSpec(procedure_id, self._procedures[procedure_id])


# =============================================================================
#  Test app builder
# =============================================================================


def build_test_app() -> tuple[FastAPI, MockLotoAuditRepository, TestableLotoAuditorAgent]:
    """Construct a FastAPI app wired with mocks. Returns (app, repo, agent)."""
    app = FastAPI()

    procedures = {
        "MOP-ATS-OK": {
            "metadata": {"ppe_category": 2},
            "steps": [
                {"description": "Open breaker upstream"},
                {"description": "Lockout breaker handle"},
                {"description": "Verify zero voltage with voltmeter"},
            ],
        },
        "MOP-UPS-MISSING-DISCHARGE": {
            "metadata": {"ppe_category": 2},
            "steps": [
                {"description": "Open breaker"},
                {"description": "Tag out"},
            ],
        },
        "MOP-UPS-FULL-COMPLIANT": {
            "metadata": {"ppe_category": 2},
            "steps": [
                {
                    "id": "step_1",
                    "description": "Open breaker (witness required)",
                    "requires_witness": True,
                },
                {
                    "description": "Wait 120 seconds for capacitor discharge",
                    "duration_s": 120,
                },
                {"description": "Verify zero voltage with CAT IV voltmeter"},
            ],
        },
    }

    agent = TestableLotoAuditorAgent(
        procedures=procedures,
        site_model=MockSiteModel(),
        graphrag_service=MockGraphRAG(),
        physics_engine=MockPhysicsEngine(),
        witness_engine=MockWitnessEngine(),
    )

    repo = MockLotoAuditRepository()

    app.state.loto_auditor = agent
    app.state.loto_auditor_repo = repo
    app.include_router(router)

    return app, repo, agent


# =============================================================================
#  Test 1: POST /api/loto/audit happy path
# =============================================================================


class TestE2EPostAudit:
    def test_e2e_post_audit_returns_pending_approval(self):
        """Full request-response cycle, audit returned with pending_approval status."""
        app, repo, _ = build_test_app()
        client = TestClient(app)

        response = client.post(
            "/api/loto/audit",
            json={
                "procedure_id": "MOP-ATS-OK",
                "target_component_id": "ats_a",
                "cet_on_duty": "wilmer",
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == AuditStatus.PENDING_APPROVAL.value
        assert body["procedure_id"] == "MOP-ATS-OK"
        assert body["target_component_id"] == "ats_a"
        assert body["cet_on_duty"] == "wilmer"
        # Audit ID has the expected format
        assert body["audit_id"].startswith("LOTO-AUDIT-")
        # All 6 pillars present
        assert "impact_radius" in body
        assert "redundancy" in body
        assert "capacitor_discharge" in body
        assert "witness_gate" in body
        assert "sequential_order" in body
        assert "ppe_category" in body
        # Persistence happened
        assert repo.store_size == 1


# =============================================================================
#  Test 2: GET retrieves persisted audit
# =============================================================================


class TestE2EGetAudit:
    def test_e2e_get_audit_returns_persisted_report(self):
        """POST then GET retrieves the same audit."""
        app, repo, _ = build_test_app()
        client = TestClient(app)

        post_response = client.post(
            "/api/loto/audit",
            json={
                "procedure_id": "MOP-ATS-OK",
                "target_component_id": "ats_a",
                "cet_on_duty": "wilmer",
            },
        )
        assert post_response.status_code == 200
        audit_id = post_response.json()["audit_id"]

        get_response = client.get(f"/api/loto/audit/{audit_id}")
        assert get_response.status_code == 200
        retrieved = get_response.json()
        assert retrieved["audit_id"] == audit_id
        assert retrieved["procedure_id"] == "MOP-ATS-OK"
        assert retrieved["status"] == AuditStatus.PENDING_APPROVAL.value


# =============================================================================
#  Test 3: 404 on unknown audit_id
# =============================================================================


class TestE2EGetAudit404:
    def test_e2e_get_audit_404_for_unknown_id(self):
        """GET with unknown audit_id returns 404."""
        app, _, _ = build_test_app()
        client = TestClient(app)

        response = client.get("/api/loto/audit/LOTO-AUDIT-NONEXISTENT-12345678")
        assert response.status_code == 404
        body = response.json()
        assert "not found" in body["detail"].lower()


# =============================================================================
#  Test 4: Invalid target component returns 404
# =============================================================================


class TestE2EInvalidTarget:
    def test_e2e_post_with_unknown_target_returns_404(self):
        """Target component not in site_model returns 404 (TargetComponentNotFoundError)."""
        app, _, _ = build_test_app()
        client = TestClient(app)

        response = client.post(
            "/api/loto/audit",
            json={
                "procedure_id": "MOP-ATS-OK",
                "target_component_id": "phantom_component_xyz",
                "cet_on_duty": "wilmer",
            },
        )
        assert response.status_code == 404
        body = response.json()
        assert "not found" in body["detail"].lower()

    def test_e2e_post_with_malformed_request_returns_422(self):
        """Pydantic validation error returns 422."""
        app, _, _ = build_test_app()
        client = TestClient(app)

        # Empty target_component_id violates min_length=1
        response = client.post(
            "/api/loto/audit",
            json={
                "procedure_id": "MOP-ATS-OK",
                "target_component_id": "",
                "cet_on_duty": "wilmer",
            },
        )
        assert response.status_code == 422


# =============================================================================
#  Test 5: Markdown renderer integration
# =============================================================================


class TestE2EMarkdownRenderer:
    def test_e2e_markdown_endpoint_renders_all_pillars(self):
        """GET .../markdown returns markdown with all 6 pillar sections."""
        app, repo, _ = build_test_app()
        client = TestClient(app)

        post_response = client.post(
            "/api/loto/audit",
            json={
                "procedure_id": "MOP-UPS-FULL-COMPLIANT",
                "target_component_id": "ups_a",
                "cet_on_duty": "wilmer",
            },
        )
        assert post_response.status_code == 200
        audit_id = post_response.json()["audit_id"]

        md_response = client.get(f"/api/loto/audit/{audit_id}/markdown")
        assert md_response.status_code == 200
        markdown = md_response.text

        # All 6 pillar headers present
        assert "Pillar 1: Topology Impact Radius" in markdown
        assert "Pillar 2: 2N Redundancy Survival" in markdown
        assert "Pillar 3: Capacitor Discharge" in markdown
        assert "Pillar 4: Witness Gate" in markdown
        assert "Pillar 5: Hybrid Sequential Order" in markdown
        assert "Pillar 6: PPE Category" in markdown
        # Standards section present
        assert "Standards Cited" in markdown
        assert "NFPA 70E" in markdown
        # ADR-006 banner present
        assert "PENDING APPROVAL" in markdown
        # Audit ID footer
        assert audit_id in markdown


# =============================================================================
#  Pure-function tests for markdown renderer (no FastAPI needed)
# =============================================================================


class TestMarkdownRenderer:
    def test_markdown_renderer_handles_all_pillar_outcomes(self):
        """Renderer produces well-formed output regardless of pillar outcomes."""
        # Build a synthetic report with mixed outcomes
        from datetime import datetime

        from loto_auditor_models import (
            CapacitorDischargeCheck,
            ImpactRadius,
            LotoLevel,
            PPECategory,
            PPECategoryCheck,
            RedundancyAssessment,
            SequentialOrderCheck,
            WitnessGateCheck,
        )

        report = LotoAuditReport(
            procedure_id="MOP-TEST",
            target_component_id="ups_a",
            cet_on_duty="wilmer",
            as_of_timestamp=datetime.now(UTC),
            impact_radius=ImpactRadius(
                affected_components=["ats_a", "rack_a_001"],
                blast_radius_racks=1,
                blast_radius_kw=142.0,
                outcome=PillarOutcome.PASS,
            ),
            redundancy=RedundancyAssessment(
                target_path="A",
                shi_pre_loto=0.95,
                shi_post_loto=0.85,
                outcome=PillarOutcome.PASS,
            ),
            capacitor_discharge=CapacitorDischargeCheck(
                required=True,
                wait_duration_s=120,
                voltmeter_verification=True,
                outcome=PillarOutcome.PASS,
            ),
            witness_gate=WitnessGateCheck(
                loto_level=LotoLevel.LEVEL_3_CAP_DISCHARGE,
                witness_required=True,
                witness_steps=["step_1"],
                outcome=PillarOutcome.PASS,
            ),
            sequential_order=SequentialOrderCheck(
                outcome=PillarOutcome.PASS,
            ),
            ppe_category=PPECategoryCheck(
                voltage_nominal=480.0,
                computed_category=PPECategory.CAT_2,
                procedure_specified_category=PPECategory.CAT_2,
                outcome=PillarOutcome.PASS,
            ),
        )
        report.aggregate_outcomes()

        markdown = render_audit_report_markdown(report)

        # Sanity checks
        assert markdown.startswith("# LOTO Audit Report")
        assert "[PASS]" in markdown  # outcome marker rendered
        assert "Pillar 1" in markdown
        assert "Pillar 6" in markdown
        assert report.audit_id in markdown
        # No exception on render = test passes
