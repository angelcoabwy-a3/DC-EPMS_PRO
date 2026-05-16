/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/mission_control.test.js
 * ROADMAP V11 T2.4 — Frontend Test Harness.
 *
 *   Bite 1 — harness proof of life (happy-dom + WebGL mock + rAF).
 *   Bite 2 — drill-down state-machine logic (DC-EPMS-MC-001 fix):
 *            navigation decoupling + self-healing _transitioning.
 *
 * three.js is replaced by tests/frontend/three.mock.js — the
 * drill-down tests never need a real WebGL renderer; the scene is
 * dependency-injected through __mc_test__.injectScene.
 * ════════════════════════════════════════════════════════════════ */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// vi.mock is hoisted above all imports by Vitest. Swap the heavy
// three.js bundle for the minimal mock before mission_control.js loads.
vi.mock('/assets/vendor/three.module.min.js', () => import('./three.mock.js'));

import * as THREE from './three.mock.js';
import { __mc_test__ } from '/assets/js/views/mission_control.js';

// ════════════════════════════════════════════════════════════════
//  Bite 1 — harness proof of life
// ════════════════════════════════════════════════════════════════
describe('T2.4 harness — Bite 1 proof of life', () => {
    it('runs inside a happy-dom environment with a live document', () => {
        expect(typeof window).toBe('object');
        expect(typeof document).toBe('object');

        const status = document.createElement('div');
        status.id = 'mc-status';
        status.textContent = 'ready';
        document.body.appendChild(status);

        expect(document.getElementById('mc-status')).not.toBeNull();
        expect(document.getElementById('mc-status').textContent).toBe('ready');

        document.body.innerHTML = '';
    });

    it('has the WebGL context mock installed (setup.js)', () => {
        const canvas = document.createElement('canvas');
        const gl = canvas.getContext('webgl');

        expect(gl).not.toBeNull();
        expect(typeof gl.createBuffer).toBe('function');
        expect(gl.COLOR_BUFFER_BIT).toBe(0);
        expect(() => gl.clear(gl.COLOR_BUFFER_BIT)).not.toThrow();
    });

    it('exposes a usable requestAnimationFrame for timing-based code', async () => {
        const ts = await new Promise((resolve) => requestAnimationFrame(resolve));
        expect(typeof ts).toBe('number');
    });
});

// ════════════════════════════════════════════════════════════════
//  Bite 2 — drill-down logic (DC-EPMS-MC-001)
// ════════════════════════════════════════════════════════════════
const BUILDING_IDS = ['yard', 'building_a', 'building_b', 'building_d'];

function makeMesh(id) {
    return {
        userData: { id },
        position: new THREE.Vector3(0, 0, 0),
        material: { emissiveIntensity: 0 },
    };
}

function makeCamera() {
    return {
        position: new THREE.Vector3(43, 50, 75),
        lookAt: vi.fn(),
        userData: {
            _origPos: new THREE.Vector3(43, 50, 75),
            _origLook: new THREE.Vector3(0, 0, 0),
        },
    };
}

// Stand up a fake scene via dependency injection — no _boot(),
// no WebGLRenderer. `hitId` is the building the fake raycaster hits.
function injectStandardScene(hitId) {
    const buildings = BUILDING_IDS.map((id) => ({ mesh: makeMesh(id) }));
    const hitMesh = hitId
        ? buildings.find((b) => b.mesh.userData.id === hitId).mesh
        : null;
    const raycaster = {
        setFromCamera: vi.fn(),
        intersectObjects: vi.fn(() => (hitMesh ? [{ object: hitMesh }] : [])),
    };
    __mc_test__.injectScene({
        buildings,
        camera: makeCamera(),
        raycaster,
        pointer: { x: 0, y: 0 },
        renderer: {
            domElement: {
                getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 540 }),
                style: {},
            },
        },
        statusEl: { textContent: '', setAttribute() {} },
    });
    return { buildings, hitMesh, raycaster };
}

