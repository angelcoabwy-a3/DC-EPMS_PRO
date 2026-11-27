"""
DC-EPMS-068 lote A -- runtime switch DC_EPMS_SITE_MODEL.

legacy stays the default (what Render runs). v2 loads only when the
generated file matches site_model.yml + power_plant.yml and passes the
validator; anything else fails closed.
"""

from __future__ import annotations

import pathlib
import shutil
import sys

import pytest
import yaml

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

import site_model as sm  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.delenv(sm.ENV_SITE_MODEL, raising=False)
    sm.reset_site_model()
    yield
    sm.reset_site_model()


def _copy_config(tmp_path: pathlib.Path) -> pathlib.Path:
    cfg = tmp_path / "config"
    cfg.mkdir()
    for name in ("site_model.yml", "site_model_v2.yml", "power_plant.yml"):
        shutil.copy(PROJECT_ROOT / "config" / name, cfg / name)
    return tmp_path


class TestVariantSelection:
    @pytest.mark.parametrize("raw", ["", "legacy", "LEGACY", "  legacy "])
    def test_default_and_explicit_legacy(self, monkeypatch, raw):
        monkeypatch.setenv(sm.ENV_SITE_MODEL, raw)
        assert sm.site_model_variant() == "legacy"

    def test_unset_is_legacy(self):
        assert sm.site_model_variant() == "legacy"

    def test_v2_case_insensitive(self, monkeypatch):
        monkeypatch.setenv(sm.ENV_SITE_MODEL, "V2")
        assert sm.site_model_variant() == "v2"

    @pytest.mark.parametrize("raw", ["v3", "2", "true", "site_model_v2.yml"])
    def test_unknown_value_fails_closed(self, monkeypatch, raw):
        monkeypatch.setenv(sm.ENV_SITE_MODEL, raw)
        with pytest.raises(sm.SiteModelConfigError, match="DC_EPMS_SITE_MODEL"):
            sm.site_model_variant()
        with pytest.raises(sm.SiteModelConfigError):
            sm.get_site_model(PROJECT_ROOT)

    def test_paths(self):
        assert sm.site_model_path(PROJECT_ROOT, "legacy").name == "site_model.yml"
        assert sm.site_model_path(PROJECT_ROOT, "v2").name == "site_model_v2.yml"
        with pytest.raises(sm.SiteModelConfigError):
            sm.site_model_path(PROJECT_ROOT, "v9")


class TestLoading:
    def test_default_loads_legacy_unchanged(self):
        m = sm.get_site_model(PROJECT_ROOT)
        assert m.variant == "legacy"
        assert m.yaml_path.name == "site_model.yml"
        assert len(m.list_components()) == 124
        assert m.get_component("ups_a")  # retired id still present on legacy

    def test_v2_loads_closed_design(self, monkeypatch):
        monkeypatch.setenv(sm.ENV_SITE_MODEL, "v2")
        m = sm.get_site_model(PROJECT_ROOT)
        assert m.variant == "v2"
        assert m.yaml_path.name == "site_model_v2.yml"
        ids = {c.canonical_id for c in m.list_components()}
        assert len(ids) == 188
        for retired in ("ups_a", "ats_a", "xfmr_a", "switchgear_a"):
            assert retired not in ids
        assert {"ups_a_01", "ups_b_08", "genset_a_09", "mvtc_a", "mvtc_b"} <= ids

    def test_v2_keeps_2n_on_a_ups_block_loto(self, monkeypatch):
        monkeypatch.setenv(sm.ENV_SITE_MODEL, "v2")
        m = sm.get_site_model(PROJECT_ROOT)
        impact = m.loto_impact("ups_a_01")
        assert impact["racks_losing_all_redundancy"] == []

    def test_v2_refuses_stale_file(self, monkeypatch, tmp_path):
        root = _copy_config(tmp_path)
        plant_path = root / "config" / "power_plant.yml"
        plant = yaml.safe_load(plant_path.read_text(encoding="utf-8"))
        plant["generators"]["units_per_path"] = 10  # input changed, file not rebuilt
        plant_path.write_text(yaml.safe_dump(plant, sort_keys=False), encoding="utf-8")
        monkeypatch.setenv(sm.ENV_SITE_MODEL, "v2")
        with pytest.raises(sm.SiteModelConfigError, match="stale"):
            sm.get_site_model(root)

    def test_v2_refuses_missing_input(self, monkeypatch, tmp_path):
        root = _copy_config(tmp_path)
        (root / "config" / "power_plant.yml").unlink()
        monkeypatch.setenv(sm.ENV_SITE_MODEL, "v2")
        with pytest.raises(sm.SiteModelConfigError, match="missing"):
            sm.get_site_model(root)

    def test_v2_refuses_invalid_model(self, monkeypatch, tmp_path):
        root = _copy_config(tmp_path)
        monkeypatch.setenv(sm.ENV_SITE_MODEL, "v2")
        import backend.site_model_v2 as v2mod

        monkeypatch.setattr(v2mod, "validate", lambda model, plant: ["forced problem"])
        with pytest.raises(sm.SiteModelConfigError, match="forced problem"):
            sm.get_site_model(root)


class TestModelRoute:
    def _client(self):
        import site_routes
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        site_routes.configure(PROJECT_ROOT)
        app = FastAPI()
        app.include_router(site_routes.router)
        return TestClient(app)

    def test_reports_legacy_by_default(self):
        body = self._client().get("/api/site/model").json()
        assert body["variant"] == "legacy"
        assert body["file"] == "config/site_model.yml"
        assert body["components"] == 124
        assert "ups_a" in body["retired_ids_present"]
        assert body["migration_complete"] is False

    def test_reports_v2(self, monkeypatch):
        monkeypatch.setenv(sm.ENV_SITE_MODEL, "v2")
        body = self._client().get("/api/site/model").json()
        assert body["variant"] == "v2"
        assert body["file"] == "config/site_model_v2.yml"
        assert body["components"] == 188
        assert body["retired_ids_present"] == []
        assert body["verified_against_power_plant"] is True

    def test_bad_flag_is_a_500_not_a_silent_fallback(self, monkeypatch):
        monkeypatch.setenv(sm.ENV_SITE_MODEL, "v3")
        res = self._client().get("/api/site/model")
        assert res.status_code == 500
        assert "DC_EPMS_SITE_MODEL" in res.json()["detail"]
