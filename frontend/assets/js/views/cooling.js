/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/cooling.js
 * Diagram Rebuild Batch 2 — Cooling (DLC) P&ID on the shared
 * diagram kit + canonical node registry + cooling availability DAG.
 *
 * What changed vs the T2.1 generation:
 *   - Symbols, orthogonal pipes, sparklines and the pump actuation
 *     modal come from core/diagram_kit.js (private copies retired).
 *   - Kalman channel ownership comes from the registry (prefix
 *     discipline via matchesChannel, not substring includes).
 *   - The What-If sandbox is now REAL: clicks trip nodes in
 *     core/cooling_grid.js — the hydraulic sibling of the power DAG
 *     — and the availability cascade renders back onto the P&ID
 *     (trip one chiller: its N+1 peer goes degraded/warning; trip
 *     both: every CDU + the hall lose cooling). One What-If
 *     semantic across the SLD views. Honest scope: availability
 *     only — thermodynamic validation stays with the backend
 *     physics engine via the Topology view.
 *
 * Data plane unchanged: /api/topology/state once per activation +
 * live trend from the Hermes telemetry stream.
 * ════════════════════════════════════════════════════════════════ */

import { registerRoute } from '../core/router.js';
import { getTopologyState, writeBmsTag, onHermesStream } from '../services/api.js';
import { subscribe } from '../core/state.js';
import { escapeHTML } from '../core/sanitize.js';
import {
    symbol, wire, sparkPolyline, createSparkTracker,
    createActuationModal, legend, DEFAULT_LEGEND,
} from '../core/diagram_kit.js';
import { channelPrefixesFor, matchesChannel } from '../core/node_registry.js';
import {
    initCoolingGrid, toggleTrip, restoreAll, getGridState,
} from '../core/cooling_grid.js';
import { n1Cooling } from '../core/contingency.js';
import { createN1Overlay } from '../core/n1_overlay.js';

let _initialized = false;
let _mode = 'live';            // 'live' | 'whatif'
let _unsubTelemetry = null;
const _ACTUATOR_TYPES = new Set(['pump']);
const _SPARK_NODES = new Set(['cooling_tower', 'chiller_1', 'chiller_2']);
const _SYM_CLS = 'pid-symbol cool-sym';   // Cooling P&ID CSS hook order

// ─── Channel ownership (registry prefix discipline) ────────────────
function _channelMatcher(nodeId, channelId) {
    const prefixes = channelPrefixesFor(nodeId);
    return matchesChannel(channelId, prefixes.length ? prefixes : [nodeId]);
}

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
        const symbolEl = el && el.querySelector('.pid-symbol');
        if (symbolEl) symbolEl.setAttribute('data-sev', nodeData.severity || 'ok');
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
//  Orthogonal thermodynamic P&ID — generated via the shared kit.
//  5 fixed tier columns (Heat Rejection -> Chillers -> Pumps ->
//  CDU -> Load), strict grid alignment; every pipe a kit-enforced
//  90° run. Chilled-water SUPPLY glows blue, warm RETURN glows
//  warm. Nodes keep the data-node / .pid-symbol / data-pid-metric
//  hooks so the (unchanged) _applyCoolingPid binder drives severity
//  + metrics.
// ════════════════════════════════════════════════════════════════
const _COOL = { supplyY: 196, returnY: 432, viewBox: '0 0 1040 740' };

function _coolNode(id, type, label, x, y, metrics) {
    const m = metrics.map((mm, i) =>
        `<text class="cool-metric" data-pid-metric="${mm.key}" x="${x}" `
        + `y="${y + 42 + i * 13}">${escapeHTML(mm.text)}</text>`).join('');
    const isAct = _ACTUATOR_TYPES.has(type);
    const actAttr = isAct ? ' data-actuator="1" tabindex="0" role="button"' : '';
    let spark = '';
    if (_SPARK_NODES.has(id)) {
        const sy = y + 42 + metrics.length * 13 + 11;
        spark = sparkPolyline(id, x - 26, sy);
    }
    return `<g class="pid-node cool-node${isAct ? ' cool-actuator' : ''}" `
        + `data-node="${id}"${actAttr}>`
        + symbol(type, x, y, { cls: _SYM_CLS })
        + `<text class="cool-name" x="${x}" y="${y - 38}">${escapeHTML(label)}</text>`
        + m + spark + `</g>`;
}

// Orthogonal pipe — kit wire with the P&ID base class.
function _coolPipe(points, kind) {
    return wire(points, 'cool-' + kind, 'cool-pipe');
}

