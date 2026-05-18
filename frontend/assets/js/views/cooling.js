/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/cooling.js
 * ROADMAP V11 T2.1 — Cooling (DLC) P&ID view extracted from app.js.
 *
 * Phase 2a — behaviour-preserving migration of the cooling P&ID data
 * binder out of the monolithic app.js IIFE. Visual reinvention (2b)
 * and the L3 control plane (2c) land in follow-up commits.
 *
 *   - registerRoute('cooling', …) hands navigation to core/router.js.
 *   - getTopologyState() (services/api.js) fetches the physics-
 *     validated /api/topology/state rollup; the legacy 5 s poll is
 *     preserved here (2a is behaviour-preserving — 2c swaps it for the
 *     Hermes telemetry stream).
 *   - _applyCoolingPid stamps per-node severity + metric text on the
 *     static #view-cooling P&ID SVG, exactly as the IIFE did.
 * ════════════════════════════════════════════════════════════════ */

import { registerRoute } from '../core/router.js';
import { getTopologyState, writeBmsTag, onHermesStream } from '../services/api.js';

let _initialized = false;
let _mode = 'live';            // 'live' | 'whatif'
let _unsubTelemetry = null;
let _modalCmd = null;          // selected START | STOP
const _history = {};           // nodeId -> rolling mean_z buffer
const _SPARK_TICKS = 20;
const _ACTUATOR_TYPES = new Set(['pump']);
const _SPARK_NODES = new Set(['cooling_tower', 'chiller_1', 'chiller_2']);

// ─── P&ID data binder (port of the legacy applyCoolingPid) ─────────
function _applyCoolingPid(data) {
    if (!data) return;
    const nodes = data.hld_nodes || {};

    // Severity -> data-sev on each P&ID node symbol.
    const sevMap = {
        cooling_tower: 'cooling_tower',
        chiller_1: 'chiller_1',
        chiller_2: 'chiller_2',
        cdu_a: 'cdu_a',
        cdu_b: 'cdu_b',
        xfmr_a_p: 'xfmr_a',
        xfmr_b_p: 'xfmr_b',
        grid_a: 'utility_north',
        grid_b: 'utility_south',
    };
    Object.entries(sevMap).forEach(([pidNodeId, dataNodeId]) => {
        const nodeData = nodes[dataNodeId];
        if (!nodeData) return;
        const el = document.querySelector(`.pid-node[data-node="${pidNodeId}"]`);
        const symbol = el && el.querySelector('.pid-symbol');
        if (symbol) symbol.setAttribute('data-sev', nodeData.severity || 'ok');
    });

    const ct = nodes.cooling_tower;
    const ch1 = nodes.chiller_1;
    const ch2 = nodes.chiller_2;
    const cda = nodes.cdu_a;
    const cdb = nodes.cdu_b;
    const xfa = nodes.xfmr_a;
    const xfb = nodes.xfmr_b;
    const ga = nodes.utility_north;
    const gb = nodes.utility_south;
    const h1 = nodes.hall_1;

    const set = (k, v) => {
        const el = document.querySelector(`[data-pid-metric="${k}"]`);
        if (el) el.textContent = v;
    };
    if (ct) {
        set('ct-wb', 'WB ' + (ct.metrics.wb_c?.toFixed(1) ?? '—') + '°C');
        set('ct-ecwt', 'ECWT ' + (ct.metrics.ecwt_c?.toFixed(1) ?? '—') + '°C');
    }
    if (ch1) set('ch1-cop', 'COP ' + (ch1.metrics.cop?.toFixed(1) ?? '—'));
    if (ch2) set('ch2-cop', 'COP ' + (ch2.metrics.cop?.toFixed(1) ?? '—'));
    if (cda) {
        set('cdua-q', Math.round(cda.metrics.q_kw ?? 0).toLocaleString() + ' kW');
        set('cdua-supply', 'SUP ' + (h1?.metrics.inlet_c?.toFixed(0) ?? '18') + '°C');
    }
    if (cdb) {
        set('cdub-q', Math.round(cdb.metrics.q_kw ?? 0).toLocaleString() + ' kW');
        set('cdub-supply', 'SUP ' + (h1?.metrics.inlet_c?.toFixed(0) ?? '18') + '°C');
    }
    if (xfa) set('xfmr-a-c', (xfa.metrics.winding_c?.toFixed(0) ?? '—') + '°C');
    if (xfb) set('xfmr-b-c', (xfb.metrics.winding_c?.toFixed(0) ?? '—') + '°C');
    if (ga) set('grid-a-kw', Math.round(ga.metrics.kw ?? 0).toLocaleString() + ' kW');
    if (gb) set('grid-b-kw', Math.round(gb.metrics.kw ?? 0).toLocaleString() + ' kW');

    // GPU Tj from rack data.
    if (Array.isArray(data.lld_racks) && data.lld_racks.length > 0) {
        const maxTj = Math.max(...data.lld_racks.map((r) => r.gpu_tj_c || 0));
        set('rack-tj', 'GPU Tj max: ' + maxTj.toFixed(1) + '°C');
    }

    // Failover + redundancy banner.
    const banner = document.getElementById('pid-banner-mode');
    const bannerSub = document.getElementById('pid-banner-sub');
    const bannerShi = document.getElementById('pid-banner-shi');
    const failLine = document.getElementById('pid-failover-line');
    const failText = document.getElementById('pid-failover-text');

    const mode = data.redundancy_mode || '2N';
    if (banner) {
        banner.textContent = mode;
        banner.setAttribute('data-mode', mode);
    }
    if (bannerSub) {
        bannerSub.textContent = ({
            '2N': 'Path Diversity Active',
            'N+1': 'One side degraded',
            'N': 'NON-REDUNDANT — investigate',
        })[mode] || mode;
    }
    if (bannerShi) bannerShi.textContent = (data.site_health ?? 0).toFixed(2);

    const showFailover = (mode === 'N');
    if (failLine) failLine.setAttribute('opacity', showFailover ? '0.9' : '0');
    if (failText) failText.setAttribute('opacity', showFailover ? '1' : '0');

    const meta = document.getElementById('pid-meta');
    if (meta) {
        meta.innerHTML = `<strong>${mode}</strong> · SHI `
            + `${(data.site_health ?? 0).toFixed(2)} · weakest `
            + `<em>${data.weakest_module || '—'}</em>`;
    }
}

