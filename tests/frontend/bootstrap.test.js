/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/bootstrap.test.js
 * ROADMAP V11 T2.1 Vector 4c — verifies core/bootstrap.js.
 *
 * core/bootstrap.js is the old app.js IIFE's residual (MODULES +
 * navigateTo + setupRouter + renderPlaceholder), promoted to an ES
 * module so app.js could be DELETED — closing Epic T2.1. This checks
 * the route table, the placeholder renderer, and the legacy nav
 * fallback for the non-declarative routes. No browser, no backend.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, afterEach } from 'vitest';

import { __bootstrap_test__ } from '/assets/js/core/bootstrap.js';

const {
    MODULES, navigateTo, renderPlaceholder, setupRouter,
    stampAppVersion, APP_VERSION,
} = __bootstrap_test__;

afterEach(() => { document.body.innerHTML = ''; });

describe('T2.1 Vector 4c — core/bootstrap.js MODULES table', () => {
    it('carries the route config for maintenance + placeholder + module routes', () => {
        expect(MODULES.overview).toBeNull();
        expect(MODULES.maintenance.kind).toBe('maintenance');
        expect(MODULES.morpheus.kind).toBe('placeholder');
        expect(MODULES.bms.kind).toBe('bms');
        expect(MODULES.copilot.kind).toBe('copilot');
    });
});

describe('T2.1 Vector 4c — core/bootstrap.js renderPlaceholder', () => {
    it('stamps a coming-soon stub view from the MODULES config', () => {
        document.body.innerHTML = `
            <div id="ph-title"></div><div id="ph-sub"></div>
            <div id="ph-icon"></div><div id="ph-desc"></div>
            <div id="ph-chips"></div>`;
        renderPlaceholder('morpheus');
        expect(document.getElementById('ph-title').textContent).toBe('Morpheus OT Security');
        expect(document.getElementById('ph-desc').textContent).toContain('IEC 62443');
        expect(document.querySelectorAll('#ph-chips .chip')).toHaveLength(3);
    });

    it('a placeholder chip deep-links into the Overview via epms:overview-ask', () => {
        document.body.innerHTML = `
            <div class="view" id="view-overview"></div>
            <div class="view" id="view-placeholder" hidden></div>
            <div id="ph-title"></div><div id="ph-sub"></div>
            <div id="ph-icon"></div><div id="ph-desc"></div>
            <div id="ph-chips"></div>`;
        let asked = null;
        document.addEventListener('epms:overview-ask', (e) => { asked = e.detail.query; });
        renderPlaceholder('gemini');
        document.querySelector('#ph-chips .chip').click();
        expect(asked).toBeTruthy();
    });
});

describe('T2.1 Vector 4c — core/bootstrap.js navigation', () => {
    it('navigateTo shows the placeholder view via the legacy fallback branch', () => {
        document.body.innerHTML = `
            <div class="view" id="view-overview"></div>
            <div class="view" id="view-placeholder" hidden></div>
            <div id="ph-title"></div><div id="ph-sub"></div>
            <div id="ph-icon"></div><div id="ph-desc"></div>
            <div id="ph-chips"></div>`;
        navigateTo('omniverse');
        expect(document.getElementById('view-placeholder').hasAttribute('hidden')).toBe(false);
    });

    it('setupRouter wires nav-item clicks to navigation', () => {
        document.body.innerHTML = `
            <div class="nav-item" data-route="omniverse"></div>
            <div class="view" id="view-overview"></div>
            <div class="view" id="view-placeholder" hidden></div>
            <div id="ph-title"></div><div id="ph-sub"></div>
            <div id="ph-icon"></div><div id="ph-desc"></div>
            <div id="ph-chips"></div>`;
        setupRouter();
        document.querySelector('.nav-item').click();
        expect(document.getElementById('view-placeholder').hasAttribute('hidden')).toBe(false);
    });
});


// ────────────────────────────────────────────────────────────────────
// Release-engineering — single APP_VERSION source-of-truth + stamp
// ────────────────────────────────────────────────────────────────────
describe('Release Engineering — APP_VERSION stamp', () => {
    it('APP_VERSION is a non-empty SemVer-ish string', () => {
        expect(typeof APP_VERSION).toBe('string');
        expect(APP_VERSION).toMatch(/^\d+\.\d+\.\d+(-[A-Za-z0-9.-]+)?$/);
    });

    it('stampAppVersion writes v<APP_VERSION> into every [data-app-version-stamp]', () => {
        document.body.innerHTML = `
            <span data-app-version-stamp>STALE</span>
            <footer><span data-app-version-stamp>ALSO_STALE</span></footer>
        `;
        // Stub fetch so the drift probe doesn't throw during the test.
        const f = vi.fn(async () => ({
            ok: true, json: async () => ({ version: APP_VERSION }),
        }));
        vi.stubGlobal('fetch', f);
        stampAppVersion();
        const stamps = document.querySelectorAll('[data-app-version-stamp]');
        expect(stamps).toHaveLength(2);
        stamps.forEach((el) => {
            expect(el.textContent).toBe(`v${APP_VERSION}`);
        });
        vi.unstubAllGlobals();
    });

    it('drift probe emits a console.warn when backend reports a different version', async () => {
        document.body.innerHTML = '<span data-app-version-stamp>x</span>';
        const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
        const f = vi.fn(async () => ({
            ok: true, json: async () => ({ version: '99.99.99' }),
        }));
        vi.stubGlobal('fetch', f);
        // _stampAppVersion now returns the probe Promise; await it for
        // deterministic flushing (no microtask-count guesswork).
        await stampAppVersion();
        expect(warn).toHaveBeenCalled();
        const msg = warn.mock.calls[0][0];
        expect(msg).toContain('version drift');
        expect(msg).toContain(`v${APP_VERSION}`);
        expect(msg).toContain('v99.99.99');
        warn.mockRestore();
        vi.unstubAllGlobals();
    });

    it('drift probe is silent when backend matches', async () => {
        document.body.innerHTML = '<span data-app-version-stamp>x</span>';
        const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
        const f = vi.fn(async () => ({
            ok: true, json: async () => ({ version: APP_VERSION }),
        }));
        vi.stubGlobal('fetch', f);
        await stampAppVersion();
        // No drift -> no warn.
        const driftCalls = warn.mock.calls.filter(
            (c) => String(c[0] || '').includes('version drift'),
        );
        expect(driftCalls).toHaveLength(0);
        warn.mockRestore();
        vi.unstubAllGlobals();
    });

    it('a fetch failure does not throw — the probe is best-effort', async () => {
        document.body.innerHTML = '<span data-app-version-stamp>x</span>';
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('down'); }));
        // The synchronous stamp must not raise (we never await a
        // rejected promise here — the .catch inside swallows).
        let p;
        expect(() => { p = stampAppVersion(); }).not.toThrow();
        await p;
        expect(document.querySelector('[data-app-version-stamp]').textContent)
            .toBe(`v${APP_VERSION}`);
        vi.unstubAllGlobals();
    });
});
