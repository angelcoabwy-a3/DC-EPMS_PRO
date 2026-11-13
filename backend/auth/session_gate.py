"""
backend/auth/session_gate.py
============================
Public-deployment session gate (release R1, 2026-11).

Problem this closes
-------------------
Epic 10 gated the HMI with a login view, but only four frontend
modules send ``Authorization: Bearer`` (core/api_client.js). The
other ~70 ``fetch`` calls, the telemetry ``EventSource`` and the
Hermes ``WebSocket`` send no header, so on a public URL every API
route stayed reachable with plain ``curl`` -- the login was cosmetic.

Design
------
A pure ASGI middleware (covers ``http`` AND ``websocket`` scopes --
``@app.middleware("http")`` would miss Hermes). It is OFF unless
``DC_EPMS_REQUIRE_AUTH`` is truthy, so local development and the
existing test floors are unchanged.

When ON, a request passes if it carries a valid JWT in either:
  * ``Authorization: Bearer <jwt>`` (existing Epic 10 clients), or
  * the httpOnly cookie ``dc_epms_session`` set by
    ``POST /api/auth/login`` (reaches EventSource / WebSocket /
    plain fetch, which cannot attach headers).

Always public (allow-list, exact or prefix):
  * ``/`` , ``/favicon.ico`` , ``/assets/*``  -- the static SPA shell
  * ``/api/health``                           -- platform healthcheck
  * ``/api/auth/login``                       -- to obtain a session
  * ``/api/copilot/mop/*``                    -- the Meta-hackathon MOP
    Verification demo (``?demo=1``), which runs without a login and
    carries its own per-visitor + global rate limits (README Limits).

Fail-closed: if the gate is ON and token verification cannot run
(e.g. PyJWT missing), requests are rejected with 503, never passed.

The gate authenticates only. Role checks (S-SEC-02) stay on the
individual write endpoints via ``require_role`` -- unchanged.
"""

from __future__ import annotations

import json
import os
from http.cookies import SimpleCookie
from typing import Any

__all__ = [
    "COOKIE_NAME",
    "ENV_REQUIRE_AUTH",
    "SessionGateMiddleware",
    "gate_enabled",
    "is_public_path",
]

ENV_REQUIRE_AUTH = "DC_EPMS_REQUIRE_AUTH"
COOKIE_NAME = "dc_epms_session"

_TRUTHY = frozenset({"1", "true", "yes", "on"})

_PUBLIC_EXACT = frozenset(
    {
        "/",
        "/favicon.ico",
        "/api/health",
        "/api/auth/login",
    }
)
_PUBLIC_PREFIXES = (
    "/assets/",
    "/api/copilot/mop/",
)

_BEARER_PREFIX = "bearer "


def gate_enabled() -> bool:
    """True when the deployment demands a session on every API call.

    Read on every request (one dict lookup) so tests and operators
    can flip it without rebuilding the app object.
    """
    return os.environ.get(ENV_REQUIRE_AUTH, "").strip().lower() in _TRUTHY


def is_public_path(path: str) -> bool:
    """Allow-list check. Anything not listed here needs a session."""
    if path in _PUBLIC_EXACT:
        return True
    return any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES)


def _extract_token(scope: dict[str, Any]) -> str | None:
    """Pull a JWT from the Authorization header, else the cookie."""
    cookie_header = ""
    for raw_name, raw_value in scope.get("headers") or ():
        name = raw_name.decode("latin-1").lower()
        if name == "authorization":
            value = raw_value.decode("latin-1").strip()
            if value.lower().startswith(_BEARER_PREFIX):
                token = value[len(_BEARER_PREFIX):].strip()
                if token:
                    return token
        elif name == "cookie":
            cookie_header = raw_value.decode("latin-1")
    if not cookie_header:
        return None
    try:
        jar: SimpleCookie = SimpleCookie()
        jar.load(cookie_header)
    except Exception:
        return None
    morsel = jar.get(COOKIE_NAME)
    if morsel is None or not morsel.value:
        return None
    return morsel.value


async def _reject_http(send: Any, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode("utf-8")
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", b"no-store"),
    ]
    if status == 401:
        headers.append((b"www-authenticate", b"Bearer"))
    await send(
        {"type": "http.response.start", "status": status, "headers": headers}
    )
    await send({"type": "http.response.body", "body": body})


class SessionGateMiddleware:
    """ASGI middleware: authenticate every non-public request."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        scope_type = scope.get("type")
        if scope_type not in ("http", "websocket") or not gate_enabled():
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        if is_public_path(path):
            await self.app(scope, receive, send)
            return
        # CORS pre-flight carries no credentials by specification.
        if scope_type == "http" and scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        status, detail = 401, "authentication required"
        token = _extract_token(scope)
        if token:
            try:
                from backend.auth.jwt_handler import TokenError, verify_token
            except Exception:
                status, detail = 503, "authentication backend unavailable"
            else:
                try:
                    verify_token(token)
                except TokenError:
                    detail = "invalid or expired session"
                else:
                    await self.app(scope, receive, send)
                    return

        if scope_type == "websocket":
            # Closing before accept makes the server answer the
            # handshake with HTTP 403; 4401 documents the reason.
            await send({"type": "websocket.close", "code": 4401})
            return
        await _reject_http(send, status, detail)
