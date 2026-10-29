/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — frontend/assets/js/core/demo.js
 * Meta Global AI Developer Hackathon (Oct 26 - Nov 4, 2026) — demo mode.
 *
 * The hackathon rules say the demo may only show what was built during
 * the event. When demo mode is on, this module hides every pre-existing
 * surface (nav entries, header chips/counters, right-rail panels) and
 * routes any disallowed URL to the configured default view. It never
 * deletes or rewrites views: demo mode only hides them, and turning it
 * off restores the app exactly as it was.
 *
 * Sources, in priority order:
 *   1. URL override: ?demo=0 forces off, ?demo=1 forces on. This is how
 *      the full app stays visible locally.
 *   2. frontend/assets/demo_config.json (demo_mode + allowed_views +
 *      default_view). If it fails to load, demo mode is off.
 *
 * No imports: core/router.js and core/bootstrap.js both consult
 * guardRoute(), so this module must stay dependency-free (no cycles).
 * ════════════════════════════════════════════════════════════════ */

const CONFIG_URL = '/assets/demo_config.json';
const DEMO_NOTE_TEXT = 'Demo mode: only features built during the Meta hackathon are shown.';
const FALLBACK_VIEW = 'mop-verify';

// Header chips + counters + right-rail panels that belong to
// pre-existing features. The product name (.logo) is never touched.
const CHROME_IDS = [
    'health-pg',
    'health-rag',
    'health-gemma',
    'health-gpu',
    'health-stream',
    'activity-strip',
    'rail-incidents',
    'rail-sysinfo',
];

let _active = false;
let _allowed = [FALLBACK_VIEW];
let _defaultView = FALLBACK_VIEW;

/**
 * Pure resolution: config file + URL search string -> demo state.
 * @param {object|null} config parsed demo_config.json (null when unloadable)
 * @param {string} search window.location.search ('' when unavailable)
 */
function resolveDemoState(config, search) {
    let active = !!(config && config.demo_mode === true);
    let params = null;
    try {
        params = new URLSearchParams(search || '');
    } catch (_e) {
        params = null;
    }
    const override = params ? params.get('demo') : null;
    if (override === '0') active = false;
    else if (override === '1') active = true;

    const allowed = (config && Array.isArray(config.allowed_views) && config.allowed_views.length)
        ? config.allowed_views.filter((v) => typeof v === 'string' && v).slice()
        : [FALLBACK_VIEW];
    let defaultView = (config && typeof config.default_view === 'string' && config.default_view)
        ? config.default_view
        : FALLBACK_VIEW;
    if (!allowed.includes(defaultView)) allowed.push(defaultView);
    return { active, allowed, defaultView };
}

/**
 * Fetch + parse the demo config. Never throws: any failure (404,
 * network error, invalid JSON, wrong shape) resolves to null, which
 * resolveDemoState() treats as "demo mode off".
 */
async function loadDemoConfig(fetchFn) {
    const run = fetchFn || (typeof fetch !== 'undefined' ? fetch : null);
    if (!run) return null;
    try {
        const res = await run(CONFIG_URL);
        if (!res || !res.ok) return null;
        const data = await res.json();
        return data && typeof data === 'object' ? data : null;
    } catch (_e) {
        return null;
    }
}

function setDemoState(state) {
    _active = !!(state && state.active);
    _allowed = (state && Array.isArray(state.allowed) && state.allowed.length)
        ? state.allowed.slice()
        : [FALLBACK_VIEW];
    _defaultView = (state && typeof state.defaultView === 'string' && state.defaultView)
        ? state.defaultView
        : FALLBACK_VIEW;
    if (!_allowed.includes(_defaultView)) _allowed.push(_defaultView);
}

function isDemoActive() {
    return _active;
}

/**
 * Router guard shared by core/router.js and core/bootstrap.js.
 * Demo off -> returns the route untouched (today's behavior).
 * Demo on -> disallowed routes become the default view, so a stale
 * URL or default route can never land on (or blank) a hidden view.
 */
function guardRoute(routeId) {
    if (!_active) return routeId;
    if (typeof routeId === 'string' && _allowed.includes(routeId)) return routeId;
    return _defaultView;
}

function _setVisible(el, visible) {
    if (!el) return;
    el.style.display = visible ? '' : 'none';
}

/**
 * Apply (or, when inactive, fully revert) every demo-mode hiding:
 * nav entries outside allowed_views, every [data-demo-chrome] element
 * (Reports rail section, header facility chips, footer telemetry
 * line), header chips/counters, right-rail panels, the nav + rail grid
 * columns themselves (zero width), plus the demo note under the
 * allowed views' headers and the slim top bar (badge + inline note).
 * Idempotent; safe to call repeatedly.
 */
