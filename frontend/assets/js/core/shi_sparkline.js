/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — core/shi_sparkline.js
 *
 * Site Health Index trend sparkline. Pure SVG (no Chart.js).
 *
 * Renders a 60-sample rolling trend of SHI values into the existing
 * #shi-sparkline element inside the SHI panel. Sample rate is driven
 * by app.js fetchSiteHealth interval (15s today -> 15min window).
 *
 * Visual elements:
 *   - Dashed horizontal line at SHI=0.50 (Pillar 2 HARD_FAIL boundary
 *     per backend/loto_auditor_agent.py SHI_DEFAULT_THRESHOLD).
 *   - Polyline connecting samples, colored by latest overall_severity
 *     (ok=accent cyan, info=accent, warning=amber, critical=red).
 *   - Red dot markers on samples that breached the 0.50 threshold.
 *
 * Layout: newest sample anchored at right edge; line grows leftward
 * as history accumulates. Once 60 samples are present, the window
 * scrolls (oldest dropped from left).
 *
 * Cost: <1ms per render (60 polyline points + threshold line + a
 * small number of breach markers). Re-renders only when shiHistory
 * changes (no setInterval — purely reactive via subscribe).
 *
 * NOT a general-purpose chart. If we ever need pan/zoom/tooltip we
 * upgrade to Chart.js. For now: instrument-grade minimalism.
 * ════════════════════════════════════════════════════════════════ */

import { subscribe, getState } from './state.js';

const SVG_NS = 'http://www.w3.org/2000/svg';

const SVG_WIDTH = 600;     // logical viewBox units
const SVG_HEIGHT = 50;
const PADDING_Y = 4;
const THRESHOLD = 0.5;
const MAX_SAMPLES = 60;

let _svg = null;
let _polyline = null;
let _thresholdLine = null;
let _markersGroup = null;
let _initialized = false;

function _yForShi(shi) {
    const usable = SVG_HEIGHT - 2 * PADDING_Y;
    const clamped = Math.max(0, Math.min(1, shi));
    return PADDING_Y + (1 - clamped) * usable;
}

function _ensureScaffold(svg) {
    // Threshold line (dashed, at SHI=0.50)
    const yT = _yForShi(THRESHOLD);
    _thresholdLine = document.createElementNS(SVG_NS, 'line');
    _thresholdLine.setAttribute('x1', '0');
    _thresholdLine.setAttribute('x2', String(SVG_WIDTH));
    _thresholdLine.setAttribute('y1', String(yT));
    _thresholdLine.setAttribute('y2', String(yT));
    _thresholdLine.setAttribute('class', 'sparkline-threshold');
    svg.appendChild(_thresholdLine);

    // Polyline (trend)
    _polyline = document.createElementNS(SVG_NS, 'polyline');
    _polyline.setAttribute('class', 'sparkline-trend');
    _polyline.setAttribute('points', '');
    svg.appendChild(_polyline);

    // Breach markers group
    _markersGroup = document.createElementNS(SVG_NS, 'g');
    _markersGroup.setAttribute('class', 'sparkline-markers');
    svg.appendChild(_markersGroup);
}

function _render() {
    if (!_initialized) return;

    const hist = getState('shiHistory') || [];

    if (hist.length === 0) {
        _polyline.setAttribute('points', '');
        _markersGroup.replaceChildren();
        _polyline.dataset.severity = 'ok';
        return;
    }

    // X mapping: newest sample at right edge, fill leftward
    const stepX = SVG_WIDTH / Math.max(1, MAX_SAMPLES - 1);
    const startX = SVG_WIDTH - (hist.length - 1) * stepX;

    const ptsArr = [];
    const breaches = [];
    for (let i = 0; i < hist.length; i++) {
        const p = hist[i];
        const x = startX + i * stepX;
        const y = _yForShi(p.shi);
        ptsArr.push(`${x.toFixed(1)},${y.toFixed(1)}`);
        if (p.shi < THRESHOLD) breaches.push({ x, y });
    }
    _polyline.setAttribute('points', ptsArr.join(' '));

    const lastSev = hist[hist.length - 1]?.severity || 'ok';
    _polyline.dataset.severity = lastSev;

    // Render breach markers (replaceChildren is faster than innerHTML='')
    const newMarkers = breaches.map((b) => {
        const c = document.createElementNS(SVG_NS, 'circle');
        c.setAttribute('cx', b.x.toFixed(1));
        c.setAttribute('cy', b.y.toFixed(1));
        c.setAttribute('r', '2.5');
        c.setAttribute('class', 'sparkline-breach');
        return c;
    });
    _markersGroup.replaceChildren(...newMarkers);
}

export function initShiSparkline({ svgId = 'shi-sparkline' } = {}) {
    _svg = document.getElementById(svgId);
    if (!_svg) {
        console.warn(`[shi_sparkline] #${svgId} not in DOM; sparkline disabled.`);
        return;
    }
    _svg.setAttribute('viewBox', `0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`);
    _svg.setAttribute('preserveAspectRatio', 'none');

    _ensureScaffold(_svg);
    _initialized = true;

    subscribe('shiHistory', _render);
    _render();  // initial paint (empty)
}

export const SHI_SPARKLINE_CONFIG = Object.freeze({
    THRESHOLD,
    MAX_SAMPLES,
    SVG_WIDTH,
    SVG_HEIGHT,
});
