/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO -- frontend/assets/js/core/auth.js
 * Epic 10 -- IAM session state for the HMI.
 *
 * Stores the JWT issued by POST /api/auth/login in localStorage,
 * exposes helpers for:
 *   - hasValidToken(): cheap synchronous check the bootstrap uses
 *     to decide whether to show the login view or the app.
 *   - getAuthHeader(): for API clients that inject Authorization.
 *   - getClaims(): decodes the JWT payload (NO signature check on
 *     the client -- the server is authoritative; this is just for
 *     UI surfaces like "logged in as <role>").
 *   - login(username, password) / logout(): mutating helpers.
 *   - onAuthChange(cb): subscribe to login / logout events.
 *
 * Threat model
 * ------------
 * localStorage tokens are XSS-recoverable. Mitigated today by
 * S-SEC-01 escapeHTML / sanitizeHTML discipline on every DOM
 * surface that touches LLM or operator-supplied strings. The
 * principled long-term move is an httpOnly cookie -- tracked
 * but out of scope for Epic 10 MVP.
 *
 * Test surface: __auth_test__ exposes pure helpers + reset().
 * ════════════════════════════════════════════════════════════════ */

const STORAGE_KEY = 'dc_epms_jwt';
const _listeners = new Set();

function _safeAtob(b64url) {
    // base64url -> base64
    const pad = '='.repeat((4 - (b64url.length % 4)) % 4);
    const b64 = (b64url + pad).replace(/-/g, '+').replace(/_/g, '/');
    try {
        return atob(b64);
    } catch (_e) {
        return '';
    }
}

function decodeClaims(token) {
    if (typeof token !== 'string' || token.split('.').length !== 3) {
        return null;
    }
    const payloadB64 = token.split('.')[1];
    const raw = _safeAtob(payloadB64);
    if (!raw) return null;
    try {
        return JSON.parse(raw);
    } catch (_e) {
        return null;
    }
}

function _isExpired(claims) {
    if (!claims || typeof claims.exp !== 'number') return true;
    return claims.exp * 1000 <= Date.now();
}

// ─── Token state ──────────────────────────────────────────────────
function getToken() {
    try {
        return localStorage.getItem(STORAGE_KEY) || null;
    } catch (_e) {
        return null;
    }
}

function setToken(token) {
    try {
        if (typeof token === 'string' && token.length > 0) {
            localStorage.setItem(STORAGE_KEY, token);
        } else {
            localStorage.removeItem(STORAGE_KEY);
        }
    } catch (_e) {
        // localStorage blocked -- nothing we can do; UI will show login.
    }
    _notify();
}

function clearToken() {
    try {
        localStorage.removeItem(STORAGE_KEY);
    } catch (_e) { /* noop */ }
    _notify();
}

function hasValidToken() {
    const t = getToken();
    if (!t) return false;
    const claims = decodeClaims(t);
    if (!claims) return false;
    return !_isExpired(claims);
}

function getClaims() {
    const t = getToken();
    if (!t) return null;
    return decodeClaims(t);
}

function getAuthHeader() {
    const t = getToken();
    if (!t) return {};
    return { 'Authorization': 'Bearer ' + t };
}

// ─── Listener fan-out ────────────────────────────────────────────
function onAuthChange(cb) {
    if (typeof cb !== 'function') return () => {};
    _listeners.add(cb);
    return () => _listeners.delete(cb);
}

function _notify() {
    const authed = hasValidToken();
    const claims = getClaims();
    for (const cb of _listeners) {
        try {
            cb({ authenticated: authed, claims });
        } catch (_e) { /* swallow listener errors */ }
    }
}

// ─── Login + logout ──────────────────────────────────────────────
async function login(username, password) {
    if (!username || !password) {
        return { ok: false, status: 400, error: 'username and password required' };
    }
    let res;
    try {
        res = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
        });
    } catch (e) {
        return { ok: false, status: 0, error: 'network error: ' + String(e) };
    }
    if (!res.ok) {
        let detail = 'login failed';
        try {
            const j = await res.json();
            if (j && j.detail) detail = j.detail;
        } catch (_e) { /* keep default */ }
        return { ok: false, status: res.status, error: detail };
    }
    let body;
    try {
        body = await res.json();
    } catch (_e) {
        return { ok: false, status: 502, error: 'bad response shape' };
    }
    if (!body || typeof body.access_token !== 'string') {
        return { ok: false, status: 502, error: 'missing access_token' };
    }
    setToken(body.access_token);
    return { ok: true, status: 200, user: body };
}

function logout() {
    clearToken();
}

// ─── Public surface ───────────────────────────────────────────────
export {
    STORAGE_KEY,
    clearToken,
    decodeClaims,
    getAuthHeader,
    getClaims,
    getToken,
    hasValidToken,
    login,
    logout,
    onAuthChange,
    setToken,
};

export const __auth_test__ = {
    STORAGE_KEY,
    decodeClaims,
    _isExpired,
    _safeAtob,
    setToken,
    clearToken,
    getToken,
    getClaims,
    getAuthHeader,
    hasValidToken,
    login,
    logout,
    onAuthChange,
    reset: () => {
        try { localStorage.removeItem(STORAGE_KEY); } catch (_e) {}
        _listeners.clear();
    },
};
