/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — core/asset_engineering.js
 * Diagram Rebuild Batch 5 — per-asset ENGINEERING DETAIL sections
 * for the Power & UPS SLD info panel.
 *
 * Pure module (returns markup strings; no DOM access) so every
 * section is unit-testable. Data origin is stated honestly in each
 * section: live fields come from the power_grid DAG state; rated
 * fields come from asset_metadata nameplates; nothing pretends to
 * be plant telemetry that the simulator does not model.
 *
 * Engineering references:
 *   - UPS operating modes per IEC 62040-3 (VFI-SS-111 class for the
 *     Galaxy VX double conversion path; ECOnversion and maintenance
 *     bypass listed as AVAILABLE modes, explicitly "not modeled").
 *   - Genset sequence per NFPA 110 Type 10 (10 s nameplate start,
 *     fast-forwarded in sim; cooldown before return to standby).
 *   - ATS per ASCO 7000-series bypass-isolation (N/E sources).
 *   - Transformer thermal limit per IEEE C57.12 / insulation
 *     Class F (155 °C).
 *   - Battery per IEEE 1188 (VRLA maintenance).
 * ════════════════════════════════════════════════════════════════ */

import { escapeHTML } from './sanitize.js';

// ─── Pure state helpers ────────────────────────────────────────────

/** IEC 62040-3 operating mode from a power_grid UPS node. */
export function upsMode(node) {
    if (!node) return 'unknown';
    if (node.tripped || node.alive === false) return 'off';
    if (node.on_battery) return 'battery';
    return node.mode || 'double_conversion';
}

/** NFPA 110 phase from a genset node (+ its ATS for ON LOAD). */
export function gensetPhase(node, atsNode) {
    if (!node) return 'unknown';
    if (node.tripped) return 'off';
    if (node.state === 'cranking') return 'cranking';
    if (node.state === 'cooldown') return 'cooldown';
    if (node.running) {
        const loaded = atsNode && atsNode.ats_pos === 'secondary' && atsNode.alive;
        return loaded ? 'on_load' : 'running';
    }
    return 'standby';
}

/** Battery runtime estimate: SOC % of the 5-min design holdup. */
export function runtimeMinutes(soc, holdupMin = 5) {
    const s = Math.max(0, Math.min(100, Number(soc) || 0));
    return (s / 100) * holdupMin;
}

/** VRLA string voltage approximation from SOC (540 V float, 480 V cutoff). */
export function battStringVoltage(soc) {
    const s = Math.max(0, Math.min(100, Number(soc) || 0));
    return 480 + 0.6 * s;
}

/** Transformer loading percentage against the 2.5 MVA nameplate. */
export function xfmrLoadingPct(loadKva, ratedKva = 2500) {
    if (!loadKva || !ratedKva) return 0;
    return Math.max(0, Math.min(150, (loadKva / ratedKva) * 100));
}

// ─── Section builders ──────────────────────────────────────────────

function _bar(pct, label, value, tone = 'ok') {
    const w = Math.max(0, Math.min(100, pct));
    return `<div class="eng-bar-row">
        <span class="eng-bar-lbl">${escapeHTML(label)}</span>
        <span class="eng-bar-track"><span class="eng-bar-fill eng-tone-${tone}" style="width:${w.toFixed(0)}%"></span></span>
        <span class="eng-bar-val">${escapeHTML(value)}</span>
    </div>`;
}

function _origin(text) {
    return `<div class="eng-origin">${escapeHTML(text)}</div>`;
}

// ── UPS: Galaxy VX internal one-line + IEC 62040-3 modes ──────────
// Breaker discipline per the Galaxy switching nomenclature the MOPs
// use: Q1 rectifier input · Q2 static-bypass input · Q3 maintenance
// bypass (external MBP panel) · Q5 battery isolation.
const UPS_MODES = [
    { id: 'double_conversion', label: 'DOUBLE CONVERSION', cls: 'VFI-SS-111 · Q1 path', modeled: true },
    { id: 'battery', label: 'BATTERY', cls: 'inverter on DC bus via Q5', modeled: true },
    { id: 'static_bypass', label: 'STATIC BYPASS', cls: 'SSM (SCR) via Q2 · ms transfer', modeled: false },
    { id: 'econversion', label: 'ECOnversion', cls: 'eco / active filter', modeled: false },
    { id: 'maint_bypass', label: 'MAINT BYPASS', cls: 'Q3 · external MBP — UPS isolated', modeled: false },
];

