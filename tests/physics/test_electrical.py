"""
Tests for Electrical physics module.

Coverage:
  - UPS efficiency curve (bell-shape)
  - Transformer loss model (C57.12 loading)
  - Battery voltage-SOC consistency
  - On-battery runtime calculation
  - ODE: utility loss -> discharge -> generator online
"""

from __future__ import annotations

from backend.physics.base import Severity
from backend.physics.electrical import (
    BATT_NOMINAL_VDC,
    UPS_ETA_DOUBLE_CONV_MAX,
    UPS_RATED_KW,
    XFMR_WINDING_MAX_C,
    ElectricalModule,
    _battery_voltage_from_soc,
    _transformer_losses_kw,
    _ups_efficiency,
)


class TestUPSEfficiencyCurve:
    def test_peak_efficiency_in_mid_load(self):
        """Efficiency should peak in the 30-90% load band."""
        eta_peak = _ups_efficiency(0.5, mode="online")
        eta_low = _ups_efficiency(0.03, mode="online")
        assert eta_peak > eta_low
        assert eta_peak == UPS_ETA_DOUBLE_CONV_MAX

    def test_econversion_higher_than_online(self):
        eta_econv = _ups_efficiency(0.5, mode="econversion")
        eta_online = _ups_efficiency(0.5, mode="online")
        assert eta_econv > eta_online

    def test_overload_reduces_efficiency(self):
        eta_normal = _ups_efficiency(0.8, mode="online")
        eta_overload = _ups_efficiency(1.1, mode="online")
        assert eta_overload < eta_normal

    def test_near_zero_load_floor(self):
        """Below 5% load, efficiency drops to floor."""
        eta_tiny = _ups_efficiency(0.02, mode="online")
        assert eta_tiny < 0.90
        assert eta_tiny > 0.85


class TestTransformerLosses:
    def test_no_load_losses_always_present(self):
        """At zero load, iron losses are still present."""
        loss = _transformer_losses_kw(0.0)
        assert loss > 0  # no-load / iron losses

    def test_losses_scale_with_load_squared(self):
        """Copper losses scale with I^2, so doubling load should
        more-than-double total losses (iron is constant)."""
        loss_low = _transformer_losses_kw(500.0)
        loss_high = _transformer_losses_kw(2_000.0)  # 4x load
        # Copper component scales 16x; iron component constant; total
        # should be well above 4x.
        assert loss_high > 4 * loss_low


class TestBatteryVoltageCurve:
    def test_full_soc_nominal_voltage(self):
        v = _battery_voltage_from_soc(1.0)
        assert abs(v - BATT_NOMINAL_VDC) < 1.0

    def test_voltage_decreases_with_soc(self):
        v_full = _battery_voltage_from_soc(1.0)
        v_half = _battery_voltage_from_soc(0.5)
        v_low = _battery_voltage_from_soc(0.2)
        assert v_full > v_half > v_low

    def test_collapse_near_empty(self):
        """Below 15% SOC, voltage should collapse rapidly."""
        v_mid = _battery_voltage_from_soc(0.2)
        v_empty = _battery_voltage_from_soc(0.05)
        assert v_empty < v_mid
        assert v_empty < 500  # well below nominal 540


class TestValidateNominal:
    def _nominal(self) -> dict:
        # UPS at 50% load gives peak efficiency (96% online)
        # Rated load = 600 kW, so 50% = 300 kW
        ups_load = 300.0
        eta_at_this_load = UPS_ETA_DOUBLE_CONV_MAX  # peak
        return {
            "utility_kw": 17_400.0,
            "facility_it_kw": 16_756.0,
            "ups_load_kw": ups_load,
            "ups_mode": "online",
            "ups_input_kw": ups_load / eta_at_this_load,
            "xfmr_load_kva": 1_800.0,  # ~72% of 2500 kVA
            "xfmr_top_oil_c": 65.0,
            "xfmr_winding_c": 25.0 + 40.0 + 65.0 * (1800 / 2500) ** 2,
            "battery_soc": 1.0,
            "battery_vdc": BATT_NOMINAL_VDC,
            "battery_on_load": False,
        }

    def test_nominal_ok(self):
        m = ElectricalModule()
        r = m.validate(self._nominal())
        assert r.severity in (Severity.OK, Severity.INFO)
        assert r.health > 0.9

    def test_nominal_metrics_complete(self):
        m = ElectricalModule()
        r = m.validate(self._nominal())
        assert "ups_efficiency_measured" in r.metrics
        assert "xfmr_losses_kw" in r.metrics
        assert "battery_soc" in r.metrics


