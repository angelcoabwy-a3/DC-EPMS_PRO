/**
 * L3 (2026-11-26): field view of one diesel generator set (Layer 2,
 * equipment look; ADR-014): the engine control panel (ECS selector
 * STOP-RESET / AUTO / RUN, emergency stop, display, pilot lights), the
 * 240 VAC jacket-water heater breaker, the 1,200 L sub-base day tank
 * with its five floats, the duplex transfer pumps P-1 lead / P-2 lag
 * (HAND-OFF-AUTO, run lamps, 49/OL reset, discharge gauge), the duplex
 * fuel filter / water separator, the rupture-basin leak float and the
 * main tank of the path.
 *
 * Contract as the other field views: genSvg() once per open with data
 * hooks, applyGenState() writes from GET /api/devices (generator device
 * -> "fuel"; path summary -> bulk tank), every action is a server call
 * (POST /api/devices/{id}/fuel). Honest scope: simulated set, model
 * values and compressed time are said on the panel.
 */
import { escapeHTML } from './sanitize.js';
import { door, fsgDefs, led } from './field_switchgear.js';

export const GEN_SETS = 9;
const TANK = { x: 532, y: 130, w: 86, h: 280 };
const ECS_ANGLE = { STOP: -45, AUTO: 0, RUN: 45 };
const PUMP_ANGLE = { HAND: -45, OFF: 0, AUTO: 45 };
const FILTER_ANGLE = { A: -40, BOTH: 0, B: 40 };
const e = (v) => escapeHTML(v === null || v === undefined ? '' : String(v));

export function genId(path, n) {
    return `genset_${String(path || 'a').toLowerCase()}_${String(n).padStart(2, '0')}`;
}

function selector3(x, y, key, labels, acts, caption) {
    return `<g class="fsg-sel xg-sel" data-sel="${key}" transform="translate(${x} ${y})">`
        + '<circle r="28" class="fsg-sel-plate"/>'
        + `<g data-act="${acts[0]}" role="button" tabindex="0"><rect x="-56" y="-38" width="34" height="18" fill="transparent"/><text x="-38" y="-26" class="fsg-tiny" text-anchor="middle">${labels[0]}</text></g>`
        + `<g data-act="${acts[1]}" role="button" tabindex="0"><rect x="-17" y="-52" width="34" height="16" fill="transparent"/><text y="-40" class="fsg-tiny" text-anchor="middle">${labels[1]}</text></g>`
        + `<g data-act="${acts[2]}" role="button" tabindex="0"><rect x="22" y="-38" width="34" height="18" fill="transparent"/><text x="38" y="-26" class="fsg-tiny" text-anchor="middle">${labels[2]}</text></g>`
        + '<g class="fsg-sel-knob xg-knob"><circle r="16" class="fsg-sel-body"/>'
        + '<path d="M-4 -15 L4 -15 L3 6 L-3 6 Z" class="fsg-sel-bar"/><circle r="3" cy="-10" class="fsg-sel-dot"/></g>'
        + `<text y="44" class="fsg-label" text-anchor="middle">${caption}</text></g>`;
}

