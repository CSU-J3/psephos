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
from pathlib import Path

import libsql

import config

DB_PATH = "data/psephos.db"
SCHEMA_PATH = "schema.sql"


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
    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=None):
        cur = self._raw.execute(sql, params) if params is not None else self._raw.execute(sql)
        return _Cur(cur)

    def executescript(self, script):
        return self._raw.executescript(script)

    def commit(self):
        return self._raw.commit()

    def close(self):
        return self._raw.close()


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
        raw = libsql.connect(database=url, auth_token=_remote_token())
        raw.execute("PRAGMA foreign_keys = ON")
        return _Conn(raw)
    conn = sqlite3.connect(path if path is not None else DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str | None = None, schema: str = SCHEMA_PATH) -> None:
    """Apply the schema. Idempotent. Remote: bootstrap over libSQL (PRAGMA lines
    stripped, no local dir). Local: create the data dir and run the full script."""
    url = _remote_url(path)
    if url:
        raw = libsql.connect(database=url, auth_token=_remote_token())
        try:
            raw.executescript(_schema_for_remote(schema))
            raw.commit()
        finally:
            raw.close()
        return
    target = path if path is not None else DB_PATH
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    sql = Path(schema).read_text(encoding="utf-8")
    conn = sqlite3.connect(target)
    try:
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
