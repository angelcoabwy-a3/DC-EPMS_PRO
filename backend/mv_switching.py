"""
backend/mv_switching.py
=======================
Release R3-B -- Medium-voltage switching safety: interlock engine and
forced switching procedures for a generator bay.

A bay is the set of devices between one generator and the 13.8 kV
generator bus:

    generator --- CB (52-G) --- DS (disconnector) --- bus
                     |
                    ES (earthing switch, generator side)

This module is PURE: no clock, no I/O, no web framework. The device
controller owns the bays and supplies the context (is the engine
running, was absence of voltage verified, would the path keep enough
generation). That keeps every rule testable in isolation.

Interlock rules (fail-safe: an unknown position or a missing fact
blocks the operation). They follow the classic "five preventions" of
MV switchgear; the operator's executive summary cites IEC 62271 for
them, which was NOT re-read for this work:

  R1  never close the CB with the earthing switch closed
  R2  never close the earthing switch with the CB or the DS closed
  R3  never close the earthing switch without a fresh verification of
      absence of voltage
  R4  never operate the disconnector unless the CB is open
  R5  never close the CB with the disconnector open
  R6  never close the CB unless the generator is at rated voltage and
      frequency (synchronising permissive)
  R7  never operate a device under LOTO
  R8  never close the disconnector with the earthing switch closed
  R9  never apply LOTO unless the bay is isolated and earthed
  R10 never take a bay out if the path would be left short of
      generation

HONEST SCOPE: this is a supervisory model for training and procedure
rehearsal. It does not replace mechanical or hardwired interlocks,
key-exchange systems, a voltage detector in the technician's hands or
a permit to work. Incident energy (arc flash) is NOT calculated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

OPEN = "OPEN"
CLOSED = "CLOSED"

# Bay operations
OP_OPEN_CB = "OPEN_CB"
OP_CLOSE_CB = "CLOSE_CB"
OP_OPEN_DS = "OPEN_DS"
OP_CLOSE_DS = "CLOSE_DS"
OP_VERIFY_ABSENCE = "VERIFY_ABSENCE_OF_VOLTAGE"
OP_CLOSE_ES = "CLOSE_ES"
OP_OPEN_ES = "OPEN_ES"
OP_APPLY_LOTO = "APPLY_LOTO"
OP_REMOVE_LOTO = "REMOVE_LOTO"

BAY_OPERATIONS = (
    OP_OPEN_CB, OP_CLOSE_CB, OP_OPEN_DS, OP_CLOSE_DS, OP_VERIFY_ABSENCE,
    OP_CLOSE_ES, OP_OPEN_ES, OP_APPLY_LOTO, OP_REMOVE_LOTO,
)

OP_LABELS = {
    OP_OPEN_CB: "Open circuit breaker 52-G",
    OP_CLOSE_CB: "Close circuit breaker 52-G",
    OP_OPEN_DS: "Open disconnector",
    OP_CLOSE_DS: "Close disconnector",
    OP_VERIFY_ABSENCE: "Verify absence of voltage",
    OP_CLOSE_ES: "Close earthing switch",
    OP_OPEN_ES: "Open earthing switch",
    OP_APPLY_LOTO: "Apply lockout / tagout",
    OP_REMOVE_LOTO: "Remove lockout / tagout",
}

# How long a verification of absence of voltage stays valid.
ABSENCE_VALID_S = 120.0
# How long a second-person approval stays valid.
WITNESS_VALID_S = 120.0

GOAL_ISOLATE = "ISOLATE_FOR_MAINTENANCE"
GOAL_RESTORE = "RETURN_TO_SERVICE"
GOALS = (GOAL_ISOLATE, GOAL_RESTORE)

GOAL_LABELS = {
    GOAL_ISOLATE: "Isolate for maintenance",
    GOAL_RESTORE: "Return to service",
}

# Step = (operation, safety_gate, two_person)
Step = tuple[str, bool, bool]

_ISOLATE_PLAN: tuple[Step, ...] = (
    (OP_OPEN_CB, False, False),
    (OP_OPEN_DS, False, False),
    (OP_VERIFY_ABSENCE, True, False),
    (OP_CLOSE_ES, True, True),
    (OP_APPLY_LOTO, True, True),
)


def plan(goal: str, bay: Bay) -> tuple[Step, ...]:
    """Ordered steps for ``goal`` from the bay's CURRENT positions, so
    a bay left half-way by an aborted procedure can always be brought
    back: the restore plan contains only the steps still needed."""
    if goal == GOAL_ISOLATE:
        return _ISOLATE_PLAN
    if goal == GOAL_RESTORE:
        steps: list[Step] = []
        if bay.loto:
            steps.append((OP_REMOVE_LOTO, True, True))
        if bay.es == CLOSED:
            steps.append((OP_OPEN_ES, True, False))
        if bay.ds == OPEN:
            steps.append((OP_CLOSE_DS, False, False))
        return tuple(steps)
    raise ValueError(f"unknown goal {goal!r}")


@dataclass
class Bay:
    """Positions of one generator bay. In service by default: DS
    closed, ES open, CB open (the CB follows the engine)."""

    bay_id: str
    cb: str = OPEN
    ds: str = CLOSED
    es: str = OPEN
    loto: bool = False
    absence_verified_at: float | None = None

    @property
    def in_service(self) -> bool:
        return self.ds == CLOSED and self.es == OPEN and not self.loto

    @property
    def isolated_and_earthed(self) -> bool:
        return self.cb == OPEN and self.ds == OPEN and self.es == CLOSED

    def indications(self) -> list[dict[str, str]]:
        return [
            {"label": "52-G breaker", "value": self.cb},
            {"label": "Disconnector", "value": self.ds},
            {"label": "Earthing switch", "value": self.es},
            {"label": "LOTO", "value": "APPLIED" if self.loto else "CLEAR"},
        ]


@dataclass(frozen=True)
class BayContext:
    """Facts the interlock engine needs and cannot derive from the
    bay. Every field defaults to the BLOCKING value (fail-safe)."""

    now: float = 0.0
    engine_stopped: bool = False
    engine_at_rated: bool = False
    voltage_present: bool = True
    path_keeps_capacity: bool = False


def interlock(bay: Bay, operation: str, ctx: BayContext) -> str | None:
    """Reason the operation is blocked, or None when every interlock
    permits it. Unknown operations and positions are blocked."""
    if operation not in BAY_OPERATIONS:
        return f"Unknown bay operation {operation!r}."
    if bay.cb not in (OPEN, CLOSED) or bay.ds not in (OPEN, CLOSED) or bay.es not in (OPEN, CLOSED):
        return "Bay position unknown: operation blocked (fail-safe)."
    if bay.loto and operation != OP_REMOVE_LOTO:
        return "R7: bay is under LOTO. Remove the lockout first."

    if operation == OP_OPEN_CB:
        return None  # opening a breaker is always permitted
    if operation == OP_CLOSE_CB:
        if bay.es == CLOSED:
            return "R1: earthing switch is closed. Closing the breaker would energise an earthed circuit."
        if bay.ds == OPEN:
            return "R5: disconnector is open. The bay is not in the service position."
        if not ctx.engine_at_rated:
            return "R6: generator is not at rated voltage and frequency (synchronising permissive)."
        return None
    if operation == OP_OPEN_DS:
        if bay.cb == CLOSED:
            return "R4: breaker is closed. A disconnector must never break load current."
        if not ctx.engine_stopped:
            return "R4: engine is not stopped. Stop the generator before isolating the bay."
        if not ctx.path_keeps_capacity:
            return "R10: the path would be left short of generation with this bay out."
        return None
    if operation == OP_CLOSE_DS:
        if bay.cb == CLOSED:
            return "R4: breaker is closed. A disconnector must never make load current."
        if bay.es == CLOSED:
            return "R8: earthing switch is closed. Closing the disconnector would earth the bus."
        return None
    if operation == OP_VERIFY_ABSENCE:
        if bay.cb == CLOSED or bay.ds == CLOSED:
            return "Bay is not isolated: open the breaker and the disconnector first."
        if ctx.voltage_present:
            return "Voltage PRESENT on the generator side. Do not proceed."
        return None
    if operation == OP_CLOSE_ES:
        if bay.cb == CLOSED or bay.ds == CLOSED:
            return "R2: breaker or disconnector is closed. Earthing a connected circuit is a short circuit."
        if ctx.voltage_present:
            return "R3: voltage present on the generator side."
        if bay.absence_verified_at is None or ctx.now - bay.absence_verified_at > ABSENCE_VALID_S:
            return (
                "R3: no fresh verification of absence of voltage "
                f"(valid for {ABSENCE_VALID_S:.0f} s)."
            )
        return None
    if operation == OP_OPEN_ES:
        return None if bay.es == CLOSED else "Earthing switch is already open."
    if operation == OP_APPLY_LOTO:
        if not bay.isolated_and_earthed:
            return "R9: bay is not isolated and earthed."
        return None
    # OP_REMOVE_LOTO
    return None if bay.loto else "No LOTO is applied on this bay."


def apply(bay: Bay, operation: str, now: float) -> None:
    """Mutate the bay. Call only after ``interlock`` returned None."""
    if operation == OP_OPEN_CB:
        bay.cb = OPEN
    elif operation == OP_CLOSE_CB:
        bay.cb = CLOSED
    elif operation == OP_OPEN_DS:
        bay.ds = OPEN
    elif operation == OP_CLOSE_DS:
        bay.ds = CLOSED
    elif operation == OP_VERIFY_ABSENCE:
        bay.absence_verified_at = now
    elif operation == OP_CLOSE_ES:
        bay.es = CLOSED
    elif operation == OP_OPEN_ES:
        bay.es = OPEN
        bay.absence_verified_at = None
    elif operation == OP_APPLY_LOTO:
        bay.loto = True
    elif operation == OP_REMOVE_LOTO:
        bay.loto = False


@dataclass
class Procedure:
    """One switching procedure in progress on one bay. Only the next
    step can run; there is no way to skip or reorder."""

    procedure_id: str
    bay_id: str
    goal: str
    operator: str
    started_at: float
    steps: tuple[Step, ...] = ()
    next_index: int = 0
    # step index -> (witness username, time of approval)
    witnesses: dict[int, tuple[str, float]] = field(default_factory=dict)
    blocked_attempts: int = 0

    @property
    def complete(self) -> bool:
        return self.next_index >= len(self.steps)

    def witness_ok(self, index: int, now: float) -> bool:
        entry = self.witnesses.get(index)
        return entry is not None and now - entry[1] <= WITNESS_VALID_S

    def describe(self, now: float) -> dict[str, Any]:
        steps = []
        for index, (operation, safety_gate, two_person) in enumerate(self.steps):
            if index < self.next_index:
                status = "done"
            elif index == self.next_index:
                status = "next"
            else:
                status = "locked"
            witness = self.witnesses.get(index)
            steps.append({
                "step": index + 1,
                "operation": operation,
                "label": OP_LABELS[operation],
                "safety_gate": safety_gate,
                "two_person": two_person,
                "status": status,
                "witness": witness[0] if witness else None,
                "witness_valid": self.witness_ok(index, now) if two_person else None,
            })
        return {
            "procedure_id": self.procedure_id,
            "bay_id": self.bay_id,
            "goal": self.goal,
            "goal_label": GOAL_LABELS[self.goal],
            "operator": self.operator,
            "complete": self.complete,
            "blocked_attempts": self.blocked_attempts,
            "steps": steps,
        }