function controlPanel() {
    const X = 40, Y = 84;
    return door(X, Y, 420, 586, 'fsg-door-upper')
        + `<g class="fsg-nameplate" transform="translate(${X + 30} ${Y + 22})">`
        + '<rect width="230" height="58" rx="2" class="fsg-np-plate"/>'
        + '<circle cx="8" cy="8" r="2.2" class="fsg-rivet"/><circle cx="222" cy="8" r="2.2" class="fsg-rivet"/>'
        + '<circle cx="8" cy="50" r="2.2" class="fsg-rivet"/><circle cx="222" cy="50" r="2.2" class="fsg-rivet"/>'
        + '<text x="115" y="25" class="fsg-np-big" text-anchor="middle" data-txt="np">GEN</text>'
        + '<text x="115" y="39" class="fsg-np-small" text-anchor="middle">2.75 MW STANDBY · 13.8 kV · 1800 rpm</text>'
        + '<text x="115" y="50" class="fsg-np-small" text-anchor="middle">ENGINE CONTROL PANEL (MODEL)</text></g>'
        // display
        + `<g transform="translate(${X + 22} ${Y + 98})"><rect width="376" height="132" rx="5" class="xf-mon"/>`
        + '<rect x="12" y="12" width="352" height="108" rx="2" class="xf-lcd"/>'
        + '<text x="22" y="32" class="xf-lcd-line" data-txt="d1"></text>'
        + '<text x="22" y="52" class="xf-lcd-line" data-txt="d2"></text>'
        + '<text x="22" y="72" class="xf-lcd-line" data-txt="d3"></text>'
        + '<text x="22" y="92" class="xf-lcd-line" data-txt="d4"></text>'
        + '<text x="22" y="111" class="xf-lcd-lbl" data-txt="d5"></text></g>'
        + led(X + 66, Y + 262, 'green', 'RUNNING', 'run')
        + led(X + 136, Y + 262, 'amber', 'NOT AUTO', 'notauto')
        + led(X + 206, Y + 262, 'red', 'SHUTDOWN', 'shut')
        + led(X + 276, Y + 262, 'amber', 'LOW COOL T', 'cold')
        + led(X + 346, Y + 262, 'amber', 'FUEL LOW', 'fuellow')
        + selector3(X + 100, Y + 380, 'ecs', ['STOP', 'AUTO', 'RUN'], ['ecs_stop', 'ecs_auto', 'ecs_run'], 'ENGINE CONTROL')
        // emergency stop: yellow collar, red mushroom
        + `<g class="xg-estop" data-act="estop" role="button" tabindex="0" transform="translate(${X + 290} ${Y + 380})">`
        + '<circle r="46" class="xg-estop-collar"/><text y="-34" class="xg-estop-txt" text-anchor="middle">EMERGENCY</text>'
        + '<text y="40" class="xg-estop-txt" text-anchor="middle">STOP</text>'
        + '<g class="xg-estop-cap"><circle r="27" class="xg-estop-shadow"/><circle r="25" class="xg-estop-red"/>'
        + '<ellipse cx="-8" cy="-9" rx="9" ry="5" class="xg-estop-glint"/></g>'
        + '<title>Push to stop at once (no cooldown). Twist to release, then STOP / RESET clears the shutdown.</title></g>'
        // jacket heater breaker
        + `<g transform="translate(${X + 22} ${Y + 470})"><rect width="376" height="96" rx="4" class="xf-relay-pan"/>`
        + '<text x="10" y="14" class="fsg-tiny fsg-light">JACKET-WATER HEATER · 240 VAC</text>'
        + '<g class="xg-brk" data-act="heater" role="button" tabindex="0" transform="translate(70 56)">'
        + '<rect x="-22" y="-30" width="44" height="60" rx="3" class="xg-brk-body"/>'
        + '<rect x="-8" y="-20" width="16" height="40" rx="2" class="xg-brk-slot"/>'
        + '<g class="xg-brk-handle"><rect x="-10" y="-20" width="20" height="18" rx="2" class="xg-brk-toggle"/></g>'
        + '<text x="32" y="-18" class="fsg-tiny fsg-light">ON</text>'
        + '<text x="32" y="26" class="fsg-tiny fsg-light">OFF</text></g>'
        + '<text x="130" y="44" class="xf-lcd-lbl xg-cool-lbl">COOLANT</text>'
        + '<text x="130" y="68" class="xg-cool" data-txt="coolant"></text>'
        + '<text x="236" y="44" class="fsg-tiny fsg-light">NFPA 110 LEVEL 1</text>'
        + '<text x="236" y="56" class="fsg-tiny fsg-light">MINIMUM 32 °C</text>'
        + '<text x="236" y="72" class="fsg-tiny fsg-light" data-txt="heaternote"></text></g>';
}

