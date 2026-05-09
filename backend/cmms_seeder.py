"""
backend/cmms_seeder.py
======================
One-shot asset registry seeder. Reads config/site_model.yml plus the
telemetry_simulator inventory, derives Tesla/SpaceX vision metadata
(path, redundancy_pillar, telemetry_channels, criticality_class, MOP
linkage), and idempotently upserts the result into the assets table.

Invoked from main.py lifespan startup. Idempotent: re-running on a
populated DB updates fields without duplicating rows.

Heuristic fallbacks documented inline. Operator can manually override
via PATCH /api/cmms/assets/{id} (Sprint 7+).
"""

from __future__ import annotations

import logging
from typing import Any

from backend.cmms_models import Asset
from backend.cmms_repository import PostgresCMMSRepository
from backend.site_model import SiteModel
from backend.telemetry_simulator import _CHANNELS_PER_TYPE  # type: ignore

log = logging.getLogger(__name__)


# ─── MOP linking heuristic (Tesla/SpaceX vision) ──────────────────────
# When Sprint 7 ships GraphRAG-driven resolver, this remains as fast
# primary lookup with graphrag fallback for unknown types.
ASSET_TYPE_TO_MOP: dict[str, str] = {
    "ups":       "T4-MOP-UPS-001",
    "chiller":   "T4-MOP-CHI-001",
    "ats":       "MOP-ATS-MONTHLY-001",
    # Other types: no executable MOP yet; will be NULL until added.
}


# ─── Criticality heuristic ────────────────────────────────────────────
# Failure of an UPS or chiller can take down the site. A workstation
# failure is annoying but non-critical. This drives WO priority
# escalation regardless of LOR.
ASSET_TYPE_CRITICALITY: dict[str, str] = {
    "ups":                "critical",
    "ats":                "critical",
    "chiller":            "critical",
    "transformer":        "critical",
    "switchgear":         "critical",
    "rectifier":          "critical",
    "utility_intake":     "critical",
    "genset":             "high",
    "rpp":                "high",
    "busway":             "high",
    "cdu":                "high",
    "pump":               "high",
    "cooling_tower_field": "high",
    "cooling_tower":      "high",
    "fuel_tank":          "medium",
    "it_rack":            "medium",
    "bms_panel":          "medium",
    "sensor":             "low",
    "workstation":        "low",
    "other":              "low",
}


# ─── Path heuristic from canonical_id pattern ─────────────────────────
def _derive_path(canonical_id: str, _meta: dict[str, Any]) -> str | None:
    """Path A vs Path B vs facility-wide.

    site_model.yml convention: components on Path A end in _a (or _a_NN
    for racks); Path B end in _b. Facility-wide components (utility,
    yard) return None. Phase 2 racks (Building D) tagged "_d_" are
    Path C2-P2; everything else Path 1 is C2-P1 by default.
    """
    cid = canonical_id.lower()
    if "_a_" in cid or cid.endswith("_a"):
        return "A"
    if "_b_" in cid or cid.endswith("_b"):
        return "B"
    if "_d_" in cid or cid.startswith("rack_d_"):
        return "C2-P2"
    return None


# ─── Redundancy pillar heuristic ──────────────────────────────────────
def _derive_redundancy_pillar(asset_type: str, _meta: dict[str, Any]) -> str | None:
    if asset_type in ("ups", "ats", "rpp", "busway", "transformer", "switchgear", "utility_intake"):
        return "2N"
    if asset_type in ("chiller", "pump", "cooling_tower_field", "cdu"):
        return "N+1"
    if asset_type in ("genset", "fuel_tank"):
        return "2N"
    if asset_type == "it_rack":
        return "2N"  # racks have two PDUs each per site_model.yml comments
    return None


# ─── Telemetry channels per asset (mapping to simulator) ──────────────
# The telemetry_simulator emits N channels per emitting component type.
# We construct the per-component channel id list as
# "<canonical_id>:<metric>" matching what the simulator's get_window()
# produces. This lets the predictive WO trigger snap an anomaly's
# channel id back to the asset.
def _derive_telemetry_channels(asset_type: str, canonical_id: str) -> list[str]:
    metrics_per_type = {
        "it_rack": ["rack_inlet_T_c", "gpu_Tj_c", "dlc_supply_T_c", "dlc_return_T_c"],
        "chiller": ["chiller_LWT_c", "chiller_cop"],
        "cdu":     ["cdu_supply_T_c", "cdu_flow_lpm"],
        "ups":     ["voltage_v_phase_ab", "voltage_v_phase_bc", "voltage_v_phase_ca",
                    "ups_soc_pct", "batt_runtime_min"],
        "pump":    ["pump_NPSH_margin_m", "pump_flow_gpm"],
        "cooling_tower_field": ["ecwt_c", "outdoor_wet_bulb_c"],
    }
    metrics = metrics_per_type.get(asset_type, [])
    return [f"{canonical_id}:{m}" for m in metrics]


# =====================================================================
#  Seeder entry point
# =====================================================================
async def seed_assets_from_site_model(
    repo: PostgresCMMSRepository,
    site_model: SiteModel,
) -> dict[str, int]:
    """Idempotent seed. Returns counters {created_or_updated, skipped}."""
    counters = {"upserted": 0, "skipped_no_type": 0}

    components = site_model.list_components()
    log.info("[cmms_seeder] starting seed: %d components in site_model", len(components))

    for comp in components:
        atype = comp.type
        if not atype or atype == "unknown":
            counters["skipped_no_type"] += 1
            continue

        # Map cooling_tower_field -> cooling_tower_field (already correct)
        # All site_model types align with our CHECK constraint.
        meta = comp.metadata or {}
        rated_kw = meta.get("rated_kw") or meta.get("rated_kva")  # kVA approx kW for transformers

        asset = Asset(
            asset_id=comp.canonical_id,
            display_name=comp.display,
            asset_type=atype if atype in (
                "ups","chiller","cdu","pump","cooling_tower_field","cooling_tower",
                "genset","transformer","switchgear","ats","rpp","busway",
                "utility_intake","fuel_tank","bms_panel","workstation","it_rack",
                "rectifier","sensor"
            ) else "other",
            facility="A3-Alpha Toronto Area",
            location_path=comp.location.path if comp.location else None,
            vendor=meta.get("vendor"),
            model=meta.get("model"),
            rated_capacity_kw=float(rated_kw) if rated_kw else None,
            rated_capacity_unit="kVA" if "rated_kva" in meta else "kW",
            path=_derive_path(comp.canonical_id, meta),
            redundancy_pillar=_derive_redundancy_pillar(atype, meta),
            telemetry_channels=_derive_telemetry_channels(atype, comp.canonical_id),
            criticality_class=ASSET_TYPE_CRITICALITY.get(atype, "medium"),
            linked_mop_id=ASSET_TYPE_TO_MOP.get(atype),
            health_state="healthy",
            metadata_json={k: v for k, v in meta.items()
                           if k not in ("vendor", "model", "rated_kw", "rated_kva")},
        )

        try:
            await repo.upsert_asset_async(asset)
            counters["upserted"] += 1
        except Exception as e:
            log.warning("[cmms_seeder] upsert failed for %s: %s", comp.canonical_id, e)

    log.info(
        "[cmms_seeder] complete: upserted=%d, skipped_no_type=%d",
        counters["upserted"],
        counters["skipped_no_type"],
    )
    return counters
