/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — frontend/assets/js/core/training_view.js
 *
 * T2: training coach panel markup for the Power view (pure).
 *   idle     drill selector + Start + Reset plant
 *   active   title, summary, steps (done / current / pending with
 *            elapsed ms), clock, battery of the drill path, Abort
 *   finished outcome, score, violations, ledger id, Download report
 * Data: GET /api/training/drills and /api/training/session; battery
 * from the plant path summary. S-SEC-01: everything escaped.
 * ════════════════════════════════════════════════════════════════ */

import { escapeHTML } from './sanitize.js';

export function fmtElapsed(ms) {
    if (ms == null || !Number.isFinite(ms)) return '—';
    const t = Math.max(0, Math.round(ms));
    const m = Math.floor(t / 60000);
    const s = Math.floor((t % 60000) / 1000);
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(t % 1000).padStart(3, '0')}`;
}

function _battery(pathSummary) {
    if (!pathSummary) return '';
    const soc = Number(pathSummary.battery_soc_pct ?? 100);
    const dead = pathSummary.bus_energized === false;
    const lost = !!pathSummary.load_lost;
    const lvl = lost ? 'crit' : (dead ? (soc < 25 ? 'crit' : 'warn') : 'ok');
    const txt = lost ? 'LOAD LOST'
        : dead ? `ON BATTERY · ${soc.toFixed(1)} % · ${Number(pathSummary.battery_runtime_min ?? 0).toFixed(1)} min left`
            : `BATTERY ${soc.toFixed(1)} %`;
    return `<div class="tr-batt" data-lvl="${lvl}"><i style="width:${Math.max(0, Math.min(100, soc))}%"></i>`
        + `<span>${escapeHTML(txt)} (model)</span></div>`;
}

export function trainingHtml({ drills = [], view = null, pathSummary = null, nowMs = Date.now(),
    selected = '', message = '', soundOn = false, soundSupported = true } = {}) {
    const s = view && view.session;
    const sound = soundSupported
        ? `<button type="button" class="tr-btn tr-sound" data-tr-sound="1" aria-pressed="${soundOn}">Sound ${soundOn ? 'ON' : 'OFF'}</button>` : '';
    const head = `<div class="tr-head"><span>TRAINING · SIMULATED PLANT</span>${sound}</div>`;
    const msg = message ? `<div class="tr-msg">${escapeHTML(message)}</div>` : '';
    if (s && view.active) {
        const elapsed = nowMs - s.started_ms;
        const steps = s.steps.map((st, i) => {
            const state = st.done ? 'done' : (st.current ? 'current' : 'pending');
            return `<li data-state="${state}"><span class="tr-n">${i + 1}</span>`
                + `<span class="tr-text">${escapeHTML(st.text)}</span>`
                + `<span class="tr-t">${st.done ? fmtElapsed(st.t_ms) : ''}</span></li>`;
        }).join('');
        return head + msg
            + `<div class="tr-title">${escapeHTML(s.drill.id)} · ${escapeHTML(s.drill.title)}</div>`
            + `<div class="tr-summary">${escapeHTML(s.drill.summary)}</div>`
            + `<div class="tr-row"><span class="tr-clock" data-tr-clock="1">${fmtElapsed(elapsed)}</span>`
            + `<span class="tr-target">target ${escapeHTML(String(s.drill.target_s))} s · limit ${escapeHTML(String(s.drill.time_limit_s))} s</span>`
            + `<button type="button" class="tr-btn tr-abort" data-tr-abort="1">Abort</button></div>`
            + _battery(pathSummary)
            + `<ol class="tr-steps">${steps}</ol>`;
    }
    const options = drills.map((d) => `<option value="${escapeHTML(d.id)}"${d.id === selected ? ' selected' : ''}>`
        + `${escapeHTML(d.id)} · ${escapeHTML(d.title)}</option>`).join('');
    const picker = `<div class="tr-row"><select class="tr-select" data-tr-select="1" aria-label="Drill">${options}</select>`
        + '<button type="button" class="tr-btn tr-start" data-tr-start="1">Start drill</button>'
        + '<button type="button" class="tr-btn" data-tr-reset="1" title="Back to the design lineup">Reset plant</button></div>';
    let result = '';
    if (s && !view.active) {
        result = `<div class="tr-result" data-outcome="${escapeHTML(s.outcome || '')}">`
            + `<b>${escapeHTML(s.drill.id)} · ${escapeHTML(s.outcome || '')}</b>`
            + `<span>Score ${escapeHTML(String(s.score ?? 0))} / 100</span>`
            + `<span>${escapeHTML(String(s.violations ?? 0))} refused command(s)</span>`
            + (s.reason ? `<span>${escapeHTML(s.reason)}</span>` : '')
            + (s.ledger_entry_id ? `<span class="tr-ledger">ledger ${escapeHTML(String(s.ledger_entry_id).slice(0, 12))}</span>` : '')
            + '<button type="button" class="tr-btn" data-tr-report="1">Download report (JSON)</button></div>'
            + '<div class="tr-note">Rubric: DC-EPMS training rubric v1 (ours, not an industry standard).</div>';
    }
    return head + msg + picker + result;
}
