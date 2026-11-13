/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO -- tests/frontend/release_r1.test.js
 * Release R1 (public full-app deployment) frontend invariants:
 *
 *   - core/auth_gate.js: inert until armed; armed + no JWT blocks
 *     navigation and asks for the login view; a valid JWT or the
 *     hackathon demo mode lets navigation through.
 *   - core/router.js honours the gate (the "/#route" bypass).
 *   - views/overview.js: the simulator-backed KPI source is
 *     labelled and polled; the DB-backed source is neither.
 *   - views/maintenance.js: the IN-MEMORY storage badge follows
 *     /api/cmms/health.
 *   - S-VISUAL-01 regression fence: every class the Optimizer and
 *     Procedure Architect views emit has a rule in app.css (both
 *     views shipped with zero rules before R1).
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import {
    armAuthGate, navigationBlocked, requestLogin, __auth_gate_test__,
} from '/assets/js/core/auth_gate.js';
import * as auth from '/assets/js/core/auth.js';
import { setDemoState } from '/assets/js/core/demo.js';
import { registerRoute, navigateTo } from '/assets/js/core/router.js';
import { __bootstrap_test__ } from '/assets/js/core/bootstrap.js';
import { __overview_test__ } from '/assets/js/views/overview.js';
import { __maintenance_test__ } from '/assets/js/views/maintenance.js';
import { __procedures_view_test__ } from '/assets/js/views/procedures.js';

const ROOT = resolve(__dirname, '..', '..');

function fakeJWT(claims) {
    const enc = (o) => btoa(JSON.stringify(o))
        .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    return `${enc({ alg: 'HS256', typ: 'JWT' })}.${enc(claims)}.sig`;
}

function validToken() {
    const exp = Math.floor(Date.now() / 1000) + 3600;
    return fakeJWT({ sub: 'u-1', username: 'alice', role: 'L1_OPERATOR', iat: exp - 3600, exp, jti: 'r1' });
}

function jsonResponse(body, { ok = true, status = 200 } = {}) {
    return { ok, status, json: async () => body };
}

beforeEach(() => {
    __auth_gate_test__.reset();
    auth.clearToken();
    setDemoState({ active: false, allowed: [], defaultView: 'overview' });
});

afterEach(() => {
    __auth_gate_test__.reset();
    auth.clearToken();
    setDemoState({ active: false, allowed: [], defaultView: 'overview' });
    __overview_test__.reset();
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
    vi.useRealTimers();
});

describe('R1 -- core/auth_gate.js', () => {
    it('is inert until armed (module-level callers keep today\'s behaviour)', () => {
        expect(auth.hasValidToken()).toBe(false);
        expect(navigationBlocked()).toBe(false);
    });

    it('armed + no session blocks navigation', () => {
        armAuthGate();
        expect(navigationBlocked()).toBe(true);
    });

    it('armed + valid JWT lets navigation through', () => {
        armAuthGate();
        auth.setToken(validToken());
        expect(navigationBlocked()).toBe(false);
    });

    it('armed + expired JWT blocks navigation', () => {
        armAuthGate();
        const past = Math.floor(Date.now() / 1000) - 10;
        auth.setToken(fakeJWT({ sub: 'u-1', username: 'a', role: 'L1_OPERATOR', iat: past - 3600, exp: past, jti: 'x' }));
        expect(navigationBlocked()).toBe(true);
    });

    it('hackathon demo mode keeps its views public', () => {
        armAuthGate();
        setDemoState({ active: true, allowed: ['mop-verify'], defaultView: 'mop-verify' });
        expect(navigationBlocked()).toBe(false);
    });

    it('requestLogin dispatches dc-epms-auth-required', () => {
        const spy = vi.fn();
        window.addEventListener('dc-epms-auth-required', spy);
        requestLogin();
        expect(spy).toHaveBeenCalledTimes(1);
        window.removeEventListener('dc-epms-auth-required', spy);
    });
});

