/**
 * T4: printable drill report (core/training_print.js) and protective
 * relay tags (core/relay_tags.js).
 */
import { describe, it, expect } from 'vitest';
import { reportDocument, openPrintable, fmtMs, soeDetail } from '/assets/js/core/training_print.js';
import { relayStates, relayRowSvg, applyRelays, RELAYS } from '/assets/js/core/relay_tags.js';

const REPORT = {
    report: 'DC-EPMS operator training report',
    simulated: true,
    drill: {
        id: 'DRILL-04', version: 3, title: 'Closed <b>transition</b>', summary: 's', path: 'a',
        target_s: 90, time_limit_s: 900,
        steps: [{ id: 'ACK', text: 'Ack' }, { id: 'CLOSE', text: 'Close' }, { id: 'STOP', text: 'Stop' }],
    },
    operator: 'manager<script>',
    started: '2026-11-15T18:25:38.249+00:00',
    ended: '2026-11-15T18:30:57.304+00:00',
    duration_ms: 319055,
    outcome: 'PASS', reason: null, score: 67,
    rubric: { name: 'DC-EPMS training rubric v2', fail: 'f', violation: 'v', violation_penalty: 10, late_penalty_per_10_s: 1 },
    steps: [{ id: 'ACK', text: 'Ack', t_ms: 18039 }, { id: 'CLOSE', text: 'Close', t_ms: 59645 }],
    violations: [{ ts: Date.parse('2026-11-15T18:27:26.236Z') / 1000, event: 'command', violation: 'unplanned_switching',
        device_id: 'mvtc_a', command: 'TRANSFER_TO_GENERATORS', actor: 'manager' }],
    step_reverts: [{ step: 'CLOSE', event: 'reverted', t_ms: 108000 }],
    soe: [{ ts: '2026-11-15T18:26:36.848+00:00', ts_ms: Date.parse('2026-11-15T18:26:36.848Z'), source: 'plant',
        event: 'command', device_id: 'mvtc_a', actor: 'manager', command: 'CLOSED_TRANSITION_RETRANSFER', angle_deg: -4.8 }],
    time_note: 'Server observation times.',
    ledger_entry_id: '7580dd89-4325',
    integrity: { report_sha256: 'ab'.repeat(32), covers: 'c', ledger_entry_id: '7580dd89-4325' },
};

describe('training_print', () => {
    it('formats ms and SOE details', () => {
        expect(fmtMs(319055)).toBe('05:19.055');
        expect(fmtMs(null)).toBe('—');
        expect(soeDetail(REPORT.soe[0])).toBe('command=CLOSED_TRANSITION_RETRANSFER · angle_deg=-4.8');
    });

    it('renders every section with times relative to the start, escaped', () => {
        const h = reportDocument(REPORT);
        expect(h.startsWith('<!DOCTYPE html>')).toBe(true);
        expect(h).toContain('PASS · Score 67 / 100');
        expect(h).toContain('SIMULATED PLANT');
        expect(h).toContain('00:18.039');                  // step time
        expect(h).toContain('00:58.599');                  // SOE close, relative to start
        expect(h).toContain('01:47.987');                  // violation, relative to start
        expect(h).toContain('unplanned_switching');
        expect(h).toContain('TRANSFER_TO_GENERATORS');
        expect(h).toContain('reverted');
        expect(h).toContain('229 s over target');
        expect(h).toContain('Not completed:');
        expect(h).toContain('ab'.repeat(32));
        expect(h).toContain('ours, not an industry standard');
        expect(h).not.toContain('<script>');
        expect(h).toContain('manager&lt;script&gt;');
        expect(h).toContain('Closed &lt;b&gt;transition&lt;/b&gt;');
    });

    it('empty sections say so', () => {
        const h = reportDocument({ ...REPORT, violations: [], step_reverts: [], soe: [], integrity: undefined });
        expect(h).toContain('None.');
        expect(h).toContain('No events.');
        expect(h).toContain('not available');
    });

    it('openPrintable writes into the new window; a blocked popup returns false', () => {
        let written = '';
        const fake = { document: { open() {}, write(x) { written += x; }, close() {} }, focus() {} };
        expect(openPrintable(REPORT, { open: () => fake })).toBe(true);
        expect(written).toContain('DRILL-04');
        expect(openPrintable(REPORT, { open: () => null })).toBe(false);
    });
});

