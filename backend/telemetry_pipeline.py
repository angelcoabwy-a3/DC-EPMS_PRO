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
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from backend.cyber_physical_tools import get_telemetry_payload

log = logging.getLogger(__name__)

DEFAULT_DT_SECONDS = 1.0
ANOMALY_WINDOW_SECONDS = 3600  # 60 minutes

# ── Incident escalation triage ──────────────────────────────────────────
# Metrics whose anomalies are CRITICAL physics events — generator bus
# desynchronization and CDU secondary-loop flow starvation. When the
# Kalman z-score flags one of these channels as anomalous, compute()
# sets the per-channel `escalation_required` flag so the predictive WO
# trigger routes the work order to the Level V/VI queue (not Level IV).
CRITICAL_ESCALATION_METRICS: frozenset = frozenset({
    "genset_phase_angle_deg",
    "genset_freq_hz",
    "genset_breaker_status",
    "cdu_flow_lpm",
    "cdu_filter_dp_kpa",
})


def requires_escalation(channel_id: str) -> bool:
    """True if `channel_id`'s metric is a critical-escalation metric.

    channel_id is the scoped '<component>:<metric>' form; the metric is
    the segment after the last ':'.
    """
    metric = channel_id.split(":", 1)[-1] if ":" in channel_id else channel_id
    return metric in CRITICAL_ESCALATION_METRICS

# Channel calibration is loaded from config/telemetry_channels.yml at
# pipeline init. Hardcoded fallbacks below are used ONLY when the YAML
# is missing or malformed (defensive — Sprint 5 C3 made the YAML the
# canonical source of truth).
_FALLBACK_DEFAULTS: dict[str, float] = {
    "R": 0.0025,
    "Q": 0.0001,
    "F": 1.0,
    "sod_threshold_k": 0.5,
}


