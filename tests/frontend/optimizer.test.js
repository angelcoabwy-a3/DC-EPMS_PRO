/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/optimizer.test.js
 * ROADMAP V11 Epic 2 Batch 2.D — HMI surface for the Optimizer queue.
 *
 * Verifies the per-view minima (S-TEST-02): render, XSS escaping,
 * route registration. Plus the action paths (POST approve / reject)
 * and the live-refresh wiring (hermes:optimizer-proposal).
 *
 * No browser, no backend — fetch is stubbed; happy-dom provides the
 * DOM.
 * ════════════════════════════════════════════════════════════════ */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { __optimizer_view_test__ } from '/assets/js/views/optimizer.js';
import { isRegistered } from '/assets/js/core/router.js';

const {
    renderQueue, renderProposalCard,
    renderHeartbeat, renderAgentVotesTable,
    renderHistory, renderForensicTrail, renderPreview,
    submitApprove, submitReject, fetchQueue, fetchHealth,
    fetchHistory, fetchForensicTrail, fetchPreview,
    toggleHistorySidebar,
    onClick,
    onHermesProposal, onHermesTick,
    initOptimizerView, reset,
} = __optimizer_view_test__;

// ── Test fixtures ────────────────────────────────────────────────────
function _qp(overrides = {}) {
    return {
        proposal: {
            proposal_id: overrides.proposal_id || 'qp-1234abcd',
            surface: overrides.surface || 'chiller_lwt',
            current_value: 7.5,
            proposed_value: 7.0,
            delta: -0.5,
            rationale: 'PUE drift sustained; LWT headroom available.',
            pue_at_emission: 1.35,
            created_at: 1.0,
        },
        consensus_verdict: overrides.consensus_verdict || 'approve',
        consensus_rationale: overrides.consensus_rationale
            || 'All agents converge on approve.',
        safety_officer_veto: !!overrides.safety_officer_veto,
        optimizer_narrative: overrides.optimizer_narrative
            || 'Lowering LWT cuts compressor work; projected dPUE -0.01.',
        queued_at: 2.0,
    };
}

function _mountView() {
    document.body.innerHTML = `
        <div id="view-optimizer">
            <button data-opt-refresh></button>
            <span data-opt-counter></span>
            <div data-opt-list></div>
        </div>`;
}

beforeEach(() => {
    document.body.innerHTML = '';
});

afterEach(() => {
    reset();
    document.body.innerHTML = '';
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
});

// ── Render ──────────────────────────────────────────────────────────
describe('Batch 2.D — views/optimizer.js renderQueue', () => {
    it('shows the empty state when the queue is empty', () => {
        _mountView();
        renderQueue([], 0);
        const list = document.querySelector('[data-opt-list]');
        expect(list.textContent).toContain('No pending proposals');
        expect(document.querySelector('[data-opt-counter]').textContent)
            .toBe('Queue: 0 pending');
    });

    it('renders one card per queued proposal with surface + delta', () => {
        _mountView();
        renderQueue([_qp({ proposal_id: 'a' }), _qp({ proposal_id: 'b', surface: 'ct_fan_vfd' })], 2);
        const cards = document.querySelectorAll('.opt-card');
        expect(cards).toHaveLength(2);
        expect(cards[0].dataset.proposalId).toBe('a');
        expect(cards[1].querySelector('.opt-surface').textContent).toBe('ct_fan_vfd');
        // Delta is rendered (format like "Δ -0.50")
        expect(cards[0].querySelector('.opt-delta').textContent).toContain('-0.50');
    });

    it('flags a safety_officer_veto with a SAFETY VETO badge', () => {
        _mountView();
        renderQueue([_qp({ proposal_id: 'veto-1', safety_officer_veto: true })], 1);
        expect(document.querySelector('.opt-veto')).not.toBeNull();
    });
});

// ── XSS — the load-bearing S-SEC-01 gate ────────────────────────────
describe('Batch 2.D — views/optimizer.js S-SEC-01 XSS routing', () => {
    it('a hostile <img onerror=...> in optimizer_narrative is neutralised', () => {
        _mountView();
        renderQueue([_qp({
            proposal_id: 'qp-xss',
            optimizer_narrative: '<img src=x onerror=window.__pwned=1>',
        })], 1);
        // sanitizeHTML drops the <img> entirely.
        const list = document.querySelector('[data-opt-list]');
        expect(list.querySelector('img')).toBeNull();
        expect(window.__pwned).toBeUndefined();
    });

    it('a <script> tag in consensus_rationale is dropped', () => {
        _mountView();
        renderQueue([_qp({
            proposal_id: 'qp-script',
            consensus_rationale: '<script>window.__pwn=1</script>safe',
        })], 1);
        const list = document.querySelector('[data-opt-list]');
        expect(list.querySelector('script')).toBeNull();
        expect(window.__pwn).toBeUndefined();
    });

    it('a hostile proposal_id is escaped in the data attribute', () => {
        _mountView();
        renderQueue([_qp({ proposal_id: '"><img src=x onerror=alert(1)>' })], 1);
        const list = document.querySelector('[data-opt-list]');
        // The escapeHTML on proposal_id keeps the attribute literal,
        // not parsed as new markup — no injected <img> from the id.
        expect(list.querySelector('img')).toBeNull();
    });
});

