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
from dataclasses import asdict, dataclass, field
from typing import Any

from backend.multi_agent import VERDICT_HARD_STOP, ConsultContext

log = logging.getLogger(__name__)

# Type alias for the consult callback. We keep the return type loose
# (Any) because the orchestrator returns a ConsensusResult but we only
# duck-type its `.consensus`, `.rationale`, and `.safety_officer_veto`
# fields here — avoiding a hard module-load coupling and keeping the
# 2.B integration test trivial (a function returning a SimpleNamespace
# is sufficient).
ConsultFn = Callable[[ConsultContext], Awaitable[Any]]
EventEmitter = Callable[[str, dict[str, Any]], Any]
KalmanProvider = Callable[[], Awaitable[dict[str, Any]] | dict[str, Any]]


# ─── Surfaces handled by the V11 cut ──────────────────────────────────
SURFACE_CHILLER_LWT = "chiller_lwt"
SURFACE_CT_FAN_VFD = "ct_fan_vfd"

VALID_SURFACES: frozenset[str] = frozenset({SURFACE_CHILLER_LWT, SURFACE_CT_FAN_VFD})


# ─── Tunable thresholds (rule-based, ADR-006 transparency) ────────────
class OptimizerConfig:
    """Control-law thresholds for the proactive PUE/WUE Optimizer.

    Toronto-baseline calibration assumptions (per engram §11)
    ---------------------------------------------------------
    The A3-Alpha Toronto Area facility is sited in **North York, Toronto
    (Ontario)**. The thresholds below are calibrated to Toronto's
    ASHRAE climate file (CSA/ASHRAE Climate Zone 6A — humid continental,
    cold winters / mild humid summers):

      * Summer design wet-bulb peak ≈ 22-23 °C (1 % cooling).
      * Summer design dry-bulb peak ≈ 30-32 °C.
      * Annualised wet-bulb mean ≈ 8-10 °C.

    These drive the cooling-tower approach + chiller LWT band choices.
    A facility in a hotter climate (e.g., Phoenix) would need looser
    LWT bounds + a tighter CT approach headroom — the constants here
    are defaults, not invariants.

    Per-threshold rationale
    -----------------------
      PUE_DRIFT_THRESHOLD = 0.02
          0.02 above target (`config/pue_targets.yml` Phase 1 = 1.30)
          fires the sustain detector. Tighter (0.01) is noisy in
          Toronto's variable summer humidity; looser (0.05) lets the
          PUE drift well into the warn band before acting.

      PUE_SUSTAIN_TICKS = 10
          ~5 min at the 30 s tick. Prevents firing on a single high-
          PUE sample (e.g., a brief chiller staging transient) while
          still responding within an operator-comfortable window.

      LWT_FLOOR_C = 6.0
          Chiller minimum LWT — below this the chiller flags out per
          mfr (Schneider Galaxy VX + York YZ rated for 6 °C floor).
          Toronto's design wet-bulb does not call for sub-6 °C LWT.

      LWT_STEP_C = 0.5
          Conservative 0.5 K steps; matches typical operator-issued
          chiller LWT trim sizes. Larger steps risk hunting.

      LWT_HALL_INLET_GUARD_C = 20.0
          ASHRAE A2 lower comfort band is 18 °C. If the hall is
          already < 20 °C, lowering LWT wastes compressor work.

      CT_APPROACH_FLOOR_K = 2.0
          Below 2 K approach the tower is saturated and additional
          fan VFD does nothing for ECWT.

      CT_APPROACH_HEADROOM_K = 5.0
          For Toronto's mild summer wet-bulb (rarely > 23 °C), a
          5 K headroom means the tower is genuinely underutilised
          and pushing the fan VFD up will move ECWT downward.

      CT_VFD_STEP_PCT = 5.0
          Conservative 5 % VFD trims; ramps the fan up gradually so
          mechanical wear + bearing temperature do not spike.

      PACING_SECONDS = 15 * 60
          Oscillation guard — at most one proposal per surface per
          15 minutes. Surfaces a proposal at most every 15 min even
          if drift sustains across multiple windows.

      LOOP_TICK_SECONDS = 30.0
          30 s tick aligns with the Hermes telemetry stream cadence
          (the 60 s mean-z window emits an actionable Z-score about
          every other tick).

    These are *defaults*, not invariants. Empirical recalibration
    against live telemetry happens in V11+ as Optimizer runtime data
    accumulates.
    """

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
AUDIT_TICK = "tick"                                       # E5.A heartbeat marker


