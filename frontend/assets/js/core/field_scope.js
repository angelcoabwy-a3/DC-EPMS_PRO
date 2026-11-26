/**
 * L6 (2026-11-26): disturbance recorder (DFR) view of one path: two
 * three-phase scope screens (13.8 kV MV bus and the 480 V critical load
 * bus), a LIVE mode that sweeps the present waveform at the display
 * frame rate, a RECORDS mode that replays a captured record in slow
 * motion with its IEEE 1159 summary, and COMTRADE downloads.
 *
 * Records come from GET /api/oscillography/records (synthesised by the
 * server from plant state changes, model transition times). LIVE is
 * drawn here from the path's "dfr" state (source, load feed, frequency)
 * as a triggered display: a stable waveform with a sweeping beam.
 */
import { escapeHTML } from './sanitize.js';
import { door, fsgDefs } from './field_switchgear.js';

const e = (v) => escapeHTML(v === null || v === undefined ? '' : String(v));
export const PLOTS = {
    MV: { y: 110, h: 180, title: 'MV BUS 13.8 kV · PHASE-TO-NEUTRAL', unit: 'kV', vln: 13.8 / Math.sqrt(3) },
    LD: { y: 345, h: 180, title: 'CRITICAL LOAD BUS 480 V · PHASE-TO-NEUTRAL', unit: 'V', vln: 480 / Math.sqrt(3) },
};
const PX = 60, PW = 630;
const PH = [['A', 0], ['B', -120], ['C', 120]];
const FAULT = [[5, 0.09], [7, 0.06], [11, 0.03]];     // same model as the server
export const SLOW_MO = 10;                               // record replay: 0.4 s -> 4 s

/** Steady three-phase waveform of a point for LIVE: {A, B, C} in volts or kV. */
export function liveWave(dfr, point, cycles = 3, spc = 64) {
    const s = dfr || {};
    const mv = s.source && s.source !== 'NONE';
    const load = s.load || 'inverter';
    let amp = 1;
    if (point === 'MV') amp = mv ? 1 : 0;
    else if (load === 'lost') amp = 0;
    else if (load === 'static_bypass' || load === 'maintenance_bypass') amp = mv ? 1 : 0;
    const harm = point === 'LD' && load === 'inverter_distorted' ? FAULT : [];
    const peak = PLOTS[point].vln * Math.SQRT2;
    const out = {};
    for (const [ph, deg] of PH) {
        const v = [];
        for (let i = 0; i <= cycles * spc; i++) {
            const th = 2 * Math.PI * i / spc + deg * Math.PI / 180;
            v.push(peak * amp * (Math.sin(th) + harm.reduce((a, [h, k]) => a + k * Math.sin(h * th), 0)));
        }
        out[ph] = v;
    }
    return out;
}

/** SVG polyline points of ``values`` in a plot (±1.25 × nominal peak). */
export function polyPoints(values, point, upto = null) {
    const p = PLOTS[point];
    const vmax = p.vln * Math.SQRT2 * 1.25;
    const n = values.length;
    const last = upto == null ? n : Math.max(0, Math.min(n, upto));
    const pts = [];
    for (let i = 0; i < last; i++) {
        const x = PX + (n > 1 ? i / (n - 1) : 0) * PW;
        const y = p.y + p.h / 2 - (values[i] / vmax) * (p.h / 2);
        pts.push(`${x.toFixed(1)},${y.toFixed(1)}`);
    }
    return pts.join(' ');
}

function plot(point) {
    const p = PLOTS[point];
    let grid = '';
    for (let i = 1; i < 10; i++) grid += `<line x1="${PX + i * PW / 10}" y1="${p.y}" x2="${PX + i * PW / 10}" y2="${p.y + p.h}" class="xo-grid"/>`;
    for (let i = 1; i < 6; i++) grid += `<line x1="${PX}" y1="${p.y + i * p.h / 6}" x2="${PX + PW}" y2="${p.y + i * p.h / 6}" class="xo-grid"/>`;
    const lv = (pu) => p.y + p.h / 2 - (pu / 1.25) * (p.h / 2);
    return `<text x="${PX}" y="${p.y - 8}" class="fsg-tiny fsg-light">${p.title}</text>`
        + `<text x="${PX + PW}" y="${p.y - 8}" class="fsg-tiny fsg-light" text-anchor="end" data-txt="${point}-hd"></text>`
        + `<rect x="${PX}" y="${p.y}" width="${PW}" height="${p.h}" class="xo-screen" data-act="zoom" role="button" tabindex="0"/>` + grid
        + `<line x1="${PX}" y1="${p.y + p.h / 2}" x2="${PX + PW}" y2="${p.y + p.h / 2}" class="xo-axis"/>`
        + `<line x1="${PX}" y1="${lv(0.9)}" x2="${PX + PW}" y2="${lv(0.9)}" class="xo-lim"/>`
        + `<text x="${PX - 6}" y="${lv(0.9) + 3}" class="xo-scale" text-anchor="end">0.9</text>`
        + `<text x="${PX - 6}" y="${lv(1.25) + 8}" class="xo-scale" text-anchor="end">pu</text>`
        + PH.map(([ph]) => `<polyline class="xo-trace" data-trace="${point}_V${ph}" data-ph="${ph}" points=""/>`).join('')
        + `<line class="xo-cursor" data-cursor="${point}" x1="${PX}" y1="${p.y}" x2="${PX}" y2="${p.y + p.h}"/>`
        + `<line class="xo-trig" data-trig="${point}" x1="0" y1="${p.y}" x2="0" y2="${p.y + p.h}"/>`
        + `<circle class="xo-beam" data-beam="${point}" r="3" cx="${PX}" cy="${p.y + p.h / 2}"/>`;
}

