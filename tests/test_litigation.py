"""Offline tests for the litigation substantive-entry classifier and helpers.

Pure functions only -- no network, no DB. Uses the real config term lists so the
test guards the actual promotion rule. Run:  pytest tests/test_litigation.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.chdir(REPO)

import config  # noqa: E402
import db  # noqa: E402
import common  # noqa: E402
from collectors import litigation as lit  # noqa: E402


def _lists():
    l = config.load_sources()["litigation"]
    return l.get("substantive_entry_types", []), l.get("excluded_entry_phrases", [])


def test_substantive_promoted():
    types, ex = _lists()
    S = lambda d: lit.is_substantive(d, types, ex)
    assert S("COMPLAINT against All Defendants filed by COMMON CAUSE")
    assert S("MOTION to Dismiss, MOTION for Summary Judgment by TODD BLANCHE, U.S. DEPARTMENT OF JUSTICE.")
    assert S("Memorandum in opposition to re 32 MOTION to Dismiss filed by COMMON CAUSE")
    assert S("Joint MOTION for Order for Expedited Dispositive Motion Briefing Schedule")
    assert S("ORDER granting motion to dismiss")
    assert S("NOTICE OF APPEAL by COMMON CAUSE")


def test_noise_excluded():
    types, ex = _lists()
    S = lambda d: lit.is_substantive(d, types, ex)
    assert not S("NOTICE of Appearance by Jane Petersen Bentrott on behalf of COMMON CAUSE")
    assert not S("MOTION for Leave to Appear Pro Hac Vice :Attorney Name- Sara Chimene-Weiss")
    assert not S("LCvR 26.1 CERTIFICATE OF DISCLOSURE of Corporate Affiliations and Financial Interests")
    assert not S("SUMMONS (3) Issued Electronically as to All Defendants")
    assert not S("RETURN OF SERVICE/AFFIDAVIT of Summons and Complaint Executed")
    assert not S("ORDER granting 4 Motion for Leave to Appear Pro Hac Vice")  # order, but pro-hac noise
    assert not S("")


def test_helpers():
    assert lit.slugify("United States v. Weber") == "united-states-v-weber"
    assert lit.split_caption("Common Cause v. U.S. Department of Justice") == ("Common Cause", "U.S. Department of Justice")
    assert lit.split_caption("No versus here") == (None, None)


def _raise_rate_limit(*args, **kwargs):
    raise RuntimeError("GET failed after 4 attempts: https://www.courtlistener.com/api/rest/v4/dockets/")


def test_resolve_rate_limit_skips_without_raising(tmp_path, monkeypatch):
    """A rate-limited resolve is caught per case: a skip dict, no exception, and
    nothing half-written -- the same graceful treatment the poll guard gives."""
    dbp = str(tmp_path / "t.db")
    db.init_db(dbp)
    conn = db.connect(dbp)
    monkeypatch.setattr(lit, "resolve_docket", _raise_rate_limit)
    seed = {"caption": "United States v. Delaware", "docket_number": "1:25-cv-01453",
            "court": "District of Delaware", "court_id": "ded", "category": "voter-data", "notes": "n"}
    r = lit.collect_case(conn, "base", {}, seed, [], [])          # must NOT raise
    assert r["resolved"] is False and r.get("resolve_failed") is True
    assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0   # nothing half-seeded
    conn.close()


def test_loop_continues_past_a_resolve_failure(tmp_path, monkeypatch):
    """First case's resolve rate-limits (skipped); the loop goes on and the second
    resolves normally -- and its caption takes the CourtListener case_name."""
    dbp = str(tmp_path / "t.db")
    db.init_db(dbp)
    conn = db.connect(dbp)
    lit.register_sources(conn)          # the B2 item's source_id FKs to sources
    conn.commit()
    calls = {"n": 0}

    def fake_resolve(base, headers, dn, court_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("GET failed after 4 attempts")
        return {"id": 777, "absolute_url": "/docket/777/us-v-real/",
                "date_filed": "2026-02-01", "date_terminated": None,
                "case_name": "United States v. RealName"}

    monkeypatch.setattr(lit, "resolve_docket", fake_resolve)
    monkeypatch.setattr(lit, "poll_entries", lambda *a, **k: ([], None))
    seeds = [
        {"caption": "United States v. First", "docket_number": "1:25-cv-00001",
         "court": "District of Delaware", "court_id": "ded", "category": "voter-data", "notes": "n"},
        {"caption": "United States v. Second", "docket_number": "1:25-cv-00002",
         "court": "District of Colorado", "court_id": "cod", "category": "voter-data", "notes": "n"},
    ]
    results = [lit.collect_case(conn, "base", {}, s, [], [], bootstrap_requests=5) for s in seeds]  # no crash
    assert results[0].get("resolve_failed") is True and results[0]["resolved"] is False
    assert results[1]["resolved"] is True
    rows = [row["caption"] for row in conn.execute("SELECT caption FROM cases").fetchall()]
    assert rows == ["United States v. RealName"]   # only the resolved one, case_name applied
    conn.close()


def test_main_exits_zero_when_every_resolve_rate_limits(tmp_path, monkeypatch):
    """The whole point of the guard: a rate-limited resolve no longer crashes main()."""
    monkeypatch.setattr(config, "load_env", lambda *a, **k: None)   # never read a real .env (no Turso creds leak in)
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "m.db"))      # local temp DB, not the repo's
    monkeypatch.setenv("COURTLISTENER_TOKEN", "test-token")
    monkeypatch.setattr(lit, "load_tracker_seeds", lambda *a, **k: [])
    monkeypatch.setattr(lit, "resolve_docket", _raise_rate_limit)
    assert lit.main() == 0


# --------------------------------------------------------------------------- #
# Incremental polling (handoff 7): the date_modified high-water mark
# --------------------------------------------------------------------------- #
def test_poll_params_bootstrap_vs_incremental(monkeypatch):
    """since=None builds the bootstrap query (no date_modified__gt, order by
    entry_number, retry kept); since=<mark> builds the incremental window
    (date_modified__gt, order by date_modified,id, empty-retry skipped)."""
    calls = []

    def fake_fetch(url, params, headers, retry_empty=True):
        calls.append((dict(params) if params else params, retry_empty))
        return {"results": [], "next": None}

    monkeypatch.setattr(lit, "_fetch_page", fake_fetch)

    lit.poll_entries("https://x/api", {}, "555", since=None)
    p, retry = calls[-1]
    assert "date_modified__gt" not in p
    assert p["order_by"] == "entry_number"
    assert p["omit"] == lit.ENTRY_OMIT
    assert retry is True                       # bootstrap first page keeps the empty-retry

    calls.clear()
    lit.poll_entries("https://x/api", {}, "555", since="2026-06-01T00:00:00Z")
    p, retry = calls[-1]
    assert p["date_modified__gt"] == "2026-06-01T00:00:00Z"
    assert p["order_by"] == "date_modified,id"
    assert p["omit"] == lit.ENTRY_OMIT
    assert retry is False                      # incremental first page skips the empty-retry


def test_incremental_empty_window_is_one_request(monkeypatch):
    """THE regression: an empty incremental first page returns ([], None) in exactly
    ONE request -- not the 5 retries the empty-page guard would otherwise spend on
    every quiet docket."""
    n = {"c": 0}

    def fake_http_get(url, params=None, headers=None, timeout=30, throttle=0.0):
        n["c"] += 1
        return {"results": [], "next": None}

    monkeypatch.setattr(common, "http_get", fake_http_get)
    assert lit.poll_entries("https://x/api", {}, "555", since="2026-06-01T00:00:00Z") == ([], None)
    assert n["c"] == 1


def test_bootstrap_empty_middle_page_still_retries(monkeypatch):
    """A bootstrap walk keeps the defensive empty-retry: an empty MIDDLE page (one
    with a `next`) is retried, not accepted, so a transient blank recovers."""
    monkeypatch.setattr(lit.time, "sleep", lambda *a, **k: None)   # no real backoff
    seq = [
        {"results": [{"date_modified": "2026-01-01T00:00:00Z"}], "next": "URL2"},  # page 1
        {"results": [], "next": "URL2"},                                          # page 2 empty -> retry
        {"results": [{"date_modified": "2026-02-02T00:00:00Z"}], "next": None},    # retry recovers
    ]
    n = {"c": 0}

    def fake_http_get(url, params=None, headers=None, timeout=30, throttle=0.0):
        d = seq[n["c"]]
        n["c"] += 1
        return d

    monkeypatch.setattr(common, "http_get", fake_http_get)
    entries, mark = lit.poll_entries("https://x/api", {}, "555", since=None)
    assert n["c"] == 3                         # the empty middle page WAS retried
    assert len(entries) == 2
    assert mark == "2026-02-02T00:00:00Z"


def test_mark_is_max_date_modified_not_last(monkeypatch):
    """The new mark is the MAX date_modified across the window, not the last entry in
    list order (order_by=date_modified,id is not guaranteed to put the max last)."""
    page = {"results": [
        {"date_modified": "2026-03-03T00:00:00Z"},
        {"date_modified": "2026-09-09T00:00:00Z"},   # max, but not last
        {"date_modified": "2026-05-05T00:00:00Z"},
    ], "next": None}
    monkeypatch.setattr(lit, "_fetch_page", lambda *a, **k: page)
    _, mark = lit.poll_entries("https://x/api", {}, "555", since="2026-01-01T00:00:00Z")
    assert mark == "2026-09-09T00:00:00Z"


def test_mark_unchanged_when_write_entries_raises(tmp_path, monkeypatch):
    """The safety invariant: if write_entries raises, the transaction rolls back and
    entries_synced_at does NOT advance, so the next run re-fetches the same window."""
    dbp = str(tmp_path / "t.db")
    db.init_db(dbp)
    conn = db.connect(dbp)
    lit.register_sources(conn)
    conn.execute(
        "INSERT INTO cases (case_id, caption, court, docket_number, entries_synced_at) "
        "VALUES ('555', 'United States v. Existing', 'District of X', '1:25-cv-09999', "
        "'2026-05-05T00:00:00Z')")
    conn.commit()
    seed = {"caption": "United States v. Existing", "docket_number": "1:25-cv-09999",
            "court": "District of X", "court_id": "xxd", "category": "voter-data", "notes": "n"}
    monkeypatch.setattr(lit, "poll_entries", lambda *a, **k: (
        [{"date_filed": "2026-09-09", "description": "ORDER", "date_modified": "2026-12-31T00:00:00Z"}],
        "2026-12-31T00:00:00Z"))

    def boom(*a, **k):
        raise RuntimeError("disk full mid-write")

    monkeypatch.setattr(lit, "write_entries", boom)
    with pytest.raises(RuntimeError):
        lit.collect_case(conn, "base", {}, seed, [], [], bootstrap_requests=5)
    mark = conn.execute("SELECT entries_synced_at FROM cases WHERE case_id='555'").fetchone()[0]
    assert mark == "2026-05-05T00:00:00Z"      # unmoved
    conn.close()


def test_full_walk_request_budget_defers_when_spent(tmp_path, monkeypatch):
    """The budget is a REQUEST count drawn down only by full walks. Three fresh-resolve
    dockets (no local history -> full-walk path), budget=3, each walk costs 2 requests:
    two get walked (budget 3 -> 1 -> -1) and the third is deferred (mark stays NULL)."""
    monkeypatch.setattr(config, "load_env", lambda *a, **k: None)
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "m.db"))
    monkeypatch.setenv("COURTLISTENER_TOKEN", "test-token")
    seeds = [
        {"caption": f"United States v. S{i}", "docket_number": f"1:25-cv-0000{i}",
         "court": "District of X", "court_id": "xxd", "category": "voter-data", "notes": "n"}
        for i in range(3)
    ]
    fake_sources = {"litigation": {
        "api": {"base": "https://x/api", "key_env": "COURTLISTENER_TOKEN"},
        "substantive_entry_types": [], "excluded_entry_phrases": [],
        "max_bootstrap_requests_per_run": 3, "seed_cases": seeds,
    }}
    monkeypatch.setattr(config, "load_sources", lambda *a, **k: fake_sources)
    monkeypatch.setattr(lit, "load_tracker_seeds", lambda *a, **k: [])

    def fake_resolve(base, headers, dn, court_id):
        return {"id": 100 + int(dn[-1]), "absolute_url": f"/docket/{dn}/",
                "date_filed": "2026-01-01", "date_terminated": None, "case_name": f"US v {dn}"}

    def fake_poll(base, headers, cid, since=None, page_counter=None):
        if page_counter is not None:        # a full walk: charge 2 requests to the budget
            page_counter[0] += 2
        return ([], "2026-10-10T00:00:00Z")

    monkeypatch.setattr(lit, "resolve_docket", fake_resolve)
    monkeypatch.setattr(lit, "poll_entries", fake_poll)

    assert lit.main() == 0
    conn = db.connect(str(tmp_path / "m.db"))
    marked = conn.execute("SELECT COUNT(*) FROM cases WHERE entries_synced_at IS NOT NULL").fetchone()[0]
    nullmark = conn.execute("SELECT COUNT(*) FROM cases WHERE entries_synced_at IS NULL").fetchone()[0]
    assert (marked, nullmark) == (2, 1)
    conn.close()


# --------------------------------------------------------------------------- #
# Single-page probe seeding (handoff 7 redesign)
# --------------------------------------------------------------------------- #
def _seed_case(conn, case_id, docket_number, court, *, latest_entry_at=None,
               entries_synced_at=None, with_entry=False):
    """Insert a bound case row (numeric case_id) the way production seeding does."""
    conn.execute(
        "INSERT INTO cases (case_id, caption, court, docket_number, latest_entry_at, "
        "entries_synced_at) VALUES (?,?,?,?,?,?)",
        (case_id, f"United States v. {case_id}", court, docket_number,
         latest_entry_at, entries_synced_at))
    if with_entry:
        conn.execute(
            "INSERT INTO case_entries (case_id, entry_at, description) VALUES (?,?,?)",
            (case_id, "2026-01-01T00:00:00Z", "COMPLAINT"))
    conn.commit()


def test_probe_one_request_sets_mark_to_page_minimum(tmp_path, monkeypatch):
    """A no-mark docket whose history we already hold is probed: exactly one request,
    and entries_synced_at is set to the MINIMUM date_modified on the descending page."""
    dbp = str(tmp_path / "t.db")
    db.init_db(dbp)
    conn = db.connect(dbp)
    lit.register_sources(conn)
    _seed_case(conn, "555", "1:25-cv-09999", "District of X",
               latest_entry_at="2026-05-01T00:00:00Z", with_entry=True)
    seed = {"caption": "United States v. Existing", "docket_number": "1:25-cv-09999",
            "court": "District of X", "court_id": "xxd", "category": "voter-data", "notes": "n"}
    n = {"c": 0}

    def fake_http_get(url, params=None, headers=None, timeout=30, throttle=0.0):
        n["c"] += 1
        assert params.get("order_by") == "-date_modified,-id"   # descending probe
        return {"results": [
            {"date_modified": "2026-09-09T00:00:00Z", "date_filed": "2026-09-01", "description": "ORDER A"},
            {"date_modified": "2026-07-07T00:00:00Z", "date_filed": "2026-07-01", "description": "ORDER B"},
            {"date_modified": "2026-08-08T00:00:00Z", "date_filed": "2026-08-01", "description": "ORDER C"},
        ], "next": "PAGE2_SHOULD_NOT_BE_FETCHED"}

    monkeypatch.setattr(common, "http_get", fake_http_get)
    r = lit.collect_case(conn, "base", {}, seed, [], [], bootstrap_requests=30)
    assert n["c"] == 1                       # page 1 only, no pagination follow
    assert r["mode"] == "probe" and r.get("walk_requests", 0) == 0
    mark = conn.execute("SELECT entries_synced_at FROM cases WHERE case_id='555'").fetchone()[0]
    assert mark == "2026-07-07T00:00:00Z"    # the MIN, not the max
    conn.close()


def test_no_history_takes_full_walk_not_probe(tmp_path, monkeypatch):
    """A no-mark docket with null latest_entry_at (never cleanly polled) takes the full
    walk, not the probe."""
    dbp = str(tmp_path / "t.db")
    db.init_db(dbp)
    conn = db.connect(dbp)
    lit.register_sources(conn)
    _seed_case(conn, "556", "1:25-cv-08888", "District of X")   # latest_entry_at NULL, no entries
    seed = {"caption": "United States v. Fresh", "docket_number": "1:25-cv-08888",
            "court": "District of X", "court_id": "xxd", "category": "voter-data", "notes": "n"}
    called = {"probe": 0, "walk": 0}
    monkeypatch.setattr(lit, "probe_mark",
                        lambda *a, **k: (called.__setitem__("probe", called["probe"] + 1), ([], None))[1])

    def fake_poll(base, headers, cid, since=None, page_counter=None):
        called["walk"] += 1
        assert since is None                 # a full walk
        return ([], None)

    monkeypatch.setattr(lit, "poll_entries", fake_poll)
    r = lit.collect_case(conn, "base", {}, seed, [], [], bootstrap_requests=30)
    assert called == {"probe": 0, "walk": 1} and r["mode"] == "full-walk"
    conn.close()


def test_marked_docket_skips_probe_goes_incremental(tmp_path, monkeypatch):
    """A docket already carrying a mark skips the probe entirely and polls incrementally
    from that mark."""
    dbp = str(tmp_path / "t.db")
    db.init_db(dbp)
    conn = db.connect(dbp)
    lit.register_sources(conn)
    _seed_case(conn, "557", "1:25-cv-07777", "District of X",
               latest_entry_at="2026-05-01T00:00:00Z", entries_synced_at="2026-06-06T00:00:00Z",
               with_entry=True)
    seed = {"caption": "United States v. Marked", "docket_number": "1:25-cv-07777",
            "court": "District of X", "court_id": "xxd", "category": "voter-data", "notes": "n"}
    called = {"probe": 0}
    monkeypatch.setattr(lit, "probe_mark",
                        lambda *a, **k: (called.__setitem__("probe", called["probe"] + 1), ([], None))[1])
    seen = {}

    def fake_poll(base, headers, cid, since=None, page_counter=None):
        seen["since"] = since
        return ([], None)

    monkeypatch.setattr(lit, "poll_entries", fake_poll)
    r = lit.collect_case(conn, "base", {}, seed, [], [], bootstrap_requests=30)
    assert called["probe"] == 0 and r["mode"] == "incremental"
    assert seen["since"] == "2026-06-06T00:00:00Z"
    conn.close()


if __name__ == "__main__":
    test_substantive_promoted()
    test_noise_excluded()
    test_helpers()
    print("ok")
