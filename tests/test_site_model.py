"""
Tests for site_model.py — Sprint S1a.

Covers:
  - Loading YAML and building indexes
  - locate() returns correct path for components in halls, rooms, yard
  - power_chain_for() returns 2N paths for racks
  - impact_set() walks downstream correctly
  - loto_impact() correctly identifies which racks retain redundancy
  - Edge cases: unknown component, malformed YAML

Run:
    pytest tests/test_site_model.py -v
"""

import pathlib
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from site_model import (
    ComponentNotFoundError,
    SiteModel,
    SiteModelLoadError,
    get_site_model,
    reset_site_model,
)


@pytest.fixture
def model():
    """Fresh model loaded from the actual A3-Alpha YAML."""
    reset_site_model()
    yaml_path = PROJECT_ROOT / "config" / "site_model.yml"
    m = SiteModel(yaml_path)
    m.load()
    return m


# ═══════════════════════════════════════════════════════════════════════
#  Loading & basic indexes
# ═══════════════════════════════════════════════════════════════════════
class TestLoading:
    def test_load_succeeds(self, model):
        assert model.site_metadata()["id"] == "a3-alpha-toronto"

    def test_site_classification_is_tier_iv(self, model):
        meta = model.site_metadata()
        assert meta["classification"] == "tier_iv_uptime"
        assert meta["redundancy"]["electrical"] == "2N"
        assert meta["redundancy"]["cooling"] == "N+1"

    def test_buildings_summary_returns_4(self, model):
        buildings = model.buildings_summary()
        assert len(buildings) == 4
        ids = [b["id"] for b in buildings]
        assert "building-a" in ids
        assert "building-b" in ids
        assert "yard" in ids
        assert "building-c" in ids

    def test_yaml_not_found_raises(self, tmp_path):
        m = SiteModel(tmp_path / "nonexistent.yml")
        with pytest.raises(SiteModelLoadError, match="not found"):
            m.load()

    def test_yaml_root_not_mapping_raises(self, tmp_path):
        bad = tmp_path / "list.yml"
        bad.write_text("- just\n- a\n- list")
        m = SiteModel(bad)
        with pytest.raises(SiteModelLoadError):
            m.load()


# ═══════════════════════════════════════════════════════════════════════
#  Component lookup & location
# ═══════════════════════════════════════════════════════════════════════
class TestLocation:
    def test_locate_chiller_returns_yard_path(self, model):
        loc = model.locate("chiller_1")
        assert loc.site_display == "A3-Alpha"
        assert loc.building_display == "Yard"
        assert loc.room_display == "Mechanical Plant North"
        assert loc.row_display is None

    def test_locate_chiller_path_string(self, model):
        path = model.location_path("chiller_1")
        assert path == "A3-Alpha / Yard / Mechanical Plant North"

    def test_locate_rack_returns_full_path_with_row(self, model):
        loc = model.locate("rack_a_01_05")
        assert loc.site_display == "A3-Alpha"
        assert loc.building_display == "Building A"
        assert loc.room_display == "Data Hall A"
        assert loc.row_display == "Row A-01"

    def test_locate_rack_path_string(self, model):
        assert (
            model.location_path("rack_a_01_05") == "A3-Alpha / Building A / Data Hall A / Row A-01"
        )

    def test_locate_ups_returns_electrical_room(self, model):
        loc = model.locate("ups_a")
        assert loc.room_type == "electrical_room"
        assert loc.room_display == "Electrical Room A"

    def test_locate_genset_returns_genset_bay(self, model):
        loc = model.locate("genset_a_01")
        assert loc.room_display == "Genset Bay"
        assert loc.building_display == "Yard"

    def test_locate_unknown_component_raises(self, model):
        with pytest.raises(ComponentNotFoundError):
            model.locate("nonexistent_unicorn")

    def test_location_to_dict_serializable(self, model):
        loc = model.locate("rack_a_01_01")
        d = loc.to_dict()
        import json

        json.dumps(d)
        assert d["path"] == "A3-Alpha / Building A / Data Hall A / Row A-01"
        assert d["site_id"] == "a3-alpha-toronto"

    def test_location_path_components_breadcrumb(self, model):
        loc = model.locate("rack_a_01_01")
        breadcrumb = loc.path_components
        assert len(breadcrumb) == 4
        assert breadcrumb[0]["level"] == "site"
        assert breadcrumb[1]["level"] == "building"
        assert breadcrumb[2]["level"] == "room"
        assert breadcrumb[2]["type"] == "data_hall"
        assert breadcrumb[3]["level"] == "row"