class TestFaults:
    def _baseline(self):
        ups_load = 300.0
        return {
            "utility_kw": 17_400.0,
            "facility_it_kw": 16_756.0,
            "ups_load_kw": ups_load,
            "ups_mode": "online",
            "ups_input_kw": ups_load / UPS_ETA_DOUBLE_CONV_MAX,
            "xfmr_load_kva": 1_800.0,
            "xfmr_top_oil_c": 65.0,
            "xfmr_winding_c": 25.0 + 40.0 + 65.0 * (1800 / 2500) ** 2,
            "battery_soc": 1.0,
            "battery_vdc": BATT_NOMINAL_VDC,
            "battery_on_load": False,
        }

    def test_transformer_winding_overtemp_critical(self):
        """Winding at / above C57.12 limit -> critical severity."""
        m = ElectricalModule()
        meas = self._baseline()
        meas["xfmr_winding_c"] = XFMR_WINDING_MAX_C + 5.0
        r = m.validate(meas)
        wnd_check = next(c for c in r.checks if c["name"] == "transformer_winding_thermal_model")
        assert not wnd_check["passed"]
        assert r.severity == Severity.CRITICAL

    def test_ups_excess_losses_flagged(self):
        """UPS drawing more input than efficiency curve predicts -> detect."""
        m = ElectricalModule()
        meas = self._baseline()
        # Triple the input for same load => efficiency drops way below curve
        meas["ups_input_kw"] = 900.0
        r = m.validate(meas)
        eff_check = next(c for c in r.checks if c["name"] == "ups_efficiency_vs_curve")
        assert not eff_check["passed"]

    def test_battery_soc_voltage_mismatch(self):
        """Measured battery V doesn't match SOC expectation -> string fault."""
        m = ElectricalModule()
        meas = self._baseline()
        # Report 100% SOC but voltage is way low
        meas["battery_soc"] = 1.0
        meas["battery_vdc"] = 480.0
        r = m.validate(meas)
        batt_check = next(c for c in r.checks if c["name"] == "battery_voltage_soc_consistency")
        assert not batt_check["passed"]
        assert r.severity >= Severity.WARNING

    def test_on_battery_low_runtime_critical(self):
        """On battery with SOC 30% -> low runtime, but still OK (>5 min)."""
        m = ElectricalModule()
        meas = self._baseline()
        meas["battery_on_load"] = True
        meas["battery_soc"] = 0.3
        meas["battery_vdc"] = _battery_voltage_from_soc(0.3)
        r = m.validate(meas)
        rt_check = next(c for c in r.checks if c["name"] == "on_battery_runtime_remaining")
        # 12 min rated * 0.3 = 3.6 min -> below 5 min threshold
        assert not rt_check["passed"]
        assert r.severity == Severity.CRITICAL


class TestSimulate:
    def test_utility_fail_depletes_battery(self):
        """Utility fails at t=0, gen never starts -> SOC drops."""
        m = ElectricalModule()
        traj = m.simulate(
            initial_state={"battery_soc": 1.0, "ups_load_kw": UPS_RATED_KW},
            perturbation={
                "utility_fail": True,
                "start_s": 0,
                "generator_start_s": None,
                "load_kw": UPS_RATED_KW,
            },
            horizon_s=900,
            dt_s=1.0,
        )
        # After 15 min at full load, battery should be near empty
        final = traj[-1]
        assert final.state["battery_soc"] < 0.1, (
            f"SOC should be depleted, got {final.state['battery_soc']:.2f}"
        )
        events = [e for snap in traj for e in snap.events]
        assert "battery_low_warning" in events

    def test_generator_online_stops_discharge(self):
        """Utility fails, gen online at t=60s -> battery doesn't fully drain."""
        m = ElectricalModule()
        traj = m.simulate(
            initial_state={"battery_soc": 1.0, "ups_load_kw": UPS_RATED_KW},
            perturbation={
                "utility_fail": True,
                "start_s": 0,
                "generator_start_s": 60.0,
                "load_kw": UPS_RATED_KW,
            },
            horizon_s=900,
            dt_s=1.0,
        )
        # Before gen online at 60s, battery drains ~60/720 = 8%
        # After gen online, battery should recharge
        final = traj[-1]
        # After 14 min on generator (recharge at 5hr rate -> +5%),
        # we should see recovery above initial minimum
        assert final.state["battery_soc"] > 0.85
        events = [e for snap in traj for e in snap.events]
        assert "generator_online" in events

    def test_nominal_trajectory_complete(self):
        m = ElectricalModule()
        traj = m.simulate(
            initial_state={"battery_soc": 1.0, "ups_load_kw": 600.0},
            perturbation={"utility_fail": False},
            horizon_s=300,
            dt_s=1.0,
        )
        assert len(traj) >= 300
        # SOC should remain near 1.0
        assert traj[-1].state["battery_soc"] >= 0.99
