"""Suite for the LegiScan monthly budget (handoff 98, Part A).

What is pinned here: every HTTP attempt reaches the `legiscan_usage` ledger, retries
included, on the state's own commit boundary; the per-run allowance is prorated from
the ledger over the collect.yml slots left in the month; a spent ceiling makes zero
calls and exits 0; a LegiScan cap signal stops the run and prints its body once; and
the tools refuse when their declared worst case does not fit.

Offline and deterministic, like tests/test_state.py: temp SQLite, `common.http_get`
or `common.requests.get` faked, `state._now` pinned so no assertion depends on the
month the suite happens to run in. Every test that drives a `main()` patches
`config.load_env` first -- loading `.env` would put production Turso in this
process's environment, and the tools' `open_ledger` is patched for the same reason.

Run:  pytest tests/test_legiscan_budget.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from requests.structures import CaseInsensitiveDict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

import common  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
from collectors import state  # noqa: E402
from tools import masterlist_corpus, sasts_dump  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "backfill_state_bills", os.path.join(REPO, "scripts", "backfill_state_bills.py"))
backfill = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backfill)

FIXTURES = Path(REPO) / "tests" / "fixtures"
BASE = "https://api.legiscan.com/"
KEY = "test-key"
TERMS = ["voter registration", "voter roll", "proof of citizenship", "mail ballot"]
GRADE = ("B", "2")
MASTERLIST = json.loads((FIXTURES / "legiscan_masterlist.json").read_text(encoding="utf-8"))
GETBILL = json.loads((FIXTURES / "legiscan_getbill.json").read_text(encoding="utf-8"))

OCT_START = datetime(2026, 10, 1, 0, 20, tzinfo=timezone.utc)
MID_OCT = datetime(2026, 10, 16, 13, 0, tzinfo=timezone.utc)


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


@pytest.fixture
def clock(monkeypatch):
    """Pin state._now; returns a setter so a test can move time mid-run."""
    now = {"t": MID_OCT}
    monkeypatch.setattr(state, "_now", lambda: now["t"])

    def set_(t):
        now["t"] = t
    set_(MID_OCT)
    return set_


def _conn():
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    db.init_db(path)
    conn = db.connect(path)
    state.register_source(conn, BASE, "B", "2")
    conn.commit()
    return conn


def _ledger(conn):
    return {r["month"]: r["queries"] for r in
            conn.execute("SELECT month, queries FROM legiscan_usage").fetchall()}


def _seed(conn, month, n):
    db.increment(conn, "legiscan_usage", "month", month, {"queries": n},
                 {"updated_at": "2026-10-01T00:00:00+00:00"})
    conn.commit()


class _Resp:
    """requests.Response stand-in for common._get (same shape as test_common's)."""
    def __init__(self, status_code, body=None, text=""):
        self.status_code = status_code
        self.headers = CaseInsensitiveDict({})
        self._body = body
        self.text = text or (json.dumps(body) if body is not None else "")

    def json(self):
        return self._body


def _requests_seq(monkeypatch, responses):
    """Fake requests.get under the REAL common._get, so attempts are counted by the
    real retry loop rather than by a fake that claims to count them."""
    it = iter(responses)
    calls = []

    def fake(url, params=None, headers=None, timeout=None):
        calls.append(params.get("op"))
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(common.requests, "get", fake)
    monkeypatch.setattr(common.time, "sleep", lambda *a, **k: None)
    return calls


def _fake_http(calls, masterlist=None, getbill=None, by_state=None):
    """A common.http_get fake that honours on_attempt as the real one does."""
    def fake(url, params=None, headers=None, timeout=common.DEFAULT_TIMEOUT, throttle=0.0,
             on_attempt=None):
        if on_attempt is not None:
            on_attempt()
        calls.append((params["op"], params.get("state") or params.get("id")))
        if by_state is not None and params["op"] == "getMasterList":
            return by_state(params["state"])
        if params["op"] == "getMasterList":
            return MASTERLIST if masterlist is None else masterlist
        return GETBILL if getbill is None else getbill(params["id"])
    return fake


# --- the ledger counts attempts ------------------------------------------------

def test_a_503_503_200_masterlist_records_three(monkeypatch, clock):
    """The acceptance case from the handoff: two retries and a success are THREE
    queries upstream, and the ledger says three -- through the real retry loop."""
    conn = _conn()
    _requests_seq(monkeypatch, [_Resp(503), _Resp(503), _Resp(200, body={
        "status": "OK", "masterlist": {"session": {}}})])
    meter = state.UsageMeter()
    state.collect(conn, BASE, KEY, ["TX"], TERMS, GRADE, budget=500, throttle=0.0,
                  meter=meter)
    assert _ledger(conn) == {"2026-10": 3}
    assert meter.run_total == 3 and meter.pending == {}


def test_transport_failures_are_attempts_too(monkeypatch, clock):
    """A timeout never produced a status, but LegiScan may still have counted the
    request, and the 08-28..09-07 exhaustion runs were exactly this shape."""
    import requests
    conn = _conn()
    _requests_seq(monkeypatch, [requests.Timeout("t")] * 4)
    r = state.collect(conn, BASE, KEY, ["TX"], TERMS, GRADE, budget=500, throttle=0.0)
    assert r["TX"]["error_msg"].startswith("GET failed after 4 attempts")
    assert _ledger(conn) == {"2026-10": 4}


def test_all_nine_masterlists_failing_still_reaches_the_ledger(monkeypatch, clock):
    """No state commits in this run, so no per-state commit can carry the count --
    and it is the run that spends the most (36 attempts on 2026-08-28). The final
    flush is what records it."""
    import requests
    conn = _conn()
    states = ["TX", "GA", "FL", "AZ", "WI", "PA", "MI", "NC", "OH"]
    _requests_seq(monkeypatch, [requests.ConnectionError("x")] * 36)
    r = state.collect(conn, BASE, KEY, states, TERMS, GRADE, budget=500, throttle=0.0)
    assert all(r[s]["error_msg"] for s in states)
    assert _ledger(conn) == {"2026-10": 36}


def test_the_ledger_rides_the_state_commit_not_its_own(monkeypatch, clock):
    """Same boundary as the data: one commit per state, and no extra commit for the
    ledger when every state committed."""
    raw = _conn()
    commits = []

    class Counting:
        def commit(self):
            commits.append(1)
            return raw.commit()

        def __getattr__(self, name):
            return getattr(raw, name)

    calls = []
    monkeypatch.setattr(common, "http_get", _fake_http(calls))
    state.collect(Counting(), BASE, KEY, ["TX"], TERMS, GRADE, budget=500, throttle=0.0)
    assert len(commits) == 1
    raw.rollback()                               # the count must already be durable
    assert _ledger(raw) == {"2026-10": len(calls)} == {"2026-10": 3}


def test_a_discarded_state_keeps_its_spend_pending_for_the_next_commit(monkeypatch, clock):
    """The data of a discarded state is re-derived by the change-hash gate; its
    queries are not re-derivable by anything. They ride the next state's commit."""
    conn = _conn()
    real = state.upsert_state_bill
    monkeypatch.setattr(state, "upsert_state_bill",
                        lambda c, b, r, st: (_ for _ in ()).throw(RuntimeError("dead stream"))
                        if st == "GA" else real(c, b, r, st))
    offsets = {"TX": 0, "GA": 100, "FL": 200}

    def ml(st):
        m = json.loads(json.dumps(MASTERLIST))
        for k, v in m["masterlist"].items():
            if k != "session":
                v["bill_id"] += offsets[st]
        return m
    calls = []
    monkeypatch.setattr(common, "http_get", _fake_http(calls, by_state=ml))
    r = state.collect(conn, BASE, KEY, ["TX", "GA", "FL"], TERMS, GRADE, budget=500,
                      throttle=0.0)
    conn.rollback()
    assert r["GA"]["error_msg"].startswith("batch discarded")
    # TX 3 + GA 2 (the write fails on its first bill, so its second is never
    # fetched) + FL 3: every call made, including the discarded state's.
    assert _ledger(conn) == {"2026-10": len(calls)} == {"2026-10": 8}


def test_a_discarded_LAST_state_is_caught_by_the_final_flush(monkeypatch, clock):
    conn = _conn()
    monkeypatch.setattr(state, "upsert_state_bill",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("dead stream")))
    calls = []
    monkeypatch.setattr(common, "http_get", _fake_http(calls))
    state.collect(conn, BASE, KEY, ["TX"], TERMS, GRADE, budget=500, throttle=0.0)
    conn.rollback()
    assert _ledger(conn) == {"2026-10": len(calls)} == {"2026-10": 2}   # masterlist + 1 getBill


