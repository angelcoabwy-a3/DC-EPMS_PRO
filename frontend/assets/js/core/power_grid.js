/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — frontend/assets/js/core/power_grid.js
 *
 * Electrical Propagation Engine — pure DAG, no DOM.
 *
 *   Replaces the hardcoded simulation timeline in power_sld.js with
 *   a real-time topology-driven evaluator. Any node can be tripped
 *   and the cascade obeys physics:
 *
 *     - Standard nodes (xfmr, rpp, busway): if input dead, output dead.
 *     - ATS: 2-input merge. Primary lost  -> 2s transfer delay (output
 *            dead during the gap)  -> genset starts  -> secondary input
 *            takes over. Primary restored -> 1.5s back-transfer.
 *     - UPS: input lost  -> battery holdup (output stays alive) until
 *            SOC reaches 0  -> output dies.
 *     - Genset: alive only when ATS has called it to run.
 *     - Battery: alive while SOC > 0 AND not tripped.
 *
 *   No external libs. State published via state.js's setState('grid', ...).
 *   Subscribers (power_ups_iso.js) re-render CSS classes on change.
 *
 *   Ref: IEEE 446 (emergency power), IEC 62040-3 (UPS classification),
 *        NFPA 110 Type 10 (10s genset start).
 * ════════════════════════════════════════════════════════════════ */

import { setState } from './state.js';

// ─── Topology — 18 nodes, directed edges via sources/targets ─────
export const TOPOLOGY = {
    // Path A
    util_a:   { type: 'util',   path: 'A', sources: [],                       targets: ['xfmr_a'] },
    xfmr_a:   { type: 'xfmr',   path: 'A', sources: ['util_a'],               targets: ['ats_a'] },
    genset_a: { type: 'genset', path: 'A', sources: [],                       targets: ['ats_a'] },
    ats_a:    { type: 'ats',    path: 'A', sources: ['xfmr_a', 'genset_a'],   targets: ['ups_a'],
                primary: 'xfmr_a', secondary: 'genset_a' },
    batt_a:   { type: 'batt',   path: 'A', sources: [],                       targets: ['ups_a'] },
    ups_a:    { type: 'ups',    path: 'A', sources: ['ats_a'],                targets: ['rpp_a1'],  battery: 'batt_a' },
    rpp_a1:   { type: 'rpp',    path: 'A', sources: ['ups_a'],                targets: ['rpp_a2'] },
    rpp_a2:   { type: 'rpp',    path: 'A', sources: ['rpp_a1'],               targets: ['busway_a'] },
    busway_a: { type: 'busway', path: 'A', sources: ['rpp_a2'],               targets: [] },
    // Path B (mirrored)
    util_b:   { type: 'util',   path: 'B', sources: [],                       targets: ['xfmr_b'] },
    xfmr_b:   { type: 'xfmr',   path: 'B', sources: ['util_b'],               targets: ['ats_b'] },
    genset_b: { type: 'genset', path: 'B', sources: [],                       targets: ['ats_b'] },
    ats_b:    { type: 'ats',    path: 'B', sources: ['xfmr_b', 'genset_b'],   targets: ['ups_b'],
                primary: 'xfmr_b', secondary: 'genset_b' },
    batt_b:   { type: 'batt',   path: 'B', sources: [],                       targets: ['ups_b'] },
    ups_b:    { type: 'ups',    path: 'B', sources: ['ats_b'],                targets: ['rpp_b1'],  battery: 'batt_b' },
    rpp_b1:   { type: 'rpp',    path: 'B', sources: ['ups_b'],                targets: ['rpp_b2'] },
    rpp_b2:   { type: 'rpp',    path: 'B', sources: ['rpp_b1'],               targets: ['busway_b'] },
    busway_b: { type: 'busway', path: 'B', sources: ['rpp_b2'],               targets: [] },
};

// Topological order — utility roots, then conditional sources, then chain.
// Hand-coded (tiny graph, simpler than Kahn's at this scale).
const TOPO_ORDER = [
    'util_a', 'util_b', 'batt_a', 'batt_b', 'genset_a', 'genset_b',
    'xfmr_a', 'xfmr_b',
    'ats_a',  'ats_b',
    'ups_a',  'ups_b',
    'rpp_a1', 'rpp_b1',
    'rpp_a2', 'rpp_b2',
    'busway_a', 'busway_b',
];