# ─── E5.E — What-If sandbox projection (pure, S-DET-01) ───────────────
PREVIEW_VERDICT_GREEN = "green"     # within tolerance, safe to approve
PREVIEW_VERDICT_AMBER = "amber"     # marginal, operator should review
PREVIEW_VERDICT_RED = "red"         # projected breach, do not approve

# ASHRAE A2 inlet band for IT racks. The "warm" boundary (35 C) is the
# spec ceiling; tolerance ramp begins at 27 C (TC9.9 recommended).
ASHRAE_A2_INLET_WARN_C = 27.0
ASHRAE_A2_INLET_BREACH_C = 35.0

# Rule-of-thumb coefficients — first-principles enough for the operator
# preview, NOT a learned model. The deterministic-sandbox doctrine
# (ADR-006 / S-DET-01) forbids an LLM from refining these numbers.
#
# Sign convention: every coefficient is signed so the formula is
# uniform across surfaces — ``dQuantity = proposal.delta * coeff``.
# A signed delta times a signed coefficient yields the correctly-signed
# projection.
#
#   chiller LWT: a 1 K drop in LWT (delta=-1) trims PUE by 0.006
#                (dPUE=-0.006) at constant load (compressor head
#                pressure), and pulls rack inlet down by ~0.4 K
#                (dInlet=-0.4). Sign convention -> both coeffs are
#                positive: dPUE = delta * (+0.006).
#   CT fan VFD : a +1 % step (delta=+1) reduces ECWT, trimming
#                compressor work for ~0.001 PUE drop per step
#                (dPUE=-0.001). WUE rises ~0.005 L/kWh per step
#                (more evaporative makeup). Sign convention -> PUE
#                coeff negative, WUE coeff positive.
_PREVIEW_COEFFS = {
    SURFACE_CHILLER_LWT: {
        "pue_per_k": 0.006,          # dPUE per K of LWT change (signed)
        "wue_per_k": 0.000,          # LWT trim doesn't change makeup
        "inlet_per_k": 0.4,          # dInlet per K of LWT change
    },
    SURFACE_CT_FAN_VFD: {
        "pue_per_pct": -0.001,       # dPUE per 1% VFD change (signed)
        "wue_per_pct": 0.005,        # dWUE per 1% VFD change (signed)
        "inlet_per_pct": 0.0,        # second-order; ignored at this fidelity
    },
}