describe('T2.4 Bite 2 — drill-down logic (DC-EPMS-MC-001)', () => {
    beforeEach(() => {
        // Fake ONLY setTimeout/clearTimeout (the watchdog). rAF is
        // stubbed to a no-op so the cosmetic zoom never advances —
        // every test is then fully deterministic.
        vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
        vi.stubGlobal('requestAnimationFrame', () => 0);
        vi.stubGlobal('cancelAnimationFrame', () => {});

        __mc_test__.reset();
        document.body.innerHTML = '';
        for (const route of ['site_topology', 'rack-heatmap', 'tech-assist']) {
            const nav = document.createElement('div');
            nav.className = 'nav-item';
            nav.setAttribute('data-route', route);
            document.body.appendChild(nav);
        }
    });

    afterEach(() => {
        __mc_test__.reset();
        vi.useRealTimers();
        vi.unstubAllGlobals();
    });

    it('TC1 — a building click navigates immediately, decoupled from the animation', () => {
        injectStandardScene('building_a');
        const navSpy = vi.fn();
        document.querySelector('.nav-item[data-route="rack-heatmap"]')
            .addEventListener('click', navSpy);

        __mc_test__.onClick({ clientX: 400, clientY: 270 });

        // Navigation fired synchronously inside _onClick — no timer,
        // no animation frame required.
        expect(navSpy).toHaveBeenCalledTimes(1);
    });

    it('TC2 — the watchdog self-heals _transitioning even if the rAF chain breaks', () => {
        const { buildings } = injectStandardScene();
        __mc_test__.animateDrillDown(buildings[1].mesh);   // building_a
        expect(__mc_test__.getTransitioning()).toBe(true);

        // rAF is stubbed to a no-op → the `step` chain NEVER advances.
        // Only the faked watchdog setTimeout can clear the flag.
        vi.advanceTimersByTime(1001);   // DURATION 600 + 400 buffer
        expect(__mc_test__.getTransitioning()).toBe(false);
    });

    it('TC3 — _onClick is NOT gated by _transitioning (click works mid-transition)', () => {
        injectStandardScene('building_b');
        __mc_test__.setTransitioning(true);
        const navSpy = vi.fn();
        document.querySelector('.nav-item[data-route="rack-heatmap"]')
            .addEventListener('click', navSpy);

        __mc_test__.onClick({ clientX: 100, clientY: 100 });

        expect(navSpy).toHaveBeenCalledTimes(1);
    });

    it('TC4 — _onPointerMove is NOT gated by _transitioning (hover works mid-transition)', () => {
        const { raycaster } = injectStandardScene('building_a');
        __mc_test__.setTransitioning(true);

        __mc_test__.onPointerMove({ clientX: 200, clientY: 200 });

        // The raycast ran — hover is not deadlocked by the flag.
        expect(raycaster.intersectObjects).toHaveBeenCalled();
    });

    it('TC5 — _stop() clears a stuck _transitioning flag', () => {
        __mc_test__.setTransitioning(true);
        expect(__mc_test__.getTransitioning()).toBe(true);

        __mc_test__.stop();

        expect(__mc_test__.getTransitioning()).toBe(false);
    });

    it('TC6 — _animateDrillDown bails cleanly when the camera is null', () => {
        injectStandardScene('building_a');
        __mc_test__.injectScene({ camera: null });   // camera torn away
        const targetMesh = { position: new THREE.Vector3(0, 0, 0) };

        expect(() => __mc_test__.animateDrillDown(targetMesh)).not.toThrow();
        expect(__mc_test__.getTransitioning()).toBe(false);
    });

    it('TC7 — DRILL_TARGETS maps every building to the correct route', () => {
        expect(__mc_test__.DRILL_TARGETS).toEqual({
            yard:       'site_topology',
            building_a: 'rack-heatmap',
            building_b: 'rack-heatmap',
            building_d: 'tech-assist',
        });
    });
});
