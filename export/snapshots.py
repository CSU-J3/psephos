"""Deterministic JSON snapshots from the items spine.

Five files under data/, one per product. Each must also be named in `collect.yml`'s
`git add` line, which stages snapshots explicitly (never `git add data/`, because
data/psephos.db is not gitignored) -- a new file omitted there is written every run
and committed by none of them, silently, since this module prints it either way.

  bills.json  -- per-bill timelines: legislation actions (A1) interleaved with the
                 news that explains them (C3/B2), in date order. Same-event news is
                 grouped into one node by a curated anchor (config: event_anchors),
                 additively -- every item still appears exactly once.
  cases.json  -- per-case timelines: CourtListener docket entries (A1) plus the
                 tracker framing (B2). No news, no litigation<->news join.
  executive.json -- the executive channel as a flat, date-ordered list: Federal
                 Register documents (A1). No bill/case scope, no clustering.
  news.json   -- the B2 news feed: a flat, date-ordered list of items from the
                 maintained expert trackers. NOT the news channel -- see below.
  state_bills.json -- per-state-bill timelines, flat and date-ordered, keyed by
                 state_bill_id (LegiScan, B2).

NO ROUTE READS ANY OF THESE, and the docstring should not imply otherwise.
`web/lib/db.ts` is a Turso client and every route is force-dynamic, so all five
files are written every run and consumed by nothing in the running system. What
they earn their place as is the diff-friendly committed record -- the evidentiary
spine that makes "exactly three case objects changed" checkable years later --
and NOT as "the input for the view", which the spec still says and which stopped
being true when the view moved to Turso. Whether that archive is worth ~4 MB
rewritten four times a day is an open question in docs/status.md. It is not a
reason to read this module as feeding a page.

The output is byte-identical for an unchanged DB: entries sort by (date, id),
cluster members by id, object keys are sorted, and NO wall-clock timestamp is
written. So an unchanged DB produces an empty git diff.

Run from the repo root:  python -m export.snapshots
"""

from __future__ import annotations

import json
from pathlib import Path

import config
import db

BILLS_PATH = "data/bills.json"
CASES_PATH = "data/cases.json"
EXECUTIVE_PATH = "data/executive.json"
STATE_BILLS_PATH = "data/state_bills.json"
NEWS_PATH = "data/news.json"

# A cluster node needs at least this many members; a lone anchor match stays a
# standalone item (a 1-member "cluster" would add nothing and only obscure it).
MIN_CLUSTER = 2


# --- grading -----------------------------------------------------------------

def grade_str(row) -> str:
    """Admiralty grade as a compact string, e.g. 'A1' / 'C3'."""
    return f"{row['admiralty_source']}{row['admiralty_info']}"


def _grade_key(grade: str) -> tuple[str, int]:
    """Sort key where the STRONGEST grade is smallest: 'A1' < 'B2' < 'C3'.

    Source reliability A-F (A strongest) then info credibility 1-6 (1 strongest).
    """
    letter = grade[:1]
    try:
        info = int(grade[1:])
    except ValueError:
        info = 99
    return (letter, info)


def strongest(grades) -> str:
    """The strongest Admiralty grade in the node. Count NEVER enters this."""
    return min(grades, key=_grade_key)


# --- anchors -----------------------------------------------------------------

def _phrases(anchor) -> list[str]:
    """Anchor `phrase` may be a str or a list of str; normalize to a lowered list."""
    p = anchor.get("phrase", [])
    items = [p] if isinstance(p, str) else list(p)
    return [s.casefold() for s in items]


def _in_window(occurred_at, anchor) -> bool:
    """True if the item's date falls in [start, end] inclusive (date-only compare)."""
    if not occurred_at:
        return False
    win = anchor.get("window", {})
    start, end = win.get("start"), win.get("end")
    date = str(occurred_at)[:10]
    return bool(start) and bool(end) and start <= date <= end


def _matches(row, anchor) -> bool:
    """A news item matches an anchor iff it is in-window AND its title contains
    one of the anchor phrases. Curated narrow phrases make substring safe and
    fully deterministic (no similarity threshold)."""
    if row["channel"] != "news":
        return False
    if not _in_window(row["occurred_at"], anchor):
        return False
    title = (row["title"] or "").casefold()
    return any(p in title for p in _phrases(anchor))


