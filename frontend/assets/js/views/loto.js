/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/loto.js
 * ROADMAP V11 T2.1 Vector 2 — LOTO Auditor view extracted from app.js.
 *
 * The 6-pillar LOTO audit interface (Camino 1 Phase E), lifted out of
 * the monolithic IIFE into a decoupled ES module:
 *
 *   - registerRoute('loto', …) hands navigation to core/router.js.
 *     This DELETES the legacy click-delegation + setTimeout(0) hack —
 *     exactly the "zombie router" LOTO-pattern that core/router.js
 *     (T2.2) was built to retire (the DC-EPMS-MAINT-001/002/003 root).
 *   - POSTs to /api/loto/audit; renders the 6-pillar report; every
 *     interpolated value is escapeHTML'd (core/sanitize.js).
 *
 * Test surface: __loto_test__ exposes the pure render helpers.
 * ════════════════════════════════════════════════════════════════ */

import { registerRoute } from '../core/router.js';
import { escapeHTML } from '../core/sanitize.js';

const $ = (id) => document.getElementById(id);

let _routeRegistered = false;
let _viewWired = false;
let lotoLastReport = null;

// Hardcoded demo procedures (no /api/mops dependency for MVP).
const LOTO_DEMO_PROCEDURES = [
    { id: 'DEMO-UPS-COMPLIANT', label: 'DEMO-UPS-COMPLIANT (Galaxy VX with capacitor discharge per NEC 460.6)' },
    { id: 'DEMO-UPS-MISSING-DISCHARGE', label: 'DEMO-UPS-MISSING-DISCHARGE (broken: omits cap discharge step)' },
    { id: 'MOP-ATS-MONTHLY-001', label: 'MOP-ATS-MONTHLY-001 (ATS monthly transfer test)' },
];

function populateLotoProcedureSelect() {
    const sel = $('loto-procedure-select');
    if (!sel) return;
    sel.innerHTML = '<option value="">-- Select procedure --</option>'
        + LOTO_DEMO_PROCEDURES.map((p) =>
            `<option value="${escapeHTML(p.id)}">${escapeHTML(p.label)}</option>`,
        ).join('');
    // Default to COMPLIANT for first-time UX
    sel.value = 'DEMO-UPS-COMPLIANT';
}

async function submitLotoAudit() {
    const procEl = $('loto-procedure-select');
    const targetEl = $('loto-target-input');
    const cetEl = $('loto-cet-input');
    const btn = $('loto-audit-btn');
    const statusBar = $('loto-status-bar');
    const statusTxt = $('loto-status-text');
    const empty = $('loto-results-empty');
    const panel = $('loto-results-panel');

    if (!procEl || !targetEl || !cetEl || !btn) return;

    const procedure_id = procEl.value.trim();
    const target_component_id = targetEl.value.trim();
    const cet_on_duty = cetEl.value.trim();

    if (!procedure_id || !target_component_id || !cet_on_duty) {
        statusBar.style.display = 'block';
        statusBar.style.background = 'rgba(255,193,7,0.12)';
        statusBar.style.borderLeft = '3px solid #FFC107';
        statusBar.style.color = '#FFC107';
        statusTxt.textContent = 'All three fields are required.';
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Auditing...';
    statusBar.style.display = 'block';
    statusBar.style.background = 'rgba(0,184,212,0.10)';
    statusBar.style.borderLeft = '3px solid #00B8D4';
    statusBar.style.color = '#00B8D4';
    statusTxt.textContent = 'Running 6-pillar audit on ' + procedure_id
        + ' targeting ' + target_component_id + '...';

    try {
        const resp = await fetch('/api/loto/audit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ procedure_id, target_component_id, cet_on_duty }),
        });
        if (!resp.ok) {
            const t = await resp.text();
            throw new Error(`HTTP ${resp.status}: ${t.substring(0, 300)}`);
        }
        const report = await resp.json();
        lotoLastReport = report;
        renderLotoResults(report);
        empty.style.display = 'none';
        panel.hidden = false;

        statusBar.style.background = 'rgba(0,212,122,0.10)';
        statusBar.style.borderLeft = '3px solid #00d47a';
        statusBar.style.color = '#00d47a';
        statusTxt.textContent = 'Audit complete in ' + (report.decision_time_ms || '--')
            + ' ms. Status: pending_approval (per ADR-006).';
    } catch (e) {
        statusBar.style.background = 'rgba(255,80,80,0.12)';
        statusBar.style.borderLeft = '3px solid #ff5050';
        statusBar.style.color = '#ff5050';
        statusTxt.textContent = 'Audit failed: ' + (e.message || String(e));
        empty.style.display = 'block';
        panel.hidden = true;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Audit Procedure';
    }
}

