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
    """A fake requests.get that yields queued responses and counts its calls.

    A queued entry that is an Exception is RAISED rather than returned, so a
    transport failure can be scripted into the same sequence as a status -- which
    is what the mixed-cause exhaustion tests (handoff 77) need."""
    state = {"n": 0}
    def fake(url, params=None, headers=None, timeout=None):
        r = responses[state["n"]]
        state["n"] += 1
        if isinstance(r, Exception):
            raise r
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


# --------------------------------------------------------------------------- #
# Exhaustion states its cause (handoff 77)
#
# _get can exhaust MAX_RETRIES two different ways -- a retryable status that
# never stops being retryable, or a transport failure on every attempt -- and
# the message has to say which. The demonstration is the 2026-08-15 00:00Z run:
# nine LegiScan states failed identically with "GET failed after 4 attempts:
# https://api.legiscan.com/" and the log could not separate 429 from 503.
# --------------------------------------------------------------------------- #
def test_retryable_exhaustion_carries_status_and_body(monkeypatch):
    """A 5xx that never recovers reports the 5xx. This is the incident's shape:
    without the status, "transient" is a verdict on persistence with the cause
    unmeasured -- and a 429 here would mean a spent monthly cap instead."""
    body = '{"status":"ERROR","alert":{"message":"Service Unavailable"}}'
    fake = _seq_get([_FakeResp(503, text=body) for _ in range(common.MAX_RETRIES)])
    monkeypatch.setattr(common.requests, "get", fake)
    monkeypatch.setattr(common.time, "sleep", lambda *a, **k: None)
    with pytest.raises(RuntimeError) as ei:
        common._get("https://api.legiscan.com/")
    msg = str(ei.value)
    assert f"GET failed after {common.MAX_RETRIES} attempts" in msg   # prefix intact
    assert "503" in msg and "Service Unavailable" in msg              # and the cause
    assert fake.state["n"] == common.MAX_RETRIES     # every attempt was actually spent
    assert ei.value.__cause__ is None                # no transport failure to blame


def test_retryable_exhaustion_truncates_a_long_body(monkeypatch):
    """Same 500-char bound HttpError uses -- one convention, not two. The URL is
    deliberately x-free so the count measures the body and nothing else."""
    fake = _seq_get([_FakeResp(500, text="x" * 5000) for _ in range(common.MAX_RETRIES)])
    monkeypatch.setattr(common.requests, "get", fake)
    monkeypatch.setattr(common.time, "sleep", lambda *a, **k: None)
    with pytest.raises(RuntimeError) as ei:
        common._get("https://api.legiscan.com/")
    assert str(ei.value).count("x") == 500


def test_transport_exhaustion_preserves_cause_and_invents_no_status(monkeypatch):
    """The other cause, unchanged: the exception stays the __cause__ and nothing
    fabricates a status code that no response ever carried."""
    exc = common.requests.ConnectionError("connection reset")
    fake = _seq_get([exc for _ in range(common.MAX_RETRIES)])
    monkeypatch.setattr(common.requests, "get", fake)
    monkeypatch.setattr(common.time, "sleep", lambda *a, **k: None)
    with pytest.raises(RuntimeError) as ei:
        common._get("https://x")
    assert ei.value.__cause__ is exc
    assert "HTTP" not in str(ei.value)
    assert fake.state["n"] == common.MAX_RETRIES


def test_mixed_exhaustion_reports_the_last_attempt_not_a_merge(monkeypatch):
    """Both directions of a mixed run. The last attempt decides, and it CLEARS the
    other -- reporting a status and a transport exception together would pair two
    failures that never co-occurred."""
    exc = common.requests.Timeout("read timed out")
    # ...status first, transport last -> transport wins, no status invented.
    fake = _seq_get([_FakeResp(503, text="upstream down"), exc, exc, exc])
    monkeypatch.setattr(common.requests, "get", fake)
    monkeypatch.setattr(common.time, "sleep", lambda *a, **k: None)
    with pytest.raises(RuntimeError) as ei:
        common._get("https://x")
    assert ei.value.__cause__ is exc
    assert "503" not in str(ei.value) and "upstream down" not in str(ei.value)

    # ...transport first, status last -> the status wins and carries no stale cause.
    fake = _seq_get([exc, exc, exc, _FakeResp(502, text="bad gateway")])
    monkeypatch.setattr(common.requests, "get", fake)
    with pytest.raises(RuntimeError) as ei:
        common._get("https://x")
    assert "502" in str(ei.value) and "bad gateway" in str(ei.value)
    assert ei.value.__cause__ is None


def test_burst_429_exhaustion_still_logs_and_now_names_itself(monkeypatch):
    """A burst 429 that outlasts the retries: _log_429 still fires on every one of
    them (the path finding 22 hardened), AND the exhaustion now says 429 -- which
    is the distinction the LegiScan log could not make."""
    seen = []
    monkeypatch.setattr(common, "_log_429", lambda url, resp, headers: seen.append(resp.status_code))
    throttle = '{"detail":"Request was throttled. Expected available in 5 seconds."}'
    fake = _seq_get([_FakeResp(429, headers={"Retry-After": "5"}, text=throttle)
                     for _ in range(common.MAX_RETRIES)])
    monkeypatch.setattr(common.requests, "get", fake)
    monkeypatch.setattr(common.time, "sleep", lambda *a, **k: None)
    with pytest.raises(RuntimeError) as ei:
        common._get("https://x")
    assert seen == [429] * common.MAX_RETRIES        # logger fired on each retried 429
    assert "429" in str(ei.value) and "throttled" in str(ei.value)
    # A burst 429 exhausting is NOT a spent daily cap; the classifier stays out of it.
    assert not isinstance(ei.value, common.RateBudgetExhausted)
