"""
tests/test_no_database_mode.py
==============================
Release R1 -- the platform must be fully browsable without
PostgreSQL (public test deployment, laptop without Docker).

Covers:
  * backend/kpi_fallback.build_kpi_point -- pure derivation of the
    Overview KPI row from the Kalman channel payload + Phase 1 PUE.
  * GET /api/telemetry/latest -- "simulator" source when no DB row
    exists; silent (None) when the simulator is switched off.
  * CMMS on the in-memory repository: routes mounted, assets seeded
    from site_model.yml, work-order lifecycle functional, storage
    backend reported honestly.
"""

from __future__ import annotations

import pathlib
import sys
from datetime import UTC, datetime

import pytest

# Same import path as tests/test_smoke.py ("import main"): a second
# import under the name backend.main would register the Prometheus
# collectors twice (DC-EPMS-008 class of failure).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "backend"))

from fastapi.testclient import TestClient

from backend.cmms_repository import (
    InMemoryCMMSRepository,
    MockCMMSRepository,
)
from backend.kpi_fallback import SOURCE_SIMULATOR, build_kpi_point

_PUE_P1 = {
    "pue": 1.33,
    "rack_count": 118,
    "rack_kw": 142.0,
    "breakdown": {"it_load_kw": 16756.0},
}


def _channels() -> dict:
    return {
        "rack_a_01_01:rack_inlet_T_c": {"last_emission": 21.0},
        "rack_a_01_02:rack_inlet_T_c": {"last_emission": 23.0},
        "rack_a_01_01:dlc_supply_T_c": {"last_emission": 30.0},
        "rack_a_01_02:dlc_supply_T_c": {"last_emission": 30.5},
        "rack_a_01_01:dlc_return_T_c": {"last_emission": 45.0},
        "rack_a_01_02:dlc_return_T_c": {"last_emission": 45.5},
        "ups_a:voltage_v_phase_ab": {"last_emission": 481.0},
        "main_bus_dc_d:voltage_v_dc_bus": {"last_emission": 799.8},
    }


class TestBuildKpiPoint:
    def test_full_point(self):
        now = datetime(2026, 11, 13, 20, 0, 0, tzinfo=UTC)
        point = build_kpi_point(_channels(), _PUE_P1, now=now)
        assert point == {
            "ts": "2026-11-13T20:00:00+00:00",
            "it_load_kw": 16756.0,
            "pue": 1.33,
            "hall_temp_c": 22.0,
            "delta_t_c": 15.0,
            "ttc_seconds": None,
            "scenario": None,
            "rack_count": 118,
            "rack_tdp_kw": 142.0,
            "hall_temp_sample_count": 2,
        }

    def test_hall_temp_ignores_other_metrics(self):
        ch = _channels()
        ch["rack_a_01_03:gpu_Tj_c"] = {"last_emission": 95.0}
        ch["sscb_d_01:sscb_junction_T_c"] = {"last_emission": 54.0}
        assert build_kpi_point(ch, _PUE_P1)["hall_temp_c"] == 22.0

    @pytest.mark.parametrize("channels", [None, {}, {"ups_a:ups_soc_pct": {"last_emission": 99.0}}])
    def test_no_rack_inlet_channel_means_no_point(self, channels):
        assert build_kpi_point(channels, _PUE_P1) is None

    def test_missing_pue_keeps_measured_fields_only(self):
        point = build_kpi_point(_channels(), None)
        assert point["hall_temp_c"] == 22.0
        assert point["delta_t_c"] == 15.0
        assert point["pue"] is None
        assert point["it_load_kw"] is None
        assert point["rack_count"] is None
        assert point["rack_tdp_kw"] is None

    def test_missing_dlc_pair_gives_no_delta_t(self):
        ch = {k: v for k, v in _channels().items() if "dlc_return" not in k}
        assert build_kpi_point(ch, _PUE_P1)["delta_t_c"] is None

    @pytest.mark.parametrize("bad", [None, "22.0", True, float("nan"), float("inf")])
    def test_malformed_emissions_are_skipped(self, bad):
        ch = _channels()
        ch["rack_a_01_03:rack_inlet_T_c"] = {"last_emission": bad}
        ch["rack_a_01_04:rack_inlet_T_c"] = "not-a-dict"
        point = build_kpi_point(ch, _PUE_P1)
        assert point["hall_temp_c"] == 22.0
        assert point["hall_temp_sample_count"] == 2

    def test_malformed_pue_snapshot_never_raises(self):
        point = build_kpi_point(
            _channels(),
            {"pue": "n/a", "rack_count": True, "rack_kw": None, "breakdown": []},
        )
        assert point["pue"] is None
        assert point["rack_count"] is None
        assert point["rack_tdp_kw"] is None
        assert point["it_load_kw"] is None

    def test_naive_clock_default_is_utc_iso(self):
        ts = build_kpi_point(_channels(), _PUE_P1)["ts"]
        assert datetime.fromisoformat(ts).utcoffset().total_seconds() == 0

    def test_source_label_constant(self):
        assert SOURCE_SIMULATOR == "simulator"


