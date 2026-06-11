/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/power.js
 * Diagram Rebuild Batch 1 — Power & UPS SLD on the shared diagram
 * kit (core/diagram_kit.js) + canonical node registry
 * (core/node_registry.js).
 *
 * What changed vs the T2.1 generation:
 *   - Symbols, orthogonal wires, sparklines and the actuation modal
 *     now come from the shared kit — one visual language across the
 *     SLD views, no private copies to drift.
 *   - Node identity (SLD id <-> topology key <-> channel prefixes)
 *     comes from the registry; Kalman channel ownership is by
 *     prefix discipline, not substring matching.
 *   - NEW: Phase 2 branch — Building D (Path C2, design target
 *     Q2 2026): 35 kV 3-phase AC -> MV RECTIFIER -> [AC/DC FENCE]
 *     -> SSCB (IEC 60947-2) -> 800 VDC UNIPOLAR TN-S bus -> BESS
 *     2.5 MWh + RPP D1/D2 -> GB300 NVL144 racks. The vocabulary
 *     fence (S-VOCAB-01) is drawn: "3-phase" exists ONLY upstream
 *     of the rectifier; the DC side is labeled UNIPOLAR TN-S.
 *     Rendered dashed/dimmed — it is a DESIGN, not deployed plant,
 *     and its nodes are NOT operable (no breaker control plane).
 *
 * Data plane unchanged: /api/topology/state once per activation +
 * live severity from the Hermes telemetry stream. L3 control plane
 * (breaker actuation, What-If DAG sandbox) unchanged.
 *
 * Test surface: __power_test__ exposes the pure mapping helpers.
 * ════════════════════════════════════════════════════════════════ */

import { registerRoute } from '../core/router.js';
import { onHermesStream, getTopologyState, writeBmsTag } from '../services/api.js';
import { subscribe, setState } from '../core/state.js';
import { toggleTrip, restoreAll } from '../core/power_grid.js';
import { escapeHTML } from '../core/sanitize.js';
import {
    severityFromChannels, symbol, wire, sparkPoints, sparkPolyline,
    createSparkTracker, createActuationModal, legend, DEFAULT_LEGEND,
} from '../core/diagram_kit.js';
import {
    sldToTopoMap, channelPrefixesFor, matchesChannel, nodesWhere,
} from '../core/node_registry.js';
import { n1Power } from '../core/contingency.js';
import { createN1Overlay } from '../core/n1_overlay.js';
import {
    startRecording, snapshotAt, range as recorderRange,
} from '../core/flight_recorder.js';
import { budgetCaption, gensetFarmSizing, farmUnits } from '../core/power_budget.js';

let _initialized = false;
let _unsubTelemetry = null;
let _mode = 'live';   // 'live' | 'whatif' — set by the Phase 2 sandbox toggle

// SLD-node-id -> /api/topology/state hld_nodes key (registry-derived).
const _NODE_MAP = sldToTopoMap();