describe('R1 -- core/router.js honours the auth gate', () => {
    function mount() {
        document.body.innerHTML = `
            <div class="nav-item" data-route="r1-probe"></div>
            <div class="view" id="view-login"></div>
            <div class="view" id="view-r1-probe" hidden></div>`;
    }

    it('without a session the target view stays hidden and login is requested', () => {
        mount();
        const activate = vi.fn();
        registerRoute('r1-probe', { viewId: 'view-r1-probe', activate });
        armAuthGate();
        const spy = vi.fn();
        window.addEventListener('dc-epms-auth-required', spy);

        expect(navigateTo('r1-probe')).toBe(true);

        expect(document.getElementById('view-r1-probe').hasAttribute('hidden')).toBe(true);
        expect(activate).not.toHaveBeenCalled();
        expect(spy).toHaveBeenCalledTimes(1);
        window.removeEventListener('dc-epms-auth-required', spy);
    });

    it('with a session the view is revealed and activated', () => {
        mount();
        const activate = vi.fn();
        registerRoute('r1-probe', { viewId: 'view-r1-probe', activate });
        armAuthGate();
        auth.setToken(validToken());

        expect(navigateTo('r1-probe')).toBe(true);

        expect(document.getElementById('view-r1-probe').hasAttribute('hidden')).toBe(false);
        expect(activate).toHaveBeenCalledTimes(1);
    });

    it('un-armed gate never blocks (direct module use)', () => {
        mount();
        registerRoute('r1-probe', { viewId: 'view-r1-probe', activate: vi.fn() });
        expect(navigateTo('r1-probe')).toBe(true);
        expect(document.getElementById('view-r1-probe').hasAttribute('hidden')).toBe(false);
    });
});

describe('R1 -- core/bootstrap.js navigateToCurrentRoute (post-login landing)', () => {
    function mount() {
        document.body.innerHTML = `
            <div class="nav-item" data-route="overview"></div>
            <div class="nav-item" data-route="r1-landing"></div>
            <div class="view" id="view-overview" hidden></div>
            <div class="view" id="view-r1-landing" hidden></div>`;
        registerRoute('overview', { viewId: 'view-overview', activate: vi.fn() });
        registerRoute('r1-landing', { viewId: 'view-r1-landing', activate: vi.fn() });
        window.__epmsRouter = { isRegistered: (r) => ['overview', 'r1-landing'].includes(r), navigateTo };
    }

    it('lands on overview when the URL carries no hash', () => {
        mount();
        window.location.hash = '';
        __bootstrap_test__.navigateToCurrentRoute();
        expect(document.getElementById('view-overview').hasAttribute('hidden')).toBe(false);
        expect(document.getElementById('view-r1-landing').hasAttribute('hidden')).toBe(true);
    });

    it('lands on the hash route when one is present', () => {
        mount();
        window.location.hash = '#r1-landing';
        __bootstrap_test__.navigateToCurrentRoute();
        expect(document.getElementById('view-r1-landing').hasAttribute('hidden')).toBe(false);
        expect(document.getElementById('view-overview').hasAttribute('hidden')).toBe(true);
        window.location.hash = '';
    });
});

