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
 *   Subscribers (views/power.js flat SLD) re-render on change.
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
    busway_a: { type: 'busway', path: 'A', sources: ['rpp_a2'],               targets: ['ddu_a1', 'ddu_a2', 'ddu_a3', 'ddu_a4', 'ddu_a5', 'ddu_a6'] },
    // 6 representative DDUs (Drop-Down Units) hanging off Busway A — each
    // services one GB200 NVL72 rack with combined 480V power tap-off + DLC
    // secondary loop hookup. 118 racks total per Path C2; we visualize 6.
    ddu_a1:   { type: 'ddu',    path: 'A', sources: ['busway_a'],             targets: [] },
    ddu_a2:   { type: 'ddu',    path: 'A', sources: ['busway_a'],             targets: [] },
    ddu_a3:   { type: 'ddu',    path: 'A', sources: ['busway_a'],             targets: [] },
    ddu_a4:   { type: 'ddu',    path: 'A', sources: ['busway_a'],             targets: [] },
    ddu_a5:   { type: 'ddu',    path: 'A', sources: ['busway_a'],             targets: [] },
    ddu_a6:   { type: 'ddu',    path: 'A', sources: ['busway_a'],             targets: [] },
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
    busway_b: { type: 'busway', path: 'B', sources: ['rpp_b2'],               targets: ['ddu_b1', 'ddu_b2', 'ddu_b3', 'ddu_b4', 'ddu_b5', 'ddu_b6'] },
    ddu_b1:   { type: 'ddu',    path: 'B', sources: ['busway_b'],             targets: [] },
    ddu_b2:   { type: 'ddu',    path: 'B', sources: ['busway_b'],             targets: [] },
    ddu_b3:   { type: 'ddu',    path: 'B', sources: ['busway_b'],             targets: [] },
    ddu_b4:   { type: 'ddu',    path: 'B', sources: ['busway_b'],             targets: [] },
    ddu_b5:   { type: 'ddu',    path: 'B', sources: ['busway_b'],             targets: [] },
    ddu_b6:   { type: 'ddu',    path: 'B', sources: ['busway_b'],             targets: [] },

    // ── Phase 2 — Building D (Path C2 DESIGN, MVP S2) ──────────────
    // Mirrors site_model.yml Path D: 35 kV AC -> MV Rectifier ->
    // SSCB -> 800 VDC UNIPOLAR TN-S bus -> {BESS, RPP D1/D2} -> hall.
    // The genset farm is the standby AC source: 13.8 kV paralleling
    // bus -> step-up 13.8/35 kV -> the rectifier's AC side. Dead-bus
    // black start is modeled INSTANT in the sandbox (the real farm
    // takes ~10 s; design-sim honesty note in the UI).
    util_d:     { type: 'util',   path: 'D', sources: [],                        targets: ['mv_rect_d'] },
    gen_farm_d: { type: 'farm',   path: 'D', sources: [],                        targets: ['mv_bus_d'] },
    mv_bus_d:   { type: 'mvbus',  path: 'D', sources: ['gen_farm_d'],            targets: ['stepup_d'] },
    stepup_d:   { type: 'xfmr',   path: 'D', sources: ['mv_bus_d'],              targets: ['mv_rect_d'] },
    mv_rect_d:  { type: 'mvrect', path: 'D', sources: ['util_d', 'stepup_d'],    targets: ['sscb_d'],
                  primary: 'util_d', secondary: 'stepup_d' },
    sscb_d:     { type: 'sscb',   path: 'D', sources: ['mv_rect_d'],             targets: ['dc_bus_d'] },
    dc_bus_d:   { type: 'dcbus',  path: 'D', sources: ['sscb_d'],                targets: ['bess_d', 'rpp_d1', 'rpp_d2'] },
    // BESS is bus-parallel storage (a load/reserve, never a steady-
    // state source in this DAG — same finite-holdup rule as batteries).
    bess_d:     { type: 'bess',   path: 'D', sources: ['dc_bus_d'],              targets: [] },
    rpp_d1:     { type: 'rpp',    path: 'D', sources: ['dc_bus_d'],              targets: ['hall_d'] },
    rpp_d2:     { type: 'rpp',    path: 'D', sources: ['dc_bus_d'],              targets: ['hall_d'] },
    hall_d:     { type: 'hall',   path: 'D', sources: ['rpp_d1', 'rpp_d2'],      targets: [] },
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
    // Leaf DDUs propagate from busway alive state
    'ddu_a1', 'ddu_a2', 'ddu_a3', 'ddu_a4', 'ddu_a5', 'ddu_a6',
    'ddu_b1', 'ddu_b2', 'ddu_b3', 'ddu_b4', 'ddu_b5', 'ddu_b6',
    // Phase 2 Building D — util first so the farm's auto-standby
    // decision (runs iff the utility feed is dead) sees fresh state.
    'util_d', 'gen_farm_d', 'mv_bus_d', 'stepup_d', 'mv_rect_d',
    'sscb_d', 'dc_bus_d', 'bess_d', 'rpp_d1', 'rpp_d2', 'hall_d',
];

// Per-node mutable state (engine-private; published via setState)
let _grid = null;
let _atsTransferTimers = { ats_a: null, ats_b: null };
let _battDecayTimers   = { batt_a: null, batt_b: null };
let _gensetTimers      = { genset_a: null, genset_b: null };
let _propagateScheduled = false;

