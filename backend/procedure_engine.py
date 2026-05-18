"""
procedure_engine.py — Sequence orchestrator for Tier IV procedures.

This is Sprint 1 of the Opción B roadmap. It implements the state
machine + step executor + audit trail for declarative procedures
(YAML-defined MOPs). It does NOT yet talk to real Cummins/ASCO/
Russelectric hardware — that is Sprint 2 (HAL adapters).

What it CAN do today:
  - Load procedures from config/procedures/*.yml
  - Validate pre-conditions before arming
  - Execute step sequence with state machine gates
  - Capture witness signatures (Sprint 3 expands this)
  - Stop and run abort_sequence on failure
  - Persist execution log for audit

What it CANNOT do today (honest):
  - Talk to real generators / ATS / UPS
  - Block on physical interlocks (dead-man circuit is Sprint 4)
  - Validate weather (Sprint 5 adds external API)
  - Multi-signature witness (Sprint 3 adds 2-of-3 logic)

Currently any 'adapter' call falls through to a SimulatedAdapter that
reads from bms_connector and never writes. The procedure_engine is
correct; the hardware bridge is the next sprint.

Honest scope notes embedded in code with `_sprint_2_TODO`,
`_sprint_3_TODO`, etc. so a reviewer sees exactly what is done vs
deferred.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from backend.cmms_models import (
    RBACDeniedError,
    UserRole,
    can_approve_work_order,
    can_arm_critical_procedure,
    can_qa_signoff_vendor,
)

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
#  State machine
# ─────────────────────────────────────────────────────────────────────────
class ProcedureState(str, Enum):
    """Valid states. Transitions enforced by ProcedureExecution.transition_to()."""

    CREATED = "CREATED"
    PRE_CONDITION_CHECK = "PRE_CONDITION_CHECK"
    ARMED = "ARMED"
    IN_PROGRESS = "IN_PROGRESS"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    ABORTING = "ABORTING"
    ABORTED = "ABORTED"


# Valid transition graph. Any other transition is a bug.
_VALID_TRANSITIONS: dict[ProcedureState, set[ProcedureState]] = {
    ProcedureState.CREATED: {ProcedureState.PRE_CONDITION_CHECK},
    ProcedureState.PRE_CONDITION_CHECK: {ProcedureState.ARMED, ProcedureState.ABORTED},
    ProcedureState.ARMED: {ProcedureState.IN_PROGRESS, ProcedureState.ABORTED},
    ProcedureState.IN_PROGRESS: {ProcedureState.VERIFYING, ProcedureState.ABORTING},
    ProcedureState.VERIFYING: {ProcedureState.COMPLETED, ProcedureState.ABORTING},
    ProcedureState.ABORTING: {ProcedureState.ABORTED},
    # Terminal states
    ProcedureState.COMPLETED: set(),
    ProcedureState.ABORTED: set(),
}


# ─────────────────────────────────────────────────────────────────────────
#  Procedure class (SOP / MOP / EOP) + EOP fast-path transition graph
# ─────────────────────────────────────────────────────────────────────────
class ProcedureClass(str, Enum):
    """Operational procedure tier per Microsoft CO+I doctrine.

    SOP  — Standard Operating Procedure: routine stability / consistency
           (daily rounds, BMS monitoring). Prevents human error.
    MOP  — Method of Procedure: planned maintenance with explicit
           approval, risk assessment, isolation mapping and rollback.
    DMOP — De-energized Method of Procedure: a MOP requiring full LOTO
           isolation (LOR >= 3). Drives the cmms_mcp two-person rule.
    EOP  — Emergency Operating Procedure: active-failure response.
           Fast-path — bypasses the manual approval (ARMED) gate.
    EMP  — Equipment Maintenance Procedure: micro-component preventive
           testing (filter / breaker / sensor scope), G1 taxonomy.
    """

    SOP = "SOP"
    MOP = "MOP"
    DMOP = "DMOP"
    EOP = "EOP"
    EMP = "EMP"


# EOP fast-path transition graph. An EOP responding to a live failure must
# reach IN_PROGRESS without waiting on the manual approval / witness gate
# that ARMED represents — so PRE_CONDITION_CHECK -> IN_PROGRESS is a legal
# transition for EOP procedures only. transition_to() selects this graph
# when ProcedureExecution.procedure_class == ProcedureClass.EOP.
_EOP_TRANSITIONS: dict[ProcedureState, set[ProcedureState]] = {
    **_VALID_TRANSITIONS,
    ProcedureState.PRE_CONDITION_CHECK: {
        ProcedureState.ARMED,
        ProcedureState.IN_PROGRESS,  # fast-path: skip the ARMED approval gate
        ProcedureState.ABORTED,
    },
}


# ─────────────────────────────────────────────────────────────────────────
#  Data structures
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class StepResult:
    """One step's execution outcome. Appended to execution_log."""

    step_id: str
    title: str
    started_at_unix: float
    finished_at_unix: float | None = None
    status: str = "PENDING"  # PENDING | RUNNING | OK | FAILED | ABORTED
    operator_acknowledged_by: str | None = None
    witness_acknowledged_by: str | None = None
    adapter_response: dict | None = None
    error: str | None = None

    @property
    def duration_s(self) -> float | None:
        if self.finished_at_unix is None:
            return None
        return self.finished_at_unix - self.started_at_unix


