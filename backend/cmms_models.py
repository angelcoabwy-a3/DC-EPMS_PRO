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
)
HEALTH_STATES = ("healthy", "degraded", "failed", "unknown")
REDUNDANCY_PILLARS = ("2N", "N+1", "N", "single")
CRITICALITY_CLASSES = ("critical", "high", "medium", "low")
WORK_CLASSES = ("PM", "CM", "EM")
PROCEDURE_CLASSES = ("SOP", "MOP", "DMOP", "EOP")
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
    rejection_reason: str | None = None

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


class ApproveRejectRequest(BaseModel):
    """Body for POST /api/cmms/work-orders/{id}/{approve|reject}."""
    model_config = ConfigDict(extra="forbid")

    cet_id: str
    rejection_reason: str | None = None  # required for reject, ignored for approve


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
