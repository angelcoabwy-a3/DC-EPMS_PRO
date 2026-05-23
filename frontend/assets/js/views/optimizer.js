/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/optimizer.js
 * ROADMAP V11 Epic 2 Batch 2.D — the Optimizer proposal queue HMI.
 *
 * Operator-facing surface for the proactive edge-agent. Lists the
 * proposals the Optimizer has queued (after passing the 2.B multi-agent
 * consensus gate) and lets an SME_L6 operator approve & actuate, or
 * reject with a reason. Per Epic 2 brief §7:
 *
 *   - The deterministic verdicts (consensus_verdict /
 *     safety_officer_veto) and the cost-heuristic figures inside each
 *     QueuedProposal are AUTHORITATIVE — never massaged for display.
 *   - LLM-authored narratives (the Optimizer's own + the rolled-up
 *     consensus rationale) route through core/sanitize.js sanitizeHTML
 *     (S-SEC-01). Structured UI (buttons, role selector) keeps
 *     per-value escapeHTML — sanitizeHTML drops <button> by design.
 *   - The Approve modal carries the operator's actor_role (default
 *     SME_L6) + an explicit ASHRAE confirmation. The server (2.C) is
 *     the authoritative RBAC gate (S-SEC-02) — this view just collects
 *     and forwards the claim.
 *   - Live refresh via the hermes:optimizer-proposal DOM event
 *     (re-emitted by core/hermes_events.js from the Hermes WS stream).
 *     A 10 s polling fallback runs alongside; both self-cancel when
 *     the view is hidden.
 *
 * Epic 5 Sprint 1:
 *   - E5.A heartbeat strip — top-of-view band that shows the loop's
 *     last tick wall-clock + most recent outcomes (sustained / drift /
 *     proposals / paced / vetoed). Refreshed by GET /api/optimizer/health
 *     on activate + on every `hermes:optimizer-tick` DOM event.
 *   - E5.C per-agent voting breakdown — each proposal card now renders
 *     a compact 6-row table with the per-agent verdicts. The Safety
 *     Officer's HARD_STOP gets an unmistakable badge (S-DET-02).
 *
 * Epic 5 Sprint 2 (this commit):
 *   - E5.B approval history sidebar — collapsible <aside> consuming
 *     GET /api/optimizer/approvals, refreshed on activate + after every
 *     successful approve / reject submit.
 *   - E5.D per-card forensic trail link — "View forensic trail" button
 *     that opens an inline panel listing the 2 ledger entries
 *     (REQUESTED + RESULT) with their HMAC + sequence_no, via
 *     GET /api/ledger/entries?proposal_id=<uuid>.
 *   - E5.E What-If sandbox preview — "Preview impact" button that hits
 *     POST /api/optimizer/preview/{id} and renders the deterministic
 *     PUE / WUE / ASHRAE-distance projection with a green/amber/red
 *     verdict. ZERO LLM calls on this path (S-DET-01).
 *
 * Test surface: __optimizer_view_test__ exposes the pure render
 * helpers + the action submit functions.
 * ════════════════════════════════════════════════════════════════ */

import { registerRoute } from '../core/router.js';
import { escapeHTML, sanitizeHTML } from '../core/sanitize.js';

const $ = (id) => document.getElementById(id);

let _routeRegistered = false;
let _viewWired = false;
let _refreshInterval = null;

const ROLE_CHOICES = ['SME_L6', 'MANAGER_L7'];   // SME_L6 is the minimum
const POLL_MS = 10000;

// ─── E5.A — Heartbeat strip ──────────────────────────────────────────
function _formatTickTime(tickUnix) {
    if (!tickUnix || typeof tickUnix !== 'number') return '—';
    try {
        const ts = new Date(tickUnix * 1000);
        // Local time, second-precision — operator wants "how stale is this?"
        return ts.toLocaleTimeString();
    } catch (_) {
        return '—';
    }
}

function _formatAgo(tickUnix) {
    if (!tickUnix || typeof tickUnix !== 'number') return 'never';
    const sec = Math.max(0, Math.floor(Date.now() / 1000 - tickUnix));
    if (sec < 60) return `${sec}s ago`;
    if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
    return `${Math.floor(sec / 3600)}h ago`;
}

