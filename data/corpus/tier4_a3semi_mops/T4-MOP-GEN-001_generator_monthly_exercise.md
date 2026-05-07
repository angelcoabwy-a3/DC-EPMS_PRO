---
doc_id: T4-MOP-GEN-001
tier: 4
priority: high
doc_type: MOP
domain: emergency_power
equipment: Caterpillar 3516C diesel generator (2 units, N+1)
standard_refs: [NFPA 110 Type 10, EGSA Certified]
applies_to: [generator_monthly, backup_power, load_bank]
keywords: [mop, generator, monthly_exercise, load_bank, caterpillar, diesel]
facility: A3-Alpha Toronto Area
duration: 2 hours per generator
personnel_required: 1 EGSA-certified technician
---

# MOP: Generator Monthly Exercise Test

**Procedure ID**: T4-MOP-GEN-001
**Revision**: 2026.1
**Scheduled**: First Friday of each month, 09:00 local
**Authority**: NFPA 110 §8.4.2, a3semi Emergency Power Program

## Purpose

Monthly exercise of Caterpillar 3516C standby generators. Validates
starting capability, load-carrying performance, and control system
function. Satisfies NFPA 110 Type 10 Level 1 monthly exercise
requirement.

## Scope

- Generator 1 (A3-GEN-001)
- Generator 2 (A3-GEN-002)
- Tested sequentially (not simultaneously to preserve redundancy)
- 30-minute minimum run per unit, loaded exercise

## Pre-work requirements

### 24 hours before

1. Review prior month's exercise report
2. Verify fuel level in bulk tank (minimum 50% for exercise)
3. Confirm resistive load bank operational (if using load bank) or
   planned transfer switch operation (if using building load)
4. Notify NOC of testing window

### 1 hour before

1. Verify weather acceptable (wind <50 km/h for outdoor installation)
2. Confirm utility power quality (stable, no active faults)
3. Check generator room ventilation
4. Inspect exhaust stack and louvers
5. Brief any operators of scheduled testing

### At start

1. Document pre-start conditions:
   - Coolant temperature: ___°C
   - Fuel level: ___%
   - Battery voltage: ___V
   - Oil level: ___
   - Ambient temperature: ___°C
2. Clear any existing alarms (non-critical)

## Test procedure — per generator

### Phase 1: Cold start (automatic)

1. At ATS: initiate test (simulates utility loss)
2. Time start command sent
3. Observe generator start sequence:
   - Cranking begins within 1 second
   - First start attempt: should start within 3 seconds
4. Record:
   - Crank time (seconds)
   - Voltage build time
   - Frequency stabilization time

**Acceptance: <10 seconds from start signal to load-ready per NFPA 110
Type 10**

### Phase 2: Warm-up (5 minutes)

Allow generator to warm up without load:

- Monitor oil pressure stabilization
- Observe coolant temperature trending toward operating range
- Record any abnormal sounds, vibrations, smoke

### Phase 3: Load transfer (5 minutes)

Two methods, depending on configuration:

**Option A: Load bank exercise (preferred for monthly)**
- Connect resistive load bank
- Apply load in steps: 25%, 50%, 75% of generator rating
- Record voltage, frequency, current at each step
- Monitor for load-rejection capability

**Option B: Building transfer (for NFPA 110 compliance evidence)**
- ATS commanded to transfer to generator
- Observe transfer (10-second window)
- Building runs on generator
- Monitor load sharing with second generator (if both online)

### Phase 4: Loaded run (30 minutes minimum)

Monitor continuously:

- Output voltage (each phase): should be 480V ±2%
- Output frequency: 60 Hz ±0.5%
- Output current (each phase): track against load
- Engine parameters:
  - Oil pressure: 2.4-5.2 bar (gauge)
  - Oil temperature: 85-110°C
  - Coolant temperature: 80-95°C
  - Exhaust stack temperature: <540°C
  - Battery charge voltage: 26-28V
- Vibration characteristics

Record every 5 minutes.

### Phase 5: Cool-down (5 minutes)

1. Reduce load gradually (if load bank)
2. Operate no-load for 5 minutes
3. Allow coolant temperature to stabilize
4. Monitor for any cool-down anomalies

### Phase 6: Shutdown

1. Command normal shutdown at local panel
2. Verify:
   - Engine stops within 60 seconds
   - Voltage collapses properly
   - Generator protection relays reset
3. If using ATS: verify re-transfer to utility
4. Observe re-transfer quality (should be seamless, <10 seconds)

### Phase 7: Post-run inspection

1. Check for any fluid leaks
2. Verify battery charging current stable
3. Check oil level (consumption during test)
4. Check coolant level
5. Verify all alarms cleared
6. Record final readings

## Acceptance criteria

Monthly exercise passes when ALL of:

- [ ] Started within 10 seconds of command (NFPA 110 Type 10)
- [ ] Reached rated voltage and frequency within specification
- [ ] Carried 30-minute loaded run without alarm
- [ ] Shutdown normally without error
- [ ] Post-run inspection clean
- [ ] No leaks, abnormal sounds, or vibrations noted

## Failure modes and actions

### Failure to start

Crank but no fire:
1. Check fuel pressure
2. Verify fuel filter not blocked
3. Inspect glow plugs / starting aids (winter)
4. Check air filter

Crank failure:
1. Battery voltage check (must be >24V)
2. Starter motor inspection
3. Battery load test

### Voltage out of range

- Voltage regulator adjustment needed
- Check field excitation
- Inspect output stator

### Temperature excursion

- Verify coolant circulation
- Check radiator cleanliness
- Verify thermostat operation
- Inspect for exhaust leak into engine compartment

### Oil pressure low

STOP test immediately:
- Check oil level
- Inspect for leaks
- Do NOT operate generator until root cause identified

### Load rejection

Generator trip during load bank test:
- Review trip log
- Check voltage regulator stability
- Inspect governor response
- May indicate control system issue needing factory service

## Fuel management during exercise

Monthly exercise consumes significant fuel:

- Fuel consumption: ~300 L/hour at full load (3516C)
- 30-minute loaded test: ~150 L per generator
- Two generators: ~300 L monthly
- Bulk tank refill planning: every 3-4 months if no outages

After exercise:
- Fuel level recorded
- Refill triggered if level <40%
- Fuel sample quarterly for polishing decision

## Battery system

Starting battery maintenance during exercise:

- Voltage before start: should be >24V
- Voltage during crank: should not drop below 20V
- Voltage after start: should trend to float (27.2V)
- If battery voltage drops during crank: battery load test required

## Documentation

Every monthly exercise generates:

- Signed exercise report (NFPA 110 §8.4.2)
- Data log: voltages, currents, temperatures, pressures
- Fuel consumption record
- Battery condition record
- Any observations or minor adjustments
- Entry in PostgreSQL `procedures` table

Reports retained minimum 7 years per NFPA 110.

## Annual full-load test

In addition to monthly exercises, NFPA 110 requires annual 4-hour
full-load test. This is a SEPARATE, LARGER event with its own MOP
(T4-MOP-GEN-002). The monthly exercise prepares for the annual by
identifying any developing issues.

## References

- NFPA 110-2022 §8.4.2 (Monthly Exercise)
- NFPA 110-2022 §8.4.9 (Annual Full-Load Test)
- Caterpillar 3516C Operation and Maintenance Manual
- EGSA (Electrical Generating Systems Association) Standards
- a3semi Generator Exercise Report: A3-OPS-FRM-035
