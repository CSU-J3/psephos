"""Shared collector helpers: HTTP with retry, content hashing, timestamps.

Every collector reuses these so dedup keys and time formats stay consistent
across channels.
"""

from __future__ import annotations

import hashlib
import re
import sys
import time
from datetime import datetime, timezone

import requests
from dateutil import parser as dateparser

DEFAULT_TIMEOUT = 30
MAX_RETRIES = 4
MAX_RETRY_AFTER = 30  # seconds; honor Retry-After only up to this, so one
                      # throttled request can't stall the shared cron step
RETRY_STATUS = {429, 500, 502, 503, 504}
UNIT_SEP = "\x1f"  # field separator for content hashing


class HttpError(RuntimeError):
    """A non-retryable HTTP error status, carrying the body that explains it.

    RUNTIMEERROR SUBCLASS DELIBERATELY, and the choice is load-bearing rather
    than stylistic. `resolve_docket`'s caller catches `RuntimeError` to treat a
    failed resolve as a per-item skip (collectors/litigation.py); the two poll
    handlers catch broad `Exception`. Raising anything outside that hierarchy
    would let a malformed request escape `main()` and take down a run, which is
    the exit-0 invariant that transport failures already honour. A bad query is
    a per-item failure, not a run-ending one.

    Deliberately NOT a sibling of RateBudgetExhausted, which is not a
    RuntimeError precisely because a spent daily cap SHOULD abort the run rather
    than be swallowed per item.

    THE BODY TRAVELS WITH THE EXCEPTION. `raise_for_status()` used to be what
    ran here, and it discards the response body -- so a 400 arrived as
    "400 Client Error: Bad Request for url: ..." with the server's explanation
    thrown away. CourtListener answers a bad filter with exactly the diagnostic
    needed (`{"detail":"Unknown filter parameters are not allowed.",
    "unknown_params":["case_name__icontains"]}`), and losing it cost four
    requests and a second session to recover.
    """

    def __init__(self, status_code: int, url: str, body: str = ""):
        self.status_code = status_code
        self.url = url
        self.body = body
        detail = f": {body[:500]}" if body else ""
        super().__init__(f"HTTP {status_code} for {url}{detail}")


class RateBudgetExhausted(Exception):
    """A daily request cap is spent; no retry within our wait budget can refill it.
    Distinct from a burst-rate 429 (transient, retried). Carries seconds until the
    window frees so the caller can report a reset and abort instead of retry-storming."""

    def __init__(self, reset_seconds: float | None):
        self.reset_seconds = reset_seconds
        super().__init__(
            f"daily rate budget exhausted; resets in ~{reset_seconds:.0f}s"
            if reset_seconds is not None else "daily rate budget exhausted")


def _get(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    throttle: float = 0.0,
) -> requests.Response:
    """GET with backoff on rate-limit / server errors, returning the raw Response.

    `throttle` sleeps before the request to stay under a documented rate limit.
    Retries on 429 and 5xx with exponential backoff (honoring Retry-After when
    present); raises `HttpError` IMMEDIATELY on any other error status, without
    sleeping or retrying, carrying the response body. See HttpError for why the
    two categories are separated and why the body has to survive the raise.
    """
    if throttle:
        time.sleep(throttle)
    # EXHAUSTION HAS TWO CAUSES AND THE MESSAGE HAS TO SAY WHICH. A retryable
    # status and a transport failure both end up at the raise below, so the last
    # attempt's outcome is recorded here rather than reconstructed there.
    # Whichever fired LAST wins and clears the other: reporting a status
    # alongside a transport exception would pair two failures that never
    # co-occurred, and a stale __cause__ from three attempts ago is worse than
    # none. Clearing last_exc on the status path is also what keeps that path's
    # `from None` behaviour with a single raise statement.
    last_exc: Exception | None = None
    last_status: int | None = None
    last_body = ""
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code in RETRY_STATUS:
                if resp.status_code == 429:
                    _log_429(url, resp, headers)
                    # Tell a daily-cap 429 (hopeless: Retry-After ~ tens of thousands of
                    # seconds, far past any wait we'd take) from a burst-rate 429
                    # (transient). _reset_seconds is UNCAPPED, so a reset beyond
                    # MAX_RETRY_AFTER is by definition a wait we won't take -> abort now
                    # rather than flail MAX_RETRIES times and discard the status.
                    # Limitation: a cap with NO Retry-After AND no body count degrades to
                    # the old retry-then-RuntimeError; CourtListener's throttle body carries it.
                    reset = _reset_seconds(resp)
                    if reset is not None and reset > MAX_RETRY_AFTER:
                        raise RateBudgetExhausted(reset)
                last_exc, last_status, last_body = None, resp.status_code, resp.text
                time.sleep(_retry_after(resp, attempt))
                continue
            # RETRYABILITY IS A CATEGORY, NOT A SEVERITY. Retry exists for answers
            # that can differ next time: a 429 (the window moves), a 5xx in
            # RETRY_STATUS (the server may recover), a transport failure (the
            # connection may succeed). A 4xx outside that set is the server saying
            # the REQUEST is wrong, and re-sending it unchanged cannot change the
            # answer -- so raise on the first response, with no sleep and no loop.
            # This extends the principle the 429 path above already states in as
            # many words ("abort now rather than flail MAX_RETRIES times"); that
            # reasoning was applied to the daily cap and never to the rest.
            #
            # Measured cost of the old behaviour: `raise_for_status()` raised
            # HTTPError, a requests.RequestException subclass, which the handler
            # below caught and retried -- so every 400/401/403/404 in this
            # project's history cost 4 requests against a contended quota and 7s
            # of backoff, and threw away the body that said why. One malformed
            # CourtListener query on 2026-08-14 spent 4 of a 2-request budget and
            # yielded nothing.
            # `status_code >= 400` rather than `resp.ok`: the same test without
            # depending on a requests-specific property, which keeps the Response
            # surface this function needs to exactly status_code/headers/text/json.
            if resp.status_code >= 400:
                raise HttpError(resp.status_code, url, resp.text)
            return resp
        except requests.RequestException as exc:
            last_exc, last_status = exc, None
            time.sleep(2 ** attempt)
    # THE ASYMMETRY THIS CLOSES. HttpError above exists because raise_for_status()
    # discarded the body that explained the failure -- and the retryable branch
    # beside it discarded the status AND the body, taking `continue` without
    # recording the response, so exhaustion raised this bare message from None.
    # Measured cost: at the 2026-08-15 00:00Z run all nine LegiScan states failed
    # identically with "GET failed after 4 attempts: https://api.legiscan.com/",
    # about twenty minutes of a 30m15s run, and the log cannot say whether that
    # was 429, 500 or 503. Not academic -- LegiScan's EDU tier carries a monthly
    # cap that presents as a 429, so the log as written cannot separate "upstream
    # had a bad night" from "we are out of quota for the month", and "transient"
    # becomes a verdict on persistence with the cause never measured.
    # Same shape as HttpError's (status, then body at 500 chars); the prefix is
    # unchanged, so the new material is strictly appended.
    detail = ""
    if last_status is not None:
        detail = f" (last: HTTP {last_status}{f': {last_body[:500]}' if last_body else ''})"
    raise RuntimeError(
        f"GET failed after {MAX_RETRIES} attempts: {url}{detail}") from last_exc


