/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — frontend/assets/js/core/plant_mirror.js
 *
 * DC-EPMS-073: in LIVE mode the Power SLD drawing follows the
 * simulated Power Controls plant (GET /api/devices), the same plant
 * the alarm banner reads. Before this, LIVE drew the nominal browser
 * DAG, so a transfer to generators done in Power Controls raised an
 * alarm while the drawing still showed the utility.
 *
 * mirrorGrid(baseGrid, plant) -> a NEW grid object:
 *   transfer device state  -> mvtc_x ats_pos (UTILITY / GENERATORS)
 *   generator states       -> genset_x running / state, units_out
 *   UPS blocks in service  -> ups_x units_out
 *   UPS blocks on bypass   -> ups_x plant_mode = 'static_bypass'
 *   all blocks Dynamic Online -> plant_mode = 'dynamic_online'
 *   utility lost (T1)      -> util_x tripped; transfer OPEN -> both
 *                             mains open (52-U TRIP when ANSI 27)
 *   battery SOC / load lost -> batt_x soc (0 when the load was lost)
 * then the pure flow pass of power_grid.js (propagateStatic).
 *
 * What the plant does NOT model is left as the base grid has it:
 * Phase 2 Building D. Pure module: no DOM,
 * no fetch, never mutates its inputs, never writes to the plant.
 * ════════════════════════════════════════════════════════════════ */

import { propagateStatic } from './power_grid.js';

const GEN_LIVE = new Set(['RUNNING', 'ON_LOAD']);

function _genState(states) {
    if (states.some((s) => GEN_LIVE.has(s))) return 'running';
    if (states.includes('CRANKING')) return 'cranking';
    if (states.includes('COOLDOWN')) return 'cooldown';
    return 'standby';
}

/** Validate the GET /api/devices payload shape we rely on. */
export function isPlantSnapshot(plant) {
    return !!plant && Array.isArray(plant.devices) && Array.isArray(plant.paths);
}

export function mirrorGrid(baseGrid, plant) {
    if (!baseGrid || !isPlantSnapshot(plant)) return baseGrid;
    const g = {};
    for (const id of Object.keys(baseGrid)) g[id] = { ...baseGrid[id] };

    for (const p of ['a', 'b']) {
        const devs = plant.devices.filter((d) => String(d.path).toLowerCase() === p);
        const summary = plant.paths.find((s) => String(s.path).toLowerCase() === p);
        if (!devs.length || !summary) continue;

        // T1: utility loss (ANSI 27) and the dead-bus OPEN state.
        const util = g['util_' + p];
        if (util && summary.utility_ok === false) util.tripped = true;
        const tc = g['mvtc_' + p];
        const xfer = devs.find((d) => d.kind === 'transfer');
        if (tc && xfer) {
            tc.ats_pos = xfer.state === 'GENERATORS' ? 'secondary'
                : (xfer.state === 'OPEN' ? 'open' : 'primary');
            tc.transferring = false;
            // 52-U tripped by ANSI 27 shows TRIP on the drawing.
            tc.tripped = xfer.state === 'OPEN' && summary.utility_ok === false;
        }
        const batt = g['batt_' + p];
        if (batt && summary.battery_soc_pct != null) {
            batt.soc = summary.load_lost ? 0 : Number(summary.battery_soc_pct);
        }

        const gen = g['genset_' + p];
        const gens = devs.filter((d) => d.kind === 'generator');
        if (gen && gens.length) {
            gen.state = _genState(gens.map((d) => d.state));
            gen.running = gen.state === 'running';
            const total = Number(summary.gen_total) || gens.length;
            gen.units_out = Math.max(0, total - (Number(summary.gen_available) || 0));
        }

        const ups = g['ups_' + p];
        const blocks = devs.filter((d) => d.kind === 'ups');
        if (ups && blocks.length) {
            const total = Number(summary.ups_total) || blocks.length;
            ups.units_out = Math.max(0, total - (Number(summary.ups_in_service) || 0));
        }
    }

    const out = propagateStatic(g);
    for (const p of ['a', 'b']) {
        const ups = out['ups_' + p];
        if (!ups) continue;
        const carrying = plant.devices.filter((d) => d.kind === 'ups'
            && String(d.path).toLowerCase() === p && d.state !== 'ISOLATED');
        ups.plant_mode = null;
        if (ups.alive && !ups.on_battery && carrying.length) {
            if (carrying.some((d) => d.state === 'STATIC_BYPASS')) ups.plant_mode = 'static_bypass';
            else if (carrying.every((d) => d.state === 'DYNAMIC_ONLINE')) ups.plant_mode = 'dynamic_online';
        }
        ups.bypass_blocks = carrying.filter((d) => d.state === 'STATIC_BYPASS').length;
    }
    return out;
}

/** UPS mode caption for the drawing (number of blocks on static bypass), or null to keep the default. */
export function plantModeLabel(ups) {
    if (!ups || !ups.plant_mode) return null;
    if (ups.plant_mode === 'static_bypass') return `BYPASS × ${ups.bypass_blocks}`;
    if (ups.plant_mode === 'dynamic_online') return 'DYNAMIC ONLINE';
    return null;
}
