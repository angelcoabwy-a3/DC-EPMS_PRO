"""
tests/test_auth_models.py
=========================
Epic 10 -- Role enum + User dataclass + role rank ordering.

Invariants:
  - Role enum has exactly the four canonical levels.
  - Role values are stable strings (round-trip in JWT claims).
  - ROLE_RANK is strictly monotone: L1_OPERATOR < L2_TECHNICIAN <
    SAFETY_OFFICER < FACILITY_MANAGER.
  - role_at_least() returns the expected gating decision.
"""

from __future__ import annotations

import pytest

from backend.auth.models import ROLE_RANK, Role, User, role_at_least


class TestRoleEnum:
    def test_exactly_four_roles(self) -> None:
        assert len(Role) == 4

    def test_role_values_are_canonical(self) -> None:
        assert Role.L1_OPERATOR.value == "L1_OPERATOR"
        assert Role.L2_TECHNICIAN.value == "L2_TECHNICIAN"
        assert Role.SAFETY_OFFICER.value == "SAFETY_OFFICER"
        assert Role.FACILITY_MANAGER.value == "FACILITY_MANAGER"

    def test_role_round_trip_via_value(self) -> None:
        for r in Role:
            assert Role(r.value) is r


class TestRoleRank:
    def test_rank_strictly_monotone(self) -> None:
        ranks = [
            ROLE_RANK[Role.L1_OPERATOR],
            ROLE_RANK[Role.L2_TECHNICIAN],
            ROLE_RANK[Role.SAFETY_OFFICER],
            ROLE_RANK[Role.FACILITY_MANAGER],
        ]
        assert ranks == sorted(ranks)
        assert len(set(ranks)) == 4  # distinct

    def test_every_role_has_a_rank(self) -> None:
        for r in Role:
            assert r in ROLE_RANK


class TestRoleAtLeast:
    def test_same_role_passes(self) -> None:
        assert role_at_least(Role.SAFETY_OFFICER, Role.SAFETY_OFFICER) is True

    def test_higher_role_passes(self) -> None:
        assert role_at_least(Role.FACILITY_MANAGER, Role.SAFETY_OFFICER) is True

    def test_lower_role_fails(self) -> None:
        assert role_at_least(Role.L1_OPERATOR, Role.SAFETY_OFFICER) is False

    def test_unknown_role_fails_safely(self) -> None:
        # Defensive: a malformed claim should NOT pass any gate.
        assert role_at_least(None, Role.L1_OPERATOR) is False  # type: ignore[arg-type]


class TestUser:
    def test_user_construction_and_immutability(self) -> None:
        u = User(
            user_id="u-1",
            username="alice",
            password_hash="deadbeef",
            password_salt="cafe",
            role=Role.SAFETY_OFFICER,
        )
        assert u.username == "alice"
        # Frozen dataclass: any attribute assignment raises FrozenInstanceError.
        with pytest.raises(
            __import__("dataclasses").FrozenInstanceError,
        ):
            u.username = "mallory"  # type: ignore[misc]

    def test_user_equality_is_structural(self) -> None:
        u1 = User("u-1", "a", "h", "s", Role.L1_OPERATOR)
        u2 = User("u-1", "a", "h", "s", Role.L1_OPERATOR)
        assert u1 == u2
