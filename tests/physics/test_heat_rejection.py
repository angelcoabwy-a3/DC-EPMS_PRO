"""
Tests for Heat Rejection physics module.

Coverage:
  - Psychrometric functions (saturation pressure, dew point, wet bulb)
  - Chiller COP curve (PLR and ECWT sensitivity)
  - Validator: outdoor wet bulb, condensation margin, COP cross-check,
    N+1 redundancy
  - Simulate: heat wave ramp up
"""
from __future__ import annotations

import math
import pytest

from backend.physics.base import Severity
from backend.physics.heat_rejection import (
    CHILLER_RATED_CAPACITY_KW,
    CHILLER_RATED_COP,
    DLC_SUPPLY_TARGET_C,
    HeatRejectionModule,
    chiller_cop,
    dew_point_c_from_rh,
    humidity_ratio_from_rh,
    saturation_vapor_pressure_pa,
    wet_bulb_c,
)


class TestPsychrometrics:

    def test_sat_pressure_0c_matches_literature(self):
        """At 0 C, saturation pressure = 611.2 Pa."""
        p = saturation_vapor_pressure_pa(0.0)
        assert abs(p - 611.2) < 1.0

    def test_sat_pressure_100c_near_1atm(self):
        """At 100 C, saturation pressure ≈ 101.3 kPa (by definition)."""
        p = saturation_vapor_pressure_pa(100.0)
        # Magnus approx is within ~1% at 100C boundary
        assert 90_000 < p < 105_000

    def test_sat_pressure_monotonic(self):
        for t in range(0, 40, 5):
            p1 = saturation_vapor_pressure_pa(t)
            p2 = saturation_vapor_pressure_pa(t + 5)
            assert p2 > p1

    def test_humidity_ratio_at_saturation(self):
        """At 100% RH, humidity ratio matches saturation."""
        w_100 = humidity_ratio_from_rh(25.0, 100.0)
        w_50 = humidity_ratio_from_rh(25.0, 50.0)
        assert w_100 > w_50
        assert abs(w_50 - w_100 / 2) < 0.002  # approximately linear at moderate T

    def test_dew_point_at_100_rh_equals_db(self):
        """At 100% RH, dew point = dry bulb."""
        dp = dew_point_c_from_rh(25.0, 100.0)
        assert abs(dp - 25.0) < 0.5

    def test_dew_point_monotonic_with_rh(self):
        dp_30 = dew_point_c_from_rh(25.0, 30.0)
        dp_70 = dew_point_c_from_rh(25.0, 70.0)
        assert dp_30 < dp_70
        assert dp_30 < 25.0  # always below dry bulb

    def test_wet_bulb_at_100_rh_equals_db(self):
        twb = wet_bulb_c(25.0, 100.0)
        assert abs(twb - 25.0) < 0.5

    def test_wet_bulb_between_dp_and_db(self):
        """Wet bulb must lie between dew point and dry bulb."""
        t_db = 30.0
        rh = 50.0
        dp = dew_point_c_from_rh(t_db, rh)
        twb = wet_bulb_c(t_db, rh)
        assert dp < twb < t_db

    def test_wet_bulb_known_value(self):
        """Literature check: T_db=30, RH=50% -> T_wb ≈ 22.0 C."""
        twb = wet_bulb_c(30.0, 50.0)
        assert 21.0 < twb < 23.0, f"Got T_wb = {twb:.2f}"


class TestChillerCOP:

    def test_rated_conditions(self):
        """At rated PLR and ECWT, COP matches nominal within tolerance."""
        cop = chiller_cop(plr=1.0, ecwt_c=29.4, lchwt_c=6.7)
        assert abs(cop - CHILLER_RATED_COP) < 0.2

    def test_cop_peaks_at_part_load(self):
        """York YZ peaks near 50% PLR."""
        cop_peak = chiller_cop(0.5, ecwt_c=29.4)
        cop_full = chiller_cop(1.0, ecwt_c=29.4)
        assert cop_peak > cop_full

    def test_cop_drops_with_high_ecwt(self):
        """Each 1 C ECWT rise ~ 3% COP loss."""
        cop_cool = chiller_cop(0.5, ecwt_c=29.4)
        cop_hot = chiller_cop(0.5, ecwt_c=35.0)
        assert cop_cool > cop_hot
        ratio = cop_hot / cop_cool
        # 5.6 C rise * 3% per C ≈ 17% drop
        assert 0.75 < ratio < 0.90


class TestValidateNominal:

    def _nominal(self) -> dict:
        """Operational point at Toronto summer, moderate load."""
        return {
            "outdoor_t_db_c": 25.0,
            "outdoor_rh_percent": 50.0,
            "hall_dew_point_c": 8.0,     # well below 16 C margin
            "dlc_supply_c": 18.0,
            "chiller_1_load_kw": 2_500.0,
            "chiller_1_power_kw": 350.0,  # COP ~7.1
            "chiller_1_ecwt_c": 29.0,
            "chiller_1_lchwt_c": 6.7,
            "chiller_2_load_kw": 2_500.0,
            "chiller_2_power_kw": 350.0,
            "chiller_2_ecwt_c": 29.0,
            "chiller_2_lchwt_c": 6.7,
        }

    def test_nominal_ok(self):
        m = HeatRejectionModule()
        r = m.validate(self._nominal())
        assert r.severity in (Severity.OK, Severity.INFO)
        assert r.health > 0.85

    def test_metrics_populated(self):
        m = HeatRejectionModule()
        r = m.validate(self._nominal())
        assert "outdoor_wet_bulb_c" in r.metrics
        assert "condensation_margin_c" in r.metrics
        assert r.metrics["condensation_margin_c"] > 0


