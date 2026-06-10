/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/power_grid.test.js
 * Diagram Rebuild Batch 5 — the electrical DAG engine gets test
 * coverage (it had none), including the NEW genset NFPA 110 start
 * sequence and the UPS IEC 62040-3 operating-mode field.
 *
 * Fake timers drive the ATS 2 s transfer gap, the 0.8 s genset
 * crank, the 1.2 s cooldown and the 1 %/s battery decay.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import {
    initPowerGrid, tripNode, restoreNode, restoreAll, getGridState,
} from '/assets/js/core/power_grid.js';

beforeEach(() => {
    vi.useFakeTimers();
    initPowerGrid();
});

afterEach(() => {
    restoreAll();
    vi.useRealTimers();
});

describe('B5 — power_grid genset NFPA 110 sequence', () => {
    it('utility loss starts the sequence: ATS in transfer, genset CRANKING', () => {
        tripNode('util_a');
        const g = getGridState();
        expect(g.ats_a.transferring).toBe(true);
        expect(g.genset_a.state).toBe('cranking');
        expect(g.genset_a.running).toBe(false);
        // UPS rides the gap on battery (IEC 62040-3 battery mode).
        expect(g.ups_a.on_battery).toBe(true);
        expect(g.ups_a.mode).toBe('battery');
        expect(g.ups_a.alive).toBe(true);   // load never drops
    });

    it('crank completes at 0.8 s; ATS closes onto the genset at 2 s', () => {
        tripNode('util_a');
        vi.advanceTimersByTime(800);
        let g = getGridState();
        expect(g.genset_a.state).toBe('running');
        expect(g.genset_a.running).toBe(true);
        expect(g.ats_a.transferring).toBe(true);   // still inside the gap

        vi.advanceTimersByTime(1200);   // t = 2.0 s
        g = getGridState();
        expect(g.ats_a.transferring).toBe(false);
        expect(g.ats_a.ats_pos).toBe('secondary');
        expect(g.ats_a.alive).toBe(true);
        expect(g.ups_a.on_battery).toBe(false);
        expect(g.ups_a.mode).toBe('double_conversion');
        expect(g.ups_a.energized_by).toBe('genset');
        expect(g.rpp_a1.energized_by).toBe('genset');
    });

    it('utility restoration back-transfers and runs the genset COOLDOWN', () => {
        tripNode('util_a');
        vi.advanceTimersByTime(2000);    // on genset
        restoreNode('util_a');
        vi.advanceTimersByTime(1500);    // back-transfer completes
        let g = getGridState();
        expect(g.ats_a.ats_pos).toBe('primary');
        expect(g.genset_a.running).toBe(false);
        expect(g.genset_a.state).toBe('cooldown');

        vi.advanceTimersByTime(1200);    // cooldown elapses
        g = getGridState();
        expect(g.genset_a.state).toBe('standby');
        expect(g.ups_a.energized_by).toBe('util');
    });

    it('a tripped genset never leaves standby (start inhibited)', () => {
        tripNode('genset_a');
        tripNode('util_a');
        vi.advanceTimersByTime(3000);
        const g = getGridState();
        expect(g.genset_a.running).toBe(false);
        expect(g.genset_a.alive).toBe(false);
        // UPS carries the load on battery — the only thing left.
        expect(g.ups_a.on_battery).toBe(true);
    });
});

describe('B5 — power_grid UPS battery holdup + decay', () => {
    it('decays SOC at 1 %/s while on battery and recovers mode on restore', () => {
        tripNode('ats_a');               // ATS dead -> UPS on battery for good
        let g = getGridState();
        expect(g.ups_a.mode).toBe('battery');
        vi.advanceTimersByTime(3000);
        g = getGridState();
        expect(g.batt_a.soc).toBe(97);
        restoreNode('ats_a');
        g = getGridState();
        expect(g.ups_a.mode).toBe('double_conversion');
        expect(g.ups_a.on_battery).toBe(false);
    });

    it('UPS goes dark (mode off) when the battery is exhausted', () => {
        tripNode('ats_a');
        tripNode('batt_a');
        const g = getGridState();
        expect(g.ups_a.alive).toBe(false);
        expect(g.ups_a.mode).toBe('off');
        expect(g.rpp_a1.alive).toBe(false);   // cascade reaches the load
    });

    it('restoreAll returns gensets to standby and UPS to double conversion', () => {
        tripNode('util_a');
        vi.advanceTimersByTime(2000);
        restoreAll();
        const g = getGridState();
        expect(g.genset_a.state).toBe('standby');
        expect(g.ups_a.mode).toBe('double_conversion');
        expect(g.batt_a.soc).toBe(100);
        expect(g.ats_a.ats_pos).toBe('primary');
    });
});
