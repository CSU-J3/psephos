"""Database access for psephos: dual-backend (Turso/libSQL or local SQLite).

`schema.sql` is the source of truth. `init_db()` applies it through Python so
local dev on Windows needs no `sqlite3` CLI; the schema is idempotent
(CREATE TABLE IF NOT EXISTS), so re-running is safe.

Backend selection (both connect() and init_db()):
  - an explicit `path` argument  -> local SQLite (stdlib sqlite3). Tests and
    offline dev always take this branch, so the suite stays deterministic.
  - no path + TURSO_DATABASE_URL set in the env -> remote Turso over libSQL.
  - no path + no env -> local SQLite at DB_PATH (offline dev fallback).

The libSQL client returns plain tuples and ignores `row_factory`, so the remote
backend is wrapped (_Conn/_Cur/_Row) to preserve sqlite3.Row semantics -- name
access (`row["col"]`), positional/iteration access by value, direct cursor
iteration -- and the `cur.lastrowid` / `cur.rowcount` contract the collectors and
export rely on. The wrapper is the ONLY remote-specific code; collectors, export,
and tests are unchanged. See requirements.txt for why the libsql version is
pinned exactly.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

import libsql

import config

DB_PATH = "data/psephos.db"
SCHEMA_PATH = "schema.sql"


# --- transient transport failures at connection establishment ---------------
# Turso is a managed platform in front of the database and its edge can fail a
# connection outright. Three consecutive runs -- 08-06 23:46Z, 08-07 01:58Z,
# 08-07 06:56Z -- died on
#     Hrana: api error: status=502 Bad Gateway, upstream forward failed
# raised from the FIRST statement inside init_db's _apply_migrations, before any
# collector ran and before any connection existed. db.recover and the whole
# _pending/reopen machinery below cannot reach that by construction: there is
# nothing to reset. The next scheduled run six hours later succeeded unaided
# every time, which is what a transient platform blip looks like, so a bounded
# retry at establishment is the entire fix.
#
# State the residual honestly. All three failures were at a dedicated
# schema-bootstrap STEP whose unguarded connection ran seconds before the
# collectors; `2eec868` removed that step on 08-08 (see the comment in
# `.github/workflows/collect.yml`). There are ZERO observed failures at the six
# per-collector init_db() calls or at connect()'s PRAGMA, which are what this
# guards. It is insurance and an instrument -- the retry's stderr line is how a
# survived blip becomes visible -- not the repair of a measured defect.
#
# Deliberately distinct from the stale-stream family in _Conn.execute below.
# That one is a 404 "stream not found" on an ESTABLISHED connection, handled by
# a single reopen-and-retry gated on _pending; a stale stream is not fixed by
# sleeping and a 502 is not fixed by one immediate retry. The two must not
# converge, so the predicate below must never match a stale-stream message and
# tests/test_db.py asserts exactly that against the real string.
_TRANSPORT_ERRORS = (
    # Match `status=`, never the bare number: a Hrana stream id is hex and could
    # contain "502" on its own, which would misroute a stale stream to this path.
    "status=502", "status=503", "status=504",
    "bad gateway", "service unavailable", "gateway timeout",
    "upstream forward failed",
    "connection reset", "connection refused", "connection closed",
    "timed out",
)

# Three sleeps, ~10.5s of ladder, four attempts. Short on purpose: connect()
# hands this same ladder to `reopen`, so under a sustained outage every failing
# statement can cost 10.5s and a per-item handler's recover() another -- and
# state.py iterates 484 bills. `collect.yml` bounds the job at 30 minutes as the
# backstop for exactly that amplification.
_CONNECT_BACKOFF = (1.5, 3.0, 6.0)


def _is_transport_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(sig in text for sig in _TRANSPORT_ERRORS)


def _close_quietly(raw) -> None:
    """Close a connection we are done with, swallowing whatever close() raises.

    On the failure path the connection is already known-bad, and a close() that
    fails with ANY type would mask the transport error we are about to retry --
    precisely what this exists to prevent. The breadth is the point, not an
    oversight: narrowing it to the type seen once would reintroduce the mask."""
    try:
        raw.close()
    except Exception:
        pass


def _retry_transport(attempt, what: str):
    """Run `attempt`, retrying it on a transient transport failure.

    `attempt` must be idempotent, and both call sites are: open a connection, or
    apply an IF NOT EXISTS schema behind guarded ADD COLUMNs. Anything that is
    not a transport failure propagates on the first try, untouched.

    The final attempt sits OUTSIDE the loop so its exception is raised by the
    call itself with its own traceback; a `raise last` after the loop types as
    Optional and re-raises a stale exception object."""
    for i, delay in enumerate(_CONNECT_BACKOFF, start=1):
        try:
            return attempt()
        except Exception as exc:
            if not _is_transport_error(exc):
                raise
            print(f"db: {what} hit a transport error ({exc}); retry {i} of "
                  f"{len(_CONNECT_BACKOFF)} in {delay}s", file=sys.stderr)
            time.sleep(delay)
    return attempt()


# --- remote (libSQL) row wrapper --------------------------------------------
# libsql 0.1.x rows are tuples and Connection has no row_factory; these thin
# wrappers map each tuple to a _Row via cursor.description so every existing
# `row["col"]` site keeps working, and proxy lastrowid / rowcount unchanged.


class _Row:
    """Mirrors sqlite3.Row: name access (row["col"]) AND positional / iteration
    by value (row[0], `(x,) = row`). A plain dict is NOT a faithful stand-in --
    unpacking a dict yields its KEYS, which would silently turn news.py:165's
    `for (seen,) in ...` fuzzy-dedup loop into a compare against column names on
    the remote backend. sqlite3.Row unpacks by value, so this matches it."""

    __slots__ = ("_cols", "_vals")

    def __init__(self, cols, vals):
        self._cols = cols
        self._vals = tuple(vals)

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._vals[self._cols.index(key)]
        return self._vals[key]  # int / slice -> positional, like sqlite3.Row

    def __iter__(self):
        return iter(self._vals)  # by value, so `(seen,) = row` yields the value

    def __len__(self):
        return len(self._vals)

    def keys(self):
        return list(self._cols)


class _Cur:
    def __init__(self, cur):
        self._cur = cur

    @property
    def lastrowid(self):
        return self._cur.lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount

    def _wrap(self, tup):
        if tup is None:
            return None
        cols = [d[0] for d in self._cur.description]
        return _Row(cols, tup)

    def fetchone(self):
        return self._wrap(self._cur.fetchone())

    def fetchall(self):
        return [self._wrap(t) for t in self._cur.fetchall()]

    def __iter__(self):
        # libsql 0.1.x Cursor is NOT iterable (unlike sqlite3.Cursor), so we
        # cannot delegate to `for t in self._cur`. Drain via fetchone() -- which
        # both backends support -- and _wrap each row exactly as fetchall does.
        while True:
            tup = self._cur.fetchone()
            if tup is None:
                return
            yield self._wrap(tup)


class _Conn:
    def __init__(self, raw, reopen=None):
        self._raw = raw
        # `reopen` rebuilds the underlying libSQL connection (same url/token, with
        # PRAGMA foreign_keys re-applied); None on local SQLite and in tests that
        # wrap a connection directly, which disables the reopen-and-retry path.
        self._reopen = reopen
        # Has an uncommitted statement run since the last commit/rollback? A reopen
        # abandons the open transaction, so retry is only safe when nothing is
        # pending -- otherwise the failing statement's siblings would be dropped.
        self._pending = False

    def _run(self, sql, params):
        return self._raw.execute(sql, params) if params is not None else self._raw.execute(sql)

    def execute(self, sql, params=None):
        try:
            cur = self._run(sql, params)
        except ValueError as exc:
            # Turso drops a server-side Hrana stream when a connection outlives it
            # (a long run: litigation's throttled CourtListener retries hold one
            # connection ~70min). The next statement then raises
            #   ValueError: Hrana: ... "stream not found: ..."
            # which stdlib sqlite3 never exposes. Reopen and retry ONCE, but only
            # when nothing is uncommitted -- reopening loses the open transaction,
            # so retrying a statement with uncommitted siblings would silently drop
            # them. When _pending, re-raise; the next cron run redoes the batch
            # idempotently (INSERT OR IGNORE / content_hash). commit() is never
            # retried: it would commit an empty transaction on the fresh connection.
            if self._reopen is None or self._pending or "stream not found" not in str(exc).lower():
                raise
            self._raw = self._reopen()
            cur = self._run(sql, params)
        self._pending = True
        return _Cur(cur)

    def executescript(self, script):
        return self._raw.executescript(script)

    def commit(self):
        result = self._raw.commit()
        self._pending = False
        return result

    def rollback(self):
        result = self._raw.rollback()
        self._pending = False
        return result

    def reset(self):
        """Discard the open transaction and rebuild the connection. The caller is
        stating that losing the pending batch is acceptable -- news.py's per-source
        handler, where the batch is one source's uncommitted entries and re-running
        the source re-derives them. Never call this to paper over a mid-batch failure
        whose writes matter; that's what the _pending re-raise in execute() is for.

        This is NOT rollback(): the stream is often already dead when we recover, so
        self._raw.rollback() may itself raise. reset() skips the dead connection and
        builds a fresh one instead. On local SQLite (_reopen is None) there is no
        connection to rebuild, so it just clears _pending and no-ops."""
        if self._reopen is None:
            self._pending = False
            return
        self._raw = self._reopen()
        self._pending = False

    def close(self):
        return self._raw.close()


def recover(conn) -> None:
    """Discard an aborted transaction so a per-item handler can carry on. On the
    remote _Conn the Hrana stream may already be dead, so reset() abandons it and
    rebuilds the connection; local SQLite (and tests that wrap a raw sqlite3
    connection directly) has no reset(), where a plain rollback() is enough. The
    getattr, rather than a type check, is what lets those raw-connection tests take
    the rollback path.

    This helper exists because a handler that calls rollback() on a dead stream
    raises inside the handler and takes down the very run the handler was written
    to keep alive -- the failure family in legislation.py that handoff 15 closed."""
    reset = getattr(conn, "reset", None)
    if reset is not None:
        reset()
    else:
        conn.rollback()


def _remote_url(path: str | None) -> str | None:
    """The Turso URL to use, or None to use local SQLite. An explicit path always
    means local (tests/dev); otherwise honor TURSO_DATABASE_URL if present."""
    if path is not None:
        return None
    return os.environ.get("TURSO_DATABASE_URL") or None


def _remote_token() -> str:
    token = os.environ.get("TURSO_AUTH_TOKEN")
    if not token:
        raise RuntimeError(
            "TURSO_DATABASE_URL is set but TURSO_AUTH_TOKEN is missing. "
            "Set it in .env (local) or as a GitHub Actions secret."
        )
    return token


# Guarded column-adds for tables that predate a column. SQLite has no
# `ADD COLUMN IF NOT EXISTS`, and init_db's executescript only CREATEs (never
# ALTERs), so a live table that already exists -- the remote Turso `items`, or a
# seeded local db -- never gains a new column from the schema text alone. Each
# entry is (table, column, decl). The column must be nullable with an implicit
# NULL default for SQLite to accept ADD COLUMN carrying a REFERENCES clause.
_MIGRATIONS = [
    ("items", "state_bill_id", "TEXT REFERENCES state_bills(state_bill_id)"),
    ("cases", "entries_synced_at", "TEXT"),
    ("cases", "superseded_by", "TEXT REFERENCES cases(case_id)"),
    ("cases", "status_checked_at", "TEXT"),
    ("cases", "state", "TEXT"),
]


def _apply_migrations(conn) -> None:
    """Bridge a live table to a newly-added column, and run BEFORE the schema's
    executescript. The schema indexes items(state_bill_id); that CREATE INDEX
    would fail on a legacy `items` whose column isn't there yet, so the ALTER has
    to land first. On a FRESH db the table doesn't exist here -- we skip, and the
    CREATE (run next by executescript) adds the column and its index directly. On
    re-run the column is already present, so this no-ops. foreign_keys is off
    during init, so ALTER ... REFERENCES a not-yet-created parent is accepted.
    PRAGMA table_info yields the column name at index 1 on both backends (raw
    libSQL remote, stdlib sqlite3 local), so positional access works for both."""
    for table, column, decl in _MIGRATIONS:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not exists:
            continue  # fresh db: executescript's CREATE adds the column + index
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def _schema_for_remote(schema: str) -> str:
    """Schema text minus PRAGMA lines: journal_mode=WAL is a local-file concept
    (server-managed on Turso) and foreign_keys is set per-connection at connect."""
    lines = Path(schema).read_text(encoding="utf-8").splitlines()
    kept = [ln for ln in lines if not ln.strip().upper().startswith("PRAGMA")]
    return "\n".join(kept)


def connect(path: str | None = None):
    """Open a connection. Rows support name access (`row["col"]`) on both backends
    and foreign keys are enforced per-connection."""
    url = _remote_url(path)
    if url:
        token = _remote_token()

        def _open():
            raw = libsql.connect(database=url, auth_token=token)
            try:
                # libsql.connect() is lazy, so this PRAGMA is the first round trip
                # and therefore where establishment actually fails. It is also the
                # setting every remote connection needs, so the probe is free.
                raw.execute("PRAGMA foreign_keys = ON")
            except Exception:
                _close_quietly(raw)
                raise
            return raw

        def _open_retrying():
            return _retry_transport(_open, "connect")

        # `reopen` gets the retrying variant, so _Conn.execute's stale-stream
        # recovery and reset() inherit the ladder: they rebuild through this exact
        # path, and a rebuild landing inside a blip would otherwise fail outright --
        # the wider blast radius of the two call sites, since it fires mid-run.
        return _Conn(_open_retrying(), reopen=_open_retrying)
    conn = sqlite3.connect(path if path is not None else DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str | None = None, schema: str = SCHEMA_PATH) -> None:
    """Apply the schema. Idempotent. Remote: bootstrap over libSQL (PRAGMA lines
    stripped, no local dir). Local: create the data dir and run the full script."""
    url = _remote_url(path)
    if url:
        def _bootstrap():
            raw = libsql.connect(database=url, auth_token=_remote_token())
            try:
                _apply_migrations(raw)
                raw.executescript(_schema_for_remote(schema))
                raw.commit()
            finally:
                # _close_quietly, not close(): on the failure path this connection
                # is the dead one, and a raising close() would replace the transport
                # error _retry_transport branches on with an unrelated one.
                _close_quietly(raw)

        # The whole bootstrap retries, not just libsql.connect(): the observed 502s
        # were raised by _apply_migrations' first statement, so retrying the connect
        # alone would have retried nothing. Re-running it is safe -- the ALTERs are
        # existence-guarded and the schema is CREATE ... IF NOT EXISTS.
        _retry_transport(_bootstrap, "schema bootstrap")
        return
    target = path if path is not None else DB_PATH
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    sql = Path(schema).read_text(encoding="utf-8")
    conn = sqlite3.connect(target)
    try:
        _apply_migrations(conn)
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()


def upsert(conn, table: str, row: dict, pk: str) -> None:
    """INSERT, or UPDATE the non-pk columns on conflict with the primary key."""
    cols = list(row)
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != pk)
    sql = (
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT({pk}) DO UPDATE SET {updates}"
    )
    conn.execute(sql, [row[c] for c in cols])


def insert_ignore(conn, table: str, row: dict) -> bool:
    """INSERT OR IGNORE; return True if a new row was added.

    Relies on the table's UNIQUE constraint to drop duplicates, which is how
    bill_actions, bill_relations, and items stay idempotent across runs.
    """
    cols = list(row)
    placeholders = ", ".join("?" for _ in cols)
    sql = f"INSERT OR IGNORE INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
    cur = conn.execute(sql, [row[c] for c in cols])
    return cur.rowcount > 0


if __name__ == "__main__":
    config.load_env()
    init_db()
    where = "Turso" if os.environ.get("TURSO_DATABASE_URL") else DB_PATH
    print(f"Initialized schema on {where} from {SCHEMA_PATH}")
