/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/scenarios.test.js
 * ROADMAP V11 T2.1 — verifies the first extracted IIFE view.
 *
 *   - services/api.js : fetch wrapper, error normalisation, endpoints.
 *   - views/scenarios.js : pure render helpers + XSS escaping.
 *
 * No browser, no backend: fetch is stubbed, the render helpers are
 * pure string functions exposed via __scenarios_test__.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { apiFetch, getScenarios, runScenario } from '/assets/js/services/api.js';
import { __scenarios_test__ } from '/assets/js/views/scenarios.js';

// Build a minimal fetch Response double.
function fakeResponse(body, { ok = true, status = 200, asText = false } = {}) {
    return {
        ok,
        status,
        json: async () => body,
        text: async () => (asText ? body : JSON.stringify(body)),
    };
}

// ════════════════════════════════════════════════════════════════
//  services/api.js
// ════════════════════════════════════════════════════════════════
describe('T2.1 — services/api.js', () => {
    afterEach(() => {
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
    });

    it('apiFetch resolves to the parsed JSON body on a 2xx response', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => fakeResponse({ ok: 1 })));
        await expect(apiFetch('/api/x')).resolves.toEqual({ ok: 1 });
    });

    it('apiFetch throws with the HTTP status on a non-2xx response', async () => {
        vi.stubGlobal('fetch', vi.fn(async () =>
            fakeResponse('internal boom', { ok: false, status: 500, asText: true })));
        await expect(apiFetch('/api/x')).rejects.toThrow(/HTTP 500/);
    });

    it('apiFetch throws a network error when fetch itself rejects', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
        await expect(apiFetch('/api/x')).rejects.toThrow(/network error/);
    });

    it('getScenarios returns the scenarios array', async () => {
        const spy = vi.fn(async () => fakeResponse({ scenarios: [{ id: 's1' }, { id: 's2' }] }));
        vi.stubGlobal('fetch', spy);
        const out = await getScenarios();
        expect(out).toHaveLength(2);
        expect(spy.mock.calls[0][0]).toBe('/api/scenarios');
    });

    it('getScenarios degrades to [] when the payload omits the key', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => fakeResponse({})));
        await expect(getScenarios()).resolves.toEqual([]);
    });

    it('runScenario POSTs to the run endpoint with the horizon query', async () => {
        const spy = vi.fn(async () => fakeResponse({ trajectory: [] }));
        vi.stubGlobal('fetch', spy);
        await runScenario('chiller-fail');
        expect(spy.mock.calls[0]).toEqual([
            '/api/scenarios/chiller-fail/run?horizon_s=900',
            { method: 'POST' },
        ]);
    });

    it('runScenario URL-encodes the scenario id', async () => {
        const spy = vi.fn(async () => fakeResponse({}));
        vi.stubGlobal('fetch', spy);
        await runScenario('a b/c');
        expect(spy.mock.calls[0][0]).toBe('/api/scenarios/a%20b%2Fc/run?horizon_s=900');
    });
});

// ════════════════════════════════════════════════════════════════
//  views/scenarios.js — pure render helpers
// ════════════════════════════════════════════════════════════════
describe('T2.1 — views/scenarios.js render helpers', () => {
    beforeEach(() => { __scenarios_test__.reset(); });

    it('escape() neutralises HTML metacharacters', () => {
        expect(__scenarios_test__.escape('<script>alert(1)</script>'))
            .toBe('&lt;script&gt;alert(1)&lt;/script&gt;');
        expect(__scenarios_test__.escape(null)).toBe('');
        expect(__scenarios_test__.escape(undefined)).toBe('');
    });

    it('modIcon() maps known physics modules and falls back', () => {
        expect(__scenarios_test__.modIcon('electrical')).toBe('⚡');
        expect(__scenarios_test__.modIcon('it_thermal')).toBe('🌡');
        expect(__scenarios_test__.modIcon('nonsense')).toBe('◌');
    });

    it('sevClass() prefixes the severity and defaults to info', () => {
        expect(__scenarios_test__.sevClass('critical')).toBe('sev-critical');
        expect(__scenarios_test__.sevClass(undefined)).toBe('sev-info');
    });

    it('scenarioCardHtml() renders id + severity and escapes a hostile name', () => {
        const html = __scenarios_test__.scenarioCardHtml({
            id: 'scn-1',
            name: '<img src=x onerror=alert(1)>',
            primary_module: 'electrical',
            severity_if_uncorrected: 'critical',
            expected_ttr_minutes: 12,
        });
        expect(html).toContain('data-id="scn-1"');
        expect(html).toContain('sev-critical');
        // the XSS payload must be escaped, never emitted as a live tag
        expect(html).not.toContain('<img src=x');
        expect(html).toContain('&lt;img src=x');
    });

    it('pickDatasets() selects the it_thermal metric pair', () => {
        const ds = __scenarios_test__.pickDatasets({
            module: 'it_thermal',
            trajectory: [{ t: 0, state: { hall_air_c: 22, gpu_tj_estimate_c: 60 } }],
        });
        expect(ds).toHaveLength(2);
        expect(ds.map(d => d.label)).toEqual(['Hall air (°C)', 'GPU Tj est. (°C)']);
        expect(ds[0].data).toEqual([22]);
    });

    it('pickDatasets() returns [] for an unknown module', () => {
        expect(__scenarios_test__.pickDatasets({ module: 'mystery', trajectory: [] }))
            .toEqual([]);
    });

    it('the scenario cache round-trips through the test surface', () => {
        expect(__scenarios_test__.getCache()).toBeNull();
        __scenarios_test__.setCache([{ id: 'a' }]);
        expect(__scenarios_test__.getCache()).toEqual([{ id: 'a' }]);
        __scenarios_test__.reset();
        expect(__scenarios_test__.getCache()).toBeNull();
    });
});
