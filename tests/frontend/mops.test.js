/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/mops.test.js
 * ROADMAP V11 T2.1 — verifies the MOPs view extracted from app.js.
 *
 *   - services/api.js  : getMops / getMop / generateMop endpoints.
 *   - views/mops.js    : pure render + markdown helpers, XSS escaping,
 *     and the list render against a happy-dom #view-mops fixture.
 *
 * No browser, no backend: fetch is stubbed, helpers are pure functions
 * exposed via __mops_test__.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, vi, afterEach } from 'vitest';

import { getMops, getMop, generateMop } from '/assets/js/services/api.js';
import { __mops_test__ } from '/assets/js/views/mops.js';

const { markdownLite, mopCardHtml, renderList, reset } = __mops_test__;

function fakeResponse(body, { ok = true, status = 200 } = {}) {
    return {
        ok,
        status,
        json: async () => body,
        text: async () => JSON.stringify(body),
    };
}

// ════════════════════════════════════════════════════════════════
//  services/api.js — MOP endpoints
// ════════════════════════════════════════════════════════════════
describe('T2.1 — services/api.js MOP endpoints', () => {
    afterEach(() => {
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
    });

    it('getMops resolves to the library payload object', async () => {
        vi.stubGlobal('fetch', vi.fn(async () =>
            fakeResponse({ mops: [{ doc_id: 'M-1' }], count: 1, by_type: { MOP: 1 } })));
        const d = await getMops();
        expect(d.count).toBe(1);
        expect(d.mops[0].doc_id).toBe('M-1');
    });

    it('getMop URL-encodes the doc id', async () => {
        const spy = vi.fn(async () => fakeResponse({ doc_id: 'a/b' }));
        vi.stubGlobal('fetch', spy);
        await getMop('a/b');
        expect(spy).toHaveBeenCalledWith('/api/mops/a%2Fb', undefined);
    });

    it('generateMop POSTs the spec as a JSON body', async () => {
        const spy = vi.fn(async () => fakeResponse({ topic: 't', steps: [] }));
        vi.stubGlobal('fetch', spy);
        await generateMop({ topic: 't', doc_type: 'MOP', equipment: 'e', duration: 'd' });
        expect(spy).toHaveBeenCalledTimes(1);
        const [path, opts] = spy.mock.calls[0];
        expect(path).toBe('/api/mops/generate');
        expect(opts.method).toBe('POST');
        expect(JSON.parse(opts.body)).toEqual({
            topic: 't', doc_type: 'MOP', equipment: 'e', duration: 'd',
        });
    });

    it('generateMop throws with the HTTP status on a non-2xx response', async () => {
        vi.stubGlobal('fetch', vi.fn(async () =>
            fakeResponse('llm timeout', { ok: false, status: 502 })));
        await expect(generateMop({ topic: 't' })).rejects.toThrow(/HTTP 502/);
    });
});

// ════════════════════════════════════════════════════════════════
//  views/mops.js — pure helpers
// ════════════════════════════════════════════════════════════════
describe('T2.1 — views/mops.js pure helpers', () => {
    it('markdownLite renders bold, italic, code and line breaks', () => {
        const h = markdownLite('a **b** c `d` e *f*\nline2');
        expect(h).toContain('<strong>b</strong>');
        expect(h).toContain('<code>d</code>');
        expect(h).toContain('<em>f</em>');
        expect(h).toContain('<br>');
    });

    it('markdownLite escapes HTML before applying markdown (XSS-safe)', () => {
        const h = markdownLite('<script>alert(1)</script> **ok**');
        expect(h).not.toContain('<script>');
        expect(h).toContain('&lt;script&gt;');
        expect(h).toContain('<strong>ok</strong>');
    });

    it('markdownLite returns empty string for a falsy input', () => {
        expect(markdownLite('')).toBe('');
        expect(markdownLite(null)).toBe('');
        expect(markdownLite(undefined)).toBe('');
    });

    it('mopCardHtml carries the doc id, title and type badge', () => {
        const html = mopCardHtml({
            doc_id: 'MOP-CHI-001', doc_type: 'MOP',
            title: 'Chiller PM', equipment: 'York YZ', duration: '6h',
        });
        expect(html).toContain('MOP-CHI-001');
        expect(html).toContain('Chiller PM');
        expect(html).toContain('mop-card');
        expect(html).toContain('data-id="MOP-CHI-001"');
    });

    it('mopCardHtml flags an EOP with the critical severity class', () => {
        const html = mopCardHtml({ doc_id: 'EOP-1', doc_type: 'EOP', title: 'Emergency' });
        expect(html).toContain('mop-type sev-critical');
        expect(html).toContain('EOP');
    });

    it('mopCardHtml escapes an XSS payload in the title and id', () => {
        const html = mopCardHtml({
            doc_id: '<img src=x onerror=alert(1)>',
            doc_type: 'MOP',
            title: '<script>steal()</script>',
        });
        expect(html).not.toContain('<script>steal');
        expect(html).not.toContain('<img src=x');
        expect(html).toContain('&lt;script&gt;');
    });
});

// ════════════════════════════════════════════════════════════════
//  views/mops.js — _renderList against a happy-dom fixture
// ════════════════════════════════════════════════════════════════
describe('T2.1 — views/mops.js _renderList()', () => {
    function mountFixture() {
        document.body.innerHTML = `
            <div class="view" id="view-mops">
                <span id="mops-meta"></span>
                <div id="mops-list"></div>
                <div id="mops-detail"></div>
            </div>`;
    }

    afterEach(() => {
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
        document.body.innerHTML = '';
        reset();
    });

    it('populates the list and the meta line from the API payload', async () => {
        mountFixture();
        vi.stubGlobal('fetch', vi.fn(async () => fakeResponse({
            mops: [
                { doc_id: 'MOP-1', doc_type: 'MOP', title: 'Proc one' },
                { doc_id: 'EOP-9', doc_type: 'EOP', title: 'Proc two' },
            ],
            count: 2,
            by_type: { MOP: 1, EOP: 1 },
        })));
        await renderList();
        expect(document.getElementById('mops-list').innerHTML).toContain('MOP-1');
        expect(document.getElementById('mops-list').innerHTML).toContain('mop-card');
        expect(document.getElementById('mops-meta').textContent).toContain('2 procedures indexed');
    });

    it('shows the empty-state message when the corpus has no procedures', async () => {
        mountFixture();
        vi.stubGlobal('fetch', vi.fn(async () =>
            fakeResponse({ mops: [], count: 0, by_type: {} })));
        await renderList();
        expect(document.getElementById('mops-list').innerHTML).toContain('No procedures found');
    });

    it('renders a degraded state when the fetch fails', async () => {
        mountFixture();
        vi.stubGlobal('fetch', vi.fn(async () =>
            fakeResponse('corpus down', { ok: false, status: 500 })));
        await renderList();
        expect(document.getElementById('mops-list').innerHTML).toContain('Failed to load');
    });
});
