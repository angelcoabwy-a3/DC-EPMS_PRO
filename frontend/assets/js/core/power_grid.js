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
 *     - MV transfer controller (mvtc, DC-EPMS-068 closed design; was a
 *            480 V ATS): 52-U utility incomer / 52-GM generator main,
 *            open transition. Primary lost -> 2 s gap (output dead) ->
 *            generator bus starts -> 52-GM closes. Primary restored ->
 *            1.5 s back-transfer. Same engine rules as the old ATS;
 *            the position field keeps its name (ats_pos).
 *     - UPS bank: 8 x 2.5 MW blocks per path (config/power_plant.yml).
 *            Input lost -> battery holdup until SOC 0. Blocks can be
 *            taken out one by one (setUnitsOut): the bank stays alive
 *            while one block is in service; capacity / N / N+1 are
 *            published against the 16.76 MW full-path IT load.
 *     - Generator bus: 9 x 2.75 MW at 13.8 kV per path. Alive only when
 *            the transfer controller has called it; N / N+1 against
 *            the 21.5 MW generation floor (ADR-013).
 *     - Battery: alive while SOC > 0 AND not tripped.
 *
 *   No external libs. State published via state.js's setState('grid', ...).
 *   Subscribers (views/power.js flat SLD) re-render on change.
 *
 *   Ref: IEEE 446 (emergency power), IEC 62040-3 (UPS classification),
 *        NFPA 110 Type 10 (10s genset start).
 * ════════════════════════════════════════════════════════════════ */

import { setState } from './state.js';

// ─── Closed Phase 1 design (config/power_plant.yml, ADR-013) ─────
// Fenced against the YAML in tests/frontend/power_grid.test.js.
export const PHASE1 = Object.freeze({
    itLoadPerPathKw: 16760,      // one path carrying 100 % of the IT load
    ups: Object.freeze({ units: 8, unitKw: 2500, floorKw: 16760, eta: 0.97 }),
    gen: Object.freeze({ units: 9, unitKw: 2750, floorKw: 21500 }),  // design total
});

