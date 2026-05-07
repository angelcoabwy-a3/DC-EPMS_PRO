-- =============================================================================
-- Migration: 2026_05_W2_loto_audits.sql
-- Purpose:   Create loto_audits table for LOTO Auditor Agent (Batch 4)
-- Standard:  Tier IV audit trail per ADR-006 Deterministic Sandbox
-- =============================================================================
--
-- Rationale:
--   The LOTO Auditor Agent generates audit reports that MUST persist
--   beyond the request lifecycle for the following reasons:
--
--   1. Audit trail compliance with CSA Z462-24 + NFPA 70E documentation
--      requirements (procedures must be traceable for 7+ years).
--   2. Witness gate flow requires looking up audit reports by audit_id
--      when CETs sign or reject during multi-step approval.
--   3. CHANGELOG of facility decisions: every approval or rejection
--      becomes a record for incident reconstruction.
--
-- Schema design choices:
--   - audit_id is TEXT primary key with format LOTO-AUDIT-YYYYMMDD-HHMMSS-uuidshort
--     for human readability AND uniqueness.
--   - report_json JSONB stores the full LotoAuditReport Pydantic model
--     serialization. Avoids N denormalized columns that would all need
--     to be added when pillars evolve in future ADRs.
--   - Partial indexes optimize the most common queries (hard fails,
--     pending approvals) without bloating the index for the common case.
--   - status is a constrained TEXT (no native enum) so future enum
--     extensions don't require ALTER TYPE migrations.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loto_audits (
    audit_id              TEXT PRIMARY KEY,
    timestamp             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    procedure_id          TEXT NOT NULL,
    target_component_id   TEXT NOT NULL,
    cet_on_duty           TEXT NOT NULL,
    facility              TEXT NOT NULL DEFAULT 'A3-Alpha Toronto Area',

    -- Aggregate verdict
    overall_outcome       TEXT NOT NULL CHECK (overall_outcome IN ('PASS', 'WARN', 'HARD_FAIL', 'NOT_APPLICABLE')),
    hard_fail_count       INTEGER NOT NULL CHECK (hard_fail_count >= 0),
    warn_count            INTEGER NOT NULL CHECK (warn_count >= 0),
    pass_count            INTEGER NOT NULL CHECK (pass_count >= 0),
    not_applicable_count  INTEGER NOT NULL DEFAULT 0 CHECK (not_applicable_count >= 0),

    -- State machine per ADR-006
    status                TEXT NOT NULL DEFAULT 'pending_approval'
                          CHECK (status IN ('pending_approval', 'approved', 'rejected', 'superseded')),
    rejection_reason      TEXT,
    approver_cet          TEXT,
    approved_at           TIMESTAMPTZ,
    rejected_at           TIMESTAMPTZ,

    -- Report contents (Pydantic LotoAuditReport serialized)
    report_json           JSONB NOT NULL,

    -- Provenance and performance
    decision_time_ms      INTEGER NOT NULL CHECK (decision_time_ms > 0),
    api_version           TEXT NOT NULL DEFAULT '1.0',

    -- Audit metadata
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- Indexes
-- =============================================================================

-- Primary index for chronological queries (most recent audits first)
CREATE INDEX IF NOT EXISTS idx_loto_audits_timestamp
    ON loto_audits (timestamp DESC);

-- Per-target index for "show me all audits for ups_a"
CREATE INDEX IF NOT EXISTS idx_loto_audits_target
    ON loto_audits (target_component_id, timestamp DESC);

-- Per-procedure index for "all audits of MOP-UPS-001"
CREATE INDEX IF NOT EXISTS idx_loto_audits_procedure
    ON loto_audits (procedure_id, timestamp DESC);

-- Partial index for pending approvals dashboard
CREATE INDEX IF NOT EXISTS idx_loto_audits_pending
    ON loto_audits (timestamp DESC)
    WHERE status = 'pending_approval';

-- Partial index for HARD_FAIL alerts
CREATE INDEX IF NOT EXISTS idx_loto_audits_hard_fails
    ON loto_audits (timestamp DESC)
    WHERE overall_outcome = 'HARD_FAIL';

-- CET-specific lookups for shift handover
CREATE INDEX IF NOT EXISTS idx_loto_audits_cet
    ON loto_audits (cet_on_duty, timestamp DESC);

-- =============================================================================
-- Trigger to auto-update updated_at on status changes
-- =============================================================================

CREATE OR REPLACE FUNCTION update_loto_audits_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();

    -- Auto-stamp approval/rejection timestamps when status transitions
    IF OLD.status = 'pending_approval' AND NEW.status = 'approved' THEN
        NEW.approved_at = NOW();
    ELSIF OLD.status = 'pending_approval' AND NEW.status = 'rejected' THEN
        NEW.rejected_at = NOW();
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_loto_audits_updated_at ON loto_audits;

CREATE TRIGGER trigger_loto_audits_updated_at
    BEFORE UPDATE ON loto_audits
    FOR EACH ROW
    EXECUTE FUNCTION update_loto_audits_updated_at();

-- =============================================================================
-- Verification queries (run after migration to confirm schema)
-- =============================================================================

-- SELECT COUNT(*) FROM loto_audits;
-- SELECT column_name, data_type, is_nullable FROM information_schema.columns
--     WHERE table_name = 'loto_audits' ORDER BY ordinal_position;
