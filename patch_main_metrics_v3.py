"""
patch_main_metrics_v3.py

v3 fix: The FastAPI() instantiation match was broken because [^)]* doesn't
handle parentheses inside string literals. The actual main.py has:

    app = FastAPI(
        title="DC-EPMS PRO",
        description="a3semi Edge Operations - ... (Tier IV 2N 40MW)",
        ...
    )

The "(Tier IV 2N 40MW)" inside description fooled the regex into matching
a partial expression, breaking the string when setup_metrics(app) was inserted.

v3 uses parenthesis-balance counting instead of regex for the FastAPI() match.

Idempotent. BOM-aware. Validates AST before writing.
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
    print("INFO: UTF-8 BOM detected. Will preserve in output.")

# ── Idempotency check ──────────────────────────────────────────────────────
already_imported = "from backend.metrics_router import setup_metrics" in content
already_called = re.search(r"setup_metrics\s*\(\s*app\s*\)", content) is not None

if already_imported and already_called:
    print("INFO: Patch already applied. No changes.")
    sys.exit(0)

# ── Backup ─────────────────────────────────────────────────────────────────
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = MAIN_PY.with_name(f"main.py.bak_pre_metrics_v3_{ts}")
backup.write_bytes(raw_bytes)
print(f"Backup created: backend/{backup.name}")


# ─────────────────────────────────────────────────────────────────────────────
# Helper: find_balanced_paren_end
# Given source code and a position pointing AT an opening '(', find the
# matching closing ')' position. Handles strings (skips paren-tokens inside
# string literals) and nested parens.
# ─────────────────────────────────────────────────────────────────────────────
def find_balanced_paren_end(src: str, open_paren_pos: int) -> int:
    """
    Returns the index of the closing ')' that matches the '(' at open_paren_pos.
    Returns -1 if not found.

    Tracks string literal state so '(' and ')' inside strings don't count.
    Handles single quotes, double quotes, triple quotes, and escapes.
    """
    if src[open_paren_pos] != "(":
        raise ValueError(f"open_paren_pos {open_paren_pos} does not point to '('")

    i = open_paren_pos + 1
    depth = 1
    n = len(src)

    in_string = False
    string_char = ""
    is_triple = False

    while i < n and depth > 0:
        ch = src[i]

        # String state machine
        if in_string:
            if ch == "\\" and not is_triple:
                # Escape: skip next char
                i += 2
                continue
            if is_triple:
                if src[i : i + 3] == string_char:
                    in_string = False
                    string_char = ""
                    is_triple = False
                    i += 3
                    continue
            elif ch == string_char:
                in_string = False
                string_char = ""
            i += 1
            continue

        # Not in string — check for string start
        if ch in ('"', "'"):
            triple = src[i : i + 3]
            if triple == ch * 3:
                in_string = True
                string_char = ch * 3
                is_triple = True
                i += 3
                continue
            in_string = True
            string_char = ch
            i += 1
            continue

        # Comment? skip to end of line
        if ch == "#":
            nl = src.find("\n", i)
            if nl == -1:
                return -1
            i = nl + 1
            continue

        # Paren tracking
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i

        i += 1

    return -1  # unmatched


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

# ── Patch 2: insert setup_metrics(app) after FastAPI() balanced close ──────
if not already_called:
    # Find "app = FastAPI(" — match the opening paren only, then balance manually
    fastapi_anchor = re.compile(r"^app\s*=\s*FastAPI\s*\(", re.MULTILINE)
    match = fastapi_anchor.search(content)
    if not match:
        print("ERROR: Could not find 'app = FastAPI(' pattern")
        sys.exit(3)

    # The '(' is the last char matched
    open_paren_pos = match.end() - 1

    # Find balanced closing ')'
    close_paren_pos = find_balanced_paren_end(content, open_paren_pos)
    if close_paren_pos == -1:
        print(
            f"ERROR: Could not find balanced ')' for FastAPI(...) "
            f"opened at offset {open_paren_pos}"
        )
        sys.exit(4)

    # Insert AFTER the closing paren
    insert_pos = close_paren_pos + 1
    new_call = (
        "\n\n# Prometheus instrumentation (Batch 2 - Decision B2-3 = B curated subset)\n"
        "# Honors ENABLE_METRICS env var. Graceful no-op if [obs] extra not installed.\n"
        "setup_metrics(app)"
    )
    content = content[:insert_pos] + new_call + content[insert_pos:]
    print(
        f"  [PATCH 2/2] Inserted: setup_metrics(app) after FastAPI(...) "
        f"closing ')' at offset {close_paren_pos}"
    )
else:
    print("  [SKIP 2/2] setup_metrics(app) call already present")

# ── Validate Python syntax (BOM-aware) ─────────────────────────────────────
try:
    content_for_ast = content.lstrip(BOM)
    ast.parse(content_for_ast)
    print("  [AST] Syntax validation PASSED")
except SyntaxError as e:
    print(f"ERROR: Patch produced invalid Python syntax: {e}")
    print("File NOT written. Backup preserved.")
    print()
    print("Diagnostic — context around the error:")
    lines = content.splitlines()
    if e.lineno and e.lineno >= 1:
        start = max(0, e.lineno - 3)
        end = min(len(lines), e.lineno + 2)
        for ln in range(start, end):
            marker = ">>> " if (ln + 1) == e.lineno else "    "
            print(f"{marker}{ln + 1:4d}: {lines[ln]}")
    sys.exit(5)

# ── Write back, preserving BOM if present ──────────────────────────────────
if has_bom and not content.startswith(BOM):
    content = BOM + content

MAIN_PY.write_bytes(content.encode("utf-8"))

print()
print("SUCCESS: backend/main.py patched.")
print(f"  Lines added: {content.count(chr(10)) - original.count(chr(10))}")
print(f"  BOM preserved: {has_bom}")
print("  AST validation: PASSED (BOM-aware, paren-balanced)")
print()
print("Verify with:")
print("  python -c \"from backend.main import app; print('main.py imports OK')\"")
