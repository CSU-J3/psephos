"""Acceptance + invariant suite for the export layer (export/snapshots.py).

Deterministic and offline: builds a temp DB, seeds synthetic items, and drives
the real build_bills / build_cases / write_json. No network, and it never touches
data/psephos.db. Anchors are passed in directly so the suite is independent of
config/sources.yaml.

Run:  pytest tests/test_export.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.chdir(REPO)  # db.init_db uses a repo-relative schema path

import db  # noqa: E402
from export import snapshots  # noqa: E402

# Grades by source slug, so seeded items get a coherent Admiralty grade.
SOURCES = {
    "congress-gov": ("legislation", "A", "1"),
    "courtlistener": ("litigation", "A", "1"),
    "seed-cases": ("litigation", "B", "2"),
    "google-news": ("news", "C", "3"),
    "democracy-docket": ("news", "B", "2"),
    "federal-register": ("executive", "A", "1"),
    "legiscan": ("state", "B", "2"),
}

ANCHOR = {
    "id": "hh",
    "label": "housing hostage",
    "bill": "billA-119",
    "phrase": "housing",
    "window": {"start": "2026-06-24", "end": "2026-06-25"},
}


def _conn():
    """Fresh temp DB with sources registered (items.source_id has an FK)."""
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    db.init_db(path)
    conn = db.connect(path)
    for sid, (channel, src, _info) in SOURCES.items():
        conn.execute(
            "INSERT INTO sources (id, name, channel, kind, admiralty_source) "
            "VALUES (?,?,?,?,?)", (sid, sid, channel, "api", src),
        )
    conn.commit()
    return conn


def _bill(conn, bill_id, is_vehicle=0):
    db.upsert(conn, "bills", {
        "bill_id": bill_id, "congress": 119, "bill_type": "s", "number": 1,
        "is_vehicle": is_vehicle,
    }, pk="bill_id")
    conn.commit()


def _case(conn, case_id):
    db.upsert(conn, "cases", {"case_id": case_id, "caption": case_id}, pk="case_id")
    conn.commit()


def _state_bill(conn, state_bill_id, *, state="TX", bill_number="SB100",
                is_vehicle=0, updated_at=None):
    db.upsert(conn, "state_bills", {
        "state_bill_id": state_bill_id, "state": state, "bill_number": bill_number,
        "is_vehicle": is_vehicle, "updated_at": updated_at,
    }, pk="state_bill_id")
    conn.commit()


_HASH = [0]


def _item(conn, *, source_id, title, occurred_at, bill_id=None, case_id=None,
          state_bill_id=None):
    """Seed one item; returns its rowid. content_hash is unique per call."""
    channel, src, info = SOURCES[source_id]
    _HASH[0] += 1
    cur = conn.execute(
        "INSERT INTO items (channel, source_id, source_url, title, occurred_at, "
        "fetched_at, admiralty_source, admiralty_info, bill_id, case_id, "
        "state_bill_id, content_hash) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (channel, source_id, f"https://ex/{_HASH[0]}", title, occurred_at,
         "2026-01-01T00:00:00+00:00", src, info, bill_id, case_id,
         state_bill_id, f"h{_HASH[0]}"),
    )
    conn.commit()
    return cur.lastrowid


def _all_ids(timeline):
    """Every item id referenced by a timeline, standalone entries and cluster
    members alike. Returns a flat list so duplicates are detectable."""
    ids = []
    for e in timeline:
        if e["kind"] == "cluster":
            ids.extend(m["id"] for m in e["members"])
        else:
            ids.append(e["id"])
    return ids


def _timeline_for(bills, bill_id):
    return next(b["timeline"] for b in bills if b["bill_id"] == bill_id)


# --- core acceptance ---------------------------------------------------------

def test_cluster_collapses_lossless_and_grade_is_strongest():
    conn = _conn()
    _bill(conn, "billA-119", is_vehicle=1)
    seeded = set()
    # 2 legislation actions (A1)
    seeded.add(_item(conn, source_id="congress-gov", title="Passed Senate by UC", occurred_at="2025-12-18"))
    seeded.add(_item(conn, source_id="congress-gov", title="On passage 218-213", occurred_at="2026-02-11", bill_id="billA-119"))
    conn.execute("UPDATE items SET bill_id='billA-119' WHERE bill_id IS NULL AND channel='legislation'")
    conn.commit()
    # 4 signing-cancellation news, DISTINCT titles, all contain "housing", in window
    for t, d in [
        ("Trump won't sign bipartisan housing bill until SAVE Act", "2026-06-24"),
        ("Trump halts housing bill signing until Congress acts", "2026-06-24"),
        ("Trump cancels signing of housing bill over SAVE America", "2026-06-24"),
        ("Trump delays major housing bill signing", "2026-06-25"),
    ]:
        seeded.add(_item(conn, source_id="google-news", title=t, occurred_at=d, bill_id="billA-119"))
    # 3 that must NOT join: out-of-window-before, in-range-without-phrase, far date
    seeded.add(_item(conn, source_id="google-news", title="Thune: votes aren't there on filibuster", occurred_at="2026-06-17", bill_id="billA-119"))
    seeded.add(_item(conn, source_id="google-news", title="What to know about the SAVE Act stall", occurred_at="2026-06-24", bill_id="billA-119"))
    seeded.add(_item(conn, source_id="google-news", title="SD Republicans reject censuring Thune", occurred_at="2026-06-27", bill_id="billA-119"))

    bills = snapshots.build_bills(conn, [ANCHOR])
    tl = _timeline_for(bills, "billA-119")
    clusters = [e for e in tl if e["kind"] == "cluster"]

    assert len(clusters) == 1
    node = clusters[0]
    assert node["source_count"] == 4
    assert len(node["members"]) == 4
    assert node["grade"] == "C3"            # 4x C3 stays C3 -- count never inflates grade
    assert node["anchor"] == "hh"
    # lossless: every seeded id appears exactly once across the whole timeline
    ids = _all_ids(tl)
    assert sorted(ids) == sorted(seeded)
    assert len(ids) == len(set(ids))
    # members sorted by id; entries sorted by (date, id)
    assert node["members"] == sorted(node["members"], key=lambda m: m["id"])
    keys = [snapshots._sort_key(e) for e in tl]
    assert keys == sorted(keys)


def test_b2_member_flips_node_grade():
    conn = _conn()
    _bill(conn, "billA-119")
    _item(conn, source_id="google-news", title="Trump halts housing bill signing", occurred_at="2026-06-24", bill_id="billA-119")
    _item(conn, source_id="democracy-docket", title="Housing bill held hostage to SAVE Act", occurred_at="2026-06-25", bill_id="billA-119")
    bills = snapshots.build_bills(conn, [ANCHOR])
    node = next(e for e in _timeline_for(bills, "billA-119") if e["kind"] == "cluster")
    assert node["source_count"] == 2
    assert node["grade"] == "B2"            # strongest member wins; B2 < C3


# --- added invariants --------------------------------------------------------

def test_window_boundary_day_after_stays_standalone():
    """An item dated exactly one day AFTER the inclusive window end must not join
    the cluster -- pins the boundary so a future widening can't silently absorb it."""
    conn = _conn()
    _bill(conn, "billA-119")
    inwin = [
        _item(conn, source_id="google-news", title="Trump halts housing bill signing", occurred_at="2026-06-24", bill_id="billA-119"),
        _item(conn, source_id="google-news", title="Trump cancels housing bill signing", occurred_at="2026-06-25", bill_id="billA-119"),
    ]
    # 2026-06-26 = window end (06-25) + 1 day, same bill, DOES contain "housing"
    after = _item(conn, source_id="google-news", title="Housing bill still unsigned a day later", occurred_at="2026-06-26", bill_id="billA-119")

    tl = _timeline_for(snapshots.build_bills(conn, [ANCHOR]), "billA-119")
    node = next(e for e in tl if e["kind"] == "cluster")
    assert sorted(m["id"] for m in node["members"]) == sorted(inwin)
    after_entry = next(e for e in tl if e["kind"] == "item" and e["id"] == after)
    assert after_entry["kind"] == "item"    # standalone, not absorbed
    assert after not in {m["id"] for m in node["members"]}


