"""
backend/usd_export.py
=====================
Release R2-C -- USD export of the site model (replaces the
"Omniverse 3D" stub).

What it is
----------
``build_usda`` renders ``config/site_model.yml`` as an OpenUSD ASCII
stage (``.usda``): one prim per building, room, row and component,
the component metadata as custom attributes, and the power and
cooling chains as USD relationships. The file opens in any USD tool
(usdview, Blender, NVIDIA Omniverse).

What it is NOT (honest scope)
-----------------------------
* There is no Omniverse live-link and no telemetry in the stage: it
  is a static export of the declared topology.
* The geometry is SCHEMATIC. The site model carries no coordinates,
  so components are placed on a deterministic grid (rows of racks,
  rooms side by side) and drawn as unit cubes scaled by asset type.
  It is not a surveyed or architectural layout. The stage says so in
  its ``doc`` metadata and on every geometry prim.
* All facility data is simulated.

Design notes
------------
* Pure text generation, no ``pxr`` dependency at runtime: the public
  instance installs requirements-minimal only. The test-suite opens
  the result with ``usd-core`` when that package is available.
* Deterministic: same model, byte-identical stage (sorted traversal,
  no clock, no randomness), so the export can be diffed in review.
* Vocabulary fence (S-VOCAB-01): metadata keys are copied verbatim.
  ``voltage_v_dc`` stays a DC attribute; nothing here re-labels the
  800 VDC unipolar bus with phase wording.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

__all__ = [
    "ROOT_PRIM",
    "SCHEMATIC_NOTICE",
    "USDA_MEDIA_TYPE",
    "build_usda",
    "export_filename",
    "prim_name",
    "register_usd_export_routes",
    "stage_summary",
]

USDA_MEDIA_TYPE = "text/plain; charset=utf-8"
ROOT_PRIM = "World"
SITE_PRIM = "Site"
NAMESPACE = "a3semi"

SCHEMATIC_NOTICE = (
    "SCHEMATIC layout generated from config/site_model.yml. The site model "
    "has no coordinates: positions and sizes are a deterministic grid, not a "
    "surveyed or architectural layout. All facility data is simulated."
)

# Footprint (x, y, z) in metres per asset type, used only to make the
# schematic readable. Typical envelope orders of magnitude; not vendor
# dimensions.
_DEFAULT_SIZE = (1.0, 1.0, 1.5)
_SIZE_BY_TYPE: dict[str, tuple[float, float, float]] = {
    "it_rack": (0.6, 1.2, 2.2),
    "cdu": (0.8, 1.2, 2.0),
    "rpp": (0.8, 0.4, 2.0),
    "busway": (6.0, 0.3, 0.3),
    "ups": (4.0, 1.0, 2.0),
    "switchgear": (4.0, 1.5, 2.3),
    "transformer": (3.0, 2.5, 3.0),
    "ats": (1.5, 1.0, 2.2),
    "genset": (6.0, 2.5, 3.0),
    "genset_farm": (30.0, 12.0, 4.0),
    "mv_bus": (12.0, 1.5, 2.5),
    "mv_rectifier": (6.0, 3.0, 3.0),
    "sscb": (1.2, 1.0, 2.2),
    "dc_bus": (10.0, 0.4, 0.4),
    "bess": (12.0, 2.5, 2.9),
    "utility_intake": (4.0, 4.0, 4.0),
    "chiller": (6.0, 2.5, 3.0),
    "cooling_tower_field": (10.0, 6.0, 5.0),
    "pump": (1.5, 1.0, 1.2),
    "fuel_tank": (6.0, 2.5, 2.5),
}

# displayColor (linear RGB 0-1) per asset family.
_COLOR_DEFAULT = (0.55, 0.58, 0.62)
_COLOR_BY_TYPE: dict[str, tuple[float, float, float]] = {
    "it_rack": (0.00, 0.72, 0.83),
    "cdu": (0.20, 0.55, 0.90),
    "chiller": (0.20, 0.55, 0.90),
    "cooling_tower_field": (0.20, 0.55, 0.90),
    "pump": (0.20, 0.55, 0.90),
    "coolant_pump": (0.20, 0.55, 0.90),
    "valve": (0.20, 0.55, 0.90),
    "ups": (0.98, 0.75, 0.14),
    "battery": (0.98, 0.75, 0.14),
    "bess": (0.98, 0.75, 0.14),
    "genset": (0.90, 0.45, 0.10),
    "genset_farm": (0.90, 0.45, 0.10),
    "fuel_tank": (0.90, 0.45, 0.10),
    "utility_intake": (0.85, 0.20, 0.20),
    "transformer": (0.85, 0.20, 0.20),
    "mv_bus": (0.85, 0.20, 0.20),
    "mv_rectifier": (0.85, 0.20, 0.20),
}

_ROOM_PITCH_X = 40.0     # metres between rooms of one building
_BUILDING_PITCH_Y = 60.0  # metres between buildings
_ROW_PITCH_Y = 3.6        # hot/cold aisle pitch between rack rows
_RACK_PITCH_X = 0.8       # rack-to-rack pitch inside a row
_EQUIP_GAP = 1.5          # gap between non-rack equipment in a room
_ROW_BLOCK_OFFSET_Y = 6.0  # rows start behind the room equipment line

_UNPLACED_BUILDING = "unplaced"
_UNPLACED_ROOM = "no_room"

_IDENT_RE = re.compile(r"[^A-Za-z0-9_]")


# ─────────────────────────────────────────────────────────────────────
#  Small pure helpers
# ─────────────────────────────────────────────────────────────────────
def prim_name(raw: Any) -> str:
    """A valid USD prim identifier for ``raw``.

    USD identifiers match ``[A-Za-z_][A-Za-z0-9_]*``. Anything else
    becomes ``_``; a leading digit or an empty result gets a ``_``
    prefix. Deterministic, never raises.
    """
    text = _IDENT_RE.sub("_", str(raw if raw is not None else ""))
    if not text or text[0].isdigit():
        text = "_" + text
    return text


def _usd_string(value: Any) -> str:
    """USD string literal. JSON escaping is a subset of USD's rules
    for double-quoted strings (backslash, quote, control characters),
    and ``ensure_ascii`` keeps the layer 7-bit clean."""
    return json.dumps(str(value), ensure_ascii=True)


def _fmt(number: float) -> str:
    """Compact, locale-free decimal with no exponent and no -0."""
    if not math.isfinite(number):
        return "0"
    text = f"{number:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _vec(values: tuple[float, float, float]) -> str:
    return "(" + ", ".join(_fmt(v) for v in values) + ")"


def export_filename(site_id: Any) -> str:
    """Download name derived from the site id (ASCII, no path parts)."""
    stem = re.sub(r"[^A-Za-z0-9_-]", "-", str(site_id or "site")).strip("-") or "site"
    return f"{stem}.usda"


def _meta_attr_lines(metadata: dict[str, Any], indent: str) -> list[str]:
    """Component metadata as ``custom`` attributes, sorted by key.

    bool -> bool, int -> int, float -> double, everything else ->
    string (lists and dicts are JSON-encoded so nothing is dropped).
    Non-finite floats are written as strings: USD has no portable
    literal for them in a double attribute.
    """
    lines: list[str] = []
    for key in sorted(metadata):
        name = f"{NAMESPACE}:meta:{prim_name(key)}"
        value = metadata[key]
        if isinstance(value, bool):
            lines.append(f"{indent}custom bool {name} = {'true' if value else 'false'}")
        elif isinstance(value, int):
            lines.append(f"{indent}custom int {name} = {value}")
        elif isinstance(value, float) and math.isfinite(value):
            lines.append(f"{indent}custom double {name} = {_fmt(value)}")
        elif isinstance(value, str):
            lines.append(f"{indent}custom string {name} = {_usd_string(value)}")
        elif value is None:
            continue
        else:
            encoded = json.dumps(value, sort_keys=True, default=str, ensure_ascii=True)
            lines.append(f"{indent}custom string {name} = {_usd_string(encoded)}")
    return lines


# ─────────────────────────────────────────────────────────────────────
#  Layout: group components and assign schematic positions
# ─────────────────────────────────────────────────────────────────────
def _group(model: Any) -> dict[str, dict[str, dict[str, list[Any]]]]:
    """building -> room -> row ("" = not in a row) -> components."""
    tree: dict[str, dict[str, dict[str, list[Any]]]] = {}
    for comp in model.list_components():
        loc = comp.location
        building = loc.building_id or _UNPLACED_BUILDING
        room = loc.room_id or _UNPLACED_ROOM
        row = loc.row_id or ""
        tree.setdefault(building, {}).setdefault(room, {}).setdefault(row, []).append(comp)
    for rooms in tree.values():
        for rows in rooms.values():
            for comps in rows.values():
                comps.sort(key=lambda c: c.canonical_id)
    return tree


def _display_names(model: Any) -> dict[str, str]:
    """building / room / row id -> display name, from the locations."""
    names: dict[str, str] = {}
    for comp in model.list_components():
        loc = comp.location
        for ident, display in (
            (loc.building_id, loc.building_display),
            (loc.room_id, loc.room_display),
            (loc.row_id, loc.row_display),
        ):
            if ident and display and ident not in names:
                names[ident] = display
    return names


def _prim_paths(tree: dict[str, dict[str, dict[str, list[Any]]]]) -> dict[str, str]:
    """canonical_id -> absolute prim path. Raises on a collision so a
    renamed asset can never silently shadow another prim."""
    paths: dict[str, str] = {}
    seen: dict[str, str] = {}
    for building in sorted(tree):
        for room in sorted(tree[building]):
            for row in sorted(tree[building][room]):
                for comp in tree[building][room][row]:
                    parts = [ROOT_PRIM, SITE_PRIM, prim_name(building), prim_name(room)]
                    if row:
                        parts.append(prim_name(row))
                    parts.append(prim_name(comp.canonical_id))
                    path = "/" + "/".join(parts)
                    if path in seen:
                        raise ValueError(
                            f"prim path collision: {comp.canonical_id!r} and "
                            f"{seen[path]!r} both map to {path}"
                        )
                    seen[path] = comp.canonical_id
                    paths[comp.canonical_id] = path
    return paths


def _rel_lines(name: str, targets: list[str], indent: str) -> list[str]:
    if not targets:
        return []
    if len(targets) == 1:
        return [f"{indent}custom rel {NAMESPACE}:{name} = <{targets[0]}>"]
    lines = [f"{indent}custom rel {NAMESPACE}:{name} = ["]
    lines.extend(f"{indent}    <{t}>," for t in targets)
    lines.append(f"{indent}]")
    return lines


def _component_block(
    comp: Any,
    position: tuple[float, float, float],
    paths: dict[str, str],
    power_down: dict[str, list[str]],
    cooling_down: dict[str, list[str]],
    indent: str,
) -> list[str]:
    size = _SIZE_BY_TYPE.get(comp.type, _DEFAULT_SIZE)
    color = _COLOR_BY_TYPE.get(comp.type, _COLOR_DEFAULT)
    # Unit cube (size = 1) scaled to the footprint, lifted so it sits
    # on the floor plane (z = 0).
    translate = (position[0], position[1], position[2] + size[2] / 2.0)
    inner = indent + "    "
    lines = [
        f'{indent}def Cube "{prim_name(comp.canonical_id)}" (',
        f"{inner}doc = {_usd_string('Schematic placeholder, not vendor geometry.')}",
        f'{inner}kind = "component"',
        f"{indent})",
        f"{indent}{{",
        f"{inner}double size = 1",
        f"{inner}color3f[] primvars:displayColor = [{_vec(color)}]",
        f"{inner}double3 xformOp:translate = {_vec(translate)}",
        f"{inner}float3 xformOp:scale = {_vec(size)}",
        f'{inner}uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]',
        f"{inner}custom string {NAMESPACE}:canonicalId = {_usd_string(comp.canonical_id)}",
        f"{inner}custom string {NAMESPACE}:assetType = {_usd_string(comp.type)}",
        f"{inner}custom string {NAMESPACE}:display = {_usd_string(comp.display)}",
        f"{inner}custom string {NAMESPACE}:locationPath = {_usd_string(comp.location.path)}",
    ]
    lines.extend(_meta_attr_lines(dict(comp.metadata or {}), inner))
    for rel_name, table in (("powerFeeds", power_down), ("coolingFeeds", cooling_down)):
        targets = sorted(
            paths[t] for t in set(table.get(comp.canonical_id, ())) if t in paths
        )
        lines.extend(_rel_lines(rel_name, targets, inner))
    lines.append(f"{indent}}}")
    return lines


def _xform_open(name: str, display: str | None, kind: str, indent: str) -> list[str]:
    inner = indent + "    "
    lines = [f'{indent}def Xform "{prim_name(name)}" (', f'{inner}kind = "{kind}"', f"{indent})", f"{indent}{{"]
    if display:
        lines.append(f"{inner}custom string {NAMESPACE}:display = {_usd_string(display)}")
    lines.append(f"{inner}custom string {NAMESPACE}:sourceId = {_usd_string(name)}")
    return lines


def stage_summary(model: Any) -> dict[str, Any]:
    """Counts the HMI shows next to the download (no stage text)."""
    tree = _group(model)
    paths = _prim_paths(tree)
    power = getattr(model, "_power_downstream", {}) or {}
    cooling = getattr(model, "_cooling_downstream", {}) or {}

    def _edges(table: dict[str, list[str]]) -> int:
        return sum(
            1 for src, dsts in table.items() if src in paths
            for dst in set(dsts) if dst in paths
        )

    by_type: dict[str, int] = {}
    for comp in model.list_components():
        by_type[comp.type] = by_type.get(comp.type, 0) + 1
    site = model.site_metadata() or {}
    return {
        "site_id": site.get("id"),
        "site_name": site.get("name"),
        "filename": export_filename(site.get("id")),
        "component_count": len(paths),
        "building_count": len(tree),
        "unplaced_component_count": sum(
            len(c) for rows in tree.get(_UNPLACED_BUILDING, {}).values() for c in rows.values()
        ),
        "power_edge_count": _edges(power),
        "cooling_edge_count": _edges(cooling),
        "components_by_type": dict(sorted(by_type.items())),
        "layout": "schematic",
        "notice": SCHEMATIC_NOTICE,
    }


def build_usda(model: Any) -> str:
    """Render the site model as a ``.usda`` layer. Deterministic."""
    tree = _group(model)
    paths = _prim_paths(tree)
    names = _display_names(model)
    power_down = getattr(model, "_power_downstream", {}) or {}
    cooling_down = getattr(model, "_cooling_downstream", {}) or {}
    site = model.site_metadata() or {}

    out: list[str] = [
        "#usda 1.0",
        "(",
        f'    defaultPrim = "{ROOT_PRIM}"',
        f"    doc = {_usd_string(SCHEMATIC_NOTICE)}",
        "    metersPerUnit = 1",
        '    upAxis = "Z"',
        "    customLayerData = {",
        f"        string generator = {_usd_string('DC-EPMS PRO backend/usd_export.py')}",
        f"        string layout = {_usd_string('schematic')}",
        f"        string siteId = {_usd_string(site.get('id', ''))}",
        f"        string siteName = {_usd_string(site.get('name', ''))}",
        f"        int componentCount = {len(paths)}",
        "    }",
        ")",
        "",
        f'def Xform "{ROOT_PRIM}" (',
        '    kind = "assembly"',
        ")",
        "{",
        f'    def Xform "{SITE_PRIM}" (',
        '        kind = "group"',
        "    )",
        "    {",
        f"        custom string {NAMESPACE}:display = {_usd_string(site.get('name', ''))}",
        f"        custom string {NAMESPACE}:sourceId = {_usd_string(site.get('id', ''))}",
    ]

    b_indent, r_indent, w_indent = " " * 8, " " * 12, " " * 16
    for b_index, building in enumerate(sorted(tree)):
        out.append("")
        out.extend(_xform_open(building, names.get(building), "group", b_indent))
        origin_y = b_index * _BUILDING_PITCH_Y
        for r_index, room in enumerate(sorted(tree[building])):
            out.append("")
            out.extend(_xform_open(room, names.get(room), "group", r_indent))
            origin_x = r_index * _ROOM_PITCH_X
            rows = tree[building][room]

            # Equipment not in a row: one line along X at the room front.
            cursor = origin_x
            for comp in rows.get("", []):
                width = _SIZE_BY_TYPE.get(comp.type, _DEFAULT_SIZE)[0]
                position = (cursor + width / 2.0, origin_y, 0.0)
                out.extend(_component_block(comp, position, paths, power_down, cooling_down, w_indent))
                cursor += width + _EQUIP_GAP

            # Rack rows: behind the equipment line, one aisle pitch apart.
            for row_index, row in enumerate(k for k in sorted(rows) if k):
                out.extend(_xform_open(row, names.get(row), "group", w_indent))
                row_y = origin_y + _ROW_BLOCK_OFFSET_Y + row_index * _ROW_PITCH_Y
                for slot, comp in enumerate(rows[row]):
                    position = (origin_x + slot * _RACK_PITCH_X, row_y, 0.0)
                    out.extend(
                        _component_block(comp, position, paths, power_down, cooling_down, w_indent + "    ")
                    )
                out.append(f"{w_indent}}}")
            out.append(f"{r_indent}}}")
        out.append(f"{b_indent}}}")

    out.extend(["    }", "}", ""])
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────────────────────────────────
def register_usd_export_routes(app: FastAPI, model_getter: Any) -> None:
    """Mount the read-only export (ADR-006).

    ``GET /api/site/usd``          the ``.usda`` layer as a download
    ``GET /api/site/usd/summary``  counts + the schematic notice

    ``model_getter`` is a zero-argument callable returning the loaded
    SiteModel -- injected so this module does not import site_model.

    FastAPI names are imported at module level on purpose: with
    ``from __future__ import annotations`` a ``Response`` annotation
    imported inside this function cannot be resolved by FastAPI (the
    forward-reference pitfall already recorded for this project).
    """
    def _model() -> Any:
        try:
            return model_getter()
        except Exception as e:
            raise HTTPException(503, f"site model unavailable: {str(e)[:160]}") from e

    @app.get("/api/site/usd/summary")
    async def get_site_usd_summary() -> dict[str, Any]:
        return stage_summary(_model())

    @app.get("/api/site/usd")
    async def get_site_usd() -> Response:
        model = _model()
        try:
            text = build_usda(model)
        except ValueError as e:
            raise HTTPException(500, f"USD export failed: {str(e)[:200]}") from e
        site = model.site_metadata() or {}
        return Response(
            content=text,
            media_type=USDA_MEDIA_TYPE,
            headers={
                "Content-Disposition": f'attachment; filename="{export_filename(site.get("id"))}"',
                "Cache-Control": "no-store",
            },
        )
