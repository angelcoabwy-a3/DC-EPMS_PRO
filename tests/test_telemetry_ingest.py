"""Edge ingest endpoint tests (gateway-rs phase 2 Batch C).

Covers the Python mirror of the gateway's length-prefix framing, the
ingest endpoint's defensive rejections, the EdgeChannelStore admission
rules, and — non-negotiable — the vocabulary fence: a DC envelope
surfaces v_dc_bus_v and can never surface phase fields
(S-TELEMETRY-01 / S-VOCAB-01 on the receive side).
"""
from __future__ import annotations

import struct

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.telemetry_ingest_routes import (
    INGEST_CONTENT_TYPE,
    parse_framed_batch,
    register_telemetry_ingest,
)
from backend.telemetry_proto.v1 import telemetry_pb2 as pb


# ─── envelope builders (the gateway's output, hand-rolled) ───────────
def dc_envelope(seq: int = 1, volts: float = 800.0) -> pb.TelemetryEnvelope:
    env = pb.TelemetryEnvelope()
    env.discipline = pb.DISCIPLINE_ELECTRICAL
    env.sequence_number = seq
    env.site_id = "a3-alpha-toronto"
    env.asset_id = "dc_bus_d"
    env.quality = pb.QUALITY_SIMULATED
    env.electrical.voltage.dc_unipolar.v_dc_bus_v = volts
    env.electrical.voltage.dc_unipolar.quality = pb.QUALITY_SIMULATED
    env.emitted_at.GetCurrentTime()
    return env


def ac_envelope(seq: int = 2) -> pb.TelemetryEnvelope:
    env = pb.TelemetryEnvelope()
    env.discipline = pb.DISCIPLINE_ELECTRICAL
    env.sequence_number = seq
    env.site_id = "a3-alpha-toronto"
    env.asset_id = "utility_intake_d"
    env.quality = pb.QUALITY_SIMULATED
    ac = env.electrical.voltage.ac_three_phase
    ac.v_ab_v = 35000.0
    ac.v_bc_v = 35010.0
    ac.v_ca_v = 34990.0
    ac.frequency_hz = 60.0
    ac.bus_segment = pb.AC_BUS_UTILITY_MV
    return env


def thermal_envelope(seq: int = 3) -> pb.TelemetryEnvelope:
    env = pb.TelemetryEnvelope()
    env.discipline = pb.DISCIPLINE_THERMAL
    env.sequence_number = seq
    env.site_id = "a3-alpha-toronto"
    env.asset_id = "cdu_a_01"
    env.quality = pb.QUALITY_SIMULATED
    t = env.thermal.temperature
    t.location = pb.TEMP_DLC_SUPPLY
    t.temperature_k = 291.15
    t.approach_to_dewpoint_k = 10.0
    return env


def frame(envelopes: list[pb.TelemetryEnvelope]) -> bytes:
    body = b""
    for env in envelopes:
        raw = env.SerializeToString()
        body += struct.pack(">I", len(raw)) + raw
    return body


@pytest.fixture
def stack():
    app = FastAPI()
    store = register_telemetry_ingest(app)
    return TestClient(app), store


def _post(client: TestClient, body: bytes, content_type: str = INGEST_CONTENT_TYPE):
    return client.post(
        "/api/telemetry/ingest/proto",
        content=body,
        headers={"content-type": content_type},
    )


# ─── framing parser (mirror of egress.rs frame_batch) ────────────────
class TestFramedBatchParser:
    def test_roundtrips_a_batch(self):
        envs = [dc_envelope(1), ac_envelope(2), thermal_envelope(3)]
        parsed = parse_framed_batch(frame(envs))
        assert len(parsed) == 3
        assert parsed[0].asset_id == "dc_bus_d"
        assert parsed[2].thermal.temperature.approach_to_dewpoint_k == 10.0

    def test_truncated_envelope_rejected_whole(self):
        body = frame([dc_envelope()])
        with pytest.raises(ValueError, match="truncated"):
            parse_framed_batch(body[:-3])

    def test_truncated_length_prefix_rejected(self):
        with pytest.raises(ValueError, match="length prefix"):
            parse_framed_batch(b"\x00\x01")

    def test_oversized_envelope_declaration_rejected(self):
        body = struct.pack(">I", 10 * 1024 * 1024) + b"x"
        with pytest.raises(ValueError, match="cap"):
            parse_framed_batch(body)

    def test_empty_body_is_an_empty_batch(self):
        assert parse_framed_batch(b"") == []


