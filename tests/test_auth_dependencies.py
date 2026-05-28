"""
tests/test_auth_dependencies.py
===============================
Epic 10 -- FastAPI dependency invariants for JWT extraction +
role gating + Maker-Checker distinctness.

These are tested by direct coroutine call against the dependency
functions (no TestClient round-trip), so they collect in the
project's broader test environment without tripping the
fastapi/starlette quirks. HTTPException is the contract.
"""

from __future__ import annotations

import asyncio
import warnings

warnings.filterwarnings(
    "ignore",
    message="'HTTP_422_UNPROCESSABLE_ENTITY' is deprecated",
    category=DeprecationWarning,
)

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from backend.auth.dependencies import (  # noqa: E402
    assert_maker_checker_distinct,
    extract_checker_jwt,
    get_current_user,
    require_role,
)
from backend.auth.jwt_handler import (  # noqa: E402
    ENV_JWT_SECRET,
    _reset_ephemeral_secret_for_tests,
    issue_token,
)
from backend.auth.models import Role, User  # noqa: E402


@pytest.fixture(autouse=True)
def _fixed_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        ENV_JWT_SECRET,
        "test-secret-32-bytes-or-more-for-hs256-XXXXXXX",
    )
    _reset_ephemeral_secret_for_tests()


def _make_user(user_id: str, role: Role) -> User:
    return User(
        user_id=user_id,
        username=user_id.replace("u-", ""),
        password_hash="ab" * 32,
        password_salt="cd" * 16,
        role=role,
    )


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


# ─── get_current_user ──────────────────────────────────────────────
class TestGetCurrentUser:
    def test_valid_bearer_returns_claims(self) -> None:
        user = _make_user("u-alice", Role.SAFETY_OFFICER)
        token = issue_token(user)
        claims = _run(get_current_user(authorization=f"Bearer {token}"))
        assert claims.sub == "u-alice"
        assert claims.role is Role.SAFETY_OFFICER

    def test_missing_header_raises_401(self) -> None:
        with pytest.raises(HTTPException) as ei:
            _run(get_current_user(authorization=None))
        assert ei.value.status_code == 401
        assert "missing" in str(ei.value.detail).lower()

    def test_non_bearer_scheme_raises_401(self) -> None:
        with pytest.raises(HTTPException) as ei:
            _run(get_current_user(authorization="Basic abc"))
        assert ei.value.status_code == 401
        assert "bearer" in str(ei.value.detail).lower()

    def test_empty_bearer_raises_401(self) -> None:
        with pytest.raises(HTTPException) as ei:
            _run(get_current_user(authorization="Bearer "))
        assert ei.value.status_code == 401

    def test_malformed_token_raises_401(self) -> None:
        with pytest.raises(HTTPException) as ei:
            _run(get_current_user(authorization="Bearer not.a.jwt"))
        assert ei.value.status_code == 401
        assert "invalid token" in str(ei.value.detail).lower()


# ─── require_role ──────────────────────────────────────────────────
class TestRequireRole:
    def test_equal_role_passes(self) -> None:
        user = _make_user("u-1", Role.SAFETY_OFFICER)
        token = issue_token(user)
        gate = require_role(Role.SAFETY_OFFICER)
        claims = _run(gate(authorization=f"Bearer {token}"))
        assert claims.sub == "u-1"

    def test_higher_role_passes(self) -> None:
        user = _make_user("u-1", Role.FACILITY_MANAGER)
        token = issue_token(user)
        gate = require_role(Role.SAFETY_OFFICER)
        claims = _run(gate(authorization=f"Bearer {token}"))
        assert claims.role is Role.FACILITY_MANAGER

    def test_lower_role_raises_403(self) -> None:
        user = _make_user("u-1", Role.L1_OPERATOR)
        token = issue_token(user)
        gate = require_role(Role.SAFETY_OFFICER)
        with pytest.raises(HTTPException) as ei:
            _run(gate(authorization=f"Bearer {token}"))
        assert ei.value.status_code == 403
        assert "below required" in str(ei.value.detail).lower()

    def test_missing_token_raises_401(self) -> None:
        gate = require_role(Role.SAFETY_OFFICER)
        with pytest.raises(HTTPException) as ei:
            _run(gate(authorization=None))
        assert ei.value.status_code == 401


# ─── extract_checker_jwt ───────────────────────────────────────────
class TestExtractCheckerJWT:
    def test_valid_token_returns_claims(self) -> None:
        user = _make_user("u-checker", Role.SAFETY_OFFICER)
        token = issue_token(user)
        claims = extract_checker_jwt(token)
        assert claims.sub == "u-checker"

    def test_missing_token_raises_400(self) -> None:
        with pytest.raises(HTTPException) as ei:
            extract_checker_jwt(None)
        assert ei.value.status_code == 400

    def test_malformed_token_raises_401(self) -> None:
        with pytest.raises(HTTPException) as ei:
            extract_checker_jwt("garbage")
        assert ei.value.status_code == 401


# ─── Maker-Checker distinctness ────────────────────────────────────
class TestMakerCheckerDistinct:
    def test_distinct_user_ids_pass(self) -> None:
        u_a = _make_user("u-a", Role.SAFETY_OFFICER)
        u_b = _make_user("u-b", Role.SAFETY_OFFICER)
        a_claims = _run(
            get_current_user(authorization=f"Bearer {issue_token(u_a)}"),
        )
        b_claims = _run(
            get_current_user(authorization=f"Bearer {issue_token(u_b)}"),
        )
        # No exception means pass.
        assert_maker_checker_distinct(a_claims, b_claims)

    def test_same_user_id_raises_403(self) -> None:
        u = _make_user("u-same", Role.SAFETY_OFFICER)
        a_token = issue_token(u)
        b_token = issue_token(u)
        a_claims = _run(get_current_user(authorization=f"Bearer {a_token}"))
        b_claims = _run(get_current_user(authorization=f"Bearer {b_token}"))
        with pytest.raises(HTTPException) as ei:
            assert_maker_checker_distinct(a_claims, b_claims)
        assert ei.value.status_code == 403
        assert "distinct" in str(ei.value.detail).lower()
