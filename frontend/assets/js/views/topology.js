/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/topology.js
 * Diagram Rebuild Batch 3 — Facility Topology (HLD/LLD) generated
 * from the canonical node registry via the shared diagram kit.
 *
 * What changed vs the T2.1 Vector 4a generation:
 *   - The hand-authored static HLD SVG in index.html is RETIRED.
 *     _buildHldMarkup() generates the system-of-systems map
 *     (electrical 2N chain + IT halls + CDU loop + heat rejection)
 *     with kit-enforced orthogonal flows — the last diagonal-
 *     spaghetti diagram in the HMI is gone.
 *   - Vocabulary fix: the electrical section header read
 *     "27kV -> 480V -> 480VDC"; Phase 1 distribution is 480 VAC
 *     3-phase (S-VOCAB-01 — there is no 480 VDC bus in Phase 1).
 *   - Data plane joins the fleet pattern: /api/topology/state is
 *     fetched ONCE per activation (+ the Refresh button); the
 *     legacy 8 s setInterval poll is eradicated. Live severity now
 *     arrives on the Hermes telemetry stream, mapped through the
 *     registry's channel-prefix discipline.
 *   - Building D (Phase 2, Path C2) appears as an honest dashed
 *     design marker pointing at the Power SLD's 800 VDC branch.
 *
 * Unchanged contracts: the rule-based AI Mission Control insight
 * engine, the LLD rack grid renderer, the Emergency Simulation
 * (POST /api/topology/whatif — the BACKEND physics What-If; the
 * local DAG sandboxes live in the Power/Cooling SLD views), the
 * node detail panel, and the cooling-tower sparkline.
 * ════════════════════════════════════════════════════════════════ */

import { registerRoute } from '../core/router.js';
import { escapeHTML } from '../core/sanitize.js';
import { onHermesStream } from '../services/api.js';
import { wire, severityFromChannels } from '../core/diagram_kit.js';
import { nodeForTopoKey, matchesChannel } from '../core/node_registry.js';

const $ = (id) => document.getElementById(id);

let _routeRegistered = false;
let topologyState = null;
let currentTopologyTab = 'hld';
let _unsubTelemetry = null;
// Day 8: state for sparkline + emergency simulation mode
const ctSparklineHistory = { wb: [], amb: [], maxPoints: 60 };
let emergencySimMode = false;

function fmt0(v) { return (v == null) ? '—' : Math.round(v).toLocaleString(); }
function fmt1(v) { return (v == null) ? '—' : Number(v).toFixed(1); }

// ════════════════════════════════════════════════════════════════
//  HLD generator — registry-driven system-of-systems map
// ════════════════════════════════════════════════════════════════

