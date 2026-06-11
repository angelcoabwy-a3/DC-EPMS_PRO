"""MVP S2 runtime smoke — Phase 2 design-sim channels on the live SSE.

Connects to /api/telemetry/stream, reads the FIRST channel_innovations
event, and verifies the Building D design-sim channels ride the wire
(S-RUNTIME-01: unit tests passing is not evidence the live process
serves the new code).

Usage:  python scripts/smoke_phase2_channels.py  (backend on :8080)
Exit 0 = all expected channels live; exit 1 = missing channels.
"""
from __future__ import annotations

import json
import sys
import urllib.request

URL = "http://127.0.0.1:8080/api/telemetry/stream"

EXPECTED = [
    "utility_feed_d:utility_voltage_kv",
    "mv_rectifier_d:rect_load_mw",
    "mv_rectifier_d:rect_efficiency_ratio",
    "sscb_d_01:sscb_junction_T_c",
    "main_bus_dc_d:voltage_v_dc_bus",
    "bess_d_01:bess_soc_pct",
    "bess_d_01:bess_dc_current_a",
    "gen_farm_d:farm_units_online_count",
    "gen_farm_d:farm_bus_voltage_kv",
]


def main() -> int:
    req = urllib.request.Request(URL, headers={"Accept": "text/event-stream"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = None
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("data:"):
                payload = json.loads(line[5:].strip())
                break
    if payload is None:
        print("[smoke] FAIL: no SSE event received")
        return 1

    channels = payload.get("channels", {})
    print(f"[smoke] first event: schema={payload.get('schema')} "
          f"channels={len(channels)}")

    missing = [c for c in EXPECTED if c not in channels]
    for c in EXPECTED:
        if c in channels:
            v = channels[c]
            print(f"[smoke]   OK  {c}  value={v.get('value', v.get('mean', '?'))}")
    if missing:
        for c in missing:
            print(f"[smoke]   MISSING  {c}")
        return 1

    # Vocabulary fence at the live wire (S-VOCAB-01).
    for ch_id in channels:
        metric = ch_id.split(":", 1)[-1]
        if "dc_bus" in metric and "phase" in metric:
            print(f"[smoke]   VOCAB VIOLATION: {ch_id}")
            return 1

    print("[smoke] PASS: Phase 2 design-sim chain is live on the wire")
    return 0


if __name__ == "__main__":
    sys.exit(main())
