/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/cooling.test.js
 * ROADMAP V11 T2.1 Phase 2a — verifies the extracted Cooling view.
 *
 * Behaviour-preserving extraction smoke test: the P&ID data binder
 * stamps node severity + metric text + the redundancy banner onto a
 * happy-dom #view-cooling fixture. No browser, no backend.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, vi, afterEach } from 'vitest';

import { __cooling_test__ } from '/assets/js/views/cooling.js';

const { applyCoolingPid } = __cooling_test__;

describe('T2.1 Phase 2a — views/cooling.js applyCoolingPid()', () => {
    afterEach(() => { document.body.innerHTML = ''; });

    it('stamps node severity, metric text and the redundancy banner', () => {
        document.body.innerHTML = `
            <div id="view-cooling">
                <div class="pid-node" data-node="chiller_1">
                    <div class="pid-symbol"></div>
                </div>
                <span data-pid-metric="ch1-cop"></span>
                <div id="pid-banner-mode"></div>
                <div id="pid-banner-sub"></div>
                <div id="pid-meta"></div>
            </div>`;
        applyCoolingPid({
            hld_nodes: {
                chiller_1: { severity: 'warning', metrics: { cop: 4.2 } },
            },
            redundancy_mode: '2N',
            site_health: 0.91,
            weakest_module: 'heat_rejection',
        });
        expect(document.querySelector('.pid-node[data-node="chiller_1"] .pid-symbol')
            .getAttribute('data-sev')).toBe('warning');
        expect(document.querySelector('[data-pid-metric="ch1-cop"]').textContent)
            .toBe('COP 4.2');
        expect(document.getElementById('pid-banner-mode').textContent).toBe('2N');
        expect(document.getElementById('pid-meta').innerHTML).toContain('heat_rejection');
    });

    it('surfaces the N (non-redundant) mode in the failover banner', () => {
        document.body.innerHTML = `
            <div id="view-cooling">
                <div id="pid-banner-mode"></div>
                <div id="pid-banner-sub"></div>
            </div>`;
        applyCoolingPid({ hld_nodes: {}, redundancy_mode: 'N', site_health: 0.4 });
        expect(document.getElementById('pid-banner-mode').textContent).toBe('N');
        expect(document.getElementById('pid-banner-sub').textContent)
            .toContain('NON-REDUNDANT');
    });

    it('is a safe no-op on a null rollup', () => {
        expect(() => applyCoolingPid(null)).not.toThrow();
    });
});

