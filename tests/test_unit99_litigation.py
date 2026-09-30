"""Unit 99 on the litigation channel: the loud lines main() prints and the
`channel_runs` rows it writes, pinned with planted fixtures.

The collector still exits 0 on every path (the exit-0 invariant); what unit 99 adds is
that a refused token, a cap-cut run and a planned deferral each leave ONE literal line in
the log and a row the collect run's verdict step reads. These tests drive
`collectors.litigation.main()` end to end against a local SQLite file under tmp_path
(reached through db.DB_PATH, exactly as main() reaches it) and fake every CourtListener
request at `common.http_get` -- the one layer resolve_docket, poll_entries and
refresh_status all funnel into -- or at `lit.refresh_status` where the test is about
main()'s handling rather than the pass itself. `AuthTally` is also pinned directly.

The token is an obviously fake fixture value. Every main() test asserts it never reaches
stdout or stderr; one test plants it in a response body to prove the printed line and the
row redact it.

Run:  pytest tests/test_unit99_litigation.py
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
import config  # noqa: E402
import db  # noqa: E402
import run_signals  # noqa: E402
from collectors import litigation as lit  # noqa: E402

TOKEN = "FIXTUREKEY-0123456789abcdef"
RUN_ID = "99990001"
BASE = "https://cl.invalid/api"

BODY_401 = '{"detail":"Invalid token."}'
BODY_403 = '{"detail":"You do not have permission to perform this action."}'
# What quote() makes of each body: scrubbed, inner double quotes turned to single, and
# the whole wrapped in double quotes.
QUOTED_401 = "\"{'detail':'Invalid token.'}\""
QUOTED_403 = "\"{'detail':'You do not have permission to perform this action.'}\""

ONE_ENTRY = {"results": [{"date_modified": "2026-09-01T00:00:00Z", "date_filed": "2026-09-01",
                          "description": "COMPLAINT"}], "next": None}


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def _seed(i: int) -> dict:
    return {"caption": f"United States v. S{i}", "docket_number": f"1:25-cv-0000{i}",
            "court": "District of X", "court_id": "xxd", "category": "voter-data", "notes": "n"}


def _search_hit(params: dict) -> dict:
    """The single docket a `/dockets/?docket_number=` search returns for `_seed(i)`:
    id 100 + i, pending. A fresh resolve stamps status_checked_at, so a row bound this
    way is never due in the same run's refresh pass."""
    i = int(params["docket_number"][-1])
    return {"results": [{"id": 100 + i, "absolute_url": f"/docket/{100 + i}/x/",
                         "date_filed": "2026-01-01", "date_terminated": None,
                         "case_name": f"United States v. S{i}"}]}


def _env(monkeypatch, tmp_path, *, seeds=(), token=TOKEN, **overrides) -> str:
    """Point main() at a local temp DB and a fake sources dict; never read a real .env,
    never reach Turso. `token=None` unsets the variable. Returns the DB path, already
    initialised so a test can plant `cases` rows before main() runs."""
    dbp = str(tmp_path / "m.db")
    monkeypatch.setattr(config, "load_env", lambda *a, **k: None)
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv(db.REQUIRE_REMOTE_ENV, raising=False)
    monkeypatch.setattr(db, "DB_PATH", dbp)
    monkeypatch.setenv("GITHUB_RUN_ID", RUN_ID)
    if token is None:
        monkeypatch.delenv("COURTLISTENER_TOKEN", raising=False)
    else:
        monkeypatch.setenv("COURTLISTENER_TOKEN", token)
    litcfg = {"api": {"base": BASE, "key_env": "COURTLISTENER_TOKEN"},
              "substantive_entry_types": [], "excluded_entry_phrases": [],
              "max_bootstrap_requests_per_run": 30, "status_refresh_hours": 24,
              "max_status_refresh_per_run": 40, "seed_cases": list(seeds)}
    litcfg.update(overrides)
    monkeypatch.setattr(config, "load_sources", lambda *a, **k: {"litigation": litcfg})
    monkeypatch.setattr(lit, "load_tracker_seeds", lambda *a, **k: [])
    db.init_db(dbp)
    return dbp


