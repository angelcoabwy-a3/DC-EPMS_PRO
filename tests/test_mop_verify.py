"""Offline tests for MOP photo verification (no network, no credits).

Fake SAM/Spark clients drive backend.mop_verify through assignment,
cropping, judging, verdicts, sessions, claims, retries, and the guard.
Band colors in synthetic panels route each crop to its scripted answer,
so the tests also prove crops come from the right regions.
"""

import asyncio
import base64
import inspect
import io
import json
import logging
import threading
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image, ImageDraw

import backend.mop_verify as mop_verify
from backend.copilot_agent import (
    _TOOL_FNS,
    TOOL_SCHEMAS,
    copilot_mop_session_restart,
    copilot_mop_session_start,
    copilot_mop_steps,
    copilot_mop_verify,
    run_investigation,
    tool_verify_photo,
)
from backend.copilot_limits import (
    check_limits,
    get_daily_count,
    get_ip_usage,
    record_meta_attempt,
    reset_for_tests,
)

RED = (255, 0, 0)
GREEN = (0, 200, 0)
BLUE = (0, 0, 255)
YELLOW = (255, 255, 0)
CYAN = (0, 255, 255)
MAGENTA = (255, 0, 255)

LEFT_COL = (60, 100, 530, 1100)
RIGHT_COL = (670, 100, 1140, 1100)

LEFT_BANDS = {
    "Q5": (60, 510, 530, 700),
    "Q7": (60, 710, 530, 900),
    "Q9": (60, 910, 530, 1100),
}
RIGHT_BANDS = {
    "Q6": (670, 510, 1140, 700),
    "Q8": (670, 710, 1140, 900),
    "BYP": (670, 910, 1140, 1100),
}
BAND_COLORS = {
    "Q5": RED,
    "Q7": GREEN,
    "Q9": BLUE,
    "Q6": YELLOW,
    "Q8": CYAN,
    "BYP": MAGENTA,
}


def _painted(rect_colors, width=1200, height=1600):
    img = Image.new("RGB", (width, height), (128, 128, 128))
    draw = ImageDraw.Draw(img)
    for (x1, y1, x2, y2), color in rect_colors:
        draw.rectangle([x1, y1, x2 - 1, y2 - 1], fill=color)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def _split_panel():
    rects = [(LEFT_BANDS[label], BAND_COLORS[label]) for label in ("Q5", "Q7", "Q9")]
    rects += [(RIGHT_BANDS[label], BAND_COLORS[label]) for label in ("Q6", "Q8", "BYP")]
    return _painted(rects)


def _nearest(color, palette):
    best, best_dist = None, None
    for candidate in palette:
        dist = sum((a - b) ** 2 for a, b in zip(color, candidate, strict=True))
        if best_dist is None or dist < best_dist:
            best, best_dist = candidate, dist
    return best


def _handle_json(handle):
    return json.dumps({"handle": handle, "notes": "test"})


class FakeSAM:
    """Canned boxes (or scripted errors) with a call count."""

    def __init__(self, boxes=None, errors=None):
        self.boxes = boxes if boxes is not None else []
        self.errors = list(errors or [])
        self.calls = 0

    def __call__(self, image_bytes):
        assert isinstance(image_bytes, bytes)
        assert image_bytes
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return [tuple(box) for box in self.boxes]


