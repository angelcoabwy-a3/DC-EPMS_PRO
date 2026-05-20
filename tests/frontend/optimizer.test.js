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
    submitApprove, submitReject, fetchQueue, onHermesProposal,
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
