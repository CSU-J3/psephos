"""Unit 99, ruling 2a: no credential survives into the issue comment or the channel_runs
evidence, whatever error a channel meets.

Actions masks secrets in the run LOG. It does not mask text a step sends to the Issues
API, so the `collect red` comment cannot lean on the mask. This plants a FAKE value for
every credential the collect run carries -- the Congress.gov key, the LegiScan key, the
CourtListener token, the Turso URL and token -- under their real variable names, into
every error each credentialed channel can raise: response bodies, LegiScan alerts, and
request URLs carrying the key as a query parameter. It drives each collector's real
main(), renders the issue comment through tools.collect_verdict.main() exactly as the
Verdict step does, and asserts that none of the fake values survives in the evidence, the
comment, or the lines the run prints; and that no evidence line carries a query string.

FAKE VALUES ONLY (the secret-audit rule). config.load_env is replaced, so no `.env` is
read, and the database is a temp SQLite file, never the Turso URL planted here.

Run:  pytest tests/test_unit99_secrets.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import common  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import run_signals as rs  # noqa: E402
from collectors import legislation as leg  # noqa: E402
from collectors import litigation as lit  # noqa: E402
from collectors import state  # noqa: E402
from tools import collect_verdict as cv  # noqa: E402

_REAL_INIT, _REAL_CONNECT = db.init_db, db.connect

RID = "990222"
FAKE = {
    "CONGRESS_API_KEY": "FAKECONGRESSKEY-0123456789abcdefghij",
    "LEGISCAN_API_KEY": "FAKELEGISCANKEY-9876543210fedcba",
    "COURTLISTENER_TOKEN": "FAKECOURTLISTENERTOKEN-00112233445566778899",
    "TURSO_DATABASE_URL": "libsql://psephos-fakedb-0000.example-region.turso.io",
    "TURSO_AUTH_TOKEN": "FAKETURSOTOKEN.eyJmYWtlIjoidHJ1ZSJ9.abcdefghij0123456789",
}
TURSO_HOST = "psephos-fakedb-0000.example-region.turso.io"
NEEDLES = (*FAKE.values(), TURSO_HOST)

# Each source's request URL with its own key as a query parameter, as a server that
# echoes the request would carry it.
URLQ = {
    "legislation": ("https://api.congress.gov/v3/bill/119/hr/22"
                    f"?api_key={FAKE['CONGRESS_API_KEY']}&format=json"),
    "litigation": ("https://www.courtlistener.com/api/rest/v4/dockets/"
                   f"?docket_number=1:26-cv-01&token={FAKE['COURTLISTENER_TOKEN']}"),
    "state": f"https://api.legiscan.com/?key={FAKE['LEGISCAN_API_KEY']}&op=getSessionList",
}
# Every fake value, bare and inside every URL, including the database URL with its token.
# Evidence truncates at 300 characters, so a long poison tests only its front: every
# error runs with the segments forward and reversed, and each segment also runs ALONE
# through each channel's quoting path (test_each_segment_alone_...), with a positive
# control that it reached the evidence at all.
SEGMENTS = (
    "congress " + FAKE["CONGRESS_API_KEY"],
    "legiscan " + FAKE["LEGISCAN_API_KEY"],
    "courtlistener " + FAKE["COURTLISTENER_TOKEN"],
    "db " + FAKE["TURSO_DATABASE_URL"],
    "host " + TURSO_HOST,
    "dbtoken " + FAKE["TURSO_AUTH_TOKEN"],
    "GET " + URLQ["legislation"],
    "GET " + URLQ["state"],
    "GET " + URLQ["litigation"],
    "connect " + FAKE["TURSO_DATABASE_URL"] + "?authToken=" + FAKE["TURSO_AUTH_TOKEN"],
)
POISONS = {"forward": " " + " ".join(SEGMENTS) + " ",
           "reversed": " " + " ".join(reversed(SEGMENTS)) + " "}
POISON = POISONS["forward"]
QUERY_MARKS = ("api_key=", "?key=", "&token=", "authToken=")


def _code_body(code: str, p: str) -> str:
    return json.dumps({"error": {"code": code, "message": "fixture" + p}})


# Every error the shared HTTP layer can raise into a channel, each carrying the poison
# `p` in its body and the key-bearing URL `u` in its message.
COMMON_ERRORS = {
    "401": lambda u, p: common.HttpError(401, u, "Unauthorized" + p),
    "403": lambda u, p: common.HttpError(403, u, "Forbidden" + p),
    "400": lambda u, p: common.HttpError(400, u, "Bad Request" + p),
    "404": lambda u, p: common.HttpError(404, u, "Not Found" + p),
    "503 retried": lambda u, p: common.RetriesExhausted(
        f"GET failed after 4 attempts: {u} (last: HTTP 503: {p})", 503,
        "Service Unavailable" + p),
    "429 retried": lambda u, p: common.RetriesExhausted(
        f"GET failed after 4 attempts: {u} (last: HTTP 429: {p})", 429,
        "Too Many Requests" + p),
    "transport": lambda u, p: common.RetriesExhausted(f"GET failed after 4 attempts: {u}"),
    "rate budget": lambda u, p: common.RateBudgetExhausted(None, "Rate limit exceeded" + p),
    "runtime": lambda u, p: RuntimeError(f"persistent empty pages from {u}" + p),
}
# api.data.gov's shapes: the key codes on their documented status and off it, and the
# rate limit, retried and budgeted.
LEGISLATION_ERRORS = {
    **COMMON_ERRORS,
    "403 key code": lambda u, p: common.HttpError(403, u, _code_body("API_KEY_INVALID", p)),
    "400 key code": lambda u, p: common.HttpError(400, u, _code_body("API_KEY_DISABLED", p)),
    "429 over rate limit": lambda u, p: common.RetriesExhausted(
        f"GET failed after 4 attempts: {u}", 429, _code_body("OVER_RATE_LIMIT", p)),
    "budget over rate limit": lambda u, p: common.RateBudgetExhausted(
        3600, _code_body("OVER_RATE_LIMIT", p)),
}
LITIGATION_ERRORS = dict(COMMON_ERRORS)
# LegiScan answers 200 with status=ERROR and an alert; these are payloads, not raises.
STATE_ERRORS = {
    **COMMON_ERRORS,
    "alert naming the key": lambda u, p: {"status": "ERROR",
                                          "alert": {"message": "Invalid API key" + p}},
    "alert not naming it": lambda u, p: {"status": "ERROR",
                                         "alert": {"message": "Service unavailable" + p}},
    "allowance alert": lambda u, p: {"status": "ERROR",
                                     "alert": {"message": "Monthly query limit reached" + p}},
    "allowance 429": lambda u, p: common.RateBudgetExhausted(
        None, "Rate limit exceeded: 10000/month." + p),
    "allowance 503 retried": lambda u, p: common.RetriesExhausted(
        f"GET failed after 4 attempts: {u}", 503, "Monthly query limit reached" + p),
}
ERRORS = {"legislation": LEGISLATION_ERRORS, "litigation": LITIGATION_ERRORS,
          "state": STATE_ERRORS}
# The path on which each channel QUOTES the body into its evidence: the loud line that
# carries the most of it, so a segment that survives anywhere survives here.
QUOTING = {"legislation": "403", "litigation": "401", "state": "alert naming the key"}
MAINS = {"legislation": leg.main, "litigation": lit.main, "state": state.main}
KEY_ENV = {"legislation": "CONGRESS_API_KEY", "litigation": "COURTLISTENER_TOKEN",
           "state": "LEGISCAN_API_KEY"}


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Every credential set to its fake under its real name; no .env; a temp database;
    the slot unset so state runs; the tracker's seeds empty so litigation walks only the
    config seeds."""
    path = str(tmp_path / "t.db")
    _REAL_INIT(path)
    monkeypatch.setattr(config, "load_env", lambda *a, **k: None)
    monkeypatch.setattr(db, "init_db", lambda *a, **k: _REAL_INIT(path))
    monkeypatch.setattr(db, "connect", lambda *a, **k: _REAL_CONNECT(path))
    monkeypatch.setattr(lit, "load_tracker_seeds", lambda *a, **k: [])
    monkeypatch.delenv(db.REQUIRE_REMOTE_ENV, raising=False)
    monkeypatch.delenv("SLOT", raising=False)
    for name, value in FAKE.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("GITHUB_RUN_ID", RID)
    runner_temp = tmp_path / "runner_temp"
    runner_temp.mkdir()
    for k, v in {"RUNNER_TEMP": str(runner_temp), "JOB_STATUS": "success",
                 "RUN_URL": "https://example.invalid/runs/990222",
                 "RUN_STARTED_AT": "2026-09-28T20:00:00Z"}.items():
        monkeypatch.setenv(k, v)
    return {"path": path, "comment": runner_temp / "collect-verdict.md"}


