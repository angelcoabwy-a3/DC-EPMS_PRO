"""
Sprint S2 - Batch 1: Knowledge Corpus Setup
Creates config/knowledge/ directory with 5 markdown documents:
  - 3 source docs (NVIDIA 800VDC, OCP-LVDC, STMicro BMS) ingested verbatim
  - 2 stubs for Ontario/Canada compliance (CSA Z462-24, OESC)
  - 1 README.md as index

Each .md has YAML frontmatter declaring:
  - id: stable identifier (used as graph node id)
  - title: human-readable title
  - source: origin (vendor/standard body)
  - applies_to: list of component types this knowledge governs
  - tags: facets for filtering
  - jurisdiction: geographic applicability
  - version: doc version (for invalidation)

This frontmatter is parsed by graphrag_index.py to build the knowledge graph
edges automatically (KnowledgeNode --[applies_to]--> ComponentType).
"""
from pathlib import Path
import sys

ROOT = Path(r"C:\dev\DC-EPMS_PRO")
KNOW_DIR = ROOT / "config" / "knowledge"

KNOW_DIR.mkdir(parents=True, exist_ok=True)

DOCS = {}

# ════════════════════════════════════════════════════════════════════════
# Doc 1: NVIDIA 800 VDC Architecture (verbatim from user-provided source)
# ════════════════════════════════════════════════════════════════════════
DOCS["nvidia-800vdc-architecture.md"] = """---
id: nvidia-800vdc
title: NVIDIA 800 VDC Architecture for Next-Generation AI Infrastructure
source: NVIDIA / OCP roadmap
source_type: vendor_whitepaper
applies_to:
  - medium_voltage_rectifier
  - dc_busbar
  - side_car_power_rack
  - solid_state_transformer
  - battery_energy_storage
  - capacitor_bank
tags: [800vdc, lvdc, ai_factory, gb200, gb300, blackwell, rubin, ocp-orv3]
jurisdiction: international
version: "2024-Q4"
voltage_class: LVDC
---

# NVIDIA 800 VDC Architecture for Next-Generation AI Infrastructure

## 1. Architectural Imperative

The transition to AI Factories (e.g., Blackwell/Rubin clusters) drives rack
power densities from 40 kW to over 150 kW, with future projections exceeding
1000 kW per rack. To support this, 800 VDC has emerged as the optimal power
distribution architecture.

- **Key Driver:** 800 VDC allows for a 157% increase in power transmission
  through the same copper cross-section compared to 415 VAC.
- **Rack Distribution:** Direct 800 VDC distribution to the compute node.
  Conversion from 800 VDC to 12 VDC happens close to the GPU to minimize
  copper volume.

## 2. Power Racks and Facility Distribution

To support the density, AC/DC conversion is moving outside the IT rack.

- **Near-term (White Space Retrofit):** Dedicated Side Car Power Racks
  containing rectifiers (AC to 800 VDC).
- **Long-term (Facility Level):** Medium Voltage (MV) Rectifiers or Solid
  State Transformers (SST) converting directly from MVAC (e.g., 35 kVAC)
  to 800 VDC.

## 3. Load Swings and Energy Storage

Synchronized GPU workloads cause rapid power demand swings (e.g., from 30%
idle to 100% peak in milliseconds).

- **Mitigation:** Energy storage is required to flatten the load.
  - *Short-duration (<100 ms):* Capacitors near the compute racks.
  - *Long-duration (>10 s):* Lithium-ion batteries (BESS) at the facility
    level for load averaging and grid support.

## 4. Safety and Compliance

- **Voltage Level:** 800 VDC remains within the Low Voltage DC (LVDC) limit
  (less than or equal to 1500 VDC).
- **Protection:** Single-ended 800 V DC configuration is preferred over
  bipolar plus/minus 400 V DC due to component availability (two-pole
  breakers vs. three-pole).
- **Arc-Flash:** Working with 800 VDC requires strict Lockout/Tagout (LOTO)
  and Arc-Flash mitigation strategies due to high fault currents from
  capacitive discharges.
"""

# ════════════════════════════════════════════════════════════════════════
# Doc 2: OCP LVDC Power Distribution (verbatim)
# ════════════════════════════════════════════════════════════════════════
DOCS["ocp-lvdc-power-distribution.md"] = """---
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
"""

