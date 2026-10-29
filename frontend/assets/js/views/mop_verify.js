/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/mop_verify.js
 * Shift Agentic Investigator (Meta hackathon) — MOP photo verification HMI.
 *
 * Three panels: procedure stepper (GET /api/copilot/mop/steps), photo
 * verification for the current step only (POST /api/copilot/mop/verify
 * multipart), and the result rendered ONLY from the API response.
 *
 * Contracts:
 *   - S-SEC-01: every server/model/operator string renders via
 *     escapeHTML or SVG textContent. No innerHTML with raw text.
 *   - Photos live in memory (object URLs) only; revoked on replace /
 *     restart. Nothing is written to browser storage.
 *   - Verdicts come from the server, which computes them in code from
 *     the photo readings. This view never invents a result: 429 / 503
 *     / 400 / network failures render as explicit error states.
 *
 * Test surface: __mop_verify_test__ exposes the pure helpers plus the
 * minimal state hooks a happy-dom smoke test needs.
 * ════════════════════════════════════════════════════════════════ */

import { registerRoute } from '../core/router.js';
import { escapeHTML } from '../core/sanitize.js';
import { authFetch } from '../core/api_client.js';
import { isDemoActive } from '../core/demo.js';

const STEPS_URL = '/api/copilot/mop/steps';
const VERIFY_URL = '/api/copilot/mop/verify';
const SAMPLE_BASE = '/assets/demo_photos/';
const MAX_FILE_BYTES = 12 * 1024 * 1024;

// Filenames under frontend/demo_photos/ (copies served from SAMPLE_BASE).
// The server offers no directory listing, so the list is UI config;
// labels are derived from the names in code (humanizeSampleName).
const SAMPLE_FILES = [
    '01_initial.jpg',
    '02_step1.jpg',
    '03_step2.jpg',
    '07_mismatch_after_step2.jpg',
    '08_uncertain.jpg',
];

// ─── Module state ──────────────────────────────────────────────────
let _routeRegistered = false;
let _wired = false;
let _stepsData = null;      // GET /api/copilot/mop/steps payload
let _sessionId = null;
let _currentStep = 0;
let _blockedStep = null;    // step_id whose last verdict was not MATCH
let _completed = false;
let _photo = null;          // { blob, name, url, width, height } | null
let _running = false;
let _elapsedTimer = null;
let _retryUntil = 0;        // epoch ms while a 429 Retry-After is honoured
let _retryTimer = null;
let _demoLayout = false;  // the view currently shows the demo skeleton
let _savedLayoutHTML = null; // classic .mv-layout outerHTML (restored when demo turns off)
let _lastBody = null;     // last verify response (re-rendered across skeleton swaps)
let _zoomOn = true;       // demo "Zoom to breakers" toggle state
let _samplesVisible = false; // probeSamples() found the sample photos
let _keysWired = false;   // document keydown listener (registered once)
let _demoListenerWired = false; // epms:demo-mode listener (registered once)

// ─── Pure helpers (testable) ───────────────────────────────────────
function newSessionId() {
    try {
        if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
            return 'mop-' + crypto.randomUUID();
        }
    } catch (_e) { /* fall through to Math.random */ }
    const hex = () => Math.floor(Math.random() * 0xffffffff).toString(16).padStart(8, '0');
    return 'mop-' + hex() + '-' + hex().slice(0, 4);
}

function humanizeSampleName(filename) {
    const stem = String(filename).replace(/\.[^.]*$/, '');
    return stem.replace(/_/g, ' ').replace(/([a-zA-Z])(\d)/g, '$1 $2');
}

function isFileTooLarge(size) {
    return typeof size !== 'number' || size <= 0 || size > MAX_FILE_BYTES;
}

function parseNotes(raw) {
    if (typeof raw !== 'string' || raw.length === 0) return '';
    try {
        const obj = JSON.parse(raw);
        if (obj && typeof obj.notes === 'string') return obj.notes;
    } catch (_e) { /* not JSON — fall through */ }
    return '';
}

function cardState(mapped, expected) {
    if (mapped === 'NO_ANSWER' || mapped === 'UNKNOWN') return 'warn';
    return mapped === expected ? 'match' : 'mismatch';
}

function stepState(stepId, currentStep, blockedStep, completed) {
    if (completed || stepId < currentStep) return 'done';
    if (stepId === blockedStep) return 'blocked';
    if (stepId === currentStep) return 'current';
    return 'todo';
}

function formatLatency(seconds) {
    if (typeof seconds !== 'number' || Number.isNaN(seconds)) return '—';
    return seconds.toFixed(1) + ' s';
}

function formatCountdown(ms) {
    const total = Math.max(0, Math.ceil(ms / 1000));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = total % 60;
    if (hours > 0) return hours + 'h ' + String(minutes).padStart(2, '0') + 'm';
    if (minutes > 0) return minutes + 'm ' + String(seconds).padStart(2, '0') + 's';
    return seconds + 's';
}

function verdictCopy(verdict, stepId, advanced, completed) {
    switch (verdict) {
        case 'MATCH':
            return completed
                ? 'MATCH — final step confirmed. Procedure complete.'
                : 'MATCH — step ' + stepId + ' confirmed, step ' + (stepId + 1) + ' unlocked.';
        case 'MISMATCH':
            return 'MISMATCH — step ' + stepId + ' not confirmed. Next step stays locked.';
        case 'UNCERTAIN':
            return 'UNCERTAIN — the photo does not settle step ' + stepId + '. Take a new photo; next step stays locked.';
        case 'NO_ANSWER':
            return 'NO_ANSWER — no reading came back for step ' + stepId + '. Take a new photo; next step stays locked.';
        default:
            return String(verdict) + ' — unexpected verdict for step ' + stepId + '.';
    }
}

function contradictionCopy(contradiction) {
    if (!contradiction || typeof contradiction !== 'object') return '';
    return 'Operator reported ' + contradiction.label + ' ' + contradiction.claimed
        + '; the photo shows ' + contradiction.observed + '.';
}

function _cropBoxes(readings, operated) {
    const boxes = [];
    for (const label of operated || []) {
        const box = (readings || {})[label] && (readings || {})[label].crop_box;
        if (Array.isArray(box) && box.length >= 4
            && box.slice(0, 4).every((v) => typeof v === 'number' && Number.isFinite(v))) {
            boxes.push(box.slice(0, 4));
        }
    }
    return boxes;
}

