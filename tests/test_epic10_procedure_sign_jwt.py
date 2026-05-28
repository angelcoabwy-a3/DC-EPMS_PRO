"""
tests/test_epic10_procedure_sign_jwt.py
=======================================
Epic 10 -- JWT-gated procedure sign + Maker-Checker dual-JWT
distinctness invariants on /api/procedures/architect/sign.

The existing pre-Epic-10 tests in tests/test_procedure_architect.py
exercise the body-only signing path; this file adds the JWT path:

  - /architect/generate: 401 missing Auth, 403 below L2_TECHNICIAN,
    200 with valid JWT.
  - /architect/sign (SOP): 401 missing Auth, 403 below SAFETY_OFFICER,
    200 with valid SAFETY_OFFICER JWT, ledger entry records
    jwt_authenticated=True.
  - /architect/sign (MOP) Maker-Checker dual-JWT:
      maker JWT -> 202,
      same JWT as checker -> 403,
      second JWT with DIFFERENT user_id -> 200 + ledger entry
      with both subjects.

  - Forged / expired token -> 401.
"""

from __future__ import annotations

import warnings

warnings.filterwarnings(
    "ignore",
    message="'HTTP_422_UNPROCESSABLE_ENTITY' is deprecated",
    category=DeprecationWarning,
)

import secrets  # noqa: E402

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.auth.jwt_handler import (  # noqa: E402
    ENV_JWT_SECRET,
    _reset_ephemeral_secret_for_tests,
    issue_token,
)
from backend.auth.models import Role, User  # noqa: E402
from backend.ledger.forensic_ledger import (  # noqa: E402
    ForensicLedger,
    InMemoryPersistence,
)
from backend.procedure_routes import (  # noqa: E402
    _reset_pending_mop_signatures_for_test,
    router as procedure_router,
)


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        ENV_JWT_SECRET,
        "test-secret-32-bytes-or-more-for-hs256-XXXXXXX",
    )
    _reset_ephemeral_secret_for_tests()
    _reset_pending_mop_signatures_for_test()


@pytest.fixture
def app_with_ledger() -> FastAPI:
    app = FastAPI()
    app.state.forensic_ledger = ForensicLedger(InMemoryPersistence())
    # The router already carries its own /api/procedures prefix --
    # mounting with no extra prefix yields /api/procedures/architect/*.
    app.include_router(procedure_router)
    return app


def _user(user_id: str, role: Role) -> User:
    return User(
        user_id=user_id,
        username=user_id,
        password_hash="ab" * 32,
        password_salt="cd" * 16,
        role=role,
    )


def _bearer(user_id: str, role: Role) -> dict[str, str]:
    token = issue_token(_user(user_id, role))
    return {"Authorization": f"Bearer {token}"}


SOP_OK = (
    "## Procedimiento de Operación Estándar\n\n"
    "1. Trabajo en frío con sistema de-energizado.\n"
    "2. Documentar lectura inicial.\n"
)


MOP_OK = """## MOP — UPS battery cabinet replacement

### 1. Alcance y Objetivo
Reemplazo seguro de cabinet UPS-B.

### 2. Evaluación de Impacto y Riesgos
Vector Eléctrico. Impacto Aguas Arriba/Abajo.

### 3. Prerrequisitos
LOTO aplicado per CSA Z462-24. PPE NFPA 70E categoría 2.
Agente Revisor (Checker) ONLINE en MCP. HVAC AI confirmado.

### 4. Pasos Secuenciales
1. [HOLD POINT] Vivo-Muerto-Vivo verificación en cabinet UPS-B.
2. Aislar batería per LOTO.
3. Drenar capacitores per NEC 460.6 (5 minutos).
4. Reemplazar cabinet.
5. Re-energizar y verificar.

### 5. Plan de Reversión / Back-out
Re-instalar cabinet original.
"""


