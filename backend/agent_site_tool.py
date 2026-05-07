"""
agent_site_tool.py — Site-aware agent tool for the Co-Pilot.

Sprint S1b. Adds a 4th tool to the agent's repertoire (alongside the
existing tools from v8.0/v8.1).

Tool: tool_query_site_model
  Operations:
    - locate           — return location path of a component
    - power_chain      — show 2N feeds for a component
    - loto_impact      — preview LOTO impact (with redundancy info)
    - search           — find components by name fragment

Disclosure discipline (v8.0.1): the tool returns FACTUAL data only.
It does not recommend actions. The agent's system prompt instructs
it to read the data and answer the user's question, not to draft
work orders or procedures unless the user explicitly asks.

Integration in agent_copilot.py:

    from agent_site_tool import tool_query_site_model, TOOL_DEFINITION

    TOOLS = [
        ...existing 4 tools (chat, draft_cmms, etc.)...,
        TOOL_DEFINITION,
    ]

    def dispatch(tool_name, args):
        if tool_name == "query_site_model":
            return tool_query_site_model(**args)
        ...
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


TOOL_DEFINITION = {
    "name": "query_site_model",
    "description": (
        "Query the A3-Alpha site model for component location, power chain "
        "(2N redundancy proof), or LOTO impact analysis. Use this when the "
        "user asks WHERE a component is, WHAT FEEDS a component, or WHAT "
        "IS AFFECTED if a component is taken offline. Returns factual data "
        "only — does not recommend or execute actions."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["locate", "power_chain", "loto_impact", "search"],
                "description": (
                    "locate: return location path of a component. "
                    "power_chain: show all upstream feeds (Path A + Path B). "
                    "loto_impact: preview LOTO impact with rack-level redundancy. "
                    "search: find components by name fragment."
                ),
            },
            "canonical_id": {
                "type": "string",
                "description": (
                    "Canonical component identifier (e.g. chiller_1, ups_a, "
                    "rack_a_01_05). Required for locate/power_chain/loto_impact. "
                    "Optional for search."
                ),
            },
            "search_query": {
                "type": "string",
                "description": "Substring to search for (used only with operation=search)",
            },
            "type_filter": {
                "type": "string",
                "description": "Filter search by component type (chiller, ups, ats, etc.)",
            },
        },
        "required": ["operation"],
    },
}


def tool_query_site_model(
    operation: str,
    canonical_id: Optional[str] = None,
    search_query: Optional[str] = None,
    type_filter: Optional[str] = None,
    project_root: Optional[Path] = None,
) -> dict:
    """Dispatch to the right site_model query.

    Returns a JSON-serializable dict. Errors are returned in the response
    (not raised) so the agent can read them and explain to the user.
    """
    try:
        from site_model import (
            get_site_model,
            ComponentNotFoundError,
            SiteModelError,
        )
    except ImportError as e:
        return {
            "success": False,
            "error": "site_model not available",
            "detail": str(e),
        }

    try:
        if project_root is None:
            project_root = Path(__file__).resolve().parent.parent
        model = get_site_model(project_root)
    except (RuntimeError, SiteModelError) as e:
        return {
            "success": False,
            "error": "site_model load failed",
            "detail": str(e),
        }

    if operation == "search":
        return _do_search(model, search_query, type_filter)

    if not canonical_id:
        return {
            "success": False,
            "error": "canonical_id is required for this operation",
            "operation": operation,
        }

    try:
        if operation == "locate":
            return _do_locate(model, canonical_id)
        elif operation == "power_chain":
            return _do_power_chain(model, canonical_id)
        elif operation == "loto_impact":
            return _do_loto_impact(model, canonical_id)
        else:
            return {
                "success": False,
                "error": f"unknown operation '{operation}'",
                "valid_operations": ["locate", "power_chain", "loto_impact", "search"],
            }
    except ComponentNotFoundError:
        return {
            "success": False,
            "error": f"component '{canonical_id}' not found in site model",
            "hint": "Try operation='search' with search_query to find similar IDs",
        }


def _do_locate(model, canonical_id: str) -> dict:
    comp = model.get_component(canonical_id)
    return {
        "success": True,
        "operation": "locate",
        "canonical_id": canonical_id,
        "asset_display": comp.display,
        "asset_type": comp.type,
        "location_path": comp.location.path,
        "location_breadcrumb": comp.location.path_components,
    }


def _do_power_chain(model, canonical_id: str) -> dict:
    chain = model.power_chain_for(canonical_id)
    comp = model.get_component(canonical_id)
    summary = {
        "feed_count": chain["feed_count"],
        "is_redundant": chain["feed_count"] >= 2,
        "feed_groups": [f["group"] for f in chain["feeds"]],
    }
    return {
        "success": True,
        "operation": "power_chain",
        "canonical_id": canonical_id,
        "asset_display": comp.display,
        "summary": summary,
        "feeds": chain["feeds"],
    }


def _do_loto_impact(model, canonical_id: str) -> dict:
    result = model.loto_impact(canonical_id)
    # Add a human-friendly summary at the top for the agent to read
    racks_safe = len(result["racks_affected"]) - len(result["racks_losing_all_redundancy"])
    if not result.get("location"):
        location_str = "(component not in hierarchy or unknown)"
    else:
        location_str = result["location"]["path"]

    summary = {
        "target_display": result["loto_target_display"],
        "target_location": location_str,
        "total_racks_affected": len(result["racks_affected"]),
        "racks_safe_via_redundancy": racks_safe,
        "racks_at_outage_risk": len(result["racks_losing_all_redundancy"]),
        "is_safe_loto": len(result["racks_losing_all_redundancy"]) == 0,
    }
    return {
        "success": True,
        "operation": "loto_impact",
        "canonical_id": canonical_id,
        "summary": summary,
        "detail": result,
    }


def _do_search(
    model,
    search_query: Optional[str],
    type_filter: Optional[str],
) -> dict:
    components = model.list_components(type_filter=type_filter)
    if search_query:
        q = search_query.lower()
        components = [
            c for c in components
            if q in c.canonical_id.lower() or q in c.display.lower()
        ]
    # Cap results
    max_results = 50
    truncated = len(components) > max_results
    components = components[:max_results]
    return {
        "success": True,
        "operation": "search",
        "query": search_query,
        "type_filter": type_filter,
        "count": len(components),
        "truncated": truncated,
        "results": [
            {
                "canonical_id": c.canonical_id,
                "display": c.display,
                "type": c.type,
                "location_path": c.location.path,
            }
            for c in components
        ],
    }


# Schema in the format expected by agent_copilot.TOOLS_SCHEMA
QUERY_SITE_MODEL_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": TOOL_DEFINITION["name"],
        "description": TOOL_DEFINITION["description"],
        "parameters": TOOL_DEFINITION["input_schema"],
    },
}