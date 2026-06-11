/* ════════════════════════════════════════════════════════════════
 * DC-EPMS PRO — core/power_budget.js
 * 50 MW track — Building D (Phase 2 DESIGN) energy budget + genset
 * farm sizing. Pure module: one source of truth for every number
 * the diagrams print, so PUE, losses and farm size can never drift
 * apart between views.
 *
 * Model (design-grade, stated assumptions — not live telemetry):
 *   IT load        : 250 racks x 200 kW GB300 NVL144 = 50 MW
 *   Power chain    : MV rectifier eta + DC distribution I2R
 *   Cooling        : split DLC (CDU liquid) / air (CRAH); chiller
 *                    compressor work = heat / COP (water-cooled,
 *                    York YZ class); CHW+CDU pumps; cooling-tower
 *                    fans; CRAH fans on the air fraction
 *   Aux            : lighting + controls + misc
 *   PUE            : total facility / IT
 *
 * Genset farm (operator spec): >50 MW cannot be a single prime
 * mover; farm of MV units (13.8 kV) on paralleling switchgear,
 * N+2 redundancy, ANSI 25 sync + dead-bus black start (see
 * config/knowledge/genset-farm-mv-paralleling.md).
 * ════════════════════════════════════════════════════════════════ */

export const PHASE2_DEFAULTS = Object.freeze({
    itMw: 50.0,                 // 250 x 200 kW GB300 NVL144
    rectifierEff: 0.985,        // MV solid-state rectifier
    dcDistLossFrac: 0.005,      // 800 VDC bus + RPP I2R
    dlcFraction: 0.85,          // heat captured by liquid (CDU)
    chillerCop: 6.0,            // water-cooled centrifugal, full load
    pumpFracOfIt: 0.016,        // CHW + CDU pump trains
    towerFanFracOfIt: 0.016,    // forced-draft cooling tower fans
    crahFanFracOfAirHeat: 0.10, // CRAH fan W per W of air-side heat
    auxMw: 0.5,                 // lighting, controls, misc
    gensetUnitMw: 3.2,          // farm prime-mover block size
    gensetRedundancy: 2,        // N+2
});

/**
 * Compute the full Phase 2 energy budget. Every output in MW.
 * @returns {{ it, rectifierLoss, dcDistLoss, chillers, pumps,
 *             towerFans, crahFans, aux, totalFacility, pue,
 *             heatTotal, heatDlc, heatAir }}
 */
export function phase2Budget(overrides = {}) {
    const p = { ...PHASE2_DEFAULTS, ...overrides };
    const it = p.itMw;

    // Electrical chain losses (become heat too, but rejected outside
    // the white space — kept out of the chiller load for clarity).
    const rectifierLoss = it / p.rectifierEff - it;
    const dcDistLoss = it * p.dcDistLossFrac;

    // Practically all IT watts become heat to reject.
    const heatTotal = it;
    const heatDlc = heatTotal * p.dlcFraction;
    const heatAir = heatTotal - heatDlc;

    const chillers = heatTotal / p.chillerCop;     // compressor work
    const pumps = it * p.pumpFracOfIt;
    const towerFans = it * p.towerFanFracOfIt;
    const crahFans = heatAir * p.crahFanFracOfAirHeat;

    const totalFacility = it + rectifierLoss + dcDistLoss
        + chillers + pumps + towerFans + crahFans + p.auxMw;

    return {
        it,
        rectifierLoss,
        dcDistLoss,
        chillers,
        pumps,
        towerFans,
        crahFans,
        aux: p.auxMw,
        heatTotal,
        heatDlc,
        heatAir,
        totalFacility,
        pue: totalFacility / it,
    };
}

/**
 * Genset farm sizing for the budget's total facility load.
 * @returns {{ unitMw, required, installed, redundancy, farmMw }}
 */
export function gensetFarmSizing(overrides = {}) {
    const p = { ...PHASE2_DEFAULTS, ...overrides };
    const b = phase2Budget(overrides);
    const required = Math.ceil(b.totalFacility / p.gensetUnitMw);
    const installed = required + p.gensetRedundancy;
    return {
        unitMw: p.gensetUnitMw,
        required,
        installed,
        redundancy: p.gensetRedundancy,
        farmMw: installed * p.gensetUnitMw,
    };
}

/** One-line budget caption for the diagrams (single source). */
export function budgetCaption(overrides = {}) {
    const b = phase2Budget(overrides);
    const f = (v) => v.toFixed(1);
    return `IT ${f(b.it)} MW · rect loss ${f(b.rectifierLoss)} · DC dist ${f(b.dcDistLoss)}`
        + ` · chillers ${f(b.chillers)} (COP ${(PHASE2_DEFAULTS.chillerCop).toFixed(0)})`
        + ` · pumps ${f(b.pumps)} · tower fans ${f(b.towerFans)}`
        + ` · CRAH ${f(b.crahFans)} · aux ${f(b.aux)}`
        + ` → TOTAL ${f(b.totalFacility)} MW · PUE ${b.pue.toFixed(2)}`;
}
