"""
tests/test_mv_switching.py
==========================
Release R3-B -- backend/mv_switching.py: the interlock engine is pure,
so every rule is proven here without a controller or a clock.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from backend import mv_switching as mv  # noqa: E402

SAFE = mv.BayContext(
    now=100.0, engine_stopped=True, engine_at_rated=False,
    voltage_present=False, path_keeps_capacity=True,
)
RUNNING = mv.BayContext(
    now=100.0, engine_stopped=False, engine_at_rated=True,
    voltage_present=True, path_keeps_capacity=True,
)


def bay(**kw) -> mv.Bay:
    return mv.Bay(bay_id="gen_a_01", **kw)


class TestFailSafe:
    def test_default_context_blocks_everything_that_needs_a_fact(self):
        ctx = mv.BayContext()
        assert mv.interlock(bay(), mv.OP_CLOSE_CB, ctx) is not None
        assert mv.interlock(bay(), mv.OP_OPEN_DS, ctx) is not None
        assert mv.interlock(bay(ds=mv.OPEN), mv.OP_VERIFY_ABSENCE, ctx) is not None
        assert mv.interlock(bay(ds=mv.OPEN), mv.OP_CLOSE_ES, ctx) is not None

    def test_unknown_position_blocks(self):
        reason = mv.interlock(bay(cb="INTERMEDIATE"), mv.OP_OPEN_DS, SAFE)
        assert "fail-safe" in reason

    def test_unknown_operation_blocks(self):
        assert "Unknown" in mv.interlock(bay(), "RACK_OUT", SAFE)

    def test_opening_a_breaker_is_always_permitted(self):
        assert mv.interlock(bay(cb=mv.CLOSED), mv.OP_OPEN_CB, mv.BayContext()) is None


class TestRules:
    def test_r1_no_close_cb_on_an_earthed_bay(self):
        b = bay(ds=mv.OPEN, es=mv.CLOSED)
        assert mv.interlock(b, mv.OP_CLOSE_CB, RUNNING).startswith("R1")

    def test_r2_no_earthing_with_cb_or_ds_closed(self):
        assert mv.interlock(bay(), mv.OP_CLOSE_ES, SAFE).startswith("R2")
        assert mv.interlock(bay(cb=mv.CLOSED, ds=mv.OPEN), mv.OP_CLOSE_ES, SAFE).startswith("R2")

    def test_r3_no_earthing_without_fresh_verification(self):
        b = bay(ds=mv.OPEN)
        assert mv.interlock(b, mv.OP_CLOSE_ES, SAFE).startswith("R3")
        b.absence_verified_at = SAFE.now - mv.ABSENCE_VALID_S - 1
        assert mv.interlock(b, mv.OP_CLOSE_ES, SAFE).startswith("R3")
        b.absence_verified_at = SAFE.now - 5
        assert mv.interlock(b, mv.OP_CLOSE_ES, SAFE) is None

    def test_r3_voltage_present_beats_a_verification(self):
        b = bay(ds=mv.OPEN, absence_verified_at=99.0)
        ctx = mv.BayContext(now=100.0, voltage_present=True)
        assert "voltage present" in mv.interlock(b, mv.OP_CLOSE_ES, ctx)

    def test_r4_disconnector_never_breaks_or_makes_load(self):
        assert mv.interlock(bay(cb=mv.CLOSED), mv.OP_OPEN_DS, SAFE).startswith("R4")
        assert mv.interlock(bay(cb=mv.CLOSED, ds=mv.OPEN), mv.OP_CLOSE_DS, SAFE).startswith("R4")
        assert mv.interlock(bay(), mv.OP_OPEN_DS, RUNNING).startswith("R4")

    def test_r5_r6_closing_the_breaker(self):
        assert mv.interlock(bay(ds=mv.OPEN), mv.OP_CLOSE_CB, RUNNING).startswith("R5")
        assert mv.interlock(bay(), mv.OP_CLOSE_CB, SAFE).startswith("R6")
        assert mv.interlock(bay(), mv.OP_CLOSE_CB, RUNNING) is None

    def test_r7_loto_blocks_everything_but_its_removal(self):
        b = bay(ds=mv.OPEN, es=mv.CLOSED, loto=True)
        for operation in mv.BAY_OPERATIONS:
            reason = mv.interlock(b, operation, SAFE)
            if operation == mv.OP_REMOVE_LOTO:
                assert reason is None
            else:
                assert reason.startswith("R7"), operation

    def test_r8_no_closing_the_disconnector_on_an_earthed_bay(self):
        assert mv.interlock(bay(ds=mv.OPEN, es=mv.CLOSED), mv.OP_CLOSE_DS, SAFE).startswith("R8")

    def test_r9_loto_only_on_an_isolated_and_earthed_bay(self):
        assert mv.interlock(bay(), mv.OP_APPLY_LOTO, SAFE).startswith("R9")
        assert mv.interlock(bay(ds=mv.OPEN), mv.OP_APPLY_LOTO, SAFE).startswith("R9")
        assert mv.interlock(bay(ds=mv.OPEN, es=mv.CLOSED), mv.OP_APPLY_LOTO, SAFE) is None

    def test_r10_path_capacity(self):
        ctx = mv.BayContext(now=1.0, engine_stopped=True, voltage_present=False)
        assert mv.interlock(bay(), mv.OP_OPEN_DS, ctx).startswith("R10")


class TestApplyAndPlans:
    def test_full_isolation_then_restore(self):
        b = bay()
        for operation, _gate, _two in mv.plan(mv.GOAL_ISOLATE, b):
            assert mv.interlock(b, operation, SAFE) is None, operation
            mv.apply(b, operation, SAFE.now)
        assert b.isolated_and_earthed
        assert b.loto
        assert not b.in_service
        for operation, _gate, _two in mv.plan(mv.GOAL_RESTORE, b):
            assert mv.interlock(b, operation, SAFE) is None, operation
            mv.apply(b, operation, SAFE.now)
        assert b.in_service
        assert b.absence_verified_at is None

    def test_restore_plan_holds_only_the_steps_still_needed(self):
        ops = lambda b: [s[0] for s in mv.plan(mv.GOAL_RESTORE, b)]  # noqa: E731
        assert ops(bay(ds=mv.OPEN)) == [mv.OP_CLOSE_DS]
        assert ops(bay(ds=mv.OPEN, es=mv.CLOSED)) == [mv.OP_OPEN_ES, mv.OP_CLOSE_DS]
        assert ops(bay(ds=mv.OPEN, es=mv.CLOSED, loto=True)) == [
            mv.OP_REMOVE_LOTO, mv.OP_OPEN_ES, mv.OP_CLOSE_DS,
        ]

    def test_safety_gates_and_two_person_steps(self):
        plan = {s[0]: s for s in mv.plan(mv.GOAL_ISOLATE, bay())}
        assert plan[mv.OP_CLOSE_ES][1:] == (True, True)
        assert plan[mv.OP_APPLY_LOTO][1:] == (True, True)
        assert plan[mv.OP_VERIFY_ABSENCE][1:] == (True, False)
        remove = mv.plan(mv.GOAL_RESTORE, bay(ds=mv.OPEN, es=mv.CLOSED, loto=True))[0]
        assert remove == (mv.OP_REMOVE_LOTO, True, True)

    def test_unknown_goal(self):
        with pytest.raises(ValueError, match="unknown goal"):
            mv.plan("EXPLODE", bay())

    def test_witness_approval_expires(self):
        proc = mv.Procedure("p", "gen_a_01", mv.GOAL_ISOLATE, "op", 0.0,
                            steps=mv.plan(mv.GOAL_ISOLATE, bay()))
        proc.witnesses[3] = ("w", 10.0)
        assert proc.witness_ok(3, 20.0)
        assert not proc.witness_ok(3, 10.0 + mv.WITNESS_VALID_S + 1)
        assert not proc.witness_ok(4, 20.0)

    def test_module_is_pure(self):
        text = pathlib.Path(mv.__file__).read_text(encoding="utf-8")
        for forbidden in ("import time", "fastapi", "import requests", "open("):
            assert forbidden not in text