def test_a_run_straddling_the_month_books_each_attempt_to_its_month(monkeypatch, clock):
    conn = _conn()
    clock(utc(2026, 9, 30, 23, 59))
    seen = []

    def fake(url, params=None, headers=None, timeout=None, throttle=0.0, on_attempt=None):
        on_attempt()
        seen.append(params["state"])
        if len(seen) == 2:
            clock(utc(2026, 10, 1, 0, 0, 1))     # midnight passes between states
        return {"status": "OK", "masterlist": {}}
    monkeypatch.setattr(common, "http_get", fake)
    state.collect(conn, BASE, KEY, ["TX", "GA", "FL"], TERMS, GRADE, budget=500,
                  throttle=0.0)
    assert _ledger(conn) == {"2026-09": 2, "2026-10": 1}


def test_increment_accumulates_across_writers():
    """The cron and a tool both write the month's row; the second must add, not
    replace. This is why db.increment exists instead of db.upsert."""
    conn = _conn()
    _seed(conn, "2026-10", 40)
    _seed(conn, "2026-10", 2)
    assert _ledger(conn) == {"2026-10": 42}


# --- proration ------------------------------------------------------------------

# DAILY STATE SLOTS since handoff 98b: only the 06:17Z slot runs the channel, so
# runs_left is 1 + the 06:17Z slots still to come in the month.
@pytest.mark.parametrize("now, expected", [
    (OCT_START, 32),                           # before Oct 1's 06:17Z: this + 31
    (utc(2026, 10, 1, 3, 0), 32),              # still before it
    (utc(2026, 10, 1, 10, 30), 31),            # Oct 1's own state run, landing ~4h late
    (MID_OCT, 16),                             # 1 + Oct 17..31
    (utc(2026, 10, 31, 5, 0), 2),              # Oct 31's slot still to come
    (utc(2026, 10, 31, 13, 0), 1),             # the month's last state run
    (utc(2026, 11, 1, 0, 20), 31),             # a 30-day month
    (utc(2027, 2, 1, 0, 20), 29),              # February
])
def test_runs_left(now, expected):
    assert state.runs_left(now) == expected


def test_budget_at_month_start():
    b = state.run_budget(0, 8000, 9, 500, OCT_START)
    assert (b.month, b.runs_left, b.allowance, b.getbill, b.skip) == ("2026-10", 32, 250, 241, None)


