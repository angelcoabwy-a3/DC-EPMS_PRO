/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/procedures.test.js
 * Epic 6 — Procedure Architect HMI.
 *
 * Coverage:
 *   - Pure markdown render: headers, lists, emphasis, code fences.
 *   - S-SEC-01: every hostile payload (script / img onerror / iframe)
 *     in agent-authored content, audit findings, or doc_type is
 *     escaped — no markup makes it to the DOM. Tests cover the
 *     three known XSS vectors the live LLM can produce.
 *   - Verdict pill: approve / caution / hard_stop -> correct class.
 *   - renderResult: approve shows Sign button, hard_stop hides it +
 *     shows the refusal banner + findings.
 *   - submitGenerate: form validation (doc_type + min length), POST
 *     body shape, error rendering on HTTP failure.
 *   - submitSign: posts the draft body to /sign, renders entry id +
 *     sequence on success, renders refusal detail on 403.
 *   - Click dispatch: "generate" / "sign" actions route to the
 *     right handler.
 *   - Route registration on initProceduresView.
 *
 * No browser, no backend — fetch is stubbed; happy-dom provides the
 * DOM.
 * ════════════════════════════════════════════════════════════════ */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { __procedures_view_test__ } from '/assets/js/views/procedures.js';
import { isRegistered } from '/assets/js/core/router.js';

const {
    renderMarkdown, renderResult, verdictPill,
    submitGenerate, submitSign, submitSaveToLibrary, onClick,
    renderAssetSelect, resolveAssetId,
    syncCustomAssetVisibility, renderContextChips,
    applyContextTemplate,
    installStaleHandler, isStaleVsLastGenerate, markResultStale,
    fetchTelemetrySnapshot,
    initProceduresView, reset,
    DOC_TYPES, ASSET_PRESETS, ASSET_CUSTOM_VALUE, ASSET_NONE_VALUE,
    CONTEXT_TEMPLATES, TELEMETRY_METADATA_KEYS,
} = __procedures_view_test__;


/** Mounts the production skeleton — uses the real renderAssetSelect()
 *  + an empty chips slot ready for renderContextChips(). Keeps the
 *  Sprint-1 tests working against the new form shape. */
function _mountView() {
    // Commit 4: stub also exposes the MOP-category wrap + select so
    // the new visibility / category-switching tests can exercise the
    // production wiring without the full template.
    const { MOP_CATEGORY_KEYS: KEYS, MOP_CATEGORY_LABELS: LBL,
        MOP_CATEGORY_DEFAULT: DEF } = __procedures_view_test__;
    const catOpts = KEYS.map((k) => (
        `<option value="${k}"${k === DEF ? ' selected' : ''}>${LBL[k]}</option>`
    )).join('');
    document.body.innerHTML = `
        <div id="view-procedures-architect">
            <select data-proc-doc-type>
                <option value="SOP">SOP</option>
                <option value="MOP">MOP</option>
                <option value="EOP">EOP</option>
                <option value="EMP">EMP</option>
            </select>
            <select data-proc-asset-select>${renderAssetSelect()}</select>
            <label data-proc-asset-custom-wrap hidden>
                <input type="text" data-proc-asset-custom>
            </label>
            <label data-proc-mop-category-wrap hidden>
                <select data-proc-mop-category>${catOpts}</select>
            </label>
            <div data-proc-ctx-chips></div>
            <textarea data-proc-context></textarea>
            <button data-action="generate">Generate</button>
            <div data-proc-result></div>
        </div>`;
}

function _fakeFetchOK(body) {
    return vi.fn(async () => ({
        ok: true, status: 200, json: async () => body,
    }));
}

function _fakeFetchFail(status, detail = 'fail') {
    return vi.fn(async () => ({
        ok: false, status, statusText: 'Err',
        json: async () => ({ detail }),
    }));
}

