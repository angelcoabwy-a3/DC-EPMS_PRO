/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — frontend/assets/js/core/phase2_live.js
 *
 * Lot 11 (2026-11-27): live numbers on the Building D (Phase 2) branch
 * of the Power SLD. Two sources, both simulated:
 *   - the telemetry stream (Hermes 'telemetry' frames): per-path
 *     channels '<asset>:<metric>' with last_emission values; since lot
 *     12 the simulator pins them to the Building D plant state;
 *   - the Building D plant block of GET /api/devices ('building_d'):
 *     breaker states, source, farm, SOC.
 * Output: { metricKey: text } for the SLD <text data-sld-metric=...>
 * nodes drawn by views/power.js (_flatPhase2).
 *
 * S-VOCAB-01: kV labels belong to the 35 kV 3-phase AC feed only; the
 * 800 VDC bus is unipolar (voltage_v_dc_bus) and never says "phase".
 * Pure module: no DOM, no fetch.
 * ════════════════════════════════════════════════════════════════ */

const PATHS = [
    { sfx: '', ch: '', bess: 'bess_d_01', sscb: 'sscb_d_01', key: 'a' },
    { sfx: '_b', ch: '_b', bess: 'bess_d_b_01', sscb: 'sscb_d_b_01', key: 'b' },
];

function _val(channels, id) {
    const c = channels ? channels[id] : undefined;
    const v = c && typeof c === 'object' ? c.last_emission : c;
    return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

function _fmt(v, digits) {
    return Number(v).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Text for the SLD metrics from a telemetry channel map. Keys whose
 *  channel is absent are left out (the drawing keeps its placeholder). */
export function metricsFromChannels(channels) {
    const out = {};
    if (!channels || typeof channels !== 'object') return out;
    for (const p of PATHS) {
        const kv = _val(channels, `utility_feed_d${p.ch}:utility_voltage_kv`);
        if (kv !== null) out[`util_d${p.sfx}-kv`] = kv > 0.5 ? `${_fmt(kv, 1)} kV` : '0 kV · LOST';
        const mw = _val(channels, `mv_rectifier_d${p.ch}:rect_load_mw`);
        const eff = _val(channels, `mv_rectifier_d${p.ch}:rect_efficiency_ratio`);
        if (mw !== null) {
            out[`mv_rect_d${p.sfx}-load`] = `${_fmt(Math.max(0, mw), 1)} MW`
                + (eff !== null && mw > 0.05 ? ` · η ${_fmt(eff * 100, 1)} %` : '');
            if (eff !== null && eff > 0) {
                out[`util_d${p.sfx}-kw`] = mw > 0.05 ? `AC in ${_fmt(mw / eff, 1)} MW` : 'AC in 0 MW';
            }
        }
        const v = _val(channels, `main_bus_dc_d${p.ch}:voltage_v_dc_bus`);
        if (v !== null) out[`dc_bus_d${p.sfx}-v`] = v > 1 ? `${_fmt(v, 0)} VDC` : '0 VDC · DEAD';
        const soc = _val(channels, `${p.bess}:bess_soc_pct`);
        const amps = _val(channels, `${p.bess}:bess_dc_current_a`);
        if (soc !== null) {
            let flow = 'idle';
            if (amps !== null && amps > 50) flow = `discharging ${_fmt(amps, 0)} A`;
            else if (amps !== null && amps < -50) flow = `charging ${_fmt(-amps, 0)} A`;
            // Simulator jitter can read a hair above 100 % or below 0.
            const pct = Math.min(100, Math.max(0, soc));
            out[`bess_d${p.sfx}-soc`] = `SOC ${_fmt(pct, 1)} % · ${flow}`;
        }
        const tj = _val(channels, `${p.sscb}:sscb_junction_T_c`);
        if (tj !== null) out[`sscb_d${p.sfx}-clear`] = `Tj ${_fmt(tj, 0)} °C · 1-100 µs`;
    }
    return out;
}

/** Text for the SLD metrics from the Building D plant block. */
export function metricsFromPlant(bd) {
    const out = {};
    if (!bd || !Array.isArray(bd.paths)) return out;
    for (const p of bd.paths) {
        const sfx = p.path === 'b' ? '_b' : '';
        const trip = p.sscb === 'TRIPPED' && p.sscb_trip
            ? ` (${String(p.sscb_trip).replace(/_/g, ' ').toLowerCase()})` : '';
        out[`sscb_d${sfx}-state`] = `${p.sscb}${trip}`;
    }
    return out;
}

/** Hall caption: who carries Building D right now. */
export function hallCaption(bd) {
    if (!bd || !Array.isArray(bd.paths)) return null;
    if (bd.load_lost) return 'HALL LOAD LOST · both 800 VDC buses dark';
    const parts = bd.paths.map((p) => `${p.label || p.path} ${_fmt((p.carrying_kw || 0) / 1000, 1)} MW`);
    const step = bd.load_step && bd.load_step.active ? ' · load step active' : '';
    return `${parts.join(' · ')}${step}`;
}
