"""
DC-EPMS-068 lote B -- role resolution and backend consumers on both
site model variants.

Every assertion runs on the legacy model (what the public host runs)
and on v2 (closed Phase 1 design) unless it is variant-specific.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import types

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

import site_model as sm  # noqa: E402
import site_roles as roles  # noqa: E402
from loto_auditor_pillar_helpers import (  # noqa: E402
    build_steady_state_measurements,
    simulate_loto_measurements,
)

RETIRED = {"ups_a", "ups_b", "ats_a", "ats_b", "xfmr_a", "xfmr_b", "switchgear_a", "switchgear_b"}


def _load(monkeypatch, variant: str):
    if variant == "legacy":
        monkeypatch.delenv(sm.ENV_SITE_MODEL, raising=False)
    else:
        monkeypatch.setenv(sm.ENV_SITE_MODEL, variant)
    sm.reset_site_model()
    return sm.get_site_model(PROJECT_ROOT)


@pytest.fixture(autouse=True)
def _reset():
    sm.reset_site_model()
    yield
    sm.reset_site_model()


@pytest.fixture(params=["legacy", "v2"])
def model(request, monkeypatch):
    return _load(monkeypatch, request.param)


# ── path_of ─────────────────────────────────────────────────────────
class _C:
    def __init__(self, cid, meta=None, ctype="x"):
        self.canonical_id, self.metadata, self.type = cid, meta or {}, ctype


@pytest.mark.parametrize(
    ("cid", "meta", "expected"),
    [
        ("ups_a", {}, "a"),
        ("ats_b", {}, "b"),
        ("ups_a_01", {}, "a"),
        ("genset_b_09", {}, "b"),
        ("rpp_a_02", {}, "a"),
        ("mvtc_b", {}, "b"),
        ("chiller_1", {}, None),
        ("rack_a_01_05", {}, None),
        ("whatever", {"path": "B"}, "b"),
        ("ups_a_01", {"path": "b"}, "b"),  # declared metadata wins
        ("mv_rectifier_d", {}, None),
    ],
)
def test_path_of(cid, meta, expected):
    assert roles.path_of(_C(cid, meta)) == expected


# ── roles per variant ───────────────────────────────────────────────
def test_roles_legacy(monkeypatch):
    m = _load(monkeypatch, "legacy")
    assert roles.role_summary(m) == {
        "a": {"transfer": "ats_a", "ups": ["ups_a"], "utility_transformer": "xfmr_a"},
        "b": {"transfer": "ats_b", "ups": ["ups_b"], "utility_transformer": "xfmr_b"},
    }
    assert roles.primary_ups(m, "a") == "ups_a"


def test_roles_v2(monkeypatch):
    m = _load(monkeypatch, "v2")
    summary = roles.role_summary(m)
    for p in "ab":
        assert summary[p]["transfer"] == f"mvtc_{p}"
        assert summary[p]["ups"] == [f"ups_{p}_{i:02d}" for i in range(1, 9)]
        assert summary[p]["utility_transformer"] == f"mv_xfmr_{p}"
    assert roles.primary_ups(m, "b") == "ups_b_01"
    flat = {
        v for s in summary.values() for v in [s["transfer"], s["utility_transformer"], *s["ups"]]
    }
    assert not flat & RETIRED


def test_primary_ups_unknown_path(model):
    assert roles.primary_ups(model, "z") is None


# ── power_chain_for grouping (was hard-coded to ats_a / ats_b) ──────
def test_every_fed_phase1_rack_has_two_feeds(model):
    racks = [c.canonical_id for c in model.list_components() if c.type == "it_rack"]
    phase1 = [r for r in racks if not r.startswith("rack_d")]
    fed = [r for r in phase1 if model._power_upstream.get(r)]
    # DC-EPMS-072 (open): only 10 of the 50 modelled Phase 1 racks carry
    # a power chain, on both variants. Fence the number so a change in
    # either direction is noticed.
    assert (len(phase1), len(fed)) == (50, 10)
    for rack in fed:
        chain = model.power_chain_for(rack)
        groups = [f["group"] for f in chain["feeds"]]
        assert groups[:2] == ["path_a", "path_b"], (rack, groups)


def test_group_for_path():
    t = {"a": "mvtc_a", "b": "mvtc_b"}
    assert roles.group_for_path(["rack", "ups_a_01", "mvtc_a", "utility_feed_a"], t) == "path_a"
    assert roles.group_for_path(["rack", "mvtc_b"], t) == "path_b"
    assert roles.group_for_path(["fuel_tank_a"], t) is None
    assert roles.group_for_path(["x"], {}) is None


# ── HLD aggregate namespace ─────────────────────────────────────────
def test_hld_key_legacy_identity(monkeypatch):
    m = _load(monkeypatch, "legacy")
    assert roles.hld_key(m, "ups_a") == "ups_a"
    assert roles.hld_key(m, "xfmr_b") == "xfmr_b"
    assert roles.hld_key(m, "ats_a") is None


def test_hld_key_v2_groups(monkeypatch):
    m = _load(monkeypatch, "v2")
    assert roles.hld_key(m, "ups_a_03") == "ups_a"
    assert roles.hld_key(m, "ups_b_08") == "ups_b"
    assert roles.hld_key(m, "mv_xfmr_a") == "xfmr_a"
    assert roles.hld_key(m, "unit_sub_a_01") is None  # not the utility transformer
    assert roles.hld_key(m, "mvtc_a") is None
    assert roles.hld_key(m, "genset_a_01") is None
    assert roles.hld_key(m, "does_not_exist") is None
    assert roles.hld_members(m, "ups_a") == [f"ups_a_{i:02d}" for i in range(1, 9)]
    assert roles.hld_members(m, "xfmr_b") == ["mv_xfmr_b"]
    assert roles.hld_members(m, "chiller_1") == []


# ── LOTO pillar 2: block-level vs path-level UPS LOTO ───────────────
def test_simulate_block_loto_keeps_path():
    base = build_steady_state_measurements()
    sim = simulate_loto_measurements(
        base,
        target_id="ups_a_01",
        target_type="ups",
        target_path="A",
        ups_path_remaining_kw=17500.0,
    )
    assert sim.get("ups_a_online", True) is True
    assert sim.get("battery_on_load", False) is False
    assert sim["ups_blocks_offline"] == 1
    assert base.get("ups_blocks_offline") is None  # base not mutated


def test_simulate_short_remaining_falls_back_to_path_loss():
    base = build_steady_state_measurements()
    sim = simulate_loto_measurements(
        base,
        target_id="ups_a_01",
        target_type="ups",
        target_path="A",
        ups_path_remaining_kw=12500.0,  # below the 16.76 MW full-path load
    )
    assert sim["ups_a_online"] is False
    assert sim["battery_on_load"] is True
    assert "ups_blocks_offline" not in sim


def test_simulate_legacy_signature_unchanged():
    base = build_steady_state_measurements()
    sim = simulate_loto_measurements(base, target_id="ups_a", target_type="ups", target_path="A")
    assert sim["ups_a_online"] is False


def _pillar2(model, target: str):
    """Run pillar 2 on the real site model + real physics engine."""
    from loto_auditor_agent import LotoAuditorAgent, ProcedureSpec
    from loto_auditor_models import LotoAuditRequest
    from physics_engine import PhysicsEngine

    agent = LotoAuditorAgent(
        site_model=model,
        graphrag_service=None,
        physics_engine=PhysicsEngine(),
        witness_engine=None,
    )
    request = LotoAuditRequest(
        procedure_id="T4-MOP-UPS-001", target_component_id=target, cet_on_duty="pytest"
    )
    sources: dict[str, str] = {}
    red = agent._check_pillar_2_redundancy(request, ProcedureSpec("T4-MOP-UPS-001", {}), sources)
    return red, sources


def test_audit_v2_single_block_keeps_2n(monkeypatch):
    m = _load(monkeypatch, "v2")
    red, sources = _pillar2(m, "ups_a_01")
    assert red.outcome.value == "PASS", red
    assert red.path_a_state == "block_loto_path_keeps_n"
    assert red.path_b_state == "normal"
    assert sources["site_model_ups_blocks"].startswith("OK (17500 kW")


def test_audit_v2_path_b_block(monkeypatch):
    m = _load(monkeypatch, "v2")
    red, _ = _pillar2(m, "ups_b_08")
    assert red.path_b_state == "block_loto_path_keeps_n"
    assert red.path_a_state == "normal"


def test_audit_legacy_ups_is_still_a_path_loss(monkeypatch):
    m = _load(monkeypatch, "legacy")
    red, sources = _pillar2(m, "ups_a")
    # Legacy model: one 2.5 MW UPS per path (DC-EPMS-057), so a LOTO on
    # it stays a path loss and the physics gate keeps failing it. The
    # block-level branch must not engage.
    assert red.outcome.value == "HARD_FAIL"
    assert red.path_a_state != "block_loto_path_keeps_n"
    assert "site_model_ups_blocks" not in sources


# ── CMMS seeder path ───────────────────────────────────────────────
def test_seeder_prefers_declared_path():
    from backend.cmms_seeder import _derive_path, _derive_redundancy_pillar

    assert _derive_path("weird_id", {"path": "b"}) == "B"
    assert _derive_path("ups_a", {}) == "A"
    assert _derive_path("mvtc_b", {}) == "B"
    assert _derive_redundancy_pillar("mv_transfer_controller", {}) == "2N"
    assert _derive_redundancy_pillar("mv_switchgear", {}) == "2N"


# ── copilot query_unified_graph maps v2 ids to the HLD group ────────
def test_copilot_maps_block_to_hld_group(monkeypatch):
    m = _load(monkeypatch, "v2")
    import agent_copilot

    async def fake_topology():
        return {
            "hld_nodes": {
                "ups_a": {"label": "UPS Galaxy A", "severity": "ok", "health": 1.0, "metrics": {}}
            },
            "redundancy_mode": "2N",
            "site_health": 1.0,
        }

    fake_main = types.ModuleType("main")
    fake_main.get_topology_state = fake_topology
    fake_main.PROJECT_ROOT = PROJECT_ROOT
    monkeypatch.setitem(sys.modules, "main", fake_main)
    assert sm.get_site_model(PROJECT_ROOT) is m

    out = asyncio.run(agent_copilot.tool_query_unified_graph({"device_id": "ups_a_04"}))
    assert out["device_id"] == "ups_a"
    assert out["requested_id"] == "ups_a_04"
    assert out["hld_group_members"] == [f"ups_a_{i:02d}" for i in range(1, 9)]
    assert "aggregated" in out["_note"]

    out = asyncio.run(agent_copilot.tool_query_unified_graph({"device_id": "nope"}))
    assert "error" in out
