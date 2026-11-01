"""Offline tests for POST /api/copilot/mop/transcribe (no network, no credits).

A fake speech client stands in for Muse Voice Transcribe; WAV fixtures
are built with struct (valid plus every 400 shape). Route functions are
driven directly with stub requests, like tests/test_mop_verify.py.
"""

import asyncio
import inspect
import json
import logging
import struct
from types import SimpleNamespace

import pytest

import backend.copilot_agent as copilot_agent
from backend.copilot_agent import copilot_mop_transcribe
from backend.copilot_limits import (
    check_limits,
    get_daily_count,
    reset_for_tests,
)


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    reset_for_tests()
    monkeypatch.setattr(copilot_agent, "_default_transcribe_client", None)
    yield
    reset_for_tests()


class _StubUpload:
    """UploadFile stand-in carrying WAV bytes (no sockets, no threadpool)."""

    def __init__(self, data: bytes, filename: str = "readback.wav"):
        self._data = data
        self.filename = filename

    async def read(self):
        await asyncio.sleep(0)
        return self._data


class _StubRequest:
    """Request stand-in: canned form fields plus a fixed client address."""

    def __init__(self, fields):
        self._fields = dict(fields)
        self.client = SimpleNamespace(host="testclient", port=50000)

    async def form(self):
        await asyncio.sleep(0)
        return dict(self._fields)


class _FakeSpeech:
    """Speech client stand-in: records calls, returns a canned transcript."""

    def __init__(self, transcript: str):
        self.transcript = transcript
        self.calls = 0
        self.audio: list = []
        self.filenames: list = []

    def __call__(self, wav_bytes: bytes, filename: str = "readback.wav") -> str:
        self.calls += 1
        self.audio.append(wav_bytes)
        self.filenames.append(filename)
        return self.transcript


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


def _call_transcribe(monkeypatch, fields):
    monkeypatch.setattr(asyncio, "to_thread", _immediate_to_thread)
    return _drive(copilot_mop_transcribe(_StubRequest(fields)))


def _resp_body(resp):
    return json.loads(resp.body)


