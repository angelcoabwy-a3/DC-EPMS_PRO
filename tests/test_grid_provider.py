"""
tests/test_grid_provider.py
============================
Epic 3 Batch 3.C prep — IESO Ontario grid-intensity mock provider.

Coverage:
  - GridState shape + dataclass invariants
  - TOU band classification: off-peak / mid-peak / on-peak
  - Weekend dominance over weekday clock
  - Carbon profile bounds: overnight floor + afternoon peak ceiling
  - Naive-datetime handling (Toronto-local interpretation)
  - Aware-datetime handling (cross-tz conversion)
  - Default branch (now=None) returns a valid snapshot
  - carbon_descriptor() bucket boundaries
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from backend.grid_provider import (
    HIGH_CARBON_THRESHOLD,
    LOW_CARBON_THRESHOLD,
    MED_CARBON_THRESHOLD,
    TORONTO_TZ,
    TOU_BANDS,
    GridState,
    carbon_descriptor,
    get_grid_state,
)


# ─── TOU band classification ─────────────────────────────────────────
def test_off_peak_overnight_weekday():
    """3 AM weekday → off-peak."""
    s = get_grid_state(datetime(2026, 5, 19, 3, 0, tzinfo=TORONTO_TZ))   # Tue
    assert s.tou_band == "off-peak"
    assert s.is_peak_demand is False
    assert s.tou_price_cents_per_kwh == pytest.approx(7.6)


def test_on_peak_weekday_morning():
    """8 AM weekday → on-peak (7-11am window)."""
    s = get_grid_state(datetime(2026, 5, 19, 8, 0, tzinfo=TORONTO_TZ))   # Tue
    assert s.tou_band == "on-peak"
    assert s.is_peak_demand is True
    assert s.tou_price_cents_per_kwh == pytest.approx(15.1)


def test_on_peak_weekday_evening():
    """6 PM weekday → on-peak (5-7pm window)."""
    s = get_grid_state(datetime(2026, 5, 19, 18, 0, tzinfo=TORONTO_TZ))   # Tue
    assert s.tou_band == "on-peak"
    assert s.is_peak_demand is True


def test_mid_peak_weekday_midday():
    """1 PM weekday → mid-peak."""
    s = get_grid_state(datetime(2026, 5, 19, 13, 0, tzinfo=TORONTO_TZ))   # Tue
    assert s.tou_band == "mid-peak"
    assert s.is_peak_demand is False
    assert s.tou_price_cents_per_kwh == pytest.approx(12.2)


def test_weekend_always_off_peak():
    """Saturday at 1 PM still returns off-peak (weekend dominance)."""
    s = get_grid_state(datetime(2026, 5, 23, 13, 0, tzinfo=TORONTO_TZ))   # Sat
    assert s.tou_band == "off-peak"
    assert s.is_peak_demand is False


# ─── Carbon profile bounds ───────────────────────────────────────────
def test_carbon_intensity_overnight_below_med():
    """Overnight (3 AM weekday) carbon stays below MED threshold."""
    s = get_grid_state(datetime(2026, 5, 19, 3, 0, tzinfo=TORONTO_TZ))
    assert s.carbon_gco2_per_kwh < MED_CARBON_THRESHOLD
    assert s.carbon_gco2_per_kwh > 0


def test_carbon_intensity_afternoon_above_high():
    """Weekday 2 PM hits HIGH carbon threshold — gas peakers active."""
    s = get_grid_state(datetime(2026, 5, 19, 14, 0, tzinfo=TORONTO_TZ))
    assert s.carbon_gco2_per_kwh >= HIGH_CARBON_THRESHOLD


def test_carbon_intensity_weekend_low():
    """Saturday afternoon: carbon stays below LOW threshold (no gas peakers)."""
    s = get_grid_state(datetime(2026, 5, 23, 14, 0, tzinfo=TORONTO_TZ))
    assert s.carbon_gco2_per_kwh < LOW_CARBON_THRESHOLD


# ─── Naive + aware datetime handling ─────────────────────────────────
def test_naive_datetime_interpreted_as_toronto():
    """Naive datetime is treated as Toronto-local time."""
    naive = datetime(2026, 5, 19, 3, 0)
    aware = datetime(2026, 5, 19, 3, 0, tzinfo=TORONTO_TZ)
    s1 = get_grid_state(naive)
    s2 = get_grid_state(aware)
    assert s1.tou_band == s2.tou_band
    assert s1.carbon_gco2_per_kwh == s2.carbon_gco2_per_kwh


def test_aware_datetime_cross_tz_converted():
    """UTC datetime gets converted to Toronto; verdict reflects local hour.

    Toronto is UTC-4 in summer (EDT). 12:00 UTC on a weekday = 08:00
    Toronto = on-peak.
    """
    utc = datetime(2026, 5, 19, 12, 0, tzinfo=UTC)   # Tue 12 UTC
    s = get_grid_state(utc)
    assert s.tou_band == "on-peak"


# ─── Default branch + shape ──────────────────────────────────────────
def test_default_now_returns_valid_snapshot():
    """get_grid_state() with no args returns a valid snapshot."""
    s = get_grid_state()
    assert isinstance(s, GridState)
    assert s.tou_band in TOU_BANDS
    assert s.carbon_gco2_per_kwh > 0
    assert s.timestamp > 0


def test_grid_state_to_dict_roundtrip():
    """GridState.to_dict() exposes every field."""
    s = get_grid_state(datetime(2026, 5, 19, 3, 0, tzinfo=TORONTO_TZ))
    d = s.to_dict()
    assert set(d.keys()) == {
        "carbon_gco2_per_kwh", "tou_price_cents_per_kwh",
        "tou_band", "is_peak_demand", "timestamp",
    }
    assert d["tou_band"] == "off-peak"


def test_grid_state_is_frozen():
    """GridState is immutable (frozen dataclass)."""
    s = get_grid_state(datetime(2026, 5, 19, 3, 0, tzinfo=TORONTO_TZ))
    with pytest.raises(FrozenInstanceError):
        s.carbon_gco2_per_kwh = 999.0   # type: ignore[misc]


# ─── carbon_descriptor() bucket boundaries ──────────────────────────
def test_carbon_descriptor_buckets():
    assert "low" in carbon_descriptor(LOW_CARBON_THRESHOLD - 1).lower()
    assert "moderate" in carbon_descriptor(LOW_CARBON_THRESHOLD).lower()
    assert "elevated" in carbon_descriptor(MED_CARBON_THRESHOLD).lower()
    assert "high" in carbon_descriptor(HIGH_CARBON_THRESHOLD).lower()