// ── fetchQueue ──────────────────────────────────────────────────────
describe('Batch 2.D — views/optimizer.js fetchQueue', () => {
    it('GETs /api/optimizer/proposals and renders the response', async () => {
        _mountView();
        const spy = vi.fn(async () => ({
            ok: true, status: 200,
            json: async () => ({ proposals: [_qp({ proposal_id: 'live-1' })], queue_size: 1 }),
        }));
        vi.stubGlobal('fetch', spy);
        await fetchQueue();
        expect(spy).toHaveBeenCalledWith('/api/optimizer/proposals');
        expect(document.querySelectorAll('.opt-card')).toHaveLength(1);
        expect(document.querySelector('.opt-card').dataset.proposalId).toBe('live-1');
    });

    it('shows the "service not running" hint on HTTP 503', async () => {
        _mountView();
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: false, status: 503,
            json: async () => ({}),
        })));
        await fetchQueue();
        expect(document.querySelector('[data-opt-list]').textContent)
            .toContain('Optimizer service not running');
    });

    it('shows an error inline on a fetch failure', async () => {
        _mountView();
        vi.stubGlobal('fetch', vi.fn(async () => {
            throw new Error('Network down');
        }));
        await fetchQueue();
        expect(document.querySelector('[data-opt-list]').textContent)
            .toContain('Failed to fetch proposals');
        expect(document.querySelector('[data-opt-list]').textContent)
            .toContain('Network down');
    });
});

// ── Approve ─────────────────────────────────────────────────────────
describe('Batch 2.D — views/optimizer.js submitApprove (S-SEC-02 claim)', () => {
    function _mountWithProposal(pid = 'qp-app') {
        _mountView();
        renderQueue([_qp({ proposal_id: pid })], 1);
        // Reveal the approve form (mimics the operator clicking Approve).
        const form = document.querySelector(
            `.opt-form-approve[data-proposal-id="${pid}"]`,
        );
        form.hidden = false;
        return form;
    }

    it('POSTs the actor_role + confirm_ashrae claim to /approve/{id}', async () => {
        const form = _mountWithProposal('qp-A');
        form.querySelector('.opt-ashrae-check').checked = true;
        form.querySelector('.opt-operator-input').value = 'wilmer.angel';

        // Two fetches will fire — POST /approve, then a follow-up GET /proposals.
        const spy = vi.fn(async (url) => {
            if (url.startsWith('/api/optimizer/approve/')) {
                return {
                    ok: true, status: 200,
                    json: async () => ({
                        decision: 'approved',
                        bms_write_success: true,
                        bms_tag_id: 'HVAC.CHILLER_1.LWT_SETPOINT',
                        bms_write_message: 'ok',
                    }),
                };
            }
            // refresh
            return {
                ok: true, status: 200,
                json: async () => ({ proposals: [], queue_size: 0 }),
            };
        });
        vi.stubGlobal('fetch', spy);

        await submitApprove('qp-A');

        // First call: the approval POST
        const [postUrl, postOpts] = spy.mock.calls[0];
        expect(postUrl).toBe('/api/optimizer/approve/qp-A');
        expect(postOpts.method).toBe('POST');
        const body = JSON.parse(postOpts.body);
        expect(body.actor_role).toBe('SME_L6');
        expect(body.operator_id).toBe('wilmer.angel');
        expect(body.confirm_ashrae).toBe(true);

        // Result rendered inline
        const result = document.querySelector('.opt-result[data-proposal-id="qp-A"]');
        expect(result.textContent).toContain('APPROVED');
        expect(result.textContent).toContain('BMS write OK');
    });

    it('refuses to POST when confirm_ashrae is unchecked', async () => {
        _mountWithProposal('qp-noashrae');
        // confirm-ashrae deliberately left unchecked.
        const spy = vi.fn();
        vi.stubGlobal('fetch', spy);
        await submitApprove('qp-noashrae');
        expect(spy).not.toHaveBeenCalled();
        const result = document.querySelector('.opt-result[data-proposal-id="qp-noashrae"]');
        expect(result.textContent).toContain('ASHRAE');
    });

    it('shows the server error detail when POST returns 403', async () => {
        const form = _mountWithProposal('qp-403');
        form.querySelector('.opt-ashrae-check').checked = true;
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: false, status: 403,
            statusText: 'Forbidden',
            json: async () => ({ detail: 'requires SME_L6' }),
        })));
        await submitApprove('qp-403');
        const result = document.querySelector('.opt-result[data-proposal-id="qp-403"]');
        expect(result.textContent).toContain('403');
        expect(result.textContent).toContain('requires SME_L6');
    });
});

