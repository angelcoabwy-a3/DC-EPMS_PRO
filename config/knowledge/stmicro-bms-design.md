---
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
