/**
 * L2 (2026-11-26): field view of the utility transformer of one path
 * (Layer 2, equipment look; ADR-014). Marshalling box with the
 * temperature monitor (top oil 26 / winding 49, fan stages), liquid
 * level and nitrogen gauges, fan selector and the 63 / 87T / 86T
 * relays; the de-energized tap changer (DETC) with its key lock; the
 * trapped-key chain K1 / K2 across 52-U, 52-T and the DETC; and the
 * 27.5 kV primary circuit switcher 52-T.
 *
 * Same contract as field_switchgear.js: the SVG is built once per
 * open (xfmrSvg) with data hooks, applyXfmrState() writes attributes
 * and texts from GET /api/devices (device mvtc_x -> "transformer"),
 * and every action is a server call (POST /api/devices/{id}/xfmr):
 * the server owns the interlocks, the drawing never decides.
 *
 * Honest scope: simulated equipment. Thermal values come from a model
 * with typical constants and compressed time (the panel says so);
 * liquid level and nitrogen pressure are illustrative.
 */
import { escapeHTML } from './sanitize.js';
import { door, fsgDefs, led } from './field_switchgear.js';

export const XFMR_EVENT_KINDS = Object.freeze([
    'interlock_defeated', 'xfmr_internal_fault', 'xfmr_temperature_alarm', 'xfmr_temperature_normal',
]);
const DETC_ANGLE = [-64, -32, 0, 32, 64];          // positions 1..5
const SEGS = 28;                                    // 0..140 C, 5 C per segment
const SEG_C = 5;
const FAN_ANGLE = { OFF: -45, AUTO: 0, ON: 45 };
const e = (v) => escapeHTML(v === null || v === undefined ? '' : String(v));

function bar(key, x, y) {
    let s = `<g class="xf-bar" data-bar="${key}" transform="translate(${x} ${y})">`;
    for (let i = 0; i < SEGS; i++) {
        s += `<rect class="xf-seg" data-i="${i}" x="${i * 8}" y="0" width="6" height="12" rx="1"/>`;
    }
    for (const c of [0, 50, 100, 140]) {
        s += `<text x="${(c / SEG_C) * 8}" y="22" class="xf-scale" text-anchor="middle">${c}</text>`;
    }
    return s + '</g>';
}

function dial(cx, cy, key, title, lo, mid, hi) {
    let ticks = '';
    for (let i = 0; i <= 8; i++) {
        const a = (-120 + i * 30) * Math.PI / 180;
        const r1 = 34, r2 = i % 4 === 0 ? 27 : 30;
        ticks += `<line x1="${(Math.sin(a) * r1).toFixed(1)}" y1="${(-Math.cos(a) * r1).toFixed(1)}" `
            + `x2="${(Math.sin(a) * r2).toFixed(1)}" y2="${(-Math.cos(a) * r2).toFixed(1)}" class="xf-tick"/>`;
    }
    return `<g transform="translate(${cx} ${cy})">`
        + '<circle r="44" class="xf-dial-bezel"/><circle r="38" class="xf-dial-face"/>' + ticks
        + `<text x="-26" y="22" class="xf-scale-d" text-anchor="middle">${lo}</text>`
        + `<text y="-16" class="xf-scale-d" text-anchor="middle">${mid}</text>`
        + `<text x="26" y="22" class="xf-scale-d" text-anchor="middle">${hi}</text>`
        + `<g class="xf-needle" data-needle="${key}"><path d="M-2 4 L0 -32 L2 4 Z" class="xf-needle-shape"/></g>`
        + '<circle r="4" class="xf-needle-hub"/>'
        + `<text y="34" class="xf-dial-val" data-txt="${key}" text-anchor="middle"></text>`
        + `<text y="60" class="fsg-label" text-anchor="middle">${title}</text></g>`;
}

