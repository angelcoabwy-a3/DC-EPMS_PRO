/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — core/telemetry_engine.js
 *
 * SSE network handler. Replaces the IIFE-private functions in app.js
 * (legacy IIFE; see git history for archive/app.js.legacy):
 *
 *   - startTelemetryStream()  legacy:122-143
 *   - handleTelemetry(point)  legacy:145-158
 *   - updateKPIs(point)       legacy:160-180  (stays in views/, not here)
 *
 * Status: SKELETON — Sprint 5.5 Hybrid Frontend Pivot, Phase 1.0.
 *   Wired: NO (app.js still owns the EventSource).
 *   Next bite: move EventSource lifecycle here, expose start/stop,
 *   add schema-aware dispatch + reconnect-with-backoff.
 *
 * Design contract (binding when implemented):
 *
 *   1. SSE schema dispatch
 *      - legacy KPI payload `{latest: {...flat fields...}, ts}` -> kpi handler
 *      - C2 channel payload `{schema: "channel_innovations",
 *          channels: {ch_id: {n_emissions, max_z, mean_z, is_anomalous,
 *          last_emission}}}` -> channels handler
 *      Single onmessage routes by `data.schema` (default = legacy_kpi).
 *
 *   2. Stale-data tracking
 *      Every successful message updates `state.lastTelemetryAtMs`.
 *      A separate frame-scheduler module reads this and toggles a
 *      DOM dataset attribute for CSS-driven staleness rendering.
 *
 *   3. Reconnect policy
 *      Exponential backoff: 1s, 2s, 4s, 8s, capped at 30s.
 *      Reset to 1s after a successful message.
 *      Hard reset (close + reopen fresh EventSource) on every retry
 *      to avoid stuck-connection states observed in legacy 5s fixed
 *      reconnect (legacy:135-142).
 *
 *   4. Worker offload (Phase 2)
 *      JSON parsing of large channel payloads will move to a Web
 *      Worker. The main thread receives only the parsed object via
 *      postMessage. See ./workers/telemetry_parser.js (TODO).
 *
 * Public API (planned):
 *
 *   import { startTelemetry, stopTelemetry } from './core/telemetry_engine.js';
 *   startTelemetry(API_BASE);          // begins SSE
 *   stopTelemetry();                   // closes EventSource cleanly
 *
 * ════════════════════════════════════════════════════════════════ */

import { setState, getState } from './state.js';

const SCHEMA_LEGACY_KPI = 'legacy_kpi';
const SCHEMA_CHANNEL_INNOVATIONS = 'channel_innovations';

const RECONNECT_INITIAL_MS = 1000;
const RECONNECT_MAX_MS = 30000;

let _source = null;
let _reconnectMs = RECONNECT_INITIAL_MS;
let _reconnectTimer = null;

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

function _onMessage(e) {
    let data;
    try {
        data = JSON.parse(e.data);
    } catch (err) {
        console.warn('[telemetry] JSON parse failed:', err);
        return;
    }
    const schema = data.schema || SCHEMA_LEGACY_KPI;
    const handler = _dispatchTable[schema];
    if (!handler) {
        console.warn('[telemetry] unknown schema:', schema);
        return;
    }
    handler(data);
    setState('schemaVersion', schema);
    setState('lastTelemetryAtMs', performance.now());

    // counters + lag for activity strip (Bite A3)
    setState('messageCount', (getState('messageCount') || 0) + 1);
    if (typeof data.ts === 'number') {
        // backend ts is unix seconds (main.py:471); compare to client ms
        setState('serverClientLagMs', Date.now() - data.ts * 1000);
    }

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

export function startTelemetry(apiBase) {
    setState('_apiBase', apiBase);
    if (_source) stopTelemetry();
    _source = new EventSource(`${apiBase}/api/telemetry/stream`);
    _source.onmessage = _onMessage;
    _source.onerror = _onError;
    setState('telemetrySource', _source);
}

export function stopTelemetry() {
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

export const SCHEMAS = Object.freeze({
    LEGACY_KPI: SCHEMA_LEGACY_KPI,
    CHANNEL_INNOVATIONS: SCHEMA_CHANNEL_INNOVATIONS,
});
