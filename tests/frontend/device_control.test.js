/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO -- tests/frontend/device_control.test.js
 * Release R3-A / R3-B -- views/device_control.js
 *   - Path tabs, capacity summary with N and N+1 as text.
 *   - Cards: state, indications, readings, refused commands.
 *   - Select-before-operate.
 *   - MV procedure: only the next step is actionable, witness form,
 *     password never kept.
 *   - Scenario library and run report.
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

function gen(overrides = {}) {
    return Object.assign({
        id: 'gen_a_01', kind: 'generator', display: 'Generator A1', path: 'a',
        vendor: '', model: '', authority: 'REMOTE', state: 'STANDBY',
        status: { tone: 'ok', text: 'Ready to start' },
        readings: [
            { label: 'Engine speed', value: 0, unit: 'rpm' },
            { label: 'Output voltage', value: 13.8, unit: 'kV' },
        ],
        indications: [
            { label: '52-G breaker', value: 'OPEN' }, { label: 'Disconnector', value: 'CLOSED' },
            { label: 'Earthing switch', value: 'OPEN' }, { label: 'LOTO', value: 'CLEAR' },
        ],
        commands: [
            { command: 'START', label: 'Start engine', description: 'Cranks.', permitted: true, blocked_reason: null },
            { command: 'STOP', label: 'Stop engine', description: 'Stops.', permitted: false, blocked_reason: 'Engine is not running.' },
        ],
        switching: { procedure: null, goals: [
            { goal: 'ISOLATE_FOR_MAINTENANCE', label: 'Isolate for maintenance', permitted: true, blocked_reason: null },
            { goal: 'RETURN_TO_SERVICE', label: 'Return to service', permitted: false, blocked_reason: 'Bay is already in service.' },
        ] },
    }, overrides);
}

function procedure(nextIndex, extra = {}) {
    const ops = [
        ['OPEN_CB', 'Open circuit breaker 52-G', false, false],
        ['OPEN_DS', 'Open disconnector', false, false],
        ['VERIFY_ABSENCE_OF_VOLTAGE', 'Verify absence of voltage', true, false],
        ['CLOSE_ES', 'Close earthing switch', true, true],
        ['APPLY_LOTO', 'Apply lockout / tagout', true, true],
    ];
    return Object.assign({
        procedure_id: 'p1', bay_id: 'gen_a_01', goal: 'ISOLATE_FOR_MAINTENANCE',
        goal_label: 'Isolate for maintenance', operator: 'manager', complete: false, blocked_attempts: 0,
        steps: ops.map(([operation, label, safety_gate, two_person], i) => ({
            step: i + 1, operation, label, safety_gate, two_person,
            status: i < nextIndex ? 'done' : (i === nextIndex ? 'next' : 'locked'),
            witness: null, witness_valid: two_person ? false : null,
        })),
    }, extra);
}

function summary(path = 'a', overrides = {}) {
    return Object.assign({
        path, source: 'UTILITY', it_load_kw: 8380, it_design_kw: 16760,
        ups_in_service: 8, ups_total: 8, ups_capacity_kw: 20000, ups_n_ok: true, ups_n_plus_1_ok: true,
        ups_losses_kw: 259, ups_protected: true, demand_kw: 10734, design_demand_kw: 21468,
        gen_available: 9, gen_total: 9, gen_available_kw: 22500, gen_on_bus_kw: 0,
        gen_n_ok: true, gen_n_plus_1_ok: false,
    }, overrides);
}

function payload(devices, events = []) {
    return {
        notice: 'SIMULATED plant. No field equipment is connected.',
        paths: [summary('a'), summary('b')], devices, events, select_ttl_s: 30,
    };
}

const LIB = {
    sandbox_notice: 'Runs execute in a sandbox copy of the plant model.',
    scenarios: [{ scenario_id: 'MV-SW-001', version: '1.0.0', title: 'Safe isolation', category: 'MediumVoltage_Switching',
        description: 'Forced sequence.', safety_critical: true, steps: 2, criteria: 3 }],
};

