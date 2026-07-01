"""Deterministic JSON snapshots from the items spine.

Two products, one file each under data/:

  bills.json  -- per-bill timelines: legislation actions (A1) interleaved with the
                 news that explains them (C3/B2), in date order. Same-event news is
                 grouped into one node by a curated anchor (config: event_anchors),
                 additively -- every item still appears exactly once.
  cases.json  -- per-case timelines: CourtListener docket entries (A1) plus the
                 tracker framing (B2). No news, no litigation<->news join.
  executive.json -- the executive channel as a flat, date-ordered list: Federal
                 Register documents (A1). No bill/case scope, no clustering.

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
STATE_PATH = "data/state.json"

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
    (B2) items keyed by case_id. No clustering (anchors are bill-scoped), no news."""
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


def build_state(conn) -> list[dict]:
    """The state channel as a flat, date-ordered list. Items-only like executive
    (bill_id/case_id null), no bill/case scope and no clustering; reuses
    _item_entry / _sort_key so state entries match the item shape and stay
    byte-stable."""
    rows = conn.execute(
        "SELECT * FROM items WHERE channel = 'state' ORDER BY occurred_at, id"
    ).fetchall()
    return sorted((_item_entry(r) for r in rows), key=_sort_key)


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
        state = build_state(conn)
    finally:
        conn.close()

    write_json(BILLS_PATH, bills)
    write_json(CASES_PATH, cases)
    write_json(EXECUTIVE_PATH, executive)
    write_json(STATE_PATH, state)

    nodes = sum(1 for b in bills for e in b["timeline"] if e["kind"] == "cluster")
    print(f"  wrote {BILLS_PATH} ({len(bills)} bills), {CASES_PATH} "
          f"({len(cases)} cases), {EXECUTIVE_PATH} ({len(executive)} executive), "
          f"and {STATE_PATH} ({len(state)} state); {nodes} cluster node(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
