"""
tests/test_api_procedures.py -- Sprint Bite G5 API integration tests.

Verifies the HTTP contracts of the procedure-generator routes on an
ISOLATED FastAPI app (only the procedure router, no full-app lifespan)
-- this deliberately avoids the pre-existing test_smoke startup hang
(DC-EPMS-039) while still exercising the real route handlers.

Key assertion: a TECH_L4 activation attempt is rejected with HTTP 403.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.procedure_routes import router as procedure_router

_app = FastAPI()
_app.include_router(procedure_router)
client = TestClient(_app)


# ── /generate ─────────────────────────────────────────────────────────
def test_generate_sop_returns_200_draft():
    resp = client.post("/api/procedures/generate",
                        json={"asset_id": "chiller_1", "procedure_class": "SOP"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["procedure_class"] == "SOP"
    assert body["status"] == "DRAFT"
    assert len(body["steps"]) == 5


def test_generate_mop_micro_component_returns_200():
    resp = client.post("/api/procedures/generate",
                        json={"asset_id": "cdu_a_01_secondary_filter",
                              "procedure_class": "MOP"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["procedure_class"] == "MOP"
    iso = body["isolation_compile"]["isolation_points"]
    assert "cdu_a_01_isolation_valve_supply" in iso


def test_generate_eop_without_anomaly_profile_returns_400():
    resp = client.post("/api/procedures/generate",
                        json={"asset_id": "genset_a_01", "procedure_class": "EOP"})
    assert resp.status_code == 400


def test_generate_eop_with_anomaly_profile_returns_200():
    resp = client.post("/api/procedures/generate",
                        json={"asset_id": "genset_a_01", "procedure_class": "EOP",
                              "anomaly_profile": "gen_desync"})
    assert resp.status_code == 200
    assert resp.json()["procedure_class"] == "EOP"


def test_generate_unknown_asset_returns_400():
    resp = client.post("/api/procedures/generate",
                        json={"asset_id": "no_such_asset_xyz",
                              "procedure_class": "SOP"})
    assert resp.status_code == 400


def test_generate_rejects_bad_procedure_class():
    resp = client.post("/api/procedures/generate",
                        json={"asset_id": "chiller_1", "procedure_class": "BOGUS"})
    assert resp.status_code == 422  # pydantic pattern validation


# ── /{id}/activate ────────────────────────────────────────────────────
def test_activate_with_l5_returns_200_active():
    gen = client.post("/api/procedures/generate",
                      json={"asset_id": "ups_a", "procedure_class": "SOP"})
    draft = gen.json()
    resp = client.post(f"/api/procedures/{draft['procedure_id']}/activate",
                       json={"actor_role": "SENIOR_TECH_L5", "procedure": draft})
    assert resp.status_code == 200
    promoted = resp.json()
    assert promoted["status"] == "ACTIVE"
    assert promoted["version"] == "1.0"


def test_activate_with_tech_l4_returns_403():
    """G5 key assertion: a Level IV promotion attempt is forbidden."""
    gen = client.post("/api/procedures/generate",
                      json={"asset_id": "ups_a", "procedure_class": "SOP"})
    draft = gen.json()
    resp = client.post(f"/api/procedures/{draft['procedure_id']}/activate",
                       json={"actor_role": "TECH_L4", "procedure": draft})
    assert resp.status_code == 403


def test_activate_path_body_id_mismatch_returns_400():
    gen = client.post("/api/procedures/generate",
                      json={"asset_id": "ups_a", "procedure_class": "SOP"})
    draft = gen.json()
    resp = client.post("/api/procedures/SOME-OTHER-ID/activate",
                       json={"actor_role": "SME_L6", "procedure": draft})
    assert resp.status_code == 400
