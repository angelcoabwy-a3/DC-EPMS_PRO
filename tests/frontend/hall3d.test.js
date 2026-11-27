/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO -- tests/frontend/hall3d.test.js
 * 3D Hall lote 2 (ADR-021): core/hall3d_model.js + views/hall3d.js
 *   - geometry: mm -> m, busway placement per path, tap-offs cover
 *     every rack feed, pipes and CDUs per row;
 *   - the cutaway rack is excluded from the instanced set;
 *   - header numbers come only from the payload; XSS escaped;
 *   - no WebGL (jsdom) -> honest error, no crash;
 *   - vocabulary fence on labels; CSS fence for h3d-* classes.
 * The payload contract on the backend side is in
 * tests/test_design_model.py::test_frontend_contract.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import {
    buildSceneSpec, busways, rackBox, tapOffs, labelIsVocabSafe, MM,
} from '/assets/js/core/hall3d_model.js';
import { __hall3d_test__ as V, initHall3dView } from '/assets/js/views/hall3d.js';
import { isRegistered } from '/assets/js/core/router.js';

const ROOT = resolve(__dirname, '..', '..');
const HOSTILE = '<img src=x onerror=alert(1)>';

// Small synthetic hall in the same shape as GET /api/design/building-d:
// 2 rows x 4 racks, 2 half-row busways per path.
function design(overrides = {}) {
    const rows = [0, 1].map((r) => ({
        id: `D0${r + 1}`, y_mm: r * 2400, section: 1,
        busways: ['a', 'b'].flatMap((p) => [
            { id: `BW-D0${r + 1}-${p.toUpperCase()}1`, path: p, section: `${p.toUpperCase()}1`, racks: [1, 2], x_mm: [0, 1200], z_mm: 3200 },
            { id: `BW-D0${r + 1}-${p.toUpperCase()}2`, path: p, section: `${p.toUpperCase()}1`, racks: [3, 4], x_mm: [1200, 2400], z_mm: 3200 },
        ]),
    }));
    return Object.assign({
        site: 'A3-Alpha Toronto Area', hall: 'DH1',
        dc: { nominal_v: 800, polarity: 'unipolar', earthing: 'TN-S' },
        basis: { it_kw: { value: 1600, unit: 'kW', tag: 'MODEL' } },
        chain: [
            { id: 'row_busways', total: 8, current: { value: 500 }, rating: { value: 630 } },
            { id: 'rack_feeds', current: { value: 250 } },
            { id: 'mv_rectifiers', total: 4 },
            { id: 'cdus', per_row: 3 },
        ],
        layout: { hall: 'DH1', rows, extent_mm: { x: 2400, y: 3600 } },
    }, overrides);
}

function racks() {
    const out = [];
    for (const [r, y] of [['D01', 0], ['D02', 2400]]) {
        for (let i = 0; i < 4; i += 1) {
            const half = i < 2 ? 1 : 2;
            out.push({
                id: `DH1-${r}-0${i + 1}`, row: r, position: i + 1,
                x_mm: i * 600, y_mm: y, w_mm: 600, d_mm: 1200, h_mm: 2300,
                feeds: ['a', 'b'].map((p) => ({ path: p, busway: `BW-${r}-${p.toUpperCase()}${half}` })),
            });
        }
    }
    return out;
}

afterEach(() => {
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
});

