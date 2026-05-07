---
doc_id: T1-SAF-EPO-005
tier: 1
priority: critical
domain: emergency_response
standard: NFPA 75, NFPA 76, IEC 62040
applies_to: [epo_system, emergency_shutdown, total_isolation]
keywords: [epo, emergency_power_off, shunt_trip, dump_sequence, life_safety]
facility: A3-Alpha Toronto Area
---

# Emergency Power Off (EPO) — Activation and Recovery

Authority: NFPA 75 (Fire Protection of Information Technology Equipment),
NFPA 76 (Fire Protection of Telecommunications Facilities)

## Purpose

The Emergency Power Off (EPO) system provides a single manual action to
de-energize the entire A3-Alpha Toronto Area data hall during a life-
safety emergency. EPO is a LAST-RESORT measure — it causes total service
loss and potential hardware damage to the 118 Blackwell NVL72 racks.

## WHEN to activate EPO

EPO is ONLY activated for:

1. **Fire with electrical involvement** — fire inside energized switchgear,
   UPS, or PDU where fire suppression alone is insufficient
2. **Arc flash incident in progress** — victim trapped or unreachable
   without de-energization
3. **Electrocution in progress** — victim in contact with energized parts
   and cannot be safely removed
4. **Water intrusion** to energized equipment — flooding from chilled
   water leak, roof leak, or fire suppression discharge
5. **Major earthquake or structural failure** — if equipment integrity is
   compromised

## When NOT to activate EPO

Do not activate EPO for:

- Single rack or PDU fire (use targeted suppression)
- Small water leak (isolate affected zone only)
- UPS battery smoke (enable maintenance bypass, isolate battery string)
- Scheduled maintenance (use planned LOTO procedure)
- Alarm testing (use normal shutdown sequence)

Activating EPO when not required is a documented violation and triggers
a full root-cause investigation.

## A3-Alpha EPO system architecture

Three independent EPO circuits:

| Circuit | Coverage | Button location |
|---------|----------|-----------------|
| EPO-A | Hall A (Rack rows 1-8) | Main entry, emergency exit A, NOC desk |
| EPO-B | Hall B (Rack rows 9-16) | Main entry, emergency exit B, NOC desk |
| EPO-C | MEP room (UPS, PDU, switchgear) | MEP entry, emergency exit C, NOC desk |

Each EPO button is a break-glass station with tamper alarm. Activation
requires:

1. Lift the plastic cover
2. Press and hold the red button for 3 seconds
3. Audible alarm confirms activation

## EPO shutdown sequence (milliseconds to seconds)

t=0: Button pressed
t+10ms: Shunt trip signal sent to:
  - UPS Galaxy VX output breakers (instant isolation of affected hall)
  - Upstream main breakers at switchgear
  - Generator output breakers (if generator on-line)
t+50ms: IT load de-energized
t+100ms: HVAC shutdown signal sent (fans stop to prevent smoke propagation)
t+200ms: Fire alarm system receives EPO activation signal
t+500ms: EPMS logs EPO event to PostgreSQL incidents table with
  severity=critical, source=EPO_ACTIVATION
t+1s:    Facility 9-1-1 auto-dial initiated
t+2s:    NOC receives audible and visual EPO alarm
t+30s:   Expected first responder contact

## What the EPO DOES and DOES NOT cut

EPO cuts:
- All IT equipment power (PDU output)
- UPS output (but NOT battery float charge in separate circuits)
- HVAC fans and CRAH
- Non-emergency lighting

EPO does NOT cut:
- Emergency lighting (code-required, separate circuit)
- Fire alarm system (code-required, battery-backed)
- Fire suppression (code-required, isolated circuit)
- UPS battery room ventilation (hydrogen safety)
- EPO monitoring circuit itself

## Recovery from EPO activation

Never attempt quick recovery. The sequence below is MANDATORY:

### Phase 1 — Ensure safety

1. Confirm all personnel accounted for and evacuated from affected zone
2. Fire department and emergency medical services on scene
3. Root cause of EPO activation identified and neutralized
4. Facility manager authorizes restoration

### Phase 2 — Equipment inspection

All power equipment in affected zone must be inspected:

- Visual inspection of switchgear, UPS, PDU for damage
- Thermographic scan (IR camera) of all energized components
- Insulation resistance testing (megger) on all feeders
- Arc flash incident review if arc flash occurred
- UPS battery string voltage verification
- Sign-off by qualified electrician

### Phase 3 — Controlled re-energization

Sequence (reverse of EPO):

1. Main utility breaker → ON, verify voltage
2. Switchgear bus → energize, observe for faults
3. UPS input → energize (UPS starts in bypass mode)
4. UPS output → transfer to online mode after 5-minute warm-up
5. PDU → energize one rack row at a time (5-minute intervals)
6. HVAC → start, achieve target temperature before IT re-energization
7. IT load → servers power up per rack application team schedule

Full restoration of 16.8 MW load from EPO can take 45-90 minutes. This
is the expected RTO for an EPO event under ISO 22301.

### Phase 4 — Post-incident review

Mandatory within 48 hours per ISO 22301 P1 classification:

- Timeline reconstruction from EPMS logs and PostgreSQL incidents
- Root cause analysis (5-Why methodology)
- Corrective action identification
- Update procedures if gaps identified
- Regulatory notification if required (ESA for electrical incidents)

## EPO testing — annual

EPO circuits MUST be tested annually per NFPA 75. Live testing is NOT
permitted in production; instead:

- Simulator test: each EPO button disconnected from shunt trip, continuity
  verified, then reconnected
- Trip curve verification: breaker tested for proper shunt trip response
- Annunciation test: verify EPMS receives EPO signal
- Documentation: test report filed with a3semi compliance office

## Common mistakes to avoid

- Activating EPO as a "quick stop" for planned work — this damages
  equipment and triggers a full investigation
- Covering an EPO button to "prevent accidents" — violates code
- Silencing the EPO alarm before clearing the activation condition
- Attempting restoration before qualified personnel inspection complete
- Failing to log the event in PostgreSQL — creates an audit gap

## Training

- All NOC personnel, security, and facility staff: EPO awareness training
- Qualified electricians and supervisors: EPO system technical training
- Annual drills: tabletop exercise of EPO activation and recovery
- Post-drill debrief with improvement actions

## Documentation template

Every EPO event is documented with:

```
EPO Incident Report
-------------------
Incident ID:         (auto from incidents table)
Activation time:     YYYY-MM-DD HH:MM:SS UTC
Circuit(s) activated: EPO-A / EPO-B / EPO-C
Activator:           (name or "automatic from fire panel")
Reason:              (fire / arc flash / water / other)
Load affected:       (kW impacted)
Duration of outage:  (minutes from t=0 to full restoration)
Equipment damage:    (none / list)
Root cause:          (from post-incident review)
Corrective actions:  (list)
```

## References

- NFPA 75-2020 (Standard for the Fire Protection of Information Technology
  Equipment) §8.5 Disconnect Means
- NFPA 76-2020 (Standard for the Fire Protection of Telecommunications
  Facilities)
- IEC 62040-1 (UPS General and Safety Requirements)
- CSA 22.2 No. 107.3 (Uninterruptible Power Supplies)
- a3semi EPO Activation Report Template: A3-SAF-FRM-031
