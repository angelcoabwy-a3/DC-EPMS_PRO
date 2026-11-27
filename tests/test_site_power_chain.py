"""DC-EPMS-072: every Phase 1 rack has a 2N power chain, and the
distribution in between can carry it.

Ratings rule (same as ADR-021): in 2N one path must carry the FULL load,
so each busway and RPP is checked against the whole downstream rack load
at 80 % continuous. 480 V, pf 0.95 is a model assumption, not a vendor
figure.
"""

from __future__ import annotations

import math
import pathlib
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

import site_model as sm  # noqa: E402

PF = 0.95
CONTINUOUS = 0.8


def _load(monkeypatch, variant):
    if variant == "legacy":
        monkeypatch.delenv(sm.ENV_SITE_MODEL, raising=False)
    else:
        monkeypatch.setenv(sm.ENV_SITE_MODEL, variant)
    sm.reset_site_model()
    return sm.get_site_model(PROJECT_ROOT)


@pytest.fixture(params=["legacy", "v2"])
def model(request, monkeypatch):
    m = _load(monkeypatch, request.param)
    yield m
    sm.reset_site_model()


def _phase1_racks(m):
    return [
        c.canonical_id
        for c in m.list_components()
        if c.type == "it_rack" and not c.canonical_id.startswith("rack_d")
    ]


def _racks_below(m, node):
    downstream = m._power_downstream
    out, stack, seen = set(), [node], set()
    while stack:
        n = stack.pop()
        for child in downstream.get(n, []):
            if child in seen:
                continue
            seen.add(child)
            if child.startswith("rack_"):
                out.add(child)
            else:
                stack.append(child)
    return out


def test_every_phase1_rack_has_one_busway_per_path(model):
    racks = _phase1_racks(model)
    assert len(racks) == 50
    for rack in racks:
        ups = sorted(model._power_upstream.get(rack, []))
        assert len(ups) == 2, (rack, ups)
        assert ups[0].startswith("busway_a_"), (rack, ups)
        assert ups[1].startswith("busway_b_"), (rack, ups)
        # same row on both paths
        assert ups[0][-2:] == ups[1][-2:], (rack, ups)


def test_every_phase1_rack_survives_a_whole_path(model):
    for rack in _phase1_racks(model):
        groups = [f["group"] for f in model.power_chain_for(rack)["feeds"]]
        assert "path_a" in groups, (rack, groups)
        assert "path_b" in groups, (rack, groups)


def test_busways_and_rpps_carry_full_row_load_in_2n(model):
    comps = {c.canonical_id: c for c in model.list_components()}
    rated = {c.canonical_id: c for c in model.list_components()}
    checked = 0
    for cid, c in comps.items():
        if c.type not in ("busway", "rpp") or cid.startswith("rpp_d"):
            continue
        racks = _racks_below(model, cid)
        assert racks, f"{cid} feeds no rack"
        load_kw = sum(float(rated[r].metadata.get("rated_kw", 0)) for r in racks)
        if c.type == "busway":
            amps = float(c.metadata["rated_amps"])
            volts = float(c.metadata.get("voltage_v", 480))
            cont_kw = math.sqrt(3) * volts * amps * PF * CONTINUOUS / 1000.0
        else:
            cont_kw = float(c.metadata["rated_kw"]) * CONTINUOUS
        assert load_kw <= cont_kw, (cid, load_kw, round(cont_kw))
        checked += 1
    assert checked == 14  # 10 busways + 4 RPPs
