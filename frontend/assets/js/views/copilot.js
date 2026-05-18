/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/copilot.js
 * ROADMAP V11 T2.1 — Facility Co-Pilot AI view extracted from app.js.
 *
 * The agent chat / draft-approval interface, lifted out of the
 * monolithic IIFE into a decoupled ES module:
 *
 *   - registerRoute('copilot', …) hands navigation to core/router.js.
 *   - LLM-authored chat surfaces (replies, tool traces, the inspect
 *     modal) are routed through core/sanitize.js sanitizeHTML — the
 *     F3-5 XSS allowlist filter. NOTE: the structured draft-card UI is
 *     NOT routed through sanitizeHTML — that filter (correctly) drops
 *     interactive <button> tags, which the Approve/Reject/Inspect
 *     cards need. Those cards instead escape every interpolated value
 *     with escapeHTML at build time — the correct XSS defence for
 *     structured, non-LLM UI.
 *   - subscribes to the Hermes `hermes:agent-consensus` DOM event and
 *     surfaces a resolved multi-agent consensus into the chat.
 *
 * Test surface: __copilot_test__ exposes the pure render helpers.
 * ════════════════════════════════════════════════════════════════ */

import { registerRoute } from '../core/router.js';
import { escapeHTML, sanitizeHTML } from '../core/sanitize.js';

let _initialized = false;
let _history = [];
let _draftsTimer = null;
let _inflight = false;

// ─── Lifecycle / routing ───────────────────────────────────────────
async function _renderCopilotView() {
    await _refreshCopilotStatus();

    // Wire interactions (idempotent — a `_bound` flag guards each element).
    _wireCopilotChat();
    _wireCopilotChips();
    _wireCopilotDraftsRefresh();
    _wireCopilotAuditLink();

    await _refreshCopilotDrafts();
    if (!_draftsTimer) {
        _draftsTimer = setInterval(() => {
            const v = document.getElementById('view-copilot');
            if (v && !v.hasAttribute('hidden')) {
                _refreshCopilotDrafts();
            } else {
                clearInterval(_draftsTimer);
                _draftsTimer = null;
            }
        }, 10000);
    }
}

async function _refreshCopilotStatus() {
    const dot = document.getElementById('copilot-dot');
    const text = document.getElementById('copilot-status-text');
    const tools = document.getElementById('copilot-tools');
    if (!dot || !text || !tools) return;
    try {
        const r = await fetch('/api/agent/health');
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        if (d.status === 'ok') {
            dot.className = 'copilot-dot copilot-dot-ok';
            text.textContent = `Connected · ${d.model_id}`;
            tools.textContent = `${(d.tools || []).length} tools registered`;
            tools.title = (d.tools || []).join(', ');
        } else {
            dot.className = 'copilot-dot copilot-dot-warn';
            text.textContent = d.error || 'Degraded';
            tools.textContent = '—';
        }
    } catch (e) {
        dot.className = 'copilot-dot copilot-dot-err';
        text.textContent = `Unreachable (${e.message})`;
        tools.textContent = '—';
    }
}

function _wireCopilotChat() {
    const input = document.getElementById('copilot-input');
    const send = document.getElementById('copilot-send');
    if (!input || !send) return;
    if (!send._bound) {
        send._bound = true;
        send.addEventListener('click', () => _sendCopilotMessage());
    }
    if (!input._bound) {
        input._bound = true;
        input.addEventListener('keydown', (ev) => {
            if (ev.key === 'Enter' && !ev.shiftKey) {
                ev.preventDefault();
                _sendCopilotMessage();
            }
        });
    }
}

function _wireCopilotChips() {
    document.querySelectorAll('.copilot-chip').forEach((chip) => {
        if (chip._bound) return;
        chip._bound = true;
        chip.addEventListener('click', () => {
            const prompt = chip.dataset.prompt || chip.textContent;
            const input = document.getElementById('copilot-input');
            if (input) input.value = prompt;
            _sendCopilotMessage();
        });
    });
}

