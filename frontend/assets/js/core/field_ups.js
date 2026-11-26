/**
 * L4 (2026-11-26): field view of the UPS bank of one path (Layer 2,
 * equipment look; ADR-014): the UPS system panel (display, mimic,
 * transfer buttons, the 8 blocks), the external maintenance bypass
 * cabinet (Q1 rectifier input, Q2 static-bypass input, Q4 MIB, Q3 MBB,
 * Kirk locks on MIB / MBB, solenoid key release unit) and the battery
 * cabinet (QF1 with shunt trip and padlock hasp).
 *
 * Same contract as the other field views: upsSvg() once per open,
 * applyUpsState() from GET /api/devices (path summary -> ups_system,
 * UPS block devices), every action is a server call
 * (POST /api/ups-systems/{path}/action). Simulated equipment.
 */
import { escapeHTML } from './sanitize.js';
import { door, fsgDefs, led } from './field_switchgear.js';

const e = (v) => escapeHTML(v === null || v === undefined ? '' : String(v));
const BRK_X = { Q1: 566, Q2: 660, Q4: 754, Q3: 848 };

function upsPanel() {
    const X = 40, Y = 84;
    let chips = '';
    for (let n = 1; n <= 8; n++) {
        chips += `<g class="xu-chip" data-block="${n}" transform="translate(${X + 40 + (n - 1) * 44} ${Y + 456})">`
            + '<rect x="-18" y="-14" width="36" height="28" rx="3"/>'
            + `<text y="-2" text-anchor="middle" class="xu-chip-n">${n}</text>`
            + `<text y="9" text-anchor="middle" class="xu-chip-s" data-txt="b${n}"></text></g>`;
    }
    return door(X, Y, 420, 586, 'fsg-door-upper')
        + `<g class="fsg-nameplate" transform="translate(${X + 30} ${Y + 22})">`
        + '<rect width="250" height="58" rx="2" class="fsg-np-plate"/>'
        + '<circle cx="8" cy="8" r="2.2" class="fsg-rivet"/><circle cx="242" cy="8" r="2.2" class="fsg-rivet"/>'
        + '<circle cx="8" cy="50" r="2.2" class="fsg-rivet"/><circle cx="242" cy="50" r="2.2" class="fsg-rivet"/>'
        + '<text x="125" y="25" class="fsg-np-big" text-anchor="middle" data-txt="np">UPS</text>'
        + '<text x="125" y="39" class="fsg-np-small" text-anchor="middle">8 × 2.5 MW DOUBLE CONVERSION · 480 V</text>'
        + '<text x="125" y="50" class="fsg-np-small" text-anchor="middle">SYSTEM CONTROL PANEL (MODEL)</text></g>'
        + `<g transform="translate(${X + 22} ${Y + 98})"><rect width="376" height="112" rx="5" class="xf-mon"/>`
        + '<rect x="12" y="12" width="352" height="88" rx="2" class="xf-lcd"/>'
        + '<text x="22" y="32" class="xf-lcd-line" data-txt="d1"></text>'
        + '<text x="22" y="52" class="xf-lcd-line" data-txt="d2"></text>'
        + '<text x="22" y="72" class="xf-lcd-line" data-txt="d3"></text>'
        + '<text x="22" y="91" class="xf-lcd-lbl" data-txt="d4"></text></g>'
        // mimic on the door
        + `<g class="xu-mimic" transform="translate(${X + 30} ${Y + 240})">`
        + '<text x="0" y="-8" class="fsg-tiny">SYSTEM MIMIC</text>'
        + '<path class="xu-line" data-seg="in" d="M0 40 H40"/>'
        + '<path class="xu-line" data-seg="rect" d="M40 40 H70"/>'
        + '<rect x="70" y="26" width="56" height="28" rx="3" class="xu-box" data-box="rect"/><text x="98" y="44" class="xu-box-t" text-anchor="middle">RECT</text>'
        + '<path class="xu-line" data-seg="dc" d="M126 40 H160"/>'
        + '<rect x="160" y="26" width="56" height="28" rx="3" class="xu-box" data-box="inv"/><text x="188" y="44" class="xu-box-t" text-anchor="middle">INV</text>'
        + '<path class="xu-line" data-seg="inv" d="M216 40 H260"/>'
        + '<path class="xu-line" data-seg="byp" d="M0 100 H260 V58"/>'
        + '<rect x="248" y="26" width="28" height="28" rx="3" class="xu-box" data-box="ss"/><text x="262" y="44" class="xu-box-t" text-anchor="middle">SS</text>'
        + '<path class="xu-line" data-seg="out" d="M276 40 H360"/>'
        + '<path class="xu-line" data-seg="batt" d="M143 40 V80"/>'
        + '<rect x="128" y="80" width="30" height="16" rx="2" class="xu-box" data-box="batt"/><text x="143" y="92" class="xu-box-t" text-anchor="middle">BATT</text>'
        + '<text x="0" y="34" class="fsg-tiny">Q1</text><text x="0" y="96" class="fsg-tiny">Q2</text><text x="330" y="34" class="fsg-tiny">Q4 →</text>'
        + '<path class="xu-line xu-mbb" data-seg="mbb" d="M0 130 H360"/><text x="150" y="146" class="fsg-tiny">Q3 MAINTENANCE BYPASS</text></g>'
        + `<g class="xu-btn" data-act="to_bypass" role="button" tabindex="0" transform="translate(${X + 110} ${Y + 410})">`
        + '<rect x="-80" y="-18" width="160" height="36" rx="4"/><text y="5" text-anchor="middle">TRANSFER TO BYPASS</text></g>'
        + `<g class="xu-btn" data-act="to_inverter" role="button" tabindex="0" transform="translate(${X + 310} ${Y + 410})">`
        + '<rect x="-80" y="-18" width="160" height="36" rx="4"/><text y="5" text-anchor="middle">TRANSFER TO INVERTER</text></g>'
        + `<text x="${X + 30}" y="${Y + 436}" class="fsg-tiny">UPS BLOCKS</text>` + chips
        + led(X + 80, Y + 520, 'green', 'INVERTER', 'inv')
        + led(X + 160, Y + 520, 'amber', 'BYPASS', 'byp')
        + led(X + 240, Y + 520, 'amber', 'ON BATTERY', 'batt')
        + led(X + 320, Y + 520, 'red', 'LOAD LOST', 'lost');
}

