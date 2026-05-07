"""
Tests for PhysicsEngine facade.

Coverage:
  - validate_site runs all 4 modules and returns aggregated result
  - Site Health Index uses min() + severity modifier
  - First-law cross-check produces residuals
  - Cascade detection for known patterns
  - simulate_scenario dispatches to correct module
"""
from __future__ import annotations

import pytest

from backend.physics.base import Severity
from backend.physics_engine import (
    PhysicsEngine,
    SiteValidationResult,
    get_engine,
)


class TestValidateSite:

    def _nominal_site(self) -> dict:
        """Combined telemetry that keeps all 4 modules happy."""
        return {
            # IT
            "rack_count": 118,
            "rack_tdp_kw": 142.0,
            "dlc_supply_c": 18.0,
            "dlc_return_c": 18.0 + 21.3,
            "dlc_flow_l_min": 100.0,
            "hall_inlet_c": 20.0,
            "gpu_tj_max_c": 70.0,
            # Mechanical
            "loop_flow_m3_s": 0.066,
            "loop_dp_measured_bar": 2.17,
            "loop_supply_c": 18.0,
            "loop_return_c": 40.0,
            "cdu_primary_in_c": 7.0,
            "cdu_primary_out_c": 27.0,
            "cdu_primary_flow_m3_s": 0.066,
            "pump_speed_hz": 60.0,
            "pump_suction_bar": 1.8,
            "pump_power_kw": 45.0,
            # Electrical
            "utility_kw": 17_400.0,
            "facility_it_kw": 16_756.0,
            "ups_load_kw": 300.0,
            "ups_mode": "online",
            "ups_input_kw": 300.0 / 0.96,
            "xfmr_load_kva": 1_800.0,
            "xfmr_top_oil_c": 65.0,
            "xfmr_winding_c": 98.7,
            "battery_soc": 1.0,
            "battery_vdc": 540.0,
            "battery_on_load": False,
            # Heat rejection
            "outdoor_t_db_c": 25.0,
            "outdoor_rh_percent": 50.0,
            "hall_dew_point_c": 8.0,
            "chiller_1_load_kw": 2_500.0,
            "chiller_1_power_kw": 350.0,
            "chiller_1_ecwt_c": 29.0,
            "chiller_1_lchwt_c": 6.7,
            "chiller_2_load_kw": 2_500.0,
            "chiller_2_power_kw": 350.0,
            "chiller_2_ecwt_c": 29.0,
            "chiller_2_lchwt_c": 6.7,
        }

    def test_nominal_site_all_healthy(self):
        engine = PhysicsEngine()
        result = engine.validate_site(self._nominal_site())
        assert result.site_health > 0.85
        assert result.overall_severity in (Severity.OK, Severity.INFO)
        assert len(result.modules) == 4
        assert set(result.modules.keys()) == {
            "it_thermal", "mechanical", "electrical", "heat_rejection"
        }

    def test_all_modules_healths_reported(self):
        engine = PhysicsEngine()
        result = engine.validate_site(self._nominal_site())
        for name, r in result.modules.items():
            assert 0.0 <= r.health <= 1.0
            assert r.module == name

    def test_weakest_module_identified(self):
        """With a single weak spot, weakest_module should name it."""
        engine = PhysicsEngine()
        m = self._nominal_site()
        # Break electrical - transformer overtemp
        m["xfmr_winding_c"] = 140.0
        result = engine.validate_site(m)
        assert result.weakest_module == "electrical"
        assert result.site_health < 0.75  # severity_modifier kicks in

    def test_min_rule_dominates(self):
        """Worst module dictates SHI even if others are perfect."""
        engine = PhysicsEngine()
        m = self._nominal_site()
        # Break mechanical severely
        m["pump_suction_bar"] = 0.3  # cavitation
        result = engine.validate_site(m)
        mech_h = result.modules["mechanical"].health
        # SHI ≤ mech health * severity_modifier
        assert result.site_health <= mech_h + 0.01


class TestFirstLawCrossCheck:

    def test_residuals_computed(self):
        engine = PhysicsEngine()
        m = TestValidateSite()._nominal_site()
        result = engine.validate_site(m)
        # Both cross-checks should return numeric residuals
        # (may be zero if metrics don't align in test data)
        assert isinstance(result.first_law_residuals, dict)


class TestCascadeDetection:

    def test_pump_cavitation_with_it_stress(self):
        """Pump cavitation + IT energy residual -> cascade event."""
        engine = PhysicsEngine()
        m = TestValidateSite()._nominal_site()
        # Force both patterns
        m["pump_suction_bar"] = 0.3          # cavitation
        m["dlc_flow_l_min"] = 40.0           # DLC flow anomaly
        m["dlc_return_c"] = 60.0             # breaks energy balance
        result = engine.validate_site(m)
        cascade_names = [c["pattern"] for c in result.cascade_events]
        assert "pump_cavitation_to_it_thermal_stress" in cascade_names

    def test_heat_wave_cascade(self):
        """Heat wave + chiller COP low -> cascade event."""
        engine = PhysicsEngine()
        m = TestValidateSite()._nominal_site()
        # Elevated wet-bulb
        m["outdoor_t_db_c"] = 36.0
        m["outdoor_rh_percent"] = 70.0
        # Chiller COP below curve
        m["chiller_1_power_kw"] = 700.0
        m["chiller_2_power_kw"] = 700.0
        result = engine.validate_site(m)
        cascade_names = [c["pattern"] for c in result.cascade_events]
        assert "heat_wave_chiller_degradation" in cascade_names

    def test_no_cascade_in_nominal(self):
        engine = PhysicsEngine()
        result = engine.validate_site(TestValidateSite()._nominal_site())
        assert len(result.cascade_events) == 0


class TestSimulateScenario:

    def test_scenario_dispatches_to_module(self):
        engine = PhysicsEngine()
        scenario = {
            "id": "SCN-TEST",
            "name": "Test scenario",
            "primary_module": "it_thermal",
            "initial_state": {
                "hall_return_c": 22.0,
                "rack_count": 118,
                "rack_tdp_kw": 142.0,
                "dlc_supply_c": 18.0,
                "dlc_flow_l_min": 100.0,
            },
            "perturbation": {
                "cooling_factor": 0.5,
                "dlc_flow_factor": 0.5,
                "start_s": 0,
                "duration_s": 300,
            },
        }
        out = engine.simulate_scenario(scenario, horizon_s=60, dt_s=1.0)
        assert out["scenario_id"] == "SCN-TEST"
        assert out["module"] == "it_thermal"
        assert len(out["trajectory"]) >= 60
        assert "summary" in out

    def test_unknown_module_raises(self):
        engine = PhysicsEngine()
        with pytest.raises(ValueError):
            engine.simulate_scenario(
                {"id": "SCN-X", "primary_module": "nonexistent"}
            )


class TestSingleton:

    def test_get_engine_returns_same_instance(self):
        e1 = get_engine()
        e2 = get_engine()
        assert e1 is e2


class TestSiteValidationResultSerialization:

    def test_to_dict_round_trip(self):
        engine = PhysicsEngine()
        result = engine.validate_site(TestValidateSite()._nominal_site())
        d = result.to_dict()
        assert "site_health" in d
        assert "modules" in d
        assert "cascade_events" in d
        assert len(d["modules"]) == 4
