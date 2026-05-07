"""
Sprint S2 - Batch 2: Generate GraphRAG backend modules + tests.

Creates 5 files in C:\\dev\\DC-EPMS_PRO\\:
  - backend/knowledge_graph.py   - NetworkX wrapper over site_model + KnowledgeNodes
  - backend/graphrag_index.py    - Markdown loader + chunking + embeddings + FAISS
  - backend/graphrag_service.py  - Orchestration of retrieval queries
  - backend/graphrag_routes.py   - FastAPI router
  - tests/test_graphrag.py       - Coverage tests

This script is idempotent and creates safety backups of any pre-existing
files (.bak_pre_s2).

Uses pure pathlib + write_bytes(utf-8) - no encoding ambiguity.
"""
from pathlib import Path

ROOT = Path(r"C:\dev\DC-EPMS_PRO")
BACKEND = ROOT / "backend"
TESTS = ROOT / "tests"
TESTS.mkdir(exist_ok=True)

FILES: dict[Path, str] = {}

# ════════════════════════════════════════════════════════════════════════
# FILE 1: backend/knowledge_graph.py
# ════════════════════════════════════════════════════════════════════════
FILES[BACKEND / "knowledge_graph.py"] = '''"""
backend/knowledge_graph.py - Sprint S2

Builds a NetworkX MultiDiGraph that fuses:
  1. The site model (components, locations, power edges, cooling edges)
     loaded from site_model.SiteModel.
  2. KnowledgeNodes parsed from config/knowledge/*.md frontmatter.

Edge types in the graph:
  - feeds_power_to       (component -> component)        from site_model
  - cools                (component -> component)        from site_model
  - located_in           (component -> location)         from site_model
  - applies_to_type      (knowledge_node -> type_string) from frontmatter
  - cites                (knowledge_node -> knowledge_node) cross-refs

Public API:
  - build_knowledge_graph(site_model, knowledge_docs) -> MultiDiGraph
  - get_upstream_chain(graph, component_id, relation) -> list[str]
  - get_applicable_knowledge(graph, component_id) -> list[KnowledgeNode]
  - get_knowledge_for_component_type(graph, type_str) -> list[KnowledgeNode]

Note: this module does NOT load the docs itself. The graphrag_index module
parses the markdowns and passes the resulting list of doc dicts here.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional
import logging

import networkx as nx

log = logging.getLogger(__name__)


@dataclass
class KnowledgeNode:
    """A single knowledge document (one markdown file)."""
    id: str
    title: str
    source: str
    source_type: str
    applies_to: list[str]
    tags: list[str]
    jurisdiction: str
    version: str
    voltage_class: str
    file_path: str
    body_text: str  # full markdown body (sans frontmatter)


def build_knowledge_graph(
    site_model_obj: Any,
    knowledge_docs: list[KnowledgeNode],
) -> nx.MultiDiGraph:
    """Construct the unified graph.

    Args:
        site_model_obj: instance of SiteModel from site_model.py
        knowledge_docs: list of KnowledgeNode parsed from markdown corpus

    Returns:
        nx.MultiDiGraph with mixed node types. Each node has a 'kind'
        attribute: 'component', 'location', or 'knowledge'.
    """
    g = nx.MultiDiGraph()

    # ── Add component nodes ──
    for cid, comp in site_model_obj.components.items():
        g.add_node(
            cid,
            kind="component",
            display=comp.display,
            type=comp.type,
            location_path=comp.location.path if comp.location else None,
            metadata=getattr(comp, "metadata", {}) or {},
        )

    # ── Add location nodes ──
    for lid, loc in site_model_obj.locations.items():
        g.add_node(
            lid,
            kind="location",
            display=loc.display,
            level=loc.level,
            path=loc.path,
        )

    # ── Add located_in edges (component -> location) ──
    for cid, comp in site_model_obj.components.items():
        if comp.location is not None:
            # The deepest location id is the leaf in components[]
            leaves = [c for c in comp.location.components if c.level != "site"]
            if leaves:
                deepest = leaves[-1].id
                if deepest in g:
                    g.add_edge(cid, deepest, key="located_in", relation="located_in")

    # ── Add power feed edges ──
    for edge in getattr(site_model_obj, "power_edges", []):
        if edge.source in g and edge.target in g:
            g.add_edge(
                edge.source,
                edge.target,
                key=f"power:{edge.source}:{edge.target}",
                relation="feeds_power_to",
                group=getattr(edge, "group", None),
            )

    # ── Add cooling edges ──
    for edge in getattr(site_model_obj, "cooling_edges", []):
        if edge.source in g and edge.target in g:
            g.add_edge(
                edge.source,
                edge.target,
                key=f"cool:{edge.source}:{edge.target}",
                relation="cools",
            )

    # ── Add knowledge nodes ──
    for kn in knowledge_docs:
        g.add_node(
            kn.id,
            kind="knowledge",
            title=kn.title,
            source=kn.source,
            source_type=kn.source_type,
            jurisdiction=kn.jurisdiction,
            version=kn.version,
            voltage_class=kn.voltage_class,
            tags=kn.tags,
            applies_to=kn.applies_to,
            file_path=kn.file_path,
        )

    # ── Add applies_to_type edges (knowledge -> type_marker_node) ──
    # We model component types as virtual nodes prefixed with "type:" so
    # the graph can answer "all knowledge for type chiller" without
    # requiring text matching at query time.
    type_nodes_added: set[str] = set()
    for kn in knowledge_docs:
        for type_str in kn.applies_to:
            type_node = f"type:{type_str}"
            if type_node not in type_nodes_added:
                g.add_node(type_node, kind="component_type", type=type_str)
                type_nodes_added.add(type_node)
            g.add_edge(
                kn.id,
                type_node,
                key=f"applies:{kn.id}:{type_str}",
                relation="applies_to_type",
            )

    # ── Add component -> type edges (so we can join knowledge to components) ──
    for cid, comp in site_model_obj.components.items():
        type_node = f"type:{comp.type}"
        if type_node in g:
            g.add_edge(
                cid,
                type_node,
                key=f"is_a:{cid}",
                relation="is_a",
            )

    log.info(
        "[knowledge_graph] built: %d nodes, %d edges (components=%d, locations=%d, knowledge=%d, types=%d)",
        g.number_of_nodes(),
        g.number_of_edges(),
        sum(1 for _, d in g.nodes(data=True) if d.get("kind") == "component"),
        sum(1 for _, d in g.nodes(data=True) if d.get("kind") == "location"),
        sum(1 for _, d in g.nodes(data=True) if d.get("kind") == "knowledge"),
        len(type_nodes_added),
    )
    return g


def get_upstream_chain(
    graph: nx.MultiDiGraph,
    component_id: str,
    relation: str = "feeds_power_to",
    max_hops: int = 10,
) -> list[str]:
    """BFS upstream over the given relation. Returns list of ancestor node ids."""
    if component_id not in graph:
        return []
    visited: list[str] = []
    seen: set[str] = set()
    frontier: list[tuple[str, int]] = [(component_id, 0)]
    while frontier:
        node, depth = frontier.pop(0)
        if node in seen or depth > max_hops:
            continue
        seen.add(node)
        if node != component_id:
            visited.append(node)
        # in-edges with the desired relation are the upstream sources
        for src, _, data in graph.in_edges(node, data=True):
            if data.get("relation") == relation and src not in seen:
                frontier.append((src, depth + 1))
    return visited


def get_applicable_knowledge(
    graph: nx.MultiDiGraph,
    component_id: str,
) -> list[dict]:
    """Find all KnowledgeNodes that apply to the given component.

    Resolution path: component -[is_a]-> type:X <-[applies_to_type]- knowledge
    """
    if component_id not in graph:
        return []
    comp_data = graph.nodes[component_id]
    if comp_data.get("kind") != "component":
        return []

    type_str = comp_data.get("type")
    if not type_str:
        return []

    return get_knowledge_for_component_type(graph, type_str)


def get_knowledge_for_component_type(
    graph: nx.MultiDiGraph,
    type_str: str,
) -> list[dict]:
    """Find KnowledgeNodes applicable to a component type."""
    type_node = f"type:{type_str}"
    if type_node not in graph:
        return []

    knowledge_nodes: list[dict] = []
    for src, _, data in graph.in_edges(type_node, data=True):
        if data.get("relation") == "applies_to_type":
            kn_data = graph.nodes[src]
            if kn_data.get("kind") == "knowledge":
                knowledge_nodes.append({
                    "id": src,
                    "title": kn_data.get("title"),
                    "source": kn_data.get("source"),
                    "source_type": kn_data.get("source_type"),
                    "jurisdiction": kn_data.get("jurisdiction"),
                    "version": kn_data.get("version"),
                    "voltage_class": kn_data.get("voltage_class"),
                    "tags": kn_data.get("tags", []),
                })
    return knowledge_nodes


def filter_by_jurisdiction(
    knowledge_list: list[dict],
    component_jurisdiction: str = "ontario_canada",
) -> list[dict]:
    """Filter knowledge nodes to those applicable in the given jurisdiction.

    Rules:
      - Always include 'international' jurisdiction.
      - Include 'canada' if component is in Canada (any province).
      - Include 'ontario_canada' only if component is in Ontario.
      - For US components, would substitute NFPA-70E for CSA Z462-24, etc.
        (Not implemented; A3-Alpha is Toronto for now.)
    """
    keep: list[dict] = []
    for kn in knowledge_list:
        kj = kn.get("jurisdiction", "international")
        if kj == "international":
            keep.append(kn)
        elif kj == "canada" and "canada" in component_jurisdiction:
            keep.append(kn)
        elif kj == "ontario_canada" and component_jurisdiction == "ontario_canada":
            keep.append(kn)
    return keep
'''

