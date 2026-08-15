"""Offline tests for the litigation substantive-entry classifier and helpers.

Pure functions only -- no network, no DB. Uses the real config term lists so the
test guards the actual promotion rule. Run:  pytest tests/test_litigation.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.chdir(REPO)

import libsql  # noqa: E402
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


def test_case_status_both_branches():
    """`date_terminated` is the whole mapping. Pinned because tools/status_audit
    evaluates this same function against a live docket to measure how stale the
    stored `cases.status` values are; a silent change here would move the audit's
    yardstick along with the collector and hide the drift it exists to find.
    Absent, null and empty-string all mean 'not terminated' -- CourtListener sends
    null for a live docket, and the falsy check must not treat "" as a date."""
    assert lit.case_status({"id": 1}) == "pending"
    assert lit.case_status({"id": 1, "date_terminated": None}) == "pending"
    assert lit.case_status({"id": 1, "date_terminated": ""}) == "pending"
    assert lit.case_status({"id": 1, "date_terminated": "2026-06-24"}) == "terminated"


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


def test_upsert_case_preserves_asserted_superseded_by(tmp_path):
    """The load-bearing invariant behind the Georgia venue refile (handoff 14): a
    terminated source row that is STILL a live seed gets an upsert_case on every run,
    yet its out-of-band `superseded_by` must survive. It does because the row dict omits
    that column and db.upsert only writes listed columns. Assert the link is untouched
    AND that status/caption/updated_at DID change, so this proves the upsert actually ran
    rather than silently no-opping and passing for the wrong reason."""
    dbp = str(tmp_path / "t.db")
    db.init_db(dbp)
    conn = db.connect(dbp)
    # The successor row must exist first: superseded_by is a self-FK to cases(case_id).
    conn.execute(
        "INSERT INTO cases (case_id, caption, status, docket_number) VALUES (?, ?, ?, ?)",
        ("72193752", "United States v. Georgia", "pending", "1:26-cv-00485"),
    )
    # Pre-existing terminated source with an asserted link and a stale caption/timestamp.
    conn.execute(
        "INSERT INTO cases (case_id, caption, status, docket_number, updated_at, superseded_by) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("72053306", "United States v. Georgia (old)", "terminated",
         "5:25-cv-00548", "2000-01-01T00:00:00Z", "72193752"),
    )
    conn.commit()

    seed = {"caption": "United States v. Georgia (seed)", "docket_number": "5:25-cv-00548",
            "court": "Middle District of Georgia", "category": "voter-data", "notes": "n"}
    docket = {"case_name": "United States v. Georgia", "date_filed": "2025-11-01",
              "date_terminated": None, "absolute_url": "/docket/1/us-v-ga/"}
    lit.upsert_case(conn, "72053306", seed, docket)
    conn.commit()

    row = conn.execute(
        "SELECT superseded_by, status, caption, updated_at FROM cases WHERE case_id = '72053306'"
    ).fetchone()
    assert row["superseded_by"] == "72193752"                     # the link survived the rewrite
    assert row["status"] == "pending"                             # ... and the upsert really ran
    assert row["caption"] == "United States v. Georgia"           # case_name applied
    assert row["updated_at"] != "2000-01-01T00:00:00Z"            # timestamp refreshed
    conn.close()


def _entries_db(tmp_path):
    """A temp DB with the courtlistener source row write_entries' A1 items FK to."""
    dbp = str(tmp_path / "entries.db")
    db.init_db(dbp)
    conn = db.connect(dbp)
    conn.execute(
        "INSERT INTO sources (id, name, channel, kind, admiralty_source, admiralty_info)"
        " VALUES ('courtlistener', 'CL', 'litigation', 'api', 'A', '1')")
    conn.execute("INSERT INTO cases (case_id, caption, status) VALUES ('X', 'c', 'pending')")
    conn.commit()
    return conn


