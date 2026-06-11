"""
tests/test_graphrag.py - Sprint S2 coverage tests

Tests cover:
  - Knowledge corpus loading and frontmatter parsing
  - Graph construction (component+location+knowledge nodes; edges)
  - Upstream chain BFS
  - Applicable knowledge resolution by component type
  - Jurisdiction filtering (Ontario priority)
  - GraphRAGService end-to-end (with lazy-loaded index)
  - FastAPI routes via TestClient

Heavy: this triggers the model download on first run if not cached.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from graphrag_index import (  # noqa: E402
    _chunk_text,
    _split_frontmatter,
    load_knowledge_corpus,
)
from graphrag_service import GraphRAGService  # noqa: E402
from knowledge_graph import (  # noqa: E402
    build_knowledge_graph,
    filter_by_jurisdiction,
    get_applicable_knowledge,
    get_upstream_chain,
)
from site_model import SiteModel  # noqa: E402

CORPUS_DIR = ROOT / "config" / "knowledge"
SITE_MODEL_PATH = ROOT / "config" / "site_model.yml"


# ────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def site_model():
    sm = SiteModel(yaml_path=SITE_MODEL_PATH)
    sm.load()
    return sm


@pytest.fixture(scope="module")
def docs():
    return load_knowledge_corpus(CORPUS_DIR)


@pytest.fixture(scope="module")
def graph(site_model, docs):
    return build_knowledge_graph(site_model, docs)


@pytest.fixture(scope="module")
def service(site_model):
    return GraphRAGService(site_model, CORPUS_DIR)


# ────────────────────────────────────────────────────────────────────
# Frontmatter & chunking
# ────────────────────────────────────────────────────────────────────
def test_split_frontmatter_basic():
    raw = "---\nid: x\ntitle: T\n---\nbody here"
    meta, body = _split_frontmatter(raw)
    assert meta["id"] == "x"
    assert meta["title"] == "T"
    assert body.strip() == "body here"


def test_split_frontmatter_no_frontmatter():
    raw = "no frontmatter at all"
    meta, body = _split_frontmatter(raw)
    assert meta == {}
    assert body == raw


def test_chunk_text_short():
    assert _chunk_text("hello world") == ["hello world"]


def test_chunk_text_long_overlaps():
    text = " ".join([f"w{i}" for i in range(500)])
    chunks = _chunk_text(text)
    assert len(chunks) > 1
    # overlap: last 50 words of chunk i appear in start of chunk i+1
    first = chunks[0].split()
    second = chunks[1].split()
    overlap = set(first[-50:]) & set(second[:50])
    assert len(overlap) >= 40  # most words overlap


# ────────────────────────────────────────────────────────────────────
# Corpus loading
# ────────────────────────────────────────────────────────────────────
def test_corpus_has_baseline_docs(docs):
    # The 5 baseline docs that shipped at v0.5.0 must remain present.
    # The corpus has since grown (CDU 2d4ea37, then the Epic 6 Commit 2
    # electrical/distribution/Eaton triple) -- use >= to stay resilient
    # against future additions and check named presence instead of an
    # exact count.
    ids = sorted(d.id for d in docs)
    assert len(docs) >= 5
    assert "nvidia-800vdc" in ids
    assert "ocp-lvdc" in ids
    assert "stmicro-bms" in ids
    assert "csa-z462-24" in ids
    assert "oesc-ontario-28" in ids


def test_csa_z462_jurisdiction_canada(docs):
    csa = next(d for d in docs if d.id == "csa-z462-24")
    assert csa.jurisdiction == "canada"


def test_oesc_jurisdiction_ontario(docs):
    oesc = next(d for d in docs if d.id == "oesc-ontario-28")
    assert oesc.jurisdiction == "ontario_canada"


# ────────────────────────────────────────────────────────────────────
# Graph construction
# ────────────────────────────────────────────────────────────────────
def test_graph_has_expected_component_count(graph):
    components = [n for n, d in graph.nodes(data=True) if d.get("kind") == "component"]
    # 91 original + 7 Path D (Phase 2 SLD) + 12 G1 taxonomy slice
    # (2 system roots + 10 genset/CDU micro-components) + 3 Path D
    # standby generation (50 MW track: gen_farm_d, mv_bus_d,
    # stepup_xfmr_d) = 113.
    assert len(components) == 113


def test_graph_has_baseline_knowledge_nodes(graph):
    # Same rationale as `test_corpus_has_baseline_docs` -- corpus has
    # grown post-v0.5.0; use >= to stay resilient.
    knowledge = [n for n, d in graph.nodes(data=True) if d.get("kind") == "knowledge"]
    assert len(knowledge) >= 5


def test_graph_has_type_marker_nodes(graph):
    types = [n for n, d in graph.nodes(data=True) if d.get("kind") == "component_type"]
    # Roughly: 5 docs * avg 5 types = 25 unique-ish, but depends on overlaps
    assert len(types) >= 10


def test_chiller_1_in_graph(graph):
    assert "chiller_1" in graph
    node = graph.nodes["chiller_1"]
    assert node["kind"] == "component"
    assert node["type"] == "chiller"


# ────────────────────────────────────────────────────────────────────
# Knowledge resolution
# ────────────────────────────────────────────────────────────────────
def test_chiller_has_csa_z462(graph):
    """A chiller in Ontario should be governed by CSA Z462-24."""
    knowledge = get_applicable_knowledge(graph, "chiller_1")
    ids = {k["id"] for k in knowledge}
    # The chiller type is in CSA Z462's applies_to list
    assert "csa-z462-24" in ids


def test_jurisdiction_filter_ontario_keeps_canadian(graph):
    knowledge = get_applicable_knowledge(graph, "chiller_1")
    filtered = filter_by_jurisdiction(knowledge, "ontario_canada")
    juris = {k["jurisdiction"] for k in filtered}
    # international + canada + ontario_canada all kept
    assert "ontario_canada" in juris or "canada" in juris


def test_jurisdiction_filter_excludes_non_applicable(graph):
    """Verify pure 'international' docs always pass."""
    knowledge = [
        {"id": "a", "jurisdiction": "international"},
        {"id": "b", "jurisdiction": "us_only"},
        {"id": "c", "jurisdiction": "ontario_canada"},
    ]
    filtered = filter_by_jurisdiction(knowledge, "ontario_canada")
    ids = {k["id"] for k in filtered}
    assert "a" in ids
    assert "c" in ids
    assert "b" not in ids


# ────────────────────────────────────────────────────────────────────
# Upstream chain
# ────────────────────────────────────────────────────────────────────
def test_upstream_rack_has_path_to_utility(graph):
    chain = get_upstream_chain(graph, "rack_a_01_01")
    # Should include at least an RPP
    assert any("rpp" in n for n in chain)


# ────────────────────────────────────────────────────────────────────
# Service end-to-end (triggers model load)
# ────────────────────────────────────────────────────────────────────
@pytest.mark.slow
def test_service_query_basic(service):
    result = service.query("arc flash protection 800VDC", k=3)
    assert "chunks" in result
    assert len(result["chunks"]) <= 3
    assert all("score" in c for c in result["chunks"])
    assert all(0.0 <= c["score"] <= 1.0 for c in result["chunks"])


@pytest.mark.slow
def test_service_query_with_component(service):
    result = service.query(
        "LOTO procedure",
        component_id="chiller_1",
        k=3,
    )
    assert result["component_id"] == "chiller_1"
    assert result["graph_context"]["display"] is not None
    assert isinstance(result["applicable_knowledge"], list)


@pytest.mark.slow
def test_service_loto_with_knowledge(service):
    result = service.loto_with_knowledge("rpp_a_01")
    assert "loto_impact" in result
    assert "applicable_knowledge" in result
    assert "procedure_chunks" in result
    assert isinstance(result["procedure_chunks"], list)


@pytest.mark.slow
def test_service_upstream(service):
    result = service.upstream("rack_a_01_01")
    assert result["component_id"] == "rack_a_01_01"
    assert isinstance(result["chain"], list)


@pytest.mark.slow
def test_service_related_knowledge(service):
    result = service.related_knowledge("chiller_1")
    assert result["component_id"] == "chiller_1"
    assert isinstance(result["knowledge"], list)