def test_budget_mid_month():
    b = state.run_budget(4000, 8000, 9, 500, MID_OCT)
    assert (b.runs_left, b.allowance, b.getbill) == (16, 250, 241)


def test_the_session_calls_are_paid_before_getbill():
    """`spent` is what the run paid before its master lists -- the day's
    getSessionList, and once the nine-query bootstrap. It comes out of the share."""
    b = state.run_budget(0, 8000, 9, 500, OCT_START, spent=10)
    assert (b.allowance, b.getbill) == (250, 231)


def test_budget_one_slot_before_rollover_hands_over_everything_left():
    b = state.run_budget(7000, 8000, 9, 500, utc(2026, 10, 31, 19, 0))
    assert (b.runs_left, b.allowance, b.getbill) == (1, 1000, 500)   # max_getbill binds


def test_a_quiet_first_half_rolls_forward():
    """Unspent share is not lost: a month that spent ~10 a day until the 16th hands
    the second half roughly twice the per-run getBill of the first."""
    quiet = state.run_budget(15 * 10, 8000, 9, 500, MID_OCT)
    assert quiet.getbill > 2 * state.run_budget(0, 8000, 9, 500, OCT_START).getbill - 9


def test_storm_is_metered_not_front_loaded():
    """The failure proration exists for: 500 changed bills on the 1st would, under a
    flat cap, spend 509 of the month in one run. Prorated over 32 daily slots, 241."""
    assert state.run_budget(0, 8000, 9, 500, OCT_START).getbill == 241


@pytest.mark.parametrize("used, skip, getbill", [
    (7990, None, 1),            # share 10: nine masterlists and one bill
    (7991, "share", 0),         # share 9: the masterlists alone -- would store nothing
    (7992, "ceiling", 0),       # the ceiling cannot pay for the masterlists at all
    (8000, "ceiling", 0),
    (9500, "ceiling", 0),
])
def test_skip_when_the_run_cannot_buy_a_single_bill(used, skip, getbill):
    b = state.run_budget(used, 8000, 9, 500, utc(2026, 10, 31, 19, 0))
    assert (b.skip, b.getbill) == (skip, getbill)


def test_an_overspent_month_skips_rather_than_spending_masterlists_on_nothing():
    """The review's case: a share too small to buy a single bill at mid-month. The
    handoff's rule alone would run master-list-only runs to the end of the month;
    the amendment skips them, and the share accumulates until a run can afford one."""
    b = state.run_budget(7850, 8000, 9, 500, MID_OCT)
    assert (b.allowance, b.skip, b.getbill) == (9, "share", 0)
    later = state.run_budget(7850, 8000, 9, 500, utc(2026, 10, 25, 13, 0))
    assert later.skip is None and later.getbill > 0


def test_a_share_skip_makes_no_master_list_calls_and_exits_0(monkeypatch, capsys, main_conn, clock):
    """The share is judged AFTER the session calls, since only they say how many
    master lists the run needs: 10 spent on sessions (9 bootstrap + 1 national), then
    a share of 19 cannot buy 9 master lists and one bill, so none is requested."""
    clock(utc(2026, 10, 31, 19, 0))
    _seed(main_conn, "2026-10", 7981)
    calls = []
    monkeypatch.setattr(common, "http_get", _legiscan(calls))
    assert state.main() == 0
    assert {op for op, _ in calls} == {"getSessionList"} and len(calls) == 10
    out = capsys.readouterr().out
    assert ("state: this run's prorated share (19) cannot pay for 9 master list(s) plus one "
            "getBill after 10 spent on sessions (used 7981 of 8000, 1 state slot(s) left), "
            "skipping") in out
    assert _ledger(main_conn) == {"2026-10": 7991}             # the session calls, ledgered


def test_getbill_budget_is_never_negative_and_never_over_the_cap():
    for used in range(0, 10_500, 97):
        for now in (OCT_START, MID_OCT, utc(2026, 10, 31, 19, 0), utc(2026, 10, 1, 0, 5)):
            for max_getbill in (0, 1, 55, 500):
                b = state.run_budget(used, 8000, 9, max_getbill, now)
                assert 0 <= b.getbill <= max_getbill
                assert b.allowance >= 0


# --- main(): ceiling, printing, exit 0 -----------------------------------------

WATCHED = ["TX", "GA", "FL", "AZ", "WI", "PA", "MI", "NC", "OH"]   # config order
# ARBITRARY ids, deliberately NOT LegiScan's alphabetical enumeration: the collector
# must use what the bootstrap measured, so a test that passes here cannot be passing
# because some code path typed the real table in. (The alphabetical prediction lives in
# tests/test_state_sessions.py, against the MEASURED ids.)
FAKE_ID = {st: 100 + i for i, st in enumerate(WATCHED)}
SESSION_STATE = {9000 + i: st for i, st in enumerate(WATCHED)}


def _sessions_for(st):
    """One current regular session and one prior session per watched state."""
    i = WATCHED.index(st)
    return [
        {"session_id": 9000 + i, "state_id": FAKE_ID[st], "year_start": 2026, "year_end": 2026,
         "prefile": 0, "sine_die": 0, "prior": 0, "special": 0,
         "session_name": f"{st} 2026 Regular Session", "dataset_hash": f"h-{st}"},
        {"session_id": 8000 + i, "state_id": FAKE_ID[st], "year_start": 2025, "year_end": 2025,
         "prefile": 0, "sine_die": 1, "prior": 1, "special": 0,
         "session_name": f"{st} 2025 Regular Session", "dataset_hash": f"old-{st}"},
    ]


