/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — frontend/assets/js/core/power_status.js
 *
 * Power SLD "vida 2":
 *   1. statusStrip(grid, itKw): one row per Phase 1 path with the
 *      active source, load, UPS bank and generator bus N / N+1, and
 *      the 52-U / 52-GM positions. Pure, returns markup.
 *   2. EventLog: a clocked sequence of events derived by DIFFING
 *      successive DAG snapshots (utility lost, 52-U opens, crank,
 *      52-GM closes, battery, blocks out ...). The DAG engine stays
 *      untouched; the log only observes it. t = 0 is the first event
 *      after a reset (restoreAll / leaving What-If).
 *
 * Both read the What-If / Replay DAG (core/power_grid.js) and the
 * design-model flows (core/power_flow.js). Nothing here reaches the
 * plant (ADR-006).
 * ════════════════════════════════════════════════════════════════ */

import { pathFlows, fmtPower } from './power_flow.js';
import { escapeHTML } from './sanitize.js';

const PATHS = ['a', 'b'];

function _breakers(tc) {
    if (!tc) return { u: 'closed', gm: 'open' };
    if (tc.transferring || tc.ats_pos === 'open') return { u: 'open', gm: 'open' };
    const onGen = tc.ats_pos === 'secondary';
    return { u: !tc.tripped && !onGen ? 'closed' : 'open', gm: !tc.tripped && onGen ? 'closed' : 'open' };
}

function _nTag(n) {
    if (!n || n.capacity_kw == null) return { txt: '—', lvl: 'muted' };
    if (n.n1_ok) return { txt: 'N+1', lvl: 'ok' };
    if (n.n_ok) return { txt: 'N', lvl: 'warn' };
    return { txt: '< N', lvl: 'crit' };
}

const SOURCE_LABEL = { util: 'UTILITY', genset: 'GENERATORS', battery: 'BATTERY', null: 'NO OUTPUT' };

/** Per-path status row data (exported for tests). */
export function pathStatus(grid, itKw) {
    const g = grid || {};
    const flows = pathFlows(g, itKw);
    return PATHS.map((p) => {
        const f = flows[p];
        const b = _breakers(g['mvtc_' + p]);
        return {
            path: p,
            source: f.source,
            sourceLabel: SOURCE_LABEL[f.source] ?? 'NO OUTPUT',
            loadKw: f.upsOutKw,
            share: f.share,
            ups: _nTag(g['ups_' + p]),
            gen: _nTag(g['genset_' + p]),
            u52: b.u,
            gm52: b.gm,
            transferring: !!(g['mvtc_' + p] || {}).transferring,
        };
    });
}

export function statusStrip(grid, itKw) {
    return pathStatus(grid, itKw).map((r) => `
        <div class="pwr-strip-row" data-path="${r.path}" data-source="${r.source ?? 'none'}">
            <span class="pwr-strip-path">PATH ${r.path.toUpperCase()}</span>
            <span class="pwr-strip-src" data-k="source">${escapeHTML(r.sourceLabel)}${r.transferring ? ' · IN TRANSFER' : ''}</span>
            <span class="pwr-strip-kv"><i>LOAD</i><b data-k="load">${fmtPower(r.loadKw)} · ${(r.share * 100).toFixed(0)} %</b></span>
            <span class="pwr-strip-kv"><i>UPS</i><b data-k="ups" data-lvl="${r.ups.lvl}">${r.ups.txt}</b></span>
            <span class="pwr-strip-kv"><i>GEN</i><b data-k="gen" data-lvl="${r.gen.lvl}">${r.gen.txt}</b></span>
            <span class="pwr-strip-kv"><i>52-U</i><b data-k="u52" data-state="${r.u52}">${r.u52.toUpperCase()}</b></span>
            <span class="pwr-strip-kv"><i>52-GM</i><b data-k="gm52" data-state="${r.gm52}">${r.gm52.toUpperCase()}</b></span>
        </div>`).join('');
}

// ── Event log ─────────────────────────────────────────────────────

