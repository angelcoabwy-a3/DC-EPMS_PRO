/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO -- tests/frontend/device_control.test.js
 * Release R3-A -- views/device_control.js
 *   - One card per device, grouped UPS / transfer / generator.
 *   - Simulation notice always printed.
 *   - Refused commands are disabled and show the server's reason.
 *   - Select-before-operate: select moves nothing, operate sends the
 *     token, expiry drops the selection.
 *   - XSS on every server-supplied string (S-SEC-01).
 *   - S-VISUAL-01 fence: every dvc-* class has a CSS rule.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { __device_control_test__ as V, initDeviceControlView } from '/assets/js/views/device_control.js';
import { isRegistered } from '/assets/js/core/router.js';

const ROOT = resolve(__dirname, '..', '..');
const HOSTILE = '<img src=x onerror=alert(1)>';

function device(overrides = {}) {
    return Object.assign({
        id: 'genset_a_01', kind: 'generator', display: 'Genset A1', path: 'a',
        vendor: 'cummins', model: 'QSK95', authority: 'REMOTE', state: 'STANDBY',
        status: { tone: 'ok', text: 'Ready to start' },
        readings: [
            { label: 'Engine speed', value: 0, unit: 'rpm' },
            { label: 'Starter battery', value: 25.6, unit: 'V' },
        ],
        commands: [
            { command: 'START', label: 'Start engine', description: 'Cranks.', permitted: true, blocked_reason: null },
            { command: 'STOP', label: 'Stop engine', description: 'Stops.', permitted: false, blocked_reason: 'Engine is not running.' },
        ],
    }, overrides);
}

function payload(devices, events = []) {
    return {
        notice: 'SIMULATED devices. No field equipment is connected.',
        devices, events, select_ttl_s: 30,
    };
}

function mount() {
    document.body.innerHTML = '<div class="view" id="view-device-control"></div>';
    return document.getElementById('view-device-control');
}

function jsonResponse(body, status = 200) {
    return { ok: status >= 200 && status < 300, status, json: async () => body };
}

async function flush() {
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
}

afterEach(() => {
    V.reset();
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
    vi.useRealTimers();
});

describe('R3-A -- renderPanels', () => {
    it('always prints the simulation notice and the control rules', () => {
        const root = mount();
        root.innerHTML = V.renderPanels(payload([device()]));
        expect(root.querySelector('.dvc-notice').textContent).toContain('SIMULATED devices');
        expect(root.querySelector('.dvc-rules').textContent).toContain('FACILITY MANAGER');
        expect(root.querySelector('.dvc-rules').textContent).toContain('Forensic Ledger');
    });

    it('groups cards as UPS, transfer switches, generators', () => {
        const root = mount();
        root.innerHTML = V.renderPanels(payload([
            device(),
            device({ id: 'ats_a', kind: 'transfer', display: 'ATS-A' }),
            device({ id: 'ups_a', kind: 'ups', display: 'UPS A' }),
            device({ id: 'ups_b', kind: 'ups', display: 'UPS B', path: 'b' }),
        ]));
        const sections = [...root.querySelectorAll('.dvc-section[data-kind]')];
        expect(sections.map((s) => s.getAttribute('data-kind'))).toEqual(['ups', 'transfer', 'generator']);
        expect(sections.map((s) => s.querySelectorAll('.dvc-card').length)).toEqual([2, 1, 1]);
        expect(sections[0].querySelector('.dvc-count').textContent).toBe('2');
    });

    it('says so when a kind has no device', () => {
        const root = mount();
        root.innerHTML = V.renderPanels(payload([device()]));
        expect(root.querySelector('[data-kind="ups"]').textContent).toContain('None in the site model');
    });
});

