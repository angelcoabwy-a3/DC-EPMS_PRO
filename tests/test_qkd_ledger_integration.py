"""
tests/test_qkd_ledger_integration.py
====================================
Epic 9 -- QKD <-> Forensic Ledger integration invariants.

Covers:
  - Ledger without a qkd_provider behaves exactly as before
    (S-LEDGER-01 backward compatibility).
  - Ledger with a qkd_provider but a payload WITHOUT proposal_id
    does NOT consume from the pool (key-less entry, pool depth
    unchanged).
  - Ledger with a qkd_provider AND proposal_id consumes one key;
    the entry payload carries a "qkd" sub-object; the chain still
    verifies; pool depth decreases by 1 per consume.
  - Pool-empty fallback: ledger appends a key-less entry without
    raising; verify_chain still passes.
  - Provider that raises does NOT propagate into ledger; entry is
    appended key-less.
  - HMAC integrity: the qkd fingerprint is INSIDE the HMAC body
    (mutating the persisted payload AFTER write breaks the chain).
"""

from __future__ import annotations

import asyncio

import pytest

from backend.ledger.forensic_ledger import (
    ForensicLedger,
    InMemoryPersistence,
    LedgerChainBrokenError,
)
from backend.services.qkd_service import QKDService


@pytest.fixture
def fresh_key() -> bytes:
    # 32-byte HMAC key for the ledger -- distinct from the QKD bits.
    return b"\xab" * 32


@pytest.fixture
def clean_pool() -> QKDService:
    svc = QKDService(
        base_seed=7777, n_photons=512, pool_capacity=16, eavesdrop=False,
    )
    svc.replenish(8)
    return svc


@pytest.fixture
def empty_pool() -> QKDService:
    # Constructed but never replenished -- depth=0.
    return QKDService(
        base_seed=8888, n_photons=512, pool_capacity=16, eavesdrop=False,
    )


class TestBackwardCompatibility:
    def test_ledger_without_provider_unchanged(
        self, fresh_key: bytes,
    ) -> None:
        ledger = ForensicLedger(
            InMemoryPersistence(), key=fresh_key, key_version=1,
        )
        assert ledger.qkd_provider is None
        entry = asyncio.run(
            ledger.append(
                actor="operator",
                action="BMS_WRITE_REQUESTED",
                payload={"tag_id": "cdu_a.flow", "proposal_id": "p-001"},
            ),
        )
        # No QKD = no qkd field.
        assert "qkd" not in entry.payload

    def test_ledger_with_provider_no_proposal_id_does_not_consume(
        self, fresh_key: bytes, clean_pool: QKDService,
    ) -> None:
        depth_before = clean_pool.stats().pool_depth
        ledger = ForensicLedger(
            InMemoryPersistence(),
            key=fresh_key,
            key_version=1,
            qkd_provider=clean_pool,
        )
        entry = asyncio.run(
            ledger.append(
                actor="operator",
                action="BMS_WRITE_REQUESTED",
                payload={"tag_id": "cdu_a.flow"},
            ),
        )
        depth_after = clean_pool.stats().pool_depth
        # No proposal_id -> human-direct write -> no QKD consume.
        assert depth_before == depth_after
        assert "qkd" not in entry.payload