function btn(x, y, w, act, label, extra = '') {
    return `<g class="xo-btn" data-act="${act}" ${extra} role="button" tabindex="0" transform="translate(${x} ${y})">`
        + `<rect width="${w}" height="26" rx="3"/><text x="${w / 2}" y="17" text-anchor="middle">${label}</text></g>`;
}

function side() {
    const X = 716, Y = 84;
    let rows = '';
    for (let i = 0; i < 9; i++) {
        rows += `<g class="xo-rec" data-act="record" data-idx="${i}" role="button" tabindex="0" transform="translate(${X + 14} ${Y + 92 + i * 34})">`
            + '<rect width="208" height="30" rx="2"/>'
            + `<text x="8" y="12" class="xo-rec-id" data-txt="r${i}a"></text>`
            + `<text x="8" y="24" class="xo-rec-t" data-txt="r${i}b"></text></g>`;
    }
    return door(X, Y, 236, 604, 'fsg-door-upper')
        + `<text x="${X + 14}" y="${Y + 24}" class="fsg-label">RECORDER</text>`
        + `<text x="${X + 14}" y="${Y + 36}" class="fsg-tiny">32 SAMPLES / CYCLE · 0.1 s PRE · 0.3 s POST</text>`
        + btn(X + 14, Y + 50, 100, 'live', 'LIVE') + btn(X + 122, Y + 50, 100, 'records', 'RECORDS')
        + rows
        + btn(X + 14, Y + 412, 100, 'play', 'PLAY ▶') + btn(X + 122, Y + 412, 100, 'trigger', 'TRIGGER')
        + btn(X + 14, Y + 446, 100, 'cfg', 'COMTRADE .CFG') + btn(X + 122, Y + 446, 100, 'dat', 'COMTRADE .DAT')
        + `<text x="${X + 14}" y="${Y + 500}" class="fsg-tiny">TRAINING INJECTION (SIMULATION)</text>`
        + btn(X + 14, Y + 508, 208, 'sag', 'UTILITY SAG 0.6 pu · 6 CYCLES')
        + `<text x="${X + 14}" y="${Y + 556}" class="fsg-tiny" data-txt="side1"></text>`
        + `<text x="${X + 14}" y="${Y + 570}" class="fsg-tiny" data-txt="side2"></text>`;
}

/** Static SVG of the recorder view for one path. */
export function scopeSvg(path) {
    const P = e(String(path || 'a').toUpperCase());
    const frame = '<rect x="20" y="20" width="940" height="672" rx="4" class="fsg-frame"/>'
        + '<rect x="20" y="20" width="940" height="52" rx="4" class="fsg-topcap"/>'
        + `<text x="44" y="44" class="fsg-head">DISTURBANCE RECORDER · PATH ${P}</text>`
        + '<text x="44" y="61" class="fsg-tiny fsg-light">3-PHASE VOLTAGE · IEEE 1159 RMS VARIATIONS · COMTRADE C37.111-1999 · SIMULATED · MODEL TRANSITION TIMES</text>'
        + '<line x1="704" y1="76" x2="704" y2="688" class="fsg-split"/>';
    const legend = PH.map(([ph], i) => `<g transform="translate(${PX + i * 70} 548)"><line x1="0" y1="0" x2="18" y2="0" class="xo-trace" data-ph="${ph}"/>`
        + `<text x="24" y="4" class="fsg-tiny fsg-light">V${ph}</text></g>`).join('');
    return `<svg class="fsg-svg xo-svg" viewBox="0 0 980 712" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Disturbance recorder, path ${P}">`
        + fsgDefs() + `<g filter="url(#fsg-powder)">${frame}`
        + `<g class="fsg-section xo-section" data-section="SCOPE">${plot('MV')}${plot('LD')}${legend}`
        + `<text x="${PX + PW}" y="552" class="fsg-tiny fsg-light" text-anchor="end" data-txt="tbase"></text>`
        + `<g transform="translate(${PX} 566)"><rect width="${PW}" height="112" rx="3" class="xf-lcd"/>`
        + '<text x="12" y="22" class="xf-lcd-line" data-txt="s1"></text>'
        + '<text x="12" y="42" class="xf-lcd-line" data-txt="s2"></text>'
        + '<text x="12" y="62" class="xf-lcd-line" data-txt="s3"></text>'
        + '<text x="12" y="82" class="xf-lcd-line" data-txt="s4"></text>'
        + '<text x="12" y="102" class="xf-lcd-lbl" data-txt="s5"></text></g>'
        + side() + '</g></g></svg>';
}