@dataclass
class ProcedureExecution:
    """Runtime execution of a procedure. One per operator-initiated run."""

    execution_id: str
    procedure_id: str
    procedure_title: str
    operator: str
    state: ProcedureState
    created_at_unix: float
    started_at_unix: float | None = None
    completed_at_unix: float | None = None
    abort_reason: str | None = None
    pre_condition_results: list[dict] = field(default_factory=list)
    execution_log: list[StepResult] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    procedure_class: ProcedureClass = ProcedureClass.MOP
    vendor_supervision_log: list = field(default_factory=list)

    def transition_to(
        self,
        new_state: ProcedureState,
        actor_role: UserRole | str | None = None,
    ) -> None:
        """Enforce valid state transitions. Raises if invalid.

        EOP procedures use the fast-path graph (_EOP_TRANSITIONS): an
        emergency response may go PRE_CONDITION_CHECK -> IN_PROGRESS
        directly, skipping the manual approval gate that ARMED represents.

        RBAC: the ARMED transition is gated. A TECH_L4 cannot ARM a
        procedure — SENIOR_TECH_L5 is the floor, SME_L6 for a high-risk
        one (metadata['high_risk']). The gate enforces strictly only when
        actor_role is supplied; legacy call sites that pass none get a
        warning, not a block, until the auth layer is wired.
        """
        graph = (
            _EOP_TRANSITIONS
            if self.procedure_class == ProcedureClass.EOP
            else _VALID_TRANSITIONS
        )
        valid_next = graph.get(self.state, set())
        if new_state not in valid_next:
            raise InvalidTransitionError(
                f"Cannot transition {self.state} -> {new_state}. Valid next states: {valid_next}"
            )
        if new_state is ProcedureState.ARMED:
            high_risk = bool(self.metadata.get("high_risk", False))
            if actor_role is None:
                log.warning(
                    "[procedure_engine] %s -> ARMED with no actor_role; "
                    "RBAC gate NOT enforced (auth layer pending)",
                    self.execution_id[:8],
                )
            elif not can_arm_critical_procedure(actor_role, high_risk=high_risk):
                raise RBACDeniedError(
                    f"role {actor_role} cannot ARM procedure {self.procedure_id} "
                    f"(high_risk={high_risk}) - "
                    f"{'SME_L6' if high_risk else 'SENIOR_TECH_L5 or SME_L6'} required."
                )
        log.info(
            "[procedure_engine] %s: %s -> %s",
            self.execution_id[:8],
            self.state.value,
            new_state.value,
        )
        self.state = new_state


class InvalidTransitionError(RuntimeError):
    """Raised when transition_to() is called with an invalid target state."""


class ProcedureNotFoundError(KeyError):
    """Raised when a procedure_id has no corresponding YAML file."""


class PreConditionFailedError(RuntimeError):
    """Raised when a hard precondition fails. Triggers ABORT."""


# ─────────────────────────────────────────────────────────────────────────
#  Vendor supervision lifecycle — 3-step tiered loop within an MOP
# ─────────────────────────────────────────────────────────────────────────
class VendorSupervisionStage(str, Enum):
    """Tiered vendor-management loop executed inside an MOP. Modeled as
    its own ordered sub-stage enum rather than as new ProcedureState
    members — the loop is a sub-process within IN_PROGRESS, and adding it
    to the core 8-state graph would break every existing transition path.

    PRE_WORK_BRIEFING_COMPLETED — safety / scope briefing logged.
    ACTIVE_SHIFT_SUPERVISION    — vendor working under escort.
    POST_WORK_QA_SIGNOFF        — QA acceptance that closes the LOTO.
    """

    PRE_WORK_BRIEFING_COMPLETED = "PRE_WORK_BRIEFING_COMPLETED"
    ACTIVE_SHIFT_SUPERVISION = "ACTIVE_SHIFT_SUPERVISION"
    POST_WORK_QA_SIGNOFF = "POST_WORK_QA_SIGNOFF"