def test_latest_entry_at_cannot_move_backwards_on_a_backfilled_window(tmp_path):
    """The regression that cost 12 of 40 rows, up to 83 days (handoff 55/56).

    `write_entries` used to set latest_entry_at to the max date_filed IN THE POLLED
    BATCH. That was correct while every poll was a full walk and the batch was the
    docket. Once polling went incremental (c8b8b6f, 2026-07-22) the batch became a
    date_modified window, and RECAP backfills old filings late -- so a window can
    legitimately contain ONLY an old entry, and the assignment walked the column
    backwards. West Virginia read 2026-05-15 while holding an entry from 2026-08-06.

    This is that exact sequence. It fails against the assignment and passes against
    the derivation, which is what makes it a regression test rather than a restatement
    of the new code: the second poll's batch max (05-15) is deliberately OLDER than
    the stored value, so an implementation that trusts the batch writes 05-15."""
    conn = _entries_db(tmp_path)
    types, excludes = ["order"], []
    stored = lambda: conn.execute(
        "SELECT latest_entry_at FROM cases WHERE case_id = 'X'").fetchone()["latest_entry_at"]
    table_max = lambda: conn.execute(
        "SELECT MAX(entry_at) FROM case_entries WHERE case_id = 'X'").fetchone()[0]

    lit.write_entries(conn, "X", "c", None,
                      [{"date_filed": "2026-08-06", "description": "ORDER recent"}],
                      types, excludes)
    conn.commit()
    assert stored() == "2026-08-06T00:00:00"

    # A later poll whose window holds only a late-backfilled OLDER filing.
    lit.write_entries(conn, "X", "c", None,
                      [{"date_filed": "2026-05-15", "description": "ORDER backfilled"}],
                      types, excludes)
    conn.commit()
    assert stored() == "2026-08-06T00:00:00"      # unmoved: the batch is not the docket
    assert stored() == table_max()                # and still equal to its derivation
    conn.close()


def test_latest_entry_at_equals_the_table_max_after_a_non_empty_poll(tmp_path):
    """The invariant itself, stated forwards: after any poll that inserted anything,
    the column equals MAX(case_entries.entry_at). Exercised with an out-of-order batch
    so a max is genuinely computed rather than the last row's value being read off.

    The duplicate re-poll below asserts only that the value is unchanged. It does NOT
    pin the `if counts["new_entries"]` gate, and saying so would be a lie of the kind
    this suite keeps catching: dropping the gate recomputes the SAME value, so no
    assertion on the value can distinguish the two. The gate is a write-volume
    property (34 no-op UPDATEs per run without it), and pinning it would mean counting
    statements rather than reading state. Left unpinned deliberately, and named here
    so the gap is visible rather than assumed covered."""
    conn = _entries_db(tmp_path)
    types, excludes = ["order"], []
    batch = [
        {"date_filed": "2026-03-01", "description": "ORDER one"},
        {"date_filed": "2026-07-04", "description": "ORDER three"},   # the max, in the middle
        {"date_filed": "2026-05-02", "description": "ORDER two"},
    ]
    counts = lit.write_entries(conn, "X", "c", None, batch, types, excludes)
    conn.commit()
    assert counts["new_entries"] == 3
    row = conn.execute(
        "SELECT latest_entry_at, (SELECT MAX(entry_at) FROM case_entries WHERE case_id = 'X')"
        " AS m FROM cases WHERE case_id = 'X'").fetchone()
    assert row["latest_entry_at"] == row["m"] == "2026-07-04T00:00:00"

    # Re-poll the identical window: every insert_ignore is a duplicate, nothing changes.
    again = lit.write_entries(conn, "X", "c", None, batch, types, excludes)
    conn.commit()
    assert again["new_entries"] == 0
    assert conn.execute(
        "SELECT latest_entry_at FROM cases WHERE case_id = 'X'"
    ).fetchone()["latest_entry_at"] == "2026-07-04T00:00:00"
    conn.close()


def test_normalize_state_strips_the_trackers_docket_suffix():
    """`Georgia (1)` and `Georgia (2)` are one jurisdiction with two dockets, not two
    states. The artifact disambiguates inside the state field because it carries one
    row per docket; a per-state view joining the raw value renders two Georgia cells.
    Pinned here because the suffix is the tracker's convention and can only be caught
    at the boundary. The None arm is the config seeds, which carry no state at all."""
    assert lit.normalize_state("Georgia (1)") == "Georgia"
    assert lit.normalize_state("Georgia (2)") == "Georgia"
    assert lit.normalize_state("Georgia") == "Georgia"
    assert lit.normalize_state("New Hampshire") == "New Hampshire"   # a space survives
    assert lit.normalize_state("DC") == "DC"                          # DC is a value, not a gap
    assert lit.normalize_state(None) is None
    assert lit.normalize_state("") is None
    assert lit.normalize_state("   ") is None


