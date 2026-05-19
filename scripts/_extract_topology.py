"""DC-EPMS PRO - one-shot: excise the HLD/LLD Topology view from app.js.

ROADMAP V11 T2.1 Vector 4 (Stage 4a) - the Facility Topology (HLD/LLD)
view (renderTopologyView, runEmergencyWhatIf, showWhatIfBanner,
fetchTopologyState, applyTopologyState, applyNodeBadge, applyNodeMetrics,
updateSparkline, updateDeltaTRisk, renderMissionControlInsights,
generateInsights, fmt0, fmt1, renderLLDRacks, showTopologyNodeDetail)
has been migrated to frontend/assets/js/views/topology.js - a decoupled
ES module that uses core/router.js registerRoute('topology').

This removes the now-dead IIFE block, leaving a breadcrumb.

Byte-level read/write (no newline translation, no BOM).
"""

from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "frontend" / "assets" / "app.js"

START_MARK = "Topology view (Day 6)"
END_MARK = "MIGRATED (ROADMAP V11 T2.1): the Cooling"

BREADCRUMB = [
    "    // MIGRATED (ROADMAP V11 T2.1 Vector 4a): the HLD/LLD Topology view",
    "    // now lives in views/topology.js (ES module). Route ownership moved",
    "    // to core/router.js registerRoute('topology'); this IIFE no longer",
    "    // renders it.",
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
        f"app.js: removed {removed} lines (HLD/LLD Topology view), breadcrumb "
        f"inserted at line {start + 1}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
