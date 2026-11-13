"""
backend/kpi_fallback.py
=======================
Release R1 -- Overview KPI point without TimescaleDB.

The Overview KPI cards (Hall temperature / IT load / fleet) read the
legacy ``telemetry`` table through ``GET /api/telemetry/latest``. That
table is only written by the external ``scripts/simulator.py`` process,
so on any deployment without PostgreSQL (or without that script
running) the cards stayed at an em dash while the in-process Path C2
simulator + Kalman pipeline was streaming 281 live channels next to
them.

``build_kpi_point`` derives the same flat row shape from sources that
are always in-process:

  hall_temp_c   mean of every ``rack_inlet_T_c`` channel (the ASHRAE
                TC 9.9 quantity the card is labelled with)
  delta_t_c     mean ``dlc_return_T_c`` minus mean ``dlc_supply_T_c``
  it_load_kw,
  pue,
  rack_count,
  rack_tdp_kw   Phase 1 snapshot from backend/physics/pue.py (ADR-004)

It is a pure function (no I/O, no clock unless ``now`` is omitted) and
returns ``None`` when the inputs cannot support an honest point --
the caller then reports "no data" instead of inventing one.

Honest scope: every value is SIMULATED. The endpoint labels the
response ``"source": "simulator"`` and the HMI shows that label.
"""

from __future__ import annotations

from datetime import UTC, datetime
from statistics import fmean
from typing import Any

__all__ = ["SOURCE_SIMULATOR", "build_kpi_point"]

SOURCE_SIMULATOR = "simulator"

_METRIC_HALL = "rack_inlet_T_c"
_METRIC_DLC_SUPPLY = "dlc_supply_T_c"
_METRIC_DLC_RETURN = "dlc_return_T_c"


def _metric_values(channels: dict[str, Any], metric: str) -> list[float]:
    """Latest emission of every channel whose id ends in ``:<metric>``."""
    suffix = ":" + metric
    out: list[float] = []
    for channel_id, fields in channels.items():
        if not isinstance(channel_id, str) or not channel_id.endswith(suffix):
            continue
        if not isinstance(fields, dict):
            continue
        value = fields.get("last_emission")
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        if value != value or value in (float("inf"), float("-inf")):
            continue
        out.append(float(value))
    return out


def build_kpi_point(
    channels: dict[str, Any] | None,
    pue_phase_1: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Flat KPI row in the ``telemetry`` table shape, or ``None``.

    ``channels`` is the ``channel_innovations`` payload
    (``{"<component>:<metric>": {"last_emission": float, ...}}``).
    ``pue_phase_1`` is ``PUESnapshot.to_dict()`` for Phase 1.
    """
    if not channels:
        return None
    hall = _metric_values(channels, _METRIC_HALL)
    if not hall:
        return None

    supply = _metric_values(channels, _METRIC_DLC_SUPPLY)
    ret = _metric_values(channels, _METRIC_DLC_RETURN)
    delta_t = round(fmean(ret) - fmean(supply), 2) if supply and ret else None

    pue: float | None = None
    it_load_kw: float | None = None
    rack_count: int | None = None
    rack_tdp_kw: float | None = None
    if isinstance(pue_phase_1, dict):
        raw_pue = pue_phase_1.get("pue")
        if isinstance(raw_pue, int | float) and not isinstance(raw_pue, bool):
            pue = float(raw_pue)
        breakdown = pue_phase_1.get("breakdown")
        if isinstance(breakdown, dict):
            raw_it = breakdown.get("it_load_kw")
            if isinstance(raw_it, int | float) and not isinstance(raw_it, bool):
                it_load_kw = float(raw_it)
        raw_count = pue_phase_1.get("rack_count")
        if isinstance(raw_count, int) and not isinstance(raw_count, bool):
            rack_count = raw_count
        raw_tdp = pue_phase_1.get("rack_kw")
        if isinstance(raw_tdp, int | float) and not isinstance(raw_tdp, bool):
            rack_tdp_kw = float(raw_tdp)

    stamp = now if now is not None else datetime.now(UTC)
    return {
        "ts": stamp.astimezone(UTC).isoformat(),
        "it_load_kw": it_load_kw,
        "pue": pue,
        "hall_temp_c": round(fmean(hall), 2),
        "delta_t_c": delta_t,
        "ttc_seconds": None,
        "scenario": None,
        "rack_count": rack_count,
        "rack_tdp_kw": rack_tdp_kw,
        "hall_temp_sample_count": len(hall),
    }