/**
 * Demo "Zoom to breakers": union of the API crop boxes plus a margin
 * (fraction of the union size on every side), clamped to the image.
 * Returns { x, y, w, h } in image pixels, or null when there is
 * nothing valid to zoom to. Pure; the SVG viewBox consumes it.
 */
function zoomBox(cropBoxes, width, height, margin) {
    const pad = (typeof margin === 'number' && margin >= 0) ? margin : 0.1;
    const valid = (cropBoxes || []).filter((box) => Array.isArray(box) && box.length >= 4
        && box.slice(0, 4).every((v) => typeof v === 'number' && Number.isFinite(v)));
    if (!valid.length || !(width > 0) || !(height > 0)) return null;
    let x1 = Infinity;
    let y1 = Infinity;
    let x2 = -Infinity;
    let y2 = -Infinity;
    for (const box of valid) {
        x1 = Math.min(x1, box[0]);
        y1 = Math.min(y1, box[1]);
        x2 = Math.max(x2, box[2]);
        y2 = Math.max(y2, box[3]);
    }
    const px = Math.max(1, x2 - x1) * pad;
    const py = Math.max(1, y2 - y1) * pad;
    const zx = Math.max(0, Math.round(x1 - px));
    const zy = Math.max(0, Math.round(y1 - py));
    const zx2 = Math.min(width, Math.round(x2 + px));
    const zy2 = Math.min(height, Math.round(y2 + py));
    return { x: zx, y: zy, w: Math.max(1, zx2 - zx), h: Math.max(1, zy2 - zy) };
}

// ─── DOM helpers ───────────────────────────────────────────────────
function _view() {
    return document.getElementById('view-mop-verify');
}

function _hook(name) {
    const view = _view();
    return view ? view.querySelector('[data-mv-' + name + ']') : null;
}

function _esc(value) {
    return escapeHTML(value === null || value === undefined ? '' : String(value));
}

function _stateChip(state) {
    const cls = state === 'CLOSED' ? 'closed' : (state === 'OPEN' ? 'open' : 'warn');
    return '<span class="mv-chip" data-chip="' + cls + '">' + _esc(state) + '</span>';
}

// ─── Procedure panel ───────────────────────────────────────────────
function _expectedChips(expectedState, operatedLabels) {
    return operatedLabels.map((label) => (
        '<span class="mv-expect"><span class="mv-expect-label">' + _esc(label) + '</span> '
        + _stateChip(expectedState ? expectedState[label] : '—') + '</span>'
    )).join('');
}

function renderStepper() {
    if (isDemoActive()) { renderDemoTracker(); return; }
    const list = _hook('stepper');
    if (!list || !_stepsData) return;
    const operated = _stepsData.operated_labels || [];
    const items = [];
    items.push(
        '<li class="mv-step" data-state="' + stepState(0, _currentStep, _blockedStep, _completed) + '">'
        + '<span class="mv-step-index">0</span>'
        + '<div class="mv-step-body">'
        + '<div class="mv-step-action">' + _esc('Confirm the initial panel state.') + '</div>'
        + '<div class="mv-step-expects">' + _expectedChips(_stepsData.initial_state, operated) + '</div>'
        + '</div></li>'
    );
    for (const step of _stepsData.steps || []) {
        const id = step.step_id;
        items.push(
            '<li class="mv-step" data-state="' + stepState(id, _currentStep, _blockedStep, _completed) + '">'
            + '<span class="mv-step-index">' + _esc(id) + '</span>'
            + '<div class="mv-step-body">'
            + '<div class="mv-step-action">' + _esc(step.action) + '</div>'
            + '<div class="mv-step-meta"><span class="mv-panel-label">'
            + _esc(step.panel_label) + '</span></div>'
            + '<div class="mv-step-expects">' + _expectedChips(step.expected_state, operated) + '</div>'
            + '</div></li>'
        );
    }
    list.innerHTML = items.join('');
}

function renderProcedureHead() {
    const mopEl = _hook('mop');
    if (mopEl) {
        mopEl.innerHTML = _stepsData
            ? '<span class="mv-mop-id">' + _esc(_stepsData.mop_id) + '</span> '
            + '<span class="mv-mop-ver">v' + _esc(_stepsData.version) + '</span>'
            : _esc('Loading procedure…');
    }
    const sessionEl = _hook('session');
    if (sessionEl) sessionEl.textContent = _sessionId || '—';
    renderStepper();
    renderCurrent();
}

function _currentStepRecord() {
    if (!_stepsData) return null;
    return (_stepsData.steps || []).find((s) => s.step_id === _currentStep) || null;
}

function renderCurrent() {
    const el = _hook('current');
    if (!el) return;
    if (isDemoActive()) { renderDemoCurrent(el); return; }
    if (!_stepsData) {
        el.innerHTML = '';
        return;
    }
    if (_completed) {
        el.innerHTML = '<div class="mv-current mv-complete">'
            + _esc('Procedure complete — all 5 steps verified.') + '</div>';
        return;
    }
    const record = _currentStepRecord();
    const action = _currentStep === 0
        ? 'Confirm the initial panel state.'
        : (record ? record.action : '');
    const panelLabel = _currentStep === 0
        ? '—'
        : (record ? record.panel_label : '—');
    el.innerHTML = '<div class="mv-current">'
        + '<span class="mv-current-k">Verifying step</span> '
        + '<span class="mv-step-index mv-inline">' + _esc(_currentStep) + '</span> '
        + '<span class="mv-panel-label">' + _esc(panelLabel) + '</span>'
        + '<div class="mv-step-action">' + _esc(action) + '</div>'
        + '</div>';
    _updateVerifyButton();
}

async function fetchSteps() {
    let res;
    try {
        res = await authFetch(STEPS_URL);
    } catch (_e) {
        return { ok: false, kind: 'network' };
    }
    if (res.status === 429) {
        return { ok: false, kind: 'ratelimit' };
    }
    if (!res.ok) {
        return { ok: false, kind: 'http', status: res.status };
    }
    try {
        return { ok: true, data: await res.json() };
    } catch (_e) {
        return { ok: false, kind: 'parse' };
    }
}