describe('relay_tags', () => {
    const plant = (over = {}, sync = null) => ({
        paths: [{ path: 'a', utility_ok: true, ...over }],
        devices: [{ kind: 'transfer', path: 'a', synchro: sync }],
    });

    it('27 follows the utility; unmodelled relays say N/M', () => {
        const s = relayStates('a', plant({ utility_ok: false }), null);
        expect(s.find((x) => x.ansi === '27')).toMatchObject({ state: 'PICKED UP', tone: 'crit' });
        for (const a of ['50/51', '59', '87T']) {
            expect(s.find((x) => x.ansi === a)).toMatchObject({ state: 'N/M', tone: 'id' });
        }
        expect(relayStates('a', plant(), null).find((x) => x.ansi === '27').state).toBe('NORMAL');
    });

    it('25: off outside training mode, then idle / block / permit / armed', () => {
        const st = (sync) => relayStates('a', plant({}, sync), null).find((x) => x.ansi === '25').state;
        expect(st(null)).toBe('OFF');
        expect(st({ enabled: false })).toBe('OFF');
        expect(st({ enabled: true, live: false })).toBe('IDLE');
        expect(st({ enabled: true, live: true, permissive: false })).toBe('BLOCK');
        expect(st({ enabled: true, live: true, permissive: true })).toBe('PERMIT');
        expect(st({ enabled: true, live: true, permissive: false, close_armed: true })).toBe('ARMED');
    });

    it('L2: 87T follows the transformer, 27 picks up with 52-T open', () => {
        const pl = (tr, over = {}) => ({ paths: [{ path: 'a', utility_ok: true, ...over }],
            devices: [{ kind: 'transfer', path: 'a', transformer: tr }] });
        const r = (x, a) => x.find((y) => y.ansi === a);
        expect(r(relayStates('a', pl({ flag_87t: false }), null), '87T')).toMatchObject({ state: 'NORMAL', tone: 'ok' });
        expect(r(relayStates('a', pl({ flag_87t: true }), null), '87T')).toMatchObject({ state: 'TRIP', tone: 'crit' });
        expect(r(relayStates('a', pl({}, { incomer_live: false }), null), '27').state).toBe('PICKED UP');
    });

    it('What-If falls back to the DAG utility state', () => {
        const s = relayStates('b', null, { util_b: { tripped: true } });
        expect(s.find((x) => x.ansi === '27').state).toBe('PICKED UP');
        expect(relayStates('b', null, null).find((x) => x.ansi === '27').state).toBe('—');
    });

    it('draws one chip per relay and paints states', () => {
        document.body.innerHTML = `<svg>${relayRowSvg('a', 190, 300)}</svg>`;
        const root = document.querySelector('svg');
        expect(root.querySelectorAll('.pf-relay').length).toBe(RELAYS.length);
        applyRelays(root, 'a', relayStates('a', plant({ utility_ok: false }), null));
        const g = root.querySelector('[data-relay="a:27"]');
        expect(g.getAttribute('data-tone')).toBe('crit');
        expect(g.querySelector('.pf-relay-state').textContent).toBe('PICKED UP');
        expect(root.querySelector('[data-relay="a:87T"] title').textContent).toContain('not modelled');
    });
});

describe('Power SLD carries the relay rows (T4)', () => {
    it('both Phase 1 paths draw the relay row and the legend names it', async () => {
        const { __power_test__ } = await import('/assets/js/views/power.js');
        const svg = __power_test__.buildFlatMarkup();
        expect(svg).toContain('data-relays="a"');
        expect(svg).toContain('data-relays="b"');
        expect(svg).toContain('N/M = not modelled');
    });
});
