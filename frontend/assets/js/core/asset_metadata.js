/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — frontend/assets/js/core/asset_metadata.js
 *
 * Realistic industrial metadata for the 18 SLD assets — Phase 1
 * (deployed Buildings A/B at A3-Alpha Toronto Area). Replaces the
 * static `--- kW` placeholders with model + rating + last-PM +
 * vendor manual references.
 *
 * Source for ratings:
 *   - NVIDIA GB200 NVL72 reference design (2024 spec sheet)
 *   - Schneider Galaxy VX datasheet (2025 v4.1)
 *   - Eaton 2.5 MVA Dry-Type catalogue (vector group + impedance)
 *   - ASCO 7000-Series ATS spec (NFPA 110 Type 10 conformance)
 *   - Cummins QSK60-G6 standby genset technical data sheet
 *   - C&D Technologies VRLA Pure Lead datasheet
 *   - Server Technology PRO4 RPP-class datasheet
 *   - Starline Track Busway 800A spec
 * ════════════════════════════════════════════════════════════════ */

const _common = (path) => ({
    util:    { type: 'Utility Feed',                     model: path === 'A' ? 'Hydro One MV Feed (North)' : 'Hydro One MV Feed (South)',
               rating: '27.5 kV three-phase · 50 MVA available',
               sparkline: { unit: 'MW',  baseline: 14.8, range: 1.4,  color: '#00E5FF' } },
    xfmr:    { type: 'Step-Down Transformer',            model: 'Eaton 2.5 MVA Dry-Type',
               rating: '27.5 kV → 480 V · 2.5 MVA',
               sparkline: { unit: '°C',  baseline: 64,   range: 6,    color: '#FFB300' } },
    genset:  { type: 'Standby Generator',                model: 'Cummins QSK60-G6 · diesel',
               rating: '2.0 MW · 480 V 3-phase · NFPA 110 Type 10',
               sparkline: { unit: 'rpm', baseline: 0,    range: 0,    color: '#FFB300' } },
    ats:     { type: 'Automatic Transfer Switch',        model: 'ASCO 7000-Series · 4-pole bypass-isolation',
               rating: '480 V · 1600 A · NFPA 110 Type 10 (10 s nameplate, fast-fwd 2 s in sim)',
               sparkline: { unit: '',    baseline: 1,    range: 0,    color: '#00E5FF' } },
    ups:     { type: 'Uninterruptible Power Supply',     model: 'Schneider Galaxy VX 750 kVA · double-conversion',
               rating: '480 V · 750 kW · η ≥ 96.5% online · 5-min holdup',
               sparkline: { unit: 'kW',  baseline: 612,  range: 24,   color: '#00E5FF' } },
    batt:    { type: 'Battery Bank',                     model: 'C&D Technologies VRLA Pure Lead-Tin',
               rating: '540 VDC · 264 cells · 5-min @ 750 kW',
               sparkline: { unit: '%',   baseline: 100,  range: 0,    color: '#FFB300' } },
    rpp:     { type: 'Remote Power Panel',               model: 'Server Technology PRO4 · 24-circuit',
               rating: '480 V · 400 A · per-circuit metering',
               sparkline: { unit: 'kW',  baseline: 198,  range: 12,   color: '#00E5FF' } },
    busway:  { type: 'Starline Track Busway',            model: 'Starline T5 · 800 A plug-in tap-off',
               rating: '480 V · 800 A · 24 m run · GB200 NVL72 tap-offs',
               sparkline: { unit: 'kW',  baseline: 410,  range: 18,   color: '#00E5FF' } },
});

