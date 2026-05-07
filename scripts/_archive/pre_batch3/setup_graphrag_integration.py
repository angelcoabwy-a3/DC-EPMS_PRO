"""
Sprint S2 - Batch 3: Integration of GraphRAG into the running app.

Operations:
  1. Create backend/agent_graph_tool.py (the agent tool wrapper)
  2. Patch backend/main.py to mount the /api/graph router
  3. Patch backend/agent_copilot.py to register query_graph_rag (6th tool)
  4. Create scripts/smoke_graphrag.py (end-to-end validation)

All file edits use byte-level operations (read_bytes / write_bytes),
preserve emojis/encoding, and create .bak_pre_s2_batch3 backups for
modified files.
"""
from pathlib import Path
import sys

ROOT = Path(r"C:\dev\DC-EPMS_PRO")
BACKEND = ROOT / "backend"
SCRIPTS = ROOT / "scripts"

if not BACKEND.exists():
    print(f"ERROR: backend dir not found: {BACKEND}")
    sys.exit(1)

SCRIPTS.mkdir(exist_ok=True)


# ════════════════════════════════════════════════════════════════════════
# FILE A (NEW): backend/agent_graph_tool.py
# ════════════════════════════════════════════════════════════════════════
AGENT_GRAPH_TOOL = '''"""
backend/agent_graph_tool.py - Sprint S2

The agent-facing wrapper for GraphRAG. Implements Mode A (pure retrieval):
the tool returns structured factual data (chunks + graph context) and the
orchestrating LLM is responsible for synthesizing a natural-language answer.

This keeps the LLM-call budget at exactly 1 per user turn (no internal
sub-call from the tool itself), and produces a fully auditable trace
where every claim in the agent's reply can be matched to a chunk.

Public API:
  - tool_query_graph_rag(args: dict) -> dict
  - QUERY_GRAPH_RAG_SCHEMA: dict (function-wrapper schema for the agent registry)

The service is supplied at registration time via set_graphrag_service(svc).
"""
from __future__ import annotations
from typing import Any, Optional
import logging

log = logging.getLogger(__name__)

_SERVICE: Optional[Any] = None


def set_graphrag_service(svc: Any) -> None:
    """Inject the GraphRAGService instance (called from main.py at boot)."""
    global _SERVICE
    _SERVICE = svc
    log.info("[agent_graph_tool] GraphRAG service injected")


async def tool_query_graph_rag(args: dict) -> dict:
    """READ-INTENT tool. Pure retrieval.

    Returns chunks + graph context + applicable knowledge. The LLM
    synthesises the natural-language reply using these as evidence.

    Args:
        text: user query in natural language
        component_id: optional component to scope the query
        k: optional top-k chunks (default 5, max 20)
        include_loto: if True, also includes LOTO impact + procedure chunks

    Returns:
        dict with keys:
          - chunks: list of {knowledge_id, chunk_index, text, score, meta}
          - graph_context: dict (or None) with component info
          - applicable_knowledge: list of dicts (jurisdiction-filtered)
          - loto_block: optional dict if include_loto=True
          - meta: dict with index stats and timing
    """
    if _SERVICE is None:
        return {
            "error": "GraphRAG service not initialised",
            "chunks": [],
            "applicable_knowledge": [],
        }

    text = args.get("text", "").strip()
    if not text:
        return {
            "error": "missing 'text' argument",
            "chunks": [],
            "applicable_knowledge": [],
        }

    component_id = args.get("component_id")
    k = int(args.get("k", 5))
    if k < 1:
        k = 1
    if k > 20:
        k = 20
    include_loto = bool(args.get("include_loto", False))

    try:
        result = _SERVICE.query(text=text, component_id=component_id, k=k)
    except Exception as e:
        log.exception("[tool_query_graph_rag] query failed")
        return {
            "error": f"graphrag query failed: {e}",
            "chunks": [],
            "applicable_knowledge": [],
        }

    payload: dict = {
        "query": text,
        "component_id": component_id,
        "graph_context": result.get("graph_context"),
        "applicable_knowledge": result.get("applicable_knowledge", []),
        "chunks": result.get("chunks", []),
        "jurisdictions_used": result.get("jurisdictions_used", []),
    }

    if include_loto and component_id:
        try:
            loto = _SERVICE.loto_with_knowledge(component_id)
            payload["loto_block"] = {
                "loto_impact": loto.get("loto_impact"),
                "procedure_chunks": loto.get("procedure_chunks", []),
            }
        except Exception as e:
            log.warning("[tool_query_graph_rag] loto block failed: %s", e)
            payload["loto_block"] = {"error": str(e)}

    return payload


# Schema in the format expected by agent_copilot.TOOLS_SCHEMA
# (matches DRAFT_CMMS_WORK_ORDER_SCHEMA shape: function-wrapper + parameters)
QUERY_GRAPH_RAG_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": "query_graph_rag",
        "description": (
            "Query the facility knowledge graph (GraphRAG) for procedural, "
            "regulatory, or topological context. Returns retrieved chunks "
            "from indexed standards (CSA Z462-24, OESC, OCP-LVDC, NVIDIA "
            "800VDC, STMicro BMS), applicable-knowledge metadata for the "
            "specified component, and graph context. Use this when the "
            "operator asks about safety procedures, voltage standards, "
            "LOTO requirements, arc-flash protection, capacitor discharge, "
            "or any compliance question that relates equipment to "
            "regulatory standards. The returned chunks should be cited "
            "in your reply."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Free-text query (e.g. 'arc flash PPE for 800VDC busbar', 'CSA Z462 PPE requirements for chiller LOTO').",
                },
                "component_id": {
                    "type": "string",
                    "description": "Optional canonical component id to scope the query (e.g. 'chiller_1', 'rpp_a_01'). When provided, the response includes the component's applicable knowledge filtered by jurisdiction.",
                },
                "k": {
                    "type": "integer",
                    "description": "Top-k chunks to retrieve (default 5, max 20).",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20,
                },
                "include_loto": {
                    "type": "boolean",
                    "description": "If true and component_id is set, also include the deterministic LOTO impact + procedure-relevant chunks.",
                    "default": False,
                },
            },
            "required": ["text"],
        },
    },
}
'''