class FakeSpark:
    """Answers routed by crop center color; thread-safe for parallel crops."""

    def __init__(self, answers_by_color, errors=None):
        self.answers_by_color = dict(answers_by_color)
        self.errors = list(errors or [])
        self.calls = 0
        self._lock = threading.Lock()

    def __call__(self, crop_bytes):
        with Image.open(io.BytesIO(crop_bytes)) as img:
            rgb = img.convert("RGB")
            color = rgb.getpixel((rgb.size[0] // 2, rgb.size[1] // 2))
        with self._lock:
            self.calls += 1
            if self.errors:
                raise self.errors.pop(0)
        return self.answers_by_color[_nearest(color, self.answers_by_color)]


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    reset_for_tests()
    mop_verify.reset_sessions_for_tests()
    monkeypatch.setattr(mop_verify, "_default_sam_client", None)
    monkeypatch.setattr(mop_verify, "_default_spark_client", None)
    yield
    reset_for_tests()
    mop_verify.reset_sessions_for_tests()


class _StubUpload:
    """UploadFile stand-in carrying photo bytes (no sockets, no threadpool)."""

    def __init__(self, data: bytes):
        self._data = data

    async def read(self):
        await asyncio.sleep(0)
        return self._data


_NO_JSON = object()


class _StubRequest:
    """Request stand-in: canned form fields plus a fixed client address."""

    def __init__(self, fields, json_body=_NO_JSON):
        self._fields = dict(fields)
        self._json_body = json_body
        self.client = SimpleNamespace(host="testclient", port=50000)

    async def form(self):
        await asyncio.sleep(0)
        return dict(self._fields)

    async def json(self):
        await asyncio.sleep(0)
        if self._json_body is _NO_JSON:
            raise ValueError("no JSON body")
        return self._json_body


async def _immediate_to_thread(func, /, *args, **kwargs):
    await asyncio.sleep(0)
    return func(*args, **kwargs)


def _drive(awaitable):
    """Run a coroutine chain with no event loop (pure in-memory awaits)."""
    gen = awaitable.__await__()
    value = None
    while True:
        try:
            yielded = gen.send(value)
        except StopIteration as done:
            return done.value
        value = _drive(yielded) if inspect.isawaitable(yielded) else None


def _call_verify(monkeypatch, fields):
    monkeypatch.setattr(asyncio, "to_thread", _immediate_to_thread)
    return _drive(copilot_mop_verify(_StubRequest(fields)))


def _call_steps():
    return _drive(copilot_mop_steps(_StubRequest({})))


def _call_session_start(json_body=_NO_JSON):
    return _drive(copilot_mop_session_start(_StubRequest({}, json_body)))


def _call_session_restart(json_body=_NO_JSON):
    return _drive(copilot_mop_session_restart(_StubRequest({}, json_body)))


def _resp_body(resp):
    return json.loads(resp.body)


def _inject(monkeypatch, sam, spark):
    monkeypatch.setattr(mop_verify, "_default_sam_client", sam)
    monkeypatch.setattr(mop_verify, "_default_spark_client", spark)


def _direct_boxes():
    left = [(60, 100 + i * 250, 530, 300 + i * 250) for i in range(4)]
    right = [(670, 100 + i * 250, 1140, 300 + i * 250) for i in range(4)]
    return left + right


def _direct_panel():
    rects = []
    for box, label in zip(_direct_boxes()[:4], ("Q1/Q3", "Q5", "Q7", "Q9"), strict=False):
        rects.append((box, BAND_COLORS.get(label, RED)))
    for box, label in zip(_direct_boxes()[4:], ("Q2/Q4", "Q6", "Q8", "BYP"), strict=False):
        rects.append((box, BAND_COLORS.get(label, YELLOW)))
    return _painted(rects)


def _all(handles):
    return {color: _handle_json(handle) for color, handle in handles.items()}


def test_eight_boxes_assigned_directly(monkeypatch):
    sam = FakeSAM(boxes=_direct_boxes())
    spark = FakeSpark(_all(dict.fromkeys(BAND_COLORS.values(), "RIGHT")))
    _inject(monkeypatch, sam, spark)
    result = mop_verify.verify_photo(0, _direct_panel())
    assert result["verdict"] == "MATCH"
    assert result["column_methods"]["left"]["method"] == "4 boxes"
    assert result["column_methods"]["right"]["method"] == "4 boxes"
    assert sam.calls == 1
    assert spark.calls == 5


def test_two_column_boxes_split(monkeypatch):
    sam = FakeSAM(boxes=[LEFT_COL, RIGHT_COL])
    spark = FakeSpark(_all(dict.fromkeys(BAND_COLORS.values(), "RIGHT")))
    _inject(monkeypatch, sam, spark)
    result = mop_verify.verify_photo(0, _split_panel())
    assert result["verdict"] == "MATCH"
    assert result["column_methods"]["left"]["method"] == "split"
    assert result["column_methods"]["right"]["method"] == "split"
    assert sam.calls == 1
    assert spark.calls == 5


def test_five_boxes_mixed_direct_and_split(monkeypatch):
    boxes = _direct_boxes()[:4] + [RIGHT_COL]
    sam = FakeSAM(boxes=boxes)
    spark = FakeSpark(_all(dict.fromkeys(BAND_COLORS.values(), "RIGHT")))
    _inject(monkeypatch, sam, spark)
    rects = [
        (_direct_boxes()[1], RED),
        (_direct_boxes()[2], GREEN),
        (_direct_boxes()[3], BLUE),
        (RIGHT_BANDS["Q8"], CYAN),
        (RIGHT_BANDS["BYP"], MAGENTA),
    ]
    result = mop_verify.verify_photo(0, _painted(rects))
    assert result["verdict"] == "MATCH"
    assert result["column_methods"]["left"]["method"] == "4 boxes"
    assert result["column_methods"]["right"]["method"] == "split"


def test_bad_aspect_ratio_makes_column_unknown(monkeypatch):
    bad_right = (670, 100, 810, 1100)
    sam = FakeSAM(boxes=[LEFT_COL, bad_right])
    spark = FakeSpark(_all(dict.fromkeys(BAND_COLORS.values(), "RIGHT")))
    _inject(monkeypatch, sam, spark)
    result = mop_verify.verify_photo(0, _split_panel())
    assert result["column_methods"]["right"]["method"] == "UNKNOWN"
    assert result["readings"]["Q8"]["mapped"] == "UNKNOWN"
    assert result["readings"]["BYP"]["mapped"] == "UNKNOWN"
    assert result["readings"]["Q5"]["mapped"] == "CLOSED"
    assert result["verdict"] == "UNCERTAIN"
    assert spark.calls == 3


def test_left_right_mapping_per_column(monkeypatch):
    sam = FakeSAM(boxes=[LEFT_COL, RIGHT_COL])
    answers = {
        RED: _handle_json("RIGHT"),
        GREEN: _handle_json("LEFT"),
        BLUE: _handle_json("RIGHT"),
        YELLOW: _handle_json("LEFT"),
        CYAN: _handle_json("LEFT"),
        MAGENTA: _handle_json("RIGHT"),
    }
    spark = FakeSpark(answers)
    _inject(monkeypatch, sam, spark)
    result = mop_verify.verify_photo(0, _split_panel())
    readings = result["readings"]
    assert readings["Q5"]["mapped"] == "CLOSED"
    assert readings["Q7"]["mapped"] == "OPEN"
    assert readings["Q9"]["mapped"] == "CLOSED"
    assert readings["Q8"]["mapped"] == "CLOSED"
    assert readings["BYP"]["mapped"] == "OPEN"


def test_match_advances_the_step(monkeypatch):
    sam = FakeSAM(boxes=[LEFT_COL, RIGHT_COL])
    spark = FakeSpark(_all(dict.fromkeys(BAND_COLORS.values(), "RIGHT")))
    _inject(monkeypatch, sam, spark)
    result = mop_verify.verify_photo(0, _split_panel(), session_id="adv")
    assert result["verdict"] == "MATCH"
    assert result["advanced"] is True
    assert result["blocked"] is False
    session = mop_verify.get_session("adv")
    assert session.current_step == 1
    assert len(session.history) == 1


def test_mismatch_blocks_with_hazard(monkeypatch):
    sam = FakeSAM(boxes=[LEFT_COL, RIGHT_COL])
    answers = _all(dict.fromkeys(BAND_COLORS.values(), "RIGHT"))
    answers[CYAN] = _handle_json("RIGHT")
    answers[MAGENTA] = _handle_json("LEFT")
    spark = FakeSpark(answers)
    _inject(monkeypatch, sam, spark)
    result = mop_verify.verify_photo(2, _split_panel(), session_id="block")
    assert result["verdict"] == "MISMATCH"
    assert result["differing_labels"] == ["Q8"]
    assert result["blocked"] is True
    assert result["advanced"] is False
    assert "opening Q9" in result["hazard_if_wrong"]
    assert result["expected_state"]["Q8"] == "CLOSED"
    assert mop_verify.get_session("block").current_step == 0


def test_uncertain_blocks_with_hazard(monkeypatch):
    sam = FakeSAM(boxes=[LEFT_COL, RIGHT_COL])
    answers = _all(dict.fromkeys(BAND_COLORS.values(), "RIGHT"))
    answers[MAGENTA] = _handle_json("UNKNOWN")
    spark = FakeSpark(answers)
    _inject(monkeypatch, sam, spark)
    result = mop_verify.verify_photo(1, _split_panel(), session_id="unc")
    assert result["verdict"] == "UNCERTAIN"
    assert result["blocked"] is True
    assert "Q8" in result["hazard_if_wrong"]
    assert mop_verify.get_session("unc").current_step == 0


def test_no_answer_blocks_with_hazard(monkeypatch):
    sam = FakeSAM(boxes=[LEFT_COL, RIGHT_COL])
    spark = FakeSpark(
        _all(dict.fromkeys(BAND_COLORS.values(), "RIGHT")),
        errors=[RuntimeError("spark exploded")],
    )
    _inject(monkeypatch, sam, spark)
    result = mop_verify.verify_photo(3, _split_panel(), session_id="noa")
    assert result["verdict"] == "NO_ANSWER"
    assert result["blocked"] is True
    assert "Q9" in result["hazard_if_wrong"]
    assert mop_verify.get_session("noa").current_step == 0


def test_operator_claim_contradiction(monkeypatch):
    sam = FakeSAM(boxes=[LEFT_COL, RIGHT_COL])
    answers = _all(dict.fromkeys(BAND_COLORS.values(), "RIGHT"))
    answers[MAGENTA] = _handle_json("LEFT")
    spark = FakeSpark(answers)
    _inject(monkeypatch, sam, spark)
    result = mop_verify.verify_photo(2, _split_panel(), operator_claim="Q8 closed")
    assert result["claim"] == {"label": "Q8", "state": "CLOSED"}
    assert result["contradiction"] == {"label": "Q8", "claimed": "CLOSED", "observed": "OPEN"}


def test_unparseable_claim_gives_no_contradiction(monkeypatch):
    sam = FakeSAM(boxes=[LEFT_COL, RIGHT_COL])
    spark = FakeSpark(_all(dict.fromkeys(BAND_COLORS.values(), "RIGHT")))
    _inject(monkeypatch, sam, spark)
    result = mop_verify.verify_photo(0, _split_panel(), operator_claim="looks fine")
    assert result["claim"] is None
    assert result["contradiction"] is None
    assert result["verdict"] == "MATCH"


@pytest.mark.parametrize(
    ("transcript", "label", "state"),
    [
        ("Step two, Q eight, closed.", "Q8", "CLOSED"),
        ("Step two, Q eight. On.", "Q8", "CLOSED"),
        ("Step one, B Y P, on.", "BYP", "CLOSED"),
        ("Initial state Q8 open.", "Q8", "OPEN"),
        ("Q8 off", "Q8", "OPEN"),
        ("BYP opened", "BYP", "OPEN"),
        ("Step one, be Y P on.", "BYP", "CLOSED"),
        ("Step two, cue eight. On.", "Q8", "CLOSED"),
        ("bee why pee off", "BYP", "OPEN"),
        ("queue seven off", "Q7", "OPEN"),
    ],
)
def test_parse_claim_voice_probe_transcripts(transcript, label, state):
    assert mop_verify._parse_claim(transcript) == {"label": label, "state": state}


@pytest.mark.parametrize(
    "transcript",
    [
        "Instead one, BYP plus",
        "Step two, QA closet.",
        "Q A closed",
        "Q8 Q9 closed",
        "Q8 open closed",
        "Step two.",
        "be closed",
        "cue on",
    ],
)
def test_parse_claim_rejects(transcript):
    assert mop_verify._parse_claim(transcript) is None


def test_distractors_are_never_scored(monkeypatch):
    sam = FakeSAM(boxes=_direct_boxes())
    spark = FakeSpark(_all(dict.fromkeys(BAND_COLORS.values(), "RIGHT")))
    _inject(monkeypatch, sam, spark)
    result = mop_verify.verify_photo(0, _direct_panel())
    assert set(result["readings"]) == {"Q5", "Q7", "Q8", "Q9", "BYP"}
    assert spark.calls == 5


def test_call_counts_per_verify(monkeypatch):
    sam = FakeSAM(boxes=[LEFT_COL, RIGHT_COL])
    spark = FakeSpark(_all(dict.fromkeys(BAND_COLORS.values(), "RIGHT")))
    _inject(monkeypatch, sam, spark)
    result = mop_verify.verify_photo(0, _split_panel())
    assert sam.calls == 1
    assert spark.calls == 5
    assert result["meta_calls_made"] == 6
    assert get_daily_count() == 1


def test_timeout_retried_once_then_succeeds(monkeypatch):
    sam = FakeSAM(boxes=[LEFT_COL, RIGHT_COL])
    spark = FakeSpark(
        _all(dict.fromkeys(BAND_COLORS.values(), "RIGHT")),
        errors=[httpx.ReadTimeout("boom")],
    )
    _inject(monkeypatch, sam, spark)
    result = mop_verify.verify_photo(0, _split_panel())
    assert result["verdict"] == "MATCH"
    assert spark.calls == 6
    assert result["meta_calls_made"] == 7


def test_non_timeout_error_never_retried(monkeypatch):
    sam = FakeSAM(boxes=[LEFT_COL, RIGHT_COL])
    spark = FakeSpark(
        _all(dict.fromkeys(BAND_COLORS.values(), "RIGHT")),
        errors=[RuntimeError("boom")],
    )
    _inject(monkeypatch, sam, spark)
    result = mop_verify.verify_photo(0, _split_panel())
    assert result["verdict"] == "NO_ANSWER"
    assert spark.calls == 5
    assert result["meta_calls_made"] == 6


def test_retry_budget_caps_total_retries_at_five(monkeypatch):
    sam = FakeSAM(boxes=[LEFT_COL, RIGHT_COL])

    class AlwaysTimeout:
        def __init__(self):
            self.calls = 0
            self._lock = threading.Lock()

        def __call__(self, crop_bytes):
            assert isinstance(crop_bytes, bytes)
            with self._lock:
                self.calls += 1
            raise httpx.ReadTimeout("always down")

    spark = AlwaysTimeout()
    monkeypatch.setattr(mop_verify, "_default_sam_client", sam)
    monkeypatch.setattr(mop_verify, "_default_spark_client", spark)
    result = mop_verify.verify_photo(0, _split_panel())
    assert result["verdict"] == "NO_ANSWER"
    assert spark.calls == 10
    assert result["meta_calls_made"] == 11


def test_bad_step_id_rejected():
    with pytest.raises(mop_verify.MopInputError, match="step_id"):
        mop_verify.verify_photo(9, _split_panel())


def test_undecodable_image_rejected():
    with pytest.raises(mop_verify.MopInputError, match="image"):
        mop_verify.verify_photo(0, b"not an image")


def test_render_debug_overlay_returns_jpeg():
    overlay = mop_verify.render_debug_overlay(
        _split_panel(), [LEFT_COL, RIGHT_COL], [("Q5", LEFT_BANDS["Q5"])]
    )
    assert isinstance(overlay, bytes)
    assert overlay[:2] == b"\xff\xd8"


def test_get_mop_steps_shape():
    summary = mop_verify.get_mop_steps()
    assert summary["mop_id"] == "MOP-UPS-BYP-DEMO-01"
    assert summary["version"] == "1.3"
    assert [step["step_id"] for step in summary["steps"]] == [1, 2, 3, 4, 5]
    assert summary["operated_labels"] == ["Q5", "Q7", "Q9", "Q8", "BYP"]


def test_verify_endpoint_success(monkeypatch):
    monkeypatch.setenv("META_API_KEY", "test-key-not-real")
    sam = FakeSAM(boxes=[LEFT_COL, RIGHT_COL])
    spark = FakeSpark(_all(dict.fromkeys(BAND_COLORS.values(), "RIGHT")))
    _inject(monkeypatch, sam, spark)
    mop_verify.get_session("http-1")
    resp = _call_verify(
        monkeypatch,
        {
            "image": _StubUpload(_split_panel()),
            "step_id": "0",
            "session_id": "http-1",
        },
    )
    assert resp.status_code == 200
    body = _resp_body(resp)
    assert body["verdict"] == "MATCH"
    assert body["meta_call_made"] is True
    assert body["session"]["current_step"] == 1
    assert get_daily_count() == 1


def test_verify_endpoint_bad_input_before_guard(monkeypatch):
    monkeypatch.setenv("META_DAILY_CAP", "0")
    resp = _call_verify(
        monkeypatch,
        {
            "image": _StubUpload(_split_panel()),
            "step_id": "9",
            "session_id": "http-bad",
        },
    )
    assert resp.status_code == 400
    resp = _call_verify(monkeypatch, {"step_id": "0", "session_id": "http-bad"})
    assert resp.status_code == 400


def test_verify_endpoint_guard_before_any_meta_call(monkeypatch):
    monkeypatch.setenv("META_DAILY_CAP", "0")
    monkeypatch.setenv("META_API_KEY", "test-key-not-real")
    sam = FakeSAM(boxes=[LEFT_COL, RIGHT_COL])
    spark = FakeSpark(_all(dict.fromkeys(BAND_COLORS.values(), "RIGHT")))
    _inject(monkeypatch, sam, spark)
    mop_verify.get_session("http-429")
    resp = _call_verify(
        monkeypatch,
        {
            "image": _StubUpload(_split_panel()),
            "step_id": "0",
            "session_id": "http-429",
        },
    )
    assert resp.status_code == 429
    body = _resp_body(resp)
    assert body["error"] == "limit_exceeded"
    assert body["limit"] == "daily_cap"
    assert body["meta_call_made"] is False
    assert body["daily_cap"] == 0
    assert "retry_after_s" in body
    assert resp.headers["Retry-After"] == str(body["retry_after_s"])
    assert sam.calls == 0
    assert spark.calls == 0


def test_verify_endpoint_503_without_key(monkeypatch):
    monkeypatch.delenv("META_API_KEY", raising=False)
    mop_verify.get_session("http-503")
    resp = _call_verify(
        monkeypatch,
        {
            "image": _StubUpload(_split_panel()),
            "step_id": "0",
            "session_id": "http-503",
        },
    )
    assert resp.status_code == 503
    assert _resp_body(resp)["meta_call_made"] is False


def test_steps_endpoint():
    resp = _call_steps()
    assert resp.status_code == 200
    body = _resp_body(resp)
    assert body["mop_id"] == "MOP-UPS-BYP-DEMO-01"
    assert len(body["steps"]) == 5


def test_steps_endpoint_never_counts_or_429s(monkeypatch):
    monkeypatch.setenv("META_DAILY_CAP", "0")
    resp = _call_steps()
    assert resp.status_code == 200
    assert get_ip_usage("testclient") == (0, 10)
    assert get_daily_count() == 0


def _trace_lines(caplog):
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "mop.trace" and record.getMessage().startswith("MOP_TRACE")
    ]


def test_has_and_drop_session_do_not_create():
    assert mop_verify.has_session("ghost") is False
    assert mop_verify.drop_session("ghost") is False
    mop_verify.get_session("ghost")
    assert mop_verify.has_session("ghost") is True
    assert mop_verify.drop_session("ghost") is True
    assert mop_verify.has_session("ghost") is False


def test_verify_endpoint_unknown_session_is_409(monkeypatch, caplog):
    monkeypatch.setenv("META_API_KEY", "test-key-not-real")
    sam = FakeSAM(boxes=[LEFT_COL, RIGHT_COL])
    spark = FakeSpark(_all(dict.fromkeys(BAND_COLORS.values(), "RIGHT")))
    _inject(monkeypatch, sam, spark)
    caplog.set_level(logging.INFO, logger="mop.trace")
    resp = _call_verify(
        monkeypatch,
        {
            "image": _StubUpload(_split_panel()),
            "step_id": "1",
            "session_id": "stale-after-restart",
        },
    )
    assert resp.status_code == 409
    body = _resp_body(resp)
    assert body["error"] == "session_not_found"
    assert body["meta_call_made"] is False
    assert "Restart procedure" in body["detail"]
    assert sam.calls == 0
    assert spark.calls == 0
    assert get_daily_count() == 0
    assert get_ip_usage("testclient") == (0, 10)
    assert mop_verify.has_session("stale-after-restart") is False
    lines = _trace_lines(caplog)
    assert len(lines) == 1
    assert "event=verify" in lines[0]
    assert "verdict=session_not_found" in lines[0]
    assert "http=409" in lines[0]
    assert f"trace={body['trace_id']}" in lines[0]


def test_session_start_adopts_proposed_id():
    resp = _call_session_start({"session_id": "page-1"})
    assert resp.status_code == 200
    body = _resp_body(resp)
    assert body["session"] == {"session_id": "page-1", "current_step": 0, "completed": False}
    assert mop_verify.has_session("page-1") is True
    assert len(body["trace_id"]) == 8


def test_session_start_without_body_mints_id():
    resp = _call_session_start()
    assert resp.status_code == 200
    minted = _resp_body(resp)["session"]["session_id"]
    assert len(minted) == 16
    assert mop_verify.has_session(minted) is True


def test_session_start_resets_a_known_id():
    session = mop_verify.get_session("page-again")
    session.current_step = 3
    resp = _call_session_start({"session_id": "page-again"})
    assert _resp_body(resp)["session"]["current_step"] == 0


def test_session_start_bad_body_is_400():
    assert _call_session_start({"session_id": "  "}).status_code == 400
    assert _call_session_start({"session_id": 42}).status_code == 400
    assert _call_session_start(["not", "a", "dict"]).status_code == 400


def test_session_start_never_counts_or_429s(monkeypatch):
    monkeypatch.setenv("META_DAILY_CAP", "0")
    resp = _call_session_start({"session_id": "page-free"})
    assert resp.status_code == 200
    assert mop_verify.has_session("page-free") is True
    assert get_ip_usage("testclient") == (0, 10)
    assert get_daily_count() == 0


def test_session_restart_drops_old_and_mints_fresh():
    mop_verify.get_session("old-1")
    resp = _call_session_restart({"session_id": "old-1"})
    assert resp.status_code == 200
    fresh = _resp_body(resp)["session"]
    assert fresh["session_id"] != "old-1"
    assert fresh["current_step"] == 0
    assert mop_verify.has_session("old-1") is False
    assert mop_verify.has_session(fresh["session_id"]) is True


def test_session_restart_never_409s():
    resp = _call_session_restart({"session_id": "never-existed"})
    assert resp.status_code == 200
    assert _resp_body(resp)["session"]["current_step"] == 0
    assert _call_session_restart().status_code == 200


def test_session_restart_bad_body_is_400():
    assert _call_session_restart({"session_id": ""}).status_code == 400


def test_trace_steps_success(caplog):
    caplog.set_level(logging.INFO, logger="mop.trace")
    resp = _call_steps()
    body = _resp_body(resp)
    lines = _trace_lines(caplog)
    assert len(lines) == 1
    assert f"trace={body['trace_id']}" in lines[0]
    assert "event=steps" in lines[0]
    assert "http=200" in lines[0]
    assert "limit_ip=0/10" in lines[0]
    assert "daily=0/50" in lines[0]


def test_quota_free_routes_work_when_ip_quota_exhausted(caplog):
    for _ in range(10):
        check_limits("testclient")
        record_meta_attempt()
    assert get_ip_usage("testclient") == (10, 10)
    assert get_daily_count() == 10
    caplog.set_level(logging.INFO, logger="mop.trace")
    assert _call_session_start({"session_id": "exhausted-1"}).status_code == 200
    assert _call_session_restart({"session_id": "exhausted-1"}).status_code == 200
    assert _call_steps().status_code == 200
    assert get_ip_usage("testclient") == (10, 10)
    assert get_daily_count() == 10
    lines = _trace_lines(caplog)
    assert len(lines) == 3
    for line in lines:
        assert "limit_ip=10/10" in line
        assert "daily=10/50" in line
        assert "http=200" in line


def test_trace_verify_success_with_claim(monkeypatch, caplog):
    monkeypatch.setenv("META_API_KEY", "test-key-not-real")
    sam = FakeSAM(boxes=[LEFT_COL, RIGHT_COL])
    spark = FakeSpark(_all(dict.fromkeys(BAND_COLORS.values(), "RIGHT")))
    _inject(monkeypatch, sam, spark)
    mop_verify.get_session("http-trace")
    caplog.set_level(logging.INFO, logger="mop.trace")
    resp = _call_verify(
        monkeypatch,
        {
            "image": _StubUpload(_split_panel()),
            "step_id": "0",
            "session_id": "http-trace",
            "operator_claim": "Q8 closed",
        },
    )
    body = _resp_body(resp)
    assert resp.status_code == 200
    lines = _trace_lines(caplog)
    assert len(lines) == 1
    line = lines[0]
    assert f"trace={body['trace_id']}" in line
    assert "event=verify" in line
    assert "session=http-tra" in line
    assert "step=0" in line
    assert f"verdict={body['verdict']}" in line
    assert "differing=-" in line
    assert "claim=Q8:CLOSED" in line
    assert "contradiction=yes" in line
    assert f"meta_calls={body['meta_calls_made']}" in line
    assert "http=200" in line
    assert "limit_ip=1/10" in line
    assert "daily=1/50" in line
    # Privacy: parsed claim only, never the raw words, headers, keys or bytes.
    assert "Q8 closed" not in line
    assert "Bearer" not in line
    assert "Authorization" not in line
    assert "testclient" not in line
    assert len(line) < 500


def test_trace_verify_without_claim_logs_dashes(monkeypatch, caplog):
    monkeypatch.setenv("META_API_KEY", "test-key-not-real")
    sam = FakeSAM(boxes=[LEFT_COL, RIGHT_COL])
    spark = FakeSpark(_all(dict.fromkeys(BAND_COLORS.values(), "RIGHT")))
    _inject(monkeypatch, sam, spark)
    mop_verify.get_session("http-noclaim")
    caplog.set_level(logging.INFO, logger="mop.trace")
    resp = _call_verify(
        monkeypatch,
        {
            "image": _StubUpload(_split_panel()),
            "step_id": "0",
            "session_id": "http-noclaim",
        },
    )
    assert resp.status_code == 200
    lines = _trace_lines(caplog)
    assert len(lines) == 1
    assert "claim=-" in lines[0]
    assert "contradiction=-" in lines[0]


def test_trace_verify_429(monkeypatch, caplog):
    monkeypatch.setenv("META_DAILY_CAP", "0")
    monkeypatch.setenv("META_API_KEY", "test-key-not-real")
    mop_verify.get_session("http-trace-429")
    caplog.set_level(logging.INFO, logger="mop.trace")
    resp = _call_verify(
        monkeypatch,
        {
            "image": _StubUpload(_split_panel()),
            "step_id": "0",
            "session_id": "http-trace-429",
        },
    )
    body = _resp_body(resp)
    assert resp.status_code == 429
    lines = _trace_lines(caplog)
    assert len(lines) == 1
    assert f"trace={body['trace_id']}" in lines[0]
    assert "event=verify" in lines[0]
    assert "verdict=rate_limited" in lines[0]
    assert "session=http-tra" in lines[0]
    assert "http=429" in lines[0]


def test_trace_session_start_and_restart(caplog):
    caplog.set_level(logging.INFO, logger="mop.trace")
    start_body = _resp_body(_call_session_start({"session_id": "trace-start"}))
    restart_body = _resp_body(_call_session_restart({"session_id": "trace-start"}))
    lines = _trace_lines(caplog)
    assert len(lines) == 2
    assert "event=session_start" in lines[0]
    assert f"trace={start_body['trace_id']}" in lines[0]
    assert "session=trace-st" in lines[0]
    assert "http=200" in lines[0]
    assert "event=restart" in lines[1]
    assert f"trace={restart_body['trace_id']}" in lines[1]
    assert "limit_ip=0/10" in lines[1]
    assert "daily=0/50" in lines[1]


def test_restarts_never_consume_quota(monkeypatch, caplog):
    monkeypatch.setenv("META_API_KEY", "test-key-not-real")
    sam = FakeSAM(boxes=[LEFT_COL, RIGHT_COL])
    spark = FakeSpark(_all(dict.fromkeys(BAND_COLORS.values(), "RIGHT")))
    _inject(monkeypatch, sam, spark)
    caplog.set_level(logging.INFO, logger="mop.trace")
    fresh = None
    for _ in range(20):
        resp = _call_session_restart()
        assert resp.status_code == 200
        fresh = _resp_body(resp)["session"]["session_id"]
    assert get_ip_usage("testclient") == (0, 10)
    assert get_daily_count() == 0
    resp = _call_verify(
        monkeypatch,
        {
            "image": _StubUpload(_split_panel()),
            "step_id": "0",
            "session_id": fresh,
        },
    )
    assert resp.status_code == 200
    lines = _trace_lines(caplog)
    assert "event=restart" in lines[0]
    assert "limit_ip=0/10" in lines[0]
    assert "event=verify" in lines[-1]
    assert "limit_ip=1/10" in lines[-1]
    assert "daily=1/50" in lines[-1]


def test_restart_logs_same_counters_as_verify(monkeypatch, caplog):
    monkeypatch.setenv("META_API_KEY", "test-key-not-real")
    sam = FakeSAM(boxes=[LEFT_COL, RIGHT_COL])
    spark = FakeSpark(_all(dict.fromkeys(BAND_COLORS.values(), "RIGHT")))
    _inject(monkeypatch, sam, spark)
    mop_verify.get_session("http-cmp")
    caplog.set_level(logging.INFO, logger="mop.trace")
    _call_verify(
        monkeypatch,
        {
            "image": _StubUpload(_split_panel()),
            "step_id": "0",
            "session_id": "http-cmp",
        },
    )
    _call_session_restart({"session_id": "http-cmp"})
    lines = _trace_lines(caplog)
    assert len(lines) == 2
    assert "event=verify" in lines[0]
    assert "event=restart" in lines[1]
    for key in ("limit_ip=1/10", "daily=1/50"):
        assert key in lines[0]
        assert key in lines[1]
    assert "meta_calls=0" in lines[1]
    assert "http=200" in lines[1]


class _FakeClock:
    """Injectable session clock: deterministic TTL tests, no sleeps."""

    def __init__(self, start=1_000_000.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def test_session_cap_evicts_least_recently_used(monkeypatch):
    monkeypatch.setenv("MOP_MAX_SESSIONS", "3")
    clock = _FakeClock()
    monkeypatch.setattr(mop_verify, "_session_clock", clock)
    for sid in ("s1", "s2", "s3"):
        mop_verify.get_session(sid)
        clock.advance(10)
    mop_verify.get_session("s1")  # touch: s1 is now most recent
    clock.advance(10)
    mop_verify.get_session("s4")
    assert mop_verify.has_session("s1") is True
    assert mop_verify.has_session("s2") is False
    assert mop_verify.has_session("s3") is True
    assert mop_verify.has_session("s4") is True


def test_evicted_session_409s_with_zero_meta_calls(monkeypatch):
    monkeypatch.setenv("MOP_MAX_SESSIONS", "3")
    monkeypatch.setenv("META_API_KEY", "test-key-not-real")
    sam = FakeSAM(boxes=[LEFT_COL, RIGHT_COL])
    spark = FakeSpark(_all(dict.fromkeys(BAND_COLORS.values(), "RIGHT")))
    _inject(monkeypatch, sam, spark)
    clock = _FakeClock()
    monkeypatch.setattr(mop_verify, "_session_clock", clock)
    for sid in ("s1", "s2", "s3", "s4"):
        mop_verify.get_session(sid)
        clock.advance(10)
    assert mop_verify.has_session("s1") is False
    resp = _call_verify(
        monkeypatch,
        {
            "image": _StubUpload(_split_panel()),
            "step_id": "0",
            "session_id": "s1",
        },
    )
    assert resp.status_code == 409
    assert _resp_body(resp)["error"] == "session_not_found"
    assert sam.calls == 0
    assert spark.calls == 0
    assert get_daily_count() == 0
    assert get_ip_usage("testclient") == (0, 10)


def test_session_ttl_expiry_409s(monkeypatch):
    monkeypatch.setenv("MOP_SESSION_TTL_MIN", "60")
    monkeypatch.setenv("META_API_KEY", "test-key-not-real")
    sam = FakeSAM(boxes=[LEFT_COL, RIGHT_COL])
    spark = FakeSpark(_all(dict.fromkeys(BAND_COLORS.values(), "RIGHT")))
    _inject(monkeypatch, sam, spark)
    clock = _FakeClock()
    monkeypatch.setattr(mop_verify, "_session_clock", clock)
    mop_verify.get_session("ttl-1")
    clock.advance(61 * 60)
    assert mop_verify.has_session("ttl-1") is False
    resp = _call_verify(
        monkeypatch,
        {
            "image": _StubUpload(_split_panel()),
            "step_id": "0",
            "session_id": "ttl-1",
        },
    )
    assert resp.status_code == 409
    assert _resp_body(resp)["error"] == "session_not_found"
    assert sam.calls == 0
    assert spark.calls == 0
    assert get_daily_count() == 0
    assert get_ip_usage("testclient") == (0, 10)


def test_expired_sessions_do_not_evict_live_ones(monkeypatch):
    monkeypatch.setenv("MOP_MAX_SESSIONS", "3")
    monkeypatch.setenv("MOP_SESSION_TTL_MIN", "60")
    clock = _FakeClock()
    monkeypatch.setattr(mop_verify, "_session_clock", clock)
    mop_verify.get_session("s1")
    mop_verify.get_session("s2")
    clock.advance(61 * 60)
    mop_verify.get_session("s3")
    mop_verify.get_session("s4")
    mop_verify.get_session("s5")
    assert mop_verify.has_session("s1") is False
    assert mop_verify.has_session("s2") is False
    assert mop_verify.has_session("s3") is True
    assert mop_verify.has_session("s4") is True
    assert mop_verify.has_session("s5") is True


def test_verify_touch_refreshes_session_ttl(monkeypatch):
    monkeypatch.setenv("MOP_SESSION_TTL_MIN", "60")
    monkeypatch.setenv("META_API_KEY", "test-key-not-real")
    sam = FakeSAM(boxes=[LEFT_COL, RIGHT_COL])
    spark = FakeSpark(_all(dict.fromkeys(BAND_COLORS.values(), "RIGHT")))
    _inject(monkeypatch, sam, spark)
    clock = _FakeClock()
    monkeypatch.setattr(mop_verify, "_session_clock", clock)
    mop_verify.get_session("http-touch")
    clock.advance(59 * 60)
    resp = _call_verify(
        monkeypatch,
        {
            "image": _StubUpload(_split_panel()),
            "step_id": "0",
            "session_id": "http-touch",
        },
    )
    assert resp.status_code == 200
    clock.advance(59 * 60)  # past the original deadline, within the touch deadline
    assert mop_verify.has_session("http-touch") is True
    clock.advance(2 * 60)  # past the touch deadline
    assert mop_verify.has_session("http-touch") is False


def test_restart_old_id_is_unknown_with_zero_meta_calls(monkeypatch):
    monkeypatch.setenv("META_API_KEY", "test-key-not-real")
    sam = FakeSAM(boxes=[LEFT_COL, RIGHT_COL])
    spark = FakeSpark(_all(dict.fromkeys(BAND_COLORS.values(), "RIGHT")))
    _inject(monkeypatch, sam, spark)
    old = _resp_body(_call_session_start({"session_id": "restart-me"}))["session"]["session_id"]
    fresh = _resp_body(_call_session_restart({"session_id": old}))["session"]["session_id"]
    assert fresh != old
    assert mop_verify.has_session(old) is False
    resp = _call_verify(
        monkeypatch,
        {
            "image": _StubUpload(_split_panel()),
            "step_id": "0",
            "session_id": old,
        },
    )
    assert resp.status_code == 409
    assert _resp_body(resp)["error"] == "session_not_found"
    assert sam.calls == 0
    assert spark.calls == 0
    assert get_daily_count() == 0
    assert get_ip_usage("testclient") == (0, 10)


@pytest.mark.parametrize("raw", ["", "abc", "0", "-5"])
def test_session_env_garbage_falls_back_to_defaults(monkeypatch, raw):
    monkeypatch.setenv("MOP_MAX_SESSIONS", raw)
    monkeypatch.setenv("MOP_SESSION_TTL_MIN", raw)
    assert mop_verify.get_max_sessions() == 200
    assert mop_verify.get_session_ttl_min() == 120


def test_session_env_valid_values_are_honoured(monkeypatch):
    monkeypatch.setenv("MOP_MAX_SESSIONS", "3")
    monkeypatch.setenv("MOP_SESSION_TTL_MIN", "30")
    assert mop_verify.get_max_sessions() == 3
    assert mop_verify.get_session_ttl_min() == 30


def test_tool_registered():
    names = [schema["function"]["name"] for schema in TOOL_SCHEMAS]
    assert "verify_photo" in names
    assert "verify_photo" in _TOOL_FNS


def test_tool_needs_stored_photo():
    result = tool_verify_photo({"session_id": "ghost", "step_id": 0})
    assert "no photo" in result["error"]


def test_tool_rejects_bad_step():
    result = tool_verify_photo({"session_id": "ghost", "step_id": 9})
    assert "step_id" in result["error"]


def test_tool_success_feeds_checklist(monkeypatch):
    monkeypatch.setenv("META_API_KEY", "test-key-not-real")
    sam = FakeSAM(boxes=[LEFT_COL, RIGHT_COL])
    spark = FakeSpark(_all(dict.fromkeys(BAND_COLORS.values(), "RIGHT")))
    _inject(monkeypatch, sam, spark)
    mop_verify.store_session_photo("loop-1", _split_panel())

    checklist = {
        "working_hypothesis": "utility_loss",
        "checklist": [
            {
                "id": "CHK-01",
                "question": "Panel matches initial state?",
                "evidence_needed": "photo",
                "is_counter_evidence": False,
            },
            {
                "id": "CHK-02",
                "question": "q2?",
                "evidence_needed": "e2",
                "is_counter_evidence": False,
            },
            {
                "id": "CHK-03",
                "question": "q3?",
                "evidence_needed": "e3",
                "is_counter_evidence": False,
            },
            {
                "id": "CHK-04",
                "question": "q4?",
                "evidence_needed": "e4",
                "is_counter_evidence": True,
            },
        ],
    }
    final = {
        "probable_cause": "utility_loss",
        "confidence": "high",
        "claims": [
            {
                "text": "panel matches initial state",
                "evidence_ids": ["mop-step-0-Q5"],
            }
        ],
        "investigation_checklist": [
            {
                "id": "CHK-01",
                "status": "settled",
                "cited_evidence_ids": ["mop-step-0-Q5"],
            }
        ],
        "unconfirmed": [],
        "verification_checklist": ["photo matches step 0"],
    }
    script = [
        {"choices": [{"message": {"role": "assistant", "content": json.dumps(checklist)}}]},
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "verify_photo",
                                    "arguments": json.dumps({"session_id": "loop-1", "step_id": 0}),
                                },
                            }
                        ],
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-2",
                                "type": "function",
                                "function": {
                                    "name": "query_alarms",
                                    "arguments": json.dumps(
                                        {
                                            "scenario_id": "burst-utility-01",
                                            "window_minutes": 30,
                                        }
                                    ),
                                },
                            }
                        ],
                    }
                }
            ]
        },
        {"choices": [{"message": {"role": "assistant", "content": json.dumps(final)}}]},
    ]

    class ScriptedClient:
        def __init__(self):
            self.calls = list(script)

        def chat(self, messages, tools):
            assert self.calls
            return self.calls.pop(0)

    result = run_investigation("burst-utility-01", client=ScriptedClient())
    assert sorted(result["tools_used"]) == ["query_alarms", "verify_photo"]
    assert result["model_calls"] == 4
    assert result["claims"][0]["verified"] is True
    assert result["investigation_checklist"][0]["status"] == "settled"
    assert get_daily_count() == 1