function keyIcon(name, cls = '') {
    return `<g class="xf-key ${cls}"><circle r="7" class="xf-key-bow"/><circle r="2.4" class="xf-key-hole"/>`
        + '<rect x="6" y="-2" width="20" height="4" class="xf-key-blade"/>'
        + '<rect x="20" y="2" width="3" height="4" class="xf-key-blade"/><rect x="24" y="2" width="2" height="3" class="xf-key-blade"/>'
        + `<text y="18" class="xf-key-name" text-anchor="middle">${name}</text></g>`;
}

function lockCyl(x, y, id, label, sub) {
    return `<g class="xf-lock" data-act="${id}" data-lock="${id}" role="button" tabindex="0" transform="translate(${x} ${y})">`
        + '<rect x="-46" y="-34" width="92" height="88" fill="transparent"/>'
        + '<circle r="22" class="xf-lock-body"/><circle r="15" class="xf-lock-cyl"/>'
        + '<g class="xf-lock-plug"><rect x="-2.2" y="-11" width="4.4" height="22" rx="1" class="xf-lock-slot"/></g>'
        + `<g class="xf-lock-key" transform="translate(36 0) rotate(180)">${keyIcon('')}</g>`
        + `<text y="38" class="fsg-label" text-anchor="middle">${label}</text>`
        + `<text y="49" class="fsg-tiny" text-anchor="middle">${sub}</text></g>`;
}

