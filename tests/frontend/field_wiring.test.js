/**
 * L5: field view of the MV control compartment (core/field_wiring.js):
 * PT secondary fuse holders, TB-1 and the multimeter.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { wiringSvg, applyWiringState, resolveWiringClick, isWiringEvent, wiringEventText, TB_ROWS }
    from '/assets/js/core/field_wiring.js';
import { fieldLogHtml } from '/assets/js/core/field_switchgear.js';
import { faceplateHtml } from '/assets/js/core/sbo_faceplate.js';
import { __power_test__ } from '/assets/js/views/power.js';

const W = (over = {}) => ({
    fuses: { 'F-1A': { ok: false, pulled: false }, 'F-1B': { ok: true, pulled: false } },
    meter: 'VAC', measured: [], readings: [], points: {}, start_contact: true, actions: [], ...over,
});

function mount(w = W()) {
    document.body.innerHTML = `<div id="root">${wiringSvg('a')}</div>`;
    const root = document.getElementById('root');
    applyWiringState(root, w);
    return root;
}

describe('field_wiring: drawing', () => {
    it('two fuse holders, twelve TB-1 points, the meter; the fuse condition is never drawn', () => {
        const root = mount();
        expect(root.querySelectorAll('.xw-fuse')).toHaveLength(2);
        expect(root.querySelectorAll('.xw-pt')).toHaveLength(TB_ROWS.length);
        expect(root.innerHTML).toContain('SIMULATED EQUIPMENT');
        expect(root.innerHTML).not.toMatch(/blown/i);
        expect(root.querySelector('[data-section="WIRING"]').getAttribute('data-mode')).toBe('VAC');
    });

    it('shows the last reading, the beep and the leads on the probed row', () => {
        const w = W({ meter: 'OHM', fuses: { 'F-1A': { ok: true, pulled: true }, 'F-1B': { ok: true, pulled: false } },
            readings: [{ point: 'F1A_FUSE', label: 'Across fuse F-1A', mode: 'OHM', display: '0.1 Ω', beep: true, warning: null }] });
        const root = mount(w);
        expect(root.querySelector('[data-txt="disp"]').textContent).toBe('0.1 Ω');
        expect(root.querySelector('[data-txt="beep"]').textContent).toContain('BEEP');
        expect(root.querySelector('.xw-fuse[data-fuse="F1A"]').getAttribute('data-pulled')).toBe('1');
        expect(root.querySelector('.xw-pt[data-point="F1A_FUSE"]').getAttribute('data-on')).toBe('1');
        expect(root.querySelector('[data-lead="red"]').getAttribute('d')).toContain('C');
    });

    it('flags resistance on a live circuit and shows OFF', () => {
        let root = mount(W({ meter: 'OHM', readings: [{ point: 'P1_N1', label: 'Station battery', display: 'LIVE',
            beep: false, warning: 'x' }] }));
        expect(root.querySelector('[data-txt="warn"]').textContent).toContain('LIVE CIRCUIT');
        root = mount(W({ meter: 'OFF' }));
        expect(root.querySelector('[data-txt="disp"]').textContent).toBe('OFF');
    });
});

describe('field_wiring: clicks and log', () => {
    it('resolves dial, test points and fuse holders', () => {
        const root = mount();
        const at = (sel, w = W()) => resolveWiringClick(root.querySelector(sel), w);
        expect(at('.xw-dialpos[data-mode="VDC"] rect')).toMatchObject({ action: 'METER_VDC' });
        expect(at('.xw-pt[data-point="F1A_LOAD"] rect')).toMatchObject({ action: 'MEASURE_F1A_LOAD', kind: 'probe' });
        expect(at('.xw-holder[data-fuse="F1A"] rect')).toMatchObject({ action: 'PULL_F1A' });
        expect(at('.xw-holder[data-fuse="F1A"] rect', W({ fuses: { 'F-1A': { ok: false, pulled: true }, 'F-1B': {} } })))
            .toMatchObject({ action: 'INSERT_F1A' });
        expect(at('.xw-replace[data-fuse="F1B"] rect')).toMatchObject({ action: 'REPLACE_F1B' });
    });

    it('log keeps compartment events and the 27 trip', () => {
        const events = [
            { ts: 1, event: 'inspection', device_id: 'mvtc_a', equipment: 'wiring', command: 'MEASURE_F1A_LOAD@MVTC_A',
                reading: { point: 'F1A_LOAD', display: '0.0 V~' } },
            { ts: 2, event: 'protection_trip', device_id: 'mvtc_a', relay: '27', detail: 'incomer undervoltage' },
            { ts: 3, event: 'command', device_id: 'mvtc_a', field: true, breaker: '52-U', command: 'RACK_OUT' },
        ];
        expect(wiringEventText(events[0])).toBe('METER F1A_LOAD · 0.0 V~');
        const html = fieldLogHtml(events, '', 'mvtc_a', { match: isWiringEvent, text: wiringEventText, empty: 'none' });
        expect(html).toContain('ANSI 27');
        expect(html).not.toContain('RACK_OUT');
        // The switchgear log leaves the compartment events out.
        expect(fieldLogHtml(events, '', 'mvtc_a')).not.toContain('MEASURE_F1A_LOAD');
    });
});

describe('Power view + faceplate wiring (L5 control compartment)', () => {
    afterEach(() => { vi.restoreAllMocks(); __power_test__.closeField(); });

    it('MV transfer faceplate offers the control compartment', () => {
        const xfer = { id: 'mvtc_a', kind: 'transfer', path: 'a', state: 'UTILITY', cubicles: [], wiring: W() };
        expect(faceplateHtml('mvtc_a', { devices: [xfer], paths: [] })).toContain('data-fp-equip="wiring"');
    });

    it('opens the compartment and probes a point', async () => {
        document.body.innerHTML = '<div id="view-power"><div class="pid-canvas"><svg class="pid-svg"></svg></div></div>';
        const xfer = { id: 'mvtc_a', kind: 'transfer', path: 'a', state: 'GENERATORS', cubicles: [], wiring: W() };
        __power_test__.setPlant({ paths: [{ path: 'a' }], devices: [xfer], events: [] });
        const calls = [];
        vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, opts) => {
            calls.push([String(url), opts && opts.body]);
            const body = String(url).includes('/wiring')
                ? { success: true, event: { reading: { point: 'F1A_LINE', label: 'F-1A line', display: '120.0 V~' } } }
                : { paths: [{ path: 'a' }], devices: [xfer], events: [] };
            return { ok: true, status: 200, json: async () => body };
        });
        __power_test__.openField('a', 'wiring');
        const el = document.getElementById('pwr-field');
        expect(el.getAttribute('aria-label')).toBe('Field view: MV control compartment');
        await __power_test__.onFieldClick({ target: el.querySelector('.xw-pt[data-point="F1A_LINE"] rect') });
        const post = calls.find(([u]) => u.includes('/api/devices/mvtc_a/wiring'));
        expect(JSON.parse(post[1])).toMatchObject({ action: 'MEASURE_F1A_LINE' });
    });
});
