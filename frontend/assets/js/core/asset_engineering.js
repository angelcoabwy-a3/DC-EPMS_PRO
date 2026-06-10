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

// ── UPS: IEC 62040-3 modes + internal power-path mimic ────────────
const UPS_MODES = [
    { id: 'double_conversion', label: 'DOUBLE CONVERSION', cls: 'VFI-SS-111', modeled: true },
    { id: 'battery', label: 'BATTERY', cls: 'inverter on DC bus', modeled: true },
    { id: 'static_bypass', label: 'STATIC BYPASS', cls: 'SSM transfer', modeled: false },
    { id: 'econversion', label: 'ECOnversion', cls: 'eco / active filter', modeled: false },
    { id: 'maint_bypass', label: 'MAINT BYPASS', cls: 'external MBB', modeled: false },
];

function _upsMimic(mode) {
    // Active path per mode: double_conversion = IN->RECT->DC->INV->OUT,
    // battery = BATT->DC->INV->OUT (rectifier dark), off = all dark.
    const on = (seg) => {
        if (mode === 'double_conversion') return ['in', 'rect', 'dc', 'inv', 'out'].includes(seg) ? ' eng-on' : '';
        if (mode === 'battery') return ['batt', 'dc', 'inv', 'out'].includes(seg) ? ' eng-on' : '';
        return '';
    };
    return `<svg class="eng-mimic" viewBox="0 0 300 130" xmlns="http://www.w3.org/2000/svg">
        <path class="eng-wire eng-bypass-rail" d="M14 28 L286 28"/>
        <rect class="eng-box eng-ssm" x="130" y="16" width="40" height="24" rx="2"/>
        <text class="eng-txt" x="150" y="32">SSM</text>
        <text class="eng-lbl" x="150" y="10">STATIC BYPASS RAIL</text>
        <path class="eng-wire${on('in')}" d="M14 70 L62 70"/>
        <rect class="eng-box${on('rect')}" x="62" y="54" width="44" height="32" rx="2"/>
        <text class="eng-txt" x="84" y="74">AC→DC</text>
        <path class="eng-wire${on('dc')}" d="M106 70 L150 70"/>
        <rect class="eng-box eng-dclink${on('dc')}" x="150" y="64" width="34" height="12" rx="2"/>
        <text class="eng-lbl" x="167" y="56">DC LINK</text>
        <path class="eng-wire${on('dc')}" d="M184 70 L196 70"/>
        <rect class="eng-box${on('inv')}" x="196" y="54" width="44" height="32" rx="2"/>
        <text class="eng-txt" x="218" y="74">DC→AC</text>
        <path class="eng-wire${on('out')}" d="M240 70 L286 70"/>
        <path class="eng-wire${on('batt')}" d="M167 76 L167 102"/>
        <rect class="eng-box eng-batt${on('batt')}" x="143" y="102" width="48" height="22" rx="2"/>
        <text class="eng-txt" x="167" y="117">BATT</text>
        <text class="eng-lbl" x="14" y="84">INPUT</text>
        <text class="eng-lbl" x="286" y="84" text-anchor="end">OUTPUT</text>
    </svg>`;
}

function _upsSection(node) {
    const mode = upsMode(node);
    const soc = node?.soc ?? null;   // soc lives on the battery node, not here
    const chips = UPS_MODES.map((m) => {
        const active = m.id === mode;
        const dim = !m.modeled && !active;
        return `<span class="eng-chip${active ? ' eng-chip-active' : ''}${dim ? ' eng-chip-dim' : ''}"
            title="${escapeHTML(m.cls + (m.modeled ? '' : ' — available mode, not modeled in sim'))}"
            data-mode="${m.id}">${escapeHTML(m.label)}</span>`;
    }).join('');
    return `<div class="eng-section" data-eng="ups">
        <div class="sld-info-eyebrow">OPERATING MODE · IEC 62040-3</div>
        <div class="eng-chips">${chips}</div>
        ${_upsMimic(mode)}
        ${soc != null ? _bar(soc, 'SOC', soc.toFixed(0) + ' %', soc < 30 ? 'crit' : soc < 70 ? 'warn' : 'ok') : ''}
        ${_origin('Live: mode + path from grid DAG · class VFI-SS-111 per nameplate')}
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
 */
export function engineeringSection(id, grid, meta) {
    if (_P2_IDS.has(id) || meta?.design) return _designSection(id);
    const node = grid?.[id] || null;
    if (id.startsWith('ups_')) {
        // SOC rides on the sibling battery node for the bar.
        const battNode = grid?.['batt_' + id.slice(4)];
        return _upsSection({ ...(node || {}), soc: battNode?.soc ?? null });
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