function marshallingBox() {
    const X = 40, Y = 84;
    return door(X, Y, 420, 586, 'fsg-door-upper')
        + `<g class="fsg-nameplate" transform="translate(${X + 30} ${Y + 22})">`
        + '<rect width="230" height="58" rx="2" class="fsg-np-plate"/>'
        + '<circle cx="8" cy="8" r="2.2" class="fsg-rivet"/><circle cx="222" cy="8" r="2.2" class="fsg-rivet"/>'
        + '<circle cx="8" cy="50" r="2.2" class="fsg-rivet"/><circle cx="222" cy="50" r="2.2" class="fsg-rivet"/>'
        + '<text x="115" y="25" class="fsg-np-big" text-anchor="middle" data-txt="np">XFMR</text>'
        + '<text x="115" y="39" class="fsg-np-small" text-anchor="middle">15/20/25 MVA ONAN/ONAF1/ONAF2 (MODEL)</text>'
        + '<text x="115" y="50" class="fsg-np-small" text-anchor="middle">27.5 kV Δ / 13.8 kV Y · FR3 · N2 BLANKET</text></g>'
        + `<g class="fsg-afl" transform="translate(${X + 276} ${Y + 18})">`
        + '<rect width="118" height="64" rx="2" class="fsg-afl-body"/><rect width="118" height="18" rx="2" class="fsg-afl-head"/>'
        + '<text x="59" y="13" class="fsg-afl-head-txt" text-anchor="middle">DANGER</text>'
        + '<text x="59" y="31" class="fsg-afl-txt" text-anchor="middle">27.5 kV / 13.8 kV AC</text>'
        + '<text x="59" y="44" class="fsg-afl-strong" text-anchor="middle">ARC FLASH STUDY</text>'
        + '<text x="59" y="54" class="fsg-afl-strong" text-anchor="middle">NOT PERFORMED</text>'
        + '<title>Simulated equipment: no incident energy, boundary or PPE category exists (NFPA 70E 130.5, CSA Z462).</title></g>'
        // temperature monitor
        + `<g transform="translate(${X + 22} ${Y + 98})">`
        + '<rect width="376" height="168" rx="5" class="xf-mon"/>'
        + '<text x="12" y="17" class="xf-mon-head">WINDING / OIL TEMPERATURE MONITOR</text>'
        + '<text x="364" y="17" class="xf-mon-head" text-anchor="end" data-txt="timescale"></text>'
        + '<rect x="12" y="26" width="104" height="38" rx="2" class="xf-lcd"/>'
        + '<text x="18" y="38" class="xf-lcd-lbl">TOP OIL  26</text><text x="110" y="58" class="xf-lcd-big" data-txt="oil" text-anchor="end"></text>'
        + '<rect x="12" y="82" width="104" height="38" rx="2" class="xf-lcd"/>'
        + '<text x="18" y="94" class="xf-lcd-lbl">WINDING  49</text><text x="110" y="114" class="xf-lcd-big" data-txt="wdg" text-anchor="end"></text>'
        + bar('oil', 132, 38) + bar('wdg', 132, 94)
        + '<g data-marks="oil" transform="translate(132 38)"></g><g data-marks="wdg" transform="translate(132 94)"></g>'
        + '</g>'
        + led(X + 66, Y + 296, 'white', 'FAN 1', 'fan1')
        + led(X + 126, Y + 296, 'white', 'FAN 2', 'fan2')
        + led(X + 186, Y + 296, 'amber', 'ALARM', 'alarm')
        + led(X + 246, Y + 296, 'red', 'TRIP 86T', 'trip')
        + `<text x="${X + 280}" y="${Y + 293}" class="fsg-tiny">COOLING</text>`
        + `<text x="${X + 280}" y="${Y + 305}" class="xf-stage" data-txt="stage"></text>`
        // gauges + fan selector
        + dial(X + 84, Y + 384, 'level', 'LIQUID LEVEL', 'LO', '25 °C', 'HI')
        + dial(X + 210, Y + 384, 'n2', 'N2 BLANKET psig', '-10', '0', '+10')
        + `<g class="fsg-sel xf-fans" transform="translate(${X + 340} ${Y + 384})">`
        + '<circle r="34" class="fsg-sel-plate"/>'
        + '<g data-act="fans_off" role="button" tabindex="0"><rect x="-58" y="-44" width="34" height="20" fill="transparent"/><text x="-40" y="-30" class="fsg-tiny" text-anchor="middle">OFF</text></g>'
        + '<g data-act="fans_auto" role="button" tabindex="0"><rect x="-16" y="-54" width="32" height="18" fill="transparent"/><text y="-40" class="fsg-tiny" text-anchor="middle">AUTO</text></g>'
        + '<g data-act="fans_on" role="button" tabindex="0"><rect x="24" y="-44" width="38" height="20" fill="transparent"/><text x="42" y="-30" class="fsg-tiny" text-anchor="middle">HAND</text></g>'
        + '<g class="fsg-sel-knob xf-fan-knob"><circle r="19" class="fsg-sel-body"/>'
        + '<path d="M-4 -18 L4 -18 L3 6 L-3 6 Z" class="fsg-sel-bar"/><circle r="3" cy="-12" class="fsg-sel-dot"/></g>'
        + '<text y="52" class="fsg-label" text-anchor="middle">FANS</text></g>'
        // relays: 63, 87T, 86T
        + `<g transform="translate(${X + 22} ${Y + 470})"><rect width="376" height="100" rx="4" class="xf-relay-pan"/>`
        + '<text x="10" y="14" class="fsg-tiny fsg-light">TRANSFORMER PROTECTION</text></g>'
        + `<g transform="translate(${X + 86} ${Y + 524})">`
        + '<circle r="26" class="xf-63-body"/><circle r="17" class="xf-63-glass"/>'
        + '<g class="xf-63-flag"><rect x="-13" y="-6" width="26" height="12" rx="1" class="xf-63-flag-face"/></g>'
        + '<text y="40" class="fsg-tiny fsg-light" text-anchor="middle">63 SUDDEN PRESSURE</text>'
        + `<g class="xf-btn" data-act="r63" role="button" tabindex="0" transform="translate(40 -14)"><rect x="-14" y="-8" width="28" height="16" rx="3"/><text y="3.5" text-anchor="middle">RST</text></g></g>`
        + `<g transform="translate(${X + 208} ${Y + 524})">`
        + '<rect x="-40" y="-30" width="80" height="54" rx="3" class="xf-ied"/>'
        + '<rect x="-32" y="-22" width="64" height="18" rx="1" class="xf-lcd"/><text y="-9" class="xf-lcd-lbl" text-anchor="middle" data-txt="ied">87T</text>'
        + '<circle cx="-22" cy="10" r="5" class="xf-ied-led" data-led87="trip"/><text x="-14" y="13" class="xf-ied-txt">TRIP</text>'
        + '<g class="xf-btn" data-act="r87" role="button" tabindex="0" transform="translate(24 10)"><rect x="-14" y="-8" width="28" height="16" rx="3"/><text y="3.5" text-anchor="middle">RST</text></g>'
        + '<text y="40" class="fsg-tiny fsg-light" text-anchor="middle">87T DIFFERENTIAL</text></g>'
        + `<g class="fsg-86" data-act="86t" role="button" tabindex="0" transform="translate(${X + 336} ${Y + 518}) scale(.72)">`
        + '<circle r="44" class="fsg-86-bezel"/><circle r="36" class="fsg-86-face"/>'
        + '<rect x="-11" y="13" width="22" height="11" rx="1.5" class="fsg-86-target"/>'
        + '<g class="fsg-86-handle"><path d="M-6 6 L-6 -30 Q0 -40 6 -30 L6 6 Q0 12 -6 6 Z" class="fsg-86-grip"/><circle r="7" class="fsg-86-hub"/></g>'
        + '<text y="64" class="xf-86-lbl" text-anchor="middle">86T LOCKOUT</text>'
        + '<title>86T lockout relay: trips 52-T and 52-U; reset by hand after the 63 / 87T targets are recorded and reset.</title></g>';
}