def _plant_pending(dbp: str, case_ids) -> None:
    """Pending `cases` rows never status-checked: every one is due for the refresh."""
    conn = db.connect(dbp)
    for cid in case_ids:
        conn.execute("INSERT INTO cases (case_id, caption, status) VALUES (?, ?, 'pending')",
                     (cid, f"case {cid}"))
    conn.commit()
    conn.close()


def _run(capsys) -> tuple[str, str]:
    """main(), its exit code held to 0, and its captured (stdout, stderr). The fixture
    token is asserted absent from both: the Authorization header is the only place the
    channel holds it, and nothing prints a header."""
    assert lit.main() == 0
    out, err = capsys.readouterr()
    assert TOKEN not in out and TOKEN not in err
    return out, err


def _lines(out: str, prefix: str) -> list[str]:
    return [ln for ln in out.splitlines() if ln.startswith(prefix)]


def _loud_lines(out: str) -> list[str]:
    return [ln for ln in out.splitlines()
            if ln.startswith(("CREDENTIAL FAILURE", "NO OK REPLIES", "RUN CUT SHORT"))]


def _rows(dbp: str) -> dict[str, dict]:
    """This run's channel_runs rows keyed by class, after checking every row carries the
    run id and the channel."""
    conn = db.connect(dbp)
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM channel_runs").fetchall()]
    finally:
        conn.close()
    assert all(r["run_id"] == RUN_ID and r["channel"] == "litigation" for r in rows)
    return {r["class"]: r for r in rows}


# --------------------------------------------------------------------------- #
# (1) a 401 on a poll
# --------------------------------------------------------------------------- #
def test_a_401_on_a_poll_prints_one_credential_line_with_the_body_quoted(
        tmp_path, monkeypatch, capsys):
    """The resolve answers, the entries poll is refused 401. collect_case swallows the
    poll failure as a per-docket skip, as it always did -- and main() now reads the
    error it carries and prints the credential line, body quoted, exit still 0."""
    dbp = _env(monkeypatch, tmp_path, seeds=[_seed(1)])
    seen_headers = []

    def fake_get(url, params=None, headers=None, timeout=None, throttle=0.0, on_attempt=None):
        seen_headers.append(headers)
        if url.endswith("/docket-entries/"):
            raise common.HttpError(401, url, BODY_401)
        return _search_hit(params)

    monkeypatch.setattr(common, "http_get", fake_get)
    out, err = _run(capsys)

    line = f"CREDENTIAL FAILURE litigation: HTTP 401 {QUOTED_401}"
    assert _lines(out, "CREDENTIAL FAILURE") == [line]
    assert _loud_lines(out) == [line]
    assert "poll failed, skipped" in err                  # still a per-docket skip
    rows = _rows(dbp)
    assert set(rows) == {run_signals.CREDENTIAL}          # no OK reply was counted
    assert rows[run_signals.CREDENTIAL]["evidence"] == f"HTTP 401 {QUOTED_401}"
    # The token WAS in play -- which is what makes its absence from the output mean
    # something rather than hold vacuously.
    assert seen_headers and all(h["Authorization"] == f"Token {TOKEN}" for h in seen_headers)


# --------------------------------------------------------------------------- #
# (2) every request 403, no OK reply
# --------------------------------------------------------------------------- #
def test_every_request_refused_403_is_a_credential_failure(tmp_path, monkeypatch, capsys):
    """Two seeds, both resolves refused 403, nothing answered OK: that is the token,
    not two dockets. One line for the class however many refusals, the count in it,
    the FIRST body quoted."""
    dbp = _env(monkeypatch, tmp_path, seeds=[_seed(1), _seed(2)])
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None, throttle=0.0, on_attempt=None):
        calls.append(url)
        body = BODY_403 if len(calls) == 1 else '{"detail":"second body, not quoted"}'
        raise common.HttpError(403, url, body)

    monkeypatch.setattr(common, "http_get", fake_get)
    out, err = _run(capsys)

    assert len(calls) == 2                                # both seeds tried; no refresh due
    line = f"CREDENTIAL FAILURE litigation: every request refused, HTTP 403 x2 {QUOTED_403}"
    assert _lines(out, "CREDENTIAL FAILURE") == [line]
    assert err.count("resolve failed, skipped") == 2
    rows = _rows(dbp)
    assert set(rows) == {run_signals.CREDENTIAL}
    assert rows[run_signals.CREDENTIAL]["evidence"] == (
        f"every request refused, HTTP 403 x2 {QUOTED_403}")