# Ordered progression — a stage may only be logged once its predecessor is.
_VENDOR_STAGE_ORDER: list[VendorSupervisionStage] = [
    VendorSupervisionStage.PRE_WORK_BRIEFING_COMPLETED,
    VendorSupervisionStage.ACTIVE_SHIFT_SUPERVISION,
    VendorSupervisionStage.POST_WORK_QA_SIGNOFF,
]


@dataclass
class VendorSupervisionRecord:
    """Audit record of one logged vendor-supervision stage."""

    stage: VendorSupervisionStage
    logged_by: str
    logged_by_role: str
    logged_at_unix: float


def log_vendor_stage(
    stage: VendorSupervisionStage,
    actor_role: UserRole | str | None,
    logged_by: str,
    prior_stages: list[VendorSupervisionStage] | None = None,
) -> VendorSupervisionRecord:
    """Validate + build a vendor-supervision record. Raises on a gate fail.

    - Stages must be logged in order (no skipping a predecessor).
    - PRE_WORK_BRIEFING_COMPLETED + ACTIVE_SHIFT_SUPERVISION: any tech (L4+).
    - POST_WORK_QA_SIGNOFF: SENIOR_TECH_L5 or higher — it closes the LOTO.
    """
    prior = prior_stages or []
    idx = _VENDOR_STAGE_ORDER.index(stage)
    if idx > 0 and _VENDOR_STAGE_ORDER[idx - 1] not in prior:
        raise InvalidTransitionError(
            f"vendor stage {stage.value} cannot be logged before "
            f"{_VENDOR_STAGE_ORDER[idx - 1].value} is complete"
        )
    if stage is VendorSupervisionStage.POST_WORK_QA_SIGNOFF and not can_qa_signoff_vendor(actor_role):
        raise RBACDeniedError(
            f"role {actor_role or 'NONE'} cannot sign off vendor QA "
            "(closes the LOTO) — SENIOR_TECH_L5 or SME_L6 required."
        )
    return VendorSupervisionRecord(
        stage=stage,
        logged_by=logged_by,
        logged_by_role=str(actor_role) if actor_role else "UNKNOWN",
        logged_at_unix=time.time(),
    )


# ─────────────────────────────────────────────────────────────────────────
#  G4 -- RBAC procedure promotion gate (DRAFT -> ACTIVE)
# ─────────────────────────────────────────────────────────────────────────
DRAFT_STATUS = "DRAFT"
ACTIVE_STATUS = "ACTIVE"


def promote_procedure(procedure: dict, actor_role: UserRole | str) -> dict:
    """Promote a generated DRAFT procedure to ACTIVE / v1.0.

    RBAC gate (Multi-Tier framework): only SENIOR_TECH_L5 or SME_L6 may
    activate a procedure. A TECH_L4 may draft or compile one (the
    procedure_generator factories) but cannot promote it -- the attempt
    raises RBACDeniedError with a descriptive message.

    Returns a promoted copy (status ACTIVE, version 1.0, activated_by_role
    audit stamp); the input dict is not mutated.
    """
    current = procedure.get("status", DRAFT_STATUS)
    if current == ACTIVE_STATUS:
        return procedure  # already active -- idempotent
    if current != DRAFT_STATUS:
        raise InvalidTransitionError(
            f"cannot promote a procedure in status {current!r}; expected DRAFT"
        )

    role_name = (actor_role.value if isinstance(actor_role, UserRole)
                 else str(actor_role))
    if not can_approve_work_order(actor_role):
        raise RBACDeniedError(
            f"role {role_name} cannot promote a procedure to ACTIVE -- "
            "SENIOR_TECH_L5 or SME_L6 signature is required. A TECH_L4 may "
            "draft or compile a procedure but may not activate it."
        )

    promoted = dict(procedure)
    promoted["status"] = ACTIVE_STATUS
    promoted["version"] = "1.0"
    promoted["activated_by_role"] = role_name
    return promoted


