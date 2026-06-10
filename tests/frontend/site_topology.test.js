/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/site_topology.test.js
 * Diagram Rebuild Batch 4 — the force-directed site graph stops
 * being a dead map: live Hermes severity + the registry-resolved
 * cross-link into the SLD views.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, afterEach } from 'vitest';

import { __site_topology_test__ } from '/assets/js/views/site_topology.js';

const {
    applyTelemetry, onTelemetryFrame, sldTargetFor, renderDetail,
    renderNodes, setData, select, reset,
} = __site_topology_test__;

afterEach(() => {
    reset();
    document.body.innerHTML = '';
});

function mountGraph() {
    document.body.innerHTML = `
        <svg id="topo-graph-svg">
            <g id="topo-graph-edges"></g>
            <g id="topo-graph-nodes"></g>
        </svg>`;
    setData([
        { id: 'ups_a', type: 'ups', x: 100, y: 100 },
        { id: 'chiller_1', type: 'chiller', x: 200, y: 100 },
        { id: 'rack_a_01', type: 'it_rack', x: 300, y: 100 },
    ], []);
    renderNodes();
}

// ════════════════════════════════════════════════════════════════
//  Live severity (Hermes -> registry channel prefixes -> glow)
// ════════════════════════════════════════════════════════════════
describe('B4 — site_topology applyTelemetry()', () => {
    it('marks an anomalous node with the critical glow class', () => {
        mountGraph();
        applyTelemetry({ ups_a_soc: { is_anomalous: true, max_z: 4.0 } });
        const el = document.querySelector('.topo-node[data-id="ups_a"]');
        expect(el.classList.contains('topo-gsev-critical')).toBe(true);
        expect(el.classList.contains('topo-gsev-warning')).toBe(false);
    });

    it('downgrades to warning on elevated z and clears back to ok', () => {
        mountGraph();
        applyTelemetry({ chiller_1_cop: { is_anomalous: false, max_z: 2.6 } });
        const el = document.querySelector('.topo-node[data-id="chiller_1"]');
        expect(el.classList.contains('topo-gsev-warning')).toBe(true);
        applyTelemetry({ chiller_1_cop: { is_anomalous: false, max_z: 0.3 } });
        expect(el.classList.contains('topo-gsev-warning')).toBe(false);
        expect(el.classList.contains('topo-gsev-critical')).toBe(false);
    });

    it('severity survives a full re-render (state lives in the module map)', () => {
        mountGraph();
        applyTelemetry({ ups_a_soc: { is_anomalous: true } });
        renderNodes();   // simulate a re-layout
        const el = document.querySelector('.topo-node[data-id="ups_a"]');
        expect(el.getAttribute('class')).toContain('topo-gsev-critical');
    });

    it('prefix discipline holds: ups_a channels never light up rack_a_01', () => {
        mountGraph();
        applyTelemetry({ ups_a_soc: { is_anomalous: true } });
        const rack = document.querySelector('.topo-node[data-id="rack_a_01"]');
        expect(rack.getAttribute('class')).not.toContain('topo-gsev');
    });

    it('onTelemetryFrame routes a Hermes frame; null payloads are no-ops', () => {
        mountGraph();
        onTelemetryFrame({ channels: { ups_a_soc: { is_anomalous: true } } });
        expect(document.querySelector('.topo-node[data-id="ups_a"]')
            .classList.contains('topo-gsev-critical')).toBe(true);
        expect(() => onTelemetryFrame(null)).not.toThrow();
        expect(() => applyTelemetry({})).not.toThrow();
    });
});

// ════════════════════════════════════════════════════════════════
//  Cross-link (registry identity -> owning diagram view)
// ════════════════════════════════════════════════════════════════
describe('B4 — site_topology cross-link into the SLD views', () => {
    it('resolves power-chain graph ids to the Power SLD route', () => {
        expect(sldTargetFor('ups_a')).toEqual(
            { route: 'power', label: 'Open in Power SLD' });
        expect(sldTargetFor('utility_feed_a').route).toBe('power');
        // Phase 2 chain resolves too — one identity, five views.
        expect(sldTargetFor('mv_rectifier_d').route).toBe('power');
        expect(sldTargetFor('main_bus_dc_d').route).toBe('power');
    });

    it('resolves cooling-chain ids to the Cooling P&ID route', () => {
        expect(sldTargetFor('chiller_1')).toEqual(
            { route: 'cooling', label: 'Open in Cooling P&ID' });
        expect(sldTargetFor('cdu_a').route).toBe('cooling');
    });

    it('returns null for assets outside the registry (no dead buttons)', () => {
        expect(sldTargetFor('rack_a_01')).toBeNull();
        expect(sldTargetFor('definitely_unknown')).toBeNull();
    });

    it('renderDetail shows the cross-link button only for mapped assets', () => {
        document.body.innerHTML = `
            <div id="topo-graph-detail" hidden>
                <span id="topo-graph-detail-id"></span>
                <span id="topo-graph-detail-type"></span>
                <span id="topo-graph-detail-facility"></span>
                <span id="topo-graph-detail-building"></span>
                <span id="topo-graph-detail-room"></span>
                <span id="topo-graph-detail-impact"></span>
                <button id="topo-graph-detail-open-sld" hidden></button>
            </div>`;
        setData([
            { id: 'ups_a', type: 'ups', x: 0, y: 0 },
            { id: 'rack_a_01', type: 'it_rack', x: 0, y: 0 },
        ], []);
        const btn = document.getElementById('topo-graph-detail-open-sld');

        select('ups_a');
        renderDetail();
        expect(btn.hidden).toBe(false);
        expect(btn.textContent).toBe('Open in Power SLD');
        expect(btn.dataset.route).toBe('power');

        select('rack_a_01');
        renderDetail();
        expect(btn.hidden).toBe(true);
        expect(btn.dataset.route).toBeUndefined();
    });
});
