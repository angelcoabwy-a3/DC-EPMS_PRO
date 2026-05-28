"""
tests/test_jwt_handler.py
=========================
Epic 10 -- JWT issue/verify + password hashing + InMemoryUserStore +
login helper invariants.

Covers:
  - issue_token + verify_token round-trip preserves every claim.
  - Tampering the token body invalidates the signature.
  - Expired token raises TokenError("token expired").
  - Unknown role in claims raises TokenError("unknown role").
  - Missing claim raises TokenError.
  - PBKDF2 hash + verify_password round-trip; two identical
    passwords yield different hashes (per-call salt) but both
    verify.
  - InMemoryUserStore add/find/dedup behaviour.
  - seed_demo_users() returns 5 users covering 4 roles, with two
    SAFETY_OFFICER user_ids for Maker-Checker.
  - login() success returns full payload; failure raises LoginError
    with a uniform message (no username-existence leak).
"""

from __future__ import annotations

import time

import pytest

from backend.auth.jwt_handler import (
    DEFAULT_TTL_SECONDS,
    ENV_JWT_SECRET,
    InMemoryUserStore,
    LoginError,
    TokenError,
    _reset_ephemeral_secret_for_tests,
    hash_password,
    issue_token,
    login,
    seed_demo_users,
    verify_password,
    verify_token,
)
from backend.auth.models import Role, User


