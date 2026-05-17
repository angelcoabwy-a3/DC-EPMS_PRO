/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/hermes_events.test.js
 * ROADMAP V11 T3.1 — unified event-driven plane, frontend routing.
 *
 * Verifies core/hermes_events.js routes the cmms_alerts + agent_consensus
 * streams into reactive state and decoupled DOM CustomEvents. WebSocket
 * is stubbed; no real socket.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { initHermesEvents, __hermes_events_test__ } from '/assets/js/core/hermes_events.js';
import { connectHermes, __hermes_test__ } from '/assets/js/services/api.js';
import { getState } from '/assets/js/core/state.js';

// ── WebSocket double ─────────────────────────────────────────────────
class FakeWS {
    constructor(url) {
        this.url = url;
        this.readyState = FakeWS.CONNECTING;
        this._listeners = {};
        FakeWS.last = this;
    }
    addEventListener(type, fn) { (this._listeners[type] ||= []).push(fn); }
    dispatch(type, ev) { (this._listeners[type] || []).forEach((fn) => fn(ev)); }
    send() {}
    close() { this.readyState = FakeWS.CLOSED; this.dispatch('close', {}); }
}
FakeWS.CONNECTING = 0;
FakeWS.OPEN = 1;
FakeWS.CLOSED = 3;
FakeWS.last = null;

function wsFrame(stream, payload) {
    return { data: JSON.stringify({ stream, seq: 1, ts: 1, payload }) };
}

describe('T3.1 — Hermes EDA frontend routing (core/hermes_events.js)', () => {
    beforeEach(() => {
        vi.stubGlobal('WebSocket', FakeWS);
        __hermes_test__.reset();
        __hermes_events_test__.reset();
    });

    afterEach(() => {
        __hermes_test__.reset();
        __hermes_events_test__.reset();
        vi.unstubAllGlobals();
    });

    it('a cmms_alerts payload lands in reactive state', () => {
        __hermes_events_test__.onCmmsAlert({ event: 'work_order_saved', work_order_id: 'WO-1' });
        expect(__hermes_events_test__.getCmmsAlerts()[0].work_order_id).toBe('WO-1');
        expect(getState('cmmsAlerts')[0].work_order_id).toBe('WO-1');
        expect(getState('cmmsAlertCount')).toBe(1);
    });

    it('an EDGE_HEALING_RECOMMENDED alert sets state + fires a DOM event', () => {
        const seen = [];
        const handler = (e) => seen.push(e.detail);
        document.addEventListener('hermes:edge-healing', handler);
        try {
            __hermes_events_test__.onCmmsAlert({
                event: 'EDGE_HEALING_RECOMMENDED',
                asset_id: 'genset_a_01',
                max_z: 5.2,
                actuation: 'CET_APPROVAL_REQUIRED',
            });
        } finally {
            document.removeEventListener('hermes:edge-healing', handler);
        }
        expect(getState('edgeHealingAlert').asset_id).toBe('genset_a_01');
        expect(seen).toHaveLength(1);
        expect(seen[0].actuation).toBe('CET_APPROVAL_REQUIRED');
    });

    it('an agent_consensus payload lands in state + fires a DOM event', () => {
        const seen = [];
        const handler = (e) => seen.push(e.detail);
        document.addEventListener('hermes:agent-consensus', handler);
        try {
            __hermes_events_test__.onAgentConsensus({
                agent: 'consensus', event: 'resolved', veto_active: true,
            });
        } finally {
            document.removeEventListener('hermes:agent-consensus', handler);
        }
        expect(getState('agentConsensus')[0].veto_active).toBe(true);
        expect(seen).toHaveLength(1);
    });

    it('a cmms_alerts WS frame routes end-to-end through onHermesStream', () => {
        initHermesEvents();
        connectHermes();
        FakeWS.last.dispatch('message', wsFrame('cmms_alerts', {
            event: 'work_order_saved', work_order_id: 'WO-9', status: 'pending_approval',
        }));
        expect(getState('cmmsAlerts')[0].work_order_id).toBe('WO-9');
    });

    it('retains at most 50 alerts (newest first)', () => {
        for (let i = 0; i < 60; i += 1) {
            __hermes_events_test__.onCmmsAlert({ event: 'work_order_saved', work_order_id: `WO-${i}` });
        }
        const alerts = __hermes_events_test__.getCmmsAlerts();
        expect(alerts).toHaveLength(50);
        expect(alerts[0].work_order_id).toBe('WO-59');
    });
});
