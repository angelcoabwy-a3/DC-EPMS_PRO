# ADR-002: NetworkX MultiDiGraph In-Memory (vs Neo4j Persistent Server)

* Status: ACCEPTED
* Date: 2026-04 (decision originally taken during S2 Sprint, retroactively documented 2026-05-06 in Batch 3)
* Decision-maker: Wilmer Y. Angel Beltran (CET, Lead Architect a3semi)
* Sprint: S2 GraphRAG completion
* MADR template: https://adr.github.io/madr/

## Context

DC-EPMS PRO needs a graph-shaped data structure to express:

1. The facility topology DAG (power_chains and cooling_chains) — required for LOTO impact analysis (which downstream nodes lose power if I de-energize this upstream node).
2. The knowledge-to-component edges (`applies_to`) — required for GraphRAG topological retrieval (per ADR-001).
3. Future: dependency graphs for the alarm-storm mitigation logic (S7 V9 W9-10).

The dataset is small by graph standards: ~80 to ~200 components depending on Phase 1 vs Phase 2 deployment, plus a few hundred edges (containment, power, cooling, knowledge). Read-heavy workload (many traversals per request, rare structural updates).

## Decision

Use Python's **NetworkX 3.6.1** library. Specifically `MultiDiGraph` (allows multiple labeled edges between the same pair of nodes — needed because power_chains and cooling_chains may share endpoints with different semantics).

The graph is built in-memory at FastAPI lifespan startup from the declarative YAML in `config/site_model.yml` plus the markdown documents in `config/knowledge/`. No persistence layer; rebuild is essentially instantaneous (tens of milliseconds for the current scale; expected sub-second even at 368-rack Path C2 scale).

## Consequences

### Positive

- **Zero operational overhead**: no daemon, no port, no auth, no schema migrations. Aligns with Phase V9 edge-first autonomy and IEC 62443 Deterministic Sandbox principles (per ADR-006). Container image stays small (NetworkX is a pure-Python ~5 MB dependency vs Neo4j Community at ~700 MB).
- **Read latency is essentially memory access**: traversals are O(neighbors) on Python dicts. A LOTO impact walk over 80 components completes in microseconds.
- **Single source of truth**: YAML on disk is the authoritative topology. The graph in memory is a pure derivation, never source of truth. Eliminates an entire class of "graph drifted from YAML" bugs.
- **Testable with pure pytest**: no integration test harness to spin up Neo4j; `tests/test_graphrag.py` (20 tests) and `tests/test_site_model.py` (44 tests) run as ordinary unit tests.
- **Lifespan lifecycle alignment**: graph is rebuilt on every FastAPI startup, so changes to `site_model.yml` take effect on next container restart. No cache invalidation logic.

### Negative / Trade-offs

- **No multi-process sharing**: each FastAPI worker holds its own copy of the graph. Acceptable because the graph is small (low MB) and the project runs in a single-process configuration today.
- **No graph-native query language**: cannot use Cypher. Must express traversals as Python code in `backend/knowledge_graph.py`. Mitigated by the small set of traversal patterns the project actually uses (LOTO impact walk, applies_to lookup, redundancy state check).
- **Restart cost**: rebuilding the graph at startup adds latency to lifespan setup (~50 ms today). Becomes more visible at facility scale beyond Path C2 (368 racks, several hundred edges) but still well under the 60-second healthcheck start_period budget.
- **No persistent edge weights / runtime mutations**: if future runtime weights are needed (e.g., real-time edge scoring based on telemetry), they must be derived per-request or stored alongside the graph in supplementary structures.

## Alternatives Considered and Rejected

- **Neo4j Community in Docker** as a separate service alongside epms-db. Rejected: requires Cypher driver dependency, cross-container network round-trips per traversal, schema migration tooling, container image bloat, and operational mode that conflicts with Tier IV edge-first autonomy. The project's graph is too small to benefit from Neo4j's distributed/sharded design.
- **igraph (C-based)**: faster than NetworkX for very large graphs (millions of nodes) but pure-Python NetworkX is 100x faster than the project's needs already. Not worth the C compilation dependency for the marginal speed-up at this scale.
- **Plain dict/adjacency list** without a library. Rejected because LOTO impact analysis benefits from NetworkX's algorithms module (`descendants`, `ancestors`, `shortest_path`) which are correct on the first try and well-tested upstream.
- **TigerGraph or RedisGraph** cloud services. Rejected: the project must run edge-local without external dependencies for the Hyperscale Override Protocol scenario (1.4 GW Federated Fleet operates with degraded uplink).

## References

- `backend/knowledge_graph.py` — NetworkX wrapper with traversal methods
- `backend/graphrag_service.py` — combines NetworkX + FAISS (per ADR-003) into the GraphRAG service
- `backend/site_model.py` — converts YAML to NetworkX nodes/edges
- ADR-001 (Dual-RAG architecture context)
- ADR-003 (FAISS IndexFlatIP, the vector half of the GraphRAG pair)
- ADR-006 (Deterministic Sandbox / edge-first autonomy)

## Verification

- 20 unit tests in `tests/test_graphrag.py` exercise traversals, edge addition, and component-to-knowledge edge resolution.
- 44 unit tests in `tests/test_site_model.py` verify YAML-to-graph conversion (Location, ComponentInfo dataclasses; ImpactSet computation for LOTO).
- Aggregate test run in 6.67s for 103 tests (Batch 2 Layer 4) confirms no measurable graph-construction regression as the codebase grew.
