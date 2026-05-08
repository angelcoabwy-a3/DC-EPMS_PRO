"""
backend/loto_auditor_repository.py
====================================
Persistence layer for LOTO audit reports (Batch 4.D).

Wraps the loto_audits PostgreSQL table created by the Batch 4.A migration
(2026_05_W2_loto_audits.sql). Exposes a sync interface for the agent
(which is sync) while delegating to asyncpg under the hood for production.

Per ADR-006 Deterministic Sandbox:
  - All audits persist in pending_approval state initially
  - Repository never auto-transitions state
  - State changes (approved, rejected) require separate explicit calls
    via approve_audit / reject_audit (witness_engine integration scope)

Design choices:
  - Idempotent save via INSERT ON CONFLICT DO UPDATE (re-running same
    audit overwrites prior report_json)
  - get_by_id raises AuditNotFoundError on miss (vs returning None)
    for explicit FastAPI 404 mapping
  - list_recent supports cursor-based pagination for HMI handover view
  - MockLotoAuditRepository provided for tests (in-memory dict)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from loto_auditor_models import LotoAuditReport

log = logging.getLogger(__name__)


# =============================================================================
#  Exceptions
# =============================================================================

class RepositoryError(RuntimeError):
    """Base exception for repository failures (connection, query)."""


class AuditNotFoundError(RepositoryError):
    """Raised when audit_id is not present in the repository."""


# =============================================================================
#  Protocol (interface contract)
# =============================================================================

class LotoAuditRepositoryProtocol(Protocol):
    """Repository interface contract.

    Production: PostgresLotoAuditRepository
    Tests: MockLotoAuditRepository
    """

    def save(self, report: LotoAuditReport) -> None:
        """Persist an audit report. Idempotent on audit_id."""
        ...

    def get_by_id(self, audit_id: str) -> LotoAuditReport:
        """Fetch a report by audit_id. Raises AuditNotFoundError on miss."""
        ...

    def list_recent(self, limit: int = 50) -> list[LotoAuditReport]:
        """Return up to `limit` most-recent reports, descending by timestamp."""
        ...


# =============================================================================
#  Postgres implementation (production)
# =============================================================================

class PostgresLotoAuditRepository:
    """asyncpg-backed repository for loto_audits table.

    NOTE: this class wraps async pool calls in synchronous facade methods
    using asyncio.run() helpers. The reason: the LotoAuditorAgent is sync
    by design (deterministic, cpu-bound). FastAPI routes that call the
    agent and then this repository are async-aware and use the async
    methods directly.
    """

    def __init__(self, asyncpg_pool: Any) -> None:
        """Initialize with an asyncpg connection pool.

        The pool is typically obtained via main.py lifespan startup and
        injected into route handlers via FastAPI Depends().
        """
        self._pool = asyncpg_pool

    async def save_async(self, report: LotoAuditReport) -> None:
        """Persist a report (async path used by FastAPI route handlers).

        Idempotent: re-saving the same audit_id updates report_json, status,
        outcome counts, and updated_at trigger fires automatically.
        """
        report_dict = report.model_dump(mode="json")
        report_json_str = json.dumps(report_dict, default=str)

        sql = """
        INSERT INTO loto_audits (
            audit_id, timestamp, procedure_id, target_component_id,
            cet_on_duty, facility,
            overall_outcome, hard_fail_count, warn_count, pass_count,
            not_applicable_count,
            status, rejection_reason, approver_cet,
            report_json, decision_time_ms, api_version
        ) VALUES (
            $1, $2, $3, $4,
            $5, $6,
            $7, $8, $9, $10,
            $11,
            $12, $13, $14,
            $15::jsonb, $16, $17
        )
        ON CONFLICT (audit_id) DO UPDATE SET
            overall_outcome = EXCLUDED.overall_outcome,
            hard_fail_count = EXCLUDED.hard_fail_count,
            warn_count = EXCLUDED.warn_count,
            pass_count = EXCLUDED.pass_count,
            not_applicable_count = EXCLUDED.not_applicable_count,
            status = EXCLUDED.status,
            report_json = EXCLUDED.report_json,
            decision_time_ms = EXCLUDED.decision_time_ms
        ;
        """

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    sql,
                    report.audit_id, report.timestamp, report.procedure_id,
                    report.target_component_id, report.cet_on_duty,
                    report.facility,
                    report.overall_outcome.value, report.hard_fail_count,
                    report.warn_count, report.pass_count,
                    report.not_applicable_count,
                    report.status.value, report.rejection_reason,
                    report.approver_cet,
                    report_json_str, report.decision_time_ms,
                    report.api_version,
                )
            log.info("Persisted LOTO audit %s (outcome=%s)",
                     report.audit_id, report.overall_outcome.value)
        except Exception as e:
            log.exception("Failed to persist audit %s: %s", report.audit_id, e)
            raise RepositoryError(
                f"Failed to save audit {report.audit_id}: {e}"
            ) from e

    async def get_by_id_async(self, audit_id: str) -> LotoAuditReport:
        """Fetch a report by audit_id (async)."""
        sql = "SELECT report_json FROM loto_audits WHERE audit_id = $1;"
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(sql, audit_id)
        except Exception as e:
            raise RepositoryError(
                f"Query failed for audit {audit_id}: {e}"
            ) from e

        if row is None:
            raise AuditNotFoundError(
                f"Audit '{audit_id}' not found in repository"
            )

        report_json = row["report_json"]
        # asyncpg returns JSONB as string in some configs, dict in others
        if isinstance(report_json, str):
            report_dict = json.loads(report_json)
        else:
            report_dict = report_json
        return LotoAuditReport.model_validate(report_dict)

    async def list_recent_async(
        self,
        limit: int = 50,
    ) -> list[LotoAuditReport]:
        """Return most-recent audits (async)."""
        sql = """
        SELECT report_json FROM loto_audits
        ORDER BY timestamp DESC
        LIMIT $1;
        """
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(sql, limit)
        except Exception as e:
            raise RepositoryError(f"List query failed: {e}") from e

        results = []
        for row in rows:
            report_json = row["report_json"]
            if isinstance(report_json, str):
                report_dict = json.loads(report_json)
            else:
                report_dict = report_json
            try:
                results.append(LotoAuditReport.model_validate(report_dict))
            except Exception as e:
                log.warning("Skipping malformed audit row: %s", e)
        return results


# =============================================================================
#  Mock implementation (tests)
# =============================================================================

class MockLotoAuditRepository:
    """In-memory dict-backed repository for tests.

    Implements the same async methods as PostgresLotoAuditRepository so
    tests can swap via FastAPI dependency_overrides without touching
    actual SQL.

    Idempotent save: re-saving same audit_id replaces existing entry.
    """

    def __init__(self) -> None:
        self._store: dict[str, LotoAuditReport] = {}
        self._save_count = 0

    async def save_async(self, report: LotoAuditReport) -> None:
        # Deep-copy via Pydantic round-trip to avoid mutation surprises
        snapshot_dict = report.model_dump(mode="python")
        self._store[report.audit_id] = LotoAuditReport.model_validate(snapshot_dict)
        self._save_count += 1

    async def get_by_id_async(self, audit_id: str) -> LotoAuditReport:
        if audit_id not in self._store:
            raise AuditNotFoundError(
                f"Audit '{audit_id}' not found in mock repository"
            )
        return self._store[audit_id]

    async def list_recent_async(
        self,
        limit: int = 50,
    ) -> list[LotoAuditReport]:
        sorted_audits = sorted(
            self._store.values(),
            key=lambda r: r.timestamp,
            reverse=True,
        )
        return sorted_audits[:limit]

    @property
    def store_size(self) -> int:
        """Test introspection: how many audits are currently held."""
        return len(self._store)

    @property
    def save_count(self) -> int:
        """Test introspection: how many save calls have been made.

        Differs from store_size when same audit_id is saved multiple times.
        """
        return self._save_count

    def clear(self) -> None:
        """Test helper: reset store between test methods."""
        self._store.clear()
        self._save_count = 0
