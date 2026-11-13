"""
tests/test_session_gate.py
==========================
Release R1 -- public-deployment session gate
(backend/auth/session_gate.py) + gated login cookie + password
seeding policy.

Invariants:
  * Gate OFF (default): every route behaves exactly as before.
  * Gate ON: non-public http routes answer 401 without a session,
    200 with a Bearer JWT or the httpOnly cookie; forged / expired
    tokens answer 401; websocket handshakes are refused.
  * Allow-list stays reachable with no session (SPA shell, health,
    login, hackathon MOP Verification).
  * Gated login mirrors the JWT into an httpOnly cookie; un-gated
    login payload is byte-for-byte the pre-R1 shape.
  * Gated seeding never installs the repo-default passwords.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.auth.jwt_handler import (
    ENV_JWT_SECRET,
    ENV_PASSWORD_PREFIX,
    _reset_ephemeral_secret_for_tests,
    issue_token,
    seed_demo_users,
)
from backend.auth.models import Role, User
from backend.auth.session_gate import (
    COOKIE_NAME,
    ENV_REQUIRE_AUTH,
    SessionGateMiddleware,
    gate_enabled,
    is_public_path,
)


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        ENV_JWT_SECRET, "test-secret-32-bytes-or-more-for-hs256-XXXXXXX",
    )
    monkeypatch.delenv(ENV_REQUIRE_AUTH, raising=False)
    _reset_ephemeral_secret_for_tests()


def _user() -> User:
    return User(
        user_id="u-test",
        username="tester",
        password_hash="00",
        password_salt="00",
        role=Role.L1_OPERATOR,
    )


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.add_middleware(SessionGateMiddleware)

    @app.get("/")
    async def root() -> dict:
        return {"shell": True}

    @app.get("/api/health")
    async def health() -> dict:
        return {"ok": True}

    @app.get("/api/copilot/mop/steps")
    async def mop_steps() -> dict:
        return {"steps": []}

    @app.get("/api/site/components")
    async def components() -> dict:
        return {"components": 113}

    @app.get("/lm/v1/models")
    async def lm_models() -> dict:
        return {"data": []}

    @app.websocket("/api/hermes")
    async def hermes(ws: WebSocket) -> None:
        await ws.accept()
        await ws.send_json({"hello": True})
        await ws.close()

    return TestClient(app)


class TestGateSwitch:
    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " On "])
    def test_truthy_values_enable(self, monkeypatch, value):
        monkeypatch.setenv(ENV_REQUIRE_AUTH, value)
        assert gate_enabled() is True

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe"])
    def test_other_values_disable(self, monkeypatch, value):
        monkeypatch.setenv(ENV_REQUIRE_AUTH, value)
        assert gate_enabled() is False

    def test_unset_is_disabled(self):
        assert gate_enabled() is False


class TestAllowList:
    @pytest.mark.parametrize(
        "path",
        [
            "/",
            "/favicon.ico",
            "/api/health",
            "/api/auth/login",
            "/assets/app.css",
            "/assets/js/main.js",
            "/api/copilot/mop/verify",
            "/api/copilot/mop/session/start",
        ],
    )
    def test_public(self, path):
        assert is_public_path(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "/api/site/components",
            "/api/copilot/investigate",
            "/api/copilot/mops",
            "/api/auth/whoami",
            "/api/bms/write",
            "/agent/stream",
            "/lm/v1/chat/completions",
            "/metrics",
            "/docs",
            "/openapi.json",
            "/assets",
            "/api/healthz",
        ],
    )
    def test_private(self, path):
        assert is_public_path(path) is False


class TestGateOff:
    def test_everything_open_by_default(self, client):
        assert client.get("/api/site/components").status_code == 200
        assert client.get("/lm/v1/models").status_code == 200
        with client.websocket_connect("/api/hermes") as ws:
            assert ws.receive_json() == {"hello": True}


class TestGateOn:
    @pytest.fixture(autouse=True)
    def _on(self, monkeypatch):
        monkeypatch.setenv(ENV_REQUIRE_AUTH, "1")

    def test_private_route_needs_session(self, client):
        res = client.get("/api/site/components")
        assert res.status_code == 401
        assert res.json() == {"detail": "authentication required"}
        assert res.headers["www-authenticate"] == "Bearer"
        assert res.headers["cache-control"] == "no-store"

    def test_llm_proxy_is_gated(self, client):
        assert client.get("/lm/v1/models").status_code == 401

    def test_public_routes_stay_open(self, client):
        assert client.get("/").status_code == 200
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/copilot/mop/steps").status_code == 200

    def test_bearer_header_passes(self, client):
        token = issue_token(_user())
        res = client.get(
            "/api/site/components",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        assert res.json() == {"components": 113}

    def test_cookie_passes(self, client):
        client.cookies.set(COOKIE_NAME, issue_token(_user()))
        assert client.get("/api/site/components").status_code == 200

    def test_forged_token_rejected(self, client):
        token = issue_token(_user())
        forged = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
        res = client.get(
            "/api/site/components",
            headers={"Authorization": f"Bearer {forged}"},
        )
        assert res.status_code == 401
        assert res.json() == {"detail": "invalid or expired session"}

    def test_expired_token_rejected(self, client):
        import time

        import jwt

        from backend.auth.jwt_handler import JWT_ALG, _get_jwt_secret

        now = int(time.time())
        token = jwt.encode(
            {
                "sub": "u-test", "username": "tester",
                "role": Role.L1_OPERATOR.value,
                "iat": now - 7200, "exp": now - 3600, "jti": "expired",
            },
            _get_jwt_secret(),
            algorithm=JWT_ALG,
        )
        client.cookies.set(COOKIE_NAME, token)
        assert client.get("/api/site/components").status_code == 401

    def test_token_signed_with_other_secret_rejected(self, client, monkeypatch):
        token = issue_token(_user())
        monkeypatch.setenv(ENV_JWT_SECRET, "a-different-secret-of-sufficient-length-YYYY")
        _reset_ephemeral_secret_for_tests()
        client.cookies.set(COOKIE_NAME, token)
        assert client.get("/api/site/components").status_code == 401

    def test_non_bearer_scheme_rejected(self, client):
        res = client.get(
            "/api/site/components",
            headers={"Authorization": "Basic dGVzdDp0ZXN0"},
        )
        assert res.status_code == 401

    def test_options_preflight_passes_through(self, client):
        # No CORS middleware in this fixture, so the router answers
        # 405 -- the point is the gate did not answer 401 first.
        assert client.options("/api/site/components").status_code == 405

    def test_websocket_refused_without_session(self, client):
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/hermes"):
            pass

    def test_websocket_accepted_with_cookie(self, client):
        client.cookies.set(COOKIE_NAME, issue_token(_user()))
        with client.websocket_connect("/api/hermes") as ws:
            assert ws.receive_json() == {"hello": True}


class TestSeedingPolicy:
    def test_ungated_seeds_five_repo_defaults(self):
        store = seed_demo_users()
        assert sorted(u.username for u in store.all_users()) == [
            "manager", "operator", "safety_a", "safety_b", "technician",
        ]

    def test_gated_without_overrides_seeds_nobody(self, monkeypatch):
        monkeypatch.setenv(ENV_REQUIRE_AUTH, "1")
        for name in ("OPERATOR", "TECHNICIAN", "SAFETY_A", "SAFETY_B", "MANAGER"):
            monkeypatch.delenv(ENV_PASSWORD_PREFIX + name, raising=False)
        assert seed_demo_users().all_users() == []

    def test_gated_seeds_only_overridden_users(self, monkeypatch):
        from backend.auth.jwt_handler import LoginError, login

        monkeypatch.setenv(ENV_REQUIRE_AUTH, "1")
        for name in ("OPERATOR", "TECHNICIAN", "SAFETY_A", "SAFETY_B"):
            monkeypatch.delenv(ENV_PASSWORD_PREFIX + name, raising=False)
        monkeypatch.setenv(ENV_PASSWORD_PREFIX + "MANAGER", "a-long-private-passphrase")
        store = seed_demo_users()
        assert [u.username for u in store.all_users()] == ["manager"]
        out = login(store, username="manager", password="a-long-private-passphrase")
        assert out["role"] == Role.FACILITY_MANAGER.value
        with pytest.raises(LoginError):
            login(store, username="manager", password="manager-demo")

    def test_override_applies_ungated_too(self, monkeypatch):
        from backend.auth.jwt_handler import LoginError, login

        monkeypatch.setenv(ENV_PASSWORD_PREFIX + "OPERATOR", "local-override-pass")
        store = seed_demo_users()
        assert len(store.all_users()) == 5
        login(store, username="operator", password="local-override-pass")
        with pytest.raises(LoginError):
            login(store, username="operator", password="operator-demo")


class TestMainAppLoginCookie:
    """Integration against the real app object (lifespan boot)."""

    def test_ungated_login_payload_is_unchanged(self):
        from backend.main import app

        with TestClient(app) as c:
            res = c.post(
                "/api/auth/login",
                json={"username": "manager", "password": "manager-demo"},
            )
            assert res.status_code == 200
            assert set(res.json()) == {
                "access_token", "token_type", "expires_in",
                "user_id", "username", "role",
            }
            assert COOKIE_NAME not in res.cookies
            # Gate off: API reachable with no session, as before.
            assert c.get("/api/site/components").status_code == 200

    def test_gated_login_sets_httponly_cookie_and_unlocks_api(self, monkeypatch):
        from backend.main import app

        monkeypatch.setenv(ENV_REQUIRE_AUTH, "1")
        monkeypatch.setenv(ENV_PASSWORD_PREFIX + "MANAGER", "a-long-private-passphrase")
        with TestClient(app) as c:
            assert c.get("/").status_code == 200
            assert c.get("/api/health").status_code == 200
            assert c.get("/api/site/components").status_code == 401
            assert c.get("/api/auth/whoami").status_code == 401

            bad = c.post(
                "/api/auth/login",
                json={"username": "manager", "password": "manager-demo"},
            )
            assert bad.status_code == 401

            res = c.post(
                "/api/auth/login",
                json={"username": "manager", "password": "a-long-private-passphrase"},
            )
            assert res.status_code == 200
            assert res.json()["session"] == "cookie"
            set_cookie = res.headers["set-cookie"]
            assert set_cookie.startswith(COOKIE_NAME + "=")
            lowered = set_cookie.lower()
            assert "httponly" in lowered
            assert "samesite=lax" in lowered
            assert "path=/" in lowered

            # The cookie alone (no Authorization header) now unlocks.
            assert c.get("/api/site/components").status_code == 200

    def test_gated_cookie_is_secure_behind_https_proxy(self, monkeypatch):
        from backend.main import app

        monkeypatch.setenv(ENV_REQUIRE_AUTH, "1")
        monkeypatch.setenv(ENV_PASSWORD_PREFIX + "OPERATOR", "another-private-passphrase")
        with TestClient(app) as c:
            res = c.post(
                "/api/auth/login",
                json={"username": "operator", "password": "another-private-passphrase"},
                headers={"X-Forwarded-Proto": "https"},
            )
            assert res.status_code == 200
            assert "secure" in res.headers["set-cookie"].lower()