# --- entry assembly ----------------------------------------------------------

def _item_entry(row) -> dict:
    return {
        "kind": "item",
        "id": row["id"],
        "channel": row["channel"],
        "source_id": row["source_id"],
        "source_url": row["source_url"],
        "title": row["title"],
        "occurred_at": row["occurred_at"],
        "grade": grade_str(row),
    }


def _member(row) -> dict:
    return {
        "id": row["id"],
        "source_id": row["source_id"],
        "source_url": row["source_url"],
        "title": row["title"],
        "occurred_at": row["occurred_at"],
        "grade": grade_str(row),
    }


def _sort_key(entry):
    """Order entries by (date, id). A cluster sorts by its earliest member date
    and smallest member id. `None`/'' dates sort first, deterministically."""
    if entry["kind"] == "cluster":
        dates = [m["occurred_at"] or "" for m in entry["members"]]
        return (min(dates), entry["members"][0]["id"])
    return (entry["occurred_at"] or "", entry["id"])


def _build_timeline(rows, anchors) -> list[dict]:
    """Additive grouping: every row becomes exactly one entry, either a standalone
    item or a member of one cluster node. First matching anchor wins (config
    order); anchors are expected non-overlapping."""
    # Assign each row to the first anchor it matches (or None).
    assigned: dict[int, list] = {}     # anchor index -> [rows]
    standalone = []
    for row in rows:
        hit = next((i for i, a in enumerate(anchors) if _matches(row, a)), None)
        if hit is None:
            standalone.append(row)
        else:
            assigned.setdefault(hit, []).append(row)

    entries = [_item_entry(r) for r in standalone]

    for idx, members in assigned.items():
        if len(members) < MIN_CLUSTER:
            # Lone match: stays a standalone item -- lossless, never dropped.
            entries.extend(_item_entry(r) for r in members)
            continue
        member_objs = sorted((_member(r) for r in members), key=lambda m: m["id"])
        anchor = anchors[idx]
        entries.append({
            "kind": "cluster",
            "anchor": anchor["id"],
            "label": anchor.get("label", anchor["id"]),
            "date": min(m["occurred_at"] or "" for m in member_objs),
            "grade": strongest([m["grade"] for m in member_objs]),
            "source_count": len(member_objs),
            "members": member_objs,
        })

    return sorted(entries, key=_sort_key)


# --- products ----------------------------------------------------------------

def build_bills(conn, anchors) -> list[dict]:
    """Per-bill objects sorted by bill_id. Timeline = legislation + news items on
    the bill. bill_relations are intentionally NOT surfaced (the action log
    carries the maneuver; is_vehicle carries the vehicle signal)."""
    out = []
    bills = conn.execute("SELECT * FROM bills ORDER BY bill_id").fetchall()
    for b in bills:
        rows = conn.execute(
            "SELECT * FROM items WHERE bill_id = ? ORDER BY occurred_at, id", (b["bill_id"],)
        ).fetchall()
        bill_anchors = [a for a in anchors if a.get("bill") == b["bill_id"]]
        out.append({
            "bill_id": b["bill_id"],
            "congress": b["congress"],
            "bill_type": b["bill_type"],
            "number": b["number"],
            "short_title": b["short_title"],
            "sponsor": b["sponsor"],
            "status": b["status"],
            "is_vehicle": bool(b["is_vehicle"]),
            "latest_action": b["latest_action"],
            "latest_action_at": b["latest_action_at"],
            "timeline": _build_timeline(rows, bill_anchors),
        })
    return out


