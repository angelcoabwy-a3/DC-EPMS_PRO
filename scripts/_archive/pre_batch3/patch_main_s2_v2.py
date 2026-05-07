"""
Sprint S2 Batch 3 v2: insert the GraphRAG mount block in main.py at
the correct location: AFTER the Sprint S1b try/except block closes,
not in the middle of a multi-line log.info() call.

Marker (stable, single-line):
    log.error(f"[Sprint S1b] Site routes mount failed: {e}")

Insertion: AFTER that line, at module-scope (no indent).

Validates the result with ast.parse() before writing to disk - so if
anything goes wrong, the disk file is NOT corrupted.
"""
from pathlib import Path
import ast
import sys

MAIN_PATH = Path(r"C:\dev\DC-EPMS_PRO\backend\main.py")

# Backup (only if we don't already have one from this fix attempt)
bak = MAIN_PATH.with_suffix(".py.bak_pre_s2_v2")
if not bak.exists():
    bak.write_bytes(MAIN_PATH.read_bytes())
    print(f"[bak] {bak.name}")

data = MAIN_PATH.read_bytes()

# Idempotency: if S2 mount already present, skip
if b"[Sprint S2] GraphRAG service mounted" in data:
    print("[skip] main.py already has S2 mount block. Nothing to do.")
    sys.exit(0)

# Find the stable single-line marker at module-scope
marker = b'log.error(f"[Sprint S1b] Site routes mount failed: {e}")'
idx = data.find(marker)
if idx < 0:
    print("[FAIL] marker not found")
    sys.exit(1)

# Find end of that line (LF)
line_end = data.find(b"\n", idx)
if line_end < 0:
    print("[FAIL] could not find end of marker line")
    sys.exit(1)

# Detect line ending style
eol = b"\r\n" if (line_end > 0 and data[line_end - 1:line_end] == b"\r") else b"\n"

# The S2 block uses `get_site_model()` (the module-level helper) to obtain
# a SiteModel reference, since `_site_model` from the S1b try/except is
# scoped to that block. Going through the public helper is also cleaner.
#
# We instantiate INSIDE its own try/except so any failure (corpus missing,
# embedding model not downloadable in offline mode, etc) only disables S2;
# it never breaks the server's S1b/S1a/Sprint-3 startup.

s2_block_lines = [
    b"",
    b"",
    b"# ==============================================================",
    b"#  Sprint S2: GraphRAG service + router",
    b"# ==============================================================",
    b"try:",
    b"    from graphrag_service import GraphRAGService",
    b"    from graphrag_routes import make_graphrag_router",
    b"    from agent_graph_tool import set_graphrag_service",
    b"    from site_model import get_site_model as _s2_get_site_model",
    b"    _s2_corpus_dir = PROJECT_ROOT / 'config' / 'knowledge'",
    b"    _s2_site_model = _s2_get_site_model(PROJECT_ROOT)",
    b"    _s2_service = GraphRAGService(_s2_site_model, _s2_corpus_dir)",
    b"    set_graphrag_service(_s2_service)",
    b"    app.include_router(make_graphrag_router(_s2_service))",
    b"    _s2_doc_count = len([p for p in _s2_corpus_dir.glob('*.md') if p.name.lower() != 'readme.md'])",
    b"    log.info(",
    b"        f'[Sprint S2] GraphRAG service mounted at /api/graph '",
    b"        f'(lazy index, {_s2_doc_count} knowledge docs available)'",
    b"    )",
    b"except ImportError as _s2_e:",
    b"    log.warning(f'[Sprint S2] GraphRAG NOT loaded (ImportError): {_s2_e}')",
    b"except Exception as _s2_e:",
    b"    log.warning(f'[Sprint S2] GraphRAG NOT mounted: {_s2_e}')",
]

s2_block = eol.join(s2_block_lines) + eol

# Insert AFTER the marker line (just past its trailing newline)
new_data = data[:line_end + 1] + s2_block + data[line_end + 1:]

# Validate AST BEFORE writing to disk
try:
    text_for_check = new_data.decode("utf-8")
    # Strip BOM for compile()
    if text_for_check.startswith("\ufeff"):
        text_for_check = text_for_check[1:]
    ast.parse(text_for_check)
except SyntaxError as e:
    print(f"[FAIL] AST check after patch: line {e.lineno}: {e.msg}")
    print("       Disk file NOT modified. Backup is intact.")
    # Show the area where the patch was inserted, for diagnosis
    inserted_text = s2_block.decode("utf-8")
    print()
    print("--- Inserted block ---")
    print(inserted_text)
    sys.exit(1)

# Write
MAIN_PATH.write_bytes(new_data)
print(f"[ok] PATCHED main.py (+{len(s2_block)} bytes)")

# Re-validate by re-reading and parsing
text = MAIN_PATH.read_text(encoding="utf-8")
if text.startswith("\ufeff"):
    text = text[1:]
ast.parse(text)
print("[ok] Re-parse confirms valid Python")

print()
print("Next: restart server and look for")
print("  '[Sprint S2] GraphRAG service mounted at /api/graph'")
