"""
DC-EPMS PRO - Physics Engine: Electrical Module (Elec Room)
============================================================
Validates and simulates the electrical distribution plant: utility
transformer, UPS Galaxy VX (A and B), and downstream RPP / PDU losses.

Governing physics
-----------------
1. Joule's law (I^2 * R losses):

        P_loss = I^2 * R

   Applied to:
       - Transformer copper (winding) losses (fixed at rated load)
       - Transformer core (iron) losses (fixed regardless of load)
       - Conductor losses in busway and feeders

2. Transformer overall loss model:

        P_loss(t) = P_no_load + P_full_load * (S(t)/S_rated)^2

   Where S(t)/S_rated is the loading factor. This is the standard
   ANSI C57.12 curve: copper losses scale with load squared, iron
   losses are roughly constant.

3. UPS efficiency curves (empirical from Schneider Galaxy VX datasheet):

        eta(load) = eta_max * f(load_fraction)

   Where f(x) is bell-shaped with peak around 30-70% load for online
   double-conversion mode. Below 10% or above 95% load, efficiency
   drops notably.

4. Battery voltage droop during discharge (Peukert relationship):

        V_terminal(SOC) = V_nominal * (SOC^0.1)  for SOC in [0.2, 1.0]

   Simplified curve; sufficient for a 15-min simulation window.

References
----------
  - T2-VEN-SE-UPS-GVX          (Galaxy VX operation manual)
  - T2-VEN-SE-WP122            (Schneider WP122 critical power)
  - T4-MOP-UPS-001             (UPS quarterly PM)
  - IEEE 1184 / 1188           (UPS battery practices)
  - ANSI C57.12                (Transformer loss standard)
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

log = logging.getLogger("dc-epms.physics.electrical")


# ---------------------------------------------------------------------------
#  Design constants for A3-Alpha
# ---------------------------------------------------------------------------

# --- Utility main transformer (27 kV / 480 V, per-side) ---
# Two transformers in 2N (one per utility side)
XFMR_RATED_KVA = 2_500.0  # 2.5 MVA per transformer
XFMR_NO_LOAD_LOSS_KW = 3.5  # iron losses (present always)
XFMR_FULL_LOAD_LOSS_KW = 22.0  # copper losses at 100% load
XFMR_AMBIENT_NOMINAL_C = 25.0
XFMR_WINDING_MAX_C = 130.0  # IEEE C57.12 hottest-spot limit for 65C rise
XFMR_TOP_OIL_MAX_C = 95.0

# --- UPS Galaxy VX 750 kVA ---
UPS_RATED_KVA = 750.0
UPS_RATED_KW = 600.0  # at PF=0.8 per legacy, Galaxy VX supports unity PF
UPS_ETA_MAX = 0.97  # eConversion mode peak
UPS_ETA_DOUBLE_CONV_MAX = 0.96
UPS_LOW_LOAD_ETA_FLOOR = 0.88  # at ~5% load

# --- Battery string (VRLA, 240 cells, 480 VDC) ---
BATT_NOMINAL_VDC = 540.0  # float voltage
BATT_CELLS = 240
BATT_CELL_FLOAT_V = 2.25
BATT_CELL_DISCHARGE_END_V = 1.75  # cutoff
BATT_CAPACITY_AH = 250.0  # 60-cell jar, rated 10-hr
BATT_RUNTIME_NOMINAL_MIN = 15.0  # a3semi spec at full load
BATT_RUNTIME_FULL_LOAD_MIN = 12.0  # realistic VRLA end-of-life


# ---------------------------------------------------------------------------
#  Helper functions
# ---------------------------------------------------------------------------


def _ups_efficiency(load_fraction: float, mode: str = "online") -> float:
    """Compute UPS efficiency for a given load fraction.

    Based on published Galaxy VX curves:
      - Peak ~97% at 30-80% load in eConversion
      - ~96% peak in online double-conversion
      - Drops to ~88% at 5% load (parasitic + control losses dominate)
      - Drops to ~94% at 100% load (conductor + switching losses rise)

    Args:
        load_fraction: [0.0, 1.2] actual load / rated load
        mode: "online" (double-conversion) or "econversion"

    Returns:
        Efficiency in [0, 1].
    """
    lf = max(0.0, min(1.2, load_fraction))
    eta_peak = UPS_ETA_MAX if mode == "econversion" else UPS_ETA_DOUBLE_CONV_MAX

    if lf < 0.05:
        # Near-zero load; only control-circuit parasitic draw
        return UPS_LOW_LOAD_ETA_FLOOR

    if lf < 0.3:
        # Linear ramp from floor to peak between 5% and 30%
        return UPS_LOW_LOAD_ETA_FLOOR + (eta_peak - UPS_LOW_LOAD_ETA_FLOOR) * ((lf - 0.05) / 0.25)

    if lf < 0.9:
        # Flat near peak
        return eta_peak

    # Above 90% load, slight rolloff
    return eta_peak - 0.02 * (lf - 0.9) / 0.1


def _transformer_losses_kw(load_kva: float) -> float:
    """Transformer total loss per ANSI C57.12 loading model.

    P_loss(t) = P_no_load + P_full_load * (S/S_rated)^2
    """
    loading = load_kva / max(XFMR_RATED_KVA, 0.001)
    return XFMR_NO_LOAD_LOSS_KW + XFMR_FULL_LOAD_LOSS_KW * (loading**2)


def _battery_voltage_from_soc(soc: float) -> float:
    """Approximate battery DC bus voltage as function of state-of-charge.

    Uses simplified Peukert-style curve V(SOC) = V_nom * SOC^0.1 for
    SOC in [0.15, 1.0]. Below 0.15 voltage collapses fast.
    """
    soc = max(0.0, min(1.0, soc))
    if soc > 0.15:
        return BATT_NOMINAL_VDC * (soc**0.10)
    else:
        # Collapse toward cutoff
        return BATT_CELLS * BATT_CELL_DISCHARGE_END_V * (soc / 0.15)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ---------------------------------------------------------------------------
#  ElectricalModule
# ---------------------------------------------------------------------------


class ElectricalModule(PhysicsModule):
    """Validator + simulator for the electrical plant.

    Expected measurement schema (validate):
        {
          "utility_kw":            float,   # power drawn from utility
          "facility_it_kw":        float,   # downstream IT load
          "ups_load_kw":           float,   # UPS output
          "ups_mode":              str,     # "online"|"econversion"|"bypass"
          "ups_input_kw":          float,   # UPS input (measured)
          "xfmr_load_kva":         float,   # transformer loading
          "xfmr_top_oil_c":        float,   # transformer top oil temp
          "xfmr_winding_c":        float,   # hottest-spot winding temp
          "battery_soc":           float,   # [0, 1]
          "battery_vdc":           float,   # measured DC bus voltage
          "battery_on_load":       bool,    # True if on battery
        }
    """

    module_name = "electrical"

    # ------------------------------------------------------------------ #
    #  Steady-state validation
    # ------------------------------------------------------------------ #

    def validate(
        self,
        measurements: dict[str, Any],
    ) -> ValidationResult:
        r = ValidationResult(module=self.module_name)

        utility_kw = float(measurements.get("utility_kw", 17_400.0))
        float(measurements.get("facility_it_kw", 16_756.0))
        ups_load_kw = float(measurements.get("ups_load_kw", 16_756.0))
        ups_mode = str(measurements.get("ups_mode", "online"))
        ups_input_kw = float(measurements.get("ups_input_kw", 17_450.0))
        xfmr_load_kva = float(measurements.get("xfmr_load_kva", 18_500.0))
        xfmr_top_oil = float(measurements.get("xfmr_top_oil_c", 65.0))
        xfmr_winding = float(measurements.get("xfmr_winding_c", 85.0))
        batt_soc = float(measurements.get("battery_soc", 1.0))
        batt_vdc_meas = float(measurements.get("battery_vdc", BATT_NOMINAL_VDC))
        on_batt = bool(measurements.get("battery_on_load", False))

        # ============ Check 1: UPS efficiency curve =====================
        load_fraction = ups_load_kw / UPS_RATED_KW
        eta_expected = _ups_efficiency(load_fraction, mode=ups_mode)
        expected_input_kw = ups_load_kw / max(eta_expected, 0.01)

        # Measured efficiency
        if ups_input_kw > 0:
            eta_measured = ups_load_kw / ups_input_kw
        else:
            eta_measured = 0.0

        eff_residual = eta_measured - eta_expected
        eff_threshold = 0.015  # 1.5 pp
        eff_ok = abs(eff_residual) <= eff_threshold
        r.add_check(
            name="ups_efficiency_vs_curve",
            passed=eff_ok,
            value=eff_residual,
            threshold=eff_threshold,
            unit="fraction",
        )
        if not eff_ok:
            if eff_residual < 0:
                interp = (
                    f"UPS efficiency {eta_measured * 100:.2f}% below expected "
                    f"{eta_expected * 100:.2f}% at {load_fraction * 100:.0f}% "
                    f"load. Excess dissipation "
                    f"{(ups_input_kw - expected_input_kw):.1f} kW; typically "
                    f"indicates cooling-fan degradation, capacitor ESR rise, "
                    f"or rectifier imbalance."
                )
            else:
                interp = (
                    f"UPS efficiency {eta_measured * 100:.2f}% above expected "
                    f"{eta_expected * 100:.2f}% - likely meter-calibration "
                    f"issue rather than genuine improvement."
                )
            action = (
                "Verify input and output kW meter calibration. See "
                "T4-MOP-UPS-001 section 'Thermographic scan of internal "
                "bus'."
            )
            r.escalate(Severity.INFO)
            r.add_justification(
                PhysicalJustification(
                    law="ups_efficiency_curve",
                    measured={
                        "ups_load_kw": ups_load_kw,
                        "ups_input_kw": ups_input_kw,
                        "eta_measured": eta_measured,
                        "load_fraction": load_fraction,
                        "ups_mode": ups_mode,
                    },
                    expected={"eta_expected": eta_expected},
                    residual={"residual_fraction": eff_residual},
                    threshold={"threshold_fraction": eff_threshold},
                    interpretation=interp,
                    suggested_action=action,
                )
            )

        # ============ Check 2: Transformer losses (Joule + iron) ========
        xfmr_loss_expected = _transformer_losses_kw(xfmr_load_kva)
        # Expected utility draw = sum of downstream + losses
        # (simplified: single xfmr model; production uses 2 xfmrs parallel)
        # Check transformer thermal: winding temp should track load loss
        xfmr_load_frac = xfmr_load_kva / XFMR_RATED_KVA
        # Simplified thermal model: steady-state winding rise scales with loss
        # Expected temp = ambient + (no_load_rise) + (full_load_rise) * (load_frac)^2
        ambient = XFMR_AMBIENT_NOMINAL_C
        expected_winding = ambient + 40.0 + 65.0 * (xfmr_load_frac**2)
        winding_residual = xfmr_winding - expected_winding
        winding_threshold = 12.0  # K
        winding_ok = abs(winding_residual) <= winding_threshold
        r.add_check(
            name="transformer_winding_thermal_model",
            passed=winding_ok,
            value=winding_residual,
            threshold=winding_threshold,
            unit="C",
        )
        if not winding_ok and winding_residual > 0:
            interp = (
                f"Transformer winding {xfmr_winding:.1f} C exceeds thermal-"
                f"model expectation {expected_winding:.1f} C by "
                f"{winding_residual:.1f} K. Possible oil-cooling degradation "
                f"(fans, pumps), harmonic distortion, or load imbalance."
            )
            if xfmr_winding >= XFMR_WINDING_MAX_C:
                r.escalate(Severity.CRITICAL)
                interp = (
                    "CRITICAL: "
                    + interp
                    + (
                        f" Winding at or above {XFMR_WINDING_MAX_C:.0f} C IEEE "
                        f"C57.12 hottest-spot limit; insulation aging "
                        f"accelerates 2x per 6-8 K above design."
                    )
                )
            else:
                r.escalate(Severity.WARNING)
            r.add_justification(
                PhysicalJustification(
                    law="transformer_thermal_ieee_c57_12",
                    measured={
                        "xfmr_winding_c": xfmr_winding,
                        "xfmr_top_oil_c": xfmr_top_oil,
                        "xfmr_load_kva": xfmr_load_kva,
                        "xfmr_load_fraction": xfmr_load_frac,
                    },
                    expected={
                        "winding_expected_c": expected_winding,
                        "winding_max_c": XFMR_WINDING_MAX_C,
                        "losses_kw": xfmr_loss_expected,
                    },
                    residual={"residual_c": winding_residual},
                    threshold={"threshold_c": winding_threshold},
                    interpretation=interp,
                    suggested_action=(
                        "Verify transformer cooling fans operational. Check "
                        "harmonic content with power-quality analyzer. Review "
                        "load balance across phases."
                    ),
                )
            )

        # ============ Check 3: Battery voltage vs SOC curve =============
        batt_vdc_expected = _battery_voltage_from_soc(batt_soc)
        batt_v_residual = batt_vdc_meas - batt_vdc_expected
        batt_v_threshold = 8.0  # V
        batt_v_ok = abs(batt_v_residual) <= batt_v_threshold
        r.add_check(
            name="battery_voltage_soc_consistency",
            passed=batt_v_ok,
            value=batt_v_residual,
            threshold=batt_v_threshold,
            unit="V",
        )
        if not batt_v_ok:
            interp = (
                f"Battery DC bus {batt_vdc_meas:.1f} V at reported SOC "
                f"{batt_soc * 100:.0f}%, expected {batt_vdc_expected:.1f} V. "
                f"Residual {batt_v_residual:+.1f} V indicates SOC estimate "
                f"drift or a failing cell in one string."
            )
            action = (
                "Schedule individual cell voltage measurement per "
                "T4-MOP-UPS-001 section 'Battery maintenance'. Expected "
                "float voltage per cell: 2.25 V +/- 0.03 V."
            )
            r.escalate(Severity.WARNING)
            r.add_justification(
                PhysicalJustification(
                    law="battery_voltage_soc",
                    measured={
                        "battery_vdc": batt_vdc_meas,
                        "battery_soc": batt_soc,
                    },
                    expected={"battery_vdc_expected": batt_vdc_expected},
                    residual={"residual_v": batt_v_residual},
                    threshold={"threshold_v": batt_v_threshold},
                    interpretation=interp,
                    suggested_action=action,
                )
            )

        # ============ Check 4: On-battery urgency =======================
        if on_batt:
            # Estimate remaining runtime from SOC (linear is a fine approximation
            # above SOC=0.2)
            runtime_est_min = BATT_RUNTIME_FULL_LOAD_MIN * batt_soc
            r.add_check(
                name="on_battery_runtime_remaining",
                passed=runtime_est_min > 5.0,
                value=runtime_est_min,
                threshold=5.0,
                unit="min",
            )
            if runtime_est_min < 5.0:
                r.escalate(Severity.CRITICAL)
                r.add_justification(
                    PhysicalJustification(
                        law="battery_runtime_remaining",
                        measured={
                            "battery_soc": batt_soc,
                            "runtime_est_min": runtime_est_min,
                        },
                        expected={"minimum_safe_min": 5.0},
                        residual={"deficit_min": 5.0 - runtime_est_min},
                        threshold={"threshold_min": 5.0},
                        interpretation=(
                            f"On battery with only {runtime_est_min:.1f} min "
                            f"of runtime remaining. Utility or generator "
                            f"restoration required in under 5 min or initiate "
                            f"orderly IT shutdown."
                        ),
                        suggested_action=(
                            "Verify generator start status. If generator not "
                            "yet online, activate EOP per T1-SAF-EPO-005. "
                            "Begin IT workload migration sequence."
                        ),
                    )
                )
            elif runtime_est_min < 10.0:
                r.escalate(Severity.WARNING)

        # --- Health score ---
        penalty = max(
            0.0 if eff_ok else 0.10,
            0.0 if winding_ok else (0.6 if xfmr_winding >= XFMR_WINDING_MAX_C else 0.25),
            0.0 if batt_v_ok else 0.20,
            (0.0 if (not on_batt or batt_soc > 0.5) else (0.7 if batt_soc < 0.2 else 0.3)),
        )
        r.health = _clamp01(1.0 - penalty)

        r.metrics = {
            "utility_kw": utility_kw,
            "ups_load_kw": ups_load_kw,
            "ups_input_kw": ups_input_kw,
            "ups_efficiency_measured": eta_measured,
            "ups_efficiency_expected": eta_expected,
            "ups_load_fraction": load_fraction,
            "xfmr_load_kva": xfmr_load_kva,
            "xfmr_load_fraction": xfmr_load_frac,
            "xfmr_winding_c": xfmr_winding,
            "xfmr_losses_kw": xfmr_loss_expected,
            "battery_soc": batt_soc,
            "battery_vdc": batt_vdc_meas,
            "battery_on_load": on_batt,
            "health": r.health,
        }
        return r

    # ------------------------------------------------------------------ #
    #  Transient simulation: utility-loss scenario
    # ------------------------------------------------------------------ #

    def simulate(
        self,
        initial_state: dict[str, float],
        perturbation: dict[str, Any],
        horizon_s: int = 900,
        dt_s: float = 1.0,
    ) -> list[StateSnapshot]:
        """Simulate battery discharge transient during utility loss.

        Governing ODE (state-of-charge):
            dSOC/dt = -I_load / (Q_capacity_as)

        Where I_load = P_load / V_bus.

        Perturbation schema:
            {
              "type": str,
              "utility_fail":      bool   - True: loss of utility at start_s
              "generator_start_s": float  - when generator takes over
                                            (if None: never)
              "start_s":           float
              "duration_s":        float
              "load_kw":           float  - facility load during event
            }
        """
        soc0 = float(initial_state.get("battery_soc", 1.0))
        load_kw = float(perturbation.get("load_kw", initial_state.get("ups_load_kw", 16_756.0)))
        utility_fail = bool(perturbation.get("utility_fail", True))
        start_s = float(perturbation.get("start_s", 0.0))
        gen_start_s = perturbation.get("generator_start_s")

        # Battery capacity in ampere-seconds at nominal voltage:
        # Q_as = C_Ah * 3600
        # For runtime calculation we use an effective drain rate per unit SOC.
        # At full load and 1.0 SOC we know runtime ~= 12 min = 720 s.
        # So dSOC/dt = -1/720 at full load in SOC-per-second.
        # More generally, drain rate ~= (load / rated_load) / runtime_at_rated

        rated_load = UPS_RATED_KW
        load_ratio = load_kw / rated_load
        base_drain_per_s = 1.0 / (BATT_RUNTIME_FULL_LOAD_MIN * 60.0)
        drain_per_s = base_drain_per_s * load_ratio

        def dSOCdt(t, soc):  # noqa: N802 - ODE derivative dSOC/dt
            t_s = float(t)
            on_battery = False
            if (
                utility_fail
                and t_s >= start_s
                and (gen_start_s is None or t_s < float(gen_start_s))
            ):
                on_battery = True
            if not on_battery:
                # Utility/generator carrying load: recharge at 5C_10 rate
                # (i.e. full charge in 5 hours)
                recharge_per_s = 1.0 / (5 * 3600)
                rate = recharge_per_s if float(soc[0]) < 1.0 else 0.0
            else:
                rate = -drain_per_s
            return np.array([rate]) if HAS_SCIPY else [rate]

        if HAS_SCIPY:
            t_eval = np.arange(0.0, horizon_s + dt_s, dt_s)
            sol = solve_ivp(
                dSOCdt,
                (0.0, float(horizon_s)),
                y0=np.array([soc0]),
                t_eval=t_eval,
                method="RK45",
                rtol=1e-5,
                atol=1e-5,
            )
            if not sol.success:
                log.error("electrical ODE failed: %s", sol.message)
                return []
            ts = sol.t
            socs = sol.y[0]
        else:
            # Pure Euler fallback
            ts_list, soc_list = [], []
            soc = soc0
            t = 0.0
            while t <= horizon_s:
                rate = dSOCdt(t, [soc])[0]
                soc = max(0.0, min(1.0, soc + rate * dt_s))
                ts_list.append(t)
                soc_list.append(soc)
                t += dt_s
            ts, socs = ts_list, soc_list

        trajectory: list[StateSnapshot] = []
        depletion_event = False
        low_battery_event = False

        for i, t in enumerate(ts):
            soc = float(socs[i])
            t_s = float(t)
            on_batt = (
                utility_fail
                and t_s >= start_s
                and (gen_start_s is None or t_s < float(gen_start_s))
            )
            vdc = _battery_voltage_from_soc(soc)

            events = []
            if soc < 0.3 and not low_battery_event:
                events.append("battery_low_warning")
                low_battery_event = True
            if soc < 0.15 and not depletion_event:
                events.append("battery_depletion_imminent")
                depletion_event = True
            if gen_start_s is not None and abs(t_s - float(gen_start_s)) < dt_s / 2:
                events.append("generator_online")

            trajectory.append(
                StateSnapshot(
                    t=t_s,
                    state={
                        "battery_soc": soc,
                        "battery_vdc": vdc,
                        "on_battery": on_batt,
                        # Use -1.0 as sentinel for "not applicable" (battery not
                        # discharging). JSON does not permit Infinity per RFC 8259,
                        # so we cannot return float('inf') here.
                        "runtime_remaining_min": (
                            soc / base_drain_per_s / 60.0 / load_ratio
                            if (on_batt and load_ratio > 0)
                            else -1.0
                        ),
                        "load_kw": load_kw,
                    },
                    events=events,
                )
            )

        return trajectory
