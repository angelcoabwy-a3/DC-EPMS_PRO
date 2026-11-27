/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO -- frontend/assets/js/views/hall3d.js
 * 3D Hall track, lote 2 (ADR-021): Building D hall DH1 in WebGL.
 *
 * Draws the Building D design model (GET /api/design/building-d and
 * /racks): 250 racks (one cutaway, the rest instanced), 40 overhead
 * 800 VDC unipolar busways with animated flow and bloom, tap-offs,
 * DLC supply / return headers and drops, CDUs. Geometry comes from
 * core/hall3d_model.js (pure, unit-tested).
 *
 * Honest scope, printed on the view: DESIGN layout of a simulated
 * facility; rack internals, pipe sizes and tap-off boxes are
 * schematic; live telemetry binding is lote 3.
 *
 * Read-only (ADR-006). S-SEC-01: interpolated values escaped.
 * Performance: InstancedMesh for every repeated part, pixel ratio
 * capped at 1.5, bloom at half resolution, render loop stops while
 * the view is hidden.
 * ════════════════════════════════════════════════════════════════ */

import * as THREE from '/assets/vendor/three.module.min.js';
import { OrbitControls } from '/assets/vendor/three-addons/controls/OrbitControls.js';
import { EffectComposer } from '/assets/vendor/three-addons/postprocessing/EffectComposer.js';
import { RenderPass } from '/assets/vendor/three-addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from '/assets/vendor/three-addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from '/assets/vendor/three-addons/postprocessing/OutputPass.js';
import { RoomEnvironment } from '/assets/vendor/three-addons/environments/RoomEnvironment.js';
import { registerRoute } from '../core/router.js';
import { escapeHTML } from '../core/sanitize.js';
import { getState, subscribe } from '../core/state.js';
import {
    buildSceneSpec, chainEntry, COLOURS, DRAW,
    liveFromChannels, derivedLive, governQuality, qualitySettings,
    tourKeyframes, ease, callouts, laneLayout, ndcToStage,
    pathScenario, whatIfText, WHATIF_CYCLE,
} from '../core/hall3d_model.js';

const VIEW_ID = 'view-hall-3d';
const ROUTE_ID = 'hall-3d';
const DESIGN_URL = '/api/design/building-d';
const RACKS_URL = '/api/design/building-d/racks';
const MAX_PIXEL_RATIO = 1.5;
const TOUR_SECONDS = 14;
const BAND_COLOUR = { normal: 0x3ccf7a, 'off-nominal': 0xf2c037, under: 0xff4b3e, over: 0xff4b3e, unknown: 0x8a949e };

let _initialized = false;
let _ctx = null;          // { renderer, composer, scene, camera, controls, flows, raf, ... }

function $root() { return document.getElementById(VIEW_ID); }

function _num(v, digits = 0) {
    const n = Number(v);
    return Number.isFinite(n) ? n.toLocaleString('en-US', { maximumFractionDigits: digits }) : '-';
}

function _val(entry, key) {
    const x = entry?.[key];
    return x && typeof x === 'object' ? x.value : x;
}

/** Header + legend text, built from the design payload only. */
export function headerHtml(design) {
    const it = design?.basis?.it_kw?.value;
    const bw = chainEntry(design, 'row_busways');
    const feed = chainEntry(design, 'rack_feeds');
    const rect = chainEntry(design, 'mv_rectifiers');
    const spec = [
        `IT ${_num(Number(it) / 1000, 1)} MW (DESIGN)`,
        `${_num(bw?.total)} busways, ${_num(_val(bw, 'current'))} A of ${_num(_val(bw, 'rating'))} A`,
        `rack feed ${_num(_val(feed, 'current'))} A at ${_num(design?.dc?.nominal_v)} VDC`,
        `${_num(rect?.total)} MV rectifiers`,
    ].map((s) => `<span>${escapeHTML(s)}</span>`).join('');
    return `
        <div class="view-hdr">
            <h2>3D Hall, Building D <span class="h3d-tag">DESIGN</span></h2>
            <div class="view-sub">${escapeHTML(design?.site || '')} · hall ${escapeHTML(design?.hall || '')} ·
                ${escapeHTML(String(design?.dc?.nominal_v ?? ''))} VDC ${escapeHTML(design?.dc?.polarity || '')}
                ${escapeHTML(design?.dc?.earthing || '')} · 2N paths A and B</div>
        </div>
        <div class="h3d-spec">${spec}</div>`;
}

