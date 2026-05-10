/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — frontend/assets/js/views/asset_panel.js
 *
 * Phase 4: Contextual System Info Panel for the Power & UPS SLD.
 *
 *   Default state: SYSTEM OVERVIEW (path A/B status, total load,
 *   PUE, SHI, count of tripped/on-battery/transferring nodes —
 *   derived from grid state).
 *
 *   On selection: ASSET DETAIL — model, rating, vendor metadata,
 *   60-sample sparkline of the asset's key metric, action buttons.
 *
 *   Selection lifecycle:
 *     - Plain click on iso-block → setState('selectedAsset', id)
 *       (NOT shift-click — that's TRIP — and NOT TRIP pip)
 *     - Click on the panel's [×] close button → setState(null)
 *     - Click outside any iso-block but inside the canvas → null
 *
 *   Sparkline:
 *     - Chart.js 4.4.1 (already vendored; no CDN at runtime).
 *     - On selection: prepopulate 60 synthetic samples from the
 *       asset's baseline metadata, then 1Hz push live samples
 *       (baseline + ±0.5 % noise). When selection changes, the
 *       chart is re-mounted from scratch.
 *     - Battery SOC: bound to grid.batt_x.soc (real, decays during
 *       sim — not synthetic).
 *
 *   Action buttons (Phase 4 directive 4):
 *     [View MOP] [Create Work Order] [Open in Maintenance]
 *     - View MOP: toast + console.log (placeholder for future
 *       MOPs router integration).
 *     - Create WO: toast + sessionStorage handoff +
 *       programmatic nav to #maintenance.
 *     - Open in Maintenance: same as Create WO but pre-loads
 *       the asset filter without forcing the WO modal open.
 * ════════════════════════════════════════════════════════════════ */

import { getState, setState, subscribe } from '../core/state.js';
import { getAssetMeta } from '../core/asset_metadata.js';
import { getGridState } from '../core/power_grid.js';
import { playClick } from '../core/sound.js';

const TREND_LEN = 60;          // samples
const TREND_INTERVAL_MS = 1000;

let _panelEl   = null;
let _chart     = null;          // Chart.js instance
let _trendTimer = null;
let _initialized = false;

// ─── Mount + DOM ──────────────────────────────────────────────────

function _ensureMount() {
    let mount = document.getElementById('sld-info-panel');
    if (mount) { _panelEl = mount; return mount; }
    // Create the panel as a sibling of pid-canvas
    const view = document.getElementById('view-power');
    const canvas = view ? view.querySelector('.pid-canvas') : null;
    if (!view || !canvas) return null;
    // Wrap canvas + new panel in a stage-row grid container
    let row = view.querySelector('.sld-stage-row');
    if (!row) {
        row = document.createElement('div');
        row.className = 'sld-stage-row';
        view.insertBefore(row, canvas);
        row.appendChild(canvas);  // moves canvas into the row
    }
    mount = document.createElement('aside');
    mount.id = 'sld-info-panel';
    mount.className = 'sld-info-panel';
    row.appendChild(mount);
    _panelEl = mount;
    return mount;
}

function _renderOverview() {
    const grid = getGridState() || {};
    const tripped     = Object.values(grid).filter((n) => n.tripped).length;
    const onBattery   = Object.values(grid).filter((n) => n.on_battery).length;
    const transferring = Object.values(grid).filter((n) => n.transferring).length;
    const liveA = Object.values(grid).filter((n) => n.path === 'A' && n.alive).length;
    const liveB = Object.values(grid).filter((n) => n.path === 'B' && n.alive).length;
    const totalA = Object.values(grid).filter((n) => n.path === 'A').length;
    const totalB = Object.values(grid).filter((n) => n.path === 'B').length;

    let banner = 'NOMINAL';
    let bannerTone = 'ok';
    if (tripped > 0)               { banner = `${tripped} TRIPPED`;        bannerTone = 'crit'; }
    else if (transferring > 0)     { banner = 'TRANSFERRING';              bannerTone = 'warn'; }
    else if (onBattery > 0)        { banner = `${onBattery} ON BATTERY`;   bannerTone = 'warn'; }

    return `
      <div class="sld-info-card sld-info-overview">
        <div class="sld-info-hdr">
          <div class="sld-info-eyebrow">SYSTEM</div>
          <div class="sld-info-title">2N Redundancy</div>
          <div class="sld-info-subtitle">Path Diversity</div>
        </div>
        <div class="sld-info-banner sld-tone-${bannerTone}">${banner}</div>
        <div class="sld-info-rows">
          <div class="sld-info-row"><span>Path A live</span><span>${liveA} / ${totalA}</span></div>
          <div class="sld-info-row"><span>Path B live</span><span>${liveB} / ${totalB}</span></div>
          <div class="sld-info-row"><span>Tripped</span><span class="${tripped ? 'tone-crit' : ''}">${tripped}</span></div>
          <div class="sld-info-row"><span>On battery</span><span class="${onBattery ? 'tone-warn' : ''}">${onBattery}</span></div>
          <div class="sld-info-row"><span>Transferring</span><span class="${transferring ? 'tone-warn' : ''}">${transferring}</span></div>
        </div>
        <div class="sld-info-footer">
          <span class="sld-info-hint">Click any node to inspect · shift-click or ⚡ pip to TRIP</span>
        </div>
      </div>
    `;
}

function _renderAssetDetail(id) {
    const meta = getAssetMeta(id);
    const grid = getGridState() || {};
    const node = grid[id];
    if (!meta) return _renderOverview();

    const stateBadge = _stateBadge(node);
    const detailRows = (meta.details || []).map(d =>
        `<div class="sld-info-row"><span>${d.k}</span><span>${d.v}</span></div>`
    ).join('');
    const manualLines = (meta.manuals || []).map(m => `<li>${m}</li>`).join('');

    return `
      <div class="sld-info-card sld-info-asset" data-asset="${id}">
        <button class="sld-info-close" id="sld-info-close" type="button" title="Close (return to overview)">×</button>
        <div class="sld-info-hdr">
          <div class="sld-info-eyebrow">${meta.type.toUpperCase()}</div>
          <div class="sld-info-title">${meta.label}</div>
          <div class="sld-info-subtitle">${meta.model}</div>
          <div class="sld-info-rating">${meta.rating}</div>
        </div>
        <div class="sld-info-state">${stateBadge}</div>

        <div class="sld-info-spark">
          <div class="sld-info-spark-hdr">
            <span>${meta.sparkline.label || meta.sparkline.unit}</span>
            <span class="sld-info-spark-now" id="sld-info-spark-now">—</span>
          </div>
          <canvas id="sld-info-sparkline" class="sld-info-sparkline" width="280" height="60"></canvas>
        </div>

        <div class="sld-info-rows">${detailRows}</div>

        ${manualLines ? `<div class="sld-info-manuals"><div class="sld-info-eyebrow">MANUALS</div><ul>${manualLines}</ul></div>` : ''}

        <div class="sld-info-actions">
          <button class="btn btn-secondary btn-sm sld-info-action" data-action="view-mop"  type="button">📖 View MOP</button>
          <button class="btn btn-secondary btn-sm sld-info-action" data-action="create-wo" type="button">🛠 Create Work Order</button>
          <button class="btn btn-secondary btn-sm sld-info-action" data-action="drill"     type="button">→ Open in Maintenance</button>
        </div>
      </div>
    `;
}

function _stateBadge(node) {
    if (!node) return '<span class="sld-state-badge sld-tone-info">UNKNOWN</span>';
    if (node.tripped)        return '<span class="sld-state-badge sld-tone-crit">TRIPPED</span>';
    if (!node.alive)         return '<span class="sld-state-badge sld-tone-crit">DEAD</span>';
    if (node.on_battery)     return '<span class="sld-state-badge sld-tone-warn">ON BATTERY</span>';
    if (node.transferring)   return '<span class="sld-state-badge sld-tone-warn">TRANSFERRING</span>';
    if (node.energized_by === 'genset') return '<span class="sld-state-badge sld-tone-warn">ON GENSET</span>';
    return `<span class="sld-state-badge sld-tone-ok">ENERGIZED · ${node.path || ''}</span>`;
}

// ─── Sparkline (Chart.js) ─────────────────────────────────────────

function _destroyChart() {
    if (_chart) { try { _chart.destroy(); } catch {} _chart = null; }
    if (_trendTimer) { clearInterval(_trendTimer); _trendTimer = null; }
}

function _seedTrend(id, meta) {
    const baseline = _liveSampleFor(id, meta);
    const range = meta.sparkline.range || 0;
    const samples = [];
    const now = Date.now();
    for (let i = TREND_LEN - 1; i >= 0; i--) {
        const v = baseline + (range > 0 ? (Math.random() - 0.5) * range : 0);
        samples.push({ t: now - i * TREND_INTERVAL_MS, v });
    }
    const trends = getState('assetTrends') || {};
    trends[id] = samples;
    setState('assetTrends', trends);
    return samples;
}

function _liveSampleFor(id, meta) {
    const grid = getGridState() || {};
    const node = grid[id];
    if (!node) return meta.sparkline.baseline || 0;
    // Special metrics: battery SOC is real
    if (node.type === 'batt') return node.soc != null ? node.soc : 100;
    // Genset rpm: 0 if not running, ~1800 if running, mid-spool if warming
    if (node.type === 'genset') {
        if (!node.alive) return 0;
        return 1800 + (Math.random() - 0.5) * 12;
    }
    // ATS pos: encoded as 1=primary, 2=transferring, 3=secondary
    if (node.type === 'ats') {
        if (node.transferring)     return 2;
        return node.ats_pos === 'primary' ? 1 : 3;
    }
    // Standard nodes: dead = 0; on_battery = 80% baseline (UPS holdup);
    // alive = baseline ± 0.5%
    const baseline = meta.sparkline.baseline || 0;
    const range = meta.sparkline.range || 0;
    if (!node.alive) return 0;
    if (node.on_battery) return baseline * 0.78 + (Math.random() - 0.5) * range * 0.4;
    if (node.energized_by === 'genset') return baseline * 0.92 + (Math.random() - 0.5) * range * 0.6;
    return baseline + (Math.random() - 0.5) * range;
}

function _mountSparkline(id) {
    const meta = getAssetMeta(id);
    if (!meta || !meta.sparkline) return;
    const canvas = document.getElementById('sld-info-sparkline');
    if (!canvas || !window.Chart) return;

    const samples = _seedTrend(id, meta);
    const labels = samples.map((_, i) => i);
    const data   = samples.map(s => s.v);

    _destroyChart();
    _chart = new window.Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
            labels,
            datasets: [{
                data,
                borderColor: meta.sparkline.color || '#00E5FF',
                backgroundColor: (meta.sparkline.color || '#00E5FF') + '22',
                borderWidth: 1.5,
                pointRadius: 0,
                fill: true,
                tension: 0.3,
            }],
        },
        options: {
            responsive: false,
            animation: false,
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
            scales: {
                x: { display: false },
                y: { display: false, grace: '5%' },
            },
            elements: { line: { borderJoinStyle: 'round' } },
        },
    });

    // Update "now" readout
    _updateSparkNow(samples[samples.length - 1].v, meta.sparkline.unit);

    // 1 Hz live push
    _trendTimer = setInterval(() => {
        if (!_chart) return;
        const v = _liveSampleFor(id, meta);
        const trends = getState('assetTrends') || {};
        const series = trends[id] || [];
        series.push({ t: Date.now(), v });
        if (series.length > TREND_LEN) series.shift();
        trends[id] = series;
        setState('assetTrends', trends);

        _chart.data.datasets[0].data = series.map(s => s.v);
        _chart.data.labels = series.map((_, i) => i);
        _chart.update('none');

        _updateSparkNow(v, meta.sparkline.unit);
    }, TREND_INTERVAL_MS);
}

