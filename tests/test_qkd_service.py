"""
tests/test_qkd_service.py
=========================
Epic 9 -- QKDService invariants.

Covers:
  - Clean-channel replenish admits keys to the pool, fingerprints
    are unique across batches, and stats reflect accepted total.
  - Eavesdropper-simulated service rejects every batch above the
    11% threshold, the audit log records each reject with a reason,
    and `consume_for_ledger()` returns None (pool stays empty).
  - FIFO consume order: oldest admitted key is returned first.
  - `consume_for_ledger()` returns a JSON-safe dict with the
    expected keys.
  - `periodic_replenish_sync()` tops up to target_depth and bails
    out cleanly when eavesdrop blocks all admits (no infinite loop).
  - Recent audit window is capped at the requested limit.
"""

from __future__ import annotations

import pytest

from backend.services.qkd_service import (
    QKDService,
    fingerprints,
    periodic_replenish_sync,
)


@pytest.fixture
def clean_svc() -> QKDService:
    """Clean-channel service: no eavesdropper. Every batch admits."""
    return QKDService(
        base_seed=12345,
        n_photons=512,
        pool_capacity=8,
        eavesdrop=False,
    )


@pytest.fixture
def eve_svc() -> QKDService:
    """Eavesdrop service: every batch rejects (QBER ~25%)."""
    return QKDService(
        base_seed=12345,
        n_photons=1024,  # enough samples for QBER to stabilise above 11%
        pool_capacity=8,
        eavesdrop=True,
        seed_eve=999,
    )


class TestReplenish:
    def test_clean_channel_admits_keys(self, clean_svc: QKDService) -> None:
        admitted, rejected = clean_svc.replenish(4)
        assert admitted == 4
        assert rejected == 0
        assert clean_svc.stats().pool_depth == 4

    def test_eavesdrop_rejects_all(self, eve_svc: QKDService) -> None:
        admitted, rejected = eve_svc.replenish(4)
        assert admitted == 0
        assert rejected == 4
        assert eve_svc.stats().pool_depth == 0
        assert eve_svc.stats().keys_rejected_total == 4

    def test_replenish_zero_or_negative_raises(
        self, clean_svc: QKDService,
    ) -> None:
        with pytest.raises(ValueError, match="n_keys must be positive"):
            clean_svc.replenish(0)
        with pytest.raises(ValueError, match="n_keys must be positive"):
            clean_svc.replenish(-1)

    def test_fingerprints_unique_across_batch(
        self, clean_svc: QKDService,
    ) -> None:
        # The deterministic seed sequence advances per-batch, so
        # successive runs MUST produce different keys.
        clean_svc.replenish(8)
        keys = [clean_svc.consume_key() for _ in range(8)]
        assert all(k is not None for k in keys)
        # Type-narrow for the linter -- already asserted above.
        fps = fingerprints([k for k in keys if k is not None])
        assert len(set(fps)) == 8, f"duplicate fingerprints: {fps}"


class TestConsume:
    def test_consume_empty_returns_none(self, clean_svc: QKDService) -> None:
        assert clean_svc.consume_key() is None
        assert clean_svc.consume_for_ledger() is None

    def test_fifo_order(self, clean_svc: QKDService) -> None:
        clean_svc.replenish(3)
        first = clean_svc.consume_key()
        second = clean_svc.consume_key()
        third = clean_svc.consume_key()
        assert first is not None
        assert second is not None
        assert third is not None
        # FIFO -- chronological generated_at.
        assert first.generated_at <= second.generated_at
        assert second.generated_at <= third.generated_at

    def test_consume_for_ledger_shape(self, clean_svc: QKDService) -> None:
        clean_svc.replenish(1)
        ledger_view = clean_svc.consume_for_ledger()
        assert ledger_view is not None
        assert set(ledger_view.keys()) == {
            "fingerprint", "n_bits", "qber_at_issue", "generated_at",
        }
        assert isinstance(ledger_view["fingerprint"], str)
        assert isinstance(ledger_view["n_bits"], int)
        assert isinstance(ledger_view["qber_at_issue"], float)
        assert isinstance(ledger_view["generated_at"], str)


