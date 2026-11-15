/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/power_flow.test.js
 * SLD "vida 1": design-consistent power flow, ANSI 52 breakers, flow
 * animation layer and the UPS bank opened into its blocks.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import { pathFlows, fmtPower, fmtApparent, PF } from '/assets/js/core/power_flow.js';
import {
    initPowerGrid, tripNode, restoreAll, getGridState, setUnitsOut, PHASE1,
} from '/assets/js/core/power_grid.js';
import { upsBankSection, engineeringSection } from '/assets/js/core/asset_engineering.js';
import { __power_test__ } from '/assets/js/views/power.js';

beforeEach(() => { vi.useFakeTimers(); initPowerGrid(); });
afterEach(() => { restoreAll(); vi.useRealTimers(); document.body.innerHTML = ''; });

describe('power_flow — numbers follow the design', () => {
    it('2N nominal: each path carries half of 16.76 MW', () => {
        const f = pathFlows(getGridState());
        expect(f.a.share).toBe(0.5);
        expect(f.a.upsOutKw).toBeCloseTo(8380, 6);
        expect(f.a.perBlockKw).toBeCloseTo(8380 / 8, 6);
        expect(f.a.upsLoadPct).toBeCloseTo(41.9, 1);
        expect(f.a.lossKw).toBeCloseTo(8380 * (1 / 0.97 - 1), 6);   // 259 kW, as Power Controls
        expect(f.a.upsInKw).toBeCloseTo(8380 / 0.97, 6);
        expect(f.a.xfmrKva).toBeCloseTo(8380 / 0.97 / PF, 6);
        expect(f.a.source).toBe('util');
        expect(f.a.genKw).toBe(0);
        expect(f.a.rppKw).toBeCloseTo(4190, 6);
    });

    it('a dead path hands 100 % to the other one', () => {
        setUnitsOut('ups_b', 8);
        const f = pathFlows(getGridState());
        expect(f.b.share).toBe(0);
        expect(f.a.share).toBe(1);
        expect(f.a.upsOutKw).toBeCloseTo(16760, 6);
        expect(f.a.upsLoadPct).toBeCloseTo(83.8, 1);
    });

    it('one block out: the remaining 7 share the path load', () => {
        setUnitsOut('ups_a', 1);
        const f = pathFlows(getGridState());
        expect(f.a.blocksIn).toBe(7);
        expect(f.a.perBlockKw).toBeCloseTo(8380 / 7, 6);
    });

    it('on generators the bus carries the UPS input; transformer at zero', () => {
        tripNode('util_a');
        vi.advanceTimersByTime(2000);
        const f = pathFlows(getGridState());
        expect(f.a.source).toBe('genset');
        expect(f.a.xfmrKva).toBe(0);
        expect(f.a.genKw).toBeCloseTo(8380 / 0.97, 6);
        expect(f.a.genLoadPct).toBeCloseTo((8380 / 0.97) / 24750 * 100, 6);
    });

    it('during the transfer gap the UPS rides the battery: no input drawn', () => {
        tripNode('util_a');
        const f = pathFlows(getGridState());
        expect(f.a.source).toBe('battery');
        expect(f.a.upsInKw).toBe(0);
        expect(f.a.upsOutKw).toBeCloseTo(8380, 6);
    });

    it('uses the facility IT load when given; ignores bad input', () => {
        expect(pathFlows(getGridState(), 12000).a.upsOutKw).toBe(6000);
        expect(pathFlows(getGridState(), -5).a.upsOutKw).toBeCloseTo(8380, 6);
        expect(pathFlows(null).a.share).toBe(0.5);
    });

    it('formats', () => {
        expect(fmtPower(8380)).toBe('8.38 MW');
        expect(fmtPower(259)).toBe('259 kW');
        expect(fmtPower(0)).toBe('0 kW');
        expect(fmtApparent(9600)).toBe('9.60 MVA');
    });

    it('DAG: MV switchgear and unit substations sit between the transfer controller and the bank', () => {
        expect(getGridState().mv_swgr_a.alive).toBe(true);
        tripNode('mv_swgr_a');
        const g = getGridState();
        expect(g.usub_a.alive).toBe(false);
        expect(g.ups_a.on_battery).toBe(true);
        expect(PHASE1.ups.eta).toBe(0.97);
    });
});

