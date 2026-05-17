"""
backend/cmms_repository.py
==========================
asyncpg-backed persistence for CMMS Core v1.0 (Sprint 6 Fase 2).

Mirrors the loto_auditor_repository pattern (Batch 4.D). Both async
methods (for FastAPI route handlers) and a Mock implementation (for tests
running without a live PostgreSQL).

Per ADR-006 Deterministic Sandbox:
  * All work orders persist in pending_approval state initially.
  * State transitions (approve, reject, complete) require explicit
    method calls; the repository never auto-advances.

Production usage:
  from backend.cmms_repository import PostgresCMMSRepository
  repo = PostgresCMMSRepository(asyncpg_pool)
  asset = await repo.get_asset_async("ups_a")
  await repo.save_work_order_async(wo)

Test usage:
  from backend.cmms_repository import MockCMMSRepository
  repo = MockCMMSRepository()
  await repo.upsert_asset_async(asset)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterable

from backend.cmms_models import Asset, AssetHealthAggregate, WorkOrder

log = logging.getLogger(__name__)


# =====================================================================
#  Exceptions
# =====================================================================
class CMMSRepositoryError(RuntimeError):
    pass


class AssetNotFoundError(CMMSRepositoryError):
    pass


class WorkOrderNotFoundError(CMMSRepositoryError):
    pass


class WorkOrderStateConflictError(CMMSRepositoryError):
    """ADR-006 audit-trail integrity guard.

    A WO state transition was attempted from a state where it is not
    legal — for example, re-approving an already-approved WO would
    overwrite the original CET signature, breaking single-signature
    auditability. The route handler maps this to HTTP 409 Conflict.
    """

    def __init__(self, wo_id: str, current_status: str, attempted: str,
                 current_cet: str | None = None):
        self.wo_id = wo_id
        self.current_status = current_status
        self.attempted = attempted
        self.current_cet = current_cet
        msg = (
            f"work_order '{wo_id}' is already '{current_status}'"
            + (f" (signed by '{current_cet}')" if current_cet else "")
            + f"; cannot transition to '{attempted}'."
        )
        super().__init__(msg)


# =====================================================================
#  Helpers
# =====================================================================
def _row_to_asset(row: Any) -> Asset:
    """Convert an asyncpg Record (or dict) to an Asset Pydantic model."""
    d = dict(row)
    # asyncpg returns JSONB as str in some configs, dict/list in others
    for key in ("telemetry_channels", "metadata_json"):
        v = d.get(key)
        if isinstance(v, str):
            d[key] = json.loads(v)
        elif v is None and key == "telemetry_channels":
            d[key] = []
        elif v is None and key == "metadata_json":
            d[key] = {}
    # rated_capacity_kw arrives as Decimal; Pydantic accepts that
    if d.get("rated_capacity_kw") is not None:
        d["rated_capacity_kw"] = float(d["rated_capacity_kw"])
    return Asset.model_validate(d)


def _row_to_wo(row: Any) -> WorkOrder:
    d = dict(row)
    for key in (
        "predictive_metadata",
        "telemetry_snapshot_json",
        "draft_json",
        "result_json",
    ):
        v = d.get(key)
        if isinstance(v, str):
            d[key] = json.loads(v)
    if d.get("estimated_cost_usd") is not None:
        d["estimated_cost_usd"] = float(d["estimated_cost_usd"])
    return WorkOrder.model_validate(d)


# =====================================================================
#  Postgres implementation
# =====================================================================
class PostgresCMMSRepository:
    """asyncpg pool-backed repository for assets + work_orders.

    The pool is owned by the FastAPI lifespan (main.py db_manager.pool)
    and injected here. Exceptions wrap into CMMSRepositoryError so
    routes can return clean HTTP errors.
    """

    def __init__(self, asyncpg_pool: Any) -> None:
        self._pool = asyncpg_pool

    # ── Asset CRUD ────────────────────────────────────────────────────
    async def upsert_asset_async(self, asset: Asset) -> None:
        sql = """
        INSERT INTO assets (
            asset_id, display_name, asset_type, facility, location_path,
            vendor, model, rated_capacity_kw, rated_capacity_unit,
            path, redundancy_pillar, telemetry_channels, criticality_class,
            linked_mop_id, health_state,
            last_pm_completed_at, next_pm_due_at, pm_interval_days,
            metadata_json
        ) VALUES (
            $1, $2, $3, $4, $5,
            $6, $7, $8, $9,
            $10, $11, $12::jsonb, $13,
            $14, $15,
            $16, $17, $18,
            $19::jsonb
        )
        ON CONFLICT (asset_id) DO UPDATE SET
            display_name      = EXCLUDED.display_name,
            asset_type        = EXCLUDED.asset_type,
            facility          = EXCLUDED.facility,
            location_path     = EXCLUDED.location_path,
            vendor            = EXCLUDED.vendor,
            model             = EXCLUDED.model,
            rated_capacity_kw = EXCLUDED.rated_capacity_kw,
            rated_capacity_unit = EXCLUDED.rated_capacity_unit,
            path              = EXCLUDED.path,
            redundancy_pillar = EXCLUDED.redundancy_pillar,
            telemetry_channels = EXCLUDED.telemetry_channels,
            criticality_class = EXCLUDED.criticality_class,
            linked_mop_id     = EXCLUDED.linked_mop_id,
            health_state      = EXCLUDED.health_state,
            metadata_json     = EXCLUDED.metadata_json
        ;
        """
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    sql,
                    asset.asset_id,
                    asset.display_name,
                    asset.asset_type,
                    asset.facility,
                    asset.location_path,
                    asset.vendor,
                    asset.model,
                    asset.rated_capacity_kw,
                    asset.rated_capacity_unit,
                    asset.path,
                    asset.redundancy_pillar,
                    json.dumps(asset.telemetry_channels),
                    asset.criticality_class,
                    asset.linked_mop_id,
                    asset.health_state,
                    asset.last_pm_completed_at,
                    asset.next_pm_due_at,
                    asset.pm_interval_days,
                    json.dumps(asset.metadata_json),
                )
        except Exception as e:
            raise CMMSRepositoryError(f"upsert_asset {asset.asset_id} failed: {e}") from e

    async def upsert_assets_bulk_async(self, assets: Iterable[Asset]) -> int:
        """Idempotent bulk upsert. Returns count."""
        count = 0
        for a in assets:
            await self.upsert_asset_async(a)
            count += 1
        return count

    async def get_asset_async(self, asset_id: str) -> Asset:
        sql = "SELECT * FROM assets WHERE asset_id = $1;"
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(sql, asset_id)
        except Exception as e:
            raise CMMSRepositoryError(f"get_asset {asset_id} failed: {e}") from e
        if row is None:
            raise AssetNotFoundError(f"asset '{asset_id}' not found")
        return _row_to_asset(row)

    async def list_assets_async(
        self,
        asset_type: str | None = None,
        path: str | None = None,
        criticality_class: str | None = None,
        health_state: str | None = None,
        limit: int = 1000,
    ) -> list[Asset]:
        clauses: list[str] = []
        params: list[Any] = []
        if asset_type:
            clauses.append(f"asset_type = ${len(params) + 1}")
            params.append(asset_type)
        if path:
            clauses.append(f"path = ${len(params) + 1}")
            params.append(path)
        if criticality_class:
            clauses.append(f"criticality_class = ${len(params) + 1}")
            params.append(criticality_class)
        if health_state:
            clauses.append(f"health_state = ${len(params) + 1}")
            params.append(health_state)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM assets {where} ORDER BY asset_id LIMIT ${len(params) + 1};"
        params.append(limit)
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(sql, *params)
        except Exception as e:
            raise CMMSRepositoryError(f"list_assets failed: {e}") from e
        return [_row_to_asset(r) for r in rows]

    async def get_health_aggregate_async(self) -> list[AssetHealthAggregate]:
        sql = "SELECT * FROM asset_health_aggregate ORDER BY facility, path NULLS LAST, asset_type;"
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(sql)
        except Exception as e:
            raise CMMSRepositoryError(f"health aggregate query failed: {e}") from e
        out = []
        for r in rows:
            d = dict(r)
            if d.get("aggregate_health_score") is not None:
                d["aggregate_health_score"] = float(d["aggregate_health_score"])
            out.append(AssetHealthAggregate.model_validate(d))
        return out

    # ── WorkOrder CRUD ────────────────────────────────────────────────
    async def save_work_order_async(self, wo: WorkOrder) -> None:
        sql = """
        INSERT INTO work_orders (
            work_order_id, timestamp,
            asset_id, asset_type_at_creation,
            work_class, lor, procedure_class,
            linked_mop_id, linked_loto_audit_id,
            trigger_source, predictive_metadata,
            issue_summary, estimated_cost_usd,
            requires_loto, requires_oem_specialist,
            status, priority,
            telemetry_snapshot_json, mop_resolution_method,
            requested_by, assigned_to_cet, approved_by_cet,
            due_at,
            draft_json, result_json,
            api_version
        ) VALUES (
            $1, $2,
            $3, $4,
            $5, $6, $7,
            $8, $9,
            $10, $11::jsonb,
            $12, $13,
            $14, $15,
            $16, $17,
            $18::jsonb, $19,
            $20, $21, $22,
            $23,
            $24::jsonb, $25::jsonb,
            $26
        )
        ON CONFLICT (work_order_id) DO UPDATE SET
            status                   = EXCLUDED.status,
            priority                 = EXCLUDED.priority,
            assigned_to_cet          = EXCLUDED.assigned_to_cet,
            approved_by_cet          = EXCLUDED.approved_by_cet,
            rejection_reason         = COALESCE(work_orders.rejection_reason, EXCLUDED.rejection_reason),
            telemetry_snapshot_json  = COALESCE(work_orders.telemetry_snapshot_json, EXCLUDED.telemetry_snapshot_json),
            result_json              = COALESCE(EXCLUDED.result_json, work_orders.result_json)
        ;
        """
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    sql,
                    wo.work_order_id,
                    wo.timestamp,
                    wo.asset_id,
                    wo.asset_type_at_creation,
                    wo.work_class,
                    wo.lor,
                    wo.procedure_class,
                    wo.linked_mop_id,
                    wo.linked_loto_audit_id,
                    wo.trigger_source,
                    json.dumps(wo.predictive_metadata) if wo.predictive_metadata else None,
                    wo.issue_summary,
                    wo.estimated_cost_usd,
                    wo.requires_loto,
                    wo.requires_oem_specialist,
                    wo.status,
                    wo.priority,
                    json.dumps(wo.telemetry_snapshot_json) if wo.telemetry_snapshot_json else None,
                    wo.mop_resolution_method,
                    wo.requested_by,
                    wo.assigned_to_cet,
                    wo.approved_by_cet,
                    wo.due_at,
                    json.dumps(wo.draft_json),
                    json.dumps(wo.result_json) if wo.result_json else None,
                    wo.api_version,
                )
        except Exception as e:
            raise CMMSRepositoryError(f"save_work_order {wo.work_order_id} failed: {e}") from e

        # T3.1 EDA: broadcast the WO mutation on the Hermes cmms_alerts
        # stream. Fire-and-forget -- streaming must never affect persistence.
        try:
            from backend import hermes
            hermes.emit_event("cmms_alerts", {
                "event": "work_order_saved",
                "work_order_id": wo.work_order_id,
                "asset_id": wo.asset_id,
                "status": wo.status,
                "priority": wo.priority,
                "trigger_source": wo.trigger_source,
            })
        except Exception:
            pass

    async def get_work_order_async(self, wo_id: str) -> WorkOrder:
        sql = "SELECT * FROM work_orders WHERE work_order_id = $1;"
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(sql, wo_id)
        except Exception as e:
            raise CMMSRepositoryError(f"get_work_order {wo_id} failed: {e}") from e
        if row is None:
            raise WorkOrderNotFoundError(f"work_order '{wo_id}' not found")
        return _row_to_wo(row)

    async def list_work_orders_async(
        self,
        status: str | None = None,
        asset_id: str | None = None,
        trigger_source: str | None = None,
        priority: str | None = None,
        lor_min: int | None = None,
        only_open: bool = False,
        limit: int = 100,
    ) -> list[WorkOrder]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append(f"status = ${len(params) + 1}")
            params.append(status)
        if asset_id:
            clauses.append(f"asset_id = ${len(params) + 1}")
            params.append(asset_id)
        if trigger_source:
            clauses.append(f"trigger_source = ${len(params) + 1}")
            params.append(trigger_source)
        if priority:
            clauses.append(f"priority = ${len(params) + 1}")
            params.append(priority)
        if lor_min is not None:
            clauses.append(f"lor >= ${len(params) + 1}")
            params.append(lor_min)
        if only_open:
            clauses.append(
                "status IN ('pending_approval','approved','scheduled','in_progress')"
            )
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM work_orders {where} ORDER BY timestamp DESC LIMIT ${len(params) + 1};"
        params.append(limit)
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(sql, *params)
        except Exception as e:
            raise CMMSRepositoryError(f"list_work_orders failed: {e}") from e
        return [_row_to_wo(r) for r in rows]

    async def transition_status_async(
        self,
        wo_id: str,
        new_status: str,
        cet_id: str,
        rejection_reason: str | None = None,
    ) -> WorkOrder:
        """Perform a state-machine transition and return the updated WO.

        ADR-006 audit-trail integrity (DC-EPMS-040 fix):
          * approve  is only valid from 'pending_approval'.
          * reject   is only valid from 'pending_approval'.
        Re-approving an already-approved WO would silently overwrite
        the original `approved_by_cet`, breaking single-signature
        auditability — so we raise WorkOrderStateConflictError (HTTP
        409) instead.

        Other transitions (approved -> scheduled -> in_progress ->
        completed) preserve approved_by_cet and rejection_reason via
        the WHERE-clause; existing assigned_to_cet is set on the first
        in_progress transition only.
        """
        # Atomic guarded UPDATE: only succeeds if the source state is
        # legal for the requested target state. We drive that via a
        # WHERE clause; if no row matches, we re-fetch to determine
        # whether the WO doesn't exist (-> 404) vs is in the wrong
        # state (-> 409).
        update_sql = """
        UPDATE work_orders
        SET status = $2,
            approved_by_cet = CASE
                WHEN $2 = 'approved' AND approved_by_cet IS NULL THEN $3
                ELSE approved_by_cet
            END,
            assigned_to_cet = CASE
                WHEN $2 = 'in_progress' AND assigned_to_cet IS NULL THEN $3
                ELSE assigned_to_cet
            END,
            rejection_reason = CASE
                WHEN $2 = 'rejected' THEN $4
                ELSE rejection_reason
            END
        WHERE work_order_id = $1
          AND CASE
                WHEN $2 = 'approved' THEN status = 'pending_approval'
                WHEN $2 = 'rejected' THEN status = 'pending_approval'
                ELSE TRUE
              END
        RETURNING *;
        """
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    update_sql, wo_id, new_status, cet_id, rejection_reason,
                )
                if row is None:
                    # Either WO doesn't exist or it's in the wrong state.
                    current = await conn.fetchrow(
                        "SELECT status, approved_by_cet FROM work_orders "
                        "WHERE work_order_id = $1",
                        wo_id,
                    )
        except Exception as e:
            raise CMMSRepositoryError(f"transition_status {wo_id} failed: {e}") from e
        if row is None:
            if current is None:
                raise WorkOrderNotFoundError(f"work_order '{wo_id}' not found")
            raise WorkOrderStateConflictError(
                wo_id=wo_id,
                current_status=current["status"],
                attempted=new_status,
                current_cet=current["approved_by_cet"],
            )
        return _row_to_wo(row)


# =====================================================================
#  Mock implementation (tests)
# =====================================================================
class MockCMMSRepository:
    """In-memory dict-backed repository for tests without PostgreSQL."""

    def __init__(self) -> None:
        self._assets: dict[str, Asset] = {}
        self._work_orders: dict[str, WorkOrder] = {}

    async def upsert_asset_async(self, asset: Asset) -> None:
        self._assets[asset.asset_id] = asset.model_copy()

    async def upsert_assets_bulk_async(self, assets: Iterable[Asset]) -> int:
        count = 0
        for a in assets:
            await self.upsert_asset_async(a)
            count += 1
        return count

    async def get_asset_async(self, asset_id: str) -> Asset:
        if asset_id not in self._assets:
            raise AssetNotFoundError(f"asset '{asset_id}' not found")
        return self._assets[asset_id]

    async def list_assets_async(
        self,
        asset_type: str | None = None,
        path: str | None = None,
        criticality_class: str | None = None,
        health_state: str | None = None,
        limit: int = 1000,
    ) -> list[Asset]:
        out = list(self._assets.values())
        if asset_type:
            out = [a for a in out if a.asset_type == asset_type]
        if path:
            out = [a for a in out if a.path == path]
        if criticality_class:
            out = [a for a in out if a.criticality_class == criticality_class]
        if health_state:
            out = [a for a in out if a.health_state == health_state]
        return sorted(out, key=lambda a: a.asset_id)[:limit]

    async def get_health_aggregate_async(self) -> list[AssetHealthAggregate]:
        # Simplified aggregation for tests
        from collections import defaultdict
        groups: dict[tuple, list[Asset]] = defaultdict(list)
        for a in self._assets.values():
            groups[(a.facility, a.path, a.redundancy_pillar, a.asset_type)].append(a)
        out = []
        for (facility, path, pillar, atype), assets in groups.items():
            wos_open = [w for w in self._work_orders.values() if w.asset_id in {a.asset_id for a in assets}
                        and w.status in ("pending_approval", "approved", "scheduled", "in_progress")]
            out.append(AssetHealthAggregate(
                facility=facility,
                path=path,
                redundancy_pillar=pillar,
                asset_type=atype,
                total=len(assets),
                healthy_count=sum(1 for a in assets if a.health_state == "healthy"),
                degraded_count=sum(1 for a in assets if a.health_state == "degraded"),
                failed_count=sum(1 for a in assets if a.health_state == "failed"),
                unknown_count=sum(1 for a in assets if a.health_state == "unknown"),
                total_open_wos=len(wos_open),
                total_overdue_wos=0,
                total_p1_wos=sum(1 for w in wos_open if w.priority == "P1"),
                aggregate_health_score=None,
            ))
        return out

    async def save_work_order_async(self, wo: WorkOrder) -> None:
        self._work_orders[wo.work_order_id] = wo.model_copy()

    async def get_work_order_async(self, wo_id: str) -> WorkOrder:
        if wo_id not in self._work_orders:
            raise WorkOrderNotFoundError(f"work_order '{wo_id}' not found")
        return self._work_orders[wo_id]

    async def list_work_orders_async(
        self,
        status: str | None = None,
        asset_id: str | None = None,
        trigger_source: str | None = None,
        priority: str | None = None,
        lor_min: int | None = None,
        only_open: bool = False,
        limit: int = 100,
    ) -> list[WorkOrder]:
        out = list(self._work_orders.values())
        if status:
            out = [w for w in out if w.status == status]
        if asset_id:
            out = [w for w in out if w.asset_id == asset_id]
        if trigger_source:
            out = [w for w in out if w.trigger_source == trigger_source]
        if priority:
            out = [w for w in out if w.priority == priority]
        if lor_min is not None:
            out = [w for w in out if w.lor >= lor_min]
        if only_open:
            out = [w for w in out if w.status in ("pending_approval", "approved", "scheduled", "in_progress")]
        return sorted(out, key=lambda w: w.timestamp, reverse=True)[:limit]

    async def transition_status_async(
        self,
        wo_id: str,
        new_status: str,
        cet_id: str,
        rejection_reason: str | None = None,
    ) -> WorkOrder:
        """Same ADR-006 audit-trail guard as PostgresCMMSRepository.

        approve / reject only legal from 'pending_approval'; otherwise
        WorkOrderStateConflictError (HTTP 409). Other transitions are
        permissive — the production state machine lives in postgres.
        """
        if wo_id not in self._work_orders:
            raise WorkOrderNotFoundError(f"work_order '{wo_id}' not found")
        wo = self._work_orders[wo_id]
        if new_status in ("approved", "rejected") and wo.status != "pending_approval":
            raise WorkOrderStateConflictError(
                wo_id=wo_id,
                current_status=wo.status,
                attempted=new_status,
                current_cet=wo.approved_by_cet,
            )
        updates: dict[str, Any] = {"status": new_status}
        # Approved: write CET only on first transition (already guarded above).
        if new_status == "approved":
            updates["approved_by_cet"] = cet_id
        # In-progress: latch assigned_to_cet on first transition.
        if new_status == "in_progress" and wo.assigned_to_cet is None:
            updates["assigned_to_cet"] = cet_id
        if new_status == "rejected":
            updates["rejection_reason"] = rejection_reason
        updated = wo.model_copy(update=updates)
        self._work_orders[wo_id] = updated
        return updated