def test_single_match_stays_standalone_not_a_node():
    """An anchor matching exactly ONE in-window item yields a standalone item,
    never a 1-member cluster and never a drop -- guards the lossless no-node branch."""
    conn = _conn()
    _bill(conn, "billA-119")
    only = _item(conn, source_id="google-news", title="Trump halts housing bill signing", occurred_at="2026-06-24", bill_id="billA-119")
    other = _item(conn, source_id="google-news", title="Unrelated election news", occurred_at="2026-06-24", bill_id="billA-119")

    tl = _timeline_for(snapshots.build_bills(conn, [ANCHOR]), "billA-119")
    assert all(e["kind"] == "item" for e in tl)     # no cluster formed
    assert sorted(_all_ids(tl)) == sorted([only, other])
    match_entry = next(e for e in tl if e["id"] == only)
    assert match_entry["kind"] == "item"


# --- determinism + cases -----------------------------------------------------

def test_output_is_byte_identical_and_timestamp_free():
    conn = _conn()
    _bill(conn, "billA-119")
    _item(conn, source_id="google-news", title="Trump halts housing bill signing", occurred_at="2026-06-24", bill_id="billA-119")
    _item(conn, source_id="google-news", title="Trump cancels housing bill signing", occurred_at="2026-06-25", bill_id="billA-119")
    bills = snapshots.build_bills(conn, [ANCHOR])

    out = Path(tempfile.mkdtemp())
    b1 = snapshots.write_json(str(out / "a.json"), bills)
    b2 = snapshots.write_json(str(out / "b.json"), bills)
    assert b1 == b2                                  # byte-identical
    assert b1.endswith(b"\n")                        # trailing newline
    assert b"2026-01-01T00:00:00" not in b1          # no fetched_at / wall-clock leaked


