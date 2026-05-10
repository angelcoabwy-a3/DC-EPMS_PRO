/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — frontend/assets/js/views/power_ups_iso.js
 *
 * 2.5D Isometric Schematic for Power & UPS SLD.
 *
 *   Lead Architect mandate (2026-05-10):
 *     - Isometric projection via CSS rotateX/rotateZ on container.
 *     - 3D glass blocks via stacked box-shadow + pseudo-elements.
 *     - SVG lines floating above the iso floor with stroke-dashoffset
 *       energy flow animation (cyan A / violet B / amber battery).
 *     - Counter-rotated billboarded labels (readable like flat PDF).
 *     - LIVING ORGANISM: 4 dynamic behaviors driven by state.js:
 *         1. Variable power flow speed bound to load_kw.
 *         2. Thermal pulsing per block via --stress CSS var.
 *         3. Mechanical actuation (ATS arm rotation, genset fan spin).
 *         4. Numeric telemetry jitter (±0.2% every 800ms).
 *
 *   Architecture choice (over pure SVG / pure HTML):
 *     - Hybrid: HTML iso-blocks (cubes via CSS pseudo-elements +
 *       box-shadow stack) + SVG <line> for energy flow (animated
 *       stroke-dashoffset).
 *     - Container gets perspective + transform: rotateX(55) rotateZ(-30).
 *       60/-45 was prescribed but reads too steep — labels become
 *       unreadable. 55/-30 preserves cube recognition + label clarity.
 *
 *   power_sld.js integration:
 *     - Iso-blocks carry `.sld-node` class + `data-sld-node` attr so
 *       power_sld.js simulation state machine drives them via the
 *       same selectors as the legacy SVG.
 *     - The legacy SVG is hidden (display:none) but kept in DOM for
 *       print-fallback / accessibility / future iso-toggle.
 * ════════════════════════════════════════════════════════════════ */

import { getState, subscribe } from '../core/state.js';
import { toggleTrip, getGridState } from '../core/power_grid.js';

