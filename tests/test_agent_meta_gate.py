"""Quota gate for model_hint="meta" on the classic Agent Copilot path.

POST /agent/stream accepts model_hint="meta" (backend/main.py AgentQuery)
and AgentEngine.stream() routed it straight to MetaProvider with no
check_limits accounting, so the public demo could spend Meta credits
without the per-IP limit or the daily cap. The gate: unless the env var
AGENT_META_ENABLED is exactly "1", stream() yields the sentinel
"[Meta backend disabled on this deployment]" and returns without
constructing MetaProvider (no import effect, no network).

All tests are offline: MetaProvider is always a spy/fake, never real.
"""

import inspect
import sys
from typing import ClassVar

import pytest

import backend.llm_providers as llm_providers
from backend.agent_engine import AgentEngine

SENTINEL = "[Meta backend disabled on this deployment]"


def _drive(awaitable):
    """Run a coroutine chain with no event loop (pure in-memory awaits).

    Same pump as tests/test_mop_transcribe.py: the sandbox forbids the
    socketpair asyncio.new_event_loop() needs on Windows, so no loop.
    """
    gen = awaitable.__await__()
    value = None
    while True:
        try:
            yielded = gen.send(value)
        except StopIteration as done:
            return done.value
        value = _drive(yielded) if inspect.isawaitable(yielded) else None


def _drain(agen):
    """Collect an async generator into a list with no event loop."""
    out = []
    while True:
        try:
            out.append(_drive(agen.__anext__()))
        except StopAsyncIteration:
            return out


def _engine():
    # No key, no RAG, unreachable LM Studio URL: any network attempt would
    # fail, so every hermetic test below must pass without touching it.
    return AgentEngine(
        lm_studio_url="http://127.0.0.1:9",
        anthropic_api_key="",
        rag_service=None,
    )


@pytest.fixture
def meta_spy(monkeypatch):
    """Route `from llm_providers import MetaProvider` (as _stream_meta does
    it) at a recording fake. Fails the test if the real class is used."""

    class SpyProvider:
        constructions: ClassVar[list] = []
        stream_calls: ClassVar[list] = []
        tokens: ClassVar[list] = ["meta-token-1", "meta-token-2"]

        def __init__(self, *args, **kwargs):
            type(self).constructions.append((args, kwargs))

        async def stream(self, prompt, max_tokens=500):
            type(self).stream_calls.append((prompt, max_tokens))
            for token in type(self).tokens:
                yield token

    SpyProvider.constructions.clear()
    SpyProvider.stream_calls.clear()
    # _stream_meta imports the top-level name; bind it to the same module
    # object the backend package uses, then swap the class on it.
    monkeypatch.setitem(sys.modules, "llm_providers", llm_providers)
    monkeypatch.setattr(llm_providers, "MetaProvider", SpyProvider)
    return SpyProvider


@pytest.mark.parametrize("env_value", [None, "0", "true"])
def test_meta_disabled_yields_sentinel_without_provider(monkeypatch, meta_spy, env_value):
    """Unset / "0" / "true": sentinel only, MetaProvider never constructed."""
    if env_value is None:
        monkeypatch.delenv("AGENT_META_ENABLED", raising=False)
    else:
        monkeypatch.setenv("AGENT_META_ENABLED", env_value)
    tokens = _drain(_engine().stream("UPS status summary", model_hint="meta"))
    assert tokens == [SENTINEL]
    assert meta_spy.constructions == []
    assert meta_spy.stream_calls == []


def test_meta_enabled_uses_provider(monkeypatch, meta_spy):
    """AGENT_META_ENABLED="1": the Meta path runs (mocked, no network)."""
    monkeypatch.setenv("AGENT_META_ENABLED", "1")
    engine = _engine()
    tokens = _drain(engine.stream("UPS status summary", model_hint="meta"))
    assert tokens == ["meta-token-1", "meta-token-2"]
    assert len(meta_spy.constructions) == 1
    assert len(meta_spy.stream_calls) == 1
    prompt, max_tokens = meta_spy.stream_calls[0]
    assert "UPS status summary" in prompt
    assert max_tokens == 500


@pytest.mark.parametrize("env_value", [None, "1"])
def test_claude_path_unchanged(monkeypatch, meta_spy, env_value):
    """model_hint="claude" behaves as before, whatever the gate env says."""
    if env_value is None:
        monkeypatch.delenv("AGENT_META_ENABLED", raising=False)
    else:
        monkeypatch.setenv("AGENT_META_ENABLED", env_value)
    tokens = _drain(_engine().stream("Explain the UPS bypass interlock", model_hint="claude"))
    assert tokens == ["[Claude API key not configured]"]
    assert meta_spy.constructions == []


def test_auto_path_unchanged(monkeypatch, meta_spy):
    """model_hint="auto" still routes a non-routine query to Claude."""

    async def _probe_must_not_run(self):
        raise AssertionError("probe_gemma must not run for this query")

    async def _fake_claude(self, prompt, max_tokens):
        yield "CLAUDE-MARKER"

    monkeypatch.delenv("AGENT_META_ENABLED", raising=False)
    monkeypatch.setattr(AgentEngine, "probe_gemma", _probe_must_not_run)
    monkeypatch.setattr(AgentEngine, "_stream_claude", _fake_claude)
    tokens = _drain(_engine().stream("Explain the UPS bypass interlock", model_hint="auto"))
    assert tokens == ["CLAUDE-MARKER"]
    assert meta_spy.constructions == []


def test_gemma_path_unchanged(monkeypatch, meta_spy):
    """model_hint="gemma" still routes to the Gemma streamer."""

    async def _fake_gemma(self, prompt, max_tokens):
        yield "GEMMA-MARKER"

    monkeypatch.delenv("AGENT_META_ENABLED", raising=False)
    monkeypatch.setattr(AgentEngine, "_stream_gemma", _fake_gemma)
    tokens = _drain(_engine().stream("UPS status summary", model_hint="gemma"))
    assert tokens == ["GEMMA-MARKER"]
    assert meta_spy.constructions == []
