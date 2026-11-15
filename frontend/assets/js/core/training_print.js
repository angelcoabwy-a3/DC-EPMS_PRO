/**
 * T4 (2026-11-15): printable drill report.
 *
 * Builds a self-contained, print-styled HTML document from the JSON of
 * GET /api/training/report and opens it in a new window; the operator
 * saves it as PDF with the browser's print dialog ("Save as PDF").
 * No PDF library: the browser renders and paginates. Everything the
 * report carries is escaped (S-SEC-01): drill texts, actors and event
 * details are data.
 */
import { escapeHTML } from './sanitize.js';

const e = (v) => escapeHTML(v === null || v === undefined ? '' : String(v));

export function fmtMs(ms) {
    if (ms === null || ms === undefined || !Number.isFinite(Number(ms))) return '—';
    const n = Math.max(0, Math.round(Number(ms)));
    const m = Math.floor(n / 60000);
    const s = Math.floor(n / 1000) % 60;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(n % 1000).padStart(3, '0')}`;
}

const SKIP = new Set(['ts', 'ts_ms', 'source', 'event', 'device_id', 'actor', 'alarm_id']);

/** One-line detail of an SOE row: the keys the table has no column for. */
export function soeDetail(row) {
    return Object.entries(row || {})
        .filter(([k, v]) => !SKIP.has(k) && v !== null && v !== undefined && v !== '')
        .map(([k, v]) => `${k}=${Array.isArray(v) ? v.join(',') : (typeof v === 'object' ? JSON.stringify(v) : v)}`)
        .join(' · ');
}

const CSS = `
*{box-sizing:border-box}
body{font:12px/1.4 -apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#111;margin:24px;background:#fff}
h1{font-size:18px;margin:0 0 2px}
h2{font-size:13px;margin:18px 0 6px;border-bottom:1px solid #999;padding-bottom:2px;text-transform:uppercase;letter-spacing:.04em}
.sub{color:#555;margin:0 0 12px}
.banner{border:1px solid #111;padding:6px 10px;margin:10px 0;font-weight:700}
.banner[data-outcome="PASS"]{border-color:#1b5e20}
.banner[data-outcome="FAIL"]{border-color:#b71c1c}
dl{display:grid;grid-template-columns:150px 1fr;gap:2px 10px;margin:0}
dt{color:#555}dd{margin:0}
table{width:100%;border-collapse:collapse;margin-top:4px}
th,td{border:1px solid #bbb;padding:3px 5px;text-align:left;vertical-align:top}
th{background:#eee;font-weight:600}
td.mono,.mono{font-family:ui-monospace,Consolas,monospace;font-size:11px}
.note{color:#555;font-size:11px;margin-top:6px}
.empty{color:#777;font-style:italic}
.toolbar{margin-bottom:12px}
.toolbar button{font:inherit;padding:4px 10px}
tr{page-break-inside:avoid}
@media print{.toolbar{display:none}body{margin:12mm}h2{page-break-after:avoid}}
@page{size:auto;margin:12mm}
`;

/** Full HTML document for a finished drill report. */
export function reportDocument(r) {
    if (!r || typeof r !== 'object') throw new Error('no report');
    const d = r.drill || {};
    const startMs = Date.parse(r.started) || null;
    const rel = (ms) => (startMs && Number.isFinite(Number(ms)) ? fmtMs(Number(ms) - startMs) : '—');
    const target = Number(d.target_s);
    const stepTarget = (id) => {
        const st = (d.steps || []).find((s) => s.id === id);
        return st ? e(st.text) : '';
    };

    const steps = (r.steps || []).length
        ? `<table><thead><tr><th>#</th><th>Step</th><th>Done at</th></tr></thead><tbody>${(r.steps || []).map((s, i) =>
            `<tr><td>${i + 1}</td><td>${e(s.id)} · ${e(s.text)}</td><td class="mono">${fmtMs(s.t_ms)}</td></tr>`).join('')}</tbody></table>`
        : '<p class="empty">No step completed.</p>';
    const notDone = (d.steps || []).slice((r.steps || []).length)
        .map((s) => `<li>${e(s.id)} · ${stepTarget(s.id)}</li>`).join('');

    const viol = (r.violations || []).length
        ? `<table><thead><tr><th>t</th><th>Type</th><th>Device</th><th>Command / detail</th><th>Actor</th></tr></thead><tbody>${
            (r.violations || []).map((v) => `<tr><td class="mono">${rel(Number(v.ts) * 1000)}</td>`
                + `<td>${e(v.violation || v.event)}</td><td class="mono">${e(v.device_id)}</td>`
                + `<td>${e([v.command, v.detail || v.reason].filter(Boolean).join(' · '))}</td><td>${e(v.actor)}</td></tr>`).join('')}</tbody></table>`
        : '<p class="empty">None.</p>';

    const reverts = (r.step_reverts || []).length
        ? `<table><thead><tr><th>t</th><th>Step</th><th>Event</th></tr></thead><tbody>${
            (r.step_reverts || []).map((x) => `<tr><td class="mono">${fmtMs(x.t_ms)}</td><td>${e(x.step)}</td><td>${e(x.event)}</td></tr>`).join('')}</tbody></table>`
        : '<p class="empty">None.</p>';

    const soe = (r.soe || []).length
        ? `<table><thead><tr><th>t</th><th>Source</th><th>Event</th><th>Device</th><th>Actor</th><th>Detail</th></tr></thead><tbody>${
            (r.soe || []).map((x) => `<tr><td class="mono">${rel(x.ts_ms)}</td><td>${e(x.source)}</td>`
                + `<td>${e(x.event)}${x.alarm_id ? ' ' + e(x.alarm_id) : ''}</td><td class="mono">${e(x.device_id)}</td>`
                + `<td>${e(x.actor)}</td><td class="mono">${e(soeDetail(x))}</td></tr>`).join('')}</tbody></table>`
        : '<p class="empty">No events.</p>';

    const integ = r.integrity || {};
    const rubric = r.rubric || {};
    const late = r.outcome === 'PASS' && Number.isFinite(target)
        ? Math.max(0, Math.round(Number(r.duration_ms) / 1000 - target)) : null;

    return '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        + `<title>${e(d.id)} report · ${e(r.operator)} · ${e(r.started)}</title><style>${CSS}</style></head><body>`
        + '<div class="toolbar"><button type="button" onclick="window.print()">Print / Save as PDF</button></div>'
        + `<h1>${e(r.report || 'DC-EPMS operator training report')}</h1>`
        + `<p class="sub">SIMULATED PLANT · training record, not an operating log · ${e(d.id)} v${e(d.version)}</p>`
        + `<div class="banner" data-outcome="${e(r.outcome)}">${e(r.outcome)} · Score ${e(r.score ?? 0)} / 100`
        + `${r.reason ? ' · ' + e(r.reason) : ''}</div>`
        + '<h2>Drill</h2><dl>'
        + `<dt>Drill</dt><dd>${e(d.id)} · ${e(d.title)}</dd>`
        + `<dt>Summary</dt><dd>${e(d.summary)}</dd>`
        + `<dt>Path</dt><dd>${e(String(d.path || '').toUpperCase())}</dd>`
        + `<dt>Operator</dt><dd>${e(r.operator)}</dd>`
        + `<dt>Started</dt><dd class="mono">${e(r.started)}</dd>`
        + `<dt>Ended</dt><dd class="mono">${e(r.ended)}</dd>`
        + `<dt>Duration</dt><dd class="mono">${fmtMs(r.duration_ms)} (target ${e(d.target_s)} s, limit ${e(d.time_limit_s)} s${late !== null ? `, ${late} s over target` : ''})</dd>`
        + '</dl>'
        + `<h2>Steps</h2>${steps}${notDone ? `<p class="note">Not completed:</p><ul>${notDone}</ul>` : ''}`
        + `<h2>Violations (${(r.violations || []).length})</h2>${viol}`
        + `<h2>Reverted steps</h2>${reverts}`
        + `<h2>Sequence of events</h2>${soe}`
        + `<p class="note">${e(r.time_note)} t is relative to the drill start.</p>`
        + '<h2>Scoring</h2><dl>'
        + `<dt>Rubric</dt><dd>${e(rubric.name)} (ours, not an industry standard)</dd>`
        + `<dt>Fail</dt><dd>${e(rubric.fail)}</dd>`
        + `<dt>Violation</dt><dd>${e(rubric.violation || 'refused or blocked command')} · -${e(rubric.violation_penalty)} each</dd>`
        + `<dt>Late</dt><dd>-${e(rubric.late_penalty_per_10_s)} per started 10 s beyond the target</dd>`
        + '</dl>'
        + '<h2>Integrity</h2><dl>'
        + `<dt>Ledger entry</dt><dd class="mono">${e(r.ledger_entry_id || integ.ledger_entry_id || 'not recorded')}</dd>`
        + `<dt>Report SHA-256</dt><dd class="mono">${e(integ.report_sha256 || 'not available')}</dd>`
        + `<dt>Covers</dt><dd>${e(integ.covers || '')}</dd>`
        + '</dl>'
        + '<p class="note">The digest is the one recorded in the Forensic Ledger (TRAINING_DRILL_RESULT). '
        + 'This printout is a rendering of the JSON report; the JSON is the verifiable record.</p>'
        + '</body></html>';
}

/** Open the report in a new window ready to print. Returns false when a
 *  popup blocker refuses the window. */
export function openPrintable(report, win = (typeof window !== 'undefined' ? window : null)) {
    if (!win) return false;
    const w = win.open('', '_blank');
    if (!w) return false;
    w.document.open();
    w.document.write(reportDocument(report));
    w.document.close();
    try { w.focus(); } catch (_e) { /* ignore */ }
    return true;
}
