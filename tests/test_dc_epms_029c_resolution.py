"""DC-EPMS-029c resolution tests (MVP S4 bug closeout).

Closes the sensitivity half left open by DC-EPMS-029b: after 029b the
LOTO simulation wrote physics-canonical fields, but only 2 of 6 LOTO
types (UPS, CDU) moved site_health. Two stacked defects caused it:

1. MASKED BASELINE — build_steady_state_measurements carried SITE-level
   magnitudes (ups_load_kw=16756 vs the UNIT-level Galaxy VX model with
   UPS_RATED_KW=600; loop_flow 0.45 m^3/s vs the per-hall Darcy
   geometry at 0.066). The pre-LOTO baseline already failed
   ups_efficiency / xfmr_thermal / darcy / cdu_balance (SHI 0.54), and
   under the min() rollup that degraded floor swallowed every
   post-LOTO delta.

2. BLIND HEAT_REJECTION — an offline chiller (power=0) skipped its COP
   check, the N+1 ratio sat exactly on its passing boundary, and no
   check looked at redundancy loss or condenser-water temperature, so
   chiller and cooling_tower LOTO left the module at health 1.0.

Fix:
  - Baseline recalibrated to unit-level values derived from the
    modules' own curves -> validates healthy (SHI = 1.0).
  - heat_rejection Check 5 now fails when a unit is offline under load
    (carrying chiller = SPOF), and the new Check 6
    (condenser_water_envelope) warns when worst running-chiller ECWT
    exceeds 34 C (York YZ rated 29.4 C, trip 40 C).

Acceptance: ALL SIX LOTO types produce SHI delta > 0.05 from a healthy
baseline, each through its physically-correct failure mechanism.
"""

from __future__ import annotations

import pytest

from backend.loto_auditor_pillar_helpers import (
    build_steady_state_measurements,
    simulate_loto_measurements,
)
from backend.physics.heat_rejection import HeatRejectionModule
from backend.physics_engine import get_engine


@pytest.fixture
def physics():
    return get_engine()


@pytest.fixture
def base():
    return build_steady_state_measurements()


# ─────────────────────────────────────────────────────────────────────
#  Defect 1 — the baseline must validate HEALTHY (no masking floor)
# ─────────────────────────────────────────────────────────────────────
def test_baseline_validates_healthy(physics, base):
    """Pre-LOTO SHI must be 1.0: a degraded baseline masks LOTO deltas
    under the min() rollup. Regression fence for the 029c calibration —
    if a physics curve or threshold changes, this fails loudly instead
    of silently re-masking the deltas."""
    pre = physics.validate_site(base)
    failed = {
        name: [c["name"] for c in r.checks if not c["passed"]]
        for name, r in pre.modules.items()
        if any(not c["passed"] for c in r.checks)
    }
    assert not failed, f"baseline fails physics checks: {failed}"
    assert pre.site_health >= 0.99, (
        f"baseline SHI {pre.site_health:.4f} < 0.99 — the masking floor is back"
    )


# ─────────────────────────────────────────────────────────────────────
#  Acceptance — every LOTO type moves site_health
# ─────────────────────────────────────────────────────────────────────
LOTO_CASES = [
    pytest.param("ups_a", "ups", None, id="ups"),
    pytest.param("chiller_1", "chiller", None, id="chiller"),
    pytest.param("cooling_tower_field_n", "cooling_tower", None, id="cooling_tower"),
    pytest.param("chw_pump_n_01", "chw_pump", None, id="chw_pump"),
    pytest.param("cdu_a_01", "cdu", None, id="cdu"),
    pytest.param("rpp_a_01", "rpp", "A", id="rpp"),
]


@pytest.mark.parametrize(("tid", "ttype", "tpath"), LOTO_CASES)
def test_every_loto_type_produces_shi_delta(physics, base, tid, ttype, tpath):
    """DC-EPMS-029c acceptance: the previously-insensitive types
    (chiller, cooling_tower, chw_pump, rpp) now react, and the 029b
    pair (ups, cdu) keeps reacting."""
    pre = physics.validate_site(base)
    sim = simulate_loto_measurements(base, tid, ttype, target_path=tpath)
    post = physics.validate_site(sim)
    delta = pre.site_health - post.site_health
    assert delta > 0.05, (
        f"{ttype} LOTO insensitive: pre={pre.site_health:.4f} "
        f"post={post.site_health:.4f} delta={delta:+.4f}"
    )


