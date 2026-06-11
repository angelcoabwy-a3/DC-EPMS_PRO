/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/contingency.test.js
 * N-1 Shadow — pure steady-state contingency evaluator + the shared
 * diagram overlay.
 *
 * The engineering judgments are the test subjects: genset = degraded
 * survival; battery holdup = NOT sustained survival; cooling N+1
 * pairs absorb a single loss.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, afterEach } from 'vitest';

import {
    steadyStatePower, steadyStateCooling, n1Power, n1Cooling,
} from '/assets/js/core/contingency.js';
import { createN1Overlay } from '/assets/js/core/n1_overlay.js';
import { __power_test__ } from '/assets/js/views/power.js';

// ════════════════════════════════════════════════════════════════
//  Pure evaluator — POWER
// ════════════════════════════════════════════════════════════════
describe('N1 — steadyStatePower()', () => {
    it('baseline: everything alive on utility, nothing degraded', () => {
        const s = steadyStatePower();
        expect(s.get('ups_a').alive).toBe(true);
        expect(s.get('ups_a').energizedBy).toBe('util');
        expect(s.get('ddu_a1').alive).toBe(true);
        expect(s.get('ups_a').degraded).toBe(false);
    });

    it('utility loss is ABSORBED degraded: the chain rides the genset', () => {
        const s = steadyStatePower(new Set(['util_a']));
        expect(s.get('ats_a').alive).toBe(true);
        expect(s.get('ups_a').alive).toBe(true);
        expect(s.get('ups_a').energizedBy).toBe('genset');
        expect(s.get('ups_a').degraded).toBe(true);
        expect(s.get('ddu_a1').degraded).toBe(true);
        // Path B untouched.
        expect(s.get('ups_b').degraded).toBe(false);
    });

    it('ATS loss is NOT absorbed: battery holdup is excluded from sustained survival', () => {
        const s = steadyStatePower(new Set(['ats_a']));
        expect(s.get('ups_a').alive).toBe(false);
        expect(s.get('rpp_a1').alive).toBe(false);
        expect(s.get('ddu_a6').alive).toBe(false);
    });

    it('utility + genset double loss kills the path (but that is N-2)', () => {
        const s = steadyStatePower(new Set(['util_a', 'genset_a']));
        expect(s.get('ups_a').alive).toBe(false);
    });
});

// ════════════════════════════════════════════════════════════════
//  Pure evaluator — COOLING
// ════════════════════════════════════════════════════════════════
describe('N1 — steadyStateCooling()', () => {
    it('one chiller out: absorbed, the N+1 peer reports degraded', () => {
        const s = steadyStateCooling(new Set(['chiller_1']));
        expect(s.get('chiller_2').alive).toBe(true);
        expect(s.get('chiller_2').degraded).toBe(true);
        expect(s.get('data_hall').alive).toBe(true);
    });

    it('tower out: the whole chain loses cooling', () => {
        const s = steadyStateCooling(new Set(['cooling_tower']));
        expect(s.get('chiller_1').alive).toBe(false);
        expect(s.get('data_hall').alive).toBe(false);
    });
});

// ════════════════════════════════════════════════════════════════
//  N-1 sweeps
// ════════════════════════════════════════════════════════════════
describe('N1 — n1Power() / n1Cooling() sweeps', () => {
    it('classifies utility as warning (degraded survivors), ATS as critical', () => {
        const a = n1Power();
        expect(a.get('util_a').tone).toBe('warning');
        // The de-energized intermediate (xfmr) is REPORTED in lost,
        // but with zero load loss the tone stays warning.
        expect(a.get('util_a').lost).toEqual(['xfmr_a']);
        expect(a.get('util_a').degraded.length).toBeGreaterThan(0);
        expect(a.get('ats_a').tone).toBe('critical');
        expect(a.get('ats_a').lost).toContain('ups_a');
        expect(a.get('ats_a').lost).toContain('ddu_a1');
        // Leaf DDU failure hurts nobody else.
        expect(a.get('ddu_a1').tone).toBe('ok');
        // Battery is not a candidate (already excluded from survival).
        expect(a.has('batt_a')).toBe(false);
    });

    it('cooling sweep: chiller absorbed (warning), tower critical', () => {
        const a = n1Cooling();
        expect(a.get('chiller_1').tone).toBe('warning');
        expect(a.get('chiller_1').degraded).toContain('chiller_2');
        expect(a.get('cooling_tower').tone).toBe('critical');
        expect(a.get('cooling_tower').lost).toContain('data_hall');
    });
});

// ════════════════════════════════════════════════════════════════
//  Overlay (DOM layer) — via the Power SLD integration
// ════════════════════════════════════════════════════════════════
describe('N1 — overlay on the Power SLD', () => {
    const { renderFlatSld, buildN1Toggle, setN1, n1Overlay, setMode, reset } =
        __power_test__;

    afterEach(() => {
        reset();
        document.body.innerHTML = '';
    });

    function mountView() {
        document.body.innerHTML =
            '<div id="view-power"><div class="pid-action-bar"></div>'
            + '<svg class="pid-svg"></svg></div>';
        renderFlatSld();
        buildN1Toggle();
    }

    it('setN1(true) stamps tone-coded badges on the SLD nodes', () => {
        mountView();
        setN1(true);
        expect(n1Overlay.isAttached()).toBe(true);
        const atsBadge = document.querySelector('[data-n1-badge="ats_a"]');
        expect(atsBadge).not.toBeNull();
        expect(atsBadge.getAttribute('data-tone')).toBe('critical');
        expect(atsBadge.textContent).toMatch(/^N-1:\d+$/);
        const utilBadge = document.querySelector('[data-n1-badge="util_a"]');
        expect(utilBadge.getAttribute('data-tone')).toBe('warning');
        // Phase 2 design nodes are outside the contingency model: no badge.
        expect(document.querySelector('[data-n1-badge="mv_rect_d"]')).toBeNull();
    });

    it('setN1(false) removes every badge and glow', () => {
        mountView();
        setN1(true);
        setN1(false);
        expect(document.querySelectorAll('[data-n1-badge]')).toHaveLength(0);
        expect(n1Overlay.isAttached()).toBe(false);
    });

    it('entering the What-If sandbox retires the shadow; it cannot attach inside', () => {
        mountView();
        setN1(true);
        setMode('whatif');
        expect(n1Overlay.isAttached()).toBe(false);
        setN1(true);   // attempt inside the sandbox
        expect(n1Overlay.isAttached()).toBe(false);
    });

    it('createN1Overlay is a safe no-op against a missing root', () => {
        const ov = createN1Overlay({
            rootSelector: '#nope', nodeSelector: '.x', idAttr: 'x',
            nameSelector: '.y', analysisFn: () => new Map(),
        });
        expect(() => { ov.attach(); ov.detach(); }).not.toThrow();
        expect(ov.isAttached()).toBe(false);
    });
});
