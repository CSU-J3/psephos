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


# --- transient transport failures at establishment --------------------------
# The other half of the Turso failure space, and deliberately a separate
# mechanism from the stale stream above: a 502 from the platform edge, raised
# before a usable connection exists. Verbatim from the three runs it killed
# (08-06 23:46Z, 08-07 01:58Z, 08-07 06:56Z), all at _apply_migrations' first
# statement inside init_db().

_BAD_GATEWAY = "Hrana: api error: status=502 Bad Gateway, upstream forward failed"

# Captured at import, before any test patches libsql.connect. The fakes below build
# REAL in-memory connections to delegate to, and calling the patched name to do that
# would recurse into the fake itself.
_REAL_CONNECT = libsql.connect


def _mem():
    return _REAL_CONNECT(":memory:")


class _Raw502:
    """A raw connection whose first statement raises the observed 502 when `fail`
    is set; otherwise delegates to a real in-memory libsql connection. Counts its
    own close() calls, since closing the dead connection before the retry is part
    of the contract."""

    def __init__(self, real, fail=False):
        self._real = real
        self._fail = fail
        self.closed = 0

    def execute(self, sql, params=None):
        if self._fail:
            raise ValueError(_BAD_GATEWAY)
        return self._real.execute(sql, params) if params is not None else self._real.execute(sql)

    def executescript(self, script):
        return self._real.executescript(script)

    def commit(self):
        return self._real.commit()

    def close(self):
        self.closed += 1


def _remote_env(monkeypatch):
    """Route db._remote_url down the Turso branch without a real database."""
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://fake-psephos.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "not-a-real-token")


def _capture_sleeps(monkeypatch):
    """Record the ladder instead of serving it -- the suite must not sleep 10.5s."""
    slept = []
    monkeypatch.setattr(db.time, "sleep", lambda s: slept.append(s))
    return slept


def _fake_connect(monkeypatch, factory):
    """Patch libsql.connect with `factory(n)`, n being the 1-based call number.
    Returns the call counter so a test can assert how many attempts were made."""
    calls = {"n": 0}

    def fake(database=None, auth_token=None):
        calls["n"] += 1
        return factory(calls["n"])

    monkeypatch.setattr(db.libsql, "connect", fake)
    return calls


def test_connect_retries_a_transient_transport_failure(monkeypatch):
    """A 502 on the establishing PRAGMA sleeps once and the retry returns a usable
    connection -- the run survives a blip instead of dying at import."""
    _remote_env(monkeypatch)
    slept = _capture_sleeps(monkeypatch)
    opened = []

    def factory(n):
        raw = _Raw502(_mem(), fail=(n == 1))
        opened.append(raw)
        return raw

    calls = _fake_connect(monkeypatch, factory)

    conn = db.connect()
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0

    assert calls["n"] == 2          # one failed establishment, one that worked
    assert slept == [1.5]           # first rung only
    assert opened[0].closed == 1    # the dead connection was closed before the retry


def test_transport_retry_gives_up_after_four_attempts_and_raises_the_real_error(monkeypatch):
    """The ladder is bounded: four attempts, three sleeps, ~10.5s, and then the
    underlying error propagates as itself -- not as None, and not wrapped."""
    _remote_env(monkeypatch)
    slept = _capture_sleeps(monkeypatch)
    calls = _fake_connect(monkeypatch, lambda n: _Raw502(_mem(), fail=True))

    with pytest.raises(ValueError, match="502 Bad Gateway"):
        db.connect()

    assert calls["n"] == 4
    assert slept == [1.5, 3.0, 6.0]
    assert sum(slept) == 10.5


def test_transport_retry_does_not_retry_a_non_transport_error(monkeypatch):
    """Only the transport family gets the ladder. Anything else raises on the first
    attempt with no sleep -- a syntax error must not cost 10.5s per statement."""
    _remote_env(monkeypatch)
    slept = _capture_sleeps(monkeypatch)

    class _Broken:
        def execute(self, sql, params=None):
            raise ValueError('near "PRAGMA": syntax error')

        def close(self):
            pass

    calls = _fake_connect(monkeypatch, lambda n: _Broken())

    with pytest.raises(ValueError, match="syntax error"):
        db.connect()

    assert calls["n"] == 1
    assert slept == []


