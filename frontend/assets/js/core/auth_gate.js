/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO -- frontend/assets/js/core/auth_gate.js
 * Release R1 -- navigation-level auth guard.
 *
 * Problem this closes
 * -------------------
 * main.js applied the Epic 10 login gate once at boot (hide every
 * view, show #view-login). The router did not know about it: the
 * deferred initial-hash navigation and any later hashchange called
 * navigateTo(), which un-hides the target view. Loading
 * "/#optimizer" without a session therefore rendered the Optimizer
 * shell and no login form at all.
 *
 * Contract
 * --------
 *   armAuthGate()        main.js calls it once at boot. Until then
 *                        the guard is inert, so modules (and their
 *                        vitest suites) that drive the router
 *                        directly keep today's behaviour.
 *   navigationBlocked()  true when armed, no valid JWT, and the
 *                        hackathon demo mode is off. Demo mode keeps
 *                        its allowed views public by design; its own
 *                        guardRoute() restricts which views those are.
 *   requestLogin()       dispatches dc-epms-auth-required -- the same
 *                        event core/api_client.js emits on a 401;
 *                        main.js answers it by showing the login view.
 *
 * Core modules must not import views (layering), hence the event
 * instead of a direct showLoginView() call.
 * ════════════════════════════════════════════════════════════════ */

import { hasValidToken } from './auth.js';
import { isDemoActive } from './demo.js';

let _armed = false;

function armAuthGate() {
    _armed = true;
}

function navigationBlocked() {
    return _armed && !isDemoActive() && !hasValidToken();
}

function requestLogin() {
    try {
        window.dispatchEvent(new CustomEvent('dc-epms-auth-required'));
    } catch (_e) { /* CustomEvent unsupported in some sandboxes */ }
}

function _resetForTest() {
    _armed = false;
}

export { armAuthGate, navigationBlocked, requestLogin };

export const __auth_gate_test__ = { reset: _resetForTest };