def test_in_memory_alias_is_the_same_class():
    assert InMemoryCMMSRepository is MockCMMSRepository


@pytest.fixture
def no_db_client(monkeypatch: pytest.MonkeyPatch):
    """Real app object booted with PostgreSQL forced unavailable."""
    import main as main_mod

    monkeypatch.setattr(main_mod, "DBManager", None)
    monkeypatch.setattr(main_mod, "db_manager", None)
    monkeypatch.delenv("DC_EPMS_CMMS_FALLBACK", raising=False)
    monkeypatch.delenv("DC_EPMS_REQUIRE_AUTH", raising=False)
    monkeypatch.setenv("DC_EPMS_USE_SIMULATOR", "1")
    # DC-EPMS-069: the GraphRAG warmup crashes natively on AMD + Windows.
    monkeypatch.setenv("DC_EPMS_SKIP_WARMUP", "1")
    with TestClient(main_mod.app) as client:
        yield client


class TestNoDatabaseApp:
    def test_health_reports_postgres_down(self, no_db_client):
        body = no_db_client.get("/api/health").json()
        assert body["postgres"]["status"] == "down"

    def test_kpi_latest_comes_from_simulator(self, no_db_client):
        res = no_db_client.get("/api/telemetry/latest")
        assert res.status_code == 200
        body = res.json()
        assert body["source"] == "simulator"
        latest = body["latest"]
        # ASHRAE TC 9.9 Class A2 allowable envelope for the hall mean.
        assert 10.0 <= latest["hall_temp_c"] <= 35.0
        assert latest["hall_temp_sample_count"] >= 1
        assert latest["rack_count"] == 118
        assert latest["rack_tdp_kw"] == 142.0
        assert latest["it_load_kw"] == pytest.approx(118 * 142.0)
        assert 1.0 < latest["pue"] < 2.0
        # DLC return must be warmer than supply.
        assert latest["delta_t_c"] > 0

    def test_kpi_latest_is_silent_when_simulator_is_off(self, no_db_client, monkeypatch):
        monkeypatch.setenv("DC_EPMS_USE_SIMULATOR", "0")
        body = no_db_client.get("/api/telemetry/latest").json()
        assert body["latest"] is None
        assert body["error"] == "DB unavailable"
        assert "source" not in body

    def test_cmms_health_reports_memory_backend(self, no_db_client):
        res = no_db_client.get("/api/cmms/health")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "up"
        assert body["backend"] == "memory"
        assert body["asset_count"] > 0

    def test_cmms_assets_are_seeded_from_site_model(self, no_db_client):
        res = no_db_client.get("/api/cmms/assets", params={"limit": 500})
        assert res.status_code == 200
        racks = no_db_client.get(
            "/api/cmms/assets", params={"asset_type": "it_rack", "limit": 200},
        )
        assert racks.status_code == 200

    def test_cmms_work_order_listing_works(self, no_db_client):
        res = no_db_client.get(
            "/api/cmms/work-orders", params={"only_open": "true", "limit": 200},
        )
        assert res.status_code == 200

    def test_dependent_routers_are_mounted(self, no_db_client):
        # These routers are wired inside the CMMS boot block; before
        # R1 they answered 404 whenever PostgreSQL was down.
        assert no_db_client.get("/api/tech-assist/documents").status_code != 404
        assert no_db_client.get("/api/optimizer/health").status_code != 404
        assert no_db_client.get("/api/optimizer/proposals").status_code != 404