function _shell(root) {
    root.innerHTML = `
        <div class="h3d-head" data-h3d-head><div class="view-hdr"><h2>3D Hall, Building D</h2>
            <div class="view-sub">Loading the design model…</div></div></div>
        <div class="h3d-stage" data-h3d-stage>
            <canvas class="h3d-canvas" data-h3d-canvas role="img"
                aria-label="3D view of Building D hall DH1: racks, 800 VDC busways, cooling pipes"></canvas>
            <div class="h3d-hud" data-h3d-hud>
                <button type="button" class="h3d-btn" data-h3d-tour>TOUR</button>
                <button type="button" class="h3d-btn" data-h3d-callouts aria-pressed="true">CALLOUTS</button>
                <button type="button" class="h3d-btn" data-h3d-whatif title="Sandbox: trip one 2N path and see the other carry the hall. Nothing is sent to the plant.">WHAT-IF: 2N</button>
                <button type="button" class="h3d-btn" data-h3d-quality title="Rendering quality. Drops automatically below 30 fps; click to change by hand.">HIGH</button>
                <span data-h3d-fps>- fps</span>
            </div>
            <div class="h3d-whatif" data-h3d-whatif-banner role="status" hidden></div>
            <div class="h3d-live" data-h3d-live aria-live="polite"></div>
            <div class="h3d-rack" data-h3d-rack hidden></div>
            <div class="h3d-labels" data-h3d-labels></div>
            <div class="h3d-legend">
                <div><i style="background:#ff2bd6"></i>800 VDC busway, path A</div>
                <div><i style="background:#b04dff"></i>800 VDC busway, path B</div>
                <div><i style="background:#2f8cff"></i>DLC supply</div>
                <div><i style="background:#ff4b3e"></i>DLC return</div>
            </div>
            <div class="h3d-note" role="note">DESIGN layout of a simulated facility (ADR-021). Rack internals,
                tap-off boxes and pipe sizes are schematic. LIVE values come from the simulator, which still models the
                single-path Building D (DC-EPMS-076); per-rack load is MODEL. Click a rack for its data.</div>
        </div>`;
}

async function _getJson(url) {
    const r = await fetch(url, { credentials: 'same-origin' });
    if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
    return r.json();
}

// ── materials / textures ────────────────────────────────────────
function _flowTexture(hex) {
    const c = document.createElement('canvas');
    c.width = 256; c.height = 16;
    const g = c.getContext('2d');
    const col = `#${hex.toString(16).padStart(6, '0')}`;
    const grad = g.createLinearGradient(0, 0, 256, 0);
    grad.addColorStop(0.0, '#200018');
    grad.addColorStop(0.55, col);
    grad.addColorStop(0.62, '#ffffff');
    grad.addColorStop(0.7, col);
    grad.addColorStop(1.0, '#200018');
    g.fillStyle = grad;
    g.fillRect(0, 0, 256, 16);
    const t = new THREE.CanvasTexture(c);
    t.wrapS = THREE.RepeatWrapping;
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
}

function _instanced(geometry, material, items, place) {
    const mesh = new THREE.InstancedMesh(geometry, material, Math.max(1, items.length));
    const m = new THREE.Matrix4();
    const q = new THREE.Quaternion();
    const s = new THREE.Vector3(1, 1, 1);
    const p = new THREE.Vector3();
    items.forEach((it, i) => {
        place(it, p, q, s);
        m.compose(p, q, s);
        mesh.setMatrixAt(i, m);
    });
    mesh.count = items.length;
    mesh.instanceMatrix.needsUpdate = true;
    return mesh;
}

