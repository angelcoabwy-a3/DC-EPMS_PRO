-- =============================================================================
-- Migration: 2026_05_W2_cmms_core.sql
-- Purpose:   CMMS Core v1.0 schema -- assets + work_orders + triggers
-- Standard:  Tier IV asset lifecycle management per ISO 55001 + a3semi OPS
-- =============================================================================
--
-- Context:
--   Wilmer 2026-05-09 CET directive: "MOPs must stop being documents and
--   become Operational Entities." This migration creates the persistent
--   layer that turns Sprint 5 telemetry anomalies into actionable work
--   orders, links them to executable MOP YAMLs (T4-MOP-CHI-001, T4-MOP-
--   UPS-001, etc.), and feeds back into the Site Health Index.
--
-- Schema design choices (mirroring loto_audits pattern):
--   - asset_id / work_order_id are TEXT primary keys for human readability
--     and stability across replicas. asset_id matches site_model.yml
--     canonical_id verbatim (e.g. ups_a, chiller_1, rack_a_01_05).
--   - Constrained TEXT fields (no native ENUM) so future state machine
--     extensions don't require ALTER TYPE.
--   - JSONB payloads for draft_json / predictive_metadata / result_json
--     avoid N denormalized columns when LOR scoring or THA shapes evolve.
--   - Partial indexes optimize the high-frequency operator queries
--     (open WOs, overdue WOs, predictive WOs by channel) without bloating
--     the index for the steady-state.
--   - updated_at trigger pattern matches loto_audits for consistency.
--
-- Integration points:
--   - Sprint 5 C2 telemetry_pipeline.compute() emits anomalies -> CMMS
--     trigger creates WO with trigger_source='predictive_kalman'.
--   - LOTO audits link WO -> linked_loto_audit_id (FK soft).
--   - physics_engine.validate_site() can read overdue WO count to drop
--     SHI severity (Wilmer requirement: critical infrastructure with
--     overdue maintenance is NOT healthy regardless of telemetry).
-- =============================================================================


-- =============================================================================
-- Table 1: assets
--
-- Canonical asset registry. Seeded from config/site_model.yml on first
-- boot via a migrate-and-seed routine (separate from this DDL).
-- =============================================================================

