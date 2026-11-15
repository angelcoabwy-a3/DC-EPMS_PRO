/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/power_status.test.js
 * SLD "vida 2": per-path status strip + clocked sequence of events.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import { pathStatus, statusStrip, diffEvents, EventLog } from '/assets/js/core/power_status.js';
import {
    initPowerGrid, tripNode, restoreAll, getGridState, setUnitsOut,
} from '/assets/js/core/power_grid.js';
import { __power_test__ } from '/assets/js/views/power.js';

beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(0); initPowerGrid(); });
afterEach(() => { restoreAll(); vi.useRealTimers(); document.body.innerHTML = ''; });

describe('status strip', () => {
    it('nominal: both paths on utility, 50 %, UPS and GEN N+1, 52-U closed', () => {
        const rows = pathStatus(getGridState());
        for (const r of rows) {
            expect(r.sourceLabel).toBe('UTILITY');
            expect(r.share).toBe(0.5);
            expect(r.ups.txt).toBe('N+1');
            expect(r.gen.txt).toBe('N+1');
            expect(r.u52).toBe('closed');
            expect(r.gm52).toBe('open');
        }
    });

    it('transfer gap -> battery, both breakers open; then generators with 52-GM closed', () => {
        tripNode('util_a');
        let a = pathStatus(getGridState())[0];
        expect(a.sourceLabel).toBe('BATTERY');
        expect(a.transferring).toBe(true);
        expect(a.u52).toBe('open');
        expect(a.gm52).toBe('open');
        vi.advanceTimersByTime(2000);
        a = pathStatus(getGridState())[0];
        expect(a.sourceLabel).toBe('GENERATORS');
        expect(a.gm52).toBe('closed');
        expect(a.u52).toBe('open');
    });

    it('blocks out lower the UPS tag; a dead bank shows NO OUTPUT and moves the load', () => {
        setUnitsOut('ups_a', 1);
        expect(pathStatus(getGridState())[0].ups.txt).toBe('N');
        setUnitsOut('ups_a', 2);
        expect(pathStatus(getGridState())[0].ups.txt).toBe('< N');
        setUnitsOut('ups_b', 8);
        const [a, b] = pathStatus(getGridState());
        expect(b.sourceLabel).toBe('NO OUTPUT');
        expect(a.share).toBe(1);
    });

    it('renders one row per path with data attributes for styling', () => {
        document.body.innerHTML = statusStrip(getGridState());
        expect(document.querySelectorAll('.pwr-strip-row').length).toBe(2);
        expect(document.querySelector('[data-path="a"] [data-k="load"]').textContent).toBe('8.38 MW · 50 %');
        expect(document.querySelector('[data-path="b"] [data-k="u52"]').dataset.state).toBe('closed');
    });
});

describe('sequence of events', () => {
    it('diffEvents reads a utility loss as loss + 52-U opening + crank + battery', () => {
        const before = JSON.parse(JSON.stringify(getGridState()));
        tripNode('util_a');
        const texts = diffEvents(before, getGridState(), 'a').map((e) => e.text);
        expect(texts).toContain('UTILITY A lost');
        expect(texts).toContain('52-U opens · transfer A started');
        expect(texts).toContain('GEN BUS A CRANKING');
        expect(texts).toContain('UPS BANK A on battery');
        expect(diffEvents(before, getGridState(), 'b')).toEqual([]);
    });

    it('EventLog stamps the full transfer with a clock from t = 0', () => {
        const log = new EventLog({ now: () => Date.now() });
        log.observe(getGridState());               // baseline, no events
        tripNode('util_a');
        log.observe(getGridState());
        vi.advanceTimersByTime(800);
        log.observe(getGridState());
        vi.advanceTimersByTime(1200);
        log.observe(getGridState());
        const seq = log.events.map((e) => [e.t, e.text]);
        expect(seq[0]).toEqual([0, 'UTILITY A lost']);
        const gm = seq.find(([, t]) => t === '52-GM closes · PATH A on generators');
        expect(gm[0]).toBeCloseTo(2.0, 5);
        const run = seq.find(([, t]) => t === 'GEN BUS A RUNNING');
        expect(run[0]).toBeCloseTo(0.8, 5);
        expect(log.elapsed()).toBeCloseTo(2.0, 5);
    });

    it('reset clears the sequence; render escapes and shows an empty hint', () => {
        const log = new EventLog();
        expect(log.render()).toContain('No events');
        log.events.push({ t: 0, path: 'a', level: 'crit', text: '<img src=x onerror=alert(1)>' });
        document.body.innerHTML = log.render();
        expect(document.querySelector('img')).toBeNull();
        log.reset();
        expect(log.events).toEqual([]);
        expect(log.elapsed()).toBeNull();
    });

    it('a baseline at reset means the first change is already recorded', () => {
        const log = new EventLog();
        log.reset(getGridState());
        setUnitsOut('ups_b', 1);
        log.observe(getGridState());
        expect(log.events.map((e) => e.text)).toEqual(['UPS BANK B: 1 block(s) out']);
    });

    it('caps the log length', () => {
        const log = new EventLog({ max: 3 });
        log.observe(getGridState());
        for (let i = 1; i <= 4; i++) { setUnitsOut('ups_a', i % 2); log.observe(getGridState()); }
        expect(log.events.length).toBe(3);
    });
});

