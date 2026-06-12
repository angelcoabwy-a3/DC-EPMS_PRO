"""
DC-EPMS PRO - Physics Engine: Heat Rejection Module (Exterior)
===============================================================
Validates and simulates the facility heat-rejection subsystem: chillers
(York YZ), cooling-tower/condenser loop, and the psychrometric state of
the outdoor air driving heat-rejection capacity.

Governing physics
-----------------
1. Psychrometric relations (ASHRAE Handbook Fundamentals, Ch. 1):

     - Saturation vapor pressure:  Magnus-Tetens approximation
           P_ws(T) = 611.2 * exp(17.625 * T / (T + 243.04))     [Pa]
     - Humidity ratio:             W = 0.622 * P_w / (P - P_w)   [kg/kg]
     - Dew point (inverse Magnus): from partial pressure P_w
     - Wet-bulb temperature:       iterative solution of psychrometric
                                   energy balance
                                   (h(T_db, W) = h(T_wb, W_sat(T_wb)))

2. Chiller coefficient of performance (COP):

        COP = Q_evap / P_compressor

   For York YZ magnetic-bearing centrifugal chillers, COP is a function
   of:
     - Part-load ratio (PLR = Q_actual / Q_rated)
     - Condenser entering water temperature (ECWT), tracks wet-bulb
     - Chilled water setpoint (LCHWT)

   Simplified bi-cubic curve (York datasheet approximation):

        COP(PLR, ECWT) = COP_nominal * f_plr(PLR) * f_ecwt(ECWT)

3. Cooling tower approach & range (for reference):

        Range    = T_cond_return - T_cond_supply
        Approach = T_cond_supply - T_wet_bulb    (target: 3-5 C)

4. Transient cooling capacity (simulate):

        dQ_rejected/dt = f(T_outdoor, W_outdoor, load_request)

   When outdoor wet-bulb rises, chiller loses efficiency. The ODE
   tracks condenser water temperature during a heat-wave scenario.

Condensation risk check
-----------------------
The White Space (IT hall) has DLC manifolds at ~18 C. If hall dew point
rises above (DLC_supply - safety_margin), condensation forms on the
manifold surfaces - an electrical-shock and corrosion hazard. We
cross-check here because dew point is a heat-rejection / outdoor-air
concern, not a hall-air one.

References
----------
  - ASHRAE Handbook Fundamentals, Chapter 1 (Psychrometrics)
  - T3-STD-ASHRAE-A2        (thermal envelope)
  - T2-VEN-YK-CHI-YZ        (York YZ chiller spec)
  - T4-MOP-CHI-001          (chiller quarterly PM)
  - AHRI 550/590            (chiller performance rating standard)
"""

from __future__ import annotations

import logging
import math
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

log = logging.getLogger("dc-epms.physics.heat_rejection")


# ---------------------------------------------------------------------------
#  Atmospheric constants
# ---------------------------------------------------------------------------

P_ATM_PA = 101_325.0  # standard atmospheric pressure
R_DA = 287.055  # J/(kg*K), dry-air gas constant


# ---------------------------------------------------------------------------
#  York YZ chiller design values (A3-Alpha, 2 units N+1)
# ---------------------------------------------------------------------------

CHILLER_COUNT = 2
CHILLER_RATED_CAPACITY_KW = 5_275.0  # 1500 TR = 5275 kW per unit
CHILLER_RATED_COP = 7.2  # AHRI conditions
CHILLER_RATED_ECWT_C = 29.4  # AHRI entering condenser water
CHILLER_RATED_LCHWT_C = 6.7  # AHRI leaving chilled water
CHILLER_MIN_ECWT_C = 10.0  # operational minimum
CHILLER_MAX_ECWT_C = 40.0  # operational maximum, >40 trips
# DC-EPMS-029c: approach-margin warning. Above 34 C the condenser has
# lost most of its tower approach margin (rated 29.4 C + ~4.6 K) and is
# trending toward the 40 C high-discharge-pressure trip.
CHILLER_ECWT_WARN_C = 34.0

# --- a3semi operational targets ---
DLC_SUPPLY_TARGET_C = 18.0
CONDENSATION_MARGIN_C = 2.0  # keep dew point >=2 C below DLC supply


# ---------------------------------------------------------------------------
#  Psychrometric functions (ASHRAE / Magnus)
# ---------------------------------------------------------------------------


