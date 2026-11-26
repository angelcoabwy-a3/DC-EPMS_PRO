/**
 * L5 (2026-11-26): field view of the battery room of one path (Layer 2,
 * equipment look; ADR-014): one rack of 40 VRLA jars at a time (4
 * strings, 542.1 V DC float), the tools a technician carries (infrared
 * camera with an ironbow palette, battery analyzer for jar voltage and
 * internal ohmic value, hand tools to replace a jar), the string
 * disconnects SB1..SB4 with padlock hasps and mid-string links, the H2
 * monitor and the exhaust fans EF-1 (lead) / EF-2 (lag).
 *
 * Same contract as the other field views: batterySvg() once per open,
 * applyBatteryState() from GET /api/devices (path summary ->
 * battery_room), every action is a server call
 * (POST /api/battery-rooms/{path}/action). The jar voltage and ohmic
 * value come only from the analyzer, as in the room. Simulated equipment.
 */
import { escapeHTML } from './sanitize.js';
import { door, fsgDefs, led } from './field_switchgear.js';

const e = (v) => escapeHTML(v === null || v === undefined ? '' : String(v));
const RX = 50, RY = 150, JW = 62, JH = 92;          // rack origin, jar pitch
const IR_MIN = 20, IR_MAX = 50;                      // fixed camera span, °C
// Ironbow-like ramp: black, violet, magenta-red, orange, yellow, white.
const IRONBOW = [[0, 0, 0, 0], [0.2, 60, 0, 120], [0.45, 190, 20, 90], [0.65, 240, 110, 10],
    [0.85, 255, 210, 40], [1, 255, 255, 235]];

export function ironbow(t) {
    const x = Math.max(0, Math.min(1, (Number(t) - IR_MIN) / (IR_MAX - IR_MIN)));
    for (let i = 1; i < IRONBOW.length; i++) {
        const [p1, r1, g1, b1] = IRONBOW[i];
        const [p0, r0, g0, b0] = IRONBOW[i - 1];
        if (x <= p1) {
            const k = (x - p0) / (p1 - p0 || 1);
            const c = (a, b) => Math.round(a + (b - a) * k);
            return `rgb(${c(r0, r1)},${c(g0, g1)},${c(b0, b1)})`;
        }
    }
    return 'rgb(255,255,235)';
}

function rack() {
    let jars = '';
    for (let j = 1; j <= 40; j++) {
        const col = (j - 1) % 10, row = Math.floor((j - 1) / 10);
        const x = RX + 14 + col * JW, y = RY + 34 + row * JH;
        jars += `<g class="xb-jar" data-jar="${j}" role="button" tabindex="0" transform="translate(${x} ${y})">`
            + '<rect x="0" y="10" width="52" height="70" rx="3" class="xb-jar-body"/>'
            + '<rect x="7" y="3" width="10" height="8" rx="1.5" class="xb-post xb-pos"/>'
            + '<rect x="35" y="3" width="10" height="8" rx="1.5" class="xb-post"/>'
            + `<text x="26" y="40" class="xb-jar-n" text-anchor="middle">${j}</text>`
            + `<text x="26" y="62" class="xb-jar-t" text-anchor="middle" data-txt="t${j}"></text></g>`;
    }
    let tabs = '';
    for (let s = 1; s <= 4; s++) {
        tabs += `<g class="xb-tab" data-act="tab" data-string="${s}" role="button" tabindex="0" transform="translate(${RX + 14 + (s - 1) * 96} ${RY - 52})">`
            + `<rect width="88" height="30" rx="3"/><text x="44" y="20" text-anchor="middle">STRING ${s}</text></g>`;
    }
    const tools = [['ir', 'IR CAMERA'], ['meter', 'ANALYZER'], ['replace', 'REPLACE JAR']];
    const toolBtns = tools.map(([k, label], i) =>
        `<g class="xb-tool" data-act="tool" data-tool="${k}" role="button" tabindex="0" transform="translate(${RX + 404 + i * 82} ${RY - 52})">`
        + `<rect width="76" height="30" rx="3"/><text x="38" y="20" text-anchor="middle">${label}</text></g>`).join('');
    return `<text x="${RX}" y="${RY - 62}" class="fsg-tiny fsg-light">BATTERY RACK · 40 × 12 V VRLA · 542.1 V DC FLOAT</text>`
        + tabs + toolBtns
        + `<rect x="${RX}" y="${RY}" width="650" height="410" rx="4" class="xb-rack"/>`
        + `<text x="${RX + 14}" y="${RY + 22}" class="fsg-tiny xu-light" data-txt="rackhead"></text>`
        + `<text x="${RX + 636}" y="${RY + 22}" class="fsg-tiny xu-light" text-anchor="end" data-txt="ircap"></text>`
        + jars
        + `<g class="xb-scale" transform="translate(${RX + 430} ${RY + 400})">`
        + `<rect x="0" y="-6" width="200" height="8" fill="url(#xb-ironbow)"/>`
        + `<text x="0" y="-10" class="fsg-tiny xu-light">${IR_MIN} °C</text>`
        + `<text x="200" y="-10" class="fsg-tiny xu-light" text-anchor="end">${IR_MAX} °C</text></g>`;
}

