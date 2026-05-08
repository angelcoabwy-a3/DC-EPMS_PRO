"""
backend/loto_auditor_pillar_helpers.py
========================================
Helper functions for LOTO Auditor Pillars 1+2+3 (Batch 4.B).

Design principles:
  - Pure functions where possible (no hidden state, no I/O)
  - Defensive: tolerate missing metadata, mocked dependencies
  - Deterministic: same inputs always produce same outputs
  - Logged at DEBUG level so audit trace can reconstruct decisions

These helpers are imported by loto_auditor_agent.py to keep the
6-pillar method bodies short and focused on pillar logic, not
parsing minutiae.

References:
  - NEC 460.6 (Capacitor Discharge): 60-second minimum wait,
    50V threshold, voltmeter verification
  - Tier IV Topology Standard (Uptime Institute): 70% retention
    threshold for redundancy survival
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

log = logging.getLogger(__name__)


# =============================================================================
#  Procedure parsing helpers (Pillar 3 support)
# =============================================================================

# Keywords that indicate a step performs capacitor discharge or equivalent
DISCHARGE_KEYWORDS: tuple[str, ...] = (
    "discharge",
    "capacitor",
    "wait for caps",
    "wait for capacitors",
    "cap discharge",
    "capacitive",
    "stored energy",
    "bleed resistor",
    "dc link discharge",
)

# Keywords that indicate CAT IV voltmeter verification of de-energized state
VOLTMETER_KEYWORDS: tuple[str, ...] = (
    "cat iv",
    "category iv",
    "cat-iv",
    "voltmeter",
    "fluke",
    "verify zero",
    "verify de-energized",
    "verify de-energised",
    "zero-energy verification",
    "absence of voltage",
)

# Phase classification keywords for Pillar 5 (defined here for Batch 4.C reuse)
ELECTRICAL_PHASE_KEYWORDS: tuple[str, ...] = (
    "open breaker",
    "open disconnect",
    "rack out",
    "racked out",
    "open switch",
    "isolate electrical",
    "trip ats",
    "lockout breaker",
    "tag-out breaker",
)

HYDRAULIC_PHASE_KEYWORDS: tuple[str, ...] = (
    "close valve",
    "close coolant",
    "coolant valve",
    "valve to isolate",
    "isolate cooling",
    "isolate coolant",
    "isolate manifold",
    "isolate loop",
    "isolate cdu",
    "stop pump",
    "stop secondary pump",
    "stop primary pump",
    "drain coolant",
    "drain loop",
    "drain manifold",
    "close manifold",
    "shut off chilled water",
    "shut down chilled water",
    "isolate chilled water",
)

PURGE_PHASE_KEYWORDS: tuple[str, ...] = (
    "purge",
    "vent",
    "release pressure",
    "evacuate",
    "blow down",
    "flush nitrogen",
)


def step_text(step: dict) -> str:
    """Concatenate description, action, title, and notes from a YAML step.

    Returns lowercased text for case-insensitive keyword matching.
    """
    parts = [
        str(step.get("description", "")),
        str(step.get("action", "")),
        str(step.get("title", "")),
        str(step.get("notes", "")),
        str(step.get("name", "")),
    ]
    return " ".join(p for p in parts if p).lower()


def extract_wait_seconds(step: dict) -> int:
    """Return the wait duration in seconds for a step.

    Strategy:
      1. Check explicit fields: 'wait_seconds', 'duration_s', 'duration_seconds'
      2. Regex-extract from text (e.g. '60 second', '120s', '5 minute')
      3. Return max of all sources (conservative for safety)
    """
    seconds = 0

    # Explicit numeric fields
    for key in ("wait_seconds", "duration_s", "duration_seconds", "wait_s"):
        v = step.get(key)
        if v is None:
            continue
        try:
            iv = int(v)
            if iv > seconds:
                seconds = iv
        except (TypeError, ValueError):
            log.debug("Step has non-numeric %s field: %r", key, v)

    # Regex extraction from concatenated text
    text = step_text(step)

    # Match patterns like "60 second", "60 seconds", "60s", "60 sec", "60-second"
    sec_matches = re.findall(r"\b(\d+)\s*(?:[-]\s*)?(?:seconds?|secs?|s)\b", text)
    for m in sec_matches:
        try:
            iv = int(m)
            if iv > seconds:
                seconds = iv
        except ValueError:
            continue

    # Match "1 minute", "5 minutes", "5 mins"
    min_matches = re.findall(r"\b(\d+)\s*(?:[-]\s*)?(?:minutes?|mins?)\b", text)
    for m in min_matches:
        try:
            iv = int(m) * 60
            if iv > seconds:
                seconds = iv
        except ValueError:
            continue

    return seconds


def parse_discharge_compliance(steps: list[dict]) -> tuple[bool, int, bool]:
    """Scan procedure steps for capacitor discharge compliance.

    Returns:
        (found, wait_seconds, has_voltmeter)
        - found: True if any step matches DISCHARGE_KEYWORDS
        - wait_seconds: maximum wait duration found across discharge steps
        - has_voltmeter: True if any step matches VOLTMETER_KEYWORDS
    """
    found = False
    wait_seconds = 0
    has_voltmeter = False

    for step in steps:
        text = step_text(step)
        if any(kw in text for kw in DISCHARGE_KEYWORDS):
            found = True
            ws = extract_wait_seconds(step)
            if ws > wait_seconds:
                wait_seconds = ws

        if any(kw in text for kw in VOLTMETER_KEYWORDS):
            has_voltmeter = True

    log.debug(
        "Discharge parse: found=%s wait_s=%d voltmeter=%s",
        found, wait_seconds, has_voltmeter,
    )
    return found, wait_seconds, has_voltmeter


# =============================================================================
#  Steady-state measurement builder (Pillar 2 support)
# =============================================================================

def build_steady_state_measurements(
    overrides: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build a baseline measurement dictionary for physics_engine.validate_site().

    Values approximate A3-Alpha Phase 1 nominal operating point:
      - Utility 17.4 MW total
      - IT load 16.7 MW (Buildings A+B Phase 1: 118 racks * 142 kW)
      - Both UPS Galaxy VX online
      - 3 chillers York YZ N+1 active
      - Chilled water supply 7 degC (ASHRAE A2 envelope)
      - Hall inlet 22 degC (within Class A2 18-27 degC)
      - Path A and Path B fully present

    NOTE: real production agent (Batch 4.D) replaces this with TimescaleDB
    snapshot at as_of_timestamp. Batch 4.B uses these defaults so the
    physics_engine still produces a valid baseline SHI for comparison.
    """
    base = {
        # Electrical
        "utility_kw": 17400.0,
        "facility_it_kw": 16756.0,
        "ups_load_kw": 16756.0,
        "ups_mode": "online",
        "ups_a_online": True,
        "ups_b_online": True,
        "ats_position": "primary",
        # Cooling
        "chiller_count_online": 3,
        "chiller_supply_temp_c": 7.0,
        "chiller_return_temp_c": 12.0,
        "cooling_tower_count_online": 2,
        "chw_pump_count_online": 3,
        "cdu_pressure_bar": 2.0,
        # Thermal
        "hall_inlet_temp_c": 22.0,
        "hall_outlet_temp_c": 27.0,
        "hall_dewpoint_c": 8.0,
        "rack_count": 118,
        "rack_tdp_kw": 142.0,
        # Mechanical
        "pump_suction_bar": 1.8,
        "pump_power_kw": 45.0,
    }

    if overrides:
        base.update(overrides)

    return base


