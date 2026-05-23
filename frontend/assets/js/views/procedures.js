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

// ─── Pre-defined asset picker ────────────────────────────────────────
// Curated Path-C2 asset list (per CLAUDE.md "config/site_model.yml ←
// 91 components"). Grouped by domain for the optgroup labels. The
// operator can also pick "Custom…" to type any canonical_id manually,
// or leave it blank for a site-wide procedure.
//
// This list is intentionally hardcoded (not a /api/site/components
// fetch) — keeps the view network-independent at activation, and the
// operator's most common picks load instantly. Extension path: swap
// to a fetch on activate + cache. The Custom option always escapes.
const ASSET_PRESETS = [
    { group: 'Electrical — UPS / Transformers / Switchgear', items: [
        { id: 'ups_a',         label: 'UPS A (Path A)' },
        { id: 'ups_b',         label: 'UPS B (Path B)' },
        { id: 'xfmr_a',        label: 'Transformer A' },
        { id: 'xfmr_b',        label: 'Transformer B' },
        { id: 'utility_north', label: 'Utility North (Path A)' },
        { id: 'utility_south', label: 'Utility South (Path B)' },
    ] },
    { group: 'Electrical — Distribution', items: [
        { id: 'rpp_a1', label: 'RPP A1 (Path A)' },
        { id: 'rpp_a2', label: 'RPP A2 (Path A)' },
        { id: 'rpp_b1', label: 'RPP B1 (Path B)' },
        { id: 'rpp_b2', label: 'RPP B2 (Path B)' },
        { id: 'busway_a', label: 'Busway A' },
        { id: 'busway_b', label: 'Busway B' },
    ] },
    { group: 'Mechanical — Cooling', items: [
        { id: 'chiller_1',     label: 'Chiller 1 (York YZ)' },
        { id: 'chiller_2',     label: 'Chiller 2 (York YZ)' },
        { id: 'cdu_a',         label: 'CDU A (DLC primary)' },
        { id: 'cdu_b',         label: 'CDU B (DLC primary)' },
        { id: 'cooling_tower', label: 'Cooling Tower (N+1)' },
    ] },
    { group: 'IT Halls', items: [
        { id: 'hall_1', label: 'Hall 1 (Building A)' },
        { id: 'hall_2', label: 'Hall 2 (Building A)' },
        { id: 'hall_3', label: 'Hall 3 (Building B)' },
    ] },
];

const ASSET_CUSTOM_VALUE = '__custom__';
const ASSET_NONE_VALUE = '';

