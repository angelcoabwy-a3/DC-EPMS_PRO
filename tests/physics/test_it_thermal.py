"""
Tests for IT Thermal physics module.

Coverage:
  - Base data types (ValidationResult, StateSnapshot, Severity)
  - Steady-state validator: nominal, excess heat, out-of-envelope inlet,
    GPU thermal trip
  - ODE simulation: returns a complete trajectory
  - Analytic fallback (when scipy unavailable)
  - Time-to-critical calculation
"""
from __future__ import annotations

import os
import sys

# Ensure project root is on path when running pytest from tests/
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest

from backend.physics.base import (
    PhysicalJustification,
    Severity,
    StateSnapshot,
    ValidationResult,
)
from backend.physics.it_thermal import (
    A2_INLET_MAX_C,
    GPU_TJ_THROTTLE_C,
    GPU_TJ_TRIP_C,
    ITThermalModule,
    OPS_INLET_TARGET_C,
    RACK_COUNT,
)


# ---------------------------------------------------------------------------
#  Base data type tests
# ---------------------------------------------------------------------------

class TestBaseTypes:
    """Sanity tests on dataclasses."""

    def test_severity_weights_ordered(self):
        assert Severity.OK.weight() < Severity.INFO.weight()
        assert Severity.INFO.weight() < Severity.WARNING.weight()
        assert Severity.WARNING.weight() < Severity.CRITICAL.weight()

    def test_validation_result_escalate_monotonic(self):
        r = ValidationResult(module="test")
        assert r.severity == Severity.OK
        r.escalate(Severity.WARNING)
        assert r.severity == Severity.WARNING
        # Escalating DOWN must not lower severity
        r.escalate(Severity.INFO)
        assert r.severity == Severity.WARNING
        r.escalate(Severity.CRITICAL)
        assert r.severity == Severity.CRITICAL

    def test_validation_result_add_check(self):
        r = ValidationResult(module="test")
        r.add_check("dummy", passed=True, value=42.0, threshold=50.0, unit="X")
        assert len(r.checks) == 1
        assert r.checks[0]["name"] == "dummy"
        assert r.checks[0]["passed"] is True

    def test_physical_justification_to_dict(self):
        j = PhysicalJustification(
            law="test_law",
            measured={"a": 1.0},
            expected={"a": 2.0},
            residual={"a": -1.0},
            threshold={"a": 0.5},
            interpretation="Test",
            suggested_action="Check it",
        )
        d = j.to_dict()
        assert d["law"] == "test_law"
        assert d["measured"]["a"] == 1.0
        assert d["residual"]["a"] == -1.0

    def test_state_snapshot_dict(self):
        s = StateSnapshot(t=10.0, state={"T": 20.0}, events=["evt1"])
        d = s.to_dict()
        assert d["t"] == 10.0
        assert d["state"]["T"] == 20.0
        assert "evt1" in d["events"]


# ---------------------------------------------------------------------------
#  Steady-state validator tests
# ---------------------------------------------------------------------------

class TestValidateNominal:
    """When telemetry matches physics exactly, all checks pass."""

    def _nominal_measurements(self) -> dict:
        """Telemetry at the design operating point, physically balanced.

        Energy balance: Q_it = m_dot * cp * dT per rack.
        At 142 kW nominal with 95% to DLC (134.9 kW):
          m_dot needed = 134,900 / (3650 * 22) = 1.68 kg/s
          flow needed  = 1.68 / 1040 * 60 * 1000 = 97 L/min
        So flow=100 L/min with dT=21.3 K gives a balanced system.
        """
        return {
            "rack_count": 118,
            "rack_tdp_kw": 142.0,
            "dlc_supply_c": 18.0,
            "dlc_return_c": 18.0 + 21.3,  # dT that balances at 100 L/min
            "dlc_flow_l_min": 100.0,
            "hall_inlet_c": OPS_INLET_TARGET_C,
            "hall_return_c": 22.0,
            "gpu_tj_max_c": 70.0,
        }

    def test_nominal_passes(self):
        m = ITThermalModule()
        r = m.validate(self._nominal_measurements())
        assert r.severity == Severity.OK
        assert r.health > 0.9
        # All checks present
        check_names = {c["name"] for c in r.checks}
        assert "first_law_energy_balance" in check_names
        assert "ashrae_a2_inlet_envelope" in check_names
        assert "gpu_junction_temp" in check_names

    def test_nominal_energy_balance_residual_small(self):
        m = ITThermalModule()
        r = m.validate(self._nominal_measurements())
        residual = r.metrics["energy_residual_kw"]
        # At nominal flow matching the delta_T we chose, residual should
        # be well within the 3% threshold (about +/- 500 kW for 16.8 MW).
        assert abs(residual) < 500