def simulate_loto_measurements(
    base: dict[str, Any],
    target_id: str,
    target_type: str,
    target_path: Optional[str] = None,
) -> dict[str, Any]:
    """Apply LOTO simulation to baseline measurements.

    Returns a NEW dict (does not mutate base). The simulation is conservative:
      - Force the affected component offline
      - Reduce redundant component count by 1
      - Leave non-affected paths nominal

    Component-type rules:
      - ups: forces ups_X_online = False, mode = "single_path"
      - chiller: decrements chiller_count_online
      - ats: forces position = "alternate"
      - cooling_tower: decrements cooling_tower_count_online
      - chw_pump: decrements chw_pump_count_online
      - cdu: marks cooling chain degraded (CDU loss is hydraulic)
      - rpp / busway / xfmr: zero kW for that path
      - default: passes base through (other component types not yet modeled)
    """
    sim = dict(base)
    target_lower = target_id.lower()
    type_lower = target_type.lower()

    if type_lower == "ups":
        if "_a" in target_lower:
            sim["ups_a_online"] = False
        elif "_b" in target_lower:
            sim["ups_b_online"] = False
        sim["ups_mode"] = "single_path"
        # Approximate: lose half the UPS-served load capacity
        # (real physics would rebalance, this is conservative for SHI)
        sim["ups_load_kw"] = base.get("ups_load_kw", 16756.0) * 0.95

    elif type_lower == "chiller":
        sim["chiller_count_online"] = max(
            0, int(base.get("chiller_count_online", 3)) - 1
        )

    elif type_lower == "ats":
        sim["ats_position"] = "alternate"

    elif type_lower == "cooling_tower":
        sim["cooling_tower_count_online"] = max(
            0, int(base.get("cooling_tower_count_online", 2)) - 1
        )

    elif type_lower == "chw_pump":
        sim["chw_pump_count_online"] = max(
            0, int(base.get("chw_pump_count_online", 3)) - 1
        )

    elif type_lower == "cdu":
        # CDU loss reduces secondary loop capacity
        sim["cdu_offline_count"] = int(base.get("cdu_offline_count", 0)) + 1

    elif type_lower in ("rpp", "busway", "xfmr", "transformer"):
        # Path-level loss reduces facility IT capacity
        if target_path == "A":
            sim["facility_it_kw"] = base.get("facility_it_kw", 16756.0) * 0.5
        elif target_path == "B":
            sim["facility_it_kw"] = base.get("facility_it_kw", 16756.0) * 0.5

    return sim


