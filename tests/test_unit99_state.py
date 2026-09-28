"""Suite for unit 99 on the state channel: the loud lines and the channel_runs rows.

What is pinned here (Corey's rulings, 2026-09-28):
  - names_the_key / credential_signal_text: a reply is a key refusal only when it names
    the key, and an allowance body is never read as one (the cap is checked first);
  - R4: a reply naming the key stops the run -- no getMasterList, getBill or further
    session call after it -- and main() prints ONE `CREDENTIAL FAILURE state: "..."` line
    quoting the alert, exits 0 and writes the row;
  - R3: a run that made requests and got no OK reply at all prints `NO OK REPLIES state`,
    quoting the first failure, and is NOT labelled a credential failure unless the reply
    named the key; a transport outage lands here too;
  - R6: an allowance body cuts the run short (never a credential line); a getBill budget
    of 0 prints a DEFERRED line with the count and stores no hash;
  - R7: a clean run writes an `ok` row, state's receipt;
  - R5: a missing key on the state slot prints the line and writes the row, while a
    non-state slot never reads the key and writes nothing;
  - the fixture key never reaches a signal line or a row, even when an alert echoes it.

Offline, like tests/test_state_sessions.py: temp SQLite, `common.http_get` faked,
`state._now` pinned, `config.load_env` / `db.connect` patched so nothing reaches Turso or
reads `.env`. The key is an obvious fixture value, never a real one. The fake serves
ARBITRARY state ids (100 + index).

Run:  pytest tests/test_unit99_state.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

import common  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import run_signals  # noqa: E402
from collectors import state  # noqa: E402

FIXTURES = Path(REPO) / "tests" / "fixtures"
MASTERLIST = json.loads((FIXTURES / "legiscan_masterlist.json").read_text(encoding="utf-8"))
GETBILL = json.loads((FIXTURES / "legiscan_getbill.json").read_text(encoding="utf-8"))
BASE = "https://api.legiscan.com/"
WATCHED = ["TX", "GA", "FL", "AZ", "WI", "PA", "MI", "NC", "OH"]   # config order
FAKE_ID = {st: 100 + i for i, st in enumerate(WATCHED)}
FIXTURE_KEY = "FIXTUREKEY-0123456789abcdef"
KEY_ENV = "LEGISCAN_API_KEY"
RUN_ID = "990001"
FRI = datetime(2026, 10, 16, 10, 30, tzinfo=timezone.utc)   # previous ET day Thu: poll

SIGNAL_PREFIXES = ("CREDENTIAL FAILURE", "NO OK REPLIES", "RUN CUT SHORT", "DEFERRED")
KEY_ALERT = {"status": "ERROR", "alert": {"message": "Invalid API key"}}


# --- fakes (the shapes tests/test_state_sessions.py uses) ----------------------------

def _session(st, sid, *, sine_die=0, prior=0):
    return {"session_id": sid, "state_id": FAKE_ID[st], "year_start": 2026, "year_end": 2026,
            "prefile": 0, "sine_die": sine_die, "prior": prior, "special": 0,
            "session_name": f"{st} {sid}", "dataset_hash": f"h-{st}-{sid}"}


def default_sessions():
    """One active regular session (9000 + i) and one prior session per watched state."""
    return {st: [_session(st, 9000 + i), _session(st, 8000 + i, sine_die=1, prior=1)]
            for i, st in enumerate(WATCHED)}


def _ml(st):
    """The fixture master list re-labelled as `st`'s, so the URL tripwire passes."""
    m = json.loads(json.dumps(MASTERLIST))
    for k, v in m["masterlist"].items():
        if k == "session":
            v["state_id"] = FAKE_ID[st]
        elif isinstance(v, dict):
            v["url"] = v["url"].replace("/TX/", f"/{st}/")
    return m


def _empty(st):
    return {"status": "OK", "masterlist": {"session": {"state_id": FAKE_ID[st]}}}


