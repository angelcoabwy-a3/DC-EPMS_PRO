---
doc_id: T3-STD-THERMAL-MODEL
tier: 3
priority: medium
domain: thermal_physics
standard: First Law of Thermodynamics, Newton's Law of Cooling
applies_to: [ttc_calculation, thermal_transient, predictive_control]
keywords: [newton_cooling, thermal_model, ttc, time_to_critical, predictive, physics]
facility: A3-Alpha Toronto Area
---

# Data Center Thermal Model — Physics of Time-to-Critical

Source: First Law of Thermodynamics; Newton's Law of Cooling
Application: A3-Alpha Toronto Area EPMS predictive thermal control

## Purpose

Quantify the time available to respond to cooling capacity loss before
reaching ASHRAE A2 upper limit (35°C). This time is the Time-to-Critical
(TTC), and it drives response procedures, operator reaction budgets, and
automation thresholds.

## The governing equation

First Law of Thermodynamics for a control volume (the data hall):

```
dU/dt = Q_in - Q_out

where:
  U      = internal energy of the hall air (J)
  Q_in   = heat added to the hall (W) = IT load dissipated to air
  Q_out  = heat removed from the hall (W) = cooling capacity
  t      = time (s)
```

Assuming ideal gas (air) with fixed mass:

```
dT/dt = (Q_in - Q_out) / (m * c_p)

where:
  T      = hall air temperature (K)
  m      = mass of air in the hall (kg)
  c_p    = specific heat capacity of air (J/kg·K) = 1005 J/kg·K at 20°C
```

## A3-Alpha hall parameters

### Per hall (Hall A, B, or C)

- Volume: 800 m³ (40 m × 20 m × 10 m)
- Air mass: ~960 kg (density 1.2 kg/m³ at 20°C, 101.3 kPa)
- Effective thermal mass (including steel, concrete): ~12,000 kJ/K
- Rack count per hall: 40 racks (slight variation for aisle spacing)

### Heat load

At A3-Alpha with Blackwell NVL72:

```
Q_rack_total = 142 kW (typical, per rack)
Q_to_DLC     = 142 × 0.95 = 134.9 kW (to liquid loop)
Q_to_air     = 142 × 0.05 = 7.1 kW (to air, per rack)
Q_hall_air   = 40 racks × 7.1 kW = 284 kW (per hall)
Q_facility   = 118 × 142 = 16,756 kW (total IT)
```

### Cooling capacity

CRAH units per hall (air side):
- 6 CRAHs per hall, each 75 kW = 450 kW capacity per hall
- Normal operation: 284 kW load = 63% capacity utilization
- Good margin for transients

DLC loop per hall (liquid side):
- 40 racks × 40 L/min = 1600 L/min per hall
- ΔT = 24°C (18°C supply, 42°C return typical)
- Q_DLC = 1600 L/min × 1 kg/L × 4.186 kJ/kg/K × 24°C / 60s = 2677 kW
- This captures the ~5400 kW DLC load per hall (with margin)

## Newton's Law of Cooling — transient model

When cooling is reduced (chiller trip, pump failure), temperature rises
following:

```
dT/dt = (Q_in - Q_out_reduced) / (m * c_p)

If Q_out = 0 (total cooling loss):
T(t) = T_0 + (Q_in / (m * c_p)) * t

With Q_in = 284,000 W per hall, m*c_p = 960 * 1005 = 965,000 J/K:
T(t) = T_0 + (284,000 / 965,000) * t
T(t) = T_0 + 0.294 * t  (°C per second)
```

Wait — this is initial rise rate. Real response is asymptotic because
hot aisles exchange heat with structure (concrete, steel, equipment
housings have thermal mass).

### Full exponential model

```
T(t) = T_ss + (T_0 - T_ss) * exp(-t / tau)

where:
  T_ss   = steady-state temperature with reduced cooling
  T_0    = initial temperature
  tau    = thermal time constant
```

### Measured A3-Alpha parameters

From commissioning tests:
- tau (time constant) = 53.3 seconds
- T_ss (no-cooling steady state) = 45°C
- T_0 (normal operating) = 22°C

## Solving for TTC — when does T reach 35°C?