def _wav_bytes(seconds=1.0, channels=1, rate=24000, bits=16, comptype=1):
    nframes = int(seconds * rate)
    data = b"\x00" * (nframes * channels * (bits // 8))
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(data),
        b"WAVE",
        b"fmt ",
        16,
        comptype,
        channels,
        rate,
        rate * channels * (bits // 8),
        channels * (bits // 8),
        bits,
        b"data",
        len(data),
    )
    return header + data


def test_missing_audio_is_400(monkeypatch):
    resp = _call_transcribe(monkeypatch, {})
    assert resp.status_code == 400
    assert _resp_body(resp)["error"] == "invalid_request"


def test_empty_audio_is_400(monkeypatch):
    resp = _call_transcribe(monkeypatch, {"audio": _StubUpload(b"")})
    assert resp.status_code == 400
    assert "non-empty" in _resp_body(resp)["detail"]


def test_wrong_format_is_400(monkeypatch):
    resp = _call_transcribe(monkeypatch, {"audio": _StubUpload(b"not a wav file at all")})
    assert resp.status_code == 400
    assert _resp_body(resp)["error"] == "invalid_request"


def test_non_pcm_is_400(monkeypatch):
    resp = _call_transcribe(monkeypatch, {"audio": _StubUpload(_wav_bytes(comptype=3))})
    assert resp.status_code == 400


def test_stereo_is_400(monkeypatch):
    resp = _call_transcribe(monkeypatch, {"audio": _StubUpload(_wav_bytes(channels=2))})
    assert resp.status_code == 400
    assert "mono" in _resp_body(resp)["detail"]


def test_wrong_sample_rate_is_400(monkeypatch):
    resp = _call_transcribe(monkeypatch, {"audio": _StubUpload(_wav_bytes(rate=8000))})
    assert resp.status_code == 400
    assert "24000" in _resp_body(resp)["detail"]


def test_truncated_is_400(monkeypatch):
    full = _wav_bytes(seconds=2.0)
    resp = _call_transcribe(monkeypatch, {"audio": _StubUpload(full[: len(full) // 2])})
    assert resp.status_code == 400
    assert "truncated" in _resp_body(resp)["detail"]


def test_too_long_is_400(monkeypatch):
    resp = _call_transcribe(monkeypatch, {"audio": _StubUpload(_wav_bytes(seconds=11.0))})
    assert resp.status_code == 400
    assert "longer than" in _resp_body(resp)["detail"]


def test_guard_429_before_any_meta_call(monkeypatch):
    monkeypatch.setenv("META_DAILY_CAP", "0")
    monkeypatch.setenv("META_API_KEY", "test-key-not-real")
    fake = _FakeSpeech("step two, Q eight, on,")
    monkeypatch.setattr(copilot_agent, "_default_transcribe_client", fake)
    resp = _call_transcribe(monkeypatch, {"audio": _StubUpload(_wav_bytes())})
    assert resp.status_code == 429
    body = _resp_body(resp)
    assert body["error"] == "limit_exceeded"
    assert body["meta_call_made"] is False
    assert resp.headers["Retry-After"] == str(body["retry_after_s"])
    assert fake.calls == 0
    assert get_daily_count() == 0


def test_per_ip_429_detail_uses_new_wording(monkeypatch):
    monkeypatch.setenv("META_API_KEY", "test-key-not-real")
    fake = _FakeSpeech("step two, Q eight, on,")
    monkeypatch.setattr(copilot_agent, "_default_transcribe_client", fake)
    for _ in range(10):
        check_limits("testclient")
    resp = _call_transcribe(monkeypatch, {"audio": _StubUpload(_wav_bytes())})
    assert resp.status_code == 429
    body = _resp_body(resp)
    assert body["limit"] == "per_ip"
    assert "Meta-backed requests" in body["detail"]
    assert fake.calls == 0


def test_success_returns_transcript_and_claim(monkeypatch):
    monkeypatch.setenv("META_API_KEY", "test-key-not-real")
    fake = _FakeSpeech("step two, Q eight, on,")
    monkeypatch.setattr(copilot_agent, "_default_transcribe_client", fake)
    resp = _call_transcribe(monkeypatch, {"audio": _StubUpload(_wav_bytes())})
    assert resp.status_code == 200
    body = _resp_body(resp)
    assert body["transcript"] == "step two, Q eight, on,"
    assert body["claim"] == {"label": "Q8", "state": "CLOSED"}
    assert body["rejection_reason"] is None
    assert body["model"] == "muse-voice-transcribe-1.0"
    assert body["meta_call_made"] is True
    assert fake.calls == 1
    assert get_daily_count() == 1


def test_success_with_stt_letter_spelling(monkeypatch):
    monkeypatch.setenv("META_API_KEY", "test-key-not-real")
    fake = _FakeSpeech("Step two, cue eight. On.")
    monkeypatch.setattr(copilot_agent, "_default_transcribe_client", fake)
    resp = _call_transcribe(monkeypatch, {"audio": _StubUpload(_wav_bytes())})
    assert resp.status_code == 200
    assert _resp_body(resp)["claim"] == {"label": "Q8", "state": "CLOSED"}


def test_rejected_transcript_returns_reason(monkeypatch):
    monkeypatch.setenv("META_API_KEY", "test-key-not-real")
    fake = _FakeSpeech("hello there")
    monkeypatch.setattr(copilot_agent, "_default_transcribe_client", fake)
    resp = _call_transcribe(monkeypatch, {"audio": _StubUpload(_wav_bytes())})
    assert resp.status_code == 200
    body = _resp_body(resp)
    assert body["claim"] is None
    assert body["rejection_reason"] == "no breaker label or state word heard"


OBSERVED_TRANSCRIBE_BODY = {
    "audioDurationMs": 3760,
    "sessionId": "voyager/transcribe/61A7D2D2A02640CBB17796DD5BA56E9E",
    "transcript": "Step two, cue eight, on.",
    "turns": [],
}


def test_extract_transcript_reads_observed_response_structure():
    assert (
        copilot_agent._extract_transcript(dict(OBSERVED_TRANSCRIBE_BODY))
        == "Step two, cue eight, on."
    )


def test_endpoint_forwards_upload_filename(monkeypatch):
    monkeypatch.setenv("META_API_KEY", "test-key-not-real")
    fake = _FakeSpeech("step two, Q eight, on,")
    monkeypatch.setattr(copilot_agent, "_default_transcribe_client", fake)
    resp = _call_transcribe(
        monkeypatch, {"audio": _StubUpload(_wav_bytes(), "readback_s2_q8_on.wav")}
    )
    assert resp.status_code == 200
    assert fake.filenames == ["readback_s2_q8_on.wav"]


def test_503_without_key(monkeypatch):
    monkeypatch.delenv("META_API_KEY", raising=False)
    fake = _FakeSpeech("step two, Q eight, on,")
    monkeypatch.setattr(copilot_agent, "_default_transcribe_client", fake)
    resp = _call_transcribe(monkeypatch, {"audio": _StubUpload(_wav_bytes())})
    assert resp.status_code == 503
    assert _resp_body(resp)["meta_call_made"] is False
    assert fake.calls == 0


def _trace_lines(caplog):
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "mop.trace" and record.getMessage().startswith("MOP_TRACE")
    ]


def test_trace_transcribe_success(monkeypatch, caplog):
    monkeypatch.setenv("META_API_KEY", "test-key-not-real")
    fake = _FakeSpeech("step two, Q eight, on,")
    monkeypatch.setattr(copilot_agent, "_default_transcribe_client", fake)
    caplog.set_level(logging.INFO, logger="mop.trace")
    resp = _call_transcribe(monkeypatch, {"audio": _StubUpload(_wav_bytes())})
    body = _resp_body(resp)
    assert resp.status_code == 200
    lines = _trace_lines(caplog)
    assert len(lines) == 1
    line = lines[0]
    assert f"trace={body['trace_id']}" in line
    assert "event=transcribe" in line
    assert "claim=Q8:CLOSED" in line
    assert "meta_calls=1" in line
    assert "http=200" in line
    assert "limit_ip=1/10" in line
    assert "daily=1/50" in line
    # Privacy: parsed claim only, never the raw transcript or audio bytes.
    assert "step two, Q eight, on," not in line
    assert "Bearer" not in line
    assert len(line) < 500


def test_trace_transcribe_429(monkeypatch, caplog):
    monkeypatch.setenv("META_DAILY_CAP", "0")
    monkeypatch.setenv("META_API_KEY", "test-key-not-real")
    fake = _FakeSpeech("step two, Q eight, on,")
    monkeypatch.setattr(copilot_agent, "_default_transcribe_client", fake)
    caplog.set_level(logging.INFO, logger="mop.trace")
    resp = _call_transcribe(monkeypatch, {"audio": _StubUpload(_wav_bytes())})
    body = _resp_body(resp)
    assert resp.status_code == 429
    lines = _trace_lines(caplog)
    assert len(lines) == 1
    assert f"trace={body['trace_id']}" in lines[0]
    assert "event=transcribe" in lines[0]
    assert "verdict=rate_limited" in lines[0]
    assert "http=429" in lines[0]
    assert fake.calls == 0


def test_trace_transcribe_unparsed_claim(monkeypatch, caplog):
    monkeypatch.setenv("META_API_KEY", "test-key-not-real")
    fake = _FakeSpeech("hello there")
    monkeypatch.setattr(copilot_agent, "_default_transcribe_client", fake)
    caplog.set_level(logging.INFO, logger="mop.trace")
    resp = _call_transcribe(monkeypatch, {"audio": _StubUpload(_wav_bytes())})
    assert resp.status_code == 200
    lines = _trace_lines(caplog)
    assert len(lines) == 1
    assert "claim=unparsed" in lines[0]
    assert "hello there" not in lines[0]
