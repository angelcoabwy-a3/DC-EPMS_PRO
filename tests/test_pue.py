"""Tests for backend.physics.pue (Sprint 5.5b).

Coverage:
  - PUEConfig loads expected schema
  - first_law_residual_pct math + edge cases
  - classify_first_law thresholds
  - classify_pue_state for all bands incl. design-target
  - compute_pue_for_phase produces deterministic baselines
  - Phase 1 baseline lands in audit_grade band
  - Phase 2 design target marked is_design_target=true
  - Demo noise stays inside the configured envelope
  - Error path: phase fractions summing >= 1.0 raises ValueError
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.physics.pue import (
    PUEConfig,
    classify_first_law,
    classify_pue_state,
    compute_pue_both_phases,
    compute_pue_for_phase,
    first_law_residual_pct,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "pue_targets.yml"


@pytest.fixture(scope="module")
def cfg() -> PUEConfig:
    return PUEConfig.load(CONFIG_PATH)


# ─── Config ───────────────────────────────────────────────────────────
def test_config_loads_both_phases(cfg):
    p1 = cfg.phase("phase_1")
    p2 = cfg.phase("phase_2")
    assert p1["target_pue"] == 1.30
    assert p2["target_pue"] == 1.15
    assert p1["voltage_class"].startswith("480 VAC")
    assert "800 VDC" in p2["voltage_class"]
    assert p1["rack_count"] == 118
    assert p2["rack_count"] == 250


def test_config_unknown_phase_raises(cfg):
    with pytest.raises(ValueError, match="unknown phase"):
        cfg.phase("phase_3")


def test_config_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        PUEConfig(Path("nonexistent.yml"))


# ─── first-law residual ────────────────────────────────────────────────
def test_residual_zero_when_inputs_match():
    assert first_law_residual_pct(1000.0, 1000.0) == 0.0


def test_residual_handles_zero_input():
    assert first_law_residual_pct(0.0, 0.0) == 0.0


def test_residual_pct_sign_independent():
    a = first_law_residual_pct(1000.0, 1050.0)
    b = first_law_residual_pct(1000.0,  950.0)
    assert a == b == 5.0


def test_classify_first_law_bands(cfg):
    th = cfg.first_law_thresholds
    assert classify_first_law(0.5, th) == "audit_grade"
    assert classify_first_law(2.0, th) == "audit_grade"   # boundary
    assert classify_first_law(3.0, th) == "acceptable"
    assert classify_first_law(5.0, th) == "acceptable"    # boundary
    assert classify_first_law(7.5, th) == "instrumentation_drift"


# ─── PUE state classifier ─────────────────────────────────────────────
def test_classify_pue_good_warn_crit():
    assert classify_pue_state(1.20, 1.30, 1.45, 1.60) == "good"
    assert classify_pue_state(1.50, 1.30, 1.45, 1.60) == "warn"
    assert classify_pue_state(1.70, 1.30, 1.45, 1.60) == "crit"


def test_classify_pue_design_target_overrides():
    # Even a "good" PUE returns 'design' when is_design_target=True
    assert classify_pue_state(1.10, 1.15, 1.25, 1.40, is_design_target=True) == "design"


# ─── Phase 1 compute (deployed) ───────────────────────────────────────
def test_phase_1_no_noise_baseline(cfg):
    snap = compute_pue_for_phase(
        "phase_1", cfg, is_design_target=False, add_demo_noise=False,
    )
    # 118 racks * 142 kW = 16,756 kW IT
    assert snap.breakdown.it_load_kw == 16_756.0
    # PUE = 1 / (1 - cooling_frac - elec_frac - aux_frac)
    # = 1 / (1 - 0.18 - 0.06 - 0.005) = 1 / 0.755 ≈ 1.324
    assert 1.31 < snap.pue < 1.34
    assert snap.target_pue == 1.30
    assert snap.state == "good"
    assert snap.first_law_state == "audit_grade"
    assert snap.first_law_residual_pct == 0.0
    assert snap.is_design_target is False


def test_phase_1_breakdown_sums_to_total(cfg):
    snap = compute_pue_for_phase(
        "phase_1", cfg, add_demo_noise=False,
    )
    bd = snap.breakdown
    total = (bd.it_load_kw + bd.cooling_kw
             + bd.electrical_losses_kw + bd.lighting_aux_kw)
    assert abs(bd.total_facility_kw - total) < 0.001


# ─── Phase 2 compute (design target) ──────────────────────────────────
def test_phase_2_design_target(cfg):
    snap = compute_pue_for_phase(
        "phase_2", cfg, is_design_target=True, add_demo_noise=False,
    )
    # 250 racks * 200 kW = 50,000 kW IT
    assert snap.breakdown.it_load_kw == 50_000.0
    # PUE = 1 / (1 - 0.10 - 0.03 - 0.003) = 1 / 0.867 ≈ 1.153
    assert 1.14 < snap.pue < 1.17
    assert snap.target_pue == 1.15
    assert snap.is_design_target is True
    assert snap.state == "design"   # always 'design' regardless of value


# ─── Demo noise envelope ──────────────────────────────────────────────
def test_demo_noise_within_amplitude(cfg):
    """Repeated calls add noise but must stay within ±amplitude band."""
    base = compute_pue_for_phase("phase_1", cfg, add_demo_noise=False).pue
    amp = cfg.demo_noise["amplitude"]
    for _ in range(20):
        snap = compute_pue_for_phase("phase_1", cfg, add_demo_noise=True)
        assert abs(snap.pue - base) <= amp + 0.001  # tiny float tolerance


# ─── Both-phase rollup ────────────────────────────────────────────────
def test_compute_both_phases_returns_pair(cfg):
    snaps = compute_pue_both_phases(cfg, add_demo_noise=False)
    assert "phase_1" in snaps and "phase_2" in snaps
    assert snaps["phase_1"].is_design_target is False
    assert snaps["phase_2"].is_design_target is True
    # Phase 2 PUE strictly better than Phase 1 by design
    assert snaps["phase_2"].pue < snaps["phase_1"].pue


# ─── Error paths ──────────────────────────────────────────────────────
def test_overhead_fractions_too_large_raises(tmp_path):
    bad_yaml = tmp_path / "bad.yml"
    bad_yaml.write_text(
        "phase_1:\n"
        "  description: x\n  voltage_class: x\n  rack_count: 10\n"
        "  rack_kw: 100\n  target_pue: 1.3\n  warn_threshold: 1.4\n"
        "  crit_threshold: 1.6\n  rectification_efficiency: 0.9\n"
        "  cooling_load_fraction: 0.5\n"
        "  electrical_loss_fraction: 0.4\n"
        "  lighting_aux_fraction: 0.2\n"
        "phase_2:\n"
        "  description: x\n  voltage_class: x\n  rack_count: 10\n"
        "  rack_kw: 100\n  target_pue: 1.15\n  warn_threshold: 1.25\n"
        "  crit_threshold: 1.4\n  rectification_efficiency: 0.97\n"
        "  cooling_load_fraction: 0.10\n"
        "  electrical_loss_fraction: 0.03\n"
        "  lighting_aux_fraction: 0.003\n"
        "first_law_cross_check:\n"
        "  audit_grade_residual_pct: 2.0\n"
        "  acceptable_residual_pct: 5.0\n",
        encoding="utf-8",
    )
    bad_cfg = PUEConfig(bad_yaml)
    with pytest.raises(ValueError, match="overhead fractions"):
        compute_pue_for_phase("phase_1", bad_cfg, add_demo_noise=False)
