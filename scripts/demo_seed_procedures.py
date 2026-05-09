"""
demo_seed_procedures.py
========================
Seeds 3 deterministic demo procedures for the LOTO Auditor live demo:

  1. DEMO-UPS-COMPLIANT          - all 6 pillars PASS
  2. DEMO-UPS-MISSING-DISCHARGE  - Pillar 3 HARD_FAIL (NEC 460.6)
  3. DEMO-RECTIFIER-UNDER-PPE    - Pillar 6 HARD_FAIL (NFPA 70E)

These procedures are written to config/procedures/ in the format the
LOTO Auditor expects. The targets must exist in your site_model.yml.
If they do not, edit the target_component_id below or run the demo
against components that ARE in your site model.

Idempotent: skips files that already exist. Use --force to overwrite.

Usage:
    python demo_seed_procedures.py
    python demo_seed_procedures.py --force      # overwrite if exists
    python demo_seed_procedures.py --dry-run    # preview only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROCEDURES_DIR = Path("config/procedures")


# =============================================================================
#  Procedure definitions (YAML strings - written verbatim)
# =============================================================================

PROCEDURE_COMPLIANT = """\
# DEMO-UPS-COMPLIANT
# A fully compliant LOTO procedure for a UPS unit on path A.
# All 6 pillars should PASS for this procedure.
procedure_id: DEMO-UPS-COMPLIANT
title: UPS Path A - Monthly LOTO (Compliant Demo)
target_component_id: ups_a
ppe_category: 2
loto_level: 3
metadata:
  version: 1.0
  author: wilmer
  reviewed_by: "[CET pending]"
  jurisdiction: Ontario
  standards:
    - "NFPA 70E Section 130"
    - "NEC 460.6"
    - "CSA Z462-24"
  estimated_duration_minutes: 45

steps:
  - id: step_1
    description: "Notify CMMS of upcoming LOTO. Confirm path B is fully online."
    phase: PREP
    estimated_duration_s: 60

  - id: step_2
    description: "Don PPE Category 2: arc-rated coverall, hood, gloves, voltage-rated boots."
    phase: PPE_DON
    estimated_duration_s: 180

  - id: step_3
    description: "Open upstream breaker BKR-A-UPS-01 with witness present. Verify visually."
    phase: ELECTRICAL
    requires_witness: true
    estimated_duration_s: 60

  - id: step_4
    description: "Apply lockout device on BKR-A-UPS-01 handle. Apply personal danger tag."
    phase: ELECTRICAL
    estimated_duration_s: 120

  - id: step_5
    description: "Wait 120 seconds for capacitor discharge per NEC 460.6."
    phase: ELECTRICAL
    duration_s: 120
    estimated_duration_s: 120

  - id: step_6
    description: "Verify zero voltage with CAT IV voltmeter on all three phases."
    phase: ELECTRICAL
    requires_voltmeter: true
    estimated_duration_s: 90

  - id: step_7
    description: "Close coolant supply isolation valve VLV-A-UPS-01-CLG."
    phase: HYDRAULIC
    estimated_duration_s: 60

  - id: step_8
    description: "Purge cooling lines through drain port DRN-A-UPS-01."
    phase: PURGE
    estimated_duration_s: 300

  - id: step_9
    description: "Place equipment-out-of-service tag on UPS-A control panel."
    phase: SIGNOFF
    estimated_duration_s: 60
"""


PROCEDURE_MISSING_DISCHARGE = """\
# DEMO-UPS-MISSING-DISCHARGE
# A defective LOTO procedure: missing the capacitor discharge step.
# Pillar 3 should HARD_FAIL with NEC 460.6 citation.
# This is the kind of subtle defect that can kill a CET. The breaker is
# open, the lockout is on, but there are hundreds of joules sitting in
# the DC bus capacitors.
procedure_id: DEMO-UPS-MISSING-DISCHARGE
title: UPS Path A - LOTO (Defective - missing discharge)
target_component_id: ups_a
ppe_category: 2
loto_level: 3
metadata:
  version: 1.0
  author: wilmer
  reviewed_by: "[CET pending]"
  jurisdiction: Ontario
  estimated_duration_minutes: 30
  defect_type: "Missing capacitor discharge step (NEC 460.6 violation)"

steps:
  - id: step_1
    description: "Don PPE Category 2."
    phase: PPE_DON
    estimated_duration_s: 180

  - id: step_2
    description: "Open upstream breaker BKR-A-UPS-01."
    phase: ELECTRICAL
    requires_witness: true
    estimated_duration_s: 60

  - id: step_3
    description: "Apply lockout device on BKR-A-UPS-01 handle."
    phase: ELECTRICAL
    estimated_duration_s: 120

  # NOTE: capacitor discharge step is INTENTIONALLY MISSING here.
  # No 60-second wait. No CAT IV voltmeter verification.

  - id: step_4
    description: "Place equipment-out-of-service tag on UPS-A control panel."
    phase: SIGNOFF
    estimated_duration_s: 60