// HLD nodes keyed by /api/topology/state ids. Geometry + display
// dressing live here; identity (channels, phase, chain) lives in the
// registry. w/h default to the standard 120x60 tile.
const _HLD_NODES = [
    { id: 'utility_north', title: 'Utility North', sub: 'Feed A · 27.5 kV',      x: 40,  y: 50,  metrics: [{ key: 'utility_north-kw', text: '— kW' }] },
    { id: 'utility_south', title: 'Utility South', sub: 'Feed B · 27.5 kV',      x: 40,  y: 130, metrics: [{ key: 'utility_south-kw', text: '— kW' }] },
    { id: 'xfmr_a',        title: 'XFMR A',        sub: '2.5 MVA · System A',    x: 220, y: 50,  metrics: [{ key: 'xfmr_a-winding', text: '—°C' }] },
    { id: 'xfmr_b',        title: 'XFMR B',        sub: '2.5 MVA · System B',    x: 220, y: 130, metrics: [{ key: 'xfmr_b-winding', text: '—°C' }] },
    { id: 'ups_a',         title: 'UPS Galaxy A',  sub: '750 kVA · System A',    x: 390, y: 50,  metrics: [{ key: 'ups_a-soc', text: 'SOC —%' }] },
    { id: 'ups_b',         title: 'UPS Galaxy B',  sub: '750 kVA · System B',    x: 390, y: 130, metrics: [{ key: 'ups_b-soc', text: 'SOC —%' }] },
    { id: 'hall_1', large: true, physics: true, title: 'Hall 1', sub: '~40 racks GB200 (P1)', x: 580, y: 260, w: 150, h: 80,
      metrics: [{ key: 'hall_1-inlet', text: '— °C inlet' }, { key: 'hall_1-load', text: '— kW' }] },
    { id: 'hall_2', large: true, physics: true, title: 'Hall 2', sub: '~40 racks GB200 (P1)', x: 750, y: 260, w: 150, h: 80,
      metrics: [{ key: 'hall_2-inlet', text: '— °C inlet' }, { key: 'hall_2-load', text: '— kW' }] },
    { id: 'hall_3', large: true, physics: true, title: 'Hall 3', sub: '~38 racks GB200 (P1)', x: 920, y: 260, w: 150, h: 80,
      metrics: [{ key: 'hall_3-inlet', text: '— °C inlet' }, { key: 'hall_3-load', text: '— kW' }] },
    { id: 'cdu_a', badge: true, title: 'CDU A', sub: '6 MW HX', x: 220, y: 270, w: 110,
      metrics: [{ key: 'cdu_a-q', text: '— kW' }] },
    { id: 'cdu_b', badge: true, title: 'CDU B', sub: '6 MW HX', x: 220, y: 350, w: 110,
      metrics: [{ key: 'cdu_b-q', text: '— kW' }] },
    { id: 'chiller_1', physics: true, title: 'Chiller 1', sub: '5275 kW', x: 220, y: 470, w: 110,
      metrics: [{ key: 'chiller_1-cop', text: 'COP —' }] },
    { id: 'chiller_2', physics: true, title: 'Chiller 2', sub: '5275 kW', x: 220, y: 545, w: 110,
      metrics: [{ key: 'chiller_2-cop', text: 'COP —' }] },
];

function _hldNode(n) {
    const w = n.w || 120;
    const h = n.h || (n.large ? 80 : 60);
    const cx = w / 2;
    const metricY0 = n.large ? 56 : 50;
    const metrics = (n.metrics || []).map((m, i) =>
        `<text x="${cx}" y="${metricY0 + i * 16}" class="topo-node-metric" `
        + `data-metric="${m.key}">${escapeHTML(m.text)}</text>`).join('');
    const badge = n.badge
        ? `<g class="topo-badge topo-badge-active" transform="translate(${w - 34}, 4)" data-badge="${n.id}">`
          + `<rect width="32" height="11" rx="2"/>`
          + `<text x="16" y="8" class="topo-badge-text">ACTIVE</text></g>`
        : '';
    const physics = n.physics
        ? `<g class="topo-physics-badge" transform="translate(${w - 18}, 4)">`
          + `<title>Validated by Physics Engine</title>`
          + `<circle cx="7" cy="7" r="6.5"/>`
          + `<text x="7" y="10" class="topo-physics-icon">⚛</text></g>`
        : '';
    return `<g class="topo-node${n.large ? ' topo-node-large' : ''}" `
        + `data-node="${n.id}" transform="translate(${n.x}, ${n.y})">`
        + `<rect width="${w}" height="${h}" rx="4" class="topo-node-rect"`
        + (n.id === 'cooling_tower' ? ' id="cooling-tower-rect"' : '') + `/>`
        + `<text x="${cx}" y="${n.large ? 22 : 20}" class="topo-node-title">${escapeHTML(n.title)}</text>`
        + `<text x="${cx}" y="${n.large ? 38 : 34}" class="topo-node-sub">${escapeHTML(n.sub)}</text>`
        + metrics + badge + physics
        + `</g>`;
}