function dayTank() {
    const { x, y, w, h } = TANK;
    const marks = [['hi_hi', 95, '95 HI-HI SHUTOFF'], ['pump_stop', 85, '85 PUMPS STOP'],
        ['lead', 60, '60 P-1 LEAD'], ['lag', 40, '40 P-2 LOW'], ['crit', 15, '15 ENGINE SHUTDN']]
        .map(([k, pct, label]) => {
            const yy = y + h - (h * pct) / 100;
            return `<g class="xg-mark" data-mark="${k}"><line x1="${x - 6}" y1="${yy}" x2="${x + w + 6}" y2="${yy}"/>`
                + `<circle cx="${x + w + 12}" cy="${yy}" r="4" class="xg-mark-dot"/>`
                + `<text x="${x + w + 20}" y="${yy + 3}" class="fsg-tiny">${label}</text></g>`;
        }).join('');
    return door(510, 84, 214, 372, 'fsg-door-upper')
        + `<text x="${x - 6}" y="${y - 22}" class="fsg-label">SUB-BASE DAY TANK</text>`
        + `<text x="${x - 6}" y="${y - 10}" class="fsg-tiny">1,200 L · MAGNETIC FLOATS</text>`
        + `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="4" class="xg-tank"/>`
        + `<clipPath id="xg-tank-clip"><rect x="${x + 3}" y="${y + 3}" width="${w - 6}" height="${h - 6}" rx="3"/></clipPath>`
        + '<g clip-path="url(#xg-tank-clip)">'
        + `<g class="xg-fuel"><rect class="xg-fuel-body" x="${x}" y="${y}" width="${w}" height="${h}"/>`
        + `<path class="xg-wave" d="M${x - 40} ${y} q15 -5 30 0 t30 0 t30 0 t30 0 t30 0 t30 0 t30 0 V${y + 8} H${x - 40} Z"/></g></g>`
        + marks
        + `<text x="${x + w / 2}" y="${y + h + 20}" class="xg-tank-pct" data-txt="lvl" text-anchor="middle"></text>`
        + `<text x="${x + w / 2}" y="${y + h + 34}" class="fsg-tiny" data-txt="lvl_l" text-anchor="middle"></text>`;
}

function pumpPanel() {
    const X = 752, Y = 96;
    const pump = (k, x, name, role) => `<g data-pump="${k}" transform="translate(${x} 0)">`
        + `<text y="40" class="fsg-label" text-anchor="middle">${name}</text>`
        + `<text y="51" class="fsg-tiny" text-anchor="middle">${role}</text>`
        + `<g transform="translate(0 100) scale(.72)">${selector3(0, 0, k, ['HAND', 'OFF', 'AUTO'],
            [`${k}_hand`, `${k}_off`, `${k}_auto`], '')}</g>`
        + `<g class="fsg-led" data-led="${k}run" data-colour="green" transform="translate(-22 162)">`
        + '<circle r="11" class="fsg-led-bezel"/><circle r="8" class="fsg-led-lens"/>'
        + '<text y="22" class="fsg-tiny" text-anchor="middle">RUN</text></g>'
        + `<g class="xg-ol" data-act="${k}_ol" role="button" tabindex="0" transform="translate(18 162)">`
        + '<rect x="-15" y="-13" width="30" height="26" rx="3" class="xg-ol-body"/><circle r="8" class="xg-ol-btn"/>'
        + '<text y="24" class="fsg-tiny" text-anchor="middle">49/OL</text></g></g>';
    return door(X - 14, Y - 12, 192, 372, 'fsg-door-upper')
        + `<text x="${X + 80}" y="${Y + 12}" class="fsg-label" text-anchor="middle">DUPLEX TRANSFER PUMPS</text>`
        + `<g transform="translate(${X} ${Y})">${pump('p1', 30, 'P-1', 'LEAD')}${pump('p2', 106, 'P-2', 'LAG')}</g>`
        + `<g transform="translate(${X + 100} ${Y + 250})"><circle r="22" class="xf-dial-bezel"/><circle r="18" class="xf-dial-face"/>`
        + '<g class="xf-needle" data-needle="disch"><path d="M-1.5 3 L0 -15 L1.5 3 Z" class="xf-needle-shape"/></g><circle r="2.5" class="xf-needle-hub"/>'
        + '<text y="34" class="fsg-tiny" text-anchor="middle" data-txt="disch"></text></g>'
        + `<g class="fsg-led" data-led="sol" data-colour="white" transform="translate(${X + 34} ${Y + 250})">`
        + '<circle r="10" class="fsg-led-bezel"/><circle r="7" class="fsg-led-lens"/>'
        + '<text y="22" class="fsg-tiny" text-anchor="middle">SOLENOID</text></g>'
        + `<text x="${X + 82}" y="${Y + 304}" class="fsg-label" text-anchor="middle">MAIN TANK · PATH</text>`
        + `<text x="${X + 82}" y="${Y + 318}" class="fsg-tiny" text-anchor="middle" data-txt="bulk"></text>`
        + `<text x="${X + 82}" y="${Y + 330}" class="fsg-tiny" text-anchor="middle" data-txt="bulkh"></text>`;
}

