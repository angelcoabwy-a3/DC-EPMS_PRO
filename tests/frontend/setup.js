/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/setup.js
 * Vitest setupFile — runs once per test file, after the happy-dom
 * environment is created, before the test code.
 *
 * happy-dom does not implement WebGL. The B1 Mission Control view
 * (via three.js) calls canvas.getContext('webgl'|'webgl2'). This
 * file stubs getContext so importing/exercising that code in Bite 2+
 * never crashes the runner. Per the T2.4 directive: mock WebGL
 * entirely; do NOT test the real render loop yet.
 * ════════════════════════════════════════════════════════════════ */

// Permissive WebGL context stub: ALL-CAPS props (GL enums) read as 0,
// every other access returns a chainable no-op function.
const _webglStub = new Proxy({}, {
    get(_target, prop) {
        if (typeof prop === 'string' && /^[A-Z][A-Z0-9_]*$/.test(prop)) return 0;
        return () => _webglStub;
    },
});

// Minimal 2D context stub (Chart.js / sparklines may probe it later).
const _ctx2dStub = new Proxy({}, { get: () => () => {} });

if (typeof HTMLCanvasElement !== 'undefined') {
    HTMLCanvasElement.prototype.getContext = function getContext(kind) {
        if (kind === 'webgl' || kind === 'webgl2' || kind === 'experimental-webgl') {
            return _webglStub;
        }
        if (kind === '2d') return _ctx2dStub;
        return null;
    };
}

// happy-dom provides requestAnimationFrame; keep a defensive fallback
// so timing-dependent code (drill-down zoom, _transitionWatchdog)
// never throws if the environment is swapped later.
if (typeof globalThis.requestAnimationFrame !== 'function') {
    globalThis.requestAnimationFrame = (cb) => setTimeout(() => cb(performance.now()), 16);
    globalThis.cancelAnimationFrame = (id) => clearTimeout(id);
}

// Epic 10 -- Node 22+ ships an experimental localStorage global that
// requires `--localstorage-file=<path>` to work; without it,
// localStorage.setItem is missing. happy-dom's window.localStorage IS
// a working in-memory implementation -- we force-bind it as the
// global so calls written as plain `localStorage.setItem(...)`
// (the way browser code is written) work in the test env. Use a
// pure in-memory polyfill if window.localStorage is also missing so
// the test does not silently use a stub.
function _makeMemoryStorage() {
    let store = new Map();
    return {
        setItem(k, v) { store.set(String(k), String(v)); },
        getItem(k) { return store.has(String(k)) ? store.get(String(k)) : null; },
        removeItem(k) { store.delete(String(k)); },
        clear() { store = new Map(); },
        key(i) { return Array.from(store.keys())[i] || null; },
        get length() { return store.size; },
    };
}

function _installStorage(name) {
    let target = null;
    try {
        if (typeof window !== 'undefined' && window[name]
            && typeof window[name].setItem === 'function') {
            target = window[name];
        }
    } catch (_e) { /* fall through to polyfill */ }
    if (!target) target = _makeMemoryStorage();
    try {
        Object.defineProperty(globalThis, name, {
            configurable: true,
            writable: true,
            value: target,
        });
    } catch (_e) {
        // If we cannot redefine, mutate the existing object's methods.
        const existing = globalThis[name];
        if (existing) {
            existing.setItem = target.setItem.bind(target);
            existing.getItem = target.getItem.bind(target);
            existing.removeItem = target.removeItem.bind(target);
            existing.clear = target.clear.bind(target);
        }
    }
}

_installStorage('localStorage');
_installStorage('sessionStorage');
