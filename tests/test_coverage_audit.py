"""Suite for tools/coverage_audit.py.

Offline and deterministic: temp SQLite DB, no network, never touches Turso. `main()` is
NOT exercised -- it calls config.load_env()/db.connect(), which route to production
Turso when the env is set. Tests drive the pure helpers plus a conn-parameterized
section-2 scan, so the suite can never read the remote.

Two things here are regression pins rather than ordinary coverage, and they are the
reason this file exists:

  * The DATE STRIP. `held on 10-28-2025` yields the docket-shaped token `28-2025`, and
    both of the parse artifacts this filter removes were reported as coverage gaps
    before it existed. Remove the strip and section 2 grows false entries that read
    exactly like real ones.
  * The UNION seed set. Against the tracker artifact alone the alarm reads 2 rather
    than 0, the two extras being config seeds that are polled every run (handoff 26
    section 3, shipped as a bug once). `test_alarm_artifact_alone_would_false_fire`
    pins that difference so nobody "simplifies" seeded_keys back to one source.

Run:  pytest tests/test_coverage_audit.py
"""
from __future__ import annotations

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

import pytest  # noqa: E402

from tools import coverage_audit as ca  # noqa: E402


class Row(dict):
    """cases rows are sqlite3.Row-like; dict access is all the helpers use."""


def _row(case_id, docket, court, status="terminated", superseded_by=None, caption="X v. Y"):
    return Row(case_id=case_id, docket_number=docket, court=court, status=status,
               superseded_by=superseded_by, caption=caption)


# --- section 1, the reconciliation alarm ------------------------------------

def test_alarm_silent_when_every_unseeded_row_is_linked():
    rows = [_row("1", "1:25-cv-00371", "District of New Hampshire", superseded_by="9"),
            _row("2", "5:25-cv-00548", "Middle District of Georgia")]
    seeded = {("5:25-cv-00548", "Middle District of Georgia")}
    assert ca.unreconciled(rows, seeded) == []


def test_alarm_fires_on_the_ky_va_nm_state():
    """Unseeded and unlinked: the exact state KY/VA/NM sat in for weeks."""
    rows = [_row("72334676", "3:26-cv-00019", "Eastern District of Kentucky")]
    assert [r["case_id"] for r in ca.unreconciled(rows, set())] == ["72334676"]


def test_alarm_join_is_docket_and_court_together():
    """Same docket number at a different court is a different case."""
    rows = [_row("1", "1:25-cv-00371", "District of New Hampshire")]
    assert ca.unreconciled(rows, {("1:25-cv-00371", "District of Maryland")})


def test_alarm_artifact_alone_would_false_fire():
    """The handoff-26 trap, pinned. A config seed is polled every run; drop it from
    the seed set and the alarm reports it as covered by nothing."""
    config_seed = _row("71499795", "1:25-cv-03501", "D.D.C.", status="terminated")
    tracker_only = {("5:25-cv-00548", "Middle District of Georgia")}
    union = tracker_only | {("1:25-cv-03501", "D.D.C.")}
    assert ca.unreconciled([config_seed], tracker_only)   # artifact alone: false fire
    assert ca.unreconciled([config_seed], union) == []    # union: silent, correct


# --- section 2, unresolvable references -------------------------------------

def _scan(conn, held):
    return ca.unresolvable_refs(conn, held)


@pytest.fixture()
def conn(tmp_path):
    import sqlite3
    c = sqlite3.connect(tmp_path / "t.db")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE case_entries (case_id TEXT, description TEXT)")
    yield c
    c.close()


def test_dates_are_stripped_before_matching(conn):
    """`held on 10-28-2025` must not become the docket reference `28-2025`."""
    conn.execute("INSERT INTO case_entries VALUES (?, ?)",
                 ("71499795", "TRANSCRIPT held on 10-28-2025; Issuance: 10-30-2025."))
    assert _scan(conn, set()) == {}


def test_real_unresolvable_reference_is_reported(conn):
    conn.execute("INSERT INTO case_entries VALUES (?, ?)",
                 ("71499795", "USCA Case Number 26-5243 for 113 Notice of Appeal"))
    refs = _scan(conn, set())
    assert list(refs) == ["26-5243"]
    assert refs["26-5243"][0][0] == "71499795"


def test_district_original_behind_a_held_circuit_row_is_reported(conn):
    """The four-gap shape: a circuit row naming a district docket nobody holds."""
    conn.execute("INSERT INTO case_entries VALUES (?, ?)",
                 ("72356732", "CASE OPENED. notice of appeal filed in 2:25-cv-09149-DOC-ADS"))
    assert list(_scan(conn, set())) == ["2:25-cv-09149"]


def test_held_dockets_are_not_reported(conn):
    conn.execute("INSERT INTO case_entries VALUES (?, ?)",
                 ("1", "Originating case number: 3:26-cv-00042-RCY"))
    assert _scan(conn, {"3:26-cv-00042"}) == {}


def test_entry_number_brackets_never_match(conn):
    """[6] and [32] are docket entry references; the year-dash form excludes them."""
    conn.execute("INSERT INTO case_entries VALUES (?, ?)",
                 ("72347022", "re [6] Motion, [32] Response, [106] Order [Entered: 02/2"))
    assert _scan(conn, set()) == {}


# --- section 3, the cert watch list -----------------------------------------

def test_cert_watch_holds_terminated_circuit_rows_only():
    rows = [_row("72347022", "26-1225", "Sixth Circuit"),
            _row("73674243", "26-5657", "Sixth Circuit", status="pending"),
            _row("71453026", "2:25-cv-01481", "Western District of Pennsylvania")]
    assert [r["case_id"] for r in ca.cert_watch(rows)] == ["72347022"]


def test_cert_watch_excludes_a_linked_circuit_row():
    rows = [_row("72347022", "26-1225", "Sixth Circuit", superseded_by="99")]
    assert ca.cert_watch(rows) == []
