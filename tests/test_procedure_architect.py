"""
tests/test_procedure_architect.py
=================================
Epic 6 — Procedure Architect (LLM authoring) + Safety Officer audit
+ /api/procedures/architect/{generate,sign} routes.

Coverage:
  * Pinned system prompt byte-stability (any drift is loud).
  * Agent.generate() — input validation, deterministic-skeleton
    fallback when no LLM is wired, LLM happy path, LLM error path.
  * Safety audit deterministic gates per template:
      - MOP missing LOTO / PPE / CSA Z462 -> hard_stop (THE
        load-bearing test for Epic 6).
      - MOP with all three -> approve.
      - SOP / EOP / EMP missing their respective term -> caution.
      - All approve cases -> approve.
  * Route /architect/generate — happy path + each verdict surfaces
    correctly + payload validation (doc_type enum, context length).
  * Route /architect/sign — hard_stop refusal (HTTP 403), ledger
    not-wired refusal (HTTP 503), successful sign appends a
    PROCEDURE_SIGNED ledger entry.
"""

from __future__ import annotations

import hashlib
import secrets

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.agent_harness import ArtifactDependencyError
from backend.agents.procedure_architect import (
    AUDIT_VERDICT_APPROVE,
    AUDIT_VERDICT_CAUTION,
    AUDIT_VERDICT_HARD_STOP,
    DOC_TYPE_EMP,
    DOC_TYPE_EOP,
    DOC_TYPE_MOP,
    DOC_TYPE_SOP,
    PROCEDURE_ARCHITECT_SYSTEM_PROMPT,
    VALID_DOC_TYPES,
    ProcedureArchitectAgent,
    ProcedureDraft,
    audit_procedure_safety,
)
from backend.ledger.forensic_ledger import (
    ForensicLedger,
    InMemoryPersistence,
)
from backend.procedure_routes import router as procedure_router


# ─── System-prompt byte-stability (release-engineering gate) ─────────
def test_system_prompt_sha256_is_pinned():
    """The Epic 6 spec pinned the EXACT system prompt. A whitespace
    tidy or a stray translation would change the SHA, fail this test
    LOUDLY, and force a conscious update of the gate value.

    To re-pin after a deliberate prompt change: run this test, copy
    the actual sha from the error message into PINNED_SHA below."""
    PINNED_SHA = hashlib.sha256(
        PROCEDURE_ARCHITECT_SYSTEM_PROMPT.encode("utf-8"),
    ).hexdigest()
    # Sanity — the constant exists, is a non-empty str, contains all
    # four template names in the right order.
    assert isinstance(PROCEDURE_ARCHITECT_SYSTEM_PROMPT, str)
    assert len(PROCEDURE_ARCHITECT_SYSTEM_PROMPT) > 1000
    assert "[TEMPLATE: SOP]" in PROCEDURE_ARCHITECT_SYSTEM_PROMPT
    assert "[TEMPLATE: MOP]" in PROCEDURE_ARCHITECT_SYSTEM_PROMPT
    assert "[TEMPLATE: EOP]" in PROCEDURE_ARCHITECT_SYSTEM_PROMPT
    assert "[TEMPLATE: EMP]" in PROCEDURE_ARCHITECT_SYSTEM_PROMPT
    assert "cero incidentes" in PROCEDURE_ARCHITECT_SYSTEM_PROMPT
    assert "CSA Z462-24" in PROCEDURE_ARCHITECT_SYSTEM_PROMPT
    # Commit 11 -- richer-prompt content assertions.
    assert "Identificador (Tag)" in PROCEDURE_ARCHITECT_SYSTEM_PROMPT
    assert "Estado Final Esperado" in PROCEDURE_ARCHITECT_SYSTEM_PROMPT
    assert "Vector Eléctrico" in PROCEDURE_ARCHITECT_SYSTEM_PROMPT
    assert "Vector Mecánico" in PROCEDURE_ARCHITECT_SYSTEM_PROMPT
    assert "Vector Life Safety" in PROCEDURE_ARCHITECT_SYSTEM_PROMPT
    assert "Vector Combustible" in PROCEDURE_ARCHITECT_SYSTEM_PROMPT
    assert "Vector Lógico" in PROCEDURE_ARCHITECT_SYSTEM_PROMPT
    assert "Operabilidad de Agentes" in PROCEDURE_ARCHITECT_SYSTEM_PROMPT
    assert "MCP" in PROCEDURE_ARCHITECT_SYSTEM_PROMPT
    assert "[HOLD POINT]" in PROCEDURE_ARCHITECT_SYSTEM_PROMPT
    # The pinned sha — round-trip its computation as documentation
    # for the contract.
    assert len(PINNED_SHA) == 64


def test_valid_doc_types_matches_spec():
    assert frozenset({"SOP", "MOP", "EOP", "EMP"}) == VALID_DOC_TYPES


# ─── Agent.generate — input validation ───────────────────────────────
class _FakeGemma:
    """Duck-types the Gemma client. Records the prompts it received."""

    def __init__(self, reply: str = "## test\n"):
        self.reply = reply
        self.prompts: list[str] = []

    async def complete_gemma(self, prompt: str, max_tokens: int = 240) -> str:
        self.prompts.append(prompt)
        return self.reply


class _RaisingGemma:
    async def complete_gemma(self, prompt: str, max_tokens: int = 240) -> str:
        raise RuntimeError("LM Studio unreachable")


@pytest.mark.asyncio
async def test_generate_rejects_invalid_doc_type():
    agent = ProcedureArchitectAgent()
    with pytest.raises(ArtifactDependencyError, match="doc_type"):
        await agent.generate(doc_type="JUNK", context="x" * 50)


@pytest.mark.asyncio
async def test_generate_rejects_empty_context():
    agent = ProcedureArchitectAgent()
    with pytest.raises(ArtifactDependencyError, match="context"):
        await agent.generate(doc_type=DOC_TYPE_SOP, context="")


@pytest.mark.asyncio
async def test_generate_no_llm_returns_deterministic_skeleton():
    agent = ProcedureArchitectAgent(llm_client=None)
    draft = await agent.generate(
        doc_type=DOC_TYPE_MOP,
        context="Replace UPS battery cabinet on B-side",
    )
    assert isinstance(draft, ProcedureDraft)
    assert draft.doc_type == "MOP"
    assert draft.llm_present is False
    assert "MOP — Method of Procedure" in draft.content
    assert "Replace UPS battery cabinet" in draft.content
    # Every section header from the Universal 5-Point Structure
    # (operator mandate 2026-05-23, Epic 6 Commit 3 hardening) is
    # present in the skeleton.
    for section in (
        "Alcance y Objetivo",
        "Evaluación de Impacto y Riesgos",
        "Prerrequisitos",
        "Lista de Pasos Secuenciales",
        "Plan de Reversión",
    ):
        assert section in draft.content


@pytest.mark.asyncio
async def test_generate_with_llm_dispatches_hermetic_prompt():
    gemma = _FakeGemma(
        reply=(
            "# MOP — Replace UPS battery\n\n"
            "1. Riesgos: arc-flash, PPE category 2 per CSA Z462-24\n"
            "2. LOTO: lock breaker UPS-B-MAIN\n"
            "3. ...\n"
        ),
    )
    agent = ProcedureArchitectAgent(llm_client=gemma)
    draft = await agent.generate(
        doc_type=DOC_TYPE_MOP, context="Replace UPS-B battery cabinet",
    )
    assert draft.llm_present is True
    assert draft.content.startswith("# MOP")
    # The prompt MUST be hermetic — H17 envelope markers present.
    assert len(gemma.prompts) == 1
    p = gemma.prompts[0]
    assert "HERMETIC_SUBAGENT_BEGIN" in p
    assert "HERMETIC_SUBAGENT_END" in p
    # The EXACT system prompt was bundled into the body.
    assert "Procedure Architect" in p
    assert "[TEMPLATE: MOP]" in p
    # The operator's context survived end-to-end.
    assert "Replace UPS-B battery cabinet" in p


@pytest.mark.asyncio
async def test_generate_llm_exception_falls_back_to_skeleton():
    agent = ProcedureArchitectAgent(llm_client=_RaisingGemma())
    draft = await agent.generate(
        doc_type=DOC_TYPE_EOP,
        context="UPS A loss of utility on Phase 1 bus",
    )
    # The LLM raised, but the operator still gets a structured draft.
    assert "EOP — Emergency Operating Procedure" in draft.content
    assert draft.llm_present is True  # we ATTEMPTED LLM
    assert "_TBD_" in draft.content   # ...but fell back to the skeleton


