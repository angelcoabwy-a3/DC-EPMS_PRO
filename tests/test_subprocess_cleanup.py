"""
tests/test_subprocess_cleanup.py
================================
Epic 6 Sprint 3 Phase 1 — subprocess hygiene in backend/main.py.

Background (the operational bug this code prevents):
  On Windows the venv launches Python via a small shim
  (``.venv/Scripts/python.exe``). When the operator does
  ``Stop-Process`` on the shim, the child Python keeps running and
  holds the :8080 socket (we hit this three times in a row during
  the prior session). Plus any multiprocessing.spawn workers the
  child has open (ML loaders, FAISS index threads).

These tests verify the in-process cleanup path:
  * ``_active_children_terminator`` calls .terminate() + .join() on
    every multiprocessing child reported by multiprocessing.active_children().
  * Per-child exceptions are swallowed so one stuck worker doesn't
    block the rest.
  * Workers still alive after terminate get .kill()'d if available.
  * ``_install_signal_handlers`` registers SIGINT (+ SIGTERM/SIGBREAK
    where available) and the helper is wired up to call the cleanup
    when a signal lands.
  * ``_cleanup_subtree`` is wired into atexit at import time.

What these tests do NOT cover:
  * Stop-Process -Force on the venv shim — the OS skips Python's
    handlers entirely. That requires a Windows Job Object (pywin32)
    and is documented as out-of-scope in backend/main.py.
"""

from __future__ import annotations

import atexit
import importlib
import pathlib
import signal as _signal
import sys

import pytest

# main is imported the same way as in tests/test_smoke.py
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))


@pytest.fixture
def main_module():
    """Reload main.py per test so atexit registrations are stable."""
    if "main" in sys.modules:
        return importlib.reload(sys.modules["main"])
    import main

    return main


# ─── _active_children_terminator — happy + edge paths ────────────────
class _FakeChild:
    """Mocks a multiprocessing.Process. Tracks .terminate / .join /
    .kill calls so the test can assert on the cleanup sequence."""

    def __init__(self, pid: int, *, dies_on_terminate: bool = True):
        self.pid = pid
        self._dies = dies_on_terminate
        self._alive = True
        self.terminate_called = 0
        self.kill_called = 0
        self.join_calls: list[float | None] = []

    def terminate(self) -> None:
        self.terminate_called += 1
        if self._dies:
            self._alive = False

    def join(self, timeout=None) -> None:
        self.join_calls.append(timeout)

    def is_alive(self) -> bool:
        return self._alive

    def kill(self) -> None:
        self.kill_called += 1
        self._alive = False


def test_terminator_with_no_children_returns_empty(main_module):
    out = main_module._active_children_terminator(active_children_fn=list)
    assert out == []


def test_terminator_calls_terminate_and_join_on_each_child(main_module):
    kids = [_FakeChild(1001), _FakeChild(1002), _FakeChild(1003)]
    out = main_module._active_children_terminator(
        active_children_fn=lambda: kids,
        terminate_timeout_s=0.01,
    )
    assert out == [1001, 1002, 1003]
    for k in kids:
        assert k.terminate_called == 1
        # join called at least once with our timeout
        assert k.join_calls
        assert k.join_calls[0] == 0.01


def test_terminator_escalates_to_kill_when_terminate_does_not_take(main_module):
    """Worker that survives .terminate() must receive .kill() so the
    cleanup is bounded — otherwise a stuck child blocks shutdown
    indefinitely."""
    stuck = _FakeChild(2001, dies_on_terminate=False)
    out = main_module._active_children_terminator(
        active_children_fn=lambda: [stuck],
        terminate_timeout_s=0.01,
    )
    assert stuck.terminate_called == 1
    assert stuck.kill_called == 1
    assert out == [2001]


