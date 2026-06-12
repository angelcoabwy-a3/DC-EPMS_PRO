/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/overview.test.js
 * ROADMAP V11 T2.1 Vector 4b — verifies the extracted Overview view.
 *
 * The Overview is the final view out of the IIFE monolith. Behaviour-
 * preserving smoke test: KPI binding, the incident strip (+ hostile
 * title escaping), the SHI panel, severity-class mapping, and that
 * initOverviewView() registers the 'overview' route. No browser, no
 * backend.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';

import { __overview_test__ } from '/assets/js/views/overview.js';
import { isRegistered } from '/assets/js/core/router.js';

const { updateKPIs, renderIncidents, renderSiteHealth, severityClass,
    initOverviewView, setIncidents, reset } = __overview_test__;

// DC-EPMS-TEST-01: initOverviewView() fires the initial poll cycle
// (health / telemetry / incidents / SHI). Unstubbed, those relative
// fetches hit happy-dom's default origin (:3000) and leak unhandled
// ECONNREFUSED rejections when this file runs in isolation. Every
// fetcher bails cleanly on a non-ok response, so a blanket ok:false
// stub keeps the view code on its no-op paths.
beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
        ok: false, status: 503, json: async () => ({}),
    })));
});

afterEach(() => {
    reset();
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
});

describe('T2.1 Vector 4b — views/overview.js KPIs + severity', () => {
    it('severityClass maps backend severities to CSS classes', () => {
        expect(severityClass('critical')).toBe('sev-critical');
        expect(severityClass('warning')).toBe('sev-warning');
        expect(severityClass(null)).toBe('sev-ok');
    });

    it('updateKPIs binds the telemetry KPI cards with threshold classes', () => {
        document.body.innerHTML = `
            <div id="kpi-pue"></div><div id="kpi-temp"></div>
            <div id="kpi-load"></div><div id="kpi-racks"></div>`;
        updateKPIs({ pue: 1.45, hall_temp_c: 36, it_load_kw: 5000, rack_count: 118, rack_tdp_kw: 142 });
        expect(document.getElementById('kpi-pue').textContent).toBe('1.450');
        expect(document.getElementById('kpi-pue').className).toContain('crit');
        expect(document.getElementById('kpi-racks').textContent).toBe('118 × 142kW');
    });
});

describe('T2.1 Vector 4b — views/overview.js incident strip', () => {
    it('renders incident rows and escapes a hostile incident title (XSS)', () => {
        document.body.innerHTML = '<div id="incident-list"></div>';
        setIncidents([
            { severity: 'critical', ts: '2026-05-19T10:00:00', title: 'Chiller-1 trip', status: 'open' },
            { severity: 'info', ts: '2026-05-19T09:00:00', title: '<img src=x onerror=alert(1)>', status: 'closed' },
        ]);
        renderIncidents();
        const list = document.getElementById('incident-list');
        expect(list.querySelectorAll('.incident-row')).toHaveLength(2);
        expect(list.querySelector('img')).toBeNull();
        expect(list.textContent).toContain('<img src=x onerror=alert(1)>');
    });

    it('shows the empty state when there are no incidents', () => {
        document.body.innerHTML = '<div id="incident-list"></div>';
        setIncidents([]);
        renderIncidents();
        expect(document.getElementById('incident-list').textContent).toContain('No incidents');
    });
});

describe('T2.1 Vector 4b — views/overview.js SHI panel + routing', () => {
    it('renderSiteHealth binds the Site Health Index value + bar', () => {
        document.body.innerHTML = `
            <div id="shi-value"></div>
            <div id="shi-bar"></div>
            <div id="shi-dot"></div>
            <div id="shi-weakest"></div>
            <div id="shi-cascades"></div>`;
        renderSiteHealth({
            site_health: 0.91, overall_severity: 'ok', weakest_module: 'heat_rejection',
            cascade_count: 0, module_healths: {}, module_severities: {},
        });
        expect(document.getElementById('shi-value').textContent).toBe('0.91');
        expect(document.getElementById('shi-bar').style.width).toBe('91%');
        expect(document.getElementById('shi-weakest').textContent).toBe('heat_rejection');
    });

    it('initOverviewView registers the overview route on core/router.js', () => {
        document.body.innerHTML = '<div id="view-overview"></div>';
        initOverviewView();
        expect(isRegistered('overview')).toBe(true);
    });
});
