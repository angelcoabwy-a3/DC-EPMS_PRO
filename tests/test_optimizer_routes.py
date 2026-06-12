"""Tests for backend.optimizer_routes — Epic 2 Batch 2.C.

Coverage:
  * GET  /api/optimizer/proposals    — lists the queue.
  * GET  /api/optimizer/approvals/{} — fetches an operator decision.
  * GET  /api/optimizer/approvals    — lists recent decisions.
  * POST /api/optimizer/approve/{}   — happy path + RBAC 403 + missing
    actor_role + missing confirm_ashrae + 404 unknown id + 422 unknown
    surface + 409 safety veto + BMS-write-failure path.
  * POST /api/optimizer/reject/{}    — happy path + 403 + 404 +
    empty-reason (422 from Pydantic).
  * ApprovalLog capacity sliding window.
  * The Optimizer's NO-DIRECT-BMS-CALL invariant carried into 2.C:
    when the operator approves a proposal, the route handler — NOT
    backend.optimizer — is what calls bms_write_fn. (Asserted by
    inspecting that the optimizer service has no field that points
    at bms_write_fn or this routes module.)
"""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.optimizer import (
    SURFACE_CHILLER_LWT,
    SURFACE_CT_FAN_VFD,
    OptimizerConfig,
    OptimizerService,
    Proposal,
    QueuedProposal,
)
from backend.optimizer_routes import (
    DECISION_APPROVED,
    DECISION_REJECTED,
    SURFACE_TO_BMS_TAG,
    ApprovalLog,
    OptimizerApproval,
    register_optimizer_routes,
)


# ─── Test fixtures ────────────────────────────────────────────────────
def _make_queued(
    proposal_id: str = "qp-1",
    surface: str = SURFACE_CHILLER_LWT,
    veto: bool = False,
) -> QueuedProposal:
    return QueuedProposal(
        proposal=Proposal(
            proposal_id=proposal_id,
            surface=surface,
            current_value=7.5,
            proposed_value=7.0,
            delta=-0.5,
            rationale="test rationale",
            pue_at_emission=1.35,
            created_at=time.time(),
        ),
        consensus_verdict="approve",
        consensus_rationale="all good",
        safety_officer_veto=veto,
        optimizer_narrative="lowering LWT to reduce compressor load",
        queued_at=time.time(),
    )


@pytest.fixture
def stack():
    """Build a minimal FastAPI app wired to a fresh OptimizerService
    and an in-memory ApprovalLog. Returns (client, svc, bms_calls, app).

    bms_calls is the recording stub for the BMS write seam — every
    approval that reaches BMS write appends a row here.
    """
    bms_calls: list[dict] = []

    def fake_bms_write(tag_id, value, user):
        bms_calls.append({"tag_id": tag_id, "value": value, "user": user})
        return True, f"wrote {value} to {tag_id}"

    app = FastAPI()
    svc = OptimizerService(
        telemetry_provider=None,
        pue_target=1.30,
        cfg=OptimizerConfig,
    )
    register_optimizer_routes(app, bms_write_fn=fake_bms_write)
    app.state.optimizer_service = svc
    return TestClient(app), svc, bms_calls, app


# ─── GET /proposals ───────────────────────────────────────────────────
class TestListProposals:
    def test_empty_queue(self, stack):
        client, _svc, _bms, _app = stack
        r = client.get("/api/optimizer/proposals")
        assert r.status_code == 200
        assert r.json() == {"proposals": [], "queue_size": 0}

    def test_lists_queued_proposals(self, stack):
        client, svc, _bms, _app = stack
        svc.queue.enqueue(_make_queued("a"))
        svc.queue.enqueue(_make_queued("b", surface=SURFACE_CT_FAN_VFD))
        r = client.get("/api/optimizer/proposals")
        assert r.status_code == 200
        body = r.json()
        assert body["queue_size"] == 2
        ids = [p["proposal"]["proposal_id"] for p in body["proposals"]]
        assert ids == ["a", "b"]

    def test_503_when_optimizer_service_not_mounted(self):
        app = FastAPI()
        register_optimizer_routes(app, bms_write_fn=lambda *a, **k: (True, "ok"))
        # NOTE: deliberately do NOT set app.state.optimizer_service
        client = TestClient(app)
        r = client.get("/api/optimizer/proposals")
        assert r.status_code == 503
        assert "Optimizer service not running" in r.json()["detail"]


