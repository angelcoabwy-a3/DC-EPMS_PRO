/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — frontend/tests/demo_mode.test.js
 * Meta hackathon demo mode + MOP Verification readback/layout behavior.
 *
 * Lives under frontend/ (NOT tests/) so the hackathon demo work adds no
 * files to the pre-existing backend vitest layout. Run it with the
 * sibling config — no server, no network, no Meta calls:
 *   npx vitest run --config frontend/tests/vitest.demo.config.js
 *
 * Covers: demo_config resolution + ?demo= override, nav hiding,
 * unknown-route redirect to default_view, and readback clearing after
 * a verification and after Restart. All fetch traffic is stubbed.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, afterEach } from 'vitest';

import {
    resolveDemoState,
    loadDemoConfig,
    setDemoState,
    guardRoute,
    applyDemoMode,
    DEMO_NOTE_TEXT,
} from '/assets/js/core/demo.js';
import { initRouter, registerRoute } from '/assets/js/core/router.js';
import { __bootstrap_test__ } from '/assets/js/core/bootstrap.js';
import { __mop_verify_test__ } from '/assets/js/views/mop_verify.js';

const DEMO_ON = { active: true, allowed: ['mop-verify'], defaultView: 'mop-verify' };
const DEMO_OFF = { active: false, allowed: ['mop-verify'], defaultView: 'mop-verify' };

afterEach(() => {
    setDemoState(DEMO_OFF);
    document.body.innerHTML = '';
});

function chromeFixture() {
    document.body.innerHTML = `
        <div class="nav-item" data-route="overview">Overview</div>
        <div class="nav-item" data-route="mop-verify">MOP Verification</div>
        <div class="nav-item" data-route="power">Power</div>
        <div class="nav-section" data-demo-chrome="reports"><button>report</button></div>
        <div class="facility-info" data-demo-chrome="facility"><span>chips</span></div>
        <div class="footer-item" data-demo-chrome="footer-telemetry">telemetry</div>
        <div class="status-pill" id="health-pg"></div>
        <div class="status-pill" id="health-stream"></div>
        <section id="activity-strip"></section>
        <aside class="panel-side">
            <div class="telemetry-panel" id="rail-incidents"></div>
            <div class="telemetry-panel" id="rail-sysinfo"></div>
        </aside>
        <div class="view" id="view-overview"></div>
        <div class="view" id="view-mop-verify" hidden>
            <div class="view-hdr"><h2>MOP Verification</h2><div class="view-sub">sub</div></div>
        </div>`;
}

function mvFixture() {
    document.body.innerHTML = `
        <div class="view" id="view-mop-verify">
            <input type="text" data-mv-claim value="">
            <input type="file" data-mv-file>
            <button type="button" data-mv-verify-btn></button>
            <div data-mv-result></div>
            <div data-mv-mop></div>
            <div data-mv-session></div>
            <ol data-mv-stepper></ol>
            <div data-mv-current></div>
            <div data-mv-preview></div>
            <div data-mv-status></div>
        </div>`;
}

describe('demo mode — resolveDemoState (config + ?demo= override)', () => {
    it('turns on from the config file with its allowed views + default', () => {
        const state = resolveDemoState(
            { demo_mode: true, allowed_views: ['mop-verify'], default_view: 'mop-verify' }, '');
        expect(state.active).toBe(true);
        expect(state.allowed).toEqual(['mop-verify']);
        expect(state.defaultView).toBe('mop-verify');
    });

    it('?demo=0 forces demo mode off even when the config says on', () => {
        const state = resolveDemoState(
            { demo_mode: true, allowed_views: ['mop-verify'], default_view: 'mop-verify' }, '?demo=0');
        expect(state.active).toBe(false);
    });

    it('stays off when the config fails to load and no override is given', () => {
        expect(resolveDemoState(null, '').active).toBe(false);
        expect(resolveDemoState(null, '?other=1').active).toBe(false);
    });

    it('?demo=1 forces demo mode on with safe fallbacks when the config is missing', () => {
        const state = resolveDemoState(null, '?demo=1');
        expect(state.active).toBe(true);
        expect(state.allowed).toEqual(['mop-verify']);
        expect(state.defaultView).toBe('mop-verify');
    });
});

describe('demo mode — loadDemoConfig never throws, never touches the network directly', () => {
    it('returns the parsed config on HTTP 200', async () => {
        const data = await loadDemoConfig(async () => ({
            ok: true,
            json: async () => ({ demo_mode: true }),
        }));
        expect(data).toEqual({ demo_mode: true });
    });

    it('returns null when the fetch rejects (missing file, offline)', async () => {
        const data = await loadDemoConfig(async () => { throw new Error('boom'); });
        expect(data).toBeNull();
    });

    it('returns null on non-200 responses', async () => {
        const data = await loadDemoConfig(async () => ({ ok: false, status: 404 }));
        expect(data).toBeNull();
    });
});

