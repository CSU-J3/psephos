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

Then the OBJECTS (step c for tier 1, Corey's rulings of 2026-10-02). The id backfill walk
gave each object the clock its rows carried; the first two walks ran before this pass had
bounded the rows, so an object whose rows had no item got NULL (`cl_objects`: "NULL for
step (c) to derive from the id order"). Now that every row is bounded, such an object takes
the earliest and latest `seen_at` of the rows it owns -- seen_at being a lower bound where
the row's own seen_by is set. A held-apart object owns no row: its text is another
object's row on its day, and that row is its evidence, the rule the poll and the walk
apply. Times are compared as times, not strings: seen_at carries two formats.

No page reads seen_at, seen_by or an object's clock before the switch. Re-running is
idempotent: rows that already carry a seen_at, and objects that carry a first_seen_at,
are left alone.

Usage (repo root):
    python -m scripts.backfill_seen_at            # dry run: counts by basis
    python -m scripts.backfill_seen_at --apply    # write, commit
"""

from __future__ import annotations

import sys
from datetime import datetime

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


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def plan_objects(conn) -> tuple[list[tuple[int, str, str, str]], int]:
    """(cl_entry_id, first_seen_at, updated_at, basis) for every held object whose clock is
    NULL and whose evidence is now held, and how many are left without any. Reads only."""
    objs = [dict(r) for r in conn.execute(
        "SELECT cl_entry_id, case_id, entry_at, description FROM cl_entries "
        "WHERE held = 1 AND first_seen_at IS NULL ORDER BY cl_entry_id").fetchall()]
    if not objs:
        return [], 0
    owned: dict = {}
    for r in conn.execute("SELECT cl_entry_id, seen_at FROM case_entries "
                          "WHERE cl_entry_id IS NOT NULL AND seen_at IS NOT NULL").fetchall():
        owned.setdefault(r["cl_entry_id"], []).append(r["seen_at"])
    by_text = {(r["case_id"], r["entry_at"], r["description"]): r["seen_at"] for r in conn.execute(
        "SELECT case_id, entry_at, description, seen_at FROM case_entries "
        "WHERE seen_at IS NOT NULL").fetchall()}
    out, none = [], 0
    for o in objs:
        times = owned.get(o["cl_entry_id"])
        basis = "own rows"
        if not times:
            held = by_text.get((o["case_id"], o["entry_at"], o["description"]))
            times, basis = ([held], "the row holding its text") if held else ([], None)
        if not times:
            none += 1
            continue
        out.append((o["cl_entry_id"], min(times, key=_t), max(times, key=_t), basis))
    return out, none


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
        objs, none = plan_objects(conn)
        obasis: dict = {}
        for *_, b in objs:
            obasis[b] = obasis.get(b, 0) + 1
        print(f"objects without a clock, with evidence held: {len(objs)}  by basis: "
              f"{dict(sorted(obasis.items()))}  without: {none}"
              + ("  (rows above are written first, then re-planned)" if todo else ""))
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
        # The objects read the rows' seen_at, so they are planned after the rows are written.
        objs, none = plan_objects(conn)
        for i in range(0, len(objs), _CHUNK):
            chunk = objs[i:i + _CHUNK]
            w = " ".join("WHEN ? THEN ?" for _ in chunk)
            params = [x for oid, first, _, _ in chunk for x in (oid, first)]
            params += [x for oid, _, last, _ in chunk for x in (oid, last)]
            params += [oid for oid, *_ in chunk]
            conn.execute(f"UPDATE cl_entries SET first_seen_at = CASE cl_entry_id {w} END, "
                         f"updated_at = COALESCE(updated_at, CASE cl_entry_id {w} END) "
                         f"WHERE first_seen_at IS NULL AND cl_entry_id IN "
                         f"({', '.join('?' for _ in chunk)})", params)
        conn.commit()
        print(f"  objects: wrote {len(objs)}, committed; {none} still without evidence")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