/**
 * Galaxy breaker POSITIONS per operating mode (the mode-NOMINAL
 * lineup). Pure — and distinct from path energization: in battery
 * mode Q1 stays CLOSED (the breaker does not open itself; the input
 * is simply dead).
 */
export function upsBreakerStates(mode) {
    if (mode === 'maint_bypass') {
        // The MBP wraps the UPS; Q1/Q2/Q4/Q5 open for safe
        // intervention (rectifier + inverter + static bypass +
        // batteries physically isolated, Castell-interlocked).
        return { Q1: 'open', Q2: 'open', Q3: 'closed', Q4: 'open', Q5: 'open' };
    }
    return { Q1: 'closed', Q2: 'closed', Q3: 'open', Q4: 'closed', Q5: 'closed' };
}

/**
 * Map live /api/bms/tags rows to a Q-position object for one UPS.
 * Pure. Tag convention: PWR.UPS_A.Q1_POS .. Q5_POS with enum value
 * "Open" | "Closed". Returns null when no Q tags exist (pre-Q-state
 * deployments degrade to the mode-nominal lineup).
 */
export function parseQTags(tags, upsId) {
    const prefix = 'PWR.' + String(upsId || '').toUpperCase() + '.Q';
    const out = {};
    for (const t of tags || []) {
        if (!t?.id?.startsWith(prefix) || !t.id.endsWith('_POS')) continue;
        const q = t.id.slice(prefix.length - 1).replace('_POS', '');
        out[q] = String(t.current_value).toLowerCase() === 'closed' ? 'closed' : 'open';
    }
    return Object.keys(out).length ? out : null;
}

/**
 * Compare ACTUAL Q positions (BMS telemetry) against the
 * mode-nominal lineup. Returns a list of mismatch strings — the
 * maneuvering-error detector ("Q3 reads CLOSED in double conversion
 * = the MBP was left bridged after maintenance").
 */
export function qMismatches(mode, qActual) {
    if (!qActual) return [];
    const nominal = upsBreakerStates(mode);
    const out = [];
    for (const q of Object.keys(nominal)) {
        if (qActual[q] && qActual[q] !== nominal[q]) {
            let msg = `${q} expected ${nominal[q].toUpperCase()}, reads ${qActual[q].toUpperCase()}`;
            if (q === 'Q3' && qActual.Q3 === 'closed') msg += ' — MBP still bridged?';
            if (q === 'Q5' && qActual.Q5 === 'open') msg += ' — battery isolated: NO holdup';
            out.push(msg);
        }
    }
    return out;
}

// Energized path segments per mode. 'charge' = battery float trickle.
// Topology per the Galaxy one-line: inverter AND static bypass
// converge at the SSM (static switching module), then Q4, then load.
const _UPS_PATHS = {
    double_conversion: ['in1', 'q1', 'rect', 'dc', 'inv', 'ssm', 'q4', 'out', 'q5charge'],
    battery: ['q5', 'batt', 'dc', 'inv', 'ssm', 'q4', 'out'],
    static_bypass: ['in2', 'q2', 'ssm', 'q4', 'out'],
    maint_bypass: ['mbp', 'q3', 'out'],
    off: [],
    unknown: [],
};

