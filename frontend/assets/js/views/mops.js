/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/mops.js
 * ROADMAP V11 T2.1 — MOPs/SOPs/EOPs library extracted from app.js.
 *
 * Behaviour-preserving migration of the procedure-library view out of
 * the monolithic app.js IIFE: a corpus-indexed list of MOP/SOP/EOP
 * procedures, a step-by-step execution checklist with timestamps, and
 * an AI generator that drafts a new procedure via /api/mops/generate.
 *
 * Integration (mirrors views/scenarios.js + views/incidents.js):
 *   - registerRoute('mops', …) hands navigation to core/router.js (the
 *     T2.2 declarative registry); the IIFE no longer renders this view.
 *   - HTTP goes through services/api.js (getMops / getMop / generateMop).
 *   - HTML escaping uses the shared core/sanitize.js escapeHTML.
 *   - EDA: subscribes to `hermes:cmms-alert` — when CMMS activity lands
 *     and this view is on screen, the library cache is invalidated and
 *     re-rendered. (A light coupling: the procedure corpus rarely moves,
 *     but the hook keeps the view consistent with the EDA plane.)
 *
 * State (was IIFE-scoped in app.js) is now module-scoped: the fetched
 * library cache plus per-procedure checklist progress + timestamps.
 *
 * Test surface: __mops_test__ exposes the pure render/markdown helpers.
 * ════════════════════════════════════════════════════════════════ */

import { registerRoute } from '../core/router.js';
import { escapeHTML as _escape } from '../core/sanitize.js';
import { getMops, getMop, generateMop } from '../services/api.js';

// ─── Module state ──────────────────────────────────────────────────
let _initialized = false;
let _mopsCache = null;            // array of MOP summaries — fetched once
const _mopChecks = {};            // doc_id -> Set of completed step_nums
const _mopTimestamps = {};        // doc_id -> { step_num: timestamp }