function bowl(side, x, y) {
    return `<g data-bowl="${side}" transform="translate(${x} ${y})">`
        + '<rect x="-24" y="-10" width="48" height="16" rx="3" class="xg-filter-head"/>'
        + '<rect x="-18" y="6" width="36" height="70" rx="8" class="xg-bowl"/>'
        + '<rect x="-16" y="8" width="32" height="66" rx="7" class="xg-bowl-fuel"/>'
        + '<rect x="-16" y="74" width="32" height="0" rx="2" class="xg-bowl-water" data-water="1"/>'
        + `<text y="-16" class="fsg-label" text-anchor="middle">FILTER ${side}</text>`
        + `<text y="92" class="fsg-tiny" text-anchor="middle" data-txt="water_${side}"></text>`
        + `<g class="fsg-btn-rack" data-act="drain_${side}" role="button" tabindex="0" transform="translate(0 108)">`
        + '<rect x="-26" y="-8" width="52" height="16" rx="3"/><text y="3.5" text-anchor="middle">DRAIN</text></g>'
        + `<g class="fsg-btn-rack" data-act="elem_${side}" role="button" tabindex="0" transform="translate(0 128)">`
        + '<rect x="-26" y="-8" width="52" height="16" rx="3"/><text y="3.5" text-anchor="middle">ELEMENT</text></g></g>';
}

function fuelPanel() {
    const X = 510, Y = 470;
    return door(X, Y, 420, 200, 'fsg-door-upper')
        + `<text x="${X + 20}" y="${Y + 22}" class="fsg-label">DUPLEX FUEL FILTER / WATER SEPARATOR</text>`
        + bowl('A', X + 46, Y + 54) + bowl('B', X + 196, Y + 54)
        + `<g transform="translate(${X + 121} ${Y + 92})">${selector3(0, 0, 'filter', ['A', 'BOTH', 'B'],
            ['filter_a', 'filter_both', 'filter_b'], '')}</g>`
        + `<g transform="translate(${X + 121} ${Y + 158})"><circle r="20" class="xf-dial-bezel"/><circle r="16" class="xf-dial-face"/>`
        + '<g class="xf-needle" data-needle="dp"><path d="M-1.5 3 L0 -13 L1.5 3 Z" class="xf-needle-shape"/></g><circle r="2.5" class="xf-needle-hub"/>'
        + '<text y="32" class="fsg-tiny" text-anchor="middle" data-txt="dp"></text></g>'
        // rupture basin
        + `<g transform="translate(${X + 320} ${Y + 40})"><text x="10" y="0" class="fsg-label" text-anchor="middle">RUPTURE BASIN</text>`
        + '<rect x="-50" y="10" width="120" height="44" rx="2" class="xg-basin"/>'
        + '<rect x="-48" y="40" width="116" height="12" class="xg-basin-fuel"/>'
        + '<g class="xg-float"><rect x="-6" y="28" width="12" height="16" rx="3" class="xg-float-body"/></g>'
        + '<g class="fsg-led" data-led="leak" data-colour="red" transform="translate(48 30)"><circle r="9" class="fsg-led-bezel"/><circle r="6" class="fsg-led-lens"/></g>'
        + '<text x="10" y="70" class="fsg-tiny" text-anchor="middle">LEAK FLOAT · STOPS PUMPS</text>'
        + '<g class="fsg-btn-rack" data-act="clean_basin" role="button" tabindex="0" transform="translate(-14 96)">'
        + '<rect x="-34" y="-9" width="68" height="18" rx="3"/><text y="4" text-anchor="middle">CLEAN BASIN</text></g>'
        + '<g class="fsg-btn-rack" data-act="reset_leak" role="button" tabindex="0" transform="translate(60 96)">'
        + '<rect x="-30" y="-9" width="60" height="18" rx="3"/><text y="4" text-anchor="middle">RESET</text></g></g>';
}

