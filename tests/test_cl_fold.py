"""R1 step d's fold (collectors/cl_fold.py): which item presents each entry, and with what
text. Corey's rulings of 2026-09-30: every row and item kept; the survivor text the hybrid
(latest for tier 1, the long form for tier 2), FILED IN ERROR replacing the original on the
page; fetched_at the earliest, updated_at the latest; B2 notes folded per case."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import common  # noqa: E402
import db  # noqa: E402
from collectors import cl_fold as fold  # noqa: E402
from collectors import cl_objects as co  # noqa: E402
from collectors import litigation as lit  # noqa: E402

CASE = "71499795"
TYPES, EXCL = ["order", "notice of appeal", "memorandum"], []


def _db(tmp_path):
    dbp = str(tmp_path / "f.db")
    db.init_db(dbp)
    conn = db.connect(dbp)
    for sid, a, i in (("courtlistener", "A", "1"), ("seed-cases", "B", "2")):
        conn.execute("INSERT INTO sources (id, name, channel, kind, admiralty_source, admiralty_info)"
                     " VALUES (?, ?, 'litigation', 'api', ?, ?)", (sid, sid, a, i))
    conn.execute("INSERT INTO cases (case_id, caption, status) VALUES (?, 'LWV v. DHS', 'pending')", (CASE,))
    conn.commit()
    return conn


def _e(cl_id, desc, day="2026-08-21"):
    return {"id": cl_id, "date_filed": day, "description": desc, "recap_documents": [],
            "entry_number": None, "date_modified": "2026-08-22T00:00:00Z"}


def _poll(conn, entries, fetched=None, monkeypatch=None):
    """write_entries, then the fold in its own transaction: what collect_case does."""
    if monkeypatch is not None and fetched is not None:
        monkeypatch.setattr(common, "now_iso", lambda: fetched)
    lit.write_entries(conn, CASE, "League of Women Voters v. DHS", None, entries, TYPES, EXCL)
    conn.commit()
    fold.refold_quietly(conn, CASE)


def _items(conn):
    return [dict(r) for r in conn.execute(
        "SELECT id, title, summary, occurred_at, fetched_at, merged_into, display_title, "
        "display_summary, display_at, updated_at FROM items ORDER BY id")]


def test_a_re_described_entry_presents_once_with_its_latest_text_and_first_seen_time(tmp_path, monkeypatch):
    """#141: 'Notice of Appeal to DC Circuit', then the full text. Two items, one entry."""
    conn = _db(tmp_path)
    _poll(conn, [_e(475375313, "Notice of Appeal to DC Circuit")], "2026-08-21T20:00:00Z", monkeypatch)
    _poll(conn, [_e(475375313, "NOTICE OF APPEAL TO DC CIRCUIT COURT as to 112 Order")],
          "2026-08-22T08:00:00Z", monkeypatch)
    first, second = _items(conn)
    assert first["merged_into"] is None and second["merged_into"] == first["id"]
    assert first["display_summary"] == "NOTICE OF APPEAL TO DC CIRCUIT COURT as to 112 Order"
    assert first["display_title"] == ("League of Women Voters v. DHS: "
                                      "NOTICE OF APPEAL TO DC CIRCUIT COURT as to 112 Order")
    assert first["fetched_at"] == "2026-08-21T20:00:00Z"       # the earliest: first seen
    assert first["updated_at"] == "2026-08-22T08:00:00Z"       # the latest
    assert (first["title"], first["summary"]) == ("League of Women Voters v. DHS: Notice of Appeal "
                                                  "to DC Circuit", "Notice of Appeal to DC Circuit")


