"""Every public figure the R1 switch moves, before and after, for the page's dated notes
(Corey's ruling 5, 2026-09-30: "a dated note on each surface whose figure moves, saying
duplicate court-entry rows were merged, with the before and after") and for the record
(build order d: "record every public figure before and after at the moment of the switch").

READ-ONLY against the database. Writes one file, web/lib/entry-merge.json, which the page's
notes and the export read. Run it at the switch, BEFORE scripts/repair_latest_entry --apply:
the "before" of latest_entry_at is the column as it stands, and the repair moves it.

THE SWITCH IS TWO MOVES, each with its own dated note (Corey, 2026-10-02: "Ship tier 1 now
... Tier 2's links, when decided, get their own dated note"). Every figure is read THREE
ways from ONE state of the record, so each pair differs only by the definition and not by a
run that landed between two reads:

  rows     what a page reads today: `items`, `case_entries`
  tier 1   entries, every tier-2 link ignored: rows sharing a CourtListener entry id are
           one entry, and items fold one per entry (collectors/cl_fold.py's grouping, the
           twin_of chain not followed)
  objects  the switch: tier 1 plus the links psephos has asserted. This is what
           `record_items` and `record_entries` hold when every case is folded, and the
           snapshot is refused if they hold anything else.

  move "merge" (rows -> tier 1)      duplicate court-entry rows were merged
  move "link"  (tier 1 -> objects)   pairs of court records describing one entry linked;
                                     written only when a link moved a figure

  map "· N entries"          case_entries rows            held entries (record_entries)
  /case "N entries"          A1 items                     A1 items, one per entry
  cases.json timeline        items                        items, one per entry
  Wire litigation            items (total, +24h, +7d,     one per entry (the fold also
                             the older-than-7d clause)    takes the tracker-note repeats)
  latest_entry_at            the stored column            MAX over entries
  rejected states            the outcome over rows        the outcome over entries
                                                          (current texts: a clerk's strike
                                                          counts at its word, ruling 2)

The Wire's windows are cut where the page cuts them: the record's clock in milliseconds,
less a day or a week (web/lib/activity.windowStarts).

THE SNAPSHOT IS REFUSED WHILE IT CANNOT BE COMPLETE: a docket still unwalked, a rule link
not yet applied, or a case the fold has not reached would move a figure after the notes
were written, with no note. A pair waiting for a person is recorded (pending_person)
rather than refused: its link, when ruled, is a later move with its own note.

Usage (repo root):
    python -m tools.merge_notes [--on YYYY-MM-DD] [--out PATH] [--incomplete]
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config
import db

OUT = Path("web/lib/entry-merge.json")
WHY = "duplicate court-entry rows were merged"
WHY_LINK = "pairs of court records that describe one entry were linked"
HISTORY_DAYS = 7          # web/lib/feed.ts HISTORY_AFTER_DAYS
READINGS = ("rows", "tier1", "objects")

# web/lib/outcomes.ts, ported: the rejected-states outcome is read every way here, and a
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

# record_entries with every tier-2 link ignored: the tier-1 reading of the entries.
TIER1_ENTRIES = """(SELECT o.case_id, COALESCE(o.entry_at, e.entry_at) AS entry_at,
       COALESCE(e.description, o.description) AS description, o.cl_entry_id, o.current_row AS row_id
  FROM cl_entries o LEFT JOIN case_entries e ON e.id = o.current_row WHERE o.held = 1
UNION ALL
SELECT e.case_id, e.entry_at, e.description, NULL AS cl_entry_id, e.id AS row_id
  FROM case_entries e WHERE e.cl_entry_id IS NULL)"""
ENTRY_TABLES = {"rows": ("case_entries", "e.id"), "tier1": (TIER1_ENTRIES, "e.row_id"),
                "objects": ("record_entries", "e.row_id")}


def _day(s: str) -> datetime:
    return datetime.fromisoformat(s[:10])


def _ms(s: str) -> datetime:
    """A stamp as JavaScript's Date holds it: milliseconds, UTC."""
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t.replace(microsecond=t.microsecond // 1000 * 1000)


def _js_iso(t: datetime) -> str:
    """new Date(...).toISOString().replace("Z", "+00:00"): the string the page compares."""
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}+00:00"


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