describe('R1 -- views/overview.js simulator-backed KPI cards', () => {
    function mountKpis() {
        document.body.innerHTML = `
            <div id="kpi-pue"></div><div id="kpi-temp"></div>
            <div id="kpi-load"></div><div id="kpi-racks"></div>
            <div id="kpi-source-note" hidden></div>`;
    }
    const simRow = {
        ts: '2026-11-13T20:00:00+00:00', pue: 1.313, hall_temp_c: 22.03,
        it_load_kw: 16756, rack_count: 118, rack_tdp_kw: 142,
    };

    it('paints the cards and shows the source note for "simulator"', async () => {
        mountKpis();
        vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ latest: simRow, source: 'simulator' })));
        const source = await __overview_test__.refreshLatestKpi();
        expect(source).toBe('simulator');
        expect(document.getElementById('kpi-temp').textContent).toBe('22.0°C');
        expect(document.getElementById('kpi-temp').className).toContain('ok');
        expect(document.getElementById('kpi-racks').textContent).toBe('118 × 142kW');
        expect(document.getElementById('kpi-source-note').hidden).toBe(false);
    });

    it('keeps the note hidden for the "timescaledb" source', async () => {
        mountKpis();
        vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ latest: simRow, source: 'timescaledb' })));
        expect(await __overview_test__.refreshLatestKpi()).toBe('timescaledb');
        expect(document.getElementById('kpi-source-note').hidden).toBe(true);
    });

    it('returns "" and leaves the cards alone when there is no row', async () => {
        mountKpis();
        vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ latest: null, error: 'DB unavailable' })));
        expect(await __overview_test__.refreshLatestKpi()).toBe('');
        expect(document.getElementById('kpi-temp').textContent).toBe('');
        expect(document.getElementById('kpi-source-note').hidden).toBe(true);
    });

    it('survives a network failure', async () => {
        mountKpis();
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
        expect(await __overview_test__.refreshLatestKpi()).toBe('');
    });

    it('polls only the simulator source, and only one timer', async () => {
        mountKpis();
        vi.useFakeTimers();
        const fetchSpy = vi.fn(async (url) => (url === '/api/telemetry/latest'
            ? jsonResponse({ latest: simRow, source: 'simulator' })
            : jsonResponse({}, { ok: false, status: 503 })));
        vi.stubGlobal('fetch', fetchSpy);
        const latestCalls = () => fetchSpy.mock.calls.filter((c) => c[0] === '/api/telemetry/latest').length;

        await __overview_test__.loadHistoricalTelemetry();
        await __overview_test__.loadHistoricalTelemetry();
        expect(__overview_test__.kpiPollStarted()).toBe(true);
        expect(latestCalls()).toBe(2);

        await vi.advanceTimersByTimeAsync(15000);
        expect(latestCalls()).toBe(3);
    });

    it('does not poll the DB-backed source', async () => {
        mountKpis();
        vi.useFakeTimers();
        const fetchSpy = vi.fn(async (url) => (url === '/api/telemetry/latest'
            ? jsonResponse({ latest: simRow, source: 'timescaledb' })
            : jsonResponse({}, { ok: false, status: 503 })));
        vi.stubGlobal('fetch', fetchSpy);
        await __overview_test__.loadHistoricalTelemetry();
        expect(__overview_test__.kpiPollStarted()).toBe(false);
        await vi.advanceTimersByTimeAsync(60000);
        expect(fetchSpy.mock.calls.filter((c) => c[0] === '/api/telemetry/latest').length).toBe(1);
    });
});

describe('R1 -- views/maintenance.js storage badge', () => {
    function mount() {
        document.body.innerHTML = `
            <div id="view-maintenance">
                <span data-field="cmms-backend" hidden></span>
            </div>`;
        return document.querySelector('[data-field="cmms-backend"]');
    }

    it('shows the badge when the CMMS runs in memory', async () => {
        const badge = mount();
        vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ status: 'up', backend: 'memory' })));
        await __maintenance_test__.refreshStorageBadge();
        expect(badge.hidden).toBe(false);
    });

    it('hides the badge on PostgreSQL', async () => {
        const badge = mount();
        badge.hidden = false;
        vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ status: 'up', backend: 'postgres' })));
        await __maintenance_test__.refreshStorageBadge();
        expect(badge.hidden).toBe(true);
    });

    it('keeps the previous state when the probe fails', async () => {
        const badge = mount();
        badge.hidden = false;
        vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({}, { ok: false, status: 503 })));
        await __maintenance_test__.refreshStorageBadge();
        expect(badge.hidden).toBe(false);
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
        await __maintenance_test__.refreshStorageBadge();
        expect(badge.hidden).toBe(false);
    });
});

describe('R1 -- views/procedures.js markdown bullets', () => {
    const render = __procedures_view_test__.renderMarkdown || __procedures_view_test__._renderMarkdown;

    it("renders '* ' lines as list items, like '- ' lines", () => {
        const html = render('* **Tag:** UPS-B\n* Estado final: _TBD_\n\n- dash item');
        expect(html).toContain('<ul class="proc-list">');
        expect(html).toContain('<li><strong>Tag:</strong> UPS-B</li>');
        expect(html).toContain('<li>Estado final: _TBD_</li>');
        expect(html).toContain('<li>dash item</li>');
        expect(html).not.toMatch(/<p[^>]*>\* /);
    });

    it('still escapes hostile markup inside a bullet (S-SEC-01)', () => {
        const html = render('* <img src=x onerror=alert(1)>');
        expect(html).not.toContain('<img');
        expect(html).toContain('&lt;img');
    });
});

