"""
backend/tech_assist/document_ingest.py
=======================================
Sprint 7.1b — PDF ingestion pipeline.

Pipeline:
  raw bytes (multipart/form-data upload)
       |
       v   PDFParser.extract_text()
  per-page text (list[str])
       |
       v   chunk_text() with sentence-boundary-aware splitting
  chunks (list[Chunk{text, page_idx, char_offset}])
       |
       v   rag_service.add_documents() -- ChromaDB upsert
  ChromaDB (existing epms_knowledge collection or dedicated
            tech_assist_uploads collection per ingester config)

Design choices:
  * Pluggable parser interface (PDFParser ABC) so tests can inject a
    StubParser without requiring pypdf.
  * Sentence-aware chunker: 600-800 chars per chunk with 100-char
    overlap, broken at '. ' / '\n\n' / '\n' boundaries when possible.
    Standard chunking sweet spot for Tier IV technical manuals.
  * Tier metadata: uploaded docs default to Tier 4 (a3semi-specific)
    but can be overridden via ingest payload (e.g. a vendor manual
    upload should be Tier 2). Operator selects at upload time.
  * Disk persistence of original PDF: data/tech_assist_uploads/
    {document_id}.pdf for forensic reference + re-ingestion if
    chunking strategy changes.

Disambiguation note: this module reuses rag_service's ChromaDB
collection by default. PDF chunks become first-class citizens of
the troubleshoot QA retrieval surface immediately upon successful
ingestion.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ─── Constants ─────────────────────────────────────────────────────────
DEFAULT_CHUNK_SIZE_CHARS = 700
DEFAULT_CHUNK_OVERLAP   = 100
MIN_CHUNK_SIZE_CHARS    = 60      # discard chunks smaller than this
MAX_PDF_SIZE_BYTES      = 50 * 1024 * 1024  # 50MB cap


# ─── Errors ────────────────────────────────────────────────────────────
class DocumentIngestError(RuntimeError):
    pass


class PDFParseError(DocumentIngestError):
    pass


# ─── Chunk dataclass ───────────────────────────────────────────────────
class Chunk:
    """One chunk of extracted text ready for embedding."""

    __slots__ = ("text", "page_idx", "char_offset", "char_length")

    def __init__(self, text: str, page_idx: int, char_offset: int):
        self.text = text
        self.page_idx = page_idx
        self.char_offset = char_offset
        self.char_length = len(text)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "page_idx": self.page_idx,
            "char_offset": self.char_offset,
            "char_length": self.char_length,
        }


# ─── PDF parser interface + impls ──────────────────────────────────────
class PDFParser(ABC):
    """Pluggable PDF text extractor."""

    @abstractmethod
    def extract_pages(self, pdf_bytes: bytes) -> list[str]:
        """Return list of per-page text (length == page count)."""


class PypdfParser(PDFParser):
    """Production parser using pypdf (pure Python, MIT)."""

    def extract_pages(self, pdf_bytes: bytes) -> list[str]:
        try:
            from pypdf import PdfReader  # type: ignore
        except ImportError as e:
            raise DocumentIngestError(
                "pypdf not available. Install via 'pip install pypdf' "
                "or pip install -e .[tech-assist]"
            ) from e

        try:
            from io import BytesIO
            reader = PdfReader(BytesIO(pdf_bytes))
            pages = []
            for page in reader.pages:
                try:
                    txt = page.extract_text() or ""
                except Exception as e:
                    log.warning("[document_ingest] page extract failed: %s", e)
                    txt = ""
                pages.append(txt)
            return pages
        except Exception as e:
            raise PDFParseError(f"pypdf failed to parse PDF: {e}") from e


class StubPDFParser(PDFParser):
    """Test parser: returns pre-supplied page text. Bypasses pypdf entirely."""

    def __init__(self, pages: list[str]):
        self._pages = pages

    def extract_pages(self, _pdf_bytes: bytes) -> list[str]:
        return list(self._pages)


# ─── Chunker ───────────────────────────────────────────────────────────
def chunk_text(
    text: str,
    page_idx: int = 0,
    chunk_size: int = DEFAULT_CHUNK_SIZE_CHARS,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[Chunk]:
    """Split text into overlapping sentence-aware chunks.

    Strategy: target chunk_size chars, prefer breaking at sentence
    boundaries within the second half of the chunk. Overlap by
    `overlap` chars to preserve context across chunk boundaries.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [Chunk(text=text, page_idx=page_idx, char_offset=0)]

    chunks: list[Chunk] = []
    start = 0
    text_len = len(text)

    # Boundary regex: sentence-ending punctuation followed by space, or
    # paragraph break. Used to find natural break points.
    boundary_re = re.compile(r"[.!?]\s+|\n\n+|\n")

    while start < text_len:
        end = min(start + chunk_size, text_len)
        if end < text_len:
            # Search for boundary within the second half of the chunk
            search_start = start + chunk_size // 2
            boundaries = [m.end() for m in boundary_re.finditer(text, search_start, end)]
            if boundaries:
                end = boundaries[-1]

        chunk_str = text[start:end].strip()
        if len(chunk_str) >= MIN_CHUNK_SIZE_CHARS:
            chunks.append(Chunk(text=chunk_str, page_idx=page_idx, char_offset=start))

        if end >= text_len:
            break
        # Slide window with overlap
        next_start = max(start + 1, end - overlap)
        if next_start <= start:  # paranoid guard against infinite loop
            next_start = end
        start = next_start

    return chunks