describe('Power view wiring', () => {
    it('What-If mounts the strip and the sequence panel and fills them on a trip', () => {
        vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503, json: async () => ({}) })));
        document.body.innerHTML = '<div id="view-power"><div class="pid-action-bar"></div>'
            + '<div class="pid-canvas"><svg class="pid-svg"></svg></div></div>';
        const { renderFlatSld, setMode, applyGrid, eventLog } = __power_test__;
        renderFlatSld();
        setMode('whatif');
        applyGrid(getGridState());
        expect(document.getElementById('pwr-status').querySelectorAll('.pwr-strip-row').length).toBe(2);
        tripNode('util_b');
        applyGrid(getGridState());
        expect(document.getElementById('pwr-tl-body').textContent).toContain('UTILITY B lost');
        expect(document.getElementById('pwr-tl-clock').textContent).toBe('t = 0.0 s');
        expect(eventLog.events.length).toBeGreaterThan(0);
        setMode('live');
        expect(eventLog.events.length).toBe(0);
        vi.unstubAllGlobals();
    });
});

describe('HMI H4: alarm banner on the Power view', () => {
    const DOM = '<div id="view-power"><div class="pid-action-bar"></div>'
        + '<div class="pid-canvas"><svg class="pid-svg"></svg></div></div>';
    const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
    afterEach(() => { vi.unstubAllGlobals(); });

    it('What-If: sandbox alarms appear on a trip and ACK is local (no POST)', () => {
        const fetchSpy = vi.fn(async () => ({ ok: false, status: 503, text: async () => '', json: async () => ({}) }));
        vi.stubGlobal('fetch', fetchSpy);
        document.body.innerHTML = DOM;
        const { renderFlatSld, setMode, applyGrid, sandboxAlarms } = __power_test__;
        renderFlatSld();
        setMode('whatif');
        applyGrid(getGridState());
        const banner = document.getElementById('pwr-alarms');
        expect(banner.dataset.source).toBe('sandbox');
        expect(banner.textContent).toContain('No active alarms');
        tripNode('util_a');
        applyGrid(getGridState());
        expect(banner.querySelector('[data-state="UNACK"]')).not.toBeNull();
        expect(banner.textContent).toContain('Path A utility supply lost');
        fetchSpy.mockClear();
        banner.querySelector('[data-ack-all]').click();
        expect(sandboxAlarms.snapshot().unacked).toBe(0);
        expect(banner.querySelector('[data-state="UNACK"]')).toBeNull();
        expect(fetchSpy).not.toHaveBeenCalled();
        setMode('live');
        expect(sandboxAlarms.snapshot().alarms).toEqual([]);
    });

    it('LIVE: banner shows backend alarms and ACK posts to the backend', async () => {
        const live = {
            alarms: [{ id: 'PATH_A_UNPROTECTED', priority: 'HIGH', state: 'UNACK',
                message: 'Path A load not battery-backed', activated: '2026-11-15T02:00:00.123Z' }],
            unacked: 1,
        };
        const fetchSpy = vi.fn(async (url, opts) => ({
            ok: true, status: 200,
            json: async () => (opts && opts.method === 'POST' ? { success: true } : live),
        }));
        vi.stubGlobal('fetch', fetchSpy);
        document.body.innerHTML = DOM;
        const { renderFlatSld, setMode, pollAlarms } = __power_test__;
        renderFlatSld();
        setMode('live');
        await pollAlarms(true);
        const banner = document.getElementById('pwr-alarms');
        expect(banner.dataset.source).toBe('live');
        expect(banner.textContent).toContain('Path A load not battery-backed');
        banner.querySelector('[data-ack="PATH_A_UNPROTECTED"]').click();
        await flush();
        const post = fetchSpy.mock.calls.find(([, o]) => o && o.method === 'POST');
        expect(post[0]).toBe('/api/alarms/PATH_A_UNPROTECTED/ack');
    });

    it('LIVE: refused ACK tells the operator to sign in', async () => {
        vi.stubGlobal('fetch', vi.fn(async (url, opts) => (opts && opts.method === 'POST'
            ? { ok: false, status: 401, text: async () => 'authentication required' }
            : { ok: true, status: 200, json: async () => ({ alarms: [{ id: 'X', priority: 'LOW', state: 'UNACK', message: 'm' }], unacked: 1 }) })));
        document.body.innerHTML = DOM;
        const { renderFlatSld, setMode, pollAlarms } = __power_test__;
        renderFlatSld();
        setMode('live');
        await pollAlarms(true);
        document.querySelector('[data-ack="X"]').click();
        await flush(); await flush(); await flush();
        expect(document.getElementById('pwr-alarms').textContent).toContain('ACK refused');
    });
});
