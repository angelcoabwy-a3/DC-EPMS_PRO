/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — core/power_sld.js
 *
 * Power & UPS SLD enhancer — Lead Engineer Mode upgrade.
 *
 * Four directives implemented:
 *
 *   1. UNIFIED PALETTE
 *      Cyan = Path A energized · Violet = Path B energized
 *      Amber = battery / genset hot · Red/Gray = fault / cold
 *      Old "live/battery/standby" classes co-exist for backward
 *      compat; the enhancer applies sld-line-path-a / -b / -batt /
 *      -fault classes that override the legacy palette.
 *
 *   2. ANIMATED FLOW (CSS stroke-dashoffset)
 *      Lines flowing get .sld-line-flowing which animates the
 *      stroke-dashoffset infinitely. When state flips to fault/cold
 *      the class is removed and the line goes dark grey statically.
 *
 *   3. CLICK-TO-DRILL
 *      Each [data-sld-node] becomes a click target. On click,
 *      sessionStorage gets cmms_focus_asset_id=<id> and we navigate
 *      programmatically to the appropriate detail view based on
 *      asset type:
 *        ups, ats, rpp, batt   -> #maintenance (asset filter)
 *        xfmr, switchgear      -> #site_topology (graph centred)
 *        util, genset          -> #tech-assist (troubleshoot)
 *
 *   4. SIMULATE UTILITY LOSS (Path A)
 *      Click the action-bar button -> a 3-step animated sequence
 *      runs over ~10s using state.js as the source of truth:
 *        t=0     util_a + xfmr_a -> COLD (gray)
 *                ats_a transferring (amber pulse)
 *                ups_a -> ON BATTERY (amber)
 *                batt_a SOC ticks down 1 %/s from 100 %
 *        t=4s    genset_a spins up (amber pulse, sld-line-batt)
 *        t=8s    ats_a connects to genset (amber line genset_a-ats_a
 *                animated; ats_a-ups_a now amber instead of cyan)
 *                ups_a no longer on battery; batt SOC stops decay
 *        Reset  button restores nominal state instantly.
 *
 * State.js integration:
 *   setState('powerSim', { active, scenario, startTs, soc, ... })
 *   subscribers (this module + future Hermes) react to state changes.
 *
 * No external libraries. Pure ES module + DOM + state.js bus.
 * ════════════════════════════════════════════════════════════════ */

import { setState, getState, subscribe } from './state.js';
import { playWarning, playClick } from './sound.js';

// ─── Static catalogues ────────────────────────────────────────────
// All SLD nodes by id, mapped to their type (drives drill-down route)
// and which path they belong to.
const NODE_CATALOGUE = {
    // Path A
    util_a:    { type: 'util',     path: 'A' },
    xfmr_a:    { type: 'xfmr',     path: 'A' },
    ats_a:     { type: 'ats',      path: 'A' },
    genset_a:  { type: 'genset',   path: 'A' },
    ups_a:     { type: 'ups',      path: 'A' },
    batt_a:    { type: 'batt',     path: 'A' },
    rpp_a1:    { type: 'rpp',      path: 'A' },
    rpp_a2:    { type: 'rpp',      path: 'A' },
    busway_a:  { type: 'busway',   path: 'A' },
    // Path B
    util_b:    { type: 'util',     path: 'B' },
    xfmr_b:    { type: 'xfmr',     path: 'B' },
    ats_b:     { type: 'ats',      path: 'B' },
    genset_b:  { type: 'genset',   path: 'B' },
    ups_b:     { type: 'ups',      path: 'B' },
    batt_b:    { type: 'batt',     path: 'B' },
    rpp_b1:    { type: 'rpp',      path: 'B' },
    rpp_b2:    { type: 'rpp',      path: 'B' },
    busway_b:  { type: 'busway',   path: 'B' },
};

const DRILL_TARGETS = {
    ups:    'maintenance',
    ats:    'maintenance',
    rpp:    'maintenance',
    batt:   'maintenance',
    xfmr:   'site_topology',
    switchgear: 'site_topology',
    util:   'tech-assist',
    genset: 'tech-assist',
    busway: 'maintenance',
};