class TestWarmupSkip:
    """DC-EPMS-069: DC_EPMS_SKIP_WARMUP=1 must keep the lifespan away
    from the embedding stack (both warmup stages)."""

    def test_skip_flag_bypasses_both_stages(self, monkeypatch: pytest.MonkeyPatch):
        import main as main_mod

        calls: list[str] = []

        class _Spy:
            def loto_with_knowledge(self, cid):
                calls.append(f"graphrag:{cid}")

            def audit(self, request):
                calls.append("loto_audit")

        monkeypatch.setattr(main_mod, "DBManager", None)
        monkeypatch.setattr(main_mod, "db_manager", None)
        monkeypatch.setattr(main_mod, "_s2_service", _Spy(), raising=False)
        monkeypatch.setattr(main_mod.app.state, "loto_auditor", _Spy(), raising=False)
        monkeypatch.setenv("DC_EPMS_SKIP_WARMUP", "1")
        with TestClient(main_mod.app) as client:
            assert client.get("/api/health").status_code == 200
        assert calls == []

    def test_without_the_flag_the_warmup_runs(self, monkeypatch: pytest.MonkeyPatch):
        import main as main_mod

        calls: list[str] = []

        class _Spy:
            def loto_with_knowledge(self, cid):
                calls.append("graphrag")

        monkeypatch.setattr(main_mod, "DBManager", None)
        monkeypatch.setattr(main_mod, "db_manager", None)
        monkeypatch.setattr(main_mod, "_s2_service", _Spy(), raising=False)
        monkeypatch.setattr(main_mod.app.state, "loto_auditor", None, raising=False)
        monkeypatch.delenv("DC_EPMS_SKIP_WARMUP", raising=False)
        with TestClient(main_mod.app):
            pass
        assert calls == ["graphrag"]


def test_session_default_keeps_the_warmup_off():
    """tests/conftest.py fence: every test that enters the real lifespan
    (test_session_gate.TestRealApp, test_ot_security, ...) runs with the
    warmup off unless it opts back in."""
    import os

    assert os.environ.get("DC_EPMS_SKIP_WARMUP") == "1"


# ── DC-EPMS-071: public /api/health leaks no internals ─────────────
@pytest.fixture
def public_no_db_client(monkeypatch: pytest.MonkeyPatch):
    """Gated (public) boot with no PostgreSQL, no RAG, loopback LLM."""
    import main as main_mod

    monkeypatch.setattr(main_mod, "DBManager", None)
    monkeypatch.setattr(main_mod, "db_manager", None)
    monkeypatch.delenv("DC_EPMS_CMMS_FALLBACK", raising=False)
    monkeypatch.setenv("DC_EPMS_REQUIRE_AUTH", "1")
    monkeypatch.setenv("DC_EPMS_JWT_SECRET", "t" * 48)
    monkeypatch.setenv("DC_EPMS_USE_SIMULATOR", "1")
    monkeypatch.setenv("DC_EPMS_SKIP_WARMUP", "1")
    monkeypatch.setattr(main_mod, "LM_STUDIO_URL", "http://127.0.0.1:1234")
    # A public host has no GPU. Force the NVML probe to "unavailable" so the
    # result does not depend on the machine running the suite (the operator
    # workstation has a real RTX 3060 and reported "IDLE").
    monkeypatch.setattr(main_mod, "_read_gpu_stats", lambda: {"source": "unavailable"})
    with TestClient(main_mod.app) as client:
        # The lifespan (re)binds rag_service when chromadb is installed
        # (operator Windows venv), so force "no RAG" AFTER startup.
        monkeypatch.setattr(main_mod, "rag_service", None)
        yield client


class TestPublicHealth:
    def test_anonymous_readable(self, public_no_db_client):
        assert public_no_db_client.get("/api/health").status_code == 200

    def test_absent_subsystems_report_disabled_not_down(self, public_no_db_client):
        body = public_no_db_client.get("/api/health").json()
        assert body["mode"] == "public"
        for key in ("postgres", "rag", "gemma"):
            assert body[key]["status"] == "disabled", key
        assert body["gpu"]["status"] == "disabled"

    def test_present_gpu_is_reported_as_is(self, public_no_db_client, monkeypatch):
        import main as main_mod

        fake = {"source": "nvml", "gpu": "RTX 3060", "status": "IDLE"}
        monkeypatch.setattr(main_mod, "_read_gpu_stats", lambda: dict(fake))
        body = public_no_db_client.get("/api/health").json()
        assert body["gpu"]["status"] == "IDLE"
        assert body["gpu"]["source"] == "nvml"

    def test_no_loopback_url_or_error_text(self, public_no_db_client):
        raw = public_no_db_client.get("/api/health").text
        assert "127.0.0.1" not in raw
        assert "localhost" not in raw
        assert "1234" not in raw
        assert '"error"' not in raw

    def test_local_mode_keeps_full_diagnostics(self, no_db_client):
        body = no_db_client.get("/api/health").json()
        assert "mode" not in body
        assert body["postgres"]["status"] == "down"
        assert "url" in body["gemma"]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://127.0.0.1:1234", True),
        ("http://localhost:1234/v1", True),
        ("http://[::1]:1234", True),
        ("https://llm.example.com", False),
        ("not a url", False),
    ],
)
def test_is_loopback_url(url, expected):
    import main as main_mod

    assert main_mod._is_loopback_url(url) is expected