// ─── Catalogue: 18 nodes, exact (x,y) match to legacy SVG transforms
const NODES = [
    // Path A
    { id: 'util_a',   type: 'util',   path: 'A', x: 20,  y: 60,  w: 80,  h: 60, label: 'Utility North',   metrics: [{ k: 'kv', t: '27.5 kV',  jitter: false }, { k: 'kw', t: '— kW',    jitter: true }] },
    { id: 'xfmr_a',   type: 'xfmr',   path: 'A', x: 160, y: 50,  w: 60,  h: 80, label: 'XFMR A',          metrics: [{ k: 'c',  t: '— °C',    jitter: true  }, { k: 'load', t: '— kVA', jitter: true }] },
    { id: 'genset_a', type: 'genset', path: 'A', x: 280, y: 55,  w: 70,  h: 70, label: 'Genset A',        metrics: [{ k: 'state', t: 'STANDBY', jitter: false }] },
    { id: 'ats_a',    type: 'ats',    path: 'A', x: 400, y: 60,  w: 60,  h: 50, label: 'ATS-A',           metrics: [{ k: 'pos', t: 'UTILITY', jitter: false }] },
    { id: 'ups_a',    type: 'ups',    path: 'A', x: 520, y: 50,  w: 80,  h: 80, label: 'UPS Galaxy VX A', metrics: [{ k: 'mode', t: 'ONLINE',  jitter: false }, { k: 'load', t: '— kW',  jitter: true }] },
    { id: 'batt_a',   type: 'batt',   path: 'A', x: 540, y: 145, w: 50,  h: 30, label: 'Batt VRLA-A',     metrics: [{ k: 'soc', t: 'SOC 100%', jitter: false }] },
    { id: 'rpp_a1',   type: 'rpp',    path: 'A', x: 660, y: 60,  w: 70,  h: 50, label: 'RPP-A1',          metrics: [{ k: 'kw', t: '— kW',     jitter: true }] },
    { id: 'rpp_a2',   type: 'rpp',    path: 'A', x: 750, y: 60,  w: 70,  h: 50, label: 'RPP-A2',          metrics: [{ k: 'kw', t: '— kW',     jitter: true }] },
    { id: 'busway_a', type: 'busway', path: 'A', x: 840, y: 70,  w: 200, h: 18, label: 'Busway A',        metrics: [{ k: 'load', t: '— kW · — A', jitter: true }] },
    // Path B
    { id: 'util_b',   type: 'util',   path: 'B', x: 20,  y: 400, w: 80,  h: 60, label: 'Utility South',   metrics: [{ k: 'kv', t: '27.5 kV',  jitter: false }, { k: 'kw', t: '— kW',    jitter: true }] },
    { id: 'xfmr_b',   type: 'xfmr',   path: 'B', x: 160, y: 390, w: 60,  h: 80, label: 'XFMR B',          metrics: [{ k: 'c',  t: '— °C',    jitter: true  }, { k: 'load', t: '— kVA', jitter: true }] },
    { id: 'genset_b', type: 'genset', path: 'B', x: 280, y: 395, w: 70,  h: 70, label: 'Genset B',        metrics: [{ k: 'state', t: 'STANDBY', jitter: false }] },
    { id: 'ats_b',    type: 'ats',    path: 'B', x: 400, y: 400, w: 60,  h: 50, label: 'ATS-B',           metrics: [{ k: 'pos', t: 'UTILITY', jitter: false }] },
    { id: 'ups_b',    type: 'ups',    path: 'B', x: 520, y: 390, w: 80,  h: 80, label: 'UPS Galaxy VX B', metrics: [{ k: 'mode', t: 'ONLINE',  jitter: false }, { k: 'load', t: '— kW',  jitter: true }] },
    { id: 'batt_b',   type: 'batt',   path: 'B', x: 540, y: 485, w: 50,  h: 30, label: 'Batt VRLA-B',     metrics: [{ k: 'soc', t: 'SOC 100%', jitter: false }] },
    { id: 'rpp_b1',   type: 'rpp',    path: 'B', x: 660, y: 400, w: 70,  h: 50, label: 'RPP-B1',          metrics: [{ k: 'kw', t: '— kW',     jitter: true }] },
    { id: 'rpp_b2',   type: 'rpp',    path: 'B', x: 750, y: 400, w: 70,  h: 50, label: 'RPP-B2',          metrics: [{ k: 'kw', t: '— kW',     jitter: true }] },
    { id: 'busway_b', type: 'busway', path: 'B', x: 840, y: 410, w: 200, h: 18, label: 'Busway B',        metrics: [{ k: 'load', t: '— kW · — A', jitter: true }] },
];

// ─── Catalogue: 16 lines with exact endpoints (x1,y1)→(x2,y2)
const LINES = [
    { id: 'util_a-xfmr_a',    x1: 100, y1: 90,  x2: 160, y2: 90,  path: 'A', kind: 'flow'    },
    { id: 'xfmr_a-ats_a',     x1: 220, y1: 90,  x2: 400, y2: 85,  path: 'A', kind: 'flow'    },
    { id: 'genset_a-ats_a',   x1: 350, y1: 90,  x2: 400, y2: 90,  path: 'A', kind: 'cold'    },
    { id: 'ats_a-ups_a',      x1: 460, y1: 85,  x2: 520, y2: 90,  path: 'A', kind: 'flow'    },
    { id: 'batt_a-ups_a',     x1: 565, y1: 160, x2: 565, y2: 130, path: 'A', kind: 'battery' },
    { id: 'ups_a-rpp_a1',     x1: 600, y1: 90,  x2: 660, y2: 85,  path: 'A', kind: 'flow'    },
    { id: 'rpp_a1-rpp_a2',    x1: 730, y1: 85,  x2: 750, y2: 85,  path: 'A', kind: 'flow'    },
    { id: 'rpp_a2-busway_a',  x1: 820, y1: 85,  x2: 840, y2: 79,  path: 'A', kind: 'flow'    },
    { id: 'util_b-xfmr_b',    x1: 100, y1: 430, x2: 160, y2: 430, path: 'B', kind: 'flow'    },
    { id: 'xfmr_b-ats_b',     x1: 220, y1: 430, x2: 400, y2: 425, path: 'B', kind: 'flow'    },
    { id: 'genset_b-ats_b',   x1: 350, y1: 430, x2: 400, y2: 430, path: 'B', kind: 'cold'    },
    { id: 'ats_b-ups_b',      x1: 460, y1: 425, x2: 520, y2: 430, path: 'B', kind: 'flow'    },
    { id: 'batt_b-ups_b',     x1: 565, y1: 500, x2: 565, y2: 470, path: 'B', kind: 'battery' },
    { id: 'ups_b-rpp_b1',     x1: 600, y1: 430, x2: 660, y2: 425, path: 'B', kind: 'flow'    },
    { id: 'rpp_b1-rpp_b2',    x1: 730, y1: 425, x2: 750, y2: 425, path: 'B', kind: 'flow'    },
    { id: 'rpp_b2-busway_b',  x1: 820, y1: 425, x2: 840, y2: 419, path: 'B', kind: 'flow'    },
];

