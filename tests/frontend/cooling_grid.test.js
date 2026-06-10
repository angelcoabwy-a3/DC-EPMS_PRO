/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/cooling_grid.test.js
 * Diagram Rebuild Batch 2 — cooling availability DAG engine.
 *
 * Pure engine, no DOM. The hydraulic sibling of power_grid.js: one
 * What-If semantic across the SLD views. Honest scope asserted:
 * availability only (who still has chilled water), not
 * thermodynamics.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, beforeEach } from 'vitest';

import {
    COOL_TOPOLOGY, initCoolingGrid, tripNode, restoreNode, toggleTrip,
    restoreAll, getGridState,
} from '/assets/js/core/cooling_grid.js';
import { subscribe } from '/assets/js/core/state.js';

beforeEach(() => {
    initCoolingGrid();
});

describe('B2 — cooling_grid availability DAG', () => {
    it('initializes the 10-node chain fully alive, nothing degraded', () => {
        const g = getGridState();
        expect(Object.keys(g)).toHaveLength(10);
        for (const id of Object.keys(COOL_TOPOLOGY)) {
            expect(g[id].alive).toBe(true);
            expect(g[id].degraded).toBe(false);
        }
    });

    it('tripping one chiller consumes N+1: peer degraded, load still served', () => {
        tripNode('chiller_1');
        const g = getGridState();
        expect(g.chiller_1.alive).toBe(false);
        expect(g.chiller_2.alive).toBe(true);
        expect(g.chiller_2.degraded).toBe(true);   // redundancy consumed
        // Downstream keeps chilled water — N+1 did its job.
        expect(g.chwp_1.alive).toBe(true);
        expect(g.cdu_a.alive).toBe(true);
        expect(g.data_hall.alive).toBe(true);
    });

    it('tripping BOTH chillers cascades: pumps, CDUs, hall, CRAHs all lose cooling', () => {
        tripNode('chiller_1');
        tripNode('chiller_2');
        const g = getGridState();
        expect(g.chwp_1.alive).toBe(false);
        expect(g.chwp_2.alive).toBe(false);
        expect(g.cdu_a.alive).toBe(false);
        expect(g.cdu_b.alive).toBe(false);
        expect(g.data_hall.alive).toBe(false);
        expect(g.crah_1.alive).toBe(false);
    });

    it('tripping the cooling tower kills heat rejection for the whole chain', () => {
        tripNode('cooling_tower');
        const g = getGridState();
        expect(g.chiller_1.alive).toBe(false);
        expect(g.chiller_2.alive).toBe(false);
        expect(g.data_hall.alive).toBe(false);
    });

    it('tripping one CDU leaves the hall served by its 2N peer (degraded)', () => {
        tripNode('cdu_a');
        const g = getGridState();
        expect(g.cdu_a.alive).toBe(false);
        expect(g.cdu_b.alive).toBe(true);
        expect(g.cdu_b.degraded).toBe(true);
        expect(g.data_hall.alive).toBe(true);
    });

    it('toggleTrip toggles; restoreAll returns to nominal', () => {
        toggleTrip('chwp_1');
        expect(getGridState().chwp_1.tripped).toBe(true);
        toggleTrip('chwp_1');
        expect(getGridState().chwp_1.tripped).toBe(false);
        tripNode('chiller_1');
        tripNode('cdu_b');
        restoreAll();
        const g = getGridState();
        for (const id of Object.keys(COOL_TOPOLOGY)) {
            expect(g[id].alive).toBe(true);
            expect(g[id].degraded).toBe(false);
        }
    });

    it('restoreNode only acts on tripped nodes; unknown ids are safe no-ops', () => {
        expect(restoreNode('chiller_1')).toBe(false);   // not tripped
        expect(tripNode('definitely_not_a_node')).toBe(false);
        expect(toggleTrip('nope')).toBe(false);
    });

    it('publishes every propagation as a coolgrid state snapshot', () => {
        let seen = null;
        const unsub = subscribe('coolgrid', (snap) => { seen = snap; });
        tripNode('chiller_1');
        unsub();
        expect(seen).not.toBeNull();
        expect(seen.chiller_1.alive).toBe(false);
        expect(seen.chiller_2.degraded).toBe(true);
        // Snapshot, not the live ref — engine internals stay private.
        expect(seen.chiller_1).not.toBe(getGridState().chiller_1);
    });
});
