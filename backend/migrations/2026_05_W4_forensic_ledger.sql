-- ============================================================================
--  2026_05_W4_forensic_ledger.sql
--  Forward migration for ADR-011 (Forensic Ledger).
--
--  Closes DC-EPMS-MSD-001 + DC-EPMS-MSD-002 from the 2026-05-22 MSD audit.
--
--  NOT YET APPLIED. This file is the artifact only. Apply it with:
--      psql -h 127.0.0.1 -U epms -d dcepms -f backend/migrations/2026_05_W4_forensic_ledger.sql
--
--  Until it is applied, backend/main.py's lifespan boot path keeps the
--  forensic ledger on InMemoryPersistence (set via env probe). Applying
--  this migration AND restarting the backend switches it to
--  PostgresPersistence. Per S-RUNTIME-01 the restart is mandatory — the
--  backend does not hot-reload.
--
--  Idempotency: every statement is IF NOT EXISTS / OR REPLACE so this
--  file is safe to re-run.
-- ============================================================================

-- ── Table ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ledger_entries (
    entry_id      UUID        PRIMARY KEY,
    sequence_no   BIGSERIAL   UNIQUE NOT NULL,
    ts            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor         TEXT        NOT NULL,
    action        TEXT        NOT NULL,
    payload       JSONB       NOT NULL,
    prev_hash     BYTEA       NOT NULL,
    entry_hmac    BYTEA       NOT NULL,
    key_version   INTEGER     NOT NULL DEFAULT 1,
    CONSTRAINT ledger_entries_hmac_len_check CHECK (octet_length(entry_hmac) = 32),
    CONSTRAINT ledger_entries_prev_hash_len_check
        CHECK (octet_length(prev_hash) = 0 OR octet_length(prev_hash) = 32),
    CONSTRAINT ledger_entries_actor_nonempty   CHECK (char_length(actor) > 0),
    CONSTRAINT ledger_entries_action_nonempty  CHECK (char_length(action) > 0)
);

-- ── Indexes ─────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_ledger_entries_ts
    ON ledger_entries (ts DESC);

CREATE INDEX IF NOT EXISTS idx_ledger_entries_actor_action
    ON ledger_entries (actor, action);

CREATE INDEX IF NOT EXISTS idx_ledger_entries_action_ts
    ON ledger_entries (action, ts DESC);

-- ── Immutability triggers (IEC 62443-3-3 SR 6.1 / NIST SP 800-53r5 AU-9) ───
CREATE OR REPLACE FUNCTION ledger_entries_immutable_guard()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'ledger_entries is append-only (IEC 62443-3-3 SR 6.1, ADR-011)';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS ledger_entries_no_update ON ledger_entries;
CREATE TRIGGER ledger_entries_no_update
    BEFORE UPDATE ON ledger_entries
    FOR EACH ROW EXECUTE FUNCTION ledger_entries_immutable_guard();

DROP TRIGGER IF EXISTS ledger_entries_no_delete ON ledger_entries;
CREATE TRIGGER ledger_entries_no_delete
    BEFORE DELETE ON ledger_entries
    FOR EACH ROW EXECUTE FUNCTION ledger_entries_immutable_guard();

DROP TRIGGER IF EXISTS ledger_entries_no_truncate ON ledger_entries;
CREATE TRIGGER ledger_entries_no_truncate
    BEFORE TRUNCATE ON ledger_entries
    FOR EACH STATEMENT EXECUTE FUNCTION ledger_entries_immutable_guard();

-- ── TimescaleDB hypertable (optional — skipped if extension missing) ────────
-- The chunk window is 30 days: at ~100 ops/day * 2 entries per op the table
-- grows ~6000 rows/month, well within a single chunk for query efficiency.
-- See ADR-011 §Storage growth.
DO $$
BEGIN
    PERFORM 1 FROM pg_extension WHERE extname = 'timescaledb';
    IF FOUND THEN
        PERFORM create_hypertable(
            'ledger_entries', 'ts',
            chunk_time_interval => INTERVAL '30 days',
            if_not_exists       => TRUE,
            migrate_data        => TRUE
        );
    END IF;
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'TimescaleDB hypertable skipped: %', SQLERRM;
END
$$;

-- ── Comment metadata (audit-tool readable) ──────────────────────────────────
COMMENT ON TABLE  ledger_entries IS
    'Forensic ledger (ADR-011). HMAC-SHA256 chained, append-only. '
    'IEC 62443-3-3 SR 6.1 / SR 6.2 / SR 7.3 / SR 7.4.';
COMMENT ON COLUMN ledger_entries.entry_id     IS 'UUID v4 — primary key.';
COMMENT ON COLUMN ledger_entries.sequence_no  IS
    'BIGSERIAL gapless monotonic — chain order. UNIQUE.';
COMMENT ON COLUMN ledger_entries.prev_hash    IS
    '32-byte entry_hmac of the predecessor entry. '
    'b'''' (length 0) for the genesis entry by convention.';
COMMENT ON COLUMN ledger_entries.entry_hmac   IS
    'HMAC-SHA256(key[version], '
    'prev_hash || entry_id || ts_iso || actor || action '
    '|| sha256(canonical_json(payload))).';
COMMENT ON COLUMN ledger_entries.key_version  IS
    '0 = ephemeral dev key (unverifiable across restarts). '
    '>=1 = configured production key. Increments on rotation.';
