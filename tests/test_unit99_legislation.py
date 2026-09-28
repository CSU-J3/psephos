"""Unit 99 on the legislation channel: the loud line, the channel_runs row, and the key.

WHY THIS EXISTS. The Congress.gov key sat disabled for 33 scheduled runs and every one
concluded `success`: six `ERROR:` lines a run, exit 0, nothing downstream reading a log.
Unit 99 keeps the exit 0 and makes the failure LOUD -- one literal line per class and a
`channel_runs` row the verdict step reads. Each test below plants the upstream reply that
class exists for and drives the real `main()` end to end: the real `collect_bill`, the
real `classify`, the real `RunSignals`, and a real local SQLite database built from
`schema.sql`. Only the HTTP layer (`common.http_get`) and the config/env loaders are
faked; `.env` is never read.

THE KEY IS A FIXTURE and every main()-driven test ends by asserting it appears nowhere:
not in stdout, not in stderr, not in any row's evidence. The line names the channel and
nothing about the key (run_signals' module docstring); that is the property pinned.

Run:  pytest tests/test_unit99_legislation.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.chdir(REPO)

import common  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import run_signals  # noqa: E402
from collectors import legislation as leg  # noqa: E402

FAKE_KEY = "FIXTUREKEY-0123456789abcdef"
KEY_ENV = "PSEPHOS_FIXTURE_CONGRESS_KEY"
BASE = "https://api.congress.gov/v3/"
RUN_ID = "990099"

# Captured before any test patches them: the harness reroutes main()'s no-argument
# calls to these, pinned to the test's own file.
_REAL_CONNECT = db.connect
_REAL_INIT = db.init_db

# The body api.congress.gov returned for the disabled key, VERBATIM. Its message is not
# the api.data.gov manual's wording, which is why R2 matches on error.code alone.
DISABLED_BODY = (
    '{"error": {"code": "API_KEY_DISABLED", "message": "The api_key supplied has been '
    'disabled. Contact us for assistance: https://api.congress.gov:443"}}'
)
RATE_BODY = (
    '{"error": {"code": "OVER_RATE_LIMIT", "message": "You have exceeded your rate '
    'limit. Try again later or contact us at https://api.congress.gov:443/contact/ '
    'for assistance"}}'
)

# The five api.data.gov key codes, spelled out here rather than read from leg.KEY_CODES:
# a code dropped from the source set must fail this file, not shrink it.
FIVE_KEY_CODES = ("API_KEY_MISSING", "API_KEY_INVALID", "API_KEY_DISABLED",
                  "API_KEY_UNAUTHORIZED", "API_KEY_UNVERIFIED")

SIGNAL_PREFIXES = tuple(sorted(set(run_signals.PREFIX.values())))

THREE_BILLS = [
    {"bill_id": "hr22-119", "congress": 119, "type": "hr", "number": 22},
    {"bill_id": "s1383-119", "congress": 119, "type": "s", "number": 1383,
     "is_vehicle": True},
    {"bill_id": "hr7296-119", "congress": 119, "type": "hr", "number": 7296},
]

_SUFFIX_FIELD = {"/actions": "actions", "/amendments": "amendments",
                 "/relatedbills": "relatedBills"}


def _api_error(code: str, message: str = "fixture message") -> str:
    return json.dumps({"error": {"code": code, "message": message}})


class _Upstream:
    """A fake Congress.gov behind `common.http_get`. `plan` maps a bill_id to a factory
    (url -> exception) raised on that bill's FIRST request -- the detail GET, which is
    where a refused key or a spent window lands. An unplanned bill answers OK."""

    def __init__(self):
        self.watchlist: list[dict] = []
        self.plan: dict = {}
        self.calls: list[tuple[str, str]] = []   # (bill_id, suffix)

    def _stem(self, entry: dict) -> str:
        return f"{BASE.rstrip('/')}/bill/{entry['congress']}/{entry['type']}/{entry['number']}"

    def http_get(self, url, params=None, headers=None, timeout=None, throttle=0.0,
                 on_attempt=None):
        # The key travels in params, never in the URL -- the shape common._get has, and
        # the reason an HttpError's message (which names the URL) is key-free by itself.
        assert params and params.get("api_key") == FAKE_KEY
        assert FAKE_KEY not in url
        for entry in self.watchlist:
            stem = self._stem(entry)
            if url.startswith(stem) and url[len(stem):] in ("", *_SUFFIX_FIELD):
                suffix = url[len(stem):]
                break
        else:
            raise AssertionError(f"unexpected URL {url}")
        bill_id = entry["bill_id"]
        self.calls.append((bill_id, suffix))
        if suffix == "" and bill_id in self.plan:
            raise self.plan[bill_id](url)
        if suffix == "":
            return {"bill": {
                "title": f"Fixture title for {bill_id}",
                "sponsors": [{"fullName": "Rep. Fixture"}],
                "introducedDate": "2025-01-03",
                "latestAction": {"text": "Referred to committee.", "actionDate": "2025-01-03"},
                "cosponsors": {"count": 7},
            }}
        if suffix == "/actions":
            return {"actions": [{"actionDate": "2025-01-03", "text": "Introduced.",
                                 "actionCode": "Intro-H"}], "pagination": {"count": 1}}
        return {_SUFFIX_FIELD[suffix]: [], "pagination": {"count": 0}}

    def bills_requested(self) -> list[str]:
        return [b for b, s in self.calls if s == ""]


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """main() against a local file DB and the fake upstream, with the fixture key set."""
    path = str(tmp_path / "t.db")
    _REAL_INIT(path)
    up = _Upstream()
    up.watchlist = [dict(b) for b in THREE_BILLS]

    monkeypatch.setattr(config, "load_env", lambda *a, **k: None)   # never read .env
    monkeypatch.setattr(db, "init_db", lambda *a, **k: _REAL_INIT(path))
    monkeypatch.setattr(db, "connect", lambda *a, **k: _REAL_CONNECT(path))
    monkeypatch.setattr(config, "load_sources", lambda *a, **k: {"legislation": {
        "api": {"base": BASE, "key_env": KEY_ENV},
        "default_grade": {"source": "A", "info": "1"},
        "watchlist": up.watchlist,
    }})
    monkeypatch.setattr(common, "http_get", up.http_get)
    monkeypatch.setenv(KEY_ENV, FAKE_KEY)
    monkeypatch.setenv("GITHUB_RUN_ID", RUN_ID)
    up.path = path
    return up


def _rows(path: str) -> list[tuple]:
    conn = _REAL_CONNECT(path)
    try:
        return [tuple(r) for r in conn.execute(
            "SELECT run_id, channel, class, evidence FROM channel_runs ORDER BY class"
        ).fetchall()]
    finally:
        conn.close()


def _count(path: str, table: str) -> int:
    conn = _REAL_CONNECT(path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _signal_lines(out: str) -> list[str]:
    return [ln for ln in out.splitlines() if ln.startswith(SIGNAL_PREFIXES)]


def _assert_key_absent(out: str, err: str, path: str) -> None:
    assert FAKE_KEY not in out
    assert FAKE_KEY not in err
    for row in _rows(path):
        assert FAKE_KEY not in " ".join(row)


# --- (1) the observed failure, end to end -------------------------------------------


def test_disabled_key_prints_one_credential_line_and_writes_its_row(harness, capsys):
    """The 33-run incident, replayed. Every bill gets the verbatim 403; the line prints
    ONCE (RunSignals dedups the class), the row carries the same evidence, main exits 0.
    A credential failure does not stop the loop -- only a cut-short does -- so every bill
    is still attempted, which is what makes the single line a dedup and not a break."""
    harness.plan = {b["bill_id"]: (lambda url: common.HttpError(403, url, DISABLED_BODY))
                    for b in THREE_BILLS}

    assert leg.main() == 0

    out, err = capsys.readouterr()
    line = "CREDENTIAL FAILURE legislation: API_KEY_DISABLED (HTTP 403)"
    assert _signal_lines(out) == [line]
    assert out.splitlines().count(line) == 1
    assert harness.bills_requested() == [b["bill_id"] for b in THREE_BILLS]
    assert err.count("ERROR:") == 3            # the per-bill skip lines still print
    # No bill answered OK, so no `ok` row: the verdict reads the credential row alone.
    assert _rows(harness.path) == [
        (RUN_ID, "legislation", run_signals.CREDENTIAL, "API_KEY_DISABLED (HTTP 403)"),
    ]
    assert _count(harness.path, "bills") == 0
    _assert_key_absent(out, err, harness.path)


# --- (2) every key code, and the codes that are not key codes ------------------------


def test_the_five_key_codes_are_exactly_leg_key_codes():
    assert set(FIVE_KEY_CODES) == set(leg.KEY_CODES)


@pytest.mark.parametrize("code", FIVE_KEY_CODES)
@pytest.mark.parametrize("status", [403, 401])
def test_each_key_code_classifies_as_credential(code, status):
    """Matched on error.code, whatever the message says (R2)."""
    exc = common.HttpError(status, f"{BASE}bill/119/hr/22",
                           _api_error(code, "wording the manual never used"))
    assert leg.classify(exc, FAKE_KEY) == (run_signals.CREDENTIAL,
                                           f"{code} (HTTP {status})")


@pytest.mark.parametrize("code", FIVE_KEY_CODES)
def test_each_key_code_reaches_the_credential_line_through_main(harness, capsys, code):
    harness.plan = {"hr22-119": lambda url: common.HttpError(403, url, _api_error(code))}

    assert leg.main() == 0

    out, err = capsys.readouterr()
    assert _signal_lines(out) == [f"CREDENTIAL FAILURE legislation: {code} (HTTP 403)"]
    classes = [r[2] for r in _rows(harness.path)]
    assert classes == [run_signals.CREDENTIAL, run_signals.OK]
    _assert_key_absent(out, err, harness.path)


@pytest.mark.parametrize("status, code", [
    (404, "NOT_FOUND"),          # api.data.gov: an unknown route, not the key
    (400, "HTTPS_REQUIRED"),     # api.data.gov: the scheme, not the key
])
def test_not_found_and_https_required_are_not_credential(status, code):
    exc = common.HttpError(status, f"{BASE}bill/119/hr/22", _api_error(code))
    assert leg.classify(exc, FAKE_KEY) is None


def test_non_key_failures_are_per_bill_skips_and_stay_quiet(harness, capsys):
    """404 NOT_FOUND, 400 HTTPS_REQUIRED and a transport exhaustion each skip one bill
    and print nothing loud; the next bill still runs. The transport case is chained from
    an error whose text carries `?api_key=` -- the hazard run_signals names -- and main
    must not format that __cause__."""
    harness.watchlist.append({"bill_id": "hr7300-119", "congress": 119, "type": "hr",
                              "number": 7300})

    def transport(url):
        exc = common.RetriesExhausted(f"GET failed after 4 attempts: {url}", None, "")
        exc.__cause__ = ConnectionError(f"Max retries exceeded with url: {url}"
                                        f"?api_key={FAKE_KEY}&format=json")
        return exc

    harness.plan = {
        "hr22-119": lambda url: common.HttpError(404, url, _api_error("NOT_FOUND")),
        "s1383-119": lambda url: common.HttpError(400, url, _api_error("HTTPS_REQUIRED")),
        "hr7296-119": transport,
    }

    assert leg.main() == 0

    out, err = capsys.readouterr()
    assert _signal_lines(out) == []
    assert harness.bills_requested() == ["hr22-119", "s1383-119", "hr7296-119",
                                         "hr7300-119"]
    assert _rows(harness.path) == [(RUN_ID, "legislation", run_signals.OK, "1 OK reply")]
    _assert_key_absent(out, err, harness.path)


# --- (3) an unrecognised refusal is quoted, and the key in it redacted ---------------


ECHO_BODY = ('{"message": "Forbidden: key ' + FAKE_KEY + ' is not allowed from '
             '198.51.100.7"}')


def test_unrecognised_403_body_is_quoted_with_the_key_redacted(harness, capsys):
    """R2's other half: ANY 403 whose body is not a key code is still a credential
    failure, with the body quoted so a person can read what the server said. A body that
    echoes the key reaches the line and the row as [redacted]; quote() also turns the
    body's double quotes to single so the evidence has one pair of quotes."""
    harness.plan = {b["bill_id"]: (lambda url: common.HttpError(403, url, ECHO_BODY))
                    for b in THREE_BILLS}

    assert leg.main() == 0

    out, err = capsys.readouterr()
    evidence = ("HTTP 403 \"{'message': 'Forbidden: key [redacted] is not allowed from "
                "198.51.100.7'}\"")
    assert _signal_lines(out) == [f"CREDENTIAL FAILURE legislation: {evidence}"]
    assert _rows(harness.path) == [
        (RUN_ID, "legislation", run_signals.CREDENTIAL, evidence),
    ]
    assert FAKE_KEY not in out
    for row in _rows(harness.path):
        assert FAKE_KEY not in " ".join(row)


