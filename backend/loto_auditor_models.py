"""
backend/loto_auditor_models.py
================================
Pydantic models for the LOTO Auditor Agent (Batch 4 V9 Pillar 4 deliverable).

Models cover the 6 pillars of LOTO validation:
  1. Topological impact radius
  2. 2N redundancy survival
  3. Capacitor discharge verification (NEC 460.6)
  4. Witness gate compliance (LOTO Level 3+)
  5. Hybrid sequential order (Electrical to Hydraulic to Purge)
  6. PPE category and arc flash citation (NFPA 70E)

Per ADR-006 (Deterministic Sandbox), the LotoAuditReport is always
created in state `pending_approval` and never advances autonomously.
A qualified CET must explicitly transition state via the
witness_engine state machine.

References cited in audit reports:
- NFPA 70E Standard for Electrical Safety in the Workplace, Section 130
- CSA Z462-24 Workplace Electrical Safety (Ontario jurisdiction)
- Ontario Electrical Safety Code 28th Edition (OESC 28)
- NEC 460.6 Capacitor Discharge requirements
- IEC 60947-2 (SSCB protection for 800VDC Building D)
- IEEE 1584-2018 (arc flash hazard calculation, future enhancement)
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


# =============================================================================
#  Enums
# =============================================================================

class AuditStatus(str, Enum):
    """LOTO audit state. Per ADR-006, always starts pending_approval."""
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class PillarOutcome(str, Enum):
    """Result of an individual pillar check."""
    PASS = "PASS"
    WARN = "WARN"
    HARD_FAIL = "HARD_FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class LotoLevel(int, Enum):
    """LOTO Level per a3semi doctrine."""
    LEVEL_1_BASIC = 1                    # Single-source isolation, low voltage
    LEVEL_2_INTERMEDIATE = 2             # Multi-source isolation, no caps
    LEVEL_3_CAP_DISCHARGE = 3            # UPS or capacitor banks present
    LEVEL_4_ARC_FLASH = 4                # 800 VDC or HV equipment


class LotoPhase(str, Enum):
    """Sequential phase per A3-Alpha hybrid LOTO doctrine."""
    ELECTRICAL_ISOLATION = "electrical_isolation"
    HYDRAULIC_ISOLATION = "hydraulic_isolation"
    PURGE = "purge"
    VERIFICATION = "verification"
    OTHER = "other"


class PPECategory(int, Enum):
    """NFPA 70E PPE Category levels."""
    CAT_0 = 0   # < 50V, no PPE
    CAT_1 = 1   # 4 cal/cm2 minimum
    CAT_2 = 2   # 8 cal/cm2
    CAT_3 = 3   # 25 cal/cm2
    CAT_4 = 4   # 40 cal/cm2 (mandatory for 800VDC)


# =============================================================================
#  Input model
# =============================================================================

class LotoAuditRequest(BaseModel):
    """Request to audit a LOTO procedure against a target component."""

    procedure_id: str = Field(
        ...,
        description="Procedure ID from config/procedures (e.g. 'MOP-ATS-MONTHLY-001')",
        min_length=1,
        max_length=128,
    )
    target_component_id: str = Field(
        ...,
        description="Canonical component ID from site_model.yml (e.g. 'ups_a')",
        min_length=1,
        max_length=128,
    )
    cet_on_duty: str = Field(
        ...,
        description="CET requesting the audit (used in audit trail)",
        min_length=1,
        max_length=128,
    )
    as_of_timestamp: Optional[datetime] = Field(
        default=None,
        description=(
            "Snapshot timestamp for telemetry. If None, uses current time. "
            "Provide explicit timestamp to audit against historical state "
            "(e.g. validate procedure with pre-incident telemetry)."
        ),
    )
    include_llm_summary: bool = Field(
        default=False,
        description=(
            "If True, agent calls LM Studio (gemma-4-e2b-it) for human-readable "
            "executive summary. Adds ~5-8s latency. Default False (deterministic only)."
        ),
    )

    @field_validator("target_component_id")
    @classmethod
    def validate_component_id(cls, v: str) -> str:
        # Strip leading/trailing whitespace first, then validate internals
        stripped = v.strip()
        if " " in stripped or "/" in stripped:
            raise ValueError("Component ID must not contain whitespace or slashes")
        return stripped.lower()


# =============================================================================
#  Pillar output models
# =============================================================================

class ImpactRadius(BaseModel):
    """Pillar 1: topological impact analysis."""

    affected_components: list[str] = Field(
        default_factory=list,
        description="All component IDs that lose power or cooling if target is LOTO'd",
    )
    immediate_loads: list[str] = Field(
        default_factory=list,
        description="Components directly downstream (1 hop)",
    )
    transitive_loads: list[str] = Field(
        default_factory=list,
        description="Components affected via cascading (2+ hops)",
    )
    blast_radius_racks: int = Field(
        default=0,
        description="Number of racks (compute) affected",
    )
    blast_radius_kw: float = Field(
        default=0.0,
        description="Total IT load in kW that loses power",
    )
    cooling_chain_affected: list[str] = Field(
        default_factory=list,
        description="Cooling components (CDU, chiller) affected",
    )
    graphrag_consistency_check: bool = Field(
        default=True,
        description="True if site_model topology matches GraphRAG semantic topology",
    )
    outcome: PillarOutcome = PillarOutcome.PASS
    notes: list[str] = Field(default_factory=list)


class RedundancyAssessment(BaseModel):
    """Pillar 2: 2N redundancy survival check."""

    target_path: Optional[str] = Field(
        default=None,
        description="Path A or Path B that target belongs to (None if not 2N protected)",
    )
    path_a_state: str = Field(default="unknown")
    path_b_state: str = Field(default="unknown")
    shi_pre_loto: float = Field(
        default=1.0,
        description="Site Health Index BEFORE simulated LOTO (0.0-1.0)",
        ge=0.0,
        le=1.0,
    )
    shi_post_loto: float = Field(
        default=1.0,
        description="Site Health Index AFTER simulated LOTO (0.0-1.0)",
        ge=0.0,
        le=1.0,
    )
    shi_threshold: float = Field(
        default=0.7,
        description="Minimum acceptable post-LOTO SHI",
        ge=0.0,
        le=1.0,
    )
    single_points_of_failure: list[str] = Field(
        default_factory=list,
        description="Components that become SPOF if target is removed",
    )
    overlapping_maintenance: bool = Field(
        default=False,
        description="True if opposite path is also in maintenance window",
    )
    hard_fail_reasons: list[str] = Field(default_factory=list)
    outcome: PillarOutcome = PillarOutcome.PASS


class CapacitorDischargeCheck(BaseModel):
    """Pillar 3: capacitor discharge verification per NEC 460.6."""

    required: bool = Field(
        default=False,
        description="True if discharge step is mandatory for this target",
    )
    required_reason: Optional[str] = Field(
        default=None,
        description="Why discharge is required (voltage threshold, UPS, DC link)",
    )
    found_in_procedure: bool = Field(
        default=False,
        description="True if procedure YAML contains a discharge wait step",
    )
    wait_duration_s: int = Field(
        default=0,
        description="Discharge wait time specified in procedure (seconds)",
        ge=0,
    )
    minimum_required_s: int = Field(
        default=60,
        description="Minimum required wait per NEC 460.6 (60s for standard caps)",
    )
    voltmeter_verification: bool = Field(
        default=False,
        description="True if procedure mandates CAT IV voltmeter verification post-wait",
    )
    target_threshold_v: float = Field(
        default=50.0,
        description="Voltage threshold capacitors must discharge below (per NEC 460.6)",
    )
    citation: str = Field(
        default="NEC 460.6",
        description="Standard citation for the requirement",
    )
    outcome: PillarOutcome = PillarOutcome.PASS
    notes: list[str] = Field(default_factory=list)


class WitnessGateCheck(BaseModel):
    """Pillar 4: witness gate compliance for LOTO Level 3+."""

    loto_level: LotoLevel = LotoLevel.LEVEL_1_BASIC
    level_rationale: str = Field(default="")
    witness_required: bool = Field(default=False)
    witness_steps: list[str] = Field(
        default_factory=list,
        description="Step IDs in procedure with requires_witness=true",
    )
    identity_collision_protected: bool = Field(
        default=False,
        description="True if witness_engine enforces non-self-witness rule",
    )
    outcome: PillarOutcome = PillarOutcome.PASS
    notes: list[str] = Field(default_factory=list)


class SequentialOrderCheck(BaseModel):
    """Pillar 5: hybrid sequential LOTO order check."""

    phases_detected: list[LotoPhase] = Field(default_factory=list)
    phases_in_correct_order: bool = Field(default=True)
    purge_required: bool = Field(
        default=False,
        description="True if target involves cooling and purge step is mandated",
    )
    purge_present: bool = Field(default=False)
    warnings: list[str] = Field(default_factory=list)
    hard_fail_reasons: list[str] = Field(default_factory=list)
    outcome: PillarOutcome = PillarOutcome.PASS


class PPECategoryCheck(BaseModel):
    """Pillar 6: PPE category and arc flash compliance per NFPA 70E."""

    voltage_nominal: float = Field(
        default=0.0,
        description="Nominal voltage of target component (V)",
        ge=0.0,
    )
    computed_category: PPECategory = PPECategory.CAT_0
    procedure_specified_category: Optional[PPECategory] = None
    incident_energy_cal_cm2: Optional[float] = Field(
        default=None,
        description=(
            "Calculated incident energy if available (cal/cm2). "
            "None if IEEE 1584 calculator not implemented yet (V10 deferred)."
        ),
        ge=0.0,
    )
    arc_flash_boundary_mm: Optional[float] = Field(
        default=None,
        description="Arc flash boundary distance in mm. None if not calculated.",
        ge=0.0,
    )
    citations: list[str] = Field(
        default_factory=lambda: ["NFPA 70E Section 130", "CSA Z462-24"],
    )
    outcome: PillarOutcome = PillarOutcome.PASS
    warnings: list[str] = Field(default_factory=list)
    hard_fail_reasons: list[str] = Field(default_factory=list)


# =============================================================================
#  Aggregate report model
# =============================================================================

class LotoAuditReport(BaseModel):
    """Aggregate LOTO audit report.

    Per ADR-006 Deterministic Sandbox, report is always created in
    state `pending_approval`. Only a CET signing via witness_engine can
    transition state. No autonomous transition is allowed.
    """

    audit_id: str = Field(
        default_factory=lambda: f"LOTO-AUDIT-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}",
        description="Unique audit identifier (timestamp + uuid suffix)",
    )
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    procedure_id: str
    target_component_id: str
    cet_on_duty: str
    as_of_timestamp: datetime
    facility: str = Field(default="A3-Alpha Toronto Area")

    # Pillar results
    impact_radius: ImpactRadius
    redundancy: RedundancyAssessment
    capacitor_discharge: CapacitorDischargeCheck
    witness_gate: WitnessGateCheck
    sequential_order: SequentialOrderCheck
    ppe_category: PPECategoryCheck

    # Aggregate verdict
    overall_outcome: PillarOutcome = PillarOutcome.PASS
    hard_fail_count: int = Field(default=0, ge=0)
    warn_count: int = Field(default=0, ge=0)
    pass_count: int = Field(default=0, ge=0)
    not_applicable_count: int = Field(default=0, ge=0)

    # State per ADR-006
    status: AuditStatus = AuditStatus.PENDING_APPROVAL
    rejection_reason: Optional[str] = None
    approver_cet: Optional[str] = None

    # Provenance trace
    sources_consulted: dict[str, str] = Field(
        default_factory=dict,
        description="Map of source name to status (e.g. 'site_model: OK', 'graphrag: timeout')",
    )
    decision_time_ms: int = Field(
        default=0,
        description="Total wall-clock time of the audit in milliseconds",
        ge=0,
    )
    api_version: str = Field(default="1.0")

    # Optional LLM summary
    llm_summary: Optional[str] = Field(
        default=None,
        description="Human-readable executive summary if include_llm_summary=true in request",
    )
    llm_synthesis_status: str = Field(
        default="skipped",
        description="success | timeout | skipped | error",
    )

    # Citations applied
    standards_cited: list[str] = Field(
        default_factory=lambda: [
            "NFPA 70E Section 130",
            "CSA Z462-24",
            "Ontario Electrical Safety Code 28th Edition",
            "NEC 460.6",
        ],
    )

    def aggregate_outcomes(self) -> None:
        """Recompute overall_outcome from pillars. Mutates self."""
        pillars = [
            self.impact_radius.outcome,
            self.redundancy.outcome,
            self.capacitor_discharge.outcome,
            self.witness_gate.outcome,
            self.sequential_order.outcome,
            self.ppe_category.outcome,
        ]
        self.hard_fail_count = sum(1 for p in pillars if p == PillarOutcome.HARD_FAIL)
        self.warn_count = sum(1 for p in pillars if p == PillarOutcome.WARN)
        self.pass_count = sum(1 for p in pillars if p == PillarOutcome.PASS)
        self.not_applicable_count = sum(
            1 for p in pillars if p == PillarOutcome.NOT_APPLICABLE
        )

        if self.hard_fail_count > 0:
            self.overall_outcome = PillarOutcome.HARD_FAIL
        elif self.warn_count > 0:
            self.overall_outcome = PillarOutcome.WARN
        else:
            self.overall_outcome = PillarOutcome.PASS


# =============================================================================
#  Storage models (persistence helpers)
# =============================================================================

class LotoAuditDBRecord(BaseModel):
    """Mirror of the loto_audits PostgreSQL row.

    Used to serialize/deserialize audit reports between application
    layer and database without exposing JSONB internals.
    """

    audit_id: str
    timestamp: datetime
    procedure_id: str
    target_component_id: str
    cet_on_duty: str
    overall_outcome: PillarOutcome
    hard_fail_count: int
    warn_count: int
    status: AuditStatus
    report_json: dict
    decision_time_ms: int
    api_version: str = "1.0"
