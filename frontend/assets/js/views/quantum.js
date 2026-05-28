/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/quantum.js
 * Epic 9 — BB84 QKD educational telemetry HMI.
 *
 * Operator-facing surface for the deterministic BB84 simulator that
 * stamps Optimizer-approved ledger entries with a QKD fingerprint.
 * The view exists to make the simulator's QBER signature visible:
 * when a (simulated) eavesdropper is injected, every batch rejects,
 * the pool stalls, and downstream Optimizer entries fall back to
 * the key-less path -- this is the educational demonstration of
 * the BB84 intercept-and-resend detector.
 *
 * Contracts:
 *   - S-SEC-01: every payload field from /api/qkd/status renders via
 *     escapeHTML. Fingerprints are 16 hex chars; we display the first
 *     8 + an ellipsis to keep the row scannable without leaking the
 *     full value into chat-paste / screenshot recipients. (In a real
 *     QKD system this would be the line between "shown" and "secret";
 *     here it's defensive UX hygiene.)
 *   - S-DET-01: the QBER status badge derives from a deterministic
 *     threshold comparison; no LLM in the visual path.
 *   - Polling: 5 s interval, cancels on view hide. Re-arms on show.
 *
 * Test surface: __quantum_view_test__ exposes the pure render helpers
 * (renderHeader, renderQberBadge, renderPoolStats, renderAuditRow,
 * formatFingerprint), the fetch helper (fetchStatus), and reset.
 * ════════════════════════════════════════════════════════════════ */

import { registerRoute } from '../core/router.js';
import { escapeHTML } from '../core/sanitize.js';

const $ = (id) => document.getElementById(id);

let _routeRegistered = false;
let _viewWired = false;
let _refreshInterval = null;
let _lastStatus = null;

const POLL_MS = 5000;
const FINGERPRINT_DISPLAY_LEN = 8;  // chars shown before ellipsis
const AUDIT_RENDER_LIMIT = 12;

// ─── Pure helpers (testable) ────────────────────────────────────────
function formatFingerprint(raw) {
    // Defensive: untrusted-shaped input -> empty string sentinel.
    if (typeof raw !== 'string' || raw.length === 0) {
        return '—';
    }
    const head = raw.slice(0, FINGERPRINT_DISPLAY_LEN);
    return head + '…';
}

function _formatPercent(x) {
    if (typeof x !== 'number' || Number.isNaN(x)) return '—';
    return (x * 100).toFixed(2) + '%';
}

function _formatThreshold(x) {
    if (typeof x !== 'number') return '—';
    return (x * 100).toFixed(1) + '%';
}

function _formatIsoShort(s) {
    // Defensive parse -- backend sends ISO 8601 UTC.
    if (typeof s !== 'string') return '—';
    const t = new Date(s);
    if (Number.isNaN(t.getTime())) return '—';
    return t.toLocaleTimeString();
}

function renderHeader(framing) {
    const el = document.querySelector('[data-qkd-framing]');
    if (!el) return;
    const text = (typeof framing === 'string' && framing.length > 0)
        ? framing
        : 'Educational BB84 simulator.';
    el.innerHTML = escapeHTML(text);
}

function renderQberBadge(status) {
    const el = document.querySelector('[data-qkd-qber-badge]');
    if (!el) return;
    if (!status || typeof status !== 'object') {
        el.innerHTML = escapeHTML('QBER: —');
        el.dataset.state = 'unknown';
        return;
    }
    const qber = (typeof status.last_qber === 'number')
        ? status.last_qber : null;
    const threshold = (typeof status.qber_threshold === 'number')
        ? status.qber_threshold : 0.11;
    let state = 'unknown';
    let label = 'QBER: —';
    if (qber === null) {
        state = 'unknown';
        label = 'QBER: — (no batches yet)';
    } else if (qber >= threshold) {
        state = 'red';
        label = 'QBER: ' + _formatPercent(qber)
            + ' ≥ ' + _formatThreshold(threshold)
            + ' — signing blocked';
    } else {
        state = 'green';
        label = 'QBER: ' + _formatPercent(qber)
            + ' < ' + _formatThreshold(threshold)
            + ' — pool healthy';
    }
    el.dataset.state = state;
    el.innerHTML = escapeHTML(label);
}

function renderPoolStats(status) {
    const el = document.querySelector('[data-qkd-pool]');
    if (!el) return;
    if (!status || typeof status !== 'object') {
        el.innerHTML = escapeHTML('Pool: —');
        return;
    }
    const depth = Number.isFinite(status.pool_depth) ? status.pool_depth : 0;
    const cap = Number.isFinite(status.pool_capacity)
        ? status.pool_capacity : 0;
    const accepted = Number.isFinite(status.keys_accepted_total)
        ? status.keys_accepted_total : 0;
    const rejected = Number.isFinite(status.keys_rejected_total)
        ? status.keys_rejected_total : 0;
    const eve = !!status.eavesdrop_simulated;
    el.innerHTML = [
        '<div class="qkd-stat"><span class="qkd-stat-label">'
            + escapeHTML('Pool depth')
            + '</span><span class="qkd-stat-value">'
            + escapeHTML(String(depth) + ' / ' + String(cap))
            + '</span></div>',
        '<div class="qkd-stat"><span class="qkd-stat-label">'
            + escapeHTML('Keys accepted (total)')
            + '</span><span class="qkd-stat-value">'
            + escapeHTML(String(accepted))
            + '</span></div>',
        '<div class="qkd-stat"><span class="qkd-stat-label">'
            + escapeHTML('Keys rejected (total)')
            + '</span><span class="qkd-stat-value">'
            + escapeHTML(String(rejected))
            + '</span></div>',
        '<div class="qkd-stat"><span class="qkd-stat-label">'
            + escapeHTML('Eavesdrop simulated')
            + '</span><span class="qkd-stat-value">'
            + escapeHTML(eve ? 'YES (audit drill)' : 'no')
            + '</span></div>',
    ].join('');
}

function renderAuditRow(record) {
    if (!record || typeof record !== 'object') return '';
    const decision = (record.decision === 'accepted' || record.decision === 'rejected')
        ? record.decision : 'unknown';
    const ts = _formatIsoShort(record.ts);
    const qberPct = _formatPercent(record.qber);
    const fp = formatFingerprint(record.fingerprint);
    const reason = typeof record.reason === 'string' ? record.reason : '';
    return ''
        + '<tr class="qkd-audit-row" data-decision="'
        + escapeHTML(decision)
        + '">'
        + '<td>' + escapeHTML(ts) + '</td>'
        + '<td>' + escapeHTML(decision) + '</td>'
        + '<td>' + escapeHTML(qberPct) + '</td>'
        + '<td><code>' + escapeHTML(fp) + '</code></td>'
        + '<td>' + escapeHTML(reason) + '</td>'
        + '</tr>';
}

function renderAuditTable(records) {
    const el = document.querySelector('[data-qkd-audit]');
    if (!el) return;
    if (!Array.isArray(records) || records.length === 0) {
        el.innerHTML = ''
            + '<tr><td colspan="5" class="qkd-audit-empty">'
            + escapeHTML('No audit records yet — pool primed at boot.')
            + '</td></tr>';
        return;
    }
    // Newest first, capped.
    const ordered = records.slice().reverse().slice(0, AUDIT_RENDER_LIMIT);
    el.innerHTML = ordered.map(renderAuditRow).join('');
}

// ─── Fetch + apply ──────────────────────────────────────────────────
async function fetchStatus() {
    let res;
    try {
        res = await fetch('/api/qkd/status?audit_limit=16');
    } catch (_e) {
        return null;
    }
    if (!res || !res.ok) return null;
    let json;
    try {
        json = await res.json();
    } catch (_e) {
        return null;
    }
    return json;
}

function applyStatus(status) {
    _lastStatus = status;
    renderHeader(status && status.framing);
    renderQberBadge(status);
    renderPoolStats(status);
    renderAuditTable(status && status.recent_audit);
}

async function refresh() {
    const status = await fetchStatus();
    applyStatus(status);
}

// ─── View lifecycle ─────────────────────────────────────────────────
function startPolling() {
    if (_refreshInterval !== null) return;
    refresh();
    _refreshInterval = setInterval(refresh, POLL_MS);
}

function stopPolling() {
    if (_refreshInterval !== null) {
        clearInterval(_refreshInterval);
        _refreshInterval = null;
    }
}

function initQuantumView() {
    if (_routeRegistered) return;
    registerRoute('quantum', {
        viewId: 'view-quantum',
        activate: () => {
            if (!_viewWired) {
                _viewWired = true;
            }
            startPolling();
        },
        deactivate: () => {
            stopPolling();
        },
    });
    _routeRegistered = true;
}

function reset() {
    stopPolling();
    _routeRegistered = false;
    _viewWired = false;
    _lastStatus = null;
}

// ─── Exports ────────────────────────────────────────────────────────
export { initQuantumView };
export const __quantum_view_test__ = {
    formatFingerprint,
    renderHeader,
    renderQberBadge,
    renderPoolStats,
    renderAuditRow,
    renderAuditTable,
    fetchStatus,
    applyStatus,
    refresh,
    startPolling,
    stopPolling,
    initQuantumView,
    reset,
    getLastStatus: () => _lastStatus,
};
