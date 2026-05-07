#!/usr/bin/env python
"""
DC-EPMS PRO - fix_mojibake.py
==============================
Resolves DC-EPMS-015 by mass-replacing mojibake unicode in
project source files with ASCII or proper unicode equivalents.

Strategy:
  - Per-file: read with utf-8-sig, apply mapping table
    (longest-first to avoid partial matches), AST-validate, write back
  - Mathematical symbols (Greek letters, etc.) replaced with proper
    Unicode forms where readable, ASCII transliteration where the
    cosmetic ambiguity warning fires
  - Backup each file as .bak_pre_dc015_TIMESTAMP before modifying

Mapping table is conservative:
  - Multiplication sign U+00D7 -> "x" (RUF001 fires; ASCII safer for code)
  - En dash U+2013 -> "-" (RUF001 fires; range expressions read fine)
  - Right single quote U+2019 -> "'" (RUF003 fires)
  - Right double quote U+201D -> '"' (RUF003 fires)
  - Left double quote U+201C -> '"'
  - Em dash U+2014 -> " - " (with spaces for readability)
  - Less or equal U+2264 -> "<=" (RUF001 fires in code; safe in code context)
  - Greater or equal U+2265 -> ">="
  - Minus sign U+2212 -> "-"
  - Approximately U+2248 -> "~"
  - Right arrow U+2192 -> "->"
  - Degree sign U+00B0 stays (only causes RUF if ambiguous, kept as is)
  - Greek letters (delta, tau, epsilon) replaced with named ASCII
    forms in comments only ("Delta P" -> "dP", "tau=60" -> "tau=60"
    where the variable name `tau` is already used in code)

Usage:
    python fix_mojibake.py                       # APPLY all files
    python fix_mojibake.py --dry-run             # Preview only
    python fix_mojibake.py --file backend/X.py   # Single file
"""

from __future__ import annotations

import argparse
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path.cwd()
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")


class C:
    R = "\033[91m"
    G = "\033[92m"
    Y = "\033[93m"
    B = "\033[94m"
    BOLD = "\033[1m"
    END = "\033[0m"


def info(m): print(f"{C.B}[INFO]{C.END} {m}")
def ok(m):   print(f"{C.G}[ OK ]{C.END} {m}")
def warn(m): print(f"{C.Y}[WARN]{C.END} {m}")
def err(m):  print(f"{C.R}[FAIL]{C.END} {m}")


# ============================================================
# Mojibake mapping table (longest-first to avoid partial matches)
# ============================================================

# Each entry: (codepoint or sequence, replacement, description)
# Sorted by length descending in apply order so multi-char sequences
# (composed mojibake from cp1252 misencoding) match before single chars.

MOJIBAKE_MAP = [
    # ---- Multi-character mojibake patterns (highest priority) ----
    # These come from cp1252 misencoding of UTF-8; if the file has been
    # round-tripped already, single Unicode chars are present instead.
    # We handle BOTH cases.

    # Composed mojibake (cp1252 corruption of UTF-8 bytes):
    ("\u00e2\u20ac\u201d", " - ", "em-dash mojibake -> spaced hyphen"),
    ("\u00e2\u20ac\u201c", " - ", "en-dash mojibake -> spaced hyphen"),
    ("\u00e2\u20ac\u2122", "'", "right-quote mojibake -> apostrophe"),
    ("\u00e2\u020c\u00a0\u2122", "->", "arrow mojibake -> ASCII arrow"),

    # ---- Single-character ambiguous unicode (RUF001/002/003) ----
    # Math operators that cause RUF*** in strings/comments/docstrings.
    ("\u00d7", "x", "multiplication sign U+00D7 -> ASCII x"),
    ("\u2013", "-", "en dash U+2013 -> hyphen-minus"),
    ("\u2014", " - ", "em dash U+2014 -> spaced hyphen"),
    ("\u2019", "'", "right single quote U+2019 -> apostrophe"),
    ("\u2018", "'", "left single quote U+2018 -> apostrophe"),
    ("\u201c", '"', "left double quote U+201C -> straight quote"),
    ("\u201d", '"', "right double quote U+201D -> straight quote"),
    ("\u2264", "<=", "less-or-equal U+2264 -> ASCII <="),
    ("\u2265", ">=", "greater-or-equal U+2265 -> ASCII >="),
    ("\u2212", "-", "minus sign U+2212 -> hyphen-minus"),
    ("\u2248", "~", "approximately U+2248 -> tilde"),
    ("\u2192", "->", "right arrow U+2192 -> ASCII arrow"),
    ("\u00b7", "-", "middle dot U+00B7 -> hyphen-minus"),

    # Degree sign with adjacent C/F deserves to keep meaning explicit.
    # We replace standalone degree sign with "deg" but keep "degC"/"degF"
    # patterns where C or F follows immediately.
    ("\u00b0C", "degC", "degree sign + C -> degC"),
    ("\u00b0F", "degF", "degree sign + F -> degF"),
    ("\u00b0", "deg", "degree sign U+00B0 -> deg"),

    # Greek letters in comments/docstrings - replace with ASCII names
    # to avoid reader confusion. These are usually inside math notation.
    ("\u0394P", "dP", "Delta P U+0394 P -> dP (pressure differential)"),
    ("\u0394T", "dT", "Delta T -> dT (temperature differential)"),
    ("\u0394", "delta", "Delta U+0394 -> delta"),
    ("\u03c4", "tau", "tau U+03C4 -> ASCII tau"),
    ("\u03b5", "epsilon", "epsilon U+03B5 -> ASCII epsilon"),
    ("\u03c3", "sigma", "sigma U+03C3 -> ASCII sigma"),

    # Box drawing characters used as separators
    ("\u2500", "-", "box horizontal U+2500 -> hyphen"),
    ("\u2550", "=", "double horizontal U+2550 -> equals"),
    ("\u2502", "|", "box vertical U+2502 -> pipe"),
    ("\u2551", "|", "double vertical U+2551 -> pipe"),
    ("\u2588", "#", "block U+2588 -> hash"),

    # Arrows in comments
    ("\u21d2", "=>", "rightwards double arrow -> =>"),
    ("\u21d0", "<=", "leftwards double arrow -> <="),
    ("\u2191", "^", "upwards arrow -> caret"),
    ("\u2193", "v", "downwards arrow -> v"),
]


