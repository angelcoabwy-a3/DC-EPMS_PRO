/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/overview.js
 * ROADMAP V11 T2.1 Vector 4b — the Overview / landing dashboard
 * extracted from app.js (the final view out of the IIFE monolith).
 *
 * The operator landing screen: health pills, telemetry KPI cards, the
 * Chart.js PUE trend, the grounded RAG agent chat (SSE token stream),
 * the incident strip, voice input (Riva-ready), the shift-report PDF
 * export, and the Site Health Index panel.
 *
 *   - registerRoute('overview', …) hands navigation to core/router.js.
 *   - telemetry: subscribes to the reactive store (core/telemetry_
 *     engine.js owns the SSE). The legacy EventSource fallback path
 *     was dead code (window.__epms.useNewEngine is frozen true) and is
 *     dropped here per the ROADMAP V4 pre-step.
 *   - LLM/agent text is escapeHTML'd before innerHTML (the agent box
 *     renders escaped plaintext, not markup — F3-5 consistent).
 *   - placeholder views deep-link a suggested query in via the
 *     `epms:overview-ask` DOM event.
 *
 * Test surface: __overview_test__ exposes the pure render helpers.
 * ════════════════════════════════════════════════════════════════ */

import { registerRoute } from '../core/router.js';
import { escapeHTML } from '../core/sanitize.js';

let _initialized = false;
let _intervals = [];

// ── State ──────────────────────────────────────────────────────────
const state = {
    pueHistory: [],
    latestTelemetry: null,
    incidents: [],
    agentStreaming: false,
    agentBuffer: '',
    agentSources: [],
    mediaRecorder: null,
    isRecording: false,
};

// ── DOM references ─────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const els = {
    pueValue: () => $('kpi-pue'),
    tempValue: () => $('kpi-temp'),
    loadValue: () => $('kpi-load'),
    rackValue: () => $('kpi-racks'),
    pueChart: () => $('pueChart'),
    agentInput: () => $('agent-input'),
    agentResponse: () => $('agent-response'),
    agentSend: () => $('agent-send'),
    agentVoice: () => $('agent-voice'),
    agentModel: () => $('agent-model'),
    incidentList: () => $('incident-list'),
    healthPg: () => $('health-pg'),
    healthRag: () => $('health-rag'),
    healthGemma: () => $('health-gemma'),
    healthGpu: () => $('health-gpu'),
    advisoryZone: () => $('advisory-zone'),
    shiftReport: () => $('btn-shift-report'),
};

// ── Utilities ──────────────────────────────────────────────────────
const fmt = {
    pue: (v) => (v == null ? '—' : v.toFixed(3)),
    temp: (v) => (v == null ? '—' : v.toFixed(1) + '°C'),
    load: (v) => (v == null ? '—' : Math.round(v).toLocaleString() + ' kW'),
    int: (v) => (v == null ? '—' : Math.round(v).toLocaleString()),
    time: (iso) => {
        if (!iso) return '—';
        try { return new Date(iso).toLocaleTimeString('en-CA', { hour12: false }); }
        catch (e) { return iso.slice(11, 19); }
    },
};

// ── Health check (every 15s) ───────────────────────────────────────
async function checkHealth() {
    try {
        const resp = await fetch('/api/health');
        if (!resp.ok) throw new Error('health endpoint down');
        const h = await resp.json();

        updatePill(els.healthPg(), h.postgres?.status === 'up', 'PostgreSQL');
        updatePill(els.healthRag(), h.rag?.status === 'up', `RAG (${h.rag?.docs || 0})`);
        updatePill(els.healthGemma(), h.gemma?.status === 'up', 'Gemma 4');

        const gpu = h.gpu || {};
        const gpuUp = gpu.source === 'nvml';
        const gpuLbl = gpuUp
            ? `GPU ${gpu.sm_pct || 0}% · ${gpu.temp_c || 0}°C`
            : 'GPU offline';
        updatePill(els.healthGpu(), gpuUp, gpuLbl);
    } catch (e) {
        console.warn('health check failed:', e);
        [els.healthPg(), els.healthRag(), els.healthGemma(), els.healthGpu()]
            .forEach((el) => el && updatePill(el, false, el.dataset.label || 'offline'));
    }
}

