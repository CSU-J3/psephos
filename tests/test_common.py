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
from requests.structures import CaseInsensitiveDict

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
    """Minimal requests.Response stand-in for _get: status/headers/text/json.

    HEADERS ARE CASE-INSENSITIVE ON PURPOSE. A real `requests.Response` carries a
    CaseInsensitiveDict, and CourtListener sends the header lowercased -- finding
    22's capture records `retry-after: 46`. With a plain dict, `_retry_after`'s
    `headers.get("Retry-After")` misses it silently and the request falls down the
    exponential path, which is a different test than the one being written. Found
    by measuring the retry schedule, not by reading."""
    def __init__(self, status_code, headers=None, text="", body=None):
        self.status_code = status_code
        self.headers = CaseInsensitiveDict(headers or {})
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
    # This body names no scope, so it exercises the UNSCOPED path -- the magnitude
    # fallback, which handoff 79 deliberately left bit-for-bit unchanged. The
    # scoped seam is pinned separately below.
    assert common._throttle_scope(_FakeResp(429, text=throttle)) is None


# --------------------------------------------------------------------------- #
# Classify a throttle on its SCOPE, not its magnitude (handoff 79)
#
# _get used to read a reset above MAX_RETRY_AFTER as a spent daily budget and
# abort the collector. Finding 22 measured a response where that is flatly wrong:
# a body saying `20/min` with `retry-after: 46`. The reset is large BECAUSE the
# burst was tight -- 20 requests inside 14.5s means the oldest ages out at t=60,
# so 60 - 14.5 ~= 46 -- and the ceiling for a per-minute window is 60s, double
# MAX_RETRY_AFTER. So the tighter the burst the more it looks like a daily cap.
#
# Both 429s this account has ever produced are per-minute scopes, so every real
# 429 in the project's history aborted litigation over a condition that clears in
# under a minute, while the daily-cap branch has never been exercised by a real
# response at all.
# --------------------------------------------------------------------------- #

# REPLAYED REAL RESPONSE, measured 2026-08-10 01:40Z against production
# CourtListener on the token collectors/litigation.py loads. Recorded with its
# headers in docs/findings/22-throttle-scope-vs-magnitude.md, which also carries
# the 21-request burst table that derives the 46 independently of retry-after.
BODY_20_MIN = ('{"detail":"Request was throttled. Rate limit exceeded: 20/min. '
               'Expected available in 46 seconds."}')
HEADERS_20_MIN = {"retry-after": "46"}          # lowercase, exactly as captured

# REPLAYED REAL RESPONSE, captured during the 2026-08-05/06 silent de-tiering and
# recorded 2026-08-09 in bfc8be9, where it lives in common._log_429's docstring.
# ONLY THE BODY WAS PRESERVED -- the header map was not, which is why the
# body-only case below exhausts rather than clearing. Finding 22 proves the
# server does send retry-after, so the absence is the record's, not the wire's.
BODY_5_MIN = ('{"detail": "Request was throttled. Rate limit exceeded: 5/min. '
              'Expected available in 55 seconds."}')

# CONSTRUCTED, NOT OBSERVED. No real daily-cap 429 exists for this account, and
# `250/day` is on the falsified list in docs/status.md as a figure that was never
# read off it -- the authenticated free default was 125/day and the measured EDU
# level shows no daily figure at all. The cap branch therefore has no artifact,
# and this fixture is a format guess rather than evidence. Kept because the
# branch still needs a test; labelled so nobody cites it as a measurement.
BODY_250_DAY = ('{"detail":"Rate limit exceeded: 250/day. '
                'Expected available in 41134 seconds."}')


def test_throttle_scope_reads_the_unit_after_the_slash():
    """The parser, against both real bodies and the constructed one."""
    assert common._throttle_scope(_FakeResp(429, text=BODY_20_MIN)) == "burst"
    assert common._throttle_scope(_FakeResp(429, text=BODY_5_MIN)) == "burst"
    assert common._throttle_scope(_FakeResp(429, text=BODY_250_DAY)) == "cap"


def test_throttle_scope_spells_out_the_units_it_knows():
    """DRF writes these as second/minute/hour/day as readily as the abbreviations,
    so match on prefixes. An hour is a burst by scope -- see the hourly test below
    for the consequence, which is pinned rather than assumed."""
    for text, want in (("Rate limit exceeded: 10/sec.", "burst"),
                       ("Rate limit exceeded: 10/second.", "burst"),
                       ("Rate limit exceeded: 60/minute.", "burst"),
                       ("Rate limit exceeded: 1000/hour.", "burst"),
                       ("Rate limit exceeded: 100/day.", "cap"),
                       ("Rate limit exceeded: 5000/week.", "cap"),
                       ("Rate limit exceeded: 30000/year.", "cap")):
        assert common._throttle_scope(_FakeResp(429, text=text)) == want, text


