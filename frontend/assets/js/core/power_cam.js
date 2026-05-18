/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — frontend/assets/js/core/power_cam.js
 *
 * Iso-stage camera controls for the 2.5D Power & UPS SLD.
 *
 *   Stateless lock to a fixed isometric angle was Lead Architect's
 *   constraint for v0.10.6/0.10.7 (operational clarity over kitsch).
 *   This module extends the same constraint with USER-OPERATED but
 *   bounded camera adjustments — the operator can zoom / pan / pitch
 *   to inspect a specific node, but cannot break out into free-roam
 *   3D (no orbit, no fly-through).
 *
 * Capabilities:
 *   - Zoom: scroll wheel + [+] / [−] buttons (clamped 0.4..2.5)
 *   - Pan:  mouse drag (clamped to ±400 px)
 *   - Pitch: [↑pitch] / [↓pitch] (clamped 30°..75°)
 *   - Yaw:   [⟲yaw] / [⟳yaw] (clamped -60°..0°)
 *   - Mode:  toggle ISO ↔ FLAT (legacy SVG)
 *   - Reset View: snap back to defaults
 *
 *   Pan uses translate3d in the iso world's compound transform, so
 *   it pans WITHIN the iso plane (not screen-space). For fault diag,
 *   that's actually what you want — pan to follow the busway as you
 *   zoom into RPP-A2.
 *
 * Integration:
 *   - Reads/writes _cam private state.
 *   - On every change, applies inline `transform` to .sld-iso-world,
 *     which overrides the static class rule + the responsive @media
 *     rule (inline > class specificity).
 *   - When mode='flat': hides .sld-iso-stage and unhides the legacy
 *     .pid-svg (which power_ups_iso.js had marked .sld-legacy-hidden).
 * ════════════════════════════════════════════════════════════════ */

const DEFAULTS = Object.freeze({
    zoom:  1.0,
    panX:  0,
    panY:  0,
    pitch: 55,    // rotateX degrees
    yaw:  -30,    // rotateZ degrees
    mode:  'iso', // 'iso' | 'flat'
});

const LIMITS = Object.freeze({
    zoom:  [0.4, 2.5],
    pan:   [-400, 400],
    pitch: [30, 75],
    yaw:  [-60, 0],
});

const ISO_BASE_SCALE = 0.95;  // flat 2.5D fills the stage (T2.1, was 0.78 for the rotated plane)

const _cam = { ...DEFAULTS };
let _initialized = false;
let _dragStart   = null;
let _dragMoved   = false;

// ─── Apply cam state to DOM ───────────────────────────────────────

function _applyCam() {
    const stage    = document.querySelector('.sld-iso-stage');
    const world    = document.querySelector('.sld-iso-world');
    const flatSvg  = document.querySelector('#view-power .pid-svg');
    if (!world) return;

    if (_cam.mode === 'flat') {
        if (stage) stage.style.display = 'none';
        if (flatSvg) flatSvg.classList.remove('sld-legacy-hidden');
    } else {
        if (stage) stage.style.display = '';
        if (flatSvg) flatSvg.classList.add('sld-legacy-hidden');
        const finalScale = (_cam.zoom * ISO_BASE_SCALE).toFixed(3);
        // T2.1 reinvention: flat 2.5D — no rotateX/rotateZ. Pan + zoom
        // only; pitch/yaw state is retained but no longer tilts the plane,
        // so node labels stay flat-to-screen and legible.
        world.style.transform =
            `translate3d(${_cam.panX}px, ${_cam.panY}px, 0) ` +
            `scale(${finalScale})`;
    }

    // Toolbar readouts
    _setText('cam-zoom-val',  _cam.zoom.toFixed(1) + '×');
    _setText('cam-pitch-val', _cam.pitch + '°');
    _setText('cam-yaw-val',   _cam.yaw   + '°');
    _setText('cam-mode-val',  _cam.mode === 'iso' ? 'ISO' : 'FLAT');
    const modeBtn = document.getElementById('cam-mode-toggle');
    if (modeBtn) modeBtn.textContent = _cam.mode === 'iso' ? 'View: ISO' : 'View: FLAT';
}

function _setText(id, txt) {
    const el = document.getElementById(id);
    if (el) el.textContent = txt;
}

function _clamp(v, [lo, hi]) { return Math.max(lo, Math.min(hi, v)); }

// ─── Public API (also bound to buttons below) ─────────────────────

export function camZoom(delta)  {
    _cam.zoom  = _clamp(_cam.zoom * (delta > 0 ? 1.12 : 1 / 1.12), LIMITS.zoom);
    _applyCam();
}
export function camPitch(delta) { _cam.pitch = _clamp(_cam.pitch + delta, LIMITS.pitch); _applyCam(); }
export function camYaw(delta)   { _cam.yaw   = _clamp(_cam.yaw   + delta, LIMITS.yaw);   _applyCam(); }
export function camPan(dx, dy)  {
    _cam.panX = _clamp(_cam.panX + dx, LIMITS.pan);
    _cam.panY = _clamp(_cam.panY + dy, LIMITS.pan);
    _applyCam();
}
export function camToggleMode() {
    _cam.mode = _cam.mode === 'iso' ? 'flat' : 'iso';
    _applyCam();
}
export function camReset() {
    Object.assign(_cam, DEFAULTS);
    _applyCam();
}
export function getCamState() { return { ..._cam }; }