function updatePill(el, isUp, label) {
    if (!el) return;
    el.classList.toggle('up', isUp);
    el.classList.toggle('down', !isUp);
    const lblEl = el.querySelector('.lbl');
    if (lblEl) lblEl.textContent = label;
}

// ── Telemetry ──────────────────────────────────────────────────────
// core/telemetry_engine.js owns the SSE; main.js starts it. We
// subscribe to the reactive store. (The legacy EventSource fallback
// that lived here was dead code — useNewEngine is frozen true — and
// was dropped in T2.1 Vector 4.)
function subscribeTelemetry() {
    if (window.__epms) {
        window.__epms.subscribe('latestTelemetry', (point) => {
            if (point) handleTelemetry(point);
        });
    }
}

function handleTelemetry(point) {
    state.latestTelemetry = point;
    updateKPIs(point);
    if (point.pue != null) {
        state.pueHistory.push({
            ts: point.ts,
            pue: point.pue,
            temp: point.hall_temp_c,
        });
        if (state.pueHistory.length > 60) state.pueHistory.shift();
        updatePueChart();
    }
    checkAdvisories(point);
}

function updateKPIs(p) {
    const pueEl = els.pueValue();
    if (pueEl) {
        pueEl.textContent = fmt.pue(p.pue);
        pueEl.className = 'value ' + (
            p.pue > 1.40 ? 'crit'
                : p.pue > 1.30 ? 'warn' : 'ok'
        );
    }
    const tempEl = els.tempValue();
    if (tempEl) {
        tempEl.textContent = fmt.temp(p.hall_temp_c);
        tempEl.className = 'value ' + (
            p.hall_temp_c >= 35 ? 'crit'
                : p.hall_temp_c >= 30 ? 'warn' : 'ok'
        );
    }
    const loadEl = els.loadValue();
    if (loadEl) loadEl.textContent = fmt.load(p.it_load_kw);

    const rackEl = els.rackValue();
    if (rackEl) rackEl.textContent = `${p.rack_count || 118} × ${p.rack_tdp_kw || 142}kW`;
}

// ── Advisories ─────────────────────────────────────────────────────
function checkAdvisories(point) {
    const zone = els.advisoryZone();
    if (!zone) return;
    zone.innerHTML = '';

    if (point.pue > 1.40) {
        addAdvisory(zone, 'crit', 'PUE efficiency alert',
            `Current PUE ${point.pue.toFixed(3)} exceeds A-Cubed Semiconductor threshold (1.40). `
            + 'Immediate check recommended: chiller redundancy (N-1), DLC flow, hot-aisle containment.');
    } else if (point.pue > 1.30) {
        addAdvisory(zone, 'warn', 'PUE trending upward',
            `PUE ${point.pue.toFixed(3)} above target 1.30. Monitor next 15 minutes for sustained trend.`);
    }

    if (point.hall_temp_c >= 32) {
        addAdvisory(zone, 'crit', 'ASHRAE A2 thermal excursion',
            `Hall temperature ${point.hall_temp_c.toFixed(1)}°C approaching A2 limit (35°C). `
            + 'Verify cooling delivery and IT load correlation.');
    }
}

function addAdvisory(zone, level, hdr, body) {
    const el = document.createElement('div');
    el.className = 'advisory ' + level;
    el.innerHTML = `<div class="hdr">${escapeHTML(hdr)}</div>
                    <div>${escapeHTML(body)}</div>`;
    zone.appendChild(el);
}