def test_403s_from_the_refresh_pass_count_toward_the_credential_verdict(
        tmp_path, monkeypatch, capsys):
    """refresh_status now returns its per-row errors and main() feeds them to the tally:
    a run whose only requests were refresh reads, every one refused 403, is a credential
    failure too -- not two quiet per-row skips."""
    dbp = _env(monkeypatch, tmp_path)                     # no seeds: only the refresh runs
    _plant_pending(dbp, ["100", "200"])

    def fake_get(url, params=None, headers=None, timeout=None, throttle=0.0, on_attempt=None):
        raise common.HttpError(403, url, BODY_403)

    monkeypatch.setattr(common, "http_get", fake_get)
    out, err = _run(capsys)

    assert err.count("status refresh failed, skipped") == 2
    assert _lines(out, "CREDENTIAL FAILURE") == [
        f"CREDENTIAL FAILURE litigation: every request refused, HTTP 403 x2 {QUOTED_403}"]
    assert set(_rows(dbp)) == {run_signals.CREDENTIAL}


# --------------------------------------------------------------------------- #
# (3) a lone 403 among OK replies
# --------------------------------------------------------------------------- #
def test_a_lone_403_among_ok_replies_is_a_per_docket_skip_not_a_credential_line(
        tmp_path, monkeypatch, capsys):
    """One docket refused 403, two answered. A 403 is a credential failure only when
    NOTHING answered; here it stays the per-docket skip it always was, and the run
    records its receipt instead."""
    dbp = _env(monkeypatch, tmp_path, seeds=[_seed(0), _seed(1), _seed(2)])

    def fake_get(url, params=None, headers=None, timeout=None, throttle=0.0, on_attempt=None):
        if url.endswith("/docket-entries/"):
            return ONE_ENTRY
        if params["docket_number"] == "1:25-cv-00001":
            raise common.HttpError(403, url, BODY_403)
        return _search_hit(params)

    monkeypatch.setattr(common, "http_get", fake_get)
    out, err = _run(capsys)

    assert _lines(out, "CREDENTIAL FAILURE") == []
    assert _loud_lines(out) == []
    assert err.count("resolve failed, skipped") == 1
    rows = _rows(dbp)
    assert set(rows) == {run_signals.OK}
    assert rows[run_signals.OK]["evidence"] == "2 OK replies"


# --------------------------------------------------------------------------- #
# (4) the seed loop hits the daily cap
# --------------------------------------------------------------------------- #
def test_the_seed_loop_cap_prints_run_cut_short_with_the_unpolled_count(
        tmp_path, monkeypatch, capsys):
    """Seed 2 of 3 hits the daily cap mid-poll. The line counts the seeds left unpolled
    -- the one that hit the cap and every one after it -- and says the refresh was
    skipped, which the code must then actually do."""
    dbp = _env(monkeypatch, tmp_path, seeds=[_seed(0), _seed(1), _seed(2)])

    def fake_get(url, params=None, headers=None, timeout=None, throttle=0.0, on_attempt=None):
        if url.endswith("/docket-entries/"):
            if params and params.get("docket") == "101":
                raise common.RateBudgetExhausted(41134)
            return ONE_ENTRY
        return _search_hit(params)

    monkeypatch.setattr(common, "http_get", fake_get)
    refreshed = []
    monkeypatch.setattr(lit, "refresh_status", lambda *a, **k: refreshed.append(1))
    out, err = _run(capsys)

    line = ("RUN CUT SHORT litigation: daily cap hit (daily rate budget exhausted; resets "
            "in ~41134s); 2 of 3 seeds unpolled, status refresh skipped")
    assert _lines(out, "RUN CUT SHORT") == [line]
    assert _loud_lines(out) == [line]
    assert refreshed == []                                # the refresh really was skipped
    assert "status refresh skipped" in err
    rows = _rows(dbp)
    assert set(rows) == {run_signals.CUT, run_signals.OK}
    assert rows[run_signals.CUT]["evidence"] == line.split(": ", 1)[1]
    assert rows[run_signals.OK]["evidence"] == "1 OK reply"   # seed 0 answered