def saturation_vapor_pressure_pa(t_db_c: float) -> float:
    """Saturation vapor pressure of water at dry-bulb temperature T_db.

    Uses the Magnus-Tetens approximation (valid for -40 to 50 C):

        P_ws(T) = 611.2 * exp(17.625 * T / (T + 243.04))   [Pa]

    Args:
        t_db_c: dry-bulb temperature in degrees Celsius.

    Returns:
        Saturation pressure of water in Pascals.
    """
    return 611.2 * math.exp(17.625 * t_db_c / (t_db_c + 243.04))


def humidity_ratio_from_rh(
    t_db_c: float,
    rh_percent: float,
    p_atm_pa: float = P_ATM_PA,
) -> float:
    """Humidity ratio W (kg water / kg dry air) from dry-bulb + RH.

    W = 0.622 * P_w / (P - P_w)

    where P_w = (RH/100) * P_ws(T_db)
    """
    p_ws = saturation_vapor_pressure_pa(t_db_c)
    p_w = (rh_percent / 100.0) * p_ws
    if p_atm_pa - p_w <= 0:
        return 0.0
    return 0.622 * p_w / (p_atm_pa - p_w)


def dew_point_c_from_rh(t_db_c: float, rh_percent: float) -> float:
    """Dew point temperature from dry-bulb + RH.

    Inverse Magnus: solve P_w = P_ws(T_dp).

        T_dp = 243.04 * ln(P_w/611.2) / (17.625 - ln(P_w/611.2))
    """
    if rh_percent <= 0:
        return -273.15
    p_ws = saturation_vapor_pressure_pa(t_db_c)
    p_w = (rh_percent / 100.0) * p_ws
    if p_w <= 0:
        return -273.15
    alpha = math.log(p_w / 611.2)
    return 243.04 * alpha / (17.625 - alpha)


def wet_bulb_c(
    t_db_c: float,
    rh_percent: float,
    p_atm_pa: float = P_ATM_PA,
) -> float:
    """Wet-bulb temperature by bisection on the psychrometric equation.

    Solves:  h_measured(T_db, W) = h_sat(T_wb)
    where h = 1.006*T + W*(2501 + 1.86*T)  [kJ/kg dry air]

    Uses bisection (not Newton) because the enthalpy equation for
    saturation has highly non-linear d(w_sat)/dT that destabilizes
    Newton's method at moderate-to-high temperatures. Bisection
    converges reliably in 25-30 iterations for 0.01 C tolerance.
    """
    if rh_percent <= 0:
        rh_percent = 0.001
    if rh_percent >= 100:
        return t_db_c  # saturated; wet-bulb = dry-bulb

    w_measured = humidity_ratio_from_rh(t_db_c, rh_percent, p_atm_pa)
    h_measured = 1.006 * t_db_c + w_measured * (2501.0 + 1.86 * t_db_c)

    def h_sat(t_wb: float) -> float:
        """Saturated enthalpy at T_wb (i.e. RH=100%)."""
        w = humidity_ratio_from_rh(t_wb, 100.0, p_atm_pa)
        return 1.006 * t_wb + w * (2501.0 + 1.86 * t_wb)

    # Wet bulb is bounded below by dew point and above by dry bulb
    lo = dew_point_c_from_rh(t_db_c, rh_percent) - 0.1
    hi = t_db_c + 0.1

    # Bisection; ~30 iterations gives ~0.001 C precision
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if h_sat(mid) < h_measured:
            lo = mid
        else:
            hi = mid
        if hi - lo < 0.01:
            break

    return 0.5 * (lo + hi)


# ---------------------------------------------------------------------------
#  Chiller performance model
# ---------------------------------------------------------------------------