function analyzer() {
    const X = RX, Y = RY + 424;
    return `<g class="xb-meter" transform="translate(${X} ${Y})">`
        + '<rect width="650" height="96" rx="8" class="xb-meter-body"/>'
        + '<rect x="12" y="12" width="420" height="72" rx="3" class="xf-lcd"/>'
        + '<text x="24" y="36" class="xf-lcd-line" data-txt="m1">ANALYZER · select a jar</text>'
        + '<text x="24" y="56" class="xf-lcd-line" data-txt="m2"></text>'
        + '<text x="24" y="76" class="xf-lcd-lbl" data-txt="m3"></text>'
        + '<text x="448" y="30" class="fsg-tiny xu-light">BATTERY ANALYZER (MODEL)</text>'
        + '<text x="448" y="46" class="fsg-tiny xu-light">V DC · INTERNAL OHMIC mΩ</text>'
        + '<text x="448" y="62" class="fsg-tiny xu-light" data-txt="thr"></text>'
        + '<text x="448" y="78" class="fsg-tiny xu-light" data-txt="ir1"></text></g>';
}

function stringPanel() {
    const X = 720, Y = 84;
    let rows = '';
    for (let s = 1; s <= 4; s++) {
        const y = Y + 48 + (s - 1) * 92;
        rows += `<g class="xb-sb" data-sb="${s}" transform="translate(${X + 16} ${y})">`
            + '<rect width="200" height="84" rx="3" class="xu-brk-body"/>'
            + `<text x="10" y="16" class="fsg-label xu-light">SB${s}</text>`
            + `<text x="10" y="30" class="fsg-tiny xu-light" data-txt="sbv${s}"></text>`
            + `<text x="10" y="42" class="fsg-tiny xu-light" data-txt="sbw${s}"></text>`
            + `<text x="10" y="54" class="fsg-tiny xu-light" data-txt="sba${s}"></text>`
            + `<g class="xu-handle" data-act="sb" data-string="${s}" role="button" tabindex="0" transform="translate(110 46)">`
            + '<rect x="-16" y="-30" width="32" height="60" rx="4" class="xg-brk-body"/>'
            + '<g class="xu-handle-lever"><rect x="-8" y="-24" width="16" height="22" rx="3" class="xu-lever"/></g></g>'
            + `<g class="fsg-hasp xb-hasp" data-act="hasp" data-string="${s}" role="button" tabindex="0" transform="translate(148 50)">`
            + '<rect x="-12" y="-10" width="24" height="26" rx="3" class="fsg-hasp-plate"/><circle cy="2" r="4" class="fsg-hasp-hole"/>'
            + '<g class="xu-padlock"><path d="M-7 -2 L-7 -10 Q0 -20 7 -10 L7 -2" class="fsg-shackle"/>'
            + '<rect x="-10" y="-3" width="20" height="17" rx="2.5" class="fsg-lock-body"/></g></g>'
            + `<g class="xb-link" data-act="link" data-string="${s}" role="button" tabindex="0" transform="translate(181 50)">`
            + '<rect x="-16" y="-18" width="32" height="36" fill="transparent"/>'
            + '<circle cx="-9" r="4" class="xb-link-stud"/><circle cx="9" r="4" class="xb-link-stud"/>'
            + '<rect x="-12" y="-3" width="24" height="6" rx="2" class="xb-link-bar"/>'
            + '<text y="26" class="fsg-tiny xu-light" text-anchor="middle">LINK</text></g>'
            + `<text x="10" y="74" class="fsg-tiny xu-light" data-txt="sbs${s}"></text></g>`;
    }
    return door(X, Y, 232, 430, 'fsg-door-upper')
        + `<text x="${X + 16}" y="${Y + 24}" class="fsg-label">STRING DISCONNECTS</text>`
        + `<text x="${X + 16}" y="${Y + 36}" class="fsg-tiny">DC · BEHIND QF1 · STRING MONITOR</text>` + rows;
}

