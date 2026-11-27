/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — frontend/assets/js/core/sbo_faceplate.js
 *
 * T2: select-before-operate faceplate opened from the Power SLD in
 * LIVE. Pure markup from the GET /api/devices payload; the Power view
 * wires the buttons to POST /api/devices/{id}/authority|select|operate.
 *
 * Two steps, as in the IEC 61850 control model: SELECT (the server
 * re-checks interlocks and arms the command for 30 s) then EXECUTE or
 * CANCEL. Every rule is the server's; a refused command shows the
 * server's own reason. S-SEC-01: everything interpolated is escaped.
 * ════════════════════════════════════════════════════════════════ */

import { escapeHTML } from './sanitize.js';
import { synchroscopeHtml } from './synchroscope.js';

// Lot 12 (ADR-023): Building D nodes of the SLD that open a faceplate.
// The SLD node id is the device id (mv_rect_d, sscb_d_b, ...); the farm
// block (gen_farm_d) opens both per-path farms (one block is drawn).
const _D_NODE = /^(mv_rect_d|sscb_d|bess_d)(_b)?$/;
const _D_TITLES = {
    mv_rect_d: 'Rectifier group', sscb_d: 'Bus main SSCB', bess_d: 'BESS', gen_farm_d: 'Generator farms',
};

/** True when an SLD node id opens a select-before-operate faceplate. */
export function isFaceplateTarget(id) {
    const s = String(id || '');
    return /^(mvtc|genset|ups)_[ab]$/.test(s) || _D_NODE.test(s) || s === 'gen_farm_d';
}

/** Building D path of a faceplate target ('a' | 'b'), null for others. */
export function bldgDPath(target) {
    const m = _D_NODE.exec(String(target || ''));
    return m ? (m[2] ? 'b' : 'a') : null;
}

function _title(target) {
    const s = String(target || '');
    const m = _D_NODE.exec(s);
    if (m) return `${_D_TITLES[m[1]]} D-${m[2] ? 'B' : 'A'}`;
    if (s === 'gen_farm_d') return _D_TITLES.gen_farm_d;
    const [kind, path] = s.split('_');
    return `${TITLES[kind] || 'Devices'} ${String(path || '').toUpperCase()}`;
}

// Bench / training injections offered next to the Building D devices
// (POST /api/bldg-d/inject, FACILITY_MANAGER, recorded in the ledger).
const _D_SIMS = {
    mv_rect_d: (p) => [['utility_loss', 'Simulate utility loss'], ['utility_restore', 'Simulate utility back']]
        .map(([k, l]) => ({ injection: k, path: p, label: `${l} D-${p.toUpperCase()}` })),
    sscb_d: (p) => [{ injection: 'bus_fault', path: p, label: `Simulate 800 VDC bus fault D-${p.toUpperCase()}` }],
    bess_d: () => [{ injection: 'load_step', kw: 12000, delay_s: 10, duration_s: 20,
                     label: 'Simulate hall load step +12 MW in 10 s (20 s)' }],
};

function _simsHtml(target) {
    const m = _D_NODE.exec(String(target || ''));
    if (!m) return '';
    const sims = _D_SIMS[m[1]](m[2] ? 'b' : 'a');
    return '<div class="fp-sims"><span class="fp-sims-label">SIMULATE (bench, ledger)</span>'
        + sims.map((x) => `<button type="button" class="fp-btn fp-sim" data-fp-inject="${escapeHTML(x.injection)}"`
            + (x.path ? ` data-fp-path="${escapeHTML(x.path)}"` : '')
            + (x.kw ? ` data-fp-kw="${escapeHTML(x.kw)}" data-fp-delay="${escapeHTML(x.delay_s)}" data-fp-dur="${escapeHTML(x.duration_s)}"` : '')
            + `>${escapeHTML(x.label)}</button>`).join('')
        + '</div>';
}

/** Devices behind an SLD element: breaker group, node id or path bank. */
export function devicesFor(target, plant) {
    const devs = (plant && plant.devices) || [];
    if (_D_NODE.test(String(target || ''))) return devs.filter((d) => d.id === target);
    if (target === 'gen_farm_d') return devs.filter((d) => d.kind === 'farm');
    const m = /^(mvtc|genset|ups)_([ab])$/.exec(String(target || ''));
    if (!m) return [];
    const [, kind, path] = m;
    if (kind === 'mvtc') return devs.filter((d) => d.kind === 'transfer' && d.path === path);
    if (kind === 'genset') {
        return devs.filter((d) => d.path === path && (d.kind === 'transfer' || d.kind === 'generator'));
    }
    return devs.filter((d) => d.kind === 'ups' && d.path === path);
}

const TITLES = { mvtc: 'MV transfer', genset: 'Generator bus', ups: 'UPS bank' };
const _D_KINDS = new Set(['rectifier', 'sscb', 'bess', 'farm']);

function _readingsHtml(d) {
    const rows = (d.readings || []).map((r) => `<span class="fp-ind">${escapeHTML(r.label)}: `
        + `<b>${escapeHTML(Number(r.value).toLocaleString('en-US'))} ${escapeHTML(r.unit || '')}</b></span>`).join('');
    return rows ? `<div class="fp-inds fp-readings">${rows}</div>` : '';
}