class Fake:
    """A LegiScan that knows sessions. `route(op, arg, params)` may return a payload or
    an exception for any call; returning None falls through to the healthy default."""

    def __init__(self, route=None, masterlists=None):
        self.sessions = default_sessions()
        self.route = route
        self.masterlists = masterlists or {}
        self.calls = []

    def state_of(self, sid):
        for st, rows in self.sessions.items():
            if any(r["session_id"] == sid for r in rows):
                return st
        raise AssertionError(f"unknown session {sid}")

    def __call__(self, url, params=None, headers=None, timeout=common.DEFAULT_TIMEOUT,
                 throttle=0.0, on_attempt=None):
        if on_attempt is not None:
            on_attempt()
        op = params["op"]
        arg = params.get("state") or params.get("id")
        self.calls.append((op, arg))
        if self.route is not None:
            r = self.route(op, arg, params)
            if isinstance(r, BaseException):
                raise r
            if r is not None:
                return r
        if op == "getSessionList":
            rows = self.sessions.get(arg, []) if arg else \
                [r for rows in self.sessions.values() for r in rows]
            return {"status": "OK", "sessions": rows}
        if op == "getMasterList":
            if "id" in params:
                return self.masterlists.get(arg) or _ml(self.state_of(arg))
            return _ml(arg)
        if op == "getBill":
            return GETBILL
        raise AssertionError(op)

    def ops(self, op):
        return [a for o, a in self.calls if o == op]


class _NoClose:
    def __init__(self, raw):
        self._raw = raw

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._raw, name)


# Bound at import, before any fixture patches db.init_db/db.connect (the trap
# tests/test_state_sessions.py records).
_REAL_INIT, _REAL_CONNECT = db.init_db, db.connect


def _conn():
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    _REAL_INIT(path)
    conn = _REAL_CONNECT(path)
    state.register_source(conn, BASE, "B", "2")
    conn.commit()
    return conn


def _seed_sessions(conn):
    """Store every watched state's sessions as a previous run would have, so main()
    skips the bootstrap and the national getSessionList is its first call."""
    for st, rows in default_sessions().items():
        for s in rows:
            state.upsert_session(conn, st, s, "2026-10-01T00:00:00+00:00")
    conn.commit()


@pytest.fixture
def run(monkeypatch, capsys):
    """run(fake, slot=None, key=FIXTURE_KEY, seeded=True) -> (rc, stdout, stderr):
    state.main() on a temp DB that persists across calls in the test. key=None makes
    the key's variable read as unset; run.asked records every secret name read."""
    raw = _conn()
    asked = []
    holder = {"key": FIXTURE_KEY}

    def require_env(name):
        asked.append(name)
        if name == KEY_ENV and holder["key"]:
            return holder["key"]
        raise SystemExit(f"Missing required environment variable {name}.")

    monkeypatch.setattr(config, "load_env", lambda *a, **k: None)
    monkeypatch.setattr(config, "require_env", require_env)
    monkeypatch.setattr(db, "init_db", lambda *a, **k: None)
    monkeypatch.setattr(db, "connect", lambda *a, **k: _NoClose(raw))
    monkeypatch.setattr(state, "_now", lambda: FRI)
    monkeypatch.setenv("GITHUB_RUN_ID", RUN_ID)

    def go(fake, slot=None, key=FIXTURE_KEY, seeded=True):
        if seeded and not raw.execute("SELECT COUNT(*) FROM state_sessions").fetchone()[0]:
            _seed_sessions(raw)
        holder["key"] = key
        monkeypatch.setattr(common, "http_get", fake)
        if slot is None:
            monkeypatch.delenv("SLOT", raising=False)
        else:
            monkeypatch.setenv("SLOT", slot)
        rc = state.main()
        out = capsys.readouterr()
        return rc, out.out, out.err
    go.conn = raw
    go.asked = asked
    return go


def _signals(out):
    """The run_signals lines: literal prefixes at column 0."""
    return [line for line in out.splitlines() if line.startswith(SIGNAL_PREFIXES)]


def _rows(conn):
    """{class: evidence} for state's channel_runs rows, asserting run id and channel."""
    rows = conn.execute("SELECT run_id, channel, class, evidence, written_at "
                        "FROM channel_runs").fetchall()
    for r in rows:
        assert (r["run_id"], r["channel"]) == (RUN_ID, "state")
        assert r["written_at"]
    return {r["class"]: r["evidence"] for r in rows}


