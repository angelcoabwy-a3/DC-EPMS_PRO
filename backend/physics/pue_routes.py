"""
backend/physics/pue_routes.py
=============================
Sprint 5.5b — REST surface for PUE.

Endpoints:
  GET  /api/physics/pue           Both phases as a single snapshot pair
  GET  /api/physics/pue/{phase}   Single phase ("phase_1" | "phase_2")
  GET  /api/physics/pue/health    Probe + config summary

Per ADR-006: advisory output. Operator decisions remain CET-gated.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException

from backend.physics.pue import PUEConfig, compute_pue_both_phases, compute_pue_for_phase

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/physics", tags=["physics"])


@router.get("/pue/health")
async def pue_health() -> dict[str, Any]:
    try:
        cfg = PUEConfig.get()
    except RuntimeError:
        return {"status": "uninitialized"}
    return {
        "status": "up",
        "phases": {
            "phase_1": {
                "description": cfg.phase("phase_1")["description"],
                "target_pue": cfg.phase("phase_1")["target_pue"],
            },
            "phase_2": {
                "description": cfg.phase("phase_2")["description"],
                "target_pue": cfg.phase("phase_2")["target_pue"],
            },
        },
        "first_law_thresholds": cfg.first_law_thresholds,
    }


@router.get("/pue")
async def pue_both() -> dict[str, Any]:
    """Return a snapshot for Phase 1 (live) and Phase 2 (design target)."""
    try:
        cfg = PUEConfig.get()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="PUEConfig not initialized") from None
    snaps = compute_pue_both_phases(cfg)
    return {
        "phase_1": snaps["phase_1"].to_dict(),
        "phase_2": snaps["phase_2"].to_dict(),
    }


@router.get("/pue/{phase}")
async def pue_single(phase: str) -> dict[str, Any]:
    if phase not in ("phase_1", "phase_2"):
        raise HTTPException(status_code=400,
                            detail="phase must be 'phase_1' or 'phase_2'")
    try:
        cfg = PUEConfig.get()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="PUEConfig not initialized") from None
    is_design = (phase == "phase_2")
    snap = compute_pue_for_phase(phase, cfg, is_design_target=is_design)
    return snap.to_dict()


def register_pue_routes(app: FastAPI, project_root: Path) -> None:
    """Mount the PUE router and load config. Idempotent."""
    config_path = project_root / "config" / "pue_targets.yml"
    PUEConfig.load(config_path)
    if not getattr(app.state, "_pue_router_registered", False):
        app.include_router(router)
        app.state._pue_router_registered = True
    log.info("PUE routes registered: 3 endpoints under /api/physics")
