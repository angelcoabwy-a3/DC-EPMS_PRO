---
doc_id: T2-VEN-YK-CHI-YZ
tier: 2
priority: high
domain: mechanical_cooling
vendor: York (Johnson Controls)
equipment: YZ centrifugal chiller
applies_to: [chiller_operation, refrigerant_management, condenser]
keywords: [york_yz, centrifugal_chiller, magnetic_bearing, r_1233zd, oil_free, cooling_tower]
facility: A3-Alpha Toronto Area
---

# York YZ Magnetic-Bearing Centrifugal Chiller — Operation & Maintenance

Source: Johnson Controls York YZ Engineering Guide (form 160.87-EG1)
Equipment: York YZ-F12, 1500 TR magnetic-bearing centrifugal chiller
Applicability: A3-Alpha Chiller 1 and Chiller 2 (N+1 redundancy)

## System overview

The York YZ chiller is a next-generation centrifugal chiller using:
- Magnetic-bearing compressor (oil-free operation)
- R-1233zd(E) refrigerant (HFO, ultra-low GWP = 1)
- VSD (variable speed drive) for part-load efficiency
- Integrated economizer cycle

Two YZ-F12 units at A3-Alpha provide N+1 redundancy. Each is sized for
100% facility cooling load; both run simultaneously at ~50% load for
efficiency, with instant capacity to cover single-unit failure.

### Key specifications (per unit)

- Nominal capacity: 1500 TR (5275 kW thermal)
- Refrigerant: R-1233zd(E), charge 850 kg
- Compressor: Magnetic-bearing, oil-free
- Motor: 1000 kW, VSD-controlled, 3-phase 480V
- COP: 7.2 at AHRI conditions, 11+ at part load (economizer active)
- Evaporator: Flooded, 10.5 m³ shell volume
- Condenser: Flooded, water-cooled, 12 m³ shell volume

## Operating principles

### Magnetic-bearing compressor — why it matters

Traditional chillers use oil-lubricated bearings in the compressor.
Problems with oil:
- Oil contaminates refrigerant, degrading heat transfer 5-15%
- Oil migration causes foamed oil on evaporator return
- Oil changes every 5 years (costly, labor-intensive)
- Oil pumps consume parasitic power

The YZ uses magnetic bearings — the shaft floats in an active magnetic
field with no physical contact. Benefits:
- Zero oil = zero oil-related maintenance
- Near-frictionless, improves efficiency 8-12%
- Instant start capability (no oil pressure build-up delay)
- 20+ year expected bearing life (vs 7-10 years oil)

### R-1233zd(E) refrigerant — the HFO advantage

R-1233zd replaces R-134a and R-123 in new installations:
- GWP (global warming potential): 1 (vs R-134a at 1430)
- ODP (ozone depletion): 0
- Low-pressure refrigerant (simplifies servicing)
- Classified A1 (non-toxic, non-flammable)
- Meets EPA SNAP approval and EU F-Gas regulations

Charge management:
- Refrigerant is a consumable — small losses occur over years
- A3-Alpha tracks refrigerant inventory quarterly
- Refrigerant recovery required during any service that opens the
  refrigerant loop (environmental compliance)

## Startup sequence

Do not bypass any step. The YZ protects itself aggressively.

### Pre-start checklist

1. Chilled water and condenser water flows established
2. Condenser water temperature 13-32°C (25°C typical summer, lower winter)
3. Chilled water return temperature 8-20°C
4. No active alarms on the Smart Panel
5. Compressor suction and discharge pressures within normal band
6. Magnetic bearing levitation test passes (self-test on start)

### Cold start

1. Operator: Main menu -> Start Compressor
2. Chiller runs pre-start self-test (10 seconds):
   - Magnetic bearing levitation (shaft must float within spec)
   - Refrigerant pressure sensors (all in normal range)
   - Compressor vibration sensors (zero baseline)
3. VSD begins spin-up from 0 Hz
4. Target: 100 Hz (6000 RPM) at full load
5. Smart Panel monitors all parameters continuously
6. Chiller reaches setpoint leaving chilled water temperature (LCHWT)
   within 3-5 minutes typical

### Capacity control — how the YZ modulates

- Speed (VSD): primary control, 0-100% speed range (0 to ~7000 RPM)
- Inlet guide vanes (IGV): secondary, 0-100% angle
- Economizer: active at part-load (below 60% load)

Predictive control from the EPMS:
- EPMS publishes expected IT load forecast (10-minute horizon)
- Chiller anticipates load changes, pre-positions VSD for efficiency
- Reduces temperature overshoot on rapid load changes

