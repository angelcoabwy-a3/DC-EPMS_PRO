"""Demo the hackathon-built Shift Forensic Investigator (no API key needed).

Injects the pre-existing utility_failure scenario, runs the
deterministic analysis, then investigates the burst. Without
META_API_KEY set, the agent uses the deterministic investigation
and prints that source clearly, so the demo never pretends a model
call happened.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.copilot_forensic import investigate_sync  # noqa: E402
from backend.shift_copilot import (  # noqa: E402
    SimulateIn,
    copilot_simulate,
    run_analysis,
)


def main() -> None:
    copilot_simulate(SimulateIn(scenario="utility_failure", count=8))
    analysis = run_analysis()
    result = investigate_sync(analysis)
    print(f"Investigation source: {result['source']}")
    print(f"Probable cause ({result['confidence']} confidence): {result['probable_cause']}")
    print(f"Priority: {result['priority']} | Story: {result['story_id']}")
    print("--- Timeline (evidence) ---")
    for e in result["timeline"]:
        print(f"{e['created_at']} | {e['source']} | {e['severity']} | {e['title']}")
    print("--- Hypotheses ---")
    for h in result["hypotheses"]:
        print(f"{h['label']}: {h['status']}")
    print("--- Verify in person ---")
    for item in result["verification_checklist"]:
        print(f"- {item}")
    print("---")
    print(result["text"])


if __name__ == "__main__":
    main()