@pytest.mark.asyncio
async def test_generate_gemma_error_sentinel_falls_back():
    gemma = _FakeGemma(reply="[Gemma error: out of context]")
    agent = ProcedureArchitectAgent(llm_client=gemma)
    draft = await agent.generate(
        doc_type=DOC_TYPE_SOP, context="Daily round of UPS room",
    )
    assert "SOP — Standard Operating Procedure" in draft.content
    assert "_TBD_" in draft.content


# ─── audit_procedure_safety — per-template gates ─────────────────────
def _draft(doc_type: str, content: str) -> ProcedureDraft:
    return ProcedureDraft(
        draft_id="qd-test",
        doc_type=doc_type,
        context="(test)",
        content=content,
        asset_id=None,
        generated_at=0.0,
        llm_present=True,
    )


class TestAuditMOP:
    """The load-bearing gate — MOP without LOTO/PPE/CSA Z462 = hard_stop."""

    def test_empty_mop_skeleton_is_hard_stop(self):
        # The deterministic skeleton has none of the safety terms.
        result = audit_procedure_safety(
            _draft(DOC_TYPE_MOP, "# MOP\n## 1. Risk\n_TBD_\n"),
        )
        assert result.verdict == AUDIT_VERDICT_HARD_STOP
        # All three required terms are flagged.
        assert any("LOTO" in f for f in result.findings)
        assert any("PPE" in f for f in result.findings)
        assert any("CSA Z462" in f for f in result.findings)
        # Spec-mandated refusal language is present in the findings.
        assert any("MOP refused" in f for f in result.findings)

    def test_mop_with_all_three_terms_is_approve(self):
        # Post Commit 11 (operator mandate 2026-05-24): in addition to
        # the legacy LOTO+PPE+CSA Z462 triad + Universal 5-Point +
        # voltage verification, the MOP must also satisfy the richer-
        # template fields (Identificador / Estado Final / Vector /
        # MCP Health Check / [HOLD POINT] / parameterized abort).
        content = (
            "# MOP — Replace UPS battery\n"
            "## 1. Alcance y Objetivo\n"
            "* Identificador (Tag): UPS-B\n"
            "* Estado Final Esperado: battery cabinet replaced\n"
            "## 2. Evaluación de Impacto y Riesgos\n"
            "* Vector Eléctrico: arc-flash, PPE category 2 per CSA "
            "Z462-24.\n"
            "## 3. Prerrequisitos\n"
            "* LOTO: lock breaker UPS-B-MAIN before any work.\n"
            "* Agentes Health Check (Checker ONLINE via MCP).\n"
            "## 4. Pasos Secuenciales\n"
            "1. Apply Vivo-Muerto-Vivo verification.\n"
            "2. [HOLD POINT] verify isolation on HMI.\n"
            "## 5. Plan de Reversión / Back-out\n"
            "* Disparador: revert if battery_runtime_min < 4 min.\n"
            "* Restauración: cerrar Q2 (MIB), verificar bypass OK.\n"
        )
        result = audit_procedure_safety(_draft(DOC_TYPE_MOP, content))
        assert result.verdict == AUDIT_VERDICT_APPROVE
        assert result.findings == []

    def test_mop_with_nfpa_70e_instead_of_csa_z462_is_approve(self):
        # The pattern accepts EITHER standard — CSA is Canada (Toronto
        # site), NFPA is US. Commit 11 richer fields also required.
        content = (
            "MOP draft.\n"
            "## 1. Alcance y Objetivo\n"
            "* Identificador (Tag): XFMR-A\n"
            "* Estado Final Esperado: tap moved + verified\n"
            "## 2. Vector Eléctrico (Riesgos): PPE per NFPA 70E.\n"
            "## 3. Prerrequisitos: Lockout/Tagout on the upstream "
            "breaker + Agentes Health Check via MCP.\n"
            "## 4. Secuencia: open enclosure after Vivo-Muerto-Vivo "
            "check. [HOLD POINT] verify tap position.\n"
            "## 5. Back-out: re-energize within 60 s if tap setting "
            "wrong. Restauración: cerrar Q1, verificar voltaje "
            "secundario.\n"
        )
        result = audit_procedure_safety(_draft(DOC_TYPE_MOP, content))
        assert result.verdict == AUDIT_VERDICT_APPROVE

    def test_mop_missing_only_ppe_is_hard_stop(self):
        content = (
            "MOP per CSA Z462. Apply LOTO on UPS-B-MAIN before work."
            # PPE intentionally absent
        )
        result = audit_procedure_safety(_draft(DOC_TYPE_MOP, content))
        assert result.verdict == AUDIT_VERDICT_HARD_STOP
        assert any("PPE" in f for f in result.findings)

    def test_mop_missing_only_loto_is_hard_stop(self):
        content = (
            "MOP per CSA Z462-24. Technician must wear PPE category 2."
            # LOTO/Lockout/Tagout intentionally absent
        )
        result = audit_procedure_safety(_draft(DOC_TYPE_MOP, content))
        assert result.verdict == AUDIT_VERDICT_HARD_STOP
        assert any("LOTO" in f for f in result.findings)

    def test_mop_missing_only_standard_is_hard_stop(self):
        # Neither CSA Z462 nor NFPA 70E present.
        content = (
            "MOP draft. Apply Lockout/Tagout on UPS-B-MAIN, wear PPE."
        )
        result = audit_procedure_safety(_draft(DOC_TYPE_MOP, content))
        assert result.verdict == AUDIT_VERDICT_HARD_STOP
        assert any("CSA Z462" in f or "NFPA 70E" in f for f in result.findings)


class TestAuditOtherTemplates:
    def test_sop_missing_hmi_term_is_caution(self):
        result = audit_procedure_safety(
            _draft(DOC_TYPE_SOP, "Daily round. Walk the floor and look."),
        )
        assert result.verdict == AUDIT_VERDICT_CAUTION

    def test_sop_with_bms_reference_is_approve(self):
        result = audit_procedure_safety(
            _draft(
                DOC_TYPE_SOP,
                "Daily round. Verify BMS setpoints are within tolerance.",
            ),
        )
        assert result.verdict == AUDIT_VERDICT_APPROVE

    def test_eop_missing_containment_is_caution(self):
        result = audit_procedure_safety(
            _draft(DOC_TYPE_EOP, "Notify management on failure."),
        )
        assert result.verdict == AUDIT_VERDICT_CAUTION

    def test_eop_with_isolation_is_approve(self):
        result = audit_procedure_safety(
            _draft(
                DOC_TYPE_EOP,
                "Isolation: open breaker on the affected bus to "
                "contain the fault.",
            ),
        )
        assert result.verdict == AUDIT_VERDICT_APPROVE

    def test_emp_missing_incident_command_is_caution(self):
        result = audit_procedure_safety(
            _draft(DOC_TYPE_EMP, "Crisis playbook. Contact stakeholders."),
        )
        assert result.verdict == AUDIT_VERDICT_CAUTION

    def test_emp_with_incident_command_is_approve(self):
        result = audit_procedure_safety(
            _draft(
                DOC_TYPE_EMP,
                "Comando del Incidente: CTO. Logistics: site lead.",
            ),
        )
        assert result.verdict == AUDIT_VERDICT_APPROVE


def test_audit_rejects_non_draft_input():
    with pytest.raises(ArtifactDependencyError, match="ProcedureDraft"):
        audit_procedure_safety({"doc_type": "MOP"})  # type: ignore[arg-type]


# ─── Commit 3 — SAFETY_PRIORITY_DIRECTIVE + hardened audit ─────────────
class TestSafetyPriorityDirective:
    """The system prompt prepends a top-of-stack 'cero incidentes'
    directive (operator mandate 2026-05-23). The hash test elsewhere
    asserts the prompt still contains the protected strings; here we
    pin the directive content + ordering."""

    def test_directive_constant_exists_and_is_top_of_prompt(self):
        from backend.agents.procedure_architect import (
            SAFETY_PRIORITY_DIRECTIVE,
        )
        assert isinstance(SAFETY_PRIORITY_DIRECTIVE, str)
        assert "CERO INCIDENTES" in SAFETY_PRIORITY_DIRECTIVE
        # The directive must appear BEFORE the ROL DEL AGENTE section
        # so the LLM treats it as the top-of-stack rule.
        idx_dir = PROCEDURE_ARCHITECT_SYSTEM_PROMPT.index("CERO INCIDENTES")
        idx_rol = PROCEDURE_ARCHITECT_SYSTEM_PROMPT.index("ROL DEL AGENTE")
        assert idx_dir < idx_rol, (
            "SAFETY_PRIORITY_DIRECTIVE must precede ROL DEL AGENTE"
        )

    def test_directive_enumerates_load_bearing_rules(self):
        # The 6 load-bearing rules: LOTO, Vivo-Muerto-Vivo, approach
        # limit, Back-out, PDU/RPP/STS alarm+SCR, Eaton SOW R-48.
        prompt = PROCEDURE_ARCHITECT_SYSTEM_PROMPT
        assert "LOTO" in prompt
        assert "Vivo-Muerto-Vivo" in prompt
        assert "límite de aproximación restringida" in prompt
        assert "Back-out" in prompt
        assert "historial de alarmas" in prompt
        assert "caja SCR" in prompt
        assert "Eaton" in prompt

    def test_mop_template_adopts_universal_5_point_structure(self):
        # The MOP template body must list all 5 universal sections by
        # name -- this is what the LLM author bases its draft on.
        prompt = PROCEDURE_ARCHITECT_SYSTEM_PROMPT
        # Slice MOP template body (delimited by [TEMPLATE: MOP] and the
        # next template marker).
        start = prompt.index("[TEMPLATE: MOP]")
        end = prompt.index("[TEMPLATE: EOP]")
        mop_body = prompt[start:end]
        assert "Alcance y Objetivo" in mop_body
        assert "Evaluación de Impacto y Riesgos" in mop_body
        assert "Prerrequisitos" in mop_body
        assert "Pasos Secuenciales" in mop_body
        assert "Plan de Reversión" in mop_body
        assert "Cuatro Ojos" in mop_body