def _upstream(make, url, poison):
    """A common.http_get that answers every call with `make(url, poison)`: raised when it
    is an exception, returned when it is a payload. It calls on_attempt as the real one
    does, so state's meter counts the request."""
    def http_get(u, params=None, headers=None, timeout=None, throttle=0.0,
                 on_attempt=None, **kw):
        if on_attempt is not None:
            on_attempt()
        r = make(url, poison)
        if isinstance(r, BaseException):
            raise r
        return r
    return http_get


def _evidence(path: str) -> list[tuple[str, str, str]]:
    conn = _REAL_CONNECT(path)
    try:
        return [tuple(r) for r in conn.execute(
            "SELECT channel, class, evidence FROM channel_runs WHERE run_id = ?",
            (RID,)).fetchall()]
    finally:
        conn.close()


def _run_and_render(world, channel, capsys):
    """The channel's real main(), then the Verdict step's main(); returns the run's rows,
    the rendered comment, and everything printed."""
    assert MAINS[channel]() == 0
    collector = capsys.readouterr()
    assert cv.main() == 1                    # a dispatch expects all three channels: red
    verdict = capsys.readouterr()
    rows = _evidence(world["path"])
    comment = world["comment"].read_text(encoding="utf-8")
    printed = collector.out + collector.err + verdict.out + verdict.err
    return rows, comment, printed