// Per-node mutable state (engine-private; published via setState)
let _grid = null;
let _atsTransferTimers = { ats_a: null, ats_b: null };
let _battDecayTimers   = { batt_a: null, batt_b: null };
let _propagateScheduled = false;

// ─── Initial state ────────────────────────────────────────────────

function _initGrid() {
    _grid = {};
    for (const id of Object.keys(TOPOLOGY)) {
        const t = TOPOLOGY[id];
        _grid[id] = {
            id,
            type: t.type,
            path: t.path,
            tripped: false,
            alive: false,           // computed by propagate
            on_battery: false,      // ups only
            soc: 100,               // batt only
            ats_pos: t.type === 'ats' ? 'primary' : null,
            transferring: false,    // ats only
            running: false,         // genset only
            energized_by: null,     // 'util' | 'genset' | 'battery' | null
        };
    }
}

// ─── Propagation core ─────────────────────────────────────────────

function _propagate() {
    if (!_grid) return;

    for (const id of TOPO_ORDER) {
        const t = TOPOLOGY[id];
        const n = _grid[id];

        // Tripped breaker: hard kill, no propagation
        if (n.tripped) {
            n.alive = false;
            n.energized_by = null;
            continue;
        }

        if (t.type === 'util') {
            n.alive = true;
            n.energized_by = 'util';
        }
        else if (t.type === 'genset') {
            n.alive = !!n.running;
            n.energized_by = n.alive ? 'genset' : null;
        }
        else if (t.type === 'batt') {
            n.alive = n.soc > 0;
            n.energized_by = n.alive ? 'battery' : null;
        }
        else if (t.type === 'ats') {
            const primary = _grid[t.primary];
            const secondary = _grid[t.secondary];

            if (n.transferring) {
                // 2-second power gap during transfer — ATS output dead
                n.alive = false;
                n.energized_by = null;
                n.ats_pos = 'transferring';
            }
            else if (n.ats_pos === 'primary' && primary.alive) {
                n.alive = true;
                n.energized_by = primary.energized_by;
            }
            else if (n.ats_pos === 'secondary' && secondary.alive) {
                n.alive = true;
                n.energized_by = secondary.energized_by;  // 'genset'
            }
            else {
                // ATS pos doesn't match a live source — output dead
                n.alive = false;
                n.energized_by = null;
            }
        }
        else if (t.type === 'ups') {
            const ats = _grid[t.sources[0]];
            const batt = _grid[t.battery];

            if (ats.alive) {
                n.alive = true;
                n.on_battery = false;
                n.energized_by = ats.energized_by;
            } else if (batt && batt.alive) {
                // UPS holdup — output stays alive on battery
                n.alive = true;
                n.on_battery = true;
                n.energized_by = 'battery';
            } else {
                n.alive = false;
                n.on_battery = false;
                n.energized_by = null;
            }
        }
        else {
            // Standard node (xfmr, rpp, busway) — passthrough
            const inputAlive = t.sources.some((s) => _grid[s].alive);
            n.alive = inputAlive;
            if (inputAlive) {
                const liveSrc = t.sources.find((s) => _grid[s].alive);
                n.energized_by = _grid[liveSrc].energized_by;
            } else {
                n.energized_by = null;
            }
        }
    }

    // Check ATS transfer triggers (mutates state, may schedule timers)
    _maybeTriggerTransfers();
    // Check UPS battery decay (mutates state, schedules 1Hz interval)
    _manageBatteryDecay();

    // Publish full grid state (shallow clone — subscribers see new ref)
    const snapshot = {};
    for (const id of Object.keys(_grid)) snapshot[id] = { ..._grid[id] };
    setState('grid', snapshot);
}

function _scheduleProp() {
    if (_propagateScheduled) return;
    _propagateScheduled = true;
    queueMicrotask(() => {
        _propagateScheduled = false;
        _propagate();
    });
}

// ─── ATS transfer logic (NFPA 110 Type 10 — 10s start; we fast-fwd to 2s) ─

