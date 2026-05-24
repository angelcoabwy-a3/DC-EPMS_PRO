"""
tests/test_mcp_health.py
========================
S-MCP-HEALTH-01 option (ii) -- backend.mcp_health probe + cache +
audit gate integration.

The probe is feature-flagged behind DC_EPMS_MCP_PROBE (default OFF).
When disabled, state is None and the audit gate behaves exactly as
v0.16.0 (string-match only). When enabled, the background task
polls the configured URL; audit fires a CAUTION finding when the
probe is failing so operators know Discipline AI agents are
unreachable.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.agents.procedure_architect import (
    AUDIT_VERDICT_APPROVE,
    AUDIT_VERDICT_CAUTION,
    DOC_TYPE_MOP,
    ProcedureDraft,
    audit_procedure_safety,
)
from backend.mcp_health import (
    _reset_mcp_health_for_test,
    _set_mcp_health_for_test,
    get_mcp_health,
    probe_mcp_sync,
)


# ─── Reset state between every test (probe is module-level) ──────────
@pytest.fixture(autouse=True)
def _reset_probe_state():
    _reset_mcp_health_for_test()
    yield
    _reset_mcp_health_for_test()


def _full_richer_mop() -> str:
    """A MOP body that passes EVERY other audit rule -- only the MCP
    probe-failure finding can fire CAUTION in these tests."""
    return (
        "# MOP — Test\n"
        "## 1. Alcance y Objetivo\n"
        "* Identificador (Tag): UPS-TEST\n"
        "* Estado Final Esperado: isolated\n"
        "## 2. Evaluación de Impacto y Riesgos\n"
        "* Vector Eléctrico: arc-flash, PPE Cat 2 per CSA Z462-24\n"
        "## 3. Prerrequisitos\n"
        "* LOTO + PTW + Agentes MCP Health Check (Checker ONLINE)\n"
        "## 4. Pasos Secuenciales\n"
        "1. Vivo-Muerto-Vivo before manipulation\n"
        "2. [HOLD POINT] verify isolation\n"
        "## 5. Plan de Reversión\n"
        "* Disparador: revert if T > 27 °C for > 60 s\n"
        "* Restauración: cerrar Q2, verificar bypass OK\n"
    )


def _draft(content: str, asset_id: str | None = None) -> ProcedureDraft:
    return ProcedureDraft(
        draft_id="t",
        doc_type=DOC_TYPE_MOP,
        context="(test)",
        content=content,
        asset_id=asset_id,
        generated_at=0.0,
        llm_present=False,
    )


# ─── get_mcp_health initial state ────────────────────────────────────
class TestMcpHealthState:
    def test_initial_state_is_none(self):
        state, reason, ts = get_mcp_health()
        assert state is None
        assert reason == ""
        assert ts == 0.0

    def test_set_for_test_writes_state(self):
        _set_mcp_health_for_test(True, "test-injected reason", 12345.0)
        state, reason, ts = get_mcp_health()
        assert state is True
        assert reason == "test-injected reason"
        assert ts == 12345.0

    def test_set_for_test_can_inject_false(self):
        _set_mcp_health_for_test(False, "LM Studio unreachable")
        state, reason, _ = get_mcp_health()
        assert state is False
        assert "LM Studio unreachable" in reason

    def test_reset_returns_to_none(self):
        _set_mcp_health_for_test(True)
        _reset_mcp_health_for_test()
        state, _, _ = get_mcp_health()
        assert state is None


# ─── probe_mcp_sync unit tests ──────────────────────────────────────
class TestProbeMcpSync:
    def test_returns_true_on_http_200(self):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda self: mock_resp
        mock_resp.__exit__ = lambda *args: False
        with patch("backend.mcp_health.request.urlopen", return_value=mock_resp):
            healthy, reason = probe_mcp_sync()
        assert healthy is True
        assert "HTTP 200" in reason

    def test_returns_false_on_http_500(self):
        mock_resp = MagicMock()
        mock_resp.status = 500
        mock_resp.__enter__ = lambda self: mock_resp
        mock_resp.__exit__ = lambda *args: False
        with patch("backend.mcp_health.request.urlopen", return_value=mock_resp):
            healthy, reason = probe_mcp_sync()
        assert healthy is False
        assert "HTTP 500" in reason

    def test_returns_false_on_url_error(self):
        from urllib.error import URLError
        with patch(
            "backend.mcp_health.request.urlopen",
            side_effect=URLError("Connection refused"),
        ):
            healthy, reason = probe_mcp_sync()
        assert healthy is False
        assert "URLError" in reason

    def test_returns_false_on_generic_exception(self):
        with patch(
            "backend.mcp_health.request.urlopen",
            side_effect=RuntimeError("unexpected"),
        ):
            healthy, reason = probe_mcp_sync()
        assert healthy is False
        assert "probe error" in reason


# ─── Audit gate integration ─────────────────────────────────────────
class TestAuditMcpProbeIntegration:
    """The audit gate reads get_mcp_health() and fires a CAUTION
    finding when the probe is UNHEALTHY (False). Probe state of
    None (disabled) or True (healthy) does NOT fire the additional
    finding -- behavior matches v0.16.0 string-match-only path."""

    def test_probe_disabled_does_not_fire_extra_finding(self):
        # state=None means probe disabled -- no MCP-probe finding.
        # Body is fully richer-compliant -> verdict APPROVE.
        _reset_mcp_health_for_test()
        result = audit_procedure_safety(_draft(_full_richer_mop()))
        assert result.verdict == AUDIT_VERDICT_APPROVE
        assert not any(
            "MCP health probe FAILED" in f for f in result.findings
        )

    def test_probe_healthy_does_not_fire_extra_finding(self):
        _set_mcp_health_for_test(True, "HTTP 200 from LM Studio")
        result = audit_procedure_safety(_draft(_full_richer_mop()))
        assert result.verdict == AUDIT_VERDICT_APPROVE
        assert not any(
            "MCP health probe FAILED" in f for f in result.findings
        )

    def test_probe_failing_fires_caution_with_reason(self):
        _set_mcp_health_for_test(
            False, "URLError: Connection refused (LM Studio offline)",
        )
        result = audit_procedure_safety(_draft(_full_richer_mop()))
        # CAUTION because the probe-failed finding fires; the body
        # itself satisfies every other rule.
        assert result.verdict == AUDIT_VERDICT_CAUTION
        probe_findings = [
            f for f in result.findings if "MCP health probe FAILED" in f
        ]
        assert len(probe_findings) == 1
        # Reason annotated for diagnosability.
        assert "Connection refused" in probe_findings[0]
        assert "Discipline AI agents may not be reachable" in probe_findings[0]

    def test_probe_failing_compounds_with_other_richer_omissions(self):
        # Body missing the agent-health string-match too -- BOTH
        # advisories fire, verdict CAUTION (no hard_stop from these).
        # Body is carefully constructed to not contain MCP / Health
        # Check / Agente Revisor / Discipline AI tokens anywhere.
        body = (
            "# MOP — Test\n"
            "## 1. Alcance y Objetivo\n"
            "* Identificador (Tag): UPS-TEST\n"
            "* Estado Final Esperado: isolated\n"
            "## 2. Evaluación de Impacto y Riesgos\n"
            "* Vector Eléctrico: arc-flash, PPE Cat 2 per CSA Z462-24\n"
            "## 3. Prerrequisitos\n"
            "* LOTO + PTW + manager notification confirmed\n"
            "## 4. Pasos Secuenciales\n"
            "1. Vivo-Muerto-Vivo before manipulation\n"
            "2. [HOLD POINT] verify isolation\n"
            "## 5. Plan de Reversión\n"
            "* Disparador: revert if T > 27 °C for > 60 s\n"
            "* Restauración: cerrar Q2\n"
        )
        _set_mcp_health_for_test(False, "URLError: timed out")
        result = audit_procedure_safety(_draft(body))
        assert result.verdict == AUDIT_VERDICT_CAUTION
        assert any("MCP / Agentes ONLINE" in f for f in result.findings)
        assert any("MCP health probe FAILED" in f for f in result.findings)