// ── Reject ──────────────────────────────────────────────────────────
describe('Batch 2.D — views/optimizer.js submitReject', () => {
    function _mountWithProposal(pid = 'qp-rej') {
        _mountView();
        renderQueue([_qp({ proposal_id: pid })], 1);
        const form = document.querySelector(
            `.opt-form-reject[data-proposal-id="${pid}"]`,
        );
        form.hidden = false;
        return form;
    }

    it('POSTs reason + actor_role to /reject/{id}', async () => {
        const form = _mountWithProposal('qp-R');
        form.querySelector('.opt-reason-input').value = 'Hall already cool.';
        const spy = vi.fn(async (url) => {
            if (url.startsWith('/api/optimizer/reject/')) {
                return {
                    ok: true, status: 200,
                    json: async () => ({
                        decision: 'rejected',
                        reason: 'Hall already cool.',
                    }),
                };
            }
            return { ok: true, status: 200, json: async () => ({ proposals: [], queue_size: 0 }) };
        });
        vi.stubGlobal('fetch', spy);

        await submitReject('qp-R');
        const [postUrl, postOpts] = spy.mock.calls[0];
        expect(postUrl).toBe('/api/optimizer/reject/qp-R');
        const body = JSON.parse(postOpts.body);
        expect(body.actor_role).toBe('SME_L6');
        expect(body.reason).toBe('Hall already cool.');

        const result = document.querySelector('.opt-result[data-proposal-id="qp-R"]');
        expect(result.textContent).toContain('REJECTED');
    });

    it('refuses to POST when the reason is empty', async () => {
        _mountWithProposal('qp-noreason');
        const spy = vi.fn();
        vi.stubGlobal('fetch', spy);
        await submitReject('qp-noreason');
        expect(spy).not.toHaveBeenCalled();
        const result = document.querySelector('.opt-result[data-proposal-id="qp-noreason"]');
        expect(result.textContent).toContain('Reason is required');
    });
});

// ── Route registration (S-ROUTE-01) ─────────────────────────────────
describe('Batch 2.D — views/optimizer.js route registration', () => {
    it('initOptimizerView registers "optimizer" on core/router.js', () => {
        document.body.innerHTML = '<div id="view-optimizer"></div>';
        initOptimizerView();
        expect(isRegistered('optimizer')).toBe(true);
    });

    it('a Hermes optimizer-proposal event triggers a queue refresh', async () => {
        // _mountView pre-installs the [data-opt-list] skeleton so
        // _fetchQueue doesn't early-return (the activate handler
        // would do this in production, but the test path bypasses
        // the router by calling the listener directly).
        _mountView();
        const spy = vi.fn(async () => ({
            ok: true, status: 200,
            json: async () => ({ proposals: [], queue_size: 0 }),
        }));
        vi.stubGlobal('fetch', spy);
        await fetchQueue();                  // initial fetch
        await onHermesProposal();            // hermes-triggered refetch
        expect(spy.mock.calls.length).toBe(2);
    });
});


// ════════════════════════════════════════════════════════════════════
// Epic 5 Sprint 1 — Observability
// ════════════════════════════════════════════════════════════════════

function _mountViewWithHeartbeat() {
    document.body.innerHTML = `
        <div id="view-optimizer">
            <button data-opt-refresh></button>
            <span data-opt-counter></span>
            <div data-opt-heartbeat></div>
            <div data-opt-list></div>
        </div>`;
}

// ── E5.A — heartbeat strip ──────────────────────────────────────────
describe('Epic 5.A — renderHeartbeat', () => {
    it('renders running + tick count + outcomes', () => {
        _mountViewWithHeartbeat();
        renderHeartbeat({
            is_running: true,
            last_tick_unix: Math.floor(Date.now() / 1000) - 5,
            tick_count: 42,
            last_tick_outcomes: {
                sustained: true,
                drift: 0.0432,
                n_proposals: 2,
                n_paced_out: 1,
                n_vetoed: 0,
            },
            queue_size: 3,
        });
        const strip = document.querySelector('[data-opt-heartbeat]');
        expect(strip.textContent).toContain('RUNNING');
        expect(strip.textContent).toContain('tick #42');
        expect(strip.textContent).toContain('drift sustained');
        expect(strip.textContent).toContain('drift 0.043');
        expect(strip.textContent).toContain('proposed 2');
        expect(strip.textContent).toContain('paced 1');
        expect(strip.textContent).toContain('vetoed 0');
        expect(strip.textContent).toContain('queue 3');
    });

    it('renders STOPPED when is_running=false', () => {
        _mountViewWithHeartbeat();
        renderHeartbeat({
            is_running: false,
            last_tick_unix: 0,
            tick_count: 0,
            last_tick_outcomes: {},
            queue_size: 0,
        });
        const strip = document.querySelector('[data-opt-heartbeat]');
        expect(strip.textContent).toContain('STOPPED');
    });

    it('shows "unknown" placeholder when health payload is missing', () => {
        _mountViewWithHeartbeat();
        renderHeartbeat(null);
        const strip = document.querySelector('[data-opt-heartbeat]');
        expect(strip.textContent).toContain('unknown');
    });

    it('XSS — hostile tick_count is escaped, not rendered as markup', () => {
        _mountViewWithHeartbeat();
        renderHeartbeat({
            is_running: true,
            last_tick_unix: Math.floor(Date.now() / 1000),
            // Number(...) coerces to NaN -> 0, but if the value passes through
            // it must be escaped, not interpolated as HTML.
            tick_count: '<img src=x onerror=alert(1)>',
            last_tick_outcomes: {},
            queue_size: 0,
        });
        const strip = document.querySelector('[data-opt-heartbeat]');
        expect(strip.querySelector('img')).toBeNull();
    });
});

