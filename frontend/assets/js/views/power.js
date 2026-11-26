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
import { subscribe, setState, getState } from '../core/state.js';
import { toggleTrip, restoreAll, setUnitsOut, getTopology, PHASE1 } from '../core/power_grid.js';
import {
    pathFlows, fmtPower, fmtApparent, fmtReactive, PF,
    MV_KV, LV_V, NOMINAL_HZ, UPS_RUNTIME_SPEC_MIN,
} from '../core/power_flow.js';
import { statusStrip, EventLog } from '../core/power_status.js';
import { BREAKER_SCHEME, breakerText } from '../core/hmi_scheme.js';
import { AlarmEngine, conditionsFromGrid, alarmBannerHtml } from '../core/alarm_state.js';
import { apiFetch } from '../services/api.js';
import { mirrorGrid, plantModeLabel, isPlantSnapshot } from '../core/plant_mirror.js';
import { ControlRoomAudio } from '../core/control_room_audio.js';
import { plantPost, plantGet } from '../core/plant_client.js';
import { faceplateHtml } from '../core/sbo_faceplate.js';
import { trainingHtml } from '../core/training_view.js';
import { openPrintable } from '../core/training_print.js';
import { fieldLineupSvg, applyFieldState, resolveClick, fieldLogHtml } from '../core/field_switchgear.js';
import { xfmrSvg, applyXfmrState, resolveXfmrClick, isXfmrEvent, xfmrEventText } from '../core/field_xfmr.js';
import { genSvg, applyGenState, resolveGenClick, isGenEvent, genEventText, genId } from '../core/field_gen.js';
import { upsSvg, applyUpsState, resolveUpsClick, isUpsEvent, upsEventText } from '../core/field_ups.js';
import { needleAngle, permissive, etaNow, etaText } from '../core/synchroscope.js';
import { escapeHTML } from '../core/sanitize.js';
import { relayRowSvg, relayStates, applyRelays } from '../core/relay_tags.js';
import {
    attachViewport, viewportToolbarHtml, presetForPath, SLD_PRESETS, DEFAULT_PRESET,
} from '../core/sld_viewport.js';
import {
    severityFromChannels, symbol, wire, sparkPoints, sparkPolyline,
    createSparkTracker, createActuationModal, legend,
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
let _itKw = null;     // facility Phase 1 IT load from the topology feed (power_flow)
// vida 2: clocked event sequence derived from DAG snapshots
const _eventLog = new EventLog();
// HMI H4: sandbox alarms live in the browser (What-If only); live
// alarms are the backend state of the simulated plant (/api/alarms).
const _sandboxAlarms = new AlarmEngine();
let _liveAlarms = null;
let _alarmErr = '';    // live feed error
let _ackErr = '';      // last refused ACK (kept until an ACK succeeds)
let _alarmPollAt = 0;
const ALARM_POLL_MS = 3000;
// DC-EPMS-073: in LIVE the drawing follows the Power Controls plant.
let _plant = null;
let _plantAt = null;
let _plantAtMs = 0;
let _syncRaf = null;
// T2: training coach, SBO faceplate, control-room sounds.
const _audio = new ControlRoomAudio();
let _drills = [];
let _trView = null;
let _trSelected = '';
let _trMsg = '';
let _trTimer = null;
let _fpTarget = null;
let _fpMsg = '';
let _fpTimer = null;
const _fpPending = new Map();   // deviceId -> { token, label, expiresAt }
let _seenUnack = new Set();
let _prevXfer = {};
let _prevSteps = 0;
// UI-1: SLD viewport (named views, zoom, pan) + inspector toggle.
let _vp = null;
// L1: field view of the 13.8 kV switchgear (Layer 2).
let _fieldPath = null;
let _fieldEquip = 'swgr';      // L2: 'swgr' | 'xfmr'; L3: 'gen'
let _fieldGen = 1;             // L3: set number shown (1..9)
let _fieldMsg = '';
let _fieldBusy = false;
let _fieldTimer = null;
const _fieldCovers = new Set();
let _vpReturn = DEFAULT_PRESET;
let _inspOpen = true;
const _VP_KEY = 'dcepms.sld.view';
const _INSP_KEY = 'dcepms.sld.inspector';

/** The grid the drawing shows: plant mirror in LIVE, the DAG otherwise. */
function _effGrid(grid) {
    if (_mode === 'live' && grid && _plant) return mirrorGrid(grid, _plant);
    return grid;
}
let _clockTimer = null;

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
        _setMetric('util_a-kv', (ua.metrics.kv ?? 27.5).toFixed(1) + ` kV · ${NOMINAL_HZ} Hz`);
    }
    if (ub) {
        _setMetric('util_b-kw', Math.round(ub.metrics.kw ?? 0).toLocaleString() + ' kW');
        _setMetric('util_b-kv', (ub.metrics.kv ?? 27.5).toFixed(1) + ` kV · ${NOMINAL_HZ} Hz`);
    }
    // Transformer / UPS / RPP loads come from core/power_flow.js
    // (design-consistent: 8 x 2.5 MW blocks per path, eta 0.97). The
    // physics engine's unit-level samples (a 300 kW "UPS", a 1,800 kVA
    // transformer) contradicted the drawing and are not shown.
    if (xa) _setMetric('xfmr_a-c', (xa.metrics.winding_c ?? 0).toFixed(0) + '°C');
    if (xb) _setMetric('xfmr_b-c', (xb.metrics.winding_c ?? 0).toFixed(0) + '°C');
    if (upa) {
        _setMetric('ups_a-mode', upa.metrics.battery_on_load ? 'BATTERY' : 'ONLINE · η 97 %');
        _setMetric('batt_a-soc', 'SOC ' + Math.round((upa.metrics.soc ?? 1) * 100) + '%');
    }
    if (upb) {
        _setMetric('ups_b-mode', upb.metrics.battery_on_load ? 'BATTERY' : 'ONLINE · η 97 %');
        _setMetric('batt_b-soc', 'SOC ' + Math.round((upb.metrics.soc ?? 1) * 100) + '%');
    }

    const bwyA = nodes.busway_a, bwyB = nodes.busway_b;
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
    // MV transfer controller / generator bus state derived from UPS
    // battery-on-load (52-U closed = UTILITY, 52-GM closed = GENERATORS).
    const atsA = (upa && upa.metrics.battery_on_load) ? 'GENSET' : 'UTILITY';
    const atsB = (upb && upb.metrics.battery_on_load) ? 'GENSET' : 'UTILITY';
    _setMetric('mvtc_a-pos', atsA === 'GENSET' ? '52-GM · GEN BUS' : '52-U · UTILITY');
    _setMetric('mvtc_b-pos', atsB === 'GENSET' ? '52-GM · GEN BUS' : '52-U · UTILITY');
    _setMetric('genset_a-state', atsA === 'GENSET' ? 'RUNNING' : 'STANDBY');
    _setMetric('genset_b-state', atsB === 'GENSET' ? 'RUNNING' : 'STANDBY');

    // ─── Banner: total load + PUE + SHI + redundancy ───
    const totalLoad = (ua?.metrics.kw ?? 0) + (ub?.metrics.kw ?? 0);
    const itLoad = (nodes.hall_1?.metrics.load_kw ?? 0)
        + (nodes.hall_2?.metrics.load_kw ?? 0)
        + (nodes.hall_3?.metrics.load_kw ?? 0);
    const pue = (itLoad > 0 && totalLoad > 0) ? (totalLoad / itLoad) : null;
    _itKw = itLoad > 0 ? itLoad : null;
    _applyFlow(getState('grid'));

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
        // DC-EPMS-073: the physics topology carries its own UPS mode
        // guess; the plant mirror wins when it is loaded.
        if (_mode === 'live' && _plant) {
            const g = getState('grid');
            if (g) _applyGrid(_effGrid(g));
        }
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
    // HMI H4: live alarms ride the telemetry cadence (throttled).
    _pollAlarms();
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
    // Phase 1 closed design (DC-EPMS-068): 52-U between the transformer
    // and the generator junction; MV switchgear + unit substations
    // between the transfer controller and the UPS bank.
    p1: { u52: 330, swgr: 676, usub: 730 },
    spineY: { A: 232, B: 540 },
    phase2: { spineY: 880, headerY: 766, dividerY: 726, fenceX: 484 },
    // 50 MW track: genset farm row + power-budget caption block.
    farm: { busY: 1110, genY: 1180, tieX: 304 },
    viewBox: '0 0 1200 1260',
};

