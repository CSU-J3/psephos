"""CourtListener docket-entry identity: which held rows are one upstream entry (R1).

Corey's rulings, 2026-09-30 (docs/status.md, "Duplicate rows at the source"): every
`case_entries` row and id is kept, and an object table sits on top -- `cl_entries`, one
row per CourtListener docket-entry object, keyed on CourtListener's own entry id, with
the text a mutable field. The D0 found 599 extra rows on 45 dockets because the only key
psephos had was (case_id, entry_at, description): a re-described entry inserted a new
row and a new item, and nothing tied the two back together.

This module holds the identity rules, used two ways:

  * POLL MODE (collectors.litigation.write_entries). Every polled entry carries its
    CourtListener `id`, so the row it lands on is stamped with it. An entry whose id is
    not yet known may ADOPT an existing row with no id by exact text; by whitespace or
    the one-sided "(Entered: ...)" stamp rule only when the row carries the entry's own
    document number and no other entry in the batch serves that number that day. That
    is the safe insert-time normalization the D0 measured (109 rows, 0 wrong at the
    group level), narrowed by what the objects showed: 9 of the 109 were tier-2 pairs,
    and on 73544809 one of them (88676/88680) is two CourtListener objects -- a stamped
    text and an unstamped one, neither with a document number. Adopting by text alone
    handed the older object's row to the newer one. The token is what the tier-1 re-
    renders share and the tier-2 twins do not.

  * WALK MODE (backfill_docket). One full walk of a docket sees every object at once,
    so it may also attach a row by its document-number token when exactly one upstream
    object carries that token. The walk writes ids, never new rows or items: it is the
    id backfill, not a re-collection, and nothing a page reads changes because of it.

What neither mode does is link two different CourtListener objects that describe one
minute entry (tier 2). No upstream field links them; that link is psephos's assertion,
made by a checked rule or by a person, and lives in `cl_entries.twin_of`.

CLOCKS. An object's `first_seen_at` and `updated_at` say when psephos HELD its text, never
when an id reached it. A new text is held now. A row held before ids were kept carries its
own evidence -- its `seen_at`, else its item's `fetched_at` -- and when it has none the
object's clock stays NULL for step (c) to derive from the id order, rather than taking the
walk's time and moving every legacy entry's clock to the backfill day.
"""

from __future__ import annotations

import re

import common

CL_BASE_WEB = "https://www.courtlistener.com"

# The trailing clerk stamp, "(Entered: 09/25/2025)" or "[Entered: 07/08/2026 02:19 PM]".
# The D0's own pattern (dup_d0 work2_ab/norm5.py), kept byte-for-byte so the 109 it
# measured is the rule this code applies.
STAMP = re.compile(r"\s*[\(\[]\s*Entered:\s*([^\)\]]*)[\)\]]\s*$", re.I)

# /docket/<docket id>/<document number or appellate document id>/[<attachment>/]<slug>/
# The appellate ids carry leading zeros that CourtListener has served both with and
# without (73544809: 89413/89450), so the token is the integer, not the string.
_TOKEN = re.compile(r"/docket/\d+/(\d+)/")


def ws(text: str) -> str:
    """Whitespace collapsed: the only character-level normalization the rule allows."""
    return " ".join((text or "").split())


def stamp_of(text: str) -> str | None:
    m = STAMP.search(text or "")
    return m.group(1).strip() if m else None


def unstamped(text: str) -> str:
    return STAMP.sub("", text or "")


def doc_token(url: str | None) -> str | None:
    m = _TOKEN.search(url or "")
    return str(int(m.group(1))) if m else None


