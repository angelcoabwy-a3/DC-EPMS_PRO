/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO -- frontend/assets/js/views/device_control.js
 * Release R3-A -- Power Controls: one panel per UPS, transfer switch
 * and generator, with readings and supervised switching.
 *
 * Data: GET /api/devices (polled while the view is visible).
 * Control: POST /api/devices/{id}/authority | select | operate.
 *
 * Control discipline, all enforced by the server and only mirrored
 * here:
 *   - AUTO / REMOTE / LOCAL authority per device. Commands run only
 *     in REMOTE.
 *   - Select-before-operate: a command is first SELECTED (nothing
 *     moves), then confirmed with OPERATE inside the time window.
 *   - The operator's role comes from the session; a button that the
 *     server would refuse is disabled with the server's own reason.
 *
 * HONEST SCOPE, printed permanently on the view: devices are
 * SIMULATED. S-SEC-01: every interpolated value is escaped. ADR-006:
 * no agent can reach these routes.
 * ════════════════════════════════════════════════════════════════ */

import { registerRoute } from '../core/router.js';
import { escapeHTML } from '../core/sanitize.js';
import { getAuthHeader } from '../core/auth.js';

const VIEW_ID = 'view-device-control';
const ROUTE_ID = 'device-control';
const ENDPOINT = '/api/devices';
const POLL_MS = 2000;
const TICK_MS = 1000;

const KIND_TITLES = {
    ups: 'UPS',
    transfer: 'Transfer switches',
    generator: 'Generators',
};
const KIND_ORDER = ['ups', 'transfer', 'generator'];
const TONES = ['ok', 'warn', 'crit', 'info'];
const AUTHORITY_HINT = {
    AUTO: 'The device follows its own controller. Remote commands are refused.',
    REMOTE: 'Commands from this panel are accepted.',
    LOCAL: 'Key switch at the equipment (bench simulation). Remote commands are refused.',
};

let _routeRegistered = false;
let _pollTimer = null;
let _tickTimer = null;
let _payload = null;
// deviceId -> { token, command, label, description, expiresAt }
const _pending = new Map();
// deviceId -> { tone: 'ok' | 'crit', text }
const _messages = new Map();
let _now = () => Date.now();

function $root() {
    return document.getElementById(VIEW_ID);
}

// ─── Pure helpers ───────────────────────────────────────────────────
function stateLabel(state) {
    return String(state || '').replace(/_/g, ' ');
}

function formatValue(reading) {
    const v = Number(reading && reading.value);
    if (!Number.isFinite(v)) return '--';
    return v.toLocaleString('en-US', { maximumFractionDigits: 1 });
}

function formatClock(unixSeconds) {
    const n = Number(unixSeconds);
    if (!Number.isFinite(n)) return '--:--:--';
    try {
        return new Date(n * 1000).toISOString().slice(11, 19);
    } catch (_e) {
        return '--:--:--';
    }
}

function secondsLeft(pending) {
    if (!pending) return 0;
    return Math.max(0, Math.ceil((pending.expiresAt - _now()) / 1000));
}

function groupByKind(devices) {
    const groups = new Map(KIND_ORDER.map((k) => [k, []]));
    (Array.isArray(devices) ? devices : []).forEach((d) => {
        if (groups.has(d.kind)) groups.get(d.kind).push(d);
    });
    return groups;
}

function eventDetail(e) {
    if (e.event === 'command') {
        return `${e.command || ''}: ${stateLabel(e.from_state)} to ${stateLabel(e.to_state)}`;
    }
    if (e.event === 'authority') {
        const sim = e.source === 'bench_simulation' ? ' (bench simulation)' : '';
        return `${e.previous || ''} to ${e.authority || ''}${sim}`;
    }
    return `${e.command ? e.command + ': ' : ''}${e.detail || ''}`;
}

// ─── Render ─────────────────────────────────────────────────────────
function renderAuthority(device) {
    const buttons = ['AUTO', 'REMOTE', 'LOCAL'].map((mode) => {
        const active = device.authority === mode;
        return `<button type="button" class="dvc-auth-btn${active ? ' is-active' : ''}"
            data-dvc-action="authority" data-device="${escapeHTML(device.id)}" data-mode="${mode}"
            aria-pressed="${active ? 'true' : 'false'}" title="${escapeHTML(AUTHORITY_HINT[mode])}"${active ? ' disabled' : ''}>${mode}</button>`;
    }).join('');
    return `
        <div class="dvc-auth" role="group" aria-label="Control authority">
            <span class="dvc-auth-lbl">Authority</span>
            <div class="dvc-auth-seg">${buttons}</div>
        </div>
        <div class="dvc-auth-hint">${escapeHTML(AUTHORITY_HINT[device.authority] || '')}</div>`;
}

