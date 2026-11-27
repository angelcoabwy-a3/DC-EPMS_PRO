/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — frontend/assets/js/core/asset_metadata.js
 *
 * Industrial metadata for the SLD assets. Phase 1 power entries follow
 * the closed design in config/power_plant.yml (DC-EPMS-068); other
 * entries keep their earlier reference data — Phase 1
 * (deployed Buildings A/B at A3-Alpha Toronto Area). Replaces the
 * static `--- kW` placeholders with model + rating + last-PM +
 * vendor manual references.
 *
 * Source for ratings:
 *   - NVIDIA GB200 NVL72 reference design (2024 spec sheet)
 *   - (before DC-EPMS-068 the power entries cited Galaxy VX, a 2.5 MVA
 *     dry-type, an ASCO 7000 ATS and a Cummins QSK60; those no longer
 *     match the closed design and were removed)
 *   - C&D Technologies VRLA Pure Lead datasheet
 *   - Server Technology PRO4 RPP-class datasheet
 *   - Starline Track Busway 800A spec
 * ════════════════════════════════════════════════════════════════ */

const _common = (path) => ({
    util:    { type: 'Utility Feed',                     model: path === 'A' ? 'Hydro One MV Feed (North)' : 'Hydro One MV Feed (South)',
               rating: '27.5 kV three-phase · 50 MVA available',
               sparkline: { unit: 'MW',  baseline: 14.8, range: 1.4,  color: '#00E5FF' } },
    // Closed Phase 1 design (config/power_plant.yml, DC-EPMS-068).
    xfmr:    { type: 'Utility Transformer',              model: 'MV/MV · vendor not selected',
               rating: '27.5 kV → 13.8 kV · 25 MVA (sizing assumption, site model v2)',
               sparkline: { unit: '°C',  baseline: 64,   range: 6,    color: '#FFB300' } },
    genset:  { type: 'Generator Bus (9 sets)',           model: 'MV standby sets · vendor not selected',
               rating: '9 × 2.75 MW · 13.8 kV · N+1 on the 21.5 MW floor (ADR-013)',
               sparkline: { unit: 'rpm', baseline: 0,    range: 0,    color: '#FFB300' } },
    mvtc:    { type: 'MV Transfer Controller',           model: '52-U utility incomer / 52-GM generator main · vendor not selected',
               rating: '13.8 kV · open transition (2 s gap in sim)',
               sparkline: { unit: '',    baseline: 1,    range: 0,    color: '#00E5FF' } },
    ups:     { type: 'UPS Bank (8 blocks)',              model: 'Vertiv Trinergy 2500 · double conversion',
               rating: '8 × 2.5 MW · 480 V · 20 MW per path · N+1 inside the path',
               sparkline: { unit: 'kW',  baseline: 8380, range: 120,  color: '#00E5FF' } },
    batt:    { type: 'Battery (per UPS block)',          model: 'chemistry not specified in config/power_plant.yml',
               rating: '10 min at full load per block (operator design: 8 to 12 min)',
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
        label: 'XFMR A · 27.5/13.8 kV',
        details: [
            { k: 'Site model v2 id', v: 'mv_xfmr_a' },
            { k: 'Sizing',           v: 'design total load at 0.9 PF, next 5 MVA (assumption, not vendor data)' },
            { k: 'History',          v: 'simulated plant: no maintenance history' },
        ],
        manuals: [],
    },
    genset_a: {
        ..._common('A').genset,
        label: 'Generator Bus A',
        details: [
            { k: 'Site model v2 ids', v: 'genset_a_01 … genset_a_09' },
            { k: 'Paralleling',       v: '13.8 kV bus · ANSI 25 synchronising' },
            { k: 'Withdrawal rule',   v: 'one set per path out at a time (ADR-013)' },
            { k: 'History',           v: 'simulated plant: no run-hour records' },
        ],
        manuals: [],
    },
    mvtc_a: {
        ..._common('A').mvtc,
        label: 'MV Transfer A',
        details: [
            { k: 'Breakers',  v: '52-U (utility) · 52-GM (generator main)' },
            { k: 'Switching', v: 'supervised from Power Controls (select-before-operate, ledger)' },
            { k: 'Replaces',  v: '480 V ATS of the legacy site model (DC-EPMS-058)' },
        ],
        manuals: [],
    },
    ups_a: {
        ..._common('A').ups,
        label: 'UPS Bank A',
        details: [
            { k: 'Site model v2 ids', v: 'ups_a_01 … ups_a_08' },
            { k: 'Efficiency',        v: '0.97 double conversion · 0.99 Dynamic Online (model)' },
            { k: 'Capacity rule',     v: 'N = 16.76 MW full-path IT load; one block out keeps N' },
            { k: 'History',           v: 'simulated plant: no maintenance history' },
        ],
        manuals: [],
    },
    batt_a: {
        ..._common('A').batt,
        label: 'Batteries A',
        details: [
            { k: 'Holdup in sim', v: '1 % SOC per second while on battery (fast-forward)' },
        ],
        manuals: [],
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
        label: 'XFMR B · 27.5/13.8 kV',
        details: [
            { k: 'Site model v2 id', v: 'mv_xfmr_b' },
            { k: 'Sizing',           v: 'design total load at 0.9 PF, next 5 MVA (assumption, not vendor data)' },
            { k: 'History',          v: 'simulated plant: no maintenance history' },
        ],
        manuals: [],
    },
    genset_b: {
        ..._common('B').genset,
        label: 'Generator Bus B',
        details: [
            { k: 'Site model v2 ids', v: 'genset_b_01 … genset_b_09' },
            { k: 'Paralleling',       v: '13.8 kV bus · ANSI 25 synchronising' },
            { k: 'Withdrawal rule',   v: 'one set per path out at a time (ADR-013)' },
            { k: 'History',           v: 'simulated plant: no run-hour records' },
        ],
        manuals: [],
    },
    mvtc_b: {
        ..._common('B').mvtc,
        label: 'MV Transfer B',
        details: [
            { k: 'Breakers',  v: '52-U (utility) · 52-GM (generator main)' },
            { k: 'Switching', v: 'supervised from Power Controls (select-before-operate, ledger)' },
            { k: 'Replaces',  v: '480 V ATS of the legacy site model (DC-EPMS-058)' },
        ],
        manuals: [],
    },
    ups_b: {
        ..._common('B').ups,
        label: 'UPS Bank B',
        details: [
            { k: 'Site model v2 ids', v: 'ups_b_01 … ups_b_08' },
            { k: 'Efficiency',        v: '0.97 double conversion · 0.99 Dynamic Online (model)' },
            { k: 'Capacity rule',     v: 'N = 16.76 MW full-path IT load; one block out keeps N' },
            { k: 'History',           v: 'simulated plant: no maintenance history' },
        ],
        manuals: [],
    },
    batt_b: {
        ..._common('B').batt,
        label: 'Batteries B',
        details: [
            { k: 'Holdup in sim', v: '1 % SOC per second while on battery (fast-forward)' },
        ],
        manuals: [],
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

// 2N Building D (DC-EPMS-076): path D-B mirrors the path D-A design
// assets; labels name the path, BESS sized per ADR-021 rev 2.
ASSET_METADATA.bess_d.label = 'BESS D-A';
ASSET_METADATA.bess_d.rating = '15 MWh per path · 10 min at 50 MW · bidirectional';
ASSET_METADATA.bess_d.details = [
    { k: 'Capacity', v: '15 MWh (6 x 2.5 MWh blocks, ADR-021 rev 2)' },
    { k: 'Role', v: 'Ride-through + peak shaving on the path A DC bus' },
];
for (const [a, b, letter] of [['util_d', 'util_d_b', 'B'], ['mv_rect_d', 'mv_rect_d_b', 'B'],
    ['sscb_d', 'sscb_d_b', 'B'], ['dc_bus_d', 'dc_bus_d_b', 'B'], ['bess_d', 'bess_d_b', 'B']]) {
    const src = ASSET_METADATA[a];
    ASSET_METADATA[b] = {
        ...src,
        label: String(src.label).replace(/\bD(-A|-01)?\b/, `D-${letter}`).replace(/ D$/, ` D-${letter}`),
        details: [...(src.details || []), { k: 'Path', v: 'D-B (2N mirror of path D-A)' }],
    };
}
// Path A labels name their path too, once the B clones are made.
for (const a of ['util_d', 'mv_rect_d', 'sscb_d', 'dc_bus_d']) {
    const m = ASSET_METADATA[a];
    if (!/D-A\b/.test(m.label)) {
        m.label = String(m.label).replace(/\bD(-01)?\b/, 'D-A').replace(/ D$/, ' D-A');
    }
}

export function getAssetMeta(id) {
    return ASSET_METADATA[id] || null;
}
