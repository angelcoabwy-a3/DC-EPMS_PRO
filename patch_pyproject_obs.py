"""
patch_pyproject_obs.py

Adds 'prometheus-fastapi-instrumentator>=7.0.0,<8.0.0' to the [obs] extra
in pyproject.toml. This is required for the Docker container to install
the package during build. Without this, setup_metrics() degrades gracefully
to no-op, leaving /metrics endpoint absent.

Idempotent: detects existing entry, no duplicate adds.
BOM-aware. Handles 3 scenarios:
  A. [obs] extra doesn't exist -> create it
  B. [obs] exists but missing the package -> add it
  C. Already has the package -> no changes

Run: python patch_pyproject_obs.py
"""

from __future__ import annotations

import re
import sys
import tomllib
from datetime import datetime
from pathlib import Path

PYPROJECT = Path("pyproject.toml")
BOM = "\ufeff"
TARGET_PKG = "prometheus-fastapi-instrumentator"
TARGET_PIN = '"prometheus-fastapi-instrumentator>=7.0.0,<8.0.0"'

if not PYPROJECT.exists():
    print(f"ERROR: {PYPROJECT} not found")
    sys.exit(1)

raw = PYPROJECT.read_bytes()
has_bom = raw.startswith(b"\xef\xbb\xbf")
content = raw.decode("utf-8-sig") if has_bom else raw.decode("utf-8")

if has_bom:
    print("INFO: UTF-8 BOM detected. Will preserve.")

# ── Idempotency check ──────────────────────────────────────────────────────
if TARGET_PKG in content:
    print(f"INFO: {TARGET_PKG} already in pyproject.toml. No changes.")
    sys.exit(0)

# ── Backup ─────────────────────────────────────────────────────────────────
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = PYPROJECT.with_name(f"pyproject.toml.bak_pre_obs_fix_{ts}")
backup.write_bytes(raw)
print(f"Backup created: {backup.name}")

# ── Parse current state to determine scenario ──────────────────────────────
parsed = tomllib.loads(content.lstrip(BOM))
optional_deps = parsed.get("project", {}).get("optional-dependencies", {})
obs_exists = "obs" in optional_deps
current_obs = optional_deps.get("obs", [])

print(f"Current [obs] extra: {current_obs if obs_exists else 'DOES NOT EXIST'}")

# ── Scenario A: [obs] doesn't exist - create it ────────────────────────────
if not obs_exists:
    print("Scenario A: creating [obs] extra")
    
    # Find the [project.optional-dependencies] section
    section_re = re.compile(
        r'(\[project\.optional-dependencies\][^\[]*?)(\n\[|\Z)',
        re.MULTILINE | re.DOTALL,
    )
    match = section_re.search(content)
    if not match:
        print("ERROR: [project.optional-dependencies] section not found")
        sys.exit(2)
    
    section_end = match.end(1)
    
    # Insert obs extra at the end of the section
    new_extra = (
        f'\n# Observability stack (Batch 2 - Prometheus instrumentation)\n'
        f'obs = [\n'
        f'  {TARGET_PIN},\n'
        f']\n'
    )
    
    content = content[:section_end] + new_extra + content[section_end:]
    print(f"  Added new [obs] extra with {TARGET_PKG}")

# ── Scenario B: [obs] exists but missing package - add to existing ─────────
else:
    print("Scenario B: adding to existing [obs] extra")
    
    # Find the obs = [ ... ] block
    obs_pattern = re.compile(
        r'(obs\s*=\s*\[\s*\n)',
        re.MULTILINE,
    )
    match = obs_pattern.search(content)
    if not match:
        print("ERROR: 'obs = [' pattern not found despite tomllib seeing it")
        print("Manual edit required.")
        sys.exit(3)
    
    insert_pos = match.end()
    new_line = f'  {TARGET_PIN},\n'
    content = content[:insert_pos] + new_line + content[insert_pos:]
    print(f"  Added {TARGET_PKG} to [obs]")

# ── Validate TOML syntax ──────────────────────────────────────────────────
try:
    tomllib.loads(content.lstrip(BOM))
    print("  [TOML] Syntax validation PASSED")
except tomllib.TOMLDecodeError as e:
    print(f"ERROR: Patch produced invalid TOML: {e}")
    print("File NOT written. Backup preserved.")
    sys.exit(4)

# ── Verify the new state ──────────────────────────────────────────────────
parsed_new = tomllib.loads(content.lstrip(BOM))
new_obs = parsed_new["project"]["optional-dependencies"]["obs"]
if not any(TARGET_PKG in item for item in new_obs):
    print(f"ERROR: {TARGET_PKG} not in [obs] after patch (parsing inconsistency)")
    sys.exit(5)

print(f"  Final [obs] extra: {new_obs}")

# ── Write back, preserving BOM ─────────────────────────────────────────────
if has_bom and not content.startswith(BOM):
    content = BOM + content

PYPROJECT.write_bytes(content.encode("utf-8"))

print()
print("SUCCESS: pyproject.toml patched.")
print(f"  Added: {TARGET_PIN}")
print(f"  BOM preserved: {has_bom}")
print()
print("Next steps:")
print("  1. Rebuild container:")
print("     docker build --no-cache --target runtime -t dc-epms-pro:latest .")
print("  2. Re-validate:")
print("     .\\validate_batch2.ps1")
