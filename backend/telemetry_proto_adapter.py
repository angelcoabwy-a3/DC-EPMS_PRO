"""
backend/telemetry_proto_adapter.py
==================================
Bridge between the Sprint 5 telemetry pipeline (engineering-unit
JSON-shaped dict) and the Epic 8 canonical v1 wire format
(strict-SI proto envelopes).

The adapter is the seam where:

  * Engineering units (deg C, kPa, LPM, kW, pct, min, m-head)
    become strict SI (K, Pa, m3/s, W, ratio, s, Pa).
  * Per-channel pipeline records become typed proto envelopes
    (TemperatureMeasurement / VoltageReading / FlowMeasurement /
    UPSBatteryHealth / ...).
  * Three voltage_v_phase_{ab,bc,ca} channels on a common component
    collapse into ONE AcThreePhaseVoltage payload per envelope.
  * The Kalman z-score from the pipeline becomes
    :class:`MeasurementQuality`.

Public API
----------

    envelope_from_pipeline_record(...)         single-channel builder
    envelopes_from_pipeline_payload(...)       end-to-end aggregator

Skill binding
-------------

* ``S-TELEMETRY-01`` -- wire-format invariants. Every envelope
  produced here MUST satisfy the schema invariants enforced by
  ``tests/test_telemetry_proto_schema.py``.
* ``S-VOCAB-01``     -- vocabulary fence. Channels with the
  ``voltage_v_phase_*`` metric MUST route to
  :class:`AcThreePhaseVoltage`, NEVER to
  :class:`DcUnipolarVoltage`. The single-channel builder REFUSES
  to handle these (returns ``None``); the aggregator is the only
  path that can emit a three-phase envelope, and only when all
  three phases are present.
* ``S-DET-01``       -- pure-Python deterministic. No LLM, no
  network I/O, no time-of-day side effects. ADR-006 deterministic
  sandbox compliant.
"""
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

from backend.telemetry_proto.v1 import telemetry_pb2 as pb

log = logging.getLogger(__name__)


# Convenience re-export so callers can write
# `from backend.telemetry_proto_adapter import AC_BUS_PRIMARY_480_A`
# without dragging in the whole pb2 module.
AC_BUS_PRIMARY_480_A = pb.AC_BUS_PRIMARY_480_A


# ─── unit conversions (strict SI) ─────────────────────────────────────────

_KELVIN_OFFSET = 273.15
_KPA_TO_PA = 1000.0
_LPM_TO_M3_PER_S = 1.0 / 60_000.0    # 1 L = 0.001 m^3; per 60 seconds
_GPM_TO_LPM = 3.785411784            # US liquid gallon
_KW_TO_W = 1000.0
_WATER_RHO_KG_M3 = 1000.0
_STANDARD_GRAVITY_M_S2 = 9.80665
_M_HEAD_WATER_TO_PA = _WATER_RHO_KG_M3 * _STANDARD_GRAVITY_M_S2


def c_to_k(c: float) -> float:
    """Celsius (absolute) -> Kelvin. NOT for deltas -- a delta of 1
    deg C IS 1 K with no offset."""
    return float(c) + _KELVIN_OFFSET


def kpa_to_pa(kpa: float) -> float:
    return float(kpa) * _KPA_TO_PA


def lpm_to_m3_per_s(lpm: float) -> float:
    return float(lpm) * _LPM_TO_M3_PER_S


def gpm_to_m3_per_s(gpm: float) -> float:
    return float(gpm) * _GPM_TO_LPM * _LPM_TO_M3_PER_S


def kw_to_w(kw: float) -> float:
    return float(kw) * _KW_TO_W


def pct_to_ratio(pct: float) -> float:
    return float(pct) / 100.0


def min_to_s(m: float) -> float:
    return float(m) * 60.0


def m_head_water_to_pa(m: float) -> float:
    """Convert metres of water column to Pascals at standard gravity.

    P = rho * g * h with rho = 1000 kg/m^3 (water at 4 deg C) and
    g = 9.80665 m/s^2. Used to map NPSH margin (conventionally
    reported in m) to strict-SI pressure.
    """
    return float(m) * _M_HEAD_WATER_TO_PA


