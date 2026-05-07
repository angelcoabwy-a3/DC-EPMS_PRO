---
doc_id: T2-VEN-ST-PDU
tier: 2
priority: high
domain: power_distribution
vendor: Starline
equipment: Busway T5 Series 2500A
applies_to: [pdu_operation, busway_inspection, tap_boxes]
keywords: [starline, busway, pdu, tap_box, thermographic, rpp]
facility: A3-Alpha Toronto Area
---

# Starline Busway — T5 Series Power Distribution

Source: Starline Track Busway T5 Installation & Service Manual
Equipment: Starline T5 Series, 2500A, 480V 3-phase
Applicability: A3-Alpha MEP room to Hall A/B/C power distribution

## System overview

Starline busway provides high-current, flexible power distribution with
tap-off points (plug-in units) that can be added, moved, or reconfigured
without shutting down the busway. At A3-Alpha:

- 2 redundant busway runs (A-side and B-side) per hall
- Each busway: 2500A rated, 480V 3-phase, neutral+ground
- Feeds RPPs (Remote Power Panels) via tap boxes
- RPPs then distribute to PDUs at row and rack level

### Why busway for high-density

Traditional copper feeder cables at 2500A are:
- Extremely heavy (>50 kg/m for parallel conductors)
- Difficult to route, require large cable trays
- Inflexible (adding loads requires splicing)
- Higher impedance than busway at this current class

Starline busway advantages:
- Modular, plug-in tap boxes
- ~5x lower installed labor
- Lower impedance (better voltage regulation)
- Easy thermographic inspection
- Spares kept on-site for rapid replacement

## Tap box installation — zero-downtime procedure

Tap boxes can be added/removed while the busway is energized using
insulated tooling. This is a qualified-persons-only task per NFPA 70E.

### Adding a tap box

Prerequisites:
- Tap box rated for the required current (typically 100A or 200A)
- NFPA 70E Category 2 PPE minimum (8 cal/cm²), insulated tooling
- Two qualified workers (two-person rule)
- Maintenance window approved with facility manager

Procedure:
1. Don Category 2 PPE (arc-rated coverall, face shield, Class 0 gloves)
2. Verify tap box model matches busway current rating
3. Locate next available slot on the busway (slots spaced 300 mm)
4. Align tap box contacts with busway slots
5. Fully seat tap box using insulated lever (clicks into position)
6. Verify LED indicators: GREEN = connected, no fault
7. Energize downstream RPP breaker
8. Verify voltage at tap box output with qualified meter
9. Log installation in `procedures` table with equipment and location

### Removing a tap box

Reverse the procedure:
1. De-energize downstream load first (LOTO at RPP)
2. Verify zero voltage at tap box output
3. Use removal tool to release latches
4. Slide tap box out — contacts retract into insulated housing
5. Cover the busway slot with a blank plate

## Inspection schedule

### Monthly

- Visual inspection: any discoloration, scorching, loose covers
- LED status check on each tap box (all GREEN expected)
- Ambient temperature check (busway rated to 40°C ambient)
- Review any fault alerts from the integrated monitor

### Quarterly (critical)

- Full IR thermographic scan of every tap box and every busway joint
- Temperature rise tolerance per NFPA 70B Annex Q:
  - <10°C rise above ambient: normal
  - 10-20°C: monitor, investigate at next quarterly
  - 20-40°C: corrective action required within 30 days
  - >40°C: immediate corrective action, may require de-energization
- Tap box contact engagement force spot-check (5% sample)
- Busway joint torque verification (manufacturer spec)

### Annual

- All tap boxes: pull, inspect contacts, torque to spec, reinstall
- Busway joints: complete torque verification (all joints)
- Insulation resistance test (megger): all phases to ground, >100 MΩ
- Neutral and ground bond verification: <0.1 Ω
- Branch circuit coordination study review

### 5-year

- Comprehensive busway refurbishment inspection
- Consider tap box contact replacement (high-cycle slots)
- Update one-line diagram if any reconfigurations occurred

## Thermographic inspection — the right way

Thermography is the most important predictive maintenance technique for
busway. The inspection protocol:

### Equipment

- IR camera: FLIR T-series or equivalent, ±2°C accuracy
- Emissivity setting: 0.95 for painted busway surfaces
- Reflected apparent temperature: measured with aluminum foil target
- Distance and focus: within 1 meter, focused on hot spots

### Load requirement

- Minimum 40% of rated current at time of scan
- Higher load = better identification of high-resistance connections
- Coordinate with operations to schedule scans during peak IT load

### What to look for

- Phase-to-phase asymmetry: all 3 phases at similar temp is normal
- Phase hotter than others: suggests loose connection or high-resistance
  contact in that phase
- Joint hotter than adjacent busway: joint torque issue
- Tap box body temperature vs busway temperature: 5-10°C normal, more
  suggests tap box contact issue

### Documentation

Each scan produces:
- Thermographic images (archived in `procedures` table with photo refs)
- Temperature readings tabulated per tap box
- Trend analysis comparing to prior scans
- Corrective action list for any abnormalities
- Signed report by Level II thermographer per ASNT

## Fault modes and troubleshooting

### Tap box LED RED (fault)

Possible causes:
1. Phase loss upstream (utility brownout, breaker trip)
2. Severe voltage imbalance (>10% between phases)
3. Tap box internal fault (rare, requires replacement)

Response:
1. Check upstream feeder status via EPMS
2. If upstream healthy: replace tap box at next maintenance window
3. Until replacement: verify downstream RPP on the other side of 2N
4. Document in `incidents` table

### Thermographic hot spot

Possible causes:
1. Loose connection at tap box-to-busway interface
2. Contamination (dust, oxidation) in slot
3. Overload approaching current rating

Response:
1. Verify actual current with clamp meter on downstream feeders
2. If below 80% rating: schedule maintenance window, torque check
3. If above 80%: emergency load transfer, replace tap box immediately

### Unusual sound from busway

Possible causes:
1. Lamination vibration at high load (harmonic)
2. Loose busway joint (serious)

Response:
1. Locate source with stethoscope
2. Record audio for reference
3. Schedule inspection at next window

## Integration with EPMS

Starline provides the Critical Power Monitor for each RPP downstream:

- Per-tap box: voltage, current, power factor, energy consumption
- Published via Modbus TCP (polled by EPMS every second)
- Alarms for overcurrent, voltage deviation, frequency deviation
- Energy data feeds into PUE calculation

## Safety reminders

- Busway is 2500A — a fault is catastrophic
- Arc flash boundary is typically 0.9 m at RPP — respect it
- NEVER use non-insulated tooling near energized busway
- NEVER remove a tap box under load — always de-energize downstream first
- If in doubt, call the facility manager

## Documentation

Every busway operation generates:
- Entry in `procedures` table (type=BUSWAY_INSPECTION or BUSWAY_TAP_CHANGE)
- Thermographic photos archived
- Incident entry if any abnormality found
- Signed work order

## References

- Starline T5 Series Installation & Service Manual
- NFPA 70E-2024 (Standard for Electrical Safety in the Workplace)
- NFPA 70B-2023 (Recommended Practice for Electrical Equipment Maintenance)
- ASNT SNT-TC-1A (Non-Destructive Testing Personnel Certification)
- a3semi Busway Inspection Log: A3-OPS-FRM-018
