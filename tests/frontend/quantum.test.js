/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/quantum.test.js
 * Epic 9 — BB84 educational QKD telemetry HMI.
 *
 * Verifies the per-view minima (S-TEST-02):
 *   - render smoke (badge, pool stats, audit table)
 *   - XSS-escaping assertion on every API-derived string field
 *   - route registration via isRegistered('quantum')
 *
 * Plus Epic 9-specific:
 *   - Fingerprint display truncates to 8 chars + ellipsis (S-SEC-01
 *     defence-in-depth even though the server-issued value is only
 *     16 hex chars).
 *   - QBER badge state machine: <threshold = green, >=threshold = red
 *     with "signing blocked" copy, missing = unknown.
 *   - Poll lifecycle: startPolling -> setInterval; stopPolling -> 0.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { __quantum_view_test__ } from '/assets/js/views/quantum.js';
import { isRegistered } from '/assets/js/core/router.js';

const {
    formatFingerprint,
    renderHeader,
    renderQberBadge,
    renderPoolStats,
    renderAuditTable,
    fetchStatus,
    applyStatus,
    startPolling,
    stopPolling,
    initQuantumView,
    reset,
} = __quantum_view_test__;

function fakeResponse(body, { ok = true } = {}) {
    return {
        ok,
        status: ok ? 200 : 500,
        json: async () => body,
        text: async () => JSON.stringify(body),
    };
}

function mountView() {
    document.body.innerHTML = `
        <div id="view-quantum">
            <div data-qkd-framing></div>
            <span data-qkd-qber-badge data-state="unknown">QBER: —</span>
            <div data-qkd-pool></div>
            <table><tbody data-qkd-audit></tbody></table>
        </div>`;
}

function sampleStatus({ qber = 0.0, depth = 8, last = 'accepted',
    audit = [], eve = false } = {}) {
    return {
        framing: 'Educational BB84 simulator.',
        pool_depth: depth,
        pool_capacity: 32,
        keys_accepted_total: 12,
        keys_rejected_total: 3,
        last_qber: qber,
        last_decision: last,
        qber_threshold: 0.11,
        eavesdrop_simulated: eve,
        audit_log_size: audit.length,
        recent_audit: audit,
    };
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

// ─── Pure helpers ───────────────────────────────────────────────────
describe('Epic 9 — formatFingerprint', () => {
    it('truncates to first 8 chars + ellipsis', () => {
        expect(formatFingerprint('deadbeefcafebabe'))
            .toBe('deadbeef…');
    });

    it('returns em-dash for empty / non-string input', () => {
        expect(formatFingerprint('')).toBe('—');
        expect(formatFingerprint(null)).toBe('—');
        expect(formatFingerprint(undefined)).toBe('—');
        expect(formatFingerprint(42)).toBe('—');
    });
});

// ─── QBER badge ─────────────────────────────────────────────────────
describe('Epic 9 — renderQberBadge state machine', () => {
    it('renders unknown when status is null', () => {
        mountView();
        renderQberBadge(null);
        const el = document.querySelector('[data-qkd-qber-badge]');
        expect(el.dataset.state).toBe('unknown');
        expect(el.textContent).toContain('QBER: —');
    });

    it('renders green when qber below threshold', () => {
        mountView();
        renderQberBadge(sampleStatus({ qber: 0.03 }));
        const el = document.querySelector('[data-qkd-qber-badge]');
        expect(el.dataset.state).toBe('green');
        expect(el.textContent).toContain('pool healthy');
    });

    it('renders red and signals signing blocked above threshold', () => {
        mountView();
        renderQberBadge(sampleStatus({ qber: 0.25 }));
        const el = document.querySelector('[data-qkd-qber-badge]');
        expect(el.dataset.state).toBe('red');
        expect(el.textContent).toContain('signing blocked');
    });

    it('renders unknown when last_qber is null (no batches yet)', () => {
        mountView();
        renderQberBadge(sampleStatus({ qber: null }));
        const el = document.querySelector('[data-qkd-qber-badge]');
        expect(el.dataset.state).toBe('unknown');
        expect(el.textContent).toContain('no batches yet');
    });
});

// ─── Pool stats render ──────────────────────────────────────────────
describe('Epic 9 — renderPoolStats', () => {
    it('shows depth / capacity, totals, and eavesdrop flag', () => {
        mountView();
        renderPoolStats(sampleStatus({ depth: 8, eve: true }));
        const html = document.querySelector('[data-qkd-pool]').innerHTML;
        expect(html).toContain('8 / 32');
        expect(html).toContain('Keys accepted (total)');
        expect(html).toContain('YES (audit drill)');
    });

    it('renders dash when status is null', () => {
        mountView();
        renderPoolStats(null);
        const el = document.querySelector('[data-qkd-pool]');
        expect(el.textContent).toContain('Pool: —');
    });
});

// ─── Audit table render + XSS gate ──────────────────────────────────
describe('Epic 9 — renderAuditTable XSS gate (S-SEC-01)', () => {
    it('empty state when no records', () => {
        mountView();
        renderAuditTable([]);
        const html = document.querySelector('[data-qkd-audit]').innerHTML;
        expect(html).toContain('No audit records yet');
    });

    it('escapes <img onerror> XSS in reason field', () => {
        mountView();
        renderAuditTable([{
            ts: '2026-05-27T12:00:00+00:00',
            decision: 'rejected',
            qber: 0.25,
            threshold: 0.11,
            fingerprint: 'deadbeefcafebabe',
            reason: '<img src=x onerror=alert(1)>',
        }]);
        const tbody = document.querySelector('[data-qkd-audit]');
        const html = tbody.innerHTML;
        // No raw <img> survived as an actual DOM element. After
        // escaping, the literal text "onerror" survives inside the
        // td as harmless text -- the live attribute does not.
        expect(html).not.toContain('<img');
        expect(tbody.querySelectorAll('img').length).toBe(0);
        // Escaped form present.
        expect(html).toContain('&lt;img');
        // Decision + fingerprint truncation rendered.
        expect(html).toContain('rejected');
        expect(html).toContain('deadbeef…');
    });

    it('escapes <script> in fingerprint (defence in depth)', () => {
        mountView();
        renderAuditTable([{
            ts: '2026-05-27T12:00:00+00:00',
            decision: 'accepted',
            qber: 0.0,
            threshold: 0.11,
            // Server-issued value is always 16 hex chars; this models
            // an adversarial cache poison / proxy injection.
            fingerprint: '<script>alert(1)</script>',
            reason: '',
        }]);
        const html = document.querySelector('[data-qkd-audit]').innerHTML;
        expect(html).not.toContain('<script>');
        expect(html).toContain('&lt;script&gt;');
    });

    it('caps audit table at the render limit', () => {
        mountView();
        const many = [];
        for (let i = 0; i < 30; i++) {
            many.push({
                ts: '2026-05-27T12:00:00+00:00',
                decision: 'accepted',
                qber: 0.0,
                threshold: 0.11,
                fingerprint: ('a' + i).padEnd(16, 'b'),
                reason: '',
            });
        }
        renderAuditTable(many);
        const rows = document.querySelectorAll('[data-qkd-audit] tr.qkd-audit-row');
        // Render limit hard-coded to 12.
        expect(rows.length).toBe(12);
    });
});

// ─── Header framing render ──────────────────────────────────────────
describe('Epic 9 — renderHeader framing', () => {
    it('escapes the framing string', () => {
        mountView();
        renderHeader('<script>boom</script>Educational sim.');
        const el = document.querySelector('[data-qkd-framing]');
        expect(el.innerHTML).not.toContain('<script>');
        expect(el.innerHTML).toContain('&lt;script&gt;');
    });

    it('falls back to default text when framing is missing', () => {
        mountView();
        renderHeader(null);
        const el = document.querySelector('[data-qkd-framing]');
        expect(el.textContent).toContain('Educational BB84 simulator.');
    });
});

// ─── Fetch ──────────────────────────────────────────────────────────
describe('Epic 9 — fetchStatus', () => {
    it('hits /api/qkd/status with audit_limit param', async () => {
        const spy = vi.fn(async () =>
            fakeResponse(sampleStatus()));
        vi.stubGlobal('fetch', spy);
        const data = await fetchStatus();
        expect(spy).toHaveBeenCalledWith('/api/qkd/status?audit_limit=16');
        expect(data.pool_depth).toBe(8);
    });

    it('returns null on network failure', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => {
            throw new Error('network unreachable');
        }));
        const data = await fetchStatus();
        expect(data).toBeNull();
    });

    it('returns null on non-2xx', async () => {
        vi.stubGlobal('fetch', vi.fn(async () =>
            fakeResponse({}, { ok: false })));
        const data = await fetchStatus();
        expect(data).toBeNull();
    });
});

