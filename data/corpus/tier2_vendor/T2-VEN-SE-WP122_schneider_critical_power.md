---
doc_id: T2-VEN-SE-WP122
tier: 2
priority: high
domain: critical_power_cooling
standard: Schneider Electric WP122
vendor: Schneider Electric
applies_to: [power_distribution, cooling_topology, redundancy_design]
keywords: [wp122, tier_iv, 2n, redundancy, dlc, cooling_density]
facility: A3-Alpha Toronto Area
---

# Schneider Electric WP122 — Critical Power and Cooling Reference

Source: Schneider Electric White Paper WP122
Applicability: Reference framework for A3-Alpha Toronto Area design and
operations

## Key principles

Schneider WP122 establishes the design framework for critical power and
cooling in high-density data center environments. The four core principles
applied at A3-Alpha:

1. **Redundancy matches criticality** — Tier IV 2N for all mission-critical
   paths (power + cooling)
2. **Density drives topology** — DLC required for any rack >20 kW, a3semi
   standardizes on DLC for the full Blackwell NVL72 fleet (142 kW/rack)
3. **Cooling tracks compute load in real time** — predictive thermal
   control rather than reactive setpoint tracking
4. **Separation of concerns** — power, cooling, and IT network are
   independently redundant; a failure in one does not cascade

## Power topology — Tier IV 2N application

A3-Alpha power architecture per WP122 §3:

```
Utility (27 kV) -> Switchgear (A & B) -> UPS Galaxy VX (A & B)
  -> PDU (A-side) -> Rack feed A
  -> PDU (B-side) -> Rack feed B

Each rack has TWO independent feeds from physically separate paths.
Failure of any single component in A-path OR B-path does not interrupt
IT load.
```

### Key WP122 requirements applied

- UPS runtime at full load: minimum 10 minutes (a3semi exceeds: 15 min)
- Automatic transfer to generator on utility loss: <10 seconds (NFPA 110
  Type 10)
- PUE design target: 1.30 or better (a3semi achieves 1.10-1.15 typical)
- Concurrent maintainability: any single component serviceable without
  downtime (Tier IV requirement)

## Cooling topology — DLC primary, CRAH secondary

For Blackwell NVL72 racks at 142 kW each, traditional air cooling is
infeasible. WP122 §4 mandates DLC for densities >20 kW/rack. A3-Alpha
implementation:

### Direct Liquid Cooling (DLC) primary loop

- Coolant: 50/50 propylene glycol-water (PGW)
- Supply temperature (TCS): 18°C target, 20°C maximum
- Return temperature (TCR): 45°C maximum
- Flow rate: 40 L/min per rack (nominal), 60 L/min peak
- System pressure: 3.5 bar primary, 2.5 bar secondary
- Filtration: 50-micron cartridge, replaced quarterly

### CRAH secondary (sensible heat)

CRAH units handle the ~5% of heat not captured by DLC cold plates
(components outside the cold plate coverage: DIMMs, network cards,
chassis):

- Supply air temperature: 24°C ±1°C
- Return air temperature: up to 35°C (ASHRAE A2 upper)
- Airflow: 15 kg/s per hall aggregate
- Humidity: 30-60% RH

## Thermal physics — WP122 approach

WP122 §4.3 specifies the Newton cooling law model for transient
response. A3-Alpha implements this in the EPMS:

```
dT/dt = (Q_it - Q_cool) / (m_air * cp_air)

Where:
  T       = hot-aisle temperature (K)
  Q_it    = IT heat load (W) = rack_count * rack_kW * 1000 * thermal_fraction
  Q_cool  = removed heat (W) = (TCR - TCS) * flow_rate * cp_pgw * density_pgw
  m_air   = hot-aisle air mass (kg) = 800 kg typical
  cp_air  = specific heat of air = 1005 J/(kg·K)
```

For Blackwell NVL72 with DLC coverage 95%:
- Thermal fraction to air = 0.05 (DLC captures 95% to the coolant loop)
- Air-side heat load: 16,756 kW * 0.05 = 838 kW (handled by CRAH)
- Water-side heat load: 16,756 kW * 0.95 = 15,918 kW (handled by DLC)

## Time-to-Critical (TTC) calculation

When cooling capacity is lost or reduced (chiller trip, DLC pump failure),
WP122 §4.4 defines the Time-to-Critical as the time to reach ASHRAE A2
upper limit (35°C):

```
T(t) = T_ss + (T_0 - T_ss) * exp(-t / tau)

Solving for t when T(t) = 35°C:
t_critical = -tau * ln((35 - T_ss) / (T_0 - T_ss))

With tau = 53.3 s (measured at A3-Alpha hall A)
With T_ss = 45°C (steady-state with no cooling)
With T_0 = 22°C (normal operating)

t_critical ≈ 53.3 * ln(23/10) ≈ 44 seconds
```

This 44-second window is the critical response time when cooling fails —
the EPMS must detect, classify, and trigger response within this budget.

## Maintenance schedule per WP122

| Component | Frequency | Procedure ref |
|-----------|-----------|---------------|
| UPS battery impedance test | Monthly | T4-MOP-UPS-001 |
| UPS capacitor inspection | Quarterly | T4-MOP-UPS-002 |
| Chiller oil analysis | Quarterly | T4-MOP-CHI-001 |
| DLC filter replacement | Quarterly | T4-MOP-DLC-001 |
| PDU busway thermographic | Quarterly | T4-MOP-PDU-001 |
| Generator no-load test | Monthly | T4-MOP-GEN-001 |
| Generator full-load test | Annual (4-hour) | T4-MOP-GEN-002 |
| Fire alarm full test | Annual | T4-MOP-FIR-001 |
| Transfer switch exercise | Quarterly | T4-MOP-XFR-001 |

## Monitoring — what WP122 mandates

WP122 §5 specifies minimum monitoring coverage:

- Per-rack power (A and B feed, kW, kVA, power factor)
- Per-rack inlet temperature
- Per-aisle DLC supply/return temperature and flow
- Per-UPS load percentage and battery state
- Per-chiller load percentage, compressor state, refrigerant pressure
- Facility PUE (15-minute moving average and instantaneous)

A3-Alpha EPMS exceeds WP122 requirements with per-rack outlet temperature
and per-rack DLC flow measurement via the Gemini ER 1.6 robot's
thermographic survey.

## Integration with EPMS

A3-Alpha's EPMS integrates WP122 monitoring data via:

- Modbus TCP poll of each UPS, chiller, CRAH (1-second cadence)
- DNP3 poll of switchgear (5-second cadence)
- Direct GPIO read of generator state via IoT gateway
- All data persisted to PostgreSQL `telemetry` hypertable
- Real-time alarms for threshold excursions

## Reference contacts

- Schneider Electric Regional Technical Support: 1-800-SCHNEIDER
- a3semi facility engineering: facilities@a3semi.com (SLA 4-hour response)

## References

- Schneider Electric WP122, "Fundamental Principles of Air Conditioner
  Sizing for Data Centers"
- Schneider Electric WP66, "Understanding the Three Phases of Air
  Distribution in Data Centers"
- Schneider Electric WP49, "Power and Cooling Capacity Management for Data
  Centers"
- Schneider Electric TradeOff Tools (web-based sizing calculators)
- a3semi Single Line Diagram: A3-ENG-DRW-001 (current rev: 2025.4)
