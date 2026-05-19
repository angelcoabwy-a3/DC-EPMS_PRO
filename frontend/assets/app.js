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

    // MIGRATED (ROADMAP V11 T2.1 Vector 4a): the HLD/LLD Topology view
    // now lives in views/topology.js (ES module). Route ownership moved
    // to core/router.js registerRoute('topology'); this IIFE no longer
    // renders it.

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



    // ERADICATED (ROADMAP V11 T2.1 Vector 3): the legacy Site Topology
    // tree+detail view was confirmed-dead code - views/site_topology.js
    // (force-directed graph) owns the 'site_topology' route via
    // core/router.js, so the legacy renderSiteTopologyView was
    // unreachable. Deleted, not migrated. See scripts/
    // _eradicate_site_topology_legacy.py for the full adjudication.

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

    // MIGRATED (ROADMAP V11 T2.1 Vector 2): the LOTO Auditor view now
    // lives in views/loto.js (ES module). Route ownership moved to
    // core/router.js registerRoute('loto') - the legacy document-level
    // click-delegation + setTimeout(0) routing hack is retired.


})();
