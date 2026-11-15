/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — frontend/assets/js/core/synchroscope.js
 *
 * T3: synchroscope (ANSI 25) for the closed-transition TRAINING mode.
 * The server sends angle and slip at each poll; between polls the
 * needle is extrapolated with the slip (360 x slip degrees per
 * second) so it turns smoothly. The permissive lamp shown here is a
 * display estimate: the server's sync-check decides. EXECUTE arms a
 * sync-check supervised close: the server closes 52-U at the instant
 * angle and slip are in the window (up to 30 s), so the operator's job
 * is the governor, not the click timing.
 * Clockwise = generator bus faster than the utility.
 * ════════════════════════════════════════════════════════════════ */

import { escapeHTML } from './sanitize.js';

export function wrapDeg(a) {
    return ((((a + 180) % 360) + 360) % 360) - 180;
}

/** Needle angle now, from the last server sample. */
export function needleAngle(sync, receivedAtMs, nowMs) {
    if (!sync) return 0;
    if (!sync.live) return Number(sync.angle_deg) || 0;
    const dt = Math.max(0, (nowMs - receivedAtMs) / 1000);
    return wrapDeg((Number(sync.angle_deg) || 0) + 360 * (Number(sync.slip_hz) || 0) * dt);
}

export function permissive(sync, angle) {
    return !!sync && !!sync.live && Math.abs(angle) <= sync.max_angle_deg
        && Math.abs(Number(sync.slip_hz)) <= sync.max_slip_hz;
}

/** Seconds until the window, from the last server sample (null = never). */
export function etaNow(sync, receivedAtMs, nowMs) {
    if (!sync || !sync.live || sync.window_eta_s == null) return null;
    const left = Number(sync.window_eta_s) - Math.max(0, (nowMs - receivedAtMs) / 1000);
    return left > 0 ? left : 0;
}

export function etaText(eta) {
    if (eta == null) return 'Window: not reached at this slip';
    return eta <= 0 ? 'IN WINDOW' : `Window in ${eta.toFixed(1)} s`;
}

const fmt = (v, d) => (Number(v) >= 0 ? '+' : '') + Number(v).toFixed(d);

export function synchroscopeHtml(deviceId, sync, angle = Number(sync?.angle_deg) || 0) {
    if (!sync || !sync.enabled) return '';
    const id = escapeHTML(deviceId);
    const w = Number(sync.max_angle_deg) || 10;
    const r = 52;
    const pt = (deg, rad) => {
        const t = (deg - 90) * Math.PI / 180;
        return `${(60 + rad * Math.cos(t)).toFixed(2)} ${(60 + rad * Math.sin(t)).toFixed(2)}`;
    };
    const ticks = Array.from({ length: 12 }, (_, i) => i * 30)
        .map((d) => `<path class="sy-tick" d="M${pt(d, r - 6)} L${pt(d, r)}"/>`).join('');
    const wedge = `<path class="sy-window" d="M60 60 L${pt(-w, r)} A${r} ${r} 0 0 1 ${pt(w, r)} Z"/>`;
    const ok = permissive(sync, angle);
    return `<div class="sy" data-sync="${id}">`
        + `<svg class="sy-dial" viewBox="0 0 120 120" role="img" aria-label="Synchroscope">`
        + `<circle class="sy-face" cx="60" cy="60" r="${r}"/>${wedge}${ticks}`
        + `<text class="sy-lbl" x="96" y="20">FAST</text><text class="sy-lbl" x="2" y="20">SLOW</text>`
        + `<line class="sy-needle" data-sync-needle="${id}" x1="60" y1="60" x2="60" y2="14" `
        + `transform="rotate(${angle.toFixed(1)} 60 60)"/><circle class="sy-hub" cx="60" cy="60" r="4"/></svg>`
        + '<div class="sy-read">'
        + `<span>GEN <b>${Number(sync.gen_hz).toFixed(3)} Hz</b></span>`
        + `<span>UTIL <b>${Number(sync.utility_hz).toFixed(3)} Hz</b></span>`
        + `<span>SLIP <b>${fmt(sync.slip_hz, 3)} Hz</b> (max ±${Number(sync.max_slip_hz).toFixed(2)})</span>`
        + `<span>Δφ <b data-sync-angle="${id}">${fmt(angle, 1)}°</b> (window ±${w.toFixed(0)}°)</span>`
        + `<span class="sy-lamp" data-sync-lamp="${id}" data-ok="${ok ? 1 : 0}">25 ${ok ? 'PERMIT' : 'BLOCK'}</span>`
        + `<span class="sy-eta" data-sync-eta="${id}">${escapeHTML(etaText(sync.live ? sync.window_eta_s : null))}</span>`
        + (sync.close_armed
            ? `<span class="sy-armed">SYNC CLOSE ARMED · closes in window · ${Number(sync.close_remaining_s || 0).toFixed(0)} s left `
              + `<button type="button" class="fp-btn" data-fp-synccancel="${id}">Cancel</button></span>` : '')
        + (sync.live ? '' : '<span class="sy-note">Not islanded: no phase drift</span>')
        + '</div>'
        + '<div class="sy-gov"><span>GOVERNOR</span>'
        + [-0.05, -0.01, 0.01, 0.05].map((d) => `<button type="button" class="fp-btn" data-fp-gov="${id}" `
            + `data-delta="${d}">${d < 0 ? 'LOWER' : 'RAISE'} ${Math.abs(d).toFixed(2)}</button>`).join('')
        + '</div>'
        + '<div class="sy-note">Training mode, outside the A3 design. EXECUTE arms a supervised close: '
        + 'the server closes 52-U when angle and slip are in the window (30 s max). Lamp and ETA are display estimates.</div></div>';
}