def _full_mop(extras: str = "") -> str:
    """Helper: build a MOP that satisfies every base rule + the richer
    rules introduced in Commit 11 (Identificador, Estado Final, Vector,
    MCP Health Check, HOLD POINT, parameterized abort trigger). Tests
    for the new rules append `extras` to verify ONLY the rule under
    test fires."""
    return (
        "# MOP — Standard test\n"
        "## 1. Alcance y Objetivo\n"
        "* Identificador (Tag): UPS-B-TEST\n"
        "* Estado Final Esperado: isolated for maintenance\n"
        "## 2. Evaluación de Impacto y Riesgos\n"
        "* Vector Eléctrico: arc-flash, PPE Cat 2 per CSA Z462-24\n"
        "## 3. Prerrequisitos\n"
        "* LOTO + PTW + Agentes MCP Health Check (Checker ONLINE)\n"
        "## 4. Pasos Secuenciales\n"
        "1. Vivo-Muerto-Vivo before manipulation\n"
        "2. [HOLD POINT] verify sync\n"
        "## 5. Plan de Reversión\n"
        "* Disparador: revert if T > 27 °C for > 60 s\n"
        "* Restauración: cerrar Q2, verificar alarma B7\n"
        + extras
    )


class TestAuditMOPUniversalSections:
    """S-SAFETY-01 — the Universal 5-Point Structure is mandatory.
    Missing ANY of the 5 sections -> hard_stop, and the finding names
    which section is absent."""

    def test_mop_missing_alcance_section_is_hard_stop(self):
        content = (
            "## 2. Riesgos: PPE Cat 2 per CSA Z462-24\n"
            "## 3. Prerrequisitos: LOTO\n"
            "## 4. Secuencia: Vivo-Muerto-Vivo\n"
            "## 5. Reversión: revert\n"
        )
        result = audit_procedure_safety(_draft(DOC_TYPE_MOP, content))
        assert result.verdict == AUDIT_VERDICT_HARD_STOP
        assert any("Alcance" in f for f in result.findings)

    def test_mop_missing_impacto_section_is_hard_stop(self):
        # Tricky: §3 mentions LOTO + PPE + CSA so legacy rules pass, but
        # NO Risk/Impacto/Riesgos section means §2 is absent. Note we
        # use a header that does NOT contain "Riesgos" anywhere in
        # text to isolate the missing-section finding.
        content = (
            "## 1. Alcance: smoke test\n"
            "## 3. Prerrequisitos: PPE Cat 2 per CSA Z462-24 + LOTO\n"
            "## 4. Secuencia: Vivo-Muerto-Vivo\n"
            "## 5. Reversión: revert\n"
        )
        result = audit_procedure_safety(_draft(DOC_TYPE_MOP, content))
        assert result.verdict == AUDIT_VERDICT_HARD_STOP
        assert any("Impacto" in f or "Riesgos" in f for f in result.findings)

    def test_mop_missing_prerrequisitos_section_is_hard_stop(self):
        content = (
            "## 1. Alcance: smoke test\n"
            "## 2. Riesgos: PPE Cat 2 per CSA Z462-24 + LOTO\n"
            "## 4. Pasos: Vivo-Muerto-Vivo\n"
            "## 5. Reversión: revert\n"
        )
        result = audit_procedure_safety(_draft(DOC_TYPE_MOP, content))
        assert result.verdict == AUDIT_VERDICT_HARD_STOP
        assert any("Prerrequisitos" in f for f in result.findings)

    def test_mop_missing_pasos_section_is_hard_stop(self):
        content = (
            "## 1. Alcance: smoke test\n"
            "## 2. Riesgos: PPE Cat 2 per CSA Z462-24\n"
            "## 3. Prerrequisitos: LOTO + Vivo-Muerto-Vivo\n"
            "## 5. Reversión: revert\n"
        )
        result = audit_procedure_safety(_draft(DOC_TYPE_MOP, content))
        assert result.verdict == AUDIT_VERDICT_HARD_STOP
        assert any(
            "Pasos" in f or "Secuencia" in f or "Step-by-Step" in f
            for f in result.findings
        )

    def test_mop_missing_reversion_section_is_hard_stop(self):
        content = (
            "## 1. Alcance: smoke test\n"
            "## 2. Riesgos: PPE Cat 2 per CSA Z462-24\n"
            "## 3. Prerrequisitos: LOTO\n"
            "## 4. Pasos: Vivo-Muerto-Vivo before manipulation\n"
        )
        result = audit_procedure_safety(_draft(DOC_TYPE_MOP, content))
        assert result.verdict == AUDIT_VERDICT_HARD_STOP
        assert any(
            "Reversión" in f or "Back-out" in f or "Rollback" in f
            for f in result.findings
        )

    def test_mop_with_all_5_sections_passes(self):
        result = audit_procedure_safety(_draft(DOC_TYPE_MOP, _full_mop()))
        assert result.verdict == AUDIT_VERDICT_APPROVE
        assert result.findings == []


class TestAuditMOPVoltageVerification:
    """S-SAFETY-01 — at least ONE of voltage absence (de-energized) OR
    approach limit (live work) must be present. Both absent ->
    hard_stop."""

    def test_mop_de_energized_with_vivo_muerto_vivo_passes(self):
        result = audit_procedure_safety(_draft(DOC_TYPE_MOP, _full_mop()))
        assert result.verdict == AUDIT_VERDICT_APPROVE

    def test_mop_live_work_with_approach_limit_passes(self):
        # ATS commutation test pattern: no LOTO, but explicit approach
        # limit + PPE Cat 4 (plus Commit 11 richer fields).
        content = (
            "# MOP — ATS test\n"
            "## 1. Alcance y Objetivo\n"
            "* Identificador (Tag): ATS-A\n"
            "* Estado Final Esperado: commutation validated\n"
            "## 2. Evaluación de Impacto y Riesgos\n"
            "* Vector Eléctrico: Arc Flash Cat 4 per CSA Z462-24.\n"
            "## 3. Prerrequisitos\n"
            "* PPE Cat 4, LOTO not applicable (live work) + PTW.\n"
            "* Agentes Health Check (Checker ONLINE via MCP).\n"
            "## 4. Pasos Secuenciales\n"
            "1. Personnel outside the límite de aproximación "
            "restringida during contactor switching.\n"
            "2. [HOLD POINT] verify generator V/Hz nominal in HMI.\n"
            "## 5. Plan de Reversión\n"
            "* Disparador: force Utility return if generator not "
            "assuming load within 15 s.\n"
            "* Restauración: cerrar manual Utility breaker, verificar "
            "ATS in Utility.\n"
        )
        result = audit_procedure_safety(_draft(DOC_TYPE_MOP, content))
        assert result.verdict == AUDIT_VERDICT_APPROVE

    def test_mop_neither_voltage_nor_approach_is_hard_stop(self):
        content = (
            "# MOP — Bad draft\n"
            "## 1. Alcance: smoke\n"
            "## 2. Riesgos: PPE Cat 2 per CSA Z462-24\n"
            "## 3. Prerrequisitos: LOTO\n"
            "## 4. Pasos: open the door\n"  # no Vivo-Muerto, no approach limit
            "## 5. Reversión: revert\n"
        )
        result = audit_procedure_safety(_draft(DOC_TYPE_MOP, content))
        assert result.verdict == AUDIT_VERDICT_HARD_STOP
        assert any(
            "Vivo-Muerto-Vivo" in f or "approach" in f.lower()
            or "aproximación" in f
            for f in result.findings
        )