def _assert_clean(rows, comment, printed):
    for needle in NEEDLES:
        for ch, cls, ev in rows:
            assert needle not in ev, (ch, cls)
        assert needle not in comment
        assert needle not in printed
    for ch, cls, ev in rows:
        for mark in QUERY_MARKS:
            assert mark not in ev, (ch, cls, mark)
    for mark in QUERY_MARKS:
        assert mark not in comment


CASES = [(ch, name, order) for ch, errors in ERRORS.items() for name in errors
         for order in POISONS]


@pytest.mark.parametrize("channel, error, order", CASES,
                         ids=[f"{c}-{e}-{o}" for c, e, o in CASES])
def test_no_fake_credential_survives_any_channel_error(world, monkeypatch, capsys,
                                                       channel, error, order):
    monkeypatch.setattr(common, "http_get",
                        _upstream(ERRORS[channel][error], URLQ[channel], POISONS[order]))
    rows, comment, printed = _run_and_render(world, channel, capsys)
    assert any(ch == channel for ch, _, _ in rows), "the channel wrote its row"
    # A loud class reaches the comment; a quiet one (a per-item skip, `unreached`) does
    # not, and its row is checked all the same.
    if any(ch == channel and cls in rs.LOUD for ch, cls, _ in rows):
        assert f"| {channel} |" in comment
    _assert_clean(rows, comment, printed)


@pytest.mark.parametrize("channel", sorted(MAINS))
def test_a_missing_key_leaves_the_others_out_too(world, monkeypatch, capsys, channel):
    """R5's line names the variable; the other four credentials are still in the
    environment and still stay out."""
    monkeypatch.delenv(KEY_ENV[channel])
    monkeypatch.setattr(common, "http_get",
                        _upstream(COMMON_ERRORS["403"], URLQ[channel], POISON))
    rows, comment, printed = _run_and_render(world, channel, capsys)
    assert (channel, rs.MISSING, f"{KEY_ENV[channel]} is not set") in rows
    _assert_clean(rows, comment, printed)


SEGMENT_CASES = [(ch, i) for ch in sorted(MAINS) for i in range(len(SEGMENTS))]


@pytest.mark.parametrize("channel, i", SEGMENT_CASES,
                         ids=[f"{c}-segment{i}" for c, i in SEGMENT_CASES])