// ── scene parts ─────────────────────────────────────────────────
function _hallShell(scene, spec) {
    const [ex, ez] = spec.extent;
    const pad = 6;
    const floor = new THREE.Mesh(
        new THREE.PlaneGeometry(ex + 2 * pad + 6, ez + 2 * pad),
        new THREE.MeshStandardMaterial({ color: COLOURS.floor, roughness: 0.32, metalness: 0.0 }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.set(ex / 2 + 3, 0, ez / 2);
    scene.add(floor);
    const grid = new THREE.GridHelper(Math.max(ex, ez) + 2 * pad + 6, Math.round((Math.max(ex, ez) + 18) / 0.6), 0xb9bfc6, 0xc9ced4);
    grid.position.set(ex / 2 + 3, 0.002, ez / 2);
    grid.material.transparent = true;
    grid.material.opacity = 0.35;
    scene.add(grid);
    // Room as one back-faced box: from any orbit position the walls
    // nearest the camera are culled and never hide the hall.
    const room = new THREE.Mesh(
        new THREE.BoxGeometry(ex + 2 * pad + 6, 6, ez + 2 * pad),
        new THREE.MeshStandardMaterial({ color: 0xeef0f2, roughness: 0.9, side: THREE.BackSide }),
    );
    room.position.set(ex / 2 + 3, 3 - 0.01, ez / 2);
    scene.add(room);
}

function _racks(scene, spec) {
    const body = new THREE.MeshStandardMaterial({ color: COLOURS.rack, roughness: 0.5, metalness: 0.25 });
    const door = new THREE.MeshStandardMaterial({ color: 0x14171b, roughness: 0.7, metalness: 0.2 });
    const led = new THREE.MeshStandardMaterial({ color: 0x9aa4ae, emissive: 0x6f7a86, emissiveIntensity: 0.6 });
    const list = spec.instanced;
    if (!list.length) return;
    const [w, h, d] = list[0].size;
    const bodyMesh = _instanced(new THREE.BoxGeometry(w * 0.98, h, d * 0.98), body, list,
        (r, p) => p.set(...r.center));
    bodyMesh.userData.rackIds = list.map((r) => r.id);
    scene.add(bodyMesh);
    // front door panel (cold-aisle side) and a status strip
    scene.add(_instanced(new THREE.BoxGeometry(w * 0.9, h * 0.94, 0.02), door, list,
        (r, p) => p.set(r.center[0], r.center[1], r.center[2] - d / 2 - 0.006)));
    scene.add(_instanced(new THREE.BoxGeometry(w * 0.6, 0.02, 0.01), led, list,
        (r, p) => p.set(r.center[0], h * 0.92, r.center[2] - d / 2 - 0.02)));
    return { bodyMesh, led };
}

function _cutawayRack(scene, spec) {
    const r = spec.racks.find((x) => x.id === spec.detail);
    if (!r) return;
    const [w, h, d] = r.size;
    const g = new THREE.Group();
    g.position.set(r.center[0] - w / 2, 0, r.center[2] - d / 2);
    const steel = new THREE.MeshStandardMaterial({ color: 0x24292f, roughness: 0.4, metalness: 0.7 });
    const post = new THREE.BoxGeometry(0.04, h, 0.04);
    for (const [x, z] of [[0.02, 0.02], [w - 0.02, 0.02], [0.02, d - 0.02], [w - 0.02, d - 0.02]]) {
        const m = new THREE.Mesh(post, steel); m.position.set(x, h / 2, z); g.add(m);
    }
    const cap = new THREE.Mesh(new THREE.BoxGeometry(w, 0.04, d), steel);
    cap.position.set(w / 2, h - 0.02, d / 2); g.add(cap);
    const base = cap.clone(); base.position.y = 0.02; g.add(base);
    const back = new THREE.Mesh(new THREE.BoxGeometry(0.02, h, d), steel);   // far side panel only
    back.position.set(w - 0.01, h / 2, d / 2); g.add(back);
    // trays (SCHEMATIC count)
    const pcb = new THREE.MeshStandardMaterial({ color: 0x1f4d34, roughness: 0.55, metalness: 0.2 });
    const plate = new THREE.MeshStandardMaterial({ color: 0xb8c0c8, roughness: 0.25, metalness: 0.9 });
    const usable = h - 0.3;
    const pitch = usable / DRAW.trays;
    for (let i = 0; i < DRAW.trays; i += 1) {
        const y = 0.15 + pitch * (i + 0.5);
        const t = new THREE.Mesh(new THREE.BoxGeometry(w - 0.1, pitch * 0.55, d * 0.78), pcb);
        t.position.set(w / 2, y, d * 0.42); g.add(t);
        const cp = new THREE.Mesh(new THREE.BoxGeometry((w - 0.1) * 0.7, pitch * 0.18, d * 0.42), plate);
        cp.position.set(w / 2, y + pitch * 0.34, d * 0.36); g.add(cp);
    }
    // rear DC busbar (copper) and DLC manifolds
    const copper = new THREE.MeshStandardMaterial({ color: 0xc8743a, roughness: 0.28, metalness: 1.0 });
    const bar = new THREE.Mesh(new THREE.BoxGeometry(0.12, usable, 0.02), copper);
    bar.position.set(w / 2, h / 2, d - 0.06); g.add(bar);
    const sup = new THREE.MeshStandardMaterial({ color: COLOURS.supply, roughness: 0.3, metalness: 0.5 });
    const ret = new THREE.MeshStandardMaterial({ color: COLOURS.return, roughness: 0.3, metalness: 0.5 });
    const man = new THREE.CylinderGeometry(0.025, 0.025, usable, 16);
    const ms = new THREE.Mesh(man, sup); ms.position.set(0.1, h / 2, d - 0.08); g.add(ms);
    const mr = new THREE.Mesh(man, ret); mr.position.set(w - 0.1, h / 2, d - 0.08); g.add(mr);
    const hose = new THREE.CylinderGeometry(0.008, 0.008, d * 0.16, 8);
    hose.rotateX(Math.PI / 2);
    for (let i = 0; i < DRAW.trays; i += 1) {
        const y = 0.15 + pitch * (i + 0.5);
        const a = new THREE.Mesh(hose, sup); a.position.set(0.1, y, d * 0.84); g.add(a);
        const b = new THREE.Mesh(hose, ret); b.position.set(w - 0.1, y, d * 0.84); g.add(b);
    }
    g.userData.rackId = r.id;
    scene.add(g);
    return g;
}

function _busways(scene, spec) {
    const flows = [];
    const [bw, bh] = DRAW.buswaySection;
    const housing = new THREE.MeshStandardMaterial({ color: 0x3a3f46, roughness: 0.5, metalness: 0.6 });
    for (const b of spec.busways) {
        const tex = _flowTexture(COLOURS.busway[b.path]);
        tex.repeat.set(Math.max(1, b.length / 1.8), 1);
        const core = new THREE.MeshStandardMaterial({
            color: 0x1a0016, emissive: COLOURS.busway[b.path], emissiveMap: tex,
            emissiveIntensity: 4.0, roughness: 0.35, metalness: 0.3,
        });
        const m = new THREE.Mesh(new THREE.BoxGeometry(b.length, bh * 0.55, bw * 0.6), core);
        m.position.set(...b.center);
        scene.add(m);
        const hs = new THREE.Mesh(new THREE.BoxGeometry(b.length, bh * 0.25, bw), housing);
        hs.position.set(b.center[0], b.y + bh * 0.42, b.z);
        scene.add(hs);
        flows.push({ tex, sign: b.flowSign, path: b.path, mat: core });
    }
    // tap-offs and drops
    const tapMat = new THREE.MeshStandardMaterial({ color: 0x5b626b, roughness: 0.5, metalness: 0.6 });
    scene.add(_instanced(new THREE.BoxGeometry(...DRAW.tapOff), tapMat, spec.tapOffs,
        (t, p) => p.set(...t.box)));
    const dropMat = new THREE.MeshStandardMaterial({ color: 0x2a2a2a, emissive: 0x7a1468, emissiveIntensity: 0.8 });
    const unit = new THREE.CylinderGeometry(0.015, 0.015, 1, 8);
    scene.add(_instanced(unit, dropMat, spec.tapOffs, (t, p, q, s) => {
        const len = Math.max(0.01, t.drop.y1 - t.drop.y0);
        p.set(t.drop.x, (t.drop.y0 + t.drop.y1) / 2, t.drop.z);
        s.set(1, len, 1);
    }));
    return flows;
}

function _pipes(scene, spec) {
    const mats = {
        supply: new THREE.MeshStandardMaterial({ color: COLOURS.supply, roughness: 0.25, metalness: 0.55, emissive: COLOURS.supply, emissiveIntensity: 0.12 }),
        return: new THREE.MeshStandardMaterial({ color: COLOURS.return, roughness: 0.25, metalness: 0.55, emissive: COLOURS.return, emissiveIntensity: 0.12 }),
    };
    for (const p of spec.pipes) {
        const len = p.x1 - p.x0;
        const geo = new THREE.CylinderGeometry(DRAW.pipeRadius, DRAW.pipeRadius, len, 20);
        geo.rotateZ(Math.PI / 2);
        const m = new THREE.Mesh(geo, mats[p.kind]);
        m.position.set((p.x0 + p.x1) / 2, p.y, p.z + (p.kind === 'supply' ? -0.18 : 0.18));
        scene.add(m);
    }
    // per-rack drops from the headers to the rack top
    const h = spec.racks[0]?.size[1] ?? 2.3;
    const unit = new THREE.CylinderGeometry(0.02, 0.02, 1, 8);
    for (const kind of ['supply', 'return']) {
        const y1 = kind === 'supply' ? DRAW.pipeSupplyY : DRAW.pipeReturnY;
        scene.add(_instanced(unit, mats[kind], spec.racks, (r, p, q, s) => {
            p.set(r.center[0] + (kind === 'supply' ? -0.15 : 0.15), (h + y1) / 2, r.center[2] + (kind === 'supply' ? -0.18 : 0.18));
            s.set(1, Math.max(0.01, y1 - h), 1);
        }));
    }
}

function _cdus(scene, spec) {
    const mat = new THREE.MeshStandardMaterial({ color: 0xc9cdd2, roughness: 0.45, metalness: 0.35 });
    scene.add(_instanced(new THREE.BoxGeometry(...DRAW.cduSize), mat, spec.cdus, (c, p) => p.set(...c.center)));
}

// ── renderer / loop ─────────────────────────────────────────────
function _build(root, spec, design) {
    const canvas = root.querySelector('[data-h3d-canvas]');
    const stage = root.querySelector('[data-h3d-stage]');
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 0.85;
    renderer.outputColorSpace = THREE.SRGBColorSpace;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xe9ecef);
    const pmrem = new THREE.PMREMGenerator(renderer);
    scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    scene.environmentIntensity = 0.45;
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8a9097, 0.35));
    const sun = new THREE.DirectionalLight(0xffffff, 0.8);
    sun.position.set(-10, 20, -8);
    scene.add(sun);

    _hallShell(scene, spec);
    const rackParts = _racks(scene, spec);
    const cutaway = _cutawayRack(scene, spec);
    const flows = _busways(scene, spec);
    _pipes(scene, spec);
    _cdus(scene, spec);

    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 400);
    const detail = spec.racks.find((x) => x.id === spec.detail);
    // Portrait screens see less sideways: start further back and higher.
    const portrait = stage.clientWidth < stage.clientHeight;
    const home = tourKeyframes(spec).at(-1);
    if (portrait) camera.position.set(-4.8, 3.6, -8.0);
    else camera.position.set(...home.pos);
    const controls = new OrbitControls(camera, canvas);
    controls.enableDamping = true;
    controls.maxPolarAngle = Math.PI * 0.49;
    controls.minDistance = 1.5;
    controls.maxDistance = 90;
    controls.target.set(...home.target);

    const composer = new EffectComposer(renderer);
    composer.addPass(new RenderPass(scene, camera));
    const bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.7, 0.35, 1.6);
    composer.addPass(bloom);
    composer.addPass(new OutputPass());

    // Callout labels (DOM) + leader lines (SVG) over the canvas.
    const labelHost = root.querySelector('[data-h3d-labels]');

    const ctx = { renderer, composer, bloom, scene, camera, controls, flows, raf: 0, stage, spec, design,
        labelHost, calloutItems: [], showCallouts: stage.clientWidth >= 900,
        rackParts, cutaway, selected: null, live: null, derived: null,
        quality: { level: 2, low: 0, manual: false }, tour: null, tripped: null,
        frames: 0, fpsT: performance.now(), last: performance.now(),
        fpsEl: root.querySelector('[data-h3d-fps]'), root };
    _buildCallouts(ctx);
    _setCallouts(ctx, ctx.showCallouts);

    const resize = () => {
        const w = Math.max(1, stage.clientWidth);
        const h = Math.max(1, stage.clientHeight);
        renderer.setSize(w, h, false);
        composer.setSize(w, h);
        bloom.resolution.set(Math.round(w / 2), Math.round(h / 2));
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
    };
    ctx.resize = resize;
    if (typeof ResizeObserver !== 'undefined') new ResizeObserver(resize).observe(stage);
    resize();
    _wireInput(ctx);
    return ctx;
}

