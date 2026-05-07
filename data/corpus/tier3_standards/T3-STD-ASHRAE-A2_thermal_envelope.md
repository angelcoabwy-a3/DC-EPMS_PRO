---
doc_id: T3-STD-ASHRAE-A2
tier: 3
priority: medium
domain: thermal_standards
standard: ASHRAE TC 9.9 (Thermal Guidelines for Data Processing Environments)
applies_to: [inlet_temperature, humidity, thermal_envelope]
keywords: [ashrae, a2, thermal, envelope, inlet_temperature, humidity, dew_point]
facility: A3-Alpha Toronto Area
---

# ASHRAE A2 Thermal Envelope

Source: ASHRAE TC 9.9, "Thermal Guidelines for Data Processing Environments"
Reference: ASHRAE Technical Committee 9.9, 5th Edition (2021)

## Overview

ASHRAE TC 9.9 defines thermal envelopes for IT equipment in data centers.
A3-Alpha operates primarily in the A2 envelope for the Blackwell NVL72
fleet, with some tolerance into A3 during normal operations and strict
avoidance of A4 conditions.

## ASHRAE envelopes (summary)

| Envelope | Inlet T | Inlet RH | Dew Point | Notes |
|----------|---------|----------|-----------|-------|
| A1 | 15-32°C | 20-80% | -9 to 17°C | Legacy enterprise |
| A2 | 10-35°C | 20-80% | -9 to 21°C | **A3-Alpha target** |
| A3 | 5-40°C | 8-85% | -12 to 24°C | Higher tolerance |
| A4 | 5-45°C | 8-90% | -12 to 24°C | Maximum stress |

A3-Alpha design operating point: 18-22°C inlet, 45% RH, comfortably
within A2.

## Why A2 specifically for A3-Alpha

A3-Alpha's Blackwell NVL72 racks use DLC (direct liquid cooling) for
~95% of heat removal. The remaining 5% (DIMMs, network cards, chassis)
is handled by CRAH air-side cooling. The A2 envelope gives:

- Energy efficiency: 20°C inlet vs A1's 15°C reduces chiller load
- Equipment health: conservative enough for all installed electronics
- PUE target: 1.10-1.15 achievable with 20°C inlet, dry climate
- Humidity management: 20-80% RH prevents ESD (below 20%) and
  condensation (above 80%)

## Understanding the psychrometric boundaries

### Temperature limits

- Lower 10°C: prevents condensation on cooled surfaces (return water
  from DLC loop could be as cold as 18°C in summer startup)
- Upper 35°C: prevents sustained thermal stress on electronic
  components, maintains margin before automatic throttling

### Humidity limits

- Lower 20% RH: below this, ESD risk rises exponentially; can damage
  sensitive electronics during handling
- Upper 80% RH: above this, condensation can form on cooled surfaces
  (especially DLC quick-disconnects when disconnected)

### Dew point limits (most critical for DLC)

- Lower -9°C: unusually dry for Toronto, mostly prevents issues with
  filter media and gasketing
- Upper 21°C: CRITICAL — supply water temperature in DLC must stay
  above facility dew point. If dew point rises to 17°C and DLC supply
  is 18°C, condensation will form on DLC manifolds.

## A3-Alpha operational bands (tighter than A2)

a3semi imposes tighter bands than A2 for operational excellence:

| Parameter | a3semi target | a3semi alarm | ASHRAE A2 |
|-----------|---------------|--------------|-----------|
| Inlet temp | 20°C ±2°C | 18°C / 24°C | 10-35°C |
| Inlet RH | 45% ±10% | 30% / 60% | 20-80% |
| Dew point | 8°C ±3°C | 5°C / 12°C | -9 to 21°C |

The alarm bands trigger EPMS warnings for trend analysis. The A2
envelope is the hard limit — exceeding it triggers incident creation
with severity=critical.

## Instrumentation — what a3semi measures

### Hall-level

- 6 inlet air temperature sensors per hall (cold aisle positions)
- 6 return air temperature sensors (hot aisle positions)
- 2 humidity/dew point transmitters per hall
- Barometric pressure (for accurate psychrometric calcs)