function _upsMimic(mode, qActual) {
    const segs = _UPS_PATHS[mode] || [];
    const lit = (s) => (segs.includes(s) ? ' eng-on' : '');
    const charge = segs.includes('q5charge') ? ' eng-charge' : '';
    // ACTUAL positions (BMS Q-state telemetry) override the nominal
    // lineup; a position that disagrees with nominal gets the alarm
    // ring (the maneuvering-error detector, rendered per-breaker).
    const nominal = upsBreakerStates(mode);
    const Q = { ...nominal, ...(qActual || {}) };

    // Breaker glyph: closed = continuous blade; open = blade swung out.
    const breaker = (id, x, y, seg) => {
        const pos = Q[id];
        const mismatch = qActual && qActual[id] && qActual[id] !== nominal[id];
        const blade = pos === 'closed'
            ? `<line class="eng-q-blade" x1="${x - 7}" y1="${y}" x2="${x + 7}" y2="${y}"/>`
            : `<line class="eng-q-blade" x1="${x - 7}" y1="${y}" x2="${x + 4}" y2="${y - 8}"/>`;
        return `<g class="eng-q${lit(seg)}${seg === 'q5' || seg === 'q5charge' ? charge : ''}${mismatch ? ' eng-q-mismatch' : ''}" data-q="${id}" data-pos="${pos}">
            ${mismatch ? `<circle class="eng-q-alarm-ring" cx="${x}" cy="${y}" r="11"/>` : ''}
            <circle class="eng-q-pole" cx="${x - 7}" cy="${y}" r="1.8"/>
            <circle class="eng-q-pole" cx="${x + 7}" cy="${y}" r="1.8"/>
            ${blade}
            <text class="eng-lbl" x="${x}" y="${y + 12}">${id}</text>
        </g>`;
    };

    // Topology per the Galaxy one-line (operator spec): inverter AND
    // static bypass converge at the SSM, then Q4, then the load.
    return `<svg class="eng-mimic" viewBox="0 0 370 206" xmlns="http://www.w3.org/2000/svg">
        <!-- Q3 maintenance bypass rail (external MBP panel) -->
        <path class="eng-wire eng-mbp-rail${lit('mbp')}" d="M14 18 L356 18"/>
        ${breaker('Q3', 180, 18, 'q3')}
        <text class="eng-lbl" x="14" y="10">MBP · EXTERNAL PANEL · Castell interlock</text>
        <path class="eng-wire eng-mbp-rail${lit('mbp')}" d="M14 18 L14 110"/>
        <path class="eng-wire eng-mbp-rail${lit('out')}" d="M356 18 L356 110"/>

        <!-- Static bypass leg: INPUT 2 -> Q2 -> SSM top -->
        <path class="eng-wire${lit('in2')}" d="M14 56 L66 56"/>
        ${breaker('Q2', 80, 56, 'q2')}
        <path class="eng-wire${lit('q2')}" d="M94 56 L284 56 L284 84"/>
        <text class="eng-lbl" x="160" y="48">SCR antiparalelo · 0 ms</text>

        <!-- Main path: INPUT 1 -> Q1 -> PFC RECT -> DC BUS -> INV -> SSM -->
        <path class="eng-wire${lit('in1')}" d="M14 110 L66 110"/>
        ${breaker('Q1', 80, 110, 'q1')}
        <path class="eng-wire${lit('q1')}" d="M94 110 L102 110"/>
        <rect class="eng-box${lit('rect')}" x="102" y="94" width="48" height="32" rx="2"/>
        <text class="eng-txt" x="126" y="110">AC→DC</text>
        <text class="eng-lbl" x="126" y="122">IGBT · THDi&lt;3%</text>
        <path class="eng-wire${lit('dc')}" d="M150 110 L162 110"/>
        <rect class="eng-box eng-dclink${lit('dc')}" x="162" y="104" width="34" height="12" rx="2"/>
        <text class="eng-lbl" x="179" y="98">DC BUS</text>
        <path class="eng-wire${lit('dc')}" d="M196 110 L206 110"/>
        <rect class="eng-box${lit('inv')}" x="206" y="94" width="48" height="32" rx="2"/>
        <text class="eng-txt" x="230" y="110">DC→AC</text>
        <text class="eng-lbl" x="230" y="122">PWM · ±1%</text>
        <path class="eng-wire${lit('inv')}" d="M254 110 L266 110"/>

        <!-- SSM: the common static switching module -> Q4 -> load -->
        <rect class="eng-box eng-ssm${lit('ssm')}" x="266" y="84" width="36" height="42" rx="2"/>
        <text class="eng-txt" x="284" y="108">SSM</text>
        <path class="eng-wire${lit('q4')}" d="M302 110 L312 110"/>
        ${breaker('Q4', 326, 110, 'q4')}
        <path class="eng-wire${lit('out')}" d="M340 110 L356 110"/>

        <!-- Battery branch: DC BUS -> Q5 -> BATT -->
        <path class="eng-wire${lit('q5')}${charge}" d="M179 116 L179 142"/>
        ${breaker('Q5', 179, 152, 'q5')}
        <path class="eng-wire${lit('batt')}${charge}" d="M179 162 L179 172"/>
        <rect class="eng-box eng-batt${lit('batt')}${charge}" x="153" y="172" width="52" height="24" rx="2"/>
        <text class="eng-txt" x="179" y="188">BATT</text>
        <text class="eng-lbl" x="222" y="186">VRLA/Li-ion · BMS · Q5 isol.</text>

        <text class="eng-lbl" x="14" y="124">INPUT 1</text>
        <text class="eng-lbl" x="14" y="70">INPUT 2 (BYP)</text>
        <text class="eng-lbl" x="356" y="124" text-anchor="end">LOAD</text>
    </svg>`;
}