// ════════════════════════════════════════════════════════════════
//  PHASE 2b — orthogonal thermodynamic SCADA SLD
//
//  Replaces the hand-authored P&ID SVG with a programmatic generator.
//  5 fixed tier columns (Heat Rejection -> Chillers -> Pumps -> CDU ->
//  Load), strict grid alignment; every pipe a pure 90° run. Chilled-
//  water SUPPLY glows blue, warm RETURN glows warm. Nodes keep the
//  data-node / .pid-symbol / data-pid-metric hooks so the (unchanged)
//  _applyCoolingPid binder drives severity + metrics.
// ════════════════════════════════════════════════════════════════
const _COOL = { supplyY: 196, returnY: 432 };

function _coolSymbol(type, x, y) {
    if (type === 'pump') {
        return `<circle class="pid-symbol cool-sym" data-sev="ok" cx="${x}" cy="${y}" r="21"/>`
            + `<path class="cool-glyph" d="M${x - 9} ${y} L${x + 8} ${y - 8} `
            + `L${x + 8} ${y + 8} Z"/>`;
    }
    if (type === 'tower') {
        return `<rect class="pid-symbol cool-sym" data-sev="ok" x="${x - 42}" `
            + `y="${y - 32}" width="84" height="64" rx="3"/>`
            + `<path class="cool-fin" d="M${x - 30} ${y - 14} H${x + 30} `
            + `M${x - 30} ${y + 2} H${x + 30} M${x - 30} ${y + 18} H${x + 30}"/>`;
    }
    const w = type === 'hall' ? 100 : (type === 'crah' ? 56 : 80);
    const h = type === 'hall' ? 58 : (type === 'crah' ? 34 : 46);
    return `<rect class="pid-symbol cool-sym" data-sev="ok" x="${x - w / 2}" `
        + `y="${y - h / 2}" width="${w}" height="${h}" rx="2.5"/>`;
}

