/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO -- frontend/assets/js/views/device_control.js
 * Release R3-A / R3-B -- Power Controls.
 *
 * One path at a time (A | B): capacity summary, the MV transfer
 * controller, the UPS blocks and the generators, each with readings
 * and supervised switching. Below: the executable scenario library.
 *
 * Data:    GET  /api/devices            (polled while visible)
 * Control: POST /api/devices/{id}/authority | select | operate
 * MV bay:  POST /api/mv/bays/{id}/procedure
 *          POST /api/mv/procedures/{pid}/witness | step | abort
 * Library: GET  /api/power-scenarios, POST .../{id}/run (sandbox)
 *
 * Every rule is enforced by the server and only mirrored here:
 * authority, select-before-operate, forced switching sequence,
 * two-person rule. A button the server would refuse is disabled and
 * shows the server's own reason.
 *
 * HONEST SCOPE, printed permanently: the plant is SIMULATED.
 * S-SEC-01: every interpolated value is escaped; the witness password
 * is read from the field, sent once and cleared, never kept in state.
 * ADR-006: no agent can reach these routes.
 * ════════════════════════════════════════════════════════════════ */

import { registerRoute } from '../core/router.js';
import { escapeHTML } from '../core/sanitize.js';
import { getAuthHeader } from '../core/auth.js';

const VIEW_ID = 'view-device-control';
const ROUTE_ID = 'device-control';
const ENDPOINT = '/api/devices';
const MV_ENDPOINT = '/api/mv';
const SCENARIOS = '/api/power-scenarios';
const POLL_MS = 2000;
const TICK_MS = 1000;

const KIND_TITLES = {
    transfer: 'Medium-voltage transfer',
    ups: 'UPS blocks',
    generator: 'Generators and 13.8 kV bays',
};
const KIND_ORDER = ['transfer', 'ups', 'generator'];
// Lot 12 (ADR-023): Building D paths (device paths 'da' / 'db').
const D_KIND_ORDER = ['rectifier', 'sscb', 'bess', 'farm'];
const D_KIND_TITLES = {
    rectifier: 'Rectifier group (35 kV 3-phase AC in, 800 VDC out)',
    sscb: 'Bus main SSCB (800 VDC unipolar TN-S)',
    bess: 'BESS (on the 800 VDC bus)',
    farm: 'Generator farm (13.8 kV, stepped up to 35 kV)',
};
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
let _path = null;
let _library = null;
let _run = null;          // last scenario result
let _running = null;      // scenario id being run
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

