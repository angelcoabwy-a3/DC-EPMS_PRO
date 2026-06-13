"""
backend/telemetry_ingest_routes.py
==================================
Edge ingest endpoint for the v1 telemetry wire format (gateway-rs
phase 2 Batch C). This is the receiving side of the field-edge loop:

    field device --Modbus TCP--> edge/gateway-rs --HTTP POST--> here

Wire framing (mirror of ``edge/gateway-rs/src/egress.rs``)::

    [u32 big-endian length][TelemetryEnvelope bytes] ... repeated

Content-Type: ``application/x-dcepms-telemetry-v1``.

Transport is HTTP POST (NOT gRPC) by design: the canonical
``telemetry.proto`` defines messages only -- adding a ``service`` is a
schema change gated behind RFC + ADR. The envelopes on the wire ARE
the canonical schema, unmodified.

Scope (honest): ingested envelopes land in an in-memory
``EdgeChannelStore`` (latest value + counters per channel) surfaced at
``GET /api/telemetry/edge`` for ops/HMI visibility. TimescaleDB
persistence and Kalman admission of edge channels are the next bites
of the edge track, not this one.

Skills exercised
----------------
* ``S-TELEMETRY-01`` -- the wire-format invariants are verified on
  ingest: every envelope must decode as a v1 ``TelemetryEnvelope``
  and carry a payload arm.
* ``S-VOCAB-01`` -- the topology oneof travels intact: a DC envelope
  surfaces ``v_dc_bus_v`` (never phase fields); an AC envelope
  surfaces its three phases. The store records which arm arrived.
"""
from __future__ import annotations

import logging
import struct
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.telemetry_proto.v1 import telemetry_pb2 as pb

log = logging.getLogger("dc-epms-pro")

INGEST_CONTENT_TYPE = "application/x-dcepms-telemetry-v1"

# Defensive caps: a single batch from one gateway poll sweep is a
# handful of envelopes; reject obviously hostile/corrupt sizes.
MAX_BATCH_BYTES = 4 * 1024 * 1024
MAX_ENVELOPE_BYTES = 64 * 1024


def parse_framed_batch(body: bytes) -> list[pb.TelemetryEnvelope]:
    """Parse ``[u32be len][envelope bytes]...`` into envelopes.

    Raises ``ValueError`` on any truncation or decode failure --
    a partially-valid batch is rejected whole (no silent loss).
    """
    if len(body) > MAX_BATCH_BYTES:
        raise ValueError(f"batch exceeds {MAX_BATCH_BYTES} bytes")
    envelopes: list[pb.TelemetryEnvelope] = []
    at = 0
    while at < len(body):
        if at + 4 > len(body):
            raise ValueError(f"truncated length prefix at offset {at}")
        (length,) = struct.unpack_from(">I", body, at)
        at += 4
        if length > MAX_ENVELOPE_BYTES:
            raise ValueError(f"envelope declares {length} bytes (cap {MAX_ENVELOPE_BYTES})")
        if at + length > len(body):
            raise ValueError(f"truncated envelope at offset {at} (declared {length} bytes)")
        env = pb.TelemetryEnvelope()
        try:
            env.ParseFromString(body[at : at + length])
        except Exception as e:  # protobuf DecodeError
            raise ValueError(f"envelope decode failed at offset {at}: {e}") from e
        envelopes.append(env)
        at += length
    return envelopes