@dataclass(frozen=True)
class PreviewProjection:
    """Outcome of :func:`simulate_setpoint_impact`. Pure data — no LLM
    refinement, no telemetry-source attribution beyond what the caller
    supplied via :class:`TelemetryPoint`."""

    proposal_id: str
    surface: str
    current_value: float
    proposed_value: float
    delta: float
    projected_pue: float | None
    projected_pue_delta: float | None
    projected_wue_delta: float | None
    projected_inlet_c: float | None
    projected_inlet_delta_c: float | None
    ashrae_distance_c: float | None
    verdict: str                    # green / amber / red
    findings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def simulate_setpoint_impact(
    proposal: Proposal,
    point: TelemetryPoint | None,
    pue_target: float = 1.30,
) -> PreviewProjection:
    """Project the PUE / WUE / ASHRAE-distance impact of approving
    ``proposal`` against the current telemetry ``point``. Pure-Python,
    deterministic, side-effect free.

    Harness #21 and S-DET-01 / ADR-006: NO LLM call lives on this path.
    The operator preview is computed by the same rule-based coefficients
    that justify the proposal in the first place — an LLM-refined
    projection would erode the deterministic-sandbox guarantee.

    The verdict bands:
      * ``green`` — projected inlet stays below the ASHRAE A2 warn
        threshold (27 C) AND projected PUE is at or below target.
      * ``amber`` — projected inlet inside the warn band [27, 35) C
        OR projected PUE still above target by less than 0.02.
      * ``red``  — projected inlet >= 35 C (A2 breach) OR projected
        PUE worse than current by any margin (the proposal is making
        things worse — an arithmetic sign error somewhere upstream).

    ``point`` may be ``None`` — in that case the projection returns the
    proposal in shape, with ``verdict="amber"`` and a finding explaining
    that the live telemetry is missing.
    """
    findings: list[str] = []
    if point is None or point.pue is None:
        findings.append(
            "live telemetry unavailable; projection limited to proposal shape",
        )
        return PreviewProjection(
            proposal_id=proposal.proposal_id,
            surface=proposal.surface,
            current_value=proposal.current_value,
            proposed_value=proposal.proposed_value,
            delta=proposal.delta,
            projected_pue=None,
            projected_pue_delta=None,
            projected_wue_delta=None,
            projected_inlet_c=None,
            projected_inlet_delta_c=None,
            ashrae_distance_c=None,
            verdict=PREVIEW_VERDICT_AMBER,
            findings=findings,
        )

    surface = proposal.surface
    coeffs = _PREVIEW_COEFFS.get(surface)
    if coeffs is None:
        findings.append(f"no preview coefficients for surface={surface!r}")
        return PreviewProjection(
            proposal_id=proposal.proposal_id,
            surface=surface,
            current_value=proposal.current_value,
            proposed_value=proposal.proposed_value,
            delta=proposal.delta,
            projected_pue=point.pue,
            projected_pue_delta=0.0,
            projected_wue_delta=0.0,
            projected_inlet_c=point.hall_temp_c,
            projected_inlet_delta_c=0.0,
            ashrae_distance_c=(
                ASHRAE_A2_INLET_BREACH_C - point.hall_temp_c
                if point.hall_temp_c is not None else None
            ),
            verdict=PREVIEW_VERDICT_AMBER,
            findings=findings,
        )

    # Uniform formula: dQuantity = signed delta * signed coeff.
    # The coefficients differ per surface (per-K vs per-pct units).
    if surface == SURFACE_CHILLER_LWT:
        pue_delta = proposal.delta * coeffs["pue_per_k"]
        wue_delta = proposal.delta * coeffs["wue_per_k"]
        inlet_delta = proposal.delta * coeffs["inlet_per_k"]
    elif surface == SURFACE_CT_FAN_VFD:
        pue_delta = proposal.delta * coeffs["pue_per_pct"]
        wue_delta = proposal.delta * coeffs["wue_per_pct"]
        inlet_delta = proposal.delta * coeffs["inlet_per_pct"]
    else:
        pue_delta = 0.0
        wue_delta = 0.0
        inlet_delta = 0.0

    projected_pue = point.pue + pue_delta
    projected_inlet = (
        point.hall_temp_c + inlet_delta if point.hall_temp_c is not None
        else None
    )
    ashrae_distance = (
        ASHRAE_A2_INLET_BREACH_C - projected_inlet
        if projected_inlet is not None else None
    )

    # Verdict logic — three independent failure modes collapse into red.
    verdict = PREVIEW_VERDICT_GREEN
    if projected_inlet is not None and projected_inlet >= ASHRAE_A2_INLET_BREACH_C:
        verdict = PREVIEW_VERDICT_RED
        findings.append(
            f"projected hall inlet {projected_inlet:.2f} C >= A2 breach "
            f"{ASHRAE_A2_INLET_BREACH_C:.1f} C"
        )
    elif pue_delta > 0:
        # Proposal makes PUE WORSE — coefficient sign disagrees with
        # control law intent. Refuse rather than ship the wrong-way trim.
        verdict = PREVIEW_VERDICT_RED
        findings.append(
            f"projected PUE delta {pue_delta:+.3f} (worsens vs current)"
        )
    elif projected_inlet is not None and projected_inlet >= ASHRAE_A2_INLET_WARN_C:
        verdict = PREVIEW_VERDICT_AMBER
        findings.append(
            f"projected hall inlet {projected_inlet:.2f} C in A2 warn band "
            f"[{ASHRAE_A2_INLET_WARN_C:.1f}, {ASHRAE_A2_INLET_BREACH_C:.1f}) C"
        )
    elif projected_pue > pue_target + 0.02:
        verdict = PREVIEW_VERDICT_AMBER
        findings.append(
            f"projected PUE {projected_pue:.3f} still > target+0.02 "
            f"({pue_target + 0.02:.3f})"
        )
    else:
        findings.append(
            f"projected PUE {projected_pue:.3f} <= target+0.02 and inlet within "
            f"ASHRAE A2 recommended band"
        )

    return PreviewProjection(
        proposal_id=proposal.proposal_id,
        surface=surface,
        current_value=proposal.current_value,
        proposed_value=proposal.proposed_value,
        delta=proposal.delta,
        projected_pue=projected_pue,
        projected_pue_delta=pue_delta,
        projected_wue_delta=wue_delta,
        projected_inlet_c=projected_inlet,
        projected_inlet_delta_c=inlet_delta,
        ashrae_distance_c=ashrae_distance,
        verdict=verdict,
        findings=findings,
    )


