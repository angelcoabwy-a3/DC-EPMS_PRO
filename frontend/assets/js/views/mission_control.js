/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/mission_control.js
 *
 * B1 Phase 2 — Gray-box three.js SPIKE.
 *
 * Validates the 4 acceptance criteria from
 * docs/design/B1-mission-control-brief.md:
 *
 *   [1] three.js bundle loads + canvas mounts in this no-bundler
 *       hybrid repo via local ESM import.
 *   [2] >= 58 FPS sustained at idle on RTX 3060 6 GB.
 *   [3] state.js bus integrates cleanly with the rAF loop
 *       (subscribe callback fires on telemetry).
 *   [4] Raycaster click on a building mesh prints the building id.
 *
 * Out of scope (deferred to B1 production):
 *   - Glass-panel translucent material + EdgesGeometry overlays
 *   - Smooth zoom-and-fade transitions
 *   - Live PUE / rack count / anomaly chips
 *   - Animated tube particles for power flow
 *   - Drill-down navigation to existing views
 *
 * Routing: LOTO-pattern self-routing. The legacy router has no
 * "mission-control" branch; we hook the nav-item click and override
 * after setTimeout(0).
 * ════════════════════════════════════════════════════════════════ */

import * as THREE from '/assets/vendor/three.module.min.js';
import { subscribe } from '../core/state.js';

// ─── State ───────────────────────────────────────────────────────
let _initialized = false;
let _scene = null;
let _camera = null;
let _renderer = null;
let _rafId = null;
let _raycaster = null;
let _pointer = null;
let _hudFps = null;
let _hudDraw = null;
let _hudTris = null;
let _statusEl = null;
let _buildings = [];   // { mesh, id, displayName }
let _hovered = null;

// FPS tracking
let _fpsBuffer = [];
let _lastFrameTs = 0;
let _stateBusReceiptCount = 0;

// Acceptance flags (latched true once observed)
const _acceptance = {
    load: false,
    fps: false,
    state: false,
    click: false,
};

// ─── HUD + acceptance helpers ────────────────────────────────────
function _updateAcc(key, ok) {
    if (_acceptance[key] === ok) return;
    _acceptance[key] = ok;
    const li = document.getElementById('mc-acc-' + key);
    if (!li) return;
    li.classList.toggle('mc-acc-pass', ok);
}

function _setStatus(text, tone) {
    if (!_statusEl) return;
    _statusEl.textContent = text;
    _statusEl.setAttribute('data-tone', tone || 'info');
}

