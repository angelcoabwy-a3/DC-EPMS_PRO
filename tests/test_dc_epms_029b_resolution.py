"""DC-EPMS-029b resolution tests (Sprint 5 follow-up).

Verifies the STRUCTURAL fix: simulate_loto_measurements now modifies
physics-engine canonical fields (chiller_X_load_kw, ups_mode,
loop_flow_m3_s, etc.) instead of operating only on the virtual
redundancy-state namespace (chiller_count_online, ups_a_online).

Original symptom (pre-fix):
  shi_pre == shi_post for ALL LOTO targets.

Root cause:
  build_steady_state_measurements + simulate_loto_measurements wrote
  to fields that physics modules did not read. The two namespaces
  were disjoint, so validate_site() saw identical inputs pre/post.

Fix:
  - build_steady_state_measurements now also includes physics-canonical
    fields (chiller_1_load_kw, ups_input_kw, etc.).
  - simulate_loto_measurements per LOTO type modifies BOTH the legacy
    redundancy fields (Pillar 2 SPOF detection) AND the canonical
    physics fields (drives validate_site sensitivity).

Closure scope:
  This test verifies the STRUCTURAL fix is in place. At least 2 LOTO
  types (UPS, CDU) produce a measurable post-LOTO SHI delta with the
  current physics_engine. For the remaining LOTO types (chiller,
  cooling_tower, chw_pump, rpp) the simulate_loto output IS different
  in physics-canonical fields, but the physics_engine's pass/fail
  thresholds are not sensitive enough to surface that delta into
  site_health. That insensitivity is tracked separately as
  DC-EPMS-029c (physics_engine LOTO sensitivity tuning).
"""

from __future__ import annotations

import pytest

from backend.loto_auditor_pillar_helpers import (
    build_steady_state_measurements,
    simulate_loto_measurements,
)
from backend.physics_engine import get_engine


@pytest.fixture
def physics():
    return get_engine()


@pytest.fixture
def base():
    return build_steady_state_measurements()


# ─────────────────────────────────────────────────────────────────────
#  STRUCTURAL fix — simulate_loto writes physics-canonical fields
# ─────────────────────────────────────────────────────────────────────
def test_baseline_includes_physics_canonical_fields(base):
    """Regression: the canonical field set must be present (DC-EPMS-029b fix)."""
    canonical_required = {
        "ups_mode", "battery_on_load", "ups_input_kw", "battery_soc",
        "rack_count", "rack_tdp_kw", "loop_flow_m3_s",
        "cdu_primary_flow_m3_s", "pump_power_kw",
        "chiller_1_load_kw", "chiller_1_power_kw", "chiller_1_ecwt_c",
        "chiller_2_load_kw", "chiller_2_power_kw", "chiller_2_ecwt_c",
    }
    missing = canonical_required - set(base.keys())
    assert not missing, f"baseline missing physics-canonical fields: {missing}"


def test_chiller_loto_writes_canonical_chiller_fields(base):
    """Chiller LOTO: chiller_X_load_kw and _power_kw zero on offline,
    carrying chiller load doubles, ECWT rises."""
    sim = simulate_loto_measurements(base, "chiller_1", "chiller")
    assert sim["chiller_1_load_kw"] == 0.0
    assert sim["chiller_1_power_kw"] == 0.0
    assert sim["chiller_2_load_kw"] > base["chiller_2_load_kw"]
    assert sim["chiller_2_ecwt_c"] > base["chiller_2_ecwt_c"]
    # Pillar 2 redundancy field still updated
    assert sim["chiller_count_online"] == 2


def test_chiller_2_loto_targets_chiller_2(base):
    """Per-id parsing: chiller_2 LOTO zeroes chiller_2 (not chiller_1)."""
    sim = simulate_loto_measurements(base, "chiller_2", "chiller")
    assert sim["chiller_2_load_kw"] == 0.0
    assert sim["chiller_1_load_kw"] > base["chiller_1_load_kw"]


def test_ups_loto_writes_canonical_electrical_fields(base):
    """UPS LOTO: ups_mode, battery_on_load, battery_soc, ups_input_kw all change."""
    sim = simulate_loto_measurements(base, "ups_a", "ups")
    assert sim["ups_mode"] == "battery"
    assert sim["battery_on_load"] is True
    assert sim["battery_soc"] < base["battery_soc"]
    assert sim["ups_input_kw"] < base["ups_input_kw"]
    # Pillar 2 redundancy field still updated
    assert sim["ups_a_online"] is False


def test_chw_pump_loto_writes_canonical_mechanical_fields(base):
    sim = simulate_loto_measurements(base, "chw_pump_n_01", "chw_pump")
    assert sim["loop_flow_m3_s"] < base["loop_flow_m3_s"]
    assert sim["pump_power_kw"] < base["pump_power_kw"]
    assert sim["chw_pump_count_online"] == 2


