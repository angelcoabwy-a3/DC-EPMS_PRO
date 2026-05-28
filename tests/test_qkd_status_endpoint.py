"""
tests/test_qkd_status_endpoint.py
=================================
Epic 9 -- /api/qkd/status payload shape.

Tests :func:`backend.services.qkd_service.build_status_payload`,
the framework-agnostic helper that backs the FastAPI endpoint. We
test it here instead of going through TestClient because the
project's broader test environment has a known fastapi/starlette
version mismatch that breaks the FastAPI app's `on_startup` keyword
in this worktree; isolating to the helper keeps the assertions
focused on the payload contract.
"""

from __future__ import annotations

import pytest

from backend.services.qkd_service import (
    QKD_STATUS_AUDIT_LIMIT_MAX,
    QKDService,
    build_status_payload,
)


@pytest.fixture
def primed_svc() -> QKDService:
    svc = QKDService(
        base_seed=2026, n_photons=256, pool_capacity=8, eavesdrop=False,
    )
    svc.replenish(3)
    return svc


@pytest.fixture
def eve_svc() -> QKDService:
    svc = QKDService(
        base_seed=2026, n_photons=1024, pool_capacity=8,
        eavesdrop=True, seed_eve=7,
    )
    svc.replenish(2)
    return svc


class TestPayloadShape:
    def test_returns_framing_string(self, primed_svc: QKDService) -> None:
        out = build_status_payload(primed_svc, audit_limit=16)
        assert "framing" in out
        assert "Educational" in out["framing"]
        assert "Not a real quantum channel" in out["framing"]

    def test_returns_pool_stats(self, primed_svc: QKDService) -> None:
        out = build_status_payload(primed_svc, audit_limit=16)
        assert out["pool_depth"] == 3
        assert out["pool_capacity"] == 8
        assert out["keys_accepted_total"] == 3
        assert out["keys_rejected_total"] == 0
        assert out["last_qber"] == 0.0
        assert out["last_decision"] == "accepted"
        assert out["qber_threshold"] == pytest.approx(0.11)
        assert out["eavesdrop_simulated"] is False

    def test_returns_recent_audit_with_keys(
        self, primed_svc: QKDService,
    ) -> None:
        out = build_status_payload(primed_svc, audit_limit=8)
        assert len(out["recent_audit"]) == 3
        for r in out["recent_audit"]:
            assert {"ts", "decision", "qber", "threshold",
                    "fingerprint", "reason"} <= set(r.keys())
            assert isinstance(r["fingerprint"], str)
            assert len(r["fingerprint"]) == 16
            assert r["decision"] in ("accepted", "rejected")

    def test_eavesdrop_state_reflected(self, eve_svc: QKDService) -> None:
        out = build_status_payload(eve_svc, audit_limit=16)
        assert out["eavesdrop_simulated"] is True
        assert out["pool_depth"] == 0
        assert out["keys_rejected_total"] == 2
        assert out["last_decision"] == "rejected"
        for r in out["recent_audit"]:
            assert r["decision"] == "rejected"
            assert r["reason"] != ""


class TestGuards:
    def test_no_service_raises_value_error_with_svc_tag(self) -> None:
        with pytest.raises(ValueError, match="^svc:"):
            build_status_payload(None, audit_limit=16)

    def test_negative_limit_raises(
        self, primed_svc: QKDService,
    ) -> None:
        with pytest.raises(
            ValueError, match="audit_limit must be non-negative",
        ):
            build_status_payload(primed_svc, audit_limit=-1)

    def test_limit_clamped_to_max(self, primed_svc: QKDService) -> None:
        out = build_status_payload(primed_svc, audit_limit=9999)
        assert len(out["recent_audit"]) <= QKD_STATUS_AUDIT_LIMIT_MAX

    def test_zero_limit_returns_empty_audit(
        self, primed_svc: QKDService,
    ) -> None:
        out = build_status_payload(primed_svc, audit_limit=0)
        assert out["recent_audit"] == []
        # Stats still populated.
        assert out["pool_depth"] == 3
