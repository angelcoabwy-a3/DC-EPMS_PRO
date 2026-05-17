/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — frontend/assets/js/core/router.js
 * ROADMAP V11 T2.2 — declarative route registry.
 *
 * Replaces the per-view `_wireRouting()` LOTO pattern, where each ES
 * view added its own document click listener + setTimeout(0) to
 * override the legacy IIFE router. That race — the "zombie router" —
 * was the root of DC-EPMS-MAINT-001/002/003 and the drill-down
 * fragility.
 *
 * The single click entry point stays the legacy IIFE setupRouter();
 * its navigateTo() delegates any REGISTERED route to this module via
 * window.__epmsRouter. Unregistered routes fall through to the legacy
 * renderer untouched — a bug here cannot brick the whole navigation.
 * ════════════════════════════════════════════════════════════════ */

// routeId -> { viewId, activate(ctx) }
const _routes = new Map();
// routeIds that have already had their first activation
const _activated = new Set();

/**
 * Register an ES-module view's route. Called from the view's
 * init*View() at startup.
 * @param {string} routeId  the data-route value (e.g. 'mission-control')
 * @param {{viewId: string, activate?: function}} handler
 */
export function registerRoute(routeId, handler) {
    if (!routeId || !handler || !handler.viewId) {
        console.warn('[router] registerRoute: bad registration for', routeId);
        return;
    }
    _routes.set(routeId, handler);
}

/** True if routeId is owned by this declarative router. */
export function isRegistered(routeId) {
    return _routes.has(routeId);
}

/**
 * Activate a registered route: hide all views, show the target,
 * set the nav-active state, then call the view's activate() handler.
 * Returns true if handled, false if the route is not registered
 * (the caller should then fall back to the legacy renderer).
 */
export function navigateTo(routeId) {
    const handler = _routes.get(routeId);
    if (!handler) return false;

    document.querySelectorAll('.view').forEach(v => v.setAttribute('hidden', ''));
    const view = document.getElementById(handler.viewId);
    if (view) view.removeAttribute('hidden');

    document.querySelectorAll('.nav-item').forEach(n =>
        n.classList.toggle('active', n.dataset.route === routeId));

    const firstActivation = !_activated.has(routeId);
    _activated.add(routeId);
    try {
        handler.activate?.({ firstActivation });
    } catch (e) {
        console.error('[router] activate failed for route', routeId, e);
    }
    return true;
}

/**
 * Publish the router on window so the legacy IIFE in app.js can
 * delegate registered routes to it. Call once from main.js.
 */
export function initRouter() {
    window.__epmsRouter = { isRegistered, navigateTo };
    console.log('[router] declarative route registry ready');
}
