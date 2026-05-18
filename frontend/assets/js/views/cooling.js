/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/cooling.js
 * ROADMAP V11 T2.1 — Cooling (DLC) P&ID view extracted from app.js.
 *
 * Phase 2a — behaviour-preserving migration of the cooling P&ID data
 * binder out of the monolithic app.js IIFE. Visual reinvention (2b)
 * and the L3 control plane (2c) land in follow-up commits.
 *
 *   - registerRoute('cooling', …) hands navigation to core/router.js.
 *   - getTopologyState() (services/api.js) fetches the physics-
 *     validated /api/topology/state rollup; the legacy 5 s poll is
 *     preserved here (2a is behaviour-preserving — 2c swaps it for the
 *     Hermes telemetry stream).
 *   - _applyCoolingPid stamps per-node severity + metric text on the
 *     static #view-cooling P&ID SVG, exactly as the IIFE did.
 * ════════════════════════════════════════════════════════════════ */

import { registerRoute } from '../core/router.js';
import { getTopologyState } from '../services/api.js';

let _initialized = false;
let _refreshTimer = null;

// ─── P&ID data binder (port of the legacy applyCoolingPid) ─────────
function _applyCoolingPid(data) {
    if (!data) return;
    const nodes = data.hld_nodes || {};

    // Severity -> data-sev on each P&ID node symbol.
    const sevMap = {
        cooling_tower: 'cooling_tower',
        chiller_1: 'chiller_1',
        chiller_2: 'chiller_2',
        cdu_a: 'cdu_a',
        cdu_b: 'cdu_b',
        xfmr_a_p: 'xfmr_a',
        xfmr_b_p: 'xfmr_b',
        grid_a: 'utility_north',
        grid_b: 'utility_south',
    };
    Object.entries(sevMap).forEach(([pidNodeId, dataNodeId]) => {
        const nodeData = nodes[dataNodeId];
        if (!nodeData) return;
        const el = document.querySelector(`.pid-node[data-node="${pidNodeId}"]`);
        const symbol = el && el.querySelector('.pid-symbol');
        if (symbol) symbol.setAttribute('data-sev', nodeData.severity || 'ok');
    });

    const ct = nodes.cooling_tower;
    const ch1 = nodes.chiller_1;
    const ch2 = nodes.chiller_2;
    const cda = nodes.cdu_a;
    const cdb = nodes.cdu_b;
    const xfa = nodes.xfmr_a;
    const xfb = nodes.xfmr_b;
    const ga = nodes.utility_north;
    const gb = nodes.utility_south;
    const h1 = nodes.hall_1;

    const set = (k, v) => {
        const el = document.querySelector(`[data-pid-metric="${k}"]`);
        if (el) el.textContent = v;
    };
    if (ct) {
        set('ct-wb', 'WB ' + (ct.metrics.wb_c?.toFixed(1) ?? '—') + '°C');
        set('ct-ecwt', 'ECWT ' + (ct.metrics.ecwt_c?.toFixed(1) ?? '—') + '°C');
    }
    if (ch1) set('ch1-cop', 'COP ' + (ch1.metrics.cop?.toFixed(1) ?? '—'));
    if (ch2) set('ch2-cop', 'COP ' + (ch2.metrics.cop?.toFixed(1) ?? '—'));
    if (cda) {
        set('cdua-q', Math.round(cda.metrics.q_kw ?? 0).toLocaleString() + ' kW');
        set('cdua-supply', 'SUP ' + (h1?.metrics.inlet_c?.toFixed(0) ?? '18') + '°C');
    }
    if (cdb) {
        set('cdub-q', Math.round(cdb.metrics.q_kw ?? 0).toLocaleString() + ' kW');
        set('cdub-supply', 'SUP ' + (h1?.metrics.inlet_c?.toFixed(0) ?? '18') + '°C');
    }
    if (xfa) set('xfmr-a-c', (xfa.metrics.winding_c?.toFixed(0) ?? '—') + '°C');
    if (xfb) set('xfmr-b-c', (xfb.metrics.winding_c?.toFixed(0) ?? '—') + '°C');
    if (ga) set('grid-a-kw', Math.round(ga.metrics.kw ?? 0).toLocaleString() + ' kW');
    if (gb) set('grid-b-kw', Math.round(gb.metrics.kw ?? 0).toLocaleString() + ' kW');

    // GPU Tj from rack data.
    if (Array.isArray(data.lld_racks) && data.lld_racks.length > 0) {
        const maxTj = Math.max(...data.lld_racks.map((r) => r.gpu_tj_c || 0));
        set('rack-tj', 'GPU Tj max: ' + maxTj.toFixed(1) + '°C');
    }

    // Failover + redundancy banner.
    const banner = document.getElementById('pid-banner-mode');
    const bannerSub = document.getElementById('pid-banner-sub');
    const bannerShi = document.getElementById('pid-banner-shi');
    const failLine = document.getElementById('pid-failover-line');
    const failText = document.getElementById('pid-failover-text');

    const mode = data.redundancy_mode || '2N';
    if (banner) {
        banner.textContent = mode;
        banner.setAttribute('data-mode', mode);
    }
    if (bannerSub) {
        bannerSub.textContent = ({
            '2N': 'Path Diversity Active',
            'N+1': 'One side degraded',
            'N': 'NON-REDUNDANT — investigate',
        })[mode] || mode;
    }
    if (bannerShi) bannerShi.textContent = (data.site_health ?? 0).toFixed(2);

    const showFailover = (mode === 'N');
    if (failLine) failLine.setAttribute('opacity', showFailover ? '0.9' : '0');
    if (failText) failText.setAttribute('opacity', showFailover ? '1' : '0');

    const meta = document.getElementById('pid-meta');
    if (meta) {
        meta.innerHTML = `<strong>${mode}</strong> · SHI `
            + `${(data.site_health ?? 0).toFixed(2)} · weakest `
            + `<em>${data.weakest_module || '—'}</em>`;
    }
}