/** Static SVG of the generator field view for one path. */
export function genSvg(path) {
    const P = e(String(path || 'a').toUpperCase());
    let sets = '';
    for (let n = 1; n <= GEN_SETS; n++) {
        sets += `<g class="xg-setbtn" data-act="set" data-n="${n}" role="button" tabindex="0" transform="translate(${598 + (n - 1) * 38} 46)">`
            + `<rect x="-16" y="-12" width="32" height="24" rx="3"/><text y="4" text-anchor="middle">G${n}</text></g>`;
    }
    const frame = '<rect x="20" y="20" width="940" height="672" rx="4" class="fsg-frame"/>'
        + '<rect x="20" y="20" width="940" height="52" rx="4" class="fsg-topcap"/>'
        + `<text x="44" y="44" class="fsg-head" data-txt="head">GENERATOR SET · PATH ${P}</text>`
        + '<text x="44" y="61" class="fsg-tiny fsg-light" data-txt="sub">SIMULATED EQUIPMENT</text>'
        + sets
        + '<line x1="490" y1="76" x2="490" y2="688" class="fsg-split"/>';
    return `<svg class="fsg-svg xg-svg" viewBox="0 0 980 712" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Generator set field view, path ${P}">`
        + fsgDefs() + `<g filter="url(#fsg-powder)">${frame}`
        + `<g class="fsg-section xg-section" data-section="GEN">${controlPanel()}${dayTank()}${pumpPanel()}${fuelPanel()}</g>`
        + '</g></svg>';
}

function setText(root, key, text) {
    const el = root.querySelector(`[data-txt="${key}"]`);
    if (el) el.textContent = text;
}

function reading(dev, label) {
    const r = (dev.readings || []).find((x) => x.label === label);
    return r ? Number(r.value) : 0;
}

