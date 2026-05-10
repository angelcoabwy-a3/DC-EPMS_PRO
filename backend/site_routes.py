"""
site_routes.py — HTTP endpoints for site model queries.

Sprint S1b. Mounts at /api/site under main.py.

Endpoints:
  GET  /api/site/metadata                — facility-level summary
  GET  /api/site/buildings               — top-level building list (HMI tree root)
  GET  /api/site/tree/{building_id}      — expandable sub-tree
  GET  /api/site/components              — paginated component list with filters
  GET  /api/site/components/{id}         — single component details
  GET  /api/site/locate/{id}             — location path + breadcrumb
  GET  /api/site/power-chain/{id}        — upstream feed analysis (2N proof)
  GET  /api/site/impact/{id}             — downstream impact (raw)
  GET  /api/site/loto-impact/{id}        — LOTO planning view (with redundancy)

All endpoints are read-only. The site_model is loaded once at startup
via get_site_model() and cached as a singleton.

Errors:
  404 if canonical_id not found
  500 if site_model failed to initialize (returns clear error message)
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from site_model import (
    ComponentNotFoundError,
    SiteModelError,
    get_site_model,
)

log = logging.getLogger(__name__)

# Module-level constant set at registration time by main.py
_PROJECT_ROOT: Path | None = None


def configure(project_root: Path) -> None:
    """Called by main.py during startup to point the router at the project."""
    global _PROJECT_ROOT
    _PROJECT_ROOT = project_root


def _model():
    """Lazy fetch the singleton; surface a clear error if not initialized."""
    if _PROJECT_ROOT is None:
        raise HTTPException(
            status_code=500,
            detail="site_model not configured (configure() not called)",
        )
    try:
        return get_site_model(_PROJECT_ROOT)
    except SiteModelError as e:
        log.exception("[site_routes] failed to load site model")
        raise HTTPException(status_code=500, detail=f"site model load failed: {e}")


router = APIRouter(prefix="/api/site", tags=["site"])


# ─────────────────────────────────────────────────────────────────────────
#  Metadata + tree navigation
# ─────────────────────────────────────────────────────────────────────────
@router.get("/metadata")
def get_metadata():
    """High-level facility info: name, classification, redundancy, capacity."""
    m = _model()
    return m.site_metadata()


@router.get("/buildings")
def list_buildings():
    """Top-level buildings — used by HMI sidebar tree as root nodes."""
    m = _model()
    return {"buildings": m.buildings_summary()}


@router.get("/tree/{building_id}")
def get_building_tree(building_id: str):
    """Expandable sub-tree for a building.

    Returns the full nested structure of the building including all rooms,
    rows, and rack canonical_ids. The HMI uses this to populate the tree
    when a building is expanded.
    """
    m = _model()
    raw = m._raw  # safe read-only access
    for b in raw.get("buildings", []) or []:
        if b.get("id") == building_id:
            # Strip any verbose fields not needed for tree rendering
            return {
                "id": b.get("id"),
                "display": b.get("display"),
                "type": b.get("type"),
                "description": b.get("description"),
                "rooms": [
                    {
                        "id": r.get("id"),
                        "display": r.get("display"),
                        "type": r.get("type"),
                        "description": r.get("description"),
                        "components": r.get("components", []) or [],
                        "rows": [
                            {
                                "id": row.get("id"),
                                "display": row.get("display"),
                                "rack_count": row.get("rack_count"),
                                "racks": row.get("racks", []) or [],
                            }
                            for row in (r.get("rows", []) or [])
                        ],
                    }
                    for r in (b.get("rooms", []) or [])
                ],
            }
    raise HTTPException(status_code=404, detail=f"building '{building_id}' not found")


# ─────────────────────────────────────────────────────────────────────────
#  Component queries
# ─────────────────────────────────────────────────────────────────────────
@router.get("/components")
def list_components(
    type: str | None = Query(None, description="Filter by type (chiller, ups, ats, ...)"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Paginated component list. Filter by type for HMI faceted browsing."""
    m = _model()
    all_comps = m.list_components(type_filter=type)
    total = len(all_comps)
    page = all_comps[offset : offset + limit]
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [c.to_dict() for c in page],
    }