function _maybeTriggerTransfers() {
    for (const atsId of ['ats_a', 'ats_b']) {
        const ats = _grid[atsId];
        const t = TOPOLOGY[atsId];
        const primary = _grid[t.primary];
        const secondary = _grid[t.secondary];

        // Primary lost while running on primary -> kick off transfer
        if (ats.ats_pos === 'primary' && !primary.alive && !ats.transferring) {
            ats.transferring = true;
            ats.alive = false;
            ats.energized_by = null;
            _grid[t.secondary].running = true;  // start genset

            if (_atsTransferTimers[atsId]) clearTimeout(_atsTransferTimers[atsId]);
            _atsTransferTimers[atsId] = setTimeout(() => {
                ats.transferring = false;
                ats.ats_pos = 'secondary';
                _atsTransferTimers[atsId] = null;
                _propagate();
            }, 2000);
        }
        // Primary restored while on secondary -> back-transfer
        else if (ats.ats_pos === 'secondary' && primary.alive && !ats.transferring) {
            ats.transferring = true;
            if (_atsTransferTimers[atsId]) clearTimeout(_atsTransferTimers[atsId]);
            _atsTransferTimers[atsId] = setTimeout(() => {
                ats.transferring = false;
                ats.ats_pos = 'primary';
                _grid[t.secondary].running = false;  // stop genset
                _atsTransferTimers[atsId] = null;
                _propagate();
            }, 1500);
        }
    }
}

// ─── UPS battery decay (1% per second while on battery) ───────────

function _manageBatteryDecay() {
    for (const upsId of ['ups_a', 'ups_b']) {
        const ups = _grid[upsId];
        const t = TOPOLOGY[upsId];
        const battId = t.battery;
        const batt = _grid[battId];

        if (ups.on_battery && !_battDecayTimers[battId]) {
            _battDecayTimers[battId] = setInterval(() => {
                if (!_grid) return;
                batt.soc = Math.max(0, batt.soc - 1);
                if (batt.soc === 0) batt.alive = false;
                _propagate();
            }, 1000);
        } else if (!ups.on_battery && _battDecayTimers[battId]) {
            clearInterval(_battDecayTimers[battId]);
            _battDecayTimers[battId] = null;
        }
    }
}

// ─── Public API ───────────────────────────────────────────────────

export function initPowerGrid() {
    _initGrid();
    _propagate();
    console.log('[power_grid] DAG engine initialized: 18 nodes, 17 edges');
}

export function tripNode(id) {
    if (!_grid || !_grid[id]) return false;
    if (_grid[id].tripped) return false;
    _grid[id].tripped = true;
    console.log(`[power_grid] TRIP -> ${id} (${_grid[id].type})`);
    _propagate();
    return true;
}

export function restoreNode(id) {
    if (!_grid || !_grid[id]) return false;
    if (!_grid[id].tripped) return false;
    _grid[id].tripped = false;
    console.log(`[power_grid] RESTORE -> ${id}`);
    _propagate();
    return true;
}

export function toggleTrip(id) {
    if (!_grid || !_grid[id]) return false;
    return _grid[id].tripped ? restoreNode(id) : tripNode(id);
}

export function restoreAll() {
    if (!_grid) return;
    // Cancel pending ATS timers
    for (const k of Object.keys(_atsTransferTimers)) {
        if (_atsTransferTimers[k]) {
            clearTimeout(_atsTransferTimers[k]);
            _atsTransferTimers[k] = null;
        }
    }
    for (const k of Object.keys(_battDecayTimers)) {
        if (_battDecayTimers[k]) {
            clearInterval(_battDecayTimers[k]);
            _battDecayTimers[k] = null;
        }
    }
    for (const id of Object.keys(_grid)) {
        const n = _grid[id];
        n.tripped = false;
        n.transferring = false;
        if (n.type === 'batt')   { n.soc = 100;       n.alive = true;  }
        if (n.type === 'genset') { n.running = false; n.alive = false; }
        if (n.type === 'ats')    { n.ats_pos = 'primary'; }
        if (n.type === 'ups')    { n.on_battery = false; }
    }
    console.log('[power_grid] RESTORE ALL');
    _propagate();
}

export function getGridState()    { return _grid; }
export function getTopology()     { return TOPOLOGY; }
export function getTopoOrder()    { return TOPO_ORDER.slice(); }

// Convenience: which nodes are currently tripped
export function getTrippedNodes() {
    if (!_grid) return [];
    return Object.values(_grid).filter((n) => n.tripped).map((n) => n.id);
}