async function loadProcedure() {
    const out = await fetchSteps();
    if (!out.ok) {
        const mopEl = _hook('mop');
        if (mopEl) {
            const msg = out.kind === 'network'
                ? 'Procedure unavailable: network error reaching the server.'
                : out.kind === 'ratelimit'
                    ? 'Procedure unavailable: rate limit hit (429). Retry shortly.'
                    : 'Procedure unavailable: server error' + (out.status ? ' (' + out.status + ')' : '') + '.';
            mopEl.innerHTML = '<span class="mv-error-inline">' + _esc(msg) + '</span>';
        }
        return;
    }
    _stepsData = out.data;
    renderProcedureHead();
}

// ─── Verification panel ────────────────────────────────────────────
function _setPhoto(blob, name) {
    _clearPhoto();
    if (isDemoActive()) {
        // A new photo invalidates the displayed result overlay; the
        // right-column text stays until the next verification, as usual.
        _lastBody = null;
        _zoomOn = true;
        const zoomWrap = _hook('zoom-wrap');
        if (zoomWrap) zoomWrap.setAttribute('hidden', '');
        const zoomToggle = _hook('zoom');
        if (zoomToggle) zoomToggle.checked = true;
    }
    _photo = { blob, name, url: URL.createObjectURL(blob), width: 0, height: 0 };
    const img = new Image();
    img.onload = () => {
        if (_photo && _photo.url === img.src) {
            _photo.width = img.naturalWidth;
            _photo.height = img.naturalHeight;
        }
    };
    img.src = _photo.url;
    renderPreview();
    _updateVerifyButton();
}

function _clearPhoto() {
    if (_photo && _photo.url) {
        try { URL.revokeObjectURL(_photo.url); } catch (_e) { /* already revoked */ }
    }
    _photo = null;
}

function renderPreview() {
    if (isDemoActive()) { renderDemoStage(); return; }
    const el = _hook('preview');
    if (!el) return;
    if (!_photo) {
        el.innerHTML = '';
        return;
    }
    el.innerHTML = '<img class="mv-preview-img" alt="">'
        + '<div class="mv-preview-name">' + _esc(_photo.name) + '</div>';
    const img = el.querySelector('img');
    if (img) img.src = _photo.url;
}

function _updateVerifyButton() {
    const btn = _hook('verify-btn');
    if (!btn) return;
    const limited = Date.now() < _retryUntil;
    btn.disabled = _running || !_photo || !_stepsData || _completed || limited;
}

function _setStatus(html) {
    const el = _hook('status');
    if (el) el.innerHTML = html || '';
}

// Clear the operator readback so an old claim is never sent by
// accident with the next photo. Called after every verification and
// on Restart procedure.
function _clearClaim() {
    const claimInput = _hook('claim');
    if (claimInput) claimInput.value = '';
}

function _startElapsed() {
    _stopElapsed();
    const started = Date.now();
    const paint = () => {
        const secs = Math.floor((Date.now() - started) / 1000);
        if (isDemoActive()) {
            _setStatus('<div class="mv-running-big">'
                + '<div class="mv-running-secs">' + _esc(secs + ' s') + '</div>'
                + '<div class="mv-running-models">' + _esc('SAM 3.1 + Muse Spark 1.3') + '</div>'
                + '</div>');
        } else {
            _setStatus('<span class="mv-running">'
                + _esc('Verifying… ' + secs + ' s (about 6 to 12 s per photo)') + '</span>');
        }
        _updateVerifyButton();
    };
    paint();
    _elapsedTimer = setInterval(paint, 500);
}

function _stopElapsed() {
    if (_elapsedTimer !== null) {
        clearInterval(_elapsedTimer);
        _elapsedTimer = null;
    }
}

function _honourRetryAfter(seconds) {
    if (!Number.isFinite(seconds) || seconds <= 0) seconds = 60;
    _retryUntil = Date.now() + seconds * 1000;
    _updateVerifyButton();
    const paint = () => {
        const left = _retryUntil - Date.now();
        if (left <= 0) {
            if (_retryTimer !== null) {
                clearInterval(_retryTimer);
                _retryTimer = null;
            }
            _setStatus('');
            _updateVerifyButton();
            return;
        }
        _setStatus('<span class="mv-running">' + _esc('Rate limited — retry in ' + formatCountdown(left)) + '</span>');
    };
    if (_retryTimer !== null) clearInterval(_retryTimer);
    _retryTimer = setInterval(paint, 1000);
    paint();
}

async function runVerification() {
    if (_running || !_photo || !_stepsData || _completed) return;
    if (Date.now() < _retryUntil) return;
    _running = true;
    _updateVerifyButton();
    _startElapsed();
    const claimInput = _hook('claim');
    const claim = claimInput && typeof claimInput.value === 'string'
        ? claimInput.value.trim() : '';
    const form = new FormData();
    form.append('image', _photo.blob, _photo.name);
    form.append('step_id', String(_currentStep));
    form.append('session_id', _sessionId);
    if (claim) form.append('operator_claim', claim);
    let res;
    try {
        res = await authFetch(VERIFY_URL, { method: 'POST', body: form });
    } catch (_e) {
        _running = false;
        _stopElapsed();
        _setStatus('');
        _clearClaim();
        renderError('network', { message: 'Network error reaching the server. No result was produced.' });
        _updateVerifyButton();
        return;
    }
    _running = false;
    _stopElapsed();
    _setStatus('');
    if (res.status === 200) {
        let body = null;
        try { body = await res.json(); } catch (_e) { /* falls through */ }
        _clearClaim();
        if (!body || typeof body !== 'object') {
            renderError('parse', { message: 'The server answered 200 with an unreadable body. No result shown.' });
        } else {
            applyResult(body);
        }
        _updateVerifyButton();
        return;
    }
    if (res.status === 429) {
        let body = {};
        try { body = await res.json(); } catch (_e) { /* keep {} */ }
        const headerSecs = Number(res.headers.get('Retry-After'));
        const retrySecs = Number.isFinite(headerSecs) ? headerSecs : Number(body.retry_after_s);
        _clearClaim();
        renderError('ratelimit', {
            limit: body.limit,
            dailyCap: body.daily_cap,
            metaCallMade: body.meta_call_made,
            detail: body.detail,
        });
        _honourRetryAfter(retrySecs);
        return;
    }
    if (res.status === 400) {
        let detail = '';
        try { detail = (await res.json()).detail || ''; } catch (_e) { /* keep '' */ }
        _clearClaim();
        renderError('badrequest', { message: detail || 'Bad request.' });
        _updateVerifyButton();
        return;
    }
    let detail = '';
    try {
        const body = await res.json();
        detail = (body && body.detail) || '';
    } catch (_e) { /* keep '' */ }
    _clearClaim();
    renderError('unavailable', {
        message: detail || ('Verification unavailable (HTTP ' + res.status + ').'),
    });
    _updateVerifyButton();
}

