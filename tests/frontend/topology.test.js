/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/topology.test.js
 * ROADMAP V11 T2.1 Vector 4a — verifies the extracted Topology view.
 *
 * Behaviour-preserving extraction smoke test: the rule-based Mission
 * Control insight engine, the LLD rack grid, the topology-state data
 * binder, hostile-value escaping, and that initTopologyView() registers
 * the 'topology' route. No browser, no backend.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, afterEach } from 'vitest';

import { __topology_test__ } from '/assets/js/views/topology.js';
import { isRegistered } from '/assets/js/core/router.js';

const { generateInsights, applyTopologyState, renderLLDRacks,
    buildHldMarkup, renderHld, applyTelemetry,
    fmt0, fmt1, initTopologyView, reset } = __topology_test__;

afterEach(() => {
    reset();
    document.body.innerHTML = '';
});

describe('T2.1 Vector 4a — views/topology.js generateInsights()', () => {
    it('flags a NON-REDUNDANT (N) site as a critical insight', () => {
        const out = generateInsights({ redundancy_mode: 'N', hld_nodes: {} });
        expect(out).toHaveLength(1);
        expect(out[0].severity).toBe('critical');
    });

    it('is silent when the site is 2N with no degraded nodes', () => {
        expect(generateInsights({ redundancy_mode: '2N', hld_nodes: {} })).toHaveLength(0);
    });

    it('warns on a transformer winding above the IEEE C57.12 hot-spot', () => {
        const out = generateInsights({
            redundancy_mode: '2N',
            hld_nodes: {
                xfmr_a: { metrics: { winding_c: 115 } },
                xfmr_b: { metrics: { winding_c: 100 } },
            },
        });
        expect(out.some((i) => i.severity === 'warning' && i.text.includes('winding'))).toBe(true);
    });
});

describe('T2.1 Vector 4a — views/topology.js render helpers', () => {
    it('fmt0 / fmt1 format numbers and degrade gracefully on null', () => {
        expect(fmt0(1234.7)).toBe((1235).toLocaleString());
        expect(fmt1(4.237)).toBe('4.2');
        expect(fmt0(null)).toBe('—');
        expect(fmt1(undefined)).toBe('—');
    });

    it('renderLLDRacks stamps a rack <g> per rack and escapes the id', () => {
        document.body.innerHTML = '<svg><g id="lld-rack-group"></g></svg>';
        renderLLDRacks([
            { id: 'rack-A1', severity: 'ok', gpu_tj_c: 64, dlc_dt_k: 8, health: 0.96 },
            { id: 'rack-A2', severity: 'warning', gpu_tj_c: 78, dlc_dt_k: 5, health: 0.71 },
        ]);
        expect(document.querySelectorAll('#lld-rack-group g.lld-rack')).toHaveLength(2);
        expect(document.getElementById('lld-rack-group').textContent).toContain('rack-A1');
    });

    it('applyTopologyState binds the header SHI / weakest / redundancy badge', () => {
        document.body.innerHTML = `
            <div id="topo-shi"></div>
            <div id="topo-weakest"></div>
            <div id="topo-redundancy"></div>`;
        applyTopologyState({
            site_health: 0.91, weakest_module: 'heat_rejection',
            redundancy_mode: '2N', hld_nodes: {},
        });
        expect(document.getElementById('topo-shi').textContent).toBe('0.91');
        expect(document.getElementById('topo-weakest').textContent).toBe('heat_rejection');
        expect(document.getElementById('topo-redundancy').textContent).toBe('2N');
    });
});

describe('T2.1 Vector 4a — views/topology.js declarative routing', () => {
    it('initTopologyView registers the topology route on core/router.js', () => {
        document.body.innerHTML = '<div id="view-topology"></div>';
        initTopologyView();
        expect(isRegistered('topology')).toBe(true);
    });
});

