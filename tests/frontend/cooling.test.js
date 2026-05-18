/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/cooling.test.js
 * ROADMAP V11 T2.1 Phase 2a — verifies the extracted Cooling view.
 *
 * Behaviour-preserving extraction smoke test: the P&ID data binder
 * stamps node severity + metric text + the redundancy banner onto a
 * happy-dom #view-cooling fixture. No browser, no backend.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, afterEach } from 'vitest';

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
        expect(svg.getAttribute('viewBox')).toBe('0 0 1040 620');
    });
});
