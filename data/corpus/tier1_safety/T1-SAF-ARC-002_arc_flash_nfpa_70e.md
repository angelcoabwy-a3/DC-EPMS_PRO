---
doc_id: T1-SAF-ARC-002
tier: 1
priority: critical
domain: electrical_safety
standard: NFPA 70E
applies_to: all_energized_equipment_above_50V
keywords: [arc_flash, ppe, boundary, incident_energy, category, calorie]
facility: A3-Alpha Toronto Area
---

# Arc Flash Hazard Analysis and PPE Requirements

Authority: NFPA 70E-2024 Article 130, CSA Z462-21 Section 4

## Purpose

Protect personnel from thermal effects of an arc flash event when energized
work cannot be avoided. Arc flash produces heat up to 19,400°C, pressure
waves, toxic gases, and molten metal ejecta. This procedure defines PPE
selection, approach boundaries, and work restrictions at A3-Alpha Toronto
Area.

## Principle: establish an electrically safe work condition FIRST

Arc flash PPE is the last line of defense. The primary control is
de-energization via LOTO (see T1-SAF-LOTO-001). Energized work is permitted
ONLY when:

- De-energization creates additional or greater hazard
- Task is infeasible in a de-energized state (diagnostic testing, voltage
  verification, adjacent-phase work)
- An Energized Work Permit is signed by the facility manager

## Incident energy and PPE categories

PPE is selected based on the calculated incident energy at the working
distance. At A3-Alpha, incident energy studies are refreshed every 5 years
or after significant single-line changes.

| Category | Incident Energy | Typical Equipment | Key PPE |
|----------|-----------------|-------------------|---------|
| CAT 1 | 4 cal/cm² | Low-voltage (<240V) control panels | Arc-rated shirt + pants, safety glasses |
| CAT 2 | 8 cal/cm² | 480V RPP panels, small PDUs | Arc-rated coverall + face shield + balaclava |
| CAT 3 | 25 cal/cm² | 600V switchgear, UPS input | Arc flash suit + hood, Class 0 gloves |
| CAT 4 | 40 cal/cm² | Utility tie, transformer secondary | Arc flash suit + hood rated 40 cal/cm² |

All panels at A3-Alpha carry an arc flash label per NFPA 70E Article 130.5
with the category, working distance, and boundary distances clearly printed.

## Approach boundaries

Three concentric boundaries around energized equipment:

### 1. Arc Flash Boundary

The distance at which a person without PPE would receive 1.2 cal/cm² — the
threshold for second-degree burns. Beyond this boundary, no arc-rated PPE
is required.

At A3-Alpha Toronto Area:
- Typical RPP (480V): 0.9 m
- UPS Galaxy VX input switchgear: 1.8 m
- Utility tie (27 kV): 4.6 m

### 2. Limited Approach Boundary

Only qualified persons may cross this boundary. Unqualified persons
require an escort and continuous supervision.

### 3. Restricted Approach Boundary

Only qualified persons in arc-rated PPE with an Energized Work Permit may
cross. Defines the zone where inadvertent contact with an energized part
is likely.

## PPE selection protocol

Before any work inside the Arc Flash Boundary:

1. Read the equipment label to identify the category.
2. Select PPE matching OR exceeding the labeled category.
3. Inspect PPE before use: no tears, no contamination, no compressed
   fibres (arc-rated fabric loses rating when compressed by straps or
   contact with hot surfaces).
4. Don PPE in the correct sequence: inner layers first, outer coverall,
   balaclava, hood, gloves, boots.
5. Confirm PPE integrity with the second person (two-person rule).

## Class 0 / Class 2 rubber insulating gloves

Voltage-class gloves are required whenever the Restricted Approach
Boundary is crossed:

- Class 0: ≤1000 V AC — used for 480V and below work
- Class 2: ≤17,000 V AC — used for 4160V backup distribution
- Leather protector gloves MUST be worn over rubber gloves
- Air test gloves before each use (roll the cuff, observe for leaks)
- Dielectric test every 6 months, recorded per CSA Z462 §4.3.3

## Two-person rule

Energized work above 50V never proceeds alone:

- One qualified worker performs the task
- A second qualified worker stands outside the Arc Flash Boundary
  monitoring for abnormal conditions and carrying a hook stick for
  emergency equipment de-energization
- Neither person leaves until the task is complete and equipment is
  re-energized or locked out

## Restrictions — no-go tasks at A3-Alpha

The following tasks are PROHIBITED as energized work regardless of PPE:

- Bolted fault tests (arc forcing)
- Disassembly of bus structures
- Work inside switchgear during source transfer
- Any task where incident energy exceeds 40 cal/cm² (requires remote
  racking tools or scheduled outage)

## Incident response — if an arc flash occurs

1. PULL fire alarm to trigger automatic shutdown of affected feeder
2. Evacuate area — shock wave can propagate 10+ meters
3. Do NOT touch the victim until power confirmed removed (PDU + UPS
   backfeed)
4. Call 911 and facility medical response
5. Preserve scene for post-incident investigation
6. All personnel undergo medical evaluation, even without visible injury
7. Formal investigation within 48 hours per ISO 22301 P1 timeline

## Documentation

Each energized work event requires:

- Signed Energized Work Permit (a3semi form A3-SAF-FRM-008)
- Incident energy label photo attached to permit
- PPE checklist signed by both workers
- Entry in `incidents` table with source=ENERGIZED_WORK
- Post-work review in next shift report

## References

- NFPA 70E-2024, Article 130 (Work Involving Electrical Hazards)
- CSA Z462-21, Section 4 (Safety-Related Work Practices)
- IEEE 1584-2018 (Guide for Performing Arc Flash Hazard Calculations)
- a3semi Incident Energy Study: A3-SAF-STU-001 (current rev: 2025.3)
