"""
backend/site_roles.py -- DC-EPMS-068 lote B.

Resolve Phase 1 power components by ROLE instead of by literal id, so
the same backend code runs on the legacy site model (ups_a, ats_a,
xfmr_a, switchgear_a) and on site_model_v2 (ups_a_01..08, mvtc_a,
mv_xfmr_a, lv_swbd_a_NN). Pure functions over a loaded SiteModel; no
I/O, no globals.

Path membership ("a" / "b") comes from the component's ``path``
metadata when present (every v2 Phase 1 component carries it) and
otherwise from the id suffix (``ats_a``, ``ups_b``, ``rpp_a1``,
``genset_b_02``). Components that belong to neither path return None.

Roles:
  transfer      ats (legacy) | mv_transfer_controller (v2)
  ups           ups
  utility_xfmr  the transformer fed by the path's utility intake
                (legacy xfmr_a 27.5 kV/480 V, v2 mv_xfmr_a 27.5/13.8 kV)
"""

from __future__ import annotations

import re
from typing import Any

PATHS = ("a", "b")
TRANSFER_TYPES = ("ats", "mv_transfer_controller")

# ups_a, ats_b, xfmr_a, switchgear_b, rpp_a1, busway_b, ups_a_01,
# genset_b_02, unit_sub_a_03, lv_swbd_b_08, mv_xfmr_a, mvtc_b
_SUFFIX = re.compile(r"_([ab])(?:\d+|_\d+)?$")


def path_of(component: Any) -> str | None:
    """Path letter of a ComponentInfo (or None)."""
    meta = getattr(component, "metadata", {}) or {}
    p = str(meta.get("path", "")).strip().lower()
    if p in PATHS:
        return p
    m = _SUFFIX.search(getattr(component, "canonical_id", "") or "")
    return m.group(1) if m else None


def _by_type(model: Any, types: tuple[str, ...]) -> list[Any]:
    return [c for c in model.list_components() if c.type in types]


def _sorted_ids(components: list[Any]) -> list[str]:
    return sorted(c.canonical_id for c in components)


def transfer_ids(model: Any) -> dict[str, str]:
    """{path: transfer component id} for the paths that have one."""
    out: dict[str, str] = {}
    for c in sorted(_by_type(model, TRANSFER_TYPES), key=lambda c: c.canonical_id):
        p = path_of(c)
        if p and p not in out:
            out[p] = c.canonical_id
    return out


def ups_ids(model: Any, path: str | None = None) -> list[str]:
    """UPS ids, sorted; optionally only one path."""
    ups = _by_type(model, ("ups",))
    if path is not None:
        ups = [c for c in ups if path_of(c) == path]
    return _sorted_ids(ups)


def primary_ups(model: Any, path: str = "a") -> str | None:
    """The first UPS of a path (ups_a on legacy, ups_a_01 on v2)."""
    ids = ups_ids(model, path)
    return ids[0] if ids else None


def utility_transformer(model: Any, path: str) -> str | None:
    """First transformer reached walking down from the path's utility intake.

    Legacy: utility_feed_a -> ats_a -> xfmr_a (the DC-EPMS-058 ordering).
    v2:     utility_feed_a -> mv_xfmr_a. Breadth-first, nearest wins.
    """
    downstream = getattr(model, "_power_downstream", {}) or {}
    frontier = sorted(
        c.canonical_id
        for c in _by_type(model, ("utility_intake",))
        if path_of(c) == path
    )
    seen = set(frontier)
    for _depth in range(6):
        nxt_level: list[str] = []
        for node in frontier:
            for nxt in sorted(downstream.get(node, [])):
                if nxt in seen:
                    continue
                seen.add(nxt)
                try:
                    comp = model.get_component(nxt)
                except Exception:  # edge to an unknown id
                    continue
                if comp.type == "transformer":
                    return nxt
                nxt_level.append(nxt)
        frontier = nxt_level
        if not frontier:
            break
    return None


def group_for_path(nodes: list[str], transfers: dict[str, str]) -> str | None:
    """'path_a' / 'path_b' when a node list passes through that transfer."""
    for p in PATHS:
        tid = transfers.get(p)
        if tid and tid in nodes:
            return f"path_{p}"
    return None


def role_summary(model: Any) -> dict[str, Any]:
    """Per-path role map, for /api/site/model and the copilot tools."""
    transfers = transfer_ids(model)
    return {
        p: {
            "transfer": transfers.get(p),
            "ups": ups_ids(model, p),
            "utility_transformer": utility_transformer(model, p),
        }
        for p in PATHS
    }


# ── HLD aggregate namespace ─────────────────────────────────────────
# The topology endpoint (main.get_topology_state) and the copilot's
# query_unified_graph tool speak an AGGREGATED high-level namespace:
# utility_north / utility_south, xfmr_a / xfmr_b, ups_a / ups_b, rpp_*,
# busway_*, cdu_*, chiller_*, cooling_tower, hall_*. Under the legacy
# model several of those keys coincide with site-model ids; under v2
# they do not (path A has eight UPS blocks, one HLD "ups_a" group).
# hld_key maps a site-model id to the HLD group that represents it.

HLD_GROUP_LABELS = {
    "ups": "UPS group (all blocks of the path)",
    "utility_xfmr": "utility transformer of the path",
}


def hld_key(model: Any, component_id: str) -> str | None:
    """HLD aggregate key for a site-model component id, or None.

    Identity for ids that already are HLD keys on the legacy model.
    UPS blocks map to ``ups_<path>``; the path's utility transformer
    maps to ``xfmr_<path>``. Transfer devices (ATS, MV transfer
    controller), switchboards and generators have no HLD node.
    """
    try:
        comp = model.get_component(component_id)
    except Exception:  # not in the site model
        return None
    p = path_of(comp)
    if comp.type == "ups" and p:
        return f"ups_{p}"
    if comp.type == "transformer" and p and utility_transformer(model, p) == component_id:
        return f"xfmr_{p}"
    return None


def hld_members(model: Any, key: str) -> list[str]:
    """Site-model ids represented by an HLD key (inverse of hld_key)."""
    m = re.fullmatch(r"(ups|xfmr)_([ab])", key or "")
    if not m:
        return []
    kind, p = m.groups()
    if kind == "ups":
        return ups_ids(model, p)
    xf = utility_transformer(model, p)
    return [xf] if xf else []