// ─── Sample photos ─────────────────────────────────────────────────
function renderSamples() {
    const wrap = _hook('samples');
    if (!wrap) return;
    wrap.innerHTML = SAMPLE_FILES.map((file) => (
        '<button type="button" class="btn btn-secondary btn-sm mv-sample" data-sample="'
        + _esc(file) + '">' + _esc('Try: ' + humanizeSampleName(file)) + '</button>'
    )).join('');
    wrap.querySelectorAll('[data-sample]').forEach((btn) => {
        btn.addEventListener('click', () => loadSample(btn.getAttribute('data-sample')));
    });
}

async function probeSamples() {
    const section = _hook('samples-section');
    if (!section) return;
    let ok = false;
    try {
        const res = await fetch(SAMPLE_BASE + SAMPLE_FILES[0], { method: 'HEAD' });
        ok = !!(res && res.ok);
    } catch (_e) {
        ok = false;
    }
    if (!ok) {
        _samplesVisible = false;
        section.setAttribute('hidden', '');
        return;
    }
    _samplesVisible = true;
    section.removeAttribute('hidden');
    renderSamples();
}

async function loadSample(filename) {
    if (_running) return;
    _setStatus('<span class="mv-running">' + _esc('Loading sample photo…') + '</span>');
    let res;
    try {
        res = await fetch(SAMPLE_BASE + filename);
    } catch (_e) {
        _setStatus('');
        renderError('sample', { message: 'Could not load the sample photo (network error).' });
        return;
    }
    if (!res || !res.ok) {
        _setStatus('');
        renderError('sample', { message: 'Could not load the sample photo (HTTP ' + (res ? res.status : '—') + ').' });
        return;
    }
    const blob = await res.blob();
    if (isFileTooLarge(blob.size)) {
        _setStatus('');
        renderError('sample', { message: 'Sample photo exceeds the 12 MB limit.' });
        return;
    }
    _setStatus('');
    _setPhoto(blob, filename);
}

// ─── Result panel ──────────────────────────────────────────────────
const SVG_NS = 'http://www.w3.org/2000/svg';

function _svgEl(tag, attrs, text) {
    const el = document.createElementNS(SVG_NS, tag);
    for (const key of Object.keys(attrs || {})) el.setAttribute(key, attrs[key]);
    if (text !== undefined && text !== null) el.textContent = String(text);
    return el;
}

function renderOverlay(container, photoUrl, width, height, readings, operated, samBoxes, samVisible) {
    container.innerHTML = '';
    const img = document.createElement('img');
    img.className = 'mv-photo';
    img.alt = 'Uploaded panel photo with verification overlay';
    img.src = photoUrl;
    container.appendChild(img);
    const svg = _svgEl('svg', {
        class: 'mv-overlay',
        viewBox: '0 0 ' + width + ' ' + height,
        'aria-hidden': 'true',
    });
    const fontSize = Math.max(28, Math.round(width * 0.022));
    const samGroup = _svgEl('g', { class: 'mv-sam-group', display: samVisible ? 'inline' : 'none' });
    for (const box of samBoxes || []) {
        if (!Array.isArray(box) || box.length < 4) continue;
        const [x1, y1, x2, y2] = box;
        samGroup.appendChild(_svgEl('rect', {
            x: x1, y: y1, width: Math.max(1, x2 - x1), height: Math.max(1, y2 - y1),
            class: 'mv-sam-rect',
        }));
    }
    svg.appendChild(samGroup);
    for (const label of operated) {
        const reading = (readings || {})[label] || {};
        const box = reading.crop_box;
        if (!Array.isArray(box) || box.length < 4) continue;
        const [x1, y1, x2, y2] = box;
        const state = cardState(reading.mapped, undefined);
        const group = _svgEl('g', {});
        group.appendChild(_svgEl('rect', {
            x: x1, y: y1, width: Math.max(1, x2 - x1), height: Math.max(1, y2 - y1),
            class: 'mv-crop-rect',
            'data-crop': state === 'warn' ? 'warn' : (reading.mapped === 'CLOSED' || reading.mapped === 'OPEN' ? 'read' : 'warn'),
        }));
        const tag = _svgEl('text', {
            x: x1 + 6, y: Math.max(y1 - 8, fontSize),
            class: 'mv-crop-tag',
            'font-size': fontSize,
        }, label + ' ' + (reading.mapped || '—'));
        group.appendChild(tag);
        svg.appendChild(group);
    }
    container.appendChild(svg);
}

function renderCards(container, readings, expectedState, operated) {
    const cards = operated.map((label) => {
        const reading = (readings || {})[label] || {};
        const mapped = reading.mapped || '—';
        const expected = expectedState ? expectedState[label] : '—';
        const state = cardState(reading.mapped, expected);
        let note = parseNotes(reading.raw);
        if (!note) {
            note = reading.call_error || reading.parse_error || '—';
            if (typeof note === 'string' && note.length > 160) note = note.slice(0, 160) + '…';
        }
        return '<article class="mv-card" data-state="' + state + '">'
            + '<div class="mv-card-head"><span class="mv-card-label">' + _esc(label) + '</span>'
            + _stateChip(mapped) + '</div>'
            + '<div class="mv-card-row"><span>Expected</span>' + _stateChip(expected) + '</div>'
            + '<div class="mv-card-note">' + _esc(note) + '</div>'
            + '</article>';
    }).join('');
    container.innerHTML = '<div class="mv-cards-caption">' + _esc('Model reading per breaker crop') + '</div>'
        + '<div class="mv-cards">' + cards + '</div>';
}