/** Write a generator snapshot (and its path summary) into the view. */
export function applyGenState(root, dev, path = null, n = 1) {
    if (!root || !dev || !dev.fuel) return;
    const f = dev.fuel;
    const sec = root.querySelector('[data-section="GEN"]');
    if (!sec) return;
    const running = ['CRANKING', 'RUNNING', 'ON_LOAD'].includes(dev.state);
    const attrs = { 'data-estop': f.estop, 'data-running': running, 'data-heater': f.heater_on,
        'data-leak': f.leak, 'data-leak-present': f.leak_present, 'data-ecs': f.ecs_mode };
    for (const [k, v] of Object.entries(attrs)) {
        sec.setAttribute(k, typeof v === 'boolean' ? (v ? '1' : '0') : String(v ?? ''));
    }
    root.querySelectorAll('.xg-setbtn').forEach((b) =>
        b.setAttribute('data-on', String(Number(b.getAttribute('data-n')) === Number(n) ? 1 : 0)));
    setText(root, 'head', `${String(dev.display || dev.id).toUpperCase()} · PATH ${String(dev.path || '').toUpperCase()}`);
    setText(root, 'sub', `2.75 MW · 13.8 kV · ${f.model_note ? `TIME ×${f.time_scale} (MODEL)` : ''} · SIMULATED EQUIPMENT`);
    setText(sec, 'np', String(dev.display || '').replace('Generator ', 'G-'));
    const state = String(dev.state || '').replace(/_/g, ' ');
    setText(sec, 'd1', `${state} · ECS ${f.ecs_mode}${f.estop ? ' · E-STOP' : ''}`);
    setText(sec, 'd2', `${reading(dev, 'Engine speed').toFixed(0)} rpm · ${reading(dev, 'Output frequency').toFixed(1)} Hz · ${reading(dev, 'Real power').toFixed(0)} kW`);
    setText(sec, 'd3', `COOLANT ${Number(f.coolant_c).toFixed(1)} °C · FUEL ${Number(f.burn_lph).toFixed(0)} L/h`);
    setText(sec, 'd4', f.shutdown ? `SHUTDOWN: ${f.shutdown}` : (f.available_reason || 'READY'));
    setText(sec, 'd5', `DAY TANK ${f.day_tank_pct} % · ${f.run_hours_left != null ? `${f.run_hours_left} h at this burn` : 'not burning'}`);
    setText(sec, 'coolant', `${Number(f.coolant_c).toFixed(1)} °C`);
    setText(sec, 'heaternote', f.heater_on ? 'ON · SET 43 °C (MODEL)' : 'HEATER OFF');
    const leds = { run: running, notauto: f.ecs_mode !== 'AUTO', shut: !!f.shutdown || f.estop,
        cold: f.coolant_low, fuellow: f.low_alarm,
        p1run: f.pumps[0] && f.pumps[0].running, p2run: f.pumps[1] && f.pumps[1].running,
        sol: f.solenoid_open, leak: f.leak };
    for (const [k, on] of Object.entries(leds)) {
        const g = sec.querySelector(`[data-led="${k}"]`);
        if (g) g.setAttribute('data-on', on ? '1' : '0');
    }
    const rot = (sel, deg) => {
        const g = sec.querySelector(`[data-sel="${sel}"] .xg-knob`);
        if (g) g.style.transform = `rotate(${deg}deg)`;
    };
    rot('ecs', ECS_ANGLE[f.ecs_mode] ?? 0);
    rot('p1', PUMP_ANGLE[f.pumps[0]?.mode] ?? 0);
    rot('p2', PUMP_ANGLE[f.pumps[1]?.mode] ?? 0);
    rot('filter', FILTER_ANGLE[f.filter?.selected] ?? 0);
    for (const k of ['p1', 'p2']) {
        const p = f.pumps[k === 'p1' ? 0 : 1] || {};
        const ol = sec.querySelector(`[data-act="${k}_ol"]`);
        if (ol) ol.setAttribute('data-trip', p.overload ? '1' : '0');
    }
    // day tank
    const lvl = Math.max(0, Math.min(100, Number(f.day_tank_pct)));
    const fuel = sec.querySelector('.xg-fuel');
    if (fuel) fuel.style.transform = `translateY(${(TANK.h * (100 - lvl)) / 100}px)`;
    setText(sec, 'lvl', `${lvl.toFixed(1)} %`);
    setText(sec, 'lvl_l', `${f.day_tank_l} L`);
    for (const [k, pct] of Object.entries({ hi_hi: 95, pump_stop: 85, lead: 60, lag: 40, crit: 15 })) {
        const m = sec.querySelector(`[data-mark="${k}"]`);
        if (m) m.setAttribute('data-wet', lvl >= pct ? '1' : '0');
    }
    // pumps discharge, bulk
    const needle = (key, deg) => {
        const g = sec.querySelector(`[data-needle="${key}"]`);
        if (g) g.style.transform = `rotate(${deg}deg)`;
    };
    needle('disch', -120 + 240 * Math.min(1, Number(f.discharge_psig) / 40));
    setText(sec, 'disch', `${Number(f.discharge_psig).toFixed(0)} psig`);
    if (path) {
        setText(sec, 'bulk', `${path.bulk_fuel_pct ?? '—'} % of 50,000 L`);
        setText(sec, 'bulkh', path.bulk_hours_left != null ? `${path.bulk_hours_left} h at path burn` : 'no burn');
    }
    // filter
    const filt = f.filter || {};
    needle('dp', -120 + 240 * Math.min(1, Number(filt.dp_psi) / 10));
    setText(sec, 'dp', `ΔP ${Number(filt.dp_psi).toFixed(1)} psi`);
    for (const side of ['A', 'B']) {
        const w = Number((filt.water_pct || {})[side] || 0);
        const b = sec.querySelector(`[data-bowl="${side}"]`);
        if (!b) continue;
        b.setAttribute('data-insvc', filt.selected === side || filt.selected === 'BOTH' ? '1' : '0');
        const water = b.querySelector('[data-water]');
        if (water) {
            const hh = (64 * w) / 100;
            water.setAttribute('y', String(74 - hh));
            water.setAttribute('height', String(hh));
        }
        setText(b, `water_${side}`, `WATER ${w.toFixed(0)} %`);
    }
}