function selector(x, y, fan) {
    const acts = [`${fan}_hand`, `${fan}_off`, `${fan}_auto`];
    const lbl = ['HAND', 'OFF', 'AUTO'];
    return `<g class="fsg-sel xg-sel" data-sel="${fan}" transform="translate(${x} ${y}) scale(.72)">`
        + '<circle r="28" class="fsg-sel-plate"/>'
        + `<g data-act="${acts[0]}" role="button" tabindex="0"><rect x="-56" y="-38" width="34" height="18" fill="transparent"/><text x="-38" y="-26" class="fsg-tiny" text-anchor="middle">${lbl[0]}</text></g>`
        + `<g data-act="${acts[1]}" role="button" tabindex="0"><rect x="-17" y="-52" width="34" height="16" fill="transparent"/><text y="-40" class="fsg-tiny" text-anchor="middle">${lbl[1]}</text></g>`
        + `<g data-act="${acts[2]}" role="button" tabindex="0"><rect x="22" y="-38" width="34" height="18" fill="transparent"/><text x="38" y="-26" class="fsg-tiny" text-anchor="middle">${lbl[2]}</text></g>`
        + '<g class="fsg-sel-knob xg-knob"><circle r="16" class="fsg-sel-body"/>'
        + '<path d="M-4 -15 L4 -15 L3 6 L-3 6 Z" class="fsg-sel-bar"/><circle r="3" cy="-10" class="fsg-sel-dot"/></g></g>';
}

function ventPanel() {
    const X = 720, Y = 528;
    return door(X, Y, 232, 160, 'fsg-door-upper')
        + `<text x="${X + 16}" y="${Y + 22}" class="fsg-label">H2 EXHAUST</text>`
        + `<g transform="translate(${X + 14} ${Y + 30})"><rect width="204" height="42" rx="3" class="xf-lcd"/>`
        + '<text x="8" y="18" class="xf-lcd-line" data-txt="h1"></text>'
        + '<text x="8" y="34" class="xf-lcd-lbl" data-txt="h2"></text></g>'
        + selector(X + 46, Y + 118, 'ef1') + selector(X + 150, Y + 118, 'ef2')
        + `<text x="${X + 46}" y="${Y + 150}" class="fsg-tiny" text-anchor="middle">EF-1 LEAD</text>`
        + `<text x="${X + 150}" y="${Y + 150}" class="fsg-tiny" text-anchor="middle">EF-2 LAG</text>`
        + `<g transform="translate(${X + 98} ${Y + 98}) scale(.6)">${led(0, 0, 'green', '', 'ef1run')}</g>`
        + `<g transform="translate(${X + 202} ${Y + 98}) scale(.6)">${led(0, 0, 'green', '', 'ef2run')}</g>`
        + `<g class="xb-reset" data-act="ef1_reset" role="button" tabindex="0" transform="translate(${X + 98} ${Y + 128})"><rect x="-14" y="-7" width="28" height="14" rx="2"/><text y="4" text-anchor="middle">RST</text></g>`
        + `<g class="xb-reset" data-act="ef2_reset" role="button" tabindex="0" transform="translate(${X + 202} ${Y + 128})"><rect x="-14" y="-7" width="28" height="14" rx="2"/><text y="4" text-anchor="middle">RST</text></g>`;
}

/** Static SVG of the battery room field view for one path. */
export function batterySvg(path) {
    const P = e(String(path || 'a').toUpperCase());
    let stops = '';
    for (let i = 0; i <= 10; i++) stops += `<stop offset="${i / 10}" stop-color="${ironbow(IR_MIN + (IR_MAX - IR_MIN) * i / 10)}"/>`;
    const defs = fsgDefs().replace('</defs>', `<linearGradient id="xb-ironbow" x1="0" x2="1">${stops}</linearGradient></defs>`);
    const frame = '<rect x="20" y="20" width="940" height="672" rx="4" class="fsg-frame"/>'
        + '<rect x="20" y="20" width="940" height="52" rx="4" class="fsg-topcap"/>'
        + `<text x="44" y="44" class="fsg-head">BATTERY ROOM · UPS BANK ${P}</text>`
        + '<text x="44" y="61" class="fsg-tiny fsg-light">4 STRINGS × 40 JARS · VRLA · H2 EXHAUST · SIMULATED EQUIPMENT · MODEL VALUES</text>'
        + '<line x1="706" y1="76" x2="706" y2="688" class="fsg-split"/>';
    return `<svg class="fsg-svg xb-svg" viewBox="0 0 980 712" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Battery room field view, path ${P}">`
        + defs + `<g filter="url(#fsg-powder)">${frame}`
        + `<g class="fsg-section xb-section" data-section="BATT">${rack()}${analyzer()}${stringPanel()}${ventPanel()}</g>`
        + '</g></svg>';
}

