/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/rack_heatmap.js
 *
 * Tier B / B2: Rack Anomaly Heatmap.
 *
 * 50 GB200 NVL72 racks shown as cells in a Path A / Path B grid:
 *   - Each cell color-codes the rack's GPU Tj into 4 bands
 *   - Each cell BLINK-intensity tracks the Kalman z-score
 *     (higher anomaly = faster blink + sharper alarm border)
 *   - Click → opens a detail panel with sparkline + recent WOs
 *
 * Data sources:
 *   - Rack inventory: GET /api/cmms/assets?asset_type=it_rack
 *   - WO history: GET /api/cmms/work-orders?asset_id=…&only_open=true
 *   - Live Tj + Kalman z-score: T3.6 — subscribed to the `channels`
 *     state key (the Hermes `telemetry` channel_innovations payload).
 *     Real per-rack max_z drives the cell color band + anomaly blink.
 *     The deterministic sinusoid is now a STALE-FALLBACK only: it runs
 *     solely when no live channel data has arrived for
 *     LIVE_FALLBACK_GRACE_MS (e.g. the WS dropped).
 *
 * The Tesla Megapack / SpaceX Starlink Operations aesthetic — every
 * cell is one fleet element, the wall is the fleet, anomalies pop
 * without visual noise from healthy cells.
 *
 * Per ADR-006: visual advisory. Click → detail. No autonomous shed.
 * ════════════════════════════════════════════════════════════════ */

import { subscribe } from '../core/state.js';
import { registerRoute } from '../core/router.js';

const API_BASE = '';
const SPARK_LEN = 60;
const SIM_PERIOD_MS = 1000;            // 1 Hz fallback heartbeat
const LIVE_FALLBACK_GRACE_MS = 15_000; // sim resumes only after this live-data gap
const Z_THRESHOLD_ANOMALY = 3.0;

// ─── State ───────────────────────────────────────────────────────
let _initialized = false;
let _racks = [];                // Array<{ asset_id, ..., tj, z, sparkline:[], wos:[] }>
let _byId = new Map();
let _selectedId = null;
let _simTimer = null;
let _lastLiveTs = 0;            // T3.6: ts of the last live channels payload

// ─── HTML escape ─────────────────────────────────────────────────
function _esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[c]);
}

// ─── Tj band classifier (matches heat_overlay.js NVIDIA spec) ────
const BAND_THRESHOLDS = [
    { name: 'cold',   max: 60 },
    { name: 'normal', max: 78 },
    { name: 'warn',   max: 86 },
    { name: 'crit',   max: 999 },
];
function _bandFor(tjC) {
    if (typeof tjC !== 'number' || Number.isNaN(tjC)) return 'normal';
    for (const b of BAND_THRESHOLDS) if (tjC <= b.max) return b.name;
    return 'crit';
}

// ─── Deterministic simulator for demo when telemetry is absent ───
function _simulateTj(rackId, t, baselineC = 70) {
    // Use the rack id as a seed so each rack has its own phase.
    let seed = 0;
    for (let i = 0; i < rackId.length; i++) seed = (seed * 31 + rackId.charCodeAt(i)) >>> 0;
    const phase = (seed % 1000) / 1000 * Math.PI * 2;
    const swing = 4 + ((seed >> 4) % 5);    // 4-8°C swing band
    return baselineC + Math.sin(t / 4 + phase) * swing;
}
function _simulateZ(rackId, tjC) {
    // Higher Tj → higher z-score on average. Deterministic jitter.
    let seed = 0;
    for (let i = 0; i < rackId.length; i++) seed = (seed * 17 + rackId.charCodeAt(i)) >>> 0;
    const noise = ((seed % 100) / 100 - 0.5);    // -0.5..+0.5
    if (tjC < 60) return 0.5 + noise * 0.3;
    if (tjC < 78) return 1.2 + noise * 0.5;
    if (tjC < 86) return 2.6 + noise * 0.6;
    return 4.5 + noise * 0.8;                    // crit
}

// ─── Kick a "burst" — temporarily push a few racks into anomaly ──
let _burstUntilTs = 0;
let _burstRackIds = [];
function _triggerBurst() {
    if (_racks.length === 0) return;
    _burstUntilTs = Date.now() + 14_000;     // 14 s burst
    // Pick 3 racks deterministically: 17%, 50%, 83% through the array
    const N = _racks.length;
    _burstRackIds = [
        _racks[Math.floor(N * 0.17)]?.asset_id,
        _racks[Math.floor(N * 0.50)]?.asset_id,
        _racks[Math.floor(N * 0.83)]?.asset_id,
    ].filter(Boolean);
}

