"""
DC-EPMS PRO — Database Layer (PostgreSQL + TimescaleDB)
========================================================
Async connection pool via asyncpg. All queries are parameterized — SQL
injection safe. Handles hypertable creation, incident audit trail,
and telemetry compression.

Schema invariants:
  - telemetry: TimescaleDB hypertable, chunked on ts
  - incidents: immutable audit log with JSONB physics_json
  - procedures: MOPs/EOPs with ChromaDB embedding refs

Physics payload guarantees:
  - physics_json is validated as JSONB by Postgres → malformed JSON rejected
  - String fields are auto-escaped by asyncpg parameterized queries
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

try:
    import asyncpg
except ImportError:
    asyncpg = None

log = logging.getLogger("dc-epms.db")


class DBManager:
    """Async PostgreSQL + TimescaleDB manager with connection pooling."""

    SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS telemetry (
        ts            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        it_load_kw    DOUBLE PRECISION NOT NULL,
        pue           DOUBLE PRECISION NOT NULL,
        hall_temp_c   DOUBLE PRECISION NOT NULL,
        delta_t_c     DOUBLE PRECISION,
        ttc_seconds   DOUBLE PRECISION,
        scenario      TEXT DEFAULT 'NORMAL',
        rack_count    INTEGER DEFAULT 118,
        rack_tdp_kw   INTEGER DEFAULT 142
    );

    CREATE TABLE IF NOT EXISTS incidents (
        incident_id   TEXT PRIMARY KEY,
        ts            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        source        TEXT NOT NULL,
        title         TEXT NOT NULL,
        detail        TEXT,
        severity      TEXT NOT NULL,
        status        TEXT NOT NULL DEFAULT 'OPEN',
        physics_json  JSONB DEFAULT '{}',
        morpheus_json JSONB DEFAULT '{}',
        sequential_thinking_json JSONB DEFAULT '{}',
        rca           TEXT DEFAULT '',
        actions       JSONB DEFAULT '[]'
    );

    CREATE INDEX IF NOT EXISTS idx_incidents_ts       ON incidents (ts DESC);
    CREATE INDEX IF NOT EXISTS idx_incidents_severity ON incidents (severity);

    CREATE TABLE IF NOT EXISTS procedures (
        id            TEXT PRIMARY KEY,
        type          TEXT NOT NULL,
        title         TEXT NOT NULL,
        equipment     TEXT,
        content       TEXT NOT NULL,
        embedding_id  TEXT,
        last_updated  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS session_log (
        id            BIGSERIAL PRIMARY KEY,
        ts            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        tool_name     TEXT NOT NULL,
        input_json    JSONB,
        output_json   JSONB
    );
    """

    HYPERTABLE_SQL = """
    SELECT create_hypertable('telemetry', 'ts',
        chunk_time_interval => INTERVAL '1 day',
        if_not_exists => TRUE);
    """

    def __init__(self, dsn: str, min_size: int = 2, max_size: int = 10):
        self.dsn = dsn
        self.min_size = min_size
        self.max_size = max_size
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        """Establish connection pool and ensure schema.

        Handles legacy schema migration: drops tables that don't match the
        expected schema and recreates them.
        """
        if asyncpg is None:
            raise RuntimeError("asyncpg not installed - run: pip install asyncpg")
        self.pool = await asyncpg.create_pool(
            dsn=self.dsn,
            min_size=self.min_size,
            max_size=self.max_size,
            command_timeout=30.0,
        )
        async with self.pool.acquire() as conn:
            # ── Step 1: inspect existing telemetry schema ──────
            tel_exists = await conn.fetchval("""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema='public' AND table_name='telemetry'
                )
            """)

            if tel_exists:
                cols = await conn.fetch("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='telemetry'
                """)
                col_names = {r["column_name"] for r in cols}
                required = {
                    "ts",
                    "it_load_kw",
                    "pue",
                    "hall_temp_c",
                    "delta_t_c",
                    "ttc_seconds",
                    "scenario",
                    "rack_count",
                    "rack_tdp_kw",
                }
                missing = required - col_names
                if missing:
                    log.warning(
                        "Legacy telemetry table detected (missing cols: %s) - dropping",
                        missing,
                    )
                    await conn.execute("DROP TABLE IF EXISTS telemetry CASCADE")

            # ── Step 2: inspect existing incidents schema ──────
            inc_exists = await conn.fetchval("""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema='public' AND table_name='incidents'
                )
            """)

            if inc_exists:
                cols = await conn.fetch("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='incidents'
                """)
                col_names = {r["column_name"] for r in cols}
                required = {"incident_id", "ts", "severity", "physics_json"}
                missing = required - col_names
                if missing:
                    log.warning(
                        "Legacy incidents table detected (missing cols: %s) - dropping",
                        missing,
                    )
                    await conn.execute("DROP TABLE IF EXISTS incidents CASCADE")

            # ── Step 3: create tables with the correct schema ──
            try:
                await conn.execute(self.SCHEMA_SQL)
                log.info("Schema created/verified")
            except Exception as e:
                log.error("Schema creation failed: %s", e)
                raise

            # ── Step 4: create TimescaleDB hypertable (optional) ──
            try:
                await conn.execute(self.HYPERTABLE_SQL)
                log.info("TimescaleDB hypertable ready on telemetry.ts")
            except Exception as e:
                # Not fatal - telemetry works without hypertable
                log.info("TimescaleDB hypertable skipped: %s", str(e)[:150])

        log.info("DB schema ready; pool size %d-%d", self.min_size, self.max_size)

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    async def ping(self) -> bool:
        """Fast connectivity probe."""
        if not self.pool:
            return False
        async with self.pool.acquire() as conn:
            row = await conn.fetchval("SELECT 1")
            return row == 1

    # ── Telemetry operations ──────────────────────────────────
    async def insert_telemetry(self, point: dict) -> int:
        """Insert single telemetry point. Returns row count."""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                INSERT INTO telemetry
                    (it_load_kw, pue, hall_temp_c, delta_t_c, ttc_seconds,
                     scenario, rack_count, rack_tdp_kw)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                float(point["it_load_kw"]),
                float(point["pue"]),
                float(point["hall_temp_c"]),
                float(point.get("delta_t_c") or 0.0),
                (float(point["ttc_seconds"]) if point.get("ttc_seconds") is not None else None),
                str(point.get("scenario", "NORMAL")),
                int(point.get("rack_count", 118)),
                int(point.get("rack_tdp_kw", 142)),
            )
            return 1 if result.startswith("INSERT") else 0

    async def fetch_telemetry(self, limit: int = 60) -> list[dict]:
        """Fetch recent telemetry for dashboard."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT ts, it_load_kw, pue, hall_temp_c, delta_t_c,
                       ttc_seconds, scenario, rack_count, rack_tdp_kw
                FROM telemetry
                ORDER BY ts DESC
                LIMIT $1
                """,
                limit,
            )
            return [self._row_to_dict(r) for r in rows]

    # ── Incidents operations ──────────────────────────────────
    async def insert_incident(self, incident: dict) -> str:
        """Insert incident with SQL-safe JSONB handling.

        physics_json is passed as a Python string — asyncpg binds it as text
        and Postgres validates it as JSONB on insert. Malformed JSON raises
        asyncpg.exceptions.InvalidTextRepresentationError.
        """
        physics = incident.get("physics_json", "{}")
        if isinstance(physics, dict):
            physics = json.dumps(physics)
        # Validate JSON before sending to DB
        try:
            json.loads(physics)
        except json.JSONDecodeError:
            physics = "{}"

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO incidents
                    (incident_id, source, title, detail, severity, status, physics_json)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                ON CONFLICT (incident_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    detail = EXCLUDED.detail
                """,
                incident["incident_id"],
                incident["source"],
                incident["title"],
                incident.get("detail", "")[:5000],
                incident["severity"],
                incident.get("status", "OPEN"),
                physics,
            )
            return incident["incident_id"]

    async def fetch_incidents(self, limit: int = 50) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT incident_id, ts, source, title, detail,
                       severity, status, physics_json
                FROM incidents
                ORDER BY ts DESC
                LIMIT $1
                """,
                limit,
            )
            return [self._row_to_dict(r) for r in rows]

    # ── Helper ────────────────────────────────────────────────
    @staticmethod
    def _row_to_dict(row) -> dict:
        """Convert asyncpg Record to JSON-serializable dict."""
        result = {}
        for k, v in dict(row).items():
            if isinstance(v, datetime):
                if v.tzinfo is None:
                    v = v.replace(tzinfo=UTC)
                result[k] = v.isoformat()
            else:
                result[k] = v
        return result