// ── callouts with leader lines ──────────────────────────────────
function _calloutHtml(c) {
    return `<div class="h3d-co-title">${escapeHTML(c.title)}</div>`
        + c.lines.map((l) => `<div class="h3d-co-line">${escapeHTML(l)}</div>`).join('');
}

function _buildCallouts(ctx) {
    const host = ctx.labelHost;
    host.innerHTML = '<svg class="h3d-leaders" data-h3d-leaders aria-hidden="true"></svg>';
    const svg = host.querySelector('[data-h3d-leaders]');
    for (const c of callouts(ctx.spec, ctx.design, _liveForText(ctx))) {
        const el = document.createElement('div');
        el.className = `h3d-callout h3d-co-${c.id}`;
        el.innerHTML = _calloutHtml(c);
        host.appendChild(el);
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
        line.setAttribute('class', `h3d-leader h3d-leader-${c.id}`);
        const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        dot.setAttribute('r', '4');
        dot.setAttribute('class', `h3d-leader-dot h3d-leader-${c.id}`);
        svg.append(line, dot);
        ctx.calloutItems.push({ id: c.id, el, line, dot, anchor: new THREE.Vector3(...c.anchor) });
    }
}

function _layoutCallouts(ctx) {
    const w = ctx.stage.clientWidth;
    const h = ctx.stage.clientHeight;
    const tops = laneLayout(ctx.calloutItems.map((it) => it.el.offsetHeight || 60), h);
    const v = new THREE.Vector3();
    ctx.calloutItems.forEach((it, i) => {
        it.el.style.top = `${tops[i]}px`;
        const p = ndcToStage(v.copy(it.anchor).project(ctx.camera), w, h);
        if (!p) {
            it.line.setAttribute('points', '');
            it.dot.setAttribute('visibility', 'hidden');
            return;
        }
        const x0 = 12 + it.el.offsetWidth;
        const y0 = tops[i] + (it.el.offsetHeight || 60) / 2;
        const elbow = Math.min(p[0], x0 + 24);
        it.line.setAttribute('points', `${x0},${y0} ${elbow},${y0} ${p[0]},${p[1]}`);
        it.dot.setAttribute('cx', String(p[0]));
        it.dot.setAttribute('cy', String(p[1]));
        it.dot.setAttribute('visibility', 'visible');
    });
}