def test_upsert_case_writes_state_from_the_seed_and_null_for_a_config_seed(tmp_path):
    """Two arms of one rule, because they fail in opposite directions.

    A tracker seed carries `state` and the row must take it NORMALIZED -- writing the
    raw `Georgia (1)` would push the artifact's row convention into the database and
    every consumer would have to know about it.

    A config seed carries no `state` key at all, and the row must take NULL. Common
    Cause v. DOJ and LWV v. DHS sue federal agencies; they have no state, and the NULL
    is the mechanism that keeps them out of every per-state view rather than an
    absence nobody noticed. `.get()` returning None must not become the string 'None'
    or an empty string, both of which would render as a 32nd jurisdiction."""
    dbp = str(tmp_path / "t.db")
    db.init_db(dbp)
    conn = db.connect(dbp)

    tracker_seed = {"caption": "United States v. Georgia", "docket_number": "5:25-cv-00548",
                    "court": "Middle District of Georgia", "category": "voter-data",
                    "state": "Georgia (1)", "notes": "n"}
    lit.upsert_case(conn, "72053306", tracker_seed, None)

    config_seed = {"caption": "Common Cause v. U.S. Department of Justice",
                   "docket_number": "1:26-cv-01352", "court": "D.D.C.",
                   "category": "voter-data", "notes": "n"}
    lit.upsert_case(conn, "73218916", config_seed, None)
    conn.commit()

    states = {r["case_id"]: r["state"]
              for r in conn.execute("SELECT case_id, state FROM cases").fetchall()}
    assert states == {"72053306": "Georgia", "73218916": None}
    conn.close()


def test_state_is_rewritten_on_the_reuse_path_not_only_on_first_resolve(tmp_path):
    """`state` must sit in the UNCONDITIONAL row dict, not behind `if docket is not None`.

    This is the invariant the whole column design rests on: the backfill is one-time
    only because the collector rewrites `state` on every seeded row on every run. Reuse
    (docket=None) IS the steady state -- both 2026-08-10 runs polled 34 dockets and
    printed `incremental` for all 34, with zero resolves -- so a write behind that guard
    would land on first resolve and never again. A tracker rename, or a change to
    normalize_state, would then diverge from the database silently and permanently.
    That is the write-once shape `status` already has (see tools/status_audit), and it
    is the wrong shape for a column added to render a per-state view.

    The discrimination was demonstrated, not assumed: with the write moved inside the
    guard this fails on the last assertion below (`'Georgia' != 'Georgia Corrected'`).
    `test_normalize_state_...` keeps passing under either placement, since it never
    calls upsert_case. `test_upsert_case_writes_state_...` also fails under the guard,
    but only INCIDENTALLY -- it happens to pass `docket=None`, so it exercises the reuse
    path by accident of how it was written rather than by anything it asserts, and it
    would stop covering this the moment someone handed it a docket. That is the argument
    for a dedicated test rather than leaning on the coverage next door.

    Two arms, since a rename must both apply and normalize: `Georgia (1)` -> `Georgia (2)`
    is the same jurisdiction and must stay `Georgia` (the value cannot go stale as
    `Georgia` for the wrong reason), and a genuine relabel must actually move."""
    dbp = str(tmp_path / "t.db")
    db.init_db(dbp)
    conn = db.connect(dbp)

    seed = {"caption": "United States v. Georgia", "docket_number": "5:25-cv-00548",
            "court": "Middle District of Georgia", "category": "voter-data",
            "state": "Georgia (1)", "notes": "n"}
    docket = {"case_name": "United States v. RAFFENSPERGER", "date_filed": "2025-12-18",
              "date_terminated": "2026-01-23", "absolute_url": "/docket/1/us-v-ga/"}
    lit.upsert_case(conn, "72053306", seed, docket)      # first resolve
    conn.commit()

    state = lambda: conn.execute(
        "SELECT state FROM cases WHERE case_id = '72053306'").fetchone()["state"]
    assert state() == "Georgia"

    # The tracker's suffix moves on a refile; the jurisdiction does not. Reuse path.
    lit.upsert_case(conn, "72053306", {**seed, "state": "Georgia (2)"}, None)
    conn.commit()
    assert state() == "Georgia"

    # A genuine relabel on the reuse path must reach the column. This is the assertion
    # that fails if the write sits behind the docket guard.
    lit.upsert_case(conn, "72053306", {**seed, "state": "Georgia Corrected"}, None)
    conn.commit()
    assert state() == "Georgia Corrected"
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