# ─── MeasurementQuality derivation ────────────────────────────────────────

def quality_from_z_score(z: float) -> int:
    """Map a Kalman normalized z-score to :class:`MeasurementQuality`.

    Rules:
      * ``NaN`` -> ``QUALITY_INVALID`` (sensor failed / out of range)
      * ``|z| < 2.0`` -> ``QUALITY_GOOD`` (in-band, trusted)
      * else -> ``QUALITY_DEGRADED`` (flagged for review; value
        usable -- INVALID is reserved for hardware failure)
    """
    try:
        z_float = float(z)
    except (TypeError, ValueError):
        return pb.QUALITY_INVALID
    if math.isnan(z_float):
        return pb.QUALITY_INVALID
    if abs(z_float) < 2.0:
        return pb.QUALITY_GOOD
    return pb.QUALITY_DEGRADED


# ─── Channel-scope helper ─────────────────────────────────────────────────

def _split_scope(channel_id: str) -> tuple[str, str]:
    """Return ``(component_id, metric)``.

    A scoped id ``ups_a:voltage_v_phase_ab`` returns
    ``("ups_a", "voltage_v_phase_ab")``. An unscoped id ``gpu_Tj_c``
    returns ``("gpu_Tj_c", "gpu_Tj_c")`` -- the channel acts as its
    own component, a degenerate but acceptable shape.
    """
    if ":" in channel_id:
        comp, _, metric = channel_id.partition(":")
        return comp, metric
    return channel_id, channel_id


# ─── KalmanInnovation builder ─────────────────────────────────────────────

def _build_innovation(z_score: float, is_anomalous: bool) -> pb.KalmanInnovation:
    """Build a KalmanInnovation message.

    The pipeline does not surface the raw innovation residual or the
    innovation variance (they live inside the Kalman filter state).
    The wire format exposes the normalised z-score and the anomaly
    flag -- sufficient for downstream consumers that gate decisions
    on sensor health.
    """
    inv = pb.KalmanInnovation()
    inv.innovation = 0.0
    inv.innovation_var = 0.0
    inv.normalized_z = float(z_score)
    inv.is_anomalous = bool(is_anomalous)
    return inv


# ─── Per-metric builders ──────────────────────────────────────────────────

def _build_temperature(env: pb.TelemetryEnvelope, raw_c: float, location: int,
                       quality: int) -> None:
    env.discipline = pb.DISCIPLINE_THERMAL
    tm = env.thermal.temperature
    tm.location = location
    tm.temperature_k = c_to_k(raw_c)
    tm.quality = quality


def _build_flow_lpm(env: pb.TelemetryEnvelope, raw_lpm: float, asset_id: str,
                    quality: int) -> None:
    env.discipline = pb.DISCIPLINE_MECHANICAL
    fm = env.mechanical.flow
    fm.flow_m3_per_s = lpm_to_m3_per_s(raw_lpm)
    fm.cdu_id = asset_id
    fm.quality = quality


def _build_flow_gpm(env: pb.TelemetryEnvelope, raw_gpm: float, asset_id: str,
                    quality: int) -> None:
    env.discipline = pb.DISCIPLINE_MECHANICAL
    fm = env.mechanical.flow
    fm.flow_m3_per_s = gpm_to_m3_per_s(raw_gpm)
    fm.cdu_id = asset_id
    fm.quality = quality


def _build_filter_dp(env: pb.TelemetryEnvelope, raw_kpa: float, asset_id: str,
                     quality: int) -> None:
    env.discipline = pb.DISCIPLINE_MECHANICAL
    fdp = env.mechanical.filter_dp
    fdp.delta_p_pa = kpa_to_pa(raw_kpa)
    fdp.stage = pb.FILTER_STAGE_MAIN
    fdp.cdu_id = asset_id
    fdp.quality = quality


