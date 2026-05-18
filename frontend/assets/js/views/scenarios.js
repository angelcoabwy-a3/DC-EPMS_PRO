/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/scenarios.js
 * ROADMAP V11 T2.1 — first legacy IIFE view extracted to an ES module.
 *
 * Behaviour-preserving migration of the failure-scenario simulator out
 * of the monolithic app.js IIFE: a catalogue of critical scenarios,
 * each with an ODE-projected 15-minute trajectory chart.
 *
 * Integration (mirrors views/multi_agent.js, the established pattern):
 *   - registerRoute('scenarios', …) hands navigation to core/router.js
 *     (the T2.2 declarative registry). The legacy navigateTo() delegates
 *     any registered route, so the IIFE no longer renders this view.
 *   - HTTP goes through services/api.js (the T2.1 keystone).
 *   - Chart.js stays a window global (loaded by index.html, as before);
 *     guarded with `typeof Chart` so the module is import-safe — and
 *     unit-testable — with no Chart present.
 *
 * Test surface: __scenarios_test__ exposes the pure render helpers so
 * the Vitest harness asserts HTML output + XSS escaping without a
 * browser or a backend.
 * ════════════════════════════════════════════════════════════════ */

import { registerRoute } from '../core/router.js';
import { getScenarios, runScenario } from '../services/api.js';
import { escapeHTML as _escape } from '../core/sanitize.js';

let _cache = null;          // scenarios array — fetched once, then reused
let _initialized = false;

// ─── Pure presentation helpers (the __scenarios_test__ surface) ────
const _MOD_ICONS = {
    it_thermal:     '🌡',
    mechanical:     '⚙',
    electrical:     '⚡',
    heat_rejection: '❄',
};

function _modIcon(module) {
    return _MOD_ICONS[module] || '◌';
}

function _sevClass(sev) {
    return 'sev-' + (sev || 'info');
}

function _scenarioCardHtml(s) {
    return `<div class="scenario-card" data-id="${_escape(s.id)}">
                <div class="scenario-card-hdr">
                    <span class="scenario-mod-icon">${_modIcon(s.primary_module)}</span>
                    <span class="scenario-id">${_escape(s.id)}</span>
                    <span class="scenario-sev ${_sevClass(s.severity_if_uncorrected)}">${_escape(s.severity_if_uncorrected || 'info')}</span>
                </div>
                <div class="scenario-name">${_escape(s.name)}</div>
                <div class="scenario-meta">
                    <span>${_escape(s.primary_module)}</span>
                    <span>·</span>
                    <span>TTR ${_escape(s.expected_ttr_minutes || '?')} min</span>
                </div>
            </div>`;
}

function _scenarioDetailHtml(s) {
    const stds = (s.standard_refs || [])
        .map(r => `<span class="scenario-std-chip">${_escape(r)}</span>`).join('');
    return `
            <div class="scenario-detail-hdr">
                <h3>${_escape(s.name)}</h3>
                <div class="scenario-detail-meta">
                    <span class="scenario-id-badge">${_escape(s.id)}</span>
                    <span class="scenario-sev ${_sevClass(s.severity_if_uncorrected)}">${_escape(s.severity_if_uncorrected || 'info')}</span>
                    <span>Module: <strong>${_escape(s.primary_module)}</strong></span>
                    <span>Expected TTR: <strong>${_escape(s.expected_ttr_minutes || '?')} min</strong></span>
                </div>
            </div>

            <div class="scenario-section">
                <div class="scenario-section-lbl">Description</div>
                <div class="scenario-desc">${_escape(s.description)}</div>
            </div>

            <div class="scenario-section">
                <div class="scenario-section-lbl">Mitigation document</div>
                <div class="scenario-doc-ref">📄 ${_escape(s.mitigation_doc || 'n/a')}</div>
            </div>

            <div class="scenario-section">
                <div class="scenario-section-lbl">Standards</div>
                <div class="scenario-standards">${stds}</div>
            </div>

            <div class="scenario-action-row">
                <button class="btn" id="btn-run-scenario">▶ Run 15-min simulation</button>
                <span class="scenario-action-note">ODE integration via scipy.solve_ivp</span>
            </div>

            <div class="scenario-result" id="scenario-result"></div>
        `;
}