def chiller_cop(
    plr: float,
    ecwt_c: float,
    lchwt_c: float = CHILLER_RATED_LCHWT_C,
) -> float:
    """Coefficient of performance for a York YZ magnetic-bearing chiller.

    Simplified model combining:
      - Part-load ratio curve (COP peaks around 50% PLR due to VSD)
      - ECWT curve (every 1 C rise above 29.4 C costs ~3 % COP)
      - Fixed LCHWT term for a3semi 6.7 C setpoint

    Args:
        plr:    Part-load ratio [0, 1.2]
        ecwt_c: Entering condenser water temperature
        lchwt_c: Leaving chilled water temperature

    Returns:
        COP (dimensionless)
    """
    plr = max(0.0, min(1.2, plr))
    ecwt_c = max(5.0, min(45.0, ecwt_c))

    # PLR curve: simple quadratic peaking at PLR=0.5
    # f_plr(0.25)=0.85, f_plr(0.5)=1.10, f_plr(1.0)=1.00, f_plr(1.2)=0.85
    if plr < 0.15:
        f_plr = 0.70 + (plr / 0.15) * 0.15  # 0.70 -> 0.85
    elif plr < 0.5:
        f_plr = 0.85 + (plr - 0.15) / 0.35 * 0.25  # 0.85 -> 1.10
    elif plr < 1.0:
        f_plr = 1.10 - (plr - 0.5) / 0.5 * 0.10  # 1.10 -> 1.00
    else:
        f_plr = 1.00 - (plr - 1.0) / 0.2 * 0.15  # 1.00 -> 0.85

    # ECWT curve: +1 C ECWT ~ -3% COP
    f_ecwt = 1.0 - 0.03 * (ecwt_c - CHILLER_RATED_ECWT_C)
    f_ecwt = max(0.4, min(1.25, f_ecwt))

    # LCHWT correction: +1 C LCHWT ~ +1.8% COP
    f_lchwt = 1.0 + 0.018 * (lchwt_c - CHILLER_RATED_LCHWT_C)
    f_lchwt = max(0.85, min(1.20, f_lchwt))

    return CHILLER_RATED_COP * f_plr * f_ecwt * f_lchwt


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ---------------------------------------------------------------------------
#  HeatRejectionModule
# ---------------------------------------------------------------------------


