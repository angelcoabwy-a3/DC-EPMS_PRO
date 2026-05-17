"""
hermes.py — ROADMAP V11 T3.1: Project Hermes WebSocket telemetry pipeline.

A multiplexed, real-time push channel for live operational state.

Multiplexed frame envelope
--------------------------
Every message on the socket is a JSON object:

    {
        "stream":  "<logical channel>",   # telemetry | hermes | cmms | ...
        "seq":     <int>,                 # monotonic counter
        "ts":      <float unix seconds>,
        "payload": { ... }                # stream-specific body
    }

A single socket carries any number of logical streams; the client
demultiplexes on `stream`.

Telemetry source — LIVE Kalman pipeline tap
-------------------------------------------
`_real_telemetry_frame()` taps the same `telemetry_simulator` +
`telemetry_pipeline` (Kalman + Send-on-Delta) singletons the legacy SSE
endpoint drives, and emits the identical `channel_innovations` payload —
so the frontend dispatch is byte-compatible across the SSE -> WS cutover.
If the simulator / site model is unavailable the producer degrades to a
representative `legacy_kpi` frame rather than starving the stream.

Broadcast model
---------------
One shared `_broadcast_loop` computes a telemetry tick once and fans it
out via `ConnectionManager.broadcast()` — the Kalman pipeline is stepped
exactly once per tick regardless of how many dashboards are connected.
The loop is started on the first connection and cancelled when the last
client leaves.

Mounted by backend/main.py:  app.include_router(hermes.router)
Endpoint:  WS /api/hermes
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import pathlib
import random
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)

router = APIRouter()

# backend/hermes.py -> project root is parent.parent
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Telemetry tick interval (seconds). 5 s matches the Kalman pipeline
# cadence (one get_window(n_samples=5) per tick). Module-level so tests
# can shrink it.
HERMES_TICK_SECONDS = 5.0

# Path C2 steady-state baselines for the representative fallback frame.
_PUE_BASE = 1.10
_IT_LOAD_BASE_KW = 16756.0
_HALL_TEMP_BASE_C = 22.6
_DELTA_T_BASE_C = 4.6


# ─────────────────────────────────────────────────────────────────────
#  Multiplexed frame envelope
# ─────────────────────────────────────────────────────────────────────
def build_frame(stream: str, payload: dict, seq: int = 0) -> dict:
    """Wrap a payload in the multiplexed Hermes envelope."""
    return {
        "stream": stream,
        "seq": int(seq),
        "ts": time.time(),
        "payload": payload,
    }


# ─────────────────────────────────────────────────────────────────────
#  Connection manager — owns live sockets, fan-out broadcast
# ─────────────────────────────────────────────────────────────────────
class ConnectionManager:
    """Tracks active WebSocket connections and fans frames out to them.

    No mutex: asyncio is single-threaded and every mutation here
    (set.add / set.discard) completes with no intervening `await`, so it
    is already atomic with respect to the event loop.

    Defensive by contract — a socket that raises on send is dropped, not
    propagated: one dead client never starves the rest of the fan-out.
    """

    def __init__(self) -> None:
        self._active: set[WebSocket] = set()

    @property
    def active_count(self) -> int:
        return len(self._active)

    async def connect(self, websocket: WebSocket) -> None:
        """Accept the handshake and register the socket."""
        await websocket.accept()
        self._active.add(websocket)
        log.info("[hermes] client connected (%d active)", self.active_count)

    def disconnect(self, websocket: WebSocket) -> None:
        """Deregister a socket. Safe to call more than once."""
        self._active.discard(websocket)
        log.info("[hermes] client disconnected (%d active)", self.active_count)

    async def send(self, websocket: WebSocket, frame: dict) -> bool:
        """Send one frame to one socket. Drops the socket and returns
        False on any failure rather than raising."""
        try:
            await websocket.send_json(frame)
            return True
        except Exception as e:
            log.debug("[hermes] send failed, dropping client: %s", e)
            self.disconnect(websocket)
            return False

    async def broadcast(self, frame: dict) -> int:
        """Fan a frame out to every live socket. Returns the delivery count."""
        delivered = 0
        # Iterate a snapshot — send() may disconnect a socket mid-loop.
        for websocket in list(self._active):
            if await self.send(websocket, frame):
                delivered += 1
        return delivered


# Process-singleton manager — the WS endpoint and the broadcast loop share it.
manager = ConnectionManager()


# ─────────────────────────────────────────────────────────────────────
#  Telemetry source — live Kalman pipeline tap (+ representative fallback)
# ─────────────────────────────────────────────────────────────────────
def _real_telemetry_frame() -> dict:
    """One tick of REAL Path C2 telemetry: simulator window -> Kalman pipeline.

    Returns the `channel_innovations` payload — the exact shape the legacy
    SSE endpoint (/api/telemetry/stream) emits, so the frontend dispatch is
    byte-compatible across the transport cutover. Raises if the simulator /
    site model is unavailable; `_telemetry_payload` then falls back.

    Taps the same process-singleton simulator + pipeline the SSE path uses,
    so the Kalman filter state is shared, not duplicated.
    """
    # Lazy imports — mirror the SSE endpoint; avoids import-time coupling.
    from site_model import get_site_model
    from telemetry_pipeline import get_pipeline
    from telemetry_simulator import get_simulator

    sim = get_simulator(get_site_model(_PROJECT_ROOT))
    pipeline = get_pipeline(dt_seconds=1.0)
    window = sim.get_window(dt_seconds=1.0, n_samples=5)
    channels = pipeline.compute(window)
    return {
        "schema": "channel_innovations",
        "channels": channels,
        "anomaly_count_60min": pipeline.count_anomalies_60min(),
        "ts": time.time(),
    }


def _telemetry_snapshot(seq: int) -> dict:
    """A representative Path C2 telemetry frame body — the graceful
    fallback when the live Kalman tap is unavailable."""
    phase = seq * 0.5
    return {
        "pue": round(_PUE_BASE + 0.02 * math.sin(phase) + random.uniform(-0.004, 0.004), 4),
        "it_load_kw": round(_IT_LOAD_BASE_KW + 240.0 * math.sin(phase * 0.7), 1),
        "hall_temp_c": round(_HALL_TEMP_BASE_C + 0.4 * math.sin(phase * 1.3), 2),
        "delta_t_c": round(_DELTA_T_BASE_C + 0.2 * math.sin(phase), 2),
        "scenario": "NORMAL",
    }


def _telemetry_payload(seq: int) -> dict:
    """The telemetry frame body: the live Kalman tap when available, else
    a representative `legacy_kpi` frame so the stream degrades gracefully."""
    try:
        return _real_telemetry_frame()
    except Exception as e:
        log.debug("[hermes] live telemetry tap unavailable (%s); representative frame", e)
        return {"schema": "legacy_kpi", "latest": _telemetry_snapshot(seq), "ts": time.time()}


# ─────────────────────────────────────────────────────────────────────
#  Shared broadcast loop — one Kalman tick, fanned out to every client
# ─────────────────────────────────────────────────────────────────────
_producer_task: asyncio.Task | None = None


async def _broadcast_loop() -> None:
    """Compute one telemetry tick and broadcast it to all clients."""
    seq = 0
    try:
        while True:
            seq += 1
            await manager.broadcast(build_frame("telemetry", _telemetry_payload(seq), seq))
            await asyncio.sleep(HERMES_TICK_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.error("[hermes] broadcast loop crashed: %s", e)


def _ensure_producer() -> None:
    """Start the broadcast loop if it is not already running."""
    global _producer_task
    if _producer_task is None or _producer_task.done():
        _producer_task = asyncio.create_task(_broadcast_loop())
        log.info("[hermes] telemetry broadcast loop started (tick=%.1fs)", HERMES_TICK_SECONDS)


async def _stop_producer_if_idle() -> None:
    """Cancel the broadcast loop once the last client has disconnected."""
    global _producer_task
    if manager.active_count == 0 and _producer_task is not None:
        _producer_task.cancel()
        with contextlib.suppress(BaseException):
            await _producer_task
        _producer_task = None
        log.info("[hermes] no clients — telemetry broadcast loop stopped")


# ─────────────────────────────────────────────────────────────────────
#  WebSocket endpoint
# ─────────────────────────────────────────────────────────────────────
@router.websocket("/api/hermes")
async def hermes_stream(websocket: WebSocket) -> None:
    """Multiplexed Hermes stream.

    On connect: one `hermes` control frame; thereafter the shared
    broadcast loop pushes a `telemetry` frame every HERMES_TICK_SECONDS.
    A concurrent receive loop detects the client disconnecting so the
    producer is torn down once the last dashboard leaves.
    """
    await manager.connect(websocket)
    await websocket.send_json(build_frame(
        "hermes",
        {"event": "connected", "streams": ["telemetry"], "tick_s": HERMES_TICK_SECONDS},
        seq=0,
    ))
    _ensure_producer()
    try:
        # No inbound data is expected; receive() is the disconnect probe.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.debug("[hermes] stream ended: %s", e)
    finally:
        manager.disconnect(websocket)
        await _stop_producer_if_idle()