EXPECTED_CROP_PROMPT = (
    "This is a close-up photo of one circuit breaker. In the middle there is "
    "a rectangular window with a handle inside it, and the handle has a number "
    "printed on it. Is the handle at the LEFT end or the RIGHT end of the "
    "window, as seen in this photo? If the handle or the window is not clearly "
    "visible, or something covers it, answer UNKNOWN. Return only JSON: "
    '{"handle": "LEFT|RIGHT|UNKNOWN", "notes": "short reason"}.'
)


class _FakeHttpResponse:
    def __init__(self, body):
        self._body = body
        self.status_code = 200
        self.text = json.dumps(body)

    def json(self):
        return self._body


class _FakeTransport:
    """httpx.post stand-in: records wire calls, serves canned SAM/Spark bodies."""

    def __init__(self, sam_body, spark_text):
        self.sam_body = sam_body
        self.spark_text = spark_text
        self.calls = []
        self._lock = threading.Lock()

    def __call__(self, url, json=None, headers=None, timeout=None):
        record = {
            "url": url,
            "payload": json,
            "headers": dict(headers or {}),
            "timeout": timeout,
        }
        with self._lock:
            self.calls.append(record)
        if url.endswith("/responses"):
            return _FakeHttpResponse(self.sam_body)
        return _FakeHttpResponse({"choices": [{"message": {"content": self.spark_text}}]})

    def calls_to(self, suffix):
        with self._lock:
            return [call for call in self.calls if call["url"].endswith(suffix)]


