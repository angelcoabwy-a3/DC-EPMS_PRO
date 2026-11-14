"""
tests/test_site_model_v2.py
===========================
DC-EPMS-068 -- backend/site_model_v2.py + scripts/build_site_model_v2.py.

  * v2 is consistent with the closed design and loads in SiteModel.
  * The committed config/site_model_v2.yml and telemetry_mapping_v2.yml
    are not stale (single source of truth: power_plant.yml).
  * The same validator flags the legacy model (DC-EPMS-058).
  * Mutations of the design are caught (N+1, 2N, voltage).
  * The Power Controls roster and v2 share one identity.
"""

from __future__ import annotations

import copy
import pathlib
import subprocess
import sys

import pytest
import yaml

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from site_model import SiteModel  # noqa: E402

from backend import site_model_v2 as v2  # noqa: E402
from backend.device_control import DeviceController, load_design  # noqa: E402

LEGACY = yaml.safe_load((PROJECT_ROOT / "config" / "site_model.yml").read_text(encoding="utf-8"))
PLANT = yaml.safe_load((PROJECT_ROOT / "config" / "power_plant.yml").read_text(encoding="utf-8"))
V2_PATH = PROJECT_ROOT / "config" / "site_model_v2.yml"


@pytest.fixture(scope="module")
def model() -> dict:
    return v2.build(LEGACY, PLANT)


@pytest.fixture(scope="module")
def site(tmp_path_factory, model) -> SiteModel:
    path = tmp_path_factory.mktemp("v2") / "site_model_v2.yml"
    path.write_text(yaml.safe_dump(model, sort_keys=False), encoding="utf-8")
    sm = SiteModel(yaml_path=path)
    sm.load()
    return sm


class TestBuild:
    def test_v2_is_consistent_with_the_closed_design(self, model):
        assert v2.validate(model, PLANT) == []

    def test_build_is_deterministic_and_pure(self, model):
        before = copy.deepcopy(LEGACY)
        assert v2.build(LEGACY, PLANT) == model
        assert before == LEGACY

    def test_phase1_train_per_path(self, model):
        comps = model["components"]
        for p in ("a", "b"):
            ups = [c for c in comps if c.startswith(f"ups_{p}_") and comps[c]["type"] == "ups"]
            gens = [c for c in comps if c.startswith(f"genset_{p}_") and comps[c]["type"] == "genset"]
            assert len(ups) == 8
            assert len(gens) == 9
            assert all(comps[u]["model"] == "Trinergy 2500" for u in ups)
            assert all(comps[g]["rated_kw"] == 2750 and comps[g]["voltage_kv"] == 13.8 for g in gens)
            assert comps[f"mvtc_{p}"]["type"] == "mv_transfer_controller"
            for legacy_id in (f"ats_{p}", f"xfmr_{p}", f"switchgear_{p}", f"ups_{p}"):
                assert legacy_id not in comps

    def test_no_480v_ats_and_no_480v_generator(self, model):
        comps = model["components"]
        assert not any(m.get("type") == "ats" for m in comps.values())
        gens = [m for m in comps.values() if m.get("type") == "genset"]
        assert gens
        assert all("voltage_v" not in m and "incident_energy_cal" not in m for m in gens)

    def test_sizing_assumptions_are_stated(self, model):
        size = v2.sizing(PLANT)
        assert size == {"unit_sub_kva": 3500, "lv_swbd_amps": 5000,
                        "lv_secondary_amps": 4210, "mv_xfmr_kva": 25000}
        assert "assumption" in model["components"]["unit_sub_a_01"]["sizing"]
        assert "assumption" in model["components"]["mv_xfmr_a"]["sizing"]

    def test_micro_components_of_a_kept_genset_survive(self, model):
        comps = model["components"]
        assert comps["genset_a_01_starter_battery"]["parent"] == "genset_a_01"
        assert comps["genset_a_01"]["parent"] == "sys_backup_power"

    def test_building_d_and_cooling_are_untouched(self, model):
        d_old = [e for e in LEGACY["power_chains"] if e["from"].endswith("_d") or "_d_" in e["from"]]
        d_new = [e for e in model["power_chains"] if e["from"].endswith("_d") or "_d_" in e["from"]]
        assert d_old == d_new
        assert d_old
        assert model["cooling_chains"] == LEGACY["cooling_chains"]
        for cid in ("mv_rectifier_d", "gen_farm_d", "stepup_xfmr_d"):
            assert model["components"][cid] == LEGACY["components"][cid]

    def test_every_new_component_has_a_room(self, model):
        located = {c for b in model["buildings"] for r in b.get("rooms") or [] for c in r.get("components") or []}
        for p in ("a", "b"):
            for members in v2.phase1_ids(p, PLANT).values():
                assert set(members) <= located


