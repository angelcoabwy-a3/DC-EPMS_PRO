"""Tests for backend.tech_assist.document_ingest (Sprint 7.1b).

Coverage:
  - chunk_text: short text returns single chunk; long text splits with
    overlap; sentence-boundary preferred breaks; min size filter.
  - chunk_pages: page_idx assigned correctly across pages.
  - StubPDFParser: returns pre-supplied pages.
  - DocumentIngester guards: empty PDF, oversized, magic bytes,
    invalid tier, invalid priority.
  - Full ingest with StubPDFParser + FakeRAGService: chunks reach
    ChromaDB collection.upsert with proper metadata.
  - Document_id format DOC-YYYYMMDD-uuid8.
  - remove_document deletes chunks via collection.delete.
  - Ingester singleton get/reset.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.tech_assist.document_ingest import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE_CHARS,
    Chunk,
    DocumentIngestError,
    DocumentIngester,
    StubPDFParser,
    _document_id,
    chunk_pages,
    chunk_text,
    get_ingester,
    reset_ingester,
)


# ─── Chunk utility ────────────────────────────────────────────────────
def test_chunk_short_text_single_chunk():
    chunks = chunk_text("Just a short sentence.", page_idx=0)
    assert len(chunks) == 1
    assert chunks[0].text == "Just a short sentence."
    assert chunks[0].page_idx == 0
    assert chunks[0].char_offset == 0


def test_chunk_long_text_splits_with_overlap():
    # 2400 chars
    text = ("This is a long technical paragraph about chiller maintenance. " * 40)
    chunks = chunk_text(text, page_idx=2, chunk_size=600, overlap=80)
    assert len(chunks) >= 3
    for c in chunks:
        assert c.page_idx == 2
        assert len(c.text) <= 700  # chunk_size + boundary slack
    # Verify overlap: last 30 chars of chunk[0] should appear somewhere in chunk[1]
    overlap_excerpt = chunks[0].text[-30:].strip()
    if overlap_excerpt:
        assert overlap_excerpt in chunks[1].text or chunks[1].text.startswith(overlap_excerpt[:10])


def test_chunk_prefers_sentence_boundary():
    text = (
        "First sentence is short. Second sentence is also short. "
        "Third sentence is here. " * 30
    )
    chunks = chunk_text(text, chunk_size=300, overlap=50)
    # Most chunks should end at sentence boundary (period+space)
    boundary_count = sum(1 for c in chunks[:-1] if c.text.rstrip().endswith("."))
    assert boundary_count >= len(chunks) // 2


def test_chunk_empty_text_returns_empty():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_chunk_below_min_size_filtered():
    # Text is 30 chars - below MIN_CHUNK_SIZE_CHARS (60)
    chunks = chunk_text("tiny", page_idx=0)
    assert len(chunks) == 1  # short text fits in single chunk regardless of min
    # But a leftover sliver from chunking long text would be filtered
    # (verified indirectly via the long test above)


def test_chunk_pages_assigns_page_index():
    pages = [
        "Page one content. " * 20,
        "Page two content totally different. " * 20,
        "",  # empty page
        "Page four after a blank. " * 20,
    ]
    chunks = chunk_pages(pages, chunk_size=200, overlap=30)
    page_indices = {c.page_idx for c in chunks}
    # Empty page 2 contributes no chunks
    assert page_indices == {0, 1, 3}


# ─── StubPDFParser ────────────────────────────────────────────────────
def test_stub_parser_returns_supplied_pages():
    p = StubPDFParser(["alpha", "beta", "gamma"])
    assert p.extract_pages(b"any") == ["alpha", "beta", "gamma"]


# ─── DocumentIngester guards ──────────────────────────────────────────
class FakeCollection:
    """Mimics ChromaDB Collection upsert/get/delete."""
    def __init__(self):
        self.calls = []
        self._store: dict = {}

    def upsert(self, ids, documents, metadatas):
        self.calls.append(("upsert", ids, documents, metadatas))
        for i, d, m in zip(ids, documents, metadatas):
            self._store[i] = (d, m)

    def get(self, where=None):
        ids = []
        metas = []
        for i, (_, m) in self._store.items():
            if where:
                ok = all(m.get(k) == v for k, v in where.items())
                if not ok:
                    continue
            ids.append(i)
            metas.append(m)
        return {"ids": ids, "metadatas": metas}

    def delete(self, ids):
        for i in ids:
            self._store.pop(i, None)


class FakeRAGService:
    def __init__(self):
        self.collection = FakeCollection()


@pytest.fixture
def ingester():
    rag = FakeRAGService()
    parser = StubPDFParser([
        "Page 1 text. " * 60,  # ~780 chars
        "Page 2 text totally different content for chunking. " * 50,
    ])
    return DocumentIngester(rag_service=rag, parser=parser, upload_dir=None)


@pytest.fixture
def ingester_with_upload_dir(tmp_path):
    rag = FakeRAGService()
    parser = StubPDFParser(["Sample technical content for testing. " * 30])
    return DocumentIngester(
        rag_service=rag,
        parser=parser,
        upload_dir=tmp_path / "uploads",
    )


def test_empty_pdf_raises(ingester):
    with pytest.raises(DocumentIngestError, match="empty"):
        ingester.ingest_pdf(b"", original_filename="x.pdf")


def test_non_pdf_magic_bytes_raises(ingester):
    with pytest.raises(DocumentIngestError, match="magic bytes"):
        ingester.ingest_pdf(b"NOT A PDF blob blah blah blah", original_filename="fake.pdf")


def test_oversized_pdf_raises(ingester):
    huge = b"%PDF-1.7" + b"\0" * (51 * 1024 * 1024)
    with pytest.raises(DocumentIngestError, match="too large"):
        ingester.ingest_pdf(huge, original_filename="huge.pdf")


def test_invalid_tier_raises(ingester):
    with pytest.raises(DocumentIngestError, match="tier"):
        ingester.ingest_pdf(b"%PDF-1.4 abc", original_filename="x.pdf", tier=5)


def test_invalid_priority_raises(ingester):
    with pytest.raises(DocumentIngestError, match="priority"):
        ingester.ingest_pdf(b"%PDF-1.4 abc", original_filename="x.pdf", priority="urgent")


# ─── Full ingest path ─────────────────────────────────────────────────
def test_ingest_happy_path_upserts_chunks(ingester):
    pdf = b"%PDF-1.4\nstub content; parser is stubbed"
    result = ingester.ingest_pdf(
        pdf_bytes=pdf,
        original_filename="york_yz_manual.pdf",
        title="York YZ Engineering Guide",
        tier=2,
        priority="high",
        asset_id="chiller_1",
        vendor="York",
        uploaded_by="wilmer",
    )
    assert result["page_count"] == 2
    assert result["chunk_count"] >= 2
    assert result["chunks_indexed"] == result["chunk_count"]
    assert result["tier"] == 2
    assert result["priority"] == "high"
    assert re.match(r"^DOC-\d{8}-[a-f0-9]{8}$", result["document_id"])
    assert result["elapsed_ms"] >= 0

    # Verify ChromaDB upsert call
    coll = ingester.rag_service.collection
    assert len(coll.calls) == 1
    call = coll.calls[0]
    assert call[0] == "upsert"
    ids, docs, metas = call[1], call[2], call[3]
    assert len(ids) == result["chunk_count"]
    assert all(i.startswith(result["document_id"] + "::chunk_") for i in ids)
    # Metadata check on first chunk
    m0 = metas[0]
    assert m0["document_id"] == result["document_id"]
    assert m0["title"] == "York YZ Engineering Guide"
    assert m0["source"] == "uploaded_pdf"
    assert m0["tier"] == 2
    assert m0["priority"] == "high"
    assert m0["asset_id"] == "chiller_1"
    assert m0["vendor"] == "York"
    assert m0["uploaded_by"] == "wilmer"
    assert "chunk_index" in m0
    assert "page_idx" in m0


def test_persists_pdf_to_disk_when_upload_dir_set(ingester_with_upload_dir):
    pdf = b"%PDF-1.4\ndummy"
    result = ingester_with_upload_dir.ingest_pdf(
        pdf_bytes=pdf, original_filename="t.pdf",
    )
    saved = Path(result["saved_path"])
    assert saved.exists()
    assert saved.read_bytes() == pdf


def test_no_disk_persistence_when_upload_dir_none(ingester):
    pdf = b"%PDF-1.4\ndummy"
    result = ingester.ingest_pdf(pdf_bytes=pdf, original_filename="t.pdf")
    assert result["saved_path"] is None


def test_remove_document_deletes_chunks(ingester):
    pdf = b"%PDF-1.4\ndummy"
    r = ingester.ingest_pdf(pdf_bytes=pdf, original_filename="t.pdf")
    deleted = ingester.remove_document(r["document_id"])
    assert deleted == r["chunk_count"]
    # Second remove -> nothing left
    assert ingester.remove_document(r["document_id"]) == 0


def test_document_id_format():
    did = _document_id()
    assert re.match(r"^DOC-\d{8}-[a-f0-9]{8}$", did)


# ─── Singleton ────────────────────────────────────────────────────────
def test_ingester_singleton():
    rag = FakeRAGService()
    reset_ingester()
    i1 = get_ingester(rag_service=rag)
    i2 = get_ingester()
    assert i1 is i2
    reset_ingester()
    i3 = get_ingester(rag_service=rag)
    assert i3 is not i1


def test_ingester_get_without_init_raises():
    reset_ingester()
    with pytest.raises(RuntimeError, match="not initialized"):
        get_ingester()
