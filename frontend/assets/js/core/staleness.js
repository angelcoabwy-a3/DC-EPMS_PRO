/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — core/staleness.js
 *
 * Stale-data badge for the SSE telemetry stream.
 *
 *   "In critical infrastructure, no data is better than stale data."
 *
 * State machine (4 states):
 *
 *   unknown   No SSE message received yet (boot).             [—]
 *   fresh     Last message < T_FRESH_MS ago.                  [OK, green]
 *   warn      T_FRESH_MS <= age < T_WARN_MS.                  [Xs, amber, pulse]
 *   stale     age >= T_WARN_MS.                               [Xs STALE, red, pulse]
 *
 * Trigger sources:
 *   - subscribe('lastTelemetryAtMs', _evaluate)  fired on every fresh
 *     SSE message (legacy IIFE bridge calls window.__epms.setState).
 *   - setInterval(_evaluate, TICK_MS) fires every second so elapsed
 *     time keeps progressing even when no new messages arrive (which
 *     is exactly the case we need to detect).
 *
 * DOM contract:
 *   - Pill element id="health-stream" in app-header (added in
 *     index.html).
 *   - Module writes data-staleness on the pill AND on
 *     document.documentElement so global CSS rules can react.
 *   - Module rewrites .lbl text content.
 *
 * Threshold rationale:
 *   T_FRESH_MS = 10000 — Wilmer 2026-05-09: "Si no llega telemetria
 *                       en 10s, cambia el estado visual a warning."
 *   T_WARN_MS  = 30000 — escalation to STALE after 3x the fresh
 *                       threshold. Beyond this the operator must
 *                       assume the source is dead, not slow.
 *
 * NO direct DOM lookup outside initStaleness(). The pill reference is
 * cached at init; the hot path is JS-only state read + 2 attribute
 * writes per second. Cost: negligible (<0.1 ms/tick).
 * ════════════════════════════════════════════════════════════════ */

import { subscribe, getState } from './state.js';

const STATES = Object.freeze({
    UNKNOWN: 'unknown',
    FRESH:   'fresh',
    WARN:    'warn',
    STALE:   'stale',
});

const T_FRESH_MS = 10_000;
const T_WARN_MS  = 30_000;
const TICK_MS    = 1000;

let _pillEl = null;
let _intervalId = null;

function _classifyAge(ageMs) {
    if (ageMs < T_FRESH_MS) return STATES.FRESH;
    if (ageMs < T_WARN_MS)  return STATES.WARN;
    return STATES.STALE;
}

function _formatLabel(level, ageMs) {
    if (level === STATES.UNKNOWN) return 'Stream —';
    if (level === STATES.FRESH)   return 'Stream OK';
    const seconds = Math.floor(ageMs / 1000);
    if (level === STATES.WARN)    return `Stream ${seconds}s`;
    return `Stream ${seconds}s STALE`;
}

function _evaluate() {
    if (!_pillEl) return;

    const lastMs = getState('lastTelemetryAtMs') || 0;
    let level;
    let ageMs = 0;

    if (lastMs === 0) {
        level = STATES.UNKNOWN;
    } else {
        ageMs = performance.now() - lastMs;
        level = _classifyAge(ageMs);
    }

    _pillEl.dataset.staleness = level;
    document.documentElement.dataset.staleness = level;

    const lblEl = _pillEl.querySelector('.lbl');
    if (lblEl) lblEl.textContent = _formatLabel(level, ageMs);
}

export function initStaleness({ pillId = 'health-stream', tickMs = TICK_MS } = {}) {
    _pillEl = document.getElementById(pillId);
    if (!_pillEl) {
        console.warn(`[staleness] pill #${pillId} not found in DOM; badge disabled.`);
        return;
    }
    subscribe('lastTelemetryAtMs', _evaluate);

    if (_intervalId) clearInterval(_intervalId);
    _intervalId = setInterval(_evaluate, tickMs);

    _evaluate(); // initial paint -> UNKNOWN
}

export function stopStaleness() {
    if (_intervalId) {
        clearInterval(_intervalId);
        _intervalId = null;
    }
}

export const STALENESS_STATES = STATES;
export const STALENESS_THRESHOLDS = Object.freeze({
    T_FRESH_MS,
    T_WARN_MS,
    TICK_MS,
});
