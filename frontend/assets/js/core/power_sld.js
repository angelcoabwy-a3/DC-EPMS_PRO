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
import { tripNode, restoreAll } from './power_grid.js';

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

// 12 DDUs — extend NODE_CATALOGUE so click-selection resolves them too
['a', 'b'].forEach((p) => {
    [1, 2, 3, 4, 5, 6].forEach((n) => {
        NODE_CATALOGUE[`ddu_${p}${n}`] = { type: 'ddu', path: p.toUpperCase() };
    });
});

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
    ddu:    'rack-heatmap',
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

// Hardcoded simulation timeline removed in v0.10.7 — see core/power_grid.js
// for the DAG-based propagation engine that replaced it.

let _initialized = false;
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

// ─── Click selection (Phase 4 v0.10.9) ────────────────────────────
//
// Plain click on a node -> set state.selectedAsset, which the
// asset_panel.js renderer subscribes to. Drill-down to the
// Maintenance view is now an explicit action button INSIDE the
// asset panel, not the click itself. This frees the primary
// gesture for inspection without forcing a route change.
//
// Shift-click is intercepted upstream by power_ups_iso.js for TRIP
// (returns early there). The TRIP pip click also stops propagation
// so we never reach this handler for those gestures.
function _onSldClick(e) {
    if (e.shiftKey) return;
    if (e.target && e.target.closest && e.target.closest('.iso-trip-pip')) return;
    const nodeEl = e.target.closest('[data-sld-node]');
    if (!nodeEl) {
        // Click on empty canvas -> deselect
        if (e.target.closest('.sld-iso-stage') || e.target.closest('.pid-canvas')) {
            if (getState('selectedAsset')) {
                setState('selectedAsset', null);
                playClick();
            }
        }
        return;
    }
    const id = nodeEl.dataset.sldNode;
    if (!NODE_CATALOGUE[id]) return;
    setState('selectedAsset', id);
    playClick();
}

// ─── Demo trigger: hand off to the DAG engine ─────────────────────
//
// The hardcoded simulation timeline is gone (v0.10.7). Faults are now
// injected via core/power_grid.js's tripNode() / restoreAll(), which
// runs propagatePower() and publishes state.grid for the iso layer to
// re-render. The Sim button is preserved as a one-click demo shortcut
// that trips util_a (utility-loss A) — the engine handles the cascade.

function _setSimStatus(text, tone) {
    if (!_statusEl) return;
    _statusEl.textContent = text;
    _statusEl.setAttribute('data-tone', tone || 'info');
    _statusEl.removeAttribute('hidden');
}

function _runSimulation() {
    // Trip util_a — the DAG engine cascades:
    //   util_a -> xfmr_a (dies) -> ats_a (2s transfer, genset_a starts)
    //                                -> ups_a goes on battery during gap
    //                                -> ats_a back online via genset
    tripNode('util_a');
    _setSimStatus('TRIP injected: util_a · cascading through DAG', 'warn');
    if (_btnReset) _btnReset.removeAttribute('hidden');
    if (_btnSim)   _btnSim.disabled = true;
    playWarning();
}

function _resetSimulation() {
    restoreAll();
    _setSimStatus('Nominal · 2N redundancy intact', 'ok');
    setTimeout(() => { _statusEl?.setAttribute('hidden', ''); }, 1800);
    if (_btnReset) _btnReset.setAttribute('hidden', '');
    if (_btnSim)   _btnSim.disabled = false;
    playClick();
}

// Status pill auto-update from grid state — counts tripped nodes
function _wireStatusPill() {
    subscribe('grid', (grid) => {
        if (!grid || !_statusEl) return;
        const tripped = Object.values(grid).filter((n) => n.tripped).map((n) => n.id);
        const onBattery = Object.values(grid).filter((n) => n.on_battery).map((n) => n.id);
        const transferring = Object.values(grid).filter((n) => n.transferring).map((n) => n.id);

        if (tripped.length === 0 && onBattery.length === 0 && transferring.length === 0) {
            // fully nominal — only hide if button is in nominal state
            if (_btnReset && _btnReset.hasAttribute('hidden')) {
                // already nominal; nothing to do
            }
            return;
        }
        const parts = [];
        if (tripped.length)      parts.push(`${tripped.length} TRIPPED [${tripped.join(', ')}]`);
        if (transferring.length) parts.push(`${transferring.length} TRANSFERRING`);
        if (onBattery.length)    parts.push(`${onBattery.length} ON BATTERY`);
        _setSimStatus(parts.join(' · '), 'warn');
        if (_btnReset) _btnReset.removeAttribute('hidden');
    });
}

// ─── Wiring ──────────────────────────────────────────────────────
function _wireEvents() {
    _btnSim   = document.getElementById('sld-sim-utility-loss-a');
    _btnReset = document.getElementById('sld-sim-reset');
    _statusEl = document.getElementById('sld-sim-status');

    _btnSim?.addEventListener('click', _runSimulation);
    _btnReset?.addEventListener('click', _resetSimulation);

    // Make the entire SLD canvas a click delegator for nodes (covers both
    // legacy SVG and the iso-block layer rendered by power_ups_iso.js).
    const canvas = document.querySelector('#view-power .pid-canvas');
    canvas?.addEventListener('click', _onSldClick);

    // Subscribe the status pill to grid state changes
    _wireStatusPill();
}

// ─── Public init ────────────────────────────────────────────────
export function initPowerSld() {
    if (_initialized) return;
    if (!document.querySelector('#view-power .pid-svg')) {
        // SLD not in DOM (defensive)
        return;
    }
    _wireEvents();
    // Apply nominal palette to legacy SVG (kept hidden when iso is mounted)
    _applyNominalState();

    _initialized = true;
    console.log('[power_sld] enhancer ready (palette + flow + click + DAG-bound sim)');
}