@router.get("/components/{canonical_id}")
def get_component(canonical_id: str):
    """Single component details: type, location, vendor, ratings."""
    m = _model()
    try:
        comp = m.get_component(canonical_id)
    except ComponentNotFoundError:
        raise HTTPException(status_code=404, detail=f"component '{canonical_id}' not found")
    return comp.to_dict()


@router.get("/locate/{canonical_id}")
def locate(canonical_id: str):
    """Just the location for a component. Used by CMMS WO injection."""
    m = _model()
    try:
        loc = m.locate(canonical_id)
        comp = m.get_component(canonical_id)
    except ComponentNotFoundError:
        raise HTTPException(status_code=404, detail=f"component '{canonical_id}' not found")
    return {
        "canonical_id": canonical_id,
        "display": comp.display,
        "type": comp.type,
        "location": loc.to_dict(),
    }


# ─────────────────────────────────────────────────────────────────────────
#  Power / cooling / impact
# ─────────────────────────────────────────────────────────────────────────
@router.get("/graph")
def graph(chain: str = Query("all", pattern="^(power|cooling|all)$")):
    """All nodes + edges for the topology graph (force-directed view).

    Tier A / A1 — feeds frontend force-directed graph in
    view-site-topology. Lightweight payload: location reduced to a
    single human-readable path string; voltage/capacity stripped to
    keep the wire compact for ~91 nodes.

    Returns:
        {
            "nodes": [
                {
                    "id": "ups_a",
                    "display": "UPS A (...)",
                    "type": "ups",
                    "facility": "A3-Alpha Toronto Area",
                    "building_id": "building-a",
                    "room_type": "electrical_room",
                    "location_path": "A3-Alpha / Building A / Electrical Room A"
                }, ...
            ],
            "edges": [
                {"src": "switchgear_a", "dst": "ups_a", "chain": "power"}, ...
            ],
            "summary": {
                "node_count": 91,
                "power_edges": 44,
                "cooling_edges": 24,
                "by_type": {"it_rack": 50, "rpp": 4, ...}
            }
        }
    """
    m = _model()
    nodes = []
    by_type: dict[str, int] = {}
    for c in m.list_components():
        loc = c.location
        nodes.append({
            "id": c.canonical_id,
            "display": c.display,
            "type": c.type,
            "facility": "A3-Alpha Toronto Area",
            "building_id": getattr(loc, "building_id", None),
            "room_type": getattr(loc, "room_type", None),
            "location_path": getattr(loc, "path", ""),
        })
        by_type[c.type] = by_type.get(c.type, 0) + 1

    edges = []
    if chain in ("power", "all"):
        for src, dsts in m._power_downstream.items():
            for dst in dsts:
                edges.append({"src": src, "dst": dst, "chain": "power"})
    if chain in ("cooling", "all"):
        for src, dsts in m._cooling_downstream.items():
            for dst in dsts:
                edges.append({"src": src, "dst": dst, "chain": "cooling"})

    return {
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "node_count": len(nodes),
            "power_edges": sum(1 for e in edges if e["chain"] == "power"),
            "cooling_edges": sum(1 for e in edges if e["chain"] == "cooling"),
            "by_type": by_type,
        },
    }


@router.get("/power-chain/{canonical_id}")
def power_chain(canonical_id: str):
    """Upstream power feeds (Path A + Path B for 2N components).

    Operator query: 'where does power come from?'
    """
    m = _model()
    try:
        return m.power_chain_for(canonical_id)
    except ComponentNotFoundError:
        raise HTTPException(status_code=404, detail=f"component '{canonical_id}' not found")


@router.get("/impact/{canonical_id}")
def impact(
    canonical_id: str,
    chain: str = Query("power", pattern="^(power|cooling)$"),
):
    """Downstream impact set: what loses its feed if this fails?

    Does NOT account for redundancy — see /loto-impact for that.
    """
    m = _model()
    try:
        result = m.impact_set(canonical_id, chain=chain)
        return result.to_dict()
    except ComponentNotFoundError:
        raise HTTPException(status_code=404, detail=f"component '{canonical_id}' not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/loto-impact/{canonical_id}")
def loto_impact(canonical_id: str):
    """LOTO planning view: per-rack redundancy analysis.

    For each affected rack: total feed paths, paths still alive after
    LOTO, and a boolean 'still_has_redundancy'. The 'racks_losing_all_redundancy'
    list is the actionable outage risk.
    """
    m = _model()
    return m.loto_impact(canonical_id)