const SVG_NS = 'http://www.w3.org/2000/svg';

let _stage   = null;
let _world   = null;
let _flowSvg = null;
let _jitterTimer = null;
let _organicTimer = null;
let _initialized = false;

// ─── DOM construction ─────────────────────────────────────────────

function _buildBlock(node) {
    const el = document.createElement('div');
    el.className = `sld-node sld-iso-block iso-${node.type} iso-path-${node.path.toLowerCase()}`;
    el.dataset.sldNode = node.id;
    el.style.setProperty('--x', node.x);
    el.style.setProperty('--y', node.y);
    el.style.setProperty('--w', node.w);
    el.style.setProperty('--h', node.h);

    // Title bar (label) — counter-rotated for billboard readability
    const title = document.createElement('div');
    title.className = 'iso-block-title';
    title.textContent = node.label;
    el.appendChild(title);

    // Type-specific embellishments
    if (node.type === 'ats') {
        const arm = document.createElement('div');
        arm.className = 'iso-ats-arm';
        arm.dataset.armPos = 'utility';
        el.appendChild(arm);

        const armDots = document.createElement('div');
        armDots.className = 'iso-ats-pivots';
        armDots.innerHTML = '<span></span><span></span><span></span>';
        el.appendChild(armDots);
    } else if (node.type === 'genset') {
        const fan = document.createElement('div');
        fan.className = 'iso-genset-fan';
        fan.innerHTML = '<span></span><span></span><span></span>';
        el.appendChild(fan);
    } else if (node.type === 'xfmr') {
        const coils = document.createElement('div');
        coils.className = 'iso-xfmr-coils';
        coils.innerHTML = '<span></span><span></span>';
        el.appendChild(coils);
    } else if (node.type === 'ups') {
        const wave = document.createElement('div');
        wave.className = 'iso-ups-wave';
        el.appendChild(wave);
    } else if (node.type === 'batt') {
        const cells = document.createElement('div');
        cells.className = 'iso-batt-cells';
        cells.innerHTML = '<span></span><span></span><span></span><span></span>';
        el.appendChild(cells);
    }

    // Trip pip — always-visible breaker button (universal fault injection)
    const tripPip = document.createElement('button');
    tripPip.className = 'iso-trip-pip';
    tripPip.type = 'button';
    tripPip.title = `Trip ${node.label} breaker (shift-click also works)`;
    tripPip.dataset.tripFor = node.id;
    tripPip.textContent = 'TRIP';
    el.appendChild(tripPip);

    // Metrics — counter-rotated
    const metricsBox = document.createElement('div');
    metricsBox.className = 'iso-block-metrics';
    node.metrics.forEach(m => {
        const span = document.createElement('span');
        span.className = 'iso-metric';
        span.dataset.sldMetric = `${node.id}-${m.k}`;
        span.textContent = m.t;
        if (m.jitter) span.dataset.jitter = '1';
        metricsBox.appendChild(span);
    });
    el.appendChild(metricsBox);

    return el;
}

