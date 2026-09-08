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
import re
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


# --- a read-only token's refusal --------------------------------------------
# Turso enforces a read-only auth token by BLOCKING write statements, and it counts
# `PRAGMA foreign_keys = ON` among them. Because that PRAGMA is on the connect path,
# the refusal arrives as a failure to ESTABLISH rather than as a failed write:
#
#   ValueError: Hrana: `stream error: `Error { message: "Operation was blocked: SQL
#   write operations are forbidden (current session doesn't have write permission)",
#   code: "BLOCKED" }``
#
# THE DISCRIMINATOR IS THE CODE FIELD, NEVER THE MESSAGE. "Operation was blocked:
# SQL write operations are forbidden" is Turso's prose, and prose is not an
# interface -- it can be reworded in a point release with no version bump and no
# symptom here beyond connections that quietly stop working. `code` is the field the
# protocol defines. This client hands it to us inside a serialized error rather than
# as an attribute, so what follows extracts THAT FIELD from the serialization; it
# does not match against the wording sitting beside it. A future client exposing
# `.code` directly is preferred, and is tried first.
_BLOCKED_CODE = re.compile(r'\bcode:\s*"BLOCKED"')


def _is_write_forbidden(exc: BaseException) -> bool:
    """Did the server refuse this statement because the session cannot write?"""
    code = getattr(exc, "code", None)
    if isinstance(code, str):
        return code.strip().upper() == "BLOCKED"
    return _BLOCKED_CODE.search(str(exc)) is not None


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
    def __init__(self, raw, reopen=None, fk_enforced=True):
        self._raw = raw
        # False ONLY on a connection whose server refused `PRAGMA foreign_keys = ON`
        # because the token is read-only. Reads are unaffected; the write helpers
        # refuse on it. Defaults True so every existing construction site keeps the
        # contract it already had -- local SQLite, which applies the PRAGMA, and the
        # tests that wrap a raw connection directly.
        self.fk_enforced = fk_enforced
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
    ("items", "outlet", "TEXT"),
    ("cases", "date_terminated", "TEXT"),
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
            """Open a raw connection. Returns (raw, fk_enforced)."""
            raw = libsql.connect(database=url, auth_token=token)
            try:
                # libsql.connect() is lazy, so this PRAGMA is the first round trip
                # and therefore where establishment actually fails. It is also the
                # setting every remote connection needs, so the probe is free.
                raw.execute("PRAGMA foreign_keys = ON")
                return raw, True
            except Exception as exc:
                if not _is_write_forbidden(exc):
                    _close_quietly(raw)
                    raise
            # A READ-ONLY TOKEN REFUSED THE PRAGMA. That refusal is the token working
            # as mapped, not a fault -- but Turso counts this PRAGMA as a WRITE, and
            # it sits on the connect path, so the refusal made every read-only
            # connection impossible rather than merely unable to write. audit.yml ran
            # for the first time on 2026-09-08 and died here, before reading a row.
            #
            # Proceeding is correct rather than a concession: foreign keys constrain
            # WRITES, and a session that cannot write needs no enforcement. What does
            # need replacing is the probe -- the PRAGMA was also how establishment
            # was proven, so SELECT 1 takes that job. A transport failure on it still
            # reaches _retry_transport, unchanged.
            #
            # The connection is marked fk_enforced=False and the write helpers refuse
            # on it. The server would refuse them anyway; the flag is what stops a
            # future writer INHERITING this fallback silently.
            try:
                raw.execute("SELECT 1")
            except Exception:
                _close_quietly(raw)
                raise
            return raw, False

        def _open_retrying():
            return _retry_transport(_open, "connect")

        # `reopen` gets the retrying variant, so _Conn.execute's stale-stream
        # recovery and reset() inherit the ladder: they rebuild through this exact
        # path, and a rebuild landing inside a blip would otherwise fail outright --
        # the wider blast radius of the two call sites, since it fires mid-run.
        # `reopen` drops the flag deliberately: a rebuild goes through the same
        # url and token and therefore reaches the same permission, so a connection
        # cannot change its fk_enforced under itself mid-run.
        raw, fk_enforced = _open_retrying()
        return _Conn(raw, reopen=lambda: _open_retrying()[0], fk_enforced=fk_enforced)
    conn = sqlite3.connect(path if path is not None else DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # SAY SO WHEN THE FALLBACK IS TAKEN BY ACCIDENT. An explicit path means local was
    # ASKED for (tests, offline dev) and is silent. No path and no URL means the
    # caller wanted whatever `connect()` gives and got the local file -- which is
    # the trap: a `.env` sitting on disk is not the environment, and a script that
    # forgets `config.load_env()` reads a stale local database while looking exactly
    # like a production read. Measured 2026-08-15: an ad-hoc query reported 12 news
    # items against production's 87, and what exposed it was an unrelated missing
    # table raising sqlite3.OperationalError -- an accident of which query ran
    # first. A single-query session has no such accident available.
    if path is None:
        print(f"db: no TURSO_DATABASE_URL in the environment; using the local SQLite "
              f"fallback at {DB_PATH}. Numbers read here are NOT production. Call "
              "config.load_env() first if you meant Turso.", file=sys.stderr)
    return conn


def backend(conn) -> str:
    """Name the backend a connection actually reached: `turso` or `sqlite`.

    THE DISCRIMINATOR IS THE CONNECTION OBJECT, NOT THE ENVIRONMENT, and that is the
    whole point. Every other way of asking -- is `.env` present, is TURSO_DATABASE_URL
    set now, did I mean to load it -- describes intent, and intent is what goes wrong.
    The object records what happened.

    Use it in any read-only analysis that reports a figure, so the figure arrives with
    its provenance attached. `tools/coverage_audit.py` is unaffected by the trap
    because it calls `config.load_env()` itself before connecting; that is the pattern
    to copy, not a reason to skip naming the backend."""
    return "turso" if isinstance(conn, _Conn) else "sqlite"


def require_remote(conn, what: str = "this reading") -> None:
    """Raise unless `conn` reached Turso. For scripts and analyses whose output is
    only meaningful against production -- an alarm, an audit, a count quoted into a
    doc. Fails loudly and immediately rather than answering from the local fallback,
    which is the failure mode this exists to remove: a wrong number that looks right."""
    if backend(conn) != "turso":
        raise RuntimeError(
            f"{what} requires the remote Turso database, but this connection is "
            f"local SQLite. Call config.load_env() before db.connect(), and check "
            f"TURSO_DATABASE_URL is in the .env being loaded."
        )


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


def _require_writable(conn, what: str) -> None:
    """Refuse a write on a connection opened with a read-only token.

    THE SERVER IS THE REAL ENFORCEMENT and this does not pretend otherwise -- a write
    that got past here would still come back BLOCKED. What this adds is WHERE the
    refusal happens and what it says. Without it the failure arrives from three
    layers down as a Hrana stream error naming a PRAGMA the caller never wrote,
    which is how the read-only path was misread as a connection fault in the first
    place (2026-09-08, audit.yml's first run).

    It reads `fk_enforced` rather than a separate read-only flag on purpose: those
    are the same fact. The connection is unenforced BECAUSE the session cannot
    write, and keeping one attribute keeps them from drifting apart.

    getattr with a True default so a local sqlite3.Connection -- which has no such
    attribute and enforces the PRAGMA successfully -- passes untouched."""
    if getattr(conn, "fk_enforced", True):
        return
    raise RuntimeError(
        f"{what} refused: this connection was opened with a READ-ONLY Turso token. "
        f"Its server declined `PRAGMA foreign_keys = ON`, so foreign keys are not "
        f"enforced on it and no write may run through it. Reads are unaffected. "
        f"Anything that mutates needs a writing token in TURSO_AUTH_TOKEN -- see "
        f"the read-only branch in db.connect()."
    )


def upsert(conn, table: str, row: dict, pk: str) -> None:
    """INSERT, or UPDATE the non-pk columns on conflict with the primary key."""
    _require_writable(conn, f"upsert into {table}")
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
    _require_writable(conn, f"insert into {table}")
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
