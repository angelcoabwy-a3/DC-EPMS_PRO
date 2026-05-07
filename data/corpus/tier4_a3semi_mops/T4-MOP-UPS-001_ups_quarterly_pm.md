---
doc_id: T4-MOP-UPS-001
tier: 4
priority: high
doc_type: MOP
domain: ups_maintenance
equipment: UPS Galaxy VX 750 kVA (both A and B)
standard_refs: [CSA Z462, NFPA 70E, IEEE 1188, IEC 62040]
applies_to: [planned_maintenance, ups_quarterly]
keywords: [mop, ups_pm, battery_impedance, capacitor_inspection, quarterly]
facility: A3-Alpha Toronto Area
duration: 4 hours per unit
personnel_required: 2 qualified
---

# MOP: UPS Galaxy VX Quarterly Preventive Maintenance

**Procedure ID**: T4-MOP-UPS-001
**Revision**: 2026.1
**Approved by**: Facility Manager, a3semi
**Last executed**: (logged in `procedures` table)

## Purpose

Quarterly preventive maintenance on the Schneider Galaxy VX 750 kVA UPS
units at A3-Alpha Toronto Area. Maintains reliability, captures aging
signals early, satisfies Schneider warranty requirements, and documents
compliance with facility operating standards.

## Scope

- UPS A (A3-MEP-UPS-001) and UPS B (A3-MEP-UPS-002)
- Performed on ONE unit at a time, never both simultaneously
- While one unit is in maintenance bypass, the other carries full load
- Scheduled during low-load periods (typically Saturday 02:00-06:00)

## Pre-work requirements

### 24 hours before

1. Submit maintenance work order via a3semi WO system
2. Notify customers via SLA communication template
3. Pre-stage spare parts: air filters, terminal cleaning supplies
4. Verify other UPS is in full health (no active alarms)
5. Confirm both qualified technicians available

### 1 hour before

1. Brief team on scope, hazards, and contingencies
2. Verify PPE available: NFPA 70E Category 2 (8 cal/cm²)
3. Review LOTO procedure (T1-SAF-LOTO-001)
4. Set fire suppression system in MEP room to MANUAL
5. Establish NOC contact schedule (check-in every 30 minutes)

## Hazards and controls

| Hazard | Control |
|--------|---------|
| Arc flash (800 A at 480V) | Category 2 PPE, test-before-touch |
| Electrical shock (480V, lethal) | LOTO verified before any contact |
| Battery acid | Face shield, acid-resistant gloves, neutralizer on hand |
| Heavy battery cells (35 kg each) | Lifting equipment if batteries moved |
| Compressed air | Safety glasses, earplugs near vent |
| Load transfer risk | Verify B-side healthy before isolating A-side |

## Tools and materials

- CAT IV 1000V rated multimeter (calibrated within 12 months)
- Torque wrench (with current calibration certificate)
- Insulation resistance tester (Megger, >1000V)
- Infrared thermographic camera
- Air filter replacements (Schneider PN 870-6023)
- Terminal cleaning supplies (NO-OX-ID A)
- Two personal locks per technician
- Lockout tags pre-printed with operator name

## Procedure

### Phase 1 — Transfer to maintenance bypass (30 minutes)

**Step 1.1**: At UPS A front panel, verify load transfer readiness:
- [ ] Load is within 125% of rating
- [ ] No active alarms
- [ ] UPS B showing "ONLINE" and full health
- [ ] Utility power quality verified (voltage, frequency within ±5%)

**Step 1.2**: Don Category 2 PPE (two-person check):
- [ ] Arc-rated coverall (8 cal/cm²)
- [ ] Face shield with arc rating
- [ ] Balaclava (arc-rated)
- [ ] Class 0 rubber gloves with leather protectors
- [ ] Safety boots with dielectric rating

**Step 1.3**: Execute bypass transfer:
1. UPS Menu > Transfer > Manual Bypass
2. Verify static bypass engagement: front panel shows "STATIC BYPASS"
3. Close maintenance bypass breaker (key interlock)
4. Open UPS A output breaker (key interlock)
5. Verify: front panel shows "MAINT BYPASS", load continues uninterrupted

**Step 1.4**: Apply LOTO to UPS A input:
1. Open UPS A input breaker at switchgear
2. Apply personal lock and tag (each technician)
3. Verify zero voltage at UPS input terminals:
   - Phase A to ground: ___ V (expect 0)
   - Phase B to ground: ___ V (expect 0)
   - Phase C to ground: ___ V (expect 0)
4. Meter cross-check on known live source
5. Sign LOTO permit

**Step 1.5**: Allow DC bus to discharge:
- Wait minimum 5 minutes
- Verify DC bus voltage <50 V at discharge terminals

### Phase 2 — Inspection and maintenance (2.5 hours)

**Step 2.1**: Visual inspection
- [ ] All covers secured, no damage
- [ ] No burning odor, no discoloration
- [ ] Cable insulation intact
- [ ] No liquid stains or battery leaks
- [ ] Cleanliness adequate (dust <1 mm accumulation)

**Step 2.2**: Air filter replacement
- Open front access panels
- Remove and discard old filter
- Inspect fan blades for dust buildup (clean with compressed air)
- Install new filter (Schneider PN 870-6023)
- Verify correct orientation (airflow arrow)

