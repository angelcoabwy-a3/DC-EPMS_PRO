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
 *   - HUD MODE overlay panels (glassmorphism): 4 cards at a fixed,
 *     draggable, localStorage-persisted corner layout — replaces the
 *     old world→screen projection that collapsed them into an
 *     unreadable central stack. Live data from /api/physics/pue
 *     + /api/cmms/assets + /api/cmms/work-orders. SVG connector lines
 *     keep the panel↔building cognitive anchor. See _hud* functions.
 *   - Animated power flow: cyan particle InstancedMesh sliding
 *     along CatmullRomCurve3 from Yard → A and Yard → B
 *   - Raycaster click on a building → smooth 0.6 s zoom-and-fade
 *     transition → programmatic nav to the correct detail view
 *
 * Spike acceptance criteria from v0.10.3-b1-spike preserved:
 *   FPS HUD bottom-right + state.js subscribe + Raycaster pattern.
 * ════════════════════════════════════════════════════════════════ */

import * as THREE from '/assets/vendor/three.module.min.js';
import { subscribe, setState } from '../core/state.js';
import { registerRoute } from '../core/router.js';
import { escapeHTML } from '../core/sanitize.js';

const API_BASE = '';

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
let _hermesAlertHandler = null;   // T3.1: bound hermes:cmms-alert / :agent-consensus listener
let _transitioning = false;
let _transitionWatchdog = null;   // fail-safe timer for _transitioning (see _animateDrillDown)

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
    buildingD.userData = { id: 'building_d', displayName: 'Building D · 800 VDC unipolar TN-S · design Q2 2026', clickable: true };
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

