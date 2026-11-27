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
