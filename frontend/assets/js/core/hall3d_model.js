/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO -- frontend/assets/js/core/hall3d_model.js
 * 3D Hall track, lote 2 (ADR-021).
 *
 * PURE module: turns the Building D design payload
 * (GET /api/design/building-d + /racks) into a scene specification in
 * metres. No three.js, no DOM, so the geometry is unit-tested.
 *
 * Axes: X along the row (rack position), Z across rows (design y_mm),
 * Y up. Design coordinates are millimetres; everything here is metres.
 *
 * Every number comes from the design model. Elements that are drawn
 * but not specified by the design (tray count inside the cutaway rack,
 * pipe diameters, tap-off boxes) are flagged SCHEMATIC.
 * ════════════════════════════════════════════════════════════════ */

export const MM = 0.001;

/** Visual constants. Not engineering data: used for drawing only. */
export const DRAW = Object.freeze({
    buswaySection: [0.22, 0.12],      // width, height (m), SCHEMATIC
    tapOff: [0.18, 0.16, 0.22],       // SCHEMATIC
    pipeRadius: 0.07,                 // SCHEMATIC
    pipeSupplyY: 2.62,
    pipeReturnY: 2.82,
    cduSize: [0.8, 2.2, 1.2],         // SCHEMATIC
    cduGap: 1.2,                      // from the row end
    trays: 18,                        // SCHEMATIC, not vendor data
});

/** Path colours: both paths are 800 VDC unipolar; B is drawn a shade
 *  cooler so the two busways stay distinguishable. */
export const COLOURS = Object.freeze({
    busway: { a: 0xff2bd6, b: 0xb04dff },
    supply: 0x2f8cff,
    return: 0xff4b3e,
    rack: 0x1b1f24,
    floor: 0xd9dde2,
});

function finite(n, fallback = 0) {
    const v = Number(n);
    return Number.isFinite(v) ? v : fallback;
}

/** Rack box (centre + size) in metres. */
export function rackBox(r) {
    const w = finite(r.w_mm) * MM;
    const d = finite(r.d_mm) * MM;
    const h = finite(r.h_mm) * MM;
    return {
        id: String(r.id),
        row: String(r.row),
        position: finite(r.position),
        center: [finite(r.x_mm) * MM + w / 2, h / 2, finite(r.y_mm) * MM + d / 2],
        size: [w, h, d],
    };
}

/**
 * Busways of every row. Path A runs over the front quarter of the
 * rack depth, path B over the rear quarter. `feedEnd` is the end the
 * section bus enters (x = 0 side for the first half, far end for the
 * second) and sets the direction of the animated flow.
 */
export function busways(rows, rackDepthMm) {
    const d = finite(rackDepthMm) * MM;
    const out = [];
    for (const row of rows || []) {
        const z0 = finite(row.y_mm) * MM;
        for (const b of row.busways || []) {
            const x0 = finite(b.x_mm?.[0]) * MM;
            const x1 = finite(b.x_mm?.[1]) * MM;
            const zc = z0 + (b.path === 'a' ? d * 0.25 : d * 0.75);
            const half = String(b.id).endsWith('1') ? 1 : 2;
            out.push({
                id: String(b.id),
                row: String(row.id),
                path: b.path === 'b' ? 'b' : 'a',
                section: String(b.section),
                racks: b.racks,
                y: finite(b.z_mm) * MM,
                z: zc,
                x0, x1,
                length: Math.max(0, x1 - x0),
                center: [(x0 + x1) / 2, finite(b.z_mm) * MM, zc],
                flowSign: half === 1 ? 1 : -1,
            });
        }
    }
    return out;
}

/** Tap-off box + drop for each rack feed (SCHEMATIC position). */
export function tapOffs(racks, buswayList) {
    const byId = new Map(buswayList.map((b) => [b.id, b]));
    const out = [];
    for (const r of racks || []) {
        const box = rackBox(r);
        for (const f of r.feeds || []) {
            const bw = byId.get(f.busway);
            if (!bw) continue;
            const top = box.size[1];
            out.push({
                rack: box.id, path: bw.path, busway: bw.id,
                box: [box.center[0], bw.y - DRAW.buswaySection[1] / 2 - DRAW.tapOff[1] / 2, bw.z],
                drop: { x: box.center[0], z: bw.z, y0: top, y1: bw.y - DRAW.buswaySection[1] / 2 - DRAW.tapOff[1] },
            });
        }
    }
    return out;
}