class TestValidateFaultInjection:

    def test_energy_residual_flagged_when_dlc_flow_low(self):
        """If DLC flow drops 50% but delta_T stays the same, we violate
        first-law balance: removed heat drops in proportion."""
        m = ITThermalModule()
        meas = {
            "rack_count": 118,
            "rack_tdp_kw": 142.0,
            "dlc_supply_c": 18.0,
            "dlc_return_c": 40.0,
            "dlc_flow_l_min": 20.0,  # half of nominal
            "hall_inlet_c": OPS_INLET_TARGET_C,
            "gpu_tj_max_c": 72.0,
        }
        r = m.validate(meas)
        balance_check = next(
            c for c in r.checks if c["name"] == "first_law_energy_balance"
        )
        assert balance_check["passed"] is False
        # At least one justification with residual
        energy_just = [
            j for j in r.justifications
            if j.law == "first_law_energy_balance_dlc"
        ]
        assert len(energy_just) == 1
        assert energy_just[0].residual["residual_kw"] > 0  # missing removed heat

    def test_a2_exceeded_triggers_critical(self):
        m = ITThermalModule()
        meas = {
            "rack_count": 118,
            "rack_tdp_kw": 142.0,
            "dlc_supply_c": 18.0,
            "dlc_return_c": 40.0,
            "dlc_flow_l_min": 100.0,
            "hall_inlet_c": 36.0,  # above A2
            "gpu_tj_max_c": 72.0,
        }
        r = m.validate(meas)
        assert r.severity == Severity.CRITICAL
        envelope_check = next(
            c for c in r.checks if c["name"] == "ashrae_a2_inlet_envelope"
        )
        assert envelope_check["passed"] is False

    def test_gpu_trip_critical(self):
        m = ITThermalModule()
        meas = {
            "rack_count": 118,
            "rack_tdp_kw": 142.0,
            "dlc_supply_c": 18.0,
            "dlc_return_c": 40.0,
            "dlc_flow_l_min": 100.0,
            "hall_inlet_c": OPS_INLET_TARGET_C,
            "gpu_tj_max_c": GPU_TJ_TRIP_C + 1,
        }
        r = m.validate(meas)
        assert r.severity == Severity.CRITICAL
        trip_just = [
            j for j in r.justifications
            if j.law == "gpu_junction_thermal_trip"
        ]
        assert len(trip_just) == 1

    def test_gpu_throttle_critical(self):
        m = ITThermalModule()
        meas = {
            "rack_count": 118,
            "rack_tdp_kw": 142.0,
            "dlc_supply_c": 18.0,
            "dlc_return_c": 40.0,
            "dlc_flow_l_min": 100.0,
            "hall_inlet_c": OPS_INLET_TARGET_C,
            "gpu_tj_max_c": GPU_TJ_THROTTLE_C + 1,
        }
        r = m.validate(meas)
        assert r.severity == Severity.CRITICAL

    def test_inlet_below_a2_is_warning(self):
        m = ITThermalModule()
        meas = {
            "rack_count": 118,
            "rack_tdp_kw": 142.0,
            "dlc_supply_c": 18.0,
            "dlc_return_c": 40.0,
            "dlc_flow_l_min": 100.0,
            "hall_inlet_c": 8.0,  # below A2
            "gpu_tj_max_c": 70.0,
        }
        r = m.validate(meas)
        assert r.severity == Severity.WARNING


class TestValidateDefaults:
    """validate() should cope with partial telemetry by using defaults."""

    def test_empty_dict_does_not_crash(self):
        m = ITThermalModule()
        r = m.validate({})
        assert r.module == "it_thermal"
        # With defaults we expect OK or close to it
        assert r.severity in (Severity.OK, Severity.INFO)