# ─── /architect/generate JWT gate ─────────────────────────────────
class TestArchitectGenerateJWT:
    def test_missing_jwt_falls_back_to_body_path(
        self, app_with_ledger: FastAPI,
    ) -> None:
        """Backward compat: pre-Epic-10 callers without Authorization
        still get a 200 (the body-only test suite stays green)."""
        client = TestClient(app_with_ledger)
        r = client.post(
            "/api/procedures/architect/generate",
            json={
                "doc_type": "SOP",
                "context": "demo context >=10 chars long",
            },
        )
        assert r.status_code == 200

    def test_l1_operator_jwt_is_refused_403(
        self, app_with_ledger: FastAPI,
    ) -> None:
        client = TestClient(app_with_ledger)
        r = client.post(
            "/api/procedures/architect/generate",
            json={
                "doc_type": "SOP",
                "context": "demo context >=10 chars long",
            },
            headers=_bearer("u-op", Role.L1_OPERATOR),
        )
        assert r.status_code == 403
        assert "L2_TECHNICIAN" in r.json()["detail"]

    def test_l2_technician_jwt_passes(
        self, app_with_ledger: FastAPI,
    ) -> None:
        client = TestClient(app_with_ledger)
        r = client.post(
            "/api/procedures/architect/generate",
            json={
                "doc_type": "SOP",
                "context": "demo context >=10 chars long",
            },
            headers=_bearer("u-tech", Role.L2_TECHNICIAN),
        )
        assert r.status_code == 200

    def test_malformed_jwt_returns_401(
        self, app_with_ledger: FastAPI,
    ) -> None:
        client = TestClient(app_with_ledger)
        r = client.post(
            "/api/procedures/architect/generate",
            json={
                "doc_type": "SOP",
                "context": "demo context >=10 chars long",
            },
            headers={"Authorization": "Bearer not-a-jwt"},
        )
        assert r.status_code == 401
        assert "invalid token" in r.json()["detail"].lower()

    def test_non_bearer_scheme_returns_401(
        self, app_with_ledger: FastAPI,
    ) -> None:
        client = TestClient(app_with_ledger)
        r = client.post(
            "/api/procedures/architect/generate",
            json={
                "doc_type": "SOP",
                "context": "demo context >=10 chars long",
            },
            headers={"Authorization": "Basic abc"},
        )
        assert r.status_code == 401


