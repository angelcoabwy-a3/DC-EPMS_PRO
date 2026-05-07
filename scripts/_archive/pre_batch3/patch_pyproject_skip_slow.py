"""
patch_pyproject_skip_slow.py

Adds '-m', 'not slow' to the addopts list in pyproject.toml so that
slow tests (including the FAISS AVX2 crashers on AMD+Windows) are
excluded from default `pytest` runs.

Run: python patch_pyproject_skip_slow.py

Idempotent: detects if patch already applied, exits with status.
"""

import sys
from pathlib import Path

PYPROJECT = Path("pyproject.toml")

if not PYPROJECT.exists():
    print("ERROR: pyproject.toml not found in current directory")
    sys.exit(1)

content = PYPROJECT.read_text(encoding="utf-8")

# The exact anchor we are looking for
ANCHOR = '  "--timeout-method=thread",\n]'

# What it should become
REPLACEMENT = '  "--timeout-method=thread",\n  "-m", "not slow",\n]'

# Idempotency check
if '"-m", "not slow",' in content:
    print("INFO: Patch already applied (pyproject.toml already excludes slow tests)")
    print("No changes made.")
    sys.exit(0)

if ANCHOR not in content:
    print("ERROR: Anchor string not found in pyproject.toml")
    print(f"Looking for: {ANCHOR!r}")
    print()
    print("Showing addopts section for diagnosis:")
    # Print the addopts block for diagnosis
    if "addopts = [" in content:
        start = content.index("addopts = [")
        end = content.index("]", start) + 1
        print(content[start:end])
    sys.exit(2)

# Apply patch
new_content = content.replace(ANCHOR, REPLACEMENT, 1)

# Verify only one replacement happened
if new_content.count(REPLACEMENT) != 1:
    print(f"ERROR: Expected exactly 1 replacement, got {new_content.count(REPLACEMENT)}")
    sys.exit(3)

PYPROJECT.write_text(new_content, encoding="utf-8")

print("SUCCESS: Patch applied to pyproject.toml")
print()
print("Resulting addopts section:")
start = new_content.index("addopts = [")
end = new_content.index("]", start) + 1
print(new_content[start:end])
print()
print("Slow tests now excluded by default. To include them, run:")
print("  pytest -m slow")
print("Or to include all tests:")
print("  pytest -m \"\"")