def http_get(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    throttle: float = 0.0,
) -> dict:
    """GET and parse a JSON body (the API collectors' path)."""
    return _get(url, params, headers, timeout, throttle).json()


def http_get_text(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    throttle: float = 0.0,
) -> str:
    """GET a text/HTML body with the same backoff as `http_get`.

    For scraped pages that are not JSON (e.g. the UW tracker table). When the
    server omits a charset, requests defaults text/* to ISO-8859-1 and mangles
    UTF-8; fall back to the sniffed encoding so scraped text stays clean.
    """
    resp = _get(url, params, headers, timeout, throttle)
    if "charset" not in resp.headers.get("content-type", "").lower():
        resp.encoding = resp.apparent_encoding
    return resp.text


def _retry_after(resp: requests.Response, attempt: int) -> float:
    """Seconds to wait before a retry: Retry-After header (honored up to
    MAX_RETRY_AFTER), else exponential."""
    header = resp.headers.get("Retry-After")
    if header:
        try:
            return min(float(header), MAX_RETRY_AFTER)
        except ValueError:
            pass
    return float(2 ** attempt)


def _log_429(url: str, resp: requests.Response, sent: dict | None = None) -> None:
    """Dump a throttle response to stderr BEFORE anything classifies it.

    Which throttle fired is stated only in the body -- CourtListener returns
    `{"detail": "Request was throttled. Rate limit exceeded: 5/min. Expected
    available in 55 seconds."}` and carries no X-RateLimit-* header at all, so
    `retry-after` alone gives a delay with no scope attached. Called before the
    MAX_RETRY_AFTER comparison, so it fires on the retried 429s too; those are
    the majority and they leave no trace today. stderr, not stdout, because a
    collector's stdout is block-buffered under the cron and flushes at process
    exit, which is what made per-request timing unrecoverable from the logs.

    Pure logging: no return value, no control flow, nothing classified here."""
    secret = (sent or {}).get("Authorization")

    def scrub(text: str) -> str:
        return text.replace(secret, "<redacted>") if secret and secret in text else text

    safe = {k: ("<redacted>" if k.lower() == "authorization" else scrub(v))
            for k, v in resp.headers.items()}
    print(f"  429 from {url}\n    headers: {safe}\n    body: {scrub(resp.text)}",
          file=sys.stderr)


def _reset_seconds(resp: requests.Response) -> int | None:
    """Seconds until a throttle frees, UNCAPPED (unlike _retry_after): the Retry-After
    header, else the count in an `Expected available in N seconds` throttle body. The
    magnitude is what lets _get tell a daily cap (huge) from a burst (small)."""
    ra = resp.headers.get("Retry-After")
    if ra and ra.isdigit():
        return int(ra)
    m = re.search(r"(\d+)\s*seconds", resp.text)
    return int(m.group(1)) if m else None


def content_hash(*parts) -> str:
    """sha256 over the parts, joined by a unit separator. The items dedup key."""
    joined = UNIT_SEP.join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def now_iso() -> str:
    """Current UTC time as an ISO-8601 string (fetched_at)."""
    return datetime.now(timezone.utc).isoformat()


def to_iso(value) -> str | None:
    """Normalize an arbitrary date/datetime string to ISO-8601, or None."""
    if not value:
        return None
    try:
        return dateparser.parse(str(value)).isoformat()
    except (ValueError, OverflowError):
        return None
