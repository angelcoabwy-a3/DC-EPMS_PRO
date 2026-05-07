---
doc_id: T1-SAF-CSE-003
tier: 1
priority: critical
domain: physical_safety
standard: OSHA 29 CFR 1910.146, CSA Z1006
applies_to: [under_floor_plenum, cable_trays, battery_rooms, cooling_sumps]
keywords: [confined_space, entry_permit, atmospheric_test, rescue_plan]
facility: A3-Alpha Toronto Area
---

# Confined Space Entry Procedure

Authority: OSHA 29 CFR 1910.146, CSA Z1006-16

## Definition

A confined space at A3-Alpha Toronto Area is any area that:
- Is large enough for a person to enter
- Has limited or restricted means of entry/exit
- Is not designed for continuous occupancy

Permit-required confined spaces (PRCS) additionally have:
- Potential hazardous atmosphere
- Material that could engulf the entrant
- Internally converging walls or downward-sloping floor
- Any other serious safety hazard

## A3-Alpha PRCS inventory

| Location | Type | Hazards |
|----------|------|---------|
| Under-floor plenum (hall A, B, C) | PRCS | CO₂ inerting (gas suppression backup), low-O₂ pockets behind CRAH units |
| Battery room 1 and 2 | PRCS | Hydrogen accumulation during UPS float charge (potential explosive >4% LEL) |
| Chilled water sump | PRCS | Drowning hazard, biological growth, confined geometry |
| Cable tray vault | PRCS | Dust, heat accumulation, limited egress |
| Generator day-tank vault | PRCS | Diesel vapor, fuel exposure |

## Entry permit workflow

NO entry without a signed permit. Permits are single-use, single-shift,
and expire at end-of-shift.

### Pre-entry checklist (all items required)

1. Entry permit completed: entrant(s), attendant, supervisor signatures
2. Atmospheric testing completed within 15 minutes of entry:
   - Oxygen: 19.5% to 23.5%
   - LEL (lower explosive limit): <10%
   - CO: <25 ppm
   - H₂S: <10 ppm
3. Ventilation active if atmosphere marginal
4. Communication established (radio + visual if possible)
5. Rescue team notified and standing by
6. Equipment isolated per LOTO if applicable (T1-SAF-LOTO-001)
7. Fire suppression system: set to MANUAL for the duration of the entry

### During entry

- Attendant remains at entry point; never leaves station
- Continuous atmospheric monitoring (not just pre-entry)
- Entrant reports check-ins every 15 minutes
- ANY deviation (alarm, dizziness, loss of contact) triggers immediate
  evacuation

### Post-entry

1. All entrants accounted for
2. Permit signed off by attendant and supervisor
3. Atmospheric monitor downloaded — readings archived for 3 years
4. Fire suppression restored to AUTO with documented verification
5. Entry logged in PostgreSQL `incidents` table with
   source=CONFINED_SPACE_ENTRY

## Hydrogen gas — special rules for battery rooms

UPS Galaxy VX systems at A3-Alpha use sealed VRLA batteries. During high
charge rates (post-outage recovery), hydrogen can evolve and accumulate:

- Continuous ventilation must maintain H₂ <1% LEL (4000 ppm)
- H₂ sensors trigger audible/visual alarm at 25% LEL (1000 ppm)
- At 50% LEL (2000 ppm): automatic shutdown of charging system via
  Morpheus OT integration
- NO smoking, no sparking tools, no non-intrinsically-safe electronics
  within battery room at any time

## CO₂ inerting — fire suppression interaction

A3-Alpha's data hall uses pre-action water mist; however, the tape library
and cable vault use CO₂ total-flooding. Entry into CO₂-protected spaces
requires:

- Discharge the system to MANUAL mode before entry
- Post a physical lockout on the discharge valve
- Post "FIRE SUPPRESSION DISABLED" placard at entry
- Second worker monitors for fire alarm activations during entry
- Restore to AUTO within 15 minutes of entry completion

Failure to restore suppression to AUTO is a critical incident, logged as
severity=critical.

## Rescue plan

Every entry permit specifies the rescue method:

1. Non-entry rescue (preferred): entrant wears retrieval harness, attendant
   pulls entrant out via lifeline without entering
2. Entry rescue: trained rescue team (minimum 2 persons) with SCBA
3. External rescue: facility 911 response — expect 6-8 minute arrival

Non-entry rescue is mandatory for all under-floor plenum and cable tray
entries unless physical geometry prevents a straight lifeline path.

## Atmospheric monitor calibration

The MSA Altair 4XR monitors used at A3-Alpha require:

- Bump test before each shift (known gas challenge)
- Full calibration every 6 months
- Sensor replacement at end of 2-year service life
- Calibration records stored in PostgreSQL `procedures` table with
  type=CALIBRATION and equipment=ALTAIR_4XR_{serial}

## Training

- Initial confined space training: 16 hours (classroom + practical)
- Annual refresher required
- Rescue team: additional 24 hours plus quarterly drills
- Supervisor training: 8 hours supervisor-specific modules

## References

- OSHA 29 CFR 1910.146 (Permit-Required Confined Spaces)
- CSA Z1006-16 (Management of Work in Confined Spaces)
- NFPA 12 (CO₂ Extinguishing Systems)
- ANSI/ISEA Z87.1 (Eye and Face Protection)
- a3semi Confined Space Entry Permit: A3-SAF-FRM-014