def build_cases(conn) -> list[dict]:
    """Per-case objects sorted by case_id. Timeline = docket (A1) + tracker framing
    (B2) items keyed by case_id. No clustering (anchors are bill-scoped), no news.

    Emits 14 of the table's 17 columns. The three held back, deliberately:
    `updated_at` and `entries_synced_at` both move independently of content -- the
    first on every touch, the second as an upstream high-water mark -- and either
    would rewrite this file four times a day with no change in what it says, which
    is exactly the property the archive exists for (see the state_bills precedent,
    test_state_bills_json_stable_despite_moving_updated_at). `seeded_from` is
    non-null on all 46 rows with a single distinct value, so it would add a constant
    key carrying no information.

    The omission this docstring exists to prevent is not a missing column but a
    missing METHOD: the original inventory of what was absent was written by reading
    the code and came out at five when the answer was seven. The check is
    PRAGMA table_info(cases) differenced against the emitted keys, which is a query.
    """
    out = []
    cases = conn.execute("SELECT * FROM cases ORDER BY case_id").fetchall()
    for c in cases:
        rows = conn.execute(
            "SELECT * FROM items WHERE case_id = ? ORDER BY occurred_at, id", (c["case_id"],)
        ).fetchall()
        entries = sorted((_item_entry(r) for r in rows), key=_sort_key)
        out.append({
            "case_id": c["case_id"],
            "caption": c["caption"],
            "court": c["court"],
            "docket_number": c["docket_number"],
            "category": c["category"],
            "status": c["status"],
            "plaintiff": c["plaintiff"],
            "defendant": c["defendant"],
            "filed_at": c["filed_at"],
            "superseded_by": c["superseded_by"],   # this docket's continuation: the circuit
                                                   # appeal or venue refile that replaced it
                                                   # (handoff 13/14/37). Set on the terminated
                                                   # row, pointing forward; null on all but the
                                                   # seven terminated source rows.
            # The four below were in the table and not in the file. Their absence was
            # invisible for as long as it lasted, because nothing read the snapshot for
            # them -- it surfaced only when the board's mock had to join back to
            # data/doj_cases.json for every per-state figure, and when status_audit
            # reported export lag as database drift. Key ORDER here is presentational:
            # write_json serialises with sort_keys=True, so the file is alphabetical
            # whatever this literal says.
            "state": c["state"],                   # the key every per-state reading needs.
                                                   # Written by upsert_case through
                                                   # normalize_state, which strips the
                                                   # "Georgia (1)" suffix at the boundary.
                                                   # NULL on the three federal-defendant rows
                                                   # (Common Cause v. DOJ, LWV v. DHS, and the
                                                   # D.C. Circuit successor 26-5243) -- a suit
                                                   # against a federal agency has no state.
                                                   # NOT derivable from `court`: 14 rows are
                                                   # circuit rows and a circuit spans several.
            "latest_entry_at": c["latest_entry_at"],   # the column getCases ORDERS BY. Absent,
                                                       # the ordering could not be checked
                                                       # against the snapshot at all.
            "status_checked_at": c["status_checked_at"],   # the receipt proving `status` was
                                                           # re-read. Its absence is what let
                                                           # a stale write-once premise stand.
            "source_url": c["source_url"],         # every other exported object carries one;
                                                   # without it a case cannot be opened from
                                                   # the snapshot.
            # THE RAW DOCKET LENGTH, WHICH IS NOT len(timeline). write_entries inserts
            # every docket entry into case_entries and promotes only those passing
            # is_substantive into items; the timeline below is built from items, so it
            # is the PROMOTED subset. Both numbers are real and they answer different
            # questions -- "how long is this docket" vs "how much of it was worth an
            # item". Measured across all 46 cases on 2026-08-19: raw 4,594, promoted
            # 2,170, and the two differ on EVERY row (0 of 46 equal, and promoted
            # never exceeds raw, which it cannot). A reader who assumes
            # entry_count == len(timeline) is wrong by a factor of two.
            "entry_count": conn.execute(
                "SELECT COUNT(*) FROM case_entries WHERE case_id = ?", (c["case_id"],)
            ).fetchall()[0][0],
            "timeline": entries,
        })
    return out


def build_executive(conn) -> list[dict]:
    """The executive channel as a flat, date-ordered list. No bill/case scope and
    no clustering (anchors are bill-scoped); reuses _item_entry / _sort_key."""
    rows = conn.execute(
        "SELECT * FROM items WHERE channel = 'executive' ORDER BY occurred_at, id"
    ).fetchall()
    return sorted((_item_entry(r) for r in rows), key=_sort_key)


