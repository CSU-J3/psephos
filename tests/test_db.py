"""Wrapper suite for db._Conn / _Cur / _Row (the remote/libSQL adapters).

CI's pytest runs on local SQLite (no Turso creds), so the remote wrapper would
otherwise go untested. These tests exercise db._Cur directly over a fake cursor
that mimics libsql 0.1.x exactly: it supports fetchone/fetchall/description but
is NOT iterable -- which is precisely why news.py:165's `for (seen,) in ...`
crashed on Turso. A revert to delegating `for t in self._cur` re-raises here.

The _Conn test uses a REAL in-memory libsql connection (no creds needed), which
is the only way to catch a missing wrapper delegate like rollback -- its absence
crashed the collectors' error-path skips on Turso with AttributeError.

Run:  pytest tests/test_db.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import libsql
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import db  # noqa: E402


class _LibsqlLikeCursor:
    """Mimics a libsql 0.1.x Cursor: fetchone/fetchall/description + lastrowid /
    rowcount, but deliberately NO __iter__. Rows are plain tuples (libsql ignores
    row_factory). Built from a sqlite3 cursor so the column metadata is real."""

    def __init__(self, sqlite_cur):
        self._rows = [tuple(r) for r in sqlite_cur.fetchall()]
        self.description = sqlite_cur.description
        self.lastrowid = sqlite_cur.lastrowid
        self.rowcount = sqlite_cur.rowcount
        self._i = 0

    def fetchone(self):
        if self._i >= len(self._rows):
            return None
        row = self._rows[self._i]
        self._i += 1
        return row

    def fetchall(self):
        rest = self._rows[self._i:]
        self._i = len(self._rows)
        return rest


def _fixture_cur(query="SELECT a, b FROM t ORDER BY a"):
    # No row_factory: plain tuples out, exactly like the libsql client.
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (a TEXT, b TEXT)")
    conn.execute("INSERT INTO t VALUES ('p', 'q')")
    conn.execute("INSERT INTO t VALUES ('x', 'y')")
    return _LibsqlLikeCursor(conn.execute(query))


def test_raw_libsql_like_cursor_is_not_iterable():
    """Guards the premise: the fake must reproduce libsql's non-iterability, or
    the iteration tests below would pass for the wrong reason."""
    with pytest.raises(TypeError):
        iter(_fixture_cur())


def test_direct_iteration_yields_named_rows():
    """The news.py:165 pattern: iterate the cursor directly via the wrapper."""
    cur = db._Cur(_fixture_cur())
    rows = list(cur)
    assert len(rows) == 2
    assert rows[0]["a"] == "p"  # name access survives direct iteration
    assert rows[0]["b"] == "q"
    assert rows[1]["a"] == "x"


def test_direct_iteration_tuple_unpacks_by_value():
    """Exactly news.py:165: `for (seen,) in conn.execute("SELECT title_norm ...")`.
    A dict-based wrapper would yield the column NAME here, not the value."""
    cur = db._Cur(_fixture_cur("SELECT a FROM t ORDER BY a"))
    seen = [s for (s,) in cur]
    assert seen == ["p", "x"]  # values, not the column name "a"


def test_row_supports_positional_and_name_access():
    row = db._Cur(_fixture_cur()).fetchone()
    assert row["a"] == "p"   # name
    assert row[0] == "p"     # positional, like sqlite3.Row
    assert list(row) == ["p", "q"]  # iteration by value
    assert row.keys() == ["a", "b"]


def test_fetchall_and_fetchone_share_wrapping():
    rows = db._Cur(_fixture_cur()).fetchall()
    assert [r["a"] for r in rows] == ["p", "x"]
    assert db._Cur(_fixture_cur()).fetchone()["b"] == "q"


def test_conn_wrapper_commit_and_rollback_over_real_libsql():
    """_Conn wraps the actual libsql client. rollback() was the missing delegate:
    the collectors' error-path skips (litigation poll-fail litigation.py:287,
    executive.py:203/213, legislation.py:238) call conn.rollback() and crashed on
    Turso with AttributeError -- invisible on stdlib sqlite3, which has rollback.
    Exercise both paths against the real client, no Turso creds needed."""
    conn = db._Conn(libsql.connect(":memory:"))
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.commit()  # DDL committed; table empty

    # rollback path: an uncommitted insert reverts to 0 rows
    conn.execute("INSERT INTO t VALUES (1)")
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0

    # commit path: a committed insert persists
    conn.execute("INSERT INTO t VALUES (2)")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    conn.close()


# --- stale-Hrana-stream recovery -------------------------------------------
# Turso drops a server-side Hrana stream when a connection outlives it; the next
# statement raises ValueError: Hrana: ... "stream not found: ...". A real expiry
# can't be forced offline, so a fake raw wraps a real in-memory libsql connection
# and raises that ValueError on demand -- keeping the post-reopen path on the real
# client, as the rollback test does.

_STALE = (
    'Hrana: `api error: `status=404 Not Found, '
    'body={"error":"stream not found: eba5e539:3d21f92"}``'
)


class _FakeRaw:
    """Delegates to a real in-memory libsql connection, but raises the stale-stream
    ValueError on the next execute when `fail_next` is set (once, then clears)."""

    def __init__(self, real):
        self._real = real
        self.fail_next = False

    def execute(self, sql, params=None):
        if self.fail_next:
            self.fail_next = False
            raise ValueError(_STALE)
        return self._real.execute(sql, params) if params is not None else self._real.execute(sql)

    def commit(self):
        return self._real.commit()

    def rollback(self):
        return self._real.rollback()


def test_execute_recovers_from_stale_hrana_stream():
    """A stale stream on the first statement (nothing uncommitted) reopens once and
    the retried statement returns the real result -- the news.py:156 crash case."""
    seeded = libsql.connect(":memory:")
    seeded.execute("CREATE TABLE t (x INTEGER)")
    seeded.execute("INSERT INTO t VALUES (7)")
    seeded.commit()

    calls = {"reopen": 0}

    def reopen():
        calls["reopen"] += 1
        return seeded  # the "fresh" connection after the stream was dropped

    fake = _FakeRaw(libsql.connect(":memory:"))
    fake.fail_next = True
    conn = db._Conn(fake, reopen=reopen)

    # nothing pending -> the stale error triggers exactly one reopen + retry
    assert conn.execute("SELECT x FROM t").fetchone()["x"] == 7
    assert calls["reopen"] == 1


def test_execute_does_not_retry_when_transaction_pending():
    """With an uncommitted write pending, a stale stream must NOT reopen -- doing so
    would drop the pending write. The error re-raises and reopen is never called."""
    real = libsql.connect(":memory:")
    real.execute("CREATE TABLE t (x INTEGER)")
    real.commit()
    fake = _FakeRaw(real)

    calls = {"reopen": 0}

    def reopen():
        calls["reopen"] += 1
        return real

    conn = db._Conn(fake, reopen=reopen)
    conn.execute("INSERT INTO t VALUES (1)")  # _pending = True, not yet committed

    fake.fail_next = True
    with pytest.raises(ValueError, match="stream not found"):
        conn.execute("INSERT INTO t VALUES (2)")
    assert calls["reopen"] == 0  # safety gate held


def test_execute_propagates_unrelated_valueerror():
    """A ValueError that is not a stale-stream error is never swallowed, and never
    triggers a reconnect -- only the specific Hrana signal does."""
    calls = {"reopen": 0}

    class _Boom:
        def execute(self, sql, params=None):
            raise ValueError("near \"SELCT\": syntax error")

    def reopen():
        calls["reopen"] += 1
        return _Boom()

    conn = db._Conn(_Boom(), reopen=reopen)
    with pytest.raises(ValueError, match="syntax error"):
        conn.execute("SELCT 1")
    assert calls["reopen"] == 0