def test_mark_unchanged_under_reset_recovery(monkeypatch):
    """The same :445 invariant, but on a remote-shaped _Conn so db.recover takes the
    RESET path -- the only path that actually changed at :445. The local-SQLite test
    above exercises recover()'s rollback fallthrough; this one pins the mark under
    reset(), the site where a wrong call would corrupt the high-water mark.

    reset() models a reopen: the open transaction is abandoned (nothing pending
    lands) while committed rows persist. The stub returns the same in-memory store
    after a rollback, which reproduces exactly that -- committed state kept, the
    write block's transaction gone -- without needing a live Turso stream."""
    real = libsql.connect(":memory:")
    real.executescript(db._schema_for_remote(db.SCHEMA_PATH))
    real.commit()

    def reopen():
        real.rollback()   # abandon the open txn, as a fresh connection would; keep committed rows
        return real

    conn = db._Conn(real, reopen=reopen)
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
    # recover() went through reset() (no crash), and the mark never advanced.
    assert conn._pending is False
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
    # main() now ends with the status refresh (handoff 27), which reaches the HTTP
    # layer directly rather than through resolve_docket/poll_entries. Without this
    # stub the three rows this test creates are all due, and the pass issues real
    # requests at the fake base -- they fail, per-row isolation swallows them, and the
    # test still passes while spending ~87s in retry backoff against a live DNS lookup.
    refreshed = []

    def fake_get(url, params=None, headers=None, timeout=None, throttle=0.0):
        refreshed.append(url)
        return {"id": url.rstrip("/").split("/")[-1], "date_terminated": None}

    monkeypatch.setattr(common, "http_get", fake_get)

    assert lit.main() == 0
    conn = db.connect(str(tmp_path / "m.db"))
    marked = conn.execute("SELECT COUNT(*) FROM cases WHERE entries_synced_at IS NOT NULL").fetchone()[0]
    nullmark = conn.execute("SELECT COUNT(*) FROM cases WHERE entries_synced_at IS NULL").fetchone()[0]
    assert (marked, nullmark) == (2, 1)
    # Every row carries a receipt and NONE of them costs a refresh request. This
    # assertion was `== 3` until 2026-08-15 and pinned the handoff-27 deferral: a row
    # resolved this run used to land with status_checked_at NULL, which made it
    # immediately due, so the refresh re-read the very docket the resolve had just
    # read. upsert_case now stamps the receipt in its docket branch, so all three are
    # already fresh and the pass has nothing to do.
    #
    # Zero, not one: all three seeds carry docket_number and court_id and the fake
    # resolve returns a docket for each, so all three take the branch that stamps. The
    # third row's NULL in the line above is `entries_synced_at` -- a DEFERRED WALK, not
    # an unresolved docket. Those two NULLs mean different things and this test holds
    # both, which is exactly how they get conflated.
    assert len(refreshed) == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM cases WHERE status_checked_at IS NULL").fetchone()[0] == 0
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


# --------------------------------------------------------------------------- #
# Daily-cap abort (handoff 8): don't retry-storm a spent cap
# --------------------------------------------------------------------------- #
def test_collect_case_reraises_daily_cap_mark_unmoved(tmp_path, monkeypatch):
    """A daily-cap 429 during the poll propagates (for main to abort on) rather than
    being swallowed as a skip, and the mark stays put / the txn rolls back."""
    dbp = str(tmp_path / "t.db")
    db.init_db(dbp)
    conn = db.connect(dbp)
    lit.register_sources(conn)
    conn.execute(
        "INSERT INTO cases (case_id, caption, court, docket_number, entries_synced_at) "
        "VALUES ('555','United States v. Marked','District of X','1:25-cv-09999','2026-05-05T00:00:00Z')")
    conn.commit()
    seed = {"caption": "United States v. Marked", "docket_number": "1:25-cv-09999",
            "court": "District of X", "court_id": "xxd", "category": "voter-data", "notes": "n"}

    def raise_cap(*a, **k):
        raise common.RateBudgetExhausted(41134)

    monkeypatch.setattr(lit, "poll_entries", raise_cap)   # mark set -> incremental path polls
    with pytest.raises(common.RateBudgetExhausted):
        lit.collect_case(conn, "base", {}, seed, [], [], bootstrap_requests=30)
    mark = conn.execute("SELECT entries_synced_at FROM cases WHERE case_id='555'").fetchone()[0]
    assert mark == "2026-05-05T00:00:00Z"             # unmoved
    conn.close()


def test_main_aborts_on_daily_cap_and_exits_zero(tmp_path, monkeypatch):
    """main() breaks the seed loop on the cap and still returns 0 (the exit-0 invariant
    that keeps executive/news/state running), leaving later seeds untouched."""
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
        "max_bootstrap_requests_per_run": 30, "seed_cases": seeds,
    }}
    monkeypatch.setattr(config, "load_sources", lambda *a, **k: fake_sources)
    monkeypatch.setattr(lit, "load_tracker_seeds", lambda *a, **k: [])

    def fake_resolve(base, headers, dn, court_id):
        return {"id": 100 + int(dn[-1]), "absolute_url": f"/docket/{dn}/",
                "date_filed": "2026-01-01", "date_terminated": None, "case_name": f"US v {dn}"}

    calls = {"n": 0}

    def fake_poll(base, headers, cid, since=None, page_counter=None):
        calls["n"] += 1
        if calls["n"] == 2:                            # the SECOND docket hits the cap
            raise common.RateBudgetExhausted(41134)
        return ([], "2026-10-10T00:00:00Z")

    monkeypatch.setattr(lit, "resolve_docket", fake_resolve)
    monkeypatch.setattr(lit, "poll_entries", fake_poll)

    assert lit.main() == 0                             # aborted, but exit 0
    assert calls["n"] == 2                             # broke at seed 2; seed 3 never polled
    conn = db.connect(str(tmp_path / "m.db"))
    assert conn.execute("SELECT COUNT(*) FROM cases WHERE case_id='102'").fetchone()[0] == 0  # seed 3 untouched
    conn.close()