describe('Epic 5.A — fetchHealth', () => {
    it('GETs /api/optimizer/health and renders the strip', async () => {
        _mountViewWithHeartbeat();
        const spy = vi.fn(async () => ({
            ok: true, status: 200,
            json: async () => ({
                is_running: true,
                last_tick_unix: Math.floor(Date.now() / 1000),
                tick_count: 5,
                last_tick_outcomes: { sustained: false, drift: 0.01, n_proposals: 0 },
                queue_size: 0,
            }),
        }));
        vi.stubGlobal('fetch', spy);
        await fetchHealth();
        expect(spy).toHaveBeenCalledWith('/api/optimizer/health');
        const strip = document.querySelector('[data-opt-heartbeat]');
        expect(strip.textContent).toContain('RUNNING');
        expect(strip.textContent).toContain('tick #5');
    });

    it('renders the "service not running" message on HTTP 503', async () => {
        _mountViewWithHeartbeat();
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: false, status: 503, json: async () => ({}),
        })));
        await fetchHealth();
        const strip = document.querySelector('[data-opt-heartbeat]');
        expect(strip.textContent).toContain('Optimizer service not running');
    });

    it('renders an error message on network failure', async () => {
        _mountViewWithHeartbeat();
        vi.stubGlobal('fetch', vi.fn(async () => {
            throw new Error('Network down');
        }));
        await fetchHealth();
        const strip = document.querySelector('[data-opt-heartbeat]');
        expect(strip.textContent).toContain('heartbeat error');
        expect(strip.textContent).toContain('Network down');
    });
});

describe('Epic 5.A — onHermesTick event', () => {
    it('renders the strip from the event detail without re-fetching', () => {
        _mountViewWithHeartbeat();
        const fetchSpy = vi.fn();
        vi.stubGlobal('fetch', fetchSpy);
        const ev = new CustomEvent('hermes:optimizer-tick', {
            detail: {
                tick_unix: Math.floor(Date.now() / 1000),
                tick_count: 99,
                outcomes: {
                    sustained: true, drift: 0.05,
                    n_proposals: 1, n_paced_out: 0, n_vetoed: 0,
                },
                queue_size: 4,
                is_running: true,
            },
        });
        onHermesTick(ev);
        const strip = document.querySelector('[data-opt-heartbeat]');
        expect(strip.textContent).toContain('tick #99');
        expect(strip.textContent).toContain('queue 4');
        // The detail-fast-path must NOT trigger a network round-trip.
        expect(fetchSpy).not.toHaveBeenCalled();
    });
});


