"""Suite for the state collector's session cadence (handoff 98b §4, as revised and ruled).

What is pinned here:
  - the state_id bootstrap: MEASURED once per watched state, ledgered, printed once;
  - the alphabetical prediction of those ids, held against the measurement;
  - the active/adjourned classifier and the Tue-Sat gate across the 2026-11-01 DST
    change;
  - master lists by SESSION id, a concurrent special session included; adjourned
    sessions gated on a moved dataset_hash, and quiet at zero calls otherwise;
  - the URL tripwire; the first-run default; the slot gate; the cache-hit proxy.

Offline: temp SQLite, `common.http_get` faked, `state._now` pinned. The fake serves
ARBITRARY state ids (100 + index), never LegiScan's real ones, so nothing here can pass
because some code path typed the real table in. main() tests patch config.load_env and
db.connect, so the suite never reaches production Turso.

Run:  pytest tests/test_state_sessions.py
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
from collectors import state  # noqa: E402

FIXTURES = Path(REPO) / "tests" / "fixtures"
MASTERLIST = json.loads((FIXTURES / "legiscan_masterlist.json").read_text(encoding="utf-8"))
GETBILL = json.loads((FIXTURES / "legiscan_getbill.json").read_text(encoding="utf-8"))
BASE = "https://api.legiscan.com/"
TERMS = ["voter registration", "voter roll", "proof of citizenship", "mail ballot"]
GRADE = ("B", "2")
WATCHED = ["TX", "GA", "FL", "AZ", "WI", "PA", "MI", "NC", "OH"]   # config order
FAKE_ID = {st: 100 + i for i, st in enumerate(WATCHED)}


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


FRI = utc(2026, 10, 16, 10, 30)   # a 06:17Z run landing late; previous ET day Thu: poll
SUN = utc(2026, 10, 18, 10, 30)   # previous ET day Sat: skip
MON = utc(2026, 10, 19, 10, 30)   # previous ET day Sun: skip


# --- the alphabetical prediction, held against the MEASUREMENT --------------------------
#
# LegiScan publishes no state_id table (manual rev. 20250317; "Internal state id", p34).
# The PREDICTION is that it enumerates states alphabetically BY NAME, AL=1 ... WY=50:
# TX=43, AZ=3, WI=49, and so on. The manual's own examples pin CA=5 (p9, p25) and MD=20
# (p11), both consistent.
#
# The collector never uses this. It MEASURES ids on its first run (getSessionList&state=XX)
# and stores what LegiScan says. This test holds the prediction against that measurement
# (tests/fixtures/legiscan_state_ids_measured.json, taken 2026-09-25). A MISMATCH FAILS SO
# IT GETS LOOKED AT, and the fix is to update this expectation from the measured value --
# never to override the measurement to fit the prediction (Corey, 2026-09-24).

STATES_BY_NAME = [
    ("Alabama", "AL"), ("Alaska", "AK"), ("Arizona", "AZ"), ("Arkansas", "AR"),
    ("California", "CA"), ("Colorado", "CO"), ("Connecticut", "CT"), ("Delaware", "DE"),
    ("Florida", "FL"), ("Georgia", "GA"), ("Hawaii", "HI"), ("Idaho", "ID"),
    ("Illinois", "IL"), ("Indiana", "IN"), ("Iowa", "IA"), ("Kansas", "KS"),
    ("Kentucky", "KY"), ("Louisiana", "LA"), ("Maine", "ME"), ("Maryland", "MD"),
    ("Massachusetts", "MA"), ("Michigan", "MI"), ("Minnesota", "MN"), ("Mississippi", "MS"),
    ("Missouri", "MO"), ("Montana", "MT"), ("Nebraska", "NE"), ("Nevada", "NV"),
    ("New Hampshire", "NH"), ("New Jersey", "NJ"), ("New Mexico", "NM"), ("New York", "NY"),
    ("North Carolina", "NC"), ("North Dakota", "ND"), ("Ohio", "OH"), ("Oklahoma", "OK"),
    ("Oregon", "OR"), ("Pennsylvania", "PA"), ("Rhode Island", "RI"), ("South Carolina", "SC"),
    ("South Dakota", "SD"), ("Tennessee", "TN"), ("Texas", "TX"), ("Utah", "UT"),
    ("Vermont", "VT"), ("Virginia", "VA"), ("Washington", "WA"), ("West Virginia", "WV"),
    ("Wisconsin", "WI"), ("Wyoming", "WY"),
]
PREDICTED = {abbr: i + 1 for i, (_, abbr) in enumerate(sorted(STATES_BY_NAME))}


def test_the_prediction_is_alphabetical_by_state_name():
    assert len(PREDICTED) == 50
    assert (PREDICTED["AL"], PREDICTED["WY"]) == (1, 50)
    assert (PREDICTED["TX"], PREDICTED["AZ"], PREDICTED["WI"]) == (43, 3, 49)


def test_the_prediction_agrees_with_the_manuals_own_examples():
    assert (PREDICTED["CA"], PREDICTED["MD"]) == (5, 20)


def test_the_measured_ids_match_the_alphabetical_prediction():
    measured = json.loads((FIXTURES / "legiscan_state_ids_measured.json")
                          .read_text(encoding="utf-8"))["ids"]
    assert set(measured) == set(WATCHED)
    assert measured == {st: PREDICTED[st] for st in measured}


# --- fakes -------------------------------------------------------------------------

def _session(st, sid, *, sine_die=0, prefile=0, prior=0, special=0, h=None):
    return {"session_id": sid, "state_id": FAKE_ID[st], "year_start": 2026, "year_end": 2026,
            "prefile": prefile, "sine_die": sine_die, "prior": prior, "special": special,
            "session_name": f"{st} {sid}", "dataset_hash": h or f"h-{st}-{sid}"}


def default_sessions():
    """One active regular session and one prior session per watched state."""
    return {st: [_session(st, 9000 + i), _session(st, 8000 + i, sine_die=1, prior=1)]
            for i, st in enumerate(WATCHED)}


def _ml(st, offset=0, url_state=None):
    """The fixture master list re-labelled as `st`'s. `offset` moves the bill ids, so
    two sessions of one state hold different bills; `url_state` lets a test make the
    URLs name another state (the tripwire)."""
    m = json.loads(json.dumps(MASTERLIST))
    for k, v in m["masterlist"].items():
        if k == "session":
            v["state_id"] = FAKE_ID[st]
        elif isinstance(v, dict):
            v["bill_id"] += offset
            v["url"] = v["url"].replace("/TX/", f"/{url_state or st}/")
    return m


def _empty(st):
    """A master list with no bills, whose session block names `st` correctly."""
    return {"status": "OK", "masterlist": {"session": {"state_id": FAKE_ID[st]}}}


class Fake:
    """A LegiScan that knows sessions. `sessions` is {state: [session dicts]}; the
    master list for a session id defaults to _ml(state of that session)."""

    def __init__(self, sessions=None, masterlists=None, fail_bootstrap=(), fail_national=False):
        self.sessions = sessions if sessions is not None else default_sessions()
        self.masterlists = masterlists or {}
        self.fail_bootstrap = set(fail_bootstrap)
        self.fail_national = fail_national
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
        self.calls.append((op, params.get("state") or params.get("id")))
        if op == "getSessionList":
            st = params.get("state")
            if st in self.fail_bootstrap or (st is None and self.fail_national):
                return {"status": "ERROR", "alert": {"message": "Temporary failure"}}
            rows = self.sessions.get(st, []) if st else \
                [r for rows in self.sessions.values() for r in rows]
            return {"status": "OK", "sessions": rows}
        if op == "getMasterList":
            if "id" in params:
                sid = params["id"]
                return self.masterlists.get(sid) or _ml(self.state_of(sid))
            return _ml(params["state"])
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


# Bound at import, before any fixture patches db.init_db/db.connect: a helper that
# looked them up at call time would, inside a `run` test, quietly hand back the
# fixture's database instead of a fresh one (found the hard way in this file).
_REAL_INIT, _REAL_CONNECT = db.init_db, db.connect


def _conn():
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    _REAL_INIT(path)
    conn = _REAL_CONNECT(path)
    state.register_source(conn, BASE, "B", "2")
    conn.commit()
    return conn


@pytest.fixture
def run(monkeypatch):
    """run(fake, now, slot=None) -> (exit code, stdout, stderr): state.main() on one
    temp DB that persists across calls in the test, never on Turso."""
    raw = _conn()
    monkeypatch.setattr(config, "load_env", lambda *a, **k: None)
    monkeypatch.setattr(config, "require_env", lambda name: "k")
    monkeypatch.setattr(db, "init_db", lambda *a, **k: None)
    monkeypatch.setattr(db, "connect", lambda *a, **k: _NoClose(raw))

    def go(fake, now, capsys, slot=None):
        monkeypatch.setattr(state, "_now", lambda: now)
        monkeypatch.setattr(common, "http_get", fake)
        if slot is None:
            monkeypatch.delenv("SLOT", raising=False)
        else:
            monkeypatch.setenv("SLOT", slot)
        rc = state.main()
        out = capsys.readouterr()
        return rc, out.out, out.err
    go.conn = raw
    return go


def _ledger(conn):
    return {r["month"]: (r["queries"], r["masterlists"], r["unchanged_masterlists"]) for r in
            conn.execute("SELECT month, queries, masterlists, unchanged_masterlists "
                         "FROM legiscan_usage").fetchall()}


# --- the classifier and the weekday gate ------------------------------------------

@pytest.mark.parametrize("sine_die, prefile, prior, active", [
    (0, 0, 0, True),      # in session
    (1, 0, 0, False),     # adjourned sine die
    (1, 1, 0, True),      # prefiling open counts as active
    (0, 0, 1, False),     # a prior session is never active by sine_die
    (1, 1, 1, True),      # the ruled formula: prefile alone is enough
])
def test_session_active(sine_die, prefile, prior, active):
    assert state.session_active(sine_die, prefile, prior) is active


@pytest.mark.parametrize("now, polls", [
    (utc(2026, 10, 31, 6, 17), True),    # Sat 02:17 EDT: previous day Fri
    (utc(2026, 10, 31, 11, 0), True),    # the same run landing late
    (utc(2026, 11, 1, 6, 17), False),    # Sun 01:17 EST, first slot after the change: Sat
    (utc(2026, 11, 2, 6, 17), False),    # Mon: previous day Sun
    (utc(2026, 11, 3, 6, 17), True),     # Tue: previous day Mon
    # 04:30Z on Nov 3 is 23:30 EST on MON Nov 2, whose previous day is Sunday: skip.
    # Pinned because it is exactly where reading the UTC date would say Tuesday.
    (utc(2026, 11, 3, 4, 30), False),
    # And the EDT side: 04:30Z on Oct 27 is 00:30 EDT on TUESDAY, previous day Monday:
    # poll. A hard-coded EST offset reads it as Monday 23:30 and skips -- so this case
    # and the one above together rule out BOTH fixed offsets.
    (utc(2026, 10, 27, 4, 30), True),
])
def test_poll_day_across_the_dst_change(now, polls):
    assert state.poll_day(now) is polls


def test_the_gate_uses_the_zone_not_an_offset():
    assert state.ET.key == "America/New_York"
    assert utc(2026, 10, 31, 6, 17).astimezone(state.ET).utcoffset().total_seconds() == -4 * 3600
    assert utc(2026, 11, 1, 6, 17).astimezone(state.ET).utcoffset().total_seconds() == -5 * 3600


def _store(conn, st, sessions, masterlist_hash=None):
    for s in sessions:
        state.upsert_session(conn, st, s, "2026-10-01T00:00:00+00:00")
    if masterlist_hash is not None:
        conn.execute("UPDATE state_sessions SET masterlist_hash = dataset_hash WHERE state = ?",
                     (st,))
    conn.commit()


def test_plan_polls_a_concurrent_special_session_as_its_own_target():
    conn = _conn()
    _store(conn, "GA", [_session("GA", 2167), _session("GA", 2268, special=1),
                        _session("GA", 2000, sine_die=1, prior=1)])
    targets, notes = state.plan_targets(conn, ["GA"], FRI)
    assert [(t.state, t.session_id, t.why) for t in targets] == [
        ("GA", 2167, "active"), ("GA", 2268, "active")]


def test_plan_on_a_sun_or_mon_slot_skips_active_and_says_so():
    conn = _conn()
    _store(conn, "PA", [_session("PA", 2192)])
    for now in (SUN, MON):
        targets, notes = state.plan_targets(conn, ["PA"], now)
        assert targets == [] and notes == ["PA/2192: active; Sun/Mon slot, skip"]


def test_plan_adjourned_is_hash_gated_on_any_day():
    conn = _conn()
    _store(conn, "TX", [_session("TX", 2160, sine_die=1)])
    for now in (FRI, SUN):          # the weekday gate is for ACTIVE sessions only
        targets, _ = state.plan_targets(conn, ["TX"], now)
        assert [(t.session_id, t.why) for t in targets] == [(2160, "adjourned, dataset_hash moved")]
    conn.execute("UPDATE state_sessions SET masterlist_hash = ?",
                 (state.done_marker("h-TX-2160", ""),))
    conn.commit()
    targets, notes = state.plan_targets(conn, ["TX"], FRI)
    assert targets == [] and notes == ["TX/2160: adjourned, dataset_hash unmoved; zero calls"]


def test_plan_ignores_prior_sessions_and_defaults_a_state_with_none_stored():
    conn = _conn()
    _store(conn, "OH", [_session("OH", 1, sine_die=1, prior=1)])
    targets, notes = state.plan_targets(conn, ["OH", "NC"], FRI)
    assert notes == ["OH: every stored session is prior; nothing to poll"]
    assert [(t.state, t.session_id) for t in targets] == [("NC", None)]     # first-run default


def test_hash_seen_at_is_our_observation_time_and_moves_only_with_the_hash():
    conn = _conn()
    s = _session("TX", 2160, h="A")
    state.upsert_session(conn, "TX", s, "2026-10-01T00:00:00+00:00")
    state.upsert_session(conn, "TX", s, "2026-10-02T00:00:00+00:00")
    seen = lambda: conn.execute("SELECT hash_seen_at FROM state_sessions").fetchone()[0]  # noqa: E731
    assert seen() == "2026-10-01T00:00:00+00:00"                 # same hash: kept
    state.upsert_session(conn, "TX", dict(s, dataset_hash="B"), "2026-10-03T00:00:00+00:00")
    assert seen() == "2026-10-03T00:00:00+00:00"                 # moved: re-stamped


# --- main(): the bootstrap ---------------------------------------------------------

def test_the_bootstrap_measures_once_ledgers_its_queries_and_prints_once(run, capsys):
    fake = Fake()
    rc, out, _ = run(fake, FRI, capsys)
    assert rc == 0
    assert fake.ops("getSessionList")[:9] == WATCHED                      # one per state
    assert fake.ops("getSessionList")[9:] == [None]                       # then the national
    table = json.dumps(dict(sorted(FAKE_ID.items())))
    assert out.count("state_id bootstrap, MEASURED from 9 getSessionList&state= queries") == 1
    assert table in out                                                   # the measured ids
    queries, masterlists, unchanged = _ledger(run.conn)["2026-10"]
    assert queries == len(fake.calls)                                     # all of them ledgered
    ids = {r[0]: r[1] for r in run.conn.execute("SELECT DISTINCT state, state_id FROM state_sessions")}
    assert ids == FAKE_ID                                                 # stored as measured

    fake2 = Fake()
    rc, out, _ = run(fake2, utc(2026, 10, 17, 10, 30), capsys)            # the next day
    assert fake2.ops("getSessionList") == [None]                          # national only
    assert "bootstrap" not in out


def test_a_bootstrap_reply_naming_two_state_ids_is_refused(run, capsys):
    sessions = default_sessions()
    sessions["TX"][1]["state_id"] = 999                                   # one reply, two ids
    fake = Fake(sessions=sessions)
    rc, out, err = run(fake, FRI, capsys)
    assert "TX  state_id bootstrap refused" in err
    stored = run.conn.execute("SELECT COUNT(*) FROM state_sessions WHERE state = 'TX'").fetchone()[0]
    assert stored == 0
    assert ("getMasterList", "TX") in fake.calls                          # first-run default


def test_first_run_default_polls_an_unmeasured_state_by_state(run, capsys):
    fake = Fake(fail_bootstrap={"TX"})
    rc, out, err = run(fake, FRI, capsys)
    assert rc == 0
    assert ("getMasterList", "TX") in fake.calls                          # Invocation B
    assert ("getMasterList", 9001) in fake.calls                          # GA by session id
    assert "no measured sessions: active by default, state=" in out


# --- main(): session polling, adjourned quiet, the tripwire ---------------------------

def test_active_sessions_poll_tue_to_sat_and_skip_sun_mon(run, capsys):
    fake = Fake()
    run(fake, FRI, capsys)
    assert fake.ops("getMasterList") == [9000 + i for i in range(9)]
    fake_sun = Fake()
    rc, out, _ = run(fake_sun, SUN, capsys)
    assert fake_sun.ops("getMasterList") == []
    assert fake_sun.ops("getSessionList") == [None]                       # still one a day
    assert "state: no session to poll this slot" in out


def test_an_adjourned_session_with_an_unmoved_hash_makes_zero_calls(run, capsys):
    sessions = {st: [_session(st, 9000 + i, sine_die=1)] for i, st in enumerate(WATCHED)}
    fake = Fake(sessions=sessions)
    run(fake, FRI, capsys)                                  # first sight: polled, fully processed
    assert len(fake.ops("getMasterList")) == 9
    fake2 = Fake(sessions=sessions)
    rc, out, _ = run(fake2, utc(2026, 10, 17, 10, 30), capsys)
    assert fake2.calls == [("getSessionList", None)]                      # ZERO master lists
    assert "adjourned, dataset_hash unmoved; zero calls" in out


def test_an_adjourned_session_is_polled_again_when_its_hash_moves(run, capsys):
    sessions = {"TX": [_session("TX", 2160, sine_die=1, h="A")]}
    sessions.update({st: [_session(st, 9000 + i, sine_die=1)] for i, st in enumerate(WATCHED)
                     if st != "TX"})
    run(Fake(sessions=sessions), FRI, capsys)
    sessions["TX"] = [_session("TX", 2160, sine_die=1, h="B")]            # LegiScan's dataset moved
    fake = Fake(sessions=sessions)
    run(fake, utc(2026, 10, 17, 10, 30), capsys)
    assert fake.ops("getMasterList") == [2160]


def test_a_budget_cut_session_is_not_marked_done(run, capsys, monkeypatch):
    """masterlist_hash moves only when every changed bill was fetched, so an adjourned
    session cut short by the budget is polled again rather than going quiet."""
    sessions = {st: [_session(st, 9000 + i, sine_die=1)] for i, st in enumerate(WATCHED)}
    empty = {9000 + i: _empty(st) for i, st in enumerate(WATCHED) if st != "TX"}
    monkeypatch.setattr(state, "run_budget", lambda *a, **k: state.Budget(
        "2026-10", 0, 16, 11, 1, None))                                  # getBill budget 1
    run(Fake(sessions=sessions, masterlists=empty), FRI, capsys)
    marked = {r[0]: r[1] for r in run.conn.execute(
        "SELECT state, masterlist_hash IS NOT NULL FROM state_sessions")}
    assert marked["TX"] == 0                     # TX's 2 changed bills, 1 fetched: not done
    assert marked["GA"] == 1                     # nothing to fetch: done


def test_the_tripwire_refuses_a_session_whose_urls_name_another_state(run, capsys):
    # Every other session is empty, so the refused one is the only possible writer.
    masterlists = {9000 + i: _empty(st) for i, st in enumerate(WATCHED) if st != "TX"}
    masterlists[9000] = _ml("TX", url_state="OK")                        # mapped TX, names OK
    fake = Fake(masterlists=masterlists)
    rc, out, err = run(fake, FRI, capsys)
    assert rc == 0
    assert "refused: session 9000 was mapped to TX (state_id 100) but its master list names ['OK']" in err
    tx = run.conn.execute("SELECT masterlist_hash FROM state_sessions WHERE session_id = 9000").fetchone()
    assert tx[0] is None                                                  # not marked done
    for table in ("state_seen", "state_bills", "items"):
        assert run.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    assert fake.ops("getBill") == []                                      # nothing fetched


def test_the_tripwire_also_reads_the_session_block(run, capsys):
    bad = _ml("TX")
    bad["masterlist"]["session"]["state_id"] = FAKE_ID["OH"]
    fake = Fake(masterlists={9000: bad})
    rc, out, err = run(fake, FRI, capsys)
    assert f"names state_id {FAKE_ID['OH']}; nothing written" in err


def test_a_national_call_that_does_not_land_plans_from_stored_sessions(run, capsys):
    run(Fake(), FRI, capsys)
    fake = Fake(fail_national=True)
    rc, out, err = run(fake, utc(2026, 10, 17, 10, 30), capsys)
    assert "national getSessionList ERROR: LegiScan getSessionList status=ERROR" in err
    assert "(national getSessionList failed)" in out
    assert fake.ops("getMasterList") == [9000 + i for i in range(9)]


def test_the_national_call_stores_only_watched_states(run, capsys):
    sessions = default_sessions()
    fake = Fake(sessions=sessions)
    run(fake, FRI, capsys)
    sessions["ZZ"] = [dict(_session("TX", 7777), state_id=555, session_name="not watched")]
    run(Fake(sessions=sessions), utc(2026, 10, 17, 10, 30), capsys)
    assert run.conn.execute("SELECT COUNT(*) FROM state_sessions WHERE state_id = 555").fetchone()[0] == 0


# --- the slot gate, the proxy -------------------------------------------------------

@pytest.mark.parametrize("slot, runs", [
    ("17 0 * * *", False), ("17 12 * * *", False), ("17 18 * * *", False),
    ("17 6 * * *", True), ("dispatch", True), (None, True),
])
def test_the_slot_gate(run, capsys, slot, runs):
    fake = Fake()
    rc, out, _ = run(fake, FRI, capsys, slot=slot)
    assert rc == 0
    if runs:
        assert fake.calls
    else:
        assert fake.calls == []
        assert f"state: not this slot ({slot}); the state collector runs on 17 6 * * * only" in out


def test_the_cache_hit_proxy_counts_answered_master_lists(run, capsys):
    """Nine master lists; TX's two election bills are new, and every later state serves
    the same ids, so eight moved no stored hash."""
    run(Fake(), FRI, capsys)
    queries, masterlists, unchanged = _ledger(run.conn)["2026-10"]
    assert (masterlists, unchanged) == (9, 8)


# --- review of this build (2026-09-25): guarded session writes, outage stop, --------
# --- the filter fingerprint, and the two ruled main() tests it found missing -------

def test_two_adjourned_sessions_only_the_moved_one_is_polled(run, capsys):
    """The ruled test: one state, two non-prior adjourned sessions, one hash moves."""
    sessions = {st: [_session(st, 9000 + i, sine_die=1)] for i, st in enumerate(WATCHED)}
    sessions["FL"] = [_session("FL", 2220, sine_die=1, h="a"),
                      _session("FL", 2259, sine_die=1, special=1, h="b")]
    run(Fake(sessions=sessions), FRI, capsys)
    sessions["FL"] = [_session("FL", 2220, sine_die=1, h="a"),
                      _session("FL", 2259, sine_die=1, special=1, h="b2")]
    fake = Fake(sessions=sessions)
    run(fake, utc(2026, 10, 17, 10, 30), capsys)
    assert fake.ops("getMasterList") == [2259]


def test_a_concurrent_special_session_is_polled_and_stored_end_to_end(run, capsys, monkeypatch):
    """The ruled test: GA in regular and special session at once. Both are polled,
    both sessions' bills gate and store; a budget-cut sibling is not marked done."""
    sessions = default_sessions()
    sessions["GA"] = [_session("GA", 2167), _session("GA", 2268, special=1)]
    masterlists = {9000 + i: _empty(st) for i, st in enumerate(WATCHED) if st != "GA"}
    masterlists[2167] = _ml("GA", offset=1000)
    masterlists[2268] = _ml("GA", offset=2000)
    fake = Fake(sessions=sessions, masterlists=masterlists)
    run(fake, FRI, capsys)
    assert 2167 in fake.ops("getMasterList") and 2268 in fake.ops("getMasterList")
    seen = {r[0] for r in run.conn.execute("SELECT bill_id FROM state_seen").fetchall()}
    assert {1701001, 1701002, 1702001, 1702002} <= seen          # both sessions' bills
    marks = dict(run.conn.execute(
        "SELECT session_id, masterlist_hash IS NOT NULL FROM state_sessions WHERE state = 'GA'").fetchall())
    assert marks[2167] == 1 and marks[2268] == 1

    # budget-cut sibling: a fresh DB where getBill budget is 2 -- the regular session's
    # two bills use it, the special session's two are deferred, so it stays unmarked.
    run2_conn = _conn()
    monkeypatch.setattr(db, "connect", lambda *a, **k: _NoClose(run2_conn))
    monkeypatch.setattr(state, "run_budget", lambda *a, **k: state.Budget(
        "2026-10", 0, 16, 40, 2, None))
    rc, out2, _ = run(Fake(sessions=sessions, masterlists=masterlists), FRI, capsys)
    marks = dict(run2_conn.execute(
        "SELECT session_id, masterlist_hash IS NOT NULL FROM state_sessions WHERE state = 'GA'").fetchall())
    assert (marks[2167], marks[2268]) == (1, 0)


