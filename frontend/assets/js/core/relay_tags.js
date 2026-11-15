/**
 * T4 (2026-11-15): protective relay indicators on the Power SLD.
 *
 * Honest scope: the simulator models two functions only.
 *   27  incomer undervoltage: real in the simulation (trips 52-U).
 *   25  sync check: real only in closed-transition TRAINING MODE.
 * 87T (transformer differential), 50/51 (incomer overcurrent) and 59
 * (overvoltage) are drawn as identification tags of the design lineup:
 * no settings, no coordination, no trip logic exists for them, and the
 * tag says so. Device numbers per IEEE C37.2.
 */

export const RELAYS = Object.freeze([
    { ansi: '27', name: 'Incomer undervoltage', modelled: true },
    { ansi: '25', name: 'Sync check (training mode only)', modelled: true },
    { ansi: '50/51', name: 'Incomer overcurrent', modelled: false },
    { ansi: '59', name: 'Incomer overvoltage', modelled: false },
    { ansi: '87T', name: 'Transformer differential', modelled: false },
]);

const NOT_MODELLED = { state: 'N/M', tone: 'id', note: 'not modelled: identification only, no settings or trip logic' };

/**
 * Relay states for one path.
 * @param {string} path 'a' | 'b'
 * @param {object|null} plant GET /api/devices snapshot (live), or null
 * @param {object|null} grid DAG grid (What-If / no plant)
 * @returns {Array<{ansi,name,state,tone,note}>} tone: ok | warn | crit | off | id
 */
export function relayStates(path, plant, grid) {
    const p = String(path || '').toLowerCase();
    const summary = plant && Array.isArray(plant.paths)
        ? plant.paths.find((s) => String(s.path).toLowerCase() === p) : null;
    const xfer = plant && Array.isArray(plant.devices)
        ? plant.devices.find((d) => d.kind === 'transfer' && String(d.path).toLowerCase() === p) : null;

    let r27;
    if (summary) {
        r27 = summary.utility_ok === false
            ? { state: 'PICKED UP', tone: 'crit', note: 'no utility voltage on the incomer' }
            : { state: 'NORMAL', tone: 'ok', note: 'utility voltage present' };
    } else if (grid && grid['util_' + p]) {
        r27 = grid['util_' + p].tripped
            ? { state: 'PICKED UP', tone: 'crit', note: 'What-If: utility tripped in the sandbox' }
            : { state: 'NORMAL', tone: 'ok', note: 'What-If sandbox' };
    } else {
        r27 = { state: '—', tone: 'off', note: 'no plant data' };
    }

    const sync = xfer && xfer.synchro;
    let r25;
    if (!sync || !sync.enabled) {
        r25 = { state: 'OFF', tone: 'off', note: 'closed-transition training mode is off (A3 design: open transition)' };
    } else if (!sync.live) {
        r25 = { state: 'IDLE', tone: 'off', note: 'not islanded: no phase drift to supervise' };
    } else if (sync.close_armed) {
        r25 = { state: 'ARMED', tone: 'warn', note: 'supervised close armed: waiting for the window' };
    } else if (sync.permissive) {
        r25 = { state: 'PERMIT', tone: 'ok', note: 'angle and slip inside the window' };
    } else {
        r25 = { state: 'BLOCK', tone: 'warn', note: 'angle or slip outside the window' };
    }

    return RELAYS.map((r) => {
        const s = r.ansi === '27' ? r27 : (r.ansi === '25' ? r25 : NOT_MODELLED);
        return { ansi: r.ansi, name: r.name, ...s };
    });
}

const W = 38;
const H = 24;
const GAP = 3;

/** SVG row of relay chips for one path (states filled by applyRelays). */
export function relayRowSvg(suffix, x, y) {
    const chips = RELAYS.map((r, i) => {
        const cx = x + i * (W + GAP);
        return `<g class="pf-relay" data-relay="${suffix}:${r.ansi}" data-tone="${r.modelled ? 'off' : 'id'}">`
            + `<rect class="pf-relay-box" x="${cx}" y="${y}" width="${W}" height="${H}" rx="2"/>`
            + `<text class="pf-relay-num" x="${cx + W / 2}" y="${y + 10}" text-anchor="middle">${r.ansi}</text>`
            + `<text class="pf-relay-state" x="${cx + W / 2}" y="${y + 20}" text-anchor="middle">${r.modelled ? '—' : 'N/M'}</text>`
            + `<title>ANSI ${r.ansi} ${r.name}</title></g>`;
    }).join('');
    return `<g class="pf-relays" data-relays="${suffix}">`
        + `<text class="pf-relay-cap" x="${x}" y="${y - 4}">RELAYS · 52-U / XFMR · MODEL</text>${chips}</g>`;
}

/** Paint the states into an SVG root that holds relayRowSvg rows. */
export function applyRelays(root, path, states) {
    if (!root) return;
    for (const s of states) {
        const g = root.querySelector(`[data-relay="${path}:${CSS_ESC(s.ansi)}"]`);
        if (!g) continue;
        g.setAttribute('data-tone', s.tone);
        const st = g.querySelector('.pf-relay-state');
        if (st) st.textContent = s.state;
        const t = g.querySelector('title');
        if (t) t.textContent = `ANSI ${s.ansi} ${s.name}: ${s.state} (${s.note})`;
    }
}

function CSS_ESC(v) {
    return String(v).replace(/["\\]/g, '\\$&');
}
