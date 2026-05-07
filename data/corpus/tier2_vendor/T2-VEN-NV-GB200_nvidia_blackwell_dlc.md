---
doc_id: T2-VEN-NV-GB200
tier: 2
priority: high
domain: it_cooling
vendor: NVIDIA
equipment: GB200 NVL72 rack (72x GPU, 36x Grace CPU)
applies_to: [blackwell_rack, dlc_spec, gpu_cooling, compute_density]
keywords: [gb200, nvl72, blackwell, dlc, direct_liquid_cooling, 142kw, rack_density]
facility: A3-Alpha Toronto Area
---

# NVIDIA GB200 NVL72 — Direct Liquid Cooling Specifications

Source: NVIDIA GB200 NVL72 Datasheet and Installation Guide
Equipment: NVIDIA GB200 NVL72 rack with Blackwell B200 GPUs
Applicability: A3-Alpha Toronto Area — 118 racks deployed

## Rack overview

The GB200 NVL72 is NVIDIA's flagship AI training rack, delivering
exceptional compute density that mandates direct liquid cooling.

### Physical specifications

- Dimensions: 1200 mm W × 1200 mm D × 2200 mm H
- Weight: 1,300 kg (empty), 1,600 kg (fully populated)
- Compute units: 72 × Blackwell B200 GPUs + 36 × Grace CPUs
- NVLink switch: 9 × NVSwitch 4.0 (3rd gen, 5x bandwidth vs Hopper)
- Memory: 13.5 TB HBM3e (187.5 GB per GPU × 72)

### Power specifications (A3-Alpha operating)

- Nominal IT power: 142 kW per rack (at typical training workload)
- Peak power: 180 kW (during extreme model checkpoint saves)
- Minimum idle: 45 kW (model serving, low batch size)
- Power supply: Dual 415V 3-phase feeds, 2N redundancy
- PDU: Intelligent rack PDU with per-outlet metering

## Why DLC is mandatory

At 142 kW in a 1.2×1.2×2.2 m volume, power density = 53.7 kW/m². Air
cooling this density would require:
- Airflow: ~24 m³/s (enormous, impractical in a raised floor design)
- Supply temperature: below 15°C (requires expensive chilled air)
- Noise level: >95 dBA (hearing damage risk)

DLC solves this by capturing 95-97% of the heat directly in the
coolant loop at the cold plate, bypassing air entirely.

## A3-Alpha DLC system architecture

```
Facility chilled water       Technology Cooling Water (TCW) manifold
    (from York YZ)      ->       (per-rack manifold)
                                      |
                                      v
                              Rack Cold Plate Loop
                              (72 GPU + 36 CPU
                               cold plates in parallel)
                                      |
                                      v
                              Return to TCW manifold
                                      |
                                      v
                              Facility condenser
                              (rejects to cooling tower)
```

### Coolant specifications

- Fluid: 50/50 propylene glycol and deionized water (PGW)
- Supply temperature (TCS): 18°C ±1°C
- Return temperature (TCR): 40-45°C (under full load)
- Approach ΔT: 22-27°C (GPU junction to TCS)
- Flow rate per rack: 40 L/min nominal, 60 L/min peak
- System pressure: 2.5 bar secondary loop, 3.5 bar primary
- pH: 9.0-10.5 (corrosion inhibitor target)
- Conductivity: <500 µS/cm (limits galvanic corrosion)

### Why 18°C supply, not colder?

Data center efficiency:
- Lower supply temperature = lower chiller COP (more work per kW cooling)
- At 18°C supply vs 10°C supply: chiller COP rises from ~5 to ~7
- Blackwell GPUs tolerate much higher junction temperatures (up to 90°C)
- 18°C is the optimal point for facility PUE and compute performance

Mechanical considerations:
- Condensation risk below facility dew point (prevents supply below 16°C
  in summer Toronto weather)
- Distribution piping condensation insurance

## Coolant loop components — per rack

### Cold plates (per GPU/CPU)

Each Blackwell B200 has a custom cold plate:
- Direct contact with GPU die (not the package)
- Micro-channel design with ~2000 fins
- 4 mm channel height, 0.5 mm channel width
- Thermal resistance: 0.015 K/W (exceptional)
- Materials: copper base, nickel-plated for corrosion resistance

### Quick-disconnect couplers (per server)

- Non-spill couplers (spill <0.01 mL per disconnect)
- Rated for 1000+ connection cycles
- Color-coded: blue for supply, red for return
- Hot-swappable (rack can be serviced without loop shutdown)

### Rack manifold

