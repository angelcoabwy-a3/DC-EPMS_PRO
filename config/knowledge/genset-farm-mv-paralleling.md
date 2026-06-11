---
id: genset-farm-mv-paralleling
title: "Large-Scale Generation Plants (>50 MW): MV Paralleling, Dead-Bus Logic and Load Shedding"
source: Hyperscale standby generation engineering principles (operator spec 2026-06-10)
source_type: engineering_reference
applies_to:
  - genset
  - paralleling_switchgear
  - medium_voltage_bus
tags:
  - ansi_25
  - dead_bus
  - black_start
  - load_shedding
  - medium_voltage
voltage_class: 13.8kV
---

# Large-Scale Generation Plants (>50 MW): MV Paralleling, Dead-Bus Logic and Load Shedding

> Reference knowledge for farm-scale standby generation (operator
> spec, 2026-06-10). SCOPE NOTE: A3-Alpha Phase 1 runs 2 gensets per
> path on an N+1 paralleling bus — this document describes the
> ENGINEERING PRINCIPLES at hyperscale (16-20 units), as panel-grade
> background, not as the deployed plant.

## Why medium voltage (MV)

Above ~50 MW a single prime mover is physically impossible (thermal
dissipation, mechanical construction limits); a paralleled genset
farm is used (e.g. 16-20 x 3.2 MW units, N+1 or N+2). Low-voltage
distribution is unviable at that scale — three-phase current:

    I = P / (sqrt(3) x V x pf)

For 50 MW at pf 0.8:
- at 480 V  -> ~75,178 A (impractical copper bus bars, I^2R losses)
- at 13.8 kV -> ~2,615 A

Generation and primary distribution therefore run natively at MV
(13.8 kV or 4.16 kV) into arc-resistant paralleling switchgear.

```
[ Gen 1 ] [ Gen 2 ] [ Gen 3 ] ... [ Gen N ]   (MV alternators)
    |         |         |             |
  [ 52 ]    [ 52 ]    [ 52 ]        [ 52 ]    (vacuum breakers)
    +---------+---------+-------------+
                  v
        [ MAIN MV BUS ]
                  v
              [ 52 ]
                  v
     [ Step-down transformer ]
                  v
     [ Substation distribution / STS ]
```

## Synchronization and dead-bus logic

Coupling alternators onto a live bus requires strict matching of
FOUR variables: voltage, frequency, phase angle and phase sequence.

- **ANSI 25 synchronism-check relay**: supervises the incoming
  generator against the live bus; permits breaker (52) closure only
  when the differences tend to zero.
- **Dead-bus sequence (black start)**:
  1. Total utility loss — the MV bus de-energizes completely.
  2. All gensets receive a simultaneous start order.
  3. The FIRST unit reaching 90 % of nominal V and f wins priority:
     its controller closes onto the dead bus, energizing it.
  4. The bus is no longer dead — every remaining unit must now sync
     AGAINST it, dynamically trimming governor (speed/frequency) and
     AVR field excitation before its 52 may close.

## Plant auxiliaries

- **Thermal transfer loops**: each engine block rejects megawatts of
  heat through forced-draft remote radiators on variable-speed AC
  motors. Closed cooling loops demand chemical water monitoring
  (pH, conductivity, corrosion inhibitors) to mitigate cylinder-
  liner cavitation at high thermal load.
- **Ring-main fuel system**: bulk storage tanks pump diesel through
  a pressurized ring main to per-unit day tanks; levels managed by
  redundant solenoid valves + ultrasonic sensors on the industrial
  control loop.

## Master control and load shedding

The farm is governed by redundant high-speed PLCs balancing
available generation against datacenter demand continuously. On a
sudden unit trip (high coolant temperature, low oil pressure), the
capacity loss can drag bus frequency down; the PLC executes a load-
shedding algorithm in <100 ms, selectively opening breakers on
non-critical loads (offices, general lighting, standby chillers) to
stabilize frequency and preserve the IT load uninterrupted.
