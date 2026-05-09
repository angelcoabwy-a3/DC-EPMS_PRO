"""
backend/tech_assist/models.py
=============================
Pydantic DTOs for the Tech Assist API surface.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ─── Request ───────────────────────────────────────────────────────────
class TroubleshootRequest(BaseModel):
    """Body for POST /api/tech-assist/troubleshoot."""
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=3, max_length=600,
                       description="Free-form technician question.")
    asset_id: str | None = Field(
        default=None,
        description="Canonical asset id (e.g. chiller_1). When provided, "
                    "the response includes asset-specific failure history "
                    "and MOP linkage.",
    )
    error_code: str | None = Field(
        default=None, max_length=64,
        description="Optional manufacturer error code (e.g. 'E-204').",
    )
    k_chunks: int = Field(
        default=4, ge=1, le=15,
        description="Number of manual chunks to retrieve from RAG.",
    )
    history_months: int = Field(
        default=12, ge=1, le=60,
        description="WO history lookback window in months.",
    )
    use_llm: bool = Field(
        default=True,
        description="If False, return retrieved context only (no LLM call).",
    )


# ─── Response ──────────────────────────────────────────────────────────
class ManualChunk(BaseModel):
    """A retrieved snippet from the knowledge corpus."""
    doc_id: str
    score: float
    tier: int
    metadata: dict[str, Any] = Field(default_factory=dict)
    text_excerpt: str  # first 500 chars; full text is in source


class HistoricalWO(BaseModel):
    """Compact view of a past work order for prompt context."""
    work_order_id: str
    timestamp: datetime
    work_class: str
    status: str
    priority: str
    issue_summary: str
    closure_summary: str | None = None  # from result_json or last update


class TroubleshootResponse(BaseModel):
    """Body returned by POST /api/tech-assist/troubleshoot."""
    model_config = ConfigDict(extra="forbid")

    query: str
    asset_id: str | None
    error_code: str | None

    # Retrieval context
    chunks_retrieved: list[ManualChunk]
    history_count: int
    historical_wos: list[HistoricalWO]
    asset_metadata: dict[str, Any] | None

    # LLM output (None if use_llm=false or LLM failed)
    llm_answer: str | None
    llm_synthesis_status: str  # "success" | "skipped" | "timeout" | "error"
    llm_model: str | None      # which model produced the answer
    decision_time_ms: int

    # Audit
    safety_keywords_detected: list[str]
    sources_consulted: dict[str, str]  # source name -> outcome
