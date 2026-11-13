/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO -- tests/frontend/ot_security.test.js
 * Release R2-A -- views/ot_security.js
 *
 *   - sortChecks: failing first (worst severity first), stable.
 *   - Severity is carried by a TEXT badge, never colour alone.
 *   - XSS: usernames, tag ids, error strings, check text (S-SEC-01).
 *   - Honest scope: the disclaimer is always rendered.
 *   - Fetch lifecycle: error postures, hidden view does not poll,
 *     one timer only.
 *   - S-VISUAL-01 fence: every ots-* class has a CSS rule.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { __ot_security_test__ as V, initOtSecurityView } from '/assets/js/views/ot_security.js';
import { isRegistered } from '/assets/js/core/router.js';

const ROOT = resolve(__dirname, '..', '..');
const HOSTILE = '<img src=x onerror=alert(1)>';

function check(id, status, severity, extra = {}) {
    return Object.assign({
        id, status, severity,
        title: `title ${id}`, detail: `detail ${id}`,
        reference: 'IEC 62443-3-3 SR 1.1 (x)',
        remediation: status === 'fail' ? `fix ${id}` : '',
    }, extra);
}

function payload(overrides = {}) {
    return Object.assign({
        schema: 'ot_security_posture_v1',
        generated_at: 1794600000,
        disclaimer: 'Self-reported posture. No network traffic is inspected.',
        summary: { failed: 3, passed: 1, info: 1, worst_severity: 'high',
            by_severity: { critical: 0, high: 1, medium: 1, low: 1 } },
        checks: [
            check('C-PASS', 'pass', null),
            check('C-LOW', 'fail', 'low'),
            check('C-INFO', 'info', null),
            check('C-HIGH', 'fail', 'high'),
            check('C-MED', 'fail', 'medium'),
        ],
        facts: {
            access: { gate_enabled: false, jwt_secret_from_env: false, user_store_ready: true,
                users: [
                    { username: 'manager', role: 'FACILITY_MANAGER', password_source: 'environment' },
                    { username: 'operator', role: 'L1_OPERATOR', password_source: 'repo_default' },
                ] },
            ledger: { available: true, verified: true, total_entries: 4, key_version: 0,
                hmac_key_from_env: false, persistence: 'memory' },
            bms: { available: true, total_tags: 62, writable_tags: 21,
                by_protocol: { BACnet: 55, Modbus: 7 }, writable_by_protocol: { BACnet: 21 },
                audit_total: 2, audit_accepted: 1, audit_denied: 1,
                audit_recent: [
                    { ts: 1794600000, tag_id: 'HVAC.CHWP1.STATUS', user: 'wilmer', success: true, error: '' },
                    { ts: 1794600060, tag_id: 'PWR.UPS_A.SOC', user: 'x', success: false, error: 'tag is not writable' },
                ] },
            edge: { available: true, channel_count: 4, batches_accepted: 7, envelopes_accepted: 28,
                envelopes_rejected: 0, last_ingest_ts: 1794600000, device_authenticated: false },
        },
    }, overrides);
}

function mount(hidden = false) {
    document.body.innerHTML = `<div class="view" id="view-ot-security"${hidden ? ' hidden' : ''}></div>`;
    return document.getElementById('view-ot-security');
}

afterEach(() => {
    V.reset();
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
    vi.useRealTimers();
});

describe('R2-A -- sortChecks', () => {
    it('orders fail (critical>high>medium>low), then info, then pass', () => {
        const ids = V.sortChecks(payload().checks).map((c) => c.id);
        expect(ids).toEqual(['C-HIGH', 'C-MED', 'C-LOW', 'C-INFO', 'C-PASS']);
    });

    it('is stable inside a group and does not mutate the input', () => {
        const input = [check('A', 'fail', 'medium'), check('B', 'fail', 'medium'), check('Z', 'fail', 'critical')];
        const copy = input.slice();
        expect(V.sortChecks(input).map((c) => c.id)).toEqual(['Z', 'A', 'B']);
        expect(input).toEqual(copy);
    });

    it('tolerates garbage', () => {
        expect(V.sortChecks(null)).toEqual([]);
        expect(V.sortChecks(undefined)).toEqual([]);
        const odd = V.sortChecks([check('U', 'fail', 'bogus'), check('H', 'fail', 'high')]);
        expect(odd.map((c) => c.id)).toEqual(['H', 'U']);
    });
});

