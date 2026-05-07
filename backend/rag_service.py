"""
DC-EPMS PRO — RAG Service v2 (Tier-Aware)
==========================================
ChromaDB-backed retrieval augmented generation with metadata filtering
and tier-based priority scoring.

Tier hierarchy (higher priority = retrieved first for safety queries):
  Tier 1: Safety (LOTO, arc flash, confined space, fire, EPO)
  Tier 2: Vendor procedures (Schneider, York, NVIDIA, Starline)
  Tier 3: Standards & calculations (ASHRAE, IEC, ISO, NFPA)
  Tier 4: a3semi-specific MOPs and EOPs

Safety-first retrieval: when query contains safety keywords, Tier 1
docs are boosted in ranking. See SAFETY_KEYWORDS for triggers.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Optional

try:
    import chromadb
    from chromadb.config import Settings
except ImportError:
    chromadb = None
    Settings = None

log = logging.getLogger("dc-epms.rag")

# ── Safety keyword triggers (boost Tier 1 retrieval) ─────────────────
SAFETY_KEYWORDS = {
    "loto", "lockout", "tagout", "arc flash", "arc-flash", "arcflash",
    "energized", "ppe", "electrocution", "shock", "isolation",
    "confined space", "epo", "emergency power off", "shunt trip",
    "fire", "smoke", "suppression", "vesda", "evacuation",
    "hazmat", "hazard", "safety", "emergency", "injury", "victim",
    "fatality", "lethal", "dangerous", "combustion",
    "class 0", "class 2", "nfpa 70e", "csa z462",
}


class RAGService:
    """Tier-aware retrieval augmented generation service."""

    def __init__(
        self,
        chroma_path: str,
        collection_name: str = "epms_knowledge",
    ):
        if chromadb is None:
            raise RuntimeError(
                "chromadb not installed - run: pip install chromadb"
            )
        self.chroma_path = chroma_path
        self.collection_name = collection_name
        self._lock = threading.Lock()

        os.makedirs(chroma_path, exist_ok=True)

        self.client = chromadb.PersistentClient(
            path=chroma_path,
            settings=Settings(anonymized_telemetry=False),
        )

        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        log.info(
            "ChromaDB connected: %s (%d docs)",
            chroma_path,
            self.collection.count(),
        )

    def count(self) -> int:
        """Total indexed chunks."""
        with self._lock:
            return self.collection.count()

    def upsert(
        self,
        doc_id: str,
        text: str,
        metadata: Optional[dict] = None,
    ) -> None:
        """Insert or replace a document.

        Metadata conventions used by tier-aware retrieval:
          tier         : int 1-4
          priority     : 'critical' | 'high' | 'medium'
          domain       : subsystem (e.g., 'electrical_safety')
          standard     : referenced standard (e.g., 'NFPA 70E')
          doc_type     : 'MOP' | 'EOP' | 'STANDARD' | 'VENDOR'
          keywords     : comma-separated tag list
        """
        meta = metadata or {}
        # ChromaDB only accepts primitive metadata values
        clean_meta = {}
        for k, v in meta.items():
            if isinstance(v, (str, int, float, bool)):
                clean_meta[k] = v
            elif isinstance(v, list):
                clean_meta[k] = ",".join(str(x) for x in v)
            else:
                clean_meta[k] = str(v)

        with self._lock:
            try:
                self.collection.upsert(
                    ids=[doc_id],
                    documents=[text],
                    metadatas=[clean_meta],
                )
            except Exception as e:
                log.error("upsert failed for %s: %s", doc_id, e)
                raise

    def delete(self, doc_id: str) -> None:
        with self._lock:
            self.collection.delete(ids=[doc_id])

    def query(
        self,
        question: str,
        n_results: int = 5,
        tier_filter: Optional[int] = None,
        min_priority: Optional[str] = None,
    ) -> dict:
        """Semantic search with tier-based priority boosting."""
        safety_boost = self._query_needs_safety_priority(question)

        fetch_n = max(n_results * 3, 15)

        where_clause = None
        if tier_filter is not None:
            where_clause = {"tier": tier_filter}

        with self._lock:
            try:
                raw = self.collection.query(
                    query_texts=[question],
                    n_results=fetch_n,
                    where=where_clause,
                )
            except Exception as e:
                log.error("query failed: %s", e)
                return {
                    "question": question,
                    "results": [],
                    "tier_distribution": {},
                    "safety_boosted": safety_boost,
                    "error": str(e),
                }

        docs = raw.get("documents", [[]])[0]
        metas = raw.get("metadatas", [[]])[0]
        ids = raw.get("ids", [[]])[0]
        dists = raw.get("distances", [[]])[0]

        # Convert distances to similarity scores, apply tier boost
        results = []
        for doc_id, text, meta, dist in zip(ids, docs, metas, dists):
            similarity = 1.0 - (dist or 0.0)
            try:
                tier = int((meta or {}).get("tier", 4))
            except (ValueError, TypeError):
                tier = 4
            priority = (meta or {}).get("priority", "medium")

            if min_priority:
                priority_order = {"medium": 0, "high": 1, "critical": 2}
                if priority_order.get(priority, 0) < priority_order.get(
                    min_priority, 0
                ):
                    continue

            boost = 0.0
            if safety_boost and tier == 1:
                boost = 0.30
            elif tier == 1:
                boost = 0.10
            elif tier == 2:
                boost = 0.05

            score = similarity + boost
            results.append(
                {
                    "doc_id": doc_id,
                    "text": text,
                    "metadata": meta or {},
                    "score": score,
                    "similarity": similarity,
                    "tier": tier,
                    "boost": boost,
                }
            )

        results.sort(key=lambda r: r["score"], reverse=True)
        results = results[:n_results]

        tier_dist = {}
        for r in results:
            tier_dist[r["tier"]] = tier_dist.get(r["tier"], 0) + 1

        return {
            "question": question,
            "results": results,
            "tier_distribution": tier_dist,
            "safety_boosted": safety_boost,
            "total_indexed": self.count(),
        }

    def _query_needs_safety_priority(self, question: str) -> bool:
        """Detect if query should boost Tier 1 results."""
        q = question.lower()
        return any(kw in q for kw in SAFETY_KEYWORDS)

    def build_context(
        self,
        question: str,
        n_results: int = 4,
        max_chars: int = 6000,
    ) -> str:
        """Retrieve and format context for injection into LLM prompt."""
        result = self.query(question, n_results=n_results)
        chunks = result["results"]

        if not chunks:
            return "No relevant documents found in the knowledge base."

        context_parts = []
        total_chars = 0

        for i, chunk in enumerate(chunks, 1):
            doc_id = chunk["doc_id"]
            text = chunk["text"]
            meta = chunk["metadata"]
            tier = meta.get("tier", "?")
            priority = meta.get("priority", "")
            standard = meta.get("standard", "")

            header = f"[Source {i}: {doc_id} | Tier {tier}"
            if priority:
                header += f" ({priority})"
            if standard:
                header += f" | {standard}"
            header += "]"

            remaining = max_chars - total_chars - len(header) - 20
            if remaining <= 100:
                break
            if len(text) > remaining:
                text = text[:remaining].rsplit(" ", 1)[0] + "..."

            chunk_block = f"{header}\n{text}\n"
            context_parts.append(chunk_block)
            total_chars += len(chunk_block)

        return "\n---\n".join(context_parts)


# ── Module-level convenience ────────────────────────────────────────

_service_instance: Optional[RAGService] = None


def get_service(
    chroma_path: Optional[str] = None,
) -> RAGService:
    """Get or create the singleton RAG service."""
    global _service_instance
    if _service_instance is None:
        path = chroma_path or os.environ.get("CHROMA_PATH", "data/chroma_db")
        _service_instance = RAGService(path)
    return _service_instance
