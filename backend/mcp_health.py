"""
backend/mcp_health.py
=====================
MCP / Discipline AI health probe (S-MCP-HEALTH-01 option (ii)).

The Procedure Architect audit gate enforces (CAUTION level) that MOPs
mention the MCP / Agent health check in §3. Option (i) was a pure
string-match -- it could be satisfied by an operator typing the word
"MCP" without actually verifying the agents are reachable. Option
(ii) -- this module -- adds a real network probe.

Architecture:

  * **Background asyncio task** in the FastAPI lifespan polls the
    configured URL every ``DC_EPMS_MCP_PROBE_INTERVAL_S`` seconds
    (default 60s). Result is written to module-level state.
  * **Sync read API** ``get_mcp_health()`` lets the audit gate read
    the cached state without touching I/O. Microsecond latency,
    deterministic, no async-from-sync acrobatics.
  * **Default OFF** -- ``DC_EPMS_MCP_PROBE`` env var must be ``true``
    / ``1`` / ``yes`` to enable. When disabled, the audit gate sees
    state=None and skips the probe-based finding, preserving the
    legacy string-match behavior 1:1.

Probe URL:
  * Default ``http://127.0.0.1:1234/v1/models`` (LM Studio's OpenAI-
    compatible endpoint -- the concrete backend every Discipline AI
    agent calls). If LM Studio is up, the agents are reachable.
  * Override via ``DC_EPMS_MCP_PROBE_URL`` for deployments that route
    through a real MCP server / proxy.

Failure semantics:
  * Probe times out / returns non-200 / network unreachable ->
    ``_mcp_healthy = False``, audit fires a CAUTION finding annotating
    the probe reason.
  * Probe succeeds -> ``_mcp_healthy = True``, no probe-related
    finding (string-match rule still applies independently).
  * Probe disabled or never run -> ``_mcp_healthy = None``, audit
    behaves exactly as it did in v0.16.0 (string-match only).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any
from urllib import error, request

log = logging.getLogger(__name__)

# ─── Configuration (env-var driven) ───────────────────────────────────
PROBE_ENABLED: bool = os.environ.get(
    "DC_EPMS_MCP_PROBE", "false",
).lower() in ("true", "1", "yes", "on")

PROBE_URL: str = os.environ.get(
    "DC_EPMS_MCP_PROBE_URL", "http://127.0.0.1:1234/v1/models",
)

PROBE_INTERVAL_S: int = int(os.environ.get("DC_EPMS_MCP_PROBE_INTERVAL_S", "60"))
PROBE_TIMEOUT_S: int = int(os.environ.get("DC_EPMS_MCP_PROBE_TIMEOUT_S", "5"))


# ─── Module state (read by audit_procedure_safety) ────────────────────
# tri-state:
#   None  -> probe disabled OR never run; audit skips probe-based finding
#   True  -> last probe succeeded
#   False -> last probe failed
_mcp_healthy: bool | None = None
_last_probe_unix: float = 0.0
_last_probe_reason: str = ""


def get_mcp_health() -> tuple[bool | None, str, float]:
    """Sync read of the cached MCP health state.

    Returns ``(state, reason, last_probe_unix)``:
      * ``state`` -- None (disabled), True (healthy), False (unhealthy).
      * ``reason`` -- human-readable diagnostic string.
      * ``last_probe_unix`` -- unix timestamp of last probe attempt.

    Audit gate uses this for the S-MCP-HEALTH-01 option (ii) finding.
    """
    return (_mcp_healthy, _last_probe_reason, _last_probe_unix)


def _set_mcp_health_for_test(
    state: bool | None,
    reason: str = "test-injected",
    ts: float | None = None,
) -> None:
    """Test helper -- directly inject probe state. Bypasses the
    background task and the network."""
    global _mcp_healthy, _last_probe_reason, _last_probe_unix
    _mcp_healthy = state
    _last_probe_reason = reason
    _last_probe_unix = ts if ts is not None else time.time()


def _reset_mcp_health_for_test() -> None:
    """Test helper -- reset to disabled state."""
    global _mcp_healthy, _last_probe_reason, _last_probe_unix
    _mcp_healthy = None
    _last_probe_reason = ""
    _last_probe_unix = 0.0


# ─── Probe implementation ─────────────────────────────────────────────
def probe_mcp_sync() -> tuple[bool, str]:
    """Single synchronous probe of the configured URL. Returns
    ``(healthy, reason)``. NOT awaitable -- safe to call from sync
    contexts (the background task runs this in an executor)."""
    try:
        req = request.Request(PROBE_URL, headers={"Accept": "application/json"})
        with request.urlopen(req, timeout=PROBE_TIMEOUT_S) as resp:
            status = getattr(resp, "status", 200)
            if 200 <= status < 300:
                return (True, f"HTTP {status} from {PROBE_URL}")
            return (False, f"HTTP {status} from {PROBE_URL}")
    except error.URLError as e:
        # Includes timeouts, connection refused, DNS failure.
        return (False, f"URLError: {e.reason}")
    except OSError as e:
        return (False, f"OSError: {e}")
    except Exception as e:
        return (False, f"probe error: {type(e).__name__}: {e}")


async def _probe_loop() -> None:
    """Background task: probe every ``PROBE_INTERVAL_S`` seconds,
    update module state. Runs forever; cancel via task.cancel().

    Runs ``probe_mcp_sync`` in an executor so the probe network call
    does not block the event loop. Even at the default 60s cadence,
    blocking would only stall for ``PROBE_TIMEOUT_S`` worst-case --
    but cleanliness is cheap.
    """
    global _mcp_healthy, _last_probe_unix, _last_probe_reason
    while True:
        try:
            loop = asyncio.get_running_loop()
            healthy, reason = await loop.run_in_executor(None, probe_mcp_sync)
            _mcp_healthy = healthy
            _last_probe_unix = time.time()
            _last_probe_reason = reason
            log.debug(
                "[mcp_health] probe iteration: healthy=%s reason=%s",
                healthy, reason,
            )
        except asyncio.CancelledError:
            log.info("[mcp_health] probe loop cancelled (clean shutdown)")
            raise
        except Exception as e:
            _mcp_healthy = False
            _last_probe_reason = f"probe loop error: {e}"
            _last_probe_unix = time.time()
            log.warning("[mcp_health] probe iteration failed: %s", e)
        await asyncio.sleep(PROBE_INTERVAL_S)


def start_probe_background_task(
    loop: asyncio.AbstractEventLoop,
) -> Any | None:
    """Lifespan hook -- starts the background probe loop if the env
    flag is set. Returns the Task handle (so the caller can cancel
    on shutdown) or None if probe is disabled.

    Does an initial sync probe before scheduling the background loop
    so the first audit call sees a fresh result instead of None.
    """
    global _mcp_healthy, _last_probe_reason, _last_probe_unix
    if not PROBE_ENABLED:
        log.info(
            "[mcp_health] probe DISABLED (set DC_EPMS_MCP_PROBE=true "
            "to enable runtime probing of %s)", PROBE_URL,
        )
        _mcp_healthy = None
        return None

    log.info(
        "[mcp_health] probe ENABLED -- url=%s interval=%ds timeout=%ds",
        PROBE_URL, PROBE_INTERVAL_S, PROBE_TIMEOUT_S,
    )
    # Initial sync probe -- the first audit shouldn't see stale None.
    healthy, reason = probe_mcp_sync()
    _mcp_healthy = healthy
    _last_probe_reason = reason
    _last_probe_unix = time.time()
    log.info(
        "[mcp_health] initial probe: healthy=%s reason=%s",
        healthy, reason,
    )
    return loop.create_task(_probe_loop())