function _buildFlowSvg() {
    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('class', 'sld-iso-flow');
    svg.setAttribute('viewBox', '0 0 1200 720');
    svg.setAttribute('preserveAspectRatio', 'none');
    LINES.forEach(line => {
        const ln = document.createElementNS(SVG_NS, 'line');
        const flowClass =
            line.kind === 'battery' ? 'sld-line-battery' :
            line.kind === 'cold'    ? 'sld-line-cold'    :
            (line.path === 'A'       ? 'sld-line-flow-a' : 'sld-line-flow-b');
        const flowingClass = line.kind === 'cold' ? '' : 'sld-line-flowing';
        ln.setAttribute('class', `sld-line iso-line ${flowClass} ${flowingClass}`.trim());
        ln.setAttribute('x1', line.x1);
        ln.setAttribute('y1', line.y1);
        ln.setAttribute('x2', line.x2);
        ln.setAttribute('y2', line.y2);
        ln.dataset.sldLine = line.id;
        ln.dataset.path = line.path;
        ln.dataset.kind = line.kind;
        svg.appendChild(ln);
    });
    return svg;
}

// ─── Dynamic behaviors ────────────────────────────────────────────

// #1 — VARIABLE POWER FLOW
// Map each line's --flow-duration to its source-node liveness:
//   - dead source: animation suppressed (CSS .is-dead handles)
//   - alive on battery: slower amber rhythm (1.4s)
//   - alive on genset: medium amber (1.0s)
//   - alive on utility + telemetry load: 1.6s..0.45s by load magnitude
function _bindVariableFlow() {
    const apply = () => {
        if (!_flowSvg) return;
        const grid = getState('grid') || getGridState() || {};
        const t = getState('lastTelemetry') || {};
        const loadA = _approxPathLoad(t, 'A');
        const loadB = _approxPathLoad(t, 'B');

        _flowSvg.querySelectorAll('.iso-line').forEach((ln) => {
            const lineId = ln.dataset.sldLine;
            const srcId  = lineId.split('-')[0];
            const src    = grid[srcId];

            // Dead source: line dead (CSS) — duration irrelevant
            if (!src || !src.alive) {
                ln.classList.add('is-dead');
                ln.classList.remove('is-on-battery', 'is-on-genset');
                return;
            }
            ln.classList.remove('is-dead');

            // Energization mode shapes color + duration
            if (src.energized_by === 'battery') {
                ln.classList.add('is-on-battery');
                ln.classList.remove('is-on-genset');
                ln.style.setProperty('--flow-duration', '1.4s');
            } else if (src.energized_by === 'genset') {
                ln.classList.add('is-on-genset');
                ln.classList.remove('is-on-battery');
                ln.style.setProperty('--flow-duration', '0.95s');
            } else {
                ln.classList.remove('is-on-battery', 'is-on-genset');
                const path = ln.dataset.path;
                const load = path === 'A' ? loadA : loadB;
                ln.style.setProperty('--flow-duration', (1.6 - load * 1.15).toFixed(2) + 's');
            }
        });
    };
    subscribe('grid', apply);
    subscribe('lastTelemetry', apply);

    // Organic baseline oscillation when no telemetry: slow sine
    let phase = 0;
    _organicTimer = setInterval(() => {
        phase += 0.07;
        if (!_flowSvg) return;
        const t = getState('lastTelemetry');
        if (t && t.payload) return; // real data is driving — skip organic
        const grid = getState('grid') || {};
        const oscA = (Math.sin(phase) + 1) * 0.15 + 0.40;
        const oscB = (Math.sin(phase + Math.PI / 3) + 1) * 0.15 + 0.40;
        _flowSvg.querySelectorAll('.iso-line').forEach((ln) => {
            if (ln.classList.contains('is-dead')) return;
            if (ln.classList.contains('is-on-battery') || ln.classList.contains('is-on-genset')) return;
            const path = ln.dataset.path;
            const osc  = path === 'A' ? oscA : oscB;
            ln.style.setProperty('--flow-duration', (1.6 - osc * 1.15).toFixed(2) + 's');
        });
    }, 600);
    apply();
}

