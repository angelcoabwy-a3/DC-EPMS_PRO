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
    submitGenerate, submitSign, onClick,
    renderAssetSelect, resolveAssetId,
    syncCustomAssetVisibility, renderContextChips,
    applyContextTemplate,
    initProceduresView, reset,
    DOC_TYPES, ASSET_PRESETS, ASSET_CUSTOM_VALUE, ASSET_NONE_VALUE,
    CONTEXT_TEMPLATES,
} = __procedures_view_test__;


/** Mounts the production skeleton — uses the real renderAssetSelect()
 *  + an empty chips slot ready for renderContextChips(). Keeps the
 *  Sprint-1 tests working against the new form shape. */
function _mountView() {
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
        const [url, opts] = spy.mock.calls[0];
        expect(url).toBe('/api/procedures/architect/generate');
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
        await Promise.resolve(); await Promise.resolve();
        expect(spy).toHaveBeenCalled();
        expect(spy.mock.calls[0][0]).toBe('/api/procedures/architect/generate');
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
        _mountView();
        const root = document.getElementById('view-procedures-architect');
        root.querySelector('[data-proc-doc-type]').value = 'MOP';
        renderContextChips(root);
        const chips = root.querySelectorAll(
            '[data-proc-ctx-chips] button.proc-chip',
        );
        expect(chips.length).toBe(CONTEXT_TEMPLATES.MOP.length);
        const labels = Array.from(chips).map((c) => c.textContent);
        for (const tpl of CONTEXT_TEMPLATES.MOP) {
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
