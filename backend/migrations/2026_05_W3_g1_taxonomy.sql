-- ════════════════════════════════════════════════════════════════════
--  2026_05_W3_g1_taxonomy.sql
--  Forward migration for Sprint Bite G1 (see docs/adr/ADR-010).
--
--  The original 2026_05_W2_cmms_core.sql is an APPLIED migration with a
--  CREATE TABLE IF NOT EXISTS body -- it is left immutable. Editing it
--  would neither alter the live `dcepms` schema (IF NOT EXISTS skips an
--  existing table) nor be sound migration practice. This file ALTERs.
--
--  NOT YET APPLIED. This file is the artifact only. Apply it with:
--      psql -h 127.0.0.1 -U epms -d dcepms -f backend/migrations/2026_05_W3_g1_taxonomy.sql
--  Until it is applied, backend/cmms_seeder.py MUST keep mapping the new
--  micro-component types to 'other' (its current fallback). Widening the
--  seeder allowlist before this runs would make the next CMMS re-seed
--  violate the live assets_asset_type_check constraint.
--
--  Constraint names below are the PostgreSQL auto-generated names for
--  the inline CHECKs in W2 ({table}_{column}_check). Verify with
--  \d assets / \d work_orders if a DROP unexpectedly no-ops.
-- ════════════════════════════════════════════════════════════════════

-- ── assets: hierarchical taxonomy columns (ADR-010 containment tree) ──
ALTER TABLE assets ADD COLUMN IF NOT EXISTS asset_level     TEXT;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS parent_asset_id TEXT;

-- ── assets: Arc Flash data (NFPA 70E / IEEE 1584) ─────────────────────
ALTER TABLE assets ADD COLUMN IF NOT EXISTS fault_current_ka     DOUBLE PRECISION;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS incident_energy_cal  DOUBLE PRECISION;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS arc_flash_boundary_m DOUBLE PRECISION;

-- ── assets: widen the asset_type CHECK for G1 micro-component types
--    and the Phase-2 SLD types currently absorbed into 'other'.
ALTER TABLE assets DROP CONSTRAINT IF EXISTS assets_asset_type_check;
ALTER TABLE assets ADD CONSTRAINT assets_asset_type_check
    CHECK (asset_type IN (
        'ups', 'chiller', 'cdu', 'pump',
        'cooling_tower_field', 'cooling_tower',
        'genset', 'transformer', 'switchgear',
        'ats', 'rpp', 'busway', 'utility_intake',
        'fuel_tank', 'bms_panel', 'workstation',
        'it_rack', 'rectifier', 'sensor', 'other',
        -- G1 micro-component taxonomy types
        'system', 'battery', 'breaker', 'filter', 'valve',
        'fuel_pump', 'coolant_pump',
        -- Phase-2 SLD topology types
        'mv_rectifier', 'sscb', 'dc_bus', 'bess'
    ));

-- ── assets: optional CHECK on the new asset_level column ──────────────
ALTER TABLE assets DROP CONSTRAINT IF EXISTS assets_asset_level_check;
ALTER TABLE assets ADD CONSTRAINT assets_asset_level_check
    CHECK (asset_level IS NULL OR asset_level IN (
        'system', 'equipment', 'sub_assembly', 'component', 'sensor'
    ));

-- ── work_orders: add EMP to the procedure_class CHECK ─────────────────
ALTER TABLE work_orders DROP CONSTRAINT IF EXISTS work_orders_procedure_class_check;
ALTER TABLE work_orders ADD CONSTRAINT work_orders_procedure_class_check
    CHECK (procedure_class IN ('SOP', 'MOP', 'DMOP', 'EOP', 'EMP'));