function _liveForText(ctx) {
    const live = ctx.live || {};
    return {
        ...live, rackKw: ctx.derived?.rackKw ?? null, rackA: ctx.derived?.rackA ?? null,
        whatIf: ctx.tripped ? pathScenario(ctx.design, ctx.derived, ctx.tripped) : null,
    };
}

function _refreshCallouts(ctx) {
    for (const c of callouts(ctx.spec, ctx.design, _liveForText(ctx))) {
        const it = ctx.calloutItems.find((x) => x.id === c.id);
        if (it) it.el.innerHTML = _calloutHtml(c);
    }
}

function _setCallouts(ctx, on) {
    ctx.showCallouts = on;
    ctx.root.querySelector('[data-h3d-labels]').hidden = !on;
    ctx.root.querySelector('[data-h3d-callouts]')?.setAttribute('aria-pressed', String(on));
}

// ── live data (simulator channels) ──────────────────────────────
function _fmt(v, d = 0) {
    if (!Number.isFinite(v)) return '-';
    const r = Number(v.toFixed(d));
    return (Object.is(r, -0) ? 0 : r).toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d });
}

export function livePanelHtml(live, derived) {
    if (!live?.any) {
        return '<div class="h3d-live-h">LIVE (simulator)</div><div class="h3d-live-r">No Building D channels yet.</div>';
    }
    const rows = [
        ['800 VDC bus', `${_fmt(live.busV, 1)} V`, derived?.band || 'unknown'],
        ['Rectifier load', `${_fmt(live.rectMw, 1)} MW`, ''],
        ['Rectifier efficiency', `${_fmt((live.rectEff ?? NaN) * 100, 1)} %`, ''],
        ['SSCB junction', `${_fmt(live.sscbC, 1)} C`, ''],
        ['BESS SOC', `${_fmt(live.bessSoc, 1)} %`, ''],
        ['BESS current', `${_fmt(live.bessA, 0)} A`, ''],
        ['Per rack (MODEL)', `${_fmt(derived?.rackKw, 0)} kW · ${_fmt(derived?.rackA, 0)} A`, ''],
    ];
    return '<div class="h3d-live-h">LIVE (simulator)</div>' + rows.map(([k, v, band]) =>
        `<div class="h3d-live-r"><span>${escapeHTML(k)}</span><b${band ? ` data-band="${escapeHTML(band)}"` : ''}>${escapeHTML(v)}</b></div>`).join('');
}