def test_a_filter_change_re_polls_an_adjourned_session_once(run, capsys, monkeypatch):
    """CLAUDE.md's standing rule: a term broadening self-stamps on the next run, with
    no backfill. That holds for adjourned sessions only because the done-marker
    carries the filter fingerprint (the review of this build reproduced it failing
    without). A new term re-polls each adjourned session ONCE; then they go quiet."""
    sessions = {st: [_session(st, 9000 + i, sine_die=1)] for i, st in enumerate(WATCHED)}
    real_load = config.load_sources

    def with_terms(terms):
        def load():
            src = real_load()
            src["state"]["terms"] = terms
            src["state"]["exclude_terms"] = []
            return src
        monkeypatch.setattr(config, "load_sources", load)

    with_terms(["voter registration"])
    run(Fake(sessions=sessions), FRI, capsys)
    assert {r[0] for r in run.conn.execute("SELECT bill_id FROM state_seen")} == {1700001}
    with_terms(["voter registration", "mail ballot"])                     # broadened
    fake = Fake(sessions=sessions)
    rc, out, _ = run(fake, utc(2026, 10, 17, 10, 30), capsys)
    assert len(fake.ops("getMasterList")) == 9                            # each once
    assert "adjourned, election filter changed" in out
    assert {r[0] for r in run.conn.execute("SELECT bill_id FROM state_seen")} == {1700001, 1700002}
    fake3 = Fake(sessions=sessions)
    run(fake3, utc(2026, 10, 18, 10, 30), capsys)
    assert fake3.ops("getMasterList") == []                               # quiet again