@pytest.mark.parametrize("status, body, evidence", [
    (401, "Unauthorized", 'HTTP 401 "Unauthorized"'),
    (403, "<html>\n  <body>403   Forbidden</body>\n</html>",
     'HTTP 403 "<html> <body>403 Forbidden</body> </html>"'),
    # A key-shaped code this file does not know is quoted, never trusted as a key code.
    (403, _api_error("API_KEY_SOMETHING_NEW", "new"),
     "HTTP 403 \"{'error': {'code': 'API_KEY_SOMETHING_NEW', 'message': 'new'}}\""),
    (403, "denied for " + FAKE_KEY, 'HTTP 403 "denied for [redacted]"'),
])
def test_unrecognised_401_403_bodies_classify_as_quoted_credential(status, body, evidence):
    exc = common.HttpError(status, f"{BASE}bill/119/hr/22", body)
    assert leg.classify(exc, FAKE_KEY) == (run_signals.CREDENTIAL, evidence)


def test_a_body_echoing_the_key_leaves_no_trace_on_stderr(harness, capsys):
    """The per-bill ERROR line predates unit 99 and prints the exception's text, which
    carries the body; run_signals.safe() scrubs the key from it. Written as a strict xfail
    by the test's author, who found the leak; it passes now and stays as a guard."""
    harness.plan = {"hr22-119": lambda url: common.HttpError(403, url, ECHO_BODY)}

    assert leg.main() == 0

    out, err = capsys.readouterr()
    assert FAKE_KEY not in out
    assert FAKE_KEY not in err