function _wireCopilotDraftsRefresh() {
    const btn = document.getElementById('copilot-drafts-refresh');
    if (btn && !btn._bound) {
        btn._bound = true;
        btn.addEventListener('click', () => _refreshCopilotDrafts());
    }
}

function _wireCopilotAuditLink() {
    const link = document.getElementById('copilot-audit-link');
    if (link && !link._bound) {
        link._bound = true;
        link.addEventListener('click', (ev) => {
            ev.preventDefault();
            // Navigate to the BMS view via the nav rail (legacy router).
            const nav = document.querySelector('.nav-item[data-route="bms"]');
            if (nav) nav.click();
            setTimeout(() => {
                if (typeof window.showBmsAudit === 'function') window.showBmsAudit();
            }, 200);
        });
    }
}

// ─── Chat ──────────────────────────────────────────────────────────
async function _sendCopilotMessage() {
    if (_inflight) return;
    const input = document.getElementById('copilot-input');
    const messages = document.getElementById('copilot-messages');
    if (!input || !messages) return;

    const text = (input.value || '').trim();
    if (!text) return;

    _appendCopilotMessage('user', text);
    input.value = '';

    const spinnerId = 'copilot-spinner-' + Date.now();
    _appendCopilotMessage('assistant', '<span class="copilot-spinner">⏳ Thinking…</span>',
        { html: true, id: spinnerId });

    _inflight = true;
    try {
        const r = await fetch('/api/agent/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: text,
                history: _history,
                operator: 'wilmer.angel',
            }),
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();

        const sp = document.getElementById(spinnerId);
        if (sp) sp.remove();

        if (d.tool_invocations && d.tool_invocations.length > 0) {
            _renderToolTrace(d.tool_invocations);
        }
        _appendCopilotMessage('assistant', d.reply || '(empty reply)');

        _history.push({ role: 'user', content: text });
        _history.push({ role: 'assistant', content: d.reply || '' });

        if (d.drafts && d.drafts.length > 0) {
            await _refreshCopilotDrafts();
            _flashDraft(d.drafts[d.drafts.length - 1]);
        }
    } catch (e) {
        const sp = document.getElementById(spinnerId);
        if (sp) sp.remove();
        _appendCopilotMessage('assistant', `⚠ Error: ${escapeHTML(e.message)}`,
            { error: true });
    } finally {
        _inflight = false;
    }
}

