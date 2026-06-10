/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/diagram_kit.test.js
 * Diagram Rebuild Batch 0 — shared diagram kit + canonical node
 * registry.
 *
 * The kit is the single visual language for every engineering
 * diagram; the registry is the single identity map. Both are pure
 * modules — happy-dom only where the DOM is genuinely involved
 * (spark tracker, actuation modal).
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, vi, afterEach } from 'vitest';

import {
    SEV, severityFromChannels, orthoPath, wire, symbol, SYMBOL_TYPES,
    sparkPoints, sparkPolyline, createSparkTracker, legend,
    DEFAULT_LEGEND, createActuationModal,
} from '/assets/js/core/diagram_kit.js';
import {
    getNode, topoKeyFor, nodeForGraphId, nodesWhere, sldToTopoMap,
    matchesChannel, channelPrefixesFor, __registry_test__,
} from '/assets/js/core/node_registry.js';

// ════════════════════════════════════════════════════════════════
//  Orthogonal wiring — the no-spaghetti guarantee is structural
// ════════════════════════════════════════════════════════════════
describe('B0 — diagram_kit orthoPath()', () => {
    it('builds an M/L path from axis-aligned waypoints', () => {
        expect(orthoPath([[0, 0], [10, 0], [10, 5]])).toBe('M0 0 L10 0 L10 5');
    });

    it('THROWS on a diagonal segment (orthogonality by construction)', () => {
        expect(() => orthoPath([[0, 0], [10, 7]])).toThrow(/diagonal/);
    });

    it('wire() emits a pf-wire path with the caller class', () => {
        const w = wire([[0, 4], [8, 4]], 'pf-dc');
        expect(w).toContain('class="pf-wire pf-dc"');
        expect(w).toContain('d="M0 4 L8 4"');
    });
});

// ════════════════════════════════════════════════════════════════
//  Symbol library — incl. the Phase 2 set
// ════════════════════════════════════════════════════════════════
describe('B0 — diagram_kit symbol()', () => {
    it('every symbol carries the pid-symbol severity hook', () => {
        for (const t of SYMBOL_TYPES) {
            expect(symbol(t, 100, 100)).toContain('pid-symbol');
            expect(symbol(t, 100, 100)).toContain('data-sev="ok"');
        }
    });

    it('xfmr renders the two-winding IEEE mark', () => {
        const s = symbol('xfmr', 50, 50);
        expect([...s.matchAll(/<circle/g)]).toHaveLength(2);
    });

    it('rectifier renders the AC/DC converter boundary mark', () => {
        const s = symbol('rectifier', 50, 50);
        expect(s).toContain('>AC<');
        expect(s).toContain('>DC<');
        expect(s).toContain('pf-conv-divider');
    });

    it('dcbus renders the 800 VDC bus bar with its DC class', () => {
        expect(symbol('dcbus', 50, 50)).toContain('pf-bus-dc');
    });

    it('unknown types fall back to the generic equipment box', () => {
        expect(symbol('definitely_not_a_type', 50, 50)).toContain('<rect');
    });
});

// ════════════════════════════════════════════════════════════════
//  Severity model (single source)
// ════════════════════════════════════════════════════════════════
describe('B0 — diagram_kit severityFromChannels()', () => {
    it('anomalous channel -> critical, |max_z|>=2 -> warning, else ok', () => {
        expect(severityFromChannels([{ is_anomalous: true }])).toBe(SEV.CRITICAL);
        expect(severityFromChannels([{ max_z: -2.4 }])).toBe(SEV.WARNING);
        expect(severityFromChannels([{ max_z: 1.1 }])).toBe(SEV.OK);
        expect(severityFromChannels([])).toBe(SEV.OK);
    });
});