// ── E5.C — per-agent voting table ───────────────────────────────────
describe('Epic 5.C — renderAgentVotesTable', () => {
    it('renders one row per agent with name + verdict + summary', () => {
        const html = renderAgentVotesTable({
            agent_verdicts: [
                { agent_name: 'Architect', verdict: 'approve', summary: 'topology ok' },
                { agent_name: 'Safety Officer', verdict: 'approve', summary: 'no LOTO' },
                { agent_name: 'Diagnostician', verdict: 'approve', summary: 'no recurrence' },
                { agent_name: 'Analyst', verdict: 'approve', summary: 'opex cheap' },
                { agent_name: 'Capacity Planner', verdict: 'approve', summary: 'headroom ok' },
                { agent_name: 'Carbon/Grid', verdict: 'caution', summary: 'on-peak TOU' },
            ],
        });
        const div = document.createElement('div');
        div.innerHTML = html;
        const rows = div.querySelectorAll('tr.opt-vote-row');
        expect(rows.length).toBe(6);
        // Architect row content
        expect(rows[0].querySelector('.opt-vote-name').textContent).toBe('Architect');
        expect(rows[0].querySelector('.opt-vote-verdict').textContent).toContain('approve');
        // Carbon/Grid caution row
        expect(rows[5].querySelector('.opt-vote-name').textContent).toBe('Carbon/Grid');
        expect(rows[5].querySelector('.opt-vote-verdict').textContent).toContain('caution');
    });

    it('flags Safety Officer hard_stop with an unmistakable veto badge', () => {
        const html = renderAgentVotesTable({
            agent_verdicts: [
                { agent_name: 'Safety Officer', verdict: 'hard_stop', summary: 'capacitor-class — VETO' },
                { agent_name: 'Architect', verdict: 'approve', summary: 'topology ok' },
            ],
        });
        const div = document.createElement('div');
        div.innerHTML = html;
        const safetyRow = div.querySelector('.opt-vote-row-veto');
        expect(safetyRow).not.toBeNull();
        expect(safetyRow.querySelector('.opt-vote-name').textContent).toBe('Safety Officer');
        // The veto badge carries the BADGE class AND the SAFETY VETO label.
        const badge = safetyRow.querySelector('.opt-vote-badge-veto');
        expect(badge).not.toBeNull();
        expect(badge.textContent).toContain('SAFETY VETO');
    });

    it('does NOT flag Safety Officer approve as a veto (S-DET-02 binding)', () => {
        const html = renderAgentVotesTable({
            agent_verdicts: [
                { agent_name: 'Safety Officer', verdict: 'approve', summary: 'ok' },
            ],
        });
        const div = document.createElement('div');
        div.innerHTML = html;
        expect(div.querySelector('.opt-vote-row-veto')).toBeNull();
        expect(div.querySelector('.opt-vote-badge-veto')).toBeNull();
    });

    it('does NOT flag other agents hard_stop as a Safety VETO', () => {
        // Per the S-DET-02 binding: only the Safety Officer holds VETO
        // authority. A Carbon/Grid hard_stop (rank-2 branch) is NOT a
        // veto — must render as a normal hard_stop, no SAFETY VETO badge.
        const html = renderAgentVotesTable({
            agent_verdicts: [
                { agent_name: 'Carbon/Grid', verdict: 'hard_stop', summary: 'carbon HIGH + on-peak' },
            ],
        });
        const div = document.createElement('div');
        div.innerHTML = html;
        expect(div.querySelector('.opt-vote-badge-veto')).toBeNull();
        expect(div.textContent).not.toContain('SAFETY VETO');
    });

    it('renders an empty-state row when agent_verdicts is missing', () => {
        const html = renderAgentVotesTable({});
        expect(html).toContain('no per-agent breakdown');
    });

    it('XSS — hostile agent_name + summary are escaped', () => {
        const html = renderAgentVotesTable({
            agent_verdicts: [
                {
                    agent_name: '<img src=x onerror=window.__pwn1=1>',
                    verdict: 'approve',
                    summary: '<script>window.__pwn2=1</script>',
                },
            ],
        });
        const div = document.createElement('div');
        div.innerHTML = html;
        expect(div.querySelector('img')).toBeNull();
        expect(div.querySelector('script')).toBeNull();
        expect(window.__pwn1).toBeUndefined();
        expect(window.__pwn2).toBeUndefined();
    });
});

// ── E5.C — proposal card embeds the vote table ──────────────────────
describe('Epic 5.C — renderProposalCard embeds agent votes', () => {
    it('shows the per-agent table inside the card body', () => {
        _mountView();
        renderQueue([{
            ..._qp({ proposal_id: 'qp-votes' }),
            agent_verdicts: [
                { agent_name: 'Architect', verdict: 'approve', summary: 'ok' },
                { agent_name: 'Safety Officer', verdict: 'hard_stop', summary: 'VETO' },
            ],
        }], 1);
        const card = document.querySelector('.opt-card');
        const table = card.querySelector('table.opt-votes');
        expect(table).not.toBeNull();
        expect(table.querySelectorAll('tr.opt-vote-row').length).toBe(2);
        // Safety row carries the unmistakable veto badge.
        expect(table.querySelector('.opt-vote-badge-veto')).not.toBeNull();
    });
});


// ════════════════════════════════════════════════════════════════════
// Epic 5 Sprint 2 — auditability + sandbox preview
// ════════════════════════════════════════════════════════════════════

function _mountFullView() {
    document.body.innerHTML = `
        <div id="view-optimizer">
            <button data-opt-refresh></button>
            <span data-opt-counter></span>
            <button data-opt-history-toggle></button>
            <span data-opt-history-counter>0</span>
            <div data-opt-heartbeat></div>
            <div data-opt-list></div>
            <aside data-opt-history hidden data-open="0">
                <div data-opt-history-body></div>
            </aside>
        </div>`;
}