# ─── E5.C helper: per-agent breakdown extraction ──────────────────────
def _extract_agent_verdicts(consensus: Any) -> list[dict[str, Any]]:
    """Extract the per-agent voting breakdown from a ConsensusResult.

    Returns a list of ``{agent_name, verdict, summary}`` dicts — one per
    agent. Empty list when the consult was not wired (``None``) or the
    result carries no ``agents`` attribute / iterable. Duck-typed on the
    multi_agent.AgentVerdict shape so a mock or partial implementation
    stays compatible.
    """
    if consensus is None:
        return []
    agents = getattr(consensus, "agents", None)
    if not agents:
        return []
    out: list[dict[str, Any]] = []
    for a in agents:
        try:
            out.append({
                "agent_name": str(getattr(a, "agent_name", "") or ""),
                "verdict": str(getattr(a, "verdict", "") or ""),
                "summary": str(getattr(a, "summary", "") or ""),
            })
        except Exception:
            # A malformed agent entry should not poison the queue —
            # skip it and surface what we can.
            continue
    return out


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


# ─── Proposal queue (2.B — in-memory; persistent table in 2.C) ──────
@dataclass(frozen=True)
class QueuedProposal:
    """A proposal that has cleared the consensus gate and is awaiting
    operator review. Carries the multi-agent consensus + the Optimizer's
    own advisory narrative. ADR-006: the consensus verdict is the
    deterministic gate; the narrative is informational only.

    Epic 5.C (Observability): ``agent_verdicts`` carries the per-agent
    breakdown from the multi-agent consensus chain — one dict per agent
    with ``agent_name`` + ``verdict`` + ``summary`` so the HMI can
    surface each individual vote without re-querying the orchestrator.
    Empty list when no consult was wired or the consult returned
    ``None``. The Safety Officer's row is the load-bearing one — its
    ``hard_stop`` is the uncrossable veto (S-DET-02).
    """

    proposal: Proposal
    consensus_verdict: str | None       # None when consult_fn not wired
    consensus_rationale: str
    safety_officer_veto: bool
    optimizer_narrative: str
    queued_at: float
    agent_verdicts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["proposal"] = self.proposal.to_dict()
        return d


