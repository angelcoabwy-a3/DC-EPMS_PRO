/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/power.test.js
 * ROADMAP V11 T2.1 — verifies the Power SLD view extracted from app.js.
 *
 *   - services/api.js : getTopologyState endpoint.
 *   - views/power.js  : the Kalman-channel -> node-severity mapping,
 *     the topology data-binder, and the Hermes telemetry frame route,
 *     against happy-dom fixtures.
 *
 * No browser, no backend: fetch is stubbed; helpers via __power_test__.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, vi, afterEach } from 'vitest';

import { getTopologyState } from '/assets/js/services/api.js';
import { __power_test__ } from '/assets/js/views/power.js';

const { severityFromChannels, applyTelemetry, applyTopology, onTelemetryFrame } =
    __power_test__;

function fakeResponse(body, { ok = true, status = 200 } = {}) {
    return {
        ok,
        status,
        json: async () => body,
        text: async () => JSON.stringify(body),
    };
}

// ════════════════════════════════════════════════════════════════
//  services/api.js — getTopologyState
// ════════════════════════════════════════════════════════════════
describe('T2.1 — services/api.js getTopologyState()', () => {
    afterEach(() => {
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
    });

    it('resolves to the topology rollup payload', async () => {
        vi.stubGlobal('fetch', vi.fn(async () =>
            fakeResponse({ hld_nodes: {}, redundancy_mode: '2N' })));
        const d = await getTopologyState();
        expect(d.redundancy_mode).toBe('2N');
    });

    it('throws with the HTTP status on a non-2xx response', async () => {
        vi.stubGlobal('fetch', vi.fn(async () =>
            fakeResponse('engine down', { ok: false, status: 503 })));
        await expect(getTopologyState()).rejects.toThrow(/HTTP 503/);
    });
});

// ════════════════════════════════════════════════════════════════
//  views/power.js — _severityFromChannels (pure)
// ════════════════════════════════════════════════════════════════
describe('T2.1 — views/power.js severityFromChannels()', () => {
    it('returns critical when any channel is anomalous', () => {
        expect(severityFromChannels([{ max_z: 0.1 }, { is_anomalous: true }]))
            .toBe('critical');
    });

    it('returns warning when |max_z| >= 2 and nothing is anomalous', () => {
        expect(severityFromChannels([{ max_z: 2.4 }])).toBe('warning');
        expect(severityFromChannels([{ max_z: -3.1 }])).toBe('warning');
    });

    it('returns ok for quiet channels', () => {
        expect(severityFromChannels([{ max_z: 0.8 }, { max_z: 1.2 }])).toBe('ok');
    });

    it('returns ok for an empty channel set', () => {
        expect(severityFromChannels([])).toBe('ok');
    });
});

// ════════════════════════════════════════════════════════════════
//  views/power.js — _applyTelemetry (live Kalman -> DAG nodes)
// ════════════════════════════════════════════════════════════════
describe('T2.1 — views/power.js applyTelemetry()', () => {
    function mountIso() {
        document.body.innerHTML = `
            <div id="view-power">
                <div class="sld-iso-block" data-sld-node="ups_a"></div>
                <div class="sld-iso-block" data-sld-node="ups_b"></div>
                <div class="sld-iso-block" data-sld-node="util_a"></div>
            </div>`;
    }
    afterEach(() => { document.body.innerHTML = ''; });

    it('maps an anomalous Kalman channel onto its node as data-sev=critical', () => {
        mountIso();
        applyTelemetry({
            'ups_a_soc': { is_anomalous: true, max_z: 4.1 },
            'ups_b_soc': { is_anomalous: false, max_z: 0.4 },
        });
        expect(document.querySelector('[data-sld-node="ups_a"]').dataset.sev).toBe('critical');
        expect(document.querySelector('[data-sld-node="ups_b"]').dataset.sev).toBe('ok');
    });

    it('maps an elevated z-score onto its node as data-sev=warning', () => {
        mountIso();
        applyTelemetry({ 'ups_b_soc': { is_anomalous: false, max_z: 2.7 } });
        expect(document.querySelector('[data-sld-node="ups_b"]').dataset.sev).toBe('warning');
    });

    it('leaves nodes with no matching channel untouched', () => {
        mountIso();
        applyTelemetry({ 'ups_a_soc': { is_anomalous: true } });
        expect(document.querySelector('[data-sld-node="util_a"]').dataset.sev).toBeUndefined();
    });

    it('is a safe no-op on an empty / missing payload', () => {
        mountIso();
        expect(() => applyTelemetry(null)).not.toThrow();
        expect(() => applyTelemetry({})).not.toThrow();
    });

    it('onTelemetryFrame routes a Hermes frame channels block through', () => {
        mountIso();
        onTelemetryFrame({ schema: 'channel_innovations', channels: {
            'ups_a_soc': { is_anomalous: true },
        } });
        expect(document.querySelector('[data-sld-node="ups_a"]').dataset.sev).toBe('critical');
    });
});

