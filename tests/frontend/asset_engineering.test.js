/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/asset_engineering.test.js
 * Diagram Rebuild Batch 5 — per-asset engineering detail sections.
 *
 * Pure module: state helpers (IEC 62040-3 UPS modes, NFPA 110
 * genset phases, runtime/voltage/loading math) + section markup
 * (mimic hooks, phase strips, design spec sheets, vocabulary
 * fence on the Phase 2 entries).
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect } from 'vitest';

import {
    upsMode, gensetPhase, runtimeMinutes, battStringVoltage,
    xfmrLoadingPct, engineeringSection,
} from '/assets/js/core/asset_engineering.js';
import { getAssetMeta } from '/assets/js/core/asset_metadata.js';

// ════════════════════════════════════════════════════════════════
//  Pure state helpers
// ════════════════════════════════════════════════════════════════
describe('B5 — asset_engineering state helpers', () => {
    it('upsMode maps grid state to IEC 62040-3 modes', () => {
        expect(upsMode(null)).toBe('unknown');
        expect(upsMode({ tripped: true })).toBe('off');
        expect(upsMode({ alive: false })).toBe('off');
        expect(upsMode({ alive: true, on_battery: true })).toBe('battery');
        expect(upsMode({ alive: true, mode: 'double_conversion' })).toBe('double_conversion');
    });

    it('gensetPhase walks the NFPA 110 sequence incl. ON LOAD via its ATS', () => {
        expect(gensetPhase({ state: 'standby', running: false })).toBe('standby');
        expect(gensetPhase({ state: 'cranking', running: false })).toBe('cranking');
        expect(gensetPhase({ state: 'running', running: true })).toBe('running');
        expect(gensetPhase(
            { state: 'running', running: true },
            { ats_pos: 'secondary', alive: true },
        )).toBe('on_load');
        expect(gensetPhase({ state: 'cooldown', running: false })).toBe('cooldown');
        expect(gensetPhase({ tripped: true })).toBe('off');
    });

    it('runtime / voltage / loading math behaves and clamps', () => {
        expect(runtimeMinutes(100)).toBe(5);
        expect(runtimeMinutes(50)).toBe(2.5);
        expect(runtimeMinutes(-10)).toBe(0);
        expect(battStringVoltage(100)).toBe(540);
        expect(battStringVoltage(0)).toBe(480);
        expect(xfmrLoadingPct(1250)).toBe(50);
        expect(xfmrLoadingPct(10000)).toBe(150);   // clamp
        expect(xfmrLoadingPct(0)).toBe(0);
    });
});

// ════════════════════════════════════════════════════════════════
//  UPS section — modes + internal power-path mimic
// ════════════════════════════════════════════════════════════════
describe('B5 — UPS engineering section', () => {
    it('renders the IEC 62040-3 chips with double conversion active', () => {
        const grid = {
            ups_a: { alive: true, mode: 'double_conversion' },
            batt_a: { soc: 100 },
        };
        const html = engineeringSection('ups_a', grid, {});
        expect(html).toContain('IEC 62040-3');
        expect(html).toContain('VFI-SS-111');
        expect(html).toMatch(/eng-chip-active[^>]*data-mode="double_conversion"/);
        // Non-modeled modes are present but honestly dimmed.
        expect(html).toMatch(/eng-chip-dim[^>]*data-mode="econversion"/);
        expect(html).toContain('not modeled in sim');
    });

    it('battery mode lights the BATT->DC->INV path and the SOC bar follows', () => {
        const grid = {
            ups_a: { alive: true, on_battery: true, mode: 'battery' },
            batt_a: { soc: 42 },
        };
        const html = engineeringSection('ups_a', grid, {});
        expect(html).toMatch(/eng-chip-active[^>]*data-mode="battery"/);
        expect(html).toContain('eng-batt eng-on');
        expect(html).toContain('42 %');
    });
});

// ════════════════════════════════════════════════════════════════
//  Genset section — NFPA 110 phase strip + readouts
// ════════════════════════════════════════════════════════════════
describe('B5 — genset engineering section', () => {
    it('highlights CRANKING with mid-spool readouts', () => {
        const grid = { genset_a: { state: 'cranking', running: false }, ats_a: {} };
        const html = engineeringSection('genset_a', grid, {});
        expect(html).toContain('NFPA 110 TYPE 10');
        expect(html).toMatch(/eng-phase-active[^>]*data-phase="cranking"/);
        expect(html).toContain('<strong>900</strong>');     // rpm mid-spool
        expect(html).toContain('Sim-derived');               // honesty footer
    });

    it('ON LOAD when running and its ATS sits on the emergency source', () => {
        const grid = {
            genset_b: { state: 'running', running: true },
            ats_b: { ats_pos: 'secondary', alive: true },
        };
        const html = engineeringSection('genset_b', grid, {});
        expect(html).toMatch(/eng-phase-active[^>]*data-phase="on_load"/);
        expect(html).toContain('60 Hz');
    });
});

// ════════════════════════════════════════════════════════════════
//  ATS / battery sections
// ════════════════════════════════════════════════════════════════
describe('B5 — ATS + battery sections', () => {
    it('ATS shows the load gap warning during an open transition', () => {
        const html = engineeringSection('ats_a', { ats_a: { transferring: true } }, {});
        expect(html).toContain('IN TRANSFER');
        expect(html).toContain('Load gap');
    });

    it('battery section computes runtime and string voltage from SOC', () => {
        const html = engineeringSection('batt_a', { batt_a: { soc: 50 } }, {});
        expect(html).toContain('IEEE 1188');
        expect(html).toContain('2.5 min');
        expect(html).toContain('510 V');
    });

    it('unmapped asset types return an empty section', () => {
        expect(engineeringSection('busway_a', {}, {})).toBe('');
    });
});

// ════════════════════════════════════════════════════════════════
//  Phase 2 design assets — spec sheets + vocabulary fence
// ════════════════════════════════════════════════════════════════
describe('B5 — Phase 2 design sections + metadata', () => {
    it('Phase 2 ids render the DESIGN badge instead of live state', () => {
        for (const id of ['mv_rect_d', 'sscb_d', 'dc_bus_d', 'bess_d']) {
            const html = engineeringSection(id, null, getAssetMeta(id));
            expect(html).toContain('DESIGN · PH2');
            expect(html).toContain('no live telemetry');
        }
    });

    it('S-VOCAB-01 — DC-side design entries never carry phase vocabulary', () => {
        const html = engineeringSection('dc_bus_d', null, getAssetMeta('dc_bus_d'));
        expect(html).toContain('UNIPOLAR TN-S');
        for (const id of ['mv_rect_d', 'sscb_d', 'dc_bus_d', 'bess_d', 'rpp_d1', 'rpp_d2']) {
            const meta = getAssetMeta(id);
            expect(meta).not.toBeNull();
            expect(meta.design).toBe(true);
            const flat = JSON.stringify([meta.label, meta.rating]).toLowerCase();
            expect(flat).not.toMatch(/trif|three-phase|3-phase/);
        }
    });

    it('SSCB metadata states the IEC 60947-2 clearing class', () => {
        expect(getAssetMeta('sscb_d').rating).toContain('IEC 60947-2');
        expect(getAssetMeta('sscb_d').rating).toContain('1-100 µs');
    });
});