// All SLD lines by id ("src-dst") with their rest-state classification.
// Each entry: path = 'A'|'B', kind = 'flow'|'battery'|'cold'.
const LINE_CATALOGUE = {
    // Path A
    'util_a-xfmr_a':       { path: 'A', kind: 'flow' },
    'xfmr_a-ats_a':        { path: 'A', kind: 'flow' },
    'genset_a-ats_a':      { path: 'A', kind: 'cold' },          // standby until utility loss
    'ats_a-ups_a':         { path: 'A', kind: 'flow' },
    'batt_a-ups_a':        { path: 'A', kind: 'battery-idle' },
    'ups_a-rpp_a1':        { path: 'A', kind: 'flow' },
    'rpp_a1-rpp_a2':       { path: 'A', kind: 'flow' },
    'rpp_a2-busway_a':     { path: 'A', kind: 'flow' },
    // Path B
    'util_b-xfmr_b':       { path: 'B', kind: 'flow' },
    'xfmr_b-ats_b':        { path: 'B', kind: 'flow' },
    'genset_b-ats_b':      { path: 'B', kind: 'cold' },
    'ats_b-ups_b':         { path: 'B', kind: 'flow' },
    'batt_b-ups_b':        { path: 'B', kind: 'battery-idle' },
    'ups_b-rpp_b1':        { path: 'B', kind: 'flow' },
    'rpp_b1-rpp_b2':       { path: 'B', kind: 'flow' },
    'rpp_b2-busway_b':     { path: 'B', kind: 'flow' },
};

// ─── Simulation state ──────────────────────────────────────────────
const SIM_STAGES = {
    NOMINAL: 'nominal',
    UTILITY_LOSS_A: 'utility_loss_a',
};
const UTILITY_LOSS_A_TIMELINE = [
    // {at: ms, label: status, action: fn}
    { at:    0, label: 'Utility A lost · UPS A on battery · ATS A transferring',
                action: '_subStage1_loss' },
    { at: 4000, label: 'Genset A spinning up (cold start)',
                action: '_subStage2_genset_warmup' },
    { at: 8000, label: 'Genset A online · ATS A connected · UPS A on amber bus',
                action: '_subStage3_genset_online' },
];

let _initialized = false;
let _socTimer = null;
let _soc = 100;
let _stageTimers = [];
let _btnSim = null;
let _btnReset = null;
let _statusEl = null;

// ─── Apply state to the SLD DOM ───────────────────────────────────
// Uses querySelectorAll so iso-blocks (HTML divs in views/power_ups_iso.js)
// AND legacy SVG <g class="sld-node"> stay in sync, regardless of which
// layer is currently visible.
function _applyNodeState(nodeId, state) {
    // state is one of: 'energized-a' | 'energized-b' | 'battery' |
    //                  'cold' | 'fault' | 'nominal' | 'transferring'
    const els = document.querySelectorAll(`.sld-node[data-sld-node="${nodeId}"]`);
    els.forEach((el) => {
        el.classList.remove(
            'sld-node-energized-a', 'sld-node-energized-b',
            'sld-node-battery', 'sld-node-cold', 'sld-node-fault',
            'sld-node-transferring',
        );
        if (state) el.classList.add(`sld-node-${state}`);
    });
}

function _applyLineState(lineId, state) {
    // state is one of: 'flow-a' | 'flow-b' | 'battery' | 'cold' | 'fault'
    const els = document.querySelectorAll(`.sld-line[data-sld-line="${lineId}"]`);
    els.forEach((el) => {
        el.classList.remove(
            'sld-line-flow-a', 'sld-line-flow-b',
            'sld-line-battery', 'sld-line-cold', 'sld-line-fault',
            'sld-line-flowing',
        );
        if (state === 'flow-a' || state === 'flow-b' || state === 'battery') {
            el.classList.add(`sld-line-${state}`, 'sld-line-flowing');
        } else if (state) {
            el.classList.add(`sld-line-${state}`);
        }
    });
}

