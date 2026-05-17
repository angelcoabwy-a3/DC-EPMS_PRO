"""Tests for backend.telemetry_simulator (Sprint 5 C1).

Coverage:
  - Inventory loading from site_model.yml
  - Channel naming convention (component_id:metric)
  - Per-component-type channel coverage
  - Steady-state samples within Path C2 spec bounds
  - Determinism with seed
  - Anomaly injection with thermal_runaway, pump_cavitation,
    phase_imbalance, ups_drain, chiller_degraded
  - Anomaly auto-clear after duration_samples
  - Placeholder payload shape matches frontend SCHEMA_CHANNEL_INNOVATIONS
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backend.site_model import SiteModel
from backend.telemetry_simulator import (
    ANOMALY_PROFILES,
    PHASE1_BASELINES,
    REGION_PROFILES,
    TelemetrySimulator,
    build_placeholder_payload,
    reset_simulator,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SITE_YAML = PROJECT_ROOT / "config" / "site_model.yml"


@pytest.fixture
def site_model():
    sm = SiteModel(SITE_YAML)
    sm.load()
    return sm


@pytest.fixture
def sim(site_model):
    reset_simulator()
    return TelemetrySimulator(site_model, seed=42)


# ─────────────────────────────────────────────────────────────────────
#  Inventory loading
# ─────────────────────────────────────────────────────────────────────
def test_simulator_loads_inventory_from_site_model(sim):
    """Simulator must enumerate emitting components from site_model.yml."""
    assert sim.component_count > 0, "no components found"
    assert sim.channel_count > 0, "no channels derived"
    # Path C2 Phase 1 baseline: 50 racks + 3 chillers + 6 cdus + 2 ups
    # + 3 pumps + 2 cooling tower fields = 66 emitting components.
    # Channel total: 50*4 + 3*2 + 6*2 + 2*5 + 3*2 + 2*2 = 238.
    assert sim.component_count >= 60, f"expected >=60 emitting components, got {sim.component_count}"
    assert sim.channel_count >= 200, f"expected >=200 channels, got {sim.channel_count}"


def test_window_shape_matches_n_samples(sim):
    """Each channel array must have shape (n_samples,)."""
    n = 5
    window = sim.get_window(n_samples=n)
    for ch_id, arr in window.items():
        assert isinstance(arr, np.ndarray), f"{ch_id}: not ndarray"
        assert arr.shape == (n,), f"{ch_id}: shape {arr.shape}, expected ({n},)"
        assert arr.dtype == np.float64, f"{ch_id}: dtype {arr.dtype}"


def test_channel_id_format_is_component_scoped(sim):
    """Channel IDs must be '<component_id>:<metric>' to disambiguate."""
    window = sim.get_window(n_samples=1)
    for ch_id in window.keys():
        assert ":" in ch_id, f"channel id {ch_id!r} missing component scope"
        parts = ch_id.split(":")
        assert len(parts) == 2, f"channel id {ch_id!r} has unexpected format"


# ─────────────────────────────────────────────────────────────────────
#  Channel coverage per component type
# ─────────────────────────────────────────────────────────────────────
def test_it_rack_emits_thermal_quad_channels(sim):
    """Each it_rack must emit rack_inlet, gpu_Tj, dlc_supply, dlc_return."""
    window = sim.get_window(n_samples=1)
    rack_id = "rack_a_01_01"
    expected = {
        f"{rack_id}:rack_inlet_T_c",
        f"{rack_id}:gpu_Tj_c",
        f"{rack_id}:dlc_supply_T_c",
        f"{rack_id}:dlc_return_T_c",
    }
    actual_for_rack = {k for k in window if k.startswith(f"{rack_id}:")}
    assert actual_for_rack == expected, (
        f"rack channels mismatch: missing={expected - actual_for_rack}, "
        f"extra={actual_for_rack - expected}"
    )


def test_ups_emits_three_phase_voltage_phase1_schema(sim):
    """UPS emits triple-phase 480 VAC fields (vocabulary fence Phase 1)."""
    window = sim.get_window(n_samples=1)
    ups_id = "ups_a"
    phase_keys = {
        f"{ups_id}:voltage_v_phase_ab",
        f"{ups_id}:voltage_v_phase_bc",
        f"{ups_id}:voltage_v_phase_ca",
    }
    for k in phase_keys:
        assert k in window, f"missing Phase 1 schema field: {k}"
    # Vocabulary fence: NO dc_bus field on Phase 1 components
    assert f"{ups_id}:voltage_v_dc_bus" not in window, (
        "Phase 1 UPS must NOT emit dc_bus channel"
    )


def test_chiller_and_pump_channels_present(sim):
    """Mechanical components emit thermal + flow channels."""
    window = sim.get_window(n_samples=1)
    chiller_keys = [k for k in window if k.startswith("chiller_") and ":" in k]
    pump_keys = [k for k in window if k.startswith("chw_pump_") and ":" in k]
    assert len(chiller_keys) >= 6, "expected >=6 chiller channels (3 chillers * 2 metrics)"
    assert len(pump_keys) >= 6, "expected >=6 pump channels (3 pumps * 2 metrics)"


# ─────────────────────────────────────────────────────────────────────
#  Steady-state bounds
# ─────────────────────────────────────────────────────────────────────
def test_steady_state_within_path_c2_bounds(sim):
    """Random samples must stay within ~5 sigma of baseline."""
    window = sim.get_window(n_samples=20)
    rack_id = "rack_a_01_01"
    inlet = window[f"{rack_id}:rack_inlet_T_c"]
    mean, std = PHASE1_BASELINES["rack_inlet_T_c"]
    # 5 sigma bound: extremely unlikely any sample exits this range
    assert np.all(np.abs(inlet - mean) < 5 * std), (
        f"rack_inlet samples out of bounds: {inlet}"
    )
    # Sanity: gpu_Tj higher than rack inlet (workload heat)
    gpu = window[f"{rack_id}:gpu_Tj_c"]
    assert gpu.mean() > inlet.mean() + 20, "gpu_Tj should be markedly hotter than inlet"


# ─────────────────────────────────────────────────────────────────────
#  Determinism
# ─────────────────────────────────────────────────────────────────────
def test_deterministic_with_seed(site_model):
    """Two simulators with the same seed produce identical first window."""
    s1 = TelemetrySimulator(site_model, seed=12345)
    s2 = TelemetrySimulator(site_model, seed=12345)
    w1 = s1.get_window(n_samples=10)
    w2 = s2.get_window(n_samples=10)
    assert w1.keys() == w2.keys()
    for ch_id in w1:
        np.testing.assert_array_equal(w1[ch_id], w2[ch_id])


def test_different_seed_produces_different_samples(site_model):
    s1 = TelemetrySimulator(site_model, seed=1)
    s2 = TelemetrySimulator(site_model, seed=2)
    w1 = s1.get_window(n_samples=5)
    w2 = s2.get_window(n_samples=5)
    sample_ch = next(iter(w1.keys()))
    assert not np.array_equal(w1[sample_ch], w2[sample_ch])


# ─────────────────────────────────────────────────────────────────────
#  Anomaly injection
# ─────────────────────────────────────────────────────────────────────
def test_inject_thermal_runaway_visible_in_gpu_Tj(sim):
    """Injected thermal_runaway pushes gpu_Tj far above baseline."""
    rack_id = "rack_a_01_05"
    n_affected = sim.inject_anomaly(rack_id, "thermal_runaway", magnitude=1.0)
    assert n_affected >= 2, "thermal_runaway should affect >=2 channels (gpu_Tj, rack_inlet)"

    window = sim.get_window(n_samples=10)
    gpu = window[f"{rack_id}:gpu_Tj_c"]
    baseline_mean, baseline_std = PHASE1_BASELINES["gpu_Tj_c"]
    # Profile delta is +25 C; baseline mean 68 C -> expected ~93 C
    assert gpu.mean() > baseline_mean + 15, (
        f"gpu_Tj should be elevated under thermal_runaway, got mean={gpu.mean():.1f}"
    )


def test_inject_pump_cavitation_drops_npsh(sim):
    pump_id = "chw_pump_n_01"
    sim.inject_anomaly(pump_id, "pump_cavitation", magnitude=1.0)
    window = sim.get_window(n_samples=10)
    npsh = window[f"{pump_id}:pump_NPSH_margin_m"]
    baseline_mean, _ = PHASE1_BASELINES["pump_NPSH_margin_m"]
    # Profile delta -2.5 m: baseline 3.5 m -> expected ~1.0 m, possibly negative
    assert npsh.mean() < baseline_mean - 1.5, (
        f"NPSH should drop under pump_cavitation, got mean={npsh.mean():.2f}"
    )


def test_anomaly_auto_clears_after_duration(sim):
    """Anomaly persists for duration_samples then naturally clears."""
    rack_id = "rack_a_02_01"
    sim.inject_anomaly(rack_id, "thermal_runaway", magnitude=1.0, duration_samples=10)
    # With 5 samples per window, anomaly clears after 2 windows
    sim.get_window(n_samples=5)  # decrements remaining 10 -> 5
    sim.get_window(n_samples=5)  # decrements remaining 5 -> 0, expires
    # Third window should be back to normal
    window = sim.get_window(n_samples=10)
    gpu = window[f"{rack_id}:gpu_Tj_c"]
    baseline_mean, baseline_std = PHASE1_BASELINES["gpu_Tj_c"]
    assert abs(gpu.mean() - baseline_mean) < 5 * baseline_std, (
        f"after auto-clear, gpu_Tj should be back to baseline; got mean={gpu.mean():.1f}"
    )


def test_unknown_anomaly_kind_raises(sim):
    with pytest.raises(ValueError, match="unknown anomaly kind"):
        sim.inject_anomaly("rack_a_01_01", "rapture", magnitude=1.0)


def test_inject_on_non_emitting_component_returns_zero(sim):
    """Components like switchgear don't emit telemetry; inject is a no-op."""
    n = sim.inject_anomaly("switchgear_a", "phase_imbalance", magnitude=1.0)
    assert n == 0