// ─── Pre-defined context templates per doc_type ──────────────────────
// Click a chip to pre-fill the textarea. `{asset}` is substituted with
// the currently selected asset_id (or "the affected asset" when none
// is picked — keeps the template grammatical without a server round-
// trip). Operator can edit after the auto-fill — the chip is a starter,
// not a lock-in.
//
// 3-5 templates per doc_type chosen to span the common operator
// playbook for each category. Free-form context still works — the
// chips are a UX accelerator, not a constraint.
const CONTEXT_TEMPLATES = {
    SOP: [
        { label: 'Daily round',
          text: 'Daily round of {asset}. Verify BMS setpoints, '
                + 'inspect for alarms, log the reading.' },
        { label: 'Weekly preventive',
          text: 'Weekly preventive inspection of {asset}. Check '
                + 'physical condition, BMS trend, no off-nominal '
                + 'parameters in the EPMS.' },
        { label: 'Monthly PM',
          text: 'Monthly preventive maintenance of {asset}. Walk '
                + 'the unit, verify HMI states match physical state, '
                + 'record the closure.' },
        { label: 'Shift handover',
          text: 'Shift handover round including {asset}. Confirm '
                + 'BMS values, open incidents, pending MOPs are '
                + 'communicated to the incoming CET.' },
    ],
    MOP: [
        // Back-out language is math-grounded (industry-notes follow-up):
        // every chip pins the back-out window to a physical bound
        // operators can actually compute (battery runtime, ASHRAE A2
        // envelope, sync-check expiry, vendor rollback availability).
        { label: 'Battery cabinet replace',
          text: 'Replace battery cabinet on {asset} during the '
                + 'scheduled maintenance window. Coordinate LOTO + PPE '
                + 'category 2 per CSA Z462-24. Vendor escort required. '
                + 'Back-out plan: revert before battery autonomy at the '
                + 'current load reaches the low-voltage cutoff — read '
                + '`battery_runtime_min` from the BMS before isolation '
                + 'and use that as the hard deadline.' },
        { label: 'Load transfer',
          text: 'Planned load transfer maneuver on {asset}. Coordinate '
                + 'with the redundant path; verify the alternate is '
                + 'healthy before isolation. LOTO + PPE per CSA Z462-24. '
                + 'Back-out plan: if the alternate degrades during the '
                + 'transfer, revert before the sync-check window '
                + 'expires; the back-out budget is bounded by the '
                + 'redundant UPS runtime under projected post-transfer '
                + 'load.' },
        { label: 'Filter / fluid service',
          text: 'Scheduled filter and fluid service on {asset}. Isolate '
                + 'the unit per the LOTO protocol; wear the PPE the '
                + 'CSA Z462-24 risk table requires for the energy class. '
                + 'Back-out plan: if the redundant cooling chain '
                + 'destabilises (ECWT rise, secondary loop pressure '
                + 'drop, hall inlet trending up), restore the isolated '
                + 'unit before the thermal envelope breaches ASHRAE A2 '
                + '(35 °C inlet cap).' },
        { label: 'Firmware upgrade',
          text: 'Firmware upgrade on {asset}. Stage the binary, '
                + 'arrange the vendor service window, define the LOTO '
                + 'scope and PPE per CSA Z462-24 for any physical '
                + 'access. Back-out plan: keep the prior firmware '
                + 'binary staged + a vendor on-call session active; '
                + 'the back-out budget is bounded by the operator '
                + "confidence interval on the vendor's documented "
                + 'rollback procedure.' },
    ],
    EOP: [
        { label: 'Loss of redundancy',
          text: 'Loss of redundancy event on {asset}. Confirm the '
                + 'alarm, isolate the affected component, escalate per '
                + 'the redundancy-violation matrix. Contain before '
                + 'further degradation.' },
        { label: 'Thermal event',
          text: 'Thermal event on {asset}. Containment: open the '
                + 'rack door, reduce IT load, escalate to mechanical '
                + 'lead. Isolate the affected cooling chain.' },
        { label: 'Electrical fault',
          text: 'Electrical fault detected on {asset}. Contention: '
                + 'isolate the affected bus, transfer load to the '
                + 'redundant path, halt any in-flight maintenance.' },
        { label: 'BMS comms loss',
          text: 'BMS comms loss to {asset}. Containment: fall back to '
                + 'local control panel, isolate the BMS write path, '
                + 'escalate to the controls vendor on-call.' },
    ],
    EMP: [
        { label: 'Site-wide power loss',
          text: 'Site-wide loss-of-utility event. Activate the '
                + 'incident command bridge; coordinate logistics, '
                + 'on-site escort, customer communications, vendor '
                + 'dispatch.' },
        { label: 'Multi-site coordination',
          text: 'Multi-site incident coordination. Designate the '
                + 'incident commander on each side; align customer '
                + 'communications and escalation paths.' },
        { label: 'Vendor escalation',
          text: 'Vendor escalation playbook. Define incident command '
                + 'authority, dispatch path for field engineers, '
                + 'access escort, stakeholder communication template.' },
    ],
};

let _routeRegistered = false;
let _viewWired = false;
let _currentDraft = null;   // last {draft, safety_audit} response

// Epic 6 Sprint 3 Phase 2 — stale-verdict invalidation.
// Snapshot of the context the operator submitted to /generate. When
// the textarea diverges from this snapshot we mark the result card
// as stale, hide the Sign button, and surface a "Re-generate
// required" banner. Prevents the safety-critical class of bug where
// an operator edits the textarea after seeing APPROVE and then
// clicks Sign on a draft that doesn't match the current text.
let _lastGeneratedContext = null;
let _staleHandlerInstalled = false;