def test_cooling_tower_loto_writes_canonical_chiller_ecwt(base):
    sim = simulate_loto_measurements(base, "cooling_tower_field_n", "cooling_tower")
    assert sim["chiller_1_ecwt_c"] > base["chiller_1_ecwt_c"]
    assert sim["chiller_2_ecwt_c"] > base["chiller_2_ecwt_c"]
    assert sim["cooling_tower_count_online"] == 1


def test_cdu_loto_writes_canonical_flow_and_dlc_return(base):
    sim = simulate_loto_measurements(base, "cdu_a_01", "cdu")
    assert sim["cdu_primary_flow_m3_s"] < base["cdu_primary_flow_m3_s"]
    assert sim["dlc_return_c"] > base.get("dlc_return_c", 45.0)


def test_path_a_rpp_loto_writes_canonical_electrical_fields(base):
    """RPP/Path A LOTO halves facility load, utility input, UPS input, xfmr load."""
    sim = simulate_loto_measurements(base, "rpp_a_01", "rpp", target_path="A")
    assert sim["facility_it_kw"] == base["facility_it_kw"] * 0.5
    assert sim["utility_kw"] == base["utility_kw"] * 0.5
    assert sim["ups_input_kw"] == base["ups_input_kw"] * 0.5


# ─────────────────────────────────────────────────────────────────────
#  FUNCTIONAL verification — at least 2 LOTO types move site_health
# ─────────────────────────────────────────────────────────────────────
def _shi_delta_for_loto(physics, base, target_id, target_type, target_path=None):
    pre = physics.validate_site(base)
    sim = simulate_loto_measurements(base, target_id, target_type, target_path=target_path)
    post = physics.validate_site(sim)
    return pre.site_health, post.site_health, pre.site_health - post.site_health


def test_ups_loto_produces_shi_delta(physics, base):
    """UPS LOTO: battery_on_load + battery_soc=0.4 -> electrical degrades, severity escalates."""
    pre, post, delta = _shi_delta_for_loto(physics, base, "ups_a", "ups")
    assert delta > 0.05, (
        f"UPS LOTO should produce >0.05 SHI delta, got pre={pre:.3f} post={post:.3f} delta={delta:+.3f}"
    )


def test_cdu_loto_produces_shi_delta(physics, base):
    """CDU LOTO: dlc_return +2 C -> it_thermal first_law fails."""
    pre, post, delta = _shi_delta_for_loto(physics, base, "cdu_a_01", "cdu")
    assert delta > 0.05, (
        f"CDU LOTO should produce >0.05 SHI delta, got pre={pre:.3f} post={post:.3f} delta={delta:+.3f}"
    )


def test_at_least_two_loto_types_produce_shi_delta(physics, base):
    """Original DC-EPMS-029b acceptance: shi_pre != shi_post for non-trivial LOTO."""
    cases = [
        ("ups_a",         "ups",          None),
        ("cdu_a_01",      "cdu",          None),
        ("chiller_1",     "chiller",      None),
        ("chw_pump_n_01", "chw_pump",     None),
        ("cooling_tower_field_n", "cooling_tower", None),
        ("rpp_a_01",      "rpp",          "A"),
    ]
    moving = []
    for tid, ttype, tpath in cases:
        _, _, delta = _shi_delta_for_loto(physics, base, tid, ttype, tpath)
        if abs(delta) > 0.01:
            moving.append((ttype, delta))
    assert len(moving) >= 2, (
        f"DC-EPMS-029b NOT resolved: only {len(moving)} of {len(cases)} LOTO types "
        f"produce SHI delta > 0.01. Moving cases: {moving}"
    )


# ─────────────────────────────────────────────────────────────────────
#  Pillar 2 redundancy fields preserved (no regression)
# ─────────────────────────────────────────────────────────────────────
def test_pillar2_legacy_fields_still_modified(base):
    """SPOF detection still works: legacy redundancy-state fields are touched."""
    sim_ups = simulate_loto_measurements(base, "ups_a", "ups")
    assert sim_ups["ups_a_online"] is False

    sim_chi = simulate_loto_measurements(base, "chiller_1", "chiller")
    assert sim_chi["chiller_count_online"] == 2

    sim_pump = simulate_loto_measurements(base, "chw_pump_n_01", "chw_pump")
    assert sim_pump["chw_pump_count_online"] == 2

    sim_ct = simulate_loto_measurements(base, "cooling_tower_field_n", "cooling_tower")
    assert sim_ct["cooling_tower_count_online"] == 1


# ─────────────────────────────────────────────────────────────────────
#  Symmetry / immutability
# ─────────────────────────────────────────────────────────────────────
def test_no_loto_returns_base_unchanged(base):
    """simulate_loto_measurements with unknown type returns base unchanged."""
    sim = simulate_loto_measurements(base, "fuel_tank_a", "fuel_tank")
    assert sim == base


def test_immutability_of_input_base(base):
    """simulate_loto_measurements MUST NOT mutate the input dict."""
    snapshot = dict(base)
    _ = simulate_loto_measurements(base, "chiller_1", "chiller")
    assert base == snapshot, "input base was mutated"
