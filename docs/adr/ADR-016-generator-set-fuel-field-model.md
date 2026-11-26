# ADR-016: Generator set and fuel system field model

- Status: accepted
- Date: 2026-11-26
- Deciders: Wilmer Y. Angel Beltran (operator, GO for lot L3), Claude (implementation)

## Context and problem statement

Lot L3 of the operator's master specification asks for each 2.75 MW
diesel set as a technician meets it: the engine control panel (STOP /
AUTO / RUN selector, emergency stop), the jacket-water heater, the
1,200 L sub-base day tank with five floats, duplex transfer pumps with
HAND / OFF / AUTO and motor overloads, a duplex fuel filter / water
separator and a rupture-basin leak float, fed from a 50,000 L bulk tank.
Until L3 a generator was a state machine (STANDBY to ON_LOAD) with
unlimited fuel and no local controls.

## Decision drivers

- What the plant already decides (auto start, N / N+1, generation floor)
  must react to a set that cannot run, with one source of truth.
- Grounding: NFPA 110 Level 1 coolant minimum, a real fuel curve, real
  day-tank practice; model values said as such.
- ADR-006 fence: no agent imports the control modules.

## Decision

1. **`backend/gen_fuel.py`** (pure) holds one `GenSet` per generator and
   the controller holds one bulk tank per path. State reaches the plant
   snapshot as `fuel` on each generator and `bulk_fuel_*` on each path.
2. **A set that cannot run is unavailable everywhere**: e-stop, latched
   shutdown, day tank at or below 15 %, or engine control in STOP drop it
   from auto start, remote START and the N / N+1 count (`_gens_available`).
   RUN starts it locally. STOP / RESET clears a latched shutdown.
3. **Shutdowns are protection trips**: low fuel, filter starvation and the
   e-stop open 52-G and stop the engine. If the remaining sets on the bus
   cannot carry the path demand, they trip too (model: no load shedding),
   the MV bus goes dead and the UPS rides the battery.
4. **Grounded values**: NFPA 110 Level 1 coolant minimum 32 C (quoted in
   manufacturer manuals, not checked against the standard text); fuel
   curve 239 / 391 / 542 / 694 L/h at 1/4 to full load from a Cummins DQLH
   2750 kW 60 Hz data sheet, no-load point extrapolated; per-pump HAND /
   OFF / AUTO, basin float that stops the pumps and a normally closed
   supply solenoid from a day-tank guide specification. Float levels and
   tank sizes from the operator's master specification.
5. **Model values**, said in the payload and on the panel: pump flow
   1,200 L/h, heater setpoint 43 C, engine-room ambient 17.8 C (master
   spec), time constants, 12 s cold-start load-acceptance delay, filter
   pressure-drop curve and thresholds, time compressed x30. The high-high
   float stops the pumps even in HAND (verify on a real panel drawing).
6. **Not modelled**: per-set governor / AVR bias for manual paralleling
   (the T3 bus governor stays), lube oil, battery charger, fuel delivery
   to the bulk tank, lead / lag alternation.

## Consequences

- DRILL-07: lead pump on overload, lag pump left in OFF while the path is
  on generators; the trainee restores the pumps before the 15 % shutdown.
- New alarms per set (e-stop, shutdown, not in AUTO, fuel low / high-high,
  pump overload / not in AUTO, basin leak, filter restriction, water in
  fuel, low coolant temperature) and per path (main tank low, below 25 %
  or under 3 h at the present burn).
- Generator readings gain day tank, coolant and fuel rate.