def _sam_wire_body(boxes, width=1200, height=1600):
    markers = "".join(
        f"<|box;x1={x1};y1={y1};x2={x2};y2={y2};w={width};h={height}|>" for x1, y1, x2, y2 in boxes
    )
    return {"output": [{"type": "detections", "text": markers}]}


def _run_through_wire(monkeypatch):
    """verify_photo via the REAL client wrappers with the transport patched."""
    monkeypatch.setenv("META_API_KEY", "test-key-not-real")
    monkeypatch.delenv("META_API_URL", raising=False)
    transport = _FakeTransport(
        _sam_wire_body(_direct_boxes()),
        json.dumps({"handle": "RIGHT", "notes": "wire"}),
    )
    monkeypatch.setattr(httpx, "post", transport)
    image = _direct_panel()
    result = mop_verify.verify_photo(0, image)
    return result, transport, image


def test_wire_sam_request_matches_probe_shape(monkeypatch):
    _, transport, image = _run_through_wire(monkeypatch)
    sam_calls = transport.calls_to("/responses")
    assert len(sam_calls) == 1
    call = sam_calls[0]
    assert call["url"] == "https://api.meta.ai/v1/responses"
    assert call["timeout"] == 120.0
    assert call["headers"]["Authorization"] == "Bearer test-key-not-real"
    payload = call["payload"]
    assert payload["model"] == "sam-3.1"
    assert payload["stream"] is False
    assert payload["input"][0]["type"] == "message"
    assert payload["input"][0]["role"] == "user"
    content = payload["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "circuit breaker"}
    assert content[1]["type"] == "input_image"
    data_url = content[1]["image_url"]
    assert data_url.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(data_url.split(",", 1)[1]) == image


def test_wire_spark_crop_request_shape(monkeypatch):
    result, transport, _image = _run_through_wire(monkeypatch)
    spark_calls = transport.calls_to("/chat/completions")
    assert len(spark_calls) == 5
    seen = set()
    for call in spark_calls:
        assert call["url"] == "https://api.meta.ai/v1/chat/completions"
        assert call["timeout"] == 120.0
        payload = call["payload"]
        assert payload["model"] == "muse-spark-1.3"
        assert payload["max_tokens"] == 4000
        assert payload["reasoning_effort"] == "low"
        assert payload["stream"] is False
        assert payload["messages"][0]["role"] == "user"
        content = payload["messages"][0]["content"]
        assert content[0] == {"type": "text", "text": EXPECTED_CROP_PROMPT}
        assert content[1]["type"] == "image_url"
        # A bare string here drew HTTP 400 from the API; it must be an object.
        assert isinstance(content[1]["image_url"], dict)
        data_url = content[1]["image_url"]["url"]
        assert data_url.startswith("data:image/jpeg;base64,")
        crop = base64.b64decode(data_url.split(",", 1)[1])
        assert crop[:2] == b"\xff\xd8"
        seen.add(crop)
    assert len(seen) == 5
    assert result["verdict"] == "MATCH"
    assert result["meta_calls_made"] == 6
