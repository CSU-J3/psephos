"""Bound when psephos first held each case_entries row written before seen_at existed (R1
step c, Corey's rulings of 2026-09-30). Dry-run by default.

The /case ledger will show every earlier description of an entry "beside when it was seen"
(the plan's revisions table, ruling 1). Rows written since 2026-09-30 carry an exact
seen_at. Older rows carry nothing, and this is the one-time pass that bounds them from what
the record already holds:

  * a row whose text has an A1 item: the item's fetched_at. write_entries writes the row
    and its item in the same loop, seconds apart, so this is exact (seen_by NULL);
  * any other row: the id bracket (collectors/cl_twins.RunClock). case_entries ids are one
    AUTOINCREMENT written in run order, so a row lies between the runs of its nearest
    item-bearing neighbours by id. seen_at is the start of the earliest run it can be in,
    seen_by the end of the latest -- "first held between these two". The D0 measured this
    on the 00:38Z dump: 2,805 rows exact, 3,213 pinned to one run, 575 in a range of 2-4.

No page reads seen_at or seen_by before the switch. Re-running is idempotent: rows that
already carry a seen_at are left alone.

Usage (repo root):
    python -m scripts.backfill_seen_at            # dry run: counts by basis
    python -m scripts.backfill_seen_at --apply    # write, commit
"""

from __future__ import annotations

import sys

import common
import config
import db
from collectors import cl_twins as tw

_CHUNK = 100


def plan(conn) -> list[tuple[int, str, str | None, str]]:
    """(row id, seen_at, seen_by, basis) for every row with no seen_at. Reads only."""
    rows = [dict(r) for r in conn.execute(
        "SELECT id, case_id, entry_at, description, seen_at FROM case_entries ORDER BY id").fetchall()]
    fetched = [r["fetched_at"] for r in conn.execute(
        "SELECT fetched_at FROM items WHERE channel IN "
        "('litigation', 'state', 'legislation', 'executive')").fetchall()]
    item_time = {r["content_hash"]: r["fetched_at"] for r in conn.execute(
        "SELECT content_hash, fetched_at FROM items WHERE channel = 'litigation'").fetchall()}
    irt = {}
    for r in rows:
        h = common.content_hash(r["case_id"], r["entry_at"], r["description"])
        if h in item_time:
            irt[r["id"]] = item_time[h]
    clock = tw.RunClock(fetched, irt)
    out = []
    for r in rows:
        if r["seen_at"]:
            continue
        if r["id"] in irt:
            out.append((r["id"], irt[r["id"]], None, "item"))
            continue
        lo, hi = clock.bracket(r["id"])
        out.append((r["id"], clock.starts[lo].isoformat(), clock.ends[hi].isoformat(),
                    "one run" if lo == hi else f"{hi - lo + 1} runs"))
    return out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    apply = "--apply" in argv
    config.load_env()
    conn = db.connect()
    try:
        todo = plan(conn)
        basis: dict = {}
        for *_, b in todo:
            basis[b] = basis.get(b, 0) + 1
        print(f"rows without seen_at: {len(todo)}  by basis: {dict(sorted(basis.items()))}")
        if not apply:
            print("  DRY-RUN -- nothing written. Re-run with --apply.")
            return 0
        db.require_remote(conn, "bounding seen_at on the record")
        for i in range(0, len(todo), _CHUNK):
            chunk = todo[i:i + _CHUNK]
            w = " ".join("WHEN ? THEN ?" for _ in chunk)
            params = [x for rid, at, _, _ in chunk for x in (rid, at)]
            params += [x for rid, _, by, _ in chunk for x in (rid, by)]
            params += [rid for rid, *_ in chunk]
            conn.execute(f"UPDATE case_entries SET seen_at = CASE id {w} END, seen_by = CASE id {w} END "
                         f"WHERE seen_at IS NULL AND id IN ({', '.join('?' for _ in chunk)})", params)
        conn.commit()
        print(f"  wrote {len(todo)}, committed")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
