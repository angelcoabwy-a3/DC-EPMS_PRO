/* T3: synchroscope display (closed-transition training mode). */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { wrapDeg, needleAngle, permissive, synchroscopeHtml } from '/assets/js/core/synchroscope.js';
import { faceplateHtml } from '/assets/js/core/sbo_faceplate.js';
import { initPowerGrid, restoreAll } from '/assets/js/core/power_grid.js';
import { __power_test__ } from '/assets/js/views/power.js';

const SYNC = {
    enabled: true, live: true, gen_hz: 60.25, utility_hz: 60, slip_hz: 0.25, angle_deg: 150,
    max_angle_deg: 10, max_slip_hz: 0.1, permissive: false,
};

describe('synchroscope maths', () => {
    it('wraps into [-180, 180)', () => {
        expect(wrapDeg(190)).toBe(-170);
        expect(wrapDeg(-190)).toBe(170);
        expect(wrapDeg(180)).toBe(-180);
    });
    it('extrapolates the needle with the slip between polls', () => {
        // 0.25 Hz = 90 deg/s: 150 + 90 = 240 -> -120
        expect(needleAngle(SYNC, 0, 1000)).toBeCloseTo(-120);
        expect(needleAngle({ ...SYNC, live: false }, 0, 5000)).toBe(150);
    });
    it('permissive needs angle AND slip inside the window', () => {
        expect(permissive(SYNC, 5)).toBe(false);                   // slip too high
        expect(permissive({ ...SYNC, slip_hz: 0.05 }, 5)).toBe(true);
        expect(permissive({ ...SYNC, slip_hz: 0.05 }, 15)).toBe(false);
    });
});

describe('synchroscope markup', () => {
    it('dial, window, readouts, lamp and governor buttons; nothing when the mode is off', () => {
        const h = synchroscopeHtml('mvtc_a', SYNC);
        expect(h).toContain('data-sync-needle="mvtc_a"');
        expect(h).toContain('rotate(150.0 60 60)');
        expect(h).toContain('SLIP <b>+0.250 Hz</b>');
        expect(h).toContain('25 BLOCK');
        expect(h).toContain('data-delta="-0.05"');
        expect(h).toContain('outside the A3 design');
        expect(synchroscopeHtml('mvtc_a', { ...SYNC, enabled: false })).toBe('');
    });
    it('faceplate embeds the synchroscope for the transfer controller only', () => {
        const plant = { paths: [], devices: [
            { id: 'mvtc_a', kind: 'transfer', path: 'a', state: 'GENERATORS', synchro: SYNC, commands: [] },
            { id: 'genset_a_01', kind: 'generator', path: 'a', state: 'ON_LOAD', commands: [] },
        ] };
        const h = faceplateHtml('genset_a', plant);
        expect((h.match(/data-sync-needle/g) || []).length).toBe(1);
    });
});

describe('Power view: governor and needle (T3)', () => {
    const DOM = '<div id="view-power"><div class="pid-action-bar"></div>'
        + '<div class="pid-canvas"><svg class="pid-svg"></svg></div></div>';
    afterEach(() => { vi.unstubAllGlobals(); restoreAll(); document.body.innerHTML = ''; });

    it('governor button posts delta_hz; frame moves the needle and the lamp', async () => {
        initPowerGrid();
        const plant = { paths: [{ path: 'a' }, { path: 'b' }], devices: [
            { id: 'mvtc_a', kind: 'transfer', path: 'a', state: 'GENERATORS', authority: 'REMOTE',
              synchro: { ...SYNC, slip_hz: 0.05, angle_deg: -30 }, commands: [] },
        ] };
        const f = vi.fn(async (url, o = {}) => ({
            ok: true, status: 200,
            json: async () => (String(url).includes('/api/devices') && !o.method ? plant : (url === '/api/alarms' ? { alarms: [], unacked: 0 } : { success: true })),
        }));
        vi.stubGlobal('fetch', f);
        vi.stubGlobal('requestAnimationFrame', () => 1);
        document.body.innerHTML = DOM;
        const { renderFlatSld, setMode, pollAlarms, openFaceplate, onFaceplateClick, syncFrame } = __power_test__;
        renderFlatSld();
        setMode('live');
        await pollAlarms(true);
        openFaceplate('mvtc_a');
        const fp = document.getElementById('pwr-faceplate');
        await onFaceplateClick({ target: fp.querySelector('[data-fp-gov="mvtc_a"][data-delta="-0.01"]') });
        const post = f.mock.calls.find(([u, o]) => u === '/api/devices/mvtc_a/governor' && o.method === 'POST');
        expect(JSON.parse(post[1].body).delta_hz).toBe(-0.01);
        // 0.05 Hz = 18 deg/s: -30 deg + 1.5 s -> -3 deg, inside the window
        syncFrame(Date.now() + 1500);
        expect(fp.querySelector('[data-sync-lamp="mvtc_a"]').textContent).toBe('25 PERMIT');
        expect(fp.querySelector('[data-sync-needle="mvtc_a"]').getAttribute('transform')).toMatch(/rotate\(-[0-9]/);
    });
});

describe('supervised close display (T3b)', () => {
    it('ETA counts down from the server sample and says IN WINDOW at zero', async () => {
        const { etaNow, etaText } = await import('/assets/js/core/synchroscope.js');
        const s = { ...SYNC, window_eta_s: 12.4 };
        expect(etaNow(s, 0, 2000)).toBeCloseTo(10.4);
        expect(etaText(etaNow(s, 0, 20000))).toBe('IN WINDOW');
        expect(etaText(null)).toMatch(/not reached/);
        expect(etaNow({ ...s, live: false }, 0, 0)).toBe(null);
    });
    it('armed close shows the countdown and a cancel button', () => {
        const h = synchroscopeHtml('mvtc_a', { ...SYNC, window_eta_s: 5, close_armed: true, close_remaining_s: 23.6 });
        expect(h).toContain('SYNC CLOSE ARMED');
        expect(h).toContain('24 s left');
        expect(h).toContain('data-fp-synccancel="mvtc_a"');
        expect(h).toContain('Window in 5.0 s');
        expect(synchroscopeHtml('mvtc_a', SYNC)).not.toContain('SYNC CLOSE ARMED');
    });
});
