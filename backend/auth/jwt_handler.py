"""
backend/auth/jwt_handler.py
===========================
Epic 10 -- Stateless JWT issue/verify + PBKDF2 password hashing +
in-memory user store + login helper.

Secret management
-----------------
Reads ``DC_EPMS_JWT_SECRET`` (any non-empty string). When absent,
generates an ephemeral 32-byte secret at module import and emits a
loud WARNING -- the dev fallback is intentionally process-scoped so
that tokens DO NOT survive a backend restart. Production deployments
MUST set the env variable.

Password hashing
----------------
PBKDF2-HMAC-SHA256 with a per-user 16-byte random salt and 200_000
iterations. Both hash and salt are stored as lowercase hex strings.
The verification path uses ``hmac.compare_digest`` for constant-time
comparison. This is good enough for the educational MVP -- a
production identity backend (Argon2id, OIDC) is the right
permanent answer.

The in-memory user store is a demo MVP. Production deployments
swap it for a backing database via the same ``UserStore`` Protocol.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
import uuid
from typing import Protocol, runtime_checkable

import jwt

from backend.auth.models import Role, TokenClaims, User

log = logging.getLogger(__name__)


JWT_ALG = "HS256"
DEFAULT_TTL_SECONDS = 3600  # 1 hour access token
ENV_JWT_SECRET = "DC_EPMS_JWT_SECRET"

_PBKDF2_ITERS = 200_000
_PBKDF2_SALT_BYTES = 16


# ─── Secret management ────────────────────────────────────────────
_EPHEMERAL_SECRET: str | None = None


def _get_jwt_secret() -> str:
    """Return the configured JWT signing secret.

    Resolution order:
      1. DC_EPMS_JWT_SECRET environment variable (production path).
      2. Ephemeral 32-byte secret generated at first call, logged
         loudly. Tokens issued under this DO NOT survive restart.
    """
    raw = os.environ.get(ENV_JWT_SECRET)
    if raw:
        return raw
    global _EPHEMERAL_SECRET
    if _EPHEMERAL_SECRET is None:
        _EPHEMERAL_SECRET = secrets.token_hex(32)
        log.warning(
            "%s not set -- using ephemeral JWT secret. Tokens issued "
            "now will be invalid after backend restart. SET THE ENV "
            "VARIABLE IN PRODUCTION.",
            ENV_JWT_SECRET,
        )
    return _EPHEMERAL_SECRET


# Test-only hook: pytest can override the secret per-test.
def _reset_ephemeral_secret_for_tests() -> None:
    """Reset the lazily-initialised ephemeral secret. Tests use this
    to verify the ephemeral fallback path; production never calls it."""
    global _EPHEMERAL_SECRET
    _EPHEMERAL_SECRET = None


# ─── JWT issue + verify ───────────────────────────────────────────
class TokenError(Exception):
    """Raised on any token-verification failure. The HTTP layer
    catches this and maps to HTTP 401."""


def issue_token(user: User, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> str:
    """Issue a signed JWT for ``user``. Claims:

      sub      -- user_id
      username -- display name (informational)
      role     -- canonical Role.value
      iat/exp  -- unix timestamps
      jti      -- per-token uuid4 (for future revocation)
    """
    if ttl_seconds <= 0:
        raise ValueError(f"ttl_seconds must be positive, got {ttl_seconds}")
    now = int(time.time())
    claims = {
        "sub": user.user_id,
        "username": user.username,
        "role": user.role.value,
        "iat": now,
        "exp": now + ttl_seconds,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, _get_jwt_secret(), algorithm=JWT_ALG)


def verify_token(token: str) -> TokenClaims:
    """Decode + verify a signed JWT. Raises TokenError on any failure.

    Failures cover:
      * malformed token,
      * bad signature,
      * expired token,
      * missing claim,
      * role value not in the canonical enum.
    """
    if not token or not isinstance(token, str):
        raise TokenError("empty or non-string token")
    try:
        decoded = jwt.decode(
            token, _get_jwt_secret(), algorithms=[JWT_ALG],
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token expired") from exc
    except jwt.InvalidSignatureError as exc:
        raise TokenError("invalid signature") from exc
    except jwt.PyJWTError as exc:
        raise TokenError(f"invalid token: {exc}") from exc
    required = {"sub", "username", "role", "iat", "exp", "jti"}
    missing = required - set(decoded.keys())
    if missing:
        raise TokenError(f"missing claims: {sorted(missing)}")
    try:
        role = Role(decoded["role"])
    except ValueError as exc:
        raise TokenError(f"unknown role: {decoded['role']!r}") from exc
    return TokenClaims(
        sub=str(decoded["sub"]),
        username=str(decoded["username"]),
        role=role,
        iat=int(decoded["iat"]),
        exp=int(decoded["exp"]),
        jti=str(decoded["jti"]),
    )


# ─── Password hashing ─────────────────────────────────────────────
def hash_password(
    password: str, *, salt: bytes | None = None,
) -> tuple[str, str]:
    """Return ``(hash_hex, salt_hex)`` for the given password.

    A fresh 16-byte salt is generated when ``salt`` is None -- callers
    seeding fixtures may pass an explicit salt for determinism.
    """
    if not password:
        raise ValueError("password must be non-empty")
    if salt is None:
        salt = secrets.token_bytes(_PBKDF2_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERS,
    )
    return digest.hex(), salt.hex()


def verify_password(
    password: str, *, expected_hash_hex: str, salt_hex: str,
) -> bool:
    """Constant-time compare of ``password`` against the stored
    hash. Returns True on match, False otherwise."""
    if not password or not expected_hash_hex or not salt_hex:
        return False
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERS,
    )
    return hmac.compare_digest(digest.hex(), expected_hash_hex)


# ─── User store ───────────────────────────────────────────────────
@runtime_checkable
class UserStore(Protocol):
    """Storage seam for user records. Production implementations
    swap an asyncpg / OIDC backend behind the same shape."""

    def find_by_username(self, username: str) -> User | None: ...
    def find_by_user_id(self, user_id: str) -> User | None: ...
    def all_users(self) -> list[User]: ...


class InMemoryUserStore:
    """Dict-backed demo store. Not thread-safe across writers --
    seeded once at boot then read-only in steady state."""

    def __init__(self) -> None:
        self._by_username: dict[str, User] = {}
        self._by_user_id: dict[str, User] = {}

    def add(self, user: User) -> None:
        if user.username in self._by_username:
            raise ValueError(f"username already exists: {user.username!r}")
        if user.user_id in self._by_user_id:
            raise ValueError(f"user_id already exists: {user.user_id!r}")
        self._by_username[user.username] = user
        self._by_user_id[user.user_id] = user

    def find_by_username(self, username: str) -> User | None:
        return self._by_username.get(username)

    def find_by_user_id(self, user_id: str) -> User | None:
        return self._by_user_id.get(user_id)

    def all_users(self) -> list[User]:
        return list(self._by_username.values())


def seed_demo_users() -> InMemoryUserStore:
    """Seed one demo user per role. Passwords are intentionally
    weak educational-demo defaults; production must replace this
    seeding with a real provisioning flow.

    Returned store has 4 users:
        operator  / operator-demo   -> L1_OPERATOR
        technician / technician-demo -> L2_TECHNICIAN
        safety_a  / safety-demo     -> SAFETY_OFFICER
        safety_b  / safety-demo-b   -> SAFETY_OFFICER (second
                                         signer for Maker-Checker)
        manager   / manager-demo    -> FACILITY_MANAGER

    Two SAFETY_OFFICER seeds are needed so the Maker-Checker flow
    has distinct user_ids out of the box.
    """
    seeds: list[tuple[str, str, str, Role]] = [
        ("u-operator", "operator", "operator-demo", Role.L1_OPERATOR),
        ("u-technician", "technician", "technician-demo", Role.L2_TECHNICIAN),
        ("u-safety-a", "safety_a", "safety-demo", Role.SAFETY_OFFICER),
        ("u-safety-b", "safety_b", "safety-demo-b", Role.SAFETY_OFFICER),
        ("u-manager", "manager", "manager-demo", Role.FACILITY_MANAGER),
    ]
    store = InMemoryUserStore()
    for user_id, username, password, role in seeds:
        h, s = hash_password(password)
        store.add(User(
            user_id=user_id,
            username=username,
            password_hash=h,
            password_salt=s,
            role=role,
        ))
    return store


# ─── Login helper (framework-agnostic, for the /api/auth/login
#     endpoint and direct tests) ────────────────────────────────────
class LoginError(Exception):
    """Raised by ``login()`` on invalid credentials. The HTTP layer
    maps this to HTTP 401 with an opaque message (do NOT leak
    'user not found' vs 'wrong password' -- both branches collapse
    to the same response)."""


def login(
    store: UserStore, *, username: str, password: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict[str, str | int]:
    """Validate credentials, return an access-token payload.

    Returns a dict shaped for the JSON endpoint:
        {"access_token": str, "token_type": "bearer",
         "expires_in": int, "user_id": str, "username": str,
         "role": str}

    Raises LoginError on any auth failure -- the caller maps to 401.
    """
    if not username or not password:
        raise LoginError("empty username or password")
    user = store.find_by_username(username)
    if user is None:
        # Cost-equivalent path: still run a hash so timing does not
        # leak the existence of the username. We discard the result.
        hash_password(password)
        raise LoginError("invalid credentials")
    if not verify_password(
        password,
        expected_hash_hex=user.password_hash,
        salt_hex=user.password_salt,
    ):
        raise LoginError("invalid credentials")
    token = issue_token(user, ttl_seconds=ttl_seconds)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": ttl_seconds,
        "user_id": user.user_id,
        "username": user.username,
        "role": user.role.value,
    }
