/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/tech_assist.js
 *
 * Sprint 7.1 frontend: Field assistance + asset onboarding surface.
 *
 * Renders the Tech Assist view, backed by /api/tech-assist/*:
 *   - Top-left  : Nameplate OCR  (Sprint 7.1d) -> POST /nameplate/extract
 *   - Top-right : Troubleshoot QA (Sprint 7.1a) -> POST /troubleshoot
 *   - Bottom    : Knowledge Library (Sprint 7.1b) -> GET /documents,
 *                                                    POST /ingest-pdf,
 *                                                    DELETE /documents/{id}
 *
 * No polling — every panel is event-driven on user action. Library
 * refreshes on view-show, on Upload completion, and on explicit click.
 *
 * Routing: nav-item click delegation following the LOTO pattern. The
 * legacy IIFE router in app.js does not have a `tech-assist` branch,
 * so we self-route after a setTimeout(0) to override its decision.
 *
 * ADR-006 compliance: every panel surfaces *suggestions*. Linking an
 * asset, drafting a WO, or deleting a doc are operator-driven gestures.
 * Style: instrument-grade, mirrors Maintenance + Activity Strip.
 * ════════════════════════════════════════════════════════════════ */

import { registerRoute } from '../core/router.js';
import { trapFocus } from '../core/focus_trap.js';
import { sanitizeHTML } from '../core/sanitize.js';

const API_BASE = '';

const SAMPLE_NAMEPLATE = `SCHNEIDER ELECTRIC GALAXY VX UPS
Model: GVX750-N480
Serial: SVX-2024-008812
Rated 750 kVA / 675 kW
Voltage: 480 VAC, 60 Hz
Battery 24 V
MFG 2024-03`;

let _container = null;
let _initialized = false;

// Sprint 7.1d-followup: cache of the last extracted_fields so the
// enrich modal can pre-fill without re-running the regex.
let _lastExtractedFields = {};
let _libraryLoaded = false;