// ════════════════════════════════════════════════════════════════
//  PHASE 2b — orthogonal thermodynamic SCADA SLD
//
//  Replaces the hand-authored P&ID SVG with a programmatic generator.
//  5 fixed tier columns (Heat Rejection -> Chillers -> Pumps -> CDU ->
//  Load), strict grid alignment; every pipe a pure 90° run. Chilled-
//  water SUPPLY glows blue, warm RETURN glows warm. Nodes keep the
//  data-node / .pid-symbol / data-pid-metric hooks so the (unchanged)
//  _applyCoolingPid binder drives severity + metrics.
// ════════════════════════════════════════════════════════════════
const _COOL = { supplyY: 196, returnY: 432 };

function _coolSymbol(type, x, y) {
    if (type === 'pump') {
        return `<circle class="pid-symbol cool-sym" data-sev="ok" cx="${x}" cy="${y}" r="21"/>`
            + `<path class="cool-glyph" d="M${x - 9} ${y} L${x + 8} ${y - 8} `
            + `L${x + 8} ${y + 8} Z"/>`;
    }
    if (type === 'tower') {
        return `<rect class="pid-symbol cool-sym" data-sev="ok" x="${x - 42}" `
            + `y="${y - 32}" width="84" height="64" rx="3"/>`
            + `<path class="cool-fin" d="M${x - 30} ${y - 14} H${x + 30} `
            + `M${x - 30} ${y + 2} H${x + 30} M${x - 30} ${y + 18} H${x + 30}"/>`;
    }
    const w = type === 'hall' ? 100 : (type === 'crah' ? 56 : 80);
    const h = type === 'hall' ? 58 : (type === 'crah' ? 34 : 46);
    return `<rect class="pid-symbol cool-sym" data-sev="ok" x="${x - w / 2}" `
        + `y="${y - h / 2}" width="${w}" height="${h}" rx="2.5"/>`;
}

function _coolNode(id, type, label, x, y, metrics) {
    const m = metrics.map((mm, i) =>
        `<text class="cool-metric" data-pid-metric="${mm.key}" x="${x}" `
        + `y="${y + 42 + i * 13}">${mm.text}</text>`).join('');
    return `<g class="pid-node cool-node" data-node="${id}">`
        + _coolSymbol(type, x, y)
        + `<text class="cool-name" x="${x}" y="${y - 38}">${label}</text>`
        + m + `</g>`;
}

// Orthogonal pipe — caller passes axis-aligned waypoints only.
function _coolPipe(points, kind) {
    const d = points.map((p, i) => (i === 0 ? 'M' : 'L') + p[0] + ' ' + p[1]).join(' ');
    return `<path class="cool-pipe cool-${kind}" d="${d}"/>`;
}