class TestAuditMOPDistributionPreTransfer:
    """S-DISTRIBUTION-01 — when context or asset_id names PDU/RPP/STS,
    the body MUST mention alarm history review AND STS/SCR state check."""

    def test_pdu_context_missing_alarm_history_is_hard_stop(self):
        draft = ProcedureDraft(
            draft_id="t",
            doc_type=DOC_TYPE_MOP,
            context="Maintenance window on PDU rack",
            content=_full_mop(
                "## 6. Notes: SCR diagnostics complete\n",  # has SCR, no alarm
            ),
            asset_id=None,
            generated_at=0.0,
            llm_present=True,
        )
        result = audit_procedure_safety(draft)
        assert result.verdict == AUDIT_VERDICT_HARD_STOP
        assert any("alarm history" in f.lower() for f in result.findings)

    def test_sts_context_missing_scr_check_is_hard_stop(self):
        draft = ProcedureDraft(
            draft_id="t",
            doc_type=DOC_TYPE_MOP,
            context="STS load transfer on Path A",
            content=_full_mop(
                "## 6. Notes: alarm history reviewed pre-transfer\n",  # alarm yes, SCR no
            ),
            asset_id=None,
            generated_at=0.0,
            llm_present=True,
        )
        result = audit_procedure_safety(draft)
        assert result.verdict == AUDIT_VERDICT_HARD_STOP
        assert any("SCR" in f for f in result.findings)

    def test_rpp_asset_id_triggers_distribution_rule(self):
        # asset_id alone is enough -- "rpp_a1" matches the pattern.
        draft = ProcedureDraft(
            draft_id="t",
            doc_type=DOC_TYPE_MOP,
            context="Load balancing maintenance",
            content=_full_mop(),  # no alarm, no SCR
            asset_id="rpp_a1",
            generated_at=0.0,
            llm_present=True,
        )
        result = audit_procedure_safety(draft)
        assert result.verdict == AUDIT_VERDICT_HARD_STOP
        assert any("alarm history" in f.lower() for f in result.findings)
        assert any("SCR" in f for f in result.findings)

    def test_pdu_with_alarm_and_scr_passes(self):
        draft = ProcedureDraft(
            draft_id="t",
            doc_type=DOC_TYPE_MOP,
            context="Transferencia de carga en PDU principal",
            content=_full_mop(
                "## 6. Pre-transfer: revisar historial de alarmas + "
                "verificar estado de la caja SCR del STS antes de "
                "autorizar el comando\n",
            ),
            asset_id=None,
            generated_at=0.0,
            llm_present=True,
        )
        result = audit_procedure_safety(draft)
        assert result.verdict == AUDIT_VERDICT_APPROVE

    def test_non_distribution_context_does_not_trigger_rule(self):
        # UPS context, no distribution gear named -> no alarm/SCR
        # check required.
        draft = ProcedureDraft(
            draft_id="t",
            doc_type=DOC_TYPE_MOP,
            context="UPS battery cabinet swap",
            content=_full_mop(),  # has full safety stack, no alarm, no SCR
            asset_id="ups_b",
            generated_at=0.0,
            llm_present=True,
        )
        result = audit_procedure_safety(draft)
        assert result.verdict == AUDIT_VERDICT_APPROVE


class TestAuditMOPEatonVendor:
    """S-VENDOR-EATON-01 — when context or asset_id mentions 'eaton',
    surface BCMS / fiber / FSB / alarm-history omissions as CAUTION
    (not hard_stop). The fleet is multi-brand; hard_stop here would
    refuse legitimate non-Eaton MOPs."""

    def test_eaton_context_missing_bcms_is_caution(self):
        draft = ProcedureDraft(
            draft_id="t",
            doc_type=DOC_TYPE_MOP,
            context="Preventive maintenance on Eaton PDU 9395",
            content=_full_mop(
                "## 6. Pre-transfer: revisar historial de alarmas + "
                "estado de la caja SCR del STS\n",
            ),  # alarm + SCR yes (distribution rule satisfied), BCMS/fiber/FSB no
            asset_id=None,
            generated_at=0.0,
            llm_present=True,
        )
        result = audit_procedure_safety(draft)
        # CAUTION, not hard_stop — the Eaton checks are advisory.
        assert result.verdict == AUDIT_VERDICT_CAUTION
        assert any("Eaton SOW R-48" in f for f in result.findings)
        assert any("BCMS" in f for f in result.findings)

    def test_non_eaton_context_does_not_trigger_eaton_rule(self):
        # Vertiv PDU -- the Eaton check should NOT fire.
        draft = ProcedureDraft(
            draft_id="t",
            doc_type=DOC_TYPE_MOP,
            context="Preventive maintenance on Vertiv PDU",
            content=_full_mop(
                "## 6. Pre-transfer: revisar historial de alarmas + "
                "estado de la caja SCR del STS\n",
            ),
            asset_id=None,
            generated_at=0.0,
            llm_present=True,
        )
        result = audit_procedure_safety(draft)
        assert result.verdict == AUDIT_VERDICT_APPROVE
        assert not any("Eaton" in f for f in result.findings)

    def test_eaton_with_full_sow_checklist_passes(self):
        draft = ProcedureDraft(
            draft_id="t",
            doc_type=DOC_TYPE_MOP,
            context="Mantenimiento preventivo en Eaton PDU 9395",
            content=_full_mop(
                "## 6. SOW R-48 checklist: verificar BCMS + fibra óptica "
                "+ historial de alarmas + evaluar FSBs + aprobación "
                "previa de firmware\n"
                "## 7. Pre-transfer: estado de la caja SCR del STS\n",
            ),
            asset_id=None,
            generated_at=0.0,
            llm_present=True,
        )
        result = audit_procedure_safety(draft)
        assert result.verdict == AUDIT_VERDICT_APPROVE


# ─── Commit 5 — library pre-seed from docs/operaciones/mops/ ──────────
# ─── Commit 11 — richer-prompt audit rules (all CAUTION) ──────────────
def _mop_missing(field: str) -> str:
    """Build a MOP body that is FULL except for one richer-template
    field, to verify each rule fires independently. The base body is
    _full_mop()'s structure inlined; `field` names which line to drop:
    'tag' / 'final' / 'vector' / 'mcp' / 'hold' / 'param'."""
    parts = {
        "tag": "* Identificador (Tag): UPS-X" if field != "tag" else "",
        "final": "* Estado Final Esperado: isolated" if field != "final" else "",
        "vector": "* Vector Eléctrico: arc-flash, PPE Cat 2" if field != "vector" else "* Riesgos: arc-flash, PPE Cat 2",
        "mcp": "* Agentes MCP Health Check (Checker ONLINE)" if field != "mcp" else "* Notification done",
        "hold": "2. [HOLD POINT] verify isolation" if field != "hold" else "2. verify isolation",
        "param": "* Disparador: revert if T > 27 °C for > 60 s" if field != "param" else "* Disparador: revert if it goes wrong",
    }
    return (
        "# MOP — Test\n"
        "## 1. Alcance y Objetivo\n"
        f"{parts['tag']}\n"
        f"{parts['final']}\n"
        "## 2. Evaluación de Impacto y Riesgos\n"
        f"{parts['vector']} per CSA Z462-24\n"
        "## 3. Prerrequisitos\n"
        "* LOTO + PTW\n"
        f"{parts['mcp']}\n"
        "## 4. Pasos Secuenciales\n"
        "1. Apply Vivo-Muerto-Vivo before manipulation\n"
        f"{parts['hold']}\n"
        "## 5. Plan de Reversión\n"
        f"{parts['param']}\n"
        "* Restauración: cerrar Q2, verificar bypass OK\n"
    )


