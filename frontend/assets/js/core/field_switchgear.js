/**
 * L1 (2026-11-15): field view of the 13.8 kV switchgear of one path,
 * the two draw-out main breakers 52-U and 52-GM (Layer 2: equipment
 * as it looks at the line-up, not the ISA-101 control-room mimic).
 *
 * The drawing is built ONCE per open (fieldLineupSvg) with data hooks;
 * applyFieldState() only writes attributes and texts from the plant
 * snapshot, so CSS transitions (racking pointer, 86 handle, flags,
 * crank) animate instead of being re-rendered away. Every action is a
 * backend call (POST /api/devices/{id}/field): the server owns the
 * interlocks, the drawing never decides what is permitted.
 *
 * Honest scope: simulated equipment. Ratings marked (model) are
 * assumptions; no arc-flash study exists and the label says so.
 */
import { escapeHTML } from './sanitize.js';

export const FIELD_BREAKERS = Object.freeze(['52-U', '52-GM']);
const SEC_W = 420;
const SEC_X = { '52-U': 40, '52-GM': 520 };
const TOP_Y = 84;      // upper (relay / control) door
const LOW_Y = 352;     // lower (breaker) door
const RACK_X = { CONNECTED: 0, TEST: 62, DISCONNECTED: 124 };

const e = (v) => escapeHTML(v === null || v === undefined ? '' : String(v));

function screws(x, y, w, h, inset = 12) {
    return [[x + inset, y + inset], [x + w - inset, y + inset], [x + inset, y + h - inset], [x + w - inset, y + h - inset]]
        .map(([cx, cy]) => `<g class="fsg-screw" transform="translate(${cx} ${cy})">`
            + '<circle r="5.2" class="fsg-screw-head"/>'
            + '<path d="M-3 -1.7 L0 -3.4 L3 -1.7 L3 1.7 L0 3.4 L-3 1.7 Z" class="fsg-screw-hex"/></g>').join('');
}

function door(x, y, w, h, cls) {
    return `<rect class="fsg-door ${cls}" x="${x}" y="${y}" width="${w}" height="${h}" rx="3"/>`
        + `<rect class="fsg-door-sheen" x="${x}" y="${y}" width="${w}" height="${h}" rx="3"/>`
        + `<rect class="fsg-hinge" x="${x - 5}" y="${y + 26}" width="7" height="34" rx="1.5"/>`
        + `<rect class="fsg-hinge" x="${x - 5}" y="${y + h - 60}" width="7" height="34" rx="1.5"/>`
        + `<g class="fsg-handle" transform="translate(${x + w - 22} ${y + h / 2})">`
        + '<rect x="-6" y="-28" width="12" height="56" rx="5"/><circle r="4.5" class="fsg-handle-boss"/></g>'
        + screws(x, y, w, h);
}

function led(cx, cy, colour, label, key) {
    return `<g class="fsg-led" data-led="${key}" data-colour="${colour}" transform="translate(${cx} ${cy})">`
        + '<circle r="15" class="fsg-led-bezel"/><circle r="11" class="fsg-led-lens"/>'
        + '<circle r="7" class="fsg-led-fresnel"/><circle r="3.5" class="fsg-led-fresnel"/>'
        + '<ellipse cx="-3.5" cy="-4" rx="3.5" ry="2" class="fsg-led-glint"/>'
        + `<text y="29" class="fsg-tiny" text-anchor="middle">${label}</text></g>`;
}

