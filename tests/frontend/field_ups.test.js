/**
 * L4: field view of the UPS bank (core/field_ups.js) and its wiring in
 * the Power view and the UPS faceplate.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { upsSvg, applyUpsState, resolveUpsClick, isUpsEvent, upsEventText } from '/assets/js/core/field_ups.js';
import { fieldLogHtml } from '/assets/js/core/field_switchgear.js';
import { faceplateHtml } from '/assets/js/core/sbo_faceplate.js';
import { __power_test__ } from '/assets/js/views/power.js';

const ACTIONS = ['SYSTEM_TO_BYPASS', 'SYSTEM_TO_INVERTER', 'CLOSE_Q1', 'OPEN_Q1', 'CLOSE_Q2', 'OPEN_Q2',
    'CLOSE_Q3', 'OPEN_Q3', 'CLOSE_Q4', 'OPEN_Q4', 'CLOSE_QF1', 'OPEN_QF1', 'SKRU_RELEASE', 'SKRU_CAPTURE',
    'UNLOCK_MBB', 'LOCK_MBB', 'UNLOCK_MIB', 'LOCK_MIB', 'PADLOCK_QF1', 'UNPADLOCK_QF1'];
const US = (over = {}) => ({
    breakers: { Q1: true, Q2: true, Q3: false, Q4: true, QF1: true }, qf1_padlock: null,
    mib_unlocked: true, mbb_unlocked: false, skru_keys: 1, hand_keys: 0, skru_lamp: false,
    mode: 'INVERTER', load_source: 'INVERTER', bypass_live: true, rect_live: true, parked: [],
    on_maintenance_bypass: false, actions: ACTIONS.map((a) => ({ action: a, permitted: true })), ...over,
});
const PS = (us = US(), over = {}) => ({
    path: 'a', it_load_kw: 8380, ups_in_service: 8, ups_total: 8, load_lost: false, on_battery: false,
    load_feed: 'UPS', battery_soc_pct: 100, battery_runtime_min: 9.5, ups_system: us, ...over,
});
const BLOCKS = Array.from({ length: 8 }, (_, i) => ({ id: `ups_a_0${i + 1}`, kind: 'ups', path: 'a',
    state: i === 7 ? 'STATIC_BYPASS' : 'DOUBLE_CONVERSION' }));

function mount(ps = PS()) {
    document.body.innerHTML = `<div id="root">${upsSvg('a')}</div>`;
    const root = document.getElementById('root');
    applyUpsState(root, ps, BLOCKS);
    return root;
}

describe('field_ups: drawing', () => {
    it('four bypass breakers, QF1, SKRU, eight block chips, honest labels', () => {
        const root = mount();
        for (const id of ['Q1', 'Q2', 'Q3', 'Q4', 'QF1']) expect(root.querySelector(`.xu-brk[data-brk="${id}"]`)).not.toBeNull();
        expect(root.querySelectorAll('.xu-chip')).toHaveLength(8);
        expect(root.innerHTML).toContain('SIMULATED EQUIPMENT');
        expect(root.querySelector('[data-block="8"]').getAttribute('data-state')).toBe('STATIC_BYPASS');
        expect(root.querySelector('[data-txt="b8"]').textContent).toBe('BYP');
    });

    it('normal service: inverter path live, MBB locked open, key in the SKRU', () => {
        const root = mount();
        const sec = root.querySelector('[data-section="UPS"]');
        expect(sec.getAttribute('data-mode')).toBe('INVERTER');
        expect(root.querySelector('[data-seg="inv"]').getAttribute('data-live')).toBe('1');
        expect(root.querySelector('[data-seg="mbb"]').getAttribute('data-live')).toBe('0');
        expect(root.querySelector('[data-lock="MBB"]').getAttribute('data-key')).toBe('0');
        expect(sec.getAttribute('data-skru-key')).toBe('1');
        expect(root.querySelector('.xu-brk[data-brk="Q3"]').getAttribute('data-closed')).toBe('0');
    });

    it('on maintenance bypass with QF1 locked out', () => {
        const us = US({ breakers: { Q1: false, Q2: false, Q3: true, Q4: false, QF1: false }, qf1_padlock: 'manager',
            mib_unlocked: false, mbb_unlocked: true, mode: 'OFF', load_source: 'MAINTENANCE_BYPASS',
            on_maintenance_bypass: true, bypass_live: false, rect_live: false });
        const root = mount(PS(us, { load_feed: 'maintenance bypass', ups_in_service: 0 }));
        expect(root.querySelector('[data-seg="mbb"]').getAttribute('data-live')).toBe('1');
        expect(root.querySelector('[data-txt="feed2"]').textContent).toContain('NO BATTERY');
        expect(root.querySelector('[data-section="UPS"]').getAttribute('data-padlock')).toBe('1');
        expect(root.querySelector('[data-txt="bt1"]').textContent).toBe('QF1 OPEN · LOCKED OUT');
    });
});

describe('field_ups: clicks and log', () => {
    it('resolves breakers, locks, SKRU, hasp and the display buttons', () => {
        const root = mount();
        const at = (sel, us = US()) => resolveUpsClick(root.querySelector(sel), us);
        expect(at('[data-act="to_bypass"] rect')).toMatchObject({ action: 'SYSTEM_TO_BYPASS' });
        expect(at('.xu-handle[data-brk="Q4"] rect')).toMatchObject({ action: 'OPEN_Q4', kind: 'breaker' });
        expect(at('.xu-handle[data-brk="Q3"] rect')).toMatchObject({ action: 'CLOSE_Q3' });
        expect(at('[data-lock="MBB"] .xf-lock-cyl')).toMatchObject({ action: 'UNLOCK_MBB' });
        expect(at('[data-lock="MIB"] .xf-lock-cyl')).toMatchObject({ action: 'LOCK_MIB' });
        expect(at('[data-act="skru"] rect')).toMatchObject({ action: 'SKRU_RELEASE' });
        expect(at('[data-act="skru"] rect', US({ skru_keys: 0, hand_keys: 1 }))).toMatchObject({ action: 'SKRU_CAPTURE' });
        expect(at('[data-act="hasp"] rect')).toMatchObject({ action: 'PADLOCK_QF1' });
        expect(resolveUpsClick(root.querySelector('.xf-lcd'), US())).toBeNull();
    });

    it('log keeps UPS events of the path, escaped', () => {
        const events = [
            { ts: 1, event: 'command', device_id: 'ups_system_a', command: 'CLOSE_Q3@UPS_A', equipment: 'ups',
                mode: 'STATIC_BYPASS', load_feed: 'maintenance bypass' },
            { ts: 2, event: 'refused', device_id: 'ups_system_a', command: 'OPEN_Q4@UPS_A', detail: '<make before break>' },
            { ts: 3, event: 'load_lost', device_id: 'path_a', detail: 'x' },
            { ts: 4, event: 'command', device_id: 'genset_a_01', command: 'P2_AUTO@GENSET_A_01' },
        ];
        expect(upsEventText(events[0])).toBe('CLOSE_Q3@UPS_A · STATIC BYPASS · maintenance bypass');
        const ids = ['ups_system_a', 'path_a'];
        const html = fieldLogHtml(events, '', '', { anyDevice: true,
            match: (ev) => ids.includes(ev.device_id) && isUpsEvent(ev), text: upsEventText, empty: 'none' });
        expect(html).toContain('&lt;make before break&gt;');
        expect(html).toContain('LOAD LOST');
        expect(html).not.toContain('P2_AUTO');
    });
});

describe('Power view + faceplate wiring (L4)', () => {
    afterEach(() => { vi.restoreAllMocks(); __power_test__.closeField(); });

    it('UPS faceplate offers the field view', () => {
        const html = faceplateHtml('ups_a', { devices: BLOCKS, paths: [PS()] });
        expect(html).toContain('data-fp-equip="ups"');
    });

    it('opens the UPS view and posts an action', async () => {
        document.body.innerHTML = '<div id="view-power"><div class="pid-canvas"><svg class="pid-svg"></svg></div></div>';
        const xfer = { id: 'mvtc_a', kind: 'transfer', path: 'a', state: 'UTILITY', cubicles: [] };
        __power_test__.setPlant({ paths: [PS()], devices: [xfer, ...BLOCKS], events: [] });
        const calls = [];
        vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, opts) => {
            calls.push([String(url), opts && opts.body]);
            const body = String(url).includes('/api/ups-systems/')
                ? { success: true, event: { mode: 'STATIC_BYPASS', load_feed: 'UPS' } }
                : { paths: [PS()], devices: [xfer, ...BLOCKS], events: [] };
            return { ok: true, status: 200, json: async () => body };
        });
        __power_test__.openField('a', 'ups');
        const el = document.getElementById('pwr-field');
        expect(el.getAttribute('aria-label')).toBe('Field view: UPS bank');
        await __power_test__.onFieldClick({ target: el.querySelector('[data-act="to_bypass"] rect') });
        const post = calls.find(([u]) => u.includes('/api/ups-systems/a/action'));
        expect(JSON.parse(post[1])).toMatchObject({ action: 'SYSTEM_TO_BYPASS' });
    });
});