# --- (1) the predicates ----------------------------------------------------------------

@pytest.mark.parametrize("text, names", [
    ("Invalid API key", True),
    ("API key disabled", True),
    ("api KEY has been SUSPENDED", True),                       # casefolded
    ("Temporary failure", False),
    ("Monthly query limit reached", False),                     # an allowance alert
    ("Monthly query limit reached for this API key", False),    # names the key, refuses nothing
    ("Invalid month parameter", False),                         # a refusal word, no key
    ('<meta name="keywords"> Not found: the page is missing', False),  # `key` in a word
    ("monkey business: invalid request", False),
    ("Missing apikey", True),
    ("", False),
    (None, False),
])
def test_names_the_key(text, names):
    assert state.names_the_key(text) is names


@pytest.mark.parametrize("message, quoted", [
    ("Invalid API key", "Invalid API key"),
    ("API key disabled", "API key disabled"),
    ("Temporary failure", None),
    ("Monthly query limit reached", None),
])
def test_credential_signal_text_on_an_error_alert(message, quoted):
    exc = state.LegiScanError("getSessionList", {"status": "ERROR", "alert": {"message": message}})
    assert state.credential_signal_text(exc) == quoted


def test_credential_signal_text_on_a_string_alert():
    exc = state.LegiScanError("getBill", {"status": "ERROR", "alert": "API key disabled"})
    assert state.credential_signal_text(exc) == "API key disabled"


def test_credential_signal_text_reads_a_4xx_body_only():
    assert state.credential_signal_text(common.HttpError(401, BASE, "Invalid API key")) \
        == "Invalid API key"
    assert state.credential_signal_text(common.HttpError(403, BASE, "Forbidden")) is None
    # Not a 4xx: a 5xx or an exhausted retry ladder is an outage, whatever its body says.
    assert state.credential_signal_text(common.HttpError(500, BASE, "Invalid API key")) is None
    assert state.credential_signal_text(
        common.RetriesExhausted("GET failed after 4 attempts: x", 503, "Invalid API key")) is None
    assert state.credential_signal_text(RuntimeError("Invalid API key")) is None


def test_stop_on_reads_the_cap_before_the_key():
    """A body naming both the allowance and a key refusal is a cap signal, not a
    credential failure: the cap's handling predates unit 99 and is checked first."""
    both = state.LegiScanError("getBill", {"status": "ERROR", "alert": {
        "message": "API key suspended: monthly query limit reached"}})
    meter = state.UsageMeter()
    assert state.stop_on(meter, both) is True
    assert meter.cap_signal == both.body and meter.credential_signal is None
    assert meter.stopped()

    meter = state.UsageMeter()
    assert state.stop_on(meter, state.LegiScanError("getBill", KEY_ALERT)) is True
    assert (meter.cap_signal, meter.credential_signal) == (None, "Invalid API key")
    assert meter.stopped()

    meter = state.UsageMeter()
    assert state.stop_on(meter, state.LegiScanError("getBill", {
        "status": "ERROR", "alert": {"message": "Temporary failure"}})) is False
    assert not meter.stopped()


# --- (2) R4: a key refusal stops the run ------------------------------------------------

def test_a_national_key_refusal_stops_the_run_and_prints_one_credential_line(run):
    fake = Fake(route=lambda op, arg, p: KEY_ALERT if op == "getSessionList" and arg is None
                else None)
    rc, out, err = run(fake)
    assert rc == 0
    assert fake.calls == [("getSessionList", None)]            # nothing after the refusal
    assert fake.ops("getMasterList") == [] and fake.ops("getBill") == []
    assert _signals(out) == ['CREDENTIAL FAILURE state: "Invalid API key"']
    assert _rows(run.conn) == {"credential failure": '"Invalid API key"'}   # no ok, no no-OK
    assert "national getSessionList ERROR" not in err          # stopped, not a skip


