"""Shared collector helpers: HTTP with retry, content hashing, timestamps.

Every collector reuses these so dedup keys and time formats stay consistent
across channels.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone

import requests
from dateutil import parser as dateparser

DEFAULT_TIMEOUT = 30
MAX_RETRIES = 4
RETRY_STATUS = {429, 500, 502, 503, 504}
UNIT_SEP = "\x1f"  # field separator for content hashing


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
                wait = _retry_after(resp, attempt)
                time.sleep(wait)
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
    """Seconds to wait before a retry: Retry-After header, else exponential."""
    header = resp.headers.get("Retry-After")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    return float(2 ** attempt)


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
