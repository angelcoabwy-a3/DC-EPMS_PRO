"""
backend/tech_assist/routes.py
=============================
FastAPI router for /api/tech-assist/*.

Endpoints:
  GET  /health                  status + rag/cmms availability flags
  POST /troubleshoot            Sprint 7.1a real-time QA
  POST /ingest-pdf              Sprint 7.1b PDF -> chunks -> ChromaDB
  GET  /documents               Sprint 7.1b list ingested docs
  DELETE /documents/{id}        Sprint 7.1b remove doc + chunks
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)

from backend.tech_assist.document_ingest import (
    DocumentIngester,
    DocumentIngestError,
)
from backend.tech_assist.models import TroubleshootRequest, TroubleshootResponse
from backend.tech_assist.troubleshoot import TroubleshootAgent

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tech-assist", tags=["tech-assist"])


def _get_agent(request: Request) -> TroubleshootAgent:
    agent = getattr(request.app.state, "tech_assist_agent", None)
    if agent is None:
        raise HTTPException(status_code=503, detail="Tech Assist agent not initialized")
    return agent


def _get_ingester(request: Request) -> DocumentIngester:
    ing = getattr(request.app.state, "tech_assist_ingester", None)
    if ing is None:
        raise HTTPException(status_code=503, detail="Document ingester not initialized")
    return ing


@router.get("/health")
async def tech_assist_health(request: Request) -> dict[str, Any]:
    agent = getattr(request.app.state, "tech_assist_agent", None)
    ing = getattr(request.app.state, "tech_assist_ingester", None)
    return {
        "status": "up" if agent is not None else "uninitialized",
        "rag_available":   agent.rag_service is not None if agent else False,
        "cmms_available":  agent.cmms_repo    is not None if agent else False,
        "lm_studio_url":   agent.lm_studio_url if agent else None,
        "lm_studio_model": agent.lm_studio_model if agent else None,
        "ingest_available": ing is not None,
        "upload_dir":      str(ing.upload_dir) if ing and ing.upload_dir else None,
    }


@router.post("/troubleshoot", response_model=TroubleshootResponse)
async def troubleshoot(request: Request, body: TroubleshootRequest) -> TroubleshootResponse:
    """Real-time field assistance.

    Combines knowledge corpus retrieval (rag_service) + asset failure
    history (cmms_repository) + LLM synthesis (LM Studio gemma) into
    a structured 3-section answer with citations. ADR-006 compliant:
    advisory only, no autonomous action."""
    agent = _get_agent(request)
    try:
        return await agent.answer(body)
    except Exception as e:
        log.exception("troubleshoot failed: %s", e)
        raise HTTPException(status_code=500, detail=f"troubleshoot error: {e}")


@router.post("/ingest-pdf")
async def ingest_pdf(
    request: Request,
    file: UploadFile = File(..., description="PDF file (max 50 MB)"),
    title: str | None = Form(default=None),
    tier: int = Form(default=4, ge=1, le=4),
    priority: str = Form(default="medium"),
    asset_id: str | None = Form(default=None),
    vendor: str | None = Form(default=None),
    uploaded_by: str | None = Form(default=None),
) -> dict[str, Any]:
    """Ingest a PDF manual into the knowledge corpus (Sprint 7.1b).

    The PDF is parsed page-by-page, chunked with sentence-aware
    overlap, and upserted into the ChromaDB collection so subsequent
    troubleshoot queries can cite it. Original PDF persisted to
    upload_dir for forensic reference.

    Tier guidance:
      1 = Safety (LOTO, arc flash, EPO)
      2 = Vendor procedure (Schneider, York, NVIDIA, Starline)
      3 = Standard (ASHRAE, IEC, NFPA, ISO)
      4 = a3semi-specific MOP/EOP (default)
    """
    ing = _get_ingester(request)
    if not file.filename:
        raise HTTPException(status_code=400, detail="missing filename")
    pdf_bytes = await file.read()
    try:
        result = ing.ingest_pdf(
            pdf_bytes=pdf_bytes,
            original_filename=file.filename,
            title=title,
            tier=tier,
            priority=priority,
            asset_id=asset_id,
            vendor=vendor,
            uploaded_by=uploaded_by,
        )
        return result
    except DocumentIngestError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.exception("ingest_pdf failed: %s", e)
        raise HTTPException(status_code=500, detail=f"ingest error: {e}")


@router.get("/documents")
async def list_documents(request: Request) -> dict[str, Any]:
    """List ingested documents by querying ChromaDB metadata.

    Groups by document_id. Returns one summary entry per uploaded PDF.
    """
    ing = _get_ingester(request)
    rag = ing.rag_service
    if rag is None or not hasattr(rag, "collection") or rag.collection is None:
        return {"count": 0, "documents": []}

    try:
        result = rag.collection.get(where={"source": "uploaded_pdf"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"query failed: {e}")

    metas = result.get("metadatas") or []
    docs: dict[str, dict[str, Any]] = {}
    for meta in metas:
        if not meta:
            continue
        did = meta.get("document_id")
        if not did:
            continue
        if did not in docs:
            docs[did] = {
                "document_id": did,
                "title": meta.get("title"),
                "original_filename": meta.get("original_filename"),
                "tier": meta.get("tier"),
                "priority": meta.get("priority"),
                "asset_id": meta.get("asset_id"),
                "vendor": meta.get("vendor"),
                "uploaded_at": meta.get("uploaded_at"),
                "uploaded_by": meta.get("uploaded_by"),
                "chunk_count": 0,
            }
        docs[did]["chunk_count"] += 1

    return {
        "count": len(docs),
        "documents": sorted(
            docs.values(), key=lambda d: d.get("uploaded_at") or "", reverse=True,
        ),
    }


@router.delete("/documents/{document_id}")
async def delete_document(request: Request, document_id: str) -> dict[str, Any]:
    """Remove all chunks for a document_id from the corpus."""
    ing = _get_ingester(request)
    deleted = ing.remove_document(document_id)
    return {"document_id": document_id, "chunks_deleted": deleted}


def register_tech_assist_routes(
    app: FastAPI,
    rag_service: Any | None,
    cmms_repo: Any | None,
    upload_dir: Path | None = None,
) -> None:
    """Mount the router + initialize agent + ingester on app.state."""
    agent = TroubleshootAgent(rag_service=rag_service, cmms_repo=cmms_repo)
    app.state.tech_assist_agent = agent

    if rag_service is not None:
        ingester = DocumentIngester(rag_service=rag_service, upload_dir=upload_dir)
        app.state.tech_assist_ingester = ingester
        log.info("Tech Assist ingester ready (upload_dir=%s)", upload_dir)
    else:
        log.warning("Tech Assist ingester NOT registered: rag_service unavailable")

    if not getattr(app.state, "_tech_assist_router_registered", False):
        app.include_router(router)
        app.state._tech_assist_router_registered = True
    log.info("Tech Assist routes registered: 5 endpoints active under /api/tech-assist")
