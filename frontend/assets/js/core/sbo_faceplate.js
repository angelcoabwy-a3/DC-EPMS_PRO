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

/** Devices behind an SLD element: breaker group, node id or path bank. */
export function devicesFor(target, plant) {
    const devs = (plant && plant.devices) || [];
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
    const head = `${TITLES[kind] || 'Devices'} ${String(path || '').toUpperCase()}`;
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
            + (d.kind === 'transfer' && d.synchro ? synchroscopeHtml(d.id, d.synchro) : '')
            + (d.kind === 'transfer' && d.cubicles
                ? `<button type="button" class="fp-btn fp-field" data-fp-field="${escapeHTML(d.path)}">Field view: 13.8 kV switchgear (racking, springs, 86, padlock)</button>` : '')
            + (d.kind === 'generator' && d.fuel
                ? `<button type="button" class="fp-btn fp-field" data-fp-field="${escapeHTML(d.path)}" data-fp-equip="gen" data-fp-gen="${escapeHTML(Number(String(d.id).slice(-2)) || 1)}">Field view: set panel, day tank, pumps, filter</button>` : '')
            + _commands(d, pending, nowMs) + '</div>';
    }).join('');
    return `<div class="fp-head"><span>${escapeHTML(head)} · SELECT then EXECUTE</span>`
        + '<button type="button" class="fp-close" data-fp-close="1" aria-label="Close">×</button></div>'
        + (message ? `<div class="fp-msg">${escapeHTML(message)}</div>` : '')
        + `<div class="fp-body">${rows}</div>`
        + '<div class="fp-foot">SIMULATED plant · rules enforced by the server · actions in the Forensic Ledger</div>';
}
