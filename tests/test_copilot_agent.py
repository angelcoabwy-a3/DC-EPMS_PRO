"""Offline tests for the agentic investigator (no network, no credits).

A scripted fake model client drives run_investigation through the real
tool loop, fixture, validation, and priority floor.
"""

import json

from backend.agent_fixture import SCENARIOS
from backend.copilot_agent import run_investigation


class FakeClient:
    """Scripted stand-in with the same chat(messages, tools) shape."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def chat(self, messages, tools):
        self.calls += 1
        assert self.script, "fake client ran out of scripted responses"
        return self.script.pop(0)


def _tool_resp(*calls):
    tool_calls = []
    for i, (name, args) in enumerate(calls):
        tool_calls.append(
            {
                "id": f"call-{i}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        )
    message = {"role": "assistant", "content": None, "tool_calls": tool_calls}
    return {"choices": [{"message": message}]}


def _final_resp(final):
    message = {"role": "assistant", "content": json.dumps(final)}
    return {"choices": [{"message": message}]}


def _final(cause="utility_loss", ids=None, confidence="high"):
    return {
        "probable_cause": cause,
        "confidence": confidence,
        "claims": [{"text": "burst points here", "evidence_ids": ids or []}],
        "unconfirmed": [],
        "verification_checklist": ["Go and look in person."],
    }


def test_fixture_holds_two_causes_with_distractors_and_no_triage():
    assert SCENARIOS["burst-utility-01"]["true_cause"] == "utility_loss"
    assert SCENARIOS["burst-cooling-02"]["true_cause"] == "cooling_loss"
    for scenario_id in ("burst-utility-01", "burst-cooling-02"):
        scenario = SCENARIOS[scenario_id]
        titles = [a["title"] for a in scenario["alarms"]]
        assert any("VESDA" in t for t in titles), "each scenario needs a distractor"
        for forbidden in ("triage", "priority", "story", "hypotheses"):
            assert forbidden not in scenario


def test_early_conclusion_rejected():
    client = FakeClient(
        [
            _final_resp(_final(ids=["U-01"])),
            _tool_resp(("query_alarms", {"scenario_id": "burst-utility-01", "window_minutes": 30})),
            _tool_resp(
                (
                    "get_breaker_state",
                    {"scenario_id": "burst-utility-01", "breaker_id": "util-a-feeder"},
                )
            ),
            _final_resp(_final(ids=["U-01", "U-03"])),
        ]
    )
    result = run_investigation("burst-utility-01", client=client)
    assert result["probable_cause"] == "utility_loss"
    assert result["early_rejections"] == 1
    assert result["model_calls"] == 4
    assert set(result["tools_used"]) == {"query_alarms", "get_breaker_state"}


def test_iteration_cap_reached():
    tool = _tool_resp(("query_alarms", {"scenario_id": "burst-utility-01", "window_minutes": 30}))
    client = FakeClient([tool] * 8)
    result = run_investigation("burst-utility-01", client=client)
    assert client.calls == 8
    assert result["model_calls"] == 8
    assert result["probable_cause"] == "unknown"
    assert result["confidence"] == "low"


def test_invented_evidence_id_flagged_as_unverified():
    final = _final(ids=["U-01"])
    final["claims"].append({"text": "invented link", "evidence_ids": ["INC-FAKE-999"]})
    client = FakeClient(
        [
            _tool_resp(("query_alarms", {"scenario_id": "burst-utility-01", "window_minutes": 30})),
            _tool_resp(
                ("get_trend", {"scenario_id": "burst-utility-01", "point_id": "util-a-voltage-kv"})
            ),
            _final_resp(final),
        ]
    )
    result = run_investigation("burst-utility-01", client=client)
    by_text = {c["text"]: c for c in result["claims"]}
    assert by_text["burst points here"]["verified"] is True
    assert by_text["invented link"]["verified"] is False


def test_cause_outside_closed_list_mapped_to_unknown():
    client = FakeClient(
        [
            _tool_resp(("query_alarms", {"scenario_id": "burst-cooling-02", "window_minutes": 30})),
            _tool_resp(
                (
                    "get_breaker_state",
                    {"scenario_id": "burst-cooling-02", "breaker_id": "chiller-2-feeder"},
                )
            ),
            _final_resp(_final(cause="meteor_strike", ids=["C-01"])),
        ]
    )
    result = run_investigation("burst-cooling-02", client=client)
    assert result["probable_cause"] == "unknown"
    assert any("mapped to unknown" in n for n in result["notes"])


def test_priority_floor_raises_table_priority():
    client = FakeClient(
        [
            _tool_resp(("query_alarms", {"scenario_id": "burst-utility-01", "window_minutes": 30})),
            _tool_resp(
                (
                    "get_breaker_state",
                    {"scenario_id": "burst-utility-01", "breaker_id": "util-a-feeder"},
                )
            ),
            _final_resp(_final(cause="unknown", ids=["U-01"], confidence="medium")),
        ]
    )
    result = run_investigation("burst-utility-01", client=client)
    assert result["priority"] == "P1"
    assert result["suggested_procedure"] == "SOP-DAILY-ROUNDS-001"
    assert any("raised table priority" in n for n in result["notes"])
