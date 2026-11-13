/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO -- frontend/assets/js/views/ot_security.js
 * Release R2-A -- OT Security posture (replaces the Morpheus stub).
 *
 * Renders GET /api/ot-security/posture: deterministic checks the
 * backend computes about its own instance (session gate, ledger
 * chain, control-surface inventory, edge ingest) plus the gaps it
 * cannot cover. HONEST SCOPE: no network traffic is inspected and
 * no NVIDIA Morpheus pipeline exists; the payload says so and this
 * view prints that disclaimer permanently.
 *
 * Read-only surface (ADR-006): no button here changes state.
 * S-SEC-01: every interpolated value goes through escapeHTML --
 * usernames, tag ids and error strings are operator / device text.
 * Severity is never conveyed by colour alone: each row carries a
 * text badge.
 * ════════════════════════════════════════════════════════════════ */

import { registerRoute } from '../core/router.js';
import { escapeHTML } from '../core/sanitize.js';

const VIEW_ID = 'view-ot-security';
const ROUTE_ID = 'ot-security';
const ENDPOINT = '/api/ot-security/posture';
const POLL_MS = 15000;
const SEVERITIES = ['critical', 'high', 'medium', 'low'];

let _routeRegistered = false;
let _timer = null;

function $root() {
    return document.getElementById(VIEW_ID);
}

// ─── Pure helpers ───────────────────────────────────────────────────
/** Failing checks first (worst severity first), then info, then pass.
 *  Stable within a group so the backend's order is preserved. */
function sortChecks(checks) {
    const rank = (c) => {
        if (c.status === 'fail') {
            const i = SEVERITIES.indexOf(c.severity);
            return i === -1 ? SEVERITIES.length : i;
        }
        return c.status === 'info' ? 10 : 20;
    };
    return (Array.isArray(checks) ? checks : [])
        .map((c, i) => ({ c, i }))
        .sort((a, b) => (rank(a.c) - rank(b.c)) || (a.i - b.i))
        .map((x) => x.c);
}

function badgeFor(check) {
    if (check.status === 'fail') {
        const sev = SEVERITIES.includes(check.severity) ? check.severity : 'medium';
        return { cls: `ots-badge ots-badge-${sev}`, label: sev.toUpperCase() };
    }
    if (check.status === 'pass') return { cls: 'ots-badge ots-badge-pass', label: 'PASS' };
    return { cls: 'ots-badge ots-badge-info', label: 'INFO' };
}

function formatTs(unixSeconds) {
    if (typeof unixSeconds !== 'number' || !isFinite(unixSeconds)) return 'never';
    try {
        return new Date(unixSeconds * 1000).toISOString().replace('.000Z', 'Z');
    } catch (_e) {
        return 'never';
    }
}

// ─── Render ─────────────────────────────────────────────────────────
function renderSummary(summary) {
    const s = summary || {};
    const by = s.by_severity || {};
    const worst = SEVERITIES.includes(s.worst_severity) ? s.worst_severity : 'none';
    const tiles = SEVERITIES.map((sev) => `
        <div class="ots-tile ots-tile-${sev}" data-count="${Number(by[sev]) || 0}">
            <div class="ots-tile-val">${escapeHTML(String(Number(by[sev]) || 0))}</div>
            <div class="ots-tile-lbl">${escapeHTML(sev)}</div>
        </div>`).join('');
    return `
        <div class="ots-summary" data-worst="${escapeHTML(worst)}">
            ${tiles}
            <div class="ots-tile ots-tile-pass">
                <div class="ots-tile-val">${escapeHTML(String(Number(s.passed) || 0))}</div>
                <div class="ots-tile-lbl">passing</div>
            </div>
        </div>`;
}

function renderCheck(check) {
    const b = badgeFor(check);
    const remediation = check.status === 'fail' && check.remediation
        ? `<div class="ots-check-fix"><strong>Remediation:</strong> ${escapeHTML(check.remediation)}</div>`
        : '';
    return `
        <li class="ots-check ots-check-${escapeHTML(check.status || 'info')}" data-check-id="${escapeHTML(check.id || '')}">
            <div class="ots-check-hdr">
                <span class="${b.cls}">${escapeHTML(b.label)}</span>
                <span class="ots-check-id">${escapeHTML(check.id || '')}</span>
                <span class="ots-check-title">${escapeHTML(check.title || '')}</span>
            </div>
            <div class="ots-check-detail">${escapeHTML(check.detail || '')}</div>
            ${remediation}
            <div class="ots-check-ref">${escapeHTML(check.reference || '')}</div>
        </li>`;
}

