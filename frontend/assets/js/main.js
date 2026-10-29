/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — frontend/assets/js/main.js
 *
 * The single ES module entry point for the HMI.
 *
 * ROADMAP V11 T2.1 is CLOSED: the legacy app.js IIFE monolith has been
 * fully dismantled into ES modules. index.html now loads only this
 * file; every view lives in views/*.js, every shared engine in
 * core/*.js, and core/bootstrap.js carries the old IIFE's router glue.
 *
 * Responsibilities:
 *   1. Bootstrap the reactive state container (core/state.js).
 *   2. Wire the staleness monitor (core/staleness.js).
 *   3. Expose the frozen `window.__epms` bridge (setState + getState +
 *      subscribe) — still the shared reactive surface between modules.
 *   4. Initialise every core engine + view, then the router glue.
 *
 * Loaded once from index.html:
 *   <script type="module" src="/assets/js/main.js"></script>
 * ════════════════════════════════════════════════════════════════ */

import { setState, getState, subscribe } from './core/state.js';
import { initRouter } from './core/router.js';
import { initStaleness } from './core/staleness.js';
import { initActivityStrip } from './core/activity_strip.js';
import { initShiSparkline } from './core/shi_sparkline.js';
import { initPueWidget } from './core/pue_widget.js';
import { initSound } from './core/sound.js';
import { initKeyboard } from './core/keyboard.js';
import { initHeatOverlay } from './core/heat_overlay.js';
import { initPowerSld } from './core/power_sld.js';
import { startTelemetry } from './core/telemetry_engine.js';
import { initHermesEvents } from './core/hermes_events.js';
import { initMaintenanceView } from './views/maintenance.js';
import { initSiteTopologyView } from './views/site_topology.js';
import { initRackHeatmapView } from './views/rack_heatmap.js';
import { initMissionControlView } from './views/mission_control.js';
import { initTechAssistView } from './views/tech_assist.js';
import { initMultiAgentView } from './views/multi_agent.js';
import { initPowerGrid } from './core/power_grid.js';
import { initAssetPanel } from './views/asset_panel.js';
import { initScenariosView } from './views/scenarios.js';
import { initIncidentsView } from './views/incidents.js';
import { initShiftCopilotView } from './views/shift_copilot.js';
import { initMopsView } from './views/mops.js';
import { initPowerView } from './views/power.js';
import { initCoolingView } from './views/cooling.js';
import { initCopilotView } from './views/copilot.js';
import { initBmsView } from './views/bms.js';
import { initLotoView } from './views/loto.js';
import { initTopologyView } from './views/topology.js';
import { initOverviewView } from './views/overview.js';
import { initOptimizerView } from './views/optimizer.js';
import { initProceduresView } from './views/procedures.js';
import { initQuantumView } from './views/quantum.js';
import { initMopVerifyView } from './views/mop_verify.js';
import { initLoginView, showLoginView, hideLoginView } from './views/login.js';
import { hasValidToken, getClaims, onAuthChange } from './core/auth.js';
import { startQkdGate } from './core/qkd_gate.js';
import { initBootstrap } from './core/bootstrap.js';
import { initDemoMode } from './core/demo.js';

// Telemetry engine flag. core/telemetry_engine.js owns the SSE; this
// stays a flag purely as a console kill-switch for debugging.
//     window.__epms.useNewEngine = false; location.reload();
const USE_NEW_TELEMETRY_ENGINE = true;

window.__epms = Object.freeze({
    setState,
    getState,
    subscribe,
    useNewEngine: USE_NEW_TELEMETRY_ENGINE,
});

