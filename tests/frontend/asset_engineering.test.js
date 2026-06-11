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
    xfmrLoadingPct, engineeringSection, upsBreakerStates,
    parseQTags, qMismatches,
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

    it('Galaxy one-line carries the full Q-breaker discipline (Q1..Q5)', () => {
        const grid = { ups_a: { alive: true, mode: 'double_conversion' }, batt_a: { soc: 100 } };
        const html = engineeringSection('ups_a', grid, {});
        for (const q of ['Q1', 'Q2', 'Q3', 'Q4', 'Q5']) {
            expect(html).toContain(`data-q="${q}"`);
        }
        expect(html).toContain('IGBT · THDi&lt;3%');
        expect(html).toContain('SCR antiparalelo · 0 ms');
        expect(html).toContain('PWM · ±1%');
        expect(html).toContain('MBP · EXTERNAL PANEL · Castell interlock');
        // The SSM is the common output junction (inverter + bypass legs).
        expect(html).toContain('>SSM<');
        // MOP switching discipline footer incl. the Q4 step.
        expect(html).toContain('MBP transfer (MOP-UPS-001)');
        expect(html).toContain('close Q3 → open Q4');
        // Honest origin: without BMS tags, positions are mode-nominal.
        expect(html).toContain('Q-state tags unavailable');
    });

    it('breaker POSITION is distinct from path ENERGIZATION (battery mode)', () => {
        const grid = {
            ups_a: { alive: true, on_battery: true, mode: 'battery' },
            batt_a: { soc: 60 },
        };
        const html = engineeringSection('ups_a', grid, {});
        // Q1 stays CLOSED — the input is dead, the breaker did not open…
        expect(html).toMatch(/data-q="Q1" data-pos="closed"/);
        // …and therefore its glyph is NOT energized.
        expect(html).not.toMatch(/eng-q eng-on[^>]*data-q="Q1"/);
        // Q5 carries the discharge: closed AND energized.
        expect(html).toMatch(/class="eng-q eng-on[^"]*" data-q="Q5" data-pos="closed"/);
    });

    it('upsBreakerStates: maintenance bypass isolates the UPS (Q3 in, rest out)', () => {
        expect(upsBreakerStates('maint_bypass')).toEqual(
            { Q1: 'open', Q2: 'open', Q3: 'closed', Q4: 'open', Q5: 'open' });
        expect(upsBreakerStates('double_conversion')).toEqual(
            { Q1: 'closed', Q2: 'closed', Q3: 'open', Q4: 'closed', Q5: 'closed' });
        expect(upsBreakerStates('battery').Q1).toBe('closed');
    });

    it('normal mode shows the battery float-charging trickle via Q5', () => {
        const grid = { ups_a: { alive: true, mode: 'double_conversion' }, batt_a: { soc: 100 } };
        const html = engineeringSection('ups_a', grid, {});
        expect(html).toContain('eng-charge');
    });
});

// ════════════════════════════════════════════════════════════════
//  Q-state track — live BMS positions vs mode-nominal lineup
// ════════════════════════════════════════════════════════════════
describe('B-Q — Q-state tags, mismatch detection', () => {
    const TAGS = [
        { id: 'PWR.UPS_A.Q1_POS', current_value: 'Closed' },
        { id: 'PWR.UPS_A.Q2_POS', current_value: 'Closed' },
        { id: 'PWR.UPS_A.Q3_POS', current_value: 'Closed' },   // <- left bridged!
        { id: 'PWR.UPS_A.Q4_POS', current_value: 'Closed' },
        { id: 'PWR.UPS_A.Q5_POS', current_value: 'Open' },     // <- batt isolated!
        { id: 'PWR.UPS_B.Q1_POS', current_value: 'Closed' },
        { id: 'PWR.UPS_A.BATTERY_SOC', current_value: 100 },   // non-Q noise
    ];

    it('parseQTags maps the tag rows of ONE ups to a position object', () => {
        expect(parseQTags(TAGS, 'ups_a')).toEqual({
            Q1: 'closed', Q2: 'closed', Q3: 'closed', Q4: 'closed', Q5: 'open',
        });
        expect(parseQTags(TAGS, 'ups_b')).toEqual({ Q1: 'closed' });
        expect(parseQTags([], 'ups_a')).toBeNull();
        expect(parseQTags(null, 'ups_a')).toBeNull();
    });

    it('qMismatches flags the bridged MBP and the isolated battery', () => {
        const q = parseQTags(TAGS, 'ups_a');
        const ms = qMismatches('double_conversion', q);
        expect(ms).toHaveLength(2);
        expect(ms.join(' | ')).toContain('Q3 expected OPEN, reads CLOSED — MBP still bridged?');
        expect(ms.join(' | ')).toContain('Q5 expected CLOSED, reads OPEN — battery isolated: NO holdup');
        // A nominal lineup raises nothing.
        expect(qMismatches('double_conversion',
            upsBreakerStates('double_conversion'))).toHaveLength(0);
        expect(qMismatches('double_conversion', null)).toHaveLength(0);
    });

    it('the section renders ACTUAL positions + the mismatch alarm + rings', () => {
        const grid = { ups_a: { alive: true, mode: 'double_conversion' }, batt_a: { soc: 100 } };
        const html = engineeringSection('ups_a', grid, {},
            { qStates: parseQTags(TAGS, 'ups_a') });
        expect(html).toContain('Q-STATE MISMATCH');
        expect(html).toContain('MBP still bridged?');
        // Actual position wins over nominal in the glyph…
        expect(html).toMatch(/data-q="Q3" data-pos="closed"/);
        // …and the offending breakers carry the alarm ring.
        expect(html).toContain('eng-q-mismatch');
        expect(html).toContain('eng-q-alarm-ring');
        // Origin line now credits the BMS tags.
        expect(html).toContain('Q POSITIONS from BMS tags');
    });

    it('genset section carries the ANSI 25 / dead-bus paralleling note', () => {
        const html = engineeringSection('genset_a',
            { genset_a: { state: 'standby' }, ats_a: {} }, {});
        expect(html).toContain('ANSI 25 sync check');
        expect(html).toContain('dead-bus black-start');
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
