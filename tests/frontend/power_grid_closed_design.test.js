/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/power_grid_closed_design.test.js
 * DC-EPMS-068 lote C1: the Power SLD DAG on the closed Phase 1 design
 * (MV transfer controller, generator bus 9 x 2.75 MW, UPS bank
 * 8 x 2.5 MW). Numbers fenced against config/power_plant.yml.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import {
    initPowerGrid, tripNode, restoreAll, getGridState, getTopology,
    setUnitsOut, isTransfer, PHASE1,
} from '/assets/js/core/power_grid.js';
import { steadyStatePower } from '/assets/js/core/contingency.js';

const PLANT = readFileSync(resolve(__dirname, '../../config/power_plant.yml'), 'utf8');

/** First numeric value of `key:` inside the top-level `section:` block. */
function yamlNum(section, key) {
    const block = PLANT.split(/\n(?=\S)/).find((b) => b.startsWith(section + ':'));
    const m = block && block.match(new RegExp(`\\n\\s+${key}:\\s*([0-9.]+)`));
    return m ? Number(m[1]) : NaN;
}

beforeEach(() => {
    vi.useFakeTimers();
    initPowerGrid();
});
afterEach(() => {
    restoreAll();
    vi.useRealTimers();
});

describe('C1 — closed design numbers match config/power_plant.yml', () => {
    it('UPS bank and generator bus sizing', () => {
        expect(PHASE1.ups.units).toBe(yamlNum('ups', 'units_per_path'));
        expect(PHASE1.ups.unitKw).toBe(yamlNum('ups', 'rated_kw'));
        expect(PHASE1.gen.units).toBe(yamlNum('generators', 'units_per_path'));
        expect(PHASE1.gen.unitKw).toBe(yamlNum('generators', 'rated_kw'));
        expect(PHASE1.itLoadPerPathKw).toBe(yamlNum('design_basis', 'it_load_per_path_kw'));
        expect(PHASE1.ups.floorKw).toBe(yamlNum('design_basis', 'it_load_per_path_kw'));
        expect(PHASE1.gen.floorKw).toBe(yamlNum('design_basis', 'design_total_load_kw'));
    });
});

describe('C1 — topology', () => {
    it('no 480 V ATS remains in Phase 1; each path has an MV transfer controller', () => {
        const topo = getTopology();
        expect(topo.ats_a).toBeUndefined();
        expect(topo.ats_b).toBeUndefined();
        for (const p of ['a', 'b']) {
            const t = topo['mvtc_' + p];
            expect(t.type).toBe('mvtc');
            expect(isTransfer(t.type)).toBe(true);
            expect(t.primary).toBe('xfmr_' + p);
            expect(t.secondary).toBe('genset_' + p);
            expect(topo['mvtc_' + p].targets).toEqual(['mv_swgr_' + p]);
            expect(topo['mv_swgr_' + p].targets).toEqual(['usub_' + p]);
            expect(topo['ups_' + p].sources).toEqual(['usub_' + p]);
        }
    });
});

describe('C1 — unit banks: capacity, N, N+1', () => {
    it('full banks: UPS 20 MW N+1, generators 24.75 MW N+1', () => {
        const g = getGridState();
        expect(g.ups_a.capacity_kw).toBe(20000);
        expect(g.ups_a.n_ok && g.ups_a.n1_ok).toBe(true);
        expect(g.genset_a.capacity_kw).toBe(24750);
        expect(g.genset_a.n_ok && g.genset_a.n1_ok).toBe(true);
    });

    it('one UPS block out: 17.5 MW, still N, no longer N+1, bank alive', () => {
        setUnitsOut('ups_a', 1);
        const u = getGridState().ups_a;
        expect(u.capacity_kw).toBe(17500);
        expect(u.n_ok).toBe(true);
        expect(u.n1_ok).toBe(false);
        expect(u.alive).toBe(true);
        expect(u.mode).toBe('double_conversion');
    });

    it('two UPS blocks out: 15 MW, below N for the 16.76 MW path load', () => {
        setUnitsOut('ups_a', 2);
        expect(getGridState().ups_a.n_ok).toBe(false);
    });

    it('all eight blocks out: the bank has no output', () => {
        setUnitsOut('ups_b', 8);
        const g = getGridState();
        expect(g.ups_b.alive).toBe(false);
        expect(g.ups_b.mode).toBe('off');
        expect(g.ddu_b1.alive).toBe(false);
        expect(g.ddu_a1.alive).toBe(true);   // 2N: path A untouched
    });

    it('one generator out: 22 MW is N but not N+1 (22 - 2.75 < 21.5 MW floor)', () => {
        setUnitsOut('genset_a', 1);
        const g = getGridState().genset_a;
        expect(g.capacity_kw).toBe(22000);
        expect(g.n_ok).toBe(true);       // ADR-013: one set per path may be out
        expect(g.n1_ok).toBe(false);
    });

    it('clamps and rejects non-bank nodes', () => {
        expect(setUnitsOut('ups_a', 99)).toBe(true);
        expect(getGridState().ups_a.units_out).toBe(8);
        expect(setUnitsOut('ups_a', -3)).toBe(true);
        expect(getGridState().ups_a.units_out).toBe(0);
        expect(setUnitsOut('rpp_a1', 1)).toBe(false);
        expect(setUnitsOut('nope', 1)).toBe(false);
    });

    it('restoreAll returns every unit to service', () => {
        setUnitsOut('ups_a', 3);
        setUnitsOut('genset_b', 2);
        restoreAll();
        const g = getGridState();
        expect(g.ups_a.units_out).toBe(0);
        expect(g.genset_b.units_out).toBe(0);
        expect(g.ups_a.capacity_kw).toBe(20000);
    });
});