/** Build the full thermodynamic P&ID inner markup. */
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

    // ── orthogonal piping (kit-enforced 90°) ──
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

    // DLC honesty caption: Phase 1 plant today; Phase 2 retrofit is
    // design scope (the Power SLD carries the full 800 VDC branch).
    const caption = `<text class="pf-caption" x="${T.load}" y="300">`
        + `DLC cold plates · GB200 (Ph1) / GB300 retrofit (Ph2 design)</text>`;

    return rails + pipes + nodes + caption + legend(DEFAULT_LEGEND, 24, 624);
}

/** Render the orthogonal cooling P&ID into the legacy .pid-svg. */
function _renderCoolingSld() {
    const svg = document.querySelector('#view-cooling .pid-svg');
    if (!svg) return;
    svg.setAttribute('viewBox', _COOL.viewBox);
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    svg.classList.add('cool-svg');
    svg.innerHTML = _buildCoolingSld();
}

// ════════════════════════════════════════════════════════════════
//  L3 control plane (actuation · What-If DAG · sparklines)
// ════════════════════════════════════════════════════════════════
function _bmsTagFor(nodeId) {
    // chwp_1 -> HVAC.CHWP1.STATUS  (ISA-95 registry tag, writable BO).
    return 'HVAC.' + nodeId.replace('chwp_', 'CHWP').toUpperCase() + '.STATUS';
}

const _pumpModal = createActuationModal({
    modalId: 'cool-pump-modal',
    titleId: 'cool-modal-title',
    roleSelectId: 'cool-modal-role',
    icon: '&#10052;',
    title: 'CHW Pump Control',
    targetLabel: 'Target pump:',
    commands: [
        { cmd: 'START', label: 'START PUMP' },
        { cmd: 'STOP', label: 'STOP PUMP' },
    ],
    onSubmit: (nodeId, cmd, actorRole) => _submitPumpCommand(nodeId, cmd, actorRole),
});

function _openPumpModal(nodeId, label) { _pumpModal.open(nodeId, label); }

async function _submitPumpCommand(nodeId, cmd, actorRole) {
    if (!document.getElementById('cool-pump-modal') || !cmd) return;
    _pumpModal.showPending();
    const outcome = await writeBmsTag({
        tag_id: _bmsTagFor(nodeId),
        value: cmd === 'START' ? 'On' : 'Off',
        user: 'cooling-sld-operator',
        actor_role: actorRole,
    });
    _pumpModal.showResult(outcome, cmd, nodeId);
}

/**
 * Render the cooling availability DAG state onto the P&ID.
 * tripped / dead -> critical; surviving peer of a dead redundant
 * pair -> warning (redundancy consumed); else ok.
 */
function _applyGrid(grid) {
    if (!grid) return;
    document.querySelectorAll('#view-cooling .pid-svg .cool-node').forEach((node) => {
        const n = grid[node.dataset.node];
        if (!n) return;
        let sev = 'ok';
        if (n.tripped || n.alive === false) sev = 'critical';
        else if (n.degraded) sev = 'warning';
        node.querySelectorAll('.pid-symbol').forEach((s) => s.setAttribute('data-sev', sev));
        node.classList.toggle('cool-tripped', !!n.tripped);
    });
}

/** SVG click delegation — routes a node click by current mode. */
function _onCoolClick(e) {
    const node = e.target.closest('.cool-node');
    if (!node) return;
    const id = node.dataset.node;
    if (_mode === 'whatif') {
        // Sandbox: trip/restore the node in the LOCAL availability DAG
        // and render the cascade — zero bytes to the backend.
        if (!getGridState()) initCoolingGrid();
        toggleTrip(id);
        _applyGrid(getGridState());
        return;
    }
    if (node.dataset.actuator) {
        const label = node.querySelector('.cool-name');
        _openPumpModal(id, label ? label.textContent : id);
    }
}

// ── N-1 Shadow (shared overlay; see views/power.js rationale) ──
const _n1Overlay = createN1Overlay({
    rootSelector: '#view-cooling .pid-svg',
    nodeSelector: '.cool-node',
    idAttr: 'node',
    nameSelector: '.cool-name',
    analysisFn: n1Cooling,
});

function _setN1(on) {
    if (on && _mode === 'whatif') return;
    if (on) _n1Overlay.attach(); else _n1Overlay.detach();
    const btn = document.getElementById('cool-n1-toggle');
    if (btn) {
        btn.dataset.on = on ? '1' : '0';
        btn.classList.toggle('is-on', on);
    }
}

function _buildN1Toggle() {
    if (document.getElementById('cool-n1-toggle')) return;
    const view = document.getElementById('view-cooling');
    if (!view) return;
    const btn = document.createElement('button');
    btn.id = 'cool-n1-toggle';
    btn.type = 'button';
    btn.className = 'pwr-mode-toggle pwr-n1-toggle';
    btn.dataset.on = '0';
    btn.textContent = '◬ N-1 SHADOW';
    btn.title = 'Sustained single-failure contingency painted on the P&ID '
        + '(availability semantics; not thermodynamics)';
    btn.addEventListener('click', () => _setN1(btn.dataset.on !== '1'));
    const bar = view.querySelector('.pid-action-bar') || view;
    const modeBtn = document.getElementById('cool-mode-toggle');
    bar.insertBefore(btn, modeBtn ? modeBtn.nextSibling : bar.firstChild);
}