# --- (4) a spent window is a cut-short that stops the loop ---------------------------


def _retries_429(url):
    return common.RetriesExhausted(
        f"GET failed after 4 attempts: {url} (last: HTTP 429: {RATE_BODY[:500]})",
        429, RATE_BODY)


def _budget_429(url):
    return common.RateBudgetExhausted(3600.0, RATE_BODY)


@pytest.mark.parametrize("make, line", [
    (_retries_429,
     "RUN CUT SHORT legislation: OVER_RATE_LIMIT; remaining bills skipped"),
    (_budget_429,
     "RUN CUT SHORT legislation: OVER_RATE_LIMIT (daily rate budget exhausted; "
     "resets in ~3600s); remaining bills skipped"),
])
def test_over_rate_limit_429_cuts_the_run_short_and_stops_the_loop(harness, capsys,
                                                                   make, line):
    """R6: the rate window is shared across the key, so the bill after a spent window
    must not spend a request. Bill 1 answers, bill 2 hits OVER_RATE_LIMIT, bill 3 is
    never requested. The row set carries both the cut-short and the ok receipt."""
    harness.plan = {"s1383-119": make}

    assert leg.main() == 0

    out, err = capsys.readouterr()
    assert _signal_lines(out) == [line]
    assert harness.bills_requested() == ["hr22-119", "s1383-119"]
    assert not any(b == "hr7296-119" for b, _ in harness.calls)
    assert _rows(harness.path) == [
        (RUN_ID, "legislation", run_signals.CUT, line.split(": ", 1)[1]),
        (RUN_ID, "legislation", run_signals.OK, "1 OK reply"),
    ]
    _assert_key_absent(out, err, harness.path)