// Node types that are operable breakers — clickable in the control plane.
// The MV transfer controller is NOT actuated from the SLD: supervised
// switching lives in Power Controls (select-before-operate, ledger).
const _BREAKER_TYPES = new Set(['rpp']);

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
    const L = _FLAT.p1;                 // closed-design Phase 1 x positions
    const cls = energized; // 'pf-a' | 'pf-b'
    const genY = S - 116;
    const busY = S - 64;
    const gmY = S - 30;                 // 52-GM on the generator drop
    const battY = S + 130;             // clears the UPS metric + sparkline rows
    const X = suffix.toUpperCase();
    // HMI H1: every run also carries a STATIC direction chevron at its
    // midpoint (drawn first point -> second point = direction of power
    // flow). No animated dashes: ISA-101 reserves motion for abnormal.
    const arrow = (name, [[x1, y1], [x2, y2]]) => {
        const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
        const dx = Math.sign(x2 - x1), dy = Math.sign(y2 - y1);
        const tip = [mx + dx * 5, my + dy * 5];
        const b1 = [mx - dx * 4 - dy * 5, my - dy * 4 - dx * 5];
        const b2 = [mx - dx * 4 + dy * 5, my - dy * 4 + dx * 5];
        return `<path class="pf-arrow" data-arrow="${suffix}:${name}" `
            + `d="M${b1[0]} ${b1[1]} L${tip[0]} ${tip[1]} L${b2[0]} ${b2[1]}"/>`;
    };
    const seg = (name, pts, extra = '', withArrow = true) =>
        wire(pts, `${cls} pf-seg${extra}`).replace('<path ', `<path data-seg="${suffix}:${name}" `)
        + (withArrow ? arrow(name, pts) : '');
    // ── orthogonal wiring; every run carries data-seg for the flow layer ──
    const wires = [
        seg('util', [[T.util + 40, S], [T.xfmr - 14, S]]),
        seg('xfmr', [[T.xfmr + 14, S], [L.u52 - 11, S]]),
        seg('u52', [[L.u52 + 11, S], [T.gen, S]]),
        seg('gen', [[T.gen, genY + 23], [T.gen, busY - 5]]),
        seg('bus', [[T.gen, busY + 5], [T.gen, gmY - 11]]),
        seg('gm', [[T.gen, gmY + 11], [T.gen, S]]),
        seg('mv', [[T.gen, S], [T.ats - 40, S]]),
        seg('mvtc', [[T.ats + 40, S], [L.swgr - 5, S]]),
        // HMI H2: these two runs carry the unit-substation breakers
        // instead of a chevron (no room for both).
        seg('swgr', [[L.swgr + 5, S], [L.usub - 14, S]], '', false),
        seg('usub', [[L.usub + 14, S], [T.ups - 40, S]], '', false),
        seg('ups', [[T.ups + 40, S], [T.pdu - 40, S]]),
        seg('batt', [[T.ups, battY - 23], [T.ups, S + 23]]),
    ].join('');
    // ── nodes ──
    const nodes = [
        _flatNode('util_' + suffix, 'util', 'UTILITY ' + X,
            T.util, S, [{ key: 'util_' + suffix + '-kv', text: '27.5 kV · 60 Hz' },
                        { key: 'util_' + suffix + '-kw', text: '— kW' }]),
        _flatNode('xfmr_' + suffix, 'xfmr', 'XFMR ' + X,
            T.xfmr, S, [{ key: 'xfmr_' + suffix + '-load', text: '— MVA' },
                        { key: 'xfmr_' + suffix + '-ratio', text: '27.5/13.8 kV' }]),
        _flatNode('genset_' + suffix, 'genset',
            'GEN BUS ' + X + ` · ${PHASE1.gen.units} × ${PHASE1.gen.unitKw / 1000} MW`,
            T.gen, genY, [{ key: 'genset_' + suffix + '-state', text: 'STANDBY' }]),
        _flatNode('mvtc_' + suffix, 'mvtc', 'MV TRANSFER ' + X + ' · 13.8 kV',
            T.ats, S, [{ key: 'mvtc_' + suffix + '-pos', text: '52-U · UTILITY' }]),
        _flatNode('ups_' + suffix, 'ups',
            'UPS BANK ' + X + ` · ${PHASE1.ups.units} × TRINERGY`,
            T.ups, S, [{ key: 'ups_' + suffix + '-mode', text: 'ONLINE' },
                       { key: 'ups_' + suffix + '-load', text: '— MW' }]),
        // H3: autonomy is the design spec (config/power_plant.yml,
        // runtime_full_load_min), not a discharge-curve estimate.
        _flatNode('batt_' + suffix, 'batt',
            `BATTERY ${X} · ${UPS_RUNTIME_SPEC_MIN} MIN @ ${PHASE1.ups.units * PHASE1.ups.unitKw / 1000} MW (SPEC)`,
            T.ups, battY, [{ key: 'batt_' + suffix + '-soc', text: 'SOC 100%' }]),
        _flatNode('rpp_' + suffix + '1', 'rpp', 'RPP / PDU ' + X,
            T.pdu, S, [{ key: 'rpp_' + suffix + '1-kw', text: '— kW' },
                       { key: 'rpp_' + suffix + '1-lv', text: `${LV_V} V 3-ph · ${NOMINAL_HZ} Hz` }]),
    ].join('');
    // paralleling bus: label to the right so it never covers the G glyph
    const parBus = `<g class="sld-node pf-node" data-sld-node="par_bus_${suffix}">`
        + `<rect class="pf-sym pid-symbol pf-bus" data-sev="ok" x="${T.gen - 52}" y="${busY - 5}" width="104" height="10" rx="2"/>`
        + `<text class="pf-sub-label" x="${T.gen + 60}" y="${busY + 4}">PARALLELING BUS · 13.8 kV · ANSI 25</text></g>`;
    // 13.8 kV MV main switchgear (vertical bus bar) + unit substations
    const mv = `<g class="sld-node pf-node" data-sld-node="mv_swgr_${suffix}">`
        + `<rect class="pf-sym pid-symbol pf-bus" data-sev="ok" x="${L.swgr - 5}" y="${S - 26}" width="10" height="52" rx="2"/>`
        + `<text class="pf-sub-label pf-center" x="${L.swgr}" y="${S + 56}">13.8 kV SWGR</text></g>`
        + `<g class="sld-node pf-node" data-sld-node="usub_${suffix}">`
        + `<circle class="pf-sym pid-symbol" data-sev="ok" cx="${L.usub}" cy="${S - 8}" r="14"/>`
        + `<circle class="pf-sym pid-symbol" data-sev="ok" cx="${L.usub}" cy="${S + 8}" r="14"/>`
        + `<text class="pf-sub-label pf-end" x="${L.usub + 16}" y="${S + 40}">${PHASE1.ups.units} × 3.5 MVA</text>`
        + `<title>${PHASE1.ups.units} unit substations 13.8 kV / 480 V, 3.5 MVA each (sizing assumption, site model v2)</title></g>`;
    // ANSI 52 breakers: 52-U on the utility incomer, 52-GM on the
    // generator main. Drawn open or closed from the DAG (_applyFlow).
    // HMI H1: the colour convention lives in core/hmi_scheme.js and the
    // state is ALSO written as text, so colour is never the only cue.
    const brk = (id, label, x, y, labelX, labelY, anchor, st) =>
        `<g class="pf-52" data-brk="${suffix}:${id}" data-state="closed">`
        + `<rect class="pf-52-box" x="${x - 11}" y="${y - 11}" width="22" height="22" rx="2"/>`
        + `<path class="pf-52-blade" d="M${x - 7} ${y + 7} L${x + 7} ${y - 7}"/>`
        + `<text class="pf-52-label" x="${labelX}" y="${labelY}" text-anchor="${anchor}">${label}</text>`
        + `<text class="pf-52-state" x="${st[0]}" y="${st[1]}" text-anchor="${st[2]}">`
        + `${breakerText('closed')}</text>`
        // L1: switchgear cubicle state (racked out, 86, padlock)
        + `<text class="pf-52-cub" data-cub="${suffix}:${id}" x="${id === 'gm' ? x - 16 : st[0]}" `
        + `y="${id === 'gm' ? y + 6 : st[1] + 10}" text-anchor="${id === 'gm' ? 'end' : st[2]}"></text></g>`;
    const breakers = brk('u', '52-U', L.u52, S, L.u52 - 13, S - 14, 'end', [L.u52, S + 25, 'middle'])
        + brk('gm', '52-GM', T.gen, gmY, T.gen - 18, gmY - 6, 'end', [T.gen + 16, gmY + 4, 'start'])
        // HMI H2: 52-U / 52-GM interlock (the transfer is open-transition
        // in the model: the two mains are never closed together).
        + `<path class="pf-interlock" data-interlock="${suffix}" `
        + `d="M${L.u52} ${S - 11} L${L.u52} ${gmY} L${T.gen - 11} ${gmY}">`
        + `<title>Interlock 52-U / 52-GM: never closed together (open transition)</title></path>`
        // HMI H2: unit substation primary (13.8 kV) and secondary
        // (480 V main) breakers. No device model or telemetry exists
        // for them: drawn in the design normal lineup, marked MODEL.
        + _miniBrk(suffix, 'sp', '52-P', (L.swgr + 5 + L.usub - 14) / 2, S,
            'Unit substation primary breaker, 13.8 kV (design normal lineup, not modelled or metered)')
        + _miniBrk(suffix, 'ss', '52-S', (L.usub + 14 + T.ups - 40) / 2, S,
            'Unit substation secondary main, 480 V (design normal lineup, not modelled or metered)');
    // HMI H3: design-model data tag on the 13.8 kV bus (filled by
    // _applyFlow). Every value here is computed, never metered.
    const tag = `<g class="pf-tag" data-tag="${suffix}:mv">`
        + `<rect class="pf-tag-box" x="402" y="${S + 30}" width="146" height="46" rx="3"/>`
        + `<text class="pf-tag-head" x="408" y="${S + 42}">MODEL · MV ${MV_KV} kV · ${NOMINAL_HZ} Hz</text>`
        + `<text class="pf-tag-line" data-tag-line="${suffix}:pq" x="408" y="${S + 56}"></text>`
        + `<text class="pf-tag-line" data-tag-line="${suffix}:spf" x="408" y="${S + 69}"></text>`
        + `<title>Design model: P from the IT load and UPS efficiency, PF ${PF.toFixed(2)} assumed, transformer losses not modelled. Not metering.</title></g>`;
    // power-flow labels (filled by _applyFlow)
    const flowTxt = (key, x, y, anchor = 'middle') =>
        `<text class="pf-flow-label" data-flow="${suffix}:${key}" x="${x}" y="${y}" text-anchor="${anchor}"></text>`;
    const labels = flowTxt('mv', (T.gen + T.ats - 40) / 2, S - 8)
        + flowTxt('ups', (T.ups + 40 + T.pdu - 40) / 2, S - 8)
        + flowTxt('gen', T.gen + 18, gmY - 16, 'start');
    const strips = _unitStrip('genset_' + suffix, T.gen, genY - 52)
        + _unitStrip('ups_' + suffix, T.ups, S - 52);
    // T4: protective relay tags of the incomer / transformer (27 and 25
    // simulated, the rest identification only: core/relay_tags.js).
    const relays = relayRowSvg(suffix, 232, S + 84);
    return `<g class="pf-pathgroup" data-path="${suffix}">${wires}${breakers}${mv}${parBus}${nodes}${labels}${strips}${tag}${relays}</g>`;
}