def test_init_db_retries_the_transport_failure_at_the_migration_probe(tmp_path, monkeypatch):
    """The failure site as observed: db.py's _apply_migrations, not libsql.connect.

    libsql.connect() is lazy, so the 502 surfaced on the first statement of the
    migration probe. A retry wrapped around the connect alone would have retried
    nothing; this asserts the whole bootstrap is the unit that repeats."""
    schema = tmp_path / "mini.sql"
    schema.write_text(
        "PRAGMA journal_mode = WAL;\nCREATE TABLE IF NOT EXISTS t (x INTEGER);\n",
        encoding="utf-8")

    _remote_env(monkeypatch)
    slept = _capture_sleeps(monkeypatch)
    opened = []

    def factory(n):
        raw = _Raw502(_mem(), fail=(n == 1))
        opened.append(raw)
        return raw

    calls = _fake_connect(monkeypatch, factory)

    db.init_db(schema=str(schema))   # no path -> remote branch, per _remote_url

    assert calls["n"] == 2
    assert slept == [1.5]
    assert opened[0].closed == 1     # dead connection closed before the retry
    # ... and the retry actually applied the schema on the second connection.
    assert opened[1].execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0


def test_reset_inherits_the_transport_ladder(monkeypatch):
    """The second call site, and the one with the wider blast radius: reset() (the
    remote arm of db.recover) rebuilds mid-run, so a rebuild landing inside a blip
    must take the ladder too rather than failing outright."""
    _remote_env(monkeypatch)
    slept = _capture_sleeps(monkeypatch)

    # 1st: the original connection. 2nd: a rebuild that lands in the blip. 3rd: the
    # rebuild that succeeds.
    calls = _fake_connect(
        monkeypatch, lambda n: _Raw502(_mem(), fail=(n == 2)))

    conn = db.connect()
    assert calls["n"] == 1
    conn.execute("CREATE TABLE t (x INTEGER)")   # _pending = True

    db.recover(conn)                             # -> reset() -> reopen, mid-blip

    assert calls["n"] == 3
    assert slept == [1.5]
    assert conn._pending is False
    conn.execute("SELECT 1")                     # the rebuilt connection is live


def test_stale_stream_is_not_a_transport_error_and_keeps_the_single_retry_path(monkeypatch):
    """The two mechanisms must stay separate, asserted in both directions against
    the real strings. A stale stream is not fixed by sleeping (the connection is
    gone; only a reopen helps) and a 502 is not fixed by one immediate retry."""
    assert db._is_transport_error(ValueError(_STALE)) is False
    assert "stream not found" not in _BAD_GATEWAY.lower()
    # The 404 in the stale message is the near miss the `status=` prefixes exist for.
    assert "status=404" in _STALE

    # And the stale path still behaves as it did: one reopen, no ladder, no sleep.
    slept = _capture_sleeps(monkeypatch)
    seeded = libsql.connect(":memory:")
    seeded.execute("CREATE TABLE t (x INTEGER)")
    seeded.execute("INSERT INTO t VALUES (7)")
    seeded.commit()

    calls = {"reopen": 0}

    def reopen():
        calls["reopen"] += 1
        return seeded

    fake = _FakeRaw(libsql.connect(":memory:"))
    fake.fail_next = True
    conn = db._Conn(fake, reopen=reopen)

    assert conn.execute("SELECT x FROM t").fetchone()["x"] == 7
    assert calls["reopen"] == 1
    assert slept == []


# --- db.recover: the shared per-item recovery helper ------------------------
# recover() is what collectors' handlers call instead of a bare rollback(). On a
# raw sqlite3 connection (local dev, and tests) it falls through to rollback();
# on a _Conn it takes reset(), which rebuilds the connection rather than rolling
# back a stream that may already be dead.


