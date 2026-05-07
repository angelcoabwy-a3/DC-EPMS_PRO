"""
scripts/smoke_graphrag.py - Sprint S2 end-to-end smoke test.

Validates against a running server (default http://localhost:8080):

  1. /api/graph/health                              -> ok
  2. /api/graph/stats                               -> stats payload
  3. POST /api/graph/query                          -> chunks + graph_context
  4. GET  /api/graph/upstream/rack_a_01_05          -> upstream chain
  5. GET  /api/graph/related-knowledge/chiller_1    -> applicable docs
  6. GET  /api/graph/loto-with-knowledge/rpp_a_01   -> S1b LOTO + procedure chunks
  7. (optional) Direct python invocation of the agent tool

Usage:
    python scripts/smoke_graphrag.py
    python scripts/smoke_graphrag.py --base http://localhost:8080
    python scripts/smoke_graphrag.py --skip-tool   # only HTTP tests
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _http(method: str, url: str, body: dict | None = None, timeout: float = 60.0) -> dict:
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        return json.loads(raw)


def _section(title: str) -> None:
    print()
    print("=" * 78)
    print(f"  {title}")
    print("=" * 78)


def _check(label: str, ok: bool, detail: str = "") -> bool:
    status = "[ok]  " if ok else "[FAIL]"
    print(f"  {status} {label}{(' - ' + detail) if detail else ''}")
    return ok


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://localhost:8080", help="Base URL")
    p.add_argument("--skip-tool", action="store_true", help="Skip direct tool invocation")
    args = p.parse_args()

    base = args.base.rstrip("/")
    fails = 0
    total = 0

    # ── Test 1: /api/graph/health ──
    _section("Test 1: GET /api/graph/health")
    total += 1
    try:
        r = _http("GET", f"{base}/api/graph/health")
        ok = bool(r.get("ok"))
        if not _check("health endpoint reachable", ok, json.dumps(r)):
            fails += 1
    except (URLError, HTTPError) as e:
        _check("health endpoint reachable", False, str(e))
        fails += 1
        print()
        print("  FATAL: server not reachable at", base)
        print("  Start it: python backend/main.py")
        return 1

    # ── Test 2: /api/graph/stats ──
    _section("Test 2: GET /api/graph/stats")
    total += 1
    try:
        r = _http("GET", f"{base}/api/graph/stats")
        loaded = r.get("index", {}).get("loaded", False)
        n_docs = r.get("index", {}).get("n_docs", 0)
        # Stats may show loaded=False initially (lazy). That's normal.
        ok = "index" in r
        _check(f"stats payload returned (loaded={loaded}, n_docs={n_docs})", ok)
        if not ok:
            fails += 1
    except Exception as e:
        _check("stats", False, str(e))
        fails += 1

    # ── Test 3: POST /api/graph/query (triggers lazy load on first run) ──
    _section("Test 3: POST /api/graph/query")
    print("  (this triggers embedding-model load on first run; ~30s if model not cached)")
    total += 1
    try:
        t0 = time.time()
        r = _http(
            "POST",
            f"{base}/api/graph/query",
            body={
                "text": "arc flash PPE for 800VDC busbar capacitor discharge",
                "k": 3,
            },
            timeout=120.0,
        )
        elapsed = time.time() - t0
        chunks = r.get("chunks", [])
        ok_count = len(chunks) > 0
        ok_scores = all(0.0 <= c.get("score", -1) <= 1.0 for c in chunks)
        _check(f"query returned {len(chunks)} chunks in {elapsed:.1f}s", ok_count and ok_scores)
        if not (ok_count and ok_scores):
            fails += 1
        elif chunks:
            top = chunks[0]
            print(f"        top hit: {top['meta']['title']} (score={top['score']:.3f})")
            print(
                f"        source : {top['meta']['source']} (jurisdiction={top['meta']['jurisdiction']})"
            )
    except Exception as e:
        _check("query", False, str(e))
        fails += 1

    # ── Test 4: GET /api/graph/upstream/{component_id} ──
    _section("Test 4: GET /api/graph/upstream/rack_a_01_05")
    total += 1
    try:
        r = _http("GET", f"{base}/api/graph/upstream/rack_a_01_05")
        chain = r.get("chain", [])
        ok = len(chain) > 0
        _check(f"upstream chain has {len(chain)} hops", ok)
        if ok:
            print(f"        chain: {' -> '.join(chain[:6])}{'...' if len(chain) > 6 else ''}")
        else:
            fails += 1
    except Exception as e:
        _check("upstream", False, str(e))
        fails += 1

    # ── Test 5: GET /api/graph/related-knowledge/chiller_1 ──
    _section("Test 5: GET /api/graph/related-knowledge/chiller_1")
    total += 1
    try:
        r = _http("GET", f"{base}/api/graph/related-knowledge/chiller_1")
        knowledge = r.get("knowledge", [])
        ids = [k["id"] for k in knowledge]
        # CSA Z462-24 should apply to chillers in Ontario
        ok = "csa-z462-24" in ids
        _check(f"chiller_1 has {len(knowledge)} applicable docs (csa-z462-24 expected)", ok)
        if knowledge:
            for kn in knowledge:
                print(
                    f"        - {kn['id']}: {kn['title'][:60]}... (jurisdiction={kn['jurisdiction']})"
                )
        if not ok:
            fails += 1
    except Exception as e:
        _check("related-knowledge", False, str(e))
        fails += 1

    # ── Test 6: GET /api/graph/loto-with-knowledge/rpp_a_01 ──
    _section("Test 6: GET /api/graph/loto-with-knowledge/rpp_a_01")
    total += 1
    try:
        r = _http("GET", f"{base}/api/graph/loto-with-knowledge/rpp_a_01")
        loto = r.get("loto_impact", {})
        chunks = r.get("procedure_chunks", [])
        ok = "loto_impact" in r and "procedure_chunks" in r
        racks = loto.get("racks_affected", [])
        risk = len(loto.get("racks_losing_all_redundancy", []))
        _check(
            f"loto-with-knowledge ({len(racks)} racks affected, {risk} at risk, {len(chunks)} procedure chunks)",
            ok,
        )
        if not ok:
            fails += 1
    except Exception as e:
        _check("loto-with-knowledge", False, str(e))
        fails += 1

    # ── Test 7: Agent tool direct invocation (bypass HTTP) ──
    if not args.skip_tool:
        _section("Test 7: Direct agent tool invocation (in-process)")
        total += 1
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
            import asyncio

            from agent_graph_tool import set_graphrag_service, tool_query_graph_rag
            from graphrag_service import GraphRAGService

            # Trigger graph build via the live service in main.py - but here we're
            # in a separate process from the server. So we re-instantiate.
            from site_model import SiteModel

            corpus = Path(__file__).resolve().parent.parent / "config" / "knowledge"
            sm = SiteModel(
                yaml_path=Path(__file__).resolve().parent.parent / "config" / "site_model.yml"
            )
            sm.load()
            svc = GraphRAGService(sm, corpus)
            set_graphrag_service(svc)

            result = asyncio.run(
                tool_query_graph_rag(
                    {
                        "text": "lockout tagout chiller refrigerant safety",
                        "component_id": "chiller_1",
                        "k": 3,
                        "include_loto": True,
                    }
                )
            )
            ok = "chunks" in result and "applicable_knowledge" in result and "loto_block" in result
            _check(
                f"tool returned {len(result.get('chunks', []))} chunks, "
                f"{len(result.get('applicable_knowledge', []))} applicable docs, "
                f"loto_block={'yes' if result.get('loto_block') else 'no'}",
                ok,
            )
            if not ok:
                fails += 1
                print(json.dumps(result, indent=2, default=str)[:500])
        except Exception as e:
            _check("tool invocation", False, str(e))
            fails += 1

    # ── Summary ──
    _section("Summary")
    passed = total - fails
    print(f"  Passed: {passed}/{total}")
    if fails == 0:
        print()
        print("  ALL SMOKE TESTS PASSED. Sprint S2 wiring is COMPLETE.")
    else:
        print()
        print(f"  {fails} test(s) failed. See output above.")
    print()
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
