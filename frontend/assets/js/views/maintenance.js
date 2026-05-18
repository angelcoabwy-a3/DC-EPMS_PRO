/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/maintenance.js
 *
 * Sprint 6 Fase 5: CMMS Core v1.0 frontend.
 *
 * Renders the Maintenance view backed by /api/cmms/* endpoints:
 *   - Asset Health Grid (left panel) clustered by asset_type
 *   - Work Order backlog (right panel) with filters
 *   - 4 KPI cards on top (totals, overdue, predictive)
 *
 * Live updates: T3.1 event-driven — refreshes on the Hermes
 * `hermes:cmms-alert` DOM event (Work-Order mutations / edge-healing)
 * and on becoming visible. Zero HTTP polling (no setInterval).
 *
 * Read-only for now: approve/reject buttons inline are V2 (Sprint 6.5
 * or later). Operators approve via curl/Swagger or the /docs UI today.
 *
 * Style: instrument-grade (mirrors Activity Strip discipline).
 * No emojis, no animations beyond severity color transitions.
 * ════════════════════════════════════════════════════════════════ */

import { playClick } from '../core/sound.js';
import { registerRoute } from '../core/router.js';
import { trapFocus } from '../core/focus_trap.js';

const API_BASE = '';  // same-origin

let _container = null;
let _hermesAlertHandler = null;   // T3.1: bound hermes:cmms-alert listener
let _isVisible = false;
let _focusAssetId = null;     // v0.10.12: handoff from #power asset panel
let _filters = {
    status: '',
    priority: '',
    trigger_source: '',
    asset_id: '',
    only_open: true,
};

// Sprint Consolidation Mission 3: per-row expand/collapse for
// predictive WOs. Cached so that a refresh tick doesn't collapse a
// detail panel the operator just opened.
const _expandedWOs = new Set();
const _wosById = new Map();

// ─── Fetch helpers ────────────────────────────────────────────────
async function _fetchAssets() {
    const r = await fetch(`${API_BASE}/api/cmms/assets?limit=500`);
    if (!r.ok) throw new Error(`assets ${r.status}`);
    return r.json();
}

async function _fetchWorkOrders() {
    const params = new URLSearchParams();
    if (_filters.status)         params.set('status', _filters.status);
    if (_filters.priority)       params.set('priority', _filters.priority);
    if (_filters.trigger_source) params.set('trigger_source', _filters.trigger_source);
    if (_filters.only_open)      params.set('only_open', 'true');
    if (_filters.asset_id)       params.set('asset_id', _filters.asset_id);
    params.set('limit', '200');
    const r = await fetch(`${API_BASE}/api/cmms/work-orders?${params}`);
    if (!r.ok) throw new Error(`work-orders ${r.status}`);
    return r.json();
}

// v0.10.12: consume sessionStorage handoff from #power asset panel
// (set by views/asset_panel.js when user clicks "Open in Maintenance").
// Sets _focusAssetId so banner + filter can highlight the right rows;
// clears the storage key so a subsequent unrelated nav doesn't re-apply.
function _consumeFocusHandoff() {
    let id = null;
    try { id = sessionStorage.getItem('cmms_focus_asset_id'); } catch {}
    if (id) {
        _focusAssetId = id;
        try { sessionStorage.removeItem('cmms_focus_asset_id'); } catch {}
    }
    let openCreate = false;
    try { openCreate = sessionStorage.getItem('cmms_open_create_modal') === '1'; } catch {}
    if (openCreate) {
        try { sessionStorage.removeItem('cmms_open_create_modal'); } catch {}
        // Create-WO modal isn't built yet — surface a placeholder toast.
        // Phase 5 will wire this to a real modal; for now the focus filter
        // alone gives the operator a useful drill landing.
        console.log('[maintenance] cmms_open_create_modal=1 — Create-WO modal pending in Phase 5');
    }
    return _focusAssetId;
}

// ─── Sprint 6.6: CET signature + approve/reject actions ───────────
// CET id stored in sessionStorage so it persists across page reloads
// within the tab but resets on browser close. ADR-006 compliance:
// the backend enforces the state machine; this is just convenience.
function _getCetId() {
    let id = sessionStorage.getItem('cmms_cet_id');
    if (!id || !id.trim()) {
        id = prompt(
            'Enter your CET ID for this session\n(used to sign work order approvals; reset on browser close):',
            'wilmer',
        );
        if (id && id.trim()) {
            sessionStorage.setItem('cmms_cet_id', id.trim());
            return id.trim();
        }
        return null;
    }
    return id;
}

async function _approveWorkOrder(woId, woContext) {
    const cetId = _getCetId();
    if (!cetId) return false;

    const ok = confirm(
        `Approve work order?\n\n` +
        `  WO:        ${woId}\n` +
        `  Asset:     ${woContext.asset_id}\n` +
        `  Priority:  ${woContext.priority}\n` +
        `  Class:     ${woContext.work_class} / ${woContext.procedure_class || '—'}\n` +
        `  LOTO:      ${woContext.requires_loto ? 'YES' : 'no'}\n` +
        `  CET sign:  ${cetId}\n\n` +
        `This transitions status pending_approval -> approved per ADR-006.`,
    );
    if (!ok) return false;

    const r = await fetch(`${API_BASE}/api/cmms/work-orders/${encodeURIComponent(woId)}/approve`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        // F3-1: backend RBAC gate - actor_role from the live role selector.
        body: JSON.stringify({cet_id: cetId, actor_role: _procgenRole()}),
    });
    if (!r.ok) {
        const errText = await r.text().catch(() => `${r.status}`);
        alert(`Approve failed: ${errText.slice(0, 200)}`);
        return false;
    }
    playClick();
    return true;
}

async function _rejectWorkOrder(woId, woContext) {
    const cetId = _getCetId();
    if (!cetId) return false;

    const reason = prompt(
        `Reject work order ${woId}?\n` +
        `Asset: ${woContext.asset_id} (priority ${woContext.priority})\n\n` +
        `Enter rejection reason (required):`,
    );
    if (!reason || !reason.trim()) return false;

    const ok = confirm(
        `Confirm rejection?\n\n` +
        `  WO:     ${woId}\n` +
        `  Reason: ${reason.trim()}\n` +
        `  CET:    ${cetId}\n\n` +
        `This transitions status pending_approval -> rejected (irreversible).`,
    );
    if (!ok) return false;

    const r = await fetch(`${API_BASE}/api/cmms/work-orders/${encodeURIComponent(woId)}/reject`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        // F3-1: backend RBAC gate - actor_role from the live role selector.
        body: JSON.stringify({cet_id: cetId, rejection_reason: reason.trim(), actor_role: _procgenRole()}),
    });
    if (!r.ok) {
        const errText = await r.text().catch(() => `${r.status}`);
        alert(`Reject failed: ${errText.slice(0, 200)}`);
        return false;
    }
    playClick();
    return true;
}

