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
import { initActivityStrip } from './core/activity_strip.js';
import { initShiSparkline } from './core/shi_sparkline.js';
import { initPueWidget } from './core/pue_widget.js';
import { startTelemetry } from './core/telemetry_engine.js';
import { initMaintenanceView } from './views/maintenance.js';
import { initTechAssistView } from './views/tech_assist.js';
import { initMultiAgentView } from './views/multi_agent.js';

// Feature flag — when false the legacy IIFE in app.js owns the SSE.
// Toggle in browser console for emergency rollback:
//     window.__epms.useNewEngine = false; location.reload();
const USE_NEW_TELEMETRY_ENGINE = true;

window.__epms = Object.freeze({
    setState,
    getState,
    subscribe,
    useNewEngine: USE_NEW_TELEMETRY_ENGINE,
});

initStaleness();
initActivityStrip();
initShiSparkline();
initPueWidget();
initMaintenanceView();
initTechAssistView();
initMultiAgentView();

if (USE_NEW_TELEMETRY_ENGINE) {
    startTelemetry(window.location.origin);
}

console.log(
    '%c DC-EPMS hybrid bridge ready ',
    'background:#00B8D4;color:#0B0D10;font-weight:700;padding:2px 6px;border-radius:2px;',
    USE_NEW_TELEMETRY_ENGINE ? '(new engine: ON)' : '(new engine: OFF — legacy SSE)',
);
