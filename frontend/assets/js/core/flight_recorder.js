/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — core/flight_recorder.js
 * Forensic Replay (innovation track R2) — the HMI's black box.
 *
 * In-browser ring buffer of everything the diagrams render from:
 * Hermes telemetry frames + power/cooling DAG snapshots, all
 * timestamped. snapshotAt(t) reconstructs the full diagram state at
 * any instant in the window — because the Diagram Rebuild made every
 * diagram a pure function of state, REPLAY IS JUST RE-RENDER.
 *
 * Market note: historians (PI, Ignition) replay value trends; none
 * replays the complete live mimic as video, and none interleaves
 * the operator's actions with their HMAC chain-of-custody (that
 * overlay is the view's job, fed by /api/ledger/entries).
 *
 * HONEST SCOPE: a SESSION recorder — last ~10 min (600 ticks @ 1 Hz)
 * held in browser memory since page load. Not persisted history;
 * the UI says so.
 * ════════════════════════════════════════════════════════════════ */

import { onHermesStream } from '../services/api.js';
import { subscribe } from './state.js';

const CAP = 600;                       // ~10 min @ 1 Hz
const KINDS = ['telemetry', 'grid', 'coolgrid'];

let _buf = [];                         // [{t, kind, payload}] (t ascending)
let _unsubs = [];
let _recording = false;

/** Append one timestamped entry; evict beyond capacity. */
export function record(kind, payload, t = Date.now()) {
    if (!KINDS.includes(kind) || payload == null) return;
    _buf.push({ t, kind, payload });
    if (_buf.length > CAP) _buf.splice(0, _buf.length - CAP);
}

/** Latest entry of each kind at or before `t` (the diagram state then). */
export function snapshotAt(t) {
    const snap = { telemetry: null, grid: null, coolgrid: null };
    for (const e of _buf) {
        if (e.t > t) break;
        snap[e.kind] = e.payload;
    }
    return snap;
}

/** Recording window. count=0 -> nothing to replay yet. */
export function range() {
    if (!_buf.length) return { start: 0, end: 0, count: 0 };
    return { start: _buf[0].t, end: _buf[_buf.length - 1].t, count: _buf.length };
}

/** Begin recording the live planes. Idempotent. */
export function startRecording() {
    if (_recording) return;
    _unsubs.push(onHermesStream('telemetry', (p) => {
        if (p && p.channels) record('telemetry', p);
    }));
    _unsubs.push(subscribe('grid', (g) => record('grid', g)));
    _unsubs.push(subscribe('coolgrid', (g) => record('coolgrid', g)));
    _recording = true;
    console.log('[flight_recorder] session black box armed (cap %d ticks)', CAP);
}

export function stopRecording() {
    _unsubs.forEach((u) => { try { u(); } catch {} });
    _unsubs = [];
    _recording = false;
}

export function isRecording() { return _recording; }

/** Test/maintenance surface. */
export const __recorder_test__ = {
    CAP,
    clear: () => { _buf = []; },
    size: () => _buf.length,
};