def test_each_segment_alone_is_quoted_without_its_value(world, monkeypatch, capsys,
                                                        channel, i):
    """One segment, short enough that truncation cannot hide it, through the channel's
    quoting path. The POSITIVE CONTROL: the segment's non-secret part -- its label, or
    the URL stripped of its query -- reaches the evidence, so a clean result means the
    value was removed, not that the text never arrived."""
    segment = SEGMENTS[i]
    monkeypatch.setattr(common, "http_get",
                        _upstream(ERRORS[channel][QUOTING[channel]], URLQ[channel],
                                  " " + segment + " "))
    rows, comment, printed = _run_and_render(world, channel, capsys)
    loud = [ev for ch, cls, ev in rows if ch == channel and cls in rs.LOUD]
    assert loud, rows
    label, _, rest = segment.partition(" ")
    control = rs.strip_queries(rest) if "://" in rest else rs.REDACTED
    control = control.replace(FAKE["TURSO_DATABASE_URL"], rs.REDACTED)
    assert f"{label} {control}" in loud[0], (loud[0], label, control)
    _assert_clean(rows, comment, printed)


def test_the_verdict_keeps_them_out_of_its_own_findings_and_any_other_writers_rows(
        world, monkeypatch, capsys):
    """Rows the collectors did not scrub -- another writer's, or an older build's -- and
    a database error naming everything: the comment is scrubbed again as it renders."""
    conn = _REAL_CONNECT(world["path"])
    conn.execute("INSERT INTO channel_runs (run_id, channel, class, evidence, written_at) "
                 "VALUES (?, 'legislation', 'credential failure', ?, '2026-09-28T20:01:00+00:00')",
                 (RID, "raw" + POISON))
    conn.execute("INSERT INTO channel_runs (run_id, channel, class, evidence, written_at) "
                 "VALUES (?, 'state', 'no OK replies', ?, '2026-09-28T20:01:00+00:00')",
                 (RID, "raw" + POISONS["reversed"]))
    conn.commit()
    conn.close()
    assert cv.main() == 1
    out = capsys.readouterr()
    comment = world["comment"].read_text(encoding="utf-8")
    _assert_clean([], comment, out.out + out.err)

    def unreadable(*a, **k):
        raise RuntimeError("stream error" + POISON)

    monkeypatch.setattr(cv, "verdict", unreadable)
    assert cv.main() == 1
    out = capsys.readouterr()
    comment = world["comment"].read_text(encoding="utf-8")
    assert "| job | job | the verdict could not read the database: RuntimeError |" in comment
    _assert_clean([], comment, out.out + out.err)


def test_the_credential_names_are_the_ones_the_run_carries():
    """CREDENTIAL_ENV is every key_env in config/sources.yaml plus the Turso pair, and
    collect.yml's collectors step passes each of them."""
    sources = yaml.safe_load((REPO / "config" / "sources.yaml").read_text(encoding="utf-8"))
    key_envs = {sources[ch]["api"]["key_env"] for ch in ("legislation", "litigation", "state")}
    assert set(rs.CREDENTIAL_ENV) == key_envs | {"TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN"}
    wf = yaml.safe_load((REPO / ".github" / "workflows" / "collect.yml").read_text(
        encoding="utf-8"))
    step = next(s for s in wf["jobs"]["collect"]["steps"] if s.get("name") == "Run collectors")
    assert set(rs.CREDENTIAL_ENV) <= set(step["env"])


def test_env_secrets_reads_every_credential_and_the_database_host(monkeypatch):
    for name, value in FAKE.items():
        monkeypatch.setenv(name, value)
    got = rs.env_secrets()
    assert set(got) == set(NEEDLES)
    for name in FAKE:
        monkeypatch.delenv(name)
    assert rs.env_secrets() == ()


@pytest.mark.parametrize("text, stripped", [
    ("GET https://api.congress.gov/v3/bill/119/hr/22?api_key=abc&format=json done",
     "GET https://api.congress.gov/v3/bill/119/hr/22 done"),
    ("see 'https://api.legiscan.com/?key=abc&op=getBill'.", "see 'https://api.legiscan.com/'."),
    ("libsql://db.example.turso.io?authToken=abc", "libsql://db.example.turso.io"),
    ("wss://db.example.turso.io/v2#frag", "wss://db.example.turso.io/v2"),
    ("no url here? really", "no url here? really"),
])
def test_strip_queries(text, stripped):
    assert rs.strip_queries(text) == stripped
