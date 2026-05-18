"""DC-EPMS PRO - one-shot: excise the Power SLD data-binder from app.js.

ROADMAP V11 T2.1 - the Power & UPS view data plane (renderPowerView +
fetchPowerSld + applyPowerSld + the 5 s poll timer) has been migrated to
frontend/assets/js/views/power.js (ES module). The 2.5D isometric
rendering engine (power_ups_iso/sld/grid/cam) is untouched. This removes
the now-dead IIFE block from the legacy monolith, leaving a breadcrumb.

Byte-level read/write (no newline translation, no BOM).
"""

from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "frontend" / "assets" / "app.js"

START_MARK = "Power & UPS Single-Line Diagram (v5.1)"
END_MARK = "Facility Co-Pilot view"

BREADCRUMB = [
    "    // MIGRATED (ROADMAP V11 T2.1): the Power & UPS SLD data plane now",
    "    // lives in views/power.js (ES module) + services/api.js. The 2.5D",
    "    // isometric engine (power_ups_iso/sld/grid/cam) is unchanged. Route",
    "    // ownership moved to core/router.js; this IIFE no longer renders it.",
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
        f"app.js: removed {removed} lines (Power SLD data plane), breadcrumb "
        f"inserted at line {start + 1}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