def _ml_for(st):
    """The fixture master list, re-labelled as `st`'s: its bill URLs and session
    block name `st`, so the tripwire passes. Same bill ids for every state, so the
    change-hash gate makes them new only to the first state polled."""
    m = json.loads(json.dumps(MASTERLIST))
    for k, v in m["masterlist"].items():
        if k == "session":
            v["state_id"] = FAKE_ID[st]
        elif isinstance(v, dict) and v.get("url"):
            v["url"] = v["url"].replace("/TX/", f"/{st}/")
    return m


def _session_payload(st=None, sessions=None):
    sessions = sessions or _sessions_for
    rows = sessions(st) if st else [x for s in WATCHED for x in sessions(s)]
    return {"status": "OK", "sessions": rows}


def _legiscan(calls, masterlist=None, getbill=None, sessions=None):
    """A common.http_get fake that knows every op main() now makes."""
    def fake(url, params=None, headers=None, timeout=common.DEFAULT_TIMEOUT, throttle=0.0,
             on_attempt=None):
        if on_attempt is not None:
            on_attempt()
        op = params["op"]
        calls.append((op, params.get("state") or params.get("id")))
        if op == "getSessionList":
            return _session_payload(params.get("state"), sessions)
        if op == "getMasterList":
            st = params.get("state") or SESSION_STATE.get(params.get("id"))
            return masterlist(st) if masterlist else _ml_for(st)
        if op == "getBill":
            return getbill(params["id"]) if getbill else GETBILL
        raise AssertionError(f"unexpected op {op}")
    return fake


class _NoClose:
    """main() closes its connection; the test still needs to read the ledger after."""

    def __init__(self, raw):
        self._raw = raw

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._raw, name)


@pytest.fixture
def main_conn(monkeypatch, clock):
    """Wire state.main() to a temp DB with the real config, and never to Turso."""
    raw = _conn()
    conn = _NoClose(raw)
    monkeypatch.setattr(config, "load_env", lambda *a, **k: None)
    monkeypatch.setattr(config, "require_env", lambda name: "k")
    monkeypatch.setattr(db, "init_db", lambda *a, **k: None)
    monkeypatch.setattr(db, "connect", lambda *a, **k: conn)
    return raw


def test_ceiling_reached_makes_zero_calls_and_exits_0(monkeypatch, capsys, main_conn, clock):
    clock(utc(2026, 10, 31, 19, 0))
    _seed(main_conn, "2026-10", 7995)
    calls = []
    monkeypatch.setattr(common, "http_get", _fake_http(calls))
    assert state.main() == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "state: monthly ceiling reached (used 7995 of 8000), skipping" in out
    assert _ledger(main_conn) == {"2026-10": 7995}          # nothing spent, nothing written


def test_main_prints_a_spend_line_that_matches_the_ledger(monkeypatch, capsys, main_conn):
    calls = []
    monkeypatch.setattr(common, "http_get", _legiscan(calls))
    assert state.main() == 0
    out = capsys.readouterr().out
    n = len(calls)
    # 9 bootstrap getSessionList&state= + 1 national getSessionList + 9 master lists
    # by session id; the fixture's two election bills are new only to the first state
    # polled (every state serves the same ids), so two getBills.
    assert n == 9 + 1 + 9 + 2
    assert f"LegiScan queries this run: {n} HTTP attempt(s)" in out
    assert _ledger(main_conn) == {"2026-10": n}
    assert "ledger 2026-10: 0 of 8000 cron ceiling used (10000 monthly cap); 16 state slot(s)" in out


def test_main_passes_the_prorated_budget_to_collect(monkeypatch, main_conn, clock):
    """32 daily slots from Oct 1 00:20Z -> share 250; 10 spent on sessions and 9
    master lists come first -> 231 for getBill. Every target is a SESSION."""
    clock(OCT_START)
    seen = {}

    def spy(conn, base, key, states, terms, grade, budget, throttle, excludes=(), meter=None,
            targets=None, state_ids=None):
        seen["budget"], seen["throttle"] = budget, throttle
        seen["targets"] = [(t.state, t.session_id) for t in targets]
        seen["state_ids"] = state_ids
        return {}
    monkeypatch.setattr(state, "collect", spy)
    monkeypatch.setattr(common, "http_get", _legiscan([]))
    state.main()
    assert (seen["budget"], seen["throttle"]) == (231, state.THROTTLE)
    assert seen["targets"] == [(st, 9000 + i) for i, st in enumerate(WATCHED)]
    assert seen["state_ids"] == FAKE_ID                        # measured, not typed


# --- cap signal ---------------------------------------------------------------------

CAP_BODY = {"status": "ERROR", "alert": {"message": "Monthly query limit reached"}}


def test_a_monthly_error_on_a_masterlist_stops_the_run(monkeypatch, capsys, main_conn):
    calls = []

    def masterlist(st):
        return CAP_BODY if st == "GA" else _ml_for(st)
    monkeypatch.setattr(common, "http_get", _legiscan(calls, masterlist=masterlist))
    assert state.main() == 0
    out = capsys.readouterr().out
    sessions_called = [s for op, s in calls if op == "getMasterList"]
    assert sessions_called == [9000, 9001]                 # TX, then GA; nothing after
    assert f"  {'FL/9002':<10} skipped: LegiScan signalled its allowance is spent" in out
    body = json.dumps(CAP_BODY, separators=(",", ":"))
    assert out.count(body) == 1                            # verbatim, once
    assert _ledger(main_conn) == {"2026-10": len(calls)}