function _updateSparkNow(v, unit) {
    const el = document.getElementById('sld-info-spark-now');
    if (!el) return;
    const decimals = v < 1 ? 3 : (v < 10 ? 2 : (v < 100 ? 1 : 0));
    el.textContent = v.toFixed(decimals) + (unit ? ' ' + unit : '');
}

// ─── Action handlers ──────────────────────────────────────────────

function _toast(msg, tone = 'info') {
    let host = document.getElementById('sld-info-toast');
    if (!host) {
        host = document.createElement('div');
        host.id = 'sld-info-toast';
        host.className = 'sld-info-toast';
        document.body.appendChild(host);
    }
    host.textContent = msg;
    host.dataset.tone = tone;
    host.classList.add('is-visible');
    clearTimeout(_toast._timer);
    _toast._timer = setTimeout(() => host.classList.remove('is-visible'), 2400);
}

function _onAction(action, assetId) {
    const meta = getAssetMeta(assetId);
    if (!meta) return;
    if (action === 'view-mop') {
        const m = (meta.manuals && meta.manuals[0]) || 'no MOP linked';
        _toast(`MOP: ${m}`, 'info');
        console.log('[asset_panel] view-mop', assetId, m);
    }
    else if (action === 'create-wo') {
        try { sessionStorage.setItem('cmms_focus_asset_id', assetId); } catch {}
        try { sessionStorage.setItem('cmms_open_create_modal', '1'); } catch {}
        _toast(`Open Maintenance · pre-fill WO for ${meta.label}`, 'ok');
        const navItem = document.querySelector('.nav-item[data-route="maintenance"]');
        if (navItem) navItem.click();
    }
    else if (action === 'drill') {
        try { sessionStorage.setItem('cmms_focus_asset_id', assetId); } catch {}
        _toast(`Open Maintenance · filter ${meta.label}`, 'ok');
        const navItem = document.querySelector('.nav-item[data-route="maintenance"]');
        if (navItem) navItem.click();
    }
    playClick();
}

