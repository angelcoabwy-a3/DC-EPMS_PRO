"""
DC-EPMS PRO - Physics Engine: Mechanical Module (Mech Room)
============================================================
Validates and simulates the hydraulic and thermal behaviour of the
Coolant Distribution Units (CDUs), primary/secondary loops, and
facility chilled-water pumps.

Governing physics
-----------------
1. Darcy-Weisbach pressure drop (validate):

        delta_P = f * (L/D) * (rho * v^2 / 2)

   Where:
       f        = Darcy friction factor (dimensionless), here 0.02 for
                  smooth schedule-40 steel at turbulent Re
       L/D      = pipe length-to-diameter ratio
       rho      = fluid density (kg/m^3), 1040 for 50/50 PG/W
       v        = mean flow velocity (m/s)

   Used to cross-check measured supply-to-return pressure drop against
   theoretical for the installed pipe geometry. A residual indicates
   either flow instrumentation drift, valve throttling, or fouling.

2. Pump affinity laws (validate + simulate):

        Q2/Q1 = (N2/N1)           # flow scales linearly with RPM
        H2/H1 = (N2/N1)^2         # head scales with RPM squared
        P2/P1 = (N2/N1)^3         # power scales with RPM cubed

3. CDU heat exchanger effectiveness (validate):

        epsilon = Q_actual / Q_max
        Q_max   = C_min * (T_hot_in - T_cold_in)

   Typical design: epsilon = 0.75-0.85 for plate HX with counterflow.

4. Transient flow + temperature in the secondary loop (simulate):

        dT_return/dt = (Q_in - Q_removed) / (m_loop * cp)

   Where m_loop is the total coolant mass in the secondary loop and
   Q_removed depends on chiller capacity and pump flow. If pump loses
   pressure, flow drops, delta_T rises to keep Q_in = Q_removed.

References
----------
  - T2-VEN-NV-GB200           (Blackwell DLC coolant specification)
  - T2-VEN-SE-WP122           (Schneider critical power/cooling)
  - T4-MOP-CHI-001            (York YZ chiller quarterly PM)
  - Moody diagram for friction factors (turbulent region)
"""

from __future__ import annotations

import logging
from typing import Any

try:
    import numpy as np
    from scipy.integrate import solve_ivp

    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    np = None
    solve_ivp = None

from backend.physics.base import (
    PhysicalJustification,
    PhysicsModule,
    Severity,
    StateSnapshot,
    ValidationResult,
)

log = logging.getLogger("dc-epms.physics.mechanical")


# ---------------------------------------------------------------------------
#  Fluid properties and pipe geometry for A3-Alpha Toronto Area
# ---------------------------------------------------------------------------

# --- 50/50 propylene glycol-water coolant at ~30 C ---
RHO_PGW = 1_040.0  # kg/m^3
CP_PGW = 3_650.0  # J/(kg*K)
MU_PGW = 3.2e-3  # Pa*s (dynamic viscosity, ~3x that of water)

# --- Secondary loop pipe geometry (approximate, plant as-built) ---
# Main headers going from CDU to manifolds
LOOP_PIPE_DIAMETER_M = 0.152  # 6" schedule-40 steel
LOOP_PIPE_LENGTH_M = 240.0  # aggregated round-trip length per hall
DARCY_FRICTION_FACTOR = 0.020  # turbulent, commercial steel

# --- Per-hall secondary loop design ---
HALL_FLOW_NOMINAL_M3_S = 0.066  # ~4000 L/min = 40 racks x 100 L/min
HALL_FLOW_NOMINAL_L_MIN = 3960.0
HALL_COOLANT_MASS_KG = 4_500.0  # aggregate fluid in hall loop (pipes + HX)

# --- CDU thermal design ---
CDU_NOMINAL_CAPACITY_KW = 6_000.0  # 6 MW per CDU
CDU_EFFECTIVENESS_NOMINAL = 0.82  # plate HX effectiveness
CDU_APPROACH_NOMINAL_K = 2.5  # T_cold_out - T_cold_in at design

# --- Pump design ---
PUMP_RATED_HEAD_M = 35.0  # 35 m head at rated flow
PUMP_RATED_POWER_KW = 45.0  # 45 kW shaft input at rated point
PUMP_MIN_SUCTION_PRESSURE_BAR = 1.2  # below this, cavitation risk rises


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _volumetric_to_velocity(
    flow_m3_s: float,
    diameter_m: float,
) -> float:
    """Convert volumetric flow to mean velocity through a pipe section.

    v = Q / A = Q / (pi/4 * D^2)
    """
    import math

    area = math.pi * 0.25 * diameter_m**2
    return flow_m3_s / area if area > 0 else 0.0


