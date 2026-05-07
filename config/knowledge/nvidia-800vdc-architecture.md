---
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