/** Events between two DAG snapshots for one path (pure, exported). */
export function diffEvents(prev, next, p) {
    const P = p.toUpperCase();
    const o = (id) => (prev || {})[`${id}_${p}`] || {};
    const n = (id) => (next || {})[`${id}_${p}`] || {};
    const ev = [];
    const push = (level, text) => ev.push({ path: p, level, text });

    if (o('util').alive !== false && n('util').alive === false) push('crit', `UTILITY ${P} lost`);
    if (o('util').alive === false && n('util').alive !== false) push('ok', `UTILITY ${P} restored`);

    const ot = o('mvtc'), nt = n('mvtc');
    if (!ot.transferring && nt.transferring) {
        push('warn', nt.ats_pos === 'secondary' ? `52-GM opens · back-transfer ${P} started`
            : `52-U opens · transfer ${P} started`);
    }
    if (ot.ats_pos !== 'secondary' && nt.ats_pos === 'secondary') push('warn', `52-GM closes · PATH ${P} on generators`);
    if (ot.ats_pos === 'secondary' && nt.ats_pos === 'primary') push('ok', `52-U recloses · PATH ${P} back on utility`);
    if (!ot.tripped && nt.tripped) push('crit', `MV TRANSFER ${P} tripped`);

    const og = o('genset'), ng = n('genset');
    if (og.state !== ng.state && ng.state) {
        const lvl = ng.state === 'standby' ? 'ok' : 'warn';
        push(lvl, `GEN BUS ${P} ${ng.state.toUpperCase().replace('_', ' ')}`);
    }
    if ((og.units_out || 0) !== (ng.units_out || 0)) {
        push('warn', `GEN BUS ${P}: ${ng.units_out || 0} set(s) out`);
    }

    const ou = o('ups'), nu = n('ups');
    if (!ou.on_battery && nu.on_battery) push('warn', `UPS BANK ${P} on battery`);
    if (ou.on_battery && !nu.on_battery && nu.alive) push('ok', `UPS BANK ${P} off battery`);
    if (ou.alive !== false && nu.alive === false) push('crit', `UPS BANK ${P} output lost`);
    if (ou.alive === false && nu.alive !== false) push('ok', `UPS BANK ${P} output restored`);
    if ((ou.units_out || 0) !== (nu.units_out || 0)) {
        push(nu.n_ok ? 'warn' : 'crit', `UPS BANK ${P}: ${nu.units_out || 0} block(s) out`);
    }
    return ev;
}

export class EventLog {
    constructor({ now = () => Date.now(), max = 40 } = {}) {
        this._now = now;
        this._max = max;
        this.reset();
    }

    /** Clear the sequence. With a baseline snapshot, the very next
     *  change is already an event (no change is lost to priming). */
    reset(baseline = null) {
        this.events = [];
        this._t0 = null;
        this._prev = baseline ? JSON.parse(JSON.stringify(baseline)) : null;
    }

    /** Feed a DAG snapshot; returns the events it produced. */
    observe(grid) {
        if (!grid) return [];
        const snap = JSON.parse(JSON.stringify(grid));
        if (!this._prev) { this._prev = snap; return []; }
        const found = PATHS.flatMap((p) => diffEvents(this._prev, snap, p));
        this._prev = snap;
        if (!found.length) return [];
        const t = this._now();
        if (this._t0 === null) this._t0 = t;
        const ts = (t - this._t0) / 1000;
        for (const e of found) this.events.push({ ...e, t: ts });
        if (this.events.length > this._max) this.events.splice(0, this.events.length - this._max);
        return found;
    }

    /** Seconds since t = 0 (null before the first event). */
    elapsed() {
        return this._t0 === null ? null : (this._now() - this._t0) / 1000;
    }

    render() {
        if (!this.events.length) {
            return '<div class="pwr-tl-empty">No events. In WHAT-IF, trip a utility, a transfer controller or take units out to see the sequence.</div>';
        }
        return this.events.map((e) => `
            <div class="pwr-tl-ev" data-lvl="${e.level}" data-path="${e.path}">
                <span class="pwr-tl-t">t+${e.t.toFixed(2)} s</span>
                <span class="pwr-tl-txt">${escapeHTML(e.text)}</span>
            </div>`).join('');
    }
}
