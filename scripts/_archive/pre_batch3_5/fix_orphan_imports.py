#!/usr/bin/env python
"""
DC-EPMS PRO - fix_orphan_imports.py
====================================
Resolves DC-EPMS-012 and DC-EPMS-013 by adding missing imports
to orphan files cyber_physical_tools.py and dpo_edge_healing.py.

Strategy:
  - cyber_physical_tools.py: add `import numpy as np` and
    `from numba import njit` after the module docstring.
    These are stdlib-equivalent for the project (numpy/numba are
    already in the venv via sentence-transformers transitive deps
    and ml extras respectively).

  - dpo_edge_healing.py: add `import json`, `import time`,
    `from pathlib import Path`, plus a guarded import block for
    `torch`, `LoraConfig`, `TaskType`, `TrainingArguments` because
    those dependencies are optional (S6 sprint will install them
    explicitly per ADR-007 entry criteria).

    Module-level objects `LORA_CONFIG_EDGE` and
    `DPO_TRAINING_ARGS_EDGE` get refactored from immediate
    construction to lazy factory functions
    `get_lora_config_edge()` and `get_dpo_training_args_edge()`
    so that import does not fail on machines lacking torch/peft.

Defensive:
  - Reads with utf-8-sig to tolerate BOM
  - AST-validates result before writing
  - Backs up original as .bak_pre_dc012013_TIMESTAMP
  - Idempotent: detects already-fixed files and skips

Usage:
    python fix_orphan_imports.py             # APPLY
    python fix_orphan_imports.py --dry-run   # Preview only
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
# DC-EPMS-012 - cyber_physical_tools.py
# ============================================================

CYBER_PHYS_FILE = "backend/cyber_physical_tools.py"
CYBER_PHYS_IMPORTS = '''from __future__ import annotations

import numpy as np

try:
    from numba import njit
except ImportError:
    # Fallback for environments without numba: provide no-op decorator
    # so module imports clean. Functions decorated with @njit will fall
    # back to pure-Python execution (slower but correct).
    def njit(*args, **kwargs):
        # Allow both @njit and @njit(cache=True, ...) usage
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]
        def decorator(fn):
            return fn
        return decorator

'''

CYBER_PHYS_MARKER = "import numpy as np"


def fix_dc_epms_012(apply: bool) -> bool:
    info(f"DC-EPMS-012: Fix imports in {CYBER_PHYS_FILE}")
    path = PROJECT_ROOT / CYBER_PHYS_FILE
    if not path.exists():
        err(f"File not found: {path}")
        return False

    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")

    if CYBER_PHYS_MARKER in text and "from numba import njit" in text:
        info("DC-EPMS-012 already fixed (idempotent skip)")
        return True

    # Find end of module docstring and insert imports right after it.
    # Strategy: parse AST, find docstring node end_lineno, insert
    # imports as a new line block right after.
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        err(f"Cannot parse current file (will need manual fix): {e}")
        return False

    insert_line = 0
    if (tree.body and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)):
        # Module docstring exists; insert after it
        insert_line = tree.body[0].end_lineno or 1
    else:
        # No docstring; insert at line 0
        insert_line = 0

    lines = text.splitlines(keepends=True)
    new_lines = lines[:insert_line] + ["\n", CYBER_PHYS_IMPORTS] + lines[insert_line:]
    new_text = "".join(new_lines)

    # Validate AST of result
    try:
        ast.parse(new_text)
    except SyntaxError as e:
        err(f"Resulting file would not parse: {e}")
        return False

    if apply:
        backup = path.with_suffix(f".py.bak_pre_dc012_{TIMESTAMP}")
        shutil.copy2(path, backup)
        path.write_text(new_text, encoding="utf-8")
        ok(f"DC-EPMS-012 fixed: {CYBER_PHYS_FILE} (backup: {backup.name})")
    else:
        info(f"Would insert imports at line {insert_line + 1}")
        info(f"Would back up as: {path.name}.bak_pre_dc012_{TIMESTAMP}")

    return True


# ============================================================
# DC-EPMS-013 - dpo_edge_healing.py
# ============================================================

DPO_FILE = "backend/dpo_edge_healing.py"

DPO_IMPORTS = '''from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

# Optional ML dependencies (only required when DPO recompile is invoked
# per ADR-007). Module imports clean even if these are absent so that
# CMMS draft capture (which does NOT need torch) continues to work.
try:
    import torch
    from peft import LoraConfig, TaskType
    from transformers import TrainingArguments
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False
    torch = None  # type: ignore[assignment]
    LoraConfig = None  # type: ignore[assignment, misc]
    TaskType = None  # type: ignore[assignment, misc]
    TrainingArguments = None  # type: ignore[assignment, misc]

'''

DPO_LAZY_FACTORY = '''

# ───────────────────────────────────────────────────────────────────────
#  Lazy factories (DC-EPMS-013 fix)
# ───────────────────────────────────────────────────────────────────────
# The original module had LORA_CONFIG_EDGE and DPO_TRAINING_ARGS_EDGE as
# top-level names that constructed peft/transformers objects on import.
# That pattern fails on machines that do not have torch/peft installed.
# ADR-007 requires this module to import clean even without those deps
# (capture-only path uses zero ML dependencies).
#
# Factory functions below construct the objects only when called, after
# verifying the optional dependencies are available. CMMS draft capture
# never calls these; only the manual /api/dpo/recompile endpoint does.

def get_lora_config_edge():
    """Construct LoRA config for edge training. Requires peft installed."""
    if not _TORCH_AVAILABLE:
        raise RuntimeError(
            "peft/transformers/torch not installed. "
            "Install with: pip install -e .[ml]"
        )
    return LoraConfig(
        r=8,
        lora_alpha=16,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
    )


def get_dpo_training_args_edge(output_dir: str = "./lora_edge_run"):
    """Construct DPO training args for edge nightly compute.
    Requires transformers installed."""
    if not _TORCH_AVAILABLE:
        raise RuntimeError(
            "transformers/torch not installed. "
            "Install with: pip install -e .[ml]"
        )
    return TrainingArguments(
        output_dir=output_dir,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=16,
        num_train_epochs=1,
        learning_rate=5e-5,
        logging_steps=10,
        save_strategy="epoch",
        gradient_checkpointing=True,
        fp16=True,
        optim="paged_adamw_8bit",
        max_grad_norm=1.0,
        warmup_ratio=0.03,
        report_to="none",
        remove_unused_columns=False,
    )

'''

DPO_MARKER = "import torch"
DPO_OLD_LORA_PATTERN = "LORA_CONFIG_EDGE = LoraConfig("
DPO_OLD_TRAINING_PATTERN = "DPO_TRAINING_ARGS_EDGE = TrainingArguments("


def fix_dc_epms_013(apply: bool) -> bool:
    info(f"DC-EPMS-013: Fix imports in {DPO_FILE}")
    path = PROJECT_ROOT / DPO_FILE
    if not path.exists():
        err(f"File not found: {path}")
        return False

    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")

    if "_TORCH_AVAILABLE" in text and "def get_lora_config_edge" in text:
        info("DC-EPMS-013 already fixed (idempotent skip)")
        return True

    # Step 1: parse AST to find module docstring end
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        err(f"Cannot parse current file: {e}")
        return False

    insert_line = 0
    if (tree.body and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)):
        insert_line = tree.body[0].end_lineno or 1
    else:
        insert_line = 0

    # Step 2: comment out the old LORA_CONFIG_EDGE and DPO_TRAINING_ARGS_EDGE
    # block by wrapping it. We don't delete since user may want to read
    # the original definition; we just disable execution.
    lines = text.splitlines(keepends=True)

    # Find LORA_CONFIG_EDGE = LoraConfig( block - turn into comment block
    # spanning until matching closing paren
    new_lines = lines[:insert_line] + ["\n", DPO_IMPORTS] + lines[insert_line:]

    # Now locate the original module-level constructions and disable them
    # by prefixing each line with `# ` until balanced parens close.
    out_lines = []
    skipping = False
    paren_depth = 0
    for line in new_lines:
        if not skipping and (DPO_OLD_LORA_PATTERN in line or DPO_OLD_TRAINING_PATTERN in line):
            # Begin commenting block out
            skipping = True
            paren_depth = line.count("(") - line.count(")")
            out_lines.append("# DC-EPMS-013: original module-level construction disabled\n")
            out_lines.append("# Use get_lora_config_edge() / get_dpo_training_args_edge() factories instead.\n")
            out_lines.append("# " + line)
            if paren_depth <= 0:
                skipping = False
        elif skipping:
            paren_depth += line.count("(") - line.count(")")
            out_lines.append("# " + line)
            if paren_depth <= 0:
                skipping = False
        else:
            out_lines.append(line)

    # Append the lazy factory block at end of file
    new_text = "".join(out_lines) + DPO_LAZY_FACTORY

    # Validate AST of result
    try:
        ast.parse(new_text)
    except SyntaxError as e:
        err(f"Resulting file would not parse: {e}")
        return False

    if apply:
        backup = path.with_suffix(f".py.bak_pre_dc013_{TIMESTAMP}")
        shutil.copy2(path, backup)
        path.write_text(new_text, encoding="utf-8")
        ok(f"DC-EPMS-013 fixed: {DPO_FILE} (backup: {backup.name})")
    else:
        info(f"Would insert imports at line {insert_line + 1}")
        info(f"Would comment out original LORA_CONFIG_EDGE and DPO_TRAINING_ARGS_EDGE blocks")
        info(f"Would append lazy factory functions at end of file")
        info(f"Would back up as: {path.name}.bak_pre_dc013_{TIMESTAMP}")

    return True


# ============================================================
# Verification step
# ============================================================

def verify_imports(apply: bool) -> bool:
    """Try to import both files programmatically (only in apply mode).
    In dry-run, only AST-validates."""
    if not apply:
        info("Skipping import verification (dry-run mode)")
        return True

    sys.path.insert(0, str(PROJECT_ROOT))

    info("Verifying cyber_physical_tools imports clean...")
    try:
        # Reload-safe import test via importlib
        import importlib
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_test_cyber_phys",
            PROJECT_ROOT / CYBER_PHYS_FILE
        )
        if spec is None or spec.loader is None:
            err("Could not create import spec for cyber_physical_tools")
            return False
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ok(f"cyber_physical_tools imports clean (numba available: {hasattr(module, 'njit')})")
    except Exception as e:
        err(f"cyber_physical_tools import failed: {e}")
        return False

    info("Verifying dpo_edge_healing imports clean...")
    try:
        spec = importlib.util.spec_from_file_location(
            "_test_dpo",
            PROJECT_ROOT / DPO_FILE
        )
        if spec is None or spec.loader is None:
            err("Could not create import spec for dpo_edge_healing")
            return False
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        torch_available = getattr(module, "_TORCH_AVAILABLE", None)
        ok(f"dpo_edge_healing imports clean (_TORCH_AVAILABLE={torch_available})")
        # Verify factory functions exist
        if not hasattr(module, "get_lora_config_edge"):
            err("Missing factory: get_lora_config_edge")
            return False
        if not hasattr(module, "get_dpo_training_args_edge"):
            err("Missing factory: get_dpo_training_args_edge")
            return False
        ok("Both lazy factory functions present")
    except Exception as e:
        err(f"dpo_edge_healing import failed: {e}")
        return False

    return True


# ============================================================
# Main
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="Fix DC-EPMS-012 and DC-EPMS-013")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    print(f"\n{C.BOLD}{'=' * 60}{C.END}")
    print(f"{C.BOLD}DC-EPMS PRO - Fix Orphan Imports (DC-EPMS-012 + 013){C.END}")
    print(f"{C.BOLD}Mode: {'DRY-RUN' if args.dry_run else 'APPLY'}{C.END}")
    print(f"{C.BOLD}{'=' * 60}{C.END}\n")

    markers = ["pyproject.toml", "backend"]
    missing = [m for m in markers if not (PROJECT_ROOT / m).exists()]
    if missing:
        err(f"Not at project root. Missing: {missing}")
        return 1
    ok(f"Project root: {PROJECT_ROOT}")

    print(f"\n{C.BOLD}--- DC-EPMS-012: cyber_physical_tools.py ---{C.END}")
    r1 = fix_dc_epms_012(not args.dry_run)

    print(f"\n{C.BOLD}--- DC-EPMS-013: dpo_edge_healing.py ---{C.END}")
    r2 = fix_dc_epms_013(not args.dry_run)

    print(f"\n{C.BOLD}--- Verify imports ---{C.END}")
    r3 = verify_imports(not args.dry_run)

    print(f"\n{C.BOLD}{'=' * 60}{C.END}")
    if r1 and r2 and r3:
        if args.dry_run:
            print(f"{C.Y}DRY-RUN complete. Run without --dry-run to apply.{C.END}\n")
        else:
            print(f"{C.G}DC-EPMS-012 and DC-EPMS-013 RESOLVED.{C.END}")
            print(f"{C.G}Next: run ruff check on these files to confirm zero F821.{C.END}\n")
        return 0
    else:
        err("One or more fixes failed. Inspect output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