def test_a_monthly_429_through_the_real_retry_loop_stops_the_run(monkeypatch, clock):
    """A 429 whose body names a /month scope is RateBudgetExhausted in common, on its
    first request. The state collector must not treat that as one bad state."""
    conn = _conn()
    calls = _requests_seq(monkeypatch, [
        _Resp(429, text="Rate limit exceeded: 10000/month.")])
    meter = state.UsageMeter()
    r = state.collect(conn, BASE, KEY, ["TX", "GA"], TERMS, GRADE, budget=500,
                      throttle=0.0, meter=meter)
    assert calls == ["getMasterList"]                       # GA never called
    assert r["GA"]["skipped"] and meter.cap_signal
    assert _ledger(conn) == {"2026-10": 1}


def test_a_monthly_error_on_getbill_keeps_the_states_completed_bills(monkeypatch, clock):
    conn = _conn()
    calls = []
    first = {}

    def getbill(bid):
        if not first:
            first["id"] = bid
            return GETBILL
        return CAP_BODY
    monkeypatch.setattr(common, "http_get", _fake_http(calls, getbill=getbill))
    meter = state.UsageMeter()
    r = state.collect(conn, BASE, KEY, ["TX", "GA"], TERMS, GRADE, budget=500,
                      throttle=0.0, meter=meter)
    conn.rollback()
    assert r["TX"]["getbills"] == 1 and r["TX"]["errors"] == 1
    assert r["TX"]["new_items"] > 0                         # committed, not discarded
    assert state.seen_hash(conn, first["id"]) is not None
    assert r["GA"]["skipped"]
    assert ("getMasterList", "GA") not in calls


def test_an_ordinary_error_is_not_a_cap_signal(monkeypatch, clock):
    conn = _conn()
    calls = []

    def by_state(st):
        return {"status": "ERROR", "alert": {"message": "Unknown state abbreviation"}} \
            if st == "ZZ" else MASTERLIST
    monkeypatch.setattr(common, "http_get", _fake_http(calls, by_state=by_state))
    meter = state.UsageMeter()
    r = state.collect(conn, BASE, KEY, ["ZZ", "TX"], TERMS, GRADE, budget=500,
                      throttle=0.0, meter=meter)
    assert meter.cap_signal is None and r["TX"]["new_items"] == 6


def test_cap_signal_body_is_verbatim():
    exc = state.LegiScanError("getBill", CAP_BODY)
    assert state.cap_signal_body(exc) == json.dumps(CAP_BODY, separators=(",", ":"))
    assert str(exc) == "LegiScan getBill status=ERROR: Monthly query limit reached"
    assert state.cap_signal_body(RuntimeError("GET failed after 4 attempts: x")) is None


# --- tools ----------------------------------------------------------------------------

def test_tool_gate_refuses_when_headroom_is_short(capsys, clock):
    conn = _conn()
    _seed(conn, "2026-10", 9_970)
    assert state.tool_gate(conn, 9, 10_000, "t") is False      # 36 worst case > 30
    assert state.tool_gate(conn, 7, 10_000, "t") is True       # 28 fits
    err = capsys.readouterr().err
    assert "REFUSED" in err


def test_masterlist_corpus_refuses_with_zero_calls(monkeypatch, clock):
    conn = _conn()
    _seed(conn, "2026-10", 9_990)
    calls = []
    monkeypatch.setattr(common, "http_get", _fake_http(calls))
    assert masterlist_corpus.gated_build(conn, BASE, KEY, ["TX", "GA", "FL"], 10_000) is None
    assert calls == []
    assert _ledger(conn) == {"2026-10": 9_990}


def test_masterlist_corpus_ledgers_its_attempts(monkeypatch, clock):
    conn = _conn()
    calls = []
    monkeypatch.setattr(common, "http_get", _fake_http(calls))
    corpus = masterlist_corpus.gated_build(conn, BASE, KEY, ["TX", "GA"], 10_000)
    assert set(corpus) == {"TX", "GA"}
    assert _ledger(conn) == {"2026-10": 2}


def test_sasts_dump_refuses_then_ledgers(monkeypatch, clock):
    conn = _conn()
    ids = [str(i) for i in range(1, 101)]                      # 400 worst case
    _seed(conn, "2026-10", 9_700)
    calls = []
    monkeypatch.setattr(common, "http_get", _fake_http(calls, getbill=lambda bid: GETBILL))
    assert sasts_dump.gated_dump(conn, BASE, KEY, ids, 10_000) is None
    assert calls == []
    assert sasts_dump.gated_dump(conn, BASE, KEY, ids[:10], 10_000) is not None
    assert _ledger(conn) == {"2026-10": 9_710}


def test_a_tool_that_crashes_midway_still_ledgers_what_it_spent(monkeypatch, clock):
    conn = _conn()
    n = {"i": 0}

    def fake(url, params=None, headers=None, timeout=None, throttle=0.0, on_attempt=None):
        on_attempt()
        n["i"] += 1
        if n["i"] == 3:
            raise KeyboardInterrupt
        return {"status": "OK", "masterlist": {}}
    monkeypatch.setattr(common, "http_get", fake)
    with pytest.raises(KeyboardInterrupt):
        masterlist_corpus.gated_build(conn, BASE, KEY, ["TX", "GA", "FL", "AZ"], 10_000)
    assert _ledger(conn) == {"2026-10": 3}