def test_month_is_a_cap_not_a_minute():
    """The reason units are matched on PREFIXES and not first letters. `m` is
    ambiguous between min and month, and reading a monthly cap as a burst is
    exactly the failure this classifier exists to prevent -- it is also the shape
    LegiScan's EDU cap takes, which is the open question from handoff 77."""
    assert common._throttle_scope(_FakeResp(429, text="Rate limit exceeded: 1/month.")) == "cap"
    assert common._throttle_scope(_FakeResp(429, text="Rate limit exceeded: 1/min.")) == "burst"


def test_throttle_scope_returns_none_when_nothing_parses():
    """No guessing. An unrecognised or absent scope hands the decision back to the
    magnitude fallback rather than inventing a classification."""
    assert common._throttle_scope(_FakeResp(429, text="")) is None
    assert common._throttle_scope(_FakeResp(429, text="Too Many Requests")) is None
    assert common._throttle_scope(_FakeResp(429, text="Rate limit exceeded: 5/fortnight.")) is None
    # A reset alone is not a scope -- this is the body shape DRF sends unadorned.
    assert common._throttle_scope(
        _FakeResp(429, text="Request was throttled. Expected available in 40000 seconds.")) is None


def test_finding_22_body_retries_instead_of_aborting_the_run(monkeypatch):
    """THE DEFECT FINDING 22 FILED. A 20/min scope with a 46s reset must retry.

    Before this fix it raised RateBudgetExhausted on the first response, which
    aborts litigation for the cycle (collectors/litigation.py:521, 647, 696) over
    a throttle that clears in under a minute."""
    ok = _FakeResp(200, body={"ok": True})
    fake = _seq_get([_FakeResp(429, headers=HEADERS_20_MIN, text=BODY_20_MIN),
                     _FakeResp(429, headers=HEADERS_20_MIN, text=BODY_20_MIN), ok])
    monkeypatch.setattr(common.requests, "get", fake)
    monkeypatch.setattr(common.time, "sleep", lambda *a, **k: None)
    assert common._get("https://www.courtlistener.com/api/rest/v4/courts/") is ok
    assert fake.state["n"] == 3
    # And the magnitude that used to decide it is still large -- the scope is what
    # changed the verdict, not the number.
    assert common._reset_seconds(_FakeResp(429, headers=HEADERS_20_MIN)) == 46
    assert 46 > common.MAX_RETRY_AFTER


def test_finding_22_retry_schedule_actually_clears_the_window(monkeypatch):
    """The fix is only correct if the burst path can SUCCEED, so pin the arithmetic
    rather than asserting it in a comment.

    retry-after: 46 caps to MAX_RETRY_AFTER=30 per attempt, so requests land at
    t = 0, 30, 60, 90. The third is past the 46s window, with a fourth in reserve;
    a per-minute window's ceiling is 60s, so every per-minute throttle clears
    inside MAX_RETRIES."""
    resp = _FakeResp(429, headers=HEADERS_20_MIN, text=BODY_20_MIN)
    waits = [common._retry_after(resp, attempt) for attempt in range(common.MAX_RETRIES)]
    assert waits == [30.0, 30.0, 30.0, 30.0]
    at = [sum(waits[:i]) for i in range(common.MAX_RETRIES)]
    assert at == [0.0, 30.0, 60.0, 90.0]
    assert at[2] >= 46 and at[3] >= 60          # clears the window, and the ceiling


def test_de_tier_5min_body_as_served_clears_on_the_third_request(monkeypatch):
    """The 08-09 body with the retry-after the server actually sends: 55s window,
    waits capped at 30, so request three at t=60 clears it."""
    ok = _FakeResp(200, body={"ok": True})
    fake = _seq_get([_FakeResp(429, headers={"Retry-After": "55"}, text=BODY_5_MIN),
                     _FakeResp(429, headers={"Retry-After": "55"}, text=BODY_5_MIN), ok])
    monkeypatch.setattr(common.requests, "get", fake)
    monkeypatch.setattr(common.time, "sleep", lambda *a, **k: None)
    assert common._get("https://x") is ok
    assert fake.state["n"] == 3


