/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — core/contingency.js
 * N-1 Shadow (innovation track) — pure steady-state contingency
 * evaluator over the DAG topologies.
 *
 * The live engines (power_grid / cooling_grid) are singletons with
 * timers and state publication — unusable for silent simulation.
 * This module re-evaluates the SAME topologies as pure functions:
 * no timers, no DOM, no setState. For every single-failure
 * candidate it answers: who is LOST, who survives DEGRADED?
 *
 * HONEST STEADY-STATE RULES (the engineering judgment, stated):
 *   - A genset counts as survival, but DEGRADED — the site is one
 *     further failure from darkness and burning diesel.
 *   - A UPS battery does NOT count as steady-state survival — the
 *     holdup is 5 minutes by design. N-1 SUSTAINED is the question.
 *   - Cooling availability semantics mirror cooling_grid (tower is
 *     the heat-rejection root; chiller/pump pairs are N+1; CDUs 2N).
 *
 * This is STRUCTURAL availability analysis (who has a live feed),
 * not load-flow and not thermodynamics — same honest scope as the
 * What-If DAGs, stated in the UI.
 *
 * Market note: utility EMS run N-1 contingency in separate
 * engineering screens; no datacenter HMI paints it as a living
 * layer on the one-line. That is the point of this module.
 * ════════════════════════════════════════════════════════════════ */

import { TOPOLOGY, getTopoOrder } from './power_grid.js';
import { COOL_TOPOLOGY } from './cooling_grid.js';

// ─── Pure steady-state evaluation: POWER ──────────────────────────
/**
 * Steady-state outcome of the power chain with `tripped` nodes out.
 * Returns Map<nodeId, {alive, energizedBy, degraded}>.
 */
export function steadyStatePower(tripped = new Set()) {
    const out = new Map();
    const isTripped = (id) => tripped.has(id);

    for (const id of getTopoOrder()) {
        const t = TOPOLOGY[id];
        let alive = false;
        let energizedBy = null;

        if (isTripped(id)) {
            out.set(id, { alive: false, energizedBy: null, degraded: false });
            continue;
        }
        if (t.type === 'util') {
            alive = true; energizedBy = 'util';
        } else if (t.type === 'genset' || t.type === 'farm') {
            // Runs iff its merge point will need it (resolved at the
            // ATS / MV rectifier below); provisionally available.
            // Availability != running. The Phase 2 farm follows the
            // same rule — N+2 standby capacity counts as survival,
            // DEGRADED (burning diesel, one failure from darkness).
            alive = true; energizedBy = 'genset';
        } else if (t.type === 'batt') {
            // Finite holdup — NOT steady-state survival. (The Phase 2
            // BESS is a bus-parallel load in this DAG, never a source,
            // so the same doctrine holds structurally.)
            alive = false; energizedBy = null;
        } else if (t.type === 'mvrect') {
            // Solid-state 2-input AC-side merge: utility primary,
            // farm-via-step-up secondary. No transfer gap.
            const primary = out.get(t.primary);
            const secondary = out.get(t.secondary);
            if (primary?.alive) {
                alive = true; energizedBy = primary.energizedBy;
            } else if (secondary?.alive) {
                alive = true; energizedBy = secondary.energizedBy;
            }
        } else if (t.type === 'ats') {
            const primary = out.get(t.primary);
            const secondary = out.get(t.secondary);
            if (primary?.alive) {
                alive = true; energizedBy = primary.energizedBy;
            } else if (secondary?.alive && !isTripped(t.secondary)) {
                alive = true; energizedBy = 'genset';
            }
        } else if (t.type === 'ups') {
            const input = out.get(t.sources[0]);
            if (input?.alive) {
                alive = true; energizedBy = input.energizedBy;
            }
            // else: battery holdup excluded by rule -> lost.
        } else {
            // Passthrough (xfmr, rpp, busway, ddu)
            const liveSrc = t.sources.find((s) => out.get(s)?.alive);
            if (liveSrc) {
                alive = true; energizedBy = out.get(liveSrc).energizedBy;
            }
        }
        out.set(id, { alive, energizedBy, degraded: alive && energizedBy === 'genset' });
    }
    return out;
}