# ─── ingest endpoint ─────────────────────────────────────────────────
class TestIngestEndpoint:
    def test_accepts_a_gateway_batch(self, stack):
        client, store = stack
        r = _post(client, frame([dc_envelope(), ac_envelope(), thermal_envelope()]))
        assert r.status_code == 200
        body = r.json()
        assert body["accepted"] == 3
        assert body["rejected"] == 0
        assert body["edge_channels"] == 3
        assert store.envelopes_accepted == 3

    def test_wrong_content_type_is_415(self, stack):
        client, _ = stack
        r = _post(client, frame([dc_envelope()]), content_type="application/json")
        assert r.status_code == 415

    def test_corrupt_body_is_400_and_nothing_admitted(self, stack):
        client, store = stack
        r = _post(client, frame([dc_envelope()])[:-2])
        assert r.status_code == 400
        assert store.envelopes_accepted == 0

    def test_envelope_without_payload_is_rejected_not_fatal(self, stack):
        client, _ = stack
        bare = pb.TelemetryEnvelope()
        bare.site_id = "a3-alpha-toronto"
        bare.asset_id = "ghost"
        r = _post(client, frame([bare, dc_envelope()]))
        assert r.status_code == 200
        assert r.json() == {"accepted": 1, "rejected": 1, "edge_channels": 1}

    def test_repeat_polls_update_latest_not_duplicate(self, stack):
        client, _ = stack
        _post(client, frame([dc_envelope(seq=1, volts=800.0)]))
        _post(client, frame([dc_envelope(seq=2, volts=801.4)]))
        snap = client.get("/api/telemetry/edge").json()
        assert snap["channel_count"] == 1
        ch = snap["channels"][0]
        assert ch["updates"] == 2
        assert ch["sequence_number"] == 2
        assert ch["values"]["v_dc_bus_v"] == 801.4


# ─── vocabulary fence on the receive side ────────────────────────────
class TestVocabularyFenceOnIngest:
    def test_dc_channel_surfaces_v_dc_bus_v_and_no_phases(self, stack):
        client, _ = stack
        _post(client, frame([dc_envelope()]))
        ch = client.get("/api/telemetry/edge").json()["channels"][0]
        assert ch["kind"] == "electrical.voltage.dc_unipolar"
        assert ch["values"]["v_dc_bus_v"] == 800.0
        # The fence: NO phase key may exist on a DC channel summary.
        forbidden = {"v_ab_v", "v_bc_v", "v_ca_v"}
        assert not forbidden & set(ch["values"]), (
            f"VOCABULARY FENCE BREACH: dc channel carries {forbidden & set(ch['values'])}"
        )

    def test_ac_channel_surfaces_three_phases_and_segment(self, stack):
        client, _ = stack
        _post(client, frame([ac_envelope()]))
        ch = client.get("/api/telemetry/edge").json()["channels"][0]
        assert ch["kind"] == "electrical.voltage.ac_three_phase"
        assert ch["values"]["v_ab_v"] == 35000.0
        assert ch["values"]["bus_segment"] == "AC_BUS_UTILITY_MV"

    def test_dlc_supply_arrives_with_its_mandatory_atd(self, stack):
        client, _ = stack
        _post(client, frame([thermal_envelope()]))
        ch = client.get("/api/telemetry/edge").json()["channels"][0]
        assert ch["kind"] == "thermal.temperature"
        assert ch["values"]["location"] == "TEMP_DLC_SUPPLY"
        assert ch["values"]["approach_to_dewpoint_k"] == 10.0

    def test_bench_data_is_honestly_labeled_simulated(self, stack):
        client, _ = stack
        _post(client, frame([dc_envelope()]))
        ch = client.get("/api/telemetry/edge").json()["channels"][0]
        assert ch["quality"] == "QUALITY_SIMULATED"