### Per-rack

- Inlet temperature at top and bottom of rack front
- Outlet (return) temperature at top and bottom of rack rear
- Published to PostgreSQL telemetry every 15 seconds

### Calibration

- Temperature sensors: ±0.2°C accuracy, calibrated annually
- Humidity transmitters: ±2% RH accuracy, calibrated semi-annually
- Calibration records in `procedures` table

## Condensation risk calculation

Critical check performed continuously by EPMS:

```
if DLC_supply_temp <= dew_point + safety_margin:
    raise_alert("Condensation risk on DLC manifolds")
    
where safety_margin = 2.0°C
```

Example: if facility dew point is 17°C and DLC supply target is 18°C:
- margin = 18 - 17 = 1°C
- Below 2°C margin → EPMS triggers warning
- Operator action: raise DLC supply to 19-20°C OR increase dehumidification

## Thermal dynamics — transient response

Per Newton's law of cooling applied to a data hall:

```
T(t) = T_final + (T_initial - T_final) * exp(-t/tau)

At A3-Alpha hall A:
  tau (time constant) ≈ 53.3 seconds
  T_final (if cooling stops) ≈ 45°C
  T_initial (normal operation) ≈ 22°C
  
Time to reach 35°C (A2 critical):
  t = -tau * ln((35 - T_final) / (T_initial - T_final))
  t = -53.3 * ln((35-45)/(22-45))
  t ≈ 44 seconds
```

This 44-second window is why fast response to cooling faults is
critical. The EPMS predictive advisory must trigger within 10 seconds
to allow 30+ seconds for operator action.

## Common excursions and response

### Inlet temperature rising rapidly (>0.5°C/minute)

Likely cause: cooling capacity reduction (chiller trip, DLC pump issue)

Response sequence:
1. EPMS automatic advisory to NOC
2. Verify cooling plant status (chiller, pumps, cooling tower)
3. If cooling healthy: check airflow (CRAH fans, containment breach)
4. If cooling degraded: activate backup cooling or EOP-003 (emergency
   cooling reduction)

### Humidity excursion (>60% RH)

Likely cause: outdoor air infiltration (winter) or chilled water leak
(summer)

Response sequence:
1. Isolate affected zone if possible
2. Dispatch inspection team (leak check, building envelope check)
3. Monitor dew point closely (condensation risk)
4. If sustained >65% for >5 minutes: consider reducing DLC supply by
   1°C to increase margin

### Dew point approaching supply water temperature

Likely cause: humidity spike from evaporative process or leak

Response sequence:
1. EPMS auto-raises DLC supply by 1°C
2. Investigate humidity source
3. Increase dehumidification capacity if available
4. Document in `incidents` with investigation notes

## Integration with EPMS predictive control

a3semi's EPMS implements predictive thermal control:

1. EPMS forecasts IT load 10 minutes ahead using historical training
   patterns
2. Forecast sent to chiller control via Modbus
3. Chiller VSD adjusts proactively (not reactively)
4. Result: smaller temperature swings, better thermal stability

## Reporting and compliance

A3-Alpha generates automatic compliance reports:

- Monthly: temperature and humidity excursion summary
- Quarterly: ASHRAE A2 envelope compliance certificate
- Annual: thermal audit with trend analysis and benchmarking

These reports support a3semi's enterprise customer contracts and
regulatory compliance (Canada Energy Use Data and Benchmarking).

## References

- ASHRAE TC 9.9, "Thermal Guidelines for Data Processing Environments,"
  5th Edition (2021)
- ASHRAE Handbook Fundamentals, Chapter 1 (Psychrometrics)
- ASHRAE Handbook HVAC Applications, Chapter 19 (Data Centers)
- ANSI/ASHRAE Standard 90.4 (Energy Standard for Data Centers)
- a3semi Environmental Compliance Program: A3-ENV-PRG-001
- a3semi ASHRAE A2 Compliance Report: monthly, archived in `procedures`
