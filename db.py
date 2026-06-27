"""SQLite access for psephos: schema loader, connection, and upsert helpers.

`schema.sql` is the source of truth. `init_db()` runs it through Python so local
dev on Windows needs no `sqlite3` CLI; the schema is idempotent
(CREATE TABLE IF NOT EXISTS), so re-running is safe.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = "data/psephos.db"
SCHEMA_PATH = "schema.sql"


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    """Open a connection with row access by name and FK enforcement on."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str = DB_PATH, schema: str = SCHEMA_PATH) -> None:
    """Create the data dir if missing and apply the schema. Idempotent."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sql = Path(schema).read_text(encoding="utf-8")
    conn = connect(path)
    try:
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()


def upsert(conn: sqlite3.Connection, table: str, row: dict, pk: str) -> None:
    """INSERT, or UPDATE the non-pk columns on conflict with the primary key."""
    cols = list(row)
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != pk)
    sql = (
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT({pk}) DO UPDATE SET {updates}"
    )
    conn.execute(sql, [row[c] for c in cols])


def insert_ignore(conn: sqlite3.Connection, table: str, row: dict) -> bool:
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
    init_db()
    print(f"Initialized {DB_PATH} from {SCHEMA_PATH}")
