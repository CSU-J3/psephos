"""Offline tests for common._retry_after's backoff bounds.

Pure functions only -- no network, no DB. Guards that a large Retry-After header
is honored only up to MAX_RETRY_AFTER, so one throttled request can't stall the
shared cron step. Run:  pytest tests/test_common.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.chdir(REPO)

import common  # noqa: E402


class _Resp:
    """Minimal stand-in for requests.Response: just the headers _retry_after reads."""
    def __init__(self, retry_after=None):
        self.headers = {} if retry_after is None else {"Retry-After": retry_after}


def test_retry_after_caps_huge_header():
    """A multi-minute server ask is clamped to the cap, not honored verbatim."""
    assert common._retry_after(_Resp("3600"), 0) == float(common.MAX_RETRY_AFTER)
    assert common.MAX_RETRY_AFTER == 30


def test_retry_after_passes_small_header_through():
    """A wait under the cap is respected unchanged -- the cap never inflates a wait."""
    assert common._retry_after(_Resp("5"), 0) == 5.0


def test_retry_after_no_header_uses_exponential():
    """No header -> the untouched 2**attempt fallback, still bounded at 8s (attempt 3)."""
    assert common._retry_after(_Resp(), 0) == 1.0
    assert common._retry_after(_Resp(), 3) == 8.0


# --------------------------------------------------------------------------- #
# Daily-cap discrimination in _get (handoff 8)
# --------------------------------------------------------------------------- #
class _FakeResp:
    """Minimal requests.Response stand-in for _get: status/headers/text/json."""
    def __init__(self, status_code, headers=None, text="", body=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"unexpected raise_for_status on {self.status_code}")


def _seq_get(responses):
    """A fake requests.get that yields queued responses and counts its calls."""
    state = {"n": 0}
    def fake(url, params=None, headers=None, timeout=None):
        r = responses[state["n"]]
        state["n"] += 1
        return r
    fake.state = state
    return fake


def test_daily_cap_surfaces_immediately(monkeypatch):
    """A 429 whose reset exceeds MAX_RETRY_AFTER raises RateBudgetExhausted on the
    FIRST request -- no 4x flail -- carrying the parsed reset."""
    resp = _FakeResp(429, headers={"Retry-After": "41134"},
                     text='{"detail":"Rate limit exceeded: 250/day. Expected available in 41134 seconds."}')
    fake = _seq_get([resp])
    monkeypatch.setattr(common.requests, "get", fake)
    monkeypatch.setattr(common.time, "sleep", lambda *a, **k: None)
    with pytest.raises(common.RateBudgetExhausted) as ei:
        common._get("https://x")
    assert fake.state["n"] == 1                    # aborted on the first request
    assert ei.value.reset_seconds == 41134


def test_daily_cap_read_from_body_when_no_header(monkeypatch):
    """No Retry-After header, but the throttle body carries the seconds -> still aborts."""
    resp = _FakeResp(429, text="Request was throttled. Expected available in 40000 seconds.")
    fake = _seq_get([resp])
    monkeypatch.setattr(common.requests, "get", fake)
    monkeypatch.setattr(common.time, "sleep", lambda *a, **k: None)
    with pytest.raises(common.RateBudgetExhausted) as ei:
        common._get("https://x")
    assert fake.state["n"] == 1 and ei.value.reset_seconds == 40000


def test_burst_429_still_retries(monkeypatch):
    """A 429 with a small Retry-After is transient: retry past it to the 200."""
    ok = _FakeResp(200, body={"ok": True})
    fake = _seq_get([_FakeResp(429, headers={"Retry-After": "5"}), ok])
    monkeypatch.setattr(common.requests, "get", fake)
    monkeypatch.setattr(common.time, "sleep", lambda *a, **k: None)
    assert common._get("https://x") is ok
    assert fake.state["n"] == 2                    # retried, did not abort


def test_5xx_still_retries(monkeypatch):
    """A 503 then 200 still retries and returns -- 5xx never hits the cap branch."""
    ok = _FakeResp(200, body={"ok": True})
    fake = _seq_get([_FakeResp(503), ok])
    monkeypatch.setattr(common.requests, "get", fake)
    monkeypatch.setattr(common.time, "sleep", lambda *a, **k: None)
    assert common._get("https://x") is ok
    assert fake.state["n"] == 2


if __name__ == "__main__":
    test_retry_after_caps_huge_header()
    test_retry_after_passes_small_header_through()
    test_retry_after_no_header_uses_exponential()
    print("ok")


# --------------------------------------------------------------------------- #
# Retryability by category, not by error-ness (handoff 67)
# --------------------------------------------------------------------------- #
def _counting_sleep():
    """A time.sleep stand-in that records every call, so 'no sleeps' is assertable
    rather than inferred from wall clock."""
    calls = []
    def fake(seconds=0, *a, **k):
        calls.append(seconds)
    fake.calls = calls
    return fake


def test_400_raises_immediately_with_no_sleeps(monkeypatch):
    """A malformed request cannot succeed on retry, so it costs ONE request.

    This is the defect that produced the entry: raise_for_status() raised
    HTTPError, a requests.RequestException, which the transport handler caught
    and retried -- four requests against a contended quota for a query the
    server had already rejected on its merits.
    """
    resp = _FakeResp(400, text='{"detail":"Unknown filter parameters are not allowed.",'
                               '"unknown_params":["case_name__icontains"]}')
    fake = _seq_get([resp])
    sleep = _counting_sleep()
    monkeypatch.setattr(common.requests, "get", fake)
    monkeypatch.setattr(common.time, "sleep", sleep)
    with pytest.raises(common.HttpError) as ei:
        common._get("https://x")
    assert fake.state["n"] == 1                       # ONE request, not MAX_RETRIES
    assert sleep.calls == []                          # and no backoff at all
    assert ei.value.status_code == 400


def test_400_carries_the_body_into_the_exception(monkeypatch):
    """The diagnostic must survive the raise. Losing it is what cost the session."""
    resp = _FakeResp(400, text='{"unknown_params":["case_name__icontains"]}')
    monkeypatch.setattr(common.requests, "get", _seq_get([resp]))
    monkeypatch.setattr(common.time, "sleep", lambda *a, **k: None)
    with pytest.raises(common.HttpError) as ei:
        common._get("https://x")
    assert "case_name__icontains" in str(ei.value)
    assert "case_name__icontains" in ei.value.body


def test_http_error_is_a_runtimeerror_so_callers_skip_the_item(monkeypatch):
    """resolve_docket's caller catches RuntimeError to treat a failed resolve as a
    per-item skip. If HttpError left that hierarchy, a malformed request would
    escape main() and end a run -- the exit-0 invariant transport failures keep."""
    assert issubclass(common.HttpError, RuntimeError)
    # And the daily-cap signal deliberately does NOT, because it should abort.
    assert not issubclass(common.RateBudgetExhausted, RuntimeError)


def test_404_also_raises_immediately(monkeypatch):
    """Not a special case for 400: every non-retryable status takes this path."""
    fake = _seq_get([_FakeResp(404, text="Not found")])
    monkeypatch.setattr(common.requests, "get", fake)
    monkeypatch.setattr(common.time, "sleep", lambda *a, **k: None)
    with pytest.raises(common.HttpError):
        common._get("https://x")
    assert fake.state["n"] == 1


def test_502_still_takes_the_transport_retry_path(monkeypatch):
    """The seam: a retryable 5xx must be untouched by the 4xx change."""
    ok = _FakeResp(200, body={"ok": True})
    fake = _seq_get([_FakeResp(502), ok])
    monkeypatch.setattr(common.requests, "get", fake)
    monkeypatch.setattr(common.time, "sleep", lambda *a, **k: None)
    assert common._get("https://x") is ok
    assert fake.state["n"] == 2


def test_429_still_routes_to_log_and_budget_classifier(monkeypatch):
    """The other seam, and the one finding 22 hardened. A daily-cap 429 must still
    reach _log_429 and still raise RateBudgetExhausted -- NOT HttpError."""
    seen = {}
    monkeypatch.setattr(common, "_log_429",
                        lambda url, resp, headers: seen.update(status=resp.status_code))
    resp = _FakeResp(429, headers={"Retry-After": "41134"})
    fake = _seq_get([resp])
    monkeypatch.setattr(common.requests, "get", fake)
    monkeypatch.setattr(common.time, "sleep", lambda *a, **k: None)
    with pytest.raises(common.RateBudgetExhausted):
        common._get("https://x")
    assert seen == {"status": 429}                    # the logger still fired
    assert fake.state["n"] == 1
