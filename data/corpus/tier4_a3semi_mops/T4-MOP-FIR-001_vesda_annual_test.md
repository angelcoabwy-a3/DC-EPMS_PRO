---
doc_id: T4-MOP-FIR-001
tier: 4
priority: high
doc_type: MOP
domain: fire_life_safety
equipment: VESDA LaserSCANNER aspirating smoke detection
standard_refs: [NFPA 72, NFPA 75]
applies_to: [vesda_annual, smoke_detection, fire_system_test]
keywords: [mop, vesda, annual_test, fire_alarm, smoke_detection, aspirating]
facility: A3-Alpha Toronto Area
duration: 8 hours
personnel_required: NICET Level III fire alarm technician + assistant
---

# MOP: VESDA Annual Comprehensive Test

**Procedure ID**: T4-MOP-FIR-001
**Revision**: 2026.1
**Scheduled**: 2nd Saturday of April annually
**Authority**: NFPA 72 §14.4.5, a3semi Fire Protection Program

## Purpose

Comprehensive annual test of VESDA LaserSCANNER aspirating smoke detection
systems at A3-Alpha Toronto Area. Validates flow rates, transport times,
sensitivity, and integration with fire alarm panel. Satisfies NFPA 72
annual inspection requirement.

## Scope

- VESDA-A: Hall A coverage
- VESDA-B: Hall B coverage
- VESDA-C: Hall C coverage
- VESDA-MEP: MEP room (UPS, switchgear)
- VESDA-BAT: Battery room (hydrogen detection integrated)

## Pre-work requirements

### 72 hours before

1. Notify customers via standard maintenance communication
2. Notify 9-1-1 dispatcher of scheduled testing window
3. Confirm fire department not planning responses to A3-Alpha
4. Pre-stage calibrated smoke test kit
5. Verify suppression system isolation procedures reviewed

### 24 hours before

1. Final customer notification with exact start time
2. NOC team briefing (test coordinator role assigned)
3. Verify fire watch staffing plan
4. Stage equipment at MEP room

### At start (T-0)

1. Set fire alarm panel to TEST mode (documented in log)
2. Set suppression systems to MANUAL (each system, each zone)
3. Post "FIRE SUPPRESSION IN MANUAL" placards
4. Confirm NOC receives test-mode signal
5. Initiate 9-1-1 notification (courtesy call): "Testing begins"

## Test sequence (per VESDA unit)

### Test 1: Flow rate verification (NFPA 72 §14.4.5.2)

1. Connect flow meter to VESDA intake
2. Record baseline airflow per pipe branch
3. Compare to commissioning report (must be within ±20%)
4. Record and document

**Acceptance**: ≥80% of commissioning flow rate per branch

### Test 2: Transport time (NFPA 72 §14.4.5.5)

For EACH sampling pipe branch:

1. Identify farthest sampling hole from VESDA head
2. Stop watch ready
3. Inject calibrated smoke stimulus at farthest hole
4. Start timer at injection
5. Stop timer when VESDA displays first detection
6. Record transport time

**Acceptance**: <60 seconds from farthest hole to detection

**Typical A3-Alpha values:**
- Hall A branches: 22-38 seconds (pass)
- Hall B branches: 25-42 seconds (pass)
- MEP branches: 15-28 seconds (pass)

### Test 3: Sensitivity verification

For EACH VESDA unit:

1. Inject test smoke at MEDIUM density
2. Verify Alert (0.003%/m) trigger
3. Increase density to Action (0.01%/m)
4. Verify panel annunciation at each level
5. Continue to Fire 1 (0.05%/m) — verify annunciation
6. STOP at Fire 1 — do NOT trigger Fire 2 (would initiate evacuation)
7. Allow to clear, verify return to normal within 60 seconds

### Test 4: Fire panel integration

1. Verify signal path: VESDA → Fire Alarm Control Panel (FACP)
2. Confirm FACP receives Alert, Action, Fire 1 signals
3. Verify annunciation at:
   - FACP display
   - NOC remote annunciator
   - EPMS via network link
4. Document any signal path issues

### Test 5: Laser calibration (factory reference)

1. Insert NIST-traceable reference source into VESDA head
2. Record indicated level
3. Compare to expected value (per manufacturer)
4. If drift >5%: mark for service calibration
5. Document results

## Post-test restoration

After all tests complete:

1. Restore fire alarm panel from TEST to NORMAL
2. Verify normal-mode indication on FACP
3. Restore each suppression system to AUTO:
   - Pre-action water mist
   - FM-200 (MEP room)
   - CO₂ (tape library, cable vault)
4. Remove "MANUAL" placards
5. Send "TEST COMPLETE" message to all affected personnel
6. Final notification to 9-1-1 dispatcher
7. Walk through each hall to verify operational status

## Verification walk-through

Post-restoration verification:

- FACP shows all systems normal
- No latent alarms
- VESDA indicators GREEN at each head
- Suppression valves in AUTO position
- Manual activation stations unobstructed
- Emergency lighting functional
- Exit signs illuminated

## Acceptance criteria

Annual test passes when ALL of:

- [ ] All VESDA units: flow rate within ±20% commissioning
- [ ] All transport times <60 seconds
- [ ] All sensitivity thresholds verified
- [ ] Fire panel integration verified
- [ ] Laser calibration within ±5%
- [ ] Systems restored to NORMAL/AUTO
- [ ] Documentation signed by NICET Level III
- [ ] No pending anomalies

## Failure modes and actions

### Transport time exceeds 60 seconds

Likely causes:
- Pipe blockage (debris, dust accumulation)
- Fan failure or degradation
- Filter heavily loaded

Actions:
1. Identify specific branch with long time
2. Pressure test to locate blockage
3. Clear blockage or replace filter
4. Re-test to verify <60 seconds
5. Do NOT return to service until re-test passes

### Flow rate <80% of commissioning

Likely causes:
- Pipe leak
- Loose fitting
- Sensor degradation

Actions:
1. Pressure-decay test each branch
2. Visually inspect pipe joints
3. Repair identified leaks
4. Re-commission flow rates per NFPA 72

### Sensitivity drift

Likely causes:
- Laser aging (approaching end-of-life at ~60,000 hours)
- Sensor contamination

Actions:
1. Clean sensor if contamination visible
2. If laser near end-of-life: schedule replacement within 30 days
3. Increase inspection frequency until replaced

### Panel integration fault

Likely causes:
- Wiring fault
- Panel configuration error
- Network link issue

Actions:
1. Verify wiring continuity
2. Check panel programming
3. Test with portable annunciator
4. Do NOT return to service until fully integrated

## Documentation

Annual test generates:

- Signed test report (retained minimum 5 years per NFPA 72)
- Transport time table by branch
- Flow rate table by branch
- Sensitivity verification results
- Calibration certificates
- Entry in PostgreSQL `procedures` table with complete metrics
- Customer compliance notification
- Regulatory submissions as required

## References

- NFPA 72-2022 §14.4.5 (Air Sampling Smoke Detection)
- NFPA 75-2020 (Protection of Information Technology Equipment)
- NICET Level III Fire Alarm Systems certification
- VESDA LaserSCANNER installation manual (Xtralis 10325_13)
- a3semi VESDA Test Record: A3-SAF-FRM-022