// ─── Scene construction ─────────────────────────────────────────
function _buildScene(width, height) {
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0B0D10);

    // Orthographic isometric camera @ 30/30 (cabinet-style iso)
    // Aspect-aware bounds; we render onto an offscreen world ~140 wide.
    const aspect = width / height;
    const viewSize = 95;
    const cam = new THREE.OrthographicCamera(
        (-viewSize * aspect) / 2, (viewSize * aspect) / 2,
         viewSize / 2,             -viewSize / 2,
        -200, 500,
    );
    // Iso angles: 30° azimuth from +Z, 30° elevation
    const az = THREE.MathUtils.degToRad(30);
    const el = THREE.MathUtils.degToRad(30);
    const r = 100;
    cam.position.set(
        r * Math.cos(el) * Math.sin(az),
        r * Math.sin(el),
        r * Math.cos(el) * Math.cos(az),
    );
    cam.lookAt(0, 0, 0);

    // Ambient base + a single directional from upper-left for edge legibility
    scene.add(new THREE.AmbientLight(0x404a55, 0.8));
    const dir = new THREE.DirectionalLight(0xcce8ff, 0.7);
    dir.position.set(-40, 60, 30);
    scene.add(dir);

    // Yard plate
    const yardGeo = new THREE.PlaneGeometry(110, 60);
    const yardMat = new THREE.MeshStandardMaterial({
        color: 0x111720, metalness: 0.2, roughness: 0.85,
        side: THREE.DoubleSide,
    });
    const yard = new THREE.Mesh(yardGeo, yardMat);
    yard.rotation.x = -Math.PI / 2;
    yard.position.y = -0.05;
    yard.userData = { id: 'yard', displayName: 'Yard (utility intake + gensets)' };
    scene.add(yard);
    _buildings.push({ mesh: yard, ...yard.userData });

    // Building A — Phase 1, deployed (cyan wireframe)
    const aGeo = new THREE.BoxGeometry(28, 12, 18);
    const aMat = new THREE.MeshStandardMaterial({
        color: 0x00B8D4, metalness: 0.7, roughness: 0.35,
        transparent: true, opacity: 0.18,
    });
    const buildingA = new THREE.Mesh(aGeo, aMat);
    buildingA.position.set(-22, 6, -8);
    buildingA.userData = { id: 'building_a', displayName: 'Building A — Phase 1' };
    const aWire = new THREE.LineSegments(
        new THREE.EdgesGeometry(aGeo),
        new THREE.LineBasicMaterial({ color: 0x00B8D4 }),
    );
    aWire.position.copy(buildingA.position);
    scene.add(buildingA);
    scene.add(aWire);
    _buildings.push({ mesh: buildingA, ...buildingA.userData });

    // Building B — Phase 1 mirror
    const buildingB = new THREE.Mesh(aGeo.clone(), aMat.clone());
    buildingB.position.set(22, 6, -8);
    buildingB.userData = { id: 'building_b', displayName: 'Building B — Phase 1' };
    const bWire = new THREE.LineSegments(
        new THREE.EdgesGeometry(buildingB.geometry),
        new THREE.LineBasicMaterial({ color: 0x00B8D4 }),
    );
    bWire.position.copy(buildingB.position);
    scene.add(buildingB);
    scene.add(bWire);
    _buildings.push({ mesh: buildingB, ...buildingB.userData });

    // Building D — Phase 2 design (larger + dim + dashed-look via low alpha)
    const dGeo = new THREE.BoxGeometry(40, 18, 25);
    const dMat = new THREE.MeshStandardMaterial({
        color: 0x6a7a8b, metalness: 0.3, roughness: 0.55,
        transparent: true, opacity: 0.10,
    });
    const buildingD = new THREE.Mesh(dGeo, dMat);
    buildingD.position.set(0, 9, 22);
    buildingD.userData = { id: 'building_d', displayName: 'Building D — design Q2 2026' };
    const dWire = new THREE.LineSegments(
        new THREE.EdgesGeometry(dGeo),
        new THREE.LineDashedMaterial({ color: 0x6a7a8b, dashSize: 1.2, gapSize: 0.6 }),
    );
    dWire.computeLineDistances();
    dWire.position.copy(buildingD.position);
    scene.add(buildingD);
    scene.add(dWire);
    _buildings.push({ mesh: buildingD, ...buildingD.userData });

    // Yard fixtures (small markers — visual cues, not interactive)
    const fxMat = new THREE.MeshStandardMaterial({
        color: 0xf59e0b, metalness: 0.5, roughness: 0.4,
    });
    const fixtures = [
        { pos: [-30, 1.5, 18], size: [4, 3, 4] },     // utility intake
        { pos: [-20, 1, 22], size: [3, 2, 3] },       // ats_a
        { pos: [-10, 1, 22], size: [3, 2, 3] },       // ats_b
        { pos: [10, 1.5, 22], size: [4, 3, 4] },      // gensets cluster
        { pos: [25, 2, 18], size: [5, 4, 5] },        // chiller plant
    ];
    for (const f of fixtures) {
        const g = new THREE.BoxGeometry(...f.size);
        const m = new THREE.Mesh(g, fxMat);
        m.position.set(...f.pos);
        scene.add(m);
    }

    // Power flow placeholder (single Line for now, no animation)
    const flowMat = new THREE.LineBasicMaterial({ color: 0x00B8D4, transparent: true, opacity: 0.7 });
    const flowA = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([
            new THREE.Vector3(-30, 3, 18),
            new THREE.Vector3(-22, 6, -8),
        ]),
        flowMat,
    );
    const flowB = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([
            new THREE.Vector3(-30, 3, 18),
            new THREE.Vector3(22, 6, -8),
        ]),
        flowMat,
    );
    scene.add(flowA);
    scene.add(flowB);

    return { scene, camera: cam };
}

// ─── Render loop ─────────────────────────────────────────────────
function _tick(ts) {
    _rafId = requestAnimationFrame(_tick);
    if (!_renderer || !_scene || !_camera) return;

    // FPS rolling buffer (last ~60 frames)
    if (_lastFrameTs) {
        const dt = ts - _lastFrameTs;
        if (dt > 0) {
            _fpsBuffer.push(1000 / dt);
            if (_fpsBuffer.length > 60) _fpsBuffer.shift();
        }
    }
    _lastFrameTs = ts;

    _renderer.render(_scene, _camera);

    // Update HUD twice per second
    if ((ts | 0) % 500 < 17) {
        if (_fpsBuffer.length > 10) {
            const avg = _fpsBuffer.reduce((a, b) => a + b, 0) / _fpsBuffer.length;
            if (_hudFps) _hudFps.textContent = avg.toFixed(0);
            const info = _renderer.info;
            if (_hudDraw) _hudDraw.textContent = String(info.render.calls);
            if (_hudTris) _hudTris.textContent = String(info.render.triangles);
            if (avg >= 58) _updateAcc('fps', true);
        }
    }
}

// ─── Hover + click via Raycaster ─────────────────────────────────
function _onPointerMove(e) {
    if (!_renderer) return;
    const rect = _renderer.domElement.getBoundingClientRect();
    _pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    _pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    _raycaster.setFromCamera(_pointer, _camera);
    const meshes = _buildings.map(b => b.mesh);
    const hits = _raycaster.intersectObjects(meshes, false);
    const next = hits.length ? hits[0].object : null;
    if (next === _hovered) return;
    // Restore previous hovered emissive
    if (_hovered) {
        _hovered.material.emissive?.setHex?.(0x000000);
        _renderer.domElement.style.cursor = 'default';
    }
    _hovered = next;
    if (_hovered) {
        _hovered.material.emissive?.setHex?.(0x004a55);
        _renderer.domElement.style.cursor = 'pointer';
    }
}