function breaker(id, label, sub) {
    const x = BRK_X[id];
    const kirk = id === 'Q3' || id === 'Q4';
    return `<g class="xu-brk" data-brk="${id}" transform="translate(${x} 150)">`
        + '<rect x="-40" y="0" width="80" height="212" rx="3" class="xu-brk-body"/>'
        + `<text y="18" class="fsg-label xu-light" text-anchor="middle">${id}</text>`
        + `<text y="30" class="fsg-tiny xu-light" text-anchor="middle">${label}</text>`
        + `<text y="40" class="fsg-tiny xu-light" text-anchor="middle">${sub}</text>`
        + '<g transform="translate(0 60)"><rect x="-30" y="-12" width="60" height="24" rx="2" class="fsg-window"/>'
        + '<rect x="-27" y="-9" width="54" height="18" class="fsg-flag-face xu-flag"/>'
        + '<text y="4.5" class="fsg-flag-txt" text-anchor="middle" data-txt="flag"></text></g>'
        + `<g class="xu-handle" data-act="brk" data-brk="${id}" role="button" tabindex="0" transform="translate(0 132)">`
        + '<rect x="-20" y="-30" width="40" height="60" rx="4" class="xg-brk-body"/>'
        + '<g class="xu-handle-lever"><rect x="-9" y="-24" width="18" height="22" rx="3" class="xu-lever"/></g>'
        + '<text x="0" y="-34" class="fsg-tiny xu-light" text-anchor="middle">ON</text>'
        + '<text x="0" y="42" class="fsg-tiny xu-light" text-anchor="middle">OFF</text></g>'
        + (kirk ? `<g class="xf-lock" data-act="lock" data-lock="${id === 'Q3' ? 'MBB' : 'MIB'}" role="button" tabindex="0" transform="translate(0 194)" >`
            + '<rect x="-24" y="-16" width="48" height="32" fill="transparent"/>'
            + '<circle r="12" class="xf-lock-body"/><circle r="8" class="xf-lock-cyl"/>'
            + '<g class="xf-lock-plug"><rect x="-1.5" y="-6" width="3" height="12" rx="1" class="xf-lock-slot"/></g>'
            + '<g class="xf-lock-key" transform="translate(24 0) rotate(180) scale(.7)"><circle r="7" class="xf-key-bow"/>'
            + '<rect x="6" y="-2" width="20" height="4" class="xf-key-blade"/></g></g>' : '')
        + '</g>';
}

