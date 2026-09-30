"""The fold: which item presents each docket entry, and with what text (R1 step d, Corey's
rulings of 2026-09-30).

Every item stays; the fold only says how the page reads them. It is written into five
`items` columns that no reader looked at before the switch, so building it moves nothing
a page shows:

  merged_into      the item this one is folded into; NULL for an item that presents an entry
  display_title    the presenting item's title with the SURVIVOR text (ruling 2)
  display_summary  the survivor text
  display_at       the entry's date now (it follows the object: Nevada's re-dated rows)
  updated_at       the latest fetched_at in the group (ruling c: "updated_at the latest")

GROUPS:
  * A1 items (CourtListener) by entry: an item's `cl_entry_id` object, or, for a tier-2
    twin, the object it is `twin_of`. Items with no object stay unfolded, one entry each.
  * B2 items (the tracker notes) by case: one subject per case, the notes mutable (ruling 7:
    the 89 repeats reach the Wire's litigation total, so B2 joins this unit).

WHICH ITEM PRESENTS: the earliest fetched (then lowest id). Its fetched_at is the entry's
first-seen time, so the record clock, the fresh dot and the Wire's +24h read "when psephos
first held this entry" -- ruling c's "fetched_at is the earliest" -- and a re-description
never makes an old entry look new.

WHICH TEXT (ruling 2, the hybrid): an entry's current text -- the text the object that IS
the entry serves now, its current row's. For a tier-1 entry that is the latest text, and a
clerk's FILED IN ERROR replaces the original on the page (the original stays in its row).
For a tier-2 pair the entry is the long-form object (link_entry_twins points the short
form's twin_of at it), so the long form is the text. A B2 subject shows its latest notes,
dated by the first copy that carried a date.
"""

from __future__ import annotations

COLS = ("merged_into", "display_title", "display_summary", "display_at", "updated_at")
_CHUNK = 50


def _prefix(item: dict, caption: str | None) -> str:
    """The caption part of an A1 title, which write_entries built as f"{caption}:
    {desc[:180]}" from the SEED caption. Taken off the item itself so the fold never
    renames a case; the cases row's caption only when the title does not have that shape."""
    title, summary = item["title"] or "", item["summary"] or ""
    tail = ": " + summary[:180]
    if summary and title.endswith(tail):
        return title[: len(title) - len(tail)]
    return caption or title.split(": ", 1)[0]


def plan_case(conn, case_id: str) -> dict[int, tuple]:
    """{item id: (merged_into, display_title, display_summary, display_at, updated_at)} for
    every litigation item on the case. Reads only."""
    caption = (conn.execute("SELECT caption FROM cases WHERE case_id = ?", (case_id,)).fetchone()
               or {"caption": None})["caption"]
    objs = {r["cl_entry_id"]: dict(r) for r in conn.execute(
        "SELECT o.cl_entry_id, o.twin_of, o.entry_at, o.description, e.description AS row_text, "
        "e.entry_at AS row_at FROM cl_entries o LEFT JOIN case_entries e ON e.id = o.current_row "
        "WHERE o.case_id = ?", (case_id,)).fetchall()}
    items = [dict(r) for r in conn.execute(
        "SELECT id, source_id, title, summary, occurred_at, fetched_at, cl_entry_id "
        "FROM items WHERE case_id = ? AND channel = 'litigation'", (case_id,)).fetchall()]

    groups: dict = {}
    want: dict[int, tuple] = {}
    for it in items:
        key = None
        if it["source_id"] == "seed-cases":
            key = ("b2",)
        elif it["cl_entry_id"] is not None and it["cl_entry_id"] in objs:
            # The entry is the END of the twin_of chain, the object record_entries counts
            # (twin_of IS NULL). link_entry_twins refuses to make a chain, but the fold must
            # agree with the count whatever links exist; a cycle stops the walk.
            root, seen = it["cl_entry_id"], set()
            while objs[root]["twin_of"] in objs and root not in seen:
                seen.add(root)
                root = objs[root]["twin_of"]
            key = ("a1", root)
        if key is None:
            want[it["id"]] = (None, None, None, None, None)
        else:
            groups.setdefault(key, []).append(it)

    for key, members in groups.items():
        members.sort(key=lambda m: (m["fetched_at"] or "", m["id"]))
        rep = members[0]
        updated = max(m["fetched_at"] or "" for m in members) or None
        if key[0] == "a1":
            root = objs[key[1]]
            text = root["row_text"] if root["row_text"] is not None else root["description"]
            at = root["entry_at"] if root["entry_at"] is not None else root["row_at"]
            shown = (f"{_prefix(rep, caption)}: {(text or '')[:180]}", text, at)
        else:
            latest = members[-1]
            at = next((m["occurred_at"] for m in members if m["occurred_at"]), None)
            shown = (latest["title"], latest["summary"], at)
        want[rep["id"]] = (None, *shown, updated)
        for m in members[1:]:
            want[m["id"]] = (rep["id"], None, None, None, None)
    return want


