/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — frontend/assets/js/core/bootstrap.js
 * ROADMAP V11 T2.1 Vector 4c — the IIFE monolith's residual.
 *
 * This is the last ~120 LOC of the old app.js, promoted to an ES
 * module. With it, app.js is DELETED — Epic T2.1 (dismantle the
 * app.js IIFE) is closed: the frontend is now fully modular
 * (core/ + views/, all routed by core/router.js).
 *
 * Responsibilities:
 *   - MODULES: the route → {title, sub, kind} config table.
 *   - navigateTo(): the single nav entry point. Delegates every
 *     core/router.js-registered route to the declarative registry;
 *     only `maintenance` (MutationObserver-driven) and the
 *     `placeholder` views (Morpheus / Gemini / Omniverse) still use
 *     the inline branch.
 *   - setupRouter(): wires the nav-rail clicks.
 *   - renderPlaceholder(): the coming-soon stub views. A suggested-
 *     query chip deep-links into the Overview agent via the
 *     `epms:overview-ask` DOM event (views/overview.js listens).
 * ════════════════════════════════════════════════════════════════ */

const $ = (id) => document.getElementById(id);

// ── Router + module config ─────────────────────────────────────────
const MODULES = {
    overview: null, // views/overview.js owns the route
    maintenance: {
        kind: 'maintenance',
        title: 'Maintenance — CMMS',
        sub: 'Asset registry · Work-order backlog · CET approvals',
    },
    scenarios: {
        kind: 'scenarios',
        title: 'Failure scenario simulator',
        sub: '10 critical scenarios with ODE-based 15-minute projections',
    },
    incidents: {
        kind: 'incidents',
        title: 'Incidents audit log',
        sub: 'All events from PostgreSQL - most recent first',
    },
    power: {
        kind: 'power',
        title: 'Power & UPS — Single-Line Diagram',
        sub: '2N · UPS Galaxy VX · RPP · Starline busway',
    },
    cooling: {
        kind: 'cooling',
        title: 'Cooling (DLC) — P&ID Live View',
        sub: 'DLC loop · Heat rejection · Power path with 2N failover',
    },
    mops: {
        kind: 'mops',
        title: 'MOPs / SOPs / EOPs Library',
        sub: 'Indexed procedures from the corpus + LLM generator for new MOPs',
    },
    morpheus: {
        kind: 'placeholder',
        title: 'Morpheus OT Security',
        sub: 'NVIDIA Morpheus - IEC 62443 cyber-physical correlation',
        icon: '⌂', // house (security)
        desc: 'NVIDIA Morpheus AI Sentinel monitors Modbus TCP and DNP3 traffic across IEC 62443 zones SL-0 to SL-3. Detects cyber-physical anomalies and triggers SOAR isolation on confidence >85% per SR 5.2.',
        chips: [
            'Explain IEC 62443 SL-2 zone isolation requirements.',
            'What Morpheus baseline Modbus log rate is normal?',
            'Walk me through SOAR isolation on chiller OT anomaly.',
        ],
    },
    gemini: {
        kind: 'placeholder',
        title: 'Gemini ER 1.6 Robot',
        sub: 'Autonomous inspection - thermographic imaging, moisture detection',
        icon: '⚫', // circle (robot)
        desc: 'NVIDIA Gemini ER 1.6 inspection robot. Performs scheduled thermographic rack scans, moisture detection on raised floor, cable management verification. Integrated via ROS2 with event-driven incident creation.',
        chips: [
            'What anomalies can Gemini ER 1.6 detect on Blackwell racks?',
            'Summarize robot IR thermography procedure for PDU inspection.',
            'How does ROS2 integration publish incidents to PostgreSQL?',
        ],
    },
    omniverse: {
        kind: 'placeholder',
        title: 'NVIDIA Omniverse',
        sub: 'Digital twin - physics-based facility visualization',
        icon: '◎', // bullseye
        desc: 'NVIDIA Omniverse digital twin of A3-Alpha Toronto Area. Live-link to real-time telemetry via USD / Kit. Visualizes thermal flow, power distribution, and fault propagation scenarios.',
        chips: [
            'Explain Omniverse Live-Link integration for EPMS.',
            'How does USD represent data center thermal zones?',
            'Walk me through a chillerFail scenario in the digital twin.',
        ],
    },
    topology: {
        kind: 'topology',
        title: 'Facility Topology (HLD/LLD)',
        sub: 'Live system-of-systems map with physics-driven node colouring',
    },
    bms: {
        kind: 'bms',
        title: 'BMS Connector',
        sub: 'BACnet/Modbus tag namespace — Niagara/EBI/EcoStruxure compatible',
    },
    site_topology: {
        kind: 'site_topology',
        title: 'Site Topology',
        sub: 'Physical hierarchy and 2N power chain analysis',
    },
    copilot: {
        kind: 'copilot',
        title: 'Facility Co-Pilot',
        sub: 'Tool-using LLM agent · Gemma 4 e2b · HITL drafts · NIST SP 800-82 audit',
    },
};