// ─── Sprint 7.1c: voice closure modal (v0.10.13 hardened) ────────
let _activeClosureWoId = null;
let _escListenerAttached = false;

// Light toast for closure success — reuses .sld-info-toast CSS class
function _maintToast(msg, tone = 'ok') {
    let host = document.getElementById('m-toast');
    if (!host) {
        host = document.createElement('div');
        host.id = 'm-toast';
        host.className = 'sld-info-toast';
        document.body.appendChild(host);
    }
    host.textContent = msg;
    host.dataset.tone = tone;
    host.classList.add('is-visible');
    clearTimeout(_maintToast._t);
    _maintToast._t = setTimeout(() => host.classList.remove('is-visible'), 2800);
}

// Escape handler — attached only while modal is open (no permanent
// global listener; clean lifecycle, no leak)
function _onEscapeKey(e) {
    if (e.key === 'Escape') _closeClosureModal();
}

function _attachEscape() {
    if (_escListenerAttached) return;
    document.addEventListener('keydown', _onEscapeKey);
    _escListenerAttached = true;
}
function _detachEscape() {
    if (!_escListenerAttached) return;
    document.removeEventListener('keydown', _onEscapeKey);
    _escListenerAttached = false;
}

// Reset validation styling — called on close + on input/focus
function _clearValidation() {
    document.querySelectorAll('#m-closure-overlay .is-invalid')
        .forEach((el) => el.classList.remove('is-invalid'));
    document.querySelectorAll('#m-closure-overlay .m-validation-hint.is-visible')
        .forEach((el) => el.classList.remove('is-visible'));
}

// T2.5 A11y-1 — focus-trap release handle for the closure dialog.
let _closureTrapRelease = null;

function _openClosureModal(woId, woContext) {
    _activeClosureWoId = woId;
    const overlay = document.getElementById('m-closure-overlay');
    const ctxEl   = document.getElementById('m-closure-context');
    const cetEl   = document.getElementById('m-closure-cet');
    const notesEl = document.getElementById('m-closure-notes');
    const completeEl  = document.getElementById('m-closure-complete');
    const followupsEl = document.getElementById('m-closure-followups');
    const formBody    = document.getElementById('m-closure-form-body');
    const resultBox   = document.getElementById('m-closure-result');
    if (!overlay || !ctxEl || !cetEl || !notesEl) return;

    // Reset state
    if (resultBox) {
        resultBox.setAttribute('hidden', '');
        resultBox.innerHTML = '';
    }
    if (formBody) formBody.removeAttribute('hidden');
    _clearValidation();

    ctxEl.innerHTML = `<strong>${_escape(woId)}</strong> &middot; asset: <strong>${_escape(woContext.asset_id || '?')}</strong> &middot; priority: ${_escape(woContext.priority || '?')} &middot; LOTO: ${woContext.requires_loto ? 'YES' : 'no'}`;

    // Default CET id from sessionStorage (same convention as approve flow)
    const stored = sessionStorage.getItem('cmms_cet_id') || '';
    cetEl.value = stored;
    notesEl.value = '';
    completeEl.checked = false;
    followupsEl.checked = true;

    overlay.removeAttribute('hidden');
    _attachEscape();
    // T2.5 A11y-1 (WCAG 2.4.3): constrain Tab to the dialog. Escape is
    // already handled by _attachEscape, so no onEscape here (avoids a
    // double close).
    _closureTrapRelease = trapFocus(document.getElementById('m-closure-modal'));
    setTimeout(() => notesEl.focus(), 50);
}

function _closeClosureModal() {
    const overlay = document.getElementById('m-closure-overlay');
    if (overlay) overlay.setAttribute('hidden', '');
    _detachEscape();
    // T2.5 A11y-1 — release the focus trap + return focus to the trigger.
    if (_closureTrapRelease) { _closureTrapRelease(); _closureTrapRelease = null; }
    _clearValidation();
    _activeClosureWoId = null;
}

async function _submitClosure() {
    const cetEl   = document.getElementById('m-closure-cet');
    const notesEl = document.getElementById('m-closure-notes');
    const completeEl  = document.getElementById('m-closure-complete');
    const followupsEl = document.getElementById('m-closure-followups');
    const submitBtn   = document.getElementById('m-closure-submit');
    const resultBox   = document.getElementById('m-closure-result');
    if (!_activeClosureWoId || !cetEl || !notesEl) return;

    const cetId = (cetEl.value || '').trim();
    const notes = (notesEl.value || '').trim();

    // v0.10.13: visible validation — shake + red border, no more alert()
    _clearValidation();
    let invalid = false;
    let firstInvalidEl = null;
    if (!cetId) {
        cetEl.classList.add('is-invalid');
        firstInvalidEl = firstInvalidEl || cetEl;
        invalid = true;
    }
    if (notes.length < 10) {
        notesEl.classList.add('is-invalid');
        const hint = document.getElementById('m-closure-notes-hint');
        if (hint) hint.classList.add('is-visible');
        firstInvalidEl = firstInvalidEl || notesEl;
        invalid = true;
    }
    if (invalid) {
        if (firstInvalidEl) firstInvalidEl.focus();
        // Re-trigger animation each click by reflow-resetting
        void cetEl.offsetWidth;
        void notesEl.offsetWidth;
        return;
    }

    sessionStorage.setItem('cmms_cet_id', cetId);

    submitBtn.disabled = true;
    submitBtn.textContent = 'normalizing…';

    if (resultBox) {
        resultBox.removeAttribute('hidden');
        resultBox.innerHTML = `<div class="m-closure-status m-closure-status-pending">Sending notes to gemma for normalization (typically 2&ndash;6 seconds)&hellip;</div>`;
    }

    try {
        const r = await fetch(
            `${API_BASE}/api/tech-assist/closure/${encodeURIComponent(_activeClosureWoId)}/dictate`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    cet_id: cetId,
                    notes_text: notes,
                    complete_wo: completeEl.checked,
                    auto_create_follow_ups: followupsEl.checked,
                }),
            },
        );
        if (!r.ok) {
            const errText = await r.text().catch(() => `${r.status}`);
            if (resultBox) {
                resultBox.innerHTML = `<div class="m-closure-status m-closure-status-err">HTTP ${r.status}: ${_escape(errText.slice(0, 400))}</div>`;
            }
            // Re-enable submit so operator can retry; do NOT auto-close
            // (error is informational and they may want to read it)
            return;
        }
        const data = await r.json();
        const followupsN = (data.follow_ups_created || []).length;

        // v0.10.13 directive 3: persist normalized result to state.js
        // so subscribers can react (a future toast feed, audit log, etc.)
        try {
            if (window.__epms && window.__epms.getState && window.__epms.setState) {
                const history = window.__epms.getState('closureHistory') || [];
                history.unshift({
                    wo_id: _activeClosureWoId,
                    ts: Date.now(),
                    cet_id: cetId,
                    status_after: data.status_after,
                    normalized: data.normalized,
                    follow_ups_created: data.follow_ups_created || [],
                });
                window.__epms.setState('closureHistory', history.slice(0, 50));
            }
        } catch (e) { /* state bridge optional */ }

        console.log(
            '[maintenance] closure submitted OK ·',
            _activeClosureWoId,
            '· status=' + data.status_after,
            '· follow_ups=' + followupsN,
            '· elapsed_ms=' + data.elapsed_ms,
        );
        _maintToast(
            `Closure submitted · ${data.status_after}` +
            (followupsN ? ` · ${followupsN} follow-up${followupsN > 1 ? 's' : ''} created` : ''),
            'ok',
        );

        // v0.10.13 directive 3: force-close the modal post-success.
        // The result panel was useful for debugging but operationally,
        // the operator wants to keep moving — the toast + refreshed
        // backlog row carry the same information.
        _closeClosureModal();
        await _refresh();
    } catch (err) {
        if (resultBox) {
            resultBox.innerHTML = `<div class="m-closure-status m-closure-status-err">Network error: ${_escape(err.message)}</div>`;
        }
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Submit closure';
    }
}

