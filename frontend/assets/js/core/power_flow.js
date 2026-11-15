/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — frontend/assets/js/core/power_flow.js
 *
 * Steady-state power flow for the Phase 1 closed design, as drawn on
 * the Power SLD. Pure: (DAG grid state, facility IT load) -> per-path
 * numbers. No DOM, no fetch.
 *
 * Why: the SLD showed the physics engine's unit-level samples (a
 * 300 kW "UPS", a 1,800 kVA transformer) next to a design of 8 x 2.5
 * MW blocks per path. Those numbers contradicted the drawing. This
 * module derives the drawn numbers from the design instead:
 *
 *   share      2N: each live path carries 50 %; one live path 100 %.
 *   upsOutKw   itKw x share  (IT load leaves the UPS bank)
 *   perBlock   upsOutKw / blocks in service (blocks share equally)
 *   lossKw     upsOutKw x (1 / eta - 1), eta = 0.97 double conversion
 *   upsInKw    upsOutKw + lossKw (0 while on battery)
 *   kva        upsInKw / pf, pf = 0.9 (same assumption as the v2
 *              site model sizing). Carried by the MV switchgear and
 *              unit substations, and by the utility transformer only
 *              when the path rides the utility.
 *   genKw      upsInKw when the path rides the generator bus.
 *
 * Honest scope: battery recharge, cooling and auxiliary loads on the
 * 480 V boards are NOT in these numbers (UPS path only). The values
 * are a design-consistent model, not metering.
 * ════════════════════════════════════════════════════════════════ */

import { PHASE1 } from './power_grid.js';

export const PF = 0.9;
// HMI H3 nameplate values for the drawn data tags (design, not metering):
// 60 Hz (Ontario grid), 13.8 kV MV bus and 480 V LV (config/power_plant.yml),
// UPS autonomy at full bank load = runtime_full_load_min (operator documents
// give 8 to 12 min; the design file holds 10).
export const NOMINAL_HZ = 60;
export const MV_KV = 13.8;
export const LV_V = 480;
export const UPS_RUNTIME_SPEC_MIN = 10;

/** Reactive power for a real power at a power factor: Q = P tan(acos pf). */
export function reactiveKvar(kw, pf = PF) {
    if (!Number.isFinite(kw) || kw <= 0 || !(pf > 0 && pf <= 1)) return 0;
    return kw * Math.tan(Math.acos(pf));
}
export const DEFAULT_IT_KW = PHASE1.itLoadPerPathKw;   // 16.76 MW facility IT

/**
 * @param {object|null} grid   power_grid snapshot (getGridState / state 'grid')
 * @param {number} [itKw]      facility Phase 1 IT load in kW
 * @returns {{a: object, b: object, itKw: number}}
 */
export function pathFlows(grid, itKw = DEFAULT_IT_KW) {
    const it = Number.isFinite(itKw) && itKw > 0 ? itKw : DEFAULT_IT_KW;
    const g = grid || {};
    const live = (p) => !!(g['ups_' + p] ? g['ups_' + p].alive : true);
    const la = live('a'), lb = live('b');
    const nLive = (la ? 1 : 0) + (lb ? 1 : 0);
    const out = { itKw: it };
    for (const p of ['a', 'b']) {
        const ups = g['ups_' + p] || {};
        const isLive = p === 'a' ? la : lb;
        const share = isLive && nLive > 0 ? 1 / nLive : 0;
        const upsOutKw = it * share;
        const blocksIn = Math.max(0, PHASE1.ups.units - (ups.units_out || 0));
        const onBattery = !!ups.on_battery;
        const lossKw = upsOutKw * (1 / PHASE1.ups.eta - 1);
        const upsInKw = onBattery ? 0 : upsOutKw + lossKw;
        const source = !isLive ? null
            : (onBattery ? 'battery' : (ups.energized_by || 'util'));
        const kva = upsInKw / PF;
        const capKw = blocksIn * PHASE1.ups.unitKw;
        const genCapKw = Math.max(0, PHASE1.gen.units - ((g['genset_' + p] || {}).units_out || 0))
            * PHASE1.gen.unitKw;
        out[p] = {
            share,
            source,
            upsOutKw,
            blocksIn,
            perBlockKw: blocksIn > 0 ? upsOutKw / blocksIn : 0,
            upsLoadPct: capKw > 0 ? (upsOutKw / capKw) * 100 : 0,
            lossKw: onBattery ? 0 : lossKw,
            upsInKw,
            mvKva: kva,
            xfmrKva: source === 'util' ? kva : 0,
            genKw: source === 'genset' ? upsInKw : 0,
            genLoadPct: source === 'genset' && genCapKw > 0 ? (upsInKw / genCapKw) * 100 : 0,
            rppKw: upsOutKw / 2,
        };
    }
    return out;
}

/** "8.38 MW" / "940 kW" — compact power label for the drawing. */
export function fmtPower(kw) {
    if (!Number.isFinite(kw) || kw <= 0) return '0 kW';
    return kw >= 1000 ? `${(kw / 1000).toFixed(2)} MW` : `${Math.round(kw)} kW`;
}

/** Same for apparent power. */
export function fmtApparent(kva) {
    if (!Number.isFinite(kva) || kva <= 0) return '0 kVA';
    return kva >= 1000 ? `${(kva / 1000).toFixed(2)} MVA` : `${Math.round(kva)} kVA`;
}

/** "4.18 Mvar" / "420 kvar" for a real power at the model power factor. */
export function fmtReactive(kw, pf = PF) {
    const q = reactiveKvar(kw, pf);
    if (q <= 0) return '0 kvar';
    return q >= 1000 ? `${(q / 1000).toFixed(2)} Mvar` : `${Math.round(q)} kvar`;
}