describe('R2-A -- badges carry text, not only colour', () => {
    it.each([
        [check('x', 'fail', 'critical'), 'CRITICAL', 'ots-badge-critical'],
        [check('x', 'fail', 'high'), 'HIGH', 'ots-badge-high'],
        [check('x', 'fail', 'medium'), 'MEDIUM', 'ots-badge-medium'],
        [check('x', 'fail', 'low'), 'LOW', 'ots-badge-low'],
        [check('x', 'pass', null), 'PASS', 'ots-badge-pass'],
        [check('x', 'info', null), 'INFO', 'ots-badge-info'],
    ])('%#', (c, label, cls) => {
        const b = V.badgeFor(c);
        expect(b.label).toBe(label);
        expect(b.cls).toContain(cls);
    });

    it('an unknown severity on a failing check is never rendered as passing', () => {
        const b = V.badgeFor(check('x', 'fail', 'weird'));
        expect(b.label).toBe('MEDIUM');
    });
});

describe('R2-A -- renderPosture', () => {
    it('always prints the honest-scope disclaimer', () => {
        const html = V.renderPosture(payload());
        expect(html).toContain('class="ots-disclaimer"');
        expect(html).toContain('No network traffic is inspected.');
    });

    it('renders the summary tiles with their counts', () => {
        const root = mount();
        root.innerHTML = V.renderPosture(payload());
        const tile = (sev) => root.querySelector(`.ots-tile-${sev}`);
        expect(tile('high').dataset.count).toBe('1');
        expect(tile('critical').dataset.count).toBe('0');
        expect(tile('pass').querySelector('.ots-tile-val').textContent).toBe('1');
        expect(root.querySelector('.ots-summary').dataset.worst).toBe('high');
    });

    it('shows remediation only on failing checks', () => {
        const root = mount();
        root.innerHTML = V.renderPosture(payload());
        const li = (id) => root.querySelector(`[data-check-id="${id}"]`);
        expect(li('C-HIGH').querySelector('.ots-check-fix').textContent).toContain('fix C-HIGH');
        expect(li('C-PASS').querySelector('.ots-check-fix')).toBeNull();
        expect(li('C-INFO').querySelector('.ots-check-fix')).toBeNull();
        expect(li('C-HIGH').querySelector('.ots-check-ref').textContent).toContain('IEC 62443-3-3');
    });

    it('lists accounts with their password source as text', () => {
        const root = mount();
        root.innerHTML = V.renderAccess(payload().facts.access);
        const text = root.textContent;
        expect(text).toContain('REPO DEFAULT');
        expect(text).toContain('ENVIRONMENT');
        expect(text).toContain('OFF');
        expect(text).toContain('ephemeral');
    });

    it('marks a broken ledger chain as critical with the index', () => {
        const html = V.renderLedger({ available: true, verified: false, divergence_index: 7,
            total_entries: 9, key_version: 1, hmac_key_from_env: true, persistence: 'postgres' });
        expect(html).toContain('ots-badge-critical');
        expect(html).toContain('BROKEN AT 7');
        expect(html).toContain('PostgreSQL');
    });

    it('renders protocol totals and the audit rows', () => {
        const root = mount();
        root.innerHTML = V.renderBms(payload().facts.bms);
        const total = root.querySelector('.ots-total');
        expect(total.textContent.replace(/\s+/g, ' ')).toContain('Total 62 21');
        expect(root.textContent).toContain('DENIED');
        expect(root.textContent).toContain('tag is not writable');
        expect(root.textContent).toContain('2026-11-13T');
    });

    it('degrades section by section', () => {
        expect(V.renderAccess({ error: 'boom' })).toContain('unavailable');
        expect(V.renderLedger({ available: false })).toContain('not running');
        expect(V.renderBms(null)).toContain('not loaded');
        expect(V.renderEdge({ available: false })).toContain('not mounted');
        expect(V.renderChecks([])).toContain('No checks returned');
        expect(() => V.renderPosture({})).not.toThrow();
        expect(() => V.renderPosture(null)).not.toThrow();
    });

    it('formats timestamps and never-ingested state', () => {
        expect(V.formatTs(1794600000)).toBe('2026-11-13T20:00:00Z');
        expect(V.formatTs(null)).toBe('never');
        expect(V.formatTs(NaN)).toBe('never');
    });
});

