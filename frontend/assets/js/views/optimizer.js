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
 * Out of 2.D scope (deferred): per-agent narrative breakdown (would
 * need QueuedProposal to carry the 4 agent rationales individually),
 * a What-If sandbox preview, persistent approval history in the
 * sidebar (the 2.C GET /approvals endpoint is exposed but not yet
 * surfaced here).
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
            <div class="opt-narrative opt-narrative-optimizer">
                <strong>Optimizer:</strong> ${optNarrative}
            </div>
            <div class="opt-narrative opt-narrative-consensus">
                <strong>Consensus rationale:</strong> ${consNarrative}
            </div>
        </div>
        <div class="opt-card-actions">
            <button class="opt-btn opt-btn-approve" data-action="approve"
                    data-proposal-id="${idEsc}">Approve &amp; Actuate</button>
            <button class="opt-btn opt-btn-reject" data-action="reject"
                    data-proposal-id="${idEsc}">Reject</button>
        </div>
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
        // No auto-refresh; same rationale as _submitApprove.
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
    }
}

function _onHermesProposal() {
    // Best-effort refresh on a live event; failures already surface in
    // _fetchQueue's catch block. Returns the promise so tests can
    // await; the production DOM-event listener path doesn't need to.
    return _fetchQueue();
}

function _wireOptimizerView() {
    if (_viewWired) return;
    const root = $('view-optimizer');
    if (!root) return;
    // Build the static skeleton once. Subsequent renders just refill
    // [data-opt-list].
    root.innerHTML = `
        <div class="opt-hdr">
            <h2>Optimizer · Proactive PUE/WUE Setpoint Proposals</h2>
            <div class="opt-sub">
                Edge-agent proposes; the operator approves under SME_L6 RBAC.
                ADR-006 Proposer Pattern · Epic 2.
            </div>
        </div>
        <div class="opt-bar">
            <button data-opt-refresh class="opt-btn opt-btn-refresh">Refresh</button>
            <span data-opt-counter class="opt-counter">Queue: —</span>
        </div>
        <div data-opt-list class="opt-list"></div>
    `;
    root.addEventListener('click', _onClick);
    const refreshBtn = root.querySelector('[data-opt-refresh]');
    if (refreshBtn && !refreshBtn._bound) {
        refreshBtn._bound = true;
        refreshBtn.addEventListener('click', () => _fetchQueue());
    }
    document.addEventListener('hermes:optimizer-proposal', _onHermesProposal);
    _viewWired = true;
}

async function _activate() {
    _wireOptimizerView();
    await _fetchQueue();
    if (!_refreshInterval) {
        _refreshInterval = setInterval(() => {
            // Self-cancel when the view is off-screen.
            const v = $('view-optimizer');
            if (v && !v.hasAttribute('hidden')) {
                _fetchQueue();
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
    submitApprove: _submitApprove,
    submitReject: _submitReject,
    fetchQueue: _fetchQueue,
    onClick: _onClick,
    onHermesProposal: _onHermesProposal,
    initOptimizerView,
    reset: () => {
        _routeRegistered = false;
        _viewWired = false;
        if (_refreshInterval) {
            clearInterval(_refreshInterval);
            _refreshInterval = null;
        }
        document.removeEventListener('hermes:optimizer-proposal', _onHermesProposal);
    },
};