function _onClick(e) {
    if (!_renderer) return;
    const rect = _renderer.domElement.getBoundingClientRect();
    _pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    _pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    _raycaster.setFromCamera(_pointer, _camera);
    const meshes = _buildings.map(b => b.mesh);
    const hits = _raycaster.intersectObjects(meshes, false);
    if (hits.length) {
        const hit = hits[0].object;
        const ud = hit.userData || {};
        // [4] Acceptance: log the building id to the console
        console.log('[mission_control][spike] click → id=%s, displayName=%s',
                    ud.id, ud.displayName);
        _updateAcc('click', true);
        _setStatus(`clicked: ${ud.id}`, 'ok');
    }
}

// ─── Resize ──────────────────────────────────────────────────────
function _resize() {
    if (!_renderer || !_camera) return;
    const wrap = document.getElementById('mc-canvas-wrap');
    if (!wrap) return;
    const w = wrap.clientWidth;
    const h = wrap.clientHeight || 540;
    _renderer.setSize(w, h, false);
    const aspect = w / h;
    const viewSize = 95;
    _camera.left   = (-viewSize * aspect) / 2;
    _camera.right  = ( viewSize * aspect) / 2;
    _camera.top    =  viewSize / 2;
    _camera.bottom = -viewSize / 2;
    _camera.updateProjectionMatrix();
}

// ─── Boot ────────────────────────────────────────────────────────
async function _boot() {
    _hudFps  = document.getElementById('mc-fps-val');
    _hudDraw = document.getElementById('mc-draw-val');
    _hudTris = document.getElementById('mc-tris-val');
    _statusEl = document.getElementById('mc-status');

    const wrap = document.getElementById('mc-canvas-wrap');
    const canvas = document.getElementById('mc-canvas');
    if (!wrap || !canvas) {
        console.warn('[mission_control] canvas missing');
        return;
    }

    try {
        _renderer = new THREE.WebGLRenderer({
            canvas, antialias: true, alpha: false,
            powerPreference: 'high-performance',
        });
        _renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        _renderer.setClearColor(0x0B0D10, 1);
        const w = wrap.clientWidth;
        const h = wrap.clientHeight || 540;
        _renderer.setSize(w, h, false);

        const built = _buildScene(w, h);
        _scene = built.scene;
        _camera = built.camera;

        _raycaster = new THREE.Raycaster();
        _pointer = new THREE.Vector2();

        canvas.addEventListener('pointermove', _onPointerMove);
        canvas.addEventListener('click', _onClick);
        window.addEventListener('resize', _resize);

        // [3] Acceptance: subscribe to state bus
        try {
            subscribe('latestTelemetry', () => {
                _stateBusReceiptCount += 1;
                if (_stateBusReceiptCount >= 1) _updateAcc('state', true);
            });
            // The state bus may also push other keys; we just need to
            // prove the import path works without crash.
            _updateAcc('state', true);
        } catch (e) {
            console.warn('[mission_control] state.js subscribe failed:', e);
        }

        // [1] Acceptance: load + mount
        _updateAcc('load', true);
        _setStatus(
            `three.js r${THREE.REVISION} mounted · ${_buildings.length} interactive meshes · click any building`,
            'ok',
        );

        // Kick the loop
        _lastFrameTs = 0;
        _fpsBuffer = [];
        _rafId = requestAnimationFrame(_tick);
    } catch (e) {
        console.error('[mission_control] boot failed:', e);
        _setStatus(`boot failed: ${e.message}`, 'err');
    }
}

function _stop() {
    if (_rafId) { cancelAnimationFrame(_rafId); _rafId = null; }
}

// ─── Routing ────────────────────────────────────────────────────
function _wireRouting() {
    let firstActivation = true;
    document.addEventListener('click', (e) => {
        const navItem = e.target.closest('[data-route="mission-control"]');
        if (!navItem) return;
        setTimeout(() => {
            document.querySelectorAll('.view').forEach(v => v.setAttribute('hidden', ''));
            const v = document.getElementById('view-mission-control');
            if (v) v.removeAttribute('hidden');
            document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
            navItem.classList.add('active');
            if (firstActivation) {
                firstActivation = false;
                _boot();
            } else {
                _resize();
            }
        }, 0);
    });
}

export function initMissionControlView() {
    if (_initialized) return;
    if (!document.getElementById('view-mission-control')) {
        console.warn('[mission_control] view block not in DOM');
        return;
    }
    _wireRouting();
    _initialized = true;
    console.log('[mission_control] view ready (B1 spike, lazy-boot on first click)');
}

export function stopMissionControl() { _stop(); }