# --------------------------------------------------------------------------- #
# (5) the refresh pass aborts on the cap
# --------------------------------------------------------------------------- #
def test_a_refresh_aborted_on_the_cap_is_no_longer_discarded(tmp_path, monkeypatch, capsys):
    """refresh_status's `aborted` flag used to be computed and thrown away, so a refresh
    the daily cap cut short exited 0 in silence. main() now binds the result and prints
    the cut-short line with how far the pass got."""
    dbp = _env(monkeypatch, tmp_path)
    _plant_pending(dbp, ["100", "200", "300"])
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None, throttle=0.0, on_attempt=None):
        calls.append(url)
        if len(calls) > 1:
            raise common.RateBudgetExhausted(46)
        return {"id": "100", "date_terminated": None}

    monkeypatch.setattr(common, "http_get", fake_get)
    out, err = _run(capsys)

    line = "RUN CUT SHORT litigation: status refresh aborted, daily cap hit; 1/3 checked"
    assert _lines(out, "RUN CUT SHORT") == [line]
    assert _loud_lines(out) == [line]
    assert _lines(out, "DEFERRED") == []
    rows = _rows(dbp)
    assert set(rows) == {run_signals.CUT, run_signals.OK}
    assert rows[run_signals.CUT]["evidence"] == "status refresh aborted, daily cap hit; 1/3 checked"
    assert rows[run_signals.OK]["evidence"] == "1 OK reply"


def test_a_refresh_both_capped_and_aborted_reports_the_abort(tmp_path, monkeypatch, capsys):
    """The two flags can both be set: the cap trims the due list, then the daily budget
    runs out inside what is left. The abort is the loud one and wins; the deferral line
    would understate a run that did not finish the work it had planned."""
    dbp = _env(monkeypatch, tmp_path, max_status_refresh_per_run=2)
    _plant_pending(dbp, ["100", "200", "300"])
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None, throttle=0.0, on_attempt=None):
        calls.append(url)
        if len(calls) > 1:
            raise common.RateBudgetExhausted(46)
        return {"id": "100", "date_terminated": None}

    monkeypatch.setattr(common, "http_get", fake_get)
    out, err = _run(capsys)

    # The denominator is the pass's own slice, as refresh_status's abort line prints it
    # (the review found the row saying 1/3 beside a log saying 1/2); the backlog the cap
    # trimmed is named beside it.
    assert _lines(out, "RUN CUT SHORT") == [
        "RUN CUT SHORT litigation: status refresh aborted, daily cap hit; 1/2 checked "
        "(3 due, capped at 2)"]
    assert "1/2 checked, rest retry next run" in err
    assert _lines(out, "DEFERRED") == []
    assert set(_rows(dbp)) == {run_signals.CUT, run_signals.OK}


# --------------------------------------------------------------------------- #
# (6) the refresh pass is capped
# --------------------------------------------------------------------------- #
def test_a_capped_refresh_prints_deferred_and_is_not_loud(tmp_path, monkeypatch, capsys):
    """The per-run cap is a PLANNED deferral: the rows left over are the freshest and
    the ordering resumes them next run. Printed, recorded, never loud."""
    dbp = _env(monkeypatch, tmp_path, max_status_refresh_per_run=2)
    _plant_pending(dbp, ["100", "200", "300"])
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None, throttle=0.0, on_attempt=None):
        calls.append(url)
        return {"id": url.rstrip("/").split("/")[-1], "date_terminated": None}

    monkeypatch.setattr(common, "http_get", fake_get)
    out, err = _run(capsys)

    assert len(calls) == 2
    line = "DEFERRED litigation: status refresh capped at 2 of 3 due; the rest resume next run"
    assert _lines(out, "DEFERRED") == [line]
    assert _loud_lines(out) == []
    rows = _rows(dbp)
    assert set(rows) == {run_signals.DEFERRED, run_signals.OK}
    assert not set(rows) & run_signals.LOUD
    assert rows[run_signals.DEFERRED]["evidence"] == line.split(": ", 1)[1]
    assert rows[run_signals.OK]["evidence"] == "2 OK replies"


