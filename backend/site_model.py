"""
site_model.py — Site hierarchy + power/cooling chain analysis.

Sprint S1a of the portfolio expansion. Cubre el gap identificado en
la entrevista de Microsoft CO+I: "how is the data center composed in
its specific locations?"

Loads config/site_model.yml and exposes a query interface that
answers operational questions like:

  - locate("rack_a_01_05") returns the full path:
      "A3-Alpha / Building A / Data Hall A / Row A-01"

  - power_chain_for("rack_a_01_05") returns BOTH paths (Path A and
    Path B) showing every component upstream that feeds power to it.

  - impact_set("busway_a_01") returns every component that loses ITS
    feed if the busway opens — answers the LOTO question.

  - loto_impact("rpp_a_01") goes further: for each rack downstream,
    reports whether it still has Path B redundancy after the LOTO.

This module does NOT change existing flat IDs. chiller_1 is still
chiller_1; bms_connector tags continue working unchanged. The site
model adds a *layer* on top, not a replacement.

Integration points (Sprint S1b):
  - cmms_mcp.draft_cmms_work_order: location injected into WO metadata
  - procedure_engine: MOPs can reference physical zones for safety
  - agent_copilot: HMI answers location queries from the agent

═══════════════════════════════════════════════════════════════════════
  HONEST scope notes:

  - Declarative model, hand-maintained. Sprint S2+ adds frontend tree
    explorer; future sprint could add IFC/BIM importer.

  - Read-only at runtime. Add/remove via YAML edit + reload.

  - Power chains are simple DAGs with explicit edges. No state-aware
    logic ("breaker open" → edge inactive). That's a future sprint.

  - Cooling chains are simplified. Real Tier IV facilities have
    valving and isolation that this model doesn't represent.
═══════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
#  Errors
# ─────────────────────────────────────────────────────────────────────────
class SiteModelError(RuntimeError):
    """Base class for site model errors."""


class ComponentNotFoundError(KeyError):
    """No component with the given canonical_id."""


class SiteModelLoadError(SiteModelError):
    """YAML failed to load or schema invalid."""


# ─────────────────────────────────────────────────────────────────────────
#  Data classes
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class Location:
    """A physical location in the site hierarchy.

    Path example: "A3-Alpha / Building A / Data Hall A / Row A-01"
    """

    site_id: str
    site_display: str
    building_id: str | None = None
    building_display: str | None = None
    room_id: str | None = None
    room_display: str | None = None
    room_type: str | None = None
    row_id: str | None = None
    row_display: str | None = None

    @property
    def path(self) -> str:
        parts = [self.site_display]
        if self.building_display:
            parts.append(self.building_display)
        if self.room_display:
            parts.append(self.room_display)
        if self.row_display:
            parts.append(self.row_display)
        return " / ".join(parts)

    @property
    def path_components(self) -> list[dict]:
        out = [{"id": self.site_id, "display": self.site_display, "level": "site"}]
        if self.building_id:
            out.append(
                {"id": self.building_id, "display": self.building_display, "level": "building"}
            )
        if self.room_id:
            out.append(
                {
                    "id": self.room_id,
                    "display": self.room_display,
                    "level": "room",
                    "type": self.room_type,
                }
            )
        if self.row_id:
            out.append({"id": self.row_id, "display": self.row_display, "level": "row"})
        return out

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "components": self.path_components,
            "site_id": self.site_id,
            "building_id": self.building_id,
            "room_id": self.room_id,
            "room_type": self.room_type,
            "row_id": self.row_id,
        }


@dataclass
class ComponentInfo:
    """Metadata about a single component (chiller_1, ups_a, etc.)."""

    canonical_id: str
    display: str
    type: str
    location: Location
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "canonical_id": self.canonical_id,
            "display": self.display,
            "type": self.type,
            "location": self.location.to_dict(),
            **self.metadata,
        }


@dataclass
class ImpactSet:
    """Result of impact_set() query."""

    failed_node: str
    chain_type: str
    immediate: list[str]
    transitive: list[str]
    by_type: dict[str, list[str]]

    def to_dict(self) -> dict:
        return {
            "failed_node": self.failed_node,
            "chain_type": self.chain_type,
            "immediate_count": len(self.immediate),
            "transitive_count": len(self.transitive),
            "immediate": self.immediate,
            "transitive": self.transitive,
            "by_type": self.by_type,
        }


# ─────────────────────────────────────────────────────────────────────────
#  Main SiteModel class
# ─────────────────────────────────────────────────────────────────────────
class SiteModel:
    """In-memory site model loaded from YAML.

    Indexes built at load time for O(1) queries:
      _location_by_id    canonical_id → Location
      _component_by_id   canonical_id → ComponentInfo
      _power_*           adjacency lists (forward + reverse)
      _cooling_*         adjacency lists (forward + reverse)
    """

    def __init__(self, yaml_path: Path):
        self.yaml_path = yaml_path
        self._raw: dict = {}
        self._site_id: str = ""
        self._site_display: str = ""
        self._location_by_id: dict[str, Location] = {}
        self._component_by_id: dict[str, ComponentInfo] = {}

        # Power chain DAG
        self._power_downstream: dict[str, list[str]] = defaultdict(list)
        self._power_upstream: dict[str, list[str]] = defaultdict(list)
        self._cooling_downstream: dict[str, list[str]] = defaultdict(list)
        self._cooling_upstream: dict[str, list[str]] = defaultdict(list)

    # ── Loading ───────────────────────────────────────────────────────
    def load(self) -> None:
        if not self.yaml_path.exists():
            raise SiteModelLoadError(f"site model YAML not found: {self.yaml_path}")

        try:
            with open(self.yaml_path, encoding="utf-8") as f:
                self._raw = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise SiteModelLoadError(f"YAML parse error: {e}") from e

        if not isinstance(self._raw, dict):
            raise SiteModelLoadError("YAML root must be a mapping")

        self._build_site_metadata()
        self._build_location_index()
        self._build_component_index()
        self._build_power_chains()
        self._build_cooling_chains()

        log.info(
            "[site_model] loaded: %d components, %d locations, " "%d power edges, %d cooling edges",
            len(self._component_by_id),
            len(self._location_by_id),
            sum(len(v) for v in self._power_downstream.values()),
            sum(len(v) for v in self._cooling_downstream.values()),
        )

    def _build_site_metadata(self) -> None:
        site = self._raw.get("site") or {}
        self._site_id = site.get("id", "unknown_site")
        self._site_display = site.get("display_path", site.get("name", self._site_id))

    def _build_location_index(self) -> None:
        for building in self._raw.get("buildings", []) or []:
            b_id = building.get("id", "")
            b_display = building.get("display", b_id)

            for room in building.get("rooms", []) or []:
                r_id = room.get("id", "")
                r_display = room.get("display", r_id)
                r_type = room.get("type", "")

                # Components directly in the room
                for comp_id in room.get("components", []) or []:
                    self._location_by_id[comp_id] = Location(
                        site_id=self._site_id,
                        site_display=self._site_display,
                        building_id=b_id,
                        building_display=b_display,
                        room_id=r_id,
                        room_display=r_display,
                        room_type=r_type,
                    )

                # Rows (data halls)
                for row in room.get("rows", []) or []:
                    rw_id = row.get("id", "")
                    rw_display = row.get("display", rw_id)
                    for rack_id in row.get("racks", []) or []:
                        self._location_by_id[rack_id] = Location(
                            site_id=self._site_id,
                            site_display=self._site_display,
                            building_id=b_id,
                            building_display=b_display,
                            room_id=r_id,
                            room_display=r_display,
                            room_type=r_type,
                            row_id=rw_id,
                            row_display=rw_display,
                        )

    def _build_component_index(self) -> None:
        components = self._raw.get("components", {}) or {}
        unlocated_count = 0

        for comp_id, meta in components.items():
            if not isinstance(meta, dict):
                log.warning("[site_model] component %s has non-dict metadata, skipping", comp_id)
                continue
            location = self._location_by_id.get(comp_id)
            if location is None:
                location = Location(site_id=self._site_id, site_display=self._site_display)
                unlocated_count += 1

            self._component_by_id[comp_id] = ComponentInfo(
                canonical_id=comp_id,
                display=meta.get("display", comp_id),
                type=meta.get("type", "unknown"),
                location=location,
                metadata={k: v for k, v in meta.items() if k not in ("display", "type")},
            )

        if unlocated_count:
            log.warning(
                "[site_model] %d components have no location in hierarchy",
                unlocated_count,
            )

    def _build_power_chains(self) -> None:
        for edge in self._raw.get("power_chains", []) or []:
            src = edge.get("from")
            dst = edge.get("to")
            if not src or not dst:
                continue
            self._power_downstream[src].append(dst)
            self._power_upstream[dst].append(src)

    def _build_cooling_chains(self) -> None:
        for edge in self._raw.get("cooling_chains", []) or []:
            src = edge.get("from")
            dst = edge.get("to")
            if not src or not dst:
                continue
            self._cooling_downstream[src].append(dst)
            self._cooling_upstream[dst].append(src)

    # ── Public query API ──────────────────────────────────────────────
    def site_metadata(self) -> dict:
        """High-level facility metadata."""
        return self._raw.get("site", {})

    def buildings_summary(self) -> list[dict]:
        """Lightweight building list for HMI tree top level."""
        return [
            {
                "id": b.get("id"),
                "display": b.get("display"),
                "type": b.get("type"),
                "room_count": len(b.get("rooms", []) or []),
            }
            for b in self._raw.get("buildings", []) or []
        ]

    def list_components(self, type_filter: str | None = None) -> list[ComponentInfo]:
        result = list(self._component_by_id.values())
        if type_filter:
            result = [c for c in result if c.type == type_filter]
        return result

    def get_component(self, canonical_id: str) -> ComponentInfo:
        if canonical_id not in self._component_by_id:
            raise ComponentNotFoundError(canonical_id)
        return self._component_by_id[canonical_id]

    def locate(self, canonical_id: str) -> Location:
        """Physical location of a component."""
        if canonical_id not in self._component_by_id:
            raise ComponentNotFoundError(canonical_id)
        return self._component_by_id[canonical_id].location

    def location_path(self, canonical_id: str) -> str:
        """Human-readable location string for HMI/CMMS injection."""
        return self.locate(canonical_id).path

    def power_chain_for(self, canonical_id: str) -> dict:
        """All power feeds upstream of a component.

        For a 2N facility, results are grouped by feed_group:
          'path_a': all paths that trace back through ats_a (utility OR gensets A)
          'path_b': all paths that trace back through ats_b
        Each group has its alternative roots (utility + gensets) but counts
        as ONE redundant path from the operator's perspective.

        Returns {
            'component': canonical_id,
            'feed_count': 2,           # number of distinct redundant paths
            'feeds': [
                {'group': 'path_a', 'roots': ['utility_feed_a','genset_a_01','genset_a_02'],
                 'representative_path': [...]},
                {'group': 'path_b', ...},
            ]
        }
        """
        if canonical_id not in self._component_by_id and canonical_id not in self._power_upstream:
            raise ComponentNotFoundError(canonical_id)

        paths_to_roots: list[list[str]] = []
        self._collect_paths_to_roots(
            canonical_id,
            self._power_upstream,
            [canonical_id],
            paths_to_roots,
        )

        # Group by feed_group: a path belongs to "path_a" if it contains ats_a,
        # "path_b" if it contains ats_b, "other" otherwise (e.g. fuel-only chains).
        groups: dict[str, dict] = {}
        for path in paths_to_roots:
            if "ats_a" in path:
                group_key = "path_a"
            elif "ats_b" in path:
                group_key = "path_b"
            else:
                # Could be fuel chain or other ancillary; identify by root
                group_key = f"other_{path[-1]}"

            if group_key not in groups:
                groups[group_key] = {
                    "group": group_key,
                    "roots": [],
                    "representative_path": list(reversed(path)),
                }
            root = path[-1]
            if root not in groups[group_key]["roots"]:
                groups[group_key]["roots"].append(root)

        feeds = list(groups.values())

        # Sort: path_a first, path_b second, others after
        feeds.sort(
            key=lambda f: (
                0 if f["group"] == "path_a" else 1 if f["group"] == "path_b" else 2,
                f["group"],
            )
        )

        return {
            "component": canonical_id,
            "feed_count": len(feeds),
            "feeds": feeds,
        }

    def _collect_paths_to_roots(
        self,
        node: str,
        edges: dict[str, list[str]],
        current_path: list[str],
        all_paths: list[list[str]],
        max_depth: int = 50,
    ) -> None:
        if len(current_path) > max_depth:
            return
        upstreams = edges.get(node, [])
        if not upstreams:
            all_paths.append(list(current_path))
            return
        for parent in upstreams:
            if parent in current_path:
                continue
            current_path.append(parent)
            self._collect_paths_to_roots(parent, edges, current_path, all_paths, max_depth)
            current_path.pop()

    def impact_set(self, canonical_id: str, chain: str = "power") -> ImpactSet:
        """All components that lose their feed if this node fails.

        Does NOT account for redundancy — returns full downstream set.
        Caller intersects with redundancy info to determine actual outage risk.
        """
        if chain == "power":
            edges = self._power_downstream
        elif chain == "cooling":
            edges = self._cooling_downstream
        else:
            raise ValueError(f"chain must be 'power' or 'cooling', got '{chain}'")

        immediate = list(edges.get(canonical_id, []))
        transitive_set: set[str] = set()
        queue = deque([canonical_id])
        while queue:
            node = queue.popleft()
            for child in edges.get(node, []):
                if child in transitive_set:
                    continue
                transitive_set.add(child)
                queue.append(child)

        by_type: dict[str, list[str]] = defaultdict(list)
        for comp_id in transitive_set:
            comp = self._component_by_id.get(comp_id)
            ctype = comp.type if comp else "unknown"
            by_type[ctype].append(comp_id)

        return ImpactSet(
            failed_node=canonical_id,
            chain_type=chain,
            immediate=immediate,
            transitive=sorted(transitive_set),
            by_type=dict(by_type),
        )

    def loto_impact(self, canonical_id: str) -> dict:
        """Higher-level LOTO impact analysis for HMI/CMMS.

        For a candidate LOTO target, returns:
          - location of the component
          - immediate downstream + transitive set
          - racks affected, with redundancy status of each
            ("still has Path B" vs "would lose all redundancy")

        This answers: "If I LOTO rpp_a_01, which racks lose Path A
        redundancy? Which still have Path B intact?"
        """
        try:
            comp = self.get_component(canonical_id)
        except ComponentNotFoundError:
            comp = None

        impact = self.impact_set(canonical_id, chain="power")

        # For each rack downstream, count remaining redundant feed groups
        # whose representative path does NOT contain the LOTO target.
        # In a 2N facility, a rack has 2 feed groups (path_a, path_b).
        # If the LOTO is on a Path A component, path_a is invalidated but
        # path_b survives, so the rack still has 1 remaining redundant path.
        rack_redundancy = []
        for rack_id in impact.by_type.get("it_rack", []):
            chain_info = self.power_chain_for(rack_id)
            feeds = chain_info["feeds"]
            still_redundant_feeds = [
                f for f in feeds if canonical_id not in f["representative_path"]
            ]
            rack_redundancy.append(
                {
                    "rack": rack_id,
                    "rack_display": (
                        self._component_by_id[rack_id].display
                        if rack_id in self._component_by_id
                        else rack_id
                    ),
                    "total_paths": len(feeds),
                    "remaining_paths": len(still_redundant_feeds),
                    "still_has_redundancy": len(still_redundant_feeds) >= 1,
                }
            )

        return {
            "loto_target": canonical_id,
            "loto_target_display": comp.display if comp else canonical_id,
            "location": comp.location.to_dict() if comp else None,
            "downstream_count": len(impact.transitive),
            "immediate": impact.immediate,
            "by_type": impact.by_type,
            "racks_affected": rack_redundancy,
            "racks_losing_all_redundancy": [
                r for r in rack_redundancy if not r["still_has_redundancy"]
            ],
            "_note": (
                "racks_losing_all_redundancy is the actionable risk: those "
                "racks would experience IT outage if this LOTO is performed "
                "without additional mitigation."
            ),
        }


# ─────────────────────────────────────────────────────────────────────────
#  Module-level singleton + factory
# ─────────────────────────────────────────────────────────────────────────
_global_model: SiteModel | None = None


def get_site_model(project_root: Path | None = None) -> SiteModel:
    """Lazy-loaded singleton."""
    global _global_model
    if _global_model is None:
        if project_root is None:
            raise RuntimeError("site model not initialized; first call must pass project_root")
        yaml_path = project_root / "config" / "site_model.yml"
        _global_model = SiteModel(yaml_path)
        _global_model.load()
    return _global_model


def reset_site_model() -> None:
    """Test helper — discard singleton so tests get fresh load."""
    global _global_model
    _global_model = None