# ─── POST /approve happy path + RBAC ──────────────────────────────────
class TestApproveHappyPath:
    def test_approve_sme_l6_dequeues_and_writes_bms(self, stack):
        client, svc, bms_calls, _app = stack
        svc.queue.enqueue(_make_queued("qp-100"))
        r = client.post(
            "/api/optimizer/approve/qp-100",
            json={
                "actor_role": "SME_L6",
                "operator_id": "wilmer.angel",
                "confirm_ashrae": True,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["decision"] == DECISION_APPROVED
        assert body["operator_id"] == "wilmer.angel"
        assert body["actor_role"] == "SME_L6"
        assert body["bms_write_success"] is True
        assert body["bms_tag_id"] == SURFACE_TO_BMS_TAG[SURFACE_CHILLER_LWT]
        # Proposal dequeued
        assert svc.queue.size() == 0
        # BMS write seam was called exactly once with the proposed value
        assert len(bms_calls) == 1
        assert bms_calls[0]["tag_id"] == SURFACE_TO_BMS_TAG[SURFACE_CHILLER_LWT]
        assert bms_calls[0]["value"] == 7.0
        assert bms_calls[0]["user"] == "wilmer.angel"


# ─── POST /approve — RBAC + validation failures ───────────────────────
class TestApproveRejection:
    def test_403_when_actor_role_below_sme_l6(self, stack):
        client, svc, bms_calls, _app = stack
        svc.queue.enqueue(_make_queued("qp-1"))
        r = client.post(
            "/api/optimizer/approve/qp-1",
            json={
                "actor_role": "TECH_L4",
                "operator_id": "wilmer.angel",
                "confirm_ashrae": True,
            },
        )
        assert r.status_code == 403
        assert "SME_L6" in r.json()["detail"] or "rank" in r.json()["detail"].lower()
        # Queue untouched, no BMS write
        assert svc.queue.size() == 1
        assert bms_calls == []

    def test_400_when_actor_role_missing(self, stack):
        client, svc, bms_calls, _app = stack
        svc.queue.enqueue(_make_queued("qp-2"))
        r = client.post(
            "/api/optimizer/approve/qp-2",
            json={
                "actor_role": "",
                "operator_id": "wilmer.angel",
                "confirm_ashrae": True,
            },
        )
        # Stricter than the enforce-when-present default — actor_role is
        # required at this endpoint.
        assert r.status_code == 400
        assert svc.queue.size() == 1
        assert bms_calls == []

    def test_400_when_confirm_ashrae_false(self, stack):
        client, svc, bms_calls, _app = stack
        svc.queue.enqueue(_make_queued("qp-3"))
        r = client.post(
            "/api/optimizer/approve/qp-3",
            json={
                "actor_role": "SME_L6",
                "operator_id": "wilmer.angel",
                "confirm_ashrae": False,
            },
        )
        assert r.status_code == 400
        assert "ASHRAE" in r.json()["detail"]
        # Queue untouched
        assert svc.queue.size() == 1
        assert bms_calls == []

    def test_404_when_proposal_unknown(self, stack):
        client, _svc, bms_calls, _app = stack
        r = client.post(
            "/api/optimizer/approve/does-not-exist",
            json={
                "actor_role": "SME_L6",
                "operator_id": "wilmer.angel",
                "confirm_ashrae": True,
            },
        )
        assert r.status_code == 404
        assert bms_calls == []

    def test_409_when_proposal_carries_safety_veto(self, stack):
        # Defence in depth (S-DET-02). 2.B's tick() should never queue
        # a vetoed proposal; if one shows up, refuse it.
        client, svc, bms_calls, _app = stack
        svc.queue.enqueue(_make_queued("qp-veto", veto=True))
        r = client.post(
            "/api/optimizer/approve/qp-veto",
            json={
                "actor_role": "SME_L6",
                "operator_id": "wilmer.angel",
                "confirm_ashrae": True,
            },
        )
        assert r.status_code == 409
        assert "VETO" in r.json()["detail"]
        assert bms_calls == []

    def test_422_when_surface_has_no_bms_tag_mapping(self, stack):
        client, svc, bms_calls, _app = stack
        # Build a proposal with a surface the routes module doesn't
        # know about. Re-enqueue safety: the route re-enqueues so the
        # proposal isn't lost.
        qp = QueuedProposal(
            proposal=Proposal(
                proposal_id="qp-unknown-surface",
                surface="gpu_clock_mhz",   # not in SURFACE_TO_BMS_TAG
                current_value=1800, proposed_value=1750, delta=-50,
                rationale="speculative", pue_at_emission=1.35,
                created_at=time.time(),
            ),
            consensus_verdict="approve", consensus_rationale="ok",
            safety_officer_veto=False, optimizer_narrative="",
            queued_at=time.time(),
        )
        svc.queue.enqueue(qp)
        r = client.post(
            "/api/optimizer/approve/qp-unknown-surface",
            json={
                "actor_role": "SME_L6",
                "operator_id": "wilmer.angel",
                "confirm_ashrae": True,
            },
        )
        assert r.status_code == 422
        # Proposal re-enqueued — operator can act on it after the catalog
        # is extended; never silently dropped.
        assert svc.queue.size() == 1
        assert bms_calls == []


# ─── POST /approve — BMS write failure path ───────────────────────────
class TestApproveBmsFailure:
    def test_bms_write_failure_still_records_approval(self):
        """When the BMS write fails (e.g., tag not writable), the
        operator decision is STILL recorded — the operator's intent
        is auditable. The HMI can read bms_write_success=False and
        prompt for retry."""
        bms_calls: list[dict] = []

        def failing_bms_write(tag_id, value, user):
            bms_calls.append({"tag_id": tag_id, "value": value, "user": user})
            return False, f"tag {tag_id} is not writable"

        app = FastAPI()
        svc = OptimizerService(telemetry_provider=None, pue_target=1.30)
        register_optimizer_routes(app, bms_write_fn=failing_bms_write)
        app.state.optimizer_service = svc
        svc.queue.enqueue(_make_queued("qp-fail"))
        client = TestClient(app)

        r = client.post(
            "/api/optimizer/approve/qp-fail",
            json={
                "actor_role": "SME_L6",
                "operator_id": "wilmer.angel",
                "confirm_ashrae": True,
            },
        )
        assert r.status_code == 200    # operator decision succeeded
        body = r.json()
        assert body["decision"] == DECISION_APPROVED
        assert body["bms_write_success"] is False
        assert "not writable" in body["bms_write_message"]
        # Proposal still dequeued (the operator decided)
        assert svc.queue.size() == 0
        # Audit row recorded
        log_ = app.state.optimizer_approval_log
        assert log_.size() == 1
        assert log_.get("qp-fail").bms_write_success is False

    def test_bms_write_exception_caught_and_recorded(self):
        def crashing_bms_write(*_a, **_k):
            raise RuntimeError("BMS connector raised")

        app = FastAPI()
        svc = OptimizerService(telemetry_provider=None, pue_target=1.30)
        register_optimizer_routes(app, bms_write_fn=crashing_bms_write)
        app.state.optimizer_service = svc
        svc.queue.enqueue(_make_queued("qp-crash"))
        client = TestClient(app)

        r = client.post(
            "/api/optimizer/approve/qp-crash",
            json={
                "actor_role": "SME_L6",
                "operator_id": "w.a",
                "confirm_ashrae": True,
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["bms_write_success"] is False
        assert "exception" in body["bms_write_message"].lower()


# ─── POST /reject ─────────────────────────────────────────────────────
class TestReject:
    def test_reject_happy_path_records_reason(self, stack):
        client, svc, bms_calls, _app = stack
        svc.queue.enqueue(_make_queued("qp-r1"))
        r = client.post(
            "/api/optimizer/reject/qp-r1",
            json={
                "actor_role": "SME_L6",
                "operator_id": "wilmer.angel",
                "reason": "Hall already cooler than target; skipping.",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["decision"] == DECISION_REJECTED
        assert body["reason"].startswith("Hall already cooler")
        # No BMS write on reject
        assert bms_calls == []
        # Proposal dequeued
        assert svc.queue.size() == 0

    def test_reject_requires_non_empty_reason(self, stack):
        client, svc, _bms, _app = stack
        svc.queue.enqueue(_make_queued("qp-r2"))
        r = client.post(
            "/api/optimizer/reject/qp-r2",
            json={
                "actor_role": "SME_L6",
                "operator_id": "wilmer.angel",
                "reason": "",
            },
        )
        # Pydantic rejects min_length=1 with 422
        assert r.status_code == 422
        assert svc.queue.size() == 1   # still queued

    def test_reject_requires_sme_l6(self, stack):
        client, svc, _bms, _app = stack
        svc.queue.enqueue(_make_queued("qp-r3"))
        r = client.post(
            "/api/optimizer/reject/qp-r3",
            json={
                "actor_role": "SENIOR_TECH_L5",
                "operator_id": "wilmer.angel",
                "reason": "operator chose not to actuate",
            },
        )
        assert r.status_code == 403
        assert svc.queue.size() == 1

    def test_reject_404_when_unknown(self, stack):
        client, _svc, _bms, _app = stack
        r = client.post(
            "/api/optimizer/reject/nope",
            json={
                "actor_role": "SME_L6",
                "operator_id": "w.a",
                "reason": "not found",
            },
        )
        assert r.status_code == 404


# ─── GET /approvals ───────────────────────────────────────────────────
class TestFetchApprovals:
    def test_fetch_by_id_returns_recorded_approval(self, stack):
        client, svc, _bms, _app = stack
        svc.queue.enqueue(_make_queued("qp-fetch"))
        client.post(
            "/api/optimizer/approve/qp-fetch",
            json={
                "actor_role": "SME_L6",
                "operator_id": "wilmer.angel",
                "confirm_ashrae": True,
            },
        )
        r = client.get("/api/optimizer/approvals/qp-fetch")
        assert r.status_code == 200
        assert r.json()["decision"] == DECISION_APPROVED

    def test_fetch_404_when_no_decision_recorded(self, stack):
        client, _svc, _bms, _app = stack
        r = client.get("/api/optimizer/approvals/never-existed")
        assert r.status_code == 404

    def test_list_approvals_endpoint(self, stack):
        client, svc, _bms, _app = stack
        svc.queue.enqueue(_make_queued("a"))
        svc.queue.enqueue(_make_queued("b"))
        client.post(
            "/api/optimizer/approve/a",
            json={"actor_role": "SME_L6", "operator_id": "op",
                  "confirm_ashrae": True},
        )
        client.post(
            "/api/optimizer/reject/b",
            json={"actor_role": "SME_L6", "operator_id": "op",
                  "reason": "skipping"},
        )
        r = client.get("/api/optimizer/approvals")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        decisions = [a["decision"] for a in body["approvals"]]
        assert decisions == [DECISION_APPROVED, DECISION_REJECTED]


# ─── ApprovalLog unit ─────────────────────────────────────────────────
class TestApprovalLog:
    def test_record_and_get(self):
        log_ = ApprovalLog()
        log_.record(OptimizerApproval(
            proposal_id="p1", decision="approved",
            operator_id="op", actor_role="SME_L6",
            decision_at=1.0, approval_id="a1",
        ))
        a = log_.get("p1")
        assert a is not None
        assert a.decision == "approved"
        assert log_.get("nope") is None
        assert log_.size() == 1

    def test_capacity_sliding_window(self):
        log_ = ApprovalLog(max_entries=2)
        for i in range(4):
            log_.record(OptimizerApproval(
                proposal_id=f"p{i}", decision="approved",
                operator_id="op", actor_role="SME_L6",
                decision_at=float(i), approval_id=f"a{i}",
            ))
        assert log_.size() == 2
        assert [a.proposal_id for a in log_.list()] == ["p2", "p3"]


# ─── Idempotent route registration ────────────────────────────────────
class TestRouteRegistration:
    def test_register_is_idempotent(self):
        app = FastAPI()
        register_optimizer_routes(app, bms_write_fn=lambda *a, **k: (True, "ok"))
        register_optimizer_routes(app, bms_write_fn=lambda *a, **k: (True, "ok2"))
        # No DuplicateOperation error; the registered flag prevents
        # double-mounting.
        assert getattr(app.state, "_optimizer_routes_registered", False) is True
        # But the seam is replaced on each call (the most-recent
        # bms_write_fn wins).
        assert app.state.optimizer_bms_write_fn(1, 2, 3) == (True, "ok2")


# ════════════════════════════════════════════════════════════════════
# Epic 5 Sprint 1 — E5.A GET /api/optimizer/health
# ════════════════════════════════════════════════════════════════════
class TestOptimizerHealthEndpoint:
    def test_health_returns_initial_snapshot(self, stack):
        client, svc, _bms, _app = stack
        r = client.get("/api/optimizer/health")
        assert r.status_code == 200
        body = r.json()
        assert body["is_running"] is False
        assert body["pue_target"] == 1.30
        assert body["last_tick_unix"] == 0.0
        assert body["tick_count"] == 0
        assert body["queue_size"] == 0
        assert body["last_tick_outcomes"] == {}
        assert body["audit_recent"] == []

    def test_health_reflects_queued_proposals(self, stack):
        client, svc, _bms, _app = stack
        svc.queue.enqueue(_make_queued("h-1"))
        svc.queue.enqueue(_make_queued("h-2", surface=SURFACE_CT_FAN_VFD))
        r = client.get("/api/optimizer/health")
        assert r.status_code == 200
        assert r.json()["queue_size"] == 2

    def test_health_returns_503_when_service_not_wired(self):
        # Build an app without the optimizer service on app.state.
        app = FastAPI()
        register_optimizer_routes(app, bms_write_fn=lambda *a, **k: (True, "ok"))
        # Note: no app.state.optimizer_service assignment.
        client = TestClient(app)
        r = client.get("/api/optimizer/health")
        assert r.status_code == 503
        assert "not running" in r.json()["detail"].lower()


# ════════════════════════════════════════════════════════════════════
# Epic 5 Sprint 3 — E5.F GET /api/optimizer/config (read-only inspector)
# ════════════════════════════════════════════════════════════════════
class TestOptimizerConfigEndpoint:
    def test_config_returns_every_threshold_read_only(self, stack):
        client, _svc, _bms, _app = stack
        r = client.get("/api/optimizer/config")
        assert r.status_code == 200
        body = r.json()
        assert body["read_only"] is True
        assert body["pue_target"] == 1.30
        assert sorted(body["surfaces"]) == ["chiller_lwt", "ct_fan_vfd"]
        th = body["thresholds"]
        # Every control-law constant the operator needs the WHY for.
        for key in (
            "PUE_DRIFT_THRESHOLD", "PUE_SUSTAIN_TICKS",
            "LWT_FLOOR_C", "LWT_STEP_C", "LWT_HALL_INLET_GUARD_C",
            "CT_VFD_MAX_PCT", "CT_VFD_STEP_PCT",
            "CT_APPROACH_FLOOR_K", "CT_APPROACH_HEADROOM_K",
            "PACING_SECONDS", "LOOP_TICK_SECONDS",
        ):
            assert key in th, f"threshold missing from inspector: {key}"
        assert th["PACING_SECONDS"] == 900
        # ADR-006: design-time config — the note states it explicitly.
        assert "ADR-006" in body["note"]

    def test_config_returns_503_when_service_not_wired(self):
        app = FastAPI()
        register_optimizer_routes(app, bms_write_fn=lambda *a, **k: (True, "ok"))
        client = TestClient(app)
        r = client.get("/api/optimizer/config")
        assert r.status_code == 503


# ════════════════════════════════════════════════════════════════════
# Epic 5 Sprint 1 — E5.C per-agent verdicts traverse to JSON
# ════════════════════════════════════════════════════════════════════
class TestQueuedProposalAgentVerdictsJSON:
    def test_proposals_endpoint_carries_agent_verdicts(self, stack):
        client, svc, _bms, _app = stack
        # Build a QueuedProposal WITH per-agent breakdown.
        qp = QueuedProposal(
            proposal=Proposal(
                proposal_id="qp-votes",
                surface=SURFACE_CHILLER_LWT,
                current_value=7.5,
                proposed_value=7.0,
                delta=-0.5,
                rationale="r",
                pue_at_emission=1.35,
                created_at=time.time(),
            ),
            consensus_verdict="approve",
            consensus_rationale="all good",
            safety_officer_veto=False,
            optimizer_narrative="n",
            queued_at=time.time(),
            agent_verdicts=[
                {"agent_name": "Architect", "verdict": "approve", "summary": "topology ok"},
                {"agent_name": "Safety Officer", "verdict": "approve", "summary": "no LOTO"},
                {"agent_name": "Diagnostician", "verdict": "approve", "summary": "no recurrence"},
                {"agent_name": "Analyst", "verdict": "approve", "summary": "opex cheap"},
                {"agent_name": "Capacity Planner", "verdict": "approve", "summary": "headroom"},
                {"agent_name": "Carbon/Grid", "verdict": "caution", "summary": "on-peak TOU"},
            ],
        )
        svc.queue.enqueue(qp)
        r = client.get("/api/optimizer/proposals")
        assert r.status_code == 200
        body = r.json()
        out = body["proposals"][0]
        assert "agent_verdicts" in out
        assert len(out["agent_verdicts"]) == 6
        # Safety Officer row identifiable
        so = next(a for a in out["agent_verdicts"] if a["agent_name"] == "Safety Officer")
        assert so["verdict"] == "approve"


# ════════════════════════════════════════════════════════════════════
# Epic 5 Sprint 2 — E5.E POST /api/optimizer/preview/{id}
# ════════════════════════════════════════════════════════════════════
class TestOptimizerPreviewEndpoint:
    def test_preview_returns_projection_for_queued_proposal(self, stack):
        client, svc, _bms, _app = stack
        qp = _make_queued("qp-preview", surface=SURFACE_CHILLER_LWT)
        svc.queue.enqueue(qp)
        r = client.post("/api/optimizer/preview/qp-preview")
        assert r.status_code == 200
        body = r.json()
        # Schema check — every PreviewProjection field present.
        for key in (
            "proposal_id", "surface", "current_value", "proposed_value",
            "delta", "projected_pue", "projected_pue_delta",
            "projected_wue_delta", "projected_inlet_c",
            "projected_inlet_delta_c", "ashrae_distance_c",
            "verdict", "findings",
        ):
            assert key in body
        assert body["proposal_id"] == "qp-preview"
        # With no telemetry provider wired, projected_pue is None ->
        # amber verdict per simulate_setpoint_impact's contract.
        assert body["verdict"] == "amber"

    def test_preview_returns_404_for_unknown_proposal(self, stack):
        client, _svc, _bms, _app = stack
        r = client.post("/api/optimizer/preview/no-such-id")
        assert r.status_code == 404
        assert "not in queue" in r.json()["detail"].lower()

    def test_preview_does_not_dequeue_the_proposal(self, stack):
        client, svc, _bms, _app = stack
        qp = _make_queued("qp-keep", surface=SURFACE_CHILLER_LWT)
        svc.queue.enqueue(qp)
        client.post("/api/optimizer/preview/qp-keep")
        # Still in the queue after preview — operator hasn't decided yet.
        assert svc.queue.size() == 1

    def test_preview_returns_503_when_service_not_running(self):
        app = FastAPI()
        register_optimizer_routes(app, bms_write_fn=lambda *a, **k: (True, "ok"))
        client = TestClient(app)
        r = client.post("/api/optimizer/preview/qp-x")
        assert r.status_code == 503


# ════════════════════════════════════════════════════════════════════
# Epic 5 Sprint 2 — S-DET-01 binding on the preview route
# ════════════════════════════════════════════════════════════════════
def test_preview_route_does_not_import_llm_modules():
    """The preview route handler must not import or reference any LLM
    client — the projection is pure-Python per S-DET-01 / ADR-006.
    A future refactor that pulls Gemma into the preview path fails
    this test loudly (it lives alongside the older BMS-write invariant
    in test_optimizer.py)."""
    import re as _re
    from pathlib import Path as _Path

    from backend import optimizer_routes as _mod
    src = _Path(_mod.__file__).read_text(encoding="utf-8")
    pat = _re.compile(
        r"async def preview_proposal_impact\b.*?\n(?=\n[A-Za-z@]|\Z)",
        _re.S,
    )
    m = pat.search(src)
    assert m is not None, "preview_proposal_impact() not found"
    body = m.group(0)
    for needle in ("complete_gemma", "llm_client", "_synthesize_narrative"):
        assert needle not in body, (
            f"preview_proposal_impact() must be LLM-free (S-DET-01); "
            f"found {needle!r} in its body."
        )
