"""
tests/test_usd_export.py
========================
Release R2-C -- backend/usd_export.py.

  * The layer is deterministic and structurally sound (balanced
    braces, valid prim identifiers, no dangling relationship).
  * Every site-model component becomes exactly one prim carrying its
    metadata; every power / cooling edge becomes a relationship.
  * Honest-scope fence: the schematic notice is in the stage
    metadata and in the summary.
  * Vocabulary fence (S-VOCAB-01): the 800 VDC bus is never labelled
    with phase wording.
  * When usd-core is installed, the layer is opened with the real
    USD runtime and re-checked there.
"""

from __future__ import annotations

import pathlib
import re
import sys
from types import SimpleNamespace

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
# Same import path as tests/test_smoke.py (DC-EPMS-008 class).
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402
from site_model import SiteModel  # noqa: E402

from backend.usd_export import (  # noqa: E402
    ROOT_PRIM,
    SCHEMATIC_NOTICE,
    build_usda,
    export_filename,
    prim_name,
    stage_summary,
)

_PRIM_DEF = re.compile(r'^\s*def (Xform|Cube) "([^"]+)"', re.M)
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@pytest.fixture(scope="module")
def model() -> SiteModel:
    sm = SiteModel(yaml_path=PROJECT_ROOT / "config" / "site_model.yml")
    sm.load()
    return sm


@pytest.fixture(scope="module")
def usda(model: SiteModel) -> str:
    return build_usda(model)


def _fake_model(components, power=None, cooling=None, site=None):
    return SimpleNamespace(
        list_components=lambda: components,
        site_metadata=lambda: site or {"id": "t", "name": "T"},
        _power_downstream=power or {},
        _cooling_downstream=cooling or {},
    )


def _comp(cid, ctype="ups", building="b1", room="r1", row=None, **meta):
    loc = SimpleNamespace(
        building_id=building,
        building_display=building and building.upper(),
        room_id=room,
        room_display=room and room.upper(),
        row_id=row,
        row_display=row and row.upper(),
        path="/".join(x for x in (building, room, row) if x),
    )
    return SimpleNamespace(
        canonical_id=cid, display=cid.upper(), type=ctype, location=loc, metadata=meta
    )


class TestPureHelpers:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("ups_a", "ups_a"),
            ("building-a", "building_a"),
            ("row a/01", "row_a_01"),
            ("9lives", "_9lives"),
            ("", "_"),
            (None, "_"),
            ("ünïcode", "_n_code"),
        ],
    )
    def test_prim_name(self, raw, expected):
        assert prim_name(raw) == expected
        assert _IDENT.match(prim_name(raw))

    @pytest.mark.parametrize(
        ("site_id", "expected"),
        [
            ("a3-alpha-toronto", "a3-alpha-toronto.usda"),
            ("../../etc/passwd", "etc-passwd.usda"),
            ('x"; rm -rf', "x---rm--rf.usda"),
            ("", "site.usda"),
            (None, "site.usda"),
        ],
    )
    def test_export_filename_is_safe(self, site_id, expected):
        name = export_filename(site_id)
        assert name == expected
        assert "/" not in name
        assert '"' not in name


class TestStageStructure:
    def test_is_deterministic(self, model, usda):
        assert build_usda(model) == usda

    def test_header_and_honest_scope_metadata(self, usda):
        assert usda.startswith("#usda 1.0\n")
        assert f'defaultPrim = "{ROOT_PRIM}"' in usda
        assert 'upAxis = "Z"' in usda
        assert "metersPerUnit = 1" in usda
        assert SCHEMATIC_NOTICE in usda
        assert 'string layout = "schematic"' in usda

    def test_is_ascii_and_balanced(self, usda):
        usda.encode("ascii")
        for open_c, close_c in ("{}", "()", "[]"):
            assert usda.count(open_c) == usda.count(close_c), open_c

    def test_every_prim_identifier_is_valid(self, usda):
        names = [m.group(2) for m in _PRIM_DEF.finditer(usda)]
        assert names
        for name in names:
            assert _IDENT.match(name), name

    def test_one_cube_per_component(self, model, usda):
        cubes = [m.group(2) for m in _PRIM_DEF.finditer(usda) if m.group(1) == "Cube"]
        expected = sorted(prim_name(c.canonical_id) for c in model.list_components())
        assert sorted(cubes) == expected
        assert len(cubes) == len(set(cubes)) == 113

    def test_metadata_is_carried_as_typed_attributes(self, usda):
        assert "custom int a3semi:meta:rated_kw = 2500" in usda
        assert 'custom string a3semi:canonicalId = "ups_a"' in usda
        assert 'custom string a3semi:assetType = "it_rack"' in usda
        assert "custom double a3semi:meta:voltage_kv = 27.5" in usda

    def test_power_edges_become_relationships(self, usda):
        block = usda[usda.index('def Cube "ups_a"') :]
        block = block[: block.index("\n                }")]
        assert "custom rel a3semi:powerFeeds = [" in block
        assert "/er_a/rpp_a_01>" in block
        assert "/er_a/rpp_a_02>" in block

    def test_no_relationship_target_is_dangling(self, model, usda):
        targets = set(re.findall(r"<(/[^>]+)>", usda))
        assert targets
        leafs = {t.rsplit("/", 1)[1] for t in targets}
        known = {prim_name(c.canonical_id) for c in model.list_components()}
        assert leafs <= known

    def test_vocabulary_fence_on_the_dc_bus(self, usda):
        block = usda[usda.index('def Cube "main_bus_dc_d"') :]
        block = block[: block.index("\n                }")].lower()
        assert "custom int a3semi:meta:voltage_v_dc = 800" in block
        assert "unipolar" in block
        for forbidden in ("trifasico", "trif\\u00e1sico", "3-phase", "three-phase", "phase_ab"):
            assert forbidden not in block