/** HMI H2: small breaker for devices the model does not operate. */
function _miniBrk(suffix, id, label, x, y, title) {
    return `<g class="pf-52 pf-52-mini" data-brk="${suffix}:${id}" data-state="closed" data-model="design">`
        + `<rect class="pf-52-box" x="${x - 7}" y="${y - 7}" width="14" height="14" rx="2"/>`
        + `<path class="pf-52-blade" d="M${x - 4} ${y + 4} L${x + 4} ${y - 4}"/>`
        + `<text class="pf-52-label" x="${x}" y="${y - 11}" text-anchor="middle">${label}</text>`
        + `<title>${escapeHTML(title)}</title></g>`;
}

/**
 * DC-EPMS-068: one tick per installed unit of a bank (UPS blocks,
 * generator sets), so the drawing cannot claim capacity the design
 * does not have. Ticks reflect units out of service (What-If) and the
 * caption carries capacity with N / N+1 from the DAG engine.
 */
function _unitStrip(id, x, y) {
    const t = getTopology()[id];
    if (!t || !t.units) return '';
    const w = 9, gap = 3;
    const total = t.units * w + (t.units - 1) * gap;
    const x0 = x - total / 2;
    const ticks = Array.from({ length: t.units }, (_, i) =>
        `<rect class="pf-unit" data-unit-of="${id}" data-unit="${i}" data-out="0" `
        + `x="${x0 + i * (w + gap)}" y="${y - 6}" width="${w}" height="12" rx="1.5">`
        + `<title>${escapeHTML(id)} unit ${i + 1} of ${t.units}</title></rect>`).join('');
    const cap = `<text class="pf-metric pf-unit-cap" data-sld-metric="${id}-cap" `
        + `x="${x0 + total + 8}" y="${y + 4}" text-anchor="start">`
        + `${((t.units * t.unitKw) / 1000).toFixed(2)} MW</text>`;
    return `<g class="pf-unit-strip" data-units-for="${id}">${ticks}${cap}</g>`;
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
    // Headless markup consumers (scripts/preview_diagrams.mjs) flip
    // the LOD state without a DOM — the builders stay pure.
    if (typeof document === 'undefined') return;
    const svg = document.querySelector('#view-power .pid-svg');
    if (!svg) return;
    svg.innerHTML = _buildFlatMarkup();
    if (_vp) {
        if (_farmLod === 1) { _vpReturn = _vp.preset || _vpReturn; _vp.set('farm'); }
        else _vp.set(_vpReturn === 'farm' ? DEFAULT_PRESET : _vpReturn);
    } else {
        svg.setAttribute('viewBox', _farmLod === 1 ? _FARM_FOCUS_VIEWBOX : _FLAT.viewBox);
    }
    if (_initialized) _refresh();
}