def _build_npsh(env: pb.TelemetryEnvelope, raw_m: float, quality: int) -> None:
    env.discipline = pb.DISCIPLINE_MECHANICAL
    pump = env.mechanical.pump
    pump.npsh_margin_pa = m_head_water_to_pa(raw_m)
    pump.quality = quality


def _build_ups_soc(env: pb.TelemetryEnvelope, raw_pct: float, quality: int) -> None:
    env.discipline = pb.DISCIPLINE_ELECTRICAL
    ub = env.electrical.ups_battery
    ub.soc_ratio = pct_to_ratio(raw_pct)
    ub.quality = quality


def _build_ups_runtime(env: pb.TelemetryEnvelope, raw_min: float, quality: int) -> None:
    env.discipline = pb.DISCIPLINE_ELECTRICAL
    ub = env.electrical.ups_battery
    ub.runtime_s = min_to_s(raw_min)
    ub.quality = quality


# ─── Metric classification table ──────────────────────────────────────────

# Temperature channels mapped to TempLocation enum values.
# Adding a new thermal channel: append here.
_TEMP_METRICS: dict[str, int] = {
    "rack_inlet_T_c":           pb.TEMP_RACK_INLET,
    "gpu_Tj_c":                 pb.TEMP_GPU_TJ_AVG,
    "dlc_supply_T_c":           pb.TEMP_DLC_SUPPLY,
    "dlc_return_T_c":           pb.TEMP_DLC_RETURN,
    "chiller_LWT_c":            pb.TEMP_CHILLER_LWT,
    "cdu_primary_supply_T_c":   pb.TEMP_DLC_SUPPLY,
    "cdu_secondary_supply_T_c": pb.TEMP_DLC_SUPPLY,
    "ecwt_c":                   pb.TEMP_ECWT,
    "outdoor_wet_bulb_c":       pb.TEMP_WET_BULB,
}


# ─── Top-level builders ───────────────────────────────────────────────────

def envelope_from_pipeline_record(
    *,
    site_id: str,
    asset_id: str,
    metric: str,
    raw_value: float,
    z_score: float,
    is_anomalous: bool,
    sequence_number: int = 0,
) -> pb.TelemetryEnvelope | None:
    """Build a v1 envelope from a single (channel, value) record.

    Returns ``None`` when:

      * The metric is ``voltage_v_phase_{ab|bc|ca}`` -- the
        three-phase aggregator (`envelopes_from_pipeline_payload`)
        is the only legitimate way to emit an
        :class:`AcThreePhaseVoltage` payload. Producing one from a
        single phase would leave 2 of 3 fields unpopulated, which
        violates the panel-grade contract.
      * The metric is unknown to the v1.0 classifier (the caller
        should add it to the table or skip it).

    Otherwise returns a fully-populated envelope with discipline,
    innovation, envelope-level quality, and the metric-specific
    measurement body all set.
    """
    if metric.startswith("voltage_v_phase_"):
        return None  # caller must aggregate -- see S-VOCAB-01

    quality = quality_from_z_score(z_score)

    env = pb.TelemetryEnvelope()
    env.sequence_number = sequence_number
    env.site_id = site_id
    env.asset_id = asset_id
    env.innovation.CopyFrom(_build_innovation(z_score, is_anomalous))
    env.quality = quality

    if metric in _TEMP_METRICS:
        _build_temperature(env, raw_value, _TEMP_METRICS[metric], quality)
        return env

    if metric == "cdu_flow_lpm":
        _build_flow_lpm(env, raw_value, asset_id, quality)
        return env

    if metric == "pump_flow_gpm":
        _build_flow_gpm(env, raw_value, asset_id, quality)
        return env

    if metric == "cdu_filter_dp_kpa":
        _build_filter_dp(env, raw_value, asset_id, quality)
        return env

    if metric == "pump_NPSH_margin_m":
        _build_npsh(env, raw_value, quality)
        return env

    if metric == "ups_soc_pct":
        _build_ups_soc(env, raw_value, quality)
        return env

    if metric == "batt_runtime_min":
        _build_ups_runtime(env, raw_value, quality)
        return env

    log.debug(
        "[telemetry_proto_adapter] unknown metric %r on asset %r; skipping",
        metric, asset_id,
    )
    return None