// ─── Minimal markdown renderer (escape-first, then bold/code/italic) ─
function _markdownLite(s) {
    if (!s) return '';
    let h = _escape(s);
    h = h.replace(/`([^`]+)`/g, '<code>$1</code>');
    h = h.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    h = h.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    h = h.replace(/\n/g, '<br>');
    return h;
}

function _docTypeOptions() {
    return 'MOP / SOP / EOP';
}

// ─── Pure presentation helpers (the __mops_test__ surface) ─────────
function _mopCardHtml(m) {
    const typeBadge = m.doc_type === 'EOP'
        ? '<span class="mop-type sev-critical">EOP</span>'
        : '<span class="mop-type">' + _escape(m.doc_type) + '</span>';
    const standardsHtml = (m.standard_refs || []).slice(0, 2).map(s =>
        `<span class="mop-std">${_escape(s)}</span>`
    ).join('');
    return `<div class="mop-card" data-id="${_escape(m.doc_id)}">
        <div class="mop-card-hdr">
            ${typeBadge}
            <span class="mop-id">${_escape(m.doc_id)}</span>
        </div>
        <div class="mop-name">${_escape(m.title)}</div>
        <div class="mop-meta">
            ${_escape(m.equipment || '')}
            ${m.duration ? '<span>· ' + _escape(m.duration) + '</span>' : ''}
        </div>
        ${standardsHtml ? '<div class="mop-stds">' + standardsHtml + '</div>' : ''}
    </div>`;
}

// ─── List render ───────────────────────────────────────────────────
async function _renderList() {
    const listEl = document.getElementById('mops-list');
    const metaEl = document.getElementById('mops-meta');
    if (!listEl) return;

    if (!_mopsCache) {
        try {
            const d = await getMops();
            _mopsCache = d.mops || [];
            if (metaEl) {
                const types = d.by_type || {};
                metaEl.textContent = `${d.count} procedures indexed: `
                    + Object.entries(types).map(([k, v]) => `${v} ${k}`).join(', ');
            }
        } catch (e) {
            listEl.innerHTML =
                `<div class="mops-empty" style="color:var(--crit)">Failed to load: ${_escape(e.message)}</div>`;
            return;
        }
    }

    if (_mopsCache.length === 0) {
        listEl.innerHTML = '<div class="mops-empty">No procedures found.</div>';
        return;
    }

    listEl.innerHTML = _mopsCache.map(_mopCardHtml).join('');
    listEl.querySelectorAll('.mop-card').forEach(card => {
        card.addEventListener('click', () => {
            listEl.querySelectorAll('.mop-card').forEach(c => c.classList.remove('active'));
            card.classList.add('active');
            _showDetail(card.dataset.id);
        });
    });
}

// ─── Detail render + step-checklist ────────────────────────────────
async function _showDetail(docId) {
    const detailEl = document.getElementById('mops-detail');
    if (!detailEl) return;
    detailEl.innerHTML = '<div class="mops-loading"><span class="loading"></span>Loading procedure…</div>';
    try {
        const d = await getMop(docId);
        _renderMopContent(detailEl, d);
    } catch (e) {
        detailEl.innerHTML =
            `<div class="mops-empty" style="color:var(--crit)">Error: ${_escape(e.message)}</div>`;
    }
}

function _renderMopContent(el, d) {
    const meta = d.metadata || {};
    const steps = d.steps || [];
    const docId = d.doc_id;

    if (!_mopChecks[docId]) _mopChecks[docId] = new Set();
    if (!_mopTimestamps[docId]) _mopTimestamps[docId] = {};

    const completed = _mopChecks[docId].size;
    const total = steps.length;
    const pct = total > 0 ? Math.round(completed / total * 100) : 0;

    const standardsList = (meta.standard_refs || []).map(s =>
        `<span class="mop-std-chip">${_escape(s)}</span>`
    ).join('');

    const stepsHtml = steps.length === 0
        ? '<div class="mop-no-steps">This procedure does not have explicit steps. View raw markdown below.</div>'
        : steps.map(s => {
            const isChecked = _mopChecks[docId].has(s.step_num);
            const ts = _mopTimestamps[docId][s.step_num] || '';
            return `<div class="mop-step ${isChecked ? 'completed' : ''}" data-step="${s.step_num}">
                <div class="mop-step-hdr">
                    <input type="checkbox" class="mop-step-check" data-step="${s.step_num}" ${isChecked ? 'checked' : ''}>
                    <span class="mop-step-num">${s.step_num}</span>
                    <span class="mop-step-title">${_escape(s.title)}</span>
                    <span class="mop-step-ts">${_escape(ts)}</span>
                </div>
                <div class="mop-step-content">${_markdownLite(s.content)}</div>
            </div>`;
        }).join('');

    el.innerHTML = `
        <div class="mop-detail-hdr">
            <h3>${_escape(d.title || docId)}</h3>
            <div class="mop-detail-meta">
                <span class="mop-id-badge">${_escape(docId)}</span>
                <span class="mop-type ${meta.doc_type === 'EOP' ? 'sev-critical' : ''}">${_escape(meta.doc_type || 'MOP')}</span>
                ${meta.equipment ? '<span><strong>Equipment:</strong> ' + _escape(meta.equipment) + '</span>' : ''}
                ${meta.duration ? '<span><strong>Duration:</strong> ' + _escape(meta.duration) + '</span>' : ''}
                ${meta.personnel_required ? '<span><strong>Personnel:</strong> ' + _escape(meta.personnel_required) + '</span>' : ''}
            </div>
            ${standardsList ? '<div class="mop-stds-row"><span class="mop-section-lbl">Standards:</span> ' + standardsList + '</div>' : ''}
        </div>

        <div class="mop-progress-section">
            <div class="mop-progress-hdr">
                <span>Execution progress</span>
                <span class="mop-progress-counter">${completed} / ${total} steps</span>
            </div>
            <div class="mop-progress-bar">
                <div class="mop-progress-fill" style="width:${pct}%"></div>
            </div>
            <div class="mop-progress-actions">
                <button class="btn btn-secondary btn-sm" id="mop-reset">Reset checklist</button>
                <span class="mop-progress-note">Check items as you complete them. Timestamps recorded automatically.</span>
            </div>
        </div>

        <div class="mop-steps">
            ${stepsHtml}
        </div>

        <details class="mop-raw">
            <summary>View raw markdown</summary>
            <pre class="mop-raw-content">${_escape(d.body || '')}</pre>
        </details>
    `;

    el.querySelectorAll('.mop-step-check').forEach(cb => {
        cb.addEventListener('change', () => {
            const stepNum = parseInt(cb.dataset.step, 10);
            const stepEl = el.querySelector('[data-step="' + stepNum + '"]');
            if (cb.checked) {
                _mopChecks[docId].add(stepNum);
                _mopTimestamps[docId][stepNum] = new Date().toLocaleTimeString();
                if (stepEl) stepEl.classList.add('completed');
            } else {
                _mopChecks[docId].delete(stepNum);
                delete _mopTimestamps[docId][stepNum];
                if (stepEl) stepEl.classList.remove('completed');
            }
            const newCount = _mopChecks[docId].size;
            const newPct = total > 0 ? Math.round(newCount / total * 100) : 0;
            const counter = el.querySelector('.mop-progress-counter');
            const fill = el.querySelector('.mop-progress-fill');
            const tsEl = stepEl ? stepEl.querySelector('.mop-step-ts') : null;
            if (counter) counter.textContent = newCount + ' / ' + total + ' steps';
            if (fill) fill.style.width = newPct + '%';
            if (tsEl) tsEl.textContent = _mopTimestamps[docId][stepNum] || '';
        });
    });

    const resetBtn = el.querySelector('#mop-reset');
    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            _mopChecks[docId] = new Set();
            _mopTimestamps[docId] = {};
            _renderMopContent(el, d);
        });
    }
}

// ─── AI generator ──────────────────────────────────────────────────
function _showGenerator() {
    const detailEl = document.getElementById('mops-detail');
    if (!detailEl) return;
    detailEl.innerHTML = `
        <div class="mop-detail-hdr">
            <h3>🤖 Generate new procedure with AI</h3>
            <div class="mop-detail-meta">
                <span style="color:var(--text-muted)">The AI agent will draft a structured ${_docTypeOptions()} grounded in the corpus format.</span>
            </div>
        </div>

        <div class="mop-gen-form">
            <label class="mop-gen-lbl">Procedure type</label>
            <select id="mop-gen-type" class="mop-gen-input">
                <option value="MOP">MOP - Method of Procedure</option>
                <option value="SOP">SOP - Standard Operating Procedure</option>
                <option value="EOP">EOP - Emergency Operating Procedure</option>
            </select>

            <label class="mop-gen-lbl">Topic / Purpose</label>
            <input type="text" id="mop-gen-topic" class="mop-gen-input"
                placeholder="e.g. CRAH fan filter inspection and replacement"
                value="">

            <label class="mop-gen-lbl">Target equipment</label>
            <input type="text" id="mop-gen-equipment" class="mop-gen-input"
                placeholder="e.g. Liebert CRV CRAH unit, 30-ton">

            <label class="mop-gen-lbl">Estimated duration</label>
            <input type="text" id="mop-gen-duration" class="mop-gen-input"
                placeholder="e.g. 2 hours per unit">

            <div class="mop-gen-actions">
                <button class="btn" id="mop-gen-go">Generate with AI</button>
                <button class="btn btn-secondary" id="mop-gen-cancel">Cancel</button>
            </div>

            <div id="mop-gen-result" class="mop-gen-result"></div>
        </div>
    `;

    const goBtn = document.getElementById('mop-gen-go');
    const cancelBtn = document.getElementById('mop-gen-cancel');
    if (cancelBtn) {
        cancelBtn.addEventListener('click', () => {
            detailEl.innerHTML = '<div class="mops-empty"><div style="font-size:32px;margin-bottom:10px">📋</div>Select a procedure on the left.</div>';
        });
    }
    if (goBtn) goBtn.addEventListener('click', _doGenerate);
}

async function _doGenerate() {
    const topic = document.getElementById('mop-gen-topic').value.trim();
    const docType = document.getElementById('mop-gen-type').value;
    const equipment = document.getElementById('mop-gen-equipment').value.trim();
    const duration = document.getElementById('mop-gen-duration').value.trim();
    const resultEl = document.getElementById('mop-gen-result');
    const btn = document.getElementById('mop-gen-go');

    if (!topic) {
        alert('Please enter a topic for the procedure.');
        return;
    }
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="loading"></span>Generating (this can take 30-60s)…';
    }
    resultEl.innerHTML = '<div class="scenario-running">AI is drafting the procedure with the corpus as a template…</div>';

    try {
        const d = await generateMop({
            topic,
            doc_type: docType,
            equipment: equipment || 'Not specified',
            duration: duration || 'TBD',
        });
        _renderGeneratedMop(resultEl, d);
    } catch (e) {
        resultEl.innerHTML =
            `<div style="color:var(--crit);padding:14px">Generation failed: ${_escape(e.message)}</div>`;
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = 'Generate with AI';
        }
    }
}

function _renderGeneratedMop(el, d) {
    const steps = d.steps || [];
    const stepsHtml = steps.length === 0
        ? '<div class="mop-no-steps">No explicit steps were extracted. See raw markdown.</div>'
        : steps.map(s => `<div class="mop-step">
            <div class="mop-step-hdr">
                <span class="mop-step-num">${s.step_num}</span>
                <span class="mop-step-title">${_escape(s.title)}</span>
            </div>
            <div class="mop-step-content">${_markdownLite(s.content)}</div>
        </div>`).join('');

    el.innerHTML = `
        <div class="mop-gen-output-hdr">
            <h4>✓ Generated procedure</h4>
            <div class="mop-detail-meta">
                <span>Topic: <strong>${_escape(d.topic)}</strong></span>
                <span>Type: <strong>${_escape(d.doc_type)}</strong></span>
                <span>${_escape(String(steps.length))} steps extracted</span>
            </div>
        </div>

        <div class="mop-steps">
            ${stepsHtml}
        </div>

        <details class="mop-raw" open>
            <summary>View raw generated markdown (you can copy/save this)</summary>
            <pre class="mop-raw-content">${_escape(d.raw_markdown || '')}</pre>
            <button class="btn btn-secondary btn-sm" id="mop-gen-copy">Copy markdown to clipboard</button>
        </details>
    `;

    const copyBtn = document.getElementById('mop-gen-copy');
    if (copyBtn) {
        copyBtn.addEventListener('click', async () => {
            try {
                await navigator.clipboard.writeText(d.raw_markdown || '');
                copyBtn.textContent = '✓ Copied';
                setTimeout(() => { copyBtn.textContent = 'Copy markdown to clipboard'; }, 2000);
            } catch (_e) {
                copyBtn.textContent = 'Copy failed';
            }
        });
    }
}

// ─── EDA — refresh on the Hermes cmms_alerts plane ─────────────────
function _onCmmsAlert() {
    const view = document.getElementById('view-mops');
    if (view && !view.hasAttribute('hidden')) {
        _mopsCache = null;       // invalidate — re-fetch on next render
        _renderList();
    }
}

// ─── Routing + lifecycle ───────────────────────────────────────────
function _activate() {
    _renderList();
}

/** Public entry — called once from main.js at bootstrap. */
export function initMopsView() {
    if (_initialized) return;
    if (!document.getElementById('view-mops')) {
        console.warn('[mops] #view-mops not in DOM; view disabled.');
        return;
    }
    registerRoute('mops', { viewId: 'view-mops', activate: _activate });

    const genBtn = document.getElementById('btn-mop-generate');
    if (genBtn) genBtn.addEventListener('click', _showGenerator);

    document.addEventListener('hermes:cmms-alert', _onCmmsAlert);

    _initialized = true;
    console.log('[mops] view ready (MOP/SOP/EOP library — T2.1 ES module)');
}

// ─── Test surface ──────────────────────────────────────────────────
export const __mops_test__ = {
    escape: _escape,
    markdownLite: _markdownLite,
    mopCardHtml: _mopCardHtml,
    renderList: _renderList,
    reset: () => {
        _initialized = false;
        _mopsCache = null;
        for (const k of Object.keys(_mopChecks)) delete _mopChecks[k];
        for (const k of Object.keys(_mopTimestamps)) delete _mopTimestamps[k];
    },
};