function _upsSection(node, qActual) {
    const mode = upsMode(node);
    const soc = node?.soc ?? null;   // soc lives on the battery node, not here
    const chips = UPS_MODES.map((m) => {
        const active = m.id === mode;
        const dim = !m.modeled && !active;
        return `<span class="eng-chip${active ? ' eng-chip-active' : ''}${dim ? ' eng-chip-dim' : ''}"
            title="${escapeHTML(m.cls + (m.modeled ? '' : ' — available mode, not modeled in sim'))}"
            data-mode="${m.id}">${escapeHTML(m.label)}</span>`;
    }).join('');
    // Q-state mismatch alarms: ACTUAL BMS positions vs mode-nominal.
    const mismatches = qMismatches(mode, qActual);
    const qAlarm = mismatches.length
        ? `<div class="eng-qalarm" data-qalarm="${mismatches.length}">⚠ Q-STATE MISMATCH: `
          + mismatches.map(escapeHTML).join(' · ') + `</div>`
        : '';
    // The switching discipline the MOPs encode: transfer to external
    // maintenance bypass with zero load interruption.
    const mbpSeq = `<div class="eng-seq"><span class="eng-seq-lbl">MBP transfer (MOP-UPS-001):</span>
        INV→bypass → close Q3 → open Q4 → open Q2 → open Q1 → open Q5 — load never drops</div>`;
    const origin = qActual
        ? 'Live: mode + path from grid DAG · Q POSITIONS from BMS tags (PWR.UPS_x.Qn_POS) · VFI-SS-111 per nameplate'
        : 'Live: mode + path from grid DAG · breaker POSITIONS are mode-nominal (Q-state tags unavailable) · VFI-SS-111 per nameplate';
    return `<div class="eng-section" data-eng="ups">
        <div class="sld-info-eyebrow">OPERATING MODE · IEC 62040-3 · GALAXY VX ONE-LINE</div>
        <div class="eng-chips">${chips}</div>
        ${qAlarm}
        ${_upsMimic(mode, qActual)}
        ${soc != null ? _bar(soc, 'SOC', soc.toFixed(0) + ' %', soc < 30 ? 'crit' : soc < 70 ? 'warn' : 'ok') : ''}
        ${mbpSeq}
        ${_origin(origin)}
    </div>`;
}

// ── Genset: NFPA 110 phase strip + state-driven readouts ──────────
const GENSET_PHASES = [
    { id: 'standby', label: 'STANDBY' },
    { id: 'cranking', label: 'CRANKING' },
    { id: 'running', label: 'RUNNING' },
    { id: 'on_load', label: 'ON LOAD' },
    { id: 'cooldown', label: 'COOLDOWN' },
];

