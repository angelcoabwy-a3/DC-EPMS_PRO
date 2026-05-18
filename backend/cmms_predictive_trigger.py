"""
backend/cmms_predictive_trigger.py
===================================
Sprint 9.1 — Predictive Work Order trigger from Kalman anomalies.

Closes the demo-killer end-to-end loop:

    telemetry_simulator                       (Sprint 5 C1)
        |
        v
    Kalman + SoD pipeline                     (Sprint 5 C2)
        |
        v   {ch_id: {is_anomalous, max_z, mean_z, last_emission, ...}}
        |
        v
    PredictiveTrigger.handle_payload()        (THIS MODULE)
        |   - sustain counter per channel
        |   - dedupe per asset (open WO from same trigger source)
        |   - channel_id -> asset_id lookup
        |
        v
    cmms_repository.save_work_order_async()   (Sprint 6 Fase 2)
        |
        v
    Frontend Maintenance view (polled)        (Sprint 6 Fase 5)
        |
        v
    CET sees P1/P2 WO with telemetry snapshot, approves, executes

Sustain semantics:
  - is_anomalous=true on a channel increments its consecutive counter.
  - is_anomalous=false RESETS the counter (anomaly self-cleared).
  - When counter reaches sustain_threshold (default 3 windows), the
    trigger fires and creates a WO. Counter is then reset to avoid
    duplicate WOs while the anomaly persists.
  - Dedupe is also enforced at the DB layer: if an open
    (pending_approval / approved / scheduled / in_progress) WO with
    trigger_source=predictive_kalman already exists for the asset,
    no new WO is created until that one is closed.

Hardware-aware:
  - Single-process asyncio: shared state, no locks needed.
  - Per-payload work is O(channels) = ~238 in current inventory =
    sub-millisecond.

ADR-006 Deterministic Sandbox compliance:
  - WOs always land in pending_approval.
  - CET must explicitly approve via /api/cmms/work-orders/{id}/approve.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from backend.cmms_models import WorkOrder
from backend.cmms_repository import (
    AssetNotFoundError,
    CMMSRepositoryError,
    PostgresCMMSRepository,
)

log = logging.getLogger(__name__)


# ─── Tunable parameters ────────────────────────────────────────────────
DEFAULT_SUSTAIN_THRESHOLD = 3   # consecutive anomalous windows before WO
DEFAULT_LIKELIHOOD_IDX    = 4   # 1-5 scale; predictive = "happening"
DEFAULT_CONSEQUENCE_IDX   = 4   # critical asset escalates further


# ─── Priority + class derivation (mirrors cmms_routes helpers) ─────────
def _compute_lor(likelihood: int, consequence: int) -> int:
    return max(1, min(25, likelihood * consequence))


def _derive_priority(lor: int, criticality: str) -> str:
    if lor >= 20:
        base = "P1"
    elif lor >= 12:
        base = "P2"
    elif lor >= 6:
        base = "P3"
    else:
        base = "P4"
    if criticality == "critical" and base in ("P3", "P4"):
        base = "P2"
    if criticality == "critical" and base == "P2" and lor >= 15:
        base = "P1"
    return base


def _derive_procedure_class(work_class: str, requires_loto: bool) -> str:
    if work_class == "EM":
        return "EOP"
    if requires_loto:
        return "DMOP"
    if work_class == "CM":
        return "MOP"
    return "SOP"


def _wo_id() -> str:
    return f"WO-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"


# ─── Predictive trigger state machine ──────────────────────────────────
class PredictiveTrigger:
    """Per-channel sustain tracker that emits a WO when anomaly persists.

    Single-instance pattern (managed via get_predictive_trigger() in
    this module). Holds mutable state across SSE messages within a
    single uvicorn process; no cross-process coordination today.
    """

    def __init__(
        self,
        repository: PostgresCMMSRepository,
        sustain_threshold: int = DEFAULT_SUSTAIN_THRESHOLD,
    ) -> None:
        self._repo = repository
        self.sustain_threshold = sustain_threshold

        # Per-channel rolling state
        self._sustain_counts: dict[str, int] = {}
        self._first_anomaly_at: dict[str, datetime] = {}
        self._last_metadata: dict[str, dict[str, Any]] = {}

        # Cumulative metrics (for /api/cmms/predictive/stats endpoint, V2)
        self._total_anomalies_seen = 0
        self._total_wos_created = 0
        self._total_dedup_skipped = 0

    # ── Public surface ───────────────────────────────────────────────
    async def handle_payload(self, channels_payload: dict[str, dict[str, Any]]) -> None:
        """Called once per SSE message with the channel_innovations payload.

        Updates per-channel sustain counters and triggers WO creation
        when threshold is reached. Defensive: logs and swallows
        exceptions so a trigger failure NEVER kills the SSE stream.
        """
        if not channels_payload:
            return

        for ch_id, fields in channels_payload.items():
            try:
                if fields.get("is_anomalous"):
                    self._total_anomalies_seen += 1
                    self._increment_sustain(ch_id, fields)
                    if self._sustain_counts[ch_id] >= self.sustain_threshold:
                        await self._maybe_create_wo(ch_id)
                else:
                    self._reset_sustain(ch_id)
            except Exception as e:
                log.warning("[predictive_trigger] error on %s: %s", ch_id, e)

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "sustain_threshold": self.sustain_threshold,
            "channels_tracked": len(self._sustain_counts),
            "anomalies_seen": self._total_anomalies_seen,
            "wos_created": self._total_wos_created,
            "dedup_skipped": self._total_dedup_skipped,
            "currently_sustaining": {
                ch: count
                for ch, count in self._sustain_counts.items()
                if count > 0
            },
        }

    def reset(self) -> None:
        """Test helper: clear all sustain state. Does NOT touch DB."""
        self._sustain_counts.clear()
        self._first_anomaly_at.clear()
        self._last_metadata.clear()
        self._total_anomalies_seen = 0
        self._total_wos_created = 0
        self._total_dedup_skipped = 0

    # ── Internal state mgmt ──────────────────────────────────────────
    def _increment_sustain(self, ch_id: str, fields: dict[str, Any]) -> None:
        self._last_metadata[ch_id] = dict(fields)
        if ch_id not in self._sustain_counts or self._sustain_counts[ch_id] == 0:
            # First anomalous window in this streak
            self._first_anomaly_at[ch_id] = datetime.now(UTC)
        self._sustain_counts[ch_id] = self._sustain_counts.get(ch_id, 0) + 1

    def _reset_sustain(self, ch_id: str) -> None:
        if self._sustain_counts.get(ch_id, 0) > 0:
            log.debug("[predictive_trigger] %s sustain reset (was %d)",
                      ch_id, self._sustain_counts[ch_id])
        self._sustain_counts.pop(ch_id, None)
        self._first_anomaly_at.pop(ch_id, None)
        self._last_metadata.pop(ch_id, None)

    # ── WO creation ──────────────────────────────────────────────────
    async def _maybe_create_wo(self, ch_id: str) -> None:
        """Resolve channel -> asset, dedupe, build + persist WO."""
        asset_id = self._channel_to_asset_id(ch_id)
        if not asset_id:
            log.warning("[predictive_trigger] cannot resolve asset for %s", ch_id)
            self._reset_sustain(ch_id)
            return

        # Dedupe: any existing open predictive WO for this asset?
        try:
            existing = await self._repo.list_work_orders_async(
                asset_id=asset_id,
                trigger_source="predictive_kalman",
                only_open=True,
                limit=1,
            )
            if existing:
                log.debug(
                    "[predictive_trigger] dedupe: open predictive WO %s exists for %s",
                    existing[0].work_order_id, asset_id,
                )
                self._total_dedup_skipped += 1
                # Reset sustain so we don't loop on every payload while WO is open
                self._reset_sustain(ch_id)
                return
        except CMMSRepositoryError as e:
            log.warning("[predictive_trigger] dedup query failed for %s: %s", asset_id, e)
            return

        # Resolve asset for criticality + MOP linkage
        try:
            asset = await self._repo.get_asset_async(asset_id)
        except AssetNotFoundError:
            log.warning(
                "[predictive_trigger] channel %s maps to unknown asset %s; skipping",
                ch_id, asset_id,
            )
            self._reset_sustain(ch_id)
            return
        except CMMSRepositoryError as e:
            log.warning("[predictive_trigger] asset lookup failed for %s: %s", asset_id, e)
            return

        # Build the WO
        metadata = self._last_metadata.get(ch_id, {})
        sustain = self._sustain_counts.get(ch_id, 0)
        first_at = self._first_anomaly_at.get(ch_id)
        max_z = float(metadata.get("max_z", 0.0))
        mean_z = float(metadata.get("mean_z", 0.0))
        last_em = float(metadata.get("last_emission", 0.0))

        # Predictive WOs default to CM (corrective). LOTO inferred from
        # asset_type: any energized component (ups, ats, transformer, etc.)
        # implies LOTO is needed for hands-on diagnosis.
        requires_loto = asset.asset_type in (
            "ups", "ats", "transformer", "switchgear", "rpp",
            "busway", "rectifier",
        )

        lor = _compute_lor(DEFAULT_LIKELIHOOD_IDX, DEFAULT_CONSEQUENCE_IDX)
        priority = _derive_priority(lor, asset.criticality_class)
        proc_class = _derive_procedure_class("CM", requires_loto)

        metric = ch_id.split(":", 1)[1] if ":" in ch_id else "unknown"
        issue = (
            f"Predictive anomaly: {metric} on {asset_id} max_z={max_z:.2f} "
            f"sustained {sustain} windows (>= {self.sustain_threshold} threshold). "
            f"Last emission: {last_em:.3f}."
        )

        now = datetime.now(UTC)
        wo = WorkOrder(
            work_order_id=_wo_id(),
            timestamp=now,
            asset_id=asset_id,
            asset_type_at_creation=asset.asset_type,
            work_class="CM",
            lor=lor,
            procedure_class=proc_class,
            linked_mop_id=asset.linked_mop_id,
            linked_loto_audit_id=None,
            trigger_source="predictive_kalman",
            predictive_metadata={
                "channel_id": ch_id,
                "metric": metric,
                "max_z": max_z,
                "mean_z": mean_z,
                "sustain_count": sustain,
                "sustain_threshold": self.sustain_threshold,
                "first_anomaly_at": first_at.isoformat() if first_at else None,
                "last_emission": last_em,
                "asset_criticality": asset.criticality_class,
                "anomaly_z_threshold": 3.0,  # cyber_physical_tools default
            },
            issue_summary=issue,
            estimated_cost_usd=0.0,
            requires_loto=requires_loto,
            requires_oem_specialist=False,
            status="pending_approval",
            priority=priority,
            telemetry_snapshot_json={
                "channel_id": ch_id,
                "snapshot_taken_at": now.isoformat(),
                "last_emission": last_em,
                "max_z": max_z,
                "mean_z": mean_z,
                "sustained_for_windows": sustain,
                "n_emissions_last_window": int(metadata.get("n_emissions", 0)),
            },
            mop_resolution_method="hardcoded" if asset.linked_mop_id else None,
            requested_by="predictive_trigger",
            draft_json={
                "lor": lor,
                "lor_breakdown": {
                    "likelihood_idx": DEFAULT_LIKELIHOOD_IDX,
                    "consequence_idx": DEFAULT_CONSEQUENCE_IDX,
                    "asset_criticality": asset.criticality_class,
                    "trigger_basis": "kalman_z_score_sustained",
                },
                "linked_mop_id": asset.linked_mop_id,
                "procedure_class": proc_class,
                "issue_summary": issue,
                "auto_generated": True,
            },
        )

        try:
            await self._repo.save_work_order_async(wo)
            self._total_wos_created += 1
            log.info(
                "[predictive_trigger] WO %s created: asset=%s priority=%s "
                "max_z=%.2f sustain=%d",
                wo.work_order_id, asset_id, priority, max_z, sustain,
            )
        except CMMSRepositoryError as e:
            log.error("[predictive_trigger] WO save failed for %s: %s", asset_id, e)
            return

        # Reset sustain so we don't fire again until the dedup window
        # opens (i.e., the existing WO is closed).
        self._reset_sustain(ch_id)

    # ── Channel -> asset resolution ──────────────────────────────────
    @staticmethod
    def _channel_to_asset_id(ch_id: str) -> str | None:
        """Channel IDs are scoped '<asset_id>:<metric>' by simulator
        convention. Split on first colon."""
        if ":" not in ch_id:
            return None
        asset_id = ch_id.split(":", 1)[0].strip()
        return asset_id or None


# ─── Module-level singleton ────────────────────────────────────────────
_trigger: PredictiveTrigger | None = None


def get_predictive_trigger(
    repository: PostgresCMMSRepository | None = None,
    sustain_threshold: int = DEFAULT_SUSTAIN_THRESHOLD,
) -> PredictiveTrigger:
    """Lazy singleton. First call must pass repository."""
    global _trigger
    if _trigger is None:
        if repository is None:
            raise RuntimeError(
                "predictive_trigger not initialized; "
                "first call must pass repository"
            )
        _trigger = PredictiveTrigger(repository, sustain_threshold=sustain_threshold)
        log.info(
            "[predictive_trigger] initialized (sustain_threshold=%d)",
            sustain_threshold,
        )
    return _trigger


def reset_predictive_trigger() -> None:
    """Test helper — discard the singleton."""
    global _trigger
    _trigger = None