// ─── Apply nominal palette (default state, idempotent) ────────────
function _applyNominalState() {
    // Nodes
    for (const [id, info] of Object.entries(NODE_CATALOGUE)) {
        if (info.type === 'genset') { _applyNodeState(id, 'cold'); continue; }
        if (info.type === 'batt')   { _applyNodeState(id, 'battery'); continue; }   // idle=ready
        _applyNodeState(id, info.path === 'A' ? 'energized-a' : 'energized-b');
    }
    // Lines
    for (const [id, info] of Object.entries(LINE_CATALOGUE)) {
        if (info.kind === 'cold')           _applyLineState(id, 'cold');
        else if (info.kind === 'battery-idle') _applyLineState(id, 'battery');
        else _applyLineState(id, info.path === 'A' ? 'flow-a' : 'flow-b');
    }
    // Battery line stays as a static link, no flow animation
    document.querySelectorAll(
        `.sld-line[data-sld-line="batt_a-ups_a"], .sld-line[data-sld-line="batt_b-ups_b"]`
    ).forEach((el) => el.classList.remove('sld-line-flowing'));
}

// ─── Click drill-down ─────────────────────────────────────────────
function _onSldClick(e) {
    const nodeEl = e.target.closest('[data-sld-node]');
    if (!nodeEl) return;
    const id = nodeEl.dataset.sldNode;
    const info = NODE_CATALOGUE[id];
    if (!info) return;
    const route = DRILL_TARGETS[info.type] || 'maintenance';
    // Stash the focus asset id so the destination view can read it
    try { sessionStorage.setItem('cmms_focus_asset_id', id); } catch {}
    console.log('[power_sld] click → %s (%s) → route=%s', id, info.type, route);
    playClick();
    const navItem = document.querySelector(`.nav-item[data-route="${route}"]`);
    if (navItem) navItem.click();
}

// ─── Simulate Utility Loss (Path A) ───────────────────────────────
function _clearTimers() {
    _stageTimers.forEach(t => clearTimeout(t));
    _stageTimers = [];
    if (_socTimer) { clearInterval(_socTimer); _socTimer = null; }
}

function _setSimStatus(text, tone) {
    if (!_statusEl) return;
    _statusEl.textContent = text;
    _statusEl.setAttribute('data-tone', tone || 'info');
    _statusEl.removeAttribute('hidden');
}

function _subStage1_loss() {
    _setSimStatus(UTILITY_LOSS_A_TIMELINE[0].label, 'warn');
    // Publish stage so iso layer (power_ups_iso.js) can react with ATS arm + genset fan
    setState('powerSim', { active: true, scenario: SIM_STAGES.UTILITY_LOSS_A, stage: 'utility_loss_a', startTs: Date.now() });
    // Path A upstream goes cold
    _applyNodeState('util_a', 'fault');
    _applyNodeState('xfmr_a', 'cold');
    _applyLineState('util_a-xfmr_a', 'fault');
    _applyLineState('xfmr_a-ats_a', 'cold');
    // ATS in transit
    _applyNodeState('ats_a', 'transferring');
    // UPS on battery
    _applyNodeState('ups_a', 'battery');
    _applyLineState('ats_a-ups_a', 'cold');           // input from ATS gone for now
    _applyLineState('batt_a-ups_a', 'battery');       // battery line lights up flowing
    // Re-add flowing class to the battery line so it animates
    const battLine = document.querySelector(`.sld-line[data-sld-line="batt_a-ups_a"]`);
    if (battLine) battLine.classList.add('sld-line-flowing');
    // Downstream still gets power from UPS battery, but recolour amber
    ['ups_a-rpp_a1', 'rpp_a1-rpp_a2', 'rpp_a2-busway_a'].forEach(l => _applyLineState(l, 'battery'));
    ['rpp_a1', 'rpp_a2', 'busway_a'].forEach(n => _applyNodeState(n, 'battery'));
    // SOC ticker
    _soc = 100;
    setState('powerSim.soc_a', _soc);
    _socTimer = setInterval(() => {
        _soc = Math.max(0, _soc - 1);
        setState('powerSim.soc_a', _soc);
        _renderSocOnBatteryNode();
    }, 1000);
    playWarning();
}

function _subStage2_genset_warmup() {
    _setSimStatus(UTILITY_LOSS_A_TIMELINE[1].label, 'warn');
    setState('powerSim', { active: true, scenario: SIM_STAGES.UTILITY_LOSS_A, stage: 'genset_warming_a', startTs: Date.now() });
    _applyNodeState('genset_a', 'transferring');     // amber pulse
}

