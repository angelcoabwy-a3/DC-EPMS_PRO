import sys
sys.path.insert(0, "backend")
from site_model import SiteModel
from pathlib import Path

sm = SiteModel(yaml_path=Path("config/site_model.yml"))
sm.load()

# Try the public methods to see their return shapes
print("=== list_components() ===")
comps = sm.list_components()
print(f"  type: {type(comps).__name__}, count: {len(comps)}")
print(f"  first item type: {type(comps[0]).__name__}")
print(f"  first item: {comps[0]}")
print()

print("=== get_component('chiller_1') ===")
c = sm.get_component('chiller_1')
print(f"  type: {type(c).__name__}")
print(f"  attrs: {[a for a in dir(c) if not a.startswith('_')]}")
print(f"  raw repr: {c}")
print()

print("=== buildings_summary() ===")
bs = sm.buildings_summary()
print(f"  type: {type(bs).__name__}")
import json
print(f"  preview: {json.dumps(bs[:1] if isinstance(bs, list) else bs, indent=2, default=str)[:600]}")
print()

print("=== power_chain_for('rack_a_01_01') ===")
pc = sm.power_chain_for('rack_a_01_01')
print(f"  type: {type(pc).__name__}")
print(f"  preview: {json.dumps(pc, indent=2, default=str)[:500]}")