// ─── Pure steady-state evaluation: COOLING ────────────────────────
/** Same contract for the cooling chain (mirrors cooling_grid rules). */
export function steadyStateCooling(tripped = new Set()) {
    const out = new Map();
    const isT = (id) => tripped.has(id);
    const up = (id) => out.get(id)?.alive === true;

    out.set('cooling_tower', { alive: !isT('cooling_tower') });
    const towerUp = up('cooling_tower');
    out.set('chiller_1', { alive: !isT('chiller_1') && towerUp });
    out.set('chiller_2', { alive: !isT('chiller_2') && towerUp });
    const chwUp = up('chiller_1') || up('chiller_2');
    out.set('chwp_1', { alive: !isT('chwp_1') && chwUp });
    out.set('chwp_2', { alive: !isT('chwp_2') && chwUp });
    const flowUp = up('chwp_1') || up('chwp_2');
    out.set('cdu_a', { alive: !isT('cdu_a') && flowUp });
    out.set('cdu_b', { alive: !isT('cdu_b') && flowUp });
    out.set('data_hall', { alive: !isT('data_hall') && (up('cdu_a') || up('cdu_b')) });
    out.set('crah_1', { alive: !isT('crah_1') && chwUp });
    out.set('crah_2', { alive: !isT('crah_2') && chwUp });

    // Peer degradation (redundancy consumed)
    for (const id of Object.keys(COOL_TOPOLOGY)) {
        const n = out.get(id);
        const peers = COOL_TOPOLOGY[id].peers;
        n.degraded = n.alive && peers.length > 0 && peers.every((p) => !up(p));
        n.energizedBy = null;
    }
    return out;
}

// ─── N-1 analysis (one entry per single-failure candidate) ────────
/**
 * @typedef {Object} N1Entry
 * @property {string[]} lost      nodes that go dark (excl. the candidate)
 * @property {string[]} degraded  nodes that survive degraded
 * @property {'ok'|'warning'|'critical'} tone  badge tone
 */

function _diff(baseline, scenario, candidate, isLoad) {
    const lost = [];
    const degraded = [];
    for (const [id, b] of baseline) {
        if (id === candidate) continue;
        const s = scenario.get(id);
        if (b.alive && !s.alive) lost.push(id);
        else if (s.alive && s.degraded && !b.degraded) degraded.push(id);
    }
    // Tone reflects LOAD impact, the metric an operator pays for:
    // a de-energized intermediate component (e.g. the transformer
    // upstream of an ATS riding its genset) is reported in `lost`
    // but does not make the contingency critical by itself.
    const lostLoad = lost.some(isLoad);
    const tone = lostLoad ? 'critical'
        : (lost.length || degraded.length) ? 'warning' : 'ok';
    return { lost, degraded, tone };
}

/** Full power-chain N-1 sweep. Returns Map<candidateId, N1Entry>. */
export function n1Power() {
    const baseline = steadyStatePower();
    // Load = what the operator pays for: Phase 1 rack drops (DDUs)
    // and the Phase 2 GB300 hall.
    const isLoad = (id) => TOPOLOGY[id]?.type === 'ddu' || TOPOLOGY[id]?.type === 'hall';
    const result = new Map();
    for (const id of Object.keys(TOPOLOGY)) {
        // Battery is excluded as a candidate: it is already excluded
        // from steady-state survival, so tripping it changes nothing.
        if (TOPOLOGY[id].type === 'batt') continue;
        result.set(id, _diff(baseline, steadyStatePower(new Set([id])), id, isLoad));
    }
    return result;
}

/** Full cooling-chain N-1 sweep. */
export function n1Cooling() {
    const baseline = steadyStateCooling();
    const isLoad = (id) => COOL_TOPOLOGY[id]?.type === 'hall';   // the IT hall
    const result = new Map();
    for (const id of Object.keys(COOL_TOPOLOGY)) {
        result.set(id, _diff(baseline, steadyStateCooling(new Set([id])), id, isLoad));
    }
    return result;
}
