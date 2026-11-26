/**
 * L6: disturbance recorder view (core/field_scope.js) and its wiring in
 * the Power view.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { scopeSvg, applyScopeState, resolveScopeClick, liveWave, polyPoints, animate, PLOTS }
    from '/assets/js/core/field_scope.js';
import { __power_test__ } from '/assets/js/views/power.js';

const N = 768;
const wave = (amp, from = 0) => Array.from({ length: N }, (_, i) => (i < from ? 11.27 : amp) * Math.sin(i / 32 * 2 * Math.PI));
const REC = {
    id: 'DFR-A-0001', path: 'a', ts: 1795000000, trigger: 'MV UTILITY -> NONE', cause: ['utility_lost 27'],
    fs: 1920, pre_s: 0.1, post_s: 0.3,
    summary: { MV: { min_pu: 0, below_0_9_ms: 291.7, class: 'interruption (still on at the end of the record)', thd_pct: 0, transition: 'collapse', transition_ms: 0 },
        LD: { min_pu: 1, below_0_9_ms: 0, class: 'no RMS variation', thd_pct: 0, transition: 'none', transition_ms: 0 } },
    samples: { MV_VA: wave(0, 192), MV_VB: wave(0, 192), MV_VC: wave(0, 192), LD_VA: wave(391), LD_VB: wave(391), LD_VC: wave(391) },
};

function mount(ui) {
    document.body.innerHTML = `<div id="root">${scopeSvg('a')}</div>`;
    const root = document.getElementById('root');
    applyScopeState(root, ui);
    return root;
}

describe('field_scope: pure helpers', () => {
    it('live wave follows the path state', () => {
        const ok = liveWave({ source: 'UTILITY', load: 'inverter' }, 'MV');
        expect(Math.max(...ok.A)).toBeCloseTo(PLOTS.MV.vln * Math.SQRT2, 1);
        expect(Math.max(...liveWave({ source: 'NONE', load: 'inverter' }, 'MV').A)).toBe(0);
        expect(Math.max(...liveWave({ source: 'NONE', load: 'inverter' }, 'LD').A)).toBeGreaterThan(270);
        expect(Math.max(...liveWave({ source: 'NONE', load: 'static_bypass' }, 'LD').A)).toBe(0);
        const d = liveWave({ source: 'UTILITY', load: 'inverter_distorted' }, 'LD');
        expect(d.A).not.toEqual(liveWave({ source: 'UTILITY', load: 'inverter' }, 'LD').A);
    });

    it('polyline points stay inside the plot and honour the playhead', () => {
        const pts = polyPoints([0, 400, -400], 'LD').split(' ');
        expect(pts).toHaveLength(3);
        const ys = pts.map((p) => Number(p.split(',')[1]));
        expect(Math.min(...ys)).toBeGreaterThanOrEqual(PLOTS.LD.y);
        expect(Math.max(...ys)).toBeLessThanOrEqual(PLOTS.LD.y + PLOTS.LD.h);
        expect(polyPoints([1, 2, 3, 4], 'MV', 2).split(' ')).toHaveLength(2);
    });

    it('animate runs until the step returns false', async () => {
        let n = 0;
        const stop = animate(() => { n += 1; return n < 3; }, null);
        await new Promise((r) => { setTimeout(r, 120); });
        stop();
        expect(n).toBe(3);
    });
});

describe('field_scope: drawing', () => {
    it('two screens, six traces, honest labels', () => {
        const root = mount({ mode: 'live', records: [], dfr: { source: 'UTILITY', load: 'inverter', hz: 60 }, path: 'a' });
        expect(root.querySelectorAll('.xo-trace[data-trace]')).toHaveLength(6);
        expect(root.innerHTML).toContain('COMTRADE C37.111-1999');
        expect(root.innerHTML).toContain('MODEL TRANSITION TIMES');
        expect(root.querySelector('[data-txt="s2"]').textContent).toBe('MV ON UTILITY · 60.00 Hz');
        expect(root.querySelector('[data-trace="MV_VA"]').getAttribute('points').split(' ').length).toBeGreaterThan(100);
    });

    it('a record replays to the playhead with its IEEE 1159 summary', () => {
        const root = mount({ mode: 'records', records: [REC], record: REC, selected: REC.id, playhead: 0.5 });
        expect(root.querySelector('[data-trace="MV_VA"]').getAttribute('points').split(' ')).toHaveLength(384);
        expect(root.querySelector('[data-txt="s2"]').textContent).toContain('INTERRUPTION');
        expect(root.querySelector('[data-txt="s3"]').textContent).toContain('NO RMS VARIATION');
        expect(root.querySelector('.xo-rec[data-idx="0"]').getAttribute('data-on')).toBe('1');
        expect(root.querySelector('[data-txt="r0b"]').textContent).toBe('MV UTILITY -> NONE');
    });

    it('zoom shows 192 samples around the trigger', () => {
        const root = mount({ mode: 'records', records: [REC], record: REC, selected: REC.id, playhead: 1, zoom: true });
        expect(root.querySelector('[data-trace="LD_VA"]').getAttribute('points').split(' ')).toHaveLength(192);
        expect(root.querySelector('[data-txt="tbase"]').textContent).toContain('ZOOM');
    });

    it('record text is escaped by construction (textContent)', () => {
        const bad = { ...REC, trigger: '<img src=x onerror=1>' };
        const root = mount({ mode: 'records', records: [bad], record: bad, selected: bad.id, playhead: 1 });
        expect(root.innerHTML).not.toContain('<img');
    });
});

describe('field_scope: clicks', () => {
    it('modes, records, play, trigger, sag and downloads', () => {
        const root = mount({ mode: 'live', records: [REC] });
        const at = (sel, ui) => resolveScopeClick(root.querySelector(sel), ui);
        expect(at('[data-act="live"] rect', {})).toEqual({ ui: { mode: 'live' } });
        expect(at('[data-act="records"] rect', { records: [REC] })).toMatchObject({ fetch: REC.id });
        expect(at('.xo-rec[data-idx="0"] rect', { records: [REC] })).toMatchObject({ fetch: REC.id, play: true });
        expect(at('.xo-rec[data-idx="3"] rect', { records: [REC] })).toBeNull();
        expect(at('[data-act="trigger"] rect', {})).toEqual({ action: 'trigger' });
        expect(at('[data-act="sag"] rect', {})).toEqual({ action: 'sag' });
        expect(at('[data-act="cfg"] rect', {})).toBeNull();
        expect(at('[data-act="dat"] rect', { selected: REC.id })).toEqual({ download: 'dat' });
        expect(at('.xo-screen', { mode: 'records', record: REC })).toEqual({ ui: { zoom: true } });
        expect(at('.xo-screen', { mode: 'live' })).toBeNull();
    });
});

describe('Power view wiring (L6)', () => {
    afterEach(() => { vi.restoreAllMocks(); __power_test__.closeField(); });

    it('opens the recorder, lists records and injects a training sag', async () => {
        document.body.innerHTML = '<div id="view-power"><div class="pid-canvas"><svg class="pid-svg"></svg></div></div>';
        const xfer = { id: 'mvtc_a', kind: 'transfer', path: 'a', state: 'UTILITY', cubicles: [] };
        const ps = { path: 'a', dfr: { source: 'UTILITY', load: 'inverter', hz: 60 } };
        __power_test__.setPlant({ paths: [ps], devices: [xfer], events: [] });
        const calls = [];
        vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, opts) => {
            const u = String(url);
            calls.push([u, opts && opts.method, opts && opts.body]);
            let body = { paths: [ps], devices: [xfer], events: [] };
            if (u.includes('/api/oscillography/records?')) body = { records: [REC] };
            else if (u.includes('/api/oscillography/records/')) body = REC;
            else if (u.includes('/sag')) body = { success: true, record: REC };
            return { ok: true, status: 200, json: async () => body };
        });
        __power_test__.openField('a', 'scope');
        const el = document.getElementById('pwr-field');
        expect(el.getAttribute('aria-label')).toBe('Field view: disturbance recorder');
        await new Promise((r) => { setTimeout(r, 20); });
        expect(calls.some(([u]) => u.includes('/api/oscillography/records?path=a'))).toBe(true);
        await __power_test__.onFieldClick({ target: el.querySelector('[data-act="sag"] rect') });
        const post = calls.find(([u, m]) => u.includes('/api/oscillography/a/sag') && m === 'POST');
        expect(JSON.parse(post[2])).toMatchObject({ depth_pu: 0.6, cycles: 6 });
        expect(el.querySelector('[data-section="SCOPE"]').getAttribute('data-mode')).toBe('records');
    });
});
