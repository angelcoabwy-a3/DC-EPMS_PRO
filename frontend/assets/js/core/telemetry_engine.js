/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — core/telemetry_engine.js
 *
 * Real-time telemetry transport for the HMI.
 *
 * ROADMAP V11 T3.1 — TRANSPORT CUTOVER:
 *   The live transport is now the Project Hermes multiplexed WebSocket
 *   (services/api.js → /api/hermes). The legacy SSE EventSource path is
 *   retained below, flag-gated, for emergency rollback ONLY.
 *
 *   Both transports funnel into the SAME `_ingest()` schema dispatch, so
 *   the view layer (Mission Control, PUE widget, SHI sparkline, activity
 *   strip, heatmaps) is untouched by the cutover — it only ever reads
 *   the reactive state keys this module writes.
 *
 * Schema dispatch (unchanged across the cutover):
 *   - legacy_kpi          {latest:{…flat…}, ts}        → latestTelemetry
 *   - channel_innovations {channels:{…}, anomaly_count_60min, ts}
 *                                                      → channels + anomalies
 *
 * Public API:
 *   import { startTelemetry, stopTelemetry } from './core/telemetry_engine.js';
 *   startTelemetry(apiBase);   // connects the live transport
 *   stopTelemetry();           // tears it down cleanly
 * ════════════════════════════════════════════════════════════════ */

import { setState, getState } from './state.js';
import { connectHermes, onHermesStream } from '../services/api.js';

const SCHEMA_LEGACY_KPI = 'legacy_kpi';
const SCHEMA_CHANNEL_INNOVATIONS = 'channel_innovations';

const RECONNECT_INITIAL_MS = 1000;
const RECONNECT_MAX_MS = 30000;

// T3.1 cutover: the Hermes WebSocket is the live telemetry transport.
// Set false (here or via console) to fall back to the legacy SSE
// EventSource — kept wired purely for emergency rollback.
const _USE_HERMES_TRANSPORT = true;

let _source = null;            // legacy SSE EventSource (rollback path)
let _reconnectMs = RECONNECT_INITIAL_MS;
let _reconnectTimer = null;
let _hermesUnsub = null;       // Hermes telemetry-stream subscription handle

const _dispatchTable = {
    [SCHEMA_LEGACY_KPI]: (data) => setState('latestTelemetry', data.latest ?? null),
    [SCHEMA_CHANNEL_INNOVATIONS]: (data) => {
        setState('channels', data.channels ?? {});
        // Sprint 5 C2: backend pipeline reports rolling 60-min anomaly count.
        // Frontend Activity Strip subscribes to this for the Anomalies cell.
        if (typeof data.anomaly_count_60min === 'number') {
            setState('anomalyCount60min', data.anomaly_count_60min);
        }
    },
};

/**
 * Transport-agnostic ingest: route a parsed telemetry object by its
 * schema and update the reactive store. Both the Hermes WS path and the
 * legacy SSE path call this with an already-parsed object.
 */
function _ingest(data) {
    if (!data || typeof data !== 'object') return;
    const schema = data.schema || SCHEMA_LEGACY_KPI;
    const handler = _dispatchTable[schema];
    if (!handler) {
        console.warn('[telemetry] unknown schema:', schema);
        return;
    }
    handler(data);
    setState('schemaVersion', schema);
    setState('lastTelemetryAtMs', performance.now());
    setState('messageCount', (getState('messageCount') || 0) + 1);
    if (typeof data.ts === 'number') {
        // backend ts is unix seconds; compare to client ms
        setState('serverClientLagMs', Date.now() - data.ts * 1000);
    }
}

// ─── Legacy SSE transport (rollback path — _USE_HERMES_TRANSPORT=false) ───
function _onMessage(e) {
    let data;
    try {
        data = JSON.parse(e.data);
    } catch (err) {
        console.warn('[telemetry] JSON parse failed:', err);
        return;
    }
    _ingest(data);
    _reconnectMs = RECONNECT_INITIAL_MS;
}

function _onError() {
    console.warn(`[telemetry] SSE disconnected, reconnect in ${_reconnectMs}ms...`);
    setState('reconnectCount', (getState('reconnectCount') || 0) + 1);
    if (_source) {
        try { _source.close(); } catch (_) { /* noop */ }
        _source = null;
    }
    if (_reconnectTimer) clearTimeout(_reconnectTimer);
    _reconnectTimer = setTimeout(() => {
        _reconnectMs = Math.min(_reconnectMs * 2, RECONNECT_MAX_MS);
        const apiBase = getState('_apiBase');
        if (apiBase) startTelemetry(apiBase);
    }, _reconnectMs);
}

function _startLegacySse(apiBase) {
    if (_source) {
        try { _source.close(); } catch (_) { /* noop */ }
    }
    _source = new EventSource(`${apiBase}/api/telemetry/stream`);
    _source.onmessage = _onMessage;
    _source.onerror = _onError;
    setState('telemetrySource', _source);
}

function _stopLegacySse() {
    if (_reconnectTimer) {
        clearTimeout(_reconnectTimer);
        _reconnectTimer = null;
    }
    if (_source) {
        try { _source.close(); } catch (_) { /* noop */ }
        _source = null;
    }
    setState('telemetrySource', null);
}

// ─── Public API ───────────────────────────────────────────────────
export function startTelemetry(apiBase) {
    setState('_apiBase', apiBase);

    if (_USE_HERMES_TRANSPORT) {
        // Live path: subscribe the schema dispatch to the Hermes
        // `telemetry` stream. The WS client (services/api.js) owns the
        // socket lifecycle + exponential-backoff reconnection.
        if (_hermesUnsub) _hermesUnsub();
        connectHermes();
        _hermesUnsub = onHermesStream('telemetry', _ingest);
        setState('telemetryTransport', 'hermes-ws');
        console.log('[telemetry] transport: Hermes WebSocket (/api/hermes)');
        return;
    }

    // Rollback path: legacy SSE EventSource.
    _startLegacySse(apiBase);
    setState('telemetryTransport', 'legacy-sse');
    console.warn('[telemetry] transport: legacy SSE (rollback mode)');
}

export function stopTelemetry() {
    if (_hermesUnsub) {
        _hermesUnsub();
        _hermesUnsub = null;
    }
    _stopLegacySse();
}

export const SCHEMAS = Object.freeze({
    LEGACY_KPI: SCHEMA_LEGACY_KPI,
    CHANNEL_INNOVATIONS: SCHEMA_CHANNEL_INNOVATIONS,
});