// ─── Form helpers — asset picker + context auto-fill ────────────────
/** Build the asset-id <select>'s inner markup. Includes a "(none)"
 *  option, the curated optgroups, and the trailing "Custom…" option
 *  that reveals the manual text input below. Every label + id flows
 *  through escapeHTML — defensive even though the source is a static
 *  module-level constant. */
function _renderAssetSelect() {
    const none = `<option value="${ASSET_NONE_VALUE}">`
        + '(none — site-wide procedure)</option>';
    const groups = ASSET_PRESETS.map((g) => {
        const opts = g.items.map(
            (it) => `<option value="${escapeHTML(it.id)}">`
                + `${escapeHTML(it.label)}</option>`,
        ).join('');
        return `<optgroup label="${escapeHTML(g.group)}">${opts}</optgroup>`;
    }).join('');
    const custom = `<option value="${ASSET_CUSTOM_VALUE}">`
        + '(Custom — type below)</option>';
    return none + groups + custom;
}

/** Resolve the effective asset id from the form (preset choice OR the
 *  custom text input when the picker is set to Custom). Returns "" for
 *  site-wide / unspecified. Trimmed; never returns the sentinel. */
function _resolveAssetId(root) {
    const sel = root.querySelector('[data-proc-asset-select]')?.value || '';
    if (sel === ASSET_CUSTOM_VALUE) {
        return (
            root.querySelector('[data-proc-asset-custom]')?.value?.trim() || ''
        );
    }
    return sel === ASSET_NONE_VALUE ? '' : sel;
}

/** Show / hide the Custom text input based on the picker selection.
 *  Hidden by default; revealed only when the operator picks the
 *  sentinel "(Custom)" option. */
function _syncCustomAssetVisibility(root) {
    const sel = root.querySelector('[data-proc-asset-select]')?.value || '';
    const wrap = root.querySelector('[data-proc-asset-custom-wrap]');
    if (!wrap) return;
    wrap.hidden = sel !== ASSET_CUSTOM_VALUE;
}

/** Re-render the context quick-pick chip row for the currently
 *  selected doc_type. Each chip is a <button data-action="ctx-fill"
 *  data-ctx-text="..."> — the click dispatcher routes it to
 *  _applyContextTemplate. */
function _renderContextChips(root) {
    const slot = root.querySelector('[data-proc-ctx-chips]');
    if (!slot) return;
    const docType = root.querySelector('[data-proc-doc-type]')?.value || 'SOP';
    const templates = CONTEXT_TEMPLATES[docType] || [];
    if (templates.length === 0) {
        slot.innerHTML = '';
        return;
    }
    const chips = templates.map((t) => (
        '<button type="button" class="proc-chip" '
        + 'data-action="ctx-fill" '
        + `data-ctx-text="${escapeHTML(t.text)}">`
        + escapeHTML(t.label)
        + '</button>'
    )).join('');
    slot.innerHTML = '<span class="proc-chips-hint">'
        + 'Quick context — click a template to pre-fill:'
        + '</span> ' + chips;
}

/** Apply a clicked chip's template to the textarea, substituting
 *  ``{asset}`` with the currently selected asset_id (or a neutral
 *  placeholder when none). Replaces existing textarea content —
 *  intentional, the operator can re-edit. */
function _applyContextTemplate(root, templateText) {
    const ta = root.querySelector('[data-proc-context]');
    if (!ta) return;
    const asset = _resolveAssetId(root);
    const replaced = String(templateText || '').replace(
        /\{asset\}/g,
        asset || 'the affected asset',
    );
    ta.value = replaced;
    // Visual feedback: focus the textarea so the operator sees the cursor.
    ta.focus();
}


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