function setText(root, key, text) {
    const el = root.querySelector(`[data-txt="${key}"]`);
    if (el) el.textContent = text;
}

const stamp = (ts) => {
    const t = new Date(Number(ts) * 1000);
    return Number.isNaN(t.getTime()) ? '' : t.toISOString().slice(11, 23);
};

/**
 * Write the recorder state. ui = {mode: 'live'|'records', records: [...],
 * record (with samples) | null, selected, playhead (0..1), sweep (0..1),
 * dfr (live state of the path)}.
 */
export function applyScopeState(root, ui = {}) {
    const sec = root && root.querySelector('[data-section="SCOPE"]');
    if (!sec) return;
    const mode = ui.mode === 'records' ? 'records' : 'live';
    sec.setAttribute('data-mode', mode);
    sec.querySelectorAll('[data-act="live"], [data-act="records"]').forEach((g) =>
        g.setAttribute('data-on', g.getAttribute('data-act') === mode ? '1' : '0'));
    const recs = ui.records || [];
    for (let i = 0; i < 9; i++) {
        const g = sec.querySelector(`.xo-rec[data-idx="${i}"]`);
        const r = recs[i];
        if (!g) continue;
        g.setAttribute('data-empty', r ? '0' : '1');
        g.setAttribute('data-on', r && r.id === ui.selected ? '1' : '0');
        setText(g, `r${i}a`, r ? `${r.id} · ${stamp(r.ts)} UTC` : '');
        setText(g, `r${i}b`, r ? String(r.trigger).toUpperCase().slice(0, 38) : (i === 0 ? 'NO RECORD YET' : ''));
    }
    const rec = mode === 'records' ? ui.record : null;
    if (rec && rec.samples) {
        // ZOOM: 2 cycles before to 4 cycles after the trigger (192 samples).
        const nPre0 = Math.round(rec.pre_s * rec.fs);
        const lo = ui.zoom ? Math.max(0, nPre0 - 64) : 0;
        const hi = ui.zoom ? Math.min(rec.samples.MV_VA.length, nPre0 + 128) : rec.samples.MV_VA.length;
        const cut = (arr) => arr.slice(lo, hi);
        const n = hi - lo;
        const upto = Math.round((ui.playhead == null ? 1 : ui.playhead) * n);
        const nPre = nPre0 - lo;
        for (const point of ['MV', 'LD']) {
            for (const [ph] of PH) {
                const pl = sec.querySelector(`[data-trace="${point}_V${ph}"]`);
                if (pl) pl.setAttribute('points', polyPoints(cut(rec.samples[`${point}_V${ph}`]), point, upto));
            }
            const x = PX + (upto / Math.max(1, n - 1)) * PW;
            const cur = sec.querySelector(`[data-cursor="${point}"]`);
            if (cur) { cur.setAttribute('x1', x.toFixed(1)); cur.setAttribute('x2', x.toFixed(1)); }
            const tx = PX + (nPre / Math.max(1, n - 1)) * PW;
            const trig = sec.querySelector(`[data-trig="${point}"]`);
            if (trig) { trig.setAttribute('x1', tx.toFixed(1)); trig.setAttribute('x2', tx.toFixed(1)); }
            const s = (rec.summary || {})[point] || {};
            setText(sec, `${point}-hd`, `MIN ${s.min_pu} pu · THD ${s.thd_pct} %`);
        }
        const mv = rec.summary.MV || {};
        const ld = rec.summary.LD || {};
        setText(sec, 's1', `${rec.id} · ${String(rec.trigger).toUpperCase()}`);
        setText(sec, 's2', `MV: ${String(mv.class).toUpperCase()} · ${mv.below_0_9_ms} ms BELOW 0.9 pu`);
        setText(sec, 's3', `LOAD: ${String(ld.class).toUpperCase()} · ${ld.below_0_9_ms} ms BELOW 0.9 pu`);
        setText(sec, 's4', `TRANSITION MV ${mv.transition}${mv.transition_ms ? ` ${mv.transition_ms} ms` : ''} · LOAD ${ld.transition}${ld.transition_ms ? ` ${ld.transition_ms} ms` : ''}`);
        setText(sec, 's5', `CAUSE: ${(rec.cause || []).join(' · ').slice(0, 100)}`);
        setText(sec, 'tbase', ui.zoom ? `ZOOM 100 ms AROUND THE TRIGGER · CLICK THE SCREEN TO RETURN`
            : `0.4 s RECORD · TRIGGER AT 0.1 s · REPLAY ×1/${SLOW_MO} · CLICK THE SCREEN TO ZOOM`);
        sec.setAttribute('data-load-hit', /sag|interruption|notch/.test(String(ld.class)) ? '1' : '0');
        return;
    }
    const live = ui.dfr || {};
    for (const point of ['MV', 'LD']) {
        const w = liveWave(live, point);
        for (const [ph] of PH) {
            const pl = sec.querySelector(`[data-trace="${point}_V${ph}"]`);
            if (pl) pl.setAttribute('points', polyPoints(w[ph], point));
        }
        const sweep = Math.max(0, Math.min(1, Number(ui.sweep) || 0));
        const x = PX + sweep * PW;
        const k = Math.round(sweep * (w.A.length - 1));
        const p = PLOTS[point];
        const vmax = p.vln * Math.SQRT2 * 1.25;
        const beam = sec.querySelector(`[data-beam="${point}"]`);
        if (beam) { beam.setAttribute('cx', x.toFixed(1)); beam.setAttribute('cy', (p.y + p.h / 2 - (w.A[k] / vmax) * (p.h / 2)).toFixed(1)); }
        const cur = sec.querySelector(`[data-cursor="${point}"]`);
        if (cur) { cur.setAttribute('x1', PX); cur.setAttribute('x2', PX); }
        setText(sec, `${point}-hd`, '');
    }
    const live1 = live.source === 'NONE' ? 'MV BUS DEAD' : `MV ON ${live.source || '?'} · ${Number(live.hz || 60).toFixed(2)} Hz`;
    setText(sec, 's1', `LIVE · PATH ${String(ui.path || '').toUpperCase()} · TRIGGERED DISPLAY`);
    setText(sec, 's2', live1);
    setText(sec, 's3', `LOAD BUS: ${String(live.load || '').replace(/_/g, ' ').toUpperCase()}`);
    setText(sec, 's4', recs.length ? `${recs.length} RECORD(S) · LAST ${recs[0].id}: ${String(recs[0].trigger).toUpperCase()}` : 'NO RECORD YET');
    setText(sec, 's5', 'A RECORD IS TAKEN WHEN THE SOURCE OR THE LOAD FEED OF THE PATH CHANGES');
    setText(sec, 'tbase', '3 CYCLES · 16.7 ms/CYCLE');
    sec.setAttribute('data-load-hit', '0');
}