# =============================================================================
#  SPOF detection (Pillar 2 support)
# =============================================================================

def detect_chiller_spof(
    target_type: str,
    chiller_count_online_post: int,
    n_plus_1_threshold: int = 2,
) -> Optional[str]:
    """Return SPOF description if chiller redundancy is lost, else None.

    Logic (per A3-Alpha N+1 cooling doctrine):
      - 3 chillers nominal (1 in standby) is N+1
      - LOTO 1 chiller leaves 2 active = still N (no margin) but operational
      - If only 1 left, ANY second failure = full cooling loss
    """
    if target_type.lower() != "chiller":
        return None

    if chiller_count_online_post < n_plus_1_threshold:
        return (
            f"Chiller count post-LOTO is {chiller_count_online_post}, "
            f"below N+1 threshold {n_plus_1_threshold}. "
            "Any second chiller failure causes full cooling loss."
        )
    return None


def detect_ups_path_spof(
    target_type: str,
    target_path: Optional[str],
    ups_a_online: bool,
    ups_b_online: bool,
) -> Optional[str]:
    """Return SPOF description if UPS path redundancy is lost.

    LOTO of UPS_A means UPS_B must carry full load. If UPS_B is also
    offline (overlapping maintenance) we have catastrophic loss of
    conditioned power.
    """
    if target_type.lower() != "ups":
        return None

    if target_path == "A" and not ups_b_online:
        return (
            "UPS_A is target of LOTO and UPS_B is also offline. "
            "Total loss of conditioned power."
        )
    if target_path == "B" and not ups_a_online:
        return (
            "UPS_B is target of LOTO and UPS_A is also offline. "
            "Total loss of conditioned power."
        )
    return None


# =============================================================================
#  Capacitor discharge requirement classifier (Pillar 3 support)
# =============================================================================