function _maybeBurst(rackId, tjC) {
    if (Date.now() > _burstUntilTs) return null;
    if (!_burstRackIds.includes(rackId)) return null;
    return { tj: 88 + (rackId.charCodeAt(rackId.length - 1) % 6), z: 5.5 };
}

// ─── Render: aggregate per-rack tj/z into meta counters + paint ──
function _renderAll() {
    let hot = 0, anomalous = 0;
    let tjMin = Infinity, tjMax = -Infinity;
    for (const r of _racks) {
        if (r.band === 'warn' || r.band === 'crit') hot++;
        if (r.z >= Z_THRESHOLD_ANOMALY) anomalous++;
        if (r.tj < tjMin) tjMin = r.tj;
        if (r.tj > tjMax) tjMax = r.tj;
    }
    _renderGrid();
    _renderMeta(_racks.length, anomalous, hot, tjMin, tjMax);
    if (_selectedId) _renderDetail();
}

// ─── Sim-fallback tick ───────────────────────────────────────────
// T3.6: runs ONLY when live channel data has gone stale for
// LIVE_FALLBACK_GRACE_MS — live Hermes telemetry is the primary source.
function _tick() {
    if (Date.now() - _lastLiveTs < LIVE_FALLBACK_GRACE_MS) return;
    const t = Date.now() / 1000;
    for (const r of _racks) {
        const burst = _maybeBurst(r.asset_id, r.tj);
        let tj, z;
        if (burst) {
            tj = burst.tj; z = burst.z;
        } else {
            tj = _simulateTj(r.asset_id, t, r._baseline_tj);
            z = _simulateZ(r.asset_id, tj);
        }
        r.tj = tj;
        r.z = z;
        r.band = _bandFor(tj);
        r.sparkline.push(tj);
        if (r.sparkline.length > SPARK_LEN) r.sparkline.shift();
    }
    _renderAll();
}

// ─── Render ──────────────────────────────────────────────────────
function _renderMeta(total, anomalous, hot, tjMin, tjMax) {
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    set('rack-heatmap-count', total);
    set('rack-heatmap-anomalous', anomalous);
    set('rack-heatmap-hot', hot);
    if (tjMin === Infinity) set('rack-heatmap-tj-range', '—');
    else set('rack-heatmap-tj-range', `${tjMin.toFixed(1)}–${tjMax.toFixed(1)} °C`);
}

function _renderGrid() {
    const root = document.getElementById('rack-heatmap-grid');
    if (!root) return;
    if (_racks.length === 0) {
        root.innerHTML = '<div class="rack-heatmap-loading">No it_rack assets in CMMS. Run replay_demo.ps1.</div>';
        return;
    }
    // Group by path (A / B / unset)
    const groups = { A: [], B: [], '?': [] };
    for (const r of _racks) {
        const p = r.path === 'A' ? 'A' : r.path === 'B' ? 'B' : '?';
        groups[p].push(r);
    }
    const cellHTML = (r) => {
        const isSel = r.asset_id === _selectedId;
        const blinkSpeed = r.z >= Z_THRESHOLD_ANOMALY
            ? Math.max(0.4, 1.4 - r.z * 0.18).toFixed(2) + 's'
            : '0s';
        const style = blinkSpeed !== '0s'
            ? `style="--rack-blink-speed:${blinkSpeed}"`
            : '';
        return `<button class="rack-cell rack-cell-${r.band}${isSel ? ' rack-cell-selected' : ''}${r.z >= Z_THRESHOLD_ANOMALY ? ' rack-cell-anomaly' : ''}"
                        data-rack-id="${_esc(r.asset_id)}" type="button" ${style}
                        title="${_esc(r.asset_id)} · Tj ${r.tj.toFixed(1)}°C · z=${r.z.toFixed(2)}">
                    <span class="rack-cell-id">${_esc((r.asset_id.match(/_([0-9]+)_([0-9]+)$/) || ['', '?', '?']).slice(1).join('-'))}</span>
                    <span class="rack-cell-tj">${r.tj.toFixed(0)}°</span>
                    <span class="rack-cell-z">z${r.z.toFixed(1)}</span>
                </button>`;
    };
    const groupHTML = (label, list, cls) => list.length ? `
        <div class="rack-group ${cls}">
            <div class="rack-group-label">Path ${label} <span class="rack-group-count">${list.length}</span></div>
            <div class="rack-group-cells">${list.map(cellHTML).join('')}</div>
        </div>` : '';
    root.innerHTML =
        groupHTML('A', groups.A, 'rack-group-a') +
        groupHTML('B', groups.B, 'rack-group-b') +
        groupHTML('—', groups['?'], 'rack-group-other');
}