(BACKEND / "agent_graph_tool.py").write_bytes(AGENT_GRAPH_TOOL.encode("utf-8"))
print(f"[ok] CREATED backend/agent_graph_tool.py ({len(AGENT_GRAPH_TOOL)} bytes)")


# ════════════════════════════════════════════════════════════════════════
# PATCH B: backend/main.py - mount /api/graph router and inject service
# ════════════════════════════════════════════════════════════════════════
MAIN_PATH = BACKEND / "main.py"
main_data = MAIN_PATH.read_bytes()

# Backup
bak = MAIN_PATH.with_suffix(".py.bak_pre_s2_batch3")
if not bak.exists():
    bak.write_bytes(main_data)
    print(f"[bak] main.py -> {bak.name}")

# Insertion point: after the Sprint S1b mounting (search for known marker)
# We need to find: 'log.info("[Sprint S1b] Site routes mounted at /api/site'
# (the bytes around this line are stable).
# Then append our S2 mount block after the line.
s1b_marker = b'log.info("[Sprint S1b] Site routes mounted at /api/site'

idx = main_data.find(s1b_marker)
if idx < 0:
    # Try fallback marker
    s1b_marker = b"[Sprint S1b] Site routes mounted at /api/site"
    idx = main_data.find(s1b_marker)

if idx < 0:
    print("[FAIL] could not find S1b mount marker in main.py")
    sys.exit(1)

# Find end of that line (the closing `)` and newline)
line_end = main_data.find(b"\n", idx)
if line_end < 0:
    print("[FAIL] could not find end of S1b mount line")
    sys.exit(1)

# Detect line ending
eol = b"\r\n" if main_data[line_end - 1:line_end] == b"\r" else b"\n"

# Block to inject AFTER the S1b line (single insertion point)
s2_block = (
    eol +
    b"# Sprint S2: GraphRAG service + router" + eol +
    b"try:" + eol +
    b"    from graphrag_service import GraphRAGService" + eol +
    b"    from graphrag_routes import make_graphrag_router" + eol +
    b"    from agent_graph_tool import set_graphrag_service" + eol +
    b"    _graphrag_corpus_dir = Path(__file__).parent.parent / 'config' / 'knowledge'" + eol +
    b"    _graphrag_service = GraphRAGService(site_model, _graphrag_corpus_dir)" + eol +
    b"    set_graphrag_service(_graphrag_service)" + eol +
    b"    app.include_router(make_graphrag_router(_graphrag_service))" + eol +
    b"    log.info('[Sprint S2] GraphRAG service mounted at /api/graph (lazy index, %d knowledge docs available)', len(list(_graphrag_corpus_dir.glob('*.md'))) - 1)" + eol +
    b"except Exception as _e:" + eol +
    b"    log.warning('[Sprint S2] GraphRAG NOT mounted: %s', _e)" + eol
)

# Insert after the newline that ends the S1b line
new_main = main_data[:line_end + len(eol)] + s2_block + main_data[line_end + len(eol):]

# Idempotency check
if b"[Sprint S2] GraphRAG service mounted" in main_data:
    print("[skip] main.py already has S2 mount block")
else:
    MAIN_PATH.write_bytes(new_main)
    print(f"[ok] PATCHED main.py (+{len(s2_block)} bytes)")