function _renderClosureResult(data) {
    const box = document.getElementById('m-closure-result');
    if (!box) return;
    box.removeAttribute('hidden');

    // Backend response shape (verified against POST /closure/{id}/dictate):
    //   { work_order_id, status_after, normalized: {...}, raw_notes_chars,
    //     follow_ups_created: [...], follow_ups_skipped: [...], elapsed_ms }
    const norm = data.normalized || {};
    const completed = data.status_after === 'completed';
    const created   = data.follow_ups_created || [];
    const status    = norm._normalization_status || 'success';

    const meta = [
        `<span class="m-closure-meta">normalization: <strong>${_escape(status)}</strong></span>`,
        `<span class="m-closure-meta">status: <strong>${_escape(data.status_after || '?')}</strong></span>`,
        norm.time_spent_min != null ? `<span class="m-closure-meta">time: <strong>${_escape(String(norm.time_spent_min))} min</strong></span>` : '',
        Number.isFinite(data.elapsed_ms) ? `<span class="m-closure-meta">LLM: <strong>${data.elapsed_ms} ms</strong></span>` : '',
    ].filter(Boolean).join('');

    const partsHTML = (norm.parts_used || []).length
        ? `<div class="m-closure-section-title">Parts used</div>
           <div class="m-closure-chips">${(norm.parts_used || []).map(p => `<span class="m-closure-chip">${_escape(p)}</span>`).join('')}</div>`
        : '';

    const safetyHTML = (norm.safety_events || []).length
        ? `<div class="m-closure-section-title">Safety events</div>
           <div class="m-closure-chips">${(norm.safety_events || []).map(p => `<span class="m-closure-chip" style="border-color:rgba(239,68,68,0.5);color:var(--crit);">${_escape(p)}</span>`).join('')}</div>`
        : '';

    // Backend returns follow_ups_created as a list of WO ID strings
    // (not full objects). We pair each id with the matching recommendation
    // from norm.follow_ups_recommended (same order, by index) so the
    // operator sees what each new WO is about.
    const skipped = data.follow_ups_skipped || [];
    const recs    = norm.follow_ups_recommended || [];
    let followupsHTML = '';
    if (created.length) {
        followupsHTML = `<div class="m-closure-section-title">Follow-up WOs created (pending_approval)</div>` +
            created.map((wid, idx) => {
                const rec = recs[idx] || {};
                return `
                <div class="m-closure-followup">
                  <div><strong>${_escape(wid)}</strong> &middot; ${_escape(rec.asset_id || '?')} &middot; class: ${_escape(rec.suggested_work_class || '?')}</div>
                  <div class="m-closure-followup-meta">${_escape(rec.summary || '(see Maintenance backlog for details)')}</div>
                </div>`;
            }).join('');
    } else if (skipped.length) {
        followupsHTML = `<div class="m-closure-section-title">Follow-ups skipped</div>` +
            skipped.map(fu => `
                <div class="m-closure-followup">
                  <div>${_escape(typeof fu === 'string' ? fu : (fu.summary || JSON.stringify(fu)))}</div>
                </div>`).join('');
    } else if (recs.length) {
        followupsHTML = `<div class="m-closure-section-title">Follow-ups recommended (not created &mdash; checkbox unchecked)</div>` +
            recs.map(fu => `
                <div class="m-closure-followup">
                  <div>${_escape(fu.summary || '?')}</div>
                  <div class="m-closure-followup-meta">asset: ${_escape(fu.asset_id || '?')} &middot; severity: ${_escape(fu.severity || '?')} &middot; class: ${_escape(fu.suggested_work_class || '?')}</div>
                </div>`).join('');
    }

    box.innerHTML = `
        <div class="m-closure-status m-closure-status-ok">&#x2714; closure normalized</div>
        <div class="m-closure-meta-row">${meta}</div>
        <div class="m-closure-section-title">Primary action</div>
        <div class="m-closure-primary">${_escape(norm.primary_action || '&mdash;')}</div>
        <div class="m-closure-section-title">Professional report</div>
        <div class="m-closure-report">${_escape(norm.professional_report || '&mdash;')}</div>
        ${partsHTML}
        ${safetyHTML}
        ${followupsHTML}
        <div class="m-modal-actions">
            <button class="btn btn-primary" id="m-closure-done" type="button">Done</button>
        </div>
    `;
    document.getElementById('m-closure-done')?.addEventListener('click', _closeClosureModal);
}

function _wireClosureModal() {
    // Close affordances — all converge on _closeClosureModal()
    document.getElementById('m-closure-cancel')?.addEventListener('click', _closeClosureModal);
    document.getElementById('m-closure-cancel-2')?.addEventListener('click', _closeClosureModal);
    document.getElementById('m-closure-submit')?.addEventListener('click', _submitClosure);
    document.getElementById('m-closure-overlay')?.addEventListener('click', (e) => {
        if (e.target === e.currentTarget) _closeClosureModal();
    });
    // Escape listener is attached/detached around the modal lifecycle
    // in _attachEscape/_detachEscape — NOT permanent.

    // Validation-feedback clearers — kill .is-invalid on focus/input so
    // shake doesn't stick once user starts typing.
    const cetEl   = document.getElementById('m-closure-cet');
    const notesEl = document.getElementById('m-closure-notes');
    const hintEl  = document.getElementById('m-closure-notes-hint');
    [cetEl, notesEl].forEach((el) => {
        if (!el) return;
        const clear = () => {
            el.classList.remove('is-invalid');
            if (el === notesEl && hintEl) hintEl.classList.remove('is-visible');
        };
        el.addEventListener('focus', clear);
        el.addEventListener('input', clear);
    });
}