def test_a_clerks_strike_replaces_the_original_on_the_page(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    _poll(conn, [_e(1, "ORDER granting the motion to dismiss")], "2026-08-21T20:00:00Z", monkeypatch)
    _poll(conn, [_e(1, "***FILED IN ERROR*** ORDER granting the motion to dismiss")],
          "2026-08-22T08:00:00Z", monkeypatch)
    (only,) = [i for i in _items(conn) if i["merged_into"] is None]
    assert only["display_summary"].startswith("***FILED IN ERROR***")
    # The original stays in its row and its item.
    assert conn.execute("SELECT COUNT(*) FROM case_entries WHERE description = "
                        "'ORDER granting the motion to dismiss'").fetchone()[0] == 1
    assert only["summary"] == "ORDER granting the motion to dismiss"


def test_a_re_dated_entry_takes_the_objects_date(tmp_path, monkeypatch):
    """Nevada: 'USCA Order Time Schedule' Aug 24, re-served Aug 20."""
    conn = _db(tmp_path)
    _poll(conn, [_e(9, "USCA ORDER time schedule", day="2026-08-24")], "2026-08-25T00:00:00Z", monkeypatch)
    _poll(conn, [_e(9, "USCA ORDER time schedule", day="2026-08-20")], "2026-08-26T00:00:00Z", monkeypatch)
    (only,) = [i for i in _items(conn) if i["merged_into"] is None]
    assert only["display_at"] == "2026-08-20T00:00:00"


def test_a_linked_tier_two_pair_presents_the_long_form_at_the_earlier_time(tmp_path, monkeypatch):
    """The Jul 20 pair: the short object's item came first; once linked, the entry shows
    the long form, at the short form's first-seen time."""
    conn = _db(tmp_path)
    _poll(conn, [_e(471517786, "Order on Motion to Enforce Judgment AND Set/Reset Deadlines",
                    day="2026-07-20")], "2026-07-20T22:00:00Z", monkeypatch)
    _poll(conn, [_e(471527695, "MINUTE ORDER: The Court has reviewed the Parties' briefing",
                    day="2026-07-20")], "2026-07-21T08:00:00Z", monkeypatch)
    assert sum(1 for i in _items(conn) if i["merged_into"] is None) == 2   # unlinked: two entries
    conn.execute("UPDATE cl_entries SET twin_of = 471527695, twin_rule = 'test' "
                 "WHERE cl_entry_id = 471517786")
    fold.refold_case(conn, CASE)
    conn.commit()
    (only,) = [i for i in _items(conn) if i["merged_into"] is None]
    assert only["summary"].startswith("Order on Motion")                    # the short form's item...
    assert only["display_summary"].startswith("MINUTE ORDER: The Court")    # ...shows the long form
    assert only["fetched_at"] == "2026-07-20T22:00:00Z"


def test_items_with_no_object_are_left_alone(tmp_path):
    conn = _db(tmp_path)
    conn.execute("INSERT INTO items (channel, source_id, source_url, title, summary, fetched_at, "
                 "admiralty_source, admiralty_info, case_id, content_hash, merged_into, display_title) "
                 "VALUES ('litigation', 'courtlistener', 'u', 't', 's', 'f', 'A', '1', ?, 'h', 99, 'stale')",
                 (CASE,))
    fold.refold_case(conn, CASE)
    (it,) = _items(conn)
    assert (it["merged_into"], it["display_title"]) == (None, None)     # cleared, not kept


def test_tracker_notes_fold_to_one_subject_with_the_latest_notes(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    seed = {"caption": "LWV v. DHS", "category": "voter-data", "notes": "first notes"}
    monkeypatch.setattr(common, "now_iso", lambda: "2026-07-01T00:00:00Z")
    lit.write_b2_item(conn, CASE, seed, "2025-10-01T00:00:00", None)
    monkeypatch.setattr(common, "now_iso", lambda: "2026-08-01T00:00:00Z")
    lit.write_b2_item(conn, CASE, {**seed, "notes": "revised notes"}, None, None)
    fold.refold_case(conn, CASE)
    items = _items(conn)
    shown = [i for i in items if i["merged_into"] is None]
    assert len(items) == 2 and len(shown) == 1
    assert shown[0]["display_summary"] == "revised notes"
    assert shown[0]["display_at"] == "2025-10-01T00:00:00"        # the first copy carried the date
    assert shown[0]["fetched_at"] == "2026-07-01T00:00:00Z"


def test_the_collector_refolds_a_notes_edit(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    conn.execute("UPDATE cases SET docket_number = '1:25-cv-03501', court = 'D.D.C.' WHERE case_id = ?", (CASE,))
    conn.commit()
    seed = {"caption": "LWV v. DHS", "docket_number": "1:25-cv-03501", "court": "D.D.C.",
            "court_id": "dcd", "category": "voter-data", "notes": "first"}
    monkeypatch.setattr(lit, "poll_entries", lambda *a, **k: ([], None))
    lit.collect_case(conn, "b", {}, seed, TYPES, EXCL)
    lit.collect_case(conn, "b", {}, {**seed, "notes": "second"}, TYPES, EXCL)
    shown = [i for i in _items(conn) if i["merged_into"] is None]
    assert [i["display_summary"] for i in shown] == ["second"]


def test_refold_writes_only_what_differs(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    _poll(conn, [_e(1, "ORDER one")], "2026-08-21T20:00:00Z", monkeypatch)
    assert fold.refold_case(conn, CASE)["changed"] == 0          # write_entries already folded
    conn.execute("UPDATE items SET display_title = 'drifted'")
    assert fold.refold_case(conn, CASE)["changed"] == 1


def test_the_walk_folds_the_rows_it_ties(tmp_path, monkeypatch):
    """Two legacy items for one entry (#131's shape): after the walk, one presents."""
    conn = _db(tmp_path)
    for desc, fetched in (("Supplemental Memorandum", "2026-07-20T19:31:18Z"),
                          ("SUPPLEMENTAL MEMORANDUM re 128 MOTION to Enforce", "2026-07-21T08:12:22Z")):
        conn.execute("INSERT INTO case_entries (case_id, entry_at, description, document_url) "
                     "VALUES (?, '2026-07-20T00:00:00', ?, 'https://www.courtlistener.com/docket/71499795/131/lwv/')",
                     (CASE, desc))
        conn.execute("INSERT INTO items (channel, source_id, source_url, title, summary, occurred_at, "
                     "fetched_at, admiralty_source, admiralty_info, case_id, content_hash) VALUES "
                     "('litigation', 'courtlistener', 'u', ?, ?, '2026-07-20T00:00:00', ?, 'A', '1', ?, ?)",
                     (f"LWV: {desc}", desc, fetched, CASE, common.content_hash(CASE, "2026-07-20T00:00:00", desc)))
    conn.commit()
    e = _e(471479890, "SUPPLEMENTAL MEMORANDUM re 128 MOTION to Enforce", day="2026-07-20")
    e["recap_documents"] = [{"absolute_url": "/docket/71499795/131/lwv/", "description": ""}]
    monkeypatch.setattr(lit, "poll_entries", lambda *a, **k: ([e], None))
    lit.backfill_walk(conn, "b", {}, 50, set())
    shown = [i for i in _items(conn) if i["merged_into"] is None]
    assert len(shown) == 1 and shown[0]["summary"] == "Supplemental Memorandum"
    assert shown[0]["display_summary"] == "SUPPLEMENTAL MEMORANDUM re 128 MOTION to Enforce"


def _seeded(conn):
    conn.execute("UPDATE cases SET docket_number = '1:25-cv-03501', court = 'D.D.C.' WHERE case_id = ?", (CASE,))
    conn.commit()
    return {"caption": "LWV v. DHS", "docket_number": "1:25-cv-03501", "court": "D.D.C.",
            "court_id": "dcd", "category": "voter-data", "notes": "n"}


def test_a_fold_failure_never_costs_the_poll_or_its_mark(tmp_path, monkeypatch, capsys):
    """The fold runs after the poll's commit, in its own transaction: a fold that fails --
    even one that ends its transaction -- leaves the entries and the mark committed."""
    conn = _db(tmp_path)
    seed = _seeded(conn)
    monkeypatch.setattr(lit, "poll_entries", lambda *a, **k: ([_e(1, "ORDER one")], "2026-08-22T00:00:00Z"))

    def broken(*a, **k):
        raise ValueError("database or disk is full")

    monkeypatch.setattr(fold, "refold_case", broken)
    conn.execute("UPDATE cases SET entries_synced_at = '2026-08-01T00:00:00Z', latest_entry_at = '2026-08-01' WHERE case_id = ?", (CASE,))
    conn.commit()
    lit.collect_case(conn, "b", {}, seed, TYPES, EXCL)
    assert conn.execute("SELECT COUNT(*) FROM case_entries").fetchone()[0] == 1
    assert conn.execute("SELECT entries_synced_at FROM cases").fetchone()[0] == "2026-08-22T00:00:00Z"
    assert "not refolded" in capsys.readouterr().err
    assert fold.unfolded(conn) == [CASE]            # the sweep will find it


# --------------------------------------------------------------------------- #
# The switch's two reads (schema.sql views)
# --------------------------------------------------------------------------- #
def test_record_items_reads_one_item_per_entry_with_the_survivor(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    _poll(conn, [_e(475375313, "Notice of Appeal to DC Circuit")], "2026-08-21T20:00:00Z", monkeypatch)
    _poll(conn, [_e(475375313, "NOTICE OF APPEAL TO DC CIRCUIT COURT as to 112 Order", day="2026-08-22")],
          "2026-08-22T08:00:00Z", monkeypatch)
    rows = [dict(r) for r in conn.execute("SELECT title, summary, occurred_at, fetched_at, updated_at "
                                          "FROM record_items WHERE case_id = ?", (CASE,))]
    assert rows == [{"title": "League of Women Voters v. DHS: NOTICE OF APPEAL TO DC CIRCUIT COURT as to 112 Order",
                     "summary": "NOTICE OF APPEAL TO DC CIRCUIT COURT as to 112 Order",
                     "occurred_at": "2026-08-22T00:00:00", "fetched_at": "2026-08-21T20:00:00Z",
                     "updated_at": "2026-08-22T08:00:00Z"}]
    assert conn.execute("SELECT COUNT(*) FROM items WHERE case_id = ?", (CASE,)).fetchone()[0] == 2


def test_record_entries_counts_entries_not_rows(tmp_path, monkeypatch):
    """Two texts of one entry (tier 1), a tier-2 pair once linked, and a row nothing ties."""
    conn = _db(tmp_path)
    _poll(conn, [_e(1, "Notice of Appeal to DC Circuit")], "2026-08-21T20:00:00Z", monkeypatch)
    _poll(conn, [_e(1, "NOTICE OF APPEAL TO DC CIRCUIT COURT as to 112 Order")], "2026-08-22T08:00:00Z", monkeypatch)
    _poll(conn, [_e(2, "Order on Motion to Enforce"), _e(3, "MINUTE ORDER: the Court has reviewed")],
          "2026-08-22T08:00:00Z", monkeypatch)
    conn.execute("INSERT INTO case_entries (case_id, entry_at, description) VALUES (?, '2026-06-01T00:00:00', 'legacy')", (CASE,))
    n = lambda: conn.execute("SELECT COUNT(*) FROM record_entries WHERE case_id = ?", (CASE,)).fetchone()[0]
    assert conn.execute("SELECT COUNT(*) FROM case_entries").fetchone()[0] == 5
    assert n() == 4                                   # 1 (two texts) + 2 + 3 + the legacy row
    conn.execute("UPDATE cl_entries SET twin_of = 3 WHERE cl_entry_id = 2")
    assert n() == 3
    latest = conn.execute("SELECT description FROM record_entries WHERE cl_entry_id = 1").fetchone()[0]
    assert latest == "NOTICE OF APPEAL TO DC CIRCUIT COURT as to 112 Order"


def test_record_entries_dates_an_entry_by_its_object(tmp_path, monkeypatch):
    """Nevada's shape: MAX over record_entries is the re-dated Aug 20, where MAX over the
    rows still reads the stale Aug 24."""
    conn = _db(tmp_path)
    _poll(conn, [_e(9, "USCA ORDER time schedule", day="2026-08-24")], "2026-08-25T00:00:00Z", monkeypatch)
    _poll(conn, [_e(9, "USCA ORDER time schedule", day="2026-08-20")], "2026-08-26T00:00:00Z", monkeypatch)
    assert conn.execute("SELECT MAX(entry_at) FROM case_entries").fetchone()[0] == "2026-08-24T00:00:00"
    assert conn.execute("SELECT MAX(entry_at) FROM record_entries").fetchone()[0] == "2026-08-20T00:00:00"


def test_the_fold_follows_a_twin_chain_to_its_end(tmp_path, monkeypatch):
    """A chain the link script now refuses to make, folded as record_entries counts it."""
    conn = _db(tmp_path)
    _poll(conn, [_e(101, "Order on Motion"), _e(102, "MINUTE ORDER granting the motion in part"),
                 _e(103, "MINUTE ORDER granting the motion in part and setting a hearing")],
          "2026-08-21T20:00:00Z", monkeypatch)
    conn.execute("UPDATE cl_entries SET twin_of = 102 WHERE cl_entry_id = 101")
    conn.execute("UPDATE cl_entries SET twin_of = 103 WHERE cl_entry_id = 102")
    fold.refold_case(conn, CASE)
    shown = [i for i in _items(conn) if i["merged_into"] is None]
    assert len(shown) == 1
    assert shown[0]["display_summary"] == "MINUTE ORDER granting the motion in part and setting a hearing"
    assert conn.execute("SELECT COUNT(*) FROM record_entries").fetchone()[0] == 1


def test_a_slug_case_refolds_its_notes(tmp_path):
    conn = _db(tmp_path)
    seed = {"caption": "Common Cause v. DOJ", "docket_number": None, "court_id": None,
            "category": "voter-data", "notes": "first"}
    lit.collect_case(conn, "b", {}, seed, TYPES, EXCL)
    lit.collect_case(conn, "b", {}, {**seed, "notes": "second"}, TYPES, EXCL)
    shown = [dict(r) for r in conn.execute(
        "SELECT display_summary FROM items WHERE case_id = 'common-cause-v-doj' AND merged_into IS NULL")]
    assert shown == [{"display_summary": "second"}]


def test_the_sweep_finds_what_no_refold_reached(tmp_path):
    conn = _db(tmp_path)
    lit.write_entries(conn, CASE, "c", None, [_e(1, "ORDER one")], TYPES, EXCL)
    conn.commit()
    assert fold.unfolded(conn) == [CASE]
    fold.refold_quietly(conn, CASE)
    assert fold.unfolded(conn) == []


def test_the_collector_folds_a_re_described_entry_after_its_poll(tmp_path, monkeypatch):
    """collect_case folds after the poll commits. The B2 subject is already held, so the
    only refold that can fold the second text is the one after the entries."""
    conn = _db(tmp_path)
    seed = _seeded(conn)
    served = iter([[_e(475375313, "Notice of Appeal to DC Circuit")],
                   [_e(475375313, "NOTICE OF APPEAL TO DC CIRCUIT COURT as to 112 Order")]])
    monkeypatch.setattr(lit, "poll_entries", lambda *a, **k: (next(served), "2026-08-22T00:00:00Z"))
    conn.execute("UPDATE cases SET entries_synced_at = '2026-08-01T00:00:00Z', latest_entry_at = '2026-08-01' WHERE case_id = ?", (CASE,))
    conn.commit()
    lit.collect_case(conn, "b", {}, seed, TYPES, EXCL)
    lit.collect_case(conn, "b", {}, seed, TYPES, EXCL)
    a1 = [i for i in _items(conn) if i["merged_into"] is None and i["summary"] != "n"]
    assert len(a1) == 1
    assert a1[0]["display_summary"] == "NOTICE OF APPEAL TO DC CIRCUIT COURT as to 112 Order"
