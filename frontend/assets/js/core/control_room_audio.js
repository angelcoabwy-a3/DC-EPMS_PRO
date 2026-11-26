/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — frontend/assets/js/core/control_room_audio.js
 *
 * T2 (2026-11-15): procedural control-room sounds with the Web Audio
 * API, no audio files. OFF by default; browsers only allow audio after
 * a user gesture, so it is switched on from a button.
 *
 *   breaker(close)  short mechanical thud for a breaker operation
 *   alarm(priority) HIGH: two-tone pulse, MEDIUM / LOW: single tone
 *   chime()         drill step completed
 *   engineStart()   low ramp for a generator bus start
 *
 * These are cues, not recordings of real equipment. Fails silent when
 * the browser has no AudioContext.
 * ════════════════════════════════════════════════════════════════ */

const STORE_KEY = 'dcepms.audio.on';

export class ControlRoomAudio {
    constructor(win = (typeof window !== 'undefined' ? window : null)) {
        this.win = win;
        this.ctx = null;
        this.on = false;
        try {
            this.on = !!win && win.localStorage?.getItem(STORE_KEY) === '1';
        } catch (_e) { this.on = false; }
    }

    get supported() {
        return !!(this.win && (this.win.AudioContext || this.win.webkitAudioContext));
    }

    setOn(on) {
        this.on = !!on && this.supported;
        try { this.win?.localStorage?.setItem(STORE_KEY, this.on ? '1' : '0'); } catch (_e) { /* storage blocked */ }
        if (this.on) this._ctx();
        return this.on;
    }

    _ctx() {
        if (!this.on || !this.supported) return null;
        if (!this.ctx) {
            const Ctor = this.win.AudioContext || this.win.webkitAudioContext;
            try { this.ctx = new Ctor(); } catch (_e) { return null; }
        }
        if (this.ctx.state === 'suspended' && this.ctx.resume) this.ctx.resume();
        return this.ctx;
    }

    _tone(type, f0, f1, gain, dur, delay = 0) {
        const ctx = this._ctx();
        if (!ctx) return false;
        const t = ctx.currentTime + delay;
        const osc = ctx.createOscillator();
        const g = ctx.createGain();
        osc.type = type;
        osc.frequency.setValueAtTime(f0, t);
        if (f1 !== f0) osc.frequency.exponentialRampToValueAtTime(f1, t + dur);
        g.gain.setValueAtTime(gain, t);
        g.gain.exponentialRampToValueAtTime(0.001, t + dur);
        osc.connect(g);
        g.connect(ctx.destination);
        osc.start(t);
        osc.stop(t + dur + 0.02);
        return true;
    }

    breaker(close = true) {
        const a = this._tone('triangle', close ? 135 : 110, 28, 0.5, 0.18);
        if (a) this._tone('sawtooth', close ? 920 : 680, 190, 0.2, 0.07, 0.02);
        return a;
    }

    alarm(priority = 'HIGH') {
        if (priority === 'HIGH') {
            const a = this._tone('square', 880, 880, 0.08, 0.12);
            if (a) this._tone('square', 660, 660, 0.08, 0.12, 0.13);
            return a;
        }
        return this._tone('square', 520, 520, 0.06, 0.2);
    }

    chime() {
        const a = this._tone('sine', 587.33, 587.33, 0.1, 0.12);
        if (a) this._tone('sine', 880, 880, 0.1, 0.18, 0.09);
        return a;
    }

    engineStart() {
        return this._tone('sawtooth', 24, 60, 0.12, 1.8);
    }

    /** L1: short filtered-noise burst (mechanical transients). */
    _noise(gain, dur, delay = 0, freq = 2400) {
        const ctx = this._ctx();
        if (!ctx || !ctx.createBuffer) return false;
        const t = ctx.currentTime + delay;
        const n = Math.max(1, Math.floor(ctx.sampleRate * dur));
        const buf = ctx.createBuffer(1, n, ctx.sampleRate);
        const data = buf.getChannelData(0);
        for (let i = 0; i < n; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / n);
        const src = ctx.createBufferSource();
        src.buffer = buf;
        const g = ctx.createGain();
        g.gain.setValueAtTime(gain, t);
        let node = src;
        if (ctx.createBiquadFilter) {
            const f = ctx.createBiquadFilter();
            f.type = 'bandpass';
            f.frequency.value = freq;
            src.connect(f);
            node = f;
        }
        node.connect(g);
        g.connect(ctx.destination);
        src.start(t);
        return true;
    }

    /** Racking crank: a train of pawl clicks. */
    ratchet(clicks = 12, span = 1.0) {
        let ok = false;
        for (let i = 0; i < clicks; i++) ok = this._noise(0.25, 0.018, (i * span) / clicks, 3200) || ok;
        return ok;
    }

    /** Charging-handle stroke: one heavy pawl click and a spring creak. */
    pump() {
        const a = this._noise(0.35, 0.03, 0, 1800);
        if (a) this._tone('triangle', 240, 150, 0.08, 0.12, 0.03);
        return a;
    }

    /** Interlock: the mechanism refuses, a dull metallic stop. */
    clunk() {
        const a = this._tone('square', 70, 45, 0.25, 0.12);
        if (a) this._noise(0.2, 0.05, 0, 700);
        return a;
    }

    /** L2: internal arc in oil, a contained detonation: low thump,
     *  broadband burst and the tank ringing down. */
    arc() {
        const a = this._tone('sine', 62, 24, 0.9, 0.7);
        if (a) {
            this._noise(0.8, 0.35, 0, 400);
            this._noise(0.4, 0.6, 0.05, 1500);
            this._tone('triangle', 180, 90, 0.15, 1.2, 0.1);
        }
        return a;
    }

    /** Padlock shackle or key switch. */
    latch() {
        const a = this._noise(0.3, 0.012, 0, 5200);
        if (a) this._noise(0.2, 0.012, 0.06, 4200);
        return a;
    }
}