async function _onActionClick(e) {
    const btn = e.target.closest('[data-cmms-action]');
    if (!btn || btn.disabled) return;
    const action = btn.dataset.cmmsAction;
    const woId = btn.dataset.woId;
    if (!action || !woId) return;

    // Mission 3: drill-down toggle is local-only, no API call.
    if (action === 'toggle-detail') {
        _onToggleDetail(woId);
        return;
    }

    // Build context from the row's data attributes
    const tr = btn.closest('tr');
    const ctx = {
        asset_id: tr?.dataset.assetId || '',
        priority: tr?.dataset.priority || '',
        work_class: tr?.dataset.workClass || '',
        procedure_class: tr?.dataset.procedureClass || '',
        requires_loto: tr?.dataset.requiresLoto === 'true',
    };

    // Sprint 7.1c: voice closure opens a modal, not a confirm dialog.
    if (action === 'close') {
        _openClosureModal(woId, ctx);
        return;
    }

    btn.disabled = true;
    btn.textContent = action === 'approve' ? '...' : '...';
    try {
        const ok = action === 'approve'
            ? await _approveWorkOrder(woId, ctx)
            : await _rejectWorkOrder(woId, ctx);
        if (ok) {
            await _refresh();
        }
    } finally {
        btn.disabled = false;
    }
}

// ─── Formatters ───────────────────────────────────────────────────
function _ageText(isoTimestamp) {
    if (!isoTimestamp) return '—';
    const ms = Date.now() - new Date(isoTimestamp).getTime();
    const min = Math.floor(ms / 60_000);
    if (min < 1) return 'just now';
    if (min < 60) return `${min}m`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr}h`;
    return `${Math.floor(hr / 24)}d`;
}

function _escape(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => (
        {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]
    ));
}

// ─── KPI cards ────────────────────────────────────────────────────
function _renderKPIs(assets, workOrders) {
    const $ = id => document.querySelector(`#view-maintenance [data-field="${id}"]`);

    const totalAssets = assets.length;
    const byCrit = assets.reduce((acc, a) => {
        acc[a.criticality_class] = (acc[a.criticality_class] || 0) + 1;
        return acc;
    }, {});
    const critSummary = ['critical', 'high', 'medium', 'low']
        .map(k => `${k[0].toUpperCase()}: ${byCrit[k] || 0}`).join(' · ');

    const openWos = workOrders.filter(w =>
        ['pending_approval', 'approved', 'scheduled', 'in_progress'].includes(w.status));
    const byPri = openWos.reduce((acc, w) => {
        acc[w.priority] = (acc[w.priority] || 0) + 1;
        return acc;
    }, {});
    const priSummary = ['P1', 'P2', 'P3', 'P4']
        .map(p => `${p}: ${byPri[p] || 0}`).join(' · ');

    const overdue = workOrders.filter(w =>
        w.due_at && new Date(w.due_at) < new Date()
        && !['completed', 'rejected', 'cancelled'].includes(w.status)
    ).length;

    const predictive = workOrders.filter(w => w.trigger_source === 'predictive_kalman').length;

    if ($('total-assets'))         $('total-assets').textContent = totalAssets;
    if ($('total-by-criticality')) $('total-by-criticality').textContent = critSummary;
    if ($('total-open-wos'))       $('total-open-wos').textContent = openWos.length;
    if ($('open-by-priority'))     $('open-by-priority').textContent = priSummary;
    if ($('overdue-wos')) {
        $('overdue-wos').textContent = overdue;
        $('overdue-wos').dataset.severity = overdue > 0 ? 'high' : 'low';
    }
    if ($('predictive-wos')) {
        $('predictive-wos').textContent = predictive;
        $('predictive-wos').dataset.severity = predictive > 0 ? 'high' : 'low';
    }
    const last = document.querySelector('#view-maintenance [data-field="last-refresh"]');
    if (last) last.textContent = `last refresh: ${new Date().toLocaleTimeString('en-CA', { hour12: false })}`;
}

// ─── Asset health grid ────────────────────────────────────────────
function _groupAssetsByCluster(assets) {
    // Cluster by asset_type, with path/pillar shown as sub-line.
    const groups = {};
    for (const a of assets) {
        const key = a.asset_type;
        if (!groups[key]) groups[key] = [];
        groups[key].push(a);
    }
    // Sort: critical types first
    const order = [
        'ups', 'ats', 'chiller', 'transformer', 'switchgear',
        'rectifier', 'utility_intake', 'genset', 'rpp', 'busway',
        'cdu', 'pump', 'cooling_tower_field', 'cooling_tower',
        'fuel_tank', 'it_rack', 'bms_panel', 'sensor', 'workstation', 'other',
    ];
    return order
        .filter(k => groups[k])
        .map(k => ({ asset_type: k, assets: groups[k] }));
}

function _renderAssetGrid(assets) {
    const container = document.getElementById('m-asset-grid');
    if (!container) return;

    if (assets.length === 0) {
        container.innerHTML = '<div class="m-empty">No assets found.</div>';
        return;
    }

    const clusters = _groupAssetsByCluster(assets);
    const cards = clusters.map(({ asset_type, assets: items }) => {
        const total = items.length;
        const healthy = items.filter(a => a.health_state === 'healthy').length;
        const degraded = items.filter(a => a.health_state === 'degraded').length;
        const failed = items.filter(a => a.health_state === 'failed').length;
        const critCount = items.filter(a => a.criticality_class === 'critical').length;

        // Determine card severity
        let cardSev = 'ok';
        if (failed > 0) cardSev = 'crit';
        else if (degraded > 0) cardSev = 'warn';

        // Path/pillar summary for this cluster
        const paths = [...new Set(items.map(a => a.path).filter(Boolean))].join(', ') || '—';
        const pillars = [...new Set(items.map(a => a.redundancy_pillar).filter(Boolean))].join(', ') || '—';

        return `
            <div class="m-asset-card" data-severity="${cardSev}">
                <div class="m-asset-card-hdr">
                    <span class="m-asset-type">${_escape(asset_type)}</span>
                    <span class="m-asset-count">${total}</span>
                </div>
                <div class="m-asset-card-body">
                    <div class="m-asset-meta">
                        <span class="m-meta-k">paths</span><span class="m-meta-v">${_escape(paths)}</span>
                    </div>
                    <div class="m-asset-meta">
                        <span class="m-meta-k">pillar</span><span class="m-meta-v">${_escape(pillars)}</span>
                    </div>
                    <div class="m-asset-meta">
                        <span class="m-meta-k">critical</span>
                        <span class="m-meta-v" data-severity="${critCount > 0 ? 'high' : 'low'}">${critCount}</span>
                    </div>
                </div>
                <div class="m-asset-card-foot">
                    <span class="m-health-pill m-health-healthy" title="healthy">${healthy}</span>
                    <span class="m-health-pill m-health-degraded" title="degraded">${degraded}</span>
                    <span class="m-health-pill m-health-failed" title="failed">${failed}</span>
                </div>
            </div>
        `;
    }).join('');

    container.innerHTML = cards;
}