def test_de_tier_5min_body_only_exhausts_but_still_does_not_abort(monkeypatch):
    """The artifact AS PRESERVED carries no header, so backoff falls to 1/2/4/8 and
    reaches 7s against a 55s window -- it cannot clear, and exhausts.

    That degradation is still strictly better than what shipped before. RuntimeError
    is a per-item skip (collectors/litigation.py:525, 657) and the run continues;
    RateBudgetExhausted aborted the whole collector. Pinned so the difference is
    deliberate rather than incidental, and so the seam is visible: _log_429 fires on
    every attempt and the daily-cap classifier is never reached."""
    seen = []
    monkeypatch.setattr(common, "_log_429", lambda url, resp, headers: seen.append(resp.status_code))
    fake = _seq_get([_FakeResp(429, text=BODY_5_MIN) for _ in range(common.MAX_RETRIES)])
    monkeypatch.setattr(common.requests, "get", fake)
    monkeypatch.setattr(common.time, "sleep", lambda *a, **k: None)
    with pytest.raises(RuntimeError) as ei:
        common._get("https://x")
    assert not isinstance(ei.value, common.RateBudgetExhausted)
    assert seen == [429] * common.MAX_RETRIES
    assert "429" in str(ei.value) and "5/min" in str(ei.value)   # names itself, per 8e752f4


def test_an_hourly_scope_is_a_burst_that_cannot_clear(monkeypatch):
    """The one sub-daily unit whose window outlasts the retry budget: an hour can
    report up to 3600s and the ladder tops out near 90s. It is classified burst by
    scope, so it retries and exhausts to a per-item skip rather than aborting.

    CourtListener's 1,000/hour is real, so this is not hypothetical. Recorded as
    the known cost of classifying on the unit: a genuinely spent hourly budget
    keeps the run alive and spends four requests learning that."""
    body = '{"detail":"Request was throttled. Rate limit exceeded: 1000/hour. Expected available in 2400 seconds."}'
    fake = _seq_get([_FakeResp(429, headers={"Retry-After": "2400"}, text=body)
                     for _ in range(common.MAX_RETRIES)])
    monkeypatch.setattr(common.requests, "get", fake)
    monkeypatch.setattr(common.time, "sleep", lambda *a, **k: None)
    with pytest.raises(RuntimeError) as ei:
        common._get("https://x")
    assert not isinstance(ei.value, common.RateBudgetExhausted)
    assert fake.state["n"] == common.MAX_RETRIES


def test_a_named_daily_scope_still_aborts_immediately(monkeypatch):
    """The cap branch, on the constructed fixture. A daily scope is hopeless by
    definition -- no wait inside this run refills it -- so it aborts at one request
    regardless of what the reset says."""
    fake = _seq_get([_FakeResp(429, headers={"Retry-After": "41134"}, text=BODY_250_DAY)])
    monkeypatch.setattr(common.requests, "get", fake)
    monkeypatch.setattr(common.time, "sleep", lambda *a, **k: None)
    with pytest.raises(common.RateBudgetExhausted) as ei:
        common._get("https://x")
    assert fake.state["n"] == 1
    assert ei.value.reset_seconds == 41134


def test_a_daily_scope_aborts_even_with_a_small_reset(monkeypatch):
    """Scope decides, in BOTH directions. A daily cap reporting a short reset still
    aborts -- the rule is the unit, not the number, or the fix would just be the
    magnitude heuristic wearing a different hat."""
    body = '{"detail":"Rate limit exceeded: 100/day. Expected available in 5 seconds."}'
    fake = _seq_get([_FakeResp(429, headers={"Retry-After": "5"}, text=body)])
    monkeypatch.setattr(common.requests, "get", fake)
    monkeypatch.setattr(common.time, "sleep", lambda *a, **k: None)
    with pytest.raises(common.RateBudgetExhausted):
        common._get("https://x")
    assert fake.state["n"] == 1


def test_degraded_429_falls_back_to_retry_then_runtimeerror(monkeypatch):
    """No Retry-After, no parseable body, no scope: nothing to classify on. The
    documented degradation, pinned so it stays deliberate -- retry the ladder, then
    raise RuntimeError carrying the status and body."""
    fake = _seq_get([_FakeResp(429, text="Too Many Requests") for _ in range(common.MAX_RETRIES)])
    monkeypatch.setattr(common.requests, "get", fake)
    monkeypatch.setattr(common.time, "sleep", lambda *a, **k: None)
    with pytest.raises(RuntimeError) as ei:
        common._get("https://x")
    assert not isinstance(ei.value, common.RateBudgetExhausted)
    assert fake.state["n"] == common.MAX_RETRIES
    assert "429" in str(ei.value) and "Too Many Requests" in str(ei.value)