def presenting(items: list[dict], objs: dict, reading: str) -> list[dict]:
    """The litigation items a page lists under one reading, each with the date it reads.
    cl_fold.plan_case's grouping: a tracker note folds per case; a CourtListener item folds
    by entry -- the END of the twin_of chain under 'objects', its own object under 'tier1';
    an item with no object presents itself. The earliest fetched (then lowest id) presents
    its group, so its fetched_at is the entry's first-seen time."""
    if reading == "rows":
        return [{**it, "at": it["occurred_at"]} for it in items]
    groups: dict = {}
    out = []
    for it in items:
        key = None
        if it["source_id"] == "seed-cases":
            key = ("b2", it["case_id"])
        elif it["cl_entry_id"] in objs and objs[it["cl_entry_id"]]["case_id"] == it["case_id"]:
            root, seen = it["cl_entry_id"], set()
            while reading == "objects" and objs[root]["twin_of"] in objs and root not in seen:
                seen.add(root)
                root = objs[root]["twin_of"]
            key = ("a1", it["case_id"], root)
        if key is None:
            out.append({**it, "at": it["occurred_at"]})
        else:
            groups.setdefault(key, []).append(it)
    for key, members in groups.items():
        members.sort(key=lambda m: (m["fetched_at"] or "", m["id"]))
        if key[0] == "a1":
            root = objs[key[2]]
            at = root["entry_at"] if root["entry_at"] is not None else root["row_at"]
        else:
            at = next((m["occurred_at"] for m in members if m["occurred_at"]), None)
        out.append({**members[0], "at": at})
    return out


def _entries(objs: dict, rows: list[dict], reading: str) -> tuple[dict, dict]:
    """({case: entry count}, {case: latest entry date}) under one reading: rows, or held
    objects (not twins, under 'objects') plus the rows no object claims, each dated by its
    object (record_entries' definition)."""
    count: dict = {}
    latest: dict = {}

    def add(case, at):
        count[case] = count.get(case, 0) + 1
        if at is not None and (latest.get(case) is None or at > latest[case]):
            latest[case] = at
    for r in rows:
        if reading == "rows" or r["cl_entry_id"] is None:
            add(r["case_id"], r["entry_at"])
    if reading != "rows":
        for o in objs.values():
            if o["held"] == 1 and not (reading == "objects" and o["twin_of"] is not None):
                add(o["case_id"], o["entry_at"] if o["entry_at"] is not None else o["row_at"])
    return count, latest