function _subStage3_genset_online() {
    _setSimStatus(UTILITY_LOSS_A_TIMELINE[2].label, 'warn');
    setState('powerSim', { active: true, scenario: SIM_STAGES.UTILITY_LOSS_A, stage: 'genset_online_a', startTs: Date.now() });
    // Genset feeding ATS
    _applyNodeState('genset_a', 'battery');           // running on amber now
    _applyLineState('genset_a-ats_a', 'battery');
    // ATS on genset
    _applyNodeState('ats_a', 'battery');
    _applyLineState('ats_a-ups_a', 'battery');
    // UPS on amber bus (no longer pure battery)
    _applyNodeState('ups_a', 'battery');
    // Stop SOC decay (UPS is now charging back)
    if (_socTimer) { clearInterval(_socTimer); _socTimer = null; }
}

function _renderSocOnBatteryNode() {
    // Best-effort: try to inline the SOC into both legacy SVG and iso-block
    document.querySelectorAll('[data-sld-metric="batt_a-soc"]').forEach((el) => {
        el.textContent = `${_soc}%`;
        el.dataset.frozen = '1';   // tell iso jitter loop to leave SOC alone
    });
}

function _runSimulation(scenario) {
    _clearTimers();
    setState('powerSim', { active: true, scenario, startTs: Date.now() });
    if (scenario !== SIM_STAGES.UTILITY_LOSS_A) return;
    const actions = {
        '_subStage1_loss': _subStage1_loss,
        '_subStage2_genset_warmup': _subStage2_genset_warmup,
        '_subStage3_genset_online': _subStage3_genset_online,
    };
    for (const stage of UTILITY_LOSS_A_TIMELINE) {
        const t = setTimeout(actions[stage.action], stage.at);
        _stageTimers.push(t);
    }
    if (_btnReset) _btnReset.removeAttribute('hidden');
    if (_btnSim) _btnSim.disabled = true;
}

function _resetSimulation() {
    _clearTimers();
    setState('powerSim', { active: false, scenario: SIM_STAGES.NOMINAL, stage: 'nominal', startTs: Date.now() });
    _soc = 100;
    setState('powerSim.soc_a', _soc);
    // Unfreeze SOC for jitter loop now that sim is reset
    document.querySelectorAll('[data-sld-metric="batt_a-soc"]').forEach((el) => {
        delete el.dataset.frozen;
        el.textContent = 'SOC 100%';
    });
    _applyNominalState();
    _setSimStatus('Nominal · 2N redundancy intact', 'ok');
    setTimeout(() => { _statusEl?.setAttribute('hidden', ''); }, 1800);
    if (_btnReset) _btnReset.setAttribute('hidden', '');
    if (_btnSim) _btnSim.disabled = false;
    playClick();
}

// ─── Wiring ──────────────────────────────────────────────────────
function _wireEvents() {
    _btnSim   = document.getElementById('sld-sim-utility-loss-a');
    _btnReset = document.getElementById('sld-sim-reset');
    _statusEl = document.getElementById('sld-sim-status');

    _btnSim?.addEventListener('click', () => _runSimulation(SIM_STAGES.UTILITY_LOSS_A));
    _btnReset?.addEventListener('click', _resetSimulation);

    // Make the entire SLD canvas a click delegator for nodes (covers both
    // legacy SVG and the iso-block layer rendered by power_ups_iso.js).
    const canvas = document.querySelector('#view-power .pid-canvas');
    canvas?.addEventListener('click', _onSldClick);
}

// ─── Public init ────────────────────────────────────────────────
export function initPowerSld() {
    if (_initialized) return;
    if (!document.querySelector('#view-power .pid-svg')) {
        // SLD not in DOM (defensive)
        return;
    }
    _wireEvents();
    _applyNominalState();
    setState('powerSim', { active: false, scenario: SIM_STAGES.NOMINAL });

    // Subscribe to powerSim state — future Hermes hook
    try {
        subscribe('powerSim', (s) => {
            if (!s) return;
            // External force-reset
            if (s.scenario === SIM_STAGES.NOMINAL && s.active === false &&
                getState('powerSim.soc_a') !== _soc) {
                _resetSimulation();
            }
        });
    } catch {}

    _initialized = true;
    console.log('[power_sld] enhancer ready (palette + flow + click + sim)');
}
