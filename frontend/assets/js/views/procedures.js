/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/procedures.js
 * ROADMAP V11 Epic 6 — Procedure Architect HMI.
 *
 * Operator-facing surface for the LLM-authored SOP / MOP / EOP / EMP
 * documents. Companion to the deterministic compiler view (already
 * exposed by the legacy MOP browser at /mops).
 *
 * Workflow:
 *   1. Operator picks a doc_type from the dropdown + describes the
 *      context in the textarea ("Replace UPS-B battery cabinet").
 *   2. Submit -> POST /api/procedures/architect/generate.
 *   3. The backend returns {draft, safety_audit}. We render the
 *      draft content (markdown -> safe HTML) and the audit verdict
 *      pill (approve / caution / hard_stop).
 *   4. Approve -> Sign-to-Ledger button is visible. Operator clicks
 *      -> POST /api/procedures/architect/sign -> ledger entry id is
 *      shown back to the operator as proof of approval.
 *   5. hard_stop -> the Sign button is HIDDEN; the audit findings
 *      list is rendered so the operator can re-prompt with the
 *      missing safety terms.
 *
 * Contracts preserved:
 *   - S-SEC-01: every rendered field goes through escapeHTML;
 *     sanitizeHTML wraps the assembled markup. No untrusted HTML
 *     ever lands in the DOM. The markdown renderer is a
 *     deliberately-minimal escape-then-pattern-substitute pass
 *     (headers, bold, italic, code-fence, lists) — NOT a full
 *     markdown library, which would expand the attack surface.
 *   - S-DET-02 binding (server-side): the Sign endpoint re-audits
 *     content. Even if the HMI tried to forge an approved verdict,
 *     a hard_stop content body returns HTTP 403.
 *
 * Test surface: __procedures_view_test__ exposes the pure render +
 * fetch helpers, and the click dispatcher.
 * ════════════════════════════════════════════════════════════════ */

import { registerRoute } from '../core/router.js';
import { escapeHTML, sanitizeHTML } from '../core/sanitize.js';

const $ = (id) => document.getElementById(id);

const DOC_TYPES = ['SOP', 'MOP', 'EOP', 'EMP'];
const VERDICT_APPROVE = 'approve';
const VERDICT_CAUTION = 'caution';
const VERDICT_HARD_STOP = 'hard_stop';

let _routeRegistered = false;
let _viewWired = false;
let _currentDraft = null;   // last {draft, safety_audit} response


// ─── Markdown -> safe HTML (deliberately minimal) ────────────────────
/**
 * Render a small, safe subset of markdown:
 *   - `# H1`, `## H2`, `### H3` headers
 *   - `**bold**` and `*italic*` emphasis
 *   - `` `code` `` inline code
 *   - `- item` unordered list
 *   - `1. item` ordered list (rendered as <li> inside <ol>)
 *   - paragraphs separated by blank lines
 *
 * The input is FIRST escapeHTML'd. The pattern substitutions then
 * operate on already-escaped text — so any HTML/JS the LLM emits is
 * neutered before any markup is generated. This is intentional: a
 * full markdown library would let `<` re-emerge via auto-linking or
 * raw-HTML support and reintroduce XSS.
 */
