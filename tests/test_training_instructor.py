"""AI-1 -- backend/training_instructor.py: debrief of a finished drill
(deterministic and Meta sources), name scrubbing, citation guard, daily
cap, cache, and the /api/training/debrief route."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import (  # noqa: E402
    alarm_engine as ae,
    device_control as dc,
    training as tr,
    training_instructor as ti,
    training_routes as trr,
)
from backend.auth.jwt_handler import issue_token, seed_demo_users  # noqa: E402
from backend.ledger import ForensicLedger  # noqa: E402
from backend.ledger.forensic_ledger import InMemoryPersistence  # noqa: E402

DESIGN = PROJECT_ROOT / "config" / "power_plant.yml"
DRILLS = PROJECT_ROOT / "config" / "training_drills"
FORWARD = ["SYSTEM_TO_BYPASS", "SKRU_RELEASE", "UNLOCK_MBB", "CLOSE_Q3", "OPEN_Q4", "LOCK_MIB",
           "SKRU_CAPTURE", "OPEN_QF1", "OPEN_Q1", "OPEN_Q2", "PADLOCK_QF1"]


class Clock:
    def __init__(self):
        self.t = 1_000.0

    def __call__(self):
        return self.t


class FakeProvider:
    def __init__(self, text="Summary: ok. NFPA 110 and IEEE 1584 apply.", configured=True):
        self.text, self.is_configured, self.model, self.calls = text, configured, "muse-spark-1.3", 0
        self.prompts = []

    async def stream(self, prompt, max_tokens=500):
        self.calls += 1
        self.prompts.append((prompt, max_tokens))
        for part in (self.text[:10], self.text[10:]):
            yield part


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    ti.reset_limits()
    monkeypatch.delenv(ti.DAILY_CAP_ENV, raising=False)
    yield
    ti.reset_limits()


def run_drill08(extra_first=True):
    clock = Clock()
    ctl = dc.DeviceController.from_design(dc.load_design(DESIGN), clock=clock, wall_clock=clock)
    tm = tr.TrainingManager(tr.load_drills(DRILLS), clock=clock)
    eng = ae.AlarmEngine()
    tm.start("DRILL-08", "alice", ctl, eng)
    for a in (["OPEN_Q4"] if extra_first else []) + FORWARD:
        clock.t += 3
        try:
            ctl.ups_action("a", a, "alice")
        except dc.DeviceControlError as exc:
            ctl.ups_refusal("a", "alice", exc.detail, a)
        tm.evaluate(ctl, eng)
    return ctl, tm, eng


def debrief(report, **kw):
    return asyncio.run(ti.debrief(report, **kw))


class TestBrief:
    def test_name_scrubbed_and_shape(self):
        _, tm, _ = run_drill08()
        brief = ti.build_brief(tm.last_report, ["DRILL-08", "DRILL-09"])
        blob = str(brief)
        assert "alice" not in blob
        assert brief["result"]["score"] == 90
        assert brief["result"]["violations"][0]["command"] == "OPEN_Q4@UPS_A"
        assert brief["drill"]["references"]
        assert len(brief["soe"]) <= ti.SOE_LINES

    def test_deterministic_en_es(self):
        _, tm, _ = run_drill08()
        brief = ti.build_brief(tm.last_report, ["DRILL-08", "DRILL-09"])
        en = ti.deterministic_debrief(brief, "en")
        assert "PASS with 90 / 100" in en["summary"]
        assert any("refused by the interlock" in x for x in en["to_correct"])
        assert en["next"] == "Repeat DRILL-08 until it passes with no violation."
        es = ti.deterministic_debrief(brief, "es")
        assert "Qué corregir" in es["text"]

    def test_clean_run_suggests_the_next_drill(self):
        _, tm, _ = run_drill08(extra_first=False)
        brief = ti.build_brief(tm.last_report, ["DRILL-07", "DRILL-08", "DRILL-09"])
        assert ti.deterministic_debrief(brief)["next"] == "Move on to DRILL-09."

    def test_citation_guard(self):
        refs = ["OSHA 29 CFR 1910.147: lockout", "Schneider Galaxy VX manual"]
        assert ti.unverified_citations("Per OSHA 1910.147 and NFPA 70E.", refs) == ["NFPA 70E"]
        assert ti.unverified_citations("No standards here.", refs) == []


class TestDebrief:
    def test_no_key_is_deterministic(self):
        _, tm, _ = run_drill08()
        r = debrief(tm.last_report, provider=FakeProvider(configured=False))
        assert r["source"] == "deterministic"
        assert "not configured" in r["note"]
        assert r["calls_today"] == 0

    def test_meta_text_cache_and_guard(self):
        _, tm, _ = run_drill08()
        p = FakeProvider()
        r = debrief(tm.last_report, provider=p, drill_ids=["DRILL-08"])
        assert (r["source"], r["model"]) == ("meta", "muse-spark-1.3")
        assert r["text"].startswith("Summary: ok.")
        assert "NFPA 110" in r["unverified_citations"]
        assert p.prompts[0][1] == ti.MAX_TOKENS
        assert "alice" not in p.prompts[0][0]
        again = debrief(tm.last_report, provider=p, drill_ids=["DRILL-08"])
        assert again["cached"] is True
        assert p.calls == 1
        assert again["calls_today"] == 1

    def test_daily_cap_and_bad_output(self, monkeypatch):
        _, tm, _ = run_drill08()
        monkeypatch.setenv(ti.DAILY_CAP_ENV, "1")
        bad = debrief(tm.last_report, provider=FakeProvider(text="[Meta API error 500]"))
        assert bad["source"] == "deterministic"
        assert "no usable text" in bad["note"]
        capped = debrief(tm.last_report, lang="es", provider=FakeProvider())
        assert capped["source"] == "deterministic"
        assert "cap reached (1" in capped["note"]

    def test_garbage_cap_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv(ti.DAILY_CAP_ENV, "lots")
        assert ti.daily_cap() == ti.DAILY_CAP_DEFAULT


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("DC_EPMS_REQUIRE_AUTH", raising=False)
    monkeypatch.delenv("META_API_KEY", raising=False)
    ctl, tm, eng = run_drill08()
    app = FastAPI()
    app.state.forensic_ledger = ForensicLedger(InMemoryPersistence(), key=b"k" * 32)
    trr.register_training_routes(app, lambda: ctl, eng, lambda: tm)
    with TestClient(app) as c:
        yield c


def bearer(name):
    user = seed_demo_users().find_by_username(name)
    return {"Authorization": f"Bearer {issue_token(user)}"}


class TestRoute:
    def test_debrief_route_deterministic_without_key(self, client):
        assert client.post("/api/training/debrief", json={}, headers=bearer("operator")).status_code == 403
        r = client.post("/api/training/debrief", json={"lang": "es"}, headers=bearer("manager"))
        assert r.status_code == 200
        body = r.json()
        assert (body["source"], body["lang"]) == ("deterministic", "es")
        entries = client.app.state.forensic_ledger.persistence._entries
        last = next(e for e in entries if e.entry_id == body["ledger_entry_id"])
        assert last.action == trr.ACTION_TRAINING_DEBRIEF
        assert last.payload["drill"] == "DRILL-08"
        assert "text" not in last.payload


def test_default_provider_uses_muse_spark(monkeypatch):
    """Without META_MODEL the instructor asks for muse-spark-1.3, not the
    provider's placeholder; without a key nothing is sent."""
    from backend import llm_providers
    seen = {}

    class Spy(llm_providers.MetaProvider):
        def __init__(self, **kw):
            seen.update(kw)
            super().__init__(**kw)

    monkeypatch.setattr(llm_providers, "MetaProvider", Spy)
    monkeypatch.delenv("META_MODEL", raising=False)
    monkeypatch.delenv("META_API_KEY", raising=False)
    _, tm, _ = run_drill08()
    r = debrief(tm.last_report, lang="es")
    assert seen["model"] == ti.DEFAULT_MODEL
    assert "Spanish" in seen["system_prompt"]
    assert r["source"] == "deterministic"


