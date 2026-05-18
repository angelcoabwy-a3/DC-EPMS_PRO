/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — Dashboard SPA
 * Features:
 *   - SSE agent streaming (token-by-token from /agent/stream)
 *   - SSE telemetry push (every 5s from /api/telemetry/stream)
 *   - Chart.js PUE trend (60 samples rolling)
 *   - Incident list (polled every 10s from /api/incidents)
 *   - Voice input (MediaRecorder → /api/voice/transcribe)
 *   - Shift report PDF download
 *   - Unified /api/health status
 * ════════════════════════════════════════════════════════════════ */

(function() {
    'use strict';

    // ── Boot banner (easy to verify in DevTools console) ───
    console.log(
        '%c DC-EPMS PRO v8.1.0 %c a3semi %c Co-Pilot Panel + CMMS',
        'background:#00B8D4;color:#0B0D10;font-weight:700;padding:2px 6px;border-radius:2px;',
        'background:#1C2128;color:#00B8D4;padding:2px 6px;',
        'color:#9AA0A6;'
    );

    const API_BASE = window.location.origin;

    // ── State ──────────────────────────────────────────────
    const state = {
        pueHistory:    [],
        latestTelemetry: null,
        incidents:     [],
        agentStreaming: false,
        agentBuffer:   '',
        agentSources:  [],
        mediaRecorder: null,
        isRecording:   false,
        healthCheckInterval: null,
        telemetrySource: null,
        incidentSource: null,
    };

    // ── DOM references ─────────────────────────────────────
    const $ = (id) => document.getElementById(id);
    const els = {
        pueValue:      () => $('kpi-pue'),
        tempValue:     () => $('kpi-temp'),
        loadValue:     () => $('kpi-load'),
        rackValue:     () => $('kpi-racks'),
        pueChart:      () => $('pueChart'),
        agentInput:    () => $('agent-input'),
        agentResponse: () => $('agent-response'),
        agentSend:     () => $('agent-send'),
        agentVoice:    () => $('agent-voice'),
        agentModel:    () => $('agent-model'),
        incidentList:  () => $('incident-list'),
        healthPg:      () => $('health-pg'),
        healthRag:     () => $('health-rag'),
        healthGemma:   () => $('health-gemma'),
        healthGpu:     () => $('health-gpu'),
        advisoryZone:  () => $('advisory-zone'),
        shiftReport:   () => $('btn-shift-report'),
    };

    // ── Utilities ──────────────────────────────────────────
    const fmt = {
        pue: (v)      => v == null ? '—' : v.toFixed(3),
        temp: (v)     => v == null ? '—' : v.toFixed(1) + '°C',
        load: (v)     => v == null ? '—' : Math.round(v).toLocaleString() + ' kW',
        int: (v)      => v == null ? '—' : Math.round(v).toLocaleString(),
        time: (iso)   => {
            if (!iso) return '—';
            try { return new Date(iso).toLocaleTimeString('en-CA', { hour12: false }); }
            catch (e) { return iso.slice(11, 19); }
        },
    };

    function escapeHtml(s) {
        const div = document.createElement('div');
        div.textContent = s || '';
        return div.innerHTML;
    }

    // ── Health check (every 15s) ───────────────────────────
    async function checkHealth() {
        try {
            const resp = await fetch(`${API_BASE}/api/health`);
            if (!resp.ok) throw new Error('health endpoint down');
            const h = await resp.json();

            updatePill(els.healthPg(),    h.postgres?.status === 'up', 'PostgreSQL');
            updatePill(els.healthRag(),   h.rag?.status === 'up',       `RAG (${h.rag?.docs || 0})`);
            updatePill(els.healthGemma(), h.gemma?.status === 'up',     'Gemma 4');

            const gpu = h.gpu || {};
            const gpuUp = gpu.source === 'nvml';
            const gpuLbl = gpuUp
                ? `GPU ${gpu.sm_pct || 0}% · ${gpu.temp_c || 0}°C`
                : 'GPU offline';
            updatePill(els.healthGpu(), gpuUp, gpuLbl);
        } catch (e) {
            console.warn('health check failed:', e);
            [els.healthPg(), els.healthRag(), els.healthGemma(), els.healthGpu()]
                .forEach(el => el && updatePill(el, false, el.dataset.label || 'offline'));
        }
    }

    function updatePill(el, isUp, label) {
        if (!el) return;
        el.classList.toggle('up',   isUp);
        el.classList.toggle('down', !isUp);
        const lblEl = el.querySelector('.lbl');
        if (lblEl) lblEl.textContent = label;
    }

    // ── SSE: Telemetry stream ──────────────────────────────
    // Sprint 5.5 hybrid pivot Bite A2: delegate SSE ownership to
    // frontend/assets/js/core/telemetry_engine.js when the new module
    // is loaded. Legacy path retained as fallback for browsers without
    // ES module support OR when window.__epms.useNewEngine === false.
    //
    // Flow when new engine is ON:
    //   telemetry_engine._onMessage  ->  setState('latestTelemetry', point)
    //   ->  Proxy notify  ->  this subscriber  ->  handleTelemetry(point)
    //
    // The legacy fallback below is byte-identical to the pre-Bite-A2
    // code so behaviour is unchanged when the feature flag is off.
    function startTelemetryStream() {
        if (window.__epms && window.__epms.useNewEngine !== false) {
            // New path: subscribe to the reactive store; SSE is owned
            // by telemetry_engine.js and was started from main.js.
            window.__epms.subscribe('latestTelemetry', (point) => {
                if (point) handleTelemetry(point);
            });
            return;
        }

        // Legacy fallback (feature flag off or module load failed)
        if (state.telemetrySource) state.telemetrySource.close();
        state.telemetrySource = new EventSource(`${API_BASE}/api/telemetry/stream`);

        state.telemetrySource.onmessage = (e) => {
            try {
                const data = JSON.parse(e.data);
                if (window.__epms) window.__epms.setState('lastTelemetryAtMs', performance.now());
                if (data.latest) handleTelemetry(data.latest);
            } catch (err) {
                console.warn('SSE telemetry parse error:', err);
            }
        };

        state.telemetrySource.onerror = () => {
            console.warn('telemetry SSE disconnected, reconnecting in 5s...');
            if (state.telemetrySource) {
                state.telemetrySource.close();
                state.telemetrySource = null;
            }
            setTimeout(startTelemetryStream, 5000);
        };
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
                p.pue > 1.40 ? 'crit' :
                p.pue > 1.30 ? 'warn' : 'ok'
            );
        }
        const tempEl = els.tempValue();
        if (tempEl) {
            tempEl.textContent = fmt.temp(p.hall_temp_c);
            tempEl.className = 'value ' + (
                p.hall_temp_c >= 35 ? 'crit' :
                p.hall_temp_c >= 30 ? 'warn' : 'ok'
            );
        }
        const loadEl = els.loadValue();
        if (loadEl) loadEl.textContent = fmt.load(p.it_load_kw);

        const rackEl = els.rackValue();
        if (rackEl) rackEl.textContent = `${p.rack_count || 118} × ${p.rack_tdp_kw || 142}kW`;
    }

    // ── Advisories ─────────────────────────────────────────
    function checkAdvisories(point) {
        const zone = els.advisoryZone();
        if (!zone) return;
        zone.innerHTML = '';

        if (point.pue > 1.40) {
            addAdvisory(zone, 'crit', 'PUE efficiency alert',
                `Current PUE ${point.pue.toFixed(3)} exceeds A-Cubed Semiconductor threshold (1.40). ` +
                `Immediate check recommended: chiller redundancy (N-1), DLC flow, hot-aisle containment.`);
        } else if (point.pue > 1.30) {
            addAdvisory(zone, 'warn', 'PUE trending upward',
                `PUE ${point.pue.toFixed(3)} above target 1.30. Monitor next 15 minutes for sustained trend.`);
        }

        if (point.hall_temp_c >= 32) {
            addAdvisory(zone, 'crit', 'ASHRAE A2 thermal excursion',
                `Hall temperature ${point.hall_temp_c.toFixed(1)}°C approaching A2 limit (35°C). ` +
                `Verify cooling delivery and IT load correlation.`);
        }
    }

    function addAdvisory(zone, level, hdr, body) {
        const el = document.createElement('div');
        el.className = 'advisory ' + level;
        el.innerHTML = `<div class="hdr">${escapeHtml(hdr)}</div>
                        <div>${escapeHtml(body)}</div>`;
        zone.appendChild(el);
    }

    // ── Chart.js: PUE trend ────────────────────────────────
    let pueChart = null;
    function initChart() {
        const canvas = els.pueChart();
        if (!canvas || !window.Chart) return;
        const ctx = canvas.getContext('2d');

        pueChart = new Chart(ctx, {
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
                            label: (ctx) => `PUE: ${ctx.parsed.y.toFixed(3)}`,
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
        pueChart.data.datasets[0].data = points.map(p => p.pue);
        pueChart.update('none');
    }

    // ── Agent rendering helpers (sources + markdown-lite) ──
    const TIER_COLORS = {
        1: '#E53935',   // red
        2: '#FB8C00',   // orange
        3: '#00B8D4',   // cyan
        4: '#4CAF50',   // green
    };

    function renderSourcesBlock() {
        if (!state.agentSources || state.agentSources.length === 0) return '';
        const chips = state.agentSources.map(s => {
            const tier = s.tier || '?';
            const tierClass = `tier-${tier}`;
            const bgColor = TIER_COLORS[tier] || '#666';
            const boost = s.boost > 0 ? ` boost=+${s.boost.toFixed(2)}` : '';
            const title = [
                `Doc: ${s.doc_id}`,
                `Tier: ${tier} (${s.priority || 'n/a'})`,
                `Standard: ${s.standard || 'n/a'}`,
                `Score: ${s.score.toFixed(3)}${boost}`,
                ``,
                s.snippet,
            ].join('\n');
            // Inline styles as fallback if CSS fails to load
            return `<span class="src-chip ${tierClass}" title="${escapeHtml(title)}" style="display:inline-flex;align-items:center;gap:5px;padding:3px 8px;margin:2px;font-size:10px;font-family:monospace;border-radius:3px;background:#1C2128;border:1px solid #2A3038;">
                <span class="src-tier" style="font-weight:700;font-size:9px;padding:1px 5px;border-radius:2px;background:${bgColor};color:#fff;">T${tier}</span>
                <span class="src-id" style="color:#E8EAED;">${escapeHtml(s.doc_id)}</span>
            </span>`;
        }).join('');
        return `<div class="agent-sources" style="margin-bottom:10px;padding:8px 10px;background:#14181D;border-left:2px solid #00B8D4;border-radius:4px;">
            <div class="agent-sources-lbl" style="font-size:10px;color:#9AA0A6;text-transform:uppercase;letter-spacing:0.6px;margin-bottom:6px;">Grounded in ${state.agentSources.length} source${state.agentSources.length === 1 ? '' : 's'}:</div>
            <div class="agent-sources-chips" style="display:flex;flex-wrap:wrap;gap:2px;">${chips}</div>
        </div>`;
    }

    function renderAgentStreaming(el) {
        const sources = renderSourcesBlock();
        const body = escapeHtml(state.agentBuffer) +
            '<span class="streaming-cursor"></span>';
        el.innerHTML = sources + '<div class="agent-body" style="white-space:pre-wrap;word-wrap:break-word;font-size:12px;line-height:1.55;">' + body + '</div>';
    }

    function renderAgentFinal(el) {
        const sources = renderSourcesBlock();
        el.innerHTML = sources +
            '<div class="agent-body" style="white-space:pre-wrap;word-wrap:break-word;font-size:12px;line-height:1.55;">' + escapeHtml(state.agentBuffer) + '</div>';
    }

    // ── SSE: Agent streaming ───────────────────────────────
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
            const resp = await fetch(`${API_BASE}/agent/stream`, {
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
                        // NEW: handle RAG sources emitted before tokens
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
                            respEl.innerHTML = `<span style="color:var(--crit)">Error: ${escapeHtml(obj.error)}</span>`;
                        }
                    } catch (e) {
                        console.warn('parse agent chunk:', e);
                    }
                }
            }
            renderAgentFinal(respEl);
        } catch (e) {
            respEl.innerHTML = `<span style="color:var(--crit)">Error: ${escapeHtml(e.message)}</span>`;
        } finally {
            state.agentStreaming = false;
            if (sendBtn) sendBtn.disabled = false;
        }
    }

    // ── Incident polling ──────────────────────────────────
    async function refreshIncidents() {
        try {
            const resp = await fetch(`${API_BASE}/api/incidents?limit=20`);
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
        list.innerHTML = state.incidents.map(inc => {
            const cls = severityClass(inc.severity);
            return `<div class="incident-row ${cls}">
                <span class="sev" style="color:var(--${cls === 'info' ? 'accent' : cls})">${escapeHtml((inc.severity || 'info').slice(0, 4).toUpperCase())}</span>
                <span class="ts">${fmt.time(inc.ts)}</span>
                <span class="title" title="${escapeHtml(inc.title)}">${escapeHtml(inc.title)}</span>
                <span class="status">${escapeHtml(inc.status)}</span>
            </div>`;
        }).join('');
    }

    // ── Voice input (Riva-ready) ──────────────────────────
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
                stream.getTracks().forEach(t => t.stop());
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
            const resp = await fetch(`${API_BASE}/api/voice/transcribe`, {
                method: 'POST',
                body: fd,
            });
            const data = await resp.json();
            if (data.transcript) {
                els.agentInput().value = data.transcript;
                sendAgentQuery(data.transcript);
            } else if (data.status === 'not_implemented') {
                alert('Voice ready: Riva ASR integration pending (WSL2). ' +
                      'Configure RIVA_GRPC_URL in .env.');
            }
        } catch (e) {
            alert('Voice upload failed: ' + e.message);
        }
    }

    // ── Shift Report download ──────────────────────────────
    async function downloadShiftReport() {
        const btn = els.shiftReport();
        if (!btn) return;
        btn.disabled = true;
        const orig = btn.innerHTML;
        btn.innerHTML = '<span class="loading"></span>Generating PDF...';

        try {
            const resp = await fetch(`${API_BASE}/api/shift/report`, {
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
                } catch (_) {}
                throw new Error(`HTTP ${resp.status}${detail ? ' - ' + detail : ''}`);
            }

            const blob = await resp.blob();
            if (blob.size < 100) {
                throw new Error('PDF came back empty - check backend logs');
            }
            const url  = URL.createObjectURL(blob);
            const a    = document.createElement('a');
            const ts   = new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-');
            a.href     = url;
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
                alert('Shift report failed:\n\n' + e.message +
                      '\n\nCheck backend logs for details.');
                btn.innerHTML = orig;
            }, 100);
        } finally {
            btn.disabled = false;
        }
    }

    // ── Initial load: backfill 60 points + fetch latest for KPIs
    async function loadHistoricalTelemetry() {
        // 1. Populate chart from /api/telemetry?limit=60
        try {
            const resp = await fetch(`${API_BASE}/api/telemetry?limit=60`);
            if (resp.ok) {
                const data = await resp.json();
                if (data.rows) {
                    state.pueHistory = data.rows.reverse().map(r => ({
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
            const resp = await fetch(`${API_BASE}/api/telemetry/latest`);
            if (resp.ok) {
                const data = await resp.json();
                if (data.latest) handleTelemetry(data.latest);
            }
        } catch (e) {
            console.warn('latest telemetry fetch failed:', e);
        }
    }

    // ── Quick-action chips ─────────────────────────────────
    function setupQuickActions() {
        document.querySelectorAll('.chip').forEach(chip => {
            chip.addEventListener('click', () => {
                const q = chip.dataset.query || chip.textContent.trim();
                els.agentInput().value = q;
                sendAgentQuery(q);
            });
        });
    }

    // ================================================================
    //  Router + module placeholder config
    // ================================================================
    const MODULES = {
        overview: null, // renders view-overview directly
        // v0.10.12: declared so navigateTo doesn't fall through to overview
        // before the ES-module LOTO-pattern in views/maintenance.js fires.
        // The legacy router now shows view-maintenance directly; the
        // ES module's MutationObserver picks up the un-hide and refreshes.
        maintenance: {
            kind:  'maintenance',
            title: 'Maintenance — CMMS',
            sub:   'Asset registry · Work-order backlog · CET approvals',
        },
        scenarios: {
            kind: 'scenarios',
            title: 'Failure scenario simulator',
            sub:   '10 critical scenarios with ODE-based 15-minute projections',
        },
        incidents: {
            kind: 'incidents',
            title: 'Incidents audit log',
            sub:   'All events from PostgreSQL - most recent first',
        },
        power: {
            kind: 'power',
            title: 'Power & UPS — Single-Line Diagram',
            sub:   '2N · UPS Galaxy VX · RPP · Starline busway',
        },
        cooling: {
            kind: 'cooling',
            title: 'Cooling (DLC) — P&ID Live View',
            sub:   'DLC loop · Heat rejection · Power path with 2N failover',
        },
        mops: {
            kind: 'mops',
            title: 'MOPs / SOPs / EOPs Library',
            sub:   'Indexed procedures from the corpus + LLM generator for new MOPs',
        },
        morpheus: {
            kind: 'placeholder',
            title: 'Morpheus OT Security',
            sub:   'NVIDIA Morpheus - IEC 62443 cyber-physical correlation',
            icon:  '\u2302', // house (security)
            desc:  'NVIDIA Morpheus AI Sentinel monitors Modbus TCP and DNP3 traffic across IEC 62443 zones SL-0 to SL-3. Detects cyber-physical anomalies and triggers SOAR isolation on confidence >85% per SR 5.2.',
            chips: [
                'Explain IEC 62443 SL-2 zone isolation requirements.',
                'What Morpheus baseline Modbus log rate is normal?',
                'Walk me through SOAR isolation on chiller OT anomaly.',
            ],
        },
        gemini: {
            kind: 'placeholder',
            title: 'Gemini ER 1.6 Robot',
            sub:   'Autonomous inspection - thermographic imaging, moisture detection',
            icon:  '\u26AB', // circle (robot)
            desc:  'NVIDIA Gemini ER 1.6 inspection robot. Performs scheduled thermographic rack scans, moisture detection on raised floor, cable management verification. Integrated via ROS2 with event-driven incident creation.',
            chips: [
                'What anomalies can Gemini ER 1.6 detect on Blackwell racks?',
                'Summarize robot IR thermography procedure for PDU inspection.',
                'How does ROS2 integration publish incidents to PostgreSQL?',
            ],
        },
        omniverse: {
            kind: 'placeholder',
            title: 'NVIDIA Omniverse',
            sub:   'Digital twin - physics-based facility visualization',
            icon:  '\u25CE', // bullseye
            desc:  'NVIDIA Omniverse digital twin of A3-Alpha Toronto Area. Live-link to real-time telemetry via USD / Kit. Visualizes thermal flow, power distribution, and fault propagation scenarios.',
            chips: [
                'Explain Omniverse Live-Link integration for EPMS.',
                'How does USD represent data center thermal zones?',
                'Walk me through a chillerFail scenario in the digital twin.',
            ],
        },
        topology: {
            kind: 'topology',
            title: 'Facility Topology (HLD/LLD)',
            sub:   'Live system-of-systems map with physics-driven node colouring',        },
        bms: {
            kind: 'bms',
            title: 'BMS Connector',
            sub:   'BACnet/Modbus tag namespace — Niagara/EBI/EcoStruxure compatible',
        },
        site_topology: {
            kind: 'site_topology',
            title: 'Site Topology',
            sub:   'Physical hierarchy and 2N power chain analysis',
        },
        copilot: {
            kind: 'copilot',
            title: 'Facility Co-Pilot',
            sub:   'Tool-using LLM agent · Gemma 4 e2b · HITL drafts · NIST SP 800-82 audit',
        },
    };

    // ── Site Health Index (Day 4) ─────────────────────────
    async function fetchSiteHealth() {
        try {
            const resp = await fetch(`${API_BASE}/api/site/health`);
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
            // Color by health
            barEl.className = 'shi-bar ' + severityClass(d.overall_severity);
        }
        if (dotEl) dotEl.className = 'shi-dot ' + severityClass(d.overall_severity);
        if (weakestEl) weakestEl.textContent = d.weakest_module || '—';
        if (cascadesEl) cascadesEl.textContent = d.cascade_count;

        // Update per-module bars
        const mh = d.module_healths || {};
        const ms = d.module_severities || {};
        Object.keys(mh).forEach(mod => {
            const fill = document.querySelector(`[data-mod-fill="${mod}"]`);
            const val = document.querySelector(`[data-mod-val="${mod}"]`);
            const h = mh[mod];
            if (fill) {
                fill.style.width = (h * 100) + '%';
                fill.className = 'shi-module-fill ' + severityClass(ms[mod] || 'ok');
            }
            if (val) val.textContent = h.toFixed(2);
        });

        // Sprint 5.5 hybrid Bite B: push to capped 60-sample history so
        // core/shi_sparkline.js can render the trend. New array reference
        // (not in-place mutation) so the Proxy notifies subscribers.
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

    // ── Scenarios view (Day 4) ────────────────────────────
    // MIGRATED (ROADMAP V11 T2.1): the failure-scenario simulator now
    // lives in views/scenarios.js (ES module) + services/api.js. Route
    // ownership moved to core/router.js; this IIFE no longer renders it.

    // MIGRATED (ROADMAP V11 T2.1): the MOPs/SOPs/EOPs library now
    // lives in views/mops.js (ES module) + services/api.js. Route
    // ownership moved to core/router.js; this IIFE no longer renders it.

    // ── Topology view (Day 6) ─────────────────────────────
    let topologyState = null;
    let topologyRefreshInterval = null;
    let currentTopologyTab = 'hld';
    // Day 8: state for sparkline + emergency simulation mode
    const ctSparklineHistory = { wb: [], amb: [], maxPoints: 60 };
    let emergencySimMode = false;

    async function renderTopologyView() {
        // Bind tab handlers (idempotent)
        document.querySelectorAll('.topo-tab').forEach(tab => {
            if (!tab._bound) {
                tab._bound = true;
                tab.addEventListener('click', () => {
                    document.querySelectorAll('.topo-tab').forEach(t => t.classList.remove('active'));
                    tab.classList.add('active');
                    currentTopologyTab = tab.dataset.tab;
                    document.getElementById('topo-canvas-hld').hidden = (currentTopologyTab !== 'hld');
                    document.getElementById('topo-canvas-lld').hidden = (currentTopologyTab !== 'lld');
                    if (currentTopologyTab === 'lld' && topologyState) {
                        renderLLDRacks(topologyState.lld_racks || []);
                    }
                });
            }
        });

        // Refresh button
        const refreshBtn = $('topo-refresh');
        if (refreshBtn && !refreshBtn._bound) {
            refreshBtn._bound = true;
            refreshBtn.addEventListener('click', fetchTopologyState);
        }

        // Detail close
        const closeBtn = $('topo-detail-close');
        if (closeBtn && !closeBtn._bound) {
            closeBtn._bound = true;
            closeBtn.addEventListener('click', () => {
                $('topo-detail-panel').hidden = true;
            });
        }

        // Bind node click handlers (idempotent on each render)
        document.querySelectorAll('.topo-node[data-node]').forEach(node => {
            if (!node._bound) {
                node._bound = true;
                node.addEventListener('click', () => {
                    if (emergencySimMode) {
                        runEmergencyWhatIf(node.dataset.node);
                    } else {
                        showTopologyNodeDetail(node.dataset.node);
                    }
                });
            }
        });

        // Bind Emergency Simulation toggle
        const emBtn = $('emergency-sim-btn');
        if (emBtn && !emBtn._bound) {
            emBtn._bound = true;
            emBtn.addEventListener('click', () => {
                emergencySimMode = !emergencySimMode;
                if (emergencySimMode) {
                    emBtn.classList.add('active');
                    emBtn.textContent = '🚨 SIM ACTIVE — click any node to fail';
                    document.querySelectorAll('.topo-node').forEach(n => n.classList.add('sim-mode'));
                } else {
                    emBtn.classList.remove('active');
                    emBtn.textContent = '🚨 Emergency Simulation';
                    document.querySelectorAll('.topo-node').forEach(n => n.classList.remove('sim-mode'));
                    // Clear any what-if banner
                    const banner = $('whatif-banner');
                    if (banner) banner.remove();
                }
            });
        }

        // Initial fetch + start auto-refresh
        await fetchTopologyState();
        if (!topologyRefreshInterval) {
            topologyRefreshInterval = setInterval(fetchTopologyState, 8000);
        }
    }

    async function runEmergencyWhatIf(nodeId) {
        try {
            const resp = await fetch(`${API_BASE}/api/topology/whatif`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ failed_node: nodeId }),
            });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const d = await resp.json();
            showWhatIfBanner(d);
        } catch (e) {
            console.error('What-If failed:', e);
        }
    }

    function showWhatIfBanner(d) {
        // Remove any prior banner
        const old = $('whatif-banner');
        if (old) old.remove();

        const banner = document.createElement('div');
        banner.id = 'whatif-banner';
        banner.className = 'whatif-banner';
        const deltaSign = d.shi_delta >= 0 ? '+' : '';
        banner.innerHTML = `
            <div class="whatif-hdr">
                <span class="whatif-title">⚡ WHAT-IF SIMULATION</span>
                <button class="whatif-close" onclick="document.getElementById('whatif-banner').remove()">×</button>
            </div>
            <div class="whatif-body">
                <div class="whatif-row">
                    <span class="whatif-lbl">Failed component:</span>
                    <span class="whatif-val whatif-fail">${escapeHtml(d.failed_node)}</span>
                </div>
                <div class="whatif-row">
                    <span class="whatif-lbl">Description:</span>
                    <span class="whatif-val">${escapeHtml(d.description)}</span>
                </div>
                <div class="whatif-row">
                    <span class="whatif-lbl">SHI:</span>
                    <span class="whatif-val">${d.baseline.site_health.toFixed(2)} → <span class="whatif-after">${d.degraded.site_health.toFixed(2)}</span> (${deltaSign}${d.shi_delta.toFixed(2)})</span>
                </div>
                <div class="whatif-row">
                    <span class="whatif-lbl">Redundancy:</span>
                    <span class="whatif-val">${escapeHtml(d.redundancy_after_failure)}</span>
                </div>
                <div class="whatif-row">
                    <span class="whatif-lbl">Weakest module:</span>
                    <span class="whatif-val">${escapeHtml(d.degraded.weakest)}</span>
                </div>
                <div class="whatif-assessment">
                    <strong>Physics-engine assessment:</strong> ${escapeHtml(d.physics_assessment)}
                </div>
            </div>
        `;
        const view = $('view-topology');
        if (view) view.insertBefore(banner, view.firstChild.nextSibling);
    }

    async function fetchTopologyState() {
        try {
            const resp = await fetch(`${API_BASE}/api/topology/state`);
            if (!resp.ok) throw new Error('failed: ' + resp.status);
            topologyState = await resp.json();
            applyTopologyState(topologyState);
        } catch (e) {
            console.warn('fetchTopologyState:', e.message);
        }
    }

    // 1h history of WB + ambient for sparkline (declared at top of scope)

    function applyTopologyState(data) {
        if (!data) return;

        // Header
        const shiEl = $('topo-shi');
        const wkEl = $('topo-weakest');
        const redEl = $('topo-redundancy');
        if (shiEl) shiEl.textContent = (data.site_health || 0).toFixed(2);
        if (wkEl) wkEl.textContent = data.weakest_module || '—';
        if (redEl) {
            const mode = data.redundancy_mode || '2N';
            redEl.textContent = mode;
            redEl.className = 'topo-redundancy-badge mode-' + mode.replace('+', 'plus').replace(/\s/g, '-');
        }

        // Per-node colouring (HLD)
        const nodes = data.hld_nodes || {};
        Object.entries(nodes).forEach(([nodeId, nodeData]) => {
            const nodeEl = document.querySelector(`.topo-node[data-node="${nodeId}"]`);
            if (!nodeEl) return;
            const rect = nodeEl.querySelector('rect.topo-node-rect') || nodeEl.querySelector('rect');
            if (rect) {
                rect.setAttribute('class', 'topo-node-rect sev-' + nodeData.severity);
            }
            applyNodeMetrics(nodeId, nodeData);
            applyNodeBadge(nodeId, nodeData);
        });

        // Cooling tower sparkline + delta-T pulse
        const ctNode = nodes.cooling_tower;
        if (ctNode) {
            updateSparkline(ctNode.metrics || {});
            updateDeltaTRisk(ctNode.metrics || {});
        }

        // LLD racks
        if (currentTopologyTab === 'lld') {
            renderLLDRacks(data.lld_racks || []);
        }

        // AI Mission Control insights
        renderMissionControlInsights(data);
    }

    function applyNodeBadge(nodeId, nodeData) {
        // Find badge for this node and update ACTIVE/STANDBY based on nodeData.metrics.active
        const badge = document.querySelector(`[data-badge="${nodeId}"]`);
        if (!badge) return;
        const m = nodeData.metrics || {};
        const isActive = m.active !== undefined ? m.active : true;
        const txt = badge.querySelector('text');
        const rect = badge.querySelector('rect');
        if (isActive) {
            badge.setAttribute('class', 'topo-badge topo-badge-active');
            if (txt) txt.textContent = 'ACTIVE';
        } else {
            badge.setAttribute('class', 'topo-badge topo-badge-standby');
            if (txt) txt.textContent = 'STANDBY';
        }
    }

    function applyNodeMetrics(nodeId, nodeData) {
        const m = nodeData.metrics || {};
        const updates = {
            // Dual utility (Day 8)
            'utility_north-kw':   () => fmt0(m.kw) + ' kW',
            'utility_south-kw':   () => fmt0(m.kw) + ' kW',
            // Old single utility (kept for backward compat)
            'utility-kw':         () => fmt0(m.kw) + ' kW',
            'xfmr_a-winding':     () => fmt1(m.winding_c) + '°C',
            'xfmr_b-winding':     () => fmt1(m.winding_c) + '°C',
            'ups_a-soc':          () => 'SOC ' + Math.round((m.soc || 0) * 100) + '%',
            'ups_b-soc':          () => 'SOC ' + Math.round((m.soc || 0) * 100) + '%',
            'hall_1-inlet':       () => fmt1(m.inlet_c) + ' °C',
            'hall_1-load':        () => fmt0(m.load_kw) + ' kW',
            'hall_2-inlet':       () => fmt1(m.inlet_c) + ' °C',
            'hall_2-load':        () => fmt0(m.load_kw) + ' kW',
            'hall_3-inlet':       () => fmt1(m.inlet_c) + ' °C',
            'hall_3-load':        () => fmt0(m.load_kw) + ' kW',
            'cdu_a-q':            () => fmt0(m.q_kw) + ' kW',
            'cdu_b-q':            () => fmt0(m.q_kw) + ' kW',
            'chiller_1-cop':      () => 'COP ' + fmt1(m.cop),
            'chiller_2-cop':      () => 'COP ' + fmt1(m.cop),
            'cooling_tower-wb':   () => 'WB ' + fmt1(m.wb_c) + '°C',
            'cooling_tower-ecwt': () => 'ECWT ' + fmt1(m.ecwt_c) + '°C',
        };
        Object.keys(updates).forEach(metricId => {
            if (metricId.startsWith(nodeId + '-')) {
                const el = document.querySelector(`[data-metric="${metricId}"]`);
                if (el) el.textContent = updates[metricId]();
            }
        });
    }

    function updateSparkline(metrics) {
        const wb = metrics.wb_c;
        // Use ECWT - 4 as ambient proxy if not directly available
        const amb = metrics.ecwt_c ? metrics.ecwt_c - 4 : null;
        if (typeof wb !== 'number') return;

        ctSparklineHistory.wb.push(wb);
        if (typeof amb === 'number') ctSparklineHistory.amb.push(amb);
        // Keep last N points (60 = ~1h at 1 min refresh)
        if (ctSparklineHistory.wb.length > ctSparklineHistory.maxPoints) {
            ctSparklineHistory.wb.shift();
        }
        if (ctSparklineHistory.amb.length > ctSparklineHistory.maxPoints) {
            ctSparklineHistory.amb.shift();
        }

        const wbLine = $('ct-sparkline-wb');
        const ambLine = $('ct-sparkline-amb');
        if (!wbLine) return;

        // Find min/max for scaling across both series
        const allVals = ctSparklineHistory.wb.concat(ctSparklineHistory.amb);
        if (allVals.length < 2) return;
        const vmin = Math.min(...allVals);
        const vmax = Math.max(...allVals);
        const range = Math.max(vmax - vmin, 1.0);

        // Sparkline canvas: 140w x 30h, with 12px top padding
        const W = 140, H = 18, top = 11;
        const toPoints = (arr) => {
            return arr.map((v, i) => {
                const x = (i / Math.max(arr.length - 1, 1)) * W;
                const y = top + H - ((v - vmin) / range) * H;
                return `${x.toFixed(1)},${y.toFixed(1)}`;
            }).join(' ');
        };
        wbLine.setAttribute('points', toPoints(ctSparklineHistory.wb));
        if (ambLine) ambLine.setAttribute('points', toPoints(ctSparklineHistory.amb));
    }

    function updateDeltaTRisk(metrics) {
        const wb = metrics.wb_c;
        const ecwt = metrics.ecwt_c;
        const warnEl = $('ct-deltat-warn');
        const rectEl = $('cooling-tower-rect');
        if (typeof wb !== 'number' || typeof ecwt !== 'number') return;

        const deltaT = ecwt - wb;
        // Cooling tower approach typically 3-6 K. <2 K = trouble.
        if (deltaT < 2.5) {
            if (warnEl) warnEl.textContent = '⚠ Low ΔT Risk';
            if (rectEl) rectEl.classList.add('low-deltat-pulse');
        } else {
            if (warnEl) warnEl.textContent = '';
            if (rectEl) rectEl.classList.remove('low-deltat-pulse');
        }
    }

    function renderMissionControlInsights(data) {
        const insightsEl = $('ai-mc-insights');
        const statusEl = $('ai-mc-status');
        if (!insightsEl) return;

        const insights = generateInsights(data);
        if (statusEl) {
            statusEl.textContent = insights.length === 0
                ? 'all systems nominal'
                : insights.length + ' insight' + (insights.length === 1 ? '' : 's') + ' detected';
        }
        if (insights.length === 0) {
            insightsEl.innerHTML = `
                <div class="ai-mc-insight ai-mc-ok">
                    <span class="ai-mc-icon">✓</span>
                    <span>All physics-validated metrics within design envelope. Site operating in ${data.redundancy_mode || '2N'} mode at SHI ${(data.site_health || 1).toFixed(2)}.</span>
                </div>`;
            return;
        }
        insightsEl.innerHTML = insights.map(i =>
            `<div class="ai-mc-insight ai-mc-${i.severity}">
                <span class="ai-mc-icon">${i.icon}</span>
                <span>${escapeHtml(i.text)}</span>
            </div>`
        ).join('');
    }

    function generateInsights(data) {
        // Rule-based insights derived from topology state. Real production
        // would query the agent_engine; this is a deterministic heuristic
        // layer that fires immediately on telemetry change.
        const out = [];
        const nodes = data.hld_nodes || {};

        // Redundancy mode warning
        if (data.redundancy_mode === 'N') {
            out.push({
                severity: 'critical',
                icon: '🚨',
                text: 'Wilmer, the site is operating NON-REDUNDANT (N). A single additional component failure would cause an outage. Trigger EOP-COOL-003 if heat-rejection related.',
            });
        } else if (data.redundancy_mode === 'N+1') {
            out.push({
                severity: 'warning',
                icon: '⚠',
                text: 'Site degraded to N+1. One redundant path is at warning state. Recommend root-cause investigation within the next 30 minutes.',
            });
        }

        // Transformer winding analysis
        const xfmrA = nodes.xfmr_a;
        const xfmrB = nodes.xfmr_b;
        if (xfmrA && xfmrB) {
            const ta = xfmrA.metrics?.winding_c || 0;
            const tb = xfmrB.metrics?.winding_c || 0;
            if (ta > 110 || tb > 110) {
                out.push({
                    severity: 'warning',
                    icon: '🔥',
                    text: `Transformer winding above 110°C detected (XFMR A: ${ta.toFixed(1)}°C, XFMR B: ${tb.toFixed(1)}°C). IEEE C57.12 rated hottest-spot is 95-110°C. Suggest checking harmonic loading.`,
                });
            } else if (Math.abs(ta - tb) > 5) {
                out.push({
                    severity: 'info',
                    icon: 'ℹ',
                    text: `Transformer thermal imbalance detected: XFMR A ${ta.toFixed(1)}°C vs XFMR B ${tb.toFixed(1)}°C (Δ ${Math.abs(ta-tb).toFixed(1)}°C). Check for asymmetric load distribution.`,
                });
            }
        }

        // GPU thermal headroom
        const hall1 = nodes.hall_1;
        if (hall1?.metrics?.inlet_c && hall1.metrics.inlet_c > 25) {
            out.push({
                severity: 'warning',
                icon: '🌡',
                text: `Hall inlet at ${hall1.metrics.inlet_c.toFixed(1)}°C (ASHRAE A2 max is 35°C, recommended is 18-27°C). Monitor GPU Tj and consider increasing CDU flow.`,
            });
        }

        // Cooling tower delta-T
        const ct = nodes.cooling_tower;
        if (ct?.metrics?.wb_c && ct?.metrics?.ecwt_c) {
            const dt = ct.metrics.ecwt_c - ct.metrics.wb_c;
            if (dt < 2.5) {
                out.push({
                    severity: 'critical',
                    icon: '❄',
                    text: `Cooling tower approach is ${dt.toFixed(1)}K (design 3-6 K). WB ${ct.metrics.wb_c.toFixed(1)}°C is approaching ECWT ${ct.metrics.ecwt_c.toFixed(1)}°C — heat rejection capacity is at limit.`,
                });
            }
        }

        // Battery SOC
        const upsA = nodes.ups_a;
        if (upsA?.metrics?.soc !== undefined && upsA.metrics.soc < 0.85) {
            out.push({
                severity: 'warning',
                icon: '🔋',
                text: `UPS A battery SOC at ${(upsA.metrics.soc*100).toFixed(0)}% (should be ≥ 90% in standby). Recheck per IEEE 1188 quarterly schedule.`,
            });
        }

        return out;
    }

    function fmt0(v) { return (v == null) ? '—' : Math.round(v).toLocaleString(); }
    function fmt1(v) { return (v == null) ? '—' : Number(v).toFixed(1); }

    function renderLLDRacks(racks) {
        const group = document.getElementById('lld-rack-group');
        if (!group || racks.length === 0) return;

        // Layout: 2 rows of 6 racks
        const rackW = 140, rackH = 160, gapX = 22, gapY = 30;
        let html = '';
        racks.forEach((r, i) => {
            const row = Math.floor(i / 6);
            const col = i % 6;
            const x = col * (rackW + gapX);
            const y = row * (rackH + gapY);

            const sevClass = 'sev-' + r.severity;
            // Header
            html += `<g class="lld-rack" transform="translate(${x}, ${y})">
                <rect width="${rackW}" height="${rackH}" rx="3" class="lld-rack-rect ${sevClass}"/>
                <text x="${rackW/2}" y="20" class="lld-rack-id">${escapeHtml(r.id)}</text>
                <text x="${rackW/2}" y="36" class="lld-rack-sub">GB200 NVL72</text>
                <line x1="10" y1="50" x2="${rackW-10}" y2="50" stroke="#2A3038"/>
                <text x="10" y="68" class="lld-rack-metric">GPU Tj</text>
                <text x="${rackW-10}" y="68" class="lld-rack-val" text-anchor="end">${r.gpu_tj_c}°C</text>
                <text x="10" y="88" class="lld-rack-metric">DLC ΔT</text>
                <text x="${rackW-10}" y="88" class="lld-rack-val" text-anchor="end">${r.dlc_dt_k} K</text>
                <text x="10" y="108" class="lld-rack-metric">Health</text>
                <text x="${rackW-10}" y="108" class="lld-rack-val" text-anchor="end">${r.health.toFixed(2)}</text>
                <!-- Health bar at bottom -->
                <rect x="10" y="125" width="${rackW-20}" height="6" rx="2" fill="#0B0D10"/>
                <rect x="10" y="125" width="${(rackW-20) * r.health}" height="6" rx="2" class="lld-rack-fill ${sevClass}"/>
                <text x="${rackW/2}" y="150" class="lld-rack-status">${escapeHtml(r.severity.toUpperCase())}</text>
            </g>`;
        });
        group.innerHTML = html;
    }

    function showTopologyNodeDetail(nodeId) {
        if (!topologyState || !topologyState.hld_nodes) return;
        const node = topologyState.hld_nodes[nodeId];
        if (!node) return;

        const panel = $('topo-detail-panel');
        const titleEl = $('topo-detail-title');
        const bodyEl = $('topo-detail-body');

        if (titleEl) titleEl.textContent = node.label || nodeId;

        const metricsHtml = Object.entries(node.metrics || {}).map(([k, v]) => {
            const formatted = typeof v === 'number'
                ? (Number.isInteger(v) ? v.toLocaleString() : v.toFixed(2))
                : String(v);
            return `<div class="topo-detail-row">
                <span class="topo-detail-key">${escapeHtml(k)}</span>
                <span class="topo-detail-val">${escapeHtml(formatted)}</span>
            </div>`;
        }).join('');

        bodyEl.innerHTML = `
            <div class="topo-detail-row">
                <span class="topo-detail-key">Severity</span>
                <span class="topo-detail-val sev-${node.severity}">${escapeHtml(node.severity.toUpperCase())}</span>
            </div>
            <div class="topo-detail-row">
                <span class="topo-detail-key">Health</span>
                <span class="topo-detail-val">${node.health.toFixed(2)}</span>
            </div>
            ${metricsHtml}
        `;
        panel.hidden = false;
    }

    // MIGRATED (ROADMAP V11 T2.1): the Cooling (DLC) P&ID view now
    // lives in views/cooling.js (ES module) + services/api.js. Route
    // ownership moved to core/router.js; this IIFE no longer renders it.

    // MIGRATED (ROADMAP V11 T2.1): the Power & UPS SLD data plane now
    // lives in views/power.js (ES module) + services/api.js. The 2.5D
    // isometric engine (power_ups_iso/sld/grid/cam) is unchanged. Route
    // ownership moved to core/router.js; this IIFE no longer renders it.

    // MIGRATED (ROADMAP V11 T2.1): the Facility Co-Pilot AI view now
    // lives in views/copilot.js (ES module). LLM-authored chat/tool-trace
    // surfaces route through core/sanitize.js (F3-5 XSS allowlist); the
    // view subscribes to the Hermes hermes:agent-consensus DOM event.
    // Route ownership moved to core/router.js; this IIFE no longer renders it.

    // MIGRATED (ROADMAP V11 T2.1 Vector 1): the BMS Connector view now
    // lives in views/bms.js (ES module). Route ownership moved to
    // core/router.js; showBmsAudit is re-exposed on window so the
    // views/copilot.js audit deep-link keeps working. This IIFE no
    // longer renders it.

    // ── Original placeholder renderer ─────────────────────
    function renderPlaceholder(routeKey) {
        const cfg = MODULES[routeKey];
        if (!cfg || cfg.kind !== 'placeholder') return;
        $('ph-title').textContent = cfg.title;
        $('ph-sub').textContent   = cfg.sub;
        $('ph-icon').textContent  = cfg.icon;
        $('ph-desc').textContent  = cfg.desc;
        const chipBox = $('ph-chips');
        chipBox.innerHTML = '';
        (cfg.chips || []).forEach(q => {
            const c = document.createElement('div');
            c.className = 'chip';
            c.textContent = q;
            c.style.cursor = 'pointer';
            c.addEventListener('click', () => {
                // Navigate to overview and send the query
                navigateTo('overview');
                els.agentInput().value = q;
                sendAgentQuery(q);
            });
            chipBox.appendChild(c);
        });
    }

    // NOTE: the Incidents view was extracted to views/incidents.js
    // (ROADMAP V11 T2.1). core/router.js owns the 'incidents' route;
    // navigateTo() below delegates it before the legacy switch.

    function navigateTo(routeKey) {
        if (!routeKey) routeKey = 'overview';

        // T2.2: ES-module routes are owned by core/router.js. Delegate
        // any registered route to it and return, so the legacy renderer
        // below does not also fire (kills the dual-router race).
        if (window.__epmsRouter && window.__epmsRouter.isRegistered(routeKey)) {
            window.__epmsRouter.navigateTo(routeKey);
            return;
        }

        // Update nav active state
        document.querySelectorAll('.nav-item').forEach(n => {
            n.classList.toggle('active', n.dataset.route === routeKey);
        });

        // Hide all views
        document.querySelectorAll('.view').forEach(v => v.setAttribute('hidden', ''));

        // Show correct view
        const cfg = MODULES[routeKey];
        if (routeKey === 'overview' || !cfg) {
            const ov = $('view-overview');
            if (ov) ov.removeAttribute('hidden');
            // Refresh SHI on each return to overview
            fetchSiteHealth();
        } else if (cfg.kind === 'topology') {
            const v = $('view-topology');
            if (v) v.removeAttribute('hidden');
            renderTopologyView();
        } else if (cfg.kind === 'site_topology') {
            const v = $('view-site-topology');
            if (v) v.removeAttribute('hidden');
            renderSiteTopologyView();
        } else if (cfg.kind === 'maintenance') {
            // v0.10.12: hand control to the ES-module renderer.
            // We unhide here so MutationObserver in views/maintenance.js
            // picks it up immediately (no flash of overview).
            const v = $('view-maintenance');
            if (v) v.removeAttribute('hidden');
        } else if (cfg.kind === 'placeholder') {
            const v = $('view-placeholder');
            if (v) v.removeAttribute('hidden');
            renderPlaceholder(routeKey);
        }
    }



    // Sprint S1b - Site Topology view renderer
    let _stSelectedId = null;
    let _stInitialized = false;

    // Lucide SVG icons map for tree (size 14 for leaves/rooms)
    const _ST_LUCIDE_SVGS = {
        warehouse: '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" data-lucide="warehouse"><path d="M22 8.35V20a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8.35A2 2 0 0 1 3.26 6.5l8-3.2a2 2 0 0 1 1.48 0l8 3.2A2 2 0 0 1 22 8.35Z"/><path d="M6 18h12"/><path d="M6 14h12"/><rect width="12" height="12" x="6" y="10"/></svg>',
        server: '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" data-lucide="server"><rect width="20" height="8" x="2" y="2" rx="2" ry="2"/><rect width="20" height="8" x="2" y="14" rx="2" ry="2"/><line x1="6" x2="6.01" y1="6" y2="6"/><line x1="6" x2="6.01" y1="18" y2="18"/></svg>',
        layout_grid: '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" data-lucide="layout-grid"><rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/></svg>',
        zap: '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" data-lucide="zap"><path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/></svg>',
        snowflake: '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" data-lucide="snowflake"><path d="M2 12h20"/><path d="M12 2v20"/><path d="m20 16-4-4 4-4"/><path d="m4 8 4 4-4 4"/><path d="m16 4-4 4-4-4"/><path d="m8 20 4-4 4 4"/></svg>',
        fuel: '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" data-lucide="fuel"><line x1="3" x2="15" y1="22" y2="22"/><line x1="4" x2="14" y1="9" y2="9"/><path d="M14 22V4a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v18"/><path d="M14 13h2a2 2 0 0 1 2 2v2a2 2 0 0 0 2 2a2 2 0 0 0 2-2V9.83a2 2 0 0 0-.59-1.42L18 5"/></svg>',
        monitor: '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" data-lucide="monitor"><rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/><line x1="12" x2="12" y1="17" y2="21"/></svg>',
        rows: '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" data-lucide="rows"><rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><line x1="3" x2="21" y1="9" y2="9"/><line x1="3" x2="21" y1="15" y2="15"/></svg>',
    };
    function _stLucideSvg(name) {
        return _ST_LUCIDE_SVGS[name.replace(/-/g, '_')] || '';
    }


    async function renderSiteTopologyView() {
        if (_stInitialized) {
            await _stRenderTree();
            return;
        }
        _stInitialized = true;
        document.querySelectorAll('.st-tab').forEach(btn => {
            if (btn._bound) return;
            btn._bound = true;
            btn.addEventListener('click', () => {
                const tab = btn.dataset.stTab;
                document.querySelectorAll('.st-tab').forEach(b => b.classList.toggle('st-tab-active', b === btn));
                document.querySelectorAll('.st-tab-content').forEach(c => { c.hidden = c.id !== `st-tab-${tab}`; });
                if (tab === 'power') _stLoadPowerTab();
                if (tab === 'loto') _stLoadLotoTab();
            });
        });
        const refreshBtn = $('st-refresh');
        if (refreshBtn && !refreshBtn._bound) {
            refreshBtn._bound = true;
            refreshBtn.addEventListener('click', _stRenderTree);
        }
        await _stRenderTree();
    }

    async function _stApi(path) {
        const r = await fetch(`${API_BASE}/api/site${path}`);
        if (!r.ok) throw new Error(`API ${path} -> ${r.status}`);
        return r.json();
    }

    async function _stRenderTree() {
        const root = $('st-tree');
        root.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-muted,#6a7a8b);font-style:italic;">Loading...</div>';
        try {
            const meta = await _stApi('/metadata');
            $('st-redundancy').textContent = `${meta.redundancy.electrical} / ${meta.redundancy.cooling}`;
            const compsResp = await _stApi('/components?limit=1000');
            $('st-count').textContent = compsResp.total;
            const { buildings } = await _stApi('/buildings');
            root.innerHTML = '';
            for (const b of buildings) root.appendChild(_stBuildingNode(b));
        } catch (e) {
            root.innerHTML = `<div style="padding:24px;color:#ff5050;">Error: ${e.message}</div>`;
        }
    }

    function _stBuildingNode(b) {
        const wrap = document.createElement('div');
        const row = document.createElement('div'); row.className = 'st-tree-row';
        const toggle = document.createElement('span'); toggle.className = 'st-tree-toggle'; toggle.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" data-lucide="chevron-right"><path d="m9 18 6-6-6-6"/></svg>';
        const icon = document.createElement('span'); icon.className = 'st-tree-icon'; icon.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" data-lucide="warehouse"><path d="M22 8.35V20a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8.35A2 2 0 0 1 3.26 6.5l8-3.2a2 2 0 0 1 1.48 0l8 3.2A2 2 0 0 1 22 8.35Z"/><path d="M6 18h12"/><path d="M6 14h12"/><rect width="12" height="12" x="6" y="10"/></svg>';
        const label = document.createElement('span'); label.className = 'st-tree-label'; label.textContent = b.display;
        const count = document.createElement('span'); count.className = 'st-tree-count'; count.textContent = `${b.room_count} rooms`;
        row.append(toggle, icon, label, count); wrap.appendChild(row);
        const children = document.createElement('div'); children.className = 'st-tree-children'; children.style.display = 'none';
        wrap.appendChild(children);
        let loaded = false;
        row.addEventListener('click', async (e) => {
            e.stopPropagation();
            const expanded = children.style.display === 'block';
            children.style.display = expanded ? 'none' : 'block';
            toggle.innerHTML = expanded ? '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" data-lucide="chevron-right"><path d="m9 18 6-6-6-6"/></svg>' : '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" data-lucide="chevron-down"><path d="m6 9 6 6 6-6"/></svg>';
            if (!loaded && !expanded) {
                loaded = true;
                children.innerHTML = '<div style="padding:6px 12px;color:var(--text-muted,#6a7a8b);font-style:italic;font-size:11px;">Loading...</div>';
                try {
                    const data = await _stApi(`/tree/${b.id}`);
                    children.innerHTML = '';
                    for (const room of data.rooms) children.appendChild(_stRoomNode(room));
                } catch (err) {
                    children.innerHTML = `<div style="padding:6px;color:#ff5050;">${err.message}</div>`;
                }
            }
        });
        return wrap;
    }

    function _stRoomNode(room) {
        const wrap = document.createElement('div');
        const row = document.createElement('div'); row.className = 'st-tree-row';
        const toggle = document.createElement('span'); toggle.className = 'st-tree-toggle'; toggle.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" data-lucide="chevron-right"><path d="m9 18 6-6-6-6"/></svg>';
        const iconMap = { data_hall:'server', electrical_room:'zap', mechanical_room:'snowflake', mechanical_plant:'snowflake', emergency_power:'zap', utility_intake:'zap', fuel_depot:'fuel', control_room:'monitor' };
        const iconName = iconMap[room.type] || 'layout-grid';
        const icon = document.createElement('span'); icon.className = 'st-tree-icon'; icon.innerHTML = _stLucideSvg(iconName);
        const label = document.createElement('span'); label.className = 'st-tree-label'; label.textContent = room.display;
        const total = (room.components || []).length + (room.rows || []).length;
        const count = document.createElement('span'); count.className = 'st-tree-count'; count.textContent = total ? `${total} items` : '';
        row.append(toggle, icon, label, count); wrap.appendChild(row);
        const children = document.createElement('div'); children.className = 'st-tree-children'; children.style.display = 'none';
        wrap.appendChild(children);
        for (const r of (room.rows || [])) children.appendChild(_stRowNode(r));
        for (const cId of (room.components || [])) children.appendChild(_stLeaf(cId));
        row.addEventListener('click', (e) => {
            e.stopPropagation();
            const expanded = children.style.display === 'block';
            children.style.display = expanded ? 'none' : 'block';
            toggle.innerHTML = expanded ? '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" data-lucide="chevron-right"><path d="m9 18 6-6-6-6"/></svg>' : '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" data-lucide="chevron-down"><path d="m6 9 6 6 6-6"/></svg>';
        });
        return wrap;
    }

    function _stRowNode(rowData) {
        const wrap = document.createElement('div');
        const row = document.createElement('div'); row.className = 'st-tree-row';
        const toggle = document.createElement('span'); toggle.className = 'st-tree-toggle'; toggle.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" data-lucide="chevron-right"><path d="m9 18 6-6-6-6"/></svg>';
        const icon = document.createElement('span'); icon.className = 'st-tree-icon'; icon.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" data-lucide="rows"><rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><line x1="3" x2="21" y1="9" y2="9"/><line x1="3" x2="21" y1="15" y2="15"/></svg>';
        const label = document.createElement('span'); label.className = 'st-tree-label'; label.textContent = rowData.display;
        const count = document.createElement('span'); count.className = 'st-tree-count'; count.textContent = `${rowData.racks.length} racks`;
        row.append(toggle, icon, label, count); wrap.appendChild(row);
        const children = document.createElement('div'); children.className = 'st-tree-children'; children.style.display = 'none';
        wrap.appendChild(children);
        for (const rackId of rowData.racks) children.appendChild(_stLeaf(rackId));
        row.addEventListener('click', (e) => {
            e.stopPropagation();
            const expanded = children.style.display === 'block';
            children.style.display = expanded ? 'none' : 'block';
            toggle.innerHTML = expanded ? '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" data-lucide="chevron-right"><path d="m9 18 6-6-6-6"/></svg>' : '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" data-lucide="chevron-down"><path d="m6 9 6 6 6-6"/></svg>';
        });
        return wrap;
    }

    function _stLeaf(canonicalId) {
        const leaf = document.createElement('div');
        leaf.className = 'st-tree-leaf';
        leaf.textContent = canonicalId;
        leaf.dataset.cid = canonicalId;
        leaf.addEventListener('click', (e) => { e.stopPropagation(); _stSelect(canonicalId); });
        return leaf;
    }

    async function _stSelect(canonicalId) {
        _stSelectedId = canonicalId;
        document.querySelectorAll('.st-tree-leaf.st-selected').forEach(n => n.classList.remove('st-selected'));
        document.querySelectorAll(`.st-tree-leaf[data-cid="${canonicalId}"]`).forEach(n => n.classList.add('st-selected'));
        $('st-detail-empty').style.display = 'none';
        $('st-detail-content').style.display = 'block';
        try {
            const comp = await _stApi(`/components/${canonicalId}`);
            $('st-title').textContent = comp.display;
            const bc = $('st-breadcrumb'); bc.innerHTML = '';
            comp.location.components.forEach((c, i) => {
                if (i > 0) bc.insertAdjacentHTML('beforeend', '<span style="margin:0 6px;color:var(--border,#2b3640);">/</span>');
                bc.insertAdjacentHTML('beforeend', `<span>${c.display}</span>`);
            });
            const grid = $('st-tab-overview');
            grid.innerHTML = '<dl class="st-overview-grid"></dl>';
            const dl = grid.firstElementChild;
            const fields = [
                ['Canonical ID', comp.canonical_id],
                ['Display', comp.display],
                ['Type', comp.type],
                ['Location', comp.location.path],
            ];
            Object.entries(comp).forEach(([k, v]) => {
                if (['canonical_id','display','type','location'].includes(k)) return;
                if (v === null || v === undefined || typeof v === 'object') return;
                const label = k.replace(/_/g,' ').replace(/\b\w/g, l => l.toUpperCase());
                fields.push([label, String(v)]);
            });
            for (const [k, v] of fields) {
                dl.insertAdjacentHTML('beforeend', `<dt>${k}</dt><dd>${v}</dd>`);
            }
            document.querySelectorAll('.st-tab').forEach(b => b.classList.toggle('st-tab-active', b.dataset.stTab === 'overview'));
            document.querySelectorAll('.st-tab-content').forEach(c => c.hidden = c.id !== 'st-tab-overview');
            $('st-tab-power').innerHTML = '<em style="color:var(--text-muted,#6a7a8b)">Click "Power Chain" to load.</em>';
            $('st-tab-loto').innerHTML = '<em style="color:var(--text-muted,#6a7a8b)">Click "LOTO Impact" to load.</em>';
        } catch (e) {
            $('st-title').textContent = 'Error';
            $('st-tab-overview').textContent = e.message;
        }
    }

    async function _stLoadPowerTab() {
        if (!_stSelectedId) return;
        const target = $('st-tab-power');
        target.innerHTML = '<em style="color:var(--text-muted,#6a7a8b)">Loading...</em>';
        try {
            const data = await _stApi(`/power-chain/${_stSelectedId}`);
            target.innerHTML = '';
            const summary = document.createElement('div');
            summary.style.cssText = 'background:var(--bg,#0B0D10);border-radius:6px;padding:11px 14px;margin-bottom:14px;display:flex;gap:18px;align-items:center;';
            if (data.feed_count >= 2) {
                summary.innerHTML = `<span style="background:var(--cyan,#00B8D4);color:var(--bg,#0B0D10);padding:3px 10px;border-radius:4px;font-weight:700;font-size:12px;">2N</span><span>${data.feed_count} redundant feed paths</span>`;
            } else if (data.feed_count === 1) {
                summary.innerHTML = `<span>1 feed path (single-corded)</span>`;
            } else {
                summary.innerHTML = `<span>No upstream feeds</span>`;
            }
            target.appendChild(summary);
            data.feeds.forEach(feed => {
                const block = document.createElement('div');
                block.className = 'st-feed-block ' + (feed.group === 'path_b' ? 'st-path-b' : feed.group === 'path_a' ? '' : 'st-other');
                let html = `<div class="st-feed-title">${feed.group.replace('_',' ').toUpperCase()}</div>`;
                html += '<div class="st-feed-roots">Roots: ';
                feed.roots.forEach(r => html += `<span class="st-root-pill">${r}</span>`);
                html += '</div>';
                html += '<div class="st-feed-path">';
                feed.representative_path.forEach((node, i) => {
                    if (i > 0) html += '<span style="color:var(--text-muted,#6a7a8b);margin:0 4px;">\u2192</span>';
                    html += node;
                });
                html += '</div>';
                block.innerHTML = html;
                target.appendChild(block);
            });
        } catch (e) {
            target.innerHTML = `<div style="color:#ff5050;">Error: ${e.message}</div>`;
        }
    }

    async function _stLoadLotoTab() {
        if (!_stSelectedId) return;
        const target = $('st-tab-loto');
        target.innerHTML = '<em style="color:var(--text-muted,#6a7a8b)">Loading...</em>';
        try {
            const data = await _stApi(`/loto-impact/${_stSelectedId}`);
            target.innerHTML = '';
            const safe = data.racks_losing_all_redundancy.length === 0;
            const banner = document.createElement('div');
            banner.className = 'st-loto-banner ' + (safe ? 'st-safe' : 'st-unsafe');
            banner.textContent = safe
                ? '\u2713 Safe LOTO - all affected racks retain Path B redundancy.'
                : `\u26A0 Risk - ${data.racks_losing_all_redundancy.length} racks would lose all redundancy.`;
            target.appendChild(banner);
            const stats = document.createElement('div');
            stats.className = 'st-stats';
            stats.innerHTML = `
                <div class="st-stat"><div class="st-stat-val">${data.downstream_count}</div><div class="st-stat-lbl">Downstream</div></div>
                <div class="st-stat"><div class="st-stat-val">${data.racks_affected.length}</div><div class="st-stat-lbl">Racks Affected</div></div>
                <div class="st-stat"><div class="st-stat-val ${safe ? 'st-ok' : 'st-danger'}">${data.racks_losing_all_redundancy.length}</div><div class="st-stat-lbl">At Outage Risk</div></div>
            `;
            target.appendChild(stats);
            if (data.racks_affected.length) {
                const h = document.createElement('h4');
                h.style.cssText = 'font-size:12px;color:var(--text-muted,#8a9aab);margin:14px 0 8px;text-transform:uppercase;letter-spacing:0.04em;';
                h.textContent = 'Per-Rack Redundancy';
                target.appendChild(h);
                const list = document.createElement('div');
                list.className = 'st-rack-list';
                data.racks_affected.forEach(r => {
                    const status = r.still_has_redundancy
                        ? `<span class="st-status-safe">${r.remaining_paths}/${r.total_paths} paths OK</span>`
                        : `<span class="st-status-danger">OUTAGE RISK</span>`;
                    list.insertAdjacentHTML('beforeend', `<div class="st-rack-row"><span>${r.rack}</span>${status}</div>`);
                });
                target.appendChild(list);
            }
        } catch (e) {
            target.innerHTML = `<div style="color:#ff5050;">Error: ${e.message}</div>`;
        }
    }

    function setupRouter() {
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', () => {
                const route = item.dataset.route;
                if (route) navigateTo(route);
            });
        });
        // Incidents view (incl. its refresh button) is owned by
        // views/incidents.js since T2.1 — nothing to wire here.
    }

    // ── Wire up UI ─────────────────────────────────────────
    function setupEventListeners() {
        const sendBtn = els.agentSend();
        const input   = els.agentInput();
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

        // SHI refresh button (Day 4)
        const shiBtn = $('shi-refresh');
        if (shiBtn) shiBtn.addEventListener('click', fetchSiteHealth);
    }

    // ── Boot ───────────────────────────────────────────────
    function boot() {
        console.log('DC-EPMS PRO SPA booting...');
        initChart();
        setupEventListeners();
        setupQuickActions();
        setupRouter();

        checkHealth();
        state.healthCheckInterval = setInterval(checkHealth, 15000);

        loadHistoricalTelemetry();
        startTelemetryStream();

        refreshIncidents();
        setInterval(refreshIncidents, 10000);

        // Site Health Index (Day 4)
        fetchSiteHealth();
        setInterval(fetchSiteHealth, 15000);

        console.log('DC-EPMS PRO ready.');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }

    // ---------------------------------------------------------------
    //  LOTO Auditor view (Camino 1 Phase E - Sprint 5 partial)
    //  Backend: /api/loto/audit (Batch 4.D closure v0.7.0-batch4)
    //  Per ADR-006: every audit returns status=pending_approval
    // ---------------------------------------------------------------

    let lotoLastReport = null;
    let lotoInitialized = false;

    // Hardcoded demo procedures (no /api/mops dependency for MVP).
    // In Sprint 5+ wire to /api/mops or new /api/loto/procedures endpoint.
    const LOTO_DEMO_PROCEDURES = [
        { id: 'DEMO-UPS-COMPLIANT',         label: 'DEMO-UPS-COMPLIANT (Galaxy VX with capacitor discharge per NEC 460.6)' },
        { id: 'DEMO-UPS-MISSING-DISCHARGE', label: 'DEMO-UPS-MISSING-DISCHARGE (broken: omits cap discharge step)' },
        { id: 'MOP-ATS-MONTHLY-001',        label: 'MOP-ATS-MONTHLY-001 (ATS monthly transfer test)' }
    ];

    function lotoEscapeHtml(s) {
        if (s === null || s === undefined) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function populateLotoProcedureSelect() {
        const sel = $('loto-procedure-select');
        if (!sel) return;
        sel.innerHTML = '<option value="">-- Select procedure --</option>' +
            LOTO_DEMO_PROCEDURES.map(p =>
                `<option value="${lotoEscapeHtml(p.id)}">${lotoEscapeHtml(p.label)}</option>`
            ).join('');
        // Default to COMPLIANT for first-time UX
        sel.value = 'DEMO-UPS-COMPLIANT';
    }

    async function submitLotoAudit() {
        const procEl   = $('loto-procedure-select');
        const targetEl = $('loto-target-input');
        const cetEl    = $('loto-cet-input');
        const btn      = $('loto-audit-btn');
        const statusBar = $('loto-status-bar');
        const statusTxt = $('loto-status-text');
        const empty     = $('loto-results-empty');
        const panel     = $('loto-results-panel');

        if (!procEl || !targetEl || !cetEl || !btn) return;

        const procedure_id = procEl.value.trim();
        const target_component_id = targetEl.value.trim();
        const cet_on_duty = cetEl.value.trim();

        if (!procedure_id || !target_component_id || !cet_on_duty) {
            statusBar.style.display = 'block';
            statusBar.style.background = 'rgba(255,193,7,0.12)';
            statusBar.style.borderLeft = '3px solid #FFC107';
            statusBar.style.color = '#FFC107';
            statusTxt.textContent = 'All three fields are required.';
            return;
        }

        btn.disabled = true;
        btn.textContent = 'Auditing...';
        statusBar.style.display = 'block';
        statusBar.style.background = 'rgba(0,184,212,0.10)';
        statusBar.style.borderLeft = '3px solid #00B8D4';
        statusBar.style.color = '#00B8D4';
        statusTxt.textContent = 'Running 6-pillar audit on ' + procedure_id + ' targeting ' + target_component_id + '...';

        try {
            const resp = await fetch(`${API_BASE}/api/loto/audit`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ procedure_id, target_component_id, cet_on_duty })
            });
            if (!resp.ok) {
                const t = await resp.text();
                throw new Error(`HTTP ${resp.status}: ${t.substring(0, 300)}`);
            }
            const report = await resp.json();
            lotoLastReport = report;
            renderLotoResults(report);
            empty.style.display = 'none';
            panel.hidden = false;

            statusBar.style.background = 'rgba(0,212,122,0.10)';
            statusBar.style.borderLeft = '3px solid #00d47a';
            statusBar.style.color = '#00d47a';
            statusTxt.textContent = 'Audit complete in ' + (report.decision_time_ms || '--') + ' ms. Status: pending_approval (per ADR-006).';
        } catch (e) {
            statusBar.style.background = 'rgba(255,80,80,0.12)';
            statusBar.style.borderLeft = '3px solid #ff5050';
            statusBar.style.color = '#ff5050';
            statusTxt.textContent = 'Audit failed: ' + (e.message || String(e));
            empty.style.display = 'block';
            panel.hidden = true;
        } finally {
            btn.disabled = false;
            btn.textContent = 'Audit Procedure';
        }
    }

    function lotoOutcomeClass(outcome) {
        if (!outcome) return 'outcome-warn';
        const o = String(outcome).toUpperCase();
        if (o === 'ALL_PASS' || o === 'PASS') return 'outcome-pass';
        if (o === 'HARD_FAIL') return 'outcome-hard-fail';
        return 'outcome-warn';
    }

    function lotoOverallClass(outcome) {
        if (!outcome) return 'overall-warn';
        const o = String(outcome).toUpperCase();
        if (o === 'ALL_PASS' || o === 'PASS') return 'overall-all-pass';
        if (o === 'HARD_FAIL') return 'overall-hard-fail';
        return 'overall-warn';
    }

    function renderLotoPillar(num, title, lines, outcome) {
        const card = document.querySelector(`.loto-pillar-card[data-pillar="${num}"]`);
        const outcomeEl = document.querySelector(`[data-pillar-outcome="${num}"]`);
        const bodyEl = document.querySelector(`[data-pillar-body="${num}"]`);
        if (!card || !outcomeEl || !bodyEl) return;

        const cls = lotoOutcomeClass(outcome);
        outcomeEl.className = 'loto-pillar-outcome ' + cls;
        outcomeEl.textContent = outcome || '--';

        card.classList.remove('outcome-pass', 'outcome-warn', 'outcome-hard-fail');
        card.classList.add(cls);

        bodyEl.innerHTML = lines.map(l => `<div>${lotoEscapeHtml(l)}</div>`).join('');
    }

    function renderLotoResults(report) {
        if (!report) return;

        // Overall
        const overallBadge = $('loto-overall-badge');
        const overallCard  = $('loto-overall-card');
        const overallSub   = $('loto-overall-sub');
        const decTime      = $('loto-decision-time');
        const hardFails    = $('loto-hard-fails');
        const sourcesPre   = $('loto-sources-pre');

        const overall = report.overall_outcome || 'WARN';
        const ovCls = lotoOverallClass(overall);

        overallBadge.className = ovCls;
        overallBadge.textContent = overall;
        overallCard.className = '';
        overallCard.style.cssText = 'background:var(--surface,#14181D);border:2px solid var(--border,#1f262d);border-radius:8px;padding:18px;margin-bottom:14px;display:flex;align-items:center;gap:18px;';
        overallCard.classList.add(ovCls);

        overallSub.textContent = 'Procedure: ' + (report.procedure_id || '--') + ' | Target: ' + (report.target_component_id || '--');
        decTime.textContent = (report.decision_time_ms || '--') + ' ms';
        hardFails.textContent = (report.hard_fail_count !== undefined ? report.hard_fail_count : '--');

        // Pillar 1 - Topology
        const topo = report.topology || {};
        const blastRadius = (topo.impact_radius && topo.impact_radius.affected_components) || [];
        renderLotoPillar(1, 'Topology', [
            'Impact radius: ' + blastRadius.length + ' affected component(s)',
            'Power chain: ' + (topo.power_chain_summary || 'unknown'),
            'Cooling chain: ' + (topo.cooling_chain_summary || 'skipped'),
            'Outcome: ' + (topo.outcome || '--')
        ], topo.outcome);

        // Pillar 2 - Redundancy
        const red = report.redundancy || {};
        renderLotoPillar(2, 'Redundancy 2N', [
            'Target path: ' + (red.target_path || '--'),
            'Path A state: ' + (red.path_a_state || '--'),
            'Path B state: ' + (red.path_b_state || '--'),
            'SHI pre/post: ' + (red.shi_pre_loto !== undefined ? red.shi_pre_loto.toFixed(3) : '--') + ' / ' + (red.shi_post_loto !== undefined ? red.shi_post_loto.toFixed(3) : '--') + ' (threshold ' + (red.shi_threshold || '--') + ')',
            'SPOFs detected: ' + ((red.single_points_of_failure || []).length),
            'Outcome: ' + (red.outcome || '--')
        ], red.outcome);

        // Pillar 3 - Capacitor Discharge
        const cap = report.capacitor_discharge || {};
        renderLotoPillar(3, 'Capacitor Discharge', [
            'Required: ' + (cap.required ? 'yes' : 'no') + ((cap.required_reason) ? ' (' + cap.required_reason + ')' : ''),
            'Found in procedure: ' + (cap.found_in_procedure ? 'yes' : 'NO'),
            'Wait duration: ' + (cap.wait_duration_s || 0) + ' s (min required ' + (cap.minimum_required_s || 60) + ' s)',
            'Voltmeter verification: ' + (cap.voltmeter_verification ? 'yes' : 'NO'),
            'Citation: ' + (cap.citation || '--'),
            'Outcome: ' + (cap.outcome || '--')
        ], cap.outcome);

        // Pillar 4 - Witness Gate
        const wit = report.witness_gate || {};
        renderLotoPillar(4, 'Witness Gate', [
            'Witness required: ' + (wit.witness_required ? 'yes' : 'no'),
            'Steps requiring witness: ' + ((wit.witness_required_steps || []).length),
            'Identity collision protection: ' + (wit.identity_collision_protected ? 'yes' : 'NO'),
            'Witness engine: ' + (wit.witness_engine_status || '--'),
            'Outcome: ' + (wit.outcome || '--')
        ], wit.outcome);

        // Pillar 5 - Sequential Order
        const seq = report.sequential_order || {};
        renderLotoPillar(5, 'Sequential Order', [
            'Phase order detected: ' + ((seq.detected_phase_order || []).join(' -> ') || '--'),
            'Expected order (electrical -> hydraulic -> purge): ' + (seq.order_compliant ? 'yes' : 'NO'),
            'Outcome: ' + (seq.outcome || '--')
        ], seq.outcome);

        // Pillar 6 - PPE Category
        const ppe = report.ppe_category || {};
        renderLotoPillar(6, 'PPE Category', [
            'Voltage class: ' + (ppe.voltage_nominal ? (ppe.voltage_nominal + ' V') : '--'),
            'Required PPE category: ' + (ppe.required_category || '--'),
            'Procedure PPE category: ' + (ppe.procedure_category || '--'),
            'Citation: NFPA 70E 130.5(C)',
            'Outcome: ' + (ppe.outcome || '--')
        ], ppe.outcome);

        // Sources consulted (audit trail)
        if (sourcesPre) {
            sourcesPre.textContent = JSON.stringify(report.sources_consulted || {}, null, 2);
        }
    }

    function initLotoView() {
        if (lotoInitialized) return;
        lotoInitialized = true;

        populateLotoProcedureSelect();

        const btn = $('loto-audit-btn');
        if (btn) {
            btn.addEventListener('click', submitLotoAudit);
        }

        // Allow Enter key in target/cet inputs to trigger audit
        ['loto-target-input', 'loto-cet-input'].forEach(id => {
            const el = $(id);
            if (el) {
                el.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        submitLotoAudit();
                    }
                });
            }
        });

        console.log('[LOTO Auditor] view initialized');
    }

    // Hook into router: when nav-item with data-route="loto" is clicked,
    // initialize the view. We patch into the existing router by listening
    // to a custom event the router fires (or by polling DOM mutations).
    //
    // Strategy: hook via DOMContentLoaded + click delegation on nav-item,
    // since the router is internal to the IIFE and we cannot easily refactor.
    document.addEventListener('click', (e) => {
        const navItem = e.target.closest('[data-route="loto"]');
        if (navItem) {
            // Defer to next tick so the router has time to switch views
            setTimeout(() => {
                initLotoView();
                // Manually toggle visibility if router did not handle 'loto' route
                document.querySelectorAll('.view').forEach(v => { v.hidden = true; });
                const lotoView = $('view-loto-auditor');
                if (lotoView) {
                    lotoView.hidden = false;
                }
                document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
                navItem.classList.add('active');
            }, 0);
        }
    });

    // ---------------------------------------------------------------
    //  END LOTO Auditor view
    // ---------------------------------------------------------------

})();