// ════════════════════════════════════════════════════════════════
//  views/cooling.js — Phase 2b: orthogonal thermodynamic SCADA SLD
// ════════════════════════════════════════════════════════════════
describe('T2.1 Phase 2b — views/cooling.js buildCoolingSld()', () => {
    const { buildCoolingSld, renderCoolingSld } = __cooling_test__;

    afterEach(() => { document.body.innerHTML = ''; });

    it('emits the cooling equipment chain with data-binder hooks intact', () => {
        const svg = buildCoolingSld();
        for (const id of [
            'cooling_tower', 'chiller_1', 'chiller_2', 'chwp_1', 'chwp_2',
            'cdu_a', 'cdu_b', 'data_hall', 'crah_1', 'crah_2',
        ]) {
            expect(svg).toContain(`data-node="${id}"`);
        }
        // _applyCoolingPid binds severity on .pid-symbol + text on data-pid-metric
        expect(svg).toContain('class="pid-symbol cool-sym"');
        expect(svg).toContain('data-pid-metric="ch1-cop"');
    });

    it('routes every pipe strictly orthogonally and tags supply vs return', () => {
        const svg = buildCoolingSld();
        const pipes = [...svg.matchAll(/<path class="cool-pipe[^"]*" d="([^"]+)"/g)]
            .map((m) => m[1]);
        expect(pipes.length).toBeGreaterThan(0);
        for (const d of pipes) {
            const pts = d.trim().split(/[ML]\s*/).filter(Boolean)
                .map((p) => p.trim().split(/\s+/).map(Number));
            for (let i = 1; i < pts.length; i += 1) {
                const [x1, y1] = pts[i - 1];
                const [x2, y2] = pts[i];
                expect(x1 === x2 || y1 === y2).toBe(true);
            }
        }
        expect(svg).toContain('cool-pipe cool-supply');
        expect(svg).toContain('cool-pipe cool-return');
    });

    it('renderCoolingSld injects the SLD into the .pid-svg container', () => {
        document.body.innerHTML =
            '<div id="view-cooling"><svg class="pid-svg"></svg></div>';
        renderCoolingSld();
        const svg = document.querySelector('#view-cooling .pid-svg');
        expect(svg.innerHTML).toContain('data-node="chiller_1"');
        // Batch 2: canvas grew to host the shared kit legend.
        expect(svg.getAttribute('viewBox')).toBe('0 0 1040 740');
    });

    it('mounts the shared kit legend (one visual language)', () => {
        const svg = buildCoolingSld();
        expect(svg).toContain('dk-legend');
        expect(svg).toContain('800 VDC unipolar TN-S');
    });
});

// ════════════════════════════════════════════════════════════════
//  views/cooling.js — Phase 2c: L3 control plane
// ════════════════════════════════════════════════════════════════
describe('T2.1 Phase 2c — views/cooling.js L3 control plane', () => {
    const { buildCoolingSld, renderCoolingSld, bmsTagFor, openPumpModal,
        submitPumpCommand, onCoolClick, setMode, getMode, updateSparklines,
        reset } = __cooling_test__;

    function mountView() {
        document.body.innerHTML =
            '<div id="view-cooling"><div class="pid-action-bar"></div>'
            + '<svg class="pid-svg"></svg></div>';
    }
    afterEach(() => {
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
        document.body.innerHTML = '';
        reset();
    });

    it('tags CHW pumps as actuators and maps them to the BMS registry', () => {
        const svg = buildCoolingSld();
        expect(svg).toMatch(/data-node="chwp_1"[^>]*data-actuator="1"/);
        expect(bmsTagFor('chwp_1')).toBe('HVAC.CHWP1.STATUS');
        expect(bmsTagFor('chwp_2')).toBe('HVAC.CHWP2.STATUS');
    });

    it('a live-mode click on a pump opens the actuation modal', () => {
        mountView();
        renderCoolingSld();
        const pump = document.querySelector('.cool-node[data-actuator]');
        expect(pump).not.toBeNull();
        onCoolClick({ target: pump.querySelector('.cool-name') || pump });
        expect(document.getElementById('cool-pump-modal').hidden).toBe(false);
    });

    it('submitPumpCommand POSTs to /api/bms/write with the actor_role claim', async () => {
        const spy = vi.fn(async () => ({
            ok: true, status: 200, json: async () => ({ message: 'CHWP1 <- On' }),
        }));
        vi.stubGlobal('fetch', spy);
        openPumpModal('chwp_1', 'CHW PUMP A');
        await submitPumpCommand('chwp_1', 'START', 'SME_L6');
        const [path, opts] = spy.mock.calls[0];
        expect(path).toBe('/api/bms/write');
        expect(JSON.parse(opts.body)).toMatchObject({
            tag_id: 'HVAC.CHWP1.STATUS', value: 'On', actor_role: 'SME_L6',
        });
        expect(document.querySelector('.pwr-modal-result').className).toContain('is-ok');
    });

    it('surfaces a 403 RBAC denial for a sub-SME_L6 role', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: false, status: 403, json: async () => ({ detail: 'requires SME_L6' }),
        })));
        openPumpModal('chwp_2', 'CHW PUMP B');
        await submitPumpCommand('chwp_2', 'STOP', 'TECH_L4');
        expect(document.querySelector('.pwr-modal-result').className).toContain('is-denied');
    });

    it('What-If mode marks a sandbox and a node-click trips the DAG node', () => {
        mountView();
        renderCoolingSld();
        setMode('whatif');
        expect(getMode()).toBe('whatif');
        expect(document.getElementById('view-cooling').classList.contains('cool-whatif'))
            .toBe(true);
        const node = document.querySelector('.cool-node[data-node="chiller_1"]');
        onCoolClick({ target: node });
        expect(node.querySelector('.pid-symbol').getAttribute('data-sev'))
            .toBe('critical');
    });

    it('What-If is a real cascade: tripping one chiller degrades its N+1 peer', () => {
        mountView();
        renderCoolingSld();
        setMode('whatif');
        const ch1 = document.querySelector('.cool-node[data-node="chiller_1"]');
        onCoolClick({ target: ch1 });
        // The surviving peer reports consumed redundancy…
        const ch2sym = document.querySelector(
            '.cool-node[data-node="chiller_2"] .pid-symbol');
        expect(ch2sym.getAttribute('data-sev')).toBe('warning');
        // …while the load is still served (N+1 did its job).
        const hallSym = document.querySelector(
            '.cool-node[data-node="data_hall"] .pid-symbol');
        expect(hallSym.getAttribute('data-sev')).toBe('ok');
    });

    it('What-If cascade reaches the hall when BOTH chillers are tripped', () => {
        mountView();
        renderCoolingSld();
        setMode('whatif');
        onCoolClick({ target: document.querySelector('.cool-node[data-node="chiller_1"]') });
        onCoolClick({ target: document.querySelector('.cool-node[data-node="chiller_2"]') });
        const hallSym = document.querySelector(
            '.cool-node[data-node="data_hall"] .pid-symbol');
        expect(hallSym.getAttribute('data-sev')).toBe('critical');
        // Returning to LIVE clears the simulated trips.
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: true, status: 200, json: async () => ({ hld_nodes: {} }),
        })));
        setMode('live');
        expect(hallSym.getAttribute('data-sev')).toBe('ok');
    });

    it('updateSparklines accumulates Kalman ticks onto the cooling sparklines', () => {
        mountView();
        renderCoolingSld();
        updateSparklines({ cooling_tower_wb: { mean_z: 1.0 }, gpu_Tj: { mean_z: 0.3 } });
        updateSparklines({ cooling_tower_wb: { mean_z: 2.2 }, gpu_Tj: { mean_z: 0.4 } });
        const poly = document.querySelector('[data-spark="cooling_tower"]');
        expect(poly).not.toBeNull();
        expect(poly.getAttribute('points').trim().split(' ')).toHaveLength(2);
    });
});