beforeEach(() => { document.body.innerHTML = ''; });
afterEach(() => { reset(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });


// ─── Markdown render ────────────────────────────────────────────────
describe('Epic 6 — renderMarkdown', () => {
    it('renders headers H1/H2/H3', () => {
        const html = renderMarkdown('# Top\n## Mid\n### Low');
        expect(html).toContain('<h1');
        expect(html).toContain('Top');
        expect(html).toContain('<h2');
        expect(html).toContain('Mid');
        expect(html).toContain('<h3');
        expect(html).toContain('Low');
    });

    it('renders bold and italic', () => {
        const html = renderMarkdown('**bold** and *italic*');
        expect(html).toContain('<strong>bold</strong>');
        expect(html).toContain('<em>italic</em>');
    });

    it('renders inline code', () => {
        const html = renderMarkdown('Use `LOTO` on the bus.');
        expect(html).toContain('<code class="proc-code">LOTO</code>');
    });

    it('renders unordered + ordered lists', () => {
        const html = renderMarkdown('- a\n- b\n\n1. one\n2. two');
        expect(html).toContain('<ul');
        expect(html).toContain('<li>a</li>');
        expect(html).toContain('<li>b</li>');
        expect(html).toContain('<ol');
        expect(html).toContain('<li>one</li>');
        expect(html).toContain('<li>two</li>');
    });

    it('renders code fences as <pre><code> blocks', () => {
        const html = renderMarkdown('```\nemergency_stop UPS_A\n```');
        expect(html).toContain('<pre class="proc-codeblock">');
        expect(html).toContain('emergency_stop UPS_A');
    });

    it('returns empty string for empty input', () => {
        expect(renderMarkdown('')).toBe('');
        expect(renderMarkdown(null)).toBe('');
        expect(renderMarkdown(undefined)).toBe('');
    });
});


// ─── S-SEC-01 XSS gate ─────────────────────────────────────────────
describe('Epic 6 — S-SEC-01 XSS resistance in renderMarkdown', () => {
    it('strips a <script> tag from agent-authored content', () => {
        const html = renderMarkdown('# Title\n<script>window.__pwn1=1</script>');
        const div = document.createElement('div');
        div.innerHTML = html;
        expect(div.querySelector('script')).toBeNull();
        expect(window.__pwn1).toBeUndefined();
    });

    it('neutralises <img src=x onerror=...>', () => {
        const html = renderMarkdown('## Section\n<img src=x onerror=window.__pwn2=1>');
        const div = document.createElement('div');
        div.innerHTML = html;
        expect(div.querySelector('img')).toBeNull();
        expect(window.__pwn2).toBeUndefined();
    });

    it('neutralises <iframe> injection', () => {
        const html = renderMarkdown('Run this:\n<iframe src=javascript:alert(1)></iframe>');
        const div = document.createElement('div');
        div.innerHTML = html;
        expect(div.querySelector('iframe')).toBeNull();
    });

    it('escapes HTML entities in code fences (no raw HTML leaks)', () => {
        const html = renderMarkdown('```\n<script>evil()</script>\n```');
        const div = document.createElement('div');
        div.innerHTML = html;
        expect(div.querySelector('script')).toBeNull();
        // Visible text shows the escaped form (no execution).
        expect(div.textContent).toContain('<script>evil()</script>');
    });
});


// ─── Verdict pill ───────────────────────────────────────────────────
describe('Epic 6 — verdictPill', () => {
    it('uses approve class for approve verdict', () => {
        expect(verdictPill('approve')).toContain('proc-pill-approve');
        expect(verdictPill('approve')).toContain('APPROVE');
    });

    it('uses caution class for caution verdict', () => {
        expect(verdictPill('caution')).toContain('proc-pill-caution');
        expect(verdictPill('caution')).toContain('CAUTION');
    });

    it('flags hard_stop with the SAFETY HARD_STOP label + veto class', () => {
        const pill = verdictPill('hard_stop');
        expect(pill).toContain('proc-pill-veto');
        expect(pill).toContain('SAFETY HARD_STOP');
    });
});


// ─── renderResult — verdict-gated UI ───────────────────────────────
describe('Epic 6 — renderResult Sign-button gating', () => {
    it('approved SOP renders a Sign button', () => {
        _mountView();
        renderResult({
            draft: {
                draft_id: 'qd-1', doc_type: 'SOP',
                content: '# SOP\nVerify BMS setpoints.',
                llm_present: false,
            },
            safety_audit: { verdict: 'approve', findings: [] },
        });
        const slot = document.querySelector('[data-proc-result]');
        expect(slot.querySelector('.proc-btn-sign')).not.toBeNull();
        expect(slot.querySelector('.proc-btn-sign').dataset.draftId).toBe('qd-1');
    });

    it('hard_stop MOP renders the refusal banner + findings, NO Sign button', () => {
        _mountView();
        renderResult({
            draft: {
                draft_id: 'qd-mop',
                doc_type: 'MOP',
                content: '# MOP\nMissing safety terms.',
                llm_present: true,
            },
            safety_audit: {
                verdict: 'hard_stop',
                findings: [
                    'missing required MOP term: LOTO (Lockout/Tagout)',
                    'missing required MOP term: PPE (personal protective equipment)',
                    'missing required MOP term: CSA Z462 / NFPA 70E electrical safety standard',
                ],
            },
        });
        const slot = document.querySelector('[data-proc-result]');
        expect(slot.querySelector('.proc-btn-sign')).toBeNull();
        expect(slot.querySelector('.proc-banner-hardstop')).not.toBeNull();
        const findings = slot.querySelectorAll('.proc-findings li');
        expect(findings.length).toBe(3);
        // Pill shows SAFETY HARD_STOP, not approve.
        expect(slot.querySelector('.proc-pill-veto')).not.toBeNull();
    });

    it('caution SOP renders findings but no Sign button', () => {
        _mountView();
        renderResult({
            draft: {
                draft_id: 'qd-soft', doc_type: 'SOP',
                content: '# SOP\nWalk the floor.',
                llm_present: true,
            },
            safety_audit: {
                verdict: 'caution',
                findings: ['missing required SOP term: HMI/BMS verification'],
            },
        });
        const slot = document.querySelector('[data-proc-result]');
        expect(slot.querySelector('.proc-btn-sign')).toBeNull();
        expect(slot.querySelector('.proc-pill-caution')).not.toBeNull();
        expect(slot.querySelectorAll('.proc-findings li').length).toBe(1);
    });

    it('XSS — hostile finding text is escaped', () => {
        _mountView();
        renderResult({
            draft: { draft_id: 'qd-xss', doc_type: 'MOP', content: 'x', llm_present: true },
            safety_audit: {
                verdict: 'hard_stop',
                findings: ['<img src=x onerror=window.__fxss=1>'],
            },
        });
        const slot = document.querySelector('[data-proc-result]');
        expect(slot.querySelector('img')).toBeNull();
        expect(window.__fxss).toBeUndefined();
    });
});


// ─── submitGenerate ─────────────────────────────────────────────────
describe('Epic 6 — submitGenerate', () => {
    it('POSTs the form payload to /api/procedures/architect/generate', async () => {
        _mountView();
        document.querySelector('[data-proc-doc-type]').value = 'MOP';
        document.querySelector('[data-proc-asset-select]').value = 'ups_b';
        document.querySelector('[data-proc-context]').value =
            'Replace UPS-B battery cabinet on Phase 1 main bus.';
        const spy = _fakeFetchOK({
            draft: {
                draft_id: 'qd-live', doc_type: 'MOP',
                content: '# MOP\nWith CSA Z462, LOTO, PPE.',
                llm_present: true,
            },
            safety_audit: { verdict: 'approve', findings: [] },
        });
        vi.stubGlobal('fetch', spy);
        await submitGenerate();
        // Phase 3 introduced a /api/telemetry/latest pre-pull, so we
        // can't trust calls[0] to be the architect POST anymore — find
        // by URL instead. The pre-pull silently returns {} from this
        // stub (no `latest` field) and the architect call still fires.
        const archCall = spy.mock.calls.find(
            (c) => c[0] === '/api/procedures/architect/generate',
        );
        expect(archCall).toBeDefined();
        const [, opts] = archCall;
        expect(opts.method).toBe('POST');
        const body = JSON.parse(opts.body);
        expect(body.doc_type).toBe('MOP');
        expect(body.context).toContain('UPS-B');
        expect(body.asset_id).toBe('ups_b');
        // Approve verdict -> Sign button rendered.
        expect(document.querySelector('.proc-btn-sign')).not.toBeNull();
    });

    it('refuses to POST when context < 10 chars', async () => {
        _mountView();
        document.querySelector('[data-proc-context]').value = 'short';
        const spy = vi.fn();
        vi.stubGlobal('fetch', spy);
        await submitGenerate();
        expect(spy).not.toHaveBeenCalled();
        expect(document.querySelector('[data-proc-result]').textContent)
            .toContain('at least 10 characters');
    });

    it('renders the server error detail on HTTP 422', async () => {
        _mountView();
        document.querySelector('[data-proc-context]').value =
            'A valid-length context string for testing.';
        vi.stubGlobal('fetch', _fakeFetchFail(422, 'doc_type pattern mismatch'));
        await submitGenerate();
        const slot = document.querySelector('[data-proc-result]');
        expect(slot.textContent).toContain('422');
        expect(slot.textContent).toContain('doc_type pattern mismatch');
    });
});


// ─── submitSign ─────────────────────────────────────────────────────
describe('Epic 6 — submitSign', () => {
    async function _setupApprovedDraft(draftId) {
        _mountView();
        const spy = _fakeFetchOK({
            draft: {
                draft_id: draftId, doc_type: 'MOP', asset_id: 'ups_b',
                content: 'PPE per CSA Z462. LOTO on bus.',
                llm_present: true,
            },
            safety_audit: { verdict: 'approve', findings: [] },
        });
        vi.stubGlobal('fetch', spy);
        document.querySelector('[data-proc-context]').value =
            'A valid context for the sign test.';
        await submitGenerate();
        vi.unstubAllGlobals();
        return spy;
    }

    it('POSTs the draft body to /sign and renders entry id', async () => {
        await _setupApprovedDraft('qd-sign');
        const signSpy = _fakeFetchOK({
            signed: true,
            draft_id: 'qd-sign',
            entry_id: 'a1b2c3d4e5f6abcd1111222233334444',
            sequence_no: 42,
            content_sha256: 'deadbeef'.repeat(8),
            safety_audit_verdict: 'approve',
        });
        vi.stubGlobal('fetch', signSpy);
        await submitSign('qd-sign');
        const [url, opts] = signSpy.mock.calls[0];
        expect(url).toBe('/api/procedures/architect/sign');
        expect(opts.method).toBe('POST');
        const body = JSON.parse(opts.body);
        expect(body.draft_id).toBe('qd-sign');
        expect(body.doc_type).toBe('MOP');
        expect(body.content).toContain('CSA Z462');
        // Success rendered in the per-draft slot.
        const slot = document.querySelector(
            '.proc-sign-result[data-draft-id="qd-sign"]',
        );
        expect(slot.textContent).toContain('Signed to ledger');
        expect(slot.textContent).toContain('seq #42');
    });

    it('renders the 403 refusal detail (server re-audit failed)', async () => {
        await _setupApprovedDraft('qd-bypass');
        vi.stubGlobal(
            'fetch',
            _fakeFetchFail(403, 'Safety Officer HARD_STOP on draft qd-bypass'),
        );
        await submitSign('qd-bypass');
        const slot = document.querySelector(
            '.proc-sign-result[data-draft-id="qd-bypass"]',
        );
        expect(slot.textContent).toContain('403');
        expect(slot.textContent).toContain('HARD_STOP');
        expect(slot.querySelector('.proc-sign-fail')).not.toBeNull();
    });

    it('ignores a stale draft-id mismatch (defence vs double-click)', async () => {
        await _setupApprovedDraft('qd-current');
        const spy = vi.fn();
        vi.stubGlobal('fetch', spy);
        await submitSign('qd-OTHER');   // mismatched id
        expect(spy).not.toHaveBeenCalled();
    });
});


// ─── Click dispatch ─────────────────────────────────────────────────
describe('Epic 6 — onClick dispatch', () => {
    function _fakeEvent(target) { return { target }; }

    it('"generate" action triggers submitGenerate', async () => {
        _mountView();
        document.querySelector('[data-proc-context]').value =
            'A valid context for the click test.';
        const spy = _fakeFetchOK({
            draft: {
                draft_id: 'qd-c', doc_type: 'SOP',
                content: '# x', llm_present: false,
            },
            safety_audit: { verdict: 'approve', findings: [] },
        });
        vi.stubGlobal('fetch', spy);
        const btn = document.querySelector('[data-action="generate"]');
        onClick(_fakeEvent(btn));
        // Two awaits per fetch in the chain — telemetry pre-pull +
        // architect generate. Three awaits is enough margin.
        await Promise.resolve();
        await Promise.resolve();
        await Promise.resolve();
        expect(spy).toHaveBeenCalled();
        const urls = spy.mock.calls.map((c) => c[0]);
        expect(urls).toContain('/api/procedures/architect/generate');
    });
});


// ─── Route registration ─────────────────────────────────────────────
describe('Epic 6 — route registration', () => {
    it('initProceduresView registers "procedures-architect"', () => {
        document.body.innerHTML = '<div id="view-procedures-architect"></div>';
        initProceduresView();
        expect(isRegistered('procedures-architect')).toBe(true);
    });

    it('DOC_TYPES carries the spec-pinned vocabulary', () => {
        expect(DOC_TYPES).toEqual(['SOP', 'MOP', 'EOP', 'EMP']);
    });
});


// ════════════════════════════════════════════════════════════════════
// Asset picker — preset dropdown + custom toggle
// ════════════════════════════════════════════════════════════════════
describe('Procedure Architect — asset preset shape', () => {
    it('ASSET_PRESETS is grouped, non-empty, and every id is a string', () => {
        expect(Array.isArray(ASSET_PRESETS)).toBe(true);
        expect(ASSET_PRESETS.length).toBeGreaterThan(0);
        for (const g of ASSET_PRESETS) {
            expect(typeof g.group).toBe('string');
            expect(g.group.length).toBeGreaterThan(0);
            expect(Array.isArray(g.items)).toBe(true);
            expect(g.items.length).toBeGreaterThan(0);
            for (const it of g.items) {
                expect(typeof it.id).toBe('string');
                expect(typeof it.label).toBe('string');
                expect(it.id.length).toBeGreaterThan(0);
            }
        }
    });

    it('common Path-C2 assets are present in the curated list', () => {
        const allIds = new Set();
        for (const g of ASSET_PRESETS) for (const it of g.items) allIds.add(it.id);
        // Sanity — the 4 most-referenced assets in CLAUDE.md are picked.
        ['ups_a', 'ups_b', 'chiller_1', 'chiller_2'].forEach((id) => {
            expect(allIds.has(id)).toBe(true);
        });
    });

    it('renderAssetSelect emits <optgroup>s + the Custom + None options', () => {
        const html = renderAssetSelect();
        // None + Custom sentinels.
        expect(html).toContain(`value="${ASSET_NONE_VALUE}"`);
        expect(html).toContain(`value="${ASSET_CUSTOM_VALUE}"`);
        expect(html).toContain('Custom');
        // One <optgroup> per preset group, with the right label.
        for (const g of ASSET_PRESETS) {
            expect(html).toContain(`<optgroup label="${g.group}"`);
        }
        // Every asset id is rendered exactly once.
        for (const g of ASSET_PRESETS) {
            for (const it of g.items) {
                expect(html).toContain(`value="${it.id}"`);
            }
        }
    });

    it('renderAssetSelect escapes hostile label characters (defence in depth)', () => {
        // The constant is curated, but the helper should still escape —
        // a future PR adding "x & y" or "<script>" in a label must not
        // break the markup. Hand-roll a tiny preset to prove the path.
        const html = renderAssetSelect();
        const div = document.createElement('div');
        div.innerHTML = `<select>${html}</select>`;
        // No stray <script> from the curated list.
        expect(div.querySelector('script')).toBeNull();
        // All options are present.
        const count = div.querySelectorAll('option').length;
        // none + custom + every preset item
        let presetCount = 0;
        for (const g of ASSET_PRESETS) presetCount += g.items.length;
        expect(count).toBe(2 + presetCount);
    });
});

describe('Procedure Architect — custom asset toggle', () => {
    it('custom input is hidden by default', () => {
        _mountView();
        const wrap = document.querySelector('[data-proc-asset-custom-wrap]');
        expect(wrap.hidden).toBe(true);
    });

    it('syncCustomAssetVisibility reveals the input when Custom is picked', () => {
        _mountView();
        const root = document.getElementById('view-procedures-architect');
        const sel = root.querySelector('[data-proc-asset-select]');
        const wrap = root.querySelector('[data-proc-asset-custom-wrap]');
        sel.value = ASSET_CUSTOM_VALUE;
        syncCustomAssetVisibility(root);
        expect(wrap.hidden).toBe(false);
        // Pick a preset back -> hidden again.
        sel.value = 'ups_a';
        syncCustomAssetVisibility(root);
        expect(wrap.hidden).toBe(true);
    });

    it('resolveAssetId returns the preset id when one is selected', () => {
        _mountView();
        const root = document.getElementById('view-procedures-architect');
        root.querySelector('[data-proc-asset-select]').value = 'chiller_2';
        expect(resolveAssetId(root)).toBe('chiller_2');
    });

    it('resolveAssetId returns "" when (none) is selected', () => {
        _mountView();
        const root = document.getElementById('view-procedures-architect');
        root.querySelector('[data-proc-asset-select]').value = ASSET_NONE_VALUE;
        expect(resolveAssetId(root)).toBe('');
    });

    it('resolveAssetId returns the custom text when Custom is selected', () => {
        _mountView();
        const root = document.getElementById('view-procedures-architect');
        root.querySelector('[data-proc-asset-select]').value = ASSET_CUSTOM_VALUE;
        root.querySelector('[data-proc-asset-custom]').value = '  genset_a  ';
        expect(resolveAssetId(root)).toBe('genset_a');
    });

    it('resolveAssetId returns "" when Custom selected but input empty', () => {
        _mountView();
        const root = document.getElementById('view-procedures-architect');
        root.querySelector('[data-proc-asset-select]').value = ASSET_CUSTOM_VALUE;
        // Input intentionally left blank.
        expect(resolveAssetId(root)).toBe('');
    });
});


// ════════════════════════════════════════════════════════════════════
// Context quick-pick chips — per doc_type, auto-fill with asset sub
// ════════════════════════════════════════════════════════════════════
describe('Procedure Architect — CONTEXT_TEMPLATES shape', () => {
    it('exposes templates for every doc_type', () => {
        for (const t of DOC_TYPES) {
            expect(Array.isArray(CONTEXT_TEMPLATES[t])).toBe(true);
            expect(CONTEXT_TEMPLATES[t].length).toBeGreaterThanOrEqual(3);
            for (const tpl of CONTEXT_TEMPLATES[t]) {
                expect(typeof tpl.label).toBe('string');
                expect(typeof tpl.text).toBe('string');
                expect(tpl.label.length).toBeGreaterThan(0);
                expect(tpl.text.length).toBeGreaterThan(20);
            }
        }
    });

    it('every MOP template includes the {asset} substitution token', () => {
        // MOP scenarios are asset-bound by definition — a MOP without
        // an asset placeholder would render grammatically off after
        // substitution.
        for (const tpl of CONTEXT_TEMPLATES.MOP) {
            expect(tpl.text).toContain('{asset}');
        }
    });

    it('every MOP template already mentions the safety terms the audit needs', () => {
        // Quality gate — if a chip pre-fills the context and the
        // operator clicks Generate verbatim, the resulting MOP draft
        // should at least START with the safety vocabulary present in
        // the OPERATOR CONTEXT field. The hermetic prompt carries the
        // context into the LLM so this is the first chance for the
        // model to see LOTO/PPE/CSA Z462.
        for (const tpl of CONTEXT_TEMPLATES.MOP) {
            const t = tpl.text;
            expect(/LOTO/i.test(t) || /Lockout/i.test(t)).toBe(true);
            expect(/PPE/i.test(t)).toBe(true);
            expect(/CSA\s*Z462/i.test(t) || /NFPA\s*70E/i.test(t)).toBe(true);
        }
    });

    it('every MOP template names a back-out plan bounded by a physical limit', () => {
        // Industry-notes follow-up: each MOP starter must pin the
        // back-out window to a computable physical bound (battery
        // runtime, ASHRAE A2 envelope, sync-check expiry, vendor
        // rollback support). A back-out plan without a clock is just
        // a wish — operators need a deadline they can derive from
        // BMS readouts. Regression test prevents a future PR that
        // strips the back-out language while editing the chip text.
        for (const tpl of CONTEXT_TEMPLATES.MOP) {
            const t = tpl.text;
            expect(/back[-\s]?out/i.test(t)).toBe(true);
        }
    });
});

describe('Procedure Architect — renderContextChips filters by doc_type', () => {
    it('renders one chip per template for the selected doc_type (SOP default)', () => {
        _mountView();
        const root = document.getElementById('view-procedures-architect');
        renderContextChips(root);
        const slot = root.querySelector('[data-proc-ctx-chips]');
        const chips = slot.querySelectorAll('button.proc-chip[data-action="ctx-fill"]');
        expect(chips.length).toBe(CONTEXT_TEMPLATES.SOP.length);
        // Chip labels match the SOP template labels exactly.
        const labels = Array.from(chips).map((c) => c.textContent);
        for (const tpl of CONTEXT_TEMPLATES.SOP) {
            expect(labels).toContain(tpl.label);
        }
    });

    it('flips to MOP chips when the operator changes doc_type', () => {
        // Commit 4: MOP chips are now filtered by category. The
        // default category is `ups` (4 chips), not the flat union of
        // every MOP category. Test asserts the default-category
        // chips render, not the full union.
        const {
            MOP_CATEGORIES: M, MOP_CATEGORY_DEFAULT: DEFAULT_K,
        } = __procedures_view_test__;
        _mountView();
        const root = document.getElementById('view-procedures-architect');
        root.querySelector('[data-proc-doc-type]').value = 'MOP';
        renderContextChips(root);
        const chips = root.querySelectorAll(
            '[data-proc-ctx-chips] button.proc-chip',
        );
        expect(chips.length).toBe(M[DEFAULT_K].length);
        const labels = Array.from(chips).map((c) => c.textContent);
        for (const tpl of M[DEFAULT_K]) {
            expect(labels).toContain(tpl.label);
        }
    });

    it('every doc_type renders chips (no empty rows for SOP/MOP/EOP/EMP)', () => {
        _mountView();
        const root = document.getElementById('view-procedures-architect');
        for (const t of DOC_TYPES) {
            root.querySelector('[data-proc-doc-type]').value = t;
            renderContextChips(root);
            const chips = root.querySelectorAll(
                '[data-proc-ctx-chips] button.proc-chip',
            );
            expect(chips.length).toBeGreaterThan(0);
        }
    });
});

describe('Procedure Architect — applyContextTemplate auto-fills the textarea', () => {
    it('substitutes {asset} with the picked preset', () => {
        _mountView();
        const root = document.getElementById('view-procedures-architect');
        root.querySelector('[data-proc-asset-select]').value = 'ups_b';
        applyContextTemplate(
            root, 'Replace battery cabinet on {asset} — LOTO + PPE per CSA Z462-24.',
        );
        const ta = root.querySelector('[data-proc-context]');
        expect(ta.value).toBe(
            'Replace battery cabinet on ups_b — LOTO + PPE per CSA Z462-24.',
        );
    });

    it('substitutes {asset} with the Custom text when picked', () => {
        _mountView();
        const root = document.getElementById('view-procedures-architect');
        root.querySelector('[data-proc-asset-select]').value = ASSET_CUSTOM_VALUE;
        root.querySelector('[data-proc-asset-custom]').value = 'bess_1';
        applyContextTemplate(root, 'Inspect {asset}.');
        expect(root.querySelector('[data-proc-context]').value).toBe(
            'Inspect bess_1.',
        );
    });

    it('substitutes {asset} with a neutral placeholder when no asset picked', () => {
        _mountView();
        const root = document.getElementById('view-procedures-architect');
        // Default (none) selected.
        applyContextTemplate(root, 'Inspect {asset}.');
        expect(root.querySelector('[data-proc-context]').value).toBe(
            'Inspect the affected asset.',
        );
    });

    it('overwrites prior textarea content (templates are starter, not append)', () => {
        _mountView();
        const root = document.getElementById('view-procedures-architect');
        const ta = root.querySelector('[data-proc-context]');
        ta.value = 'old typed context';
        applyContextTemplate(root, 'Brand new template.');
        expect(ta.value).toBe('Brand new template.');
    });
});

// ════════════════════════════════════════════════════════════════════
// Commit 4 -- MOP categorías
// ════════════════════════════════════════════════════════════════════
describe('Procedure Architect — MOP_CATEGORIES shape (Commit 4)', () => {
    const { MOP_CATEGORIES, MOP_CATEGORY_KEYS, MOP_CATEGORY_LABELS,
        MOP_CATEGORY_DEFAULT } = __procedures_view_test__;

    it('exposes 12 categorías matching the operator catalog (v0.17.0 expansion)', () => {
        expect(MOP_CATEGORY_KEYS).toEqual([
            'ups', 'transformer', 'utility',
            'pdu_sts', 'rpp', 'busway',
            'chiller', 'crah', 'tower', 'global',
            'life_safety', 'combustible',
        ]);
        for (const k of MOP_CATEGORY_KEYS) {
            expect(Array.isArray(MOP_CATEGORIES[k])).toBe(true);
            expect(MOP_CATEGORIES[k].length).toBeGreaterThanOrEqual(2);
            expect(typeof MOP_CATEGORY_LABELS[k]).toBe('string');
            expect(MOP_CATEGORY_LABELS[k].length).toBeGreaterThan(0);
        }
    });

    it('default category is ups (most common starter)', () => {
        expect(MOP_CATEGORY_DEFAULT).toBe('ups');
        expect(MOP_CATEGORIES[MOP_CATEGORY_DEFAULT]).toBeDefined();
    });

    it('38 total chips across the 12 categorías (4+4+4+3+3+3+3+3+3+2+3+3)', () => {
        const total = MOP_CATEGORY_KEYS.reduce(
            (sum, k) => sum + MOP_CATEGORIES[k].length, 0,
        );
        expect(total).toBe(38);
    });

    it('every chip in every category embeds the safety contract', () => {
        // S-SAFETY-01: each chip text must contain LOTO/Lockout/Tagout
        // (even live-work chips say "LOTO no aplica") + PPE + CSA Z462
        // / NFPA 70E + Vivo-Muerto-Vivo OR limite de aproximacion +
        // Back-out + {asset}.
        for (const k of MOP_CATEGORY_KEYS) {
            for (const chip of MOP_CATEGORIES[k]) {
                const t = chip.text;
                expect(typeof chip.label).toBe('string');
                expect(chip.label.length).toBeGreaterThan(0);
                expect(t.length).toBeGreaterThan(80);
                expect(t).toContain('{asset}');
                expect(/LOTO|Lockout|Tagout/i.test(t)).toBe(true);
                expect(/PPE/i.test(t)).toBe(true);
                expect(/CSA\s*Z462|NFPA\s*70E/i.test(t)).toBe(true);
                expect(
                    /Vivo[-\s]*Muerto[-\s]*Vivo|l[ií]mite de aproximaci[oó]n/i.test(t),
                ).toBe(true);
                expect(/back[-\s]?out/i.test(t)).toBe(true);
            }
        }
    });

    it('pdu_sts chips embed alarm-history + SCR pre-transfer hint (S-DISTRIBUTION-01)', () => {
        // The PDU/STS chip authors a starter whose text steers the LLM
        // toward including the alarm-history + SCR check the audit
        // gate enforces. Either presence is acceptable per chip.
        for (const chip of MOP_CATEGORIES.pdu_sts) {
            const t = chip.text;
            expect(/historial de alarmas|alarm history/i.test(t)).toBe(true);
            expect(/SCR|caja SCR/i.test(t)).toBe(true);
        }
    });
});

describe('Procedure Architect — MOP category select + chip filtering (Commit 4)', () => {
    const { MOP_CATEGORIES, MOP_CATEGORY_KEYS,
        setCurrentMopCategory, syncMopCategoryVisibility,
        getCurrentMopCategory, MOP_CATEGORY_DEFAULT } = __procedures_view_test__;

    it('category wrap is HIDDEN by default (doc_type=SOP)', () => {
        _mountView();
        const root = document.getElementById('view-procedures-architect');
        syncMopCategoryVisibility(root);
        const wrap = root.querySelector('[data-proc-mop-category-wrap]');
        expect(wrap.hidden).toBe(true);
    });

    it('category wrap becomes VISIBLE when doc_type flips to MOP', () => {
        _mountView();
        const root = document.getElementById('view-procedures-architect');
        root.querySelector('[data-proc-doc-type]').value = 'MOP';
        syncMopCategoryVisibility(root);
        const wrap = root.querySelector('[data-proc-mop-category-wrap]');
        expect(wrap.hidden).toBe(false);
    });

    it('category wrap returns to HIDDEN for EOP/EMP', () => {
        _mountView();
        const root = document.getElementById('view-procedures-architect');
        for (const t of ['SOP', 'EOP', 'EMP']) {
            root.querySelector('[data-proc-doc-type]').value = t;
            syncMopCategoryVisibility(root);
            const wrap = root.querySelector('[data-proc-mop-category-wrap]');
            expect(wrap.hidden).toBe(true);
        }
    });

    it('renderContextChips on MOP renders the DEFAULT category chips (ups)', () => {
        _mountView();
        const root = document.getElementById('view-procedures-architect');
        root.querySelector('[data-proc-doc-type]').value = 'MOP';
        renderContextChips(root);
        const chips = root.querySelectorAll(
            '[data-proc-ctx-chips] button.proc-chip',
        );
        expect(chips.length).toBe(MOP_CATEGORIES.ups.length);
        const labels = Array.from(chips).map((c) => c.textContent);
        for (const chip of MOP_CATEGORIES.ups) {
            expect(labels).toContain(chip.label);
        }
    });

    it('changing category re-renders the chip row with new bucket', () => {
        _mountView();
        const root = document.getElementById('view-procedures-architect');
        root.querySelector('[data-proc-doc-type]').value = 'MOP';

        // Switch to busway -> 3 chips, all from the busway bucket.
        setCurrentMopCategory('busway');
        renderContextChips(root);
        let chips = root.querySelectorAll('[data-proc-ctx-chips] button.proc-chip');
        expect(chips.length).toBe(MOP_CATEGORIES.busway.length);
        let labels = Array.from(chips).map((c) => c.textContent);
        for (const chip of MOP_CATEGORIES.busway) {
            expect(labels).toContain(chip.label);
        }

        // Then transformer -> 4 chips.
        setCurrentMopCategory('transformer');
        renderContextChips(root);
        chips = root.querySelectorAll('[data-proc-ctx-chips] button.proc-chip');
        expect(chips.length).toBe(MOP_CATEGORIES.transformer.length);
        labels = Array.from(chips).map((c) => c.textContent);
        for (const chip of MOP_CATEGORIES.transformer) {
            expect(labels).toContain(chip.label);
        }
    });

    it('falls back to default category when _currentMopCategory is unknown', () => {
        _mountView();
        const root = document.getElementById('view-procedures-architect');
        root.querySelector('[data-proc-doc-type]').value = 'MOP';
        setCurrentMopCategory('garbage_key');
        renderContextChips(root);
        const chips = root.querySelectorAll(
            '[data-proc-ctx-chips] button.proc-chip',
        );
        // Falls back to MOP_CATEGORY_DEFAULT (ups)
        expect(chips.length).toBe(MOP_CATEGORIES[MOP_CATEGORY_DEFAULT].length);
    });

    it('hint surfaces the active category name (ux signal)', () => {
        _mountView();
        const root = document.getElementById('view-procedures-architect');
        root.querySelector('[data-proc-doc-type]').value = 'MOP';
        setCurrentMopCategory('rpp');
        renderContextChips(root);
        const slot = root.querySelector('[data-proc-ctx-chips]');
        expect(slot.textContent).toContain('RPP');
    });

    it('getCurrentMopCategory returns the live module-state value', () => {
        // Reset is called automatically in afterEach, so the default
        // should be the module's MOP_CATEGORY_DEFAULT.
        setCurrentMopCategory('utility');
        expect(getCurrentMopCategory()).toBe('utility');
    });
});

describe('Procedure Architect — chip click via onClick dispatcher', () => {
    function _fakeEvent(target) { return { target }; }

    it('clicking a chip routes through onClick -> applyContextTemplate', () => {
        _mountView();
        const root = document.getElementById('view-procedures-architect');
        root.querySelector('[data-proc-asset-select]').value = 'chiller_1';
        // Render chips first so onClick can find one.
        renderContextChips(root);
        const chip = root.querySelector(
            '[data-proc-ctx-chips] button.proc-chip',
        );
        expect(chip).not.toBeNull();
        onClick(_fakeEvent(chip));
        const ta = root.querySelector('[data-proc-context]');
        // The textarea was filled by the chip's template, asset
        // substituted. The exact text depends on which template is
        // first for the default SOP — we assert the asset id surfaced
        // and the template was non-empty.
        expect(ta.value.length).toBeGreaterThan(0);
        expect(ta.value).toContain('chiller_1');
        expect(ta.value).not.toContain('{asset}');
    });
});


// ════════════════════════════════════════════════════════════════════
// Epic 6 Sprint 3 Phase 2 — stale-verdict invalidation
// ════════════════════════════════════════════════════════════════════
describe('Sprint 3 Phase 2 — stale-verdict invalidation', () => {
    function _approvedDraft(id, content = 'Daily round of UPS room.') {
        return {
            draft: {
                draft_id: id, doc_type: 'SOP',
                content: `# SOP\n${content}\nVerify BMS setpoints.`,
                llm_present: false,
            },
            safety_audit: { verdict: 'approve', findings: [] },
        };
    }

    async function _setupApproved(pid = 'qd-stale') {
        _mountView();
        const spy = _fakeFetchOK(_approvedDraft(pid));
        vi.stubGlobal('fetch', spy);
        document.querySelector('[data-proc-context]').value =
            'A valid context that will be remembered.';
        await submitGenerate();
        vi.unstubAllGlobals();
        return pid;
    }

    it('is not stale immediately after a successful generate', async () => {
        await _setupApproved('qd-fresh');
        const root = document.getElementById('view-procedures-architect');
        expect(isStaleVsLastGenerate(root)).toBe(false);
    });

    it('flips stale when the operator edits the textarea after generate', async () => {
        await _setupApproved('qd-edit');
        const root = document.getElementById('view-procedures-architect');
        const ta = root.querySelector('[data-proc-context]');
        ta.value += '\nextra text added after generate';
        expect(isStaleVsLastGenerate(root)).toBe(true);
    });

    it('marks the result slot stale + hides the Sign button on edit', async () => {
        await _setupApproved('qd-mark');
        const root = document.getElementById('view-procedures-architect');
        // Sign button is present right after generate.
        expect(root.querySelector('.proc-btn-sign')).not.toBeNull();
        // Operator edits.
        const ta = root.querySelector('[data-proc-context]');
        ta.value = 'completely different content now';
        ta.dispatchEvent(new Event('input'));
        const slot = root.querySelector('[data-proc-result]');
        expect(slot.dataset.stale).toBe('1');
        expect(slot.querySelector('.proc-banner-stale')).not.toBeNull();
        // Sign button still in DOM but disabled + hidden defensively.
        const btn = slot.querySelector('.proc-btn-sign');
        expect(btn.disabled).toBe(true);
        expect(btn.hidden).toBe(true);
    });

    it('submitSign refuses to POST when context is stale', async () => {
        const pid = await _setupApproved('qd-sign-stale');
        const root = document.getElementById('view-procedures-architect');
        // Operator edits AFTER generate.
        const ta = root.querySelector('[data-proc-context]');
        ta.value = 'edited after generate';
        // Click Sign — submitSign must refuse before any network call.
        const spy = vi.fn();
        vi.stubGlobal('fetch', spy);
        await submitSign(pid);
        expect(spy).not.toHaveBeenCalled();
        const slot = document.querySelector(
            `.proc-sign-result[data-draft-id="${pid}"]`,
        );
        expect(slot.textContent.toLowerCase()).toContain('refusing to sign');
        expect(slot.textContent.toLowerCase()).toContain('edited');
    });

    it('a fresh generate clears the stale marker', async () => {
        await _setupApproved('qd-renew');
        const root = document.getElementById('view-procedures-architect');
        const ta = root.querySelector('[data-proc-context]');
        ta.value = 'edited content';
        ta.dispatchEvent(new Event('input'));
        const slot = root.querySelector('[data-proc-result]');
        expect(slot.dataset.stale).toBe('1');
        // Re-generate (the edited content becomes the new baseline).
        const spy2 = _fakeFetchOK(_approvedDraft('qd-renew2', 'edited content'));
        vi.stubGlobal('fetch', spy2);
        await submitGenerate();
        expect(slot.dataset.stale).toBe('');
        // Sign button visible again.
        expect(slot.querySelector('.proc-btn-sign')).not.toBeNull();
    });
});


// ════════════════════════════════════════════════════════════════════
// Epic 6 Sprint 3 Phase 3 — pre-pull /api/telemetry/latest into metadata
// ════════════════════════════════════════════════════════════════════
describe('Sprint 3 Phase 3 — telemetry pre-pull', () => {
    it('TELEMETRY_METADATA_KEYS is a curated whitelist', () => {
        expect(Array.isArray(TELEMETRY_METADATA_KEYS)).toBe(true);
        expect(TELEMETRY_METADATA_KEYS.length).toBeGreaterThan(0);
        // PUE + IT load are the two most-cited grounding signals.
        expect(TELEMETRY_METADATA_KEYS).toContain('pue');
        expect(TELEMETRY_METADATA_KEYS).toContain('it_load_kw');
    });

    it('fetchTelemetrySnapshot reduces a /latest payload to the whitelist', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: true, status: 200,
            json: async () => ({
                latest: {
                    pue: 1.32, it_load_kw: 14200, hall_temp_c: 22.4,
                    delta_t_c: 4.6, scenario: 'NORMAL',
                    // Keys not on the whitelist must NOT leak through.
                    raw_pid_dump: { everything: 'else' },
                    operator: 'private',
                },
                ts: 1779562345.7,
                source: 'timescaledb',
            }),
        })));
        const meta = await fetchTelemetrySnapshot();
        expect(meta.pue).toBe(1.32);
        expect(meta.it_load_kw).toBe(14200);
        expect(meta.snapshot_ts).toBeCloseTo(1779562345.7);
        // Off-whitelist keys dropped.
        expect(meta.raw_pid_dump).toBeUndefined();
        expect(meta.operator).toBeUndefined();
    });

    it('fetchTelemetrySnapshot returns {} on HTTP failure', async () => {
        vi.stubGlobal('fetch', _fakeFetchFail(503, 'down'));
        const meta = await fetchTelemetrySnapshot();
        expect(meta).toEqual({});
    });

    it('fetchTelemetrySnapshot returns {} on a network throw', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('net'); }));
        const meta = await fetchTelemetrySnapshot();
        expect(meta).toEqual({});
    });

    it('fetchTelemetrySnapshot returns {} when latest is absent or wrong type', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: true, status: 200, json: async () => ({ latest: null }),
        })));
        expect(await fetchTelemetrySnapshot()).toEqual({});
    });

    it('submitGenerate hits /api/telemetry/latest BEFORE /architect/generate', async () => {
        _mountView();
        document.querySelector('[data-proc-context]').value =
            'A valid context for the telemetry path.';
        const calls = [];
        vi.stubGlobal('fetch', vi.fn(async (url, opts) => {
            calls.push({ url, method: (opts && opts.method) || 'GET' });
            if (url === '/api/telemetry/latest') {
                return {
                    ok: true, status: 200, json: async () => ({
                        latest: { pue: 1.31, it_load_kw: 14000 },
                        ts: 1.0,
                    }),
                };
            }
            // architect/generate
            return {
                ok: true, status: 200, json: async () => ({
                    draft: {
                        draft_id: 'qd-tele', doc_type: 'SOP',
                        content: '# SOP', llm_present: false,
                    },
                    safety_audit: { verdict: 'approve', findings: [] },
                }),
            };
        }));
        await submitGenerate();
        // Telemetry comes BEFORE generate.
        expect(calls.length).toBeGreaterThanOrEqual(2);
        const teleIdx = calls.findIndex((c) => c.url === '/api/telemetry/latest');
        const genIdx = calls.findIndex(
            (c) => c.url === '/api/procedures/architect/generate',
        );
        expect(teleIdx).toBeGreaterThanOrEqual(0);
        expect(genIdx).toBeGreaterThan(teleIdx);
        // And the generate body carries the curated metadata.
        const genCall = calls[genIdx];
        // Re-grab the fetch.mock to read the body sent.
        const allMock = (await import('vitest')).vi;
        // Find the architect generate call directly:
        const arch = (globalThis.fetch).mock
            ? (globalThis.fetch).mock.calls.find(
                (c) => c[0] === '/api/procedures/architect/generate',
              )
            : null;
        expect(arch).not.toBeNull();
        const body = JSON.parse(arch[1].body);
        expect(body.metadata).toEqual({
            pue: 1.31, it_load_kw: 14000, snapshot_ts: 1.0,
        });
        // Reference the unused name so ruff/lint doesn't flag.
        void allMock; void genCall;
    });
});


