/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/multi_agent.js
 *
 * Sprint 10.1: Multi-Agent façade frontend.
 *
 * Single panel that drives POST /api/multi-agent/consult and renders
 * the consensus result + 4 per-agent cards (Architect / Safety
 * Officer / Diagnostician / Analyst).
 *
 * Visual discipline:
 *   - Consensus banner is verdict-color-coded:
 *       hard_stop -> red    (with VETO chip if Safety Officer veto)
 *       caution   -> amber
 *       approve   -> green
 *   - Agent cards in a 2x2 grid; each shows summary headline +
 *     reasoning bullets + evidence_refs in monospace.
 *   - Decision-time pill on consensus banner so the audience sees
 *     "all four agents in 350ms" without doing the math.
 *
 * Routing: LOTO/Maintenance/Tech-Assist pattern — click delegation
 * with setTimeout(0) override of the legacy navigateTo.
 * ════════════════════════════════════════════════════════════════ */

import { playVeto, playClick } from '../core/sound.js';
import { registerRoute } from '../core/router.js';
import { escapeHTML as _escape } from '../core/sanitize.js';

const API_BASE = '';

const SCENARIOS = {
    rpp: {
        query: 'Predictive trigger flagged THDi excursion on rpp_a_01 at z=12.8 sustained 3 windows. Should I authorize the LOTO right now?',
        asset_id: 'rpp_a_01',
        procedure_id: '',
        work_order_id: '',
    },
    cdu: {
        query: 'Loop flow on cdu_a_01 dropped 22% below GB200 spec. Kalman z=15.6. Authorize maintenance?',
        asset_id: 'cdu_a_01',
        procedure_id: '',
        work_order_id: '',
    },
    genset: {
        query: 'Oil pressure on genset_a_01 dropped to 38 psi (rated 45-65). Kalman z=19.2 sustained. Should I authorize?',
        asset_id: 'genset_a_01',
        procedure_id: '',
        work_order_id: '',
    },
};

let _initialized = false;

// ─── Verdict styling helpers ──────────────────────────────────────
function _verdictClass(v) {
    return {
        approve:    'good',
        caution:    'warn',
        hard_stop:  'crit',
        degraded:   'dim',
    }[v] || 'dim';
}

function _verdictLabel(v) {
    return {
        approve:    'APPROVE',
        caution:    'CAUTION',
        hard_stop:  'HARD STOP',
        degraded:   'DEGRADED',
    }[v] || (v || '—').toUpperCase();
}

// ─── Render: consensus banner ─────────────────────────────────────
function _renderConsensus(result) {
    const panel = document.getElementById('ma-consensus-panel');
    const verdictEl = document.getElementById('ma-consensus-verdict');
    const veto = document.getElementById('ma-veto-badge');
    const rationale = document.getElementById('ma-consensus-rationale');
    if (!panel || !verdictEl) return;

    const cls = _verdictClass(result.consensus);
    panel.className = `ma-consensus-panel ma-consensus-${cls}`;
    panel.removeAttribute('hidden');
    verdictEl.textContent = _verdictLabel(result.consensus);
    verdictEl.className = `ma-consensus-verdict ma-consensus-verdict-${cls}`;

    if (result.safety_officer_veto) {
        veto.removeAttribute('hidden');
    } else {
        veto.setAttribute('hidden', '');
    }
    rationale.textContent = result.rationale || '—';
}

// ─── Render: agent cards ──────────────────────────────────────────
function _renderAgents(agents) {
    const grid = document.getElementById('ma-agents-grid');
    if (!grid) return;

    if (!agents || agents.length === 0) {
        grid.innerHTML = '<div class="ma-empty">No agent verdicts returned.</div>';
        return;
    }

    // Order: Architect, Safety Officer, Diagnostician, Analyst
    const order = ['Architect', 'Safety Officer', 'Diagnostician', 'Analyst'];
    const sorted = order.map(name => agents.find(a => a.agent_name === name))
                         .filter(Boolean);

    grid.innerHTML = sorted.map(a => {
        const cls = _verdictClass(a.verdict);
        const isVeto = a.agent_name === 'Safety Officer' && a.verdict === 'hard_stop';
        const reasoning = (a.reasoning || []).map(r =>
            `<li>${_escape(r)}</li>`,
        ).join('');
        const evidence = (a.evidence_refs || []).map(e =>
            `<span class="ma-evidence">${_escape(e)}</span>`,
        ).join('');
        return `
            <div class="ma-agent-card ma-agent-card-${cls}${isVeto ? ' ma-agent-card-veto' : ''}">
                <div class="ma-agent-header">
                    <span class="ma-agent-name">${_escape(a.agent_name)}</span>
                    <span class="ma-agent-verdict ma-verdict-${cls}">${_verdictLabel(a.verdict)}</span>
                    <span class="ma-agent-time">${a.decision_time_ms} ms</span>
                </div>
                <div class="ma-agent-summary">${_escape(a.summary || '—')}</div>
                ${reasoning ? `<ul class="ma-agent-reasoning">${reasoning}</ul>` : ''}
                ${evidence ? `<div class="ma-agent-evidence-row"><span class="ma-evidence-label">evidence</span> ${evidence}</div>` : ''}
            </div>`;
    }).join('');
}

