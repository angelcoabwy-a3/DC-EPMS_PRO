/* DC-EPMS-073: the LIVE drawing follows the Power Controls plant. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mirrorGrid, plantModeLabel, isPlantSnapshot } from '/assets/js/core/plant_mirror.js';
import { initPowerGrid, restoreAll, getGridState, propagateStatic } from '/assets/js/core/power_grid.js';
import { pathFlows } from '/assets/js/core/power_flow.js';

function plant({ xferA = 'UTILITY', genA = 'STANDBY', upsA = [], genOutA = 0, upsOutA = 0 } = {}) {
    const devices = [];
    const paths = [];
    for (const p of ['a', 'b']) {
        const isA = p === 'a';
        devices.push({ id: `mvtc_${p}`, kind: 'transfer', path: p, state: isA ? xferA : 'UTILITY' });
        for (let i = 1; i <= 9; i++) {
            devices.push({ id: `genset_${p}_0${i}`, kind: 'generator', path: p,
                state: isA ? genA : 'STANDBY' });
        }
        for (let i = 1; i <= 8; i++) {
            const st = (isA && upsA[i - 1]) || 'DOUBLE_CONVERSION';
            devices.push({ id: `ups_${p}_0${i}`, kind: 'ups', path: p, state: st });
        }
        const upsIso = devices.filter((d) => d.kind === 'ups' && d.path === p && d.state === 'ISOLATED').length;
        paths.push({
            path: p, source: isA && xferA === 'GENERATORS' ? 'GENERATORS' : 'UTILITY',
            ups_total: 8, ups_in_service: 8 - upsIso - (isA ? upsOutA : 0),
            gen_total: 9, gen_available: 9 - (isA ? genOutA : 0),
        });
    }
    return { devices, paths };
}

describe('plant_mirror', () => {
    beforeEach(() => { vi.useFakeTimers(); initPowerGrid(); });
    afterEach(() => { restoreAll(); vi.useRealTimers(); });

    it('healthy plant mirrors the nominal grid', () => {
        const base = getGridState();
        const g = mirrorGrid(base, plant());
        expect(g.mvtc_a.ats_pos).toBe('primary');
        expect(g.ups_a.energized_by).toBe('util');
        expect(g.ups_a.plant_mode).toBe(null);
        expect(g.genset_a.alive).toBe(false);
    });

    it('transfer to generators in Power Controls draws the path on the generator bus', () => {
        const g = mirrorGrid(getGridState(), plant({ xferA: 'GENERATORS', genA: 'ON_LOAD' }));
        expect(g.mvtc_a.ats_pos).toBe('secondary');
        expect(g.genset_a.state).toBe('running');
        expect(g.ups_a.energized_by).toBe('genset');
        expect(g.ups_b.energized_by).toBe('util');
        expect(pathFlows(g).a.source).toBe('genset');
    });

    it('transfer commanded while sets still crank: MV bus dead, UPS rides the battery', () => {
        const g = mirrorGrid(getGridState(), plant({ xferA: 'GENERATORS', genA: 'CRANKING' }));
        expect(g.mvtc_a.alive).toBe(false);
        expect(g.ups_a.on_battery).toBe(true);
    });

    it('isolated and bypassed UPS blocks map to units out and the bypass caption', () => {
        const g = mirrorGrid(getGridState(), plant({ upsA: ['ISOLATED', 'STATIC_BYPASS'] }));
        expect(g.ups_a.units_out).toBe(1);
        expect(g.ups_a.n1_ok).toBe(false);
        expect(g.ups_a.n_ok).toBe(true);
        expect(g.ups_a.plant_mode).toBe('static_bypass');
        expect(plantModeLabel(g.ups_a)).toBe('BYPASS × 1');
        expect(plantModeLabel(g.ups_b)).toBe(null);
    });

    it('all blocks in Dynamic Online get their caption', () => {
        const g = mirrorGrid(getGridState(), plant({ upsA: Array(8).fill('DYNAMIC_ONLINE') }));
        expect(plantModeLabel(g.ups_a)).toBe('DYNAMIC ONLINE');
    });

    it('generator sets out of service lower the bus capacity', () => {
        const g = mirrorGrid(getGridState(), plant({ genOutA: 2 }));
        expect(g.genset_a.units_out).toBe(2);
        expect(g.genset_a.n_ok).toBe(false);
    });

    it('never mutates its inputs or the engine grid', () => {
        const base = getGridState();
        const p = plant({ xferA: 'GENERATORS', genA: 'ON_LOAD' });
        const before = JSON.stringify(p);
        mirrorGrid(base, p);
        expect(base.mvtc_a.ats_pos).toBe('primary');
        expect(JSON.stringify(p)).toBe(before);
    });

    it('bad payloads fall back to the base grid', () => {
        const base = getGridState();
        expect(isPlantSnapshot({ detail: 'authentication required' })).toBe(false);
        expect(mirrorGrid(base, { detail: 'x' })).toBe(base);
        expect(mirrorGrid(base, null)).toBe(base);
    });

    it('propagateStatic leaves the engine state alone', () => {
        const base = getGridState();
        const g = propagateStatic({ ...base, util_a: { ...base.util_a, tripped: true } });
        expect(g.xfmr_a.alive).toBe(false);
        expect(base.xfmr_a.alive).toBe(true);
    });
});
