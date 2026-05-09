"""Tests for backend.telemetry_pipeline.TelemetryChannelConfig (Sprint 5 C3).

Coverage:
  - Load production config/telemetry_channels.yml successfully.
  - All simulator metrics present in PHASE1_BASELINES are calibrated.
  - Per-channel get() returns explicit values when present.
  - Falls back to defaults section when channel-key missing.
  - Falls back to module fallback constants when defaults section missing.
  - Missing YAML file does not raise (logs warning, returns empty config).
  - Malformed YAML does not raise (logs error, returns empty config).
  - Schema-invalid YAML (defaults not a mapping) handled defensively.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.telemetry_pipeline import TelemetryChannelConfig, _FALLBACK_DEFAULTS
from backend.telemetry_simulator import PHASE1_BASELINES

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROD_CONFIG = PROJECT_ROOT / "config" / "telemetry_channels.yml"


# ─────────────────────────────────────────────────────────────────────
#  Production config sanity
# ─────────────────────────────────────────────────────────────────────
def test_prod_config_loads_clean():
    cfg = TelemetryChannelConfig.load(PROD_CONFIG)
    explicit = cfg.metrics_with_calibration()
    assert len(explicit) >= 15, f"expected calibration for >=15 metrics, got {len(explicit)}"


def test_every_simulator_metric_has_calibration():
    """Every metric in PHASE1_BASELINES must have explicit YAML calibration."""
    cfg = TelemetryChannelConfig.load(PROD_CONFIG)
    explicit = cfg.metrics_with_calibration()
    missing = set(PHASE1_BASELINES.keys()) - explicit
    assert not missing, f"PHASE1_BASELINES metrics missing YAML calibration: {missing}"


def test_R_values_match_simulator_std_squared():
    """For each calibrated metric, R should equal std^2 from PHASE1_BASELINES."""
    cfg = TelemetryChannelConfig.load(PROD_CONFIG)
    for metric, (mean, std) in PHASE1_BASELINES.items():
        expected_R = std ** 2
        actual_R = cfg.get(metric, "R")
        assert abs(actual_R - expected_R) < 1e-6, (
            f"{metric}: R={actual_R} but expected std^2={expected_R} (std={std})"
        )


def test_F_is_one_for_all_calibrated_channels():
    """Random-walk model: F=1.0 for every channel (DC-EPMS-037 mitigation)."""
    cfg = TelemetryChannelConfig.load(PROD_CONFIG)
    for metric in cfg.metrics_with_calibration():
        F = cfg.get(metric, "F")
        # Per-metric F not set in YAML; should fall back to defaults.F = 1.0
        assert F == 1.0, f"{metric}: F={F}, expected 1.0 (random walk)"


def test_Q_within_reasonable_bounds():
    """Q should be in [1e-5, 1e-1] for all calibrated channels."""
    cfg = TelemetryChannelConfig.load(PROD_CONFIG)
    for metric in cfg.metrics_with_calibration():
        Q = cfg.get(metric, "Q")
        assert 1e-5 <= Q <= 1e-1, f"{metric}: Q={Q} out of reasonable range"


# ─────────────────────────────────────────────────────────────────────
#  get() lookup hierarchy
# ─────────────────────────────────────────────────────────────────────
def test_explicit_channel_value_wins_over_default():
    cfg = TelemetryChannelConfig(
        defaults={"R": 0.0025, "Q": 0.0001, "F": 1.0},
        channels={"foo_metric": {"R": 99.0}},
    )
    assert cfg.get("foo_metric", "R") == 99.0
    assert cfg.get("foo_metric", "Q") == 0.0001  # falls to defaults


def test_default_used_when_channel_missing_metric():
    cfg = TelemetryChannelConfig(
        defaults={"R": 0.5, "Q": 0.01, "F": 1.0},
        channels={},
    )
    assert cfg.get("unlisted_metric", "R") == 0.5
    assert cfg.get("unlisted_metric", "Q") == 0.01


def test_fallback_used_when_defaults_missing_key():
    cfg = TelemetryChannelConfig(defaults={"R": 0.5}, channels={})
    # "Q" not in defaults; falls to _FALLBACK_DEFAULTS["Q"]
    assert cfg.get("any_metric", "Q") == _FALLBACK_DEFAULTS["Q"]
    assert cfg.get("any_metric", "F") == _FALLBACK_DEFAULTS["F"]


# ─────────────────────────────────────────────────────────────────────
#  Defensive loading
# ─────────────────────────────────────────────────────────────────────
def test_missing_yaml_returns_empty_config():
    cfg = TelemetryChannelConfig.load(Path("/does/not/exist/telemetry_channels.yml"))
    assert cfg.metrics_with_calibration() == set()
    # Defaults should still resolve to fallback constants
    assert cfg.get("any", "R") == _FALLBACK_DEFAULTS["R"]


def test_malformed_yaml_returns_empty_config(tmp_path):
    bad = tmp_path / "bad.yml"
    bad.write_text("defaults: [this, is, a, list, not, a, mapping\n", encoding="utf-8")
    cfg = TelemetryChannelConfig.load(bad)
    assert cfg.metrics_with_calibration() == set()


def test_invalid_schema_returns_empty_config(tmp_path):
    """defaults / channels must be mappings; lists are rejected."""
    bad = tmp_path / "schema.yml"
    bad.write_text("defaults:\n  - 1\n  - 2\nchannels:\n  - 3\n", encoding="utf-8")
    cfg = TelemetryChannelConfig.load(bad)
    assert cfg.metrics_with_calibration() == set()


def test_empty_yaml_file_returns_empty_config(tmp_path):
    bad = tmp_path / "empty.yml"
    bad.write_text("", encoding="utf-8")
    cfg = TelemetryChannelConfig.load(bad)
    assert cfg.metrics_with_calibration() == set()
