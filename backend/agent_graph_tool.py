"""
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

import logging
from typing import Any

log = logging.getLogger(__name__)

_SERVICE: Any | None = None


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
