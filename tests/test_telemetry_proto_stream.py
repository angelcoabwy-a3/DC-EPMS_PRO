"""
tests/test_telemetry_proto_stream.py
====================================
Tests for the SSE encoder helper at
``backend/telemetry_proto_stream.py``. The helper is the seam
between the adapter (`envelopes_from_pipeline_payload`) and the
FastAPI endpoint -- it converts a list of v1
:class:`TelemetryEnvelope` objects into the JSON payload that
rides on each SSE ``data:`` line.

Tested in isolation (no FastAPI / no live backend) so the encoder
is auditable from a clean Python environment. The endpoint
integration is validated by live smoke after backend restart per
``S-RUNTIME-01``.

Skills exercised:
  S-TELEMETRY-01  (wire-format invariants are preserved end-to-end)
  S-VOCAB-01      (vocab fence travels through serialisation)
  S-DET-01        (encoder is pure-Python deterministic)
  S-TEST-01       (pytest floor + targeted-first)
"""
from __future__ import annotations

import base64
import json
import time

import numpy as np
import pytest

from backend.telemetry_proto.v1 import telemetry_pb2 as pb
from backend.telemetry_proto_adapter import envelopes_from_pipeline_payload
from backend.telemetry_proto_stream import (
    SSE_PROTO_SCHEMA_TAG,
    encode_envelopes_for_sse,
    proto_tick_payload,
)


def _make_envelope(*, asset_id: str = "rack_001", temperature_c: float = 25.0) -> pb.TelemetryEnvelope:
    """Build a small valid envelope for tests."""
    env = pb.TelemetryEnvelope()
    env.sequence_number = 1
    env.site_id = "a3-alpha-toronto"
    env.asset_id = asset_id
    env.discipline = pb.DISCIPLINE_THERMAL
    env.quality = pb.QUALITY_GOOD
    env.thermal.temperature.location = pb.TEMP_RACK_INLET
    env.thermal.temperature.temperature_k = temperature_c + 273.15
    env.thermal.temperature.quality = pb.QUALITY_GOOD
    return env


# ─── Block A -- encode_envelopes_for_sse JSON shape ───────────────────────


class TestEncodeEnvelopesShape:

    def test_payload_is_valid_json(self):
        env = _make_envelope()
        payload = encode_envelopes_for_sse([env], anomaly_count_60min=0)
        # MUST parse cleanly as JSON.
        obj = json.loads(payload)
        assert isinstance(obj, dict)

    def test_payload_carries_schema_tag(self):
        env = _make_envelope()
        payload = encode_envelopes_for_sse([env], anomaly_count_60min=0)
        obj = json.loads(payload)
        assert obj["schema"] == SSE_PROTO_SCHEMA_TAG
        # Schema tag MUST be versioned so old/new consumers don't collide.
        assert "v1" in SSE_PROTO_SCHEMA_TAG

    def test_payload_carries_envelopes_field_as_list_of_strings(self):
        env = _make_envelope()
        payload = encode_envelopes_for_sse([env], anomaly_count_60min=0)
        obj = json.loads(payload)
        assert isinstance(obj["envelopes"], list)
        assert all(isinstance(e, str) for e in obj["envelopes"])

    def test_payload_carries_anomaly_count(self):
        env = _make_envelope()
        payload = encode_envelopes_for_sse([env], anomaly_count_60min=7)
        obj = json.loads(payload)
        assert obj["anomaly_count_60min"] == 7

    def test_payload_carries_unix_timestamp(self):
        env = _make_envelope()
        t_before = time.time()
        payload = encode_envelopes_for_sse([env], anomaly_count_60min=0)
        t_after = time.time()
        obj = json.loads(payload)
        assert t_before <= obj["ts"] <= t_after

    def test_empty_list_emits_empty_envelopes_array(self):
        payload = encode_envelopes_for_sse([], anomaly_count_60min=0)
        obj = json.loads(payload)
        assert obj["envelopes"] == []
        # Schema + count + ts still present so consumers can detect a tick.
        assert obj["schema"] == SSE_PROTO_SCHEMA_TAG
        assert obj["anomaly_count_60min"] == 0


# ─── Block B -- base64 envelope round-trip ────────────────────────────────