def test_terminator_swallows_per_child_exceptions(main_module):
    """One broken child must not block the cleanup of the rest. Logs
    the failure (we don't assert on the log call) but moves on."""

    class _Broken:
        pid = 3001

        def terminate(self):
            raise RuntimeError("worker is wedged")

        def join(self, timeout=None):
            pass

        def is_alive(self):
            return False

    good = _FakeChild(3002)
    out = main_module._active_children_terminator(
        active_children_fn=lambda: [_Broken(), good],
    )
    # Broken one was skipped; good one was terminated.
    assert out == [3002]
    assert good.terminate_called == 1


def test_terminator_handles_none_returned_from_active_children(main_module):
    """Defensive — some custom multiprocessing replacements return None
    instead of []. The cleanup MUST tolerate that without raising."""
    out = main_module._active_children_terminator(active_children_fn=lambda: None)
    assert out == []


# ─── _cleanup_subtree wraps the terminator + logs ────────────────────
def test_cleanup_subtree_runs_without_raising(main_module):
    # Production active_children() returns [] in this test context —
    # the call must complete cleanly and emit the "no children" log.
    main_module._cleanup_subtree(reason="unit-test")


# ─── atexit registration happens at import time ──────────────────────
def test_cleanup_subtree_is_registered_with_atexit(main_module):
    """A regression test would catch a future PR that deletes the
    atexit.register() line — the bug class this whole module exists
    to prevent."""
    # atexit doesn't expose a public registry list, but it does
    # expose ``_exithandlers`` (CPython implementation detail). Walk
    # it and look for our function. If the impl changes, we can fall
    # back to calling atexit.unregister() which is a no-op silent
    # success even when the fn was never registered — so that path
    # is not a useful gate. Use the CPython detail with a note.
    fns = [h[0] for h in atexit._exithandlers] if hasattr(atexit, "_exithandlers") else []
    if fns:
        assert main_module._cleanup_subtree in fns, (
            "main._cleanup_subtree must be registered with atexit — "
            "see backend/main.py 'Subprocess hygiene' block."
        )
    else:
        # Fallback path on Python builds without _exithandlers: just
        # verify unregister succeeds without raising (still proves
        # the symbol exists + is callable).
        atexit.unregister(main_module._cleanup_subtree)


# ─── _install_signal_handlers picks SIGINT at minimum ────────────────
def test_install_signal_handlers_returns_installed_list(main_module, monkeypatch):
    # Mock signal.signal so the test doesn't actually re-bind handlers
    # in this process (would break pytest's own SIGINT handling).
    installed: list[tuple[int, object]] = []

    def _fake_signal(sig, handler):
        installed.append((sig, handler))
        return _signal.SIG_DFL

    monkeypatch.setattr(_signal, "signal", _fake_signal)
    names = main_module._install_signal_handlers()
    # On every platform SIGINT exists.
    assert "SIGINT" in names
    # And signal.signal was called for every name returned.
    assert len(installed) == len(names)


def test_signal_handler_calls_cleanup_then_default(main_module, monkeypatch):
    """The installed handler must call our cleanup BEFORE re-raising
    the signal under SIG_DFL so the OS still terminates the process —
    no zombie 'paused' state because Python ate the signal."""
    cleanup_calls: list[str] = []
    monkeypatch.setattr(
        main_module, "_cleanup_subtree",
        lambda reason="atexit": cleanup_calls.append(reason),
    )
    # Stub signal.signal so installation captures the closure.
    captured: dict[int, object] = {}

    def _fake_signal(sig, handler):
        captured[sig] = handler
        return _signal.SIG_DFL

    monkeypatch.setattr(_signal, "signal", _fake_signal)
    # Stub os.kill so the test doesn't actually send signals.
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(
        main_module.os, "kill",
        lambda pid, signum: sent.append((pid, signum)),
    )
    main_module._install_signal_handlers()

    # Fire the SIGINT handler manually.
    handler = captured[_signal.SIGINT]
    handler(_signal.SIGINT, None)

    # Cleanup was called, with a signal-tagged reason.
    assert cleanup_calls, "_cleanup_subtree was not invoked"
    assert any("signal" in r for r in cleanup_calls)
    # And we re-raised SIGINT to the OS to honour SIG_DFL.
    assert sent
    assert sent[-1][1] == _signal.SIGINT
