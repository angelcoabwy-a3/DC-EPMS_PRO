"""
backend/procedure_routes.py
===========================
FastAPI router exposing the ProcedureGenerator over HTTP (Sprint Bite G5).

Endpoints (mounted under /api/procedures by main.py):

  POST /api/procedures/generate            Generate a SOP / MOP / EOP / EMP
                                           via the deterministic factory
                                           (compile_procedure, ADR-010).
  POST /api/procedures/{id}/activate       RBAC-gated DRAFT -> ACTIVE promotion

Epic 6 (LLM-narrative Procedure Architect, mounted under the same
prefix at a distinct sub-path to avoid colliding with G5's
deterministic /generate above):

  POST /api/procedures/architect/generate  LLM-authored SOP/MOP/EOP/EMP
                                           with deterministic Safety
                                           Officer audit pipeline.
  POST /api/procedures/architect/sign      Operator signs an approved
                                           draft into the forensic ledger.

/generate (G5) routes to the procedure_generator factories via
compile_procedure(). /activate routes to procedure_engine.promote_procedure
and maps its RBAC / state exceptions to clean HTTP status codes:
  RBACDeniedError             -> 403 Forbidden
  InvalidTransitionError -> 400 Bad Request
  ValueError (bad input) -> 400 Bad Request

/architect/* (Epic 6) routes to backend.agents.procedure_architect and
audits the result before returning. A MOP missing LOTO/PPE/CSA Z462
emits ``safety_audit.verdict == "hard_stop"``; the response carries
that verdict so the HMI can refuse to surface a Sign button.

HONEST: generated DRAFTs are not persisted server-side (there is no draft
store yet). /activate is therefore stateless -- the client round-trips
the DRAFT dict it received from /generate, and the {id} path segment is
cross-checked against it. A DB-backed draft store is future work.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.agents.procedure_architect import (
    DOC_TYPE_EMP,
    DOC_TYPE_EOP,
    DOC_TYPE_MOP,
    DOC_TYPE_SOP,
    ProcedureArchitectAgent,
    ProcedureDraft,
    audit_procedure_safety,
)
from backend.cmms_models import RBACDeniedError
from backend.procedure_engine import InvalidTransitionError, promote_procedure
from backend.procedure_generator import compile_procedure

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/procedures", tags=["procedure-generator"])


class GenerateRequest(BaseModel):
    """Body for POST /api/procedures/generate."""

    asset_id: str = Field(..., min_length=1, max_length=128)
    procedure_class: str = Field(..., pattern="^(SOP|MOP|EOP|EMP)$")
    anomaly_profile: str | None = Field(default=None, max_length=64)
    actor_role: str | None = Field(
        default=None,
        description="Compiling role (mock until auth is wired); defaults to TECH_L4.",
    )


class ActivateRequest(BaseModel):
    """Body for POST /api/procedures/{procedure_id}/activate."""

    actor_role: str = Field(..., min_length=1)
    procedure: dict[str, Any] = Field(
        ..., description="The generated DRAFT procedure dict to promote.",
    )


@router.post("/generate")
def generate_procedure(req: GenerateRequest) -> dict[str, Any]:
    """Generate a procedure via the corresponding factory.

    Returns the procedure JSON with HTTP 200. HTTP 400 on a bad request
    (unknown asset_id, or a missing anomaly_profile for an EOP).
    """
    try:
        proc = compile_procedure(
            req.asset_id,
            req.procedure_class,
            anomaly_profile=req.anomaly_profile,
            author_role=req.actor_role or "TECH_L4",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log.info("[procedure_routes] generated %s for %s",
             req.procedure_class, req.asset_id)
    return proc


@router.post("/{procedure_id}/activate")
def activate_procedure(procedure_id: str, req: ActivateRequest) -> dict[str, Any]:
    """RBAC-gated DRAFT -> ACTIVE promotion.

    HTTP 403 if the actor role is insufficient (a TECH_L4 cannot promote);
    HTTP 400 on an invalid state transition or a path/body id mismatch.
    """
    body_id = req.procedure.get("procedure_id")
    if body_id and body_id != procedure_id:
        raise HTTPException(
            status_code=400,
            detail=f"path procedure_id {procedure_id!r} does not match body {body_id!r}",
        )
    try:
        promoted = promote_procedure(req.procedure, req.actor_role)
    except RBACDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log.info("[procedure_routes] %s promoted to ACTIVE by %s",
             procedure_id, req.actor_role)
    return promoted


# ════════════════════════════════════════════════════════════════════
# Epic 6 — Procedure Architect (LLM-narrative + Safety Officer audit)
# ════════════════════════════════════════════════════════════════════
#
# Naming note: the spec asked for ``POST /api/procedures/generate``,
# but that path was already taken by the G5 deterministic factory
# above. To avoid breaking the existing route + its 14 tests, the
# Architect's narrative-generation endpoint lives at
# ``POST /api/procedures/architect/generate``. Same prefix, distinct
# sub-path. The two endpoints are functionally orthogonal — one
# compiles asset-graph-derived skeletons (no LLM), the other
# narrates per-template documents (LLM-driven). Operators choose
# which they need.

class ArchitectGenerateRequest(BaseModel):
    """Body for POST /api/procedures/architect/generate (Epic 6)."""

    doc_type: str = Field(
        ...,
        pattern="^(SOP|MOP|EOP|EMP)$",
        description="Procedure template to apply.",
    )
    context: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description=(
            "Free-form operator request describing the maintenance / "
            "operation / incident being documented. Becomes the "
            "CONTEXT field of the hermetic Architect prompt."
        ),
    )
    asset_id: str | None = Field(
        default=None,
        max_length=128,
        description="Optional canonical asset id this procedure targets.",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional LIVE OPERATING METADATA the operator pulled in "
            "from /api/telemetry — typically {pue, load_kw, criticality, "
            "battery_runtime_min, ...}. The Architect surfaces it as a "
            "labelled block in the hermetic prompt so the LLM grounds "
            "the document in current state rather than a static baseline. "
            "Persisted on the returned draft so the ledger entry can "
            "audit which snapshot informed the document."
        ),
    )


class ArchitectSignRequest(BaseModel):
    """Body for POST /api/procedures/architect/sign (Epic 6)."""

    draft_id: str = Field(..., min_length=1, max_length=128)
    doc_type: str = Field(..., pattern="^(SOP|MOP|EOP|EMP)$")
    content: str = Field(..., min_length=1, max_length=64_000)
    asset_id: str | None = Field(default=None, max_length=128)
    operator_id: str = Field(..., min_length=1, max_length=128)
    actor_role: str | None = Field(
        default=None,
        description="Operator role claim (mock until auth is wired).",
    )


def _get_architect_agent(request: Request) -> ProcedureArchitectAgent:
    """Pull the Architect agent off ``app.state``. Lazily constructs
    one when absent so the route works even without explicit wiring
    from main.py — the agent gracefully degrades to a deterministic
    skeleton when no llm_client is attached."""
    agent = getattr(request.app.state, "procedure_architect_agent", None)
    if agent is None:
        llm_client = getattr(request.app.state, "llm_client", None)
        model_router = getattr(request.app.state, "model_router", None)
        agent = ProcedureArchitectAgent(
            llm_client=llm_client, model_router=model_router,
        )
        request.app.state.procedure_architect_agent = agent
    return agent


@router.post("/architect/generate")
async def architect_generate(
    req: ArchitectGenerateRequest, request: Request,
) -> dict[str, Any]:
    """Epic 6 — Procedure Architect generation + Safety Officer audit.

    Pipeline:
      1. Build a hermetic Gemma prompt (H17) carrying the exact Epic 6
         system prompt + the operator's context + doc_type selector.
      2. The Architect renders a markdown document
         (deterministic skeleton if no LLM is wired).
      3. ``audit_procedure_safety()`` scans the result. A MOP missing
         LOTO / PPE / CSA Z462 callouts emits ``hard_stop``.
      4. Response carries BOTH the draft AND the audit verdict — the
         HMI uses the verdict to gate the Sign button.

    Even ``hard_stop`` drafts are returned (HTTP 200) so the operator
    can see WHY the Safety Officer refused — that signal drives the
    Architect to re-prompt with the missing terms. A 4xx would lose
    the diagnostic findings.
    """
    agent = _get_architect_agent(request)
    draft = await agent.generate(
        doc_type=req.doc_type,
        context=req.context,
        asset_id=req.asset_id,
        metadata=req.metadata,
    )
    audit = audit_procedure_safety(draft)
    log.info(
        "[procedure_routes] architect generated %s (draft=%s, "
        "audit=%s, llm=%s)",
        draft.doc_type, draft.draft_id, audit.verdict, draft.llm_present,
    )
    return {
        "draft": draft.to_dict(),
        "safety_audit": audit.to_dict(),
    }


@router.post("/architect/sign")
async def architect_sign(
    req: ArchitectSignRequest, request: Request,
) -> dict[str, Any]:
    """Epic 6 — operator signs an approved draft into the forensic ledger.

    Re-runs the audit server-side (defence in depth — a hostile HMI
    cannot forge an approved verdict). When the audit re-emits
    ``hard_stop``, the sign is refused with HTTP 403 (the operator
    cannot sign an unsafe procedure even by mistake).

    On success: appends a ``PROCEDURE_SIGNED`` action to the
    forensic ledger with the content sha256, operator_id, doc_type,
    and draft_id — the chain link that proves *this* operator
    approved *this* exact content at *this* time. Returns the ledger
    entry summary (entry_id + sequence_no + ts).
    """
    # Reconstruct a ProcedureDraft so the audit runs against the SAME
    # surface the HMI already saw — never trust client-supplied
    # verdicts.
    draft = ProcedureDraft(
        draft_id=req.draft_id,
        doc_type=req.doc_type,
        context="(replayed from sign request)",
        content=req.content,
        asset_id=req.asset_id,
        generated_at=0.0,
        llm_present=False,
    )
    audit = audit_procedure_safety(draft)
    if audit.is_blocking:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Safety Officer HARD_STOP on draft {req.draft_id!r}: "
                f"{'; '.join(audit.findings)}"
            ),
        )

    ledger = getattr(request.app.state, "forensic_ledger", None)
    if ledger is None:
        raise HTTPException(
            status_code=503,
            detail="ForensicLedger not initialised — cannot sign.",
        )

    content_sha = hashlib.sha256(req.content.encode("utf-8")).hexdigest()

    # Epic 6 Sprint 3 Phase 4 — Maker-Checker witness gate on MOPs.
    # Tier IV practice: a Method of Procedure cannot be signed by a
    # single operator. The first signer is the maker; a second
    # operator must validate (the checker). Both signatures land in
    # the same PROCEDURE_SIGNED ledger entry so the chain-of-custody
    # is a single auditable row, not two.
    if req.doc_type == DOC_TYPE_MOP:
        return await _process_mop_signature(
            req, content_sha, audit, ledger,
        )

    # SOP / EOP / EMP — single signature is sufficient.
    entry = await ledger.append(
        actor=req.operator_id,
        action="PROCEDURE_SIGNED",
        payload={
            "draft_id": req.draft_id,
            "doc_type": req.doc_type,
            "asset_id": req.asset_id,
            "actor_role": req.actor_role or "operator",
            "content_sha256": content_sha,
            "content_length": len(req.content),
            "safety_audit_verdict": audit.verdict,
            "witness_required": False,
        },
    )
    log.info(
        "[procedure_routes] architect draft %s signed by %s "
        "(ledger entry %s, seq=%s)",
        req.draft_id, req.operator_id, entry.entry_id, entry.sequence_no,
    )
    # Silence ruff for the unused-import noise during static analysis —
    # the doc-type constants are exported here for downstream callers.
    _ = (DOC_TYPE_SOP, DOC_TYPE_EOP, DOC_TYPE_EMP, asyncio)
    return {
        "signed": True,
        "draft_id": req.draft_id,
        "entry_id": entry.entry_id,
        "sequence_no": entry.sequence_no,
        "ts": entry.ts,
        "content_sha256": content_sha,
        "safety_audit_verdict": audit.verdict,
        "witness_required": False,
    }


# ─── Architect library store (in-memory) ─────────────────────────────
# Append-only list of approved + signed Architect drafts that the
# operator chose to save to the corpus library. Mirrors the pending
# MOP signature store pattern: in-memory only for now (rebuilds
# fresh on restart); a DB-backed library is queued. The library
# endpoint is what closes the Epic 6 Option A consolidation loop --
# the MOPs view (post-cleanup) renders BOTH the static corpus AND
# the Architect-signed drafts via a future merge fetch.
_architect_library: list[dict[str, Any]] = []


def _reset_architect_library_for_test() -> None:
    """Test helper -- isolates each test from prior library state."""
    _architect_library.clear()


# ─── Commit 5 -- pre-seed library from docs/operaciones/mops/MOP-*.md ─
# Called from the FastAPI lifespan at boot. Each seed entry carries
# `source: "catalog"` so the library endpoint can filter them out from
# operator-signed drafts (`source: "signed"`). Audit gate is applied to
# every seed body -- a seed that fails audit is logged + skipped, never
# silently accepted (defence in depth: a future PR that breaks a seed
# body must surface the failure in boot logs).
def _seed_architect_library_from_catalog(
    catalog_dir: Path | None = None,
) -> int:
    """Parse every `MOP-*.md` under the catalog dir and append it to the
    Architect library with `source: "catalog"`. Returns the number of
    entries seeded. Idempotency is the caller's job; this helper does
    not de-duplicate -- the lifespan calls it exactly once at startup.

    Each seed entry exposes a `category` tag inferred from the third
    segment of the filename (`MOP-001-ups-bypass-transfer.md` -> `ups`).
    Operators can filter the library view by category in a later HMI
    surface; the tag is also useful for the GraphRAG cross-reference.
    """
    catalog_dir = catalog_dir or (
        Path(__file__).resolve().parent.parent
        / "docs" / "operaciones" / "mops"
    )
    if not catalog_dir.is_dir():
        log.warning(
            "[procedure_routes] catalog dir not found, skipping seed: %s",
            catalog_dir,
        )
        return 0

    count = 0
    for mop_file in sorted(catalog_dir.glob("MOP-*.md")):
        try:
            content = mop_file.read_text(encoding="utf-8")
        except OSError as e:
            log.warning(
                "[procedure_routes] could not read catalog seed %s: %s",
                mop_file.name, e,
            )
            continue

        draft = ProcedureDraft(
            draft_id=f"seed-{mop_file.stem}",
            doc_type="MOP",
            context=f"Pre-seeded from catalog ({mop_file.name})",
            content=content,
            asset_id=None,
            generated_at=time.time(),
            llm_present=False,
        )
        audit = audit_procedure_safety(draft)
        if audit.is_blocking:
            log.warning(
                "[procedure_routes] catalog seed %s failed audit "
                "(skipped): %s",
                mop_file.name, audit.findings[:2],
            )
            continue

        # Filename convention: `MOP-<NNN>-<category>-<rest>.md` --
        # third dash-segment is the canonical category tag (ups,
        # transformer, ats, ...). Fallback to "unknown" for files that
        # do not follow the convention.
        stem_parts = mop_file.stem.split("-")
        category = stem_parts[2] if len(stem_parts) >= 3 else "unknown"

        first_h1 = next(
            (
                line.strip()[2:].strip()
                for line in content.splitlines()
                if line.startswith("# ")
            ),
            mop_file.stem,
        )

        content_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        entry = {
            "library_id": str(uuid.uuid4()),
            "draft_id": f"seed-{mop_file.stem}",
            "doc_type": "MOP",
            "asset_id": None,
            "title": first_h1,
            "content": content,
            "content_sha256": content_sha,
            "operator_id": "catalog",
            "actor_role": "system",
            "ledger_entry_id": None,
            "audit_verdict": audit.verdict,
            "saved_at": time.time(),
            "source": "catalog",
            "category": category,
            "source_file": mop_file.name,
        }
        _architect_library.append(entry)
        count += 1
        log.info(
            "[procedure_routes] catalog seed -> library: %s "
            "(category=%s, audit=%s)",
            mop_file.name, category, audit.verdict,
        )

    log.info(
        "[procedure_routes] catalog pre-seed complete -- %d MOP(s) in library",
        count,
    )
    return count


class ArchitectSaveToLibraryRequest(BaseModel):
    """Body for POST /api/procedures/architect/save-to-library.

    Same shape as ArchitectSignRequest with the addition of the
    ledger ``entry_id`` returned by /sign -- ties the library entry
    to its sealed ledger record so the audit trail spans both
    surfaces. The server re-audits content (defence in depth) and
    refuses ``hard_stop`` material from landing in the library."""

    draft_id: str = Field(..., min_length=1, max_length=128)
    doc_type: str = Field(..., pattern="^(SOP|MOP|EOP|EMP)$")
    content: str = Field(..., min_length=1, max_length=64_000)
    asset_id: str | None = Field(default=None, max_length=128)
    operator_id: str = Field(..., min_length=1, max_length=128)
    actor_role: str | None = Field(default=None, max_length=64)
    ledger_entry_id: str | None = Field(
        default=None, max_length=128,
        description="The /sign response's entry_id -- ties library "
                    "row to ledger row.",
    )
    title: str | None = Field(
        default=None, max_length=256,
        description="Operator-supplied display title for the library "
                    "card. Defaults to a doc_type + asset_id derived "
                    "string when absent.",
    )


@router.post("/architect/save-to-library")
async def architect_save_to_library(
    req: ArchitectSaveToLibraryRequest,
) -> dict[str, Any]:
    """Epic 6 Option A consolidation -- pin an approved + signed
    Architect draft into the corpus library so operators can recall
    it the next time the same maneuver comes up.

    Re-audits content before accepting (defence in depth -- a hostile
    HMI cannot stash an unsafe MOP in the library by skipping the
    audit gate). ``hard_stop`` content is refused with HTTP 403.
    """
    draft = ProcedureDraft(
        draft_id=req.draft_id,
        doc_type=req.doc_type,
        context="(replayed from save-to-library request)",
        content=req.content,
        asset_id=req.asset_id,
        generated_at=0.0,
        llm_present=False,
    )
    audit = audit_procedure_safety(draft)
    if audit.is_blocking:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Cannot save hard_stop content to the library: "
                f"{'; '.join(audit.findings)}"
            ),
        )

    content_sha = hashlib.sha256(req.content.encode("utf-8")).hexdigest()
    title = req.title or f"{req.doc_type} — {req.asset_id or 'site-wide'} ({req.draft_id[:8]})"
    entry = {
        "library_id": str(uuid.uuid4()),
        "draft_id": req.draft_id,
        "doc_type": req.doc_type,
        "asset_id": req.asset_id,
        "title": title,
        "content": req.content,
        "content_sha256": content_sha,
        "operator_id": req.operator_id,
        "actor_role": req.actor_role or "operator",
        "ledger_entry_id": req.ledger_entry_id,
        "audit_verdict": audit.verdict,
        "saved_at": time.time(),
        # Commit 5 -- distinguishes operator-signed drafts from
        # pre-seeded catalog entries on the library endpoint filter.
        "source": "signed",
        "category": None,
    }
    _architect_library.append(entry)
    log.info(
        "[procedure_routes] architect draft %s saved to library by %s "
        "(library_id=%s, ledger_entry=%s)",
        req.draft_id, req.operator_id,
        entry["library_id"], req.ledger_entry_id,
    )
    return {
        "saved": True,
        "library_id": entry["library_id"],
        "draft_id": req.draft_id,
        "title": title,
        "content_sha256": content_sha,
        "audit_verdict": audit.verdict,
        "library_size": len(_architect_library),
    }


@router.get("/architect/library")
async def architect_list_library(
    limit: int = 50,
    source: str | None = None,
) -> dict[str, Any]:
    """List the most recent ``limit`` Architect library entries
    (newest first).

    Optional ``source`` filter (Commit 5):
      - ``catalog`` -- only pre-seeded MOPs from
        ``docs/operaciones/mops/MOP-*.md``.
      - ``signed``  -- only operator-signed + saved-to-library drafts.
      - ``None``     -- everything (default; merged view).

    The MOPs library view (post-Option-A cleanup) merges these
    alongside the static corpus.
    """
    limit = max(1, min(int(limit), 500))
    items_all = list(reversed(_architect_library))
    if source:
        items_all = [it for it in items_all if it.get("source") == source]
    items = items_all[:limit]
    return {
        "items": items,
        "total": len(items_all),
        "source_filter": source,
    }


# ─── Maker-Checker witness store (in-memory) ─────────────────────────
# Module-level dict keyed by draft_id; tracks the first ("maker")
# signature awaiting a second ("checker") sign. The store is rebuilt
# fresh on every process restart -- DB persistence is queued (it
# would integrate with the existing backend/witness_engine.py 8-state
# machine). For Epic 6 Sprint 3 the in-memory store is enough: a
# crash-mid-witness means the operator re-signs the draft, which is
# the safe failure mode anyway.
_pending_mop_signatures: dict[str, dict[str, Any]] = {}


def _reset_pending_mop_signatures_for_test() -> None:
    """Test helper -- isolates each test from pending state."""
    _pending_mop_signatures.clear()


async def _process_mop_signature(
    req: ArchitectSignRequest,
    content_sha: str,
    audit: Any,
    ledger: Any,
) -> dict[str, Any]:
    """Maker-Checker flow for MOP drafts.

    First sign: stores the pending maker signature, returns HTTP 202
    + ``status: awaiting_second_signature`` so the HMI can show a
    waiting badge. No ledger entry yet.

    Second sign: validates that
      (a) the draft_id has a pending first signature,
      (b) the content sha matches (no content drift between signs --
          would let the checker rubber-stamp a different document),
      (c) the second operator_id differs from the first (Tier IV
          practice -- self-witness defeats the purpose).
    Then appends a single PROCEDURE_SIGNED ledger entry carrying
    both signers in the payload, removes the pending entry, and
    returns the entry summary.
    """
    pending = _pending_mop_signatures.get(req.draft_id)

    if pending is None:
        # First signature -- record + wait.
        _pending_mop_signatures[req.draft_id] = {
            "first_signer": req.operator_id,
            "first_signer_role": req.actor_role or "operator",
            "content_sha256": content_sha,
            "asset_id": req.asset_id,
            "ts": time.time(),
        }
        log.info(
            "[procedure_routes] MOP draft %s first sign by %s -- "
            "awaiting second signature",
            req.draft_id, req.operator_id,
        )
        return JSONResponse(
            status_code=202,
            content={
                "signed": False,
                "draft_id": req.draft_id,
                "status": "awaiting_second_signature",
                "first_signer": req.operator_id,
                "first_signer_role": req.actor_role or "operator",
                "content_sha256": content_sha,
                "doc_type": "MOP",
                "witness_required": True,
                "message": (
                    "Maker-Checker gate: a MOP cannot ship on a single "
                    "signature. A second operator (different from the "
                    "first signer) must sign the same content to seal "
                    "the ledger entry."
                ),
            },
        )

    # Second signature path -- validate the witness contract.
    if pending["content_sha256"] != content_sha:
        raise HTTPException(
            status_code=409,
            detail=(
                f"MOP content drift between first + second signature on "
                f"draft {req.draft_id!r}: first signer "
                f"{pending['first_signer']} signed sha "
                f"{pending['content_sha256'][:12]}…, second signer "
                f"{req.operator_id} attempted sha {content_sha[:12]}…. "
                "Regenerate the draft and sign the matching content."
            ),
        )
    if pending["first_signer"] == req.operator_id:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Maker-Checker violation on draft {req.draft_id!r}: "
                f"operator {req.operator_id} attempted both signatures. "
                "A MOP requires two DIFFERENT operators (Tier IV "
                "self-witness ban)."
            ),
        )

    # Both signatures valid -- land the entry + clear pending.
    entry = await ledger.append(
        actor=req.operator_id,   # the checker is the actor of record
        action="PROCEDURE_SIGNED",
        payload={
            "draft_id": req.draft_id,
            "doc_type": "MOP",
            "asset_id": req.asset_id,
            "content_sha256": content_sha,
            "content_length": len(req.content),
            "safety_audit_verdict": audit.verdict,
            "witness_required": True,
            "first_signer": pending["first_signer"],
            "first_signer_role": pending["first_signer_role"],
            "first_signer_ts": pending["ts"],
            "second_signer": req.operator_id,
            "second_signer_role": req.actor_role or "operator",
        },
    )
    _pending_mop_signatures.pop(req.draft_id, None)
    log.info(
        "[procedure_routes] MOP draft %s SEALED (maker=%s, checker=%s, "
        "ledger entry %s, seq=%s)",
        req.draft_id, pending["first_signer"], req.operator_id,
        entry.entry_id, entry.sequence_no,
    )
    return {
        "signed": True,
        "draft_id": req.draft_id,
        "entry_id": entry.entry_id,
        "sequence_no": entry.sequence_no,
        "ts": entry.ts,
        "content_sha256": content_sha,
        "safety_audit_verdict": audit.verdict,
        "witness_required": True,
        "first_signer": pending["first_signer"],
        "second_signer": req.operator_id,
    }