// The cooling tower keeps its bespoke tile (sparkline + ΔT pulse).
function _hldCoolingTower() {
    return `<g class="topo-node topo-node-large" data-node="cooling_tower" transform="translate(440, 470)">`
        + `<rect width="160" height="135" rx="4" class="topo-node-rect" id="cooling-tower-rect"/>`
        + `<text x="80" y="22" class="topo-node-title">Cooling Tower</text>`
        + `<text x="80" y="38" class="topo-node-sub">2-cell evap.</text>`
        + `<text x="80" y="58" class="topo-node-metric" data-metric="cooling_tower-wb">WB — °C</text>`
        + `<text x="80" y="73" class="topo-node-metric" data-metric="cooling_tower-ecwt">ECWT — °C</text>`
        + `<g class="topo-sparkline" transform="translate(10, 82)">`
        + `<rect width="140" height="30" rx="2" fill="rgba(0,0,0,0.3)"/>`
        + `<polyline id="ct-sparkline-wb" points="" stroke="#FB8C00" stroke-width="1.4" fill="none"/>`
        + `<polyline id="ct-sparkline-amb" points="" stroke="#00B8D4" stroke-width="1.4" fill="none"/>`
        + `<text x="3" y="9" class="topo-sparkline-lbl">1h trend</text>`
        + `<text x="138" y="9" class="topo-sparkline-lbl" text-anchor="end">WB / Amb</text>`
        + `</g>`
        + `<text x="80" y="125" class="topo-deltat-warn" id="ct-deltat-warn"></text>`
        + `</g>`;
}

// Phase 2 honest design marker — Building D points at the Power SLD
// where the full 800 VDC branch lives. Dashed, non-interactive.
function _hldBuildingD() {
    return `<g class="topo-node-design" data-phase="2" transform="translate(880, 40)">`
        + `<rect width="190" height="70" rx="4" class="topo-node-rect topo-design-rect"/>`
        + `<text x="95" y="20" class="topo-node-title">BUILDING D · PH2 DESIGN</text>`
        + `<text x="95" y="38" class="topo-node-sub">800 VDC unipolar TN-S</text>`
        + `<text x="95" y="56" class="topo-node-sub">full branch: Power SLD</text>`
        + `</g>`;
}

/** Build the full HLD inner markup (kit-enforced orthogonal flows). */
function _buildHldMarkup() {
    const sections =
        `<text x="40" y="30" class="topo-section-lbl">ELECTRICAL · 2N DUAL UTILITY · 27.5 kV → 480 VAC 3-φ</text>`
        + `<text x="40" y="245" class="topo-section-lbl-r">CDU · DLC secondary loops · 100 L/min/rack</text>`
        + `<text x="40" y="445" class="topo-section-lbl">HEAT REJECTION · York YZ chillers · cooling tower</text>`;

    // ── orthogonal flows (kit: a diagonal segment throws) ──
    const F = (pts, cls) => wire(pts, cls, 'topo-flow');
    const flows = [
        // utility -> xfmr -> ups (2N rows)
        F([[160, 80], [220, 80]], 'flow-electric'),
        F([[160, 160], [220, 160]], 'flow-electric'),
        F([[340, 80], [390, 80]], 'flow-electric'),
        F([[340, 160], [390, 160]], 'flow-electric'),
        // ups -> riser -> hall header -> drops
        F([[510, 80], [545, 80]], 'flow-electric'),
        F([[510, 160], [545, 160]], 'flow-electric'),
        F([[545, 80], [545, 240], [995, 240]], 'flow-electric'),
        F([[655, 240], [655, 260]], 'flow-electric'),
        F([[825, 240], [825, 260]], 'flow-electric'),
        F([[995, 240], [995, 260]], 'flow-electric'),
        // halls -> CDU warm return / CDU -> halls cool supply
        F([[580, 300], [330, 300]], 'flow-coolant flow-warm'),
        F([[330, 380], [560, 380], [560, 340]], 'flow-coolant flow-cool'),
        // CDU -> chiller (chilled water)
        F([[275, 410], [275, 470]], 'flow-coolant flow-cool'),
        // chillers <-> cooling tower
        F([[330, 500], [440, 500]], 'flow-coolant flow-warm'),
        F([[330, 575], [440, 575]], 'flow-coolant flow-warm'),
        F([[440, 535], [330, 535]], 'flow-coolant flow-cool'),
    ].join('');

    const nodes = _HLD_NODES.map(_hldNode).join('')
        + _hldCoolingTower()
        + _hldBuildingD();

    return sections + flows + nodes;
}

