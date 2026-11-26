/* AI-1: instructor debrief box in the training coach and its wiring. */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { trainingHtml, debriefHtml } from '/assets/js/core/training_view.js';
import { __power_test__ } from '/assets/js/views/power.js';

const DONE = { active: false, session: {
    drill: { id: 'DRILL-08', title: 'UPS bypass', summary: 's', path: 'a', target_s: 180, time_limit_s: 900 },
    started_ms: 1, outcome: 'PASS', score: 90, violations: 1, steps: [] } };
const META = { source: 'meta', model: 'muse-spark-1.3', cached: false, lang: 'es',
    text: 'Resumen: bien.\n<script>x</script>', label: 'AI-generated debrief (Meta). Verify it.',
    unverified_citations: ['NFPA 110'], note: '', calls_today: 1, daily_cap: 20 };

describe('debriefHtml', () => {
    it('offers EN / ES when nothing was asked yet', () => {
        const h = debriefHtml(null);
        expect(h).toContain('data-tr-debrief="en"');
        expect(h).toContain('data-tr-debrief="es"');
        expect(h).not.toContain('tr-debrief"');
    });

    it('labels the AI source, warns about unverified citations and escapes the text', () => {
        const h = debriefHtml({ lang: 'es', data: META });
        expect(h).toContain('data-source="meta"');
        expect(h).toContain('AI · muse-spark-1.3');
        expect(h).toContain('verify: NFPA 110');
        expect(h).toContain('&lt;script&gt;');
        expect(h).not.toContain('<script>');
        expect(h).toContain('AI calls today 1 / 20');
    });

    it('deterministic, loading and error states', () => {
        expect(debriefHtml({ data: { source: 'deterministic', text: 't', label: 'Deterministic', note: 'no key' } }))
            .toContain('DETERMINISTIC');
        expect(debriefHtml({ loading: true })).toContain('Preparing');
        expect(debriefHtml({ error: 'Debrief unavailable: x' })).toContain('data-source="error"');
    });

    it('appears only on a finished drill', () => {
        expect(trainingHtml({ drills: [], view: DONE })).toContain('Instructor debrief');
        expect(trainingHtml({ drills: [], view: { active: false, session: null } })).not.toContain('Instructor debrief');
    });
});

describe('Power view wiring (AI-1)', () => {
    afterEach(() => { __power_test__.stopTraining(); vi.unstubAllGlobals(); document.body.innerHTML = ''; });

    it('posts the language and shows the result', async () => {
        const calls = [];
        vi.stubGlobal('fetch', vi.fn(async (url, opts = {}) => {
            calls.push([url, opts.method, opts.body]);
            let body = { active: false, session: null };
            if (url === '/api/training/drills') body = { drills: [{ id: 'DRILL-08', title: 'x', target_s: 1, time_limit_s: 2 }] };
            else if (url === '/api/training/session') body = DONE;
            else if (url === '/api/training/debrief') body = META;
            else if (url === '/api/devices') body = { paths: [], devices: [] };
            else if (url === '/api/alarms') body = { alarms: [], unacked: 0 };
            return { ok: true, status: 200, json: async () => body };
        }));
        document.body.innerHTML = '<div id="view-power"><div id="pwr-training" class="pwr-tr"></div></div>';
        const { loadTraining, onTrainingClick } = __power_test__;
        await loadTraining();
        const tr = document.getElementById('pwr-training');
        await onTrainingClick({ target: tr.querySelector('[data-tr-debrief="es"]') });
        const post = calls.find(([u, m]) => u === '/api/training/debrief' && m === 'POST');
        expect(JSON.parse(post[2])).toMatchObject({ lang: 'es' });
        expect(tr.querySelector('.tr-debrief').getAttribute('data-source')).toBe('meta');
        expect(tr.textContent).toContain('Resumen: bien.');
    });
});
