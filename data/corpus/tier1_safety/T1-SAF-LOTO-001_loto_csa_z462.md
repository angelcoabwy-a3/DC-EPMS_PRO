---
doc_id: T1-SAF-LOTO-001
tier: 1
priority: critical
domain: electrical_safety
standard: CSA Z462
applies_to: all_energized_equipment
keywords: [loto, lockout, tagout, isolation, zero_energy, energized_work]
facility: A3-Alpha Toronto Area
---

# Lockout / Tagout (LOTO) Procedure

Authority: CSA Z462-21 Section 6 (Hazardous Electrical Energy Control)

## Purpose

Prevent unexpected energization, start-up, or release of stored energy during
service, maintenance, or repair of electrical equipment at A3-Alpha Toronto
Area. LOTO is the single most critical safety control for any energized
equipment work and is MANDATORY before any of the following:

- Opening any panel ≥50 V
- Removing any cover on a PDU, RPP, UPS, or switchgear
- Servicing DLC pumps, chillers, or CRAH units with electrical isolation
- Battery string maintenance on UPS Galaxy VX systems
- Generator maintenance, transfer switch work

## Scope boundaries

- LOTO is NOT optional. "Quick check" without LOTO is a work stop offense.
- LOTO applies even if the equipment is already de-energized upstream —
  you must verify and lock the isolation point at the equipment itself.
- LOTO does not replace arc-flash PPE for verification steps; see arc-flash
  boundary rules in T1-SAF-ARC-002.

## The 6-step LOTO sequence

### Step 1 — Preparation and notification

Before any work begins:

1. Review the equipment drawings and electrical single-line diagram.
2. Identify ALL energy sources: primary feed, redundant feed (2N), control
   power, capacitor banks, UPS backfeed, generator backfeed.
3. Notify all affected personnel (operators, adjacent teams, shift lead).
4. Post the LOTO permit on the shift board.
5. Confirm a qualified person is available as the second set of eyes.

### Step 2 — Equipment shutdown

Normal operational shutdown per vendor procedure:

- For chillers: follow York YZ shutdown sequence — do not simply trip power.
- For UPS: transfer to maintenance bypass BEFORE electrical isolation.
- For RPPs/PDUs: de-energize the downstream breakers before the main.

Rushing this step causes equipment damage and extends the outage.

### Step 3 — Energy isolation

Open the disconnect(s) for every identified energy source. For 2N facilities
like A3-Alpha, this means BOTH the A-side and B-side feeds of any given load.
Each isolation point must be physically operated — do not rely on remote/
programmatic trips.

### Step 4 — Lockout application

Apply a lock to each isolation point:

- Personal lock: each worker applies their own lock. One worker = one lock
  per isolation point.
- Group lock: for multi-worker tasks, use a lockbox. Each worker places
  their personal lock on the lockbox. Work cannot resume until the LAST
  personal lock is removed.
- Tag: every lock carries a tag with worker name, date, scope of work, and
  contact number. Unsigned locks are rejected.

### Step 5 — Release of stored energy

Electrical isolation does not eliminate stored energy:

- UPS DC bus: wait minimum 5 minutes after isolation; short the DC link with
  the factory-supplied discharge tool before work begins.
- Capacitor banks: wait per nameplate (typically 5 minutes), then verify
  with a grounding stick.
- Hydraulic / pneumatic actuators (louvres, dampers): bleed to atmosphere.
- Thermal stored energy: DLC coolant in hot loops may retain heat for >30
  minutes — allow cooldown or isolate return valves.

### Step 6 — Verification of zero-energy state

Mandatory test before any contact:

1. Use a meter rated for the voltage class (CAT IV 1000V for 480V feeds).
2. Test the meter on a known live source (e.g., adjacent phase).
3. Test the isolated equipment — phase-to-phase, phase-to-ground, all
   combinations.
4. Re-test the meter on the known live source.
5. Document the readings in the LOTO permit.

If any voltage is detected: STOP. Do not proceed. Re-investigate isolation
points. Common culprit: backfeed from UPS bypass or a shared neutral.

## Re-energization (reverse sequence)

1. Ensure area is clear of tools and personnel.
2. Remove personal locks — each worker removes their own.
3. Close disconnects in reverse order: downstream first, then main.
4. Monitor for abnormal conditions during re-energization.
5. Log completion in the shift report and close the LOTO permit.

## Documentation requirement

Every LOTO event generates the following records:

- Signed LOTO permit (kept on file 3 years)
- Entry in the PostgreSQL `incidents` table with source=LOTO and the
  `physics_json` field containing {feeder_id, locks_applied, verified_zero}
- Shift report entry with duration and outcome

## Common failure modes and prevention

| Failure | Cause | Prevention |
|---------|-------|------------|
| Missed backfeed | Incomplete energy source inventory | Use single-line diagram, two-person review |
| Lock defeated | Using non-personal lock | Enforce one-worker-one-lock rule |
| Verified without calibrated meter | Meter drift | Monthly meter calibration log |
| Re-energization with tools in | Rushed re-start | Mandatory 5-minute area sweep |

## Training and recertification

- Initial LOTO training: 8 hours classroom + 4 hours supervised field.
- Recertification: every 12 months or after any LOTO-related near-miss.
- Employer (a3semi) maintains training records per CSA Z462 §4.3.

## References

- CSA Z462-21, Workplace Electrical Safety, Section 6
- NFPA 70E-2024, Article 120 (Establishing an Electrically Safe Work Condition)
- OSHA 29 CFR 1910.147 (Control of Hazardous Energy)
- a3semi LOTO Permit Form: A3-SAF-FRM-002
