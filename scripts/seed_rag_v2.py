"""
DC-EPMS PRO — RAG Seed Script v2 (Tier-Aware)
==============================================
Walks `data/corpus/` recursively, parses YAML front-matter from each
`.md` file, and indexes into ChromaDB with full metadata for
tier-based retrieval.

Expected front-matter schema:
    ---
    doc_id: <unique ID>
    tier: <1-4>
    priority: critical | high | medium
    domain: <subsystem>
    standard: <referenced standard>
    doc_type: MOP | EOP | STANDARD | VENDOR
    keywords: [list, of, keywords]
    facility: <facility name>
    ---

Usage:
    python scripts/seed_rag_v2.py          # indexes all docs
    python scripts/seed_rag_v2.py --clean  # clears collection first
    python scripts/seed_rag_v2.py --tier 1 # only tier 1 docs
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure backend/ is importable when running from project root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.rag_service import RAGService  # noqa: E402

CORPUS_ROOT = ROOT / "data" / "corpus"
CHROMA_PATH = str(ROOT / "data" / "chroma_db")


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML front-matter from markdown content.

    Returns (metadata_dict, body_text). If no front-matter, returns ({}, text).
    """
    if not text.startswith("---"):
        return {}, text

    # Find the closing ---
    lines = text.split("\n")
    end_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return {}, text

    meta_lines = lines[1:end_idx]
    body = "\n".join(lines[end_idx + 1 :]).strip()

    # Parse simple YAML (key: value, supports lists in brackets)
    metadata = {}
    for line in meta_lines:
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not value:
            continue

        # Handle list syntax: [a, b, c]
        if value.startswith("[") and value.endswith("]"):
            items = value[1:-1].split(",")
            items = [item.strip().strip("'\"") for item in items if item.strip()]
            value = items
        # Handle int
        elif value.isdigit():
            value = int(value)
        # Handle string (strip quotes if present)
        else:
            value = value.strip("'\"")

        metadata[key] = value

    return metadata, body


def index_corpus(
    rag: RAGService,
    clean: bool = False,
    tier_filter: int = None,
) -> dict:
    """Index all markdown docs in the corpus directory.

    Returns stats dict with counts.
    """
    stats = {
        "total_found": 0,
        "indexed": 0,
        "skipped": 0,
        "errors": 0,
        "by_tier": {1: 0, 2: 0, 3: 0, 4: 0},
    }

    if clean:
        print(f"Cleaning collection '{rag.collection_name}'...")
        try:
            rag.client.delete_collection(rag.collection_name)
        except Exception:
            pass
        rag.collection = rag.client.get_or_create_collection(
            name=rag.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        print("  collection cleared")

    if not CORPUS_ROOT.exists():
        print(f"ERROR: Corpus directory not found: {CORPUS_ROOT}")
        return stats

    md_files = sorted(CORPUS_ROOT.rglob("*.md"))
    stats["total_found"] = len(md_files)

    print(f"Found {len(md_files)} markdown files in {CORPUS_ROOT}")
    print(f"Indexing to: {rag.chroma_path}")
    print("=" * 60)

    for md_path in md_files:
        rel_path = md_path.relative_to(CORPUS_ROOT)
        try:
            text = md_path.read_text(encoding="utf-8")
            metadata, body = parse_frontmatter(text)

            if not metadata.get("doc_id"):
                print(f"  [SKIP] {rel_path} - no doc_id in front-matter")
                stats["skipped"] += 1
                continue

            tier = metadata.get("tier", 4)
            if not isinstance(tier, int):
                try:
                    tier = int(tier)
                except (ValueError, TypeError):
                    tier = 4

            if tier_filter is not None and tier != tier_filter:
                stats["skipped"] += 1
                continue

            # Keywords may come as list from YAML parser
            keywords = metadata.get("keywords", "")
            if isinstance(keywords, list):
                metadata["keywords"] = ",".join(str(k) for k in keywords)

            # Standards may come as list
            standard_refs = metadata.get("standard_refs", "")
            if isinstance(standard_refs, list):
                metadata["standard_refs"] = ",".join(str(s) for s in standard_refs)
            applies_to = metadata.get("applies_to", "")
            if isinstance(applies_to, list):
                metadata["applies_to"] = ",".join(str(a) for a in applies_to)

            # Ensure tier is int
            metadata["tier"] = tier

            doc_id = str(metadata["doc_id"])
            rag.upsert(doc_id, body, metadata)

            tier_label = f"T{tier}"
            priority = metadata.get("priority", "-")
            print(f"  [OK]  {tier_label} [{priority:8s}] {doc_id}")

            stats["indexed"] += 1
            stats["by_tier"][tier] = stats["by_tier"].get(tier, 0) + 1

        except Exception as e:
            print(f"  [ERR] {rel_path}: {e}")
            stats["errors"] += 1

    print("=" * 60)
    print(f"Indexed: {stats['indexed']} / {stats['total_found']}")
    print(f"Skipped: {stats['skipped']}  Errors: {stats['errors']}")
    print(
        f"By tier: T1={stats['by_tier'].get(1, 0)} "
        f"T2={stats['by_tier'].get(2, 0)} "
        f"T3={stats['by_tier'].get(3, 0)} "
        f"T4={stats['by_tier'].get(4, 0)}"
    )
    print(f"Collection size: {rag.count()}")

    return stats


def main():
    p = argparse.ArgumentParser(description="DC-EPMS PRO tier-aware RAG indexer")
    p.add_argument(
        "--clean",
        action="store_true",
        help="Clear the collection before indexing",
    )
    p.add_argument(
        "--tier",
        type=int,
        choices=[1, 2, 3, 4],
        help="Index only this tier",
    )
    p.add_argument(
        "--test-query",
        type=str,
        help="Run a test query after indexing",
    )
    args = p.parse_args()

    print("DC-EPMS PRO — Tier-Aware RAG Seed v2")
    print("=" * 60)

    rag = RAGService(chroma_path=CHROMA_PATH)

    stats = index_corpus(rag, clean=args.clean, tier_filter=args.tier)

    # Optional test query
    if args.test_query:
        print()
        print("=" * 60)
        print(f"Test query: {args.test_query}")
        print("=" * 60)
        result = rag.query(args.test_query, n_results=3)
        print(f"Safety boosted: {result['safety_boosted']}")
        print(f"Tier distribution: {result['tier_distribution']}")
        print()
        for i, r in enumerate(result["results"], 1):
            print(
                f"[{i}] T{r['tier']} {r['doc_id']} "
                f"sim={r['similarity']:.3f} boost=+{r['boost']:.2f} "
                f"final={r['score']:.3f}"
            )
            print(f"    {r['text'][:150]}...")
            print()

    # Exit code reflects success
    if stats["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
