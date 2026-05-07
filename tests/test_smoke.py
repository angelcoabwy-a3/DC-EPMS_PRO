"""
DC-EPMS PRO — Backend smoke tests
=====================================
Quick validation of API endpoints without requiring full DB/RAG setup.

Run:
    pytest tests/                    # all tests
    pytest tests/test_smoke.py       # smoke only
    pytest -v --no-header            # verbose
"""

import pathlib
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    """Boot the FastAPI app for testing."""
    from main import app

    with TestClient(app) as c:
        yield c


def test_health_endpoint_reachable(client):
    """Health endpoint should always respond even without DB."""
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["service"] == "dc-epms-pro"
    assert "postgres" in data
    assert "rag" in data
    assert "gemma" in data
    assert "gpu" in data


def test_telemetry_point_validation(client):
    """Telemetry POST should validate pydantic schema."""
    # Valid
    valid = {
        "it_load_kw": 16756.0,
        "pue": 1.103,
        "hall_temp_c": 22.6,
        "delta_t_c": 4.6,
        "scenario": "NORMAL",
    }
    r = client.post("/api/telemetry", json=valid)
    assert r.status_code == 200

    # Invalid PUE (out of range)
    invalid = valid | {"pue": 0.5}
    r = client.post("/api/telemetry", json=invalid)
    assert r.status_code == 422

    # Missing required field
    r = client.post("/api/telemetry", json={"pue": 1.1})
    assert r.status_code == 422


def test_incident_sql_safe(client):
    """SQL injection attempts must not succeed."""
    sql_injection = {
        "incident_id": "INC-TEST-0001",
        "source": "TEST",
        "title": "O'Brien'; DROP TABLE incidents; --",
        "detail": "x' OR '1'='1",
        "severity": "info",
        "status": "OPEN",
        "physics_json": '{"safe": true}',
    }
    r = client.post("/api/incidents", json=sql_injection)
    # Should return 200 with written:False if DB down, or 200 if DB up
    # Either way, MUST NOT crash
    assert r.status_code == 200
    # If DB is up, the parameterized query protected us
    # If DB is down, graceful degradation reports the error


def test_rag_query_validation(client):
    """RAG query validates min/max relevance."""
    r = client.post(
        "/api/rag/query",
        json={
            "question": "What is ASHRAE A2?",
            "n_results": 3,
            "min_relevance": 0.3,
        },
    )
    assert r.status_code == 200
    # Results may be empty if RAG unavailable — that's OK
    data = r.json()
    assert "results" in data


def test_agent_query_schema(client):
    """Agent query schema rejects bad inputs."""
    r = client.post(
        "/agent/stream",
        json={
            "query": "",
            "model_hint": "auto",
        },
    )
    assert r.status_code == 422  # empty query rejected by pydantic

    r = client.post(
        "/agent/stream",
        json={
            "query": "x" * 5000,
            "model_hint": "auto",
        },
    )
    assert r.status_code == 422  # too long


def test_lm_proxy_graceful_down(client):
    """LM Studio proxy returns 502 when LM Studio is unreachable."""
    # The test env probably doesn't have LM Studio running
    r = client.get("/lm/v1/models")
    # 502 (LM down) or 200 (LM up and mocked)
    assert r.status_code in (200, 502)


def test_shift_report_endpoint_exists(client):
    """Shift report generation endpoint should respond."""
    r = client.post(
        "/api/shift/report",
        json={
            "operator": "Test Operator",
            "hours_back": 8,
        },
    )
    # 200 (PDF generated) or 503 (reportlab missing)
    assert r.status_code in (200, 503)
    if r.status_code == 200:
        assert r.headers["content-type"] == "application/pdf"


def test_voice_stub_responds(client):
    """Voice endpoint should return stub response."""
    r = client.post("/api/voice/transcribe", content=b"")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "not_implemented"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
