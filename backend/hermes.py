"""
hermes.py — ROADMAP V11 T3.1: Project Hermes WebSocket vertical slice.

A multiplexed, real-time push channel for live operational state. This
module is the first slice: the transport, the connection manager, the
multiplexed frame envelope, and one live stream (`telemetry`).

Multiplexed frame envelope
--------------------------
Every message on the socket is a JSON object:

    {
        "stream":  "<logical channel>",   # telemetry | hermes | cmms | ...
        "seq":     <int>,                 # per-connection monotonic counter
        "ts":      <float unix seconds>,
        "payload": { ... }                # stream-specific body
    }

A single socket therefore carries any number of logical streams; the
client demultiplexes on `stream`. This slice emits two: a one-shot
`hermes` control frame on connect, then a `telemetry` frame per tick.

Connection management
---------------------
`ConnectionManager` owns the set of live sockets and exposes a
`broadcast()` fan-out — the seam a later iteration uses to push
server-originated events (Kalman anomalies, CMMS WO transitions,
multi-agent consensus) to every client at once.

Telemetry source (slice scope)
------------------------------
`_telemetry_snapshot()` emits a representative Path C2 telemetry frame.
The envelope + transport are the T3.1 deliverable; the payload source
is intentionally swappable — a later bite taps the real Kalman pipeline
(telemetry_pipeline.get_pipeline().compute(window)). The decoupling
keeps this module independently testable.

Mounted by backend/main.py:  app.include_router(hermes.router)
Endpoint:  WS /api/hermes
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import random
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)

router = APIRouter()

# Telemetry tick interval (seconds). Module-level so tests can shrink it.
HERMES_TICK_SECONDS = 1.0

# Path C2 steady-state baselines for the representative telemetry frame.
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
            # A dead client must not abort the caller (broadcast loop).
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


# Process-singleton manager — the WS endpoint and any server-side
# producer share it.
manager = ConnectionManager()


# ─────────────────────────────────────────────────────────────────────
#  Telemetry source (slice producer — see module docstring)
# ─────────────────────────────────────────────────────────────────────
def _telemetry_snapshot(seq: int) -> dict:
    """A representative Path C2 telemetry frame body.

    Mild deterministic drift around the steady-state baselines so the
    live stream visibly moves. Swappable for the real Kalman pipeline tap.
    """
    phase = seq * 0.5
    return {
        "pue": round(_PUE_BASE + 0.02 * math.sin(phase) + random.uniform(-0.004, 0.004), 4),
        "it_load_kw": round(_IT_LOAD_BASE_KW + 240.0 * math.sin(phase * 0.7), 1),
        "hall_temp_c": round(_HALL_TEMP_BASE_C + 0.4 * math.sin(phase * 1.3), 2),
        "delta_t_c": round(_DELTA_T_BASE_C + 0.2 * math.sin(phase), 2),
        "scenario": "NORMAL",
    }


async def _produce(websocket: WebSocket) -> None:
    """Per-connection producer: one `telemetry` frame every tick."""
    seq = 0
    try:
        while True:
            seq += 1
            await websocket.send_json(build_frame("telemetry", _telemetry_snapshot(seq), seq))
            await asyncio.sleep(HERMES_TICK_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        # Client dropped mid-send — the receive loop will tear us down.
        log.debug("[hermes] producer stopped: %s", e)


# ─────────────────────────────────────────────────────────────────────
#  WebSocket endpoint
# ─────────────────────────────────────────────────────────────────────
@router.websocket("/api/hermes")
async def hermes_stream(websocket: WebSocket) -> None:
    """Multiplexed Hermes stream.

    On connect: one `hermes` control frame, then a `telemetry` frame
    every HERMES_TICK_SECONDS until the client disconnects. A concurrent
    receive loop exists purely to detect that disconnect so the producer
    task is always torn down cleanly.
    """
    await manager.connect(websocket)
    await websocket.send_json(build_frame(
        "hermes",
        {"event": "connected", "streams": ["telemetry"], "tick_s": HERMES_TICK_SECONDS},
        seq=0,
    ))
    producer = asyncio.create_task(_produce(websocket))
    try:
        # No inbound data is expected; receive() is the disconnect probe.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.debug("[hermes] stream ended: %s", e)
    finally:
        producer.cancel()
        with contextlib.suppress(BaseException):
            await producer
        manager.disconnect(websocket)
