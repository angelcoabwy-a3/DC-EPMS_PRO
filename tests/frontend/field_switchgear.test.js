/**
 * L1: field view of the 13.8 kV switchgear (core/field_switchgear.js)
 * and its wiring in the Power view.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { fieldLineupSvg, applyFieldState, resolveClick, fieldLogHtml, FIELD_BREAKERS }
    from '/assets/js/core/field_switchgear.js';
import { __power_test__ } from '/assets/js/views/power.js';
import { reportDocument } from '/assets/js/core/training_print.js';

const cubicle = (breaker, over = {}) => ({
    breaker, racking: 'CONNECTED', closed: breaker === '52-U', on_bus: true, spring_charged: true,
    motor_on: true, pumps: 0, pumps_needed: 5, charging_s_left: null, lockout_86: false, padlock: null,
    control_power: true,
    actions: ['RACK_OUT', 'RACK_IN', 'LOCAL_CLOSE', 'LOCAL_OPEN', 'TRIP_86', 'RESET_86', 'MOTOR_ON',
        'MOTOR_OFF', 'PUMP_SPRING', 'PADLOCK', 'UNPADLOCK'].map((a) => ({ action: a, permitted: true })),
    ...over,
});
const XFER = (u = {}, gm = {}) => ({
    id: 'mvtc_a', kind: 'transfer', path: 'a', authority: 'LOCAL',
    cubicles: [cubicle('52-U', u), cubicle('52-GM', gm)],
});

function mount(x = XFER()) {
    document.body.innerHTML = `<div id="root">${fieldLineupSvg('a')}</div>`;
    const root = document.getElementById('root');
    applyFieldState(root, x, { covers: new Set(['52-GM:close']) });
    return root;
}

describe('field_switchgear: drawing', () => {
    it('one section per main, with the honest arc-flash label', () => {
        const root = mount();
        expect(FIELD_BREAKERS.every((b) => root.querySelector(`[data-section="${b}"]`))).toBe(true);
        expect(root.innerHTML).toContain('ARC FLASH STUDY');
        expect(root.innerHTML).toContain('NOT PERFORMED');
        expect(root.innerHTML).toContain('SIMULATED');
    });

    it('state goes to attributes, flags and lights', () => {
        const root = mount(XFER({}, { racking: 'TEST', spring_charged: false, motor_on: false, pumps: 2, lockout_86: true }));
        const u = root.querySelector('[data-section="52-U"]');
        const gm = root.querySelector('[data-section="52-GM"]');
        expect(u.getAttribute('data-closed')).toBe('1');
        expect(u.querySelector('.fsg-flag-txt').textContent).toContain('CLOSED');
        expect(u.querySelector('[data-led="closed"]').getAttribute('data-on')).toBe('1');
        expect(gm.getAttribute('data-racking')).toBe('TEST');
        expect(gm.getAttribute('data-86')).toBe('1');
        expect(gm.querySelector('.fsg-sflag-txt').textContent).toBe('DISCHARGED');
        expect(gm.querySelector('[data-txt="pumps"]').textContent).toBe('STROKES 2 / 5');
        expect(gm.querySelector('[data-txt="charging"]').textContent).toBe('MANUAL');
        expect(gm.querySelector('.fsg-rack-ptr').style.transform).toContain('62px');
        expect(gm.querySelector('[data-pb="close"]').getAttribute('data-cover')).toBe('open');
        expect(u.querySelector('[data-pb="close"]').getAttribute('data-cover')).toBe('shut');
        expect(root.querySelector('.fsg-key').getAttribute('data-auth')).toBe('LOCAL');
    });

    it('padlock name is escaped and clipped', () => {
        const root = mount(XFER({}, { racking: 'DISCONNECTED', padlock: '<b>mallory-the-long</b>' }));
        const gm = root.querySelector('[data-section="52-GM"]');
        expect(gm.getAttribute('data-locked')).toBe('1');
        expect(gm.querySelector('[data-txt="lockname"]').textContent).toBe('<b>mallory');
        expect(gm.innerHTML).not.toContain('<b>mallory');
    });
});

describe('field_switchgear: clicks', () => {
    it('maps every control to a server action, toggles from the state', () => {
        const root = mount(XFER({}, { lockout_86: true, motor_on: false }));
        const q = (s) => root.querySelector(s);
        expect(resolveClick(q('[data-section="52-GM"] .fsg-86-grip'), XFER({}, { lockout_86: true })))
            .toEqual({ breaker: '52-GM', action: 'RESET_86' });
        expect(resolveClick(q('[data-section="52-U"] .fsg-86-face'), XFER()))
            .toEqual({ breaker: '52-U', action: 'TRIP_86' });
        expect(resolveClick(q('[data-section="52-GM"] .fsg-sel-body'), XFER({}, { motor_on: false })).action).toBe('MOTOR_ON');
        expect(resolveClick(q('[data-section="52-U"] .fsg-lever-grip'), XFER()).action).toBe('PUMP_SPRING');
        expect(resolveClick(q('[data-section="52-U"] [data-act="rack_out"] rect'), XFER()).action).toBe('RACK_OUT');
        expect(resolveClick(q('[data-section="52-U"] [data-act="rack_in"] text'), XFER()).action).toBe('RACK_IN');
        expect(resolveClick(q('[data-section="52-U"] .fsg-hasp-plate'), XFER()).action).toBe('PADLOCK');
        expect(resolveClick(q('[data-section="52-U"] [data-pb="close"] .fsg-pb-face'), XFER()))
            .toEqual({ breaker: '52-U', action: 'LOCAL_CLOSE', kind: 'close' });
        expect(resolveClick(q('[data-section="52-U"] [data-pb="open"] .fsg-cover-glass'), XFER()))
            .toEqual({ cover: '52-U:open' });
        expect(resolveClick(q('.fsg-key-cyl'), XFER())).toEqual({ authority: 'REMOTE' });
        expect(resolveClick(q('.fsg-key-cyl'), { ...XFER(), authority: 'AUTO' })).toEqual({ authority: 'LOCAL' });
        expect(resolveClick(q('.fsg-frame'), XFER())).toBeNull();
    });

    it('event log keeps field operations and refusals of this controller, escaped', () => {
        const h = fieldLogHtml([
            { ts: 1, event: 'command', field: true, device_id: 'mvtc_a', command: 'RACK_OUT@52-GM', racking: 'TEST', actor: 'ana' },
            { ts: 2, event: 'refused', device_id: 'mvtc_a', command: 'RACK_OUT@52-U', detail: 'C1: <closed>', actor: 'ana' },
            { ts: 3, event: 'command', device_id: 'mvtc_a', command: 'START_GENERATORS', actor: 'x' },
            { ts: 4, event: 'command', field: true, device_id: 'mvtc_b', command: 'RACK_OUT@52-U', actor: 'x' },
        ], 'INTERLOCK · C1', 'mvtc_a');
        expect(h).toContain('RACK_OUT@52-GM');
        expect(h).toContain('REFUSED RACK_OUT@52-U');
        expect(h).toContain('&lt;closed&gt;');
        expect(h).not.toContain('START_GENERATORS');
        expect(h).not.toContain('mvtc_b');
        expect(h).toContain('data-tone="warn"');
    });
});

describe('Power view wiring (L1)', () => {
    afterEach(() => { vi.restoreAllMocks(); __power_test__.closeField(); });

    it('opens the field view, posts a field action and closes with Escape', async () => {
        document.body.innerHTML = '<div id="view-power"><div class="pid-canvas"><svg class="pid-svg"></svg></div></div>';
        __power_test__.setPlant({ paths: [], devices: [XFER({}, {})], events: [] });
        const calls = [];
        vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, opts) => {
            calls.push([String(url), opts && opts.body]);
            const body = String(url).includes('/field')
                ? { success: true, event: { racking: 'TEST' } } : { paths: [], devices: [XFER()], events: [] };
            return { ok: true, status: 200, json: async () => body };
        });
        __power_test__.openField('a');
        const el = document.getElementById('pwr-field');
        expect(el.hidden).toBe(false);
        expect(el.querySelector('[data-section="52-GM"]')).not.toBeNull();
        const btn = el.querySelector('[data-section="52-GM"] [data-act="pump"] .fsg-lever-grip');
        await __power_test__.onFieldClick({ target: btn });
        const post = calls.find(([u]) => u.includes('/api/devices/mvtc_a/field'));
        expect(post).toBeTruthy();
        expect(JSON.parse(post[1])).toMatchObject({ breaker: '52-GM', action: 'PUMP_SPRING' });
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
        expect(el.hidden).toBe(true);
    });

    it('the SLD carries a cubicle tag next to both mains', () => {
        const svg = __power_test__.buildFlatMarkup();
        for (const k of ['a:u', 'a:gm', 'b:u', 'b:gm']) expect(svg).toContain(`data-cub="${k}"`);
    });
});

describe('printed report references (L1)', () => {
    it('lists the drill references with the verify note', () => {
        const h = reportDocument({ drill: { id: 'DRILL-05', references: ['OSHA 29 CFR 1910.147(d) <verify>'], steps: [] },
            steps: [], soe: [], outcome: 'PASS', score: 100 });
        expect(h).toContain('References');
        expect(h).toContain('1910.147(d) &lt;verify&gt;');
        expect(h).toContain('verify against the current edition');
    });
});