// ─── Pre-pull telemetry (Epic 6 Sprint 3 Phase 3) ───────────────────
// Whitelist of telemetry keys that get packed into the Architect
// metadata block. Keep the set narrow on purpose -- the LLM author
// only benefits from grounding signals (load + thermal + PUE +
// scenario), not every column of the telemetry table. A larger set
// dilutes the prompt + costs tokens for no quality gain.
const _TELEMETRY_METADATA_KEYS = [
    'pue',
    'it_load_kw',
    'hall_temp_c',
    'delta_t_c',
    'scenario',
];

/** Fetch /api/telemetry/latest and reduce to the curated metadata
 *  whitelist. Returns ``{}`` on any failure (network down, endpoint
 *  503, payload missing the ``latest`` field) so the Generate flow
 *  never aborts on a telemetry hiccup -- the request still goes out,
 *  just without the LIVE OPERATING METADATA block. */
async function _fetchTelemetrySnapshot() {
    try {
        const resp = await fetch('/api/telemetry/latest');
        if (!resp.ok) return {};
        const data = await resp.json();
        const latest = data && data.latest;
        if (!latest || typeof latest !== 'object') return {};
        const out = {};
        for (const k of _TELEMETRY_METADATA_KEYS) {
            if (latest[k] !== undefined && latest[k] !== null) {
                out[k] = latest[k];
            }
        }
        // Tag the snapshot timestamp so the ledger entry can audit
        // which moment-in-time informed the document.
        if (typeof data.ts === 'number') out.snapshot_ts = data.ts;
        return out;
    } catch (_) {
        return {};
    }
}


// ─── Stale-verdict invalidation (Epic 6 Sprint 3 Phase 2) ──────────
/** True when the operator has edited the textarea AFTER the most
 *  recent successful generate. The Sign button must be hidden and
 *  the result card visually marked stale in that case. */
function _isStaleVsLastGenerate(root) {
    if (_lastGeneratedContext === null) return false;
    const ta = root.querySelector('[data-proc-context]');
    if (!ta) return false;
    return ta.value !== _lastGeneratedContext;
}

/** Mark the current result card as stale -- replaces the approve
 *  card UI with a "re-generate required" banner. Idempotent: calling
 *  twice in a row is a no-op (the marker is the dataset attr). */
function _markResultStale(root) {
    const slot = root.querySelector('[data-proc-result]');
    if (!slot) return;
    if (slot.dataset.stale === '1') return;
    slot.dataset.stale = '1';
    // Hide any Sign button that's still in the DOM (defence in depth
    // -- the next render will also drop it, but if the operator races
    // a click between input + re-render, this catches it).
    slot.querySelectorAll('.proc-btn-sign').forEach((b) => {
        b.disabled = true;
        b.hidden = true;
    });
    // Surface the stale banner above whatever's still rendered.
    if (!slot.querySelector('.proc-banner-stale')) {
        const banner = document.createElement('div');
        banner.className = 'proc-banner-stale';
        banner.textContent = (
            'The context has been edited since this draft was generated. '
            + 'The Safety Officer verdict above is STALE and the Sign '
            + 'button is disabled. Click Generate again to re-evaluate.'
        );
        slot.insertBefore(banner, slot.firstChild);
    }
}

/** Wire the textarea ``input`` listener once -- subsequent calls are
 *  no-ops. Each input event compares current text vs the snapshot
 *  taken at the last successful generate and marks the card stale
 *  when they diverge. */
function _installStaleHandler(root) {
    if (_staleHandlerInstalled) return;
    const ta = root.querySelector('[data-proc-context]');
    if (!ta) return;
    ta.addEventListener('input', () => {
        if (_isStaleVsLastGenerate(root)) _markResultStale(root);
    });
    _staleHandlerInstalled = true;
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
    // Clear any prior stale marker — a fresh render is by definition
    // not stale until the operator next edits the textarea.
    slot.dataset.stale = '';

    _currentDraft = payload;
}