/** Map a click to {ui}, {fetch: id}, {action} or {download: part}. */
export function resolveScopeClick(target, ui = {}) {
    const el = target && target.closest ? target.closest('[data-act]') : null;
    if (!el) return null;
    const act = el.getAttribute('data-act');
    if (act === 'live') return { ui: { mode: 'live' } };
    if (act === 'zoom') return ui.mode === 'records' && ui.record ? { ui: { zoom: !ui.zoom } } : null;
    if (act === 'records') {
        const first = (ui.records || [])[0];
        return first ? { ui: { mode: 'records' }, fetch: ui.selected || first.id } : { ui: { mode: 'records' } };
    }
    if (act === 'record') {
        const r = (ui.records || [])[Number(el.getAttribute('data-idx'))];
        return r ? { ui: { mode: 'records', selected: r.id, playhead: 0 }, fetch: r.id, play: true } : null;
    }
    if (act === 'play') return ui.record ? { ui: { mode: 'records', playhead: 0 }, play: true } : null;
    if (act === 'trigger') return { action: 'trigger' };
    if (act === 'sag') return { action: 'sag' };
    if (act === 'cfg' || act === 'dat') return ui.selected ? { download: act } : null;
    return null;
}

/** requestAnimationFrame loop with a fallback; returns a stop function. */
export function animate(step, win = (typeof window !== 'undefined' ? window : null)) {
    let stop = false;
    let id = null;
    const raf = win && win.requestAnimationFrame ? win.requestAnimationFrame.bind(win)
        : (f) => setTimeout(() => f(Date.now()), 16);
    const caf = win && win.cancelAnimationFrame ? win.cancelAnimationFrame.bind(win) : clearTimeout;
    const loop = (t) => {
        if (stop) return;
        if (step(t) === false) return;
        id = raf(loop);
    };
    id = raf(loop);
    return () => { stop = true; if (id != null) caf(id); };
}