class HeatRejectionModule(PhysicsModule):
    """Validator + simulator for exterior heat-rejection subsystem.

    Expected measurement schema (validate):
        {
          "outdoor_t_db_c":         float,  # outdoor dry-bulb
          "outdoor_rh_percent":     float,  # outdoor relative humidity
          "hall_dew_point_c":       float,  # hall dew point (if measured)
          "dlc_supply_c":           float,  # DLC supply (white space cross-ref)
          "chiller_1_load_kw":      float,  # current heat rejection per unit
          "chiller_1_power_kw":     float,  # compressor electrical input
          "chiller_1_ecwt_c":       float,  # entering cond water
          "chiller_1_lchwt_c":      float,  # leaving chilled water
          "chiller_2_load_kw":      float,
          "chiller_2_power_kw":     float,
          "chiller_2_ecwt_c":       float,
          "chiller_2_lchwt_c":      float,
        }
    Absent keys fall back to nominal design values.
    """

    module_name = "heat_rejection"

    # ------------------------------------------------------------------ #
    #  Steady-state validation
    # ------------------------------------------------------------------ #

    def validate(
        self,
        measurements: dict[str, Any],
    ) -> ValidationResult:
        r = ValidationResult(module=self.module_name)

        # --- Parse with nominal defaults (Toronto summer, 1 chiller @ 50%) ---
        t_db = float(measurements.get("outdoor_t_db_c", 25.0))
        rh = float(measurements.get("outdoor_rh_percent", 50.0))
        hall_dp_measured = measurements.get("hall_dew_point_c")  # may be None
        dlc_supply = float(measurements.get("dlc_supply_c", DLC_SUPPLY_TARGET_C))

        ch1_load = float(measurements.get("chiller_1_load_kw", 2_500.0))
        ch1_power = float(measurements.get("chiller_1_power_kw", 350.0))
        ch1_ecwt = float(measurements.get("chiller_1_ecwt_c", 29.0))
        ch1_lchwt = float(measurements.get("chiller_1_lchwt_c", 6.7))

        ch2_load = float(measurements.get("chiller_2_load_kw", 2_500.0))
        ch2_power = float(measurements.get("chiller_2_power_kw", 350.0))
        ch2_ecwt = float(measurements.get("chiller_2_ecwt_c", 29.0))
        ch2_lchwt = float(measurements.get("chiller_2_lchwt_c", 6.7))

        # --- Derive psychrometric state ---
        w_out = humidity_ratio_from_rh(t_db, rh)
        dp_out = dew_point_c_from_rh(t_db, rh)
        twb_out = wet_bulb_c(t_db, rh)

        # ============ Check 1: outdoor wet-bulb vs chiller max ==============
        # Cooling tower approach is typically 3-5 C, so if wet-bulb > 27 C
        # the tower cannot deliver ECWT below ~30-32 C, approaching chiller
        # operational max.
        wb_ok = twb_out < 27.0
        r.add_check(
            name="outdoor_wet_bulb_capacity",
            passed=wb_ok,
            value=twb_out,
            threshold=27.0,
            unit="C",
        )
        if not wb_ok:
            interp = (
                f"Outdoor wet-bulb {twb_out:.1f} C approaches cooling tower "
                f"capacity limit. With 3-5 C approach, ECWT will rise to "
                f"{twb_out + 4.0:.1f} C, degrading chiller COP and potentially "
                f"tripping on high discharge pressure."
            )
            action = (
                "Verify cooling tower fans running. Consider enabling "
                "evaporative pre-cooling if available. Reduce IT workload "
                "per EOP-003 if ECWT approaches 40 C."
            )
            if twb_out > 30.0:
                r.escalate(Severity.CRITICAL)
            else:
                r.escalate(Severity.WARNING)
            r.add_justification(
                PhysicalJustification(
                    law="psychrometric_wet_bulb_capacity",
                    measured={
                        "outdoor_t_db_c": t_db,
                        "outdoor_rh_percent": rh,
                        "wet_bulb_c": twb_out,
                    },
                    expected={"wb_threshold_c": 27.0},
                    residual={"excess_c": twb_out - 27.0},
                    threshold={"wb_threshold_c": 27.0},
                    interpretation=interp,
                    suggested_action=action,
                )
            )

        # ============ Check 2: Condensation risk on DLC manifolds ==========
        # Hall dew point must stay below (dlc_supply - margin).
        # Use measured hall DP if available, otherwise fall back to outdoor DP
        # (implies complete HVAC failure  -  conservative bound).
        hall_dp = float(hall_dp_measured) if hall_dp_measured is not None else dp_out
        condensation_margin = dlc_supply - hall_dp
        cond_ok = condensation_margin >= CONDENSATION_MARGIN_C
        r.add_check(
            name="condensation_margin_dlc_manifold",
            passed=cond_ok,
            value=condensation_margin,
            threshold=CONDENSATION_MARGIN_C,
            unit="C",
        )
        if not cond_ok:
            interp = (
                f"Hall dew point {hall_dp:.1f} C is within "
                f"{condensation_margin:.1f} C of DLC supply {dlc_supply:.1f} C. "
                f"Condensation will form on DLC manifold surfaces; electrical "
                f"shock and corrosion hazard."
            )
            action = (
                "Raise DLC supply temperature by 1-2 C. Verify hall "
                "dehumidification active. See T1-SAF-CSE-003 for electrical "
                "safety implications."
            )
            if condensation_margin < 0:
                r.escalate(Severity.CRITICAL)
            else:
                r.escalate(Severity.WARNING)
            r.add_justification(
                PhysicalJustification(
                    law="condensation_risk_dew_point",
                    measured={
                        "hall_dew_point_c": hall_dp,
                        "dlc_supply_c": dlc_supply,
                        "outdoor_dew_point_c": dp_out,
                    },
                    expected={
                        "min_margin_c": CONDENSATION_MARGIN_C,
                        "safe_dew_point_max_c": dlc_supply - CONDENSATION_MARGIN_C,
                    },
                    residual={"margin_c": condensation_margin},
                    threshold={"min_margin_c": CONDENSATION_MARGIN_C},
                    interpretation=interp,
                    suggested_action=action,
                )
            )

        # ============ Check 3: Chiller 1 COP vs performance curve =========
        cop1_result = self._check_chiller_cop(
            r,
            chiller_num=1,
            load_kw=ch1_load,
            power_kw=ch1_power,
            ecwt_c=ch1_ecwt,
            lchwt_c=ch1_lchwt,
        )

        # ============ Check 4: Chiller 2 COP vs performance curve =========
        cop2_result = self._check_chiller_cop(
            r,
            chiller_num=2,
            load_kw=ch2_load,
            power_kw=ch2_power,
            ecwt_c=ch2_ecwt,
            lchwt_c=ch2_lchwt,
        )

        # ============ Check 5: Overall N+1 redundancy ======================
        total_rejection_kw = ch1_load + ch2_load
        # N+1 margin is lost two ways (DC-EPMS-029c):
        #   (a) total load > single-chiller capacity (a trip undersizes
        #       cooling even with both units running), or
        #   (b) a unit is already OFFLINE while the plant carries load —
        #       the carrying chiller is a single point of failure.
        redundancy_ratio = total_rejection_kw / CHILLER_RATED_CAPACITY_KW
        online_count = sum(1 for p in (ch1_power, ch2_power) if p > 1.0)
        unit_offline_under_load = online_count < CHILLER_COUNT and total_rejection_kw > 0.0
        n_plus_1_ok = redundancy_ratio <= 1.0 and not unit_offline_under_load
        r.add_check(
            name="n_plus_1_redundancy_margin",
            passed=n_plus_1_ok,
            value=redundancy_ratio,
            threshold=1.0,
            unit="ratio",
        )
        if not n_plus_1_ok:
            if unit_offline_under_load:
                interp = (
                    f"Only {online_count} of {CHILLER_COUNT} chillers online "
                    f"while rejecting {total_rejection_kw:.0f} kW. The "
                    f"carrying chiller is a single point of failure - its "
                    f"trip means total loss of heat rejection."
                )
            else:
                interp = (
                    f"Total heat rejection {total_rejection_kw:.0f} kW exceeds "
                    f"single-chiller capacity {CHILLER_RATED_CAPACITY_KW:.0f} kW. "
                    f"N+1 redundancy lost - a single chiller trip would result "
                    f"in undersized cooling capacity."
                )
            action = (
                "Reduce IT workload per EOP-003 to restore N+1 margin, or "
                "commission additional cooling capacity."
            )
            r.escalate(Severity.WARNING)
            r.add_justification(
                PhysicalJustification(
                    law="n_plus_1_redundancy",
                    measured={
                        "total_heat_rejection_kw": total_rejection_kw,
                        "single_chiller_capacity_kw": CHILLER_RATED_CAPACITY_KW,
                        "chillers_online": online_count,
                    },
                    expected={
                        "max_safe_total_kw": CHILLER_RATED_CAPACITY_KW,
                        "chillers_online_min": CHILLER_COUNT,
                    },
                    residual={"excess_kw": total_rejection_kw - CHILLER_RATED_CAPACITY_KW},
                    threshold={"redundancy_ratio_max": 1.0},
                    interpretation=interp,
                    suggested_action=action,
                )
            )

        # ============ Check 6: Condenser-water envelope (DC-EPMS-029c) =====
        # ECWT on RUNNING chillers vs the York YZ operational envelope.
        # Cooling-tower capacity loss surfaces here: fewer cells -> higher
        # ECWT at unchanged duty -> approach margin to the 40 C trip erodes.
        running_ecwts = [
            ecwt for power, ecwt in ((ch1_power, ch1_ecwt), (ch2_power, ch2_ecwt))
            if power > 1.0
        ]
        ecwt_worst = max(running_ecwts) if running_ecwts else CHILLER_RATED_ECWT_C
        ecwt_ok = ecwt_worst <= CHILLER_ECWT_WARN_C
        r.add_check(
            name="condenser_water_envelope",
            passed=ecwt_ok,
            value=ecwt_worst,
            threshold=CHILLER_ECWT_WARN_C,
            unit="C",
        )
        if not ecwt_ok:
            tripping = ecwt_worst >= CHILLER_MAX_ECWT_C
            interp = (
                f"Worst running-chiller ECWT {ecwt_worst:.1f} C exceeds the "
                f"{CHILLER_ECWT_WARN_C:.0f} C approach-margin threshold "
                f"(rated {CHILLER_RATED_ECWT_C:.1f} C, trip "
                f"{CHILLER_MAX_ECWT_C:.0f} C). Condenser heat rejection is "
                f"capacity-limited - typical of cooling tower cell loss or "
                f"fouled fill at sustained duty."
            )
            action = (
                "Verify all cooling tower cells / fans running. Check "
                "condenser water flow balance. Reduce IT workload per "
                "EOP-003 if ECWT trends toward 40 C."
            )
            r.escalate(Severity.CRITICAL if tripping else Severity.WARNING)
            r.add_justification(
                PhysicalJustification(
                    law="condenser_water_envelope",
                    measured={"ecwt_worst_c": ecwt_worst},
                    expected={
                        "ecwt_rated_c": CHILLER_RATED_ECWT_C,
                        "ecwt_warn_c": CHILLER_ECWT_WARN_C,
                        "ecwt_trip_c": CHILLER_MAX_ECWT_C,
                    },
                    residual={"excess_c": ecwt_worst - CHILLER_ECWT_WARN_C},
                    threshold={"ecwt_warn_c": CHILLER_ECWT_WARN_C},
                    interpretation=interp,
                    suggested_action=action,
                )
            )

        # --- Module health ---
        penalty = 0.0
        if not wb_ok:
            penalty = max(penalty, 0.30 if twb_out > 30 else 0.15)
        if not cond_ok:
            penalty = max(penalty, 0.60 if condensation_margin < 0 else 0.25)
        if not cop1_result["ok"]:
            penalty = max(penalty, 0.15)
        if not cop2_result["ok"]:
            penalty = max(penalty, 0.15)
        if not n_plus_1_ok:
            penalty = max(penalty, 0.20)
        if not ecwt_ok:
            penalty = max(penalty, 0.50 if ecwt_worst >= CHILLER_MAX_ECWT_C else 0.20)
        r.health = _clamp01(1.0 - penalty)

        r.metrics = {
            "outdoor_t_db_c": t_db,
            "outdoor_rh_percent": rh,
            "outdoor_humidity_ratio": w_out,
            "outdoor_dew_point_c": dp_out,
            "outdoor_wet_bulb_c": twb_out,
            "hall_dew_point_c": hall_dp,
            "condensation_margin_c": condensation_margin,
            "chiller_1_cop_measured": cop1_result["cop_measured"],
            "chiller_1_cop_expected": cop1_result["cop_expected"],
            "chiller_2_cop_measured": cop2_result["cop_measured"],
            "chiller_2_cop_expected": cop2_result["cop_expected"],
            "total_heat_rejection_kw": total_rejection_kw,
            "n_plus_1_ratio": redundancy_ratio,
            "chillers_online": online_count,
            "ecwt_worst_c": ecwt_worst,
            "health": r.health,
        }
        return r

    def _check_chiller_cop(
        self,
        r: ValidationResult,
        chiller_num: int,
        load_kw: float,
        power_kw: float,
        ecwt_c: float,
        lchwt_c: float,
    ) -> dict:
        """Validate a single chiller's measured COP against curve."""
        if power_kw <= 1.0:
            # Chiller off - skip check
            r.add_check(
                name=f"chiller_{chiller_num}_cop_vs_curve",
                passed=True,
                value=0.0,
                threshold=0.0,
                unit="COP",
            )
            return {"ok": True, "cop_measured": 0.0, "cop_expected": 0.0}

        cop_measured = load_kw / power_kw
        plr = load_kw / CHILLER_RATED_CAPACITY_KW
        cop_expected = chiller_cop(plr, ecwt_c, lchwt_c)
        residual = cop_measured - cop_expected
        threshold = 0.8  # 0.8 COP units tolerance
        ok = abs(residual) <= threshold
        r.add_check(
            name=f"chiller_{chiller_num}_cop_vs_curve",
            passed=ok,
            value=residual,
            threshold=threshold,
            unit="COP",
        )
        if not ok:
            if residual < 0:
                interp = (
                    f"Chiller {chiller_num} measured COP {cop_measured:.2f} "
                    f"vs expected {cop_expected:.2f} (PLR {plr * 100:.0f}%, "
                    f"ECWT {ecwt_c:.1f} C). Deficit {-residual:.2f} suggests "
                    f"condenser fouling, refrigerant charge loss, or "
                    f"magnetic-bearing issue."
                )
            else:
                interp = (
                    f"Chiller {chiller_num} measured COP {cop_measured:.2f} "
                    f"above expected {cop_expected:.2f}. Likely meter "
                    f"calibration issue - verify load and power readings."
                )
            action = (
                "Schedule chiller PM per T4-MOP-CHI-001 if trend persists. "
                "Check condenser water chemistry and approach temperature."
            )
            r.escalate(Severity.INFO)
            r.add_justification(
                PhysicalJustification(
                    law=f"chiller_{chiller_num}_cop_curve",
                    measured={
                        "load_kw": load_kw,
                        "power_kw": power_kw,
                        "cop_measured": cop_measured,
                        "plr": plr,
                        "ecwt_c": ecwt_c,
                        "lchwt_c": lchwt_c,
                    },
                    expected={"cop_expected": cop_expected},
                    residual={"residual_cop": residual},
                    threshold={"threshold_cop": threshold},
                    interpretation=interp,
                    suggested_action=action,
                )
            )
        return {"ok": ok, "cop_measured": cop_measured, "cop_expected": cop_expected}

    # ------------------------------------------------------------------ #
    #  Transient simulation - heat-wave scenario
    # ------------------------------------------------------------------ #

    def simulate(
        self,
        initial_state: dict[str, float],
        perturbation: dict[str, Any],
        horizon_s: int = 900,
        dt_s: float = 1.0,
    ) -> list[StateSnapshot]:
        """Simulate rising outdoor wet-bulb and impact on chiller capacity.

        Governing principle:
          Cooling-tower ECWT = T_wet_bulb + approach (3-5 C)
          Chiller COP and capacity drop as ECWT rises.
          Condenser system reaches high-pressure trip when ECWT > 40 C.

        Perturbation schema:
            {
              "type": str,
              "t_db_ramp":      bool      - if True, outdoor T_db rises
              "rh_ramp":        bool      - if True, RH rises too
              "t_db_final_c":   float     - target dry-bulb at end of ramp
              "rh_final":       float     - target RH at end of ramp
              "ramp_s":         float     - duration of ramp (seconds)
              "start_s":        float
              "duration_s":     float
            }
        """
        t_db_0 = float(initial_state.get("outdoor_t_db_c", 25.0))
        rh_0 = float(initial_state.get("outdoor_rh_percent", 50.0))
        load_kw = float(initial_state.get("it_load_kw", 16_756.0))

        t_db_final = float(perturbation.get("t_db_final_c", t_db_0))
        rh_final = float(perturbation.get("rh_final", rh_0))
        ramp_s = float(perturbation.get("ramp_s", 300.0))
        start_s = float(perturbation.get("start_s", 0.0))
        duration_s = float(perturbation.get("duration_s", horizon_s))

        # Closed-form trajectory (no ODE needed; outdoor conditions are
        # exogenous. The "ODE" here is just a projection + capacity calc).
        trajectory: list[StateSnapshot] = []

        high_pressure_triggered = False
        n_plus_1_lost = False
        condensation_triggered = False

        t = 0.0
        while t <= horizon_s:
            # Linear ramp of outdoor conditions
            if t < start_s:
                t_db_now = t_db_0
                rh_now = rh_0
            elif t < start_s + ramp_s:
                alpha = (t - start_s) / ramp_s
                t_db_now = t_db_0 + (t_db_final - t_db_0) * alpha
                rh_now = rh_0 + (rh_final - rh_0) * alpha
            elif t < start_s + duration_s:
                t_db_now = t_db_final
                rh_now = rh_final
            else:
                # Fault ended, back to initial
                t_db_now = t_db_0
                rh_now = rh_0

            # Psychrometric derivatives
            twb = wet_bulb_c(t_db_now, rh_now)
            dp = dew_point_c_from_rh(t_db_now, rh_now)
            # Cooling tower approach ~4 C
            ecwt = twb + 4.0

            # Per-chiller load: split evenly between 2 units
            per_chiller = load_kw * 0.95 / 2.0  # 95% to DLC side
            plr = per_chiller / CHILLER_RATED_CAPACITY_KW
            cop = chiller_cop(plr, ecwt, CHILLER_RATED_LCHWT_C)
            compressor_power_per_unit = per_chiller / cop if cop > 0 else 0.0

            # Event detection
            events = []
            if ecwt >= CHILLER_MAX_ECWT_C and not high_pressure_triggered:
                events.append("chiller_high_pressure_trip_imminent")
                high_pressure_triggered = True
            if plr > 1.0 and not n_plus_1_lost:
                events.append("n_plus_1_redundancy_lost")
                n_plus_1_lost = True
            if dp > (DLC_SUPPLY_TARGET_C - CONDENSATION_MARGIN_C) and not condensation_triggered:
                events.append("condensation_risk_threshold_crossed")
                condensation_triggered = True

            trajectory.append(
                StateSnapshot(
                    t=t,
                    state={
                        "outdoor_t_db_c": t_db_now,
                        "outdoor_rh_percent": rh_now,
                        "outdoor_wet_bulb_c": twb,
                        "outdoor_dew_point_c": dp,
                        "ecwt_c": ecwt,
                        "chiller_plr": plr,
                        "chiller_cop": cop,
                        "compressor_power_per_unit_kw": compressor_power_per_unit,
                        "total_compressor_power_kw": compressor_power_per_unit * 2.0,
                    },
                    events=events,
                )
            )
            t += dt_s

        return trajectory