describe('R3-A -- renderDevice', () => {
    it('shows state as text, readings with units, and the path', () => {
        const root = mount();
        root.innerHTML = V.renderDevice(device({ state: 'ON_LOAD', status: { tone: 'warn', text: 'Carrying load' } }));
        expect(root.querySelector('.dvc-badge').textContent).toBe('ON LOAD');
        expect(root.querySelector('.dvc-card').classList.contains('dvc-tone-warn')).toBe(true);
        expect(root.querySelector('.dvc-state-text').textContent).toBe('Carrying load');
        expect(root.querySelector('.dvc-chip').textContent).toBe('PATH A');
        const readings = [...root.querySelectorAll('.dvc-reading')].map((r) => r.textContent.replace(/\s+/g, ' ').trim());
        expect(readings).toEqual(['Engine speed 0 rpm', 'Starter battery 25.6 V']);
    });

    it('disables a refused command and prints the reason once', () => {
        const root = mount();
        root.innerHTML = V.renderDevice(device());
        const [start, stop] = root.querySelectorAll('[data-dvc-action="select"]');
        expect(start.disabled).toBe(false);
        expect(stop.disabled).toBe(true);
        const reasons = [...root.querySelectorAll('.dvc-blocked li')].map((li) => li.textContent);
        expect(reasons).toEqual(['Engine is not running.']);
    });

    it('ties each reason to its command when the reasons differ', () => {
        const root = mount();
        root.innerHTML = V.renderDevice(device({ commands: [
            { command: 'START', label: 'Start engine', permitted: false, blocked_reason: 'Engine is on load, not in standby.' },
            { command: 'STOP', label: 'Stop engine', permitted: false, blocked_reason: 'This set is the only source.' },
        ] }));
        const reasons = [...root.querySelectorAll('.dvc-blocked li')].map((li) => li.textContent);
        expect(reasons).toEqual([
            'Start engine: Engine is on load, not in standby.',
            'Stop engine: This set is the only source.',
        ]);
    });

    it('marks the active authority and disables only that segment', () => {
        const root = mount();
        root.innerHTML = V.renderDevice(device({ authority: 'LOCAL' }));
        const buttons = [...root.querySelectorAll('.dvc-auth-btn')];
        expect(buttons.map((b) => b.getAttribute('aria-pressed'))).toEqual(['false', 'false', 'true']);
        expect(buttons.map((b) => b.disabled)).toEqual([false, false, true]);
        expect(root.querySelector('.dvc-auth-hint').textContent).toContain('bench simulation');
    });

    it('falls back to the info tone on an unknown tone', () => {
        const root = mount();
        root.innerHTML = V.renderDevice(device({ status: { tone: 'purple"><b>', text: 'x' } }));
        expect(root.querySelector('.dvc-card').classList.contains('dvc-tone-info')).toBe(true);
    });

    it('escapes every server-supplied string (S-SEC-01)', () => {
        const root = mount();
        root.innerHTML = V.renderPanels(payload([device({
            id: HOSTILE, display: HOSTILE, vendor: HOSTILE, model: HOSTILE, path: HOSTILE,
            state: HOSTILE, status: { tone: 'ok', text: HOSTILE },
            readings: [{ label: HOSTILE, value: 1, unit: HOSTILE }],
            commands: [{ command: HOSTILE, label: HOSTILE, description: HOSTILE, permitted: false, blocked_reason: HOSTILE }],
        })], [{ ts: 1, event: HOSTILE, device_id: HOSTILE, actor: HOSTILE, detail: HOSTILE }]));
        expect(root.querySelector('img')).toBeNull();
        expect(root.querySelectorAll('[onerror]').length).toBe(0);
        expect(root.querySelector('.dvc-card-title').textContent).toBe(HOSTILE);
    });
});

describe('R3-A -- control log', () => {
    it('describes commands, authority changes and refusals', () => {
        expect(V.eventDetail({ event: 'command', command: 'START', from_state: 'STANDBY', to_state: 'CRANKING' }))
            .toBe('START: STANDBY to CRANKING');
        expect(V.eventDetail({ event: 'authority', previous: 'AUTO', authority: 'LOCAL', source: 'bench_simulation' }))
            .toBe('AUTO to LOCAL (bench simulation)');
        expect(V.eventDetail({ event: 'refused', command: 'STOP', detail: 'Engine is not running.' }))
            .toBe('STOP: Engine is not running.');
    });

    it('prints an empty state', () => {
        const root = mount();
        root.innerHTML = V.renderEvents([]);
        expect(root.textContent).toContain('No control actions since boot.');
    });
});

