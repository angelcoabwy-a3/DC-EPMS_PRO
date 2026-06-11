---
id: galaxy-vx-internal-oneline
title: Galaxy VX UPS — Internal One-Line, Q-Breaker Discipline and Operating Modes
source: Schneider Galaxy V-series switching nomenclature / IEC 62040-3 (operator spec 2026-06-10)
source_type: vendor_whitepaper
applies_to:
  - ups
  - battery
  - static_bypass
  - maintenance_bypass
tags:
  - galaxy_vx
  - q_breakers
  - iec_62040_3
  - mbp
  - double_conversion
voltage_class: 480VAC
---

# Galaxy VX UPS — Internal One-Line, Q-Breaker Discipline and Operating Modes

> Source basis: Schneider Galaxy V-series switching nomenclature and
> IEC 62040-3 mode classification, as specified by the operator
> (2026-06-10) for MOP authoring and HMI engineering detail.

## Functional blocks (the one-line, input to load)

```
[ Mains / Generator (AC) ]
        |
   +----+----------------+
   v                     v
 [ Q1 ]                [ Q2 ]
   |                     |
 [ Rectifier PFC ]     [ Static bypass leg ]
   |                     |
 [ DC BUS ] <--Q5--> [ Batteries ]
   |                     |
 [ Inverter ]            |
   +----------+----------+
              v
 [ SSM — static switching module ]
              |
           [ Q4 ]
              |
      [ Critical load ]      (Q3 = external MBP rail wrapping it all)
```

### 1. Input + PFC rectifier (Q1)
Converts incoming AC to DC for the internal bus. High-frequency IGBT
switching with active power-factor correction keeps the injected
current distortion THDi < 3 %, protecting upstream transformers and
generators from harmonic heating. Protected by the main input
breaker **Q1**.

### 2. DC bus + energy storage (Q5)
The floating energy-balance node of the system: interconnects the
rectifier output, the inverter input and the battery cabinets
through the battery isolation breaker **Q5**. Battery technologies:
VRLA or high-density Li-ion, each managed by a Battery Management
System (BMS module).

### 3. Inverter
Regenerates a perfect sinusoidal AC output from the DC bus via PWM,
holding voltage to ±1 % and quartz-precision frequency regardless of
input condition. This is the VFI (voltage and frequency independent)
half of the IEC 62040-3 VFI-SS-111 classification.

### 4. Static bypass (Q2 → SSM)
An alternate instantaneous feed path protected by **Q2**, built on
high-speed SCR thyristors in antiparallel. Performs 0 ms transfers
on severe overload (inrush), downstream short circuit, or inverter
failure, and enables high-efficiency modes such as ECOnversion. Both
the inverter leg and the bypass leg converge at the **SSM (static
switching module)**, which feeds the load through the output
isolation breaker **Q4**.

### 5. Maintenance bypass (MBP, Q3 — external)
A mechanically interlocked breaker arrangement (often Castell
captive-key transfer locks) on an EXTERNAL panel that connects input
directly to output, fully de-energizing rectifier, inverter and
static bypass modules for safe service. The zero-interruption
transfer sequence the MOPs encode:

1. Transfer load to static bypass (inverter off).
2. Close **Q3** (MBP now carries the load in parallel).
3. Open **Q4**, then **Q2**, then **Q1**, then **Q5**.
4. UPS fully isolated; load never dropped.

## Operating modes (IEC 62040-3)

| Mode | Path | Notes |
|---|---|---|
| Double conversion | Q1 → rectifier → DC bus → inverter → SSM → Q4 | VFI-SS-111; battery float-charges via Q5 |
| Battery | Q5 → DC bus → inverter → SSM → Q4 | Q1 remains CLOSED (input dead, breaker did not open) |
| Static bypass | Q2 → SSM → Q4 | SCR, 0 ms transfer |
| ECOnversion | bypass-fed with inverter as active filter | high efficiency |
| Maintenance bypass | Q3 external rail | Q1/Q2/Q4/Q5 open, UPS isolated |

## Q-state telemetry discipline (DC-EPMS implementation)

Each breaker position is exposed as a BMS tag
(`PWR.UPS_A.Q1_POS` … `Q5_POS`, BACnet BO, enum Open/Closed,
SME_L6-gated writes). The HMI compares ACTUAL positions against the
mode-nominal lineup and raises a Q-STATE MISMATCH alarm — e.g. Q3
reading CLOSED during double conversion means the maintenance bypass
was left bridged after service, silently defeating the UPS.
