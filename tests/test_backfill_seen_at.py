"""R1 step c: bounding when psephos first held a row written before seen_at existed
(scripts/backfill_seen_at.py). On the 00:38Z dump it reproduces the D0's own figures:
2,805 rows exact from their item, 3,213 pinned to one run, 575 in a range of 2-4."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import common  # noqa: E402
import db  # noqa: E402
from scripts import backfill_seen_at as B  # noqa: E402

CASE = "71499795"


def _db(tmp_path):
    dbp = str(tmp_path / "s.db")
    db.init_db(dbp)
    conn = db.connect(dbp)
    conn.execute("INSERT INTO sources (id, name, channel, kind, admiralty_source, admiralty_info)"
                 " VALUES ('courtlistener', 'CL', 'litigation', 'api', 'A', '1')")
    conn.execute("INSERT INTO cases (case_id, caption, status) VALUES (?, 'c', 'pending')", (CASE,))
    conn.commit()
    return conn


def _row(conn, rid, desc, fetched=None, seen_at=None):
    conn.execute("INSERT INTO case_entries (id, case_id, entry_at, description, seen_at) "
                 "VALUES (?, ?, '2026-07-20T00:00:00', ?, ?)", (rid, CASE, desc, seen_at))
    if fetched:
        conn.execute("INSERT INTO items (channel, source_id, source_url, title, fetched_at, "
                     "admiralty_source, admiralty_info, case_id, content_hash) VALUES "
                     "('litigation', 'courtlistener', 'u', 't', ?, 'A', '1', ?, ?)",
                     (fetched, CASE, common.content_hash(CASE, "2026-07-20T00:00:00", desc)))


def test_a_row_is_exact_from_its_item_and_bounded_by_runs_otherwise(tmp_path):
    conn = _db(tmp_path)
    _row(conn, 10, "ORDER one", fetched="2026-07-20T10:00:00Z")
    _row(conn, 11, "Minute entry, no item")                          # same run as 10 and 12
    _row(conn, 12, "ORDER two", fetched="2026-07-20T10:05:00Z")
    _row(conn, 13, "Another minute entry")                            # between two runs
    _row(conn, 14, "ORDER three", fetched="2026-07-20T18:00:00Z")
    _row(conn, 15, "Held since R1", seen_at="2026-09-30T06:30:00Z")   # never touched
    conn.commit()
    got = {rid: (at, by, basis) for rid, at, by, basis in B.plan(conn)}
    assert got[10] == ("2026-07-20T10:00:00Z", None, "item")
    assert got[11] == ("2026-07-20T10:00:00+00:00", "2026-07-20T10:05:00+00:00", "one run")
    assert got[13] == ("2026-07-20T10:00:00+00:00", "2026-07-20T18:00:00+00:00", "2 runs")
    assert 15 not in got


def test_apply_writes_once_and_runs_against_turso_only(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    _row(conn, 10, "ORDER one", fetched="2026-07-20T10:00:00Z")
    _row(conn, 11, "Minute entry, no item")
    conn.commit()
    conn.close()
    real = db.connect
    monkeypatch.setattr(B.config, "load_env", lambda *a, **k: None)
    monkeypatch.setattr(B.db, "connect", lambda *a, **k: real(str(tmp_path / "s.db")))
    with pytest.raises(RuntimeError):
        B.main(["--apply"])                                           # the real guard: local
    monkeypatch.setattr(B.db, "require_remote", lambda *a, **k: None)
    assert B.main(["--apply"]) == 0
    c = real(str(tmp_path / "s.db"))
    assert c.execute("SELECT COUNT(*) FROM case_entries WHERE seen_at IS NULL").fetchone()[0] == 0
    assert tuple(c.execute("SELECT seen_at, seen_by FROM case_entries WHERE id = 10").fetchone()) == \
        ("2026-07-20T10:00:00Z", None)
    assert B.plan(c) == []                                            # idempotent


def _obj(conn, cl_id, desc=None, first=None, held=1):
    conn.execute("INSERT INTO cl_entries (cl_entry_id, case_id, entry_at, description, held, "
                 "first_seen_at, updated_at) VALUES (?, ?, '2026-07-20T00:00:00', ?, ?, ?, ?)",
                 (cl_id, CASE, desc, held, first, first))


def test_an_object_takes_its_rows_clock_and_a_held_apart_one_its_texts_row(tmp_path, monkeypatch):
    """Step (c) for tier 1 (2026-10-02): the walk left NULL the clock of an object whose rows
    had no evidence yet. Two seen_at formats, compared as times: '...59Z' is earlier than
    '...59.5+00:00', and string order puts it after ('Z' sorts above '.')."""
    conn = _db(tmp_path)
    _row(conn, 10, "ORDER, first text", seen_at="2026-07-07T19:45:59Z")
    _row(conn, 11, "ORDER, re-described", seen_at="2026-07-07T19:45:59.500000+00:00")
    _row(conn, 12, "ORDER, a third text", seen_at="2026-07-09T08:00:00+00:00")
    conn.execute("UPDATE case_entries SET cl_entry_id = 501 WHERE id IN (10, 11, 12)")
    _obj(conn, 501)                                          # owns three rows
    _obj(conn, 502, desc="ORDER, first text")                # held apart: 10 holds its text
    _obj(conn, 503, desc="never held anywhere")              # no evidence: left NULL
    _obj(conn, 504, first="2026-07-01T00:00:00Z")            # already has a clock
    _obj(conn, 505, held=0)                                  # seen by the walk only
    conn.commit()
    got = {oid: (first, last, basis) for oid, first, last, basis in B.plan_objects(conn)[0]}
    assert got == {501: ("2026-07-07T19:45:59Z", "2026-07-09T08:00:00+00:00", "own rows"),
                   502: ("2026-07-07T19:45:59Z", "2026-07-07T19:45:59Z",
                         "the row holding its text")}
    assert min(["2026-07-07T19:45:59Z", "2026-07-07T19:45:59.500000+00:00"]) != "2026-07-07T19:45:59Z"
    assert B.plan_objects(conn)[1] == 1
    conn.close()
    real = db.connect
    monkeypatch.setattr(B.config, "load_env", lambda *a, **k: None)
    monkeypatch.setattr(B.db, "connect", lambda *a, **k: real(str(tmp_path / "s.db")))
    monkeypatch.setattr(B.db, "require_remote", lambda *a, **k: None)
    assert B.main(["--apply"]) == 0
    c = real(str(tmp_path / "s.db"))
    clocks = {r[0]: (r[1], r[2]) for r in c.execute(
        "SELECT cl_entry_id, first_seen_at, updated_at FROM cl_entries").fetchall()}
    assert clocks[501] == ("2026-07-07T19:45:59Z", "2026-07-09T08:00:00+00:00")
    assert clocks[503] == (None, None) and clocks[504] == ("2026-07-01T00:00:00Z",) * 2
    assert clocks[505] == (None, None)
    assert B.plan_objects(c) == ([], 1)                       # idempotent: only 503 is left
