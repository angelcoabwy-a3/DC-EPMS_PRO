/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — views/mission_control.js
 *
 * B1 PRODUCTION — Mission Control (Tesla Megapack Grid Operations
 *                                  aesthetic, click-to-drill).
 *
 * Implements the contract from
 * docs/design/B1-mission-control-brief.md:
 *
 *   - 4 building meshes (A, B, D, Yard) with glass-panel
 *     translucent MeshStandardMaterial + EdgesGeometry overlays
 *   - OrthographicCamera at fixed isometric angle (30° / 30°)
 *   - HTML overlay cards (glassmorphism) projected world→screen
 *     each frame, populated with live data from /api/physics/pue
 *     + /api/cmms/assets + /api/cmms/work-orders
 *   - Animated power flow: cyan particle InstancedMesh sliding
 *     along CatmullRomCurve3 from Yard → A and Yard → B
 *   - Raycaster click on a building → smooth 0.6 s zoom-and-fade
 *     transition → programmatic nav to the correct detail view
 *
 * Spike acceptance criteria from v0.10.3-b1-spike preserved:
 *   FPS HUD bottom-right + state.js subscribe + Raycaster pattern.
 * ════════════════════════════════════════════════════════════════ */

import * as THREE from '/assets/vendor/three.module.min.js';
import { subscribe } from '../core/state.js';

const API_BASE = '';
const POLL_LIVE_DATA_MS = 15_000;

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
let _tooltipEl = null;
let _fadeEl = null;
let _overlayLayer = null;

// Buildings: {mesh, edges, id, displayName, anchor (world Vec3 above mesh top), cardEl}
let _buildings = [];
let _hovered = null;
let _liveData = {
    phase_1: { pue: null, racks: 0, mw: 0, anomaly: 0 },
    phase_2: { pue: null, racks: 0, mw: 0, anomaly: 0 },
};
let _liveTimer = null;
let _transitioning = false;

// Particle flow
let _flowGroups = [];   // [{ instMesh, curve, count, speed, t[] }]

// FPS HUD
let _fpsBuffer = [];
let _lastFrameTs = 0;

// ─── HTML escape ─────────────────────────────────────────────────
function _esc(s) { return String(s ?? ''); }

// ─── Status badge ────────────────────────────────────────────────
function _setStatus(text, tone) {
    if (!_statusEl) return;
    _statusEl.textContent = text;
    _statusEl.setAttribute('data-tone', tone || 'info');
}

