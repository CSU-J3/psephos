"""Every public figure the R1 switch moves, before and after, for the page's dated notes
(Corey's ruling 5, 2026-09-30: "a dated note on each surface whose figure moves, saying
duplicate court-entry rows were merged, with the before and after") and for the record
(build order d: "record every public figure before and after at the moment of the switch").

READ-ONLY against the database. Writes one file, web/lib/entry-merge.json, which the page's
notes and the export read. Run it at the switch, BEFORE scripts/repair_latest_entry --apply:
the "before" of latest_entry_at is the column as it stands, and the repair moves it.

Each figure is read both ways from ONE state of the record, so the pair differs only by
the definition -- rows against entries -- and not by a run that landed between two reads:

  map "· N entries"          case_entries rows            record_entries
  /case "N entries"          A1 items                     A1 record_items
  cases.json timeline        items                        record_items
  Wire litigation            items (total, +24h, +7d,     record_items (the fold also takes
                             the older-than-7d clause)    the tracker-note repeats)
  latest_entry_at            the stored column            MAX over record_entries
  rejected states            the outcome over             the outcome over record_entries
                             case_entries                 (current texts: a clerk's strike
                                                          counts at its word, ruling 2)

THE SNAPSHOT IS REFUSED WHILE IT CANNOT BE COMPLETE: a docket still unwalked, or a rule
link not yet applied, would move a figure after the notes were written, with no note. A
pair waiting for a person is recorded (pending_person) rather than refused: Corey may rule
it after the switch, and the link script prints that move's before and after.

Usage (repo root):
    python -m tools.merge_notes [--on YYYY-MM-DD] [--out PATH] [--incomplete]
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import config
import db

OUT = Path("web/lib/entry-merge.json")
WHY = "duplicate court-entry rows were merged"
HISTORY_DAYS = 7          # web/lib/feed.ts HISTORY_AFTER_DAYS

# web/lib/outcomes.ts, ported: the rejected-states outcome is read both ways here, and a
# test (tests/test_merge_notes.py) asserts these are the web's own pattern sources, so the
# two cannot drift.
FILING = re.compile(r"notice\s+of\s+appeal|voluntary\s+dismissal|^\s*(motion|response|brief|reply|letter|notice\s+of\s+(appearance|supplemental)|entry\s+of\s+appearance|amicus|designation)", re.I)
JURISDICTIONAL = re.compile(r"lacks?\s+subject\s+matter\s+jurisdiction", re.I)
REJECT = [re.compile(p, re.I) for p in (
    r"grant(?:ing|ed)\s+[^;]{0,80}?motions?\s+to\s+dismiss|motions?\s+to\s+dismiss[^;]{0,80}?\b(?:are|is)\s+(?:hereby\s+)?granted",
    r"motion\s+(?:for\s+order\s+)?to\s+compel[^;]{0,90}?\bis\s+denied|deny(?:ing)?\s+[^;]{0,60}?motion\s+to\s+compel",
    r"judgment\s+entered\s+in\s+favor\s+of[^;]{0,60}defendants?|judgment\s+in\s+favor\s+of\s+(?!the\s+united\s+states|usa\b)",
    r"plaintiff\s+to\s+take\s+nothing",
    r"dismissing\s+the\s+case|this\s+case\s+is\s+dismissed",
    r"opinion\s+and\s+judgment\s+filed\s*:?\s*affirmed",
)]


def _day(s: str) -> datetime:
    return datetime.fromisoformat(s[:10])


def rejected(conn, table: str, order: str) -> dict[str, str]:
    """{state: rejected_at} as web/lib/outcomes.ts derives it (first match per case in
    the ±1-day window of date_terminated, a state once, at its earliest rejection), over
    `table` -- case_entries before the switch, record_entries after."""
    rows = conn.execute(
        f"""SELECT c.case_id, c.state, c.date_terminated, e.entry_at, e.description
              FROM cases c JOIN {table} e ON e.case_id = c.case_id
             WHERE c.status = 'terminated' AND c.state IS NOT NULL AND c.date_terminated IS NOT NULL
               AND date(substr(e.entry_at, 1, 10))
                   BETWEEN date(substr(c.date_terminated, 1, 10), '-1 day')
                       AND date(substr(c.date_terminated, 1, 10), '+1 day')
             ORDER BY c.case_id, e.entry_at, {order}""").fetchall()
    out: dict[str, str] = {}
    seen: set[str] = set()
    for r in rows:
        if r["case_id"] in seen or not r["entry_at"]:
            continue
        if abs((_day(r["entry_at"]) - _day(r["date_terminated"])).days) > 1:
            continue
        d = " ".join((r["description"] or "").split())
        if not d or FILING.search(d) or JURISDICTIONAL.search(d):
            continue
        if any(p.search(d) for p in REJECT):
            seen.add(r["case_id"])
            at = r["entry_at"][:10]
            if r["state"] not in out or at < out[r["state"]]:
                out[r["state"]] = at
    return out


def figures(conn, on: str | None = None) -> dict:
    anchor = conn.execute("SELECT MAX(fetched_at) FROM items").fetchone()[0]
    if anchor:
        at = datetime.fromisoformat(anchor.replace("Z", "+00:00"))
        day = (at - timedelta(days=1)).isoformat()
        week = (at - timedelta(days=7)).isoformat()
    else:                                   # an empty record: no window holds anything
        day = week = "9999"

    old = conn.execute(
        "SELECT COUNT(*), SUM(fetched_at >= ?), SUM(fetched_at >= ?), "
        "SUM(fetched_at >= ? AND julianday(substr(fetched_at,1,10)) "
        "    - julianday(substr(occurred_at,1,10)) > ?), "
        "SUM(merged_into IS NOT NULL AND source_id = 'seed-cases') "
        "FROM items WHERE channel = 'litigation'", (day, week, day, HISTORY_DAYS)).fetchone()
    new = conn.execute(
        "SELECT COUNT(*), SUM(fetched_at >= ?), SUM(fetched_at >= ?), "
        "SUM(fetched_at >= ? AND julianday(substr(fetched_at,1,10)) "
        "    - julianday(substr(COALESCE(display_at, occurred_at),1,10)) > ?) "
        "FROM items WHERE channel = 'litigation' AND merged_into IS NULL",
        (day, week, day, HISTORY_DAYS)).fetchone()
    wire = {k: [int(old[i] or 0), int(new[i] or 0)]
            for i, k in enumerate(("total", "day", "week", "history"))}
    wire["tracker_notes"] = int(old[4] or 0)       # of the drop, repeated tracker notes

    rb = rejected(conn, "case_entries", "e.id")
    ra = rejected(conn, "record_entries", "e.row_id")
    out = {
        "on": on or (anchor[:10] if anchor else None),
        "why": WHY,
        "clock": anchor,
        "wire": {"litigation": wire},
        "map": {"entries": [0, 0], "dockets_changed": 0, "apart": 0},
        "rejected": {"count": [len(rb), len(ra)],
                     "states": {s: [rb.get(s), ra.get(s)] for s in sorted(set(rb) | set(ra))
                                if rb.get(s) != ra.get(s)}},
        "cases": {},
    }
    for c in conn.execute("SELECT case_id, state, latest_entry_at FROM cases ORDER BY case_id").fetchall():
        cid = c["case_id"]
        one = lambda sql: conn.execute(sql, (cid,)).fetchone()[0]  # noqa: E731
        eb = one("SELECT COUNT(*) FROM case_entries WHERE case_id = ?")
        ea = one("SELECT COUNT(*) FROM record_entries WHERE case_id = ?")
        apart = one("SELECT COUNT(*) FROM cl_entries WHERE case_id = ? AND held = 1 "
                    "AND twin_of IS NULL AND current_row IS NULL")
        lb = one("SELECT COUNT(*) FROM items WHERE case_id = ? AND channel = 'litigation' "
                 "AND admiralty_source <> 'B'")
        la = one("SELECT COUNT(*) FROM record_items WHERE case_id = ? AND channel = 'litigation' "
                 "AND admiralty_source <> 'B'")
        tb = one("SELECT COUNT(*) FROM items WHERE case_id = ?")
        ta = one("SELECT COUNT(*) FROM record_items WHERE case_id = ?")
        latest = one("SELECT MAX(entry_at) FROM record_entries WHERE case_id = ?")
        if c["state"] is not None:
            out["map"]["entries"][0] += eb
            out["map"]["entries"][1] += ea
            out["map"]["dockets_changed"] += eb != ea
            out["map"]["apart"] += apart
        moved = {}
        if eb != ea:
            moved["entries"] = [eb, ea]
        if apart:
            moved["apart"] = apart
        if lb != la:
            moved["ledger"] = [lb, la]
        if tb != ta:
            moved["timeline"] = [tb, ta]
        if (c["latest_entry_at"] or None) != (latest or None):
            moved["latest_entry_at"] = [c["latest_entry_at"], latest]
        if moved:
            out["cases"][cid] = moved
    return out


def incomplete(conn) -> list[str]:
    """Why a snapshot now would miss a move: unwalked dockets, unapplied rule links."""
    from collectors import litigation
    from scripts import link_entry_twins as links
    why = []
    due = litigation.backfill_due(conn, set())
    if due:
        why.append(f"{len(due)} docket(s) not yet walked by the id backfill")
    p = links.plan(conn, links.load_links())
    if p["link"]:
        why.append(f"{len(p['link'])} tier-2 link(s) the rule would make, not yet applied")
    return why


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    on = argv[argv.index("--on") + 1] if "--on" in argv else None
    path = Path(argv[argv.index("--out") + 1]) if "--out" in argv else OUT
    config.load_env()
    conn = db.connect()
    try:
        why = incomplete(conn)
        if why and "--incomplete" not in argv:
            print("REFUSED: the switch's figures would miss a later move -- " + "; ".join(why))
            return 2
        f = figures(conn, on)
        from scripts import link_entry_twins as links
        f["pending_person"] = len(links.plan(conn, links.load_links())["person"])
        if why:
            f["incomplete"] = why
    finally:
        conn.close()
    path.write_text(json.dumps(f, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    w = f["wire"]["litigation"]
    print(f"clock {f['clock']}  on {f['on']}")
    print(f"  Wire litigation  total {w['total'][0]:,} -> {w['total'][1]:,}  +24h {w['day'][0]} -> "
          f"{w['day'][1]}  +7d {w['week'][0]} -> {w['week'][1]}  older-than-7d {w['history'][0]} -> "
          f"{w['history'][1]}  (tracker notes in the drop: {w['tracker_notes']})")
    print(f"  map entries      {f['map']['entries'][0]:,} -> {f['map']['entries'][1]:,} "
          f"({f['map']['dockets_changed']} dockets change; {f['map']['apart']} held apart)")
    print(f"  rejected states  {f['rejected']['count'][0]} -> {f['rejected']['count'][1]}  "
          f"moved: {f['rejected']['states'] or 'none'}")
    print(f"  cases that move  {len(f['cases'])}; latest_entry_at moves on "
          f"{sum(1 for v in f['cases'].values() if 'latest_entry_at' in v)}")
    print(f"  pairs waiting for a person: {f['pending_person']}")
    print(f"  -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
