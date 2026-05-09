"""
backend/tech_assist/routes.py
=============================
FastAPI router for /api/tech-assist/*.

Endpoints:
  GET  /health                            status + availability flags
  POST /troubleshoot                      Sprint 7.1a real-time QA
  POST /ingest-pdf                        Sprint 7.1b PDF -> ChromaDB
  GET  /documents                         Sprint 7.1b list ingested docs
  DELETE /documents/{id}                  Sprint 7.1b remove doc + chunks
  POST /closure/{wo_id}/dictate           Sprint 7.1c voice/text closure
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
from pydantic import BaseModel, ConfigDict, Field

from backend.cmms_repository import (
    PostgresCMMSRepository,
    WorkOrderNotFoundError,
)
from backend.tech_assist.document_ingest import (
    DocumentIngester,
    DocumentIngestError,
)
from backend.tech_assist.models import TroubleshootRequest, TroubleshootResponse
from backend.tech_assist.troubleshoot import TroubleshootAgent
from backend.tech_assist.voice_closure import (
    ClosureProcessor,
    ClosureNormalizer,
)
from backend.tech_assist.nameplate_ocr import (
    LLMNameplateFallback,
    NameplateProcessor,
)

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


# ─── Sprint 7.1c: Voice / dictation closure ───────────────────────────
class DictateClosureRequest(BaseModel):
    """Body for POST /closure/{wo_id}/dictate (text-mode MVP)."""
    model_config = ConfigDict(extra="forbid")
    cet_id: str = Field(..., min_length=1, max_length=120)
    notes_text: str = Field(..., min_length=10, max_length=8000)
    complete_wo: bool = Field(default=False,
                              description="If true, transition WO status to 'completed'.")
    auto_create_follow_ups: bool = Field(
        default=True,
        description="If false, follow-up suggestions are returned but no WOs created.",
    )


def _get_closure_processor(request: Request) -> ClosureProcessor:
    cp = getattr(request.app.state, "tech_assist_closure_processor", None)
    if cp is None:
        raise HTTPException(status_code=503, detail="Closure processor not initialized")
    return cp


@router.post("/closure/{work_order_id}/dictate")
async def dictate_closure(
    request: Request,
    work_order_id: str,
    body: DictateClosureRequest,
) -> dict[str, Any]:
    """Voice/text dictation of WO closure notes.

    LLM normalizes free-form notes into a structured professional
    report, detects degradation patterns, and (per ADR-006) creates
    follow-up WOs in pending_approval if auto_create_follow_ups=true.

    Audio mode (multipart/form-data with audio/wav) is reserved for
    Sprint 7.1c-vox when faster-whisper is installed.
    """
    cp = _get_closure_processor(request)
    try:
        result = await cp.process(
            wo_id=work_order_id,
            cet_id=body.cet_id,
            notes_text=body.notes_text,
            audio_bytes=None,
            complete_wo=body.complete_wo,
            auto_create_follow_ups=body.auto_create_follow_ups,
        )
        return result
    except WorkOrderNotFoundError:
        raise HTTPException(status_code=404,
                            detail=f"work_order '{work_order_id}' not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        log.exception("dictate_closure failed: %s", e)
        raise HTTPException(status_code=500, detail=f"closure error: {e}")


# ─── Sprint 7.1d: Nameplate OCR ───────────────────────────────────────
class NameplateExtractRequest(BaseModel):
    """Body for POST /nameplate/extract (text-mode MVP)."""
    model_config = ConfigDict(extra="forbid")
    ocr_text: str = Field(..., min_length=5, max_length=4000,
                          description="Raw OCR text from a nameplate photo. "
                                      "Browser-side OCR or pre-OCR'd manually.")
    asset_type_hint: str | None = Field(default=None,
                                        description="Optional asset_type filter "
                                                    "(ups/chiller/cdu/...) to "
                                                    "narrow candidate pool.")


def _get_nameplate_processor(request: Request) -> NameplateProcessor:
    np = getattr(request.app.state, "tech_assist_nameplate_processor", None)
    if np is None:
        raise HTTPException(status_code=503, detail="Nameplate processor not initialized")
    return np


@router.post("/nameplate/extract")
async def nameplate_extract(
    request: Request,
    body: NameplateExtractRequest,
) -> dict[str, Any]:
    """Extract structured fields from nameplate OCR text + match assets.

    MVP text-mode contract: caller supplies pre-OCR'd text. Browser
    can use the Web FileReader API + a JS OCR library, OR an admin
    pre-OCR's via easyocr/tesseract on a workstation, OR pastes the
    text directly in the demo. Image-mode upload is reserved for
    Sprint 7.1d-vision.

    Pipeline:
      regex extraction (fast, deterministic)  ->
      LLM fallback if confidence < 0.4 (LM Studio gemma)  ->
      fuzzy match against assets registry (difflib, no new deps)  ->
      suggested_action: link_to_existing | operator_confirm | seed_new_asset
    """
    np = _get_nameplate_processor(request)
    try:
        return await np.process(
            ocr_text=body.ocr_text,
            asset_type_hint=body.asset_type_hint,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        log.exception("nameplate_extract failed: %s", e)
        raise HTTPException(status_code=500, detail=f"nameplate error: {e}")


def register_tech_assist_routes(
    app: FastAPI,
    rag_service: Any | None,
    cmms_repo: PostgresCMMSRepository | None,
    upload_dir: Path | None = None,
) -> None:
    """Mount the router + initialize agent + ingester + closure + nameplate."""
    agent = TroubleshootAgent(rag_service=rag_service, cmms_repo=cmms_repo)
    app.state.tech_assist_agent = agent

    if rag_service is not None:
        ingester = DocumentIngester(rag_service=rag_service, upload_dir=upload_dir)
        app.state.tech_assist_ingester = ingester
        log.info("Tech Assist ingester ready (upload_dir=%s)", upload_dir)
    else:
        log.warning("Tech Assist ingester NOT registered: rag_service unavailable")

    if cmms_repo is not None:
        closure_processor = ClosureProcessor(
            cmms_repo=cmms_repo,
            normalizer=ClosureNormalizer(),
            transcriber=None,
        )
        app.state.tech_assist_closure_processor = closure_processor
        log.info("Tech Assist closure processor ready (text-mode)")

        nameplate_processor = NameplateProcessor(
            cmms_repo=cmms_repo,
            ocr_engine=None,
            llm_fallback=LLMNameplateFallback(),
        )
        app.state.tech_assist_nameplate_processor = nameplate_processor
        log.info("Tech Assist nameplate processor ready (regex + LLM fallback)")
    else:
        log.warning("Tech Assist closure / nameplate NOT registered: cmms_repo unavailable")

    if not getattr(app.state, "_tech_assist_router_registered", False):
        app.include_router(router)
        app.state._tech_assist_router_registered = True
    log.info("Tech Assist routes registered: 7 endpoints active under /api/tech-assist")
