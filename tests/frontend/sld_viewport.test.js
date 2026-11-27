import { describe, it, expect } from 'vitest';
import {
    SLD_PRESETS, SLD_BOUNDS, MIN_W, DEFAULT_PRESET, parseVb, fmtVb, clampVb, zoomAt, panBy,
    meetGeometry, pointerFraction, presetForPath, attachViewport, viewportToolbarHtml, fitPreset,
} from '../../frontend/assets/js/core/sld_viewport.js';

describe('sld_viewport pure helpers', () => {
    it('every preset lies inside the drawing', () => {
        for (const { vb } of Object.values(SLD_PRESETS)) {
            expect(vb[0]).toBeGreaterThanOrEqual(0);
            expect(vb[1]).toBeGreaterThanOrEqual(0);
            expect(vb[0] + vb[2]).toBeLessThanOrEqual(SLD_BOUNDS[2]);
            expect(vb[1] + vb[3]).toBeLessThanOrEqual(SLD_BOUNDS[3]);
        }
        expect(SLD_PRESETS[DEFAULT_PRESET]).toBeDefined();
    });

    it('parses and formats a viewBox, falling back to the bounds', () => {
        expect(parseVb('0 14 1200 712')).toEqual([0, 14, 1200, 712]);
        expect(parseVb('junk')).toEqual([...SLD_BOUNDS]);
        expect(fmtVb([1.04, 2, 3.333, 4])).toBe('1 2 3.3 4');
    });

    it('zoom in keeps the focus point fixed and the aspect ratio', () => {
        const vb = [0, 0, 1200, 600];
        const z = zoomAt(vb, 2, 0.5, 0.5);
        expect(z[2]).toBe(600);
        expect(z[3]).toBe(300);
        expect(z[0] + z[2] / 2).toBe(600);
        expect(z[1] + z[3] / 2).toBe(300);
    });

    it('zoom stops at the minimum width', () => {
        let vb = [0, 0, 1200, 600];
        for (let i = 0; i < 40; i++) vb = zoomAt(vb, 2);
        expect(vb[2]).toBe(MIN_W);
    });

    it('pan is clamped to the drawing; an oversize view is centred', () => {
        expect(panBy([0, 0, 600, 300], -500, -500)).toEqual([0, 0, 600, 300]);
        expect(panBy([0, 0, 600, 300], 5000, 5000)).toEqual([600, 1290, 600, 300]);
        const big = clampVb([0, 0, 1800, 1890]);
        expect(big[0]).toBe(-300);
    });

    it('maps a pointer through the meet letterbox', () => {
        const g = meetGeometry(1000, 1000, [0, 0, 1200, 600]);
        expect(g.s).toBeCloseTo(1000 / 1200);
        expect(g.oy).toBeCloseTo(250);
        expect(pointerFraction(500, 500, 1000, 1000, [0, 0, 1200, 600])).toEqual([0.5, 0.5]);
        expect(pointerFraction(0, 0, 1000, 1000, [0, 0, 1200, 600])).toEqual([0, 0]);
    });

    it('picks the view for a drill path', () => {
        expect(presetForPath('a')).toBe('a');
        expect(presetForPath('B')).toBe('b');
        expect(presetForPath(undefined)).toBe(DEFAULT_PRESET);
    });

    it('toolbar marks the active view and the inspector state', () => {
        const html = viewportToolbarHtml('a', { inspectorOpen: false });
        expect(html).toContain('data-vp="a" aria-pressed="true"');
        expect(html).toContain('data-vp="b" aria-pressed="false"');
        expect(html).toContain('data-vp-insp="1" aria-pressed="false"');
    });
});

describe('attachViewport', () => {
    const svgEl = () => {
        document.body.innerHTML = '<svg class="pid-svg" viewBox="0 0 1200 1590"></svg>';
        const svg = document.querySelector('svg');
        svg.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1200, height: 600 });
        return svg;
    };

    it('applies the preset and switches views', () => {
        const svg = svgEl();
        const seen = [];
        const vp = attachViewport(svg, { preset: 'a', onChange: (e) => seen.push(e.preset) });
        expect(svg.getAttribute('viewBox')).toBe(fmtVb(fitPreset(SLD_PRESETS.a.vb, 1200, 600)));
        vp.set('p2');
        expect(svg.getAttribute('viewBox')).toBe(fmtVb(fitPreset(SLD_PRESETS.p2.vb, 1200, 600)));
        vp.set('nope');
        expect(vp.preset).toBe('p2');
        expect(seen).toEqual(['a', 'p2']);
    });

    it('wheel zooms and leaves the named view', () => {
        const svg = svgEl();
        const vp = attachViewport(svg, { preset: 'p1' });
        const w0 = vp.viewBox[2];
        const ev = new WheelEvent('wheel', { deltaY: -100, clientX: 600, clientY: 300, cancelable: true });
        svg.dispatchEvent(ev);
        expect(ev.defaultPrevented).toBe(true);
        expect(vp.viewBox[2]).toBeLessThan(w0);
        expect(vp.preset).toBeNull();
    });

    it('a drag pans and swallows the click that follows; a plain click passes', () => {
        const svg = svgEl();
        const vp = attachViewport(svg, { preset: 'a' });
        let clicks = 0;
        svg.addEventListener('click', () => { clicks += 1; });
        svg.dispatchEvent(new PointerEvent('pointerdown', { button: 0, clientX: 100, clientY: 100 }));
        svg.dispatchEvent(new PointerEvent('pointermove', { clientX: 100, clientY: 160 }));
        svg.dispatchEvent(new PointerEvent('pointerup', { clientX: 100, clientY: 160 }));
        expect(vp.viewBox[1]).toBeLessThan(SLD_PRESETS.a.vb[1]);
        svg.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        expect(clicks).toBe(0);
        svg.dispatchEvent(new PointerEvent('pointerdown', { button: 0, clientX: 100, clientY: 100 }));
        svg.dispatchEvent(new PointerEvent('pointerup', { clientX: 101, clientY: 100 }));
        svg.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        expect(clicks).toBe(1);
    });
});

describe('fitPreset', () => {
    it('a wide element grows the view downward from its top edge', () => {
        const v = fitPreset([0, 40, 1200, 384], 1200, 600);
        expect(v).toEqual([0, 40, 1200, 600]);
    });
    it('a tall element grows the view sideways around its centre, clamped', () => {
        const v = fitPreset([400, 0, 200, 400], 600, 600);
        expect(v).toEqual([300, 0, 400, 400]);
    });
    it('keeps the view inside the drawing at the bottom edge', () => {
        const v = fitPreset([0, 722, 1200, 330], 1200, 900);
        expect(v[1] + v[3]).toBeLessThanOrEqual(1590);
    });
    it('an element with no size leaves the view unchanged', () => {
        expect(fitPreset([0, 40, 1200, 384], 0, 0)).toEqual([0, 40, 1200, 384]);
    });
});