@pytest.mark.parametrize("exc, evidence", [
    (common.RetriesExhausted("GET failed after 4 attempts", 429, ""),
     "HTTP 429; remaining bills skipped"),
    (common.RateBudgetExhausted(None, ""),
     "rate cap (daily rate budget exhausted); remaining bills skipped"),
    (common.HttpError(400, BASE, RATE_BODY),
     "OVER_RATE_LIMIT; remaining bills skipped"),
])
def test_rate_shapes_without_the_full_signature_still_cut_short(exc, evidence):
    """A 429 with no body, a spent cap with no body, and OVER_RATE_LIMIT on a non-429
    status each classify as a cut-short -- a throttle, never a credential failure."""
    assert leg.classify(exc, FAKE_KEY) == (run_signals.CUT, evidence)


# --- (5) a missing key skips the channel, loudly -------------------------------------


@pytest.mark.parametrize("value", [None, ""], ids=["unset", "empty"])
def test_missing_key_prints_the_line_writes_the_row_and_fetches_nothing(
        harness, capsys, monkeypatch, value):
    """R5: formerly config.require_env's SystemExit, which ended the `bash -e` step and
    cost every channel. Now the channel skips, names the VARIABLE (never a value), writes
    `missing secret`, and exits 0 so the other channels and the data commit still run."""
    if value is None:
        monkeypatch.delenv(KEY_ENV, raising=False)
    else:
        monkeypatch.setenv(KEY_ENV, value)
    with pytest.raises(SystemExit):           # the path main() takes, confirmed live
        config.require_env(KEY_ENV)

    assert leg.main() == 0

    out, err = capsys.readouterr()
    assert _signal_lines(out) == [f"CREDENTIAL FAILURE legislation: {KEY_ENV} is not set"]
    assert harness.calls == []
    assert _rows(harness.path) == [
        (RUN_ID, "legislation", run_signals.MISSING, f"{KEY_ENV} is not set"),
    ]
    assert _count(harness.path, "bills") == 0
    assert _count(harness.path, "sources") == 0
    _assert_key_absent(out, err, harness.path)


