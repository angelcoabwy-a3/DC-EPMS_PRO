/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/hermes.test.js
 * ROADMAP V11 T3.1 — Hermes WebSocket client (services/api.js).
 *
 * No real socket: WebSocket is stubbed with FakeWS so dispatch,
 * subscription, malformed-frame tolerance and reconnection are all
 * deterministic.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import {
    connectHermes,
    disconnectHermes,
    onHermesStream,
    hermesStatus,
    __hermes_test__,
} from '/assets/js/services/api.js';

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
    send() { /* push-only stream — client never sends */ }
    close() { this.readyState = FakeWS.CLOSED; this.dispatch('close', {}); }
    /** Simulate an unexpected drop (server/network), as the browser would. */
    simulateDrop() { this.readyState = FakeWS.CLOSED; this.dispatch('close', {}); }
}
FakeWS.CONNECTING = 0;
FakeWS.OPEN = 1;
FakeWS.CLOSING = 2;
FakeWS.CLOSED = 3;
FakeWS.created = 0;
FakeWS.last = null;

describe('T3.1 — Hermes WebSocket client', () => {
    beforeEach(() => {
        FakeWS.created = 0;
        FakeWS.last = null;
        vi.stubGlobal('WebSocket', FakeWS);
        __hermes_test__.reset();
    });

    afterEach(() => {
        __hermes_test__.reset();
        vi.unstubAllGlobals();
        vi.useRealTimers();
    });

    it('connectHermes opens one socket to the /api/hermes path', () => {
        connectHermes();
        expect(FakeWS.created).toBe(1);
        expect(FakeWS.last.url).toMatch(/^wss?:\/\//);
        expect(FakeWS.last.url).toMatch(/\/api\/hermes$/);
    });

    it('connectHermes is idempotent while a socket is live', () => {
        connectHermes();
        connectHermes();
        expect(FakeWS.created).toBe(1);
    });

    it('routes a telemetry frame to its stream subscriber', () => {
        const seen = [];
        onHermesStream('telemetry', (payload) => seen.push(payload));
        connectHermes();
        FakeWS.last.dispatch('message', {
            data: JSON.stringify({ stream: 'telemetry', seq: 1, ts: 1, payload: { pue: 1.11 } }),
        });
        expect(seen).toEqual([{ pue: 1.11 }]);
    });

    it('ignores a frame whose stream has no subscriber', () => {
        connectHermes();
        expect(() => FakeWS.last.dispatch('message', {
            data: JSON.stringify({ stream: 'cmms', payload: {} }),
        })).not.toThrow();
    });

    it('survives a malformed (non-JSON) frame', () => {
        const seen = [];
        onHermesStream('telemetry', (p) => seen.push(p));
        connectHermes();
        expect(() => FakeWS.last.dispatch('message', { data: '{bad json' })).not.toThrow();
        expect(seen).toEqual([]);
    });

    it('onHermesStream returns a working unsubscribe', () => {
        const seen = [];
        const off = onHermesStream('telemetry', (p) => seen.push(p));
        connectHermes();
        off();
        FakeWS.last.dispatch('message', {
            data: JSON.stringify({ stream: 'telemetry', payload: { x: 1 } }),
        });
        expect(seen).toEqual([]);
    });

    it('a subscriber that throws does not break dispatch', () => {
        const seen = [];
        onHermesStream('telemetry', () => { throw new Error('boom'); });
        onHermesStream('telemetry', (p) => seen.push(p));
        connectHermes();
        expect(() => FakeWS.last.dispatch('message', {
            data: JSON.stringify({ stream: 'telemetry', payload: { ok: 1 } }),
        })).not.toThrow();
        expect(seen).toEqual([{ ok: 1 }]);
    });

    it('reconnects with backoff when the socket drops unexpectedly', () => {
        vi.useFakeTimers();
        connectHermes();
        expect(FakeWS.created).toBe(1);
        FakeWS.last.simulateDrop();
        vi.advanceTimersByTime(1100);          // past the 1s initial backoff
        expect(FakeWS.created).toBe(2);        // a fresh socket was opened
    });

    it('disconnectHermes stops reconnection', () => {
        vi.useFakeTimers();
        connectHermes();
        disconnectHermes();
        expect(hermesStatus().wantOpen).toBe(false);
        FakeWS.last.simulateDrop();
        vi.advanceTimersByTime(5000);
        expect(FakeWS.created).toBe(1);        // no reconnect after explicit close
    });
});
