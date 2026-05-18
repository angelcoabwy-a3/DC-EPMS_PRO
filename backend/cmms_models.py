"""
backend/cmms_models.py
=======================
Pydantic models for CMMS Core v1.0 (Sprint 6).

Mirrors the PostgreSQL schema defined in
  backend/migrations/2026_05_W2_cmms_core.sql

Two-layer split:
  * Domain models (Asset, WorkOrder)            -- match DB rows verbatim
  * Request models (CreateWorkOrderRequest, ...)-- HTTP API surface

The repository persists Asset / WorkOrder; the router accepts
CreateWorkOrderRequest -> draft via cmms_mcp.tool_draft_cmms_work_order
-> persist as WorkOrder.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ─── Constants matching SQL CHECK constraints ─────────────────────────
ASSET_TYPES = (
    "ups", "chiller", "cdu", "pump",
    "cooling_tower_field", "cooling_tower",
    "genset", "transformer", "switchgear",
    "ats", "rpp", "busway", "utility_intake",
    "fuel_tank", "bms_panel", "workstation",
    "it_rack", "rectifier", "sensor", "other",
    # G1 micro-component taxonomy types (mirrors the W3 migration CHECK)
    "system", "battery", "breaker", "filter", "valve",
    "fuel_pump", "coolant_pump",
    # Phase-2 SLD topology types
    "mv_rectifier", "sscb", "dc_bus", "bess",
)
HEALTH_STATES = ("healthy", "degraded", "failed", "unknown")
REDUNDANCY_PILLARS = ("2N", "N+1", "N", "single")
CRITICALITY_CLASSES = ("critical", "high", "medium", "low")
WORK_CLASSES = ("PM", "CM", "EM")
PROCEDURE_CLASSES = ("SOP", "MOP", "DMOP", "EOP", "EMP")
WO_STATUSES = (
    "pending_approval", "approved", "scheduled", "in_progress",
    "completed", "rejected", "cancelled", "overdue",
)
TRIGGER_SOURCES = (
    "manual", "predictive_kalman", "scheduled_pm",
    "incident", "loto_audit",
)
PRIORITIES = ("P1", "P2", "P3", "P4")
MOP_RESOLUTION_METHODS = ("hardcoded", "graphrag", "manual")

# RCA root-cause taxonomy for incident-triggered work orders.
ROOT_CAUSE_CATEGORIES = (
    "equipment_failure", "human_error", "environmental",
    "design_deficiency", "procedure_gap", "vendor_defect", "unknown",
)


class AssetLevel(str, Enum):
    """Hierarchical asset taxonomy tier (ADR-010 containment tree).

    Macro -> micro containment scope. The ProcedureGenerator reads this to
    decide procedure scope: SYSTEM / EQUIPMENT -> holistic SOP / MOP;
    SUB_ASSEMBLY / COMPONENT / SENSOR -> hyper-focused EMP.
    """

    SYSTEM = "system"            # e.g. Backup Power
    EQUIPMENT = "equipment"      # e.g. Genset_A1
    SUB_ASSEMBLY = "sub_assembly"  # e.g. Starter Battery, Fuel Pump
    COMPONENT = "component"      # e.g. 24 VDC breaker, fuel filter
    SENSOR = "sensor"            # e.g. fuel pressure probe


# ═══════════════════════════════════════════════════════════════════════
#  RBAC — operational role hierarchy + permission matrix
#
#  Models the Equinix / Vantage hyperscale technician ladder. The gate
#  functions below are pure (role in -> bool out); the enforcement points
#  (procedure_engine ARMED transition, vendor QA sign-off, WO approval)
#  call them.
#
#  REALITY CHECK: this is the AUTHORIZATION layer only. There is no
#  authentication layer in the platform yet — the actor role is an
#  asserted claim (carried alongside a cet_id), NOT a verified identity.
#  Real authentication (login / SSO) is a separate production prerequisite.
# ═══════════════════════════════════════════════════════════════════════
class UserRole(str, Enum):
    """Operational role hierarchy (hyperscale data-center technician ladder)."""

    TECH_L4 = "TECH_L4"                # executes SOPs, drafts MOPs, monitors BMS
    SENIOR_TECH_L5 = "SENIOR_TECH_L5"  # approves standard MOPs, validates RCA
    SME_L6 = "SME_L6"                  # approves high-risk EOPs, MV / UPS isolations


# Numeric rank — higher outranks lower. Every gate decision routes through this.
_ROLE_RANK: dict[UserRole, int] = {
    UserRole.TECH_L4: 4,
    UserRole.SENIOR_TECH_L5: 5,
    UserRole.SME_L6: 6,
}


class RBACDeniedError(PermissionError):
    """Raised when an actor role is insufficient for a gated transition."""


def role_rank(role: UserRole | str | None) -> int:
    """Numeric rank for a role. None / unknown -> 0 (no privilege)."""
    if role is None:
        return 0
    try:
        return _ROLE_RANK[UserRole(role)]
    except (ValueError, KeyError):
        return 0


def can_approve_work_order(role: UserRole | str | None) -> bool:
    """L5+ may approve a work order / MOP. A TECH_L4 may only draft it."""
    return role_rank(role) >= 5


def can_arm_critical_procedure(role: UserRole | str | None, high_risk: bool = False) -> bool:
    """Gate the ARMED transition. Standard MOP -> L5+; a high-risk EOP or
    an MV / UPS isolation -> SME_L6 only."""
    return role_rank(role) >= (6 if high_risk else 5)


def can_signoff_incident_closure(role: UserRole | str | None) -> bool:
    """Incident closure sign-off requires L5+ validation. A TECH_L4 may
    enter initial RCA data but may not close the incident."""
    return role_rank(role) >= 5


def can_qa_signoff_vendor(role: UserRole | str | None) -> bool:
    """Vendor POST_WORK_QA_SIGNOFF (closes the LOTO) requires L5+."""
    return role_rank(role) >= 5


def assert_can_approve_work_order(role: UserRole | str | None) -> None:
    """Raise RBACDeniedError if `role` may not approve a work order."""
    if not can_approve_work_order(role):
        raise RBACDeniedError(
            f"role {role or 'NONE'} cannot approve a work order — "
            "SENIOR_TECH_L5 or SME_L6 signature required."
        )


# ═══════════════════════════════════════════════════════════════════════
#  Domain: Asset
# ═══════════════════════════════════════════════════════════════════════
class Asset(BaseModel):
    """Canonical asset registry row."""
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    display_name: str
    asset_type: str = Field(..., pattern="^(" + "|".join(ASSET_TYPES) + ")$")
    facility: str = "A3-Alpha Toronto Area"
    location_path: str | None = None
    vendor: str | None = None
    model: str | None = None
    rated_capacity_kw: float | None = None
    rated_capacity_unit: str = "kW"

    # Tesla/SpaceX vision fields
    path: str | None = None
    redundancy_pillar: str | None = None
    telemetry_channels: list[str] = Field(default_factory=list)
    criticality_class: str = "medium"

    linked_mop_id: str | None = None

    # G1 — hierarchical asset taxonomy (ADR-010 containment tree).
    asset_level: AssetLevel | None = None
    parent_asset_id: str | None = None

    # G1 — Arc Flash data (NFPA 70E / IEEE 1584). Carried, NOT computed —
    # populated from an arc-flash study; null on non-electrical nodes.
    fault_current_ka: float | None = None
    incident_energy_cal: float | None = None
    arc_flash_boundary_m: float | None = None

    health_state: str = "healthy"
    last_health_update_at: datetime | None = None

    last_pm_completed_at: datetime | None = None
    next_pm_due_at: datetime | None = None
    pm_interval_days: int | None = None

    metadata_json: dict[str, Any] = Field(default_factory=dict)

    created_at: datetime | None = None
    updated_at: datetime | None = None


# ═══════════════════════════════════════════════════════════════════════
#  Domain: WorkOrder
# ═══════════════════════════════════════════════════════════════════════
class WorkOrder(BaseModel):
    """Persistent CMMS work order entity."""
    model_config = ConfigDict(extra="forbid")

    work_order_id: str
    timestamp: datetime
    asset_id: str
    asset_type_at_creation: str

    work_class: str
    lor: int = Field(ge=1, le=25)
    procedure_class: str | None = None

    linked_mop_id: str | None = None
    linked_loto_audit_id: str | None = None

    trigger_source: str
    predictive_metadata: dict[str, Any] | None = None

    issue_summary: str
    estimated_cost_usd: float = 0.0
    requires_loto: bool = False
    requires_oem_specialist: bool = False

    status: str = "pending_approval"
    priority: str = "P3"
    telemetry_snapshot_json: dict[str, Any] | None = None
    mop_resolution_method: str | None = None

    requested_by: str | None = None
    assigned_to_cet: str | None = None
    approved_by_cet: str | None = None
    approved_by_role: str | None = None       # RBAC signature bit (UserRole value)
    rejection_reason: str | None = None

    # RBAC escalation + RCA (incident-triggered WOs). NOTE: these are
    # model / API-surface fields — the work_orders table does not yet
    # carry the columns; persistence needs a migration (see report).
    escalation_required: bool = False
    escalation_reason: str | None = None
    spof_identified: bool = False
    root_cause_category: str | None = None
    closure_signoff_by_role: str | None = None

    due_at: datetime | None = None
    approved_at: datetime | None = None
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    rejected_at: datetime | None = None
    cancelled_at: datetime | None = None

    draft_json: dict[str, Any]
    result_json: dict[str, Any] | None = None

    api_version: str = "1.0"
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ═══════════════════════════════════════════════════════════════════════
#  Request DTOs
# ═══════════════════════════════════════════════════════════════════════
class CreateWorkOrderRequest(BaseModel):
    """Body for POST /api/cmms/work-orders or /api/cmms/trigger-maintenance."""
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    issue_summary: str
    work_class_hint: Literal["PM", "CM", "EM"] = "PM"
    likelihood_idx: int = Field(default=3, ge=1, le=5)
    consequence_idx: int = Field(default=3, ge=1, le=5)
    estimated_cost_usd: float = 0.0
    requires_loto: bool = False
    requires_oem_specialist: bool = False
    requested_by: str | None = None
    trigger_source: str = "manual"
    predictive_metadata: dict[str, Any] | None = None
    telemetry_snapshot_json: dict[str, Any] | None = None
    due_at: datetime | None = None
    actor_role: str | None = None        # RBAC F3-4 claim; None -> gate not enforced


class ApproveRejectRequest(BaseModel):
    """Body for POST /api/cmms/work-orders/{id}/{approve|reject}."""
    model_config = ConfigDict(extra="forbid")

    cet_id: str
    actor_role: UserRole | None = None   # RBAC signature bit; None -> gate not enforced
    rejection_reason: str | None = None  # required for reject, ignored for approve


class AssetEnrichRequest(BaseModel):
    """Body for PATCH /api/cmms/assets/{asset_id}.

    Sprint 7.1d-followup: lets the operator write nameplate-OCR'd data
    (vendor / model / serial / capacity / voltage) onto an existing
    asset row whose corresponding columns are still null. Only fields
    explicitly present in the body are written; everything else is
    preserved. `serial` and `voltage_v` flow into metadata_json so they
    align with the nameplate matcher's lookup convention. ADR-006:
    advisory write — the operator sees the candidates beforehand and
    picks the target asset_id explicitly.
    """
    model_config = ConfigDict(extra="forbid")

    actor_role: str | None = None        # RBAC F3-4 claim; None -> gate not enforced
    vendor: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=120)
    serial: str | None = Field(default=None, max_length=120)
    rated_capacity_kw: float | None = Field(default=None, ge=0)
    rated_capacity_unit: str | None = Field(default=None, max_length=8)
    voltage_v: float | None = Field(default=None, ge=0)
    enriched_by: str | None = Field(default=None, max_length=120,
                                     description="CET id (audit trail). Optional.")


class AssetHealthAggregate(BaseModel):
    """Row from the asset_health_aggregate view."""
    facility: str
    path: str | None
    redundancy_pillar: str | None
    asset_type: str
    total: int
    healthy_count: int
    degraded_count: int
    failed_count: int
    unknown_count: int
    total_open_wos: int
    total_overdue_wos: int
    total_p1_wos: int
    aggregate_health_score: float | None