def readings(conn) -> dict:
    """Every figure, read three ways from one state of the record."""
    anchor = conn.execute("SELECT MAX(fetched_at) FROM items").fetchone()[0]
    if anchor:
        at = _ms(anchor)
        day, week = _js_iso(at - timedelta(days=1)), _js_iso(at - timedelta(days=7))
    else:                                   # an empty record: no window holds anything
        day = week = "9999"
    items = [dict(r) for r in conn.execute(
        "SELECT id, case_id, source_id, admiralty_source, occurred_at, fetched_at, cl_entry_id "
        "FROM items WHERE channel = 'litigation' ORDER BY id").fetchall()]
    objs = {r["cl_entry_id"]: dict(r) for r in conn.execute(
        "SELECT o.cl_entry_id, o.case_id, o.twin_of, o.held, o.entry_at, o.current_row, "
        "e.entry_at AS row_at FROM cl_entries o LEFT JOIN case_entries e ON e.id = o.current_row").fetchall()}
    rows = [dict(r) for r in conn.execute("SELECT case_id, entry_at, cl_entry_id FROM case_entries").fetchall()]
    cases = [dict(r) for r in conn.execute(
        "SELECT case_id, state, latest_entry_at FROM cases ORDER BY case_id").fetchall()]
    out: dict = {"clock": anchor, "cases": cases, "views": {
        "items": {r["case_id"]: r["n"] for r in conn.execute(
            "SELECT case_id, COUNT(*) AS n FROM record_items WHERE channel = 'litigation' "
            "GROUP BY case_id").fetchall()},
        "entries": {r["case_id"]: r["n"] for r in conn.execute(
            "SELECT case_id, COUNT(*) AS n FROM record_entries GROUP BY case_id").fetchall()}}}
    for reading in READINGS:
        p = presenting(items, objs, reading)
        per: dict = {}
        for x in p:
            c = per.setdefault(x["case_id"], {"ledger": 0, "timeline": 0})
            c["timeline"] += 1
            c["ledger"] += x["admiralty_source"] != "B"
        count, latest = _entries(objs, rows, reading)
        table, order = ENTRY_TABLES[reading]
        out[reading] = {
            "wire": {"total": len(p),
                     "day": sum(1 for x in p if x["fetched_at"] >= day),
                     "week": sum(1 for x in p if x["fetched_at"] >= week),
                     "history": sum(1 for x in p if x["fetched_at"] >= day and x["at"]
                                    and (_day(x["fetched_at"]) - _day(x["at"])).days > HISTORY_DAYS),
                     "tracker_notes": sum(1 for x in p if x["source_id"] == "seed-cases")},
            "per": per, "entries": count, "latest": latest,
            "rejected": rejected(conn, table, order),
        }
    out["apart"] = {}
    owned = {r["cl_entry_id"] for r in rows if r["cl_entry_id"] is not None}
    for o in objs.values():
        if o["held"] == 1 and o["current_row"] is None and o["cl_entry_id"] not in owned:
            out["apart"][o["case_id"]] = out["apart"].get(o["case_id"], 0) + 1
    return out


def _move(r: dict, a: str, b: str, kind: str, on: str | None) -> dict:
    """The dated move from reading a to reading b: only the figures it moved."""
    A, B = r[a], r[b]
    wa, wb = A["wire"], B["wire"]
    wire = {k: [wa[k], wb[k]] for k in ("total", "day", "week", "history")}
    if kind == "merge":
        wire["tracker_notes"] = wa["tracker_notes"] - wb["tracker_notes"]   # of the drop
    move: dict = {"kind": kind, "on": on, "why": WHY if kind == "merge" else WHY_LINK,
                  "clock": r["clock"], "wire": {"litigation": wire},
                  "map": {"entries": [0, 0], "dockets_changed": 0}, "cases": {}}
    if kind == "merge":
        move["map"]["apart"] = 0
    rb, ra = A["rejected"], B["rejected"]
    move["rejected"] = {"count": [len(rb), len(ra)],
                        "states": {s: [rb.get(s), ra.get(s)] for s in sorted(set(rb) | set(ra))
                                   if rb.get(s) != ra.get(s)}}
    for c in r["cases"]:
        cid = c["case_id"]
        eb, ea = A["entries"].get(cid, 0), B["entries"].get(cid, 0)
        pb, pa = A["per"].get(cid, {}), B["per"].get(cid, {})
        apart = r["apart"].get(cid, 0) if kind == "merge" else 0
        if c["state"] is not None:
            move["map"]["entries"][0] += eb
            move["map"]["entries"][1] += ea
            move["map"]["dockets_changed"] += eb != ea
            if kind == "merge":
                move["map"]["apart"] += apart
        moved: dict = {}
        if eb != ea:
            moved["entries"] = [eb, ea]
        if apart:
            moved["apart"] = apart
        for k in ("ledger", "timeline"):
            if pb.get(k, 0) != pa.get(k, 0):
                moved[k] = [pb.get(k, 0), pa.get(k, 0)]
        lb = c["latest_entry_at"] if a == "rows" else A["latest"].get(cid)
        la = B["latest"].get(cid)
        if (lb or None) != (la or None):
            moved["latest_entry_at"] = [lb, la]
        if moved:
            move["cases"][cid] = moved
    return move