function upperDoor(brk) {
    const X = SEC_X[brk];
    const title = brk === '52-U' ? 'UTILITY INCOMER' : 'GENERATOR MAIN';
    const fromTxt = brk === '52-U' ? 'FROM XFMR 27.5/13.8 kV' : 'FROM 13.8 kV GEN BUS';
    return door(X, TOP_Y, SEC_W, 256, 'fsg-door-upper')
        // engraved nameplate (black phenolic, white core)
        + `<g class="fsg-nameplate" transform="translate(${X + 30} ${TOP_Y + 22})">`
        + '<rect width="214" height="58" rx="2" class="fsg-np-plate"/>'
        + '<circle cx="8" cy="8" r="2.2" class="fsg-rivet"/><circle cx="206" cy="8" r="2.2" class="fsg-rivet"/>'
        + '<circle cx="8" cy="50" r="2.2" class="fsg-rivet"/><circle cx="206" cy="50" r="2.2" class="fsg-rivet"/>'
        + `<text x="107" y="27" class="fsg-np-big" text-anchor="middle">${brk}</text>`
        + `<text x="107" y="41" class="fsg-np-small" text-anchor="middle">${title}</text>`
        + `<text x="107" y="52" class="fsg-np-small" text-anchor="middle">${fromTxt}</text></g>`
        // arc-flash label (honest: no study)
        + `<g class="fsg-afl" transform="translate(${X + 262} ${TOP_Y + 18})">`
        + '<rect width="134" height="98" rx="2" class="fsg-afl-body"/>'
        + '<rect width="134" height="22" rx="2" class="fsg-afl-head"/>'
        + '<path d="M10 17 L17 4 L24 17 Z" class="fsg-afl-tri"/><text x="17" y="15.5" class="fsg-afl-bang" text-anchor="middle">!</text>'
        + '<text x="78" y="15" class="fsg-afl-head-txt" text-anchor="middle">WARNING</text>'
        + '<text x="67" y="35" class="fsg-afl-txt" text-anchor="middle">ARC FLASH AND SHOCK</text>'
        + '<text x="67" y="46" class="fsg-afl-txt" text-anchor="middle">HAZARD</text>'
        + '<text x="67" y="61" class="fsg-afl-strong" text-anchor="middle">ARC FLASH STUDY</text>'
        + '<text x="67" y="71" class="fsg-afl-strong" text-anchor="middle">NOT PERFORMED</text>'
        + '<text x="67" y="84" class="fsg-afl-txt" text-anchor="middle">13.8 kV AC · SIMULATED</text>'
        + '<text x="67" y="93" class="fsg-afl-txt" text-anchor="middle">NFPA 70E / CSA Z462</text>'
        + '<title>No incident energy, arc-flash boundary or PPE category exists for this simulated equipment. A real label comes from an engineering study (NFPA 70E 130.5, CSA Z462).</title></g>'
        // pilot lights
        + led(X + 46, TOP_Y + 112, 'red', 'CLOSED', 'closed')
        + led(X + 92, TOP_Y + 112, 'green', 'OPEN', 'open')
        + led(X + 138, TOP_Y + 112, 'amber', 'SPRING', 'spring')
        + led(X + 184, TOP_Y + 112, 'amber', '86 TRIP', 'trip86')
        + led(X + 230, TOP_Y + 112, 'white', '125 VDC', 'ctrl')
        // 86 lockout relay (pistol-grip handle + target)
        + `<g class="fsg-86" data-act="86" data-brk="${brk}" transform="translate(${X + 96} ${TOP_Y + 190})" role="button" tabindex="0">`
        + '<circle r="44" class="fsg-86-bezel"/><circle r="36" class="fsg-86-face"/>'
        + '<text x="-40" y="-36" class="fsg-tiny" text-anchor="end">RESET</text>'
        + '<text x="40" y="-36" class="fsg-tiny" text-anchor="start">TRIP</text>'
        + '<rect x="-11" y="13" width="22" height="11" rx="1.5" class="fsg-86-target"/>'
        + '<g class="fsg-86-handle"><path d="M-6 6 L-6 -30 Q0 -40 6 -30 L6 6 Q0 12 -6 6 Z" class="fsg-86-grip"/>'
        + '<circle r="7" class="fsg-86-hub"/></g>'
        + '<text y="57" class="fsg-label" text-anchor="middle">86 LOCKOUT</text>'
        + '<title>ANSI 86 lockout relay: TRIP opens the breaker and the close circuit; RESET by hand.</title></g>'
        // spring-charging motor selector
        + `<g class="fsg-sel" data-act="motor" data-brk="${brk}" transform="translate(${X + 226} ${TOP_Y + 196})" role="button" tabindex="0">`
        + '<circle r="30" class="fsg-sel-plate"/>'
        + '<text x="-24" y="-18" class="fsg-tiny" text-anchor="middle">OFF</text>'
        + '<text x="24" y="-18" class="fsg-tiny" text-anchor="middle">ON</text>'
        + '<g class="fsg-sel-knob"><circle r="17" class="fsg-sel-body"/>'
        + '<path d="M-4 -16 L4 -16 L3 6 L-3 6 Z" class="fsg-sel-bar"/><circle r="3" cy="-11" class="fsg-sel-dot"/></g>'
        + '<text y="46" class="fsg-label" text-anchor="middle">SPRING MOTOR</text></g>'
        // charging countdown
        + `<text x="${X + 330}" y="${TOP_Y + 196}" class="fsg-lcd-txt" data-txt="charging" text-anchor="middle"></text>`
        + `<text x="${X + 330}" y="${TOP_Y + 212}" class="fsg-tiny" text-anchor="middle">CHARGE STATUS</text>`;
}