function setText(root, key, text) {
    const el = root.querySelector(`[data-txt="${key}"]`);
    if (el) el.textContent = text;
}

/** Write the battery room into the view. ui = {string, tool}. */
export function applyBatteryState(root, summary, ui = {}) {
    const room = summary && summary.battery_room;
    if (!root || !room) return;
    const sec = root.querySelector('[data-section="BATT"]');
    if (!sec) return;
    const s = Math.min(4, Math.max(1, Number(ui.string) || 1));
    const tool = ui.tool || 'meter';
    const st = room.strings[s - 1] || {};
    const ir = tool === 'ir';
    sec.setAttribute('data-tool', tool);
    sec.setAttribute('data-ir', ir ? '1' : '0');
    sec.querySelectorAll('.xb-tab').forEach((g) => g.setAttribute('data-on', g.getAttribute('data-string') === String(s) ? '1' : '0'));
    sec.querySelectorAll('.xb-tool').forEach((g) => g.setAttribute('data-on', g.getAttribute('data-tool') === tool ? '1' : '0'));
    setText(sec, 'rackhead', `STRING ${s} · ${st.online ? 'ON LINE' : 'OFF LINE'} · ${st.voltage_v} V`
        + (st.float_a != null ? ` · FLOAT ${Number(st.float_a).toFixed(1)} A` : ''));
    const temps = st.temps || [];
    const vented = new Set(st.vented || []);
    const sel = ui.jar ? Number(ui.jar) : null;
    let hot = { j: 0, t: -99 };
    for (let j = 1; j <= 40; j++) {
        const g = sec.querySelector(`.xb-jar[data-jar="${j}"]`);
        if (!g) continue;
        const t = Number(temps[j - 1]);
        if (t > hot.t) hot = { j, t };
        const body = g.querySelector('.xb-jar-body');
        if (body) body.style.fill = ir ? ironbow(t) : '';
        g.setAttribute('data-vented', vented.has(j) ? '1' : '0');
        g.setAttribute('data-sel', sel === j ? '1' : '0');
        setText(g, `t${j}`, ir ? `${t.toFixed(1)}°` : '');
    }
    const sorted = temps.map(Number).sort((a, b) => a - b);
    const med = sorted.length ? sorted[Math.floor(sorted.length / 2)] : 0;
    setText(sec, 'ircap', ir ? `IR · SPOT MAX JAR ${hot.j} ${hot.t.toFixed(1)} °C · ΔT ${(hot.t - med).toFixed(1)} K` : '');
    const th = room.thresholds || {};
    setText(sec, 'thr', `OHMIC WARN +${th.ohmic_warn_pct} % · REPLACE +${th.ohmic_replace_pct} %`);
    setText(sec, 'ir1', `ΔT WARN ${th.dt_warn_c} K · ALARM ${th.dt_alarm_c} K`);
    const last = (room.readings || [])[room.readings.length - 1];
    if (last) {
        setText(sec, 'm1', `JAR ${last.jar} · ${Number(last.v).toFixed(2)} V DC`);
        setText(sec, 'm2', `${Number(last.r_mohm).toFixed(2)} mΩ · BASE ${Number(last.r_base_mohm).toFixed(2)} · ${last.rise_pct >= 0 ? '+' : ''}${last.rise_pct} %`);
        setText(sec, 'm3', `${last.status} · CASE ${Number(last.temp_c).toFixed(1)} °C`);
        sec.setAttribute('data-mstatus', last.status);
    }
    for (const x of room.strings || []) {
        const g = sec.querySelector(`.xb-sb[data-sb="${x.n}"]`);
        if (!g) continue;
        g.setAttribute('data-closed', x.closed ? '1' : '0');
        g.setAttribute('data-padlock', x.padlock ? '1' : '0');
        g.setAttribute('data-link', x.link ? '1' : '0');
        g.setAttribute('data-high', x.float_high ? '1' : '0');
        setText(g, `sbv${x.n}`, x.closed ? 'CLOSED' : 'OPEN');
        setText(g, `sbw${x.n}`, `${x.voltage_v} V`);
        setText(g, `sba${x.n}`, x.float_a != null ? `FLOAT ${Number(x.float_a).toFixed(1)} A${x.float_high ? ' HIGH' : ''}` : 'NO CURRENT');
        setText(g, `sbs${x.n}`, x.padlock ? `LOCK ${String(x.padlock).slice(0, 9)}` : (x.link ? '' : 'LINK OUT'));
    }
    const ppm = Number(room.h2_ppm);
    setText(sec, 'h1', `H2 ${ppm.toFixed(0)} ppm · ${room.h2_pct_lel} % LEL`);
    setText(sec, 'h2', ppm >= room.h2_hihi_ppm ? 'HIGH-HIGH · 25 % LEL' : ppm >= room.h2_alarm_ppm ? 'ALARM · 1 % LEL' : 'NORMAL');
    sec.setAttribute('data-h2', ppm >= room.h2_alarm_ppm ? '1' : '0');
    const rot = { HAND: -45, OFF: 0, AUTO: 45 };
    for (const f of room.fans || []) {
        const k = f.name.toLowerCase();
        const knob = sec.querySelector(`[data-sel="${k}"] .xg-knob`);
        if (knob) knob.style.transform = `rotate(${rot[f.mode] || 0}deg)`;
        const lamp = sec.querySelector(`[data-led="${k}run"]`);
        if (lamp) lamp.setAttribute('data-on', f.running ? '1' : '0');
        const rst = sec.querySelector(`[data-act="${k}_reset"]`);
        if (rst) rst.setAttribute('data-failed', f.failed ? '1' : '0');
    }
}

