"""
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

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

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

    knowledge_id: str  # parent doc id
    chunk_index: int  # position within doc
    text: str  # raw chunk text
    score: float  # cosine similarity (0..1)
    knowledge_meta: dict  # frontmatter of parent doc


def _split_frontmatter(raw: str) -> tuple[dict, str]:
    """Parse the YAML frontmatter and return (meta, body)."""
    if not raw.startswith("---"):
        return {}, raw
    end = raw.index("---", 3)
    fm_text = raw[3:end].strip()
    body = raw[end + 3 :].lstrip("\n")
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
        self._embeddings: np.ndarray | None = None  # (N, dim) normalized
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
            log.info(
                "[graphrag] lazy-loading index (first query triggers model download if cache missing)..."
            )
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
                self._chunks.append(
                    {
                        "knowledge_id": kn.id,
                        "chunk_index": i,
                        "text": c,
                    }
                )

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
        filter_jurisdictions: list[str] | None = None,
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
            candidates = list(zip(indices[0].tolist(), scores[0].tolist(), strict=False))
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
            hits.append(
                ChunkHit(
                    knowledge_id=chunk["knowledge_id"],
                    chunk_index=chunk["chunk_index"],
                    text=chunk["text"],
                    score=float(score),
                    knowledge_meta=meta,
                )
            )
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
            "backend": "faiss"
            if self._faiss_index is not None
            else ("numpy" if self._loaded else "not_loaded"),
        }


# ── module-level singleton ──
_DEFAULT_CORPUS = Path(__file__).parent.parent / "config" / "knowledge"
_INDEX: GraphRAGIndex | None = None


def get_index() -> GraphRAGIndex:
    """Returns the module singleton, creating it if needed (no lazy load yet)."""
    global _INDEX
    if _INDEX is None:
        _INDEX = GraphRAGIndex(_DEFAULT_CORPUS)
    return _INDEX