// ── Chart.js: PUE trend ────────────────────────────────────────────
let pueChart = null;
function initChart() {
    const canvas = els.pueChart();
    if (!canvas || !window.Chart) return;
    const ctx = canvas.getContext('2d');

    pueChart = new window.Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'PUE',
                data: [],
                borderColor: '#00B8D4',
                backgroundColor: 'rgba(0, 120, 212, 0.1)',
                borderWidth: 1.5,
                pointRadius: 0,
                tension: 0.3,
                fill: true,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 300 },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#111827',
                    titleColor: '#e2e8f0',
                    bodyColor: '#94a3b8',
                    borderColor: 'rgba(148,163,184,0.2)',
                    borderWidth: 1,
                    padding: 8,
                    callbacks: {
                        label: (c) => `PUE: ${c.parsed.y.toFixed(3)}`,
                    },
                },
            },
            scales: {
                x: {
                    display: false,
                    grid: { display: false },
                },
                y: {
                    min: 1.05,
                    max: 1.50,
                    ticks: {
                        color: '#64748b',
                        font: { size: 9 },
                        callback: (v) => v.toFixed(2),
                    },
                    grid: { color: 'rgba(148,163,184,0.08)' },
                },
            },
        },
    });
}

function updatePueChart() {
    if (!pueChart) return;
    const points = state.pueHistory.slice(-60);
    pueChart.data.labels = points.map((_, i) => i);
    pueChart.data.datasets[0].data = points.map((p) => p.pue);
    pueChart.update('none');
}

// ── Agent rendering helpers (sources + markdown-lite) ──────────────
const TIER_COLORS = {
    1: '#E53935',   // red
    2: '#FB8C00',   // orange
    3: '#00B8D4',   // cyan
    4: '#4CAF50',   // green
};

function renderSourcesBlock() {
    if (!state.agentSources || state.agentSources.length === 0) return '';
    const chips = state.agentSources.map((s) => {
        const tier = s.tier || '?';
        const tierClass = `tier-${tier}`;
        const bgColor = TIER_COLORS[tier] || '#666';
        const boost = s.boost > 0 ? ` boost=+${s.boost.toFixed(2)}` : '';
        const title = [
            `Doc: ${s.doc_id}`,
            `Tier: ${tier} (${s.priority || 'n/a'})`,
            `Standard: ${s.standard || 'n/a'}`,
            `Score: ${s.score.toFixed(3)}${boost}`,
            '',
            s.snippet,
        ].join('\n');
        return `<span class="src-chip ${tierClass}" title="${escapeHTML(title)}" style="display:inline-flex;align-items:center;gap:5px;padding:3px 8px;margin:2px;font-size:10px;font-family:monospace;border-radius:3px;background:#1C2128;border:1px solid #2A3038;">
            <span class="src-tier" style="font-weight:700;font-size:9px;padding:1px 5px;border-radius:2px;background:${bgColor};color:#fff;">T${tier}</span>
            <span class="src-id" style="color:#E8EAED;">${escapeHTML(s.doc_id)}</span>
        </span>`;
    }).join('');
    return `<div class="agent-sources" style="margin-bottom:10px;padding:8px 10px;background:#14181D;border-left:2px solid #00B8D4;border-radius:4px;">
        <div class="agent-sources-lbl" style="font-size:10px;color:#9AA0A6;text-transform:uppercase;letter-spacing:0.6px;margin-bottom:6px;">Grounded in ${state.agentSources.length} source${state.agentSources.length === 1 ? '' : 's'}:</div>
        <div class="agent-sources-chips" style="display:flex;flex-wrap:wrap;gap:2px;">${chips}</div>
    </div>`;
}

function renderAgentStreaming(el) {
    const sources = renderSourcesBlock();
    const body = escapeHTML(state.agentBuffer) + '<span class="streaming-cursor"></span>';
    el.innerHTML = sources + '<div class="agent-body" style="white-space:pre-wrap;word-wrap:break-word;font-size:12px;line-height:1.55;">' + body + '</div>';
}

function renderAgentFinal(el) {
    const sources = renderSourcesBlock();
    el.innerHTML = sources
        + '<div class="agent-body" style="white-space:pre-wrap;word-wrap:break-word;font-size:12px;line-height:1.55;">' + escapeHTML(state.agentBuffer) + '</div>';
}