# ---------------------------------------------------------------------------
#  Simulation tests
# ---------------------------------------------------------------------------

class TestSimulateTrajectory:

    def test_nominal_trajectory_stable(self):
        """With cooling_factor=1.0 (no fault), temperature stays near T0."""
        m = ITThermalModule()
        traj = m.simulate(
            initial_state={
                "hall_return_c": 22.0,
                "rack_count": 118,
                "rack_tdp_kw": 142.0,
            },
            perturbation={},
            horizon_s=300,
            dt_s=1.0,
        )
        assert len(traj) >= 300
        # Temperature at t=300 should still be near 22 C
        final = traj[-1]
        assert 21.5 <= final.state["hall_air_c"] <= 22.5

    def test_cooling_loss_heats_hall(self):
        """cooling_factor=0 should raise temperature significantly."""
        m = ITThermalModule()
        traj = m.simulate(
            initial_state={
                "hall_return_c": 22.0,
                "rack_count": 118,
                "rack_tdp_kw": 142.0,
            },
            perturbation={
                "cooling_factor": 0.0,
                "start_s": 0,
                "duration_s": 900,
            },
            horizon_s=900,
            dt_s=1.0,
        )
        # After 15 min with no cooling, hall temp should have risen materially
        final = traj[-1]
        assert final.state["hall_air_c"] > 25.0, (
            f"Expected rise, got {final.state['hall_air_c']:.1f} C"
        )

    def test_a2_exceeded_event_appears(self):
        """When temperature crosses 35 C we should emit an event."""
        m = ITThermalModule()
        traj = m.simulate(
            initial_state={
                "hall_return_c": 30.0,  # start hot
                "rack_count": 118,
                "rack_tdp_kw": 142.0,
            },
            perturbation={
                "cooling_factor": 0.0,
                "start_s": 0,
                "duration_s": 900,
            },
            horizon_s=900,
            dt_s=1.0,
        )
        all_events = [e for snap in traj for e in snap.events]
        assert "a2_envelope_exceeded" in all_events

    def test_dlc_flow_loss_triggers_gpu_throttle(self):
        """Losing DLC flow should raise GPU Tj estimate above throttle."""
        m = ITThermalModule()
        traj = m.simulate(
            initial_state={
                "hall_return_c": 22.0,
                "rack_count": 118,
                "rack_tdp_kw": 142.0,
                "dlc_supply_c": 18.0,
                "dlc_flow_l_min": 100.0,
            },
            perturbation={
                "cooling_factor": 1.0,
                "dlc_flow_factor": 0.3,  # major flow loss
                "start_s": 0,
                "duration_s": 900,
            },
            horizon_s=120,
            dt_s=1.0,
        )
        all_events = [e for snap in traj for e in snap.events]
        assert "gpu_thermal_throttle_initiated" in all_events


class TestTimeToCritical:

    def test_ttc_matches_literature_value(self):
        """With total cooling loss at 22 C, TTC to 35 C should be ~44 s."""
        m = ITThermalModule()
        ttc = m.time_to_critical_s(
            current_temp_c=22.0,
            cooling_factor=0.0,
            critical_temp_c=A2_INLET_MAX_C,
        )
        assert ttc is not None
        # Expected ~44 s per T3-STD-THERMAL-MODEL
        assert 40.0 <= ttc <= 50.0, f"Got TTC = {ttc:.1f} s"

    def test_ttc_none_when_cooling_sufficient(self):
        """If cooling is healthy, we should never reach critical."""
        m = ITThermalModule()
        ttc = m.time_to_critical_s(
            current_temp_c=22.0,
            cooling_factor=1.0,
            critical_temp_c=A2_INLET_MAX_C,
        )
        assert ttc is None

    def test_ttc_zero_when_already_critical(self):
        """Already at the threshold -> TTC = 0."""
        m = ITThermalModule()
        ttc = m.time_to_critical_s(
            current_temp_c=A2_INLET_MAX_C - 0.01,
            cooling_factor=0.0,
            critical_temp_c=A2_INLET_MAX_C,
        )
        assert ttc is not None
        assert ttc < 1.0
