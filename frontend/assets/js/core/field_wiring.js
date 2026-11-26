/**
 * L5 (2026-11-26): field view of the control compartment of the MV
 * transfer lineup of one path (Layer 2, equipment look; ADR-014): the
 * draw-out PT secondary fuse holders F-1A (utility sensing) and F-1B
 * (generator bus sensing), terminal block TB-1 and a true-RMS
 * multimeter with a rotary selector (OFF, V AC, V DC, resistance with
 * continuity beep) and its test leads.
 *
 * Same contract as the other field views: wiringSvg() once per open,
 * applyWiringState() from GET /api/devices (transfer controller ->
 * wiring), every action is a server call
 * (POST /api/devices/{mvtc}/wiring). The fuse condition is never drawn:
 * it is found with the meter. Simulated equipment, model readings.
 */
import { escapeHTML } from './sanitize.js';
import { door, fsgDefs } from './field_switchgear.js';

const e = (v) => escapeHTML(v === null || v === undefined ? '' : String(v));
const TB_X = 60, TB_Y = 300, ROW = 31;
export const TB_ROWS = [
    ['F1A_LINE', 'F-1A LINE', 'N', 'utility PT secondary'],
    ['F1A_LOAD', 'F-1A LOAD', 'N', 'to controller / 27'],
    ['F1A_FUSE', 'F-1A LINE', 'F-1A LOAD', 'across the fuse'],
    ['F1B_LINE', 'F-1B LINE', 'N', 'gen bus PT secondary'],
    ['F1B_LOAD', 'F-1B LOAD', 'N', 'to controller'],
    ['F1B_FUSE', 'F-1B LINE', 'F-1B LOAD', 'across the fuse'],
    ['P1_N1', 'P1', 'N1', 'station battery 125 V DC'],
    ['T73_74', '73', '74', 'engine start contact'],
    ['CC_52U', '52-U 52CC', 'N1', 'close circuit'],
    ['TC_52U', '52-U 52TC', 'N1', 'trip circuit'],
    ['CC_52GM', '52-GM 52CC', 'N1', 'close circuit'],
    ['TC_52GM', '52-GM 52TC', 'N1', 'trip circuit'],
];
const DIAL = { OFF: -60, VAC: -20, VDC: 20, OHM: 60 };
const DIAL_LBL = { OFF: 'OFF', VAC: 'V~', VDC: 'V⎓', OHM: 'Ω ·)))' };

function fuseHolder(key, label, sub, x) {
    return `<g class="xw-fuse" data-fuse="${key}" transform="translate(${x} 150)">`
        + '<rect x="-60" y="0" width="120" height="110" rx="4" class="xw-fuse-base"/>'
        + `<text y="16" class="fsg-label xu-light" text-anchor="middle">${label}</text>`
        + `<text y="28" class="fsg-tiny xu-light" text-anchor="middle">${sub}</text>`
        + `<g class="xw-holder" data-act="fuse" data-fuse="${key}" role="button" tabindex="0">`
        + '<rect x="-34" y="38" width="68" height="40" rx="5" class="xw-holder-body"/>'
        + '<rect x="-22" y="50" width="44" height="16" rx="3" class="xw-cartridge"/>'
        + '<rect x="-10" y="78" width="20" height="10" rx="2" class="xw-grip"/></g>'
        + `<g class="xb-reset xw-replace" data-act="replace" data-fuse="${key}" role="button" tabindex="0" transform="translate(0 100)">`
        + '<rect x="-36" y="-8" width="72" height="16" rx="2"/><text y="4" text-anchor="middle">NEW FUSE</text></g></g>';
}

function terminalBlock() {
    let rows = '';
    TB_ROWS.forEach(([pt, a, b, note], i) => {
        const y = TB_Y + 30 + i * ROW;
        rows += `<g class="xw-pt" data-act="point" data-point="${pt}" role="button" tabindex="0" transform="translate(${TB_X} ${y})">`
            + '<rect x="0" y="-12" width="460" height="26" rx="2" class="xw-pt-row"/>'
            + '<circle cx="18" cy="1" r="6" class="xw-screw"/><circle cx="168" cy="1" r="6" class="xw-screw"/>'
            + `<text x="32" y="5" class="xw-pt-t">${a}</text><text x="182" y="5" class="xw-pt-t">${b}</text>`
            + `<text x="318" y="5" class="fsg-tiny">${note}</text></g>`;
    });
    return `<text x="${TB_X}" y="${TB_Y + 6}" class="fsg-label">TB-1 · TEST POINTS (CLICK TO PLACE THE LEADS)</text>` + rows;
}

