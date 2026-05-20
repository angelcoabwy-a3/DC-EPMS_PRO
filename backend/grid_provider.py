"""
backend/grid_provider.py
=========================
Epic 3 Batch 3.C prep — Ontario IESO grid-intensity mock provider.

The Carbon/Grid agent (added in the next commit) consumes a callable
that returns the current ``GridState`` — carbon intensity (gCO2/kWh),
Time-of-Use pricing band, and a peak-demand flag. This module ships
the V11 MOCK: a deterministic synthetic function of the local Toronto
time-of-day + weekend status.

The real IESO (Independent Electricity System Operator) API integration
is deferred — the agent contract is identical, only the provider's
implementation changes. Pure function-as-DI-seam pattern.

Sources for the calibration
---------------------------
Ontario electricity mix is dominated by carbon-low generation:
  - Nuclear   ~ 50 % of supply (Bruce, Darlington, Pickering — ~25 gCO2/kWh)
  - Hydro     ~ 25 % of supply (~24 gCO2/kWh life-cycle)
  - Wind      ~ 10 % of supply (~11 gCO2/kWh life-cycle)
  - Natural gas peakers ~ 10-15 % — KICK IN during high demand,
                                    swinging the marginal intensity
                                    from ~30 (overnight) to ~250 g/kWh
                                    (weekday summer afternoon peak).

Time-of-Use schedule per Ontario Energy Board RPP class B (summer
season May 1 - Oct 31, residential + small commercial):
  - off-peak  7 pm - 7 am + all weekends/holidays  →  7.6  ¢/kWh
  - mid-peak  11 am - 5 pm weekdays                →  12.2 ¢/kWh
  - on-peak   7-11 am AND 5-7 pm weekdays          →  15.1 ¢/kWh

The mock returns deterministic values for a given input timestamp,
making tests fully reproducible. Production swap is a one-line change.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _resolve_toronto_tz() -> tzinfo:
    """Try IANA America/Toronto first; fall back to a fixed UTC-4 offset.

    Windows ships without the IANA tzdata DB by default; rather than make
    the ``tzdata`` PyPI package a hard requirement for this mock, fall
    back to EDT (UTC-4). Ontario is on EDT for the summer demo window
    (March-November), so the band classification stays correct. Winter
    accuracy is deferred to the real-IESO integration.
    """
    try:
        return ZoneInfo("America/Toronto")
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=-4), name="EDT")


TORONTO_TZ: tzinfo = _resolve_toronto_tz()


# ─── Carbon thresholds (gCO2/kWh) — read by the Carbon/Grid agent ─────
LOW_CARBON_THRESHOLD = 50.0     # nuclear + hydro baseload dominant
MED_CARBON_THRESHOLD = 100.0    # mixed (gas peakers warming up)
HIGH_CARBON_THRESHOLD = 200.0   # gas peakers significant share

# ─── Ontario IESO RPP summer Time-of-Use price tiers (cents/kWh) ──────
_TOU_PRICES: dict[str, float] = {
    "off-peak": 7.6,
    "mid-peak": 12.2,
    "on-peak":  15.1,
}

TOU_BANDS = frozenset(_TOU_PRICES.keys())


@dataclass(frozen=True)
class GridState:
    """Snapshot of the Ontario grid as the Carbon/Grid agent sees it."""

    carbon_gco2_per_kwh: float
    tou_price_cents_per_kwh: float
    tou_band: str               # one of TOU_BANDS
    is_peak_demand: bool        # True iff tou_band == "on-peak"
    timestamp: float            # epoch seconds, Toronto TZ-aware

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ─── Internal — band + carbon profile ────────────────────────────────
def _tou_band_for(hour: int, is_weekend: bool) -> str:
    """Ontario IESO summer Time-of-Use schedule (RPP class B).

    Weekend + holiday = off-peak all day. On weekdays:
      - 7 pm - 7 am  → off-peak
      - 7-11 am + 5-7 pm  → on-peak
      - 11 am - 5 pm  → mid-peak
    """
    if is_weekend:
        return "off-peak"
    if hour < 7 or hour >= 19:
        return "off-peak"
    if (7 <= hour < 11) or (17 <= hour < 19):
        return "on-peak"
    return "mid-peak"


def _carbon_for(hour: int, is_weekend: bool) -> float:
    """Deterministic carbon profile keyed to time-of-day + weekend.

    Ontario's nuclear + hydro baseload sets the floor ~ 30-40 g/kWh.
    Gas peakers fire during weekday afternoon demand, pushing marginal
    intensity to ~ 215 g/kWh at 11 am - 5 pm. Shoulder hours (early
    morning / early evening) sit in the middle ~ 135 g/kWh.
    """
    base = 35.0   # nuclear + hydro baseload floor
    if is_weekend or hour < 6 or hour >= 22:
        return base + 5.0     # overnight: ~ 40 g/kWh
    if 11 <= hour < 17:
        return base + 180.0   # weekday afternoon peak: ~ 215 g/kWh
    if (7 <= hour < 11) or (17 <= hour < 19):
        return base + 100.0   # shoulder peak: ~ 135 g/kWh
    return base + 40.0        # weekday daytime non-peak: ~ 75 g/kWh


# ─── Public — the provider callable ──────────────────────────────────
def get_grid_state(now: datetime | None = None) -> GridState:
    """Return the current synthetic Ontario grid state.

    Args:
        now: optional explicit timestamp (any tz; converted to America/
             Toronto). Defaults to ``datetime.now(TORONTO_TZ)`` — i.e.,
             "live" mock that varies with wall-clock.

    Returns:
        A frozen ``GridState`` snapshot. Deterministic for a given
        input timestamp, which makes tests fully reproducible.
    """
    if now is None:
        now = datetime.now(TORONTO_TZ)
    elif now.tzinfo is None:
        # Naive datetime — interpret as Toronto-local (matches Wilmer's
        # operational environment per engram §11 geography).
        now = now.replace(tzinfo=TORONTO_TZ)
    else:
        now = now.astimezone(TORONTO_TZ)

    hour = now.hour
    is_weekend = now.weekday() >= 5
    band = _tou_band_for(hour, is_weekend)
    return GridState(
        carbon_gco2_per_kwh=_carbon_for(hour, is_weekend),
        tou_price_cents_per_kwh=_TOU_PRICES[band],
        tou_band=band,
        is_peak_demand=(band == "on-peak"),
        timestamp=now.timestamp(),
    )


def carbon_descriptor(carbon_gco2_per_kwh: float) -> str:
    """Human-readable bucket label for a carbon intensity reading."""
    if carbon_gco2_per_kwh < LOW_CARBON_THRESHOLD:
        return "low / nuclear+hydro dominant"
    if carbon_gco2_per_kwh < MED_CARBON_THRESHOLD:
        return "moderate / mixed"
    if carbon_gco2_per_kwh < HIGH_CARBON_THRESHOLD:
        return "elevated / gas peakers active"
    return "high / heavy gas dispatch"
