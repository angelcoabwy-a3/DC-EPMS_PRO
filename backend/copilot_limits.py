"""Meta credit protection for the Shift Forensic Investigator.

BUILT DURING THE META GLOBAL AI DEVELOPER HACKATHON (Oct 26 - Nov 4, 2026).

In-memory, thread-safe guard for POST /api/copilot/investigate. Two
independent limits, both enforced BEFORE any Meta API work:

1. Daily cap on Meta calls (UTC date key, resets at UTC midnight):
   from env META_DAILY_CAP, default 50, safe int parsing.
2. Per-IP rate limit on investigate calls: max 10 per IP per rolling
   60 minutes. Timestamps older than 3600 s are pruned on every check.

Only the standard library is used. No tokens, no secrets in this file.

Usage from the endpoint::

    from copilot_limits import MetaLimitError, check_limits

    try:
        check_limits(client_ip)      # records one per-IP hit, or raises
    except MetaLimitError as exc:
        return JSONResponse(status_code=429, ...)

    # ... later, only when the code actually attempts the Meta call:
    from copilot_limits import record_meta_attempt
    record_meta_attempt()

A blocked request is never counted against the daily cap, and the daily
counter only moves when a Meta call is really attempted (a deterministic
fallback returned because no key is configured records nothing).
"""

from __future__ import annotations

import os
import threading
import time
from datetime import UTC, datetime, timedelta

DAILY_CAP_DEFAULT = 50
DAILY_CAP_ENV_VAR = "META_DAILY_CAP"

IP_MAX_CALLS = 10
IP_WINDOW_SECONDS = 3600.0

_lock = threading.Lock()
_daily_counts: dict[str, int] = {}
_ip_hits: dict[str, list[float]] = {}


class MetaLimitError(Exception):
    """Raised by check_limits when a request must not reach the Meta API.

    Attributes:
        limit: "daily_cap" or "per_ip".
        daily_cap: the configured daily cap (for the 429 body).
    """

    def __init__(self, limit: str, message: str, daily_cap: int):
        super().__init__(message)
        self.limit = limit
        self.message = message
        self.daily_cap = daily_cap


def get_daily_cap() -> int:
    """Daily Meta-call cap from META_DAILY_CAP, default 50.

    Garbage values (unset, empty, non-numeric) fall back to 50 instead
    of crashing the endpoint. A parsed value (including 0, which blocks
    all Meta calls) is honoured as configured.
    """
    try:
        return int(str(os.environ.get(DAILY_CAP_ENV_VAR, "")).strip())
    except (ValueError, TypeError, AttributeError):
        return DAILY_CAP_DEFAULT


def _today_key() -> str:
    """UTC date string. The counter resets at UTC midnight, not on restart."""
    return datetime.now(UTC).date().isoformat()


def seconds_until_utc_midnight() -> int:
    """Seconds from now until the next UTC midnight (daily-cap retry hint)."""
    now = datetime.now(UTC)
    today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    return max(1, int(((today_start + timedelta(days=1)) - now).total_seconds()))


def retry_after_for_ip(client_ip: str, now: float | None = None) -> int:
    """Seconds until this IP's oldest in-window hit expires (per-IP hint)."""
    ip = (client_ip or "unknown").strip() or "unknown"
    t = time.time() if now is None else now
    with _lock:
        hits = [h for h in _ip_hits.get(ip, []) if h > t - IP_WINDOW_SECONDS]
        if len(hits) < IP_MAX_CALLS:
            return 0
        return max(1, int(min(hits) + IP_WINDOW_SECONDS - t))


def check_limits(client_ip: str, now: float | None = None) -> int:
    """Run both limits before any Meta work. Returns the daily cap.

    Records one per-IP investigate hit when both limits pass. Raises
    MetaLimitError without recording anything when either limit is
    hit, so a blocked request never counts against the daily cap.
    """
    ip = (client_ip or "unknown").strip() or "unknown"
    cap = get_daily_cap()
    t = time.time() if now is None else now
    with _lock:
        used = _daily_counts.get(_today_key(), 0)
        if used >= cap:
            raise MetaLimitError(
                "daily_cap",
                f"Meta daily cap reached ({used}/{cap} Meta calls used "
                "today, UTC). No Meta call was made for this request.",
                cap,
            )
        hits = [h for h in _ip_hits.get(ip, []) if h > t - IP_WINDOW_SECONDS]
        if len(hits) >= IP_MAX_CALLS:
            _ip_hits[ip] = hits
            raise MetaLimitError(
                "per_ip",
                f"Per-IP rate limit reached ({len(hits)} investigate calls "
                f"from this IP in the last 60 minutes, max {IP_MAX_CALLS}). "
                "No Meta call was made for this request.",
                cap,
            )
        hits.append(t)
        _ip_hits[ip] = hits
        return cap


def record_meta_attempt() -> int:
    """Count one Meta call against today's UTC-date cap. Returns new total.

    Call this only when the code actually attempts the Meta call (after
    the guard passed and the provider is configured), never for a
    deterministic fallback returned for another reason.
    """
    with _lock:
        day = _today_key()
        total = _daily_counts.get(day, 0) + 1
        _daily_counts[day] = total
        return total


def get_daily_count() -> int:
    """Meta calls recorded today (UTC). Debug/testing helper."""
    with _lock:
        return _daily_counts.get(_today_key(), 0)


def reset_for_tests() -> None:
    """Clear all counters. Tests and local verification only."""
    with _lock:
        _daily_counts.clear()
        _ip_hits.clear()