// ─── Channel ownership (registry prefix discipline) ────────────────
function _channelMatcher(nodeId, channelId) {
    const prefixes = channelPrefixesFor(nodeId);
    return matchesChannel(channelId, prefixes.length ? prefixes : [nodeId]);
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

function _setMetric(key, value) {
    // Updates the flat-SVG <text> wherever the metric key appears.
    document.querySelectorAll(`[data-sld-metric="${key}"]`)
        .forEach((el) => { el.textContent = value; });
}

// ─── Live Kalman -> per-node severity (Hermes telemetry plane) ─────
// SLD Reengineering 2026-06-11: the iso stage is retired — live Kalman
// severity now paints the flat-SLD nodes directly (it previously only
// painted the iso blocks, leaving the canonical surface blind).
function _applyTelemetry(channels) {
    if (!channels || typeof channels !== 'object') return;
    const channelIds = Object.keys(channels);
    if (channelIds.length === 0) return;

    document.querySelectorAll('#view-power .pid-svg .pf-node').forEach((node) => {
        const nodeId = (node.dataset.sldNode || '').toLowerCase();
        if (!nodeId) return;
        const matched = channelIds
            .filter((c) => _channelMatcher(nodeId, c))
            .map((c) => channels[c]);
        if (matched.length === 0) return;
        const sev = severityFromChannels(matched);
        node.dataset.sev = sev;
        node.querySelectorAll('.pid-symbol')
            .forEach((s) => s.setAttribute('data-sev', sev));
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
    // What-If sandbox / Replay: the SLD is disconnected from the live
    // feed — frozen or historical state until LIVE is restored.
    if (_mode !== 'live') return;
    // Hermes `telemetry` frame: { schema, channels, anomaly_count_60min, ts }.
    if (payload && payload.channels) {
        _applyTelemetry(payload.channels);
        _updateSparklines(payload.channels);
    }
}

// ─── Micro-trend sparklines (shared kit tracker) ───────────────────
const _SPARK_NODES = new Set([
    'util_a', 'util_b', 'ups_a', 'ups_b', 'genset_a', 'genset_b',
]);
const _sparkTracker = createSparkTracker({
    rootSelector: '#view-power .pid-svg',
    nodes: _SPARK_NODES,
    ticks: 20,
});
function _updateSparklines(channels) {
    _sparkTracker.update(channels, _channelMatcher);
}

// ════════════════════════════════════════════════════════════════
//  FLAT view — orthogonal SCADA SLD, generated from the registry
//  via the shared diagram kit. 5 strict tier columns at FIXED x,
//  one horizontal spine per 2N path, every connector a pure 90°
//  run (kit-enforced: orthoPath throws on diagonals). Below the
//  Phase 1 plant, the Phase 2 (Building D) design branch with the
//  AC/DC vocabulary fence drawn explicitly.
// ════════════════════════════════════════════════════════════════
const _FLAT = {
    tierX: { util: 150, xfmr: 268, gen: 392, ats: 602, ups: 820, pdu: 1052 },
    spineY: { A: 232, B: 540 },
    phase2: { spineY: 880, headerY: 766, dividerY: 726, fenceX: 484 },
    // 50 MW track: genset farm row + power-budget caption block.
    farm: { busY: 1110, genY: 1180, tieX: 304 },
    viewBox: '0 0 1200 1260',
};

// Node types that are operable breakers — clickable in the control plane.
const _BREAKER_TYPES = new Set(['ats', 'rpp']);

// One equipment node: kit symbol + name (above) + metric (below).
// opts.breaker=false suppresses the control plane (Phase 2 design
// nodes are NOT operable — there is no deployed plant behind them).
function _flatNode(id, type, label, x, y, metrics, opts = {}) {
    const m = metrics
        .map((mm, i) => `<text class="pf-metric" data-sld-metric="${mm.key}" `
            + `x="${x}" y="${y + 40 + i * 13}">${escapeHTML(mm.text)}</text>`).join('');
    const isBreaker = _BREAKER_TYPES.has(type) && opts.breaker !== false;
    const breakerAttr = isBreaker
        ? ' data-breaker="1" tabindex="0" role="button"' : '';
    let spark = '';
    if (_SPARK_NODES.has(id)) {
        const sy = y + 40 + metrics.length * 13 + 10;
        spark = sparkPolyline(id, x - 26, sy);
    }
    return `<g class="sld-node pf-node${isBreaker ? ' pf-breaker' : ''}" `
        + `data-sld-node="${id}"${breakerAttr}>`
        + symbol(type, x, y)
        + `<text class="pf-name" x="${x}" y="${y - 34}">${escapeHTML(label)}</text>`
        + m + spark
        + `</g>`;
}

function _flatPath(suffix, S, energized) {
    const T = _FLAT.tierX;
    const cls = energized; // 'pf-a' | 'pf-b'
    const genY = S - 116;
    const busY = S - 64;
    const battY = S + 96;
    // ── orthogonal wiring (spine + branches) ──
    const wires = [
        wire([[T.util + 40, S], [T.ats - 40, S]], cls),          // utility spine -> ATS
        wire([[T.gen, genY + 23], [T.gen, busY - 5]], cls),       // genset -> paralleling bus
        wire([[T.gen, busY + 5], [T.gen, S]], 'pf-cold'),         // bus -> spine (standby)
        wire([[T.ats + 40, S], [T.ups - 40, S]], cls),            // ATS -> UPS
        wire([[T.ups - 40, S], [T.ups + 40, S]], cls),            // through UPS
        wire([[T.ups + 40, S], [T.pdu - 40, S]], cls),            // UPS -> PDU
        wire([[T.ups, battY - 23], [T.ups, S + 23]], cls),        // battery -> UPS
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

/**
 * Phase 2 — Building D (Path C2 design). Mirrors the live backend
 * graph: utility_feed_d -> mv_rectifier_d -> sscb_d_01 ->
 * main_bus_dc_d -> { bess_d_01 (bidirectional), rpp_d_01/02 }.
 *
 * The AC/DC FENCE is drawn at the rectifier output: 3-phase
 * vocabulary exists ONLY left of the fence; right of it the bus is
 * 800 VDC UNIPOLAR TN-S (S-VOCAB-01 — no phases on a DC bus).
 */
function _flatPhase2() {
    const T = _FLAT.tierX;
    const P = _FLAT.phase2;
    const S = P.spineY;
    const F = P.fenceX;
    const busHalf = 120;            // dcbus symbol half-width
    const bessY = S + 108;
    const rppD1Y = S - 44;
    const rppD2Y = S + 44;

    const header =
        `<line class="pf-section-divider" x1="24" y1="${P.dividerY}" x2="1176" y2="${P.dividerY}"/>`
        + `<text class="pf-section-title" x="150" y="${P.headerY}">`
        + `PHASE 2 — BUILDING D · PATH C2 (DESIGN · TARGET Q2 2026)</text>`;

    // The vocabulary fence: AC world | DC world.
    const fence =
        `<line class="pf-fence" x1="${F}" y1="${P.headerY + 14}" x2="${F}" y2="${S + 178}"/>`
        + `<text class="pf-fence-label" x="${F - 12}" y="${P.headerY + 34}" `
        + `text-anchor="end">3-PHASE AC · 35 kV</text>`
        + `<text class="pf-fence-label pf-fence-label-dc" x="${F + 12}" y="${P.headerY + 34}">`
        + `800 VDC · UNIPOLAR TN-S</text>`;

    // ── orthogonal wiring (kit-enforced 90°) ──
    const wires = [
        // 35 kV AC feed -> MV Rectifier (AC side)
        wire([[T.util + 40, S], [T.gen - 40, S]], 'pf-ac'),
        // MV Rectifier -> SSCB (DC side starts at the rectifier output)
        wire([[T.gen + 40, S], [T.ats - 26, S]], 'pf-dc'),
        // SSCB -> 800 VDC bus
        wire([[T.ats + 26, S], [T.ups - busHalf, S]], 'pf-dc'),
        // bus <-> BESS (bidirectional: charge / discharge)
        wire([[T.ups, S + 6], [T.ups, bessY - 23]], 'pf-dc'),
        // bus -> RPP D1 / D2
        wire([[T.ups + busHalf, S], [T.pdu - 76, S], [T.pdu - 76, rppD1Y], [T.pdu - 40, rppD1Y]], 'pf-dc'),
        wire([[T.pdu - 76, S], [T.pdu - 76, rppD2Y], [T.pdu - 40, rppD2Y]], 'pf-dc'),
    ].join('');

    // ── nodes (design — not operable: breaker:false) ──
    const nodes = [
        _flatNode('util_d', 'util', 'UTILITY D · 35 kV AC', T.util, S,
            [{ key: 'util_d-kv', text: '35.0 kV' }, { key: 'util_d-kw', text: '— kW' }],
            { breaker: false }),
        _flatNode('mv_rect_d', 'rectifier', 'MV RECTIFIER', T.gen, S,
            [{ key: 'mv_rect_d-load', text: '— MW' }], { breaker: false }),
        _flatNode('sscb_d', 'sscb', 'SSCB · IEC 60947-2', T.ats, S,
            [{ key: 'sscb_d-state', text: 'CLOSED' },
             { key: 'sscb_d-clear', text: '1-100 µs clearing' }], { breaker: false }),
        _flatNode('dc_bus_d', 'dcbus', '800 VDC BUS · UNIPOLAR TN-S', T.ups, S,
            [{ key: 'dc_bus_d-v', text: '800 VDC' }], { breaker: false }),
        _flatNode('bess_d', 'bess', 'BESS 2.5 MWh', T.ups, bessY,
            [{ key: 'bess_d-soc', text: 'SOC — %' }], { breaker: false }),
        _flatNode('rpp_d1', 'rpp', 'RPP D1', T.pdu, rppD1Y,
            [{ key: 'rpp_d1-kw', text: '— kW' }], { breaker: false }),
        _flatNode('rpp_d2', 'rpp', 'RPP D2', T.pdu, rppD2Y,
            [{ key: 'rpp_d2-kw', text: '— kW' }], { breaker: false }),
    ].join('');

    const caption =
        `<text class="pf-caption" x="${T.pdu}" y="${S + 124}">→ GB300 NVL144 · 250 racks @ 200 kW (design)</text>`
        + `<text class="pf-caption" x="${T.ups}" y="${bessY + 44}">charge / discharge</text>`;

    return `<g class="pf-pathgroup pf-phase2" data-phase="2">`
        + header + fence + wires + nodes + caption
        + _flatGensetFarm() + `</g>`;
}

/**
 * 50 MW track — the standby GENSET FARM for Building D (design).
 * >50 MW cannot be one prime mover: N+2 farm of 3.2 MW MV units on
 * 13.8 kV paralleling switchgear (ANSI 25 sync, dead-bus black
 * start), stepped UP to 35 kV before joining the rectifier's AC
 * side (never tie 13.8 kV to a 35 kV bus directly).
 *
 * LEVEL OF DETAIL (SLD Reengineering Batch B): at fit-width 22 mini
 * circles are decorative noise — the farm collapses to ONE honest
 * switchgear-lineup block (count + rating + N+2 + state summary,
 * every number from core/power_budget.js). Clicking the block
 * focuses the viewBox onto the farm and expands it into per-unit
 * switchgear cubicles: ANSI 52 breaker, generator glyph, unit id,
 * rating, NFPA 110 state strip — one cubicle per INSTALLED unit, so
 * the drawing still cannot lie about capacity.
 */
let _farmLod = 0;   // 0 = collapsed lineup block | 1 = per-unit focus

// Focused viewBox: the farm band only (budget block through captions).
const _FARM_FOCUS_VIEWBOX = '40 988 1140 264';

const _FARM_GEOM = { busL: 86, busR: 1114 };

// 52 = ANSI device number for the power circuit breaker. At farm
// density the per-unit 52s are compact marks; the bus tie keeps the
// labeled glyph.
function _breaker52(x, y, labeled) {
    return `<rect class="pf-sym pid-symbol" data-sev="ok" x="${x - (labeled ? 13 : 6)}" y="${y - (labeled ? 11 : 6)}" `
        + `width="${labeled ? 26 : 12}" height="${labeled ? 22 : 12}" rx="2"/>`
        + (labeled ? `<text class="pf-glyph pf-glyph-sm" x="${x}" y="${y + 4}">52</text>` : '');
}

// The MV-bus tie chain is identical at both LODs: bus -> labeled 52
// -> step-up xfmr -> the rectifier's 35 kV AC side (S-VOCAB-01: the
// farm is AC plant; it never touches the DC fence).
function _farmTie() {
    const F = _FLAT.farm;
    const S = _FLAT.phase2.spineY;
    const wires =
        wire([[F.tieX, F.busY - 6], [F.tieX, F.busY - 36]], 'pf-ac')
        + wire([[F.tieX, F.busY - 58], [F.tieX, S + 96]], 'pf-ac')
        + wire([[F.tieX, S + 52], [F.tieX, S]], 'pf-ac');
    return wires
        + _breaker52(F.tieX, F.busY - 47, true)
        + `<g class="sld-node pf-node" data-sld-node="stepup_d">`
        + symbol('xfmr', F.tieX, S + 74)
        + `<text class="pf-name" x="${F.tieX + 118}" y="${S + 72}">STEP-UP 13.8→35 kV</text>`
        + `</g>`;
}

// Shared budget caption block (printed at both LODs — single source).
function _farmBudgetBlock() {
    const F = _FLAT.farm;
    const parts = budgetCaption().split(' · ');
    const budgetLines = [];
    for (let i = 0; i < parts.length; i += 3) {
        budgetLines.push(parts.slice(i, i + 3).join(' · '));
    }
    const budgetTxt = budgetLines.map((line, i) =>
        `<text class="pf-caption pf-budget" x="560" y="${F.busY - 94 + i * 16}">${escapeHTML(line)}</text>`).join('');
    return `<text class="pf-section-title" x="560" y="${F.busY - 112}">POWER BUDGET · 50 MW IT (DESIGN)</text>`
        + budgetTxt;
}

function _farmSizingTxt(sizing) {
    return `${sizing.installed} × ${sizing.unitMw} MW`
        + ` (${sizing.required} required + ${sizing.redundancy} = N+${sizing.redundancy})`
        + ` · farm ${sizing.farmMw.toFixed(1)} MW`;
}

// ── LOD 0: the honest lineup block ──────────────────────────────
function _farmCollapsed(sizing, units) {
    const F = _FLAT.farm;
    const { busL, busR } = _FARM_GEOM;
    const n = sizing.installed;
    const top = F.busY - 6;
    const h = 96;

    // Cubicle tick marks along the top edge — the block reads as a
    // switchgear lineup of n cubicles, not an anonymous box.
    const pitch = (busR - busL) / n;
    const ticks = Array.from({ length: n - 1 }, (_, i) =>
        `<line class="pf-farm-sep" x1="${(busL + (i + 1) * pitch).toFixed(1)}" y1="${top}" `
        + `x2="${(busL + (i + 1) * pitch).toFixed(1)}" y2="${top + 14}"/>`).join('');

    const standby = units.filter((u) => u.state === 'STANDBY').length;
    return `<g class="sld-node pf-node pf-farm-block" data-sld-node="gen_farm_d" `
        + `data-farm-toggle="1" data-farm-lod="0" role="button" tabindex="0">`
        + `<rect class="pf-sym pid-symbol pf-farm-lineup" data-sev="ok" `
        + `x="${busL}" y="${top}" width="${busR - busL}" height="${h}" rx="3"/>`
        + ticks
        + `<text class="pf-farm-title" x="${(busL + busR) / 2}" y="${top + 32}" text-anchor="middle">`
        + `GENSET FARM · BUILDING D STANDBY (DESIGN) — ${escapeHTML(_farmSizingTxt(sizing))}</text>`
        + `<text class="pf-farm-sub" x="${(busL + busR) / 2}" y="${top + 52}" text-anchor="middle">`
        + `13.8 kV MV PARALLELING LINEUP · ANSI 25 sync · dead-bus black start · 52 per unit</text>`
        + `<text class="pf-farm-summary" x="${(busL + busR) / 2}" y="${top + 72}" text-anchor="middle">`
        + `UNIT STATES: ${standby} × STANDBY (design baseline — no live farm telemetry yet)</text>`
        + `<text class="pf-farm-hint" x="${(busL + busR) / 2}" y="${top + 88}" text-anchor="middle">`
        + `[ click to expand the lineup ]</text>`
        + `</g>`;
}

// ── LOD 1: per-unit switchgear cubicles ─────────────────────────
function _farmExpanded(sizing, units) {
    const F = _FLAT.farm;
    const { busL, busR } = _FARM_GEOM;
    const n = sizing.installed;
    const step = (busR - busL - 28) / (n - 1);
    const cubW = Math.min(42, step - 4);

    const bus =
        `<g class="sld-node pf-node" data-sld-node="mv_bus_d">`
        + `<rect class="pf-sym pid-symbol pf-bus" data-sev="ok" x="${busL}" y="${F.busY - 6}" width="${busR - busL}" height="12" rx="2"/>`
        + `<text class="pf-name" x="${(busL + busR) / 2}" y="${F.busY - 16}">MV PARALLELING BUS · 13.8 kV · ANSI 25 sync · dead-bus black start · 52 per unit</text>`
        + `</g>`;

    const cubicles = units.map((u, i) => {
        const x = Number((busL + 14 + i * step).toFixed(1));
        const cl = x - cubW / 2;
        const ct = F.busY + 16;
        return wire([[x, F.busY + 6], [x, ct]], 'pf-ac')
            + `<g class="sld-node pf-node pf-farm-cubicle" data-sld-node="gen_farm_d" `
            + `data-farm-unit="${escapeHTML(u.id)}" data-state="${escapeHTML(u.state)}">`
            + `<rect class="pf-sym pid-symbol pf-cub" data-sev="ok" x="${cl}" y="${ct}" width="${cubW}" height="96" rx="2"/>`
            + _breaker52(x, ct + 14, false)
            + `<circle class="pf-sym pid-symbol" data-sev="ok" cx="${x}" cy="${ct + 44}" r="13"/>`
            + `<text class="pf-glyph pf-glyph-sm" x="${x}" y="${ct + 48}">G</text>`
            + `<text class="pf-farm-idx" x="${x}" y="${ct + 72}">${escapeHTML(u.id)}</text>`
            + `<text class="pf-farm-rating" x="${x}" y="${ct + 84}">${u.ratedMw} MW</text>`
            + `<rect class="pf-farm-strip pf-state-${u.state.toLowerCase()}" x="${cl}" y="${ct + 88}" width="${cubW}" height="5"/>`
            + `</g>`;
    }).join('');

    const back =
        `<g class="pf-farm-back" data-farm-back="1" role="button" tabindex="0">`
        + `<rect x="48" y="996" width="110" height="24" rx="3"/>`
        + `<text x="103" y="1012" text-anchor="middle">&lt; FULL SLD</text>`
        + `</g>`;

    const captions =
        `<text class="pf-section-title" x="${busL}" y="${F.busY + 130}">`
        + `GENSET FARM · BUILDING D STANDBY (DESIGN) — ${escapeHTML(_farmSizingTxt(sizing))}</text>`
        + `<text class="pf-caption" x="${(busL + busR) / 2}" y="${F.busY + 146}">`
        + `NFPA 110 TYPE 10 sequence per unit: STANDBY → CRANKING → RUNNING → ON LOAD → COOLDOWN</text>`;

    return back + bus + cubicles + captions;
}

function _flatGensetFarm() {
    const sizing = gensetFarmSizing();
    const units = farmUnits();
    const body = (_farmLod === 1)
        ? _farmExpanded(sizing, units)
        : _farmCollapsed(sizing, units);
    return `<g data-farm="1" data-farm-lod="${_farmLod}">${_farmTie()}${body}${_farmBudgetBlock()}</g>`;
}

/**
 * LOD switch — re-renders the SLD (diagrams are pure functions of
 * state) and drives the viewBox: full canvas at LOD 0, farm band at
 * LOD 1. Severity repaints on the next Hermes frame / topology tick.
 */
function _setFarmLod(lod) {
    _farmLod = (lod === 1) ? 1 : 0;
    const svg = document.querySelector('#view-power .pid-svg');
    if (!svg) return;
    svg.innerHTML = _buildFlatMarkup();
    svg.setAttribute('viewBox', _farmLod === 1 ? _FARM_FOCUS_VIEWBOX : _FLAT.viewBox);
    if (_initialized) _refresh();
}

/** Build the full flat-SLD SVG inner markup from the tiered topology. */
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
        + tie
        + _flatPhase2()
        + legend(DEFAULT_LEGEND, 16, 96);
}

/** Render the orthogonal flat SLD into the legacy .pid-svg container. */
function _renderFlatSld() {
    const svg = document.querySelector('#view-power .pid-svg');
    if (!svg) return;
    svg.setAttribute('viewBox', _FLAT.viewBox);
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    svg.classList.add('pf-svg');
    svg.innerHTML = _buildFlatMarkup();
}

// ════════════════════════════════════════════════════════════════
//  L3 Phase 1 — interactive control plane (breaker actuation)
//
//  Breaker nodes (ATS / RPP, Phase 1 only) are clickable. The shared
//  kit modal POSTs an OPEN/CLOSE command to /api/bms/write with the
//  actor_role claim so the SME_L6 RBAC gate (F3-2) is enforced and
//  visibly surfaced — a sub-SME_L6 role yields "RBAC DENIED".
// ════════════════════════════════════════════════════════════════
const _breakerModal = createActuationModal({
    modalId: 'pwr-breaker-modal',
    titleId: 'pwr-modal-title',
    roleSelectId: 'pwr-modal-role',
    icon: '&#9889;',
    title: 'Breaker Control',
    targetLabel: 'Target breaker:',
    commands: [
        { cmd: 'OPEN', label: 'OPEN BREAKER' },
        { cmd: 'CLOSE', label: 'CLOSE BREAKER' },
    ],
    onSubmit: (nodeId, cmd, actorRole) => _submitBreakerCommand(nodeId, cmd, actorRole),
});

function _openBreakerModal(nodeId, label) { _breakerModal.open(nodeId, label); }

async function _submitBreakerCommand(nodeId, cmd, actorRole) {
    if (!document.getElementById('pwr-breaker-modal') || !cmd) return;
    _breakerModal.showPending();
    // Real ISA-95 BMS tag id from config/bms_tags.yml
    // (PWR.<NODE>.BREAKER, writable BO) — so the write returns HTTP 200.
    const outcome = await writeBmsTag({
        tag_id: `PWR.${nodeId.toUpperCase()}.BREAKER`,
        value: cmd,
        user: 'power-sld-operator',
        actor_role: actorRole,
    });
    _breakerModal.showResult(outcome, cmd, nodeId);
}

/** Flat-SVG click delegation — routes a node click by current mode. */
function _onFlatClick(e) {
    // Farm level-of-detail gestures take precedence in every mode —
    // they change what is drawn, never what is energized.
    if (e.target.closest && e.target.closest('[data-farm-toggle]')) {
        _setFarmLod(1);
        return;
    }
    if (e.target.closest && e.target.closest('[data-farm-back]')) {
        _setFarmLod(0);
        return;
    }
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
    // Live mode: breakers actuate via the modal; every other node
    // opens the engineering detail panel (Batch 5 — the flat SLD is
    // finally wired to the SCADA asset panel).
    if (node.dataset.breaker) {
        const label = node.querySelector('.pf-name');
        _openBreakerModal(id, label ? label.textContent : id);
    } else {
        setState('selectedAsset', id);
    }
}

// ════════════════════════════════════════════════════════════════
//  L3 Phase 2 — predictive What-If simulation sandbox
//
//  A LIVE <-> WHAT-IF toggle. In WHAT-IF the SLD disconnects from the
//  Hermes telemetry feed (frozen state), the view gains a hazard-stripe
//  border, and any node-click injects a simulated fault into the LOCAL
//  DAG fault-cascade engine — computed + rendered purely in frontend
//  memory. Returning to LIVE clears the simulated trips and re-syncs.
// ════════════════════════════════════════════════════════════════
function _setMode(mode) {
    _mode = (mode === 'whatif') ? 'whatif' : 'live';
    // Entering the sandbox retires the N-1 shadow (it assumes the
    // intact topology the sandbox is about to mutate).
    if (_mode === 'whatif') _setN1(false);
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

// ════════════════════════════════════════════════════════════════
//  N-1 SHADOW (innovation track) — the blast radius, always visible
//
//  Pure steady-state contingency over the same DAG topology: every
//  node carries its sustained single-failure consequence as a badge
//  (lost / degraded / absorbed; battery holdup honestly excluded),
//  hover lights the victims. Disabled inside the What-If sandbox —
//  the sandbox mutates the topology state the shadow assumes intact.
// ════════════════════════════════════════════════════════════════
const _n1Overlay = createN1Overlay({
    rootSelector: '#view-power .pid-svg',
    nodeSelector: '.pf-node',
    idAttr: 'sldNode',
    nameSelector: '.pf-name',
    analysisFn: n1Power,
});

function _setN1(on) {
    if (on && _mode === 'whatif') return;   // sandbox excludes the shadow
    if (on) _n1Overlay.attach(); else _n1Overlay.detach();
    const btn = document.getElementById('pwr-n1-toggle');
    if (btn) {
        btn.dataset.on = on ? '1' : '0';
        btn.classList.toggle('is-on', on);
    }
}

function _buildN1Toggle() {
    if (document.getElementById('pwr-n1-toggle')) return;
    const view = document.getElementById('view-power');
    if (!view) return;
    const btn = document.createElement('button');
    btn.id = 'pwr-n1-toggle';
    btn.type = 'button';
    btn.className = 'pwr-mode-toggle pwr-n1-toggle';
    btn.dataset.on = '0';
    btn.textContent = '◬ N-1 SHADOW';
    btn.title = 'Sustained single-failure contingency painted on the SLD '
        + '(structural availability; battery holdup excluded)';
    btn.addEventListener('click', () => _setN1(btn.dataset.on !== '1'));
    const bar = view.querySelector('.pid-action-bar') || view;
    const modeBtn = document.getElementById('pwr-mode-toggle');
    bar.insertBefore(btn, modeBtn ? modeBtn.nextSibling : bar.firstChild);
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

// ════════════════════════════════════════════════════════════════
//  FORENSIC REPLAY (innovation track R2) — scrub the session back
//
//  The diagrams are pure functions of state (Diagram Rebuild), so
//  replay = re-render of flight-recorder snapshots. Operator
//  actions from the Forensic Ledger ride the timeline as markers,
//  each carrying its HMAC chain prefix — auditable replay.
// ════════════════════════════════════════════════════════════════
function _fmtClock(t) {
    return new Date(t).toLocaleTimeString();
}

function _scrubTo(t) {
    const snap = snapshotAt(Number(t));
    if (snap.telemetry?.channels) _applyTelemetry(snap.telemetry.channels);
    if (snap.grid) _applyGrid(snap.grid);
    const timeEl = document.getElementById('pwr-replay-time');
    if (timeEl) timeEl.textContent = _fmtClock(Number(t));
}

async function _loadLedgerMarkers(start, end) {
    const host = document.querySelector('#pwr-replay-bar .rp-markers');
    if (!host) return;
    host.innerHTML = '';
    try {
        const r = await fetch('/api/ledger/entries?limit=200');
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const data = await r.json();
        const entries = (data.entries || []).filter((e) => {
            const t = Date.parse(e.ts);
            return Number.isFinite(t) && t >= start && t <= end;
        });
        for (const e of entries) {
            const t = Date.parse(e.ts);
            const dot = document.createElement('button');
            dot.type = 'button';
            dot.className = 'rp-marker';
            dot.style.left = (((t - start) / Math.max(1, end - start)) * 100).toFixed(2) + '%';
            dot.title = `#${e.sequence_no} ${e.action} · ${e.actor}`
                + ` · hmac ${(e.entry_hmac_hex || '').slice(0, 12)}…`;
            dot.addEventListener('click', () => {
                const slider = document.getElementById('pwr-replay-slider');
                if (slider) { slider.value = String(t); _scrubTo(t); }
                const det = document.getElementById('pwr-replay-entry');
                if (det) {
                    det.textContent = `⛓ #${e.sequence_no} ${e.action} · ${e.actor}`
                        + ` · ${_fmtClock(t)} · hmac ${(e.entry_hmac_hex || '').slice(0, 12)}…`;
                }
            });
            host.appendChild(dot);
        }
        const det = document.getElementById('pwr-replay-entry');
        if (det && !entries.length) det.textContent = 'no ledger actions in window';
    } catch (err) {
        console.warn('[power] ledger markers unavailable:', err.message);
    }
}

function _buildReplayBar() {
    let bar = document.getElementById('pwr-replay-bar');
    if (bar) { bar.hidden = false; return bar; }
    const view = document.getElementById('view-power');
    if (!view) return null;
    bar = document.createElement('div');
    bar.id = 'pwr-replay-bar';
    bar.className = 'pwr-replay-bar';
    bar.innerHTML = `
        <span class="rp-title">⏮ SESSION FLIGHT RECORDER</span>
        <span class="rp-scope">in-browser ring buffer · ~10 min · session only — not persisted history</span>
        <div class="rp-track">
            <input type="range" id="pwr-replay-slider" step="1000">
            <div class="rp-markers"></div>
        </div>
        <span class="rp-time" id="pwr-replay-time">—</span>
        <span class="rp-entry" id="pwr-replay-entry"></span>`;
    const anchor = view.querySelector('.pid-action-bar');
    if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(bar, anchor.nextSibling);
    else view.insertBefore(bar, view.firstChild);
    bar.querySelector('#pwr-replay-slider')
        .addEventListener('input', (e) => _scrubTo(e.target.value));
    return bar;
}

function _setReplay(on) {
    const btn = document.getElementById('pwr-replay-toggle');
    if (on) {
        const win = recorderRange();
        if (win.count < 2) {
            console.warn('[power] replay: buffer empty — recording runs since page load');
            return;
        }
        _setN1(false);
        _mode = 'replay';
        const view = document.getElementById('view-power');
        if (view) view.classList.add('pwr-replay');
        const bar = _buildReplayBar();
        if (bar) {
            const slider = bar.querySelector('#pwr-replay-slider');
            slider.min = String(win.start);
            slider.max = String(win.end);
            slider.value = String(win.end);
            _scrubTo(win.end);
            _loadLedgerMarkers(win.start, win.end);
        }
    } else {
        _mode = 'live';
        const view = document.getElementById('view-power');
        if (view) view.classList.remove('pwr-replay');
        const bar = document.getElementById('pwr-replay-bar');
        if (bar) bar.hidden = true;
        _refresh();   // re-sync to live; Hermes resumes on next frame
    }
    if (btn) {
        btn.dataset.on = on && _mode === 'replay' ? '1' : '0';
        btn.classList.toggle('is-on', _mode === 'replay');
    }
}

function _buildReplayToggle() {
    if (document.getElementById('pwr-replay-toggle')) return;
    const view = document.getElementById('view-power');
    if (!view) return;
    const btn = document.createElement('button');
    btn.id = 'pwr-replay-toggle';
    btn.type = 'button';
    btn.className = 'pwr-mode-toggle pwr-n1-toggle';
    btn.dataset.on = '0';
    btn.textContent = '⏮ REPLAY';
    btn.title = 'Forensic replay: scrub the session flight recorder; '
        + 'ledger actions ride the timeline with their HMAC chain';
    btn.addEventListener('click', () => _setReplay(btn.dataset.on !== '1'));
    const bar = view.querySelector('.pid-action-bar') || view;
    const n1Btn = document.getElementById('pwr-n1-toggle');
    bar.insertBefore(btn, n1Btn ? n1Btn.nextSibling : bar.firstChild);
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
    // Batch 1: render the registry-driven orthogonal SLD (Phase 1 2N
    // paths + Phase 2 Building D design branch) into .pid-svg.
    _renderFlatSld();
    // L3 Phase 1: breaker nodes are interactive actuators. Delegated on
    // the .pid-svg element so it survives _renderFlatSld() re-renders.
    const flatSvg = document.querySelector('#view-power .pid-svg');
    if (flatSvg) flatSvg.addEventListener('click', _onFlatClick);
    // L3 Phase 2: LIVE <-> WHAT-IF toggle + flat-SLD render of the local
    // DAG fault-cascade (the sandbox's simulated faults become visible).
    _buildModeToggle();
    _buildN1Toggle();
    _buildReplayToggle();
    // R2: arm the session black box (records Hermes + DAG planes).
    startRecording();
    subscribe('grid', _applyGrid);
    // T3.1: live severity from the Hermes telemetry stream — the legacy
    // 5 s setInterval poll is eradicated.
    _unsubTelemetry = onHermesStream('telemetry', _onTelemetryFrame);
    _initialized = true;
    console.log('[power] view ready (Tier IV SLD — diagram-kit rebuild, Hermes-bound)');
}

// ─── Test surface ──────────────────────────────────────────────────
export const __power_test__ = {
    nodeMap: _NODE_MAP,
    severityFromChannels,
    applyTopology: _applyTopology,
    applyTelemetry: _applyTelemetry,
    onTelemetryFrame: _onTelemetryFrame,
    buildFlatMarkup: _buildFlatMarkup,
    buildPhase2Markup: _flatPhase2,
    flatViewBox: _FLAT.viewBox,
    renderFlatSld: _renderFlatSld,
    openBreakerModal: _openBreakerModal,
    submitBreakerCommand: _submitBreakerCommand,
    onFlatClick: _onFlatClick,
    setMode: _setMode,
    getMode: () => _mode,
    buildModeToggle: _buildModeToggle,
    buildN1Toggle: _buildN1Toggle,
    setN1: _setN1,
    n1Overlay: _n1Overlay,
    setReplay: _setReplay,
    setFarmLod: _setFarmLod,
    getFarmLod: () => _farmLod,
    farmFocusViewBox: _FARM_FOCUS_VIEWBOX,
    scrubTo: _scrubTo,
    buildReplayToggle: _buildReplayToggle,
    loadLedgerMarkers: _loadLedgerMarkers,
    applyGrid: _applyGrid,
    sparkPoints,
    updateSparklines: _updateSparklines,
    channelMatcher: _channelMatcher,
    reset: () => {
        _initialized = false;
        _mode = 'live';
        _farmLod = 0;
        if (_unsubTelemetry) { _unsubTelemetry(); _unsubTelemetry = null; }
        const modal = document.getElementById('pwr-breaker-modal');
        if (modal) modal.remove();
        const replayBar = document.getElementById('pwr-replay-bar');
        if (replayBar) replayBar.remove();
        _n1Overlay.detach();
        _sparkTracker.reset();
    },
};
