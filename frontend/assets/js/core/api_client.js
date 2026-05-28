/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO -- frontend/assets/js/core/api_client.js
 * Epic 10 -- thin fetch wrapper that injects Authorization.
 *
 * Existing views call fetch() directly; new code paths that need
 * the JWT use this wrapper. Migration of existing callers is
 * incremental.
 *
 * Surface:
 *   authFetch(url, options)  -- same shape as fetch(), but injects
 *                                Authorization: Bearer <token>
 *                                from core/auth.js when present.
 *                                Returns the raw Response so the
 *                                caller can branch on .ok / .status.
 *
 *   getJSON(url) / postJSON(url, body)  -- ergonomic helpers that
 *                                          throw on non-2xx and
 *                                          return the parsed body.
 *
 * On 401: clears the stored token + dispatches the
 * 'dc-epms-auth-required' DOM event so the bootstrap can route to
 * the login view. (A 401 implies the server invalidated our token
 * -- showing stale UI is worse than forcing re-login.)
 * ════════════════════════════════════════════════════════════════ */

import { clearToken, getAuthHeader } from './auth.js';

function _mergeHeaders(base, extra) {
    const out = Object.assign({}, base || {});
    if (extra) {
        for (const k of Object.keys(extra)) out[k] = extra[k];
    }
    return out;
}

async function authFetch(url, options = {}) {
    const headers = _mergeHeaders(options.headers, getAuthHeader());
    const res = await fetch(url, Object.assign({}, options, { headers }));
    if (res.status === 401) {
        clearToken();
        try {
            window.dispatchEvent(new CustomEvent('dc-epms-auth-required'));
        } catch (_e) { /* CustomEvent unsupported in some sandboxes */ }
    }
    return res;
}

async function getJSON(url) {
    const res = await authFetch(url);
    if (!res.ok) {
        const t = await res.text().catch(() => '');
        throw new Error('GET ' + url + ' -> ' + res.status + ' ' + t);
    }
    return res.json();
}

async function postJSON(url, body) {
    const res = await authFetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!res.ok) {
        const t = await res.text().catch(() => '');
        throw new Error('POST ' + url + ' -> ' + res.status + ' ' + t);
    }
    return res.json();
}

export { authFetch, getJSON, postJSON };

export const __api_client_test__ = {
    _mergeHeaders,
    authFetch,
    getJSON,
    postJSON,
};
