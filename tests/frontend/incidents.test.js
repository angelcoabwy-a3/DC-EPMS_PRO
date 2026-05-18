/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/incidents.test.js
 * ROADMAP V11 T2.1 — verifies the Incidents view extracted from app.js.
 *
 *   - services/api.js  : getIncidents() endpoint + degradation.
 *   - views/incidents.js : pure render helpers, KPI math, XSS escaping,
 *     and the DOM render against a happy-dom #view-incidents fixture.
 *
 * No browser, no backend: fetch is stubbed, helpers are pure functions
 * exposed via __incidents_test__.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, vi, afterEach } from 'vitest';

import { getIncidents } from '/assets/js/services/api.js';
import { __incidents_test__ } from '/assets/js/views/incidents.js';

const { escape, severityClass, fmtTime, computeKpis, incidentRowHtml, render } =
    __incidents_test__;

function fakeResponse(body, { ok = true, status = 200 } = {}) {
    return {
        ok,
        status,
        json: async () => body,
        text: async () => JSON.stringify(body),
    };
}

// ════════════════════════════════════════════════════════════════
//  services/api.js — getIncidents
// ════════════════════════════════════════════════════════════════
describe('T2.1 — services/api.js getIncidents()', () => {
    afterEach(() => {
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
    });

    it('resolves to the rows array on a 2xx response', async () => {
        vi.stubGlobal('fetch', vi.fn(async () =>
            fakeResponse({ rows: [{ incident_id: 'INC-1' }] })));
        await expect(getIncidents()).resolves.toEqual([{ incident_id: 'INC-1' }]);
    });

    it('degrades to [] when the payload omits the rows key', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => fakeResponse({})));
        await expect(getIncidents()).resolves.toEqual([]);
    });

    it('passes the limit through as a query parameter', async () => {
        const spy = vi.fn(async () => fakeResponse({ rows: [] }));
        vi.stubGlobal('fetch', spy);
        await getIncidents(17);
        expect(spy).toHaveBeenCalledWith('/api/incidents?limit=17', undefined);
    });

    it('throws with the HTTP status on a non-2xx response', async () => {
        vi.stubGlobal('fetch', vi.fn(async () =>
            fakeResponse('boom', { ok: false, status: 500 })));
        await expect(getIncidents()).rejects.toThrow(/HTTP 500/);
    });
});

// ════════════════════════════════════════════════════════════════
//  views/incidents.js — pure helpers
// ════════════════════════════════════════════════════════════════
describe('T2.1 — views/incidents.js pure helpers', () => {
    it('escape neutralizes HTML metacharacters', () => {
        expect(escape('<b>&"\'</b>')).toBe('&lt;b&gt;&amp;&quot;&#39;&lt;/b&gt;');
        expect(escape(null)).toBe('');
        expect(escape(undefined)).toBe('');
    });

    it('severityClass maps every severity spelling to a CSS class', () => {
        expect(severityClass('critical')).toBe('crit');
        expect(severityClass('crit')).toBe('crit');
        expect(severityClass('WARNING')).toBe('warn');
        expect(severityClass('warn')).toBe('warn');
        expect(severityClass('info')).toBe('info');
        expect(severityClass('')).toBe('info');
        expect(severityClass(null)).toBe('info');
    });

    it('fmtTime returns an em-dash for a falsy timestamp', () => {
        expect(fmtTime(null)).toBe('—');
        expect(fmtTime('')).toBe('—');
    });

    it('fmtTime renders a numeric clock string for a real ISO timestamp', () => {
        const out = fmtTime('2026-05-17T14:30:00Z');
        expect(out).not.toBe('—');
        expect(/\d/.test(out)).toBe(true);
    });

    it('computeKpis counts total / critical / warning / open', () => {
        const rows = [
            { severity: 'critical', status: 'OPEN' },
            { severity: 'crit', status: 'closed' },
            { severity: 'warning', status: 'OPEN' },
            { severity: 'info', status: 'OPEN' },
        ];
        expect(computeKpis(rows)).toEqual({ total: 4, crit: 2, warn: 1, open: 3 });
    });

    it('computeKpis is safe on a non-array argument', () => {
        expect(computeKpis(undefined)).toEqual({ total: 0, crit: 0, warn: 0, open: 0 });
    });

    it('incidentRowHtml carries the id, severity class and status', () => {
        const html = incidentRowHtml({
            incident_id: 'INC-42', severity: 'critical',
            source: 'PUE', title: 'PUE breach', status: 'OPEN',
        });
        expect(html).toContain('INC-42');
        expect(html).toContain('inc-table-row crit');
        expect(html).toContain('OPEN');
        expect(html).toContain('CRIT');
    });

    it('incidentRowHtml escapes an XSS payload in every field', () => {
        const html = incidentRowHtml({
            incident_id: '<script>alert(1)</script>',
            severity: 'info',
            source: 'a&b',
            title: '<img src=x onerror=alert(2)>',
            status: 'OPEN',
        });
        expect(html).not.toContain('<script>');
        expect(html).not.toContain('<img src=x');
        expect(html).toContain('&lt;script&gt;');
        expect(html).toContain('a&amp;b');
    });
});

// ════════════════════════════════════════════════════════════════
//  views/incidents.js — DOM render against a happy-dom fixture
// ════════════════════════════════════════════════════════════════
describe('T2.1 — views/incidents.js _render()', () => {
    function mountFixture() {
        document.body.innerHTML = `
            <div class="view" id="view-incidents">
                <div class="value" id="inc-total">0</div>
                <div class="value" id="inc-crit">0</div>
                <div class="value" id="inc-warn">0</div>
                <div class="value" id="inc-open">0</div>
                <div id="inc-table"></div>
            </div>`;
    }

    afterEach(() => {
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
        document.body.innerHTML = '';
    });

    it('populates the KPI tiles and the table from the API rows', async () => {
        mountFixture();
        vi.stubGlobal('fetch', vi.fn(async () => fakeResponse({
            rows: [
                { incident_id: 'INC-1', severity: 'critical', status: 'OPEN', title: 't1' },
                { incident_id: 'INC-2', severity: 'info', status: 'closed', title: 't2' },
            ],
        })));
        await render();
        expect(document.getElementById('inc-total').textContent).toBe('2');
        expect(document.getElementById('inc-crit').textContent).toBe('1');
        expect(document.getElementById('inc-open').textContent).toBe('1');
        expect(document.getElementById('inc-table').innerHTML).toContain('INC-1');
        expect(document.getElementById('inc-table').innerHTML).toContain('inc-table-row');
    });

    it('shows the empty-state message when there are no incidents', async () => {
        mountFixture();
        vi.stubGlobal('fetch', vi.fn(async () => fakeResponse({ rows: [] })));
        await render();
        expect(document.getElementById('inc-table').innerHTML).toContain('No incidents recorded');
        expect(document.getElementById('inc-total').textContent).toBe('0');
    });

    it('renders a degraded state when the fetch fails', async () => {
        mountFixture();
        vi.stubGlobal('fetch', vi.fn(async () =>
            fakeResponse('db down', { ok: false, status: 503 })));
        await render();
        expect(document.getElementById('inc-table').innerHTML).toContain('Failed to load incidents');
    });
});
