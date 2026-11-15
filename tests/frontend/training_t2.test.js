/* T2: control-room audio, SBO faceplate, training coach (pure parts)
 * and their wiring on the Power view. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { ControlRoomAudio } from '/assets/js/core/control_room_audio.js';
import { faceplateHtml, devicesFor } from '/assets/js/core/sbo_faceplate.js';
import { trainingHtml, fmtElapsed } from '/assets/js/core/training_view.js';
import { initPowerGrid, restoreAll } from '/assets/js/core/power_grid.js';
import { __power_test__ } from '/assets/js/views/power.js';

function fakeWin() {
    const calls = [];
    class Osc {
        constructor() { this.type = ''; this.frequency = { setValueAtTime: () => {}, exponentialRampToValueAtTime: () => {} }; }
        connect() {} start() { calls.push(this.type); } stop() {}
    }
    class Ctx {
        constructor() { this.state = 'running'; this.currentTime = 0; this.destination = {}; }
        createOscillator() { return new Osc(); }
        createGain() { return { gain: { setValueAtTime: () => {}, exponentialRampToValueAtTime: () => {} }, connect() {} }; }
    }
    const store = {};
    return { win: { AudioContext: Ctx, localStorage: { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = v; } } }, calls };
}

describe('ControlRoomAudio', () => {
    it('is off by default and silent until switched on', () => {
        const { win, calls } = fakeWin();
        const a = new ControlRoomAudio(win);
        expect(a.on).toBe(false);
        expect(a.alarm('HIGH')).toBe(false);
        expect(calls).toEqual([]);
        a.setOn(true);
        expect(a.alarm('HIGH')).toBe(true);
        expect(calls).toEqual(['square', 'square']);
        a.breaker(true); a.chime(); a.engineStart();
        expect(calls.length).toBe(7);
    });
    it('remembers the choice and fails silent without Web Audio', () => {
        const { win } = fakeWin();
        new ControlRoomAudio(win).setOn(true);
        expect(new ControlRoomAudio(win).on).toBe(true);
        const none = new ControlRoomAudio({ localStorage: null });
        expect(none.supported).toBe(false);
        expect(none.setOn(true)).toBe(false);
        expect(none.alarm()).toBe(false);
    });
});

const PLANT = {
    paths: [{ path: 'a', battery_soc_pct: 62.5, battery_runtime_min: 14.9, bus_energized: false, load_lost: false }],
    devices: [
        { id: 'mvtc_a', kind: 'transfer', path: 'a', display: 'MV transfer controller A', state: 'OPEN',
          authority: 'AUTO', status: { tone: 'crit', text: '52-U tripped (ANSI 27): MV bus dead' },
          indications: [{ label: '52-U utility incomer', value: 'OPEN' }],
          commands: [
              { command: 'START_GENERATORS', label: 'Start generator bus', permitted: false, blocked_reason: 'Device is in AUTO' },
              { command: 'TRANSFER_TO_GENERATORS', label: 'Transfer to generators', permitted: false, blocked_reason: 'Generator bus has 0.0 MW <b>' },
          ] },
        { id: 'genset_a_01', kind: 'generator', path: 'a', display: 'Generator A1', state: 'STANDBY', authority: 'REMOTE',
          status: { tone: 'ok', text: 'Ready' }, commands: [{ command: 'START', label: 'Start engine', permitted: true }] },
        { id: 'ups_a_01', kind: 'ups', path: 'a', display: 'UPS A1', state: 'DOUBLE_CONVERSION', authority: 'AUTO', status: {}, commands: [] },
        { id: 'mvtc_b', kind: 'transfer', path: 'b', display: 'B', state: 'UTILITY', commands: [] },
    ],
};

describe('sbo_faceplate', () => {
    it('maps SLD targets to devices', () => {
        expect(devicesFor('mvtc_a', PLANT).map((d) => d.id)).toEqual(['mvtc_a']);
        expect(devicesFor('genset_a', PLANT).map((d) => d.id)).toEqual(['mvtc_a', 'genset_a_01']);
        expect(devicesFor('ups_a', PLANT).map((d) => d.id)).toEqual(['ups_a_01']);
        expect(devicesFor('rpp_a1', PLANT)).toEqual([]);
    });
    it('shows authority, disabled commands with the server reason (escaped)', () => {
        const h = faceplateHtml('mvtc_a', PLANT);
        expect(h).toContain('data-fp-auth="mvtc_a"');
        expect(h).toContain('disabled title="Device is in AUTO"');
        expect(h).toContain('&lt;b&gt;');
        expect(h).not.toContain('<b>Generator bus');
        expect(h).toContain('SIMULATED plant');
    });
    it('armed selection shows EXECUTE / CANCEL and the countdown', () => {
        const pending = new Map([['mvtc_a', { token: 't', label: 'Start generator bus', expiresAt: 25_400 }]]);
        const h = faceplateHtml('mvtc_a', PLANT, { pending, nowMs: 1000 });
        expect(h).toContain('ARMED · Start generator bus · 25 s');
        expect(h).toContain('data-fp-exec="mvtc_a"');
        expect(h).not.toContain('data-fp-select="mvtc_a"');
    });
    it('no plant: asks to sign in', () => {
        expect(faceplateHtml('mvtc_a', null)).toContain('sign in');
    });
});

const DRILLS = [{ id: 'DRILL-01', title: 'Utility loss <x>', target_s: 60, time_limit_s: 1800 }];
const ACTIVE = {
    active: true,
    session: {
        drill: { id: 'DRILL-01', title: 'Utility loss', summary: 'Recover', path: 'a', target_s: 60, time_limit_s: 1800 },
        started_ms: 1_000_000, outcome: null,
        steps: [
            { id: 'ACK', text: 'Acknowledge', done: true, t_ms: 4210, current: false },
            { id: 'START', text: 'Start', done: false, t_ms: null, current: true },
        ],
    },
};

describe('training_view', () => {
    it('formats elapsed time with ms', () => {
        expect(fmtElapsed(65_432)).toBe('01:05.432');
        expect(fmtElapsed(null)).toBe('—');
    });
    it('idle: drill picker, start and reset, escaped titles', () => {
        const h = trainingHtml({ drills: DRILLS });
        expect(h).toContain('data-tr-start="1"');
        expect(h).toContain('Utility loss &lt;x&gt;');
        expect(h).toContain('Sound OFF');
    });
    it('active: steps with state and times, clock, battery, abort', () => {
        const h = trainingHtml({ drills: DRILLS, view: ACTIVE, nowMs: 1_012_345, pathSummary: PLANT.paths[0] });
        expect(h).toContain('00:12.345');
        expect(h).toContain('data-state="done"');
        expect(h).toContain('00:04.210');
        expect(h).toContain('data-state="current"');
        expect(h).toContain('ON BATTERY · 62.5 % · 14.9 min left');
        expect(h).toContain('data-tr-abort="1"');
    });
    it('finished: outcome, score, rubric note and report download', () => {
        const done = { active: false, session: { ...ACTIVE.session, outcome: 'PASS', score: 88, violations: 1, ledger_entry_id: 'abcdef1234567890' } };
        const h = trainingHtml({ drills: DRILLS, view: done });
        expect(h).toContain('PASS');
        expect(h).toContain('Score 88 / 100');
        expect(h).toContain('ledger abcdef123456');
        expect(h).toContain('data-tr-report="1"');
        expect(h).toContain('not an industry standard');
    });
});

describe('Power view wiring (T2)', () => {
    const DOM = '<div id="view-power"><div class="pid-action-bar"></div>'
        + '<div class="pid-canvas"><svg class="pid-svg"></svg></div></div>';
    const flush = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
    beforeEach(() => { initPowerGrid(); });
    afterEach(() => { __power_test__.stopTraining(); vi.unstubAllGlobals(); restoreAll(); document.body.innerHTML = ''; });

    function route(handlers) {
        return vi.fn(async (url, opts = {}) => {
            const key = `${opts.method || 'GET'} ${url}`;
            const h = handlers[key] || handlers[url];
            const body = typeof h === 'function' ? h(opts) : h;
            if (body === undefined) return { ok: false, status: 404, json: async () => ({ detail: 'nf' }) };
            return { ok: body.__status ? body.__status < 400 : true, status: body.__status || 200, json: async () => body };
        });
    }

    it('clicking 52-U opens the faceplate; SELECT then EXECUTE posts select and operate', async () => {
        const plant = JSON.parse(JSON.stringify(PLANT));
        plant.devices[0].authority = 'REMOTE';
        plant.devices[0].commands[0].permitted = true;
        plant.paths.push({ path: 'b' });
        const f = route({
            '/api/devices': plant, '/api/alarms': { alarms: [], unacked: 0 },
            'POST /api/devices/mvtc_a/select': { select_token: 'tok', label: 'Start generator bus', expires_in_s: 30 },
            'POST /api/devices/mvtc_a/operate': { success: true },
        });
        vi.stubGlobal('fetch', f);
        document.body.innerHTML = DOM;
        const { renderFlatSld, setMode, pollAlarms, onFlatClick, onFaceplateClick } = __power_test__;
        renderFlatSld();
        setMode('live');
        await pollAlarms(true);
        onFlatClick({ target: document.querySelector('[data-brk="a:u"] .pf-52-box') });
        const fp = document.getElementById('pwr-faceplate');
        expect(fp.hidden).toBe(false);
        expect(fp.textContent).toContain('52-U tripped (ANSI 27)');
        await onFaceplateClick({ target: fp.querySelector('[data-fp-cmd="START_GENERATORS"]') });
        expect(fp.querySelector('[data-fp-exec="mvtc_a"]')).not.toBeNull();
        await onFaceplateClick({ target: fp.querySelector('[data-fp-exec="mvtc_a"]') });
        const posts = f.mock.calls.filter(([, o]) => o && o.method === 'POST').map(([u, o]) => [u, JSON.parse(o.body)]);
        expect(posts[0][0]).toBe('/api/devices/mvtc_a/select');
        expect(posts[0][1].command).toBe('START_GENERATORS');
        expect(posts[1][0]).toBe('/api/devices/mvtc_a/operate');
        expect(posts[1][1].select_token).toBe('tok');
    });

    it('refused command shows the reason in the faceplate', async () => {
        const f = route({
            '/api/devices': PLANT, '/api/alarms': { alarms: [], unacked: 0 },
            'POST /api/devices/mvtc_a/authority': { __status: 403, detail: 'role' },
        });
        vi.stubGlobal('fetch', f);
        document.body.innerHTML = DOM;
        const { renderFlatSld, setMode, pollAlarms, openFaceplate, onFaceplateClick } = __power_test__;
        renderFlatSld();
        setMode('live');
        await pollAlarms(true);
        openFaceplate('mvtc_a');
        const fp = document.getElementById('pwr-faceplate');
        await onFaceplateClick({ target: fp.querySelector('[data-fp-auth="mvtc_a"]') });
        expect(fp.textContent).toContain('FACILITY_MANAGER');
    });

    it('training: start posts the selected drill and the coach shows the steps', async () => {
        let started = false;
        const f = route({
            '/api/devices': PLANT, '/api/alarms': { alarms: [], unacked: 0 },
            '/api/training/drills': { drills: DRILLS },
            '/api/training/session': () => (started ? ACTIVE : { active: false, session: null }),
            'POST /api/training/start': () => { started = true; return ACTIVE; },
        });
        vi.stubGlobal('fetch', f);
        vi.useFakeTimers();
        document.body.innerHTML = DOM;
        const { renderFlatSld, setMode, loadTraining, onTrainingClick } = __power_test__;
        renderFlatSld();
        setMode('live');
        await loadTraining();
        const tr = document.getElementById('pwr-training');
        expect(tr.querySelector('[data-tr-start]')).not.toBeNull();
        await onTrainingClick({ target: tr.querySelector('[data-tr-start]') });
        await flush();
        const post = f.mock.calls.find(([u, o]) => u === '/api/training/start' && o.method === 'POST');
        expect(JSON.parse(post[1].body).drill_id).toBe('DRILL-01');
        expect(tr.dataset.active).toBe('1');
        expect(tr.textContent).toContain('Acknowledge');
        vi.useRealTimers();
    });

    it('training start refused for a non-manager says why', async () => {
        const f = route({
            '/api/devices': PLANT, '/api/alarms': { alarms: [], unacked: 0 },
            '/api/training/drills': { drills: DRILLS },
            '/api/training/session': { active: false, session: null },
            'POST /api/training/start': { __status: 403, detail: 'role' },
        });
        vi.stubGlobal('fetch', f);
        document.body.innerHTML = DOM;
        const { renderFlatSld, setMode, loadTraining, onTrainingClick } = __power_test__;
        renderFlatSld();
        setMode('live');
        await loadTraining();
        const tr = document.getElementById('pwr-training');
        await onTrainingClick({ target: tr.querySelector('[data-tr-start]') });
        expect(tr.textContent).toContain('FACILITY_MANAGER');
    });
});