def test_backfill_dry_run_rolls_back_the_data_but_not_the_spend(monkeypatch, clock):
    raw = _conn()
    monkeypatch.setattr(config, "load_env", lambda *a, **k: None)
    monkeypatch.setattr(config, "require_env", lambda name: "k")
    monkeypatch.setattr(backfill, "open_ledger", lambda what: _NoClose(raw))
    calls = []
    monkeypatch.setattr(common, "http_get", _fake_http(calls))
    assert backfill.main([]) == 0
    assert [op for op, _ in calls] == ["getMasterList"] * 9
    assert raw.execute("SELECT COUNT(*) AS n FROM state_bills").fetchone()["n"] == 0
    assert _ledger(raw) == {"2026-10": 9}


def test_backfill_refuses_with_zero_calls(monkeypatch, clock):
    raw = _conn()
    _seed(raw, "2026-10", 9_999)
    monkeypatch.setattr(config, "load_env", lambda *a, **k: None)
    monkeypatch.setattr(config, "require_env", lambda name: "k")
    monkeypatch.setattr(backfill, "open_ledger", lambda what: _NoClose(raw))
    calls = []
    monkeypatch.setattr(common, "http_get", _fake_http(calls))
    assert backfill.main(["--apply"]) == 1
    assert calls == []


# --- config and rate ----------------------------------------------------------------

def test_throttle_stays_under_the_two_per_second_window():
    assert state.THROTTLE >= 0.5


def test_the_state_slot_is_a_collect_yml_cron_line():
    """The channel runs on STATE_SLOT only, and runs_left prorates over STATE_SLOTS:
    STATE_SLOT must be a line collect.yml actually fires, and STATE_SLOTS must be
    that line's (hour, minute), or the budget prorates over slots that never run."""
    wf = yaml.safe_load(Path(".github/workflows/collect.yml").read_text(encoding="utf-8"))
    on = wf.get("on", wf.get(True))
    crons = {entry["cron"] for entry in on["schedule"]}
    assert state.STATE_SLOT in crons
    minute, hour, *_ = state.STATE_SLOT.split()
    assert state.STATE_SLOTS == ((int(hour), int(minute)),)


def test_config_carries_the_october_terms():
    st = config.load_sources()["state"]
    assert st["monthly_cap"] == 10_000
    assert 0 < st["cron_ceiling"] < st["monthly_cap"]
    assert st["max_getbill_per_run"] > 0


# --- A4, tightened (Corey, 2026-09-23) -----------------------------------------------
# Only two things stop the run: (a) a 429 or 5xx that has used up every retry, whose
# LAST body names a monthly or query limit; (b) a status=ERROR payload whose ALERT
# MESSAGE names one. Everything else keeps today's behaviour: a bill-level failure
# skips the bill, a state-level one skips the state, and the run goes on.

LIMIT_BODY = "Monthly query limit reached for this API key"
EMPTY_ML = {"status": "OK", "masterlist": {"session": {}}}


def _route(monkeypatch, route):
    """requests.get fake under the REAL common._get. route(params, n) returns a _Resp
    or an exception, where n counts prior requests for the same (op, id/state)."""
    calls = []
    seen = {}

    def fake(url, params=None, headers=None, timeout=None):
        key = (params.get("op"), params.get("state") or params.get("id"))
        n = seen.get(key, 0)
        seen[key] = n + 1
        calls.append(key)
        r = route(params, n)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(common.requests, "get", fake)
    monkeypatch.setattr(common.time, "sleep", lambda *a, **k: None)
    return calls


def _bill_ids():
    return sorted(v["bill_id"] for k, v in MASTERLIST["masterlist"].items()
                  if k != "session" and state.election_match(v, TERMS))


def test_a_429_that_clears_on_retry_never_aborts_and_ledgers_three(monkeypatch, clock):
    """The new ~2 req/s window. Its body may well say "query rate limit" -- this one
    does, on purpose -- and it still must not stop anything, because it cleared."""
    conn = _conn()
    window = _Resp(429, text="Query rate limit exceeded, slow down")
    calls = _route(monkeypatch, lambda p, n: window if n < 2 else _Resp(200, body=EMPTY_ML))
    meter = state.UsageMeter()
    r = state.collect(conn, BASE, KEY, ["TX"], TERMS, GRADE, budget=500, throttle=0.0,
                      meter=meter)
    assert calls == [("getMasterList", "TX")] * 3
    assert meter.cap_signal is None and r["TX"]["error_msg"] is None and not r["TX"]["skipped"]
    assert _ledger(conn) == {"2026-10": 3}


def test_an_unknown_bill_id_skips_that_bill_and_the_run_goes_on(monkeypatch, clock):
    conn = _conn()
    first, second = _bill_ids()

    def route(p, n):
        if p["op"] == "getMasterList":
            return _Resp(200, body=MASTERLIST if p["state"] == "TX" else EMPTY_ML)
        if p["id"] == first:
            return _Resp(200, body={"status": "ERROR", "alert": {"message": "Unknown bill id"}})
        return _Resp(200, body=GETBILL)
    calls = _route(monkeypatch, route)
    meter = state.UsageMeter()
    r = state.collect(conn, BASE, KEY, ["TX", "GA"], TERMS, GRADE, budget=500,
                      throttle=0.0, meter=meter)
    assert r["TX"]["errors"] == 1 and r["TX"]["getbills"] == 1
    assert ("getMasterList", "GA") in calls                    # the run went on
    assert meter.cap_signal is None and not r["GA"]["skipped"]