class TestEnvelopeRoundTrip:
    """Each envelope on the wire MUST decode back to the original
    proto message bit-for-bit. This is the panel-grade contract: the
    schema invariants enforced by tests/test_telemetry_proto_schema.py
    travel through serialisation."""

    def test_single_envelope_round_trips_through_base64(self):
        env = _make_envelope(asset_id="chiller_1", temperature_c=6.8)
        payload = encode_envelopes_for_sse([env], anomaly_count_60min=0)
        obj = json.loads(payload)
        wire_b64 = obj["envelopes"][0]
        decoded = pb.TelemetryEnvelope.FromString(
            base64.b64decode(wire_b64)
        )
        assert decoded.asset_id == "chiller_1"
        assert decoded.discipline == pb.DISCIPLINE_THERMAL
        assert decoded.thermal.temperature.temperature_k == pytest.approx(279.95)

    def test_multiple_envelopes_round_trip_preserving_order(self):
        envs = [
            _make_envelope(asset_id=f"rack_{i:03d}", temperature_c=20.0 + i)
            for i in range(5)
        ]
        for i, e in enumerate(envs):
            e.sequence_number = i

        payload = encode_envelopes_for_sse(envs, anomaly_count_60min=0)
        obj = json.loads(payload)
        decoded = [
            pb.TelemetryEnvelope.FromString(base64.b64decode(s))
            for s in obj["envelopes"]
        ]
        assert len(decoded) == 5
        for i, d in enumerate(decoded):
            assert d.sequence_number == i
            assert d.asset_id == f"rack_{i:03d}"

    def test_vocabulary_fence_survives_serialisation(self):
        # A DcUnipolarVoltage envelope serialised + deserialised MUST
        # still be DC unipolar, NOT three-phase. The fence is structural
        # in the schema, but a regression in the encoder could in
        # principle mangle the oneof. This test guards that.
        env = pb.TelemetryEnvelope()
        env.sequence_number = 1
        env.site_id = "a3-alpha"
        env.asset_id = "ups_dc_a"
        env.discipline = pb.DISCIPLINE_ELECTRICAL
        env.quality = pb.QUALITY_GOOD
        dc = env.electrical.voltage.dc_unipolar
        dc.v_dc_bus_v = 800.0
        dc.ripple_ratio = 0.005
        dc.quality = pb.QUALITY_GOOD

        payload = encode_envelopes_for_sse([env], anomaly_count_60min=0)
        obj = json.loads(payload)
        decoded = pb.TelemetryEnvelope.FromString(
            base64.b64decode(obj["envelopes"][0])
        )
        assert decoded.electrical.voltage.HasField("dc_unipolar")
        assert not decoded.electrical.voltage.HasField("ac_three_phase")
        assert decoded.electrical.voltage.dc_unipolar.v_dc_bus_v == 800.0


# ─── Block C -- end-to-end pipeline -> adapter -> encoder ─────────────────


class TestProtoTickPayloadEndToEnd:
    """`proto_tick_payload(payload, window, anomaly_count_60min, site_id)`
    is the one-shot helper the SSE endpoint calls per tick. It is
    `envelopes_from_pipeline_payload(...)` composed with
    `encode_envelopes_for_sse(...)`."""

    def test_payload_with_mixed_channels_produces_expected_envelope_count(self):
        pipeline_payload = {
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
        }
        window = {
            k: np.array([v["last_emission"]])
            for k, v in pipeline_payload.items()
        }
        s = proto_tick_payload(
            payload=pipeline_payload, window=window,
            anomaly_count_60min=3, site_id="a3-alpha",
        )
        obj = json.loads(s)
        # 3-phase aggregate (1) + gpu_Tj (1) + flow (1) = 3 envelopes
        assert len(obj["envelopes"]) == 3
        assert obj["anomaly_count_60min"] == 3
        assert obj["schema"] == SSE_PROTO_SCHEMA_TAG

    def test_proto_tick_payload_matches_adapter_output(self):
        # Defensive: the helper composition MUST agree with the
        # adapter direct call.
        pipeline_payload = {
            "rack_001:gpu_Tj_c": {
                "max_z": 1.0, "mean_z": 0.5, "is_anomalous": False,
                "last_emission": 68.0, "n_emissions": 1,
                "escalation_required": False,
            },
        }
        window = {"rack_001:gpu_Tj_c": np.array([68.0])}
        direct_envs = envelopes_from_pipeline_payload(
            payload=pipeline_payload, window=window, site_id="a3-alpha",
        )
        s = proto_tick_payload(
            payload=pipeline_payload, window=window,
            anomaly_count_60min=0, site_id="a3-alpha",
        )
        obj = json.loads(s)
        # Decode the envelope from the tick payload, compare to direct.
        wire_b64 = obj["envelopes"][0]
        decoded = pb.TelemetryEnvelope.FromString(base64.b64decode(wire_b64))
        d = direct_envs[0]
        assert decoded.discipline == d.discipline
        assert decoded.asset_id == d.asset_id
        assert decoded.thermal.temperature.temperature_k == pytest.approx(
            d.thermal.temperature.temperature_k
        )

    def test_empty_pipeline_payload_yields_zero_envelopes(self):
        s = proto_tick_payload(
            payload={}, window={},
            anomaly_count_60min=0, site_id="a3-alpha",
        )
        obj = json.loads(s)
        assert obj["envelopes"] == []
        assert obj["anomaly_count_60min"] == 0