function mount() {
    document.body.innerHTML = '<div class="view" id="view-device-control"></div>';
    return document.getElementById('view-device-control');
}

function jsonResponse(body, status = 200) {
    return { ok: status >= 200 && status < 300, status, json: async () => body };
}

async function flush() {
    for (let i = 0; i < 10; i += 1) await Promise.resolve();
}

function wire(handlers, base) {
    const calls = [];
    vi.stubGlobal('fetch', vi.fn(async (url, opts = {}) => {
        calls.push({ url, method: opts.method || 'GET', body: opts.body ? JSON.parse(opts.body) : null });
        const h = handlers[`${opts.method || 'GET'} ${url}`];
        if (h) return h();
        if (url === '/api/power-scenarios') return jsonResponse(LIB);
        return jsonResponse(base || payload([gen()]));
    }));
    return calls;
}

afterEach(() => {
    V.reset();
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
});

describe('R3-B -- path tabs and capacity summary', () => {
    it('prints the simulation notice and the control rules', () => {
        const root = mount();
        root.innerHTML = V.renderPanels(payload([gen()]));
        expect(root.querySelector('.dvc-notice').textContent).toContain('SIMULATED plant');
        const rules = root.querySelector('.dvc-rules').textContent;
        expect(rules).toContain('FACILITY MANAGER');
        expect(rules).toContain('second person');
        expect(rules).toContain('Forensic Ledger');
    });

    it('shows one path at a time and switches on click', async () => {
        const root = mount();
        wire({}, payload([gen(), gen({ id: 'gen_b_01', display: 'Generator B1', path: 'b' })]));
        await V.refresh();
        expect([...root.querySelectorAll('.dvc-card-title')].map((e) => e.textContent)).toEqual(['Generator A1']);
        root.querySelector('[data-path="b"]').click();
        expect([...root.querySelectorAll('.dvc-card-title')].map((e) => e.textContent)).toEqual(['Generator B1']);
        expect(root.querySelector('[data-path="b"]').getAttribute('aria-pressed')).toBe('true');
    });

    it('states N and N+1 as text, never by colour alone', () => {
        const root = mount();
        root.innerHTML = V.renderSummary(summary());
        const checks = [...root.querySelectorAll('.dvc-check')].map((e) => e.textContent);
        expect(checks).toEqual(['N: MET', 'N+1: MET', 'N: MET', 'N+1: NOT MET']);
        expect(root.textContent).toContain('20.00 MW');
        expect(root.textContent).toContain('259 kW');
        expect(root.textContent).toContain('full-path demand 21.47 MW');
    });

    it('flags a block on static bypass and a path on generators', () => {
        const root = mount();
        root.innerHTML = V.renderSummary(summary('a', { ups_protected: false, source: 'GENERATORS' }));
        expect(root.textContent).toContain('At least one block on static bypass');
        expect(root.querySelector('.dvc-tile-warn').textContent).toBe('GENERATORS');
    });

    it('orders sections transfer, UPS, generators', () => {
        const root = mount();
        root.innerHTML = V.renderPanels(payload([
            gen(), gen({ id: 'ups_a_01', kind: 'ups', display: 'UPS A1', switching: undefined, indications: [] }),
            gen({ id: 'mvtc_a', kind: 'transfer', display: 'MV transfer controller A', switching: undefined }),
        ]));
        const kinds = [...root.querySelectorAll('.dvc-section[data-kind]')].map((s) => s.getAttribute('data-kind'));
        expect(kinds).toEqual(['transfer', 'ups', 'generator']);
        expect(root.querySelector('[data-kind="ups"] .dvc-sw')).toBeNull();
    });
});

