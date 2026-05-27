"""
backend/telemetry_proto_stream.py
=================================
SSE encoder for the v1 telemetry wire format.

This module is the seam between the proto adapter
(:func:`envelopes_from_pipeline_payload`) and the FastAPI SSE
endpoint at ``/api/telemetry/stream/proto``. Each pipeline tick
produces a list of :class:`TelemetryEnvelope` messages; this
module serialises them to wire-format bytes, base64-encodes for
SSE transport (which is text-only -- ``data:`` lines may not
contain raw binary), and wraps the batch in a JSON envelope that
also carries tick-level metadata (timestamp + rolling anomaly
count).

Wire shape on each SSE event::

    data: {"schema": "telemetry_envelopes_v1",
           "envelopes": ["<base64-encoded-bytes>", ...],
           "anomaly_count_60min": <int>,
           "ts": <unix-seconds-float>}

The schema tag is REQUIRED (versioned) so older consumers cannot
mis-decode the binary payload. Empty ``envelopes`` arrays are
emitted on quiescent ticks so the consumer learns of the
heartbeat without inferring it from silence.

Skills exercised
----------------

* ``S-TELEMETRY-01`` -- wire-format invariants travel through
  serialisation. The base64-encoded bytes are a valid
  :class:`TelemetryEnvelope` round-trip.
* ``S-VOCAB-01``     -- the vocabulary fence (DC unipolar vs AC
  three-phase) survives the encoding boundary.
* ``S-DET-01``       -- pure-Python deterministic. No I/O, no
  LLM, no time-of-day side effects except the explicit
  ``ts`` field.
"""
from __future__ import annotations

import base64
import json
import time
from typing import Any

import numpy as np

from backend.telemetry_proto.v1 import telemetry_pb2 as pb
from backend.telemetry_proto_adapter import envelopes_from_pipeline_payload

# Versioned schema tag. Consumers MUST gate decoding on this value.
# If the wire format is ever changed in a way that affects layout,
# bump the version suffix here AND in the consumer.
SSE_PROTO_SCHEMA_TAG = "telemetry_envelopes_v1"


def encode_envelopes_for_sse(
    envelopes: list[pb.TelemetryEnvelope],
    *,
    anomaly_count_60min: int,
) -> str:
    """Serialize a batch of envelopes to the JSON payload that one
    SSE ``data:`` line carries.

    Parameters
    ----------
    envelopes :
        The v1 envelopes produced for this tick. May be empty
        (quiescent tick); the caller still wants a heartbeat
        event so the consumer knows the stream is alive.
    anomaly_count_60min :
        Rolling 60-min unique-channel anomaly count from the
        pipeline. Emitted alongside the batch so consumers can
        update an activity widget without a separate query.

    Returns
    -------
    A JSON string (NOT bytes; SSE ``data:`` lines are text).
    """
    return json.dumps({
        "schema": SSE_PROTO_SCHEMA_TAG,
        "envelopes": [
            base64.b64encode(env.SerializeToString()).decode("ascii")
            for env in envelopes
        ],
        "anomaly_count_60min": int(anomaly_count_60min),
        "ts": time.time(),
    })


def proto_tick_payload(
    *,
    payload: dict[str, dict[str, Any]],
    window: dict[str, np.ndarray],
    anomaly_count_60min: int,
    site_id: str,
    sequence_start: int = 0,
) -> str:
    """End-to-end one-shot helper: pipeline output -> SSE JSON line.

    Composes :func:`envelopes_from_pipeline_payload` (adapter) with
    :func:`encode_envelopes_for_sse` (encoder). The SSE endpoint
    calls this once per tick.

    Parameters
    ----------
    payload :
        The dict returned by ``TelemetryPipeline.compute(window)``.
    window :
        The raw simulator window passed through to the adapter
        (currently unused by v1.0 but kept for forward-compat).
    anomaly_count_60min :
        Same value the JSON endpoint emits in its
        ``anomaly_count_60min`` field.
    site_id :
        Constant for the deployment (e.g. ``"a3-alpha-toronto"``).
    sequence_start :
        Monotonic sequence anchor for this tick. The endpoint
        should pass an ever-growing counter so consumers can
        detect dropped ticks.

    Returns
    -------
    A JSON string ready to be wrapped in an SSE ``data: ...\\n\\n``
    line.
    """
    envs = envelopes_from_pipeline_payload(
        payload=payload,
        window=window,
        site_id=site_id,
        sequence_start=sequence_start,
    )
    return encode_envelopes_for_sse(
        envs,
        anomaly_count_60min=anomaly_count_60min,
    )