def refold_case(conn, case_id: str) -> dict:
    """Bring the case's fold columns to plan_case's answer, writing only what differs.
    Runs inside the caller's transaction. Returns counts."""
    want = plan_case(conn, case_id)
    have = {r["id"]: tuple(r[c] for c in COLS) for r in conn.execute(
        "SELECT id, " + ", ".join(COLS) + " FROM items WHERE case_id = ? AND channel = 'litigation'",
        (case_id,)).fetchall()}
    changed = [(iid, v) for iid, v in want.items() if have.get(iid) != v]
    for i in range(0, len(changed), _CHUNK):
        chunk = changed[i:i + _CHUNK]
        sets, params = [], []
        for k, col in enumerate(COLS):
            sets.append(f"{col} = CASE id " + " ".join("WHEN ? THEN ?" for _ in chunk) + " END")
            for iid, v in chunk:
                params += [iid, v[k]]
        params += [iid for iid, _ in chunk]
        conn.execute(f"UPDATE items SET {', '.join(sets)} WHERE id IN "
                     f"({', '.join('?' for _ in chunk)})", params)
    return {"items": len(want), "changed": len(changed),
            "merged": sum(1 for v in want.values() if v[0] is not None)}


LATEST_SQL = ("UPDATE cases SET latest_entry_at = "
              "(SELECT MAX(entry_at) FROM record_entries WHERE case_id = ?) WHERE case_id = ?")


def recompute_latest(conn, case_id: str) -> None:
    """cases.latest_entry_at from ENTRIES (the switch, R1): MAX over record_entries, so a
    re-dated entry counts at its date now and the stale row it left behind does not
    (Nevada 72026664: 2026-08-24 on the rows, 2026-08-20 on the entry). One definition
    with tools/coverage_audit section 4 and scripts/repair_latest_entry."""
    conn.execute(LATEST_SQL, (case_id, case_id))


def refold_quietly(conn, case_id: str) -> dict | None:
    """refold_case in ITS OWN transaction, for the collector's write paths: call it after
    the write it follows has committed. Never inside that write: an error that ends a
    transaction (an interrupt, an I/O error, a server-side rollback) would take the write
    with it, and a caller that went on would commit its mark or its receipt without the
    entries they record.

    A failure recovers the connection, prints, and leaves the fold for the next refold of
    the case or for the run's sweep (unfolded()), which finds it by its missing columns."""
    import sys
    try:
        out = refold_case(conn, case_id)
        conn.commit()
        return out
    except Exception as exc:   # noqa: BLE001 -- the fold is derived; the write it follows is not
        import db
        import run_signals
        try:
            db.recover(conn)
        except Exception:
            pass
        print(f"  fold {case_id}: not refolded, the next refold or the sweep finishes it -- "
              f"{run_signals.safe(exc)}", file=sys.stderr)
        return None


def unfolded(conn) -> list[str]:
    """Cases holding an item the fold has not reached: one in a group (it has an object,
    or it is a tracker note) that is neither folded into another nor presenting with a
    survivor. What a failed or skipped refold leaves, found by the columns alone."""
    return [r["case_id"] for r in conn.execute(
        "SELECT DISTINCT case_id FROM items WHERE channel = 'litigation' "
        "AND (cl_entry_id IS NOT NULL OR source_id = 'seed-cases') "
        "AND merged_into IS NULL AND display_title IS NULL AND case_id IS NOT NULL "
        "ORDER BY case_id").fetchall()]