describe('R3-B -- device card', () => {
    it('shows state, indications and readings with units', () => {
        const root = mount();
        root.innerHTML = V.renderDevice(gen());
        expect(root.querySelector('.dvc-badge').textContent).toBe('STANDBY');
        const inds = [...root.querySelectorAll('.dvc-ind')].map((e) => e.textContent.replace(/\s+/g, ' ').trim());
        expect(inds).toEqual(['52-G breaker OPEN', 'Disconnector CLOSED', 'Earthing switch OPEN', 'LOTO CLEAR']);
        const readings = [...root.querySelectorAll('.dvc-reading')].map((r) => r.textContent.replace(/\s+/g, ' ').trim());
        expect(readings).toEqual(['Engine speed 0 rpm', 'Output voltage 13.8 kV']);
    });

    it('disables refused commands and goals and prints the reasons', () => {
        const root = mount();
        root.innerHTML = V.renderDevice(gen());
        const [start, stop] = root.querySelectorAll('[data-dvc-action="select"]');
        expect([start.disabled, stop.disabled]).toEqual([false, true]);
        const [iso, back] = root.querySelectorAll('[data-dvc-action="procedure"]');
        expect([iso.disabled, back.disabled]).toEqual([false, true]);
        const reasons = [...root.querySelectorAll('.dvc-blocked li')].map((li) => li.textContent);
        expect(reasons).toEqual(['Engine is not running.', 'Bay is already in service.']);
    });

    it('ties each reason to its command when the reasons differ', () => {
        const root = mount();
        root.innerHTML = V.renderDevice(gen({ switching: undefined, commands: [
            { command: 'START', label: 'Start engine', permitted: false, blocked_reason: 'Bay is under LOTO.' },
            { command: 'STOP', label: 'Stop engine', permitted: false, blocked_reason: 'Engine is not running.' },
        ] }));
        expect([...root.querySelectorAll('.dvc-blocked li')].map((li) => li.textContent)).toEqual([
            'Start engine: Bay is under LOTO.', 'Stop engine: Engine is not running.',
        ]);
    });

    it('marks the active authority', () => {
        const root = mount();
        root.innerHTML = V.renderDevice(gen({ authority: 'LOCAL' }));
        const buttons = [...root.querySelectorAll('.dvc-auth-btn')];
        expect(buttons.map((b) => b.getAttribute('aria-pressed'))).toEqual(['false', 'false', 'true']);
        expect(root.querySelector('.dvc-auth-hint').textContent).toContain('bench simulation');
    });

    it('escapes every server-supplied string (S-SEC-01)', () => {
        const root = mount();
        const hostileProc = procedure(3, { procedure_id: 'p1', goal_label: HOSTILE, operator: HOSTILE });
        hostileProc.steps.forEach((s) => { s.label = HOSTILE; s.witness = HOSTILE; s.status = s.status === 'next' ? 'next' : HOSTILE; });
        V.setLibrary({ sandbox_notice: HOSTILE, scenarios: [{ scenario_id: HOSTILE, title: HOSTILE, description: HOSTILE, category: HOSTILE }] });
        const p = payload([gen({
            display: HOSTILE, vendor: HOSTILE, model: HOSTILE, state: HOSTILE,
            status: { tone: HOSTILE, text: HOSTILE },
            readings: [{ label: HOSTILE, value: 1, unit: HOSTILE }],
            indications: [{ label: HOSTILE, value: HOSTILE }],
            commands: [{ command: HOSTILE, label: HOSTILE, description: HOSTILE, permitted: false, blocked_reason: HOSTILE }],
            switching: { procedure: hostileProc, goals: [] },
        })], [{ ts: 1, event: HOSTILE, device_id: HOSTILE, actor: HOSTILE, detail: HOSTILE }]);
        p.notice = HOSTILE;
        root.innerHTML = V.renderPanels(p) + V.renderRun({
            scenario_id: HOSTILE, version: HOSTILE, title: HOSTILE, passed: false, ledger_entry_id: HOSTILE,
            steps: [{ step: HOSTILE, action: HOSTILE, what: HOSTILE, target: HOSTILE, expected: HOSTILE, outcome: HOSTILE, detail: HOSTILE }],
            criteria: [{ criterion: { check: HOSTILE }, actual: HOSTILE, passed: false }],
        });
        expect(root.querySelector('img')).toBeNull();
        expect(root.querySelectorAll('[onerror]').length).toBe(0);
        expect(root.querySelector('.dvc-card-title').textContent).toBe(HOSTILE);
    });
});