// ─── Work order backlog table ─────────────────────────────────────
function _renderWOBacklog(workOrders) {
    const tbody = document.getElementById('m-wo-tbody');
    const meta = document.querySelector('#view-maintenance [data-field="wo-count-meta"]');
    if (!tbody) return;

    if (meta) meta.textContent = `${workOrders.length} shown`;

    // Refresh cache for the drill-down click handler.
    _wosById.clear();
    workOrders.forEach(w => _wosById.set(w.work_order_id, w));

    if (workOrders.length === 0) {
        tbody.innerHTML = '<tr><td colspan="10" class="m-empty">No work orders match the current filters.</td></tr>';
        return;
    }

    const rows = workOrders.map(w => {
        const isOverdue = w.due_at && new Date(w.due_at) < new Date()
            && !['completed', 'rejected', 'cancelled'].includes(w.status);
        const wid = _escape(w.work_order_id);
        const asset = _escape(w.asset_id);
        const pri = _escape(w.priority);
        const wclass = _escape(w.work_class);
        const procClass = _escape(w.procedure_class || '');
        const lor = w.lor;
        const status = _escape(w.status);
        const trigger = _escape(w.trigger_source);
        const mop = _escape(w.linked_mop_id || '—');
        const age = _ageText(w.timestamp);
        const requiresLoto = w.requires_loto ? 'true' : 'false';

        // Sprint 6.6: inline approve/reject ONLY when pending_approval.
        // Sprint 7.1c: voice closure button on actionable states.
        let actionsCell;
        if (w.status === 'pending_approval') {
            actionsCell = `
                <td class="m-wo-actions">
                    <button class="m-action-btn m-action-approve" data-cmms-action="approve" data-wo-id="${wid}" title="Approve and sign as CET">✓</button>
                    <button class="m-action-btn m-action-reject"  data-cmms-action="reject"  data-wo-id="${wid}" title="Reject with reason">✗</button>
                </td>
            `;
        } else if (['approved', 'scheduled', 'in_progress'].includes(w.status)) {
            actionsCell = `
                <td class="m-wo-actions">
                    <button class="m-action-btn m-action-close" data-cmms-action="close" data-wo-id="${wid}" title="Dictate closure notes (LLM normalizes + auto-creates follow-ups)">⊝</button>
                </td>
            `;
        } else {
            actionsCell = `<td class="m-wo-actions m-wo-actions-disabled">—</td>`;
        }

        // Mission 3: drill-down chevron only on rows that carry rich
        // forensic data — predictive_kalman or any WO with a
        // telemetry_snapshot. Plain manual WOs stay flat to keep the
        // table scannable.
        const hasDrillDown = !!(w.predictive_metadata || w.telemetry_snapshot_json);
        const isExpanded = _expandedWOs.has(w.work_order_id);
        const chevron = hasDrillDown
            ? `<button class="m-wo-toggle" data-cmms-action="toggle-detail" data-wo-id="${wid}" title="${isExpanded ? 'Collapse' : 'Expand predictive metadata + telemetry snapshot'}" aria-expanded="${isExpanded}">${isExpanded ? '▼' : '▶'}</button>`
            : `<span class="m-wo-toggle-placeholder">·</span>`;

        const mainRow = `
            <tr class="m-wo-row${isExpanded ? ' m-wo-row-expanded' : ''}"
                ${isOverdue ? 'data-overdue="true"' : ''}
                data-wo-id="${wid}"
                data-asset-id="${asset}"
                data-priority="${pri}"
                data-work-class="${wclass}"
                data-procedure-class="${procClass}"
                data-requires-loto="${requiresLoto}">
                <td class="m-wo-id" title="${wid}">${chevron}${wid.slice(-12)}</td>
                <td class="m-wo-asset">${asset}</td>
                <td><span class="m-pri-badge m-pri-${pri.toLowerCase()}">${pri}</span></td>
                <td><span class="m-wclass-badge m-wclass-${wclass.toLowerCase()}">${wclass}</span></td>
                <td class="m-wo-lor">${lor}</td>
                <td><span class="m-status-pill m-status-${status.replace(/_/g, '-')}">${status.replace(/_/g, ' ')}</span></td>
                <td class="m-wo-trigger">${trigger.replace(/_/g, ' ')}</td>
                <td class="m-wo-mop">${mop}</td>
                <td class="m-wo-age">${age}</td>
                ${actionsCell}
            </tr>`;

        const detailRow = hasDrillDown
            ? `<tr class="m-wo-detail-row" data-wo-id="${wid}" ${isExpanded ? '' : 'hidden'}>
                <td colspan="10" class="m-wo-detail-cell">${_renderWODetail(w)}</td>
               </tr>`
            : '';

        return mainRow + detailRow;
    }).join('');

    tbody.innerHTML = rows;
}

// ─── Mission 3: drill-down detail panel ───────────────────────────
function _renderWODetail(w) {
    const sections = [];

    // Issue summary in full (the table cell truncates).
    if (w.issue_summary) {
        sections.push(`
            <div class="m-wo-detail-section">
                <div class="m-wo-detail-title">Issue summary</div>
                <div class="m-wo-detail-text">${_escape(w.issue_summary)}</div>
            </div>`);
    }

    // Predictive metadata: the math behind the alert.
    if (w.predictive_metadata) {
        const pm = w.predictive_metadata;
        const kvRows = Object.entries(pm).map(([k, v]) => {
            let cls = 'm-detail-kv-value';
            // Highlight the load-bearing fields the demo narrative needs.
            if (['max_z', 'mean_z'].includes(k)) cls += ' m-detail-kv-z';
            if (['metric', 'channel_id', 'standard_reference', 'trigger_basis'].includes(k)) cls += ' m-detail-kv-mono';
            return `
                <div class="m-detail-kv">
                    <span class="m-detail-kv-key">${_escape(k)}</span>
                    <span class="${cls}">${_fmtDetailValue(v)}</span>
                </div>`;
        }).join('');
        sections.push(`
            <div class="m-wo-detail-section">
                <div class="m-wo-detail-title">Predictive metadata <span class="m-wo-detail-sub">(Kalman trigger basis)</span></div>
                <div class="m-detail-kv-grid">${kvRows}</div>
            </div>`);
    }

    // Telemetry snapshot: the moment-of-anomaly state.
    if (w.telemetry_snapshot_json) {
        const ts = w.telemetry_snapshot_json;
        const items = Object.entries(ts).map(([k, v]) => `
            <div class="m-detail-kv">
                <span class="m-detail-kv-key m-detail-kv-mono">${_escape(k)}</span>
                <span class="m-detail-kv-value m-detail-kv-mono">${_fmtDetailValue(v)}</span>
            </div>`).join('');
        sections.push(`
            <div class="m-wo-detail-section">
                <div class="m-wo-detail-title">Telemetry snapshot <span class="m-wo-detail-sub">(captured at trigger time)</span></div>
                <div class="m-detail-kv-grid">${items}</div>
            </div>`);
    }

    // Provenance (small footer): who/when/state.
    const fmtDate = (iso) => {
        if (!iso) return '—';
        const d = new Date(iso);
        return isNaN(d) ? iso : d.toISOString().slice(0, 19).replace('T', ' ') + 'Z';
    };
    sections.push(`
        <div class="m-wo-detail-section m-wo-detail-provenance">
            <span><span class="m-detail-kv-key">requested_by</span> ${_escape(w.requested_by || '—')}</span>
            <span><span class="m-detail-kv-key">approved_by_cet</span> ${_escape(w.approved_by_cet || '—')}</span>
            <span><span class="m-detail-kv-key">approved_at</span> <span class="m-detail-kv-mono">${fmtDate(w.approved_at)}</span></span>
            <span><span class="m-detail-kv-key">created_at</span> <span class="m-detail-kv-mono">${fmtDate(w.timestamp)}</span></span>
        </div>`);

    return sections.join('');
}

