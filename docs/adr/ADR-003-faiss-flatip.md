# ADR-003: FAISS IndexFlatIP for Knowledge Embedding Retrieval

* Status: ACCEPTED
* Date: 2026-04 (decision originally taken during S2 Sprint, retroactively documented 2026-05-06 in Batch 3)
* Decision-maker: Wilmer Y. Angel Beltran (CET, Lead Architect a3semi)
* Sprint: S2 GraphRAG completion
* MADR template: https://adr.github.io/madr/

## Context

The GraphRAG subsystem (per ADR-001 and ADR-002) needs to combine topological filtering (NetworkX edges) with semantic similarity over short text passages (chunked standards documents and vendor whitepapers in `config/knowledge/`). NetworkX gives us topology; we need a separate vector retriever for the semantic step.

The corpus is tiny by ANN standards: 5 markdown documents (~30 to 90 KB each), chunked into a few hundred passages, embedded with sentence-transformers `all-MiniLM-L6-v2` (384-dimension). At this scale, every nearest-neighbor algorithm is essentially instant, so the choice is dominated by **operational simplicity, deterministic results, and lack of training overhead**, not raw query throughput.

## Decision

Use **`faiss.IndexFlatIP`** — the brute-force exact inner-product index over L2-normalized embedding vectors. Embeddings are computed once at lifespan startup from the corpus chunks, normalized to unit length, and stored in the index. Queries are L2-normalized at query time, then matched against the index with `index.search(query_vec, top_k)`.

Mathematical equivalence: with L2-normalized vectors, inner-product equals cosine similarity. So `IndexFlatIP` over normalized vectors gives exact cosine top-k.

## Consequences

### Positive

- **Exact retrieval**: no approximation error. For small corpora this matters more than people think — when the dataset has only a few hundred chunks, an ANN index that misses by 0.5% recall can drop the actually-relevant chunk from top-3, and the LLM downstream sees noise. Brute force is correct on the first try.
- **Zero training**: no clustering, no quantization, no graph construction. Ingestion is one numpy concat plus L2 normalization. Eliminates a whole category of bugs (training set distribution shift, cluster degenerate cases, codebook staleness).
- **Deterministic results**: same query produces same top-k every time. Critical for reproducibility of CMMS draft outputs and for pytest snapshot-style testing.
- **Trivial persistence semantics**: embeddings are recomputed from corpus on startup. The corpus (the 5 markdown files) is the authoritative source; the index is a pure derivation.
- **Aligns with NetworkX in-memory choice (ADR-002)**: both halves of the GraphRAG pair are rebuildable from disk artifacts at startup. No cache coherence problem between graph and index.
- **CPU-only**: no CUDA dependency, fits the Docker image size budget (per ADR-008 Decision GO-OPTION-C). FAISS-CPU 1.13.2 is ~50 MB.

### Negative / Trade-offs

- **Linear scan over corpus chunks per query**: O(N * D) where N is chunks and D is dimension (384). At a few hundred chunks this is microseconds. Becomes visible in the milliseconds at tens of thousands of chunks. The project's corpus is bounded by the standards documents, which grow slowly.
- **No hot reloading**: adding a new doc to `config/knowledge/` requires a container restart to be searchable. Acceptable trade-off for a corpus that turns over on quarterly/annual cadence (standards update infrequently).
- **Hardware sensitivity on AMD Ryzen + Windows**: this is the root cause of bug DC-EPMS-001 (FAISS AVX2 access violation on Wilmer's hardware). Mitigated by `pytest -m "not slow"` filter on FAISS-touching tests; tests still pass on Linux CI (planned). Long-term replacement candidate (V10): `hnswlib` or `annoy` for hardware portability.

## Alternatives Considered and Rejected

- **`IndexHNSW` (Hierarchical Navigable Small World)**: faster ANN, used at billion-scale. Rejected: no measurable benefit at hundreds of chunks; adds an HNSW graph that must be rebuilt; introduces approximation error that undermines deterministic CMMS drafting.
- **NumPy linear scan with `argpartition`**: simpler, no FAISS dependency. Considered. Rejected because FAISS gives identical results at less code (the dot-product loop is tens of lines in NumPy vs one call to `index.search`) and provides a clean upgrade path to ANN if/when corpus scales.
- **ChromaDB as the second retriever** (already used per ADR-001 for operational corpus). Rejected because the GraphRAG layer needs to compose vector similarity with NetworkX traversal in the same query, which is awkward through ChromaDB's API and would require duplicating the small standards corpus.
- **Sentence Transformers built-in `.find_similar()` API**: too coarse, only operates on flat passage lists, not amenable to combining with graph filtering.

## References

- `backend/graphrag_index.py` — FAISS index wrapper, embedding computation, L2 normalization
- `backend/graphrag_service.py` — combines FAISS results with NetworkX edge filtering
- ADR-001 (overall Dual-RAG architecture)
- ADR-002 (NetworkX in-memory rationale)
- DC-EPMS-001 (FAISS AVX2 hardware bug on AMD Ryzen + Windows; documented in CHANGELOG.md)

## Verification

- Embedding determinism: on startup, the same corpus produces the same float vectors (sentence-transformers seed is deterministic).
- L2 normalization correctness: `numpy.linalg.norm(vec)` returns 1.0 within 1e-6 tolerance.
- Top-k retrieval correctness: covered by `tests/test_graphrag.py` integration tests that fix a small fixture corpus and assert specific chunks are retrieved for known queries.
- Index size stays within budget: at the current 5-doc corpus, the in-memory index is well under 1 MB.
