"""
DC-EPMS PRO - RAG Knowledge Base Seed v2 (tier-based)
======================================================
Indexes the a3semi corpus with tier metadata for prioritized retrieval:

  Tier 1 - Safety:    data/corpus/tier1_safety/*.md
  Tier 2 - Vendor:    data/corpus/tier2_vendor/*.md
  Tier 3 - Standards: data/corpus/tier3_standards/*.md

Usage:
  python scripts/seed_rag.py            # incremental seed (upsert)
  python scripts/seed_rag.py --reset    # wipe collection and re-index
"""
from __future__ import annotations

import argparse
import sys
import pathlib
import re

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))


TIER_META = {
    "tier1_safety":    {"tier": 1, "source": "safety",    "priority": 1},
    "tier2_vendor":    {"tier": 2, "source": "vendor",    "priority": 2},
    "tier3_standards": {"tier": 3, "source": "standard",  "priority": 3},
}


def parse_markdown_header(content: str) -> dict:
    """Extract metadata hints from markdown header lines like '**Standard**: ...'."""
    meta = {}
    for line in content.splitlines()[:20]:
        m = re.match(r'^\*\*([A-Za-z ]+)\*\*:\s*(.+)$', line.strip())
        if m:
            key = m.group(1).strip().lower().replace(" ", "_")
            val = m.group(2).strip()
            if key in ("standard", "equipment", "class", "source", "applies_to"):
                meta[key] = val
    return meta


def collect_corpus() -> list[tuple[str, str, dict]]:
    """Walk corpus dir and build (doc_id, content, metadata) tuples."""
    corpus_root = PROJECT_ROOT / "data" / "corpus"
    docs = []

    if not corpus_root.exists():
        print(f"ERROR: corpus directory not found: {corpus_root}")
        return docs

    for tier_dir, tier_meta in TIER_META.items():
        tier_path = corpus_root / tier_dir
        if not tier_path.exists():
            print(f"  [SKIP] {tier_dir} not found")
            continue

        for md_file in sorted(tier_path.glob("*.md")):
            doc_id = f"{tier_dir}_{md_file.stem}"
            content = md_file.read_text(encoding="utf-8")
            if not content.strip():
                continue

            metadata = {**tier_meta}
            metadata["filename"] = md_file.name
            metadata["tier_dir"] = tier_dir

            header_meta = parse_markdown_header(content)
            metadata.update(header_meta)

            docs.append((doc_id, content, metadata))

    return docs


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true",
                   help="Delete and recreate the collection before indexing")
    args = p.parse_args()

    print("DC-EPMS PRO - RAG seed v2 (tier-based)")
    print("=" * 60)

    try:
        from rag_service import RAGService
    except ImportError as e:
        print(f"ERROR: cannot import rag_service: {e}")
        return 1

    chroma_path = PROJECT_ROOT / "data" / "chroma_db"
    chroma_path.parent.mkdir(exist_ok=True)

    print(f"ChromaDB path: {chroma_path}")
    rag = RAGService(str(chroma_path))

    if args.reset:
        print("Resetting collection...")
        rag.delete_collection()

    before = rag.count()
    print(f"Current docs: {before}\n")

    docs = collect_corpus()
    if not docs:
        print("ERROR: no documents found in data/corpus/")
        return 1

    by_tier = {1: [], 2: [], 3: []}
    for doc_id, content, metadata in docs:
        by_tier[metadata["tier"]].append((doc_id, content, metadata))

    success = 0
    for tier in (1, 2, 3):
        tier_name = {1: "SAFETY", 2: "VENDOR", 3: "STANDARDS"}[tier]
        print(f"--- Tier {tier} ({tier_name}) ---")
        for doc_id, content, metadata in by_tier[tier]:
            ok = rag.index_document(doc_id, content, metadata)
            marker = "OK" if ok else "FAIL"
            size_kb = len(content) // 1024
            print(f"  [{marker}] {doc_id:55s} ({size_kb} KB)")
            if ok:
                success += 1
        print()

    after = rag.count()
    print("=" * 60)
    print(f"Indexed {success}/{len(docs)} documents")
    print(f"Collection size: {before} -> {after}")

    if after >= 10:
        print("\nRAG ready for production queries.")
        return 0
    else:
        print("\nSeed incomplete.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