describe('R3-A -- select before operate', () => {
    it('select shows the confirmation and sends no operate', async () => {
        const root = mount();
        const calls = wire({
            'POST /api/devices/gen_a_01/select': () => jsonResponse({
                select_token: 'tok-1', command: 'START', label: 'Start engine', description: 'Cranks.', expires_in_s: 30,
            }),
        });
        await V.refresh();
        root.querySelector('[data-command="START"]').click();
        await flush();
        expect(root.querySelector('.dvc-confirm-title').textContent).toContain('Start engine');
        expect(root.querySelector('[data-dvc-countdown]').textContent).toBe('30');
        expect(calls.some((c) => c.url.endsWith('/operate'))).toBe(false);
    });

    it('operate sends the token and reports the ledger entry', async () => {
        const root = mount();
        const calls = wire({
            'POST /api/devices/gen_a_01/select': () => jsonResponse({ select_token: 'tok-1', command: 'START', label: 'Start engine', expires_in_s: 30 }),
            'POST /api/devices/gen_a_01/operate': () => jsonResponse({ success: true, ledger_entry_id: 'abcdef12-3456' }),
        });
        await V.refresh();
        root.querySelector('[data-command="START"]').click();
        await flush();
        root.querySelector('[data-dvc-action="operate"]').click();
        await flush();
        expect(calls.find((c) => c.url.endsWith('/operate')).body.select_token).toBe('tok-1');
        expect(root.querySelector('.dvc-msg-ok').textContent).toContain('Ledger entry abcdef12');
    });

    it('says so when the action was not chained', async () => {
        const root = mount();
        wire({
            'POST /api/devices/gen_a_01/select': () => jsonResponse({ select_token: 't', command: 'START', expires_in_s: 30 }),
            'POST /api/devices/gen_a_01/operate': () => jsonResponse({ success: true, ledger_entry_id: null }),
        });
        await V.refresh();
        root.querySelector('[data-command="START"]').click();
        await flush();
        root.querySelector('[data-dvc-action="operate"]').click();
        await flush();
        expect(root.querySelector('.dvc-msg').textContent).toContain('action NOT chained');
    });

    it('an expired selection disappears on the tick', async () => {
        const root = mount();
        let now = 1_000_000;
        V.setNow(() => now);
        wire({ 'POST /api/devices/gen_a_01/select': () => jsonResponse({ select_token: 't', command: 'START', expires_in_s: 30 }) });
        await V.refresh();
        root.querySelector('[data-command="START"]').click();
        await flush();
        now += 12_000;
        V.tick();
        expect(root.querySelector('[data-dvc-countdown]').textContent).toBe('18');
        now += 20_000;
        V.tick();
        expect(V.pending.size).toBe(0);
        expect(root.querySelector('.dvc-msg-crit').textContent).toContain('Selection expired');
    });

    it('shows the server reason on a refusal', async () => {
        const root = mount();
        wire({ 'POST /api/devices/gen_a_01/select': () => jsonResponse({ detail: 'this action requires FACILITY_MANAGER; role L1_OPERATOR is insufficient.' }, 403) });
        await V.refresh();
        root.querySelector('[data-command="START"]').click();
        await flush();
        expect(root.querySelector('.dvc-msg-crit').textContent).toContain('requires FACILITY_MANAGER');
    });
});