class TestSummary:
    def test_counts_match_the_model(self, model):
        s = stage_summary(model)
        assert s["component_count"] == 113
        assert s["filename"] == "a3-alpha-toronto.usda"
        assert s["layout"] == "schematic"
        assert s["notice"] == SCHEMATIC_NOTICE
        assert sum(s["components_by_type"].values()) == 113
        assert s["components_by_type"]["it_rack"] == 50
        assert s["power_edge_count"] > 0
        assert s["cooling_edge_count"] > 0
        assert s["unplaced_component_count"] == 22

    def test_edge_counts_equal_the_relationship_targets_written(self, model, usda):
        s = stage_summary(model)
        written = len(re.findall(r"^\s*<(/[^>]+)>,$", usda, re.M)) + len(
            re.findall(r"^\s*custom rel [\w:]+ = <", usda, re.M)
        )
        assert written == s["power_edge_count"] + s["cooling_edge_count"]


class TestSyntheticModels:
    def test_strings_are_escaped(self):
        comp = _comp("x1", note='he said "hi" \\ back\nnewline', display_name="ok")
        comp.display = 'A "quoted" name'
        text = build_usda(_fake_model([comp]))
        assert 'custom string a3semi:display = "A \\"quoted\\" name"' in text
        assert '\\"hi\\" \\\\ back\\nnewline' in text
        assert text.count("{") == text.count("}")

    def test_metadata_types(self):
        comp = _comp(
            "x1",
            flag=True,
            count=3,
            ratio=0.985,
            name="n",
            nothing=None,
            items=[1, 2],
            nested={"b": 1, "a": 2},
            bad=float("nan"),
        )
        text = build_usda(_fake_model([comp]))
        assert "custom bool a3semi:meta:flag = true" in text
        assert "custom int a3semi:meta:count = 3" in text
        assert "custom double a3semi:meta:ratio = 0.985" in text
        assert 'custom string a3semi:meta:name = "n"' in text
        assert "a3semi:meta:nothing" not in text
        assert 'custom string a3semi:meta:items = "[1, 2]"' in text
        assert 'custom string a3semi:meta:nested = "{\\"a\\": 2, \\"b\\": 1}"' in text
        assert 'custom string a3semi:meta:bad = "NaN"' in text

    def test_unplaced_components_get_their_own_group(self):
        comp = _comp("orphan", building=None, room=None)
        text = build_usda(_fake_model([comp]))
        assert 'def Xform "unplaced"' in text
        assert 'def Xform "no_room"' in text

    def test_edges_to_unknown_components_are_dropped(self):
        a, b = _comp("a"), _comp("b")
        text = build_usda(_fake_model([a, b], power={"a": ["b", "ghost"], "ghost": ["a"]}))
        assert "custom rel a3semi:powerFeeds = </World/Site/b1/r1/b>" in text
        assert "ghost" not in text

    def test_prim_path_collision_is_an_error_not_a_silent_overwrite(self):
        with pytest.raises(ValueError, match="prim path collision"):
            build_usda(_fake_model([_comp("rack-1"), _comp("rack_1")]))

    def test_racks_in_a_row_are_spaced_along_x(self):
        racks = [_comp(f"rack_{i}", ctype="it_rack", row="row1") for i in range(3)]
        text = build_usda(_fake_model(racks))
        xs = [float(m) for m in re.findall(r"xformOp:translate = \(([-\d.]+),", text)]
        assert xs == sorted(xs)
        assert len(set(xs)) == 3

    def test_empty_model_still_yields_a_valid_layer(self):
        text = build_usda(_fake_model([]))
        assert text.startswith("#usda 1.0\n")
        assert "int componentCount = 0" in text
        assert text.count("{") == text.count("}")