function renderFooter(container, body) {
    const models = body.models || {};
    const methods = body.column_methods || {};
    const left = methods.left || {};
    const right = methods.right || {};
    container.innerHTML = '<div class="mv-foot">'
        + _esc(
            (models.sam || '—') + ' + ' + (models.spark || '—')
            + ' · ' + (body.meta_calls_made ?? '—') + ' Meta calls'
            + ' · ' + formatLatency(body.latency_s)
            + ' · ' + (body.sam_box_count ?? '—') + ' SAM boxes'
            + ' · left: ' + (left.method || '—') + ' / right: ' + (right.method || '—')
        ) + '</div>';
}

// ─── Demo presentation rendering ──────────────────────────────────
// Horizontal step tracker, one-line current step, single photo stage
// and right-column result. Used only when demo mode is on; the
// classic renderers above stay untouched for ?demo=0.

function _expectsTip(stepId, panelLabel, expectedState, operated) {
    const chips = (operated || []).map((label) => (
        label + ' ' + ((expectedState && expectedState[label]) || '—')
    )).join(' · ');
    return 'Step ' + stepId + ' (' + panelLabel + '): ' + chips;
}

function renderDemoTracker() {
    const list = _hook('stepper');
    if (!list || !_stepsData) return;
    const operated = _stepsData.operated_labels || [];
    const dot = (id, caption, state, tip) => (
        '<li class="mv-dot" data-state="' + (state === 'todo' ? 'pending' : state) + '" title="' + _esc(tip) + '">'
        + '<span class="mv-dot-circle">' + _esc(id) + '</span>'
        + '<span class="mv-dot-cap">' + _esc(caption) + '</span></li>'
    );
    const items = [dot(0, 'INIT', stepState(0, _currentStep, _blockedStep, _completed),
        _expectsTip(0, 'initial', _stepsData.initial_state, operated))];
    for (const step of _stepsData.steps || []) {
        items.push(dot(step.step_id, step.panel_label || '',
            stepState(step.step_id, _currentStep, _blockedStep, _completed),
            _expectsTip(step.step_id, step.panel_label || '', step.expected_state, operated)));
    }
    list.innerHTML = items.join('');
}

function renderDemoCurrent(el) {
    if (_completed) {
        el.innerHTML = '<div class="mv-current-line mv-complete">'
            + _esc('Procedure complete — all 5 steps verified.') + '</div>';
    } else if (!_stepsData) {
        el.innerHTML = '';
    } else {
        const record = _currentStepRecord();
        const action = _currentStep === 0
            ? 'Confirm the initial panel state.'
            : (record ? record.action : '');
        const panelLabel = _currentStep === 0
            ? '—'
            : (record ? record.panel_label : '—');
        el.innerHTML = '<div class="mv-current-line">'
            + '<strong>' + _esc('Step ' + _currentStep) + '</strong>'
            + ' <span class="mv-panel-label">' + _esc(panelLabel) + '</span>'
            + ' <span class="mv-current-action">' + _esc(action) + '</span></div>';
    }
    _updateVerifyButton();
}

function renderDemoResult(body) {
    const host = _hook('result');
    if (!host) return;
    const verdict = body.verdict || '—';
    const bannerState = verdict === 'MATCH' ? 'ok'
        : (verdict === 'MISMATCH' ? 'crit' : 'warn');
    let html = '<div class="mv-banner" data-state="' + bannerState + '">'
        + '<div class="mv-banner-title mv-demo-verdict">' + _esc(verdictCopy(verdict, body.step_id, body.advanced, _completed)) + '</div>';
    if (verdict === 'MISMATCH') {
        const differing = (body.differing_labels || []).map((label) => (
            '<span class="mv-chip" data-chip="crit">' + _esc(label) + '</span>'
        )).join(' ');
        html += '<div class="mv-banner-labels">' + _esc('Differing: ') + differing + '</div>'
            + '<div class="mv-hazard">' + _esc(body.hazard_if_wrong || '') + '</div>';
    }
    html += '<div class="mv-verdict-note">' + _esc('Computed in code from the photo readings') + '</div>'
        + '</div>';
    if (contradictionCopy(body.contradiction)) {
        const c = body.contradiction || {};
        html += '<div class="mv-banner" data-state="contra">'
            + '<div class="mv-contra-line">' + _esc('Operator: ' + (c.label || '—') + ' ' + (c.claimed || '—')) + '</div>'
            + '<div class="mv-contra-line">' + _esc('Photo: ' + (c.label || '—') + ' ' + (c.observed || '—')) + '</div>'
            + '</div>';
    }
    html += '<div data-mv-cards></div>';
    host.innerHTML = html;

    const cardsHost = host.querySelector('[data-mv-cards]');
    const operated = (_stepsData && _stepsData.operated_labels) || Object.keys(body.readings || {});
    if (cardsHost) renderDemoCards(cardsHost, body.readings, body.expected_state, operated);
    const footHost = _hook('result-foot');
    if (footHost) renderFooter(footHost, body);
    const zoomWrap = _hook('zoom-wrap');
    if (zoomWrap) {
        if (_photo && _cropBoxes(body.readings, operated).length) zoomWrap.removeAttribute('hidden');
        else zoomWrap.setAttribute('hidden', '');
    }
    renderDemoStage();
}

function renderDemoCards(container, readings, expectedState, operated) {
    const cards = (operated || []).map((label) => {
        const reading = (readings || {})[label] || {};
        const mapped = reading.mapped || '—';
        const expected = expectedState ? expectedState[label] : '—';
        const state = cardState(reading.mapped, expected);
        const icon = state === 'match' ? '✓' : (state === 'mismatch' ? '✗' : '!');
        const note = parseNotes(reading.raw) || reading.call_error || reading.parse_error || '—';
        return '<article class="mv-card" data-state="' + state + '">'
            + '<div class="mv-card-head"><span class="mv-card-label">' + _esc(label) + '</span>'
            + '<span class="mv-card-icon" data-state="' + state + '">' + _esc(icon) + '</span></div>'
            + '<div class="mv-card-row"><span>Read</span>' + _stateChip(mapped) + '</div>'
            + '<div class="mv-card-row"><span>Expected</span>' + _stateChip(expected) + '</div>'
            + '<div class="mv-card-note mv-card-note-clip" title="' + _esc(note) + '">' + _esc(note) + '</div>'
            + '</article>';
    }).join('');
    container.innerHTML = '<div class="mv-cards mv-cards-row">' + cards + '</div>';
}