// Per-asset details + manuals + maintenance metadata (overlayed on _common)
export const ASSET_METADATA = {
    util_a: {
        ..._common('A').util,
        label: 'Utility North',
        details: [
            { k: 'Source',           v: 'Hydro One — North Substation' },
            { k: 'SLA',              v: 'Tier IV: 99.995 % (43.8 min/yr)' },
            { k: 'Last Outage',      v: '2026-01-14 (transient 4 ms)' },
            { k: 'Voltage Class',    v: '27.5 kV three-phase AC' },
        ],
        manuals: ['MOP-UTIL-001 — Utility transfer test (annual)'],
    },
    xfmr_a: {
        ..._common('A').xfmr,
        label: 'XFMR A',
        details: [
            { k: 'Impedance (Z%)',   v: '5.75 %' },
            { k: 'Cooling',          v: 'AFWF (forced air + water cooled)' },
            { k: 'Vector Group',     v: 'Dyn11' },
            { k: 'Insulation Class', v: 'F (155 °C rise)' },
            { k: 'Last PM',          v: '2026-02-20 — oil sample PASS' },
        ],
        manuals: ['MOP-XFMR-001 — Hot-spot infrared scan (semi-annual)'],
    },
    genset_a: {
        ..._common('A').genset,
        label: 'Genset A',
        details: [
            { k: 'Class',            v: 'NFPA 110 Type 10 (10 s start, ≤30 s on bus)' },
            { k: 'Fuel Capacity',    v: '5,000 gal — 72 h @ full load' },
            { k: 'Hours (life)',     v: '142 / 25,000 h MTBO' },
            { k: 'Last Run Test',    v: '2026-04-15 (30 min @ 100 % load)' },
            { k: 'Cooling',          v: 'Closed-loop water + radiator' },
        ],
        manuals: ['MOP-GEN-WEEKLY-001 — Weekly no-load start (5 min)'],
    },
    ats_a: {
        ..._common('A').ats,
        label: 'ATS-A',
        details: [
            { k: 'Transfer Time',    v: '2.0 s (10 s nameplate, fast-fwd in sim)' },
            { k: 'Inhibit Logic',    v: 'Bypass-isolation' },
            { k: 'Cycles (life)',    v: '847 / 10,000 design' },
            { k: 'Last Test',        v: '2026-04-08 (monthly transfer PASS)' },
        ],
        manuals: ['MOP-ATS-MONTHLY-001 — Monthly transfer test'],
    },
    ups_a: {
        ..._common('A').ups,
        label: 'UPS Galaxy VX A',
        details: [
            { k: 'Topology',         v: 'AC → DC → AC (true online)' },
            { k: 'Firmware',         v: 'v4.1.2 (2026-03)' },
            { k: 'Battery',          v: '480 V VRLA · 5 min @ 750 kW' },
            { k: 'Last PM',          v: '2026-03-15 — battery impedance PASS' },
            { k: 'Anomalies (30 d)', v: '0' },
        ],
        manuals: ['MOP-UPS-001 — Galaxy VX bypass + battery swap'],
    },
    batt_a: {
        ..._common('A').batt,
        label: 'Batt VRLA-A',
        details: [
            { k: 'Cell Count',          v: '264 cells (40 strings × 6.6 V)' },
            { k: 'Chemistry',           v: 'VRLA Pure Lead-Tin' },
            { k: 'Design Life',         v: '10 yr @ 25 °C ambient' },
            { k: 'Last Discharge Test', v: '2026-02-12 (capacity 98 %)' },
        ],
        manuals: ['MOP-BATT-001 — Quarterly impedance test'],
    },
    rpp_a1: {
        ..._common('A').rpp,
        label: 'RPP-A1',
        details: [
            { k: 'Branch Circuits',  v: '24 × 30 A' },
            { k: 'Monitoring',       v: 'Per-circuit kWh + power factor' },
            { k: 'Outlets',          v: 'IEC 60309 32 A blue × 24' },
            { k: 'Last Inspection',  v: '2026-04-01 (thermography PASS)' },
        ],
        manuals: ['MOP-RPP-001 — Quarterly thermography scan'],
    },
    rpp_a2: {
        ..._common('A').rpp,
        label: 'RPP-A2',
        details: [
            { k: 'Branch Circuits',  v: '24 × 30 A' },
            { k: 'Monitoring',       v: 'Per-circuit kWh + power factor' },
            { k: 'Outlets',          v: 'IEC 60309 32 A blue × 24' },
            { k: 'Last Inspection',  v: '2026-04-01 (thermography PASS)' },
        ],
        manuals: ['MOP-RPP-001 — Quarterly thermography scan'],
    },
    busway_a: {
        ..._common('A').busway,
        label: 'Busway A · GB200 NVL72',
        details: [
            { k: 'Tap-offs',         v: '118 GB200 NVL72 racks deployed' },
            { k: 'Tap Spacing',      v: '0.6 m (rack pitch)' },
            { k: 'Length',           v: '24 m / hall' },
            { k: 'Last Tightening',  v: '2026-03-30 (annual torque check)' },
        ],
        manuals: ['MOP-BUSWAY-001 — Annual tightening torque (45 N·m)'],
    },

    // Path B — same models, mirror metadata
    util_b: {
        ..._common('B').util,
        label: 'Utility South',
        details: [
            { k: 'Source',           v: 'Hydro One — South Substation' },
            { k: 'SLA',              v: 'Tier IV: 99.995 % (43.8 min/yr)' },
            { k: 'Last Outage',      v: 'none (12 mo)' },
            { k: 'Voltage Class',    v: '27.5 kV three-phase AC' },
        ],
        manuals: ['MOP-UTIL-001 — Utility transfer test (annual)'],
    },
    xfmr_b: {
        ..._common('B').xfmr,
        label: 'XFMR B',
        details: [
            { k: 'Impedance (Z%)',   v: '5.75 %' },
            { k: 'Cooling',          v: 'AFWF' },
            { k: 'Vector Group',     v: 'Dyn11' },
            { k: 'Insulation Class', v: 'F (155 °C rise)' },
            { k: 'Last PM',          v: '2026-02-22 — oil sample PASS' },
        ],
        manuals: ['MOP-XFMR-001 — Hot-spot infrared scan'],
    },
    genset_b: {
        ..._common('B').genset,
        label: 'Genset B',
        details: [
            { k: 'Class',            v: 'NFPA 110 Type 10' },
            { k: 'Fuel Capacity',    v: '5,000 gal — 72 h @ full load' },
            { k: 'Hours (life)',     v: '156 / 25,000 h MTBO' },
            { k: 'Last Run Test',    v: '2026-04-15 (30 min @ 100 % load)' },
            { k: 'Cooling',          v: 'Closed-loop water + radiator' },
        ],
        manuals: ['MOP-GEN-WEEKLY-001 — Weekly no-load start'],
    },
    ats_b: {
        ..._common('B').ats,
        label: 'ATS-B',
        details: [
            { k: 'Transfer Time',    v: '2.0 s (sim fast-fwd)' },
            { k: 'Inhibit Logic',    v: 'Bypass-isolation' },
            { k: 'Cycles (life)',    v: '892 / 10,000 design' },
            { k: 'Last Test',        v: '2026-04-08 (monthly PASS)' },
        ],
        manuals: ['MOP-ATS-MONTHLY-001 — Monthly transfer test'],
    },
    ups_b: {
        ..._common('B').ups,
        label: 'UPS Galaxy VX B',
        details: [
            { k: 'Topology',         v: 'AC → DC → AC' },
            { k: 'Firmware',         v: 'v4.1.2 (2026-03)' },
            { k: 'Battery',          v: '480 V VRLA · 5 min @ 750 kW' },
            { k: 'Last PM',          v: '2026-03-15 — battery impedance PASS' },
            { k: 'Anomalies (30 d)', v: '0' },
        ],
        manuals: ['MOP-UPS-001 — Galaxy VX bypass + battery swap'],
    },
    batt_b: {
        ..._common('B').batt,
        label: 'Batt VRLA-B',
        details: [
            { k: 'Cell Count',          v: '264 cells (40 strings × 6.6 V)' },
            { k: 'Chemistry',           v: 'VRLA Pure Lead-Tin' },
            { k: 'Design Life',         v: '10 yr @ 25 °C ambient' },
            { k: 'Last Discharge Test', v: '2026-02-12 (capacity 99 %)' },
        ],
        manuals: ['MOP-BATT-001 — Quarterly impedance test'],
    },
    rpp_b1: {
        ..._common('B').rpp,
        label: 'RPP-B1',
        details: [
            { k: 'Branch Circuits',  v: '24 × 30 A' },
            { k: 'Monitoring',       v: 'Per-circuit kWh + PF' },
            { k: 'Outlets',          v: 'IEC 60309 32 A blue × 24' },
            { k: 'Last Inspection',  v: '2026-04-01' },
        ],
        manuals: ['MOP-RPP-001 — Quarterly thermography'],
    },
    rpp_b2: {
        ..._common('B').rpp,
        label: 'RPP-B2',
        details: [
            { k: 'Branch Circuits',  v: '24 × 30 A' },
            { k: 'Monitoring',       v: 'Per-circuit kWh + PF' },
            { k: 'Outlets',          v: 'IEC 60309 32 A blue × 24' },
            { k: 'Last Inspection',  v: '2026-04-01' },
        ],
        manuals: ['MOP-RPP-001 — Quarterly thermography'],
    },
    busway_b: {
        ..._common('B').busway,
        label: 'Busway B · GB200 NVL72',
        details: [
            { k: 'Tap-offs',         v: '118 GB200 NVL72 racks deployed' },
            { k: 'Tap Spacing',      v: '0.6 m (rack pitch)' },
            { k: 'Length',           v: '24 m / hall' },
            { k: 'Last Tightening',  v: '2026-03-30 (45 N·m torque check PASS)' },
        ],
        manuals: ['MOP-BUSWAY-001 — Annual tightening torque'],
    },
};

export function getAssetMeta(id) {
    return ASSET_METADATA[id] || null;
}
