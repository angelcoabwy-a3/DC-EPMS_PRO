"""
backend/optimizer.py
=====================
Epic 2 Batch 2.A — The Optimizer (proactive edge-agent for PUE / WUE).

Design source-of-truth: ``docs/architecture/epic-2-optimizer.md``.

The Optimizer is a proactive complement to the Epic 1 reactive multi-
agent fleet: a continuous edge-agent that watches Hermes telemetry and
PROPOSES setpoint adjustments to drive PUE toward the architecture-
aware target. The load-bearing architectural decision is the **Proposer
Pattern** (ADR-006 anchored):

  * The proposal VALUE is computed by a pure-Python control law; the
    LLM is NEVER on the critical path. (S-DET-01)
  * The Optimizer has NO actor_role and never calls /api/bms/write
    even indirectly. (S-SEC-02 — enforced by an import-scan test in
    tests/test_optimizer.py.)
  * Multi-agent consensus + the Safety Officer veto are the gate that
    every proposal must clear before reaching the operator queue. The
    veto is uncrossable. (S-DET-02)
  * Operator approval at SME_L6 is what issues the BMS write — the
    Optimizer is never on that call stack.

Scope delivered by this batch (2.A)
-----------------------------------
  * The deterministic core: ``compute_proposal()`` + per-surface
    heuristics for ``chiller_lwt`` and ``ct_fan_vfd``.
  * Drift sustain detector (avoids firing on transient PUE spikes).
  * Per-surface pacing guard (oscillation control).
  * In-memory audit log (a persistent table arrives in 2.C).
  * Asyncio loop scaffold + env-flag gating
    (``DC_EPMS_OPTIMIZER_ENABLED``, default OFF for V11).

Subsequent batches will wire (2.B) multi-agent consensus + the proposal
queue + Hermes event emission; (2.C) the approve/reject endpoints with
RBAC + persistent audit chain; (2.D) the HMI surface; (2.E) the live
smoke test + ``v0.13.0`` "Proactive Edge" release tag.

Notes on calibration
--------------------
Threshold values in ``OptimizerConfig`` are placeholders inspired by
ASHRAE A2 + the V9 chiller curves. They MUST be re-calibrated against
Toronto-baseline runs (per the engram §11 geography note) before
running against any production-shaped workload. The control law is
deliberately rule-based for ADR-006 transparency; a learned PUE-
surrogate model may replace these heuristics in a later revision.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Any

log = logging.getLogger(__name__)


# ─── Surfaces handled by the V11 cut ──────────────────────────────────
SURFACE_CHILLER_LWT = "chiller_lwt"
SURFACE_CT_FAN_VFD = "ct_fan_vfd"

VALID_SURFACES: frozenset[str] = frozenset({SURFACE_CHILLER_LWT, SURFACE_CT_FAN_VFD})


# ─── Tunable thresholds (rule-based, ADR-006 transparency) ────────────
class OptimizerConfig:
    """Control-law thresholds. Re-calibrate against Toronto baseline runs."""

    # Drift detection
    PUE_DRIFT_THRESHOLD = 0.02       # PUE points above target before firing
    PUE_SUSTAIN_TICKS = 10           # ~5 min at the default 30 s tick

    # Chiller LWT bounds (°C)
    LWT_FLOOR_C = 6.0                # do not propose below this
    LWT_STEP_C = 0.5                 # propose drop in 0.5 K increments
    LWT_HALL_INLET_GUARD_C = 20.0    # if hall already this cold, skip

    # Cooling-tower fan VFD bounds (%)
    CT_VFD_MAX_PCT = 100.0           # already saturated → no proposal
    CT_VFD_STEP_PCT = 5.0
    CT_APPROACH_FLOOR_K = 2.0        # tower saturated below this approach
    CT_APPROACH_HEADROOM_K = 5.0     # only push fan above this approach

    # Pacing — at most one proposal per surface per 15 minutes
    PACING_SECONDS = 15 * 60

    # Loop tick (seconds)
    LOOP_TICK_SECONDS = 30.0


# ─── Data classes ─────────────────────────────────────────────────────
@dataclass(frozen=True)
class TelemetryPoint:
    """Lightweight view of the live telemetry payload for control-law input.

    The 2.B wiring layer maps Hermes / Kalman dicts into this shape. The
    control law is strictly typed against this — Hermes details belong
    in the wiring, not the core.
    """

    pue: float | None
    hall_temp_c: float | None
    ecwt_c: float | None             # entering condenser-water temperature
    wet_bulb_c: float | None
    chiller_lwt_c: float | None
    ct_fan_vfd_pct: float | None


@dataclass(frozen=True)
class Proposal:
    """A deterministic Optimizer proposal. Value fixed BEFORE any LLM call."""

    proposal_id: str
    surface: str
    current_value: float
    proposed_value: float
    delta: float
    rationale: str
    pue_at_emission: float | None
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuditEntry:
    """In-memory audit-log entry. 2.C will move this to PostgreSQL."""

    ts: float
    event: str
    proposal_id: str | None
    surface: str | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Audit event vocabulary
AUDIT_PROPOSED = "proposed"
AUDIT_PACED_OUT = "paced_out"
AUDIT_NO_DRIFT = "no_drift"
AUDIT_REJECTED_PRE_CONSENSUS = "rejected_pre_consensus"  # used from 2.B onward
AUDIT_SAFETY_VETO = "safety_veto"                         # used from 2.B onward
AUDIT_APPROVED = "approved"                               # used from 2.C onward


# ─── Deterministic core (S-DET-01 — verdict before LLM) ───────────────
def pue_drift(point: TelemetryPoint, pue_target: float) -> float | None:
    """Positive drift = PUE worse than target. ``None`` when no PUE reading."""
    if point.pue is None:
        return None
    return point.pue - pue_target


def compute_proposal(
    surface: str,
    point: TelemetryPoint,
    pue_target: float,
    cfg: type[OptimizerConfig] = OptimizerConfig,
) -> Proposal | None:
    """Deterministic control-law output for a single surface.

    Returns ``None`` if telemetry insufficient, surface saturated, or no
    improvement available within bounds. ADR-006: this function never
    calls an LLM — it IS the verdict for the Optimizer's proposal value.
    The LLM narrative is synthesized separately AFTER this returns (in
    Batch 2.B).
    """
    if surface not in VALID_SURFACES:
        return None
    drift = pue_drift(point, pue_target)
    if drift is None or drift <= cfg.PUE_DRIFT_THRESHOLD:
        return None
    if surface == SURFACE_CHILLER_LWT:
        return _propose_chiller_lwt(point, drift, cfg)
    if surface == SURFACE_CT_FAN_VFD:
        return _propose_ct_fan_vfd(point, drift, cfg)
    return None


def _propose_chiller_lwt(
    point: TelemetryPoint,
    drift: float,
    cfg: type[OptimizerConfig],
) -> Proposal | None:
    """Lower chiller LWT by one step when headroom exists and hall is warm enough.

    Heuristic — if PUE is drifting up AND the chiller LWT is above its
    operating floor AND the hall is not already cold (ASHRAE A2 guard),
    a lower LWT delivers more cooling per gallon, reducing compressor
    work at constant DLC load.
    """
    current = point.chiller_lwt_c
    if current is None or current <= cfg.LWT_FLOOR_C:
        return None
    # ASHRAE A2 guard — if hall inlet is already cold, no benefit
    if point.hall_temp_c is not None and point.hall_temp_c < cfg.LWT_HALL_INLET_GUARD_C:
        return None
    proposed = max(cfg.LWT_FLOOR_C, current - cfg.LWT_STEP_C)
    if proposed >= current:
        return None
    return Proposal(
        proposal_id=str(uuid.uuid4()),
        surface=SURFACE_CHILLER_LWT,
        current_value=current,
        proposed_value=proposed,
        delta=proposed - current,
        rationale=(
            f"PUE drift {drift:+.3f} above target sustained; LWT has "
            f"{current - cfg.LWT_FLOOR_C:.1f} K headroom above the "
            f"{cfg.LWT_FLOOR_C:.1f} C floor. Lowering LWT increases "
            f"cooling capacity per gallon, reducing chiller compressor "
            f"work at constant DLC load."
        ),
        pue_at_emission=point.pue,
        created_at=time.time(),
    )


def _propose_ct_fan_vfd(
    point: TelemetryPoint,
    drift: float,
    cfg: type[OptimizerConfig],
) -> Proposal | None:
    """Push CT fan VFD up one step when tower approach has clear headroom.

    Heuristic — approach = ECWT - WB. Below CT_APPROACH_FLOOR_K the
    tower is saturated and more fan does nothing. Below
    CT_APPROACH_HEADROOM_K the tower is already working hard and a 5 %
    bump won't move PUE enough to justify wear. Above the headroom
    threshold, more fan reduces ECWT, lowering condenser head pressure.
    """
    current = point.ct_fan_vfd_pct
    if current is None or current >= cfg.CT_VFD_MAX_PCT:
        return None
    if point.ecwt_c is None or point.wet_bulb_c is None:
        return None
    approach = point.ecwt_c - point.wet_bulb_c
    if approach < cfg.CT_APPROACH_HEADROOM_K:
        return None  # tower saturated or already working hard
    proposed = min(cfg.CT_VFD_MAX_PCT, current + cfg.CT_VFD_STEP_PCT)
    if proposed <= current:
        return None
    return Proposal(
        proposal_id=str(uuid.uuid4()),
        surface=SURFACE_CT_FAN_VFD,
        current_value=current,
        proposed_value=proposed,
        delta=proposed - current,
        rationale=(
            f"PUE drift {drift:+.3f} above target sustained; CT approach is "
            f"{approach:.1f} K (above the {cfg.CT_APPROACH_HEADROOM_K:.1f} K "
            f"headroom threshold). More fan capacity reduces ECWT, lowering "
            f"condenser head pressure on the chillers."
        ),
        pue_at_emission=point.pue,
        created_at=time.time(),
    )


# ─── PUE-drift sustain detector ──────────────────────────────────────
class DriftTracker:
    """Counts consecutive ticks where PUE drift exceeds threshold.

    Avoids firing on transient PUE spikes. ``update`` returns ``True``
    once the streak reaches ``sustain_ticks``; the streak does NOT reset
    on continued firings, so once sustained it stays sustained until
    drift drops below threshold.
    """

    def __init__(self, sustain_ticks: int = OptimizerConfig.PUE_SUSTAIN_TICKS):
        self._sustain = max(1, int(sustain_ticks))
        self._streak = 0

    def update(self, drift: float | None, threshold: float) -> bool:
        if drift is None or drift <= threshold:
            self._streak = 0
            return False
        self._streak += 1
        return self._streak >= self._sustain

    @property
    def streak(self) -> int:
        return self._streak

    def reset(self) -> None:
        self._streak = 0


# ─── Pacing guard ────────────────────────────────────────────────────
class PacingGuard:
    """Per-surface pacing — at most one proposal every ``pacing_seconds``."""

    def __init__(self, pacing_seconds: float = OptimizerConfig.PACING_SECONDS):
        self._pacing = max(0.0, float(pacing_seconds))
        self._last_emission: dict[str, float] = {}

    def is_paced_out(self, surface: str, now: float | None = None) -> bool:
        now_ts = now if now is not None else time.time()
        last = self._last_emission.get(surface)
        if last is None:
            return False
        return (now_ts - last) < self._pacing

    def record(self, surface: str, now: float | None = None) -> None:
        self._last_emission[surface] = now if now is not None else time.time()

    def reset(self) -> None:
        self._last_emission.clear()


# ─── Audit log (in-memory; persistent table arrives in 2.C) ──────────
class AuditLog:
    """Bounded in-memory ring buffer of Optimizer events.

    2.C will swap this for a PostgreSQL-backed table linked to the
    proposal queue + the operator approval rows by ``proposal_id``.
    """

    def __init__(self, max_entries: int = 500):
        self._entries: list[AuditEntry] = []
        self._max = max(1, int(max_entries))

    def write(
        self,
        event: str,
        proposal_id: str | None = None,
        surface: str | None = None,
        detail: str = "",
    ) -> AuditEntry:
        entry = AuditEntry(
            ts=time.time(),
            event=event,
            proposal_id=proposal_id,
            surface=surface,
            detail=detail,
        )
        self._entries.append(entry)
        if len(self._entries) > self._max:
            # Drop oldest — keep a sliding window
            self._entries = self._entries[-self._max:]
        return entry

    def entries(self, limit: int = 50) -> list[AuditEntry]:
        return list(self._entries[-max(0, int(limit)):])

    def __len__(self) -> int:
        return len(self._entries)


# ─── Optimizer service (2.A — scaffold, no consensus / no BMS write) ─
TelemetryProvider = Callable[[], Awaitable[TelemetryPoint | None] | TelemetryPoint | None]


class OptimizerService:
    """The proactive edge-agent. Batch 2.A — deterministic core + loop scaffold.

    Per the Epic 2 brief and ADR-006:
      * computes proposal values deterministically (``compute_proposal``);
      * has NO actor_role — cannot call /api/bms/write;
      * the 2.A loop emits proposals to its in-memory audit log only;
      * 2.B will wire multi-agent consensus + a real proposal queue;
      * 2.C will wire approve/reject endpoints + persistent audit.
    """

    def __init__(
        self,
        telemetry_provider: TelemetryProvider | None = None,
        pue_target: float = 1.30,
        cfg: type[OptimizerConfig] = OptimizerConfig,
    ):
        self._telemetry = telemetry_provider
        self._pue_target = float(pue_target)
        self._cfg = cfg
        self._drift = DriftTracker(cfg.PUE_SUSTAIN_TICKS)
        self._pacing = PacingGuard(cfg.PACING_SECONDS)
        self._audit = AuditLog()
        self._task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def audit(self) -> AuditLog:
        return self._audit

    @property
    def is_running(self) -> bool:
        return self._running

    async def _read_telemetry(self) -> TelemetryPoint | None:
        if self._telemetry is None:
            return None
        try:
            payload = self._telemetry()
            if asyncio.iscoroutine(payload):
                payload = await payload
            return payload if isinstance(payload, TelemetryPoint) else None
        except Exception as e:
            log.debug("[optimizer] telemetry read failed: %s", e)
            return None

    async def tick(self) -> list[Proposal]:
        """One control-loop tick. Returns the proposals emitted this tick.

        ADR-006 invariants (audited at every code change):
          * ``compute_proposal`` is pure-Python; no LLM call here.
          * No ``/api/bms/write`` is invoked from this method or its callees.
        """
        point = await self._read_telemetry()
        if point is None:
            return []

        drift = pue_drift(point, self._pue_target)
        sustained = self._drift.update(drift, self._cfg.PUE_DRIFT_THRESHOLD)
        if not sustained:
            if drift is not None and drift > self._cfg.PUE_DRIFT_THRESHOLD:
                self._audit.write(
                    AUDIT_NO_DRIFT,
                    detail=f"drift {drift:+.3f} above threshold but sustain "
                           f"streak {self._drift.streak}/{self._cfg.PUE_SUSTAIN_TICKS}",
                )
            return []

        emitted: list[Proposal] = []
        for surface in (SURFACE_CHILLER_LWT, SURFACE_CT_FAN_VFD):
            if self._pacing.is_paced_out(surface):
                self._audit.write(
                    AUDIT_PACED_OUT,
                    surface=surface,
                    detail=f"pacing guard suppressed {surface}",
                )
                continue
            proposal = compute_proposal(surface, point, self._pue_target, self._cfg)
            if proposal is None:
                continue
            self._audit.write(
                AUDIT_PROPOSED,
                proposal_id=proposal.proposal_id,
                surface=surface,
                detail=proposal.rationale,
            )
            self._pacing.record(surface)
            emitted.append(proposal)
        return emitted

    async def run_loop(self) -> None:
        """Long-running loop. Started by ``start()``; cancelled by ``stop()``.

        Per-tick exceptions are logged and skipped — the loop is durable.
        """
        log.info(
            "[optimizer] control loop starting (tick=%.1fs, target=%.2f)",
            self._cfg.LOOP_TICK_SECONDS, self._pue_target,
        )
        self._running = True
        try:
            while self._running:
                try:
                    await self.tick()
                except Exception as e:
                    # Loop must be durable — a per-tick failure (telemetry
                    # provider exception, transient state error) is logged
                    # and the loop keeps running. The deterministic core
                    # never raises by design; only adapters at the seam can.
                    log.warning("[optimizer] tick failed: %s", e, exc_info=True)
                await asyncio.sleep(self._cfg.LOOP_TICK_SECONDS)
        except asyncio.CancelledError:
            log.info("[optimizer] control loop cancelled")
            raise
        finally:
            self._running = False
            log.info("[optimizer] control loop stopped")

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self.run_loop())

    async def stop(self) -> None:
        self._running = False
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


# ─── Env-gated singleton ─────────────────────────────────────────────
_service: OptimizerService | None = None


def is_enabled() -> bool:
    """Opt-in by env flag. Default DISABLED for V11."""
    return os.environ.get("DC_EPMS_OPTIMIZER_ENABLED", "false").lower() in {
        "true", "1", "yes", "on",
    }


def get_service(
    telemetry_provider: TelemetryProvider | None = None,
    pue_target: float = 1.30,
) -> OptimizerService | None:
    """Return the singleton when the env flag is set; ``None`` otherwise.

    Per S-DET-01 / S-SEC-02: this function never touches the BMS write
    path. The returned service emits proposals to its in-memory audit
    log only. Multi-agent consensus + approve/reject endpoints arrive
    in Batches 2.B / 2.C.
    """
    if not is_enabled():
        return None
    global _service
    if _service is None:
        _service = OptimizerService(
            telemetry_provider=telemetry_provider, pue_target=pue_target,
        )
        log.info(
            "[optimizer] service initialised (Batch 2.A — control law + audit only)",
        )
    return _service


def reset_service() -> None:
    """Test helper — drop the singleton so the next ``get_service`` rebuilds."""
    global _service
    _service = None