def chunk_pages(
    pages: list[str],
    chunk_size: int = DEFAULT_CHUNK_SIZE_CHARS,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[Chunk]:
    """Chunk every page; concatenate Chunks across pages."""
    out: list[Chunk] = []
    for idx, page_text in enumerate(pages):
        out.extend(chunk_text(page_text, page_idx=idx,
                              chunk_size=chunk_size, overlap=overlap))
    return out


# ─── Document Ingester ─────────────────────────────────────────────────
def _document_id(prefix: str = "DOC") -> str:
    """DOC-YYYYMMDD-uuid8."""
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"


class DocumentIngester:
    """End-to-end pipeline: PDF bytes -> chunked text -> ChromaDB.

    rag_service contract: must expose .collection (chromadb Collection)
    OR an .add_documents(docs, metadatas, ids) method. We use the
    collection directly to upsert with full metadata control.
    """

    def __init__(
        self,
        rag_service: Any,
        parser: PDFParser | None = None,
        upload_dir: Path | None = None,
    ) -> None:
        self.rag_service = rag_service
        self.parser = parser or PypdfParser()
        self.upload_dir = upload_dir
        if upload_dir:
            upload_dir.mkdir(parents=True, exist_ok=True)

    def ingest_pdf(
        self,
        pdf_bytes: bytes,
        original_filename: str,
        title: str | None = None,
        tier: int = 4,
        priority: str = "medium",
        asset_id: str | None = None,
        vendor: str | None = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE_CHARS,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
        uploaded_by: str | None = None,
    ) -> dict[str, Any]:
        """End-to-end ingestion. Returns summary dict.

        Side effects:
          * Persists the original PDF to upload_dir/{document_id}.pdf
            if upload_dir is configured.
          * Upserts each chunk into rag_service ChromaDB with rich
            metadata for retrieval-time citation.
        """
        t0 = time.perf_counter()

        if not pdf_bytes:
            raise DocumentIngestError("empty PDF payload")
        if len(pdf_bytes) > MAX_PDF_SIZE_BYTES:
            raise DocumentIngestError(
                f"PDF too large: {len(pdf_bytes) / 1024 / 1024:.1f} MB "
                f"exceeds {MAX_PDF_SIZE_BYTES / 1024 / 1024:.0f} MB cap"
            )
        if not self._looks_like_pdf(pdf_bytes):
            raise DocumentIngestError("payload does not look like a PDF (magic bytes mismatch)")
        if tier not in (1, 2, 3, 4):
            raise DocumentIngestError(f"tier must be 1..4, got {tier}")
        if priority not in ("medium", "high", "critical"):
            raise DocumentIngestError(f"priority must be medium/high/critical, got {priority}")

        document_id = _document_id()

        # 1. Parse pages
        try:
            pages = self.parser.extract_pages(pdf_bytes)
        except DocumentIngestError:
            raise
        except Exception as e:
            raise PDFParseError(f"parser raised: {e}") from e

        if not pages:
            raise DocumentIngestError("no pages extracted from PDF")

        # 2. Chunk
        chunks = chunk_pages(pages, chunk_size=chunk_size, overlap=chunk_overlap)
        if not chunks:
            raise DocumentIngestError(
                "no usable chunks (PDF may be image-only or empty after extraction)"
            )

        # 3. Persist original PDF (forensic / re-ingest)
        saved_path: str | None = None
        if self.upload_dir is not None:
            saved_path = str(self.upload_dir / f"{document_id}.pdf")
            try:
                Path(saved_path).write_bytes(pdf_bytes)
            except Exception as e:
                log.warning("[document_ingest] failed to persist %s: %s", saved_path, e)
                saved_path = None

        # 4. Upsert chunks to ChromaDB
        upsert_count = self._upsert_chunks(
            chunks=chunks,
            document_id=document_id,
            original_filename=original_filename,
            title=title or original_filename,
            tier=tier,
            priority=priority,
            asset_id=asset_id,
            vendor=vendor,
            uploaded_by=uploaded_by,
        )

        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        result = {
            "document_id": document_id,
            "title": title or original_filename,
            "original_filename": original_filename,
            "page_count": len(pages),
            "chunk_count": len(chunks),
            "chunks_indexed": upsert_count,
            "tier": tier,
            "priority": priority,
            "asset_id": asset_id,
            "vendor": vendor,
            "saved_path": saved_path,
            "elapsed_ms": elapsed_ms,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
        log.info(
            "[document_ingest] %s ingested: %d pages -> %d chunks in %d ms",
            document_id, len(pages), len(chunks), elapsed_ms,
        )
        return result

    # ── Internals ─────────────────────────────────────────────────────
    @staticmethod
    def _looks_like_pdf(b: bytes) -> bool:
        return len(b) >= 4 and b[:4] == b"%PDF"

    def _upsert_chunks(
        self,
        chunks: list[Chunk],
        document_id: str,
        original_filename: str,
        title: str,
        tier: int,
        priority: str,
        asset_id: str | None,
        vendor: str | None,
        uploaded_by: str | None,
    ) -> int:
        if not hasattr(self.rag_service, "collection") or self.rag_service.collection is None:
            log.warning(
                "[document_ingest] rag_service.collection unavailable; skipping upsert"
            )
            return 0

        ids = [f"{document_id}::chunk_{i:04d}" for i in range(len(chunks))]
        documents = [c.text for c in chunks]
        # ChromaDB metadata values must be primitive (str/int/float/bool).
        # Use None-safe scalars.
        base_meta = {
            "document_id": document_id,
            "doc_id": document_id,           # alias for rag_service compatibility
            "title": title,
            "source": "uploaded_pdf",
            "original_filename": original_filename,
            "tier": int(tier),
            "priority": priority,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
        if asset_id:
            base_meta["asset_id"] = asset_id
        if vendor:
            base_meta["vendor"] = vendor
        if uploaded_by:
            base_meta["uploaded_by"] = uploaded_by

        metadatas = [
            {**base_meta, "chunk_index": i, "page_idx": c.page_idx,
             "char_offset": c.char_offset, "char_length": c.char_length}
            for i, c in enumerate(chunks)
        ]

        try:
            # Use upsert if available, else add (chromadb >=0.4.7 supports upsert)
            coll = self.rag_service.collection
            if hasattr(coll, "upsert"):
                coll.upsert(ids=ids, documents=documents, metadatas=metadatas)
            else:
                coll.add(ids=ids, documents=documents, metadatas=metadatas)
            return len(chunks)
        except Exception as e:
            log.error("[document_ingest] ChromaDB upsert failed: %s", e)
            raise DocumentIngestError(f"chromadb upsert failed: {e}") from e

    def remove_document(self, document_id: str) -> int:
        """Remove all chunks belonging to a document_id. Returns count
        deleted (best-effort)."""
        if not hasattr(self.rag_service, "collection") or self.rag_service.collection is None:
            return 0
        try:
            coll = self.rag_service.collection
            existing = coll.get(where={"document_id": document_id})
            ids = existing.get("ids") or []
            if ids:
                coll.delete(ids=ids)
            return len(ids)
        except Exception as e:
            log.warning("[document_ingest] remove failed for %s: %s", document_id, e)
            return 0


# ─── Singleton ─────────────────────────────────────────────────────────
_ingester: DocumentIngester | None = None


def get_ingester(
    rag_service: Any | None = None,
    upload_dir: Path | None = None,
    parser: PDFParser | None = None,
) -> DocumentIngester:
    global _ingester
    if _ingester is None:
        if rag_service is None:
            raise RuntimeError("DocumentIngester not initialized; first call must pass rag_service")
        _ingester = DocumentIngester(rag_service=rag_service, parser=parser, upload_dir=upload_dir)
        log.info("[document_ingest] DocumentIngester initialized (upload_dir=%s)", upload_dir)
    return _ingester


def reset_ingester() -> None:
    global _ingester
    _ingester = None