function _onChannels(channels) {
    const ctx = _ctx;
    if (!ctx) return;
    ctx.live = liveFromChannels(channels);
    ctx.derived = derivedLive(ctx.live, ctx.design);
    const panel = ctx.root.querySelector('[data-h3d-live]');
    if (panel) panel.innerHTML = livePanelHtml(ctx.live, ctx.derived);
    const led = ctx.rackParts?.led;
    if (led) {
        const c = BAND_COLOUR[ctx.derived.band] ?? BAND_COLOUR.unknown;
        led.color.setHex(c);
        led.emissive.setHex(c);
    }
    if (ctx.showCallouts) _refreshCallouts(ctx);
    if (ctx.tripped) _refreshWhatIf(ctx);
    if (ctx.selected) _renderRackPanel(ctx, ctx.selected.data);
}

// ── rack selection ──────────────────────────────────────────────
function _renderRackPanel(ctx, r) {
    const el = ctx.root.querySelector('[data-h3d-rack]');
    if (!el || !r) return;
    const v = (x) => (x && typeof x === 'object' ? `${_fmt(Number(x.value), 1)} ${x.unit} (${x.tag})` : '-');
    const feeds = (r.feeds || []).map((f) =>
        `<div class="h3d-live-r"><span>Feed ${escapeHTML(String(f.path).toUpperCase())} · ${escapeHTML(f.busway)} · ${escapeHTML(f.section)}</span><b>${escapeHTML(v(f.current_full))}</b></div>`).join('');
    const d = ctx.derived;
    el.innerHTML = `
        <div class="h3d-rack-h"><span>${escapeHTML(r.id)}</span>
            <button type="button" class="h3d-btn" data-h3d-rack-close aria-label="Close rack panel">CLOSE</button></div>
        <div class="h3d-live-r"><span>Model</span><b>${escapeHTML(r.model || '')}</b></div>
        <div class="h3d-live-r"><span>Power</span><b>${escapeHTML(v(r.power_kw))}</b></div>
        ${feeds}
        <div class="h3d-live-r"><span>DLC flow</span><b>${escapeHTML(v(r.cooling?.flow))}</b></div>
        <div class="h3d-live-r"><span>Supply / return max</span><b>${escapeHTML(`${_fmt(r.cooling?.supply?.value)} / ${_fmt(r.cooling?.return_max?.value)} C (DESIGN)`)}</b></div>
        <div class="h3d-live-r"><span>Now (MODEL from LIVE)</span><b>${escapeHTML(d?.rackKw != null ? `${_fmt(d.rackKw, 0)} kW · ${_fmt(d.rackA, 0)} A` : 'no live data')}</b></div>
        <div class="h3d-rack-note">${escapeHTML(r.devices?.not_modelled || '')}</div>`;
    el.hidden = false;
}