function renderReadings(device) {
    const rows = (Array.isArray(device.readings) ? device.readings : []).map((r) => `
        <div class="dvc-reading">
            <dt>${escapeHTML(r.label || '')}</dt>
            <dd><span class="dvc-reading-val">${escapeHTML(formatValue(r))}</span>
                <span class="dvc-reading-unit">${escapeHTML(r.unit || '')}</span></dd>
        </div>`).join('');
    return `<dl class="dvc-readings">${rows}</dl>`;
}

function renderCommands(device) {
    const pending = _pending.get(device.id);
    if (pending && secondsLeft(pending) > 0) {
        return `
            <div class="dvc-confirm" role="alertdialog" aria-label="Confirm command">
                <div class="dvc-confirm-title">Selected: ${escapeHTML(pending.label || pending.command)}</div>
                <div class="dvc-confirm-desc">${escapeHTML(pending.description || '')}</div>
                <div class="dvc-confirm-row">
                    <button type="button" class="dvc-btn dvc-btn-operate" data-dvc-action="operate"
                        data-device="${escapeHTML(device.id)}">Operate</button>
                    <button type="button" class="dvc-btn" data-dvc-action="cancel"
                        data-device="${escapeHTML(device.id)}">Cancel</button>
                    <span class="dvc-countdown">Nothing has moved yet. Expires in
                        <span data-dvc-countdown="${escapeHTML(device.id)}">${secondsLeft(pending)}</span> s</span>
                </div>
            </div>`;
    }
    const commands = Array.isArray(device.commands) ? device.commands : [];
    const buttons = commands.map((c) => `
        <button type="button" class="dvc-btn" data-dvc-action="select"
            data-device="${escapeHTML(device.id)}" data-command="${escapeHTML(c.command || '')}"
            title="${escapeHTML(c.description || '')}"${c.permitted ? '' : ' disabled'}>${escapeHTML(c.label || c.command || '')}</button>`).join('');
    // One line when a single reason blocks everything (authority);
    // otherwise each reason is tied to the command it blocks.
    const blockedCmds = commands.filter((c) => !c.permitted && c.blocked_reason);
    const distinct = [...new Set(blockedCmds.map((c) => c.blocked_reason))];
    let items = '';
    if (distinct.length === 1) {
        items = `<li>${escapeHTML(distinct[0])}</li>`;
    } else {
        items = blockedCmds.map((c) => `<li><span class="dvc-blocked-cmd">${escapeHTML(c.label || c.command || '')}:</span> ${escapeHTML(c.blocked_reason)}</li>`).join('');
    }
    const blocked = items ? `<ul class="dvc-blocked">${items}</ul>` : '';
    return `<div class="dvc-cmds">${buttons}</div>${blocked}`;
}

function renderDevice(device) {
    const status = device.status || {};
    const tone = TONES.includes(status.tone) ? status.tone : 'info';
    const msg = _messages.get(device.id);
    const model = [device.vendor, device.model].filter(Boolean).join(' ');
    return `
        <article class="dvc-card dvc-tone-${tone}" data-device-id="${escapeHTML(device.id)}">
            <header class="dvc-card-hdr">
                <div>
                    <div class="dvc-card-title">${escapeHTML(device.display || device.id)}</div>
                    <div class="dvc-card-sub">${escapeHTML(device.id)}${model ? ' · ' + escapeHTML(model) : ''}</div>
                </div>
                <span class="dvc-chip">PATH ${escapeHTML(String(device.path || '-').toUpperCase())}</span>
            </header>
            <div class="dvc-state">
                <span class="dvc-badge dvc-badge-${tone}">${escapeHTML(stateLabel(device.state))}</span>
                <span class="dvc-state-text">${escapeHTML(status.text || '')}</span>
            </div>
            ${renderAuthority(device)}
            ${renderReadings(device)}
            ${renderCommands(device)}
            ${msg ? `<div class="dvc-msg dvc-msg-${msg.tone === 'ok' ? 'ok' : 'crit'}" role="status">${escapeHTML(msg.text)}</div>` : ''}
        </article>`;
}

