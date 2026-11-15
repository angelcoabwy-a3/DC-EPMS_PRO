/* HMI H4: alarm states (sandbox engine), grid conditions, banner. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
    AlarmEngine, conditionsFromGrid, alarmBannerHtml, UNACK, ACKED, RTNUN, NORM,
} from '/assets/js/core/alarm_state.js';
import { initPowerGrid, tripNode, restoreAll, getGridState, setUnitsOut } from '/assets/js/core/power_grid.js';

const c = (active, id = 'X', priority = 'HIGH') => ({ id, active, priority, message: 'm', source: 's' });

describe('AlarmEngine (mirrors backend/alarm_engine.py)', () => {
    let t; let eng;
    beforeEach(() => { t = 1_763_150_000_000; eng = new AlarmEngine(() => t); });

    it('active -> ack -> clear -> NORM', () => {
        eng.evaluate([c(true)]);
        expect(eng.alarms.get('X').state).toBe(UNACK);
        expect(eng.ack('X')).toBe(true);
        expect(eng.alarms.get('X').state).toBe(ACKED);
        eng.evaluate([c(false)]);
        expect(eng.alarms.get('X').state).toBe(NORM);
    });
    it('clear before ack -> RTNUN, ack -> NORM, reactivation counts', () => {
        eng.evaluate([c(true)]);
        eng.evaluate([]);
        expect(eng.alarms.get('X').state).toBe(RTNUN);
        eng.evaluate([c(true)]);
        expect(eng.alarms.get('X').occurrences).toBe(2);
        eng.evaluate([c(false)]);
        eng.ack('X');
        expect(eng.alarms.get('X').state).toBe(NORM);
        expect(eng.ack('X')).toBe(false);
    });
    it('ms timestamps and sort: priority, then unacked first', () => {
        eng.evaluate([c(true, 'L', 'LOW'), c(true, 'H1'), c(true, 'H2')]);
        t += 250;
        eng.ack('H1');
        const s = eng.snapshot();
        expect(s.alarms.map((a) => a.id)).toEqual(['H2', 'H1', 'L']);
        expect(s.alarms[1].acked).toMatch(/\.250Z$/);
        expect(s.unacked).toBe(2);
    });
    it('rejects unknown priorities', () => {
        expect(() => eng.evaluate([c(true, 'X', 'URGENT')])).toThrow(/unknown priority/);
    });
});

describe('conditionsFromGrid (What-If DAG)', () => {
    beforeEach(() => { vi.useFakeTimers(); initPowerGrid(); });
    afterEach(() => { restoreAll(); vi.useRealTimers(); });
    const active = (g) => conditionsFromGrid(g).filter((x) => x.active).map((x) => x.id).sort();

    it('healthy plant: nothing active', () => {
        expect(active(getGridState())).toEqual([]);
    });
    it('utility loss: utility lost + on battery, then on generators', () => {
        tripNode('util_a');
        expect(active(getGridState())).toEqual(['PATH_A_ON_BATTERY', 'PATH_A_UTILITY_LOST']);
        vi.advanceTimersByTime(2000);
        expect(active(getGridState())).toEqual(['PATH_A_ON_GENERATORS', 'PATH_A_UTILITY_LOST']);
    });
    it('UPS blocks out: N+1 lost is MEDIUM, below N is HIGH', () => {
        setUnitsOut('ups_b', 1);
        const n1 = conditionsFromGrid(getGridState()).find((x) => x.id === 'PATH_B_UPS_N1_LOST');
        expect(n1.active).toBe(true);
        expect(n1.priority).toBe('MEDIUM');
        setUnitsOut('ups_b', 2);
        expect(active(getGridState())).toEqual(['PATH_B_UPS_N_LOST']);
    });
});

describe('alarmBannerHtml', () => {
    const snap = (alarms) => ({ alarms, unacked: alarms.filter((a) => a.state === 'UNACK').length });
    it('empty live banner', () => {
        const h = alarmBannerHtml(snap([]), { source: 'live' });
        expect(h).toContain('LIVE PLANT');
        expect(h).toContain('No active alarms');
        expect(h).not.toContain('ACK ALL');
    });
    it('rows carry priority, state, ACK button and escape the text', () => {
        const h = alarmBannerHtml(snap([{
            id: 'A<1>', priority: 'HIGH', state: 'UNACK', message: '<img src=x>',
            activated: '2026-11-15T02:00:00.123Z',
        }]), { source: 'sandbox' });
        expect(h).toContain('SANDBOX');
        expect(h).toContain('data-prio="HIGH"');
        expect(h).toContain('ACK ALL');
        expect(h).toContain('&lt;img src=x&gt;');
        expect(h).not.toContain('<img');
        expect(h).toMatch(/\d\d:\d\d:\d\d\.123/);
    });
    it('acked rows show who acknowledged and no ACK button', () => {
        const h = alarmBannerHtml(snap([{
            id: 'B', priority: 'LOW', state: 'ACKED', message: 'm', acked_by: 'manager',
            activated: '2026-11-15T02:00:00.000Z',
        }]), {});
        expect(h).toContain('ACK · manager');
        expect(h).not.toContain('data-ack="B"');
    });
    it('caps rows and shows the error line', () => {
        const many = Array.from({ length: 7 }, (_, i) => ({ id: 'a' + i, priority: 'LOW', state: 'UNACK', message: 'm' }));
        const h = alarmBannerHtml(snap(many), { error: 'Live alarms unavailable: HTTP 503' });
        expect(h).toContain('+2 more');
        expect(h).toContain('Live alarms unavailable');
    });
});
