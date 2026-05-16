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
