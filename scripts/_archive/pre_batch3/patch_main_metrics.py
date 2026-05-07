"""
patch_main_metrics.py — Wires backend.metrics_router into backend/main.py.

Adds (idempotently):
  1. `from backend.metrics_router import setup_metrics` near other backend imports
  2. `setup_metrics(app)` call right after `app = FastAPI(...)` instantiation

Backup: backend/main.py.bak_pre_metrics_<timestamp>

Run from project root:
    python patch_main_metrics.py

Idempotent — safe to run twice. Verifies no syntax breakage via ast.parse().
"""

from __future__ import annotations

import ast
import re
import sys
from datetime import datetime
from pathlib import Path

MAIN_PY = Path("backend/main.py")

if not MAIN_PY.exists():
    print(f"ERROR: {MAIN_PY} not found. Run from project root.")
    sys.exit(1)

content = MAIN_PY.read_text(encoding="utf-8", errors="replace")
original = content

# ─── Idempotency check ──────────────────────────────────────────────────────
already_imported = "from backend.metrics_router import setup_metrics" in content
already_called = re.search(r"setup_metrics\s*\(\s*app\s*\)", content) is not None

if already_imported and already_called:
    print("INFO: Patch already applied (import + call both present). No changes.")
    sys.exit(0)

# ─── Backup ─────────────────────────────────────────────────────────────────
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = MAIN_PY.with_name(f"main.py.bak_pre_metrics_{ts}")
backup.write_text(original, encoding="utf-8")
print(f"Backup created: backend/{backup.name}")

# ─── Patch 1: add import ────────────────────────────────────────────────────
if not already_imported:
    # Find a good anchor: prefer right after another `from backend.` import
    backend_import_re = re.compile(
        r"^(from backend\.[a-zA-Z_][a-zA-Z0-9_]* import [^\n]+)$",
        re.MULTILINE,
    )
    matches = list(backend_import_re.finditer(content))
    if matches:
        # Insert after the LAST `from backend.` import line
        last = matches[-1]
        insert_pos = last.end()
        new_import = "\nfrom backend.metrics_router import setup_metrics"
        content = content[:insert_pos] + new_import + content[insert_pos:]
        print("  [PATCH 1/2] Inserted: from backend.metrics_router import setup_metrics")
    else:
        # Fallback: insert after last top-level import
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

# ─── Patch 2: add setup_metrics(app) call right after FastAPI instantiation ─
if not already_called:
    # Anchor: `app = FastAPI(...)` — possibly multi-line, capture full call
    fastapi_re = re.compile(
        r"^(app\s*=\s*FastAPI\([^)]*\))",
        re.MULTILINE | re.DOTALL,
    )
    match = fastapi_re.search(content)
    if not match:
        print("ERROR: Could not find 'app = FastAPI(...)' instantiation")
        print("Manual edit required. Run again after locating it.")
        sys.exit(3)

    insert_pos = match.end()
    new_call = (
        "\n\n# Prometheus instrumentation (Batch 2 — Decision B2-3 = B curated subset)\n"
        "# Honors ENABLE_METRICS env var. Graceful no-op if [obs] extra not installed.\n"
        "setup_metrics(app)"
    )
    content = content[:insert_pos] + new_call + content[insert_pos:]
    print("  [PATCH 2/2] Inserted: setup_metrics(app) after FastAPI instantiation")
else:
    print("  [SKIP 2/2] setup_metrics(app) call already present")

# ─── Validate Python syntax before writing ──────────────────────────────────
try:
    ast.parse(content)
except SyntaxError as e:
    print(f"ERROR: Patch produced invalid Python syntax: {e}")
    print("File NOT written. Backup preserved.")
    sys.exit(4)

# ─── Write ──────────────────────────────────────────────────────────────────
MAIN_PY.write_text(content, encoding="utf-8")
print()
print("SUCCESS: backend/main.py patched.")
print(f"  Lines added: {content.count(chr(10)) - original.count(chr(10))}")
print(f"  AST validation: PASSED")
print()
print("Verify with:")
print('  python -c "from backend.main import app; print(\'main.py imports OK\')"')