class TestAuditLog:
    def test_rejects_record_reason(self, eve_svc: QKDService) -> None:
        eve_svc.replenish(2)
        audit = eve_svc.recent_audit(limit=8)
        assert len(audit) == 2
        for record in audit:
            assert record.decision == "rejected"
            assert "QBER" in record.reason
            assert ">= threshold" in record.reason

    def test_accepts_have_empty_reason(self, clean_svc: QKDService) -> None:
        clean_svc.replenish(2)
        audit = clean_svc.recent_audit(limit=8)
        assert len(audit) == 2
        for record in audit:
            assert record.decision == "accepted"
            assert record.reason == ""

    def test_recent_audit_respects_limit(
        self, clean_svc: QKDService,
    ) -> None:
        clean_svc.replenish(6)
        assert len(clean_svc.recent_audit(limit=3)) == 3
        assert len(clean_svc.recent_audit(limit=0)) == 0

    def test_audit_log_capped(self) -> None:
        svc = QKDService(
            base_seed=1, n_photons=256, audit_log_cap=4, pool_capacity=8,
        )
        svc.replenish(10)
        audit = svc.recent_audit(limit=100)
        # Cap honoured -- deque(maxlen=4).
        assert len(audit) == 4


class TestStats:
    def test_stats_reflect_replenish(self, clean_svc: QKDService) -> None:
        s0 = clean_svc.stats()
        assert s0.pool_depth == 0
        assert s0.keys_accepted_total == 0
        assert s0.last_qber is None

        clean_svc.replenish(3)
        s1 = clean_svc.stats()
        assert s1.pool_depth == 3
        assert s1.keys_accepted_total == 3
        assert s1.last_qber == 0.0
        assert s1.last_decision == "accepted"
        assert s1.eavesdrop_simulated is False

    def test_stats_for_eavesdropper(self, eve_svc: QKDService) -> None:
        eve_svc.replenish(2)
        s = eve_svc.stats()
        assert s.pool_depth == 0
        assert s.keys_rejected_total == 2
        assert s.last_decision == "rejected"
        assert s.eavesdrop_simulated is True
        assert s.last_qber is not None
        assert s.last_qber >= 0.11


class TestPeriodicReplenish:
    def test_tops_up_to_target(self, clean_svc: QKDService) -> None:
        admitted, rejected = periodic_replenish_sync(
            clean_svc, target_depth=5, batch_size=2,
        )
        assert clean_svc.stats().pool_depth >= 5
        assert admitted >= 5
        assert rejected == 0

    def test_bails_out_on_persistent_rejection(
        self, eve_svc: QKDService,
    ) -> None:
        # Pool can never reach target -- but the helper must NOT spin
        # forever: when a batch admits zero, it returns.
        admitted, rejected = periodic_replenish_sync(
            eve_svc, target_depth=10, batch_size=3,
        )
        assert admitted == 0
        assert rejected == 3  # exactly one batch tried, then bail.
        assert eve_svc.stats().pool_depth == 0

    def test_target_depth_zero_raises(self, clean_svc: QKDService) -> None:
        with pytest.raises(
            ValueError, match="target_depth must be positive",
        ):
            periodic_replenish_sync(
                clean_svc, target_depth=0, batch_size=2,
            )


class TestConstruction:
    def test_invalid_pool_capacity_raises(self) -> None:
        with pytest.raises(ValueError, match="pool_capacity must be positive"):
            QKDService(pool_capacity=0)

    def test_invalid_audit_log_cap_raises(self) -> None:
        with pytest.raises(ValueError, match="audit_log_cap must be positive"):
            QKDService(audit_log_cap=0)

    def test_pool_capped_at_capacity(self) -> None:
        svc = QKDService(base_seed=42, n_photons=256, pool_capacity=3)
        svc.replenish(5)
        # deque(maxlen=3) drops oldest beyond cap.
        assert svc.stats().pool_depth == 3