function bypassCabinet() {
    const X = 510, Y = 84;
    return door(X, Y, 420, 372, 'fsg-door-upper')
        + `<text x="${X + 22}" y="${Y + 24}" class="fsg-label">EXTERNAL MAINTENANCE BYPASS CABINET</text>`
        + `<text x="${X + 22}" y="${Y + 36}" class="fsg-tiny">MAKE BEFORE BREAK · KEY INTERLOCKED (MODEL)</text>`
        // SKRU
        + `<g class="xu-skru" data-act="skru" role="button" tabindex="0" transform="translate(${X + 340} ${Y + 32})">`
        + '<rect x="-56" y="-18" width="112" height="44" rx="4" class="xu-skru-body"/>'
        + '<g class="fsg-led" data-led="skru" data-colour="green" transform="translate(-36 4)"><circle r="9" class="fsg-led-bezel"/><circle r="6" class="fsg-led-lens"/></g>'
        + '<circle cx="14" cy="4" r="11" class="xf-lock-body"/><circle cx="14" cy="4" r="7" class="xf-lock-cyl"/>'
        + '<g class="xu-skru-key" transform="translate(38 4) rotate(180) scale(.7)"><circle r="7" class="xf-key-bow"/><rect x="6" y="-2" width="20" height="4" class="xf-key-blade"/></g>'
        + '<text y="-8" x="-36" class="xu-skru-t" text-anchor="middle">OK TO XFER</text>'
        + '<text y="-8" x="14" class="xu-skru-t" text-anchor="middle">SKRU</text></g>'
        + breaker('Q1', 'RECTIFIER', 'INPUT (UIB)')
        + breaker('Q2', 'BYPASS', 'INPUT (SSIB)')
        + breaker('Q4', 'MAINT. ISOL.', 'OUTPUT (MIB)')
        + breaker('Q3', 'MAINT. BYPASS', 'WRAP (MBB)')
        + `<g transform="translate(${X + 22} ${Y + 318})"><rect width="160" height="42" rx="3" class="xf-tray"/>`
        + '<text x="80" y="14" class="fsg-tiny xu-light" text-anchor="middle">KEYS IN HAND</text>'
        + '<text x="80" y="33" class="xu-hand" data-txt="hand" text-anchor="middle"></text></g>'
        + `<text x="${X + 200}" y="${Y + 336}" class="fsg-tiny" data-txt="feed"></text>`
        + `<text x="${X + 200}" y="${Y + 350}" class="fsg-tiny" data-txt="feed2"></text>`;
}

function batteryCabinet() {
    const X = 510, Y = 470;
    return door(X, Y, 420, 200, 'fsg-door-upper')
        + `<text x="${X + 22}" y="${Y + 24}" class="fsg-label">BATTERY CABINET · QF1</text>`
        + `<text x="${X + 22}" y="${Y + 36}" class="fsg-tiny">DC BREAKER · SHUNT TRIP COIL · LOTO HASP</text>`
        + `<g class="xu-brk" data-brk="QF1" transform="translate(${X + 80} ${Y + 52})">`
        + '<rect x="-46" y="0" width="92" height="130" rx="3" class="xu-brk-body"/>'
        + '<g transform="translate(0 24)"><rect x="-30" y="-12" width="60" height="24" rx="2" class="fsg-window"/>'
        + '<rect x="-27" y="-9" width="54" height="18" class="fsg-flag-face xu-flag"/>'
        + '<text y="4.5" class="fsg-flag-txt" text-anchor="middle" data-txt="flag"></text></g>'
        + '<g class="xu-handle" data-act="brk" data-brk="QF1" role="button" tabindex="0" transform="translate(0 82)">'
        + '<rect x="-20" y="-30" width="40" height="60" rx="4" class="xg-brk-body"/>'
        + '<g class="xu-handle-lever"><rect x="-9" y="-24" width="18" height="22" rx="3" class="xu-lever"/></g></g></g>'
        + `<g class="fsg-hasp xu-hasp" data-act="hasp" role="button" tabindex="0" transform="translate(${X + 164} ${Y + 134})">`
        + '<rect x="-12" y="-10" width="24" height="26" rx="3" class="fsg-hasp-plate"/><circle cy="2" r="4" class="fsg-hasp-hole"/>'
        + '<g class="xu-padlock"><path d="M-7 -2 L-7 -10 Q0 -20 7 -10 L7 -2" class="fsg-shackle"/>'
        + '<rect x="-10" y="-3" width="20" height="17" rx="2.5" class="fsg-lock-body"/></g>'
        + '<text y="34" class="fsg-tiny" text-anchor="middle">HASP</text>'
        + '<text y="44" class="fsg-tiny" text-anchor="middle" data-txt="lockname"></text></g>'
        + `<g transform="translate(${X + 210} ${Y + 56})"><rect width="190" height="80" rx="3" class="xf-lcd"/>`
        + '<text x="10" y="20" class="xf-lcd-line" data-txt="bt1"></text>'
        + '<text x="10" y="40" class="xf-lcd-line" data-txt="bt2"></text>'
        + '<text x="10" y="60" class="xf-lcd-line" data-txt="bt3"></text></g>'
        + `<text x="${X + 210}" y="${Y + 160}" class="fsg-tiny">Strings, jars and H2: diagnostics lot (L5)</text>`;
}

