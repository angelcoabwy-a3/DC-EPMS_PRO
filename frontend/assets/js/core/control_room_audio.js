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
}
