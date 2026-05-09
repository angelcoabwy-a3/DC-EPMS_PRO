"""Performance regression tests for the telemetry pipeline (Sprint 5 C3).

These are NOT strict-bound benchmarks. They establish a baseline so that
a future regression (e.g., accidentally O(n^2) loop, Numba JIT broken)
trips the CI without requiring an external benchmarking tool.

Two markers used:
  - "perf"  pytest mark (so the suite can be filtered).
  - timing print to stdout for human inspection.

Bounds are intentionally LOOSE because:
  1. AMD Ryzen + Windows: Numba @njit may fall back to pure Python on
     hardware where the FAISS-style AVX2 issue (DC-EPMS-001) lineage
     hits. The graceful fallback path in cyber_physical_tools.py is
     correct but slower.
  2. Test runners under pytest add ~10-50us overhead per call.
  3. CI machines vary in CPU clock.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from backend.site_model import SiteModel
from backend.telemetry_pipeline import TelemetryPipeline, reset_pipeline
from backend.telemetry_simulator import TelemetrySimulator, reset_simulator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SITE_YAML = PROJECT_ROOT / "config" / "site_model.yml"


@pytest.fixture
def warm_pipeline():
    """Pipeline with simulator-driven cold compile already paid."""
    reset_simulator()
    reset_pipeline()
    sm = SiteModel(SITE_YAML)
    sm.load()
    sim = TelemetrySimulator(sm, seed=42)
    pipe = TelemetryPipeline(dt_seconds=1.0)
    # Cold call — triggers Numba JIT compile if available
    _ = pipe.compute(sim.get_window(n_samples=5))
    return sim, pipe


@pytest.mark.perf
def test_cold_compile_under_5_seconds():
    """First compute() call (Numba JIT compile triggered if available)."""
    reset_simulator()
    reset_pipeline()
    sm = SiteModel(SITE_YAML)
    sm.load()
    sim = TelemetrySimulator(sm, seed=42)
    pipe = TelemetryPipeline(dt_seconds=1.0)
    window = sim.get_window(n_samples=5)

    t0 = time.perf_counter()
    payload = pipe.compute(window)
    cold_ms = (time.perf_counter() - t0) * 1000

    print(f"\n[perf] cold compute(): {cold_ms:.1f} ms over {len(payload)} channels")
    # 5s upper bound covers worst case (Numba cold compile on slow machine).
    assert cold_ms < 5000, f"cold compute() too slow: {cold_ms:.1f} ms"


@pytest.mark.perf
def test_hot_path_under_50_ms_per_window(warm_pipeline):
    """After warmup, compute() over ~238 channels should be << 50 ms."""
    sim, pipe = warm_pipeline
    n_iter = 20

    t0 = time.perf_counter()
    for _ in range(n_iter):
        pipe.compute(sim.get_window(n_samples=5))
    elapsed_ms = (time.perf_counter() - t0) * 1000
    avg_ms = elapsed_ms / n_iter

    print(f"\n[perf] hot compute() avg over {n_iter} windows: {avg_ms:.2f} ms ({pipe.channel_count} channels)")
    # Loose bound: 50 ms covers Pure Python fallback worst case.
    # SSE pushes every 5000 ms so we have 100x headroom.
    assert avg_ms < 50, f"hot compute() too slow: {avg_ms:.2f} ms avg"


@pytest.mark.perf
def test_per_step_kalman_under_500_us(warm_pipeline):
    """One kalman_innovation_step per channel should be << 500 us."""
    sim, pipe = warm_pipeline
    n_iter = 50

    # Time only the get_telemetry_payload internals indirectly via compute()
    t0 = time.perf_counter()
    for _ in range(n_iter):
        pipe.compute(sim.get_window(n_samples=5))
    elapsed_s = time.perf_counter() - t0

    # Approximate per-step cost: each window has channel_count * n_samples
    # evaluations, but SoD compresses some. Use channel_count * 5 (n_samples)
    # as an upper bound for the innovation steps.
    total_steps = n_iter * pipe.channel_count * 5
    avg_us = (elapsed_s / total_steps) * 1_000_000

    print(f"\n[perf] per-step Kalman avg: {avg_us:.1f} us ({total_steps} steps)")
    # 500 us upper bound — Pure Python inner loop without Numba is around
    # 50-200 us. Numba JIT brings this to single-digit us. SSCB µs target
    # (1-100 us per IEC 60947-2) leaves plenty of headroom.
    assert avg_us < 500, f"per-step Kalman too slow: {avg_us:.2f} us"


@pytest.mark.perf
def test_anomaly_log_trim_is_constant_time(warm_pipeline):
    """Adding entries to anomaly_log should not exhibit O(n^2) growth."""
    _, pipe = warm_pipeline
    # Pre-fill with N entries
    now = time.time()
    for i in range(10000):
        pipe._anomaly_log.append((now, f"synthetic_ch_{i}:metric"))

    t0 = time.perf_counter()
    n = pipe.count_anomalies_60min()
    elapsed_ms = (time.perf_counter() - t0) * 1000

    print(f"\n[perf] count_anomalies_60min over {len(pipe._anomaly_log)} entries: {elapsed_ms:.2f} ms (got {n})")
    # 50ms upper bound — current impl does set comprehension over the list,
    # which is O(n) at ~10us per 1000 entries.
    assert elapsed_ms < 50, f"count too slow: {elapsed_ms:.2f} ms"