function _appendCopilotMessage(role, content, opts) {
    opts = opts || {};
    const messages = document.getElementById('copilot-messages');
    if (!messages) return;

    const div = document.createElement('div');
    div.className = `copilot-msg copilot-msg-${role}`;
    if (opts.error) div.classList.add('copilot-msg-error');
    if (opts.id) div.id = opts.id;

    if (opts.html) {
        // Pre-built HTML — routed through the F3-5 XSS filter.
        div.innerHTML = sanitizeHTML(content);
    } else {
        // LLM-authored text: escape, apply light markdown, then sanitize.
        const html = escapeHTML(content)
            .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
            .replace(/`([^`]+)`/g, '<code>$1</code>')
            .replace(/\n/g, '<br>');
        div.innerHTML = sanitizeHTML(html);
    }
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
}

function _renderToolTrace(invocations) {
    const messages = document.getElementById('copilot-messages');
    if (!messages) return;
    const div = document.createElement('div');
    div.className = 'copilot-msg copilot-tool-trace';
    const rows = invocations.map((inv) => {
        const args = JSON.stringify(inv.args || {});
        const argsTrunc = args.length > 100 ? args.slice(0, 100) + '…' : args;
        return `
            <div class="copilot-tool-row">
                <span class="copilot-tool-name">⚙ ${escapeHTML(inv.tool)}</span>
                <span class="copilot-tool-args" title="${escapeHTML(args)}">${escapeHTML(argsTrunc)}</span>
                <span class="copilot-tool-result">→ ${escapeHTML(inv.result_summary || '')}</span>
            </div>`;
    }).join('');
    div.innerHTML = sanitizeHTML(`<div class="copilot-tool-trace-hdr">Tool calls</div>${rows}`);
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
}

// ─── Drafts ────────────────────────────────────────────────────────
async function _refreshCopilotDrafts() {
    const list = document.getElementById('copilot-drafts-list');
    if (!list) return;
    try {
        const r = await fetch('/api/agent/drafts');
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        const drafts = d.drafts || [];
        if (drafts.length === 0) {
            list.innerHTML = '<div class="copilot-drafts-empty">No drafts pending approval.</div>';
            return;
        }
        // Structured UI with intentional <button>s — NOT routed through
        // sanitizeHTML (it would strip the buttons). Every interpolated
        // value is escapeHTML'd inside _renderDraftCard instead.
        list.innerHTML = drafts.map(_renderDraftCard).join('');
        _wireDraftActions();
    } catch (e) {
        list.innerHTML =
            `<div class="copilot-drafts-empty copilot-drafts-error">⚠ ${escapeHTML(e.message)}</div>`;
    }
}

function _renderDraftCard(d) {
    const meta = d.metadata || {};
    const expiresIn = Math.max(0, Math.round((d.expires_at_unix - (Date.now() / 1000)) / 60));
    const kindLabel = ({
        precool_plan: 'Pre-cooling plan',
        cmms_work_order: 'CMMS work order',
    })[d.kind] || d.kind;

    let summary = '';
    if (d.kind === 'precool_plan') {
        const cmd = (d.commands && d.commands[0]) || {};
        summary = `
            <div class="copilot-draft-summary">
                Setpoint → <strong>${escapeHTML(String(cmd.payload && cmd.payload.target_c))}°C</strong>
                on ${(d.commands || []).length} chiller(s)
            </div>`;
    } else if (d.kind === 'cmms_work_order') {
        const lor = meta.lor || '—';
        const proc = meta.procedure_class || '—';
        const wc = meta.work_class || '—';
        const ppe = (meta.tha && meta.tha.ppe_level) || '—';
        const contractor = meta.contractor && meta.contractor.contractor_required
            ? '<span class="copilot-badge">+MSOW/EMPS</span>' : '';
        summary = `
            <div class="copilot-draft-summary">
                <span class="copilot-badge">Class ${escapeHTML(wc)}</span>
                <span class="copilot-badge">LOR ${escapeHTML(String(lor))}</span>
                <span class="copilot-badge">${escapeHTML(proc)}</span>
                <span class="copilot-badge">PPE ${escapeHTML(ppe)}</span>
                ${contractor}
            </div>
            <div class="copilot-draft-issue">${escapeHTML(meta.issue_summary || '')}</div>`;
    }

    const rationaleShort = (d.rationale || '').slice(0, 220);
    const rationaleEllipsis = d.rationale && d.rationale.length > 220 ? '…' : '';

    return `
        <div class="copilot-draft-card" id="copilot-draft-${escapeHTML(d.draft_id)}">
            <div class="copilot-draft-hdr">
                <span class="copilot-draft-kind">${escapeHTML(kindLabel)}</span>
                <span class="copilot-draft-ttl">expires in ${expiresIn} min</span>
            </div>
            ${summary}
            <div class="copilot-draft-rationale">${escapeHTML(rationaleShort)}${rationaleEllipsis}</div>
            <div class="copilot-draft-actions">
                <button class="copilot-draft-btn copilot-draft-approve" data-draft-id="${escapeHTML(d.draft_id)}">
                    ✓ Approve
                </button>
                <button class="copilot-draft-btn copilot-draft-reject" data-draft-id="${escapeHTML(d.draft_id)}">
                    ✗ Reject
                </button>
                <button class="copilot-draft-btn copilot-draft-inspect" data-draft-id="${escapeHTML(d.draft_id)}">
                    🔍 Inspect
                </button>
            </div>
            <div class="copilot-draft-id" title="Draft ID for audit traceability">
                ${escapeHTML(d.draft_id)}
            </div>
        </div>`;
}

function _wireDraftActions() {
    document.querySelectorAll('.copilot-draft-approve').forEach((btn) => {
        if (btn._bound) return;
        btn._bound = true;
        btn.addEventListener('click', () => _approveDraft(btn.dataset.draftId));
    });
    document.querySelectorAll('.copilot-draft-reject').forEach((btn) => {
        if (btn._bound) return;
        btn._bound = true;
        btn.addEventListener('click', () => _rejectDraft(btn.dataset.draftId));
    });
    document.querySelectorAll('.copilot-draft-inspect').forEach((btn) => {
        if (btn._bound) return;
        btn._bound = true;
        btn.addEventListener('click', () => _inspectDraft(btn.dataset.draftId));
    });
}

async function _approveDraft(draftId) {
    if (!confirm(
        `Approve draft ${draftId.slice(0, 8)}…?\n\n`
        + `This will execute the proposed commands through the audit-gated `
        + `BMS write path. NIST SP 800-82 audit log will record the `
        + `operator user-id and draft correlation ID.`
    )) return;
    try {
        const r = await fetch(`/api/agent/draft/${draftId}/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ operator: 'wilmer.angel' }),
        });
        if (!r.ok) {
            const err = await r.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${r.status}`);
        }
        const d = await r.json();
        const exec = (d.execution_log || []).map((x) =>
            `${x.status === 'EXECUTED' ? '✓' : '✗'} ${escapeHTML(x.tag_id || x.note || '')} `
            + `${escapeHTML(x.message || '')}`).join('<br>');
        _appendCopilotMessage('assistant',
            `<strong>Draft ${escapeHTML(draftId.slice(0, 8))}… APPROVED</strong> by wilmer.angel<br>`
            + (exec || '(no commands executed — likely a CMMS WO that proceeds to manual dispatch)')
            + '<br><em>Audit logged per NIST SP 800-82.</em>',
            { html: true });
        await _refreshCopilotDrafts();
    } catch (e) {
        _appendCopilotMessage('assistant', `⚠ Approve failed: ${e.message}`, { error: true });
    }
}

async function _rejectDraft(draftId) {
    const reason = prompt(
        `Reject draft ${draftId.slice(0, 8)}…\n\n`
        + 'Reason (required — feeds the v6 retraining signal):', '');
    if (!reason || !reason.trim()) return;
    try {
        const r = await fetch(`/api/agent/draft/${draftId}/reject`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ operator: 'wilmer.angel', reason: reason.trim() }),
        });
        if (!r.ok) {
            const err = await r.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${r.status}`);
        }
        _appendCopilotMessage('assistant',
            `Draft ${draftId.slice(0, 8)}… REJECTED. Rationale: "${reason}"`);
        await _refreshCopilotDrafts();
    } catch (e) {
        _appendCopilotMessage('assistant', `⚠ Reject failed: ${e.message}`, { error: true });
    }
}