def test_failed_drill_debrief_lists_what_was_missing():
    """DRILL-07 left alone: the engine shuts down on low fuel. The
    debrief says why it ended and which steps were not reached, and does
    not call 'no step done' something that went well."""
    clock = Clock()
    ctl = dc.DeviceController.from_design(dc.load_design(DESIGN), clock=clock, wall_clock=clock)
    tm = tr.TrainingManager(tr.load_drills(DRILLS), clock=clock)
    eng = ae.AlarmEngine()
    tm.start("DRILL-07", "alice", ctl, eng)
    for _ in range(200):
        clock.t += 5
        view = tm.evaluate(ctl, eng)
        if not view["active"]:
            break
    assert tm.last_report["outcome"] == "FAIL"
    det = ti.deterministic_debrief(ti.build_brief(tm.last_report, ["DRILL-07"]), "es")
    assert det["to_correct"][0].startswith("El drill terminó: genset_a_01 shut down")
    assert any(x.startswith("Pasos que faltaron: LAG_AUTO") for x in det["to_correct"])
    assert not any("ningún paso" in x for x in det["went_well"])
    assert det["next"] == "Repite DRILL-07 hasta pasarlo."
    assert not any("después del tiempo objetivo" in x for x in det["to_correct"])


def test_error_hint_from_meta_error_body():
    from backend.llm_providers import _error_hint
    body = '{"error": {"message": "Model muse-spark-9 not found", "type": "not_found"}}'
    assert _error_hint(body) == "Model muse-spark-9 not found"
    assert _error_hint("<html>\n Not   Found </html>") == "<html> Not Found </html>"
    assert _error_hint("") == ""
    assert len(_error_hint("x" * 500)) == 160