if __name__ == "__main__":
    test_substantive_promoted()
    test_noise_excluded()
    test_helpers()
    print("ok")


# --------------------------------------------------------------------------- #
# Status refresh (handoff 27): `status` is otherwise write-once
# --------------------------------------------------------------------------- #
def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _refresh_db(tmp_path, rows):
    """A cases table seeded with (case_id, status, status_checked_at, updated_at)."""
    dbp = str(tmp_path / "r.db")
    db.init_db(dbp)
    conn = db.connect(dbp)
    for case_id, status, checked, updated in rows:
        conn.execute(
            "INSERT INTO cases (case_id, caption, status, status_checked_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)", (case_id, f"case {case_id}", status, checked, updated))
    conn.commit()
    return conn


def _fake_get(recorder, date_terminated=None):
    def fake(url, params=None, headers=None, timeout=None, throttle=0.0):
        recorder.append(url)
        return {"id": url.rstrip("/").split("/")[-1], "date_terminated": date_terminated}
    return fake


def test_refresh_selection_excludes_terminated_and_fresh(tmp_path):
    """The refresh set is non-terminated AND stale. `terminated` is absorbing on the
    court's clock, so re-reading it would be pure waste -- that exclusion is what keeps
    the pass at ~+17% on the daily draw rather than doubling it."""
    conn = _refresh_db(tmp_path, [
        ("100", "terminated", None,     None),   # terminated -> never due, even unchecked
        ("200", "pending",    _iso(1),  None),   # checked an hour ago -> not yet stale
        ("300", "pending",    _iso(25), None),   # checked 25h ago -> due
        ("400", "pending",    None,     None),   # never checked -> due
        ("500", None,         None,     None),   # NULL status is unresolved, not terminated
    ])
    due = [r["case_id"] for r in lit.due_for_status_refresh(conn, _iso(24))]
    assert "100" not in due and "200" not in due
    assert set(due) == {"300", "400", "500"}
    conn.close()


def test_refresh_selection_orders_never_checked_first(tmp_path):
    """Ordering is the difference between a capped pass that makes progress and one
    that re-walks the same head of the list every run. Never-checked first, then
    oldest-checked."""
    conn = _refresh_db(tmp_path, [
        ("100", "pending", _iso(30), None),
        ("200", "pending", None,     None),
        ("300", "pending", _iso(99), None),
    ])
    assert [r["case_id"] for r in lit.due_for_status_refresh(conn, _iso(24))] == ["200", "300", "100"]
    conn.close()


def test_refresh_flip_to_terminated_writes_all_three_columns(tmp_path, monkeypatch):
    conn = _refresh_db(tmp_path, [("100", "pending", None, "2000-01-01T00:00:00Z")])
    calls = []
    monkeypatch.setattr(common, "http_get", _fake_get(calls, date_terminated="2026-07-23"))

    counts = lit.refresh_status(conn, "https://x/api", {}, _iso(24), 40)

    assert calls == ["https://x/api/dockets/100/"]
    assert counts["checked"] == 1 and counts["changed"] == 1 and counts["failed"] == 0
    row = conn.execute("SELECT status, status_checked_at, updated_at FROM cases").fetchone()
    assert row["status"] == "terminated"
    assert row["status_checked_at"] is not None
    assert row["updated_at"] != "2000-01-01T00:00:00Z"   # a real change stamps updated_at
    conn.close()


def test_refresh_noop_moves_receipt_but_not_updated_at(tmp_path, monkeypatch):
    """The one most likely to regress and the most expensive when it does. A no-op
    must move `status_checked_at` and leave `updated_at` alone: stamping it on 33
    unchanged rows a day would make every row look freshly touched and destroy the
    instrument that exposed both the starvation (handoff 25) and the orphan class."""
    conn = _refresh_db(tmp_path, [("100", "pending", None, "2000-01-01T00:00:00Z")])
    monkeypatch.setattr(common, "http_get", _fake_get([], date_terminated=None))

    counts = lit.refresh_status(conn, "https://x/api", {}, _iso(24), 40)

    assert counts["checked"] == 1 and counts["changed"] == 0
    row = conn.execute("SELECT status, status_checked_at, updated_at FROM cases").fetchone()
    assert row["status"] == "pending"
    assert row["status_checked_at"] is not None           # receipt written on the no-op
    assert row["updated_at"] == "2000-01-01T00:00:00Z"    # ... and updated_at untouched
    conn.close()