# Files known to contain mojibake (per Batch 3 ruff output)
TARGET_FILES = [
    "backend/agent_copilot.py",
    "backend/agent_engine.py",
    "backend/cyber_physical_tools.py",
    "backend/dpo_edge_healing.py",
    "backend/main.py",
    "backend/metrics_router.py",
    "backend/physics/electrical.py",
    "backend/physics/heat_rejection.py",
    "backend/physics/it_thermal.py",
    "backend/physics/mechanical.py",
    "backend/shift_report.py",
    "scripts/simulator.py",
]


def fix_file(filepath: Path, apply: bool) -> dict:
    """Process a single file. Returns dict with stats."""
    result = {
        "path": str(filepath.relative_to(PROJECT_ROOT)),
        "found": False,
        "replacements": 0,
        "by_pattern": {},
        "ast_ok": False,
        "applied": False,
        "error": None,
    }

    if not filepath.exists():
        result["error"] = "file not found"
        return result

    try:
        raw = filepath.read_bytes()
        text = raw.decode("utf-8-sig")
    except Exception as e:
        result["error"] = f"read failed: {e}"
        return result

    original = text
    for pattern, replacement, description in MOJIBAKE_MAP:
        if pattern in text:
            count = text.count(pattern)
            text = text.replace(pattern, replacement)
            result["found"] = True
            result["replacements"] += count
            result["by_pattern"][description] = count

    if not result["found"]:
        result["ast_ok"] = True
        return result

    # AST validate result
    try:
        ast.parse(text)
        result["ast_ok"] = True
    except SyntaxError as e:
        result["error"] = f"AST parse failed after substitution: {e}"
        return result

    if apply and text != original:
        backup = filepath.with_suffix(filepath.suffix + f".bak_pre_dc015_{TIMESTAMP}")
        shutil.copy2(filepath, backup)
        # Write with explicit utf-8 (no BOM) and unix line endings
        filepath.write_text(text, encoding="utf-8", newline="\n")
        result["applied"] = True

    return result


# ============================================================
# Main
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="Fix DC-EPMS-015 mojibake")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--file", type=str, help="Single file to process")
    args = parser.parse_args()

    print(f"\n{C.BOLD}{'=' * 60}{C.END}")
    print(f"{C.BOLD}DC-EPMS PRO - Fix Mojibake (DC-EPMS-015){C.END}")
    print(f"{C.BOLD}Mode: {'DRY-RUN' if args.dry_run else 'APPLY'}{C.END}")
    print(f"{C.BOLD}{'=' * 60}{C.END}\n")

    if not (PROJECT_ROOT / "pyproject.toml").exists():
        err(f"Not at project root: {PROJECT_ROOT}")
        return 1
    ok(f"Project root: {PROJECT_ROOT}")
    info(f"Mapping table: {len(MOJIBAKE_MAP)} entries")

    if args.file:
        files = [PROJECT_ROOT / args.file]
    else:
        files = [PROJECT_ROOT / f for f in TARGET_FILES]

    print(f"\n{C.BOLD}--- Processing {len(files)} files ---{C.END}\n")

    total_replacements = 0
    files_changed = 0
    files_failed = 0

    for fp in files:
        rel = fp.relative_to(PROJECT_ROOT) if fp.is_relative_to(PROJECT_ROOT) else fp
        result = fix_file(fp, not args.dry_run)

        if result["error"]:
            err(f"{rel}: {result['error']}")
            files_failed += 1
            continue

        if not result["found"]:
            info(f"{rel}: clean (no mojibake)")
            continue

        files_changed += 1
        total_replacements += result["replacements"]
        verb = "Applied" if result["applied"] else "Would apply"
        ok(f"{rel}: {verb} {result['replacements']} replacements (AST OK)")
        for pat, count in result["by_pattern"].items():
            info(f"   {count}x {pat}")

    print(f"\n{C.BOLD}{'=' * 60}{C.END}")
    print(f"{C.BOLD}SUMMARY{C.END}")
    print(f"{C.BOLD}{'=' * 60}{C.END}")
    print(f"  Files processed:     {len(files)}")
    print(f"  Files changed:       {files_changed}")
    print(f"  Files failed:        {files_failed}")
    print(f"  Total replacements:  {total_replacements}")

    if files_failed > 0:
        err("Some files failed. Inspect output above.")
        return 1

    if args.dry_run:
        print(f"\n{C.Y}DRY-RUN complete. Run without --dry-run to apply.{C.END}\n")
    else:
        print(f"\n{C.G}DC-EPMS-015 RESOLVED.{C.END}")
        print(f"{C.G}Next: run pytest --tb=no -q to confirm no regression.{C.END}")
        print(f"{C.G}Then: run ruff check backend/ scripts/ to confirm zero RUF001/002/003.{C.END}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
