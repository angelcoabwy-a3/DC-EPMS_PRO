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

const { MODULES, navigateTo, renderPlaceholder, setupRouter } = __bootstrap_test__;

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