// ─── Top-level render orchestrator ────────────────────────────────

function _render() {
    const mount = _ensureMount();
    if (!mount) return;
    const id = getState('selectedAsset');

    if (!id) {
        _destroyChart();
        mount.innerHTML = _renderOverview();
        // Also auto-update overview when grid changes
        return;
    }

    mount.innerHTML = _renderAssetDetail(id);
    queueMicrotask(() => _mountSparkline(id));

    // Wire panel-internal interactions
    const close = mount.querySelector('#sld-info-close');
    if (close) close.addEventListener('click', () => {
        setState('selectedAsset', null);
        playClick();
    });
    mount.querySelectorAll('.sld-info-action').forEach((btn) => {
        btn.addEventListener('click', () => _onAction(btn.dataset.action, id));
    });
}

// ─── Init ─────────────────────────────────────────────────────────

export function initAssetPanel() {
    if (_initialized) return;
    const mount = _ensureMount();
    if (!mount) return;
    subscribe('selectedAsset', _render);
    subscribe('grid', () => {
        // Re-render only when overview is showing OR re-render state badge
        const id = getState('selectedAsset');
        if (!id) {
            _render();
        } else {
            // Surgically update only the state badge (avoid destroying sparkline)
            const badge = _panelEl?.querySelector('.sld-info-state');
            if (badge) {
                const grid = getGridState() || {};
                badge.innerHTML = _stateBadge(grid[id]);
            }
        }
    });
    _render();
    _initialized = true;
    console.log('[asset_panel] mounted; subscribes to selectedAsset + grid');
}