// ─── Wheel + drag handlers (bound to the iso stage) ───────────────

function _onWheel(e) {
    if (_cam.mode !== 'iso') return;
    e.preventDefault();
    camZoom(e.deltaY < 0 ? +1 : -1);
}

function _onMouseDown(e) {
    if (_cam.mode !== 'iso') return;
    // Don't start drag on TRIP pip / shift-click (let those events through)
    if (e.target.closest('.iso-trip-pip')) return;
    if (e.shiftKey) return;
    if (e.button !== 0) return;
    _dragStart = { x: e.clientX, y: e.clientY, panX: _cam.panX, panY: _cam.panY };
    _dragMoved = false;
    const stage = document.querySelector('.sld-iso-stage');
    if (stage) stage.style.cursor = 'grabbing';
}

function _onMouseMove(e) {
    if (!_dragStart) return;
    const dx = e.clientX - _dragStart.x;
    const dy = e.clientY - _dragStart.y;
    if (Math.abs(dx) > 4 || Math.abs(dy) > 4) _dragMoved = true;
    _cam.panX = _clamp(_dragStart.panX + dx, LIMITS.pan);
    _cam.panY = _clamp(_dragStart.panY + dy, LIMITS.pan);
    _applyCam();
}

function _onMouseUp(e) {
    if (!_dragStart) return;
    _dragStart = null;
    const stage = document.querySelector('.sld-iso-stage');
    if (stage) stage.style.cursor = '';
    // If we actually dragged, swallow the subsequent click to prevent
    // accidental drill-down on the node we panned off of.
    if (_dragMoved) {
        const swallow = (ev) => {
            ev.stopPropagation();
            ev.preventDefault();
            window.removeEventListener('click', swallow, true);
        };
        window.addEventListener('click', swallow, true);
    }
}

// Keyboard nudges — arrows pan, +/- zoom, [/] yaw, '/. pitch
function _onKey(e) {
    // Only when #power view is active
    const powerView = document.getElementById('view-power');
    if (!powerView || powerView.hasAttribute('hidden')) return;
    // Don't interfere with form fields
    const tag = (e.target && e.target.tagName) || '';
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

    const PAN = 24;
    switch (e.key) {
        case 'ArrowLeft':  camPan(+PAN, 0); e.preventDefault(); break;
        case 'ArrowRight': camPan(-PAN, 0); e.preventDefault(); break;
        case 'ArrowUp':    camPan(0, +PAN); e.preventDefault(); break;
        case 'ArrowDown':  camPan(0, -PAN); e.preventDefault(); break;
        case '+': case '=': camZoom(+1); e.preventDefault(); break;
        case '-': case '_': camZoom(-1); e.preventDefault(); break;
        case '[':  camYaw(-5);   e.preventDefault(); break;
        case ']':  camYaw(+5);   e.preventDefault(); break;
        case ',':  camPitch(-3); e.preventDefault(); break;
        case '.':  camPitch(+3); e.preventDefault(); break;
        case '0':  camReset();   e.preventDefault(); break;
        case 'f': case 'F': camToggleMode(); e.preventDefault(); break;
        default: break;
    }
}

// ─── Toolbar wiring ───────────────────────────────────────────────

function _wireToolbar() {
    const bind = (id, fn) => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('click', (e) => { e.preventDefault(); fn(); });
    };
    bind('cam-zoom-in',     () => camZoom(+1));
    bind('cam-zoom-out',    () => camZoom(-1));
    bind('cam-pitch-up',    () => camPitch(+3));
    bind('cam-pitch-down',  () => camPitch(-3));
    bind('cam-yaw-left',    () => camYaw(-5));
    bind('cam-yaw-right',   () => camYaw(+5));
    bind('cam-mode-toggle', () => camToggleMode());
    bind('cam-reset',       () => camReset());
}

// ─── Public init ──────────────────────────────────────────────────

export function initPowerCam() {
    if (_initialized) return;
    const stage = document.querySelector('.sld-iso-stage');
    if (!stage) {
        // SLD not yet mounted; retry once on next microtask
        queueMicrotask(initPowerCam);
        return;
    }
    stage.addEventListener('wheel',     _onWheel,     { passive: false });
    stage.addEventListener('mousedown', _onMouseDown);
    window.addEventListener('mousemove', _onMouseMove);
    window.addEventListener('mouseup',   _onMouseUp);
    window.addEventListener('keydown',   _onKey);

    // Set grab cursor when in iso mode
    stage.style.cursor = 'grab';

    _wireToolbar();
    _applyCam();
    _initialized = true;
    console.log('[power_cam] camera controls active: wheel zoom, drag pan, +/- pitch/yaw, F = flat toggle, 0 = reset');
}