# ════════════════════════════════════════════════════════════════════════
# FILE 2: backend/graphrag_index.py
# ════════════════════════════════════════════════════════════════════════
FILES[BACKEND / "graphrag_index.py"] = '''"""
backend/graphrag_index.py - Sprint S2

Loads and indexes the knowledge corpus from config/knowledge/*.md.

Pipeline:
  1. Parse YAML frontmatter -> KnowledgeNode metadata
  2. Strip frontmatter -> get body text
  3. Chunk body into ~200-token windows with 50-token overlap
  4. Embed chunks with sentence-transformers all-MiniLM-L6-v2 (CPU)
  5. Index embeddings in FAISS IndexFlatIP (cosine via normalized vectors)

Public API:
  - load_knowledge_corpus(corpus_dir) -> list[KnowledgeNode]
  - GraphRAGIndex                     - the singleton index
    .ensure_loaded()                  - lazy-load (downloads model on 1st call)
    .search(query, k=5)               - returns list[ChunkHit]
    .stats()                          - diagnostics

The model is lazy-loaded: nothing happens at module import. The first call
to .search() triggers model download (~90 MB on first run, cached after).
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import re
import logging
import threading

import numpy as np
import yaml

from knowledge_graph import KnowledgeNode

log = logging.getLogger(__name__)

# Tokenization is approximate - we use whitespace splits as a fast proxy.
# At chunk boundaries, the encoder may use a different tokenizer (BPE);
# we accept ~10% slop in chunk size since semantic search is robust to it.
_CHUNK_SIZE_WORDS = 200
_CHUNK_OVERLAP_WORDS = 50
_EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
_EMBEDDING_DIM = 384  # all-MiniLM-L6-v2 produces 384-d vectors


@dataclass
class ChunkHit:
    """One search result."""
    knowledge_id: str        # parent doc id
    chunk_index: int         # position within doc
    text: str                # raw chunk text
    score: float             # cosine similarity (0..1)
    knowledge_meta: dict     # frontmatter of parent doc


def _split_frontmatter(raw: str) -> tuple[dict, str]:
    """Parse the YAML frontmatter and return (meta, body)."""
    if not raw.startswith("---"):
        return {}, raw
    end = raw.index("---", 3)
    fm_text = raw[3:end].strip()
    body = raw[end + 3:].lstrip("\\n")
    meta = yaml.safe_load(fm_text) or {}
    return meta, body


def _chunk_text(text: str) -> list[str]:
    """Greedy word-based chunking with overlap."""
    words = text.split()
    if len(words) <= _CHUNK_SIZE_WORDS:
        return [text.strip()]
    chunks: list[str] = []
    step = _CHUNK_SIZE_WORDS - _CHUNK_OVERLAP_WORDS
    for start in range(0, len(words), step):
        end = min(start + _CHUNK_SIZE_WORDS, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
    return chunks


def load_knowledge_corpus(corpus_dir: Path) -> list[KnowledgeNode]:
    """Read and parse all *.md files under corpus_dir (excluding README)."""
    docs: list[KnowledgeNode] = []
    for md_path in sorted(corpus_dir.glob("*.md")):
        if md_path.name.upper() == "README.MD":
            continue
        raw = md_path.read_text(encoding="utf-8")
        meta, body = _split_frontmatter(raw)
        if not meta:
            log.warning("[graphrag] no frontmatter in %s, skipping", md_path.name)
            continue
        try:
            kn = KnowledgeNode(
                id=meta["id"],
                title=meta.get("title", md_path.stem),
                source=meta.get("source", ""),
                source_type=meta.get("source_type", "unknown"),
                applies_to=meta.get("applies_to", []),
                tags=meta.get("tags", []),
                jurisdiction=meta.get("jurisdiction", "international"),
                version=str(meta.get("version", "")),
                voltage_class=meta.get("voltage_class", ""),
                file_path=str(md_path),
                body_text=body.strip(),
            )
            docs.append(kn)
        except KeyError as e:
            log.error("[graphrag] %s missing required field %s", md_path.name, e)

    log.info("[graphrag] loaded %d knowledge documents from %s", len(docs), corpus_dir)
    return docs


class GraphRAGIndex:
    """Lazy-loaded vector index over the knowledge corpus."""

    def __init__(self, corpus_dir: Path):
        self.corpus_dir = corpus_dir
        self._docs: list[KnowledgeNode] = []
        self._chunks: list[dict] = []  # each: {knowledge_id, chunk_index, text}
        self._embeddings: Optional[np.ndarray] = None  # (N, dim) normalized
        self._faiss_index = None  # type: ignore
        self._model = None  # SentenceTransformer (lazy)
        self._loaded = False
        self._lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def docs(self) -> list[KnowledgeNode]:
        """Returns the list of KnowledgeNode after load. Force-loads if needed."""
        self.ensure_loaded()
        return self._docs

    def ensure_loaded(self) -> None:
        """Lazy initialization. Idempotent and thread-safe."""
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            log.info("[graphrag] lazy-loading index (first query triggers model download if cache missing)...")
            self._docs = load_knowledge_corpus(self.corpus_dir)
            self._build_chunks()
            self._build_embeddings()
            self._build_faiss()
            self._loaded = True
            log.info(
                "[graphrag] index ready: %d docs, %d chunks, %d-dim embeddings, FAISS=%s",
                len(self._docs),
                len(self._chunks),
                _EMBEDDING_DIM,
                "ok" if self._faiss_index is not None else "fallback",
            )

    def _build_chunks(self) -> None:
        for kn in self._docs:
            for i, c in enumerate(_chunk_text(kn.body_text)):
                self._chunks.append({
                    "knowledge_id": kn.id,
                    "chunk_index": i,
                    "text": c,
                })

    def _build_embeddings(self) -> None:
        # Local import to defer heavy module load until first use
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(_EMBEDDING_MODEL_NAME)
        texts = [c["text"] for c in self._chunks]
        if not texts:
            self._embeddings = np.zeros((0, _EMBEDDING_DIM), dtype=np.float32)
            return
        emb = self._model.encode(
            texts,
            batch_size=16,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,  # cosine via inner product
        )
        self._embeddings = emb.astype(np.float32)

    def _build_faiss(self) -> None:
        if self._embeddings is None or len(self._embeddings) == 0:
            return
        try:
            import faiss  # type: ignore
            index = faiss.IndexFlatIP(_EMBEDDING_DIM)
            index.add(self._embeddings)
            self._faiss_index = index
        except ImportError:
            log.warning("[graphrag] faiss not available, will fall back to NumPy")
            self._faiss_index = None

    def search(
        self,
        query: str,
        k: int = 5,
        filter_jurisdictions: Optional[list[str]] = None,
    ) -> list[ChunkHit]:
        """Cosine-similarity search.

        filter_jurisdictions: if provided, return only chunks whose parent
        doc is in one of these jurisdictions. Always include 'international'
        in addition.
        """
        self.ensure_loaded()
        if self._embeddings is None or len(self._chunks) == 0:
            return []
        if self._model is None:
            return []

        q_vec = self._model.encode(
            [query],
            convert_to_numpy=True,
            normalize_embeddings=True,
        ).astype(np.float32)

        # Search wider than k to allow filtering
        search_k = max(k * 4, 20)

        if self._faiss_index is not None:
            scores, indices = self._faiss_index.search(q_vec, search_k)
            candidates = list(zip(indices[0].tolist(), scores[0].tolist()))
        else:
            sims = (self._embeddings @ q_vec.T).flatten()
            top = np.argsort(-sims)[:search_k]
            candidates = [(int(i), float(sims[i])) for i in top]

        # Index for parent doc lookup
        docs_by_id = {d.id: d for d in self._docs}

        hits: list[ChunkHit] = []
        for idx, score in candidates:
            if idx < 0 or idx >= len(self._chunks):
                continue
            chunk = self._chunks[idx]
            parent = docs_by_id.get(chunk["knowledge_id"])
            if parent is None:
                continue
            if filter_jurisdictions:
                allowed = set(filter_jurisdictions) | {"international"}
                if parent.jurisdiction not in allowed:
                    continue
            meta = {
                "id": parent.id,
                "title": parent.title,
                "source": parent.source,
                "source_type": parent.source_type,
                "jurisdiction": parent.jurisdiction,
                "version": parent.version,
                "voltage_class": parent.voltage_class,
                "tags": parent.tags,
            }
            hits.append(ChunkHit(
                knowledge_id=chunk["knowledge_id"],
                chunk_index=chunk["chunk_index"],
                text=chunk["text"],
                score=float(score),
                knowledge_meta=meta,
            ))
            if len(hits) >= k:
                break
        return hits

    def stats(self) -> dict:
        return {
            "loaded": self._loaded,
            "n_docs": len(self._docs),
            "n_chunks": len(self._chunks),
            "embedding_dim": _EMBEDDING_DIM,
            "embedding_model": _EMBEDDING_MODEL_NAME,
            "backend": "faiss" if self._faiss_index is not None else ("numpy" if self._loaded else "not_loaded"),
        }


# ── module-level singleton ──
_DEFAULT_CORPUS = Path(__file__).parent.parent / "config" / "knowledge"
_INDEX: Optional[GraphRAGIndex] = None


def get_index() -> GraphRAGIndex:
    """Returns the module singleton, creating it if needed (no lazy load yet)."""
    global _INDEX
    if _INDEX is None:
        _INDEX = GraphRAGIndex(_DEFAULT_CORPUS)
    return _INDEX
'''