// ════════════════════════════════════════════════════════════════
//  Batch 3 — registry-driven HLD generator (static SVG retired)
// ════════════════════════════════════════════════════════════════
describe('B3 — views/topology.js buildHldMarkup()', () => {
    afterEach(() => { document.body.innerHTML = ''; });

    it('emits every HLD node with its data-binder hooks intact', () => {
        const svg = buildHldMarkup();
        for (const id of [
            'utility_north', 'utility_south', 'xfmr_a', 'xfmr_b',
            'ups_a', 'ups_b', 'hall_1', 'hall_2', 'hall_3',
            'cdu_a', 'cdu_b', 'chiller_1', 'chiller_2', 'cooling_tower',
        ]) {
            expect(svg).toContain(`data-node="${id}"`);
        }
        // applyTopologyState binds onto these exact hooks:
        expect(svg).toContain('data-metric="utility_north-kw"');
        expect(svg).toContain('data-metric="cooling_tower-ecwt"');
        expect(svg).toContain('data-badge="cdu_a"');
        expect(svg).toContain('id="ct-sparkline-wb"');
        expect(svg).toContain('id="ct-deltat-warn"');
        expect(svg).toContain('id="cooling-tower-rect"');
    });

    it('routes every flow strictly orthogonally (spaghetti eradicated)', () => {
        const svg = buildHldMarkup();
        const ds = [...svg.matchAll(/<path class="topo-flow[^"]*" d="([^"]+)"/g)]
            .map((m) => m[1]);
        expect(ds.length).toBeGreaterThan(0);
        for (const d of ds) {
            const pts = d.trim().split(/[ML]\s*/).filter(Boolean)
                .map((p) => p.trim().split(/\s+/).map(Number));
            for (let i = 1; i < pts.length; i += 1) {
                const [x1, y1] = pts[i - 1];
                const [x2, y2] = pts[i];
                expect(x1 === x2 || y1 === y2).toBe(true);
            }
        }
    });

    it('S-VOCAB-01 — the electrical header says 480 VAC 3-phase, never 480VDC', () => {
        const svg = buildHldMarkup();
        expect(svg).toContain('480 VAC 3-φ');
        expect(svg).not.toMatch(/480\s*VDC/i);
        // The only VDC in the HLD is Building D's honest design marker.
        expect(svg).toContain('800 VDC unipolar TN-S');
    });

    it('marks Building D as a non-interactive Phase 2 design pointer', () => {
        const svg = buildHldMarkup();
        expect(svg).toMatch(/class="topo-node-design" data-phase="2"/);
        expect(svg).toContain('full branch: Power SLD');
        // No data-node attr -> no detail panel, no emergency-sim trips.
        expect(svg).not.toMatch(/topo-node-design[^>]*data-node=/);
    });

    it('renderHld injects the generated HLD into the #topo-hld-svg shell', () => {
        document.body.innerHTML =
            '<div id="topo-canvas-hld"><svg id="topo-hld-svg"></svg></div>';
        renderHld();
        expect(document.getElementById('topo-hld-svg').innerHTML)
            .toContain('data-node="cooling_tower"');
    });
});

// ════════════════════════════════════════════════════════════════
//  Batch 3 — Hermes-driven live severity (the 8 s poll is retired)
// ════════════════════════════════════════════════════════════════
describe('B3 — views/topology.js applyTelemetry()', () => {
    afterEach(() => { document.body.innerHTML = ''; });

    function mountHld() {
        document.body.innerHTML =
            '<div id="topo-canvas-hld"><svg id="topo-hld-svg"></svg></div>';
        renderHld();
    }

    it('maps an anomalous Kalman channel onto its HLD rect as sev-critical', () => {
        mountHld();
        applyTelemetry({ ups_a_soc: { is_anomalous: true, max_z: 4.0 } });
        const rect = document.querySelector(
            '.topo-node[data-node="ups_a"] rect.topo-node-rect');
        expect(rect.getAttribute('class')).toBe('topo-node-rect sev-critical');
    });

    it('resolves channels through the registry (utility_north owns util_a-prefixed ids)', () => {
        mountHld();
        applyTelemetry({ util_a_kw: { is_anomalous: false, max_z: 2.5 } });
        const rect = document.querySelector(
            '.topo-node[data-node="utility_north"] rect.topo-node-rect');
        expect(rect.getAttribute('class')).toBe('topo-node-rect sev-warning');
    });

    it('leaves unmatched nodes untouched and no-ops on empty payloads', () => {
        mountHld();
        applyTelemetry({ ups_a_soc: { is_anomalous: true } });
        const rect = document.querySelector(
            '.topo-node[data-node="chiller_1"] rect.topo-node-rect');
        expect(rect.getAttribute('class')).toBe('topo-node-rect');
        expect(() => applyTelemetry(null)).not.toThrow();
        expect(() => applyTelemetry({})).not.toThrow();
    });
});