def test_a_bootstrap_write_failure_prints_the_table_and_re_measures_next_run(run, capsys, monkeypatch):
    real = state.store_sessions
    calls = {"n": 0}

    def flaky(conn, rows, now_iso):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("Hrana: transport error: 502")
        return real(conn, rows, now_iso)
    monkeypatch.setattr(state, "store_sessions", flaky)
    fake = Fake()
    rc, out, err = run(fake, FRI, capsys)
    assert rc == 0                                        # never a non-zero exit
    assert "NOT STORED (write failed); re-measured next run" in out
    assert "state_id bootstrap write discarded" in err
    assert ("getMasterList", "TX") in fake.calls          # first-run default this run
    fake2 = Fake()
    rc, out, _ = run(fake2, utc(2026, 10, 17, 10, 30), capsys)
    assert fake2.ops("getSessionList")[:9] == WATCHED     # re-measured...
    assert "MEASURED from 9" in out and "NOT STORED" not in out   # ...and printed, stored


def test_a_national_write_failure_exits_0_and_plans_from_stored(run, capsys, monkeypatch):
    run(Fake(), FRI, capsys)
    real = state.store_sessions
    monkeypatch.setattr(state, "store_sessions", lambda *a, **k: (_ for _ in ()).throw(
        ValueError("Hrana: transport error: 502")))
    fake = Fake()
    rc, out, err = run(fake, utc(2026, 10, 17, 10, 30), capsys)
    assert rc == 0
    assert "national getSessionList write discarded" in err
    assert "(national getSessionList failed)" in out
    assert fake.ops("getMasterList") == [9000 + i for i in range(9)]
    monkeypatch.setattr(state, "store_sessions", real)


