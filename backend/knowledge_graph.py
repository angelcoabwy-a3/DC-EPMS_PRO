"""
backend/knowledge_graph.py - Sprint S2 (rev 2)

Builds a NetworkX MultiDiGraph that fuses:
  1. The site model (components, locations, power chains, cooling chains)
     accessed via SiteModel public API:
       - list_components() -> list[ComponentInfo]
       - power_chain_for(id) -> dict (representative_path)
       - cooling_chain_for(id) if present
  2. KnowledgeNodes parsed from config/knowledge/*.md frontmatter.

Edge types in the graph:
  - feeds_power_to       (component -> component)
  - cools                (component -> component)
  - located_in           (component -> location_node)
  - applies_to_type      (knowledge_node -> type_marker_node)
  - is_a                 (component -> type_marker_node)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import networkx as nx

log = logging.getLogger(__name__)


@dataclass
class KnowledgeNode:
    """A single knowledge document (one markdown file)."""

    id: str
    title: str
    source: str
    source_type: str
    applies_to: list[str]
    tags: list[str]
    jurisdiction: str
    version: str
    voltage_class: str
    file_path: str
    body_text: str  # full markdown body (sans frontmatter)


def _location_node_id(loc: Any, level: str) -> str | None:
    """Build a unique node id for the location at the given level."""
    if loc is None:
        return None
    if level == "site":
        return f"loc:site:{loc.site_id}" if loc.site_id else None
    if level == "building":
        return f"loc:bldg:{loc.building_id}" if loc.building_id else None
    if level == "room":
        return f"loc:room:{loc.room_id}" if loc.room_id else None
    if level == "row":
        return f"loc:row:{loc.row_id}" if loc.row_id else None
    return None


def _add_location_chain(g: nx.MultiDiGraph, loc: Any) -> str | None:
    """Add site/building/room/row nodes for a Location and return the
    deepest one (so component can be linked to it).
    """
    if loc is None:
        return None
    deepest: str | None = None
    nodes_to_add = [
        ("site", loc.site_id, getattr(loc, "site_display", "")),
        ("building", loc.building_id, getattr(loc, "building_display", "")),
        ("room", loc.room_id, getattr(loc, "room_display", "")),
        ("row", loc.row_id, getattr(loc, "row_display", "")),
    ]
    for level, ident, display in nodes_to_add:
        if not ident:
            continue
        nid = _location_node_id(loc, level)
        if nid is None:
            continue
        if nid not in g:
            g.add_node(
                nid,
                kind="location",
                level=level,
                display=display or ident,
                identifier=ident,
            )
        deepest = nid
    return deepest


def build_knowledge_graph(
    site_model_obj: Any,
    knowledge_docs: list[KnowledgeNode],
) -> nx.MultiDiGraph:
    """Construct the unified graph using SiteModel public API only."""
    g = nx.MultiDiGraph()

    # ── Add component nodes + their location chains ──
    components = site_model_obj.list_components()
    for comp in components:
        cid = comp.canonical_id
        g.add_node(
            cid,
            kind="component",
            display=comp.display,
            type=comp.type,
            metadata=comp.metadata or {},
            location_path=_format_location_path(comp.location) if comp.location else None,
        )
        deepest_loc = _add_location_chain(g, comp.location)
        if deepest_loc:
            g.add_edge(cid, deepest_loc, key=f"loc:{cid}", relation="located_in")

    # ── Add power feed edges from power_chain_for ──
    # Only racks have multiple feeds; we walk each chain and add consecutive
    # edges. Deduplicate by (src, dst, group).
    power_edges_added: set[tuple[str, str, str]] = set()
    for comp in components:
        try:
            chain = site_model_obj.power_chain_for(comp.canonical_id)
        except Exception:
            continue
        for feed in chain.get("feeds", []) or []:
            group = feed.get("group", "unknown")
            path = feed.get("representative_path", []) or []
            for i in range(len(path) - 1):
                src, dst = path[i], path[i + 1]
                if src not in g or dst not in g:
                    continue
                key = (src, dst, group)
                if key in power_edges_added:
                    continue
                power_edges_added.add(key)
                g.add_edge(
                    src,
                    dst,
                    key=f"power:{group}:{src}:{dst}",
                    relation="feeds_power_to",
                    group=group,
                )

    # ── Add cooling edges if cooling_chain_for is available ──
    cooling_edges_added: set[tuple[str, str]] = set()
    if hasattr(site_model_obj, "cooling_chain_for"):
        for comp in components:
            try:
                chain = site_model_obj.cooling_chain_for(comp.canonical_id)
            except Exception:
                continue
            if not isinstance(chain, dict):
                continue
            # Various site_models may name the field differently; try both.
            paths = chain.get("paths") or chain.get("feeds") or []
            for path_obj in paths:
                pseq = path_obj.get("representative_path") if isinstance(path_obj, dict) else None
                if not pseq:
                    continue
                for i in range(len(pseq) - 1):
                    src, dst = pseq[i], pseq[i + 1]
                    if src not in g or dst not in g:
                        continue
                    if (src, dst) in cooling_edges_added:
                        continue
                    cooling_edges_added.add((src, dst))
                    g.add_edge(
                        src,
                        dst,
                        key=f"cool:{src}:{dst}",
                        relation="cools",
                    )

    # ── Add knowledge nodes ──
    for kn in knowledge_docs:
        g.add_node(
            kn.id,
            kind="knowledge",
            title=kn.title,
            source=kn.source,
            source_type=kn.source_type,
            jurisdiction=kn.jurisdiction,
            version=kn.version,
            voltage_class=kn.voltage_class,
            tags=kn.tags,
            applies_to=kn.applies_to,
            file_path=kn.file_path,
        )

    # ── Add applies_to_type edges and component_type marker nodes ──
    type_nodes_added: set[str] = set()
    for kn in knowledge_docs:
        for type_str in kn.applies_to:
            type_node = f"type:{type_str}"
            if type_node not in type_nodes_added:
                g.add_node(type_node, kind="component_type", type=type_str)
                type_nodes_added.add(type_node)
            g.add_edge(
                kn.id,
                type_node,
                key=f"applies:{kn.id}:{type_str}",
                relation="applies_to_type",
            )

    # ── Add component -> type_marker edges so we can join knowledge ──
    for comp in components:
        type_node = f"type:{comp.type}"
        if type_node in g:
            g.add_edge(
                comp.canonical_id,
                type_node,
                key=f"is_a:{comp.canonical_id}",
                relation="is_a",
            )

    log.info(
        "[knowledge_graph] built: %d nodes, %d edges (components=%d, locations=%d, knowledge=%d, types=%d)",
        g.number_of_nodes(),
        g.number_of_edges(),
        sum(1 for _, d in g.nodes(data=True) if d.get("kind") == "component"),
        sum(1 for _, d in g.nodes(data=True) if d.get("kind") == "location"),
        sum(1 for _, d in g.nodes(data=True) if d.get("kind") == "knowledge"),
        len(type_nodes_added),
    )
    return g


def _format_location_path(loc: Any) -> str:
    """Render a location as 'Site / Building / Room' (skipping empty levels)."""
    parts: list[str] = []
    for attr in ("site_display", "building_display", "room_display", "row_display"):
        val = getattr(loc, attr, None)
        if val:
            parts.append(val)
    return " / ".join(parts)


def get_upstream_chain(
    graph: nx.MultiDiGraph,
    component_id: str,
    relation: str = "feeds_power_to",
    max_hops: int = 10,
) -> list[str]:
    """BFS upstream over the given relation. Returns list of ancestor node ids."""
    if component_id not in graph:
        return []
    visited: list[str] = []
    seen: set[str] = set()
    frontier: list[tuple[str, int]] = [(component_id, 0)]
    while frontier:
        node, depth = frontier.pop(0)
        if node in seen or depth > max_hops:
            continue
        seen.add(node)
        if node != component_id:
            visited.append(node)
        for src, _, data in graph.in_edges(node, data=True):
            if data.get("relation") == relation and src not in seen:
                frontier.append((src, depth + 1))
    return visited


def get_applicable_knowledge(
    graph: nx.MultiDiGraph,
    component_id: str,
) -> list[dict]:
    """Find KnowledgeNodes that apply to the component via:
    component -[is_a]-> type:X <-[applies_to_type]- knowledge
    """
    if component_id not in graph:
        return []
    comp_data = graph.nodes[component_id]
    if comp_data.get("kind") != "component":
        return []
    type_str = comp_data.get("type")
    if not type_str:
        return []
    return get_knowledge_for_component_type(graph, type_str)


def get_knowledge_for_component_type(
    graph: nx.MultiDiGraph,
    type_str: str,
) -> list[dict]:
    type_node = f"type:{type_str}"
    if type_node not in graph:
        return []
    knowledge_nodes: list[dict] = []
    for src, _, data in graph.in_edges(type_node, data=True):
        if data.get("relation") == "applies_to_type":
            kn_data = graph.nodes[src]
            if kn_data.get("kind") == "knowledge":
                knowledge_nodes.append(
                    {
                        "id": src,
                        "title": kn_data.get("title"),
                        "source": kn_data.get("source"),
                        "source_type": kn_data.get("source_type"),
                        "jurisdiction": kn_data.get("jurisdiction"),
                        "version": kn_data.get("version"),
                        "voltage_class": kn_data.get("voltage_class"),
                        "tags": kn_data.get("tags", []),
                    }
                )
    return knowledge_nodes


def filter_by_jurisdiction(
    knowledge_list: list[dict],
    component_jurisdiction: str = "ontario_canada",
) -> list[dict]:
    """Filter knowledge nodes to those applicable in the given jurisdiction.

    Rules:
      - Always include 'international'.
      - Include 'canada' if component is in Canada.
      - Include 'ontario_canada' only if component is in Ontario.
    """
    keep: list[dict] = []
    for kn in knowledge_list:
        kj = kn.get("jurisdiction", "international")
        if (
            kj == "international"
            or kj == "canada"
            and "canada" in component_jurisdiction
            or kj == "ontario_canada"
            and component_jurisdiction == "ontario_canada"
        ):
            keep.append(kn)
    return keep
