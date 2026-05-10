/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — core/sound.js
 *
 * Tier C / C1: Toggleable WebAudio sound design.
 *
 * Three voices generated synthetically (no external assets):
 *   - click()        Subtle 1.2 kHz tick  ~25 ms · approve/reject buttons
 *   - veto()         Two-tone descending alarm 880 → 440 Hz · ~400 ms
 *                    Triggered when Safety Officer fires HARD_STOP.
 *   - warning()      Single 660 Hz beep ~150 ms · SSE disconnect / stale
 *
 * Discipline:
 *   - WebAudio is gated by a one-time user gesture (browser policy).
 *     We initialize the AudioContext lazily on the first toggle-on or
 *     the first emit attempt; no audio plays before the user interacts.
 *   - localStorage 'epms_sound_enabled' persists the toggle across loads.
 *   - prefers-reduced-motion honored: when user has reduced-motion set
 *     OR the OS reports that they prefer reduced motion, sounds default
 *     to OFF and the toggle preserves that choice.
 *   - No sound during dev hot-reload OR when window.__epms.silent is set.
 *
 * Exports:
 *   initSound(), playClick(), playVeto(), playWarning(),
 *   isSoundEnabled(), setSoundEnabled(boolean), toggleSound()
 * ════════════════════════════════════════════════════════════════ */

const STORAGE_KEY = 'epms_sound_enabled';
const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';

let _audioCtx = null;
let _enabled = null;          // tri-state until first read: null | true | false
let _initialized = false;
let _toggleEl = null;

// ─── Toggle state ────────────────────────────────────────────────
function _readEnabled() {
    if (_enabled !== null) return _enabled;
    try {
        const stored = localStorage.getItem(STORAGE_KEY);
        if (stored === 'true') { _enabled = true;  return true; }
        if (stored === 'false') { _enabled = false; return false; }
    } catch { /* localStorage blocked */ }
    // Default OFF if user prefers reduced motion, else ON
    const reduce = window.matchMedia?.(REDUCED_MOTION_QUERY)?.matches === true;
    _enabled = !reduce;
    return _enabled;
}

function _writeEnabled(v) {
    _enabled = !!v;
    try { localStorage.setItem(STORAGE_KEY, _enabled ? 'true' : 'false'); } catch {}
    _renderToggleIcon();
}

export function isSoundEnabled() { return _readEnabled(); }
export function setSoundEnabled(v) { _writeEnabled(v); }
export function toggleSound() { _writeEnabled(!_readEnabled()); }

// ─── AudioContext lazy init ──────────────────────────────────────
function _ensureCtx() {
    if (_audioCtx) return _audioCtx;
    const Ctor = window.AudioContext || window.webkitAudioContext;
    if (!Ctor) return null;
    try { _audioCtx = new Ctor({ latencyHint: 'interactive' }); }
    catch { return null; }
    return _audioCtx;
}

function _emit(toneFn) {
    if (!_readEnabled()) return;
    if (window.__epms?.silent) return;
    const ctx = _ensureCtx();
    if (!ctx) return;
    if (ctx.state === 'suspended') {
        ctx.resume().catch(() => {});
    }
    try { toneFn(ctx, ctx.currentTime); } catch (e) { /* swallow */ }
}

// ─── Voice 1: subtle click (approve/reject buttons) ──────────────
export function playClick() {
    _emit((ctx, t0) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'square';
        osc.frequency.value = 1200;
        gain.gain.setValueAtTime(0.0001, t0);
        gain.gain.exponentialRampToValueAtTime(0.06, t0 + 0.005);
        gain.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.025);
        osc.connect(gain); gain.connect(ctx.destination);
        osc.start(t0); osc.stop(t0 + 0.030);
    });
}

// ─── Voice 2: VETO alarm (two-tone descending) ───────────────────
export function playVeto() {
    _emit((ctx, t0) => {
        // First tone (high): 880 Hz ~150 ms
        const o1 = ctx.createOscillator();
        const g1 = ctx.createGain();
        o1.type = 'triangle';
        o1.frequency.value = 880;
        g1.gain.setValueAtTime(0.0001, t0);
        g1.gain.exponentialRampToValueAtTime(0.18, t0 + 0.010);
        g1.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.150);
        o1.connect(g1); g1.connect(ctx.destination);
        o1.start(t0); o1.stop(t0 + 0.160);

        // Second tone (low): 440 Hz ~250 ms, slight overlap
        const o2 = ctx.createOscillator();
        const g2 = ctx.createGain();
        o2.type = 'triangle';
        o2.frequency.value = 440;
        const t2 = t0 + 0.140;
        g2.gain.setValueAtTime(0.0001, t2);
        g2.gain.exponentialRampToValueAtTime(0.20, t2 + 0.010);
        g2.gain.exponentialRampToValueAtTime(0.0001, t2 + 0.250);
        o2.connect(g2); g2.connect(ctx.destination);
        o2.start(t2); o2.stop(t2 + 0.260);
    });
}

// ─── Voice 3: warning beep (SSE disconnect, stale data) ──────────
export function playWarning() {
    _emit((ctx, t0) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.value = 660;
        gain.gain.setValueAtTime(0.0001, t0);
        gain.gain.exponentialRampToValueAtTime(0.12, t0 + 0.020);
        gain.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.150);
        osc.connect(gain); gain.connect(ctx.destination);
        osc.start(t0); osc.stop(t0 + 0.160);
    });
}

// ─── Toggle icon in the header ───────────────────────────────────
function _renderToggleIcon() {
    if (!_toggleEl) return;
    const on = _readEnabled();
    _toggleEl.setAttribute('aria-pressed', on ? 'true' : 'false');
    _toggleEl.title = on ? 'Sound: ON (click to mute)' : 'Sound: OFF (click to enable)';
    _toggleEl.classList.toggle('sound-on', on);
    _toggleEl.classList.toggle('sound-off', !on);
    _toggleEl.innerHTML = on
        ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>'
        : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="22" x2="16" y1="9" y2="15"/><line x1="16" x2="22" y1="9" y2="15"/></svg>';
}

// ─── Public init ────────────────────────────────────────────────
export function initSound() {
    if (_initialized) return;
    _initialized = true;

    _toggleEl = document.getElementById('epms-sound-toggle');
    if (_toggleEl) {
        _toggleEl.addEventListener('click', () => {
            toggleSound();
            // Play a confirmation click on enable so user knows it works
            if (_readEnabled()) playClick();
        });
    }
    _renderToggleIcon();
    console.log('[sound] ready (enabled=%s)', _readEnabled());
}