def derive(e: dict) -> tuple[str | None, str, str | None] | None:
    """(entry_at, description, document_url) exactly as write_entries has always derived
    them, or None for an entry with no text at all (never held, never counted)."""
    entry_at = common.to_iso(e.get("date_filed"))
    docs = e.get("recap_documents") or []
    # Document-only entries have an empty entry-level description; the PACER text then
    # lives on the document (e.g. "Order on Motion for Briefing Schedule").
    desc = (e.get("description") or "").strip()
    if not desc and docs:
        desc = (docs[0].get("description") or docs[0].get("short_description") or "").strip()
    if not desc:
        return None
    doc_url = None
    if docs and docs[0].get("absolute_url"):
        doc_url = CL_BASE_WEB + docs[0]["absolute_url"]
    return entry_at, desc, doc_url


def desc_source(e: dict) -> str:
    """'entry' when the text is the entry's own description, 'document' when it fell back
    to the first document's. With `time_filed` and `date_created` this is the fingerprint
    the D0 found on all three sampled tier-2 pairs: the short object's text comes from its
    document and it carries a time_filed; the full-text object's does not."""
    return "entry" if (e.get("description") or "").strip() else "document"


def same_object_cosmetic(a: str, b: str) -> bool:
    """Two texts ONE KNOWN OBJECT served that differ only by the stamp or whitespace.

    Both-sided on purpose: the id already fixes identity, so a stamp added or dropped
    cannot fuse two entries here. Across objects the rule is one-sided (below)."""
    return ws(unstamped(a)) == ws(unstamped(b))


def adopts(new: str, held: str) -> str | None:
    """Whether a text from an entry whose id psephos has not seen may land on a held row
    that carries no id: 'ws' (equal once whitespace is collapsed), 'stamp' (the new text
    is the held one plus a trailing stamp), else None.

    ONE-SIDED. A stamped text matches only an unstamped held text. Two same-day filings
    on an appellate docket can differ only in the time inside their stamps, so a
    two-sided rule fused 23 distinct entries in the D0; this one fused none."""
    if ws(new) == ws(held):
        return "ws"
    if stamp_of(new) is not None and stamp_of(held) is None and ws(unstamped(new)) == ws(held):
        return "stamp"
    return None


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
def load_object(conn, cl_id: int):
    return conn.execute("SELECT * FROM cl_entries WHERE cl_entry_id = ?", (cl_id,)).fetchone()


def _rows_on(conn, case_id: str, entry_at: str | None) -> list:
    return conn.execute(
        "SELECT id, description, document_url, cl_entry_id FROM case_entries "
        "WHERE case_id = ? AND entry_at IS ?", (case_id, entry_at)).fetchall()


def _link_item(conn, case_id: str, entry_at: str | None, desc: str, cl_id: int) -> None:
    """Stamp the A1 item that presents this row's text with its object, if it has one.
    Items are keyed on the row's text (content_hash(case_id, entry_at, desc)), so this
    finds exactly the item write_entries made for it."""
    conn.execute(
        "UPDATE items SET cl_entry_id = ? WHERE content_hash = ? AND cl_entry_id IS NULL",
        (cl_id, common.content_hash(case_id, entry_at, desc)))