```
35 = 45 + (22 - 45) * exp(-t / 53.3)
35 - 45 = -23 * exp(-t / 53.3)
-10 = -23 * exp(-t / 53.3)
10/23 = exp(-t / 53.3)
ln(10/23) = -t / 53.3
t = -53.3 * ln(10/23)
t = -53.3 * (-0.832)
t = 44.3 seconds
```

**TTC from normal 22°C to A2 critical 35°C = 44 seconds.**

This is the operator/automation response budget.

## Partial cooling loss — more realistic

Total cooling loss is rare. Partial loss (50% cooling) is more common:

```
If Q_out = 0.5 * Q_in:
dT/dt = (Q_in - 0.5*Q_in) / (m*c_p) = 0.5*Q_in / (m*c_p)

The hall reaches a new steady-state T_ss' where cooling = load:
T_ss' = T_0 + ΔT where ΔT is set by cooling capacity

For 50% cooling: T_ss' could be around 28-30°C (still within A2)
This is why N+1 cooling is essential — even N (no redundancy) at 50%
capacity stays within A2 envelope.
```

## Warm-up time — reverse scenario

Cold start (DLC supply water colder than hall dew point):

Risk: DLC manifold condensation. Time to reach steady-state is also
~53 seconds. If supply water is 15°C and dew point is 18°C, condensation
begins forming within seconds.

Mitigation: EPMS checks dew-point margin continuously, raises supply
temperature before condensation can form.

## Predictive control — how A3-Alpha uses this

The 44-second TTC is too short for human response alone. A3-Alpha uses
predictive control:

### Forward simulation

Every 15 seconds, EPMS runs a 60-second forward simulation:
- Input: current telemetry (temperatures, flows, IT load)
- Model: the equations above
- Output: predicted temperature in 60 seconds

### Advisory trigger

If predicted T > 30°C in 60 seconds:
- Severity: warning
- Action: advisory to NOC, pre-position chiller to higher load

If predicted T > 35°C in 60 seconds:
- Severity: critical
- Action: automatic load shedding or emergency cooling ramp
- NOC notified simultaneously

### RAG-grounded advisory generation

When trigger fires, EPMS queries the RAG with:
> "Current PUE 1.4X, hall temp 30°C, predicted 34°C in 60s.
> What is the Schneider WP122 thermal mitigation procedure?"

RAG returns the relevant procedure chunk, which is synthesized into an
actionable advisory for the operator.

## Validation — measured vs predicted

A3-Alpha validates the model quarterly:

### Test protocol
1. Select a non-production hall (if available) or low-load period
2. Reduce cooling capacity by 25% for 5 minutes
3. Record temperature rise
4. Compare to model prediction

### Expected accuracy
- Temperature prediction: ±1°C at 60 seconds ahead
- TTC prediction: ±10% for total cooling loss scenarios
- Partial cooling: ±15% (more variability from CRAH response)

### Continuous improvement

Model parameters (tau, T_ss) are updated based on measured data. This
is critical because:
- Building envelope changes (insulation, openings) affect tau
- New equipment adds thermal mass
- Seasonal humidity affects air properties

## Integration with EPMS

Physics model runs continuously:

1. 1 Hz polling of temperatures and flows
2. Every 15 seconds: run forward simulation
3. Every 60 seconds: update tau and T_ss from recent data
4. Every 5 minutes: archive predictions vs actuals (for validation)
5. Quarterly: report model accuracy to facility engineer

## Boundary conditions and caveats

The model assumes:
- Uniform temperature within the hall (reasonable for well-mixed air
  with containment)
- Steady IT load (but we update every 15s for load changes)
- No infiltration (hall sealed, positive pressure)
- No ventilation (this is a closed HVAC system with recirculation)

Conditions that violate these:
- Door left open → rapid heat exchange with corridor
- Fire suppression discharge → sudden cooling and mass change
- Major wall damage → rapid thermal coupling to outside

The model is DISABLED during abnormal physical conditions. Operator
judgment takes over.

## References

- Fundamentals of Heat and Mass Transfer, Incropera et al.
- ASHRAE Handbook Fundamentals, Chapter 1 (Psychrometrics) and
  Chapter 2 (Thermodynamics and Refrigeration Cycles)
- NVIDIA GB200 NVL72 Datasheet (for Q_to_air fraction)
- a3semi Thermal Model Validation Reports (quarterly)
- a3semi Hall Thermal Characterization Study: A3-ENG-STU-003
