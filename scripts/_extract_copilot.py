"""DC-EPMS PRO - one-shot: excise the Facility Co-Pilot view from app.js.

ROADMAP V11 T2.1 Phase 3 - the Facility Co-Pilot AI view (the agent
chat + draft-approval interface, 17 functions: renderCopilotView,
refreshCopilotStatus, the 4 wire* helpers, sendCopilotMessage,
appendCopilotMessage, renderToolTrace, refreshCopilotDrafts,
renderDraftCard, wireDraftActions, approve/reject/inspectDraft,
showDraftInspectModal, flashDraft) has been migrated to
frontend/assets/js/views/copilot.js - a decoupled ES module whose
LLM-authored surfaces route through core/sanitize.js (F3-5 XSS).

This removes the now-dead IIFE block, leaving a breadcrumb.

Byte-level read/write (no newline translation, no BOM).
"""

from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "frontend" / "assets" / "app.js"

START_MARK = "Facility Co-Pilot view (v8.0/v8.1 agent UI)"
END_MARK = "BMS Connector view (Day 7)"

BREADCRUMB = [
    "    // MIGRATED (ROADMAP V11 T2.1): the Facility Co-Pilot AI view now",
    "    // lives in views/copilot.js (ES module). LLM-authored chat/tool-trace",
    "    // surfaces route through core/sanitize.js (F3-5 XSS allowlist); the",
    "    // view subscribes to the Hermes hermes:agent-consensus DOM event.",
    "    // Route ownership moved to core/router.js; this IIFE no longer renders it.",
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
        f"app.js: removed {removed} lines (Facility Co-Pilot view), breadcrumb "
        f"inserted at line {start + 1}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