def test_case_timeline_is_items_only_no_clustering():
    conn = _conn()
    _case(conn, "1:26-cv-01352")
    _item(conn, source_id="seed-cases", title="Common Cause v. DOJ (framing)", occurred_at="2026-04-21", case_id="1:26-cv-01352")
    _item(conn, source_id="courtlistener", title="MOTION to Dismiss", occurred_at="2026-06-02", case_id="1:26-cv-01352")
    cases = snapshots.build_cases(conn)
    tl = cases[0]["timeline"]
    assert [e["kind"] for e in tl] == ["item", "item"]
    assert [e["grade"] for e in tl] == ["B2", "A1"]   # date order: framing then docket


# --- executive channel -------------------------------------------------------

def test_executive_channel_isolated_and_in_snapshot():
    """Executive items (no bill_id/case_id) belong to build_executive only -- they
    must never leak into a bill or case timeline, and both must surface here."""
    conn = _conn()
    # Two executive items, distinct dates so ordering is observable.
    e2 = _item(conn, source_id="federal-register", title="EO 14399 on mail ballots", occurred_at="2026-03-15")
    e1 = _item(conn, source_id="federal-register", title="EO 14248 on proof of citizenship", occurred_at="2025-03-25")
    # A bill-scoped and a case-scoped item that MUST NOT appear in the executive list.
    _bill(conn, "billA-119")
    _case(conn, "1:26-cv-01352")
    b_item = _item(conn, source_id="congress-gov", title="On passage 218-213", occurred_at="2026-02-11", bill_id="billA-119")
    c_item = _item(conn, source_id="courtlistener", title="MOTION to Dismiss", occurred_at="2026-06-02", case_id="1:26-cv-01352")

    ex = snapshots.build_executive(conn)
    ex_ids = [e["id"] for e in ex]
    assert ex_ids == [e1, e2]                          # date-ordered (2025 before 2026), lossless
    assert b_item not in ex_ids and c_item not in ex_ids
    assert all(e["channel"] == "executive" and e["grade"] == "A1" for e in ex)

    # The reverse isolation: executive ids appear in no bill or case timeline.
    bill_ids = {i for b in snapshots.build_bills(conn, []) for i in _all_ids(b["timeline"])}
    case_ids = {i for c in snapshots.build_cases(conn) for i in _all_ids(c["timeline"])}
    assert {e1, e2}.isdisjoint(bill_ids)
    assert {e1, e2}.isdisjoint(case_ids)


def test_executive_json_is_byte_identical_and_timestamp_free():
    conn = _conn()
    _item(conn, source_id="federal-register", title="EO 14248 on proof of citizenship", occurred_at="2025-03-25")
    _item(conn, source_id="federal-register", title="EAC voter-registration guidance", occurred_at="2026-05-01")

    out = Path(tempfile.mkdtemp())
    b1 = snapshots.write_json(str(out / "e1.json"), snapshots.build_executive(conn))
    b2 = snapshots.write_json(str(out / "e2.json"), snapshots.build_executive(conn))
    assert b1 == b2                                    # unchanged DB -> empty diff
    assert b1.endswith(b"\n")
    assert b"2026-01-01T00:00:00" not in b1            # no fetched_at / wall-clock leaked


# --- state bills (first-class dimension) -------------------------------------

