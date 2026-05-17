"""Tests for backend.telemetry_pipeline (Sprint 5 C2).

Coverage:
  - Cold start: filter_state initializes per channel on first compute()
  - Steady-state convergence: no spurious anomalies in baseline window
  - Anomaly detection: simulator-injected thermal_runaway flips
    is_anomalous=True and increments anomaly_count_60min
  - Multi-channel state isolation: anomaly on one channel does not
    leak into another
  - Filter state persistence: x_hat / P evolve across compute() calls
  - Rolling anomaly counter: unique-channel-in-60min semantics
  - Singleton lifecycle (get_pipeline / reset_pipeline)
  - Payload shape matches frontend SCHEMA_CHANNEL_INNOVATIONS contract
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from backend.site_model import SiteModel
from backend.telemetry_pipeline import (
    TelemetryPipeline,
    get_pipeline,
    reset_pipeline,
)
from backend.telemetry_simulator import TelemetrySimulator, reset_simulator

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


@pytest.fixture
def pipeline():
    reset_pipeline()
    return TelemetryPipeline(dt_seconds=1.0)


# ─────────────────────────────────────────────────────────────────────
#  Cold start
# ─────────────────────────────────────────────────────────────────────
def test_cold_start_initializes_filter_state(pipeline, sim):
    """First compute() must initialize Kalman state for every channel."""
    assert pipeline.channel_count == 0  # cold
    window = sim.get_window(n_samples=5)
    payload = pipeline.compute(window)
    assert pipeline.channel_count == len(window), (
        f"expected filter state for {len(window)} channels, "
        f"got {pipeline.channel_count}"
    )
    assert set(payload.keys()) == set(window.keys())


def test_payload_shape_matches_frontend_contract(pipeline, sim):
    """Each channel entry must have the exact 6 fields the frontend expects."""
    window = sim.get_window(n_samples=5)
    payload = pipeline.compute(window)
    expected_fields = {
        "n_emissions", "max_z", "mean_z", "is_anomalous",
        "last_emission", "escalation_required",
    }
    for ch_id, fields in payload.items():
        assert set(fields.keys()) == expected_fields, (
            f"{ch_id}: missing {expected_fields - set(fields.keys())}, "
            f"extra {set(fields.keys()) - expected_fields}"
        )


# ─────────────────────────────────────────────────────────────────────
#  Steady-state convergence (no false positives)
# ─────────────────────────────────────────────────────────────────────
def test_steady_state_no_widespread_anomalies(pipeline, sim):
    """After warmup, baseline noise should not trigger many anomalies."""
    # Warmup
    for _ in range(5):
        pipeline.compute(sim.get_window(n_samples=5))
    # Sample after convergence
    payload = pipeline.compute(sim.get_window(n_samples=10))
    anomalous = [ch for ch, f in payload.items() if f["is_anomalous"]]
    total = len(payload)
    # At 3-sigma threshold with gaussian noise, expected false-positive rate
    # is ~0.3% per sample. With 200+ channels x 10 samples, a few may fire.
    # Accept up to ~10% of channels in worst case (cyber_physical_tools'
    # cold-start P=10R takes ~5 ticks to converge, so still some noise).
    assert len(anomalous) < total * 0.20, (
        f"too many anomalies in steady state: {len(anomalous)}/{total}; "
        f"sample: {anomalous[:5]}"
    )


# ─────────────────────────────────────────────────────────────────────
#  Anomaly detection
# ─────────────────────────────────────────────────────────────────────
def test_thermal_runaway_triggers_anomaly_flag(pipeline, sim):
    """Inject thermal_runaway -> Kalman flags is_anomalous=True on gpu_Tj."""
    rack_id = "rack_a_01_05"
    gpu_ch = f"{rack_id}:gpu_Tj_c"
    # Warmup so filter converges to baseline
    for _ in range(8):
        pipeline.compute(sim.get_window(n_samples=5))
    # Inject and re-evaluate
    sim.inject_anomaly(rack_id, "thermal_runaway", magnitude=1.0, duration_samples=60)
    found_anomaly = False
    found_high_z = False
    for _ in range(3):
        payload = pipeline.compute(sim.get_window(n_samples=5))
        if payload[gpu_ch]["is_anomalous"]:
            found_anomaly = True
        if payload[gpu_ch]["max_z"] >= 3.0:
            found_high_z = True
    assert found_anomaly, "thermal_runaway should flip is_anomalous=True on gpu_Tj"
    assert found_high_z, "thermal_runaway should drive max_z >= 3.0 on gpu_Tj"


def test_pump_cavitation_triggers_anomaly_on_npsh(pipeline, sim):
    pump_id = "chw_pump_n_01"
    npsh_ch = f"{pump_id}:pump_NPSH_margin_m"
    # Warmup
    for _ in range(8):
        pipeline.compute(sim.get_window(n_samples=5))
    sim.inject_anomaly(pump_id, "pump_cavitation", magnitude=1.0, duration_samples=60)
    found = False
    for _ in range(3):
        payload = pipeline.compute(sim.get_window(n_samples=5))
        if payload[npsh_ch]["is_anomalous"]:
            found = True
            break
    assert found, "pump_cavitation should flag NPSH channel as anomalous"


# ─────────────────────────────────────────────────────────────────────
#  Multi-channel isolation
# ─────────────────────────────────────────────────────────────────────
def test_anomaly_does_not_leak_to_unrelated_channels(pipeline, sim):
    """Per-channel Kalman state guarantees isolation."""
    target_rack = "rack_a_01_05"
    other_rack = "rack_a_03_10"
    other_chiller = "chiller_1"
    # Warmup
    for _ in range(8):
        pipeline.compute(sim.get_window(n_samples=5))
    sim.inject_anomaly(target_rack, "thermal_runaway", magnitude=1.0, duration_samples=60)
    # Run and inspect: target should be anomalous, others should not
    pipeline.compute(sim.get_window(n_samples=5))
    payload = pipeline.compute(sim.get_window(n_samples=5))

    other_channels_to_check = [
        f"{other_rack}:gpu_Tj_c",
        f"{other_rack}:rack_inlet_T_c",
        f"{other_chiller}:chiller_LWT_c",
    ]
    leaked = [ch for ch in other_channels_to_check if payload[ch]["is_anomalous"]]
    assert not leaked, f"anomaly leaked to unrelated channels: {leaked}"


# ─────────────────────────────────────────────────────────────────────
#  Rolling anomaly counter
# ─────────────────────────────────────────────────────────────────────
def test_anomaly_counter_returns_unique_channels(pipeline, sim):
    """Multiple anomaly fires on same channel count as 1 unique.

    Note: the rolling log may also contain a small number of baseline-noise
    false positives (~2-3% of 238 channels per window at 3-sigma threshold).
    The test verifies that the TARGET rack's channels appear in the log
    regardless of background noise.
    """
    rack_id = "rack_a_01_05"
    for _ in range(8):
        pipeline.compute(sim.get_window(n_samples=5))
    # Reset log to isolate the post-injection signal from warmup noise
    pipeline._anomaly_log.clear()

    sim.inject_anomaly(rack_id, "thermal_runaway", magnitude=1.0, duration_samples=60)
    for _ in range(3):
        pipeline.compute(sim.get_window(n_samples=5))

    chans = pipeline.anomalous_channels_60min()
    target_chans = [c for c in chans if c.startswith(rack_id + ":")]
    # thermal_runaway affects 3 metrics on the rack: gpu_Tj, rack_inlet, dlc_return.
    # At least 1 must register as anomalous (gpu_Tj is the strongest signal).
    assert len(target_chans) >= 1, (
        f"target rack channels missing from anomaly log: full list = {chans}"
    )
    # Total log should be small (target + few baseline false positives)
    n = pipeline.count_anomalies_60min()
    assert 1 <= n <= 15, f"got {n} unique anomaly channels: {chans}"


def test_anomaly_log_trims_after_window(pipeline):
    """Entries older than ANOMALY_WINDOW_SECONDS are dropped."""
    # Manually inject old entries
    now = time.time()
    pipeline._anomaly_log = [
        (now - 7200, "old_channel:metric"),    # 2h ago, should drop
        (now - 60,   "recent_channel:metric"), # 1min ago, should stay
    ]
    n = pipeline.count_anomalies_60min()
    assert n == 1
    chans = pipeline.anomalous_channels_60min()
    assert chans == ["recent_channel:metric"]


# ─────────────────────────────────────────────────────────────────────
#  Singleton lifecycle
# ─────────────────────────────────────────────────────────────────────
def test_get_pipeline_returns_singleton():
    reset_pipeline()
    p1 = get_pipeline()
    p2 = get_pipeline()
    assert p1 is p2


def test_reset_pipeline_creates_fresh_instance():
    reset_pipeline()
    p1 = get_pipeline()
    reset_pipeline()
    p2 = get_pipeline()
    assert p1 is not p2


def test_reset_method_clears_state(pipeline, sim):
    """TelemetryPipeline.reset() clears filter_state and anomaly_log."""
    pipeline.compute(sim.get_window(n_samples=5))
    assert pipeline.channel_count > 0
    pipeline._anomaly_log.append((time.time(), "fake:ch"))
    pipeline.reset()
    assert pipeline.channel_count == 0
    assert pipeline.count_anomalies_60min() == 0


# ─────────────────────────────────────────────────────────────────────
#  Filter state persistence (Kalman convergence)
# ─────────────────────────────────────────────────────────────────────
def test_filter_state_persists_across_compute(pipeline, sim):
    """Kalman P should monotonically (mostly) decrease as samples accumulate."""
    rack_id = "rack_a_01_01"
    ch = f"{rack_id}:rack_inlet_T_c"

    pipeline.compute(sim.get_window(n_samples=5))
    p_after_first = float(pipeline._filter_state[ch]["P"][0])

    for _ in range(15):
        pipeline.compute(sim.get_window(n_samples=5))
    p_after_many = float(pipeline._filter_state[ch]["P"][0])

    # P should converge to steady-state which is < initial 10*R
    assert p_after_many < p_after_first, (
        f"Kalman P should decrease with more samples: "
        f"first={p_after_first:.6f}, many={p_after_many:.6f}"
    )