function renderDemoStage() {
    const stage = _hook('photo');
    if (!stage) return;
    if (!_photo) {
        stage.innerHTML = '<div class="mv-stage-empty">' + _esc('Select a sample photo to begin.') + '</div>';
        return;
    }
    if (!_lastBody) {
        stage.innerHTML = '';
        const img = document.createElement('img');
        img.className = 'mv-demo-photo';
        img.alt = 'Selected panel photo';
        img.src = _photo.url;
        stage.appendChild(img);
        return;
    }
    const width = _photo.width || 0;
    const height = _photo.height || 0;
    if (!(width > 0) || !(height > 0)) {
        const probe = new Image();
        probe.onload = () => {
            _photo.width = probe.naturalWidth;
            _photo.height = probe.naturalHeight;
            renderDemoStage();
        };
        probe.src = _photo.url;
        return;
    }
    // One SVG holds the photo (<image>) plus every overlay rect in the
    // same user units, so photo and overlay stay aligned by
    // construction — including under the zoomed viewBox.
    const operated = (_stepsData && _stepsData.operated_labels) || Object.keys(_lastBody.readings || {});
    const zoom = _zoomOn ? zoomBox(_cropBoxes(_lastBody.readings, operated), width, height, 0.1) : null;
    const vb = zoom
        ? (zoom.x + ' ' + zoom.y + ' ' + zoom.w + ' ' + zoom.h)
        : ('0 0 ' + width + ' ' + height);
    stage.innerHTML = '';
    const svg = _svgEl('svg', {
        class: 'mv-demo-photo',
        viewBox: vb,
        role: 'img',
        'aria-label': 'Panel photo with verification overlay',
        preserveAspectRatio: 'xMidYMid meet',
    });
    svg.appendChild(_svgEl('image', { href: _photo.url, x: 0, y: 0, width, height }));
    for (const box of _lastBody.sam_boxes || []) {
        if (!Array.isArray(box) || box.length < 4) continue;
        const [x1, y1, x2, y2] = box;
        svg.appendChild(_svgEl('rect', {
            x: x1, y: y1, width: Math.max(1, x2 - x1), height: Math.max(1, y2 - y1),
            class: 'mv-sam-rect',
        }));
    }
    const fontSize = Math.max(28, Math.round(width * 0.022));
    for (const label of operated) {
        const reading = (_lastBody.readings || {})[label] || {};
        const box = reading.crop_box;
        if (!Array.isArray(box) || box.length < 4) continue;
        const [x1, y1, x2, y2] = box;
        svg.appendChild(_svgEl('rect', {
            x: x1, y: y1, width: Math.max(1, x2 - x1), height: Math.max(1, y2 - y1),
            class: 'mv-crop-rect',
            'data-crop': (reading.mapped === 'CLOSED' || reading.mapped === 'OPEN') ? 'read' : 'warn',
        }));
        svg.appendChild(_svgEl('text', {
            x: x1 + 6, y: Math.max(y1 - 8, fontSize),
            class: 'mv-crop-tag',
            'font-size': fontSize,
        }, label + ' ' + (reading.mapped || '—')));
    }
    stage.appendChild(svg);
}

function applyResult(body) {
    const session = body.session || {};
    if (typeof session.current_step === 'number') _currentStep = session.current_step;
    _completed = !!session.completed;
    _blockedStep = body.advanced ? null : body.step_id;
    _lastBody = body;
    renderProcedureHead();
    renderResult(body);
}

function renderResult(body) {
    if (isDemoActive()) renderDemoResult(body);
    else renderClassicResult(body);
}

function renderClassicResult(body) {
    const host = _hook('result');
    if (!host) return;
    const verdict = body.verdict || '—';
    const bannerState = verdict === 'MATCH' ? 'ok'
        : (verdict === 'MISMATCH' ? 'crit' : 'warn');
    let html = '<div class="mv-banner" data-state="' + bannerState + '">'
        + '<div class="mv-banner-title">' + _esc(verdictCopy(verdict, body.step_id, body.advanced, _completed)) + '</div>';
    if (verdict === 'MISMATCH') {
        const differing = (body.differing_labels || []).map((label) => (
            '<span class="mv-chip" data-chip="crit">' + _esc(label) + '</span>'
        )).join(' ');
        html += '<div class="mv-banner-labels">' + _esc('Differing: ') + differing + '</div>'
            + '<div class="mv-hazard">' + _esc(body.hazard_if_wrong || '') + '</div>';
    }
    html += '<div class="mv-verdict-note">' + _esc('Computed in code from the photo readings') + '</div>'
        + '</div>';
    const contradiction = contradictionCopy(body.contradiction);
    if (contradiction) {
        html += '<div class="mv-banner" data-state="contra">'
            + '<div class="mv-banner-title">' + _esc(contradiction) + '</div>'
            + '</div>';
    }
    html += '<div class="mv-photo-block">'
        + '<label class="mv-toggle"><input type="checkbox" data-mv-sam-toggle checked> '
        + _esc('Show SAM boxes') + '</label>'
        + '<div class="mv-photo-wrap" data-mv-overlay></div>'
        + '</div>'
        + '<div data-mv-cards></div>'
        + '<div data-mv-result-foot></div>';
    host.innerHTML = html;

    const overlayHost = host.querySelector('[data-mv-overlay]');
    const cardsHost = host.querySelector('[data-mv-cards]');
    const footHost = host.querySelector('[data-mv-result-foot]');
    const operated = (_stepsData && _stepsData.operated_labels) || Object.keys(body.readings || {});
    const width = (_photo && _photo.width) || 0;
    const height = (_photo && _photo.height) || 0;
    const toggle = host.querySelector('[data-mv-sam-toggle]');
    const paint = () => {
        if (overlayHost && _photo) {
            renderOverlay(
                overlayHost, _photo.url, width, height,
                body.readings, operated, body.sam_boxes,
                !toggle || toggle.checked,
            );
        }
    };
    if (toggle) toggle.addEventListener('change', paint);
    if (width > 0 && height > 0) {
        paint();
    } else if (overlayHost && _photo) {
        const probe = new Image();
        probe.onload = () => {
            _photo.width = probe.naturalWidth;
            _photo.height = probe.naturalHeight;
            renderOverlay(
                overlayHost, _photo.url, _photo.width, _photo.height,
                body.readings, operated, body.sam_boxes,
                !toggle || toggle.checked,
            );
        };
        probe.src = _photo.url;
    }
    if (cardsHost) renderCards(cardsHost, body.readings, body.expected_state, operated);
    if (footHost) renderFooter(footHost, body);
}