**Step 2.3**: Terminal inspection and torque verification
For each terminal (input, output, neutral, ground):
1. Thermographic scan before disconnect (baseline)
2. Disconnect termination
3. Visual inspection for oxidation, discoloration
4. Clean with NO-OX-ID A compound if oxidation present
5. Torque to spec:
   - 480V input/output lugs: 50 N·m
   - Control terminals: 2.5 N·m
   - Ground bus: 35 N·m
6. Re-verify torque after 5-minute settling
7. Record torque values in MOP log

**Step 2.4**: Capacitor inspection
DC link capacitors and output filter capacitors:
- [ ] Visual inspection for bulging (none acceptable)
- [ ] No electrolyte leaks
- [ ] Temperature within 10°C of ambient (rule of thumb)
- [ ] Mounting torque verified

**Step 2.5**: Battery maintenance
For each of 4 battery strings:
- Terminal cleanliness and torque
- Individual cell voltage recorded (float = 2.25V ±0.03V)
- Impedance test via built-in monitor (strings must match within ±15%)
- Ambient temperature at battery location (25°C ±5°C target)
- Visual inspection for swelling or electrolyte leak

Record battery metrics to `procedures` table for trend analysis.

**Step 2.6**: Insulation resistance test
With UPS de-energized:
- Phase-to-ground (each phase): minimum 100 MΩ
- Phase-to-phase (all combinations): minimum 100 MΩ
- Low readings (<50 MΩ) indicate insulation degradation — escalate

**Step 2.7**: Thermographic scan of internal bus
Re-connect all terminations. Before re-energization, perform IR scan:
- Baseline temperatures recorded
- Anomalies (>10°C differential between phases) require investigation
- Signed report attached to MOP

### Phase 3 — Return to service (30 minutes)

**Step 3.1**: Remove LOTO
- Each technician removes personal lock
- Verify all tools and personnel clear of equipment
- Final visual inspection

**Step 3.2**: Energize UPS input
- Close UPS A input breaker at switchgear
- Wait 30 seconds for rectifier to build DC bus
- Monitor for any alarms on front panel

**Step 3.3**: UPS self-test
- At front panel: Menu > Start > Self-Test
- Observe 30-second self-test sequence
- All parameters must show GREEN

**Step 3.4**: Return to online mode
1. Close UPS A output breaker (key interlock)
2. Open maintenance bypass breaker (key interlock)
3. At front panel: Menu > Operating Mode > Online
4. Verify: front panel shows "ONLINE", load is on UPS A
5. Load distribution check: UPS A and UPS B each at ~50% (2N)

**Step 3.5**: Verification
- [ ] No alarms on either UPS
- [ ] Battery charging has begun (float voltage building)
- [ ] Load distribution balanced between A and B
- [ ] EPMS shows both UPS as healthy
- [ ] PostgreSQL `procedures` table updated with completion

### Phase 4 — Documentation (30 minutes)

**Step 4.1**: Complete MOP record
- Torque values for all terminations
- Battery voltage and impedance readings
- Insulation resistance measurements
- Thermographic image references
- Any anomalies noted with corrective actions

**Step 4.2**: Update tracking systems
- PostgreSQL `procedures` table entry
- Update shift report
- Return fire suppression to AUTO mode
- Close work order
- Restore customer notifications (if any)

**Step 4.3**: Debrief
- Review with second technician
- Any deviations from MOP noted for next revision
- Lessons learned captured in debrief log

## Acceptance criteria

MOP is complete when ALL of:
- [ ] All inspection and test steps executed and documented
- [ ] No unresolved abnormalities
- [ ] UPS A online, carrying proportional load
- [ ] Both UPS A and B healthy per EPMS
- [ ] LOTO removed, fire suppression returned to AUTO
- [ ] Documentation filed in `procedures` table

## Emergency procedures during MOP

### If UPS B fails during UPS A maintenance

Priority 1 scenario. Response:
1. STOP all MOP work immediately
2. Transfer UPS A back to online mode (if safe)
3. If UPS A cannot be restored: load on maintenance bypass (no protection)
4. Activate EOP-001 (loss of UPS redundancy) — see T4-EOP-UPS-001
5. Contact facility manager
6. Extend maintenance window until redundancy restored

### If arc flash indicator triggered

1. STOP work, evacuate beyond arc flash boundary
2. Do NOT approach until power de-energized
3. Contact NOC: 911 and facility response
4. Preserve scene for investigation
5. All personnel undergo medical evaluation

### If battery leak discovered

1. Evacuate battery room to prevent acid exposure
2. Don acid PPE (face shield, apron, neoprene gloves)
3. Apply neutralizer (sodium bicarbonate) to contain spread
4. Do not disturb leaking cell — leave for vendor service
5. Document and open HAZMAT incident

## Post-MOP monitoring

For 48 hours after MOP:

- NOC monitors both UPS for any alarms or anomalies
- Battery charge rate tracked (should reach float within 4 hours)
- Any anomaly during monitoring triggers investigation
- 48-hour report filed in `procedures`

## References

- Schneider Galaxy VX Operation Manual (T2-VEN-SE-UPS-GVX)
- LOTO procedure (T1-SAF-LOTO-001)
- Arc flash PPE procedure (T1-SAF-ARC-002)
- IEEE 1188-2020 (Battery Maintenance and Testing)
- a3semi UPS MOP Record Form: A3-OPS-FRM-024