// ── What-If sandbox toggle ──
function _setMode(mode) {
    _mode = (mode === 'whatif') ? 'whatif' : 'live';
    if (_mode === 'whatif') _setN1(false);   // shadow assumes intact topology
    const view = document.getElementById('view-cooling');
    if (view) view.classList.toggle('cool-whatif', _mode === 'whatif');
    const btn = document.getElementById('cool-mode-toggle');
    if (btn) {
        btn.textContent = _mode === 'whatif'
            ? '⚠ WHAT-IF SIMULATION' : '◉ LIVE TELEMETRY';
        btn.dataset.mode = _mode;
    }
    if (_mode === 'live') {
        // Leaving the sandbox — clear simulated trips, re-sync to live.
        if (getGridState()) {
            restoreAll();
            _applyGrid(getGridState());
        }
        _refresh();
    }
}

function _buildModeToggle() {
    if (document.getElementById('cool-mode-toggle')) return;
    const view = document.getElementById('view-cooling');
    if (!view) return;
    const btn = document.createElement('button');
    btn.id = 'cool-mode-toggle';
    btn.type = 'button';
    btn.className = 'pwr-mode-toggle';
    btn.dataset.mode = 'live';
    btn.textContent = '◉ LIVE TELEMETRY';
    btn.title = 'Toggle LIVE telemetry <-> isolated WHAT-IF simulation sandbox';
    btn.addEventListener('click', () => _setMode(_mode === 'live' ? 'whatif' : 'live'));
    const bar = view.querySelector('.pid-action-bar') || view;
    bar.insertBefore(btn, bar.firstChild);
}

// ── Telemetry sparklines (shared kit tracker) ──
const _sparkTracker = createSparkTracker({
    rootSelector: '#view-cooling .pid-svg',
    nodes: _SPARK_NODES,
    ticks: 20,
});
function _updateSparklines(channels) {
    _sparkTracker.update(channels, _channelMatcher);
}

function _onTelemetryFrame(payload) {
    if (_mode === 'whatif') return;   // sandbox — feed disconnected
    if (payload && payload.channels) _updateSparklines(payload.channels);
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
    // Baseline topology once per activation — live trend arrives on
    // the Hermes telemetry stream.
    _refresh();
}

/** Public entry — called once from main.js at bootstrap. */
export function initCoolingView() {
    if (_initialized) return;
    if (!document.getElementById('view-cooling')) {
        console.warn('[cooling] #view-cooling not in DOM; view disabled.');
        return;
    }
    registerRoute('cooling', { viewId: 'view-cooling', activate: _activate });
    // Batch 2: render the kit-driven orthogonal P&ID into .pid-svg.
    _renderCoolingSld();
    // L3: clickable actuators + What-If availability DAG + sparklines.
    const svg = document.querySelector('#view-cooling .pid-svg');
    if (svg) svg.addEventListener('click', _onCoolClick);
    _buildModeToggle();
    _buildN1Toggle();
    initCoolingGrid();
    subscribe('coolgrid', _applyGrid);
    _unsubTelemetry = onHermesStream('telemetry', _onTelemetryFrame);
    _initialized = true;
    console.log('[cooling] view ready (diagram-kit P&ID + availability DAG)');
}

// ─── Test surface ──────────────────────────────────────────────────
export const __cooling_test__ = {
    applyCoolingPid: _applyCoolingPid,
    buildCoolingSld: _buildCoolingSld,
    coolViewBox: _COOL.viewBox,
    renderCoolingSld: _renderCoolingSld,
    bmsTagFor: _bmsTagFor,
    openPumpModal: _openPumpModal,
    submitPumpCommand: _submitPumpCommand,
    onCoolClick: _onCoolClick,
    applyGrid: _applyGrid,
    setMode: _setMode,
    getMode: () => _mode,
    buildModeToggle: _buildModeToggle,
    buildN1Toggle: _buildN1Toggle,
    setN1: _setN1,
    n1Overlay: _n1Overlay,
    updateSparklines: _updateSparklines,
    channelMatcher: _channelMatcher,
    reset: () => {
        _initialized = false;
        _mode = 'live';
        if (_unsubTelemetry) { _unsubTelemetry(); _unsubTelemetry = null; }
        const modal = document.getElementById('cool-pump-modal');
        if (modal) modal.remove();
        _n1Overlay.detach();
        if (getGridState()) restoreAll();
        _sparkTracker.reset();
    },
};