# --------------------------------------------------------------------------- #
# (7) a full walk is deferred
# --------------------------------------------------------------------------- #
def test_a_walk_deferral_prints_deferred_once_and_is_not_loud(tmp_path, monkeypatch, capsys):
    """A spent full-walk request budget defers a fresh docket's walk to a later run.
    Two deferrals in one run are ONE line -- the class prints the first time it is met
    -- and one row; no docket-entries request is made."""
    dbp = _env(monkeypatch, tmp_path, seeds=[_seed(1), _seed(2)],
               max_bootstrap_requests_per_run=0)
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None, throttle=0.0, on_attempt=None):
        calls.append(url)
        if url.endswith("/docket-entries/"):
            raise AssertionError("a deferred walk must not poll")
        return _search_hit(params)

    monkeypatch.setattr(common, "http_get", fake_get)
    out, err = _run(capsys)

    assert all(u.endswith("/dockets/") for u in calls) and len(calls) == 2
    line = "DEFERRED litigation: full walk deferred, request budget spent; walks next run"
    assert _lines(out, "DEFERRED") == [line]
    assert _loud_lines(out) == []
    assert err.count("full-walk deferred (request budget spent)") == 2
    rows = _rows(dbp)
    assert set(rows) == {run_signals.DEFERRED}
    assert not set(rows) & run_signals.LOUD
    assert rows[run_signals.DEFERRED]["evidence"] == line.split(": ", 1)[1]


# --------------------------------------------------------------------------- #
# (8) a missing token
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("token", [None, ""], ids=["unset", "empty"])
def test_a_missing_token_prints_the_credential_line_writes_its_row_and_exits_zero(
        tmp_path, monkeypatch, capsys, token):
    """R5: an unset or empty COURTLISTENER_TOKEN skips the channel -- no request of any
    kind -- prints the credential line naming the VARIABLE, and records the distinct
    `missing secret` class. config.require_env's SystemExit no longer ends the step."""
    dbp = _env(monkeypatch, tmp_path, seeds=[_seed(1)], token=token)
    touched = []
    for name in ("resolve_docket", "fetch_docket", "poll_entries", "probe_mark",
                 "refresh_status"):
        monkeypatch.setattr(lit, name, lambda *a, _n=name, **k: touched.append(_n))
    monkeypatch.setattr(common, "http_get", lambda *a, **k: touched.append("http_get"))

    out, err = _run(capsys)

    assert touched == []
    line = "CREDENTIAL FAILURE litigation: COURTLISTENER_TOKEN is not set"
    assert _lines(out, "CREDENTIAL FAILURE") == [line]
    assert _loud_lines(out) == [line]
    rows = _rows(dbp)
    assert set(rows) == {run_signals.MISSING}
    assert rows[run_signals.MISSING]["evidence"] == "COURTLISTENER_TOKEN is not set"
    conn = db.connect(dbp)
    assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0
    conn.close()


# --------------------------------------------------------------------------- #
# (9) the fixture token never reaches the loud line or the row
# --------------------------------------------------------------------------- #
def test_a_token_echoed_in_a_401_body_is_redacted_from_the_line_and_the_row(
        tmp_path, monkeypatch, capsys):
    """The worst case the line has to survive: a server that echoes the token back in
    its refusal. The credential line and the channel_runs row carry `[redacted]` where
    the token was. (Every other main() test here asserts the token is absent from ALL
    output via _run(); this one plants it in a body, so stderr is checked separately
    below.)"""
    dbp = _env(monkeypatch, tmp_path, seeds=[_seed(1)])
    body = f'{{"detail":"Invalid token {TOKEN}.",  "hint":"check\\n  the header"}}'

    def fake_get(url, params=None, headers=None, timeout=None, throttle=0.0, on_attempt=None):
        if url.endswith("/docket-entries/"):
            raise common.HttpError(401, url, body)
        return _search_hit(params)

    monkeypatch.setattr(common, "http_get", fake_get)
    assert lit.main() == 0
    out, err = capsys.readouterr()

    assert TOKEN not in out
    line = ("CREDENTIAL FAILURE litigation: HTTP 401 "
            "\"{'detail':'Invalid token [redacted].', 'hint':'check\\n the header'}\"")
    assert _lines(out, "CREDENTIAL FAILURE") == [line]
    rows = _rows(dbp)
    assert TOKEN not in rows[run_signals.CREDENTIAL]["evidence"]
    assert run_signals.REDACTED in rows[run_signals.CREDENTIAL]["evidence"]
    assert all(TOKEN not in str(v) for r in rows.values() for v in r.values())


