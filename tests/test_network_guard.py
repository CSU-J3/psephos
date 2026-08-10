"""Suite for the network guard itself (tests/conftest.py).

A guard with no test is the same class of unverified claim the guard exists to catch,
so this asserts the three properties the guard is worthless without: it fires, it
fires INSTEAD of a connection error, and it fires immediately rather than after the
retry backoff that would otherwise disguise it.

Run:  pytest tests/test_network_guard.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
import requests
import requests.adapters

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import common  # noqa: E402
from conftest import NetworkCallInTest, _REAL_SEND  # noqa: E402

# Reserved TLD (RFC 2606): guaranteed never to resolve, so an unguarded call fails
# rather than reaching a real host.
UNREACHABLE = "http://psephos-guard-check.invalid/dockets/1/"


def test_requests_get_is_blocked_not_merely_unreachable():
    """The distinction that matters: NetworkCallInTest, not ConnectionError. A test
    that sees a connection error learns its fake host was fake; one that sees this
    learns it made a real call at all -- which is the finding."""
    with pytest.raises(NetworkCallInTest) as exc:
        requests.get(UNREACHABLE, timeout=5)
    assert "psephos-guard-check.invalid" in str(exc.value)   # names the attempted URL
    assert "GET" in str(exc.value)


def test_block_is_immediate_not_after_backoff():
    """Immediacy is the property, not just the exception. `common._get` retries
    `requests.RequestException` four times at 2**attempt (15s minimum) and then
    raises a generic RuntimeError. NetworkCallInTest is a BaseException, so it slips
    that handler and arrives intact and instantly -- if this ever takes >1s, the
    guard has been made catchable and is being retried."""
    start = time.monotonic()
    with pytest.raises(NetworkCallInTest):
        common.http_get(UNREACHABLE)
    assert time.monotonic() - start < 1.0


def test_guard_slips_the_handlers_that_would_swallow_it():
    """The reason for BaseException, asserted directly. Every per-item handler in the
    collectors catches `Exception` or `RuntimeError`; if the guard were catchable,
    those would absorb it and the test would pass in silence."""
    with pytest.raises(NetworkCallInTest):
        try:
            requests.get(UNREACHABLE, timeout=5)
        except Exception:                      # noqa: BLE001 - the point of the test
            pytest.fail("guard was swallowed by a bare `except Exception`")
    with pytest.raises(NetworkCallInTest):
        try:
            common.http_get(UNREACHABLE)
        except RuntimeError:
            pytest.fail("guard was swallowed by `except RuntimeError`")


def test_allow_network_fixture_restores_the_real_send(allow_network):
    """The opt-out works, asserted by identity rather than by making a real call --
    the suite must stay offline even while proving the escape hatch exists."""
    assert requests.adapters.HTTPAdapter.send is _REAL_SEND


def test_guard_is_reinstated_after_an_opt_out():
    """Runs after the test above; the fixture's teardown must have put the block back,
    or the opt-out would leak into every test that follows it."""
    assert requests.adapters.HTTPAdapter.send is not _REAL_SEND
    with pytest.raises(NetworkCallInTest):
        requests.get(UNREACHABLE, timeout=5)