def test_refresh_skips_non_numeric_case_id_without_a_request(tmp_path, monkeypatch):
    """A B2-only seed has no docket_number, so collect_case slugifies its caption and
    there is nothing to look up. All 40 rows are numeric today, but that is a property
    of today's data, not of the schema."""
    conn = _refresh_db(tmp_path, [
        ("common-cause-v-doj", "pending", None, None),
        ("100",                "pending", None, None),
    ])
    calls = []
    monkeypatch.setattr(common, "http_get", _fake_get(calls))

    counts = lit.refresh_status(conn, "https://x/api", {}, _iso(24), 40)

    assert calls == ["https://x/api/dockets/100/"]        # the slug was never requested
    assert counts["due"] == 1 and counts["skipped"] == 1 and counts["checked"] == 1
    slug = conn.execute(
        "SELECT status_checked_at FROM cases WHERE case_id = 'common-cause-v-doj'").fetchone()
    assert slug["status_checked_at"] is None              # skipped, not silently stamped
    conn.close()


def test_refresh_respects_the_per_run_cap(tmp_path, monkeypatch):
    """The cap bites the FRESHEST rows, because ordering put the least-fresh first."""
    fresh_mark = _iso(30)
    conn = _refresh_db(tmp_path, [
        ("100", "pending", None,       None),
        ("200", "pending", _iso(99),   None),
        ("300", "pending", fresh_mark, None),
    ])
    calls = []
    monkeypatch.setattr(common, "http_get", _fake_get(calls))

    counts = lit.refresh_status(conn, "https://x/api", {}, _iso(24), 2)

    assert calls == ["https://x/api/dockets/100/", "https://x/api/dockets/200/"]
    assert counts["due"] == 3 and counts["checked"] == 2 and counts["capped"] is True
    # 300 was due but deferred: its receipt is untouched, so next run still sees it.
    left = conn.execute("SELECT status_checked_at FROM cases WHERE case_id = '300'").fetchone()
    assert left["status_checked_at"] == fresh_mark
    conn.close()


def test_refresh_rate_budget_breaks_cleanly_mid_pass(tmp_path, monkeypatch):
    """A cap hit mid-pass stops the loop, keeps what already committed, and does NOT
    raise -- main()'s exit-0 invariant keeps executive/news/state running."""
    conn = _refresh_db(tmp_path, [
        ("100", "pending", None, None),
        ("200", "pending", None, None),
        ("300", "pending", None, None),
    ])
    calls = []

    def fake(url, params=None, headers=None, timeout=None, throttle=0.0):
        calls.append(url)
        if len(calls) > 1:
            raise common.RateBudgetExhausted(46)
        return {"id": "100", "date_terminated": "2026-07-23"}

    monkeypatch.setattr(common, "http_get", fake)
    counts = lit.refresh_status(conn, "https://x/api", {}, _iso(24), 40)

    assert counts["aborted"] is True
    assert counts["checked"] == 1 and counts["changed"] == 1
    # The one that got through is committed; the rest keep NULL receipts and, being
    # the least fresh, are exactly what next run's ordering picks up first.
    assert conn.execute(
        "SELECT status FROM cases WHERE case_id = '100'").fetchone()["status"] == "terminated"
    assert conn.execute(
        "SELECT COUNT(*) c FROM cases WHERE status_checked_at IS NULL").fetchone()["c"] == 2
    conn.close()


def test_refresh_failure_is_isolated_to_the_row(tmp_path, monkeypatch):
    """One bad lookup costs that row and nothing else -- the pass carries on."""
    conn = _refresh_db(tmp_path, [
        ("100", "pending", None, None),
        ("200", "pending", None, None),
    ])
    calls = []

    def fake(url, params=None, headers=None, timeout=None, throttle=0.0):
        calls.append(url)
        if "100" in url:
            raise RuntimeError("GET failed after 4 attempts")
        return {"id": "200", "date_terminated": "2026-07-14"}

    monkeypatch.setattr(common, "http_get", fake)
    counts = lit.refresh_status(conn, "https://x/api", {}, _iso(24), 40)

    assert counts["failed"] == 1 and counts["checked"] == 1 and counts["changed"] == 1
    assert conn.execute(
        "SELECT status FROM cases WHERE case_id = '200'").fetchone()["status"] == "terminated"
    conn.close()


