"""Every public figure the R1 switch moves, before and after, for the page's dated notes
(Corey's ruling 5, 2026-09-30: "a dated note on each surface whose figure moves, saying
duplicate court-entry rows were merged, with the before and after") and for the record
(build order d: "record every public figure before and after at the moment of the switch").

READ-ONLY against the database. Writes one file, web/lib/entry-merge.json, which the page's
notes read. Run it at the switch, BEFORE scripts/repair_latest_entry --apply: the "before"
of latest_entry_at is the column as it stands, and the repair is what moves it.

Each figure is read both ways from ONE state of the record, so the pair differs only by
the definition -- rows against entries -- and not by a run that landed between two reads:

  map "· N entries"      case_entries rows          record_entries
  /case "N entries"      A1 items                   A1 record_items
  Wire litigation        items (total, +24h, +7d)   record_items
  latest_entry_at        the stored column          MAX over record_entries

Usage (repo root):
    python -m tools.merge_notes [--on YYYY-MM-DD] [--out PATH]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import config
import db

OUT = Path("web/lib/entry-merge.json")
WHY = "duplicate court-entry rows were merged"


def figures(conn, on: str | None = None) -> dict:
    anchor = conn.execute("SELECT MAX(fetched_at) FROM items").fetchone()[0]
    at = datetime.fromisoformat(anchor.replace("Z", "+00:00"))
    day = (at - timedelta(days=1)).isoformat()
    week = (at - timedelta(days=7)).isoformat()

    def wire(merged_filter: str) -> list[int]:
        r = conn.execute(
            "SELECT COUNT(*), SUM(fetched_at >= ?), SUM(fetched_at >= ?) FROM items "
            f"WHERE channel = 'litigation' {merged_filter}", (day, week)).fetchone()
        return [int(r[0] or 0), int(r[1] or 0), int(r[2] or 0)]

    before, after = wire(""), wire("AND merged_into IS NULL")
    out = {
        "on": on or anchor[:10],
        "why": WHY,
        "clock": anchor,
        "wire": {"litigation": {k: [before[i], after[i]] for i, k in
                                enumerate(("total", "day", "week"))}},
        "map": {"entries": [0, 0], "dockets_changed": 0},
        "cases": {},
    }
    for c in conn.execute("SELECT case_id, state, latest_entry_at FROM cases ORDER BY case_id").fetchall():
        cid = c["case_id"]
        eb = conn.execute("SELECT COUNT(*) FROM case_entries WHERE case_id = ?", (cid,)).fetchone()[0]
        ea = conn.execute("SELECT COUNT(*) FROM record_entries WHERE case_id = ?", (cid,)).fetchone()[0]
        lb = conn.execute("SELECT COUNT(*) FROM items WHERE case_id = ? AND channel = 'litigation' "
                          "AND admiralty_source <> 'B'", (cid,)).fetchone()[0]
        la = conn.execute("SELECT COUNT(*) FROM record_items WHERE case_id = ? AND channel = 'litigation' "
                          "AND admiralty_source <> 'B'", (cid,)).fetchone()[0]
        latest = conn.execute("SELECT MAX(entry_at) FROM record_entries WHERE case_id = ?",
                              (cid,)).fetchone()[0]
        if c["state"] is not None:
            out["map"]["entries"][0] += eb
            out["map"]["entries"][1] += ea
            out["map"]["dockets_changed"] += eb != ea
        moved = {}
        if eb != ea:
            moved["entries"] = [eb, ea]
        if lb != la:
            moved["ledger"] = [lb, la]
        if (c["latest_entry_at"] or None) != (latest or None):
            moved["latest_entry_at"] = [c["latest_entry_at"], latest]
        if moved:
            out["cases"][cid] = moved
    return out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    on = argv[argv.index("--on") + 1] if "--on" in argv else None
    path = Path(argv[argv.index("--out") + 1]) if "--out" in argv else OUT
    config.load_env()
    conn = db.connect()
    try:
        f = figures(conn, on)
    finally:
        conn.close()
    path.write_text(json.dumps(f, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    w = f["wire"]["litigation"]
    print(f"clock {f['clock']}  on {f['on']}")
    print(f"  Wire litigation  total {w['total'][0]:,} -> {w['total'][1]:,}  "
          f"+24h {w['day'][0]} -> {w['day'][1]}  +7d {w['week'][0]} -> {w['week'][1]}")
    print(f"  map entries      {f['map']['entries'][0]:,} -> {f['map']['entries'][1]:,} "
          f"({f['map']['dockets_changed']} dockets change)")
    print(f"  cases that move  {len(f['cases'])}; latest_entry_at moves on "
          f"{sum(1 for v in f['cases'].values() if 'latest_entry_at' in v)}")
    print(f"  -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
