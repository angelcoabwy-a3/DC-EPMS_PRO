---
doc_id: T4-MOP-CHI-001
tier: 4
priority: high
doc_type: MOP
domain: mechanical_cooling
equipment: York YZ magnetic-bearing chiller (1 and 2)
standard_refs: [ASHRAE 147, AHRI 550/590, CSA Z462, a3semi OPS]
applies_to: [chiller_quarterly_pm, condenser_inspection, refrigerant_check]
keywords: [mop, chiller_pm, york_yz, magnetic_bearing, condenser, quarterly]
facility: A3-Alpha Toronto Area
duration: 6 hours per chiller
personnel_required: 2 qualified (1 refrigeration technician)
---

# MOP: York YZ Chiller Quarterly Preventive Maintenance

**Procedure ID**: T4-MOP-CHI-001
**Revision**: 2026.1
**Approved by**: Facility Manager, a3semi

## Purpose

Quarterly preventive maintenance on the York YZ magnetic-bearing
centrifugal chillers. Maintains cooling performance, validates
refrigerant integrity, inspects key components, and satisfies warranty
requirements.

## Scope

- Chiller 1 (A3-MEP-CHI-001) and Chiller 2 (A3-MEP-CHI-002)
- Performed on ONE unit at a time
- The other chiller carries full facility load during maintenance
- Scheduled during moderate outdoor temperature periods (spring/fall
  preferred; summer requires additional planning)

## Pre-work requirements

### 48 hours before

1. Verify N+1 cooling available (second chiller fully operational)
2. Verify weather forecast: outdoor temperature <30°C preferred
3. Confirm refrigeration technician available (certified for R-1233zd)
4. Pre-stage materials:
   - Condenser water chemistry test kit
   - Filter cartridges (50-micron for DLC loop)
   - Coolant sample bottles
   - Electronic refrigerant leak detector
5. Check condenser water treatment chemistry (pH, conductivity)

### 4 hours before

1. Reduce chiller being serviced to 20% load
2. Observe for anomalies during load reduction
3. Allow other chiller to pick up load (should reach 80-100%)
4. Brief maintenance team

## Hazards and controls

| Hazard | Control |
|--------|---------|
| R-1233zd refrigerant exposure | A1 rated (safe), but ventilation required; respirator if leak |
| Stored refrigerant pressure | Isolation valves, certified leak detector |
| Electrical hazard (1000 kW motor) | LOTO at VSD disconnect |
| Chilled water burn (45°C return) | Insulated gloves for piping work |
| Legionella in condenser water | Biocide treatment, sample before handling |
| Fall hazard (chiller deck) | Safety harness, two-person rule |

## Tools and materials

- Refrigerant leak detector (electronic, calibrated)
- Condenser water test kit (pH, conductivity, iron, biocide)
- Oil-free tools (do NOT use oil-based lubricants near magnetic bearings)
- Filter wrenches for coolant loop filters
- Torque wrench for flange connections (15-150 N·m range)
- Vibration analyzer (FLIR equivalent)
- Lockout tools and personal locks
- PPE: safety glasses, hearing protection, insulated gloves, hard hat

## Procedure

### Phase 1 — Shutdown and isolation (1 hour)

**Step 1.1**: Confirm preconditions
- [ ] Load transferred to redundant chiller (verified at EPMS)
- [ ] Outdoor temperature acceptable for reduced cooling
- [ ] All personnel at stations with PPE

**Step 1.2**: Normal shutdown sequence
1. At Smart Panel: Menu > Shutdown > Normal Stop
2. Chiller reduces load to 5% (gradual)
3. Compressor spins down (2-3 minutes)
4. Wait for "STOPPED" status on panel

**Step 1.3**: Isolate chiller from chilled water loop
1. Close chilled water supply valve (CWS-1)
2. Close chilled water return valve (CWR-1)
3. Verify pressure bleed on loop side
4. Drain service line (minimize water loss)

**Step 1.4**: Isolate chiller from condenser water loop
1. Close condenser water supply valve (CDWS-1)
2. Close condenser water return valve (CDWR-1)
3. Open air bleed at highest point

**Step 1.5**: Electrical isolation
1. Open VSD disconnect at chiller
2. Open main feeder at switchgear
3. Verify zero voltage at VSD terminals
4. Apply LOTO (T1-SAF-LOTO-001)

### Phase 2 — Inspections (3 hours)

**Step 2.1**: Smart Panel log review
- Download last 90 days of operating data
- Review for any anomaly trends:
  - Compressor speed excursions
  - Bearing gap drift
  - Refrigerant pressure trends
  - Approach temperature increasing (fouling indicator)
- Document findings

**Step 2.2**: Magnetic bearing inspection
- Verify de-levitation state (shaft on mechanical supports)
- Visually inspect bearing housings for contamination
- Measure bearing clearances (verify within spec)
- Clean any particulate with approved non-magnetic tools
- Record measurements

**Step 2.3**: Compressor external inspection
- Visual inspection for oil residue (should be none — magnetic bearings
  are oil-free; any residue suggests seal issue)
- Flange torque verification on refrigerant connections
- Cable and connector integrity check
- Vibration sensor mounting verification

