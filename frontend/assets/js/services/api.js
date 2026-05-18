/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — services/api.js
 * ROADMAP V11 T2.1 — shared HTTP service layer.
 *
 * The keystone the IIFE dismantling builds on (and the seam Project
 * Hermes / T3.1 will extend): one place that owns fetch(), HTTP-error
 * normalisation, and JSON parsing. View modules call these named
 * functions instead of hand-rolling fetch() against the page origin.
 *
 * Conventions:
 *   - Paths are root-relative ('/api/...'). FastAPI serves the SPA and
 *     the API from the same origin, so no base URL is needed.
 *   - apiFetch() THROWS on a non-2xx response or a network failure.
 *     Callers catch and render a degraded state — never a silent fail.
 *
 * This file grows one view at a time as T2.1 extracts the legacy IIFE.
 * First cut: the failure-scenario simulator (views/scenarios.js).
 * ════════════════════════════════════════════════════════════════ */

/**
 * Core HTTP wrapper. Resolves to the parsed JSON body, or throws an
 * Error whose message carries the HTTP status (or the network-failure
 * reason) so the caller can surface a meaningful degraded state.
 *
 * @param {string} path          root-relative path, e.g. '/api/scenarios'
 * @param {RequestInit} [options] passed straight through to fetch()
 * @returns {Promise<any>}        parsed JSON body
 */
export async function apiFetch(path, options) {
    let resp;
    try {
        resp = await fetch(path, options);
    } catch (e) {
        // Network-layer failure (offline, DNS, CORS) — never reached HTTP.
        throw new Error(`network error contacting ${path}: ${e.message}`);
    }
    if (!resp.ok) {
        let detail = '';
        try { detail = (await resp.text()).slice(0, 300); }
        catch (_e) { /* response body unreadable — status alone must do */ }
        throw new Error(`HTTP ${resp.status} from ${path}${detail ? ': ' + detail : ''}`);
    }
    try {
        return await resp.json();
    } catch (e) {
        throw new Error(`malformed JSON from ${path}: ${e.message}`);
    }
}

/**
 * Failure-scenario catalogue.
 * @returns {Promise<Array>} the scenarios array (degrades to [] if the
 *                           payload omits the key — never null)
 */
export async function getScenarios() {
    const data = await apiFetch('/api/scenarios');
    return data.scenarios || [];
}

/**
 * Run the ODE projection for one failure scenario.
 * @param {string} scenarioId
 * @param {number} [horizonS=900] projection horizon in seconds
 * @returns {Promise<object>}     { trajectory, events, summary, module }
 */
export async function runScenario(scenarioId, horizonS = 900) {
    const path = `/api/scenarios/${encodeURIComponent(scenarioId)}/run`
               + `?horizon_s=${encodeURIComponent(horizonS)}`;
    return apiFetch(path, { method: 'POST' });
}

/**
 * Incident audit log — every event PostgreSQL has recorded, newest first.
 * @param {number} [limit=50] max rows to return
 * @returns {Promise<Array>} the incidents array (degrades to [] if the
 *                           payload omits the key — never null)
 */
export async function getIncidents(limit = 50) {
    const data = await apiFetch(`/api/incidents?limit=${encodeURIComponent(limit)}`);
    return data.rows || [];
}

/**
 * MOP / SOP / EOP procedure library — corpus-indexed.
 * @returns {Promise<object>} { mops: [...], count, by_type }
 */
export async function getMops() {
    return apiFetch('/api/mops');
}

/**
 * Fetch one procedure document by id (metadata + parsed steps + body).
 * @param {string} docId
 * @returns {Promise<object>}
 */
export async function getMop(docId) {
    return apiFetch(`/api/mops/${encodeURIComponent(docId)}`);
}

/**
 * AI-generate a new procedure draft from a topic spec.
 * @param {{topic:string, doc_type:string, equipment:string, duration:string}} spec
 * @returns {Promise<object>} the generated procedure (steps + raw_markdown)
 */
export async function generateMop(spec) {
    return apiFetch('/api/mops/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(spec),
    });
}

/**
 * Power-topology state — the physics-validated SLD rollup: per-node
 * severity + metrics, ΣP power balance, redundancy mode, site health.
 * @returns {Promise<object>}
 */
export async function getTopologyState() {
    return apiFetch('/api/topology/state');
}


/* ════════════════════════════════════════════════════════════════
 *  Project Hermes — multiplexed WebSocket stream (ROADMAP V11 T3.1)
 *
 *  One socket to /api/hermes carries any number of logical streams,
 *  demultiplexed on the frame's `stream` field:
 *
 *      { "stream": "telemetry", "seq": N, "ts": <unix>, "payload": {…} }
 *
 *  connectHermes() is called once at bootstrap (main.js); modules
 *  subscribe via onHermesStream(stream, handler). Reconnection is
 *  automatic with exponential backoff. This runs ALONGSIDE the legacy
 *  SSE telemetry engine — the REST/SSE cutover is a later T3.1 bite.
 * ════════════════════════════════════════════════════════════════ */

