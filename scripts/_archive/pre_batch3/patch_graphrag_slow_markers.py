"""
patch_graphrag_slow_markers.py

Adds @pytest.mark.slow decorator to 2 tests in test_graphrag.py that
currently lack the marker but trigger FAISS loading (which crashes on
AMD+Windows hardware due to AVX2 access violation):
  - test_service_upstream
  - test_service_related_knowledge

These 2 tests use the same `service` fixture as the other 3 already-marked
slow tests, so they should have been marked slow from the start.

Run: python patch_graphrag_slow_markers.py

Idempotent: detects if patch already applied, exits cleanly.
Backup: writes test_graphrag.py.bak_pre_slow_markers_<timestamp>
"""

import sys
from datetime import datetime
from pathlib import Path

TARGET = Path("tests/test_graphrag.py")

if not TARGET.exists():
    print(f"ERROR: {TARGET} not found")
    sys.exit(1)

# Backup first
ts = datetime.now().strftime("%Y%m%d_%H%M")
backup = TARGET.with_suffix(f".py.bak_pre_slow_markers_{ts}")

content = TARGET.read_text(encoding="utf-8", errors="replace")
TARGET.with_name(backup.name).write_text(content, encoding="utf-8")
print(f"Backup created: {backup.name}")

# Targets — exact patterns. Anchor on the function definition line preceded
# by a blank line.
PATTERNS = [
    {
        "name": "test_service_upstream",
        "find": "\ndef test_service_upstream(",
        "replace": "\n@pytest.mark.slow\ndef test_service_upstream(",
    },
    {
        "name": "test_service_related_knowledge",
        "find": "\ndef test_service_related_knowledge(",
        "replace": "\n@pytest.mark.slow\ndef test_service_related_knowledge(",
    },
]

original_content = content
applied = 0
already_marked = 0

for p in PATTERNS:
    # Idempotency: check if already preceded by @pytest.mark.slow
    already_pattern = "@pytest.mark.slow\n" + p["find"].lstrip("\n")
    if already_pattern in content:
        print(f"  [SKIP] {p['name']} — already marked @pytest.mark.slow")
        already_marked += 1
        continue

    if p["find"] not in content:
        print(f"  [WARN] {p['name']} — anchor not found in file")
        continue

    # Verify only one occurrence
    count = content.count(p["find"])
    if count != 1:
        print(f"  [ERROR] {p['name']} — found {count} occurrences (expected 1)")
        sys.exit(2)

    content = content.replace(p["find"], p["replace"], 1)
    print(f"  [APPLY] {p['name']} — added @pytest.mark.slow decorator")
    applied += 1

if applied == 0 and already_marked == 0:
    print("ERROR: No patches applied and no targets already marked. Manual edit required.")
    sys.exit(3)

if applied > 0:
    TARGET.write_text(content, encoding="utf-8")
    print()
    print(f"SUCCESS: {applied} markers added, {already_marked} already had marker.")
    print(f"File written: {TARGET}")
else:
    print()
    print(f"INFO: All {already_marked} targets already had marker. No write needed.")

print()
print("Verification: re-run pytest with `-m 'not slow'` (default in pyproject.toml)")
print("Expected: 88 passed, 8 deselected (5 slow tests in test_graphrag.py)")
