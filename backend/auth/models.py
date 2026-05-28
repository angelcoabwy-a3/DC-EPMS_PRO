"""
backend/auth/models.py
======================
Epic 10 -- IAM role enum + User dataclass + rank gating helper.

The four roles encode the Tier-IV maker-checker model:

    L1_OPERATOR       -- read-only HMI; no write actions.
    L2_TECHNICIAN     -- generate procedure drafts; cannot sign.
    SAFETY_OFFICER    -- sign procedures (maker OR checker).
                         Two SAFETY_OFFICER signatures with distinct
                         user_ids are required to apply a MOP.
    FACILITY_MANAGER  -- everything SAFETY_OFFICER can do, plus
                         user management + ledger key rotation.

ROLE_RANK is the canonical ordering. Endpoint guards compare via
``role_at_least(claim.role, required)`` rather than enum equality so
adding a new mid-rank role later does not break gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    """Canonical IAM roles. String enum so JWT claim round-trips
    serialise to a stable wire form (no integer brittleness)."""

    L1_OPERATOR = "L1_OPERATOR"
    L2_TECHNICIAN = "L2_TECHNICIAN"
    SAFETY_OFFICER = "SAFETY_OFFICER"
    FACILITY_MANAGER = "FACILITY_MANAGER"


# Strictly monotone rank. Higher value = more authority.
ROLE_RANK: dict[Role, int] = {
    Role.L1_OPERATOR: 1,
    Role.L2_TECHNICIAN: 2,
    Role.SAFETY_OFFICER: 3,
    Role.FACILITY_MANAGER: 4,
}


def role_at_least(actual: Role | None, required: Role) -> bool:
    """Return True iff ``actual`` is at least as privileged as
    ``required``.

    Defensive: ``actual=None`` (malformed claim, missing role) fails
    every gate. Better to refuse than to fall through.
    """
    if not isinstance(actual, Role):
        return False
    return ROLE_RANK[actual] >= ROLE_RANK[required]


@dataclass(frozen=True)
class User:
    """One authenticated identity.

    ``password_hash`` is the hex-encoded PBKDF2-SHA256 digest of
    the password salted with ``password_salt`` (also hex). The
    in-memory demo store keeps these next to the user record;
    a production store keeps them in a backing database.
    """

    user_id: str
    username: str
    password_hash: str
    password_salt: str
    role: Role


@dataclass(frozen=True)
class TokenClaims:
    """Decoded JWT claims. The endpoint dependencies return one of
    these so consumers can inspect ``role`` + ``sub`` (user_id)
    without re-decoding the token."""

    sub: str
    username: str
    role: Role
    iat: int
    exp: int
    jti: str