function _renderHeartbeat(health) {
    const strip = document.querySelector('[data-opt-heartbeat]');
    if (!strip) return;
    if (!health || typeof health !== 'object') {
        strip.innerHTML = sanitizeHTML(
            '<span class="opt-hb opt-hb-unknown">heartbeat: unknown</span>',
        );
        return;
    }
    const running = !!health.is_running;
    const tickUnix = Number(health.last_tick_unix) || 0;
    const tickCount = Number(health.tick_count) || 0;
    const queueSize = Number(health.queue_size) || 0;
    const outcomes = (health.last_tick_outcomes && typeof health.last_tick_outcomes === 'object')
        ? health.last_tick_outcomes : {};
    const sustained = !!outcomes.sustained;
    const drift = (typeof outcomes.drift === 'number') ? outcomes.drift.toFixed(3) : '—';
    const nProp = Number(outcomes.n_proposals) || 0;
    const nPaced = Number(outcomes.n_paced_out) || 0;
    const nVetoed = Number(outcomes.n_vetoed) || 0;

    // Each rendered value goes through escapeHTML — defence in depth,
    // numeric values are already coerced above so injection is not
    // possible, but the discipline matches the rest of the view (S-SEC-01).
    const stateCls = running ? 'opt-hb-running' : 'opt-hb-stopped';
    const stateText = running ? 'RUNNING' : 'STOPPED';
    const sustainedCls = sustained ? 'opt-hb-sustained' : 'opt-hb-quiet';
    const sustainedText = sustained ? 'drift sustained' : 'no drift';
    strip.innerHTML = sanitizeHTML(
        `<span class="opt-hb ${stateCls}">${escapeHTML(stateText)}</span>`
        + `<span class="opt-hb opt-hb-tick">tick #${escapeHTML(String(tickCount))} `
        + `at ${escapeHTML(_formatTickTime(tickUnix))} `
        + `(${escapeHTML(_formatAgo(tickUnix))})</span>`
        + `<span class="opt-hb ${sustainedCls}">${escapeHTML(sustainedText)}</span>`
        + `<span class="opt-hb opt-hb-drift">drift ${escapeHTML(drift)}</span>`
        + `<span class="opt-hb opt-hb-proposed">proposed ${escapeHTML(String(nProp))}</span>`
        + `<span class="opt-hb opt-hb-paced">paced ${escapeHTML(String(nPaced))}</span>`
        + `<span class="opt-hb opt-hb-vetoed">vetoed ${escapeHTML(String(nVetoed))}</span>`
        + `<span class="opt-hb opt-hb-qsize">queue ${escapeHTML(String(queueSize))}</span>`,
    );
}

async function _fetchHealth() {
    const strip = document.querySelector('[data-opt-heartbeat]');
    if (!strip) return;
    try {
        const resp = await fetch('/api/optimizer/health');
        if (resp.status === 503) {
            strip.innerHTML = sanitizeHTML(
                '<span class="opt-hb opt-hb-stopped">Optimizer service not running</span>',
            );
            return;
        }
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        _renderHeartbeat(data);
    } catch (e) {
        strip.innerHTML = sanitizeHTML(
            `<span class="opt-hb opt-hb-error">heartbeat error: `
            + `${escapeHTML(e.message)}</span>`,
        );
    }
}

// ─── Fetching ────────────────────────────────────────────────────────
async function _fetchQueue() {
    const root = $('view-optimizer');
    if (!root) return;
    const list = root.querySelector('[data-opt-list]');
    if (!list) return;
    try {
        const resp = await fetch('/api/optimizer/proposals');
        if (resp.status === 503) {
            list.innerHTML = sanitizeHTML(
                '<div class="opt-empty">Optimizer service not running — set '
                + '<code>DC_EPMS_OPTIMIZER_ENABLED=true</code> and restart the '
                + 'backend to activate the proactive edge-agent (Epic 2).</div>',
            );
            return;
        }
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        _renderQueue(data.proposals || [], data.queue_size || 0);
    } catch (e) {
        list.innerHTML = sanitizeHTML(
            `<div class="opt-empty opt-empty-error">Failed to fetch proposals: `
            + `${escapeHTML(e.message)}</div>`,
        );
    }
}

// ─── Rendering ───────────────────────────────────────────────────────
function _renderQueue(proposals, queueSize) {
    const root = $('view-optimizer');
    if (!root) return;
    const list = root.querySelector('[data-opt-list]');
    const counter = root.querySelector('[data-opt-counter]');
    if (counter) counter.textContent = `Queue: ${proposals.length} pending`;

    if (proposals.length === 0) {
        // Static template — no untrusted interpolation.
        list.innerHTML = sanitizeHTML(
            '<div class="opt-empty">No pending proposals. The Optimizer '
            + 'will enqueue here when PUE drift sustains above the target '
            + 'and the multi-agent consensus passes.</div>',
        );
        return;
    }

    // The narratives ARE LLM-authored — route through sanitizeHTML.
    // Everything else (surface name, values, role selector, buttons) is
    // structured UI — per-value escapeHTML, no sanitizer (it would drop
    // the buttons + the <select>).
    list.innerHTML = proposals.map(_renderProposalCard).join('');
}