function lowerDoor(brk) {
    const X = SEC_X[brk];
    const W = SEC_W;
    const wx = X + 28, wy = LOW_Y + 18, ww = W - 76, wh = 196;
    return door(X, LOW_Y, W, 318, 'fsg-door-lower')
        // breaker compartment cut-out
        + `<rect class="fsg-cavity" x="${wx}" y="${wy}" width="${ww}" height="${wh}" rx="2"/>`
        + `<g class="fsg-truck" data-truck="${brk}">`
        + `<rect class="fsg-front" x="${wx + 14}" y="${wy + 12}" width="${ww - 28}" height="${wh - 24}" rx="3"/>`
        + `<text x="${wx + 28}" y="${wy + 30}" class="fsg-label fsg-dark">VCB · 15 kV CLASS (MODEL)</text>`
        // mechanical position flag
        + `<g transform="translate(${wx + 64} ${wy + 70})"><rect x="-38" y="-18" width="76" height="36" rx="2" class="fsg-window"/>`
        + `<g class="fsg-flag" data-flag="${brk}"><rect x="-34" y="-14" width="68" height="28" class="fsg-flag-face"/>`
        + '<text y="5.5" class="fsg-flag-txt" text-anchor="middle"></text></g>'
        + '<text y="32" class="fsg-tiny fsg-dark" text-anchor="middle">BREAKER</text></g>'
        // spring indicator
        + `<g transform="translate(${wx + 156} ${wy + 70})"><rect x="-38" y="-18" width="76" height="36" rx="2" class="fsg-window"/>`
        + `<g class="fsg-springflag" data-springflag="${brk}"><rect x="-34" y="-14" width="68" height="28" class="fsg-sflag-face"/>`
        + '<text y="4.5" class="fsg-sflag-txt" text-anchor="middle"></text></g>'
        + '<text y="32" class="fsg-tiny fsg-dark" text-anchor="middle">CLOSING SPRING</text></g>'
        // manual charging lever
        + `<g class="fsg-lever" data-act="pump" data-brk="${brk}" transform="translate(${wx + 262} ${wy + 104})" role="button" tabindex="0">`
        + '<rect x="-34" y="-66" width="68" height="104" fill="transparent"/>'
        + '<circle r="14" class="fsg-lever-hub"/>'
        + '<g class="fsg-lever-arm"><rect x="-5" y="-46" width="10" height="46" rx="4" class="fsg-lever-bar"/>'
        + '<rect x="-9" y="-58" width="18" height="18" rx="4" class="fsg-lever-grip"/></g>'
        + '<text y="32" class="fsg-tiny fsg-dark" text-anchor="middle">MANUAL CHARGE</text>'
        + '<text y="44" class="fsg-tiny fsg-dark" data-txt="pumps" text-anchor="middle"></text></g>'
        // push buttons under hinged clear covers
        + pushButton(brk, 'close', wx + 70, wy + 146, 'I', 'PUSH TO CLOSE')
        + pushButton(brk, 'open', wx + 170, wy + 146, 'O', 'PUSH TO OPEN')
        + '</g>'
        // racking: position indicator, port + crank, padlock hasp
        + `<g transform="translate(${X + 30} ${LOW_Y + 238})">`
        + '<rect width="164" height="30" rx="3" class="fsg-rack-slot"/>'
        + '<text x="20" y="45" class="fsg-tiny" text-anchor="middle">CONN</text>'
        + '<text x="82" y="45" class="fsg-tiny" text-anchor="middle">TEST</text>'
        + '<text x="144" y="45" class="fsg-tiny" text-anchor="middle">DISC</text>'
        + `<g class="fsg-rack-ptr" data-rackptr="${brk}"><path d="M20 4 L28 15 L20 26 L12 15 Z" class="fsg-rack-ptr-shape"/></g>`
        + '<text x="82" y="-6" class="fsg-label" text-anchor="middle">RACKING POSITION</text></g>'
        + `<g class="fsg-port" transform="translate(${X + 300} ${LOW_Y + 262})">`
        + '<circle r="26" class="fsg-port-ring"/><circle r="9" class="fsg-port-socket"/>'
        + `<g class="fsg-crank" data-crank="${brk}"><rect x="-4" y="-4" width="40" height="8" rx="3" class="fsg-crank-arm"/>`
        + '<circle cx="36" r="7" class="fsg-crank-knob"/></g>'
        + `<g class="fsg-hasp" data-act="lock" data-brk="${brk}" role="button" tabindex="0" transform="translate(-48 -6)">`
        + '<rect x="-12" y="-10" width="24" height="26" rx="3" class="fsg-hasp-plate"/><circle cy="2" r="4" class="fsg-hasp-hole"/>'
        + '<g class="fsg-padlock"><path d="M-7 -2 L-7 -10 Q0 -20 7 -10 L7 -2" class="fsg-shackle"/>'
        + '<rect x="-10" y="-3" width="20" height="17" rx="2.5" class="fsg-lock-body"/></g></g>'
        + `<g class="fsg-tag" data-tag="${brk}" transform="translate(-106 -6)">`
        + '<path d="M50 6 L58 4" class="fsg-tag-wire"/>'
        + '<rect width="50" height="58" rx="3" class="fsg-tag-body"/><rect width="50" height="15" rx="3" class="fsg-tag-head"/>'
        + '<circle cx="44" cy="7" r="2" class="fsg-tag-eyelet"/>'
        + '<text x="23" y="11" class="fsg-tag-head-txt" text-anchor="middle">DANGER</text>'
        + '<text x="25" y="27" class="fsg-tag-txt" text-anchor="middle">DO NOT</text>'
        + '<text x="25" y="37" class="fsg-tag-txt" text-anchor="middle">OPERATE</text>'
        + '<text x="25" y="51" class="fsg-tag-name" data-txt="lockname" text-anchor="middle"></text></g>'
        + '</g>'
        + `<g transform="translate(${X + 300} ${LOW_Y + 304})">`
        + `<g class="fsg-btn-rack" data-act="rack_in" data-brk="${brk}" role="button" tabindex="0" transform="translate(-14 0)">`
        + '<rect x="-30" y="-9" width="60" height="18" rx="3"/><text y="4" text-anchor="middle">◂ RACK IN</text></g>'
        + `<g class="fsg-btn-rack" data-act="rack_out" data-brk="${brk}" role="button" tabindex="0" transform="translate(52 0)">`
        + '<rect x="-30" y="-9" width="60" height="18" rx="3"/><text y="4" text-anchor="middle">RACK OUT ▸</text></g></g>';
}

