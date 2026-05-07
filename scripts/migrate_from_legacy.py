"""
DC-EPMS PRO — Day 1 Migration Script
======================================
Automates the cleanup + reorganization from the legacy flat structure
(C:\\Users\\Wilmer\\Desktop\\epms\\) to the professional /DC-EPMS_PRO layout.

Run from inside DC-EPMS_PRO/:
    python scripts/migrate_from_legacy.py --source "C:\\Users\\Wilmer\\Desktop\\epms"

What it does:
  1. Copies dc-epms-v15.html → frontend/index.html
  2. Copies chroma_db/ → data/chroma_db/
  3. Copies epms_mcp.db → data/
  4. Preserves .env → config/.env
  5. Archives legacy files to _legacy_backup/
  6. Deletes test_* files, backups, and obsolete HTML versions
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import sys

# Files we want to keep and move
KEEP_FILES = {
    "dc-epms-v15.html":       "frontend/index.html",
    "chroma_db":              "data/chroma_db",       # directory
    "epms_mcp.db":            "data/epms_mcp.db",
    ".env":                   "config/.env",
}

# Files to delete — obsolete
DELETE_PATTERNS = [
    "dc-epms-v1*.html",  # will match v1..v14 (v15 is explicit keep)
    "test_*.py",
    "check_*.py",
    "*_backup.*",
    "*_old.*",
    "serve_epms.py",      # legacy pre-v3
    "mcp_epms_server.py", # superseded by FastAPI main.py
    "mcp_epms_stdio*.py", # superseded
    "fix_schema.py",      # one-shot migration already done
    "index_docs*.py",     # one-shot indexing already done
]


def migrate(source: pathlib.Path, target: pathlib.Path, dry_run: bool = False):
    if not source.exists():
        print(f"ERROR: source not found: {source}")
        return 1

    target.mkdir(parents=True, exist_ok=True)
    (target / "frontend").mkdir(exist_ok=True)
    (target / "frontend" / "assets").mkdir(exist_ok=True)
    (target / "data").mkdir(exist_ok=True)
    (target / "config").mkdir(exist_ok=True)
    (target / "logs").mkdir(exist_ok=True)
    archive = target / "_legacy_backup"
    archive.mkdir(exist_ok=True)

    print(f"Source: {source}")
    print(f"Target: {target}")
    print(f"Archive: {archive}")
    print(f"Dry run: {dry_run}")
    print("=" * 60)

    # ── Copy the keep list ───────────────────────────────────
    for src_name, dst_rel in KEEP_FILES.items():
        src = source / src_name
        dst = target / dst_rel
        if not src.exists():
            print(f"  [SKIP] {src_name} not found")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dry_run:
            print(f"  [DRY]  copy {src} → {dst}")
            continue
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            print(f"  [COPY] dir  {src_name} → {dst_rel}")
        else:
            shutil.copy2(src, dst)
            print(f"  [COPY] file {src_name} → {dst_rel}")

    # ── Archive everything else for safety ───────────────────
    for item in source.iterdir():
        if item.name in {k.split("/")[0] for k in KEEP_FILES.keys()}:
            continue
        if any(item.match(p) for p in DELETE_PATTERNS):
            if dry_run:
                print(f"  [DRY]  archive+delete {item.name}")
                continue
            # Archive first
            try:
                dest = archive / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest)
                print(f"  [ARCH] {item.name}")
            except Exception as e:
                print(f"  [WARN] archive failed {item.name}: {e}")

    print("=" * 60)
    print("✓ Migration complete.")
    print(f"  Review: {target}")
    print(f"  Legacy backup at: {archive}")
    print()
    print("Next steps:")
    print(f"  1. cd {target}")
    print("  2. python -m venv .venv && .venv\\Scripts\\activate")
    print("  3. pip install -r requirements.txt")
    print("  4. cp config/.env.example config/.env  # fill in keys")
    print("  5. python backend/main.py")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--source",  required=True,  help="Legacy flat project path")
    p.add_argument("--target",  default=".",    help="Target DC-EPMS_PRO path")
    p.add_argument("--dry-run", action="store_true", help="Preview only")
    args = p.parse_args()
    sys.exit(migrate(pathlib.Path(args.source).resolve(),
                     pathlib.Path(args.target).resolve(),
                     dry_run=args.dry_run))
