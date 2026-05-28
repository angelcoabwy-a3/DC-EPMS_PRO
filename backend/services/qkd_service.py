"""
backend/services/qkd_service.py
===============================
Epic 9 -- BB84 key pool service (deterministic simulator).

A long-lived process service that keeps an in-memory buffer of
educational BB84-simulated keys. The Forensic Ledger consults this
service when appending AI-originated entries (Optimizer-approved BMS
writes) and embeds the consumed key's fingerprint into the entry
payload, making QKD provenance HMAC-chained without coupling the
chain's verifiability to the simulator's bit-stream.

Framing reminder
----------------
This is a SIMULATOR. The bits a real QKD link would derive their
security from -- single-photon no-cloning -- are absent here. Keys
emitted by this service have the entropy of `random.Random`. The
educational value is the visible QBER signature when an eavesdropper
is injected and the resulting pool stall: that demonstrates the BB84
*protocol*, not BB84 *security*.

Concurrency
-----------
The pool, audit log, and stats counters are guarded by a `threading.
RLock`. The service is intentionally synchronous -- replenish is
fast (~0.5 ms per BB84 batch at 1024 photons), so we don't push it
to an executor. Callers may schedule periodic replenish via
`asyncio.create_task(periodic_replenish(svc, interval_s))`.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from backend.crypto import bb84_core

log = logging.getLogger(__name__)


# Defaults aimed at "visible QBER stats in a 60-second demo loop":
#   - 1024 photons -> ~512 sifted -> ~256 final bits per key.
#   - sample fraction 0.5 -> the publicly compared subset gives a stable
#     QBER estimate (variance of a 256-sample proportion @ p=0 is 0;
#     @ p=0.25 it's ~ sqrt(0.25*0.75/256) ~= 0.027).
DEFAULT_N_PHOTONS = 1024
DEFAULT_POOL_CAPACITY = 32
DEFAULT_QBER_THRESHOLD = bb84_core.DEFAULT_QBER_THRESHOLD
DEFAULT_AUDIT_LOG_CAP = 256


@dataclass(frozen=True)
class QKDKey:
    """One consumable QKD key.

    Carries fingerprint + metadata only. The raw bit-stream is
    discarded inside the service once the fingerprint is computed --
    the simulator does NOT keep keys at rest. (In a real QKD system
    this would be the line between "live key buffer" and "key
    destroyed after use"; here it's just defence-in-depth for the
    audit framing.)
    """

    fingerprint: str
    n_bits: int
    qber_at_issue: float
    generated_at: datetime


@dataclass(frozen=True)
class QKDAudit:
    """One audit-trail record from the BB84 pool.

    `decision` is `"accepted"` or `"rejected"`. `reason` is empty on
    accept; on reject it carries the QBER and threshold so the
    operator can diagnose intrusion vs. mis-calibration.
    """

    ts: datetime
    decision: str
    qber: float
    threshold: float
    fingerprint: str
    reason: str = ""


@dataclass
class QKDStats:
    pool_depth: int
    pool_capacity: int
    keys_accepted_total: int
    keys_rejected_total: int
    last_qber: float | None
    last_decision: str | None
    eavesdrop_simulated: bool
    qber_threshold: float
    audit_log_size: int


class QKDService:
    """In-memory BB84 key pool with an audit log.

    Construction is deterministic given (base_seed, n_photons,
    sample_fraction, qber_threshold, eavesdrop, seed_eve). Each
    `replenish()` advances a monotonic batch counter -- so a process
    restart on the same parameters reproduces the same key stream,
    which is what makes the H13 / S-CONTINUITY-01 replay story work.
    """

    def __init__(
        self,
        *,
        base_seed: int = 0xDCEB_910E,
        n_photons: int = DEFAULT_N_PHOTONS,
        sample_fraction: float = bb84_core.DEFAULT_SAMPLE_FRACTION,
        qber_threshold: float = DEFAULT_QBER_THRESHOLD,
        pool_capacity: int = DEFAULT_POOL_CAPACITY,
        audit_log_cap: int = DEFAULT_AUDIT_LOG_CAP,
        eavesdrop: bool = False,
        seed_eve: int = 0,
    ) -> None:
        if pool_capacity <= 0:
            raise ValueError(
                f"pool_capacity must be positive, got {pool_capacity}",
            )
        if audit_log_cap <= 0:
            raise ValueError(
                f"audit_log_cap must be positive, got {audit_log_cap}",
            )
        self._base_seed = base_seed
        self._n_photons = n_photons
        self._sample_fraction = sample_fraction
        self._qber_threshold = qber_threshold
        self._eavesdrop = eavesdrop
        self._seed_eve = seed_eve
        self._pool_capacity = pool_capacity

        self._lock = threading.RLock()
        self._batch_counter = 0
        self._pool: deque[QKDKey] = deque(maxlen=pool_capacity)
        self._audit: deque[QKDAudit] = deque(maxlen=audit_log_cap)
        self._accepted_total = 0
        self._rejected_total = 0
        self._last_qber: float | None = None
        self._last_decision: str | None = None

    # ── Properties for read-only inspection ──
    @property
    def qber_threshold(self) -> float:
        return self._qber_threshold

    @property
    def pool_capacity(self) -> int:
        return self._pool_capacity

    @property
    def eavesdrop_simulated(self) -> bool:
        return self._eavesdrop

    # ── Replenish + consume ──
    def replenish(self, n_keys: int = 1) -> tuple[int, int]:
        """Generate ``n_keys`` BB84 runs and admit the ones that pass
        the QBER threshold to the pool.

        Returns ``(admitted, rejected)`` for the caller (typically a
        periodic loop or a unit test).
        """
        if n_keys <= 0:
            raise ValueError(f"n_keys must be positive, got {n_keys}")
        admitted = 0
        rejected = 0
        with self._lock:
            for _ in range(n_keys):
                seed_alice = self._base_seed + 4 * self._batch_counter
                seed_bob = self._base_seed + 4 * self._batch_counter + 1
                seed_sample = self._base_seed + 4 * self._batch_counter + 2
                # seed_eve increments along with the batch when an
                # eavesdropper is simulated -- otherwise unused.
                seed_eve = (
                    self._seed_eve + self._batch_counter
                    if self._eavesdrop
                    else 0
                )
                self._batch_counter += 1

                result = bb84_core.run_bb84(
                    n_photons=self._n_photons,
                    seed_alice=seed_alice,
                    seed_bob=seed_bob,
                    seed_sample=seed_sample,
                    eavesdrop=self._eavesdrop,
                    seed_eve=seed_eve,
                    qber_threshold=self._qber_threshold,
                    sample_fraction=self._sample_fraction,
                )
                now = datetime.now(UTC)
                fp = bb84_core.key_fingerprint(result.final_key)
                self._last_qber = result.qber

                if result.aborted:
                    rejected += 1
                    self._rejected_total += 1
                    self._last_decision = "rejected"
                    reason = (
                        f"QBER {result.qber:.4f} >= threshold "
                        f"{self._qber_threshold:.4f}"
                    )
                    self._audit.append(
                        QKDAudit(
                            ts=now,
                            decision="rejected",
                            qber=result.qber,
                            threshold=self._qber_threshold,
                            fingerprint=fp,
                            reason=reason,
                        ),
                    )
                    log.warning(
                        "[qkd] batch rejected: %s (eavesdrop=%s)",
                        reason, self._eavesdrop,
                    )
                else:
                    admitted += 1
                    self._accepted_total += 1
                    self._last_decision = "accepted"
                    self._pool.append(
                        QKDKey(
                            fingerprint=fp,
                            n_bits=len(result.final_key),
                            qber_at_issue=result.qber,
                            generated_at=now,
                        ),
                    )
                    self._audit.append(
                        QKDAudit(
                            ts=now,
                            decision="accepted",
                            qber=result.qber,
                            threshold=self._qber_threshold,
                            fingerprint=fp,
                            reason="",
                        ),
                    )
        return admitted, rejected

    def consume_key(self) -> QKDKey | None:
        """Pop the oldest key from the pool. Returns None when empty.

        Callers MUST treat None as "no QKD context this round" --
        the Forensic Ledger falls back to a key-less entry.
        """
        with self._lock:
            if not self._pool:
                return None
            return self._pool.popleft()

    # ── Consumer protocol surface used by ForensicLedger ──
    def consume_for_ledger(self) -> dict[str, float | int | str] | None:
        """Ledger-facing consume call. Returns a JSON-safe dict
        suitable for embedding in a ledger entry payload, or None if
        the pool is empty.

        Returned shape:
          {"fingerprint": "<16-hex>", "n_bits": int,
           "qber_at_issue": float, "generated_at": "<iso8601>"}
        """
        key = self.consume_key()
        if key is None:
            return None
        return {
            "fingerprint": key.fingerprint,
            "n_bits": key.n_bits,
            "qber_at_issue": key.qber_at_issue,
            "generated_at": key.generated_at.isoformat(),
        }

    # ── Stats / audit log ──
    def stats(self) -> QKDStats:
        with self._lock:
            return QKDStats(
                pool_depth=len(self._pool),
                pool_capacity=self._pool_capacity,
                keys_accepted_total=self._accepted_total,
                keys_rejected_total=self._rejected_total,
                last_qber=self._last_qber,
                last_decision=self._last_decision,
                eavesdrop_simulated=self._eavesdrop,
                qber_threshold=self._qber_threshold,
                audit_log_size=len(self._audit),
            )

    def recent_audit(self, limit: int = 32) -> list[QKDAudit]:
        if limit <= 0:
            return []
        with self._lock:
            return list(self._audit)[-limit:]


def periodic_replenish_sync(
    svc: QKDService, *, target_depth: int, batch_size: int = 4,
) -> tuple[int, int]:
    """Top up the pool to ``target_depth`` using batches of
    ``batch_size``. Returns aggregate ``(admitted, rejected)``.

    Use in a background asyncio task:

        async def loop():
            while not shutdown.is_set():
                await asyncio.to_thread(
                    periodic_replenish_sync, svc, target_depth=16,
                )
                await asyncio.sleep(5.0)
    """
    if target_depth <= 0:
        raise ValueError(
            f"target_depth must be positive, got {target_depth}",
        )
    admitted_total = 0
    rejected_total = 0
    while svc.stats().pool_depth < target_depth:
        admitted, rejected = svc.replenish(batch_size)
        admitted_total += admitted
        rejected_total += rejected
        # If a batch returned zero accepts (e.g. eavesdrop saturated),
        # break to avoid an infinite loop. The caller's next interval
        # will retry.
        if admitted == 0:
            break
    return admitted_total, rejected_total


def fingerprints(keys: Iterable[QKDKey]) -> list[str]:
    """Test helper: extract fingerprints from a key iterable."""
    return [k.fingerprint for k in keys]


# Hard cap for the /api/qkd/status audit window. Keeps the response
# size bounded regardless of caller request.
QKD_STATUS_AUDIT_LIMIT_MAX = 64


def build_status_payload(
    svc: QKDService | None, *, audit_limit: int,
) -> dict[str, object]:
    """Pure helper for the /api/qkd/status FastAPI endpoint.

    Lives here (not in backend.main) so the endpoint shape can be
    unit-tested without going through the FastAPI app -- the
    surrounding suite's environment trips on a fastapi/starlette
    version mismatch unrelated to Epic 9.

    The HTTP layer in backend.main turns ``ValueError("svc")`` into
    HTTP 503 and ``ValueError("audit_limit")`` into HTTP 400; this
    function stays framework-agnostic.
    """
    if svc is None:
        raise ValueError(
            "svc: QKDService not initialised (educational simulator off)",
        )
    if audit_limit < 0:
        raise ValueError("audit_limit must be non-negative")
    capped = min(audit_limit, QKD_STATUS_AUDIT_LIMIT_MAX)
    stats = svc.stats()
    recent = svc.recent_audit(limit=capped)
    return {
        "framing": (
            "Educational BB84 simulator. Not a real quantum channel; "
            "keys have the entropy of random.Random. See "
            "backend/crypto/bb84_core.py for limitations."
        ),
        "pool_depth": stats.pool_depth,
        "pool_capacity": stats.pool_capacity,
        "keys_accepted_total": stats.keys_accepted_total,
        "keys_rejected_total": stats.keys_rejected_total,
        "last_qber": stats.last_qber,
        "last_decision": stats.last_decision,
        "qber_threshold": stats.qber_threshold,
        "eavesdrop_simulated": stats.eavesdrop_simulated,
        "audit_log_size": stats.audit_log_size,
        "recent_audit": [
            {
                "ts": r.ts.isoformat(),
                "decision": r.decision,
                "qber": r.qber,
                "threshold": r.threshold,
                "fingerprint": r.fingerprint,
                "reason": r.reason,
            }
            for r in recent
        ],
    }