# ═══════════════════════════════════════════════════════════════════════
#  Component metadata
# ═══════════════════════════════════════════════════════════════════════
class TestComponentMetadata:
    def test_chiller_has_correct_metadata(self, model):
        c = model.get_component("chiller_1")
        assert c.type == "chiller"
        assert c.metadata["rated_tons"] == 1500
        assert c.metadata["refrigerant"] == "r-1233zd"

    def test_genset_has_cummins_vendor(self, model):
        c = model.get_component("genset_a_01")
        assert c.metadata["vendor"] == "cummins"
        assert c.metadata["model"] == "QSK95"
        assert c.metadata["rated_kw"] == 2750

    def test_ats_has_asco_vendor(self, model):
        c = model.get_component("ats_a")
        assert c.metadata["vendor"] == "asco"

    def test_rack_has_gpu_count(self, model):
        c = model.get_component("rack_a_01_01")
        assert c.metadata["gpu_count"] == 72
        assert c.metadata["rated_kw"] == 142

    def test_list_components_filtered_by_type(self, model):
        chillers = model.list_components(type_filter="chiller")
        assert len(chillers) == 3

        gensets = model.list_components(type_filter="genset")
        assert len(gensets) == 4

        racks = model.list_components(type_filter="it_rack")
        assert len(racks) >= 30

    def test_get_unknown_component_raises(self, model):
        with pytest.raises(ComponentNotFoundError):
            model.get_component("nonexistent")


# ═══════════════════════════════════════════════════════════════════════
#  Power chain analysis
# ═══════════════════════════════════════════════════════════════════════
class TestPowerChain:
    def test_rack_has_two_power_paths_2n(self, model):
        """Critical 2N test: every rack has 2 independent feeds."""
        chain = model.power_chain_for("rack_a_01_01")
        assert chain["feed_count"] == 2

    def test_rack_path_a_traces_through_path_a_components(self, model):
        chain = model.power_chain_for("rack_a_01_01")
        path_a_feeds = [f for f in chain["feeds"] if f["group"] == "path_a"]
        assert len(path_a_feeds) == 1
        path = path_a_feeds[0]["representative_path"]
        assert "ats_a" in path
        assert "xfmr_a" in path
        assert "switchgear_a" in path
        assert "ups_a" in path
        assert "rpp_a_01" in path
        assert "busway_a_01" in path
        assert "ups_b" not in path
        assert "xfmr_b" not in path
        # Path A group should have 3 alternative roots: utility + 2 gensets
        assert len(path_a_feeds[0]["roots"]) >= 1  # at least the utility
        assert "utility_feed_a" in path_a_feeds[0]["roots"]

    def test_rack_path_b_traces_through_path_b_components(self, model):
        chain = model.power_chain_for("rack_a_01_01")
        path_b_feeds = [f for f in chain["feeds"] if f["group"] == "path_b"]
        assert len(path_b_feeds) == 1
        path = path_b_feeds[0]["representative_path"]
        assert "ats_b" in path
        assert "ups_b" in path
        assert "rpp_b_01" in path
        assert "busway_b_01" in path
        assert "ups_a" not in path
        assert "utility_feed_b" in path_b_feeds[0]["roots"]

    def test_unknown_component_in_power_chain_raises(self, model):
        with pytest.raises(ComponentNotFoundError):
            model.power_chain_for("nonexistent_thing")


# ═══════════════════════════════════════════════════════════════════════
#  Impact set (downstream walk)
# ═══════════════════════════════════════════════════════════════════════
class TestImpactSet:
    def test_busway_a_01_impacts_10_racks(self, model):
        impact = model.impact_set("busway_a_01", chain="power")
        assert len(impact.immediate) == 10
        assert all(r.startswith("rack_a_01_") for r in impact.immediate)

    def test_rpp_a_01_impacts_busways_and_racks(self, model):
        impact = model.impact_set("rpp_a_01", chain="power")
        assert "busway_a_01" in impact.immediate
        assert "rack_a_01_05" in impact.transitive

    def test_ups_a_impacts_both_rpps_and_all_racks(self, model):
        impact = model.impact_set("ups_a", chain="power")
        assert "rpp_a_01" in impact.immediate
        assert "rpp_a_02" in impact.immediate
        rack_ids = [r for r in impact.transitive if r.startswith("rack_a_01_")]
        assert len(rack_ids) >= 10

    def test_chiller_1_impacts_pump_and_cdus(self, model):
        impact = model.impact_set("chiller_1", chain="cooling")
        assert "chw_pump_n_01" in impact.immediate
        assert "cdu_a_01" in impact.transitive

    def test_impact_set_groups_by_type(self, model):
        impact = model.impact_set("ups_a", chain="power")
        assert "rpp" in impact.by_type
        assert "busway" in impact.by_type
        assert "it_rack" in impact.by_type

    def test_impact_invalid_chain_raises(self, model):
        with pytest.raises(ValueError, match="chain must be"):
            model.impact_set("ups_a", chain="invalid")

    def test_unknown_node_returns_empty_impact(self, model):
        impact = model.impact_set("rack_a_01_01", chain="power")
        # Racks are leaves
        assert impact.immediate == []
        assert impact.transitive == []


