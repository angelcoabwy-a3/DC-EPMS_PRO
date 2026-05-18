"""DC-EPMS PRO - one-shot: excise the BMS Connector view from app.js.

ROADMAP V11 T2.1 Vector 1 - the BMS Connector view (the BACnet/Modbus
tag-namespace browser: closeBmsModals, bindModalClickAway, renderBmsView,
fetchBmsTags, renderBmsCategories, renderBmsStats, renderBmsTable,
formatBmsValue, showBmsWriteModal, submitBmsWrite, showBmsAudit) has
been migrated to frontend/assets/js/views/bms.js - a decoupled ES
module. showBmsAudit is re-exposed on window for the copilot deep-link.

This removes the now-dead IIFE block, leaving a breadcrumb.

Byte-level read/write (no newline translation, no BOM).
"""

from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "frontend" / "assets" / "app.js"

START_MARK = "BMS Connector view (Day 7)"
END_MARK = "Original placeholder renderer"

BREADCRUMB = [
    "    // MIGRATED (ROADMAP V11 T2.1 Vector 1): the BMS Connector view now",
    "    // lives in views/bms.js (ES module). Route ownership moved to",
    "    // core/router.js; showBmsAudit is re-exposed on window so the",
    "    // views/copilot.js audit deep-link keeps working. This IIFE no",
    "    // longer renders it.",
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
        f"app.js: removed {removed} lines (BMS Connector view), breadcrumb "
        f"inserted at line {start + 1}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