- Stainless steel, insulated
- Redundant flow paths (A and B manifolds, 2N)
- Instrumentation: flow meter, pressure, temperature in/out
- Isolation valves at each server takeoff
- Leak detection via moisture sensors on drip trays

### Leak detection

- Capacitive leak sensors in drip trays
- Alarm threshold: 5 mL accumulation
- Automatic shutoff: 50 mL accumulation
- EPMS integration: immediate incident with severity=critical
- Robotic inspection: Gemini ER 1.6 periodic moisture survey

## Operating modes

### Normal operation

- Both A and B manifolds active
- Flow ~40 L/min per rack
- Coolant return 35-45°C depending on IT load
- PUE contribution from DLC loop: 1.03-1.05 (very efficient)

### Manifold maintenance (single-side down)

One manifold can be isolated for service while the other carries full
flow:
- Close isolation valves on A (or B) manifold
- Remaining manifold doubles in flow: 80 L/min
- Pressure rises to ~3.0 bar (within spec)
- No IT impact
- Service window: up to 4 hours per manifold

### Reduced flow (abnormal)

If both manifolds experience degraded flow (pump failure, valve issue):
- Flow 25-35 L/min: IT load must reduce by 25%
- Flow 15-25 L/min: IT load must reduce by 50%
- Flow <15 L/min: emergency shutdown of rack (thermal trip)
- EPMS triggers alerts at each threshold

## Maintenance schedule

### Continuous (EPMS monitoring)

- Per-rack flow (alert if <35 L/min sustained)
- Per-rack supply/return temperature (alert if ΔT >30°C)
- Rack manifold pressure (alert outside 2.0-3.0 bar)
- Drip tray moisture (alert on any detection)

### Monthly

- Visual inspection of all rack manifold connections
- Coolant sample for pH, conductivity, visual color
- Leak detection system self-test
- Review Gemini ER 1.6 thermographic survey results

### Quarterly

- Filter replacement (50-micron, at manifold input)
- Coolant chemistry full analysis (pH, conductivity, metals content)
- Torque verification on all manifold connections
- Leak integrity test (pressure hold test, 24 hours)

### Annual

- Biocide dosing (if bacteria counts elevated in sample)
- Coolant replacement consideration (5-year cycle typical)
- Full manifold drain, clean, and re-charge for any rack showing
  persistent issues

## GPU thermal limits — what to monitor

Blackwell B200 GPU junction temperatures:
- Normal operating: 60-75°C
- Warning: 85°C (monitor for trending)
- Critical: 90°C (automatic throttling begins)
- Shutdown: 95°C (emergency trip)

Per-GPU monitoring via NVIDIA NVSM (NVIDIA System Management):
- Publishes via Redfish API
- EPMS polls Redfish endpoint per rack
- Correlates GPU temperature with DLC loop state

## Troubleshooting

### High GPU temperatures (>85°C) across the rack

- Check DLC supply temperature (should be 18°C ±1°C)
- Check per-rack flow (should be 40 L/min)
- Inspect cold plate thermal paste (if serviced recently)
- Check quick-disconnect seating (full click)

### High GPU temperature on one GPU only

- Likely: cold plate contact issue (thermal paste, mounting)
- Action: remove GPU for cold plate inspection
- Do NOT over-torque cold plate (specified torque only)

### Flow below spec

- Check both A and B manifold valve positions
- Inspect filter differential pressure (replace if >0.5 bar)
- Check pump VSD at facility level
- Pressure test for blockage

### Leak detection alarm

- Evacuate rack aisle immediately (drip tray fills rapidly)
- Isolate the leaking manifold (A or B)
- Assess IT impact (transfer workload if possible)
- Dispatch response team with absorbent materials
- Document in `incidents` with severity=critical

## Integration with EPMS

Per-rack data published to PostgreSQL telemetry:

- Flow rate (L/min)
- Supply and return temperatures (°C)
- Pressure in and out (bar)
- Drip tray moisture status
- Aggregate GPU temperatures (max, avg, min)
- IT load (kW)

EPMS correlates with facility-level data (chiller state, pump flow) to
identify root cause of any rack anomaly.

## References

- NVIDIA GB200 NVL72 Datasheet (NV-DS-GB200NVL72-001)
- NVIDIA Direct Liquid Cooling Installation Guide
- ASHRAE TC 9.9 Technical Committee white paper on liquid cooling
- AHRI 1360 (Performance Rating of Computer Room Air Conditioning)
- a3semi DLC Commissioning Report: A3-ENG-RPT-012
- a3semi DLC Monthly Inspection Log: A3-OPS-FRM-027
