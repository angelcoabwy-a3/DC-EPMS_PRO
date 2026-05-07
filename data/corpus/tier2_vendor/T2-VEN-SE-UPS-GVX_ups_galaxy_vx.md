---
doc_id: T2-VEN-SE-UPS-GVX
tier: 2
priority: high
domain: ups_systems
standard: IEC 62040, IEEE 1184
vendor: Schneider Electric
equipment: Galaxy VX 750 kVA
applies_to: [ups_operation, battery_management, bypass_transfer]
keywords: [galaxy_vx, ups, double_conversion, maintenance_bypass, static_bypass, battery_string]
facility: A3-Alpha Toronto Area
---

# UPS Galaxy VX 750 kVA — Operation and Maintenance

Source: Schneider Electric Galaxy VX Operation Manual (ref: 990-5954)
Equipment: UPS Galaxy VX 750 kVA 2N at A3-Alpha
Applicability: A3-Alpha UPS A and UPS B (identical units, 2N configuration)

## System overview

The Galaxy VX is a double-conversion online UPS providing continuous,
conditioned power with zero transfer time on utility loss. At A3-Alpha, two
Galaxy VX units in a 2N configuration power the entire 16.8 MW load —
each unit sized for full facility load independently.

### Key specifications (per unit)

- Capacity: 750 kVA / 600 kW
- Topology: Online double conversion (VFI-SS-111 per IEC 62040-3)
- Efficiency: 97% in eConversion mode, 96% in double-conversion mode
- Input: 480V 3-phase, 900A nominal
- Output: 480V 3-phase, 720A nominal
- Overload: 125% for 10 minutes, 150% for 1 minute
- Battery runtime: 15 minutes at full load (a3semi spec)
- Battery type: VRLA, 240 cells, 480 VDC nominal

## Operating modes

### 1. Normal (Online double-conversion)

Utility AC -> Rectifier -> DC Bus -> Inverter -> Load

- Input power quality conditioned (IEEE 1100 compliance)
- Battery float-charged at 2.25 V/cell (540 V)
- Zero transfer time on utility loss (inverter continuous)
- Typical mode 99%+ of operating time

### 2. eConversion (high-efficiency)

Utility AC -> Bypass -> Load (with inverter standby)

- Bypass feeds load directly when utility is clean (rare at Tier IV
  facilities with conditioned feeds)
- Inverter remains available for <2 ms transfer on disturbance
- Efficiency 97% (vs 96% double-conversion)
- a3semi uses eConversion only when utility power quality verified

### 3. Battery (on battery)

DC Bus (batteries) -> Inverter -> Load

- Triggered automatically on utility loss
- Runtime: 15 min at full load, 60 min at 25% load
- Low battery warning at 30% capacity
- Automatic shutdown at 15% capacity (configurable)

### 4. Static bypass (fault protection)

Utility AC -> Static Switch -> Load

- Triggered on inverter fault, overload, or thermal trip
- Transfer <4 ms (sub-cycle)
- Load-to-utility direct, NO conditioning
- System alarms and requires operator action to restore

### 5. Maintenance bypass (service)

Utility AC -> Maintenance Bypass Switch -> Load

- MANUAL operation for service/maintenance
- Required for battery replacement, inverter service
- Load is directly on utility with NO UPS protection during this period
- Critical: ensure utility quality is acceptable before transferring

## Maintenance bypass transfer — the MOP

WARNING: Maintenance bypass removes UPS protection. Only transfer when:

1. Utility power quality is verified within ±5% voltage, ±1% frequency
2. No active utility alarms
3. B-side UPS is online and healthy (2N redundancy preserved)
4. Facility manager authorizes via signed work permit

### Transfer to maintenance bypass

Precondition: UPS in online mode, load stable, B-side healthy.

1. Notify NOC and post "UPS A MAINTENANCE" on shift board
2. Don NFPA 70E Category 2 PPE (8 cal/cm² minimum) — see T1-SAF-ARC-002
3. At the UPS front panel: Menu -> Transfer -> Manual Bypass
4. System prompts for confirmation — verify load percentage <125%
5. Confirm transfer — static bypass engages within 4 ms
6. Manually close the maintenance bypass breaker (key-interlocked)
7. Manually open the UPS output breaker (key-interlocked)
8. Verify load is on maintenance bypass — front panel shows "MAINT BYPASS"
9. Apply LOTO to UPS input breaker per T1-SAF-LOTO-001
10. Verify zero energy on UPS input before any service work

### Transfer back to normal operation

Precondition: maintenance work complete, UPS self-test passed.

