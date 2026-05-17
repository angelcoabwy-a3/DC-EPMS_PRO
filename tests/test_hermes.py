"""
DC-EPMS PRO — tests/test_hermes.py
ROADMAP V11 T3.1 — Project Hermes: unified event-driven plane.

Covers the multiplexed frame envelope, the ConnectionManager fan-out,
the live Kalman tap, the event plane (emit_event + cmms_alerts /
agent_consensus), the closed-loop edge-healing engine, and the WS
endpoint. No real network: ConnectionManager runs against fake sockets;
the WS test mocks the producers for speed + isolation.
"""

import asyncio
import pathlib
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
# Both roots: flat imports (import hermes) need backend/; the simulator's
# own `from backend.site_model import ...` needs the project root.
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

import hermes


# ── helpers ──────────────────────────────────────────────────────────
class _FakeWS:
    """Minimal async WebSocket double for ConnectionManager tests."""

    def __init__(self, fail_on_send: bool = False):
        self.fail_on_send = fail_on_send
        self.accepted = False
        self.sent: list = []

    async def accept(self):
        self.accepted = True

    async def send_json(self, data):
        if self.fail_on_send:
            raise RuntimeError("simulated dead socket")
        self.sent.append(data)


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(hermes.router)
    return app


def _with_listener() -> _FakeWS:
    """Register a dummy connection so emit_event() is not a no-op."""
    ws = _FakeWS()
    hermes.manager._active.add(ws)
    return ws


def _clean_event_state() -> None:
    hermes.reset_hermes_state()
    hermes.manager._active.clear()


def _drain_events() -> list:
    out = []
    while not hermes._event_queue.empty():
        out.append(hermes._event_queue.get_nowait())
    return out


# ── frame envelope ───────────────────────────────────────────────────
def test_build_frame_envelope_shape():
    frame = hermes.build_frame("telemetry", {"pue": 1.1}, seq=7)
    assert frame["stream"] == "telemetry"
    assert frame["seq"] == 7
    assert isinstance(frame["ts"], float)
    assert frame["payload"] == {"pue": 1.1}


def test_telemetry_snapshot_carries_path_c2_fields():
    snap = hermes._telemetry_snapshot(3)
    assert {"pue", "it_load_kw", "hall_temp_c", "delta_t_c", "scenario"} <= set(snap)
    assert 1.0 < snap["pue"] < 1.3
    assert snap["scenario"] == "NORMAL"


# ── live Kalman pipeline tap ─────────────────────────────────────────
def test_real_telemetry_frame_taps_kalman_pipeline():
    """The production producer taps the real simulator + Kalman pipeline."""
    from telemetry_pipeline import reset_pipeline
    from telemetry_simulator import reset_simulator

    reset_simulator()
    reset_pipeline()
    try:
        frame = hermes._real_telemetry_frame()
        assert frame["schema"] == "channel_innovations"
        assert isinstance(frame["channels"], dict)
        assert len(frame["channels"]) > 0
        sample = next(iter(frame["channels"].values()))
        assert {"max_z", "mean_z", "is_anomalous"} <= set(sample)
        assert isinstance(frame["anomaly_count_60min"], int)
    finally:
        reset_simulator()
        reset_pipeline()


def test_telemetry_payload_falls_back_when_tap_unavailable(monkeypatch):
    """If the live tap raises, the producer degrades to a representative frame."""
    def _boom():
        raise RuntimeError("simulator offline")

    monkeypatch.setattr(hermes, "_real_telemetry_frame", _boom)
    payload = hermes._telemetry_payload(5)
    assert payload["schema"] == "legacy_kpi"
    assert payload["latest"]["scenario"] == "NORMAL"


# ── ConnectionManager ────────────────────────────────────────────────
def test_manager_connect_accepts_and_registers():
    mgr = hermes.ConnectionManager()

    async def _run():
        ws = _FakeWS()
        await mgr.connect(ws)
        assert ws.accepted is True
        assert mgr.active_count == 1

    asyncio.run(_run())


def test_manager_broadcast_fans_out_to_all():
    mgr = hermes.ConnectionManager()

    async def _run():
        a, b = _FakeWS(), _FakeWS()
        await mgr.connect(a)
        await mgr.connect(b)
        delivered = await mgr.broadcast(hermes.build_frame("telemetry", {"x": 1}))
        assert delivered == 2
        assert a.sent and b.sent

    asyncio.run(_run())


def test_manager_broadcast_evicts_dead_socket():
    mgr = hermes.ConnectionManager()

    async def _run():
        good, dead = _FakeWS(), _FakeWS(fail_on_send=True)
        await mgr.connect(good)
        await mgr.connect(dead)
        delivered = await mgr.broadcast(hermes.build_frame("telemetry", {}))
        assert delivered == 1
        assert mgr.active_count == 1

    asyncio.run(_run())


def test_manager_disconnect_is_idempotent():
    mgr = hermes.ConnectionManager()

    async def _run():
        ws = _FakeWS()
        await mgr.connect(ws)
        mgr.disconnect(ws)
        mgr.disconnect(ws)
        assert mgr.active_count == 0

    asyncio.run(_run())