// ─── Topology — directed edges via sources/targets ───────────────
export const TOPOLOGY = {
    // Path A -- closed Phase 1 design (DC-EPMS-068, config/power_plant.yml)
    util_a:   { type: 'util',   path: 'A', sources: [],                        targets: ['xfmr_a'] },
    // utility transformer 27.5 / 13.8 kV (site model v2: mv_xfmr_a)
    xfmr_a:   { type: 'xfmr',   path: 'A', sources: ['util_a'],                targets: ['mvtc_a'] },
    // generator bus: 9 x 2.75 MW at 13.8 kV (site model v2: genset_a_01..09)
    genset_a: { type: 'genset', path: 'A', sources: [],                        targets: ['mvtc_a'],
                units: PHASE1.gen.units, unitKw: PHASE1.gen.unitKw, floorKw: PHASE1.gen.floorKw },
    mvtc_a:   { type: 'mvtc',   path: 'A', sources: ['xfmr_a', 'genset_a'],   targets: ['mv_swgr_a'],
                primary: 'xfmr_a', secondary: 'genset_a' },
    // 13.8 kV MV main switchgear, then 8 unit substations 13.8 kV / 480 V
    // (one per UPS block; site model v2: mv_swgr_a, unit_sub_a_01..08)
    mv_swgr_a: { type: 'swgr',   path: 'A', sources: ['mvtc_a'],              targets: ['usub_a'] },
    usub_a:   { type: 'xfmr',   path: 'A', sources: ['mv_swgr_a'],           targets: ['ups_a'] },
    batt_a:   { type: 'batt',   path: 'A', sources: [],                        targets: ['ups_a'] },
    // UPS bank: 8 x Trinergy 2500 kW (site model v2: ups_a_01..08)
    ups_a:    { type: 'ups',    path: 'A', sources: ['usub_a'],                targets: ['rpp_a1'], battery: 'batt_a',
                units: PHASE1.ups.units, unitKw: PHASE1.ups.unitKw, floorKw: PHASE1.ups.floorKw },
    rpp_a1:   { type: 'rpp',    path: 'A', sources: ['ups_a'],                 targets: ['rpp_a2'] },
    rpp_a2:   { type: 'rpp',    path: 'A', sources: ['rpp_a1'],                targets: ['busway_a'] },
    busway_a: { type: 'busway', path: 'A', sources: ['rpp_a2'],                targets: ['ddu_a1', 'ddu_a2', 'ddu_a3', 'ddu_a4', 'ddu_a5', 'ddu_a6'] },
    ddu_a1:   { type: 'ddu',    path: 'A', sources: ['busway_a'],              targets: [] },
    ddu_a2:   { type: 'ddu',    path: 'A', sources: ['busway_a'],              targets: [] },
    ddu_a3:   { type: 'ddu',    path: 'A', sources: ['busway_a'],              targets: [] },
    ddu_a4:   { type: 'ddu',    path: 'A', sources: ['busway_a'],              targets: [] },
    ddu_a5:   { type: 'ddu',    path: 'A', sources: ['busway_a'],              targets: [] },
    ddu_a6:   { type: 'ddu',    path: 'A', sources: ['busway_a'],              targets: [] },
    // 6 representative DDUs per busway (118 GB200 racks in Path C2).
    // Path B -- closed Phase 1 design (DC-EPMS-068, config/power_plant.yml)
    util_b:   { type: 'util',   path: 'B', sources: [],                        targets: ['xfmr_b'] },
    // utility transformer 27.5 / 13.8 kV (site model v2: mv_xfmr_b)
    xfmr_b:   { type: 'xfmr',   path: 'B', sources: ['util_b'],                targets: ['mvtc_b'] },
    // generator bus: 9 x 2.75 MW at 13.8 kV (site model v2: genset_b_01..09)
    genset_b: { type: 'genset', path: 'B', sources: [],                        targets: ['mvtc_b'],
                units: PHASE1.gen.units, unitKw: PHASE1.gen.unitKw, floorKw: PHASE1.gen.floorKw },
    mvtc_b:   { type: 'mvtc',   path: 'B', sources: ['xfmr_b', 'genset_b'],   targets: ['mv_swgr_b'],
                primary: 'xfmr_b', secondary: 'genset_b' },
    // 13.8 kV MV main switchgear, then 8 unit substations 13.8 kV / 480 V
    // (one per UPS block; site model v2: mv_swgr_b, unit_sub_b_01..08)
    mv_swgr_b: { type: 'swgr',   path: 'B', sources: ['mvtc_b'],              targets: ['usub_b'] },
    usub_b:   { type: 'xfmr',   path: 'B', sources: ['mv_swgr_b'],           targets: ['ups_b'] },
    batt_b:   { type: 'batt',   path: 'B', sources: [],                        targets: ['ups_b'] },
    // UPS bank: 8 x Trinergy 2500 kW (site model v2: ups_b_01..08)
    ups_b:    { type: 'ups',    path: 'B', sources: ['usub_b'],                targets: ['rpp_b1'], battery: 'batt_b',
                units: PHASE1.ups.units, unitKw: PHASE1.ups.unitKw, floorKw: PHASE1.ups.floorKw },
    rpp_b1:   { type: 'rpp',    path: 'B', sources: ['ups_b'],                 targets: ['rpp_b2'] },
    rpp_b2:   { type: 'rpp',    path: 'B', sources: ['rpp_b1'],                targets: ['busway_b'] },
    busway_b: { type: 'busway', path: 'B', sources: ['rpp_b2'],                targets: ['ddu_b1', 'ddu_b2', 'ddu_b3', 'ddu_b4', 'ddu_b5', 'ddu_b6'] },
    ddu_b1:   { type: 'ddu',    path: 'B', sources: ['busway_b'],              targets: [] },
    ddu_b2:   { type: 'ddu',    path: 'B', sources: ['busway_b'],              targets: [] },
    ddu_b3:   { type: 'ddu',    path: 'B', sources: ['busway_b'],              targets: [] },
    ddu_b4:   { type: 'ddu',    path: 'B', sources: ['busway_b'],              targets: [] },
    ddu_b5:   { type: 'ddu',    path: 'B', sources: ['busway_b'],              targets: [] },
    ddu_b6:   { type: 'ddu',    path: 'B', sources: ['busway_b'],              targets: [] },

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

/** Transfer devices: the closed-design MV transfer controller (and the
 *  legacy 480 V ATS type, kept so older fixtures still evaluate). */
export function isTransfer(type) { return type === 'mvtc' || type === 'ats'; }

const TRANSFER_IDS = Object.keys(TOPOLOGY).filter((id) => isTransfer(TOPOLOGY[id].type));

// Topological order — utility roots, then conditional sources, then chain.
// Hand-coded (tiny graph, simpler than Kahn's at this scale).
const TOPO_ORDER = [
    'util_a', 'util_b', 'batt_a', 'batt_b', 'genset_a', 'genset_b',
    'xfmr_a', 'xfmr_b',
    'mvtc_a', 'mvtc_b',
    'mv_swgr_a', 'mv_swgr_b',
    'usub_a', 'usub_b',
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
let _atsTransferTimers = { mvtc_a: null, mvtc_b: null };
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
            ats_pos: isTransfer(t.type) ? 'primary' : null,
            // unit banks (UPS blocks / generator sets): how many are out
            units_out: 0,
            capacity_kw: null,
            n_ok: null,
            n1_ok: null,
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

function _unitsIn(t, n) {
    return t.units ? Math.max(0, t.units - (n.units_out || 0)) : 1;
}

// ─── Propagation core ─────────────────────────────────────────────

function _propagate() {
    if (!_grid) return;
    _flow(_grid);

    // Check transfer triggers (mutates state, may schedule timers)
    _maybeTriggerTransfers();
    // Check UPS battery decay (mutates state, schedules 1Hz interval)
    _manageBatteryDecay();

    // Publish full grid state (shallow clone — subscribers see new ref)
    const snapshot = {};
    for (const id of Object.keys(_grid)) snapshot[id] = { ..._grid[id] };
    setState('grid', snapshot);
}

/**
 * DC-EPMS-073: pure energy-flow pass over a grid object. No timers, no
 * automatic transfer, no publish. Used by the engine (on its private
 * grid) and by core/plant_mirror.js (on a copy built from the Power
 * Controls plant).
 */
function _flow(_grid) {
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
            // Generator bus: alive when called AND at least one set is in service.
            n.alive = !!n.running && _unitsIn(t, n) > 0;
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
        else if (isTransfer(t.type)) {
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

            if (t.units && _unitsIn(t, n) === 0) {
                // every block of the bank out of service: no output
                n.alive = false;
                n.on_battery = false;
                n.energized_by = null;
                n.mode = 'off';
            } else if (ats.alive) {
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

    // Unit banks: capacity and N / N+1 against the design floors.
    for (const id of TOPO_ORDER) {
        const t = TOPOLOGY[id];
        if (!t.units) continue;
        const n = _grid[id];
        const cap = n.tripped ? 0 : _unitsIn(t, n) * t.unitKw;
        n.capacity_kw = cap;
        n.n_ok = cap >= t.floorKw;
        n.n1_ok = cap - t.unitKw >= t.floorKw;
    }
}

/**
 * DC-EPMS-073: copy a grid state and run the pure flow pass on it.
 * Never touches the engine's own grid, never schedules timers.
 */
export function propagateStatic(grid) {
    if (!grid) return null;
    const g = {};
    for (const id of Object.keys(TOPOLOGY)) {
        g[id] = grid[id] ? { ...grid[id] } : null;
    }
    for (const id of Object.keys(g)) if (!g[id]) delete g[id];
    _flow(g);
    return g;
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
    for (const atsId of TRANSFER_IDS) {
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
    console.log(`[power_grid] DAG engine initialized: ${n} nodes, ${e} edges (Phase 1 closed design + Building D design)`);
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
        if (isTransfer(n.type)) { n.ats_pos = 'primary'; }
        n.units_out = 0;
        if (n.type === 'ups')    { n.on_battery = false; n.mode = 'double_conversion'; }
    }
    console.log('[power_grid] RESTORE ALL');
    _propagate();
}

/**
 * Take `count` units of a bank out of service (UPS blocks, generator
 * sets). Clamped to [0, units]. Returns false for non-bank nodes.
 * What-If only: this never reaches the plant (ADR-006).
 */
export function setUnitsOut(id, count) {
    if (!_grid || !_grid[id]) return false;
    const t = TOPOLOGY[id];
    if (!t.units) return false;
    const c = Math.max(0, Math.min(t.units, Math.floor(Number(count) || 0)));
    _grid[id].units_out = c;
    console.log(`[power_grid] UNITS OUT -> ${id} = ${c}/${t.units}`);
    _propagate();
    return true;
}

export function getGridState()    { return _grid; }
export function getTopology()     { return TOPOLOGY; }
export function getTopoOrder()    { return TOPO_ORDER.slice(); }

// Convenience: which nodes are currently tripped
export function getTrippedNodes() {
    if (!_grid) return [];
    return Object.values(_grid).filter((n) => n.tripped).map((n) => n.id);
}