class ProposalQueue:
    """Bounded in-memory queue of proposals awaiting operator approval.

    2.C will swap this for a PostgreSQL-backed table joined to the audit
    log + the operator-approval rows by ``proposal_id``. The interface
    is shaped so 2.C is a drop-in swap (enqueue / list / pop_by_id /
    size / clear).
    """

    def __init__(self, max_entries: int = 200):
        self._items: list[QueuedProposal] = []
        self._max = max(1, int(max_entries))

    def enqueue(self, qp: QueuedProposal) -> None:
        self._items.append(qp)
        if len(self._items) > self._max:
            # Drop oldest — keep a sliding window
            self._items = self._items[-self._max:]

    def list(self, limit: int = 50) -> list[QueuedProposal]:
        return list(self._items[-max(0, int(limit)):])

    def pop_by_id(self, proposal_id: str) -> QueuedProposal | None:
        for i, qp in enumerate(self._items):
            if qp.proposal.proposal_id == proposal_id:
                return self._items.pop(i)
        return None

    def size(self) -> int:
        return len(self._items)

    def clear(self) -> None:
        self._items.clear()


# ─── Optimizer service (2.A core + 2.B consensus / queue / Hermes) ──
TelemetryProvider = Callable[[], Awaitable[TelemetryPoint | None] | TelemetryPoint | None]


