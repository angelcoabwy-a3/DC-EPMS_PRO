/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — frontend/assets/js/core/alarm_state.js
 *
 * HMI H4: alarm banner support for the Power SLD.
 *
 *   1. AlarmEngine: the same ISA-18.2 style state model as
 *      backend/alarm_engine.py (NORM / UNACK / ACKED / RTNUN). Used
 *      ONLY for the What-If sandbox: sandbox alarms are acknowledged
 *      locally and never reach the backend or the Forensic Ledger.
 *      Live alarms come from GET /api/alarms (backend state).
 *   2. conditionsFromGrid(grid): alarm conditions from the What-If DAG
 *      (core/power_grid.js) via pathStatus (core/power_status.js).
 *   3. alarmBannerHtml(view): markup for the banner (escaped, S-SEC-01).
 *
 * Times: epoch ms. Displayed as local HH:MM:SS.mmm with the ISO UTC
 * string in the tooltip. Resolution is ms; accuracy is the evaluation
 * interval (sandbox: each DAG change; live: the poll), not field SOE.
 * ════════════════════════════════════════════════════════════════ */

import { pathStatus } from './power_status.js';
import { escapeHTML } from './sanitize.js';

export const NORM = 'NORM';
export const UNACK = 'UNACK';
export const ACKED = 'ACKED';
export const RTNUN = 'RTNUN';
export const PRIORITIES = Object.freeze(['HIGH', 'MEDIUM', 'LOW']);
const RANK = { HIGH: 0, MEDIUM: 1, LOW: 2 };

export class AlarmEngine {
    constructor(clock = () => Date.now()) {
        this.clock = clock;
        this.alarms = new Map();
    }

    reset() { this.alarms.clear(); }

    evaluate(conditions) {
        const now = this.clock();
        const seen = new Set();
        for (const c of conditions) {
            if (!(c.priority in RANK)) throw new Error(`unknown priority ${c.priority}`);
            seen.add(c.id);
            let a = this.alarms.get(c.id);
            if (!a) {
                a = { id: c.id, state: NORM, occurrences: 0 };
                this.alarms.set(c.id, a);
            }
            Object.assign(a, { priority: c.priority, message: c.message, source: c.source });
            this._step(a, !!c.active, now);
        }
        for (const a of this.alarms.values()) if (!seen.has(a.id)) this._step(a, false, now);
    }

    _step(a, active, now) {
        if (active && (a.state === NORM || a.state === RTNUN)) {
            Object.assign(a, {
                state: UNACK, activatedMs: now, clearedMs: null,
                ackedMs: null, ackedBy: null, changedMs: now,
            });
            a.occurrences += 1;
        } else if (!active && a.state === UNACK) {
            Object.assign(a, { state: RTNUN, clearedMs: now, changedMs: now });
        } else if (!active && a.state === ACKED) {
            Object.assign(a, { state: NORM, clearedMs: now, changedMs: now });
        }
    }

    ack(id, actor = 'sandbox') {
        const a = this.alarms.get(id);
        if (!a) return false;
        const now = this.clock();
        if (a.state === UNACK) a.state = ACKED;
        else if (a.state === RTNUN) a.state = NORM;
        else return false;
        Object.assign(a, { ackedMs: now, ackedBy: actor, changedMs: now });
        return true;
    }

    ackAll(actor = 'sandbox') {
        let n = 0;
        for (const a of this.alarms.values()) if (this.ack(a.id, actor)) n += 1;
        return n;
    }

    /** Same shape as the backend snapshot (times as ISO UTC strings). */
    snapshot() {
        const shown = [...this.alarms.values()].filter((a) => a.state !== NORM);
        shown.sort((x, y) => RANK[x.priority] - RANK[y.priority]
            || (x.state === UNACK ? 0 : 1) - (y.state === UNACK ? 0 : 1)
            || y.changedMs - x.changedMs);
        const iso = (ms) => (ms == null ? null : new Date(ms).toISOString());
        return {
            alarms: shown.map((a) => ({
                id: a.id, priority: a.priority, message: a.message, source: a.source,
                state: a.state, activated: iso(a.activatedMs), cleared: iso(a.clearedMs),
                acked: iso(a.ackedMs), acked_by: a.ackedBy, occurrences: a.occurrences,
            })),
            unacked: shown.filter((a) => a.state === UNACK || a.state === RTNUN).length,
        };
    }
}

