/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO -- frontend/assets/js/views/usd_export.js
 * Release R2-C -- USD export (replaces the Omniverse 3D stub).
 *
 * Shows what GET /api/site/usd contains (counts from
 * /api/site/usd/summary) and offers the .usda download. HONEST
 * SCOPE, printed permanently on the view: static export, schematic
 * layout, no Omniverse live-link, no telemetry in the stage.
 *
 * Read-only (ADR-006). S-SEC-01: every interpolated value is
 * escaped; the download is a plain same-origin link so the session
 * cookie of a gated deployment applies with no script involved.
 * ════════════════════════════════════════════════════════════════ */

import { registerRoute } from '../core/router.js';
import { escapeHTML } from '../core/sanitize.js';

const VIEW_ID = 'view-usd-export';
const ROUTE_ID = 'usd-export';
const SUMMARY_ENDPOINT = '/api/site/usd/summary';
const DOWNLOAD_ENDPOINT = '/api/site/usd';

let _routeRegistered = false;

function $root() {
    return document.getElementById(VIEW_ID);
}

function _count(value) {
    const n = Number(value);
    return Number.isFinite(n) ? String(n) : '0';
}

function renderTypes(byType) {
    const entries = Object.keys(byType || {}).sort()
        .map((k) => [k, Number(byType[k]) || 0])
        .sort((a, b) => (b[1] - a[1]) || a[0].localeCompare(b[0]));
    if (entries.length === 0) {
        return '<tr><td colspan="2" class="usdx-empty">No components.</td></tr>';
    }
    return entries.map(([type, n]) => `
        <tr><td class="usdx-mono">${escapeHTML(type)}</td><td class="usdx-num">${escapeHTML(String(n))}</td></tr>`).join('');
}

function renderSummary(summary) {
    const s = summary || {};
    const unplaced = Number(s.unplaced_component_count) || 0;
    const unplacedNote = unplaced > 0
        ? `<div class="usdx-note">${escapeHTML(String(unplaced))} component(s) have no building in the site model; they are exported under the <span class="usdx-mono">unplaced</span> group.</div>`
        : '';
    return `
        <div class="usdx-notice" role="note">${escapeHTML(s.notice || '')}
            No Omniverse live-link exists: this is a static file. The live 3D view of the facility is Mission Control.</div>
        <div class="usdx-tiles">
            <div class="usdx-tile"><div class="usdx-tile-val">${escapeHTML(_count(s.component_count))}</div><div class="usdx-tile-lbl">components</div></div>
            <div class="usdx-tile"><div class="usdx-tile-val">${escapeHTML(_count(s.building_count))}</div><div class="usdx-tile-lbl">building groups</div></div>
            <div class="usdx-tile"><div class="usdx-tile-val">${escapeHTML(_count(s.power_edge_count))}</div><div class="usdx-tile-lbl">power relationships</div></div>
            <div class="usdx-tile"><div class="usdx-tile-val">${escapeHTML(_count(s.cooling_edge_count))}</div><div class="usdx-tile-lbl">cooling relationships</div></div>
        </div>
        <div class="usdx-actions">
            <a class="usdx-download" href="${DOWNLOAD_ENDPOINT}" download="${escapeHTML(s.filename || 'site.usda')}">Download ${escapeHTML(s.filename || 'site.usda')}</a>
            <span class="usdx-hint">OpenUSD ASCII layer. Opens in usdview, Blender or NVIDIA Omniverse.</span>
        </div>
        ${unplacedNote}
        <div class="usdx-panels">
            <section class="usdx-panel">
                <h3>What the stage contains</h3>
                <ul class="usdx-list">
                    <li>One prim per building, room, row and component, under <span class="usdx-mono">/World/Site</span>.</li>
                    <li>Component metadata as <span class="usdx-mono">a3semi:meta:*</span> attributes (ratings, voltages, vendor).</li>
                    <li>Power and cooling chains as <span class="usdx-mono">a3semi:powerFeeds</span> / <span class="usdx-mono">a3semi:coolingFeeds</span> relationships.</li>
                    <li>Z-up, metres. Each component is a cube sized by asset type.</li>
                </ul>
                <h3>What it does not contain</h3>
                <ul class="usdx-list">
                    <li>Real coordinates. The site model has none; positions are a deterministic grid.</li>
                    <li>Vendor geometry, materials or cable routing.</li>
                    <li>Telemetry or any live state.</li>
                </ul>
            </section>
            <section class="usdx-panel">
                <h3>Components by type</h3>
                <table class="usdx-table">
                    <thead><tr><th>Asset type</th><th class="usdx-num">Count</th></tr></thead>
                    <tbody>${renderTypes(s.components_by_type)}</tbody>
                </table>
            </section>
        </div>`;
}

function renderShell() {
    const root = $root();
    if (!root || root.querySelector('[data-usdx-body]')) return;
    root.innerHTML = `
        <div class="view-hdr">
            <h2>USD Export — site model as an OpenUSD stage</h2>
            <div class="view-sub">Static, schematic export of config/site_model.yml. No live-link, no telemetry.</div>
        </div>
        <div data-usdx-body><div class="usdx-empty">Loading…</div></div>`;
}

function renderError(message) {
    const body = $root() && $root().querySelector('[data-usdx-body]');
    if (body) body.innerHTML = `<div class="usdx-empty usdx-error">${escapeHTML(message)}</div>`;
}

async function refresh() {
    const root = $root();
    if (!root) return;
    renderShell();
    let res;
    try {
        res = await fetch(SUMMARY_ENDPOINT);
    } catch (_e) {
        renderError('Export summary unreachable.');
        return;
    }
    if (!res || !res.ok) {
        renderError(`Export summary unavailable (HTTP ${res ? res.status : '?'}).`);
        return;
    }
    let summary;
    try {
        summary = await res.json();
    } catch (_e) {
        renderError('Export summary could not be parsed.');
        return;
    }
    const body = root.querySelector('[data-usdx-body]');
    if (body) body.innerHTML = renderSummary(summary);
}

function initUsdExportView() {
    if (_routeRegistered) return;
    registerRoute(ROUTE_ID, {
        viewId: VIEW_ID,
        // The site model is static per boot: one fetch per activation,
        // no polling.
        activate: () => { refresh(); },
    });
    _routeRegistered = true;
}

function reset() {
    _routeRegistered = false;
}

export { initUsdExportView };

export const __usd_export_test__ = {
    renderSummary,
    renderTypes,
    refresh,
    reset,
    DOWNLOAD_ENDPOINT,
};
