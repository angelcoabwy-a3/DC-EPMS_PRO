"""
DC-EPMS PRO — tests/test_hermes.py
ROADMAP V11 T3.1 — Project Hermes WebSocket telemetry pipeline.

Covers the multiplexed frame envelope, the ConnectionManager fan-out
(including dead-socket eviction), the live Kalman-pipeline tap, the
graceful fallback, and the WS endpoint. No real network: ConnectionManager
runs against fake sockets; the endpoint is driven by TestClient and the
WS test mocks the producer for speed + isolation.
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
        assert len(frame["channels"]) > 0   # the Path C2 inventory emits channels
        # every channel carries the Kalman innovation contract
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
        assert delivered == 1            # only the live socket received it
        assert mgr.active_count == 1     # the dead one was dropped

    asyncio.run(_run())


def test_manager_disconnect_is_idempotent():
    mgr = hermes.ConnectionManager()

    async def _run():
        ws = _FakeWS()
        await mgr.connect(ws)
        mgr.disconnect(ws)
        mgr.disconnect(ws)               # safe to call twice
        assert mgr.active_count == 0

    asyncio.run(_run())


# ── live WebSocket endpoint ──────────────────────────────────────────
def test_router_exposes_the_hermes_websocket_route():
    paths = {getattr(r, "path", None) for r in hermes.router.routes}
    assert "/api/hermes" in paths


def test_ws_endpoint_streams_multiplexed_frames(monkeypatch):
    # Shrink the tick + mock the producer so the test is fast and isolated
    # from the simulator singletons.
    monkeypatch.setattr(hermes, "HERMES_TICK_SECONDS", 0.01)
    stub = {
        "schema": "channel_innovations",
        "channels": {"rack_a_01:gpu_Tj_c": {"max_z": 0.4, "mean_z": 0.1, "is_anomalous": False}},
        "anomaly_count_60min": 0,
        "ts": 1700000000.0,
    }
    monkeypatch.setattr(hermes, "_real_telemetry_frame", lambda: dict(stub))

    client = TestClient(_make_app())
    with client.websocket_connect("/api/hermes") as ws:
        welcome = ws.receive_json()
        assert welcome["stream"] == "hermes"
        assert welcome["payload"]["event"] == "connected"
        assert "telemetry" in welcome["payload"]["streams"]

        tele = ws.receive_json()
        assert tele["stream"] == "telemetry"
        assert tele["seq"] >= 1
        assert tele["payload"]["schema"] == "channel_innovations"
        assert "rack_a_01:gpu_Tj_c" in tele["payload"]["channels"]

        # the endpoint registered the live connection with the manager
        assert hermes.manager.active_count >= 1