// ════════════════════════════════════════════════════════════════
//  Sparklines
// ════════════════════════════════════════════════════════════════
describe('B0 — diagram_kit sparklines', () => {
    afterEach(() => { document.body.innerHTML = ''; });

    it('sparkPoints maps one SVG point per sample, empty under 2', () => {
        expect(sparkPoints([1, 4, 2], 0, 10, 30, 10).split(' ')).toHaveLength(3);
        expect(sparkPoints([3], 0, 10, 30, 10)).toBe('');
    });

    it('createSparkTracker accumulates ticks and draws into the polyline', () => {
        document.body.innerHTML =
            `<div id="host"><svg>${sparkPolyline('ups_a', 0, 20)}</svg></div>`;
        const tracker = createSparkTracker({
            rootSelector: '#host', nodes: new Set(['ups_a']), ticks: 3,
        });
        const matcher = (nodeId, ch) => ch.startsWith(nodeId);
        tracker.update({ ups_a_soc: { mean_z: 1.0 } }, matcher);
        tracker.update({ ups_a_soc: { mean_z: 2.0 } }, matcher);
        const pts = document.querySelector('[data-spark="ups_a"]')
            .getAttribute('points').trim();
        expect(pts.split(' ')).toHaveLength(2);
        tracker.reset();
        expect(Object.keys(tracker._history)).toHaveLength(0);
    });
});

// ════════════════════════════════════════════════════════════════
//  Legend — the shared visual language
// ════════════════════════════════════════════════════════════════
describe('B0 — diagram_kit legend()', () => {
    it('renders one swatch row per item and escapes labels', () => {
        const g = legend([
            { swatch: 'ok', label: 'Nominal' },
            { swatch: 'dc', label: '<img onerror=x>' },
        ], 10, 20);
        expect(g).toContain('dk-swatch-ok');
        expect(g).toContain('dk-swatch-dc');
        expect(g).not.toContain('<img');
        expect(g).toContain('&lt;img');
    });

    it('DEFAULT_LEGEND teaches the DC vocabulary fence', () => {
        const labels = DEFAULT_LEGEND.map((i) => i.label).join(' | ');
        expect(labels).toContain('800 VDC unipolar TN-S');
        expect(labels).toContain('AC path (3-phase)');
    });
});

// ════════════════════════════════════════════════════════════════
//  Actuation modal factory (shared RBAC command dialog)
// ════════════════════════════════════════════════════════════════
describe('B0 — diagram_kit createActuationModal()', () => {
    afterEach(() => {
        document.body.innerHTML = '';
        vi.restoreAllMocks();
    });

    function makeModal(onSubmit = vi.fn()) {
        return createActuationModal({
            modalId: 'kit-test-modal',
            titleId: 'kit-test-title',
            roleSelectId: 'kit-test-role',
            icon: '&#9889;',
            title: 'Kit Test Control',
            targetLabel: 'Target:',
            commands: [{ cmd: 'OPEN', label: 'OPEN' }, { cmd: 'CLOSE', label: 'CLOSE' }],
            onSubmit,
        });
    }

    it('open() mounts the dialog with target + nodeId stamped', () => {
        const m = makeModal();
        m.open('ats_a', 'ATS-A');
        const el = document.getElementById('kit-test-modal');
        expect(el.hidden).toBe(false);
        expect(el.dataset.nodeId).toBe('ats_a');
        expect(el.querySelector('[data-field="target"]').textContent).toBe('ATS-A');
        expect(el.querySelector('[data-act="confirm"]').disabled).toBe(true);
    });

    it('selecting a command arms confirm; confirm fires onSubmit with the role', () => {
        const onSubmit = vi.fn();
        const m = makeModal(onSubmit);
        m.open('ats_a', 'ATS-A');
        const el = document.getElementById('kit-test-modal');
        el.querySelector('.pwr-cmd-btn[data-cmd="OPEN"]').click();
        expect(el.querySelector('[data-act="confirm"]').disabled).toBe(false);
        // Pick the role explicitly (happy-dom's `selected`-attribute
        // default resolution differs from browsers).
        el.querySelector('#kit-test-role').value = 'SME_L6';
        el.querySelector('[data-act="confirm"]').click();
        expect(onSubmit).toHaveBeenCalledWith('ats_a', 'OPEN', 'SME_L6');
    });

    it('showResult paints 403 as RBAC DENIED and 200 as accepted', () => {
        const m = makeModal();
        m.open('ats_a', 'ATS-A');
        m.showResult({ ok: false, status: 403, data: { detail: 'nope' } }, 'OPEN', 'ats_a');
        let r = document.querySelector('#kit-test-modal [data-field="result"]');
        expect(r.className).toContain('is-denied');
        m.showResult({ ok: true, status: 200, data: { message: 'done' } }, 'OPEN', 'ats_a');
        r = document.querySelector('#kit-test-modal [data-field="result"]');
        expect(r.className).toContain('is-ok');
    });
});

