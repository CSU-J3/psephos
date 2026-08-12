"""Suite for the supersession backfill (scripts/backfill_supersession.py).

Offline and deterministic: temp SQLite DB, no network, never touches Turso. main() is
NOT exercised (it calls config.load_env()/db.connect(), which route to production Turso
when the env is set). Tests drive the conn-parameterized run()/verify()/apply_links()
against a temp DB, so the suite can never write to the remote.

The refusal cases matter more than the happy path: a partial mapping is worse than none.

Run:  pytest tests/test_supersession.py
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
    "backfill_supersession", os.path.join(REPO, "scripts", "backfill_supersession.py"))
backfill = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backfill)

# Two valid pairs, shaped like the real ones (district terminated -> circuit live).
PAIRS = [
    ("100", "1:25-cv-01", "900", "26-1"),
    ("200", "2:25-cv-02", "901", "26-2"),
]


def _conn():
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    db.init_db(path)
    return db.connect(path)


def _case(conn, case_id, status, docket):
    conn.execute(
        "INSERT INTO cases (case_id, caption, status, docket_number) VALUES (?, ?, ?, ?)",
        (case_id, f"case {case_id}", status, docket),
    )
    conn.commit()


def _seed_valid(conn, pairs=PAIRS):
    for src_id, src_dock, tgt_id, tgt_dock in pairs:
        _case(conn, src_id, "terminated", src_dock)
        _case(conn, tgt_id, "pending", tgt_dock)


def _superseded(conn):
    return {r["case_id"]: r["superseded_by"]
            for r in conn.execute("SELECT case_id, superseded_by FROM cases").fetchall()}


# --- happy path -------------------------------------------------------------

def test_apply_writes_exactly_the_pairs():
    conn = _conn()
    _seed_valid(conn)
    errs, linked = backfill.run(conn, PAIRS, apply=True)
    conn.commit()
    assert errs == [] and linked == 2
    s = _superseded(conn)
    assert s["100"] == "900" and s["200"] == "901"   # district rows point forward
    assert s["900"] is None and s["901"] is None       # circuit rows untouched
    conn.close()


def test_refile_pair_links_no_court_assumption():
    """A refile links exactly like a circuit appeal: source and target are BOTH district
    courts with district-format dockets. Proves the guards carry no court assumption --
    the claim the Georgia venue refile (handoff 14) rests on."""
    conn = _conn()
    refile = [("300", "5:25-cv-00548", "301", "1:26-cv-00485")]  # M.D. Ga. -> N.D. Ga. shape
    _case(conn, "300", "terminated", "5:25-cv-00548")
    _case(conn, "301", "pending", "1:26-cv-00485")
    errs, linked = backfill.run(conn, refile, apply=True)
    conn.commit()
    assert errs == [] and linked == 1
    assert _superseded(conn)["300"] == "301"
    assert _superseded(conn)["301"] is None   # successor untouched
    conn.close()


def test_dry_run_writes_nothing():
    conn = _conn()
    _seed_valid(conn)
    errs, linked = backfill.run(conn, PAIRS, apply=False)
    assert errs == [] and linked == 0
    assert all(v is None for v in _superseded(conn).values())
    conn.close()


# --- refusals (the point of the unit) ---------------------------------------

def test_missing_target_refuses_whole_run():
    conn = _conn()
    _seed_valid(conn)
    conn.execute("DELETE FROM cases WHERE case_id = '901'")   # second pair's target gone
    conn.commit()
    errs, linked = backfill.run(conn, PAIRS, apply=True)
    assert linked == 0 and any("901" in e and "missing" in e for e in errs)
    # refusal-first: the VALID first pair is NOT written either
    assert all(v is None for v in _superseded(conn).values())
    conn.close()


def test_non_terminated_source_refuses():
    conn = _conn()
    _seed_valid(conn)
    conn.execute("UPDATE cases SET status = 'pending' WHERE case_id = '100'")
    conn.commit()
    errs, linked = backfill.run(conn, PAIRS, apply=True)
    assert linked == 0 and any("100" in e and "terminated" in e for e in errs)
    assert all(v is None for v in _superseded(conn).values())
    conn.close()


def test_terminated_target_refuses():
    conn = _conn()
    _seed_valid(conn)
    conn.execute("UPDATE cases SET status = 'terminated' WHERE case_id = '900'")
    conn.commit()
    errs, linked = backfill.run(conn, PAIRS, apply=True)
    assert linked == 0 and any("900" in e and "terminated" in e for e in errs)
    assert all(v is None for v in _superseded(conn).values())
    conn.close()


def test_docket_mismatch_refuses():
    conn = _conn()
    _seed_valid(conn)
    conn.execute("UPDATE cases SET docket_number = '26-999' WHERE case_id = '900'")
    conn.commit()
    errs, linked = backfill.run(conn, PAIRS, apply=True)
    assert linked == 0 and any("900" in e and "docket" in e for e in errs)
    assert all(v is None for v in _superseded(conn).values())
    conn.close()


# --- the dry-run display, which IS the review gate --------------------------
# describe() replaced a printout of the PAIRS constant (handoff 36). These assert it
# shows queried values rather than asserted ones -- the property that makes the gate a
# check instead of an echo. A regression here silently restores a dry-run that approves
# anything.


def test_describe_shows_the_queried_value_and_marks_the_disagreement():
    conn = _conn()
    _seed_valid(conn)
    conn.execute("UPDATE cases SET docket_number = '26-999', court = 'Ninth Circuit' "
                 "WHERE case_id = '900'")
    conn.commit()
    out = "\n".join(backfill.describe(conn, PAIRS))
    assert "26-999" in out          # the QUERIED docket, which PAIRS does not contain
    assert "!= 26-1" in out         # and the disagreement is marked against the assertion
    assert "Ninth Circuit" in out   # court is in no tuple: proof the row was read, not echoed
    conn.close()


def test_describe_flags_a_missing_row_and_a_live_source():
    conn = _conn()
    _seed_valid(conn)
    conn.execute("DELETE FROM cases WHERE case_id = '901'")          # target gone
    conn.execute("UPDATE cases SET status = 'pending' WHERE case_id = '100'")  # source alive
    conn.commit()
    out = "\n".join(backfill.describe(conn, PAIRS))
    assert "901" in out and "ROW MISSING" in out
    assert "!= terminated" in out   # the guard verify() would refuse on, shown per field
    conn.close()


# --- idempotency ------------------------------------------------------------

def test_idempotent_second_run():
    conn = _conn()
    _seed_valid(conn)
    backfill.run(conn, PAIRS, apply=True)
    conn.commit()
    first = _superseded(conn)
    backfill.run(conn, PAIRS, apply=True)
    conn.commit()
    assert _superseded(conn) == first   # same three values, no drift
    conn.close()


if __name__ == "__main__":
    test_apply_writes_exactly_the_pairs()
    test_refile_pair_links_no_court_assumption()
    test_dry_run_writes_nothing()
    test_missing_target_refuses_whole_run()
    test_non_terminated_source_refuses()
    test_terminated_target_refuses()
    test_docket_mismatch_refuses()
    test_describe_shows_the_queried_value_and_marks_the_disagreement()
    test_describe_flags_a_missing_row_and_a_live_source()
    test_idempotent_second_run()
    print("ok")
