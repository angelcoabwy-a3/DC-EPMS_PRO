/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/power.js
 * ROADMAP V11 T2.1 — Power & UPS SLD view extracted from app.js.
 *
 * Behaviour-preserving migration of the Power Single-Line-Diagram
 * data-binder out of the monolithic app.js IIFE. The 2.5D isometric
 * rendering ENGINE (core/power_sld.js, power_grid.js, power_cam.js,
 * views/power_ups_iso.js) is intentionally untouched — this module
 * owns only the *data plane*:
 *
 *   - registerRoute('power', …) hands navigation to core/router.js.
 *   - getTopologyState() (services/api.js) fetches the physics-
 *     validated /api/topology/state rollup ONCE on view activation —
 *     the baseline node severity, metrics, ΣP balance, redundancy.
 *   - The legacy 5 s setInterval poll is ERADICATED. Live reactivity
 *     is now driven by the Project Hermes `telemetry` stream: every
 *     1 Hz frame maps the live Kalman channel Z-scores onto per-node
 *     severity (`data-sev`) on the iso blocks — "live Kalman into the
 *     DAG nodes".
 *
 * Test surface: __power_test__ exposes the pure mapping helpers.
 * ════════════════════════════════════════════════════════════════ */

import { registerRoute } from '../core/router.js';
import { onHermesStream, getTopologyState } from '../services/api.js';

let _initialized = false;
let _unsubTelemetry = null;

// SLD-node-id -> /api/topology/state hld_nodes key.
const _NODE_MAP = {
    util_a: 'utility_north', util_b: 'utility_south',
    xfmr_a: 'xfmr_a', xfmr_b: 'xfmr_b',
    ups_a: 'ups_a', ups_b: 'ups_b',
    batt_a: 'ups_a', batt_b: 'ups_b',
    rpp_a1: 'rpp_a1', rpp_a2: 'rpp_a2', rpp_b1: 'rpp_b1', rpp_b2: 'rpp_b2',
    busway_a: 'busway_a', busway_b: 'busway_b',
};

// ─── Helpers ───────────────────────────────────────────────────────
function _setMetric(key, value) {
    const el = document.querySelector(`[data-sld-metric="${key}"]`);
    if (el) el.textContent = value;
}

/**
 * Derive a coarse SCADA severity from a set of Kalman channel fields.
 * Pure — exposed for tests. is_anomalous -> critical; |max_z|>=2 ->
 * warning; otherwise ok.
 */
function _severityFromChannels(fieldsList) {
    let sev = 'ok';
    for (const f of fieldsList) {
        if (!f) continue;
        if (f.is_anomalous) return 'critical';
        if (Math.abs(Number(f.max_z) || 0) >= 2) sev = 'warning';
    }
    return sev;
}