// ─── Consult ──────────────────────────────────────────────────────
async function _onConsult() {
    const queryEl = document.getElementById('ma-query');
    const assetEl = document.getElementById('ma-asset-id');
    const procEl  = document.getElementById('ma-procedure-id');
    const woEl    = document.getElementById('ma-wo-id');
    const meta    = document.getElementById('ma-consult-meta');
    const btn     = document.getElementById('ma-consult-btn');
    if (!queryEl || !btn) return;

    const query = (queryEl.value || '').trim();
    if (query.length < 3) {
        meta.textContent = 'Query too short (min 3 chars)';
        return;
    }

    const body = { query };
    const aid  = (assetEl?.value || '').trim();
    const pid  = (procEl?.value  || '').trim();
    const wid  = (woEl?.value    || '').trim();
    if (aid) body.asset_id      = aid;
    if (pid) body.procedure_id  = pid;
    if (wid) body.work_order_id = wid;

    btn.disabled = true;
    meta.textContent = 'consulting 4 agents…';

    // Reset result panels
    document.getElementById('ma-consensus-panel')?.setAttribute('hidden', '');
    document.getElementById('ma-agents-grid').innerHTML =
        '<div class="ma-empty">Agents working in parallel…</div>';

    try {
        const resp = await fetch(`${API_BASE}/api/multi-agent/consult`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!resp.ok) {
            const err = await resp.text().catch(() => `${resp.status}`);
            meta.textContent = `error ${resp.status}`;
            document.getElementById('ma-agents-grid').innerHTML =
                `<div class="ma-empty ma-error">HTTP ${resp.status}: ${_escape(err.slice(0, 300))}</div>`;
            return;
        }
        const data = await resp.json();
        meta.textContent = `${data.decision_time_ms} ms · 4 agents · ${data.consensus}`;
        _renderConsensus(data);
        _renderAgents(data.agents);
        // Tier C / C1: audio cue tracks the verdict
        if (data.safety_officer_veto || data.consensus === 'hard_stop') {
            playVeto();
        } else {
            playClick();
        }
    } catch (e) {
        meta.textContent = 'network error';
        document.getElementById('ma-agents-grid').innerHTML =
            `<div class="ma-empty ma-error">Network error: ${_escape(e.message)}</div>`;
    } finally {
        btn.disabled = false;
    }
}

function _loadScenario(name) {
    const s = SCENARIOS[name];
    if (!s) return;
    document.getElementById('ma-query').value         = s.query;
    document.getElementById('ma-asset-id').value      = s.asset_id || '';
    document.getElementById('ma-procedure-id').value  = s.procedure_id || '';
    document.getElementById('ma-wo-id').value         = s.work_order_id || '';
}

// ─── Wiring + routing ─────────────────────────────────────────────
function _wireEvents() {
    document.getElementById('ma-consult-btn')?.addEventListener('click', _onConsult);
    document.getElementById('ma-load-rpp')?.addEventListener('click',     () => _loadScenario('rpp'));
    document.getElementById('ma-load-cdu')?.addEventListener('click',     () => _loadScenario('cdu'));
    document.getElementById('ma-load-genset')?.addEventListener('click',  () => _loadScenario('genset'));
    document.getElementById('ma-query')?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            _onConsult();
        }
    });
}

function _wireRouting() {
    // T2.2: declarative registry (replaces the setTimeout(0) LOTO race).
    registerRoute('multi-agent', { viewId: 'view-multi-agent' });
}

// ─── Public API ───────────────────────────────────────────────────
export function initMultiAgentView() {
    if (_initialized) return;
    if (!document.getElementById('view-multi-agent')) {
        console.warn('[multi_agent] #view-multi-agent not in DOM; view disabled.');
        return;
    }
    _wireEvents();
    _wireRouting();
    _initialized = true;
    console.log('[multi_agent] view ready (4 agents: Architect / Safety / Diagnostician / Analyst)');
}