describe('R3-B -- medium-voltage switching procedure', () => {
    it('starting a procedure posts the goal', async () => {
        const root = mount();
        const calls = wire({ 'POST /api/mv/bays/gen_a_01/procedure': () => jsonResponse({ success: true, procedure: procedure(0) }) });
        await V.refresh();
        root.querySelector('[data-goal="ISOLATE_FOR_MAINTENANCE"]').click();
        await flush();
        expect(calls.find((c) => c.url.endsWith('/procedure')).body.goal).toBe('ISOLATE_FOR_MAINTENANCE');
        expect(root.querySelector('.dvc-msg-ok').textContent).toContain('Nothing has moved yet');
    });

    it('only the next step has a button', () => {
        const root = mount();
        root.innerHTML = V.renderDevice(gen({ switching: { procedure: procedure(1), goals: [] } }));
        const statuses = [...root.querySelectorAll('.dvc-step-status')].map((e) => e.textContent);
        expect(statuses).toEqual(['DONE', 'NEXT', 'LOCKED', 'LOCKED', 'LOCKED']);
        const buttons = [...root.querySelectorAll('[data-dvc-action="step"]')];
        expect(buttons.map((b) => b.getAttribute('data-step'))).toEqual(['2']);
        expect(root.querySelector('[data-dvc-action="procedure"]')).toBeNull();
        expect(root.querySelectorAll('.dvc-tag-gate').length).toBe(3);
        expect(root.querySelectorAll('.dvc-tag-two').length).toBe(2);
    });

    it('a two-person step shows the witness form instead of the execute button', () => {
        const root = mount();
        root.innerHTML = V.renderDevice(gen({ switching: { procedure: procedure(3), goals: [] } }));
        expect(root.querySelector('[data-dvc-action="step"]')).toBeNull();
        expect(root.querySelector('.dvc-witness-title').textContent).toContain('second person');
        expect(root.querySelector('[data-dvc-witness-pass]').getAttribute('type')).toBe('password');
        expect(root.querySelector('[data-dvc-witness-pass]').getAttribute('autocomplete')).toBe('off');
    });

    it('once witnessed, the execute button returns', () => {
        const root = mount();
        const proc = procedure(3);
        proc.steps[3].witness = 'safety_a';
        proc.steps[3].witness_valid = true;
        root.innerHTML = V.renderDevice(gen({ switching: { procedure: proc, goals: [] } }));
        expect(root.querySelector('[data-dvc-action="step"]').getAttribute('data-step')).toBe('4');
        expect(root.querySelector('.dvc-witness')).toBeNull();
        expect(root.textContent).toContain('witness safety_a');
    });

    it('witness approval sends the credentials once and clears the field', async () => {
        const root = mount();
        const base = payload([gen({ switching: { procedure: procedure(3), goals: [] } })]);
        const calls = wire({ 'POST /api/mv/procedures/p1/witness': () => jsonResponse({ success: true }) }, base);
        await V.refresh();
        root.querySelector('[data-dvc-witness-user]').value = 'safety_a';
        const pass = root.querySelector('[data-dvc-witness-pass]');
        pass.value = 'secret';
        root.querySelector('[data-dvc-action="witness"]').click();
        expect(pass.value).toBe('');
        await flush();
        const call = calls.find((c) => c.url.endsWith('/witness'));
        expect(call.body).toMatchObject({ step: 4, witness_username: 'safety_a', witness_password: 'secret' });
        expect(root.querySelector('.dvc-msg-ok').textContent).toContain('approved by safety_a');
        expect(root.innerHTML).not.toContain('secret');
    });

    it('an empty witness form is refused locally', async () => {
        const root = mount();
        const base = payload([gen({ switching: { procedure: procedure(3), goals: [] } })]);
        const calls = wire({}, base);
        await V.refresh();
        root.querySelector('[data-dvc-action="witness"]').click();
        await flush();
        expect(calls.some((c) => c.url.endsWith('/witness'))).toBe(false);
        expect(root.querySelector('.dvc-msg-crit').textContent).toContain('own username and password');
    });

    it('executing a step posts its number and shows a block from the server', async () => {
        const root = mount();
        const base = payload([gen({ switching: { procedure: procedure(1, { blocked_attempts: 2 }), goals: [] } })]);
        const calls = wire({ 'POST /api/mv/procedures/p1/step': () => jsonResponse({ detail: 'R4: breaker is closed.' }, 409) }, base);
        await V.refresh();
        expect(root.querySelector('.dvc-deviation').textContent).toContain('2 blocked attempt(s)');
        root.querySelector('[data-dvc-action="step"]').click();
        await flush();
        expect(calls.find((c) => c.url.endsWith('/step')).body.step).toBe(2);
        expect(root.querySelector('.dvc-msg-crit').textContent).toContain('R4: breaker is closed.');
    });

    it('abort warns that positions are not rolled back', async () => {
        const root = mount();
        const base = payload([gen({ switching: { procedure: procedure(2), goals: [] } })]);
        wire({ 'POST /api/mv/procedures/p1/abort': () => jsonResponse({ success: true }) }, base);
        await V.refresh();
        root.querySelector('[data-dvc-action="abort"]').click();
        await flush();
        expect(root.querySelector('.dvc-msg-ok').textContent).toContain('NOT rolled back');
    });

    it('a poll does not wipe a witness form while someone types', async () => {
        const root = mount();
        const base = payload([gen({ switching: { procedure: procedure(3), goals: [] } })]);
        wire({}, base);
        await V.refresh();
        const user = root.querySelector('[data-dvc-witness-user]');
        user.value = 'safety';
        user.focus();
        await V.refresh();
        expect(root.querySelector('[data-dvc-witness-user]').value).toBe('safety');
    });
});

