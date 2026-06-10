"""
patch_pyproject_torch_cpu.py

Adds explicit torch CPU-only pin to the [rag] extra in pyproject.toml
to prevent pip from auto-resolving torch with bundled CUDA (which
adds ~3.5 GB of cuda-toolkit, cuda-bindings, cuda-pathfinder dependencies
to the runtime image).

V9 architectural decision (2026-05-06): runtime container is CPU-only.
GPU usage in V9 is limited to:
  - LM Studio (runs on host, outside container)
  - DPO LoRA training (CPU bitsandbytes per Decision D-B)
  - Numba @njit (CPU-bound by definition)

Idempotent. BOM-aware. Backup created.

Run: python patch_pyproject_torch_cpu.py
"""

from __future__ import annotations

import re
import sys
import tomllib
from datetime import datetime
from pathlib import Path

PYPROJECT = Path("pyproject.toml")
BOM = "\ufeff"

if not PYPROJECT.exists():
    print(f"ERROR: {PYPROJECT} not found")
    sys.exit(1)

# Read with BOM detection
raw = PYPROJECT.read_bytes()
has_bom = raw.startswith(b"\xef\xbb\xbf")
content = raw.decode("utf-8-sig") if has_bom else raw.decode("utf-8")
original = content

if has_bom:
    print("INFO: UTF-8 BOM detected. Will preserve in output.")

# Idempotency check
if "torch>=2.0.0,<3.0.0" in content or '"torch>' in content:
    print("INFO: torch already pinned in pyproject.toml. No changes.")
    sys.exit(0)

# Backup
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = PYPROJECT.with_name(f"pyproject.toml.bak_pre_torch_cpu_{ts}")
backup.write_bytes(raw)
print(f"Backup created: {backup.name}")

# Strategy: find the [rag] extra in [project.optional-dependencies] and
# inject torch as the FIRST item. We want pip to resolve torch CPU-only
# before it resolves sentence-transformers (which would auto-pull cuda torch).
#
# Looking for pattern like:
#   rag = [
#     "chromadb==0.5.18",
#     "sentence-transformers==3.2.1",
#     ...
#   ]

rag_pattern = re.compile(
    r"(rag\s*=\s*\[\s*\n)",  # capture the opening
    re.MULTILINE,
)

match = rag_pattern.search(content)
if not match:
    print("ERROR: Could not find 'rag = [' extras block in pyproject.toml")
    print("Manual edit required. Look for [project.optional-dependencies] section.")
    sys.exit(2)

# Insert torch as first item right after the [
insert_pos = match.end()
torch_pins = (
    '  "torch>=2.0.0,<3.0.0",  # CPU-only via Dockerfile --index-url. Prevents CUDA bloat.\n'
    '  "torchvision>=0.15.0,<1.0.0",\n'
)
content = content[:insert_pos] + torch_pins + content[insert_pos:]

# Validate TOML syntax with tomllib
try:
    tomllib.loads(content.lstrip(BOM))
    print("  [TOML] Syntax validation PASSED")
except tomllib.TOMLDecodeError as e:
    print(f"ERROR: Patch produced invalid TOML: {e}")
    sys.exit(3)

# Write back, preserving BOM
if has_bom and not content.startswith(BOM):
    content = BOM + content
PYPROJECT.write_bytes(content.encode("utf-8"))

print()
print("SUCCESS: pyproject.toml patched.")
print("  Added: torch>=2.0.0,<3.0.0 + torchvision>=0.15.0,<1.0.0 to [rag] extra")
print(f"  BOM preserved: {has_bom}")
print()
print("Verify with:")
print(
    "  python -c \"import tomllib; data=tomllib.loads(open('pyproject.toml','rb').read().decode('utf-8-sig')); print(data['project']['optional-dependencies']['rag'][:3])\""
)