def build_news(conn) -> list[dict]:
    """The B2 news feed: a flat, date-ordered list. Reuses _item_entry / _sort_key.

    THIS IS NOT THE NEWS CHANNEL, and the difference is most of it. Measured
    against Turso 2026-08-13: the channel holds 3,407 items and this file holds
    432; the 2,975 excluded are Google News aggregates. The exclusion is the
    SPEC'S OWN GRADING RULE rather than a source blocklist: `config/sources.yaml`
    grades that source C3 with the note "aggregated; corroborate before promoting
    an item", and the spec says in as many words that an uncorroborated aggregate
    must not drive the timeline. Anywhere this file's count is quoted, quote the
    excluded count with it.

    THOSE TWO NUMBERS MOVE, the excluded one fastest, so they are dated here and
    `main()` prints both live on every run. The print is the current value; this
    docstring is a reading. The plan for this unit carried 2,955 and the same
    day's query read 2,975 -- twenty Google News items, one cron apart, which is
    all it takes for a hardcoded complement to go stale.

    ONE LIMITATION, STATED RATHER THAN DECIDED HERE. The spec's grading section
    contemplates promoting a Google News item once corroborated. Nothing
    implements that today, and this filter is source-level, so a promoted item
    would keep sitting outside the feed. That is the honest consequence of
    defining the feed by outlet reliability; if promotion is ever built, this
    query is one of the places that has to answer for it.

    THE FILTER IS ON THE SOURCE'S GRADE, NOT THE ITEM'S, and that is load-bearing.
    `classify()` demotes an item to C3 when it attaches to the vehicle bill by
    inference, so five Democracy Docket items are stored C3 despite coming from a
    B2 source. Filtering on `items.admiralty_source` would silently drop exactly
    those five. Joining `sources` is the better of the two available fields and
    survives a new B2 feed being added to config without a code change. A test
    pins the five.

    THIS DOCSTRING USED TO CLAIM THE JOIN "asks the question the spec asks -- how
    reliable is this outlet". Measured false 2026-08-14 and corrected here rather
    than left standing while the policy question waits. `sources` is the DELIVERY
    PIPE, not the outlet, and the two diverge: 138 of the 2,986 Google News items
    (4.6%) come from outlets this config already grades B2, Democracy Docket 105
    of them. Split by cohort, 74 predate the earliest item in the B2 Democracy
    Docket feed (2026-06-26) and are backfill asymmetry -- that feed reaches back
    only to psephos's first poll -- while 31 fall inside its coverage window and
    11 of those (35.5%) are absent from it, which is an ongoing pipe miss. So the
    same outlet's same journalism is graded B2 or C3 by which feed carried it.
    The fix is outlet-level promotion, which the spec already contemplates ("C3
    until corroborated, then promote") and nothing implements; it is a grading
    POLICY change and deliberately not made here. See docs/status.md.

    The join cannot inflate the count: `sources.id` is a PRIMARY KEY (schema.sql),
    so every item matches at most one source row and the result is one entry per
    item. That is the property a filtering JOIN has to earn, so it is named here.

    CONTENTS ARE THE WHOLE B2 SET, not the unanchored subset. A feed is a channel
    view, not an orphanage: defining it as "items with no bill_id" would make the
    file's contents move whenever the matcher changed, coupling an export to
    matcher behaviour. The anchored items correctly appear both here and on their
    bill pages.
    """
    rows = conn.execute(
        "SELECT i.* FROM items i JOIN sources s ON s.id = i.source_id "
        f"WHERE i.channel = 'news' AND ({news_feed_predicate()}) "
        "ORDER BY i.occurred_at, i.id"
    ).fetchall()
    return sorted((_item_entry(r) for r in rows), key=_sort_key)


