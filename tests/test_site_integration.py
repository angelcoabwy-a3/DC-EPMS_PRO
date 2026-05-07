"""
Tests for Sprint S1b — integration of site_model with HTTP, CMMS, and agent.

Three groups:
  - TestSiteRoutes: FastAPI endpoints under /api/site/*
  - TestCMMSEnrichment: WO draft injection of location metadata
  - TestAgentSiteTool: agent dispatcher for locate/power_chain/loto_impact/search

Run:
    pytest tests/test_site_integration.py -v
"""
import sys
import pathlib
import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from fastapi import FastAPI
from fastapi.testclient import TestClient

import site_routes
from site_model import reset_site_model
from cmms_site_enrichment import enrich_wo_with_location
from agent_site_tool import tool_query_site_model, TOOL_DEFINITION


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Each test gets a fresh model (avoids state leakage)."""
    reset_site_model()
    yield
    reset_site_model()


@pytest.fixture
def client():
    """FastAPI TestClient mounted with the site_routes router."""
    app = FastAPI()
    site_routes.configure(PROJECT_ROOT)
    app.include_router(site_routes.router)
    return TestClient(app)


# ═══════════════════════════════════════════════════════════════════════
#  HTTP endpoints
# ═══════════════════════════════════════════════════════════════════════
class TestSiteRoutes:

    def test_metadata_returns_tier_iv(self, client):
        r = client.get("/api/site/metadata")
        assert r.status_code == 200
        data = r.json()
        assert data["classification"] == "tier_iv_uptime"
        assert data["redundancy"]["electrical"] == "2N"

    def test_buildings_lists_4(self, client):
        r = client.get("/api/site/buildings")
        assert r.status_code == 200
        data = r.json()
        assert len(data["buildings"]) == 4
        ids = [b["id"] for b in data["buildings"]]
        assert "building-a" in ids
        assert "yard" in ids

    def test_tree_for_building_a_returns_full_subtree(self, client):
        r = client.get("/api/site/tree/building-a")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == "building-a"
        room_ids = [room["id"] for room in data["rooms"]]
        assert "dh-a" in room_ids
        assert "er-a" in room_ids
        assert "mr-a" in room_ids

    def test_tree_for_building_a_includes_rows_with_racks(self, client):
        r = client.get("/api/site/tree/building-a")
        data = r.json()
        dh_a = next(rm for rm in data["rooms"] if rm["id"] == "dh-a")
        assert len(dh_a["rows"]) == 3      # row-a-01, 02, 03
        row_a_01 = next(row for row in dh_a["rows"] if row["id"] == "row-a-01")
        assert len(row_a_01["racks"]) == 10
        assert "rack_a_01_01" in row_a_01["racks"]

    def test_tree_for_yard_returns_mech_plants(self, client):
        r = client.get("/api/site/tree/yard")
        assert r.status_code == 200
        data = r.json()
        room_ids = [r["id"] for r in data["rooms"]]
        assert "mech-plant-north" in room_ids
        assert "mech-plant-south" in room_ids
        assert "genset-bay" in room_ids
        assert "utility-substation" in room_ids
        assert "fuel-storage" in room_ids

    def test_tree_unknown_building_returns_404(self, client):
        r = client.get("/api/site/tree/nonexistent-building")
        assert r.status_code == 404

    def test_components_default_paginated(self, client):
        r = client.get("/api/site/components")
        assert r.status_code == 200
        data = r.json()
        assert data["limit"] == 200
        assert data["offset"] == 0
        assert data["total"] > 30
        assert len(data["items"]) <= 200

    def test_components_filter_by_type_chiller(self, client):
        r = client.get("/api/site/components?type=chiller")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 3
        for item in data["items"]:
            assert item["type"] == "chiller"

    def test_components_pagination_offset(self, client):
        r1 = client.get("/api/site/components?limit=5&offset=0")
        r2 = client.get("/api/site/components?limit=5&offset=5")
        ids1 = [i["canonical_id"] for i in r1.json()["items"]]
        ids2 = [i["canonical_id"] for i in r2.json()["items"]]
        assert set(ids1).isdisjoint(set(ids2))

    def test_components_invalid_limit_400(self, client):
        r = client.get("/api/site/components?limit=99999")
        assert r.status_code == 422   # FastAPI validates via Query(le=1000)

    def test_get_component_chiller_1(self, client):
        r = client.get("/api/site/components/chiller_1")
        assert r.status_code == 200
        data = r.json()
        assert data["canonical_id"] == "chiller_1"
        assert data["type"] == "chiller"
        assert data["rated_tons"] == 1500

    def test_get_component_unknown_404(self, client):
        r = client.get("/api/site/components/nonexistent_widget")
        assert r.status_code == 404

    def test_locate_chiller_returns_path(self, client):
        r = client.get("/api/site/locate/chiller_1")
        assert r.status_code == 200
        data = r.json()
        assert data["location"]["path"] == "A3-Alpha / Yard / Mechanical Plant North"
        assert data["display"] == "Chiller 1 (1500 ton water-cooled)"

    def test_locate_rack_returns_full_path_with_row(self, client):
        r = client.get("/api/site/locate/rack_a_01_05")
        assert r.status_code == 200
        data = r.json()
        assert "Row A-01" in data["location"]["path"]

    def test_locate_unknown_404(self, client):
        r = client.get("/api/site/locate/nope")
        assert r.status_code == 404

    def test_power_chain_for_rack_returns_2n(self, client):
        r = client.get("/api/site/power-chain/rack_a_01_01")
        assert r.status_code == 200
        data = r.json()
        assert data["feed_count"] == 2
        groups = [f["group"] for f in data["feeds"]]
        assert "path_a" in groups
        assert "path_b" in groups

    def test_power_chain_for_yard_root_only_one_feed(self, client):
        # ats_a is a path-A-only component; should have 1 feed group
        r = client.get("/api/site/power-chain/ats_a")
        assert r.status_code == 200
        data = r.json()
        # ats_a is fed by utility_feed_a, genset_a_01, genset_a_02
        # All in path_a group
        assert data["feed_count"] == 1
        assert data["feeds"][0]["group"] == "path_a"
        assert "utility_feed_a" in data["feeds"][0]["roots"]

    def test_power_chain_unknown_404(self, client):
        r = client.get("/api/site/power-chain/unknown")
        assert r.status_code == 404

    def test_impact_default_chain_is_power(self, client):
        r = client.get("/api/site/impact/busway_a_01")
        assert r.status_code == 200
        data = r.json()
        assert data["chain_type"] == "power"
        assert data["immediate_count"] == 10

    def test_impact_with_cooling_chain(self, client):
        r = client.get("/api/site/impact/chiller_1?chain=cooling")
        assert r.status_code == 200
        data = r.json()
        assert data["chain_type"] == "cooling"
        assert "chw_pump_n_01" in data["immediate"]

    def test_impact_invalid_chain_422(self, client):
        r = client.get("/api/site/impact/ups_a?chain=nonsense")
        assert r.status_code == 422

    def test_loto_impact_for_rpp_a_01_no_outage(self, client):
        r = client.get("/api/site/loto-impact/rpp_a_01")
        assert r.status_code == 200
        data = r.json()
        assert len(data["racks_losing_all_redundancy"]) == 0
        assert len(data["racks_affected"]) == 10

    def test_loto_impact_for_unknown_returns_safe_empty(self, client):
        # Tolerant behavior: returns empty rather than 404
        r = client.get("/api/site/loto-impact/nope")
        assert r.status_code == 200
        data = r.json()
        assert data["downstream_count"] == 0


# ═══════════════════════════════════════════════════════════════════════
#  CMMS WO enrichment
# ═══════════════════════════════════════════════════════════════════════
class TestCMMSEnrichment:

    def test_enrichment_adds_location_for_chiller(self):
        wo = {
            "title": "Chiller 1 quarterly PM",
            "description": "Tube cleaning + refrigerant test",
            "priority": "medium",
        }
        enriched = enrich_wo_with_location(wo, "chiller_1", project_root=PROJECT_ROOT)
        assert enriched["target_component_id"] == "chiller_1"
        ctx = enriched["site_context"]
        assert ctx["available"] is True
        assert ctx["location"] == "A3-Alpha / Yard / Mechanical Plant North"
        assert ctx["asset_type"] == "chiller"
        assert ctx["asset_metadata"]["rated_tons"] == 1500

    def test_enrichment_does_not_mutate_original(self):
        wo = {"title": "test", "description": "x"}
        enrich_wo_with_location(wo, "chiller_1", project_root=PROJECT_ROOT)
        # Original unchanged
        assert "site_context" not in wo
        assert "target_component_id" not in wo

    def test_enrichment_for_rack_includes_row(self):
        wo = {"title": "Rack PM"}
        enriched = enrich_wo_with_location(wo, "rack_a_01_05", project_root=PROJECT_ROOT)
        ctx = enriched["site_context"]
        assert "Row A-01" in ctx["location"]
        assert ctx["asset_type"] == "it_rack"

    def test_enrichment_unknown_component_fails_soft(self):
        wo = {"title": "test"}
        enriched = enrich_wo_with_location(wo, "nonexistent", project_root=PROJECT_ROOT)
        ctx = enriched["site_context"]
        assert ctx["available"] is False
        assert "not found" in ctx["error"]
        # Original WO fields preserved
        assert enriched["title"] == "test"

    def test_enrichment_breadcrumb_structure(self):
        wo = {"title": "test"}
        enriched = enrich_wo_with_location(wo, "rack_a_01_05", project_root=PROJECT_ROOT)
        breadcrumb = enriched["site_context"]["location_breadcrumb"]
        levels = [b["level"] for b in breadcrumb]
        assert levels == ["site", "building", "room", "row"]


# ═══════════════════════════════════════════════════════════════════════
#  Agent site tool
# ═══════════════════════════════════════════════════════════════════════
class TestAgentSiteTool:

    def test_tool_definition_has_required_fields(self):
        assert TOOL_DEFINITION["name"] == "query_site_model"
        assert "description" in TOOL_DEFINITION
        schema = TOOL_DEFINITION["input_schema"]
        assert "operation" in schema["properties"]
        assert schema["properties"]["operation"]["enum"] == [
            "locate", "power_chain", "loto_impact", "search",
        ]
        assert "operation" in schema["required"]

    def test_locate_operation_returns_path(self):
        r = tool_query_site_model(
            operation="locate", canonical_id="chiller_1",
            project_root=PROJECT_ROOT,
        )
        assert r["success"] is True
        assert r["operation"] == "locate"
        assert r["location_path"] == "A3-Alpha / Yard / Mechanical Plant North"

    def test_locate_unknown_returns_error_not_raise(self):
        r = tool_query_site_model(
            operation="locate", canonical_id="phantom",
            project_root=PROJECT_ROOT,
        )
        assert r["success"] is False
        assert "not found" in r["error"].lower()

    def test_locate_missing_id_returns_error(self):
        r = tool_query_site_model(
            operation="locate", project_root=PROJECT_ROOT,
        )
        assert r["success"] is False
        assert "required" in r["error"].lower()

    def test_power_chain_operation(self):
        r = tool_query_site_model(
            operation="power_chain", canonical_id="rack_a_01_01",
            project_root=PROJECT_ROOT,
        )
        assert r["success"] is True
        assert r["summary"]["feed_count"] == 2
        assert r["summary"]["is_redundant"] is True

    def test_loto_impact_operation_safe_loto(self):
        r = tool_query_site_model(
            operation="loto_impact", canonical_id="rpp_a_01",
            project_root=PROJECT_ROOT,
        )
        assert r["success"] is True
        s = r["summary"]
        assert s["total_racks_affected"] == 10
        assert s["racks_at_outage_risk"] == 0
        assert s["is_safe_loto"] is True

    def test_loto_impact_includes_location(self):
        r = tool_query_site_model(
            operation="loto_impact", canonical_id="rpp_a_01",
            project_root=PROJECT_ROOT,
        )
        assert "Electrical Room A" in r["summary"]["target_location"]

    def test_search_with_query_finds_chillers(self):
        r = tool_query_site_model(
            operation="search", search_query="chiller",
            project_root=PROJECT_ROOT,
        )
        assert r["success"] is True
        assert r["count"] == 3
        for item in r["results"]:
            assert "chiller" in item["canonical_id"].lower()

    def test_search_with_type_filter(self):
        r = tool_query_site_model(
            operation="search", type_filter="genset",
            project_root=PROJECT_ROOT,
        )
        assert r["success"] is True
        assert r["count"] == 4

    def test_search_combined_query_and_type(self):
        r = tool_query_site_model(
            operation="search", search_query="rack_a_01",
            type_filter="it_rack", project_root=PROJECT_ROOT,
        )
        assert r["success"] is True
        # rack_a_01_01 through rack_a_01_10 = 10
        assert r["count"] == 10

    def test_search_no_match_returns_empty(self):
        r = tool_query_site_model(
            operation="search", search_query="zzznonexistent",
            project_root=PROJECT_ROOT,
        )
        assert r["success"] is True
        assert r["count"] == 0

    def test_invalid_operation_returns_error(self):
        r = tool_query_site_model(
            operation="invalid_op", canonical_id="chiller_1",
            project_root=PROJECT_ROOT,
        )
        assert r["success"] is False
        assert "unknown operation" in r["error"].lower()

    def test_search_truncation_flag(self):
        # Search with no filter returns ALL components; check truncation
        r = tool_query_site_model(
            operation="search", project_root=PROJECT_ROOT,
        )
        # We have ~50+ components total
        if r["count"] >= 50:
            # at the cap
            assert r["truncated"] is True or r["count"] == 50