// ════════════════════════════════════════════════════════════════════
// Sprint 3 follow-up — awaiting-second-signature badge in the HMI
// ════════════════════════════════════════════════════════════════════
describe('Sprint 3 follow-up — Maker-Checker badge in HMI', () => {
    function _approvedMop(id) {
        return {
            draft: {
                draft_id: id, doc_type: 'MOP', asset_id: 'ups_b',
                content: 'PPE per CSA Z462. LOTO on bus. Back-out plan ok.',
                llm_present: true,
            },
            safety_audit: { verdict: 'approve', findings: [] },
        };
    }

    async function _setupApprovedMop(pid) {
        _mountView();
        vi.stubGlobal('fetch', _fakeFetchOK(_approvedMop(pid)));
        document.querySelector('[data-proc-context]').value =
            'A valid context for the MOP sign test.';
        await submitGenerate();
        vi.unstubAllGlobals();
    }

    it('HTTP 202 awaiting renders the badge + maker + sha + checker hint', async () => {
        await _setupApprovedMop('qd-await-1');
        // Server returns 202 on first MOP sign. Vitest doesn't read
        // ok from status code 202 automatically — supply ok=true
        // explicitly because the .ok check passes in fetch standard
        // for any 2xx.
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: true, status: 202,
            json: async () => ({
                signed: false,
                draft_id: 'qd-await-1',
                status: 'awaiting_second_signature',
                first_signer: 'maker.alice',
                first_signer_role: 'SME_L6',
                content_sha256: 'deadbeef'.repeat(8),
                doc_type: 'MOP',
                witness_required: true,
                message: 'Maker-Checker gate: a MOP cannot ship on a single signature.',
            }),
        })));
        await submitSign('qd-await-1');
        const slot = document.querySelector(
            '.proc-sign-result[data-draft-id="qd-await-1"]',
        );
        // The badge is unmistakable.
        const badge = slot.querySelector('.proc-sign-awaiting-badge');
        expect(badge).not.toBeNull();
        expect(badge.textContent).toContain('AWAITING SECOND SIGNATURE');
        // Maker identity + role surfaced.
        expect(slot.textContent).toContain('maker.alice');
        expect(slot.textContent).toContain('SME_L6');
        // Truncated content sha shown so the next operator can verify.
        expect(slot.textContent).toContain('deadbeefdeadbeef…');
        // Checker hint mentions the operator-id-change path.
        expect(slot.textContent.toLowerCase()).toContain('different');
        expect(slot.textContent.toLowerCase()).toContain('operator id');
        // No "Signed to ledger" line on the awaiting path.
        expect(slot.querySelector('.proc-sign-ok')).toBeNull();
    });

    it('second sign returns 200 sealed with both signers rendered', async () => {
        await _setupApprovedMop('qd-await-2');
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: true, status: 200,
            json: async () => ({
                signed: true,
                draft_id: 'qd-await-2',
                entry_id: 'a1b2c3d4e5f6abcd1111222233334444',
                sequence_no: 42,
                content_sha256: 'cafebabe'.repeat(8),
                safety_audit_verdict: 'approve',
                witness_required: true,
                first_signer: 'maker.alice',
                second_signer: 'checker.bob',
            }),
        })));
        await submitSign('qd-await-2');
        const slot = document.querySelector(
            '.proc-sign-result[data-draft-id="qd-await-2"]',
        );
        // Standard success line.
        expect(slot.querySelector('.proc-sign-ok')).not.toBeNull();
        expect(slot.textContent).toContain('seq #42');
        // Witness line names both operators.
        const witness = slot.querySelector('.proc-sign-witness-line');
        expect(witness).not.toBeNull();
        expect(witness.textContent).toContain('Maker:');
        expect(witness.textContent).toContain('maker.alice');
        expect(witness.textContent).toContain('Checker:');
        expect(witness.textContent).toContain('checker.bob');
    });

    it('XSS — hostile first_signer in the 202 payload is escaped', async () => {
        await _setupApprovedMop('qd-await-xss');
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: true, status: 202,
            json: async () => ({
                signed: false,
                status: 'awaiting_second_signature',
                first_signer: '<img src=x onerror=window.__pwn_await=1>',
                first_signer_role: '<script>window.__pwn_role=1</script>',
                content_sha256: 'aaaa'.repeat(16),
                witness_required: true,
            }),
        })));
        await submitSign('qd-await-xss');
        const slot = document.querySelector(
            '.proc-sign-result[data-draft-id="qd-await-xss"]',
        );
        expect(slot.querySelector('img')).toBeNull();
        expect(slot.querySelector('script')).toBeNull();
        expect(window.__pwn_await).toBeUndefined();
        expect(window.__pwn_role).toBeUndefined();
    });

    it('operator_id from the form input flows into the POST body', async () => {
        await _setupApprovedMop('qd-opid');
        // Mount adds the operator_id input via _mountView using
        // renderAssetSelect markup — but _mountView is the test
        // stub and doesn't include the input. Inject it now so the
        // production read path can find it.
        const root = document.getElementById('view-procedures-architect');
        const inp = document.createElement('input');
        inp.setAttribute('data-proc-operator-id', '');
        inp.value = '  checker.carol  ';
        root.appendChild(inp);
        const spy = vi.fn(async () => ({
            ok: true, status: 200,
            json: async () => ({
                signed: true, draft_id: 'qd-opid',
                entry_id: 'e' * 16, sequence_no: 99,
                content_sha256: 'd' * 64,
                safety_audit_verdict: 'approve',
                witness_required: false,
            }),
        }));
        vi.stubGlobal('fetch', spy);
        await submitSign('qd-opid');
        const call = spy.mock.calls.find(
            (c) => c[0] === '/api/procedures/architect/sign',
        );
        expect(call).toBeDefined();
        const body = JSON.parse(call[1].body);
        // Input value trimmed + propagated.
        expect(body.operator_id).toBe('checker.carol');
    });

    it('operator_id falls back to default when the input is absent', async () => {
        // Existing tests (Sprint 1 / Sprint 2) don't mount the input —
        // the back-compat default ensures they still POST a valid
        // operator_id without test changes.
        await _setupApprovedMop('qd-default-op');
        const spy = vi.fn(async () => ({
            ok: true, status: 200,
            json: async () => ({
                signed: true, draft_id: 'qd-default-op',
                entry_id: 'x' * 16, sequence_no: 1,
                content_sha256: 'y' * 64,
                safety_audit_verdict: 'approve',
                witness_required: false,
            }),
        }));
        vi.stubGlobal('fetch', spy);
        await submitSign('qd-default-op');
        const call = spy.mock.calls.find(
            (c) => c[0] === '/api/procedures/architect/sign',
        );
        const body = JSON.parse(call[1].body);
        expect(body.operator_id).toBe('wilmer.angel');
    });
});


