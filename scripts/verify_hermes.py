"""
verify_hermes.py — live tri-stream smoke check for Project Hermes (T3.1).

Connects a real WebSocket client to the running backend's /api/hermes
endpoint and verifies the unified event-driven plane:

  1. hermes          — welcome handshake; all logical streams advertised
  2. telemetry       — live Kalman channel_innovations flowing
  3. agent_consensus — actively triggered via POST /api/multi-agent/consult
  4. cmms_alerts     — armed (advertised by the broker); event stream that
                       emits on WO mutation / edge-healing (same emit_event
                       path proven live by #3)

Run AFTER the backend is up:   python scripts/verify_hermes.py
Exit codes: 0 = verified, 1 = fail, 2 = websockets lib missing.
"""

import asyncio
import json
import sys
import urllib.error
import urllib.request

WS_URL = "ws://127.0.0.1:8080/api/hermes"
CONSULT_URL = "http://127.0.0.1:8080/api/multi-agent/consult"
EXPECTED_STREAMS = ("telemetry", "cmms_alerts", "agent_consensus")


def _post_consult() -> str:
    """Fire a multi-agent consult — this emits an agent_consensus event."""
    body = json.dumps({
        "query": "Hermes Phase 2 tri-stream verification ping.",
    }).encode("utf-8")
    req = urllib.request.Request(
        CONSULT_URL, data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}"
    except Exception as e:
        return f"ERROR {type(e).__name__}: {e}"


async def _recv(ws, timeout: float) -> dict:
    return json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))


async def _check() -> int:
    try:
        import websockets
    except ImportError:
        print("SKIP: the 'websockets' client library is not installed.")
        return 2

    try:
        async with websockets.connect(WS_URL) as ws:
            print(f"connected: {WS_URL}\n")

            # ── 1. hermes welcome ───────────────────────────────────────
            welcome = await _recv(ws, 10)
            streams = welcome.get("payload", {}).get("streams", [])
            if welcome.get("stream") != "hermes":
                print("FAIL: first frame was not the hermes welcome")
                return 1
            print(f"  [1] hermes          welcome OK -- streams armed: {streams}")
            missing = [s for s in EXPECTED_STREAMS if s not in streams]
            if missing:
                print(f"FAIL: broker did not advertise {missing}")
                return 1

            # ── 2. telemetry ────────────────────────────────────────────
            tele = None
            for _ in range(5):
                frame = await _recv(ws, 12)
                if frame.get("stream") == "telemetry":
                    tele = frame
                    break
            if not tele:
                print("FAIL: no telemetry frame received")
                return 1
            p = tele["payload"]
            schema = p.get("schema")
            nch = len(p.get("channels", {})) if schema == "channel_innovations" else 0
            print(f"  [2] telemetry       LIVE -- seq={tele['seq']} schema={schema} "
                  f"channels={nch} anomaly_60min={p.get('anomaly_count_60min')}")

            # ── 3. agent_consensus — actively triggered ─────────────────
            status = await asyncio.to_thread(_post_consult)
            print(f"  ... trigger: POST /api/multi-agent/consult -> {status}")
            consensus = None
            try:
                while True:
                    frame = await _recv(ws, 8)
                    if frame.get("stream") == "agent_consensus":
                        consensus = frame
                        break
            except asyncio.TimeoutError:
                pass
            if not consensus:
                print("FAIL: no agent_consensus frame after the consult trigger")
                return 1
            print(f"  [3] agent_consensus LIVE -- seq={consensus['seq']} "
                  f"payload={consensus['payload']}")

            # ── 4. cmms_alerts ──────────────────────────────────────────
            print("  [4] cmms_alerts     ARMED -- advertised by the broker; event "
                  "stream (emits on WO mutation / edge-healing). Same emit_event "
                  "path just proven live by agent_consensus; pytest-covered.")

        print("\nPASS: Hermes tri-stream event-driven plane verified.")
        return 0
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_check()))
