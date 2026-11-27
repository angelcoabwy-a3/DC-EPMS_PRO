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
    liveFromChannels, derivedLive, governQuality, qualitySettings,
    tourKeyframes, ease, callouts, laneLayout, ndcToStage, LIVE_KEYS,
    pathScenario, whatIfText, WHATIF_CYCLE,
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
        site: 'A3-Alpha Toronto Area', hall: 'DH1', rack_count: 8,
        dc: { nominal_v: 800, polarity: 'unipolar', earthing: 'TN-S', min_continuous_v: 640, overvoltage_limit_v: 840 },
        basis: { it_kw: { value: 1600, unit: 'kW', tag: 'MODEL' } },
        chain: [
            { id: 'row_busways', total: 8, racks: 2, current: { value: 500 }, rating: { value: 630 } },
            { id: 'rack_feeds', current: { value: 250 } },
            { id: 'mv_rectifiers', total: 4 },
            { id: 'cdus', per_row: 3, rack_flow: { value: 111.7 }, row_flow: { value: 447 } },
            { id: 'racks', label: 'NVIDIA GB300 NVL144', unit: { value: 200 } },
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

function channels(over = {}) {
    const base = {
        [LIVE_KEYS.busV]: 799.6, [LIVE_KEYS.rectMw]: 1.5, [LIVE_KEYS.rectEff]: 0.982,
        [LIVE_KEYS.sscbC]: 55.1, [LIVE_KEYS.bessSoc]: 85, [LIVE_KEYS.bessA]: -0.2,
    };
    const all = { ...base, ...over };
    return Object.fromEntries(Object.entries(all).map(([k, v]) => [k, { last_emission: v }]));
}

describe('hall3d lote 3: live, governor, tour, callouts', () => {
    it('reads the Building D simulator channels and ignores junk', () => {
        const live = liveFromChannels(channels());
        expect(live.busV).toBe(799.6);
        expect(live.rectMw).toBe(1.5);
        expect(live.any).toBe(true);
        expect(liveFromChannels({ [LIVE_KEYS.busV]: { last_emission: 'x' } }).any).toBe(false);
        expect(liveFromChannels(undefined).any).toBe(false);
    });

    it('2N: hall load sums both paths, band is the worse of the two buses', () => {
        const live = liveFromChannels(channels({
            [LIVE_KEYS.rectMwB]: 1.5, [LIVE_KEYS.busVB]: 770,
        }));
        const d = derivedLive(live, design());
        expect(d.hallMw).toBeCloseTo(3.0);
        expect(d.rackKw).toBeCloseTo(375);              // 3.0 MW / 8 racks
        expect(d.bandA).toBe('normal');
        expect(d.bandB).toBe('off-nominal');
        expect(d.band).toBe('off-nominal');
        const html = V.livePanelHtml(live, d);
        expect(html).toContain('A 799.6 · B 770.0 V');
        expect(html).toContain('Hall load (A + B)');
    });

    it('derives per-rack MODEL load and the bus band from the design limits', () => {
        const d = derivedLive(liveFromChannels(channels()), design());
        expect(d.rackKw).toBeCloseTo(187.5);               // 1.5 MW / 8 racks
        expect(d.rackA).toBeCloseTo(187500 / 799.6);
        expect(d.band).toBe('normal');
        expect(derivedLive(liveFromChannels(channels({ [LIVE_KEYS.busV]: 630 })), design()).band).toBe('under');
        expect(derivedLive(liveFromChannels(channels({ [LIVE_KEYS.busV]: 845 })), design()).band).toBe('over');
        expect(derivedLive(liveFromChannels(channels({ [LIVE_KEYS.busV]: 770 })), design()).band).toBe('off-nominal');
        expect(derivedLive(liveFromChannels({}), design())).toMatchObject({ rackKw: null, band: 'unknown' });
    });

    it('quality governor steps down after two slow seconds and never oscillates up', () => {
        let q = { level: 2, low: 0 };
        q = governQuality(q, 25);
        expect(q.level).toBe(2);
        q = governQuality(q, 25);
        expect(q.level).toBe(1);
        q = governQuality(q, 60);
        q = governQuality(q, 60);
        expect(q.level).toBe(1);
        q = governQuality(governQuality(q, 10), 10);
        expect(q.level).toBe(0);
        expect(governQuality(governQuality(q, 5), 5).level).toBe(0);
        expect(governQuality({ level: 2, manual: true }, 5).level).toBe(2);
        expect(qualitySettings(2)).toMatchObject({ bloom: true, pixelRatio: 1.5 });
        expect(qualitySettings(0)).toMatchObject({ bloom: false, pixelRatio: 1 });
    });

    it('tour ends on the home view and easing is clamped', () => {
        const keys = tourKeyframes(buildSceneSpec(design(), racks()));
        expect(keys.length).toBeGreaterThanOrEqual(3);
        for (const k of keys) expect(k.pos[1]).toBeGreaterThan(0);
        expect(ease(-1)).toBe(0);
        expect(ease(2)).toBe(1);
        expect(ease(0.5)).toBeCloseTo(0.5);
    });

    it('three callouts, numbers from design and live, vocabulary-safe', () => {
        const spec = buildSceneSpec(design(), racks());
        const d = derivedLive(liveFromChannels(channels()), design());
        const cs = callouts(spec, design(), { ...liveFromChannels(channels()), rackKw: d.rackKw, rackA: d.rackA });
        expect(cs.map((c) => c.id)).toEqual(['busway', 'rack', 'cooling']);
        const text = (c) => [c.title, ...c.lines].join(' | ');
        expect(text(cs[0])).toContain('800 VDC BUSWAY (UNIPOLAR TN-S)');
        expect(text(cs[0])).toContain('500 A of 630 A rating (MODEL)');
        expect(text(cs[0])).toContain('bus 799.6 V (LIVE, simulator)');
        expect(text(cs[1])).toContain('load 200 kW (DESIGN)');
        expect(text(cs[1])).toContain('~188 kW');
        expect(text(cs[2])).toContain('111.7 L/min per rack (MODEL)');
        for (const c of cs) expect(labelIsVocabSafe(c.domain, text(c))).toBe(true);
        const none = callouts(spec, design(), {});
        expect(none[0].lines.join(' ')).toContain('no live data');
    });

    it('lane layout stacks labels and keeps them inside the stage', () => {
        expect(laneLayout([60, 70, 60], 800)).toEqual([140, 210, 290]);
        const tight = laneLayout([60, 70, 60], 300);
        for (const y of tight) expect(y).toBeLessThanOrEqual(300 - 60);
        expect(ndcToStage({ x: 0, y: 0, z: 0.5 }, 1000, 500)).toEqual([500, 250]);
        expect(ndcToStage({ x: 0, y: 0, z: 1.5 }, 1000, 500)).toBeNull();
        expect(ndcToStage({ x: 1.4, y: 0, z: 0.5 }, 1000, 500)).toBeNull();
    });

    it('live panel: honest empty state, escaped values, no negative zero', () => {
        expect(V.livePanelHtml({ any: false }, null)).toContain('No Building D channels yet');
        const live = liveFromChannels(channels({ [LIVE_KEYS.bessA]: -0.2 }));
        const html = V.livePanelHtml(live, derivedLive(live, design()));
        expect(html).toContain('A 799.6 · B - V');         // path B absent in this fixture
        expect(html).toContain('data-band="normal"');
        expect(html).not.toContain('-0 A');
        expect(html).toContain('LIVE (simulator)');
    });
});

describe('hall3d lote 5: 2N path what-if', () => {
    it('normal 2N: each path carries half of every rack', () => {
        const sc = pathScenario(design(), null, null);
        expect(sc.tripped).toBeNull();
        expect(sc.paths.a).toMatchObject({ state: 'normal', share: 0.5, current: 250, rating: 630 });
        expect(sc.paths.b.current).toBe(250);
        expect(sc.source).toBe('DESIGN full load');
        expect(sc.ok).toBe(true);
        expect(whatIfText(sc)).toBe('');
    });

    it('path A tripped: B carries the whole rack current, A goes dead', () => {
        const sc = pathScenario(design(), null, 'a');
        expect(sc.paths.a).toMatchObject({ state: 'tripped', share: 0, current: 0 });
        expect(sc.paths.b).toMatchObject({ state: 'carrying', share: 1, current: 500 });
        expect(sc.paths.b.utilisation).toBeCloseTo(500 / 630);
        expect(sc.ok).toBe(true);                       // 79 % <= 80 %
        expect(whatIfText(sc)).toContain('path A tripped. Path B busways carry 500 A of 630 A (79 %)');
    });

    it('uses the live MODEL rack current when present and flags the 80 % rule', () => {
        const sc = pathScenario(design(), { rackA: 270 }, 'b');
        expect(sc.source).toBe('MODEL from LIVE');
        expect(sc.paths.a.current).toBe(540);
        expect(sc.ok).toBe(false);                      // 86 % > 80 %
        expect(whatIfText(sc)).toContain('ABOVE the 80 % continuous rule');
    });

    it('ignores an unknown path and cycles normal -> A -> B', () => {
        expect(pathScenario(design(), null, 'c').tripped).toBeNull();
        expect(WHATIF_CYCLE).toEqual([null, 'a', 'b']);
    });

    it('busway callout reports the what-if', () => {
        const spec = buildSceneSpec(design(), racks());
        const live = { whatIf: pathScenario(design(), null, 'a') };
        const bus = callouts(spec, design(), live).find((c) => c.id === 'busway');
        expect(bus.lines.join(' ')).toContain('what-if: path A tripped, this busway dead');
        const liveB = { whatIf: pathScenario(design(), null, 'b') };
        expect(callouts(spec, design(), liveB)[0].lines.join(' ')).toContain('this busway at 79 %');
    });
});