// ─── Topology data plane (port of the legacy applyPowerSld) ────────
function _applyTopology(data) {
    if (!data) return;
    const nodes = data.hld_nodes || {};

    // Severity on the static-SVG fallback symbols (legacy print layer).
    Object.entries(_NODE_MAP).forEach(([sldId, dataId]) => {
        const nodeData = nodes[dataId];
        if (!nodeData) return;
        const el = document.querySelector(`.sld-node[data-sld-node="${sldId}"]`);
        const symbol = el && el.querySelector('.pid-symbol');
        if (symbol) symbol.setAttribute('data-sev', nodeData.severity || 'ok');
    });

    const ua = nodes.utility_north, ub = nodes.utility_south;
    const xa = nodes.xfmr_a, xb = nodes.xfmr_b;
    const upa = nodes.ups_a, upb = nodes.ups_b;

    if (ua) {
        _setMetric('util_a-kw', Math.round(ua.metrics.kw ?? 0).toLocaleString() + ' kW');
        _setMetric('util_a-kv', (ua.metrics.kv ?? 27.5).toFixed(1) + ' kV');
    }
    if (ub) {
        _setMetric('util_b-kw', Math.round(ub.metrics.kw ?? 0).toLocaleString() + ' kW');
        _setMetric('util_b-kv', (ub.metrics.kv ?? 27.5).toFixed(1) + ' kV');
    }
    if (xa) {
        _setMetric('xfmr_a-c', (xa.metrics.winding_c ?? 0).toFixed(0) + '°C');
        _setMetric('xfmr_a-load', Math.round(xa.metrics.load_kva ?? 0).toLocaleString() + ' kVA');
    }
    if (xb) {
        _setMetric('xfmr_b-c', (xb.metrics.winding_c ?? 0).toFixed(0) + '°C');
        _setMetric('xfmr_b-load', Math.round(xb.metrics.load_kva ?? 0).toLocaleString() + ' kVA');
    }
    if (upa) {
        const eff = ((upa.metrics.eff ?? 0.96) * 100).toFixed(1);
        _setMetric('ups_a-mode', upa.metrics.battery_on_load ? 'BATTERY' : 'ONLINE');
        _setMetric('ups_a-load', Math.round(upa.metrics.load_kw ?? 0).toLocaleString() + ' kW · Eff ' + eff + '%');
        _setMetric('batt_a-soc', 'SOC ' + Math.round((upa.metrics.soc ?? 1) * 100) + '%');
    }
    if (upb) {
        const eff = ((upb.metrics.eff ?? 0.96) * 100).toFixed(1);
        _setMetric('ups_b-mode', upb.metrics.battery_on_load ? 'BATTERY' : 'ONLINE');
        _setMetric('ups_b-load', Math.round(upb.metrics.load_kw ?? 0).toLocaleString() + ' kW · Eff ' + eff + '%');
        _setMetric('batt_b-soc', 'SOC ' + Math.round((upb.metrics.soc ?? 1) * 100) + '%');
    }

    const rppA1 = nodes.rpp_a1, rppA2 = nodes.rpp_a2;
    const rppB1 = nodes.rpp_b1, rppB2 = nodes.rpp_b2;
    const bwyA = nodes.busway_a, bwyB = nodes.busway_b;
    if (rppA1) _setMetric('rpp_a1-kw', Math.round(rppA1.metrics.load_kw ?? 0).toLocaleString() + ' kW');
    if (rppA2) _setMetric('rpp_a2-kw', Math.round(rppA2.metrics.load_kw ?? 0).toLocaleString() + ' kW');
    if (rppB1) _setMetric('rpp_b1-kw', Math.round(rppB1.metrics.load_kw ?? 0).toLocaleString() + ' kW');
    if (rppB2) _setMetric('rpp_b2-kw', Math.round(rppB2.metrics.load_kw ?? 0).toLocaleString() + ' kW');
    if (bwyA) {
        const overload = bwyA.metrics.overload ? ' ⚠ OVERLOAD' : '';
        _setMetric('busway_a-load', Math.round(bwyA.metrics.load_kw ?? 0).toLocaleString()
            + ' kW · ' + Math.round(bwyA.metrics.current_a ?? 0) + ' A' + overload);
    }
    if (bwyB) {
        const overload = bwyB.metrics.overload ? ' ⚠ OVERLOAD' : '';
        _setMetric('busway_b-load', Math.round(bwyB.metrics.load_kw ?? 0).toLocaleString()
            + ' kW · ' + Math.round(bwyB.metrics.current_a ?? 0) + ' A' + overload);
    }

    // ATS / genset state derived from UPS battery-on-load.
    const atsA = (upa && upa.metrics.battery_on_load) ? 'GENSET' : 'UTILITY';
    const atsB = (upb && upb.metrics.battery_on_load) ? 'GENSET' : 'UTILITY';
    _setMetric('ats_a-pos', atsA);
    _setMetric('ats_b-pos', atsB);
    _setMetric('genset_a-state', atsA === 'GENSET' ? 'RUNNING' : 'STANDBY');
    _setMetric('genset_b-state', atsB === 'GENSET' ? 'RUNNING' : 'STANDBY');

    // ─── Banner: total load + PUE + SHI + redundancy ───
    const totalLoad = (ua?.metrics.kw ?? 0) + (ub?.metrics.kw ?? 0);
    const itLoad = (nodes.hall_1?.metrics.load_kw ?? 0)
        + (nodes.hall_2?.metrics.load_kw ?? 0)
        + (nodes.hall_3?.metrics.load_kw ?? 0);
    const pue = (itLoad > 0 && totalLoad > 0) ? (totalLoad / itLoad) : null;

    const totalEl = document.getElementById('sld-total-load');
    const pueEl = document.getElementById('sld-pue');
    const shiEl = document.getElementById('sld-shi');
    const modeEl = document.getElementById('sld-banner-mode');
    const subEl = document.getElementById('sld-banner-sub');
    const tieLine = document.getElementById('sld-tie-line');
    const tieText = document.getElementById('sld-tie-text');

    if (totalEl) totalEl.textContent = Math.round(totalLoad).toLocaleString();
    if (pueEl) pueEl.textContent = pue ? pue.toFixed(2) : '—';
    if (shiEl) shiEl.textContent = (data.site_health ?? 0).toFixed(2);

    const mode = data.redundancy_mode || '2N';
    if (modeEl) {
        modeEl.textContent = mode;
        modeEl.setAttribute('data-mode', mode);
    }
    if (subEl) {
        subEl.textContent = ({
            '2N': 'Path Diversity', 'N+1': 'Degraded', 'N': 'NON-REDUNDANT',
        })[mode] || mode;
    }
    const tieVisible = (mode === 'N') ? '0.9' : '0';
    if (tieLine) tieLine.setAttribute('opacity', tieVisible);
    if (tieText) tieText.setAttribute('opacity', tieVisible);

    const meta = document.getElementById('sld-meta');
    if (meta) {
        const pb = data.power_balance || {};
        const ok = pb.ok;
        const color = ok ? '#4CAF50' : '#E53935';
        const balance = ok
            ? `<span style="color:${color}">✓ ΣP balance</span>`
            : `<span style="color:${color}">⚠ balance `
              + `${((pb.path_a_residual_kw || 0) + (pb.path_b_residual_kw || 0)).toFixed(2)} kW</span>`;
        meta.innerHTML = `<strong>${mode}</strong> · ${Math.round(totalLoad).toLocaleString()} kW total`
            + ` · PUE ${pue ? pue.toFixed(2) : '—'} · SHI ${(data.site_health ?? 0).toFixed(2)}`
            + ` · weakest <em>${data.weakest_module || '—'}</em> · ${balance}`;
    }
}