function _approxPathLoad(telemetry, path) {
    const p = telemetry && telemetry.payload;
    if (p) {
        try {
            const keys = Object.keys(p);
            if (keys.length === 0) return 0.50;
            let sum = 0, n = 0;
            keys.forEach((k) => {
                const ch = p[k];
                if (ch && typeof ch.mean_z === 'number') {
                    sum += Math.min(1, Math.abs(ch.mean_z));
                    n++;
                }
            });
            const avg = n > 0 ? sum / n : 0.5;
            return 0.40 + avg * 0.40;
        } catch (e) {
            return 0.50;
        }
    }
    return 0.50;
}

// #2 — THERMAL & LOAD PULSING
// Stress is now driven from grid state:
//   tripped       -> 0.95 (red)
//   on battery    -> 0.65 (amber)
//   on genset     -> 0.55 (amber)
//   xfmr/ups idle -> 0.25 (modest cyan pulse)
//   nominal       -> 0.12 (calm)
function _bindThermalPulsing() {
    const apply = () => {
        const grid = getState('grid') || {};
        document.querySelectorAll('.sld-iso-block').forEach((b) => {
            const id = b.dataset.sldNode;
            const n = grid[id];
            let stress = 0.12;

            if (n) {
                if (n.tripped)              stress = 0.95;
                else if (!n.alive)          stress = 0.85;
                else if (n.on_battery)      stress = 0.68;
                else if (n.energized_by === 'genset') stress = 0.55;
                else if (n.type === 'xfmr') stress = 0.28;
                else if (n.type === 'ups')  stress = 0.22;
            }

            b.style.setProperty('--stress', stress.toFixed(2));
            b.classList.toggle('stress-amber', stress >= 0.50 && stress < 0.85);
            b.classList.toggle('stress-red',   stress >= 0.85);
        });
    };
    subscribe('grid', apply);
    apply();
}

// #3 — MECHANICAL ACTUATION
// ATS arm follows ats_pos directly from grid state.
// Genset fan classes follow genset.running + ats.transferring.
function _bindMechanicalActuation() {
    const apply = () => {
        const grid = getState('grid') || {};

        // ATS arms (ats_a, ats_b)
        ['ats_a', 'ats_b'].forEach((atsId) => {
            const arm = document.querySelector(`[data-sld-node="${atsId}"] .iso-ats-arm`);
            if (!arm) return;
            const ats = grid[atsId];
            if (!ats) return;
            arm.dataset.armPos =
                ats.transferring        ? 'transferring' :
                ats.ats_pos === 'secondary' ? 'genset' :
                'utility';
        });

        // Genset fans
        ['genset_a', 'genset_b'].forEach((gensetId) => {
            const block = document.querySelector(`[data-sld-node="${gensetId}"]`);
            if (!block) return;
            const g = grid[gensetId];
            if (!g) {
                block.classList.remove('is-running', 'is-warming');
                return;
            }
            // Warming = associated ATS is mid-transfer; running = genset alive
            const atsId = gensetId.replace('genset_', 'ats_');
            const ats = grid[atsId];
            const warming = ats && ats.transferring;
            block.classList.toggle('is-warming', !!warming);
            block.classList.toggle('is-running', !!g.alive && !warming);
        });
    };
    subscribe('grid', apply);
    apply();
}

// Bind .is-selected class on the iso-block matching state.selectedAsset
function _bindSelectionHighlight() {
    const apply = () => {
        const sel = getState('selectedAsset');
        document.querySelectorAll('.sld-iso-block').forEach((b) => {
            b.classList.toggle('is-selected', b.dataset.sldNode === sel);
        });
    };
    subscribe('selectedAsset', apply);
    apply();
}

// Bind alive / dead / tripped / on_battery classes on iso-blocks per grid state
function _bindGridStateToCss() {
    const apply = () => {
        const grid = getState('grid') || {};
        document.querySelectorAll('.sld-iso-block').forEach((b) => {
            const id = b.dataset.sldNode;
            const n = grid[id];
            if (!n) return;
            b.classList.toggle('is-dead',       !n.alive);
            b.classList.toggle('is-tripped',     n.tripped);
            b.classList.toggle('is-on-battery',  n.on_battery);
            b.classList.toggle('is-on-genset',   n.energized_by === 'genset');
        });
        // Update battery SOC text on iso layer
        ['batt_a', 'batt_b'].forEach((bid) => {
            const n = grid[bid];
            if (!n) return;
            document.querySelectorAll(`[data-sld-metric="${bid}-soc"]`).forEach((el) => {
                el.textContent = `SOC ${n.soc}%`;
                if (n.soc < 100) el.dataset.frozen = '1';
                else delete el.dataset.frozen;
            });
        });
    };
    subscribe('grid', apply);
    apply();
}