function pushButton(brk, kind, x, y, glyph, label) {
    return `<g class="fsg-pb" data-pb="${kind}" data-brk="${brk}" transform="translate(${x} ${y})">`
        + '<rect x="-30" y="-24" width="60" height="48" rx="4" class="fsg-pb-escutcheon"/>'
        + `<g class="fsg-pb-cap" data-act="${kind}" data-brk="${brk}" role="button" tabindex="0">`
        + `<circle r="16" class="fsg-pb-ring"/><circle r="12.5" class="fsg-pb-face fsg-pb-${kind}"/>`
        + `<text y="5" class="fsg-pb-glyph" text-anchor="middle">${glyph}</text></g>`
        + `<g class="fsg-cover" data-act="cover" data-brk="${brk}" data-kind="${kind}" role="button" tabindex="0">`
        + '<rect x="-27" y="-22" width="54" height="44" rx="4" class="fsg-cover-glass"/>'
        + '<rect x="-27" y="-22" width="54" height="7" rx="3" class="fsg-cover-hinge"/></g>'
        + `<text y="36" class="fsg-tiny fsg-dark" text-anchor="middle">${label}</text></g>`;
}

/** Static SVG of the line-up for one path (built once per open). */
export function fieldLineupSvg(path) {
    const P = String(path || 'a').toUpperCase();
    const defs = '<defs>'
        + '<filter id="fsg-powder" x="0" y="0" width="100%" height="100%">'
        + '<feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="7" result="n"/>'
        + '<feColorMatrix in="n" type="matrix" values="0 0 0 0 0.5  0 0 0 0 0.5  0 0 0 0 0.5  0 0 0 0.07 0" result="g"/>'
        + '<feComposite in="g" in2="SourceGraphic" operator="in" result="m"/>'
        + '<feBlend in="SourceGraphic" in2="m" mode="multiply"/></filter>'
        + '<linearGradient id="fsg-steel" x1="0" y1="0" x2="1" y2="1">'
        + '<stop offset="0" stop-color="#b9c0c6"/><stop offset="0.55" stop-color="#a3abb2"/><stop offset="1" stop-color="#8d959c"/></linearGradient>'
        + '<linearGradient id="fsg-sheen" x1="0" y1="0" x2="0" y2="1">'
        + '<stop offset="0" stop-color="#fff" stop-opacity="0.18"/><stop offset="0.12" stop-color="#fff" stop-opacity="0"/>'
        + '<stop offset="0.9" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity="0.18"/></linearGradient>'
        + '<radialGradient id="fsg-lens-off" cx="0.4" cy="0.35" r="0.7"><stop offset="0" stop-color="#555"/><stop offset="1" stop-color="#1a1a1a"/></radialGradient>'
        + '<radialGradient id="fsg-knob" cx="0.35" cy="0.3" r="0.8"><stop offset="0" stop-color="#4a4f55"/><stop offset="1" stop-color="#0d0f11"/></radialGradient>'
        + '<linearGradient id="fsg-front" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#d4d8dc"/><stop offset="1" stop-color="#aeb4ba"/></linearGradient>'
        + '</defs>';
    const frame = '<rect x="20" y="20" width="940" height="672" rx="4" class="fsg-frame"/>'
        + '<rect x="20" y="20" width="940" height="52" rx="4" class="fsg-topcap"/>'
        + `<text x="44" y="44" class="fsg-head">13.8 kV SWITCHGEAR · PATH ${P}</text>`
        + '<text x="44" y="61" class="fsg-tiny fsg-light">3-PHASE 3-WIRE · 60 Hz · DRAW-OUT VACUUM BREAKERS · SIMULATED EQUIPMENT</text>'
        // LOCAL / REMOTE key switch for the transfer controller
        + '<g class="fsg-key" data-act="authority" role="button" tabindex="0" transform="translate(880 46)">'
        + '<rect x="-150" y="-26" width="200" height="52" fill="transparent"/>'
        + '<circle r="20" class="fsg-key-plate"/><text x="-24" y="-14" class="fsg-tiny fsg-light" text-anchor="end">REMOTE</text>'
        + '<text x="24" y="-14" class="fsg-tiny fsg-light" text-anchor="start">LOCAL</text>'
        + '<g class="fsg-key-barrel"><circle r="11" class="fsg-key-cyl"/><rect x="-2.2" y="-9" width="4.4" height="18" rx="1" class="fsg-key-slot"/>'
        + '<path d="M-3 -9 L-3 -24 L3 -24 L3 -9" class="fsg-key-blade"/><circle cy="-28" r="6" class="fsg-key-bow"/></g>'
        + '<text x="-34" y="4" class="fsg-tiny fsg-light" text-anchor="end">CONTROL</text>'
        + '<text x="-34" y="15" class="fsg-key-auth" data-txt="authority" text-anchor="end"></text></g>'
        + '<line x1="480" y1="76" x2="480" y2="688" class="fsg-split"/>';
    return `<svg class="fsg-svg" viewBox="0 0 980 712" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="13.8 kV switchgear line-up, path ${P}">`
        + defs + `<g filter="url(#fsg-powder)">${frame}`
        + FIELD_BREAKERS.map((b) => `<g class="fsg-section" data-section="${b}">${upperDoor(b)}${lowerDoor(b)}</g>`).join('')
        + '</g></svg>';
}