function renderError(kind, info) {
    const host = _hook('result');
    if (!host) return;
    const data = info || {};
    let title = '';
    let bodyHtml = '';
    if (kind === 'ratelimit') {
        title = 'Rate limited (429) — no Meta call was made';
        bodyHtml = '<div class="mv-err-row"><span>Limit</span><strong>'
            + _esc(data.limit || '—') + '</strong></div>'
            + '<div class="mv-err-row"><span>Daily cap</span><strong>'
            + _esc(data.dailyCap ?? '—') + '</strong></div>'
            + '<div class="mv-err-row"><span>Meta call made</span><strong>'
            + _esc(data.metaCallMade === undefined ? '—' : String(data.metaCallMade)) + '</strong></div>'
            + (data.detail ? '<div class="mv-err-detail">' + _esc(data.detail) + '</div>' : '');
    } else if (kind === 'unavailable') {
        title = 'Verification unavailable (503)';
        bodyHtml = '<div class="mv-err-detail">' + _esc(data.message || '') + '</div>'
            + '<div class="mv-err-note">' + _esc('No result was produced. Nothing below is a reading.') + '</div>';
    } else if (kind === 'badrequest') {
        title = 'Rejected by the server (400)';
        bodyHtml = '<div class="mv-err-detail">' + _esc(data.message || '') + '</div>';
    } else if (kind === 'network') {
        title = 'Network error';
        bodyHtml = '<div class="mv-err-detail">' + _esc(data.message || '') + '</div>';
    } else if (kind === 'sample') {
        title = 'Sample photo';
        bodyHtml = '<div class="mv-err-detail">' + _esc(data.message || '') + '</div>';
    } else if (kind === 'file') {
        title = 'Photo rejected';
        bodyHtml = '<div class="mv-err-detail">' + _esc(data.message || '') + '</div>';
    } else {
        title = 'Unexpected error';
        bodyHtml = '<div class="mv-err-detail">' + _esc(data.message || '') + '</div>';
    }
    host.innerHTML = '<div class="mv-banner" data-state="err">'
        + '<div class="mv-banner-title">' + _esc(title) + '</div>'
        + bodyHtml + '</div>';
}

// ─── Session ───────────────────────────────────────────────────────
function restartProcedure() {
    if (_running) return;
    _clearPhoto();
    const fileInput = _hook('file');
    if (fileInput) fileInput.value = '';
    _clearClaim();
    _sessionId = newSessionId();
    _currentStep = 0;
    _blockedStep = null;
    _completed = false;
    _lastBody = null;
    _zoomOn = true;
    const zoomWrap = _hook('zoom-wrap');
    if (zoomWrap) zoomWrap.setAttribute('hidden', '');
    const zoomToggle = _hook('zoom');
    if (zoomToggle) zoomToggle.checked = true;
    const host = _hook('result');
    if (host) {
        host.innerHTML = '<div class="mv-empty">' + _esc('No verification yet. Pick a photo and press Verify.') + '</div>';
    }
    if (isDemoActive()) {
        const footHost = _hook('result-foot');
        if (footHost) footHost.innerHTML = '';
    }
    renderPreview();
    renderProcedureHead();
    _setStatus('');
    _updateVerifyButton();
}

// ─── Demo presentation skeleton ─────────────────────────────────
// Swapped in for .mv-layout only when demo mode is on (?demo=0 keeps
// the static skeleton untouched). Hook names match the classic
// skeleton so every data path stays shared; there is no file picker
// in demo mode (samples + keys 1-5 are the photo source).

function demoSkeletonHTML() {
    return '<div class="mv-demo">'
        + '<section class="mv-tracker" aria-label="Procedure steps">'
        + '<ol class="mv-circles" data-mv-stepper></ol>'
        + '<div class="mv-tracker-row">'
        + '<div class="mv-tracker-current" data-mv-current></div>'
        + '<button type="button" class="btn btn-secondary" data-mv-restart>Restart procedure</button>'
        + '</div></section>'
        + '<div class="mv-demo-cols">'
        + '<section class="mv-stage-col" aria-label="Panel photo">'
        + '<div class="mv-stage" data-mv-photo></div>'
        + '<label class="mv-toggle mv-zoom" data-mv-zoom-wrap hidden><input type="checkbox" data-mv-zoom checked> '
        + 'Zoom to breakers</label>'
        + '</section>'
        + '<section class="mv-right" aria-label="Verification result">'
        + '<div class="mv-status" data-mv-status aria-live="polite"></div>'
        + '<div data-mv-result><div class="mv-empty">No verification yet. Pick a photo and press Verify.</div></div>'
        + '<div class="mv-controls">'
        + '<div class="mv-samples" data-mv-samples-section hidden>'
        + '<div class="mv-field-label">Try a sample photo</div>'
        + '<div class="mv-sample-row" data-mv-samples></div>'
        + '</div>'
        + '<label class="mv-field">'
        + '<span class="mv-field-label">Operator readback</span>'
        + '<input type="text" data-mv-claim placeholder="e.g. Q8 closed" maxlength="120" autocomplete="off">'
        + '</label>'
        + '<div class="mv-actions">'
        + '<button type="button" class="btn" data-mv-verify-btn disabled>Verify</button>'
        + '</div>'
        + '<div class="mv-verify-note">Verification can take up to a minute depending on API load.</div>'
        + '<div class="mv-keys-hint">Keys: 1–5 load sample · Enter verify · R restart</div>'
        + '</div>'
        + '<div data-mv-result-foot></div>'
        + '</section>'
        + '</div>'
        + '</div>';
}