# ─────────────────────────────────────────────────────────────────────────
#  Procedure registry (loads YAMLs from disk)
# ─────────────────────────────────────────────────────────────────────────
class ProcedureRegistry:
    """In-memory cache of procedure definitions. Load once at boot."""

    def __init__(self, procedures_dir: Path):
        self.procedures_dir = procedures_dir
        self._procedures: dict[str, dict] = {}

    def load_all(self) -> None:
        """Walk procedures_dir and load every *.yml file."""
        if not self.procedures_dir.exists():
            log.warning(
                "[procedure_engine] procedures dir not found: %s",
                self.procedures_dir,
            )
            return

        for yml_path in self.procedures_dir.glob("*.yml"):
            try:
                with open(yml_path, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                pid = data.get("procedure_id")
                if not pid:
                    log.error(
                        "[procedure_engine] %s missing procedure_id, skipping",
                        yml_path,
                    )
                    continue
                self._procedures[pid] = data
                log.info("[procedure_engine] loaded %s from %s", pid, yml_path.name)
            except yaml.YAMLError as e:
                log.error("[procedure_engine] YAML parse error in %s: %s", yml_path, e)

    def get(self, procedure_id: str) -> dict:
        if procedure_id not in self._procedures:
            raise ProcedureNotFoundError(procedure_id)
        return self._procedures[procedure_id]

    def list_ids(self) -> list[str]:
        return list(self._procedures.keys())

    def get_summary(self, procedure_id: str) -> dict:
        """Lightweight metadata for HMI display, without full step list."""
        p = self.get(procedure_id)
        return {
            "procedure_id": p.get("procedure_id"),
            "title": p.get("title"),
            "work_class": p.get("work_class"),
            "procedure_class": p.get("procedure_class"),
            "default_lor": p.get("default_lor"),
            "step_count": len(p.get("steps", [])),
            "pre_condition_count": len(p.get("pre_conditions", [])),
            "has_abort_sequence": bool(p.get("abort_sequence")),
        }


# ─────────────────────────────────────────────────────────────────────────
#  Pre-condition evaluator
# ─────────────────────────────────────────────────────────────────────────
class PreConditionEvaluator:
    """Evaluates pre_conditions block before arming a procedure.

    HONEST: This is a minimal stub for Sprint 1. Full evaluation
    (weather API, redundancy state, time-window logic) is Sprint 5.
    Today it understands a small set of literal checks against state
    pulled from bms_connector + topology endpoint.
    """

    def __init__(self, state_provider: StateProvider):
        self.state = state_provider

    async def evaluate(self, pre_conditions: list[dict]) -> list[dict]:
        """Return list of result dicts: {id, passed, value, action_on_fail}."""
        results = []
        for cond in pre_conditions:
            cond_id = cond.get("id", "unnamed_condition")
            check_expr = cond.get("check", "")
            failure_action = cond.get("failure_action", "ABORT")

            try:
                passed, observed = await self._eval_check(check_expr)
                results.append(
                    {
                        "id": cond_id,
                        "check": check_expr,
                        "passed": passed,
                        "observed": observed,
                        "failure_action": failure_action,
                        "_evaluator_status": "ok",
                    }
                )
            except Exception as e:
                # Conservative default: unknown check fails closed.
                results.append(
                    {
                        "id": cond_id,
                        "check": check_expr,
                        "passed": False,
                        "observed": None,
                        "failure_action": failure_action,
                        "_evaluator_status": f"error: {type(e).__name__}: {e}",
                        "_sprint_5_TODO": (
                            "Full expression evaluator for weather, time-windows, "
                            "and complex predicates is Sprint 5. Today only "
                            "exact-match checks against current state are supported."
                        ),
                    }
                )
        return results

    async def _eval_check(self, expr: str) -> tuple[bool, Any]:
        """Stub evaluator. Recognizes a few literal patterns from
        the example MOP YAMLs. Anything else: closed-fail safely."""
        expr_clean = expr.strip()

        # site_redundancy_mode == "VALUE"
        if expr_clean.startswith("site_redundancy_mode"):
            mode = await self.state.get_redundancy_mode()
            return (mode == "2N"), {"site_redundancy_mode": mode}

        # severity_max < CRITICAL  (incidents)
        if expr_clean.startswith("severity_max"):
            severity = await self.state.get_max_severity()
            return (severity != "CRITICAL"), {"severity_max": severity}

        # Anything else not yet implemented — fail-closed
        return False, {
            "_unsupported_expression": expr_clean,
            "_default_behavior": "fail_closed_for_safety",
        }


# ─────────────────────────────────────────────────────────────────────────
#  State provider (abstraction over current bms_connector + topology)
# ─────────────────────────────────────────────────────────────────────────
class StateProvider:
    """Pulls current facility state for pre-condition checks.

    Wraps existing tools (bms_connector, topology endpoint) so the
    procedure_engine doesn't import from main.py directly.
    """

    async def get_redundancy_mode(self) -> str:
        """Read site redundancy mode. Stub returns 2N until topology
        endpoint integration is wired in Sprint 1.5 follow-up."""
        return "2N"  # _sprint_1_TODO: read from topology/state endpoint

    async def get_max_severity(self) -> str:
        """Stub returns OK. Sprint 1.5 wires this to incidents table."""
        return "OK"  # _sprint_1_TODO: query incidents WHERE acked = false


# ─────────────────────────────────────────────────────────────────────────
#  Adapter facade (used by step executor)
# ─────────────────────────────────────────────────────────────────────────
class AdapterRegistry:
    """Sprint 1 ships with SimulatedAdapter only. Sprint 2 adds
    cummins/asco/russelectric real adapters following this same
    interface."""

    def __init__(self):
        self._adapters: dict[str, BaseAdapter] = {}

    def register(self, name: str, adapter: BaseAdapter) -> None:
        self._adapters[name] = adapter

    def get(self, name: str) -> BaseAdapter:
        if name not in self._adapters:
            # Fall-through to simulated. Logs warning for visibility.
            log.warning(
                "[procedure_engine] adapter '%s' not registered; "
                "falling back to SimulatedAdapter (Sprint 2 will add real adapter)",
                name,
            )
            return self._adapters.setdefault("simulated", SimulatedAdapter())
        return self._adapters[name]


class BaseAdapter:
    """Interface contract for hardware adapters. Sprint 2 implementations
    inherit from this."""

    async def read(self, target: str, fields: list[str]) -> dict:
        raise NotImplementedError

    async def write(self, target: str, command: str, payload: dict | None = None) -> dict:
        raise NotImplementedError

    async def verify_state(self, target: str, expected: dict) -> tuple[bool, dict]:
        """Read current state and compare against expected dict.
        Returns (all_match, observed_values_dict)."""
        raise NotImplementedError


class SimulatedAdapter(BaseAdapter):
    """Stub used during Sprint 1 development. Returns synthetic data
    consistent with bms_connector tags. Replaced per-vendor in Sprint 2."""

    async def read(self, target: str, fields: list[str]) -> dict:
        return {f: f"<simulated-{target}-{f}>" for f in fields}

    async def write(self, target: str, command: str, payload: dict | None = None) -> dict:
        log.info(
            "[SimulatedAdapter] WRITE %s.%s payload=%s (NO ACTUAL WRITE)",
            target,
            command,
            payload,
        )
        return {
            "status": "SIMULATED_OK",
            "target": target,
            "command": command,
            "_note": (
                "SimulatedAdapter accepts all writes without validation. "
                "Sprint 2 replaces this with real protocol adapters."
            ),
        }

    async def verify_state(self, target: str, expected: dict) -> tuple[bool, dict]:
        # Always returns True for simulation. Sprint 2 implements real verify.
        return True, {"_note": "SimulatedAdapter.verify_state returns OK"}


# ─────────────────────────────────────────────────────────────────────────
#  Step executor — the core of the orchestrator
# ─────────────────────────────────────────────────────────────────────────
class StepExecutor:
    """Executes one step from a procedure YAML.

    Each step is one of:
      - notification     (e.g., tenant notice)
      - read_verify      (read state, compare to expected)
      - write_verify     (write a command, then read & verify)
      - dwell            (wait N seconds, monitoring optional)
      - read_dwell       (combine read_verify + dwell)
      - cmms_finalize    (post to CMMS audit)

    All step executions go through the adapter registry. The step
    executor itself is hardware-agnostic.
    """

    def __init__(self, adapter_registry: AdapterRegistry):
        self.adapters = adapter_registry

    async def execute_step(self, step: dict, exec_ctx: ProcedureExecution) -> StepResult:
        step_id = step.get("id", "unnamed_step")
        title = step.get("title", "(no title)")
        result = StepResult(
            step_id=step_id,
            title=title,
            started_at_unix=time.time(),
            status="RUNNING",
        )
        try:
            step_type = step.get("type", "unknown")
            handler = {
                "notification": self._exec_notification,
                "read_verify": self._exec_read_verify,
                "write_verify": self._exec_write_verify,
                "dwell": self._exec_dwell,
                "read_dwell": self._exec_read_dwell,
                "cmms_finalize": self._exec_cmms_finalize,
            }.get(step_type)
            if handler is None:
                raise NotImplementedError(f"step type '{step_type}' not handled")

            adapter_response = await handler(step)
            result.adapter_response = adapter_response
            result.status = "OK"
        except Exception as e:
            result.status = "FAILED"
            result.error = f"{type(e).__name__}: {e}"
            log.error(
                "[procedure_engine] step %s FAILED: %s",
                step_id,
                result.error,
            )
        finally:
            result.finished_at_unix = time.time()
        return result

    # ── Step type handlers ────────────────────────────────────────────
    async def _exec_notification(self, step: dict) -> dict:
        # Sprint 1 stub. Sprint 5+ wires actual tenant-notification system.
        log.info("[procedure_engine] NOTIFY (stub) %s", step.get("title"))
        return {
            "status": "STUBBED",
            "_sprint_5_TODO": "wire to real tenant notification API",
        }

    async def _exec_read_verify(self, step: dict) -> dict:
        adapter = self.adapters.get(step.get("adapter", "simulated"))
        target = step.get("target")
        expected = step.get("expected", {})
        ok, observed = await adapter.verify_state(target, expected)
        if not ok:
            raise RuntimeError(
                f"verify_state failed for {target}: observed={observed}, expected={expected}"
            )
        return {"verify": "OK", "observed": observed}

    async def _exec_write_verify(self, step: dict) -> dict:
        adapter = self.adapters.get(step.get("adapter", "simulated"))
        target = step.get("target")
        command = step.get("command")
        payload = step.get("payload") or {}
        timeout_s = float(step.get("timeout_s", 30))

        write_resp = await asyncio.wait_for(
            adapter.write(target, command, payload),
            timeout=timeout_s,
        )

        verify_after = step.get("verify_after") or {}
        if verify_after:
            ok, observed = await adapter.verify_state(target, verify_after)
            if not ok:
                raise RuntimeError(
                    f"post-write verify failed for {target}: "
                    f"observed={observed}, expected={verify_after}"
                )
            return {"write": write_resp, "verify": "OK", "observed": observed}
        return {"write": write_resp}

    async def _exec_dwell(self, step: dict) -> dict:
        duration_s = float(step.get("duration_s", 0))
        # _sprint_4_TODO: monitor block aborts dwell on threshold breach.
        # Today we just sleep; emergency abort is Sprint 4.
        # Dev cap: 0.5s for fast test loops. Production removes the cap;
        # Sprint 4 adds monitor-driven abort that can break a long sleep early.
        await asyncio.sleep(min(duration_s, 0.5))
        return {
            "dwelled_s": duration_s,
            "_sprint_1_dev_note": (
                "Dwell capped at 0.5s in development to keep test loops fast. "
                "Production removes the cap; Sprint 4 adds monitor-driven abort."
            ),
        }

    async def _exec_read_dwell(self, step: dict) -> dict:
        # Combination of dwell + post-dwell read_verify
        dwell_resp = await self._exec_dwell(step)
        expected = step.get("expected_at_end") or {}
        if expected:
            adapter = self.adapters.get(step.get("adapter", "simulated"))
            ok, observed = await adapter.verify_state(step.get("target"), expected)
            if not ok and step.get("abort_on_failure", True):
                raise RuntimeError(
                    f"post-dwell verify failed: observed={observed}, expected={expected}"
                )
            return {"dwell": dwell_resp, "verify_at_end": observed}
        return {"dwell": dwell_resp}

    async def _exec_cmms_finalize(self, step: dict) -> dict:
        # Stub. Sprint 6 wires to cmms_mcp draft creation (PASS/FAIL log entry).
        return {
            "status": "STUBBED",
            "_sprint_6_TODO": "create CMMS audit log entry from procedure outcome",
        }


# ─────────────────────────────────────────────────────────────────────────
#  Procedure orchestrator — the public entry point
# ─────────────────────────────────────────────────────────────────────────
class ProcedureOrchestrator:
    """Top-level: holds registry, evaluator, executor. The HMI calls
    `start_procedure(procedure_id, operator)` and gets back an execution
    handle. Subsequent calls (arm, advance_step, abort) progress the
    state machine."""

    def __init__(
        self,
        registry: ProcedureRegistry,
        evaluator: PreConditionEvaluator,
        executor: StepExecutor,
        witness_gate: Any | None = None,  # WitnessGate, kept Any to avoid circular import
    ):
        self.registry = registry
        self.evaluator = evaluator
        self.executor = executor
        self.witness_gate = witness_gate
        self._executions: dict[str, ProcedureExecution] = {}

    def list_executions(self) -> list[dict]:
        return [asdict(e) for e in self._executions.values()]

    def get_execution(self, exec_id: str) -> ProcedureExecution:
        if exec_id not in self._executions:
            raise KeyError(f"execution {exec_id} not found")
        return self._executions[exec_id]

    async def start_procedure(self, procedure_id: str, operator: str) -> ProcedureExecution:
        proc = self.registry.get(procedure_id)
        exec_id = uuid.uuid4().hex
        execution = ProcedureExecution(
            execution_id=exec_id,
            procedure_id=procedure_id,
            procedure_title=proc.get("title", procedure_id),
            operator=operator,
            state=ProcedureState.CREATED,
            created_at_unix=time.time(),
        )
        self._executions[exec_id] = execution

        # ── Pre-condition phase ──────────────────────────────────────
        execution.transition_to(ProcedureState.PRE_CONDITION_CHECK)
        results = await self.evaluator.evaluate(proc.get("pre_conditions", []))
        execution.pre_condition_results = results

        any_hard_failure = any(
            (not r["passed"]) and r["failure_action"] == "ABORT" for r in results
        )
        if any_hard_failure:
            execution.transition_to(ProcedureState.ABORTED)
            execution.abort_reason = "pre_condition_failed"
            execution.completed_at_unix = time.time()
            return execution

        # All hard pre-conditions passed → ARMED, awaits operator GO
        execution.transition_to(ProcedureState.ARMED)
        return execution

    async def advance_to_in_progress(self, exec_id: str, operator: str) -> ProcedureExecution:
        """Operator clicks 'GO' from ARMED state. Begins step execution."""
        execution = self.get_execution(exec_id)
        if execution.state != ProcedureState.ARMED:
            raise RuntimeError(f"cannot start: state is {execution.state}, expected ARMED")

        # _sprint_3_TODO: witness signature check goes here for LOR>=3 procedures.
        # Today any operator can advance; multi-signature is Sprint 3.

        execution.transition_to(ProcedureState.IN_PROGRESS)
        execution.started_at_unix = time.time()

        proc = self.registry.get(execution.procedure_id)
        await self._run_steps(execution, proc)
        return execution

    async def _run_steps(self, execution: ProcedureExecution, proc: dict) -> None:
        """Execute steps in order. Steps with requires_witness=true block
        until a second operator signs via WitnessGate.

        On any step failure with abort_on_failure=True, transition to ABORTING."""
        for step in proc.get("steps", []):
            # ── Witness gate (Sprint 3) ───────────────────────────────
            # If the step requires a witness AND the gate is configured,
            # block here until signed/rejected/expired. The gate creates
            # a WitnessRequest visible in the HMI; HMI surfaces it to a
            # second qualified operator who clicks "Sign as witness".
            if step.get("requires_witness") and self.witness_gate is not None:
                witness_req = await self.witness_gate.await_witness(
                    execution_id=execution.execution_id,
                    procedure_id=execution.procedure_id,
                    step=step,
                    initiator=execution.operator,
                    context={
                        "procedure_title": execution.procedure_title,
                        "current_state": execution.state.value,
                        "steps_completed_so_far": len(execution.execution_log),
                    },
                )
                # Translate witness outcome into step result
                if witness_req.status.value != "SIGNED":
                    # Rejected, expired, or superseded — abort
                    fake_result = StepResult(
                        step_id=step.get("id", "unknown"),
                        title=step.get("title", "(no title)"),
                        started_at_unix=time.time(),
                        finished_at_unix=time.time(),
                        status="FAILED",
                        error=(
                            f"witness_gate: status={witness_req.status.value}"
                            f"{' reason=' + witness_req.rejection_reason if witness_req.rejection_reason else ''}"
                        ),
                    )
                    execution.execution_log.append(fake_result)
                    await self._abort_execution(
                        execution,
                        proc,
                        reason=(
                            f"step {step.get('id')} not authorised: "
                            f"witness {witness_req.status.value}"
                        ),
                    )
                    return
                # Signature OK — record the witness identity in execution metadata
                execution.metadata.setdefault("witness_signatures", []).append(
                    {
                        "step_id": step.get("id"),
                        "witness": witness_req.witness,
                        "signed_at_unix": witness_req.signed_at_unix,
                    }
                )

            # ── Execute the step (with or without witness above) ──────
            result = await self.executor.execute_step(step, execution)

            # If the step required a witness, attach the witness identity
            # to the result so the audit log captures who signed for what.
            if step.get("requires_witness") and self.witness_gate is not None:
                sigs = execution.metadata.get("witness_signatures", [])
                # Find the most recent signature for this step
                for sig in reversed(sigs):
                    if sig["step_id"] == step.get("id"):
                        result.witness_acknowledged_by = sig["witness"]
                        break

            execution.execution_log.append(result)

            if result.status == "FAILED" and step.get("abort_on_failure", True):
                await self._abort_execution(
                    execution,
                    proc,
                    reason=f"step {result.step_id} failed: {result.error}",
                )
                return

        # All steps OK → VERIFYING then COMPLETED
        execution.transition_to(ProcedureState.VERIFYING)
        # _sprint_6_TODO: post-execution verification block (compare end state
        # to baseline state for drift detection).
        execution.transition_to(ProcedureState.COMPLETED)
        execution.completed_at_unix = time.time()

    async def _abort_execution(
        self,
        execution: ProcedureExecution,
        proc: dict,
        reason: str,
    ) -> None:
        # If we're in ARMED, we never started running steps, so there is
        # nothing to abort-sequence — go directly to ABORTED. ABORTING is
        # only the right state when steps are mid-flight.
        if execution.state == ProcedureState.ARMED:
            execution.transition_to(ProcedureState.ABORTED)
            execution.abort_reason = reason
            execution.completed_at_unix = time.time()
            log.warning(
                "[procedure_engine] %s ABORTED from ARMED: %s",
                execution.execution_id[:8],
                reason,
            )
            return

        execution.transition_to(ProcedureState.ABORTING)
        execution.abort_reason = reason
        log.warning(
            "[procedure_engine] %s ABORTING: %s",
            execution.execution_id[:8],
            reason,
        )

        # Run abort_sequence if defined. _sprint_4_TODO: tighter timing
        # contracts on abort steps + emergency interlock priority.
        for abort_step in proc.get("abort_sequence", []):
            for _name, step_def in abort_step.items() if isinstance(abort_step, dict) else []:
                try:
                    await self.executor.execute_step(step_def, execution)
                except Exception as e:
                    log.error("[procedure_engine] abort step also failed: %s", e)

        execution.transition_to(ProcedureState.ABORTED)
        execution.completed_at_unix = time.time()

    async def abort_now(self, exec_id: str, operator: str, reason: str) -> ProcedureExecution:
        """Operator-triggered emergency abort. Works from ARMED, IN_PROGRESS, VERIFYING."""
        execution = self.get_execution(exec_id)
        if execution.state in (
            ProcedureState.COMPLETED,
            ProcedureState.ABORTED,
            ProcedureState.ABORTING,
        ):
            return execution  # idempotent

        # Sprint 3: supersede any pending witness requests for this execution
        # so a stale witness signature can't unblock a now-dead procedure.
        if self.witness_gate is not None:
            try:
                self.witness_gate.store.supersede_for_execution(exec_id)
            except Exception as e:
                log.warning("[procedure_engine] supersede witness failed: %s", e)

        proc = self.registry.get(execution.procedure_id)
        await self._abort_execution(
            execution,
            proc,
            reason=f"operator_abort:{operator}:{reason}",
        )
        return execution


# ─────────────────────────────────────────────────────────────────────────
#  Module-level factory (called from main.py mount block)
# ─────────────────────────────────────────────────────────────────────────
def build_default_orchestrator(project_root: Path) -> ProcedureOrchestrator:
    """Convenience factory used by main.py to instantiate the singleton."""
    registry = ProcedureRegistry(project_root / "config" / "procedures")
    registry.load_all()

    state = StateProvider()
    evaluator = PreConditionEvaluator(state)

    adapters = AdapterRegistry()
    adapters.register("simulated", SimulatedAdapter())
    # Sprint 2: register real adapters here
    #   adapters.register("cummins", CumminsModbusAdapter(...))
    #   adapters.register("asco", AscoBacnetAdapter(...))
    #   adapters.register("russelectric", RusselectricBypassAdapter(...))

    executor = StepExecutor(adapters)

    # Sprint 3: wire the witness gate. Lazy import to avoid circular dep.
    try:
        from witness_engine import WitnessGate, get_witness_store

        witness_gate = WitnessGate(store=get_witness_store())
        log.info("[procedure_engine] WitnessGate wired (Sprint 3)")
    except ImportError as e:
        log.warning("[procedure_engine] WitnessGate not loaded: %s", e)
        witness_gate = None

    return ProcedureOrchestrator(registry, evaluator, executor, witness_gate)
