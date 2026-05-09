/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — frontend/assets/js/main.js
 *
 * ES module entry point for the Sprint 5.5 hybrid pivot.
 *
 * Responsibilities:
 *   1. Bootstrap the reactive state container (core/state.js).
 *   2. Wire the staleness monitor (core/staleness.js).
 *   3. Expose a frozen bridge `window.__epms` so the legacy IIFE in
 *      app.js can publish events into the new state without becoming
 *      a module itself. The bridge is intentionally minimal (setState
 *      + getState + subscribe). It will be retired in Phase 1.1 when
 *      app.js is fragmented into modules.
 *
 * Load order in index.html (both deferred):
 *
 *   <script type="module" src="/assets/js/main.js"></script>   <- this
 *   <script defer        src="/assets/app.js"></script>        <- legacy
 *
 * Both execute after DOM parsing in document order. main.js sets the
 * bridge before app.js IIFE runs. Race-free.
 * ════════════════════════════════════════════════════════════════ */

import { setState, getState, subscribe } from './core/state.js';
import { initStaleness } from './core/staleness.js';

window.__epms = Object.freeze({ setState, getState, subscribe });

initStaleness();

console.log(
    '%c DC-EPMS hybrid bridge ready ',
    'background:#00B8D4;color:#0B0D10;font-weight:700;padding:2px 6px;border-radius:2px;',
);