**Step 2.4**: Refrigerant system inspection
- Refrigerant charge verification from Smart Panel log
- Pressure check at service ports (within 2% of historical)
- Electronic leak check at:
  - Compressor discharge flange
  - Condenser inlet/outlet flanges
  - Evaporator inlet/outlet flanges
  - All service valves
- Record leak test results (must be zero detection)

**Step 2.5**: Evaporator inspection
- Open access port (with isolation confirmed)
- Visual inspection of tube surfaces for fouling
- Ultrasonic thickness check at 3 locations (non-destructive)
- Close access port with new gasket, torque to spec

**Step 2.6**: Condenser inspection
- Condenser water chemistry analysis (separate sample):
  - pH: target 7.5-8.5
  - Conductivity: <3000 µS/cm
  - Iron: <1 ppm
  - Biocide residual: present at spec concentration
- Visual inspection of tube ends at head (if accessible)
- Fouling assessment based on approach temperature trend
- Recommend chemical cleaning if approach increased >20% since last PM

**Step 2.7**: Control system inspection
- Smart Panel self-test (Menu > Diagnostics > Self-Test)
- Sensor accuracy verification (compare to portable reference)
- VSD panel door seals, gaskets, ventilation screens
- Emergency stop button test (must trigger compressor trip)

**Step 2.8**: Filter replacement (DLC side)
- Close isolation valves before and after filter
- Drain filter housing
- Replace 50-micron cartridge
- Vent trapped air before re-pressurizing
- Log filter change in `procedures` table

### Phase 3 — Startup and verification (1.5 hours)

**Step 3.1**: Remove LOTO
- Each technician removes personal lock
- Verify all tools and materials cleared
- Final walk-around inspection

**Step 3.2**: Restore loops
1. Open chilled water valves (CWS-1, CWR-1)
2. Open condenser water valves (CDWS-1, CDWR-1)
3. Vent both loops at high points
4. Verify flows established on loop monitors
5. Check for leaks at any re-connected joints

**Step 3.3**: Electrical restoration
1. Close main feeder at switchgear
2. Close VSD disconnect
3. Verify voltage at VSD (480V ±5%)
4. Wait 60 seconds for VSD precharge

**Step 3.4**: Chiller startup
1. At Smart Panel: Clear any alarms
2. Menu > Start > Normal
3. Observe 10-second pre-start self-test
4. Verify magnetic bearing levitation (shaft floats within spec)
5. VSD spin-up begins
6. Compressor reaches target speed within 3-5 minutes
7. Chilled water outlet temperature reaches 6.5°C within 10 minutes

**Step 3.5**: Load verification
- Ramp load from 20% to 80% over 15 minutes
- Observe:
  - Compressor speed tracks load
  - VSD current within spec
  - Magnetic bearing position stable
  - Refrigerant pressures within normal band
  - All alarms clear
- Record post-PM metrics for trend analysis

### Phase 4 — Documentation (30 minutes)

**Step 4.1**: Complete MOP record
- Pre-shutdown operating metrics
- Inspection findings (all items documented)
- Refrigerant leak test results
- Condenser water chemistry
- Post-startup operating metrics
- Any anomalies with corrective action plan

**Step 4.2**: Update tracking systems
- PostgreSQL `procedures` table entry
- Update shift report
- Close work order
- Send completion summary to facility manager

**Step 4.3**: Coordinate with second chiller
- Rebalance load between chiller 1 and chiller 2
- Target 50/50 split for efficiency
- Verify both chillers contributing to PUE calculation

## Acceptance criteria

MOP is complete when ALL of:
- [ ] All inspections executed and documented
- [ ] No refrigerant leaks detected
- [ ] Approach temperatures within normal range
- [ ] Magnetic bearings within spec
- [ ] Chiller online, load balanced
- [ ] No unresolved abnormalities
- [ ] Documentation in `procedures` table

## Failure modes and escalation

### Refrigerant leak detected

1. STOP work, isolate leak source if safe
2. Evacuate area if leak >0.5 kg estimated
3. Contact Johnson Controls certified technician
4. Report leak to environment compliance (regulatory requirement)
5. Do NOT restart chiller until repaired and recharged

### Magnetic bearing fault

1. Do NOT attempt to restart
2. Contact Johnson Controls service (factory-trained only)
3. Document fault codes from Smart Panel
4. Activate chiller 2 at 100% load (hold until repair)
5. Expect 1-2 week repair window

### Condenser heavy fouling

1. Schedule chemical cleaning within 30 days
2. Arrange cleaning with specialty contractor
3. Plan for additional 8-hour outage of this chiller
4. Adjust PM schedule for next cycle

### Water chemistry out of range

1. Immediate biocide dose adjustment
2. Investigate water treatment system
3. Increase monitoring frequency to weekly
4. Full chemical treatment review with water treatment contractor

## References

- York YZ Engineering Guide (T2-VEN-YK-CHI-YZ)
- LOTO procedure (T1-SAF-LOTO-001)
- Environment Canada F-Gas Regulation
- AHRI 550/590 (Chiller Performance Rating)
- a3semi Chiller PM Record Form: A3-OPS-FRM-028
- a3semi Refrigerant Inventory Log: A3-ENV-LOG-007