function meter() {
    const X = 600, Y = 110;
    let dial = '';
    for (const [m, deg] of Object.entries(DIAL)) {
        const r = 86, a = (deg - 90) * Math.PI / 180;
        const x = Math.cos(a) * r, y = Math.sin(a) * r;
        dial += `<g class="xw-dialpos" data-act="mode" data-mode="${m}" role="button" tabindex="0" transform="translate(${x.toFixed(1)} ${y.toFixed(1)})">`
            + `<rect x="-26" y="-12" width="52" height="24" fill="transparent"/><text y="4" text-anchor="middle">${DIAL_LBL[m]}</text></g>`;
    }
    return `<g class="xw-meter" transform="translate(${X} ${Y})">`
        + '<rect x="0" y="0" width="320" height="520" rx="34" class="xw-holster"/>'
        + '<rect x="18" y="18" width="284" height="484" rx="22" class="xw-meter-body"/>'
        + '<rect x="40" y="42" width="240" height="110" rx="6" class="xw-lcd"/>'
        + '<text x="270" y="100" class="xw-lcd-big" text-anchor="end" data-txt="disp">OFF</text>'
        + '<text x="52" y="66" class="xw-lcd-small" data-txt="mode"></text>'
        + '<text x="52" y="140" class="xw-lcd-small" data-txt="pt"></text>'
        + '<text x="268" y="66" class="xw-lcd-small" text-anchor="end" data-txt="beep"></text>'
        + '<text x="160" y="176" class="fsg-tiny xw-light" text-anchor="middle">TRUE-RMS MULTIMETER (MODEL)</text>'
        + '<g transform="translate(160 300)"><circle r="62" class="xw-dial-ring"/>'
        + '<g class="xw-knob"><circle r="44" class="fsg-sel-body"/><rect x="-6" y="-44" width="12" height="40" rx="4" class="xw-pointer"/></g>'
        + dial + '</g>'
        + '<g transform="translate(0 440)">'
        + '<circle cx="90" r="14" class="xw-jack xw-jack-com"/><text x="90" y="30" class="fsg-tiny xw-light" text-anchor="middle">COM</text>'
        + '<circle cx="230" r="14" class="xw-jack xw-jack-v"/><text x="230" y="30" class="fsg-tiny xw-light" text-anchor="middle">V Ω</text></g>'
        + '<text x="160" y="196" class="xw-warn" text-anchor="middle" data-txt="warn"></text></g>';
}

/** Static SVG of the MV control compartment field view for one path. */
export function wiringSvg(path) {
    const P = e(String(path || 'a').toUpperCase());
    const frame = '<rect x="20" y="20" width="940" height="672" rx="4" class="fsg-frame"/>'
        + '<rect x="20" y="20" width="940" height="52" rx="4" class="fsg-topcap"/>'
        + `<text x="44" y="44" class="fsg-head">MV TRANSFER ${P} · CONTROL COMPARTMENT</text>`
        + '<text x="44" y="61" class="fsg-tiny fsg-light">PT SECONDARY FUSES · TB-1 · 125 V DC CONTROL · SIMULATED EQUIPMENT · MODEL READINGS</text>';
    return `<svg class="fsg-svg xw-svg" viewBox="0 0 980 712" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="MV control compartment, path ${P}">`
        + fsgDefs() + `<g filter="url(#fsg-powder)">${frame}`
        + '<g class="fsg-section xw-section" data-section="WIRING">'
        + door(40, 84, 540, 604, 'fsg-door-upper')
        + '<text x="62" y="112" class="fsg-label">CPT / PT SECONDARY FUSE BLOCK</text>'
        + '<text x="62" y="126" class="fsg-tiny">DRAW-OUT HOLDERS · PULL BEFORE TESTING THE FUSE ON RESISTANCE</text>'
        + fuseHolder('F1A', 'F-1A', 'UTILITY SENSING', 170) + fuseHolder('F1B', 'F-1B', 'GEN BUS SENSING', 330)
        + terminalBlock() + meter()
        + '<path class="xw-lead xw-lead-red" data-lead="red" d=""/><path class="xw-lead xw-lead-black" data-lead="black" d=""/>'
        + '</g></g></svg>';
}

function setText(root, key, text) {
    const el = root.querySelector(`[data-txt="${key}"]`);
    if (el) el.textContent = text;
}