def test_state_bills_isolated_and_in_snapshot():
    """State items belong to build_state_bills only, keyed by state_bill_id -- they
    must never leak into a bill, case, or executive product, and each surfaces in
    its own bill's timeline, date-ordered. Bills sort by state_bill_id."""
    conn = _conn()
    _state_bill(conn, "1700001", state="TX", bill_number="SB100")
    _state_bill(conn, "1700050", state="GA", bill_number="HB50")
    tx2 = _item(conn, source_id="legiscan", title="TX SB100: Committee report favorable", occurred_at="2026-02-15", state_bill_id="1700001")
    tx1 = _item(conn, source_id="legiscan", title="TX SB100: Introduced", occurred_at="2026-01-10", state_bill_id="1700001")
    ga1 = _item(conn, source_id="legiscan", title="GA HB50: Introduced", occurred_at="2026-01-20", state_bill_id="1700050")
    # bill-, case-, and executive-scoped items that MUST NOT appear in a state bill
    _bill(conn, "billA-119")
    _case(conn, "1:26-cv-01352")
    b_item = _item(conn, source_id="congress-gov", title="On passage 218-213", occurred_at="2026-02-11", bill_id="billA-119")
    c_item = _item(conn, source_id="courtlistener", title="MOTION to Dismiss", occurred_at="2026-06-02", case_id="1:26-cv-01352")
    e_item = _item(conn, source_id="federal-register", title="EO 14248 on proof of citizenship", occurred_at="2025-03-25")

    sb = snapshots.build_state_bills(conn)
    assert [b["state_bill_id"] for b in sb] == ["1700001", "1700050"]  # sorted by PK
    tx = next(b for b in sb if b["state_bill_id"] == "1700001")
    assert [e["id"] for e in tx["timeline"]] == [tx1, tx2]   # date-ordered within the bill
    assert tx["is_vehicle"] is False                          # 5b-b does not set it yet
    ga = next(b for b in sb if b["state_bill_id"] == "1700050")
    assert [e["id"] for e in ga["timeline"]] == [ga1]
    assert all(e["channel"] == "state" and e["grade"] == "B2"
               for b in sb for e in b["timeline"])

    # The reverse isolation: state ids appear in no bill, case, or executive product.
    state_ids = {tx1, tx2, ga1}
    bill_ids = {i for b in snapshots.build_bills(conn, []) for i in _all_ids(b["timeline"])}
    case_ids = {i for c in snapshots.build_cases(conn) for i in _all_ids(c["timeline"])}
    exec_ids = {e["id"] for e in snapshots.build_executive(conn)}
    assert state_ids.isdisjoint(bill_ids)
    assert state_ids.isdisjoint(case_ids)
    assert state_ids.isdisjoint(exec_ids)
    assert {b_item, c_item, e_item}.isdisjoint(state_ids)   # sanity: distinct ids


def test_state_bills_json_is_byte_identical_and_timestamp_free():
    conn = _conn()
    _state_bill(conn, "1700001", state="TX", bill_number="SB100")
    _state_bill(conn, "1700050", state="GA", bill_number="HB50")
    _item(conn, source_id="legiscan", title="TX SB100: Filed", occurred_at="2026-01-20", state_bill_id="1700001")
    _item(conn, source_id="legiscan", title="GA HB50: Introduced", occurred_at="2026-01-10", state_bill_id="1700050")

    out = Path(tempfile.mkdtemp())
    b1 = snapshots.write_json(str(out / "s1.json"), snapshots.build_state_bills(conn))
    b2 = snapshots.write_json(str(out / "s2.json"), snapshots.build_state_bills(conn))
    assert b1 == b2                                    # unchanged DB -> empty diff
    assert b1.endswith(b"\n")
    assert b"2026-01-01T00:00:00" not in b1            # no fetched_at / wall-clock leaked


def test_state_bills_json_stable_despite_moving_updated_at():
    """state_bills.updated_at moves on every collector run, but build_state_bills
    omits it, so the snapshot is byte-identical across runs -- the empty-diff
    guarantee, the same reason build_bills omits its own updated_at."""
    conn = _conn()
    _state_bill(conn, "1700001", state="TX", bill_number="SB100",
                updated_at="2026-07-01T00:00:00+00:00")
    _item(conn, source_id="legiscan", title="TX SB100: Filed", occurred_at="2026-01-20", state_bill_id="1700001")
    out = Path(tempfile.mkdtemp())
    b1 = snapshots.write_json(str(out / "a.json"), snapshots.build_state_bills(conn))

    # a later run: only updated_at moves
    _state_bill(conn, "1700001", state="TX", bill_number="SB100",
                updated_at="2026-07-02T12:34:56+00:00")
    b2 = snapshots.write_json(str(out / "b.json"), snapshots.build_state_bills(conn))

    assert b1 == b2                                    # updated_at change does not alter output
    assert b"2026-07-01" not in b1                     # updated_at value never leaks
    assert b"2026-07-02" not in b2