def classify_capacitor_discharge_requirement(
    voltage_nominal: float,
    target_type: str,
    has_dc_link: bool,
) -> tuple[bool, list[str]]:
    """Determine if capacitor discharge is required for this target.

    Returns:
        (required: bool, reasons: list[str])

    Rules (in order of severity):
      1. voltage_nominal >= 800 V: required (Building D 800VDC mandate)
      2. target_type == 'ups': required (Galaxy VX has DC link caps)
      3. has_dc_link == True: required (any equipment with DC link caps)
      4. otherwise: not required
    """
    required = False
    reasons: list[str] = []

    if voltage_nominal >= 800.0:
        required = True
        reasons.append(
            f"voltage_nominal {voltage_nominal:.0f} V >= 800 V "
            "(Building D 800VDC mandate)"
        )

    if target_type.lower() == "ups":
        required = True
        reasons.append(
            "UPS targets always require capacitor discharge "
            "(Galaxy VX DC link caps)"
        )

    if has_dc_link:
        required = True
        reasons.append("Target metadata indicates DC link capacitors present")

    return required, reasons


# =============================================================================
#  Component metadata accessors (defensive readers)
# =============================================================================

def get_voltage_nominal(component: Any) -> float:
    """Read voltage_nominal from component metadata, default 0.0 if missing."""
    try:
        meta = getattr(component, "metadata", {}) or {}
        return float(meta.get("voltage_nominal", 0.0))
    except (TypeError, ValueError):
        return 0.0


def get_rated_kw(component: Any) -> float:
    """Read rated_kw from component metadata, default 0.0 if missing."""
    try:
        meta = getattr(component, "metadata", {}) or {}
        v = meta.get("rated_kw") or meta.get("rated_power_kw") or 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def get_path(component: Any) -> Optional[str]:
    """Read path (A or B) from component metadata, None if not 2N protected."""
    try:
        meta = getattr(component, "metadata", {}) or {}
        path = meta.get("path") or meta.get("electrical_path")
        if path is None:
            return None
        path_str = str(path).upper().strip()
        if path_str in ("A", "B"):
            return path_str
        return None
    except (TypeError, ValueError):
        return None


def get_has_dc_link(component: Any) -> bool:
    """Read has_dc_link from component metadata, default False."""
    try:
        meta = getattr(component, "metadata", {}) or {}
        return bool(meta.get("has_dc_link", False))
    except (TypeError, ValueError):
        return False


def get_component_type(component: Any) -> str:
    """Read component type, default empty string."""
    try:
        return str(getattr(component, "type", "") or "").strip()
    except (TypeError, ValueError):
        return ""


# =============================================================================
#  Rack counting helper (Pillar 1 support)
# =============================================================================

def is_rack_type(component_type: str) -> bool:
    """Return True if component type denotes a compute rack.

    Matches:
      - 'gb200_rack', 'gb300_rack' (Path C2 facility scale)
      - any type ending in '_rack'
      - 'rack' or 'compute_rack'
    """
    if not component_type:
        return False
    lower = component_type.lower().strip()
    return (
        lower.endswith("_rack")
        or lower in ("rack", "compute_rack")
    )


# =============================================================================
#  LOTO Level classifier (Pillar 4 support)
# =============================================================================

# Imported lazily within functions to avoid circular import at module load
def classify_loto_level(
    voltage_nominal: float,
    target_type: str,
    has_dc_link: bool,
) -> tuple[Any, str]:
    """Classify LOTO Level per a3semi doctrine.

    Returns (LotoLevel enum, rationale string).

    Rules (highest-severity first):
      1. voltage_nominal >= 800: Level 4 (arc flash hazard, Building D)
      2. has_dc_link OR type == 'ups': Level 3 (cap discharge required)
      3. 50 <= voltage_nominal < 600: Level 2 (intermediate, single-source)
      4. otherwise: Level 1 (basic, low voltage)

    Note: passing 600 <= voltage_nominal < 800 with no caps and not UPS
    is treated as Level 2 with caveat - this is unusual in A3-Alpha
    (no equipment in this range exists in current site_model) but the
    classifier is conservative and does not crash.
    """
    from loto_auditor_models import LotoLevel  # late import

    if voltage_nominal >= 800.0:
        return LotoLevel.LEVEL_4_ARC_FLASH, (
            f"voltage_nominal {voltage_nominal:.0f}V >= 800V "
            "(Building D arc flash hazard, NFPA 70E Cat 3+ mandate)"
        )

    type_lower = (target_type or "").lower()
    has_caps = has_dc_link or type_lower == "ups"
    if has_caps:
        reasons = []
        if type_lower == "ups":
            reasons.append("UPS type (Galaxy VX DC link caps)")
        if has_dc_link:
            reasons.append("metadata.has_dc_link is True")
        return LotoLevel.LEVEL_3_CAP_DISCHARGE, "; ".join(reasons)

    if 50.0 <= voltage_nominal < 600.0:
        return LotoLevel.LEVEL_2_INTERMEDIATE, (
            f"voltage_nominal {voltage_nominal:.0f}V in 50-600V range, "
            "no capacitor discharge hazard"
        )

    if 600.0 <= voltage_nominal < 800.0:
        return LotoLevel.LEVEL_2_INTERMEDIATE, (
            f"voltage_nominal {voltage_nominal:.0f}V in 600-800V range "
            "without DC link - unusual configuration, treated as Level 2"
        )

    return LotoLevel.LEVEL_1_BASIC, (
        f"voltage_nominal {voltage_nominal:.0f}V < 50V, "
        "basic LOTO with low voltage"
    )


