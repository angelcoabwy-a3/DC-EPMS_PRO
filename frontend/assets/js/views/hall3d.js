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
import { buildSceneSpec, chainEntry, COLOURS, DRAW } from '../core/hall3d_model.js';

const VIEW_ID = 'view-hall-3d';
const ROUTE_ID = 'hall-3d';
const DESIGN_URL = '/api/design/building-d';
const RACKS_URL = '/api/design/building-d/racks';
const MAX_PIXEL_RATIO = 1.5;

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
                <span data-h3d-fps>- fps</span>
            </div>
            <div class="h3d-legend">
                <div><i style="background:#ff2bd6"></i>800 VDC busway, path A</div>
                <div><i style="background:#b04dff"></i>800 VDC busway, path B</div>
                <div><i style="background:#2f8cff"></i>DLC supply</div>
                <div><i style="background:#ff4b3e"></i>DLC return</div>
            </div>
            <div class="h3d-note" role="note">DESIGN layout of a simulated facility (ADR-021). Rack internals,
                tap-off boxes and pipe sizes are schematic. Live telemetry binding comes in the next lot.</div>
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
    scene.add(_instanced(new THREE.BoxGeometry(w * 0.98, h, d * 0.98), body, list,
        (r, p) => p.set(...r.center)));
    // front door panel (cold-aisle side) and a status strip
    scene.add(_instanced(new THREE.BoxGeometry(w * 0.9, h * 0.94, 0.02), door, list,
        (r, p) => p.set(r.center[0], r.center[1], r.center[2] - d / 2 - 0.006)));
    scene.add(_instanced(new THREE.BoxGeometry(w * 0.6, 0.02, 0.01), led, list,
        (r, p) => p.set(r.center[0], h * 0.92, r.center[2] - d / 2 - 0.02)));
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
    scene.add(g);
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
        flows.push({ tex, sign: b.flowSign });
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
function _build(root, spec) {
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
    _racks(scene, spec);
    _cutawayRack(scene, spec);
    const flows = _busways(scene, spec);
    _pipes(scene, spec);
    _cdus(scene, spec);

    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 400);
    const detail = spec.racks.find((x) => x.id === spec.detail);
    // Portrait screens see less sideways: start further back and higher.
    const portrait = stage.clientWidth < stage.clientHeight;
    if (portrait) camera.position.set(-4.8, 3.6, -8.0);
    else camera.position.set(-1.6, 2.1, -3.4);
    const controls = new OrbitControls(camera, canvas);
    controls.enableDamping = true;
    controls.maxPolarAngle = Math.PI * 0.49;
    controls.minDistance = 1.5;
    controls.maxDistance = 90;
    controls.target.set(detail ? detail.center[0] + 2.6 : spec.center[0], 1.5, detail ? detail.center[2] + 0.4 : spec.center[2]);

    const composer = new EffectComposer(renderer);
    composer.addPass(new RenderPass(scene, camera));
    const bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.7, 0.35, 1.6);
    composer.addPass(bloom);
    composer.addPass(new OutputPass());

    const ctx = { renderer, composer, bloom, scene, camera, controls, flows, raf: 0, stage,
        frames: 0, fpsT: performance.now(), last: performance.now(), fpsEl: root.querySelector('[data-h3d-fps]') };
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
    return ctx;
}

function _frame(now) {
    const ctx = _ctx;
    if (!ctx) return;
    if ($root()?.hidden) { ctx.raf = 0; return; }
    const dt = Math.min(0.1, (now - ctx.last) / 1000);
    ctx.last = now;
    for (const f of ctx.flows) f.tex.offset.x -= f.sign * dt * 0.6;
    ctx.controls.update();
    ctx.composer.render();
    ctx.frames += 1;
    if (now - ctx.fpsT >= 1000) {
        const fps = (ctx.frames * 1000) / (now - ctx.fpsT);
        if (ctx.fpsEl) ctx.fpsEl.textContent = `${fps.toFixed(0)} fps`;
        ctx.frames = 0; ctx.fpsT = now;
    }
    ctx.raf = requestAnimationFrame(_frame);
}

function _start() {
    if (_ctx && !_ctx.raf) {
        _ctx.last = performance.now();
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
        _ctx = _build(root, spec);
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
    _initialized = true;
}

export const __hall3d_test__ = { headerHtml, boot: _boot, ctx: () => _ctx };