@pytest.mark.parametrize("where, expected_calls", [
    # A fresh DB: the bootstrap's first getSessionList&state= is refused.
    ("bootstrap", [("getSessionList", "TX")]),
    # Sessions stored: the first master list is refused.
    ("masterlist", [("getSessionList", None), ("getMasterList", 9000)]),
    # The first getBill is refused: not the second bill, not GA's master list.
    ("getbill", [("getSessionList", None), ("getMasterList", 9000), ("getBill", 1700001)]),
])
def test_no_fan_out_after_a_key_refusal_anywhere(run, where, expected_calls):
    def route(op, arg, p):
        if where == "bootstrap" and op == "getSessionList" and arg:
            return KEY_ALERT
        if where == "masterlist" and op == "getMasterList":
            return KEY_ALERT
        if where == "getbill" and op == "getBill":
            return KEY_ALERT
        return None
    fake = Fake(route=route)
    rc, out, err = run(fake, seeded=where != "bootstrap")
    assert rc == 0
    assert fake.calls == expected_calls
    assert _signals(out) == ['CREDENTIAL FAILURE state: "Invalid API key"']
    assert _rows(run.conn)["credential failure"] == '"Invalid API key"'
    if where != "bootstrap":
        assert (f"  {'GA/9001':<10} skipped: LegiScan refused the key earlier in this run; "
                f"no request made") in out
    if where == "getbill":
        assert state.seen_hash(run.conn, 1700001) is None


# --- (3) R3: no OK reply, and no reply naming the key -----------------------------------

def test_every_reply_an_error_not_naming_the_key_is_no_ok_replies(run):
    def route(op, arg, p):
        if op == "getSessionList":
            return {"status": "ERROR", "alert": {"message": "Service temporarily unavailable"}}
        if op == "getMasterList":
            return {"status": "ERROR", "alert": {"message": "Unknown session id"}}
        return None
    fake = Fake(route=route)
    rc, out, err = run(fake)
    assert rc == 0
    # Not a stop: every planned master list was still tried (R4 is for the key only).
    assert fake.ops("getMasterList") == [9000 + i for i in range(9)]
    assert _signals(out) == ['NO OK REPLIES state: "Service temporarily unavailable"']
    assert "CREDENTIAL FAILURE" not in out + err
    assert _rows(run.conn) == {"no OK replies": '"Service temporarily unavailable"'}


def test_one_ok_reply_is_enough_to_not_be_no_ok_replies(run):
    fake = Fake(route=lambda op, arg, p: {"status": "ERROR", "alert": {
        "message": "Unknown session id"}} if op == "getMasterList" else None)
    rc, out, _ = run(fake)
    assert rc == 0
    assert _signals(out) == []                                  # the national call was OK
    assert _rows(run.conn) == {"ok": "1 OK reply"}


# --- (4) a transport outage -------------------------------------------------------------

@pytest.mark.parametrize("status, body, first", [
    (None, "", "no response after every retry (transport)"),
    (503, "Service Unavailable", "HTTP 503 Service Unavailable"),
])
def test_an_outage_is_no_ok_replies_not_a_credential_failure(run, status, body, first):
    fake = Fake(route=lambda op, arg, p: common.RetriesExhausted(
        "GET failed after 4 attempts: x", status, body))
    rc, out, err = run(fake)
    assert rc == 0
    assert fake.calls == [("getSessionList", None)]             # the outage stop, as before
    assert "LegiScan is not answering the session calls" in out
    assert _signals(out) == [f'NO OK REPLIES state: "{first}"']
    assert _rows(run.conn) == {"no OK replies": f'"{first}"'}


# --- (5) the allowance: cut short, never credential -------------------------------------

def test_a_cap_body_that_also_names_the_key_is_cut_short_not_credential(run):
    cap = {"status": "ERROR", "alert": {"message": "API key suspended: monthly query limit reached"}}
    fake = Fake(route=lambda op, arg, p: cap if op == "getMasterList" else None)
    rc, out, err = run(fake)
    assert rc == 0
    assert fake.ops("getMasterList") == [9000]                  # the cap stops the run
    lines = _signals(out)
    assert len(lines) == 1
    assert lines[0] == ("RUN CUT SHORT state: LegiScan signalled its allowance is spent; "
                        "remaining sessions skipped (its body is printed verbatim above)")
    # The body itself: printed ONCE, verbatim (A4), by main(), not repeated in the line.
    assert out.count("API key suspended: monthly query limit reached") == 1
    assert "CREDENTIAL FAILURE" not in out + err
    rows = _rows(run.conn)
    assert set(rows) == {"cut short", "ok"}                      # the national call was OK
    assert rows["cut short"] == lines[0][len("RUN CUT SHORT state: "):]


