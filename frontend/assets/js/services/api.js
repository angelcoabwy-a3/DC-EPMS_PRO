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