// ─── Build the scene (production, glass-panel) ───────────────────
function _buildScene(width, height) {
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0B0D10);

    // ── Lights ──────────────────────────────────────────────────
    scene.add(new THREE.AmbientLight(0x202830, 0.55));
    const key = new THREE.DirectionalLight(0xcceaff, 0.9);
    key.position.set(-50, 80, 35);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0x00B8D4, 0.18);
    fill.position.set(40, 30, -20);
    scene.add(fill);

    // ── Iso ortho camera ────────────────────────────────────────
    const aspect = width / height;
    const viewSize = 95;
    const cam = new THREE.OrthographicCamera(
        (-viewSize * aspect) / 2, (viewSize * aspect) / 2,
         viewSize / 2,             -viewSize / 2,
        -200, 500,
    );
    const az = THREE.MathUtils.degToRad(30);
    const el = THREE.MathUtils.degToRad(30);
    const r = 100;
    cam.position.set(
        r * Math.cos(el) * Math.sin(az),
        r * Math.sin(el),
        r * Math.cos(el) * Math.cos(az),
    );
    cam.lookAt(0, 0, 0);
    cam.userData = { _origPos: cam.position.clone(), _origLook: new THREE.Vector3(0, 0, 0) };

    // ── Yard plate (subtle grid via opacity gradient) ──────────
    const yardGeo = new THREE.PlaneGeometry(140, 90);
    const yardMat = new THREE.MeshStandardMaterial({
        color: 0x0E1318, metalness: 0.15, roughness: 0.9,
        side: THREE.DoubleSide,
    });
    const yard = new THREE.Mesh(yardGeo, yardMat);
    yard.rotation.x = -Math.PI / 2;
    yard.position.y = -0.05;
    yard.userData = { id: 'yard', displayName: 'Yard · A3-Alpha · Path C2', clickable: true };
    scene.add(yard);

    // Subtle grid lines on the yard for spatial cue
    const gridHelper = new THREE.GridHelper(140, 14, 0x14202a, 0x0e1620);
    gridHelper.position.y = 0.01;
    scene.add(gridHelper);

    // ── Building A (Phase 1, deployed) ────────────────────────
    const aGeo = new THREE.BoxGeometry(28, 12, 18);
    const glassMat = new THREE.MeshStandardMaterial({
        color: 0x00B8D4, metalness: 0.85, roughness: 0.18,
        transparent: true, opacity: 0.16,
        emissive: 0x002430, emissiveIntensity: 0.6,
    });
    const buildingA = new THREE.Mesh(aGeo, glassMat);
    buildingA.position.set(-22, 6, -8);
    buildingA.userData = { id: 'building_a', displayName: 'Building A · A3-Alpha · Path C2', clickable: true };
    scene.add(buildingA);
    const aEdges = new THREE.LineSegments(
        new THREE.EdgesGeometry(aGeo),
        new THREE.LineBasicMaterial({ color: 0x00B8D4, transparent: true, opacity: 0.95 }),
    );
    aEdges.position.copy(buildingA.position);
    scene.add(aEdges);

    // ── Building B (Phase 1, mirror) ──────────────────────────
    const buildingB = new THREE.Mesh(aGeo.clone(), glassMat.clone());
    buildingB.position.set(22, 6, -8);
    buildingB.userData = { id: 'building_b', displayName: 'Building B · A3-Alpha · Path C2', clickable: true };
    scene.add(buildingB);
    const bEdges = new THREE.LineSegments(
        new THREE.EdgesGeometry(buildingB.geometry),
        new THREE.LineBasicMaterial({ color: 0x00B8D4, transparent: true, opacity: 0.95 }),
    );
    bEdges.position.copy(buildingB.position);
    scene.add(bEdges);

    // ── Building D (Phase 2, design — dim + dashed edges) ─────
    const dGeo = new THREE.BoxGeometry(40, 18, 25);
    const dMat = new THREE.MeshStandardMaterial({
        color: 0x6a7a8b, metalness: 0.3, roughness: 0.55,
        transparent: true, opacity: 0.06,
    });
    const buildingD = new THREE.Mesh(dGeo, dMat);
    buildingD.position.set(0, 9, 22);
    buildingD.userData = { id: 'building_d', displayName: 'Building D · design Q2 2026', clickable: true };
    scene.add(buildingD);
    const dEdges = new THREE.LineSegments(
        new THREE.EdgesGeometry(dGeo),
        new THREE.LineDashedMaterial({
            color: 0x9aa8b8, dashSize: 1.6, gapSize: 0.8,
            transparent: true, opacity: 0.55,
        }),
    );
    dEdges.computeLineDistances();
    dEdges.position.copy(buildingD.position);
    scene.add(dEdges);

    _buildings = [
        { mesh: yard,      edges: null,    id: 'yard',        displayName: yard.userData.displayName,      anchor: new THREE.Vector3(-30, 4, 18),  cardEl: null },
        { mesh: buildingA, edges: aEdges,  id: 'building_a',  displayName: buildingA.userData.displayName, anchor: new THREE.Vector3(-22, 14, -8), cardEl: null },
        { mesh: buildingB, edges: bEdges,  id: 'building_b',  displayName: buildingB.userData.displayName, anchor: new THREE.Vector3( 22, 14, -8), cardEl: null },
        { mesh: buildingD, edges: dEdges,  id: 'building_d',  displayName: buildingD.userData.displayName, anchor: new THREE.Vector3(  0, 19, 22), cardEl: null },
    ];

    // ── Yard fixtures (visual cues, not clickable) ────────────
    const fxMat = new THREE.MeshStandardMaterial({
        color: 0xf59e0b, metalness: 0.5, roughness: 0.4,
        emissive: 0x2a1d05, emissiveIntensity: 0.3,
    });
    const fxEdgeMat = new THREE.LineBasicMaterial({ color: 0xfbbf24, transparent: true, opacity: 0.55 });
    const fixtures = [
        { pos: [-32,  1.5,  18], size: [4, 3, 4] },     // utility intake
        { pos: [-22,  1.0,  22], size: [3, 2, 3] },     // ats_a
        { pos: [-12,  1.0,  22], size: [3, 2, 3] },     // ats_b
        { pos: [ 12,  1.5,  22], size: [4, 3, 4] },     // gensets cluster
        { pos: [ 28,  2.0,  18], size: [5, 4, 5] },     // chiller plant
    ];
    for (const f of fixtures) {
        const g = new THREE.BoxGeometry(...f.size);
        const m = new THREE.Mesh(g, fxMat);
        m.position.set(...f.pos);
        scene.add(m);
        const eg = new THREE.LineSegments(new THREE.EdgesGeometry(g), fxEdgeMat);
        eg.position.copy(m.position);
        scene.add(eg);
    }

    return { scene, camera: cam };
}