describe('R1 -- S-VISUAL-01 fence: emitted classes have CSS rules', () => {
    const css = readFileSync(resolve(ROOT, 'frontend/assets/app.css'), 'utf8');
    const defined = new Set([...css.matchAll(/\.([A-Za-z_][\w-]*)/g)].map((m) => m[1]));

    function emittedClasses(file, prefix) {
        const src = readFileSync(resolve(ROOT, file), 'utf8');
        const out = new Set();
        for (const m of src.matchAll(/class(?:Name)?\s*=\s*["']([^"'<>{}]+)["']/g)) {
            for (const token of m[1].split(/\s+/)) {
                if (/^[A-Za-z_][\w-]*$/.test(token) && token.startsWith(prefix)) out.add(token);
            }
        }
        // Classes assembled in JS (verdict / state suffixes).
        for (const m of src.matchAll(/'((?:opt|proc)-[a-z0-9_-]+)'/g)) {
            if (m[1].startsWith(prefix) && !m[1].endsWith('-')) out.add(m[1]);
        }
        return [...out].sort();
    }

    // Emitted purely as JS hooks / state markers with no visual of
    // their own; listed explicitly so a NEW unstyled class still fails.
    const HOOK_ONLY = new Set([
        'opt-hb-tick', 'opt-hb-drift', 'opt-hb-proposed', 'opt-hb-paced', 'opt-hb-qsize',
        'opt-btn-preview', 'opt-btn-trail', 'opt-btn-refresh',
        'opt-form-approve', 'opt-form-reject', 'opt-narrative-optimizer',
        'opt-narrative-consensus', 'opt-hist-other', 'opt-history-body',
        'opt-vote-row', 'opt-hist-op', 'opt-hist-role',
        'proc-result', 'proc-pill-unknown', 'proc-sign-result',
    ]);

    it.each([
        ['frontend/assets/js/views/optimizer.js', 'opt-', 100],
        ['frontend/assets/js/views/procedures.js', 'proc-', 40],
    ])('%s: every %s* class is styled', (file, prefix, minimum) => {
        const emitted = emittedClasses(file, prefix);
        expect(emitted.length).toBeGreaterThanOrEqual(minimum);
        const unstyled = emitted.filter((c) => !defined.has(c) && !HOOK_ONLY.has(c));
        expect(unstyled).toEqual([]);
    });

    it('the Safety Officer veto badge is filled, not outlined (S-DET-02)', () => {
        const rule = css.match(/\.opt-vote-badge-veto\s*\{([^}]*)\}/);
        expect(rule).not.toBeNull();
        expect(rule[1]).toMatch(/background:\s*var\(--crit\)/);
    });

    it('login form carries no inline browser-default styling', () => {
        const html = readFileSync(resolve(ROOT, 'frontend/index.html'), 'utf8');
        const form = html.match(/<div data-login-form[^>]*>/);
        expect(form).not.toBeNull();
        expect(form[0]).toContain('class="login-form"');
        expect(form[0]).not.toContain('style=');
        expect(html).toMatch(/id="login-password" type="password" autocomplete="current-password">/);
    });

    it('the remaining stub views are tagged planned in the nav', () => {
        const html = readFileSync(resolve(ROOT, 'frontend/index.html'), 'utf8');
        // R2-A replaced the morpheus stub with the OT Security view.
        expect(html).not.toContain('data-route="morpheus"');
        expect(html).toMatch(/<div class="nav-item" data-route="ot-security">.*?OT Security<\/div>/s);
        for (const route of ['gemini', 'omniverse']) {
            const item = html.match(new RegExp(`<div class="nav-item" data-route="${route}">.*?</div>`, 's'));
            expect(item, route).not.toBeNull();
            expect(item[0]).toContain('nav-item-tag-planned');
        }
    });
});