class TestFaults:

    def _baseline(self) -> dict:
        return {
            "outdoor_t_db_c": 25.0,
            "outdoor_rh_percent": 50.0,
            "hall_dew_point_c": 8.0,
            "dlc_supply_c": 18.0,
            "chiller_1_load_kw": 2_500.0,
            "chiller_1_power_kw": 350.0,
            "chiller_1_ecwt_c": 29.0,
            "chiller_1_lchwt_c": 6.7,
            "chiller_2_load_kw": 2_500.0,
            "chiller_2_power_kw": 350.0,
            "chiller_2_ecwt_c": 29.0,
            "chiller_2_lchwt_c": 6.7,
        }

    def test_heat_wave_triggers_wet_bulb_warning(self):
        m = HeatRejectionModule()
        meas = self._baseline()
        meas["outdoor_t_db_c"] = 36.0
        meas["outdoor_rh_percent"] = 65.0
        r = m.validate(meas)
        wb_check = next(c for c in r.checks
                        if c["name"] == "outdoor_wet_bulb_capacity")
        assert not wb_check["passed"]
        assert r.severity >= Severity.WARNING

    def test_condensation_risk_critical_when_margin_negative(self):
        m = HeatRejectionModule()
        meas = self._baseline()
        # Force dew point higher than DLC supply
        meas["hall_dew_point_c"] = 20.0  # above 18 C DLC supply
        r = m.validate(meas)
        cond_check = next(c for c in r.checks
                          if c["name"] == "condensation_margin_dlc_manifold")
        assert not cond_check["passed"]
        assert r.severity == Severity.CRITICAL

    def test_condensation_warning_when_margin_small(self):
        m = HeatRejectionModule()
        meas = self._baseline()
        meas["hall_dew_point_c"] = 17.0  # 1 C below 18 -> margin < 2
        r = m.validate(meas)
        cond_check = next(c for c in r.checks
                          if c["name"] == "condensation_margin_dlc_manifold")
        assert not cond_check["passed"]

    def test_chiller_cop_deficit_flagged(self):
        """If chiller uses way more power than curve expects -> fault."""
        m = HeatRejectionModule()
        meas = self._baseline()
        meas["chiller_1_power_kw"] = 700.0  # 2x expected at 50% PLR
        r = m.validate(meas)
        cop_check = next(c for c in r.checks
                         if c["name"] == "chiller_1_cop_vs_curve")
        assert not cop_check["passed"]

    def test_n_plus_1_redundancy_violated(self):
        m = HeatRejectionModule()
        meas = self._baseline()
        # Push each chiller above rated single-unit capacity
        meas["chiller_1_load_kw"] = 5_000.0
        meas["chiller_2_load_kw"] = 5_000.0
        meas["chiller_1_power_kw"] = 700.0
        meas["chiller_2_power_kw"] = 700.0
        r = m.validate(meas)
        red_check = next(c for c in r.checks
                         if c["name"] == "n_plus_1_redundancy_margin")
        assert not red_check["passed"]


class TestSimulate:

    def test_heat_wave_ramp_generates_trajectory(self):
        m = HeatRejectionModule()
        traj = m.simulate(
            initial_state={
                "outdoor_t_db_c": 25.0,
                "outdoor_rh_percent": 50.0,
                "it_load_kw": 16_756.0,
            },
            perturbation={
                "t_db_ramp": True,
                "rh_ramp": True,
                "t_db_final_c": 36.0,
                "rh_final": 65.0,
                "ramp_s": 300,
                "start_s": 0,
                "duration_s": 3600,
            },
            horizon_s=900,
            dt_s=1.0,
        )
        assert len(traj) >= 900
        # Wet bulb should rise from ~17 to ~29 C
        wb_start = traj[0].state["outdoor_wet_bulb_c"]
        wb_end = traj[-1].state["outdoor_wet_bulb_c"]
        assert wb_end > wb_start
        assert wb_end > 25.0   # got hot

    def test_chiller_cop_declines_with_ecwt(self):
        m = HeatRejectionModule()
        traj = m.simulate(
            initial_state={
                "outdoor_t_db_c": 25.0,
                "outdoor_rh_percent": 50.0,
                "it_load_kw": 16_756.0,
            },
            perturbation={
                "t_db_ramp": True,
                "rh_ramp": True,
                "t_db_final_c": 38.0,
                "rh_final": 70.0,
                "ramp_s": 200,
                "start_s": 0,
                "duration_s": 3600,
            },
            horizon_s=500,
            dt_s=1.0,
        )
        cop_start = traj[0].state["chiller_cop"]
        cop_end = traj[-1].state["chiller_cop"]
        assert cop_end < cop_start  # efficiency degraded

    def test_nominal_conditions_stable(self):
        m = HeatRejectionModule()
        traj = m.simulate(
            initial_state={"outdoor_t_db_c": 25.0, "outdoor_rh_percent": 50.0},
            perturbation={},
            horizon_s=300,
            dt_s=1.0,
        )
        # No perturbation -> state essentially constant
        first = traj[0]
        last = traj[-1]
        assert abs(first.state["outdoor_wet_bulb_c"]
                   - last.state["outdoor_wet_bulb_c"]) < 0.5
