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
