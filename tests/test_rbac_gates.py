"""
DC-EPMS PRO — tests/test_rbac_gates.py
E2E Security Audit F3-4 — claim-based RBAC gate coverage.

Verifies the enforce-when-present authorization gate (backend/rbac.py):
  * a CLAIMED but insufficient actor_role -> hard HTTP 403
  * a sufficient claim -> passes
  * an OMITTED claim -> falls through (enforce-when-present convention)
and that the gate is wired into a live mutating endpoint.
"""

import pathlib
import sys

import pytest
from fastapi import HTTPException

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from backend.rbac import require_actor_role


# ── unit: the require_actor_role gate ────────────────────────────────
def test_insufficient_role_raises_403():
    """A claimed role below the minimum rank is rejected with 403."""
    with pytest.raises(HTTPException) as ei:
        require_actor_role("TECH_L4", 5, "approving a draft")   # rank 4 < 5
    assert ei.value.status_code == 403
    assert "Forbidden" in ei.value.detail


def test_unknown_role_claim_raises_403():
    """An unrecognised role string ranks 0 and is rejected."""
    with pytest.raises(HTTPException) as ei:
        require_actor_role("INTERN", 4, "creating a work order")
    assert ei.value.status_code == 403


def test_sufficient_role_passes():
    """A role at or above the minimum rank passes the gate."""
    require_actor_role("SENIOR_TECH_L5", 5, "approving")   # rank 5 == min
    require_actor_role("SME_L6", 5, "approving")           # rank 6 > min
    require_actor_role("SME_L6", 4, "creating")


def test_missing_claim_falls_through():
    """Enforce-when-present: an omitted / empty claim is NOT gated."""
    require_actor_role(None, 6, "anything")   # no raise
    require_actor_role("", 6, "anything")     # no raise


# ── integration: the gate wired into a live endpoint ─────────────────
@pytest.fixture(scope="module")
def client():
    """Plain TestClient — no lifespan (DC-EPMS-039 pattern). The RBAC
    gate fires at the top of the handler, before any DB work."""
    from fastapi.testclient import TestClient

    from main import app

    test_client = TestClient(app)
    yield test_client
    test_client.close()


def test_endpoint_rejects_insufficient_role(client):
    """POST /api/incidents with an unrecognised actor_role -> hard 403."""
    r = client.post("/api/incidents", json={
        "incident_id": "INC-RBAC-TEST", "source": "TEST", "title": "rbac gate",
        "actor_role": "INTERN",
    })
    assert r.status_code == 403


def test_endpoint_allows_omitted_claim(client):
    """The same endpoint with NO actor_role falls through (not 403) —
    enforce-when-present keeps the 706-test baseline green."""
    r = client.post("/api/incidents", json={
        "incident_id": "INC-RBAC-TEST-2", "source": "TEST", "title": "no claim",
    })
    assert r.status_code != 403
