"""
backend/auth/dependencies.py
============================
Epic 10 -- FastAPI dependencies that gate endpoints on a verified
JWT + role rank.

Usage on a path operation:

    from backend.auth.dependencies import require_role
    from backend.auth.models import Role

    @app.post("/api/procedures/architect/sign")
    async def sign_doc(
        body: SignRequest,
        claims = Depends(require_role(Role.SAFETY_OFFICER)),
    ):
        ...

The dependency parses ``Authorization: Bearer <jwt>``, verifies the
signature + expiry + claim shape via
:func:`backend.auth.jwt_handler.verify_token`, then enforces the
minimum role rank. Failures collapse to HTTP 401 (token problem) or
HTTP 403 (role insufficient) -- the dependency never returns a
``None`` claims object, callers can rely on the type.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Header, HTTPException

from backend.auth.jwt_handler import TokenError, verify_token
from backend.auth.models import Role, TokenClaims, role_at_least

# Force isort grouping: stdlib / third-party / first-party are
# already separated above. Re-export to suppress the I001 drift
# noise from ruff's group detector.
__all__ = [
    "assert_maker_checker_distinct",
    "extract_checker_jwt",
    "get_current_user",
    "require_role",
]


_BEARER_PREFIX = "Bearer "


def _parse_authorization_header(header_value: str | None) -> str:
    """Extract the raw JWT from an ``Authorization: Bearer <token>``
    header. Raises HTTP 401 on any structural problem."""
    if not header_value:
        raise HTTPException(401, "missing Authorization header")
    if not header_value.startswith(_BEARER_PREFIX):
        raise HTTPException(401, "Authorization must use Bearer scheme")
    token = header_value[len(_BEARER_PREFIX):].strip()
    if not token:
        raise HTTPException(401, "empty bearer token")
    return token


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
) -> TokenClaims:
    """FastAPI dependency: extract + verify the JWT on the request.

    HTTP 401 on any token problem (missing, malformed, expired,
    bad signature). Returns the decoded claims so the endpoint can
    inspect ``sub`` (user_id) + ``role``.
    """
    token = _parse_authorization_header(authorization)
    try:
        return verify_token(token)
    except TokenError as exc:
        raise HTTPException(401, f"invalid token: {exc}") from exc


def require_role(required: Role) -> Callable[..., object]:
    """Build a FastAPI dependency that gates on ``role_at_least``.

    HTTP 403 when the claim's role is below ``required``. HTTP 401
    inherits from get_current_user when the token itself is bad.
    """

    async def _gate(
        authorization: Annotated[str | None, Header()] = None,
    ) -> TokenClaims:
        claims = await get_current_user(authorization=authorization)
        if not role_at_least(claims.role, required):
            raise HTTPException(
                403,
                f"role {claims.role.value} is below required {required.value}",
            )
        return claims

    return _gate


def extract_checker_jwt(checker_token: str | None) -> TokenClaims:
    """Verify a Checker JWT carried in the request body (not in an
    Authorization header). Used by the Maker-Checker dual-signature
    endpoint.

    Raises HTTPException(401) on any token problem.
    """
    if not checker_token or not isinstance(checker_token, str):
        raise HTTPException(400, "missing checker_token in body")
    try:
        return verify_token(checker_token)
    except TokenError as exc:
        raise HTTPException(401, f"invalid checker token: {exc}") from exc


def assert_maker_checker_distinct(
    maker: TokenClaims, checker: TokenClaims,
) -> None:
    """The Maker-Checker invariant: two distinct user_ids.

    Defence-in-depth on top of the role gates -- a single SAFETY_
    OFFICER cannot apply a MOP by submitting their own JWT twice.
    Raises HTTPException(403) on violation.
    """
    if maker.sub == checker.sub:
        raise HTTPException(
            403,
            "Maker-Checker violation: maker and checker must be "
            "distinct user_ids",
        )