def test_loto_failures_land_in_the_right_module(physics, base):
    """Each LOTO type must degrade through its physically-correct path,
    not via an unrelated module's noise."""
    expectations = {
        "chiller": ("heat_rejection", "n_plus_1_redundancy_margin"),
        "cooling_tower": ("heat_rejection", "condenser_water_envelope"),
        "chw_pump": ("mechanical", "pump_affinity_cubic_power"),
        "rpp": ("electrical", "ups_efficiency_vs_curve"),
    }
    cases = {
        "chiller": ("chiller_1", None),
        "cooling_tower": ("cooling_tower_field_n", None),
        "chw_pump": ("chw_pump_n_01", None),
        "rpp": ("rpp_a_01", "A"),
    }
    for ttype, (module_name, check_name) in expectations.items():
        tid, tpath = cases[ttype]
        sim = simulate_loto_measurements(base, tid, ttype, target_path=tpath)
        post = physics.validate_site(sim)
        failed = [c["name"] for c in post.modules[module_name].checks if not c["passed"]]
        assert check_name in failed, (
            f"{ttype} LOTO: expected {module_name}.{check_name} to fail, "
            f"failed checks were {failed}"
        )


# ─────────────────────────────────────────────────────────────────────
#  Defect 2 — heat_rejection unit checks (Check 5 SPOF + Check 6 ECWT)
# ─────────────────────────────────────────────────────────────────────
def _hr_measurements(**overrides):
    m = {
        "chiller_1_load_kw": 2500.0, "chiller_1_power_kw": 350.0,
        "chiller_1_ecwt_c": 29.0,
        "chiller_2_load_kw": 2500.0, "chiller_2_power_kw": 350.0,
        "chiller_2_ecwt_c": 29.0,
    }
    m.update(overrides)
    return m


def _check(result, name):
    return next(c for c in result.checks if c["name"] == name)


def test_hr_nominal_passes_both_new_checks():
    r = HeatRejectionModule().validate(_hr_measurements())
    assert _check(r, "n_plus_1_redundancy_margin")["passed"]
    assert _check(r, "condenser_water_envelope")["passed"]
    assert r.health == 1.0


def test_hr_offline_chiller_under_load_fails_n_plus_1():
    """A unit offline (power=0) while the plant carries load = the
    carrying chiller is a SPOF. Pre-029c this scenario was health 1.0."""
    r = HeatRejectionModule().validate(_hr_measurements(
        chiller_1_load_kw=0.0, chiller_1_power_kw=0.0,
        chiller_2_load_kw=5000.0, chiller_2_power_kw=770.0,
        chiller_2_ecwt_c=34.0,
    ))
    assert not _check(r, "n_plus_1_redundancy_margin")["passed"]
    assert r.health < 1.0


def test_hr_elevated_ecwt_fails_condenser_envelope():
    """Cooling-tower capacity loss raises ECWT on running chillers past
    the 34 C approach-margin threshold."""
    r = HeatRejectionModule().validate(_hr_measurements(
        chiller_1_ecwt_c=35.0, chiller_2_ecwt_c=35.0,
    ))
    assert not _check(r, "condenser_water_envelope")["passed"]
    assert r.health < 1.0


def test_hr_offline_chiller_ecwt_ignored_by_envelope():
    """The envelope check reads RUNNING chillers only: a hot ECWT
    reading on an offline unit (stagnant condenser loop) is not an
    operational excursion."""
    r = HeatRejectionModule().validate(_hr_measurements(
        chiller_1_load_kw=0.0, chiller_1_power_kw=0.0, chiller_1_ecwt_c=38.0,
        chiller_2_load_kw=2500.0, chiller_2_power_kw=350.0, chiller_2_ecwt_c=29.0,
    ))
    assert _check(r, "condenser_water_envelope")["passed"]


def test_hr_ecwt_at_trip_escalates_critical():
    from backend.physics.base import Severity

    r = HeatRejectionModule().validate(_hr_measurements(
        chiller_1_ecwt_c=40.0, chiller_2_ecwt_c=40.0,
    ))
    assert not _check(r, "condenser_water_envelope")["passed"]
    assert r.severity == Severity.CRITICAL
    assert r.health <= 0.5