def news_feed_predicate() -> str:
    """The feed's membership rule: a B2 PIPE or a B2 OUTLET.

    OUTLET PROMOTION (handoff 82) is the second half, and it is a read-time
    derivation on purpose. Nothing rewrites `items.admiralty_source`: the item's
    stored grade records what the delivery pipe said, which the spec's
    record-both-and-flag rule wants kept, and a policy that may change should not
    be baked into 109 rows. Stored would also not have saved any work -- all three
    filtering call sites test the SOURCE's grade, so promoting by rewriting the
    item would have left every one of them unchanged.

    THIS TEXT IS DUPLICATED IN TYPESCRIPT (`web/lib/db.ts`) because the export and
    the view are different runtimes. The B2 outlet list is generated from
    `config/sources.yaml` on this side and pinned to it by a test on the other, so
    the two can drift only through a failing test rather than silently."""
    return ("s.admiralty_source = 'B' OR ("
            + config.news_outlet_sql(config.b2_outlet_keys()) + ")")


def build_state_bills(conn) -> list[dict]:
    """Per-state-bill objects sorted by state_bill_id. Timeline = the state items
    keyed by state_bill_id, flat and date-ordered like build_cases (state bills
    have no event anchors -- those are federal-bill-scoped). is_vehicle is exported
    but always 0 until 5b-b. No updated_at / change_hash in the output, so the
    snapshot stays byte-stable even though the row's updated_at moves every run
    (the same reason build_bills omits it)."""
    out = []
    bills = conn.execute("SELECT * FROM state_bills ORDER BY state_bill_id").fetchall()
    for b in bills:
        rows = conn.execute(
            "SELECT * FROM items WHERE state_bill_id = ? ORDER BY occurred_at, id",
            (b["state_bill_id"],),
        ).fetchall()
        entries = sorted((_item_entry(r) for r in rows), key=_sort_key)
        out.append({
            "state_bill_id": b["state_bill_id"],
            "state": b["state"],
            "bill_number": b["bill_number"],
            "session": b["session"],
            "title": b["title"],
            "status": b["status"],
            "is_vehicle": bool(b["is_vehicle"]),
            "last_action": b["last_action"],
            "last_action_at": b["last_action_at"],
            "url": b["url"],
            "timeline": entries,
        })
    return out


def write_json(path: str, obj) -> bytes:
    """Write `obj` deterministically: sorted keys, UTF-8, LF, no BOM, trailing
    newline, no wall-clock timestamp. Returns the bytes written (handy for tests)."""
    text = json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    data = text.encode("utf-8")
    Path(path).write_bytes(data)
    return data


def main() -> int:
    config.load_env()
    sources = config.load_sources()
    anchors = sources.get("event_anchors", []) or []

    conn = db.connect()
    try:
        bills = build_bills(conn, anchors)
        cases = build_cases(conn)
        executive = build_executive(conn)
        state_bills = build_state_bills(conn)
        news = build_news(conn)
        # Print the excluded count beside the included one, every run: this file is
        # a graded subset and the number is meaningless without its complement.
        # The exact complement of build_news, so the two always sum to the channel.
        # NOT `<> 'B'`: with outlet promotion the membership rule is no longer a
        # single column test, and negating only half of it would double-count every
        # promoted item -- reported as both included and excluded.
        news_excluded = conn.execute(
            "SELECT COUNT(*) FROM items i JOIN sources s ON s.id = i.source_id "
            f"WHERE i.channel = 'news' AND NOT ({news_feed_predicate()})"
        ).fetchone()[0]
    finally:
        conn.close()

    write_json(BILLS_PATH, bills)
    write_json(CASES_PATH, cases)
    write_json(EXECUTIVE_PATH, executive)
    write_json(STATE_BILLS_PATH, state_bills)
    write_json(NEWS_PATH, news)

    nodes = sum(1 for b in bills for e in b["timeline"] if e["kind"] == "cluster")
    print(f"  wrote {BILLS_PATH} ({len(bills)} bills), {CASES_PATH} "
          f"({len(cases)} cases), {EXECUTIVE_PATH} ({len(executive)} executive), "
          f"{STATE_BILLS_PATH} ({len(state_bills)} state bills), and {NEWS_PATH} "
          f"({len(news)} B2 news, {news_excluded} C3 excluded); {nodes} cluster node(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
