"""
patch_main_metrics_v2.py

v2 fix: Handles UTF-8 BOM correctly. The previous version's ast.parse()
rejected the BOM character (U+FEFF) at file start, even though Python's
import system handles BOM transparently.

This v2:
  - Detects BOM and strips it for AST validation only
  - Preserves BOM in the written output (so encoding stays consistent)
  - Otherwise identical to v1 logic

Run: python patch_main_metrics_v2.py
Idempotent: detects if patch already applied.
"""

from __future__ import annotations

import ast
import re
import sys
from datetime import datetime
from pathlib import Path

MAIN_PY = Path("backend/main.py")
BOM = "\ufeff"

if not MAIN_PY.exists():
    print(f"ERROR: {MAIN_PY} not found. Run from project root.")
    sys.exit(1)

# Read file, detect BOM
raw_bytes = MAIN_PY.read_bytes()
has_bom = raw_bytes.startswith(b"\xef\xbb\xbf")
content = raw_bytes.decode("utf-8-sig") if has_bom else raw_bytes.decode("utf-8")
original = content

if has_bom:
    print("INFO: UTF-8 BOM detected at file start. Will preserve in output.")

# ── Idempotency check ──────────────────────────────────────────────────────
already_imported = "from backend.metrics_router import setup_metrics" in content
already_called = re.search(r"setup_metrics\s*\(\s*app\s*\)", content) is not None

if already_imported and already_called:
    print("INFO: Patch already applied (import + call both present). No changes.")
    sys.exit(0)

# ── Backup ─────────────────────────────────────────────────────────────────
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = MAIN_PY.with_name(f"main.py.bak_pre_metrics_v2_{ts}")
backup.write_bytes(raw_bytes)  # binary copy preserves BOM exactly
print(f"Backup created: backend/{backup.name}")

# ── Patch 1: add import ────────────────────────────────────────────────────
if not already_imported:
    backend_import_re = re.compile(
        r"^(from backend\.[a-zA-Z_][a-zA-Z0-9_]* import [^\n]+)$",
        re.MULTILINE,
    )
    matches = list(backend_import_re.finditer(content))
    if matches:
        last = matches[-1]
        insert_pos = last.end()
        new_import = "\nfrom backend.metrics_router import setup_metrics"
        content = content[:insert_pos] + new_import + content[insert_pos:]
        print("  [PATCH 1/2] Inserted: from backend.metrics_router import setup_metrics")
    else:
        import_re = re.compile(r"^(import [^\n]+|from [^\n]+ import [^\n]+)$", re.MULTILINE)
        matches = list(import_re.finditer(content))
        if not matches:
            print("ERROR: Could not find any import statements in main.py")
            sys.exit(2)
        last = matches[-1]
        insert_pos = last.end()
        new_import = "\nfrom backend.metrics_router import setup_metrics"
        content = content[:insert_pos] + new_import + content[insert_pos:]
        print("  [PATCH 1/2] Inserted import after last top-level import")
else:
    print("  [SKIP 1/2] Import already present")

# ── Patch 2: add setup_metrics(app) call ────────────────────────────────────
if not already_called:
    fastapi_re = re.compile(
        r"^(app\s*=\s*FastAPI\([^)]*\))",
        re.MULTILINE | re.DOTALL,
    )
    match = fastapi_re.search(content)
    if not match:
        print("ERROR: Could not find 'app = FastAPI(...)' instantiation")
        sys.exit(3)

    insert_pos = match.end()
    new_call = (
        "\n\n# Prometheus instrumentation (Batch 2 - Decision B2-3 = B curated subset)\n"
        "# Honors ENABLE_METRICS env var. Graceful no-op if [obs] extra not installed.\n"
        "setup_metrics(app)"
    )
    content = content[:insert_pos] + new_call + content[insert_pos:]
    print("  [PATCH 2/2] Inserted: setup_metrics(app) after FastAPI instantiation")
else:
    print("  [SKIP 2/2] setup_metrics(app) call already present")

# ── Validate Python syntax (BOM-aware) ─────────────────────────────────────
try:
    # ast.parse rejects BOM at start of source. Strip it for validation only.
    content_for_ast = content.lstrip(BOM)
    ast.parse(content_for_ast)
    print("  [AST] Syntax validation PASSED")
except SyntaxError as e:
    print(f"ERROR: Patch produced invalid Python syntax: {e}")
    print("File NOT written. Backup preserved.")
    sys.exit(4)

# ── Write back, preserving BOM if it was there ──────────────────────────────
if has_bom and not content.startswith(BOM):
    content = BOM + content

# Write as bytes to preserve exact encoding
MAIN_PY.write_bytes(content.encode("utf-8"))

print()
print("SUCCESS: backend/main.py patched.")
print(f"  Lines added: {content.count(chr(10)) - original.count(chr(10))}")
print(f"  BOM preserved: {has_bom}")
print("  AST validation: PASSED (BOM-aware)")
print()
print("Verify with:")
print("  python -c \"from backend.main import app; print('main.py imports OK')\"")