/** Write the plant state into a mounted line-up. */
export function applyFieldState(root, xfer, ui = {}) {
    if (!root || !xfer) return;
    const auth = String(xfer.authority || '');
    const key = root.querySelector('.fsg-key');
    if (key) key.setAttribute('data-auth', auth);
    const at = root.querySelector('[data-txt="authority"]');
    if (at) at.textContent = auth;
    for (const c of xfer.cubicles || []) {
        const sec = root.querySelector(`[data-section="${c.breaker}"]`);
        if (!sec) continue;
        sec.setAttribute('data-racking', c.racking);
        sec.setAttribute('data-closed', c.closed ? '1' : '0');
        sec.setAttribute('data-spring', c.spring_charged ? '1' : '0');
        sec.setAttribute('data-motor', c.motor_on ? '1' : '0');
        sec.setAttribute('data-86', c.lockout_86 ? '1' : '0');
        sec.setAttribute('data-locked', c.padlock ? '1' : '0');
        sec.setAttribute('data-ctrl', c.control_power ? '1' : '0');
        const leds = { closed: c.closed && c.control_power, open: !c.closed && c.control_power,
            spring: c.spring_charged && c.control_power, trip86: c.lockout_86, ctrl: c.control_power };
        for (const [k, on] of Object.entries(leds)) {
            const g = sec.querySelector(`[data-led="${k}"]`);
            if (g) g.setAttribute('data-on', on ? '1' : '0');
        }
        const flag = sec.querySelector('.fsg-flag-txt');
        if (flag) flag.textContent = c.closed ? 'I  CLOSED' : 'O  OPEN';
        const sflag = sec.querySelector('.fsg-sflag-txt');
        if (sflag) sflag.textContent = c.spring_charged ? 'CHARGED' : 'DISCHARGED';
        const pumps = sec.querySelector('[data-txt="pumps"]');
        if (pumps) pumps.textContent = c.spring_charged ? '' : `STROKES ${c.pumps} / ${c.pumps_needed}`;
        const chg = sec.querySelector('[data-txt="charging"]');
        if (chg) {
            chg.textContent = c.spring_charged ? 'READY'
                : (c.charging_s_left != null ? `MOTOR ${Math.ceil(c.charging_s_left)} s` : (c.motor_on ? 'MOTOR' : 'MANUAL'));
        }
        const ptr = sec.querySelector('.fsg-rack-ptr');
        if (ptr) ptr.style.transform = `translateX(${RACK_X[c.racking] ?? 0}px)`;
        const name = sec.querySelector('[data-txt="lockname"]');
        if (name) name.textContent = c.padlock ? String(c.padlock).slice(0, 10) : '';
        for (const kind of ['close', 'open']) {
            const pb = sec.querySelector(`[data-pb="${kind}"]`);
            if (pb) pb.setAttribute('data-cover', ui.covers && ui.covers.has(`${c.breaker}:${kind}`) ? 'open' : 'shut');
        }
    }
}