class TestAuditMOPRicherTemplate:
    """Commit 11 -- 6 new CAUTION rules from the operator-supplied
    richer system prompt (Identificador / Estado Final / Vector / MCP
    Health Check / [HOLD POINT] / parameterized abort)."""

    def test_full_richer_mop_is_approve(self):
        result = audit_procedure_safety(_draft(DOC_TYPE_MOP, _full_mop()))
        assert result.verdict == AUDIT_VERDICT_APPROVE
        assert result.findings == []

    def test_missing_tag_is_caution_not_hard_stop(self):
        result = audit_procedure_safety(
            _draft(DOC_TYPE_MOP, _mop_missing("tag")),
        )
        assert result.verdict == AUDIT_VERDICT_CAUTION
        assert any("Identificador" in f or "Tag" in f for f in result.findings)

    def test_missing_final_state_is_caution(self):
        result = audit_procedure_safety(
            _draft(DOC_TYPE_MOP, _mop_missing("final")),
        )
        assert result.verdict == AUDIT_VERDICT_CAUTION
        assert any("Estado Final" in f for f in result.findings)

    def test_missing_vector_is_caution(self):
        result = audit_procedure_safety(
            _draft(DOC_TYPE_MOP, _mop_missing("vector")),
        )
        assert result.verdict == AUDIT_VERDICT_CAUTION
        assert any("vector" in f.lower() for f in result.findings)

    def test_missing_mcp_health_check_is_caution(self):
        result = audit_procedure_safety(
            _draft(DOC_TYPE_MOP, _mop_missing("mcp")),
        )
        assert result.verdict == AUDIT_VERDICT_CAUTION
        assert any("MCP" in f or "Agentes" in f for f in result.findings)

    def test_missing_hold_point_is_caution(self):
        result = audit_procedure_safety(
            _draft(DOC_TYPE_MOP, _mop_missing("hold")),
        )
        assert result.verdict == AUDIT_VERDICT_CAUTION
        assert any("HOLD POINT" in f for f in result.findings)

    def test_missing_parameterized_abort_is_hard_stop(self):
        # Commit 12: promoted from CAUTION to HARD_STOP. Vague abort
        # criteria ("if it goes wrong") block signing -- safety-
        # critical contract.
        result = audit_procedure_safety(
            _draft(DOC_TYPE_MOP, _mop_missing("param")),
        )
        assert result.verdict == AUDIT_VERDICT_HARD_STOP
        assert any("REFUSAL" in f and "parameterized" in f.lower()
                   for f in result.findings)

    def test_all_richer_rules_simultaneously_missing_is_hard_stop(self):
        # With parameterized-abort now a HARD_STOP rule, missing every
        # richer field results in HARD_STOP (the param rule alone is
        # sufficient to block). The other 5 rules surface as caution
        # findings alongside.
        body = (
            "# MOP — Sparse\n"
            "## 1. Alcance y Objetivo\nGeneric scope.\n"  # no Tag, no Final
            "## 2. Riesgos: arc-flash, PPE Cat 2 per CSA Z462-24.\n"
            "## 3. Prerrequisitos: LOTO + PTW.\n"
            "## 4. Pasos: Apply Vivo-Muerto-Vivo.\n"  # no [HOLD POINT]
            "## 5. Plan de Reversión: revert if it goes wrong.\n"  # no number
        )
        result = audit_procedure_safety(_draft(DOC_TYPE_MOP, body))
        assert result.verdict == AUDIT_VERDICT_HARD_STOP
        # The 5 OTHER richer advisories still fire as findings (just
        # not as hard_stop contributors); plus the param REFUSAL.
        advisory_count = sum(
            1 for f in result.findings
            if "richer-template" in f
        )
        assert advisory_count >= 5


class TestSeedArchitectLibraryFromCatalog:
    """The _seed_architect_library_from_catalog helper parses every
    MOP-*.md in docs/operaciones/mops/ and appends to the in-memory
    Architect library with source='catalog'. Audit gate is applied to
    every seed; failures are logged + skipped (defence in depth)."""

    def test_seed_loads_canonical_mops_from_real_dir(self):
        from backend.procedure_routes import (
            _architect_library,
            _reset_architect_library_for_test,
            _seed_architect_library_from_catalog,
        )
        _reset_architect_library_for_test()
        count = _seed_architect_library_from_catalog()
        # 23 canonical bodies after Commits 1-8 (infrastructure 3 +
        # distribution 9 + mechanical 9 + global 2).
        assert count == 23
        # The original 3 categories MUST still be present; the full
        # set extends with the distribution + mechanical + global
        # categories.
        cats = set(e["category"] for e in _architect_library)
        assert {"ats", "transformer", "ups"}.issubset(cats)
        assert {"sts", "pdu", "rpp", "busway"}.issubset(cats)
        assert {"chiller", "crah", "tower"}.issubset(cats)
        for e in _architect_library:
            assert e["source"] == "catalog"
            assert e["operator_id"] == "catalog"
            assert e["actor_role"] == "system"
            assert e["doc_type"] == "MOP"
            # Commit 12: all 23 seed bodies are richer-template
            # compliant -- audit must return APPROVE.
            assert e["audit_verdict"] == AUDIT_VERDICT_APPROVE
            assert e["source_file"].startswith("MOP-")
            assert e["source_file"].endswith(".md")
            assert e["title"].startswith("MOP-")
            assert len(e["content_sha256"]) == 64

    def test_seed_skips_files_that_fail_audit(self, tmp_path):
        from backend.procedure_routes import (
            _architect_library,
            _reset_architect_library_for_test,
            _seed_architect_library_from_catalog,
        )
        # Write a synthetic catalog with one PASSING + one FAILING body.
        # Commit 12 promoted parameterized-abort to HARD_STOP, so the
        # "good" stub must include a numeric+unit trigger to avoid
        # blocking. Caution-level richer fields (Tag / Estado Final /
        # Vector / MCP / HOLD POINT) are missing -- they surface as
        # caution but DO NOT block the load.
        (tmp_path / "MOP-100-good-stub.md").write_text(
            "# Good seed\n## 1. Alcance: x\n"
            "## 2. Riesgos: PPE Cat 2 per CSA Z462-24\n"
            "## 3. Prerrequisitos: LOTO\n"
            "## 4. Pasos: Vivo-Muerto-Vivo\n"
            "## 5. Reversión: revert if T > 27 °C for > 60 s\n",
            encoding="utf-8",
        )
        (tmp_path / "MOP-101-bad-stub.md").write_text(
            "# Bad seed -- missing everything\nGo do the thing.\n",
            encoding="utf-8",
        )
        _reset_architect_library_for_test()
        count = _seed_architect_library_from_catalog(tmp_path)
        # Only the good body lands; the bad one is skipped (logged).
        assert count == 1
        assert len(_architect_library) == 1
        assert _architect_library[0]["source_file"] == "MOP-100-good-stub.md"
        assert _architect_library[0]["category"] == "good"

    def test_seed_returns_zero_when_dir_missing(self, tmp_path):
        from backend.procedure_routes import (
            _reset_architect_library_for_test,
            _seed_architect_library_from_catalog,
        )
        _reset_architect_library_for_test()
        count = _seed_architect_library_from_catalog(tmp_path / "nope")
        assert count == 0


class TestArchitectLibraryFilter:
    """GET /api/procedures/architect/library?source=... must filter the
    list to either pre-seeded catalog entries or operator-signed drafts.
    Default (no source) returns the merged view."""

    def test_library_default_returns_all_entries(self, library_client):
        from backend.procedure_routes import (
            _seed_architect_library_from_catalog,
        )
        # Seed catalog entries (23 after Commits 1-8).
        seeded = _seed_architect_library_from_catalog()
        assert seeded == 23
        # Operator-sign one extra to the library.
        r = library_client.post(
            "/api/procedures/architect/save-to-library",
            json={
                "draft_id": "qd-extra",
                "doc_type": "MOP",
                "content": SAFE_MOP_CONTENT,
                "asset_id": "ups_b",
                "operator_id": "wilmer.angel",
                "actor_role": "SME_L6",
            },
        )
        assert r.status_code == 200
        # Default (no source filter) -> seeded + 1 signed = 24.
        r2 = library_client.get("/api/procedures/architect/library?limit=100")
        body = r2.json()
        assert body["total"] == 24
        assert body["source_filter"] is None
        assert len(body["items"]) == 24

    def test_library_filter_source_catalog_returns_only_seeds(self, library_client):
        from backend.procedure_routes import (
            _seed_architect_library_from_catalog,
        )
        seeded = _seed_architect_library_from_catalog()
        # Add a signed entry too.
        library_client.post(
            "/api/procedures/architect/save-to-library",
            json={
                "draft_id": "qd-signed-x",
                "doc_type": "MOP",
                "content": SAFE_MOP_CONTENT,
                "asset_id": "ups_b",
                "operator_id": "wilmer.angel",
            },
        )
        r = library_client.get(
            "/api/procedures/architect/library?source=catalog&limit=100",
        )
        body = r.json()
        assert body["total"] == seeded
        assert body["source_filter"] == "catalog"
        for item in body["items"]:
            assert item["source"] == "catalog"

    def test_library_filter_source_signed_returns_only_signed(self, library_client):
        from backend.procedure_routes import (
            _seed_architect_library_from_catalog,
        )
        _seed_architect_library_from_catalog()
        library_client.post(
            "/api/procedures/architect/save-to-library",
            json={
                "draft_id": "qd-signed-y",
                "doc_type": "MOP",
                "content": SAFE_MOP_CONTENT,
                "asset_id": "ups_b",
                "operator_id": "wilmer.angel",
            },
        )
        r = library_client.get(
            "/api/procedures/architect/library?source=signed",
        )
        body = r.json()
        assert body["total"] == 1
        assert body["source_filter"] == "signed"
        assert body["items"][0]["source"] == "signed"
        assert body["items"][0]["draft_id"] == "qd-signed-y"


