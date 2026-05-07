"""
Tests for Mechanical physics module.

Coverage:
  - Darcy-Weisbach pressure-drop validation
  - CDU heat balance (primary vs secondary)
  - Pump affinity law (P ~ N^3)
  - NPSH / cavitation detection
  - ODE simulation: flow loss -> return temp rise
"""
from __future__ import annotations

import pytest

from backend.physics.base import Severity
from backend.physics.mechanical import (
    HALL_FLOW_NOMINAL_M3_S,
    MechanicalModule,
    PUMP_MIN_SUCTION_PRESSURE_BAR,
    _darcy_pressure_drop_pa,
)


class TestDarcyWeisbach:

    def test_dp_scales_with_velocity_squared(self):
        """Darcy-Weisbach: dp ~ v^2, so dp(2Q) / dp(Q) ~ 4."""
        dp1 = _darcy_pressure_drop_pa(flow_m3_s=0.05)
        dp2 = _darcy_pressure_drop_pa(flow_m3_s=0.10)
        ratio = dp2 / dp1
        assert 3.8 <= ratio <= 4.2, f"Expected ~4x, got {ratio:.2f}"

    def test_dp_zero_flow_zero(self):
        assert _darcy_pressure_drop_pa(flow_m3_s=0.0) == 0.0

    def test_dp_is_positive(self):
        assert _darcy_pressure_drop_pa(flow_m3_s=0.05) > 0.0


class TestValidateNominal:

    def _nominal_measurements(self) -> dict:
        """Measurements at design-point equilibrium.

        CDU heat balance calc at nominal:
          Q_secondary = flow * rho_pgw * cp_pgw * dT = 5511 kW
          For primary side (water cp=4180) at 0.066 m^3/s:
            dT_primary = 5511e3 / (0.066 * 1000 * 4180) = 19.98 K
          So primary_out = 7 + 20 = 27.0 C
        """
        import math
        dp_pa = _darcy_pressure_drop_pa(HALL_FLOW_NOMINAL_M3_S)
        return {
            "loop_flow_m3_s": HALL_FLOW_NOMINAL_M3_S,
            "loop_dp_measured_bar": dp_pa / 1e5,
            "loop_supply_c": 18.0,
            "loop_return_c": 40.0,
            "cdu_primary_in_c": 7.0,
            "cdu_primary_out_c": 27.0,  # balanced at 0.066 m^3/s primary flow
            "cdu_primary_flow_m3_s": 0.066,
            "pump_speed_hz": 60.0,
            "pump_suction_bar": 1.8,
            "pump_power_kw": 45.0,
            "rack_count": 40,
            "rack_tdp_kw": 142.0,
        }

    def test_nominal_ok(self):
        m = MechanicalModule()
        r = m.validate(self._nominal_measurements())
        assert r.severity in (Severity.OK, Severity.INFO)
        assert r.health > 0.85

    def test_nominal_darcy_close(self):
        m = MechanicalModule()
        r = m.validate(self._nominal_measurements())
        check = next(c for c in r.checks
                     if c["name"] == "darcy_weisbach_loop_pressure_drop")
        assert check["passed"]