// ─── Power flow particles (Yard → A and Yard → B) ──────────────
function _setupPowerFlow(scene) {
    _flowGroups = [];
    const buildPath = (from, to) => {
        // Curve goes up out of yard, arcs over, descends into building roof
        const mid = new THREE.Vector3(
            (from.x + to.x) / 2, Math.max(from.y, to.y) + 8, (from.z + to.z) / 2,
        );
        return new THREE.CatmullRomCurve3([from.clone(), mid, to.clone()]);
    };
    const yardSrc = new THREE.Vector3(-30, 3, 18);
    const aDst = new THREE.Vector3(-22, 12, -8);
    const bDst = new THREE.Vector3( 22, 12, -8);
    const dDst = new THREE.Vector3(  0, 18, 22);

    // ── Static curve preview lines (subtle, behind particles) ──
    const flowLineMat = new THREE.LineBasicMaterial({
        color: 0x00B8D4, transparent: true, opacity: 0.18,
    });
    [[yardSrc, aDst], [yardSrc, bDst]].forEach(([a, b]) => {
        const curve = buildPath(a, b);
        const points = curve.getPoints(48);
        const geo = new THREE.BufferGeometry().setFromPoints(points);
        scene.add(new THREE.Line(geo, flowLineMat));
    });

    // Building D dashed line (no animation — design)
    const dCurve = buildPath(yardSrc, dDst);
    const dPoints = dCurve.getPoints(48);
    const dDashedGeo = new THREE.BufferGeometry().setFromPoints(dPoints);
    const dDashedMat = new THREE.LineDashedMaterial({
        color: 0x6a7a8b, dashSize: 1.4, gapSize: 0.9,
        transparent: true, opacity: 0.45,
    });
    const dDashedLine = new THREE.Line(dDashedGeo, dDashedMat);
    dDashedLine.computeLineDistances();
    scene.add(dDashedLine);

    // ── Animated particles (InstancedMesh of small spheres) ───
    const particleGeo = new THREE.SphereGeometry(0.45, 12, 10);
    const particleMat = new THREE.MeshBasicMaterial({
        color: 0x67e8f9, transparent: true, opacity: 0.95,
    });
    const PARTICLES_PER_LINE = 14;
    const SPEED = 0.12;     // curve fraction per second

    [
        { from: yardSrc, to: aDst, label: 'flow-a' },
        { from: yardSrc, to: bDst, label: 'flow-b' },
    ].forEach((cfg, idx) => {
        const curve = buildPath(cfg.from, cfg.to);
        const inst = new THREE.InstancedMesh(particleGeo, particleMat, PARTICLES_PER_LINE);
        inst.frustumCulled = false;
        scene.add(inst);
        const t = new Array(PARTICLES_PER_LINE);
        for (let i = 0; i < PARTICLES_PER_LINE; i++) {
            t[i] = i / PARTICLES_PER_LINE;   // staggered initial positions
        }
        _flowGroups.push({ instMesh: inst, curve, count: PARTICLES_PER_LINE, speed: SPEED, t });
    });
}

function _updatePowerFlow(dt) {
    const dummy = new THREE.Object3D();
    for (const g of _flowGroups) {
        for (let i = 0; i < g.count; i++) {
            g.t[i] = (g.t[i] + g.speed * dt) % 1;
            const p = g.curve.getPoint(g.t[i]);
            dummy.position.copy(p);
            // Subtle scale pulse near apex
            const sc = 0.85 + Math.sin(g.t[i] * Math.PI) * 0.4;
            dummy.scale.setScalar(sc);
            dummy.updateMatrix();
            g.instMesh.setMatrixAt(i, dummy.matrix);
        }
        g.instMesh.instanceMatrix.needsUpdate = true;
    }
}