function renderEvents(events) {
    const rows = (Array.isArray(events) ? events : []).map((e) => `
        <tr class="dvc-ev-${escapeHTML(e.event || '')}">
            <td class="dvc-mono">${escapeHTML(formatClock(e.ts))}</td>
            <td class="dvc-mono">${escapeHTML(e.device_id || '')}</td>
            <td>${escapeHTML(String(e.event || '').toUpperCase())}</td>
            <td>${escapeHTML(eventDetail(e))}</td>
            <td>${escapeHTML(e.actor || '')}</td>
        </tr>`).join('');
    return `
        <table class="dvc-table">
            <thead><tr><th>Time (UTC)</th><th>Device</th><th>Event</th><th>Detail</th><th>Operator</th></tr></thead>
            <tbody>${rows || '<tr><td colspan="5" class="dvc-empty">No control actions since boot.</td></tr>'}</tbody>
        </table>`;
}

function renderPanels(payload) {
    const p = payload || {};
    const groups = groupByKind(p.devices);
    const sections = KIND_ORDER.map((kind) => {
        const list = groups.get(kind);
        const cards = list.length
            ? list.map(renderDevice).join('')
            : '<div class="dvc-empty">None in the site model.</div>';
        return `
            <section class="dvc-section" data-kind="${kind}">
                <h3>${escapeHTML(KIND_TITLES[kind])} <span class="dvc-count">${list.length}</span></h3>
                <div class="dvc-grid">${cards}</div>
            </section>`;
    }).join('');
    return `
        <div class="dvc-notice" role="note">${escapeHTML(p.notice || '')}</div>
        <div class="dvc-rules">Commands need the FACILITY MANAGER role, the device in REMOTE, and a second confirmation.
            Every action is written to the Forensic Ledger.</div>
        ${sections}
        <section class="dvc-section">
            <h3>Control log</h3>
            ${renderEvents(p.events)}
        </section>`;
}

function renderShell() {
    const root = $root();
    if (!root || root.querySelector('[data-dvc-body]')) return;
    root.innerHTML = `
        <div class="view-hdr">
            <h2>Power Controls</h2>
            <div class="view-sub">Readings and supervised switching for UPS, transfer switches and generators.</div>
        </div>
        <div data-dvc-body><div class="dvc-empty">Loading…</div></div>`;
    root.addEventListener('click', onClick);
}

function paint() {
    const root = $root();
    const body = root && root.querySelector('[data-dvc-body]');
    if (body && _payload) body.innerHTML = renderPanels(_payload);
}

function renderError(message) {
    const body = $root() && $root().querySelector('[data-dvc-body]');
    if (body) body.innerHTML = `<div class="dvc-empty dvc-error">${escapeHTML(message)}</div>`;
}

// ─── Network ────────────────────────────────────────────────────────
async function refresh() {
    const root = $root();
    if (!root || root.hasAttribute('hidden')) return;
    renderShell();
    let res;
    try {
        res = await fetch(ENDPOINT, { headers: getAuthHeader() });
    } catch (_e) {
        renderError('Device endpoint unreachable.');
        return;
    }
    if (!res || !res.ok) {
        renderError(`Devices unavailable (HTTP ${res ? res.status : '?'}).`);
        return;
    }
    try {
        _payload = await res.json();
    } catch (_e) {
        renderError('Device response could not be parsed.');
        return;
    }
    paint();
}

async function post(deviceId, verb, body) {
    let res;
    try {
        res = await fetch(`${ENDPOINT}/${encodeURIComponent(deviceId)}/${verb}`, {
            method: 'POST',
            headers: Object.assign({ 'Content-Type': 'application/json' }, getAuthHeader()),
            // Legacy role fields are honoured by the server only when no
            // session token exists and the session gate is off.
            body: JSON.stringify(Object.assign(
                { actor_role: 'SME_L6', user: 'dashboard-operator' }, body)),
        });
    } catch (_e) {
        return { ok: false, detail: 'Server unreachable.' };
    }
    let data = null;
    try { data = await res.json(); } catch (_e) { data = null; }
    if (!res.ok) {
        const detail = data && typeof data.detail === 'string' ? data.detail : `HTTP ${res.status}`;
        return { ok: false, detail };
    }
    return { ok: true, data: data || {} };
}