function _fmtDetailValue(v) {
    if (v === null || v === undefined) return '—';
    if (typeof v === 'number') {
        return Number.isInteger(v) ? String(v) : v.toFixed(3).replace(/\.?0+$/, '') || '0';
    }
    if (typeof v === 'boolean') return v ? 'true' : 'false';
    if (typeof v === 'object') return _escape(JSON.stringify(v));
    return _escape(String(v));
}

function _onToggleDetail(woId) {
    const detailRow = document.querySelector(`#view-maintenance .m-wo-detail-row[data-wo-id="${CSS.escape(woId)}"]`);
    const mainRow   = document.querySelector(`#view-maintenance .m-wo-row[data-wo-id="${CSS.escape(woId)}"]`);
    const toggleBtn = mainRow?.querySelector('.m-wo-toggle');
    if (!detailRow || !mainRow || !toggleBtn) return;

    if (_expandedWOs.has(woId)) {
        _expandedWOs.delete(woId);
        detailRow.setAttribute('hidden', '');
        mainRow.classList.remove('m-wo-row-expanded');
        toggleBtn.textContent = '▶';
        toggleBtn.setAttribute('aria-expanded', 'false');
        toggleBtn.title = 'Expand predictive metadata + telemetry snapshot';
    } else {
        _expandedWOs.add(woId);
        detailRow.removeAttribute('hidden');
        mainRow.classList.add('m-wo-row-expanded');
        toggleBtn.textContent = '▼';
        toggleBtn.setAttribute('aria-expanded', 'true');
        toggleBtn.title = 'Collapse';
    }
}

// ─── Refresh cycle ────────────────────────────────────────────────
async function _refresh() {
    if (!_isVisible) return;
    // v0.10.12: pick up handoff from the asset panel BEFORE the fetch so
    // the asset_id filter applies on this refresh.
    const focus = _consumeFocusHandoff();
    if (focus) _filters.asset_id = focus;

    try {
        const [assetsResp, wosResp] = await Promise.all([
            _fetchAssets(),
            _fetchWorkOrders(),
        ]);
        const assets = assetsResp.assets || [];
        const wos = wosResp.work_orders || [];
        _renderKPIs(assets, wos);
        _renderAssetGrid(assets);
        _renderProcgenTree(assets);
        _renderWOBacklog(wos);
        _renderFocusBanner(assets);
    } catch (err) {
        console.warn('[maintenance] refresh failed:', err);
        const tbody = document.getElementById('m-wo-tbody');
        if (tbody) {
            tbody.innerHTML = `<tr><td colspan="10" class="m-empty m-error">Refresh failed: ${_escape(err.message)}</td></tr>`;
        }
    }
}

// v0.10.12: focus banner shows which asset is being filtered + a Clear
// button. Inserted as the first child of #view-maintenance content.
function _renderFocusBanner(assets) {
    const view = document.getElementById('view-maintenance');
    if (!view) return;
    let banner = document.getElementById('m-focus-banner');
    if (!_focusAssetId) {
        if (banner) banner.remove();
        return;
    }
    const asset = (assets || []).find(a => a.asset_id === _focusAssetId);
    const label = asset ? (asset.display_name || asset.asset_id) : _focusAssetId;
    const html = `
        <div class="m-focus-banner-inner">
            <span class="m-focus-eyebrow">FOCUS</span>
            <span class="m-focus-label">${_escape(label)}</span>
            <span class="m-focus-sub">filtering work orders for ${_escape(_focusAssetId)}</span>
            <button class="m-focus-clear" id="m-focus-clear" type="button">Clear filter</button>
        </div>
    `;
    if (banner) {
        banner.innerHTML = html;
    } else {
        banner = document.createElement('div');
        banner.id = 'm-focus-banner';
        banner.className = 'm-focus-banner';
        banner.innerHTML = html;
        view.insertBefore(banner, view.firstChild);
    }
    const clearBtn = document.getElementById('m-focus-clear');
    if (clearBtn) clearBtn.addEventListener('click', () => {
        _focusAssetId = null;
        _filters.asset_id = '';
        _refresh();
    });
}

// ─── Visibility tracking ──────────────────────────────────────────
function _checkVisibility() {
    const view = document.getElementById('view-maintenance');
    if (!view) return false;
    return !view.hasAttribute('hidden');
}

function _onVisibilityChange() {
    const wasVisible = _isVisible;
    _isVisible = _checkVisibility();
    if (_isVisible && !wasVisible) {
        // Just became visible — refresh immediately + start polling
        _refresh();
    }
    if (!_isVisible && wasVisible) {
        // Just got hidden — refresh triggers skip while hidden
    }
}

// ─── Hermes event-driven refresh (T3.1) ──────────────────────────
// Replaces the 15 s HTTP poll: the backend broadcasts a cmms_alerts
// frame on every Work-Order mutation / edge-healing recommendation,
// and core/hermes_events.js re-emits it as the `hermes:cmms-alert`
// DOM event. The grid refreshes the instant something changes.
function _onHermesAlert() {
    if (_isVisible) _refresh();
}

// ─── Filter handlers ──────────────────────────────────────────────
function _wireFilters() {
    const sf = document.getElementById('m-filter-status');
    const pf = document.getElementById('m-filter-priority');
    const tf = document.getElementById('m-filter-trigger');
    const of = document.getElementById('m-filter-only-open');
    const rb = document.getElementById('m-refresh-btn');

    if (sf) sf.addEventListener('change', () => { _filters.status = sf.value; _refresh(); });
    if (pf) pf.addEventListener('change', () => { _filters.priority = pf.value; _refresh(); });
    if (tf) tf.addEventListener('change', () => { _filters.trigger_source = tf.value; _refresh(); });
    if (of) of.addEventListener('change', () => { _filters.only_open = of.checked; _refresh(); });
    if (rb) rb.addEventListener('click', _refresh);
}

