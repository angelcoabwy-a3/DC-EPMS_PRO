"""Meta API probe: tool calling, image input, SAM docs, contributor model.

HACKATHON diagnostic script. Makes a handful of cheap model calls only:
max_tokens 200 each, one attempt per test, no retries, 30 s timeout.

Secrets: the API key comes ONLY from the META_API_KEY environment variable
and is NEVER printed. Every line printed passes through _scrub, which
redacts the key value if it ever appears in an error or payload echo.

Run from the repo root (key never on the command line, only in the env):
    META_API_KEY=<key> META_MODEL=muse-spark-1.3 python scripts/probe_meta.py

Exit code is 0 when every test PASSes, 1 otherwise.
"""

import base64
import os
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from backend.llm_providers import MetaProvider

SAM_DOCS_URL = "https://dev.meta.ai/docs/sam/overview"  # the one documented URL; no others
CONTRIBUTOR_MODEL = "muse-spark-1.3-contributor"
TIMEOUT_S = 30.0
MAX_TOKENS = 200


def _scrub(text: str) -> str:
    """Redact the key value from anything about to be printed."""
    key = os.environ.get("META_API_KEY", "")
    if key and len(key) >= 4:
        text = text.replace(key, "[REDACTED]")
    return text


def _endpoint():
    """Same base URL and auth header MetaProvider already uses."""
    provider = MetaProvider()
    url = f"{provider.api_url}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {provider.api_key}",
    }
    return provider, url, headers


def _post(url, headers, payload):
    """One non-streaming chat call. No retries. Returns (status, data, error)."""
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=TIMEOUT_S)
    except Exception as e:
        return None, None, f"{type(e).__name__}: {e}"
    try:
        data = resp.json()
    except Exception:
        data = None
    if resp.status_code != 200:
        body = (resp.text or "")[:200]
        return resp.status_code, data, f"HTTP {resp.status_code}: {body}"
    if not data:
        return resp.status_code, data, "HTTP 200 with empty/non-JSON body"
    return resp.status_code, data, ""


def _assistant_text(data):
    try:
        msg = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return "", "no choices[0].message in response"
    text = msg.get("content") or ""
    return (text if isinstance(text, str) else ""), ""


def test_tool_calling():
    """Force one get_alarm_count tool call with META_MODEL."""
    provider, url, headers = _endpoint()
    if not provider.is_configured:
        return ("tool-calling", False, "META_API_KEY not set; no request attempted")
    payload = {
        "model": provider.model,
        "max_tokens": MAX_TOKENS,
        "reasoning_effort": "low",
        "stream": False,
        "messages": [
            {"role": "user", "content": "How many open alarms are there right now?"},
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "get_alarm_count",
                    "description": "Return the number of currently open alarms.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
            },
        ],
        "tool_choice": {"type": "function", "function": {"name": "get_alarm_count"}},
    }
    status, data, error = _post(url, headers, payload)
    if error or data is None:
        return ("tool-calling", False, f"model={provider.model} error={error}")
    try:
        msg = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return ("tool-calling", False, f"model={provider.model} no choices[0].message")
    calls = msg.get("tool_calls") or []
    if not calls:
        return (
            "tool-calling",
            False,
            f"model={provider.model} no tool call returned "
            f"(finish_reason={msg.get('finish_reason')})",
        )
    first = calls[0]
    fn = first.get("function") or {}
    return (
        "tool-calling",
        True,
        f"model={provider.model} tool_call name={fn.get('name')} "
        f"arguments={fn.get('arguments')}",
    )


def _red_png(width=8, height=8):
    """Solid-red PNG built with zlib + struct only (no imaging deps)."""

    def chunk(chunk_type, data):
        head = struct.pack(">I", len(data)) + chunk_type + data
        return head + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def test_image(model_label, model_name):
    """Ask what single color a generated solid-red PNG is. PASS iff 'red'."""
    provider, url, headers = _endpoint()
    if not provider.is_configured:
        return (f"image-{model_label}", False, "META_API_KEY not set; no request attempted")
    png_b64 = base64.b64encode(_red_png()).decode("ascii")
    payload = {
        "model": model_name,
        "max_tokens": MAX_TOKENS,
        "reasoning_effort": "low",
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What single color is this image?"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png_b64}"}},
                ],
            },
        ],
    }
    status, data, error = _post(url, headers, payload)
    if error or data is None:
        return (f"image-{model_label}", False, f"model={model_name} error={error}")
    text, parse_error = _assistant_text(data)
    if parse_error:
        return (f"image-{model_label}", False, f"model={model_name} {parse_error}")
    if "red" in text.lower():
        return (f"image-{model_label}", True, f"model={model_name} answer={text[:200]!r}")
    return (
        f"image-{model_label}",
        False,
        f"model={model_name} answer missing 'red': {text[:200]!r}",
    )


def test_sam_docs():
    """Read the SAM overview docs page. No guessing of other URLs."""
    try:
        resp = httpx.get(SAM_DOCS_URL, timeout=15.0, follow_redirects=True)
    except Exception as e:
        return ("sam-docs", False, f"could not read {SAM_DOCS_URL}: {type(e).__name__}: {e}")
    if resp.status_code != 200:
        return ("sam-docs", False, f"could not read {SAM_DOCS_URL}: HTTP {resp.status_code}")
    body = resp.text or ""
    if not body.strip():
        return ("sam-docs", False, f"could not read {SAM_DOCS_URL}: HTTP 200 with empty body")
    mentions = "mentions SAM" if "sam" in body.lower() else "does not mention SAM"
    return ("sam-docs", True, f"HTTP 200, {len(body)} bytes, {mentions}")


def test_contributor():
    """Diagnostic only: one minimal chat call to the contributor model."""
    provider, url, headers = _endpoint()
    if not provider.is_configured:
        return ("contributor", False, "META_API_KEY not set; no request attempted")
    payload = {
        "model": CONTRIBUTOR_MODEL,
        "max_tokens": MAX_TOKENS,
        "reasoning_effort": "low",
        "stream": False,
        "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
    }
    status, data, error = _post(url, headers, payload)
    if error or data is None:
        return ("contributor", False, f"model={CONTRIBUTOR_MODEL} error={error}")
    text, parse_error = _assistant_text(data)
    if parse_error:
        return ("contributor", False, f"model={CONTRIBUTOR_MODEL} {parse_error}")
    if not text.strip():
        return ("contributor", False, f"model={CONTRIBUTOR_MODEL} HTTP 200 with empty content")
    return ("contributor", True, f"model={CONTRIBUTOR_MODEL} answer={text[:200]!r}")


def main() -> int:
    provider = MetaProvider()
    model = provider.model
    print(f"key: {'set (hidden)' if provider.is_configured else 'NOT SET'}")
    print(f"base_url: {provider.api_url}")
    results = [
        test_tool_calling(),
        test_image("meta-model", model),
        test_image("spark-1.1", "muse-spark-1.1"),
        test_sam_docs(),
        test_contributor(),
    ]
    failed = 0
    for name, passed, detail in results:
        print(f"TEST {name}: {'PASS' if passed else 'FAIL'} - {_scrub(detail)}")
        failed += 0 if passed else 1
    print(f"SUMMARY: {len(results) - failed}/{len(results)} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