def test_an_outage_on_the_bootstrap_stops_the_run_at_one_call(run, capsys):
    """A timeout that used every retry is ~2 minutes of ladder. Nine of those, plus the
    national call and nine state= defaults, would outlast the 45-minute job."""
    class Down(Fake):
        def __call__(self, url, params=None, **kw):
            self.calls.append((params["op"], params.get("state") or params.get("id")))
            if kw.get("on_attempt"):
                kw["on_attempt"]()
            raise common.RetriesExhausted("GET failed after 4 attempts: x", None, "")
    fake = Down()
    rc, out, _ = run(fake, FRI, capsys)
    assert rc == 0
    assert fake.calls == [("getSessionList", "TX")]
    assert "LegiScan is not answering the session calls" in out


def test_an_outage_on_the_national_call_makes_no_master_lists(run, capsys):
    run(Fake(), FRI, capsys)

    class NationalDown(Fake):
        def __call__(self, url, params=None, **kw):
            if params["op"] == "getSessionList" and not params.get("state"):
                self.calls.append(("getSessionList", None))
                raise common.RetriesExhausted("GET failed after 4 attempts: x", 503, "down")
            return super().__call__(url, params, **kw)
    fake = NationalDown()
    rc, out, _ = run(fake, utc(2026, 10, 17, 10, 30), capsys)
    assert rc == 0 and fake.ops("getMasterList") == []
    assert "(national getSessionList outage)" in out


