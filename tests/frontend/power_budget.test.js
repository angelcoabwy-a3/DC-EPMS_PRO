/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/power_budget.test.js
 * 50 MW track — Building D energy budget + genset farm sizing.
 * Pure math: the single source of truth every diagram prints.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect } from 'vitest';

import {
    PHASE2_DEFAULTS, phase2Budget, gensetFarmSizing, budgetCaption,
} from '/assets/js/core/power_budget.js';

describe('50MW — phase2Budget()', () => {
    it('builds the budget on the 50 MW IT design load', () => {
        const b = phase2Budget();
        expect(b.it).toBe(50);
        // Components are individually sane…
        expect(b.chillers).toBeCloseTo(50 / 6, 5);          // heat / COP
        expect(b.rectifierLoss).toBeCloseTo(50 / 0.985 - 50, 5);
        expect(b.dcDistLoss).toBeCloseTo(0.25, 5);
        expect(b.heatDlc).toBeCloseTo(42.5, 5);             // 85 % DLC
        expect(b.heatAir).toBeCloseTo(7.5, 5);
        expect(b.crahFans).toBeCloseTo(0.75, 5);            // 10 % of air heat
        // …and the total is exactly their sum (no hidden terms).
        const sum = b.it + b.rectifierLoss + b.dcDistLoss + b.chillers
            + b.pumps + b.towerFans + b.crahFans + b.aux;
        expect(b.totalFacility).toBeCloseTo(sum, 9);
    });

    it('PUE is total/IT and lands in the honest design band (~1.2)', () => {
        const b = phase2Budget();
        expect(b.pue).toBeCloseTo(b.totalFacility / b.it, 9);
        expect(b.pue).toBeGreaterThan(1.15);
        expect(b.pue).toBeLessThan(1.30);
    });

    it('the model coordinates: better chillers (higher COP) -> lower PUE', () => {
        const base = phase2Budget();
        const better = phase2Budget({ chillerCop: 8 });
        const worse = phase2Budget({ chillerCop: 4 });
        expect(better.pue).toBeLessThan(base.pue);
        expect(worse.pue).toBeGreaterThan(base.pue);
        // More DLC fraction -> less CRAH fan power.
        expect(phase2Budget({ dlcFraction: 0.95 }).crahFans)
            .toBeLessThan(base.crahFans);
    });
});

describe('50MW — gensetFarmSizing()', () => {
    it('sizes the N+2 farm for the FULL facility load (not just IT)', () => {
        const s = gensetFarmSizing();
        const b = phase2Budget();
        expect(s.unitMw).toBe(PHASE2_DEFAULTS.gensetUnitMw);
        expect(s.required).toBe(Math.ceil(b.totalFacility / s.unitMw));
        expect(s.installed).toBe(s.required + 2);            // N+2
        expect(s.farmMw).toBeCloseTo(s.installed * s.unitMw, 9);
        // The farm must actually cover the load with margin.
        expect(s.farmMw).toBeGreaterThan(b.totalFacility);
    });
});

describe('50MW — budgetCaption()', () => {
    it('prints every component + PUE from the same numbers', () => {
        const c = budgetCaption();
        const b = phase2Budget();
        expect(c).toContain(`IT ${b.it.toFixed(1)} MW`);
        expect(c).toContain('chillers');
        expect(c).toContain('tower fans');
        expect(c).toContain(`PUE ${b.pue.toFixed(2)}`);
        expect(c).toContain(`TOTAL ${b.totalFacility.toFixed(1)} MW`);
    });
});