async function _select(ctx, rackId) {
    const box = ctx.spec.racks.find((x) => x.id === rackId);
    if (!box) return;
    if (!ctx.highlight) {
        ctx.highlight = new THREE.LineSegments(
            new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1)),
            new THREE.LineBasicMaterial({ color: 0x35e0ff }),
        );
        ctx.scene.add(ctx.highlight);
    }
    ctx.highlight.scale.set(box.size[0] + 0.04, box.size[1] + 0.04, box.size[2] + 0.04);
    ctx.highlight.position.set(...box.center);
    ctx.highlight.visible = true;
    try {
        const data = await _getJson(`${RACKS_URL}/${encodeURIComponent(rackId)}`);
        ctx.selected = { id: rackId, data };
        _renderRackPanel(ctx, data);
    } catch (e) {
        const el = ctx.root.querySelector('[data-h3d-rack]');
        el.innerHTML = `<div class="h3d-error" role="alert">${escapeHTML(e.message)}</div>`;
        el.hidden = false;
    }
}

function _pick(ctx, ev) {
    const rect = ctx.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((ev.clientX - rect.left) / rect.width) * 2 - 1, -((ev.clientY - rect.top) / rect.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(ndc, ctx.camera);
    const targets = [ctx.rackParts?.bodyMesh, ctx.cutaway].filter(Boolean);
    const hit = ray.intersectObjects(targets, true)[0];
    if (!hit) return null;
    if (hit.object.isInstancedMesh && hit.instanceId != null) return hit.object.userData.rackIds?.[hit.instanceId] ?? null;
    let o = hit.object;
    while (o && !o.userData.rackId) o = o.parent;
    return o?.userData.rackId ?? null;
}

// ── input, tour, quality ────────────────────────────────────────
function _wireInput(ctx) {
    const canvas = ctx.renderer.domElement;
    let down = null;
    canvas.addEventListener('pointerdown', (e) => { down = [e.clientX, e.clientY]; ctx.tour = null; });
    canvas.addEventListener('pointerup', (e) => {
        if (!down) return;
        const moved = Math.hypot(e.clientX - down[0], e.clientY - down[1]);
        down = null;
        if (moved > 5) return;                 // a drag orbits, it does not select
        const id = _pick(ctx, e);
        if (id) _select(ctx, id);
    });
    ctx.root.addEventListener('click', (e) => {
        if (e.target.closest('[data-h3d-rack-close]')) {
            ctx.root.querySelector('[data-h3d-rack]').hidden = true;
            ctx.selected = null;
            if (ctx.highlight) ctx.highlight.visible = false;
        } else if (e.target.closest('[data-h3d-tour]')) {
            _startTour(ctx);
        } else if (e.target.closest('[data-h3d-whatif]')) {
            const i = WHATIF_CYCLE.indexOf(ctx.tripped);
            _setTripped(ctx, WHATIF_CYCLE[(i + 1) % WHATIF_CYCLE.length]);
        } else if (e.target.closest('[data-h3d-callouts]')) {
            _setCallouts(ctx, !ctx.showCallouts);
        } else if (e.target.closest('[data-h3d-quality]')) {
            const next = (ctx.quality.level + 2) % 3;     // HIGH -> LOW -> MEDIUM -> HIGH
            _applyQuality(ctx, { level: next, low: 0, manual: true });
        }
    });
}

function _setTripped(ctx, path) {
    ctx.tripped = path;
    for (const f of ctx.flows) {
        const dead = path && f.path === path;
        f.mat.emissiveIntensity = dead ? 0 : (path ? 5.0 : 4.0);
        f.mat.color.setHex(dead ? 0x3a3f46 : 0x1a0016);
    }
    const btn = ctx.root.querySelector('[data-h3d-whatif]');
    if (btn) btn.textContent = path ? `WHAT-IF: TRIP ${path.toUpperCase()}` : 'WHAT-IF: 2N';
    _refreshWhatIf(ctx);
    if (ctx.showCallouts) _refreshCallouts(ctx);
}

function _refreshWhatIf(ctx) {
    const el = ctx.root.querySelector('[data-h3d-whatif-banner]');
    if (!el) return;
    const sc = pathScenario(ctx.design, ctx.derived, ctx.tripped);
    el.textContent = whatIfText(sc);
    el.hidden = !ctx.tripped;
    el.dataset.ok = String(sc.ok);
}

function _applyQuality(ctx, q) {
    ctx.quality = q;
    const set = qualitySettings(q.level);
    ctx.bloom.enabled = set.bloom;
    ctx.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, set.pixelRatio));
    ctx.resize();
    const b = ctx.root.querySelector('[data-h3d-quality]');
    if (b) b.textContent = set.label + (q.manual ? '' : ' (auto)');
}

