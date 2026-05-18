/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/loto.test.js
 * ROADMAP V11 T2.1 Vector 2 — verifies the extracted LOTO Auditor.
 *
 * Behaviour-preserving extraction smoke test: outcome-class mapping,
 * the procedure picker, the 6-pillar render, hostile-line escaping,
 * and that initLotoView() registers the 'loto' route on the declarative
 * router (retiring the legacy click-delegation hack). No browser, no
 * backend.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, afterEach } from 'vitest';

import { __loto_test__ } from '/assets/js/views/loto.js';
import { isRegistered } from '/assets/js/core/router.js';

const { renderLotoResults, renderLotoPillar, lotoOutcomeClass, lotoOverallClass,
    populateLotoProcedureSelect, initLotoView, reset } = __loto_test__;

afterEach(() => {
    reset();
    document.body.innerHTML = '';
});

/** Build a #loto-pillar-card fixture for pillars 1..n. */
function mountPillars(n) {
    let html = '';
    for (let i = 1; i <= n; i += 1) {
        html += `<div class="loto-pillar-card" data-pillar="${i}">
            <span data-pillar-outcome="${i}"></span>
            <div data-pillar-body="${i}"></div>
        </div>`;
    }
    return html;
}

describe('T2.1 Vector 2 — views/loto.js outcome-class mapping', () => {
    it('maps pillar + overall outcomes to CSS classes', () => {
        expect(lotoOutcomeClass('ALL_PASS')).toBe('outcome-pass');
        expect(lotoOutcomeClass('HARD_FAIL')).toBe('outcome-hard-fail');
        expect(lotoOutcomeClass('WARN')).toBe('outcome-warn');
        expect(lotoOutcomeClass(null)).toBe('outcome-warn');
        expect(lotoOverallClass('PASS')).toBe('overall-all-pass');
        expect(lotoOverallClass('HARD_FAIL')).toBe('overall-hard-fail');
        expect(lotoOverallClass(undefined)).toBe('overall-warn');
    });
});

describe('T2.1 Vector 2 — views/loto.js procedure picker', () => {
    it('populates the select and defaults to the compliant demo procedure', () => {
        document.body.innerHTML = '<select id="loto-procedure-select"></select>';
        populateLotoProcedureSelect();
        const sel = document.getElementById('loto-procedure-select');
        // placeholder + 3 demo procedures
        expect(sel.querySelectorAll('option')).toHaveLength(4);
        expect(sel.value).toBe('DEMO-UPS-COMPLIANT');
    });
});

describe('T2.1 Vector 2 — views/loto.js pillar render', () => {
    it('stamps the outcome class + escapes hostile audit lines', () => {
        document.body.innerHTML = mountPillars(1);
        renderLotoPillar(1, 'Topology',
            ['Impact radius: <img src=x onerror=alert(1)>'], 'HARD_FAIL');
        const card = document.querySelector('.loto-pillar-card[data-pillar="1"]');
        expect(card.classList.contains('outcome-hard-fail')).toBe(true);
        expect(document.querySelector('[data-pillar-outcome="1"]').textContent)
            .toBe('HARD_FAIL');
        const body = document.querySelector('[data-pillar-body="1"]');
        expect(body.querySelector('img')).toBeNull();
        expect(body.textContent).toContain('<img src=x onerror=alert(1)>');
    });

    it('renderLotoResults fills the overall card + all 6 pillars', () => {
        document.body.innerHTML = `
            <div id="loto-overall-badge"></div>
            <div id="loto-overall-card"></div>
            <div id="loto-overall-sub"></div>
            <div id="loto-decision-time"></div>
            <div id="loto-hard-fails"></div>
            <pre id="loto-sources-pre"></pre>
            ${mountPillars(6)}`;
        renderLotoResults({
            overall_outcome: 'HARD_FAIL',
            procedure_id: 'DEMO-UPS-MISSING-DISCHARGE',
            target_component_id: 'ups_a',
            decision_time_ms: 12,
            hard_fail_count: 1,
            capacitor_discharge: { required: true, found_in_procedure: false, outcome: 'HARD_FAIL' },
            redundancy: { outcome: 'PASS' },
        });
        expect(document.getElementById('loto-overall-badge').textContent).toBe('HARD_FAIL');
        expect(document.getElementById('loto-decision-time').textContent).toBe('12 ms');
        expect(document.getElementById('loto-hard-fails').textContent).toBe('1');
        expect(document.querySelector('.loto-pillar-card[data-pillar="3"]')
            .classList.contains('outcome-hard-fail')).toBe(true);
        expect(document.querySelector('.loto-pillar-card[data-pillar="2"]')
            .classList.contains('outcome-pass')).toBe(true);
    });
});

describe('T2.1 Vector 2 — views/loto.js declarative routing', () => {
    it('initLotoView registers the loto route on core/router.js', () => {
        document.body.innerHTML = '<div id="view-loto-auditor"></div>';
        initLotoView();
        expect(isRegistered('loto')).toBe(true);
    });
});