describe('R3-B -- control log', () => {
    it('describes every event kind', () => {
        expect(V.eventDetail({ event: 'command', command: 'START', from_state: 'STANDBY', to_state: 'CRANKING' })).toBe('START: STANDBY to CRANKING');
        expect(V.eventDetail({ event: 'authority', previous: 'AUTO', authority: 'LOCAL', source: 'bench_simulation' })).toBe('AUTO to LOCAL (bench simulation)');
        expect(V.eventDetail({ event: 'procedure_step', step: 4, label: 'Close earthing switch', witness: 'safety_a', complete: false }))
            .toBe('step 4: Close earthing switch, witness safety_a');
        expect(V.eventDetail({ event: 'procedure_blocked', step: 3, detail: 'sequence deviation' })).toBe('step 3 BLOCKED: sequence deviation');
        expect(V.eventDetail({ event: 'procedure_witness', step: 4 })).toBe('second person approved step 4');
        expect(V.eventDetail({ event: 'refused', command: 'STOP', detail: 'Engine is not running.' })).toBe('STOP: Engine is not running.');
    });

    it('marks blocked rows and prints an empty state', () => {
        const root = mount();
        root.innerHTML = V.renderEvents([{ ts: 1, event: 'procedure_blocked', step: 1, detail: 'x' }, { ts: 2, event: 'command' }]);
        expect(root.querySelectorAll('.dvc-ev-refused').length).toBe(1);
        root.innerHTML = V.renderEvents([]);
        expect(root.textContent).toContain('No control actions since boot.');
    });
});