// ════════════════════════════════════════════════════════════════
//  views/power.js — _applyTopology (physics-validated rollup)
// ════════════════════════════════════════════════════════════════
describe('T2.1 — views/power.js applyTopology()', () => {
    afterEach(() => { document.body.innerHTML = ''; });

    it('binds node metrics and the redundancy banner from the rollup', () => {
        document.body.innerHTML = `
            <div id="view-power">
                <span data-sld-metric="util_a-kw"></span>
                <span data-sld-metric="ups_a-mode"></span>
                <div id="sld-banner-mode"></div>
                <div id="sld-meta"></div>
            </div>`;
        applyTopology({
            hld_nodes: {
                utility_north: { severity: 'ok', metrics: { kw: 1000, kv: 27.5 } },
                ups_a: { severity: 'ok', metrics: { load_kw: 800, eff: 0.96, soc: 1, battery_on_load: false } },
            },
            redundancy_mode: '2N',
            site_health: 0.91,
            power_balance: { ok: true },
        });
        expect(document.querySelector('[data-sld-metric="util_a-kw"]').textContent)
            .toContain('1,000 kW');
        expect(document.querySelector('[data-sld-metric="ups_a-mode"]').textContent)
            .toBe('ONLINE');
        expect(document.getElementById('sld-banner-mode').textContent).toBe('2N');
        expect(document.getElementById('sld-meta').innerHTML).toContain('2N');
    });

    it('is a safe no-op on a null rollup', () => {
        expect(() => applyTopology(null)).not.toThrow();
    });
});