# --- (6) a clean run is quiet and leaves its receipt ---------------------------------


def test_clean_run_writes_one_ok_row_and_prints_nothing_loud(harness, capsys):
    assert leg.main() == 0

    out, err = capsys.readouterr()
    assert _signal_lines(out) == []
    assert "ERROR" not in err
    assert harness.bills_requested() == [b["bill_id"] for b in THREE_BILLS]
    assert _rows(harness.path) == [(RUN_ID, "legislation", run_signals.OK, "3 OK replies")]
    assert _count(harness.path, "bills") == 3
    assert _count(harness.path, "items") == 3
    _assert_key_absent(out, err, harness.path)


def test_a_second_run_under_the_same_run_id_replaces_rather_than_duplicates(harness,
                                                                            capsys):
    """channel_runs is keyed (run_id, channel, class): a GitHub re-run of the same run id
    updates its rows in place, the same idempotence the heartbeat has."""
    assert leg.main() == 0
    assert leg.main() == 0
    capsys.readouterr()
    assert _rows(harness.path) == [(RUN_ID, "legislation", run_signals.OK, "3 OK replies")]


def test_a_key_code_is_a_credential_failure_whatever_the_status():
    """R2 matches on the code: the manual lists every key code as a 403, but the code is
    what says the key cannot be used, so it counts on a 400 or a retried 5xx body too."""
    body = json.dumps({"error": {"code": "API_KEY_INVALID", "message": "An invalid api_key"}})
    assert leg.classify(common.HttpError(400, BASE, body), FAKE_KEY) == (
        run_signals.CREDENTIAL, "API_KEY_INVALID (HTTP 400)")
    assert leg.classify(common.RetriesExhausted("GET failed after 4 attempts: x", 503, body),
                        FAKE_KEY) == (run_signals.CREDENTIAL, "API_KEY_INVALID (HTTP 503)")
    # A 503 with no key code is still a quiet per-bill skip; its receipt governs (R9).
    assert leg.classify(common.RetriesExhausted("GET failed", 503, "Service Unavailable"),
                        FAKE_KEY) is None