# ════════════════════════════════════════════════════════════════════════
# FILE 3: backend/graphrag_service.py
# ════════════════════════════════════════════════════════════════════════
FILES[BACKEND / "graphrag_service.py"] = '''"""
backend/graphrag_service.py - Sprint S2

Orchestrates GraphRAG queries combining:
  - Knowledge Graph (NetworkX) for structural relationships
  - Vector Index (FAISS) for semantic retrieval

Mode A (deterministic retrieval) only - the LLM synthesis layer (Mode B)
is implemented in agent_copilot via the agent tool registration.

Public API:
  - GraphRAGService(site_model, knowledge_dir)
    .query(text, component_id=None, k=5) -> dict
    .upstream(component_id, relation) -> dict
    .related_knowledge(component_id) -> dict
    .loto_with_knowledge(component_id) -> dict
    .stats() -> dict
"""
from __future__ import annotations
from typing import Optional, Any
from pathlib import Path
import logging

import networkx as nx

from knowledge_graph import (
    build_knowledge_graph,
    get_upstream_chain,
    get_applicable_knowledge,
    filter_by_jurisdiction,
)
from graphrag_index import get_index, GraphRAGIndex

log = logging.getLogger(__name__)


class GraphRAGService:
    """Cohesive facade over the knowledge graph + vector index."""

    def __init__(self, site_model_obj: Any, knowledge_dir: Path):
        self.site_model = site_model_obj
        self.knowledge_dir = knowledge_dir
        self._graph: Optional[nx.MultiDiGraph] = None
        self._index: GraphRAGIndex = get_index()

    @property
    def graph(self) -> nx.MultiDiGraph:
        """Build the graph on first access."""
        if self._graph is None:
            self._index.ensure_loaded()
            self._graph = build_knowledge_graph(self.site_model, self._index.docs)
        return self._graph

    # ────────────────────────────────────────────────────────────
    # Query primitives
    # ────────────────────────────────────────────────────────────
    def query(
        self,
        text: str,
        component_id: Optional[str] = None,
        k: int = 5,
        jurisdictions: Optional[list[str]] = None,
    ) -> dict:
        """Mode A: deterministic retrieval.

        Returns a structured payload of:
          - chunks: top-k semantic matches
          - graph_context: structural facts about component_id (if provided)
          - applicable_knowledge: docs whose `applies_to` mentions the
            component_type
          - jurisdictions_used: effective jurisdiction filter
        """
        graph_context = None
        applicable = []
        effective_juris = jurisdictions

        if component_id:
            comp_node = self.graph.nodes.get(component_id)
            if comp_node:
                graph_context = {
                    "component_id": component_id,
                    "display": comp_node.get("display"),
                    "type": comp_node.get("type"),
                    "location": comp_node.get("location_path"),
                }
                # Default to Toronto/Canada if not explicitly set
                if effective_juris is None:
                    effective_juris = ["canada", "ontario_canada"]
                applicable = filter_by_jurisdiction(
                    get_applicable_knowledge(self.graph, component_id),
                    component_jurisdiction="ontario_canada",
                )

        hits = self._index.search(
            text,
            k=k,
            filter_jurisdictions=effective_juris,
        )

        return {
            "query": text,
            "component_id": component_id,
            "graph_context": graph_context,
            "applicable_knowledge": applicable,
            "chunks": [
                {
                    "knowledge_id": h.knowledge_id,
                    "chunk_index": h.chunk_index,
                    "text": h.text,
                    "score": round(h.score, 4),
                    "meta": h.knowledge_meta,
                }
                for h in hits
            ],
            "jurisdictions_used": effective_juris or ["international"],
        }

    def upstream(self, component_id: str, relation: str = "feeds_power_to") -> dict:
        chain = get_upstream_chain(self.graph, component_id, relation=relation)
        return {
            "component_id": component_id,
            "relation": relation,
            "chain": chain,
            "depth": len(chain),
        }

    def related_knowledge(self, component_id: str) -> dict:
        knowledge = filter_by_jurisdiction(
            get_applicable_knowledge(self.graph, component_id),
            component_jurisdiction="ontario_canada",
        )
        return {
            "component_id": component_id,
            "knowledge": knowledge,
            "count": len(knowledge),
        }

    def loto_with_knowledge(self, component_id: str) -> dict:
        """Combine S1b LOTO impact with knowledge graph context.

        This is the integration point that demonstrates GraphRAG value:
        the LOTO calculation comes from S1b (deterministic), and the
        knowledge layer adds the procedural standards that govern HOW
        the LOTO must be performed (PPE level, capacitor discharge wait,
        SSCB sequencing, etc.).
        """
        # Reuse S1b logic via the site_model
        loto_result = self.site_model.loto_impact(component_id)
        related = self.related_knowledge(component_id)

        # Pull semantic chunks specifically about LOTO procedures for this type
        comp_node = self.graph.nodes.get(component_id, {})
        comp_type = comp_node.get("type", "")
        loto_query = f"LOTO procedure {comp_type} arc-flash PPE capacitor discharge"
        hits = self._index.search(loto_query, k=3, filter_jurisdictions=["canada", "ontario_canada"])

        return {
            "component_id": component_id,
            "loto_impact": loto_result,
            "applicable_knowledge": related["knowledge"],
            "procedure_chunks": [
                {
                    "knowledge_id": h.knowledge_id,
                    "text": h.text,
                    "score": round(h.score, 4),
                    "meta": h.knowledge_meta,
                }
                for h in hits
            ],
        }

    def stats(self) -> dict:
        idx_stats = self._index.stats()
        graph_stats = {}
        if self._graph is not None:
            kinds: dict = {}
            for _, data in self._graph.nodes(data=True):
                k = data.get("kind", "unknown")
                kinds[k] = kinds.get(k, 0) + 1
            graph_stats = {
                "n_nodes": self._graph.number_of_nodes(),
                "n_edges": self._graph.number_of_edges(),
                "by_kind": kinds,
            }
        return {
            "index": idx_stats,
            "graph": graph_stats,
        }
'''