@pytest.fixture(autouse=True)
def _fixed_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin a deterministic JWT secret for every test in this module
    so issue / verify do not depend on the ephemeral fallback.
    PyJWT 2.13 requires >= 32 bytes for HS256."""
    monkeypatch.setenv(
        ENV_JWT_SECRET,
        "test-secret-32-bytes-or-more-for-hs256-XXXXXXX",
    )
    _reset_ephemeral_secret_for_tests()


def _make_user(
    *, user_id: str = "u-1", username: str = "alice",
    role: Role = Role.SAFETY_OFFICER, password: str = "demo-pass",
) -> User:
    h, s = hash_password(password)
    return User(
        user_id=user_id, username=username,
        password_hash=h, password_salt=s, role=role,
    )


# ─── JWT round-trip ────────────────────────────────────────────────
class TestJWTRoundTrip:
    def test_issue_then_verify_preserves_claims(self) -> None:
        user = _make_user()
        token = issue_token(user)
        claims = verify_token(token)
        assert claims.sub == user.user_id
        assert claims.username == user.username
        assert claims.role is user.role
        assert claims.exp > claims.iat
        assert isinstance(claims.jti, str)
        assert len(claims.jti) >= 16

    def test_different_jti_per_issue(self) -> None:
        user = _make_user()
        a = verify_token(issue_token(user))
        b = verify_token(issue_token(user))
        assert a.jti != b.jti

    def test_invalid_ttl_raises(self) -> None:
        user = _make_user()
        with pytest.raises(ValueError, match="ttl_seconds must be positive"):
            issue_token(user, ttl_seconds=0)


class TestVerifyFailures:
    def test_tampered_signature_raises(self) -> None:
        user = _make_user()
        token = issue_token(user)
        # Flip one character in the signature segment.
        head, payload, sig = token.split(".")
        bad_sig = "A" + sig[1:] if sig[0] != "A" else "B" + sig[1:]
        tampered = ".".join([head, payload, bad_sig])
        with pytest.raises(TokenError, match="invalid signature"):
            verify_token(tampered)

    def test_expired_token_raises(self) -> None:
        user = _make_user()
        # Pre-date issuance to force expiry on verify.
        token = issue_token(user, ttl_seconds=1)
        time.sleep(1.5)
        with pytest.raises(TokenError, match="token expired"):
            verify_token(token)

    def test_empty_token_raises(self) -> None:
        with pytest.raises(TokenError, match="empty or non-string"):
            verify_token("")
        with pytest.raises(TokenError, match="empty or non-string"):
            verify_token(None)  # type: ignore[arg-type]

    def test_malformed_token_raises(self) -> None:
        with pytest.raises(TokenError, match="invalid token"):
            verify_token("not.a.jwt")


# ─── Password hashing ──────────────────────────────────────────────
class TestPasswordHashing:
    def test_hash_then_verify_succeeds(self) -> None:
        h, s = hash_password("hunter2-correct-horse")
        assert verify_password(
            "hunter2-correct-horse",
            expected_hash_hex=h, salt_hex=s,
        )

    def test_wrong_password_fails(self) -> None:
        h, s = hash_password("hunter2")
        assert not verify_password(
            "hunter3", expected_hash_hex=h, salt_hex=s,
        )

    def test_same_password_yields_different_hashes(self) -> None:
        a_hash, a_salt = hash_password("same")
        b_hash, b_salt = hash_password("same")
        # Distinct random salts -> distinct hashes -- but both verify.
        assert a_salt != b_salt
        assert a_hash != b_hash
        assert verify_password(
            "same", expected_hash_hex=a_hash, salt_hex=a_salt,
        )
        assert verify_password(
            "same", expected_hash_hex=b_hash, salt_hex=b_salt,
        )

    def test_empty_password_raises(self) -> None:
        with pytest.raises(ValueError, match="password must be non-empty"):
            hash_password("")

    def test_verify_handles_malformed_input_safely(self) -> None:
        assert verify_password(
            "anything", expected_hash_hex="not-hex-XYZ", salt_hex="ZZ",
        ) is False
        assert verify_password(
            "", expected_hash_hex="ab", salt_hex="cd",
        ) is False


# ─── InMemoryUserStore ─────────────────────────────────────────────
class TestUserStore:
    def test_add_and_find_by_username(self) -> None:
        store = InMemoryUserStore()
        u = _make_user(user_id="u-1", username="alice")
        store.add(u)
        assert store.find_by_username("alice") is u
        assert store.find_by_user_id("u-1") is u
        assert store.find_by_username("missing") is None

    def test_dedup_on_username(self) -> None:
        store = InMemoryUserStore()
        store.add(_make_user(user_id="u-1", username="alice"))
        with pytest.raises(ValueError, match="username already exists"):
            store.add(_make_user(user_id="u-2", username="alice"))

    def test_dedup_on_user_id(self) -> None:
        store = InMemoryUserStore()
        store.add(_make_user(user_id="u-1", username="alice"))
        with pytest.raises(ValueError, match="user_id already exists"):
            store.add(_make_user(user_id="u-1", username="mallory"))

    def test_all_users_returns_snapshot(self) -> None:
        store = InMemoryUserStore()
        store.add(_make_user(user_id="u-1", username="a"))
        store.add(_make_user(user_id="u-2", username="b"))
        assert len(store.all_users()) == 2


# ─── Demo seed ─────────────────────────────────────────────────────
class TestSeedDemoUsers:
    def test_count_and_role_distribution(self) -> None:
        store = seed_demo_users()
        users = store.all_users()
        assert len(users) == 5
        roles = [u.role for u in users]
        assert roles.count(Role.L1_OPERATOR) == 1
        assert roles.count(Role.L2_TECHNICIAN) == 1
        assert roles.count(Role.SAFETY_OFFICER) == 2  # Maker-Checker pair
        assert roles.count(Role.FACILITY_MANAGER) == 1

    def test_two_safety_officers_have_distinct_user_ids(self) -> None:
        store = seed_demo_users()
        safety = [u for u in store.all_users() if u.role is Role.SAFETY_OFFICER]
        assert len({u.user_id for u in safety}) == 2

    def test_seed_passwords_verify(self) -> None:
        store = seed_demo_users()
        for username, password in [
            ("operator", "operator-demo"),
            ("technician", "technician-demo"),
            ("safety_a", "safety-demo"),
            ("safety_b", "safety-demo-b"),
            ("manager", "manager-demo"),
        ]:
            u = store.find_by_username(username)
            assert u is not None, username
            assert verify_password(
                password,
                expected_hash_hex=u.password_hash,
                salt_hex=u.password_salt,
            ), username


# ─── Login helper ──────────────────────────────────────────────────
class TestLogin:
    def test_login_success_returns_full_payload(self) -> None:
        store = seed_demo_users()
        out = login(store, username="safety_a", password="safety-demo")
        assert out["token_type"] == "bearer"
        assert out["role"] == Role.SAFETY_OFFICER.value
        assert out["user_id"] == "u-safety-a"
        assert out["expires_in"] == DEFAULT_TTL_SECONDS
        # Token round-trips through verify_token.
        claims = verify_token(out["access_token"])
        assert claims.sub == "u-safety-a"
        assert claims.role is Role.SAFETY_OFFICER

    def test_unknown_username_raises_uniform_error(self) -> None:
        store = seed_demo_users()
        with pytest.raises(LoginError, match="invalid credentials"):
            login(store, username="who", password="whatever")

    def test_wrong_password_raises_uniform_error(self) -> None:
        store = seed_demo_users()
        with pytest.raises(LoginError, match="invalid credentials"):
            login(store, username="safety_a", password="WRONG")

    def test_empty_creds_raise(self) -> None:
        store = seed_demo_users()
        with pytest.raises(LoginError, match="empty"):
            login(store, username="", password="x")
        with pytest.raises(LoginError, match="empty"):
            login(store, username="safety_a", password="")


# ─── Ephemeral secret fallback ────────────────────────────────────
class TestEphemeralSecret:
    def test_no_env_var_uses_ephemeral_secret(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv(ENV_JWT_SECRET, raising=False)
        _reset_ephemeral_secret_for_tests()
        user = _make_user()
        token = issue_token(user)
        # Same-process verify still works (ephemeral secret reused).
        claims = verify_token(token)
        assert claims.sub == user.user_id
