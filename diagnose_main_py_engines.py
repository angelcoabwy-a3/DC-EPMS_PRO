"""
diagnose_main_py_engines.py
============================
Diagnoses the actual variable names / import patterns for physics_engine,
witness_engine, procedure_engine in backend/main.py.

Run from project root:
    python diagnose_main_py_engines.py

Paste the output back to Claude so the activation snippet can be tailored
to your actual main.py structure.
"""

import ast
from pathlib import Path

main_path = Path("backend/main.py")
if not main_path.exists():
    print("ERROR: backend/main.py not found - run from project root")
    raise SystemExit(1)

source = main_path.read_text(encoding="utf-8")
tree = ast.parse(source)

print("=" * 70)
print("DIAGNOSTIC: backend/main.py engine variable patterns")
print("=" * 70)

print("\n=== Module-level imports involving 'physics', 'witness', 'procedure', 'engine' ===")
for node in ast.walk(tree):
    if isinstance(node, ast.ImportFrom):
        mod = node.module or ""
        names_str = ", ".join(
            f"{n.name}" + (f" as {n.asname}" if n.asname else "")
            for n in node.names
        )
        if any(k in mod.lower() for k in ("physics", "witness", "procedure", "engine")):
            print(f"  Line {node.lineno}: from {mod} import {names_str}")
        else:
            for n in node.names:
                if any(k in n.name.lower() for k in ("physics", "witness", "procedure", "engine")):
                    print(f"  Line {node.lineno}: from {mod} import {names_str}")
                    break
    elif isinstance(node, ast.Import):
        for n in node.names:
            if any(k in n.name.lower() for k in ("physics", "witness", "procedure", "engine")):
                alias = f" as {n.asname}" if n.asname else ""
                print(f"  Line {node.lineno}: import {n.name}{alias}")

print("\n=== Module/lifespan-level assignments matching engine-like names ===")
for node in ast.walk(tree):
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                name_lower = target.id.lower()
                if any(k in name_lower for k in (
                    "physics", "witness", "procedure", "engine", "facade",
                    "service",
                )):
                    val_repr = ast.unparse(node.value) if hasattr(ast, "unparse") else "<expr>"
                    if len(val_repr) > 80:
                        val_repr = val_repr[:77] + "..."
                    print(f"  Line {node.lineno}: {target.id} = {val_repr}")

print("\n=== Method calls of form X.something() where X looks engine-related ===")
seen_calls: dict[str, list[int]] = {}
for node in ast.walk(tree):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if isinstance(node.func.value, ast.Name):
            var = node.func.value.id
            var_lower = var.lower()
            if any(k in var_lower for k in (
                "physics", "witness", "procedure", "engine", "facade", "validate"
            )):
                key = f"{var}.{node.func.attr}"
                seen_calls.setdefault(key, []).append(node.lineno)

for key in sorted(seen_calls.keys()):
    lines = seen_calls[key]
    if len(lines) > 5:
        line_str = f"{lines[0]}, {lines[1]}, ... ({len(lines)} total occurrences)"
    else:
        line_str = ", ".join(str(l) for l in lines)
    print(f"  {key}() called at line(s): {line_str}")

print("\n=== Lifespan function structure ===")
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "lifespan":
        print(f"  lifespan defined at line {node.lineno}, ends at line {node.end_lineno}")
        # First 30 lines of lifespan
        lines = source.split("\n")
        start = node.lineno - 1
        end = min(start + 30, node.end_lineno)
        print(f"  First 30 lines (line {node.lineno}-{end}):")
        for i in range(start, end):
            print(f"    {i+1:5d}| {lines[i].rstrip()}")
        break

print("\n=== app.include_router() calls (insertion point candidates) ===")
include_lines = []
for node in ast.walk(tree):
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        call = node.value
        if isinstance(call.func, ast.Attribute) and call.func.attr == "include_router":
            if isinstance(call.func.value, ast.Name) and call.func.value.id == "app":
                arg_str = ast.unparse(call.args[0]) if call.args and hasattr(ast, "unparse") else "?"
                include_lines.append((node.lineno, arg_str))

for line, arg in include_lines:
    print(f"  Line {line}: app.include_router({arg})")

print("\n" + "=" * 70)
print("Paste this output back to Claude to get a tailored activation snippet.")
print("=" * 70)