/**
 * Module-aware metric selection for the result chart. Pure: maps the
 * physics module to the 1-2 trajectory series worth plotting.
 */
function _pickDatasets(d) {
    const traj = d.trajectory || [];
    const at = (key) => traj.map(s => s.state?.[key]);
    if (d.module === 'it_thermal') {
        return [
            { label: 'Hall air (°C)', data: at('hall_air_c'),
              borderColor: '#FB8C00', backgroundColor: 'rgba(251,140,0,0.1)', tension: 0.2, pointRadius: 0 },
            { label: 'GPU Tj est. (°C)', data: at('gpu_tj_estimate_c'),
              borderColor: '#E53935', backgroundColor: 'rgba(229,57,53,0.05)', tension: 0.2, pointRadius: 0 },
        ];
    }
    if (d.module === 'mechanical') {
        return [
            { label: 'Loop return (°C)', data: at('loop_return_c'),
              borderColor: '#FB8C00', tension: 0.2, pointRadius: 0 },
            { label: 'DLC ΔT (K)', data: at('dlc_delta_T_k'),
              borderColor: '#00B8D4', tension: 0.2, pointRadius: 0, yAxisID: 'y1' },
        ];
    }
    if (d.module === 'electrical') {
        return [
            { label: 'Battery SOC', data: traj.map(s => s.state?.battery_soc * 100),
              borderColor: '#4CAF50', tension: 0.2, pointRadius: 0 },
            { label: 'Battery V (V)', data: at('battery_vdc'),
              borderColor: '#00B8D4', tension: 0.2, pointRadius: 0, yAxisID: 'y1' },
        ];
    }
    if (d.module === 'heat_rejection') {
        return [
            { label: 'Wet bulb (°C)', data: at('outdoor_wet_bulb_c'),
              borderColor: '#FB8C00', tension: 0.2, pointRadius: 0 },
            { label: 'Chiller COP', data: at('chiller_cop'),
              borderColor: '#00B8D4', tension: 0.2, pointRadius: 0, yAxisID: 'y1' },
        ];
    }
    return [];
}

function _scenarioResultHtml(d) {
    const events = d.events || [];
    const traj = d.trajectory || [];
    const summary = d.summary || {};
    const eventsHtml = events.length === 0
        ? '<div class="scenario-no-events">No events fired during simulation.</div>'
        : '<div class="scenario-events-list">' +
          events.map(e =>
              `<div class="scenario-event">
                    <span class="scenario-event-t">t=${_escape(Math.round(e.t))}s</span>
                    <span class="scenario-event-name">${_escape(e.event)}</span>
                </div>`).join('') +
          '</div>';
    return `
            <div class="scenario-result-hdr">
                <h4>Simulation result</h4>
                <div class="scenario-result-meta">
                    ${_escape(traj.length)} snapshots · ${_escape(events.length)} events · ${_escape(summary.horizon_s)}s horizon
                </div>
            </div>
            <div class="scenario-chart-wrap">
                <canvas id="scenario-chart" height="180"></canvas>
            </div>
            <div class="scenario-events-section">
                <div class="scenario-section-lbl">Events fired</div>
                ${eventsHtml}
            </div>
        `;
}

// ─── DOM render (depends on #view-scenarios children) ──────────────
async function _renderList() {
    const listEl = document.getElementById('scenarios-list');
    if (!listEl) return;
    if (!_cache) {
        try {
            _cache = await getScenarios();
        } catch (e) {
            listEl.innerHTML =
                `<div class="scenarios-empty" style="color:var(--crit)">Failed to load scenarios: ${_escape(e.message)}</div>`;
            return;
        }
    }
    if (_cache.length === 0) {
        listEl.innerHTML = '<div class="scenarios-empty">No scenarios available.</div>';
        return;
    }
    listEl.innerHTML = _cache.map(_scenarioCardHtml).join('');
    listEl.querySelectorAll('.scenario-card').forEach(card => {
        card.addEventListener('click', () => {
            listEl.querySelectorAll('.scenario-card').forEach(c => c.classList.remove('active'));
            card.classList.add('active');
            _showDetail(card.dataset.id);
        });
    });
}