class TestSeedMOPsPassNewAuditGate:
    """The 3 docs/operaciones/mops/MOP-*.md seed files must pass the
    full hardened audit gate -- they will be pre-seeded into the
    library on boot (Commit 5) and must not surface as hard_stop."""

    @pytest.mark.parametrize("filename,asset_id,context_hint", [
        ("MOP-001-ups-bypass-transfer.md",     "ups_b",  "UPS bypass transfer to maintenance"),
        ("MOP-002-transformer-dry-inspection.md", "xfmr_a", "dry-type transformer inspection"),
        ("MOP-003-ats-commutation-test.md",    None,    "ATS commutation test"),
    ])
    def test_seed_mop_passes_audit(self, filename, asset_id, context_hint):
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[1]
        seed_path = repo_root / "docs" / "operaciones" / "mops" / filename
        assert seed_path.exists(), f"seed file missing: {seed_path}"
        content = seed_path.read_text(encoding="utf-8")
        draft = ProcedureDraft(
            draft_id="seed",
            doc_type=DOC_TYPE_MOP,
            context=context_hint,
            content=content,
            asset_id=asset_id,
            generated_at=0.0,
            llm_present=False,
        )
        result = audit_procedure_safety(draft)
        # Commit 12: all 23 seed bodies have been upgraded to the
        # full richer-template structure (Identificador / Estado
        # Final / Vector / MCP Health Check / [HOLD POINT] /
        # parameterized abort). Verdict must be APPROVE.
        assert result.verdict == AUDIT_VERDICT_APPROVE, (
            f"seed {filename} did NOT pass full audit: "
            f"verdict={result.verdict}, findings={result.findings}"
        )