def test_an_allowance_signal_as_the_first_reply_is_one_class_printed_once(run):
    """The review's case: the allowance body answers the national call, so the run has
    no OK reply at all. It is the cut-short and nothing else -- not also NO OK REPLIES
    re-quoting the body the cap print already printed verbatim (A4)."""
    body = "Rate limit exceeded: 10000/month."
    fake = Fake(route=lambda op, arg, p: common.RateBudgetExhausted(None, body)
                if op == "getSessionList" else None)
    rc, out, err = run(fake)
    assert rc == 0
    assert fake.calls == [("getSessionList", None)]
    assert _signals(out) == [
        "RUN CUT SHORT state: LegiScan signalled its allowance is spent; remaining "
        "sessions skipped (its body is printed verbatim above)"]
    assert out.count(body) == 1
    assert set(_rows(run.conn)) == {"cut short"}


@pytest.mark.parametrize("status", [401, 403])
def test_a_bare_refusal_of_the_first_call_stops_the_run_without_the_credential_label(
        run, status):
    """R4's purpose is no fan-out on a dead key, and a dead key refuses the first call;
    R3 keeps the credential label for a reply that names the key. So a bare 401/403
    before any OK reply stops the run and is quoted as NO OK REPLIES. The review's probe
    of this shape fanned out to all nine master lists."""
    fake = Fake(route=lambda op, arg, p: common.HttpError(status, BASE, "Forbidden")
                if op == "getSessionList" else None)
    rc, out, err = run(fake)
    assert rc == 0
    assert fake.calls == [("getSessionList", None)]
    assert fake.ops("getMasterList") == []
    assert _signals(out) == [f'NO OK REPLIES state: "HTTP {status} Forbidden"']
    assert "CREDENTIAL FAILURE" not in out + err
    assert _rows(run.conn) == {"no OK replies": f'"HTTP {status} Forbidden"'}


def test_a_403_after_an_ok_reply_stays_per_item(run):
    """cap_signal_body's design: after the key has worked this run, a 403 is about the
    item. Stopping there would let one bill's standing 403 end every state run."""
    fake = Fake(route=lambda op, arg, p: common.HttpError(403, BASE, "Forbidden")
                if op == "getMasterList" and arg == 9000 else None)
    rc, out, err = run(fake)
    assert rc == 0
    assert fake.ops("getMasterList") == [9000 + i for i in range(9)]
    assert _signals(out) == []
    assert "ok" in _rows(run.conn)


# --- (6) R6: the getBill budget's deferral ------------------------------------------------

def test_a_getbill_budget_of_0_prints_deferred_with_the_count_and_stores_no_hash(
        run, monkeypatch):
    real_load = config.load_sources

    def load():
        src = real_load()
        src["state"]["max_getbill_per_run"] = 0
        return src
    monkeypatch.setattr(config, "load_sources", load)
    # Only TX serves bills: its two election bills are changed, and the budget is 0.
    masterlists = {9000 + i: _empty(st) for i, st in enumerate(WATCHED) if st != "TX"}
    fake = Fake(masterlists=masterlists)
    rc, out, _ = run(fake)
    assert rc == 0
    assert "getBill budget 0" in out
    assert fake.ops("getBill") == []
    assert _signals(out) == ["DEFERRED state: 2 changed bill(s) deferred, getBill budget "
                             "spent; they resume next state run"]
    assert "2 deferred (getBill budget spent)" in out
    for bill_id in (1700001, 1700002):
        assert state.seen_hash(run.conn, bill_id) is None       # resumes next run
    rows = _rows(run.conn)
    assert set(rows) == {"deferred", "ok"}                       # quiet, and reached
    assert rows["deferred"].startswith("2 changed bill(s) deferred")
    assert not set(rows) & run_signals.LOUD


