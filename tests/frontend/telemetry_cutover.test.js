/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/telemetry_cutover.test.js
 * ROADMAP V11 T3.1 — SSE → Hermes WebSocket transport cutover.
 *
 * Proves that startTelemetry() now drives the Hermes WS transport and
 * that a Hermes `telemetry` frame flows through the unchanged schema
 * dispatch into the reactive store — i.e. the view layer keeps reading
 * the same state keys. WebSocket is stubbed; no real socket.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { startTelemetry, stopTelemetry } from '/assets/js/core/telemetry_engine.js';
import { getState } from '/assets/js/core/state.js';
import { __hermes_test__ } from '/assets/js/services/api.js';

// ── WebSocket double ─────────────────────────────────────────────────
class FakeWS {
    constructor(url) {
        this.url = url;
        this.readyState = FakeWS.CONNECTING;
        this._listeners = {};
        FakeWS.created += 1;
        FakeWS.last = this;
    }
    addEventListener(type, fn) { (this._listeners[type] ||= []).push(fn); }
    dispatch(type, ev) { (this._listeners[type] || []).forEach((fn) => fn(ev)); }
    send() { /* push-only */ }
    close() { this.readyState = FakeWS.CLOSED; this.dispatch('close', {}); }
}
FakeWS.CONNECTING = 0;
FakeWS.OPEN = 1;
FakeWS.CLOSING = 2;
FakeWS.CLOSED = 3;
FakeWS.created = 0;
FakeWS.last = null;

function hermesFrame(payload) {
    return { data: JSON.stringify({ stream: 'telemetry', seq: 1, ts: 1, payload }) };
}

describe('T3.1 — telemetry transport cutover (SSE → Hermes WS)', () => {
    beforeEach(() => {
        FakeWS.created = 0;
        FakeWS.last = null;
        vi.stubGlobal('WebSocket', FakeWS);
        __hermes_test__.reset();
    });

    afterEach(() => {
        stopTelemetry();
        __hermes_test__.reset();
        vi.unstubAllGlobals();
    });

    it('startTelemetry opens the Hermes WebSocket as the live transport', () => {
        startTelemetry('http://test.local');
        expect(FakeWS.created).toBe(1);
        expect(FakeWS.last.url).toMatch(/\/api\/hermes$/);
        expect(getState('telemetryTransport')).toBe('hermes-ws');
    });

    it('a channel_innovations frame updates channels + anomaly state', () => {
        startTelemetry('http://test.local');
        FakeWS.last.dispatch('message', hermesFrame({
            schema: 'channel_innovations',
            channels: { 'rack_a_01:gpu_Tj_c': { max_z: 0.4, is_anomalous: false } },
            anomaly_count_60min: 2,
            ts: 1700000000,
        }));
        expect(getState('schemaVersion')).toBe('channel_innovations');
        expect(getState('channels')['rack_a_01:gpu_Tj_c']).toEqual({ max_z: 0.4, is_anomalous: false });
        expect(getState('anomalyCount60min')).toBe(2);
    });

    it('a legacy_kpi frame still reaches latestTelemetry through the same dispatch', () => {
        startTelemetry('http://test.local');
        FakeWS.last.dispatch('message', hermesFrame({
            schema: 'legacy_kpi',
            latest: { pue: 1.11, it_load_kw: 16800 },
            ts: 1700000000,
        }));
        expect(getState('latestTelemetry')).toEqual({ pue: 1.11, it_load_kw: 16800 });
    });

    it('stopTelemetry detaches the stream — later frames are ignored', () => {
        startTelemetry('http://test.local');
        const sock = FakeWS.last;
        stopTelemetry();
        sock.dispatch('message', hermesFrame({
            schema: 'channel_innovations',
            channels: { 'should:not_apply': { max_z: 9.9 } },
            ts: 1700000001,
        }));
        expect(getState('channels')['should:not_apply']).toBeUndefined();
    });
});