function lotoOutcomeClass(outcome) {
    if (!outcome) return 'outcome-warn';
    const o = String(outcome).toUpperCase();
    if (o === 'ALL_PASS' || o === 'PASS') return 'outcome-pass';
    if (o === 'HARD_FAIL') return 'outcome-hard-fail';
    return 'outcome-warn';
}

function lotoOverallClass(outcome) {
    if (!outcome) return 'overall-warn';
    const o = String(outcome).toUpperCase();
    if (o === 'ALL_PASS' || o === 'PASS') return 'overall-all-pass';
    if (o === 'HARD_FAIL') return 'overall-hard-fail';
    return 'overall-warn';
}

function renderLotoPillar(num, title, lines, outcome) {
    const card = document.querySelector(`.loto-pillar-card[data-pillar="${num}"]`);
    const outcomeEl = document.querySelector(`[data-pillar-outcome="${num}"]`);
    const bodyEl = document.querySelector(`[data-pillar-body="${num}"]`);
    if (!card || !outcomeEl || !bodyEl) return;

    const cls = lotoOutcomeClass(outcome);
    outcomeEl.className = 'loto-pillar-outcome ' + cls;
    outcomeEl.textContent = outcome || '--';

    card.classList.remove('outcome-pass', 'outcome-warn', 'outcome-hard-fail');
    card.classList.add(cls);

    bodyEl.innerHTML = lines.map((l) => `<div>${escapeHTML(l)}</div>`).join('');
}