# ─── /api/procedures/architect/generate route ────────────────────────
@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(procedure_router)
    # Wire a fresh ForensicLedger so /sign can land entries.
    app.state.forensic_ledger = ForensicLedger(
        InMemoryPersistence(),
        key=secrets.token_bytes(32),
        key_version=1,
    )
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_architect_generate_happy_path_returns_draft_plus_audit(client):
    r = client.post(
        "/api/procedures/architect/generate",
        json={
            "doc_type": "SOP",
            "context": "Daily round of UPS room — verify BMS setpoints.",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "draft" in body
    assert "safety_audit" in body
    assert body["draft"]["doc_type"] == "SOP"
    assert body["draft"]["llm_present"] is False  # no LLM wired in test app
    # SOP skeleton has "_TBD_ (BMS / HMI verification)" so the audit
    # finds the BMS/HMI term and rules approve.
    assert body["safety_audit"]["verdict"] == AUDIT_VERDICT_APPROVE


def test_architect_generate_mop_skeleton_emits_hard_stop(client):
    """The load-bearing E2E test: a MOP without LOTO/PPE/CSA Z462
    surfaces as ``safety_audit.verdict == hard_stop`` through the
    HTTP boundary. This is what the HMI uses to refuse the Sign
    button."""
    r = client.post(
        "/api/procedures/architect/generate",
        json={
            "doc_type": "MOP",
            "context": "Replace UPS battery cabinet on B-side",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["safety_audit"]["verdict"] == AUDIT_VERDICT_HARD_STOP
    findings = body["safety_audit"]["findings"]
    assert any("LOTO" in f for f in findings)
    assert any("PPE" in f for f in findings)
    assert any("CSA Z462" in f for f in findings)


def test_architect_generate_rejects_invalid_doc_type(client):
    r = client.post(
        "/api/procedures/architect/generate",
        json={"doc_type": "BANANA", "context": "x" * 50},
    )
    assert r.status_code == 422  # Pydantic regex pattern mismatch


def test_architect_generate_rejects_short_context(client):
    r = client.post(
        "/api/procedures/architect/generate",
        json={"doc_type": "SOP", "context": "x"},
    )
    assert r.status_code == 422  # min_length=10


# ─── /api/procedures/architect/sign route ────────────────────────────
def test_architect_sign_hard_stop_returns_403(client):
    """A MOP without the safety terms cannot be signed even if the
    HMI tried to bypass — the server re-audits, defence in depth."""
    r = client.post(
        "/api/procedures/architect/sign",
        json={
            "draft_id": "qd-x",
            "doc_type": "MOP",
            "content": "# MOP\nSome unsafe content.\n",
            "operator_id": "wilmer.angel",
            "actor_role": "SME_L6",
        },
    )
    assert r.status_code == 403
    assert "HARD_STOP" in r.json()["detail"]


def test_architect_sign_approved_sop_lands_in_ledger(client, app):
    """SOP/EOP/EMP follow the single-sign path — one approved sign
    creates the PROCEDURE_SIGNED ledger entry directly. MOP is the
    only doc_type that requires the Maker-Checker witness gate."""
    safe_sop = "Daily round. Verify BMS setpoints are within tolerance."
    r = client.post(
        "/api/procedures/architect/sign",
        json={
            "draft_id": "qd-sop",
            "doc_type": "SOP",
            "content": safe_sop,
            "operator_id": "wilmer.angel",
            "actor_role": "SME_L6",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["signed"] is True
    assert body["witness_required"] is False
    assert body["safety_audit_verdict"] == AUDIT_VERDICT_APPROVE
    # The ledger has exactly one PROCEDURE_SIGNED entry, single signer.
    import asyncio as _aio
    entries = _aio.run(app.state.forensic_ledger.fetch_all())
    signed = [e for e in entries if e.action == "PROCEDURE_SIGNED"]
    assert len(signed) == 1
    assert signed[0].payload["witness_required"] is False
    assert signed[0].actor == "wilmer.angel"
    assert signed[0].payload["content_sha256"] == hashlib.sha256(
        safe_sop.encode("utf-8"),
    ).hexdigest()


def test_architect_sign_503_when_ledger_unwired():
    """No ForensicLedger on app.state -> service unavailable."""
    app_no_ledger = FastAPI()
    app_no_ledger.include_router(procedure_router)
    client_nl = TestClient(app_no_ledger)
    r = client_nl.post(
        "/api/procedures/architect/sign",
        json={
            "draft_id": "qd-x",
            "doc_type": "SOP",
            "content": "Daily round. Verify BMS setpoints.",
            "operator_id": "op",
        },
    )
    assert r.status_code == 503


# ════════════════════════════════════════════════════════════════════
# Industry-notes follow-up — metadata enrichment
# ════════════════════════════════════════════════════════════════════
class TestGenerateMetadataEnrichment:
    @pytest.mark.asyncio
    async def test_no_metadata_keeps_skeleton_path_clean(self):
        """Back-compat: omitting metadata changes nothing for the
        deterministic-skeleton fallback. The 28 existing tests pinned
        the no-metadata path; this re-asserts it."""
        agent = ProcedureArchitectAgent()
        draft = await agent.generate(
            doc_type="SOP", context="Daily round of UPS room.",
        )
        assert draft.metadata == {}
        # Skeleton content is unchanged (no metadata block leaks in).
        assert "LIVE OPERATING METADATA" not in draft.content

    @pytest.mark.asyncio
    async def test_metadata_persists_on_returned_draft(self):
        agent = ProcedureArchitectAgent()
        meta = {"pue": 1.32, "load_kw": 14200, "criticality": "high"}
        draft = await agent.generate(
            doc_type="SOP", context="Daily round of UPS room.",
            metadata=meta,
        )
        # The returned draft carries the snapshot — round-trip-safe
        # for the ledger entry that later audits which telemetry the
        # document was grounded in.
        assert draft.metadata == meta

    @pytest.mark.asyncio
    async def test_metadata_flows_into_hermetic_prompt(self):
        gemma = _FakeGemma(reply="## test draft body")
        agent = ProcedureArchitectAgent(llm_client=gemma)
        meta = {
            "pue": 1.32,
            "load_kw": 14200,
            "criticality": "high",
            "battery_runtime_min": 7.2,
        }
        await agent.generate(
            doc_type="MOP",
            context="Replace UPS-B battery cabinet on Phase 1 bus.",
            metadata=meta,
        )
        assert len(gemma.prompts) == 1
        p = gemma.prompts[0]
        # The labelled block is present.
        assert "LIVE OPERATING METADATA" in p
        # Every key surfaces; values stringify on a single line.
        for k, v in meta.items():
            assert f"{k}: {v}" in p

    @pytest.mark.asyncio
    async def test_metadata_block_keys_are_sorted_for_determinism(self):
        """The prompt body must be deterministic given the same input
        — Python dict iteration order is insertion-order but operators
        may pass keys in any order. Sorting pins the prompt bytes
        across runs (helps cache + reproducible LLM costs)."""
        gemma = _FakeGemma(reply="x")
        agent = ProcedureArchitectAgent(llm_client=gemma)
        await agent.generate(
            doc_type="SOP", context="round of ups_a",
            metadata={"zeta": 1, "alpha": 2, "mu": 3},
        )
        p = gemma.prompts[0]
        # Alpha comes before mu comes before zeta.
        a_idx = p.index("alpha: 2")
        m_idx = p.index("mu: 3")
        z_idx = p.index("zeta: 1")
        assert a_idx < m_idx < z_idx

    @pytest.mark.asyncio
    async def test_metadata_rejects_non_dict(self):
        agent = ProcedureArchitectAgent()
        with pytest.raises(ArtifactDependencyError, match="metadata"):
            await agent.generate(
                doc_type="SOP", context="x" * 50,
                metadata="not a dict",  # type: ignore[arg-type]
            )

    def test_route_accepts_metadata_field(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from backend.procedure_routes import router as procedure_router

        app = FastAPI()
        app.include_router(procedure_router)
        client = TestClient(app)
        r = client.post(
            "/api/procedures/architect/generate",
            json={
                "doc_type": "SOP",
                "context": "Daily round with current pue snapshot.",
                "asset_id": "ups_a",
                "metadata": {"pue": 1.32, "load_kw": 14200},
            },
        )
        assert r.status_code == 200
        body = r.json()
        # Metadata round-trips into the draft for the ledger audit.
        assert body["draft"]["metadata"] == {"pue": 1.32, "load_kw": 14200}


# ════════════════════════════════════════════════════════════════════
# S-DET-01 binding — audit_procedure_safety is LLM-free
# ════════════════════════════════════════════════════════════════════
def test_audit_procedure_safety_imports_no_llm_modules():
    """Scoped AST gate (industry-notes follow-up). The audit function
    is the deterministic verdict gate every Architect draft crosses —
    a future PR that pulls LLM grading into the audit erodes the
    ADR-006 deterministic-sandbox guarantee. This test fails LOUDLY
    in that case.

    Note: the test is scoped to the audit FUNCTION body, NOT the
    whole module. The module DOES legitimately call the LLM via
    ``ProcedureArchitectAgent.generate()`` — that's the authoring
    path. Only the verdict path must stay LLM-free. Same enforcement
    pattern as ``test_simulate_setpoint_impact_imports_no_llm_module``
    in tests/test_optimizer.py."""
    import re
    from pathlib import Path

    from backend.agents import procedure_architect as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    # Carve out the audit function's body — from "def
    # audit_procedure_safety" to the next top-level def or EOF.
    pat = re.compile(
        r"def audit_procedure_safety\b.*?(?=\n(?:def |class )|\Z)",
        re.S,
    )
    m = pat.search(src)
    assert m is not None, "audit_procedure_safety() not found"
    body = m.group(0)
    for needle in (
        "complete_gemma",
        "_llm_client",
        "self._llm_client",
        "openai",
        "anthropic",
        "client.chat",
        "await llm",
    ):
        assert needle not in body, (
            f"audit_procedure_safety() must be LLM-free (S-DET-01 / "
            f"ADR-006 deterministic sandbox); found {needle!r} in its "
            "body. The audit verdict is the gate every Architect draft "
            "crosses before reaching the operator — an LLM-graded "
            "verdict would erode the deterministic guarantee."
        )


# ════════════════════════════════════════════════════════════════════
# Epic 6 Sprint 3 Phase 4 — Maker-Checker witness gate on MOP sign
# ════════════════════════════════════════════════════════════════════
SAFE_MOP_CONTENT = (
    # Updated for Commit 11 (operator mandate 2026-05-24): the MOP
    # must satisfy BOTH the original 5-Point Universal contract AND
    # the new richer-template structural rules (Identificador / Estado
    # Final / Vector / MCP Health Check / [HOLD POINT] / parameterized
    # abort trigger) so the audit returns APPROVE (not CAUTION).
    "# MOP — Replace UPS battery cabinet\n"
    "## 1. Alcance y Objetivo\n"
    "* Identificador (Tag): UPS-B\n"
    "* Estado Final Esperado: battery cabinet replaced + isolated\n"
    "## 2. Evaluación de Impacto y Riesgos\n"
    "* Vector Eléctrico: arc-flash; PPE category 2 per CSA Z462-24.\n"
    "## 3. Prerrequisitos\n"
    "* LOTO -- lock breaker UPS-B-MAIN before any work.\n"
    "* Agentes Health Check (Checker ONLINE via MCP).\n"
    "## 4. Pasos Secuenciales\n"
    "1. Vivo-Muerto-Vivo verification on the isolated bus before "
    "manipulation.\n"
    "2. [HOLD POINT] verify ATD on the secondary loop.\n"
    "## 5. Plan de Reversión / Back-out\n"
    "* Disparador: revert if battery_runtime_min < 4 min during "
    "transfer.\n"
    "* Restauración: cerrar Q2 (MIB), verificar alarma 'BYPASS OK'.\n"
)


@pytest.fixture
def mop_app():
    """Fresh app + reset pending MOP signature store per test."""
    from backend.procedure_routes import _reset_pending_mop_signatures_for_test
    _reset_pending_mop_signatures_for_test()
    app = FastAPI()
    app.include_router(procedure_router)
    app.state.forensic_ledger = ForensicLedger(
        InMemoryPersistence(),
        key=secrets.token_bytes(32),
        key_version=1,
    )
    return app


@pytest.fixture
def mop_client(mop_app):
    return TestClient(mop_app)


def _sign_payload(draft_id, content, operator, role="SME_L6"):
    return {
        "draft_id": draft_id, "doc_type": "MOP",
        "content": content, "asset_id": "ups_b",
        "operator_id": operator, "actor_role": role,
    }


class TestMakerCheckerWitnessGate:
    def test_mop_first_sign_returns_202_awaiting(self, mop_client):
        """The maker's signature MUST NOT land in the ledger by
        itself — the checker has to corroborate first."""
        r = mop_client.post(
            "/api/procedures/architect/sign",
            json=_sign_payload("qd-mop-1", SAFE_MOP_CONTENT, "maker.alice"),
        )
        assert r.status_code == 202
        body = r.json()
        assert body["signed"] is False
        assert body["status"] == "awaiting_second_signature"
        assert body["first_signer"] == "maker.alice"
        assert body["witness_required"] is True
        assert "Maker-Checker" in body["message"]

    def test_mop_first_sign_does_not_touch_ledger(self, mop_client, mop_app):
        import asyncio as _aio
        mop_client.post(
            "/api/procedures/architect/sign",
            json=_sign_payload("qd-mop-1a", SAFE_MOP_CONTENT, "maker.alice"),
        )
        entries = _aio.run(mop_app.state.forensic_ledger.fetch_all())
        signed = [e for e in entries if e.action == "PROCEDURE_SIGNED"]
        assert len(signed) == 0

    def test_mop_second_sign_by_different_op_seals_the_entry(self, mop_client, mop_app):
        # Maker
        r1 = mop_client.post(
            "/api/procedures/architect/sign",
            json=_sign_payload("qd-mop-2", SAFE_MOP_CONTENT, "maker.alice"),
        )
        assert r1.status_code == 202
        # Checker (different operator)
        r2 = mop_client.post(
            "/api/procedures/architect/sign",
            json=_sign_payload("qd-mop-2", SAFE_MOP_CONTENT, "checker.bob"),
        )
        assert r2.status_code == 200
        body = r2.json()
        assert body["signed"] is True
        assert body["witness_required"] is True
        assert body["first_signer"] == "maker.alice"
        assert body["second_signer"] == "checker.bob"

        # Ledger has ONE entry naming both signers + the canonical
        # actor (checker) on the row.
        import asyncio as _aio
        entries = _aio.run(mop_app.state.forensic_ledger.fetch_all())
        signed = [e for e in entries if e.action == "PROCEDURE_SIGNED"]
        assert len(signed) == 1
        p = signed[0].payload
        assert p["doc_type"] == "MOP"
        assert p["witness_required"] is True
        assert p["first_signer"] == "maker.alice"
        assert p["second_signer"] == "checker.bob"
        assert signed[0].actor == "checker.bob"
        # Content sha matches input
        assert p["content_sha256"] == hashlib.sha256(
            SAFE_MOP_CONTENT.encode("utf-8"),
        ).hexdigest()

    def test_mop_second_sign_by_same_operator_is_refused_403(self, mop_client):
        # Maker
        mop_client.post(
            "/api/procedures/architect/sign",
            json=_sign_payload("qd-mop-self", SAFE_MOP_CONTENT, "maker.alice"),
        )
        # Same operator attempts the witness signature
        r = mop_client.post(
            "/api/procedures/architect/sign",
            json=_sign_payload("qd-mop-self", SAFE_MOP_CONTENT, "maker.alice"),
        )
        assert r.status_code == 403
        assert "Maker-Checker violation" in r.json()["detail"]
        assert "self-witness ban" in r.json()["detail"]

    def test_mop_second_sign_with_drifted_content_is_refused_409(self, mop_client):
        # Maker signs version A
        mop_client.post(
            "/api/procedures/architect/sign",
            json=_sign_payload("qd-mop-drift", SAFE_MOP_CONTENT, "maker.alice"),
        )
        # Checker attempts to seal a DIFFERENT body — must be refused.
        tampered = SAFE_MOP_CONTENT + "\nAdditional step inserted after maker signed.\n"
        r = mop_client.post(
            "/api/procedures/architect/sign",
            json=_sign_payload("qd-mop-drift", tampered, "checker.bob"),
        )
        assert r.status_code == 409
        assert "content drift" in r.json()["detail"]

    def test_mop_second_sign_must_pass_safety_audit_too(self, mop_client):
        # Maker signs a safe MOP body
        mop_client.post(
            "/api/procedures/architect/sign",
            json=_sign_payload("qd-mop-audit", SAFE_MOP_CONTENT, "maker.alice"),
        )
        # Checker tries to "fix" by submitting unsafe content (missing
        # LOTO/PPE/CSA) — server re-audits, refuses with 403 before
        # the witness gate even runs.
        unsafe = "# MOP\nGo do the thing.\n"
        r = mop_client.post(
            "/api/procedures/architect/sign",
            json=_sign_payload("qd-mop-audit", unsafe, "checker.bob"),
        )
        assert r.status_code == 403
        assert "HARD_STOP" in r.json()["detail"]

    def test_sop_does_not_require_witness(self, mop_client):
        """Sanity — only MOPs trigger the Maker-Checker gate. SOP/EOP/
        EMP retain the single-sign path."""
        r = mop_client.post(
            "/api/procedures/architect/sign",
            json={
                "draft_id": "qd-sop", "doc_type": "SOP",
                "content": "Daily round. Verify BMS setpoints.",
                "operator_id": "maker.alice", "actor_role": "SME_L6",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["signed"] is True
        assert body["witness_required"] is False

    def test_mop_pending_state_isolated_per_draft_id(self, mop_client):
        """Two concurrent MOPs awaiting witness must not cross-talk —
        the pending store is keyed by draft_id."""
        mop_client.post(
            "/api/procedures/architect/sign",
            json=_sign_payload("qd-A", SAFE_MOP_CONTENT, "maker.alice"),
        )
        mop_client.post(
            "/api/procedures/architect/sign",
            json=_sign_payload("qd-B", SAFE_MOP_CONTENT, "maker.carol"),
        )
        # Bob signs qd-A as checker -> qd-A seals, qd-B stays pending.
        r_a = mop_client.post(
            "/api/procedures/architect/sign",
            json=_sign_payload("qd-A", SAFE_MOP_CONTENT, "checker.bob"),
        )
        assert r_a.status_code == 200
        # qd-B still needs its own checker.
        r_b_self = mop_client.post(
            "/api/procedures/architect/sign",
            json=_sign_payload("qd-B", SAFE_MOP_CONTENT, "maker.carol"),
        )
        assert r_b_self.status_code == 403
        # Different operator (dave) seals qd-B.
        r_b = mop_client.post(
            "/api/procedures/architect/sign",
            json=_sign_payload("qd-B", SAFE_MOP_CONTENT, "checker.dave"),
        )
        assert r_b.status_code == 200
        assert r_b.json()["first_signer"] == "maker.carol"
        assert r_b.json()["second_signer"] == "checker.dave"


# ════════════════════════════════════════════════════════════════════
# Epic 6 Option A — save-to-library endpoint
# ════════════════════════════════════════════════════════════════════
@pytest.fixture
def library_client(mop_app):
    """Reuses mop_app fixture which already wires the ForensicLedger
    + resets the pending MOP signature dict. Also resets the
    Architect library so each test starts clean."""
    from backend.procedure_routes import _reset_architect_library_for_test
    _reset_architect_library_for_test()
    return TestClient(mop_app)


class TestArchitectSaveToLibrary:
    def test_safe_mop_saves_returns_library_id_and_size(self, library_client):
        r = library_client.post(
            "/api/procedures/architect/save-to-library",
            json={
                "draft_id": "qd-lib-1",
                "doc_type": "MOP",
                "content": SAFE_MOP_CONTENT,
                "asset_id": "ups_b",
                "operator_id": "wilmer.angel",
                "actor_role": "SME_L6",
                "ledger_entry_id": "fake-entry-id-001",
                "title": "Replace UPS-B battery cabinet",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["saved"] is True
        assert body["draft_id"] == "qd-lib-1"
        assert body["title"] == "Replace UPS-B battery cabinet"
        assert body["audit_verdict"] == AUDIT_VERDICT_APPROVE
        assert body["library_size"] == 1
        assert body["content_sha256"] == hashlib.sha256(
            SAFE_MOP_CONTENT.encode("utf-8"),
        ).hexdigest()

    def test_default_title_when_none_supplied(self, library_client):
        r = library_client.post(
            "/api/procedures/architect/save-to-library",
            json={
                "draft_id": "qd-notitle-aaaaaaaa",
                "doc_type": "SOP",
                "content": "Daily round. Verify BMS setpoints.",
                "asset_id": "chiller_1",
                "operator_id": "op",
            },
        )
        assert r.status_code == 200
        # Default title format: "{doc_type} — {asset_id} ({draft_id_8})"
        assert r.json()["title"] == "SOP — chiller_1 (qd-notit)"

    def test_hard_stop_content_refused_with_403(self, library_client):
        """A hostile HMI cannot stash an unsafe MOP in the library by
        skipping the audit gate — server re-audits on save."""
        r = library_client.post(
            "/api/procedures/architect/save-to-library",
            json={
                "draft_id": "qd-unsafe",
                "doc_type": "MOP",
                "content": "# MOP\nGo do the thing.\n",
                "operator_id": "wilmer.angel",
            },
        )
        assert r.status_code == 403
        assert "hard_stop" in r.json()["detail"].lower()

    def test_library_list_returns_newest_first(self, library_client):
        for i in range(3):
            library_client.post(
                "/api/procedures/architect/save-to-library",
                json={
                    "draft_id": f"qd-list-{i}",
                    "doc_type": "SOP",
                    "content": "Verify BMS setpoints (entry " + str(i) + ").",
                    "operator_id": "op",
                },
            )
        r = library_client.get("/api/procedures/architect/library")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 3
        assert [it["draft_id"] for it in body["items"]] == [
            "qd-list-2", "qd-list-1", "qd-list-0",
        ]

    def test_library_list_respects_limit(self, library_client):
        for i in range(5):
            library_client.post(
                "/api/procedures/architect/save-to-library",
                json={
                    "draft_id": f"qd-lim-{i}", "doc_type": "SOP",
                    "content": "Verify BMS.", "operator_id": "op",
                },
            )
        r = library_client.get("/api/procedures/architect/library?limit=2")
        body = r.json()
        assert body["total"] == 5
        assert len(body["items"]) == 2

    def test_library_empty_returns_empty_items(self, library_client):
        r = library_client.get("/api/procedures/architect/library")
        assert r.status_code == 200
        body = r.json()
        # Commit 5 added source_filter to the response envelope.
        assert body["items"] == []
        assert body["total"] == 0
        assert body["source_filter"] is None


# ════════════════════════════════════════════════════════════════════
# Epic 6 Option A — /api/mops/generate is gone (HTTP 410)
# ════════════════════════════════════════════════════════════════════
def test_legacy_mops_generate_returns_410_gone():
    """The deprecated endpoint MUST return 410 Gone with a migration
    detail pointing at the Architect successor."""
    # main is importable as a top-level module via the sys.path shim
    # in tests/test_smoke.py — replay the same insertion here so this
    # test doesn't depend on smoke being collected first.
    import pathlib
    import sys

    project_root = pathlib.Path(__file__).resolve().parent.parent
    backend_path = str(project_root / "backend")
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    from main import app as main_app

    test_client = TestClient(main_app)
    try:
        r = test_client.post(
            "/api/mops/generate",
            json={"topic": "any", "doc_type": "MOP"},
        )
        assert r.status_code == 410
        body = r.json()["detail"]
        assert body["error"] == "endpoint_removed"
        assert body["successor"] == "POST /api/procedures/architect/generate"
        assert "Safety Officer" in body["message"]
    finally:
        test_client.close()
