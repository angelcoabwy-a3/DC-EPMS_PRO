"""
witness_engine.py — Multi-signature witness workflow.

Sprint 3 of Opción B. Adds the missing piece for IEC 62443 SR 6.1
strict compliance: when a procedure step has `requires_witness=true`,
the procedure_engine blocks execution and creates a WitnessRequest.
A SECOND operator (different identity from the initiator) must sign
before the step proceeds.

The pattern:

    Operator A initiates procedure
        → procedure_engine reaches step_03_arm_ats (requires_witness=true)
        → procedure_engine PAUSES execution
        → witness_engine creates WitnessRequest, status=PENDING
        → HMI surfaces it in the witness panel
        → Operator B opens HMI, reviews step, clicks "Sign as witness"
        → witness_engine validates: identity != Operator A
        → witness signature recorded
        → procedure_engine resumes, executes the step
        → audit log captures both identities for the step

═══════════════════════════════════════════════════════════════════════
  IEC 62443 SR 6.1 — Separation of Duties

  "The control system shall provide the capability to enforce
  separation of duties at the user/role level for sensitive
  control functions, such that the user/role that initiates a
  control action cannot be the same as the user/role that
  authorizes that control action."

  This module is what makes our procedures compliant. Without it,
  Sprint 1+2 + v8.x are necessary but not sufficient for SR 6.1.
═══════════════════════════════════════════════════════════════════════

  HONEST scope notes:

  - Witness requests are in-memory (DraftStore-style). Production
    would persist to PostgreSQL with WORM table for audit forensics.
    The interface doesn't change; only the storage backend does.

  - Identity is validated by string equality of operator user_id.
    Production would integrate with the org's IDP (Azure AD, Okta)
    and verify role claims (e.g., must hold "WitnessQualified" role).
    This module's contract is "given two distinct authenticated
    user_ids, enforce separation"; identity authentication is upstream.

  - A "qualified witness" (someone authorized to sign as witness for
    DMOP/EOP procedures) is, in this Sprint, anyone whose user_id is
    different from the initiator. Sprint 5+ adds role-based qualification.
═══════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
#  Witness request lifecycle
# ─────────────────────────────────────────────────────────────────────────
class WitnessStatus(str, Enum):
    PENDING = "PENDING"  # awaiting witness signature
    SIGNED = "SIGNED"  # witness signed, step can proceed
    REJECTED = "REJECTED"  # witness explicitly rejected
    EXPIRED = "EXPIRED"  # TTL elapsed
    SUPERSEDED = "SUPERSEDED"  # procedure aborted, request voided


# Default TTL — 15 minutes. Long enough for a witness to walk to the
# HMI from anywhere in a Tier IV facility, short enough that stale
# signatures cannot be exploited.
DEFAULT_WITNESS_TTL_S = 15 * 60


# ─────────────────────────────────────────────────────────────────────────
#  Data model
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class WitnessRequest:
    """One pending witness request. Tied to a specific step in a
    specific procedure execution. Unique by (execution_id, step_id)."""

    request_id: str
    execution_id: str  # the procedure execution that is paused
    procedure_id: str
    step_id: str
    step_title: str
    step_payload: dict  # the step dict from the YAML — for HMI display
    initiator: str  # operator who started the procedure
    created_at_unix: float
    expires_at_unix: float

    status: WitnessStatus = WitnessStatus.PENDING
    witness: str | None = None
    signed_at_unix: float | None = None
    rejection_reason: str | None = None

    # Optional context the HMI shows to the witness so they understand
    # what they're signing — current site state, expected state delta,
    # safety standards in scope.
    context: dict = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        return self.status == WitnessStatus.PENDING and time.time() > self.expires_at_unix


class WitnessError(RuntimeError):
    """Base class for witness-related errors."""


class IdentityCollisionError(WitnessError):
    """Witness identity == initiator identity. Forbidden by IEC 62443 SR 6.1."""


class WitnessRequestNotFoundError(KeyError):
    """No witness request matches the given request_id."""


class WitnessRequestNotPendingError(WitnessError):
    """Tried to sign/reject a request that is not in PENDING state."""


# ─────────────────────────────────────────────────────────────────────────
#  WitnessStore — in-memory registry with TTL
# ─────────────────────────────────────────────────────────────────────────
class WitnessStore:
    """In-memory store for witness requests. One process-singleton in
    production via dependency injection. Sprint 3+: replace with Postgres."""

    def __init__(self):
        self._requests: dict[str, WitnessRequest] = {}

    # ── CRUD ──────────────────────────────────────────────────────────
    def create(
        self,
        execution_id: str,
        procedure_id: str,
        step_id: str,
        step_title: str,
        step_payload: dict,
        initiator: str,
        ttl_s: int = DEFAULT_WITNESS_TTL_S,
        context: dict | None = None,
    ) -> WitnessRequest:
        """Create a pending witness request. Returns the WitnessRequest."""
        now = time.time()
        req = WitnessRequest(
            request_id=uuid.uuid4().hex,
            execution_id=execution_id,
            procedure_id=procedure_id,
            step_id=step_id,
            step_title=step_title,
            step_payload=step_payload,
            initiator=initiator,
            created_at_unix=now,
            expires_at_unix=now + ttl_s,
            context=context or {},
        )
        self._requests[req.request_id] = req
        log.info(
            "[witness] created request %s for %s/%s by %s (expires %.0fs)",
            req.request_id[:8],
            execution_id[:8],
            step_id,
            initiator,
            ttl_s,
        )
        return req

    def get(self, request_id: str) -> WitnessRequest:
        if request_id not in self._requests:
            raise WitnessRequestNotFoundError(request_id)
        # Lazily mark expired requests
        req = self._requests[request_id]
        if req.is_expired:
            req.status = WitnessStatus.EXPIRED
        return req

    def list_pending(self) -> list[WitnessRequest]:
        """Return all PENDING requests, garbage-collecting expired ones."""
        result = []
        for req in list(self._requests.values()):
            if req.is_expired:
                req.status = WitnessStatus.EXPIRED
            if req.status == WitnessStatus.PENDING:
                result.append(req)
        return result

    def list_for_execution(self, execution_id: str) -> list[WitnessRequest]:
        return [r for r in self._requests.values() if r.execution_id == execution_id]

    # ── Signing / Rejecting ────────────────────────────────────────────
    def sign(self, request_id: str, witness: str) -> WitnessRequest:
        """A witness signs the request. Enforces identity separation."""
        req = self.get(request_id)

        if req.status != WitnessStatus.PENDING:
            raise WitnessRequestNotPendingError(
                f"request {request_id[:8]} is in state {req.status.value}, not PENDING"
            )

        if witness == req.initiator:
            raise IdentityCollisionError(
                f"witness identity '{witness}' is the same as the initiator. "
                f"IEC 62443 SR 6.1 (separation of duties) requires distinct identities."
            )

        if not witness or not witness.strip():
            raise IdentityCollisionError("witness identity must be non-empty")

        req.witness = witness
        req.signed_at_unix = time.time()
        req.status = WitnessStatus.SIGNED
        log.info(
            "[witness] %s SIGNED by %s (initiator was %s)",
            req.request_id[:8],
            witness,
            req.initiator,
        )
        return req

    def reject(self, request_id: str, witness: str, reason: str) -> WitnessRequest:
        """A witness explicitly rejects the request."""
        req = self.get(request_id)

        if req.status != WitnessStatus.PENDING:
            raise WitnessRequestNotPendingError(
                f"request {request_id[:8]} is in state {req.status.value}, not PENDING"
            )

        if witness == req.initiator:
            raise IdentityCollisionError(
                f"witness identity '{witness}' is the same as the initiator"
            )

        req.witness = witness
        req.signed_at_unix = time.time()
        req.status = WitnessStatus.REJECTED
        req.rejection_reason = reason
        log.warning(
            "[witness] %s REJECTED by %s: %s",
            req.request_id[:8],
            witness,
            reason,
        )
        return req

    def supersede_for_execution(self, execution_id: str) -> int:
        """Mark all PENDING requests for this execution as SUPERSEDED.
        Called when a procedure is aborted while waiting on a witness."""
        count = 0
        for req in self._requests.values():
            if req.execution_id == execution_id and req.status == WitnessStatus.PENDING:
                req.status = WitnessStatus.SUPERSEDED
                count += 1
        if count:
            log.info(
                "[witness] superseded %d pending request(s) for execution %s",
                count,
                execution_id[:8],
            )
        return count


# Module-level singleton — same pattern as DraftStore in agent_copilot.py
_global_store = WitnessStore()


def get_witness_store() -> WitnessStore:
    """Accessor for the singleton store. Tests can monkeypatch this
    to inject a fresh store per-test."""
    return _global_store


# ─────────────────────────────────────────────────────────────────────────
#  WitnessGate — the integration point for procedure_engine
# ─────────────────────────────────────────────────────────────────────────
class WitnessGate:
    """Inserted between procedure_engine and StepExecutor. When a step
    requires a witness, the gate creates a WitnessRequest and waits
    (with timeout) for the signature before allowing the step to run.

    Production usage: procedure_engine instantiates WitnessGate once,
    wraps the StepExecutor in it. WitnessGate.await_witness() blocks
    until either signed or timeout."""

    def __init__(
        self,
        store: WitnessStore,
        poll_interval_s: float = 1.0,
        timeout_s: float = DEFAULT_WITNESS_TTL_S,
    ):
        self.store = store
        self.poll_interval_s = poll_interval_s
        self.timeout_s = timeout_s

    async def await_witness(
        self,
        execution_id: str,
        procedure_id: str,
        step: dict,
        initiator: str,
        context: dict | None = None,
    ) -> WitnessRequest:
        """Create a WitnessRequest and poll until signed/rejected/expired.

        Returns the final WitnessRequest. Caller inspects status:
          - SIGNED:   step can proceed
          - REJECTED: caller should abort the procedure
          - EXPIRED:  caller should abort the procedure

        Polling is async so the event loop is not blocked; HTTP
        endpoints can serve other requests during the wait.
        """
        req = self.store.create(
            execution_id=execution_id,
            procedure_id=procedure_id,
            step_id=step.get("id", "unknown"),
            step_title=step.get("title", "(no title)"),
            step_payload=step,
            initiator=initiator,
            ttl_s=int(self.timeout_s),
            context=context,
        )

        deadline = time.time() + self.timeout_s
        while time.time() < deadline:
            current = self.store.get(req.request_id)
            if current.status != WitnessStatus.PENDING:
                return current
            await asyncio.sleep(self.poll_interval_s)

        # Timed out — return the now-expired request
        final = self.store.get(req.request_id)  # triggers lazy expiry
        return final


# ─────────────────────────────────────────────────────────────────────────
#  Serialization helpers (for HTTP endpoints)
# ─────────────────────────────────────────────────────────────────────────
def serialize_request(req: WitnessRequest) -> dict:
    """Convert WitnessRequest to JSON-safe dict for HTTP responses.
    Strips heavy fields not needed by HMI."""
    d = asdict(req)
    # Replace enum with its string value
    d["status"] = req.status.value
    return d