# ════════════════════════════════════════════════════════════════════════
# Doc 3: STMicroelectronics BMS (verbatim)
# ════════════════════════════════════════════════════════════════════════
DOCS["stmicro-bms-design.md"] = """---
id: stmicro-bms
title: STMicroelectronics - Designing an Advanced BMS
source: STMicroelectronics application note
source_type: vendor_whitepaper
applies_to:
  - battery_energy_storage
  - cell_measurement_unit
  - pack_monitoring_unit
  - lithium_ion_cell
tags: [bms, lithium_ion, kalman_filter, soc, soh, isospi, bess]
jurisdiction: international
version: "2024"
voltage_class: LVDC
---

# STMicroelectronics: Designing an Advanced BMS

## 1. BMS Functions and KPIs

The Battery Management System (BMS) is critical for safety and longevity.

- **Sensing:** Monitors cell/pack voltage, module temperature, and leakage
  current.
- **Control:** Manages contactors for connection/disconnection and pre-charge
  circuits.
- **Performance:** Calculates State of Charge (SOC) and State of Health (SOH).

## 2. Cell Balancing

Lithium-ion cells in series can become unbalanced over time.

- **Passive Balancing:** Drains excess charge from high-SOC cells using
  bleeding resistors (dissipated as heat).
- **Active Balancing:** Moves charge from high-SOC to low-SOC cells using
  capacitors/inductors.

## 3. SOC Estimation

- **Kalman Filters:** Extended Kalman Filters (EKF) are used to estimate
  SOC by filtering noisy sensor data and adapting to the non-linear
  behavior of batteries. The BMS LLM agent monitors the "Innovation"
  (residual) from this filter.

## 4. BMS Hardware Architecture

- **Cell Measurement Unit (CMU):** High-resolution ADCs connected directly
  to cells for synchronous voltage and temperature sampling.
- **Pack Monitoring Unit (PMU):** Includes a Coulomb counter, measures
  total pack current/voltage, and interfaces with the main contactors and
  emergency disconnects (pyro switches).
- **Isolation:** Communication between CMUs and the main controller often
  uses isolated links (e.g., isoSPI) to protect the low-voltage control
  electronics from the high-voltage battery stack.
"""

# ════════════════════════════════════════════════════════════════════════
# Doc 4: CSA Z462-24 STUB (Ontario/Canada compliance reference, no full text)
# ════════════════════════════════════════════════════════════════════════
DOCS["csa-z462-24-stub.md"] = """---
id: csa-z462-24
title: CSA Z462-24 - Workplace Electrical Safety (Canada)
source: Canadian Standards Association
source_type: regulatory_standard
applies_to:
  - dc_busbar
  - medium_voltage_rectifier
  - electrical_panel
  - rpp
  - pdu
  - ups
  - chiller
tags: [arc-flash, loto, ppe, canada, ontario, electrical-safety]
jurisdiction: canada
version: "2024"
voltage_class: ALL
referenced_by_us_equivalent: NFPA-70E
---

# CSA Z462-24 (Workplace Electrical Safety) - Compliance Reference Stub

This is a compliance pointer, not a reproduction of the standard.
Full text is licensed by CSA Group and must be obtained from CSA.

## Applicability for A3-Alpha Toronto Area

CSA Z462-24 is the Canadian equivalent of NFPA 70E. It governs all
electrical work in Ontario data centers, including A3-Alpha. Where this
codebase references NFPA 70E in legacy MOPs, the operational standard
of record for A3-Alpha is CSA Z462-24.

## Key Compliance Points (informational)

- Risk assessment procedure required before energized electrical work.
- Hazard categories (HRC) determine PPE.
- Specific to Canada: harmonized with CSA C22.1 (Canadian Electrical Code)
  and provincial Ontario Electrical Safety Code (OESC).
- Updates introduced in the 2024 edition cover DC arc-flash for LVDC
  systems and align with IEEE 1584-2018 calculation methods.

## Use in this system

The EHS Auditor Agent (Sprint S4) cites CSA Z462-24 in lieu of NFPA 70E
when generating WO drafts whose target component is located in Ontario
(A3-Alpha Toronto Area). For US-located facilities (future expansion),
NFPA 70E remains the citation.

## Procurement

For the authoritative document, see https://www.csagroup.org
"""