/** Map a click to {action} (server action), {set: n} or null. */
export function resolveGenClick(target, dev) {
    const el = target && target.closest ? target.closest('[data-act]') : null;
    if (!el) return null;
    const act = el.getAttribute('data-act');
    if (act === 'set') return { set: Number(el.getAttribute('data-n')) };
    const f = dev && dev.fuel;
    if (!f) return null;
    const map = {
        ecs_stop: ['ECS_STOP', 'selector'], ecs_auto: ['ECS_AUTO', 'selector'], ecs_run: ['ECS_RUN', 'selector'],
        estop: [f.estop ? 'ESTOP_RELEASE' : 'ESTOP_PUSH', 'estop'],
        heater: [f.heater_on ? 'HEATER_OFF' : 'HEATER_ON', 'breaker'],
        p1_hand: ['P1_HAND', 'selector'], p1_off: ['P1_OFF', 'selector'], p1_auto: ['P1_AUTO', 'selector'],
        p2_hand: ['P2_HAND', 'selector'], p2_off: ['P2_OFF', 'selector'], p2_auto: ['P2_AUTO', 'selector'],
        p1_ol: ['RESET_P1_OL', 'button'], p2_ol: ['RESET_P2_OL', 'button'],
        filter_a: ['FILTER_A', 'selector'], filter_both: ['FILTER_BOTH', 'selector'], filter_b: ['FILTER_B', 'selector'],
        drain_A: ['DRAIN_A', 'button'], drain_B: ['DRAIN_B', 'button'],
        elem_A: ['CHANGE_ELEMENT_A', 'button'], elem_B: ['CHANGE_ELEMENT_B', 'button'],
        clean_basin: ['CLEAN_BASIN', 'button'], reset_leak: ['RESET_LEAK', 'button'],
    };
    const hit = map[act];
    if (!hit) return null;
    return { action: hit[0], kind: hit[1] };
}

/** True when a plant event belongs to the generator field view. */
export function isGenEvent(ev) {
    return ev.equipment === 'gen' || /@GENSET_/.test(String(ev.command || ''))
        || ['gen_fuel_low', 'gen_fuel_normal', 'gen_basin_leak', 'local_start', 'local_stop', 'gen_condition'].includes(ev.event)
        || (ev.event === 'protection_trip' && ev.relay === 'SHUTDOWN');
}

export function genEventText(ev) {
    if (ev.event === 'refused') return `REFUSED ${ev.command}: ${ev.detail || ''}`;
    if (ev.event === 'command') return `${ev.command} · ${String(ev.to_state || '').replace(/_/g, ' ')} · DAY TANK ${ev.day_tank_pct} %`;
    if (ev.event === 'protection_trip') return `SHUTDOWN · ${ev.detail || ''}`;
    return `${String(ev.event).replace(/_/g, ' ').toUpperCase()} ${ev.condition || ev.cause || ev.detail || ''}`.trim();
}