# --------------------------------------------------------------------------- #
# Poll mode
# --------------------------------------------------------------------------- #
def resolve_polled(conn, case_id: str, cl_id: int, entry_at: str | None, desc: str,
                   doc_url: str | None, now: str,
                   shared: frozenset = frozenset()) -> tuple[int | None, str]:
    """The row a polled entry's text lands on, inserting one only for a text this object
    has not served before. Returns (row id or None, how).

      how = 'same'      the object's current row already holds this text
            'history'   an earlier text of this object came back (A -> B -> A), exactly
                        or with only a stamp or spacing change
            'cosmetic'  the object re-served its current text with a stamp or spacing change
            'adopted'   the object took over a held row with no id (exact text)
            'adopted-ws' / 'adopted-stamp'   an unknown object took one over by the safe
                        normalization: same document number, same day, one candidate
            'inserted'  a new text: a new row, carrying the id
            'apart'     the text is already ANOTHER object's row on this day, so it is kept
                        on the object and not in case_entries (the UNIQUE key)

    ORDER MATTERS, and it is: this object's own exact row, then its own same-day rows
    by the cosmetic rule, then a row nobody owns, then another object's. A known entry's
    stamp re-render must land on its own row before a twin's identical text can claim it
    (73544809: 477057380 and 477084921 serve one text, one stamped).

    `shared` holds the (entry_at, document number) pairs more than one entry in this batch
    serves: a stamp or spacing adoption is refused on them, the walk's "wanted by exactly
    one object" guard in the only form a poll can apply."""
    obj = load_object(conn, cl_id)
    rows = _rows_on(conn, case_id, entry_at)
    exact = next((r for r in rows if r["description"] == desc), None)

    if exact is not None and exact["cl_entry_id"] == cl_id:
        same = obj is not None and obj["current_row"] == exact["id"]
        return exact["id"], ("same" if same else "history")

    if obj is not None:
        own = sorted((r for r in rows if r["cl_entry_id"] == cl_id),
                     key=lambda r: (r["id"] != obj["current_row"], -r["id"]))
        for r in own:
            if same_object_cosmetic(desc, r["description"]):
                return r["id"], ("cosmetic" if r["id"] == obj["current_row"] else "history")

    if exact is not None:
        if exact["cl_entry_id"] is None:
            conn.execute("UPDATE case_entries SET cl_entry_id = ? WHERE id = ?",
                         (cl_id, exact["id"]))
            _link_item(conn, case_id, entry_at, desc, cl_id)
            return exact["id"], "adopted"
        return None, "apart"

    tok = doc_token(doc_url)
    if obj is None and tok is not None and (entry_at, tok) not in shared:
        # The uniqueness guard: exactly one held row with no id, carrying this entry's
        # document number on this day, qualifies -- and by exactly one rule.
        cands = [(r, how) for r in rows
                 if r["cl_entry_id"] is None and doc_token(r["document_url"]) == tok
                 for how in [adopts(desc, r["description"])] if how]
        if len(cands) == 1:
            r, how = cands[0]
            conn.execute("UPDATE case_entries SET cl_entry_id = ? WHERE id = ?",
                         (cl_id, r["id"]))
            _link_item(conn, case_id, entry_at, r["description"], cl_id)
            return r["id"], f"adopted-{how}"

    cur = conn.execute(
        "INSERT OR IGNORE INTO case_entries "
        "(case_id, entry_at, description, document_url, cl_entry_id, seen_at) "
        "VALUES (?, ?, ?, ?, ?, ?)", (case_id, entry_at, desc, doc_url, cl_id, now))
    if cur.rowcount > 0:
        row = conn.execute("SELECT id FROM case_entries WHERE case_id = ? AND entry_at IS ? "
                           "AND description = ?", (case_id, entry_at, desc)).fetchone()
        return row["id"], "inserted"
    return None, "apart"   # unreachable while the exact lookup above sees every row


def _held_since(conn, case_id: str, row_id: int) -> str | None:
    """When psephos first held a row's text: its seen_at, else its item's fetched_at, else
    None (a pre-R1 row with no item -- step (c) bounds it by the id order)."""
    r = conn.execute("SELECT entry_at, description, seen_at FROM case_entries WHERE id = ?",
                     (row_id,)).fetchone()
    if r is None:
        return None
    if r["seen_at"]:
        return r["seen_at"]
    it = conn.execute("SELECT fetched_at FROM items WHERE content_hash = ?",
                      (common.content_hash(case_id, r["entry_at"], r["description"]),)).fetchone()
    return it["fetched_at"] if it else None