/** Map a click on the line-up to {breaker, action} (or a UI-only
 *  toggle). Needs the cubicle states to resolve the toggles. */
export function resolveClick(target, xfer) {
    const el = target && target.closest ? target.closest('[data-act]') : null;
    if (!el) return null;
    const act = el.getAttribute('data-act');
    const brk = el.getAttribute('data-brk');
    if (act === 'authority') {
        return { authority: xfer && xfer.authority === 'LOCAL' ? 'REMOTE' : 'LOCAL' };
    }
    const c = ((xfer && xfer.cubicles) || []).find((x) => x.breaker === brk) || {};
    switch (act) {
    case 'cover': return { cover: `${brk}:${el.getAttribute('data-kind')}` };
    case 'close': return { breaker: brk, action: 'LOCAL_CLOSE', kind: 'close' };
    case 'open': return { breaker: brk, action: 'LOCAL_OPEN', kind: 'open' };
    case '86': return { breaker: brk, action: c.lockout_86 ? 'RESET_86' : 'TRIP_86' };
    case 'motor': return { breaker: brk, action: c.motor_on ? 'MOTOR_OFF' : 'MOTOR_ON' };
    case 'pump': return { breaker: brk, action: 'PUMP_SPRING' };
    case 'lock': return { breaker: brk, action: c.padlock ? 'UNPADLOCK' : 'PADLOCK' };
    case 'rack_in': return { breaker: brk, action: 'RACK_IN' };
    case 'rack_out': return { breaker: brk, action: 'RACK_OUT' };
    default: return null;
    }
}