def find_witness_steps(steps: list[dict]) -> list[str]:
    """Return list of step IDs that have requires_witness=true.

    Recognizes truthy values: True, 'true', 'yes', 'TRUE', 'YES'.
    Step ID falls back to 'step_N' if not explicitly set.
    """
    witness_step_ids: list[str] = []
    for i, step in enumerate(steps):
        flag = step.get("requires_witness")
        if flag in (True, "true", "True", "TRUE", "yes", "Yes", "YES", 1):
            step_id = (
                step.get("id")
                or step.get("step_id")
                or step.get("name")
                or f"step_{i + 1}"
            )
            witness_step_ids.append(str(step_id))
    return witness_step_ids


# =============================================================================
#  Phase classification and order check (Pillar 5 support)
# =============================================================================

# Phase rank for sequential order check.
# Lower rank steps must come BEFORE higher rank steps.
# OTHER and VERIFICATION are rank 0 - they don't constrain ordering.
def get_phase_rank(phase: Any) -> int:
    """Return rank for a LotoPhase enum. ELECTRICAL=1, HYDRAULIC=2, PURGE=3."""
    from loto_auditor_models import LotoPhase  # late import
    rank_map = {
        LotoPhase.OTHER: 0,
        LotoPhase.VERIFICATION: 0,
        LotoPhase.ELECTRICAL_ISOLATION: 1,
        LotoPhase.HYDRAULIC_ISOLATION: 2,
        LotoPhase.PURGE: 3,
    }
    return rank_map.get(phase, 0)


def classify_step_phase(step: dict) -> Any:
    """Classify a procedure step into a LotoPhase enum.

    Strategy:
      1. Explicit 'phase' field in step (highest priority)
      2. Keyword match on step text against ELECTRICAL/HYDRAULIC/PURGE keywords
      3. Verification keyword match (verify, voltmeter, test, check absence)
      4. Default: LotoPhase.OTHER

    Returns LotoPhase enum value.
    """
    from loto_auditor_models import LotoPhase  # late import

    # Explicit phase field
    phase_raw = step.get("phase")
    if phase_raw is not None:
        try:
            return LotoPhase(str(phase_raw).lower().strip())
        except ValueError:
            log.debug("Unknown explicit phase value: %r", phase_raw)

    text = step_text(step)

    # Verification keywords (allowed at any position)
    if any(kw in text for kw in (
        "verify", "voltmeter", "test absence", "test for voltage",
        "verify zero", "verify de-energized", "verify de-energised",
        "absence of voltage",
    )):
        return LotoPhase.VERIFICATION

    # Phase keywords (order matters: check most specific first)
    if any(kw in text for kw in PURGE_PHASE_KEYWORDS):
        return LotoPhase.PURGE
    if any(kw in text for kw in HYDRAULIC_PHASE_KEYWORDS):
        return LotoPhase.HYDRAULIC_ISOLATION
    if any(kw in text for kw in ELECTRICAL_PHASE_KEYWORDS):
        return LotoPhase.ELECTRICAL_ISOLATION

    return LotoPhase.OTHER


