"""L6 -- backend/oscillography.py (disturbance records synthesised from
plant state changes, IEEE 1159 classification, COMTRADE C37.111-1999
ASCII) and the recorder in the device controller and its routes."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import (  # noqa: E402
    device_control as dc,
    oscillography as osc,
)
from backend.auth.jwt_handler import issue_token, seed_demo_users  # noqa: E402
from backend.ledger import ForensicLedger  # noqa: E402
from backend.ledger.forensic_ledger import InMemoryPersistence  # noqa: E402

DESIGN = PROJECT_ROOT / "config" / "power_plant.yml"
N = round((osc.PRE_S + osc.POST_S) * osc.FS)


def rec(pre_src, post_src, pre_load="inverter", post_load="inverter", **kw):
    pre = {"source": pre_src, "load": pre_load, "hz": 60.0}
    post = {"source": post_src, "load": post_load, "hz": 60.0}
    r = osc.Record("T", "a", 1_795_000_000.0, "t", [],
                   osc.point_states(pre_src != "NONE", 60.0, pre_load),
                   osc.point_states(post_src != "NONE", 60.0, post_load),
                   kw.get("trans") or osc.transitions(pre, post, **{k: v for k, v in kw.items() if k != "trans"}))
    return osc.synthesize(r)


# ── Pure ────────────────────────────────────────────────────────────
class TestWaveforms:
    def test_balanced_three_phase_at_nominal(self):
        r = rec("UTILITY", "UTILITY")
        assert all(len(r.samples[ch]) == N for ch in osc.CHANNELS)
        peak = max(r.samples["MV_VA"])
        assert peak == pytest.approx(13.8 / math.sqrt(3) * math.sqrt(2), rel=0.01)
        k = 100
        assert sum(r.samples[f"LD_V{p}"][k] for p in "ABC") == pytest.approx(0.0, abs=0.01)
        assert r.summary["MV"]["class"] == "no RMS variation"

    def test_utility_loss_mv_collapses_load_rides_through_on_inverter(self):
        r = rec("UTILITY", "NONE")
        assert r.summary["MV"]["min_pu"] < 0.1
        assert "interruption" in r.summary["MV"]["class"]
        assert r.summary["LD"]["class"] == "no RMS variation"

    def test_open_transition_dead_time_is_a_momentary_interruption(self):
        r = rec("GENERATORS", "UTILITY")
        assert r.summary["MV"]["transition"] == "gap"
        assert r.summary["MV"]["below_0_9_ms"] == pytest.approx(osc.OPEN_TRANSITION_S * 1000, abs=10)
        assert r.summary["MV"]["class"] == "momentary interruption"

    def test_closed_transition_has_no_gap(self):
        r = rec("GENERATORS", "UTILITY", closed_transition=True, phase_deg=8.0)
        assert r.summary["MV"]["transition"] == "phase_step"
        assert r.summary["MV"]["class"] == "no RMS variation"

    def test_static_switch_notch_under_4_ms(self):
        r = rec("UTILITY", "UTILITY", "inverter", "static_bypass")
        s = r.summary["LD"]
        assert s["transition"] == "notch"
        assert s["transition_ms"] < 4.0
        n_pre = round(osc.PRE_S * osc.FS)
        gap = r.samples["LD_VA"][n_pre:n_pre + 5]
        assert all(v == 0.0 for v in gap)

    def test_load_on_bypass_follows_the_mv_bus(self):
        r = rec("UTILITY", "NONE", "static_bypass", "static_bypass")
        assert r.summary["LD"]["min_pu"] < 0.1

    def test_inverter_fault_distortion(self):
        r = rec("UTILITY", "UTILITY", "inverter", "inverter_distorted")
        assert r.summary["LD"]["thd_pct"] == pytest.approx(11.2, abs=0.3)

    def test_sag_classification(self):
        sag = osc.Transition("sag", seconds=0.1, depth=0.6)
        r = rec("UTILITY", "UTILITY", trans={"MV": sag, "LD": osc.Transition()})
        assert r.summary["MV"]["min_pu"] == pytest.approx(0.6, abs=0.02)
        assert r.summary["MV"]["class"] == "instantaneous sag"
        assert osc.classify(0.5, 40, False) == "momentary sag"
        assert osc.classify(0.05, 400, False) == "temporary interruption"
        assert osc.classify(0.5, 0.2, False).startswith("transient")

    def test_restoration_is_named(self):
        r = rec("NONE", "GENERATORS")
        assert r.summary["MV"]["class"].startswith("voltage restored")

    def test_comtrade_1999_ascii(self):
        r = rec("UTILITY", "NONE")
        cfg, dat = osc.to_comtrade(r)
        lines = cfg.split("\r\n")
        assert lines[0] == "A3-ALPHA-TORONTO,DFR-PATH-A,1999"
        assert lines[1] == "6,6A,0D"
        assert len(lines[2].split(",")) == 13
        assert lines[8] == "60"
        assert lines[9] == "1"
        assert lines[10] == f"{osc.FS:g},{N}"
        assert lines[13] == "ASCII"
        assert lines[14] == "1"
        rows = dat.strip().split("\r\n")
        assert len(rows) == N
        first = rows[0].split(",")
        assert first[:2] == ["1", "0"]
        assert len(first) == 8
        a = float(lines[2].split(",")[5])
        k = round(osc.PRE_S * osc.FS) - 3
        assert int(rows[k].split(",")[2]) * a == pytest.approx(r.samples["MV_VA"][k], abs=a)


# ── Controller ──────────────────────────────────────────────────────
class Clock:
    def __init__(self):
        self.t = 1_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def world():
    clock = Clock()
    ctl = dc.DeviceController.from_design(dc.load_design(DESIGN), clock=clock, wall_clock=clock)
    ctl.snapshot_all()
    return ctl, clock


class TestRecorder:
    def test_steady_plant_records_nothing(self, world):
        ctl, clock = world
        clock.t += 5
        assert ctl.dfr_records() == []
        assert ctl.path_summary("a")["dfr"] == {"source": "UTILITY", "load": "inverter", "hz": 60.0}

    def test_utility_loss_and_transfer(self, world):
        ctl, clock = world
        ctl.inject_utility_loss("a", "op")
        for _ in range(30):
            clock.t += 1
            ctl.snapshot_all()
        recs = ctl.dfr_records("a")
        assert [r["trigger"] for r in reversed(recs)] == ["MV UTILITY -> NONE", "MV NONE -> GENERATORS"]
        first = recs[-1]
        assert first["cause"][:2] == ["utility_lost 27", "protection_trip 27"]
        assert any(c.startswith("auto_start x") for c in first["cause"])
        assert first["summary"]["LD"]["class"] == "no RMS variation"
        assert any(e["event"] == "dfr_record" for e in ctl._events)

    def test_ups_to_bypass_and_sag_reaches_the_load(self, world):
        ctl, _ = world
        ctl.ups_action("a", "SYSTEM_TO_BYPASS", "op")
        assert ctl.dfr_records()[0]["summary"]["LD"]["transition"] == "notch"
        sag = ctl.inject_utility_sag("a", 0.5, 6, "op")
        assert sag["summary"]["LD"]["min_pu"] == pytest.approx(0.5, abs=0.02)

    def test_sag_on_inverter_does_not_reach_the_load(self, world):
        ctl, _ = world
        sag = ctl.inject_utility_sag("a", 0.5, 6, "op")
        assert sag["summary"]["MV"]["class"] == "instantaneous sag"
        assert sag["summary"]["LD"]["class"] == "no RMS variation"
        with pytest.raises(dc.DeviceControlError):
            ctl.inject_utility_sag("a", 0.95, 6, "op")
        ctl.inject_utility_loss("a", "op")
        with pytest.raises(dc.DeviceControlError):
            ctl.inject_utility_sag("a", 0.5, 6, "op")

    def test_manual_trigger_and_reset(self, world):
        ctl, _ = world
        r = ctl.dfr_trigger("a", "op")
        assert r["trigger"] == "manual"
        assert ctl.dfr_record(r["id"]).samples
        ctl.reset("op")
        assert ctl.dfr_records() == []
        with pytest.raises(dc.DeviceControlError):
            ctl.dfr_record(r["id"])


# ── Routes ──────────────────────────────────────────────────────────
@pytest.fixture
def client(monkeypatch, world):
    monkeypatch.delenv("DC_EPMS_REQUIRE_AUTH", raising=False)
    ctl, _ = world
    app = FastAPI()
    app.state.forensic_ledger = ForensicLedger(InMemoryPersistence(), key=b"k" * 32)
    dc.register_device_control_routes(app, lambda: ctl)
    with TestClient(app) as c:
        yield c, ctl


def bearer(name):
    user = seed_demo_users().find_by_username(name)
    return {"Authorization": f"Bearer {issue_token(user)}"}


class TestRoutes:
    def test_list_get_comtrade_and_ledger(self, client):
        c, _ = client
        h = bearer("manager")
        assert c.post("/api/oscillography/a/sag", json={"depth_pu": 0.6}, headers=bearer("operator")).status_code == 403
        r = c.post("/api/oscillography/a/sag", json={"depth_pu": 0.6, "cycles": 6}, headers=h)
        assert r.status_code == 200
        rid = r.json()["record"]["id"]
        lst = c.get("/api/oscillography/records?path=a").json()
        assert lst["records"][0]["id"] == rid
        assert "samples" not in lst["records"][0]
        full = c.get(f"/api/oscillography/records/{rid}").json()
        assert len(full["samples"]["MV_VA"]) == N
        cfg = c.get(f"/api/oscillography/records/{rid}/comtrade?part=cfg")
        assert cfg.status_code == 200
        assert cfg.headers["content-disposition"].endswith(f'{rid}.cfg"')
        assert cfg.text.startswith("A3-ALPHA-TORONTO,DFR-PATH-A,1999")
        assert c.get(f"/api/oscillography/records/{rid}/comtrade?part=hdr").status_code == 400
        assert c.get("/api/oscillography/records/DFR-X-9999").status_code == 404
        entries = c.app.state.forensic_ledger.persistence._entries
        assert any(e.action == dc.ACTION_DFR and e.payload["action"] == "UTILITY_SAG" for e in entries)
        t = c.post("/api/oscillography/a/trigger", json={}, headers=h)
        assert t.json()["record"]["trigger"] == "manual"
