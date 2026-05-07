---
doc_id: T1-SAF-FIR-004
tier: 1
priority: critical
domain: fire_life_safety
standard: NFPA 72, NFPA 2001, NFPA 12
applies_to: [vesda_systems, fm_200, water_mist, fire_detection]
keywords: [vesda, laserscanner, fm200, co2_suppression, smoke_detection, pre_alarm]
facility: A3-Alpha Toronto Area
---

# Fire Detection and Suppression — VESDA + FM-200 / Water Mist

Authority: NFPA 72 (Fire Alarm Code), NFPA 2001 (Clean Agent), NFPA 12 (CO₂)

## Overview — A3-Alpha fire protection architecture

A3-Alpha Toronto Area uses a multi-tier fire protection strategy:

1. **Very Early Warning** — VESDA LaserSCANNER aspirating smoke detection
   across all IT halls, UPS rooms, and battery rooms
2. **Early Warning** — spot-type photoelectric detectors at ceiling and
   under-floor
3. **Pre-action suppression** — water mist (Marioff HI-FOG) in IT halls
4. **Clean agent** — FM-200 (HFC-227ea) in the MEP (Mechanical/Electrical/
   Plumbing) room and network core
5. **CO₂ total-flooding** — tape library and cable vault only

## VESDA LaserSCANNER — the first line of defense

VESDA draws air samples through pipe networks to a central photometric
analyzer. Typical sensitivity at A3-Alpha: 0.003% obscuration/meter — orders
of magnitude more sensitive than spot detectors.

### Alarm thresholds

| Level | Threshold | Response |
|-------|-----------|----------|
| Alert | 0.003 %/m | Local audible alarm, EPMS notification |
| Action | 0.01 %/m | Facility fire panel notification, EPMS incident severity=warning |
| Fire 1 | 0.05 %/m | Evacuation sequence starts, HVAC shutdown to affected zone |
| Fire 2 | 0.15 %/m | Full evacuation alarm, pre-action system armed, 9-1-1 auto-dial |

### VESDA testing schedule

- Daily: review alarm history log for drift
- Weekly: smoke button test (manual smoke injection at test port)
- Monthly: bypass test of each pipe network
- Semi-annual: full flow rate verification per NFPA 72 §14.4.5
- Annual: comprehensive inspection, laser calibration, sensor replacement
  if cumulative run-time >60,000 hours

## FM-200 total-flooding — MEP room only

FM-200 (HFC-227ea) is a clean agent that extinguishes fire by heat absorption
(not oxygen displacement). Safe for personnel at design concentration (7%).

### Discharge sequence

1. Two-detector coincidence (cross-zoned): requires VESDA Action + spot
   detector before discharge arms
2. 30-second pre-discharge delay with audible countdown (allows occupant
   evacuation and system abort via manual hold)
3. HVAC dampers close, fans stop (maintains concentration)
4. Agent discharges within 10 seconds, achieving 7% concentration
5. Hold time: 10 minutes minimum to prevent reignition

### Post-discharge re-entry

Re-entry requires:

- Atmospheric test: FM-200 concentration <0.1% AND oxygen 19.5-23.5%
- Ventilation complete (typically 20+ air changes)
- Fire watch posted for minimum 60 minutes after re-entry
- Source of fire identified and corrected before re-arming

## CO₂ total-flooding — tape library and cable vault

CO₂ extinguishes by oxygen displacement — LETHAL to personnel at design
concentration (34%).

### Critical safety interlocks

- Pre-discharge siren and strobe: 30-second warning
- Manual hold stations at every exit
- Mandatory CO₂ lockout during ALL entries (see T1-SAF-CSE-003)
- O₂ monitor with alarm in each room
- Post-discharge: NO re-entry until CO₂ <0.5% AND O₂ >20.9%, confirmed by
  SCBA-equipped rescue team

### Why CO₂ here and not elsewhere

CO₂ is used in tape library because the storage media is sensitive to
water, residue from clean agents, or particulates. It is NOT used in
occupied spaces — the health hazard is significant and non-negotiable.

## Water mist (Marioff HI-FOG) — IT halls

Water mist protects IT halls at A3-Alpha:

- Discharge droplet size <200 microns
- Forms a fog that cools the fire without drenching servers
- Pre-action design: pipes are DRY until fire is confirmed by double-
  interlock (smoke + heat)
- Post-discharge: system auto-resets after zone clear

Water mist is safer for the 118 Blackwell NVL72 racks than traditional
sprinkler: the mist cools and extinguishes a fire at one rack without
water-damaging adjacent powered racks.

## Periodic test procedure — VESDA annual

NFPA 72 requires annual comprehensive testing. A3-Alpha schedule: 2nd
Saturday of each April.

### Pre-test preparation (T-24 hours)

1. Coordinate with Morpheus OT to suppress spurious-alarm notifications
2. Notify all affected personnel, post testing schedule
3. Set fire alarm panel to TEST mode
4. Set fire suppression systems to MANUAL
5. Notify 9-1-1 dispatcher that scheduled testing is occurring

### Test execution

1. Inject calibrated smoke test stimulus at farthest sampling hole
2. Record transport time (must be <60 seconds per NFPA 72 §14.4.5.5)
3. Verify Alert, Action, Fire 1, Fire 2 threshold crossings sequentially
4. Repeat at 25%, 50%, 75% pipe lengths to validate flow distribution
5. Record baseline air flow rate (must be within ±20% of design)

### Post-test

1. Restore fire panel from TEST to NORMAL
2. Restore suppression systems from MANUAL to AUTO
3. Verify restoration with a test signal (not a full discharge)
4. Notify 9-1-1 dispatcher that testing is complete
5. File inspection report with a3semi compliance office
6. Log in PostgreSQL `procedures` table with type=VESDA_ANNUAL

## Common failures and troubleshooting

| Symptom | Likely cause | Corrective action |
|---------|--------------|--------------------|
| Transport time >60s | Pipe blockage or leak | Pressure test each pipe branch |
| Flow rate drift | Fan failure or filter loading | Replace filter, verify fan RPM |
| Nuisance alarms | Airborne dust, diesel particulate | Verify source, increase filter grade |
| Laser drift | Sensor aging | Recalibrate, consider replacement |

## Documentation

Every fire-protection event (alarm, test, maintenance, discharge) requires:

- Entry in PostgreSQL `incidents` table
- Updated inspection log in `procedures` table
- Photographic record of panel state before and after
- Signature of qualified fire alarm technician per NFPA 72 §10.4

## References

- NFPA 72-2022 (National Fire Alarm and Signaling Code)
- NFPA 2001-2022 (Clean Agent Fire Extinguishing Systems)
- NFPA 12-2022 (Carbon Dioxide Extinguishing Systems)
- NFPA 750-2020 (Water Mist Fire Protection Systems)
- VESDA LaserSCANNER installation manual (Xtralis document 10325_13)
- a3semi Fire Protection Annual Test Form: A3-SAF-FRM-022
