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


# --- section 4, the derived-column alarm ------------------------------------
# Shown to FIRE before its zero is trusted. A zero-expected check proves nothing until
# the pattern is demonstrated to match something -- the standing invariant this repo
# wrote after a grep returned 0 because it was wrong, not because the log was clean.


@pytest.fixture()
def drift_conn(tmp_path):
    import sqlite3
    c = sqlite3.connect(tmp_path / "d.db")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE cases (case_id TEXT, court TEXT, docket_number TEXT,"
              " latest_entry_at TEXT)")
    c.execute("CREATE TABLE case_entries (id INTEGER PRIMARY KEY, case_id TEXT, entry_at TEXT)")
    yield c
    c.close()


def _case(conn, case_id, stored, entries):
    conn.execute("INSERT INTO cases VALUES (?,?,?,?)", (case_id, "D. Test", "1:25-cv-1", stored))
    for e in entries:
        conn.execute("INSERT INTO case_entries (case_id, entry_at) VALUES (?,?)", (case_id, e))


def test_derived_drift_silent_when_the_column_equals_its_derivation(drift_conn):
    _case(drift_conn, "A", "2026-08-06", ["2026-05-15", "2026-08-06"])
    assert ca.derived_drift(drift_conn) == []


def test_derived_drift_fires_on_the_west_virginia_shape(drift_conn):
    """The exact defect: the column behind an entry the table already holds. This is
    the assertion that makes the 0 in production meaningful."""
    _case(drift_conn, "72335259", "2026-05-15", ["2026-05-15", "2026-07-13", "2026-08-06"])
    fired = ca.derived_drift(drift_conn)
    assert len(fired) == 1
    assert fired[0]["case_id"] == "72335259"
    assert fired[0]["stored"] == "2026-05-15"
    assert fired[0]["derived"] == "2026-08-06"


def test_derived_drift_fires_when_a_case_has_no_entries_but_a_stored_value(drift_conn):
    """The LEFT JOIN arm. An INNER JOIN would drop this row and the alarm would read
    clean on a case whose column is invented -- a different defect, silently hidden."""
    _case(drift_conn, "B", "2026-08-06", [])
    fired = ca.derived_drift(drift_conn)
    assert len(fired) == 1 and fired[0]["derived"] is None


def test_derived_drift_silent_on_a_case_with_neither(drift_conn):
    """No entries and no stored value agree at NULL, and must not fire."""
    _case(drift_conn, "C", None, [])
    assert ca.derived_drift(drift_conn) == []


# --------------------------------------------------------------------------- #
# Section 2 classifies the KIND of gap (handoff 85)
#
# The list used to be undifferentiated and was read as one candidate, which cost a
# handoff. The distinction was already written down -- in the module docstring --
# and a docstring is not what a reader of the OUTPUT sees. Information in the wrong
# place is not available.
# --------------------------------------------------------------------------- #
def test_a_district_token_named_by_a_circuit_row_is_a_predecessor():
    """We hold the appeal and not the case under it: seed, then supersede FORWARD.
    This is the CA/OR/AZ shape, three real gaps closed in handoff 85."""
    assert ca.classify_ref("2:25-cv-09149", ["Ninth Circuit"], ["26-1232"]) == "predecessor"


def test_a_circuit_token_named_by_a_district_row_is_a_successor():
    """We hold the original and not what continued it: the CT/NY and 26-5243 shape."""
    assert ca.classify_ref("26-5243", ["D.D.C."], ["1:25-cv-03501"]) == "successor"


def test_the_naming_rows_own_docket_in_another_notation_is_noise():
    """Arizona's local format renders the HELD 2:26-cv-00066 as the token 26-00066.
    Surfaced by seeding that very docket, so it is a live shape and not a
    hypothetical -- and it is noise rather than a gap."""
    assert ca.classify_ref("26-00066", ["District of Arizona"], ["2:26-cv-00066"]) == "self-ref"


def test_self_reference_wins_over_the_shape_test():
    """Checked FIRST on purpose: a self-reference can otherwise look like a
    successor (circuit-form token, district naming row) and send a reader hunting
    for a docket the project already holds."""
    assert ca.classify_ref("26-00066", ["District of Arizona"], ["2:26-cv-00066"]) != "successor"


def test_an_ordinary_cross_reference_is_neither():
    """Most of what remains is a filing naming some OTHER case -- a related case, a
    miscellaneous docket. Not a coverage gap of either actionable shape, and it must
    not be labelled as one."""
    assert ca.classify_ref("8:25-cv-01370", ["Central District of California"],
                           ["2:25-cv-09149"]) == "reference"