// Readouts per phase: [rpm, coolant °C, oil psi, freq Hz]
const _GENSET_READOUTS = {
    standby: [0, 25, 0, null],
    cranking: [900, 32, 18, null],
    running: [1800, 74, 45, 60],
    on_load: [1800, 82, 45, 60],
    cooldown: [1200, 60, 38, null],
    off: [0, 25, 0, null],
    unknown: [0, 25, 0, null],
};

function _gensetSection(node, atsNode) {
    const phase = gensetPhase(node, atsNode);
    const [rpm, coolant, oil, freq] = _GENSET_READOUTS[phase] || _GENSET_READOUTS.unknown;
    const strip = GENSET_PHASES.map((p) =>
        `<span class="eng-phase${p.id === phase ? ' eng-phase-active' : ''}" data-phase="${p.id}">${p.label}</span>`,
    ).join('<span class="eng-phase-arrow">→</span>');
    return `<div class="eng-section" data-eng="genset">
        <div class="sld-info-eyebrow">START SEQUENCE · NFPA 110 TYPE 10</div>
        <div class="eng-phasestrip">${strip}</div>
        <div class="eng-readouts">
            <div class="eng-readout"><span>RPM</span><strong>${rpm}</strong></div>
            <div class="eng-readout"><span>Coolant</span><strong>${coolant} °C</strong></div>
            <div class="eng-readout"><span>Oil</span><strong>${oil} psi</strong></div>
            <div class="eng-readout"><span>Freq</span><strong>${freq == null ? '—' : freq + ' Hz'}</strong></div>
        </div>
        <div class="eng-seq"><span class="eng-seq-lbl">Paralleling:</span>
        ANSI 25 sync check (V · f · phase angle · sequence) · dead-bus black-start
        priority on total loss — first unit at 90% V/f closes onto the dead bus,
        the rest sync AGAINST it (governor + AVR)</div>
        ${_origin('Sim-derived from DAG state (10 s nameplate start fast-fwd 0.8 s) — not live engine telemetry')}
    </div>`;
}

// ── ATS: N/E source position mimic ────────────────────────────────
function _atsSection(node) {
    const pos = node?.transferring ? 'transfer' : (node?.ats_pos === 'secondary' ? 'emergency' : 'normal');
    return `<div class="eng-section" data-eng="ats">
        <div class="sld-info-eyebrow">TRANSFER POSITION · ASCO 7000</div>
        <div class="eng-ats">
            <span class="eng-ats-src${pos === 'normal' ? ' eng-on' : ''}">N · UTILITY</span>
            <span class="eng-ats-sw${pos === 'transfer' ? ' eng-ats-gap' : ''}">${pos === 'transfer' ? '⇄ IN TRANSFER' : '→ LOAD'}</span>
            <span class="eng-ats-src${pos === 'emergency' ? ' eng-on' : ''}">E · GENSET</span>
        </div>
        ${pos === 'transfer' ? '<div class="eng-warn">Load gap — open transition (2 s sim / 10 s NFPA 110 nameplate)</div>' : ''}
        ${_origin('Live: position + transfer state from grid DAG')}
    </div>`;
}

// ── Transformer: Class F thermal margin + loading ─────────────────
function _xfmrSection(node) {
    const winding = node?.alive === false ? 25 : 64;   // sim baseline when energized
    const pct = (winding / 155) * 100;
    return `<div class="eng-section" data-eng="xfmr">
        <div class="sld-info-eyebrow">THERMAL MARGIN · IEEE C57.12 / CLASS F</div>
        ${_bar(pct, 'Winding', winding + ' °C / 155 °C', winding > 130 ? 'crit' : winding > 110 ? 'warn' : 'ok')}
        ${_bar(xfmrLoadingPct(1530), 'Loading', '1.53 / 2.5 MVA', 'ok')}
        ${_origin('Winding: sim baseline · rated loading from nameplate (Dyn11, Z 5.75 %)')}
    </div>`;
}