function detcPanel() {
    const X = 510, Y = 84;
    let marks = '';
    DETC_ANGLE.forEach((a, i) => {
        const r = (a * Math.PI) / 180;
        const pct = ['+5.0', '+2.5', '0', '-2.5', '-5.0'][i];
        marks += `<g transform="translate(${(Math.sin(r) * 78).toFixed(1)} ${(-Math.cos(r) * 78).toFixed(1)})">`
            + `<text y="-2" class="xf-pos" text-anchor="middle">${i + 1}</text>`
            + `<text y="9" class="xf-pos-pct" text-anchor="middle">${pct}%</text></g>`;
    });
    return door(X, Y, 420, 236, 'fsg-door-upper')
        + `<text x="${X + 26}" y="${Y + 26}" class="fsg-label">DE-ENERGIZED TAP CHANGER (DETC)</text>`
        + `<g transform="translate(${X + 26} ${Y + 36})"><rect width="196" height="30" rx="2" class="xf-warn"/>`
        + '<text x="98" y="13" class="xf-warn-txt" text-anchor="middle">OPERATE ONLY WITH THE</text>'
        + '<text x="98" y="24" class="xf-warn-txt" text-anchor="middle">TRANSFORMER DE-ENERGIZED</text></g>'
        + `<g class="xf-detc" transform="translate(${X + 140} ${Y + 160})">`
        + '<circle r="64" class="xf-detc-plate"/><circle r="56" class="xf-detc-ring"/>' + marks
        + '<g class="xf-detc-handle"><rect x="-9" y="-58" width="18" height="76" rx="6" class="xf-detc-bar"/>'
        + '<circle r="16" class="xf-detc-hub"/><rect x="-3" y="-54" width="6" height="12" rx="2" class="xf-detc-ptr"/></g>'
        + '<text y="38" class="xf-detc-pos" data-txt="tap" text-anchor="middle"></text></g>'
        + `<g class="fsg-btn-rack" data-act="detc_down" role="button" tabindex="0" transform="translate(${X + 76} ${Y + 222})">`
        + '<rect x="-36" y="-9" width="72" height="18" rx="3"/><text y="4" text-anchor="middle">◂ POS −1</text></g>'
        + `<g class="fsg-btn-rack" data-act="detc_up" role="button" tabindex="0" transform="translate(${X + 204} ${Y + 222})">`
        + '<rect x="-36" y="-9" width="72" height="18" rx="3"/><text y="4" text-anchor="middle">POS +1 ▸</text></g>'
        + lockCyl(X + 312, Y + 118, 'ld', 'L-D', 'DETC HANDLE (K2)')
        // spare key on its hook (training hazard)
        + `<g class="xf-spare" data-act="spare" role="button" tabindex="0" transform="translate(${X + 312} ${Y + 196})">`
        + '<rect x="-42" y="-16" width="96" height="40" fill="transparent"/>'
        + '<circle cx="-30" cy="-6" r="3" class="xf-hook"/><path d="M-30 -3 L-30 4" class="xf-hook-wire"/>'
        + `<g transform="translate(-30 12)">${keyIcon('SPARE', 'xf-key-spare')}</g>`
        + '<text x="14" y="0" class="fsg-tiny">SPARE DETC</text><text x="14" y="10" class="fsg-tiny">KEY (HOOK)</text>'
        + '<title>A spare DETC key should be under supervisory control, not on a hook: using it defeats the key interlock.</title></g>';
}