def _moved(m: dict) -> bool:
    w = m["wire"]["litigation"]
    return bool(m["cases"] or m["map"]["dockets_changed"] or m["rejected"]["states"]
                or m["rejected"]["count"][0] != m["rejected"]["count"][1]
                or any(w[k][0] != w[k][1] for k in ("total", "day", "week", "history")))


def figures(conn, on: str | None = None) -> dict:
    """{"on", "clock", "moves": [merge, link?], "unfolded": [...]}: every moving figure as
    the dated moves the page notes. A link move is written only when a link moved a figure."""
    r = readings(conn)
    on = on or (r["clock"][:10] if r["clock"] else None)
    links = conn.execute("SELECT COUNT(*) FROM cl_entries WHERE twin_of IS NOT NULL").fetchone()[0]
    moves = [_move(r, "rows", "tier1", "merge", on)]
    link = _move(r, "tier1", "objects", "link", on)
    link["links"] = links
    if links and _moved(link):
        moves.append(link)
    # The objects reading against what the views hold: a case the fold has not reached
    # reads differently in record_items, and its note would be wrong.
    per = r["objects"]["per"]
    unfolded = sorted({c for c in set(per) | set(r["views"]["items"])
                       if per.get(c, {}).get("timeline", 0) != r["views"]["items"].get(c, 0)}
                      | {c for c in set(r["objects"]["entries"]) | set(r["views"]["entries"])
                         if r["objects"]["entries"].get(c, 0) != r["views"]["entries"].get(c, 0)})
    return {"on": on, "clock": r["clock"], "moves": moves, "unfolded": unfolded}


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
        f = figures(conn, on)
        if f["unfolded"]:
            why.append(f"{len(f['unfolded'])} case(s) whose fold does not match the views "
                       f"({', '.join(f['unfolded'][:5])})")
        if why and "--incomplete" not in argv:
            print("REFUSED: the switch's figures would miss a later move -- " + "; ".join(why))
            return 2
        del f["unfolded"]
        from scripts import link_entry_twins as links
        f["pending_person"] = len(links.plan(conn, links.load_links())["person"])
        if why:
            f["incomplete"] = why
    finally:
        conn.close()
    path.write_text(json.dumps(f, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"clock {f['clock']}  on {f['on']}")
    for m in f["moves"]:
        w = m["wire"]["litigation"]
        print(f"move {m['kind']}" + (f" ({m['links']} links)" if m["kind"] == "link" else "") + ":")
        print(f"  Wire litigation  total {w['total'][0]:,} -> {w['total'][1]:,}  +24h {w['day'][0]} -> "
              f"{w['day'][1]}  +7d {w['week'][0]} -> {w['week'][1]}  older-than-7d {w['history'][0]} -> "
              f"{w['history'][1]}" + (f"  (tracker notes in the drop: {w['tracker_notes']})"
                                      if "tracker_notes" in w else ""))
        print(f"  map entries      {m['map']['entries'][0]:,} -> {m['map']['entries'][1]:,} "
              f"({m['map']['dockets_changed']} dockets change"
              + (f"; {m['map']['apart']} held apart)" if "apart" in m["map"] else ")"))
        print(f"  rejected states  {m['rejected']['count'][0]} -> {m['rejected']['count'][1]}  "
              f"moved: {m['rejected']['states'] or 'none'}")
        print(f"  cases that move  {len(m['cases'])}; latest_entry_at moves on "
              f"{sum(1 for v in m['cases'].values() if 'latest_entry_at' in v)}")
    print(f"pairs waiting for a person: {f['pending_person']}")
    print(f"  -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