function _renderAgentVotesTable(qp) {
    // E5.C — per-agent voting breakdown. Empty array (consult not
    // wired) renders a single placeholder row, never injects markup.
    const votes = Array.isArray(qp.agent_verdicts) ? qp.agent_verdicts : [];
    if (votes.length === 0) {
        return '<div class="opt-votes opt-votes-empty">'
            + '(no per-agent breakdown — consult not wired this tick)'
            + '</div>';
    }
    const rows = votes.map((v) => {
        const name = String(v.agent_name || '');
        const verdictStr = String(v.verdict || '');
        const summary = String(v.summary || '');
        const verdictCls = `opt-vote-${verdictStr.replace(/[^a-z0-9_-]/gi, '-')}`;
        // S-DET-02 — the Safety Officer's hard_stop is the unmistakable
        // veto badge. Match name + verdict together to avoid false
        // positives (a Safety Officer "approve" is NOT a veto).
        const isVeto = name === 'Safety Officer' && verdictStr === 'hard_stop';
        const badgeCls = isVeto
            ? 'opt-vote-badge opt-vote-badge-veto'
            : `opt-vote-badge ${verdictCls}`;
        const vetoMark = isVeto ? ' SAFETY VETO' : '';
        return '<tr class="opt-vote-row' + (isVeto ? ' opt-vote-row-veto' : '') + '">'
            + `<td class="opt-vote-name">${escapeHTML(name)}</td>`
            + `<td class="opt-vote-verdict">`
            + `<span class="${escapeHTML(badgeCls)}">${escapeHTML(verdictStr || '—')}`
            + `${escapeHTML(vetoMark)}</span></td>`
            + `<td class="opt-vote-summary">${escapeHTML(summary)}</td>`
            + '</tr>';
    }).join('');
    return '<table class="opt-votes">'
        + '<thead><tr><th>Agent</th><th>Vote</th><th>Summary</th></tr></thead>'
        + `<tbody>${rows}</tbody></table>`;
}

function _renderProposalCard(qp) {
    const p = qp.proposal || {};
    const verdict = (qp.consensus_verdict || 'no-consensus').toString();
    const verdictClass = `opt-verdict-${verdict.replace(/[^a-z0-9_-]/gi, '-')}`;
    const optNarrative = sanitizeHTML(
        qp.optimizer_narrative || '(no Optimizer narrative this tick)',
    );
    const consNarrative = sanitizeHTML(
        qp.consensus_rationale || '(no consensus rationale)',
    );
    const veto = !!qp.safety_officer_veto;
    const votesTable = _renderAgentVotesTable(qp);
    const roleOpts = ROLE_CHOICES.map(
        (r) => `<option value="${escapeHTML(r)}">${escapeHTML(r)}</option>`,
    ).join('');
    const idEsc = escapeHTML(p.proposal_id || '');
    const delta = typeof p.delta === 'number' ? p.delta.toFixed(2) : '?';
    const cur = typeof p.current_value === 'number' ? p.current_value.toFixed(2) : '?';
    const prop = typeof p.proposed_value === 'number' ? p.proposed_value.toFixed(2) : '?';
    return `<div class="opt-card" data-proposal-id="${idEsc}">
        <div class="opt-card-hdr">
            <span class="opt-surface">${escapeHTML(p.surface || 'unknown')}</span>
            <span class="opt-id">${escapeHTML((p.proposal_id || '').slice(0, 8))}</span>
            ${veto ? '<span class="opt-veto">SAFETY VETO</span>' : ''}
        </div>
        <div class="opt-card-body">
            <div class="opt-row">
                <span class="opt-current">${escapeHTML(cur)}</span>
                <span class="opt-arrow"> → </span>
                <span class="opt-proposed">${escapeHTML(prop)}</span>
                <span class="opt-delta"> (Δ ${escapeHTML(delta)})</span>
            </div>
            <div class="opt-rationale">${escapeHTML(p.rationale || '')}</div>
            <div class="opt-consensus ${escapeHTML(verdictClass)}">
                Consensus: ${escapeHTML(verdict)}
            </div>
            ${votesTable}
            <div class="opt-narrative opt-narrative-optimizer">
                <strong>Optimizer:</strong> ${optNarrative}
            </div>
            <div class="opt-narrative opt-narrative-consensus">
                <strong>Consensus rationale:</strong> ${consNarrative}
            </div>
        </div>
        <div class="opt-card-actions">
            <button class="opt-btn opt-btn-preview" data-action="preview"
                    data-proposal-id="${idEsc}">Preview impact</button>
            <button class="opt-btn opt-btn-trail" data-action="trail"
                    data-proposal-id="${idEsc}">View forensic trail</button>
            <button class="opt-btn opt-btn-approve" data-action="approve"
                    data-proposal-id="${idEsc}">Approve &amp; Actuate</button>
            <button class="opt-btn opt-btn-reject" data-action="reject"
                    data-proposal-id="${idEsc}">Reject</button>
        </div>
        <div class="opt-preview" data-proposal-id="${idEsc}" hidden></div>
        <div class="opt-trail" data-proposal-id="${idEsc}" hidden></div>
        <div class="opt-form opt-form-approve" data-proposal-id="${idEsc}" hidden>
            <label>Operator ID:
                <input type="text" class="opt-operator-input" value="wilmer.angel">
            </label>
            <label>Role (S-SEC-02 — server is authoritative):
                <select class="opt-role-select">${roleOpts}</select>
            </label>
            <label class="opt-ashrae">
                <input type="checkbox" class="opt-ashrae-check">
                Confirm sandbox-projected ASHRAE distance is within tolerance.
            </label>
            <button class="opt-btn opt-submit-approve" data-action="submit-approve"
                    data-proposal-id="${idEsc}">Submit Approve</button>
        </div>
        <div class="opt-form opt-form-reject" data-proposal-id="${idEsc}" hidden>
            <label>Operator ID:
                <input type="text" class="opt-operator-input" value="wilmer.angel">
            </label>
            <label>Role:
                <select class="opt-role-select">${roleOpts}</select>
            </label>
            <label>Reason (required):
                <textarea class="opt-reason-input" rows="3"></textarea>
            </label>
            <button class="opt-btn opt-submit-reject" data-action="submit-reject"
                    data-proposal-id="${idEsc}">Submit Reject</button>
        </div>
        <div class="opt-result" data-proposal-id="${idEsc}"></div>
    </div>`;
}