# ════════════════════════════════════════════════════════════════════════
# FILE 4: backend/graphrag_routes.py
# ════════════════════════════════════════════════════════════════════════
FILES[BACKEND / "graphrag_routes.py"] = '''"""
backend/graphrag_routes.py - Sprint S2

FastAPI router exposing the GraphRAG service endpoints.

Mounted in main.py at prefix /api/graph.

Endpoints:
  GET  /api/graph/health
  GET  /api/graph/stats
  POST /api/graph/query                    body: {text, component_id?, k?}
  GET  /api/graph/upstream/{component_id}
  GET  /api/graph/related-knowledge/{component_id}
  GET  /api/graph/loto-with-knowledge/{component_id}
"""
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from graphrag_service import GraphRAGService


def make_graphrag_router(service: GraphRAGService) -> APIRouter:
    router = APIRouter(prefix="/api/graph", tags=["graphrag"])

    @router.get("/health")
    def health():
        return {
            "ok": True,
            "loaded": service._index.is_loaded,
        }

    @router.get("/stats")
    def stats():
        return service.stats()

    class QueryReq(BaseModel):
        text: str = Field(..., min_length=2, description="Free-text query")
        component_id: Optional[str] = Field(None, description="Optional component context")
        k: int = Field(5, ge=1, le=20, description="Top-k results")
        jurisdictions: Optional[list[str]] = Field(
            None,
            description="Restrict to these jurisdictions (international always included)",
        )

    @router.post("/query")
    def query(req: QueryReq):
        return service.query(
            text=req.text,
            component_id=req.component_id,
            k=req.k,
            jurisdictions=req.jurisdictions,
        )

    @router.get("/upstream/{component_id}")
    def upstream(component_id: str, relation: str = "feeds_power_to"):
        if component_id not in service.graph:
            raise HTTPException(404, f"component '{component_id}' not in graph")
        return service.upstream(component_id, relation=relation)

    @router.get("/related-knowledge/{component_id}")
    def related_knowledge(component_id: str):
        if component_id not in service.graph:
            raise HTTPException(404, f"component '{component_id}' not in graph")
        return service.related_knowledge(component_id)

    @router.get("/loto-with-knowledge/{component_id}")
    def loto_with_knowledge(component_id: str):
        if component_id not in service.graph:
            raise HTTPException(404, f"component '{component_id}' not in graph")
        return service.loto_with_knowledge(component_id)

    return router
'''

