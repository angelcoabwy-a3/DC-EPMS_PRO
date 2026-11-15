/**
 * SLD viewport: named views, wheel zoom and drag pan for the Power SLD.
 *
 * The SLD is drawn in a 1200 x 1260 user space (Phase 1 paths, the
 * Phase 2 design branch, the Building D genset farm). Fitting all of
 * it into one screen makes the text unreadable, so the operator picks
 * a view (Path A, Path B, Phase 1, ...) and zooms or pans from there.
 * The pure helpers below are unit-tested; attachViewport() binds them
 * to an <svg> element. Nothing here changes what is drawn, only the
 * viewBox.
 */

export const SLD_BOUNDS = Object.freeze([0, 0, 1200, 1260]);
export const MIN_W = 240;

/** Named views (x, y, w, h in SLD user units). Ranges measured on the
 *  rendered drawing: Path A 50-410, Path B 360-710, Phase 2 726-1040,
 *  farm 988-1252. */
export const SLD_PRESETS = Object.freeze({
    p1: { label: 'PHASE 1', vb: [0, 14, 1200, 712] },
    a: { label: 'PATH A', vb: [0, 40, 1200, 384] },
    b: { label: 'PATH B', vb: [0, 348, 1200, 384] },
    p2: { label: 'PHASE 2', vb: [0, 722, 1200, 330] },
    farm: { label: 'FARM', vb: [40, 988, 1140, 264] },
    all: { label: 'ALL', vb: [...SLD_BOUNDS] },
});
export const DEFAULT_PRESET = 'p1';

export function parseVb(s) {
    const v = String(s || '').trim().split(/[\s,]+/).map(Number);
    return v.length === 4 && v.every(Number.isFinite) ? v : [...SLD_BOUNDS];
}

export function fmtVb(v) {
    return v.map((n) => Math.round(n * 10) / 10).join(' ');
}

/** Keep a view inside the drawing. A view wider (or taller) than the
 *  drawing is centred on that axis instead. */
export function clampVb([x, y, w, h], bounds = SLD_BOUNDS) {
    const [bx, by, bw, bh] = bounds;
    const cx = w >= bw ? bx + (bw - w) / 2 : Math.min(Math.max(x, bx), bx + bw - w);
    const cy = h >= bh ? by + (bh - h) / 2 : Math.min(Math.max(y, by), by + bh - h);
    return [cx, cy, w, h];
}

/** Zoom by `factor` (> 1 zooms in) keeping the point at fractions
 *  (fx, fy) of the view fixed. Aspect ratio is preserved. */
export function zoomAt(vb, factor, fx = 0.5, fy = 0.5, bounds = SLD_BOUNDS) {
    const [x, y, w, h] = vb;
    const maxW = bounds[2] * 1.5;
    const nw = Math.min(Math.max(w / factor, MIN_W), maxW);
    const nh = h * (nw / w);
    return clampVb([x + (w - nw) * fx, y + (h - nh) * fy, nw, nh], bounds);
}

/** Pan by (dx, dy) SLD units. */
export function panBy([x, y, w, h], dx, dy, bounds = SLD_BOUNDS) {
    return clampVb([x + dx, y + dy, w, h], bounds);
}

/** Scale and letterbox offsets of a viewBox drawn with
 *  preserveAspectRatio="xMidYMid meet" into a rect of rw x rh px. */
export function meetGeometry(rw, rh, [, , w, h]) {
    const s = Math.min(rw / w, rh / h);
    return { s, ox: (rw - w * s) / 2, oy: (rh - h * s) / 2 };
}

/** Pointer position (px inside the element) as fractions of the view. */
export function pointerFraction(px, py, rw, rh, vb) {
    const { s, ox, oy } = meetGeometry(rw, rh, vb);
    const fx = (px - ox) / (vb[2] * s);
    const fy = (py - oy) / (vb[3] * s);
    return [Math.min(Math.max(fx, 0), 1), Math.min(Math.max(fy, 0), 1)];
}

/** Grow a named view to the aspect ratio of the element so the
 *  letterbox shows drawing, not empty space: a wide screen gets more
 *  height below the view's top edge, a tall one more width around its
 *  centre. The view's own content always stays in frame. */
export function fitPreset(vb, rw, rh, bounds = SLD_BOUNDS) {
    const [x, y, w, h] = vb;
    if (!(rw > 0 && rh > 0)) return [...vb];
    const target = rw / rh;
    if (w / h > target) {
        const nh = w / target;
        return clampVb([x, y, w, nh], bounds);
    }
    const nw = h * target;
    return clampVb([x - (nw - w) / 2, y, nw, h], bounds);
}