// ════════════════════════════════════════════════════════════════
//  views/power.js — flat SLD generator (orthogonal SCADA)
// ════════════════════════════════════════════════════════════════
describe('T2.1 — views/power.js buildFlatMarkup() orthogonal SLD', () => {
    const { buildFlatMarkup, renderFlatSld } = __power_test__;

    afterEach(() => { document.body.innerHTML = ''; });

    it('emits every 5-layer tier node for both 2N paths', () => {
        const svg = buildFlatMarkup();
        for (const id of [
            'util_a', 'genset_a', 'par_bus_a', 'ats_a', 'ups_a', 'rpp_a1',
            'util_b', 'genset_b', 'ats_b', 'ups_b', 'rpp_b1',
        ]) {
            expect(svg).toContain(`data-sld-node="${id}"`);
        }
        expect(svg).toContain('GENSET / N+1');
        expect(svg).toContain('ATS / STS');
    });

    it('routes every connector strictly orthogonally (no diagonals)', () => {
        const svg = buildFlatMarkup();
        const ds = [...svg.matchAll(/<path class="pf-wire[^"]*" d="([^"]+)"/g)]
            .map((m) => m[1]);
        expect(ds.length).toBeGreaterThan(0);
        for (const d of ds) {
            const pts = d.trim().split(/[ML]\s*/).filter(Boolean)
                .map((p) => p.trim().split(/\s+/).map(Number));
            for (let i = 1; i < pts.length; i += 1) {
                const [x1, y1] = pts[i - 1];
                const [x2, y2] = pts[i];
                // a segment is orthogonal iff it shares an x or a y
                expect(x1 === x2 || y1 === y2).toBe(true);
            }
        }
    });

    it('renderFlatSld injects the SLD into the .pid-svg container', () => {
        document.body.innerHTML = '<div id="view-power"><svg class="pid-svg"></svg></div>';
        renderFlatSld();
        const svg = document.querySelector('#view-power .pid-svg');
        expect(svg.innerHTML).toContain('data-sld-node="ups_a"');
        expect(svg.getAttribute('viewBox')).toBe('0 0 1200 720');
    });

    it('tags ATS + RPP nodes as operable breakers', () => {
        const svg = buildFlatMarkup();
        expect(svg).toMatch(/data-sld-node="ats_a"[^>]*data-breaker="1"/);
        expect(svg).toMatch(/data-sld-node="rpp_a1"[^>]*data-breaker="1"/);
        // utility is NOT a breaker
        expect(svg).not.toMatch(/data-sld-node="util_a"[^>]*data-breaker/);
    });
});

// ════════════════════════════════════════════════════════════════
//  views/power.js — L3 Phase 1: breaker actuation control plane
// ════════════════════════════════════════════════════════════════
describe('L3-1 — views/power.js breaker actuation', () => {
    const { renderFlatSld, openBreakerModal, submitBreakerCommand, onFlatClick, reset } =
        __power_test__;

    afterEach(() => {
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
        document.body.innerHTML = '';
        reset();
    });

    it('openBreakerModal mounts a visible confirmation dialog', () => {
        openBreakerModal('ats_a', 'ATS-A');
        const modal = document.getElementById('pwr-breaker-modal');
        expect(modal).not.toBeNull();
        expect(modal.hidden).toBe(false);
        expect(modal.querySelector('[data-field="target"]').textContent).toBe('ATS-A');
        expect(modal.dataset.nodeId).toBe('ats_a');
    });

    it('a click on a flat breaker node opens the modal (live mode)', () => {
        document.body.innerHTML = '<div id="view-power"><svg class="pid-svg"></svg></div>';
        renderFlatSld();
        const breaker = document.querySelector('.pf-node[data-breaker]');
        expect(breaker).not.toBeNull();
        onFlatClick({ target: breaker.querySelector('.pf-name') || breaker });
        expect(document.getElementById('pwr-breaker-modal').hidden).toBe(false);
    });

    it('a click on a non-breaker node does NOT open the modal', () => {
        document.body.innerHTML = '<div id="view-power"><svg class="pid-svg"></svg></div>';
        renderFlatSld();
        const util = document.querySelector('.pf-node[data-sld-node="util_a"]');
        onFlatClick({ target: util });
        expect(document.getElementById('pwr-breaker-modal')).toBeNull();
    });

    it('submitBreakerCommand POSTs to /api/bms/write with the actor_role claim', async () => {
        const spy = vi.fn(async () => ({
            ok: true, status: 200,
            json: async () => ({ success: true, message: 'breaker.ats_a.cmd <- OPEN' }),
        }));
        vi.stubGlobal('fetch', spy);
        openBreakerModal('ats_a', 'ATS-A');
        await submitBreakerCommand('ats_a', 'OPEN', 'SME_L6');
        expect(spy).toHaveBeenCalledTimes(1);
        const [path, opts] = spy.mock.calls[0];
        expect(path).toBe('/api/bms/write');
        const body = JSON.parse(opts.body);
        expect(body).toMatchObject({ value: 'OPEN', actor_role: 'SME_L6' });
        expect(body.tag_id).toContain('ats_a');
        expect(document.querySelector('.pwr-modal-result').className).toContain('is-ok');
    });

    it('surfaces a 403 RBAC denial in the modal for a sub-SME_L6 role', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: false, status: 403,
            json: async () => ({ detail: 'BMS write requires SME_L6' }),
        })));
        openBreakerModal('rpp_a1', 'RPP-A');
        await submitBreakerCommand('rpp_a1', 'OPEN', 'TECH_L4');
        const result = document.querySelector('.pwr-modal-result');
        expect(result.className).toContain('is-denied');
        expect(result.textContent).toContain('RBAC DENIED');
    });
});
