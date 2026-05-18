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
import { onHermesStream, getTopologyState, writeBmsTag } from '../services/api.js';
import { subscribe } from '../core/state.js';
import { toggleTrip, restoreAll } from '../core/power_grid.js';

let _initialized = false;
let _unsubTelemetry = null;
let _mode = 'live';   // 'live' | 'whatif' — set by the Phase 2 sandbox toggle

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
    // Updates BOTH surfaces — the iso block metric span and the flat
    // SVG <text> — wherever the metric key appears.
    document.querySelectorAll(`[data-sld-metric="${key}"]`)
        .forEach((el) => { el.textContent = value; });
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

    // Severity on every flat-SLD symbol carrying the node id.
    Object.entries(_NODE_MAP).forEach(([sldId, dataId]) => {
        const nodeData = nodes[dataId];
        if (!nodeData) return;
        document.querySelectorAll(`.sld-node[data-sld-node="${sldId}"] .pid-symbol`)
            .forEach((sym) => sym.setAttribute('data-sev', nodeData.severity || 'ok'));
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
    // What-if sandbox: the SLD is disconnected from the live feed —
    // frozen state, no telemetry-driven updates until LIVE is restored.
    if (_mode === 'whatif') return;
    // Hermes `telemetry` frame: { schema, channels, anomaly_count_60min, ts }.
    if (payload && payload.channels) _applyTelemetry(payload.channels);
}

// ════════════════════════════════════════════════════════════════
//  FLAT view — programmatic orthogonal SCADA SLD (T2.1 reinvention)
//
//  Replaces the hand-authored static SVG that had "diagonal spaghetti"
//  routing + misaligned tiers. Built by construction so the defects
//  cannot recur: 5 strict tier columns at FIXED x (grid-aligned), one
//  horizontal spine per 2N path, and every connector a pure 90° run
//  (H or V only — no diagonals). Node labels sit in reserved zones
//  above / below the symbol band; spine lines pass behind the symbol,
//  never through text. Mimics an ETAP / AutoCAD 2D single-line.
// ════════════════════════════════════════════════════════════════
const _FLAT = {
    tierX: { util: 150, xfmr: 268, gen: 392, ats: 602, ups: 820, pdu: 1052 },
    spineY: { A: 232, B: 540 },
    SVG_NS: 'http://www.w3.org/2000/svg',
};

// Node types that are operable breakers — clickable in the control plane.
const _BREAKER_TYPES = new Set(['ats', 'rpp']);

// One equipment node: IEEE-ish symbol + name (above) + metric (below).
function _flatNode(id, type, label, x, y, metrics) {
    const m = metrics
        .map((mm, i) => `<text class="pf-metric" data-sld-metric="${mm.key}" `
            + `x="${x}" y="${y + 40 + i * 13}">${mm.text}</text>`).join('');
    let sym;
    if (type === 'xfmr') {
        sym = `<circle class="pf-sym pid-symbol" data-sev="ok" cx="${x}" cy="${y - 8}" r="14"/>`
            + `<circle class="pf-sym pid-symbol" data-sev="ok" cx="${x}" cy="${y + 8}" r="14"/>`;
    } else if (type === 'genset') {
        sym = `<circle class="pf-sym pid-symbol" data-sev="ok" cx="${x}" cy="${y}" r="23"/>`
            + `<text class="pf-glyph" x="${x}" y="${y + 6}">G</text>`;
    } else if (type === 'parbus') {
        sym = `<rect class="pf-sym pid-symbol pf-bus" data-sev="ok" x="${x - 52}" y="${y - 5}" `
            + `width="104" height="10" rx="2"/>`;
    } else {
        sym = `<rect class="pf-sym pid-symbol" data-sev="ok" x="${x - 40}" y="${y - 23}" `
            + `width="80" height="46" rx="2.5"/>`;
    }
    const isBreaker = _BREAKER_TYPES.has(type);
    const breakerAttr = isBreaker
        ? ' data-breaker="1" tabindex="0" role="button"' : '';
    return `<g class="sld-node pf-node${isBreaker ? ' pf-breaker' : ''}" `
        + `data-sld-node="${id}"${breakerAttr}>`
        + sym
        + `<text class="pf-name" x="${x}" y="${y - 34}">${label}</text>`
        + m
        + `</g>`;
}

// Orthogonal connector — accepts a list of [x,y] waypoints; the caller
// supplies only axis-aligned points so the path is 90° by construction.
function _flatWire(points, cls) {
    const d = points.map((p, i) => (i === 0 ? 'M' : 'L') + p[0] + ' ' + p[1]).join(' ');
    return `<path class="pf-wire ${cls}" d="${d}"/>`;
}

function _flatPath(suffix, S, energized) {
    const T = _FLAT.tierX;
    const cls = energized; // 'pf-a' | 'pf-b'
    const genY = S - 116;
    const busY = S - 64;
    const battY = S + 96;
    // ── orthogonal wiring (spine + branches) ──
    const wires = [
        _flatWire([[T.util + 40, S], [T.ats - 40, S]], cls),          // utility spine -> ATS
        _flatWire([[T.gen, genY + 23], [T.gen, busY - 5]], cls),       // genset -> paralleling bus
        _flatWire([[T.gen, busY + 5], [T.gen, S]], 'pf-cold'),         // bus -> spine (standby)
        _flatWire([[T.ats + 40, S], [T.ups - 40, S]], cls),            // ATS -> UPS
        _flatWire([[T.ups - 40, S], [T.ups + 40, S]], cls),            // through UPS
        _flatWire([[T.ups + 40, S], [T.pdu - 40, S]], cls),            // UPS -> PDU
        _flatWire([[T.ups, battY - 23], [T.ups, S + 23]], cls),        // battery -> UPS
    ].join('');
    // ── nodes ──
    const nodes = [
        _flatNode('util_' + suffix, 'util', 'UTILITY ' + suffix.toUpperCase(),
            T.util, S, [{ key: 'util_' + suffix + '-kv', text: '27.5 kV' },
                        { key: 'util_' + suffix + '-kw', text: '— kW' }]),
        _flatNode('xfmr_' + suffix, 'xfmr', 'XFMR ' + suffix.toUpperCase(),
            T.xfmr, S, [{ key: 'xfmr_' + suffix + '-load', text: '— kVA' }]),
        _flatNode('genset_' + suffix, 'genset', 'GENSET ' + suffix.toUpperCase(),
            T.gen, genY, [{ key: 'genset_' + suffix + '-state', text: 'STANDBY' }]),
        _flatNode('par_bus_' + suffix, 'parbus', 'PARALLELING BUS · N+1',
            T.gen, busY, []),
        _flatNode('ats_' + suffix, 'ats', 'ATS-' + suffix.toUpperCase(),
            T.ats, S, [{ key: 'ats_' + suffix + '-pos', text: 'UTILITY' }]),
        _flatNode('ups_' + suffix, 'ups', 'UPS GALAXY VX ' + suffix.toUpperCase(),
            T.ups, S, [{ key: 'ups_' + suffix + '-mode', text: 'ONLINE' },
                       { key: 'ups_' + suffix + '-load', text: '— kW' }]),
        _flatNode('batt_' + suffix, 'batt', 'BATTERY ' + suffix.toUpperCase(),
            T.ups, battY, [{ key: 'batt_' + suffix + '-soc', text: 'SOC 100%' }]),
        _flatNode('rpp_' + suffix + '1', 'rpp', 'RPP / PDU ' + suffix.toUpperCase(),
            T.pdu, S, [{ key: 'rpp_' + suffix + '1-kw', text: '— kW' }]),
    ].join('');
    return `<g class="pf-pathgroup">${wires}${nodes}</g>`;
}

/** Build the full flat-SLD SVG inner markup from the 5-tier topology. */
function _buildFlatMarkup() {
    const T = _FLAT.tierX;
    const tierLabels = [
        ['UTILITY', T.util], ['GENSET / N+1', T.gen],
        ['ATS / STS', T.ats], ['UPS 2N', T.ups], ['PDU / RPP', T.pdu],
    ];
    const rails = tierLabels.map(([name, x]) =>
        `<line class="pf-tier-rail" x1="${x}" y1="48" x2="${x}" y2="690"/>`
        + `<text class="pf-tier-label" x="${x}" y="34">${name}</text>`).join('');
    // 2N tie-line (bound by _applyTopology: visible only in N mode).
    const tie = `<line id="sld-tie-line" class="pf-tie" x1="${T.pdu}" y1="${_FLAT.spineY.A}" `
        + `x2="${T.pdu}" y2="${_FLAT.spineY.B}" opacity="0"/>`
        + `<text id="sld-tie-text" class="pf-tie-label" x="${T.pdu + 12}" `
        + `y="${(_FLAT.spineY.A + _FLAT.spineY.B) / 2}" opacity="0">2N TIE</text>`;
    return rails
        + _flatPath('a', _FLAT.spineY.A, 'pf-a')
        + _flatPath('b', _FLAT.spineY.B, 'pf-b')
        + tie;
}

/** Render the orthogonal flat SLD into the legacy .pid-svg container. */
function _renderFlatSld() {
    const svg = document.querySelector('#view-power .pid-svg');
    if (!svg) return;
    svg.setAttribute('viewBox', '0 0 1200 720');
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    svg.classList.add('pf-svg');
    svg.innerHTML = _buildFlatMarkup();
}

// ════════════════════════════════════════════════════════════════
//  PHASE 1 — interactive control plane (breaker actuation)
//
//  Breaker nodes (ATS / RPP) are clickable. A confirmation modal POSTs
//  an OPEN/CLOSE command to /api/bms/write, sending the actor_role
//  claim so the SME_L6 RBAC gate (F3-2) is enforced and visibly
//  surfaced — a sub-SME_L6 role yields an in-modal "RBAC DENIED".
// ════════════════════════════════════════════════════════════════
let _modalCmd = null;   // currently-selected OPEN | CLOSE

function _closeBreakerModal() {
    const modal = document.getElementById('pwr-breaker-modal');
    if (modal) modal.hidden = true;
}

function _ensureBreakerModal() {
    let modal = document.getElementById('pwr-breaker-modal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'pwr-breaker-modal';
    modal.className = 'pwr-modal-overlay';
    modal.hidden = true;
    modal.innerHTML = `
        <div class="pwr-modal" role="dialog" aria-modal="true" aria-labelledby="pwr-modal-title">
            <div class="pwr-modal-hdr">
                <span class="pwr-modal-icon">&#9889;</span>
                <h3 id="pwr-modal-title">Breaker Control</h3>
            </div>
            <div class="pwr-modal-body">
                <p class="pwr-modal-target">Target breaker:
                    <strong data-field="target">&mdash;</strong></p>
                <label class="pwr-modal-lbl">Command</label>
                <div class="pwr-modal-cmds">
                    <button type="button" class="pwr-cmd-btn" data-cmd="OPEN">OPEN BREAKER</button>
                    <button type="button" class="pwr-cmd-btn" data-cmd="CLOSE">CLOSE BREAKER</button>
                </div>
                <label class="pwr-modal-lbl" for="pwr-modal-role">Actor role (RBAC claim)</label>
                <select id="pwr-modal-role" class="pwr-modal-select">
                    <option value="TECH_L4">TECH_L4</option>
                    <option value="SENIOR_TECH_L5">SENIOR_TECH_L5</option>
                    <option value="SME_L6" selected>SME_L6</option>
                </select>
                <div class="pwr-modal-result" data-field="result"></div>
            </div>
            <div class="pwr-modal-foot">
                <button type="button" class="btn btn-secondary" data-act="cancel">Cancel</button>
                <button type="button" class="btn" data-act="confirm" disabled>Confirm actuation</button>
            </div>
        </div>`;
    document.body.appendChild(modal);

    modal.addEventListener('click', (e) => {
        if (e.target === modal || e.target.dataset.act === 'cancel') {
            _closeBreakerModal();
            return;
        }
        const cmdBtn = e.target.closest('.pwr-cmd-btn');
        if (cmdBtn) {
            _modalCmd = cmdBtn.dataset.cmd;
            modal.querySelectorAll('.pwr-cmd-btn').forEach((b) =>
                b.classList.toggle('is-sel', b === cmdBtn));
            modal.querySelector('[data-act="confirm"]').disabled = false;
            return;
        }
        if (e.target.dataset.act === 'confirm') {
            _submitBreakerCommand(
                modal.dataset.nodeId, _modalCmd,
                modal.querySelector('#pwr-modal-role').value,
            );
        }
    });
    return modal;
}

function _openBreakerModal(nodeId, label) {
    const modal = _ensureBreakerModal();
    _modalCmd = null;
    modal.dataset.nodeId = nodeId;
    modal.querySelector('[data-field="target"]').textContent = label || nodeId;
    const result = modal.querySelector('[data-field="result"]');
    result.textContent = '';
    result.className = 'pwr-modal-result';
    modal.querySelectorAll('.pwr-cmd-btn').forEach((b) => b.classList.remove('is-sel'));
    modal.querySelector('[data-act="confirm"]').disabled = true;
    modal.hidden = false;
}

async function _submitBreakerCommand(nodeId, cmd, actorRole) {
    const modal = document.getElementById('pwr-breaker-modal');
    if (!modal || !cmd) return;
    const result = modal.querySelector('[data-field="result"]');
    result.className = 'pwr-modal-result is-pending';
    result.textContent = 'Issuing command to BMS control surface…';

    const { ok, status, data } = await writeBmsTag({
        tag_id: `breaker.${nodeId}.cmd`,
        value: cmd,
        user: 'power-sld-operator',
        actor_role: actorRole,
    });
    if (status === 403) {
        result.className = 'pwr-modal-result is-denied';
        result.textContent = `RBAC DENIED — ${data.detail || 'SME_L6 required for BMS write'}`;
        return;
    }
    if (!ok) {
        result.className = 'pwr-modal-result is-err';
        result.textContent = `Command rejected — ${data.detail || ('HTTP ' + status)}`;
        return;
    }
    result.className = 'pwr-modal-result is-ok';
    result.textContent = `✓ ${cmd} accepted — ${data.message || nodeId}`;
}

/** Flat-SVG click delegation — routes a node click by current mode. */
function _onFlatClick(e) {
    const node = e.target.closest('.pf-node');
    if (!node) return;
    const id = node.dataset.sldNode;
    if (_mode === 'whatif') {
        // Sandbox: any node-click injects a simulated fault into the
        // LOCAL DAG engine — the cascade is computed in frontend memory,
        // zero bytes to the backend.
        toggleTrip(id);
        return;
    }
    // Live mode: only breakers are operable, via the actuation modal.
    if (node.dataset.breaker) {
        const label = node.querySelector('.pf-name');
        _openBreakerModal(id, label ? label.textContent : id);
    }
}

// ════════════════════════════════════════════════════════════════
//  PHASE 2 — predictive What-If simulation sandbox
//
//  A LIVE <-> WHAT-IF toggle. In WHAT-IF the SLD disconnects from the
//  Hermes telemetry feed (frozen state), the view gains a hazard-stripe
//  border, and any node-click injects a simulated fault into the LOCAL
//  DAG fault-cascade engine — computed + rendered purely in frontend
//  memory. Returning to LIVE clears the simulated trips and re-syncs.
// ════════════════════════════════════════════════════════════════
function _setMode(mode) {
    _mode = (mode === 'whatif') ? 'whatif' : 'live';
    const view = document.getElementById('view-power');
    if (view) view.classList.toggle('pwr-whatif', _mode === 'whatif');
    const btn = document.getElementById('pwr-mode-toggle');
    if (btn) {
        btn.textContent = _mode === 'whatif'
            ? '⚠ WHAT-IF SIMULATION' : '◉ LIVE TELEMETRY';
        btn.dataset.mode = _mode;
    }
    if (_mode === 'live') {
        // Leaving the sandbox — clear simulated trips, re-sync to live.
        restoreAll();
        _refresh();
    }
}

function _buildModeToggle() {
    if (document.getElementById('pwr-mode-toggle')) return;
    const view = document.getElementById('view-power');
    if (!view) return;
    const btn = document.createElement('button');
    btn.id = 'pwr-mode-toggle';
    btn.type = 'button';
    btn.className = 'pwr-mode-toggle';
    btn.dataset.mode = 'live';
    btn.textContent = '◉ LIVE TELEMETRY';
    btn.title = 'Toggle LIVE telemetry <-> isolated WHAT-IF simulation sandbox';
    btn.addEventListener('click', () => _setMode(_mode === 'live' ? 'whatif' : 'live'));
    const bar = view.querySelector('.pid-action-bar') || view;
    bar.insertBefore(btn, bar.firstChild);
}

/** Render the local DAG grid state (the fault cascade) onto the flat SLD. */
function _applyGrid(grid) {
    if (!grid) return;
    document.querySelectorAll('#view-power .pid-svg .pf-node').forEach((node) => {
        const n = grid[node.dataset.sldNode];
        if (!n) return;
        let sev = 'ok';
        if (n.tripped || n.alive === false) sev = 'critical';
        else if (n.on_battery || n.energized_by === 'genset') sev = 'warning';
        node.querySelectorAll('.pid-symbol').forEach((s) => s.setAttribute('data-sev', sev));
        node.classList.toggle('pf-tripped', !!n.tripped);
    });
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
    // T2.1 reinvention: render the orthogonal flat SLD into .pid-svg,
    // replacing the hand-authored static SVG (spaghetti routing).
    _renderFlatSld();
    // L3 Phase 1: breaker nodes are interactive actuators. Delegated on
    // the .pid-svg element so it survives _renderFlatSld() re-renders.
    const flatSvg = document.querySelector('#view-power .pid-svg');
    if (flatSvg) flatSvg.addEventListener('click', _onFlatClick);
    // L3 Phase 2: LIVE <-> WHAT-IF toggle + flat-SLD render of the local
    // DAG fault-cascade (the sandbox's simulated faults become visible).
    _buildModeToggle();
    subscribe('grid', _applyGrid);
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
    buildFlatMarkup: _buildFlatMarkup,
    renderFlatSld: _renderFlatSld,
    openBreakerModal: _openBreakerModal,
    submitBreakerCommand: _submitBreakerCommand,
    onFlatClick: _onFlatClick,
    setMode: _setMode,
    getMode: () => _mode,
    buildModeToggle: _buildModeToggle,
    applyGrid: _applyGrid,
    reset: () => {
        _initialized = false;
        _mode = 'live';
        if (_unsubTelemetry) { _unsubTelemetry(); _unsubTelemetry = null; }
        const modal = document.getElementById('pwr-breaker-modal');
        if (modal) modal.remove();
    },
};