/** Static SVG of the UPS bank field view for one path. */
export function upsSvg(path) {
    const P = e(String(path || 'a').toUpperCase());
    const frame = '<rect x="20" y="20" width="940" height="672" rx="4" class="fsg-frame"/>'
        + '<rect x="20" y="20" width="940" height="52" rx="4" class="fsg-topcap"/>'
        + `<text x="44" y="44" class="fsg-head">UPS BANK · PATH ${P}</text>`
        + '<text x="44" y="61" class="fsg-tiny fsg-light">480 V AC · DOUBLE CONVERSION · EXTERNAL MAINTENANCE BYPASS · SIMULATED EQUIPMENT</text>'
        + '<line x1="490" y1="76" x2="490" y2="688" class="fsg-split"/>';
    return `<svg class="fsg-svg xu-svg" viewBox="0 0 980 712" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="UPS bank field view, path ${P}">`
        + fsgDefs() + `<g filter="url(#fsg-powder)">${frame}`
        + `<g class="fsg-section xu-section" data-section="UPS">${upsPanel()}${bypassCabinet()}${batteryCabinet()}</g>`
        + '</g></svg>';
}

function setText(root, key, text) {
    const el = root.querySelector(`[data-txt="${key}"]`);
    if (el) el.textContent = text;
}

const SHORT = { DOUBLE_CONVERSION: 'VFI', DYNAMIC_ONLINE: 'DOL', STATIC_BYPASS: 'BYP', ISOLATED: 'ISO' };