// ── Placeholder ("coming soon") stub renderer ──────────────────────
function renderPlaceholder(routeKey) {
    const cfg = MODULES[routeKey];
    if (!cfg || cfg.kind !== 'placeholder') return;
    $('ph-title').textContent = cfg.title;
    $('ph-sub').textContent = cfg.sub;
    $('ph-icon').textContent = cfg.icon;
    $('ph-desc').textContent = cfg.desc;
    const chipBox = $('ph-chips');
    chipBox.innerHTML = '';
    (cfg.chips || []).forEach((q) => {
        const c = document.createElement('div');
        c.className = 'chip';
        c.textContent = q;
        c.style.cursor = 'pointer';
        c.addEventListener('click', () => {
            // Jump to the Overview and ask the suggested query. The
            // Overview agent lives in views/overview.js now, so we
            // deep-link via a DOM event instead of a direct call.
            navigateTo('overview');
            document.dispatchEvent(new CustomEvent('epms:overview-ask', {
                detail: { query: q },
            }));
        });
        chipBox.appendChild(c);
    });
}

// ── Navigation ─────────────────────────────────────────────────────
function navigateTo(routeKey) {
    if (!routeKey) routeKey = 'overview';

    // T2.2: ES-module routes are owned by core/router.js. Delegate any
    // registered route to it and return. After T2.1 closed, this covers
    // every view except `maintenance` + the `placeholder` stubs.
    if (window.__epmsRouter && window.__epmsRouter.isRegistered(routeKey)) {
        window.__epmsRouter.navigateTo(routeKey);
        return;
    }

    // Update nav active state
    document.querySelectorAll('.nav-item').forEach((n) => {
        n.classList.toggle('active', n.dataset.route === routeKey);
    });

    // Hide all views
    document.querySelectorAll('.view').forEach((v) => v.setAttribute('hidden', ''));

    const cfg = MODULES[routeKey];
    if (routeKey === 'overview' || !cfg) {
        // Defensive fallback — views/overview.js normally registers the
        // 'overview' route, so this branch only fires if it failed to load.
        const ov = $('view-overview');
        if (ov) ov.removeAttribute('hidden');
    } else if (cfg.kind === 'maintenance') {
        // v0.10.12: hand control to the ES-module renderer. We unhide
        // here so the MutationObserver in views/maintenance.js picks it
        // up immediately (no flash of overview).
        const v = $('view-maintenance');
        if (v) v.removeAttribute('hidden');
    } else if (cfg.kind === 'placeholder') {
        const v = $('view-placeholder');
        if (v) v.removeAttribute('hidden');
        renderPlaceholder(routeKey);
    }
}

function setupRouter() {
    document.querySelectorAll('.nav-item').forEach((item) => {
        item.addEventListener('click', () => {
            const route = item.dataset.route;
            if (route) navigateTo(route);
        });
    });
}

/** Public entry — called once from main.js after all routes register. */
export function initBootstrap() {
    console.log(
        '%c DC-EPMS PRO v8.1.0 %c a3semi %c Modular HMI — T2.1 closed',
        'background:#00B8D4;color:#0B0D10;font-weight:700;padding:2px 6px;border-radius:2px;',
        'background:#1C2128;color:#00B8D4;padding:2px 6px;',
        'color:#9AA0A6;',
    );
    setupRouter();
    console.log('[bootstrap] router glue ready — app.js IIFE eradicated (T2.1 Vector 4c)');
}

// ─── Test surface ──────────────────────────────────────────────────
export const __bootstrap_test__ = {
    MODULES,
    navigateTo,
    renderPlaceholder,
    setupRouter,
};