def test_unchanged_sessions_cost_no_writes():
    """~176 stored sessions for the nine states; a day on which none moved writes none."""
    conn = _conn()
    rows = [(st, x) for st, xs in default_sessions().items() for x in xs]
    assert state.store_sessions(conn, rows, "2026-10-01T00:00:00+00:00") == len(rows)
    conn.commit()
    assert state.store_sessions(conn, rows, "2026-10-02T00:00:00+00:00") == 0
    moved = [(st, dict(x, dataset_hash="new")) if x["session_id"] == 9000 else (st, x)
             for st, x in rows]
    assert state.store_sessions(conn, moved, "2026-10-03T00:00:00+00:00") == 1


# --- state_abbr: the live reply names the state after all ----------------------------

def test_a_national_row_whose_state_abbr_contradicts_the_mapping_is_refused(run, capsys):
    """The live getSessionList (2026-09-25) carries state_abbr, which page 8's example
    does not. A row filed under TX whose own state_abbr says OK is refused, loudly."""
    run(Fake(), FRI, capsys)
    sessions = default_sessions()
    sessions["TX"] = [dict(_session("TX", 9000, h="moved"), state_abbr="OK")]
    rc, out, err = run(Fake(sessions=sessions), utc(2026, 10, 17, 10, 30), capsys)
    assert rc == 0
    assert "TX  REFUSED: the measured state_id 100 names ['OK']" in err
    h = run.conn.execute("SELECT dataset_hash FROM state_sessions WHERE session_id = 9000").fetchone()[0]
    assert h == "h-TX-9000"                                   # not overwritten


def test_a_bootstrap_reply_naming_another_state_abbr_is_refused(run, capsys):
    sessions = default_sessions()
    sessions["GA"] = [dict(x, state_abbr="AL") for x in sessions["GA"]]
    rc, out, err = run(Fake(sessions=sessions), FRI, capsys)
    assert "GA  state_id bootstrap refused" in err and "state_abbr names another state" in err
    assert run.conn.execute("SELECT COUNT(*) FROM state_sessions WHERE state = 'GA'").fetchone()[0] == 0


def test_a_matching_or_absent_state_abbr_is_not_a_conflict(run, capsys):
    sessions = {st: [dict(x, state_abbr=st) for x in xs] for st, xs in default_sessions().items()}
    fake = Fake(sessions=sessions)
    rc, out, err = run(fake, FRI, capsys)
    assert "REFUSED" not in err and "refused" not in err
    assert len(fake.ops("getMasterList")) == 9