# ─────────────────────────────────────────────────────────────────────
#  Channel calibration config (Sprint 5 C3)
# ─────────────────────────────────────────────────────────────────────
class TelemetryChannelConfig:
    """YAML-backed per-channel R, Q, F, sod_threshold_k calibration.

    Public:
        TelemetryChannelConfig.load(path) -> TelemetryChannelConfig
        config.get(metric, "R", fallback=...) -> float
        config.metrics_with_calibration() -> set[str]

    The metric key is the simulator metric name (e.g. "gpu_Tj_c"), NOT
    the scoped channel id. Calibration is shared across all components
    emitting that metric type.
    """

    def __init__(self, defaults: dict[str, float], channels: dict[str, dict]):
        self._defaults = {**_FALLBACK_DEFAULTS, **defaults}
        self._channels = channels

    @classmethod
    def load(cls, yaml_path: Path) -> TelemetryChannelConfig:
        if not yaml_path.exists():
            log.warning(
                "[telemetry_pipeline] config %s not found; using fallback defaults",
                yaml_path,
            )
            return cls(defaults={}, channels={})
        try:
            with open(yaml_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            log.error("[telemetry_pipeline] YAML parse error in %s: %s", yaml_path, e)
            return cls(defaults={}, channels={})

        defaults = data.get("defaults", {}) or {}
        channels = data.get("channels", {}) or {}
        if not isinstance(defaults, dict) or not isinstance(channels, dict):
            log.error("[telemetry_pipeline] %s schema invalid (defaults/channels not mappings)", yaml_path)
            return cls(defaults={}, channels={})
        log.info(
            "[telemetry_pipeline] loaded calibration: %d explicit channels, defaults=%s",
            len(channels),
            {k: defaults.get(k, _FALLBACK_DEFAULTS[k]) for k in ("R", "Q", "F")},
        )
        return cls(defaults=defaults, channels=channels)

    def get(self, metric: str, key: str, fallback: float | None = None) -> float:
        ch = self._channels.get(metric, {})
        if isinstance(ch, dict) and key in ch:
            return float(ch[key])
        if key in self._defaults:
            return float(self._defaults[key])
        if fallback is not None:
            return float(fallback)
        return float(_FALLBACK_DEFAULTS[key])

    def metrics_with_calibration(self) -> set[str]:
        return set(self._channels.keys())


class TelemetryPipeline:
    """Owns the Kalman filter state across SSE ticks + anomaly log."""

    def __init__(
        self,
        dt_seconds: float = DEFAULT_DT_SECONDS,
        config: TelemetryChannelConfig | None = None,
    ):
        self.dt_seconds = float(dt_seconds)
        # filter_state is mutated in place by get_telemetry_payload
        self._filter_state: dict[str, Any] = {}
        # anomaly_log entries: (timestamp_unix, channel_id)
        self._anomaly_log: list[tuple[float, str]] = []
        # escalation_log: anomalies on CRITICAL_ESCALATION_METRICS channels
        self._escalation_log: list[tuple[float, str]] = []
        self._anomaly_window_s = ANOMALY_WINDOW_SECONDS
        # Per-channel calibration. If not supplied, auto-load the default
        # config/telemetry_channels.yml so direct instantiation in tests
        # gets proper R/Q/F calibration (not bare _FALLBACK_DEFAULTS).
        if config is None:
            try:
                config = TelemetryChannelConfig.load(_resolve_default_config_path())
            except Exception as e:
                log.warning("[telemetry_pipeline] auto-load failed: %s; using fallbacks", e)
                config = TelemetryChannelConfig(defaults={}, channels={})
        self._config = config

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

        # Track anomalies for rolling-window count + escalation triage.
        now = time.time()
        for ch_id, fields in payload.items():
            if not fields.get("is_anomalous"):
                fields["escalation_required"] = False
                continue
            self._anomaly_log.append((now, ch_id))
            # Critical physics anomaly -> escalate the WO to the L5/L6 queue.
            escalate = requires_escalation(ch_id)
            fields["escalation_required"] = escalate
            if escalate:
                self._escalation_log.append((now, ch_id))

        self._trim_anomaly_log(now)
        self._trim_escalation_log(now)
        return payload

    def count_escalations_60min(self) -> int:
        """Count CRITICAL anomalies in the rolling 60-min window. A non-zero
        value means at least one work order belongs in the Level V/VI queue."""
        self._trim_escalation_log(time.time())
        return len(self._escalation_log)

    def _trim_escalation_log(self, now: float) -> None:
        cutoff = now - self._anomaly_window_s
        self._escalation_log = [e for e in self._escalation_log if e[0] >= cutoff]

    # ── filter state pre-init (Sprint 5 C3 — YAML-driven calibration) ──
    def _init_filter_state_for_new_channels(self, window: dict[str, np.ndarray]) -> None:
        """Cold-start each new channel using config/telemetry_channels.yml.

        Config supplies R (measurement noise variance), Q (process noise),
        and F (state transition coefficient, default 1.0 = random walk
        for stationary signals). cyber_physical_tools defaults are
        bypassed because they were calibrated only for PT100 thermal
        channels with exponential decay models — wrong shape for our
        mixed simulator (voltage / pressure / flow / weather).
        """
        for ch_id, samples in window.items():
            if ch_id in self._filter_state:
                continue
            if samples.size == 0:
                continue
            metric = ch_id.split(":", 1)[-1] if ":" in ch_id else ch_id
            R = self._config.get(metric, "R")
            Q = self._config.get(metric, "Q")
            F = self._config.get(metric, "F")
            first = float(samples[0])
            self._filter_state[ch_id] = {
                "x_hat":        np.array([first], dtype=np.float64),
                "P":            np.array([10.0 * R], dtype=np.float64),
                "Q":            Q,
                "R":            R,
                "F":            F,
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

# Default config path resolves relative to project root. Callers can
# pass an explicit path to get_pipeline() or load it themselves.
_DEFAULT_CONFIG_PATH_PARTS = ("config", "telemetry_channels.yml")


def _resolve_default_config_path() -> Path:
    # backend/telemetry_pipeline.py -> project root is parent.parent
    return Path(__file__).resolve().parent.parent.joinpath(*_DEFAULT_CONFIG_PATH_PARTS)


def get_pipeline(
    dt_seconds: float = DEFAULT_DT_SECONDS,
    config_path: Path | None = None,
) -> TelemetryPipeline:
    """Lazy singleton. Subsequent calls ignore parameters (use first call's)."""
    global _pipeline
    if _pipeline is None:
        path = config_path or _resolve_default_config_path()
        config = TelemetryChannelConfig.load(path)
        _pipeline = TelemetryPipeline(dt_seconds=dt_seconds, config=config)
        log.info("[telemetry_pipeline] initialized (dt=%.2fs, config=%s)", dt_seconds, path)
    return _pipeline


def reset_pipeline() -> None:
    """Test helper — discard the singleton."""
    global _pipeline
    _pipeline = None