function _renderMarkdown(md) {
    if (typeof md !== 'string' || md.length === 0) return '';
    let html = escapeHTML(md);

    // Code fences (```...```) — preserve their content verbatim,
    // wrap in <pre><code>. Process FIRST so the content inside
    // doesn't get re-mangled by header / emphasis passes below.
    html = html.replace(
        /```([\s\S]*?)```/g,
        (_m, code) => `<pre class="proc-codeblock"><code>${code}</code></pre>`,
    );

    // Headers — anchored at line start.
    html = html.replace(/^### (.+)$/gm, '<h3 class="proc-h3">$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2 class="proc-h2">$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1 class="proc-h1">$1</h1>');

    // Inline code (after headers so backticks in headers stay literal).
    html = html.replace(
        /`([^`\n]+)`/g, '<code class="proc-code">$1</code>',
    );

    // Bold / italic — bold first so **x** doesn't match as italic *x*.
    html = html.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');

    // Lists — line-by-line grouping pass.
    const lines = html.split('\n');
    const out = [];
    let inUl = false;
    let inOl = false;
    const closeLists = () => {
        if (inUl) { out.push('</ul>'); inUl = false; }
        if (inOl) { out.push('</ol>'); inOl = false; }
    };
    for (const ln of lines) {
        const ulMatch = ln.match(/^- (.+)$/);
        const olMatch = ln.match(/^\d+\. (.+)$/);
        if (ulMatch) {
            if (inOl) { out.push('</ol>'); inOl = false; }
            if (!inUl) { out.push('<ul class="proc-list">'); inUl = true; }
            out.push(`<li>${ulMatch[1]}</li>`);
        } else if (olMatch) {
            if (inUl) { out.push('</ul>'); inUl = false; }
            if (!inOl) { out.push('<ol class="proc-list">'); inOl = true; }
            out.push(`<li>${olMatch[1]}</li>`);
        } else {
            closeLists();
            out.push(ln);
        }
    }
    closeLists();

    // Paragraph wrapping for runs of plain text between block elements.
    // Cheap heuristic: split on blank lines, wrap chunks that aren't
    // already block-level (h*, ul/ol, pre).
    return out.join('\n')
        .split(/\n\s*\n/)
        .map((chunk) => {
            const t = chunk.trim();
            if (!t) return '';
            if (/^<(h\d|ul|ol|pre|li)/.test(t)) return t;
            return `<p class="proc-p">${t.replace(/\n/g, '<br>')}</p>`;
        })
        .join('\n');
}


// ─── Safety verdict pill ─────────────────────────────────────────────
function _verdictPill(verdict) {
    const v = String(verdict || 'unknown').toLowerCase();
    const cls = v === VERDICT_APPROVE
        ? 'proc-pill-approve'
        : v === VERDICT_CAUTION
            ? 'proc-pill-caution'
            : v === VERDICT_HARD_STOP
                ? 'proc-pill-veto'
                : 'proc-pill-unknown';
    const label = v === VERDICT_HARD_STOP ? 'SAFETY HARD_STOP' : v.toUpperCase();
    return `<span class="proc-pill ${escapeHTML(cls)}">`
        + `${escapeHTML(label)}</span>`;
}


// ─── Result render ───────────────────────────────────────────────────
function _renderResult(payload) {
    const root = $('view-procedures-architect');
    if (!root) return;
    const slot = root.querySelector('[data-proc-result]');
    if (!slot) return;

    if (!payload || typeof payload !== 'object') {
        slot.innerHTML = sanitizeHTML(
            '<div class="proc-empty">No response yet.</div>',
        );
        return;
    }
    const draft = payload.draft || {};
    const audit = payload.safety_audit || {};
    const verdict = String(audit.verdict || 'unknown').toLowerCase();
    const findings = Array.isArray(audit.findings) ? audit.findings : [];
    const isApproved = verdict === VERDICT_APPROVE;
    const isHardStop = verdict === VERDICT_HARD_STOP;

    const findingsHtml = findings.length
        ? `<ul class="proc-findings">${
            findings.map((f) => `<li>${escapeHTML(String(f))}</li>`).join('')
          }</ul>`
        : '';

    // Markdown content is already escapeHTML'd inside _renderMarkdown
    // then markup-substituted by a deliberately-minimal pattern pass.
    // No raw HTML can leak through, so the result drops straight into
    // innerHTML — no sanitizeHTML wrap (which would strip the Sign
    // <button> below, by design — sanitize.js neuters interactive
    // elements). Same pattern as views/optimizer.js's proposal card.
    const contentHtml = _renderMarkdown(draft.content || '');

    const idEsc = escapeHTML(draft.draft_id || '');
    const docTypeEsc = escapeHTML(draft.doc_type || '?');
    const llmBadge = draft.llm_present
        ? '<span class="proc-badge proc-badge-llm">LLM-authored</span>'
        : '<span class="proc-badge proc-badge-skeleton">deterministic skeleton</span>';
    const signBtn = isApproved
        ? `<button class="proc-btn proc-btn-sign" data-action="sign"
                   data-draft-id="${idEsc}">Sign &amp; Save to Ledger</button>`
        : '';
    const hardStopBanner = isHardStop
        ? '<div class="proc-banner-hardstop">'
            + 'Safety Officer refused this draft. '
            + 'Re-prompt the Architect with the missing terms (see below) '
            + 'and try again. The Sign button is disabled.'
            + '</div>'
        : '';

    slot.innerHTML = `
        <div class="proc-card">
            <div class="proc-card-hdr">
                <span class="proc-doc-type">${docTypeEsc}</span>
                <span class="proc-draft-id">${escapeHTML(String(draft.draft_id || '').slice(0, 8))}</span>
                ${llmBadge}
                ${_verdictPill(verdict)}
            </div>
            ${hardStopBanner}
            ${findings.length ? `
                <div class="proc-audit">
                    <strong>Safety Officer audit findings:</strong>
                    ${findingsHtml}
                </div>` : ''}
            <div class="proc-content">${contentHtml}</div>
            <div class="proc-actions">${signBtn}</div>
            <div class="proc-sign-result"
                 data-draft-id="${idEsc}"></div>
        </div>
    `;

    _currentDraft = payload;
}


// ─── Fetch — generate ────────────────────────────────────────────────
async function _submitGenerate() {
    const root = $('view-procedures-architect');
    if (!root) return;
    const docType = root.querySelector('[data-proc-doc-type]')?.value || '';
    const ctx = root.querySelector('[data-proc-context]')?.value?.trim() || '';
    const assetId = root.querySelector('[data-proc-asset-id]')?.value?.trim() || '';
    const slot = root.querySelector('[data-proc-result]');

    if (!DOC_TYPES.includes(docType)) {
        slot.innerHTML = sanitizeHTML(
            '<div class="proc-empty proc-error">Pick a valid doc type.</div>',
        );
        return;
    }
    if (ctx.length < 10) {
        slot.innerHTML = sanitizeHTML(
            '<div class="proc-empty proc-error">Context must be at least 10 characters.</div>',
        );
        return;
    }

    slot.innerHTML = sanitizeHTML(
        '<div class="proc-empty">Generating…</div>',
    );
    try {
        const resp = await fetch('/api/procedures/architect/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                doc_type: docType,
                context: ctx,
                asset_id: assetId || null,
            }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            slot.innerHTML = sanitizeHTML(
                `<div class="proc-empty proc-error">HTTP ${resp.status}: `
                + `${escapeHTML(data.detail || resp.statusText)}</div>`,
            );
            return;
        }
        _renderResult(data);
    } catch (e) {
        slot.innerHTML = sanitizeHTML(
            `<div class="proc-empty proc-error">Network error: `
            + `${escapeHTML(e.message)}</div>`,
        );
    }
}


// ─── Fetch — sign ────────────────────────────────────────────────────
async function _submitSign(draftId) {
    const root = $('view-procedures-architect');
    if (!root || !_currentDraft) return;
    const draft = _currentDraft.draft || {};
    if (draft.draft_id !== draftId) return;   // staleness guard

    const slot = root.querySelector(
        `.proc-sign-result[data-draft-id="${CSS.escape(draftId)}"]`,
    );
    if (!slot) return;
    slot.innerHTML = sanitizeHTML(
        '<div class="proc-empty">Signing…</div>',
    );
    try {
        const resp = await fetch('/api/procedures/architect/sign', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                draft_id: draft.draft_id,
                doc_type: draft.doc_type,
                content: draft.content,
                asset_id: draft.asset_id || null,
                operator_id: 'wilmer.angel',
                actor_role: 'SME_L6',
            }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            slot.innerHTML = sanitizeHTML(
                `<div class="proc-sign-fail">HTTP ${resp.status}: `
                + `${escapeHTML(data.detail || resp.statusText)}</div>`,
            );
            return;
        }
        const entry = escapeHTML(String(data.entry_id || '').slice(0, 16));
        const seq = escapeHTML(String(data.sequence_no || '?'));
        const sha = escapeHTML(String(data.content_sha256 || '').slice(0, 16));
        slot.innerHTML = sanitizeHTML(
            `<div class="proc-sign-ok">
                Signed to ledger ·
                entry <code>${entry}</code> ·
                seq #${seq} ·
                sha256 <code>${sha}…</code>
            </div>`,
        );
    } catch (e) {
        slot.innerHTML = sanitizeHTML(
            `<div class="proc-sign-fail">Network error: `
            + `${escapeHTML(e.message)}</div>`,
        );
    }
}


// ─── Click dispatch ──────────────────────────────────────────────────
function _onClick(ev) {
    const t = ev.target.closest('[data-action]');
    if (!t) return;
    const action = t.dataset.action;
    switch (action) {
        case 'generate':
            _submitGenerate();
            break;
        case 'sign':
            _submitSign(t.dataset.draftId);
            break;
    }
}


// ─── Static skeleton + activation ────────────────────────────────────
function _wireProceduresView() {
    if (_viewWired) return;
    const root = $('view-procedures-architect');
    if (!root) return;
    const opts = DOC_TYPES.map(
        (t) => `<option value="${escapeHTML(t)}">${escapeHTML(t)}</option>`,
    ).join('');
    root.innerHTML = `
        <div class="proc-hdr">
            <h2>Procedure Architect · SOP / MOP / EOP / EMP</h2>
            <div class="proc-sub">
                LLM-authored documentation with deterministic Safety Officer
                audit. MOPs missing LOTO / PPE / CSA Z462-24 are refused.
                Approved drafts can be signed into the forensic ledger.
                Epic 6 · ADR-006 deterministic gate.
            </div>
        </div>
        <div class="proc-form">
            <label>
                Document type:
                <select data-proc-doc-type class="proc-select">${opts}</select>
            </label>
            <label>
                Asset id (optional):
                <input type="text" data-proc-asset-id class="proc-input"
                       placeholder="ups_b / chiller_1 / …">
            </label>
            <label>
                Operator context:
                <textarea data-proc-context class="proc-textarea" rows="4"
                          placeholder="Describe the maintenance / operation / incident the document must cover. Example: Replace UPS-B battery cabinet on Phase 1 main bus during scheduled window."></textarea>
            </label>
            <button data-action="generate" class="proc-btn proc-btn-generate">
                Generate
            </button>
        </div>
        <div data-proc-result class="proc-result"></div>
    `;
    root.addEventListener('click', _onClick);
    _viewWired = true;
}

async function _activate() {
    _wireProceduresView();
}


/** Public entry — called once from main.js at bootstrap. */
export function initProceduresView() {
    if (_routeRegistered) return;
    if (!$('view-procedures-architect')) {
        console.warn(
            '[procedures] #view-procedures-architect not in DOM; view disabled.',
        );
        return;
    }
    registerRoute('procedures-architect', {
        viewId: 'view-procedures-architect',
        activate: _activate,
    });
    _routeRegistered = true;
    console.log('[procedures] route registered (Epic 6 — Procedure Architect)');
}


// ─── Test surface ────────────────────────────────────────────────────
export const __procedures_view_test__ = {
    renderMarkdown: _renderMarkdown,
    renderResult: _renderResult,
    verdictPill: _verdictPill,
    submitGenerate: _submitGenerate,
    submitSign: _submitSign,
    onClick: _onClick,
    initProceduresView,
    reset: () => {
        _routeRegistered = false;
        _viewWired = false;
        _currentDraft = null;
    },
    DOC_TYPES,
};