# ── event plane — emit_event / cmms_alerts / agent_consensus ─────────
def test_emit_event_enqueues_a_framed_event():
    _clean_event_state()
    _with_listener()
    try:
        hermes.emit_event("cmms_alerts", {"work_order_id": "WO-1", "status": "pending_approval"})
        events = _drain_events()
        assert len(events) == 1
        assert events[0]["stream"] == "cmms_alerts"
        assert events[0]["payload"]["work_order_id"] == "WO-1"
        assert isinstance(events[0]["seq"], int)
    finally:
        _clean_event_state()


def test_emit_event_is_a_noop_with_no_listener():
    _clean_event_state()
    # no listener registered -> the live stream drops the event
    hermes.emit_event("agent_consensus", {"agent": "consensus", "event": "resolved"})
    assert hermes._event_queue.empty()
    _clean_event_state()


# ── closed-loop edge healing ─────────────────────────────────────────
def test_edge_healing_recommends_on_sustained_breach():
    """Sustained Z>3 on a critical asset -> one CET-gated recommendation."""
    _clean_event_state()
    _with_listener()
    try:
        channels = {"genset_a_01:genset_voltage_v": {"max_z": 5.2, "is_anomalous": True}}

        async def _run():
            for _ in range(hermes.EDGE_HEALING_SUSTAIN):
                await hermes._process_telemetry_channels(channels)

        asyncio.run(_run())
        eh = [e for e in _drain_events()
              if e["payload"].get("event") == "EDGE_HEALING_RECOMMENDED"]
        assert len(eh) == 1
        assert eh[0]["stream"] == "cmms_alerts"
        assert eh[0]["payload"]["asset_id"] == "genset_a_01"
        # CET-gated: the engine RECOMMENDS, it does not actuate.
        assert eh[0]["payload"]["actuation"] == "CET_APPROVAL_REQUIRED"
    finally:
        _clean_event_state()


def test_edge_healing_silent_below_sustain_threshold():
    """Fewer than EDGE_HEALING_SUSTAIN consecutive breaches -> no recommendation."""
    _clean_event_state()
    _with_listener()
    try:
        channels = {"cdu_a_01:cdu_flow_lpm": {"max_z": 6.0, "is_anomalous": True}}

        async def _run():
            for _ in range(hermes.EDGE_HEALING_SUSTAIN - 1):
                await hermes._process_telemetry_channels(channels)

        asyncio.run(_run())
        eh = [e for e in _drain_events()
              if e["payload"].get("event") == "EDGE_HEALING_RECOMMENDED"]
        assert eh == []
    finally:
        _clean_event_state()


def test_edge_healing_dedups_within_one_episode():
    """A sustained breach fires exactly once, not on every later tick."""
    _clean_event_state()
    _with_listener()
    try:
        channels = {"cdu_a_01:cdu_flow_lpm": {"max_z": 7.1, "is_anomalous": True}}

        async def _run():
            for _ in range(hermes.EDGE_HEALING_SUSTAIN + 4):
                await hermes._process_telemetry_channels(channels)

        asyncio.run(_run())
        eh = [e for e in _drain_events()
              if e["payload"].get("event") == "EDGE_HEALING_RECOMMENDED"]
        assert len(eh) == 1
    finally:
        _clean_event_state()


def test_edge_healing_ignores_non_critical_assets():
    """A non-critical asset (rack) never triggers edge healing, even at z=9."""
    _clean_event_state()
    _with_listener()
    try:
        channels = {"rack_a_01:gpu_Tj_c": {"max_z": 9.0, "is_anomalous": True}}

        async def _run():
            for _ in range(hermes.EDGE_HEALING_SUSTAIN + 2):
                await hermes._process_telemetry_channels(channels)

        asyncio.run(_run())
        eh = [e for e in _drain_events()
              if e["payload"].get("event") == "EDGE_HEALING_RECOMMENDED"]
        assert eh == []
    finally:
        _clean_event_state()


# ── live WebSocket endpoint ──────────────────────────────────────────
def test_router_exposes_the_hermes_websocket_route():
    paths = {getattr(r, "path", None) for r in hermes.router.routes}
    assert "/api/hermes" in paths


def test_ws_endpoint_streams_multiplexed_frames(monkeypatch):
    # Shrink the tick + mock the producers so the test is fast and
    # isolated from the simulator / CMMS singletons.
    monkeypatch.setattr(hermes, "HERMES_TICK_SECONDS", 0.01)
    stub = {
        "schema": "channel_innovations",
        "channels": {"rack_a_01:gpu_Tj_c": {"max_z": 0.4, "mean_z": 0.1, "is_anomalous": False}},
        "anomaly_count_60min": 0,
        "ts": 1700000000.0,
    }
    monkeypatch.setattr(hermes, "_real_telemetry_frame", lambda: dict(stub))

    async def _noop_channels(_channels):
        return None

    monkeypatch.setattr(hermes, "_process_telemetry_channels", _noop_channels)

    client = TestClient(_make_app())
    with client.websocket_connect("/api/hermes") as ws:
        welcome = ws.receive_json()
        assert welcome["stream"] == "hermes"
        assert welcome["payload"]["event"] == "connected"
        # the unified plane advertises all three logical streams
        assert {"telemetry", "cmms_alerts", "agent_consensus"} <= set(welcome["payload"]["streams"])

        tele = ws.receive_json()
        assert tele["stream"] == "telemetry"
        assert tele["seq"] >= 1
        assert tele["payload"]["schema"] == "channel_innovations"
        assert hermes.manager.active_count >= 1
