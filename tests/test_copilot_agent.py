"""Offline tests for the agentic investigator (no network, no credits).

A scripted fake model client drives run_investigation through the real
tool loop, fixture, validation, and priority floor.
"""

import json

from backend.agent_fixture import SCENARIOS
from backend.copilot_agent import (
    CHECKLIST_SYSTEM_PROMPT,
    NUDGE_BAD_CHECKLIST,
    NUDGE_BAD_JSON,
    NUDGE_MORE_EVIDENCE,
    SYSTEM_PROMPT,
    TOOL_SCHEMAS,
    run_investigation,
)


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


def _checklist_resp(working_hypothesis="utility_loss", count=4, counter=True, extra=None):
    items = []
    for i in range(1, count + 1):
        items.append(
            {
                "id": f"CHK-{i:02d}",
                "question": f"Question {i}?",
                "evidence_needed": f"Evidence {i}",
                "is_counter_evidence": bool(counter and i == count),
            }
        )
    payload = {"working_hypothesis": working_hypothesis, "checklist": items}
    if extra:
        payload.update(extra)
    message = {"role": "assistant", "content": json.dumps(payload)}
    return {"choices": [{"message": message}]}


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
            _checklist_resp(),
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
    assert result["model_calls"] == 5
    assert set(result["tools_used"]) == {"query_alarms", "get_breaker_state"}


def test_iteration_cap_reached():
    tool = _tool_resp(("query_alarms", {"scenario_id": "burst-utility-01", "window_minutes": 30}))
    client = FakeClient([_checklist_resp()] + [tool] * 7)
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
            _checklist_resp(),
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
            _checklist_resp(),
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