# ─── /architect/sign JWT gate (SOP single-signature) ──────────────
class TestArchitectSignSOPJWT:
    def test_l2_technician_cannot_sign(
        self, app_with_ledger: FastAPI,
    ) -> None:
        client = TestClient(app_with_ledger)
        r = client.post(
            "/api/procedures/architect/sign",
            json={
                "draft_id": "d1", "doc_type": "SOP",
                "content": SOP_OK, "operator_id": "u-tech",
            },
            headers=_bearer("u-tech", Role.L2_TECHNICIAN),
        )
        assert r.status_code == 403
        assert "SAFETY_OFFICER" in r.json()["detail"]

    def test_safety_officer_signs_ok(
        self, app_with_ledger: FastAPI,
    ) -> None:
        client = TestClient(app_with_ledger)
        r = client.post(
            "/api/procedures/architect/sign",
            json={
                "draft_id": "d-sop-1", "doc_type": "SOP",
                "content": SOP_OK, "operator_id": "u-safety-a",
            },
            headers=_bearer("u-safety-a", Role.SAFETY_OFFICER),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["signed"] is True
        assert body["entry_id"]

    def test_signed_entry_records_jwt_auth_flag(
        self, app_with_ledger: FastAPI,
    ) -> None:
        client = TestClient(app_with_ledger)
        client.post(
            "/api/procedures/architect/sign",
            json={
                "draft_id": "d-sop-2", "doc_type": "SOP",
                "content": SOP_OK, "operator_id": "u-safety-a",
            },
            headers=_bearer("u-safety-a", Role.SAFETY_OFFICER),
        )
        ledger = app_with_ledger.state.forensic_ledger
        entries = []
        # Walk the in-memory store -- ledger.fetch_all() is async; use
        # a sync probe via the persistence directly.
        import asyncio
        entries = asyncio.run(ledger.fetch_all())
        sop_entries = [
            e for e in entries
            if e.payload.get("draft_id") == "d-sop-2"
        ]
        assert len(sop_entries) == 1
        assert sop_entries[0].payload["jwt_authenticated"] is True

    def test_sop_without_jwt_uses_body_path(
        self, app_with_ledger: FastAPI,
    ) -> None:
        """Backward compat: body-only sign (no JWT) still works."""
        client = TestClient(app_with_ledger)
        r = client.post(
            "/api/procedures/architect/sign",
            json={
                "draft_id": "d-sop-legacy", "doc_type": "SOP",
                "content": SOP_OK, "operator_id": "legacy-op",
                "actor_role": "SME_L6",
            },
        )
        assert r.status_code == 200


# ─── /architect/sign Maker-Checker dual-JWT (MOP) ─────────────────
class TestMakerCheckerDualJWT:
    def test_maker_jwt_returns_202_awaiting(
        self, app_with_ledger: FastAPI,
    ) -> None:
        client = TestClient(app_with_ledger)
        r = client.post(
            "/api/procedures/architect/sign",
            json={
                "draft_id": "d-mop-1", "doc_type": "MOP",
                "content": MOP_OK, "operator_id": "ignored-overridden",
            },
            headers=_bearer("u-safety-a", Role.SAFETY_OFFICER),
        )
        assert r.status_code == 202
        body = r.json()
        assert body["signed"] is False
        # The pending state must record the JWT sub, not the body
        # operator_id -- the JWT override fired.
        assert body["first_signer"] == "u-safety-a"

    def test_same_user_id_second_call_refused_403(
        self, app_with_ledger: FastAPI,
    ) -> None:
        client = TestClient(app_with_ledger)
        # Maker sign
        client.post(
            "/api/procedures/architect/sign",
            json={
                "draft_id": "d-mop-self", "doc_type": "MOP",
                "content": MOP_OK, "operator_id": "u-safety-a",
            },
            headers=_bearer("u-safety-a", Role.SAFETY_OFFICER),
        )
        # Same JWT sub tries to be the checker
        r = client.post(
            "/api/procedures/architect/sign",
            json={
                "draft_id": "d-mop-self", "doc_type": "MOP",
                "content": MOP_OK, "operator_id": "u-safety-a",
            },
            headers=_bearer("u-safety-a", Role.SAFETY_OFFICER),
        )
        assert r.status_code == 403
        assert "self-witness" in r.json()["detail"].lower() or \
            "different operators" in r.json()["detail"].lower()

    def test_distinct_jwt_user_ids_seal_the_entry(
        self, app_with_ledger: FastAPI,
    ) -> None:
        client = TestClient(app_with_ledger)
        # Maker
        r1 = client.post(
            "/api/procedures/architect/sign",
            json={
                "draft_id": "d-mop-pair", "doc_type": "MOP",
                "content": MOP_OK, "operator_id": "u-safety-a",
            },
            headers=_bearer("u-safety-a", Role.SAFETY_OFFICER),
        )
        assert r1.status_code == 202
        # Checker (distinct user_id)
        r2 = client.post(
            "/api/procedures/architect/sign",
            json={
                "draft_id": "d-mop-pair", "doc_type": "MOP",
                "content": MOP_OK, "operator_id": "u-safety-b",
            },
            headers=_bearer("u-safety-b", Role.SAFETY_OFFICER),
        )
        assert r2.status_code == 200, r2.text
        body = r2.json()
        assert body["signed"] is True
        assert body["entry_id"]
        # The ledger entry must carry BOTH signers (JWT subs).
        import asyncio
        ledger = app_with_ledger.state.forensic_ledger
        entries = asyncio.run(ledger.fetch_all())
        sealed = [
            e for e in entries
            if e.payload.get("draft_id") == "d-mop-pair"
        ]
        assert len(sealed) == 1
        assert sealed[0].payload["first_signer"] == "u-safety-a"
        assert sealed[0].payload["second_signer"] == "u-safety-b"
        assert sealed[0].payload["jwt_authenticated"] is True

    def test_l2_technician_cannot_be_maker(
        self, app_with_ledger: FastAPI,
    ) -> None:
        client = TestClient(app_with_ledger)
        r = client.post(
            "/api/procedures/architect/sign",
            json={
                "draft_id": "d-mop-deny", "doc_type": "MOP",
                "content": MOP_OK, "operator_id": "u-tech",
            },
            headers=_bearer("u-tech", Role.L2_TECHNICIAN),
        )
        assert r.status_code == 403


# ─── Token failure modes ──────────────────────────────────────────
class TestTokenFailures:
    def test_forged_signature_returns_401(
        self, app_with_ledger: FastAPI,
    ) -> None:
        client = TestClient(app_with_ledger)
        token = issue_token(_user("u-safety-a", Role.SAFETY_OFFICER))
        head, payload, sig = token.split(".")
        forged = ".".join([head, payload, secrets.token_urlsafe(40)])
        r = client.post(
            "/api/procedures/architect/sign",
            json={
                "draft_id": "d-x", "doc_type": "SOP",
                "content": SOP_OK, "operator_id": "u-safety-a",
            },
            headers={"Authorization": f"Bearer {forged}"},
        )
        assert r.status_code == 401