/** Supply (blue) and return (red) headers along every row. */
export function pipes(rows, extentXmm, rackDepthMm) {
    const len = finite(extentXmm) * MM;
    const d = finite(rackDepthMm) * MM;
    const out = [];
    for (const row of rows || []) {
        const z = finite(row.y_mm) * MM + d * 0.5;
        out.push({ row: String(row.id), kind: 'supply', x0: 0, x1: len, y: DRAW.pipeSupplyY, z });
        out.push({ row: String(row.id), kind: 'return', x0: 0, x1: len, y: DRAW.pipeReturnY, z });
    }
    return out;
}

/** CDUs per row from the design chain (count = cdus.per_row), placed
 *  past the far row end. */
export function cdus(rows, perRow, extentXmm, rackDepthMm) {
    const n = Math.max(0, Math.floor(finite(perRow)));
    const x0 = finite(extentXmm) * MM + DRAW.cduGap;
    const d = finite(rackDepthMm) * MM;
    const out = [];
    for (const row of rows || []) {
        for (let i = 0; i < n; i += 1) {
            out.push({
                row: String(row.id), index: i + 1,
                center: [x0 + DRAW.cduSize[0] / 2 + i * (DRAW.cduSize[0] + 0.2),
                    DRAW.cduSize[1] / 2, finite(row.y_mm) * MM + d / 2],
            });
        }
    }
    return out;
}

/** Pick a chain entry by id. */
export function chainEntry(design, id) {
    return (design?.chain || []).find((c) => c.id === id) || null;
}

/**
 * Whole scene spec. `detailId` is the rack drawn as a cutaway (the
 * others are instanced). Defaults to the first rack of the first row.
 */
export function buildSceneSpec(design, racks, detailId = null) {
    const layout = design?.layout || {};
    const rows = layout.rows || [];
    const list = Array.isArray(racks) ? racks : [];
    const depth = list[0]?.d_mm ?? 1200;
    const ext = layout.extent_mm || { x: 0, y: 0 };
    const bw = busways(rows, depth);
    const cduEntry = chainEntry(design, 'cdus');
    const detail = detailId || list[0]?.id || null;
    const boxes = list.map(rackBox);
    return {
        hall: layout.hall || '',
        extent: [finite(ext.x) * MM, finite(ext.y) * MM],
        racks: boxes,
        detail,
        instanced: boxes.filter((b) => b.id !== detail),
        busways: bw,
        tapOffs: tapOffs(list, bw),
        pipes: pipes(rows, ext.x, depth),
        cdus: cdus(rows, cduEntry?.per_row ?? 0, ext.x, depth),
        center: [finite(ext.x) * MM / 2, 0, finite(ext.y) * MM / 2],
    };
}

/** Vocabulary fence (S-VOCAB-01): labels shown on DC objects never
 *  mention phases; AC objects never say VDC. */
export function labelIsVocabSafe(domain, text) {
    const t = String(text || '').toLowerCase();
    if (domain === 'dc') return !/phase|trif/.test(t);
    if (domain === 'ac') return !/vdc/.test(t);
    return true;
}

// ════════════════════════════════════════════════════════════════
//  Lote 3: live data, quality governor, camera tour, callouts.
//  Still pure: no three.js, no DOM.
// ════════════════════════════════════════════════════════════════

/** Simulator channels for Building D ('<asset>:<metric>' keys), one
 *  set per 2N path (DC-EPMS-076). Each path is one rectifier group, one
 *  SSCB, one DC bus and one BESS node aggregating the design model. */
