/**
 * UI-1: the Power SLD viewport toolbar, inspector toggle, farm LOD
 * through the viewport and the drill HUD (views/power.js).
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { __power_test__ } from '/assets/js/views/power.js';
import { SLD_PRESETS, fitPreset, fmtVb } from '/assets/js/core/sld_viewport.js';

const P = __power_test__;

function mount() {
    document.body.innerHTML = '<div id="view-power"><div class="sld-stage-row">'
        + '<div class="pid-canvas"><svg class="pid-svg"></svg></div>'
        + '<aside class="sld-info-panel"></aside></div></div>';
    const svg = document.querySelector('.pid-svg');
    svg.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1200, height: 600 });
    P.renderFlatSld();
    P.buildViewport(svg);
    return svg;
}

describe('Power SLD viewport (UI-1)', () => {
    beforeEach(() => { P.reset(); try { localStorage.clear(); } catch (_e) { /* none */ } });

    it('adds a toolbar with the named views and opens on Phase 1', () => {
        const svg = mount();
        const bar = document.getElementById('pwr-vp');
        expect(bar).not.toBeNull();
        for (const k of Object.keys(SLD_PRESETS)) expect(bar.querySelector(`[data-vp="${k}"]`)).not.toBeNull();
        expect(bar.querySelector('[data-vp="p1"]').getAttribute('aria-pressed')).toBe('true');
        expect(svg.getAttribute('viewBox')).toBe(fmtVb(fitPreset(SLD_PRESETS.p1.vb, 1200, 600)));
    });

    it('a view button switches the viewBox and is remembered', () => {
        const svg = mount();
        document.querySelector('[data-vp="b"]').click();
        expect(svg.getAttribute('viewBox')).toBe(fmtVb(fitPreset(SLD_PRESETS.b.vb, 1200, 600)));
        expect(localStorage.getItem('dcepms.sld.view')).toBe('b');
    });

    it('the farm LOD focuses through the viewport and returns to the last view', () => {
        const svg = mount();
        document.querySelector('[data-vp="a"]').click();
        P.onFlatClick({ target: document.querySelector('[data-farm-toggle]') });
        expect(P.getViewport().preset).toBe('farm');
        expect(svg.innerHTML).toContain('data-farm-unit="G01"');
        P.onFlatClick({ target: document.querySelector('[data-farm-back]') });
        expect(P.getViewport().preset).toBe('a');
    });

    it('the inspector toggle hides the side panel and is remembered', () => {
        mount();
        const open0 = P.isInspectorOpen();
        document.querySelector('[data-vp-insp]').click();
        expect(P.isInspectorOpen()).toBe(!open0);
        expect(document.getElementById('view-power').classList.contains('insp-closed')).toBe(open0);
        expect(localStorage.getItem('dcepms.sld.inspector')).toBe(open0 ? '0' : '1');
    });

    it('the drill HUD shows the current step and escapes drill text', () => {
        mount();
        P.setTrainingView({
            active: true,
            session: {
                started_ms: Date.now() - 65000,
                drill: { id: 'DRILL-01', time_limit_s: 1800 },
                steps: [{ text: 'Ack', done: true }, { text: '<b>Start</b> gens', current: true }, { text: 'x' }],
            },
        });
        P.renderHud();
        const hud = document.getElementById('pwr-hud');
        expect(hud.hidden).toBe(false);
        expect(hud.textContent).toContain('step 2 / 3');
        expect(hud.textContent).toContain('01:05');
        expect(hud.innerHTML).toContain('&lt;b&gt;Start');
        P.setTrainingView({ active: false, session: null });
        P.renderHud();
        expect(hud.hidden).toBe(true);
    });
});

describe('HUD alarm shortcut (UI-1)', () => {
    beforeEach(() => { P.reset(); });
    it('shows the unacknowledged count with ACK ALL, outside drills too', () => {
        mount();
        P.setTrainingView(null);
        P.setLiveAlarms({ alarms: [{ id: 'A1', state: 'UNACK' }, { id: 'A2', state: 'ACKED' }] });
        P.renderHud();
        const hud = document.getElementById('pwr-hud');
        expect(hud.hidden).toBe(false);
        expect(hud.textContent).toContain('1 unacknowledged alarm');
        expect(hud.querySelector('[data-ack-all]')).not.toBeNull();
        P.setLiveAlarms({ alarms: [] });
        P.renderHud();
        expect(hud.hidden).toBe(true);
    });
});
