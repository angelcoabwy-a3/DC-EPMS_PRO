/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/mobile_nav.test.js
 * DC-EPMS-064: phone layout drawer (iPhone 16 / 17 Pro Max, 440 px).
 * Behaviour of core/mobile_nav.js + structural fences on index.html
 * and app.css so the phone layout cannot silently regress.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import {
    initMobileNav, setNavOpen, isNavOpen, MOBILE_QUERY, __mobile_nav_test__,
} from '/assets/js/core/mobile_nav.js';

const ROOT = resolve(__dirname, '../..');
const HTML = readFileSync(resolve(ROOT, 'frontend/index.html'), 'utf8');
const CSS = readFileSync(resolve(ROOT, 'frontend/assets/app.css'), 'utf8');

function mountShell() {
    document.body.innerHTML = `
      <div class="app-shell">
        <header class="app-header">
          <button id="nav-toggle" aria-expanded="false" aria-label="Open navigation"></button>
        </header>
        <main class="app-main">
          <div class="nav-backdrop" id="nav-backdrop"></div>
          <nav class="panel-nav" id="app-nav">
            <div class="nav-item active" data-route="overview">Overview</div>
            <div class="nav-item" data-route="device-control">Power Controls</div>
          </nav>
        </main>
      </div>`;
}

beforeEach(() => {
    __mobile_nav_test__.reset();
    mountShell();
    initMobileNav();
});

afterEach(() => { document.body.innerHTML = ''; });

describe('DC-EPMS-064 — drawer state', () => {
    it('starts closed and the toggle opens it with aria-expanded', () => {
        const btn = document.getElementById('nav-toggle');
        expect(isNavOpen()).toBe(false);
        btn.click();
        expect(isNavOpen()).toBe(true);
        expect(btn.getAttribute('aria-expanded')).toBe('true');
        expect(btn.getAttribute('aria-label')).toBe('Close navigation');
        btn.click();
        expect(isNavOpen()).toBe(false);
        expect(btn.getAttribute('aria-expanded')).toBe('false');
    });

    it('choosing a view closes the drawer', () => {
        setNavOpen(true);
        document.querySelector('[data-route="device-control"]').click();
        expect(isNavOpen()).toBe(false);
    });

    it('tapping the backdrop closes the drawer', () => {
        setNavOpen(true);
        document.getElementById('nav-backdrop').click();
        expect(isNavOpen()).toBe(false);
    });

    it('Escape closes the drawer and returns focus to the toggle', () => {
        setNavOpen(true);
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
        expect(isNavOpen()).toBe(false);
        expect(document.activeElement.id).toBe('nav-toggle');
    });

    it('nav items become keyboard operable (tabindex, role, Enter)', () => {
        const item = document.querySelector('[data-route="device-control"]');
        expect(item.getAttribute('tabindex')).toBe('0');
        expect(item.getAttribute('role')).toBe('button');
        let clicked = false;
        item.addEventListener('click', () => { clicked = true; });
        item.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        expect(clicked).toBe(true);
    });

    it('init is idempotent (a second call does not double-toggle)', () => {
        initMobileNav();
        document.getElementById('nav-toggle').click();
        expect(isNavOpen()).toBe(true);
    });
});

describe('DC-EPMS-064 — structural fences', () => {
    it('declares the standard web-app tag next to the apple- one (no Chrome deprecation warning)', () => {
        const std = HTML.indexOf('<meta name="mobile-web-app-capable" content="yes">');
        const apple = HTML.indexOf('<meta name="apple-mobile-web-app-capable" content="yes">');
        expect(std).toBeGreaterThan(-1);
        expect(apple).toBeGreaterThan(-1);
    });

    it('viewport meta covers the notch / Dynamic Island (viewport-fit=cover)', () => {
        expect(HTML).toMatch(/name="viewport"[^>]*viewport-fit=cover/);
    });

    it('index.html carries the toggle, backdrop and labelled nav', () => {
        expect(HTML).toMatch(/id="nav-toggle"[^>]*aria-controls="app-nav"/);
        expect(HTML).toContain('id="nav-backdrop"');
        expect(HTML).toMatch(/<nav class="panel-nav" id="app-nav" aria-label="Views">/);
    });

    it('app.css has the phone block with the same breakpoint as the JS', () => {
        const bp = MOBILE_QUERY.match(/max-width:\s*(\d+)px/)[1];
        expect(CSS).toContain(`@media (max-width: ${bp}px) {`);
        expect(CSS).toContain('.app-shell.nav-open .panel-nav');
    });

    it('safe-area insets, dynamic viewport height and 16 px inputs are present', () => {
        expect(CSS).toContain('env(safe-area-inset-top)');
        expect(CSS).toContain('env(safe-area-inset-bottom)');
        expect(CSS).toContain('100dvh');
        expect(CSS).toMatch(/input, select, textarea \{ font-size: 16px; \}/);
    });

    it('pinch zoom is not disabled (WCAG 1.4.4)', () => {
        expect(HTML).not.toMatch(/user-scalable\s*=\s*no/);
        expect(HTML).not.toMatch(/maximum-scale\s*=\s*1/);
    });
});