function _commands(d, pending, nowMs) {
    const p = pending.get(d.id);
    if (p) {
        const left = Math.max(0, Math.ceil((p.expiresAt - nowMs) / 1000));
        return `<div class="fp-armed" data-armed="${escapeHTML(d.id)}">`
            + `<span class="fp-armed-label">ARMED · ${escapeHTML(p.label)} · ${left} s</span>`
            + `<button type="button" class="fp-btn fp-exec" data-fp-exec="${escapeHTML(d.id)}">EXECUTE</button>`
            + `<button type="button" class="fp-btn" data-fp-cancel="${escapeHTML(d.id)}">CANCEL</button></div>`;
    }
    const auth = d.authority !== 'REMOTE'
        ? `<button type="button" class="fp-btn fp-auth" data-fp-auth="${escapeHTML(d.id)}" `
          + `title="Commands from this screen need REMOTE">Set REMOTE</button>` : '';
    const cmds = (d.commands || []).map((c) => {
        const dis = c.permitted ? '' : ` disabled title="${escapeHTML(c.blocked_reason || 'Not permitted')}"`;
        return `<button type="button" class="fp-btn" data-fp-select="${escapeHTML(d.id)}" `
            + `data-fp-cmd="${escapeHTML(c.command)}"${dis}>${escapeHTML(c.label)}</button>`;
    }).join('');
    return `<div class="fp-cmds">${auth}${cmds}</div>`;
}

export function faceplateHtml(target, plant, { pending = new Map(), nowMs = Date.now(), message = '' } = {}) {
    const devs = devicesFor(target, plant);
    const [kind, path] = String(target).split('_');
    const head = _title(target);
    if (!devs.length) {
        return `<div class="fp-head"><span>${escapeHTML(head)}</span>`
            + '<button type="button" class="fp-close" data-fp-close="1" aria-label="Close">×</button></div>'
            + '<div class="fp-empty">Plant not reachable: sign in with an operator account.</div>';
    }
    const rows = devs.map((d) => {
        const ind = (d.indications || []).map((i) =>
            `<span class="fp-ind" data-v="${escapeHTML(i.value)}">${escapeHTML(i.label)}: <b>${escapeHTML(i.value)}</b></span>`).join('');
        return `<div class="fp-dev" data-fp-dev="${escapeHTML(d.id)}" data-tone="${escapeHTML(d.status?.tone || 'info')}">`
            + `<div class="fp-dev-head"><b>${escapeHTML(d.display || d.id)}</b>`
            + `<span class="fp-state">${escapeHTML(String(d.state || '').replace(/_/g, ' '))}</span>`
            + `<span class="fp-auth-tag">${escapeHTML(d.authority || '')}</span></div>`
            + `<div class="fp-status">${escapeHTML(d.status?.text || '')}</div>`
            + (ind ? `<div class="fp-inds">${ind}</div>` : '')
            + (_D_KINDS.has(d.kind) ? _readingsHtml(d) : '')
            + (d.kind === 'transfer' && d.synchro ? synchroscopeHtml(d.id, d.synchro) : '')
            + (d.kind === 'transfer' && d.cubicles
                ? `<button type="button" class="fp-btn fp-field" data-fp-field="${escapeHTML(d.path)}">Field view: 13.8 kV switchgear (racking, springs, 86, padlock)</button>` : '')
            + (d.kind === 'transfer' && d.wiring
                ? `<button type="button" class="fp-btn fp-field" data-fp-field="${escapeHTML(d.path)}" data-fp-equip="wiring">Field view: control compartment (PT fuses, TB-1, multimeter)</button>` : '')
            + (d.kind === 'generator' && d.fuel
                ? `<button type="button" class="fp-btn fp-field" data-fp-field="${escapeHTML(d.path)}" data-fp-equip="gen" data-fp-gen="${escapeHTML(Number(String(d.id).slice(-2)) || 1)}">Field view: set panel, day tank, pumps, filter</button>` : '')
            + _commands(d, pending, nowMs) + '</div>';
    }).join('');
    const upsField = kind === 'ups'
        ? `<button type="button" class="fp-btn fp-field" data-fp-field="${escapeHTML(path)}" data-fp-equip="ups">Field view: UPS bank breakers, maintenance bypass, battery QF1</button>`
            + `<button type="button" class="fp-btn fp-field" data-fp-field="${escapeHTML(path)}" data-fp-equip="batt">Field view: battery room (strings, IR, analyzer, H2)</button>` : '';
    return `<div class="fp-head"><span>${escapeHTML(head)} · SELECT then EXECUTE</span>`
        + '<button type="button" class="fp-close" data-fp-close="1" aria-label="Close">×</button></div>'
        + (message ? `<div class="fp-msg">${escapeHTML(message)}</div>` : '')
        + `<div class="fp-body">${upsField}${rows}${_simsHtml(target)}</div>`
        + '<div class="fp-foot">SIMULATED plant · rules enforced by the server · actions in the Forensic Ledger</div>';
}
