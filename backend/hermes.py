"""
hermes.py — ROADMAP V11 T3.1: Project Hermes — unified event-driven plane.

A multiplexed, real-time push channel for live operational state. One
WebSocket (/api/hermes) carries any number of logical streams; the
client demultiplexes on the frame's `stream` field.

Streams
-------
  telemetry        periodic Kalman channel_innovations (5 s tick)
  cmms_alerts      Work-Order mutations + EDGE_HEALING recommendations (event)
  agent_consensus  Multi-Agent consensus / Safety-Officer verdicts (event)

Frame envelope
--------------
  {"stream": str, "seq": int, "ts": float, "payload": {...}}

Producers
---------
  * _broadcast_loop   — periodic: computes one telemetry tick, broadcasts
    it, and feeds it downstream (predictive trigger + edge-healing).
  * _event_drain_loop — event: drains emit_event() frames and broadcasts
    them the instant they are produced.
Both run while >=1 client is connected; both stop when the last leaves.

Closed-loop Edge Healing (CET-gated — ADR-006)
----------------------------------------------
A critical asset (cdu_* / genset_*) whose Kalman z-score stays above
EDGE_HEALING_Z_THRESHOLD for EDGE_HEALING_SUSTAIN consecutive ticks
triggers: a best-effort Safety-Officer evaluation + an
EDGE_HEALING_RECOMMENDED alert on cmms_alerts + (via the restored
predictive trigger) an auto-drafted Work Order. The loop is closed by a
CET approving at the HMI -- Hermes never actuates /api/bms/write itself.
That gate is deliberate: ADR-006 Deterministic Sandbox + the F3-3 RBAC
control on BMS writes. The engine RECOMMENDS; the human AUTHORISES.

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

# ── Edge-healing detection thresholds ────────────────────────────────
EDGE_HEALING_Z_THRESHOLD = 3.0          # Kalman z-score breach level
EDGE_HEALING_SUSTAIN = 3                # consecutive ticks before recommend
_CRITICAL_ASSET_PREFIXES = ("cdu", "genset")   # primary infrastructure


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


# Process-singleton manager — every producer + the WS endpoint share it.
manager = ConnectionManager()


# ─────────────────────────────────────────────────────────────────────
#  Event plane — emit_event() + the drain loop (cmms_alerts / agent_consensus)
# ─────────────────────────────────────────────────────────────────────
# Bounded so a backlog (no drain running) can never leak memory.
_event_queue: asyncio.Queue = asyncio.Queue(maxsize=512)
_event_seq = 0


def _next_event_seq() -> int:
    global _event_seq
    _event_seq += 1
    return _event_seq


def emit_event(stream: str, payload: dict) -> None:
    """Fire-and-forget: queue an event frame for immediate broadcast.

    Safe to call from any coroutine in the uvicorn event loop (CMMS
    repository, multi-agent routes, the edge-healing engine). NEVER
    raises -- a streaming failure must not affect the caller's path.
    Drops silently when no client is connected.
    """
    try:
        if manager.active_count == 0:
            return
        _event_queue.put_nowait(build_frame(stream, payload, _next_event_seq()))
    except asyncio.QueueFull:
        log.warning("[hermes] event queue full; dropped a %s frame", stream)
    except Exception as e:
        log.debug("[hermes] emit_event(%s) noop: %s", stream, e)


async def _event_drain_loop() -> None:
    """Drain queued event frames and broadcast each one immediately."""
    try:
        while True:
            frame = await _event_queue.get()
            await manager.broadcast(frame)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.error("[hermes] event drain loop crashed: %s", e)


# ─────────────────────────────────────────────────────────────────────
#  Telemetry source — live Kalman pipeline tap (+ representative fallback)
# ─────────────────────────────────────────────────────────────────────
def _real_telemetry_frame() -> dict:
    """One tick of REAL Path C2 telemetry: simulator window -> Kalman pipeline.

    Returns the `channel_innovations` payload -- the exact shape the
    legacy SSE endpoint emits, so the frontend dispatch is byte-compatible
    across the transport cutover. Raises if the simulator / site model is
    unavailable; `_telemetry_payload` then falls back.
    """
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
    """A representative Path C2 telemetry frame body -- the graceful
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
#  Closed-loop edge healing — detect -> Safety Officer -> RECOMMEND
# ─────────────────────────────────────────────────────────────────────
# asset_id -> consecutive ticks the asset's max z-score exceeded the
# threshold; and the set of assets already recommended this episode.
_edge_healing_state: dict[str, int] = {}
_edge_healing_recommended: set[str] = set()