async function _inspectDraft(draftId) {
    try {
        const r = await fetch(`/api/agent/draft/${draftId}`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        _showDraftInspectModal(await r.json());
    } catch (e) {
        _appendCopilotMessage('assistant', `⚠ Inspect failed: ${e.message}`, { error: true });
    }
}

function _showDraftInspectModal(draft) {
    document.querySelectorAll('.copilot-inspect-modal').forEach((el) => el.remove());

    const overlay = document.createElement('div');
    overlay.className = 'copilot-inspect-modal';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);'
        + 'z-index:999999;display:flex;align-items:center;justify-content:center;cursor:pointer;';

    const panel = document.createElement('div');
    panel.style.cssText = 'background:#14181D;border:1px solid #00B8D4;border-radius:6px;'
        + 'width:760px;max-width:95vw;height:80vh;max-height:80vh;display:flex;'
        + 'flex-direction:column;cursor:auto;box-shadow:0 4px 32px rgba(0,0,0,0.7);overflow:hidden;';

    const header = document.createElement('div');
    header.style.cssText = 'display:flex;justify-content:space-between;align-items:center;'
        + 'padding:12px 16px;border-bottom:1px solid #2A3038;color:#E8EAED;'
        + 'font-weight:600;flex:0 0 auto;';
    const kindLabel = ({
        precool_plan: 'Pre-cooling plan',
        cmms_work_order: 'CMMS work order',
    })[draft.kind] || draft.kind;
    header.innerHTML = sanitizeHTML(`<span>Draft inspector: ${escapeHTML(kindLabel)}</span>`);

    const closeBtn = document.createElement('button');
    closeBtn.textContent = '×';
    closeBtn.style.cssText = 'background:transparent;border:none;color:#9AA0A6;'
        + 'font-size:28px;cursor:pointer;padding:0 12px;line-height:1;min-width:36px;min-height:36px;';
    closeBtn.onclick = (ev) => { ev.stopPropagation(); overlay.remove(); };
    header.appendChild(closeBtn);
    panel.appendChild(header);

    const body = document.createElement('div');
    body.style.cssText = 'padding:16px;overflow-y:auto;color:#E8EAED;flex:1 1 auto;'
        + 'min-height:0;font-family:monospace;font-size:11px;line-height:1.5;';
    body.innerHTML = sanitizeHTML(
        `<pre style="white-space:pre-wrap;margin:0;">${escapeHTML(JSON.stringify(draft, null, 2))}</pre>`);
    panel.appendChild(body);

    overlay.appendChild(panel);
    overlay.addEventListener('click', (ev) => {
        if (ev.target === overlay) overlay.remove();
    });
    document.body.appendChild(overlay);
}