// Sprint 6.6: delegated click listener for inline approve/reject buttons.
// Single listener on the tbody catches clicks even on dynamically rendered
// rows (no need to re-bind on every refresh).
function _wireActionButtons() {
    const tbody = document.getElementById('m-wo-tbody');
    if (!tbody) return;
    tbody.addEventListener('click', _onActionClick);
}

// LOTO-pattern self-routing: legacy IIFE router in app.js has no
// `maintenance` branch in MODULES, so navigateTo falls through to the
// overview fallback. We override that decision after a setTimeout(0)
// so this view actually becomes visible when its nav-item is clicked.
function _wireRouting() {
    // T2.2: declarative registry. The router un-hides #view-maintenance;
    // the MutationObserver below picks up the un-hide and runs _refresh.
    registerRoute('maintenance', { viewId: 'view-maintenance' });
}

// ══════════════════════════════════════════════════════════════════
//  G6: Procedure Generator panel - taxonomy drill-down + API wiring
// ══════════════════════════════════════════════════════════════════
let _procgenAssets = [];
let _procgenChildren = new Map();   // parent_id -> [asset, ...]
const _procgenExpanded = new Set(); // expanded tree-node ids
let _procgenSelected = null;        // selected asset_id
let _procgenDraft = null;           // the active DRAFT procedure dict
let _procgenTrapRelease = null;

const _PROCGEN_ANOMALIES = ['gen_desync', 'cdu_flow_starvation',
                            'thermal_runaway', 'ups_drain'];
// asset_levels that count as a micro-component (a valid EMP target).
const _MICRO_LEVELS = new Set(['sub_assembly', 'component', 'sensor']);

function _assetMeta(asset, key) {
    const m = asset && asset.metadata_json;
    return (m && typeof m === 'object') ? m[key] : undefined;
}

function _renderProcgenTree(assets) {
    _procgenAssets = assets || [];
    _procgenChildren = new Map();
    for (const a of _procgenAssets) {
        const parent = _assetMeta(a, 'parent');
        if (!parent) continue;
        if (!_procgenChildren.has(parent)) _procgenChildren.set(parent, []);
        _procgenChildren.get(parent).push(a);
    }
    const container = document.getElementById('m-procgen-tree');
    if (!container) return;

    // Roots = parentless assets; containment roots (systems + decomposed
    // equipment that have children) float to the top so the macro->micro
    // hierarchy is immediately visible.
    const roots = _procgenAssets.filter(a => !_assetMeta(a, 'parent'));
    roots.sort((a, b) => {
        const ah = _procgenChildren.has(a.asset_id) ? 0 : 1;
        const bh = _procgenChildren.has(b.asset_id) ? 0 : 1;
        if (ah !== bh) return ah - bh;
        return a.asset_id.localeCompare(b.asset_id);
    });
    container.innerHTML = roots.length
        ? roots.map(r => _procgenTreeNode(r, 0)).join('')
        : '<div class="m-empty">No assets.</div>';
}

function _procgenTreeNode(asset, depth) {
    if (depth > 8) return '';   // defensive: cap a malformed parent cycle
    const id = asset.asset_id;
    const kids = _procgenChildren.get(id) || [];
    const hasKids = kids.length > 0;
    const expanded = _procgenExpanded.has(id);
    const level = _assetMeta(asset, 'asset_level') || asset.asset_type;
    const caret = hasKids ? (expanded ? '▾' : '▸') : '·';
    const sel = id === _procgenSelected ? ' is-selected' : '';
    let html = `
        <div class="m-tree-node${sel}" style="padding-left:${8 + depth * 16}px">
            <span class="m-tree-caret" data-caret="${_escape(id)}">${caret}</span>
            <span class="m-tree-label" data-select="${_escape(id)}">${
                _escape(asset.display_name || id)}</span>
            <span class="m-tree-level">${_escape(level)}</span>
        </div>`;
    if (hasKids && expanded) {
        html += kids.slice()
            .sort((a, b) => a.asset_id.localeCompare(b.asset_id))
            .map(k => _procgenTreeNode(k, depth + 1)).join('');
    }
    return html;
}

function _onProcgenTreeClick(e) {
    const caret = e.target.closest('[data-caret]');
    if (caret) {
        const id = caret.getAttribute('data-caret');
        if (_procgenExpanded.has(id)) _procgenExpanded.delete(id);
        else _procgenExpanded.add(id);
        _renderProcgenTree(_procgenAssets);
        return;
    }
    const label = e.target.closest('[data-select]');
    if (label) _selectProcgenAsset(label.getAttribute('data-select'));
}

function _selectProcgenAsset(assetId) {
    _procgenSelected = assetId;
    _renderProcgenTree(_procgenAssets);   // re-render to paint the selection
    _renderProcgenActions(_procgenAssets.find(a => a.asset_id === assetId));
}

function _renderProcgenActions(asset) {
    const panel = document.getElementById('m-procgen-actions');
    if (!panel) return;
    if (!asset) {
        panel.innerHTML = '<div class="m-empty">Select an asset from the taxonomy tree.</div>';
        return;
    }
    const level = _assetMeta(asset, 'asset_level');
    const isMicro = _MICRO_LEVELS.has(level) || !!_assetMeta(asset, 'parent');
    const aid = _escape(asset.asset_id);
    const anomalyOpts = _PROCGEN_ANOMALIES
        .map(a => `<option value="${a}">${a}</option>`).join('');
    panel.innerHTML = `
        <div class="m-procgen-sel">
            <span class="m-procgen-sel-name">${_escape(asset.display_name || asset.asset_id)}</span>
            <span class="m-procgen-sel-meta">${_escape(level || asset.asset_type)}</span>
        </div>
        <div class="m-procgen-btns">
            <button class="btn btn-secondary" data-draft="SOP" data-asset="${aid}">Draft SOP</button>
            <button class="btn btn-secondary" data-draft="MOP" data-asset="${aid}">Draft MOP</button>
            <button class="btn btn-secondary" data-draft="EMP" data-asset="${aid}"${
                isMicro ? '' : ' disabled title="EMP targets micro-components"'}>Draft EMP</button>
        </div>
        <div class="m-procgen-eop">
            <select id="m-procgen-anomaly" class="m-filter-input">${anomalyOpts}</select>
            <button class="btn btn-secondary" data-draft="EOP" data-asset="${aid}">Draft EOP</button>
        </div>`;
}

function _onProcgenActionClick(e) {
    const btn = e.target.closest('[data-draft]');
    if (!btn || btn.disabled) return;
    const procClass = btn.getAttribute('data-draft');
    const assetId = btn.getAttribute('data-asset');
    let anomaly = null;
    if (procClass === 'EOP') {
        const sel = document.getElementById('m-procgen-anomaly');
        anomaly = sel ? sel.value : null;
    }
    _draftProcedure(assetId, procClass, anomaly);
}