// Universal fault injection wiring — TRIP pip click + shift-click on block
function _bindTripInjection() {
    const stage = _stage;
    if (!stage) return;
    stage.addEventListener('click', (e) => {
        // TRIP pip — direct toggle
        const pip = e.target.closest('.iso-trip-pip');
        if (pip) {
            e.stopPropagation();
            e.preventDefault();
            const id = pip.dataset.tripFor;
            if (id) toggleTrip(id);
            return;
        }
        // Shift-click on a block = trip toggle (drill is plain click, handled elsewhere)
        if (e.shiftKey) {
            const block = e.target.closest('.sld-iso-block');
            if (block) {
                e.stopPropagation();
                e.preventDefault();
                toggleTrip(block.dataset.sldNode);
            }
        }
    });
}

// #4 — TICKING TELEMETRY (jitter)
// Inject ±0.2% micro-fluctuation into [data-jitter="1"] metric spans
// every 800ms. Skip if any external system has set [data-frozen].
function _startTelemetryJitter() {
    if (_jitterTimer) clearInterval(_jitterTimer);
    _jitterTimer = setInterval(() => {
        document.querySelectorAll('.sld-iso-stage .iso-metric[data-jitter="1"]').forEach(el => {
            if (el.dataset.frozen) return;
            const txt = el.textContent || '';
            const m = txt.match(/(-?\d+\.?\d*)/);
            if (!m) return;
            const base = parseFloat(m[1]);
            if (!isFinite(base) || base === 0) return;
            const jittered = base * (1 + (Math.random() - 0.5) * 0.004); // ±0.2%
            const decimals = base < 1 ? 3 : (base < 10 ? 2 : 1);
            const formatted = jittered.toFixed(decimals);
            el.textContent = txt.replace(/(-?\d+\.?\d*)/, formatted);
        });
    }, 800);
}

// ─── Public API ───────────────────────────────────────────────────

export function initPowerUpsIso() {
    if (_initialized) return;
    const canvas = document.querySelector('#view-power .pid-canvas');
    if (!canvas) return; // view not in DOM
    const oldSvg = canvas.querySelector('.pid-svg');

    // Build iso stage
    _stage = document.createElement('div');
    _stage.className = 'sld-iso-stage';
    _stage.id = 'sld-iso-stage';

    _world = document.createElement('div');
    _world.className = 'sld-iso-world';

    // Floor (gridded plane)
    const floor = document.createElement('div');
    floor.className = 'sld-iso-floor';
    _world.appendChild(floor);

    // Iso blocks (18)
    NODES.forEach(node => _world.appendChild(_buildBlock(node)));

    // Flow lines (16) — translateZ in CSS to elevate above floor
    _flowSvg = _buildFlowSvg();
    _world.appendChild(_flowSvg);

    _stage.appendChild(_world);
    canvas.insertBefore(_stage, oldSvg || null);

    // Hide legacy SVG (kept in DOM as fallback)
    if (oldSvg) oldSvg.classList.add('sld-legacy-hidden');

    // Wire dynamic behaviors + grid-engine bindings
    _bindGridStateToCss();
    _bindSelectionHighlight();
    _bindVariableFlow();
    _bindThermalPulsing();
    _bindMechanicalActuation();
    _bindTripInjection();
    _startTelemetryJitter();

    _initialized = true;
    console.log('[power_ups_iso] 2.5D iso stage mounted, DAG-bound, 5 dynamic behaviors active');
}

export function destroyPowerUpsIso() {
    if (_jitterTimer)  { clearInterval(_jitterTimer);  _jitterTimer = null; }
    if (_organicTimer) { clearInterval(_organicTimer); _organicTimer = null; }
    if (_stage && _stage.parentNode) _stage.parentNode.removeChild(_stage);
    _stage = _world = _flowSvg = null;
    _initialized = false;
}