def test_an_echoed_token_never_reaches_stderr_through_the_skip_line(
        tmp_path, monkeypatch, capsys):
    """collect_case's per-docket skip line prints the exception's text, which carries
    the body; run_signals.safe() scrubs the token from it. Found by this test's author as
    a strict xfail; it passes now and stays as a guard."""
    _env(monkeypatch, tmp_path, seeds=[_seed(1)])

    def fake_get(url, params=None, headers=None, timeout=None, throttle=0.0, on_attempt=None):
        if url.endswith("/docket-entries/"):
            raise common.HttpError(401, url, f'{{"detail":"Invalid token {TOKEN}."}}')
        return _search_hit(params)

    monkeypatch.setattr(common, "http_get", fake_get)
    assert lit.main() == 0
    assert TOKEN not in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# AuthTally, directly
# --------------------------------------------------------------------------- #
def _http(status: int, body: str) -> common.HttpError:
    return common.HttpError(status, f"{BASE}/dockets/", body)


def test_authtally_is_quiet_with_no_refusals():
    t = lit.AuthTally()
    assert t.verdict((TOKEN,)) is None
    t.ok = 5
    assert t.verdict((TOKEN,)) is None


def test_authtally_any_401_is_a_credential_failure_even_among_ok_replies():
    """An anonymous or dead token gets 401 (CourtListener v4.3), so a single 401 is the
    token whatever else answered. The FIRST 401's body is the one quoted."""
    t = lit.AuthTally()
    t.ok = 10
    t.failed(_http(401, BODY_401))
    t.failed(_http(401, '{"detail":"a later body"}'))
    assert t.verdict((TOKEN,)) == f"HTTP 401 {QUOTED_401}"


def test_authtally_a_401_outranks_a_run_of_403s():
    t = lit.AuthTally()
    t.failed(_http(403, BODY_403))
    t.failed(_http(401, BODY_401))
    t.failed(_http(403, BODY_403))
    assert t.verdict((TOKEN,)) == f"HTTP 401 {QUOTED_401}"


def test_authtally_403_is_a_credential_failure_only_when_nothing_answered():
    t = lit.AuthTally()
    for body in (BODY_403, '{"detail":"second"}', '{"detail":"third"}'):
        t.failed(_http(403, body))
    assert t.verdict((TOKEN,)) == f"every request refused, HTTP 403 x3 {QUOTED_403}"
    t.ok = 1                                               # one reply answered OK
    assert t.verdict((TOKEN,)) is None


def test_authtally_ignores_every_failure_that_is_not_a_401_or_403():
    """Transport give-ups, rate budgets, 404s and 5xx are per-item failures with their
    own handling; none of them says anything about the token."""
    t = lit.AuthTally()
    for exc in (RuntimeError("GET failed after 4 attempts"),
                common.RetriesExhausted("GET failed after 4 attempts", 503, "busy"),
                common.RateBudgetExhausted(46),
                _http(404, '{"detail":"Not found."}'),
                _http(500, "oops")):
        t.failed(exc)
    assert (t.first_401, t.n_403, t.first_403) == (None, 0, None)
    assert t.verdict((TOKEN,)) is None


def test_authtally_verdict_scrubs_collapses_and_truncates_the_body():
    """The quoted body passes run_signals.scrub: the token replaced wherever it
    occurs, whitespace collapsed, and the evidence held to EVIDENCE_MAX."""
    t = lit.AuthTally()
    t.failed(_http(401, f"token {TOKEN}\n\n  was   {TOKEN} " + "x" * 1000))
    v = t.verdict((TOKEN,))
    assert TOKEN not in v
    assert v.startswith('HTTP 401 "token [redacted] was [redacted] xxx')
    inner = v[len("HTTP 401 \""):-1]
    assert len(inner) == run_signals.EVIDENCE_MAX and inner.endswith("...")
