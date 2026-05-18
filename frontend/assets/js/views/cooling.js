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
    _initialized = true;
    console.log('[cooling] view ready (DLC P&ID — T2.1 ES module)');
}

// ─── Test surface ──────────────────────────────────────────────────
export const __cooling_test__ = {
    applyCoolingPid: _applyCoolingPid,
    reset: () => {
        _initialized = false;
        if (_refreshTimer) { clearInterval(_refreshTimer); _refreshTimer = null; }
    },
};
