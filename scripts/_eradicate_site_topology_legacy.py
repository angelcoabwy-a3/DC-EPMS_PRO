"""DC-EPMS PRO - one-shot: ERADICATE the legacy Site Topology view.

ROADMAP V11 T2.1 Vector 3 - ADJUDICATION + ERADICATION (not migration).

Adjudication: the legacy Site Topology tree+detail UI (the `_st*` block
in app.js: _ST_LUCIDE_SVGS, _stLucideSvg, renderSiteTopologyView,
_stApi, _stRenderTree, _stBuildingNode/_stRoomNode/_stRowNode/_stLeaf,
_stSelect, _stLoadPowerTab, _stLoadLotoTab) is DEAD CODE.

  - views/site_topology.js (the modern force-directed graph) registers
    route 'site_topology' on core/router.js.
  - app.js navigateTo() delegates any registered route to the
    declarative router BEFORE the legacy `cfg.kind` switch is reached.
  - Therefore the `cfg.kind === 'site_topology'` branch - the only
    caller of renderSiteTopologyView - is never executed. The whole
    `_st*` block is unreachable.

Feature parity: the modern graph covers Overview (node detail panel)
and the Power chain (the Path-A/B 2N classifier + path-colour toggle).
The legacy per-rack LOTO-Impact tab is NOT pixel-replicated, but it is
unreachable today, the /api/site/loto-impact + /api/site/power-chain
backend endpoints are untouched, and dedicated LOTO analysis lives in
the (also-extracted) LOTO Auditor view. No user-facing capability is
lost. Per the SRE dead-code precedent (d495c7b): eradicate, do not
migrate dead code.

The `cfg.kind === 'site_topology'` dispatch branch is removed by a
separate edit; this script removes the `_st*` definition block.

Byte-level read/write (no newline translation, no BOM).
"""

from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "frontend" / "assets" / "app.js"

START_MARK = "Sprint S1b - Site Topology view renderer"
END_MARK = "function setupRouter()"

BREADCRUMB = [
    "    // ERADICATED (ROADMAP V11 T2.1 Vector 3): the legacy Site Topology",
    "    // tree+detail view was confirmed-dead code - views/site_topology.js",
    "    // (force-directed graph) owns the 'site_topology' route via",
    "    // core/router.js, so the legacy renderSiteTopologyView was",
    "    // unreachable. Deleted, not migrated. See scripts/",
    "    // _eradicate_site_topology_legacy.py for the full adjudication.",
    "",
]


def main() -> int:
    text = APP.read_bytes().decode("utf-8")
    lines = text.split("\n")

    starts = [i for i, ln in enumerate(lines) if START_MARK in ln]
    ends = [i for i, ln in enumerate(lines) if END_MARK in ln]
    if len(starts) != 1 or len(ends) != 1:
        raise SystemExit(f"ambiguous markers: starts={starts} ends={ends}")
    start, end = starts[0], ends[0]
    if not 0 < start < end:
        raise SystemExit(f"bad block bounds: start={start} end={end}")

    removed = end - start
    new_lines = lines[:start] + BREADCRUMB + lines[end:]
    APP.write_bytes("\n".join(new_lines).encode("utf-8"))
    print(
        f"app.js: ERADICATED {removed} lines (legacy Site Topology view), "
        f"breadcrumb inserted at line {start + 1}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