class TestValidatorFences:
    def test_legacy_model_shows_dc_epms_058(self):
        mismatches = v2.voltage_mismatches(LEGACY, v2.phase1_power_nodes(LEGACY))
        assert "utility_feed_a (27.5 kV) -> ats_a (0.48 kV)" in mismatches
        assert v2.voltage_mismatches({"components": {}, "power_chains": []}, set()) == []

    def test_superseded_generators_fail_n_plus_1(self):
        plant = copy.deepcopy(PLANT)
        plant["generators"]["rated_kw"] = 2500
        problems = v2.validate(v2.build(LEGACY, plant), plant)
        assert any("generation N+1 20000.0 kW below 21500.0 kW" in p for p in problems)

    def test_broken_2n_is_caught(self, model):
        broken = copy.deepcopy(model)
        broken["power_chains"] = [e for e in broken["power_chains"]
                                  if not (e["from"] == "rpp_b_01" and e["to"] == "busway_b_01")]
        assert any("rack_a_01_01 is not fed through mvtc_b" in p for p in v2.validate(broken, PLANT))

    def test_voltage_mismatch_is_caught(self, model):
        broken = copy.deepcopy(model)
        broken["components"]["lv_swbd_a_03"]["voltage_v"] = 600
        assert any("unit_sub_a_03 (0.48 kV) -> lv_swbd_a_03 (0.6 kV)" in p for p in v2.validate(broken, PLANT))

    def test_dangling_chain_is_caught(self, model):
        broken = copy.deepcopy(model)
        broken["power_chains"].append({"from": "ghost", "to": "ups_a_01"})
        assert "chain endpoint 'ghost' is not a component" in v2.validate(broken, PLANT)


class TestLoadsInSiteModel:
    def test_load_and_counts(self, site):
        assert len(site.list_components(type_filter="ups")) == 16
        assert len(site.list_components(type_filter="genset")) == 18
        assert len(site.list_components(type_filter="mv_transfer_controller")) == 2
        assert site.locate("ups_a_01").room_id == "er-a"
        assert site.locate("mvtc_b").room_id == "utility-substation"

    def test_rack_is_fed_by_both_paths(self, site):
        feeds = site.power_chain_for("rack_a_01_01")["feeds"]
        paths = [" ".join(f["representative_path"]) for f in feeds]
        assert any("mvtc_a" in p and "ups_a_01" in p for p in paths)
        assert any("mvtc_b" in p and "ups_b_01" in p for p in paths)

    def test_loto_on_one_ups_block_keeps_every_rack(self, site):
        impact = site.loto_impact("ups_a_01")
        assert len(impact["racks_affected"]) == 10
        assert impact["racks_losing_all_redundancy"] == []

    def test_loto_on_a_whole_transfer_controller_keeps_path_b(self, site):
        assert site.loto_impact("mvtc_a")["racks_losing_all_redundancy"] == []


class TestCommittedFiles:
    def test_generated_files_are_not_stale(self):
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "build_site_model_v2.py"), "--check"],
            capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "GENERATED" in V2_PATH.read_text(encoding="utf-8").splitlines()[0]

    def test_power_controls_roster_is_a_subset_of_v2(self, model):
        ctl = DeviceController.from_design(load_design(PROJECT_ROOT / "config" / "power_plant.yml"))
        assert set(ctl.devices) <= set(model["components"])
        assert set(ctl.bays) == {c for c, m in model["components"].items() if m.get("type") == "genset"
                                 and m.get("path") in ("a", "b")}


class TestTelemetryMapping:
    def test_symmetric_instrumentation(self, model):
        mapping = v2.telemetry_mapping(model, PLANT)
        per_path = {"a": 0, "b": 0}
        for dev in mapping["devices"]:
            per_path[dev["path"]] += len(dev["points"])
        assert per_path["a"] == per_path["b"] > 200

    def test_no_writable_points_and_ac_phase_naming(self, model):
        mapping = v2.telemetry_mapping(model, PLANT)
        tags = [pt for d in mapping["devices"] for pt in d["points"]]
        assert not any(pt["writable"] for pt in tags)
        names = " ".join(pt["tag"] for pt in tags)
        assert "PWR.UPS_A01.V_PHASE_AB" in names
        assert "PWR.GENSET_B09.CB_52G_POS" in names
        assert "DC_BUS" not in names
        assert "800" not in names
        assert "/api/devices" in mapping["write_path"]

    def test_every_legacy_power_tag_is_mapped(self):
        tags = yaml.safe_load((PROJECT_ROOT / "config" / "bms_tags.yml").read_text(encoding="utf-8"))
        tags = tags.get("tags", tags)
        names = list(tags) if isinstance(tags, dict) else [t.get("tag") or t.get("id") for t in tags]
        legacy = [n for n in names if str(n).startswith(("PWR.UPS", "PWR.ATS", "PWR.GEN", "PWR.XFMR"))]
        assert legacy
        assert sorted(set(legacy) - set(v2.LEGACY_TAG_MAP)) == []