function keyPanel() {
    const X = 510, Y = 334;
    return door(X, Y, 420, 150, 'fsg-door-upper')
        + `<text x="${X + 26}" y="${Y + 24}" class="fsg-label">KEY INTERLOCK (TRAPPED KEY, MODEL)</text>`
        + lockCyl(X + 90, Y + 72, 'lu', 'L-U', '52-U (K1)')
        + `<path d="M${X + 140} ${Y + 72} L${X + 196} ${Y + 72}" class="xf-chain"/><text x="${X + 168}" y="${Y + 66}" class="fsg-tiny" text-anchor="middle">K1</text>`
        + lockCyl(X + 240, Y + 72, 'lt', 'L-T', '52-T (K1→K2)')
        + `<path d="M${X + 290} ${Y + 72} L${X + 330} ${Y + 72}" class="xf-chain"/><text x="${X + 310}" y="${Y + 66}" class="fsg-tiny" text-anchor="middle">K2</text>`
        + `<text x="${X + 336}" y="${Y + 76}" class="fsg-tiny">→ L-D</text>`
        + `<g transform="translate(${X + 352} ${Y + 108})"><rect x="-26" y="-22" width="76" height="46" rx="3" class="xf-tray"/>`
        + '<text x="12" y="-10" class="fsg-tiny" text-anchor="middle">IN HAND</text>'
        + `<g class="xf-hand" data-hand="k1" transform="translate(-14 6)">${keyIcon('K1')}</g>`
        + `<g class="xf-hand" data-hand="k2" transform="translate(22 6)">${keyIcon('K2')}</g></g>`;
}