class OptimizerService:
    """The proactive edge-agent (Batches 2.A + 2.B).

    Per the Epic 2 brief and ADR-006:
      * computes proposal values deterministically (``compute_proposal``);
      * has NO actor_role — cannot call /api/bms/write;
      * routes every proposal through ``consult_fn`` (the multi-agent
        consensus chain); a Safety Officer ``hard_stop`` discards the
        proposal — audit-logged, never queued, never emitted (S-DET-02);
      * synthesizes an advisory narrative via Gemma AFTER the proposal
        value is fixed (S-DET-01 / S-DET-03);
      * emits ``optimizer-proposal`` events via the injected emitter for
        the HMI to subscribe to (the Hermes adapter is wired in main.py);
      * 2.C will wire approve/reject endpoints + persistent audit.
    """

    def __init__(
        self,
        telemetry_provider: TelemetryProvider | None = None,
        pue_target: float = 1.30,
        cfg: type[OptimizerConfig] = OptimizerConfig,
        # 2.B dependency-injection seams (all default None for back-compat).
        consult_fn: ConsultFn | None = None,
        llm_client: Any | None = None,
        kalman_provider: KalmanProvider | None = None,
        event_emitter: EventEmitter | None = None,
    ):
        self._telemetry = telemetry_provider
        self._pue_target = float(pue_target)
        self._cfg = cfg
        self._drift = DriftTracker(cfg.PUE_SUSTAIN_TICKS)
        self._pacing = PacingGuard(cfg.PACING_SECONDS)
        self._audit = AuditLog()
        # 2.B: in-memory proposal queue + DI seams.
        self._queue = ProposalQueue()
        self._consult_fn = consult_fn
        self._llm_client = llm_client
        self._kalman_provider = kalman_provider
        self._event_emitter = event_emitter
        self._task: asyncio.Task[None] | None = None
        self._running = False
        # E5.A (Observability heartbeat): wall-clock + structured outcome
        # of the most recent tick — surfaced by ``health()`` and emitted
        # as a ``hermes:optimizer-tick`` event so the HMI strip stays
        # live without polling.
        self._last_tick_unix: float = 0.0
        self._last_tick_outcomes: dict[str, Any] = {}
        self._tick_count: int = 0

    @property
    def audit(self) -> AuditLog:
        return self._audit

    @property
    def queue(self) -> ProposalQueue:
        return self._queue

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_tick_unix(self) -> float:
        """Wall-clock timestamp of the most recent ``tick()`` start.
        Zero until the first tick fires. E5.A heartbeat surface."""
        return self._last_tick_unix

    @property
    def last_tick_outcomes(self) -> dict[str, Any]:
        """Structured summary of the most recent tick:
        ``{sustained, drift, n_proposals, n_paced_out, n_vetoed,
        surfaces_emitted, surfaces_vetoed}``. Empty until the first
        tick fires. E5.A heartbeat surface."""
        return dict(self._last_tick_outcomes)

    @property
    def tick_count(self) -> int:
        """Monotonic count of completed ticks since service start."""
        return self._tick_count

    def health(self) -> dict[str, Any]:
        """E5.A — operator-facing health snapshot. Cheap, side-effect
        free, safe to call from a public endpoint at any time.

        Returns:
            {
                "is_running": bool,
                "pue_target": float,
                "last_tick_unix": float,
                "tick_count": int,
                "last_tick_outcomes": {...},
                "queue_size": int,
                "audit_recent": [...]  (last 10 entries),
            }
        """
        return {
            "is_running": self._running,
            "pue_target": self._pue_target,
            "last_tick_unix": self._last_tick_unix,
            "tick_count": self._tick_count,
            "last_tick_outcomes": dict(self._last_tick_outcomes),
            "queue_size": self._queue.size(),
            "audit_recent": [
                e.to_dict() for e in self._audit.entries(limit=10)
            ],
        }

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
        """One control-loop tick. Returns the proposals that cleared the
        consensus gate this tick (a Safety hard_stop drops the proposal).

        ADR-006 invariants (audited at every code change):
          * ``compute_proposal`` is pure-Python; no LLM call there.
          * No ``/api/bms/write`` is invoked from this method or its callees.

        E5.A (Observability): every tick records its wall-clock + a
        structured outcome summary, then emits a ``hermes:optimizer-tick``
        event so the HMI heartbeat strip updates live.
        """
        # E5.A — record the tick attempt up-front so a downstream early-
        # return still shows a fresh wall-clock to the operator.
        self._last_tick_unix = time.time()
        self._tick_count += 1
        outcomes: dict[str, Any] = {
            "sustained": False,
            "drift": None,
            "n_proposals": 0,
            "n_paced_out": 0,
            "n_vetoed": 0,
            "surfaces_emitted": [],
            "surfaces_vetoed": [],
            "telemetry_present": False,
        }

        try:
            point = await self._read_telemetry()
            if point is None:
                return []
            outcomes["telemetry_present"] = True

            drift = pue_drift(point, self._pue_target)
            outcomes["drift"] = drift
            sustained = self._drift.update(drift, self._cfg.PUE_DRIFT_THRESHOLD)
            outcomes["sustained"] = sustained
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
                    outcomes["n_paced_out"] += 1
                    continue
                proposal = compute_proposal(surface, point, self._pue_target, self._cfg)
                if proposal is None:
                    continue

                # 2.B: consult the multi-agent consensus chain BEFORE queueing.
                # The Safety Officer's HARD_STOP veto is uncrossable (S-DET-02).
                consensus = await self._consult_consensus(proposal)
                if (consensus is not None
                        and getattr(consensus, "consensus", None) == VERDICT_HARD_STOP):
                    self._audit.write(
                        AUDIT_SAFETY_VETO,
                        proposal_id=proposal.proposal_id,
                        surface=surface,
                        detail=getattr(consensus, "rationale", "") or "consensus hard_stop",
                    )
                    self._pacing.record(surface)   # still paces — don't re-flood vetoed surface
                    outcomes["n_vetoed"] += 1
                    outcomes["surfaces_vetoed"].append(surface)
                    continue

                # 2.B: synthesize the Optimizer's own advisory narrative
                # (S-DET-03 — T3.3 narrative-helper pattern). Verdict and
                # proposed value are already decided.
                narrative = await self._synthesize_narrative(proposal, consensus)

                # E5.C — extract the per-agent breakdown so it survives
                # the roll-up into ConsensusResult.
                agent_verdicts = _extract_agent_verdicts(consensus)

                queued = QueuedProposal(
                    proposal=proposal,
                    consensus_verdict=(
                        getattr(consensus, "consensus", None) if consensus is not None
                        else None
                    ),
                    consensus_rationale=(
                        getattr(consensus, "rationale", "") if consensus is not None
                        else ""
                    ),
                    safety_officer_veto=bool(
                        getattr(consensus, "safety_officer_veto", False)
                    ) if consensus is not None else False,
                    optimizer_narrative=narrative,
                    queued_at=time.time(),
                    agent_verdicts=agent_verdicts,
                )
                self._queue.enqueue(queued)
                self._audit.write(
                    AUDIT_PROPOSED,
                    proposal_id=proposal.proposal_id,
                    surface=surface,
                    detail=proposal.rationale,
                )
                self._pacing.record(surface)
                await self._emit_event(
                    "optimizer-proposal",
                    {
                        "proposal": proposal.to_dict(),
                        "consensus_verdict": queued.consensus_verdict,
                        "safety_officer_veto": queued.safety_officer_veto,
                        "agent_verdicts": queued.agent_verdicts,
                        "narrative_present": bool(narrative),
                    },
                )
                emitted.append(proposal)
                outcomes["n_proposals"] += 1
                outcomes["surfaces_emitted"].append(surface)
            return emitted
        finally:
            # E5.A — always persist + broadcast the heartbeat, even on
            # an early return. The HMI strip needs a fresh timestamp on
            # every tick to prove the loop is alive.
            self._last_tick_outcomes = outcomes
            self._audit.write(
                AUDIT_TICK,
                detail=(
                    f"tick #{self._tick_count}: "
                    f"sustained={outcomes['sustained']}, "
                    f"proposals={outcomes['n_proposals']}, "
                    f"paced_out={outcomes['n_paced_out']}, "
                    f"vetoed={outcomes['n_vetoed']}"
                ),
            )
            await self._emit_event(
                "optimizer-tick",
                {
                    "tick_unix": self._last_tick_unix,
                    "tick_count": self._tick_count,
                    "outcomes": outcomes,
                    "queue_size": self._queue.size(),
                    "is_running": self._running,
                },
            )

    # ── 2.B: multi-agent consensus integration (S-DET-02) ────────────
    async def _consult_consensus(self, proposal: Proposal) -> Any:
        """Route a proposal through the multi-agent consensus chain.

        Returns the ConsensusResult (duck-typed) on success, ``None`` if
        no consult_fn is wired or if the consult raised. A ``None``
        return is treated as "no consensus" downstream — the proposal
        still proceeds; the operator approval step (2.C) becomes the
        only gate. Per S-DET-02 a real ``hard_stop`` IS terminal.
        """
        if self._consult_fn is None:
            return None
        ctx = ConsultContext(
            query=(
                f"Optimizer proposes {proposal.surface}: "
                f"{proposal.current_value:.2f} -> {proposal.proposed_value:.2f} "
                f"(delta {proposal.delta:+.2f}). {proposal.rationale}"
            ),
            asset_id=proposal.surface,
            cet_id="optimizer",
        )
        try:
            return await self._consult_fn(ctx)
        except Exception as e:
            log.debug("[optimizer] consult_fn failed: %s", e)
            return None

    # ── 2.B: advisory Gemma narrative (S-DET-01 / S-DET-03) ──────────
    async def _collect_top_kalman_lines(self, top_n: int = 4) -> list[str]:
        """Render top-N anomalous Kalman channels as Z-score lines.

        Best-effort: provider failure / empty payload yields ``[]``.
        Differs from multi_agent._collect_kalman_lines in that the
        Optimizer's framing is site-wide (no asset scope) — it's
        proposing a setpoint class, not asset-specific work.
        """
        if self._kalman_provider is None:
            return []
        try:
            payload = self._kalman_provider()
            if asyncio.iscoroutine(payload):
                payload = await payload
        except Exception as e:
            log.debug("[optimizer] kalman read failed: %s", e)
            return []
        if not isinstance(payload, dict) or not payload:
            return []

        def _maxz(ch: str) -> float:
            try:
                return float(payload.get(ch, {}).get("max_z", 0.0) or 0.0)
            except (TypeError, ValueError, AttributeError):
                return 0.0

        lines: list[str] = []
        for ch in sorted(payload, key=_maxz, reverse=True)[:top_n]:
            f = payload[ch]
            flag = " ANOMALOUS" if f.get("is_anomalous") else ""
            mean_z = 0.0
            with contextlib.suppress(TypeError, ValueError):
                mean_z = float(f.get("mean_z", 0.0) or 0.0)
            lines.append(f"  {ch}: max_z={_maxz(ch):.2f} mean_z={mean_z:.2f}{flag}")
        return lines

    async def _synthesize_narrative(
        self,
        proposal: Proposal,
        consensus: Any,
    ) -> str:
        """Build the Optimizer's Gemma prompt and call the model.

        ADR-006: advisory ONLY. ``proposal.proposed_value`` is already
        fixed by ``compute_proposal``; the prompt forbids the model
        from overriding it or inventing values.
        """
        if self._llm_client is None or not hasattr(self._llm_client, "complete_gemma"):
            return ""
        kalman_lines = await self._collect_top_kalman_lines()
        kalman_block = (
            "\n".join(kalman_lines) if kalman_lines
            else "  (live Kalman tap unavailable this tick)"
        )
        cons_line = (
            "(consult not wired)" if consensus is None
            else f"{getattr(consensus, 'consensus', 'unknown')} - "
                 f"{getattr(consensus, 'rationale', '')}"
        )
        prompt = (
            "You are the Optimizer agent of a Tier IV AI-factory operations "
            "platform, responsible for proactive PUE/WUE setpoint proposals. "
            "In 2-3 sentences give an advisory narrative for the proposal "
            "below: justify the value choice and the expected delta. Ground "
            "every claim strictly in the data provided; do not invent "
            "values. Be concise and factual.\n\n"
            f"SURFACE: {proposal.surface}\n"
            f"DETERMINISTIC PROPOSAL (already decided, do not override): "
            f"{proposal.current_value:.2f} -> {proposal.proposed_value:.2f} "
            f"(delta {proposal.delta:+.2f})\n"
            f"RATIONALE: {proposal.rationale}\n"
            f"PUE AT EMISSION: {proposal.pue_at_emission}\n"
            f"MULTI-AGENT CONSENSUS: {cons_line}\n"
            "LIVE KALMAN TELEMETRY (Z-score; |z|>=3 is a statistical anomaly):\n"
            f"{kalman_block}\n"
        )
        try:
            text = await self._llm_client.complete_gemma(prompt, max_tokens=240)
        except Exception as e:
            log.debug("[optimizer] Gemma synthesis failed: %s", e)
            return ""
        text = (text or "").strip()
        if not text or text.startswith(("[Gemma error", "[Gemma stream error")):
            return ""
        return text

    # ── 2.B: Hermes event emission ───────────────────────────────────
    async def _emit_event(self, event: str, payload: dict[str, Any]) -> None:
        """Best-effort event publication. Failures are logged + swallowed."""
        if self._event_emitter is None:
            return
        try:
            result = self._event_emitter(event, payload)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            log.debug("[optimizer] event emit failed: %s", e)

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
    consult_fn: ConsultFn | None = None,
    llm_client: Any | None = None,
    kalman_provider: KalmanProvider | None = None,
    event_emitter: EventEmitter | None = None,
) -> OptimizerService | None:
    """Return the singleton when the env flag is set; ``None`` otherwise.

    Per S-DET-01 / S-SEC-02: this function never touches the BMS write
    path. The returned service emits proposals to its in-memory queue
    + audit log; the multi-agent consult and the optional Gemma
    narrative + event emission are routed through the injected
    callbacks. The approve/reject endpoints (issuing the actual BMS
    write under SME_L6 RBAC) arrive in Batch 2.C — they are NOT
    reachable from this module.
    """
    if not is_enabled():
        return None
    global _service
    if _service is None:
        _service = OptimizerService(
            telemetry_provider=telemetry_provider,
            pue_target=pue_target,
            consult_fn=consult_fn,
            llm_client=llm_client,
            kalman_provider=kalman_provider,
            event_emitter=event_emitter,
        )
        log.info(
            "[optimizer] service initialised "
            "(2.A control law + 2.B consensus/queue/narrative; "
            "consult=%s, llm=%s, kalman=%s, emitter=%s)",
            consult_fn is not None, llm_client is not None,
            kalman_provider is not None, event_emitter is not None,
        )
    return _service


def reset_service() -> None:
    """Test helper — drop the singleton so the next ``get_service`` rebuilds."""
    global _service
    _service = None