// ─── HTML overlay cards — bind + un-hide ─────────────────────────
function _bindOverlayCards() {
    _buildings.forEach(b => {
        b.cardEl = document.getElementById('mc-card-' + b.id.replace('building_', ''));
        if (!b.cardEl) return;
        b.cardEl.removeAttribute('hidden');
        // T2.5 A11y-1 (WCAG 2.1.1) — keyboard-equivalent drill-down. The
        // raycaster click path in _onClick is mouse-only; the overlay
        // card (role="button" tabindex="0" in index.html) is the keyboard
        // route. Enter/Space mirrors _onClick's navigate-then-zoom order.
        if (!b.cardEl.dataset.a11yKeyBound) {
            b.cardEl.dataset.a11yKeyBound = '1';
            b.cardEl.addEventListener('keydown', (e) => {
                if (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar') return;
                e.preventDefault();
                const route = DRILL_TARGETS[b.id];
                if (!route) return;
                console.log('[mission_control] keyboard drill → %s → %s', b.id, route);
                _drillTo(b.id, route);
                if (b.mesh) _animateDrillDown(b.mesh);
            });
        }
    });
}

// ════════════════════════════════════════════════════════════════
//  B1 HUD MODE — fixed / draggable / persisted overlay panels
//
//  Replaces the original _updateOverlayCards() world→screen
//  projection, which collapsed the 4 cards into an unreadable
//  central stack whenever the render loop was unstable. HUD MODE:
//    - 4 panels at a deliberate corner layout on load (no overlap)
//    - independent drag-and-drop per panel (pointer capture)
//    - position persisted in localStorage, survives reload
//    - [Reset Panel Layout] ghost button restores default corners
//    - SVG connector line panel↔building (cognitive anchor)
//    - hover a 3D building → its panel blurs up + connector lights
//  Entirely decoupled from the (unstable) render loop: panels are
//  repositioned only on drag / resize / reset.
// ════════════════════════════════════════════════════════════════

const HUD_LS_KEY = 'mc_panel_layout_v1';
const HUD_MARGIN = 14;            // px gap from wrap edge
const HUD_BOTTOM_RESERVED = 72;   // px kept clear bottom-right (FPS HUD + reset btn)
const HUD_SVG_NS = 'http://www.w3.org/2000/svg';

let _hudCardW = 200;              // measured from a live card at setup
let _hudCardH = 138;              // measured from a live card at setup
let _panelLayout = null;          // { a|b|d|yard: {x,y} } px relative to wrap
let _hudDrag = null;              // active drag descriptor or null
let _connectorSvg = null;
let _connectorLines = {};         // buildingId → <line>
let _resetBtn = null;
let _buildingScreenPos = {};      // buildingId → {x,y} (static, fixed camera)

// card DOM-id suffix for a building id ('building_a'→'a', 'yard'→'yard')
function _hudCardKey(buildingId) { return buildingId.replace('building_', ''); }

// ─── Default corner layout (computed from live wrap size) ──────────
function _hudDefaultLayout(W, H) {
    const xL = HUD_MARGIN;
    const xR = Math.max(HUD_MARGIN, W - _hudCardW - HUD_MARGIN);
    const yT = HUD_MARGIN;
    const yB = Math.max(HUD_MARGIN, H - _hudCardH - HUD_MARGIN - HUD_BOTTOM_RESERVED);
    return {
        a:    { x: xL, y: yT },   // Building A — top-left
        b:    { x: xR, y: yT },   // Building B — top-right
        yard: { x: xL, y: yB },   // Yard       — bottom-left
        d:    { x: xR, y: yB },   // Building D — bottom-right
    };
}

// ─── Clamp a point so the card stays fully inside the wrap ─────────
function _hudClamp(p, W, H) {
    return {
        x: Math.min(Math.max(0, p.x), Math.max(0, W - _hudCardW)),
        y: Math.min(Math.max(0, p.y), Math.max(0, H - _hudCardH)),
    };
}

// ─── localStorage persistence ──────────────────────────────────────
function _hudLoadLayout() {
    try {
        const raw = localStorage.getItem(HUD_LS_KEY);
        if (!raw) return null;
        const obj = JSON.parse(raw);
        for (const k of ['a', 'b', 'd', 'yard']) {
            if (!obj || !obj[k] ||
                typeof obj[k].x !== 'number' || typeof obj[k].y !== 'number') {
                return null;   // missing/corrupt → fall back to defaults
            }
        }
        return obj;
    } catch (e) {
        console.warn('[mission_control] layout load failed, using defaults:', e);
        return null;
    }
}

function _hudSaveLayout() {
    try {
        localStorage.setItem(HUD_LS_KEY, JSON.stringify(_panelLayout));
    } catch (e) {
        console.warn('[mission_control] layout save failed (storage blocked/full):', e);
    }
}

// ─── Apply current layout to the DOM + redraw connectors ───────────
function _hudApplyLayout() {
    for (const b of _buildings) {
        if (!b.cardEl) continue;
        const pos = _panelLayout[_hudCardKey(b.id)];
        if (!pos) continue;
        b.cardEl.style.transform = 'none';   // kill any legacy projection transform
        b.cardEl.style.left = pos.x + 'px';
        b.cardEl.style.top  = pos.y + 'px';
    }
    _hudUpdateConnectors();
}

// ─── Drag and drop (pointer-capture based) ─────────────────────────
function _hudOnPointerDown(e, buildingId, cardEl) {
    if (e.button !== undefined && e.button !== 0) return;   // primary button only
    const wrap = document.getElementById('mc-canvas-wrap');
    if (!wrap || !_panelLayout) return;
    const wrapRect = wrap.getBoundingClientRect();
    const pos = _panelLayout[_hudCardKey(buildingId)] || { x: 0, y: 0 };
    _hudDrag = {
        id: buildingId,
        cardEl,
        grabDX: (e.clientX - wrapRect.left) - pos.x,
        grabDY: (e.clientY - wrapRect.top)  - pos.y,
    };
    cardEl.classList.add('is-dragging');
    try { cardEl.setPointerCapture(e.pointerId); } catch { /* capture unsupported */ }
    e.preventDefault();
}

function _hudOnPointerDrag(e) {
    if (!_hudDrag) return;
    const wrap = document.getElementById('mc-canvas-wrap');
    if (!wrap) return;
    const wrapRect = wrap.getBoundingClientRect();
    const clamped = _hudClamp({
        x: (e.clientX - wrapRect.left) - _hudDrag.grabDX,
        y: (e.clientY - wrapRect.top)  - _hudDrag.grabDY,
    }, wrapRect.width, wrapRect.height);
    _panelLayout[_hudCardKey(_hudDrag.id)] = clamped;
    _hudDrag.cardEl.style.left = clamped.x + 'px';
    _hudDrag.cardEl.style.top  = clamped.y + 'px';
    _hudUpdateConnectors();
}

function _hudOnPointerUp(e) {
    if (!_hudDrag) return;
    _hudDrag.cardEl.classList.remove('is-dragging');
    try { _hudDrag.cardEl.releasePointerCapture(e.pointerId); } catch { /* noop */ }
    _hudDrag = null;
    _hudSaveLayout();
}

// ─── SVG connector lines (panel centre ↔ building anchor) ──────────
function _hudBuildConnectorSvg(wrap) {
    let svg = document.getElementById('mc-connector-svg');
    if (!svg) {
        svg = document.createElementNS(HUD_SVG_NS, 'svg');
        svg.setAttribute('id', 'mc-connector-svg');
        svg.setAttribute('class', 'mc-connector-svg');
        const canvas = document.getElementById('mc-canvas');
        if (canvas) wrap.insertBefore(svg, canvas.nextSibling);
        else wrap.appendChild(svg);
    }
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    _connectorLines = {};
    for (const b of _buildings) {
        const line = document.createElementNS(HUD_SVG_NS, 'line');
        line.setAttribute('class', 'mc-connector-line');
        line.setAttribute('data-building', b.id);
        svg.appendChild(line);
        _connectorLines[b.id] = line;
    }
    _connectorSvg = svg;
}

// Project each building anchor → wrap-relative px. Recomputes the
// camera inverse explicitly so it does NOT depend on the render loop.
function _hudComputeBuildingScreenPositions() {
    if (!_camera || !_renderer) return;
    _camera.updateMatrixWorld(true);
    _camera.matrixWorldInverse.copy(_camera.matrixWorld).invert();
    const rect = _renderer.domElement.getBoundingClientRect();
    const v = new THREE.Vector3();
    _buildingScreenPos = {};
    for (const b of _buildings) {
        v.copy(b.anchor).project(_camera);
        _buildingScreenPos[b.id] = {
            x: (v.x + 1) / 2 * rect.width,
            y: (-v.y + 1) / 2 * rect.height,
        };
    }
}

function _hudUpdateConnectors() {
    if (!_connectorSvg) return;
    for (const b of _buildings) {
        const line = _connectorLines[b.id];
        const pos  = _panelLayout ? _panelLayout[_hudCardKey(b.id)] : null;
        const bs   = _buildingScreenPos[b.id];
        if (!line || !pos || !bs || !b.cardEl) continue;
        const px = pos.x + b.cardEl.offsetWidth / 2;
        const py = pos.y + b.cardEl.offsetHeight / 2;
        line.setAttribute('x1', px.toFixed(1));
        line.setAttribute('y1', py.toFixed(1));
        line.setAttribute('x2', bs.x.toFixed(1));
        line.setAttribute('y2', bs.y.toFixed(1));
    }
}

// ─── Reset-to-default-layout ghost button ──────────────────────────
function _hudBuildResetButton(wrap) {
    if (document.getElementById('mc-reset-layout-btn')) {
        _resetBtn = document.getElementById('mc-reset-layout-btn');
        return;
    }
    const btn = document.createElement('button');
    btn.id = 'mc-reset-layout-btn';
    btn.className = 'mc-reset-layout-btn';
    btn.type = 'button';
    btn.title = 'Reset the 4 panels to their default corner layout';
    btn.innerHTML =
        '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" ' +
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
        '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>' +
        '<path d="M3 3v5h5"/></svg><span>Reset Panel Layout</span>';
    btn.addEventListener('click', _hudResetLayout);
    wrap.appendChild(btn);
    _resetBtn = btn;
}

function _hudResetLayout() {
    const wrap = document.getElementById('mc-canvas-wrap');
    if (!wrap) return;
    const rect = wrap.getBoundingClientRect();
    _panelLayout = _hudDefaultLayout(rect.width, rect.height);
    try { localStorage.removeItem(HUD_LS_KEY); } catch { /* noop */ }
    _hudApplyLayout();
    _setStatus('panel layout reset to default corners', 'ok');
}

// ─── Hover-link: hovered 3D building → its panel + connector ───────
function _hudSetLinkedHover(buildingId) {
    for (const b of _buildings) {
        const on = (b.id === buildingId);
        if (b.cardEl) b.cardEl.classList.toggle('is-linked-hover', on);
        const line = _connectorLines[b.id];
        if (line) line.classList.toggle('is-active', on);
    }
}

// ─── HUD setup — called once from _boot after _bindOverlayCards ────
function _hudSetup() {
    const wrap = document.getElementById('mc-canvas-wrap');
    if (!wrap) return;
    const rect = wrap.getBoundingClientRect();

    // Measure a real card so corner math + connector centres are exact
    const sample = _buildings.find(b => b.cardEl);
    if (sample && sample.cardEl) {
        _hudCardW = sample.cardEl.offsetWidth  || _hudCardW;
        _hudCardH = sample.cardEl.offsetHeight || _hudCardH;
    }

    // Layout: persisted (clamped into current bounds) else defaults
    const saved = _hudLoadLayout();
    if (saved) {
        _panelLayout = {};
        for (const k of ['a', 'b', 'd', 'yard']) {
            _panelLayout[k] = _hudClamp(saved[k], rect.width, rect.height);
        }
    } else {
        _panelLayout = _hudDefaultLayout(rect.width, rect.height);
    }

    // Wire drag handlers on every card
    for (const b of _buildings) {
        if (!b.cardEl) continue;
        b.cardEl.classList.add('mc-hud-card');
        b.cardEl.addEventListener('pointerdown', (e) => _hudOnPointerDown(e, b.id, b.cardEl));
        b.cardEl.addEventListener('pointermove', _hudOnPointerDrag);
        b.cardEl.addEventListener('pointerup', _hudOnPointerUp);
        b.cardEl.addEventListener('pointercancel', _hudOnPointerUp);
    }

    _hudBuildConnectorSvg(wrap);
    _hudBuildResetButton(wrap);
    _hudComputeBuildingScreenPositions();
    _hudApplyLayout();
    console.log('[mission_control] HUD MODE ready — 4 panels, drag + persist + connectors');
}

// ─── HUD resize — re-clamp panels, recompute anchors, redraw ───────
function _hudOnResize() {
    const wrap = document.getElementById('mc-canvas-wrap');
    if (!wrap || !_panelLayout) return;
    const rect = wrap.getBoundingClientRect();
    for (const k of ['a', 'b', 'd', 'yard']) {
        if (_panelLayout[k]) {
            _panelLayout[k] = _hudClamp(_panelLayout[k], rect.width, rect.height);
        }
    }
    _hudComputeBuildingScreenPositions();
    _hudApplyLayout();
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

    // Overlay panels are HUD MODE — positioned on drag/resize/reset,
    // intentionally decoupled from this (possibly unstable) render loop.

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
    // No _transitioning gate — a cosmetic camera animation must never be
    // able to deadlock hover (drill-down deadlock fix, DC-EPMS-MC-001).
    if (!_renderer || !_camera || !_raycaster) return;
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
    // HUD MODE: light the linked panel + connector for the hovered building
    _hudSetLinkedHover(_hovered ? _hovered.userData?.id : null);
}

function _onPointerLeave() {
    if (_tooltipEl) _tooltipEl.setAttribute('hidden', '');
}

// ─── Click → drill-down ─────────────────────────────────────────
// Batch 6: building_d now drills into the Power SLD, where its
// Phase 2 800 VDC unipolar TN-S branch lives (was tech-assist).
const DRILL_TARGETS = {
    yard:        'site_topology',
    building_a:  'rack-heatmap',
    building_b:  'rack-heatmap',
    building_d:  'power',
};

const ROUTE_LABELS = {
    'site_topology': 'Site Topology',
    'rack-heatmap': 'Rack Heatmap',
    'power': 'Power & UPS SLD',
};

function _navigateTo(route) {
    const navItem = document.querySelector(`.nav-item[data-route="${route}"]`);
    if (!navItem) {
        console.warn('[mission_control] no nav-item for route=%s', route);
        return;
    }
    navItem.click();
}

// ─── Breadcrumb (Batch 6) ────────────────────────────────────────
// Drill-down trail that SURVIVES the navigation: it lives on
// document.body, not inside #view-mission-control. The first
// segment is a button back to Mission Control; any MANUAL nav-item
// click breaks the trail and dismisses it (wired in init via a
// delegated listener — note _drillTo shows the crumb AFTER its own
// _navigateTo click, so programmatic drills never self-dismiss).
function _hideBreadcrumb() {
    const el = document.getElementById('mc-breadcrumb');
    if (el) el.setAttribute('hidden', '');
}

function _showBreadcrumb(buildingId, route) {
    let el = document.getElementById('mc-breadcrumb');
    if (!el) {
        el = document.createElement('div');
        el.id = 'mc-breadcrumb';
        el.className = 'mc-breadcrumb';
        document.body.appendChild(el);
        el.addEventListener('click', (e) => {
            if (e.target.closest('[data-mc-home]')) {
                _hideBreadcrumb();
                _navigateTo('mission-control');
            }
        });
    }
    const b = _buildings.find((x) => x.id === buildingId);
    const building = escapeHTML((b && b.displayName) ? b.displayName.split('·')[0].trim() : buildingId);
    const target = escapeHTML(ROUTE_LABELS[route] || route);
    el.innerHTML =
        `<button type="button" class="mc-crumb mc-crumb-home" data-mc-home="1">🛰 Mission Control</button>`
        + `<span class="mc-crumb-sep">▸</span><span class="mc-crumb">${building}</span>`
        + `<span class="mc-crumb-sep">▸</span><span class="mc-crumb mc-crumb-here">${target}</span>`;
    el.removeAttribute('hidden');
}

// One drill path for mouse + keyboard: navigate, then leave the
// trail. Building D additionally pre-selects its MV Rectifier so the
// Power view opens with the Phase 2 spec sheet in the asset panel.
function _drillTo(buildingId, route) {
    if (!route) return;
    _setStatus(`drilling: ${buildingId} → ${route}`, 'ok');
    if (buildingId === 'building_d') setState('selectedAsset', 'mv_rect_d');
    _navigateTo(route);
    _showBreadcrumb(buildingId, route);
}

// Cosmetic camera zoom ONLY. Navigation is decoupled — it already fired
// synchronously in _onClick before this is ever called. A skipped or
// interrupted animation therefore costs nothing functional.
function _animateDrillDown(targetMesh) {
    // Reentrancy guard so two zooms do not fight. NOT a correctness gate.
    if (_transitioning || !_camera) return;
    _transitioning = true;

    const DURATION = 600;

    // Fail-safe watchdog: _transitioning must NEVER stay stuck true. Even
    // if the rAF chain is interrupted (view torn down, tab backgrounded),
    // this force-clears it so click + hover can never deadlock again
    // (drill-down deadlock fix, DC-EPMS-MC-001).
    clearTimeout(_transitionWatchdog);
    _transitionWatchdog = setTimeout(() => { _transitioning = false; }, DURATION + 400);

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
    const ease = (t) => t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;

    // Single exit path — clears the flag + watchdog, resets the camera.
    const _endTransition = () => {
        _transitioning = false;
        clearTimeout(_transitionWatchdog);
        if (_camera) {
            _camera.position.copy(_camera.userData._origPos);
            _camera.lookAt(_camera.userData._origLook);
        }
        if (_fadeEl) {
            _fadeEl.style.opacity = '0';
            setTimeout(() => _fadeEl.setAttribute('hidden', ''), 250);
        }
    };

    const step = (now) => {
        // Guard: the scene may have been torn down mid-animation.
        if (!_camera || !_renderer) { _endTransition(); return; }
        const elapsed = now - startTs;
        const k = Math.min(1, elapsed / DURATION);
        const e = ease(k);
        _camera.position.lerpVectors(startPos, endPos, e);
        _camera.lookAt(startLook.clone().lerp(endLook, e));
        if (k < 1) {
            requestAnimationFrame(step);
        } else {
            _endTransition();
        }
    };
    requestAnimationFrame(step);
}

function _onClick(e) {
    // No _transitioning gate — clicks must work even mid-animation
    // (drill-down deadlock fix, DC-EPMS-MC-001).
    if (!_renderer || !_camera || !_raycaster) return;
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
    if (!route) return;
    // Navigate FIRST — immediate, synchronous, unconditional. The drill-down
    // must succeed even if the zoom animation never runs or is interrupted.
    _drillTo(id, route);
    // Camera zoom is now pure fire-and-forget eye-candy, fully decoupled.
    _animateDrillDown(hit);
}

// ─── Resize ──────────────────────────────────────────────────────
function _resize() {
    if (!_renderer || !_camera) return;
    const wrap = document.getElementById('mc-canvas-wrap');
    if (!wrap) return;
    const w = wrap.clientWidth;
    const h = wrap.clientHeight || 540;
    // The view is hidden (display:none -> clientWidth 0). Resizing now
    // would build a degenerate OrthographicCamera (left===right) and
    // poison the HUD projection with NaN. Skip until the view is shown.
    if (w === 0) return;
    _renderer.setSize(w, h, false);
    const aspect = w / h;
    const viewSize = 95;
    _camera.left   = (-viewSize * aspect) / 2;
    _camera.right  = ( viewSize * aspect) / 2;
    _camera.top    =  viewSize / 2;
    _camera.bottom = -viewSize / 2;
    _camera.updateProjectionMatrix();
    _hudOnResize();   // B1 HUD MODE — re-clamp panels + redraw connectors
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
        _hudSetup();   // B1 HUD MODE — fixed/draggable panels + connectors
        try { subscribe('latestTelemetry', () => { /* future: real-time card refresh */ }); } catch {}

        // Initial live-data fetch, then event-driven from Hermes.
        await _fetchLiveData();

        // T3.1 cutover: no HTTP poll. The overlay cards / badges refresh
        // on the Hermes cmms_alerts + agent_consensus DOM events that
        // core/hermes_events.js dispatches — instant, zero interval.
        _hermesAlertHandler = () => { _fetchLiveData(); };
        document.addEventListener('hermes:cmms-alert', _hermesAlertHandler);
        document.addEventListener('hermes:agent-consensus', _hermesAlertHandler);

        _setStatus(`ready · three.js r${THREE.REVISION} · 4 buildings · live data via Hermes WS`, 'ok');

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
    if (_hermesAlertHandler) {
        document.removeEventListener('hermes:cmms-alert', _hermesAlertHandler);
        document.removeEventListener('hermes:agent-consensus', _hermesAlertHandler);
        _hermesAlertHandler = null;
    }
    // Fail-safe: never leave a transition flag stuck across a stop.
    clearTimeout(_transitionWatchdog);
    _transitioning = false;
}

// ─── Routing (LOTO pattern) ─────────────────────────────────────
function _wireRouting() {
    // T2.2: declarative registry (replaces the setTimeout(0) LOTO race).
    registerRoute('mission-control', {
        viewId: 'view-mission-control',
        activate: ({ firstActivation }) => {
            if (firstActivation) {
                _boot();
            } else {
                _resize();
                _fetchLiveData();
            }
        },
    });
}

export function initMissionControlView() {
    if (_initialized) return;
    if (!document.getElementById('view-mission-control')) {
        console.warn('[mission_control] view block not in DOM');
        return;
    }
    _wireRouting();
    // Batch 6: a MANUAL sidebar navigation breaks the drill-down trail
    // and dismisses the breadcrumb. _drillTo shows the crumb AFTER its
    // own programmatic nav-item click, so drills never self-dismiss.
    document.addEventListener('click', (e) => {
        if (e.target.closest('.nav-item')) _hideBreadcrumb();
    });
    _initialized = true;
    console.log('[mission_control] view ready (B1 production · Tesla Megapack)');
}

export function stopMissionControl() { _stop(); }

// ════════════════════════════════════════════════════════════════
//  Test-only surface — ROADMAP V11 T2.4.
//
//  Exposed for the Vitest harness only; production (main.js) imports
//  just initMissionControlView, so this is an unused export there —
//  prod-inert (a few bytes in the un-bundled build). injectScene is
//  dependency injection: a test stands up a fake scene WITHOUT the
//  real _boot()/WebGLRenderer. Keep this surface minimal + explicit.
// ════════════════════════════════════════════════════════════════
export const __mc_test__ = {
    // Drill-down state-machine handlers (post DC-EPMS-MC-001 fix)
    onClick:          _onClick,
    onPointerMove:    _onPointerMove,
    animateDrillDown: _animateDrillDown,
    navigateTo:       _navigateTo,
    drillTo:          _drillTo,
    showBreadcrumb:   _showBreadcrumb,
    hideBreadcrumb:   _hideBreadcrumb,
    stop:             _stop,
    DRILL_TARGETS,
    ROUTE_LABELS,

    // _transitioning flag — read / force
    getTransitioning: () => _transitioning,
    setTransitioning: (v) => { _transitioning = !!v; },

    // Dependency injection — fake scene, no _boot() required
    injectScene({ buildings, renderer, camera, raycaster, pointer, statusEl, fadeEl } = {}) {
        if (buildings !== undefined) _buildings = buildings;
        if (renderer  !== undefined) _renderer = renderer;
        if (camera    !== undefined) _camera = camera;
        if (raycaster !== undefined) _raycaster = raycaster;
        if (pointer   !== undefined) _pointer = pointer;
        if (statusEl  !== undefined) _statusEl = statusEl;
        if (fadeEl    !== undefined) _fadeEl = fadeEl;
    },

    // Restore module state between tests
    reset() {
        clearTimeout(_transitionWatchdog);
        _transitionWatchdog = null;
        _transitioning = false;
        _buildings = [];
        _renderer = null;
        _camera = null;
        _raycaster = null;
        _pointer = null;
        _hovered = null;
        _statusEl = null;
        _fadeEl = null;
    },
};