def test_main_returns_zero_when_the_refresh_hits_the_cap(tmp_path, monkeypatch):
    """End to end: the refresh runs after the seed loop, and a cap hit inside it still
    exits 0 so executive/news/state keep running."""
    dbp = str(tmp_path / "m.db")
    monkeypatch.setattr(config, "load_env", lambda *a, **k: None)
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "DB_PATH", dbp)
    monkeypatch.setenv("COURTLISTENER_TOKEN", "test-token")
    monkeypatch.setattr(lit, "load_tracker_seeds", lambda *a, **k: [])
    monkeypatch.setattr(lit, "resolve_docket", lambda *a, **k: None)   # config seeds don't bind

    db.init_db(dbp)
    seed = db.connect(dbp)
    seed.execute("INSERT INTO cases (case_id, caption, status) VALUES ('100', 'c', 'pending')")
    seed.commit()
    seed.close()

    def fake(url, params=None, headers=None, timeout=None, throttle=0.0):
        raise common.RateBudgetExhausted(46)

    monkeypatch.setattr(common, "http_get", fake)
    assert lit.main() == 0


def test_main_skips_the_refresh_when_the_seed_loop_hit_the_cap(tmp_path, monkeypatch):
    """The budget is already spent, so every refresh request would 429 immediately.
    Tracked with a flag rather than inferred from the loop's end state."""
    dbp = str(tmp_path / "m.db")
    monkeypatch.setattr(config, "load_env", lambda *a, **k: None)
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "DB_PATH", dbp)
    monkeypatch.setenv("COURTLISTENER_TOKEN", "test-token")
    monkeypatch.setattr(lit, "load_tracker_seeds", lambda *a, **k: [])

    def cap_out(*a, **k):
        raise common.RateBudgetExhausted(46)

    monkeypatch.setattr(lit, "resolve_docket", cap_out)
    called = []
    monkeypatch.setattr(lit, "refresh_status", lambda *a, **k: called.append(1))

    assert lit.main() == 0
    assert called == []      # refresh never attempted


def test_a_raising_refresh_pass_does_not_cost_the_cycle(tmp_path, monkeypatch, capsys):
    """The exit-0 invariant at the one line that did not honour it.

    refresh_status's FIRST statement is due_for_status_refresh's SELECT, which runs
    before any per-row handler exists. A raise there left main() non-zero, and since
    the collectors are sequential lines in one `-e` step that costs export and the data
    commit for the whole cycle -- a lost run that looks like an empty diff. The seed
    loop has already committed per case, so the refresh must fail alone."""
    dbp = str(tmp_path / "m.db")
    monkeypatch.setattr(config, "load_env", lambda *a, **k: None)
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "DB_PATH", dbp)
    monkeypatch.setenv("COURTLISTENER_TOKEN", "test-token")
    monkeypatch.setattr(lit, "load_tracker_seeds", lambda *a, **k: [])
    monkeypatch.setattr(lit, "resolve_docket", lambda *a, **k: None)

    def boom(*a, **k):
        # The realistic shape: the SELECT itself fails (missing column / dead stream).
        raise ValueError("no such column: status_checked_at")

    monkeypatch.setattr(lit, "refresh_status", boom)

    assert lit.main() == 0
    err = capsys.readouterr().err
    assert "status refresh pass failed, skipped" in err
    assert "no such column: status_checked_at" in err   # the cause survives to the log


def test_the_real_selection_failure_is_caught_not_just_a_stub(tmp_path, monkeypatch, capsys):
    """The same guard exercised through the REAL refresh_status, with the SELECT
    failing -- so this still passes if refresh_status is ever restructured such that a
    stubbed-out function no longer represents the failure."""
    dbp = str(tmp_path / "m.db")
    monkeypatch.setattr(config, "load_env", lambda *a, **k: None)
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "DB_PATH", dbp)
    monkeypatch.setenv("COURTLISTENER_TOKEN", "test-token")
    monkeypatch.setattr(lit, "load_tracker_seeds", lambda *a, **k: [])
    monkeypatch.setattr(lit, "resolve_docket", lambda *a, **k: None)

    def bad_select(conn, stale_before):
        raise ValueError("Hrana: stream not found")

    monkeypatch.setattr(lit, "due_for_status_refresh", bad_select)

    assert lit.main() == 0
    assert "status refresh pass failed, skipped" in capsys.readouterr().err