// ─── Apply pipeline ─────────────────────────────────────────────────
describe('Epic 9 — applyStatus end-to-end', () => {
    it('renders badge + pool + audit from one payload', () => {
        mountView();
        applyStatus(sampleStatus({
            qber: 0.20,
            audit: [{
                ts: '2026-05-27T12:00:00+00:00',
                decision: 'rejected',
                qber: 0.20,
                threshold: 0.11,
                fingerprint: 'badf00ddeadbeef0',
                reason: 'QBER 0.2000 >= threshold 0.1100',
            }],
        }));
        const badge = document.querySelector('[data-qkd-qber-badge]');
        expect(badge.dataset.state).toBe('red');
        const pool = document.querySelector('[data-qkd-pool]').innerHTML;
        expect(pool).toContain('Pool depth');
        const audit = document.querySelector('[data-qkd-audit]').innerHTML;
        expect(audit).toContain('rejected');
        expect(audit).toContain('badf00dd…');
    });
});

// ─── Poll lifecycle ─────────────────────────────────────────────────
describe('Epic 9 — polling lifecycle', () => {
    it('startPolling installs an interval; stopPolling clears it', () => {
        vi.useFakeTimers();
        try {
            vi.stubGlobal('fetch', vi.fn(async () =>
                fakeResponse(sampleStatus())));
            mountView();
            startPolling();
            // Initial fetch + one tick later.
            vi.advanceTimersByTime(6000);
            stopPolling();
            // After stop, advancing more should not produce extra calls.
            const callsAtStop = global.fetch.mock.calls.length;
            vi.advanceTimersByTime(20000);
            expect(global.fetch.mock.calls.length).toBe(callsAtStop);
        } finally {
            vi.useRealTimers();
        }
    });
});

// ─── Route registration (S-ROUTE-01) ────────────────────────────────
describe('Epic 9 — route registration', () => {
    it('initQuantumView registers the "quantum" route', () => {
        initQuantumView();
        expect(isRegistered('quantum')).toBe(true);
    });

    it('initQuantumView is idempotent (S-ROUTE-02)', () => {
        initQuantumView();
        initQuantumView();
        // No crash; route still registered.
        expect(isRegistered('quantum')).toBe(true);
    });
});
