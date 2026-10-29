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

function _startElapsed() {
    _stopElapsed();
    const started = Date.now();
    const paint = () => {
        const secs = Math.floor((Date.now() - started) / 1000);
        _setStatus('<span class="mv-running">'
            + _esc('Verifying… ' + secs + ' s (about 6 to 12 s per photo)') + '</span>');
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
        renderError('badrequest', { message: detail || 'Bad request.' });
        _updateVerifyButton();
        return;
    }
    let detail = '';
    try {
        const body = await res.json();
        detail = (body && body.detail) || '';
    } catch (_e) { /* keep '' */ }
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
        section.setAttribute('hidden', '');
        return;
    }
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

function applyResult(body) {
    const session = body.session || {};
    if (typeof session.current_step === 'number') _currentStep = session.current_step;
    _completed = !!session.completed;
    _blockedStep = body.advanced ? null : body.step_id;
    renderProcedureHead();

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
    const claimInput = _hook('claim');
    if (claimInput) claimInput.value = '';
    _sessionId = newSessionId();
    _currentStep = 0;
    _blockedStep = null;
    _completed = false;
    const host = _hook('result');
    if (host) {
        host.innerHTML = '<div class="mv-empty">' + _esc('No verification yet. Pick a photo and press Verify.') + '</div>';
    }
    renderPreview();
    renderProcedureHead();
    _setStatus('');
    _updateVerifyButton();
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
}

function initMopVerifyView() {
    if (_routeRegistered) return;
    registerRoute('mop-verify', {
        viewId: 'view-mop-verify',
        activate: ({ firstActivation } = {}) => {
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
    }),
    setStepsData: (data) => { _stepsData = data; },
    setSession: (id, step) => { _sessionId = id; _currentStep = step; },
    setPhotoForTest: (blob, name, width, height) => {
        _clearPhoto();
        _photo = { blob, name, url: 'blob:test/' + name, width: width || 0, height: height || 0 };
    },
};