function _renderDetail() {
    const box = document.getElementById('rack-heatmap-detail');
    if (!box) return;
    if (!_selectedId) { box.setAttribute('hidden', ''); return; }
    const r = _byId.get(_selectedId);
    if (!r) { box.setAttribute('hidden', ''); return; }
    box.removeAttribute('hidden');

    const set = (id, val, dataAttr) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = val;
        if (dataAttr) el.setAttribute('data-band', dataAttr);
    };
    set('rack-heatmap-detail-id', r.asset_id);
    set('rack-heatmap-detail-tj', r.tj.toFixed(2) + ' °C');
    set('rack-heatmap-detail-band', r.band, r.band);
    set('rack-heatmap-detail-z', r.z.toFixed(2));
    set('rack-heatmap-detail-path', r.path || '—');
    set('rack-heatmap-detail-crit', r.criticality_class || '—');
    set('rack-heatmap-detail-wos', String(r.wos?.length || 0));

    // Sparkline SVG
    _renderSparkline(r);
    // WO list
    const woList = document.getElementById('rack-heatmap-detail-wo-list');
    if (woList) {
        if (!r.wos || r.wos.length === 0) {
            woList.innerHTML = '<div class="rack-empty">No open work orders.</div>';
        } else {
            woList.innerHTML = r.wos.map(w => `
                <div class="rack-wo">
                    <span class="rack-wo-id">${_esc(w.work_order_id || '?')}</span>
                    <span class="rack-wo-pri">${_esc(w.priority || '?')}</span>
                    <span class="rack-wo-status">${_esc(w.status || '?')}</span>
                    <span class="rack-wo-summary">${_esc((w.issue_summary || '').slice(0, 80))}</span>
                </div>
            `).join('');
        }
    }
}