function primaryPanel() {
    const X = 510, Y = 498;
    return door(X, Y, 420, 172, 'fsg-door-upper')
        + `<text x="${X + 26}" y="${Y + 24}" class="fsg-label">52-T PRIMARY CIRCUIT SWITCHER · 27.5 kV</text>`
        + `<g transform="translate(${X + 70} ${Y + 66})"><rect x="-38" y="-18" width="76" height="36" rx="2" class="fsg-window"/>`
        + '<g class="fsg-flag"><rect x="-34" y="-14" width="68" height="28" class="fsg-flag-face xf-52t-flag"/>'
        + '<text y="5.5" class="fsg-flag-txt" data-txt="t52" text-anchor="middle"></text></g></g>'
        + led(X + 150, Y + 66, 'red', 'CLOSED', 't_closed')
        + led(X + 196, Y + 66, 'green', 'OPEN', 't_open')
        + `<g class="fsg-pb" transform="translate(${X + 262} ${Y + 66})"><rect x="-26" y="-22" width="52" height="44" rx="4" class="fsg-pb-escutcheon"/>`
        + '<g class="fsg-pb-cap" data-act="t_close" role="button" tabindex="0"><circle r="16" class="fsg-pb-ring"/><circle r="12.5" class="fsg-pb-face fsg-pb-close"/>'
        + '<text y="5" class="fsg-pb-glyph" text-anchor="middle">I</text></g></g>'
        + `<g class="fsg-pb" transform="translate(${X + 328} ${Y + 66})"><rect x="-26" y="-22" width="52" height="44" rx="4" class="fsg-pb-escutcheon"/>`
        + '<g class="fsg-pb-cap" data-act="t_open" role="button" tabindex="0"><circle r="16" class="fsg-pb-ring"/><circle r="12.5" class="fsg-pb-face fsg-pb-open"/>'
        + '<text y="5" class="fsg-pb-glyph" text-anchor="middle">O</text></g></g>'
        + `<g transform="translate(${X + 26} ${Y + 100})"><rect width="368" height="58" rx="3" class="xf-lcd"/>`
        + '<text x="10" y="17" class="xf-lcd-line" data-txt="l1"></text>'
        + '<text x="10" y="33" class="xf-lcd-line" data-txt="l2"></text>'
        + '<text x="10" y="49" class="xf-lcd-line" data-txt="l3"></text></g>';
}

/** Static SVG of the transformer field view for one path. */
export function xfmrSvg(path) {
    const P = e(String(path || 'a').toUpperCase());
    const frame = '<rect x="20" y="20" width="940" height="672" rx="4" class="fsg-frame"/>'
        + '<rect x="20" y="20" width="940" height="52" rx="4" class="fsg-topcap"/>'
        + `<text x="44" y="44" class="fsg-head">UTILITY TRANSFORMER · PATH ${P}</text>`
        + '<text x="44" y="61" class="fsg-tiny fsg-light">27.5 kV Δ / 13.8 kV Y SOLIDLY GROUNDED · 60 Hz · SEALED TANK · SIMULATED EQUIPMENT</text>'
        + '<line x1="490" y1="76" x2="490" y2="688" class="fsg-split"/>';
    return `<svg class="fsg-svg xf-svg" viewBox="0 0 980 712" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Utility transformer ${P} field view">`
        + fsgDefs() + `<g filter="url(#fsg-powder)">${frame}`
        + `<g class="fsg-section xf-section" data-section="XFMR">${marshallingBox()}${detcPanel()}${keyPanel()}${primaryPanel()}</g>`
        + '</g></svg>';
}

function segTone(c, alarm, trip) {
    if (c >= trip) return 'r';
    if (c >= alarm) return 'a';
    return 'g';
}

function setText(root, key, text) {
    const el = root.querySelector(`[data-txt="${key}"]`);
    if (el) el.textContent = text;
}