def test_recover_on_local_sqlite_rolls_back_without_raising():
    """No reset attr -> recover() falls through to rollback(), discarding the open
    transaction, and never raises. This is the local-dev / test path."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.commit()
    conn.execute("INSERT INTO t VALUES (1)")  # uncommitted
    db.recover(conn)                          # -> rollback()
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0


def test_recover_on_conn_takes_reset_path_and_clears_pending():
    """A _Conn has reset(), so recover() rebuilds the connection: _pending clears
    and the connection is usable afterward."""
    seeded = libsql.connect(":memory:")
    seeded.execute("CREATE TABLE t (x INTEGER)")
    seeded.commit()

    calls = {"reopen": 0}

    def reopen():
        calls["reopen"] += 1
        return seeded

    conn = db._Conn(libsql.connect(":memory:"), reopen=reopen)
    conn.execute("CREATE TABLE t (x INTEGER)")   # _pending = True
    assert conn._pending is True

    db.recover(conn)                             # -> reset() -> reopen
    assert calls["reopen"] == 1
    assert conn._pending is False
    # the rebuilt connection is live and queryable
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0


def test_recover_survives_a_raising_rollback():
    """The one that matters: on a _Conn whose underlying rollback() raises (a dead
    Hrana stream), recover() must NOT propagate -- reset() rebuilds and never touches
    the dead rollback -- where a bare conn.rollback() WOULD raise."""

    class _DeadRollback:
        def rollback(self):
            raise ValueError(_STALE)
        def close(self):
            pass

    conn = db._Conn(_DeadRollback(), reopen=lambda: libsql.connect(":memory:"))
    conn._pending = True

    # bare rollback() propagates the dead-stream error ...
    with pytest.raises(ValueError, match="stream not found"):
        conn.rollback()
    # ... but recover() takes the reset path and survives.
    db.recover(conn)
    assert conn._pending is False


def test_migration_adds_status_checked_at_to_a_legacy_cases_table(tmp_path):
    """A `cases` table that predates the column gets it on the next init_db().

    This is the mechanism the production cron relies on: `_apply_migrations` runs
    BEFORE the schema's executescript, and every collector main() calls init_db(),
    so Turso takes the column on the next scheduled run with no hand-run ALTER.
    Asserted on a table built WITHOUT the column rather than on a fresh schema --
    a fresh db gets it from the CREATE and would pass even if _MIGRATIONS were
    empty, which is the whole failure this test exists to catch.

    (First migration test in the suite; entries_synced_at and superseded_by were
    added without one.)"""
    path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(path)
    legacy.execute(
        "CREATE TABLE cases (case_id TEXT PRIMARY KEY, caption TEXT NOT NULL, status TEXT)")
    legacy.execute("INSERT INTO cases VALUES ('72053306', 'US v. RAFFENSPERGER', 'terminated')")
    legacy.commit()
    legacy.close()

    cols = lambda p: [r[1] for r in sqlite3.connect(p).execute("PRAGMA table_info(cases)")]
    assert "status_checked_at" not in cols(path)

    db.init_db(str(path))

    assert "status_checked_at" in cols(path)
    # The migration is an ALTER, not a rebuild: existing rows and values survive it,
    # and the new column reads NULL -- which is what makes every row due on the
    # first refresh pass.
    row = sqlite3.connect(path).execute(
        "SELECT status, status_checked_at FROM cases WHERE case_id = '72053306'").fetchone()
    assert row == ("terminated", None)


def test_migration_adds_state_to_a_legacy_cases_table(tmp_path):
    """Same mechanism as the test above, for `cases.state` (handoff 53).

    Written separately rather than folded in, because the two columns reach production
    by the same route but mean different things on arrival: a NULL `status_checked_at`
    makes a row DUE, while a NULL `state` makes a row INVISIBLE to a per-state view.
    The second failure is silent -- a grid renders 30 cells instead of 31 and nothing
    errors -- so the ALTER landing on the live Turso table is the only thing standing
    between the column and a hole nobody would be told about.

    Asserted against a table built WITHOUT the column: a fresh schema would gain it
    from the CREATE and pass even with _MIGRATIONS empty."""
    path = tmp_path / "legacy_state.db"
    legacy = sqlite3.connect(path)
    legacy.execute(
        "CREATE TABLE cases (case_id TEXT PRIMARY KEY, caption TEXT NOT NULL, status TEXT)")
    legacy.execute("INSERT INTO cases VALUES ('71453026', 'US v. PENNSYLVANIA', 'terminated')")
    legacy.commit()
    legacy.close()

    cols = lambda p: [r[1] for r in sqlite3.connect(p).execute("PRAGMA table_info(cases)")]
    assert "state" not in cols(path)

    db.init_db(str(path))

    assert "state" in cols(path)
    # ALTER, not rebuild: the row survives and the new column reads NULL. This row is
    # one of the six the collector can never reach -- W.D. Pa. dropped out of the
    # tracker when its appeal was docketed -- so NULL here is exactly the state the
    # backfill exists to clear.
    row = sqlite3.connect(path).execute(
        "SELECT status, state FROM cases WHERE case_id = '71453026'").fetchone()
    assert row == ("terminated", None)
