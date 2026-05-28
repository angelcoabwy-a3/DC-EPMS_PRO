/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO -- frontend/assets/js/core/qkd_gate.js
 * Epic 10 -- global QKD-based signing gate.
 *
 * Polls /api/qkd/status. When the simulator's last_qber crosses
 * the threshold (default 11% per Shor-Preskill / matching Epic 9
 * backend), the gate CLOSES:
 *
 *   - body.classList adds 'qkd-gate-closed'.
 *   - [data-qkd-gate-banner] becomes visible with the message
 *     "Firma Deshabilitada: Enlace Interceptado" + QBER and
 *     threshold values.
 *   - isSigningEnabled() returns false; callers MUST consult it
 *     before submitting any sign request. Backend re-checks
 *     server-side (the gate is UX speed; the backend is the
 *     load-bearing safety).
 *
 * On gate re-open (QBER falls below threshold):
 *   - body class removed.
 *   - banner hidden.
 *   - 'dc-epms-qkd-gate-opened' event fired.
 *
 * Module surface:
 *   - startQkdGate(opts?)  -- one-shot init. Idempotent.
 *   - stopQkdGate()        -- stops the poll (tests).
 *   - isSigningEnabled()   -- synchronous, returns current state.
 *   - onQkdGateChange(cb)  -- subscribe to state flips.
 *
 * Honest framing reminder: the gate is driven by an EDUCATIONAL
 * simulator (backend/crypto/bb84_core.py). On a real QKD link the
 * QBER would come from physical photon counts; here it is the
 * intercept-and-resend signature of the seeded eavesdropper sim.
 * ════════════════════════════════════════════════════════════════ */

import { escapeHTML } from './sanitize.js';

const STATUS_URL = '/api/qkd/status?audit_limit=4';
const DEFAULT_POLL_MS = 5000;
const BODY_CLOSED_CLASS = 'qkd-gate-closed';
const BANNER_TEXT_BASE = 'Firma Deshabilitada: Enlace Interceptado';

let _pollInterval = null;
let _started = false;
let _lastState = {
    enabled: true,        // default-open so we don't block before first poll
    qber: null,
    threshold: 0.11,
    last_decision: null,
    pool_depth: null,
};
const _listeners = new Set();


function isSigningEnabled() {
    return _lastState.enabled;
}

function getQkdGateState() {
    return Object.assign({}, _lastState);
}

function onQkdGateChange(cb) {
    if (typeof cb !== 'function') return () => {};
    _listeners.add(cb);
    return () => _listeners.delete(cb);
}

function _notify(prevEnabled) {
    for (const cb of _listeners) {
        try {
            cb(getQkdGateState());
        } catch (_e) { /* swallow */ }
    }
    if (prevEnabled !== _lastState.enabled) {
        try {
            const name = _lastState.enabled
                ? 'dc-epms-qkd-gate-opened'
                : 'dc-epms-qkd-gate-closed';
            window.dispatchEvent(new CustomEvent(name, {
                detail: getQkdGateState(),
            }));
        } catch (_e) { /* CustomEvent unsupported */ }
    }
}

function _updateDom() {
    const body = document.body;
    if (!body) return;
    if (_lastState.enabled) {
        body.classList.remove(BODY_CLOSED_CLASS);
    } else {
        body.classList.add(BODY_CLOSED_CLASS);
    }
    const banner = document.querySelector('[data-qkd-gate-banner]');
    if (!banner) return;
    if (_lastState.enabled) {
        banner.hidden = true;
        banner.innerHTML = '';
        return;
    }
    banner.hidden = false;
    const qberPct = (_lastState.qber !== null && _lastState.qber !== undefined)
        ? (_lastState.qber * 100).toFixed(2) + '%'
        : '—';
    const thrPct = (_lastState.threshold !== null && _lastState.threshold !== undefined)
        ? (_lastState.threshold * 100).toFixed(1) + '%'
        : '11.0%';
    banner.innerHTML = ''
        + '<strong class="qkd-gate-banner-headline">'
        + escapeHTML(BANNER_TEXT_BASE)
        + '</strong>'
        + ' &nbsp; <span class="qkd-gate-banner-detail">QBER '
        + escapeHTML(qberPct)
        + ' >= '
        + escapeHTML(thrPct)
        + '. La firma de MOPs/EOPs queda bloqueada hasta que el pool QKD se recupere.'
        + '</span>';
}

function applyStatusPayload(status) {
    const prevEnabled = _lastState.enabled;
    if (!status || typeof status !== 'object') {
        // No data -- assume gate open (fail-permissive on UI; backend
        // is authoritative). Reasonable for the "first poll pending"
        // window after page load.
        _lastState = Object.assign({}, _lastState, {
            enabled: true, qber: null, last_decision: null,
        });
        _updateDom();
        _notify(prevEnabled);
        return;
    }
    const threshold = (typeof status.qber_threshold === 'number')
        ? status.qber_threshold : 0.11;
    const qber = (typeof status.last_qber === 'number')
        ? status.last_qber : null;
    // Gate-close decision: only CLOSE on a positive observation
    // above threshold. Null QBER (no batches yet) keeps the gate
    // OPEN -- otherwise startup blocks signing forever in a fresh
    // boot where the pool has not been primed.
    let enabled = true;
    if (qber !== null && qber >= threshold) enabled = false;
    _lastState = {
        enabled,
        qber,
        threshold,
        last_decision: status.last_decision || null,
        pool_depth: (typeof status.pool_depth === 'number')
            ? status.pool_depth : null,
    };
    _updateDom();
    _notify(prevEnabled);
}

async function _pollOnce() {
    let res;
    try {
        res = await fetch(STATUS_URL);
    } catch (_e) {
        return;  // transient network blip -- keep last state
    }
    if (!res || !res.ok) return;
    let body;
    try {
        body = await res.json();
    } catch (_e) {
        return;
    }
    applyStatusPayload(body);
}

function startQkdGate(opts = {}) {
    if (_started) return;
    _started = true;
    const ms = (typeof opts.pollMs === 'number' && opts.pollMs > 0)
        ? opts.pollMs : DEFAULT_POLL_MS;
    _pollOnce();
    _pollInterval = setInterval(_pollOnce, ms);
}

function stopQkdGate() {
    if (_pollInterval !== null) {
        clearInterval(_pollInterval);
        _pollInterval = null;
    }
    _started = false;
}

function reset() {
    stopQkdGate();
    _listeners.clear();
    _lastState = {
        enabled: true,
        qber: null,
        threshold: 0.11,
        last_decision: null,
        pool_depth: null,
    };
}

export {
    BANNER_TEXT_BASE,
    BODY_CLOSED_CLASS,
    applyStatusPayload,
    getQkdGateState,
    isSigningEnabled,
    onQkdGateChange,
    startQkdGate,
    stopQkdGate,
};

export const __qkd_gate_test__ = {
    BANNER_TEXT_BASE,
    BODY_CLOSED_CLASS,
    applyStatusPayload,
    getQkdGateState,
    isSigningEnabled,
    onQkdGateChange,
    startQkdGate,
    stopQkdGate,
    _pollOnce,
    _updateDom,
    reset,
};
