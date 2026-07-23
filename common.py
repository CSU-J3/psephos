"""Shared collector helpers: HTTP with retry, content hashing, timestamps.

Every collector reuses these so dedup keys and time formats stay consistent
across channels.
"""

from __future__ import annotations

import hashlib
import re
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
    present); raises for any other error status.
    """
    if throttle:
        time.sleep(throttle)
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code in RETRY_STATUS:
                if resp.status_code == 429:
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
                time.sleep(_retry_after(resp, attempt))
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"GET failed after {MAX_RETRIES} attempts: {url}") from last_exc


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