// ── E5.B — Approval history sidebar ─────────────────────────────────
describe('Epic 5.B — renderHistory + fetchHistory', () => {
    it('renders the empty-state message when no approvals', () => {
        _mountFullView();
        renderHistory([]);
        expect(document.querySelector('[data-opt-history-body]').textContent)
            .toContain('No recent decisions');
    });

    it('renders one li.opt-hist-row per approval, newest first', () => {
        _mountFullView();
        renderHistory([
            {
                proposal_id: 'qp-1', decision: 'approved',
                operator_id: 'op1', actor_role: 'SME_L6',
                decision_at: 1700000000,
                bms_tag_id: 'HVAC.CHILLER1.CW_SETPOINT',
                bms_write_success: true,
            },
            {
                proposal_id: 'qp-2', decision: 'rejected',
                operator_id: 'op2', actor_role: 'MANAGER_L7',
                decision_at: 1700000060,
                reason: 'Hall already cool',
            },
        ]);
        const rows = document.querySelectorAll('li.opt-hist-row');
        expect(rows).toHaveLength(2);
        // Newest first (decision_at=1700000060 -> qp-2)
        expect(rows[0].textContent).toContain('REJECTED');
        expect(rows[0].textContent).toContain('Hall already cool');
        // First row carries the rejected class
        expect(rows[0].classList.contains('opt-hist-rejected')).toBe(true);
        // The approved row shows a BMS OK badge
        expect(rows[1].querySelector('.opt-hist-write-ok')).not.toBeNull();
    });

    it('XSS — hostile operator_id + reason are escaped', () => {
        _mountFullView();
        renderHistory([{
            proposal_id: 'qp-xss', decision: 'approved',
            operator_id: '<img src=x onerror=window.__h1=1>',
            actor_role: 'SME_L6',
            decision_at: 1700000000,
            reason: '<script>window.__h2=1</script>',
        }]);
        const body = document.querySelector('[data-opt-history-body]');
        expect(body.querySelector('img')).toBeNull();
        expect(body.querySelector('script')).toBeNull();
        expect(window.__h1).toBeUndefined();
        expect(window.__h2).toBeUndefined();
    });

    it('fetchHistory GETs /api/optimizer/approvals and renders', async () => {
        _mountFullView();
        const spy = vi.fn(async () => ({
            ok: true, status: 200,
            json: async () => ({
                approvals: [{
                    proposal_id: 'qp-A', decision: 'approved',
                    operator_id: 'op', actor_role: 'SME_L6',
                    decision_at: 1700000000,
                }],
                total: 1,
            }),
        }));
        vi.stubGlobal('fetch', spy);
        await fetchHistory();
        expect(spy).toHaveBeenCalledWith('/api/optimizer/approvals');
        expect(document.querySelectorAll('li.opt-hist-row')).toHaveLength(1);
        expect(document.querySelector('[data-opt-history-counter]').textContent).toBe('1');
    });

    it('toggleHistorySidebar flips the aside [hidden] + dataset.open', () => {
        _mountFullView();
        const aside = document.querySelector('[data-opt-history]');
        expect(aside.hidden).toBe(true);
        toggleHistorySidebar();
        expect(aside.hidden).toBe(false);
        expect(aside.dataset.open).toBe('1');
        toggleHistorySidebar();
        expect(aside.hidden).toBe(true);
    });
});