// ── SSE: Agent streaming ───────────────────────────────────────────
async function sendAgentQuery(query) {
    if (!query || state.agentStreaming) return;
    state.agentStreaming = true;
    state.agentBuffer = '';
    state.agentSources = [];

    const sendBtn = els.agentSend();
    if (sendBtn) sendBtn.disabled = true;

    const respEl = els.agentResponse();
    respEl.classList.remove('empty');
    respEl.innerHTML = '<span class="loading"></span>Querying knowledge base...';

    try {
        const resp = await fetch('/agent/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query: query,
                max_tokens: 500,
                model_hint: 'auto',
            }),
        });

        if (!resp.ok) throw new Error(`agent returned ${resp.status}`);

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        respEl.innerHTML = '<span class="streaming-cursor"></span>';

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const data = line.slice(6).trim();
                if (data === '[DONE]') {
                    renderAgentFinal(respEl);
                    return;
                }
                try {
                    const obj = JSON.parse(data);
                    // handle RAG sources emitted before tokens
                    if (obj.sources) {
                        state.agentSources = obj.sources;
                        renderAgentStreaming(respEl);
                    }
                    if (obj.token) {
                        state.agentBuffer += obj.token;
                        renderAgentStreaming(respEl);
                        respEl.scrollTop = respEl.scrollHeight;
                    }
                    if (obj.error) {
                        respEl.innerHTML = `<span style="color:var(--crit)">Error: ${escapeHTML(obj.error)}</span>`;
                    }
                } catch (e) {
                    console.warn('parse agent chunk:', e);
                }
            }
        }
        renderAgentFinal(respEl);
    } catch (e) {
        respEl.innerHTML = `<span style="color:var(--crit)">Error: ${escapeHTML(e.message)}</span>`;
    } finally {
        state.agentStreaming = false;
        if (sendBtn) sendBtn.disabled = false;
    }
}

// ── Incident polling ───────────────────────────────────────────────
async function refreshIncidents() {
    try {
        const resp = await fetch('/api/incidents?limit=20');
        if (!resp.ok) return;
        const data = await resp.json();
        state.incidents = data.rows || [];
        renderIncidents();
    } catch (e) {
        console.warn('incident fetch failed:', e);
    }
}

function renderIncidents() {
    const list = els.incidentList();
    if (!list) return;
    if (state.incidents.length === 0) {
        list.innerHTML = '<div style="font-size:11px;color:var(--text-dim);padding:20px;text-align:center">No incidents</div>';
        return;
    }
    list.innerHTML = state.incidents.map((inc) => {
        const cls = severityClass(inc.severity);
        return `<div class="incident-row ${cls}">
            <span class="sev" style="color:var(--${cls === 'info' ? 'accent' : cls})">${escapeHTML((inc.severity || 'info').slice(0, 4).toUpperCase())}</span>
            <span class="ts">${fmt.time(inc.ts)}</span>
            <span class="title" title="${escapeHTML(inc.title)}">${escapeHTML(inc.title)}</span>
            <span class="status">${escapeHTML(inc.status)}</span>
        </div>`;
    }).join('');
}

// ── Voice input (Riva-ready) ───────────────────────────────────────
async function toggleVoice() {
    if (state.isRecording) {
        stopRecording();
        return;
    }
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
        const chunks = [];

        recorder.ondataavailable = (e) => {
            if (e.data.size > 0) chunks.push(e.data);
        };

        recorder.onstop = async () => {
            const blob = new Blob(chunks, { type: 'audio/webm' });
            stream.getTracks().forEach((t) => t.stop());
            await sendVoiceToRiva(blob);
        };

        recorder.start();
        state.mediaRecorder = recorder;
        state.isRecording = true;
        const btn = els.agentVoice();
        if (btn) btn.classList.add('recording');
    } catch (e) {
        alert('Microphone access denied: ' + e.message);
    }
}

function stopRecording() {
    if (state.mediaRecorder && state.mediaRecorder.state === 'recording') {
        state.mediaRecorder.stop();
    }
    state.isRecording = false;
    const btn = els.agentVoice();
    if (btn) btn.classList.remove('recording');
}

