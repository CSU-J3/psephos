"""Backfill `items.outlet` for news rows collected before the column existed.

WHY THIS IS A BACKFILL AND NOT THE NORMAL PATH. `collectors/news.py:fetch_feed`
now keeps the feed's own `<source>` element, which is the publisher's own
statement of who wrote the piece. Every row collected before that change has no
such record -- the element was parsed by feedparser and dropped before storage --
and it is NOT recoverable, because `raw_json` persisted the same four fields.
What is recoverable is the ` - Publisher` suffix Google News appends to the
title, which is what this script parses.

THE TWO ARE NOT EQUAL EVIDENCE, and the difference is the reason this file exists
rather than a one-line UPDATE. A structured element is the publisher stating the
publisher; a title suffix is a rendering convention the publisher controls and
does not intend as data. It was measured before being trusted -- 139 of 139
correct across the cohort of items whose suffix names an outlet psephos grades B2
(read individually, 2026-08-15) -- but a later reader must be able to tell which
kind of evidence a given row carries. Rows written from here are distinguishable
by date: anything with `fetched_at` before the collector change is a parse.

Dry-run by default. Read the distribution it prints before `--apply`: the top
suffixes are the check that the parse is picking up publishers rather than
headline fragments.

Run:  python -m scripts.backfill_outlet            # dry run
      python -m scripts.backfill_outlet --apply
"""
from __future__ import annotations

import sys
from collections import Counter

import config
import db
from collectors.news import outlet_from_title

# Only the aggregator's rows. A plain RSS feed's `source_id` already names the
# outlet, so parsing its titles would invent a field where one is not needed --
# and those titles carry no publisher suffix to parse in the first place.
SELECT_SQL = (
    "SELECT id, title FROM items "
    "WHERE channel = 'news' AND source_id = 'google-news' AND outlet IS NULL"
)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    apply = "--apply" in argv

    config.load_env()
    db.init_db()
    conn = db.connect()
    try:
        db.require_remote(conn, "the outlet backfill")
        rows = conn.execute(SELECT_SQL).fetchall()
        parsed = [(r["id"], outlet_from_title(r["title"])) for r in rows]
        hits = [(i, o) for i, o in parsed if o]
        misses = [i for i, o in parsed if not o]

        counts = Counter(o for _, o in hits)
        print(f"  rows with a NULL outlet:  {len(rows)}")
        print(f"  would fill:               {len(hits)}")
        print(f"  would stay NULL:          {len(misses)}  (no ' - ' in the title)")
        print(f"  distinct outlets parsed:  {len(counts)}")
        print("  top 15 by volume -- read these; they should look like publishers:")
        for name, n in counts.most_common(15):
            print(f"      {n:>4}  {name}")

        if not apply:
            print("  DRY-RUN -- nothing written. Re-run with --apply.")
            return 0

        # Grouped by outlet rather than one statement per row: same rows written,
        # a third of the round trips (964 against 3,003) on a metered remote that
        # psephos shares with another project. Chunked because an IN list is not
        # unbounded, and SQLITE_MAX_VARIABLE_NUMBER is the limit that bites.
        by_outlet: dict[str, list[int]] = {}
        for item_id, outlet in hits:
            by_outlet.setdefault(outlet, []).append(item_id)
        for outlet, ids in by_outlet.items():
            for i in range(0, len(ids), 200):
                chunk = ids[i:i + 200]
                marks = ",".join("?" * len(chunk))
                conn.execute(f"UPDATE items SET outlet = ? WHERE id IN ({marks})",
                             (outlet, *chunk))
        conn.commit()
        remaining = len(conn.execute(SELECT_SQL).fetchall())
        print(f"  APPLIED -- filled {len(hits)}; {remaining} google-news rows still NULL.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
