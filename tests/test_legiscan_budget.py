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
    db.increment(conn, "legiscan_usage", "month", month, "queries", n,
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

@pytest.mark.parametrize("now, expected", [
    (OCT_START, 124),                          # 00:17 slot's run, on time: 31*4
    (utc(2026, 10, 1, 3, 0), 124),             # the same run landing ~3h late
    (utc(2026, 10, 1, 0, 5), 125),             # Sep 30 18:17's run, landing after 00:00Z
    (MID_OCT, 62),                             # 1 + Oct 16 18:17 + 15 days * 4
    (utc(2026, 10, 31, 13, 0), 2),             # the 12:17 run; 18:17 still to come
    (utc(2026, 10, 31, 19, 0), 1),             # the month's last slot
    (utc(2026, 11, 1, 0, 20), 120),            # a 30-day month
    (utc(2027, 2, 1, 0, 20), 112),             # February
])
def test_runs_left(now, expected):
    assert state.runs_left(now) == expected


def test_budget_at_month_start():
    b = state.run_budget(0, 8000, 9, 500, OCT_START)
    assert (b.month, b.runs_left, b.allowance, b.getbill, b.skip) == ("2026-10", 124, 64, 55, None)


def test_budget_mid_month():
    b = state.run_budget(4000, 8000, 9, 500, MID_OCT)
    assert (b.runs_left, b.allowance, b.getbill) == (62, 64, 55)


def test_budget_one_slot_before_rollover_hands_over_everything_left():
    b = state.run_budget(7000, 8000, 9, 500, utc(2026, 10, 31, 19, 0))
    assert (b.runs_left, b.allowance, b.getbill) == (1, 1000, 500)   # max_getbill binds


def test_a_quiet_first_half_rolls_forward():
    """Unspent share is not lost: a month that spent only masterlists until the
    16th hands the second half roughly twice the per-run getBill of the first."""
    quiet = state.run_budget(62 * 9, 8000, 9, 500, MID_OCT)
    assert quiet.getbill > 2 * state.run_budget(0, 8000, 9, 500, OCT_START).getbill - 9


def test_storm_is_metered_not_front_loaded():
    """The failure proration exists for: 500 changed bills on the 1st would, under
    the old flat cap, spend 509 of the month in one run. Prorated, 55."""
    assert state.run_budget(0, 8000, 9, 500, OCT_START).getbill == 55


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
    """The review's case: share 8 at mid-month. The handoff's rule alone would run
    61 masterlist-only runs (549 queries, zero bills); the amendment skips them, and
    the share accumulates until a run can afford a bill."""
    b = state.run_budget(7450, 8000, 9, 500, MID_OCT)
    assert (b.allowance, b.skip, b.getbill) == (8, "share", 0)
    later = state.run_budget(7450, 8000, 9, 500, utc(2026, 10, 25, 13, 0))
    assert later.skip is None and later.getbill > 0


def test_a_share_skip_makes_zero_calls_and_exits_0(monkeypatch, capsys, main_conn, clock):
    _seed(main_conn, "2026-10", 7450)
    calls = []
    monkeypatch.setattr(common, "http_get", _fake_http(calls))
    assert state.main() == 0
    assert calls == []
    out = capsys.readouterr().out
    assert ("state: this run's prorated share (8) cannot pay for 9 masterlists plus one "
            "getBill (used 7450 of 8000, 62 run(s) left), skipping") in out


def test_getbill_budget_is_never_negative_and_never_over_the_cap():
    for used in range(0, 10_500, 97):
        for now in (OCT_START, MID_OCT, utc(2026, 10, 31, 19, 0), utc(2026, 10, 1, 0, 5)):
            for max_getbill in (0, 1, 55, 500):
                b = state.run_budget(used, 8000, 9, max_getbill, now)
                assert 0 <= b.getbill <= max_getbill
                assert b.allowance >= 0


# --- main(): ceiling, printing, exit 0 -----------------------------------------

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
    monkeypatch.setattr(common, "http_get", _fake_http(calls))
    assert state.main() == 0
    out = capsys.readouterr().out
    n = len(calls)
    # Nine masterlists; the fixture's two election bills are new only to the first
    # state (every state serves the same ids), so two getBills.
    assert n == 11
    assert f"LegiScan queries this run: {n} HTTP attempt(s)" in out
    assert _ledger(main_conn) == {"2026-10": n}
    assert "ledger 2026-10: 0 of 8000 cron ceiling used (10000 monthly cap); 62 run(s)" in out


def test_main_passes_the_prorated_budget_to_collect(monkeypatch, main_conn, clock):
    clock(OCT_START)
    seen = {}

    def spy(conn, base, key, states, terms, grade, budget, throttle, excludes=(), meter=None):
        seen["budget"], seen["throttle"] = budget, throttle
        return {}
    monkeypatch.setattr(state, "collect", spy)
    state.main()
    assert seen == {"budget": 55, "throttle": state.THROTTLE}


# --- cap signal ---------------------------------------------------------------------

CAP_BODY = {"status": "ERROR", "alert": {"message": "Monthly query limit reached"}}


def test_a_monthly_error_on_a_masterlist_stops_the_run(monkeypatch, capsys, main_conn):
    calls = []

    def by_state(st):
        return CAP_BODY if st == "GA" else MASTERLIST
    monkeypatch.setattr(common, "http_get", _fake_http(calls, by_state=by_state))
    assert state.main() == 0
    out = capsys.readouterr().out
    states_called = [s for op, s in calls if op == "getMasterList"]
    assert states_called == ["TX", "GA"]                   # nothing after GA
    assert "  FL  skipped: LegiScan signalled its allowance is spent" in out
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


def test_cron_slots_agree_with_collect_yml():
    wf = yaml.safe_load(Path(".github/workflows/collect.yml").read_text(encoding="utf-8"))
    on = wf.get("on", wf.get(True))
    slots = set()
    for entry in on["schedule"]:
        minute, hour, *_ = entry["cron"].split()
        slots.add((int(hour), int(minute)))
    assert slots == set(state.CRON_SLOTS)


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
        if p["op"] == "getMasterList":
            return _Resp(200, body=MASTERLIST)
        if p["id"] == first:
            return _Resp(200, body=GETBILL)
        return _Resp(429, text=LIMIT_BODY)
    calls = _route(monkeypatch, route)
    assert state.main() == 0
    out = capsys.readouterr().out
    assert calls.count(("getBill", second)) == common.MAX_RETRIES    # every retry used
    assert [c for c in calls if c[0] == "getMasterList"] == [("getMasterList", "TX")]
    main_conn.rollback()
    assert state.seen_hash(main_conn, first) is not None             # finished bill committed
    assert state.seen_hash(main_conn, second) is None                # resumes next run
    for st in ("GA", "FL", "AZ", "WI", "PA", "MI", "NC", "OH"):
        assert f"  {st:<3} skipped: " in out
    assert out.count(LIMIT_BODY) == 1                                # verbatim, once
    assert _ledger(main_conn) == {"2026-10": 1 + 1 + common.MAX_RETRIES}


def test_a_429_exhausted_on_an_unrelated_body_skips_the_state_and_goes_on(
        monkeypatch, capsys, main_conn):
    def route(p, n):
        if p["op"] == "getMasterList" and p["state"] == "TX":
            return _Resp(429, text="Too Many Requests")
        return _Resp(200, body=EMPTY_ML)
    calls = _route(monkeypatch, route)
    assert state.main() == 0
    cap = capsys.readouterr()
    assert calls.count(("getMasterList", "TX")) == common.MAX_RETRIES
    assert len({c for c in calls if c[0] == "getMasterList"}) == 9   # every state tried
    assert "TX  ERROR: GET failed after 4 attempts" in cap.err
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