def _is_critical_asset(asset_id: str) -> bool:
    """True for primary infrastructure (CDU / genset) per the directive."""
    return asset_id.startswith(_CRITICAL_ASSET_PREFIXES)


async def _safety_officer_eval(asset_id: str, max_z: float) -> dict:
    """Best-effort Safety-Officer evaluation of a containment recommendation.

    Runs the real Multi-Agent consensus protocol. Returns a verdict dict;
    degrades to 'unavailable' (never raises) if the orchestrator is not
    initialised -- the recommendation still fires.
    """
    try:
        from multi_agent import ConsultContext, get_orchestrator

        orch = get_orchestrator()
        ctx = ConsultContext(
            query=(f"Edge-healing: critical asset {asset_id} Kalman z={max_z:.2f} "
                   f"sustained {EDGE_HEALING_SUSTAIN} ticks. Evaluate automated "
                   f"containment isolation."),
            asset_id=asset_id,
        )
        result = await orch.consult(ctx)
        return {
            "consensus": result.consensus,
            "safety_officer_veto": bool(result.safety_officer_veto),
        }
    except Exception as e:
        log.debug("[hermes] Safety Officer eval unavailable: %s", e)
        return {"consensus": "unavailable", "safety_officer_veto": None}


async def _trigger_edge_healing(asset_id: str, max_z: float, sustain: int) -> None:
    """Emit a CET-gated EDGE_HEALING_RECOMMENDED alert. Does NOT actuate."""
    verdict = await _safety_officer_eval(asset_id, max_z)
    emit_event("cmms_alerts", {
        "event": "EDGE_HEALING_RECOMMENDED",
        "asset_id": asset_id,
        "max_z": round(max_z, 2),
        "sustain_ticks": sustain,
        "severity": "high",
        "safety_officer": verdict,
        "recommended_action": "AUTOMATED_CONTAINMENT_ISOLATION",
        "actuation": "CET_APPROVAL_REQUIRED",
        "note": ("Per ADR-006 the BMS write is gated behind CET approval at the "
                 "HMI -- Hermes recommends, the CET authorises."),
    })
    log.warning(
        "[hermes] EDGE_HEALING_RECOMMENDED asset=%s z=%.2f sustain=%d safety=%s",
        asset_id, max_z, sustain, verdict.get("consensus"),
    )


async def _detect_edge_healing(channels: dict) -> None:
    """Per-tick edge-healing detection over the Kalman channel payload.

    Tracks, per critical asset, the consecutive ticks its peak z-score
    stays above threshold. On EDGE_HEALING_SUSTAIN consecutive ticks it
    fires one recommendation (deduped until the breach clears).
    """
    # Peak z-score per critical asset this tick.
    crit_z: dict[str, float] = {}
    for ch_id, fields in channels.items():
        asset_id = ch_id.split(":", 1)[0]
        if not _is_critical_asset(asset_id):
            continue
        try:
            z = float(fields.get("max_z", 0.0) or 0.0)
        except (TypeError, ValueError):
            z = 0.0
        crit_z[asset_id] = max(crit_z.get(asset_id, 0.0), z)

    for asset_id, z in crit_z.items():
        if z > EDGE_HEALING_Z_THRESHOLD:
            _edge_healing_state[asset_id] = _edge_healing_state.get(asset_id, 0) + 1
            if (_edge_healing_state[asset_id] >= EDGE_HEALING_SUSTAIN
                    and asset_id not in _edge_healing_recommended):
                _edge_healing_recommended.add(asset_id)
                await _trigger_edge_healing(asset_id, z, _edge_healing_state[asset_id])
        else:
            # Breach cleared — reset so a future episode can re-recommend.
            _edge_healing_state.pop(asset_id, None)
            _edge_healing_recommended.discard(asset_id)


