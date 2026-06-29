"""Wrapper suite for db._Cur / _Row (the remote/libSQL row adapter).

CI's pytest runs on local SQLite (no Turso creds), so the remote wrapper would
otherwise go untested. These tests exercise db._Cur directly over a fake cursor
that mimics libsql 0.1.x exactly: it supports fetchone/fetchall/description but
is NOT iterable -- which is precisely why news.py:165's `for (seen,) in ...`
crashed on Turso. A revert to delegating `for t in self._cur` re-raises here.

Run:  pytest tests/test_db.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

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