def _reynolds_number(
    velocity_m_s: float,
    diameter_m: float,
    density: float = RHO_PGW,
    viscosity: float = MU_PGW,
) -> float:
    """Reynolds number for pipe flow: Re = rho * v * D / mu."""
    return density * velocity_m_s * diameter_m / viscosity


def _darcy_pressure_drop_pa(
    flow_m3_s: float,
    diameter_m: float = LOOP_PIPE_DIAMETER_M,
    length_m: float = LOOP_PIPE_LENGTH_M,
    friction_factor: float = DARCY_FRICTION_FACTOR,
    density: float = RHO_PGW,
) -> float:
    """Darcy-Weisbach pressure drop across a uniform pipe section.

    Returns pressure drop in Pascals.
    """
    v = _volumetric_to_velocity(flow_m3_s, diameter_m)
    if length_m == 0 or diameter_m == 0:
        return 0.0
    return friction_factor * (length_m / diameter_m) * (density * v**2 / 2.0)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ---------------------------------------------------------------------------
#  MechanicalModule
# ---------------------------------------------------------------------------


class MechanicalModule(PhysicsModule):
    """Validator + simulator for the cooling mechanical plant.

    Expected measurement schema (validate):
        {
          "loop_flow_m3_s":        float,   # secondary loop volumetric flow
          "loop_dp_measured_bar":  float,   # supply-to-return pressure drop
          "loop_supply_c":         float,   # T at CDU secondary out
          "loop_return_c":         float,   # T at CDU secondary in
          "cdu_primary_in_c":      float,   # T at CDU primary (chilled water)
          "cdu_primary_out_c":     float,
          "cdu_primary_flow_m3_s": float,
          "pump_speed_hz":         float,   # VFD output frequency, nominal 60
          "pump_suction_bar":      float,   # NPSH indicator
          "pump_power_kw":         float,   # measured shaft power
          "rack_count":            int,
          "rack_tdp_kw":           float,
        }
    Absent keys fall back to nominal design values.
    """

    module_name = "mechanical"

    # ------------------------------------------------------------------ #
    #  Steady-state validation
    # ------------------------------------------------------------------ #

    def validate(
        self,
        measurements: dict[str, Any],
    ) -> ValidationResult:
        """Check mechanical-plant telemetry against physics."""
        r = ValidationResult(module=self.module_name)

        # --- Parse with sensible nominal defaults ---
        flow = float(measurements.get("loop_flow_m3_s", HALL_FLOW_NOMINAL_M3_S))
        dp_meas_bar = float(measurements.get("loop_dp_measured_bar", 0.85))
        loop_supply_c = float(measurements.get("loop_supply_c", 18.0))
        loop_return_c = float(measurements.get("loop_return_c", 40.0))
        cdu_prim_in = float(measurements.get("cdu_primary_in_c", 7.0))
        cdu_prim_out = float(measurements.get("cdu_primary_out_c", 14.0))
        cdu_prim_flow = float(measurements.get("cdu_primary_flow_m3_s", 0.08))
        pump_hz = float(measurements.get("pump_speed_hz", 60.0))
        pump_suct_bar = float(measurements.get("pump_suction_bar", 1.8))
        pump_power_kw = float(measurements.get("pump_power_kw", 45.0))
        rack_count = int(measurements.get("rack_count", 40))
        rack_kw = float(measurements.get("rack_tdp_kw", 142.0))

        # ============ Check 1: Darcy-Weisbach pressure drop ==============
        dp_expected_pa = _darcy_pressure_drop_pa(flow)
        dp_expected_bar = dp_expected_pa / 1e5

        dp_residual_bar = dp_meas_bar - dp_expected_bar
        # Threshold: 30% of expected or 0.2 bar floor
        dp_threshold_bar = max(abs(dp_expected_bar) * 0.30, 0.20)
        dp_ok = abs(dp_residual_bar) <= dp_threshold_bar
        r.add_check(
            name="darcy_weisbach_loop_pressure_drop",
            passed=dp_ok,
            value=dp_residual_bar,
            threshold=dp_threshold_bar,
            unit="bar",
        )

        if not dp_ok:
            if dp_residual_bar > 0:
                interp = (
                    f"Measured loop pressure drop {dp_meas_bar:.2f} bar "
                    f"exceeds Darcy-Weisbach theoretical "
                    f"{dp_expected_bar:.2f} bar by {dp_residual_bar:.2f} bar. "
                    f"Suggests partial blockage (clogged filter, partially "
                    f"closed valve, or debris) increasing local losses."
                )
                action = (
                    "Inspect secondary-loop strainer differential pressure "
                    "per T4-MOP-CHI-001 section 'Filter replacement'. "
                    "Check valve positions on manifold."
                )
                r.escalate(Severity.WARNING)
            else:
                interp = (
                    f"Measured loop pressure drop {dp_meas_bar:.2f} bar is "
                    f"below theoretical {dp_expected_bar:.2f} bar by "
                    f"{-dp_residual_bar:.2f} bar. Suggests a bypass path "
                    f"(leak, open bypass valve, or flow-meter under-reading)."
                )
                action = (
                    "Inspect secondary loop for leaks. Verify bypass valve "
                    "state. Cross-check flow meter against pump affinity "
                    "curve."
                )
                r.escalate(Severity.WARNING)
            r.add_justification(
                PhysicalJustification(
                    law="darcy_weisbach",
                    measured={
                        "loop_dp_measured_bar": dp_meas_bar,
                        "loop_flow_m3_s": flow,
                        "loop_flow_l_min": flow * 60_000.0,
                    },
                    expected={"dp_theoretical_bar": dp_expected_bar},
                    residual={"dp_residual_bar": dp_residual_bar},
                    threshold={"dp_threshold_bar": dp_threshold_bar},
                    interpretation=interp,
                    suggested_action=action,
                )
            )

        # ============ Check 2: CDU thermal balance ======================
        # Secondary side heat pickup
        m_dot_sec = flow * RHO_PGW
        q_secondary_kw = m_dot_sec * CP_PGW * (loop_return_c - loop_supply_c) / 1000.0

        # Primary side heat removal (chilled water, assume water cp=4180)
        m_dot_prim = cdu_prim_flow * 1000.0  # water density 1000 kg/m^3
        q_primary_kw = m_dot_prim * 4180.0 * (cdu_prim_out - cdu_prim_in) / 1000.0

        cdu_residual_kw = q_secondary_kw - q_primary_kw
        cdu_threshold_kw = max(abs(q_secondary_kw) * 0.05, 200.0)
        cdu_ok = abs(cdu_residual_kw) <= cdu_threshold_kw
        r.add_check(
            name="cdu_heat_balance",
            passed=cdu_ok,
            value=cdu_residual_kw,
            threshold=cdu_threshold_kw,
            unit="kW",
        )

        if not cdu_ok:
            interp = (
                f"CDU secondary heat pickup {q_secondary_kw:.0f} kW vs "
                f"primary heat removal {q_primary_kw:.0f} kW. Residual "
                f"{cdu_residual_kw:+.0f} kW exceeds threshold. "
                f"Possible heat exchanger fouling or instrumentation drift."
            )
            action = (
                "Verify RTD calibration on CDU inlet/outlet. Review plate "
                "HX cleaning log per T4-MOP-CHI-001."
            )
            r.escalate(Severity.WARNING)
            r.add_justification(
                PhysicalJustification(
                    law="cdu_heat_exchanger_balance",
                    measured={
                        "q_secondary_kw": q_secondary_kw,
                        "q_primary_kw": q_primary_kw,
                        "loop_supply_c": loop_supply_c,
                        "loop_return_c": loop_return_c,
                        "cdu_primary_in_c": cdu_prim_in,
                        "cdu_primary_out_c": cdu_prim_out,
                    },
                    expected={
                        "balanced_kw": 0.0,
                    },
                    residual={"residual_kw": cdu_residual_kw},
                    threshold={"threshold_kw": cdu_threshold_kw},
                    interpretation=interp,
                    suggested_action=action,
                )
            )

        # ============ Check 3: Pump affinity laws (expected power) ======
        speed_ratio = pump_hz / 60.0  # nominal is 60 Hz (North America)
        expected_power_kw = PUMP_RATED_POWER_KW * (speed_ratio**3)
        power_residual = pump_power_kw - expected_power_kw
        power_threshold = max(expected_power_kw * 0.20, 3.0)
        power_ok = abs(power_residual) <= power_threshold
        r.add_check(
            name="pump_affinity_cubic_power",
            passed=power_ok,
            value=power_residual,
            threshold=power_threshold,
            unit="kW",
        )
        if not power_ok:
            if power_residual > 0:
                interp = (
                    f"Pump at {pump_hz:.1f} Hz drawing {pump_power_kw:.1f} kW, "
                    f"affinity-law expectation {expected_power_kw:.1f} kW. "
                    f"Over by {power_residual:.1f} kW. Likely bearing friction "
                    f"or impeller fouling."
                )
            else:
                interp = (
                    f"Pump at {pump_hz:.1f} Hz drawing {pump_power_kw:.1f} kW, "
                    f"below affinity-law expectation {expected_power_kw:.1f} kW "
                    f"by {-power_residual:.1f} kW. Likely cavitation or "
                    f"reduced system resistance (open bypass)."
                )
            action = (
                "Record vibration spectrum. Check suction pressure. "
                "Compare to pump-curve factory data."
            )
            r.escalate(Severity.INFO)
            r.add_justification(
                PhysicalJustification(
                    law="pump_affinity_cubic",
                    measured={
                        "pump_power_kw": pump_power_kw,
                        "pump_speed_hz": pump_hz,
                    },
                    expected={"power_kw_at_speed": expected_power_kw},
                    residual={"residual_kw": power_residual},
                    threshold={"threshold_kw": power_threshold},
                    interpretation=interp,
                    suggested_action=action,
                )
            )

        # ============ Check 4: Pump NPSH / cavitation risk ==============
        cavit_ok = pump_suct_bar >= PUMP_MIN_SUCTION_PRESSURE_BAR
        r.add_check(
            name="pump_cavitation_margin",
            passed=cavit_ok,
            value=pump_suct_bar,
            threshold=PUMP_MIN_SUCTION_PRESSURE_BAR,
            unit="bar",
        )
        if not cavit_ok:
            margin = PUMP_MIN_SUCTION_PRESSURE_BAR - pump_suct_bar
            interp = (
                f"Pump suction pressure {pump_suct_bar:.2f} bar below "
                f"{PUMP_MIN_SUCTION_PRESSURE_BAR:.2f} bar NPSH minimum by "
                f"{margin:.2f} bar. Cavitation erosion accelerates; pump "
                f"output and efficiency degrade non-linearly."
            )
            action = (
                "Raise expansion-tank pressure; verify air-vent operation; "
                "check suction-side strainer. See T4-MOP-CHI-001."
            )
            r.escalate(Severity.CRITICAL if margin > 0.3 else Severity.WARNING)
            r.add_justification(
                PhysicalJustification(
                    law="pump_npsh_limit",
                    measured={"pump_suction_bar": pump_suct_bar},
                    expected={"min_suction_bar": PUMP_MIN_SUCTION_PRESSURE_BAR},
                    residual={"margin_bar": -margin},
                    threshold={"min_suction_bar": PUMP_MIN_SUCTION_PRESSURE_BAR},
                    interpretation=interp,
                    suggested_action=action,
                )
            )

        # --- Compute module health ---
        penalty = max(
            0.0 if dp_ok else min(0.4, abs(dp_residual_bar) / max(dp_threshold_bar, 0.01) * 0.15),
            0.0 if cdu_ok else 0.20,
            0.0 if power_ok else 0.10,
            0.0 if cavit_ok else 0.60,
        )
        r.health = _clamp01(1.0 - penalty)

        r.metrics = {
            "loop_flow_m3_s": flow,
            "loop_flow_l_min": flow * 60_000.0,
            "loop_dp_measured_bar": dp_meas_bar,
            "loop_dp_theoretical_bar": dp_expected_bar,
            "q_secondary_kw": q_secondary_kw,
            "q_primary_kw": q_primary_kw,
            "pump_power_kw": pump_power_kw,
            "pump_suction_bar": pump_suct_bar,
            "health": r.health,
        }

        return r

    # ------------------------------------------------------------------ #
    #  Transient simulation
    # ------------------------------------------------------------------ #

    def simulate(
        self,
        initial_state: dict[str, float],
        perturbation: dict[str, Any],
        horizon_s: int = 900,
        dt_s: float = 1.0,
    ) -> list[StateSnapshot]:
        """Integrate secondary-loop temperature ODE under mechanical faults.

        Governing ODE:
            dT_return/dt = (Q_in - Q_removed(t)) / (m_loop * cp)

        Perturbation schema:
            {
              "type": str,
              "flow_factor":    float [0,1]  - retained flow fraction
              "pump_trip":      bool         - if True, flow -> 0 instantly
              "start_s":        int          - when fault begins
              "duration_s":     int          - how long fault persists
              "rack_kw_mult":   float        - IT-load multiplier
            }
        """
        T0_return = float(initial_state.get("loop_return_c", 40.0))
        T_supply = float(initial_state.get("loop_supply_c", 18.0))
        rack_count = int(initial_state.get("rack_count", 40))
        rack_kw = float(initial_state.get("rack_tdp_kw", 142.0))
        flow_nom = float(initial_state.get("loop_flow_m3_s", HALL_FLOW_NOMINAL_M3_S))

        flow_factor = float(perturbation.get("flow_factor", 1.0))
        pump_trip = bool(perturbation.get("pump_trip", False))
        start_s = float(perturbation.get("start_s", 0.0))
        duration_s = float(perturbation.get("duration_s", horizon_s))
        rack_kw_mult = float(perturbation.get("rack_kw_mult", 1.0))

        # Effective fault factor
        if pump_trip:
            flow_factor = 0.02  # near-zero flow (natural convection residual)

        m_loop = HALL_COOLANT_MASS_KG
        cp = CP_PGW

        Q_in_w = rack_count * rack_kw * rack_kw_mult * 0.95 * 1000.0
        # At steady state, Q_removed equals Q_in exactly. Under fault, the
        # CDU can still extract heat but only as fast as the flow carries
        # coolant through it. Q_removed ~= flow * cp * (T_return - T_supply).
        # So if flow drops, T_return must rise to maintain balance.

        def dTdt(t, T):
            t_s = float(t)
            fault_active = start_s <= t_s < (start_s + duration_s)
            ff = flow_factor if fault_active else 1.0
            flow_now = flow_nom * ff
            m_dot_now = flow_now * RHO_PGW

            # Heat removed by the CDU at current flow and T_return
            Q_out = m_dot_now * cp * (float(T[0]) - T_supply)
            return np.array([(Q_in_w - Q_out) / (m_loop * cp)])

        if HAS_SCIPY:
            t_eval = np.arange(0.0, horizon_s + dt_s, dt_s)
            sol = solve_ivp(
                dTdt,
                (0.0, float(horizon_s)),
                y0=np.array([T0_return]),
                t_eval=t_eval,
                method="RK45",
                rtol=1e-4,
                atol=1e-3,
            )
            if not sol.success:
                log.error("mechanical ODE failed: %s", sol.message)
                return []
            ts = sol.t
            Ts = sol.y[0]
        else:
            # Explicit Euler fallback
            ts = np.arange(0.0, horizon_s + dt_s, dt_s) if np else None
            if ts is None:
                # No numpy; pure python fallback
                ts_list, T_list = [], []
                T = T0_return
                t = 0.0
                while t <= horizon_s:
                    fault_active = start_s <= t < start_s + duration_s
                    ff = flow_factor if fault_active else 1.0
                    m_dot_now = flow_nom * ff * RHO_PGW
                    Q_out = m_dot_now * cp * (T - T_supply)
                    dT = (Q_in_w - Q_out) / (m_loop * cp)
                    T += dT * dt_s
                    ts_list.append(t)
                    T_list.append(T)
                    t += dt_s
                ts, Ts = ts_list, T_list
            else:
                Ts = np.zeros_like(ts)
                Ts[0] = T0_return
                for i in range(1, len(ts)):
                    T_prev = float(Ts[i - 1])
                    dT = dTdt(ts[i - 1], np.array([T_prev]))[0]
                    Ts[i] = T_prev + dT * dt_s

        # --- Build trajectory with event detection ---
        trajectory: list[StateSnapshot] = []
        overtemp_triggered = False
        for i, t in enumerate(ts):
            T_return = float(Ts[i])
            t_s = float(t)
            fault_active = start_s <= t_s < (start_s + duration_s)
            ff = flow_factor if fault_active else 1.0

            events = []
            # Secondary loop over-temperature event: return > design max (45 C)
            if T_return > 45.0 and not overtemp_triggered:
                events.append("secondary_loop_overtemp")
                overtemp_triggered = True

            trajectory.append(
                StateSnapshot(
                    t=t_s,
                    state={
                        "loop_return_c": T_return,
                        "loop_supply_c": T_supply,
                        "flow_factor": ff,
                        "flow_m3_s": flow_nom * ff,
                        "dlc_delta_T_k": T_return - T_supply,
                    },
                    events=events,
                )
            )

        return trajectory