/** Render the generated HLD into the #topo-hld-svg shell. */
function _renderHld() {
    const svg = $('topo-hld-svg');
    if (!svg) return;
    svg.innerHTML = _buildHldMarkup();
}

// ─── Live severity from the Hermes telemetry stream ───────────────
// Maps Kalman channels onto HLD node rects through the registry's
// channel-prefix discipline (same fleet pattern as Power/Cooling).
function _applyTelemetry(channels) {
    if (!channels || typeof channels !== 'object') return;
    const ids = Object.keys(channels);
    if (!ids.length) return;
    document.querySelectorAll('#topo-canvas-hld .topo-node[data-node]').forEach((el) => {
        const topoKey = el.dataset.node;
        const entry = nodeForTopoKey(topoKey);
        const prefixes = entry?.channels?.length ? entry.channels : [topoKey];
        const matched = ids.filter((c) => matchesChannel(c, prefixes))
            .map((c) => channels[c]);
        if (!matched.length) return;
        const sev = severityFromChannels(matched);
        const rect = el.querySelector('rect.topo-node-rect') || el.querySelector('rect');
        if (rect) rect.setAttribute('class', 'topo-node-rect sev-' + sev);
    });
}

function _onTelemetryFrame(payload) {
    if (payload && payload.channels) _applyTelemetry(payload.channels);
}