// ─── Actions ─────────────────────────────────────────────────────────
function _showForm(proposalId, kind) {
    const root = $('view-optimizer');
    if (!root) return;
    // Hide all forms for this card, then reveal the requested kind.
    root.querySelectorAll(
        `.opt-form[data-proposal-id="${CSS.escape(proposalId)}"]`,
    ).forEach((el) => { el.hidden = true; });
    const form = root.querySelector(
        `.opt-form-${kind}[data-proposal-id="${CSS.escape(proposalId)}"]`,
    );
    if (form) form.hidden = false;
}

function _renderResult(proposalId, ok, message) {
    const root = $('view-optimizer');
    if (!root) return;
    const slot = root.querySelector(
        `.opt-result[data-proposal-id="${CSS.escape(proposalId)}"]`,
    );
    if (!slot) return;
    const cls = ok ? 'opt-result-ok' : 'opt-result-err';
    slot.innerHTML = sanitizeHTML(
        `<div class="${cls}">${escapeHTML(message)}</div>`,
    );
}

function _readForm(proposalId, kind) {
    const root = $('view-optimizer');
    const form = root.querySelector(
        `.opt-form-${kind}[data-proposal-id="${CSS.escape(proposalId)}"]`,
    );
    if (!form) return null;
    const out = {
        operator_id: form.querySelector('.opt-operator-input')?.value?.trim() || '',
        actor_role: form.querySelector('.opt-role-select')?.value || '',
    };
    if (kind === 'approve') {
        out.confirm_ashrae = !!form.querySelector('.opt-ashrae-check')?.checked;
    } else if (kind === 'reject') {
        out.reason = form.querySelector('.opt-reason-input')?.value?.trim() || '';
    }
    return out;
}