# ════════════════════════════════════════════════════════════════════════
# Doc 5: OESC Ontario STUB
# ════════════════════════════════════════════════════════════════════════
DOCS["oesc-ontario-stub.md"] = """---
id: oesc-ontario-28
title: Ontario Electrical Safety Code (OESC), 28th Edition
source: Electrical Safety Authority of Ontario
source_type: regulatory_standard
applies_to:
  - electrical_panel
  - rpp
  - pdu
  - dc_busbar
  - solid_state_transformer
tags: [ontario, electrical-code, lvdc, esa, jurisdictional]
jurisdiction: ontario_canada
version: "28th-2024"
voltage_class: ALL
based_on: CSA-C22.1
---

# Ontario Electrical Safety Code (OESC), 28th Edition - Compliance Reference Stub

This is a compliance pointer, not a reproduction of the regulation.
Full text is published by the Electrical Safety Authority of Ontario.

## Applicability for A3-Alpha Toronto Area

The OESC is the legally adopted electrical code in Ontario, derived
from CSA C22.1 with provincial amendments. All permanent electrical
installations at A3-Alpha must comply with OESC 28th edition.

## Key Sections (informational)

- Section 0: Object, scope, definitions.
- Section 4: Conductors (sizing, ampacity).
- Section 14: Protection and control (overcurrent, ground fault).
- Section 26: Installation of electrical equipment (transformers, panels).
- Section 36: High-voltage installations (greater than 750 V).
- Provincial amendments to CSA C22.1 specific to Ontario climate, snow
  load, frost line, and remote substation requirements.

## Use in this system

When the GraphRAG knowledge graph evaluates a CMMS WO targeting
electrical equipment in Ontario, the EHS Auditor cites OESC 28
sections relevant to the equipment class. Cross-referenced with
CSA Z462-24 for safety procedures.

## Procurement

For the authoritative document, see https://esasafe.com
"""

# ════════════════════════════════════════════════════════════════════════
# README.md - index of the corpus
# ════════════════════════════════════════════════════════════════════════
DOCS["README.md"] = """# DC-EPMS PRO - Knowledge Corpus

This directory contains the source documents ingested by the GraphRAG
subsystem (Sprint S2). Each document carries YAML frontmatter that
declares:

- `id`: stable identifier used as the knowledge graph node id
- `title`: human-readable
- `source`, `source_type`: provenance and category
- `applies_to`: list of component types this doc governs
- `tags`: facets for filtering
- `jurisdiction`: geographic applicability
- `version`: doc version (used for invalidation)
- `voltage_class`: LVDC/MVDC/MVAC/etc.

The graphrag_index.py module parses these files at boot (or on first
query, in lazy mode), builds an embedding index over chunks, and links
each document to component types in the site model graph via the
`applies_to` declaration.

## Current Corpus (Sprint S2)

| File | Type | Jurisdiction | Voltage |
|------|------|--------------|---------|
| nvidia-800vdc-architecture.md | vendor_whitepaper | international | LVDC |
| ocp-lvdc-power-distribution.md | industry_specification | international | LVDC |
| stmicro-bms-design.md | vendor_whitepaper | international | LVDC |
| csa-z462-24-stub.md | regulatory_standard | canada | ALL |
| oesc-ontario-stub.md | regulatory_standard | ontario_canada | ALL |

## Adding new knowledge

To add a document, drop a `.md` file with a complete frontmatter into
this directory. Restart the server (or re-issue an `/api/graph/reindex`
admin call - reindex endpoint planned for S5).

## Compliance and Copyright

Vendor whitepapers (NVIDIA, STMicro) are reproduced from publicly
available sources for technical reference within this private R&D
project (a3semi internal). They are NOT redistributed.

Regulatory standards (CSA Z462-24, OESC) are referenced as STUBS
ONLY - we do not reproduce the licensed content. Cite this codebase's
references to procurement URLs (csagroup.org, esasafe.com) for the
authoritative documents.
"""

# ════════════════════════════════════════════════════════════════════════
# Write all files
# ════════════════════════════════════════════════════════════════════════
print(f"Target directory: {KNOW_DIR}")
print(f"Files to create: {len(DOCS)}")
print()

for filename, content in DOCS.items():
    target = KNOW_DIR / filename
    # Write as UTF-8 without BOM, LF line endings (clean for parsing)
    target.write_bytes(content.encode("utf-8"))
    size = target.stat().st_size
    print(f"  [ok] {filename} ({size} bytes)")

print()
print(f"=== Knowledge corpus written to {KNOW_DIR} ===")