def test_tool_results_follow_their_assistant_message():
    observed = {}

    class CheckingClient:
        def __init__(self):
            self.calls = 0

        def chat(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return _checklist_resp()
            if self.calls == 2:
                return _tool_resp(
                    ("query_alarms", {"scenario_id": "burst-utility-01", "window_minutes": 30})
                )
            if self.calls == 3:
                observed["messages"] = list(messages)
                return _tool_resp(
                    (
                        "get_breaker_state",
                        {"scenario_id": "burst-utility-01", "breaker_id": "util-a-feeder"},
                    )
                )
            return _final_resp(_final(ids=["U-01", "util-a-feeder"]))

    result = run_investigation("burst-utility-01", client=CheckingClient())
    messages = observed["messages"]
    tools_seen = [m for m in messages if m.get("role") == "tool"]
    assert tools_seen, "a later request must carry the tool result"
    at = messages.index(tools_seen[0])
    wanted = tools_seen[0].get("tool_call_id")
    assert any(
        call.get("id") == wanted
        for msg in messages[:at]
        if msg.get("role") == "assistant"
        for call in (msg.get("tool_calls") or [])
    ), "assistant tool_calls must precede the tool result with the same id"
    assert result["probable_cause"] == "utility_loss"
    assert set(result["tools_used"]) == {"query_alarms", "get_breaker_state"}


def test_priority_floor_raises_table_priority():
    client = FakeClient(
        [
            _checklist_resp(),
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


def _run_standard(client_script):
    return run_investigation("burst-utility-01", client=FakeClient(client_script))


def _two_tools():
    return [
        _tool_resp(("query_alarms", {"scenario_id": "burst-utility-01", "window_minutes": 30})),
        _tool_resp(
            (
                "get_breaker_state",
                {"scenario_id": "burst-utility-01", "breaker_id": "util-a-feeder"},
            )
        ),
    ]


def test_checklist_first_call_has_no_tools_array():
    seen = []

    class RecordingClient:
        def __init__(self, script):
            self.script = list(script)

        def chat(self, messages, tools):
            seen.append((list(messages), tools))
            assert self.script, "fake client ran out of scripted responses"
            return self.script.pop(0)

    client = RecordingClient([_checklist_resp(), *_two_tools(), _final_resp(_final())])
    result = run_investigation("burst-utility-01", client=client)
    assert seen[0][1] is None, "checklist call must carry no tools array"
    assert seen[1][1] == TOOL_SCHEMAS, "tool calls resume after the checklist"
    assert result["probable_cause"] == "utility_loss"
    for messages, _tools in seen:
        for message in messages:
            if message.get("role") in ("system", "user"):
                assert "VESDA" not in message["content"]
                assert "self-test" not in message["content"]


def test_checklist_without_counter_evidence_regenerated_once():
    client = FakeClient(
        [_checklist_resp(counter=False), _checklist_resp(), *_two_tools(), _final_resp(_final())]
    )
    result = run_investigation("burst-utility-01", client=client)
    assert result["probable_cause"] == "utility_loss"
    assert result["model_calls"] == 5
    stored = result["investigation_checklist"]
    assert len(stored) == 4
    assert any(i["is_counter_evidence"] for i in stored)


def test_invalid_checklist_after_regen_stops_unknown_low():
    bad = _checklist_resp(counter=False)
    result = _run_standard([bad, bad])
    assert result["probable_cause"] == "unknown"
    assert result["confidence"] == "low"
    assert result["model_calls"] == 2


def test_hypothesis_outside_list_invalid():
    client = FakeClient(
        [
            _checklist_resp(working_hypothesis="meteor_strike"),
            _checklist_resp("cooling_loss"),
            *_two_tools(),
            _final_resp(_final()),
        ]
    )
    result = run_investigation("burst-utility-01", client=client)
    assert result["working_hypothesis"] == "cooling_loss"
    assert result["probable_cause"] == "utility_loss"


def test_probable_cause_in_checklist_ignored():
    chk = _checklist_resp(extra={"probable_cause": "fire_event"})
    client = FakeClient([chk, *_two_tools(), _final_resp(_final())])
    result = run_investigation("burst-utility-01", client=client)
    assert result["probable_cause"] == "utility_loss"


def _inv_final(entries):
    final = _final()
    final["investigation_checklist"] = entries
    return final


def test_settled_with_invented_id_downgraded():
    final = _inv_final(
        [{"id": "CHK-01", "status": "settled", "cited_evidence_ids": ["U-01", "INC-FAKE-999"]}]
    )
    client = FakeClient(
        [
            _checklist_resp(),
            _two_tools()[0],
            _tool_resp(
                ("get_trend", {"scenario_id": "burst-utility-01", "point_id": "util-a-voltage-kv"})
            ),
            _final_resp(final),
        ]
    )
    result = run_investigation("burst-utility-01", client=client)
    entry = {e["id"]: e for e in result["investigation_checklist"]}["CHK-01"]
    assert entry["status"] == "not_settled"
    assert entry["cited_evidence_ids"] == ["U-01"]


def test_final_keeps_stored_question_discards_unknown_id():
    final = _inv_final(
        [
            {
                "id": "CHK-01",
                "question": "CHANGED?",
                "status": "settled",
                "cited_evidence_ids": ["U-01"],
            },
            {"id": "CHK-99", "status": "settled", "cited_evidence_ids": ["U-02"]},
        ]
    )
    client = FakeClient([_checklist_resp(), *_two_tools(), _final_resp(final)])
    result = run_investigation("burst-utility-01", client=client)
    entry = {e["id"]: e for e in result["investigation_checklist"]}["CHK-01"]
    assert entry["question"] == "Question 1?"
    assert result["discarded_checklist_ids"] == ["CHK-99"]


def test_omitted_item_becomes_not_settled():
    final = _inv_final([{"id": "CHK-01", "status": "settled", "cited_evidence_ids": ["U-01"]}])
    client = FakeClient([_checklist_resp(), *_two_tools(), _final_resp(final)])
    result = run_investigation("burst-utility-01", client=client)
    by_id = {e["id"]: e for e in result["investigation_checklist"]}
    assert by_id["CHK-01"]["status"] == "settled"
    for missing in ("CHK-02", "CHK-03", "CHK-04"):
        assert by_id[missing]["status"] == "not_settled"
        assert by_id[missing]["cited_evidence_ids"] == []


def test_unsettled_counter_evidence_caps_medium():
    final = _final(confidence="high")
    client = FakeClient([_checklist_resp(), *_two_tools(), _final_resp(final)])
    result = run_investigation("burst-utility-01", client=client)
    assert result["confidence"] == "medium"


def test_contradicted_caps_low_and_unconfirmed():
    final = _inv_final(
        [
            {"id": "CHK-01", "status": "settled", "cited_evidence_ids": ["U-01"]},
            {"id": "CHK-04", "status": "contradicted", "cited_evidence_ids": ["U-03"]},
        ]
    )
    final["confidence"] = "high"
    client = FakeClient([_checklist_resp(), *_two_tools(), _final_resp(final)])
    result = run_investigation("burst-utility-01", client=client)
    assert result["confidence"] == "low"
    assert any("CHK-04" in u for u in result["unconfirmed"])


def test_checklist_counts_toward_cap():
    client = FakeClient([_checklist_resp(counter=False)])
    result = run_investigation("burst-utility-01", client=client, max_calls=1)
    assert result["probable_cause"] == "unknown"
    assert result["confidence"] == "low"
    assert result["model_calls"] == 1


def test_prompts_carry_no_scenario_hints():
    for text in (
        CHECKLIST_SYSTEM_PROMPT,
        SYSTEM_PROMPT,
        NUDGE_BAD_CHECKLIST,
        NUDGE_BAD_JSON,
        NUDGE_MORE_EVIDENCE,
    ):
        assert "VESDA" not in text
        assert "self-test" not in text