// ─── Fetch — generate ────────────────────────────────────────────────
async function _submitGenerate() {
    const root = $('view-procedures-architect');
    if (!root) return;
    // Belt-and-suspenders — install the stale-detection listener on
    // every generate in case the view was mounted by a test path
    // that bypassed _wireProceduresView.
    _installStaleHandler(root);
    const docType = root.querySelector('[data-proc-doc-type]')?.value || '';
    const ctx = root.querySelector('[data-proc-context]')?.value?.trim() || '';
    const assetId = _resolveAssetId(root);
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
        '<div class="proc-empty">Pulling telemetry snapshot…</div>',
    );
    // Phase 3: pre-pull a curated telemetry snapshot so the Architect
    // grounds the document in current state. Failures here are
    // tolerated -- the Generate request still goes out without the
    // metadata block.
    const metadata = await _fetchTelemetrySnapshot();
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
                metadata: Object.keys(metadata).length > 0 ? metadata : null,
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
        // Snapshot the context that produced this result so the
        // stale-detection listener can compare against subsequent edits.
        _lastGeneratedContext = ctx;
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
    if (draft.draft_id !== draftId) return;   // staleness guard (race)

    const slot = root.querySelector(
        `.proc-sign-result[data-draft-id="${CSS.escape(draftId)}"]`,
    );
    if (!slot) return;
    // Phase 2 staleness gate: refuse to sign when the textarea has
    // drifted since the last generate. The server re-audits on /sign
    // and would also refuse a hard_stop, but this client-side block
    // is the safety-critical UX layer — the operator never even sees
    // a "sign in flight" spinner on stale content.
    if (_isStaleVsLastGenerate(root)) {
        slot.innerHTML = sanitizeHTML(
            '<div class="proc-sign-fail">Refusing to sign — context '
            + 'has been edited since this draft was generated. Click '
            + 'Generate again to re-evaluate.</div>',
        );
        return;
    }
    slot.innerHTML = sanitizeHTML(
        '<div class="proc-empty">Signing…</div>',
    );
    // Read the operator_id from the input the form exposes. Default
    // to 'wilmer.angel' when the input is missing (test paths that
    // mount a partial skeleton) so existing behaviour is back-compat.
    const opInput = root.querySelector('[data-proc-operator-id]');
    const operatorId = (opInput?.value || 'wilmer.angel').trim() || 'wilmer.angel';
    try {
        const resp = await fetch('/api/procedures/architect/sign', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                draft_id: draft.draft_id,
                doc_type: draft.doc_type,
                content: draft.content,
                asset_id: draft.asset_id || null,
                operator_id: operatorId,
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
        // Epic 6 Sprint 3 Phase 4 wire-level: the MOP Maker-Checker
        // backend returns HTTP 202 + ``status: awaiting_second_signature``
        // on the first MOP sign. Render an unmistakable badge + the
        // maker's name + the content sha so the next operator (the
        // checker) has the proof-of-context they need to corroborate.
        if (data.status === 'awaiting_second_signature') {
            const maker = escapeHTML(String(data.first_signer || 'unknown'));
            const makerRole = escapeHTML(
                String(data.first_signer_role || 'operator'),
            );
            const sha = escapeHTML(
                String(data.content_sha256 || '').slice(0, 16),
            );
            slot.innerHTML = sanitizeHTML(
                '<div class="proc-sign-awaiting">'
                + '<span class="proc-sign-awaiting-badge">'
                + 'AWAITING SECOND SIGNATURE</span>'
                + ` Maker: <code>${maker}</code>`
                + ` (${makerRole}) ·`
                + ` sha256 <code>${sha}…</code>`
                + '<div class="proc-sign-awaiting-hint">'
                + 'Tier IV Maker-Checker (CSA Z462-24 + Uptime '
                + 'Institute): a MOP requires two distinct operators. '
                + 'Change the <strong>Operator id</strong> above to a '
                + 'different name and click <strong>Sign</strong> again '
                + 'to seal the ledger entry. The same operator cannot '
                + 'witness their own draft.'
                + '</div>'
                + '</div>',
            );
            return;
        }
        const entry = escapeHTML(String(data.entry_id || '').slice(0, 16));
        const seq = escapeHTML(String(data.sequence_no || '?'));
        const sha = escapeHTML(String(data.content_sha256 || '').slice(0, 16));
        // Sealed-by-witness path carries both signers in the response.
        const witnessLine = (data.witness_required && data.first_signer)
            ? `<div class="proc-sign-witness-line">Maker: `
                + `<code>${escapeHTML(String(data.first_signer))}</code> · `
                + `Checker: <code>${escapeHTML(String(data.second_signer || operatorId))}</code></div>`
            : '';
        slot.innerHTML = sanitizeHTML(
            `<div class="proc-sign-ok">
                Signed to ledger ·
                entry <code>${entry}</code> ·
                seq #${seq} ·
                sha256 <code>${sha}…</code>
            </div>`
            + witnessLine,
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
        case 'ctx-fill': {
            // Chip click: pre-fill the textarea with the template and
            // substitute the currently-selected asset_id.
            const root = $('view-procedures-architect');
            if (root) _applyContextTemplate(root, t.dataset.ctxText);
            break;
        }
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
                <select data-proc-asset-select class="proc-select">
                    ${_renderAssetSelect()}
                </select>
            </label>
            <label data-proc-asset-custom-wrap hidden>
                Custom asset id:
                <input type="text" data-proc-asset-custom class="proc-input"
                       placeholder="any canonical_id (e.g. genset_a, bess_1)">
            </label>
            <label>
                Operator context:
                <div data-proc-ctx-chips class="proc-chips-row"></div>
                <textarea data-proc-context class="proc-textarea" rows="4"
                          placeholder="Describe the maintenance / operation / incident the document must cover. Example: Replace UPS-B battery cabinet on Phase 1 main bus during scheduled window."></textarea>
            </label>
            <label>
                Operator id (used at sign time — change to a DIFFERENT
                name for MOP Maker-Checker witness):
                <input type="text" data-proc-operator-id class="proc-input"
                       value="wilmer.angel"
                       placeholder="signing operator id">
            </label>
            <button data-action="generate" class="proc-btn proc-btn-generate">
                Generate
            </button>
        </div>
        <div data-proc-result class="proc-result"></div>
    `;
    // Initial chip render for the default doc_type (SOP).
    _renderContextChips(root);
    // Phase 2: textarea input listener — clears verdict + hides Sign
    // when the operator edits after a generate.
    _installStaleHandler(root);
    root.addEventListener('click', _onClick);
    // Re-render chips when doc_type changes; sync custom-asset
    // visibility when the asset picker changes. Both are 'change'
    // events (not 'click') so they need dedicated listeners.
    root.querySelector('[data-proc-doc-type]')?.addEventListener(
        'change', () => _renderContextChips(root),
    );
    root.querySelector('[data-proc-asset-select]')?.addEventListener(
        'change', () => _syncCustomAssetVisibility(root),
    );
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
    renderAssetSelect: _renderAssetSelect,
    resolveAssetId: _resolveAssetId,
    syncCustomAssetVisibility: _syncCustomAssetVisibility,
    renderContextChips: _renderContextChips,
    applyContextTemplate: _applyContextTemplate,
    installStaleHandler: _installStaleHandler,
    isStaleVsLastGenerate: _isStaleVsLastGenerate,
    markResultStale: _markResultStale,
    fetchTelemetrySnapshot: _fetchTelemetrySnapshot,
    TELEMETRY_METADATA_KEYS: _TELEMETRY_METADATA_KEYS,
    initProceduresView,
    reset: () => {
        _routeRegistered = false;
        _viewWired = false;
        _currentDraft = null;
        _lastGeneratedContext = null;
        _staleHandlerInstalled = false;
    },
    DOC_TYPES,
    ASSET_PRESETS,
    ASSET_CUSTOM_VALUE,
    ASSET_NONE_VALUE,
    CONTEXT_TEMPLATES,
};