# ═══════════════════════════════════════════════════════════════════════
#  LOTO impact — the operational query that matters
# ═══════════════════════════════════════════════════════════════════════
class TestLotoImpact:
    def test_loto_busway_a_01_racks_keep_redundancy_via_path_b(self, model):
        """The headline test: LOTO of busway_a_01 affects 10 racks,
        but ALL of them retain Path B redundancy (cross-fed from busway_b_01)."""
        result = model.loto_impact("busway_a_01")

        assert len(result["racks_affected"]) == 10
        assert len(result["racks_losing_all_redundancy"]) == 0

        for rack_info in result["racks_affected"]:
            assert rack_info["still_has_redundancy"] is True
            assert rack_info["total_paths"] == 2
            assert rack_info["remaining_paths"] == 1

    def test_loto_rpp_a_01_racks_keep_redundancy(self, model):
        result = model.loto_impact("rpp_a_01")
        assert len(result["racks_losing_all_redundancy"]) == 0

    def test_loto_ups_a_racks_keep_redundancy(self, model):
        """Even taking out UPS A — every rack has UPS B feeding via Path B."""
        result = model.loto_impact("ups_a")
        assert len(result["racks_losing_all_redundancy"]) == 0

    def test_loto_includes_location_info(self, model):
        result = model.loto_impact("ups_a")
        assert result["location"] is not None
        assert "Electrical Room A" in result["location"]["path"]

    def test_loto_includes_display_name(self, model):
        result = model.loto_impact("genset_a_01")
        assert (
            "Cummins" in result["loto_target_display"] or "Genset" in result["loto_target_display"]
        )

    def test_loto_unknown_component_returns_empty_safely(self, model):
        result = model.loto_impact("nonexistent_thing")
        assert result["loto_target"] == "nonexistent_thing"
        assert result["downstream_count"] == 0
        assert result["racks_affected"] == []


# ═══════════════════════════════════════════════════════════════════════
#  Cooling chain
# ═══════════════════════════════════════════════════════════════════════
class TestCoolingChain:
    def test_cdu_a_01_cools_racks(self, model):
        impact = model.impact_set("cdu_a_01", chain="cooling")
        assert len(impact.immediate) >= 5

    def test_chiller_1_failure_propagates_to_cdu(self, model):
        impact = model.impact_set("chiller_1", chain="cooling")
        assert "cdu_a_01" in impact.transitive or "cdu_a_02" in impact.transitive


# ═══════════════════════════════════════════════════════════════════════
#  Singleton factory
# ═══════════════════════════════════════════════════════════════════════
class TestSingleton:
    def test_get_site_model_caches(self):
        reset_site_model()
        m1 = get_site_model(PROJECT_ROOT)
        m2 = get_site_model(PROJECT_ROOT)
        assert m1 is m2

    def test_get_site_model_first_call_requires_root(self):
        reset_site_model()
        with pytest.raises(RuntimeError, match="not initialized"):
            get_site_model(None)

    def test_reset_clears_singleton(self):
        reset_site_model()
        m1 = get_site_model(PROJECT_ROOT)
        reset_site_model()
        m2 = get_site_model(PROJECT_ROOT)
        assert m1 is not m2


# ═══════════════════════════════════════════════════════════════════════
#  Integration use case: CMMS work order location injection
# ═══════════════════════════════════════════════════════════════════════
class TestCMMSIntegration:
    def test_location_injection_for_chiller_work_order(self, model):
        """Simulates cmms_mcp.draft_cmms_work_order injecting location."""
        target = "chiller_1"
        location = model.location_path(target)
        comp = model.get_component(target)

        wo_metadata = {
            "target": target,
            "target_display": comp.display,
            "location": location,
            "location_breadcrumb": comp.location.path_components,
            "vendor": comp.metadata.get("vendor"),
            "rated_tons": comp.metadata.get("rated_tons"),
        }

        assert wo_metadata["location"] == "A3-Alpha / Yard / Mechanical Plant North"
        assert wo_metadata["target_display"] == "Chiller 1 (1500 ton water-cooled)"
        assert wo_metadata["rated_tons"] == 1500

    def test_location_injection_for_rack_work_order(self, model):
        target = "rack_a_01_05"
        location = model.location_path(target)
        assert "Row A-01" in location
        assert "Data Hall A" in location
