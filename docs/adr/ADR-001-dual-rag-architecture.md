# ADR-001: Dual-RAG Architecture (ChromaDB Primary + GraphRAG Secondary)

* Status: ACCEPTED
* Date: 2026-04 (decision originally taken during S2 Sprint, retroactively documented 2026-05-06 in Batch 3)
* Decision-maker: Wilmer Y. Angel Beltran (CET, Lead Architect a3semi)
* Sprint: S2 GraphRAG completion
* MADR template: https://adr.github.io/madr/

## Context

DC-EPMS PRO requires retrieval-augmented generation across two distinct query patterns that are difficult to satisfy with a single retriever:

1. **Operational lookup** — given a free-text question from a CET (e.g., "how do I LOTO a Galaxy VX UPS?"), return the most relevant procedural document. This is high-volume, latency-sensitive, and must respect document priority (Safety tier > Vendor tier > Standards tier > MOPs tier).

2. **Topological lookup** — given a physical component in `site_model.yml` (e.g., `bus_d_main`), return the standards documents that apply to that specific component class with a jurisdictional filter (Ontario vs international). This requires walking edges in a knowledge graph, not text similarity.

Vector-only retrieval (ChromaDB alone) handles operational lookup well but cannot enforce topological membership without expensive metadata filtering across every chunk. Graph-only retrieval (NetworkX alone) handles topology cleanly but loses semantic richness for natural-language CET queries.

## Decision

Maintain two parallel RAG subsystems coexisting in `backend/main.py`:

- **Primary**: `backend/rag_service.py` (ChromaDB persistent client, ~234 lines, 20 references in main.py). Indexes 20 operational documents across 4 priority tiers (Safety, Vendor, Standards, a3semi MOPs). Tier-priority scoring boosts Safety tier results above others. Backed by `data/chroma_db/` (~5 MB across 2 collections + sqlite metadata).

- **Secondary**: `backend/graphrag_service.py` (NetworkX MultiDiGraph + FAISS IndexFlatIP + sentence-transformers `all-MiniLM-L6-v2`, ~166 lines, 3 references in main.py). Indexes 5 standards/vendor whitepapers in `config/knowledge/` linked to physical components via declarative `applies_to` edges. Lazy-loaded on first query.

Routing rule (encoded in agent_copilot tool registry): operational queries route to ChromaDB via `query_rag` tool; topological queries route to GraphRAG via `query_graph_rag` tool. The Copilot itself selects based on query semantics.

## Consequences

### Positive

- Each retriever optimized for its query class. ChromaDB query latency stays under 100 ms p95 for tier-aware lookups. GraphRAG can surface "which standards apply to this MV rectifier" via single graph traversal in under 50 ms.
- Independent failure modes: if ChromaDB index corrupts, GraphRAG topological queries continue. If sentence-transformers model fails to load, operational queries continue.
- Storage efficiency: ChromaDB ~5 MB on disk for 20 docs (chunk-level granularity); GraphRAG NetworkX in-memory (~few MB) loaded once at request time.
- Separation of concerns: agent tool registry exposes both retrievers as named capabilities; CMMS work-order drafting can synthesize from both within the Deterministic Sandbox.

### Negative / Trade-offs

- Two persistence mechanisms to operate (ChromaDB sqlite + NetworkX serialized, plus FAISS index). Resolved partially by NetworkX being in-memory rebuilt on startup (no persistent layer concern).
- Cross-RAG consistency: if operational doc and graph doc reference the same standard, two parallel ingestion paths must stay in sync. Mitigated by treating ChromaDB as runtime corpus (tier-mapped MOPs) and GraphRAG as architectural reference corpus (small fixed set of vendor whitepapers).
- Cognitive load on contributors: must understand which retriever to query for which class of question. Mitigated by tool registry abstraction (the agent picks).

## Alternatives Considered and Rejected

- **Single ChromaDB with metadata filters** for component-aware queries. Rejected: filtering across embedded chunks is O(n) on chunk count and breaks tier-priority scoring. Topological membership is a graph property, not a text property.
- **Single Neo4j** as both vector store and graph store. Rejected per ADR-002 (Neo4j requires daemon process; conflicts with edge-first autonomy and deterministic Sandbox principles).
- **Hybrid with re-ranking** layer combining vector similarity and graph distance. Considered for V10. Rejected for V9 due to added complexity in failure modes and latency budget.

## References

- `backend/rag_service.py` — primary RAG implementation
- `backend/graphrag_service.py` — secondary RAG implementation
- `backend/agent_copilot.py` — tool registry routing logic (`_build_default_registry`)
- `02_STATUS_SUMMARY_REAL.md` Sec 5 (Dual-RAG Architecture)
- ADR-002 (NetworkX in-memory choice)
- ADR-003 (FAISS IndexFlatIP choice)
- ADR-006 (Deterministic Sandbox preserved across both RAG channels)

## Verification

- Operational query smoke test (ChromaDB): `POST /api/rag/query` with `query="LOTO Galaxy VX UPS"` returns Tier-1-Safety boosted result above Tier-4-MOP for the same topic.
- Topological query smoke test (GraphRAG): `POST /api/graph/query` with `query="standards applicable to bus_d_main"` returns OCP-LVDC + IEC TR 63282 nodes via `applies_to` edge traversal, not by text similarity alone.
- Both retrievers covered by 20+ unit tests in `tests/test_graphrag.py` and 51 tests in `tests/test_cmms_mcp.py` exercising the agent's RAG-mediated drafting flow.
