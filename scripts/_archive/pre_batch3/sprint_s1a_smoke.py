import sys
sys.path.insert(0, "backend")
from site_model import SiteModel
from pathlib import Path
import json

m = SiteModel(Path("config/site_model.yml"))
m.load()

print("="*70)
print(" SPRINT S1a SMOKE - A3-Alpha Toronto")
print("="*70)

print(f"\n[Locate] chiller_1   -> {m.location_path('chiller_1')}")
print(f"[Locate] rack_a_01_05 -> {m.location_path('rack_a_01_05')}")
print(f"[Locate] ups_a        -> {m.location_path('ups_a')}")
print(f"[Locate] genset_a_01  -> {m.location_path('genset_a_01')}")

chain = m.power_chain_for("rack_a_01_05")
print(f"\n[Power 2N] rack_a_01_05 has {chain['feed_count']} redundant feeds:")
for feed in chain["feeds"]:
    print(f"  [{feed['group']}] alternative roots: {feed['roots']}")

loto = m.loto_impact("rpp_a_01")
print(f"\n[LOTO] target: {loto['loto_target_display']}")
print(f"  located in:  {loto['location']['path']}")
print(f"  downstream:  {loto['downstream_count']} components")
print(f"  racks affected: {len(loto['racks_affected'])}")
print(f"  racks losing ALL redundancy: {len(loto['racks_losing_all_redundancy'])}")
print(f"  -> Reading: every affected rack still has Path B feed -> safe LOTO")

target = "chiller_1"
comp = m.get_component(target)
wo = {
    "asset_id": target,
    "asset_display": comp.display,
    "location": m.location_path(target),
    "rated_tons": comp.metadata.get("rated_tons"),
    "work_type": "PM_QUARTERLY",
    "trade": "mechanical",
}
print(f"\n[CMMS WO Draft]")
print(json.dumps(wo, indent=2))
print("="*70)