// ── E5.D — Per-card forensic trail ──────────────────────────────────
describe('Epic 5.D — renderForensicTrail + fetchForensicTrail', () => {
    function _mountWithTrailSlot(pid = 'qp-trail') {
        _mountView();
        renderQueue([{ ..._qp({ proposal_id: pid }) }], 1);
        // Card was rendered with a hidden .opt-trail slot per proposal.
        const slot = document.querySelector(
            `.opt-trail[data-proposal-id="${pid}"]`,
        );
        slot.hidden = false;
        return slot;
    }

    it('renders the empty-state when no ledger entries match', () => {
        _mountWithTrailSlot('qp-empty');
        renderForensicTrail('qp-empty', { entries: [] });
        const slot = document.querySelector('.opt-trail[data-proposal-id="qp-empty"]');
        expect(slot.textContent).toContain('No ledger entries linked');
    });

    it('renders REQUESTED + RESULT entries with sequence + hmac chips', () => {
        _mountWithTrailSlot('qp-trail');
        renderForensicTrail('qp-trail', {
            entries: [
                {
                    entry_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
                    sequence_no: 12, action: 'BMS_WRITE_REQUESTED',
                    actor: 'optimizer', ts: '2026-05-23T18:00:00Z',
                    entry_hmac: '0123456789abcdef0123456789abcdef',
                    key_version: 1,
                    payload: { tag_id: 'HVAC.X', proposal_id: 'qp-trail' },
                },
                {
                    entry_id: 'ffffffff-bbbb-cccc-dddd-eeeeeeeeeeee',
                    sequence_no: 13, action: 'BMS_WRITE_RESULT',
                    actor: 'optimizer', ts: '2026-05-23T18:00:01Z',
                    entry_hmac: 'fedcba9876543210fedcba9876543210',
                    key_version: 1,
                    payload: {
                        ref_entry_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
                        success: true, message: 'ok',
                    },
                },
            ],
            matched: 2,
            total: 200,
        });
        const slot = document.querySelector('.opt-trail[data-proposal-id="qp-trail"]');
        const entries = slot.querySelectorAll('li.opt-trail-entry');
        expect(entries).toHaveLength(2);
        expect(entries[0].textContent).toContain('#12');
        expect(entries[0].textContent).toContain('BMS_WRITE_REQUESTED');
        expect(entries[1].textContent).toContain('BMS_WRITE_RESULT');
        // The header line says how many entries are linked + chain total.
        expect(slot.textContent).toContain('2 entries linked');
        expect(slot.textContent).toContain('200');
    });

    it('XSS — hostile payload is rendered as escaped JSON, not parsed', () => {
        _mountWithTrailSlot('qp-xss-trail');
        renderForensicTrail('qp-xss-trail', {
            entries: [{
                entry_id: 'x', sequence_no: 1, action: 'X',
                actor: '<script>window.__t1=1</script>',
                ts: 't', entry_hmac: 'h', key_version: 0,
                payload: { evil: '<img src=x onerror=window.__t2=1>' },
            }],
            matched: 1, total: 1,
        });
        const slot = document.querySelector('.opt-trail[data-proposal-id="qp-xss-trail"]');
        expect(slot.querySelector('script')).toBeNull();
        expect(slot.querySelector('img')).toBeNull();
        expect(window.__t1).toBeUndefined();
        expect(window.__t2).toBeUndefined();
    });

    it('fetchForensicTrail GETs the proposal-scoped endpoint', async () => {
        _mountWithTrailSlot('qp-fetch');
        const spy = vi.fn(async () => ({
            ok: true, status: 200,
            json: async () => ({
                entries: [], matched: 0, total: 0,
            }),
        }));
        vi.stubGlobal('fetch', spy);
        await fetchForensicTrail('qp-fetch');
        expect(spy).toHaveBeenCalledWith(
            '/api/ledger/entries?proposal_id=qp-fetch',
        );
    });
});


// ── E5.E — Preview impact ───────────────────────────────────────────
describe('Epic 5.E — renderPreview + fetchPreview', () => {
    function _mountWithPreviewSlot(pid = 'qp-preview') {
        _mountView();
        renderQueue([{ ..._qp({ proposal_id: pid }) }], 1);
        const slot = document.querySelector(
            `.opt-preview[data-proposal-id="${pid}"]`,
        );
        slot.hidden = false;
        return slot;
    }

    it('renders a GREEN projection card with PUE / WUE / inlet rows', () => {
        _mountWithPreviewSlot('qp-green');
        renderPreview('qp-green', {
            proposal_id: 'qp-green', surface: 'chiller_lwt',
            current_value: 7.5, proposed_value: 7.0, delta: -0.5,
            projected_pue: 1.307, projected_pue_delta: -0.003,
            projected_wue_delta: 0.0,
            projected_inlet_c: 21.8, projected_inlet_delta_c: -0.2,
            ashrae_distance_c: 13.2,
            verdict: 'green',
            findings: ['projected PUE 1.307 <= target+0.02'],
        });
        const slot = document.querySelector('.opt-preview[data-proposal-id="qp-green"]');
        expect(slot.querySelector('.opt-preview-green')).not.toBeNull();
        expect(slot.textContent).toContain('GREEN');
        expect(slot.textContent).toContain('1.307');
        expect(slot.textContent).toContain('-0.003');
        expect(slot.textContent).toContain('13.20');
        // The deterministic-sandbox note is rendered (S-DET-01 evidence).
        expect(slot.textContent).toContain('S-DET-01');
    });

    it('renders a RED projection with findings', () => {
        _mountWithPreviewSlot('qp-red');
        renderPreview('qp-red', {
            proposal_id: 'qp-red', surface: 'chiller_lwt',
            current_value: 7.0, proposed_value: 9.0, delta: 2.0,
            projected_pue: 1.32, projected_pue_delta: 0.012,
            projected_wue_delta: 0.0,
            projected_inlet_c: 35.3, projected_inlet_delta_c: 0.8,
            ashrae_distance_c: -0.3,
            verdict: 'red',
            findings: [
                'projected hall inlet 35.30 C >= A2 breach 35.0 C',
            ],
        });
        const slot = document.querySelector('.opt-preview[data-proposal-id="qp-red"]');
        expect(slot.querySelector('.opt-preview-red')).not.toBeNull();
        expect(slot.textContent).toContain('RED');
        expect(slot.querySelectorAll('ul.opt-preview-findings li').length).toBe(1);
    });

    it('fetchPreview POSTs to /api/optimizer/preview/{id}', async () => {
        _mountWithPreviewSlot('qp-post');
        const spy = vi.fn(async () => ({
            ok: true, status: 200,
            json: async () => ({
                proposal_id: 'qp-post', surface: 'chiller_lwt',
                current_value: 7.5, proposed_value: 7.0, delta: -0.5,
                projected_pue: 1.31, projected_pue_delta: -0.003,
                projected_wue_delta: 0, projected_inlet_c: 21.8,
                projected_inlet_delta_c: -0.2, ashrae_distance_c: 13.2,
                verdict: 'green', findings: [],
            }),
        }));
        vi.stubGlobal('fetch', spy);
        await fetchPreview('qp-post');
        const [url, opts] = spy.mock.calls[0];
        expect(url).toBe('/api/optimizer/preview/qp-post');
        expect(opts.method).toBe('POST');
        const slot = document.querySelector('.opt-preview[data-proposal-id="qp-post"]');
        expect(slot.textContent).toContain('GREEN');
    });

    it('shows a 404 message when the proposal is no longer queued', async () => {
        _mountWithPreviewSlot('qp-gone');
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: false, status: 404, json: async () => ({ detail: 'gone' }),
        })));
        await fetchPreview('qp-gone');
        const slot = document.querySelector('.opt-preview[data-proposal-id="qp-gone"]');
        expect(slot.textContent.toLowerCase()).toContain('no longer queued');
    });

    it('XSS — hostile findings strings are escaped', () => {
        _mountWithPreviewSlot('qp-xss-prev');
        renderPreview('qp-xss-prev', {
            proposal_id: 'qp-xss-prev', surface: 'chiller_lwt',
            current_value: 7, proposed_value: 7, delta: 0,
            projected_pue: 1.3, projected_pue_delta: 0,
            projected_wue_delta: 0, projected_inlet_c: 22,
            projected_inlet_delta_c: 0, ashrae_distance_c: 13,
            verdict: 'green',
            findings: ['<img src=x onerror=window.__p1=1>'],
        });
        const slot = document.querySelector('.opt-preview[data-proposal-id="qp-xss-prev"]');
        expect(slot.querySelector('img')).toBeNull();
        expect(window.__p1).toBeUndefined();
    });
});


