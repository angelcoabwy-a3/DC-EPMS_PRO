# ADR-023: Building D simulated plant (live, operable, drills)

- Status: accepted
- Date: 2026-11-27
- Deciders: Wilmer Y. Angel Beltran (operator: GO on "SLD live and
  operable, then drills" for Building D), Claude (implementation)

## Context and problem statement

After DC-EPMS-076 step 2 the Power SLD drew Building D as 2N, but every
number on it was a fixed design value and nothing on it could be
operated. Phase 1 already has a simulated plant behind Power Controls
(select-before-operate, authority, ledger, alarms, training drills). The
operator asked for the same on Building D: live numbers, supervised
switching and drills.

## Decision

1. **One pure plant model**, `backend/bldg_d.py` (`BuildingD`), per path
   D-A / D-B: utility 35 kV (3-phase AC), generator farm, rectifier
   group input breaker and modules, bus main SSCB, 800 VDC unipolar TN-S
   bus, BESS. Numbers come from the ADR-021 design model
   (`params_from_sizing`); timings and limits not in the design are
   marked MODEL.
2. **Load sharing**: dual-corded racks draw from both buses. Rectifier-fed
   buses share the hall equally within what each can deliver; a bus on
   its BESS droops, so the BESS only covers what the rectifiers cannot
   (water-filling). A bus collapses (SSCB and BESS breaker trip on
   undervoltage) only when all live sources together cannot carry the
   hall: then the hall load is lost and latched. No load shedding.
3. **Ramp limit on the AC source**, not on the rectifier: the generator
   farm takes load at a limited rate (block load acceptance, MODEL
   2 MW/s per path); the utility follows within one tick (MODEL). This
   is what makes the BESS matter when a path runs on its farm.
4. **Farm per path** (as ADR-021): AUTO start on utility loss after a
   MODEL 10 s start delay (NFPA 110 names 10 s for Type 10), automatic
   transfer of the rectifier input, manual retransfer, cooldown. The SLD
   still draws one farm block for both paths.
5. **Power Controls integration**: eight devices (rectifier group, SSCB,
   BESS, farm per path) in `DeviceController` with device paths `da` /
   `db`, built only when `from_design(..., building_d=params)` is given
   (main.py does; power scenarios and older tests do not). Same rules as
   Phase 1: AUTO / REMOTE / LOCAL, select-before-operate, FACILITY_MANAGER,
   Forensic Ledger. Interlocks are supervisory (model), e.g. refusing to
   open the last live bus that has no BESS.
6. **Telemetry follows the plant**: `telemetry_simulator.set_state_overlay`
   pins the mean of selected channels (`<asset>:<metric>`) to the plant
   values; the simulator's own zero-mean jitter stays, a dead quantity
   reads 0, no extra RNG draws. Registered on both module identities
   (`telemetry_simulator` and `backend.telemetry_simulator`). A failing
   overlay is logged and ignored.
7. **Bench injections**: `POST /api/bldg-d/inject` (FACILITY_MANAGER,
   ledger `BUILDING_D_SIMULATION_INJECTION`): utility loss / restore, bus
   fault, BESS breaker open, farm auto OFF, settled preset, load step.
8. **Alarms**: `conditions_from_building_d` (`BLDG_D*_...`).
9. **Drills**: DRILL-11 (utility D-A lost, farm auto OFF), DRILL-12
   (800 VDC bus fault D-A, isolate / clear / re-energise in order),
   DRILL-13 (load step on one path on its farm with the BESS left open).
   New training check `bldg_d`, failure `hall_d_lost`, injection `bldg_d`.

## Consequences

- The SLD Building D branch shows live numbers (kV, MW, efficiency, bus
  VDC, SOC and BESS current, SSCB junction temperature, who carries the
  hall) and opens a faceplate on the rectifier groups, SSCBs, BESS and
  the farm block, with bench injections next to the commands.
- The plant mirror drives the DAG for Building D in LIVE; What-If keeps
  the sandbox DAG.
- A standby farm (and its 13.8 kV bus and step-up) now reads healthy on
  the SLD instead of critical.

## Honest scope

- Simulation only. No DC fault current, no SSCB let-through, no arc
  energy, no protection coordination. "1-100 us" is the design class,
  not a computed clearing time.
- Time resolution is one second; sub-second load swings (the 100 ms
  GB300 swing in the design) are represented by a seconds-scale step.
- SSCB junction temperature is a linear MODEL (30 C + 25 K at the 2N
  design current), not a thermal model.
- The rectifier groups are one block per path (14 modules), not two
  sections of 7; the N+1 rule is counted per path (12 of 14).
- One farm block is drawn for two per-path farms; the farm block still
  carries the old `power_budget.js` sizing text (22 x 3.2 MW).