function renderChecks(checks) {
    const sorted = sortChecks(checks);
    if (sorted.length === 0) {
        return '<div class="ots-empty">No checks returned.</div>';
    }
    return `<ul class="ots-checks">${sorted.map(renderCheck).join('')}</ul>`;
}

function _kv(label, value) {
    return `<tr><td class="ots-k">${escapeHTML(label)}</td><td class="ots-v">${escapeHTML(String(value))}</td></tr>`;
}

function renderAccess(access) {
    if (!access || access.error) {
        return '<div class="ots-empty">Access posture unavailable.</div>';
    }
    const users = Array.isArray(access.users) ? access.users : [];
    const rows = users.map((u) => `
        <tr>
            <td>${escapeHTML(u.username || '')}</td>
            <td>${escapeHTML(u.role || '')}</td>
            <td>${u.password_source === 'environment'
                ? '<span class="ots-badge ots-badge-pass">ENVIRONMENT</span>'
                : '<span class="ots-badge ots-badge-high">REPO DEFAULT</span>'}</td>
        </tr>`).join('');
    return `
        <table class="ots-kv"><tbody>
            ${_kv('Session gate', access.gate_enabled ? 'ON' : 'OFF')}
            ${_kv('Signing secret', access.jwt_secret_from_env ? 'configured' : 'ephemeral (per boot)')}
            ${_kv('Accounts', users.length)}
        </tbody></table>
        <table class="ots-table">
            <thead><tr><th>User</th><th>Role</th><th>Password source</th></tr></thead>
            <tbody>${rows || '<tr><td colspan="3" class="ots-empty">No accounts seeded.</td></tr>'}</tbody>
        </table>`;
}

function renderLedger(ledger) {
    if (!ledger || !ledger.available) {
        return '<div class="ots-empty">Forensic ledger is not running on this instance.</div>';
    }
    const chain = ledger.verified
        ? '<span class="ots-badge ots-badge-pass">VERIFIED</span>'
        : `<span class="ots-badge ots-badge-critical">BROKEN AT ${escapeHTML(String(ledger.divergence_index))}</span>`;
    return `
        <table class="ots-kv"><tbody>
            <tr><td class="ots-k">Hash chain</td><td class="ots-v">${chain}</td></tr>
            ${_kv('Entries', Number(ledger.total_entries) || 0)}
            ${_kv('HMAC key', ledger.hmac_key_from_env ? `configured (version ${ledger.key_version})` : 'ephemeral (per boot)')}
            ${_kv('Storage', ledger.persistence === 'postgres' ? 'PostgreSQL' : 'in memory (lost on restart)')}
        </tbody></table>`;
}

function renderBms(bms) {
    if (!bms || !bms.available) {
        return '<div class="ots-empty">BMS connector is not loaded.</div>';
    }
    const byProto = bms.by_protocol || {};
    const writable = bms.writable_by_protocol || {};
    const protoRows = Object.keys(byProto).sort().map((p) => `
        <tr>
            <td>${escapeHTML(p)}</td>
            <td class="ots-num">${escapeHTML(String(byProto[p]))}</td>
            <td class="ots-num">${escapeHTML(String(writable[p] || 0))}</td>
        </tr>`).join('');
    const recent = Array.isArray(bms.audit_recent) ? bms.audit_recent : [];
    const auditRows = recent.map((e) => `
        <tr>
            <td class="ots-mono">${escapeHTML(formatTs(e.ts))}</td>
            <td class="ots-mono">${escapeHTML(e.tag_id || '')}</td>
            <td>${escapeHTML(e.user || '')}</td>
            <td>${e.success
                ? '<span class="ots-badge ots-badge-pass">ACCEPTED</span>'
                : '<span class="ots-badge ots-badge-medium">DENIED</span>'}</td>
            <td>${escapeHTML(e.error || '')}</td>
        </tr>`).join('');
    return `
        <table class="ots-table">
            <thead><tr><th>Protocol</th><th class="ots-num">Tags</th><th class="ots-num">Writable</th></tr></thead>
            <tbody>
                ${protoRows}
                <tr class="ots-total">
                    <td>Total</td>
                    <td class="ots-num">${escapeHTML(String(Number(bms.total_tags) || 0))}</td>
                    <td class="ots-num">${escapeHTML(String(Number(bms.writable_tags) || 0))}</td>
                </tr>
            </tbody>
        </table>
        <div class="ots-sub">Write attempts since boot: ${escapeHTML(String(Number(bms.audit_total) || 0))}
            (${escapeHTML(String(Number(bms.audit_accepted) || 0))} accepted,
            ${escapeHTML(String(Number(bms.audit_denied) || 0))} denied by the connector)</div>
        <table class="ots-table">
            <thead><tr><th>Time (UTC)</th><th>Tag</th><th>User</th><th>Result</th><th>Reason</th></tr></thead>
            <tbody>${auditRows || '<tr><td colspan="5" class="ots-empty">No write attempts recorded since boot.</td></tr>'}</tbody>
        </table>`;
}