export const LIVE_KEYS = Object.freeze({
    busV: 'main_bus_dc_d:voltage_v_dc_bus',
    rectMw: 'mv_rectifier_d:rect_load_mw',
    rectEff: 'mv_rectifier_d:rect_efficiency_ratio',
    sscbC: 'sscb_d_01:sscb_junction_T_c',
    bessSoc: 'bess_d_01:bess_soc_pct',
    bessA: 'bess_d_01:bess_dc_current_a',
    busVB: 'main_bus_dc_d_b:voltage_v_dc_bus',
    rectMwB: 'mv_rectifier_d_b:rect_load_mw',
    rectEffB: 'mv_rectifier_d_b:rect_efficiency_ratio',
    sscbCB: 'sscb_d_b_01:sscb_junction_T_c',
    bessSocB: 'bess_d_b_01:bess_soc_pct',
    bessAB: 'bess_d_b_01:bess_dc_current_a',
});

function _emission(channels, key) {
    const ch = channels?.[key];
    const v = ch && typeof ch === 'object' ? ch.last_emission : undefined;
    return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

/** Pick the Building D live values out of the channel map. */
export function liveFromChannels(channels) {
    const out = {};
    for (const [k, key] of Object.entries(LIVE_KEYS)) out[k] = _emission(channels, key);
    out.any = Object.values(out).some((v) => v !== null);
    return out;
}

/**
 * Values derived from live + design. Per-rack load is MODEL: rectifier
 * load spread evenly over the racks (no per-rack telemetry exists).
 * Bus band uses the design limits (640 V min continuous, 840 V limit).
 */
export function derivedLive(live, design) {
    const racks = finite(design?.rack_count, 0);
    const nominal = finite(design?.dc?.nominal_v, 800);
    const vmin = finite(design?.dc?.min_continuous_v, 640);
    const vmax = finite(design?.dc?.overvoltage_limit_v, 840);
    const out = { rackKw: null, rackA: null, band: 'unknown', bandA: 'unknown', bandB: 'unknown', flowScale: 1, hallMw: null };
    // Hall load = both paths' rectifier groups (2N); either may be absent.
    const parts = [live?.rectMw, live?.rectMwB].filter((v) => v !== null && v !== undefined);
    if (parts.length && racks > 0) {
        out.hallMw = parts.reduce((a, b) => a + b, 0);
        out.rackKw = (out.hallMw * 1000) / racks;
        const vs = [live.busV, live.busVB].filter((v) => v !== null && v !== undefined);
        const v = vs.length ? vs.reduce((a, b) => a + b, 0) / vs.length : nominal;
        out.rackA = v > 0 ? (out.rackKw * 1000) / v : null;
        const itMw = finite(design?.basis?.it_kw?.value, 0) / 1000;
        out.flowScale = itMw > 0 ? Math.max(0.1, Math.min(2, out.hallMw / itMw)) : 1;
    }
    const band = (v) => {
        if (v === null || v === undefined) return 'unknown';
        if (v >= vmax) return 'over';
        if (v < vmin) return 'under';
        if (Math.abs(v - nominal) / nominal > 0.02) return 'off-nominal';
        return 'normal';
    };
    out.bandA = band(live?.busV);
    out.bandB = band(live?.busVB);
    const rank = { unknown: 0, normal: 1, 'off-nominal': 2, under: 3, over: 3 };
    out.band = rank[out.bandB] > rank[out.bandA] ? out.bandB : out.bandA;
    return out;
}

/**
 * Quality governor. Levels: 2 = bloom + pixel ratio 1.5, 1 = no bloom,
 * 0 = no bloom + pixel ratio 1. Drops one level after `need` consecutive
 * one-second samples under `floor` fps. Never climbs back on its own
 * (no oscillation); the operator can raise it by hand.
 */
export function governQuality(state, fps, floor = 30, need = 2) {
    const s = { level: state?.level ?? 2, low: state?.low ?? 0, manual: !!state?.manual };
    if (s.manual || !Number.isFinite(fps)) return s;
    s.low = fps < floor ? s.low + 1 : 0;
    if (s.low >= need && s.level > 0) { s.level -= 1; s.low = 0; }
    return s;
}

export function qualitySettings(level) {
    if (level >= 2) return { bloom: true, pixelRatio: 1.5, label: 'HIGH' };
    if (level === 1) return { bloom: false, pixelRatio: 1.5, label: 'MEDIUM' };
    return { bloom: false, pixelRatio: 1.0, label: 'LOW' };
}

/** Camera tour keyframes [{pos, target}] in metres, from the spec. */
export function tourKeyframes(spec) {
    const [ex, ez] = spec?.extent || [0, 0];
    const d = spec?.racks?.find((r) => r.id === spec.detail);
    const dc = d ? d.center : [0, 1.15, 0.6];
    return [
        { pos: [-8, 12, -10], target: [ex / 2, 0, ez / 2] },
        { pos: [-3, 5, -5], target: [ex * 0.3, 2.4, 1] },
        { pos: [dc[0] - 1.2, 3.4, dc[2] - 2.2], target: [dc[0] + 3, 3.0, dc[2]] },
        // home: three-quarter view of the first row, all callouts in frame
        { pos: [dc[0] - 4.3, 4.4, dc[2] - 6.6], target: [dc[0] + 3.7, 2.0, dc[2] + 0.3] },
    ];
}

/** Smoothstep easing on [0, 1]. */
export function ease(t) {
    const x = Math.max(0, Math.min(1, t));
    return x * x * (3 - 2 * x);
}

function _fmt(v, digits = 0) {
    return Number.isFinite(v) ? v.toLocaleString('en-US', { maximumFractionDigits: digits, minimumFractionDigits: digits }) : '-';
}

/**
 * Three callouts with leader lines. Text comes from the design payload
 * (DESIGN / MODEL) and the simulator (LIVE). Anchors in metres; the view
 * places the labels in a screen lane (laneLayout) and draws the lines.
 */
export function callouts(spec, design, live) {
    const bw = chainEntry(design, 'row_busways');
    const feed = chainEntry(design, 'rack_feeds');
    const cdu = chainEntry(design, 'cdus');
    const rack = chainEntry(design, 'racks');
    const vNom = finite(design?.dc?.nominal_v, 800);
    const b0 = spec?.busways?.find((b) => b.id.endsWith('-A1')) || spec?.busways?.[0];
    const d = spec?.racks?.find((r) => r.id === spec.detail);
    const p0 = spec?.pipes?.find((p) => p.kind === 'supply');
    const val = (e, k) => (e?.[k] && typeof e[k] === 'object' ? e[k].value : null);
    const out = [];
    if (b0) {
        out.push({
            id: 'busway', domain: 'dc',
            anchor: [b0.x0 + Math.min(4, b0.length / 2), b0.y, b0.z],
            title: `${vNom} VDC BUSWAY (UNIPOLAR TN-S)`,
            lines: [
                `${b0.id} · ${b0.racks?.[1] - b0.racks?.[0] + 1} racks`,
                `${_fmt(val(bw, 'current'))} A of ${_fmt(val(bw, 'rating'))} A rating (MODEL)`,
                live?.busV !== null && live?.busV !== undefined
                    ? `bus ${_fmt(live.busV, 1)} V (LIVE, simulator)` : 'bus voltage: no live data',
                ...(live?.whatIf?.tripped ? [`what-if: path ${live.whatIf.tripped.toUpperCase()} tripped, `
                    + `this busway ${live.whatIf.tripped === b0.path ? 'dead' : `at ${Math.round((live.whatIf.paths[b0.path].utilisation ?? 0) * 100)} %`}`] : []),
            ],
        });
    }
    if (d) {
        out.push({
            id: 'rack', domain: 'dc',
            anchor: [d.center[0], d.size[1], d.center[2]],
            title: String(rack?.label || 'AI rack').toUpperCase(),
            lines: [
                `load ${_fmt(val(rack, 'unit'))} kW (DESIGN)`,
                `${vNom} VDC · ${_fmt(val(feed, 'current'), 0)} A per feed at full load (MODEL)`,
                live?.rackKw !== null && live?.rackKw !== undefined
                    ? `now ~${_fmt(live.rackKw, 0)} kW, ${_fmt(live.rackA, 0)} A (MODEL from LIVE)` : 'no live load',
            ],
        });
    }
    if (p0) {
        out.push({
            id: 'cooling', domain: 'liquid',
            anchor: [Math.min(6, p0.x1 / 2), p0.y, p0.z - 0.18],
            title: 'DIRECT LIQUID COOLING',
            lines: [
                `${_fmt(val(cdu, 'rack_flow'), 1)} L/min per rack (MODEL)`,
                `${_fmt(val(cdu, 'row_flow'))} L/min per row · ${cdu?.per_row ?? '-'} CDUs per row`,
                'supply 18 C · return 45 C max (DESIGN)',
            ],
        });
    }
    return out;
}

/**
 * Screen lane for the callout labels: stacked on the left edge, below
 * the legend, so they never cover the HUD, live or rack panels.
 * Returns the top (px) of each label.
 */
export function laneLayout(heights, stageH, top = 140, gap = 10) {
    const out = [];
    let y = Math.max(top, 0);
    for (const h of heights) {
        out.push(Math.min(y, Math.max(0, stageH - h - 40)));
        y += h + gap;
    }
    return out;
}

/** Projected point (NDC from three.js) to stage pixels; null if the
 *  point is behind the camera or outside the frame. */
export function ndcToStage(ndc, w, h) {
    if (!ndc || ndc.z > 1 || ndc.z < -1 || Math.abs(ndc.x) > 1.05 || Math.abs(ndc.y) > 1.05) return null;
    return [((ndc.x + 1) / 2) * w, ((1 - ndc.y) / 2) * h];
}

// ════════════════════════════════════════════════════════════════
//  Lote 5: 2N path what-if (sandbox, local, never sent anywhere).
// ════════════════════════════════════════════════════════════════

export const WHATIF_CYCLE = Object.freeze([null, 'a', 'b']);

/**
 * Per-path busway loading with one path tripped (or none). Each rack
 * draws its current half from each path in normal 2N; with a path
 * tripped the other carries all of it. Rack current = live MODEL value
 * when available, otherwise the design full-load feed current.
 * Busway current = racks on the busway x rack current x share.
 */
export function pathScenario(design, live, tripped = null) {
    const bw = chainEntry(design, 'row_busways');
    const feed = chainEntry(design, 'rack_feeds');
    const val = (e, k) => (e?.[k] && typeof e[k] === 'object' ? Number(e[k].value) : null);
    const rating = val(bw, 'rating');
    const racksPerBusway = Number(bw?.racks) || 0;
    const liveA = Number.isFinite(live?.rackA) ? live.rackA : null;
    const rackA = liveA ?? val(feed, 'current');
    const source = liveA !== null ? 'MODEL from LIVE' : 'DESIGN full load';
    const out = { tripped: tripped === 'a' || tripped === 'b' ? tripped : null, source, paths: {} };
    for (const p of ['a', 'b']) {
        let share = 0.5;
        let state = 'normal';
        if (out.tripped === p) { share = 0; state = 'tripped'; }
        else if (out.tripped) { share = 1; state = 'carrying'; }
        const current = rackA !== null ? racksPerBusway * rackA * share : null;
        out.paths[p] = {
            state, share, current,
            rating,
            utilisation: current !== null && rating ? current / rating : null,
        };
    }
    const worst = Math.max(...['a', 'b'].map((p) => out.paths[p].utilisation ?? 0));
    out.ok = worst <= 0.8 + 1e-9;           // continuous loading rule (ADR-021)
    return out;
}

export function whatIfText(sc) {
    if (!sc?.tripped) return '';
    const other = sc.tripped === 'a' ? 'b' : 'a';
    const p = sc.paths[other];
    const pct = p.utilisation !== null ? Math.round(p.utilisation * 100) : null;
    const amps = Number.isFinite(p.current) ? Math.round(p.current).toLocaleString('en-US') : '-';
    return `WHAT-IF (sandbox): path ${sc.tripped.toUpperCase()} tripped. Path ${other.toUpperCase()} `
        + `busways carry ${amps} A of ${Number(p.rating).toLocaleString('en-US')} A`
        + (pct !== null ? ` (${pct} %)` : '') + `, ${sc.source}. `
        + (sc.ok ? 'Within the 80 % continuous rule.' : 'ABOVE the 80 % continuous rule.');
}
