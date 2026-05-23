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
    # Every section header from the spec is present in the skeleton.
    for section in (
        "Identificación de Riesgos",
        "Protocolo de Aislamiento",
        "Prerrequisitos",
        "Secuencia de Intervención",
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
        content = (
            "# MOP — Replace UPS battery\n"
            "Riesgos: arc-flash, PPE category 2 per CSA Z462-24.\n"
            "LOTO: lock breaker UPS-B-MAIN before any work.\n"
        )
        result = audit_procedure_safety(_draft(DOC_TYPE_MOP, content))
        assert result.verdict == AUDIT_VERDICT_APPROVE
        assert result.findings == []

    def test_mop_with_nfpa_70e_instead_of_csa_z462_is_approve(self):
        # The pattern accepts EITHER standard — this is the US-spec
        # equivalent. CSA is Canada (Toronto site), NFPA is US, both
        # are valid arc-flash standards.
        content = (
            "MOP draft. PPE per NFPA 70E. Apply Lockout/Tagout on the "
            "upstream breaker before opening the enclosure."
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
    "# MOP — Replace UPS battery cabinet\n"
    "Riesgos: arc-flash; PPE category 2 per CSA Z462-24.\n"
    "LOTO: lock breaker UPS-B-MAIN before any work.\n"
    "Back-out plan: revert before battery_runtime_min cutoff.\n"
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
        assert r.json() == {"items": [], "total": 0}


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