/** Map a click to {action}, {ui} (view-only change) or null. */
export function resolveBatteryClick(target, room, ui = {}) {
    const el = target && target.closest ? target.closest('[data-act], .xb-jar') : null;
    if (!el || !room) return null;
    const s = Math.min(4, Math.max(1, Number(ui.string) || 1));
    if (el.classList && el.classList.contains('xb-jar')) {
        const j = Number(el.getAttribute('data-jar'));
        if (ui.tool === 'replace') return { action: `REPLACE_S${s}_J${j}`, kind: 'tool' };
        if (ui.tool === 'ir') return { ui: { jar: j } };
        return { action: `MEASURE_S${s}_J${j}`, kind: 'probe', ui: { jar: j } };
    }
    const act = el.getAttribute('data-act');
    const n = Number(el.getAttribute('data-string'));
    const x = (room.strings || [])[n - 1] || {};
    if (act === 'tab') return { ui: { string: n, jar: null }, scan: ui.tool === 'ir' ? `IR_SCAN_S${n}` : null };
    if (act === 'tool') {
        const tool = el.getAttribute('data-tool');
        return { ui: { tool }, scan: tool === 'ir' ? `IR_SCAN_S${s}` : null };
    }
    if (act === 'sb') return { action: `${x.closed ? 'OPEN' : 'CLOSE'}_SB${n}`, kind: 'breaker' };
    if (act === 'hasp') return { action: `${x.padlock ? 'UNPADLOCK' : 'PADLOCK'}_SB${n}`, kind: 'key' };
    if (act === 'link') return { action: `${x.link ? 'BREAK_LINK' : 'MAKE_LINK'}_S${n}`, kind: 'tool' };
    const m = /^(ef[12])_(hand|off|auto|reset)$/.exec(act || '');
    if (m) return { action: `${m[1].toUpperCase()}_${m[2].toUpperCase()}`, kind: m[2] === 'reset' ? 'button' : 'selector' };
    return null;
}

export function isBatteryEvent(ev) {
    return ev.equipment === 'battery' || /@BATT_[AB]$/.test(String(ev.command || ''))
        || ['thermal_runaway', 'fan_start', 'battery_condition'].includes(ev.event);
}

export function batteryEventText(ev) {
    if (ev.event === 'refused') return `REFUSED ${ev.command}: ${ev.detail || ''}`;
    const r = ev.reading;
    if (ev.event === 'inspection' && r && r.jar) return `ANALYZER ${r.jar} · ${r.v} V · ${r.r_mohm} mΩ · ${r.status}`;
    if (ev.event === 'inspection' && r) return `IR SCAN STRING ${r.string} · MAX ${r.hottest} ${r.max_c} °C`;
    if (ev.event === 'command') return `${ev.command} · ${ev.strings_online} of 4 strings on line`;
    return `${String(ev.event).replace(/_/g, ' ').toUpperCase()} ${ev.detail || ''}`.trim();
}