def test_a_429_exhausted_on_a_named_limit_aborts_keeps_finished_bills_exits_0(
        monkeypatch, capsys, main_conn):
    first, second = _bill_ids()

    def route(p, n):
        if p["op"] == "getSessionList":
            return _Resp(200, body=_session_payload(p.get("state")))
        if p["op"] == "getMasterList":
            return _Resp(200, body=_ml_for(SESSION_STATE[p["id"]]))
        if p["id"] == first:
            return _Resp(200, body=GETBILL)
        return _Resp(429, text=LIMIT_BODY)
    calls = _route(monkeypatch, route)
    assert state.main() == 0
    out = capsys.readouterr().out
    assert calls.count(("getBill", second)) == common.MAX_RETRIES    # every retry used
    assert [c for c in calls if c[0] == "getMasterList"] == [("getMasterList", 9000)]
    main_conn.rollback()
    assert state.seen_hash(main_conn, first) is not None             # finished bill committed
    assert state.seen_hash(main_conn, second) is None                # resumes next run
    for i, st in enumerate(WATCHED[1:], start=1):
        assert f"  {st + '/' + str(9000 + i):<10} skipped: " in out
    assert out.count(LIMIT_BODY) == 1                                # verbatim, once
    assert _ledger(main_conn) == {"2026-10": 9 + 1 + 1 + 1 + common.MAX_RETRIES}


def test_a_429_exhausted_on_an_unrelated_body_skips_the_state_and_goes_on(
        monkeypatch, capsys, main_conn):
    def route(p, n):
        if p["op"] == "getSessionList":
            return _Resp(200, body=_session_payload(p.get("state")))
        if p["op"] == "getMasterList" and p["id"] == 9000:
            return _Resp(429, text="Too Many Requests")
        return _Resp(200, body=EMPTY_ML)
    calls = _route(monkeypatch, route)
    assert state.main() == 0
    cap = capsys.readouterr()
    assert calls.count(("getMasterList", 9000)) == common.MAX_RETRIES
    assert len({c for c in calls if c[0] == "getMasterList"}) == 9   # every session tried
    assert f"  {'TX/9000':<10} ERROR: GET failed after 4 attempts" in cap.err
    assert "Too Many Requests" in cap.err                            # the body is printed
    assert "skipped:" not in cap.out and "Body verbatim" not in cap.out


# The discriminating cases: each is something the looser first draft (any text
# containing "month", or any RateBudgetExhausted) got wrong in one direction or the
# other. The four above pin the brief; these pin the predicate's edges.

def test_a_4xx_naming_the_limit_is_not_on_the_list():
    """Only 429/5xx-after-every-retry and status=ERROR stop the run. A 403 keeps
    today's behaviour, a per-state or per-bill skip, whatever its body says."""
    assert state.cap_signal_body(common.HttpError(403, BASE, LIMIT_BODY)) is None


def test_an_error_alert_saying_month_without_limit_does_not_abort():
    exc = state.LegiScanError("getMasterList",
                              {"status": "ERROR", "alert": {"message": "Invalid month parameter"}})
    assert state.cap_signal_body(exc) is None


def test_an_error_body_is_judged_on_its_alert_message_not_its_other_fields():
    exc = state.LegiScanError("getBill", {"status": "ERROR",
                                          "alert": {"message": "Unknown bill id"},
                                          "note": "see the monthly query limit FAQ"})
    assert state.cap_signal_body(exc) is None


def test_the_query_arm_catches_a_limit_that_never_says_month():
    exc = state.LegiScanError("getBill", {"status": "ERROR",
                                          "alert": {"message": "Query limit exceeded"}})
    assert state.cap_signal_body(exc) == exc.body


def test_a_5xx_exhausted_on_a_query_limit_aborts(monkeypatch, clock):
    conn = _conn()
    calls = _route(monkeypatch, lambda p, n: _Resp(503, text="Daily query limit exceeded"))
    meter = state.UsageMeter()
    r = state.collect(conn, BASE, KEY, ["TX", "GA"], TERMS, GRADE, budget=500,
                      throttle=0.0, meter=meter)
    assert calls == [("getMasterList", "TX")] * common.MAX_RETRIES
    assert meter.cap_signal == "Daily query limit exceeded" and r["GA"]["skipped"]


def test_a_budget_exhausted_429_with_an_unrelated_body_does_not_abort(monkeypatch, clock):
    """An unscoped 429 with a long Retry-After is RateBudgetExhausted in common, but
    its body names no limit, so for LegiScan it is one failed state, not the month."""
    conn = _conn()

    def route(p, n):
        if p["state"] == "TX":
            r = _Resp(429, text="Too Many Requests")
            r.headers["Retry-After"] = "3600"
            return r
        return _Resp(200, body=EMPTY_ML)
    calls = _route(monkeypatch, route)
    meter = state.UsageMeter()
    r = state.collect(conn, BASE, KEY, ["TX", "GA"], TERMS, GRADE, budget=500,
                      throttle=0.0, meter=meter)
    assert meter.cap_signal is None and r["TX"]["error_msg"] and not r["GA"]["skipped"]
    assert ("getMasterList", "GA") in calls


def test_transport_exhaustion_never_aborts(monkeypatch, clock):
    import requests
    conn = _conn()
    _route(monkeypatch, lambda p, n: requests.Timeout("t") if p["state"] == "TX"
           else _Resp(200, body=EMPTY_ML))
    meter = state.UsageMeter()
    r = state.collect(conn, BASE, KEY, ["TX", "GA"], TERMS, GRADE, budget=500,
                      throttle=0.0, meter=meter)
    assert meter.cap_signal is None and not r["GA"]["skipped"]