describe('R2-A -- XSS gate (S-SEC-01)', () => {
    it('escapes hostile text in every operator- or device-supplied field', () => {
        const p = payload({ disclaimer: HOSTILE });
        p.checks = [check(HOSTILE, 'fail', 'high', {
            title: HOSTILE, detail: HOSTILE, remediation: HOSTILE, reference: HOSTILE })];
        p.facts.access.users = [{ username: HOSTILE, role: HOSTILE, password_source: 'repo_default' }];
        p.facts.bms.by_protocol = { [HOSTILE]: 1 };
        p.facts.bms.audit_recent = [{ ts: 1, tag_id: HOSTILE, user: HOSTILE, success: false, error: HOSTILE }];
        p.facts.ledger.divergence_index = HOSTILE;
        p.facts.ledger.verified = false;
        const root = mount();
        root.innerHTML = V.renderPosture(p);
        // No element was created from the hostile text, and no event
        // handler attribute exists anywhere. (innerHTML is not asserted:
        // the serializer legitimately prints "<" inside an attribute
        // value such as data-check-id, which is inert.)
        expect(root.querySelector('img')).toBeNull();
        expect(root.querySelector('[onerror]')).toBeNull();
        expect(root.querySelector('[data-check-id]').dataset.checkId).toBe(HOSTILE);
        expect(root.textContent).toContain('<img src=x onerror=alert(1)>');
    });

    it('a quote in a check id cannot break out of the attribute', () => {
        const root = mount();
        root.innerHTML = V.renderCheck(check('x" onmouseover="alert(1)', 'fail', 'high'));
        const li = root.querySelector('li');
        expect(li.hasAttribute('onmouseover')).toBe(false);
        expect(li.dataset.checkId).toBe('x" onmouseover="alert(1)');
    });
});

describe('R2-A -- fetch lifecycle', () => {
    it('registers the ot-security route once', () => {
        initOtSecurityView();
        initOtSecurityView();
        expect(isRegistered('ot-security')).toBe(true);
    });

    it('renders the payload into the view', async () => {
        const root = mount();
        vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => payload() })));
        await V.refresh();
        expect(root.querySelector('h2').textContent).toContain('OT Security');
        expect(root.querySelectorAll('.ots-check').length).toBe(5);
    });

    it.each([
        [async () => ({ ok: false, status: 401, json: async () => ({}) }), 'HTTP 401'],
        [async () => { throw new Error('offline'); }, 'unreachable'],
        [async () => ({ ok: true, status: 200, json: async () => { throw new Error('bad'); } }), 'could not be parsed'],
    ])('shows an explicit error posture %#', async (impl, text) => {
        const root = mount();
        vi.stubGlobal('fetch', vi.fn(impl));
        await V.refresh();
        expect(root.querySelector('.ots-error').textContent).toContain(text);
    });

    it('does not call the API while the view is hidden', async () => {
        mount(true);
        const spy = vi.fn(async () => ({ ok: true, status: 200, json: async () => payload() }));
        vi.stubGlobal('fetch', spy);
        await V.refresh();
        expect(spy).not.toHaveBeenCalled();
    });

    it('runs a single timer and stops cleanly', async () => {
        mount();
        vi.useFakeTimers();
        const spy = vi.fn(async () => ({ ok: true, status: 200, json: async () => payload() }));
        vi.stubGlobal('fetch', spy);
        V.startPolling();
        V.startPolling();
        expect(V.isPolling()).toBe(true);
        await vi.advanceTimersByTimeAsync(V.POLL_MS);
        expect(spy).toHaveBeenCalledTimes(2);
        V.stopPolling();
        expect(V.isPolling()).toBe(false);
        await vi.advanceTimersByTimeAsync(V.POLL_MS * 3);
        expect(spy).toHaveBeenCalledTimes(2);
    });
});

describe('R2-A -- S-VISUAL-01 fence + wiring', () => {
    it('every ots-* class the view emits has a CSS rule', () => {
        const css = readFileSync(resolve(ROOT, 'frontend/assets/app.css'), 'utf8');
        const defined = new Set([...css.matchAll(/\.([A-Za-z_][\w-]*)/g)].map((m) => m[1]));
        const src = readFileSync(resolve(ROOT, 'frontend/assets/js/views/ot_security.js'), 'utf8');
        const emitted = new Set();
        for (const m of src.matchAll(/class(?:Name)?\s*=\s*["']([^"'<>{}]+)["']/g)) {
            for (const t of m[1].split(/\s+/)) if (/^ots-[\w-]+$/.test(t) && !t.endsWith('-')) emitted.add(t);
        }
        for (const m of src.matchAll(/ots-badge-(critical|high|medium|low|pass|info)/g)) emitted.add(m[0]);
        for (const sev of ['critical', 'high', 'medium', 'low', 'pass']) emitted.add(`ots-tile-${sev}`);
        for (const st of ['fail', 'pass']) emitted.add(`ots-check-${st}`);
        expect(emitted.size).toBeGreaterThanOrEqual(30);
        const unstyled = [...emitted].filter((c) => !defined.has(c)).sort();
        expect(unstyled).toEqual([]);
    });

    it('index.html mounts the view container and main.js initialises it', () => {
        const html = readFileSync(resolve(ROOT, 'frontend/index.html'), 'utf8');
        expect(html).toContain('<div class="view" id="view-ot-security" hidden></div>');
        expect(html).toContain('data-route="ot-security"');
        const main = readFileSync(resolve(ROOT, 'frontend/assets/js/main.js'), 'utf8');
        expect(main).toContain('initOtSecurityView();');
    });
});