// ── Card actions wire-up ────────────────────────────────────────────
//
// The production view wires `_onClick` once via root.addEventListener
// inside _wireOptimizerView(). Calling that here would couple us to
// the full activate path. Instead we test the dispatch contract: when
// onClick sees a [data-action] element with the right action + pid,
// it triggers the matching fetch path. Equivalent coverage, less
// fixture coupling.
function _fakeClickEvent(targetEl) {
    return { target: targetEl };
}

describe('Epic 5.B/D/E — card actions trigger the right handlers', () => {
    it('"Preview impact" action dispatches the preview POST', async () => {
        _mountView();
        renderQueue([_qp({ proposal_id: 'qp-clk' })], 1);
        const spy = vi.fn(async () => ({
            ok: true, status: 200,
            json: async () => ({
                proposal_id: 'qp-clk', surface: 'chiller_lwt',
                current_value: 7.5, proposed_value: 7.0, delta: -0.5,
                projected_pue: 1.31, projected_pue_delta: -0.003,
                projected_wue_delta: 0, projected_inlet_c: 22,
                projected_inlet_delta_c: 0, ashrae_distance_c: 13,
                verdict: 'green', findings: [],
            }),
        }));
        vi.stubGlobal('fetch', spy);
        const btn = document.querySelector(
            '.opt-btn-preview[data-proposal-id="qp-clk"]',
        );
        expect(btn).not.toBeNull();
        onClick(_fakeClickEvent(btn));
        await Promise.resolve(); await Promise.resolve();
        const urls = spy.mock.calls.map((c) => c[0]);
        expect(urls.some((u) => u.startsWith('/api/optimizer/preview/'))).toBe(true);
    });

    it('"View forensic trail" action dispatches the ledger GET', async () => {
        _mountView();
        renderQueue([_qp({ proposal_id: 'qp-trail-click' })], 1);
        const spy = vi.fn(async () => ({
            ok: true, status: 200,
            json: async () => ({ entries: [], matched: 0, total: 0 }),
        }));
        vi.stubGlobal('fetch', spy);
        const btn = document.querySelector(
            '.opt-btn-trail[data-proposal-id="qp-trail-click"]',
        );
        expect(btn).not.toBeNull();
        onClick(_fakeClickEvent(btn));
        await Promise.resolve(); await Promise.resolve();
        const urls = spy.mock.calls.map((c) => c[0]);
        expect(urls.some((u) => u.startsWith('/api/ledger/entries?proposal_id='))).toBe(true);
    });
});
