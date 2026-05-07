import sys
sys.path.insert(0, "backend")
from site_model import SiteModel
from pathlib import Path

sm = SiteModel(yaml_path=Path("config/site_model.yml"))
sm.load()

# All public attributes
attrs = [a for a in dir(sm) if not a.startswith("_")]
print("Public attributes/methods:")
for a in sorted(attrs):
    obj = getattr(sm, a)
    kind = "method" if callable(obj) else type(obj).__name__
    print(f"  {a}: {kind}")