# ════════════════════════════════════════════════════════════════════════
# PATCH C: backend/agent_copilot.py - register query_graph_rag (6th tool)
# ════════════════════════════════════════════════════════════════════════
COPILOT_PATH = BACKEND / "agent_copilot.py"
copilot_data = COPILOT_PATH.read_bytes()

bak = COPILOT_PATH.with_suffix(".py.bak_pre_s2_batch3")
if not bak.exists():
    bak.write_bytes(copilot_data)
    print(f"[bak] agent_copilot.py -> {bak.name}")

# Find the S1b registration block (which we know is just before `return reg`)
# Pattern: log.info("[Sprint S1b] Site model query tool registered")
s1b_reg_marker = b'log.info("[Sprint S1b] Site model query tool registered")'

idx = copilot_data.find(s1b_reg_marker)
if idx < 0:
    print("[FAIL] could not find S1b registration marker in agent_copilot.py")
    sys.exit(1)

# Find the end of the except block - look for the next 'return reg' after this point
return_marker = b"return reg"
return_idx = copilot_data.find(return_marker, idx)
if return_idx < 0:
    print("[FAIL] could not find 'return reg' after S1b block")
    sys.exit(1)

# Walk backward from return_idx to find the start of that line (preceded by spaces)
line_start = return_idx
while line_start > 0 and copilot_data[line_start - 1] not in (0x0A, 0x0D):
    line_start -= 1

# Detect eol style by scanning surrounding bytes
sample = copilot_data[max(0, idx - 100):idx + 200]
eol = b"\r\n" if b"\r\n" in sample else b"\n"

# Build the S2 registration block (with same indentation as S1b: 4 spaces, 8 spaces inside try)
s2_reg = (
    eol +
    b"    # Sprint S2: GraphRAG query tool" + eol +
    b"    try:" + eol +
    b"        from agent_graph_tool import tool_query_graph_rag, QUERY_GRAPH_RAG_SCHEMA" + eol +
    b"        reg.register('query_graph_rag', tool_query_graph_rag)" + eol +
    b"        TOOLS_SCHEMA.append(QUERY_GRAPH_RAG_SCHEMA)" + eol +
    b"        log.info('[Sprint S2] GraphRAG query tool registered')" + eol +
    b"    except Exception as e:" + eol +
    b"        log.warning(f'[Sprint S2] GraphRAG query tool NOT registered: {e}')" + eol +
    eol
)

# Idempotency check
if b"[Sprint S2] GraphRAG query tool registered" in copilot_data:
    print("[skip] agent_copilot.py already has S2 registration block")
else:
    new_copilot = copilot_data[:line_start] + s2_reg + copilot_data[line_start:]
    COPILOT_PATH.write_bytes(new_copilot)
    print(f"[ok] PATCHED agent_copilot.py (+{len(s2_reg)} bytes)")


# ════════════════════════════════════════════════════════════════════════
# FILE D (NEW): scripts/smoke_graphrag.py
# ════════════════════════════════════════════════════════════════════════
SMOKE_SCRIPT = '''"""
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
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


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
            print(f"        source : {top['meta']['source']} (jurisdiction={top['meta']['jurisdiction']})")
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
                print(f"        - {kn['id']}: {kn['title'][:60]}... (jurisdiction={kn['jurisdiction']})")
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
            from agent_graph_tool import tool_query_graph_rag

            # Trigger graph build via the live service in main.py - but here we're
            # in a separate process from the server. So we re-instantiate.
            from site_model import SiteModel
            from graphrag_service import GraphRAGService
            from agent_graph_tool import set_graphrag_service

            corpus = Path(__file__).resolve().parent.parent / "config" / "knowledge"
            sm = SiteModel(yaml_path=Path(__file__).resolve().parent.parent / "config" / "site_model.yml")
            sm.load()
            svc = GraphRAGService(sm, corpus)
            set_graphrag_service(svc)

            result = asyncio.run(tool_query_graph_rag({
                "text": "lockout tagout chiller refrigerant safety",
                "component_id": "chiller_1",
                "k": 3,
                "include_loto": True,
            }))
            ok = (
                "chunks" in result
                and "applicable_knowledge" in result
                and "loto_block" in result
            )
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
'''

(SCRIPTS / "smoke_graphrag.py").write_bytes(SMOKE_SCRIPT.encode("utf-8"))
print(f"[ok] CREATED scripts/smoke_graphrag.py ({len(SMOKE_SCRIPT)} bytes)")

print()
print("=" * 78)
print("  Sprint S2 Batch 3 wiring done")
print("=" * 78)
print()
print("Next steps:")
print("  1. Verify Python syntax of all 4 modified/created files")
print("  2. Restart server: python backend/main.py")
print("     Look for: '[Sprint S2] GraphRAG service mounted at /api/graph'")
print("     Look for: '[Sprint S2] GraphRAG query tool registered'")
print("  3. Run smoke: python scripts/smoke_graphrag.py")