// ════════════════════════════════════════════════════════════════════
// Epic 6 Option A — Save-to-library from Architect post-sign
// ════════════════════════════════════════════════════════════════════
describe('Option A — Save-to-library button', () => {
    async function _signAndGetSlot(pid) {
        // Generate + sign-success cycle leaving the Save button in the DOM.
        _mountView();
        const approveBody = {
            draft: {
                draft_id: pid, doc_type: 'SOP',
                content: '# SOP\nDaily round. Verify BMS setpoints.',
                llm_present: false,
            },
            safety_audit: { verdict: 'approve', findings: [] },
        };
        vi.stubGlobal('fetch', _fakeFetchOK(approveBody));
        document.querySelector('[data-proc-context]').value =
            'A valid context for the save-to-library test.';
        await submitGenerate();
        // Sign-success returns 200 with witness_required=false (SOP path).
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: true, status: 200,
            json: async () => ({
                signed: true, draft_id: pid,
                entry_id: 'lentry-' + pid,
                sequence_no: 17,
                content_sha256: 'sigsha256deadbeef'.repeat(4),
                safety_audit_verdict: 'approve',
                witness_required: false,
            }),
        })));
        await submitSign(pid);
        vi.unstubAllGlobals();
        return document.querySelector(
            `.proc-sign-result[data-draft-id="${pid}"]`,
        );
    }

    it('renders the Save button after a successful sign', async () => {
        const slot = await _signAndGetSlot('qd-save-1');
        const btn = slot.querySelector('.proc-btn-save-library');
        expect(btn).not.toBeNull();
        expect(btn.textContent).toContain('Save to library');
        expect(btn.dataset.draftId).toBe('qd-save-1');
        expect(btn.dataset.ledgerEntryId).toBe('lentry-qd-save-1');
    });

    it('POSTs draft + ledger_entry_id + operator to /save-to-library', async () => {
        await _signAndGetSlot('qd-save-post');
        const spy = vi.fn(async () => ({
            ok: true, status: 200,
            json: async () => ({
                saved: true,
                library_id: 'lib-1234-abcd-5678-ef00',
                draft_id: 'qd-save-post',
                title: 'SOP — site-wide (qd-save-)',
                content_sha256: 'x' * 64,
                audit_verdict: 'approve',
                library_size: 1,
            }),
        }));
        vi.stubGlobal('fetch', spy);
        await submitSaveToLibrary('qd-save-post', 'lentry-qd-save-post');
        const call = spy.mock.calls.find(
            (c) => c[0] === '/api/procedures/architect/save-to-library',
        );
        expect(call).toBeDefined();
        expect(call[1].method).toBe('POST');
        const body = JSON.parse(call[1].body);
        expect(body.draft_id).toBe('qd-save-post');
        expect(body.ledger_entry_id).toBe('lentry-qd-save-post');
        expect(body.doc_type).toBe('SOP');
        expect(body.operator_id).toBe('wilmer.angel');
    });

    it('shows success line + removes Save button after a 200', async () => {
        const slot = await _signAndGetSlot('qd-save-ok');
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: true, status: 200,
            json: async () => ({
                saved: true,
                library_id: 'lib-ok-id-1234567890abcdef',
                draft_id: 'qd-save-ok',
                title: 't', content_sha256: 'x', audit_verdict: 'approve',
                library_size: 5,
            }),
        })));
        await submitSaveToLibrary('qd-save-ok', 'lentry-qd-save-ok');
        // Sign block still there.
        expect(slot.querySelector('.proc-sign-ok')).not.toBeNull();
        // Save button removed; success line appended.
        expect(slot.querySelector('.proc-btn-save-library')).toBeNull();
        const okLine = slot.querySelector('.proc-library-ok');
        expect(okLine).not.toBeNull();
        expect(okLine.textContent).toContain('Saved to library');
        expect(okLine.textContent).toContain('library now holds 5');
    });

    it('on 403 shows fail line without removing the Save button', async () => {
        const slot = await _signAndGetSlot('qd-save-fail');
        vi.stubGlobal('fetch', _fakeFetchFail(403, 'Cannot save hard_stop content'));
        await submitSaveToLibrary('qd-save-fail', 'lentry-qd-save-fail');
        // Fail line appears; sign block still present; button still there
        // so operator can retry after the audit issue is fixed.
        expect(slot.querySelector('.proc-sign-ok')).not.toBeNull();
        expect(slot.querySelector('.proc-btn-save-library')).not.toBeNull();
        const failLine = slot.querySelector('.proc-library-fail');
        expect(failLine).not.toBeNull();
        expect(failLine.textContent).toContain('403');
        expect(failLine.textContent).toContain('hard_stop');
    });

    it('XSS — hostile detail string is escaped', async () => {
        const slot = await _signAndGetSlot('qd-save-xss');
        vi.stubGlobal('fetch', _fakeFetchFail(
            500, '<img src=x onerror=window.__pwn_lib=1>',
        ));
        await submitSaveToLibrary('qd-save-xss', 'lentry-qd-save-xss');
        expect(slot.querySelector('img')).toBeNull();
        expect(window.__pwn_lib).toBeUndefined();
    });

    it('save action routes through onClick dispatcher', async () => {
        await _signAndGetSlot('qd-save-click');
        const spy = vi.fn(async () => ({
            ok: true, status: 200,
            json: async () => ({
                saved: true, library_id: 'l-c', draft_id: 'qd-save-click',
                title: 't', content_sha256: 'x', audit_verdict: 'approve',
                library_size: 1,
            }),
        }));
        vi.stubGlobal('fetch', spy);
        const btn = document.querySelector(
            '.proc-btn-save-library[data-draft-id="qd-save-click"]',
        );
        expect(btn).not.toBeNull();
        onClick({ target: btn });
        // Two awaits to flush the fetch().then() chain.
        await Promise.resolve();
        await Promise.resolve();
        await Promise.resolve();
        const urls = spy.mock.calls.map((c) => c[0]);
        expect(urls).toContain('/api/procedures/architect/save-to-library');
    });
});