describe('demo mode — applyDemoMode hides pre-existing chrome', () => {
    it('demo on hides non-allowed nav entries and pre-existing chrome, keeps mop-verify', () => {
        chromeFixture();
        setDemoState(DEMO_ON);
        applyDemoMode();

        expect(document.querySelector('[data-route="overview"]').style.display).toBe('none');
        expect(document.querySelector('[data-route="power"]').style.display).toBe('none');
        expect(document.querySelector('[data-route="mop-verify"]').style.display).toBe('');
        expect(document.querySelector('[data-demo-chrome="reports"]').style.display).toBe('none');
        expect(document.querySelector('[data-demo-chrome="facility"]').style.display).toBe('none');
        expect(document.querySelector('[data-demo-chrome="footer-telemetry"]').style.display).toBe('none');
        expect(document.getElementById('health-pg').style.display).toBe('none');
        expect(document.getElementById('health-stream').style.display).toBe('none');
        expect(document.getElementById('activity-strip').style.display).toBe('none');
        expect(document.getElementById('rail-incidents').style.display).toBe('none');
        expect(document.getElementById('rail-sysinfo').style.display).toBe('none');

        const note = document.querySelector('#view-mop-verify .view-hdr .demo-note');
        expect(note && note.textContent).toBe(DEMO_NOTE_TEXT);
    });

    it('?demo=0 (demo off) shows every nav entry and removes the demo note', () => {
        chromeFixture();
        setDemoState(DEMO_ON);
        applyDemoMode();
        // Flip off, as ?demo=0 resolves, and re-apply: full app restored.
        setDemoState({ active: false, allowed: ['mop-verify'], defaultView: 'mop-verify' });
        applyDemoMode();

        for (const el of document.querySelectorAll('.nav-item[data-route]')) {
            expect(el.style.display).toBe('');
        }
        expect(document.querySelector('[data-demo-chrome="reports"]').style.display).toBe('');
        expect(document.querySelector('[data-demo-chrome="facility"]').style.display).toBe('');
        expect(document.querySelector('[data-demo-chrome="footer-telemetry"]').style.display).toBe('');
        expect(document.getElementById('health-pg').style.display).toBe('');
        expect(document.getElementById('activity-strip').style.display).toBe('');
        expect(document.getElementById('rail-incidents').style.display).toBe('');
        expect(document.querySelector('.demo-note')).toBeNull();
    });
});

describe('demo mode — body class drives the layout fix', () => {
    it('adds demo-mode to body when on, removes it when ?demo=0 resolves off', () => {
        chromeFixture();
        setDemoState(DEMO_ON);
        applyDemoMode();
        expect(document.body.classList.contains('demo-mode')).toBe(true);

        const off = resolveDemoState(
            { demo_mode: true, allowed_views: ['mop-verify'], default_view: 'mop-verify' }, '?demo=0');
        setDemoState(off);
        applyDemoMode();
        expect(document.body.classList.contains('demo-mode')).toBe(false);
    });
});

describe('demo mode — routing guard', () => {
    it('guardRoute passes everything through when demo mode is off', () => {
        setDemoState(DEMO_OFF);
        expect(guardRoute('overview')).toBe('overview');
        expect(guardRoute('no-such-route')).toBe('no-such-route');
    });

    it('an unknown route redirects to default_view in demo mode (no blank page)', () => {
        chromeFixture();
        initRouter();
        registerRoute('mop-verify', { viewId: 'view-mop-verify' });
        setDemoState(DEMO_ON);

        __bootstrap_test__.navigateTo('no-such-route');

        expect(document.getElementById('view-mop-verify').hasAttribute('hidden')).toBe(false);
        expect(document.getElementById('view-overview').hasAttribute('hidden')).toBe(true);
    });
});

describe('mop-verify — operator readback is cleared', () => {
    const STEPS = {
        mop_id: 'MOP-UPS-BYP-DEMO-01',
        version: '1.3',
        operated_labels: ['Q8'],
        initial_state: { Q8: 'OPEN' },
        steps: [{ step_id: 1, panel_label: 'Q8', action: 'Close Q8.', expected_state: { Q8: 'CLOSED' } }],
    };
    const MATCH_BODY = {
        verdict: 'MATCH',
        step_id: 1,
        advanced: true,
        session: { current_step: 2, completed: false },
        differing_labels: [],
        expected_state: { Q8: 'CLOSED' },
        readings: { Q8: { mapped: 'CLOSED', raw: '{"handle":"LEFT","notes":"n"}', crop_box: [1, 2, 3, 4] } },
        sam_boxes: [[0, 0, 10, 10]],
        column_methods: { left: { method: 'split' }, right: { method: 'split' } },
        models: { sam: 'sam-3.1', spark: 'muse-spark-1.3' },
        meta_calls_made: 6,
        latency_s: 9.9,
    };

    it('clears the readback field after a verification', async () => {
        mvFixture();
        __mop_verify_test__.reset();
        __mop_verify_test__.setStepsData(STEPS);
        __mop_verify_test__.setSession('sess-1', 1);
        __mop_verify_test__.setPhotoForTest(new Blob(['x'], { type: 'image/jpeg' }), 'p.jpg', 100, 100);
        const claim = document.querySelector('[data-mv-claim]');
        claim.value = 'Q8 closed';

        const realFetch = globalThis.fetch;
        globalThis.fetch = async () => ({
            status: 200,
            ok: true,
            headers: { get: () => null },
            json: async () => MATCH_BODY,
        });
        try {
            await __mop_verify_test__.runVerification();
        } finally {
            globalThis.fetch = realFetch;
        }

        expect(claim.value).toBe('');
    });

    it('clears the readback field on Restart procedure', () => {
        mvFixture();
        __mop_verify_test__.reset();
        const claim = document.querySelector('[data-mv-claim]');
        claim.value = 'stale claim';
        __mop_verify_test__.restartProcedure();
        expect(claim.value).toBe('');
    });
});