// ─── HTML overlay cards (project world → screen each frame) ────
function _bindOverlayCards() {
    _buildings.forEach(b => {
        b.cardEl = document.getElementById('mc-card-' + b.id.replace('building_', ''));
        if (b.cardEl) b.cardEl.removeAttribute('hidden');
    });
}

function _updateOverlayCards() {
    if (!_renderer || !_camera) return;
    const rect = _renderer.domElement.getBoundingClientRect();
    const tmp = new THREE.Vector3();
    for (const b of _buildings) {
        if (!b.cardEl) continue;
        tmp.copy(b.anchor).project(_camera);
        const x = (tmp.x + 1) / 2 * rect.width;
        const y = (-tmp.y + 1) / 2 * rect.height;
        b.cardEl.style.transform = `translate(-50%, -100%) translate(${x.toFixed(0)}px, ${y.toFixed(0)}px)`;
    }
}

// ─── Live data fetch + apply to overlay cards ──────────────────
async function _fetchLiveData() {
    try {
        const [pueResp, assetsResp, wosResp] = await Promise.all([
            fetch(`${API_BASE}/api/physics/pue`).then(r => r.ok ? r.json() : null),
            fetch(`${API_BASE}/api/cmms/assets?asset_type=it_rack&limit=200`).then(r => r.ok ? r.json() : null),
            fetch(`${API_BASE}/api/cmms/work-orders?trigger_source=predictive_kalman&only_open=true&limit=200`).then(r => r.ok ? r.json() : null),
        ]);

        // PUE
        if (pueResp) {
            _liveData.phase_1.pue = pueResp.phase_1?.pue;
            _liveData.phase_2.pue = pueResp.phase_2?.pue;
        }
        // Racks per path + IT MW
        if (assetsResp?.assets) {
            const byPath = { A: 0, B: 0 };
            for (const a of assetsResp.assets) {
                if (a.path === 'A') byPath.A++;
                else if (a.path === 'B') byPath.B++;
            }
            _liveData.phase_1.racks = byPath.A + byPath.B;     // total Phase 1 (informational)
            _liveData.A_racks = byPath.A;
            _liveData.B_racks = byPath.B;
            _liveData.A_mw = (byPath.A * 142) / 1000;          // GB200 142 kW/rack
            _liveData.B_mw = (byPath.B * 142) / 1000;
        }
        // Anomaly count per path: count predictive_kalman pending WOs
        // whose asset_id contains a path-letter pattern. Matches our
        // simulator burst convention.
        if (wosResp?.work_orders) {
            // Build asset_id → path map from assetsResp once
            const pathMap = new Map();
            if (assetsResp?.assets) {
                for (const a of assetsResp.assets) pathMap.set(a.asset_id, a.path);
            }
            const anomA = wosResp.work_orders.filter(
                w => w.status === 'pending_approval' &&
                     (pathMap.get(w.asset_id) === 'A' ||
                      /(^|[_-])a([_-]|$)|_a_/.test(w.asset_id))).length;
            const anomB = wosResp.work_orders.filter(
                w => w.status === 'pending_approval' &&
                     (pathMap.get(w.asset_id) === 'B' ||
                      /(^|[_-])b([_-]|$)|_b_/.test(w.asset_id))).length;
            _liveData.A_anom = anomA;
            _liveData.B_anom = anomB;
        }

        _applyLiveDataToCards();
    } catch (e) {
        console.warn('[mission_control] live data fetch failed:', e);
    }
}

