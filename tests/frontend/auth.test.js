/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO -- tests/frontend/auth.test.js
 * Epic 10 -- core/auth.js + core/api_client.js + views/login.js
 * invariants.
 *
 * Verifies the per-view minima (S-TEST-02):
 *   - Login renders + XSS-escapes error / banner content.
 *   - Auth state machine: setToken / clearToken / hasValidToken,
 *     decodeClaims survives malformed input.
 *   - api_client.authFetch injects Bearer token; 401 response
 *     clears the token + dispatches dc-epms-auth-required.
 *
 * Plus Epic 10 specifics:
 *   - login() POST shape + success/failure handling.
 *   - Login submit dispatches dc-epms-auth-granted on success.
 * ════════════════════════════════════════════════════════════════ */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { __auth_test__ } from '/assets/js/core/auth.js';
import { __api_client_test__ } from '/assets/js/core/api_client.js';
import { __login_view_test__ } from '/assets/js/views/login.js';

const auth = __auth_test__;
const api = __api_client_test__;
const loginView = __login_view_test__;

function fakeResponse(body, { ok = true, status = ok ? 200 : 500 } = {}) {
    return {
        ok,
        status,
        json: async () => body,
        text: async () => JSON.stringify(body),
    };
}

// Build a fake unsigned JWT (header.payload.signature) with the
// given payload. The client never verifies signatures, so this is
// good enough for the decodeClaims test surface.
function fakeJWT(payload) {
    const b64url = (s) => btoa(s)
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=+$/, '');
    const head = b64url(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
    const body = b64url(JSON.stringify(payload));
    return head + '.' + body + '.fake-signature';
}

beforeEach(() => {
    auth.reset();
    document.body.innerHTML = '';
});

afterEach(() => {
    auth.reset();
    loginView.reset();
    document.body.innerHTML = '';
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
});

// ─── core/auth.js ────────────────────────────────────────────────
describe('Epic 10 -- core/auth.js token state', () => {
    it('hasValidToken false when empty', () => {
        expect(auth.hasValidToken()).toBe(false);
        expect(auth.getClaims()).toBeNull();
    });

    it('decodeClaims handles malformed token', () => {
        expect(auth.decodeClaims('garbage')).toBeNull();
        expect(auth.decodeClaims('a.b')).toBeNull();
        expect(auth.decodeClaims('a.b.c')).toBeNull();
        expect(auth.decodeClaims(null)).toBeNull();
    });

    it('setToken + getClaims round-trip', () => {
        const future = Math.floor(Date.now() / 1000) + 3600;
        const tok = fakeJWT({
            sub: 'u-1', username: 'alice', role: 'SAFETY_OFFICER',
            iat: future - 3600, exp: future, jti: 'x',
        });
        auth.setToken(tok);
        expect(auth.hasValidToken()).toBe(true);
        const claims = auth.getClaims();
        expect(claims.sub).toBe('u-1');
        expect(claims.role).toBe('SAFETY_OFFICER');
    });

    it('expired token is not valid', () => {
        const past = Math.floor(Date.now() / 1000) - 100;
        const tok = fakeJWT({
            sub: 'u-1', username: 'a', role: 'L1_OPERATOR',
            iat: past - 3600, exp: past, jti: 'x',
        });
        auth.setToken(tok);
        expect(auth.hasValidToken()).toBe(false);
    });

    it('clearToken removes the stored value', () => {
        auth.setToken('any');
        auth.clearToken();
        expect(auth.getToken()).toBeNull();
    });

    it('getAuthHeader returns Bearer when token set', () => {
        auth.setToken('abc');
        const h = auth.getAuthHeader();
        expect(h.Authorization).toBe('Bearer abc');
    });

    it('getAuthHeader is empty object when no token', () => {
        expect(auth.getAuthHeader()).toEqual({});
    });
});

// ─── core/auth.js login() ────────────────────────────────────────
describe('Epic 10 -- core/auth.js login()', () => {
    it('rejects empty credentials without a network call', async () => {
        const spy = vi.fn();
        vi.stubGlobal('fetch', spy);
        const r = await auth.login('', '');
        expect(r.ok).toBe(false);
        expect(spy).not.toHaveBeenCalled();
    });

    it('stores token on 200 success', async () => {
        const future = Math.floor(Date.now() / 1000) + 3600;
        const tok = fakeJWT({
            sub: 'u-1', username: 'alice', role: 'SAFETY_OFFICER',
            iat: future - 3600, exp: future, jti: 'x',
        });
        vi.stubGlobal('fetch', vi.fn(async () => fakeResponse({
            access_token: tok, token_type: 'bearer', expires_in: 3600,
            user_id: 'u-1', username: 'alice', role: 'SAFETY_OFFICER',
        })));
        const r = await auth.login('alice', 'pw');
        expect(r.ok).toBe(true);
        expect(auth.hasValidToken()).toBe(true);
    });

    it('returns error on 401 without storing a token', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => fakeResponse(
            { detail: 'invalid credentials' }, { ok: false, status: 401 },
        )));
        const r = await auth.login('alice', 'wrong');
        expect(r.ok).toBe(false);
        expect(r.status).toBe(401);
        expect(r.error).toBe('invalid credentials');
        expect(auth.getToken()).toBeNull();
    });
});