async def _process_telemetry_channels(channels: dict) -> None:
    """Downstream fan-out of one telemetry tick's channel payload.

    (a) Feeds the predictive-WO trigger -- RESTORES the path the SSE->WS
        cutover (bf20042) silently dropped.
    (b) Runs edge-healing detection.
    Both sub-steps are defensive: a failure in one never blocks the other
    or the telemetry broadcast.
    """
    if not channels:
        return
    # (a) restore the predictive Work-Order feed
    try:
        from cmms_predictive_trigger import get_predictive_trigger
        await get_predictive_trigger().handle_payload(channels)
    except Exception as e:
        log.debug("[hermes] predictive trigger feed skipped: %s", e)
    # (b) edge-healing detection
    try:
        await _detect_edge_healing(channels)
    except Exception as e:
        log.warning("[hermes] edge-healing detection error: %s", e)


def reset_hermes_state() -> None:
    """Test helper -- clear edge-healing state + drain the event queue."""
    _edge_healing_state.clear()
    _edge_healing_recommended.clear()
    while not _event_queue.empty():
        try:
            _event_queue.get_nowait()
        except Exception:
            break


# ─────────────────────────────────────────────────────────────────────
#  Producers — periodic telemetry broadcast + event drain
# ─────────────────────────────────────────────────────────────────────
_telemetry_task: asyncio.Task | None = None
_event_task: asyncio.Task | None = None


async def _broadcast_loop() -> None:
    """Compute one telemetry tick, broadcast it, fan it downstream."""
    seq = 0
    try:
        while True:
            seq += 1
            payload = _telemetry_payload(seq)
            await manager.broadcast(build_frame("telemetry", payload, seq))
            if payload.get("schema") == "channel_innovations":
                await _process_telemetry_channels(payload.get("channels", {}))
            await asyncio.sleep(HERMES_TICK_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.error("[hermes] broadcast loop crashed: %s", e)


def _ensure_producers() -> None:
    """Start the telemetry + event-drain loops if not already running."""
    global _telemetry_task, _event_task
    if _telemetry_task is None or _telemetry_task.done():
        _telemetry_task = asyncio.create_task(_broadcast_loop())
        log.info("[hermes] telemetry broadcast loop started (tick=%.1fs)", HERMES_TICK_SECONDS)
    if _event_task is None or _event_task.done():
        _event_task = asyncio.create_task(_event_drain_loop())
        log.info("[hermes] event drain loop started (cmms_alerts + agent_consensus)")


async def _stop_producers_if_idle() -> None:
    """Cancel both producer loops once the last client has disconnected."""
    global _telemetry_task, _event_task
    if manager.active_count > 0:
        return
    for name, task in (("telemetry", _telemetry_task), ("event", _event_task)):
        if task is not None:
            task.cancel()
            with contextlib.suppress(BaseException):
                await task
    _telemetry_task = None
    _event_task = None
    log.info("[hermes] no clients — producer loops stopped")


# ─────────────────────────────────────────────────────────────────────
#  WebSocket endpoint
# ─────────────────────────────────────────────────────────────────────
@router.websocket("/api/hermes")
async def hermes_stream(websocket: WebSocket) -> None:
    """Multiplexed Hermes stream.

    On connect: one `hermes` control frame; thereafter the telemetry loop
    pushes `telemetry` frames every HERMES_TICK_SECONDS and the event
    drain pushes `cmms_alerts` / `agent_consensus` frames as they occur.
    A concurrent receive loop detects the client disconnecting so the
    producers are torn down once the last dashboard leaves.
    """
    await manager.connect(websocket)
    await websocket.send_json(build_frame(
        "hermes",
        {
            "event": "connected",
            "streams": ["telemetry", "cmms_alerts", "agent_consensus"],
            "tick_s": HERMES_TICK_SECONDS,
        },
        seq=0,
    ))
    _ensure_producers()
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
        await _stop_producers_if_idle()