## Normal operating parameters

| Parameter | Normal range | Alarm low | Alarm high |
|-----------|--------------|-----------|------------|
| LCHWT (leaving chilled water) | 6.0-7.5°C | 5.0°C | 9.0°C |
| LCHWT setpoint | 6.5°C typical | — | — |
| Condenser leaving temp | 25-35°C | — | 40°C |
| Compressor speed | 40-95% | — | 98% |
| Evaporator approach | 0.5-2.0°C | — | 3.0°C |
| Condenser approach | 0.5-2.5°C | — | 3.5°C |
| Motor current | 400-850 A | — | 900 A |
| Magnetic bearing position | ±20 µm | — | ±50 µm |
| Refrigerant charge | 850 kg ±3% | 820 kg | — |

## Maintenance schedule

### Monthly

- Review alarm history and trends (Smart Panel log export)
- Record bearing gap measurements (should be stable within ±2 µm over
  a month)
- Record refrigerant charge estimate (from Smart Panel, no opening the
  loop)
- Condenser tube temperature scan (IR camera, non-contact)
- VSD cooling airflow verification

### Quarterly

- Quarterly PM (see T4-MOP-CHI-001 for full procedure)
- Condenser water chemistry: pH 7.5-8.5, conductivity, biocide residual
- Evaporator approach trend analysis (fouling indicator)
- Compressor vibration spectrum analysis (baseline comparison)
- VSD capacitor inspection

### Annual

- Full refrigerant charge verification (scale-weigh sample method)
- Compressor magnetic bearing calibration (factory-trained technician)
- Evaporator tube eddy-current test (if trending suggests fouling)
- Condenser tube mechanical brushing if scale observed
- VSD comprehensive inspection, capacitor replacement if >5 years

### 5-year

- Compressor teardown inspection (factory-trained)
- Refrigerant loop leak test (electronic + ultrasonic)
- Heat exchanger pressure test

## Shutdown — two types

### Normal shutdown (for maintenance)

1. Reduce load: operator commands load reduction via Smart Panel
2. Monitor load transfer to the other chiller
3. When load <5%, command manual shutdown
4. Compressor spins down over 2-3 minutes
5. Magnetic bearing de-levitates (shaft drops to mechanical supports)
6. Chilled water and condenser water flows continue for 5 minutes
   (prevents thermal shock)
7. Flows secured, chiller ready for service

### Emergency shutdown (fault or EPO)

1. Chiller trips on high pressure, low evaporator, or bearing fault
2. Compressor stops immediately (VSD commanded to zero)
3. Solenoid valves close (refrigerant isolation)
4. Condenser and evaporator flows continue until operator intervention
5. EPMS records incident with severity=critical

## Common faults and troubleshooting

| Fault | Likely cause | Action |
|-------|--------------|--------|
| High discharge pressure | Dirty condenser tubes | Brush tubes, verify cooling tower |
| High discharge pressure | Non-condensables in refrigerant | Evacuate, verify leak test |
| Low evaporator pressure | Low water flow | Check pumps, strainers |
| Low evaporator pressure | Refrigerant undercharge | Leak test, recharge |
| Bearing fault | Sensor or controller | Contact Johnson Controls technician |
| High vibration | Impeller imbalance | Service required, cannot run |
| Economizer fault | Float valve or sensor | Scheduled service, bypass economizer |

## Integration with EPMS

The York YZ publishes via Modbus TCP:

- Compressor speed, motor current, motor temperature
- Evap supply and return temperatures
- Cond supply and return temperatures  
- Refrigerant pressures (suction, discharge, economizer)
- Oil pressure (always zero for oil-free, but published)
- Active alarms and fault codes

EPMS correlates chiller state with facility telemetry — if PUE rises
while chiller load is stable, indicates air-side issue (CRAH, airflow)
rather than chilled water production.

## Refrigerant management — environmental

Canada environmental compliance for HFOs:

- Refrigerant inventory tracked quarterly
- Any leak >1 kg reportable within 24 hours
- Annual leak test mandatory
- Certified recovery technician required for any loop opening
- Recovery records kept for 5 years

## References

- Johnson Controls York YZ Engineering Guide (form 160.87-EG1)
- AHRI 550/590 (Chiller Performance Rating)
- ASHRAE Standard 34 (Refrigerant Designation and Safety)
- Environment and Climate Change Canada F-Gas Regulation
- a3semi Chiller Operating Log: A3-OPS-FRM-023
- a3semi Refrigerant Inventory: A3-ENV-LOG-007