/** Write the transformer snapshot into a mounted view. */
export function applyXfmrState(root, t, path = '') {
    if (!root || !t) return;
    const sec = root.querySelector('[data-section="XFMR"]');
    if (!sec) return;
    const sp = t.setpoints || {};
    const attrs = {
        'data-86': t.lockout_86t, 'data-63': t.flag_63, 'data-87': t.flag_87t,
        'data-energized': t.energized, 'data-primary': t.primary_closed,
        'data-detc-locked': t.detc_locked, 'data-spare': t.spare_key_available,
        'data-damaged': t.damaged, 'data-fan1': t.fan1, 'data-fan2': t.fan2,
        'data-k1': t.key_k1, 'data-k2': t.key_k2, 'data-fan': t.fan_mode,
        'data-unlocked-by': t.detc_unlocked_by || '',
    };
    for (const [k, v] of Object.entries(attrs)) {
        sec.setAttribute(k, typeof v === 'boolean' ? (v ? '1' : '0') : String(v ?? ''));
    }
    setText(sec, 'np', `XFMR-${String(path || t.id || '').replace('xfmr_', '').toUpperCase()}`);
    setText(sec, 'oil', `${Number(t.top_oil_c).toFixed(1)}°C`);
    setText(sec, 'wdg', `${Number(t.winding_c).toFixed(1)}°C`);
    setText(sec, 'timescale', `MODEL · TIME ×${t.thermal_time_scale}`);
    setText(sec, 'stage', `${t.cooling_stage} · ${t.rating_mva} MVA`);
    setText(sec, 'tap', `POS ${t.tap} · ${Number(t.tap_pct) > 0 ? '+' : ''}${t.tap_pct} %`);
    setText(sec, 'level', `${Math.round(t.liquid_level_pct)} %`);
    setText(sec, 'n2', `${Number(t.nitrogen_psig).toFixed(1)}`);
    setText(sec, 'ied', t.flag_87t ? '87T TRIP' : '87T OK');
    setText(sec, 't52', t.primary_closed ? 'I  CLOSED' : 'O  OPEN');
    setText(sec, 'l1', `UTILITY ${Number(t.grid_kv).toFixed(2)} kV ${t.grid_ok ? '' : '· LOST'}`);
    setText(sec, 'l2', `13.8 kV SIDE ${Number(t.secondary_kv).toFixed(3)} kV · ${t.energized ? 'ENERGIZED' : 'DE-ENERGIZED'}`);
    setText(sec, 'l3', t.damaged ? 'INTERNAL FAULT · OUT OF SERVICE · TESTS REQUIRED'
        : `LOAD ${Number(t.load_mva).toFixed(2)} MVA · ${t.load_pct} % OF ${t.cooling_stage}`);
    for (const [key, val] of [['oil', t.top_oil_c], ['wdg', t.winding_c]]) {
        const alarm = key === 'oil' ? sp.oil_alarm_c : sp.winding_alarm_c;
        const trip = key === 'oil' ? sp.oil_trip_c : sp.winding_trip_c;
        sec.querySelectorAll(`[data-bar="${key}"] .xf-seg`).forEach((s) => {
            const c = Number(s.getAttribute('data-i')) * SEG_C;
            s.setAttribute('data-lit', c <= Number(val) ? segTone(c, alarm, trip) : '');
        });
        const marks = sec.querySelector(`[data-marks="${key}"]`);
        if (marks && !marks.childNodes.length && alarm != null) {
            marks.innerHTML = [[alarm, 'a'], [trip, 'r']].map(([c, tone]) =>
                `<path d="M${(c / SEG_C) * 8} -4 l-3 -4 h6 z" class="xf-mark" data-tone="${tone}"/>`).join('');
        }
    }
    const leds = { fan1: t.fan1, fan2: t.fan2, alarm: t.oil_alarm || t.winding_alarm,
        trip: t.lockout_86t, t_closed: t.primary_closed, t_open: !t.primary_closed };
    for (const [k, on] of Object.entries(leds)) {
        const g = sec.querySelector(`[data-led="${k}"]`);
        if (g) g.setAttribute('data-on', on ? '1' : '0');
    }
    const n = (key, deg) => {
        const g = sec.querySelector(`[data-needle="${key}"]`);
        if (g) g.style.transform = `rotate(${deg}deg)`;
    };
    n('level', -120 + 240 * Math.max(0, Math.min(100, Number(t.liquid_level_pct))) / 100);
    n('n2', -120 + 240 * (Math.max(-10, Math.min(10, Number(t.nitrogen_psig))) + 10) / 20);
    const handle = sec.querySelector('.xf-detc-handle');
    if (handle) handle.style.transform = `rotate(${DETC_ANGLE[(Number(t.tap) || 3) - 1]}deg)`;
    const knob = sec.querySelector('.xf-fan-knob');
    if (knob) knob.style.transform = `rotate(${FAN_ANGLE[t.fan_mode] ?? 0}deg)`;
    // keys in their locks / in hand
    const inLock = { lu: t.key_k1 === 'L-U', lt: t.key_k1 === 'L-T' || t.key_k2 === 'L-T',
        ld: t.key_k2 === 'L-D' || t.detc_unlocked_by === 'SPARE' };
    for (const [id, on] of Object.entries(inLock)) {
        const g = sec.querySelector(`[data-lock="${id}"]`);
        if (g) g.setAttribute('data-key', on ? '1' : '0');
    }
    const turned = { lu: t.key_k1 !== 'L-U', lt: t.key_k1 === 'L-T', ld: !t.detc_locked };
    for (const [id, on] of Object.entries(turned)) {
        const g = sec.querySelector(`[data-lock="${id}"]`);
        if (g) g.setAttribute('data-turned', on ? '1' : '0');
    }
    for (const k of ['k1', 'k2']) {
        const g = sec.querySelector(`[data-hand="${k}"]`);
        if (g) g.setAttribute('data-on', t[`key_${k}`] === 'HAND' ? '1' : '0');
    }
}