describe('R3-A -- select before operate', () => {
    function wire(handlers) {
        const calls = [];
        vi.stubGlobal('fetch', vi.fn(async (url, opts = {}) => {
            calls.push({ url, method: opts.method || 'GET', body: opts.body ? JSON.parse(opts.body) : null });
            const key = `${opts.method || 'GET'} ${url}`;
            const h = handlers[key];
            return h ? h() : jsonResponse(payload([device()]));
        }));
        return calls;
    }

    it('select shows the confirmation and sends no operate', async () => {
        const root = mount();
        const calls = wire({
            'POST /api/devices/genset_a_01/select': () => jsonResponse({
                select_token: 'tok-1', command: 'START', label: 'Start engine',
                description: 'Cranks.', expires_in_s: 30,
            }),
        });
        await V.refresh();
        root.querySelector('[data-command="START"]').click();
        await flush();
        expect(root.querySelector('.dvc-confirm-title').textContent).toContain('Start engine');
        expect(root.querySelector('.dvc-countdown').textContent).toContain('Nothing has moved yet');
        expect(root.querySelector('[data-dvc-countdown]').textContent).toBe('30');
        expect(calls.some((c) => c.url.endsWith('/operate'))).toBe(false);
        expect(root.querySelector('[data-dvc-action="select"]')).toBeNull();
    });

    it('operate sends the token and reports the ledger entry', async () => {
        const root = mount();
        const calls = wire({
            'POST /api/devices/genset_a_01/select': () => jsonResponse({
                select_token: 'tok-1', command: 'START', label: 'Start engine', expires_in_s: 30,
            }),
            'POST /api/devices/genset_a_01/operate': () => jsonResponse({
                success: true, ledger_entry_id: 'abcdef12-3456',
            }),
        });
        await V.refresh();
        root.querySelector('[data-command="START"]').click();
        await flush();
        root.querySelector('[data-dvc-action="operate"]').click();
        await flush();
        const op = calls.find((c) => c.url.endsWith('/operate'));
        expect(op.body.select_token).toBe('tok-1');
        expect(V.pending.size).toBe(0);
        expect(root.querySelector('.dvc-msg-ok').textContent).toContain('Ledger entry abcdef12');
    });

    it('says so when the action was not chained', async () => {
        const root = mount();
        wire({
            'POST /api/devices/genset_a_01/select': () => jsonResponse({ select_token: 't', command: 'START', expires_in_s: 30 }),
            'POST /api/devices/genset_a_01/operate': () => jsonResponse({ success: true, ledger_entry_id: null }),
        });
        await V.refresh();
        root.querySelector('[data-command="START"]').click();
        await flush();
        root.querySelector('[data-dvc-action="operate"]').click();
        await flush();
        expect(root.querySelector('.dvc-msg').textContent).toContain('action NOT chained');
    });

    it('cancel drops the selection without calling the server', async () => {
        const root = mount();
        const calls = wire({
            'POST /api/devices/genset_a_01/select': () => jsonResponse({ select_token: 't', command: 'START', expires_in_s: 30 }),
        });
        await V.refresh();
        root.querySelector('[data-command="START"]').click();
        await flush();
        const before = calls.length;
        root.querySelector('[data-dvc-action="cancel"]').click();
        expect(V.pending.size).toBe(0);
        expect(calls.length).toBe(before);
        expect(root.querySelector('.dvc-msg').textContent).toContain('Nothing moved');
    });

    it('an expired selection disappears on the tick', async () => {
        const root = mount();
        let now = 1_000_000;
        V.setNow(() => now);
        wire({
            'POST /api/devices/genset_a_01/select': () => jsonResponse({ select_token: 't', command: 'START', expires_in_s: 30 }),
        });
        await V.refresh();
        root.querySelector('[data-command="START"]').click();
        await flush();
        now += 12_000;
        V.tick();
        expect(root.querySelector('[data-dvc-countdown]').textContent).toBe('18');
        now += 20_000;
        V.tick();
        expect(V.pending.size).toBe(0);
        expect(root.querySelector('.dvc-confirm')).toBeNull();
        expect(root.querySelector('.dvc-msg-crit').textContent).toContain('Selection expired');
    });

    it('shows the server reason on a refusal', async () => {
        const root = mount();
        wire({
            'POST /api/devices/genset_a_01/select': () => jsonResponse(
                { detail: 'device control requires FACILITY_MANAGER; role L1_OPERATOR is insufficient.' }, 403),
        });
        await V.refresh();
        root.querySelector('[data-command="START"]').click();
        await flush();
        expect(root.querySelector('.dvc-msg-crit').textContent).toContain('requires FACILITY_MANAGER');
        expect(V.pending.size).toBe(0);
    });

    it('authority change posts the mode', async () => {
        const root = mount();
        const calls = wire({
            'POST /api/devices/genset_a_01/authority': () => jsonResponse({ success: true }),
        });
        await V.refresh();
        root.querySelector('[data-mode="AUTO"]').click();
        await flush();
        const call = calls.find((c) => c.url.endsWith('/authority'));
        expect(call.body.authority).toBe('AUTO');
        expect(root.querySelector('.dvc-msg-ok').textContent).toContain('Authority set to AUTO');
    });
});