def _payload_summary(env: pb.TelemetryEnvelope) -> tuple[str, dict[str, Any]] | None:
    """Return ``(channel_kind, headline_values)`` for the envelope's
    payload arm, or None when no payload is set.

    The kind string encodes the full oneof path -- the vocabulary
    fence is therefore VISIBLE in the store: a DC bus reading is
    ``electrical.voltage.dc_unipolar`` and its values carry
    ``v_dc_bus_v``; phase fields can only appear under
    ``...ac_three_phase``.
    """
    arm = env.WhichOneof("payload")
    if arm is None:
        return None

    if arm == "electrical":
        body = env.electrical.WhichOneof("body")
        if body == "voltage":
            topo = env.electrical.voltage.WhichOneof("topology")
            if topo == "dc_unipolar":
                dc = env.electrical.voltage.dc_unipolar
                return ("electrical.voltage.dc_unipolar", {
                    "v_dc_bus_v": dc.v_dc_bus_v,
                    "ripple_ratio": dc.ripple_ratio,
                })
            if topo == "ac_three_phase":
                ac = env.electrical.voltage.ac_three_phase
                return ("electrical.voltage.ac_three_phase", {
                    "v_ab_v": ac.v_ab_v,
                    "v_bc_v": ac.v_bc_v,
                    "v_ca_v": ac.v_ca_v,
                    "frequency_hz": ac.frequency_hz,
                    "bus_segment": pb.AcBusSegment.Name(ac.bus_segment),
                })
            return (f"electrical.voltage.{topo}", {})
        return (f"electrical.{body}", {})

    if arm == "thermal":
        body = env.thermal.WhichOneof("body")
        if body == "temperature":
            t = env.thermal.temperature
            return ("thermal.temperature", {
                "location": pb.TempLocation.Name(t.location),
                "temperature_k": t.temperature_k,
                "approach_to_dewpoint_k": t.approach_to_dewpoint_k,
            })
        return (f"thermal.{body}", {})

    if arm == "mechanical":
        body = env.mechanical.WhichOneof("body")
        if body == "flow":
            f = env.mechanical.flow
            return ("mechanical.flow", {
                "flow_m3_per_s": f.flow_m3_per_s,
                "loop": pb.CoolantLoop.Name(f.loop),
            })
        return (f"mechanical.{body}", {})

    return (arm, {})


class EdgeChannelStore:
    """Latest-value store for edge-ingested channels.

    In-memory by design for this bite (see module docstring). Keyed by
    ``site_id/asset_id/channel_kind``.
    """

    def __init__(self) -> None:
        self._channels: dict[str, dict[str, Any]] = {}
        self.batches_accepted = 0
        self.envelopes_accepted = 0
        self.envelopes_rejected = 0
        self.last_ingest_ts: float | None = None

    def admit(self, env: pb.TelemetryEnvelope) -> bool:
        summary = _payload_summary(env)
        if summary is None or not env.site_id or not env.asset_id:
            self.envelopes_rejected += 1
            return False
        kind, values = summary
        key = f"{env.site_id}/{env.asset_id}/{kind}"
        entry = self._channels.get(key)
        if entry is None:
            entry = {"updates": 0}
            self._channels[key] = entry
        entry["updates"] += 1
        entry.update({
            "site_id": env.site_id,
            "asset_id": env.asset_id,
            "kind": kind,
            "values": values,
            "quality": pb.MeasurementQuality.Name(env.quality),
            "sequence_number": env.sequence_number,
            "emitted_at": env.emitted_at.ToDatetime().isoformat() + "Z"
            if env.HasField("emitted_at") else None,
        })
        self.envelopes_accepted += 1
        return True

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema": "edge_channels_v1",
            "channel_count": len(self._channels),
            "channels": sorted(self._channels.values(), key=lambda c: c["asset_id"]),
            "batches_accepted": self.batches_accepted,
            "envelopes_accepted": self.envelopes_accepted,
            "envelopes_rejected": self.envelopes_rejected,
            "last_ingest_ts": self.last_ingest_ts,
        }


def register_telemetry_ingest(app: FastAPI) -> EdgeChannelStore:
    """Mount POST /api/telemetry/ingest/proto + GET /api/telemetry/edge."""
    store = EdgeChannelStore()

    @app.post("/api/telemetry/ingest/proto")
    async def ingest_proto(request: Request) -> JSONResponse:
        content_type = request.headers.get("content-type", "")
        if not content_type.startswith(INGEST_CONTENT_TYPE):
            return JSONResponse(
                status_code=415,
                content={"detail": f"content-type must be {INGEST_CONTENT_TYPE}"},
            )
        body = await request.body()
        try:
            envelopes = parse_framed_batch(body)
        except ValueError as e:
            return JSONResponse(status_code=400, content={"detail": str(e)})

        accepted = sum(1 for env in envelopes if store.admit(env))
        store.batches_accepted += 1
        store.last_ingest_ts = time.time()
        return JSONResponse(content={
            "accepted": accepted,
            "rejected": len(envelopes) - accepted,
            "edge_channels": len(store._channels),
        })

    @app.get("/api/telemetry/edge")
    async def edge_channels() -> dict[str, Any]:
        return store.snapshot()

    return store