describe('SLD flow layer', () => {
    const { renderFlatSld, applyGrid } = __power_test__;
    function mount() {
        vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503, json: async () => ({}) })));
        document.body.innerHTML = '<div id="view-power"><div class="pid-action-bar"></div><svg class="pid-svg"></svg></div>';
        renderFlatSld();
    }
    afterEach(() => vi.unstubAllGlobals());
    const seg = (s) => document.querySelector(`[data-seg="${s}"]`);
    const brk = (b) => document.querySelector(`[data-brk="${b}"]`);
    const txt = (k) => document.querySelector(`[data-flow="${k}"]`)?.textContent;
    const arrow = (k) => document.querySelector(`[data-arrow="${k}"]`);
    const stateTxt = (k) => document.querySelector(`[data-brk="${k}"] .pf-52-state`)?.textContent;
    const metric = (k) => document.querySelector(`[data-sld-metric="${k}"]`)?.textContent;

    it('draws the closed-design runs, both breakers and the MV equipment', () => {
        mount();
        for (const p of ['a', 'b']) {
            for (const s of ['util', 'xfmr', 'u52', 'gen', 'bus', 'gm', 'mv', 'mvtc', 'swgr', 'usub', 'ups', 'batt']) {
                expect(seg(`${p}:${s}`), `${p}:${s}`).not.toBeNull();
            }
            expect(brk(`${p}:u`)).not.toBeNull();
            expect(brk(`${p}:gm`)).not.toBeNull();
            expect(document.querySelector(`[data-sld-node="mv_swgr_${p}"]`)).not.toBeNull();
            expect(document.querySelector(`[data-sld-node="usub_${p}"]`)).not.toBeNull();
        }
    });

    it('nominal: utility runs flow, generator runs idle, 52-U closed, 52-GM open', () => {
        mount();
        applyGrid(getGridState());
        expect(seg('a:xfmr').classList.contains('pf-flow')).toBe(true);
        expect(seg('a:xfmr').getAttribute('data-src')).toBe('util');
        expect(seg('a:gm').classList.contains('pf-flow')).toBe(false);
        expect(brk('a:u').getAttribute('data-state')).toBe('closed');
        expect(brk('a:gm').getAttribute('data-state')).toBe('open');
        expect(txt('a:ups')).toBe('8.38 MW');
        expect(metric('ups_a-load')).toBe('8.38 MW · 42 % of bank');
        expect(metric('xfmr_a-load')).toBe('9.60 MVA of 25');
        expect(metric('util_a-kw')).toBe('8.64 MW');
        expect(metric('rpp_a1-kw')).toBe('4.19 MW ×2');
        // a standby generator bus is not painted as a fault
        expect(document.querySelector('[data-sld-node="genset_a"] .pid-symbol').getAttribute('data-sev')).toBe('ok');
    });

    it('transfer: both breakers pulse, then 52-GM closes and the generator runs carry the bus', () => {
        mount();
        tripNode('util_a');
        applyGrid(getGridState());
        expect(brk('a:u').getAttribute('data-state')).toBe('transfer');
        expect(seg('a:batt').getAttribute('data-src')).toBe('battery');
        vi.advanceTimersByTime(2000);
        applyGrid(getGridState());
        expect(brk('a:u').getAttribute('data-state')).toBe('open');
        expect(brk('a:gm').getAttribute('data-state')).toBe('closed');
        expect(seg('a:gm').getAttribute('data-src')).toBe('genset');
        expect(seg('a:util').classList.contains('pf-dead')).toBe(true);
        expect(txt('a:gen')).toContain('8.64 MW');
        expect(metric('xfmr_a-load')).toBe('0 MVA');
    });

    it('path B dead: path A carries the whole load, B runs go cold', () => {
        mount();
        setUnitsOut('ups_b', 8);
        applyGrid(getGridState());
        expect(seg('b:ups').classList.contains('pf-flow')).toBe(false);
        expect(arrow('b:ups').classList.contains('pf-arrow-on')).toBe(false);
        expect(arrow('a:ups').classList.contains('pf-arrow-on')).toBe(true);
    });

    it('HMI H1: ANSI scheme on the svg, breaker state written as text', () => {
        mount();
        applyGrid(getGridState());
        expect(document.querySelector('#view-power .pid-svg').getAttribute('data-scheme')).toBe('ansi');
        expect(stateTxt('a:u')).toBe('CLOSED');
        expect(stateTxt('a:gm')).toBe('OPEN');
        tripNode('util_a');
        applyGrid(getGridState());
        expect(stateTxt('a:u')).toBe('XFER');
        vi.advanceTimersByTime(2000);
        applyGrid(getGridState());
        expect(stateTxt('a:u')).toBe('OPEN');
        expect(stateTxt('a:gm')).toBe('CLOSED');
    });

    it('HMI H1: MV transfer controller trip shows TRIP on the carrying breaker', () => {
        mount();
        tripNode('mvtc_a');
        applyGrid(getGridState());
        expect(brk('a:u').getAttribute('data-state')).toBe('trip');
        expect(stateTxt('a:u')).toBe('TRIP');
        expect(stateTxt('a:gm')).toBe('OPEN');
    });

    it('HMI H1: static direction chevrons, one per run, lit only while carrying', () => {
        mount();
        applyGrid(getGridState());
        expect(document.querySelectorAll('[data-arrow^="a:"]').length).toBe(10);   // swgr + usub runs carry breakers (H2)
        expect(arrow('a:xfmr').classList.contains('pf-arrow-on')).toBe(true);
        expect(arrow('a:gen').classList.contains('pf-arrow-on')).toBe(false);
        expect(seg('a:xfmr').style.getPropertyValue('--flow-dur')).toBe('');
    });

    it('HMI H1: legend teaches the breaker convention and keeps the DC fence', () => {
        mount();
        const legend = [...document.querySelectorAll('#view-power .dk-legend-text')].map((t) => t.textContent).join(' | ');
        expect(legend).toContain('Breaker CLOSED (red, filled)');
        expect(legend).toContain('Breaker OPEN (green, hollow)');
        expect(legend).toContain('800 VDC unipolar TN-S');
        expect(legend).not.toMatch(/800 VDC.*(3-phase|trif)/i);
    });
});