class TestFaults:

    def _baseline(self):
        """Start from nominal and override specific fields."""
        import math
        dp_pa = _darcy_pressure_drop_pa(HALL_FLOW_NOMINAL_M3_S)
        return {
            "loop_flow_m3_s": HALL_FLOW_NOMINAL_M3_S,
            "loop_dp_measured_bar": dp_pa / 1e5,
            "loop_supply_c": 18.0,
            "loop_return_c": 40.0,
            "cdu_primary_in_c": 7.0,
            "cdu_primary_out_c": 27.0,
            "cdu_primary_flow_m3_s": 0.066,
            "pump_speed_hz": 60.0,
            "pump_suction_bar": 1.8,
            "pump_power_kw": 45.0,
            "rack_count": 40,
            "rack_tdp_kw": 142.0,
        }

    def test_partial_blockage_dp_elevated(self):
        """If dp is much higher than Darcy for the given flow -> blockage."""
        m = MechanicalModule()
        meas = self._baseline()
        # Triple the measured dp
        meas["loop_dp_measured_bar"] *= 3.0
        r = m.validate(meas)
        dp_check = next(c for c in r.checks
                        if c["name"] == "darcy_weisbach_loop_pressure_drop")
        assert not dp_check["passed"]
        assert r.severity >= Severity.WARNING
        # Justification references darcy-weisbach
        just = [j for j in r.justifications if j.law == "darcy_weisbach"]
        assert len(just) == 1

    def test_leak_dp_depressed(self):
        """If dp is much lower than Darcy -> bypass/leak."""
        m = MechanicalModule()
        meas = self._baseline()
        meas["loop_dp_measured_bar"] *= 0.3
        r = m.validate(meas)
        dp_check = next(c for c in r.checks
                        if c["name"] == "darcy_weisbach_loop_pressure_drop")
        assert not dp_check["passed"]

    def test_cavitation_critical(self):
        """Pump suction below NPSH min -> critical."""
        m = MechanicalModule()
        meas = self._baseline()
        meas["pump_suction_bar"] = 0.5  # well below 1.2 bar
        r = m.validate(meas)
        cav_check = next(c for c in r.checks
                         if c["name"] == "pump_cavitation_margin")
        assert not cav_check["passed"]
        assert r.severity == Severity.CRITICAL

    def test_pump_power_high_indicates_friction(self):
        """Pump drawing more than affinity law predicts -> bearing friction."""
        m = MechanicalModule()
        meas = self._baseline()
        # At 60 Hz, expected ~45 kW. Give it 65 kW.
        meas["pump_power_kw"] = 65.0
        r = m.validate(meas)
        pwr_check = next(c for c in r.checks
                         if c["name"] == "pump_affinity_cubic_power")
        assert not pwr_check["passed"]

    def test_cdu_imbalance_flagged(self):
        """Secondary and primary heat don't match -> fouling/drift."""
        m = MechanicalModule()
        meas = self._baseline()
        # Make primary side way too cold a spread => lots less heat
        meas["cdu_primary_out_c"] = 14.0  # should be ~25
        r = m.validate(meas)
        cdu_check = next(c for c in r.checks
                         if c["name"] == "cdu_heat_balance")
        assert not cdu_check["passed"]


class TestSimulate:

    def test_nominal_flow_keeps_temp_stable(self):
        m = MechanicalModule()
        traj = m.simulate(
            initial_state={
                "loop_return_c": 40.0,
                "loop_supply_c": 18.0,
                "rack_count": 40,
                "rack_tdp_kw": 142.0,
                "loop_flow_m3_s": HALL_FLOW_NOMINAL_M3_S,
            },
            perturbation={},
            horizon_s=600,
            dt_s=1.0,
        )
        assert len(traj) >= 600
        final = traj[-1]
        # With nominal flow, return temp should stay near 40 C
        assert 38.0 <= final.state["loop_return_c"] <= 42.0

    def test_pump_trip_heats_secondary_loop(self):
        m = MechanicalModule()
        traj = m.simulate(
            initial_state={
                "loop_return_c": 40.0,
                "loop_supply_c": 18.0,
                "rack_count": 40,
                "rack_tdp_kw": 142.0,
                "loop_flow_m3_s": HALL_FLOW_NOMINAL_M3_S,
            },
            perturbation={
                "pump_trip": True,
                "start_s": 0,
                "duration_s": 900,
            },
            horizon_s=900,
            dt_s=1.0,
        )
        # Under pump trip, return temp should rise significantly
        final = traj[-1]
        assert final.state["loop_return_c"] > 45.0, (
            f"Expected temp rise, got {final.state['loop_return_c']:.1f}"
        )
        # Overtemp event should fire
        all_events = [e for snap in traj for e in snap.events]
        assert "secondary_loop_overtemp" in all_events

    def test_flow_reduction_raises_delta_t(self):
        """Under reduced flow, delta_T must rise to maintain Q balance."""
        m = MechanicalModule()
        traj = m.simulate(
            initial_state={
                "loop_return_c": 40.0,
                "loop_supply_c": 18.0,
                "rack_count": 40,
                "rack_tdp_kw": 142.0,
                "loop_flow_m3_s": HALL_FLOW_NOMINAL_M3_S,
            },
            perturbation={
                "flow_factor": 0.5,
                "start_s": 0,
                "duration_s": 900,
            },
            horizon_s=300,
            dt_s=1.0,
        )
        final = traj[-1]
        assert final.state["dlc_delta_T_k"] > 25.0