class TestWithUsdRuntime:
    """Opens the layer with the real USD runtime when available."""

    def test_stage_opens_and_matches(self, model, usda, tmp_path):
        pxr_usd = pytest.importorskip("pxr.Usd")
        from pxr import UsdGeom

        path = tmp_path / "site.usda"
        path.write_text(usda, encoding="utf-8")
        stage = pxr_usd.Stage.Open(str(path))
        assert stage is not None
        assert str(stage.GetDefaultPrim().GetPath()) == f"/{ROOT_PRIM}"
        assert UsdGeom.GetStageUpAxis(stage) == "Z"
        assert UsdGeom.GetStageMetersPerUnit(stage) == 1.0

        cubes = [p for p in stage.Traverse() if p.GetTypeName() == "Cube"]
        assert len(cubes) == 113
        edges = 0
        for prim in cubes:
            for rel in prim.GetRelationships():
                for target in rel.GetTargets():
                    edges += 1
                    assert stage.GetPrimAtPath(target).IsValid(), target
        s = stage_summary(model)
        assert edges == s["power_edge_count"] + s["cooling_edge_count"]

        ups = next(p for p in cubes if p.GetName() == "ups_a")
        assert ups.GetAttribute("a3semi:meta:rated_kw").Get() == 2500
        bus = next(p for p in cubes if p.GetName() == "main_bus_dc_d")
        assert bus.GetAttribute("a3semi:meta:voltage_v_dc").Get() == 800
        assert "unipolar" in bus.GetAttribute("a3semi:display").Get()


class TestRoutes:
    """Routes on a minimal app.

    Deliberately NOT the real ``main.app``: this file sorts after
    tests/test_subprocess_cleanup.py, which ``importlib.reload``s
    ``main``. The reloaded app re-registers the Prometheus in-progress
    gauge when its middleware stack is first built, so any test that
    boots ``main.app`` afterwards fails with "Duplicated timeseries"
    (DC-EPMS-062, pre-existing isolation hazard). Wiring into the
    real app is asserted from its route table, which needs no boot.
    """

    @pytest.fixture
    def client(self, model, monkeypatch):
        from fastapi import FastAPI

        from backend.auth.session_gate import SessionGateMiddleware
        from backend.usd_export import register_usd_export_routes

        monkeypatch.delenv("DC_EPMS_REQUIRE_AUTH", raising=False)
        app = FastAPI()
        app.add_middleware(SessionGateMiddleware)
        register_usd_export_routes(app, lambda: model)
        return TestClient(app)

    def test_download(self, client, usda):
        res = client.get("/api/site/usd")
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/plain")
        assert res.headers["content-disposition"] == 'attachment; filename="a3-alpha-toronto.usda"'
        assert res.headers["cache-control"] == "no-store"
        assert res.text == usda

    def test_summary(self, client):
        body = client.get("/api/site/usd/summary").json()
        assert body["component_count"] == 113
        assert body["notice"] == SCHEMATIC_NOTICE

    def test_read_only(self, client):
        assert client.post("/api/site/usd").status_code == 405
        assert client.put("/api/site/usd/summary").status_code == 405

    def test_gated_deployment_requires_a_session(self, client, monkeypatch):
        monkeypatch.setenv("DC_EPMS_REQUIRE_AUTH", "1")
        assert client.get("/api/site/usd").status_code == 401
        assert client.get("/api/site/usd/summary").status_code == 401

    def test_unavailable_model_is_503_not_500(self):
        from fastapi import FastAPI

        from backend.usd_export import register_usd_export_routes

        def _broken():
            raise RuntimeError("site model not initialized")

        app = FastAPI()
        register_usd_export_routes(app, _broken)
        c = TestClient(app)
        assert c.get("/api/site/usd").status_code == 503
        assert c.get("/api/site/usd/summary").status_code == 503

    def test_collision_surfaces_as_500_with_a_reason(self):
        from fastapi import FastAPI

        from backend.usd_export import register_usd_export_routes

        app = FastAPI()
        register_usd_export_routes(app, lambda: _fake_model([_comp("rack-1"), _comp("rack_1")]))
        res = TestClient(app).get("/api/site/usd")
        assert res.status_code == 500
        assert "prim path collision" in res.json()["detail"]

    def test_real_app_mounts_both_routes(self):
        import main as main_mod

        paths = {getattr(r, "path", None) for r in main_mod.app.routes}
        assert "/api/site/usd" in paths
        assert "/api/site/usd/summary" in paths