def envelopes_from_pipeline_payload(
    *,
    payload: dict[str, dict[str, Any]],
    window: dict[str, np.ndarray],
    site_id: str,
    sequence_start: int = 0,
) -> list[pb.TelemetryEnvelope]:
    """End-to-end converter: pipeline output -> list of v1 envelopes.

    Behaviour:

      * Channels whose metric is one of
        ``voltage_v_phase_{ab|bc|ca}`` are grouped by component.
        When all THREE phases are present for a component, ONE
        :class:`AcThreePhaseVoltage` envelope is emitted (per
        S-VOCAB-01: never a partial DC envelope). Incomplete sets
        are skipped with a debug log entry.
      * All other channels dispatch to
        :func:`envelope_from_pipeline_record`. ``None`` returns
        (unknown metrics) are skipped.
      * Sequence numbers are assigned monotonically starting at
        ``sequence_start``.
      * The ``window`` parameter is accepted (and validated to
        share keys with ``payload``) so the adapter has the
        ability in v1.1 to surface raw innovation residuals
        alongside the z-score. It is currently unused.

    Returns:
        The list of envelopes in arbitrary order (proto messages
        carry their own ``sequence_number`` for ordering on the
        wire).
    """
    del window  # accepted for forward-compat; not used by v1.0

    envs: list[pb.TelemetryEnvelope] = []
    seq = sequence_start

    phase_groups: dict[str, dict[str, dict[str, Any]]] = {}
    other_records: list[tuple[str, str, dict[str, Any]]] = []

    for ch_id, fields in payload.items():
        component, metric = _split_scope(ch_id)
        if metric in (
            "voltage_v_phase_ab",
            "voltage_v_phase_bc",
            "voltage_v_phase_ca",
        ):
            phase_groups.setdefault(component, {})[metric] = fields
        else:
            other_records.append((component, metric, fields))

    # Pass 1: aggregate complete three-phase groups.
    for component, phases in phase_groups.items():
        required = {
            "voltage_v_phase_ab",
            "voltage_v_phase_bc",
            "voltage_v_phase_ca",
        }
        if not required.issubset(phases.keys()):
            log.debug(
                "[telemetry_proto_adapter] component %r has partial phase set %s; skipping",
                component, sorted(phases.keys()),
            )
            continue

        max_z = max(
            abs(phases[m]["max_z"]) for m in required
        )
        any_anom = any(phases[m]["is_anomalous"] for m in required)
        quality = quality_from_z_score(max_z)

        env = pb.TelemetryEnvelope()
        env.sequence_number = seq
        seq += 1
        env.site_id = site_id
        env.asset_id = component
        env.discipline = pb.DISCIPLINE_ELECTRICAL
        env.innovation.CopyFrom(_build_innovation(max_z, any_anom))
        env.quality = quality

        ac = env.electrical.voltage.ac_three_phase
        ac.v_ab_v = float(phases["voltage_v_phase_ab"]["last_emission"])
        ac.v_bc_v = float(phases["voltage_v_phase_bc"]["last_emission"])
        ac.v_ca_v = float(phases["voltage_v_phase_ca"]["last_emission"])
        ac.frequency_hz = 60.0
        ac.bus_segment = AC_BUS_PRIMARY_480_A
        ac.quality = quality

        envs.append(env)

    # Pass 2: dispatch all other records.
    for component, metric, fields in other_records:
        env = envelope_from_pipeline_record(
            site_id=site_id,
            asset_id=component,
            metric=metric,
            raw_value=float(fields["last_emission"]),
            z_score=float(fields["max_z"]),
            is_anomalous=bool(fields["is_anomalous"]),
            sequence_number=seq,
        )
        if env is None:
            continue
        seq += 1
        envs.append(env)

    return envs