async function _submitApprove(proposalId) {
    const body = _readForm(proposalId, 'approve');
    if (!body) return;
    if (!body.operator_id) {
        _renderResult(proposalId, false, 'Operator ID is required.');
        return;
    }
    if (!body.confirm_ashrae) {
        _renderResult(
            proposalId, false,
            'You must confirm the ASHRAE distance is within tolerance.',
        );
        return;
    }
    try {
        const resp = await fetch(`/api/optimizer/approve/${encodeURIComponent(proposalId)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            _renderResult(
                proposalId, false,
                `HTTP ${resp.status}: ${data.detail || resp.statusText}`,
            );
            return;
        }
        const verdict = data.decision || 'approved';
        const bms = data.bms_write_success === true
            ? `BMS write OK (${data.bms_tag_id || 'unknown tag'})`
            : `BMS write failed: ${data.bms_write_message || 'unknown'}`;
        _renderResult(proposalId, data.bms_write_success === true,
            `${verdict.toUpperCase()} — ${bms}`);
        // E5.B — refresh the history sidebar so the operator sees the
        // decision they just made land in the audit list.
        _fetchHistory();
        // NOTE: deliberately NOT auto-refreshing the queue here. A
        // re-render would wipe the inline result the operator just
        // saw. The 10 s poll OR a backend hermes:optimizer-proposal
        // (Batch 2.D) catches the dequeue within seconds; the operator
        // can also click Refresh manually.
    } catch (e) {
        _renderResult(proposalId, false, `Network error: ${e.message}`);
    }
}

async function _submitReject(proposalId) {
    const body = _readForm(proposalId, 'reject');
    if (!body) return;
    if (!body.operator_id) {
        _renderResult(proposalId, false, 'Operator ID is required.');
        return;
    }
    if (!body.reason) {
        _renderResult(proposalId, false, 'Reason is required.');
        return;
    }
    try {
        const resp = await fetch(`/api/optimizer/reject/${encodeURIComponent(proposalId)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            _renderResult(
                proposalId, false,
                `HTTP ${resp.status}: ${data.detail || resp.statusText}`,
            );
            return;
        }
        _renderResult(proposalId, true, `REJECTED — ${data.reason || ''}`);
        // E5.B — refresh the history sidebar (same as in _submitApprove).
        _fetchHistory();
        // No queue auto-refresh; same rationale as _submitApprove.
    } catch (e) {
        _renderResult(proposalId, false, `Network error: ${e.message}`);
    }
}

// ─── Wiring ──────────────────────────────────────────────────────────
function _onClick(ev) {
    const t = ev.target.closest('[data-action]');
    if (!t) return;
    const action = t.dataset.action;
    const pid = t.dataset.proposalId;
    if (!pid) return;
    switch (action) {
        case 'approve':
            _showForm(pid, 'approve');
            break;
        case 'reject':
            _showForm(pid, 'reject');
            break;
        case 'submit-approve':
            _submitApprove(pid);
            break;
        case 'submit-reject':
            _submitReject(pid);
            break;
        case 'preview':         // E5.E
            _fetchPreview(pid);
            break;
        case 'trail':           // E5.D
            _fetchForensicTrail(pid);
            break;
    }
}

function _onHermesProposal() {
    // Best-effort refresh on a live event; failures already surface in
    // _fetchQueue's catch block. Returns the promise so tests can
    // await; the production DOM-event listener path doesn't need to.
    return _fetchQueue();
}

function _onHermesTick(ev) {
    // E5.A — Optimizer loop heartbeat. The payload from
    // hermes_events.js carries the exact shape of the health snapshot
    // (plus an `event` field). Re-render the strip directly from the
    // event so the operator sees a fresh wall-clock within ~ms of the
    // tick; an occasional miss is caught by the GET fallback below.
    try {
        const d = ev && ev.detail ? ev.detail : null;
        if (d) {
            _renderHeartbeat({
                is_running: !!d.is_running,
                pue_target: undefined,
                last_tick_unix: Number(d.tick_unix) || 0,
                tick_count: Number(d.tick_count) || 0,
                last_tick_outcomes: d.outcomes || {},
                queue_size: Number(d.queue_size) || 0,
                audit_recent: [],
            });
            return;
        }
    } catch (_) { /* fall through to fetch */ }
    // Defensive fallback — if the event shape changes upstream the
    // strip still refreshes via the authoritative endpoint.
    return _fetchHealth();
}

// ─── E5.B — Approval history sidebar ─────────────────────────────────
function _formatHistoryTime(unix) {
    if (!unix || typeof unix !== 'number') return '—';
    try {
        return new Date(unix * 1000).toLocaleString();
    } catch (_) {
        return '—';
    }
}

function _renderHistory(approvals) {
    const slot = document.querySelector('[data-opt-history-body]');
    if (!slot) return;
    if (!Array.isArray(approvals) || approvals.length === 0) {
        slot.innerHTML = sanitizeHTML(
            '<div class="opt-hist-empty">No recent decisions yet.</div>',
        );
        return;
    }
    // Newest first — server returns chronological (oldest first), so reverse.
    const rows = [...approvals].reverse().map((a) => {
        const decision = String(a.decision || 'unknown').toLowerCase();
        const cls = decision === 'approved'
            ? 'opt-hist-approved'
            : (decision === 'rejected' ? 'opt-hist-rejected' : 'opt-hist-other');
        const op = String(a.operator_id || '—');
        const role = String(a.actor_role || '—');
        const ts = _formatHistoryTime(Number(a.decision_at));
        const pidShort = String(a.proposal_id || '').slice(0, 8);
        const reason = String(a.reason || '');
        const tag = String(a.bms_tag_id || '');
        const writeOk = a.bms_write_success;
        let writeBadge = '';
        if (writeOk === true) {
            writeBadge = '<span class="opt-hist-write opt-hist-write-ok">BMS OK</span>';
        } else if (writeOk === false) {
            writeBadge = '<span class="opt-hist-write opt-hist-write-fail">BMS FAIL</span>';
        }
        return `<li class="opt-hist-row ${escapeHTML(cls)}">
            <div class="opt-hist-line1">
                <span class="opt-hist-decision">${escapeHTML(decision.toUpperCase())}</span>
                <span class="opt-hist-pid">${escapeHTML(pidShort)}</span>
                ${writeBadge}
            </div>
            <div class="opt-hist-line2">
                <span class="opt-hist-op">${escapeHTML(op)}</span>
                <span class="opt-hist-role">(${escapeHTML(role)})</span>
                <span class="opt-hist-ts">${escapeHTML(ts)}</span>
            </div>
            ${tag ? `<div class="opt-hist-tag">tag: ${escapeHTML(tag)}</div>` : ''}
            ${reason ? `<div class="opt-hist-reason">${escapeHTML(reason)}</div>` : ''}
        </li>`;
    }).join('');
    slot.innerHTML = sanitizeHTML(`<ul class="opt-hist-list">${rows}</ul>`);
}

async function _fetchHistory() {
    const slot = document.querySelector('[data-opt-history-body]');
    if (!slot) return;
    try {
        const resp = await fetch('/api/optimizer/approvals');
        if (resp.status === 503) {
            slot.innerHTML = sanitizeHTML(
                '<div class="opt-hist-empty">Optimizer not running.</div>',
            );
            return;
        }
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        _renderHistory(data.approvals || []);
        const counter = document.querySelector('[data-opt-history-counter]');
        if (counter) counter.textContent = String(Number(data.total) || 0);
    } catch (e) {
        slot.innerHTML = sanitizeHTML(
            `<div class="opt-hist-empty opt-hist-error">history error: `
            + `${escapeHTML(e.message)}</div>`,
        );
    }
}

function _toggleHistorySidebar() {
    const aside = document.querySelector('[data-opt-history]');
    if (!aside) return;
    const isOpen = aside.dataset.open === '1';
    aside.dataset.open = isOpen ? '0' : '1';
    aside.hidden = isOpen;
}


// ─── E5.D — Per-card forensic trail link ─────────────────────────────
function _renderForensicTrail(proposalId, payload) {
    const root = $('view-optimizer');
    if (!root) return;
    const slot = root.querySelector(
        `.opt-trail[data-proposal-id="${CSS.escape(proposalId)}"]`,
    );
    if (!slot) return;
    if (!payload || !Array.isArray(payload.entries) || payload.entries.length === 0) {
        slot.innerHTML = sanitizeHTML(
            '<div class="opt-trail-empty">No ledger entries linked '
            + 'to this proposal_id yet. The REQUESTED + RESULT rows are '
            + 'written when the operator clicks Approve and the BMS write '
            + 'seam fires.</div>',
        );
        return;
    }
    const rows = payload.entries.map((e) => {
        const seq = String(e.sequence_no ?? '?');
        const action = String(e.action || '?');
        const ts = String(e.ts || '');
        const actor = String(e.actor || '—');
        const idShort = String(e.entry_id || '').slice(0, 12);
        const hmacShort = String(e.entry_hmac || '').slice(0, 16);
        const keyVer = String(e.key_version ?? '?');
        // Payload is rendered as escaped JSON — operators must see the
        // exact bytes, but no markup is permitted.
        const payloadJson = (() => {
            try { return JSON.stringify(e.payload || {}, null, 2); }
            catch (_) { return '(unserialisable)'; }
        })();
        return `<li class="opt-trail-entry">
            <div class="opt-trail-hdr">
                <span class="opt-trail-seq">#${escapeHTML(seq)}</span>
                <span class="opt-trail-action">${escapeHTML(action)}</span>
                <span class="opt-trail-actor">${escapeHTML(actor)}</span>
                <span class="opt-trail-ts">${escapeHTML(ts)}</span>
            </div>
            <div class="opt-trail-meta">
                entry_id <code>${escapeHTML(idShort)}</code> ·
                hmac <code>${escapeHTML(hmacShort)}</code> ·
                key_v${escapeHTML(keyVer)}
            </div>
            <pre class="opt-trail-payload">${escapeHTML(payloadJson)}</pre>
        </li>`;
    }).join('');
    const matched = Number(payload.matched ?? payload.entries.length);
    const total = Number(payload.total ?? 0);
    const word = matched === 1 ? 'entry' : 'entries';
    const headerLine = `Forensic trail: ${matched} ${word} linked `
        + `(chain total ${total})`;
    slot.innerHTML = sanitizeHTML(
        `<div class="opt-trail-hdr-line">${escapeHTML(headerLine)}</div>`
        + `<ul class="opt-trail-list">${rows}</ul>`,
    );
}

async function _fetchForensicTrail(proposalId) {
    const root = $('view-optimizer');
    if (!root) return;
    const slot = root.querySelector(
        `.opt-trail[data-proposal-id="${CSS.escape(proposalId)}"]`,
    );
    if (!slot) return;
    slot.hidden = false;
    slot.innerHTML = sanitizeHTML('<div class="opt-trail-empty">Loading…</div>');
    try {
        const url = `/api/ledger/entries?proposal_id=${encodeURIComponent(proposalId)}`;
        const resp = await fetch(url);
        if (resp.status === 503) {
            slot.innerHTML = sanitizeHTML(
                '<div class="opt-trail-empty opt-trail-error">'
                + 'Forensic ledger not running on this deployment.</div>',
            );
            return;
        }
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        _renderForensicTrail(proposalId, data);
    } catch (e) {
        slot.innerHTML = sanitizeHTML(
            `<div class="opt-trail-empty opt-trail-error">`
            + `Failed to fetch forensic trail: ${escapeHTML(e.message)}</div>`,
        );
    }
}


// ─── E5.E — What-If sandbox preview ──────────────────────────────────
function _renderPreview(proposalId, projection) {
    const root = $('view-optimizer');
    if (!root) return;
    const slot = root.querySelector(
        `.opt-preview[data-proposal-id="${CSS.escape(proposalId)}"]`,
    );
    if (!slot) return;
    if (!projection || typeof projection !== 'object') {
        slot.innerHTML = sanitizeHTML(
            '<div class="opt-preview-empty">No projection returned.</div>',
        );
        return;
    }
    const verdict = String(projection.verdict || 'amber').toLowerCase();
    const verdictCls = `opt-preview-${verdict}`;
    const fmt = (v, digits) => (typeof v === 'number' ? v.toFixed(digits) : '—');
    const findings = Array.isArray(projection.findings) ? projection.findings : [];
    const findingsHtml = findings.length
        ? `<ul class="opt-preview-findings">${
            findings.map((f) => `<li>${escapeHTML(String(f))}</li>`).join('')
          }</ul>`
        : '';
    slot.hidden = false;
    slot.innerHTML = sanitizeHTML(`
        <div class="opt-preview-card ${escapeHTML(verdictCls)}">
            <div class="opt-preview-verdict">
                Preview verdict: <strong>${escapeHTML(verdict.toUpperCase())}</strong>
            </div>
            <div class="opt-preview-row">
                <span>Projected PUE:</span>
                <span>${escapeHTML(fmt(projection.projected_pue, 3))}
                    (Δ ${escapeHTML(fmt(projection.projected_pue_delta, 3))})</span>
            </div>
            <div class="opt-preview-row">
                <span>Projected WUE Δ:</span>
                <span>${escapeHTML(fmt(projection.projected_wue_delta, 3))} L/kWh</span>
            </div>
            <div class="opt-preview-row">
                <span>Projected hall inlet:</span>
                <span>${escapeHTML(fmt(projection.projected_inlet_c, 2))} °C
                    (Δ ${escapeHTML(fmt(projection.projected_inlet_delta_c, 2))} K)</span>
            </div>
            <div class="opt-preview-row">
                <span>ASHRAE A2 distance:</span>
                <span>${escapeHTML(fmt(projection.ashrae_distance_c, 2))} K</span>
            </div>
            <div class="opt-preview-note">
                Deterministic projection — no LLM (S-DET-01).
            </div>
            ${findingsHtml}
        </div>
    `);
}

async function _fetchPreview(proposalId) {
    const root = $('view-optimizer');
    if (!root) return;
    const slot = root.querySelector(
        `.opt-preview[data-proposal-id="${CSS.escape(proposalId)}"]`,
    );
    if (!slot) return;
    slot.hidden = false;
    slot.innerHTML = sanitizeHTML('<div class="opt-preview-empty">Simulating…</div>');
    try {
        const url = `/api/optimizer/preview/${encodeURIComponent(proposalId)}`;
        const resp = await fetch(url, { method: 'POST' });
        if (resp.status === 404) {
            slot.innerHTML = sanitizeHTML(
                '<div class="opt-preview-empty opt-preview-error">'
                + 'Proposal no longer queued (already decided or expired).</div>',
            );
            return;
        }
        if (resp.status === 503) {
            slot.innerHTML = sanitizeHTML(
                '<div class="opt-preview-empty opt-preview-error">'
                + 'Optimizer service not running.</div>',
            );
            return;
        }
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        _renderPreview(proposalId, data);
    } catch (e) {
        slot.innerHTML = sanitizeHTML(
            `<div class="opt-preview-empty opt-preview-error">`
            + `Preview failed: ${escapeHTML(e.message)}</div>`,
        );
    }
}


function _wireOptimizerView() {
    if (_viewWired) return;
    const root = $('view-optimizer');
    if (!root) return;
    // Build the static skeleton once. Subsequent renders just refill
    // [data-opt-list], [data-opt-heartbeat], [data-opt-history-body].
    root.innerHTML = `
        <div class="opt-hdr">
            <h2>Optimizer · Proactive PUE/WUE Setpoint Proposals</h2>
            <div class="opt-sub">
                Edge-agent proposes; the operator approves under SME_L6 RBAC.
                ADR-006 Proposer Pattern · Epic 2.
            </div>
        </div>
        <div data-opt-heartbeat class="opt-heartbeat"
             aria-label="Optimizer loop heartbeat"></div>
        <div class="opt-bar">
            <button data-opt-refresh class="opt-btn opt-btn-refresh">Refresh</button>
            <span data-opt-counter class="opt-counter">Queue: —</span>
            <button data-opt-history-toggle class="opt-btn opt-btn-history">
                History (<span data-opt-history-counter>0</span>)
            </button>
        </div>
        <div class="opt-main">
            <div data-opt-list class="opt-list"></div>
            <aside data-opt-history class="opt-history" data-open="0" hidden>
                <div class="opt-history-hdr">Approval history</div>
                <div data-opt-history-body class="opt-history-body"></div>
            </aside>
        </div>
    `;
    root.addEventListener('click', _onClick);
    const refreshBtn = root.querySelector('[data-opt-refresh]');
    if (refreshBtn && !refreshBtn._bound) {
        refreshBtn._bound = true;
        refreshBtn.addEventListener('click', () => {
            _fetchQueue();
            _fetchHealth();
            _fetchHistory();
        });
    }
    const historyBtn = root.querySelector('[data-opt-history-toggle]');
    if (historyBtn && !historyBtn._bound) {
        historyBtn._bound = true;
        historyBtn.addEventListener('click', () => {
            _toggleHistorySidebar();
            _fetchHistory();
        });
    }
    document.addEventListener('hermes:optimizer-proposal', _onHermesProposal);
    document.addEventListener('hermes:optimizer-tick', _onHermesTick);
    _viewWired = true;
}

async function _activate() {
    _wireOptimizerView();
    await Promise.all([_fetchQueue(), _fetchHealth(), _fetchHistory()]);
    if (!_refreshInterval) {
        _refreshInterval = setInterval(() => {
            // Self-cancel when the view is off-screen.
            const v = $('view-optimizer');
            if (v && !v.hasAttribute('hidden')) {
                _fetchQueue();
                _fetchHealth();
                _fetchHistory();
            } else {
                clearInterval(_refreshInterval);
                _refreshInterval = null;
            }
        }, POLL_MS);
    }
}

/** Public entry — called once from main.js at bootstrap. */
export function initOptimizerView() {
    if (_routeRegistered) return;
    if (!$('view-optimizer')) {
        console.warn('[optimizer] #view-optimizer not in DOM; view disabled.');
        return;
    }
    registerRoute('optimizer', {
        viewId: 'view-optimizer',
        activate: _activate,
    });
    _routeRegistered = true;
    console.log('[optimizer] route registered (Epic 2 Batch 2.D HMI)');
}

// ─── Test surface ────────────────────────────────────────────────────
export const __optimizer_view_test__ = {
    renderQueue: _renderQueue,
    renderProposalCard: _renderProposalCard,
    renderHeartbeat: _renderHeartbeat,
    renderAgentVotesTable: _renderAgentVotesTable,
    renderHistory: _renderHistory,
    renderForensicTrail: _renderForensicTrail,
    renderPreview: _renderPreview,
    submitApprove: _submitApprove,
    submitReject: _submitReject,
    fetchQueue: _fetchQueue,
    fetchHealth: _fetchHealth,
    fetchHistory: _fetchHistory,
    fetchForensicTrail: _fetchForensicTrail,
    fetchPreview: _fetchPreview,
    toggleHistorySidebar: _toggleHistorySidebar,
    onClick: _onClick,
    onHermesProposal: _onHermesProposal,
    onHermesTick: _onHermesTick,
    initOptimizerView,
    reset: () => {
        _routeRegistered = false;
        _viewWired = false;
        if (_refreshInterval) {
            clearInterval(_refreshInterval);
            _refreshInterval = null;
        }
        document.removeEventListener('hermes:optimizer-proposal', _onHermesProposal);
        document.removeEventListener('hermes:optimizer-tick', _onHermesTick);
    },
};