def verify_phase_order(phases: list[Any]) -> bool:
    """Verify ELECTRICAL precedes HYDRAULIC precedes PURGE.

    OTHER and VERIFICATION steps are skipped (rank 0).
    Equal ranks are allowed (multiple electrical steps in a row).

    Returns True if order respected, False if a higher-rank step
    appears before a lower-rank step (e.g. PURGE then HYDRAULIC).
    """
    last_rank = 0
    for phase in phases:
        rank = get_phase_rank(phase)
        if rank == 0:
            continue
        if rank < last_rank:
            return False
        last_rank = rank
    return True


def is_cooling_component_type(component_type: str) -> bool:
    """Return True if component type is part of cooling subsystem."""
    if not component_type:
        return False
    type_lower = component_type.lower().strip()
    return type_lower in (
        "chiller",
        "cdu",
        "cooling_tower",
        "chw_pump",
        "manifold",
        "secondary_pump",
        "primary_pump",
        "heat_exchanger",
    )


# =============================================================================
#  PPE Category computation (Pillar 6 support)
# =============================================================================

def compute_ppe_category(voltage_nominal: float) -> Any:
    """Compute required PPE category from voltage (NFPA 70E §130 conservative).

    Voltage matrix (no IEEE 1584 calc - that is V10 ADR-010 deferred):
      < 50V    -> CAT 0  (no PPE required)
      50-600V  -> CAT 2  (covers A3-Alpha 480 VAC trifásico Phase 1)
      600-1000V -> CAT 3 (covers Building D 800 VDC Phase 2)
      >= 1000V -> CAT 4  (MV switchgear)

    NOTE: this is FLOOR not ceiling. Real IEEE 1584 might require higher
    category if short-circuit current is large. The audit warns CETs to
    escalate via real arc-flash study if calculated incident energy
    exceeds the voltage-matrix category threshold.
    """
    from loto_auditor_models import PPECategory  # late import

    if voltage_nominal < 50.0:
        return PPECategory.CAT_0
    if voltage_nominal < 600.0:
        return PPECategory.CAT_2
    if voltage_nominal < 1000.0:
        return PPECategory.CAT_3
    return PPECategory.CAT_4


def parse_ppe_category_from_procedure(procedure: Any) -> Optional[Any]:
    """Extract PPE category from procedure metadata or step text.

    Search order:
      1. procedure.metadata['ppe_category'] (explicit field)
      2. step['ppe_category'] in any step (explicit field)
      3. text regex match: 'cat 4', 'category 4', 'cat-4', 'category iv'

    Returns PPECategory enum or None if not found.
    """
    from loto_auditor_models import PPECategory  # late import

    # 1. Procedure metadata
    metadata = getattr(procedure, "metadata", {}) or {}
    if "ppe_category" in metadata:
        try:
            return PPECategory(int(metadata["ppe_category"]))
        except (ValueError, TypeError):
            log.debug("Bad ppe_category in metadata: %r", metadata["ppe_category"])

    steps = getattr(procedure, "steps", []) or []

    # 2. Step explicit field
    for step in steps:
        if "ppe_category" in step:
            try:
                return PPECategory(int(step["ppe_category"]))
            except (ValueError, TypeError):
                log.debug("Bad ppe_category in step: %r", step["ppe_category"])

    # 3. Text regex
    roman_to_int = {"i": 1, "ii": 2, "iii": 3, "iv": 4}
    pattern = re.compile(
        r"(?:ppe\s*)?cat(?:egory)?\s*[-]?\s*(0|1|2|3|4|iv|iii|ii|i)\b",
        re.IGNORECASE,
    )

    for step in steps:
        text = step_text(step)
        match = pattern.search(text)
        if match:
            value = match.group(1).lower()
            if value in roman_to_int:
                try:
                    return PPECategory(roman_to_int[value])
                except (ValueError, TypeError):
                    continue
            try:
                return PPECategory(int(value))
            except (ValueError, TypeError):
                continue

    return None