/** Map a click to {action} (server action name) or null. */
export function resolveXfmrClick(target, t) {
    const el = target && target.closest ? target.closest('[data-act]') : null;
    if (!el || !t) return null;
    switch (el.getAttribute('data-act')) {
    case 'lu': return { action: t.key_k1 === 'HAND' ? 'KEY_UNLOCK_52U' : 'KEY_LOCK_52U', kind: 'key' };
    case 'lt': return { action: t.key_k1 === 'L-T' ? 'KEY_UNLOCK_52T' : 'KEY_LOCK_52T', kind: 'key' };
    case 'ld': return { action: t.detc_locked ? 'DETC_UNLOCK' : 'DETC_LOCK', kind: 'key' };
    case 'spare': return { action: 'DETC_SPARE_KEY', kind: 'key' };
    case 'detc_up': return { action: 'DETC_POS_UP', kind: 'detc' };
    case 'detc_down': return { action: 'DETC_POS_DOWN', kind: 'detc' };
    case 't_close': return { action: 'CLOSE_52T', kind: 'breaker' };
    case 't_open': return { action: 'OPEN_52T', kind: 'breaker' };
    case 'r63': return { action: 'RESET_63', kind: 'button' };
    case 'r87': return { action: 'RESET_87T', kind: 'button' };
    case '86t': return { action: 'RESET_86T', kind: 'button' };
    case 'fans_off': return { action: 'FANS_OFF', kind: 'selector' };
    case 'fans_auto': return { action: 'FANS_AUTO', kind: 'selector' };
    case 'fans_on': return { action: 'FANS_ON', kind: 'selector' };
    default: return null;
    }
}

/** True when a plant event belongs to the transformer field view. */
export function isXfmrEvent(ev) {
    return ev.equipment === 'xfmr' || String(ev.command || '').endsWith('@XFMR')
        || XFMR_EVENT_KINDS.includes(ev.event)
        || (ev.event === 'protection_trip' && (ev.relay === '86T' || ev.breaker === '52-T'));
}

/** One log line for a transformer event. */
export function xfmrEventText(ev) {
    if (ev.event === 'refused') return `REFUSED ${ev.command}: ${ev.detail || ''}`;
    if (ev.event === 'command') {
        const pos = ev.tap_from !== ev.tap ? `POS ${ev.tap_from}→${ev.tap}` : `POS ${ev.tap}`;
        if (ev.outcome === 'internal_fault') return `${ev.command} · MOVED ENERGIZED → INTERNAL FAULT`;
        return `${ev.command} · ${pos} · ${ev.energized ? 'ENERGIZED' : 'DE-ENERGIZED'}`;
    }
    return `${String(ev.event).replace(/_/g, ' ').toUpperCase()} ${ev.relay || ''} ${ev.detail || ev.cause || ''}`.trim();
}

