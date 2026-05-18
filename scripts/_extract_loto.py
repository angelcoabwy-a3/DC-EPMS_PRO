"""DC-EPMS PRO - one-shot: excise the LOTO Auditor view from app.js.

ROADMAP V11 T2.1 Vector 2 - the LOTO Auditor view (the 6-pillar audit
interface: LOTO_DEMO_PROCEDURES, lotoEscapeHtml, populateLotoProcedure
Select, submitLotoAudit, lotoOutcomeClass, lotoOverallClass,
renderLotoPillar, renderLotoResults, initLotoView + the legacy
click-delegation routing hack) has been migrated to
frontend/assets/js/views/loto.js - a decoupled ES module that uses
core/router.js registerRoute() instead of the document-level click hack.

The LOTO block is the LAST content in the IIFE; it is bracketed by a
'// ---' comment rule above the START line and another below the END
line. This removes both rules + the block, leaving a breadcrumb, and
keeps the trailing blank line + the IIFE close `})();`.

Byte-level read/write (no newline translation, no BOM).
"""

from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "frontend" / "assets" / "app.js"

START_MARK = "LOTO Auditor view (Camino 1 Phase E"
END_MARK = "END LOTO Auditor view"

BREADCRUMB = [
    "    // MIGRATED (ROADMAP V11 T2.1 Vector 2): the LOTO Auditor view now",
    "    // lives in views/loto.js (ES module). Route ownership moved to",
    "    // core/router.js registerRoute('loto') - the legacy document-level",
    "    // click-delegation + setTimeout(0) routing hack is retired.",
    "",
]


def main() -> int:
    text = APP.read_bytes().decode("utf-8")
    lines = text.split("\n")

    starts = [i for i, ln in enumerate(lines) if START_MARK in ln]
    ends = [i for i, ln in enumerate(lines) if END_MARK in ln]
    if len(starts) != 1 or len(ends) != 1:
        raise SystemExit(f"ambiguous markers: starts={starts} ends={ends}")

    # The block is bracketed by a '// ---' comment rule one line above the
    # START line and one line below the END line. Remove both rules too.
    block_start = starts[0] - 1
    block_end = ends[0] + 2  # END line + the closing '// ---' rule
    if not 0 < block_start < block_end <= len(lines):
        raise SystemExit(f"bad block bounds: {block_start}..{block_end}")

    rule_above = lines[block_start].strip()
    rule_below = lines[block_end - 1].strip()
    if not (rule_above.startswith("// --") and rule_below.startswith("// --")):
        raise SystemExit(
            f"expected '// ---' rules bracketing the block; "
            f"got above={rule_above!r} below={rule_below!r}"
        )

    removed = block_end - block_start
    new_lines = lines[:block_start] + BREADCRUMB + lines[block_end:]
    APP.write_bytes("\n".join(new_lines).encode("utf-8"))
    print(
        f"app.js: removed {removed} lines (LOTO Auditor view), breadcrumb "
        f"inserted at line {block_start + 1}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