// ─── core/api_client.js ──────────────────────────────────────────
describe('Epic 10 -- core/api_client.js', () => {
    it('authFetch injects Authorization header when token present', async () => {
        auth.setToken('abc');
        const spy = vi.fn(async () => fakeResponse({}));
        vi.stubGlobal('fetch', spy);
        await api.authFetch('/api/x');
        const call = spy.mock.calls[0];
        expect(call[0]).toBe('/api/x');
        expect(call[1].headers.Authorization).toBe('Bearer abc');
    });

    it('authFetch omits Authorization when no token', async () => {
        const spy = vi.fn(async () => fakeResponse({}));
        vi.stubGlobal('fetch', spy);
        await api.authFetch('/api/x');
        const call = spy.mock.calls[0];
        // no Authorization key.
        expect(Object.keys(call[1].headers || {})).not.toContain('Authorization');
    });

    it('authFetch clears token and dispatches event on 401', async () => {
        auth.setToken('stale');
        vi.stubGlobal('fetch', vi.fn(async () =>
            fakeResponse({}, { ok: false, status: 401 })));
        const evSpy = vi.fn();
        window.addEventListener('dc-epms-auth-required', evSpy);
        await api.authFetch('/api/x');
        expect(auth.getToken()).toBeNull();
        expect(evSpy).toHaveBeenCalled();
        window.removeEventListener('dc-epms-auth-required', evSpy);
    });
});

// ─── views/login.js ──────────────────────────────────────────────
function mountLoginDOM() {
    document.body.innerHTML = `
        <div class="view" id="view-login">
            <input id="login-username">
            <input id="login-password">
            <button data-login-submit></button>
            <div data-login-error style="display:none;"></div>
            <div data-login-banner></div>
        </div>
        <div class="view" id="view-other"></div>`;
}

describe('Epic 10 -- views/login.js renderError XSS gate', () => {
    it('escapes <script> in error message', () => {
        mountLoginDOM();
        loginView.renderError('<script>alert(1)</script>boom');
        const el = document.querySelector('[data-login-error]');
        expect(el.innerHTML).not.toContain('<script>');
        expect(el.innerHTML).toContain('&lt;script&gt;');
        expect(el.innerHTML).toContain('boom');
    });

    it('clears error on empty', () => {
        mountLoginDOM();
        loginView.renderError('something');
        loginView.renderError('');
        const el = document.querySelector('[data-login-error]');
        expect(el.innerHTML).toBe('');
        expect(el.style.display).toBe('none');
    });
});

describe('Epic 10 -- views/login.js banner XSS gate', () => {
    it('escapes role in banner', () => {
        mountLoginDOM();
        loginView.renderLoggedInBanner('alice', '<img src=x>');
        const el = document.querySelector('[data-login-banner]');
        expect(el.innerHTML).not.toContain('<img');
        expect(el.innerHTML).toContain('&lt;img');
        expect(el.innerHTML).toContain('alice');
    });
});

describe('Epic 10 -- views/login.js submitLogin', () => {
    it('rejects empty credentials with an inline error', async () => {
        mountLoginDOM();
        const spy = vi.fn();
        vi.stubGlobal('fetch', spy);
        await loginView.submitLogin();
        expect(spy).not.toHaveBeenCalled();
        const err = document.querySelector('[data-login-error]');
        expect(err.style.display).toBe('block');
        expect(err.textContent.toLowerCase()).toContain('required');
    });

    it('dispatches dc-epms-auth-granted on success', async () => {
        mountLoginDOM();
        document.getElementById('login-username').value = 'alice';
        document.getElementById('login-password').value = 'pw';
        const future = Math.floor(Date.now() / 1000) + 3600;
        const tok = fakeJWT({
            sub: 'u-1', username: 'alice', role: 'SAFETY_OFFICER',
            iat: future - 3600, exp: future, jti: 'x',
        });
        vi.stubGlobal('fetch', vi.fn(async () => fakeResponse({
            access_token: tok, token_type: 'bearer', expires_in: 3600,
            user_id: 'u-1', username: 'alice', role: 'SAFETY_OFFICER',
        })));
        const evSpy = vi.fn();
        window.addEventListener('dc-epms-auth-granted', evSpy);
        await loginView.submitLogin();
        expect(evSpy).toHaveBeenCalled();
        expect(auth.hasValidToken()).toBe(true);
        window.removeEventListener('dc-epms-auth-granted', evSpy);
    });

    it('shows server error on 401', async () => {
        mountLoginDOM();
        document.getElementById('login-username').value = 'alice';
        document.getElementById('login-password').value = 'wrong';
        vi.stubGlobal('fetch', vi.fn(async () => fakeResponse(
            { detail: 'invalid credentials' }, { ok: false, status: 401 },
        )));
        await loginView.submitLogin();
        const err = document.querySelector('[data-login-error]');
        expect(err.textContent).toContain('invalid credentials');
        expect(auth.hasValidToken()).toBe(false);
    });
});

describe('Epic 10 -- showLoginView / hideLoginView', () => {
    it('showLoginView hides all other views', () => {
        mountLoginDOM();
        document.getElementById('view-other').hidden = false;
        document.getElementById('view-login').hidden = true;
        loginView.showLoginView();
        expect(document.getElementById('view-login').hidden).toBe(false);
        expect(document.getElementById('view-other').hidden).toBe(true);
    });

    it('hideLoginView hides login but does not touch others', () => {
        mountLoginDOM();
        document.getElementById('view-other').hidden = false;
        document.getElementById('view-login').hidden = false;
        loginView.hideLoginView();
        expect(document.getElementById('view-login').hidden).toBe(true);
        expect(document.getElementById('view-other').hidden).toBe(false);
    });
});
