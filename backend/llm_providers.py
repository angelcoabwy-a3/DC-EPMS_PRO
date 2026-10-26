"""LLM provider adapters - streaming chat completions.

Each provider exposes the same shape:

    provider = MetaProvider(system_prompt="...")
    provider.is_configured          # False until credentials are present
    async for token in provider.stream(prompt, max_tokens):
        ...

The Meta provider speaks the OpenAI-compatible ``/v1/chat/completions``
SSE protocol (same wire shape the codebase already uses for the
Gemma/LM Studio path in agent_engine._stream_gemma), so activating it is
a configuration change, not a rewrite:

    export META_API_KEY="<key from Meta>"          # required
    export META_API_URL="https://<meta-endpoint>" # only if it differs
                                                  # from the default below

Without a key the provider yields the ``[Meta API key not configured]``
sentinel, mirroring the existing Claude path's behaviour.
"""

from __future__ import annotations

import json
import os
from typing import AsyncIterator

import httpx

# Default endpoint. Confirm against the official Meta Model API docs
# once credentials are issued; override with META_API_URL if needed.
DEFAULT_META_API_URL = "https://api.meta.ai/v1"

_NOT_CONFIGURED = "[Meta API key not configured]"


class MetaProvider:
    """Meta Model API streaming provider (OpenAI-compatible SSE)."""

    def __init__(
        self,
        api_key: str | None = None,
        api_url: str | None = None,
        model: str | None = None,
        system_prompt: str = "",
    ):
        self.api_key = api_key or os.environ.get("META_API_KEY", "")
        self.api_url = (api_url or os.environ.get("META_API_URL", "") or DEFAULT_META_API_URL).rstrip("/")
        self.model = model or os.environ.get("META_MODEL", "meta-default")
        self.system_prompt = system_prompt

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def probe(self) -> bool:
        """True when a key is present. (No network call in this MVP.)"""
        return self.is_configured

    async def stream(self, prompt: str, max_tokens: int = 500) -> AsyncIterator[str]:
        if not self.is_configured:
            yield _NOT_CONFIGURED
            return

        url = f"{self.api_url}/chat/completions"
        # Muse Spark is a reasoning model: reasoning tokens are mandatory
        # and count against the output cap. With a small cap (e.g. 800)
        # reasoning can eat the whole budget and return no visible text.
        # Keep reasoning effort low for this short, evidence-bound task
        # and let the caller pass a larger cap (forensic uses 4000).
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "reasoning_effort": "low",
            "stream": True,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        try:
            async with httpx.AsyncClient(timeout=120.0) as client, client.stream(
                "POST", url, json=payload, headers=headers
            ) as resp:
                if resp.status_code == 401:
                    yield "[Meta API: invalid key (401)]"
                    return
                if resp.status_code != 200:
                    yield f"[Meta API error {resp.status_code}]"
                    return
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        delta = obj.get("choices", [{}])[0].get("delta", {})
                        token = delta.get("content", "")
                        if token:
                            yield token
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            yield f"[Meta stream error: {e}]"


def get_provider(name: str, **kwargs):
    """Factory. Currently: 'meta'. Extend here for new providers."""
    if name == "meta":
        return MetaProvider(**kwargs)
    raise ValueError(f"unknown LLM provider: {name!r}")
