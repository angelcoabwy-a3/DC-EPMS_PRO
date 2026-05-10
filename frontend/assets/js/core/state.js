/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — core/state.js
 *
 * Reactive state container. Replaces the IIFE-private `state` object
 * in app.js (legacy at frontend/assets/archive/app.js.legacy:27-39).
 *
 * Status: SKELETON — Sprint 5.5 Hybrid Frontend Pivot, Phase 1.0.
 *   Wired: NO (app.js still owns state).
 *   Next bite: extract `state` from IIFE, replace closure refs with
 *   imports of `getState`, `setState`, `subscribe` from this module.
 *
 * Design contract (binding when implemented):
 *
 *   - JS Proxy wraps the state object so any property assignment
 *     fires registered listeners with the changed key + new value.
 *   - Listeners are sync by default; for batched render scheduling
 *     the consumer wraps the listener in a frame-scheduler.
 *   - Nested objects are NOT deep-proxied (cost vs benefit). For
 *     nested updates use `setState('channels', newChannelsMap)`
 *     instead of mutating in place.
 *   - The store is a SINGLE process-local instance. NO persistence
 *     to localStorage — the agent_copilot SSE channel is the source
 *     of truth, and reload is cheap.
 *
 * Telemetry handler will populate via:
 *
 *   import { setState } from './core/state.js';
 *   setState('latestTelemetry', point);
 *   setState('channels', innovationPayload);
 *
 * View renderers subscribe via:
 *
 *   import { subscribe } from './core/state.js';
 *   subscribe('channels', (next) => renderHeatmap(next));
 *
 * ════════════════════════════════════════════════════════════════ */

const _initial = {
    pueHistory: [],
    latestTelemetry: null,
    channels: null,
    incidents: [],
    agentStreaming: false,
    agentBuffer: '',
    agentSources: [],
    healthCheckInterval: null,
    telemetrySource: null,
    incidentSource: null,
    lastTelemetryAtMs: 0,
    schemaVersion: null,
    // Sprint 5.5 hybrid Bite A2/A3 — activity strip counters
    messageCount: 0,
    reconnectCount: 0,
    serverClientLagMs: null,
    anomalyCount60min: 0,
    _apiBase: null,
    // Sprint 5.5 hybrid Bite B (SHI sparkline) — capped 60-sample trend.
    // Pushed by app.js renderSiteHealth via bridge after each successful
    // /api/site/health fetch (15s interval -> 15min visible window).
    shiHistory: [],
    // Phase 4 (v0.10.9) — contextual asset panel
    selectedAsset: null,            // 'ups_a' | 'xfmr_a' | … | null
    assetTrends: {},                // { assetId: [{ t, v }] } — 60-sample rolling buffer
};

const _listeners = new Map();

function _notify(key, value) {
    const subs = _listeners.get(key);
    if (!subs) return;
    for (const fn of subs) {
        try {
            fn(value, key);
        } catch (err) {
            console.warn(`[state] listener for "${key}" threw:`, err);
        }
    }
}

const _store = new Proxy(structuredClone(_initial), {
    set(target, key, value) {
        target[key] = value;
        _notify(key, value);
        return true;
    },
});

export function getState(key) {
    return key === undefined ? _store : _store[key];
}

export function setState(key, value) {
    _store[key] = value;
}

export function subscribe(key, fn) {
    if (!_listeners.has(key)) _listeners.set(key, new Set());
    _listeners.get(key).add(fn);
    return () => _listeners.get(key)?.delete(fn);
}

export function reset() {
    Object.assign(_store, structuredClone(_initial));
}
