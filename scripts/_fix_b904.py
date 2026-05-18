"""DC-EPMS PRO - B904 fixer (DC-EPMS-021 hygiene).

Appends `from <exc>` / `from None` to every `raise X(...)` that ruff's
B904 flags: an exception re-raised inside an `except` handler without an
explicit cause. Adding the cause is behaviour-neutral - it only sets
`__cause__` for traceback chaining, never control flow or values - so
this is a safe mechanical fix.

Each raise is attributed to its NEAREST enclosing `except` handler;
nested `def`/`lambda` scopes break that attribution (ruff does the
same). When the handler binds the exception (`except X as e:`) the fix
is `from e`; an unbound handler (`except X:`) gets `from None`, which
deliberately presents a clean converted error (e.g. HTTP 404) without
leaking the internal traceback.

AST-validates the rewritten source before touching disk.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

FILES = [
    "backend/cmms_routes.py",
    "backend/main.py",
    "backend/multi_agent_routes.py",
    "backend/physics/pue_routes.py",
    "backend/site_routes.py",
    "backend/tech_assist/routes.py",
]


def collect_fixes(tree: ast.AST) -> list[tuple[int, int, str]]:
    """Return (end_lineno, end_col_offset, insert_text) per B904 raise."""
    fixes: list[tuple[int, int, str]] = []

    def visit(node: ast.AST, handler_name: str | None, in_handler: bool) -> None:
        # A nested function/lambda is a new scope: the enclosing except
        # no longer governs raises lexically inside it.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            for child in ast.iter_child_nodes(node):
                visit(child, None, False)
            return
        if isinstance(node, ast.ExceptHandler):
            for child in ast.iter_child_nodes(node):
                visit(child, node.name, True)
            return
        if (
            isinstance(node, ast.Raise)
            and in_handler
            and node.exc is not None
            and node.cause is None
        ):
            name = handler_name if handler_name else "None"
            fixes.append((node.end_lineno, node.end_col_offset, f" from {name}"))
        for child in ast.iter_child_nodes(node):
            visit(child, handler_name, in_handler)

    visit(tree, None, False)
    return fixes


def apply(path: Path) -> int:
    src = path.read_text(encoding="utf-8")
    fixes = collect_fixes(ast.parse(src))
    if not fixes:
        return 0
    lines = src.splitlines(keepends=True)
    # Apply bottom-up so earlier byte offsets stay valid. ast col offsets
    # are UTF-8 byte offsets, so splice on the encoded line.
    for end_lineno, end_col, text in sorted(fixes, reverse=True):
        raw = lines[end_lineno - 1].encode("utf-8")
        lines[end_lineno - 1] = (
            raw[:end_col] + text.encode("utf-8") + raw[end_col:]
        ).decode("utf-8")
    new_src = "".join(lines)
    ast.parse(new_src)  # AST-validate before write
    path.write_text(new_src, encoding="utf-8")
    return len(fixes)


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    total = 0
    for rel in FILES:
        n = apply(root / rel)
        total += n
        print(f"  {rel}: {n} B904 fixes")
    print(f"TOTAL: {total} B904 fixes applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
