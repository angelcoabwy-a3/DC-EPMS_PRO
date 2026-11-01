"""Offline tests for the Meta credit guard (no network, no credits).

Covers META_PER_IP_LIMIT parsing (default 10, cap 200) and the
429-on-attempt-limit+1 boundary. Counter state is reset per test.
"""

import pytest

from backend.copilot_limits import (
    MetaLimitError,
    check_limits,
    get_ip_usage,
    get_per_ip_limit,
    reset_for_tests,
)


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    monkeypatch.delenv("META_PER_IP_LIMIT", raising=False)
    reset_for_tests()
    yield
    reset_for_tests()


def test_unset_gives_default_10():
    assert get_per_ip_limit() == 10


def test_valid_value_is_honoured(monkeypatch):
    monkeypatch.setenv("META_PER_IP_LIMIT", "40")
    assert get_per_ip_limit() == 40


@pytest.mark.parametrize("raw", ["", "abc", "0", "-5"])
def test_garbage_values_fall_back_to_default_10(monkeypatch, raw):
    monkeypatch.setenv("META_PER_IP_LIMIT", raw)
    assert get_per_ip_limit() == 10


def test_large_value_is_capped_at_200(monkeypatch):
    monkeypatch.setenv("META_PER_IP_LIMIT", "999")
    assert get_per_ip_limit() == 200


def test_429_appears_on_attempt_limit_plus_1(monkeypatch):
    monkeypatch.setenv("META_PER_IP_LIMIT", "3")
    for _ in range(3):
        check_limits("testclient")
    with pytest.raises(MetaLimitError) as raised:
        check_limits("testclient")
    assert raised.value.limit == "per_ip"
    assert "Meta-backed requests" in raised.value.message
    assert "max 3" in raised.value.message


def test_default_limit_allows_10_then_429s():
    for _ in range(10):
        check_limits("testclient")
    with pytest.raises(MetaLimitError) as raised:
        check_limits("testclient")
    assert raised.value.limit == "per_ip"


def test_ip_usage_reports_used_and_max():
    assert get_ip_usage("testclient") == (0, 10)
    for _ in range(3):
        check_limits("testclient")
    assert get_ip_usage("testclient") == (3, 10)
    assert get_ip_usage("other-ip") == (0, 10)


def test_ip_usage_is_read_only():
    check_limits("testclient")
    assert get_ip_usage("testclient") == (1, 10)
    assert get_ip_usage("testclient") == (1, 10)


def test_ip_usage_honours_configured_max(monkeypatch):
    monkeypatch.setenv("META_PER_IP_LIMIT", "40")
    assert get_ip_usage("testclient") == (0, 40)