/** Which named view to show for a drill or an event on a path. */
export function presetForPath(path) {
    const p = String(path || '').toUpperCase();
    return p === 'B' ? 'b' : (p === 'A' ? 'a' : DEFAULT_PRESET);
}

const DRAG_PX = 4;

/**
 * Bind wheel zoom + drag pan to an svg. A drag longer than 4 px
 * swallows the click that follows it, so inspecting a node by click
 * still works. Returns a small controller.
 */
export function attachViewport(svg, { preset = DEFAULT_PRESET, onChange = () => {} } = {}) {
    let name = SLD_PRESETS[preset] ? preset : DEFAULT_PRESET;
    let vb = fitPreset(SLD_PRESETS[name].vb, svg.getBoundingClientRect().width,
        svg.getBoundingClientRect().height);
    let drag = null;
    let swallowClick = false;

    const apply = () => {
        svg.setAttribute('viewBox', fmtVb(vb));
        onChange({ preset: name, vb: [...vb] });
    };
    const rect = () => svg.getBoundingClientRect();

    svg.addEventListener('wheel', (ev) => {
        ev.preventDefault();
        const r = rect();
        const [fx, fy] = pointerFraction(ev.clientX - r.left, ev.clientY - r.top, r.width, r.height, vb);
        vb = zoomAt(vb, ev.deltaY < 0 ? 1.15 : 1 / 1.15, fx, fy);
        name = null;
        apply();
    }, { passive: false });

    svg.addEventListener('pointerdown', (ev) => {
        if (ev.button !== 0) return;
        drag = { x: ev.clientX, y: ev.clientY, vb: [...vb], moved: false, id: ev.pointerId };
    });
    svg.addEventListener('pointermove', (ev) => {
        if (!drag) return;
        const dx = ev.clientX - drag.x;
        const dy = ev.clientY - drag.y;
        if (!drag.moved && Math.hypot(dx, dy) < DRAG_PX) return;
        if (!drag.moved) {
            drag.moved = true;
            try { svg.setPointerCapture(drag.id); } catch (_) { /* not supported */ }
            svg.classList.add('vp-dragging');
        }
        const r = rect();
        const { s } = meetGeometry(r.width, r.height, drag.vb);
        vb = panBy(drag.vb, -dx / s, -dy / s);
        name = null;
        apply();
    });
    const end = () => {
        if (drag && drag.moved) swallowClick = true;
        drag = null;
        svg.classList.remove('vp-dragging');
    };
    svg.addEventListener('pointerup', end);
    svg.addEventListener('pointercancel', end);
    svg.addEventListener('click', (ev) => {
        if (swallowClick) { swallowClick = false; ev.stopImmediatePropagation(); ev.preventDefault(); }
    }, true);

    apply();
    return {
        get preset() { return name; },
        get viewBox() { return [...vb]; },
        set(p) {
            if (!SLD_PRESETS[p]) return;
            name = p;
            const r = rect();
            vb = fitPreset(SLD_PRESETS[p].vb, r.width, r.height);
            apply();
        },
        /** Re-fit the named view after the element was resized. */
        refit() { if (name) this.set(name); },
        zoom(factor) { vb = zoomAt(vb, factor); name = null; apply(); },
        reapply() { apply(); },
    };
}

/** Toolbar markup (buttons carry data-vp / data-vp-zoom). */
export function viewportToolbarHtml(active, { inspectorOpen = true } = {}) {
    const views = Object.entries(SLD_PRESETS).map(([k, p]) =>
        `<button type="button" class="vp-btn" data-vp="${k}" aria-pressed="${k === active}">${p.label}</button>`).join('');
    return `<div class="vp-group" role="group" aria-label="View">${views}</div>`
        + '<div class="vp-group" role="group" aria-label="Zoom">'
        + '<button type="button" class="vp-btn" data-vp-zoom="out" aria-label="Zoom out">-</button>'
        + '<button type="button" class="vp-btn" data-vp-zoom="in" aria-label="Zoom in">+</button></div>'
        + `<button type="button" class="vp-btn vp-insp" data-vp-insp="1" aria-pressed="${inspectorOpen}">Inspector</button>`
        + '<button type="button" class="vp-btn vp-insp" data-vp-field="1" title="Field view of the 13.8 kV switchgear">Field: SWGR</button>'
        + '<span class="vp-hint">wheel = zoom · drag = pan</span>';
}
