/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO -- views/login.js
 * Epic 10 -- IAM login surface.
 *
 * Username + password form. POSTs /api/auth/login via core/auth.js
 * and stores the JWT in localStorage on success. On success
 * dispatches the 'dc-epms-auth-granted' DOM event so the bootstrap
 * can reveal the rest of the app. On failure renders an inline
 * error message (S-SEC-01 escapeHTML on every server-supplied
 * string).
 *
 * Layout:
 *   #view-login   -- mounted from index.html
 *     [data-login-form]    -- container
 *     #login-username
 *     #login-password
 *     [data-login-submit]  -- button
 *     [data-login-error]   -- inline error region
 *
 * The login view does NOT register through core/router.js -- it
 * is the boot-time gate: if no valid token, bootstrap unhides
 * #view-login and HIDES every other view container.
 * ════════════════════════════════════════════════════════════════ */

import { escapeHTML } from '../core/sanitize.js';
import { hasValidToken, login } from '../core/auth.js';

const $ = (id) => document.getElementById(id);

let _wired = false;

function renderError(message) {
    const el = document.querySelector('[data-login-error]');
    if (!el) return;
    if (!message) {
        el.innerHTML = '';
        el.style.display = 'none';
        return;
    }
    el.style.display = 'block';
    el.innerHTML = '<span class="login-error">'
        + escapeHTML(String(message))
        + '</span>';
}

function renderLoggedInBanner(username, role) {
    const el = document.querySelector('[data-login-banner]');
    if (!el) return;
    el.innerHTML = ''
        + '<span class="login-banner-user">'
        + escapeHTML(String(username || '?'))
        + '</span> <span class="login-banner-role">('
        + escapeHTML(String(role || ''))
        + ')</span>';
}

async function submitLogin() {
    const u = $('login-username');
    const p = $('login-password');
    const username = (u && u.value || '').trim();
    const password = (p && p.value || '');
    renderError('');
    if (!username || !password) {
        renderError('Username and password are required.');
        return;
    }
    const out = await login(username, password);
    if (!out.ok) {
        renderError(out.error || ('login failed (HTTP ' + out.status + ')'));
        return;
    }
    renderLoggedInBanner(out.user.username, out.user.role);
    try {
        window.dispatchEvent(new CustomEvent('dc-epms-auth-granted', {
            detail: { user: out.user },
        }));
    } catch (_e) { /* harness without CustomEvent */ }
}

function onClick(ev) {
    const t = ev.target;
    if (!t) return;
    if (t.matches && t.matches('[data-login-submit]')) {
        ev.preventDefault();
        submitLogin();
    }
}

function onKeyDown(ev) {
    if (ev.key === 'Enter') {
        const ae = document.activeElement;
        if (ae && (ae.id === 'login-username' || ae.id === 'login-password')) {
            ev.preventDefault();
            submitLogin();
        }
    }
}

function initLoginView() {
    if (_wired) return;
    _wired = true;
    // The view container always exists in the DOM; we wire delegated
    // listeners on document so the listener survives re-mounts.
    document.addEventListener('click', onClick);
    document.addEventListener('keydown', onKeyDown);
}

function showLoginView() {
    const all = document.querySelectorAll('.view');
    all.forEach((el) => {
        if (el.id === 'view-login') {
            el.hidden = false;
        } else {
            el.hidden = true;
        }
    });
    const sidebar = document.querySelector('.sidebar');
    if (sidebar) sidebar.classList.add('login-locked');
}

function hideLoginView() {
    const login = document.getElementById('view-login');
    if (login) login.hidden = true;
    const sidebar = document.querySelector('.sidebar');
    if (sidebar) sidebar.classList.remove('login-locked');
}

function reset() {
    _wired = false;
}

export { initLoginView, showLoginView, hideLoginView };

export const __login_view_test__ = {
    renderError,
    renderLoggedInBanner,
    submitLogin,
    onClick,
    onKeyDown,
    initLoginView,
    showLoginView,
    hideLoginView,
    hasValidToken,
    reset,
};