const HERMES_PATH = '/api/hermes';
const _HERMES_RECONNECT_INITIAL_MS = 1000;
const _HERMES_RECONNECT_MAX_MS = 30000;

let _hermesSocket = null;
let _hermesReconnectMs = _HERMES_RECONNECT_INITIAL_MS;
let _hermesReconnectTimer = null;
let _hermesWantOpen = false;
const _hermesSubscribers = new Map();   // stream -> Set<handler>

function _hermesUrl() {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${window.location.host}${HERMES_PATH}`;
}

function _hermesDispatch(frame) {
    const subs = _hermesSubscribers.get(frame.stream);
    if (!subs) return;
    for (const handler of subs) {
        try {
            handler(frame.payload, frame);
        } catch (e) {
            console.error('[hermes] subscriber threw on stream', frame.stream, e);
        }
    }
}

function _hermesScheduleReconnect() {
    if (!_hermesWantOpen) return;
    if (_hermesReconnectTimer) clearTimeout(_hermesReconnectTimer);
    _hermesReconnectTimer = setTimeout(() => {
        _hermesReconnectTimer = null;
        _hermesReconnectMs = Math.min(_hermesReconnectMs * 2, _HERMES_RECONNECT_MAX_MS);
        connectHermes();
    }, _hermesReconnectMs);
}

/**
 * Subscribe a handler to one logical stream of the Hermes feed.
 * @param {string} streamName  e.g. 'telemetry'
 * @param {(payload:any, frame:object)=>void} handler
 * @returns {()=>void} unsubscribe
 */
export function onHermesStream(streamName, handler) {
    if (!_hermesSubscribers.has(streamName)) {
        _hermesSubscribers.set(streamName, new Set());
    }
    _hermesSubscribers.get(streamName).add(handler);
    return () => { _hermesSubscribers.get(streamName)?.delete(handler); };
}

/** Open (or re-open) the Hermes WebSocket. Idempotent while the socket is live. */
export function connectHermes() {
    _hermesWantOpen = true;
    if (_hermesSocket
        && (_hermesSocket.readyState === WebSocket.OPEN
            || _hermesSocket.readyState === WebSocket.CONNECTING)) {
        return _hermesSocket;
    }
    let sock;
    try {
        sock = new WebSocket(_hermesUrl());
    } catch (e) {
        console.warn('[hermes] socket construction failed:', e.message);
        _hermesScheduleReconnect();
        return null;
    }
    _hermesSocket = sock;

    sock.addEventListener('open', () => {
        console.log('[hermes] stream connected:', _hermesUrl());
    });
    sock.addEventListener('message', (ev) => {
        let frame;
        try {
            frame = JSON.parse(ev.data);
        } catch (e) {
            console.warn('[hermes] dropped malformed frame:', e.message);
            return;
        }
        // A good frame proves the link is healthy — reset the backoff.
        _hermesReconnectMs = _HERMES_RECONNECT_INITIAL_MS;
        if (frame && typeof frame.stream === 'string') _hermesDispatch(frame);
    });
    sock.addEventListener('close', () => {
        if (_hermesWantOpen) {
            console.warn(`[hermes] stream dropped — reconnect in ${_hermesReconnectMs}ms`);
            _hermesScheduleReconnect();
        }
    });
    sock.addEventListener('error', () => {
        // 'error' is followed by 'close'; closing here funnels recovery
        // through the single reconnect path in the close handler.
        try { sock.close(); } catch (_e) { /* already closing */ }
    });
    return sock;
}

/** Close the Hermes stream and stop reconnecting. */
export function disconnectHermes() {
    _hermesWantOpen = false;
    if (_hermesReconnectTimer) {
        clearTimeout(_hermesReconnectTimer);
        _hermesReconnectTimer = null;
    }
    if (_hermesSocket) {
        try { _hermesSocket.close(); } catch (_e) { /* already closed */ }
        _hermesSocket = null;
    }
}

/** Connection diagnostics — for the activity strip / tests. */
export function hermesStatus() {
    return {
        wantOpen: _hermesWantOpen,
        readyState: _hermesSocket ? _hermesSocket.readyState : null,
        reconnectMs: _hermesReconnectMs,
        streams: [..._hermesSubscribers.keys()],
    };
}

// Test surface — lets the Vitest harness reset module singletons.
export const __hermes_test__ = {
    reset() {
        disconnectHermes();
        _hermesSubscribers.clear();
        _hermesReconnectMs = _HERMES_RECONNECT_INITIAL_MS;
    },
};