describe('R3-B -- scenario library', () => {
    it('lists scenarios and runs one in the sandbox', async () => {
        const root = mount();
        const calls = wire({
            'POST /api/power-scenarios/MV-SW-001/run': () => jsonResponse({
                scenario_id: 'MV-SW-001', version: '1.0.0', title: 'Safe isolation', passed: true,
                blocked_events: 0, simulated_seconds: 0, ledger_entry_id: '12345678-aaaa',
                steps: [{ step: 1, action: 'authority', what: 'REMOTE', target: 'gen_a_03', expected: 'ok', outcome: 'ok', detail: '', as_expected: true }],
                criteria: [{ criterion: { check: 'bay', target: 'gen_a_03' }, actual: { loto: true }, passed: true }],
            }),
        });
        await V.refresh();
        expect(root.querySelector('[data-section="library"]').textContent).toContain('sandbox copy');
        root.querySelector('[data-dvc-action="run"]').click();
        await flush();
        expect(calls.some((c) => c.url === '/api/power-scenarios/MV-SW-001/run' && c.method === 'POST')).toBe(true);
        const run = root.querySelector('.dvc-run');
        expect(run.querySelector('.dvc-badge').textContent).toBe('PASS');
        expect(run.textContent).toContain('ledger entry 12345678');
        expect(run.querySelector('.dvc-crit-ok').textContent).toContain('MET');
    });

    it('reports FAIL with the unexpected step and the unmet criterion', () => {
        const root = mount();
        root.innerHTML = V.renderRun({
            scenario_id: 'X', version: '1', title: 't', passed: false, blocked_events: 1,
            steps: [{ step: 2, action: 'command', what: 'ISOLATE', target: 'ups_a_02', expected: 'blocked', outcome: 'ok', detail: '', as_expected: false }],
            criteria: [{ criterion: { check: 'path' }, actual: 5, passed: false }],
        });
        expect(root.querySelector('.dvc-badge').textContent).toBe('FAIL');
        expect(root.textContent).toContain('UNEXPECTED');
        expect(root.querySelector('.dvc-crit-bad').textContent).toContain('NOT MET');
        expect(root.textContent).toContain('not chained');
    });

    it('a failed request is shown as a failed run', async () => {
        const root = mount();
        wire({ 'POST /api/power-scenarios/MV-SW-001/run': () => jsonResponse({ detail: 'power plant design not loaded' }, 503) });
        await V.refresh();
        root.querySelector('[data-dvc-action="run"]').click();
        await flush();
        expect(root.querySelector('.dvc-run').textContent).toContain('Run failed: power plant design not loaded');
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

describe('R3-B -- S-VISUAL-01 fence + wiring', () => {
    it('every dvc-* class the view emits has a CSS rule', () => {
        const css = readFileSync(resolve(ROOT, 'frontend/assets/app.css'), 'utf8');
        const defined = new Set([...css.matchAll(/\.([A-Za-z_][\w-]*)/g)].map((m) => m[1]));
        const src = readFileSync(resolve(ROOT, 'frontend/assets/js/views/device_control.js'), 'utf8');
        const emitted = new Set();
        for (const m of src.matchAll(/dvc-[a-z][a-z-]*[a-z]/g)) emitted.add(m[0]);
        // data-attribute names and dynamic prefixes, expanded below
        ['dvc-action', 'dvc-body', 'dvc-countdown', 'dvc-witness-user', 'dvc-witness-pass',
            'dvc-tone', 'dvc-badge-', 'dvc-msg-', 'dvc-ev', 'dvc-check', 'dvc-tile', 'dvc-ind', 'dvc-step', 'dvc-crit']
            .forEach((k) => emitted.delete(k));
        for (const t of ['ok', 'warn', 'crit', 'info']) { emitted.add(`dvc-tone-${t}`); emitted.add(`dvc-badge-${t}`); }
        ['dvc-ev-refused', 'dvc-ev-normal', 'dvc-check', 'dvc-check-ok', 'dvc-check-bad', 'dvc-tile', 'dvc-tile-ok', 'dvc-tile-warn',
            'dvc-ind', 'dvc-ind-open', 'dvc-ind-closed', 'dvc-ind-applied', 'dvc-ind-clear',
            'dvc-step', 'dvc-step-done', 'dvc-step-next', 'dvc-step-locked', 'dvc-crit-ok', 'dvc-crit-bad',
            'dvc-msg-ok', 'dvc-msg-crit'].forEach((c) => emitted.add(c));
        expect(emitted.size).toBeGreaterThanOrEqual(70);
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
