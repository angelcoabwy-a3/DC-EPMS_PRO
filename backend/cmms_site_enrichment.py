"""
cmms_site_enrichment.py — Site-aware CMMS Work Order metadata enrichment.

Sprint S1b. Designed to be imported by cmms_mcp.py without breaking the
existing v8.1 behavior.

Usage in cmms_mcp.py:

    from cmms_site_enrichment import enrich_wo_with_location

    def tool_draft_cmms_work_order(
        title: str,
        description: str,
        priority: str = "medium",
        target_component_id: Optional[str] = None,    # NEW optional param
        ...
    ) -> dict:
        draft = {
            "title": title,
            "description": description,
            "priority": priority,
            ...existing fields...
        }
        # Sprint S1b: inject location if target component is specified
        if target_component_id:
            draft = enrich_wo_with_location(draft, target_component_id)
        return draft

The enrichment is designed to FAIL SOFT: if site_model is not available
or the component is unknown, the WO draft is returned unchanged with a
warning logged. This preserves v8.1 behavior for callers that don't pass
target_component_id, AND for callers in environments where site_model.yml
hasn't been deployed yet.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def enrich_wo_with_location(
    wo_draft: dict,
    target_component_id: str,
    project_root: Path | None = None,  # type: ignore[name-defined]
) -> dict:
    """Add location and component metadata to a CMMS work order draft.

    Args:
        wo_draft: existing WO draft dict (will not be mutated; copy returned)
        target_component_id: canonical_id of the asset the WO targets
        project_root: optional override for site_model location

    Returns:
        Enriched copy of wo_draft with these extra fields added under
        a 'site_context' subkey:
          location           — human path "A3-Alpha / Building A / ..."
          location_breadcrumb — list of {id, display, level} for HMI
          asset_display      — friendly name from site_model
          asset_type         — chiller, ups, ats, ...
          asset_metadata     — vendor, model, ratings, etc.

        If site_model is unavailable or component not found, returns the
        original draft with site_context.error set to an explanation.
        Never raises.
    """
    enriched = dict(wo_draft)  # shallow copy to avoid mutation
    enriched["target_component_id"] = target_component_id

    try:
        # Lazy import: cmms_mcp may run in environments without site_model
        from site_model import (
            ComponentNotFoundError,
            SiteModelError,
            get_site_model,
        )
    except ImportError as e:
        log.warning("[cmms_site_enrichment] site_model module not importable: %s", e)
        enriched["site_context"] = {
            "available": False,
            "error": "site_model module not available",
        }
        return enriched

    try:
        # If the singleton was already initialized at app startup, this
        # returns it; otherwise we have to provide a project_root.
        if project_root is None:
            from pathlib import Path as _Path

            # Fallback: assume we're in <project>/backend/ and config is sibling
            project_root = _Path(__file__).resolve().parent.parent
        model = get_site_model(project_root)
    except (RuntimeError, SiteModelError) as e:
        log.warning(
            "[cmms_site_enrichment] could not load site_model: %s; "
            "WO draft will not include location",
            e,
        )
        enriched["site_context"] = {
            "available": False,
            "error": f"site_model load failed: {e}",
        }
        return enriched

    try:
        comp = model.get_component(target_component_id)
    except ComponentNotFoundError:
        log.info(
            "[cmms_site_enrichment] component '%s' not in site_model; "
            "WO draft will not include location",
            target_component_id,
        )
        enriched["site_context"] = {
            "available": False,
            "error": f"component '{target_component_id}' not found in site_model",
        }
        return enriched

    enriched["site_context"] = {
        "available": True,
        "location": comp.location.path,
        "location_breadcrumb": comp.location.path_components,
        "asset_display": comp.display,
        "asset_type": comp.type,
        "asset_metadata": comp.metadata,
    }
    return enriched