// ════════════════════════════════════════════════════════════════
//  Node registry — one asset, one identity
// ════════════════════════════════════════════════════════════════
describe('B0 — node_registry canonical identity', () => {
    it('maps the SLD id to the topology-state key (the util_a triple)', () => {
        expect(topoKeyFor('util_a')).toBe('utility_north');
        expect(topoKeyFor('util_b')).toBe('utility_south');
        expect(topoKeyFor('ups_a')).toBe('ups_a');
    });

    it('maps a site-graph id back to its canonical entry', () => {
        expect(nodeForGraphId('utility_feed_a').id).toBe('util_a');
        expect(nodeForGraphId('mv_rectifier_d').id).toBe('mv_rect_d');
        expect(nodeForGraphId('main_bus_dc_d').id).toBe('dc_bus_d');
        expect(nodeForGraphId('rpp_a_01').id).toBe('rpp_a1');
    });

    it('sldToTopoMap reproduces the legacy power view mapping', () => {
        const m = sldToTopoMap();
        expect(m.util_a).toBe('utility_north');
        expect(m.rpp_b2).toBe('rpp_b2');
        expect(m.batt_a).toBe('ups_a');
        expect(m.par_bus_a).toBeUndefined();   // visual-only node
    });

    it('models the full Phase 2 Building D chain from the live graph', () => {
        const p2 = nodesWhere({ phase: 2, chain: 'power' });
        const ids = p2.map((e) => e.id);
        for (const id of ['util_d', 'mv_rect_d', 'sscb_d', 'dc_bus_d', 'bess_d', 'rpp_d1', 'rpp_d2']) {
            expect(ids).toContain(id);
        }
    });

    it('S-VOCAB-01 — no Phase 2 DC-side label ever says three-phase', () => {
        const dcSide = ['mv_rect_d', 'sscb_d', 'dc_bus_d', 'bess_d', 'rpp_d1', 'rpp_d2', 'hall_d'];
        for (const id of dcSide) {
            const label = getNode(id).label.toLowerCase();
            expect(label).not.toMatch(/trif|three-phase|3-phase/);
        }
        expect(getNode('dc_bus_d').label).toContain('UNIPOLAR TN-S');
    });

    it('matchesChannel enforces prefix discipline (the ups_a / ups_a1 fix)', () => {
        expect(matchesChannel('ups_a_soc', ['ups_a'])).toBe(true);
        expect(matchesChannel('ups_a', ['ups_a'])).toBe(true);
        expect(matchesChannel('ups_a1_voltage', ['ups_a'])).toBe(false);
        expect(matchesChannel('xfmr_a_winding', ['ups_a'])).toBe(false);
    });

    it('channelPrefixesFor returns bindings; unknown ids return []', () => {
        expect(channelPrefixesFor('util_a')).toContain('utility_north');
        expect(channelPrefixesFor('nope_xyz')).toEqual([]);
    });

    it('registry entries are structurally complete', () => {
        for (const e of __registry_test__.ENTRIES) {
            expect(e.id).toBeTruthy();
            expect(e.label).toBeTruthy();
            expect([1, 2]).toContain(e.phase);
            expect(['power', 'cooling', 'it']).toContain(e.chain);
            expect(Array.isArray(e.graph)).toBe(true);
            expect(Array.isArray(e.channels)).toBe(true);
        }
    });
});
