/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/shift_copilot.js
 * Shift Copilot panel (lives inside #view-incidents).
 *
 * Drives backend/shift_copilot.py:
 *   simulate (alarm burst) -> analyze (correlate/triage/MOP log)
 *   -> handover report. All HTTP via services/api.js.
 *
 * Pattern mirrors views/incidents.js: ES module, registerRoute hook,
 * escaped HTML everywhere, degraded-state rendering on failure.
 * ════════════════════════════════════════════════════════════════ */

import {
    copilotSimulate,
    copilotAnalyze,
    copilotHandover,
    copilotClear,
} from '../services/api.js';
import { escapeHTML as _escape } from '../core/sanitize.js';

let _initialized = false;

// ─── Pure presentation helpers ─────────────────────────────────────

const _PRIO_COLOR = { P1: 'var(--crit)', P2: 'var(--warn)', P3: 'var(--accent)' };

function _prioBadge(prio) {
    const color = _PRIO_COLOR[prio] || 'var(--text-dim)';
    return `<span style="display:inline-block;padding:2px 10px;border-radius:3px;`
        + `border:1px solid ${color};color:${color};font-weight:700;font-size:11px;">`
        + `${_escape(prio)}</span>`;
}

function _storyCardHtml(s) {
    const t = s.triage;
    const m = s.mop_log;
    const actions = (m.recommended_actions || [])
        .map((a) => `<li>${_escape(a)}</li>`).join('');
    const ids = (m.incident_ids || []).map(_escape).join(', ');
    return `<div style="background:var(--surface,#14181D);border:1px solid var(--border,#1f262d);`
        + `border-radius:8px;padding:14px 16px;margin-bottom:10px;">`
        + `<div style="display:flex;gap:10px;align-items:center;margin-bottom:8px;">`
        + _prioBadge(t.priority)
        + `<strong style="font-size:13px;">${_escape(t.story_id)} · ${_escape(t.source)}</strong>`
        + `<span style="color:var(--text-dim);font-size:11px;">${t.incident_count} alarms`
        + ` · top severity ${_escape(t.top_severity)}</span></div>`
        + `<div style="font-size:12px;margin-bottom:8px;">${_escape(m.summary)}</div>`
        + `<div style="font-size:11px;color:var(--text-dim);margin-bottom:8px;">`
        + `Suggested procedure: <code style="color:var(--cyan,#00B8D4);">${_escape(m.suggested_procedure)}</code>`
        + ` &nbsp;·&nbsp; IDs: ${_escape(ids)}</div>`
        + (actions ? `<ul style="font-size:11px;margin:0;padding-left:18px;color:var(--text-dim);">${actions}</ul>` : '')
        + `</div>`;
}

function _setHtml(id, html) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
}

function _setStatus(msg, isError) {
    const el = document.getElementById('cp-status');
    if (!el) return;
    el.textContent = msg;
    el.style.color = isError ? 'var(--crit)' : 'var(--text-dim)';
}

// ─── Actions ───────────────────────────────────────────────────────

async function _doSimulate(scenario) {
    _setStatus(`Injecting '${scenario}' alarm burst…`, false);
    _setHtml('cp-stories', '');
    _setHtml('cp-handover', '');
    try {
        const res = await copilotSimulate(scenario, 8);
        _setStatus(`Injected ${res.injected} alarms (${_escape(scenario)}). Analyzing…`, false);
        await _doAnalyze();
    } catch (e) {
        _setStatus(`Simulate failed: ${e.message}`, true);
    }
}

async function _doAnalyze() {
    _setStatus('Correlating alarms → triage → MOP log…', false);
    try {
        const analysis = await copilotAnalyze();
        const stories = analysis.stories || [];
        _setStatus(
            `${analysis.incident_count} incidents → ${stories.length} stories `
            + `(window ${analysis.correlation_window_min} min).`, false);
        _setHtml('cp-stories',
            stories.length
                ? stories.map(_storyCardHtml).join('')
                : '<div style="color:var(--text-dim);font-size:12px;">No incidents to analyze yet.</div>');
        const handover = analysis.handover || await copilotHandover().catch(() => null);
        if (handover && handover.markdown) {
            _setHtml('cp-handover',
                `<div style="margin-top:14px;"><div class="panel-title" style="margin-bottom:8px;">`
                + `Shift handover</div><pre style="background:var(--surface,#14181D);`
                + `border:1px solid var(--border,#1f262d);border-radius:8px;padding:14px;`
                + `font-size:11px;white-space:pre-wrap;color:var(--text,#c4cdd6);">`
                + `${_escape(handover.markdown)}</pre></div>`);
        }
    } catch (e) {
        _setStatus(`Analyze failed: ${e.message}`, true);
    }
}

async function _doClear() {
    try {
        const res = await copilotClear();
        _setHtml('cp-stories', '');
        _setHtml('cp-handover', '');
        _setStatus(`Cleared ${res.cleared} copilot incidents.`, false);
    } catch (e) {
        _setStatus(`Clear failed: ${e.message}`, true);
    }
}

// ─── Wiring ──────────────────────────────────────────────────────────

/** Public entry — called once from main.js at bootstrap. */
export function initShiftCopilotView() {
    if (_initialized) return;
    if (!document.getElementById('cp-analyze')) {
        console.warn('[shift-copilot] panel not in DOM; view disabled.');
        return;
    }
    const bind = (id, fn) => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('click', (e) => { e.stopPropagation(); fn(); });
    };
    bind('cp-sim-utility', () => _doSimulate('utility_failure'));
    bind('cp-sim-chiller', () => _doSimulate('chiller_fail'));
    bind('cp-analyze', _doAnalyze);
    bind('cp-clear', _doClear);
    _initialized = true;
    console.log('[shift-copilot] view ready');
}

// ─── Test surface ──────────────────────────────────────────────────
export const __shift_copilot_test__ = {
    prioBadge: _prioBadge,
    storyCardHtml: _storyCardHtml,
    reset: () => { _initialized = false; },
};
