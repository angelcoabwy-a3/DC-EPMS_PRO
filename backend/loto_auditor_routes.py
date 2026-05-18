"""
backend/loto_auditor_routes.py
================================
FastAPI router for LOTO Auditor Agent (Batch 4.D).

Exposes:
  - POST /api/loto/audit                 - Run audit, returns LotoAuditReport
  - GET /api/loto/audit/{audit_id}       - Fetch persisted audit (JSON)
  - GET /api/loto/audit/{audit_id}/markdown - Fetch as markdown text
  - GET /api/loto/audits/recent          - List recent audits

Wiring into main.py is via a 1-line call to register_loto_auditor():

    from backend.loto_auditor_routes import register_loto_auditor
    register_loto_auditor(
        app,
        site_model=site_model,
        graphrag_service=graphrag_service,
        physics_engine=physics_engine,
        witness_engine=witness_engine,
        repository=loto_audit_repo,  # PostgresLotoAuditRepository instance
    )

Per ADR-006 Deterministic Sandbox:
  - All audits return with status=pending_approval
  - No autonomous transitions
  - State changes (approved, rejected) deferred to V10 endpoint scope
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from loto_auditor_agent import (
    LotoAuditorAgent,
    LotoAuditorError,
    ProcedureNotFoundError,
    TargetComponentNotFoundError,
)
from loto_auditor_models import LotoAuditReport, LotoAuditRequest
from loto_auditor_report_renderer import render_audit_report_markdown
from loto_auditor_repository import (
    AuditNotFoundError,
    RepositoryError,
)

log = logging.getLogger(__name__)


# =============================================================================
#  Router
# =============================================================================

router = APIRouter(
    prefix="/api/loto",
    tags=["loto-auditor"],
)


# =============================================================================
#  Dependency injection helpers
# =============================================================================


def get_auditor(request: Request) -> LotoAuditorAgent:
    """Retrieve the LotoAuditorAgent instance from app.state.

    Raises 503 if not registered (caller forgot register_loto_auditor()).
    """
    auditor = getattr(request.app.state, "loto_auditor", None)
    if auditor is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "LOTO Auditor not registered. "
                "Call register_loto_auditor() in main.py lifespan startup."
            ),
        )
    return auditor


def get_repository(request: Request) -> Any:
    """Retrieve the repository from app.state.

    Returns None if not configured (audits will not be persisted).
    """
    return getattr(request.app.state, "loto_auditor_repo", None)


# =============================================================================
#  POST /api/loto/audit  - Run a new audit
# =============================================================================


@router.post(
    "/audit",
    response_model=LotoAuditReport,
    status_code=status.HTTP_200_OK,
    summary="Run a LOTO audit on a procedure + target component",
    description=(
        "Audits a LOTO procedure against a target equipment using 6 pillars. "
        "Returns a pending_approval report. Per ADR-006 Deterministic Sandbox, "
        "the report does not advance state autonomously - a CET must explicitly "
        "approve via separate endpoint (V10 scope)."
    ),
)
async def post_audit(
    body: LotoAuditRequest,
    auditor: LotoAuditorAgent = Depends(get_auditor),
    repo: Any = Depends(get_repository),
) -> LotoAuditReport:
    """Run audit + persist report."""
    from backend.rbac import require_actor_role
    require_actor_role(body.actor_role, 4, "running a LOTO audit")
    log.info(
        "POST /api/loto/audit procedure=%s target=%s cet=%s",
        body.procedure_id,
        body.target_component_id,
        body.cet_on_duty,
    )

    # Run audit (sync, deterministic logic)
    try:
        report = auditor.audit(body)
    except TargetComponentNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Target component not found: {e}",
        ) from e
    except ProcedureNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Procedure not found: {e}",
        ) from e
    except LotoAuditorError as e:
        log.exception("Auditor infrastructure error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Auditor infrastructure failure: {e}",
        ) from e

    # Persist if repository configured
    if repo is not None:
        try:
            await repo.save_async(report)
            log.debug("Persisted audit %s", report.audit_id)
        except RepositoryError as e:
            log.warning(
                "Failed to persist audit %s: %s. Returning report anyway.",
                report.audit_id,
                e,
            )
            # Don't fail the request just because persistence failed.
            # The audit verdict is still valid; CET can re-trigger to retry persist.
    else:
        log.debug(
            "No repository configured. Audit %s returned but not persisted.",
            report.audit_id,
        )

    return report


# =============================================================================
#  GET /api/loto/audit/{audit_id}  - Fetch persisted audit (JSON)
# =============================================================================


@router.get(
    "/audit/{audit_id}",
    response_model=LotoAuditReport,
    summary="Fetch a persisted LOTO audit by audit_id",
)
async def get_audit(
    audit_id: str,
    repo: Any = Depends(get_repository),
) -> LotoAuditReport:
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LOTO audit repository not configured",
        )

    try:
        return await repo.get_by_id_async(audit_id)
    except AuditNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except RepositoryError as e:
        log.exception("Repository query failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Repository unavailable: {e}",
        ) from e


# =============================================================================
#  GET /api/loto/audit/{audit_id}/markdown  - Fetch as markdown
# =============================================================================


@router.get(
    "/audit/{audit_id}/markdown",
    response_class=PlainTextResponse,
    summary="Fetch a LOTO audit rendered as markdown",
)
async def get_audit_markdown(
    audit_id: str,
    repo: Any = Depends(get_repository),
) -> str:
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LOTO audit repository not configured",
        )

    try:
        report = await repo.get_by_id_async(audit_id)
    except AuditNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except RepositoryError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Repository unavailable: {e}",
        ) from e

    return render_audit_report_markdown(report)


# =============================================================================
#  GET /api/loto/audits/recent  - List recent audits
# =============================================================================


@router.get(
    "/audits/recent",
    response_model=list[LotoAuditReport],
    summary="List most recent LOTO audits",
)
async def list_recent_audits(
    limit: int = 50,
    repo: Any = Depends(get_repository),
) -> list[LotoAuditReport]:
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LOTO audit repository not configured",
        )

    if limit < 1 or limit > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit must be between 1 and 200",
        )

    try:
        return await repo.list_recent_async(limit)
    except RepositoryError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Repository unavailable: {e}",
        ) from e


# =============================================================================
#  register_loto_auditor() - 1-line integration helper for main.py
# =============================================================================


def register_loto_auditor(
    app: FastAPI,
    *,
    site_model: Any,
    graphrag_service: Any,
    physics_engine: Any,
    witness_engine: Any,
    repository: Any | None = None,
    cmms_service: Any | None = None,
    procedures_dir: Any | None = None,
) -> LotoAuditorAgent:
    """Register the LOTO Auditor agent and route on a FastAPI app.

    Call once during lifespan startup. Idempotent: re-registering replaces
    the previous instance.

    Returns the LotoAuditorAgent instance for caller reference.

    Example:
        from backend.loto_auditor_routes import register_loto_auditor
        register_loto_auditor(
            app,
            site_model=site_model,
            graphrag_service=_s2_service,
            physics_engine=_physics_engine,
            witness_engine=_witness_engine,
            repository=loto_audit_repo,
        )
    """
    auditor_kwargs = dict(
        site_model=site_model,
        graphrag_service=graphrag_service,
        physics_engine=physics_engine,
        witness_engine=witness_engine,
    )
    if procedures_dir is not None:
        auditor_kwargs["procedures_dir"] = procedures_dir
    if cmms_service is not None:
        auditor_kwargs["cmms_service"] = cmms_service

    auditor = LotoAuditorAgent(**auditor_kwargs)
    app.state.loto_auditor = auditor
    app.state.loto_auditor_repo = repository

    # Idempotent router registration: if already included, FastAPI will not
    # complain about duplicate paths because we use the same router instance
    # check via a marker attribute.
    if not getattr(app.state, "_loto_router_registered", False):
        app.include_router(router)
        app.state._loto_router_registered = True

    log.info(
        "LOTO Auditor registered (repository=%s, cmms=%s)",
        "configured" if repository is not None else "absent",
        "configured" if cmms_service is not None else "absent",
    )
    return auditor


__all__ = [
    "get_auditor",
    "get_repository",
    "register_loto_auditor",
    "router",
]
