"""
backend/cmms_classification.py
==============================
Shared CMMS work-order classification helpers.

Phase 1 structural compaction: these four helpers had drifted into
byte-identical copies inside both ``cmms_routes.py`` and
``cmms_predictive_trigger.py``. This module is now the single source of
truth for:

  - work-order id minting
  - LOR (Likelihood x Consequence) risk scoring
  - P1-P4 priority derivation
  - SOP / MOP / DMOP / EOP procedure-class derivation

Pure functions, no I/O, no dependency on the repository or FastAPI -
safe to import from anywhere in the CMMS stack.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime


def new_work_order_id() -> str:
    """Mint a work-order id. Format: ``WO-YYYYMMDD-<uuid8>``."""
    return f"WO-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"


def compute_lor(likelihood: int, consequence: int) -> int:
    """LOR = Likelihood x Consequence, clamped to the 1..25 risk band."""
    return max(1, min(25, likelihood * consequence))


def derive_priority(lor: int, criticality: str) -> str:
    """Derive a P1-P4 priority from the LOR score and asset criticality.

    Critical-class assets escalate one band (P3/P4 -> P2), and escalate
    to P1 once a critical asset's LOR reaches 15.
    """
    if lor >= 20:
        base = "P1"
    elif lor >= 12:
        base = "P2"
    elif lor >= 6:
        base = "P3"
    else:
        base = "P4"
    if criticality == "critical" and base in ("P3", "P4"):
        base = "P2"
    if criticality == "critical" and base == "P2" and lor >= 15:
        base = "P1"
    return base


def derive_procedure_class(work_class: str, requires_loto: bool) -> str:
    """Map a work class + LOTO requirement to a procedure class.

    EM -> EOP; any requires_loto -> DMOP; CM -> MOP; otherwise SOP.
    """
    if work_class == "EM":
        return "EOP"
    if requires_loto:
        return "DMOP"
    if work_class == "CM":
        return "MOP"
    return "SOP"