def record_object(conn, case_id: str, e: dict, entry_at: str | None, desc: str,
                  row_id: int | None, how: str, now: str) -> bool:
    """Upsert the object. Returns True when its current text or date moved (a revision).

    `updated_at` moves only on a revision or when psephos first holds the entry, so it
    reads "when psephos last saw this entry change", not "when it was last polled". A new
    object that ADOPTED a row held before ids takes that row's own evidence, not `now`."""
    obj = load_object(conn, e["id"])
    if obj is None:
        if how.startswith("adopted") and row_id:
            seen = _held_since(conn, case_id, row_id)
        elif how == "apart":
            # Its text is another object's row on this day: that row is when psephos first
            # held it, the rule the walk applies too, so both orders give one clock.
            other = conn.execute("SELECT id FROM case_entries WHERE case_id = ? AND "
                                 "entry_at IS ? AND description = ?",
                                 (case_id, entry_at, desc)).fetchone()
            seen = _held_since(conn, case_id, other["id"]) if other else None
        else:
            seen = now
        conn.execute(
            "INSERT INTO cl_entries (cl_entry_id, case_id, entry_number, entry_at, description, "
            "current_row, held, first_seen_at, updated_at, date_modified, time_filed, "
            "date_created, desc_source) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)",
            (e["id"], case_id, e.get("entry_number"), entry_at, desc, row_id, seen, seen,
             e.get("date_modified"), e.get("time_filed"), e.get("date_created"),
             desc_source(e)))
        return False
    # A stamp or spacing change is not a revision: it lands on the same row (cosmetic).
    # A held-apart object has no row, so there its text is what can move.
    moved = (obj["current_row"] != row_id or obj["entry_at"] != entry_at
             or (row_id is None and obj["description"] != desc))
    # A walk-only object (held = 0) that a poll now serves is held from this poll on. A
    # legacy object with no evidence keeps its NULL: a re-serve is not when it was held.
    first = obj["first_seen_at"] or (now if obj["held"] == 0 else None)
    conn.execute(
        "UPDATE cl_entries SET entry_number = ?, entry_at = ?, description = ?, "
        "current_row = ?, held = 1, date_modified = ?, updated_at = ?, first_seen_at = ?, "
        "time_filed = ?, date_created = COALESCE(date_created, ?), desc_source = ? "
        "WHERE cl_entry_id = ?",
        (e.get("entry_number"), entry_at, desc, row_id, e.get("date_modified"),
         now if moved else obj["updated_at"], first, e.get("time_filed"),
         e.get("date_created"), desc_source(e), e["id"]))
    return moved


# --------------------------------------------------------------------------- #
# Walk mode: the id backfill
# --------------------------------------------------------------------------- #
_CHUNK = 100


def _set_ids(conn, table: str, pairs: list[tuple[int, int]]) -> None:
    """cl_entry_id for many rows in a few statements. Each execute is a round trip on
    Turso, and a docket's walk touches every held row: one UPDATE a row would be ~19,000
    statements for the whole backfill, where chunks of 100 make it a few hundred."""
    for i in range(0, len(pairs), _CHUNK):
        chunk = pairs[i:i + _CHUNK]
        whens = " ".join("WHEN ? THEN ?" for _ in chunk)
        marks = ", ".join("?" for _ in chunk)
        params = [x for pair in chunk for x in pair] + [rid for rid, _ in chunk]
        conn.execute(f"UPDATE {table} SET cl_entry_id = CASE id {whens} END "
                     f"WHERE id IN ({marks})", params)


def _insert_objects(conn, objs: list[tuple]) -> None:
    cols = ("cl_entry_id, case_id, entry_number, entry_at, description, current_row, held, "
            "first_seen_at, updated_at, date_modified, time_filed, date_created, desc_source")
    for i in range(0, len(objs), _CHUNK):
        chunk = objs[i:i + _CHUNK]
        marks = ", ".join("(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)" for _ in chunk)
        conn.execute(f"INSERT INTO cl_entries ({cols}) VALUES {marks}",
                     [x for o in chunk for x in o])

