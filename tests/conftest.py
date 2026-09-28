"""Suite-wide network guard: a live HTTP call from a test fails loudly.

Every collector test stubs the layer it means to fake -- `_fetch_page`, `poll_entries`,
`common.http_get` -- and a test that stubs one layer while `main()` reaches another
silently issues real requests. That is not hypothetical: wiring refresh_status into
`main()` (handoff 27) left `test_full_walk_request_budget_defers_when_spent` making
three live requests at a fake base, passing the whole time because the collector's
per-row isolation swallowed the failures, at ~87s of retry backoff. A one-time audit
found it; nothing would have found the next one.

`requests.adapters.HTTPAdapter.send` is the chokepoint. `common._get` calls
`requests.get`, news.py uses feedparser/requests, and `requests.get`, `Session.get`
and the retry loop all funnel into `HTTPAdapter.send`. Patching there covers every
network path this codebase actually uses. Deliberately NOT the socket layer: it buys
nothing over this and adds a failure mode nobody will diagnose quickly.

`NetworkCallInTest` derives from **BaseException**, not Exception, and that is the
load-bearing detail. Anything catchable gets absorbed before it reaches the test:

  * `common._get` retries `requests.RequestException` four times with 2**attempt
    backoff and then raises a generic RuntimeError -- so a ConnectionError-shaped
    guard would cost 15s and arrive disguised as the very error it exists to
    distinguish itself from.
  * `collect_case` catches `RuntimeError` on the resolve path, and `refresh_status`
    catches broad `Exception` per row. Either would swallow the guard, the test would
    pass, and the alarm would be silent -- the exact shape being fixed here.

BaseException slips every one of those handlers, so the guard reaches pytest intact.

A test that genuinely needs the network requests the `allow_network` fixture. Nothing
in the suite needs it today; it exists so the exception is visible in a test's
signature instead of invisible in its runtime.
"""
from __future__ import annotations

import pytest
import requests.adapters

_REAL_SEND = requests.adapters.HTTPAdapter.send


class NetworkCallInTest(BaseException):
    """A test tried to reach the network. See tests/conftest.py."""


def _blocked_send(self, request, *args, **kwargs):
    raise NetworkCallInTest(
        f"blocked live HTTP from a test: {request.method} {request.url}\n"
        f"Stub the layer the code under test actually reaches (usually "
        f"common.http_get), or request the `allow_network` fixture."
    )


@pytest.fixture(autouse=True, scope="session")
def _block_network():
    """Autouse and session-wide: applies with no opt-in, so a new test inherits the
    guard rather than inheriting the coupling."""
    requests.adapters.HTTPAdapter.send = _blocked_send
    try:
        yield
    finally:
        requests.adapters.HTTPAdapter.send = _REAL_SEND


@pytest.fixture
def allow_network():
    """Opt out of the guard for one test. Restores the real send for its duration."""
    requests.adapters.HTTPAdapter.send = _REAL_SEND
    try:
        yield
    finally:
        requests.adapters.HTTPAdapter.send = _blocked_send


@pytest.fixture(autouse=True)
def _fresh_secret_registry():
    """run_signals keeps a process-wide registry of the run's secrets, which is right for
    one collector process and wrong across a test session: one test's fixture key would
    be scrubbed from every later test's output. Clear it around each test."""
    import run_signals
    run_signals._SECRETS.clear()
    yield
    run_signals._SECRETS.clear()


@pytest.fixture(autouse=True)
def _no_inherited_run_identity(monkeypatch):
    """ci.yml runs this suite on Actions, where the runner sets GITHUB_RUN_ID and
    GITHUB_RUN_ATTEMPT -- the latter 2 on a re-run, which makes run_signals.run_id()
    append `.2` and every row keyed on a pinned id miss (43 unit 99 tests went red that
    way, measured 2026-09-28). A test that wants a run identity sets it itself."""
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ATTEMPT", raising=False)