def test_config_then_tracker_seed_is_one_row_last_writer_wins(tmp_path, monkeypatch):
    """The charter's exit condition, pinned at its seam (handoff 70).

    config/sources.yaml may carry a circuit successor the UW tracker trails. That
    bend is only safe because it SELF-NEUTRALIZES: litigation.main() iterates
    `config_seeds + tracker_seeds`, so the tracker writes last, and `cases.case_id`
    is the CourtListener docket id, so both seeds land on ONE row rather than two.
    When UW rewrites the state row its values simply overwrite the config seed's.

    WHAT THIS PROTECTS: a refactor that reorders those two lists -- or keys the
    reuse lookup differently -- silently breaks the self-neutralization, and the
    symptom would be a stale config value winning over the tracker (e.g. a `state`
    that no longer matches, dropping the row off /campaign) with nothing red.

    It also pins the free-text join key. The reuse lookup is
    `WHERE docket_number = ? AND court = ?` on `court`, NOT `court_id`, so the
    config seed has to spell the court exactly as UW does ("Second Circuit") or the
    tracker's later pass misses and spends a second resolve on a docket already
    held. The assertion is that resolve is called ONCE across both seeds.
    """
    dbp = str(tmp_path / "t.db")
    db.init_db(dbp)
    conn = db.connect(dbp)
    lit.register_sources(conn)
    conn.commit()

    calls = {"n": 0}

    def fake_resolve(base, headers, dn, court_id):
        calls["n"] += 1
        assert (dn, court_id) == ("26-2064", "ca2")
        return {"id": 73686333, "absolute_url": "/docket/73686333/usa-v-thomas/",
                "date_filed": "2026-07-28", "date_terminated": None,
                "case_name": "United States of America v. Thomas"}

    monkeypatch.setattr(lit, "resolve_docket", fake_resolve)
    monkeypatch.setattr(lit, "poll_entries", lambda *a, **k: ([], None))

    # The config seed as it now ships: UW's court spelling, its own state.
    config_seed = {
        "caption": "United States of America v. Thomas", "docket_number": "26-2064",
        "court": "Second Circuit", "court_id": "ca2", "category": "voter-data",
        "state": "Connecticut", "notes": "seeded 2026-08-14; remove on UW rewrite",
    }
    # The artifact row UW will eventually publish. Same docket, same court spelling.
    # `state` carries the tracker's disambiguation suffix so the assertion also shows
    # normalize_state ran on the WINNING write. `category` is deliberately made to
    # differ from the config seed's -- in production both read "voter-data", which
    # would make the assertion pass whichever write landed and pin nothing. A
    # discriminator is the only way this test can tell the order it exists to pin.
    tracker_seed = dict(config_seed, state="Connecticut (1)",
                        category="registration-law",
                        notes="Claims: Civil Rights Act 1960 | Status: appeal docketed")

    for seed in [config_seed] + [tracker_seed]:        # main()'s order, literally
        lit.collect_case(conn, "base", {}, seed, [], [], bootstrap_requests=5)

    # `notes` is deliberately absent here: it lands on the B2 item, not the case row.
    rows = conn.execute("SELECT case_id, court, docket_number, state, category "
                        "FROM cases").fetchall()
    assert len(rows) == 1                              # ONE row, not two
    assert str(rows[0]["case_id"]) == "73686333"       # keyed on the CL docket id
    assert rows[0]["state"] == "Connecticut"           # suffix stripped on the winning write
    assert rows[0]["category"] == "registration-law"   # the TRACKER's value: it wrote LAST
    assert calls["n"] == 1                             # reuse hit: no second resolve spent
    conn.close()


def test_reuse_lookup_misses_when_the_court_string_disagrees(tmp_path, monkeypatch):
    """The negative half, and the reason the config comment insists on UW's spelling.

    Spell the court differently between the two seeds and the reuse lookup -- which
    matches on the free-text `court` -- misses, so the second pass resolves again.
    Same single row in the end (the docket id is the PK either way), but a request
    was spent to learn what the first pass already knew.
    """
    dbp = str(tmp_path / "t.db")
    db.init_db(dbp)
    conn = db.connect(dbp)
    lit.register_sources(conn)
    conn.commit()
    calls = {"n": 0}

    def fake_resolve(base, headers, dn, court_id):
        calls["n"] += 1
        return {"id": 73686333, "absolute_url": "/docket/73686333/usa-v-thomas/",
                "date_filed": "2026-07-28", "date_terminated": None,
                "case_name": "United States of America v. Thomas"}

    monkeypatch.setattr(lit, "resolve_docket", fake_resolve)
    monkeypatch.setattr(lit, "poll_entries", lambda *a, **k: ([], None))
    base_seed = {"caption": "US v. Thomas", "docket_number": "26-2064",
                 "court_id": "ca2", "category": "voter-data", "state": "Connecticut",
                 "notes": "n"}
    for court in ("2nd Cir.", "Second Circuit"):       # the mistake, then UW's form
        lit.collect_case(conn, "base", {}, dict(base_seed, court=court), [], [],
                         bootstrap_requests=5)

    assert len(conn.execute("SELECT case_id FROM cases").fetchall()) == 1
    assert calls["n"] == 2                             # the miss cost a second resolve
    conn.close()