function _startTour(ctx) {
    const reduce = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
    const keys = tourKeyframes(ctx.spec);
    if (ctx.stage.clientWidth < ctx.stage.clientHeight) {
        // portrait: end further back so the row fits the narrow frame
        keys[keys.length - 1] = { pos: [-4.8, 3.6, -8.0], target: keys[keys.length - 1].target };
    }
    if (reduce) {
        const last = keys[keys.length - 1];
        ctx.camera.position.set(...last.pos);
        ctx.controls.target.set(...last.target);
        return;
    }
    ctx.tour = {
        t0: performance.now(),
        pos: new THREE.CatmullRomCurve3(keys.map((k) => new THREE.Vector3(...k.pos))),
        tgt: new THREE.CatmullRomCurve3(keys.map((k) => new THREE.Vector3(...k.target))),
    };
}

function _frame(now) {
    const ctx = _ctx;
    if (!ctx) return;
    if ($root()?.hidden) { ctx.raf = 0; return; }
    const dt = Math.min(0.1, (now - ctx.last) / 1000);
    ctx.last = now;
    const scale = ctx.derived?.flowScale ?? 1;
    for (const f of ctx.flows) {
        const share = ctx.tripped ? (f.path === ctx.tripped ? 0 : 2) : 1;
        f.tex.offset.x -= f.sign * dt * 0.6 * scale * share;
    }
    if (ctx.tour) {
        const t = ease((now - ctx.tour.t0) / (TOUR_SECONDS * 1000));
        ctx.camera.position.copy(ctx.tour.pos.getPoint(t));
        ctx.controls.target.copy(ctx.tour.tgt.getPoint(t));
        if (t >= 1) ctx.tour = null;
    }
    ctx.controls.update();
    ctx.composer.render();
    if (ctx.showCallouts) _layoutCallouts(ctx);
    ctx.frames += 1;
    if (now - ctx.fpsT >= 1000) {
        const fps = (ctx.frames * 1000) / (now - ctx.fpsT);
        if (ctx.fpsEl) ctx.fpsEl.textContent = `${fps.toFixed(0)} fps`;
        const q = governQuality(ctx.quality, fps);
        if (q.level !== ctx.quality.level) _applyQuality(ctx, q);
        else ctx.quality = q;
        ctx.frames = 0; ctx.fpsT = now;
    }
    ctx.raf = requestAnimationFrame(_frame);
}

function _start() {
    if (_ctx && !_ctx.raf) {
        _ctx.last = performance.now();
        _ctx.fpsT = _ctx.last;
        _ctx.frames = 0;
        _ctx.raf = requestAnimationFrame(_frame);
    }
}

async function _boot() {
    const root = $root();
    if (!root) return;
    _shell(root);
    let design;
    let racks;
    try {
        [design, racks] = await Promise.all([_getJson(DESIGN_URL), _getJson(RACKS_URL)]);
    } catch (e) {
        root.querySelector('[data-h3d-head]').innerHTML =
            `<div class="h3d-error" role="alert">Could not load the design model: ${escapeHTML(e.message)}</div>`;
        return;
    }
    root.querySelector('[data-h3d-head]').innerHTML = headerHtml(design);
    const spec = buildSceneSpec(design, racks.racks);
    try {
        _ctx = _build(root, spec, design);
        _onChannels(getState('channels'));
        _startTour(_ctx);
    } catch (e) {
        root.querySelector('[data-h3d-stage]').insertAdjacentHTML('afterbegin',
            `<div class="h3d-error" role="alert">WebGL is not available in this browser: ${escapeHTML(e.message)}</div>`);
        return;
    }
    _start();
}

export function initHall3dView() {
    if (_initialized) return;
    if (!$root()) return;
    registerRoute(ROUTE_ID, {
        viewId: VIEW_ID,
        activate: ({ firstActivation }) => {
            if (firstActivation) _boot();
            else { _ctx?.resize?.(); _start(); }
        },
    });
    try { subscribe('channels', _onChannels); } catch { /* state bus optional */ }
    _initialized = true;
}

export const __hall3d_test__ = { headerHtml, livePanelHtml, boot: _boot, ctx: () => _ctx, onChannels: _onChannels };