async function doAuthority(deviceId, mode) {
    _pending.delete(deviceId);
    const out = await post(deviceId, 'authority', { authority: mode });
    _messages.set(deviceId, out.ok
        ? { tone: 'ok', text: `Authority set to ${mode}.` }
        : { tone: 'crit', text: `Refused: ${out.detail}` });
    await refresh();
}

async function doSelect(deviceId, command) {
    const out = await post(deviceId, 'select', { command });
    if (out.ok) {
        _pending.set(deviceId, {
            token: out.data.select_token,
            command: out.data.command,
            label: out.data.label,
            description: out.data.description,
            expiresAt: _now() + (Number(out.data.expires_in_s) || 0) * 1000,
        });
        _messages.delete(deviceId);
        paint();
        return;
    }
    _messages.set(deviceId, { tone: 'crit', text: `Refused: ${out.detail}` });
    await refresh();
}

async function doOperate(deviceId) {
    const pending = _pending.get(deviceId);
    if (!pending) return;
    _pending.delete(deviceId);
    const out = await post(deviceId, 'operate', { select_token: pending.token });
    if (out.ok) {
        const ledger = out.data.ledger_entry_id
            ? ` Ledger entry ${String(out.data.ledger_entry_id).slice(0, 8)}.`
            : ' Ledger unavailable: action NOT chained.';
        _messages.set(deviceId, { tone: 'ok', text: `${pending.label || pending.command} executed.${ledger}` });
    } else {
        _messages.set(deviceId, { tone: 'crit', text: `Refused: ${out.detail}` });
    }
    await refresh();
}

function doCancel(deviceId) {
    _pending.delete(deviceId);
    _messages.set(deviceId, { tone: 'ok', text: 'Selection cancelled. Nothing moved.' });
    paint();
}

function onClick(event) {
    const target = event.target && event.target.closest
        ? event.target.closest('[data-dvc-action]') : null;
    if (!target || target.disabled) return;
    const deviceId = target.getAttribute('data-device');
    const action = target.getAttribute('data-dvc-action');
    if (!deviceId) return;
    if (action === 'authority') return doAuthority(deviceId, target.getAttribute('data-mode'));
    if (action === 'select') return doSelect(deviceId, target.getAttribute('data-command'));
    if (action === 'operate') return doOperate(deviceId);
    if (action === 'cancel') return doCancel(deviceId);
    return undefined;
}

// One-second tick: keeps the countdown honest between polls and
// drops a selection the moment its window closes.
function tick() {
    let expired = false;
    _pending.forEach((pending, deviceId) => {
        const left = secondsLeft(pending);
        if (left <= 0) {
            _pending.delete(deviceId);
            _messages.set(deviceId, { tone: 'crit', text: 'Selection expired. Nothing moved.' });
            expired = true;
            return;
        }
        const root = $root();
        const el = root && root.querySelector(`[data-dvc-countdown="${CSS.escape(deviceId)}"]`);
        if (el) el.textContent = String(left);
    });
    if (expired) paint();
}

// ─── Lifecycle ──────────────────────────────────────────────────────
function startPolling() {
    if (_pollTimer !== null) return;
    refresh();
    _pollTimer = setInterval(refresh, POLL_MS);
    _tickTimer = setInterval(tick, TICK_MS);
}

function stopPolling() {
    if (_pollTimer !== null) { clearInterval(_pollTimer); _pollTimer = null; }
    if (_tickTimer !== null) { clearInterval(_tickTimer); _tickTimer = null; }
}

function initDeviceControlView() {
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
    _payload = null;
    _pending.clear();
    _messages.clear();
    _now = () => Date.now();
}

export { initDeviceControlView };

export const __device_control_test__ = {
    stateLabel,
    formatValue,
    formatClock,
    groupByKind,
    eventDetail,
    renderDevice,
    renderPanels,
    renderEvents,
    renderShell,
    refresh,
    tick,
    startPolling,
    stopPolling,
    reset,
    pending: _pending,
    messages: _messages,
    setNow: (fn) => { _now = fn; },
    setPayload: (p) => { _payload = p; },
    POLL_MS,
    ROUTE_ID,
    VIEW_ID,
};