/** Write the path summary and its UPS blocks into the view. */
export function applyUpsState(root, summary, blocks = []) {
    const us = summary && summary.ups_system;
    if (!root || !us) return;
    const sec = root.querySelector('[data-section="UPS"]');
    if (!sec) return;
    const b = us.breakers || {};
    sec.setAttribute('data-mode', us.mode);
    sec.setAttribute('data-source', us.load_source);
    sec.setAttribute('data-lost', summary.load_lost ? '1' : '0');
    setText(sec, 'np', `UPS-${String(summary.path || '').toUpperCase()}`);
    setText(sec, 'd1', `MODE ${String(us.mode).replace('_', ' ')} · LOAD ON ${String(us.load_source).replace('_', ' ')}`);
    setText(sec, 'd2', `IT LOAD ${(Number(summary.it_load_kw) / 1000).toFixed(2)} MW · ${summary.ups_in_service} / ${summary.ups_total} BLOCKS`);
    setText(sec, 'd3', summary.load_lost ? 'CRITICAL LOAD LOST'
        : (summary.on_battery ? `ON BATTERY · ${summary.battery_runtime_min} min` : `SUPPLY: ${String(summary.load_feed || '').toUpperCase()}`));
    setText(sec, 'd4', `BATTERY ${summary.battery_soc_pct} % · BYPASS ${us.bypass_live ? 'AVAILABLE' : 'NOT AVAILABLE'} · RECT ${us.rect_live ? 'ON' : 'OFF'}`);
    const seg = {
        in: us.rect_live, rect: us.rect_live, dc: us.rect_live || (b.QF1 && summary.on_battery),
        inv: us.mode === 'INVERTER' || us.mode === 'MIXED', byp: us.bypass_live,
        out: b.Q4 && us.load_source !== 'NONE' && us.load_source !== 'MAINTENANCE_BYPASS',
        batt: b.QF1, mbb: b.Q3 && us.load_source === 'MAINTENANCE_BYPASS',
    };
    for (const [k, on] of Object.entries(seg)) {
        const el = sec.querySelector(`[data-seg="${k}"]`);
        if (el) el.setAttribute('data-live', on ? '1' : '0');
    }
    for (const id of ['Q1', 'Q2', 'Q3', 'Q4', 'QF1']) {
        const g = sec.querySelector(`.xu-brk[data-brk="${id}"]`);
        if (!g) continue;
        g.setAttribute('data-closed', b[id] ? '1' : '0');
        setText(g, 'flag', b[id] ? 'I  ON' : 'O  OFF');
    }
    const locks = { MIB: us.mib_unlocked, MBB: us.mbb_unlocked };
    for (const [k, unlocked] of Object.entries(locks)) {
        const g = sec.querySelector(`[data-lock="${k}"]`);
        if (g) {
            g.setAttribute('data-key', unlocked ? '1' : '0');
            g.setAttribute('data-turned', unlocked ? '0' : '1');
        }
    }
    sec.setAttribute('data-skru-key', String(us.skru_keys));
    const lamp = sec.querySelector('[data-led="skru"]');
    if (lamp) lamp.setAttribute('data-on', us.skru_lamp ? '1' : '0');
    setText(sec, 'hand', us.hand_keys ? `${'⚿ '.repeat(us.hand_keys).trim()} ${us.hand_keys} KEY${us.hand_keys > 1 ? 'S' : ''}` : 'NONE');
    setText(sec, 'feed', `LOAD FED BY: ${String(us.load_source).replace('_', ' ')}`);
    setText(sec, 'feed2', us.on_maintenance_bypass ? 'MBB CLOSED: NO BATTERY BEHIND THE LOAD' : '');
    sec.setAttribute('data-padlock', us.qf1_padlock ? '1' : '0');
    setText(sec, 'lockname', us.qf1_padlock ? String(us.qf1_padlock).slice(0, 12) : '');
    setText(sec, 'bt1', `QF1 ${b.QF1 ? 'CLOSED' : 'OPEN'}${us.qf1_padlock ? ' · LOCKED OUT' : ''}`);
    setText(sec, 'bt2', `SOC ${summary.battery_soc_pct} % (MODEL)`);
    setText(sec, 'bt3', b.QF1 ? (summary.on_battery ? 'DISCHARGING' : 'FLOAT / RECHARGE') : 'DISCONNECTED');
    const leds = { inv: us.mode === 'INVERTER', byp: us.mode === 'STATIC_BYPASS' || us.mode === 'MIXED',
        batt: summary.on_battery, lost: summary.load_lost };
    for (const [k, on] of Object.entries(leds)) {
        const g = sec.querySelector(`[data-led="${k}"]`);
        if (g) g.setAttribute('data-on', on ? '1' : '0');
    }
    for (const d of blocks) {
        const n = Number(String(d.id).slice(-2));
        const chip = sec.querySelector(`[data-block="${n}"]`);
        if (!chip) continue;
        chip.setAttribute('data-state', d.state);
        setText(chip, `b${n}`, SHORT[d.state] || '');
    }
}

/** Map a click to {action} or null, given the UPS system state. */
export function resolveUpsClick(target, us) {
    const el = target && target.closest ? target.closest('[data-act]') : null;
    if (!el || !us) return null;
    const act = el.getAttribute('data-act');
    const b = us.breakers || {};
    if (act === 'to_bypass') return { action: 'SYSTEM_TO_BYPASS', kind: 'button' };
    if (act === 'to_inverter') return { action: 'SYSTEM_TO_INVERTER', kind: 'button' };
    if (act === 'brk') {
        const id = el.getAttribute('data-brk');
        return { action: `${b[id] ? 'OPEN' : 'CLOSE'}_${id}`, kind: 'breaker' };
    }
    if (act === 'lock') {
        const k = el.getAttribute('data-lock');
        const unlocked = k === 'MIB' ? us.mib_unlocked : us.mbb_unlocked;
        return { action: `${unlocked ? 'LOCK' : 'UNLOCK'}_${k}`, kind: 'key' };
    }
    if (act === 'skru') return { action: us.skru_keys ? 'SKRU_RELEASE' : 'SKRU_CAPTURE', kind: 'key' };
    if (act === 'hasp') return { action: us.qf1_padlock ? 'UNPADLOCK_QF1' : 'PADLOCK_QF1', kind: 'key' };
    return null;
}

export function isUpsEvent(ev) {
    return ev.equipment === 'ups' || /@UPS_[AB]$/.test(String(ev.command || ''))
        || ['qf1_shunt_trip', 'load_lost', 'load_restored'].includes(ev.event);
}

export function upsEventText(ev) {
    if (ev.event === 'refused') return `REFUSED ${ev.command}: ${ev.detail || ''}`;
    if (ev.event === 'command') return `${ev.command} · ${String(ev.mode || '').replace('_', ' ')} · ${ev.load_feed || ''}`;
    return `${String(ev.event).replace(/_/g, ' ').toUpperCase()} ${ev.detail || ''}`.trim();
}