describe('UPS bank opened into its blocks', () => {
    it('one row per block with load, rating share and mode', () => {
        const html = upsBankSection('ups_a', getGridState());
        document.body.innerHTML = html;
        const rows = document.querySelectorAll('[data-block]');
        expect(rows.length).toBe(8);
        expect(rows[0].dataset.block).toBe('ups_a_01');
        expect(rows[7].dataset.block).toBe('ups_a_08');
        expect(rows[0].textContent).toContain('1.05 MW');
        expect(rows[0].textContent).toContain('42 %');
        expect(rows[0].textContent).toContain('VFI');
        expect(document.body.textContent).toContain('N+1');
    });

    it('blocks out of service read OUT and the bank tag drops to N only', () => {
        setUnitsOut('ups_b', 1);
        document.body.innerHTML = upsBankSection('ups_b', getGridState());
        const out = document.querySelectorAll('tr.eng-blk-out');
        expect(out.length).toBe(1);
        expect(out[0].textContent).toContain('OUT');
        expect(document.body.textContent).toContain('N only');
        expect(document.body.textContent).toContain('1.20 MW');   // 8.38 / 7
    });

    it('the asset panel section for a bank starts with the block table', () => {
        const html = engineeringSection('ups_a', getGridState(), {});
        expect(html.indexOf('data-eng="ups-bank"')).toBeGreaterThanOrEqual(0);
        expect(html.indexOf('data-eng="ups-bank"')).toBeLessThan(html.indexOf('OPERATING MODE'));
    });
});

describe('HMI H2 / H3 on the Power SLD', () => {
    const { renderFlatSld, applyGrid } = __power_test__;
    function mount() {
        vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503, json: async () => ({}) })));
        document.body.innerHTML = '<div id="view-power"><div class="pid-action-bar"></div><svg class="pid-svg"></svg></div>';
        renderFlatSld();
    }
    afterEach(() => vi.unstubAllGlobals());
    const line = (k) => document.querySelector(`[data-tag-line="${k}"]`)?.textContent;

    it('H2: interlock drawn per path, unit-substation breakers marked as design lineup', () => {
        mount();
        for (const p of ['a', 'b']) {
            expect(document.querySelector(`[data-interlock="${p}"]`)).not.toBeNull();
            for (const id of ['sp', 'ss']) {
                const b = document.querySelector(`[data-brk="${p}:${id}"]`);
                expect(b.getAttribute('data-model')).toBe('design');
                expect(b.querySelector('title').textContent).toMatch(/not modelled or metered/);
            }
        }
    });

    it('H3: MV data tag from the design model (P, Q, S, PF 0.90) labelled MODEL', () => {
        mount();
        applyGrid(getGridState());
        expect(document.querySelector('[data-tag="a:mv"] .pf-tag-head').textContent)
            .toBe('MODEL · MV 13.8 kV · 60 Hz');
        expect(line('a:pq')).toBe('P 8.64 MW · Q 4.18 Mvar');
        expect(line('a:spf')).toBe('S 9.60 MVA · PF 0.90');
    });

    it('H3: dead MV bus reads zero, battery spec and LV nameplate drawn', () => {
        mount();
        tripNode('util_a');
        applyGrid(getGridState());
        expect(line('a:pq')).toBe('P 0 kW · Q 0 kvar');
        expect(line('a:spf')).toBe('S 0 kVA · bus dead');
        expect(document.querySelector('[data-sld-node="batt_a"] .pf-name').textContent)
            .toBe('BATTERY A · 10 MIN @ 20 MW (SPEC)');
        expect(document.querySelector('[data-sld-metric="rpp_a1-lv"]').textContent).toBe('480 V 3-ph · 60 Hz');
    });
});

describe('power_flow reactive power', () => {
    it('Q = P tan(acos 0.9)', async () => {
        const { reactiveKvar, fmtReactive } = await import('/assets/js/core/power_flow.js');
        expect(reactiveKvar(1000)).toBeCloseTo(484.32, 2);
        expect(reactiveKvar(0)).toBe(0);
        expect(reactiveKvar(1000, 1)).toBeCloseTo(0, 9);
        expect(fmtReactive(8640)).toBe('4.18 Mvar');
        expect(fmtReactive(500)).toBe('242 kvar');
    });
});