function _coolNode(id, type, label, x, y, metrics) {
    const m = metrics.map((mm, i) =>
        `<text class="cool-metric" data-pid-metric="${mm.key}" x="${x}" `
        + `y="${y + 42 + i * 13}">${mm.text}</text>`).join('');
    const isAct = _ACTUATOR_TYPES.has(type);
    const actAttr = isAct ? ' data-actuator="1" tabindex="0" role="button"' : '';
    let spark = '';
    if (_SPARK_NODES.has(id)) {
        const sy = y + 42 + metrics.length * 13 + 11;
        spark = `<polyline class="cool-spark" data-spark="${id}" `
            + `data-sx="${x - 26}" data-sy="${sy}" data-sw="52" data-sh="12" `
            + `points=""/>`;
    }
    return `<g class="pid-node cool-node${isAct ? ' cool-actuator' : ''}" `
        + `data-node="${id}"${actAttr}>`
        + _coolSymbol(type, x, y)
        + `<text class="cool-name" x="${x}" y="${y - 38}">${label}</text>`
        + m + spark + `</g>`;
}

// Orthogonal pipe — caller passes axis-aligned waypoints only.
function _coolPipe(points, kind) {
    const d = points.map((p, i) => (i === 0 ? 'M' : 'L') + p[0] + ' ' + p[1]).join(' ');
    return `<path class="cool-pipe cool-${kind}" d="${d}"/>`;
}

/** Build the full thermodynamic SLD inner markup. */
function _buildCoolingSld() {
    const S = _COOL.supplyY;   // chilled-water supply header
    const R = _COOL.returnY;   // warm-water return header
    const T = { rej: 128, chiller: 322, pump: 506, cdu: 694, load: 902 };

    const tiers = [
        ['HEAT REJECTION', T.rej], ['CHILLER PLANT', T.chiller],
        ['CHW PUMPS', T.pump], ['CDU / DLC', T.cdu], ['IT LOAD', T.load],
    ];
    const rails = tiers.map(([name, x]) =>
        `<line class="cool-tier-rail" x1="${x}" y1="44" x2="${x}" y2="586"/>`
        + `<text class="cool-tier-label" x="${x}" y="30">${name}</text>`).join('');

    // ── orthogonal piping ──
    const pipes = [
        // chilled-water supply header (cold) — tower up, then across
        _coolPipe([[T.rej, 282], [T.rej, S], [T.load, S]], 'supply'),
        // warm return header — load down, back across, into the tower
        _coolPipe([[T.load, 274], [T.load, R], [T.rej, R], [T.rej, 346]], 'return'),
        // chiller / pump / CDU taps off the supply header
        _coolPipe([[T.chiller, S], [T.chiller, 173]], 'supply'),
        _coolPipe([[T.chiller, S], [T.chiller, 247]], 'supply'),
        _coolPipe([[T.pump, S], [T.pump, 175]], 'supply'),
        _coolPipe([[T.pump, S], [T.pump, 245]], 'supply'),
        _coolPipe([[T.cdu, S], [T.cdu, 173]], 'supply'),
        _coolPipe([[T.cdu, S], [T.cdu, 247]], 'supply'),
        // CRAH warm-air drops below the IT load
        _coolPipe([[T.load, R], [T.load, 470]], 'return'),
        _coolPipe([[845, 470], [959, 470]], 'return'),
        _coolPipe([[845, 470], [845, 488]], 'return'),
        _coolPipe([[959, 470], [959, 488]], 'return'),
    ].join('');

    // ── equipment nodes ──
    const nodes = [
        _coolNode('cooling_tower', 'tower', 'COOLING TOWER', T.rej, 314,
            [{ key: 'ct-wb', text: 'WB —°C' }, { key: 'ct-ecwt', text: 'ECWT —°C' }]),
        _coolNode('chiller_1', 'chiller', 'CHILLER 1', T.chiller, 150,
            [{ key: 'ch1-cop', text: 'COP —' }]),
        _coolNode('chiller_2', 'chiller', 'CHILLER 2 · N+1', T.chiller, 270,
            [{ key: 'ch2-cop', text: 'COP —' }]),
        _coolNode('chwp_1', 'pump', 'CHW PUMP A', T.pump, 154, []),
        _coolNode('chwp_2', 'pump', 'CHW PUMP B', T.pump, 266, []),
        _coolNode('cdu_a', 'cdu', 'CDU-A', T.cdu, 150,
            [{ key: 'cdua-q', text: '— kW' }, { key: 'cdua-supply', text: 'SUP —°C' }]),
        _coolNode('cdu_b', 'cdu', 'CDU-B', T.cdu, 270,
            [{ key: 'cdub-q', text: '— kW' }, { key: 'cdub-supply', text: 'SUP —°C' }]),
        _coolNode('data_hall', 'hall', 'DATA HALL', T.load, 222,
            [{ key: 'rack-tj', text: 'GPU Tj —°C' }]),
        _coolNode('crah_1', 'crah', 'CRAH-1', 845, 506, []),
        _coolNode('crah_2', 'crah', 'CRAH-2', 959, 506, []),
    ].join('');

    return rails + pipes + nodes;
}