function renderLotoResults(report) {
    if (!report) return;

    // Overall
    const overallBadge = $('loto-overall-badge');
    const overallCard = $('loto-overall-card');
    const overallSub = $('loto-overall-sub');
    const decTime = $('loto-decision-time');
    const hardFails = $('loto-hard-fails');
    const sourcesPre = $('loto-sources-pre');

    const overall = report.overall_outcome || 'WARN';
    const ovCls = lotoOverallClass(overall);

    overallBadge.className = ovCls;
    overallBadge.textContent = overall;
    overallCard.className = '';
    overallCard.style.cssText = 'background:var(--surface,#14181D);border:2px solid var(--border,#1f262d);border-radius:8px;padding:18px;margin-bottom:14px;display:flex;align-items:center;gap:18px;';
    overallCard.classList.add(ovCls);

    overallSub.textContent = 'Procedure: ' + (report.procedure_id || '--')
        + ' | Target: ' + (report.target_component_id || '--');
    decTime.textContent = (report.decision_time_ms || '--') + ' ms';
    hardFails.textContent = (report.hard_fail_count !== undefined ? report.hard_fail_count : '--');

    // Pillar 1 - Topology
    const topo = report.topology || {};
    const blastRadius = (topo.impact_radius && topo.impact_radius.affected_components) || [];
    renderLotoPillar(1, 'Topology', [
        'Impact radius: ' + blastRadius.length + ' affected component(s)',
        'Power chain: ' + (topo.power_chain_summary || 'unknown'),
        'Cooling chain: ' + (topo.cooling_chain_summary || 'skipped'),
        'Outcome: ' + (topo.outcome || '--'),
    ], topo.outcome);

    // Pillar 2 - Redundancy
    const red = report.redundancy || {};
    renderLotoPillar(2, 'Redundancy 2N', [
        'Target path: ' + (red.target_path || '--'),
        'Path A state: ' + (red.path_a_state || '--'),
        'Path B state: ' + (red.path_b_state || '--'),
        'SHI pre/post: ' + (red.shi_pre_loto !== undefined ? red.shi_pre_loto.toFixed(3) : '--')
            + ' / ' + (red.shi_post_loto !== undefined ? red.shi_post_loto.toFixed(3) : '--')
            + ' (threshold ' + (red.shi_threshold || '--') + ')',
        'SPOFs detected: ' + ((red.single_points_of_failure || []).length),
        'Outcome: ' + (red.outcome || '--'),
    ], red.outcome);

    // Pillar 3 - Capacitor Discharge
    const cap = report.capacitor_discharge || {};
    renderLotoPillar(3, 'Capacitor Discharge', [
        'Required: ' + (cap.required ? 'yes' : 'no') + ((cap.required_reason) ? ' (' + cap.required_reason + ')' : ''),
        'Found in procedure: ' + (cap.found_in_procedure ? 'yes' : 'NO'),
        'Wait duration: ' + (cap.wait_duration_s || 0) + ' s (min required ' + (cap.minimum_required_s || 60) + ' s)',
        'Voltmeter verification: ' + (cap.voltmeter_verification ? 'yes' : 'NO'),
        'Citation: ' + (cap.citation || '--'),
        'Outcome: ' + (cap.outcome || '--'),
    ], cap.outcome);

    // Pillar 4 - Witness Gate
    const wit = report.witness_gate || {};
    renderLotoPillar(4, 'Witness Gate', [
        'Witness required: ' + (wit.witness_required ? 'yes' : 'no'),
        'Steps requiring witness: ' + ((wit.witness_required_steps || []).length),
        'Identity collision protection: ' + (wit.identity_collision_protected ? 'yes' : 'NO'),
        'Witness engine: ' + (wit.witness_engine_status || '--'),
        'Outcome: ' + (wit.outcome || '--'),
    ], wit.outcome);

    // Pillar 5 - Sequential Order
    const seq = report.sequential_order || {};
    renderLotoPillar(5, 'Sequential Order', [
        'Phase order detected: ' + ((seq.detected_phase_order || []).join(' -> ') || '--'),
        'Expected order (electrical -> hydraulic -> purge): ' + (seq.order_compliant ? 'yes' : 'NO'),
        'Outcome: ' + (seq.outcome || '--'),
    ], seq.outcome);

    // Pillar 6 - PPE Category
    const ppe = report.ppe_category || {};
    renderLotoPillar(6, 'PPE Category', [
        'Voltage class: ' + (ppe.voltage_nominal ? (ppe.voltage_nominal + ' V') : '--'),
        'Required PPE category: ' + (ppe.required_category || '--'),
        'Procedure PPE category: ' + (ppe.procedure_category || '--'),
        'Citation: NFPA 70E 130.5(C)',
        'Outcome: ' + (ppe.outcome || '--'),
    ], ppe.outcome);

    // Sources consulted (audit trail)
    if (sourcesPre) {
        sourcesPre.textContent = JSON.stringify(report.sources_consulted || {}, null, 2);
    }
}

/** Per-activation wiring — idempotent (guarded by _viewWired). */
function _wireLotoView() {
    if (_viewWired) return;
    _viewWired = true;

    populateLotoProcedureSelect();

    const btn = $('loto-audit-btn');
    if (btn) {
        btn.addEventListener('click', submitLotoAudit);
    }

    // Allow Enter key in target/cet inputs to trigger audit
    ['loto-target-input', 'loto-cet-input'].forEach((id) => {
        const el = $(id);
        if (el) {
            el.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    submitLotoAudit();
                }
            });
        }
    });

    console.log('[loto] view wired');
}

/** Public entry — called once from main.js at bootstrap. */
export function initLotoView() {
    if (_routeRegistered) return;
    if (!$('view-loto-auditor')) {
        console.warn('[loto] #view-loto-auditor not in DOM; view disabled.');
        return;
    }
    // T2.2: declarative route registry. This replaces the legacy
    // document-level click-delegation + setTimeout(0) hack that the
    // IIFE used to wire the 'loto' route (the zombie-router pattern).
    registerRoute('loto', { viewId: 'view-loto-auditor', activate: _wireLotoView });
    _routeRegistered = true;
    console.log('[loto] route registered (LOTO Auditor — T2.1 Vector 2 ES module)');
}

// ─── Test surface ──────────────────────────────────────────────────
export const __loto_test__ = {
    renderLotoResults,
    renderLotoPillar,
    lotoOutcomeClass,
    lotoOverallClass,
    populateLotoProcedureSelect,
    submitLotoAudit,
    initLotoView,
    reset: () => {
        _routeRegistered = false;
        _viewWired = false;
        lotoLastReport = null;
    },
};