function _renderSparkline(r) {
    const svg = document.getElementById('rack-heatmap-detail-spark');
    if (!svg || !r.sparkline || r.sparkline.length < 2) {
        if (svg) svg.innerHTML = '';
        return;
    }
    const data = r.sparkline;
    const W = 280, H = 70;
    const tjMin = Math.min(...data) - 1;
    const tjMax = Math.max(...data) + 1;
    const range = tjMax - tjMin || 1;
    const points = data.map((v, i) => {
        const x = (i / (data.length - 1)) * W;
        const y = H - ((v - tjMin) / range) * H;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    // Threshold line at 86°C if it falls in range
    let threshLine = '';
    if (tjMin <= 86 && 86 <= tjMax) {
        const y = H - ((86 - tjMin) / range) * H;
        threshLine = `<line x1="0" y1="${y}" x2="${W}" y2="${y}"
                            stroke="#ef4444" stroke-width="0.6" stroke-dasharray="3 2" opacity="0.5"/>`;
    }
    svg.innerHTML = `
        ${threshLine}
        <polyline points="${points}" fill="none"
                  stroke="${r.band === 'crit' ? '#ef4444' : r.band === 'warn' ? '#f59e0b' : '#00B8D4'}"
                  stroke-width="1.5" stroke-linejoin="round"/>
        <text x="2" y="9" font-family="JetBrains Mono,Consolas,monospace" font-size="8"
              fill="#6a7a8b">${tjMax.toFixed(0)}°</text>
        <text x="2" y="${H - 2}" font-family="JetBrains Mono,Consolas,monospace" font-size="8"
              fill="#6a7a8b">${tjMin.toFixed(0)}°</text>`;
}

// ─── Event handlers ──────────────────────────────────────────────
function _onCellClick(e) {
    const btn = e.target.closest('[data-rack-id]');
    if (!btn) return;
    const id = btn.dataset.rackId;
    if (_selectedId === id) {
        _selectedId = null;
    } else {
        _selectedId = id;
        _maybeFetchWOs(id);
    }
    _renderGrid();
    _renderDetail();
}

async function _maybeFetchWOs(rackId) {
    const r = _byId.get(rackId);
    if (!r) return;
    if (r._wos_fetched_at && Date.now() - r._wos_fetched_at < 30_000) return;
    try {
        const resp = await fetch(`${API_BASE}/api/cmms/work-orders?asset_id=${encodeURIComponent(rackId)}&only_open=true&limit=20`);
        if (!resp.ok) return;
        const data = await resp.json();
        r.wos = data.work_orders || [];
        r._wos_fetched_at = Date.now();
        if (_selectedId === rackId) _renderDetail();
    } catch { /* swallow */ }
}

function _onDetailClose() {
    _selectedId = null;
    _renderGrid();
    _renderDetail();
}

function _onSimulateBurst() {
    _triggerBurst();
}

function _onRefresh() {
    _loadRacks();
}

// ─── Live Kalman hook (T3.6) ─────────────────────────────────────
// Subscribes to the `channels` state key — the Hermes telemetry
// channel_innovations payload. Maps each rack's gpu_Tj_c channel:
// last_emission → cell temperature, max_z → Kalman z-score (which
// drives the cell color band + anomaly blink). Real data supersedes
// the deterministic simulator.
function _onChannels(channels) {
    if (!channels || typeof channels !== 'object') return;
    let touched = false;
    for (const r of _racks) {
        // Channel ids are scoped '<asset_id>:<metric>' by the simulator.
        const ch = channels[`${r.asset_id}:gpu_Tj_c`];
        if (!ch) continue;
        if (typeof ch.last_emission === 'number') {
            r.tj = ch.last_emission;
            r.band = _bandFor(r.tj);
        }
        if (typeof ch.max_z === 'number') r.z = ch.max_z;
        r.sparkline.push(r.tj);
        if (r.sparkline.length > SPARK_LEN) r.sparkline.shift();
        touched = true;
    }
    if (touched) {
        _lastLiveTs = Date.now();
        _renderAll();
    }
}

// ─── Bootstrap ───────────────────────────────────────────────────
async function _loadRacks() {
    try {
        const resp = await fetch(`${API_BASE}/api/cmms/assets?asset_type=it_rack&limit=200`);
        if (!resp.ok) {
            console.warn('[rack_heatmap] assets fetch failed', resp.status);
            return;
        }
        const data = await resp.json();
        const assets = data.assets || [];
        _racks = assets.map(a => ({
            asset_id:           a.asset_id,
            display_name:       a.display_name,
            path:                a.path,
            criticality_class:   a.criticality_class,
            _baseline_tj:        70 + ((a.asset_id.charCodeAt(a.asset_id.length - 1) % 7) - 3),  // 67-73 baseline
            tj:                  70,
            z:                   1.0,
            band:                'normal',
            sparkline:           [],
            wos:                 [],
        }));
        _byId = new Map(_racks.map(r => [r.asset_id, r]));
        _renderGrid();
        if (_simTimer) clearInterval(_simTimer);
        _simTimer = setInterval(_tick, SIM_PERIOD_MS);
        _tick();   // first paint immediate
        console.log('[rack_heatmap] loaded %d racks, ticking @ %d ms', _racks.length, SIM_PERIOD_MS);
    } catch (e) {
        console.warn('[rack_heatmap] load error:', e);
    }
}

function _wireEvents() {
    document.getElementById('rack-heatmap-grid')?.addEventListener('click', _onCellClick);
    document.getElementById('rack-heatmap-detail-close')?.addEventListener('click', _onDetailClose);
    document.getElementById('rack-heatmap-simulate')?.addEventListener('click', _onSimulateBurst);
    document.getElementById('rack-heatmap-refresh')?.addEventListener('click', _onRefresh);
    // T3.6: live Kalman channel_innovations from the Hermes telemetry stream.
    try { subscribe('channels', _onChannels); } catch { /* state bus optional */ }
}

function _wireRouting() {
    // T2.2: declarative registry (replaces the setTimeout(0) LOTO race).
    registerRoute('rack-heatmap', {
        viewId: 'view-rack-heatmap',
        activate: ({ firstActivation }) => {
            if (firstActivation) _loadRacks();
        },
    });
}

export function initRackHeatmapView() {
    if (_initialized) return;
    if (!document.getElementById('view-rack-heatmap')) {
        console.warn('[rack_heatmap] view block not in DOM');
        return;
    }
    _wireEvents();
    _wireRouting();
    _initialized = true;
    console.log('[rack_heatmap] view ready (Tier B / B2)');
}

export function stopRackHeatmap() {
    if (_simTimer) { clearInterval(_simTimer); _simTimer = null; }
}

// ─── Test surface (T3.6) ─────────────────────────────────────────
export const __rack_heatmap_test__ = {
    onChannels: _onChannels,
    bandFor: _bandFor,
    seedRacks(rackArr) {
        _racks = rackArr.map(a => ({
            asset_id: a.asset_id, path: a.path || 'A',
            _baseline_tj: 70, tj: 70, z: 1.0, band: 'normal',
            sparkline: [], wos: [],
        }));
        _byId = new Map(_racks.map(r => [r.asset_id, r]));
    },
    getRack(id) { return _byId.get(id); },
    lastLiveTs() { return _lastLiveTs; },
    reset() { _racks = []; _byId = new Map(); _selectedId = null; _lastLiveTs = 0; },
};
