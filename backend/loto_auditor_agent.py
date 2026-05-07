"""
backend/loto_auditor_agent.py
==============================
LOTO Auditor Agent (Batch 4 V9 Pillar 4 deliverable - SKELETON).

This module defines the LotoAuditorAgent class. The skeleton phase
(Batch 4.A) provides:

- Orchestration logic for the 6-pillar audit pipeline
- Provenance tracing (sources_consulted)
- Latency profiling (decision_time_ms)
- Pillar method stubs that raise NotImplementedError

Batch 4.B will implement Pillars 1+2+3 (topology, redundancy, caps).
Batch 4.C will implement Pillars 4+5+6 (witness, order, PPE).
Batch 4.D will add the FastAPI endpoint and report renderer.

Per ADR-006 (Deterministic Sandbox):
- Agent has read-only authority over all subsystems
- Reports are always created in pending_approval state
- No autonomous state transition is permitted
- Report persistence requires explicit CET acknowledgment via
  witness_engine

Standards cited in audit reports:
- NFPA 70E Section 130
- CSA Z462-24 (Ontario jurisdiction)
- Ontario Electrical Safety Code 28th Edition
- NEC 460.6
- IEC 60947-2 (for 800VDC SSCB)
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from loto_auditor_models import (
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

log = logging.getLogger(__name__)


# =============================================================================
#  Exceptions
# =============================================================================

class LotoAuditorError(RuntimeError):
    """Base exception for LOTO auditor failures."""


class ProcedureNotFoundError(LotoAuditorError):
    """Raised when procedure YAML cannot be loaded."""


class TargetComponentNotFoundError(LotoAuditorError):
    """Raised when target_component_id is not in site_model."""


# =============================================================================
#  Procedure parser (lightweight - full impl in Batch 4.B)
# =============================================================================

class ProcedureSpec:
    """Lightweight wrapper around procedure YAML.

    Full parser will be implemented in Batch 4.B with steps,
    pre-conditions, witness flags, and phase tagging.
    """

    def __init__(self, procedure_id: str, raw: dict):
        self.procedure_id = procedure_id
        self.raw = raw
        self.steps: list[dict] = raw.get("steps", [])
        self.metadata: dict = raw.get("metadata", {})

    def has_step_with_keyword(self, keyword: str) -> bool:
        """Return True if any step description or action contains the keyword.

        Used by Batch 4.B/C pillars for procedure introspection.
        """
        keyword_lower = keyword.lower()
        for step in self.steps:
            text_blob = " ".join([
                str(step.get("description", "")),
                str(step.get("action", "")),
                str(step.get("title", "")),
            ]).lower()
            if keyword_lower in text_blob:
                return True
        return False


# =============================================================================
#  LotoAuditorAgent main class
# =============================================================================

class LotoAuditorAgent:
    """Paranoid LOTO procedure validator.

    Ingests a procedure YAML plus target equipment ID, runs 6 pillars
    of validation, and drafts a pending_approval LotoAuditReport.

    Dependencies (injected via constructor for testability):
      - site_model: SiteModel instance for topology and impact analysis
      - graphrag_service: GraphRAG service for semantic topology cross-check
      - physics_engine: PhysicsEngine for redundancy and SHI computation
      - witness_engine: WitnessGate for identity collision check
      - procedures_dir: directory containing procedure YAML files

    Usage:
        agent = LotoAuditorAgent(
            site_model=site,
            graphrag_service=graph,
            physics_engine=physics,
            witness_engine=witness,
        )
        report = agent.audit(request)
        # report.status == AuditStatus.PENDING_APPROVAL
    """

    DEFAULT_PROCEDURES_DIR = Path("config/procedures")

    def __init__(
        self,
        site_model: Any,
        graphrag_service: Any,
        physics_engine: Any,
        witness_engine: Any,
        procedures_dir: Optional[Path] = None,
    ) -> None:
        self.site_model = site_model
        self.graphrag_service = graphrag_service
        self.physics_engine = physics_engine
        self.witness_engine = witness_engine
        self.procedures_dir = procedures_dir or self.DEFAULT_PROCEDURES_DIR

    # -------------------------------------------------------------------------
    #  Main entrypoint
    # -------------------------------------------------------------------------

    def audit(self, request: LotoAuditRequest) -> LotoAuditReport:
        """Run the full 6-pillar audit. Returns pending_approval report.

        Provenance is traced in report.sources_consulted dict. Latency
        is measured in milliseconds across the entire pipeline.

        This method NEVER raises on pillar failures - failures are
        captured as PillarOutcome.HARD_FAIL within the report. The
        method only raises on infrastructure errors (target not found,
        procedure missing).
        """
        t0 = time.perf_counter()
        as_of = request.as_of_timestamp or datetime.now(timezone.utc)

        # Validate inputs (raise on infra errors)
        self._validate_target_exists(request.target_component_id)
        procedure = self._load_procedure(request.procedure_id)

        # Build report shell with placeholder pillar results
        report = LotoAuditReport(
            procedure_id=request.procedure_id,
            target_component_id=request.target_component_id,
            cet_on_duty=request.cet_on_duty,
            as_of_timestamp=as_of,
            impact_radius=ImpactRadius(),
            redundancy=RedundancyAssessment(),
            capacitor_discharge=CapacitorDischargeCheck(),
            witness_gate=WitnessGateCheck(),
            sequential_order=SequentialOrderCheck(),
            ppe_category=PPECategoryCheck(),
            status=AuditStatus.PENDING_APPROVAL,
        )

        # Run pillars one by one with isolated try/except per pillar
        # so a failure in one does NOT abort the others (defensive design).
        sources: dict[str, str] = {}

        try:
            report.impact_radius = self._check_pillar_1_topology(
                request, procedure, sources
            )
        except Exception as e:
            log.exception("Pillar 1 failed: %s", e)
            report.impact_radius.outcome = PillarOutcome.HARD_FAIL
            report.impact_radius.notes.append(f"Pillar 1 exception: {type(e).__name__}: {e}")
            sources["pillar_1_topology"] = f"error: {e}"

        try:
            report.redundancy = self._check_pillar_2_redundancy(
                request, procedure, sources
            )
        except Exception as e:
            log.exception("Pillar 2 failed: %s", e)
            report.redundancy.outcome = PillarOutcome.HARD_FAIL
            report.redundancy.hard_fail_reasons.append(
                f"Pillar 2 exception: {type(e).__name__}: {e}"
            )
            sources["pillar_2_redundancy"] = f"error: {e}"

        try:
            report.capacitor_discharge = self._check_pillar_3_capacitor_discharge(
                request, procedure, sources
            )
        except Exception as e:
            log.exception("Pillar 3 failed: %s", e)
            report.capacitor_discharge.outcome = PillarOutcome.HARD_FAIL
            report.capacitor_discharge.notes.append(
                f"Pillar 3 exception: {type(e).__name__}: {e}"
            )
            sources["pillar_3_caps"] = f"error: {e}"

        try:
            report.witness_gate = self._check_pillar_4_witness_gate(
                request, procedure, sources
            )
        except Exception as e:
            log.exception("Pillar 4 failed: %s", e)
            report.witness_gate.outcome = PillarOutcome.HARD_FAIL
            report.witness_gate.notes.append(
                f"Pillar 4 exception: {type(e).__name__}: {e}"
            )
            sources["pillar_4_witness"] = f"error: {e}"

        try:
            report.sequential_order = self._check_pillar_5_sequential_order(
                request, procedure, sources
            )
        except Exception as e:
            log.exception("Pillar 5 failed: %s", e)
            report.sequential_order.outcome = PillarOutcome.HARD_FAIL
            report.sequential_order.hard_fail_reasons.append(
                f"Pillar 5 exception: {type(e).__name__}: {e}"
            )
            sources["pillar_5_order"] = f"error: {e}"

        try:
            report.ppe_category = self._check_pillar_6_ppe_category(
                request, procedure, sources
            )
        except Exception as e:
            log.exception("Pillar 6 failed: %s", e)
            report.ppe_category.outcome = PillarOutcome.HARD_FAIL
            report.ppe_category.hard_fail_reasons.append(
                f"Pillar 6 exception: {type(e).__name__}: {e}"
            )
            sources["pillar_6_ppe"] = f"error: {e}"

        # Optional LLM summary (Batch 4.D)
        if request.include_llm_summary:
            try:
                report.llm_summary = self._render_llm_summary(report)
                report.llm_synthesis_status = "success"
                sources["llm_studio"] = "OK"
            except Exception as e:
                log.warning("LLM summary failed: %s", e)
                report.llm_summary = None
                report.llm_synthesis_status = "error"
                sources["llm_studio"] = f"error: {e}"
        else:
            report.llm_synthesis_status = "skipped"

        # Aggregate verdict
        report.aggregate_outcomes()

        # Provenance and latency
        report.sources_consulted = sources
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        report.decision_time_ms = elapsed_ms

        log.info(
            "LOTO audit %s complete: outcome=%s hard_fails=%d warns=%d in %dms",
            report.audit_id,
            report.overall_outcome.value,
            report.hard_fail_count,
            report.warn_count,
            elapsed_ms,
        )
        return report

    # -------------------------------------------------------------------------
    #  Helper methods (input validation)
    # -------------------------------------------------------------------------

    def _validate_target_exists(self, target_id: str) -> None:
        """Raise TargetComponentNotFoundError if target is not in site_model."""
        if not hasattr(self.site_model, "get_component"):
            raise LotoAuditorError(
                "site_model dependency does not expose get_component(). "
                "Cannot validate target."
            )
        try:
            self.site_model.get_component(target_id)
        except Exception as e:
            raise TargetComponentNotFoundError(
                f"Target component '{target_id}' not found in site_model: {e}"
            ) from e

    def _load_procedure(self, procedure_id: str) -> ProcedureSpec:
        """Load procedure YAML from procedures_dir.

        Returns ProcedureSpec wrapper. Raises ProcedureNotFoundError if
        the file doesn't exist or YAML parsing fails.
        """
        # Try common file naming patterns
        candidates = [
            self.procedures_dir / f"{procedure_id}.yml",
            self.procedures_dir / f"{procedure_id}.yaml",
            self.procedures_dir / procedure_id,
        ]
        for path in candidates:
            if path.is_file():
                try:
                    import yaml  # type: ignore[import-untyped]
                    with open(path, encoding="utf-8") as f:
                        raw = yaml.safe_load(f) or {}
                    return ProcedureSpec(procedure_id, raw)
                except Exception as e:
                    raise ProcedureNotFoundError(
                        f"Failed to parse procedure '{procedure_id}' at {path}: {e}"
                    ) from e

        raise ProcedureNotFoundError(
            f"Procedure '{procedure_id}' not found in {self.procedures_dir}. "
            f"Tried: {[str(c) for c in candidates]}"
        )

    # -------------------------------------------------------------------------
    #  Pillar method stubs (Batch 4.B and 4.C will implement)
    # -------------------------------------------------------------------------

    def _check_pillar_1_topology(
        self,
        request: LotoAuditRequest,
        procedure: ProcedureSpec,
        sources: dict[str, str],
    ) -> ImpactRadius:
        """Pillar 1: topological impact radius analysis.

        Implementation in Batch 4.B will:
        - Walk site_model.power_chain_for(target_id)
        - Walk site_model.cooling_chain_for(target_id) if exists
        - Cross-check with graphrag_service.query_topology(target_id)
        - Compute blast_radius_racks and blast_radius_kw
        - Set outcome to PASS if affected_components is non-empty AND
          GraphRAG cross-check is consistent
        """
        raise NotImplementedError(
            "Pillar 1 implementation deferred to Batch 4.B"
        )

    def _check_pillar_2_redundancy(
        self,
        request: LotoAuditRequest,
        procedure: ProcedureSpec,
        sources: dict[str, str],
    ) -> RedundancyAssessment:
        """Pillar 2: 2N redundancy survival check.

        Implementation in Batch 4.B will:
        - Determine target's path (A or B) from site_model metadata
        - Run physics_engine.validate_site() at as_of timestamp (pre-LOTO SHI)
        - Re-run physics_engine.validate_site() with target removed (post-LOTO SHI)
        - Detect single points of failure in remaining path
        - HARD_FAIL if shi_post_loto < shi_threshold OR overlapping_maintenance
        """
        raise NotImplementedError(
            "Pillar 2 implementation deferred to Batch 4.B"
        )

    def _check_pillar_3_capacitor_discharge(
        self,
        request: LotoAuditRequest,
        procedure: ProcedureSpec,
        sources: dict[str, str],
    ) -> CapacitorDischargeCheck:
        """Pillar 3: capacitor discharge verification per NEC 460.6.

        Implementation in Batch 4.B will:
        - Determine if discharge is required:
            - voltage_nominal >= 800: required (Building D 800VDC)
            - target.type == 'ups': required (Galaxy VX caps)
            - target.has_dc_link: required
        - Parse procedure for wait step >= 60s + voltmeter verification
        - HARD_FAIL if required AND not found
        """
        raise NotImplementedError(
            "Pillar 3 implementation deferred to Batch 4.B"
        )

    def _check_pillar_4_witness_gate(
        self,
        request: LotoAuditRequest,
        procedure: ProcedureSpec,
        sources: dict[str, str],
    ) -> WitnessGateCheck:
        """Pillar 4: witness gate compliance for LOTO Level 3+.

        Implementation in Batch 4.C will:
        - Determine LOTO level from voltage + caps + arc-flash criteria
        - For Level 3+: scan procedure for steps with requires_witness=true
        - Verify witness_engine identity collision protection is active
        - HARD_FAIL if Level 3+ and no witness steps found
        """
        raise NotImplementedError(
            "Pillar 4 implementation deferred to Batch 4.C"
        )

    def _check_pillar_5_sequential_order(
        self,
        request: LotoAuditRequest,
        procedure: ProcedureSpec,
        sources: dict[str, str],
    ) -> SequentialOrderCheck:
        """Pillar 5: hybrid sequential order check.

        Implementation in Batch 4.C will:
        - Tag each procedure step with its LotoPhase
        - Verify ELECTRICAL precedes HYDRAULIC precedes PURGE
        - If target has cooling chain: mandate PURGE step
        - HARD_FAIL if order incorrect or purge missing when required
        """
        raise NotImplementedError(
            "Pillar 5 implementation deferred to Batch 4.C"
        )

    def _check_pillar_6_ppe_category(
        self,
        request: LotoAuditRequest,
        procedure: ProcedureSpec,
        sources: dict[str, str],
    ) -> PPECategoryCheck:
        """Pillar 6: PPE category and arc flash compliance per NFPA 70E.

        Implementation in Batch 4.C will:
        - Compute required PPE category from voltage_nominal:
          - <50V: CAT_0
          - 50-600V: CAT_2
          - 600-1000V: CAT_3
          - >1000V: CAT_4
        - Parse procedure for PPE specification
        - WARN if not specified, HARD_FAIL if inadequate
        - Citations: NFPA 70E Section 130, CSA Z462-24
        """
        raise NotImplementedError(
            "Pillar 6 implementation deferred to Batch 4.C"
        )

    # -------------------------------------------------------------------------
    #  Optional LLM summary (Batch 4.D)
    # -------------------------------------------------------------------------

    def _render_llm_summary(self, report: LotoAuditReport) -> str:
        """Generate human-readable executive summary via LM Studio.

        Implementation in Batch 4.D will:
        - Format pillar outcomes into prompt
        - POST to http://127.0.0.1:1234/v1/chat/completions with timeout 8s
        - Return rendered markdown summary
        - On timeout/error, set llm_synthesis_status='timeout'
        """
        raise NotImplementedError(
            "LLM summary deferred to Batch 4.D"
        )