describe('C1 — MV transfer sequence on the generator bus', () => {
    it('utility loss: 52-U opens, gap, generator bus cranks, 52-GM closes', () => {
        tripNode('util_a');
        let g = getGridState();
        expect(g.mvtc_a.transferring).toBe(true);
        expect(g.genset_a.state).toBe('cranking');
        vi.advanceTimersByTime(2000);
        g = getGridState();
        expect(g.mvtc_a.ats_pos).toBe('secondary');
        expect(g.mvtc_a.alive).toBe(true);
        expect(g.ups_a.energized_by).toBe('genset');
    });

    it('a generator bus with every set out never carries the path', () => {
        setUnitsOut('genset_a', 9);
        tripNode('util_a');
        vi.advanceTimersByTime(2500);
        const g = getGridState();
        expect(g.genset_a.alive).toBe(false);
        expect(g.mvtc_a.alive).toBe(false);
        expect(g.ups_a.on_battery).toBe(true);
    });

    it('N-1 steady state: losing the MV transfer controller is not absorbed (battery excluded)', () => {
        const s = steadyStatePower(new Set(['mvtc_a']));
        expect(s.get('ups_a').alive).toBe(false);
        expect(s.get('ups_b').alive).toBe(true);
    });
});

// ── SLD surface (S-VISUAL-01: assert on the rendered default surface) ──
import { __power_test__ } from '/assets/js/views/power.js';

describe('C1 — unit strips on the Power SLD', () => {
    const { renderFlatSld, setMode, onFlatClick, applyGrid } = __power_test__;
    function mount() {
        vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503, json: async () => ({}) })));
        document.body.innerHTML =
            '<div id="view-power"><div class="pid-action-bar"></div>'
            + '<svg class="pid-svg"></svg></div>';
        renderFlatSld();
    }
    afterEach(() => { setMode('live'); document.body.innerHTML = ''; vi.unstubAllGlobals(); });

    it('draws one tick per installed unit (8 UPS blocks, 9 generators per path)', () => {
        mount();
        for (const p of ['a', 'b']) {
            expect(document.querySelectorAll(`[data-unit-of="ups_${p}"]`).length).toBe(8);
            expect(document.querySelectorAll(`[data-unit-of="genset_${p}"]`).length).toBe(9);
        }
        expect(document.querySelector('[data-sld-node="mvtc_a"] .pf-name').textContent)
            .toContain('MV TRANSFER A');
        expect(document.querySelector('[data-sld-node="ups_a"] .pf-name').textContent)
            .toContain('8 × TRINERGY');
        expect(document.querySelector('[data-sld-node="ats_a"]')).toBeNull();
    });

    it('What-If: a tick takes a block out and the caption shows N only', () => {
        mount();
        setMode('whatif');
        const tick = document.querySelector('[data-unit-of="ups_a"][data-unit="0"]');
        onFlatClick({ target: tick });
        const g = getGridState();
        expect(g.ups_a.units_out).toBe(1);
        applyGrid(g);
        const out = document.querySelectorAll('[data-unit-of="ups_a"][data-out="1"]');
        expect(out.length).toBe(1);
        const cap = document.querySelector('[data-sld-metric="ups_a-cap"]');
        expect(cap.textContent).toContain('17.50 MW');
        expect(cap.textContent).toContain('N only');
        expect(cap.getAttribute('data-level')).toBe('warn');
        // the out-of-service tick returns it
        onFlatClick({ target: out[0] });
        expect(getGridState().ups_a.units_out).toBe(0);
    });

    it('Live mode: clicking a tick does nothing (no plant actuation from the SLD)', () => {
        mount();
        setMode('live');
        onFlatClick({ target: document.querySelector('[data-unit-of="ups_b"][data-unit="3"]') });
        expect(getGridState().ups_b.units_out).toBe(0);
    });
});

describe('C1 — transfer position text follows the DAG', () => {
    const { renderFlatSld, applyGrid } = __power_test__;
    it('shows IN TRANSFER, then 52-GM after the gap', () => {
        document.body.innerHTML = '<div id="view-power"><div class="pid-action-bar"></div><svg class="pid-svg"></svg></div>';
        renderFlatSld();
        const pos = () => document.querySelector('[data-sld-metric="mvtc_a-pos"]').textContent;
        expect(pos()).toBe('52-U · UTILITY');
        tripNode('util_a');
        applyGrid(getGridState());
        expect(pos()).toBe('OPEN · IN TRANSFER');
        vi.advanceTimersByTime(2000);
        applyGrid(getGridState());
        expect(pos()).toBe('52-GM · GEN BUS');
        document.body.innerHTML = '';
    });
});
