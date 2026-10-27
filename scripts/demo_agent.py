"""Demo the agentic investigator over HTTP (guard exercised).

Calls the RUNNING local server, never the agent function directly, so the
credit guard and the 400/429/503 paths are real. Runs both fixture
scenarios and prints the tool trace, conclusion, and checklist of each.

Run from the repo root with the server up (server terminal holds the key):
    python backend\\main.py            (with META_API_KEY + META_MODEL set)
    python scripts\\demo_agent.py      (EPMS_BASE_URL optional, default below)

No secrets live in this file. Exit 0 only when both scenarios answer 200.
"""

import json
import os
import sys
import urllib.error
import urllib.request

BASE_URL = os.environ.get("EPMS_BASE_URL", "http://127.0.0.1:8080")
SCENARIOS = ("burst-utility-01", "burst-cooling-02")


def post_investigate(scenario):
    """POST one scenario. Returns (status, body dict). Raises on no server."""
    payload = json.dumps({"scenario": scenario}).encode("utf-8")
    request = urllib.request.Request(
        BASE_URL + "/api/copilot/agent-investigate",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {"error": "unreadable-body"}
    except Exception as e:
        raise SystemExit(f"cannot reach server at {BASE_URL}: {type(e).__name__}: {e}") from e


def show(scenario, status, body):
    print(f"=== {scenario} -> HTTP {status} ===")
    if status != 200:
        print(f"error: {body.get('error')} detail: {body.get('detail')}")
        print(f"meta_call_made: {body.get('meta_call_made')}")
        return False
    print("tool trace (in order):")
    for i, call in enumerate(body.get("tool_calls") or [], 1):
        print(f"  {i}. {call.get('tool')} {json.dumps(call.get('arguments'))}")
    print(
        f"conclusion: {body.get('probable_cause')} "
        f"[{body.get('confidence')}] {body.get('priority')} "
        f"via {body.get('suggested_procedure')} "
        f"(model {body.get('model')}, {body.get('model_calls')} calls)"
    )
    print(f"evidence cited: {body.get('evidence_ids_cited')}")
    print("verification checklist:")
    for item in body.get("verification_checklist") or []:
        print(f"  - {item}")
    return True


def main():
    ok = True
    for scenario in SCENARIOS:
        status, body = post_investigate(scenario)
        ok = show(scenario, status, body) and ok
        print()
    if not ok:
        print("DEMO FAILED: a scenario did not answer 200 (see above).")
        return 1
    print("DEMO OK: both scenarios investigated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