async function sendVoiceToRiva(blob) {
    try {
        const fd = new FormData();
        fd.append('audio', blob, 'voice.webm');
        const resp = await fetch('/api/voice/transcribe', {
            method: 'POST',
            body: fd,
        });
        const data = await resp.json();
        if (data.transcript) {
            els.agentInput().value = data.transcript;
            sendAgentQuery(data.transcript);
        } else if (data.status === 'not_implemented') {
            alert('Voice ready: Riva ASR integration pending (WSL2). '
                + 'Configure RIVA_GRPC_URL in .env.');
        }
    } catch (e) {
        alert('Voice upload failed: ' + e.message);
    }
}

// ── Shift Report download ──────────────────────────────────────────
async function downloadShiftReport() {
    const btn = els.shiftReport();
    if (!btn) return;
    btn.disabled = true;
    const orig = btn.innerHTML;
    btn.innerHTML = '<span class="loading"></span>Generating PDF...';

    try {
        const resp = await fetch('/api/shift/report', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                operator: 'W. Angel',
                hours_back: 8,
            }),
        });
        if (!resp.ok) {
            let detail = '';
            try {
                const j = await resp.json();
                detail = j.detail || j.error || '';
            } catch (_) { /* noop */ }
            throw new Error(`HTTP ${resp.status}${detail ? ' - ' + detail : ''}`);
        }

        const blob = await resp.blob();
        if (blob.size < 100) {
            throw new Error('PDF came back empty - check backend logs');
        }
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        const ts = new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-');
        a.href = url;
        a.download = `a3semi_shift_report_${ts}.pdf`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        // Visual success feedback
        btn.innerHTML = '✓ Downloaded';
        setTimeout(() => { btn.innerHTML = orig; }, 2500);
    } catch (e) {
        console.error('Shift report error:', e);
        btn.innerHTML = '✗ Failed';
        setTimeout(() => {
            alert('Shift report failed:\n\n' + e.message
                + '\n\nCheck backend logs for details.');
            btn.innerHTML = orig;
        }, 100);
    } finally {
        btn.disabled = false;
    }
}

// ── Initial load: backfill 60 points + fetch latest for KPIs ───────
async function loadHistoricalTelemetry() {
    // 1. Populate chart from /api/telemetry?limit=60
    try {
        const resp = await fetch('/api/telemetry?limit=60');
        if (resp.ok) {
            const data = await resp.json();
            if (data.rows) {
                state.pueHistory = data.rows.reverse().map((r) => ({
                    ts: r.ts,
                    pue: r.pue,
                    temp: r.hall_temp_c,
                }));
                updatePueChart();
            }
        }
    } catch (e) {
        console.warn('historical telemetry load failed:', e);
    }
    // 2. Populate KPI cards from /api/telemetry/latest (single record)
    try {
        const resp = await fetch('/api/telemetry/latest');
        if (resp.ok) {
            const data = await resp.json();
            if (data.latest) handleTelemetry(data.latest);
        }
    } catch (e) {
        console.warn('latest telemetry fetch failed:', e);
    }
}

// ── Quick-action chips ─────────────────────────────────────────────
function setupQuickActions() {
    document.querySelectorAll('.chip').forEach((chip) => {
        if (chip._bound) return;
        chip._bound = true;
        chip.addEventListener('click', () => {
            const q = chip.dataset.query || chip.textContent.trim();
            els.agentInput().value = q;
            sendAgentQuery(q);
        });
    });
}

// ── Site Health Index (Day 4) ──────────────────────────────────────
async function fetchSiteHealth() {
    try {
        const resp = await fetch('/api/site/health');
        if (!resp.ok) throw new Error('SHI endpoint returned ' + resp.status);
        const d = await resp.json();
        renderSiteHealth(d);
    } catch (e) {
        console.warn('fetchSiteHealth failed:', e.message);
        const valEl = $('shi-value');
        if (valEl) valEl.textContent = '—';
    }
}