/** Build the full flat-SLD SVG inner markup from the tiered topology. */
function _buildFlatMarkup() {
    const T = _FLAT.tierX;
    const tierLabels = [
        ['UTILITY', T.util], ['GEN BUS 13.8 kV', T.gen],
        ['MV TRANSFER', T.ats], ['UPS 2N', T.ups], ['PDU / RPP', T.pdu],
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
        // two blocks so the legend never sits on the UTILITY A label
        + legend(_HMI_LEGEND.slice(0, 5), 16, 96)
        + legend(_HMI_LEGEND.slice(5), 16, 640);
}

// HMI H1 legend: grey = normal, colour = exception; breaker convention
// from the site scheme; AC/DC kept for the Phase 2 design branch.
const _HMI_LEGEND = Object.freeze([
    { swatch: 'energized', label: 'Energized (normal, grey)' },
    { swatch: 'deenergized', label: 'De-energized' },
    { swatch: 'brk-closed', label: BREAKER_SCHEME.legendClosed },
    { swatch: 'brk-open', label: BREAKER_SCHEME.legendOpen },
    { swatch: 'relay', label: 'Relay 27 / 25 simulated · N/M = not modelled' },
    { swatch: 'interlock', label: 'Interlock (52-U / 52-GM)' },
    { swatch: 'model', label: 'MODEL = design value, not metered' },
    { swatch: 'warning', label: 'Warning (|z| >= 2)' },
    { swatch: 'critical', label: 'Critical / anomalous' },
    { swatch: 'dc', label: '800 VDC unipolar TN-S (design)' },
]);

/** Render the orthogonal flat SLD into the legacy .pid-svg container. */
function _renderFlatSld() {
    const svg = document.querySelector('#view-power .pid-svg');
    if (!svg) return;
    if (_vp) _vp.reapply(); else svg.setAttribute('viewBox', _FLAT.viewBox);
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    svg.classList.add('pf-svg');
    svg.setAttribute('data-scheme', BREAKER_SCHEME.id);
    svg.innerHTML = _buildFlatMarkup();
    // Paint the current DAG state at once (unit captions, breakers,
    // flow) instead of waiting for the next grid change.
    const g0 = getState('grid');
    if (g0) _applyGrid(_effGrid(g0)); else _applyFlow(null);
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
    // What-If: a unit tick takes one more unit of that bank out of
    // service (in-service tick) or returns one (out-of-service tick).
    const tick = e.target.closest && e.target.closest('.pf-unit');
    if (tick) {
        if (_mode !== 'whatif') return;
        const bank = tick.dataset.unitOf;
        const grid = getState('grid') || {};
        const out = grid[bank]?.units_out || 0;
        setUnitsOut(bank, tick.dataset.out === '1' ? out - 1 : out + 1);
        return;
    }
    // T2: 52-U / 52-GM open the MV transfer faceplate in LIVE.
    const brk = e.target.closest && e.target.closest('.pf-52');
    if (brk && _mode === 'live') {
        const [p, which] = String(brk.dataset.brk || '').split(':');
        if (which === 'u' || which === 'gm') _openFaceplate('mvtc_' + p);
        return;
    }
    const node = e.target.closest('.pf-node');
    if (!node) return;
    const id = node.dataset.sldNode;
    // L1: the 13.8 kV switchgear bus opens the field view in LIVE.
    if (_mode === 'live' && /^mv_swgr_[ab]$/.test(id || '')) {
        _openField(id.slice(-1), 'swgr');
        return;
    }
    // L2: the utility transformer opens its field view in LIVE.
    if (_mode === 'live' && /^xfmr_[ab]$/.test(id || '')) {
        _openField(id.slice(-1), 'xfmr');
        return;
    }
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
    if (/^(mvtc|genset|ups)_[ab]$/.test(id)) _openFaceplate(id);
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
    // Each sandbox session starts its own sequence at t = 0.
    _eventLog.reset(_mode === 'whatif' ? getState('grid') : null);
    _renderTimeline();
    // Each sandbox session starts with a clean alarm list.
    _sandboxAlarms.reset();
    if (_mode === 'whatif') {
        const g = getState('grid');
        if (g) _sandboxAlarms.evaluate(conditionsFromGrid(g, _itKw ?? undefined));
    } else {
        _pollAlarms(true);
    }
    _renderAlarms();
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
/** T4: relay chips follow the live plant (LIVE) or the DAG sandbox. */
function _applyRelays(grid) {
    const root = document.querySelector('#view-power .pid-svg');
    if (!root) return;
    const plant = _mode === 'live' ? _plant : null;
    for (const p of ['a', 'b']) applyRelays(root, p, relayStates(p, plant, grid));
    // L1: cubicle state next to 52-U / 52-GM (LIVE only: the What-If
    // sandbox has no switchgear model).
    for (const p of ['a', 'b']) {
        const xfer = plant && (plant.devices || []).find((d) => d.id === `mvtc_${p}`);
        for (const [key, brk] of [['u', '52-U'], ['gm', '52-GM']]) {
            const c = xfer && (xfer.cubicles || []).find((x) => x.breaker === brk);
            const t = root.querySelector(`[data-cub="${p}:${key}"]`);
            const g = root.querySelector(`[data-brk="${p}:${key}"]`);
            const parts = [];
            if (c && c.racking !== 'CONNECTED') parts.push(c.racking === 'TEST' ? 'TEST' : 'DISC');
            if (c && c.lockout_86) parts.push('86');
            if (c && c.padlock) parts.push('LOCKED');
            if (t) t.textContent = parts.join(' · ');
            if (g) {
                g.setAttribute('data-racked', c && c.racking !== 'CONNECTED' ? '1' : '0');
                g.setAttribute('data-lockout', c && c.lockout_86 ? '1' : '0');
            }
        }
        // L2: DETC position and 86T on the transformer symbol (LIVE).
        const tr = xfer && xfer.transformer;
        _setMetric(`xfmr_${p}-ratio`, tr
            ? `27.5/13.8 kV · POS ${tr.tap}${tr.lockout_86t ? ' · 86T' : (tr.primary_closed ? '' : ' · 52-T OPEN')}`
            : '27.5/13.8 kV');
    }
}

function _applyGrid(grid) {
    if (!grid) return;
    document.querySelectorAll('#view-power .pid-svg .pf-node').forEach((node) => {
        const n = grid[node.dataset.sldNode];
        if (!n) return;
        let sev = 'ok';
        if (n.type === 'genset' && !n.tripped) {
            // A standby generator bus is healthy, not a fault: only a
            // crank in progress or running on load is worth a colour.
            sev = n.state === 'cranking' ? 'warning' : (n.alive ? 'warning' : 'ok');
        } else if (n.tripped || n.alive === false) sev = 'critical';
        else if (n.on_battery || n.energized_by === 'genset' || n.plant_mode === 'static_bypass') sev = 'warning';
        node.querySelectorAll('.pid-symbol').forEach((s) => s.setAttribute('data-sev', sev));
        node.classList.toggle('pf-tripped', !!n.tripped);
    });
    _applyUnits(grid);
    _applyFlow(grid);
    _applyRelays(grid);
    _eventLog.observe(grid);
    _renderVida2(grid);
    // Transfer position from the DAG (What-If / Replay show the
    // simulated 52-U / 52-GM state, not the live telemetry guess).
    for (const p of ['a', 'b']) {
        const t = grid['mvtc_' + p];
        if (!t) continue;
        const txt = t.transferring ? 'OPEN · IN TRANSFER'
            : (t.ats_pos === 'secondary' ? '52-GM · GEN BUS' : '52-U · UTILITY');
        _setMetric('mvtc_' + p + '-pos', txt);
        const upsLabel = plantModeLabel(grid['ups_' + p]);
        if (upsLabel) _setMetric('ups_' + p + '-mode', upsLabel);
    }
}

// ── vida 2: per-path status strip + clocked event sequence ──────
function _ensureVida2Panels() {
    const canvas = document.querySelector('#view-power .pid-canvas');
    if (!canvas || document.getElementById('pwr-status')) return;
    // The live view wraps the canvas in a flex row with the info panel;
    // the strip and the sequence go above / below that whole row.
    const anchor = canvas.closest('.sld-stage-row') || canvas;
    const strip = document.createElement('div');
    strip.id = 'pwr-status';
    strip.className = 'pwr-strip';
    strip.setAttribute('aria-label', 'Phase 1 path status');
    strip.setAttribute('data-scheme', BREAKER_SCHEME.id);
    // HMI H4: alarm banner above the status strip.
    const al = document.createElement('section');
    al.id = 'pwr-alarms';
    al.className = 'pwr-al';
    al.setAttribute('aria-label', 'Alarm banner');
    al.setAttribute('aria-live', 'polite');
    al.addEventListener('click', _onAlarmClick);
    // T2: training coach above the alarms, faceplate as a side panel.
    const tr = document.createElement('section');
    tr.id = 'pwr-training';
    tr.className = 'pwr-tr';
    tr.setAttribute('aria-label', 'Operator training');
    tr.addEventListener('click', _onTrainingClick);
    tr.addEventListener('change', (ev) => {
        if (ev.target.dataset.trSelect) _trSelected = ev.target.value;
    });
    anchor.parentNode.insertBefore(tr, anchor);
    const fp = document.createElement('aside');
    fp.id = 'pwr-faceplate';
    fp.className = 'pwr-fp';
    fp.hidden = true;
    fp.setAttribute('aria-label', 'Select-before-operate faceplate');
    fp.addEventListener('click', _onFaceplateClick);
    (document.getElementById('view-power') || anchor.parentNode).appendChild(fp);
    anchor.parentNode.insertBefore(al, anchor);
    anchor.parentNode.insertBefore(strip, anchor);
    const tl = document.createElement('section');
    tl.id = 'pwr-timeline';
    tl.className = 'pwr-tl';
    tl.innerHTML = '<div class="pwr-tl-head"><span>SEQUENCE OF EVENTS · WHAT-IF</span>'
        + '<span class="pwr-tl-clock" id="pwr-tl-clock">t = —</span></div>'
        + '<div class="pwr-tl-body" id="pwr-tl-body" aria-live="polite"></div>';
    anchor.parentNode.insertBefore(tl, anchor.nextSibling);
}

function _renderTimeline() {
    const body = document.getElementById('pwr-tl-body');
    if (body) body.innerHTML = _eventLog.render();
    const clock = document.getElementById('pwr-tl-clock');
    const t = _eventLog.elapsed();
    if (clock) clock.textContent = t === null ? 't = —' : `t = ${t.toFixed(1)} s`;
    // The clock runs while a sequence is fresh (first 30 s), then stops.
    const running = t !== null && t < 30 && _mode === 'whatif';
    if (running && !_clockTimer) {
        _clockTimer = setInterval(() => {
            const c = document.getElementById('pwr-tl-clock');
            const e = _eventLog.elapsed();
            if (c && e !== null) c.textContent = `t = ${e.toFixed(1)} s`;
            if (e === null || e >= 30 || _mode !== 'whatif') { clearInterval(_clockTimer); _clockTimer = null; }
        }, 100);
    }
}

function _renderVida2(grid) {
    _ensureVida2Panels();
    const strip = document.getElementById('pwr-status');
    if (strip) strip.innerHTML = statusStrip(grid, _itKw ?? undefined);
    _renderTimeline();
    if (_mode === 'whatif') _sandboxAlarms.evaluate(conditionsFromGrid(grid, _itKw ?? undefined));
    _renderAlarms();
}

// ── HMI H4: alarm banner ────────────────────────────────────────
function _renderAlarms() {
    _renderHud();
    const el = document.getElementById('pwr-alarms');
    if (!el) return;
    const sandbox = _mode === 'whatif';
    el.dataset.source = sandbox ? 'sandbox' : 'live';
    el.innerHTML = sandbox
        ? alarmBannerHtml(_sandboxAlarms.snapshot(), { source: 'sandbox' })
        : alarmBannerHtml(_liveAlarms, { source: 'live', error: _alarmErr || _ackErr, syncedAt: _plantAt });
}

async function _pollAlarms(force = false) {
    const now = Date.now();
    const gap = _trView && _trView.active ? 900 : ALARM_POLL_MS;
    if (!force && now - _alarmPollAt < gap) return;
    _alarmPollAt = now;
    const [al, plant] = await Promise.allSettled([
        apiFetch('/api/alarms', { credentials: 'same-origin' }),
        apiFetch('/api/devices', { credentials: 'same-origin' }),
    ]);
    if (al.status === 'fulfilled') {
        _liveAlarms = al.value;
        _alarmErr = '';
    } else {
        _alarmErr = 'Live alarms unavailable: ' + String(al.reason?.message || al.reason).slice(0, 120);
    }
    // DC-EPMS-073: no plant -> the drawing falls back to the nominal DAG.
    if (plant.status === 'fulfilled' && isPlantSnapshot(plant.value)) {
        _plant = plant.value;
        _plantAt = new Date();
        _plantAtMs = Date.now();
    } else {
        _plant = null;
        _plantAt = null;
    }
    _soundCues();
    if (_mode !== 'whatif') {
        const g = getState('grid');
        if (g) _applyGrid(_effGrid(g));
        _renderAlarms();
    }
    _renderFaceplate();
    _applyField();
}

// ── T2: sound cues from plant / alarm changes ────────────────────
function _soundCues() {
    const unack = new Set(((_liveAlarms && _liveAlarms.alarms) || [])
        .filter((a) => a.state === 'UNACK').map((a) => a.id));
    const fresh = ((_liveAlarms && _liveAlarms.alarms) || [])
        .filter((a) => a.state === 'UNACK' && !_seenUnack.has(a.id));
    if (fresh.length) _audio.alarm(fresh.some((a) => a.priority === 'HIGH') ? 'HIGH' : 'MEDIUM');
    _seenUnack = unack;
    const xfer = {};
    for (const d of ((_plant && _plant.devices) || [])) if (d.kind === 'transfer') xfer[d.id] = d.state;
    for (const [id, st] of Object.entries(xfer)) {
        if (_prevXfer[id] && _prevXfer[id] !== st) _audio.breaker(st !== 'OPEN');
    }
    _prevXfer = xfer;
}

// ── T2: training coach ───────────────────────────────────────────
// ── UI-1: SLD viewport + inspector toggle + drill HUD ───────────
function _store(key, value) {
    try { localStorage.setItem(key, value); } catch (_e) { /* storage off */ }
}
function _load(key) {
    try { return localStorage.getItem(key); } catch (_e) { return null; }
}

function _buildViewport(svg) {
    const canvas = svg && svg.closest('.pid-canvas');
    if (!canvas || document.getElementById('pwr-vp')) return;
    canvas.classList.add('vp-canvas');
    const bar = document.createElement('div');
    bar.id = 'pwr-vp';
    bar.className = 'pwr-vp';
    bar.setAttribute('role', 'toolbar');
    bar.setAttribute('aria-label', 'Diagram view');
    bar.addEventListener('click', _onViewportClick);
    canvas.insertBefore(bar, canvas.firstChild);
    const hud = document.createElement('div');
    hud.id = 'pwr-hud';
    hud.className = 'pwr-hud';
    hud.hidden = true;
    hud.setAttribute('aria-live', 'polite');
    hud.addEventListener('click', _onAlarmClick);
    canvas.appendChild(hud);
    const savedInsp = _load(_INSP_KEY);
    // Default: inspector open only where the drawing keeps ~1300 px.
    _inspOpen = savedInsp === null ? (window.innerWidth || 0) >= 1700 : savedInsp !== '0';
    _applyInspector();
    const saved = _load(_VP_KEY);
    _vp = attachViewport(svg, {
        preset: saved && SLD_PRESETS[saved] && saved !== 'farm' ? saved : DEFAULT_PRESET,
        onChange: ({ preset }) => {
            _renderViewportBar(preset);
            if (preset && preset !== 'farm') { _vpReturn = preset; _store(_VP_KEY, preset); }
        },
    });
    // The canvas follows the window; a named view re-fits to it.
    if (typeof ResizeObserver !== 'undefined') {
        let last = '';
        new ResizeObserver(() => {
            const r = svg.getBoundingClientRect();
            const key = `${Math.round(r.width)}x${Math.round(r.height)}`;
            if (key !== last && r.width > 0) { last = key; _vp && _vp.refit(); }
        }).observe(svg);
    }
    // A node selected while the inspector is hidden opens it.
    subscribe('selectedAsset', (id) => { if (id && !_inspOpen) _setInspector(true); });
}

function _renderViewportBar(preset = _vp && _vp.preset) {
    const bar = document.getElementById('pwr-vp');
    if (bar) bar.innerHTML = viewportToolbarHtml(preset, { inspectorOpen: _inspOpen });
}

function _onViewportClick(ev) {
    const btn = ev.target.closest('button');
    if (!btn || !_vp) return;
    if (btn.dataset.vp) {
        if (btn.dataset.vp !== 'farm' && _farmLod === 1) { _vpReturn = btn.dataset.vp; _setFarmLod(0); }
        _vp.set(btn.dataset.vp);
    } else if (btn.dataset.vpZoom) {
        _vp.zoom(btn.dataset.vpZoom === 'in' ? 1.25 : 0.8);
    } else if (btn.dataset.vpInsp) {
        _setInspector(!_inspOpen);
    } else if (btn.dataset.vpField) {
        _openField(_vp.preset === 'b' ? 'b' : 'a');
    }
}

function _applyInspector() {
    const view = document.getElementById('view-power');
    if (view) view.classList.toggle('insp-closed', !_inspOpen);
}

function _setInspector(open) {
    _inspOpen = !!open;
    _store(_INSP_KEY, _inspOpen ? '1' : '0');
    _applyInspector();
    _renderViewportBar();
}

/** Compact drill coach over the diagram: the operator watches the
 *  plant and the current step without scrolling back to the coach. */
function _renderHud() {
    const hud = document.getElementById('pwr-hud');
    if (!hud) return;
    const s = _trView && _trView.active && _trView.session;
    const unack = _mode === 'live'
        ? ((_liveAlarms && _liveAlarms.alarms) || []).filter((a) => a.state === 'UNACK').length : 0;
    if (!s && !unack) { hud.hidden = true; hud.innerHTML = ''; return; }
    let html = '';
    if (s) {
        const steps = s.steps || [];
        const cur = steps.find((x) => x.current) || null;
        const done = steps.filter((x) => x.done).length;
        const elapsed = Math.max(0, Date.now() - s.started_ms);
        const mm = String(Math.floor(elapsed / 60000)).padStart(2, '0');
        const ss = String(Math.floor(elapsed / 1000) % 60).padStart(2, '0');
        html += `<div class="hud-top"><b>${escapeHTML(s.drill.id)}</b>`
            + `<span class="hud-clock">${mm}:${ss}</span>`
            + `<span>step ${Math.min(done + 1, steps.length)} / ${steps.length}</span>`
            + `<span class="hud-limit">limit ${escapeHTML(String(s.drill.time_limit_s))} s</span></div>`
            + (cur ? `<div class="hud-step">${escapeHTML(cur.text)}</div>` : '');
    }
    if (unack) {
        html += `<div class="hud-al"><span>${unack} unacknowledged alarm${unack === 1 ? '' : 's'}</span>`
            + '<button type="button" class="hud-btn" data-ack-all="1">ACK ALL</button></div>';
    }
    hud.hidden = false;
    hud.innerHTML = html;
}

function _focusDrill() {
    if (!_vp) return;
    _vp.set(presetForPath(_drillPath()));
    const canvas = document.querySelector('#view-power .pid-canvas');
    if (canvas && canvas.scrollIntoView) canvas.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

// ── L1: field view of the 13.8 kV switchgear ─────────────────────
function _fieldGenDev() {
    const id = genId(_fieldPath, _fieldGen);
    return ((_plant && _plant.devices) || []).find((d) => d.id === id) || null;
}

function _fieldXfer() {
    const id = `mvtc_${_fieldPath}`;
    return ((_plant && _plant.devices) || []).find((d) => d.id === id) || null;
}

function _ensureField() {
    let el = document.getElementById('pwr-field');
    if (el) return el;
    el = document.createElement('aside');
    el.id = 'pwr-field';
    el.className = 'pwr-field';
    el.hidden = true;
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-modal', 'true');
    el.setAttribute('aria-label', 'Field view');
    el.innerHTML = '<div class="fsg-shell"><div class="fsg-bar"><span>FIELD VIEW</span>'
        + '<span class="fsg-paths"><button type="button" data-fpath="a">PATH A</button>'
        + '<button type="button" data-fpath="b">PATH B</button></span>'
        + '<span class="fsg-paths"><button type="button" data-fequip="swgr">SWITCHGEAR</button>'
        + '<button type="button" data-fequip="xfmr">TRANSFORMER</button>'
        + '<button type="button" data-fequip="gen">GENERATOR</button>'
        + '<button type="button" data-fequip="ups">UPS</button></span>'
        + '<span class="fsg-note">Layer 2 · equipment view · every operation is checked by the server interlocks and recorded</span>'
        + '<button type="button" class="fsg-close" data-fclose="1" aria-label="Close field view">CLOSE ✕</button></div>'
        + '<div class="fsg-stage" id="pwr-field-stage"></div><div class="fsg-foot" id="pwr-field-foot"></div></div>';
    el.addEventListener('click', _onFieldClick);
    document.addEventListener('keydown', (ev) => {
        if (ev.key === 'Escape' && !el.hidden) _closeField();
    });
    document.body.appendChild(el);
    return el;
}

function _openField(path, equip, gen) {
    const el = _ensureField();
    _fieldPath = String(path || 'a').toLowerCase() === 'b' ? 'b' : 'a';
    if (equip) _fieldEquip = ['xfmr', 'gen', 'ups'].includes(equip) ? equip : 'swgr';
    if (gen) _fieldGen = Math.min(9, Math.max(1, Number(gen) || 1));
    _fieldMsg = '';
    _fieldCovers.clear();
    document.getElementById('pwr-field-stage').innerHTML = _fieldEquip === 'xfmr'
        ? xfmrSvg(_fieldPath) : ({ gen: genSvg, ups: upsSvg }[_fieldEquip] || fieldLineupSvg)(_fieldPath);
    el.setAttribute('aria-label', { xfmr: 'Field view: utility transformer', gen: 'Field view: generator set',
        ups: 'Field view: UPS bank' }[_fieldEquip]
        || 'Field view: 13.8 kV switchgear');
    el.querySelectorAll('[data-fpath]').forEach((b) =>
        b.setAttribute('aria-pressed', String(b.dataset.fpath === _fieldPath)));
    el.querySelectorAll('[data-fequip]').forEach((b) =>
        b.setAttribute('aria-pressed', String(b.dataset.fequip === _fieldEquip)));
    el.hidden = false;
    _applyField();
    if (_fieldTimer) clearInterval(_fieldTimer);
    _fieldTimer = setInterval(() => { if (!_fieldBusy) _pollAlarms(true); }, 1000);
    _pollAlarms(true);
}

function _closeField() {
    const el = document.getElementById('pwr-field');
    if (el) el.hidden = true;
    _fieldPath = null;
    if (_fieldTimer) { clearInterval(_fieldTimer); _fieldTimer = null; }
}

function _applyField() {
    if (!_fieldPath) return;
    const stage = document.getElementById('pwr-field-stage');
    const xfer = _fieldXfer();
    const xf = _fieldEquip === 'xfmr';
    const gen = _fieldEquip === 'gen' ? _fieldGenDev() : null;
    const ups = _fieldEquip === 'ups';
    const ps = ((_plant && _plant.paths) || []).find((p) => p.path === _fieldPath) || null;
    if (stage && xfer) {
        if (ups) {
            applyUpsState(stage, ps, ((_plant && _plant.devices) || [])
                .filter((d) => d.kind === 'ups' && d.path === _fieldPath));
        } else if (gen) {
            applyGenState(stage, gen, ps, _fieldGen);
        } else if (xf) applyXfmrState(stage, xfer.transformer, _fieldPath);
        else applyFieldState(stage, xfer, { covers: _fieldCovers });
    }
    const foot = document.getElementById('pwr-field-foot');
    if (foot) {
        const upsIds = [`ups_system_${_fieldPath}`, `path_${_fieldPath}`];
        const view = ups ? { anyDevice: true, match: (ev) => upsIds.includes(ev.device_id) && isUpsEvent(ev),
            text: upsEventText, empty: 'No operation on this UPS bank yet' }
            : gen ? { match: isGenEvent, text: genEventText, empty: 'No operation at this set yet' }
            : (xf ? { match: isXfmrEvent, text: xfmrEventText, empty: 'No transformer operation yet' } : null);
        foot.innerHTML = xfer ? fieldLogHtml((_plant && _plant.events) || [], _fieldMsg, gen ? gen.id : xfer.id, view)
            : '<div class="fsg-lcd-msg" data-tone="warn">Plant not reachable: sign in or wait for the next poll.</div>';
    }
}

const _wait = (ms) => new Promise((r) => { setTimeout(r, ms); });

async function _onFieldClick(ev) {
    const t = ev.target;
    if (t.closest && t.closest('[data-fclose]')) { _closeField(); return; }
    const pb = t.closest && t.closest('[data-fpath]');
    if (pb) { _openField(pb.dataset.fpath); return; }
    const eb = t.closest && t.closest('[data-fequip]');
    if (eb) { _openField(_fieldPath, eb.dataset.fequip); return; }
    if (_fieldBusy) return;
    if (_fieldEquip === 'xfmr') { await _onXfmrClick(t); return; }
    if (_fieldEquip === 'gen') { await _onGenClick(t); return; }
    if (_fieldEquip === 'ups') { await _onUpsClick(t); return; }
    const xfer = _fieldXfer();
    const r = resolveClick(t, xfer);
    if (!r || !xfer) return;
    if (r.cover) {
        if (_fieldCovers.has(r.cover)) _fieldCovers.delete(r.cover); else _fieldCovers.add(r.cover);
        _audio.latch();
        _applyField();
        return;
    }
    const stage = document.getElementById('pwr-field-stage');
    const url = (p) => `/api/devices/${encodeURIComponent(xfer.id)}/${p}`;
    _fieldBusy = true;
    try {
        if (r.authority) {
            _audio.latch();
            const res = await plantPost(url('authority'), { authority: r.authority });
            _fieldMsg = res.ok ? `CONTROL ${r.authority}` : `KEY SWITCH: ${res.detail}`;
        } else {
            const c = (xfer.cubicles || []).find((x) => x.breaker === r.breaker) || {};
            const permitted = ((c.actions || []).find((a) => a.action === r.action) || {}).permitted;
            const sec = stage && stage.querySelector(`[data-section="${r.breaker}"]`);
            const target = t.closest('[data-act]');
            // Mechanism animation first, as on real equipment: the crank
            // turns, the handle strokes, the button goes down. A blocked
            // mechanism only jolts (the server still decides).
            if (permitted && (r.action === 'RACK_IN' || r.action === 'RACK_OUT')) {
                const crank = sec && sec.querySelector('.fsg-crank');
                const cls = r.action === 'RACK_OUT' ? 'fsg-turning' : 'fsg-turning-back';
                if (crank) crank.classList.add(cls);
                _audio.ratchet(14, 1.0);
                await _wait(1050);
                if (crank) crank.classList.remove(cls);
            } else if (permitted && r.action === 'PUMP_SPRING') {
                const lever = sec && sec.querySelector('.fsg-lever');
                if (lever) lever.classList.add('fsg-pumping');
                _audio.pump();
                await _wait(180);
                if (lever) lever.classList.remove('fsg-pumping');
            } else if (r.kind) {
                const cap = target;
                if (cap) cap.classList.add('fsg-press');
                await _wait(90);
                if (cap) cap.classList.remove('fsg-press');
            }
            const res = await plantPost(url('field'), { breaker: r.breaker, action: r.action });
            if (res.ok) {
                const evd = res.data.event || {};
                _fieldMsg = `${r.action.replace(/_/g, ' ')} ${r.breaker} · ${evd.racking || ''}`;
                if (r.action === 'LOCAL_CLOSE' || r.action === 'LOCAL_OPEN' || r.action === 'TRIP_86') {
                    _audio.breaker(r.action === 'LOCAL_CLOSE');
                } else if (r.action === 'PADLOCK' || r.action === 'UNPADLOCK') _audio.latch();
                if (r.kind) _fieldCovers.delete(`${r.breaker}:${r.kind}`);
            } else {
                _fieldMsg = `INTERLOCK · ${res.detail}`;
                _audio.clunk();
                if (target) {
                    target.classList.add('fsg-shake');
                    setTimeout(() => target.classList.remove('fsg-shake'), 340);
                }
            }
        }
    } finally {
        _fieldBusy = false;
    }
    await _pollAlarms(true);
    if (_trView && _trView.active) _trainingTick();
}

// L4: an operation on the UPS bank (display, Q1 / Q2 / Q3 / Q4 / QF1,
// SKRU and Kirk locks, QF1 padlock).
async function _onUpsClick(t) {
    const ps = ((_plant && _plant.paths) || []).find((p) => p.path === _fieldPath) || null;
    const us = ps && ps.ups_system;
    const r = resolveUpsClick(t, us);
    if (!r) return;
    const target = t.closest('[data-act]');
    const permitted = ((us.actions || []).find((a) => a.action === r.action) || {}).permitted;
    _fieldBusy = true;
    try {
        if (permitted && r.kind === 'key') _audio.latch();
        else if (r.kind === 'button') {
            if (target) target.classList.add('fsg-press');
            await _wait(90);
            if (target) target.classList.remove('fsg-press');
        }
        const res = await plantPost(`/api/ups-systems/${encodeURIComponent(_fieldPath)}/action`, { action: r.action });
        if (res.ok) {
            const evd = res.data.event || {};
            _fieldMsg = `${r.action.replace(/_/g, ' ')} · ${String(evd.mode || '').replace('_', ' ')} · ${evd.load_feed || ''}`;
            if (r.kind === 'breaker') _audio.breaker(r.action.startsWith('CLOSE'));
        } else {
            _fieldMsg = `INTERLOCK · ${res.detail}`;
            _audio.clunk();
            if (target) {
                target.classList.add('fsg-shake');
                setTimeout(() => target.classList.remove('fsg-shake'), 340);
            }
        }
    } finally {
        _fieldBusy = false;
    }
    await _pollAlarms(true);
    if (_trView && _trView.active) _trainingTick();
}

// L3: an operation at a generator set (control panel, e-stop, heater,
// day-tank pumps, fuel filter, basin). The set selector is UI only.
async function _onGenClick(t) {
    const dev = _fieldGenDev();
    const r = resolveGenClick(t, dev);
    if (!r) return;
    if (r.set) {
        _fieldGen = r.set;
        _fieldMsg = '';
        _audio.latch();
        _applyField();
        return;
    }
    if (!dev) return;
    const target = t.closest('[data-act]');
    const permitted = ((dev.fuel.actions || []).find((a) => a.action === r.action) || {}).permitted;
    _fieldBusy = true;
    try {
        if (permitted && (r.kind === 'selector' || r.kind === 'breaker')) _audio.latch();
        else if (permitted && r.kind === 'estop') _audio.breaker(false);
        const res = await plantPost(`/api/devices/${encodeURIComponent(dev.id)}/fuel`, { action: r.action });
        if (res.ok) {
            const evd = res.data.event || {};
            _fieldMsg = `${r.action.replace(/_/g, ' ')} · ${String(evd.to_state || '').replace(/_/g, ' ')} · DAY TANK ${evd.day_tank_pct} %`;
            if (r.action === 'ECS_RUN') _audio.engineStart();
        } else {
            _fieldMsg = `INTERLOCK · ${res.detail}`;
            _audio.clunk();
            if (target) {
                target.classList.add('fsg-shake');
                setTimeout(() => target.classList.remove('fsg-shake'), 340);
            }
        }
    } finally {
        _fieldBusy = false;
    }
    await _pollAlarms(true);
    if (_trView && _trView.active) _trainingTick();
}

// L2: an operation at the utility transformer (keys, DETC, 52-T, relays).
async function _onXfmrClick(t) {
    const xfer = _fieldXfer();
    const tr = xfer && xfer.transformer;
    const r = resolveXfmrClick(t, tr);
    if (!r || !tr) return;
    const stage = document.getElementById('pwr-field-stage');
    const target = t.closest('[data-act]');
    const permitted = ((tr.actions || []).find((a) => a.action === r.action) || {}).permitted;
    _fieldBusy = true;
    try {
        if (permitted && r.kind === 'key') _audio.latch();
        else if (permitted && r.kind === 'detc') _audio.ratchet(6, 0.6);
        else if (r.kind === 'button' || r.kind === 'breaker') {
            const cap = target;
            if (cap) cap.classList.add('fsg-press');
            await _wait(90);
            if (cap) cap.classList.remove('fsg-press');
        }
        const res = await plantPost(`/api/devices/${encodeURIComponent(xfer.id)}/xfmr`, { action: r.action });
        if (res.ok) {
            const evd = res.data.event || {};
            _fieldMsg = `${r.action.replace(/_/g, ' ')} · POS ${evd.tap} · ${evd.energized ? 'ENERGIZED' : 'DE-ENERGIZED'}`;
            if (evd.outcome === 'internal_fault') {
                _fieldMsg = 'INTERNAL FAULT · 63 + 87T operated · 86T tripped 52-T and 52-U';
                _audio.arc();
                if (stage) {
                    stage.classList.remove('xf-arc');
                    void stage.offsetWidth;
                    stage.classList.add('xf-arc');
                    setTimeout(() => stage.classList.remove('xf-arc'), 950);
                }
            } else if (r.kind === 'breaker') _audio.breaker(r.action === 'CLOSE_52T');
            else if (r.kind === 'selector' || r.kind === 'button') _audio.latch();
        } else {
            _fieldMsg = `INTERLOCK · ${res.detail}`;
            _audio.clunk();
            if (target) {
                target.classList.add('fsg-shake');
                setTimeout(() => target.classList.remove('fsg-shake'), 340);
            }
        }
    } finally {
        _fieldBusy = false;
    }
    await _pollAlarms(true);
    if (_trView && _trView.active) _trainingTick();
}

function _drillPath() {
    const s = _trView && _trView.session;
    return s ? s.drill.path : 'a';
}

function _renderTraining() {
    const el = document.getElementById('pwr-training');
    if (!el) return;
    if (!_trSelected && _drills.length) _trSelected = _drills[0].id;
    const ps = ((_plant && _plant.paths) || []).find((p) => p.path === _drillPath()) || null;
    el.dataset.active = _trView && _trView.active ? '1' : '0';
    el.innerHTML = trainingHtml({
        drills: _drills, view: _trView, pathSummary: ps, selected: _trSelected,
        message: _trMsg, soundOn: _audio.on, soundSupported: _audio.supported,
    });
    _renderHud();
}

async function _loadTraining() {
    const d = await plantGet('/api/training/drills');
    if (d.ok) _drills = d.data.drills || [];
    await _trainingTick();
}

async function _trainingTick() {
    if (_trTimer) { clearTimeout(_trTimer); _trTimer = null; }
    const r = await plantGet('/api/training/session');
    if (r.ok) {
        const before = _prevSteps;
        _trView = r.data;
        const done = _trView.session ? _trView.session.steps.filter((x) => x.done).length : 0;
        if (done > before) _audio.chime();
        _prevSteps = done;
    }
    if (_trView && _trView.active) {
        await _pollAlarms(true);
        _trTimer = setTimeout(_trainingTick, 1000);
    }
    _renderTraining();
}

async function _onTrainingClick(ev) {
    const btn = ev.target.closest('button');
    if (!btn) return;
    if (btn.dataset.trSound) {
        _audio.setOn(!_audio.on);
        if (_audio.on) _audio.chime();
        _renderTraining();
        return;
    }
    if (btn.dataset.trPrint) {
        // Open the window inside the click (popup blockers allow that),
        // then fill it once the report arrives.
        const w = window.open('', '_blank');
        const r = await plantGet('/api/training/report');
        if (!r.ok) { if (w) w.close(); _trMsg = r.detail; _renderTraining(); return; }
        if (!openPrintable(r.data, { open: () => w })) {
            _trMsg = 'The browser blocked the report window: allow pop-ups for this site, or download the JSON.';
            _renderTraining();
        }
        return;
    }
    if (btn.dataset.trReport) {
        const r = await plantGet('/api/training/report');
        if (!r.ok) { _trMsg = r.detail; _renderTraining(); return; }
        _download(`${r.data.drill?.id || 'drill'}_report.json`, JSON.stringify(r.data, null, 2));
        return;
    }
    let r = null;
    if (btn.dataset.trStart) {
        if (_mode !== 'live') _setMode('live');
        r = await plantPost('/api/training/start', { drill_id: _trSelected });
        _prevSteps = 0;
    } else if (btn.dataset.trAbort) {
        r = await plantPost('/api/training/abort');
    } else if (btn.dataset.trReset) {
        r = await plantPost('/api/training/reset');
    }
    if (!r) return;
    _trMsg = r.ok ? '' : (r.status === 401 || r.status === 403
        ? 'Refused: drills reset the shared plant and need a FACILITY_MANAGER session.' : r.detail);
    await _trainingTick();
    if (r.ok && btn.dataset.trStart) _focusDrill();
    await _pollAlarms(true);
}

function _download(name, text) {
    try {
        const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
        const a = document.createElement('a');
        a.href = url;
        a.download = name;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (_e) { _trMsg = 'Download not available in this browser.'; _renderTraining(); }
}

// ── T2: select-before-operate faceplate ──────────────────────────
function _openFaceplate(target) {
    _fpTarget = target;
    _fpMsg = '';
    _renderFaceplate();
    if (!_plant) _pollAlarms(true);
}

function _renderFaceplate() {
    const el = document.getElementById('pwr-faceplate');
    if (!el) return;
    if (!_fpTarget || _mode !== 'live') { el.hidden = true; return; }
    el.hidden = false;
    el.innerHTML = faceplateHtml(_fpTarget, _plant, { pending: _fpPending, message: _fpMsg });
    _syncAnimate();
    if (_fpPending.size && !_fpTimer) {
        _fpTimer = setTimeout(() => {
            _fpTimer = null;
            const now = Date.now();
            for (const [id, p] of _fpPending) if (p.expiresAt <= now) _fpPending.delete(id);
            _renderFaceplate();
        }, 1000);
    }
}

// T3: turn the synchroscope needles between polls (display only).
function _syncFrame(nowMs = Date.now()) {
    const devs = (_plant && _plant.devices) || [];
    let live = false;
    document.querySelectorAll('#pwr-faceplate [data-sync-needle]').forEach((el) => {
        const id = el.dataset.syncNeedle;
        const sync = (devs.find((d) => d.id === id) || {}).synchro;
        if (!sync) return;
        live = live || !!sync.live;
        const a = needleAngle(sync, _plantAtMs, nowMs);
        el.setAttribute('transform', `rotate(${a.toFixed(1)} 60 60)`);
        const t = document.querySelector(`#pwr-faceplate [data-sync-angle="${id}"]`);
        if (t) t.textContent = `${a >= 0 ? '+' : ''}${a.toFixed(1)}°`;
        const eta = document.querySelector(`#pwr-faceplate [data-sync-eta="${id}"]`);
        if (eta) eta.textContent = etaText(etaNow(sync, _plantAtMs, nowMs));
        const lamp = document.querySelector(`#pwr-faceplate [data-sync-lamp="${id}"]`);
        if (lamp) {
            const ok = permissive(sync, a);
            lamp.dataset.ok = ok ? '1' : '0';
            lamp.textContent = `25 ${ok ? 'PERMIT' : 'BLOCK'}`;
        }
    });
    return live;
}

function _syncAnimate() {
    if (_syncRaf || typeof requestAnimationFrame !== 'function') return;
    const step = () => {
        _syncRaf = null;
        const el = document.getElementById('pwr-faceplate');
        if (!el || el.hidden) return;
        if (_syncFrame()) _syncRaf = requestAnimationFrame(step);
    };
    _syncRaf = requestAnimationFrame(step);
}

async function _onFaceplateClick(ev) {
    const btn = ev.target.closest('button');
    if (!btn) return;
    if (btn.dataset.fpClose) { _fpTarget = null; _fpPending.clear(); _renderFaceplate(); return; }
    if (btn.dataset.fpField) {
        _openField(btn.dataset.fpField, btn.dataset.fpEquip || 'swgr', btn.dataset.fpGen);
        return;
    }
    const url = (id, verb) => `/api/devices/${encodeURIComponent(id)}/${verb}`;
    let r = null;
    if (btn.dataset.fpAuth) {
        r = await plantPost(url(btn.dataset.fpAuth, 'authority'), { authority: 'REMOTE' });
    } else if (btn.dataset.fpSelect) {
        const id = btn.dataset.fpSelect;
        r = await plantPost(url(id, 'select'), { command: btn.dataset.fpCmd });
        if (r.ok) {
            _fpPending.set(id, {
                token: r.data.select_token, label: r.data.label || btn.dataset.fpCmd,
                command: btn.dataset.fpCmd,
                expiresAt: Date.now() + 1000 * (Number(r.data.expires_in_s) || 30),
            });
        }
    } else if (btn.dataset.fpExec) {
        const id = btn.dataset.fpExec;
        const p = _fpPending.get(id);
        _fpPending.delete(id);
        if (!p) return;
        r = await plantPost(url(id, 'operate'), { select_token: p.token });
        if (r.ok && p.command === 'START_GENERATORS') _audio.engineStart();
    } else if (btn.dataset.fpSynccancel) {
        r = await plantPost(url(btn.dataset.fpSynccancel, 'sync-cancel'));
    } else if (btn.dataset.fpGov) {
        r = await plantPost(url(btn.dataset.fpGov, 'governor'), { delta_hz: Number(btn.dataset.delta) });
    } else if (btn.dataset.fpCancel) {
        _fpPending.delete(btn.dataset.fpCancel);
        _renderFaceplate();
        return;
    }
    if (!r) return;
    _fpMsg = r.ok ? '' : (r.status === 401 || r.status === 403
        ? 'Refused: commands need a FACILITY_MANAGER session.' : r.detail);
    await _pollAlarms(true);
    _renderFaceplate();
}

async function _ackLive(path) {
    try {
        await apiFetch(path, {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' }, body: '{}',
        });
        _ackErr = '';
    } catch (e) {
        _ackErr = /HTTP 40[13]/.test(String(e.message))
            ? 'ACK refused: sign in with an operator account.'
            : 'ACK failed: ' + String(e.message || e).slice(0, 120);
    }
    await _pollAlarms(true);
}

function _onAlarmClick(ev) {
    const btn = ev.target.closest('button');
    if (!btn) return;
    const id = btn.dataset.ack;
    const all = btn.dataset.ackAll;
    if (_mode === 'whatif') {
        if (all) _sandboxAlarms.ackAll(); else if (id) _sandboxAlarms.ack(id);
        _renderAlarms();
        return;
    }
    if (all) _ackLive('/api/alarms/ack-all');
    else if (id) _ackLive(`/api/alarms/${encodeURIComponent(id)}/ack`);
}

// Flow layer: which runs are energized / carrying power, from which
// source, how fast the dashes move (scales with MW), breaker states
// and the drawn power numbers (core/power_flow.js).
const _SEG_NODE = {
    util: 'util', xfmr: 'xfmr', u52: 'xfmr', gen: 'genset', bus: 'genset',
    gm: 'genset', mv: 'mvtc', mvtc: 'mvtc', swgr: 'mv_swgr', usub: 'usub', ups: 'ups',
};

function _applyFlow(gridIn) {
    // No DAG snapshot yet (engine not initialised): draw the nominal plant.
    const grid = gridIn || {};
    const flows = pathFlows(grid, _itKw ?? undefined);
    for (const p of ['a', 'b']) {
        const f = flows[p];
        const tc = grid['mvtc_' + p] || {};
        const u52Closed = !tc.tripped && !tc.transferring
            && tc.ats_pos !== 'secondary' && tc.ats_pos !== 'open';
        const gmClosed = !tc.tripped && !tc.transferring && tc.ats_pos === 'secondary';
        const src = f.source;   // 'util' | 'genset' | 'battery' | null
        const carrying = {
            util: src === 'util', xfmr: src === 'util', u52: src === 'util' && u52Closed,
            gen: src === 'genset', bus: src === 'genset', gm: src === 'genset' && gmClosed,
            mv: src === 'util' || src === 'genset', mvtc: src === 'util' || src === 'genset',
            swgr: src === 'util' || src === 'genset', usub: src === 'util' || src === 'genset',
            ups: f.upsOutKw > 0, batt: src === 'battery',
        };
        document.querySelectorAll(`#view-power [data-seg^="${p}:"]`).forEach((el) => {
            const name = el.dataset.seg.split(':')[1];
            const node = grid[`${_SEG_NODE[name] ?? name}_${p}`];
            let energized = name === 'batt' ? src === 'battery' : (node ? !!node.alive : true);
            if (name === 'u52') energized = energized && u52Closed;
            if (name === 'gm') energized = energized && gmClosed;
            el.classList.toggle('pf-dead', !energized);
            el.classList.toggle('pf-flow', !!carrying[name] && energized);
            el.setAttribute('data-src', carrying[name] && energized ? (src || '') : '');
            const ar = document.querySelector(`#view-power [data-arrow="${p}:${name}"]`);
            if (ar) ar.classList.toggle('pf-arrow-on', !!carrying[name] && energized);
        });
        // Trip lands on the breaker that was carrying the bus (52-GM when
        // the controller sat on the generator side, else 52-U).
        const tripId = tc.tripped ? (tc.ats_pos === 'secondary' ? 'gm' : 'u') : null;
        const setBrk = (id, closed) => {
            const b = document.querySelector(`#view-power [data-brk="${p}:${id}"]`);
            if (!b) return;
            const state = tripId === id ? 'trip'
                : (tc.transferring ? 'transfer' : (closed ? 'closed' : 'open'));
            b.setAttribute('data-state', state);
            const st = b.querySelector('.pf-52-state');
            if (st) st.textContent = breakerText(state);
            const blade = b.querySelector('.pf-52-blade');
            if (blade) {
                const r = b.querySelector('.pf-52-box');
                const x = Number(r.getAttribute('x')) + 11, y = Number(r.getAttribute('y')) + 11;
                blade.setAttribute('d', closed
                    ? `M${x - 7} ${y + 7} L${x + 7} ${y - 7}`     // closed: blade across
                    : `M${x - 7} ${y + 7} L${x + 1} ${y - 9}`);   // open: blade lifted
            }
        };
        setBrk('u', u52Closed);
        setBrk('gm', gmClosed);
        const txt = (key, v) => {
            const el = document.querySelector(`#view-power [data-flow="${p}:${key}"]`);
            if (el) el.textContent = v;
        };
        txt('mv', src === 'util' || src === 'genset' ? fmtPower(f.upsInKw) : '');
        const tl = (key, v) => {
            const el = document.querySelector(`#view-power [data-tag-line="${p}:${key}"]`);
            if (el) el.textContent = v;
        };
        const mvP = src === 'util' || src === 'genset' ? f.upsInKw : 0;
        tl('pq', `P ${fmtPower(mvP)} · Q ${fmtReactive(mvP)}`);
        tl('spf', mvP > 0 ? `S ${fmtApparent(f.mvKva)} · PF ${PF.toFixed(2)}` : 'S 0 kVA · bus dead');
        txt('ups', f.upsOutKw > 0 ? fmtPower(f.upsOutKw) : '');
        txt('gen', f.genKw > 0 ? `${fmtPower(f.genKw)} · ${f.genLoadPct.toFixed(0)} %` : '');
        _setMetric(`util_${p}-kw`, src === 'util' ? fmtPower(f.upsInKw) : '0 kW');
        _setMetric(`xfmr_${p}-load`, src === 'util' ? `${fmtApparent(f.xfmrKva)} of 25` : '0 MVA');
        _setMetric(`ups_${p}-load`, f.upsOutKw > 0
            ? `${fmtPower(f.upsOutKw)} · ${f.upsLoadPct.toFixed(0)} % of bank` : '0 MW');
        _setMetric(`rpp_${p}1-kw`, fmtPower(f.rppKw) + ' ×2');
        if (_mode !== 'live') {
            const u = grid['ups_' + p] || {};
            _setMetric(`ups_${p}-mode`, u.mode === 'battery' ? 'BATTERY'
                : (u.mode === 'off' ? 'OFF' : 'ONLINE · η 97 %'));
        }
        const gs = grid['genset_' + p] || {};
        _setMetric(`genset_${p}-state`, (gs.state || 'standby').toUpperCase().replace('_', ' ')
            + (f.genKw > 0 ? ' · ON LOAD' : ''));
    }
}

/** Unit-bank ticks + capacity caption (DC-EPMS-068). */
function _applyUnits(grid) {
    document.querySelectorAll('#view-power .pid-svg .pf-unit-strip').forEach((strip) => {
        const id = strip.dataset.unitsFor;
        const n = grid[id];
        const t = getTopology()[id];
        if (!n || !t) return;
        const out = n.units_out || 0;
        strip.querySelectorAll('.pf-unit').forEach((tick) => {
            const i = Number(tick.dataset.unit);
            // count-based: the first `out` ticks read as out of service
            tick.setAttribute('data-out', i < out ? '1' : '0');
        });
        const cap = strip.querySelector('.pf-unit-cap');
        if (cap && n.capacity_kw != null) {
            const tag = n.n1_ok ? 'N+1' : (n.n_ok ? 'N only' : 'BELOW N');
            cap.textContent = `${(n.capacity_kw / 1000).toFixed(2)} MW · ${tag}`;
            cap.setAttribute('data-level', n.n1_ok ? 'ok' : (n.n_ok ? 'warn' : 'crit'));
        }
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
    _ensureVida2Panels();
    _pollAlarms(true);
    _loadTraining();
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
    _buildViewport(flatSvg);
    // L3 Phase 2: LIVE <-> WHAT-IF toggle + flat-SLD render of the local
    // DAG fault-cascade (the sandbox's simulated faults become visible).
    _buildModeToggle();
    _buildN1Toggle();
    _buildReplayToggle();
    // R2: arm the session black box (records Hermes + DAG planes).
    startRecording();
    subscribe('grid', (g) => _applyGrid(_effGrid(g)));
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
    openField: _openField,
    closeField: _closeField,
    onFieldClick: _onFieldClick,
    setPlant: (p) => { _plant = p; },
    buildViewport: _buildViewport,
    getViewport: () => _vp,
    renderHud: _renderHud,
    setTrainingView: (v) => { _trView = v; },
    setLiveAlarms: (v) => { _liveAlarms = v; },
    isInspectorOpen: () => _inspOpen,
    getFarmLod: () => _farmLod,
    farmFocusViewBox: _FARM_FOCUS_VIEWBOX,
    scrubTo: _scrubTo,
    buildReplayToggle: _buildReplayToggle,
    loadLedgerMarkers: _loadLedgerMarkers,
    applyGrid: _applyGrid,
    applyFlow: _applyFlow,
    eventLog: _eventLog,
    sandboxAlarms: _sandboxAlarms,
    effGrid: _effGrid,
    hasPlant: () => !!_plant,
    pollAlarms: _pollAlarms,
    renderAlarms: _renderAlarms,
    loadTraining: _loadTraining,
    trainingTick: _trainingTick,
    onTrainingClick: _onTrainingClick,
    openFaceplate: _openFaceplate,
    onFaceplateClick: _onFaceplateClick,
    faceplatePending: _fpPending,
    syncFrame: _syncFrame,
    audio: _audio,
    stopTraining: () => { if (_trTimer) clearTimeout(_trTimer); _trTimer = null; _trView = null; },
    onAlarmClick: _onAlarmClick,
    setItKw: (v) => { _itKw = v; },
    sparkPoints,
    updateSparklines: _updateSparklines,
    channelMatcher: _channelMatcher,
    reset: () => {
        _initialized = false;
        _mode = 'live';
        _farmLod = 0;
        _vp = null;
        _vpReturn = DEFAULT_PRESET;
        _inspOpen = true;
        if (_unsubTelemetry) { _unsubTelemetry(); _unsubTelemetry = null; }
        const modal = document.getElementById('pwr-breaker-modal');
        if (modal) modal.remove();
        const replayBar = document.getElementById('pwr-replay-bar');
        if (replayBar) replayBar.remove();
        _n1Overlay.detach();
        _sparkTracker.reset();
    },
};