describe('R3-A -- lifecycle and errors', () => {
    it('does not fetch while the view is hidden', async () => {
        const root = mount();
        root.setAttribute('hidden', '');
        const fetchMock = vi.fn();
        vi.stubGlobal('fetch', fetchMock);
        await V.refresh();
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('reports an HTTP error and an unreachable server', async () => {
        const root = mount();
        vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({}, 503)));
        await V.refresh();
        expect(root.querySelector('.dvc-error').textContent).toContain('HTTP 503');
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('down'); }));
        await V.refresh();
        expect(root.querySelector('.dvc-error').textContent).toContain('unreachable');
    });

    it('registers the route once', () => {
        initDeviceControlView();
        initDeviceControlView();
        expect(isRegistered(V.ROUTE_ID)).toBe(true);
    });
});

describe('R3-A -- S-VISUAL-01 fence + wiring', () => {
    it('every dvc-* class the view emits has a CSS rule', () => {
        const css = readFileSync(resolve(ROOT, 'frontend/assets/app.css'), 'utf8');
        const defined = new Set([...css.matchAll(/\.([A-Za-z_][\w-]*)/g)].map((m) => m[1]));
        const src = readFileSync(resolve(ROOT, 'frontend/assets/js/views/device_control.js'), 'utf8');
        const emitted = new Set();
        for (const m of src.matchAll(/dvc-[a-z][a-z-]*[a-z]/g)) emitted.add(m[0]);
        ['dvc-action', 'dvc-body', 'dvc-countdown', 'dvc-tone', 'dvc-badge-', 'dvc-msg-', 'dvc-ev'].forEach((k) => emitted.delete(k));
        for (const t of ['ok', 'warn', 'crit', 'info']) { emitted.add(`dvc-tone-${t}`); emitted.add(`dvc-badge-${t}`); }
        emitted.add('dvc-ev-refused');
        expect(emitted.size).toBeGreaterThanOrEqual(30);
        expect([...emitted].filter((c) => !defined.has(c)).sort()).toEqual([]);
    });

    it('the shell has the view container, the nav entry and the init call', () => {
        const html = readFileSync(resolve(ROOT, 'frontend/index.html'), 'utf8');
        expect(html).toContain('id="view-device-control"');
        expect(html).toContain('data-route="device-control"');
        const main = readFileSync(resolve(ROOT, 'frontend/assets/js/main.js'), 'utf8');
        expect(main).toContain('initDeviceControlView();');
    });
});