/** Render the orthogonal cooling SLD into the legacy .pid-svg. */
function _renderCoolingSld() {
    const svg = document.querySelector('#view-cooling .pid-svg');
    if (!svg) return;
    svg.setAttribute('viewBox', '0 0 1040 620');
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    svg.classList.add('cool-svg');
    svg.innerHTML = _buildCoolingSld();
}

// ════════════════════════════════════════════════════════════════
//  PHASE 2c — L3 control plane (actuation · What-If · sparklines)
//
//  Mirrors the Power SLD L3 plane: CHW pumps are clickable actuators
//  (RBAC-gated /api/bms/write), a LIVE<->WHAT-IF sandbox isolates the
//  view from the Hermes feed, and critical nodes carry telemetry
//  sparklines. Cooling has no DAG cascade engine, so a What-If click
//  toggles a LOCAL simulated fault on the node (no backend write).
// ════════════════════════════════════════════════════════════════
function _bmsTagFor(nodeId) {
    // chwp_1 -> HVAC.CHWP1.STATUS  (ISA-95 registry tag, writable BO).
    return 'HVAC.' + nodeId.replace('chwp_', 'CHWP').toUpperCase() + '.STATUS';
}

function _closePumpModal() {
    const m = document.getElementById('cool-pump-modal');
    if (m) m.hidden = true;
}