// ─── Live Kalman -> per-node severity (Hermes telemetry plane) ─────
function _applyTelemetry(channels) {
    if (!channels || typeof channels !== 'object') return;
    const channelIds = Object.keys(channels);
    if (channelIds.length === 0) return;

    document.querySelectorAll('#view-power .sld-iso-block').forEach((block) => {
        const nodeId = (block.dataset.sldNode || '').toLowerCase();
        if (!nodeId) return;
        const matched = channelIds
            .filter((c) => c.toLowerCase().includes(nodeId))
            .map((c) => channels[c]);
        if (matched.length === 0) return;
        block.dataset.sev = _severityFromChannels(matched);
    });
}

// ─── Data refresh + Hermes wiring ──────────────────────────────────
async function _refresh() {
    try {
        _applyTopology(await getTopologyState());
    } catch (e) {
        console.warn('[power] topology fetch failed:', e.message);
    }
}

function _onTelemetryFrame(payload) {
    // Hermes `telemetry` frame: { schema, channels, anomaly_count_60min, ts }.
    if (payload && payload.channels) _applyTelemetry(payload.channels);
}

function _activate() {
    // Baseline physics-validated topology — fetched once per activation,
    // NOT polled. Live updates arrive on the Hermes telemetry stream.
    _refresh();
}

/** Public entry — called once from main.js at bootstrap. */
export function initPowerView() {
    if (_initialized) return;
    if (!document.getElementById('view-power')) {
        console.warn('[power] #view-power not in DOM; view disabled.');
        return;
    }
    registerRoute('power', { viewId: 'view-power', activate: _activate });
    // T3.1: live severity from the Hermes telemetry stream — the legacy
    // 5 s setInterval poll is eradicated.
    _unsubTelemetry = onHermesStream('telemetry', _onTelemetryFrame);
    _initialized = true;
    console.log('[power] view ready (Tier IV SLD — T2.1 ES module, Hermes-bound)');
}

// ─── Test surface ──────────────────────────────────────────────────
export const __power_test__ = {
    nodeMap: _NODE_MAP,
    severityFromChannels: _severityFromChannels,
    applyTopology: _applyTopology,
    applyTelemetry: _applyTelemetry,
    onTelemetryFrame: _onTelemetryFrame,
    reset: () => {
        _initialized = false;
        if (_unsubTelemetry) { _unsubTelemetry(); _unsubTelemetry = null; }
    },
};