# --- (7) R7: the receipt ----------------------------------------------------------------

def test_a_clean_run_writes_only_an_ok_row(run):
    fake = Fake()
    rc, out, err = run(fake, seeded=False)
    assert rc == 0
    # 9 bootstrap + 1 national + 9 master lists + 2 getBills, every one OK.
    assert len(fake.calls) == 21
    assert _signals(out) == []
    assert _rows(run.conn) == {"ok": "21 OK replies"}


# --- (8) R5: a missing key, and the slot gate first ------------------------------------

@pytest.mark.parametrize("slot", ["17 6 * * *", "dispatch", None])
def test_a_missing_key_on_a_state_run_prints_the_line_and_writes_the_row(run, slot):
    fake = Fake()
    rc, out, err = run(fake, slot=slot, key=None)
    assert rc == 0
    assert fake.calls == []                                     # no LegiScan call at all
    assert KEY_ENV in run.asked
    assert _signals(out) == [f"CREDENTIAL FAILURE state: {KEY_ENV} is not set"]
    assert _rows(run.conn) == {"missing secret": f"{KEY_ENV} is not set"}
    assert run.conn.execute("SELECT COUNT(*) FROM legiscan_usage").fetchone()[0] == 0


@pytest.mark.parametrize("slot", ["17 0 * * *", "17 12 * * *", "17 18 * * *"])
@pytest.mark.parametrize("key", [None, FIXTURE_KEY])
def test_a_non_state_slot_never_reads_the_key_and_writes_no_row(run, slot, key):
    fake = Fake()
    rc, out, err = run(fake, slot=slot, key=key)
    assert rc == 0
    assert run.asked == []                                      # the gate returns first
    assert fake.calls == []
    assert f"state: not this slot ({slot})" in out
    assert _signals(out) == []
    assert run.conn.execute("SELECT COUNT(*) FROM channel_runs").fetchone()[0] == 0


# --- (9) the key never reaches the output ------------------------------------------------

def _echoing(message_fmt):
    """An ERROR reply whose alert echoes the key the request carried."""
    return {"status": "ERROR", "alert": {"message": message_fmt}}


def test_an_alert_echoing_the_key_is_redacted_on_the_credential_path(run):
    def route(op, arg, p):
        if op == "getSessionList" and arg is None:
            return _echoing(f"Invalid API key {p['key']}")
        return None
    fake = Fake(route=route)
    rc, out, err = run(fake)
    assert rc == 0
    assert FIXTURE_KEY not in out and FIXTURE_KEY not in err
    assert _signals(out) == ['CREDENTIAL FAILURE state: "Invalid API key [redacted]"']
    rows = _rows(run.conn)
    assert rows == {"credential failure": '"Invalid API key [redacted]"'}
    assert all(FIXTURE_KEY not in ev for ev in rows.values())


def test_an_echoed_key_is_redacted_from_the_no_ok_line_and_row(run):
    def route(op, arg, p):
        if op in ("getSessionList", "getMasterList"):
            return _echoing(f"Temporary failure for request key={p['key']}")
        return None
    rc, out, err = run(Fake(route=route))
    assert rc == 0
    lines = _signals(out)
    assert lines == ['NO OK REPLIES state: "Temporary failure for request key=[redacted]"']
    assert FIXTURE_KEY not in "\n".join(lines)
    rows = _rows(run.conn)
    assert rows == {"no OK replies": '"Temporary failure for request key=[redacted]"'}
    assert all(FIXTURE_KEY not in ev for ev in rows.values())


def test_an_echoed_key_is_redacted_from_the_cut_short_line_and_row(run):
    def route(op, arg, p):
        if op == "getMasterList":
            return _echoing(f"Monthly query limit reached for {p['key']}")
        return None
    rc, out, err = run(Fake(route=route))
    assert rc == 0
    lines = _signals(out)
    assert len(lines) == 1 and lines[0].startswith("RUN CUT SHORT state: ")
    assert FIXTURE_KEY not in lines[0]
    # The verbatim body print carries the echoed key, and safe() redacts it there.
    assert "Monthly query limit reached for [redacted]" in out
    assert FIXTURE_KEY not in out + err
    rows = _rows(run.conn)
    assert all(FIXTURE_KEY not in ev for ev in rows.values())