// ── Battery: SOC + runtime + string voltage ───────────────────────
function _battSection(node) {
    const soc = node?.soc ?? 100;
    const rt = runtimeMinutes(soc);
    const v = battStringVoltage(soc);
    return `<div class="eng-section" data-eng="batt">
        <div class="sld-info-eyebrow">DC PLANT · IEEE 1188 (VRLA)</div>
        ${_bar(soc, 'SOC', soc.toFixed(0) + ' %', soc < 30 ? 'crit' : soc < 70 ? 'warn' : 'ok')}
        <div class="eng-readouts">
            <div class="eng-readout"><span>Runtime est.</span><strong>${rt.toFixed(1)} min</strong></div>
            <div class="eng-readout"><span>String V</span><strong>${v.toFixed(0)} V</strong></div>
            <div class="eng-readout"><span>Cells</span><strong>264</strong></div>
        </div>
        ${_origin('Live: SOC from grid DAG (decays on battery) · runtime = SOC x 5-min design holdup')}
    </div>`;
}

// ── Phase 2 design assets (not deployed — spec sheet emphasis) ────
function _designSection(id) {
    const SPECS = {
        mv_rect_d: ['AC/DC BOUNDARY', '35 kV 3-phase AC in → 800 VDC out. Everything downstream is UNIPOLAR TN-S — no phases exist past this point (S-VOCAB-01).'],
        sscb_d: ['SOLID-STATE CLEARING', 'IEC 60947-2 · 1-100 µs clearing (vs ~50 ms electromechanical). No arc, no moving parts.'],
        dc_bus_d: ['800 VDC UNIPOLAR TN-S', 'Single-pole bus, earthed neutral system. Never "trifásico" — a DC bus has no phases.'],
        bess_d: ['BESS 2.5 MWh', 'Grid-side buffer on the DC bus: ride-through + peak shaving. Bidirectional charge/discharge.'],
        util_d: ['35 kV INTAKE', '3-phase AC utility feed for Building D (the LAST point where phase vocabulary applies).'],
        rpp_d1: ['DC DISTRIBUTION', '800 VDC RPP feeding GB300 NVL144 racks @ 200 kW.'],
        rpp_d2: ['DC DISTRIBUTION', '800 VDC RPP feeding GB300 NVL144 racks @ 200 kW.'],
    };
    const [title, body] = SPECS[id] || ['PHASE 2 DESIGN', 'Path C2 design scope.'];
    return `<div class="eng-section eng-design" data-eng="design">
        <div class="eng-design-badge">DESIGN · PH2 · TARGET Q2 2026 — NOT DEPLOYED</div>
        <div class="sld-info-eyebrow">${escapeHTML(title)}</div>
        <p class="eng-design-body">${escapeHTML(body)}</p>
        ${_origin('Design data only — no live telemetry exists for Phase 2 assets')}
    </div>`;
}

// ─── Dispatcher ────────────────────────────────────────────────────
const _P2_IDS = new Set(['util_d', 'mv_rect_d', 'sscb_d', 'dc_bus_d', 'bess_d', 'rpp_d1', 'rpp_d2', 'hall_d']);

/**
 * Engineering detail markup for one SLD asset.
 * @param {string} id     canonical asset id
 * @param {object} grid   full power_grid state (may be null)
 * @param {object} meta   asset_metadata entry (may be null)
 * @param {object} extras optional live extras: { qStates } from the
 *                        BMS Q-position tags (parseQTags output)
 */
export function engineeringSection(id, grid, meta, extras = {}) {
    if (_P2_IDS.has(id) || meta?.design) return _designSection(id);
    const node = grid?.[id] || null;
    if (id.startsWith('ups_')) {
        // SOC rides on the sibling battery node for the bar.
        const battNode = grid?.['batt_' + id.slice(4)];
        return _upsSection({ ...(node || {}), soc: battNode?.soc ?? null }, extras.qStates || null);
    }
    if (id.startsWith('genset_')) {
        const atsNode = grid?.['ats_' + id.slice(7)];
        return _gensetSection(node, atsNode);
    }
    if (id.startsWith('ats_')) return _atsSection(node);
    if (id.startsWith('xfmr_')) return _xfmrSection(node);
    if (id.startsWith('batt_')) return _battSection(node);
    return '';
}