function _procgenRole() {
    const sel = document.getElementById('m-procgen-role');
    return sel ? sel.value : 'TECH_L4';
}

async function _draftProcedure(assetId, procClass, anomalyProfile) {
    const body = { asset_id: assetId, procedure_class: procClass,
                   actor_role: _procgenRole() };
    if (anomalyProfile) body.anomaly_profile = anomalyProfile;
    try {
        const r = await fetch(`${API_BASE}/api/procedures/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) {
            _maintToast(`Generate failed (${r.status}): ${data.detail || 'error'}`, 'warn');
            return;
        }
        _openProcgenModal(data);
    } catch (err) {
        _maintToast(`Network error: ${err.message}`, 'warn');
    }
}

function _renderProcedureSteps(proc) {
    const steps = Array.isArray(proc.steps) ? proc.steps : [];
    const rows = steps.map((s, i) => `
        <div class="m-proc-step">
            <span class="m-proc-step-n">${i + 1}</span>
            <div class="m-proc-step-body">
                <div class="m-proc-step-title">${_escape(s.title || s.id || '-')}</div>
                <div class="m-proc-step-meta">${_escape(s.type || '')}${
                    s.vendor_stage ? ` &middot; ${_escape(s.vendor_stage)}` : ''}</div>
            </div>
        </div>`).join('');
    const warn = proc.it_load_warning
        ? `<div class="m-proc-warn">${_escape(proc.it_load_warning)}</div>` : '';
    return `
        <div class="m-proc-head">
            <span class="m-proc-class">${_escape(proc.procedure_class || '?')}</span>
            <span class="m-proc-status">${_escape(proc.status || '?')} &middot; ${
                _escape(proc.version || '')}</span>
        </div>
        <div class="m-proc-id">${_escape(proc.procedure_id || '')}</div>
        ${warn}
        <div class="m-proc-steps">${rows || '<div class="m-empty">No steps.</div>'}</div>`;
}

function _openProcgenModal(proc) {
    _procgenDraft = proc;
    const overlay = document.getElementById('m-procgen-overlay');
    const bodyEl = document.getElementById('m-procgen-body');
    const alertEl = document.getElementById('m-procgen-alert');
    const titleEl = document.getElementById('m-procgen-title');
    const activateBtn = document.getElementById('m-procgen-activate');
    if (!overlay || !bodyEl) return;
    if (alertEl) { alertEl.hidden = true; alertEl.textContent = ''; }
    if (titleEl) titleEl.textContent = `Procedure Draft - ${proc.procedure_id || ''}`;
    if (activateBtn) activateBtn.disabled = false;
    bodyEl.innerHTML = _renderProcedureSteps(proc);
    overlay.removeAttribute('hidden');
    _procgenTrapRelease = trapFocus(document.getElementById('m-procgen-modal'),
                                    { onEscape: _closeProcgenModal });
}

function _closeProcgenModal() {
    const overlay = document.getElementById('m-procgen-overlay');
    if (overlay) overlay.setAttribute('hidden', '');
    if (_procgenTrapRelease) { _procgenTrapRelease(); _procgenTrapRelease = null; }
    _procgenDraft = null;
}

function _procgenAlert(cls, msg) {
    const el = document.getElementById('m-procgen-alert');
    if (!el) return;
    el.className = `m-procgen-alert ${cls}`;
    el.textContent = msg;
    el.hidden = false;
}

async function _activateProcedure() {
    if (!_procgenDraft) return;
    const pid = _procgenDraft.procedure_id || '';
    const activateBtn = document.getElementById('m-procgen-activate');
    try {
        const r = await fetch(
            `${API_BASE}/api/procedures/${encodeURIComponent(pid)}/activate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ actor_role: _procgenRole(),
                                   procedure: _procgenDraft }),
        });
        const data = await r.json().catch(() => ({}));
        if (r.status === 403) {
            // RBAC failure -> high-visibility red banner.
            _procgenAlert('m-procgen-alert-deny',
                          'Access Denied: L5/L6 Senior Clearance Required.');
            return;
        }
        if (!r.ok) {
            _procgenAlert('m-procgen-alert-deny',
                          `Activation failed (${r.status}): ${data.detail || 'error'}`);
            return;
        }
        _procgenDraft = data;
        const bodyEl = document.getElementById('m-procgen-body');
        if (bodyEl) bodyEl.innerHTML = _renderProcedureSteps(data);
        _procgenAlert('m-procgen-alert-ok',
                      `Activated - status ${data.status}, version ${data.version}.`);
        if (activateBtn) activateBtn.disabled = true;
    } catch (err) {
        _procgenAlert('m-procgen-alert-deny', `Network error: ${err.message}`);
    }
}

function _wireProcgen() {
    document.getElementById('m-procgen-tree')
        ?.addEventListener('click', _onProcgenTreeClick);
    document.getElementById('m-procgen-actions')
        ?.addEventListener('click', _onProcgenActionClick);
    document.getElementById('m-procgen-cancel')
        ?.addEventListener('click', _closeProcgenModal);
    document.getElementById('m-procgen-close-2')
        ?.addEventListener('click', _closeProcgenModal);
    document.getElementById('m-procgen-activate')
        ?.addEventListener('click', _activateProcedure);
    document.getElementById('m-procgen-overlay')?.addEventListener('click', (e) => {
        if (e.target === e.currentTarget) _closeProcgenModal();
    });
}


// ─── Public API ───────────────────────────────────────────────────
export function initMaintenanceView() {
    _container = document.getElementById('view-maintenance');
    if (!_container) {
        console.warn('[maintenance] #view-maintenance not in DOM; view disabled.');
        return;
    }
    _wireFilters();
    _wireActionButtons();
    _wireClosureModal();
    _wireProcgen();
    _wireRouting();

    // Observe show/hide via mutation observer on the hidden attribute.
    const observer = new MutationObserver(_onVisibilityChange);
    observer.observe(_container, { attributes: true, attributeFilter: ['hidden'] });

    // Initial render if already visible; event-driven from here on.
    _isVisible = _checkVisibility();
    if (_isVisible) _refresh();

    // T3.1 cutover: subscribe to the Hermes cmms_alerts stream instead
    // of polling. core/hermes_events.js dispatches `hermes:cmms-alert`
    // on `document` for every WO mutation / edge-healing recommendation.
    _hermesAlertHandler = _onHermesAlert;
    document.addEventListener('hermes:cmms-alert', _hermesAlertHandler);
}

export function stopMaintenanceView() {
    if (_hermesAlertHandler) {
        document.removeEventListener('hermes:cmms-alert', _hermesAlertHandler);
        _hermesAlertHandler = null;
    }
}

// ─── Test surface ─────────────────────────────────────────────────
export const __maintenance_test__ = {
    onHermesAlert: _onHermesAlert,
    setVisible(v) { _isVisible = v; },
    isWired: () => _hermesAlertHandler !== null,
};
