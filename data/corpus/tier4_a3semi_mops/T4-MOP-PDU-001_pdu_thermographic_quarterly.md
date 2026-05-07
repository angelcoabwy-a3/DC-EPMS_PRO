---
doc_id: T4-MOP-PDU-001
tier: 4
priority: high
doc_type: MOP
domain: power_distribution
equipment: Starline T5 busway, RPP panels, rack PDUs
standard_refs: [NFPA 70B Annex Q, ASNT SNT-TC-1A, NFPA 70E]
applies_to: [quarterly_thermographic, busway, rpp, rack_pdu]
keywords: [mop, thermographic, ir_scan, busway, pdu, rpp, quarterly]
facility: A3-Alpha Toronto Area
duration: 4 hours facility-wide
personnel_required: Level II thermographer + qualified electrical worker
---

# MOP: Quarterly Thermographic Inspection — Power Distribution

**Procedure ID**: T4-MOP-PDU-001
**Revision**: 2026.1

## Purpose

Predictive maintenance of the electrical distribution system via infrared
thermography. Identifies loose connections, high-resistance contacts,
overloaded feeders, and phase imbalances BEFORE they cause failures.

## Scope

- Starline T5 busway runs (A-side and B-side per hall)
- Every tap box on every busway
- All RPP (Remote Power Panel) panels at row level
- A sample of rack PDUs (statistical sampling, 10% per quarter)
- Main switchgear terminations
- UPS A and B terminations

## Pre-work requirements

### 48 hours before

- Verify thermographer Level II certification current (ASNT SNT-TC-1A)
- Schedule during 80%+ facility load (better signal)
- Coordinate with operations for camera access around racks

### 4 hours before

- Calibrate IR camera (ambient temperature reference)
- Verify emissivity charts for target materials available
- Brief team on hall access rules and photography restrictions

## Tools and materials

- FLIR T-series IR camera (current calibration certificate)
- Aluminum foil (for reflected apparent temperature measurements)
- Clamp meter (to measure actual current during scan)
- Reference thermocouple (for spot verification)
- Tablet with thermography app for report generation
- Category 2 PPE for any panel opening (NFPA 70E)

## Procedure

### Phase 1 — Setup and calibration (30 min)

**Camera setup:**
- Emissivity: 0.95 for painted surfaces (busway, panels)
- Emissivity: 0.70 for bare copper (lugs, bus stabs)
- Reflected apparent temperature: measured via foil target
- Distance compensation: active
- Palette: Ironbow (preferred for technical analysis)

**Baseline measurement:**
- Ambient temperature at work area
- Record start time and weather conditions

### Phase 2 — Scanning (3 hours)

#### Busway scanning pattern

For EACH busway run (Hall A-A, A-B, B-A, B-B, C-A, C-B):

1. **Overview scan**: traverse full busway length slowly
2. **Tap box close-up**: each tap box individually, 1 m distance
3. **Joint scans**: every busway-to-busway joint, focus mode
4. **Current verification**: clamp meter reading at midpoint

**Temperature thresholds (NFPA 70B Annex Q):**

| ΔT above ambient | Condition | Action |
|------------------|-----------|--------|
| 0-10°C | Normal | No action |
| 10-20°C | Monitor | Re-scan at next quarterly |
| 20-40°C | Corrective | Action within 30 days |
| >40°C | Critical | Immediate action, de-energize if accessible |

**Phase imbalance check:**
- All three phases should be within 3°C of each other
- >3°C differential indicates load imbalance (investigate)
- >10°C differential indicates single-phase loading (correct)

#### RPP panel scanning

For EACH RPP (target 48 panels facility-wide):

1. Exterior thermographic scan (detects interior hot spots)
2. If anomaly detected: open panel with Category 2 PPE
3. Interior scan with panel open:
   - Main lug connections
   - Branch breaker terminals
   - Neutral bar connections
   - Ground bar connections
4. Document findings per panel

#### Rack PDU scanning (statistical sample)

- 10% of rack PDUs per quarter (12 PDUs)
- Rotation: different racks each quarter to complete full coverage
  over 2-year cycle
- Focus on PDU input connections and high-load outlets

### Phase 3 — Analysis and reporting (1 hour)

**Immediate anomalies:**

Any finding in "Critical" or "Corrective" category:
1. Stop further scanning at that panel
2. Isolate equipment if hazardous (escalate to electrician)
3. Create work order for correction
4. Document with photo, context, and recommended action

**Report generation:**

For each equipment inspected, record:
- Location and equipment ID
- Maximum temperature observed
- Ambient temperature at time of scan
- ΔT calculation
- Load current at time of scan (from clamp meter or monitoring)
- Phase balance assessment
- Corrective action recommendation (if any)
- Thermographic images (baseline + findings)

**Trend analysis:**

Compare to prior quarter:
- Temperature trending upward → incipient fault
- Phase balance degrading → developing load issue
- New hot spots → recent installation or maintenance quality issue

## Acceptance criteria

MOP complete when:
- [ ] All scheduled equipment scanned
- [ ] All anomalies documented with corrective actions
- [ ] Report signed by Level II thermographer
- [ ] Findings logged to PostgreSQL `procedures` table
- [ ] Corrective work orders created for all Corrective/Critical findings

## Follow-up

- Corrective findings: verified corrected at next quarterly scan
- Critical findings: verified corrected within 7 days
- Trend analysis: reviewed at next quarterly safety meeting

## References

- NFPA 70B-2023 Annex Q (Infrared Inspection Intervals and Procedures)
- ASNT SNT-TC-1A (Personnel Qualification and Certification)
- ISO 18434-1 (Thermography in Condition Monitoring)
- Starline busway guide (T2-VEN-ST-PDU)
- Arc flash PPE procedure (T1-SAF-ARC-002)
- a3semi Thermographic Report Template: A3-OPS-FRM-032