function syncDemoLayout() {
    const view = _view();
    if (!view) return;
    const wantDemo = isDemoActive();
    if (wantDemo === _demoLayout) return;
    if (wantDemo) {
        const layout = view.querySelector('.mv-layout');
        if (!layout) return;
        if (_savedLayoutHTML === null) _savedLayoutHTML = layout.outerHTML;
        const tmp = document.createElement('div');
        tmp.innerHTML = demoSkeletonHTML();
        if (!tmp.firstElementChild) return;
        layout.replaceWith(tmp.firstElementChild);
        _demoLayout = true;
    } else {
        const demo = view.querySelector('.mv-demo');
        if (!demo || _savedLayoutHTML === null) {
            _demoLayout = false;
            return;
        }
        const tmp = document.createElement('div');
        tmp.innerHTML = _savedLayoutHTML;
        if (!tmp.firstElementChild) return;
        demo.replaceWith(tmp.firstElementChild);
        _demoLayout = false;
    }
    _wired = false;
    _wire();
    renderProcedureHead();
    renderPreview();
    if (_samplesVisible) {
        const section = _hook('samples-section');
        if (section) section.removeAttribute('hidden');
        renderSamples();
    }
    if (_lastBody && _stepsData) renderResult(_lastBody);
}

function _inTextField(target) {
    if (target && typeof target.closest === 'function'
        && target.closest('input, textarea, [contenteditable="true"], [contenteditable=""]')) {
        return true;
    }
    const active = (typeof document !== 'undefined') ? document.activeElement : null;
    return !!active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA'
        || !!active.isContentEditable);
}

// Demo-only shortcuts: 1-5 load the samples in shown order, Enter
// verifies when enabled, R restarts. Silent when demo mode is off,
// when the view is hidden, or when focus sits in a text field.
function _onDemoKey(event) {
    if (!isDemoActive()) return;
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const view = _view();
    if (!view || view.hasAttribute('hidden')) return;
    if (_inTextField(event.target)) return;
    const key = event.key;
    if (typeof key === 'string' && key.length === 1 && key >= '1' && key <= '5') {
        const file = SAMPLE_FILES[Number(key) - 1];
        if (file && !_running) loadSample(file);
        return;
    }
    if (key === 'Enter') {
        // A focused button or link already activates natively; skip it
        // here so Verify never runs twice from one keypress.
        if (event.target && typeof event.target.closest === 'function'
            && event.target.closest('button, a')) return;
        const btn = _hook('verify-btn');
        if (btn && !btn.disabled) runVerification();
        return;
    }
    if (key === 'r' || key === 'R') {
        restartProcedure();
    }
}

// ─── Wiring + lifecycle ────────────────────────────────────────────
function _wire() {
    if (_wired) return;
    _wired = true;
    const fileInput = _hook('file');
    if (fileInput) {
        fileInput.addEventListener('change', () => {
            const file = fileInput.files && fileInput.files[0];
            if (!file) return;
            if (isFileTooLarge(file.size)) {
                fileInput.value = '';
                renderError('file', {
                    message: 'Photo exceeds the 12 MB limit (' + (file.size / 1048576).toFixed(1) + ' MB). Pick a smaller file.',
                });
                return;
            }
            _setPhoto(file, file.name || 'photo.jpg');
        });
    }
    const verifyBtn = _hook('verify-btn');
    if (verifyBtn) verifyBtn.addEventListener('click', runVerification);
    const restartBtn = _hook('restart');
    if (restartBtn) restartBtn.addEventListener('click', restartProcedure);
    const zoomToggle = _hook('zoom');
    if (zoomToggle) {
        zoomToggle.addEventListener('change', () => {
            _zoomOn = !!zoomToggle.checked;
            if (_lastBody) renderDemoStage();
        });
    }
    if (!_keysWired && typeof document !== 'undefined') {
        _keysWired = true;
        document.addEventListener('keydown', _onDemoKey);
    }
}

function initMopVerifyView() {
    if (_routeRegistered) return;
    if (!_demoListenerWired && typeof window !== 'undefined') {
        _demoListenerWired = true;
        window.addEventListener('epms:demo-mode', () => syncDemoLayout());
    }
    registerRoute('mop-verify', {
        viewId: 'view-mop-verify',
        activate: ({ firstActivation } = {}) => {
            syncDemoLayout();
            _wire();
            if (firstActivation) {
                _sessionId = newSessionId();
                renderProcedureHead();
                loadProcedure();
                probeSamples();
            }
        },
    });
    _routeRegistered = true;
}

function reset() {
    _stopElapsed();
    if (_retryTimer !== null) {
        clearInterval(_retryTimer);
        _retryTimer = null;
    }
    _clearPhoto();
    _routeRegistered = false;
    _wired = false;
    _stepsData = null;
    _sessionId = null;
    _currentStep = 0;
    _blockedStep = null;
    _completed = false;
    _running = false;
    _retryUntil = 0;
    _demoLayout = false;
    _savedLayoutHTML = null;
    _lastBody = null;
    _zoomOn = true;
    _samplesVisible = false;
}

// ─── Exports ───────────────────────────────────────────────────────
export { initMopVerifyView };
export const __mop_verify_test__ = {
    newSessionId,
    humanizeSampleName,
    isFileTooLarge,
    parseNotes,
    cardState,
    stepState,
    formatLatency,
    formatCountdown,
    verdictCopy,
    contradictionCopy,
    renderStepper,
    renderCurrent,
    renderOverlay,
    renderCards,
    renderFooter,
    renderError,
    applyResult,
    fetchSteps,
    loadProcedure,
    runVerification,
    loadSample,
    restartProcedure,
    syncDemoLayout,
    zoomBox,
    initMopVerifyView,
    reset,
    SAMPLE_FILES,
    MAX_FILE_BYTES,
    getState: () => ({
        sessionId: _sessionId,
        currentStep: _currentStep,
        blockedStep: _blockedStep,
        completed: _completed,
        running: _running,
        hasPhoto: !!_photo,
        hasSteps: !!_stepsData,
        demoLayout: _demoLayout,
        hasResult: !!_lastBody,
        zoomOn: _zoomOn,
    }),
    setStepsData: (data) => { _stepsData = data; },
    setSession: (id, step) => { _sessionId = id; _currentStep = step; },
    setPhotoForTest: (blob, name, width, height) => {
        _clearPhoto();
        _photo = { blob, name, url: 'blob:test/' + name, width: width || 0, height: height || 0 };
    },
};