function formatMw(kw) {
    const v = Number(kw);
    if (!Number.isFinite(v)) return '--';
    return (v / 1000).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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

function pathsOf(payload) {
    const out = (payload && Array.isArray(payload.paths) ? payload.paths : []).map((p) => p.path);
    const bd = payload && payload.building_d;
    if (bd && Array.isArray(bd.paths)) bd.paths.forEach((p) => out.push(`d${p.path}`));
    return out;
}

function isDPath(path) {
    return /^d[ab]$/.test(String(path || ''));
}

function pathLabel(path) {
    return isDPath(path) ? `BLDG D-${path.slice(1).toUpperCase()}` : `PATH ${String(path).toUpperCase()}`;
}

function renderDSummary(payload, path) {
    const bd = payload && payload.building_d;
    const s = bd && (bd.paths || []).find((p) => `d${p.path}` === path);
    if (!s) return '';
    const tile = (lbl, val, tone) => `<div class="dvc-tile" data-tone="${tone}">`
        + `<div class="dvc-tile-lbl">${escapeHTML(lbl)}</div><div class="dvc-tile-val">${escapeHTML(val)}</div></div>`;
    const hall = bd.load_lost ? 'LOAD LOST'
        : `${(Number(bd.demand_kw || 0) / 1000).toFixed(1)} MW on ${bd.paths_carrying} path(s)`;
    return `<section class="dvc-summary" aria-label="Building D path">`
        + tile('Rectifier input', s.input_closed ? (s.input_live ? s.source : 'NO INPUT') : 'OPEN',
               s.input_live ? (s.source === 'FARM' ? 'warn' : 'ok') : 'crit')
        + tile('800 VDC bus', s.bus_energized ? `${Number(s.bus_v).toFixed(0)} V` : 'DEAD', s.bus_energized ? 'ok' : 'crit')
        + tile('Path load', `${(Number(s.carrying_kw) / 1000).toFixed(1)} MW`, 'info')
        + tile('BESS', `${s.bess_breaker} · SOC ${Number(s.soc_pct).toFixed(1)} %`, s.bess_breaker === 'CLOSED' ? 'ok' : 'warn')
        + tile('Rectifiers', `${s.rect_units_in} of ${s.rect_units}${s.rect_n1_ok ? ' (N+1)' : ' (N)'}`, s.rect_n1_ok ? 'ok' : 'warn')
        + tile('Hall', hall, bd.load_lost ? 'crit' : 'info')
        + '</section>'
        + `<div class="dvc-notice" role="note">${escapeHTML(bd.notice || '')}</div>`;
}

function groupByKind(devices, path) {
    const order = isDPath(path) ? D_KIND_ORDER : KIND_ORDER;
    const groups = new Map(order.map((k) => [k, []]));
    (Array.isArray(devices) ? devices : []).forEach((d) => {
        if (d.path === path && groups.has(d.kind)) groups.get(d.kind).push(d);
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
    if (e.event === 'procedure_step') {
        const w = e.witness ? `, witness ${e.witness}` : '';
        return `step ${e.step}: ${e.label || e.operation || ''}${w}${e.complete ? ' (procedure complete)' : ''}`;
    }
    if (e.event === 'procedure_started') return `procedure started: ${stateLabel(e.goal)}`;
    if (e.event === 'procedure_witness') return `second person approved step ${e.step}`;
    if (e.event === 'procedure_aborted') return `procedure aborted at step ${e.at_step}`;
    if (e.event === 'procedure_blocked') return `step ${e.step} BLOCKED: ${e.detail || ''}`;
    return `${e.command ? e.command + ': ' : ''}${e.detail || ''}`;
}

// ─── Render: path summary ───────────────────────────────────────────
function check(ok, label) {
    return `<span class="dvc-check dvc-check-${ok ? 'ok' : 'bad'}">${escapeHTML(label)}: ${ok ? 'MET' : 'NOT MET'}</span>`;
}

function renderSummary(s) {
    if (!s) return '';
    const onGens = s.source === 'GENERATORS';
    return `
        <section class="dvc-summary" aria-label="Path capacity">
            <div class="dvc-tile">
                <div class="dvc-tile-lbl">Source</div>
                <div class="dvc-tile-val dvc-tile-${onGens ? 'warn' : 'ok'}">${escapeHTML(stateLabel(s.source))}</div>
                <div class="dvc-tile-sub">IT load ${escapeHTML(formatMw(s.it_load_kw))} MW of ${escapeHTML(formatMw(s.it_design_kw))} MW design</div>
            </div>
            <div class="dvc-tile">
                <div class="dvc-tile-lbl">UPS capacity</div>
                <div class="dvc-tile-val">${escapeHTML(formatMw(s.ups_capacity_kw))} <small>MW</small></div>
                <div class="dvc-tile-sub">${escapeHTML(String(s.ups_in_service))} of ${escapeHTML(String(s.ups_total))} blocks in service</div>
                <div class="dvc-checks">${check(s.ups_n_ok, 'N')}${check(s.ups_n_plus_1_ok, 'N+1')}</div>
            </div>
            <div class="dvc-tile">
                <div class="dvc-tile-lbl">UPS losses (model)</div>
                <div class="dvc-tile-val">${escapeHTML(String(s.ups_losses_kw))} <small>kW</small></div>
                <div class="dvc-tile-sub">${s.ups_protected ? 'All carrying blocks on the inverter' : 'At least one block on static bypass'}</div>
            </div>
            <div class="dvc-tile">
                <div class="dvc-tile-lbl">Generation available</div>
                <div class="dvc-tile-val">${escapeHTML(formatMw(s.gen_available_kw))} <small>MW</small></div>
                <div class="dvc-tile-sub">${escapeHTML(String(s.gen_available))} of ${escapeHTML(String(s.gen_total))} bays in service</div>
                <div class="dvc-checks">${check(s.gen_n_ok, 'N')}${check(s.gen_n_plus_1_ok, 'N+1')}</div>
                <dl class="dvc-floor">
                    <div><dt>Total load floor</dt><dd>${escapeHTML(formatMw(s.generation_floor_kw))} MW</dd></div>
                    <div><dt>IT load only</dt><dd>${escapeHTML(formatMw(s.it_design_kw))} MW
                        <span class="dvc-floor-note">(N+1 ${s.gen_n_plus_1_it_only_ok ? 'met' : 'not met'}, not used)</span></dd></div>
                </dl>
            </div>
        </section>`;
}

// ─── Render: device card ────────────────────────────────────────────
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

function renderIndications(device) {
    const list = Array.isArray(device.indications) ? device.indications : [];
    if (!list.length) return '';
    return `<div class="dvc-inds">${list.map((i) => `
        <span class="dvc-ind dvc-ind-${escapeHTML(String(i.value || '').toLowerCase())}">
            <span class="dvc-ind-lbl">${escapeHTML(i.label || '')}</span>
            <span class="dvc-ind-val">${escapeHTML(i.value || '')}</span>
        </span>`).join('')}</div>`;
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

function renderBlocked(items) {
    const blocked = items.filter((c) => !c.permitted && c.blocked_reason);
    const distinct = [...new Set(blocked.map((c) => c.blocked_reason))];
    if (!blocked.length) return '';
    // One line when a single reason blocks everything (authority);
    // otherwise each reason is tied to what it blocks.
    const lis = distinct.length === 1
        ? `<li>${escapeHTML(distinct[0])}</li>`
        : blocked.map((c) => `<li><span class="dvc-blocked-cmd">${escapeHTML(c.label || '')}:</span> ${escapeHTML(c.blocked_reason)}</li>`).join('');
    return `<ul class="dvc-blocked">${lis}</ul>`;
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
    return `<div class="dvc-cmds">${buttons}</div>${renderBlocked(commands)}`;
}

function renderProcedure(device, proc) {
    const steps = (Array.isArray(proc.steps) ? proc.steps : []).map((s) => {
        const tags = [
            s.safety_gate ? '<span class="dvc-tag dvc-tag-gate">safety gate</span>' : '',
            s.two_person ? '<span class="dvc-tag dvc-tag-two">two persons</span>' : '',
            s.witness ? `<span class="dvc-tag">witness ${escapeHTML(s.witness)}</span>` : '',
        ].join('');
        let action = '';
        if (s.status === 'next') {
            const needsWitness = s.two_person && !s.witness_valid;
            action = needsWitness ? `
                <div class="dvc-witness">
                    <div class="dvc-witness-title">A second person (Safety Officer or above) must approve this step.</div>
                    <input class="dvc-input" type="text" autocomplete="off" placeholder="Witness username"
                        aria-label="Witness username" data-dvc-witness-user="${escapeHTML(proc.procedure_id)}">
                    <input class="dvc-input" type="password" autocomplete="off" placeholder="Witness password"
                        aria-label="Witness password" data-dvc-witness-pass="${escapeHTML(proc.procedure_id)}">
                    <button type="button" class="dvc-btn" data-dvc-action="witness" data-device="${escapeHTML(device.id)}"
                        data-procedure="${escapeHTML(proc.procedure_id)}" data-step="${escapeHTML(String(s.step))}">Approve as second person</button>
                </div>` : `
                <button type="button" class="dvc-btn dvc-btn-operate" data-dvc-action="step" data-device="${escapeHTML(device.id)}"
                    data-procedure="${escapeHTML(proc.procedure_id)}" data-step="${escapeHTML(String(s.step))}">Execute step ${escapeHTML(String(s.step))}</button>`;
        }
        return `
            <li class="dvc-step dvc-step-${escapeHTML(s.status || '')}">
                <div class="dvc-step-row">
                    <span class="dvc-step-n">${escapeHTML(String(s.step))}</span>
                    <span class="dvc-step-lbl">${escapeHTML(s.label || s.operation || '')}</span>
                    <span class="dvc-step-status">${escapeHTML(String(s.status || '').toUpperCase())}</span>
                </div>
                <div class="dvc-step-tags">${tags}</div>
                ${action}
            </li>`;
    }).join('');
    const deviations = Number(proc.blocked_attempts) > 0
        ? `<div class="dvc-deviation">${escapeHTML(String(proc.blocked_attempts))} blocked attempt(s) recorded on this procedure.</div>` : '';
    return `
        <div class="dvc-proc" data-procedure-id="${escapeHTML(proc.procedure_id)}">
            <div class="dvc-proc-hdr">
                <span class="dvc-proc-title">Switching procedure: ${escapeHTML(proc.goal_label || proc.goal || '')}</span>
                <button type="button" class="dvc-btn dvc-btn-small" data-dvc-action="abort" data-device="${escapeHTML(device.id)}"
                    data-procedure="${escapeHTML(proc.procedure_id)}" title="Stops here. Positions are not rolled back.">Abort</button>
            </div>
            <div class="dvc-proc-sub">Operator ${escapeHTML(proc.operator || '')}. Only the next step can run.</div>
            <ol class="dvc-steps">${steps}</ol>
            ${deviations}
        </div>`;
}

function renderSwitching(device) {
    const sw = device.switching;
    if (!sw) return '';
    if (sw.procedure) return renderProcedure(device, sw.procedure);
    const goals = Array.isArray(sw.goals) ? sw.goals : [];
    const buttons = goals.map((g) => `
        <button type="button" class="dvc-btn" data-dvc-action="procedure" data-device="${escapeHTML(device.id)}"
            data-goal="${escapeHTML(g.goal || '')}"${g.permitted ? '' : ' disabled'}>${escapeHTML(g.label || g.goal || '')}</button>`).join('');
    return `
        <div class="dvc-sw">
            <div class="dvc-sw-lbl">13.8 kV bay switching (forced procedure)</div>
            <div class="dvc-cmds">${buttons}</div>
            ${renderBlocked(goals)}
        </div>`;
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
                <span class="dvc-chip">${escapeHTML(pathLabel(device.path || '-'))}</span>
            </header>
            <div class="dvc-state">
                <span class="dvc-badge dvc-badge-${tone}">${escapeHTML(stateLabel(device.state))}</span>
                <span class="dvc-state-text">${escapeHTML(status.text || '')}</span>
            </div>
            ${renderIndications(device)}
            ${renderAuthority(device)}
            ${renderReadings(device)}
            ${renderCommands(device)}
            ${renderSwitching(device)}
            ${msg ? `<div class="dvc-msg dvc-msg-${msg.tone === 'ok' ? 'ok' : 'crit'}" role="status">${escapeHTML(msg.text)}</div>` : ''}
        </article>`;
}

// ─── Render: log and scenarios ──────────────────────────────────────
function renderEvents(events) {
    const rows = (Array.isArray(events) ? events : []).map((e) => `
        <tr class="dvc-ev-${/blocked|refused/.test(String(e.event)) ? 'refused' : 'normal'}">
            <td class="dvc-mono">${escapeHTML(formatClock(e.ts))}</td>
            <td class="dvc-mono">${escapeHTML(e.device_id || '')}</td>
            <td>${escapeHTML(stateLabel(e.event).toUpperCase())}</td>
            <td>${escapeHTML(eventDetail(e))}</td>
            <td>${escapeHTML(e.actor || '')}</td>
        </tr>`).join('');
    return `
        <table class="dvc-table">
            <thead><tr><th>Time (UTC)</th><th>Device</th><th>Event</th><th>Detail</th><th>Person</th></tr></thead>
            <tbody>${rows || '<tr><td colspan="5" class="dvc-empty">No control actions since boot.</td></tr>'}</tbody>
        </table>`;
}

function renderRun(run) {
    if (!run) return '';
    const steps = (Array.isArray(run.steps) ? run.steps : []).map((s) => `
        <tr class="dvc-ev-${s.as_expected ? 'normal' : 'refused'}">
            <td class="dvc-mono">${escapeHTML(String(s.step ?? ''))}</td>
            <td>${escapeHTML(stateLabel(s.action))} ${escapeHTML(String(s.what || ''))}</td>
            <td class="dvc-mono">${escapeHTML(String(s.target || ''))}</td>
            <td>${escapeHTML(String(s.expected || '').toUpperCase())}</td>
            <td>${escapeHTML(String(s.outcome || '').toUpperCase())}${s.detail ? ': ' + escapeHTML(s.detail) : ''}</td>
            <td>${s.as_expected ? 'as expected' : 'UNEXPECTED'}</td>
        </tr>`).join('');
    const criteria = (Array.isArray(run.criteria) ? run.criteria : []).map((c) => `
        <li class="dvc-crit-${c.passed ? 'ok' : 'bad'}">${c.passed ? 'MET' : 'NOT MET'}:
            <span class="dvc-mono">${escapeHTML(JSON.stringify(c.criterion))}</span>
            (actual ${escapeHTML(JSON.stringify(c.actual))})</li>`).join('');
    return `
        <div class="dvc-run" data-run-id="${escapeHTML(run.scenario_id || '')}">
            <div class="dvc-run-hdr">
                <span class="dvc-badge dvc-badge-${run.passed ? 'ok' : 'crit'}">${run.passed ? 'PASS' : 'FAIL'}</span>
                <span class="dvc-run-title">${escapeHTML(run.scenario_id || '')} v${escapeHTML(run.version || '')}: ${escapeHTML(run.title || '')}</span>
            </div>
            <div class="dvc-run-sub">Sandbox run. ${escapeHTML(String(run.blocked_events ?? 0))} operation(s) blocked by interlocks ·
                ${escapeHTML(String(run.simulated_seconds ?? 0))} s simulated ·
                ${run.ledger_entry_id ? 'ledger entry ' + escapeHTML(String(run.ledger_entry_id).slice(0, 8)) : 'not chained (no ledger)'}</div>
            <table class="dvc-table">
                <thead><tr><th>#</th><th>Action</th><th>Target</th><th>Expected</th><th>Outcome</th><th>Verdict</th></tr></thead>
                <tbody>${steps}</tbody>
            </table>
            <ul class="dvc-criteria">${criteria}</ul>
        </div>`;
}

function renderLibrary() {
    if (!_library) return '<div class="dvc-empty">Scenario library not loaded.</div>';
    const rows = (Array.isArray(_library.scenarios) ? _library.scenarios : []).map((s) => `
        <tr>
            <td class="dvc-mono">${escapeHTML(s.scenario_id || '')}</td>
            <td>${escapeHTML(s.title || '')}<div class="dvc-lib-desc">${escapeHTML(s.description || '')}</div></td>
            <td>${escapeHTML(stateLabel(s.category))}</td>
            <td>${s.safety_critical ? '<span class="dvc-tag dvc-tag-gate">safety critical</span>' : ''}</td>
            <td><button type="button" class="dvc-btn" data-dvc-action="run" data-scenario="${escapeHTML(s.scenario_id || '')}"
                ${_running ? 'disabled' : ''}>${_running === s.scenario_id ? 'Running…' : 'Run in sandbox'}</button></td>
        </tr>`).join('');
    return `
        <div class="dvc-rules">${escapeHTML(_library.sandbox_notice || '')}</div>
        <table class="dvc-table">
            <thead><tr><th>ID</th><th>Scenario</th><th>Category</th><th></th><th></th></tr></thead>
            <tbody>${rows}</tbody>
        </table>
        ${renderRun(_run)}`;
}

function renderPanels(payload) {
    const p = payload || {};
    const paths = pathsOf(p);
    if (!paths.includes(_path)) _path = paths[0] || null;
    const tabs = paths.map((path) => `
        <button type="button" class="dvc-tab${path === _path ? ' is-active' : ''}" data-dvc-action="path"
            data-path="${escapeHTML(path)}" aria-pressed="${path === _path ? 'true' : 'false'}">${escapeHTML(pathLabel(path))}</button>`).join('');
    const summary = (p.paths || []).find((s) => s.path === _path);
    const groups = groupByKind(p.devices, _path);
    const dPath = isDPath(_path);
    const sections = (dPath ? D_KIND_ORDER : KIND_ORDER).map((kind) => {
        const list = groups.get(kind);
        const cards = list.length
            ? list.map(renderDevice).join('')
            : '<div class="dvc-empty">None in the plant design.</div>';
        const title = dPath ? D_KIND_TITLES[kind] : KIND_TITLES[kind];
        return `
            <section class="dvc-section" data-kind="${kind}">
                <h3>${escapeHTML(title)} <span class="dvc-count">${list.length}</span></h3>
                <div class="dvc-grid">${cards}</div>
            </section>`;
    }).join('');
    return `
        <div class="dvc-notice" role="note">${escapeHTML(p.notice || '')}</div>
        <div class="dvc-rules">Commands need the FACILITY MANAGER role, the device in REMOTE, and a second confirmation.
            Medium-voltage bays move only through a forced procedure; earthing and LOTO need a second person.
            Every action is written to the Forensic Ledger.</div>
        <div class="dvc-tabs" role="group" aria-label="Redundancy path">${tabs}</div>
        ${dPath ? renderDSummary(p, _path) : renderSummary(summary)}
        ${sections}
        <section class="dvc-section" data-section="log">
            <h3>Control log</h3>
            ${renderEvents(p.events)}
        </section>
        <section class="dvc-section" data-section="library">
            <h3>Scenario library <span class="dvc-count">${_library && _library.scenarios ? _library.scenarios.length : 0}</span></h3>
            ${renderLibrary()}
        </section>`;
}

function renderShell() {
    const root = $root();
    if (!root || root.querySelector('[data-dvc-body]')) return;
    root.innerHTML = `
        <div class="view-hdr">
            <h2>Power Controls</h2>
            <div class="view-sub">UPS blocks, medium-voltage transfer and generators: readings, capacity checks and supervised switching.</div>
        </div>
        <div data-dvc-body><div class="dvc-empty">Loading…</div></div>`;
    root.addEventListener('click', onClick);
}

// A repaint must not wipe what a person is typing in a witness form.
function typing() {
    const root = $root();
    const el = document.activeElement;
    return Boolean(root && el && root.contains(el) && el.classList && el.classList.contains('dvc-input'));
}

function paint(force) {
    const root = $root();
    const body = root && root.querySelector('[data-dvc-body]');
    if (!body || !_payload) return;
    if (!force && typing()) return;
    body.innerHTML = renderPanels(_payload);
}

function renderError(message) {
    const body = $root() && $root().querySelector('[data-dvc-body]');
    if (body) body.innerHTML = `<div class="dvc-empty dvc-error">${escapeHTML(message)}</div>`;
}

// ─── Network ────────────────────────────────────────────────────────
async function getJson(url) {
    let res;
    try {
        res = await fetch(url, { headers: getAuthHeader() });
    } catch (_e) {
        return { ok: false, detail: 'unreachable' };
    }
    if (!res || !res.ok) return { ok: false, detail: `HTTP ${res ? res.status : '?'}` };
    try {
        return { ok: true, data: await res.json() };
    } catch (_e) {
        return { ok: false, detail: 'could not be parsed' };
    }
}

async function refresh(force) {
    const root = $root();
    if (!root || root.hasAttribute('hidden')) return;
    renderShell();
    const out = await getJson(ENDPOINT);
    if (!out.ok) {
        renderError(`Devices unavailable (${out.detail}).`);
        return;
    }
    _payload = out.data;
    if (_library === null) {
        const lib = await getJson(SCENARIOS);
        _library = lib.ok ? lib.data : { scenarios: [], sandbox_notice: `Scenario library unavailable (${lib.detail}).` };
    }
    paint(force);
}

async function post(url, body) {
    let res;
    try {
        res = await fetch(url, {
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

function devicePost(deviceId, verb, body) {
    return post(`${ENDPOINT}/${encodeURIComponent(deviceId)}/${verb}`, body);
}

function report(deviceId, out, okText) {
    _messages.set(deviceId, out.ok
        ? { tone: 'ok', text: okText }
        : { tone: 'crit', text: `Refused: ${out.detail}` });
}

function ledgerNote(data) {
    return data && data.ledger_entry_id
        ? ` Ledger entry ${String(data.ledger_entry_id).slice(0, 8)}.`
        : ' Ledger unavailable: action NOT chained.';
}

async function doAuthority(deviceId, mode) {
    _pending.delete(deviceId);
    const out = await devicePost(deviceId, 'authority', { authority: mode });
    report(deviceId, out, `Authority set to ${mode}.`);
    await refresh(true);
}

async function doSelect(deviceId, command) {
    const out = await devicePost(deviceId, 'select', { command });
    if (out.ok) {
        _pending.set(deviceId, {
            token: out.data.select_token,
            command: out.data.command,
            label: out.data.label,
            description: out.data.description,
            expiresAt: _now() + (Number(out.data.expires_in_s) || 0) * 1000,
        });
        _messages.delete(deviceId);
        paint(true);
        return;
    }
    report(deviceId, out, '');
    await refresh(true);
}

async function doOperate(deviceId) {
    const pending = _pending.get(deviceId);
    if (!pending) return;
    _pending.delete(deviceId);
    const out = await devicePost(deviceId, 'operate', { select_token: pending.token });
    report(deviceId, out, `${pending.label || pending.command} executed.${ledgerNote(out.data)}`);
    await refresh(true);
}

function doCancel(deviceId) {
    _pending.delete(deviceId);
    _messages.set(deviceId, { tone: 'ok', text: 'Selection cancelled. Nothing moved.' });
    paint(true);
}

async function doProcedure(deviceId, goal) {
    const out = await post(`${MV_ENDPOINT}/bays/${encodeURIComponent(deviceId)}/procedure`, { goal });
    report(deviceId, out, 'Switching procedure started. Nothing has moved yet.');
    await refresh(true);
}

async function doStep(deviceId, procedureId, step) {
    const out = await post(`${MV_ENDPOINT}/procedures/${encodeURIComponent(procedureId)}/step`, { step: Number(step) });
    const done = out.ok && out.data.procedure && out.data.procedure.complete;
    report(deviceId, out, `Step ${step} executed.${done ? ' Procedure complete.' : ''}${ledgerNote(out.data)}`);
    await refresh(true);
}

async function doWitness(deviceId, procedureId, step) {
    const root = $root();
    const id = CSS.escape(procedureId);
    const userEl = root && root.querySelector(`[data-dvc-witness-user="${id}"]`);
    const passEl = root && root.querySelector(`[data-dvc-witness-pass="${id}"]`);
    const username = userEl ? userEl.value.trim() : '';
    const password = passEl ? passEl.value : '';
    if (passEl) passEl.value = '';
    if (!username || !password) {
        _messages.set(deviceId, { tone: 'crit', text: 'The witness must type their own username and password.' });
        paint(true);
        return;
    }
    const out = await post(`${MV_ENDPOINT}/procedures/${encodeURIComponent(procedureId)}/witness`, {
        step: Number(step), witness_username: username, witness_password: password,
    });
    report(deviceId, out, `Step ${step} approved by ${username}. The operator can execute it now.`);
    await refresh(true);
}

async function doAbort(deviceId, procedureId) {
    const out = await post(`${MV_ENDPOINT}/procedures/${encodeURIComponent(procedureId)}/abort`, {});
    report(deviceId, out, 'Procedure aborted. Positions were NOT rolled back: use Return to service.');
    await refresh(true);
}

async function doRun(scenarioId) {
    _running = scenarioId;
    paint(true);
    const out = await post(`${SCENARIOS}/${encodeURIComponent(scenarioId)}/run`, {});
    _running = null;
    _run = out.ok ? out.data : {
        scenario_id: scenarioId, version: '', title: `Run failed: ${out.detail}`,
        passed: false, steps: [], criteria: [],
    };
    paint(true);
}

function onClick(event) {
    const target = event.target && event.target.closest
        ? event.target.closest('[data-dvc-action]') : null;
    if (!target || target.disabled) return undefined;
    const action = target.getAttribute('data-dvc-action');
    const deviceId = target.getAttribute('data-device');
    const procedureId = target.getAttribute('data-procedure');
    if (action === 'path') {
        _path = target.getAttribute('data-path');
        paint(true);
        return undefined;
    }
    if (action === 'run') return doRun(target.getAttribute('data-scenario'));
    if (!deviceId) return undefined;
    if (action === 'authority') return doAuthority(deviceId, target.getAttribute('data-mode'));
    if (action === 'select') return doSelect(deviceId, target.getAttribute('data-command'));
    if (action === 'operate') return doOperate(deviceId);
    if (action === 'cancel') return doCancel(deviceId);
    if (action === 'procedure') return doProcedure(deviceId, target.getAttribute('data-goal'));
    if (action === 'step') return doStep(deviceId, procedureId, target.getAttribute('data-step'));
    if (action === 'witness') return doWitness(deviceId, procedureId, target.getAttribute('data-step'));
    if (action === 'abort') return doAbort(deviceId, procedureId);
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
    if (expired) paint(true);
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
    _path = null;
    _library = null;
    _run = null;
    _running = null;
    _pending.clear();
    _messages.clear();
    _now = () => Date.now();
}

export { initDeviceControlView };

export const __device_control_test__ = {
    stateLabel,
    formatValue,
    formatMw,
    formatClock,
    groupByKind,
    pathsOf,
    renderDSummary,
    eventDetail,
    renderSummary,
    renderDevice,
    renderPanels,
    renderEvents,
    renderRun,
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
    setLibrary: (l) => { _library = l; },
    setPath: (p) => { _path = p; },
    POLL_MS,
    ROUTE_ID,
    VIEW_ID,
};
