/**
 * L3: field view of a generator set (core/field_gen.js) and its wiring
 * in the Power view and the faceplate.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { genSvg, applyGenState, resolveGenClick, isGenEvent, genEventText, genId, GEN_SETS }
    from '/assets/js/core/field_gen.js';
import { fieldLogHtml } from '/assets/js/core/field_switchgear.js';
import { faceplateHtml } from '/assets/js/core/sbo_faceplate.js';
import { __power_test__ } from '/assets/js/views/power.js';

const ACTIONS = ['ECS_STOP', 'ECS_AUTO', 'ECS_RUN', 'ESTOP_PUSH', 'ESTOP_RELEASE', 'HEATER_ON', 'HEATER_OFF',
    'P1_HAND', 'P1_OFF', 'P1_AUTO', 'P2_HAND', 'P2_OFF', 'P2_AUTO', 'RESET_P1_OL', 'RESET_P2_OL',
    'FILTER_A', 'FILTER_BOTH', 'FILTER_B', 'DRAIN_A', 'DRAIN_B', 'CHANGE_ELEMENT_A', 'CHANGE_ELEMENT_B',
    'CLEAN_BASIN', 'RESET_LEAK'];
const FUEL = (over = {}) => ({
    ecs_mode: 'AUTO', estop: false, shutdown: null, heater_on: true, coolant_c: 43, coolant_low: false,
    day_tank_l: 660, day_tank_pct: 55, low_alarm: false, hi_hi: false,
    pumps: [{ id: 'P-1', mode: 'AUTO', running: false, overload: true },
        { id: 'P-2', mode: 'OFF', running: false, overload: false }],
    discharge_psig: 0, solenoid_open: false,
    filter: { selected: 'BOTH', dp_psi: 0.2, water_pct: { A: 30, B: 0 }, clog: { A: 0, B: 0 } },
    leak: false, leak_present: false, burn_lph: 350.7, run_hours_left: 1.88, available_reason: null,
    time_scale: 30, model_note: 'model',
    actions: ACTIONS.map((a) => ({ action: a, permitted: true })),
    ...over,
});
const GEN = (fuel = FUEL(), state = 'ON_LOAD') => ({
    id: 'genset_a_01', kind: 'generator', path: 'a', display: 'Generator A1', state,
    readings: [{ label: 'Engine speed', value: 1800 }, { label: 'Output frequency', value: 60 },
        { label: 'Real power', value: 1211 }],
    indications: [], commands: [], status: { tone: 'warn', text: 'Carrying load' }, authority: 'AUTO', fuel,
});
const PATH = { path: 'a', bulk_fuel_pct: 97.2, bulk_hours_left: 15.4 };

function mount(dev = GEN()) {
    document.body.innerHTML = `<div id="root">${genSvg('a')}</div>`;
    const root = document.getElementById('root');
    applyGenState(root, dev, PATH, 1);
    return root;
}

describe('field_gen: drawing', () => {
    it('nine set buttons, honest labels, NFPA 110 minimum on the heater panel', () => {
        const root = mount();
        expect(root.querySelectorAll('.xg-setbtn')).toHaveLength(GEN_SETS);
        expect(root.innerHTML).toContain('SIMULATED EQUIPMENT');
        expect(root.innerHTML).toContain('MINIMUM 32 °C');
        expect(root.querySelector('[data-txt="sub"]').textContent).toContain('TIME ×30 (MODEL)');
        expect(genId('b', 3)).toBe('genset_b_03');
    });

    it('state goes to the tank, lamps, selectors and bowls', () => {
        const root = mount();
        const sec = root.querySelector('[data-section="GEN"]');
        expect(sec.getAttribute('data-running')).toBe('1');
        expect(root.querySelector('[data-txt="lvl"]').textContent).toBe('55.0 %');
        expect(root.querySelector('.xg-fuel').style.transform).toBe('translateY(126px)');
        expect(root.querySelector('[data-mark="lead"]').getAttribute('data-wet')).toBe('0');
        expect(root.querySelector('[data-mark="lag"]').getAttribute('data-wet')).toBe('1');
        expect(root.querySelector('[data-act="p1_ol"]').getAttribute('data-trip')).toBe('1');
        expect(root.querySelector('[data-sel="p2"] .xg-knob').style.transform).toBe('rotate(0deg)');
        expect(root.querySelector('[data-bowl="A"] [data-water]').getAttribute('height')).toBe('19.2');
        expect(root.querySelector('[data-txt="bulk"]').textContent).toBe('97.2 % of 50,000 L');
        expect(root.querySelector('.xg-setbtn[data-n="1"]').getAttribute('data-on')).toBe('1');
    });

    it('e-stop and shutdown are drawn', () => {
        const root = mount(GEN(FUEL({ estop: true, shutdown: 'EMERGENCY STOP' }), 'STANDBY'));
        expect(root.querySelector('[data-section="GEN"]').getAttribute('data-estop')).toBe('1');
        expect(root.querySelector('[data-led="shut"]').getAttribute('data-on')).toBe('1');
        expect(root.querySelector('[data-txt="d4"]').textContent).toBe('SHUTDOWN: EMERGENCY STOP');
    });
});

describe('field_gen: clicks and log', () => {
    it('resolves every control', () => {
        const root = mount();
        const at = (sel, dev = GEN()) => resolveGenClick(root.querySelector(sel), dev);
        expect(at('[data-act="p2_auto"] text')).toMatchObject({ action: 'P2_AUTO' });
        expect(at('[data-act="p1_ol"] circle')).toMatchObject({ action: 'RESET_P1_OL' });
        expect(at('[data-act="estop"] .xg-estop-red')).toMatchObject({ action: 'ESTOP_PUSH' });
        expect(at('[data-act="estop"] .xg-estop-red', GEN(FUEL({ estop: true })))).toMatchObject({ action: 'ESTOP_RELEASE' });
        expect(at('[data-act="heater"] rect')).toMatchObject({ action: 'HEATER_OFF' });
        expect(at('[data-act="drain_A"] rect')).toMatchObject({ action: 'DRAIN_A' });
        expect(at('[data-act="set"][data-n="4"] rect')).toEqual({ set: 4 });
        expect(resolveGenClick(root.querySelector('.xg-tank'), GEN())).toBeNull();
    });

    it('log keeps generator events only, escaped', () => {
        const events = [
            { ts: 1, event: 'command', device_id: 'genset_a_01', command: 'P2_AUTO@GENSET_A_01', equipment: 'gen',
                to_state: 'ON_LOAD', day_tank_pct: 41.2 },
            { ts: 2, event: 'refused', device_id: 'genset_a_01', command: 'RESET_P2_OL@GENSET_A_01', detail: '<no trip>' },
            { ts: 3, event: 'protection_trip', device_id: 'genset_a_01', relay: 'SHUTDOWN', detail: 'LOW FUEL' },
            { ts: 4, event: 'command', device_id: 'genset_a_01', command: 'START', to_state: 'CRANKING' },
        ];
        expect(events.filter(isGenEvent)).toHaveLength(3);
        expect(genEventText(events[0])).toBe('P2_AUTO@GENSET_A_01 · ON LOAD · DAY TANK 41.2 %');
        const html = fieldLogHtml(events, '', 'genset_a_01', { match: isGenEvent, text: genEventText, empty: 'none' });
        expect(html).toContain('&lt;no trip&gt;');
        expect(html).toContain('SHUTDOWN · LOW FUEL');
    });
});

describe('Power view + faceplate wiring (L3)', () => {
    afterEach(() => { vi.restoreAllMocks(); __power_test__.closeField(); });

    it('faceplate offers the generator field view', () => {
        const html = faceplateHtml('genset_a', { devices: [GEN()], paths: [PATH] });
        expect(html).toContain('data-fp-equip="gen"');
        expect(html).toContain('data-fp-gen="1"');
    });

    it('opens the generator view, switches set, posts an action', async () => {
        document.body.innerHTML = '<div id="view-power"><div class="pid-canvas"><svg class="pid-svg"></svg></div></div>';
        const xfer = { id: 'mvtc_a', kind: 'transfer', path: 'a', state: 'GENERATORS', cubicles: [] };
        const g4 = { ...GEN(), id: 'genset_a_04', display: 'Generator A4' };
        __power_test__.setPlant({ paths: [PATH], devices: [xfer, GEN(), g4], events: [] });
        const calls = [];
        vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, opts) => {
            calls.push([String(url), opts && opts.body]);
            const body = String(url).includes('/fuel')
                ? { success: true, event: { to_state: 'ON_LOAD', day_tank_pct: 55 } }
                : { paths: [PATH], devices: [xfer, GEN(), g4], events: [] };
            return { ok: true, status: 200, json: async () => body };
        });
        __power_test__.openField('a', 'gen', 1);
        const el = document.getElementById('pwr-field');
        expect(el.getAttribute('aria-label')).toBe('Field view: generator set');
        await __power_test__.onFieldClick({ target: el.querySelector('[data-act="set"][data-n="4"] rect') });
        expect(el.querySelector('[data-txt="head"]').textContent).toContain('GENERATOR A4');
        await __power_test__.onFieldClick({ target: el.querySelector('[data-act="p2_auto"] text') });
        const post = calls.find(([u]) => u.includes('/api/devices/genset_a_04/fuel'));
        expect(JSON.parse(post[1])).toMatchObject({ action: 'P2_AUTO' });
    });
});