# ════════════════════════════════════════════════════════════════════════
# FILE 5: tests/test_graphrag.py
# ════════════════════════════════════════════════════════════════════════
FILES[TESTS / "test_graphrag.py"] = '''"""
tests/test_graphrag.py - Sprint S2 coverage tests

Tests cover:
  - Knowledge corpus loading and frontmatter parsing
  - Graph construction (component+location+knowledge nodes; edges)
  - Upstream chain BFS
  - Applicable knowledge resolution by component type
  - Jurisdiction filtering (Ontario priority)
  - GraphRAGService end-to-end (with lazy-loaded index)
  - FastAPI routes via TestClient

Heavy: this triggers the model download on first run if not cached.
"""
from __future__ import annotations
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from site_model import SiteModel  # noqa: E402
from knowledge_graph import (  # noqa: E402
    build_knowledge_graph,
    get_upstream_chain,
    get_applicable_knowledge,
    filter_by_jurisdiction,
    KnowledgeNode,
)
from graphrag_index import (  # noqa: E402
    load_knowledge_corpus,
    GraphRAGIndex,
    _split_frontmatter,
    _chunk_text,
)
from graphrag_service import GraphRAGService  # noqa: E402


CORPUS_DIR = ROOT / "config" / "knowledge"
SITE_MODEL_PATH = ROOT / "config" / "site_model.yml"


# ────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def site_model():
    return SiteModel.load(SITE_MODEL_PATH)


@pytest.fixture(scope="module")
def docs():
    return load_knowledge_corpus(CORPUS_DIR)


@pytest.fixture(scope="module")
def graph(site_model, docs):
    return build_knowledge_graph(site_model, docs)


@pytest.fixture(scope="module")
def service(site_model):
    return GraphRAGService(site_model, CORPUS_DIR)


# ────────────────────────────────────────────────────────────────────
# Frontmatter & chunking
# ────────────────────────────────────────────────────────────────────
def test_split_frontmatter_basic():
    raw = "---\\nid: x\\ntitle: T\\n---\\nbody here"
    meta, body = _split_frontmatter(raw)
    assert meta["id"] == "x"
    assert meta["title"] == "T"
    assert body.strip() == "body here"


def test_split_frontmatter_no_frontmatter():
    raw = "no frontmatter at all"
    meta, body = _split_frontmatter(raw)
    assert meta == {}
    assert body == raw


def test_chunk_text_short():
    assert _chunk_text("hello world") == ["hello world"]


def test_chunk_text_long_overlaps():
    text = " ".join([f"w{i}" for i in range(500)])
    chunks = _chunk_text(text)
    assert len(chunks) > 1
    # overlap: last 50 words of chunk i appear in start of chunk i+1
    first = chunks[0].split()
    second = chunks[1].split()
    overlap = set(first[-50:]) & set(second[:50])
    assert len(overlap) >= 40  # most words overlap


# ────────────────────────────────────────────────────────────────────
# Corpus loading
# ────────────────────────────────────────────────────────────────────
def test_corpus_has_5_docs(docs):
    assert len(docs) == 5
    ids = sorted(d.id for d in docs)
    assert "nvidia-800vdc" in ids
    assert "ocp-lvdc" in ids
    assert "stmicro-bms" in ids
    assert "csa-z462-24" in ids
    assert "oesc-ontario-28" in ids


def test_csa_z462_jurisdiction_canada(docs):
    csa = next(d for d in docs if d.id == "csa-z462-24")
    assert csa.jurisdiction == "canada"


def test_oesc_jurisdiction_ontario(docs):
    oesc = next(d for d in docs if d.id == "oesc-ontario-28")
    assert oesc.jurisdiction == "ontario_canada"


# ────────────────────────────────────────────────────────────────────
# Graph construction
# ────────────────────────────────────────────────────────────────────
def test_graph_has_91_components(graph):
    components = [n for n, d in graph.nodes(data=True) if d.get("kind") == "component"]
    assert len(components) == 91


def test_graph_has_5_knowledge_nodes(graph):
    knowledge = [n for n, d in graph.nodes(data=True) if d.get("kind") == "knowledge"]
    assert len(knowledge) == 5


def test_graph_has_type_marker_nodes(graph):
    types = [n for n, d in graph.nodes(data=True) if d.get("kind") == "component_type"]
    # Roughly: 5 docs * avg 5 types = 25 unique-ish, but depends on overlaps
    assert len(types) >= 10


def test_chiller_1_in_graph(graph):
    assert "chiller_1" in graph
    node = graph.nodes["chiller_1"]
    assert node["kind"] == "component"
    assert node["type"] == "chiller"


# ────────────────────────────────────────────────────────────────────
# Knowledge resolution
# ────────────────────────────────────────────────────────────────────
def test_chiller_has_csa_z462(graph):
    """A chiller in Ontario should be governed by CSA Z462-24."""
    knowledge = get_applicable_knowledge(graph, "chiller_1")
    ids = {k["id"] for k in knowledge}
    # The chiller type is in CSA Z462's applies_to list
    assert "csa-z462-24" in ids


def test_jurisdiction_filter_ontario_keeps_canadian(graph):
    knowledge = get_applicable_knowledge(graph, "chiller_1")
    filtered = filter_by_jurisdiction(knowledge, "ontario_canada")
    juris = {k["jurisdiction"] for k in filtered}
    # international + canada + ontario_canada all kept
    assert "ontario_canada" in juris or "canada" in juris


def test_jurisdiction_filter_excludes_non_applicable(graph):
    """Verify pure 'international' docs always pass."""
    knowledge = [
        {"id": "a", "jurisdiction": "international"},
        {"id": "b", "jurisdiction": "us_only"},
        {"id": "c", "jurisdiction": "ontario_canada"},
    ]
    filtered = filter_by_jurisdiction(knowledge, "ontario_canada")
    ids = {k["id"] for k in filtered}
    assert "a" in ids
    assert "c" in ids
    assert "b" not in ids


# ────────────────────────────────────────────────────────────────────
# Upstream chain
# ────────────────────────────────────────────────────────────────────
def test_upstream_rack_has_path_to_utility(graph):
    chain = get_upstream_chain(graph, "rack_a_01_01")
    # Should include at least an RPP
    assert any("rpp" in n for n in chain)


# ────────────────────────────────────────────────────────────────────
# Service end-to-end (triggers model load)
# ────────────────────────────────────────────────────────────────────
@pytest.mark.slow
def test_service_query_basic(service):
    result = service.query("arc flash protection 800VDC", k=3)
    assert "chunks" in result
    assert len(result["chunks"]) <= 3
    assert all("score" in c for c in result["chunks"])
    assert all(0.0 <= c["score"] <= 1.0 for c in result["chunks"])


@pytest.mark.slow
def test_service_query_with_component(service):
    result = service.query(
        "LOTO procedure",
        component_id="chiller_1",
        k=3,
    )
    assert result["component_id"] == "chiller_1"
    assert result["graph_context"]["display"] is not None
    assert isinstance(result["applicable_knowledge"], list)


@pytest.mark.slow
def test_service_loto_with_knowledge(service):
    result = service.loto_with_knowledge("rpp_a_01")
    assert "loto_impact" in result
    assert "applicable_knowledge" in result
    assert "procedure_chunks" in result
    assert isinstance(result["procedure_chunks"], list)


def test_service_upstream(service):
    result = service.upstream("rack_a_01_01")
    assert result["component_id"] == "rack_a_01_01"
    assert isinstance(result["chain"], list)


def test_service_related_knowledge(service):
    result = service.related_knowledge("chiller_1")
    assert result["component_id"] == "chiller_1"
    assert isinstance(result["knowledge"], list)
'''

# ════════════════════════════════════════════════════════════════════════
# Write all files
# ════════════════════════════════════════════════════════════════════════
def main():
    print("=== Sprint S2 Batch 2: Backend modules + tests ===")
    print(f"Project root: {ROOT}")
    print()

    if not ROOT.exists():
        print(f"ERROR: project root not found: {ROOT}")
        return 1

    for path, content in FILES.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            bak = path.with_suffix(path.suffix + ".bak_pre_s2")
            if not bak.exists():
                bak.write_bytes(path.read_bytes())
                print(f"  [bak] {path.name} -> {bak.name}")
        path.write_bytes(content.encode("utf-8"))
        print(f"  [ok]  {path.relative_to(ROOT)} ({len(content)} bytes)")

    print()
    print("=== Batch 2 written ===")
    print()
    print("Next steps:")
    print("  1. AST syntax check: see Batch 2 verification command")
    print("  2. Fast tests: pytest tests/test_graphrag.py -v -m not_slow")
    print("  3. Slow tests (downloads ~90MB model first time):")
    print("     pytest tests/test_graphrag.py -v")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