initRouter();
initStaleness();
initActivityStrip();
initShiSparkline();
initPueWidget();
initSound();
initKeyboard();
initHeatOverlay();
// Power grid DAG engine must come BEFORE power_sld + iso (subscribers bind early)
initPowerGrid();
initPowerSld();
initMaintenanceView();
initSiteTopologyView();
initRackHeatmapView();
initMissionControlView();
initTechAssistView();
initMultiAgentView();
// SLD Reengineering 2026-06-11: the 2.5D iso stage (power_ups_iso.js +
// power_cam.js) is RETIRED. The registry-driven flat SLD (views/power.js,
// ADR-012 diagram kit) is the one and only Power & UPS surface — the iso
// layer was Phase-1-only and silently hid the Phase 2 / 50 MW work.
// Contextual asset panel (Phase 4 v0.10.9) — .pid-canvas is static markup
initAssetPanel();
// Failure-scenario simulator — T2.1: first IIFE view extracted to an ES module
initScenariosView();
// Incident audit log — T2.1: second IIFE view extracted to an ES module
initIncidentsView();
// Shift Copilot panel (inside #view-incidents) — drives /api/copilot/*
initShiftCopilotView();
// MOP/SOP/EOP library — T2.1: third IIFE view extracted to an ES module
initMopsView();
// Power & UPS SLD — T2.1: data plane extracted; Hermes-bound (T3.1)
initPowerView();
// Cooling (DLC) P&ID — T2.1: view extracted to an ES module
initCoolingView();
// Facility Co-Pilot AI — T2.1: agent chat extracted; LLM surfaces
// XSS-sanitized (F3-5); subscribes to hermes:agent-consensus (T3.1)
initCopilotView();
// BMS Connector — T2.1 Vector 1: tag registry + RBAC write modal +
// NIST SP 800-82 audit; re-exposes window.showBmsAudit for copilot
initBmsView();
// LOTO Auditor — T2.1 Vector 2: 6-pillar audit; declarative route
// (retires the legacy click-delegation zombie-router hack)
initLotoView();
// HLD/LLD Topology — T2.1 Vector 4a: physics-driven system map +
// What-If sim + AI Mission Control insights; declarative route
initTopologyView();
// Overview / landing dashboard — T2.1 Vector 4b: the final view out
// of the IIFE monolith (health, KPIs, PUE chart, agent chat, SHI)
initOverviewView();
// Epic 2 Batch 2.D — Optimizer HMI: lists the proactive-edge-agent
// proposal queue + approve/reject under SME_L6 RBAC. Routes through
// sanitizeHTML for the LLM-authored narratives (S-SEC-01).
initOptimizerView();
// Epic 6 — Procedure Architect HMI: LLM-authored SOP / MOP / EOP / EMP
// with deterministic Safety Officer audit gate. Routes the markdown
// through a deliberately-minimal escape-then-substitute renderer
// (no full markdown library = no XSS surface) — S-SEC-01.
initProceduresView();
// Epic 9 — BB84 educational QKD telemetry HMI: surfaces the simulator's
// current QBER + pool depth so the eavesdropper-injection drill is
// visually demonstrable. structured render path -> escapeHTML only.
initQuantumView();
// Meta hackathon — MOP photo verification HMI: procedure stepper +
// multipart photo verify + result rendered only from the API response.
initMopVerifyView();
// Epic 10 — IAM login view. Wired BEFORE bootstrap so the form is
// listening for clicks even before auth has been granted. The auth
// gate below decides whether to show login or run the full app.
initLoginView();
// Router glue — T2.1 Vector 4c: the app.js IIFE residual, promoted to
// core/bootstrap.js. app.js is now DELETED — Epic T2.1 closed.
initBootstrap();
// Meta hackathon — demo mode. Async + fire-and-forget: loads
// demo_config.json (?demo=0/1 overrides), hides pre-existing surfaces
// when on, and lands on the default view. No-op when the config is
// missing, so the app boots exactly as today.
initDemoMode();

// Epic 10 -- Auth gate. If no valid JWT in localStorage, hide every
// view except #view-login and the sidebar nav. On successful login
// the dc-epms-auth-granted event fires from views/login.js -- we
// hide the login form + un-hide the default view. On 401 in any
// authFetch, core/api_client.js dispatches dc-epms-auth-required
// which routes back to the login surface.
function _applyAuthGate() {
    if (hasValidToken()) {
        hideLoginView();
        const claims = getClaims();
        const banner = document.querySelector('[data-login-banner]');
        if (banner && claims) {
            banner.textContent = (claims.username || '?') + ' (' + (claims.role || '') + ')';
        }
    } else {
        showLoginView();
    }
}

window.addEventListener('dc-epms-auth-granted', () => {
    _applyAuthGate();
});
window.addEventListener('dc-epms-auth-required', () => {
    _applyAuthGate();
});
onAuthChange(() => _applyAuthGate());

// Boot-time apply.
_applyAuthGate();

// Epic 10 Batch 4 -- start polling /api/qkd/status. When QBER
// crosses the threshold (default 11%), body.qkd-gate-closed is
// applied + the global banner appears + downstream sign actions
// refuse to dispatch. The poll continues even when the login view
// is shown (cheap; surfaces the warning the moment operators sign
// in).
startQkdGate();

// Project Hermes EDA — T3.1: route cmms_alerts + agent_consensus streams
// into reactive state + decoupled DOM events for the HMI.
initHermesEvents();

if (USE_NEW_TELEMETRY_ENGINE) {
    startTelemetry(window.location.origin);
}

console.log(
    '%c DC-EPMS hybrid bridge ready ',
    'background:#00B8D4;color:#0B0D10;font-weight:700;padding:2px 6px;border-radius:2px;',
    USE_NEW_TELEMETRY_ENGINE ? '(new engine: ON)' : '(new engine: OFF — legacy SSE)',
);