@pytest.mark.parametrize("where", [
    "getbill-credential",
    "bootstrap",
    "national",
    "masterlist",
    "masterlist-credential",
    "cap",
])
def test_an_echoed_key_never_appears_anywhere_in_the_output(run, where):
    """The whole of stdout and stderr, not only the signal lines."""
    def route(op, arg, p):
        if where == "getbill-credential" and op == "getBill":
            return _echoing(f"Invalid API key {p['key']}")
        if where == "bootstrap" and op == "getSessionList" and arg:
            return _echoing(f"Temporary failure for request key={p['key']}")
        if where == "national" and op == "getSessionList" and arg is None:
            return _echoing(f"Temporary failure for request key={p['key']}")
        if where == "masterlist" and op == "getMasterList":
            return _echoing(f"Unknown session id for key={p['key']}")
        if where == "masterlist-credential" and op == "getMasterList":
            return _echoing(f"Invalid API key {p['key']}")
        if where == "cap" and op == "getMasterList":
            return _echoing(f"Monthly query limit reached for {p['key']}")
        return None
    rc, out, err = run(Fake(route=route), seeded=where != "bootstrap")
    assert rc == 0
    assert FIXTURE_KEY not in out and FIXTURE_KEY not in err


# --- ruling 1b: which state runs write `deferred` with no `ok` ---------------------------
# The verdict excuses a slot by the `deferred` class (collect_verdict.STATE_EXCUSED_CLASS)
# only when the run that wrote it was not loud. These two drive the real main() to pin
# the two runs that write `deferred` with no `ok`: the ceiling pre-check, quiet and
# excused; and a deferral after a FAILED national call, loud and not excused (the review
# of the second rulings found the second; the first build's comment said it could not
# happen).

from tools import collect_verdict as cv  # noqa: E402

NATIONAL_ERROR = {"status": "ERROR", "alert": {"message": "Service temporarily unavailable"}}


def _seed_ledger(conn, used):
    conn.execute("INSERT INTO legiscan_usage (month, queries, updated_at) VALUES (?, ?, ?)",
                 (state.ledger_month(FRI), used, "2026-10-16T00:00:00+00:00"))
    conn.commit()


def _in_fridays_slot(conn):
    """written_at is the wall clock; place this run's rows where a late 06:17Z run on FRI
    would land, and return that slot."""
    conn.execute("UPDATE channel_runs SET written_at = '2026-10-16T13:00:00+00:00'")
    conn.commit()
    return datetime(2026, 10, 16, 6, 17, tzinfo=timezone.utc)


def test_the_ceiling_precheck_writes_deferred_alone_and_its_slot_is_excused(run):
    _seed_ledger(run.conn, 8000)                      # config's cron_ceiling
    fake = Fake()
    rc, out, err = run(fake)
    assert rc == 0
    assert fake.calls == []                           # no request made to find out
    assert _rows(run.conn) == {
        "deferred": "monthly ceiling reached (used 8000 of 8000); no request made this run"}
    assert cv.state_slot_excused(run.conn, _in_fridays_slot(run.conn))


def test_a_deferral_after_a_failed_national_call_is_loud_and_excuses_nothing(run):
    _seed_ledger(run.conn, 7998)                      # the pre-check passes, the plan does not
    fake = Fake(route=lambda op, arg, p: NATIONAL_ERROR if op == "getSessionList" else None)
    rc, out, err = run(fake)
    assert rc == 0
    rows = _rows(run.conn)
    assert "ok" not in rows
    assert rows["deferred"].startswith(
        "monthly ceiling reached (used 7998 of 8000) before master lists")
    assert rows["no OK replies"] == '"Service temporarily unavailable"'
    assert not cv.state_slot_excused(run.conn, _in_fridays_slot(run.conn))
