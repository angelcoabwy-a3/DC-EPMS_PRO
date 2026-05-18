"""DC-EPMS PRO - one-shot: excise the MOPs view block from app.js.

ROADMAP V11 T2.1 - the MOPs/SOPs/EOPs library has been migrated to
frontend/assets/js/views/mops.js (ES module). This removes the now-dead
IIFE block (renderMopsView + showMopDetail + renderMopContent +
showMopGenerator + generateMop + renderGeneratedMop + markdownLite +
its module state) from the legacy monolith, leaving a breadcrumb.

Byte-level read/write (no newline translation, no BOM) so the LF line
endings + box-drawing / emoji chars elsewhere in app.js survive intact.
"""

from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "frontend" / "assets" / "app.js"

START_MARK = "MOPs / SOPs / EOPs view (Day 5)"
END_MARK = "Topology view (Day 6)"

BREADCRUMB = [
    "    // MIGRATED (ROADMAP V11 T2.1): the MOPs/SOPs/EOPs library now",
    "    // lives in views/mops.js (ES module) + services/api.js. Route",
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
        f"app.js: removed {removed} lines (MOPs block), breadcrumb inserted "
        f"at line {start + 1}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
