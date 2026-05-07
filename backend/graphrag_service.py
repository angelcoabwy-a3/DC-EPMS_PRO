"""
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

import logging
from pathlib import Path
from typing import Any

import networkx as nx
from graphrag_index import GraphRAGIndex, get_index

from backend.knowledge_graph import (
    build_knowledge_graph,
    filter_by_jurisdiction,
    get_applicable_knowledge,
    get_upstream_chain,
)

log = logging.getLogger(__name__)


class GraphRAGService:
    """Cohesive facade over the knowledge graph + vector index."""

    def __init__(self, site_model_obj: Any, knowledge_dir: Path):
        self.site_model = site_model_obj
        self.knowledge_dir = knowledge_dir
        self._graph: nx.MultiDiGraph | None = None
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
        component_id: str | None = None,
        k: int = 5,
        jurisdictions: list[str] | None = None,
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
        hits = self._index.search(
            loto_query, k=3, filter_jurisdictions=["canada", "ontario_canada"]
        )

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