/** Sandbox alarm conditions from the What-If DAG. Ids follow the backend. */
export function conditionsFromGrid(grid, itKw) {
    const g = grid || {};
    const out = [];
    for (const s of pathStatus(g, itKw)) {
        const P = s.path.toUpperCase();
        const src = `path_${s.path}`;
        const util = g['util_' + s.path] || {};
        const tc = g['mvtc_' + s.path] || {};
        const c = (id, active, priority, message) =>
            out.push({ id: `PATH_${P}_${id}`, active, priority, message, source: src });
        c('UTILITY_LOST', util.alive === false || !!util.tripped, 'MEDIUM', `Path ${P} utility supply lost`);
        c('MVTC_TRIP', !!tc.tripped, 'HIGH', `Path ${P} MV transfer controller tripped`);
        c('ON_GENERATORS', s.source === 'genset', 'MEDIUM', `Path ${P} on generators`);
        c('ON_BATTERY', s.source === 'battery', 'HIGH', `Path ${P} UPS on battery`);
        c('NO_OUTPUT', s.source === null, 'HIGH', `Path ${P} UPS output lost`);
        c('UPS_N_LOST', s.ups.lvl === 'crit', 'HIGH', `Path ${P} UPS capacity below N`);
        c('UPS_N1_LOST', s.ups.lvl === 'warn', 'MEDIUM', `Path ${P} UPS bank lost N+1`);
        c('GEN_N_LOST', s.gen.lvl === 'crit', 'HIGH', `Path ${P} generation below N`);
        c('GEN_N1_LOST', s.gen.lvl === 'warn', 'LOW', `Path ${P} generation lost N+1`);
    }
    return out;
}

function _clock(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '—';
    const p2 = (n) => String(n).padStart(2, '0');
    return `${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())}`
        + `.${String(d.getMilliseconds()).padStart(3, '0')}`;
}

const STATE_LABEL = { UNACK: 'UNACK', ACKED: 'ACK', RTNUN: 'RTN UNACK' };

/**
 * @param {{alarms: Array, unacked: number}|null} snap
 * @param {{source: 'live'|'sandbox', error?: string, max?: number}} opts
 */
export function alarmBannerHtml(snap, opts = {}) {
    const source = opts.source === 'sandbox' ? 'sandbox' : 'live';
    const max = opts.max ?? 5;
    const head = source === 'sandbox'
        ? 'ALARMS · SANDBOX (What-If, local ack, not logged)'
        : 'ALARMS · LIVE PLANT (simulated Power Controls)';
    const alarms = (snap && snap.alarms) || [];
    const unacked = (snap && snap.unacked) || 0;
    const rows = alarms.slice(0, max).map((a) => {
        const ackable = a.state === UNACK || a.state === RTNUN;
        const when = a.state === RTNUN ? a.cleared : a.activated;
        return `<div class="pwr-al-row" data-prio="${escapeHTML(a.priority)}" data-state="${escapeHTML(a.state)}">`
            + `<span class="pwr-al-prio">${escapeHTML(a.priority)}</span>`
            + `<time class="pwr-al-time" title="${escapeHTML(when || '')}">${_clock(when)}</time>`
            + `<span class="pwr-al-msg">${escapeHTML(a.message)}</span>`
            + `<span class="pwr-al-state">${STATE_LABEL[a.state] || escapeHTML(a.state)}`
            + `${a.acked_by && a.state === ACKED ? ' · ' + escapeHTML(a.acked_by) : ''}</span>`
            + (ackable ? `<button type="button" class="pwr-al-ack" data-ack="${escapeHTML(a.id)}">ACK</button>` : '<span></span>')
            + '</div>';
    }).join('');
    const more = alarms.length > max ? `<div class="pwr-al-more">+${alarms.length - max} more</div>` : '';
    const empty = alarms.length === 0 && !opts.error ? '<div class="pwr-al-empty">No active alarms</div>' : '';
    const err = opts.error ? `<div class="pwr-al-err">${escapeHTML(opts.error)}</div>` : '';
    return `<div class="pwr-al-head" data-source="${source}"><span>${head}</span>`
        + `<span class="pwr-al-count">${unacked} unacknowledged</span>`
        + (unacked > 0 ? '<button type="button" class="pwr-al-ack-all" data-ack-all="1">ACK ALL</button>' : '')
        + `</div>${err}${rows}${more}${empty}`;
}
