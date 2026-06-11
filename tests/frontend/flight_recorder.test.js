/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/flight_recorder.test.js
 * Forensic Replay (R2) — ring buffer + replay integration on the
 * Power SLD, ledger markers with their HMAC chain prefix.
 *
 * Selector note: after renderFlatSld() the document contains BOTH
 * the SVG <g data-sld-node="ups_a"> and the iso-block fixture —
 * assertions must qualify .sld-iso-block or they read the wrong
 * element (severity lives on different surfaces per layer).
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, afterEach, vi } from 'vitest';

import {
    record, snapshotAt, range, __recorder_test__,
} from '/assets/js/core/flight_recorder.js';
import { __power_test__ } from '/assets/js/views/power.js';

afterEach(() => {
    __recorder_test__.clear();
    __power_test__.reset();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    document.body.innerHTML = '';
});

const isoUps = () =>
    document.querySelector('.sld-iso-block[data-sld-node="ups_a"]');

// ════════════════════════════════════════════════════════════════
//  Ring buffer (pure)
// ════════════════════════════════════════════════════════════════
describe('R2 — flight_recorder ring buffer', () => {
    it('records timestamped entries and reports the window', () => {
        record('telemetry', { channels: { a: 1 } }, 1000);
        record('grid', { ups_a: { alive: true } }, 2000);
        const w = range();
        expect(w).toEqual({ start: 1000, end: 2000, count: 2 });
    });

    it('snapshotAt returns the latest entry of EACH kind at or before t', () => {
        record('telemetry', { channels: { v: 1 } }, 1000);
        record('grid', { g: 1 }, 1500);
        record('telemetry', { channels: { v: 2 } }, 2000);
        record('telemetry', { channels: { v: 3 } }, 3000);
        const snap = snapshotAt(2200);
        expect(snap.telemetry.channels.v).toBe(2);   // not v3 (future)
        expect(snap.grid.g).toBe(1);
        expect(snap.coolgrid).toBeNull();
    });

    it('evicts beyond capacity (oldest first) and ignores junk', () => {
        for (let i = 0; i < __recorder_test__.CAP + 50; i += 1) {
            record('telemetry', { channels: { i } }, i);
        }
        expect(__recorder_test__.size()).toBe(__recorder_test__.CAP);
        expect(range().start).toBe(50);   // oldest 50 evicted
        record('not_a_kind', {}, 9);
        record('grid', null, 9);
        expect(__recorder_test__.size()).toBe(__recorder_test__.CAP);
    });
});

// ════════════════════════════════════════════════════════════════
//  Replay integration on the Power SLD
// ════════════════════════════════════════════════════════════════
describe('R2 — replay mode on the Power SLD', () => {
    const { renderFlatSld, buildModeToggle, buildReplayToggle, setReplay,
        scrubTo, getMode, onTelemetryFrame } = __power_test__;

    function mountView() {
        document.body.innerHTML =
            '<div id="view-power"><div class="pid-action-bar"></div>'
            + '<svg class="pid-svg"></svg>'
            + '<div class="sld-iso-block" data-sld-node="ups_a"></div></div>';
        renderFlatSld();
        buildModeToggle();
        buildReplayToggle();
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: true, status: 200, json: async () => ({ entries: [] }),
        })));
    }

    it('refuses to enter replay on an empty buffer (honest no-op)', () => {
        mountView();
        setReplay(true);
        expect(getMode()).toBe('live');
        expect(document.getElementById('pwr-replay-bar')).toBeNull();
    });

    it('enters replay, scrubs history onto the SLD, and live frames are ignored', () => {
        mountView();
        record('telemetry', { channels: { ups_a_soc: { is_anomalous: true } } }, 1000);
        record('telemetry', { channels: { ups_a_soc: { is_anomalous: false, max_z: 0.1 } } }, 5000);
        setReplay(true);
        expect(getMode()).toBe('replay');
        const bar = document.getElementById('pwr-replay-bar');
        expect(bar).not.toBeNull();
        expect(bar.textContent).toContain('session only');   // honest scope

        scrubTo(1200);   // inside the anomalous window
        expect(isoUps().dataset.sev).toBe('critical');
        scrubTo(5000);   // quiet again
        expect(isoUps().dataset.sev).toBe('ok');

        // The live feed must NOT repaint the diagram while replaying.
        onTelemetryFrame({ channels: { ups_a_soc: { is_anomalous: true } } });
        expect(isoUps().dataset.sev).toBe('ok');
    });

    it('exiting replay returns to live and hides the bar', () => {
        mountView();
        record('telemetry', { channels: {} }, 1000);
        record('telemetry', { channels: {} }, 2000);
        setReplay(true);
        setReplay(false);
        expect(getMode()).toBe('live');
        expect(document.getElementById('pwr-replay-bar').hidden).toBe(true);
    });

    it('ledger markers ride the timeline with their HMAC prefix', async () => {
        mountView();
        record('telemetry', { channels: {} }, Date.parse('2026-06-10T20:00:00Z'));
        record('telemetry', { channels: {} }, Date.parse('2026-06-10T20:10:00Z'));
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: true, status: 200,
            json: async () => ({ entries: [
                { sequence_no: 12, ts: '2026-06-10T20:05:00Z', actor: 'checker.bob',
                  action: 'PROCEDURE_SIGNED', entry_hmac_hex: '4c2cf2cf660049baf3b8' },
                { sequence_no: 3, ts: '2026-06-10T19:00:00Z', actor: 'x',
                  action: 'OUT_OF_WINDOW', entry_hmac_hex: 'dead' },
            ] }),
        })));
        setReplay(true);
        await vi.waitFor(() => {
            expect(document.querySelectorAll('#pwr-replay-bar .rp-marker')).toHaveLength(1);
        });
        const dot = document.querySelector('#pwr-replay-bar .rp-marker');
        expect(dot.title).toContain('#12 PROCEDURE_SIGNED');
        expect(dot.title).toContain('hmac 4c2cf2cf6600');
        expect(dot.style.left).toBe('50.00%');   // mid-window
        dot.click();
        expect(document.getElementById('pwr-replay-entry').textContent)
            .toContain('checker.bob');
    });

    it('a ledger fetch failure degrades gracefully (no markers, no crash)', async () => {
        mountView();
        record('telemetry', { channels: {} }, 1000);
        record('telemetry', { channels: {} }, 2000);
        vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503, json: async () => ({}) })));
        expect(() => setReplay(true)).not.toThrow();
        await Promise.resolve();
        expect(document.querySelectorAll('.rp-marker')).toHaveLength(0);
    });
});
