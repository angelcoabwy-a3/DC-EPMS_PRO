"""
tests/test_telemetry_proto_adapter.py
=====================================
TDD tests for the v1 proto adapter at
``backend/telemetry_proto_adapter.py``.

The adapter is the bridge between the Sprint 5 telemetry pipeline
(engineering-units JSON-shaped dict) and the Epic 8 canonical v1
wire format (strict-SI proto envelopes). It performs:

  1. Unit conversion from engineering units (deg C / kPa / LPM / kW
     / pct / min / m-head) to strict SI (K / Pa / m3/s / W / ratio
     / s / Pa).
  2. Discipline routing per metric (electrical / mechanical /
     thermal / life-safety / combustible).
  3. Channel classification (which message body the value goes
     into: TemperatureMeasurement / VoltageReading / etc.).
  4. 3-phase voltage grouping (voltage_v_phase_ab + bc + ca on the
     same component aggregate into ONE AcThreePhaseVoltage).
  5. MeasurementQuality derivation from the Kalman z-score:
     |z| < 2 -> GOOD, 2 <= |z| < 3 -> DEGRADED, else DEGRADED.
  6. KalmanInnovation propagation onto every envelope.

Skills exercised:
  S-TELEMETRY-01  (wire-format invariants -- envelope MUST be
                   schema-valid)
  S-VOCAB-01      (vocabulary fence -- voltage_v_phase_* MUST
                   route to AcThreePhaseVoltage, NEVER to
                   DcUnipolarVoltage)
  S-DET-01        (pure-Python deterministic; no LLM, no
                   non-determinism)
  S-TEST-01       (pytest floor + targeted-first)
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.telemetry_proto.v1 import telemetry_pb2 as pb
from backend.telemetry_proto_adapter import (
    AC_BUS_PRIMARY_480_A,
    c_to_k,
    envelope_from_pipeline_record,
    envelopes_from_pipeline_payload,
    gpm_to_m3_per_s,
    kpa_to_pa,
    kw_to_w,
    lpm_to_m3_per_s,
    m_head_water_to_pa,
    min_to_s,
    pct_to_ratio,
    quality_from_z_score,
)

# ─── Block A -- unit conversions (strict SI) ──────────────────────────────


class TestUnitConversions:

    def test_celsius_to_kelvin_uses_273_15_offset(self):
        assert c_to_k(0.0) == pytest.approx(273.15)
        assert c_to_k(25.0) == pytest.approx(298.15)
        assert c_to_k(-40.0) == pytest.approx(233.15)

    def test_celsius_to_kelvin_preserves_delta(self):
        # Critical: a 1 K delta is the SAME magnitude as a 1 deg C
        # delta. Only the OFFSET differs. Caller must use c_to_k for
        # absolute readings, NOT for deltas (e.g. ATD margin should
        # be a direct value, not c_to_k(delta)).
        a = c_to_k(20.0)
        b = c_to_k(21.0)
        assert (b - a) == pytest.approx(1.0)

    def test_kpa_to_pa(self):
        assert kpa_to_pa(100.0) == pytest.approx(100_000.0)
        assert kpa_to_pa(22.0) == pytest.approx(22_000.0)
        assert kpa_to_pa(0.0) == 0.0

    def test_lpm_to_m3_per_s(self):
        # 1 LPM = 1 L/min = 0.001 m^3 / 60 s = 1.6667e-5 m^3/s
        assert lpm_to_m3_per_s(60.0) == pytest.approx(0.001)
        assert lpm_to_m3_per_s(180.0) == pytest.approx(0.003)
        assert lpm_to_m3_per_s(0.0) == 0.0

    def test_gpm_to_m3_per_s(self):
        # 1 US gpm = 3.785411784 L/min
        # 1 US gpm = 3.785411784 / 60 / 1000 m^3/s = 6.3090e-5
        assert gpm_to_m3_per_s(1.0) == pytest.approx(6.30901964e-5, rel=1e-6)
        # 4500 gpm baseline -> ~0.284 m^3/s
        assert gpm_to_m3_per_s(4500.0) == pytest.approx(
            6.30901964e-5 * 4500.0, rel=1e-6
        )

    def test_kw_to_w(self):
        assert kw_to_w(0.5) == pytest.approx(500.0)
        assert kw_to_w(2500.0) == pytest.approx(2_500_000.0)

    def test_pct_to_ratio(self):
        assert pct_to_ratio(0.0) == 0.0
        assert pct_to_ratio(50.0) == pytest.approx(0.5)
        assert pct_to_ratio(98.5) == pytest.approx(0.985)
        assert pct_to_ratio(100.0) == pytest.approx(1.0)

    def test_min_to_s(self):
        assert min_to_s(0.0) == 0.0
        assert min_to_s(1.0) == 60.0
        assert min_to_s(15.0) == 900.0

    def test_m_head_water_to_pa_uses_water_density_and_g(self):
        # 1 m of water column at 4 deg C, g=9.80665:
        # P = rho * g * h = 1000 * 9.80665 * 1 = 9806.65 Pa
        assert m_head_water_to_pa(1.0) == pytest.approx(9806.65)
        assert m_head_water_to_pa(3.5) == pytest.approx(9806.65 * 3.5)


# ─── Block B -- MeasurementQuality derivation ─────────────────────────────


class TestQualityFromZScore:

    def test_z_below_two_is_good(self):
        assert quality_from_z_score(0.0) == pb.QUALITY_GOOD
        assert quality_from_z_score(1.0) == pb.QUALITY_GOOD
        assert quality_from_z_score(1.99) == pb.QUALITY_GOOD
        # Negative z -- absolute magnitude is what matters.
        assert quality_from_z_score(-1.5) == pb.QUALITY_GOOD

    def test_z_between_two_and_three_is_degraded(self):
        assert quality_from_z_score(2.0) == pb.QUALITY_DEGRADED
        assert quality_from_z_score(2.5) == pb.QUALITY_DEGRADED
        assert quality_from_z_score(-2.5) == pb.QUALITY_DEGRADED

    def test_z_above_three_is_degraded_not_invalid(self):
        # An anomalous reading is FLAGGED for surface, but the sensor
        # itself isn't proven faulty -- INVALID is reserved for
        # NaN / out-of-range / hardware failures.
        assert quality_from_z_score(3.0) == pb.QUALITY_DEGRADED
        assert quality_from_z_score(10.0) == pb.QUALITY_DEGRADED
        assert quality_from_z_score(-99.0) == pb.QUALITY_DEGRADED

    def test_nan_maps_to_invalid(self):
        assert quality_from_z_score(float("nan")) == pb.QUALITY_INVALID


# ─── Block C -- single-channel envelope construction ──────────────────────


class TestEnvelopeFromPipelineRecord:

    def test_temperature_channel_maps_to_thermal_reading(self):
        env = envelope_from_pipeline_record(
            site_id="a3-alpha-toronto",
            asset_id="chiller_1",
            metric="chiller_LWT_c",
            raw_value=6.8,
            z_score=0.5,
            is_anomalous=False,
            sequence_number=42,
        )
        assert env is not None
        assert env.discipline == pb.DISCIPLINE_THERMAL
        assert env.site_id == "a3-alpha-toronto"
        assert env.asset_id == "chiller_1"
        assert env.sequence_number == 42
        assert env.HasField("thermal")
        assert env.thermal.temperature.temperature_k == pytest.approx(279.95)
        assert env.thermal.temperature.quality == pb.QUALITY_GOOD

    def test_pressure_kpa_channel_maps_to_filter_dp_for_filter_channels(self):
        env = envelope_from_pipeline_record(
            site_id="a3-alpha",
            asset_id="cdu_1",
            metric="cdu_filter_dp_kpa",
            raw_value=22.0,
            z_score=0.2,
            is_anomalous=False,
        )
        assert env is not None
        assert env.discipline == pb.DISCIPLINE_MECHANICAL
        assert env.HasField("mechanical")
        assert env.mechanical.HasField("filter_dp")
        assert env.mechanical.filter_dp.delta_p_pa == pytest.approx(22_000.0)

    def test_flow_lpm_channel_maps_to_flow_measurement_m3_per_s(self):
        env = envelope_from_pipeline_record(
            site_id="a3-alpha",
            asset_id="cdu_1",
            metric="cdu_flow_lpm",
            raw_value=180.0,
            z_score=0.1,
            is_anomalous=False,
        )
        assert env is not None
        assert env.discipline == pb.DISCIPLINE_MECHANICAL
        assert env.mechanical.HasField("flow")
        assert env.mechanical.flow.flow_m3_per_s == pytest.approx(0.003)

    def test_flow_gpm_channel_maps_to_flow_measurement_m3_per_s(self):
        env = envelope_from_pipeline_record(
            site_id="a3-alpha",
            asset_id="pump_a",
            metric="pump_flow_gpm",
            raw_value=4500.0,
            z_score=0.1,
            is_anomalous=False,
        )
        assert env is not None
        assert env.mechanical.HasField("flow")
        # 4500 gpm ≈ 0.2839 m^3/s
        assert env.mechanical.flow.flow_m3_per_s == pytest.approx(
            6.30901964e-5 * 4500.0, rel=1e-5
        )

    def test_npsh_margin_m_channel_maps_to_pump_status(self):
        env = envelope_from_pipeline_record(
            site_id="a3-alpha",
            asset_id="pump_a",
            metric="pump_NPSH_margin_m",
            raw_value=3.5,
            z_score=0.3,
            is_anomalous=False,
        )
        assert env is not None
        assert env.discipline == pb.DISCIPLINE_MECHANICAL
        assert env.mechanical.HasField("pump")
        # 3.5 m water head ≈ 34323 Pa
        assert env.mechanical.pump.npsh_margin_pa == pytest.approx(34_323.275)

    def test_ups_soc_pct_channel_maps_to_battery_health_ratio(self):
        env = envelope_from_pipeline_record(
            site_id="a3-alpha",
            asset_id="ups_a",
            metric="ups_soc_pct",
            raw_value=98.5,
            z_score=0.1,
            is_anomalous=False,
        )
        assert env is not None
        assert env.discipline == pb.DISCIPLINE_ELECTRICAL
        assert env.electrical.HasField("ups_battery")
        assert env.electrical.ups_battery.soc_ratio == pytest.approx(0.985)

    def test_batt_runtime_min_channel_maps_to_battery_health_seconds(self):
        env = envelope_from_pipeline_record(
            site_id="a3-alpha",
            asset_id="ups_a",
            metric="batt_runtime_min",
            raw_value=15.0,
            z_score=0.1,
            is_anomalous=False,
        )
        assert env is not None
        assert env.discipline == pb.DISCIPLINE_ELECTRICAL
        assert env.electrical.HasField("ups_battery")
        assert env.electrical.ups_battery.runtime_s == pytest.approx(900.0)

    def test_unknown_metric_returns_none(self):
        env = envelope_from_pipeline_record(
            site_id="a3-alpha",
            asset_id="x",
            metric="some_uncharted_metric",
            raw_value=42.0,
            z_score=0.0,
            is_anomalous=False,
        )
        assert env is None

    def test_anomalous_reading_carries_kalman_innovation(self):
        env = envelope_from_pipeline_record(
            site_id="a3-alpha",
            asset_id="rack_001",
            metric="gpu_Tj_c",
            raw_value=95.0,
            z_score=4.2,
            is_anomalous=True,
        )
        assert env is not None
        assert env.innovation.normalized_z == pytest.approx(4.2)
        assert env.innovation.is_anomalous is True
        # Envelope-level quality reflects the channel's quality.
        assert env.thermal.temperature.quality == pb.QUALITY_DEGRADED


# ─── Block D -- 3-phase voltage grouping (vocabulary fence enforced) ──────


class TestThreePhaseVoltageGrouping:

    def test_three_phase_channels_aggregate_into_ac_three_phase_voltage(self):
        payload = {
            "ups_a:voltage_v_phase_ab": {
                "max_z": 0.5, "mean_z": 0.3, "is_anomalous": False,
                "last_emission": 480.2, "n_emissions": 1,
                "escalation_required": False,
            },
            "ups_a:voltage_v_phase_bc": {
                "max_z": 0.6, "mean_z": 0.4, "is_anomalous": False,
                "last_emission": 479.8, "n_emissions": 1,
                "escalation_required": False,
            },
            "ups_a:voltage_v_phase_ca": {
                "max_z": 0.4, "mean_z": 0.2, "is_anomalous": False,
                "last_emission": 480.1, "n_emissions": 1,
                "escalation_required": False,
            },
        }
        window = {k: np.array([v["last_emission"]]) for k, v in payload.items()}

        envs = envelopes_from_pipeline_payload(
            payload=payload, window=window, site_id="a3-alpha",
        )

        # Exactly ONE envelope -- the three phase channels collapsed.
        assert len(envs) == 1
        env = envs[0]
        assert env.discipline == pb.DISCIPLINE_ELECTRICAL
        assert env.asset_id == "ups_a"
        assert env.electrical.HasField("voltage")
        assert env.electrical.voltage.HasField("ac_three_phase")
        ac = env.electrical.voltage.ac_three_phase
        assert ac.v_ab_v == pytest.approx(480.2)
        assert ac.v_bc_v == pytest.approx(479.8)
        assert ac.v_ca_v == pytest.approx(480.1)
        assert ac.bus_segment == AC_BUS_PRIMARY_480_A

    def test_three_phase_envelope_uses_max_z_for_quality(self):
        payload = {
            "ups_b:voltage_v_phase_ab": {
                "max_z": 2.4, "mean_z": 1.2, "is_anomalous": False,
                "last_emission": 485.0, "n_emissions": 1,
                "escalation_required": False,
            },
            "ups_b:voltage_v_phase_bc": {
                "max_z": 0.5, "mean_z": 0.3, "is_anomalous": False,
                "last_emission": 478.0, "n_emissions": 1,
                "escalation_required": False,
            },
            "ups_b:voltage_v_phase_ca": {
                "max_z": 0.6, "mean_z": 0.4, "is_anomalous": False,
                "last_emission": 480.0, "n_emissions": 1,
                "escalation_required": False,
            },
        }
        window = {k: np.array([v["last_emission"]]) for k, v in payload.items()}
        envs = envelopes_from_pipeline_payload(
            payload=payload, window=window, site_id="a3-alpha",
        )
        assert len(envs) == 1
        # max(|z|) = 2.4 -> DEGRADED.
        assert envs[0].electrical.voltage.ac_three_phase.quality == pb.QUALITY_DEGRADED

    def test_incomplete_three_phase_set_skips_aggregate(self):
        # Only AB + BC, missing CA -- adapter SHOULD NOT emit a half-
        # populated AcThreePhaseVoltage. Skip with no panic.
        payload = {
            "ups_a:voltage_v_phase_ab": {
                "max_z": 0.5, "mean_z": 0.3, "is_anomalous": False,
                "last_emission": 480.2, "n_emissions": 1,
                "escalation_required": False,
            },
            "ups_a:voltage_v_phase_bc": {
                "max_z": 0.6, "mean_z": 0.4, "is_anomalous": False,
                "last_emission": 479.8, "n_emissions": 1,
                "escalation_required": False,
            },
        }
        window = {k: np.array([v["last_emission"]]) for k, v in payload.items()}
        envs = envelopes_from_pipeline_payload(
            payload=payload, window=window, site_id="a3-alpha",
        )
        assert envs == []

    def test_three_phase_aggregate_never_emits_dc_unipolar(self):
        # S-VOCAB-01 fence: a voltage_v_phase_* channel MUST NEVER
        # produce a DcUnipolarVoltage payload. Adding such a code
        # path is a credibility-destroying error.
        payload = {
            "ups_a:voltage_v_phase_ab": {
                "max_z": 0.5, "mean_z": 0.3, "is_anomalous": False,
                "last_emission": 480.2, "n_emissions": 1,
                "escalation_required": False,
            },
            "ups_a:voltage_v_phase_bc": {
                "max_z": 0.5, "mean_z": 0.3, "is_anomalous": False,
                "last_emission": 479.8, "n_emissions": 1,
                "escalation_required": False,
            },
            "ups_a:voltage_v_phase_ca": {
                "max_z": 0.5, "mean_z": 0.3, "is_anomalous": False,
                "last_emission": 480.1, "n_emissions": 1,
                "escalation_required": False,
            },
        }
        window = {k: np.array([v["last_emission"]]) for k, v in payload.items()}
        envs = envelopes_from_pipeline_payload(
            payload=payload, window=window, site_id="a3-alpha",
        )
        assert len(envs) == 1
        # The dc_unipolar variant must NOT be populated.
        assert not envs[0].electrical.voltage.HasField("dc_unipolar")
        # The ac_three_phase variant must be populated.
        assert envs[0].electrical.voltage.HasField("ac_three_phase")


# ─── Block E -- end-to-end pipeline → envelopes ───────────────────────────


class TestEnvelopesFromPipelinePayload:

    def test_mixed_payload_produces_correct_envelope_count(self):
        # 3 phase voltages on ups_a -> 1 envelope
        # 1 temp on rack_001        -> 1 envelope
        # 1 flow on cdu_1           -> 1 envelope
        # 1 unknown metric          -> 0 envelopes
        # Total: 3
        payload = {
            "ups_a:voltage_v_phase_ab": {
                "max_z": 0.5, "mean_z": 0.3, "is_anomalous": False,
                "last_emission": 480.0, "n_emissions": 1,
                "escalation_required": False,
            },
            "ups_a:voltage_v_phase_bc": {
                "max_z": 0.5, "mean_z": 0.3, "is_anomalous": False,
                "last_emission": 480.0, "n_emissions": 1,
                "escalation_required": False,
            },
            "ups_a:voltage_v_phase_ca": {
                "max_z": 0.5, "mean_z": 0.3, "is_anomalous": False,
                "last_emission": 480.0, "n_emissions": 1,
                "escalation_required": False,
            },
            "rack_001:gpu_Tj_c": {
                "max_z": 1.0, "mean_z": 0.5, "is_anomalous": False,
                "last_emission": 68.0, "n_emissions": 1,
                "escalation_required": False,
            },
            "cdu_1:cdu_flow_lpm": {
                "max_z": 0.4, "mean_z": 0.2, "is_anomalous": False,
                "last_emission": 180.0, "n_emissions": 1,
                "escalation_required": False,
            },
            "x:some_uncharted_metric": {
                "max_z": 0.0, "mean_z": 0.0, "is_anomalous": False,
                "last_emission": 42.0, "n_emissions": 1,
                "escalation_required": False,
            },
        }
        window = {k: np.array([v["last_emission"]]) for k, v in payload.items()}

        envs = envelopes_from_pipeline_payload(
            payload=payload, window=window, site_id="a3-alpha",
        )
        assert len(envs) == 3

    def test_sequence_numbers_are_monotonic_and_start_at_param(self):
        payload = {
            "rack_001:gpu_Tj_c": {
                "max_z": 0.0, "mean_z": 0.0, "is_anomalous": False,
                "last_emission": 68.0, "n_emissions": 1,
                "escalation_required": False,
            },
            "rack_002:gpu_Tj_c": {
                "max_z": 0.0, "mean_z": 0.0, "is_anomalous": False,
                "last_emission": 70.0, "n_emissions": 1,
                "escalation_required": False,
            },
        }
        window = {k: np.array([v["last_emission"]]) for k, v in payload.items()}
        envs = envelopes_from_pipeline_payload(
            payload=payload, window=window, site_id="a3-alpha",
            sequence_start=1000,
        )
        seqs = sorted(e.sequence_number for e in envs)
        assert seqs == [1000, 1001]

    def test_envelopes_serialize_and_round_trip(self):
        # The adapter output MUST be a valid protobuf wire payload.
        # Serialize + parse should yield identical content.
        payload = {
            "rack_001:gpu_Tj_c": {
                "max_z": 0.7, "mean_z": 0.4, "is_anomalous": False,
                "last_emission": 68.5, "n_emissions": 1,
                "escalation_required": False,
            },
        }
        window = {k: np.array([v["last_emission"]]) for k, v in payload.items()}
        envs = envelopes_from_pipeline_payload(
            payload=payload, window=window, site_id="a3-alpha",
        )
        wire = envs[0].SerializeToString()
        round_trip = pb.TelemetryEnvelope.FromString(wire)
        assert round_trip.thermal.temperature.temperature_k == pytest.approx(
            envs[0].thermal.temperature.temperature_k
        )
        assert round_trip.discipline == envs[0].discipline
        assert round_trip.asset_id == envs[0].asset_id

    def test_unscoped_channel_id_uses_metric_as_asset_id(self):
        # Channels without a "component:metric" scope fall back to
        # treating the channel_id as both the metric and the
        # asset_id (rare, but the simulator emits some this way).
        payload = {
            "gpu_Tj_c": {
                "max_z": 0.0, "mean_z": 0.0, "is_anomalous": False,
                "last_emission": 70.0, "n_emissions": 1,
                "escalation_required": False,
            },
        }
        window = {"gpu_Tj_c": np.array([70.0])}
        envs = envelopes_from_pipeline_payload(
            payload=payload, window=window, site_id="a3-alpha",
        )
        # The adapter still emits an envelope -- asset_id == metric is
        # a degenerate but acceptable shape.
        assert len(envs) == 1
        assert envs[0].asset_id == "gpu_Tj_c"


# ─── Block F -- schema invariants held end-to-end ─────────────────────────


class TestSchemaInvariantsOnAdapterOutput:
    """Cross-check: an adapter envelope MUST satisfy the same invariants
    the .proto schema tests enforce. If the proto schema gains a rule,
    the adapter MUST already comply -- this block is the gate."""

    def test_envelope_has_non_default_discipline(self):
        env = envelope_from_pipeline_record(
            site_id="a3", asset_id="x", metric="chiller_LWT_c",
            raw_value=6.8, z_score=0.0, is_anomalous=False,
        )
        assert env.discipline != pb.DISCIPLINE_UNSPECIFIED

    def test_envelope_carries_measurement_quality(self):
        env = envelope_from_pipeline_record(
            site_id="a3", asset_id="x", metric="chiller_LWT_c",
            raw_value=6.8, z_score=0.0, is_anomalous=False,
        )
        # Quality is on the inner measurement message.
        assert env.thermal.temperature.quality != pb.QUALITY_UNSPECIFIED

    def test_temperature_unit_is_kelvin_not_celsius(self):
        # If the adapter forgets c_to_k, this test fails: 6.8 K is
        # cryogenic; 279.95 K is chilled water.
        env = envelope_from_pipeline_record(
            site_id="a3", asset_id="x", metric="chiller_LWT_c",
            raw_value=6.8, z_score=0.0, is_anomalous=False,
        )
        assert env.thermal.temperature.temperature_k > 200.0, (
            "Adapter MUST convert C -> K (strict SI). A value <200 "
            "is suspiciously close to the raw deg C reading."
        )

    def test_flow_unit_is_m3_per_s_not_lpm(self):
        env = envelope_from_pipeline_record(
            site_id="a3", asset_id="cdu_1", metric="cdu_flow_lpm",
            raw_value=180.0, z_score=0.0, is_anomalous=False,
        )
        # 180 LPM -> 0.003 m3/s. If the adapter passes through raw
        # without conversion, the value would still be 180 (LPM
        # interpreted as m3/s = 180 m3/s, a Niagara Falls flow).
        assert env.mechanical.flow.flow_m3_per_s < 1.0, (
            "Adapter MUST convert LPM -> m3/s (strict SI)"
        )