function renderSiteHealth(d) {
    const valEl = $('shi-value');
    const barEl = $('shi-bar');
    const dotEl = $('shi-dot');
    const weakestEl = $('shi-weakest');
    const cascadesEl = $('shi-cascades');

    const shi = d.site_health || 0;
    const pct = Math.round(shi * 100);

    if (valEl) valEl.textContent = shi.toFixed(2);
    if (barEl) {
        barEl.style.width = pct + '%';
        barEl.className = 'shi-bar ' + severityClass(d.overall_severity);
    }
    if (dotEl) dotEl.className = 'shi-dot ' + severityClass(d.overall_severity);
    if (weakestEl) weakestEl.textContent = d.weakest_module || '—';
    if (cascadesEl) cascadesEl.textContent = d.cascade_count;

    // Update per-module bars
    const mh = d.module_healths || {};
    const ms = d.module_severities || {};
    Object.keys(mh).forEach((mod) => {
        const fill = document.querySelector(`[data-mod-fill="${mod}"]`);
        const val = document.querySelector(`[data-mod-val="${mod}"]`);
        const h = mh[mod];
        if (fill) {
            fill.style.width = (h * 100) + '%';
            fill.className = 'shi-module-fill ' + severityClass(ms[mod] || 'ok');
        }
        if (val) val.textContent = h.toFixed(2);
    });

    // Push to capped 60-sample history so core/shi_sparkline.js can
    // render the trend. New array reference so the Proxy notifies.
    if (window.__epms) {
        const prev = window.__epms.getState('shiHistory') || [];
        const next = [...prev, {
            ts: Date.now(),
            shi: d.site_health || 0,
            severity: d.overall_severity || 'ok',
        }].slice(-60);
        window.__epms.setState('shiHistory', next);
    }
}

function severityClass(sev) {
    // Match the CSS classes shi-{ok|info|warning|critical}
    return 'sev-' + (sev || 'ok');
}

// ── Wire up UI ─────────────────────────────────────────────────────
function setupEventListeners() {
    const sendBtn = els.agentSend();
    const input = els.agentInput();
    const voiceBtn = els.agentVoice();
    const reportBtn = els.shiftReport();

    if (sendBtn && input) {
        sendBtn.addEventListener('click', () => {
            const q = input.value.trim();
            if (q) sendAgentQuery(q);
        });
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                const q = input.value.trim();
                if (q) sendAgentQuery(q);
            }
        });
    }

    if (voiceBtn) voiceBtn.addEventListener('click', toggleVoice);
    if (reportBtn) reportBtn.addEventListener('click', downloadShiftReport);

    const shiBtn = $('shi-refresh');
    if (shiBtn) shiBtn.addEventListener('click', fetchSiteHealth);
}

// ── Placeholder deep-link — a suggested query from a placeholder view
function _onOverviewAsk(e) {
    const q = e && e.detail && e.detail.query;
    if (!q) return;
    const input = els.agentInput();
    if (input) input.value = q;
    sendAgentQuery(q);
}

/** Public entry — called once from main.js at bootstrap. */
export function initOverviewView() {
    if (_initialized) return;
    if (!$('view-overview')) {
        console.warn('[overview] #view-overview not in DOM; view disabled.');
        return;
    }
    // One-time dashboard bootstrap (was app.js boot()).
    initChart();
    setupEventListeners();
    setupQuickActions();

    checkHealth();
    _intervals.push(setInterval(checkHealth, 15000));

    loadHistoricalTelemetry();
    subscribeTelemetry();

    refreshIncidents();
    _intervals.push(setInterval(refreshIncidents, 10000));

    fetchSiteHealth();
    _intervals.push(setInterval(fetchSiteHealth, 15000));

    // core/router.js owns the route; activate() refreshes SHI on entry.
    registerRoute('overview', { viewId: 'view-overview', activate: () => fetchSiteHealth() });
    document.addEventListener('epms:overview-ask', _onOverviewAsk);

    _initialized = true;
    console.log('[overview] view ready (landing dashboard — T2.1 Vector 4b ES module)');
}

// ─── Test surface ──────────────────────────────────────────────────
export const __overview_test__ = {
    updateKPIs,
    renderIncidents,
    renderSiteHealth,
    severityClass,
    addAdvisory,
    initOverviewView,
    setIncidents: (rows) => { state.incidents = rows; },
    reset: () => {
        _initialized = false;
        state.incidents = [];
        state.pueHistory = [];
        state.agentBuffer = '';
        state.agentSources = [];
        _intervals.forEach(clearInterval);
        _intervals = [];
    },
};