"""


PROCEDURE_UNDER_PPE = """\
# DEMO-RECTIFIER-UNDER-PPE
# A defective LOTO procedure: PPE Category 1 specified for an 800VDC
# rectifier. NFPA 70E §130 voltage matrix requires Category 3 minimum
# for 600V+ DC. Pillar 6 should HARD_FAIL.
procedure_id: DEMO-RECTIFIER-UNDER-PPE
title: MV Rectifier - LOTO (Defective - PPE under-specified)
target_component_id: rectifier_a
ppe_category: 1
loto_level: 4
metadata:
  version: 1.0
  author: wilmer
  reviewed_by: "[CET pending]"
  jurisdiction: Ontario
  estimated_duration_minutes: 60
  defect_type: "PPE Category 1 specified for 800VDC equipment (NFPA 70E violation)"

steps:
  - id: step_1
    description: "Don PPE Category 1: standard arc-rated shirt and pants."
    phase: PPE_DON
    estimated_duration_s: 120

  - id: step_2
    description: "Open MV upstream isolation breaker BKR-MV-01 with witness."
    phase: ELECTRICAL
    requires_witness: true
    estimated_duration_s: 90

  - id: step_3
    description: "Apply lockout on BKR-MV-01."
    phase: ELECTRICAL
    estimated_duration_s: 120

  - id: step_4
    description: "Wait 300 seconds for full DC bus discharge per NEC 460.6."
    phase: ELECTRICAL
    duration_s: 300

  - id: step_5
    description: "Verify zero voltage with CAT IV voltmeter on DC+ and DC- buses."
    phase: ELECTRICAL
    requires_voltmeter: true
    estimated_duration_s: 90

  - id: step_6
    description: "Close DC output isolation switch SW-DC-01."
    phase: ELECTRICAL
    estimated_duration_s: 60
"""


# =============================================================================
#  Main
# =============================================================================

PROCEDURES = [
    ("DEMO-UPS-COMPLIANT.yml", PROCEDURE_COMPLIANT),
    ("DEMO-UPS-MISSING-DISCHARGE.yml", PROCEDURE_MISSING_DISCHARGE),
    ("DEMO-RECTIFIER-UNDER-PPE.yml", PROCEDURE_UNDER_PPE),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    parser.add_argument("--dry-run", action="store_true", help="preview only, do not write files")
    parser.add_argument(
        "--procedures-dir",
        default=str(PROCEDURES_DIR),
        help=f"output directory (default: {PROCEDURES_DIR})",
    )
    args = parser.parse_args()

    out_dir = Path(args.procedures_dir)

    if args.dry_run:
        print(f"[DRY-RUN] Would write to: {out_dir.absolute()}")
        for name, _ in PROCEDURES:
            target = out_dir / name
            status = "EXISTS (would skip)" if target.exists() else "would create"
            print(f"  {name}: {status}")
        return 0

    if not out_dir.exists():
        print(f"Creating directory: {out_dir.absolute()}")
        out_dir.mkdir(parents=True, exist_ok=True)

    written_count = 0
    skipped_count = 0

    for name, content in PROCEDURES:
        target = out_dir / name
        if target.exists() and not args.force:
            print(f"  SKIP (exists): {target}")
            skipped_count += 1
            continue
        target.write_text(content, encoding="utf-8")
        action = "OVERWROTE" if target.exists() and args.force else "WROTE"
        print(f"  {action}: {target}")
        written_count += 1

    print()
    print(f"Done. Wrote {written_count}, skipped {skipped_count}.")

    if written_count > 0:
        print()
        print("Next steps:")
        print("  1. Verify the target_component_id values match your site_model.yml:")
        print("     - ups_a")
        print("     - rectifier_a")
        print("     If your site model uses different IDs, edit the YAML files.")
        print()
        print("  2. Run a test audit against the compliant procedure:")
        print("     curl -X POST http://127.0.0.1:8080/api/loto/audit \\")
        print("       -H 'Content-Type: application/json' \\")
        print(
            '       -d \'{"procedure_id":"DEMO-UPS-COMPLIANT","target_component_id":"ups_a","cet_on_duty":"wilmer"}\''
        )
        print()
        print("  Expected: overall_outcome=pass, hard_fail_count=0")

    return 0


if __name__ == "__main__":
    sys.exit(main())
