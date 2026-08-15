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
                    # CLASSIFY ON THE SCOPE'S UNIT, NOT THE RESET'S MAGNITUDE.
                    # This used to read any reset above MAX_RETRY_AFTER as a spent
                    # daily budget and abort the run. Finding 22 measured the response
                    # that refutes it: `Rate limit exceeded: 20/min` with
                    # `retry-after: 46`. The reset is large BECAUSE the burst was
                    # tight -- 20 requests inside 14.5s means the oldest ages out at
                    # t=60, so 60-14.5 ~= 46 -- and a per-minute window's ceiling is
                    # 60s, DOUBLE MAX_RETRY_AFTER. So under the old rule the tighter
                    # the burst, the more certainly it was misread as a daily cap.
                    # Cost: both 429s this account has ever produced are per-minute
                    # scopes, so every real 429 in the project's history aborted
                    # litigation for the cycle over a condition clearing in under a
                    # minute, while the daily branch never saw a real response.
                    #
                    # Retry is viable, measured against _retry_after rather than
                    # assumed: retry-after 46 caps to 30 per attempt, so requests land
                    # at t = 0, 30, 60, 90 and the third is past the window, with a
                    # fourth in reserve. The 60s ceiling means EVERY per-minute
                    # throttle clears inside MAX_RETRIES.
                    #
                    # The unscoped arm below is deliberately untouched: where a body
                    # names its scope we believe it, and where nothing parses the old
                    # magnitude rule still runs. The fix adds information rather than
                    # swapping one guess for another.
                    #
                    # Known cost of the unit rule: an /hour scope is sub-daily, so it
                    # retries, but its window (up to 3600s) outlasts the ~90s ladder --
                    # it exhausts to RuntimeError, a per-item skip, spending four
                    # requests to learn that. CourtListener's 1,000/hour is real. That
                    # is still preferred to aborting the collector on a window that may
                    # well clear, and a per-item skip keeps the run alive either way.
                    scope = _throttle_scope(resp)
                    if scope == "cap":
                        raise RateBudgetExhausted(_reset_seconds(resp))
                    if scope is None:
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


# The scope units a throttle body can name, split by whether their window can
# clear inside the retry ladder. Matched on PREFIXES rather than first letters,
# which is load-bearing: "m" is ambiguous between min and month, and reading a
# monthly cap as a burst is precisely the failure this classifier prevents --
# also the shape LegiScan's EDU cap would take. DRF spells these out as
# second/minute/hour/day as readily as abbreviating them, so both must match.
_BURST_UNITS = ("sec", "min", "hour")
_CAP_UNITS = ("day", "week", "month", "year")


def _throttle_scope(resp: requests.Response) -> str | None:
    """Which throttle a 429 names: `burst` (retryable), `cap` (hopeless), or None.

    The scope lives ONLY in the body. CourtListener sends no X-RateLimit-* header
    of any kind -- finding 22 dumped all twenty headers to confirm it -- so
    `retry-after` gives a delay with no scope attached, and any classifier reading
    the header alone is guessing while looking informed.

    Both real captures read `Rate limit exceeded: <N>/<unit>.`, so the unit is the
    token after the slash. Returns None rather than guessing when nothing parses,
    which hands the decision back to _get's magnitude fallback."""
    m = re.search(r"[Rr]ate limit exceeded:\s*\d+\s*/\s*([A-Za-z]+)", resp.text)
    if not m:
        return None
    unit = m.group(1).lower()
    if unit.startswith(_BURST_UNITS):
        return "burst"
    if unit.startswith(_CAP_UNITS):
        return "cap"
    return None


def _reset_seconds(resp: requests.Response) -> int | None:
    """Seconds until a throttle frees, UNCAPPED (unlike _retry_after): the Retry-After
    header, else the count in an `Expected available in N seconds` throttle body.

    Magnitude is now the FALLBACK discriminator, not the primary one: _throttle_scope
    reads the scope's unit from the body and only an unscoped throttle is decided on
    this number. The docstring used to claim the magnitude was what told a cap from a
    burst, which finding 22 refuted -- a 20/min throttle reports up to 60s."""
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
