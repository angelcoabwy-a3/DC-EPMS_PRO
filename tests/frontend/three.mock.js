/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — tests/frontend/three.mock.js
 * Minimal three.js stand-in for the T2.4 drill-down tests.
 *
 * The drill-down state machine (_onClick / _animateDrillDown /
 * _onPointerMove) only ever touches THREE.Vector3 directly; the
 * scene, camera, raycaster and renderer are dependency-injected as
 * plain fakes via __mc_test__.injectScene — so this mock stays tiny:
 * a working Vector3/Vector2 plus loud stubs for anything unexpected.
 * Loaded in place of /assets/vendor/three.module.min.js via vi.mock.
 * ════════════════════════════════════════════════════════════════ */

export class Vector3 {
    constructor(x = 0, y = 0, z = 0) { this.x = x; this.y = y; this.z = z; }
    set(x, y, z) { this.x = x; this.y = y; this.z = z; return this; }
    copy(v) { this.x = v.x; this.y = v.y; this.z = v.z; return this; }
    clone() { return new Vector3(this.x, this.y, this.z); }
    lerp(v, a) {
        this.x += (v.x - this.x) * a;
        this.y += (v.y - this.y) * a;
        this.z += (v.z - this.z) * a;
        return this;
    }
    lerpVectors(a, b, t) {
        this.x = a.x + (b.x - a.x) * t;
        this.y = a.y + (b.y - a.y) * t;
        this.z = a.z + (b.z - a.z) * t;
        return this;
    }
}

export class Vector2 {
    constructor(x = 0, y = 0) { this.x = x; this.y = y; }
}

// Raycaster: the module constructs one in _boot(), which the Bite 2
// tests never run (they inject a controllable fake raycaster instead).
export class Raycaster {
    setFromCamera() {}
    intersectObjects() { return []; }
}

export const REVISION = '0-mock';
export const MathUtils = { degToRad: (d) => (d * Math.PI) / 180 };
