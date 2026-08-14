"""Suite for the latest_entry_at repair (scripts/repair_latest_entry.py).

Offline and deterministic: temp SQLite DB, no network, never touches Turso. main() is
NOT exercised -- it calls config.load_env()/db.connect(), which route to production
Turso when the env is set. Tests drive the conn-parameterized run()/find_drift()
against a temp DB.

This script asserts nothing external -- it copies a value the database already
computes from rows the database already holds -- so unlike the other two backfills
there is no refusal gate to test. What matters instead is that it finds the right
rows, leaves the right rows alone, and is a genuine no-op on a clean table.

Run:  pytest tests/test_repair_latest_entry.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

import db  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "repair_latest_entry", os.path.join(REPO, "scripts", "repair_latest_entry.py"))
repair = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(repair)


def _conn():
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    db.init_db(path)
    return db.connect(path)


def _case(conn, case_id, stored, entries):
    conn.execute(
        "INSERT INTO cases (case_id, caption, status, court, docket_number, latest_entry_at)"
        " VALUES (?, ?, 'pending', 'D. Test', ?, ?)",
        (case_id, f"case {case_id}", f"1:25-cv-{case_id}", stored))
    for e in entries:
        conn.execute(
            "INSERT INTO case_entries (case_id, entry_at, description) VALUES (?, ?, 'x')",
            (case_id, e))
    conn.commit()


def _stored(conn):
    return {r["case_id"]: r["latest_entry_at"]
            for r in conn.execute("SELECT case_id, latest_entry_at FROM cases").fetchall()}


def _populated():
    """One drifted row in the West Virginia shape, one already correct."""
    conn = _conn()
    _case(conn, "700", "2026-05-15", ["2026-05-15", "2026-07-13", "2026-08-06"])   # behind
    _case(conn, "800", "2026-08-10", ["2026-07-01", "2026-08-10"])                 # correct
    return conn


def test_finds_only_the_drifted_row():
    conn = _populated()
    rows = repair.find_drift(conn)
    assert [r["case_id"] for r in rows] == ["700"]
    assert rows[0]["stored"] == "2026-05-15"
    assert rows[0]["derived"] == "2026-08-06"
    assert rows[0]["days"] == 83          # the real WV drift, to the day
    assert rows[0]["n_entries"] == 3
    conn.close()


def test_apply_repairs_the_drifted_row_and_leaves_the_correct_one_untouched():
    conn = _populated()
    rows, fixed = repair.run(conn, apply=True)
    conn.commit()
    assert fixed == len(rows) == 1
    assert _stored(conn) == {"700": "2026-08-06", "800": "2026-08-10"}
    conn.close()


def test_dry_run_writes_nothing():
    conn = _populated()
    rows, fixed = repair.run(conn, apply=False)
    assert fixed == 0 and len(rows) == 1
    assert _stored(conn) == {"700": "2026-05-15", "800": "2026-08-10"}
    conn.close()


def test_apply_is_idempotent():
    """Second run finds nothing, which is also the standing-clean condition the
    coverage_audit alarm reads."""
    conn = _populated()
    repair.run(conn, apply=True)
    conn.commit()
    rows, fixed = repair.run(conn, apply=True)
    conn.commit()
    assert rows == [] and fixed == 0
    assert _stored(conn) == {"700": "2026-08-06", "800": "2026-08-10"}
    conn.close()


def test_a_case_with_no_entries_is_surfaced_not_skipped():
    """LEFT JOIN, not INNER. A stored value with no entries behind it is a different
    defect from drift, and it must appear rather than vanish. The repair sets it to
    NULL, which is what the derivation says -- there is no entry to point at."""
    conn = _conn()
    _case(conn, "900", "2026-08-06", [])
    rows = repair.find_drift(conn)
    assert len(rows) == 1 and rows[0]["derived"] is None and rows[0]["days"] is None
    repair.run(conn, apply=True)
    conn.commit()
    assert _stored(conn) == {"900": None}
    conn.close()


def test_drift_is_reported_worst_first():
    """The dry-run table is read by a human deciding whether to apply, so the biggest
    disagreement has to be the first line rather than buried by case_id order."""
    conn = _conn()
    _case(conn, "100", "2026-08-03", ["2026-08-04"])                  # +1d
    _case(conn, "200", "2026-05-15", ["2026-08-06"])                  # +83d
    _case(conn, "300", "2026-07-15", ["2026-08-12"])                  # +28d
    assert [r["days"] for r in repair.find_drift(conn)] == [83, 28, 1]
    conn.close()