# ─────────────────────────────────────────────────────────────────────
#  Placeholder payload (frontend contract)
# ─────────────────────────────────────────────────────────────────────
def test_placeholder_payload_matches_frontend_schema(sim):
    """build_placeholder_payload output must match SCHEMA_CHANNEL_INNOVATIONS."""
    window = sim.get_window(n_samples=5)
    payload = build_placeholder_payload(window)
    assert isinstance(payload, dict)
    assert len(payload) == len(window)
    # Inspect one entry's shape
    ch_id, fields = next(iter(payload.items()))
    expected_keys = {"n_emissions", "max_z", "mean_z", "is_anomalous", "last_emission"}
    assert set(fields.keys()) == expected_keys, (
        f"payload entry {ch_id} missing keys: {expected_keys - set(fields.keys())}"
    )
    assert fields["n_emissions"] == 5
    assert fields["max_z"] == 0.0  # C1 placeholder; C2 fills with real Kalman z
    assert fields["mean_z"] == 0.0
    assert fields["is_anomalous"] is False
    assert isinstance(fields["last_emission"], float)


def test_placeholder_payload_skips_empty_arrays():
    """Empty samples arrays must be skipped (defensive)."""
    window = {"empty:metric": np.array([], dtype=np.float64)}
    payload = build_placeholder_payload(window)
    assert "empty:metric" not in payload


# ─────────────────────────────────────────────────────────────────────
#  Anomaly profile validity
# ─────────────────────────────────────────────────────────────────────
def test_all_anomaly_profiles_target_known_metrics():
    """Every anomaly profile must reference metrics that exist in baselines.

    Genset synchronization metrics live in REGION_PROFILES (multi-region
    480V/60Hz + 416V/50Hz calibration), not PHASE1_BASELINES — so the
    known-metric set is the union of both.
    """
    region_metrics = {
        m for profile in REGION_PROFILES.values() for m in profile
    }
    known = set(PHASE1_BASELINES) | region_metrics
    for kind, profile in ANOMALY_PROFILES.items():
        for metric in profile.keys():
            assert metric in known, (
                f"anomaly {kind} targets metric {metric!r} "
                f"that is not in PHASE1_BASELINES or REGION_PROFILES"
            )
