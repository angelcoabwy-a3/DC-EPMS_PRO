/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/mission_control.test.js
 * ROADMAP V11 T2.4 — Frontend Test Harness, Bite 1: Proof of Life.
 *
 * Bite 1 proves the harness itself works: Vitest executes, happy-dom
 * supplies a real DOM, and the WebGL mock (setup.js) is installed.
 *
 * Per the T2.4 directive, Bite 1 does NOT import the real
 * mission_control.js — that module pulls in three.js and the render
 * loop, which is Bite 2 territory ("foundational infrastructure
 * first"). The file is named mission_control.test.js so Bite 2 can
 * extend it in place (e.g. importing the view module behind the
 * `/assets` alias and asserting against _transitioning behaviour).
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect } from 'vitest';

describe('T2.4 harness — Bite 1 proof of life', () => {
    it('runs inside a happy-dom environment with a live document', () => {
        expect(typeof window).toBe('object');
        expect(typeof document).toBe('object');

        // Simulate a fragment of the Mission Control DOM contract.
        const status = document.createElement('div');
        status.id = 'mc-status';
        status.textContent = 'ready';
        document.body.appendChild(status);

        expect(document.getElementById('mc-status')).not.toBeNull();
        expect(document.getElementById('mc-status').textContent).toBe('ready');

        document.body.innerHTML = '';   // clean up for test isolation
    });

    it('has the WebGL context mock installed (setup.js)', () => {
        const canvas = document.createElement('canvas');
        const gl = canvas.getContext('webgl');

        // happy-dom alone returns null here — the mock must intercept.
        expect(gl).not.toBeNull();
        expect(typeof gl.createBuffer).toBe('function');

        // GL enum reads resolve to 0; method calls are chainable no-ops
        // and must never throw — that is what will keep three.js from
        // crashing the runner when Bite 2 imports the real view.
        expect(gl.COLOR_BUFFER_BIT).toBe(0);
        expect(() => gl.clear(gl.COLOR_BUFFER_BIT)).not.toThrow();
    });

    it('exposes a usable requestAnimationFrame for timing-based code', async () => {
        const ts = await new Promise((resolve) => requestAnimationFrame(resolve));
        expect(typeof ts).toBe('number');
    });
});
