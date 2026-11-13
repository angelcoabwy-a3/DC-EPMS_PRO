/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO -- tests/frontend/usd_export.test.js
 * Release R2-C -- views/usd_export.js
 *   - Honest scope is always printed (schematic, no live-link).
 *   - Download is a plain same-origin link to the read-only API.
 *   - XSS on every server-supplied string (S-SEC-01).
 *   - Error postures; one fetch per activation, no polling.
 *   - S-VISUAL-01 fence: every usdx-* class has a CSS rule.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { __usd_export_test__ as V, initUsdExportView } from '/assets/js/views/usd_export.js';
import { isRegistered } from '/assets/js/core/router.js';

const ROOT = resolve(__dirname, '..', '..');
const HOSTILE = '<img src=x onerror=alert(1)>';

function summary(overrides = {}) {
    return Object.assign({
        site_id: 'a3-alpha-toronto', site_name: 'A3-Alpha Toronto Area',
        filename: 'a3-alpha-toronto.usda',
        component_count: 113, building_count: 5, unplaced_component_count: 22,
        power_edge_count: 54, cooling_edge_count: 24,
        components_by_type: { it_rack: 50, ups: 2, rpp: 6, chiller: 3 },
        layout: 'schematic',
        notice: 'SCHEMATIC layout generated from config/site_model.yml.',
    }, overrides);
}

function mount() {
    document.body.innerHTML = '<div class="view" id="view-usd-export"></div>';
    return document.getElementById('view-usd-export');
}

afterEach(() => {
    V.reset();
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
});

describe('R2-C -- renderSummary', () => {
    it('prints the schematic notice and the no-live-link statement', () => {
        const root = mount();
        root.innerHTML = V.renderSummary(summary());
        const notice = root.querySelector('.usdx-notice').textContent;
        expect(notice).toContain('SCHEMATIC layout');
        expect(notice).toContain('No Omniverse live-link exists');
        expect(root.textContent).toContain('Real coordinates. The site model has none');
    });

    it('shows the four counts', () => {
        const root = mount();
        root.innerHTML = V.renderSummary(summary());
        const vals = [...root.querySelectorAll('.usdx-tile-val')].map((e) => e.textContent);
        expect(vals).toEqual(['113', '5', '54', '24']);
    });

    it('offers a plain same-origin download link with the server filename', () => {
        const root = mount();
        root.innerHTML = V.renderSummary(summary());
        const a = root.querySelector('a.usdx-download');
        expect(a.getAttribute('href')).toBe('/api/site/usd');
        expect(a.getAttribute('download')).toBe('a3-alpha-toronto.usda');
        expect(a.textContent).toBe('Download a3-alpha-toronto.usda');
    });

    it('mentions unplaced components only when there are some', () => {
        const root = mount();
        root.innerHTML = V.renderSummary(summary());
        expect(root.querySelector('.usdx-note').textContent).toContain('22 component(s)');
        root.innerHTML = V.renderSummary(summary({ unplaced_component_count: 0 }));
        expect(root.querySelector('.usdx-note')).toBeNull();
    });

    it('sorts asset types by count, then name', () => {
        const root = mount();
        root.innerHTML = `<table><tbody>${V.renderTypes({ ups: 2, it_rack: 50, ats: 2, rpp: 6 })}</tbody></table>`;
        const names = [...root.querySelectorAll('td.usdx-mono')].map((e) => e.textContent);
        expect(names).toEqual(['it_rack', 'rpp', 'ats', 'ups']);
    });

    it('degrades on a missing or malformed summary', () => {
        expect(() => V.renderSummary(null)).not.toThrow();
        expect(() => V.renderSummary({})).not.toThrow();
        const root = mount();
        root.innerHTML = V.renderSummary({ component_count: 'abc' });
        expect(root.querySelector('.usdx-tile-val').textContent).toBe('0');
        expect(root.querySelector('a.usdx-download').getAttribute('download')).toBe('site.usda');
        expect(V.renderTypes(null)).toContain('No components.');
    });
});

describe('R2-C -- XSS gate (S-SEC-01)', () => {
    it('escapes server-supplied strings, including the download attribute', () => {
        const root = mount();
        root.innerHTML = V.renderSummary(summary({
            notice: HOSTILE,
            filename: 'x" onclick="alert(1)',
            components_by_type: { [HOSTILE]: 1 },
        }));
        expect(root.querySelector('img')).toBeNull();
        expect(root.querySelector('[onerror]')).toBeNull();
        const a = root.querySelector('a.usdx-download');
        expect(a.hasAttribute('onclick')).toBe(false);
        expect(a.getAttribute('download')).toBe('x" onclick="alert(1)');
        expect(a.getAttribute('href')).toBe('/api/site/usd');
    });
});

describe('R2-C -- lifecycle', () => {
    it('registers the usd-export route once', () => {
        initUsdExportView();
        initUsdExportView();
        expect(isRegistered('usd-export')).toBe(true);
    });

    it('fetches the summary once and renders it', async () => {
        const root = mount();
        const spy = vi.fn(async () => ({ ok: true, status: 200, json: async () => summary() }));
        vi.stubGlobal('fetch', spy);
        await V.refresh();
        expect(spy).toHaveBeenCalledTimes(1);
        expect(spy.mock.calls[0][0]).toBe('/api/site/usd/summary');
        expect(root.querySelector('h2').textContent).toContain('USD Export');
        expect(root.querySelector('a.usdx-download')).not.toBeNull();
    });

    it.each([
        [async () => ({ ok: false, status: 503, json: async () => ({}) }), 'HTTP 503'],
        [async () => { throw new Error('offline'); }, 'unreachable'],
        [async () => ({ ok: true, status: 200, json: async () => { throw new Error('bad'); } }), 'could not be parsed'],
    ])('shows an explicit error posture %#', async (impl, text) => {
        const root = mount();
        vi.stubGlobal('fetch', vi.fn(impl));
        await V.refresh();
        expect(root.querySelector('.usdx-error').textContent).toContain(text);
        expect(root.querySelector('a.usdx-download')).toBeNull();
    });
});

describe('R2-C -- S-VISUAL-01 fence + wiring', () => {
    it('every usdx-* class the view emits has a CSS rule', () => {
        const css = readFileSync(resolve(ROOT, 'frontend/assets/app.css'), 'utf8');
        const defined = new Set([...css.matchAll(/\.([A-Za-z_][\w-]*)/g)].map((m) => m[1]));
        const src = readFileSync(resolve(ROOT, 'frontend/assets/js/views/usd_export.js'), 'utf8');
        const emitted = new Set();
        for (const m of src.matchAll(/class\s*=\s*["']([^"'<>{}]+)["']/g)) {
            for (const t of m[1].split(/\s+/)) if (/^usdx-[\w-]+$/.test(t)) emitted.add(t);
        }
        expect(emitted.size).toBeGreaterThanOrEqual(15);
        expect([...emitted].filter((c) => !defined.has(c)).sort()).toEqual([]);
    });

    it('index.html mounts the view and main.js initialises it', () => {
        const html = readFileSync(resolve(ROOT, 'frontend/index.html'), 'utf8');
        expect(html).toContain('<div class="view" id="view-usd-export" hidden></div>');
        expect(html).toContain('data-route="usd-export"');
        const main = readFileSync(resolve(ROOT, 'frontend/assets/js/main.js'), 'utf8');
        expect(main).toContain('initUsdExportView();');
    });
});
