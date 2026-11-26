"""Building D 800 VDC design model (ADR-021)."""

from __future__ import annotations

import copy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.design_model import (
    design_payload,
    layout,
    load_inputs,
    rack_detail,
    register_design_routes,
    size,
)


@pytest.fixture(scope="module")
def inp():
    return load_inputs()


def _chain(s, cid):
    return next(c for c in s["chain"] if c["id"] == cid)


def test_sizing_numbers_follow_from_the_inputs(inp):
    s = size(inp)
    assert s["basis"]["it_kw"]["value"] == 50_000  # 250 x 200 kW
    rack = _chain(s, "rack_feeds")
    assert rack["current"]["value"] == 250.0  # 200 kW / 800 V
    assert rack["normal_current"]["value"] == 125.0  # 2N share
    assert rack["rating"]["value"] == 315  # >= 250 / 0.8
    bw = _chain(s, "row_busways")
    assert bw["current"]["value"] == 3250  # 13 racks x 250 A
    assert bw["rating"]["value"] == 5000
    sec = _chain(s, "dc_bus_sections")
    assert sec["current"]["value"] == 31250
    assert sec["rating"]["value"] == 40000
    rect = _chain(s, "mv_rectifiers")
    assert rect["per_section"] == 6
    assert rect["required_per_section"] == 5
    assert s["totals"]["rectifiers"] == 24
    gen = _chain(s, "generators")
    assert gen["per_path"] == 21
    assert s["totals"]["generators"] == 42
    bess = _chain(s, "bess")
    assert bess["installed"]["value"] == 7.5
    assert bess["per_path"] == 3
    cap = _chain(s, "capacitor_banks")
    assert cap["capacitance"]["value"] == pytest.approx(8.68, abs=0.01)
    cdu = _chain(s, "cdus")
    assert cdu["rack_flow"]["value"] == pytest.approx(111.7, abs=0.1)


def test_every_design_check_passes_and_phase1_flow_is_flagged(inp):
    checks = {c["id"]: c["status"] for c in size(inp)["checks"]}
    assert checks.pop("P1-DLC-FLOW") == "WARN"
    assert set(checks.values()) == {"PASS"}, checks


def test_vocabulary_fence_dc_has_no_phases(inp):
    for c in size(inp)["chain"]:
        if c["domain"] == "dc":
            assert c["polarity"] == "unipolar"
            assert "phases" not in c
            assert "phase" not in c["label"].lower()
        elif c["domain"] == "ac":
            assert c["phases"] == 3
            assert "vdc" not in c["label"].lower()
    rect = next(c for c in size(inp)["chain"] if c["id"] == "mv_rectifiers")
    assert rect["phases_in"] == 3
    assert rect["polarity_out"] == "unipolar"


def test_redundancy_failure_is_reported(inp):
    bad = copy.deepcopy(inp)
    bad["rectifier"]["redundancy_per_section"] = 0
    bad["rectifier"]["unit_kw"] = 4000  # 25 MW / 4 MW = 7 units, no spare
    bad["generators"]["redundancy_per_path"] = 0
    checks = {c["id"]: c["status"] for c in size(bad)["checks"]}
    assert checks["D-RECT-N1"] == "FAIL"
    assert checks["D-GEN-N1"] == "FAIL"


def test_more_rack_power_never_shrinks_the_plant(inp):
    base = size(inp)["totals"]
    hot = copy.deepcopy(inp)
    hot["it"]["rack_kw"] = 250
    up = size(hot)["totals"]
    for k in base:
        assert up[k] >= base[k], k
    assert up["generators"] > base["generators"]


def test_layout_racks_are_unique_and_do_not_overlap(inp):
    lay = layout(inp)
    racks = lay["racks"]
    assert len(racks) == 250
    assert len({r["id"] for r in racks}) == 250
    boxes = {(r["x_mm"], r["y_mm"]) for r in racks}
    assert len(boxes) == 250
    # each rack fed by exactly one busway per path, and that busway covers it
    bw = {b["id"]: b for row in lay["rows"] for b in row["busways"]}
    for r in racks:
        assert {f["path"] for f in r["feeds"]} == {"a", "b"}
        for f in r["feeds"]:
            lo, hi = bw[f["busway"]]["racks"]
            assert lo <= r["position"] <= hi


def test_rack_detail(inp):
    r = rack_detail(inp, "DH1-D01-01")
    assert r["cooling"]["flow"]["tag"] == "MODEL"
    assert "not_modelled" in r["devices"]
    assert rack_detail(inp, "nope") is None


def test_routes():
    app = FastAPI()
    register_design_routes(app)
    c = TestClient(app)
    body = c.get("/api/design/building-d").json()
    assert body["dc"]["polarity"] == "unipolar"
    assert body["rack_count"] == 250
    assert "racks" not in body["layout"]
    assert len(c.get("/api/design/building-d/racks").json()["racks"]) == 250
    assert c.get("/api/design/building-d/racks/DH1-D10-25").status_code == 200
    assert c.get("/api/design/building-d/racks/x").status_code == 404


def test_payload_is_labelled_design():
    assert design_payload()["status"].startswith("DESIGN")
