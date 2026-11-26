/**
 * L2: field view of the utility transformer (core/field_xfmr.js), its
 * wiring in the Power view and the LIVE mirror of 52-T / 86T.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { xfmrSvg, applyXfmrState, resolveXfmrClick, isXfmrEvent, xfmrEventText }
    from '/assets/js/core/field_xfmr.js';
import { fieldLogHtml } from '/assets/js/core/field_switchgear.js';
import { __power_test__ } from '/assets/js/views/power.js';
import { mirrorGrid } from '/assets/js/core/plant_mirror.js';
import { initPowerGrid, restoreAll, getGridState } from '/assets/js/core/power_grid.js';

const ACTIONS = ['OPEN_52T', 'CLOSE_52T', 'KEY_LOCK_52U', 'KEY_UNLOCK_52U', 'KEY_LOCK_52T', 'KEY_UNLOCK_52T',
    'DETC_UNLOCK', 'DETC_LOCK', 'DETC_POS_UP', 'DETC_POS_DOWN', 'DETC_SPARE_KEY', 'RESET_63', 'RESET_87T',
    'RESET_86T', 'FANS_AUTO', 'FANS_ON', 'FANS_OFF'];
const TR = (over = {}) => ({
    id: 'xfmr_a', energized: true, primary_closed: true, grid_ok: true, grid_kv: 27.5, secondary_kv: 13.8,
    tap: 3, tap_pct: 0, key_k1: 'L-U', key_k2: 'L-T', detc_locked: true, detc_unlocked_by: null,
    spare_key_available: false, fan_mode: 'AUTO', fan1: true, fan2: false, cooling_stage: 'ONAF1',
    rating_mva: 20, load_mva: 10.95, load_pct: 54.8, top_oil_c: 55.6, winding_c: 65.1,
    liquid_level_pct: 68.4, nitrogen_psig: 5.1, oil_alarm: false, winding_alarm: false,
    flag_63: false, flag_87t: false, lockout_86t: false, trip_cause: null, damaged: false,
    setpoints: { oil_alarm_c: 85, oil_trip_c: 95, winding_alarm_c: 110, winding_trip_c: 130 },
    thermal_time_scale: 60,
    actions: ACTIONS.map((a) => ({ action: a, permitted: true })),
    ...over,
});
const XFER = (tr = TR()) => ({ id: 'mvtc_a', kind: 'transfer', path: 'a', state: 'UTILITY', cubicles: [], transformer: tr });

function mount(t = TR()) {
    document.body.innerHTML = `<div id="root">${xfmrSvg('a')}</div>`;
    const root = document.getElementById('root');
    applyXfmrState(root, t, 'a');
    return root;
}

describe('field_xfmr: drawing', () => {
    it('honest labels: simulated, no arc-flash study, model time scale', () => {
        const root = mount();
        const html = root.innerHTML;
        expect(html).toContain('SIMULATED EQUIPMENT');
        expect(html).toContain('NOT PERFORMED');
        expect(html).toContain('OPERATE ONLY WITH THE');
        expect(root.querySelector('[data-txt="timescale"]').textContent).toBe('MODEL · TIME ×60');
    });

    it('state goes to attributes, gauges and the bargraph', () => {
        const root = mount();
        const sec = root.querySelector('[data-section="XFMR"]');
        expect(sec.getAttribute('data-energized')).toBe('1');
        expect(sec.getAttribute('data-k1')).toBe('L-U');
        expect(root.querySelector('[data-txt="oil"]').textContent).toBe('55.6°C');
        expect(root.querySelector('[data-txt="tap"]').textContent).toBe('POS 3 · 0 %');
        const lit = [...root.querySelectorAll('[data-bar="oil"] .xf-seg')].filter((s) => s.getAttribute('data-lit'));
        expect(lit).toHaveLength(12);              // 0..55 C in 5 C steps
        expect(root.querySelector('[data-led="fan1"]').getAttribute('data-on')).toBe('1');
        expect(root.querySelector('[data-lock="lu"]').getAttribute('data-key')).toBe('1');
        expect(root.querySelector('.xf-detc-handle').style.transform).toBe('rotate(0deg)');
    });

    it('trip, damage and key chain states are drawn', () => {
        const root = mount(TR({ lockout_86t: true, flag_63: true, flag_87t: true, damaged: true, energized: false,
            primary_closed: false, key_k1: 'L-T', key_k2: 'HAND', tap: 2, top_oil_c: 97, secondary_kv: 0 }));
        const sec = root.querySelector('[data-section="XFMR"]');
        expect(sec.getAttribute('data-86')).toBe('1');
        expect(sec.getAttribute('data-63')).toBe('1');
        expect(root.querySelector('[data-txt="l3"]').textContent).toContain('INTERNAL FAULT');
        expect(root.querySelector('[data-hand="k2"]').getAttribute('data-on')).toBe('1');
        expect(root.querySelector('[data-hand="k1"]').getAttribute('data-on')).toBe('0');
        const red = [...root.querySelectorAll('[data-bar="oil"] .xf-seg')].filter((s) => s.getAttribute('data-lit') === 'r');
        expect(red.length).toBeGreaterThan(0);
        expect(root.querySelector('.xf-detc-handle').style.transform).toBe('rotate(-32deg)');
    });
});

describe('field_xfmr: clicks', () => {
    it('lock cylinders resolve by key location', () => {
        const root = mount();
        const at = (sel, t) => resolveXfmrClick(root.querySelector(sel), t);
        expect(at('[data-lock="lu"] .xf-lock-cyl', TR())).toMatchObject({ action: 'KEY_LOCK_52U' });
        expect(at('[data-lock="lu"] .xf-lock-cyl', TR({ key_k1: 'HAND' }))).toMatchObject({ action: 'KEY_UNLOCK_52U' });
        expect(at('[data-lock="lt"] .xf-lock-cyl', TR({ key_k1: 'HAND' }))).toMatchObject({ action: 'KEY_LOCK_52T' });
        expect(at('[data-lock="lt"] .xf-lock-cyl', TR({ key_k1: 'L-T' }))).toMatchObject({ action: 'KEY_UNLOCK_52T' });
        expect(at('[data-lock="ld"] .xf-lock-cyl', TR())).toMatchObject({ action: 'DETC_UNLOCK' });
        expect(at('[data-lock="ld"] .xf-lock-cyl', TR({ detc_locked: false }))).toMatchObject({ action: 'DETC_LOCK' });
        expect(at('[data-act="detc_down"] rect', TR())).toMatchObject({ action: 'DETC_POS_DOWN' });
        expect(at('[data-act="t_open"] circle', TR())).toMatchObject({ action: 'OPEN_52T', kind: 'breaker' });
        expect(at('[data-act="fans_off"] text', TR())).toMatchObject({ action: 'FANS_OFF' });
        expect(at('[data-act="86t"] .fsg-86-grip', TR())).toMatchObject({ action: 'RESET_86T' });
        expect(resolveXfmrClick(root.querySelector('.xf-mon'), TR())).toBeNull();
    });

    it('the log shows transformer events only, escaped', () => {
        const events = [
            { ts: 1, event: 'command', device_id: 'mvtc_a', command: 'DETC_POS_DOWN@XFMR', equipment: 'xfmr',
                tap_from: 3, tap: 2, energized: false, actor: 'op' },
            { ts: 2, event: 'command', device_id: 'mvtc_a', command: 'RACK_OUT@52-GM', field: true, racking: 'TEST' },
            { ts: 3, event: 'refused', device_id: 'mvtc_a', command: 'DETC_UNLOCK@XFMR', detail: '<K2>' },
            { ts: 4, event: 'xfmr_internal_fault', device_id: 'mvtc_a', relay: '63+87T', detail: 'arc' },
        ];
        expect(events.filter(isXfmrEvent)).toHaveLength(3);
        expect(xfmrEventText(events[0])).toBe('DETC_POS_DOWN@XFMR · POS 3→2 · DE-ENERGIZED');
        expect(xfmrEventText({ ...events[0], tap: 3, outcome: 'internal_fault' }))
            .toBe('DETC_POS_DOWN@XFMR · MOVED ENERGIZED → INTERNAL FAULT');
        const html = fieldLogHtml(events, '', 'mvtc_a', { match: isXfmrEvent, text: xfmrEventText, empty: 'none' });
        expect(html).toContain('&lt;K2&gt;');
        expect(html).not.toContain('RACK_OUT');
        const swgr = fieldLogHtml(events, '', 'mvtc_a');
        expect(swgr).toContain('RACK_OUT');
        expect(swgr).not.toContain('DETC_POS_DOWN');
    });
});

describe('Power view wiring (L2)', () => {
    afterEach(() => { vi.restoreAllMocks(); __power_test__.closeField(); });

    it('opens the transformer view, posts an action and shakes on an internal fault', async () => {
        document.body.innerHTML = '<div id="view-power"><div class="pid-canvas"><svg class="pid-svg"></svg></div></div>';
        __power_test__.setPlant({ paths: [], devices: [XFER()], events: [] });
        const calls = [];
        vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, opts) => {
            calls.push([String(url), opts && opts.body]);
            const body = String(url).includes('/xfmr')
                ? { success: true, event: { tap: 3, energized: false, outcome: 'internal_fault' } }
                : { paths: [], devices: [XFER()], events: [] };
            return { ok: true, status: 200, json: async () => body };
        });
        __power_test__.openField('a', 'xfmr');
        const el = document.getElementById('pwr-field');
        expect(el.getAttribute('aria-label')).toBe('Field view: utility transformer');
        expect(el.querySelector('[data-fequip="xfmr"]').getAttribute('aria-pressed')).toBe('true');
        await __power_test__.onFieldClick({ target: el.querySelector('[data-act="detc_down"] rect') });
        const post = calls.find(([u]) => u.includes('/api/devices/mvtc_a/xfmr'));
        expect(JSON.parse(post[1])).toMatchObject({ action: 'DETC_POS_DOWN' });
        expect(document.getElementById('pwr-field-stage').classList.contains('xf-arc')).toBe(true);
        expect(el.querySelector('.fsg-lcd-msg').textContent).toContain('INTERNAL FAULT');
        // switch back to the switchgear with the bar button
        await __power_test__.onFieldClick({ target: el.querySelector('[data-fequip="swgr"]') });
        expect(el.querySelector('[data-section="XFMR"]')).toBeNull();
    });
});

describe('plant_mirror (L2)', () => {
    beforeEach(() => { vi.useFakeTimers(); initPowerGrid(); });
    afterEach(() => { restoreAll(); vi.useRealTimers(); });

    const plant = (tr, state = 'UTILITY') => ({
        devices: [{ ...XFER(tr), state }, { id: 'mvtc_b', kind: 'transfer', path: 'b', state: 'UTILITY' }],
        paths: [{ path: 'a', utility_ok: true }, { path: 'b', utility_ok: true }],
    });

    it('52-T open: the transformer is drawn dead with the utility live', () => {
        const g = mirrorGrid(getGridState(), plant(TR({ energized: false, primary_closed: false }), 'OPEN'));
        expect(g.util_a.alive).toBe(true);
        expect(g.xfmr_a.tripped).toBe(true);
        expect(g.mvtc_a.tripped).toBe(false);
    });

    it('86T: the incomer shows TRIP', () => {
        const g = mirrorGrid(getGridState(), plant(TR({ energized: false, lockout_86t: true }), 'OPEN'));
        expect(g.mvtc_a.tripped).toBe(true);
        expect(g.xfmr_b.tripped).toBeFalsy();
    });
});