function _flashDraft(draftId) {
    setTimeout(() => {
        const el = document.getElementById('copilot-draft-' + draftId);
        if (el) {
            el.classList.add('copilot-draft-flash');
            setTimeout(() => el.classList.remove('copilot-draft-flash'), 2400);
        }
    }, 100);
}

// ─── EDA — surface a resolved multi-agent consensus into the chat ──
function _onAgentConsensus(e) {
    const view = document.getElementById('view-copilot');
    if (!view || view.hasAttribute('hidden')) return;
    const d = (e && e.detail) || {};
    const veto = d.veto_active ? ' · ⛔ SAFETY VETO' : '';
    _appendCopilotMessage('assistant',
        `⚖ Multi-agent consensus: ${d.content || d.event || 'resolved'}${veto}`);
}

/** Public entry — called once from main.js at bootstrap. */
export function initCopilotView() {
    if (_initialized) return;
    if (!document.getElementById('view-copilot')) {
        console.warn('[copilot] #view-copilot not in DOM; view disabled.');
        return;
    }
    registerRoute('copilot', { viewId: 'view-copilot', activate: _renderCopilotView });
    document.addEventListener('hermes:agent-consensus', _onAgentConsensus);
    _initialized = true;
    console.log('[copilot] view ready (Facility Co-Pilot — T2.1 ES module, XSS-sanitized)');
}

// ─── Test surface ──────────────────────────────────────────────────
export const __copilot_test__ = {
    appendCopilotMessage: _appendCopilotMessage,
    renderToolTrace: _renderToolTrace,
    renderDraftCard: _renderDraftCard,
    onAgentConsensus: _onAgentConsensus,
    reset: () => {
        _initialized = false;
        _history = [];
        _inflight = false;
        if (_draftsTimer) { clearInterval(_draftsTimer); _draftsTimer = null; }
        document.querySelectorAll('.copilot-inspect-modal').forEach((el) => el.remove());
    },
};
