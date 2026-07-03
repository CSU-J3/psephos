"""Offline tests for common._retry_after's backoff bounds.

Pure functions only -- no network, no DB. Guards that a large Retry-After header
is honored only up to MAX_RETRY_AFTER, so one throttled request can't stall the
shared cron step. Run:  pytest tests/test_common.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

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


if __name__ == "__main__":
    test_retry_after_caps_huge_header()
    test_retry_after_passes_small_header_through()
    test_retry_after_no_header_uses_exponential()
    print("ok")