function applyDemoMode() {
    if (typeof document === 'undefined') return;
    if (document.body) document.body.classList.toggle('demo-mode', _active);

    document.querySelectorAll('.nav-item[data-route]').forEach((el) => {
        _setVisible(el, !_active || _allowed.includes(el.dataset.route));
    });
    document.querySelectorAll('[data-demo-chrome]').forEach((el) => {
        _setVisible(el, !_active);
    });
    for (const id of CHROME_IDS) {
        _setVisible(document.getElementById(id), !_active);
    }
    // The nav + rail grid columns leave the layout entirely (CSS also
    // collapses .app-main to one column under body.demo-mode; the
    // inline style guarantees zero width even if CSS fails to load).
    document.querySelectorAll('.panel-nav, .panel-side').forEach((el) => {
        _setVisible(el, !_active);
    });

    // Slim top bar: product name (kept) + hackathon badge + demo note
    // on the same flex line. Removed again when demo mode is off.
    document.querySelectorAll('.demo-note-inline, .demo-bar-badge').forEach((el) => {
        if (el.parentNode) el.parentNode.removeChild(el);
    });
    if (_active) {
        const header = document.querySelector('.app-header');
        const logo = header ? header.querySelector('.logo') : null;
        if (header && logo && !header.querySelector('.demo-note-inline')) {
            const badge = document.createElement('span');
            badge.className = 'mv-badge demo-bar-badge';
            badge.textContent = 'Built during hackathon';
            const note = document.createElement('span');
            note.className = 'demo-note-inline';
            note.textContent = DEMO_NOTE_TEXT;
            logo.after(badge);
            badge.after(note);
        }
    }

    document.querySelectorAll('.demo-note').forEach((el) => {
        if (el.parentNode) el.parentNode.removeChild(el);
    });
    if (_active) {
        for (const route of _allowed) {
            const header = document.querySelector('#view-' + route + ' .view-hdr');
            if (!header || header.querySelector('.demo-note')) continue;
            const note = document.createElement('div');
            note.className = 'demo-note';
            note.textContent = DEMO_NOTE_TEXT;
            header.appendChild(note);
        }
    }
}

/**
 * After the config loads, land on the default view when the current
 * URL (or the no-hash default) points at a disallowed view. Prefers
 * the declarative router; falls back to a hash assignment (picked up
 * by the setupRouter hashchange listener, which is also guarded).
 */
function ensureAllowedRoute() {
    if (!_active || typeof window === 'undefined') return;
    let current = '';
    try {
        current = ((window.location && window.location.hash) || '').replace(/^#/, '');
    } catch (_e) {
        current = '';
    }
    if (!current) current = 'overview';
    if (_allowed.includes(current)) return;
    const router = window.__epmsRouter;
    if (router && typeof router.navigateTo === 'function') {
        router.navigateTo(_defaultView);
    } else {
        try {
            window.location.hash = '#' + _defaultView;
        } catch (_e) { /* no navigation surface available */ }
    }
}

/**
 * Tell views the demo state settled so they can swap their layout
 * (mop_verify.js listens). demo.js stays dependency-free: no imports,
 * just a DOM event.
 */
function _notifyDemoMode() {
    try {
        if (typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
            window.dispatchEvent(new CustomEvent('epms:demo-mode', {
                detail: { active: _active },
            }));
        }
    } catch (_e) { /* no event surface available */ }
}

/**
 * Startup entry, called once from main.js after initBootstrap().
 * Fire-and-forget: never throws, never rejects.
 */
async function initDemoMode() {
    try {
        const config = await loadDemoConfig();
        let search = '';
        try {
            search = (typeof window !== 'undefined' && window.location) ? window.location.search : '';
        } catch (_e) {
            search = '';
        }
        setDemoState(resolveDemoState(config, search));
        applyDemoMode();
        ensureAllowedRoute();
        _notifyDemoMode();
    } catch (_e) {
        // Demo mode must never break boot: fall back to today's app.
        try {
            setDemoState({ active: false });
            applyDemoMode();
        } catch (_ignored) { /* unreachable defensive */ }
    }
}

export {
    resolveDemoState,
    loadDemoConfig,
    setDemoState,
    isDemoActive,
    guardRoute,
    applyDemoMode,
    ensureAllowedRoute,
    initDemoMode,
    DEMO_NOTE_TEXT,
    CONFIG_URL,
};