CREATE TABLE IF NOT EXISTS assets (
    asset_id              TEXT PRIMARY KEY,
    display_name          TEXT NOT NULL,
    asset_type            TEXT NOT NULL
                          CHECK (asset_type IN (
                              'ups', 'chiller', 'cdu', 'pump',
                              'cooling_tower_field', 'cooling_tower',
                              'genset', 'transformer', 'switchgear',
                              'ats', 'rpp', 'busway', 'utility_intake',
                              'fuel_tank', 'bms_panel', 'workstation',
                              'it_rack', 'rectifier', 'sensor', 'other'
                          )),
    facility              TEXT NOT NULL DEFAULT 'A3-Alpha Toronto Area',
    location_path         TEXT,
    vendor                TEXT,
    model                 TEXT,
    rated_capacity_kw     NUMERIC(10, 2),
    rated_capacity_unit   TEXT DEFAULT 'kW',

    -- MOP linkage. NULL means no executable MOP exists yet for this
    -- asset_type; the agent will fall back to manual procedure draft.
    linked_mop_id         TEXT,

    -- Derived health (updated by background process from telemetry +
    -- overdue WOs). Source of truth for the HMI Maintenance view.
    health_state          TEXT NOT NULL DEFAULT 'healthy'
                          CHECK (health_state IN (
                              'healthy', 'degraded', 'failed', 'unknown'
                          )),
    last_health_update_at TIMESTAMPTZ,

    -- Maintenance schedule
    last_pm_completed_at  TIMESTAMPTZ,
    next_pm_due_at        TIMESTAMPTZ,
    pm_interval_days      INTEGER,

    metadata_json         JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_assets_type
    ON assets (asset_type);

CREATE INDEX IF NOT EXISTS idx_assets_health
    ON assets (health_state)
    WHERE health_state IN ('degraded', 'failed');

CREATE INDEX IF NOT EXISTS idx_assets_pm_due
    ON assets (next_pm_due_at)
    WHERE next_pm_due_at IS NOT NULL;


-- =============================================================================
-- Table 2: work_orders
--
-- Persistent CMMS work orders. Replaces the in-memory drafts produced by
-- backend/cmms_mcp.tool_draft_cmms_work_order. Drafts that the operator
-- approves at the HMI become rows here.
--
-- Trigger sources:
--   manual            CET-initiated via HMI Maintenance form
--   predictive_kalman Anomaly detector (Sprint 5 C2 pipeline)
--   scheduled_pm     Calendar-driven PM
--   incident         Triggered by an incident in the incidents table
--   loto_audit       Triggered by a HARD_FAIL LOTO audit
-- =============================================================================

CREATE TABLE IF NOT EXISTS work_orders (
    work_order_id         TEXT PRIMARY KEY,
    timestamp             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Asset linkage (soft FK; assets row may be deleted if asset
    -- decommissioned but historical WOs preserve asset_id label)
    asset_id              TEXT NOT NULL,
    asset_type_at_creation TEXT NOT NULL,

    -- Classification (from cmms_mcp LOR scoring)
    work_class            TEXT NOT NULL CHECK (work_class IN ('PM', 'CM', 'EM')),
    lor                   INTEGER NOT NULL CHECK (lor BETWEEN 1 AND 25),
    procedure_class       TEXT CHECK (procedure_class IN ('SOP', 'MOP', 'DMOP', 'EOP')),

    -- MOP linkage (e.g. T4-MOP-UPS-001 for ups asset_type)
    linked_mop_id         TEXT,

    -- LOTO audit linkage (set when WO requires LOTO and audit was run)
    linked_loto_audit_id  TEXT,

    -- Provenance
    trigger_source        TEXT NOT NULL
                          CHECK (trigger_source IN (
                              'manual', 'predictive_kalman',
                              'scheduled_pm', 'incident', 'loto_audit'
                          )),
    predictive_metadata   JSONB,  -- anomaly z-score, channel_id, sustained_count

    -- Operator-facing details
    issue_summary         TEXT NOT NULL,
    estimated_cost_usd    NUMERIC(12, 2) DEFAULT 0,
    requires_loto         BOOLEAN NOT NULL DEFAULT FALSE,
    requires_oem_specialist BOOLEAN NOT NULL DEFAULT FALSE,

    -- Lifecycle (state machine)
    status                TEXT NOT NULL DEFAULT 'pending_approval'
                          CHECK (status IN (
                              'pending_approval',
                              'approved',
                              'scheduled',
                              'in_progress',
                              'completed',
                              'rejected',
                              'cancelled',
                              'overdue'
                          )),

    -- People
    requested_by          TEXT,
    assigned_to_cet       TEXT,
    approved_by_cet       TEXT,
    rejection_reason      TEXT,

    -- Timeline
    due_at                TIMESTAMPTZ,
    approved_at           TIMESTAMPTZ,
    scheduled_at          TIMESTAMPTZ,
    started_at            TIMESTAMPTZ,
    completed_at          TIMESTAMPTZ,
    rejected_at           TIMESTAMPTZ,
    cancelled_at          TIMESTAMPTZ,

    -- Full draft from tool_draft_cmms_work_order (preserves THA, LOR
    -- breakdown, contractor attachments, etc.) and post-execution result
    draft_json            JSONB NOT NULL,
    result_json           JSONB,

    api_version           TEXT NOT NULL DEFAULT '1.0',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- =============================================================================
-- Indexes
-- =============================================================================

-- Most-recent first for the Maintenance view backlog
CREATE INDEX IF NOT EXISTS idx_work_orders_timestamp
    ON work_orders (timestamp DESC);

-- "Show me all open WOs": pending_approval + approved + scheduled + in_progress
CREATE INDEX IF NOT EXISTS idx_work_orders_open
    ON work_orders (timestamp DESC)
    WHERE status IN ('pending_approval', 'approved', 'scheduled', 'in_progress');

-- "Show me overdue WOs": due_at passed and not closed
CREATE INDEX IF NOT EXISTS idx_work_orders_overdue
    ON work_orders (due_at)
    WHERE due_at < NOW()
      AND status NOT IN ('completed', 'rejected', 'cancelled');

-- Pending approval for the operator approval inbox
CREATE INDEX IF NOT EXISTS idx_work_orders_pending
    ON work_orders (timestamp DESC)
    WHERE status = 'pending_approval';

-- Per-asset lookup for "all WOs for ups_a"
CREATE INDEX IF NOT EXISTS idx_work_orders_asset
    ON work_orders (asset_id, timestamp DESC);

-- Per-trigger-source lookup for "all predictive WOs from Kalman"
CREATE INDEX IF NOT EXISTS idx_work_orders_trigger
    ON work_orders (trigger_source, timestamp DESC);

-- LOR-prioritized queue for daily standup
CREATE INDEX IF NOT EXISTS idx_work_orders_lor
    ON work_orders (lor DESC, timestamp DESC)
    WHERE status IN ('pending_approval', 'approved', 'scheduled');

-- CET-specific lookup for shift handover
CREATE INDEX IF NOT EXISTS idx_work_orders_cet
    ON work_orders (assigned_to_cet, timestamp DESC)
    WHERE assigned_to_cet IS NOT NULL;


-- =============================================================================
-- Triggers (mirror loto_audits pattern)
-- =============================================================================

CREATE OR REPLACE FUNCTION update_assets_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    IF (NEW.health_state IS DISTINCT FROM OLD.health_state) THEN
        NEW.last_health_update_at = NOW();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_assets_updated_at ON assets;
CREATE TRIGGER trigger_assets_updated_at
    BEFORE UPDATE ON assets
    FOR EACH ROW
    EXECUTE FUNCTION update_assets_updated_at();


CREATE OR REPLACE FUNCTION update_work_orders_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();

    -- Auto-stamp lifecycle transitions
    IF OLD.status = 'pending_approval' AND NEW.status = 'approved' THEN
        NEW.approved_at = NOW();
    ELSIF OLD.status = 'pending_approval' AND NEW.status = 'rejected' THEN
        NEW.rejected_at = NOW();
    ELSIF OLD.status = 'approved' AND NEW.status = 'scheduled' THEN
        NEW.scheduled_at = NOW();
    ELSIF NEW.status = 'in_progress' AND OLD.status != 'in_progress' THEN
        NEW.started_at = NOW();
    ELSIF NEW.status = 'completed' AND OLD.status != 'completed' THEN
        NEW.completed_at = NOW();
    ELSIF NEW.status = 'cancelled' AND OLD.status != 'cancelled' THEN
        NEW.cancelled_at = NOW();
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_work_orders_updated_at ON work_orders;
CREATE TRIGGER trigger_work_orders_updated_at
    BEFORE UPDATE ON work_orders
    FOR EACH ROW
    EXECUTE FUNCTION update_work_orders_updated_at();


-- =============================================================================
-- View: open_work_orders_summary
-- Used by physics_engine SHI integration and the HMI Maintenance dashboard.
-- =============================================================================

CREATE OR REPLACE VIEW open_work_orders_summary AS
SELECT
    asset_id,
    asset_type_at_creation AS asset_type,
    COUNT(*) FILTER (WHERE status IN ('pending_approval', 'approved', 'scheduled', 'in_progress')) AS open_count,
    COUNT(*) FILTER (WHERE due_at < NOW()
                       AND status NOT IN ('completed', 'rejected', 'cancelled')) AS overdue_count,
    MAX(lor) FILTER (WHERE status IN ('pending_approval', 'approved', 'scheduled', 'in_progress')) AS max_open_lor,
    MIN(due_at) FILTER (WHERE status NOT IN ('completed', 'rejected', 'cancelled')) AS earliest_due_at
FROM work_orders
GROUP BY asset_id, asset_type_at_creation;


-- =============================================================================
-- Verification queries (run after migration to confirm schema)
-- =============================================================================

-- Inventory check (expect 0 rows on fresh deploy):
--   SELECT COUNT(*) FROM assets;
--   SELECT COUNT(*) FROM work_orders;

-- Schema check:
--   SELECT column_name, data_type, is_nullable FROM information_schema.columns
--       WHERE table_name = 'work_orders' ORDER BY ordinal_position;

-- View check:
--   SELECT * FROM open_work_orders_summary LIMIT 5;