/** Build the full thermodynamic SLD inner markup. */
function _buildCoolingSld() {
    const S = _COOL.supplyY;   // chilled-water supply header
    const R = _COOL.returnY;   // warm-water return header
    const T = { rej: 128, chiller: 322, pump: 506, cdu: 694, load: 902 };

    const tiers = [
        ['HEAT REJECTION', T.rej], ['CHILLER PLANT', T.chiller],
        ['CHW PUMPS', T.pump], ['CDU / DLC', T.cdu], ['IT LOAD', T.load],
    ];
    const rails = tiers.map(([name, x]) =>
        `<line class="cool-tier-rail" x1="${x}" y1="44" x2="${x}" y2="586"/>`
        + `<text class="cool-tier-label" x="${x}" y="30">${name}</text>`).join('');

    // ── orthogonal piping ──
    const pipes = [
        // chilled-water supply header (cold) — tower up, then across
        _coolPipe([[T.rej, 282], [T.rej, S], [T.load, S]], 'supply'),
        // warm return header — load down, back across, into the tower
        _coolPipe([[T.load, 274], [T.load, R], [T.rej, R], [T.rej, 346]], 'return'),
        // chiller / pump / CDU taps off the supply header
        _coolPipe([[T.chiller, S], [T.chiller, 173]], 'supply'),
        _coolPipe([[T.chiller, S], [T.chiller, 247]], 'supply'),
        _coolPipe([[T.pump, S], [T.pump, 175]], 'supply'),
        _coolPipe([[T.pump, S], [T.pump, 245]], 'supply'),
        _coolPipe([[T.cdu, S], [T.cdu, 173]], 'supply'),
        _coolPipe([[T.cdu, S], [T.cdu, 247]], 'supply'),
        // CRAH warm-air drops below the IT load
        _coolPipe([[T.load, R], [T.load, 470]], 'return'),
        _coolPipe([[845, 470], [959, 470]], 'return'),
        _coolPipe([[845, 470], [845, 488]], 'return'),
        _coolPipe([[959, 470], [959, 488]], 'return'),
    ].join('');

    // ── equipment nodes ──
    const nodes = [
        _coolNode('cooling_tower', 'tower', 'COOLING TOWER', T.rej, 314,
            [{ key: 'ct-wb', text: 'WB —°C' }, { key: 'ct-ecwt', text: 'ECWT —°C' }]),
        _coolNode('chiller_1', 'chiller', 'CHILLER 1', T.chiller, 150,
            [{ key: 'ch1-cop', text: 'COP —' }]),
        _coolNode('chiller_2', 'chiller', 'CHILLER 2 · N+1', T.chiller, 270,
            [{ key: 'ch2-cop', text: 'COP —' }]),
        _coolNode('chwp_1', 'pump', 'CHW PUMP A', T.pump, 154, []),
        _coolNode('chwp_2', 'pump', 'CHW PUMP B', T.pump, 266, []),
        _coolNode('cdu_a', 'cdu', 'CDU-A', T.cdu, 150,
            [{ key: 'cdua-q', text: '— kW' }, { key: 'cdua-supply', text: 'SUP —°C' }]),
        _coolNode('cdu_b', 'cdu', 'CDU-B', T.cdu, 270,
            [{ key: 'cdub-q', text: '— kW' }, { key: 'cdub-supply', text: 'SUP —°C' }]),
        _coolNode('data_hall', 'hall', 'DATA HALL', T.load, 222,
            [{ key: 'rack-tj', text: 'GPU Tj —°C' }]),
        _coolNode('crah_1', 'crah', 'CRAH-1', 845, 506, []),
        _coolNode('crah_2', 'crah', 'CRAH-2', 959, 506, []),
    ].join('');

    return rails + pipes + nodes;
}

/** Render the orthogonal cooling SLD into the legacy .pid-svg. */
function _renderCoolingSld() {
    const svg = document.querySelector('#view-cooling .pid-svg');
    if (!svg) return;
    svg.setAttribute('viewBox', '0 0 1040 620');
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    svg.classList.add('cool-svg');
    svg.innerHTML = _buildCoolingSld();
}

// ─── Data refresh + routing ────────────────────────────────────────
async function _refresh() {
    try {
        _applyCoolingPid(await getTopologyState());
    } catch (e) {
        console.warn('[cooling] topology fetch failed:', e.message);
    }
}

function _activate() {
    _refresh();
    // Behaviour-preserving 5 s poll (2c replaces this with Hermes).
    if (!_refreshTimer) _refreshTimer = setInterval(_refresh, 5000);
}

/** Public entry — called once from main.js at bootstrap. */
export function initCoolingView() {
    if (_initialized) return;
    if (!document.getElementById('view-cooling')) {
        console.warn('[cooling] #view-cooling not in DOM; view disabled.');
        return;
    }
    registerRoute('cooling', { viewId: 'view-cooling', activate: _activate });
    // Phase 2b: render the orthogonal thermodynamic SLD into .pid-svg,
    // replacing the hand-authored P&ID SVG.
    _renderCoolingSld();
    _initialized = true;
    console.log('[cooling] view ready (orthogonal thermodynamic SCADA SLD — T2.1)');
}

// ─── Test surface ──────────────────────────────────────────────────
export const __cooling_test__ = {
    applyCoolingPid: _applyCoolingPid,
    buildCoolingSld: _buildCoolingSld,
    renderCoolingSld: _renderCoolingSld,
    reset: () => {
        _initialized = false;
        if (_refreshTimer) { clearInterval(_refreshTimer); _refreshTimer = null; }
    },
};