/** Status display under the line-up: last message + field events. */
export function fieldLogHtml(events, message = '', deviceId = '') {
    const rows = (events || [])
        .filter((ev) => ev.device_id === deviceId
            && (ev.field || (ev.event === 'refused' && String(ev.command || '').includes('@'))
                || ['spring_charged', 'auto_transfer_blocked', 'authority'].includes(ev.event)))
        .slice(0, 6)
        .map((ev) => {
            const t = new Date(Number(ev.ts) * 1000);
            const hh = Number.isNaN(t.getTime()) ? '' : t.toISOString().slice(11, 19);
            const what = ev.event === 'refused' ? `REFUSED ${ev.command}: ${ev.detail || ''}`
                : ev.event === 'command' ? `${ev.command} · ${ev.racking || ''}${ev.breaker_closed ? ' · CLOSED' : ''}`
                    : ev.event === 'authority' ? `CONTROL ${ev.previous} → ${ev.authority}`
                        : `${ev.event.replace(/_/g, ' ').toUpperCase()} ${ev.breaker || ''} ${ev.detail || ''}`;
            return `<li data-kind="${e(ev.event)}"><span>${e(hh)}</span><span>${e(what)}</span><span>${e(ev.actor || '')}</span></li>`;
        }).join('');
    return `<div class="fsg-lcd-msg" data-tone="${message ? 'warn' : 'ok'}">${e(message || 'READY · all operations are checked by the server interlocks')}</div>`
        + `<ul class="fsg-log">${rows || '<li><span></span><span>No switchgear operation yet</span><span></span></li>'}</ul>`;
}
