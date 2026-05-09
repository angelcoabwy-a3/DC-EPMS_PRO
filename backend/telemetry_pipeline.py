"""
telemetry_pipeline.py — Sprint 5 Bite C2.

Glue between telemetry_simulator (raw per-channel sample windows) and
cyber_physical_tools (Kalman + Send-on-Delta innovation extraction).

Replaces telemetry_simulator.build_placeholder_payload (which emitted
hardcoded {max_z=0, is_anomalous=False}) with REAL innovation residuals
computed by cyber_physical_tools.get_telemetry_payload.

Public API:

    from telemetry_pipeline import get_pipeline
    pipeline = get_pipeline()
    payload = pipeline.compute(window)
    n_anom = pipeline.count_anomalies_60min()

The pipeline owns a process-singleton filter_state dict that persists
the per-channel Kalman state (x_hat, P, Q, R, F, H, last_emitted)
across SSE messages. The cyber_physical_tools module mutates this
dict in place; the pipeline merely owns its lifecycle.

Anomaly rolling window:
  Every channel that fires is_anomalous=True in a compute() call gets
  logged with (timestamp, channel_id). count_anomalies_60min() returns
  the number of UNIQUE channels that have fired in the last 3600s.
  The frontend Activity Strip subscribes to this count via the SSE
  payload's anomaly_count_60min field (wired in main.py).

Known limitation inherited from cyber_physical_tools.py:
  SEND_ON_DELTA_K is a single fixed scalar (0.5 K) applied to ALL
  channels regardless of physical units. Thermal channels compress
  well at steady state (~12x); voltage / pressure channels barely
  compress because their noise std is much larger than 0.5. Sprint 5
  Bite C3 introduces config/telemetry_channels.yml for per-channel
  Q, R, F, and SoD threshold tuning.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

from backend.cyber_physical_tools import get_telemetry_payload

log = logging.getLogger(__name__)

DEFAULT_DT_SECONDS = 1.0
ANOMALY_WINDOW_SECONDS = 3600  # 60 minutes

# Per-metric process noise Q. Mirrors cyber_physical_tools tuning notes
# (lines 287-313). Channels not listed here use DEFAULT_Q. C3 replaces
# this with config/telemetry_channels.yml.
_PROCESS_NOISE_Q: dict[str, float] = {
    "gpu_Tj_c":            1e-2,   # workload-driven spikes
    "outdoor_wet_bulb_c":  1e-2,   # weather-driven
    "rack_inlet_T_c":      1e-3,
    "ups_soc_pct":         1e-3,
    "batt_runtime_min":    1e-3,
    "voltage_v_phase_ab":  1e-3,
    "voltage_v_phase_bc":  1e-3,
    "voltage_v_phase_ca":  1e-3,
    "cdu_flow_lpm":        1e-3,
    "pump_flow_gpm":       1e-3,
}
_DEFAULT_Q = 1e-4
_FALLBACK_R = 0.05 ** 2  # PT100 noise variance, used when metric not in baselines


class TelemetryPipeline:
    """Owns the Kalman filter state across SSE ticks + anomaly log."""

    def __init__(self, dt_seconds: float = DEFAULT_DT_SECONDS):
        self.dt_seconds = float(dt_seconds)
        # filter_state is mutated in place by get_telemetry_payload
        self._filter_state: dict[str, Any] = {}
        # anomaly_log entries: (timestamp_unix, channel_id)
        self._anomaly_log: list[tuple[float, str]] = []
        self._anomaly_window_s = ANOMALY_WINDOW_SECONDS

    # ── compute ────────────────────────────────────────────────────────
    def compute(self, window: dict[str, np.ndarray]) -> dict[str, dict]:
        """Run a sample window through SoD + Kalman.

        Returns the channel_innovations payload that the SSE endpoint
        emits and the frontend Activity Strip consumes.
        """
        # Pre-initialize filter state for any new channel using the
        # simulator's baseline std as R (=noise variance). Bypasses
        # cyber_physical_tools' hard-coded R=0.05^2 cold start which
        # only calibrates for PT100 thermal channels and produces
        # massive false positives on voltage / pressure / flow channels
        # whose native std is orders of magnitude larger.
        self._init_filter_state_for_new_channels(window)

        payload = get_telemetry_payload(
            channel_window=window,
            filter_state=self._filter_state,
            delta_t_seconds=self.dt_seconds,
        )

        # Track anomalies for rolling-window count
        now = time.time()
        for ch_id, fields in payload.items():
            if fields.get("is_anomalous"):
                self._anomaly_log.append((now, ch_id))

        self._trim_anomaly_log(now)
        return payload

    # ── filter state pre-init (channel-aware R/Q, F=1 stationary) ──────
    def _init_filter_state_for_new_channels(self, window: dict[str, np.ndarray]) -> None:
        """Cold-start each channel using simulator baseline std as R.

        Model choice F=1.0 (random walk): cyber_physical_tools defaults
        to F=exp(-dt/60) which expects exponential decay toward zero.
        Our simulator emits STATIONARY signals around a constant
        baseline (UPS at 480 V is not decaying). With F<1 the Kalman
        x_hat converges to a non-physical equilibrium between decay
        and observation, producing huge spurious z-scores. F=1 makes
        the filter a random walk tracker that follows the observed
        baseline correctly.
        """
        # Lazy import to avoid circular dep at module load time
        from backend.telemetry_simulator import PHASE1_BASELINES

        for ch_id, samples in window.items():
            if ch_id in self._filter_state:
                continue
            if samples.size == 0:
                continue
            metric = ch_id.split(":", 1)[-1] if ":" in ch_id else ch_id
            if metric in PHASE1_BASELINES:
                _, std = PHASE1_BASELINES[metric]
                R = float(std) ** 2
            else:
                R = _FALLBACK_R
            Q = _PROCESS_NOISE_Q.get(metric, _DEFAULT_Q)
            first = float(samples[0])
            self._filter_state[ch_id] = {
                "x_hat":        np.array([first], dtype=np.float64),
                "P":            np.array([10.0 * R], dtype=np.float64),
                "Q":            Q,
                "R":            R,
                "F":            1.0,   # random-walk tracker for stationary signals
                "H":            1.0,
                "last_emitted": np.array([first], dtype=np.float64),
            }

    # ── anomaly rolling window ─────────────────────────────────────────
    def _trim_anomaly_log(self, now: float | None = None) -> None:
        if now is None:
            now = time.time()
        cutoff = now - self._anomaly_window_s
        # Keep only entries within the window
        self._anomaly_log = [(t, c) for t, c in self._anomaly_log if t >= cutoff]

    def count_anomalies_60min(self) -> int:
        """Unique channels that fired is_anomalous in the last 60 min."""
        self._trim_anomaly_log()
        return len({c for _, c in self._anomaly_log})

    def anomalous_channels_60min(self) -> list[str]:
        """Sorted list of unique channels that fired in the last 60 min."""
        self._trim_anomaly_log()
        return sorted({c for _, c in self._anomaly_log})

    # ── lifecycle ──────────────────────────────────────────────────────
    @property
    def channel_count(self) -> int:
        """Number of channels currently tracked in filter state."""
        return len(self._filter_state)

    def reset(self) -> None:
        """Discard filter state + anomaly log. Tests use this between cases."""
        self._filter_state.clear()
        self._anomaly_log.clear()


# ─────────────────────────────────────────────────────────────────────
#  Module-level singleton
# ─────────────────────────────────────────────────────────────────────
_pipeline: TelemetryPipeline | None = None


def get_pipeline(dt_seconds: float = DEFAULT_DT_SECONDS) -> TelemetryPipeline:
    """Lazy singleton. Subsequent calls ignore dt_seconds (use first call's)."""
    global _pipeline
    if _pipeline is None:
        _pipeline = TelemetryPipeline(dt_seconds=dt_seconds)
        log.info("[telemetry_pipeline] initialized (dt=%.2fs)", dt_seconds)
    return _pipeline


def reset_pipeline() -> None:
    """Test helper — discard the singleton."""
    global _pipeline
    _pipeline = None