/** Write the control wiring of a transfer controller into the view. */
export function applyWiringState(root, wiring) {
    if (!root || !wiring) return;
    const sec = root.querySelector('[data-section="WIRING"]');
    if (!sec) return;
    const mode = wiring.meter || 'OFF';
    sec.setAttribute('data-mode', mode);
    const knob = sec.querySelector('.xw-knob');
    if (knob) knob.style.transform = `rotate(${DIAL[mode] || 0}deg)`;
    sec.querySelectorAll('.xw-dialpos').forEach((g) => g.setAttribute('data-on', g.getAttribute('data-mode') === mode ? '1' : '0'));
    for (const [k, f] of Object.entries(wiring.fuses || {})) {
        const g = sec.querySelector(`.xw-fuse[data-fuse="${k.replace('-', '')}"]`);
        if (g) g.setAttribute('data-pulled', f.pulled ? '1' : '0');
    }
    const last = (wiring.readings || [])[wiring.readings.length - 1];
    const off = mode === 'OFF';
    setText(sec, 'mode', off ? '' : DIAL_LBL[mode]);
    if (off || !last) {
        setText(sec, 'disp', off ? 'OFF' : '----');
        setText(sec, 'pt', '');
        setText(sec, 'beep', '');
        setText(sec, 'warn', '');
    } else {
        setText(sec, 'disp', last.display);
        setText(sec, 'pt', String(last.label || '').toUpperCase().slice(0, 34));
        setText(sec, 'beep', last.beep ? '·))) BEEP' : '');
        setText(sec, 'warn', last.warning ? 'INVALID: RESISTANCE ON A LIVE CIRCUIT' : '');
    }
    sec.querySelectorAll('.xw-pt').forEach((g) => g.setAttribute('data-on', last && g.getAttribute('data-point') === last.point ? '1' : '0'));
    // Leads from the jacks (V/Ω red, COM black) to the probed row.
    const idx = last ? TB_ROWS.findIndex((r) => r[0] === last.point) : -1;
    const red = sec.querySelector('[data-lead="red"]');
    const black = sec.querySelector('[data-lead="black"]');
    if (red && black) {
        if (idx < 0 || off) {
            red.setAttribute('d', 'M830 550 C 860 600, 880 640, 900 660');
            black.setAttribute('d', 'M690 550 C 670 600, 650 640, 630 660');
        } else {
            const y = TB_Y + 31 + idx * ROW;
            red.setAttribute('d', `M830 550 C 760 620, 300 ${y + 60}, ${TB_X + 18} ${y}`);
            black.setAttribute('d', `M690 550 C 640 610, 400 ${y + 70}, ${TB_X + 168} ${y}`);
        }
    }
}

/** Map a click to {action} or null, given the wiring state. */
export function resolveWiringClick(target, wiring) {
    const el = target && target.closest ? target.closest('[data-act]') : null;
    if (!el || !wiring) return null;
    const act = el.getAttribute('data-act');
    if (act === 'mode') return { action: `METER_${el.getAttribute('data-mode')}`, kind: 'selector' };
    if (act === 'point') return { action: `MEASURE_${el.getAttribute('data-point')}`, kind: 'probe' };
    const key = el.getAttribute('data-fuse');
    const f = (wiring.fuses || {})[key === 'F1A' ? 'F-1A' : 'F-1B'] || {};
    if (act === 'fuse') return { action: `${f.pulled ? 'INSERT' : 'PULL'}_${key}`, kind: 'tool' };
    if (act === 'replace') return { action: `REPLACE_${key}`, kind: 'tool' };
    return null;
}

export function isWiringEvent(ev) {
    return ev.equipment === 'wiring'
        || (ev.event === 'protection_trip' && ev.relay === '27')
        || /^(PULL|INSERT|REPLACE|METER|MEASURE)_/.test(String(ev.command || ''));
}

export function wiringEventText(ev) {
    if (ev.event === 'refused') return `REFUSED ${ev.command}: ${ev.detail || ''}`;
    const r = ev.reading;
    if (ev.event === 'inspection' && r && r.point) return `METER ${r.point} · ${r.display}${r.warning ? ' · INVALID' : ''}`;
    if (ev.event === 'inspection' && r) return `METER SELECTOR ${r.meter}`;
    if (ev.event === 'command') return `${String(ev.action || ev.command).replace(/_/g, ' ')} · path ${ev.transfer_state || ''}`;
    if (ev.event === 'protection_trip') return `52-U TRIPPED · ANSI 27 ${ev.detail || ''}`;
    return `${String(ev.event).replace(/_/g, ' ').toUpperCase()} ${ev.detail || ''}`.trim();
}