function renderEdge(edge) {
    if (!edge || !edge.available) {
        return '<div class="ots-empty">Edge ingest is not mounted on this instance.</div>';
    }
    return `
        <table class="ots-kv"><tbody>
            ${_kv('Channels seen', Number(edge.channel_count) || 0)}
            ${_kv('Batches accepted', Number(edge.batches_accepted) || 0)}
            ${_kv('Envelopes accepted', Number(edge.envelopes_accepted) || 0)}
            ${_kv('Envelopes rejected', Number(edge.envelopes_rejected) || 0)}
            ${_kv('Last ingest (UTC)', formatTs(edge.last_ingest_ts))}
            ${_kv('Device authentication', edge.device_authenticated ? 'yes' : 'none')}
        </tbody></table>`;
}

function renderPosture(payload) {
    const p = payload || {};
    const facts = p.facts || {};
    return `
        <div class="ots-disclaimer" role="note">${escapeHTML(p.disclaimer || '')}</div>
        ${renderSummary(p.summary)}
        <div class="ots-grid">
            <section class="ots-panel ots-panel-wide">
                <h3>Checks</h3>
                ${renderChecks(p.checks)}
            </section>
            <section class="ots-panel">
                <h3>Access</h3>
                ${renderAccess(facts.access)}
            </section>
            <section class="ots-panel">
                <h3>Forensic ledger</h3>
                ${renderLedger(facts.ledger)}
            </section>
            <section class="ots-panel">
                <h3>Edge ingest (Modbus gateway)</h3>
                ${renderEdge(facts.edge)}
            </section>
            <section class="ots-panel ots-panel-wide">
                <h3>Control surface (BMS)</h3>
                ${renderBms(facts.bms)}
            </section>
        </div>
        <div class="ots-foot">Generated ${escapeHTML(formatTs(p.generated_at))} · refreshes every ${POLL_MS / 1000} s · read-only (ADR-006)</div>`;
}

function renderShell() {
    const root = $root();
    if (!root || root.querySelector('[data-ots-body]')) return;
    root.innerHTML = `
        <div class="view-hdr">
            <h2>OT Security — platform posture</h2>
            <div class="view-sub">Deterministic self-checks: session gate, audit-trail integrity, control surface, edge ingest. No traffic inspection.</div>
        </div>
        <div data-ots-body><div class="ots-empty">Loading…</div></div>`;
}

function renderError(message) {
    const body = $root() && $root().querySelector('[data-ots-body]');
    if (body) body.innerHTML = `<div class="ots-empty ots-error">${escapeHTML(message)}</div>`;
}

// ─── Fetch + lifecycle ──────────────────────────────────────────────
async function refresh() {
    const root = $root();
    if (!root) return;
    // core/router.js does not call deactivate(), so the timer keeps
    // running after the operator leaves. Skip the request while the
    // view is hidden instead of polling a surface nobody sees.
    if (root.hasAttribute('hidden')) return;
    renderShell();
    let res;
    try {
        res = await fetch(ENDPOINT);
    } catch (_e) {
        renderError('Posture endpoint unreachable.');
        return;
    }
    if (!res || !res.ok) {
        renderError(`Posture unavailable (HTTP ${res ? res.status : '?'}).`);
        return;
    }
    let payload;
    try {
        payload = await res.json();
    } catch (_e) {
        renderError('Posture response could not be parsed.');
        return;
    }
    const body = root.querySelector('[data-ots-body]');
    if (body) body.innerHTML = renderPosture(payload);
}

function startPolling() {
    if (_timer !== null) return;
    refresh();
    _timer = setInterval(refresh, POLL_MS);
}

function stopPolling() {
    if (_timer !== null) {
        clearInterval(_timer);
        _timer = null;
    }
}

function initOtSecurityView() {
    if (_routeRegistered) return;
    registerRoute(ROUTE_ID, {
        viewId: VIEW_ID,
        activate: () => { startPolling(); },
        deactivate: () => { stopPolling(); },
    });
    _routeRegistered = true;
}

function reset() {
    stopPolling();
    _routeRegistered = false;
}

export { initOtSecurityView };

export const __ot_security_test__ = {
    sortChecks,
    badgeFor,
    formatTs,
    renderSummary,
    renderCheck,
    renderChecks,
    renderAccess,
    renderLedger,
    renderBms,
    renderEdge,
    renderPosture,
    refresh,
    startPolling,
    stopPolling,
    isPolling: () => _timer !== null,
    reset,
    POLL_MS,
};
