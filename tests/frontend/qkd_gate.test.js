/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO -- tests/frontend/qkd_gate.test.js
 * Epic 10 Batch 4 -- QKD-driven global signing gate invariants.
 *
 * Verifies the state machine:
 *   - Below threshold -> gate OPEN -> body has no qkd-gate-closed
 *     class -> banner hidden -> isSigningEnabled() true.
 *   - At/above threshold -> gate CLOSED -> body class added ->
 *     banner visible with "Firma Deshabilitada: Enlace
 *     Interceptado" + QBER/threshold values rendered.
 *   - null/undefined qber -> gate stays OPEN (no batches yet ->
 *     fail-permissive at boot; the backend is authoritative).
 *   - Transitions fire dc-epms-qkd-gate-opened /
 *     dc-epms-qkd-gate-closed events.
 *   - XSS gate: payload fields are escaped before innerHTML.
 * ════════════════════════════════════════════════════════════════ */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { __qkd_gate_test__ } from '/assets/js/core/qkd_gate.js';

const gate = __qkd_gate_test__;

function mountBanner() {
    document.body.innerHTML = '<div data-qkd-gate-banner hidden></div>';
}

function _payload({
    qber = 0.0, threshold = 0.11, last = 'accepted',
    depth = 8,
} = {}) {
    return {
        framing: 'Educational BB84 simulator.',
        pool_depth: depth,
        pool_capacity: 32,
        keys_accepted_total: 10,
        keys_rejected_total: 0,
        last_qber: qber,
        last_decision: last,
        qber_threshold: threshold,
        eavesdrop_simulated: false,
        audit_log_size: 1,
        recent_audit: [],
    };
}

beforeEach(() => {
    gate.reset();
    document.body.classList.remove('qkd-gate-closed');
    document.body.innerHTML = '';
});

afterEach(() => {
    gate.reset();
    document.body.classList.remove('qkd-gate-closed');
    document.body.innerHTML = '';
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
});


describe('Epic 10 Batch 4 -- gate state machine', () => {
    it('defaults to OPEN before any status arrives', () => {
        expect(gate.isSigningEnabled()).toBe(true);
    });

    it('stays OPEN below threshold', () => {
        mountBanner();
        gate.applyStatusPayload(_payload({ qber: 0.02 }));
        expect(gate.isSigningEnabled()).toBe(true);
        expect(document.body.classList.contains('qkd-gate-closed')).toBe(false);
        expect(document.querySelector('[data-qkd-gate-banner]').hidden).toBe(true);
    });

    it('CLOSES at or above threshold', () => {
        mountBanner();
        gate.applyStatusPayload(_payload({ qber: 0.25 }));
        expect(gate.isSigningEnabled()).toBe(false);
        expect(document.body.classList.contains('qkd-gate-closed')).toBe(true);
        const banner = document.querySelector('[data-qkd-gate-banner]');
        expect(banner.hidden).toBe(false);
        expect(banner.innerHTML).toContain('Firma Deshabilitada');
        expect(banner.innerHTML).toContain('Enlace Interceptado');
    });

    it('null QBER keeps gate OPEN (no-batches-yet path)', () => {
        mountBanner();
        gate.applyStatusPayload(_payload({ qber: null }));
        expect(gate.isSigningEnabled()).toBe(true);
        expect(document.body.classList.contains('qkd-gate-closed')).toBe(false);
    });

    it('missing payload keeps gate OPEN', () => {
        mountBanner();
        gate.applyStatusPayload(null);
        expect(gate.isSigningEnabled()).toBe(true);
    });

    it('re-opens when QBER drops back below threshold', () => {
        mountBanner();
        gate.applyStatusPayload(_payload({ qber: 0.25 }));
        expect(gate.isSigningEnabled()).toBe(false);
        gate.applyStatusPayload(_payload({ qber: 0.0 }));
        expect(gate.isSigningEnabled()).toBe(true);
        expect(document.querySelector('[data-qkd-gate-banner]').hidden).toBe(true);
    });
});

describe('Epic 10 Batch 4 -- transition events', () => {
    it('dispatches dc-epms-qkd-gate-closed on close', () => {
        mountBanner();
        const spy = vi.fn();
        window.addEventListener('dc-epms-qkd-gate-closed', spy);
        gate.applyStatusPayload(_payload({ qber: 0.30 }));
        expect(spy).toHaveBeenCalled();
        window.removeEventListener('dc-epms-qkd-gate-closed', spy);
    });

    it('dispatches dc-epms-qkd-gate-opened on re-open', () => {
        mountBanner();
        gate.applyStatusPayload(_payload({ qber: 0.30 }));
        const spy = vi.fn();
        window.addEventListener('dc-epms-qkd-gate-opened', spy);
        gate.applyStatusPayload(_payload({ qber: 0.0 }));
        expect(spy).toHaveBeenCalled();
        window.removeEventListener('dc-epms-qkd-gate-opened', spy);
    });

    it('does not re-emit on same-state polls', () => {
        mountBanner();
        const closeSpy = vi.fn();
        window.addEventListener('dc-epms-qkd-gate-closed', closeSpy);
        gate.applyStatusPayload(_payload({ qber: 0.30 }));
        gate.applyStatusPayload(_payload({ qber: 0.40 }));  // still closed
        expect(closeSpy).toHaveBeenCalledTimes(1);
        window.removeEventListener('dc-epms-qkd-gate-closed', closeSpy);
    });
});

describe('Epic 10 Batch 4 -- banner XSS gate (S-SEC-01)', () => {
    it('escapes adversarial threshold injection', () => {
        mountBanner();
        gate.applyStatusPayload({
            last_qber: 0.30,
            qber_threshold: 0.11,
            last_decision: '<script>alert(1)</script>',
            pool_depth: 0,
        });
        const banner = document.querySelector('[data-qkd-gate-banner]');
        expect(banner.innerHTML).not.toContain('<script>alert');
        // The payload-supplied last_decision is not rendered to the
        // banner (only qber + threshold are), so the assertion is
        // that NOTHING from last_decision leaks in -- defence in
        // depth.
        expect(banner.querySelectorAll('script').length).toBe(0);
    });
});

describe('Epic 10 Batch 4 -- listener fan-out', () => {
    it('onQkdGateChange callbacks see every poll', () => {
        const calls = [];
        gate.onQkdGateChange((s) => calls.push(s.enabled));
        gate.applyStatusPayload(_payload({ qber: 0.0 }));
        gate.applyStatusPayload(_payload({ qber: 0.20 }));
        gate.applyStatusPayload(_payload({ qber: 0.05 }));
        expect(calls).toEqual([true, false, true]);
    });

    it('listener errors are swallowed', () => {
        gate.onQkdGateChange(() => { throw new Error('boom'); });
        // Should not throw.
        gate.applyStatusPayload(_payload({ qber: 0.0 }));
        expect(gate.isSigningEnabled()).toBe(true);
    });
});

describe('Epic 10 Batch 4 -- getQkdGateState snapshot', () => {
    it('returns a copy with the latest fields', () => {
        gate.applyStatusPayload(_payload({
            qber: 0.18, threshold: 0.11, depth: 0,
        }));
        const s = gate.getQkdGateState();
        expect(s.enabled).toBe(false);
        expect(s.qber).toBe(0.18);
        expect(s.threshold).toBe(0.11);
        expect(s.pool_depth).toBe(0);
    });
});
