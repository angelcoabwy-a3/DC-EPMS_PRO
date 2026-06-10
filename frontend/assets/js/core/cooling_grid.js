/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — frontend/assets/js/core/cooling_grid.js
 * Diagram Rebuild Batch 2 — Cooling Availability Engine.
 *
 * Pure DAG, no DOM — the hydraulic sibling of power_grid.js, so the
 * What-If sandbox finally has ONE semantic across the SLD views
 * (before this module the Cooling What-If was a cosmetic colour
 * toggle that simulated nothing).
 *
 * HONEST SCOPE: this is a simplified AVAILABILITY model (who still
 * has chilled water), not thermodynamics. Approach temperatures,
 * COP shifts and GPU Tj excursions remain the backend physics
 * engine's job (/api/topology/whatif — the Topology view). The DAG
 * answers one question instantly and locally: if I trip this, who
 * loses cooling?
 *
 * Semantics:
 *   - cooling_tower: heat-rejection root. Dead -> chillers cannot
 *     reject heat -> chiller outputs die (high head pressure trip).
 *   - chiller_1 / chiller_2: N+1 pair. Either one alone carries the
 *     full chilled-water header.
 *   - chwp_1 / chwp_2: CHW pump pair on the shared header — either
 *     one maintains flow.
 *   - cdu_a / cdu_b: 2N liquid-cooling distribution; each needs
 *     header flow (any live pump).
 *   - data_hall: alive while ANY CDU delivers DLC flow.
 *   - crah_1 / crah_2: air-side trim; need a live chiller.
 *
 * Peer-degradation: when one half of a redundant pair is dead, the
 * surviving peer reports degraded=true — redundancy is consumed, an
 * operator must know even though nothing is down yet.
 *
 * State published via state.js setState('coolgrid', ...). Ref:
 * ASHRAE 90.4 (mechanical load), Uptime Tier IV concurrent
 * maintainability (the N+1/2N pairs being modeled).
 * ════════════════════════════════════════════════════════════════ */

import { setState } from './state.js';

// ─── Topology — 10 nodes, redundancy pairs declared explicitly ───
export const COOL_TOPOLOGY = {
    cooling_tower: { type: 'tower',   peers: [] },
    chiller_1:     { type: 'chiller', peers: ['chiller_2'] },
    chiller_2:     { type: 'chiller', peers: ['chiller_1'] },
    chwp_1:        { type: 'pump',    peers: ['chwp_2'] },
    chwp_2:        { type: 'pump',    peers: ['chwp_1'] },
    cdu_a:         { type: 'cdu',     peers: ['cdu_b'] },
    cdu_b:         { type: 'cdu',     peers: ['cdu_a'] },
    data_hall:     { type: 'hall',    peers: [] },
    crah_1:        { type: 'crah',    peers: ['crah_2'] },
    crah_2:        { type: 'crah',    peers: ['crah_1'] },
};

let _grid = null;

function _initGrid() {
    _grid = {};
    for (const id of Object.keys(COOL_TOPOLOGY)) {
        _grid[id] = {
            id,
            type: COOL_TOPOLOGY[id].type,
            tripped: false,
            alive: true,
            degraded: false,   // surviving peer of a dead redundant pair
        };
    }
}

// ─── Propagation (pure availability cascade) ──────────────────────
function _propagate() {
    if (!_grid) return;
    const g = _grid;
    const up = (n) => !n.tripped && n.alive;

    // Roots + chain, in dependency order.
    g.cooling_tower.alive = !g.cooling_tower.tripped;

    const towerUp = up(g.cooling_tower);
    g.chiller_1.alive = !g.chiller_1.tripped && towerUp;
    g.chiller_2.alive = !g.chiller_2.tripped && towerUp;
    const chwUp = up(g.chiller_1) || up(g.chiller_2);

    g.chwp_1.alive = !g.chwp_1.tripped && chwUp;
    g.chwp_2.alive = !g.chwp_2.tripped && chwUp;
    const flowUp = up(g.chwp_1) || up(g.chwp_2);

    g.cdu_a.alive = !g.cdu_a.tripped && flowUp;
    g.cdu_b.alive = !g.cdu_b.tripped && flowUp;

    g.data_hall.alive = !g.data_hall.tripped && (up(g.cdu_a) || up(g.cdu_b));
    g.crah_1.alive = !g.crah_1.tripped && chwUp;
    g.crah_2.alive = !g.crah_2.tripped && chwUp;

    // Peer-degradation: redundancy consumed but load still served.
    for (const id of Object.keys(COOL_TOPOLOGY)) {
        const n = g[id];
        const peers = COOL_TOPOLOGY[id].peers;
        n.degraded = n.alive && peers.length > 0
            && peers.every((p) => !up(g[p]));
    }

    // Publish a snapshot (new refs so subscribers see the change).
    const snapshot = {};
    for (const id of Object.keys(g)) snapshot[id] = { ...g[id] };
    setState('coolgrid', snapshot);
    return snapshot;
}

// ─── Public API (mirrors power_grid.js) ───────────────────────────
export function initCoolingGrid() {
    _initGrid();
    _propagate();
    console.log('[cooling_grid] availability DAG initialized: 10 nodes');
}

export function tripNode(id) {
    if (!_grid || !_grid[id] || _grid[id].tripped) return false;
    _grid[id].tripped = true;
    _propagate();
    return true;
}

export function restoreNode(id) {
    if (!_grid || !_grid[id] || !_grid[id].tripped) return false;
    _grid[id].tripped = false;
    _propagate();
    return true;
}

export function toggleTrip(id) {
    if (!_grid || !_grid[id]) return false;
    return _grid[id].tripped ? restoreNode(id) : tripNode(id);
}

export function restoreAll() {
    if (!_grid) return;
    for (const id of Object.keys(_grid)) _grid[id].tripped = false;
    _propagate();
}

export function getGridState() { return _grid; }