def backfill_docket(conn, case_id: str, entries: list[dict], now: str) -> dict:
    """Attach CourtListener ids to one docket's held rows from a full walk of it.

    Writes ids, objects and item links only -- never a row or an item -- and runs inside
    the caller's transaction. Rows an earlier poll already stamped keep their owner.

    Matching, in order, each step only over rows no earlier step (or poll) claimed:
      1. exact    (entry_at, description) equal to the text an object serves now
      2. adopt    the safe normalization, same day, exactly one candidate
      3. token    the row's document number, when exactly one upstream object carries it
                  (any date and text: this is what attaches an earlier description)
    A row left over is UNATTACHED: counted in the report, kept, and counted on its own
    until something ties it to an object.

    Each object's current row is the attached row whose text it serves now (exact, else
    same-object cosmetic, same day). An object with attached rows none of which holds
    its current text keeps the newest of them as current and is reported STALE -- the
    text will land by the ordinary write path the next time a poll serves it. An object
    with no attached row is recorded held = 0: seen by the walk only, never shown."""
    served = []
    seen_ids: set[int] = set()
    for e in entries:
        d = derive(e)
        if d is None or e.get("id") is None or e["id"] in seen_ids:
            continue   # no text, no id, or a page boundary serving an object twice
        seen_ids.add(e["id"])
        entry_at, desc, doc_url = d
        served.append({"e": e, "id": e["id"], "entry_at": entry_at, "desc": desc,
                       "token": doc_token(doc_url)})
    rows = {r["id"]: dict(r) for r in conn.execute(
        "SELECT id, entry_at, description, document_url, cl_entry_id, seen_at FROM case_entries "
        "WHERE case_id = ?", (case_id,)).fetchall()}
    owner = {rid: r["cl_entry_id"] for rid, r in rows.items()}
    by_text = {(r["entry_at"], r["description"]): rid for rid, r in rows.items()}

    counts = {"objects": len(served), "exact": 0, "adopted": 0, "token": 0,
              "token_shared": 0, "unattached": 0, "never_held": 0, "stale": 0,
              "apart": 0}

    # 1. exact
    for s in served:
        rid = by_text.get((s["entry_at"], s["desc"]))
        if rid is not None and owner[rid] is None:
            owner[rid] = s["id"]
            counts["exact"] += 1

    # 2. the safe normalization, unique BOTH ways: an unclaimed row is adopted only when
    #    exactly one served object's text reaches it (same day, `adopts`), and that
    #    object's text reaches no other unclaimed row. Counted over EVERY served object,
    #    those that already hold a row included: an object that owns its stamped text
    #    still takes its earlier unstamped one (a poll can have inserted the first), and
    #    a rival that took a row in step 1 still blocks a second object from its twin's
    #    text (73544809: 477057380 re-stamped to 477084921's exact text).
    reach: dict[int, list] = {}
    for s in served:
        cands = [rid for rid, r in rows.items()
                 if owner[rid] is None and r["entry_at"] == s["entry_at"]
                 and adopts(s["desc"], r["description"])]
        for rid in cands:
            reach.setdefault(rid, []).append((s["id"], len(cands)))
    for rid, who in reach.items():
        if len(who) == 1 and who[0][1] == 1:
            owner[rid] = who[0][0]
            counts["adopted"] += 1

    # 3. token
    by_token: dict[str, list] = {}
    for s in served:
        if s["token"]:
            by_token.setdefault(s["token"], []).append(s["id"])
    for rid, r in rows.items():
        if owner[rid] is not None:
            continue
        t = doc_token(r["document_url"])
        if not t or t not in by_token:
            continue
        if len(by_token[t]) == 1:
            owner[rid] = by_token[t][0]
            counts["token"] += 1
        else:
            counts["token_shared"] += 1

    counts["unattached"] = sum(1 for o in owner.values() if o is None)

    # Write ids onto the rows that gained one, and onto each such row's item. Items are
    # keyed on their row's text, so the hash finds exactly the item write_entries made.
    gained = sorted((rid, o) for rid, o in owner.items()
                    if o is not None and rows[rid]["cl_entry_id"] is None)
    _set_ids(conn, "case_entries", gained)
    items = {r["content_hash"]: dict(r) for r in conn.execute(
        "SELECT id, content_hash, fetched_at, cl_entry_id FROM items WHERE case_id = ?",
        (case_id,)).fetchall()}

    def item_of(rid):
        return items.get(common.content_hash(case_id, rows[rid]["entry_at"],
                                             rows[rid]["description"]))

    linked = []
    for rid, o in gained:
        it = item_of(rid)
        if it is not None and it["cl_entry_id"] is None:
            linked.append((it["id"], o))
    _set_ids(conn, "items", sorted(linked))

    def held_times(rids):
        out = []
        for rid in rids:
            if rows[rid]["seen_at"]:
                out.append(rows[rid]["seen_at"])
            else:
                it = item_of(rid)
                if it is not None:
                    out.append(it["fetched_at"])
        return out

    # Objects.
    known = {r["cl_entry_id"] for r in conn.execute(
        "SELECT cl_entry_id FROM cl_entries WHERE case_id = ?", (case_id,)).fetchall()}
    fresh: list[tuple] = []
    attached: dict[int, list[int]] = {}
    for rid, o in owner.items():
        if o is not None:
            attached.setdefault(o, []).append(rid)
    for s in served:
        mine = sorted(attached.get(s["id"], []))
        current = None
        for rid in mine:
            r = rows[rid]
            if r["entry_at"] == s["entry_at"] and r["description"] == s["desc"]:
                current = rid
                break
        if current is None:
            for rid in reversed(mine):
                r = rows[rid]
                if r["entry_at"] == s["entry_at"] and same_object_cosmetic(s["desc"], r["description"]):
                    current = rid
                    break
        held = 1
        if current is None and mine:
            current = mine[-1]
            counts["stale"] += 1
        elif not mine:
            # Its text is another object's row on this day (the UNIQUE key kept one), or
            # psephos never held it at all.
            if (s["entry_at"], s["desc"]) in by_text:
                counts["apart"] += 1
            else:
                held = 0
                counts["never_held"] += 1
        if s["id"] not in known:
            # Its clock is what psephos held, never the walk's time: the earliest and
            # latest evidence its rows carry, or NULL for step (c) to derive. A held-apart
            # object's text is on another object's row, and that row is its evidence --
            # the same rule record_object applies to a poll.
            times = held_times(mine or ([by_text[(s["entry_at"], s["desc"])]]
                                        if held and (s["entry_at"], s["desc"]) in by_text
                                        else []))
            fresh.append((s["id"], case_id, s["e"].get("entry_number"), s["entry_at"],
                          s["desc"], current, held, min(times) if times else None,
                          max(times) if times else None, s["e"].get("date_modified"),
                          s["e"].get("time_filed"), s["e"].get("date_created"),
                          desc_source(s["e"])))
            known.add(s["id"])
        else:
            # A poll already recorded it: the poll's own resolution stands, but the walk
            # fills what the poll could not know (entry_number, date_modified).
            conn.execute(
                "UPDATE cl_entries SET entry_number = COALESCE(entry_number, ?), "
                "date_modified = COALESCE(?, date_modified), "
                "time_filed = COALESCE(time_filed, ?), date_created = COALESCE(date_created, ?), "
                "desc_source = COALESCE(desc_source, ?) WHERE cl_entry_id = ?",
                (s["e"].get("entry_number"), s["e"].get("date_modified"),
                 s["e"].get("time_filed"), s["e"].get("date_created"), desc_source(s["e"]),
                 s["id"]))
            if mine:
                # A poll held it apart (no row), and the walk has now given it rows: the
                # row the walk found current is the one it serves. A row a poll resolved
                # is never replaced.
                conn.execute("UPDATE cl_entries SET current_row = ?, held = 1 "
                             "WHERE cl_entry_id = ? AND current_row IS NULL",
                             (current, s["id"]))
    _insert_objects(conn, fresh)
    return counts