1. Remove LOTO (all workers remove personal locks per T1-SAF-LOTO-001)
2. Close UPS input breaker, allow rectifier to charge DC bus (30 seconds)
3. Battery charge mode auto-starts (float at 540 V)
4. At UPS front panel: Start UPS (Menu -> Start)
5. UPS runs self-test (30 seconds)
6. Once "READY" status, manually close UPS output breaker
7. Manually open maintenance bypass breaker
8. Front panel should show "ONLINE" mode
9. Verify load on UPS via front panel meters
10. Clear the work permit and update PostgreSQL `procedures` table

## Battery maintenance

UPS Galaxy VX uses VRLA batteries in 4 strings of 60 cells each (240 total
cells). A3-Alpha battery maintenance schedule:

### Monthly (non-intrusive)

- Visual inspection for leaks, swelling, discoloration
- Terminal torque check (inch-lb spec per manufacturer)
- Ambient temperature verification (25°C ±5°C is optimal)
- Impedance test via built-in battery monitor
- Review voltage deviation >2% alarm log

### Quarterly (intrusive — requires maintenance bypass)

- Full capacity test: 25% load discharge for 20 minutes
- Individual cell voltage verification (float voltage 2.25 V ±0.03 V)
- Infrared thermographic scan of all terminals
- Corrosion cleaning if visible
- Torque re-verification

### Annual (intrusive — replacement planning)

- Full discharge test per IEEE 1188 to verify runtime meets spec
- Battery string replacement if capacity <80% of rated
- Expected service life: 5-7 years for VRLA at 25°C ambient

### Battery replacement procedure

Battery replacement is a Tier 1 safety operation:

- Wear sulfuric acid PPE (face shield, apron, neoprene gloves)
- Neutralize any acid spill immediately with baking soda
- Lift batteries with equipment rated for battery weight (each cell ~35 kg)
- Dispose of old batteries per HAZMAT regulations (certified recycler)
- Document replacement in `procedures` table with type=BATTERY_REPLACEMENT

## Front panel indicators — quick reference

| Indicator | State | Meaning |
|-----------|-------|---------|
| GREEN | Online | UPS operating normally, load protected |
| GREEN-flashing | Bypass | On static bypass (fault condition) |
| AMBER | Battery | On battery power, utility lost |
| AMBER-flashing | Maintenance bypass | Load NOT protected, service in progress |
| RED | Fault | Immediate action required |
| RED-flashing | Overload | Load exceeds capacity |

## Alarms and response

| Alarm | Priority | Response |
|-------|----------|----------|
| Input voltage low | Warning | Monitor utility, no action needed |
| Battery fault | Critical | Transfer to B-side, investigate string |
| Inverter overload | Critical | Reduce load immediately, check for short |
| Temperature high | Warning | Check HVAC, verify airflow to UPS |
| EEPROM fault | Critical | UPS requires vendor service — contact 1-800-SCHNEIDER |
| DC bus voltage low | Critical | Batteries depleted, utility loss in progress |

## Integration with EPMS

Galaxy VX publishes status via Modbus TCP (port 502):

- Load percentage (per phase)
- Battery state of charge
- Battery float voltage
- Input/output voltage, current, frequency
- Active alarms

EPMS polls at 1 Hz, logs to PostgreSQL telemetry. Critical alarms trigger
immediate incident creation with severity=critical.

## Common failures and resolution

| Symptom | Cause | Resolution |
|---------|-------|------------|
| Won't start after shutdown | DC bus not charged | Wait 60s after input breaker close |
| Stuck in bypass | Inverter fault history | Check event log, clear fault, restart |
| Low runtime observed | Aged batteries | Schedule capacity test, plan replacement |
| High temperature alarm | Filter clogged | Replace intake filter (quarterly MOP) |
| Audible hum louder | Transformer loading imbalance | Check phase balance, rebalance load |

## Documentation

Each UPS operation generates:
- Entry in `procedures` table (type=UPS_MAINT or UPS_TRANSFER)
- Incident entry if alarm or fault
- Updated battery monitoring log
- Shift report entry with duration and outcome

## References

- Schneider Electric Galaxy VX Operation Manual (990-5954)
- IEC 62040-3 (UPS Method of Specifying Performance)
- IEEE 1184-2023 (Guide for Batteries for UPS Applications)
- IEEE 1188-2020 (Recommended Practice for Maintenance, Testing, and
  Replacement of VRLA Batteries)
- a3semi UPS Maintenance Bypass Permit: A3-OPS-FRM-015
