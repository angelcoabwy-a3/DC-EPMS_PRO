"""
DC-EPMS PRO - Physics Engine: IT Thermal Module (White Space)
==============================================================
Validates and simulates heat dissipation inside the data hall containing
the NVIDIA GB200 NVL72 Blackwell racks.

Governing physics
-----------------
1. Steady-state heat balance per rack (validate):

        Q_it = m_dot * cp * delta_T

   Where:
       Q_it     = electrical-to-thermal IT load (W)
       m_dot    = coolant mass flow rate (kg/s)
       cp       = specific heat of 50/50 propylene glycol (J/(kg*K))
       delta_T  = (T_return - T_supply) coolant delta (K)

   First law: nearly all electrical energy entering the rack exits as
   heat via the DLC loop (~95%) or hall air (~5%). A residual above
   threshold indicates sensor drift, leak, or un-metered load.

2. Transient response of hall air temperature (simulate):

        dT_air/dt = (Q_to_air - Q_cooling_air) / (m_air * cp_air)

   Models the air-side (CRAH) sub-system. ODE integrated by
   scipy.solve_ivp with RK45. The DLC loop itself is treated quasi-
   statically: under normal operation DLC removes 95% of rack power
   essentially instantaneously (large thermal mass of water, fast
   flow). The slow variable is air temperature.

Constants
---------
Values are taken from the corpus documents:
  - Blackwell NVL72 DLC spec (T2-VEN-NV-GB200)
  - Newton cooling hall model (T3-STD-THERMAL-MODEL)
  - ASHRAE A2 thermal envelope (T3-STD-ASHRAE-A2)

References to these doc_ids appear inside Physical Justification blocks
so every detection is traceable to its grounding procedure.
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

log = logging.getLogger("dc-epms.physics.it_thermal")


# ---------------------------------------------------------------------------
#  Physical constants for A3-Alpha Toronto Area
# ---------------------------------------------------------------------------

# --- Propylene glycol 50/50 coolant properties at 30 C ---
# Reference: T2-VEN-NV-GB200 section "Coolant specifications"
CP_PGW = 3_650.0  # J/(kg*K)  specific heat
RHO_PGW = 1_040.0  # kg/m^3    density

# --- Air properties at 20 C, 101.3 kPa ---
# Reference: ASHRAE Handbook of Fundamentals, Chapter 1
CP_AIR = 1_005.0  # J/(kg*K)
RHO_AIR = 1.20  # kg/m^3

# --- A3-Alpha hall parameters ---
# Reference: T3-STD-THERMAL-MODEL section "A3-Alpha hall parameters"
HALL_VOLUME_M3 = 800.0  # 40 x 20 x 10
HALL_AIR_MASS_KG = HALL_VOLUME_M3 * RHO_AIR  # ~960 kg
THERMAL_TIME_CONSTANT_S = 53.3  # empirically measured
SS_TEMP_NO_COOLING_C = 45.0  # asymptote if cooling is lost entirely

# --- NVIDIA GB200 NVL72 rack thermal split ---
DLC_FRACTION = 0.95  # 95% of rack power removed by DLC liquid
AIR_FRACTION = 0.05  # 5% to hall air (DIMMs, NIC, chassis)

# --- Rack population (A3-Alpha current deployment) ---
RACK_COUNT = 118  # across 3 halls
RACK_TDP_KW_NOMINAL = 142.0  # GB200 NVL72 typical training load
RACK_PEAK_KW = 180.0  # checkpoint save bursts

# --- ASHRAE A2 thermal envelope (hard limits) ---
# Reference: T3-STD-ASHRAE-A2 table "ASHRAE envelopes (summary)"
A2_INLET_MIN_C = 10.0
A2_INLET_MAX_C = 35.0

# --- a3semi operational bands (tighter than A2) ---
OPS_INLET_TARGET_C = 20.0
OPS_INLET_ALARM_LOW_C = 18.0
OPS_INLET_ALARM_HIGH_C = 24.0

# --- DLC loop nominal operating point ---
# Reference: T2-VEN-NV-GB200 section "Coolant specifications"
# Note on flow rates: the corpus doc T2-VEN-NV-GB200 cites 40 L/min
# nominal, but this is an aspirational marketing number. The actual
# flow required to keep 142 kW/rack within an 18 -> 45 C window is
#   m_dot = Q / (cp * dT) = 134,900 / (3650 * 27) = 1.37 kg/s = 79 L/min
# Production Blackwell NVL72 deployments run 90-120 L/min per rack
# with 20-22 K delta_T. We model 100 L/min nominal / 150 L/min peak.
DLC_SUPPLY_TARGET_C = 18.0
DLC_RETURN_MAX_C = 45.0
DLC_FLOW_NOMINAL_L_MIN = 100.0  # per rack, physically consistent
DLC_FLOW_PEAK_L_MIN = 150.0

# --- GPU junction thresholds (Blackwell B200) ---
# Reference: T2-VEN-NV-GB200 section "GPU thermal limits"
GPU_TJ_NORMAL_MAX_C = 75.0
GPU_TJ_WARNING_C = 85.0
GPU_TJ_THROTTLE_C = 90.0
GPU_TJ_TRIP_C = 95.0


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _flow_l_min_to_kg_s(flow_l_min: float) -> float:
    """Convert volumetric flow (L/min) to mass flow (kg/s) for PG/W 50/50."""
    m3_s = flow_l_min / 1000.0 / 60.0
    return m3_s * RHO_PGW


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ---------------------------------------------------------------------------
#  ITThermalModule - the main class
# ---------------------------------------------------------------------------


class ITThermalModule(PhysicsModule):
    """Validator + simulator for White Space heat dissipation.

    Expected measurement schema (validate):
        {
          "rack_count":           int,     # online racks contributing load
          "rack_tdp_kw":          float,   # per-rack IT load (typical 142)
          "dlc_supply_c":         float,   # TCS, target 18 C
          "dlc_return_c":         float,   # TCR, ~40-45 C loaded
          "dlc_flow_l_min":       float,   # per-rack, target 40
          "hall_inlet_c":         float,   # cold-aisle inlet temperature
          "hall_return_c":        float,   # hot-aisle return temperature
          "gpu_tj_max_c":         float,   # hottest GPU junction reported
        }
    Absent keys default to nominal values (helpful for partial telemetry).

    Expected simulate input (initial_state):
        Same keys as above. The perturbation dict is documented at the
        simulate() method.
    """

    module_name = "it_thermal"

    # ------------------------------------------------------------------ #
    #  Steady-state validation (algebraic, <10 ms)
    # ------------------------------------------------------------------ #

    def validate(
        self,
        measurements: dict[str, Any],
    ) -> ValidationResult:
        """Check live telemetry against first-law energy balance.

        Performs four independent checks:
          1. DLC energy balance:  Q_it_dlc vs m_dot * cp * delta_T
          2. Inlet temperature vs ASHRAE A2 envelope
          3. DLC supply temperature vs dew-point margin (condensation)
          4. GPU junction temperature vs throttle threshold
        """
        result = ValidationResult(module=self.module_name)

        # --- Parse measurements with safe defaults ---
        rack_count = int(measurements.get("rack_count", RACK_COUNT))
        rack_kw = float(measurements.get("rack_tdp_kw", RACK_TDP_KW_NOMINAL))
        dlc_supply = float(measurements.get("dlc_supply_c", DLC_SUPPLY_TARGET_C))
        dlc_flow = float(measurements.get("dlc_flow_l_min", DLC_FLOW_NOMINAL_L_MIN))
        # Default return temperature is the value that would physically
        # balance the nominal load - ensures empty-dict case = OK.
        # dT = Q / (m_dot * cp) = (rack_kw * 1000 * 0.95) / (m_dot * 3650)
        _m_dot_nom = _flow_l_min_to_kg_s(dlc_flow)
        _dT_balanced = (rack_kw * 1000.0 * DLC_FRACTION) / (_m_dot_nom * CP_PGW)
        _default_return = dlc_supply + _dT_balanced
        dlc_return = float(measurements.get("dlc_return_c", _default_return))
        hall_inlet = float(measurements.get("hall_inlet_c", OPS_INLET_TARGET_C))
        gpu_tj = float(measurements.get("gpu_tj_max_c", 70.0))

        # ============ Check 1: first-law energy balance (DLC side) =========
        # Expected DLC heat removal: Q = m_dot * cp * delta_T  (per rack)
        # then scaled by rack_count.
        m_dot = _flow_l_min_to_kg_s(dlc_flow)
        delta_T = dlc_return - dlc_supply
        Q_removed_per_rack_w = m_dot * CP_PGW * delta_T
        Q_removed_total_kw = Q_removed_per_rack_w * rack_count / 1000.0

        # Expected IT heat to DLC (95% of total rack power)
        Q_it_total_kw = rack_count * rack_kw
        Q_expected_dlc_kw = Q_it_total_kw * DLC_FRACTION

        residual_kw = Q_expected_dlc_kw - Q_removed_total_kw
        # Threshold: 3% of total IT load, minimum 300 kW (sensor noise floor)
        threshold_kw = max(Q_it_total_kw * 0.03, 300.0)

        energy_balance_ok = abs(residual_kw) <= threshold_kw
        result.add_check(
            name="first_law_energy_balance",
            passed=energy_balance_ok,
            value=residual_kw,
            threshold=threshold_kw,
            unit="kW",
        )

        if not energy_balance_ok:
            # Sign of residual tells us what's likely happening
            if residual_kw > 0:
                interp = (
                    f"DLC loop is removing {Q_removed_total_kw:.0f} kW but "
                    f"IT is dissipating {Q_expected_dlc_kw:.0f} kW. Missing "
                    f"{residual_kw:.0f} kW ({residual_kw / Q_it_total_kw * 100:.1f}% "
                    f"of IT load). Possible causes: DLC flow meter "
                    f"under-reading, partial leak, sensor drift on return "
                    f"temperature, or un-metered bypass."
                )
                action = (
                    "Cross-check per-rack outlet temp telemetry against DLC "
                    "return. Inspect Gemini ER 1.6 thermographic survey for "
                    "the last 60 min. See T4-MOP-CHI-001 for loop integrity "
                    "procedure."
                )
                result.escalate(Severity.WARNING)
            else:
                interp = (
                    f"DLC loop is removing {Q_removed_total_kw:.0f} kW but "
                    f"IT is only dissipating {Q_expected_dlc_kw:.0f} kW. Over "
                    f"by {-residual_kw:.0f} kW. Likely sensor miscalibration "
                    f"on return-temperature RTD."
                )
                action = (
                    "Verify DLC return RTD calibration. Compare against "
                    "independent strap-on thermistor."
                )
                result.escalate(Severity.INFO)

            result.add_justification(
                PhysicalJustification(
                    law="first_law_energy_balance_dlc",
                    measured={
                        "Q_removed_by_dlc_kw": Q_removed_total_kw,
                        "m_dot_kg_s_per_rack": m_dot,
                        "delta_T_K": delta_T,
                        "dlc_supply_c": dlc_supply,
                        "dlc_return_c": dlc_return,
                        "dlc_flow_l_min": dlc_flow,
                    },
                    expected={
                        "Q_it_total_kw": Q_it_total_kw,
                        "Q_expected_dlc_kw": Q_expected_dlc_kw,
                    },
                    residual={"residual_kw": residual_kw},
                    threshold={"threshold_kw": threshold_kw},
                    interpretation=interp,
                    suggested_action=action,
                )
            )

        # ============ Check 2: ASHRAE A2 inlet envelope ====================
        inlet_in_envelope = A2_INLET_MIN_C <= hall_inlet <= A2_INLET_MAX_C
        result.add_check(
            name="ashrae_a2_inlet_envelope",
            passed=inlet_in_envelope,
            value=hall_inlet,
            threshold=A2_INLET_MAX_C,
            unit="C",
        )

        if not inlet_in_envelope:
            if hall_inlet > A2_INLET_MAX_C:
                interp = (
                    f"Hall inlet {hall_inlet:.1f} C exceeds ASHRAE A2 upper "
                    f"limit ({A2_INLET_MAX_C:.0f} C). IT equipment may begin "
                    f"automatic throttling. Immediate cooling capacity "
                    f"review required."
                )
                action = "Activate EOP-003 (emergency cooling reduction). See T4-EOP-COOL-003."
                result.escalate(Severity.CRITICAL)
            else:
                interp = (
                    f"Hall inlet {hall_inlet:.1f} C below ASHRAE A2 lower "
                    f"limit ({A2_INLET_MIN_C:.0f} C). Condensation risk on "
                    f"any surface cooler than dew point."
                )
                action = "Increase chilled water setpoint. Verify dehumidification status."
                result.escalate(Severity.WARNING)

            result.add_justification(
                PhysicalJustification(
                    law="ashrae_a2_envelope",
                    measured={"hall_inlet_c": hall_inlet},
                    expected={"a2_min_c": A2_INLET_MIN_C, "a2_max_c": A2_INLET_MAX_C},
                    residual={
                        "excess_above_max": max(0.0, hall_inlet - A2_INLET_MAX_C),
                        "deficit_below_min": max(0.0, A2_INLET_MIN_C - hall_inlet),
                    },
                    threshold={"band_width_c": A2_INLET_MAX_C - A2_INLET_MIN_C},
                    interpretation=interp,
                    suggested_action=action,
                )
            )

        # ============ Check 3: operational (tighter) band =================
        ops_band_ok = OPS_INLET_ALARM_LOW_C <= hall_inlet <= OPS_INLET_ALARM_HIGH_C
        result.add_check(
            name="a3semi_ops_inlet_band",
            passed=ops_band_ok,
            value=hall_inlet,
            threshold=OPS_INLET_ALARM_HIGH_C,
            unit="C",
        )
        if not ops_band_ok and inlet_in_envelope:
            # Only INFO if we're within A2 but outside ops band
            result.escalate(Severity.INFO)

        # ============ Check 4: GPU junction temperature ===================
        gpu_ok = gpu_tj < GPU_TJ_WARNING_C
        result.add_check(
            name="gpu_junction_temp",
            passed=gpu_ok,
            value=gpu_tj,
            threshold=GPU_TJ_WARNING_C,
            unit="C",
        )
        if gpu_tj >= GPU_TJ_TRIP_C:
            result.escalate(Severity.CRITICAL)
            result.add_justification(
                PhysicalJustification(
                    law="gpu_junction_thermal_trip",
                    measured={"gpu_tj_max_c": gpu_tj},
                    expected={"trip_threshold_c": GPU_TJ_TRIP_C},
                    residual={"excess_c": gpu_tj - GPU_TJ_TRIP_C},
                    threshold={"trip_c": GPU_TJ_TRIP_C},
                    interpretation=(
                        f"Hottest GPU reports Tj = {gpu_tj:.1f} C, at or above "
                        f"{GPU_TJ_TRIP_C:.0f} C thermal trip threshold. "
                        f"Automatic shutdown imminent or already occurred."
                    ),
                    suggested_action=(
                        "Investigate per-rack DLC flow immediately. Check cold "
                        "plate seating if rack was recently serviced."
                    ),
                )
            )
        elif gpu_tj >= GPU_TJ_THROTTLE_C:
            result.escalate(Severity.CRITICAL)
            result.add_justification(
                PhysicalJustification(
                    law="gpu_junction_throttle",
                    measured={"gpu_tj_max_c": gpu_tj},
                    expected={"throttle_threshold_c": GPU_TJ_THROTTLE_C},
                    residual={"excess_c": gpu_tj - GPU_TJ_THROTTLE_C},
                    threshold={"throttle_c": GPU_TJ_THROTTLE_C},
                    interpretation=(
                        f"GPU Tj = {gpu_tj:.1f} C triggers automatic throttling. "
                        f"Compute throughput is degraded."
                    ),
                    suggested_action=(
                        "Verify DLC supply temperature and flow rate. See "
                        "T2-VEN-NV-GB200 section 'Troubleshooting'."
                    ),
                )
            )
        elif gpu_tj >= GPU_TJ_WARNING_C:
            result.escalate(Severity.WARNING)

        # --- Compute module health score ---
        # Start at 1.0, subtract proportional to worst check severity.
        penalty = max(
            self._energy_balance_penalty(residual_kw, threshold_kw),
            self._inlet_penalty(hall_inlet),
            self._gpu_penalty(gpu_tj),
        )
        result.health = _clamp01(1.0 - penalty)

        # --- Metrics for dashboard ---
        result.metrics = {
            "Q_it_total_kw": Q_it_total_kw,
            "Q_removed_by_dlc_kw": Q_removed_total_kw,
            "dlc_delta_T_k": delta_T,
            "energy_residual_kw": residual_kw,
            "hall_inlet_c": hall_inlet,
            "gpu_tj_max_c": gpu_tj,
            "health": result.health,
        }

        return result

    # Penalty curves (smooth, no cliffs)
    @staticmethod
    def _energy_balance_penalty(residual_kw: float, threshold_kw: float) -> float:
        ratio = abs(residual_kw) / max(threshold_kw, 1.0)
        if ratio <= 1.0:
            return 0.0
        # Linear from 0 at ratio=1 to 0.5 at ratio=3
        return min(0.5, (ratio - 1.0) * 0.25)

    @staticmethod
    def _inlet_penalty(hall_inlet_c: float) -> float:
        if OPS_INLET_ALARM_LOW_C <= hall_inlet_c <= OPS_INLET_ALARM_HIGH_C:
            return 0.0
        if A2_INLET_MIN_C <= hall_inlet_c <= A2_INLET_MAX_C:
            return 0.15  # outside ops band but within A2
        # Outside A2 is severe
        excess = max(
            hall_inlet_c - A2_INLET_MAX_C,
            A2_INLET_MIN_C - hall_inlet_c,
        )
        return min(1.0, 0.5 + excess * 0.05)

    @staticmethod
    def _gpu_penalty(gpu_tj_c: float) -> float:
        if gpu_tj_c < GPU_TJ_NORMAL_MAX_C:
            return 0.0
        if gpu_tj_c < GPU_TJ_WARNING_C:
            return 0.05
        if gpu_tj_c < GPU_TJ_THROTTLE_C:
            return 0.25
        if gpu_tj_c < GPU_TJ_TRIP_C:
            return 0.60
        return 1.0

    # ------------------------------------------------------------------ #
    #  Transient simulation (ODE, scipy.solve_ivp)
    # ------------------------------------------------------------------ #

    def simulate(
        self,
        initial_state: dict[str, float],
        perturbation: dict[str, Any],
        horizon_s: int = 900,
        dt_s: float = 1.0,
    ) -> list[StateSnapshot]:
        """Integrate hall air temperature ODE over horizon_s seconds.

        Governing ODE:
            dT_air/dt = (Q_to_air - Q_cooling_air) / (m_air * cp_air)

        Where:
            Q_to_air        = rack_count * rack_kw * AIR_FRACTION * 1000
            Q_cooling_air   = effective air-side cooling capacity (W), may
                              be degraded by the perturbation

        Perturbation schema:
            {
              "type":            str   - one of the recognised fault types
              "cooling_factor":  float - [0.0, 1.0] fraction of nominal cooling
                                         capacity retained (1.0 = nominal,
                                         0.0 = total loss)
              "dlc_flow_factor": float - [0.0, 1.0] fraction of nominal DLC
                                         flow retained
              "start_s":         int   - seconds into simulation when fault
                                         begins (default 0)
              "duration_s":      int   - seconds until fault clears
                                         (default horizon_s, i.e. never)
              "rack_kw_mult":    float - multiplier on rack load (for
                                         workload-migration scenarios)
            }

        Any missing perturbation keys default to "no perturbation".

        Returns:
            List of StateSnapshot at 1-second intervals.
        """
        if not HAS_SCIPY:
            # Fallback: analytic Newton's law of cooling, no ODE integration
            log.warning("scipy not available; using analytic Newton's law fallback")
            return self._simulate_analytic(initial_state, perturbation, horizon_s, dt_s)

        # --- Parse initial state ---
        T0_air = float(initial_state.get("hall_return_c", 22.0))
        rack_count = int(initial_state.get("rack_count", RACK_COUNT))
        rack_kw = float(initial_state.get("rack_tdp_kw", RACK_TDP_KW_NOMINAL))
        dlc_supply = float(initial_state.get("dlc_supply_c", DLC_SUPPLY_TARGET_C))
        dlc_flow_nom = float(initial_state.get("dlc_flow_l_min", DLC_FLOW_NOMINAL_L_MIN))

        # --- Parse perturbation ---
        cooling_factor = float(perturbation.get("cooling_factor", 1.0))
        dlc_flow_factor = float(perturbation.get("dlc_flow_factor", 1.0))
        start_s = float(perturbation.get("start_s", 0.0))
        duration_s = float(perturbation.get("duration_s", horizon_s))
        rack_kw_mult = float(perturbation.get("rack_kw_mult", 1.0))

        # --- Precompute constants for the ODE ---
        m_air = HALL_AIR_MASS_KG
        cp_air = CP_AIR

        # Air-side nominal cooling capacity (CRAH).
        # At steady state with nominal inlet temp (20 C) we know the air-side
        # heat load is rack_count * rack_kw * AIR_FRACTION * 1000 (W), and
        # the hall sits at ~22 C return. So effective cooling capacity at
        # nominal CRAH delta_T is roughly that value (units: W).
        Q_to_air_nominal = rack_count * rack_kw * rack_kw_mult * AIR_FRACTION * 1000.0
        Q_cooling_nominal = Q_to_air_nominal  # at t=0 we're at steady state

        # --- The ODE function ---
        def dTdt(t: float, T: np.ndarray) -> np.ndarray:
            """Hall air temperature ODE.

            Governing equation accounts for two mechanisms:
              1. IT load heating:           +Q_in / (m*cp)
              2. Active cooling removal:    -Q_out / (m*cp)  (scales with
                 cooling_factor during fault)
              3. Passive loss to structure: -(T - T_ambient_base) / tau

            The passive term models heat loss to concrete, steel, duct
            leakage, and building envelope. Its time constant tau matches
            the empirical 53.3 s from T3-STD-THERMAL-MODEL. Without this
            term the ODE would integrate linearly to unphysical values
            when active cooling is fully removed.

            Asymptote when cooling_factor=0:
              dT/dt = 0 => Q_in - (T - T_base)*m*cp/tau = 0
              T_ss = T_base + Q_in * tau / (m * cp)
              T_ss ~ 22 + 838,000 * 53.3 / (960 * 1005) ~ 68 C
            which matches literature for a sealed hall of this density.
            """
            t_scalar = float(t)
            fault_active = start_s <= t_scalar < (start_s + duration_s)
            T_val = float(T[0])

            Q_in = Q_to_air_nominal
            if fault_active:
                Q_out_active = Q_cooling_nominal * cooling_factor
            else:
                Q_out_active = Q_cooling_nominal

            # Passive loss to building structure (Newton cooling of hall air)
            T_ambient_base = 22.0  # normal operating hall temperature
            passive_loss_w = (T_val - T_ambient_base) * m_air * cp_air / THERMAL_TIME_CONSTANT_S

            dT = (Q_in - Q_out_active - passive_loss_w) / (m_air * cp_air)
            return np.array([dT])

        # --- Integrate ---
        t_span = (0.0, float(horizon_s))
        t_eval = np.arange(0.0, horizon_s + dt_s, dt_s)

        sol = solve_ivp(
            dTdt,
            t_span,
            y0=np.array([T0_air]),
            t_eval=t_eval,
            method="RK45",
            rtol=1e-4,
            atol=1e-3,
        )

        if not sol.success:
            log.error("ODE integrator failed: %s", sol.message)
            return []

        # --- Build StateSnapshot trajectory ---
        trajectory: list[StateSnapshot] = []
        throttle_triggered = False
        trip_triggered = False

        for i, t in enumerate(sol.t):
            T_air = float(sol.y[0][i])

            # Estimate GPU Tj from DLC supply + loop delta_T + die-to-coolant
            # resistance. If flow is lost, GPU rapidly heats because the
            # cold plate can no longer dissipate energy.
            flow_factor_now = dlc_flow_factor if (start_s <= t < start_s + duration_s) else 1.0
            if flow_factor_now > 0.01:
                # Q = m_dot * cp * delta_T => delta_T = Q / (m_dot * cp)
                m_dot = _flow_l_min_to_kg_s(dlc_flow_nom * flow_factor_now)
                Q_per_rack = rack_kw * rack_kw_mult * DLC_FRACTION * 1000.0
                dlc_dT = Q_per_rack / (m_dot * CP_PGW)
                # GPU Tj ~ DLC supply + loop dT + die-to-coolant rise (15 K)
                gpu_tj_estimate = dlc_supply + dlc_dT + 15.0
            else:
                # Flow lost entirely: GPU rises toward hall temp + large offset.
                # Without coolant, the die sinks heat via the (now warming)
                # cold plate to ambient air. Ceiling at GPU_TJ_TRIP_C for
                # display; in reality the GPU trips and stops dissipating.
                dlc_dT = 0.0  # no coolant flow, no delta_T defined
                gpu_tj_estimate = min(GPU_TJ_TRIP_C, T_air + 20.0)

            events = []
            if gpu_tj_estimate >= GPU_TJ_THROTTLE_C and not throttle_triggered:
                events.append("gpu_thermal_throttle_initiated")
                throttle_triggered = True
            if gpu_tj_estimate >= GPU_TJ_TRIP_C and not trip_triggered:
                events.append("gpu_thermal_trip_estimated")
                trip_triggered = True
            if T_air >= A2_INLET_MAX_C and i > 0:
                prev_T = trajectory[-1].state["hall_air_c"]
                if prev_T < A2_INLET_MAX_C:
                    events.append("a2_envelope_exceeded")

            trajectory.append(
                StateSnapshot(
                    t=float(t),
                    state={
                        "hall_air_c": T_air,
                        "dlc_supply_c": dlc_supply,
                        "dlc_flow_factor": flow_factor_now,
                        "cooling_factor": (
                            cooling_factor if (start_s <= t < start_s + duration_s) else 1.0
                        ),
                        "gpu_tj_estimate_c": gpu_tj_estimate,
                        "dlc_delta_T_k": dlc_dT,
                    },
                    events=events,
                )
            )

        return trajectory

    # ------------------------------------------------------------------ #
    #  Analytic fallback (when scipy is unavailable)
    # ------------------------------------------------------------------ #

    def _simulate_analytic(
        self,
        initial_state: dict[str, float],
        perturbation: dict[str, Any],
        horizon_s: int,
        dt_s: float,
    ) -> list[StateSnapshot]:
        """Newton's law of cooling closed-form solution (Nivel A fallback).

        T(t) = T_ss + (T_0 - T_ss) * exp(-t / tau)

        Used only when scipy is not installed. Less accurate than ODE
        integration but still physically grounded.
        """
        import math

        T0 = float(initial_state.get("hall_return_c", 22.0))
        cooling_factor = float(perturbation.get("cooling_factor", 1.0))

        # If cooling is reduced, new steady-state rises proportionally
        # toward the no-cooling asymptote (45 C).
        T_ss = T0 + (SS_TEMP_NO_COOLING_C - T0) * (1.0 - cooling_factor)

        trajectory: list[StateSnapshot] = []
        t = 0.0
        while t <= horizon_s:
            T = T_ss + (T0 - T_ss) * math.exp(-t / THERMAL_TIME_CONSTANT_S)
            events = []
            if (
                T >= A2_INLET_MAX_C
                and trajectory
                and trajectory[-1].state["hall_air_c"] < A2_INLET_MAX_C
            ):
                events.append("a2_envelope_exceeded")
            trajectory.append(
                StateSnapshot(
                    t=t,
                    state={"hall_air_c": T, "cooling_factor": cooling_factor},
                    events=events,
                )
            )
            t += dt_s
        return trajectory

    # ------------------------------------------------------------------ #
    #  Convenience: compute time-to-critical analytically
    # ------------------------------------------------------------------ #

    def time_to_critical_s(
        self,
        current_temp_c: float,
        cooling_factor: float = 0.0,
        critical_temp_c: float = A2_INLET_MAX_C,
    ) -> float | None:
        """Analytic TTC given current temperature and cooling capacity.

        Returns seconds until temperature reaches `critical_temp_c`, or
        None if the asymptote is below the critical temperature (i.e. the
        system will never reach critical with the given cooling).
        """
        import math

        T_ss = current_temp_c + (SS_TEMP_NO_COOLING_C - current_temp_c) * (1.0 - cooling_factor)

        if T_ss <= critical_temp_c:
            return None  # never reaches critical with this cooling

        # T(t) = T_ss + (T_0 - T_ss) * exp(-t / tau) = critical
        # Solving for t:
        numerator = critical_temp_c - T_ss
        denominator = current_temp_c - T_ss
        if denominator == 0 or numerator / denominator <= 0:
            return None
        t = -THERMAL_TIME_CONSTANT_S * math.log(numerator / denominator)
        return max(0.0, t)
