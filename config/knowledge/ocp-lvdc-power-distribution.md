---
id: ocp-lvdc
title: Open Compute Project - Data Center Facility Low Voltage Direct Current Power Distribution
source: Open Compute Project Foundation
source_type: industry_specification
applies_to:
  - dc_busbar
  - solid_state_circuit_breaker
  - capacitor_bank
  - surge_protective_device
  - earthing_system
tags: [lvdc, iec-63282, tn-s, sscb, arc-flash, nec-460-6]
jurisdiction: international
version: "2024"
voltage_class: LVDC
references_standards: [IEC-TR-63282, NEC-460.6, NFPA-70E]
---

# OCP - Data Center Facility Low Voltage Direct Current Power Distribution

## 1. Voltage Bands and Operating Limits (IEC TR 63282)

The operating voltage for 800 VDC systems must be strictly managed to protect
equipment.

- **U2 (Minimum Continuous):** Typically approx 640 VDC. Undervoltage
  disconnecting limit.
- **U3 (Maximum Continuous):** Typically approx 760 VDC. Maximum continuous
  operating voltage.
- **U4 (Maximum Temporary):** 800 VDC. Short term maximum for switching/
  commutation.
- **U5 (Overvoltage Limit):** 840 VDC. Above this, surge protective devices
  (SPDs) conduct.

**Critical Rule:** Sources MUST NOT exceed 840 VDC.

## 2. Earthing and Polarity (TN-S System)

- **Preferred Configuration:** 800 V Unipolar TN-S or 350/700 V Bipolar TN-S.
- **TN-S Definition:** Solidly grounded system with a single connection to
  earth.
- **Advantage:** Reduces clearance/creepage requirements to earth by half
  compared to IT (ungrounded) systems, enabling higher density.

## 3. Protection and Fault Behavior

- **Fault Characteristics:** DC systems have low inductance and high
  capacitance. A short-circuit causes current to rise by tens of Amperes
  per microsecond (A/us).
- **Clearance Requirement:** Faults must be cleared in microseconds to
  prevent DC bus voltage collapse.
- **Solid-State Circuit Breakers (SSCBs):** Essential for 800 VDC systems.
  They interrupt faults in 1-100 microseconds (us), limiting the voltage
  drop and incident energy.

## 4. Safety and Arc-Flash (NFPA 70E)

- **Hazard:** High-energy DC arcs.
- **LOTO Requirement:** Before maintenance on 800 VDC busbars, power must
  be disconnected, AND capacitors must be discharged to a safe level
  (less than 50 V within 60 s per NEC 460.6).
- **PPE:** Requires high-level Arc-Flash Personal Protective Equipment
  (PPE) until the system is verified de-energized and discharged.