// ─── Lifecycle / routing ───────────────────────────────────────────
async function renderTopologyView() {
    // Bind tab handlers (idempotent)
    document.querySelectorAll('.topo-tab').forEach((tab) => {
        if (!tab._bound) {
            tab._bound = true;
            tab.addEventListener('click', () => {
                document.querySelectorAll('.topo-tab').forEach((t) => t.classList.remove('active'));
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

    // Refresh button — the only metrics re-fetch besides activation.
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

    // Node clicks — delegated on the canvas so it survives re-renders.
    const hldCanvas = $('topo-canvas-hld');
    if (hldCanvas && !hldCanvas._bound) {
        hldCanvas._bound = true;
        hldCanvas.addEventListener('click', (e) => {
            const node = e.target.closest('.topo-node[data-node]');
            if (!node) return;
            if (emergencySimMode) {
                runEmergencyWhatIf(node.dataset.node);
            } else {
                showTopologyNodeDetail(node.dataset.node);
            }
        });
    }

    // Bind Emergency Simulation toggle
    const emBtn = $('emergency-sim-btn');
    if (emBtn && !emBtn._bound) {
        emBtn._bound = true;
        emBtn.addEventListener('click', () => {
            emergencySimMode = !emergencySimMode;
            if (emergencySimMode) {
                emBtn.classList.add('active');
                emBtn.textContent = '🚨 SIM ACTIVE — click any node to fail';
                document.querySelectorAll('.topo-node').forEach((n) => n.classList.add('sim-mode'));
            } else {
                emBtn.classList.remove('active');
                emBtn.textContent = '🚨 Emergency Simulation';
                document.querySelectorAll('.topo-node').forEach((n) => n.classList.remove('sim-mode'));
                // Clear any what-if banner
                const banner = $('whatif-banner');
                if (banner) banner.remove();
            }
        });
    }

    // Baseline metrics once per activation — live severity arrives on
    // the Hermes telemetry stream (the 8 s poll is eradicated).
    await fetchTopologyState();
}

async function runEmergencyWhatIf(nodeId) {
    try {
        const resp = await fetch('/api/topology/whatif', {
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
                <span class="whatif-val whatif-fail">${escapeHTML(d.failed_node)}</span>
            </div>
            <div class="whatif-row">
                <span class="whatif-lbl">Description:</span>
                <span class="whatif-val">${escapeHTML(d.description)}</span>
            </div>
            <div class="whatif-row">
                <span class="whatif-lbl">SHI:</span>
                <span class="whatif-val">${d.baseline.site_health.toFixed(2)} → <span class="whatif-after">${d.degraded.site_health.toFixed(2)}</span> (${deltaSign}${d.shi_delta.toFixed(2)})</span>
            </div>
            <div class="whatif-row">
                <span class="whatif-lbl">Redundancy:</span>
                <span class="whatif-val">${escapeHTML(d.redundancy_after_failure)}</span>
            </div>
            <div class="whatif-row">
                <span class="whatif-lbl">Weakest module:</span>
                <span class="whatif-val">${escapeHTML(d.degraded.weakest)}</span>
            </div>
            <div class="whatif-assessment">
                <strong>Physics-engine assessment:</strong> ${escapeHTML(d.physics_assessment)}
            </div>
        </div>
    `;
    const view = $('view-topology');
    if (view) view.insertBefore(banner, view.firstChild.nextSibling);
}

async function fetchTopologyState() {
    try {
        const resp = await fetch('/api/topology/state');
        if (!resp.ok) throw new Error('failed: ' + resp.status);
        topologyState = await resp.json();
        applyTopologyState(topologyState);
    } catch (e) {
        console.warn('fetchTopologyState:', e.message);
    }
}

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
        'utility_north-kw': () => fmt0(m.kw) + ' kW',
        'utility_south-kw': () => fmt0(m.kw) + ' kW',
        // Old single utility (kept for backward compat)
        'utility-kw': () => fmt0(m.kw) + ' kW',
        'xfmr_a-winding': () => fmt1(m.winding_c) + '°C',
        'xfmr_b-winding': () => fmt1(m.winding_c) + '°C',
        'ups_a-soc': () => 'SOC ' + Math.round((m.soc || 0) * 100) + '%',
        'ups_b-soc': () => 'SOC ' + Math.round((m.soc || 0) * 100) + '%',
        'hall_1-inlet': () => fmt1(m.inlet_c) + ' °C',
        'hall_1-load': () => fmt0(m.load_kw) + ' kW',
        'hall_2-inlet': () => fmt1(m.inlet_c) + ' °C',
        'hall_2-load': () => fmt0(m.load_kw) + ' kW',
        'hall_3-inlet': () => fmt1(m.inlet_c) + ' °C',
        'hall_3-load': () => fmt0(m.load_kw) + ' kW',
        'cdu_a-q': () => fmt0(m.q_kw) + ' kW',
        'cdu_b-q': () => fmt0(m.q_kw) + ' kW',
        'chiller_1-cop': () => 'COP ' + fmt1(m.cop),
        'chiller_2-cop': () => 'COP ' + fmt1(m.cop),
        'cooling_tower-wb': () => 'WB ' + fmt1(m.wb_c) + '°C',
        'cooling_tower-ecwt': () => 'ECWT ' + fmt1(m.ecwt_c) + '°C',
    };
    Object.keys(updates).forEach((metricId) => {
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
    const toPoints = (arr) => arr.map((v, i) => {
        const x = (i / Math.max(arr.length - 1, 1)) * W;
        const y = top + H - ((v - vmin) / range) * H;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
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
                <span>All physics-validated metrics within design envelope. Site operating in ${escapeHTML(data.redundancy_mode || '2N')} mode at SHI ${(data.site_health || 1).toFixed(2)}.</span>
            </div>`;
        return;
    }
    insightsEl.innerHTML = insights.map((i) =>
        `<div class="ai-mc-insight ai-mc-${i.severity}">
            <span class="ai-mc-icon">${i.icon}</span>
            <span>${escapeHTML(i.text)}</span>
        </div>`,
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
                text: `Transformer thermal imbalance detected: XFMR A ${ta.toFixed(1)}°C vs XFMR B ${tb.toFixed(1)}°C (Δ ${Math.abs(ta - tb).toFixed(1)}°C). Check for asymmetric load distribution.`,
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
            text: `UPS A battery SOC at ${(upsA.metrics.soc * 100).toFixed(0)}% (should be ≥ 90% in standby). Recheck per IEEE 1188 quarterly schedule.`,
        });
    }

    return out;
}

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
        html += `<g class="lld-rack" transform="translate(${x}, ${y})">
            <rect width="${rackW}" height="${rackH}" rx="3" class="lld-rack-rect ${sevClass}"/>
            <text x="${rackW / 2}" y="20" class="lld-rack-id">${escapeHTML(r.id)}</text>
            <text x="${rackW / 2}" y="36" class="lld-rack-sub">GB200 NVL72</text>
            <line x1="10" y1="50" x2="${rackW - 10}" y2="50" stroke="#2A3038"/>
            <text x="10" y="68" class="lld-rack-metric">GPU Tj</text>
            <text x="${rackW - 10}" y="68" class="lld-rack-val" text-anchor="end">${r.gpu_tj_c}°C</text>
            <text x="10" y="88" class="lld-rack-metric">DLC ΔT</text>
            <text x="${rackW - 10}" y="88" class="lld-rack-val" text-anchor="end">${r.dlc_dt_k} K</text>
            <text x="10" y="108" class="lld-rack-metric">Health</text>
            <text x="${rackW - 10}" y="108" class="lld-rack-val" text-anchor="end">${r.health.toFixed(2)}</text>
            <rect x="10" y="125" width="${rackW - 20}" height="6" rx="2" fill="#0B0D10"/>
            <rect x="10" y="125" width="${(rackW - 20) * r.health}" height="6" rx="2" class="lld-rack-fill ${sevClass}"/>
            <text x="${rackW / 2}" y="150" class="lld-rack-status">${escapeHTML(r.severity.toUpperCase())}</text>
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
            <span class="topo-detail-key">${escapeHTML(k)}</span>
            <span class="topo-detail-val">${escapeHTML(formatted)}</span>
        </div>`;
    }).join('');

    bodyEl.innerHTML = `
        <div class="topo-detail-row">
            <span class="topo-detail-key">Severity</span>
            <span class="topo-detail-val sev-${node.severity}">${escapeHTML(node.severity.toUpperCase())}</span>
        </div>
        <div class="topo-detail-row">
            <span class="topo-detail-key">Health</span>
            <span class="topo-detail-val">${node.health.toFixed(2)}</span>
        </div>
        ${metricsHtml}
    `;
    panel.hidden = false;
}

/** Public entry — called once from main.js at bootstrap. */
export function initTopologyView() {
    if (_routeRegistered) return;
    if (!$('view-topology')) {
        console.warn('[topology] #view-topology not in DOM; view disabled.');
        return;
    }
    // Batch 3: generate the HLD from the registry (static SVG retired).
    _renderHld();
    registerRoute('topology', { viewId: 'view-topology', activate: renderTopologyView });
    // Live severity from the Hermes telemetry stream (no 8 s poll).
    _unsubTelemetry = onHermesStream('telemetry', _onTelemetryFrame);
    _routeRegistered = true;
    console.log('[topology] route registered (registry-driven HLD — Batch 3, Hermes-bound)');
}

// ─── Test surface ──────────────────────────────────────────────────
export const __topology_test__ = {
    generateInsights,
    applyTopologyState,
    applyTelemetry: _applyTelemetry,
    onTelemetryFrame: _onTelemetryFrame,
    buildHldMarkup: _buildHldMarkup,
    renderHld: _renderHld,
    renderLLDRacks,
    showWhatIfBanner,
    fmt0,
    fmt1,
    initTopologyView,
    setState: (s) => { topologyState = s; },
    reset: () => {
        _routeRegistered = false;
        topologyState = null;
        currentTopologyTab = 'hld';
        emergencySimMode = false;
        ctSparklineHistory.wb = [];
        ctSparklineHistory.amb = [];
        if (_unsubTelemetry) { _unsubTelemetry(); _unsubTelemetry = null; }
    },
};