@pytest.mark.parametrize("text, hit", [
    ("Monthly query limit reached", True),
    ("MONTHLY LIMIT", True),
    ("query limit exceeded", True),
    ("Rate limit exceeded: 10000/month.", True),
    ("Query rate limit exceeded, slow down", True),   # names one; retry decides, not this
    ("Too Many Requests", False),
    ("Invalid month parameter", False),
    ("Unknown bill id", False),
    ("rate limit exceeded", False),                   # limit, but neither month nor query
    ("", False),
])
def test_names_allowance_limit(text, hit):
    assert state.names_allowance_limit(text) is hit


# --- review fixes (the unit's own adversarial review, 2026-09-23) -------------------

def _backlog_masterlist(n):
    """n distinct changed election bills in one masterlist."""
    ml = {"session": {}}
    for i in range(n):
        ml[str(i)] = {"bill_id": 1_800_000 + i, "number": f"SB{i}", "change_hash": f"h{i}",
                      "title": "Relating to voter registration procedures"}
    return {"status": "OK", "masterlist": ml}


def test_a_failed_getbill_is_charged_to_the_budget(monkeypatch, clock):
    """A getBill-side outage must not walk the whole changed backlog: the budget is
    the monthly spend guard, and a failed getBill spends up to four queries."""
    conn = _conn()
    calls = _route(monkeypatch, lambda p, n: _Resp(200, body=_backlog_masterlist(40))
                   if p["op"] == "getMasterList" else _Resp(503, text="upstream down"))
    r = state.collect(conn, BASE, KEY, ["TX"], TERMS, GRADE, budget=5, throttle=0.0)
    getbill_calls = {c for c in calls if c[0] == "getBill"}
    assert len(getbill_calls) == 5                      # not 40
    assert r["TX"]["errors"] == 5 and r["TX"]["getbills"] == 0
    assert _ledger(conn) == {"2026-10": 1 + 5 * common.MAX_RETRIES}


def _pending_conn():
    """A db._Conn over a temp sqlite file: the remote wrapper, which tracks _pending."""
    import sqlite3
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    db.init_db(path)
    raw = sqlite3.connect(path)
    return db._Conn(raw)


def test_main_ends_the_ledger_read_before_collect_starts(monkeypatch, clock):
    """A pending connection refuses the stale-stream reopen, so collect() has to start
    with nothing pending, as it did before the ledger read was added."""
    conn = _pending_conn()
    state.register_source(conn, BASE, "B", "2")
    conn.commit()
    monkeypatch.setattr(config, "load_env", lambda *a, **k: None)
    monkeypatch.setattr(config, "require_env", lambda name: "k")
    monkeypatch.setattr(db, "init_db", lambda *a, **k: None)
    monkeypatch.setattr(db, "connect", lambda *a, **k: conn)
    seen = {}

    def spy(c, *a, **k):
        seen["pending"] = c._pending
        return {}
    monkeypatch.setattr(state, "collect", spy)
    monkeypatch.setattr(common, "http_get", _legiscan([]))
    state.main()
    assert seen == {"pending": False}


def test_tool_gate_ends_its_read(clock):
    conn = _pending_conn()
    state.tool_gate(conn, 9, 10_000, "t")
    assert conn._pending is False


def test_the_spend_flush_retries_once_after_recover(monkeypatch, clock):
    conn = _conn()
    real = db.increment
    fails = {"n": 1}

    def flaky(*a, **k):
        if fails["n"]:
            fails["n"] -= 1
            raise ValueError("Hrana: stream not found")
        return real(*a, **k)
    monkeypatch.setattr(db, "increment", flaky)
    meter = state.UsageMeter()
    meter(); meter()
    state.record_spend_or_warn(conn, meter, "t")
    assert _ledger(conn) == {"2026-10": 2} and meter.pending == {}


def test_sasts_dump_stops_on_a_cap_signal_and_ledgers_what_it_spent(monkeypatch, clock):
    conn = _conn()
    ids = [str(i) for i in range(1, 51)]

    def route(p, n):
        if p["id"] == "3":
            return _Resp(200, body={"status": "ERROR", "alert": {"message": LIMIT_BODY}})
        return _Resp(200, body=GETBILL)
    calls = _route(monkeypatch, route)
    with pytest.raises(state.AllowanceSpent) as ei:
        sasts_dump.gated_dump(conn, BASE, KEY, ids, 10_000)
    assert len(calls) == 3                              # not 50
    assert LIMIT_BODY in ei.value.body
    assert _ledger(conn) == {"2026-10": 3}


def test_backfill_stops_on_a_cap_signal_exits_1_and_ledgers(monkeypatch, clock):
    raw = _conn()
    monkeypatch.setattr(config, "load_env", lambda *a, **k: None)
    monkeypatch.setattr(config, "require_env", lambda name: "k")
    monkeypatch.setattr(backfill, "open_ledger", lambda what: _NoClose(raw))
    calls = _route(monkeypatch, lambda p, n: _Resp(200, body={
        "status": "ERROR", "alert": {"message": LIMIT_BODY}}) if p["state"] == "GA"
        else _Resp(200, body=MASTERLIST))
    assert backfill.main(["--apply"]) == 1
    assert [c[1] for c in calls] == ["TX", "GA"]
    assert raw.execute("SELECT COUNT(*) AS n FROM state_bills").fetchone()["n"] == 0
    assert _ledger(raw) == {"2026-10": 2}


def test_a_string_alert_is_still_classified():
    """The manual shows alert as an object; an unseen response may not follow it."""
    exc = state.LegiScanError("getBill", {"status": "ERROR", "alert": "Monthly query limit reached"})
    assert str(exc) == "LegiScan getBill status=ERROR: Monthly query limit reached"
    assert state.cap_signal_body(exc) == exc.body
