/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/incidents.js
 * ROADMAP V11 T2.1 — Incidents view extracted from the app.js IIFE.
 *
 * Behaviour-preserving migration of the incident audit-log view out of
 * the monolithic app.js: four KPI tiles (total / critical / warning /
 * open) over a most-recent-first table of PostgreSQL incident rows.
 *
 * Integration (mirrors views/scenarios.js, the established pattern):
 *   - registerRoute('incidents', …) hands navigation to core/router.js
 *     (the T2.2 declarative registry). The legacy navigateTo() delegates
 *     any registered route, so the IIFE no longer renders this view.
 *   - HTTP goes through services/api.js (getIncidents).
 *   - EDA: subscribes to the `hermes:cmms-alert` DOM event (T3.1 plane).
 *     When a CMMS alert lands and this view is on screen it refreshes
 *     live — no polling.
 *
 * Test surface: __incidents_test__ exposes the pure render helpers so
 * the Vitest harness asserts HTML output + XSS escaping + KPI math
 * without a browser or a backend.
 * ════════════════════════════════════════════════════════════════ */

import { registerRoute } from '../core/router.js';
import { getIncidents } from '../services/api.js';

const INCIDENT_LIMIT = 50;

let _initialized = false;

// ─── HTML escape (regex form — import-safe, needs no document) ─────
function _escape(s) {
    if (s === null || s === undefined) return '';
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// ─── Pure presentation helpers (the __incidents_test__ surface) ────
/** Map a raw severity string to a CSS class — mirrors the legacy
 *  app.js severityClass() so styling is byte-identical. */
function _severityClass(sev) {
    sev = (sev || '').toLowerCase();
    if (sev === 'critical' || sev === 'crit') return 'crit';
    if (sev === 'warning' || sev === 'warn') return 'warn';
    return 'info';
}

/** Format an ISO timestamp as a 24h local time — mirrors legacy fmt.time. */
function _fmtTime(iso) {
    if (!iso) return '—';
    try {
        return new Date(iso).toLocaleTimeString('en-CA', { hour12: false });
    } catch (_e) {
        return String(iso).slice(11, 19);
    }
}

/** Derive the four KPI-tile counts from the incident rows. */
function _computeKpis(rows) {
    const list = Array.isArray(rows) ? rows : [];
    return {
        total: list.length,
        crit: list.filter(r => (r.severity || '').toLowerCase().startsWith('crit')).length,
        warn: list.filter(r => (r.severity || '').toLowerCase().startsWith('warn')).length,
        open: list.filter(r => (r.status || '').toUpperCase() === 'OPEN').length,
    };
}

/** One incident table row. Every interpolated field is escaped. */
function _incidentRowHtml(r) {
    const cls = _severityClass(r.severity);
    const sev = (r.severity || 'info').toUpperCase();
    const color = cls === 'info' ? 'var(--accent)' : 'var(--' + cls + ')';
    return `<div class="inc-table-row ${cls}">
                <span class="id">${_escape(r.incident_id || '')}</span>
                <span class="ts-col">${_escape(_fmtTime(r.ts))}</span>
                <span class="sev-col" style="color:${color}">${_escape(sev.slice(0, 4))}</span>
                <span class="src-col">${_escape(r.source || '')}</span>
                <span class="title-col" title="${_escape(r.title || '')}">${_escape(r.title || '')}</span>
                <span class="status-col">${_escape(r.status || 'OPEN')}</span>
            </div>`;
}

// ─── DOM render (depends on #view-incidents children) ──────────────
function _setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = String(value);
}

async function _render() {
    const tbl = document.getElementById('inc-table');
    if (!tbl) return;
    let rows;
    try {
        rows = await getIncidents(INCIDENT_LIMIT);
    } catch (e) {
        // services/api.js convention: surface a degraded state, never a
        // silent fail (the legacy IIFE only console.warn'd here).
        tbl.innerHTML =
            '<div class="inc-empty" style="padding:30px;text-align:center;'
            + `color:var(--crit)">Failed to load incidents: ${_escape(e.message)}</div>`;
        return;
    }

    const kpis = _computeKpis(rows);
    _setText('inc-total', kpis.total);
    _setText('inc-crit', kpis.crit);
    _setText('inc-warn', kpis.warn);
    _setText('inc-open', kpis.open);

    if (rows.length === 0) {
        tbl.innerHTML =
            '<div style="padding:30px;text-align:center;color:var(--text-dim)">'
            + 'No incidents recorded yet. Run the simulator with --incidents.</div>';
        return;
    }
    tbl.innerHTML = rows.map(_incidentRowHtml).join('');
}

// ─── EDA — refresh live on the Hermes cmms_alerts plane ────────────
function _onCmmsAlert() {
    // T3.1: a CMMS alert means the audit log may have changed. Refresh
    // only when the view is actually on screen — cheap, and no polling.
    const view = document.getElementById('view-incidents');
    if (view && !view.hasAttribute('hidden')) {
        _render();
    }
}

// ─── Routing + lifecycle ───────────────────────────────────────────
function _activate() {
    // core/router.js calls this on every navigation to #view-incidents.
    _render();
}

/** Public entry — called once from main.js at bootstrap. */
export function initIncidentsView() {
    if (_initialized) return;
    if (!document.getElementById('view-incidents')) {
        console.warn('[incidents] #view-incidents not in DOM; view disabled.');
        return;
    }
    // T2.2 declarative registry — replaces the legacy IIFE render branch.
    registerRoute('incidents', { viewId: 'view-incidents', activate: _activate });

    const refreshBtn = document.getElementById('inc-refresh');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            _render();
        });
    }
    document.addEventListener('hermes:cmms-alert', _onCmmsAlert);

    _initialized = true;
    console.log('[incidents] view ready (incident audit log — T2.1 ES module)');
}

// ─── Test surface ──────────────────────────────────────────────────
export const __incidents_test__ = {
    escape: _escape,
    severityClass: _severityClass,
    fmtTime: _fmtTime,
    computeKpis: _computeKpis,
    incidentRowHtml: _incidentRowHtml,
    render: _render,
    onCmmsAlert: _onCmmsAlert,
    reset: () => { _initialized = false; },
};