function _ensurePumpModal() {
    let modal = document.getElementById('cool-pump-modal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'cool-pump-modal';
    modal.className = 'pwr-modal-overlay';
    modal.hidden = true;
    modal.innerHTML = `
        <div class="pwr-modal" role="dialog" aria-modal="true" aria-labelledby="cool-modal-title">
            <div class="pwr-modal-hdr">
                <span class="pwr-modal-icon">&#10052;</span>
                <h3 id="cool-modal-title">CHW Pump Control</h3>
            </div>
            <div class="pwr-modal-body">
                <p class="pwr-modal-target">Target pump:
                    <strong data-field="target">&mdash;</strong></p>
                <label class="pwr-modal-lbl">Command</label>
                <div class="pwr-modal-cmds">
                    <button type="button" class="pwr-cmd-btn" data-cmd="START">START PUMP</button>
                    <button type="button" class="pwr-cmd-btn" data-cmd="STOP">STOP PUMP</button>
                </div>
                <label class="pwr-modal-lbl" for="cool-modal-role">Actor role (RBAC claim)</label>
                <select id="cool-modal-role" class="pwr-modal-select">
                    <option value="TECH_L4">TECH_L4</option>
                    <option value="SENIOR_TECH_L5">SENIOR_TECH_L5</option>
                    <option value="SME_L6" selected>SME_L6</option>
                </select>
                <div class="pwr-modal-result" data-field="result"></div>
            </div>
            <div class="pwr-modal-foot">
                <button type="button" class="btn btn-secondary" data-act="cancel">Cancel</button>
                <button type="button" class="btn" data-act="confirm" disabled>Confirm actuation</button>
            </div>
        </div>`;
    document.body.appendChild(modal);
    modal.addEventListener('click', (e) => {
        if (e.target === modal || e.target.dataset.act === 'cancel') {
            _closePumpModal();
            return;
        }
        const cmdBtn = e.target.closest('.pwr-cmd-btn');
        if (cmdBtn) {
            _modalCmd = cmdBtn.dataset.cmd;
            modal.querySelectorAll('.pwr-cmd-btn').forEach((b) =>
                b.classList.toggle('is-sel', b === cmdBtn));
            modal.querySelector('[data-act="confirm"]').disabled = false;
            return;
        }
        if (e.target.dataset.act === 'confirm') {
            _submitPumpCommand(
                modal.dataset.nodeId, _modalCmd,
                modal.querySelector('#cool-modal-role').value,
            );
        }
    });
    return modal;
}

function _openPumpModal(nodeId, label) {
    const modal = _ensurePumpModal();
    _modalCmd = null;
    modal.dataset.nodeId = nodeId;
    modal.querySelector('[data-field="target"]').textContent = label || nodeId;
    const r = modal.querySelector('[data-field="result"]');
    r.textContent = '';
    r.className = 'pwr-modal-result';
    modal.querySelectorAll('.pwr-cmd-btn').forEach((b) => b.classList.remove('is-sel'));
    modal.querySelector('[data-act="confirm"]').disabled = true;
    modal.hidden = false;
}

async function _submitPumpCommand(nodeId, cmd, actorRole) {
    const modal = document.getElementById('cool-pump-modal');
    if (!modal || !cmd) return;
    const result = modal.querySelector('[data-field="result"]');
    result.className = 'pwr-modal-result is-pending';
    result.textContent = 'Issuing command to BMS control surface…';
    const { ok, status, data } = await writeBmsTag({
        tag_id: _bmsTagFor(nodeId),
        value: cmd === 'START' ? 'On' : 'Off',
        user: 'cooling-sld-operator',
        actor_role: actorRole,
    });
    if (status === 403) {
        result.className = 'pwr-modal-result is-denied';
        result.textContent = `RBAC DENIED — ${data.detail || 'SME_L6 required for BMS write'}`;
        return;
    }
    if (!ok) {
        result.className = 'pwr-modal-result is-err';
        result.textContent = `Command rejected — ${data.detail || ('HTTP ' + status)}`;
        return;
    }
    result.className = 'pwr-modal-result is-ok';
    result.textContent = `✓ ${cmd} accepted — ${data.message || nodeId}`;
}

/** SVG click delegation — routes a node click by current mode. */
function _onCoolClick(e) {
    const node = e.target.closest('.cool-node');
    if (!node) return;
    const id = node.dataset.node;
    if (_mode === 'whatif') {
        // Sandbox: toggle a LOCAL simulated fault on the node — no backend.
        const sym = node.querySelector('.pid-symbol');
        if (sym) {
            sym.setAttribute('data-sev',
                sym.getAttribute('data-sev') === 'critical' ? 'ok' : 'critical');
        }
        return;
    }
    if (node.dataset.actuator) {
        const label = node.querySelector('.cool-name');
        _openPumpModal(id, label ? label.textContent : id);
    }
}

// ── What-If sandbox toggle ──
function _setMode(mode) {
    _mode = (mode === 'whatif') ? 'whatif' : 'live';
    const view = document.getElementById('view-cooling');
    if (view) view.classList.toggle('cool-whatif', _mode === 'whatif');
    const btn = document.getElementById('cool-mode-toggle');
    if (btn) {
        btn.textContent = _mode === 'whatif'
            ? '⚠ WHAT-IF SIMULATION' : '◉ LIVE TELEMETRY';
        btn.dataset.mode = _mode;
    }
    if (_mode === 'live') _refresh();   // re-sync from live topology
}

function _buildModeToggle() {
    if (document.getElementById('cool-mode-toggle')) return;
    const view = document.getElementById('view-cooling');
    if (!view) return;
    const btn = document.createElement('button');
    btn.id = 'cool-mode-toggle';
    btn.type = 'button';
    btn.className = 'pwr-mode-toggle';
    btn.dataset.mode = 'live';
    btn.textContent = '◉ LIVE TELEMETRY';
    btn.title = 'Toggle LIVE telemetry <-> isolated WHAT-IF simulation sandbox';
    btn.addEventListener('click', () => _setMode(_mode === 'live' ? 'whatif' : 'live'));
    const bar = view.querySelector('.pid-action-bar') || view;
    bar.insertBefore(btn, bar.firstChild);
}

// ── Telemetry sparklines (last 20 Kalman ticks) ──
function _siteMeanZ(channels) {
    const ids = channels ? Object.keys(channels) : [];
    if (!ids.length) return 0;
    let sum = 0;
    for (const c of ids) sum += Math.abs(Number(channels[c].mean_z) || 0);
    return sum / ids.length;
}

function _sparkPoints(values, sx, sy, sw, sh) {
    if (!values || values.length < 2) return '';
    const lo = Math.min(...values);
    const span = (Math.max(...values) - lo) || 1;
    const step = sw / (values.length - 1);
    return values.map((v, i) => {
        const px = sx + i * step;
        const py = sy - ((v - lo) / span - 0.5) * sh;
        return `${px.toFixed(1)},${py.toFixed(1)}`;
    }).join(' ');
}

function _updateSparklines(channels) {
    const ids = channels ? Object.keys(channels) : [];
    const siteAvg = _siteMeanZ(channels);
    _SPARK_NODES.forEach((nodeId) => {
        const poly = document.querySelector(
            `#view-cooling .pid-svg [data-spark="${nodeId}"]`);
        if (!poly) return;
        const matched = ids.filter((c) => c.toLowerCase().includes(nodeId.toLowerCase()));
        const v = matched.length
            ? matched.reduce((s, c) => s + Math.abs(Number(channels[c].mean_z) || 0), 0)
              / matched.length
            : siteAvg;
        const hist = _history[nodeId] || (_history[nodeId] = []);
        hist.push(v);
        if (hist.length > _SPARK_TICKS) hist.shift();
        poly.setAttribute('points', _sparkPoints(
            hist, Number(poly.dataset.sx), Number(poly.dataset.sy),
            Number(poly.dataset.sw), Number(poly.dataset.sh)));
    });
}

function _onTelemetryFrame(payload) {
    if (_mode === 'whatif') return;   // sandbox — feed disconnected
    if (payload && payload.channels) _updateSparklines(payload.channels);
}

// ─── Data refresh + routing ────────────────────────────────────────
async function _refresh() {
    try {
        _applyCoolingPid(await getTopologyState());
    } catch (e) {
        console.warn('[cooling] topology fetch failed:', e.message);
    }
}

function _activate() {
    // Baseline topology once per activation — the recurring 5 s poll is
    // eradicated; live trend now arrives on the Hermes telemetry stream.
    _refresh();
}

/** Public entry — called once from main.js at bootstrap. */
export function initCoolingView() {
    if (_initialized) return;
    if (!document.getElementById('view-cooling')) {
        console.warn('[cooling] #view-cooling not in DOM; view disabled.');
        return;
    }
    registerRoute('cooling', { viewId: 'view-cooling', activate: _activate });
    // Phase 2b: render the orthogonal thermodynamic SLD into .pid-svg.
    _renderCoolingSld();
    // Phase 2c L3: clickable actuators + What-If sandbox + Hermes sparklines.
    const svg = document.querySelector('#view-cooling .pid-svg');
    if (svg) svg.addEventListener('click', _onCoolClick);
    _buildModeToggle();
    _unsubTelemetry = onHermesStream('telemetry', _onTelemetryFrame);
    _initialized = true;
    console.log('[cooling] view ready (L3 thermodynamic SCADA SLD — T2.1)');
}

// ─── Test surface ──────────────────────────────────────────────────
export const __cooling_test__ = {
    applyCoolingPid: _applyCoolingPid,
    buildCoolingSld: _buildCoolingSld,
    renderCoolingSld: _renderCoolingSld,
    bmsTagFor: _bmsTagFor,
    openPumpModal: _openPumpModal,
    submitPumpCommand: _submitPumpCommand,
    onCoolClick: _onCoolClick,
    setMode: _setMode,
    getMode: () => _mode,
    buildModeToggle: _buildModeToggle,
    sparkPoints: _sparkPoints,
    updateSparklines: _updateSparklines,
    reset: () => {
        _initialized = false;
        _mode = 'live';
        if (_unsubTelemetry) { _unsubTelemetry(); _unsubTelemetry = null; }
        const modal = document.getElementById('cool-pump-modal');
        if (modal) modal.remove();
        for (const k of Object.keys(_history)) delete _history[k];
    },
};
