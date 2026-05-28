"""
tests/test_epic9_acceptance.py
==============================
Epic 9 end-to-end acceptance: BB84 simulator -> QKD pool -> Forensic
Ledger entry -> HMI payload, exercised in a single process.

This is the e2e proof the user asked for in lieu of a live HTTP
smoke (the worktree's fastapi/starlette venv state prevents booting
the real app -- a pre-existing environment mismatch unrelated to
Epic 9).

The test demonstrates:
  1. A clean-channel QKDService primes a pool with admit_total>=N
     and QBER==0.
  2. A ForensicLedger configured with the pool stamps an
     Optimizer-style (proposal_id-carrying) entry with the consumed
     fingerprint; the chain verifies after multiple stamps.
  3. The HMI status payload reports the same accept totals and
     surfaces the stamped fingerprints in the audit window.
  4. Injecting an eavesdropper drains the pool: every batch rejects,
     downstream Optimizer entries fall back to key-less, the HMI
     payload's last_decision flips to "rejected" with last_qber at
     ~25% -- the BB84 signature visible to the operator.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.ledger.forensic_ledger import ForensicLedger, InMemoryPersistence
from backend.services.qkd_service import QKDService, build_status_payload


@pytest.fixture
def fresh_hmac_key() -> bytes:
    return b"\xa3" * 32


def test_clean_channel_full_chain(fresh_hmac_key: bytes) -> None:
    # 1) Prime the pool.
    pool = QKDService(
        base_seed=0xACCE9D, n_photons=512,
        pool_capacity=16, eavesdrop=False,
    )
    admitted, rejected = pool.replenish(8)
    assert admitted == 8
    assert rejected == 0
    assert pool.stats().pool_depth == 8
    assert pool.stats().last_qber == 0.0

    # 2) Wire into a ledger and stamp 3 Optimizer-style entries.
    ledger = ForensicLedger(
        InMemoryPersistence(),
        key=fresh_hmac_key,
        key_version=1,
        qkd_provider=pool,
    )

    async def _stamp_three() -> list[str]:
        fps: list[str] = []
        for i in range(3):
            entry = await ledger.append(
                actor="optimizer",
                action="BMS_WRITE_REQUESTED",
                payload={
                    "tag_id": f"ups_a.setpoint_{i}",
                    "proposal_id": f"p-clean-{i:03d}",
                    "source": "optimizer_approval",
                },
            )
            assert "qkd" in entry.payload
            fps.append(entry.payload["qkd"]["fingerprint"])
        await ledger.verify_chain()  # chain holds with QKD payload
        return fps

    stamped = asyncio.run(_stamp_three())
    # Pool drained by 3.
    assert pool.stats().pool_depth == 5
    # All three fingerprints distinct (pool advanced for each).
    assert len(set(stamped)) == 3

    # 3) HMI payload reflects the same totals + recent fingerprints.
    payload = build_status_payload(pool, audit_limit=16)
    assert payload["pool_depth"] == 5
    assert payload["keys_accepted_total"] == 8
    assert payload["keys_rejected_total"] == 0
    assert payload["last_decision"] == "accepted"
    assert payload["eavesdrop_simulated"] is False
    # The HMI sees the accept fingerprints (issued by the pool when
    # admitted; the ones consumed by the ledger are popped, but the
    # audit record persists).
    hmi_fingerprints = {r["fingerprint"] for r in payload["recent_audit"]}
    assert set(stamped).issubset(hmi_fingerprints), (
        f"stamped={stamped} hmi={hmi_fingerprints}"
    )


def test_eavesdrop_drill_drains_pool_and_ledger_falls_back(
    fresh_hmac_key: bytes,
) -> None:
    """The BB84 audit drill: operator flips the eavesdrop sim on.
    Every batch rejects, pool stays empty, Optimizer ledger entries
    fall back to key-less (chain still ticks), HMI flashes red."""
    pool = QKDService(
        base_seed=0xEEEEEE, n_photons=1024,
        pool_capacity=16, eavesdrop=True, seed_eve=42,
    )
    admitted, rejected = pool.replenish(4)
    assert admitted == 0
    assert rejected == 4

    ledger = ForensicLedger(
        InMemoryPersistence(),
        key=fresh_hmac_key,
        key_version=1,
        qkd_provider=pool,
    )

    async def _stamp_under_attack() -> bool:
        entry = await ledger.append(
            actor="optimizer",
            action="BMS_WRITE_REQUESTED",
            payload={
                "tag_id": "ups_a.setpoint",
                "proposal_id": "p-under-attack",
                "source": "optimizer_approval",
            },
        )
        await ledger.verify_chain()
        return "qkd" in entry.payload

    qkd_stamped = asyncio.run(_stamp_under_attack())
    # Pool empty -> ledger appends key-less, but chain ticks forward.
    assert qkd_stamped is False

    # HMI payload surfaces the eavesdrop signature.
    payload = build_status_payload(pool, audit_limit=16)
    assert payload["pool_depth"] == 0
    assert payload["keys_accepted_total"] == 0
    assert payload["keys_rejected_total"] == 4
    assert payload["last_decision"] == "rejected"
    assert payload["eavesdrop_simulated"] is True
    # QBER lives in the BB84-intercept-resend regime (~25%).
    assert payload["last_qber"] is not None
    assert payload["last_qber"] >= 0.11
    # Every audit record is a reject with the threshold-violation reason.
    assert len(payload["recent_audit"]) == 4
    for r in payload["recent_audit"]:
        assert r["decision"] == "rejected"
        assert ">= threshold" in r["reason"]


def test_chain_audit_trail_links_qkd_fingerprint_to_proposal(
    fresh_hmac_key: bytes,
) -> None:
    """Auditor's view: starting from a proposal_id, recover the QKD
    fingerprint that was consumed when the entry was signed.

    This is the closing invariant of S-PROPOSER-01 + Epic 9: an
    operator can answer "what QKD context signed proposal X?" from
    the ledger alone, without ever consulting the QKD pool's
    in-memory audit log."""
    pool = QKDService(
        base_seed=0xAB1234, n_photons=512,
        pool_capacity=8, eavesdrop=False,
    )
    pool.replenish(3)
    ledger = ForensicLedger(
        InMemoryPersistence(),
        key=fresh_hmac_key,
        key_version=1,
        qkd_provider=pool,
    )

    async def _stamp_and_recover() -> dict[str, str]:
        entry = await ledger.append(
            actor="optimizer",
            action="BMS_WRITE_REQUESTED",
            payload={
                "tag_id": "chiller_a.lwt_setpoint",
                "proposal_id": "p-audit-recovery-007",
            },
        )
        chain_entries = await ledger.fetch_by_proposal_id(
            "p-audit-recovery-007",
        )
        assert len(chain_entries) == 1
        recovered = chain_entries[0].payload["qkd"]
        return {
            "stamped_at_append": entry.payload["qkd"]["fingerprint"],
            "recovered_from_chain": recovered["fingerprint"],
        }

    out = asyncio.run(_stamp_and_recover())
    assert out["stamped_at_append"] == out["recovered_from_chain"]
