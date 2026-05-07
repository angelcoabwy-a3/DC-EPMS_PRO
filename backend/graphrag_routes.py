"""
backend/graphrag_routes.py - Sprint S2 (rev 2)

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


# Module-level pydantic models (FastAPI's forward-ref resolution requires
# these to be in the global namespace, not nested in a function).
class QueryReq(BaseModel):
    text: str = Field(..., min_length=2, description="Free-text query")
    component_id: Optional[str] = Field(None, description="Optional component context")
    k: int = Field(5, ge=1, le=20, description="Top-k results")
    jurisdictions: Optional[list[str]] = Field(
        None,
        description="Restrict to these jurisdictions (international always included)",
    )


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