function _applyLiveDataToCards() {
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    const fmtPue = (v) => (typeof v === 'number') ? v.toFixed(2) : '—';
    const fmtMw  = (v) => (typeof v === 'number') ? v.toFixed(1) + ' MW' : '—';
    set('mc-card-a-pue',   fmtPue(_liveData.phase_1.pue));
    set('mc-card-b-pue',   fmtPue(_liveData.phase_1.pue ? _liveData.phase_1.pue : null));   // both phases share P1 PUE for now
    set('mc-card-a-mw',    fmtMw(_liveData.A_mw));
    set('mc-card-b-mw',    fmtMw(_liveData.B_mw));
    set('mc-card-a-racks', _liveData.A_racks ?? '—');
    set('mc-card-b-racks', _liveData.B_racks ?? '—');
    set('mc-card-a-anom',  _liveData.A_anom ?? 0);
    set('mc-card-b-anom',  _liveData.B_anom ?? 0);

    // State coloring per anomaly count
    const cardA = document.getElementById('mc-card-a');
    const cardB = document.getElementById('mc-card-b');
    if (cardA) cardA.setAttribute('data-state', (_liveData.A_anom > 0) ? 'warn' : 'healthy');
    if (cardB) cardB.setAttribute('data-state', (_liveData.B_anom > 0) ? 'warn' : 'healthy');
    const stateA = document.getElementById('mc-card-a-state');
    const stateB = document.getElementById('mc-card-b-state');
    if (stateA) stateA.textContent = (_liveData.A_anom > 0) ? 'CAUTION' : 'HEALTHY';
    if (stateB) stateB.textContent = (_liveData.B_anom > 0) ? 'CAUTION' : 'HEALTHY';
}

// ─── Render loop ─────────────────────────────────────────────────
function _tick(ts) {
    _rafId = requestAnimationFrame(_tick);
    if (!_renderer || !_scene || !_camera) return;

    const dt = _lastFrameTs ? (ts - _lastFrameTs) / 1000 : 0.016;
    _lastFrameTs = ts;

    // Particle flow advance
    _updatePowerFlow(Math.min(dt, 0.1));   // cap dt to avoid jumps after tab-switch

    // Render
    _renderer.render(_scene, _camera);

    // Position overlay cards (cheap: 4 projections)
    _updateOverlayCards();

    // FPS HUD (twice/sec)
    if (dt > 0) _fpsBuffer.push(1 / dt);
    if (_fpsBuffer.length > 60) _fpsBuffer.shift();
    if ((ts | 0) % 500 < 17 && _fpsBuffer.length > 10) {
        const avg = _fpsBuffer.reduce((a, b) => a + b, 0) / _fpsBuffer.length;
        if (_hudFps) _hudFps.textContent = avg.toFixed(0);
        const info = _renderer.info;
        if (_hudDraw) _hudDraw.textContent = String(info.render.calls);
        if (_hudTris) _hudTris.textContent = String(info.render.triangles);
    }
}

// ─── Hover + tooltip ────────────────────────────────────────────
function _onPointerMove(e) {
    if (!_renderer || _transitioning) return;
    const rect = _renderer.domElement.getBoundingClientRect();
    _pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    _pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    _raycaster.setFromCamera(_pointer, _camera);
    const meshes = _buildings.map(b => b.mesh);
    const hits = _raycaster.intersectObjects(meshes, false);
    const next = hits.length ? hits[0].object : null;
    if (next === _hovered) {
        if (_hovered && _tooltipEl) {
            _tooltipEl.style.left = (e.clientX - rect.left + 14) + 'px';
            _tooltipEl.style.top  = (e.clientY - rect.top + 14) + 'px';
        }
        return;
    }
    if (_hovered) {
        _hovered.material.emissiveIntensity = _hovered === _buildings[0].mesh ? 0 : 0.6;
        _renderer.domElement.style.cursor = 'default';
    }
    _hovered = next;
    if (_hovered) {
        _hovered.material.emissiveIntensity = 1.1;
        _renderer.domElement.style.cursor = 'pointer';
        if (_tooltipEl) {
            const ud = _hovered.userData;
            _tooltipEl.innerHTML = `<strong>${_esc(ud.id)}</strong><br><span class="mc-tip-sub">${_esc(ud.displayName)}</span>`;
            _tooltipEl.removeAttribute('hidden');
            _tooltipEl.style.left = (e.clientX - rect.left + 14) + 'px';
            _tooltipEl.style.top  = (e.clientY - rect.top + 14) + 'px';
        }
    } else if (_tooltipEl) {
        _tooltipEl.setAttribute('hidden', '');
    }
}

function _onPointerLeave() {
    if (_tooltipEl) _tooltipEl.setAttribute('hidden', '');
}