function _showDetail(scenarioId) {
    const detailEl = document.getElementById('scenarios-detail');
    if (!detailEl) return;
    const s = (_cache || []).find(x => x.id === scenarioId);
    if (!s) return;
    detailEl.innerHTML = _scenarioDetailHtml(s);
    const runBtn = document.getElementById('btn-run-scenario');
    if (runBtn) runBtn.addEventListener('click', () => _doRun(scenarioId));
}

async function _doRun(scenarioId) {
    const btn = document.getElementById('btn-run-scenario');
    const resultEl = document.getElementById('scenario-result');
    if (!resultEl) return;
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="loading"></span>Running ODE simulation…';
    }
    resultEl.innerHTML = '<div class="scenario-running">Integrating ODE over 900-second horizon…</div>';
    try {
        const d = await runScenario(scenarioId, 900);
        _renderResult(resultEl, d);
    } catch (e) {
        resultEl.innerHTML =
            `<div style="color:var(--crit);padding:14px">Simulation error: ${_escape(e.message)}</div>`;
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '▶ Run 15-min simulation';
        }
    }
}

function _renderResult(el, d) {
    el.innerHTML = _scenarioResultHtml(d);
    const datasets = _pickDatasets(d);
    const labels = (d.trajectory || []).map(s => Math.round(s.t) + 's');
    const ctx = document.getElementById('scenario-chart');
    // Chart.js is a window global injected by index.html. Guard with
    // typeof so the module imports cleanly with no Chart (e.g. Vitest).
    if (ctx && typeof Chart !== 'undefined' && datasets.length > 0) {
        new Chart(ctx, {
            type: 'line',
            data: { labels, datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                scales: {
                    x:  { ticks: { maxTicksLimit: 10, color: '#9AA0A6' }, grid: { color: 'rgba(154,160,166,0.08)' } },
                    y:  { ticks: { color: '#9AA0A6' }, grid: { color: 'rgba(154,160,166,0.08)' } },
                    y1: { type: 'linear', position: 'right', ticks: { color: '#9AA0A6' }, grid: { display: false } },
                },
                plugins: { legend: { labels: { color: '#E8EAED', font: { size: 11 } } } },
            },
        });
    }
}

// ─── Routing + lifecycle ───────────────────────────────────────────
function _activate() {
    // core/router.js calls this on every navigation to #view-scenarios.
    // Re-render the list each time — cheap, since _cache avoids re-fetch.
    _renderList();
}

function _wireRouting() {
    // T2.2 declarative registry — replaces the legacy IIFE render branch.
    registerRoute('scenarios', { viewId: 'view-scenarios', activate: _activate });
}

/** Public entry — called once from main.js at bootstrap. */
export function initScenariosView() {
    if (_initialized) return;
    if (!document.getElementById('view-scenarios')) {
        console.warn('[scenarios] #view-scenarios not in DOM; view disabled.');
        return;
    }
    _wireRouting();
    _initialized = true;
    console.log('[scenarios] view ready (failure-scenario simulator — T2.1 ES module)');
}

// ─── Test surface ──────────────────────────────────────────────────
export const __scenarios_test__ = {
    escape: _escape,
    modIcon: _modIcon,
    sevClass: _sevClass,
    scenarioCardHtml: _scenarioCardHtml,
    scenarioDetailHtml: _scenarioDetailHtml,
    scenarioResultHtml: _scenarioResultHtml,
    pickDatasets: _pickDatasets,
    getCache: () => _cache,
    setCache: (v) => { _cache = v; },
    reset: () => { _cache = null; _initialized = false; },
};
