"""
backend/rbac.py — claim-based RBAC gate (E2E audit finding F3-4).

There is NO authentication layer in this platform (no login / token /
session — see the E2E Security Audit). `actor_role` is a client-supplied
*claim*, carried alongside `cet_id`, NOT a verified identity. This module
is the shared authorization gate the ~12 mutating endpoints route through,
extending the structural pattern of `b34efb1` (F3-1/2/3).

Policy — ENFORCE-WHEN-PRESENT:
  * A request that *carries* an `actor_role` claim has it enforced: a role
    ranking below the action's minimum is rejected with HTTP 403.
  * A request that *omits* the claim falls through ungated — consistent
    with the `cmms_models` "None -> gate not enforced" convention, and so
    the gate can be added without rewriting every pre-existing test.

  Fail-closed deny-by-default (reject the missing claim too) is the
  stricter posture — it requires the frontend to send `actor_role` on
  every mutating call and every test fixture updated. Tracked as a
  follow-up; this module makes the gate ACTIVE first.
"""

from __future__ import annotations

from fastapi import HTTPException

from backend.cmms_models import UserRole, role_rank

# Convenience rank constants for call sites.
RANK_TECH_L4 = role_rank(UserRole.TECH_L4)            # 4
RANK_SENIOR_L5 = role_rank(UserRole.SENIOR_TECH_L5)   # 5
RANK_SME_L6 = role_rank(UserRole.SME_L6)              # 6


def require_actor_role(
    actor_role: str | None,
    min_rank: int,
    action: str = "this operation",
) -> None:
    """Enforce-when-present RBAC gate.

    Raises HTTP 403 if `actor_role` is supplied AND ranks below `min_rank`.
    A missing / empty claim is not enforced (see module policy).

    Args:
        actor_role: the client-supplied role claim (or None / "").
        min_rank:   minimum acceptable rank (4 = TECH_L4, 5 = SENIOR, 6 = SME).
        action:     human-readable action name for the 403 detail.
    """
    if not actor_role:
        return                              # no claim -> enforce-when-present skips
    if role_rank(actor_role) < min_rank:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Forbidden: {action} requires role rank >= {min_rank}; "
                f"actor_role={actor_role!r} is insufficient (RBAC F3-4)."
            ),
        )