// ─── HTML escape helper (XSS-safe rendering) ──────────────────────
function _escape(s) {
    if (s === null || s === undefined) return '';
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function _fmtNum(v, digits = 2) {
    if (v === null || v === undefined) return '—';
    if (typeof v !== 'number') return String(v);
    return v.toFixed(digits);
}

function _fmtDateShort(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return _escape(iso);
    return d.toISOString().slice(0, 16).replace('T', ' ') + 'Z';
}

// ════════════════════════════════════════════════════════════════
//  Panel 1: Nameplate OCR
// ════════════════════════════════════════════════════════════════
async function _onNameplateExtract() {
    const ta = document.getElementById('ta-nameplate-text');
    const hintEl = document.getElementById('ta-nameplate-hint');
    const meta = document.getElementById('ta-nameplate-meta');
    const result = document.getElementById('ta-nameplate-result');
    const btn = document.getElementById('ta-nameplate-extract');
    if (!ta || !btn) return;

    const text = (ta.value || '').trim();
    if (text.length < 5) {
        result.innerHTML = `<div class="ta-empty ta-error">OCR text too short (need at least 5 characters).</div>`;
        return;
    }

    const body = { ocr_text: text };
    const hint = (hintEl?.value || '').trim();
    if (hint) body.asset_type_hint = hint;

    btn.disabled = true;
    meta.textContent = 'extracting…';
    result.innerHTML = `<div class="ta-empty">Working…</div>`;

    try {
        const resp = await fetch(`${API_BASE}/api/tech-assist/nameplate/extract`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!resp.ok) {
            const err = await resp.text().catch(() => `${resp.status}`);
            result.innerHTML = `<div class="ta-empty ta-error">HTTP ${resp.status}: ${_escape(err.slice(0, 300))}</div>`;
            meta.textContent = `error ${resp.status}`;
            return;
        }
        const data = await resp.json();
        meta.textContent = `${data.elapsed_ms} ms · ${data.extracted_fields.extraction_method}`;
        _renderNameplateResult(result, data);
    } catch (e) {
        result.innerHTML = `<div class="ta-empty ta-error">Network error: ${_escape(e.message)}</div>`;
        meta.textContent = 'error';
    } finally {
        btn.disabled = false;
    }
}

function _renderNameplateResult(container, data) {
    const f = data.extracted_fields || {};
    const cands = data.candidates || [];
    const action = data.suggested_action || {};

    const fieldRow = (label, value) => `
        <div class="ta-np-field">
            <span class="ta-np-field-label">${_escape(label)}</span>
            <span class="ta-np-field-value">${_escape(value === null || value === undefined || value === '' ? '—' : value)}</span>
        </div>`;

    const cap = f.rated_capacity_value !== null && f.rated_capacity_value !== undefined
        ? `${_fmtNum(f.rated_capacity_value, 1)} ${_escape(f.rated_capacity_unit || '')}`
        : '—';

    const confColor = f.extraction_confidence >= 0.8 ? 'good'
                    : f.extraction_confidence >= 0.4 ? 'warn'
                    : 'crit';
    const methodPill = `<span class="ta-pill ta-pill-${f.extraction_method === 'regex' ? 'good' : 'info'}">${_escape(f.extraction_method)}</span>`;
    const confPill   = `<span class="ta-pill ta-pill-${confColor}">conf ${_fmtNum(f.extraction_confidence, 2)}</span>`;

    const fieldsHTML = `
        <div class="ta-np-section-title">Extracted fields ${methodPill} ${confPill}</div>
        <div class="ta-np-fields">
            ${fieldRow('vendor',        f.vendor)}
            ${fieldRow('model',         f.model)}
            ${fieldRow('serial',        f.serial)}
            ${fieldRow('rated capacity', cap)}
            ${fieldRow('voltage',       f.voltage_nominal_v ? `${f.voltage_nominal_v} V` : null)}
            ${fieldRow('frequency',     f.frequency_hz ? `${f.frequency_hz} Hz` : null)}
            ${fieldRow('mfg date',      f.manufacture_date)}
        </div>`;

    let candidatesHTML;
    if (cands.length === 0) {
        candidatesHTML = `
            <div class="ta-np-section-title">Candidates (0)</div>
            <div class="ta-empty">No assets in the registry matched.</div>`;
    } else {
        candidatesHTML = `
            <div class="ta-np-section-title">Candidates (${cands.length})</div>
            <div class="ta-np-candidates">
                ${cands.map(c => {
                    const scoreCls = c.score >= 0.80 ? 'good'
                                  : c.score >= 0.60 ? 'warn'
                                  : 'dim';
                    const reasons = (c.match_reasons || []).map(r =>
                        `<span class="ta-reason">${_escape(r)}</span>`,
                    ).join('');
                    const summary = c.asset_summary || {};
                    return `
                        <div class="ta-np-cand">
                            <div class="ta-np-cand-row">
                                <span class="ta-np-cand-id">${_escape(c.asset_id)}</span>
                                <span class="ta-np-score ta-np-score-${scoreCls}">${_fmtNum(c.score, 2)}</span>
                            </div>
                            <div class="ta-np-cand-name">${_escape(summary.display_name || '')}</div>
                            <div class="ta-np-cand-reasons">${reasons || '<span class="ta-reason ta-reason-dim">no reasons</span>'}</div>
                        </div>`;
                }).join('')}
            </div>`;
    }

    let actionCls = 'info';
    if (action.action === 'link_to_existing') actionCls = 'good';
    else if (action.action === 'operator_confirm') actionCls = 'warn';
    else if (action.action === 'seed_new_asset') actionCls = 'dim';

    // Sprint 7.1d-followup: when seed_new_asset, offer to enrich an
    // existing asset with the extracted fields rather than create a
    // brand-new row. This closes the matcher loop end-to-end.
    const enrichBtn = action.action === 'seed_new_asset'
        ? `<button class="ta-enrich-link-action" id="ta-np-enrich-link" type="button">Enrich existing asset…</button>`
        : '';

    const actionHTML = `
        <div class="ta-np-action ta-np-action-${actionCls}">
            <div class="ta-np-action-title">Suggested action: ${_escape(action.action || '—')}</div>
            <div class="ta-np-action-rationale">${_escape(action.rationale || '')}</div>
            ${action.asset_id ? `<div class="ta-np-action-asset">→ <code>${_escape(action.asset_id)}</code></div>` : ''}
            ${enrichBtn}
        </div>`;

    container.innerHTML = fieldsHTML + candidatesHTML + actionHTML;

    // Cache the extracted fields so the enrich modal can pre-fill from
    // the most recent extraction without re-fetching.
    _lastExtractedFields = data.extracted_fields || {};

    // Wire the enrich button (created above)
    document.getElementById('ta-np-enrich-link')?.addEventListener('click', _openEnrichModal);
}

function _onNameplateLoadSample() {
    const ta = document.getElementById('ta-nameplate-text');
    const hintEl = document.getElementById('ta-nameplate-hint');
    if (ta) ta.value = SAMPLE_NAMEPLATE;
    if (hintEl) hintEl.value = 'ups';
}

// ════════════════════════════════════════════════════════════════
//  Panel 2: Troubleshoot QA
// ════════════════════════════════════════════════════════════════
async function _onTroubleshootAsk() {
    const qEl = document.getElementById('ta-troubleshoot-query');
    const aEl = document.getElementById('ta-troubleshoot-asset');
    const eEl = document.getElementById('ta-troubleshoot-error');
    const meta = document.getElementById('ta-troubleshoot-meta');
    const result = document.getElementById('ta-troubleshoot-result');
    const btn = document.getElementById('ta-troubleshoot-ask');
    if (!qEl || !btn) return;

    const query = (qEl.value || '').trim();
    if (query.length < 3) {
        result.innerHTML = `<div class="ta-empty ta-error">Question too short (need at least 3 characters).</div>`;
        return;
    }

    const body = { query, k_chunks: 4, history_months: 12, use_llm: true };
    const aid = (aEl?.value || '').trim();
    const err = (eEl?.value || '').trim();
    if (aid) body.asset_id = aid;
    if (err) body.error_code = err;

    btn.disabled = true;
    meta.textContent = 'thinking…';
    result.innerHTML = `<div class="ta-empty">Retrieving corpus chunks + WO history + invoking gemma. Typically 2–6 seconds…</div>`;

    try {
        const resp = await fetch(`${API_BASE}/api/tech-assist/troubleshoot`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!resp.ok) {
            const errBody = await resp.text().catch(() => `${resp.status}`);
            result.innerHTML = `<div class="ta-empty ta-error">HTTP ${resp.status}: ${_escape(errBody.slice(0, 300))}</div>`;
            meta.textContent = `error ${resp.status}`;
            return;
        }
        const data = await resp.json();
        meta.textContent = `${data.decision_time_ms} ms · ${data.llm_synthesis_status}`;
        _renderTroubleshootResult(result, data);
    } catch (e) {
        result.innerHTML = `<div class="ta-empty ta-error">Network error: ${_escape(e.message)}</div>`;
        meta.textContent = 'error';
    } finally {
        btn.disabled = false;
    }
}

function _renderTroubleshootResult(container, data) {
    const chunks = data.chunks_retrieved || [];
    const wos = data.historical_wos || [];
    const safety = data.safety_keywords_detected || [];

    const safetyBanner = safety.length
        ? `<div class="ta-ts-safety">⚠ Safety keywords: ${safety.map(_escape).join(', ')}</div>`
        : '';

    // F3-5: final-stage XSS gate on AI-authored output. _renderInlineMarkdown
    // escapes per line today, but routing the rendered LLM HTML through the
    // audited allowlist sanitiser makes that guarantee explicit and immune to
    // a future markdown transform (link/image support) silently reopening it.
    const llmHTML = data.llm_answer
        ? `<div class="ta-ts-answer">${sanitizeHTML(_renderInlineMarkdown(data.llm_answer))}</div>`
        : `<div class="ta-empty">LLM synthesis status: ${_escape(data.llm_synthesis_status)}${data.llm_model ? ` (${_escape(data.llm_model)})` : ''}</div>`;

    const tierLabel = (t) => {
        const m = { 1: 'SAFETY', 2: 'VENDOR', 3: 'STANDARD', 4: 'MOP' };
        return m[t] || `T${t}`;
    };

    const chunksHTML = chunks.length
        ? `<div class="ta-ts-section-title">Sources consulted (${chunks.length})</div>
           <div class="ta-ts-chunks">
                ${chunks.map(c => `
                    <div class="ta-ts-chunk">
                        <span class="ta-pill ta-pill-tier ta-pill-tier-${c.tier}">tier-${c.tier} ${_escape(tierLabel(c.tier))}</span>
                        <span class="ta-ts-chunk-id">${_escape(c.doc_id)}</span>
                        <span class="ta-ts-chunk-score">score ${_fmtNum(c.score, 3)}</span>
                        <div class="ta-ts-chunk-excerpt">${_escape((c.text_excerpt || '').slice(0, 240))}${c.text_excerpt && c.text_excerpt.length > 240 ? '…' : ''}</div>
                    </div>`).join('')}
           </div>`
        : `<div class="ta-ts-section-title">Sources consulted (0)</div>
           <div class="ta-empty">No corpus matches retrieved.</div>`;

    const wosHTML = wos.length
        ? `<div class="ta-ts-section-title">Asset history (${data.history_count})</div>
           <div class="ta-ts-wos">
                ${wos.map(w => `
                    <div class="ta-ts-wo">
                        <span class="ta-ts-wo-id">${_escape(w.work_order_id)}</span>
                        <span class="ta-pill ta-pill-info">${_escape(w.priority)}</span>
                        <span class="ta-pill ta-pill-${w.status === 'completed' ? 'good' : 'dim'}">${_escape(w.status)}</span>
                        <span class="ta-ts-wo-cls">${_escape(w.work_class)}</span>
                        <span class="ta-ts-wo-summary">${_escape(w.issue_summary)}</span>
                    </div>`).join('')}
           </div>`
        : (data.asset_id
            ? `<div class="ta-ts-section-title">Asset history (0)</div>
               <div class="ta-empty">No prior WOs in the lookback window for ${_escape(data.asset_id)}.</div>`
            : '');

    container.innerHTML = safetyBanner + llmHTML + chunksHTML + wosHTML;
}

// Minimal Markdown -> HTML for the LLM answer. Headings, bold,
// inline code, line breaks, bullet lists. Anything else passes
// through escaped. No external lib needed.
function _renderInlineMarkdown(text) {
    const lines = String(text).split(/\r?\n/);
    const out = [];
    let inList = false;
    for (const raw of lines) {
        const line = raw.trimEnd();
        if (/^\s*$/.test(line)) {
            if (inList) { out.push('</ul>'); inList = false; }
            out.push('<br>');
            continue;
        }
        const h = /^(#{1,3})\s+(.*)$/.exec(line);
        if (h) {
            if (inList) { out.push('</ul>'); inList = false; }
            const lvl = h[1].length + 2;  // h3..h5
            out.push(`<h${lvl}>${_inlineFmt(h[2])}</h${lvl}>`);
            continue;
        }
        const li = /^\s*[-*]\s+(.*)$/.exec(line);
        if (li) {
            if (!inList) { out.push('<ul>'); inList = true; }
            out.push(`<li>${_inlineFmt(li[1])}</li>`);
            continue;
        }
        if (inList) { out.push('</ul>'); inList = false; }
        out.push(`<p>${_inlineFmt(line)}</p>`);
    }
    if (inList) out.push('</ul>');
    return out.join('');
}

function _inlineFmt(s) {
    let html = _escape(s);
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    return html;
}

// ════════════════════════════════════════════════════════════════
//  Panel 3: Knowledge Library
// ════════════════════════════════════════════════════════════════
async function _refreshLibrary() {
    const tbody = document.getElementById('ta-library-tbody');
    const countEl = document.getElementById('ta-library-count');
    if (!tbody) return;

    try {
        const resp = await fetch(`${API_BASE}/api/tech-assist/documents`);
        if (!resp.ok) {
            tbody.innerHTML = `<tr><td colspan="9" class="ta-empty ta-error">HTTP ${resp.status}</td></tr>`;
            return;
        }
        const data = await resp.json();
        const docs = data.documents || [];
        if (countEl) countEl.textContent = `${data.count || 0} document(s)`;

        if (docs.length === 0) {
            tbody.innerHTML = `<tr><td colspan="9" class="ta-empty">No PDFs ingested yet. Upload one to enrich the corpus.</td></tr>`;
            _libraryLoaded = true;
            return;
        }
        tbody.innerHTML = docs.map(d => {
            const tier = Number(d.tier) || 4;
            return `<tr>
                <td class="ta-mono"><span class="ta-doc-id" title="${_escape(d.document_id)}">${_escape((d.document_id || '').slice(0, 12))}…</span></td>
                <td>${_escape(d.title || d.original_filename || '—')}</td>
                <td><span class="ta-pill ta-pill-tier ta-pill-tier-${tier}">${tier}</span></td>
                <td>${_escape(d.priority || '—')}</td>
                <td>${_escape(d.asset_id || '—')}</td>
                <td>${_escape(d.vendor || '—')}</td>
                <td class="ta-mono ta-num">${_escape(String(d.chunk_count || 0))}</td>
                <td class="ta-mono">${_fmtDateShort(d.uploaded_at)}</td>
                <td>
                    <button class="btn btn-secondary ta-doc-delete" data-doc-id="${_escape(d.document_id)}" type="button" style="font-size:11px;padding:2px 8px;">Delete</button>
                </td>
            </tr>`;
        }).join('');
        _libraryLoaded = true;
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="9" class="ta-empty ta-error">Refresh failed: ${_escape(e.message)}</td></tr>`;
    }
}

async function _onDocDelete(docId) {
    if (!docId) return;
    const ok = confirm(`Delete document?\n\n  ${docId}\n\nAll associated chunks will be removed from the corpus. This cannot be undone.`);
    if (!ok) return;

    try {
        const resp = await fetch(`${API_BASE}/api/tech-assist/documents/${encodeURIComponent(docId)}`, {
            method: 'DELETE',
        });
        if (!resp.ok) {
            const err = await resp.text().catch(() => `${resp.status}`);
            alert(`Delete failed: ${err.slice(0, 200)}`);
            return;
        }
        await _refreshLibrary();
    } catch (e) {
        alert(`Delete error: ${e.message}`);
    }
}

async function _onUploadClick() {
    const fileInput = document.getElementById('ta-upload-file');
    if (fileInput) fileInput.click();
}

async function _onUploadFileChange(e) {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    const titleEl = document.getElementById('ta-upload-title');
    const tierEl = document.getElementById('ta-upload-tier');
    const prioEl = document.getElementById('ta-upload-priority');
    const assetEl = document.getElementById('ta-upload-asset');
    const vendorEl = document.getElementById('ta-upload-vendor');
    const status = document.getElementById('ta-upload-status');

    const fd = new FormData();
    fd.append('file', file);
    if (titleEl?.value)  fd.append('title',    titleEl.value.trim());
    if (tierEl?.value)   fd.append('tier',     tierEl.value);
    if (prioEl?.value)   fd.append('priority', prioEl.value);
    if (assetEl?.value)  fd.append('asset_id', assetEl.value.trim());
    if (vendorEl?.value) fd.append('vendor',   vendorEl.value.trim());

    if (status) status.innerHTML = `<span class="ta-upload-status-pending">Uploading ${_escape(file.name)} (${(file.size / 1024).toFixed(1)} KB)…</span>`;

    try {
        const resp = await fetch(`${API_BASE}/api/tech-assist/ingest-pdf`, { method: 'POST', body: fd });
        if (!resp.ok) {
            const err = await resp.text().catch(() => `${resp.status}`);
            if (status) status.innerHTML = `<span class="ta-upload-status-err">HTTP ${resp.status}: ${_escape(err.slice(0, 200))}</span>`;
            return;
        }
        const data = await resp.json();
        if (status) status.innerHTML = `<span class="ta-upload-status-ok">✓ ${_escape(data.document_id || file.name)} — ${data.chunk_count || data.chunks_added || 0} chunks indexed in ${data.elapsed_ms || '?'} ms</span>`;
        // Reset file input so re-uploading the same file fires change
        e.target.value = '';
        if (titleEl) titleEl.value = '';
        await _refreshLibrary();
    } catch (e) {
        if (status) status.innerHTML = `<span class="ta-upload-status-err">Upload failed: ${_escape(e.message)}</span>`;
    }
}

// ════════════════════════════════════════════════════════════════
//  Sprint 7.1d-followup: Asset Enrichment modal
// ════════════════════════════════════════════════════════════════
//
// Triggered from the suggested_action banner when a Nameplate extract
// returns seed_new_asset. Operator picks a target asset (filtered by
// asset_type_hint), reviews the fields pre-filled from the extraction,
// unchecks any they don't want to write, and submits. We PATCH
// /api/cmms/assets/{id} then auto-re-run Extract so the operator sees
// the same nameplate flip from seed_new_asset to link_to_existing.
//
// ADR-006 compliant: nothing auto-mutates without an explicit Save
// click; the asset_id selection is operator-driven.
//
const ENRICH_FIELD_DEFS = [
    { key: 'vendor',             label: 'vendor',     extractFrom: 'vendor',                type: 'text' },
    { key: 'model',              label: 'model',      extractFrom: 'model',                 type: 'text' },
    { key: 'serial',             label: 'serial',     extractFrom: 'serial',                type: 'text' },
    { key: 'rated_capacity_kw',  label: 'capacity (kW)', extractFrom: 'rated_capacity_value', type: 'number', step: '0.1', unitFrom: 'rated_capacity_unit' },
    { key: 'voltage_v',          label: 'voltage (V)', extractFrom: 'voltage_nominal_v',    type: 'number', step: '1' },
];

// T2.5 A11y-1 — focus-trap release handle for the enrich dialog.
let _enrichTrapRelease = null;

async function _openEnrichModal() {
    const overlay = document.getElementById('ta-enrich-overlay');
    const ctxEl   = document.getElementById('ta-enrich-context');
    const selEl   = document.getElementById('ta-enrich-asset-id');
    const fieldsEl = document.getElementById('ta-enrich-fields');
    const cetEl   = document.getElementById('ta-enrich-cet');
    const formBody = document.getElementById('ta-enrich-form-body');
    const result  = document.getElementById('ta-enrich-result');
    if (!overlay || !ctxEl || !selEl) return;

    // Reset
    if (result) { result.innerHTML = ''; result.setAttribute('hidden', ''); }
    if (formBody) formBody.removeAttribute('hidden');

    const f = _lastExtractedFields || {};
    ctxEl.innerHTML = `Extracted: <strong>${_escape(f.vendor || '?')}</strong> &middot; <strong>${_escape(f.model || '?')}</strong> &middot; serial: ${_escape(f.serial || '—')}`;

    cetEl.value = sessionStorage.getItem('cmms_cet_id') || '';

    // Populate the asset_id dropdown filtered by asset_type_hint (if any)
    const hint = (document.getElementById('ta-nameplate-hint')?.value || '').trim();
    selEl.innerHTML = '<option value="">— loading assets —</option>';
    try {
        const params = new URLSearchParams({ limit: '500' });
        if (hint) params.set('asset_type', hint);
        const r = await fetch(`${API_BASE}/api/cmms/assets?${params}`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = await r.json();
        const opts = (data.assets || []).map(a =>
            `<option value="${_escape(a.asset_id)}">${_escape(a.asset_id)} &mdash; ${_escape(a.display_name || a.asset_type)}</option>`,
        ).join('');
        selEl.innerHTML = `<option value="">— pick an asset —</option>${opts}`;
    } catch (e) {
        selEl.innerHTML = `<option value="">— failed to load: ${_escape(e.message)} —</option>`;
    }

    // Render the field rows
    fieldsEl.innerHTML = ENRICH_FIELD_DEFS.map(def => {
        const raw = f[def.extractFrom];
        const hasValue = raw !== null && raw !== undefined && raw !== '';
        const checked = hasValue ? 'checked' : '';
        const value = hasValue ? String(raw) : '';
        const unitNote = def.unitFrom && f[def.unitFrom]
            ? ` <span style="color:var(--text-dim);font-size:9.5px">(${_escape(f[def.unitFrom])})</span>`
            : '';
        return `
            <div class="ta-enrich-field-row">
                <input type="checkbox" id="ta-enrich-chk-${def.key}" data-key="${def.key}" ${checked}>
                <label for="ta-enrich-chk-${def.key}">${_escape(def.label)}${unitNote}</label>
                <input type="${def.type}" id="ta-enrich-val-${def.key}" data-key="${def.key}"
                       ${def.step ? `step="${def.step}"` : ''}
                       value="${_escape(value)}" ${checked ? '' : 'disabled'}>
            </div>`;
    }).join('');

    // Wire each checkbox to enable/disable its sibling input
    fieldsEl.querySelectorAll('input[type="checkbox"]').forEach(chk => {
        chk.addEventListener('change', () => {
            const key = chk.dataset.key;
            const valInput = document.getElementById(`ta-enrich-val-${key}`);
            if (valInput) valInput.disabled = !chk.checked;
        });
    });

    overlay.removeAttribute('hidden');
    // T2.5 A11y-1 (WCAG 2.4.3): trap Tab inside the dialog. This modal has
    // no prior Escape handler, so wire onEscape to close it.
    _enrichTrapRelease = trapFocus(document.getElementById('ta-enrich-modal'), { onEscape: _closeEnrichModal });
    setTimeout(() => selEl.focus(), 50);
}

function _closeEnrichModal() {
    const overlay = document.getElementById('ta-enrich-overlay');
    if (overlay) overlay.setAttribute('hidden', '');
    // T2.5 A11y-1 — release the focus trap + return focus to the trigger.
    if (_enrichTrapRelease) { _enrichTrapRelease(); _enrichTrapRelease = null; }
}

async function _submitEnrich() {
    const selEl   = document.getElementById('ta-enrich-asset-id');
    const fieldsEl = document.getElementById('ta-enrich-fields');
    const cetEl   = document.getElementById('ta-enrich-cet');
    const submit  = document.getElementById('ta-enrich-submit');
    const result  = document.getElementById('ta-enrich-result');
    const formBody = document.getElementById('ta-enrich-form-body');
    if (!selEl || !fieldsEl) return;

    const assetId = (selEl.value || '').trim();
    if (!assetId) { alert('Pick a target asset first.'); selEl.focus(); return; }

    // Build the body from checked fields with non-empty values
    const body = {};
    fieldsEl.querySelectorAll('input[type="checkbox"]').forEach(chk => {
        if (!chk.checked) return;
        const key = chk.dataset.key;
        const valEl = document.getElementById(`ta-enrich-val-${key}`);
        const raw = (valEl?.value || '').trim();
        if (!raw) return;
        if (key === 'rated_capacity_kw' || key === 'voltage_v') {
            const n = Number(raw);
            if (!Number.isNaN(n)) body[key] = n;
        } else {
            body[key] = raw;
        }
    });
    const cet = (cetEl?.value || '').trim();
    if (cet) {
        body.enriched_by = cet;
        sessionStorage.setItem('cmms_cet_id', cet);
    }
    if (Object.keys(body).length === 0) {
        alert('No fields selected. Check at least one field to write.');
        return;
    }

    submit.disabled = true;
    submit.textContent = 'saving…';
    if (result) {
        result.removeAttribute('hidden');
        result.innerHTML = `<div class="m-closure-status m-closure-status-pending">Writing fields to <code>${_escape(assetId)}</code> via PATCH /api/cmms/assets/&hellip;</div>`;
    }

    try {
        const r = await fetch(`${API_BASE}/api/cmms/assets/${encodeURIComponent(assetId)}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!r.ok) {
            const err = await r.text().catch(() => `${r.status}`);
            if (result) {
                result.innerHTML = `<div class="m-closure-status m-closure-status-err">HTTP ${r.status}: ${_escape(err.slice(0, 300))}</div>`;
            }
            return;
        }
        const data = await r.json();
        if (formBody) formBody.setAttribute('hidden', '');
        const fieldList = (data.fields_written || []).map(f =>
            `<span class="m-closure-chip">${_escape(f)}</span>`,
        ).join('');
        if (result) {
            result.innerHTML = `
                <div class="m-closure-status m-closure-status-ok">&#x2714; ${_escape(assetId)} enriched</div>
                <div class="m-closure-meta-row">
                    <span class="m-closure-meta">fields_written:</span>
                    ${fieldList}
                </div>
                <div class="m-modal-actions">
                    <button class="btn btn-secondary" id="ta-enrich-done-close" type="button">Close</button>
                    <button class="btn btn-primary" id="ta-enrich-rematch" type="button">Re-run Extract</button>
                </div>
            `;
            document.getElementById('ta-enrich-done-close')?.addEventListener('click', _closeEnrichModal);
            document.getElementById('ta-enrich-rematch')?.addEventListener('click', () => {
                _closeEnrichModal();
                _onNameplateExtract();   // forces a fresh extract -> matcher should now return link_to_existing
            });
        }
    } catch (e) {
        if (result) {
            result.innerHTML = `<div class="m-closure-status m-closure-status-err">Network error: ${_escape(e.message)}</div>`;
        }
    } finally {
        submit.disabled = false;
        submit.textContent = 'Save + re-match';
    }
}

function _wireEnrichModal() {
    document.getElementById('ta-enrich-cancel')?.addEventListener('click', _closeEnrichModal);
    document.getElementById('ta-enrich-cancel-2')?.addEventListener('click', _closeEnrichModal);
    document.getElementById('ta-enrich-submit')?.addEventListener('click', _submitEnrich);
    document.getElementById('ta-enrich-overlay')?.addEventListener('click', (e) => {
        if (e.target === e.currentTarget) _closeEnrichModal();
    });
    document.addEventListener('keydown', (e) => {
        const overlay = document.getElementById('ta-enrich-overlay');
        if (e.key === 'Escape' && overlay && !overlay.hasAttribute('hidden')) {
            _closeEnrichModal();
        }
    });
}


// ════════════════════════════════════════════════════════════════
//  Wiring + routing
// ════════════════════════════════════════════════════════════════
function _wireEvents() {
    document.getElementById('ta-nameplate-extract')?.addEventListener('click', _onNameplateExtract);
    document.getElementById('ta-nameplate-sample')?.addEventListener('click', _onNameplateLoadSample);
    document.getElementById('ta-troubleshoot-ask')?.addEventListener('click', _onTroubleshootAsk);
    document.getElementById('ta-library-refresh')?.addEventListener('click', _refreshLibrary);
    document.getElementById('ta-upload-btn')?.addEventListener('click', _onUploadClick);
    document.getElementById('ta-upload-file')?.addEventListener('change', _onUploadFileChange);

    // Delegated click handler for per-row delete
    const tbody = document.getElementById('ta-library-tbody');
    if (tbody) {
        tbody.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-doc-id]');
            if (btn) _onDocDelete(btn.dataset.docId);
        });
    }
}

// LOTO-pattern: legacy router has no `tech-assist` branch, so this
// handler runs after navigateTo and forces our view visible.
function _wireRouting() {
    // T2.2: declarative registry (replaces the setTimeout(0) LOTO race).
    registerRoute('tech-assist', {
        viewId: 'view-tech-assist',
        activate: () => {
            if (!_libraryLoaded) _refreshLibrary();
        },
    });
}

// ─── Public API ───────────────────────────────────────────────────
export function initTechAssistView() {
    _container = document.getElementById('view-tech-assist');
    if (!_container) {
        console.warn('[tech_assist] #view-tech-assist not in DOM; view disabled.');
        return;
    }
    if (_initialized) return;
    _wireEvents();
    _wireEnrichModal();
    _wireRouting();
    _initialized = true;
    console.log('[tech_assist] view ready (3 panels: nameplate / troubleshoot / library)');
}
