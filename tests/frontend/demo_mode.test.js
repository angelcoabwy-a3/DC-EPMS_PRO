/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/demo_mode.test.js
 * Meta hackathon demo mode + MOP Verification presentation behavior.
 *
 * Runs with the normal suite — no server, no network, no Meta calls:
 *   .\node_modules\.bin\vitest.cmd run
 *
 * Covers: demo_config resolution + ?demo= override, nav/rail/chrome
 * hiding, slim top bar, unknown-route redirect to default_view,
 * single-photo demo result, zoomBox union+margin math, demo-only
 * keyboard shortcuts, and readback clearing after a verification and
 * after Restart. All fetch traffic is stubbed.
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
    __mop_verify_test__.reset();
    document.body.innerHTML = '';
});

function chromeFixture() {
    document.body.innerHTML = `
        <header class="app-header"><div class="logo">DC-EPMS PRO</div></header>
        <nav class="panel-nav">
            <div class="nav-item" data-route="overview">Overview</div>
            <div class="nav-item" data-route="mop-verify">MOP Verification</div>
            <div class="nav-item" data-route="power">Power</div>
            <div class="nav-section" data-demo-chrome="reports"><button>report</button></div>
        </nav>
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

function mvLayoutFixture() {
    document.body.innerHTML = `
        <div class="view" id="view-mop-verify">
            <div class="mv-layout"><div data-mv-mop>classic</div></div>
        </div>`;
}

const STEPS5 = {
    mop_id: 'MOP-UPS-BYP-DEMO-01',
    version: '1.3',
    operated_labels: ['Q5', 'Q7', 'Q9', 'Q8', 'BYP'],
    initial_state: { Q5: 'CLOSED', Q7: 'CLOSED', Q9: 'CLOSED', Q8: 'OPEN', BYP: 'OPEN' },
    steps: [1, 2, 3, 4, 5].map((id) => ({
        step_id: id,
        panel_label: ['BYP', 'Q8', 'Q9', 'Q7', 'Q5'][id - 1],
        action: 'Do step ' + id + '.',
        expected_state: { Q5: 'CLOSED', Q7: 'CLOSED', Q9: 'CLOSED', Q8: 'CLOSED', BYP: 'CLOSED' },
    })),
};

function reading(handle, box, note) {
    return { mapped: 'CLOSED', raw: '{"handle":"' + handle + '","notes":"' + note + '"}', crop_box: box };
}

const MATCH_BODY_5 = {
    verdict: 'MATCH',
    step_id: 1,
    advanced: true,
    session: { current_step: 2, completed: false },
    differing_labels: [],
    expected_state: { Q5: 'CLOSED', Q7: 'CLOSED', Q9: 'CLOSED', Q8: 'CLOSED', BYP: 'CLOSED' },
    readings: {
        Q5: reading('RIGHT', [100, 100, 200, 250], 'model note Q5'),
        Q7: reading('RIGHT', [100, 260, 200, 410], 'model note Q7'),
        Q9: reading('RIGHT', [100, 420, 200, 570], 'model note Q9'),
        Q8: reading('LEFT', [700, 260, 800, 410], 'model note Q8'),
        BYP: reading('RIGHT', [700, 420, 800, 570], 'model note BYP'),
    },
    sam_boxes: [[0, 0, 100, 100]],
    column_methods: { left: { method: 'split' }, right: { method: 'split' } },
    models: { sam: 'sam-3.1', spark: 'muse-spark-1.3' },
    meta_calls_made: 6,
    latency_s: 9.9,
};

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

    it('demo on removes the nav and rail columns from the layout (zero width)', () => {
        chromeFixture();
        setDemoState(DEMO_ON);
        applyDemoMode();

        expect(document.body.classList.contains('demo-mode')).toBe(true);
        expect(document.querySelector('.panel-nav').style.display).toBe('none');
        expect(document.querySelector('.panel-side').style.display).toBe('none');
    });

    it('demo on keeps a slim top bar: product name, badge and note on one line', () => {
        chromeFixture();
        setDemoState(DEMO_ON);
        applyDemoMode();

        const logo = document.querySelector('.app-header .logo');
        const badge = document.querySelector('.app-header .demo-bar-badge');
        const note = document.querySelector('.app-header .demo-note-inline');
        expect(logo).not.toBeNull();
        expect(badge && badge.textContent).toBe('Built during hackathon');
        expect(note && note.textContent).toBe(DEMO_NOTE_TEXT);
        expect(logo.nextElementSibling).toBe(badge);
        expect(badge.nextElementSibling).toBe(note);

        setDemoState(DEMO_OFF);
        applyDemoMode();
        expect(document.querySelector('.demo-bar-badge')).toBeNull();
        expect(document.querySelector('.demo-note-inline')).toBeNull();
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

describe('demo mode — ?demo=0 applies none of the new presentation', () => {
    it('leaves body, shell and skeleton exactly as today', () => {
        chromeFixture();
        document.body.insertAdjacentHTML('beforeend',
            '<div class="view" id="view-mop-verify">'
            + '<div class="mv-layout"><div data-mv-mop>classic</div></div></div>');
        const off = resolveDemoState(
            { demo_mode: true, allowed_views: ['mop-verify'], default_view: 'mop-verify' }, '?demo=0');
        setDemoState(off);
        applyDemoMode();
        __mop_verify_test__.syncDemoLayout();

        expect(document.body.classList.contains('demo-mode')).toBe(false);
        expect(document.querySelector('.mv-demo')).toBeNull();
        expect(document.querySelector('.mv-layout')).not.toBeNull();
        expect(document.querySelector('.demo-note-inline')).toBeNull();
        expect(document.querySelector('.demo-bar-badge')).toBeNull();
        expect(document.querySelector('.panel-nav').style.display).toBe('');
        expect(document.querySelector('.panel-side').style.display).toBe('');
    });
});

describe('demo presentation — single photo result', () => {
    function demoResultFixture() {
        mvLayoutFixture();
        setDemoState(DEMO_ON);
        __mop_verify_test__.syncDemoLayout();
        __mop_verify_test__.setStepsData(STEPS5);
        __mop_verify_test__.setSession('sess-1', 1);
        __mop_verify_test__.setPhotoForTest(new Blob(['x'], { type: 'image/jpeg' }), 'p.jpg', 1000, 800);
        __mop_verify_test__.applyResult(MATCH_BODY_5);
    }

    it('renders exactly one photo element: preview and result photo are one', () => {
        demoResultFixture();
        const stage = document.querySelector('[data-mv-photo]');
        const photos = stage.querySelectorAll('img, svg');
        expect(photos).toHaveLength(1);
        expect(photos[0].tagName.toLowerCase()).toBe('svg');
        expect(document.querySelectorAll('.mv-preview-img, .mv-photo')).toHaveLength(0);
    });

    it('zooms to the union of crop boxes plus margin, overlay in the same viewBox', () => {
        demoResultFixture();
        const svg = document.querySelector('[data-mv-photo] svg');
        // Union x 100-800 / y 100-570, padded 10% per side: 30 53 840 564.
        expect(svg.getAttribute('viewBox')).toBe('30 53 840 564');
        expect(svg.querySelectorAll('image')).toHaveLength(1);
        expect(svg.querySelectorAll('.mv-crop-rect')).toHaveLength(5);
        expect(document.querySelector('[data-mv-zoom-wrap]').hasAttribute('hidden')).toBe(false);
        expect(document.querySelector('[data-mv-zoom]').checked).toBe(true);
    });

    it('renders six tracker dots, five cards in one row, controls, then footer', () => {
        demoResultFixture();
        expect(document.querySelectorAll('.mv-dot')).toHaveLength(6);
        expect(document.querySelectorAll('[data-mv-cards] .mv-card')).toHaveLength(5);
        expect(document.querySelector('[data-mv-cards] .mv-cards-row')).not.toBeNull();
        const kids = Array.from(document.querySelector('.mv-right').children);
        const idx = (sel) => kids.findIndex((el) => el.matches(sel));
        expect(idx('[data-mv-result]')).toBeLessThan(idx('.mv-controls'));
        expect(idx('.mv-controls')).toBeLessThan(idx('[data-mv-result-foot]'));
        expect(document.querySelector('[data-mv-result-foot]').textContent).toContain('Meta calls');
    });
});

describe('demo zoomBox — union of crop boxes plus margin', () => {
    const { zoomBox } = __mop_verify_test__;

    it('unions the boxes and pads 10 percent per side', () => {
        expect(zoomBox([[100, 100, 200, 250], [700, 420, 800, 570]], 1000, 800, 0.1))
            .toEqual({ x: 30, y: 53, w: 840, h: 564 });
    });

    it('clamps to the image bounds', () => {
        expect(zoomBox([[0, 0, 50, 50]], 100, 100, 0.5)).toEqual({ x: 0, y: 0, w: 75, h: 75 });
    });

    it('returns null without valid boxes or dimensions', () => {
        expect(zoomBox([], 100, 100, 0.1)).toBeNull();
        expect(zoomBox([['a', 'b', 'c', 'd']], 100, 100, 0.1)).toBeNull();
        expect(zoomBox([[0, 0, 10, 10]], 0, 100, 0.1)).toBeNull();
    });

    it('defaults to a 10 percent margin', () => {
        expect(zoomBox([[100, 100, 200, 200]], 1000, 1000)).toEqual({ x: 90, y: 90, w: 120, h: 120 });
    });
});

describe('demo shortcuts — 1-5, Enter, R outside text fields only', () => {
    function demoWiredFixture() {
        mvLayoutFixture();
        setDemoState(DEMO_ON);
        __mop_verify_test__.syncDemoLayout();
        __mop_verify_test__.setStepsData(STEPS5);
    }

    function stubObjectUrls() {
        const realCreate = URL.createObjectURL;
        const realRevoke = URL.revokeObjectURL;
        URL.createObjectURL = () => 'blob:test/stub';
        URL.revokeObjectURL = () => {};
        return () => { URL.createObjectURL = realCreate; URL.revokeObjectURL = realRevoke; };
    }

    it('digits 1-5 load the samples in shown order', async () => {
        demoWiredFixture();
        const seen = [];
        const realFetch = globalThis.fetch;
        globalThis.fetch = async (url) => {
            seen.push(String(url));
            return { ok: true, blob: async () => new Blob(['x'], { type: 'image/jpeg' }) };
        };
        const restoreUrls = stubObjectUrls();
        try {
            document.dispatchEvent(new window.KeyboardEvent('keydown', { key: '2', bubbles: true }));
            await new Promise((r) => setTimeout(r, 20));
        } finally {
            globalThis.fetch = realFetch;
            restoreUrls();
        }
        expect(seen).toEqual(['/assets/demo_photos/' + __mop_verify_test__.SAMPLE_FILES[1]]);
        expect(__mop_verify_test__.getState().hasPhoto).toBe(true);
    });

    it('Enter runs Verify when enabled', async () => {
        demoWiredFixture();
        __mop_verify_test__.setSession('sess-1', 1);
        __mop_verify_test__.setPhotoForTest(new Blob(['x'], { type: 'image/jpeg' }), 'p.jpg', 1000, 800);
        const claim = document.querySelector('[data-mv-claim]');
        claim.value = 'Q8 closed';
        document.querySelector('[data-mv-verify-btn]').disabled = false;
        const realFetch = globalThis.fetch;
        globalThis.fetch = async () => ({
            status: 200,
            ok: true,
            headers: { get: () => null },
            json: async () => MATCH_BODY_5,
        });
        try {
            document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await new Promise((r) => setTimeout(r, 50));
        } finally {
            globalThis.fetch = realFetch;
        }
        expect(claim.value).toBe('');
        expect(__mop_verify_test__.getState().hasResult).toBe(true);
    });

    it('R runs Restart procedure', () => {
        demoWiredFixture();
        __mop_verify_test__.setSession('sess-9', 3);
        const claim = document.querySelector('[data-mv-claim]');
        claim.value = 'stale';
        document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'r', bubbles: true }));
        expect(claim.value).toBe('');
        expect(__mop_verify_test__.getState().currentStep).toBe(0);
    });

    it('shortcuts stay silent inside text fields', async () => {
        demoWiredFixture();
        let calls = 0;
        const realFetch = globalThis.fetch;
        globalThis.fetch = async () => {
            calls += 1;
            return { ok: true, blob: async () => new Blob(['x']) };
        };
        const claim = document.querySelector('[data-mv-claim]');
        claim.value = 'Q';
        try {
            claim.dispatchEvent(new window.KeyboardEvent('keydown', { key: '1', bubbles: true }));
            claim.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            claim.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'r', bubbles: true }));
            await new Promise((r) => setTimeout(r, 20));
        } finally {
            globalThis.fetch = realFetch;
        }
        expect(calls).toBe(0);
        expect(claim.value).toBe('Q');
        expect(__mop_verify_test__.getState().hasPhoto).toBe(false);
    });

    it('shortcuts stay silent when demo mode is off', async () => {
        mvLayoutFixture();
        setDemoState(DEMO_ON);
        __mop_verify_test__.syncDemoLayout(); // wires the document listener
        setDemoState(DEMO_OFF);
        let calls = 0;
        const realFetch = globalThis.fetch;
        globalThis.fetch = async () => {
            calls += 1;
            return { ok: true, blob: async () => new Blob(['x']) };
        };
        try {
            document.dispatchEvent(new window.KeyboardEvent('keydown', { key: '1', bubbles: true }));
            await new Promise((r) => setTimeout(r, 20));
        } finally {
            globalThis.fetch = realFetch;
        }
        expect(calls).toBe(0);
        expect(__mop_verify_test__.getState().hasPhoto).toBe(false);
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