// NFPA 110 Type 10 genset sequence, fast-forwarded for the sim:
// nameplate is 10 s start; we crank 0.8 s inside the ATS 2 s gap.
const GENSET_CRANK_MS = 800;
const GENSET_COOLDOWN_MS = 1200;

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
            // genset NFPA 110 sequence: standby|cranking|running|cooldown
            // (the Phase 2 farm reports standby|running — instant in sim)
            state: (t.type === 'genset' || t.type === 'farm') ? 'standby' : null,
            // ups IEC 62040-3 operating mode (derived in propagate):
            // double_conversion (VFI-SS-111) | battery | off
            mode: t.type === 'ups' ? 'off' : null,
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
            if (n.tripped) n.state = 'standby';
        }
        else if (t.type === 'farm') {
            // Phase 2 standby farm: auto-runs the moment the Building D
            // utility feed is dead (dead-bus black start, instant in
            // the sandbox). util_d is evaluated earlier in TOPO_ORDER.
            const utilDown = !_grid.util_d.alive;
            n.running = utilDown;
            n.alive = utilDown;
            n.state = utilDown ? 'running' : 'standby';
            n.energized_by = n.alive ? 'genset' : null;
        }
        else if (t.type === 'mvrect') {
            // 2-input AC-side merge (utility primary / farm secondary).
            // Solid-state: no ATS-style transfer gap.
            const prim = _grid[t.primary];
            const sec = _grid[t.secondary];
            if (prim.alive) {
                n.alive = true;
                n.energized_by = prim.energized_by;
            } else if (sec.alive) {
                n.alive = true;
                n.energized_by = sec.energized_by;   // 'genset'
            } else {
                n.alive = false;
                n.energized_by = null;
            }
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
                // IEC 62040-3 VFI-SS-111: normal path is AC->DC->AC.
                n.mode = 'double_conversion';
            } else if (batt && batt.alive) {
                // UPS holdup — output stays alive on battery
                n.alive = true;
                n.on_battery = true;
                n.energized_by = 'battery';
                n.mode = 'battery';
            } else {
                n.alive = false;
                n.on_battery = false;
                n.energized_by = null;
                n.mode = 'off';
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

        // Primary lost while running on primary -> kick off transfer.
        // The genset runs its NFPA 110 start sequence INSIDE the ATS
        // gap: STANDBY -> CRANKING (0.8 s sim / 10 s nameplate) ->
        // RUNNING, then the ATS closes onto it at the 2 s mark.
        if (ats.ats_pos === 'primary' && !primary.alive && !ats.transferring) {
            ats.transferring = true;
            ats.alive = false;
            ats.energized_by = null;
            _startGenset(t.secondary);

            if (_atsTransferTimers[atsId]) clearTimeout(_atsTransferTimers[atsId]);
            _atsTransferTimers[atsId] = setTimeout(() => {
                ats.transferring = false;
                ats.ats_pos = 'secondary';
                _atsTransferTimers[atsId] = null;
                _propagate();
            }, 2000);
        }
        // Primary restored while on secondary -> back-transfer; the
        // genset runs unloaded COOLDOWN before returning to STANDBY.
        else if (ats.ats_pos === 'secondary' && primary.alive && !ats.transferring) {
            ats.transferring = true;
            if (_atsTransferTimers[atsId]) clearTimeout(_atsTransferTimers[atsId]);
            _atsTransferTimers[atsId] = setTimeout(() => {
                ats.transferring = false;
                ats.ats_pos = 'primary';
                _stopGenset(t.secondary);
                _atsTransferTimers[atsId] = null;
                _propagate();
            }, 1500);
        }
    }
}

// ─── Genset NFPA 110 start/stop sequence ───────────────────────────

function _startGenset(gensetId) {
    const gen = _grid[gensetId];
    if (!gen || gen.tripped || gen.state === 'running' || gen.state === 'cranking') return;
    if (_gensetTimers[gensetId]) clearTimeout(_gensetTimers[gensetId]);
    gen.state = 'cranking';
    gen.running = false;
    _gensetTimers[gensetId] = setTimeout(() => {
        if (!_grid || !_grid[gensetId]) return;
        const g = _grid[gensetId];
        if (!g.tripped && g.state === 'cranking') {
            g.state = 'running';
            g.running = true;
        }
        _gensetTimers[gensetId] = null;
        _propagate();
    }, GENSET_CRANK_MS);
}

function _stopGenset(gensetId) {
    const gen = _grid[gensetId];
    if (!gen) return;
    if (_gensetTimers[gensetId]) clearTimeout(_gensetTimers[gensetId]);
    gen.running = false;
    gen.state = 'cooldown';
    _gensetTimers[gensetId] = setTimeout(() => {
        if (!_grid || !_grid[gensetId]) return;
        if (_grid[gensetId].state === 'cooldown') _grid[gensetId].state = 'standby';
        _gensetTimers[gensetId] = null;
        _propagate();
    }, GENSET_COOLDOWN_MS);
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
    const n = Object.keys(TOPOLOGY).length;
    const e = Object.values(TOPOLOGY).reduce((acc, t) => acc + t.targets.length, 0);
    console.log(`[power_grid] DAG engine initialized: ${n} nodes, ${e} edges (Phase 1 + Building D design)`);
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
    for (const k of Object.keys(_gensetTimers)) {
        if (_gensetTimers[k]) {
            clearTimeout(_gensetTimers[k]);
            _gensetTimers[k] = null;
        }
    }
    for (const id of Object.keys(_grid)) {
        const n = _grid[id];
        n.tripped = false;
        n.transferring = false;
        if (n.type === 'batt')   { n.soc = 100;       n.alive = true;  }
        if (n.type === 'genset') { n.running = false; n.alive = false; n.state = 'standby'; }
        if (n.type === 'farm')   { n.running = false; n.alive = false; n.state = 'standby'; }
        if (n.type === 'ats')    { n.ats_pos = 'primary'; }
        if (n.type === 'ups')    { n.on_battery = false; n.mode = 'double_conversion'; }
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
