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

// 12 DDUs (Drop-Down Units) — combined 480V tap-off + DLC secondary loop
// to one GB200 NVL72 rack each. Generated programmatically so all 12 share
// the same rated specs but can carry per-DDU jittered metric values.
['A', 'B'].forEach((path) => {
    for (let n = 1; n <= 6; n++) {
        const id = `ddu_${path.toLowerCase()}${n}`;
        ASSET_METADATA[id] = {
            type: 'Rack DDU + DLC Drop',
            label: `DDU-${path}${n} · GB200 NVL72`,
            model: 'Server Technology ePOD + Vertiv Liebert XDU',
            rating: '480 V · 200 A · 142 kW IT load · DLC 2nd loop',
            sparkline: { unit: '°C', baseline: 23, range: 0.4, color: '#FFB300', label: 'Inlet T' },
            details: [
                { k: 'Rack',                v: `GB200 NVL72 #${(n - 1) * 20 + (path === 'A' ? 1 : 11)}` },
                { k: 'Rated Load',          v: '142 kW · 360 GPU + 72 BlueField' },
                { k: 'Inlet Temp Setpoint', v: '22 - 24 °C (ASHRAE TC 9.9 A1)' },
                { k: 'Loop ΔT',             v: '8 °C (return ~ 31 °C)' },
                { k: 'Loop ΔP',             v: '35 kPa (CDU primary)' },
                { k: 'Coolant',             v: 'PG25 · 25 % propylene glycol' },
                { k: 'CDU',                 v: `Liebert XDU 1350 · ${path === 'A' ? '8' : '9'} on hall floor` },
                { k: 'PSU Topology',        v: '3 + 3 redundant @ 1U each' },
            ],
            manuals: [
                'MOP-DDU-001 — Quarterly torque check on busway tap',
                'MOP-DLC-001 — CDU coolant sample (PG25 mix verify)',
            ],
        };
    }
});

// ─── Phase 2 — Building D (Path C2 DESIGN, target Q2 2026) ────────
// design:true => the info panel shows a DESIGN badge instead of live
// state, and asset_engineering renders the spec-sheet section.
// Vocabulary fence (S-VOCAB-01): the DC side is UNIPOLAR TN-S —
// phase vocabulary ends at the MV Rectifier input terminals.
Object.assign(ASSET_METADATA, {
    util_d: {
        type: 'Utility Feed (Ph2 design)', design: true,
        label: 'Utility D · 35 kV',
        model: 'Hydro One MV Feed — Building D',
        rating: '35 kV three-phase AC · design intake',
        sparkline: { unit: 'MW', baseline: 0, range: 0, color: '#8fa3b8' },
        details: [
            { k: 'Voltage Class', v: '35 kV three-phase AC' },
            { k: 'Role', v: 'Last point of phase vocabulary (AC side)' },
            { k: 'Status', v: 'DESIGN — not energized' },
        ],
        manuals: [],
    },
    mv_rect_d: {
        type: 'MV Rectifier (Ph2 design)', design: true,
        label: 'MV Rectifier D',
        model: 'MV solid-state rectifier block',
        rating: '35 kVAC in → 800 VDC out · AC/DC boundary',
        sparkline: { unit: 'MW', baseline: 0, range: 0, color: '#8fa3b8' },
        details: [
            { k: 'Input', v: '35 kV 3-phase AC' },
            { k: 'Output', v: '800 VDC unipolar TN-S' },
            { k: 'Role', v: 'THE vocabulary fence — no phases downstream' },
        ],
        manuals: [],
    },
    sscb_d: {
        type: 'Solid-State Circuit Breaker (Ph2 design)', design: true,
        label: 'SSCB D-01',
        model: 'SiC solid-state breaker',
        rating: '800 VDC · 1-100 µs clearing · IEC 60947-2',
        sparkline: { unit: 'A', baseline: 0, range: 0, color: '#8fa3b8' },
        details: [
            { k: 'Clearing', v: '1-100 µs (vs ~50 ms electromechanical)' },
            { k: 'Standard', v: 'IEC 60947-2' },
            { k: 'Arc', v: 'None — no moving parts' },
        ],
        manuals: [],
    },
    dc_bus_d: {
        type: 'DC Bus (Ph2 design)', design: true,
        label: '800 VDC Bus D',
        model: 'Main DC buswork — Building D',
        rating: '800 VDC · unipolar TN-S earthing',
        sparkline: { unit: 'V', baseline: 0, range: 0, color: '#8fa3b8' },
        details: [
            { k: 'Topology', v: 'Unipolar TN-S (single pole, earthed neutral)' },
            { k: 'Phases', v: 'NONE — a DC bus has no phases' },
        ],
        manuals: [],
    },
    bess_d: {
        type: 'Battery Energy Storage (Ph2 design)', design: true,
        label: 'BESS D-01',
        model: 'LFP container on DC bus',
        rating: '2.5 MWh · bidirectional charge/discharge',
        sparkline: { unit: '%', baseline: 0, range: 0, color: '#8fa3b8' },
        details: [
            { k: 'Capacity', v: '2.5 MWh' },
            { k: 'Role', v: 'Ride-through + peak shaving on the DC bus' },
        ],
        manuals: [],
    },
    rpp_d1: {
        type: 'DC Remote Power Panel (Ph2 design)', design: true,
        label: 'RPP D1',
        model: '800 VDC distribution panel',
        rating: '800 VDC · GB300 NVL144 racks @ 200 kW',
        sparkline: { unit: 'kW', baseline: 0, range: 0, color: '#8fa3b8' },
        details: [{ k: 'Load', v: 'GB300 NVL144 · 200 kW/rack (design)' }],
        manuals: [],
    },
    rpp_d2: {
        type: 'DC Remote Power Panel (Ph2 design)', design: true,
        label: 'RPP D2',
        model: '800 VDC distribution panel',
        rating: '800 VDC · GB300 NVL144 racks @ 200 kW',
        sparkline: { unit: 'kW', baseline: 0, range: 0, color: '#8fa3b8' },
        details: [{ k: 'Load', v: 'GB300 NVL144 · 200 kW/rack (design)' }],
        manuals: [],
    },
});

export function getAssetMeta(id) {
    return ASSET_METADATA[id] || null;
}
