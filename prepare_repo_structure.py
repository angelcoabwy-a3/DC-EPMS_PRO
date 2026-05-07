#!/usr/bin/env python
"""
DC-EPMS PRO - prepare_repo_structure.py
========================================
Idempotent cleanup script for Batch 3.

Resolves bugs:
  DC-EPMS-002: Fix graphrag_service.py import path
  DC-EPMS-004: Delete 4 MD5-identical duplicate physics modules
  DC-EPMS-005: Archive 23 root iteration scripts to scripts/_archive/<sprint>/
  DC-EPMS-006: Investigate and resolve 2 chroma_db directories

Usage:
  python prepare_repo_structure.py             # DRY-RUN (default)
  python prepare_repo_structure.py --apply     # Actually modify filesystem

Defensive:
  - Creates pre-cleanup tarball before any destructive operation
  - Validates AST/encoding before file writes
  - Skips operations already done (idempotent)
  - Returns nonzero exit code on any failure
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import shutil
import sys
import tarfile
from pathlib import Path

# ============================================================
# CONFIGURATION
# ============================================================

PROJECT_ROOT = Path.cwd()
TIMESTAMP = dt.datetime.now().strftime("%Y%m%d_%H%M%S")

# DC-EPMS-002: Fix import path
GRAPHRAG_FILE = PROJECT_ROOT / "backend" / "graphrag_service.py"
GRAPHRAG_OLD = "from knowledge_graph"
GRAPHRAG_NEW = "from backend.knowledge_graph"

# DC-EPMS-004: Duplicates to delete
PHYSICS_DUPLICATES = [
    "backend/physics/physics_it_thermal.py",
    "backend/physics/physics_heat_rejection.py",
    "backend/physics/physics_electrical.py",
    "backend/physics/physics__init__.py",
    "backend/physics__init__.py",
]

# DC-EPMS-005: Iteration scripts to archive
# Pattern: any *.py or *.ps1 in root that is NOT in this whitelist
ROOT_SCRIPT_WHITELIST = {
    "apply_batch3.ps1",
    "validate_batch3.ps1",
    "prepare_repo_structure.py",
    "validate_environment.ps1",
    "patch_pyproject_obs.py",
    "patch_pyproject_torch_cpu.py",
    "patch_main_metrics_v3.py",
    "rebuild_batch2.ps1",
    "apply_batch2.ps1",
    "validate_batch2.ps1",
}

ARCHIVE_BASE = PROJECT_ROOT / "scripts" / "_archive"
ARCHIVE_TARGET_SPRINT = "pre_batch3"

# DC-EPMS-006: Chroma directories
CHROMA_OPERATIONAL = PROJECT_ROOT / "data" / "chroma_db"
CHROMA_STRAY_ROOT = PROJECT_ROOT / "chroma_db"

# Pre-cleanup tarball
TARBALL_NAME = f"pre_batch3_cleanup_{TIMESTAMP}.tar.gz"
TARBALL_PATH = PROJECT_ROOT / TARBALL_NAME


# ============================================================
# UTILITY FUNCTIONS
# ============================================================


class Color:
    """ANSI colors that work on Windows Terminal and most modern terminals."""

    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def info(msg: str) -> None:
    print(f"{Color.BLUE}[INFO]{Color.RESET} {msg}")


def success(msg: str) -> None:
    print(f"{Color.GREEN}[ OK ]{Color.RESET} {msg}")


def warn(msg: str) -> None:
    print(f"{Color.YELLOW}[WARN]{Color.RESET} {msg}")


def error(msg: str) -> None:
    print(f"{Color.RED}[FAIL]{Color.RESET} {msg}")


def dry_run_marker(apply: bool) -> str:
    return "[APPLY]" if apply else "[DRY-RUN]"


def md5_of_file(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def ast_validate_python(path: Path) -> bool:
    """Validate Python syntax. Returns True if valid."""
    try:
        with open(path, "rb") as f:
            content = f.read()
        text = content.decode("utf-8-sig")
        ast.parse(text)
        return True
    except (SyntaxError, UnicodeDecodeError) as e:
        error(f"AST validation failed for {path}: {e}")
        return False


# ============================================================
# PRE-CLEANUP TARBALL
# ============================================================


def create_pre_cleanup_tarball(apply: bool) -> bool:
    """Create defensive tarball before any destructive operation."""
    info(f"{dry_run_marker(apply)} Creating pre-cleanup tarball: {TARBALL_NAME}")

    if not apply:
        info("Tarball would include duplicates + iteration scripts + stray chroma_db")
        return True

    if TARBALL_PATH.exists():
        warn(f"Tarball already exists: {TARBALL_PATH}")
        return True

    items_to_archive = []

    # Add duplicates
    for relpath in PHYSICS_DUPLICATES:
        p = PROJECT_ROOT / relpath
        if p.exists():
            items_to_archive.append(p)

    # Add stray chroma
    if CHROMA_STRAY_ROOT.exists():
        items_to_archive.append(CHROMA_STRAY_ROOT)

    # Add iteration scripts (those not in whitelist)
    for p in PROJECT_ROOT.glob("*.py"):
        if p.name not in ROOT_SCRIPT_WHITELIST and p.is_file():
            items_to_archive.append(p)
    for p in PROJECT_ROOT.glob("*.ps1"):
        if p.name not in ROOT_SCRIPT_WHITELIST and p.is_file():
            items_to_archive.append(p)

    if not items_to_archive:
        warn("No items to archive (cleanup may already be done)")
        return True

    try:
        with tarfile.open(TARBALL_PATH, "w:gz") as tar:
            for item in items_to_archive:
                arcname = item.relative_to(PROJECT_ROOT)
                tar.add(item, arcname=str(arcname))
        success(f"Tarball created: {TARBALL_PATH} ({TARBALL_PATH.stat().st_size / 1024:.1f} KB)")
        return True
    except Exception as e:
        error(f"Tarball creation failed: {e}")
        return False


# ============================================================
# DC-EPMS-002 - Fix graphrag_service.py import
# ============================================================


def fix_dc_epms_002(apply: bool) -> bool:
    info(f"{dry_run_marker(apply)} DC-EPMS-002: Fix graphrag_service.py import path")

    if not GRAPHRAG_FILE.exists():
        warn(f"File not found, skipping: {GRAPHRAG_FILE}")
        return True

    with open(GRAPHRAG_FILE, "rb") as f:
        raw = f.read()
    content = raw.decode("utf-8-sig")

    if GRAPHRAG_NEW in content:
        info("DC-EPMS-002 already fixed (idempotent skip)")
        return True

    if GRAPHRAG_OLD not in content:
        warn(f"Pattern '{GRAPHRAG_OLD}' not found in {GRAPHRAG_FILE} (different state?)")
        return True

    new_content = content.replace(GRAPHRAG_OLD, GRAPHRAG_NEW, 1)

    # Validate AST
    try:
        ast.parse(new_content)
    except SyntaxError as e:
        error(f"DC-EPMS-002 fix would break syntax: {e}")
        return False

    if apply:
        # Backup
        backup = GRAPHRAG_FILE.with_suffix(f".py.bak_pre_dc002_{TIMESTAMP}")
        shutil.copy2(GRAPHRAG_FILE, backup)
        with open(GRAPHRAG_FILE, "wb") as f:
            f.write(new_content.encode("utf-8"))
        success(f"DC-EPMS-002 fixed: {GRAPHRAG_FILE} (backup: {backup.name})")
    else:
        info(f"Would replace '{GRAPHRAG_OLD}' with '{GRAPHRAG_NEW}'")

    return True


# ============================================================
# DC-EPMS-004 - Delete 4+1 MD5-identical duplicates
# ============================================================


def fix_dc_epms_004(apply: bool) -> bool:
    info(f"{dry_run_marker(apply)} DC-EPMS-004: Delete duplicate physics modules")

    canonicals = {
        "backend/physics/physics_it_thermal.py": "backend/physics/it_thermal.py",
        "backend/physics/physics_heat_rejection.py": "backend/physics/heat_rejection.py",
        "backend/physics/physics_electrical.py": "backend/physics/electrical.py",
        "backend/physics/physics__init__.py": "backend/physics/__init__.py",
        "backend/physics__init__.py": None,
    }

    deleted = 0
    for dup_rel, canon_rel in canonicals.items():
        dup = PROJECT_ROOT / dup_rel
        if not dup.exists():
            info(f"Already absent (idempotent): {dup_rel}")
            continue

        if canon_rel is not None:
            canon = PROJECT_ROOT / canon_rel
            if not canon.exists():
                error(f"Canonical missing: {canon_rel} (cannot verify duplicate)")
                return False
            md5_dup = md5_of_file(dup)
            md5_canon = md5_of_file(canon)
            if md5_dup != md5_canon:
                error(
                    f"Files differ! Refusing to delete: {dup_rel} ({md5_dup}) vs {canon_rel} ({md5_canon})"
                )
                return False
            info(f"MD5 verified identical: {dup_rel} == {canon_rel}")
        else:
            warn(f"No canonical for {dup_rel} (orphan outside package), deletion safe")

        if apply:
            dup.unlink()
            success(f"Deleted: {dup_rel}")
        else:
            info(f"Would delete: {dup_rel}")
        deleted += 1

    info(f"DC-EPMS-004: {deleted} duplicates {'deleted' if apply else 'identified'}")
    return True


# ============================================================
# DC-EPMS-005 - Archive root iteration scripts
# ============================================================


def fix_dc_epms_005(apply: bool) -> bool:
    info(f"{dry_run_marker(apply)} DC-EPMS-005: Archive root iteration scripts")

    archive_dir = ARCHIVE_BASE / ARCHIVE_TARGET_SPRINT
    candidates = []

    for p in PROJECT_ROOT.glob("*.py"):
        if p.is_file() and p.name not in ROOT_SCRIPT_WHITELIST:
            candidates.append(p)
    for p in PROJECT_ROOT.glob("*.ps1"):
        if p.is_file() and p.name not in ROOT_SCRIPT_WHITELIST:
            candidates.append(p)

    if not candidates:
        info("No iteration scripts to archive (already done or never existed)")
        return True

    info(f"Found {len(candidates)} iteration scripts to archive:")
    for c in candidates:
        info(f"  - {c.name}")

    if apply:
        archive_dir.mkdir(parents=True, exist_ok=True)
        gitkeep = archive_dir / ".gitkeep"
        gitkeep.touch(exist_ok=True)

        for c in candidates:
            target = archive_dir / c.name
            if target.exists():
                warn(f"Target exists, skipping: {target}")
                continue
            shutil.move(str(c), str(target))
            success(f"Archived: {c.name} -> scripts/_archive/{ARCHIVE_TARGET_SPRINT}/{c.name}")
    else:
        info(f"Would create dir: {archive_dir}")
        info(f"Would move {len(candidates)} files into archive")

    return True


# ============================================================
# DC-EPMS-006 - Resolve 2 chroma_db directories
# ============================================================


def fix_dc_epms_006(apply: bool) -> bool:
    info(f"{dry_run_marker(apply)} DC-EPMS-006: Resolve stray chroma_db directory")

    if not CHROMA_STRAY_ROOT.exists():
        info(f"Already absent (idempotent): {CHROMA_STRAY_ROOT}")
        return True

    if not CHROMA_OPERATIONAL.exists():
        error(f"Operational chroma missing: {CHROMA_OPERATIONAL}. Aborting cleanup.")
        return False

    op_size = sum(f.stat().st_size for f in CHROMA_OPERATIONAL.rglob("*") if f.is_file())
    stray_size = sum(f.stat().st_size for f in CHROMA_STRAY_ROOT.rglob("*") if f.is_file())

    info(f"Operational chroma: {op_size / 1024:.1f} KB at {CHROMA_OPERATIONAL}")
    info(f"Stray chroma:      {stray_size / 1024:.1f} KB at {CHROMA_STRAY_ROOT}")

    if stray_size > op_size:
        error(
            f"Stray ({stray_size}) is LARGER than operational ({op_size}). MANUAL INTERVENTION REQUIRED."
        )
        return False

    if apply:
        shutil.rmtree(CHROMA_STRAY_ROOT)
        success(f"Removed stray: {CHROMA_STRAY_ROOT}")
    else:
        info(f"Would remove: {CHROMA_STRAY_ROOT}")

    return True


# ============================================================
# logs/ skeleton creation (B3-2 logs/ excluded but dir versioned)
# ============================================================


def create_logs_skeleton(apply: bool) -> bool:
    info(f"{dry_run_marker(apply)} Create logs/ skeleton with .gitkeep")
    logs_dir = PROJECT_ROOT / "logs"
    if apply:
        logs_dir.mkdir(exist_ok=True)
        gitkeep = logs_dir / ".gitkeep"
        gitkeep.touch(exist_ok=True)
        success(f"Created: {logs_dir} with .gitkeep")
    else:
        info(f"Would create: {logs_dir}/")
    return True


# ============================================================
# MAIN
# ============================================================


def main() -> int:
    parser = argparse.ArgumentParser(description="DC-EPMS PRO Batch 3 cleanup orchestrator")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes. Without this flag, runs in DRY-RUN mode.",
    )
    args = parser.parse_args()

    print(f"\n{Color.BOLD}{'=' * 60}{Color.RESET}")
    print(f"{Color.BOLD}DC-EPMS PRO - Batch 3 Cleanup Orchestrator{Color.RESET}")
    print(
        f"{Color.BOLD}Mode: {'APPLY (will modify filesystem)' if args.apply else 'DRY-RUN (no changes)'}{Color.RESET}"
    )
    print(f"{Color.BOLD}{'=' * 60}{Color.RESET}\n")

    if not args.apply:
        warn("DRY-RUN mode. Use --apply to actually execute changes.\n")

    # Sanity check: must be at project root
    expected_markers = ["pyproject.toml", "backend", "tests"]
    missing = [m for m in expected_markers if not (PROJECT_ROOT / m).exists()]
    if missing:
        error(f"Not at project root. Missing: {missing}")
        return 1

    success(f"Project root verified: {PROJECT_ROOT}\n")

    steps = [
        ("Pre-cleanup tarball", create_pre_cleanup_tarball),
        ("DC-EPMS-002", fix_dc_epms_002),
        ("DC-EPMS-004", fix_dc_epms_004),
        ("DC-EPMS-005", fix_dc_epms_005),
        ("DC-EPMS-006", fix_dc_epms_006),
        ("logs/ skeleton", create_logs_skeleton),
    ]

    results = {}
    for name, func in steps:
        print(f"\n{Color.BOLD}--- {name} ---{Color.RESET}")
        try:
            ok = func(args.apply)
            results[name] = ok
        except Exception as e:
            error(f"{name} crashed: {e}")
            results[name] = False

    print(f"\n{Color.BOLD}{'=' * 60}{Color.RESET}")
    print(f"{Color.BOLD}SUMMARY{Color.RESET}")
    print(f"{Color.BOLD}{'=' * 60}{Color.RESET}")
    all_ok = True
    for name, ok in results.items():
        if ok:
            success(name)
        else:
            error(name)
            all_ok = False

    if all_ok:
        if args.apply:
            print(f"\n{Color.GREEN}{Color.BOLD}All cleanup steps SUCCEEDED.{Color.RESET}")
            print(f"{Color.GREEN}Tarball preserved: {TARBALL_NAME} (gitignored){Color.RESET}\n")
        else:
            print(
                f"\n{Color.YELLOW}{Color.BOLD}DRY-RUN complete. Review output, then re-run with --apply.{Color.RESET}\n"
            )
        return 0
    else:
        error("Some steps FAILED. Check output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