class TestQKDStamping:
    def test_proposal_id_present_consumes_key(
        self, fresh_key: bytes, clean_pool: QKDService,
    ) -> None:
        depth_before = clean_pool.stats().pool_depth
        ledger = ForensicLedger(
            InMemoryPersistence(),
            key=fresh_key,
            key_version=1,
            qkd_provider=clean_pool,
        )
        entry = asyncio.run(
            ledger.append(
                actor="optimizer",
                action="BMS_WRITE_REQUESTED",
                payload={"tag_id": "ups_a.setpoint", "proposal_id": "p-042"},
            ),
        )
        depth_after = clean_pool.stats().pool_depth
        assert depth_after == depth_before - 1
        # Payload now carries the QKD sub-record.
        assert "qkd" in entry.payload
        qkd = entry.payload["qkd"]
        assert isinstance(qkd, dict)
        assert {"fingerprint", "n_bits", "qber_at_issue", "generated_at"} <= (
            set(qkd.keys())
        )
        assert isinstance(qkd["fingerprint"], str)
        assert len(qkd["fingerprint"]) == 16

    def test_chain_still_verifies_with_qkd_entries(
        self, fresh_key: bytes, clean_pool: QKDService,
    ) -> None:
        ledger = ForensicLedger(
            InMemoryPersistence(),
            key=fresh_key,
            key_version=1,
            qkd_provider=clean_pool,
        )

        async def _run() -> None:
            for i in range(3):
                await ledger.append(
                    actor="optimizer",
                    action="BMS_WRITE_REQUESTED",
                    payload={
                        "tag_id": f"tag_{i}", "proposal_id": f"p-{i:03d}",
                    },
                )
            # Mix of qkd + key-less entries:
            await ledger.append(
                actor="operator",
                action="BMS_WRITE_REQUESTED",
                payload={"tag_id": "tag_x"},
            )
            await ledger.verify_chain()  # raises on tamper

        asyncio.run(_run())

    def test_distinct_proposals_get_distinct_fingerprints(
        self, fresh_key: bytes, clean_pool: QKDService,
    ) -> None:
        ledger = ForensicLedger(
            InMemoryPersistence(),
            key=fresh_key,
            key_version=1,
            qkd_provider=clean_pool,
        )

        async def _run() -> tuple[str, str]:
            e1 = await ledger.append(
                actor="optimizer",
                action="BMS_WRITE_REQUESTED",
                payload={"tag_id": "a", "proposal_id": "p-1"},
            )
            e2 = await ledger.append(
                actor="optimizer",
                action="BMS_WRITE_REQUESTED",
                payload={"tag_id": "b", "proposal_id": "p-2"},
            )
            return (
                e1.payload["qkd"]["fingerprint"],
                e2.payload["qkd"]["fingerprint"],
            )

        fp1, fp2 = asyncio.run(_run())
        assert fp1 != fp2


class TestFallback:
    def test_empty_pool_appends_keyless(
        self, fresh_key: bytes, empty_pool: QKDService,
    ) -> None:
        ledger = ForensicLedger(
            InMemoryPersistence(),
            key=fresh_key,
            key_version=1,
            qkd_provider=empty_pool,
        )
        entry = asyncio.run(
            ledger.append(
                actor="optimizer",
                action="BMS_WRITE_REQUESTED",
                payload={"tag_id": "x", "proposal_id": "p-999"},
            ),
        )
        # Pool empty -> no qkd field; chain ticks forward.
        assert "qkd" not in entry.payload
        asyncio.run(ledger.verify_chain())

    def test_provider_raising_falls_back_keyless(
        self, fresh_key: bytes,
    ) -> None:
        class BrokenProvider:
            def consume_for_ledger(self) -> None:
                raise RuntimeError("simulated provider failure")

        ledger = ForensicLedger(
            InMemoryPersistence(),
            key=fresh_key,
            key_version=1,
            qkd_provider=BrokenProvider(),
        )
        entry = asyncio.run(
            ledger.append(
                actor="optimizer",
                action="BMS_WRITE_REQUESTED",
                payload={"tag_id": "y", "proposal_id": "p-321"},
            ),
        )
        assert "qkd" not in entry.payload
        asyncio.run(ledger.verify_chain())


class TestHMACCoverage:
    def test_tampering_qkd_field_breaks_chain(
        self, fresh_key: bytes, clean_pool: QKDService,
    ) -> None:
        """The QKD fingerprint goes through the HMAC body -- editing
        the persisted payload after the fact MUST be detected by
        ``verify_chain()``. This is the key invariant that makes
        QKD provenance tamper-evident."""
        persistence = InMemoryPersistence()
        ledger = ForensicLedger(
            persistence,
            key=fresh_key,
            key_version=1,
            qkd_provider=clean_pool,
        )
        original = asyncio.run(
            ledger.append(
                actor="optimizer",
                action="BMS_WRITE_REQUESTED",
                payload={"tag_id": "tap", "proposal_id": "p-tamper"},
            ),
        )
        # Simulate an attacker re-writing the fingerprint -- via the
        # test-only tamper hook (production code cannot mutate
        # entries; the DB triggers + the in-memory append-only
        # discipline enforce this).
        tampered_payload = dict(original.payload)
        tampered_payload["qkd"] = dict(tampered_payload["qkd"])
        tampered_payload["qkd"]["fingerprint"] = "deadbeefdeadbeef"
        tampered = type(original)(
            entry_id=original.entry_id,
            sequence_no=original.sequence_no,
            ts=original.ts,
            actor=original.actor,
            action=original.action,
            payload=tampered_payload,
            prev_hash=original.prev_hash,
            entry_hmac=original.entry_hmac,
            key_version=original.key_version,
        )
        persistence._force_replace_for_tamper_test(0, tampered)
        with pytest.raises(LedgerChainBrokenError) as excinfo:
            asyncio.run(ledger.verify_chain())
        assert excinfo.value.divergence_index == 0
        assert "HMAC mismatch" in excinfo.value.reason
