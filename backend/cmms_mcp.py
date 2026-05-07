"""
cmms_mcp.py â€” Paperclip orchestrator + CMMS work-order draft tool.

Production-ready v8.1 module. Drop-in compatible with v8.0
agent_copilot.py: registers a fourth tool `draft_cmms_work_order` that
generates Microsoft CO+I-style maintenance work orders with:

  - Deterministic LOR (Level of Risk) computation
  - Deterministic procedure selection (SOP / MOP / DMOP / EOP)
  - Rule-based THA (Task Hazard Analysis) generation
  - Auto-escalation when thermal derivative is critical
  - MSOW + EMPS contractor attachments above $5k threshold

Decision logic is intentionally NOT LLM-mediated. The LLM's role is
limited to dispatching this tool with the operator's natural-language
request mapped to its parameters; LOR, procedure class, and THA are
all rule-based for IEC 62443 SR 6.1 auditability. A hallucinated
LOTO bypass would be a safety violation; deterministic rules cannot
hallucinate.

Honest scope notes:
  - `_fetch_thermal_derivative()` is a stub returning None until v8.1
    sprint adds the streaming derivative service. With None, the
    auto-escalation branch is never triggered, which is the
    conservative default (operator's hint is respected).
  - The Paperclip YAML at config/paperclip_org.yml is loaded at
    import time. If unavailable, hardcoded defaults take over and
    a warning is logged. The platform does not fail to boot.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import yaml

log = logging.getLogger(__name__)

# Sprint S1b: site model enrichment for WO drafts (fail-soft)
try:
    from cmms_site_enrichment import enrich_wo_with_location
    _SITE_ENRICHMENT_AVAILABLE = True
except ImportError:
    _SITE_ENRICHMENT_AVAILABLE = False


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  Paperclip org config â€” loaded at import, with fallback
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_PAPERCLIP_YAML_PATH = Path(__file__).parent.parent / "config" / "paperclip_org.yml"

PAPERCLIP_ORG: dict = {}
try:
    with open(_PAPERCLIP_YAML_PATH, encoding="utf-8") as _f:
        PAPERCLIP_ORG = yaml.safe_load(_f) or {}
    log.info("[v8.1] Paperclip org loaded from %s", _PAPERCLIP_YAML_PATH)
except FileNotFoundError:
    log.warning(
        "[v8.1] Paperclip YAML not found at %s â€” using hardcoded defaults",
        _PAPERCLIP_YAML_PATH,
    )
except yaml.YAMLError as e:
    log.error("[v8.1] Paperclip YAML parse failed: %s â€” using hardcoded defaults", e)


def _yaml_get(path: list, default):
    """Safely traverse PAPERCLIP_ORG with a list of keys."""
    cursor = PAPERCLIP_ORG
    for key in path:
        if not isinstance(cursor, dict) or key not in cursor:
            return default
        cursor = cursor[key]
    return cursor


# Conservative defaults (used if YAML unavailable)
DEFAULT_COST_THRESHOLD_USD = float(
    _yaml_get(["routing", "cost_threshold_usd"], 5000.0)
)
DEFAULT_LOTO_LOR_THRESHOLD = int(
    _yaml_get(["routing", "loto_required_threshold_lor"], 3)
)
THERMAL_CRITICAL_DT_K_PER_S = float(
    _yaml_get(["routing", "emergency_threshold_thermal_dt", "critical"], 0.5)
)
THERMAL_WARNING_DT_K_PER_S = float(
    _yaml_get(["routing", "emergency_threshold_thermal_dt", "warning"], 0.1)
)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  PURE FUNCTION 1 â€” LOR (Level of Risk) computation
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def compute_lor(
    likelihood_idx: int,
    consequence_idx: int,
    redundancy_mode: str,
) -> tuple[int, dict]:
    """Composite LOR score per Microsoft CO+I-style risk matrix.

    Args:
        likelihood_idx:  1..5 â€” failure likelihood if no action taken
        consequence_idx: 1..5 â€” severity if failure occurs
        redundancy_mode: "2N" | "N+1" | "N"

    Returns:
        (lor_int, breakdown_dict) where lor_int âˆˆ [1, 5] and the
        breakdown captures the full computation for board review.

    Math:
        LOR = clamp( (L Ã— C) / 5 + redundancy_modifier , 1, 5 )

    Raises:
        ValueError: if likelihood_idx or consequence_idx out of [1, 5]
    """
    if not (1 <= likelihood_idx <= 5):
        raise ValueError(
            f"likelihood_idx out of range [1, 5]: got {likelihood_idx}"
        )
    if not (1 <= consequence_idx <= 5):
        raise ValueError(
            f"consequence_idx out of range [1, 5]: got {consequence_idx}"
        )

    redundancy_mod = {"2N": -1, "N+1": 0, "N": +1}.get(redundancy_mode, 0)
    raw = (likelihood_idx * consequence_idx) / 5.0
    lor = max(1, min(5, int(round(raw + redundancy_mod))))

    return lor, {
        "likelihood_idx": likelihood_idx,
        "consequence_idx": consequence_idx,
        "redundancy_mode": redundancy_mode,
        "redundancy_modifier": redundancy_mod,
        "raw_score": round(raw, 2),
        "lor_final": lor,
        "rationale": (
            f"L={likelihood_idx} x C={consequence_idx} = "
            f"{likelihood_idx * consequence_idx} / 5 = {raw:.2f}, "
            f"then {redundancy_mod:+d} for {redundancy_mode} redundancy "
            f"-> LOR {lor}"
        ),
    }


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  PURE FUNCTION 2 â€” Procedure class selection (SOP/MOP/DMOP/EOP)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def select_procedure_class(
    work_class: str,
    lor: int,
    thermal_derivative_k_per_s: Optional[float],
    requires_loto: bool,
) -> str:
    """Pick exactly one procedure class. Decision tree, not LLM.

    Why deterministic: an LLM picking SOP vs DMOP would be a
    catastrophic failure mode (LOTO bypass via hallucination).

    Order of precedence (most restrictive wins):
      1. thermal_derivative >= critical -> EOP (overrides everything)
      2. requires_loto OR lor >= 3      -> DMOP
      3. work_class == "EM"             -> EOP
      4. work_class == "CM"             -> MOP
      5. work_class == "PM"             -> SOP
    """
    # Rule 1: thermal emergency overrides everything
    if thermal_derivative_k_per_s is not None:
        if abs(thermal_derivative_k_per_s) >= THERMAL_CRITICAL_DT_K_PER_S:
            return "EOP"

    # Rule 2: LOTO requirement trumps work class for safety
    if requires_loto or lor >= DEFAULT_LOTO_LOR_THRESHOLD:
        return "DMOP"

    # Rules 3-5: work class determines default
    if work_class == "EM":
        return "EOP"
    if work_class == "CM":
        return "MOP"
    if work_class == "PM":
        return "SOP"

    # Defensive: unknown work_class -> most restrictive
    return "DMOP"


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  PURE FUNCTION 3 â€” THA (Task Hazard Analysis) generation
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
_BASE_HAZARDS_BY_KIND: dict[str, list[str]] = {
    "ups":      ["arc_flash_cat_2", "stored_dc_energy", "battery_acid_exposure"],
    "chiller":  ["refrigerant_release_a2l", "rotating_equipment", "high_pressure_lines"],
    "rpp":      ["arc_flash_cat_3", "shock_277V_to_ground"],
    "cdu":      ["propylene_glycol_skin_contact", "rotating_equipment_pump"],
    "busway":   ["arc_flash_cat_2", "shock_480V_three_phase"],
    "xfmr":     ["arc_flash_cat_4", "induced_voltage", "oil_release"],
    "genset":   ["co_exposure", "high_temperature_exhaust", "fuel_release"],
    "hall":     ["arc_flash_cat_2", "high_density_compute_thermal"],
    "utility":  ["arc_flash_cat_4", "medium_voltage_27_5kV"],
}

_PPE_CATEGORY_LABELS = {
    0: "minimum",
    1: "category_1",
    2: "category_2",
    3: "category_3",
    4: "category_4",
}


def generate_tha(
    component_id: str,
    procedure_class: str,
    lor: int,
    component_kind: str,
) -> dict:
    """Construct a structured THA payload.

    Hazards are rule-derived from component_kind + procedure_class.
    INTENTIONALLY not LLM-generated â€” THA omissions have caused
    deaths in the field. A deterministic generator is auditable.
    """
    component_kind_clean = component_kind.lower().split("_")[0]
    hazards = list(
        _BASE_HAZARDS_BY_KIND.get(
            component_kind_clean, ["unknown_hazards_review_required"]
        )
    )

    # Procedure-specific hazards (additive)
    if procedure_class == "DMOP":
        hazards.append("loto_isolation_verification_required")
        hazards.append("residual_energy_dissipation_check")
    elif procedure_class == "EOP":
        hazards.append("time_pressure_decision_fatigue")
        hazards.append("post_event_review_mandatory")

    # PPE level scales with the highest arc-flash category in the hazards
    arc_flash_max_cat = 0
    for h in hazards:
        if h.startswith("arc_flash_cat_"):
            try:
                cat = int(h.rsplit("_", 1)[1])
                arc_flash_max_cat = max(arc_flash_max_cat, cat)
            except (ValueError, IndexError):
                continue

    ppe_level = _PPE_CATEGORY_LABELS.get(arc_flash_max_cat, "category_4")

    return {
        "component_id": component_id,
        "component_kind": component_kind,
        "procedure_class": procedure_class,
        "lor": lor,
        "hazards": hazards,
        "ppe_level": ppe_level,
        "two_person_rule_required": (
            procedure_class in ("DMOP", "EOP") or lor >= 3
        ),
        "standards": ["NFPA_70E", "CSA_Z462", "OSHA_1910_269"],
        "_authoring_method": "deterministic_rule_based",
        "_review_required_by": "operator_certified_qualified_electrical_worker",
    }


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  PURE FUNCTION 4 â€” Contractor attachments (MSOW / EMPS)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def determine_contractor_attachments(
    estimated_cost_usd: float,
    requires_oem_specialist: bool,
    procedure_class: str,
) -> dict:
    """Decide whether to attach MSOW (master agreement) and EMPS
    (task-specific procedure statement) for contractor work."""
    needs_contractor = (
        estimated_cost_usd >= DEFAULT_COST_THRESHOLD_USD
        or requires_oem_specialist
    )
    if not needs_contractor:
        return {"contractor_required": False}

    return {
        "contractor_required": True,
        "msow_attached": True,
        "msow_doc_id": "DRAFT_MSOW_FROM_TEMPLATE",
        "emps_attached": True,
        "emps_doc_id": "DRAFT_EMPS_FROM_TEMPLATE",
        "pre_brief_required": procedure_class in ("DMOP", "EOP", "MOP"),
        "two_person_oversight": procedure_class in ("DMOP", "EOP"),
        "_note": (
            "MSOW/EMPS docs are TEMPLATES. The board fills in vendor, "
            "schedule, and final cost during approval. Drafts cannot "
            "commit contractual terms."
        ),
    }


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  PURE FUNCTION 5 â€” SLA review hours by work class
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def sla_review_hours_for(work_class: str) -> int:
    """Board review SLA in hours, per CMMS taxonomy."""
    return {"PM": 72, "CM": 24, "EM": 1}.get(work_class, 72)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  PURE FUNCTION 6 â€” Thermal derivative fetcher (stub for v8.1 sprint)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
async def _fetch_thermal_derivative(component_id: str) -> Optional[float]:
    """Pull the latest thermal derivative dT/dt for the component.

    Stub returning None until v8.1 sprint integrates the streaming
    derivative service from cyber_physical_tools.py. With None, the
    auto-escalation branch in tool_draft_cmms_work_order is never
    triggered â€” the conservative default that preserves the
    operator-supplied work_class hint.
    """
    return None


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  Tool schema (OpenAI / MCP compatible)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
DRAFT_CMMS_WORK_ORDER_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": "draft_cmms_work_order",
        "description": (
            "Generate a CMMS work-order draft for scheduled or corrective "
            "maintenance. Returns a draft_id; board approval at the HMI "
            "is required before any contractor dispatch or BMS write "
            "occurs. Use this when the operator describes a maintenance "
            "need; the tool selects work_class (PM/CM/EM), computes LOR, "
            "picks the procedure class (SOP/MOP/DMOP/EOP), generates the "
            "THA, and decides on contractor attachments (MSOW/EMPS)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "component_id": {
                    "type": "string",
                    "description": (
                        "Canonical component identifier from the unified "
                        "graph (e.g. 'ups_a', 'chiller_1', 'rpp_b2')"
                    ),
                },
                "issue_summary": {
                    "type": "string",
                    "description": "One-sentence description of the maintenance need",
                },
                "work_class_hint": {
                    "type": "string",
                    "enum": ["PM", "CM", "EM"],
                    "description": (
                        "Operator's intent. PM=preventive scheduled, "
                        "CM=corrective with active impairment, "
                        "EM=emergency with imminent failure. The tool "
                        "may escalate but never de-escalate."
                    ),
                },
                "likelihood_idx": {
                    "type": "integer",
                    "description": "1..5 likelihood of failure if no action",
                },
                "consequence_idx": {
                    "type": "integer",
                    "description": "1..5 consequence severity if failure occurs",
                },
                "estimated_cost_usd": {
                    "type": "number",
                    "description": "Estimated total cost including parts and labor",
                },
                "requires_loto": {
                    "type": "boolean",
                    "description": "Whether de-energization is needed",
                },
                "requires_oem_specialist": {
                    "type": "boolean",
                    "description": "True if OEM-certified contractor needed",
                },
            },
            "required": [
                "component_id",
                "issue_summary",
                "work_class_hint",
                "likelihood_idx",
                "consequence_idx",
            ],
        },
    },
}


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  THE TOOL â€” async dispatch combining the 6 pure functions
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
async def tool_draft_cmms_work_order(args: dict) -> dict:
    """The dispatch logic. Composed of pure functions above so each
    step is unit-testable independently of the LLM."""

    # â”€â”€ Argument parsing with validation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    component_id = str(args.get("component_id", "")).strip()
    if not component_id:
        return {"error": "component_id required"}

    issue_summary = str(args.get("issue_summary", "")).strip()
    work_class_hint = str(args.get("work_class_hint", "PM")).upper()
    if work_class_hint not in ("PM", "CM", "EM"):
        return {"error": f"work_class_hint must be PM/CM/EM, got '{work_class_hint}'"}

    try:
        likelihood_idx = int(args.get("likelihood_idx", 3))
        consequence_idx = int(args.get("consequence_idx", 3))
    except (TypeError, ValueError):
        return {"error": "likelihood_idx and consequence_idx must be integers 1..5"}

    estimated_cost_usd = float(args.get("estimated_cost_usd", 0.0) or 0.0)
    requires_loto = bool(args.get("requires_loto", False))
    requires_oem = bool(args.get("requires_oem_specialist", False))

    # â”€â”€ Step 1: Pull current site state to ground LOR in reality â”€â”€â”€â”€â”€
    try:
        from agent_copilot import tool_query_unified_graph
    except ImportError:
        return {"error": "agent_copilot.tool_query_unified_graph unavailable"}

    state = await tool_query_unified_graph({"device_id": component_id})
    if "error" in state:
        return state

    redundancy_mode = state.get("site_redundancy_mode", "2N")
    component_kind = component_id.split("_")[0] if "_" in component_id else component_id

    # â”€â”€ Step 2: Compute LOR â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    try:
        lor, lor_breakdown = compute_lor(
            likelihood_idx=likelihood_idx,
            consequence_idx=consequence_idx,
            redundancy_mode=redundancy_mode,
        )
    except ValueError as e:
        return {"error": f"LOR computation failed: {e}"}

    # â”€â”€ Step 3: Pull thermal derivative (stub returns None today) â”€â”€â”€â”€
    thermal_dt = await _fetch_thermal_derivative(component_id)

    # If thermal derivative is critical, auto-escalate work_class to EM
    work_class = work_class_hint
    escalation_reason: Optional[str] = None
    if thermal_dt is not None and abs(thermal_dt) >= THERMAL_CRITICAL_DT_K_PER_S:
        work_class = "EM"
        escalation_reason = (
            f"Thermal derivative {thermal_dt:+.3f} K/s >= "
            f"{THERMAL_CRITICAL_DT_K_PER_S} K/s critical threshold. "
            f"Work class escalated from {work_class_hint} to EM."
        )

    # â”€â”€ Step 4: Procedure class selection (deterministic) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    procedure_class = select_procedure_class(
        work_class=work_class,
        lor=lor,
        thermal_derivative_k_per_s=thermal_dt,
        requires_loto=requires_loto,
    )

    # â”€â”€ Step 5: THA generation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    tha = generate_tha(
        component_id=component_id,
        procedure_class=procedure_class,
        lor=lor,
        component_kind=component_kind,
    )

    # â”€â”€ Step 6: Contractor attachments â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    contractor = determine_contractor_attachments(
        estimated_cost_usd=estimated_cost_usd,
        requires_oem_specialist=requires_oem,
        procedure_class=procedure_class,
    )

    # â”€â”€ Step 7: SLA hours from work_class taxonomy â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    sla_hours = sla_review_hours_for(work_class)

    # â”€â”€ Step 8: Persist as Draft (same DraftStore as v8.0) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    try:
        from agent_copilot import DraftStore
    except ImportError:
        return {"error": "agent_copilot.DraftStore unavailable"}

    draft = DraftStore.create(
        kind="cmms_work_order",
        commands=[],
        rationale=(
            f"CMMS WO for {component_id}: {issue_summary}. "
            f"Class {work_class}, LOR {lor}, procedure {procedure_class}, "
            f"SLA {sla_hours}h."
            + (f" {escalation_reason}" if escalation_reason else "")
        ),
        metadata={
            "work_class": work_class,
            "work_class_hint": work_class_hint,
            "escalation_reason": escalation_reason,
            "lor": lor,
            "lor_breakdown": lor_breakdown,
            "procedure_class": procedure_class,
            "tha": tha,
            "contractor": contractor,
            "thermal_derivative_k_per_s": thermal_dt,
            "estimated_cost_usd": estimated_cost_usd,
            "sla_review_hours": sla_hours,
            "site_redundancy_mode": redundancy_mode,
            "issue_summary": issue_summary,
        },
        ttl_s=sla_hours * 3600,
    )

    result = {
        "draft_id": draft.draft_id,
        "kind": "cmms_work_order",
        "status": "PENDING_BOARD_APPROVAL",
        "component_id": component_id,
        "issue_summary": issue_summary,
        "work_class": work_class,
        "work_class_was_escalated": escalation_reason is not None,
        "escalation_reason": escalation_reason,
        "lor": lor,
        "lor_breakdown": lor_breakdown,
        "procedure_class": procedure_class,
        "tha_summary": {
            "hazards": tha["hazards"],
            "ppe_level": tha["ppe_level"],
            "two_person_rule": tha["two_person_rule_required"],
            "standards": tha["standards"],
        },
        "contractor": contractor,
        "sla_review_hours": sla_hours,
        "approval_endpoint": f"/api/agent/draft/{draft.draft_id}/approve",
        "rejection_endpoint": f"/api/agent/draft/{draft.draft_id}/reject",
        "_human_in_the_loop_note": (
            "This work order will not be dispatched to CMMS until the "
            "board approves at the HMI. The board may modify LOR, "
            "procedure_class, or reject â€” all modifications feed the "
            "DPO learning loop in dpo_edge_healing.py (Phase 2)."
        ),
        "_provenance": {
            "lor_computation": "deterministic_rule_based",
            "procedure_selection": "deterministic_decision_tree",
            "tha_generation": "deterministic_rule_based",
            "llm_role": "summarisation_and_dispatch_only",
        },
    }

    # Sprint S1b: enrich with site_model location/breadcrumb (fail-soft)
    if _SITE_ENRICHMENT_AVAILABLE:
        try:
            result = enrich_wo_with_location(result, component_id)
        except Exception as _e:
            log.warning(f"[cmms_mcp] site enrichment skipped: {_e}")

    return result