describe('hall3d_model geometry', () => {
    it('converts a rack from millimetres to a centred box in metres', () => {
        const b = rackBox(racks()[1]);
        [0.6, 2.3, 1.2].forEach((v, i) => expect(b.size[i]).toBeCloseTo(v));
        expect(b.center[0]).toBeCloseTo(0.9);
        expect(b.center[1]).toBeCloseTo(1.15);
        expect(b.center[2]).toBeCloseTo(0.6);
        expect(MM).toBe(0.001);
    });

    it('puts path A over the front quarter and path B over the rear quarter', () => {
        const bw = busways(design().layout.rows, 1200);
        const a = bw.find((b) => b.id === 'BW-D01-A1');
        const b = bw.find((x) => x.id === 'BW-D01-B1');
        expect(a.z).toBeCloseTo(0.3);
        expect(b.z).toBeCloseTo(0.9);
        expect(a.y).toBeCloseTo(3.2);
        expect(a.length).toBeCloseTo(1.2);
        // first half flows away from x = 0, second half back toward it
        expect(a.flowSign).toBe(1);
        expect(bw.find((x) => x.id === 'BW-D01-A2').flowSign).toBe(-1);
    });

    it('gives every rack feed a tap-off on its own busway', () => {
        const list = racks();
        const bw = busways(design().layout.rows, 1200);
        const taps = tapOffs(list, bw);
        expect(taps).toHaveLength(list.length * 2);
        for (const t of taps) {
            const b = bw.find((x) => x.id === t.busway);
            expect(t.box[0]).toBeGreaterThanOrEqual(b.x0);
            expect(t.box[0]).toBeLessThanOrEqual(b.x1);
            expect(t.drop.y1).toBeGreaterThan(t.drop.y0);
        }
    });

    it('builds the scene: cutaway excluded from the instanced set, pipes and CDUs per row', () => {
        const spec = buildSceneSpec(design(), racks());
        expect(spec.racks).toHaveLength(8);
        expect(spec.detail).toBe('DH1-D01-01');
        expect(spec.instanced).toHaveLength(7);
        expect(spec.instanced.some((r) => r.id === spec.detail)).toBe(false);
        expect(spec.pipes).toHaveLength(4);
        expect(spec.cdus).toHaveLength(6);                 // 3 per row from the chain
        expect(spec.extent[0]).toBeCloseTo(2.4);
        expect(spec.extent[1]).toBeCloseTo(3.6);
    });

    it('survives an empty payload', () => {
        const spec = buildSceneSpec({}, null);
        expect(spec.racks).toEqual([]);
        expect(spec.busways).toEqual([]);
        expect(spec.detail).toBeNull();
    });

    it('vocabulary fence on labels', () => {
        expect(labelIsVocabSafe('dc', '800 VDC busway, path A')).toBe(true);
        expect(labelIsVocabSafe('dc', '800 VDC 3-phase')).toBe(false);
        expect(labelIsVocabSafe('ac', '35 kV 3-phase AC')).toBe(true);
        expect(labelIsVocabSafe('ac', '480 VDC')).toBe(false);
    });
});

describe('hall3d view', () => {
    it('header numbers come from the payload and strings are escaped', () => {
        const html = V.headerHtml(design({ site: HOSTILE }));
        expect(html).toContain('IT 1.6 MW (DESIGN)');
        expect(html).toContain('8 busways, 500 A of 630 A');
        expect(html).toContain('rack feed 250 A at 800 VDC');
        expect(html).toContain('4 MV rectifiers');
        expect(html).not.toContain('<img');
        expect(html).not.toMatch(/phase/i);
    });

    it('boots without WebGL: honest error, no crash', async () => {
        document.body.innerHTML = '<div class="view" id="view-hall-3d"></div>';
        vi.stubGlobal('fetch', vi.fn(async (url) => ({
            ok: true, status: 200,
            json: async () => (String(url).endsWith('/racks') ? { racks: racks() } : design()),
        })));
        await V.boot();
        const root = document.getElementById('view-hall-3d');
        expect(root.textContent).toContain('3D Hall, Building D');
        expect(root.textContent).toContain('schematic');
        expect(root.querySelector('.h3d-error')?.textContent).toMatch(/WebGL/);
    });

    it('reports a failed design fetch', async () => {
        document.body.innerHTML = '<div class="view" id="view-hall-3d"></div>';
        vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 401, json: async () => ({}) })));
        await V.boot();
        expect(document.querySelector('.h3d-error').textContent).toContain('HTTP 401');
    });

    it('registers the route', () => {
        document.body.innerHTML = '<div class="view" id="view-hall-3d"></div>';
        initHall3dView();
        expect(isRegistered('hall-3d')).toBe(true);
    });

    it('every h3d- class used by the view has a CSS rule (S-VISUAL-01)', () => {
        const js = readFileSync(resolve(ROOT, 'frontend/assets/js/views/hall3d.js'), 'utf8');
        const css = readFileSync(resolve(ROOT, 'frontend/assets/app.css'), 'utf8');
        const used = new Set();
        for (const m of js.matchAll(/class="([^"]*)"/g)) {
            for (const c of m[1].split(/\s+/)) if (c.startsWith('h3d-')) used.add(c);
        }
        expect(used.size).toBeGreaterThan(5);
        for (const c of used) expect(css, c).toContain(`.${c}`);
    });
});