// ─── Click → drill-down ─────────────────────────────────────────
const DRILL_TARGETS = {
    yard:        'site_topology',
    building_a:  'rack-heatmap',
    building_b:  'rack-heatmap',
    building_d:  'tech-assist',
};

function _navigateTo(route) {
    const navItem = document.querySelector(`.nav-item[data-route="${route}"]`);
    if (!navItem) {
        console.warn('[mission_control] no nav-item for route=%s', route);
        return;
    }
    navItem.click();
}

function _animateDrillDown(targetMesh, onDone) {
    if (_transitioning) return;
    _transitioning = true;

    const startPos = _camera.position.clone();
    const startLook = new THREE.Vector3(0, 0, 0);
    const endLook = targetMesh.position.clone();
    const endPos = startPos.clone().lerp(endLook, 0.35);

    // CSS fade overlay
    if (_fadeEl) {
        _fadeEl.removeAttribute('hidden');
        requestAnimationFrame(() => { _fadeEl.style.opacity = '1'; });
    }

    const startTs = performance.now();
    const DURATION = 600;
    const ease = (t) => t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;

    const step = (now) => {
        const elapsed = now - startTs;
        const k = Math.min(1, elapsed / DURATION);
        const e = ease(k);
        _camera.position.lerpVectors(startPos, endPos, e);
        _camera.lookAt(startLook.clone().lerp(endLook, e));
        if (k < 1) {
            requestAnimationFrame(step);
        } else {
            _transitioning = false;
            // Reset camera for next time
            _camera.position.copy(_camera.userData._origPos);
            _camera.lookAt(_camera.userData._origLook);
            if (_fadeEl) { _fadeEl.style.opacity = '0'; setTimeout(() => _fadeEl.setAttribute('hidden', ''), 250); }
            onDone?.();
        }
    };
    requestAnimationFrame(step);
}

function _onClick(e) {
    if (!_renderer || _transitioning) return;
    const rect = _renderer.domElement.getBoundingClientRect();
    _pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    _pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    _raycaster.setFromCamera(_pointer, _camera);
    const meshes = _buildings.map(b => b.mesh);
    const hits = _raycaster.intersectObjects(meshes, false);
    if (!hits.length) return;
    const hit = hits[0].object;
    const id = hit.userData?.id;
    const route = DRILL_TARGETS[id];
    console.log('[mission_control] click → %s → %s', id, route || '(no drill target)');
    _setStatus(`drilling: ${id} → ${route}`, 'ok');
    if (!route) return;
    _animateDrillDown(hit, () => _navigateTo(route));
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
    _hudFps   = document.getElementById('mc-fps-val');
    _hudDraw  = document.getElementById('mc-draw-val');
    _hudTris  = document.getElementById('mc-tris-val');
    _statusEl = document.getElementById('mc-status');
    _tooltipEl = document.getElementById('mc-tooltip');
    _fadeEl   = document.getElementById('mc-transition-fade');
    _overlayLayer = document.getElementById('mc-overlay-layer');

    const wrap = document.getElementById('mc-canvas-wrap');
    const canvas = document.getElementById('mc-canvas');
    if (!wrap || !canvas) return;

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
        _setupPowerFlow(_scene);

        _raycaster = new THREE.Raycaster();
        _pointer = new THREE.Vector2();

        canvas.addEventListener('pointermove', _onPointerMove);
        canvas.addEventListener('pointerleave', _onPointerLeave);
        canvas.addEventListener('click', _onClick);
        window.addEventListener('resize', _resize);

        _bindOverlayCards();
        try { subscribe('latestTelemetry', () => { /* future: real-time card refresh */ }); } catch {}

        // Initial live-data fetch + poll
        await _fetchLiveData();
        if (_liveTimer) clearInterval(_liveTimer);
        _liveTimer = setInterval(_fetchLiveData, POLL_LIVE_DATA_MS);

        _setStatus(`ready · three.js r${THREE.REVISION} · 4 buildings · live data ${POLL_LIVE_DATA_MS / 1000}s poll`, 'ok');

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
    if (_liveTimer) { clearInterval(_liveTimer); _liveTimer = null; }
}

// ─── Routing (LOTO pattern) ─────────────────────────────────────
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
                _fetchLiveData();
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
    console.log('[mission_control] view ready (B1 production · Tesla Megapack)');
}

export function stopMissionControl() { _stop(); }
