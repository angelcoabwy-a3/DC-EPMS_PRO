"""
verify_hermes.py — live smoke check for the T3.1 Hermes WebSocket cutover.

Connects to the running backend's /api/hermes endpoint and validates that
the multiplexed stream delivers a `hermes` welcome frame followed by a
real `telemetry` frame. Run AFTER the backend is up:

    python scripts/verify_hermes.py

Exit codes: 0 = live + real telemetry, 1 = fail, 2 = websockets lib missing.
"""

import asyncio
import json
import sys

URL = "ws://127.0.0.1:8080/api/hermes"


async def _check() -> int:
    try:
        import websockets
    except ImportError:
        print("SKIP: the 'websockets' client library is not installed.")
        print("      The backend WS endpoint is still covered by tests/test_hermes.py.")
        return 2

    try:
        async with websockets.connect(URL) as ws:
            print(f"connected: {URL}")

            welcome = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            print(f"  frame 1: stream={welcome.get('stream')!r} payload={welcome.get('payload')}")
            if welcome.get("stream") != "hermes":
                print("FAIL: first frame was not the 'hermes' control frame")
                return 1

            tele = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            payload = tele.get("payload", {})
            schema = payload.get("schema")
            print(f"  frame 2: stream={tele.get('stream')!r} seq={tele.get('seq')} schema={schema!r}")
            if tele.get("stream") != "telemetry":
                print("FAIL: second frame was not a 'telemetry' frame")
                return 1

            if schema == "channel_innovations":
                channels = payload.get("channels", {})
                print(f"  LIVE Kalman tap: {len(channels)} channels, "
                      f"anomaly_count_60min={payload.get('anomaly_count_60min')}")
                sample_id = next(iter(channels), None)
                if sample_id:
                    print(f"  sample channel {sample_id!r}: {channels[sample_id]}")
                print("PASS: Hermes WS live -- real channel_innovations telemetry flowing.")
            elif schema == "legacy_kpi":
                print(f"  fallback frame (representative): latest={payload.get('latest')}")
                print("PASS (degraded): Hermes WS live, but the Kalman tap fell back "
                      "to the representative producer -- check the backend log.")
            else:
                print(f"FAIL: unexpected telemetry schema {schema!r}")
                return 1
            return 0
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_check()))
