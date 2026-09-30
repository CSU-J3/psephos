"""R1 (Corey, 2026-09-30): CourtListener entry ids on every row, the safe insert-time
normalization, and the id backfill walk. docs/status.md, "Duplicate rows at the source".

Each case below is a shape the D0 found in the held record: a stamp re-render (the 94),
a short form that became the full text (#131: 65827 -> 67566), a clerk's re-date (Nevada
86998 -> 87067), an earlier text coming back (71457474 document 101), two entries sharing
a document number (D. Del. 46/71/79), and two objects serving one text on one day."""
from __future__ import annotations

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import common  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
from collectors import cl_objects as co  # noqa: E402
from collectors import litigation as lit  # noqa: E402

TYPES, EXCL = ["order", "motion", "notice of appeal"], []
DAY = "2026-07-20T00:00:00"
URL = "https://www.courtlistener.com/docket/71499795/{}/lwv/"
NOW = "2026-10-01T06:30:00Z"


def _db(tmp_path):
    dbp = str(tmp_path / "r1.db")
    db.init_db(dbp)
    conn = db.connect(dbp)
    conn.execute(
        "INSERT INTO sources (id, name, channel, kind, admiralty_source, admiralty_info)"
        " VALUES ('courtlistener', 'CL', 'litigation', 'api', 'A', '1')")
    conn.execute("INSERT INTO cases (case_id, caption, status) VALUES ('71499795', 'c', 'pending')")
    conn.commit()
    return conn


def _e(cl_id, desc, day="2026-07-20", url=None, number=None, modified="2026-07-21T00:00:00Z"):
    docs = [{"absolute_url": url, "description": ""}] if url else []
    return {"id": cl_id, "date_filed": day, "description": desc, "recap_documents": docs,
            "entry_number": number, "date_modified": modified}


def _write(conn, entries):
    c = lit.write_entries(conn, "71499795", "c", None, entries, TYPES, EXCL)
    conn.commit()
    return c


def _rows(conn):
    return [dict(r) for r in conn.execute(
        "SELECT id, entry_at, description, cl_entry_id, seen_at FROM case_entries ORDER BY id")]


def _obj(conn, cl_id):
    r = conn.execute("SELECT * FROM cl_entries WHERE cl_entry_id = ?", (cl_id,)).fetchone()
    return dict(r) if r else None


def _items(conn):
    return [dict(r) for r in conn.execute(
        "SELECT id, summary, occurred_at, cl_entry_id FROM items ORDER BY id")]


def _legacy_row(conn, desc, day=DAY, url=None, item=True):
    """A row and item as the pre-R1 collector wrote them: no id, no seen_at."""
    conn.execute("INSERT INTO case_entries (case_id, entry_at, description, document_url) "
                 "VALUES ('71499795', ?, ?, ?)", (day, desc, url))
    if item:
        conn.execute(
            "INSERT INTO items (channel, source_id, source_url, title, summary, occurred_at, "
            "fetched_at, admiralty_source, admiralty_info, case_id, content_hash) "
            "VALUES ('litigation', 'courtlistener', 'u', ?, ?, ?, '2026-07-20T19:31:18Z', "
            "'A', '1', '71499795', ?)",
            (f"c: {desc[:180]}", desc, day, common.content_hash("71499795", day, desc)))
    conn.commit()


# --------------------------------------------------------------------------- #
# The rules, as pure functions
# --------------------------------------------------------------------------- #
def test_the_stamp_pattern_is_the_d0s():
    assert co.stamp_of("ORDER granting (Entered: 09/25/2025)") == "09/25/2025"
    assert co.stamp_of("ORDER [Entered: 07/08/2026 02:19 PM]") == "07/08/2026 02:19 PM"
    assert co.stamp_of("ORDER granting") is None
    assert co.unstamped("ORDER x (Entered: 09/25/2025)") == "ORDER x"


def test_adoption_is_one_sided():
    """A stamped text may land on an unstamped held row. The reverse may not, and two
    different stamps never match: that is what fused 23 appellate filings in the D0."""
    assert co.adopts("ORDER x (Entered: 07/20/2026)", "ORDER x") == "stamp"
    assert co.adopts("ORDER x", "ORDER x (Entered: 07/20/2026)") is None
    assert co.adopts("BRIEF [Entered: 07/08/2026 02:19 PM]",
                     "BRIEF [Entered: 07/08/2026 02:21 PM]") is None
    assert co.adopts("ORDER  on   motion", "ORDER on motion") == "ws"
    assert co.adopts("ORDER on motion", "Order on motion") is None   # no casefold


def test_doc_token_strips_appellate_leading_zeros():
    assert co.doc_token("https://www.courtlistener.com/docket/73544809/01208864243/lwv/") == "1208864243"
    assert co.doc_token("https://www.courtlistener.com/docket/72347022/128/1/benson/") == "128"
    assert co.doc_token(None) is None


# --------------------------------------------------------------------------- #
# Poll mode
# --------------------------------------------------------------------------- #
def test_a_new_entry_lands_with_its_id_its_seen_time_and_its_object(tmp_path):
    conn = _db(tmp_path)
    c = _write(conn, [_e(471479890, "Order on motion", number=131)])
    assert c["new_entries"] == 1 and c["new_items"] == 1
    (row,) = _rows(conn)
    assert row["cl_entry_id"] == 471479890 and row["seen_at"]
    o = _obj(conn, 471479890)
    assert o["current_row"] == row["id"] and o["held"] == 1 and o["entry_number"] == 131
    assert [i["cl_entry_id"] for i in _items(conn)] == [471479890]


def test_the_same_entry_served_again_writes_nothing(tmp_path):
    conn = _db(tmp_path)
    _write(conn, [_e(1, "Order on motion")])
    before = _obj(conn, 1)["updated_at"]
    c = _write(conn, [_e(1, "Order on motion", modified="2026-07-22T00:00:00Z")])
    assert c["new_entries"] == c["new_items"] == c["revised"] == 0
    assert len(_rows(conn)) == 1
    o = _obj(conn, 1)
    assert o["updated_at"] == before                      # polled is not revised
    assert o["date_modified"] == "2026-07-22T00:00:00Z"


def test_a_stamp_re_render_of_a_known_entry_is_not_a_new_row(tmp_path):
    """The largest class the D0 measured: 94 rows, a stamp and nothing else. Both ways
    round, since the id already fixes identity."""
    conn = _db(tmp_path)
    _write(conn, [_e(1, "ORDER granting the motion")])
    c = _write(conn, [_e(1, "ORDER granting the motion (Entered: 07/20/2026)")])
    assert (c["new_entries"], c["new_items"], c["cosmetic"], c["revised"]) == (0, 0, 1, 0)
    c = _write(conn, [_e(1, "ORDER  granting the motion")])
    assert (c["new_entries"], c["cosmetic"]) == (0, 1)
    assert len(_rows(conn)) == 1 and len(_items(conn)) == 1


def test_a_re_described_entry_adds_a_row_keeps_the_old_one_and_moves_current(tmp_path):
    """#131: the short form 'Supplemental Memorandum' then the full text, one object."""
    conn = _db(tmp_path)
    _write(conn, [_e(471479890, "Supplemental Memorandum")])
    c = _write(conn, [_e(471479890, "SUPPLEMENTAL MEMORANDUM re 128 MOTION to Enforce filed by X")])
    assert (c["new_entries"], c["revised"]) == (1, 1)
    rows = _rows(conn)
    assert [r["cl_entry_id"] for r in rows] == [471479890, 471479890]
    assert _obj(conn, 471479890)["current_row"] == rows[1]["id"]
    # Every text keeps its item and both items name the object: the fold is the reader's.
    assert {i["cl_entry_id"] for i in _items(conn)} == {471479890}


def test_a_known_entrys_stamp_lands_on_its_own_row_when_a_twin_holds_the_stamped_text(tmp_path):
    """After the walk, 477057380 owns the unstamped row and 477084921 the stamped one. If
    CourtListener stamps 477057380's text too, the exact-text row is the twin's. The
    re-render is cosmetic on 477057380's own row, not 'apart' and not a revision."""
    conn = _db(tmp_path)
    text = "ORDER of the court re briefing schedule"
    stamped = text + " [Entered: 09/04/2026 10:27 PM]"
    _write(conn, [_e(477057380, text), _e(477084921, stamped)])
    own = _obj(conn, 477057380)["current_row"]
    before = _obj(conn, 477057380)["updated_at"]
    c = _write(conn, [_e(477057380, stamped)])
    assert (c["cosmetic"], c["revised"], c["apart"], c["new_entries"]) == (1, 0, 0, 0)
    o = _obj(conn, 477057380)
    assert o["current_row"] == own and o["updated_at"] == before


def test_a_known_entrys_stamp_never_takes_a_twins_unowned_row(tmp_path):
    """The same pair before the walk: the twin's stamped row is held with no id. The known
    entry's re-render lands on its own row and leaves the twin's for the walk."""
    conn = _db(tmp_path)
    text = "ORDER of the court re briefing schedule"
    stamped = text + " [Entered: 09/04/2026 10:27 PM]"
    _legacy_row(conn, stamped)
    _write(conn, [_e(477057380, text)])
    c = _write(conn, [_e(477057380, stamped)])
    assert (c["cosmetic"], c["adopted"]) == (1, 0)
    assert {r["description"]: r["cl_entry_id"] for r in _rows(conn)}[stamped] is None


def test_a_stamp_on_an_earlier_text_lands_on_that_row(tmp_path):
    """A known entry comes back to an earlier text, stamped: a return (history), not a new
    tier-1 row."""
    conn = _db(tmp_path)
    _write(conn, [_e(1, "ORDER one text")])
    _write(conn, [_e(1, "ORDER another text")])
    first = _rows(conn)[0]["id"]
    c = _write(conn, [_e(1, "ORDER one text (Entered: 07/20/2026)")])
    assert (c["new_entries"], c["new_items"], c["revised"]) == (0, 0, 1)
    assert _obj(conn, 1)["current_row"] == first


def test_an_earlier_text_coming_back_moves_current_without_a_row(tmp_path):
    conn = _db(tmp_path)
    _write(conn, [_e(1, "ORDER one text")])
    _write(conn, [_e(1, "ORDER another text")])
    first = _rows(conn)[0]["id"]
    c = _write(conn, [_e(1, "ORDER one text")])
    assert (c["new_entries"], c["revised"]) == (0, 1)
    assert _obj(conn, 1)["current_row"] == first


def test_a_re_date_is_a_new_row_on_the_new_date(tmp_path):
    """Nevada 86998 (Aug 24) re-served as 87067 (Aug 20): one entry, the date mutable."""
    conn = _db(tmp_path)
    _write(conn, [_e(9, "USCA Order Time Schedule", day="2026-08-24")])
    c = _write(conn, [_e(9, "USCA Order Time Schedule", day="2026-08-20")])
    assert (c["new_entries"], c["revised"]) == (1, 1)
    o = _obj(conn, 9)
    assert o["entry_at"] == "2026-08-20T00:00:00"
    assert [r["entry_at"] for r in _rows(conn)] == ["2026-08-24T00:00:00", "2026-08-20T00:00:00"]


def test_an_unknown_entry_adopts_a_legacy_row_by_exact_text(tmp_path):
    conn = _db(tmp_path)
    _legacy_row(conn, "ORDER held before ids")
    c = _write(conn, [_e(5, "ORDER held before ids")])
    assert (c["new_entries"], c["new_items"], c["adopted"]) == (0, 0, 1)
    (row,) = _rows(conn)
    assert row["cl_entry_id"] == 5 and row["seen_at"] is None   # seen_at is never invented
    assert _items(conn)[0]["cl_entry_id"] == 5


def test_an_unknown_stamped_entry_adopts_the_unstamped_legacy_row(tmp_path):
    """The tier-1 re-render: same entry, same document number, a stamp added."""
    conn = _db(tmp_path)
    _legacy_row(conn, "ORDER granting leave", url=URL.format(12))
    c = _write(conn, [_e(5, "ORDER granting leave (Entered: 07/20/2026)", url=URL.format(12))])
    assert (c["new_entries"], c["new_items"], c["adopted"]) == (0, 0, 1)
    assert _rows(conn)[0]["cl_entry_id"] == 5
    assert len(_items(conn)) == 1


def test_a_stamp_never_adopts_a_row_without_the_entrys_document_number(tmp_path):
    """73544809: 88676 (unstamped, no document number) and 88680 (the same text stamped)
    are TWO CourtListener objects, 477057380 and 477084921. If the stamped one is polled
    before the walk, adopting by text alone hands it the other object's row -- and the
    walk, which keeps a poll's owner, never gives it back."""
    conn = _db(tmp_path)
    text = "ORDER of the court re briefing schedule"
    _legacy_row(conn, text)                                           # 88676's shape
    c = _write(conn, [_e(477084921, text + " [Entered: 09/04/2026 10:27 PM]")])
    assert (c["adopted"], c["new_entries"]) == (0, 1)
    co.backfill_docket(conn, "71499795",
                       [_e(477057380, text), _e(477084921, text + " [Entered: 09/04/2026 10:27 PM]")],
                       NOW)
    owners = {r["description"]: r["cl_entry_id"] for r in _rows(conn)}
    assert owners[text] == 477057380
    assert owners[text + " [Entered: 09/04/2026 10:27 PM]"] == 477084921


def test_two_entries_in_one_batch_on_one_document_number_adopt_nothing(tmp_path):
    """The walk's 'wanted by exactly one object' guard, in the form a poll can apply:
    two same-day filings whose texts differ only in their stamps' times."""
    conn = _db(tmp_path)
    _legacy_row(conn, "BRIEF filed by appellant", url=URL.format(9))
    c = _write(conn, [_e(1, "BRIEF filed by appellant [Entered: 07/20/2026 02:19 PM]", url=URL.format(9)),
                      _e(2, "BRIEF filed by appellant [Entered: 07/20/2026 02:21 PM]", url=URL.format(9))])
    assert (c["adopted"], c["new_entries"]) == (0, 2)
    assert _rows(conn)[0]["cl_entry_id"] is None


def test_an_unstamped_entry_never_adopts_a_stamped_legacy_row(tmp_path):
    conn = _db(tmp_path)
    _legacy_row(conn, "ORDER granting leave (Entered: 07/20/2026)")
    c = _write(conn, [_e(5, "ORDER granting leave")])
    assert (c["new_entries"], c["adopted"]) == (1, 0)
    assert [r["cl_entry_id"] for r in _rows(conn)] == [None, 5]


def test_the_uniqueness_guard_refuses_two_candidates(tmp_path):
    conn = _db(tmp_path)
    _legacy_row(conn, "NOTICE of appearance", url=URL.format(4))
    _legacy_row(conn, "NOTICE  of appearance", url=URL.format(4))   # a spacing variant, also held
    c = _write(conn, [_e(5, "NOTICE of appearance [Entered: 07/20/2026 01:00 PM]", url=URL.format(4))])
    assert (c["new_entries"], c["adopted"]) == (1, 0)


def test_a_row_another_entry_owns_is_never_adopted(tmp_path):
    conn = _db(tmp_path)
    _write(conn, [_e(1, "ORDER granting leave", url=URL.format(3))])
    c = _write(conn, [_e(2, "ORDER granting leave (Entered: 07/20/2026)", url=URL.format(3))])
    assert (c["new_entries"], c["adopted"]) == (1, 0)
    assert [r["cl_entry_id"] for r in _rows(conn)] == [1, 2]


def test_two_entries_serving_one_text_on_one_day_keep_the_second_apart(tmp_path):
    """The UNIQUE key holds one row per text and day. R1 needs a rule for the second
    object: it is recorded, held apart, with no row and no item -- nothing a page reads
    changes, and the object table knows it exists."""
    conn = _db(tmp_path)
    _write(conn, [_e(1, "Association Dues for Attorney Licensed Outside the District")])
    c = _write(conn, [_e(2, "Association Dues for Attorney Licensed Outside the District")])
    assert (c["new_entries"], c["new_items"], c["apart"]) == (0, 0, 1)
    o = _obj(conn, 2)
    assert o["current_row"] is None and o["held"] == 1
    assert _rows(conn)[0]["cl_entry_id"] == 1


def test_an_entry_with_no_id_takes_the_old_path(tmp_path):
    conn = _db(tmp_path)
    c = lit.write_entries(conn, "71499795", "c", None,
                          [{"date_filed": "2026-07-20", "description": "ORDER x"}], TYPES, EXCL)
    conn.commit()
    assert c["new_entries"] == 1
    assert _rows(conn)[0]["cl_entry_id"] is None
    assert conn.execute("SELECT COUNT(*) FROM cl_entries").fetchone()[0] == 0


def test_latest_entry_at_follows_the_entry_after_the_switch(tmp_path):
    """MAX over record_entries (the switch): the entry the court re-dated counts at its
    date now, and the stale row it left does not. Nevada reads Aug 20, not Aug 24."""
    conn = _db(tmp_path)
    _write(conn, [_e(9, "USCA Order", day="2026-08-24")])
    _write(conn, [_e(9, "USCA Order", day="2026-08-20")])
    got = conn.execute("SELECT latest_entry_at FROM cases").fetchone()[0]
    assert got == "2026-08-20T00:00:00"


def test_migrations_add_the_columns_to_a_legacy_database(tmp_path):
    """Both tables as Turso holds them before R1. A fresh `items` would come from the new
    schema.sql with the column already in it, so the migration must be tested on an old
    one: schema.sql's CREATE INDEX idx_items_cl_entry fails without it, and every
    collector's init_db with it. Hand-written, not `git show HEAD:schema.sql`, which gains
    the column the moment this change is committed."""
    dbp = str(tmp_path / "legacy.db")
    raw = sqlite3.connect(dbp)
    raw.executescript(
        "CREATE TABLE case_entries (id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL,"
        " entry_at TEXT, description TEXT, document_url TEXT,"
        " UNIQUE(case_id, entry_at, description));"
        "INSERT INTO case_entries (case_id, entry_at, description) VALUES ('1', 'd', 'x');"
        "CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT NOT NULL,"
        " source_id TEXT NOT NULL, source_url TEXT NOT NULL, title TEXT NOT NULL, summary TEXT,"
        " occurred_at TEXT, fetched_at TEXT NOT NULL, admiralty_source TEXT NOT NULL,"
        " admiralty_info TEXT NOT NULL, confidence TEXT, bill_id TEXT, case_id TEXT,"
        " state_bill_id TEXT, outlet TEXT, content_hash TEXT NOT NULL, raw_json TEXT,"
        " UNIQUE(content_hash));"
        "INSERT INTO items (channel, source_id, source_url, title, fetched_at, admiralty_source,"
        " admiralty_info, content_hash) VALUES ('litigation', 's', 'u', 't', 'f', 'A', '1', 'h1');")
    raw.commit()
    raw.close()
    assert "cl_entry_id" not in {r[1] for r in sqlite3.connect(dbp).execute("PRAGMA table_info(items)")}
    db.init_db(dbp)
    conn = db.connect(dbp)
    assert {"cl_entry_id", "seen_at"} <= {r[1] for r in conn.execute("PRAGMA table_info(case_entries)")}
    assert "cl_entry_id" in {r[1] for r in conn.execute("PRAGMA table_info(items)")}
    assert conn.execute("SELECT id FROM case_entries").fetchone()[0] == 1   # the id kept
    assert tuple(conn.execute("SELECT content_hash, cl_entry_id FROM items").fetchone()) == ("h1", None)


# --------------------------------------------------------------------------- #
# Walk mode
# --------------------------------------------------------------------------- #
URL = "https://www.courtlistener.com/docket/71499795/{}/lwv/"


def test_the_walk_attaches_by_text_normalization_and_document_number(tmp_path):
    conn = _db(tmp_path)
    _legacy_row(conn, "Supplemental Memorandum", url=URL.format(131))           # earlier text
    _legacy_row(conn, "SUPPLEMENTAL MEMORANDUM re 128 MOTION", url=URL.format(131))
    _legacy_row(conn, "ORDER granting leave")                                    # stamp adopt
    _legacy_row(conn, "Minute entry nobody serves", item=False)                  # unattached
    walked = [
        _e(471479890, "SUPPLEMENTAL MEMORANDUM re 128 MOTION", url=URL.format(131), number=131),
        _e(2, "ORDER granting leave (Entered: 07/20/2026)"),
        _e(3, "NOTICE psephos never held"),
    ]
    c = co.backfill_docket(conn, "71499795", walked, "2026-10-01T06:30:00Z")
    conn.commit()
    assert c == {"objects": 3, "exact": 1, "adopted": 1, "token": 1, "token_shared": 0,
                 "unattached": 1, "never_held": 1, "stale": 0, "apart": 0}
    adopted_row = {r["description"]: r["id"] for r in _rows(conn)}["ORDER granting leave"]
    assert _obj(conn, 2)["current_row"] == adopted_row
    rows = {r["description"]: r for r in _rows(conn)}
    assert rows["Supplemental Memorandum"]["cl_entry_id"] == 471479890
    assert rows["SUPPLEMENTAL MEMORANDUM re 128 MOTION"]["cl_entry_id"] == 471479890
    assert rows["Minute entry nobody serves"]["cl_entry_id"] is None
    o = _obj(conn, 471479890)
    assert o["current_row"] == rows["SUPPLEMENTAL MEMORANDUM re 128 MOTION"]["id"]
    assert _obj(conn, 3)["held"] == 0 and _obj(conn, 3)["current_row"] is None
    # Every item presenting an attached row names its object; the walk writes no item.
    items = _items(conn)
    assert len(items) == 3
    assert sorted(i["cl_entry_id"] or 0 for i in items) == [2, 471479890, 471479890]


def test_a_document_number_two_entries_share_attaches_nothing(tmp_path):
    """D. Del. 71984384 document 71: a CERTIFICATE OF SERVICE and a RESPONSE, one number.
    The walk sees both objects carry it and ties the leftover row to neither."""
    conn = _db(tmp_path)
    _legacy_row(conn, "CERTIFICATE OF SERVICE old text", url=URL.format(71))
    walked = [_e(10, "CERTIFICATE OF SERVICE", url=URL.format(71)),
              _e(11, "RESPONSE to 70 Notice", url=URL.format(71))]
    c = co.backfill_docket(conn, "71499795", walked, "2026-10-01T06:30:00Z")
    assert (c["token"], c["token_shared"], c["unattached"]) == (0, 1, 1)


def test_an_entry_whose_text_is_not_held_is_stale_and_keeps_its_newest_row(tmp_path):
    conn = _db(tmp_path)
    _legacy_row(conn, "Order", url=URL.format(40))
    _legacy_row(conn, "ORDER on motion", url=URL.format(40))
    walked = [_e(40, "ORDER on motion, re-described upstream since", url=URL.format(40))]
    c = co.backfill_docket(conn, "71499795", walked, "2026-10-01T06:30:00Z")
    assert (c["token"], c["stale"]) == (2, 1)
    assert _obj(conn, 40)["current_row"] == max(r["id"] for r in _rows(conn))


def test_the_walk_keeps_every_row_a_poll_already_stamped(tmp_path):
    conn = _db(tmp_path)
    _write(conn, [_e(1, "ORDER polled after ids")])
    polled = _obj(conn, 1)
    walked = [_e(1, "ORDER polled after ids", number=7)]
    co.backfill_docket(conn, "71499795", walked, "2026-10-01T06:30:00Z")
    o = _obj(conn, 1)
    assert o["current_row"] == polled["current_row"] and o["first_seen_at"] == polled["first_seen_at"]
    assert o["entry_number"] == 7


def test_the_walk_writes_no_row_and_no_item(tmp_path):
    conn = _db(tmp_path)
    _legacy_row(conn, "ORDER one")
    before = (len(_rows(conn)), len(_items(conn)))
    co.backfill_docket(conn, "71499795",
                       [_e(1, "ORDER one"), _e(2, "ORDER never held"), _e(3, "ORDER one x", url=URL.format(3))],
                       "2026-10-01T06:30:00Z")
    assert (len(_rows(conn)), len(_items(conn))) == before


def _walk_case(conn, case_id, n_rows, superseded=None):
    conn.execute("INSERT INTO cases (case_id, caption, status, superseded_by) VALUES (?, 'c', 'pending', ?)",
                 (case_id, superseded))
    for k in range(n_rows):
        conn.execute("INSERT INTO case_entries (case_id, entry_at, description) VALUES (?, ?, ?)",
                     (case_id, DAY, f"ORDER {k}"))
    conn.commit()


def test_the_walk_takes_gate_listed_dockets_first_and_stops_at_the_budget(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    conn.execute("DELETE FROM case_entries")
    _walk_case(conn, "100", 30)                      # 2 pages
    _walk_case(conn, "200", 50)                      # 3 pages, gate-listed
    _walk_case(conn, "300", 10, superseded="100")    # 1 page, superseded: last
    walked = []

    def fake_poll(base, headers, cid, since=None, page_counter=None):
        # Stands in for poll_entries: the walk charges its budget from the meter, so the
        # stub spends what the pages would. The meter's own call sites are tested below.
        assert since is None
        walked.append(cid)
        n = {"100": 2, "200": 3, "300": 1}[cid]
        for _ in range(n):
            lit.SPEND.hit()
        page_counter[0] += n
        rows = conn.execute("SELECT id, description FROM case_entries WHERE case_id = ?",
                            (cid,)).fetchall()
        return [_e(10_000 + r["id"], r["description"]) for r in rows], None

    monkeypatch.setattr(lit, "poll_entries", fake_poll)
    lit.SPEND.__init__()
    out = lit.backfill_walk(conn, "b", {}, 5, {"200"})
    assert walked == ["200", "100"]                  # listed first; 300 would need a 6th
    assert (out["walked"], out["requests"], out["left"]) == (2, 5, 1)
    assert lit.SPEND.backfill == 5
    assert {r[0] for r in conn.execute("SELECT case_id FROM cl_backfill")} == {"100", "200"}
    walked.clear()
    out = lit.backfill_walk(conn, "b", {}, 5, {"200"})
    assert walked == ["300"] and out["left"] == 0    # a walked docket is never walked again


def test_a_failed_walk_writes_nothing_and_walks_again(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    conn.execute("INSERT INTO case_entries (case_id, entry_at, description) "
                 "VALUES ('71499795', ?, 'ORDER x')", (DAY,))
    conn.commit()

    def boom(*a, **k):
        raise RuntimeError("persistent empty pages")

    monkeypatch.setattr(lit, "poll_entries", boom)
    out = lit.backfill_walk(conn, "b", {}, 50, set())
    assert (out["walked"], out["failed"], out["left"]) == (0, 1, 1)
    assert conn.execute("SELECT COUNT(*) FROM cl_backfill").fetchone()[0] == 0
    assert conn.execute("SELECT failures FROM cl_backfill_attempts").fetchone()[0] == 1
    assert lit.backfill_due(conn, set()) == [("71499795", 1)]


def test_the_daily_ledger_accumulates_across_runs(tmp_path):
    conn = _db(tmp_path)
    lit.SPEND.__init__()
    lit.SPEND.total, lit.SPEND.backfill = 40, 25
    lit.record_spend(conn)
    lit.SPEND.total, lit.SPEND.backfill = 10, 0
    line = lit.record_spend(conn)
    r = conn.execute("SELECT requests, backfill FROM cl_usage").fetchone()
    assert (r["requests"], r["backfill"]) == (50, 25)
    assert "so far 50, backfill 25" in line
    lit.SPEND.__init__()


def test_gate_listed_dockets_reads_authored_unfalsified_gates_only(tmp_path):
    g = tmp_path / "gates.yaml"
    g.write_text("- {id: a, kind: authored, status: active, record_instruments: [1]}\n"
                 "- {id: f, kind: authored, status: falsified, record_instruments: [2]}\n"
                 "- {id: d, kind: derived, record_instruments: [3]}\n", encoding="utf-8")
    assert lit.gate_listed_dockets(g) == {"1"}
    assert lit.gate_listed_dockets(tmp_path / "missing.yaml") == set()
    bad = tmp_path / "bad.yaml"
    bad.write_text("- [unclosed", encoding="utf-8")
    assert lit.gate_listed_dockets(bad) == set()


def test_the_live_register_lists_the_eight_gate_listed_dockets():
    """A check of docs/gates.yaml's contents as of 2026-09-30, not of the function."""
    assert {"73131864", "74755121", "73133197", "74701505", "73568304", "73141063",
            "73544809", "71499795"} <= lit.gate_listed_dockets()


# --------------------------------------------------------------------------- #
# The review's findings, one test each (2026-09-30)
# --------------------------------------------------------------------------- #
def test_walk_two_stamped_objects_wanting_one_unstamped_row_attach_neither(tmp_path):
    conn = _db(tmp_path)
    _legacy_row(conn, "BRIEF filed")
    walked = [_e(1, "BRIEF filed [Entered: 07/20/2026 02:19 PM]"),
              _e(2, "BRIEF filed [Entered: 07/20/2026 02:21 PM]")]
    c = co.backfill_docket(conn, "71499795", walked, NOW)
    assert (c["adopted"], c["unattached"]) == (0, 1)


def test_walk_refuses_two_candidate_rows(tmp_path):
    conn = _db(tmp_path)
    _legacy_row(conn, "NOTICE of appearance")
    _legacy_row(conn, "NOTICE  of appearance")
    c = co.backfill_docket(conn, "71499795",
                           [_e(5, "NOTICE of appearance [Entered: 07/20/2026 01:00 PM]")], NOW)
    assert (c["adopted"], c["unattached"]) == (0, 2)


def test_walk_never_adopts_across_days(tmp_path):
    conn = _db(tmp_path)
    _legacy_row(conn, "NOTICE of appearance", day="2026-07-19T00:00:00")
    c = co.backfill_docket(conn, "71499795", [_e(5, "NOTICE of appearance (Entered: 07/20/2026)")], NOW)
    assert c["adopted"] == 0 and _rows(conn)[0]["cl_entry_id"] is None


def test_walk_second_object_with_the_same_text_is_apart_and_held(tmp_path):
    conn = _db(tmp_path)
    _legacy_row(conn, "Association Dues", item=False)
    c = co.backfill_docket(conn, "71499795", [_e(1, "Association Dues"), _e(2, "Association Dues")], NOW)
    assert (c["exact"], c["apart"], c["never_held"]) == (1, 1, 0)
    assert _obj(conn, 2)["held"] == 1 and _obj(conn, 2)["current_row"] is None


def test_walk_keeps_a_polled_rows_owner_against_another_object(tmp_path):
    conn = _db(tmp_path)
    _write(conn, [_e(1, "Association Dues")])
    c = co.backfill_docket(conn, "71499795", [_e(2, "Association Dues"), _e(1, "Association Dues")], NOW)
    assert c["apart"] == 1
    assert _rows(conn)[0]["cl_entry_id"] == 1 and _obj(conn, 2)["current_row"] is None


def test_walk_attaches_every_row_past_one_chunk(tmp_path):
    conn = _db(tmp_path)
    for k in range(250):
        _legacy_row(conn, f"ORDER {k}")
    c = co.backfill_docket(conn, "71499795", [_e(1000 + k, f"ORDER {k}") for k in range(250)], NOW)
    assert c["exact"] == 250
    bad = conn.execute("SELECT COUNT(*) FROM case_entries WHERE cl_entry_id IS NULL OR "
                       "cl_entry_id != 1000 + CAST(substr(description, 7) AS INTEGER)").fetchone()[0]
    assert bad == 0
    bad_items = conn.execute("SELECT COUNT(*) FROM items WHERE cl_entry_id IS NULL OR "
                             "cl_entry_id != 1000 + CAST(substr(summary, 7) AS INTEGER)").fetchone()[0]
    assert bad_items == 0
    assert conn.execute("SELECT COUNT(*) FROM cl_entries").fetchone()[0] == 250


def test_poll_after_walk_marks_a_never_held_object_held(tmp_path):
    conn = _db(tmp_path)
    co.backfill_docket(conn, "71499795", [_e(3, "NOTICE psephos never held")], NOW)
    conn.commit()
    assert _obj(conn, 3)["held"] == 0 and _obj(conn, 3)["first_seen_at"] is None
    _write(conn, [_e(3, "NOTICE psephos never held")])
    o = _obj(conn, 3)
    assert o["held"] == 1 and o["current_row"] is not None and o["first_seen_at"]


def test_an_objects_clock_is_what_psephos_held_never_the_walks_time(tmp_path):
    """Legacy items carry fetched_at 2026-07-20T19:31:18Z (see _legacy_row). A legacy row
    with no item and no seen_at leaves the clock NULL for step (c)."""
    conn = _db(tmp_path)
    _legacy_row(conn, "ORDER held in July", url=URL.format(8))
    _legacy_row(conn, "Minute entry, no item", item=False)
    co.backfill_docket(conn, "71499795", [_e(8, "ORDER held in July", url=URL.format(8)),
                                          _e(9, "Minute entry, no item")], NOW)
    assert (_obj(conn, 8)["first_seen_at"], _obj(conn, 8)["updated_at"]) == \
        ("2026-07-20T19:31:18Z", "2026-07-20T19:31:18Z")
    assert (_obj(conn, 9)["first_seen_at"], _obj(conn, 9)["updated_at"]) == (None, None)
    # The poll-adopt path takes the same evidence.
    _legacy_row(conn, "ORDER adopted by a poll")
    _write(conn, [_e(10, "ORDER adopted by a poll")])
    assert _obj(conn, 10)["first_seen_at"] == "2026-07-20T19:31:18Z"
    # A new text is held now.
    _write(conn, [_e(11, "ORDER new today")])
    assert _obj(conn, 11)["first_seen_at"] > "2026-09-30"


def test_the_walk_records_the_tier_two_fingerprint(tmp_path):
    conn = _db(tmp_path)
    e = _e(471517786, "", url=URL.format(0))
    e["recap_documents"] = [{"absolute_url": None, "description": "Order on Motion to Enforce Judgment"}]
    e["time_filed"], e["date_created"] = "17:47:07", "2026-07-20T21:47:12Z"
    co.backfill_docket(conn, "71499795", [e, _e(471527695, "MINUTE ORDER: The Court has reviewed")], NOW)
    short, full = _obj(conn, 471517786), _obj(conn, 471527695)
    assert (short["desc_source"], short["time_filed"], short["date_created"]) == \
        ("document", "17:47:07", "2026-07-20T21:47:12Z")
    assert (full["desc_source"], full["time_filed"]) == ("entry", None)


def test_backfill_due_puts_superseded_dockets_last_whatever_their_id(tmp_path):
    conn = _db(tmp_path)
    conn.execute("DELETE FROM case_entries")
    _walk_case(conn, "900", 1)
    _walk_case(conn, "100", 1, superseded="900")
    assert [c for c, _ in lit.backfill_due(conn, set())] == ["900", "100"]
    assert [c for c, _ in lit.backfill_due(conn, {"100"})] == ["100", "900"]   # listed first


def test_backfill_due_skips_a_docket_whose_rows_all_carry_ids(tmp_path):
    conn = _db(tmp_path)
    _write(conn, [_e(1, "ORDER polled after ids")])
    assert lit.backfill_due(conn, set()) == []


def _two_page_walk(monkeypatch, pages):
    """common.http_get serving `pages` in order; it calls on_attempt as the real one does."""
    it = iter(pages)

    def fake(url, params=None, headers=None, timeout=None, throttle=0.0, on_attempt=None):
        if on_attempt is not None:
            on_attempt()
        return next(it)
    monkeypatch.setattr(common, "http_get", fake)


def test_the_meter_counts_at_every_real_call_site(tmp_path, monkeypatch):
    monkeypatch.setattr(lit.time, "sleep", lambda *a, **k: None)
    lit.SPEND.__init__()
    _two_page_walk(monkeypatch, [{"results": [{"id": 1}]}])
    lit.resolve_docket("b", {}, "1:25-cv-1", "dcd")
    assert lit.SPEND.total == 1
    _two_page_walk(monkeypatch, [{"id": 5}])
    lit.fetch_docket("b", {}, "5")
    assert lit.SPEND.total == 2
    _two_page_walk(monkeypatch, [{"results": [{"id": 1}], "next": "n"}, {"results": [{"id": 2}], "next": None}])
    lit.poll_entries("b", {}, "1", since=None)
    assert lit.SPEND.total == 4
    _two_page_walk(monkeypatch, [{"results": [], "next": None}])
    lit.poll_entries("b", {}, "1", since="2026-01-01T00:00:00Z")
    assert lit.SPEND.total == 5
    conn = _db(tmp_path)
    _two_page_walk(monkeypatch, [{"date_terminated": None}])
    lit.refresh_status(conn, "b", {}, "2099-01-01", 5)
    assert (lit.SPEND.total, lit.SPEND.backfill) == (6, 0)
    lit.SPEND.__init__()


def test_the_walk_charges_the_requests_it_made_and_receipts_them(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    _legacy_row(conn, "ORDER a", url=URL.format(1))
    _legacy_row(conn, "Order b", url=URL.format(2))
    _legacy_row(conn, "ORDER b in full", url=URL.format(2))
    monkeypatch.setattr(lit.time, "sleep", lambda *a, **k: None)
    _two_page_walk(monkeypatch, [
        {"results": [_e(1, "ORDER a", url=URL.format(1))], "next": "n"},
        {"results": [_e(2, "ORDER b in full", url=URL.format(2))], "next": None}])
    lit.SPEND.__init__()
    out = lit.backfill_walk(conn, "b", {}, 50, set())
    r = dict(conn.execute("SELECT * FROM cl_backfill").fetchone())
    assert (out["requests"], out["attached"], lit.SPEND.backfill) == (2, 3, 2)
    assert (r["requests"], r["rows"], r["objects"], r["exact"], r["token"], r["unattached"]) == \
        (2, 3, 2, 2, 1, 0)
    lit.SPEND.__init__()


def test_an_upstream_failure_ends_the_walk_for_the_run(tmp_path, monkeypatch):
    """A 503 outage: every walk's first page exhausts its retries. The first failure ends
    the run's walk instead of trying all 61 dockets at ~18s to ~138s each."""
    conn = _db(tmp_path)
    conn.execute("DELETE FROM case_entries")
    for cid in ("100", "200", "300"):
        _walk_case(conn, cid, 1)
    tried = []

    def down(base, headers, cid, since=None, page_counter=None):
        tried.append(cid)
        for _ in range(4):
            lit.SPEND.hit()
        raise common.RetriesExhausted("gave up after 4 attempts", status=503)

    monkeypatch.setattr(lit, "poll_entries", down)
    lit.SPEND.__init__()
    out = lit.backfill_walk(conn, "b", {}, 120, set())
    # Two in a row is the upstream, not a docket: the run's walk ends at the second.
    assert tried == ["100", "200"] and (out["failed"], out["left"], out["requests"]) == (2, 3, 8)
    assert "second in a row" in out["stopped"]
    lit.SPEND.__init__()


def test_a_4xx_on_one_docket_skips_it_and_walks_on(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    conn.execute("DELETE FROM case_entries")
    _walk_case(conn, "100", 1)
    _walk_case(conn, "200", 1)
    tried = []

    def gone(base, headers, cid, since=None, page_counter=None):
        tried.append(cid)
        if cid == "100":
            raise common.HttpError(404, "u", "Not found.")
        rows = conn.execute("SELECT id, description FROM case_entries WHERE case_id = ?", (cid,)).fetchall()
        return [_e(50_000 + r["id"], r["description"]) for r in rows], None

    monkeypatch.setattr(lit, "poll_entries", gone)
    out = lit.backfill_walk(conn, "b", {}, 120, set())
    assert tried == ["100", "200"] and (out["walked"], out["failed"]) == (1, 1)


def test_an_empty_walk_of_a_docket_that_holds_rows_is_a_failure_not_a_receipt(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    _legacy_row(conn, "ORDER x")
    monkeypatch.setattr(lit, "poll_entries", lambda *a, **k: ([], None))
    out = lit.backfill_walk(conn, "b", {}, 50, set())
    assert (out["walked"], out["failed"], out["left"]) == (0, 1, 1)
    assert conn.execute("SELECT COUNT(*) FROM cl_backfill").fetchone()[0] == 0
    assert "served no entries" in conn.execute("SELECT last_error FROM cl_backfill_attempts").fetchone()[0]
    assert lit.backfill_due(conn, set()) == [("71499795", 1)]


def test_the_estimate_refuses_a_docket_that_does_not_fit_what_is_left(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    conn.execute("DELETE FROM case_entries")
    _walk_case(conn, "100", 1)                       # 1 page, walked first
    _walk_case(conn, "200", 50)                      # ~3 pages: does not fit 1 left
    tried = []

    def one_page(base, headers, cid, since=None, page_counter=None):
        tried.append(cid)
        lit.SPEND.hit()
        rows = conn.execute("SELECT id, description FROM case_entries WHERE case_id = ?", (cid,)).fetchall()
        return [_e(60_000 + r["id"], r["description"]) for r in rows], None

    monkeypatch.setattr(lit, "poll_entries", one_page)
    lit.SPEND.__init__()
    out = lit.backfill_walk(conn, "b", {}, 2, set())
    assert tried == ["100"] and out["left"] == 1 and "needs ~3" in out["stopped"]
    lit.SPEND.__init__()


def test_a_docket_bigger_than_a_whole_run_starts_on_a_fresh_run(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    conn.execute("DELETE FROM case_entries")
    _walk_case(conn, "100", 50)                      # ~3 pages against a budget of 2
    tried = []
    monkeypatch.setattr(lit, "poll_entries", lambda b, h, cid, **k: tried.append(cid) or (
        [_e(70_000 + r["id"], r["description"]) for r in conn.execute(
            "SELECT id, description FROM case_entries WHERE case_id = ?", (cid,)).fetchall()], None))
    out = lit.backfill_walk(conn, "b", {}, 2, set())
    assert tried == ["100"] and out["walked"] == 1


def test_the_walk_stops_at_the_daily_cap(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    conn.execute("DELETE FROM case_entries")
    _walk_case(conn, "100", 1)
    _walk_case(conn, "200", 1)
    calls = []

    def capped(base, headers, cid, since=None, page_counter=None):
        calls.append(cid)
        raise common.RateBudgetExhausted(60)

    monkeypatch.setattr(lit, "poll_entries", capped)
    out = lit.backfill_walk(conn, "b", {}, 50, set())
    assert calls == ["100"] and out["daily_cap"] and out["left"] == 2


def test_a_failed_write_leaves_no_id_from_that_docket(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    _legacy_row(conn, "ORDER x")
    monkeypatch.setattr(lit, "poll_entries", lambda *a, **k: ([_e(1, "ORDER x")], None))
    real = co._insert_objects

    def half(conn_, objs):
        raise ValueError("Hrana: stream not found")    # after _set_ids has run

    monkeypatch.setattr(co, "_insert_objects", half)
    out = lit.backfill_walk(conn, "b", {}, 50, set())
    monkeypatch.setattr(co, "_insert_objects", real)
    assert out["failed"] == 1
    assert _rows(conn)[0]["cl_entry_id"] is None
    assert conn.execute("SELECT COUNT(*) FROM cl_backfill").fetchone()[0] == 0


# --- main(): the wiring, on the real config ---------------------------------------
def _main_env(tmp_path, monkeypatch):
    import copy
    dbp = str(tmp_path / "m.db")
    monkeypatch.setattr(config, "load_env", lambda *a, **k: None)
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "DB_PATH", dbp)
    monkeypatch.setenv("COURTLISTENER_TOKEN", "test-token")
    src = copy.deepcopy(config.load_sources())
    src["litigation"]["seed_cases"] = []            # the real config, seeds emptied
    monkeypatch.setattr(config, "load_sources", lambda *a, **k: src)
    monkeypatch.setattr(lit, "load_tracker_seeds", lambda *a, **k: [])
    lit.SPEND.__init__()
    db.init_db(dbp)
    c = db.connect(dbp)
    # Terminated, so the status refresh never selects it; one bare row, so it is due.
    c.execute("INSERT INTO cases (case_id, caption, status) VALUES ('100', 'c', 'terminated')")
    c.execute("INSERT INTO case_entries (case_id, entry_at, description) "
              "VALUES ('100', '2026-07-20T00:00:00', 'ORDER granting x')")
    c.commit()
    c.close()
    return dbp, src


def _walk_one(calls):
    def fake(base, headers, cid, since=None, page_counter=None):
        calls.append((cid, since))
        lit.SPEND.hit()
        return [_e(9001, "ORDER granting x")], None
    return fake


def test_main_runs_the_backfill_on_the_real_config_key_and_writes_the_ledger(tmp_path, monkeypatch):
    dbp, _ = _main_env(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(lit, "poll_entries", _walk_one(calls))
    assert lit.main() == 0
    assert calls == [("100", None)]
    c = db.connect(dbp)
    assert c.execute("SELECT cl_entry_id FROM case_entries").fetchone()[0] == 9001
    r = c.execute("SELECT requests, backfill FROM cl_usage").fetchone()
    assert (r["requests"], r["backfill"]) == (1, 1)
    lit.SPEND.__init__()


def test_main_skips_the_backfill_when_the_refresh_hit_the_daily_cap(tmp_path, monkeypatch):
    dbp, _ = _main_env(tmp_path, monkeypatch)
    c = db.connect(dbp)
    c.execute("INSERT INTO cases (case_id, caption, status) VALUES ('200', 'c2', 'pending')")
    c.commit()
    c.close()

    def capped(*a, **k):
        raise common.RateBudgetExhausted(46)

    monkeypatch.setattr(common, "http_get", capped)
    calls = []
    monkeypatch.setattr(lit, "poll_entries", _walk_one(calls))
    assert lit.main() == 0
    assert calls == []


def test_main_skips_the_backfill_when_the_seed_loop_hit_the_cap(tmp_path, monkeypatch):
    _, src = _main_env(tmp_path, monkeypatch)
    src["litigation"]["seed_cases"] = [{"caption": "US v. S", "docket_number": "1:25-cv-00001",
                                         "court": "X", "court_id": "xxd",
                                         "category": "voter-data", "notes": "n"}]

    def cap_out(*a, **k):
        raise common.RateBudgetExhausted(46)

    monkeypatch.setattr(lit, "resolve_docket", cap_out)
    called = []
    monkeypatch.setattr(lit, "backfill_walk", lambda *a, **k: called.append(1))
    assert lit.main() == 0
    assert called == []


def test_main_survives_a_raising_walk_and_a_raising_recover(tmp_path, monkeypatch):
    """A dead remote: the walk raises, and so does the recover its handler calls. The
    collector still exits 0 and still tries its ledger (run_signals.flush's rule)."""
    dbp, _ = _main_env(tmp_path, monkeypatch)

    def boom(*a, **k):
        raise ValueError("Hrana: api error: status=502 Bad Gateway")

    monkeypatch.setattr(lit, "backfill_walk", boom)
    monkeypatch.setattr(db, "recover", boom)
    assert lit.main() == 0
    c = db.connect(dbp)
    assert c.execute("SELECT COUNT(*) FROM cl_usage").fetchone()[0] == 1


def test_main_survives_a_ledger_write_that_fails_with_its_recover(tmp_path, monkeypatch):
    _main_env(tmp_path, monkeypatch)
    monkeypatch.setattr(lit, "poll_entries", _walk_one([]))

    def boom(*a, **k):
        raise ValueError("Hrana: api error: status=502 Bad Gateway")

    monkeypatch.setattr(lit, "record_spend", boom)
    monkeypatch.setattr(db, "recover", boom)
    assert lit.main() == 0
    lit.SPEND.__init__()


def test_main_notes_a_deferral_while_dockets_are_left(tmp_path, monkeypatch):
    dbp, src = _main_env(tmp_path, monkeypatch)
    src["litigation"]["max_backfill_requests_per_run"] = 1
    c = db.connect(dbp)
    c.execute("INSERT INTO cases (case_id, caption, status) VALUES ('200', 'c', 'terminated')")
    c.execute("INSERT INTO case_entries (case_id, entry_at, description) "
              "VALUES ('200', '2026-07-20T00:00:00', 'ORDER y')")
    c.commit()
    c.close()
    monkeypatch.setattr(lit, "poll_entries", _walk_one([]))
    assert lit.main() == 0
    c = db.connect(dbp)
    cls = {r["class"] for r in c.execute("SELECT class FROM channel_runs")}
    assert "deferred" in cls and "cut short" not in cls
    lit.SPEND.__init__()


# --------------------------------------------------------------------------- #
# The second review's findings (2026-09-30)
# --------------------------------------------------------------------------- #
TEXT_73544809 = "ORDER of the court re briefing schedule"
STAMP_73544809 = TEXT_73544809 + " [Entered: 09/04/2026 10:27 PM]"


def test_a_re_stamped_twin_never_swaps_rows_walk_first(tmp_path):
    """88676 (U) and 88680 (S) on 73544809 belong to 477057380 and 477084921. If
    CourtListener stamps 477057380 too, both serve S. The walk gives S to one of them and
    must not hand U to the other by the stamp rule: U stays unattached, the second object
    is held apart, and the receipt shows both."""
    conn = _db(tmp_path)
    _legacy_row(conn, TEXT_73544809)
    _legacy_row(conn, STAMP_73544809)
    c = co.backfill_docket(conn, "71499795", [_e(477057380, STAMP_73544809),
                                              _e(477084921, STAMP_73544809)], NOW)
    owners = {r["description"]: r["cl_entry_id"] for r in _rows(conn)}
    assert owners[TEXT_73544809] is None
    assert (c["adopted"], c["unattached"], c["apart"]) == (0, 1, 1)


def test_a_re_stamped_twin_never_swaps_rows_poll_first(tmp_path):
    conn = _db(tmp_path)
    _legacy_row(conn, TEXT_73544809)
    _legacy_row(conn, STAMP_73544809)
    _write(conn, [_e(477057380, STAMP_73544809)])             # adopts S, exact
    co.backfill_docket(conn, "71499795", [_e(477057380, STAMP_73544809),
                                          _e(477084921, STAMP_73544809)], NOW)
    owners = {r["description"]: r["cl_entry_id"] for r in _rows(conn)}
    assert owners[TEXT_73544809] is None


def test_the_walk_gives_an_object_its_earlier_tokenless_text(tmp_path):
    """A tokenless tier-1 re-render polled before the walk: the poll inserts the stamped
    text as a new row (no token, so no adoption), and the walk then ties the legacy row to
    the same object, since only that object's text reaches it."""
    conn = _db(tmp_path)
    _legacy_row(conn, "MINUTE ORDER granting motion")
    _write(conn, [_e(7, "MINUTE ORDER granting motion (Entered: 07/20/2026)")])
    c = co.backfill_docket(conn, "71499795", [_e(7, "MINUTE ORDER granting motion (Entered: 07/20/2026)")], NOW)
    assert c["adopted"] == 1
    assert {r["cl_entry_id"] for r in _rows(conn)} == {7}


def test_a_tokened_stamped_entry_never_adopts_a_tokenless_legacy_row(tmp_path):
    """The 73582123 shape: a plain row with no document, then its stamped twin WITH one.
    Whether these pairs are one object has not been observed (73582123 is unwalked); a
    poll does not decide it by text."""
    conn = _db(tmp_path)
    _legacy_row(conn, "HARD COPY RECEIVED of brief")
    c = _write(conn, [_e(900, "HARD COPY RECEIVED of brief [Entered: 08/20/2026 01:00 PM]",
                         url=URL.format(40))])
    assert (c["adopted"], c["new_entries"]) == (0, 1)
    assert _rows(conn)[0]["cl_entry_id"] is None


def test_a_stamped_entry_never_adopts_a_row_on_another_document(tmp_path):
    conn = _db(tmp_path)
    _legacy_row(conn, "ORDER granting leave", url=URL.format(12))
    c = _write(conn, [_e(5, "ORDER granting leave (Entered: 07/20/2026)", url=URL.format(13))])
    assert (c["adopted"], c["new_entries"]) == (0, 1)


def test_an_entry_served_twice_in_one_window_still_adopts(tmp_path):
    conn = _db(tmp_path)
    _legacy_row(conn, "ORDER granting leave", url=URL.format(12))
    e1 = _e(5, "ORDER granting leave (Entered: 07/20/2026)", url=URL.format(12))
    e2 = _e(5, "ORDER granting leave (Entered: 07/20/2026)", url=URL.format(12),
            modified="2026-07-22T00:00:00Z")
    c = _write(conn, [e1, e2])
    assert (c["adopted"], c["new_entries"], c["new_items"]) == (1, 0, 0)
    assert len(_rows(conn)) == 1


def test_a_polled_apart_object_gets_its_row_from_the_walk(tmp_path):
    """Poll B, then a re-stamped A that is held apart, then the walk: A's current row is
    the row the walk gives it, and a later re-serve is cosmetic, not a revision."""
    conn = _db(tmp_path)
    _legacy_row(conn, TEXT_73544809)
    _legacy_row(conn, STAMP_73544809)
    _write(conn, [_e(477084921, STAMP_73544809)])            # B adopts S exactly
    _write(conn, [_e(477057380, STAMP_73544809)])            # A: S is B's, so apart
    assert _obj(conn, 477057380)["current_row"] is None
    co.backfill_docket(conn, "71499795", [_e(477057380, TEXT_73544809),
                                          _e(477084921, STAMP_73544809)], NOW)
    u = {r["description"]: r["id"] for r in _rows(conn)}[TEXT_73544809]
    assert _obj(conn, 477057380)["current_row"] == u
    c = _write(conn, [_e(477057380, TEXT_73544809)])
    assert (c["revised"], c["new_entries"]) == (0, 0)


def test_an_apart_objects_clock_is_the_same_in_both_orders(tmp_path):
    for order in ("poll", "walk"):
        sub = tmp_path / order
        sub.mkdir()
        conn = _db(sub)
        _legacy_row(conn, "CORRECTING ENTRY")                  # item fetched 2026-07-20T19:31:18Z
        if order == "poll":
            _write(conn, [_e(1, "CORRECTING ENTRY"), _e(2, "CORRECTING ENTRY")])
        else:
            co.backfill_docket(conn, "71499795", [_e(1, "CORRECTING ENTRY"), _e(2, "CORRECTING ENTRY")], NOW)
        o = _obj(conn, 2)
        assert o["current_row"] is None, order
        assert o["first_seen_at"] == "2026-07-20T19:31:18Z", order


def test_a_re_serve_keeps_a_legacy_objects_null_clock(tmp_path):
    conn = _db(tmp_path)
    _legacy_row(conn, "Minute entry, no item", item=False)
    co.backfill_docket(conn, "71499795", [_e(9, "Minute entry, no item")], NOW)
    conn.commit()
    assert _obj(conn, 9)["first_seen_at"] is None and _obj(conn, 9)["held"] == 1
    _write(conn, [_e(9, "Minute entry, no item", modified="2026-10-02T00:00:00Z")])
    o = _obj(conn, 9)
    assert (o["first_seen_at"], o["updated_at"]) == (None, None)
    assert o["date_modified"] == "2026-10-02T00:00:00Z"


def test_the_walk_clock_is_earliest_first_latest_last(tmp_path):
    conn = _db(tmp_path)
    _legacy_row(conn, "Order", url=URL.format(40))
    _legacy_row(conn, "ORDER on motion", url=URL.format(40))
    conn.execute("UPDATE items SET fetched_at = '2026-08-01T00:00:00Z' WHERE summary = 'ORDER on motion'")
    conn.commit()
    co.backfill_docket(conn, "71499795", [_e(40, "ORDER on motion", url=URL.format(40))], NOW)
    o = _obj(conn, 40)
    assert (o["first_seen_at"], o["updated_at"]) == ("2026-07-20T19:31:18Z", "2026-08-01T00:00:00Z")


def test_a_cosmetic_re_serve_lands_on_the_current_row_when_two_own_rows_match(tmp_path):
    conn = _db(tmp_path)
    _legacy_row(conn, "ORDER x", url=URL.format(7))
    _legacy_row(conn, "ORDER x (Entered: 07/20/2026)", url=URL.format(7))
    co.backfill_docket(conn, "71499795", [_e(7, "ORDER x (Entered: 07/20/2026)", url=URL.format(7))], NOW)
    conn.commit()
    o = _obj(conn, 7)
    cur, before = o["current_row"], o["updated_at"]
    c = _write(conn, [_e(7, "ORDER x [Entered: 07/20/2026 10:27 AM]", url=URL.format(7))])
    assert (c["cosmetic"], c["revised"], c["new_entries"]) == (1, 0, 0)
    o = _obj(conn, 7)
    assert o["current_row"] == cur and o["updated_at"] == before


def test_the_poll_and_the_walk_both_keep_the_fingerprint(tmp_path):
    conn = _db(tmp_path)
    e = _e(1, "ORDER x")
    e["time_filed"], e["date_created"] = "11:19:37", "2026-07-18T15:19:37Z"
    _write(conn, [e])
    o = _obj(conn, 1)
    assert (o["time_filed"], o["date_created"], o["desc_source"]) == ("11:19:37", "2026-07-18T15:19:37Z", "entry")
    # A walk over an object a poll recorded without a fingerprint fills it.
    (tmp_path / "w").mkdir()
    conn2 = _db(tmp_path / "w")
    _write(conn2, [_e(2, "ORDER y")])
    w = _e(2, "ORDER y")
    w["time_filed"], w["date_created"] = "17:47:07", "2026-07-20T21:47:12Z"
    co.backfill_docket(conn2, "71499795", [w], NOW)
    o = _obj(conn2, 2)
    assert (o["time_filed"], o["date_created"]) == ("17:47:07", "2026-07-20T21:47:12Z")


# --- the walk's queue and stop rules ----------------------------------------------
def _serve_rows(conn, prefix=80_000):
    def fake(base, headers, cid, since=None, page_counter=None):
        lit.SPEND.hit()
        rows = conn.execute("SELECT id, description FROM case_entries WHERE case_id = ?", (cid,)).fetchall()
        return [_e(prefix + r["id"], r["description"]) for r in rows], None
    return fake


def test_a_docket_that_always_fails_moves_behind_the_healthy_ones(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    conn.execute("DELETE FROM case_entries")
    for cid in ("100", "200", "300"):
        _walk_case(conn, cid, 1)
    healthy = _serve_rows(conn)
    tried = []

    def poll(base, headers, cid, since=None, page_counter=None):
        tried.append(cid)
        if cid == "100":
            raise common.RetriesExhausted("gave up", status=500)
        return healthy(base, headers, cid)

    monkeypatch.setattr(lit, "poll_entries", poll)
    out = lit.backfill_walk(conn, "b", {}, 120, set())
    assert tried == ["100", "200", "300"] and (out["walked"], out["failed"], out["left"]) == (2, 1, 1)
    # Next run it is the only one due; after BACKFILL_LOUD_AFTER failures it is stuck.
    for _ in range(lit.BACKFILL_LOUD_AFTER - 1):
        out = lit.backfill_walk(conn, "b", {}, 120, set())
    assert out["stuck"] and out["stuck"][0][:2] == ("100", lit.BACKFILL_LOUD_AFTER)


def test_a_failed_docket_goes_behind_one_that_never_failed(tmp_path):
    conn = _db(tmp_path)
    conn.execute("DELETE FROM case_entries")
    _walk_case(conn, "100", 1)
    _walk_case(conn, "200", 1)
    lit._walk_failed(conn, "100", "HTTP 500")
    assert [c for c, _ in lit.backfill_due(conn, set())] == ["200", "100"]
    assert [c for c, _ in lit.backfill_due(conn, {"100"})] == ["100", "200"]   # listed still first


def test_a_walk_truncated_by_an_empty_page_past_a_cursor_writes_nothing(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    for k in range(25):
        _legacy_row(conn, f"ORDER {k}", item=False)
    monkeypatch.setattr(lit.time, "sleep", lambda *a, **k: None)
    page1 = {"results": [_e(1000 + k, f"ORDER {k}") for k in range(20)], "next": "cursor"}
    empties = [{"results": [], "next": None}] * lit.EMPTY_RETRIES
    _two_page_walk(monkeypatch, [page1] + empties)
    out = lit.backfill_walk(conn, "b", {}, 50, set())
    assert (out["walked"], out["failed"]) == (0, 1)
    assert conn.execute("SELECT COUNT(*) FROM cl_backfill").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM case_entries WHERE cl_entry_id IS NOT NULL").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM cl_entries").fetchone()[0] == 0


def test_an_empty_walk_then_another_ends_the_runs_walk(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    conn.execute("DELETE FROM case_entries")
    for cid in ("100", "200", "300"):
        _walk_case(conn, cid, 1)
    tried = []
    monkeypatch.setattr(lit, "poll_entries", lambda b, h, cid, **k: tried.append(cid) or ([], None))
    out = lit.backfill_walk(conn, "b", {}, 50, set())
    assert tried == ["100", "200"] and (out["failed"], out["left"]) == (2, 3)
    assert "served no entries" in out["stopped"]


def test_a_401_ends_the_walk_and_a_repeated_4xx_does_too(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    conn.execute("DELETE FROM case_entries")
    for cid in ("100", "200", "300"):
        _walk_case(conn, cid, 1)
    tried = []

    def refuse(status):
        def poll(base, headers, cid, since=None, page_counter=None):
            tried.append(cid)
            raise common.HttpError(status, "u", "refused")
        return poll

    monkeypatch.setattr(lit, "poll_entries", refuse(401))
    out = lit.backfill_walk(conn, "b", {}, 50, set())
    assert tried == ["100"] and "HTTP 401" in out["stopped"] and len(out["errors"]) == 1
    conn.execute("DELETE FROM cl_backfill_attempts")
    tried.clear()
    monkeypatch.setattr(lit, "poll_entries", refuse(400))
    out = lit.backfill_walk(conn, "b", {}, 50, set())
    assert tried == ["100", "200"] and "HTTP 400" in out["stopped"]


def test_a_lone_404_skips_its_docket_and_counts_it_left(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    conn.execute("DELETE FROM case_entries")
    _walk_case(conn, "100", 1)
    _walk_case(conn, "200", 1)
    healthy = _serve_rows(conn)

    def poll(base, headers, cid, since=None, page_counter=None):
        if cid == "100":
            raise common.HttpError(404, "u", "Not found.")
        return healthy(base, headers, cid)

    monkeypatch.setattr(lit, "poll_entries", poll)
    out = lit.backfill_walk(conn, "b", {}, 50, set())
    assert (out["walked"], out["failed"], out["left"], out["stopped"]) == (1, 1, 1, None)


def test_a_4xx_walk_draws_the_budget_through_the_meter(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    conn.execute("DELETE FROM case_entries")
    for cid in ("100", "200", "300"):
        _walk_case(conn, cid, 1)
    monkeypatch.setattr(lit.time, "sleep", lambda *a, **k: None)
    asked = []

    def fake(url, params=None, headers=None, timeout=None, throttle=0.0, on_attempt=None):
        if on_attempt is not None:
            on_attempt()
        cid = (params or {}).get("docket")
        asked.append(cid)
        if cid == "100":
            raise common.HttpError(404, url, "Not found.")
        rows = conn.execute("SELECT id, description FROM case_entries WHERE case_id = ?", (cid,)).fetchall()
        return {"results": [_e(90_000 + r["id"], r["description"]) for r in rows], "next": None}

    monkeypatch.setattr(common, "http_get", fake)
    lit.SPEND.__init__()
    out = lit.backfill_walk(conn, "b", {}, 2, set())
    assert asked == ["100", "200"] and out["requests"] == 2 and "300" in out["stopped"]
    assert [r[0] for r in conn.execute("SELECT case_id FROM cl_backfill")] == ["200"]
    lit.SPEND.__init__()


def test_the_receipt_counts_attempts_not_pages(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    _legacy_row(conn, "ORDER a", url=URL.format(1))
    monkeypatch.setattr(lit.time, "sleep", lambda *a, **k: None)
    _two_page_walk(monkeypatch, [{"results": [], "next": None},
                                 {"results": [_e(1, "ORDER a", url=URL.format(1))], "next": None}])
    lit.SPEND.__init__()
    out = lit.backfill_walk(conn, "b", {}, 50, set())
    assert (out["requests"], lit.SPEND.backfill) == (2, 2)
    assert conn.execute("SELECT requests FROM cl_backfill").fetchone()[0] == 2
    lit.SPEND.__init__()


# --- main(): signals and the ledger's transaction -----------------------------------
def test_main_notes_cut_when_the_backfill_hits_the_daily_cap(tmp_path, monkeypatch):
    dbp, _ = _main_env(tmp_path, monkeypatch)

    def capped(*a, **k):
        raise common.RateBudgetExhausted(60)

    monkeypatch.setattr(lit, "poll_entries", capped)
    assert lit.main() == 0
    c = db.connect(dbp)
    rows = {r["class"]: r["evidence"] for r in c.execute("SELECT class, evidence FROM channel_runs")}
    assert rows["cut short"].startswith("id backfill stopped, daily cap hit")
    lit.SPEND.__init__()


def test_main_notes_a_stuck_docket_loud(tmp_path, monkeypatch):
    dbp, _ = _main_env(tmp_path, monkeypatch)
    c = db.connect(dbp)
    for _ in range(lit.BACKFILL_LOUD_AFTER - 1):
        lit._walk_failed(c, "100", "HTTP 500")
    c.close()

    def down(*a, **k):
        raise common.RetriesExhausted("gave up", status=500)

    monkeypatch.setattr(lit, "poll_entries", down)
    assert lit.main() == 0
    c = db.connect(dbp)
    rows = {r["class"]: r["evidence"] for r in c.execute("SELECT class, evidence FROM channel_runs")}
    assert "docket 100 has failed 3 walks" in rows["cut short"]
    lit.SPEND.__init__()


def test_main_passes_a_walks_401_to_the_credential_verdict(tmp_path, monkeypatch):
    dbp, _ = _main_env(tmp_path, monkeypatch)

    def refused(*a, **k):
        raise common.HttpError(401, "u", '{"detail":"Invalid token."}')

    monkeypatch.setattr(lit, "poll_entries", refused)
    assert lit.main() == 0
    c = db.connect(dbp)
    assert "credential failure" in {r["class"] for r in c.execute("SELECT class FROM channel_runs")}
    lit.SPEND.__init__()


def test_main_notes_a_failed_docket_as_left(tmp_path, monkeypatch):
    dbp, _ = _main_env(tmp_path, monkeypatch)

    def gone(*a, **k):
        raise common.HttpError(404, "u", "Not found.")

    monkeypatch.setattr(lit, "poll_entries", gone)
    assert lit.main() == 0
    c = db.connect(dbp)
    rows = {r["class"]: r["evidence"] for r in c.execute("SELECT class, evidence FROM channel_runs")}
    assert "1 docket(s) left, 1 failed" in rows["deferred"]
    lit.SPEND.__init__()


def test_an_interrupted_walk_commits_nothing_and_the_ledger_still_lands(tmp_path, monkeypatch):
    dbp, _ = _main_env(tmp_path, monkeypatch)
    monkeypatch.setattr(lit, "poll_entries", _walk_one([]))

    def interrupt(conn_, objs):
        raise KeyboardInterrupt

    monkeypatch.setattr(co, "_insert_objects", interrupt)
    with pytest.raises(KeyboardInterrupt):
        lit.main()
    c = db.connect(dbp)
    assert c.execute("SELECT cl_entry_id FROM case_entries").fetchone()[0] is None
    assert c.execute("SELECT COUNT(*) FROM cl_entries").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM cl_usage").fetchone()[0] == 1
    assert lit.backfill_due(c, set()) == [("100", 1)]
    lit.SPEND.__init__()


def test_a_success_between_two_failures_keeps_the_walk_going(tmp_path, monkeypatch):
    """Two systemic failures IN A ROW end the run's walk; one on each side of a success
    are two dockets' own troubles."""
    conn = _db(tmp_path)
    conn.execute("DELETE FROM case_entries")
    for cid in ("100", "200", "300", "400"):
        _walk_case(conn, cid, 1)
    healthy = _serve_rows(conn)
    tried = []

    def poll(base, headers, cid, since=None, page_counter=None):
        tried.append(cid)
        if cid in ("100", "300"):
            raise common.RetriesExhausted("gave up", status=502)
        return healthy(base, headers, cid)

    monkeypatch.setattr(lit, "poll_entries", poll)
    out = lit.backfill_walk(conn, "b", {}, 120, set())
    assert tried == ["100", "200", "300", "400"] and (out["walked"], out["failed"]) == (2, 2)
    assert out["stopped"] is None


def test_a_failed_live_docket_goes_behind_a_superseded_one_that_never_failed(tmp_path):
    conn = _db(tmp_path)
    conn.execute("DELETE FROM case_entries")
    _walk_case(conn, "100", 1)
    _walk_case(conn, "200", 1, superseded="100")
    assert [c for c, _ in lit.backfill_due(conn, set())] == ["100", "200"]
    lit._walk_failed(conn, "100", "HTTP 500")
    assert [c for c, _ in lit.backfill_due(conn, set())] == ["200", "100"]


def test_a_walk_that_succeeds_clears_its_failure_record(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    conn.execute("DELETE FROM case_entries")
    _walk_case(conn, "100", 1)
    for _ in range(lit.BACKFILL_LOUD_AFTER):
        lit._walk_failed(conn, "100", "HTTP 500")
    monkeypatch.setattr(lit, "poll_entries", _serve_rows(conn))
    out = lit.backfill_walk(conn, "b", {}, 50, set())
    assert out["walked"] == 1 and out["stuck"] == []
    assert conn.execute("SELECT COUNT(*) FROM cl_backfill_attempts").fetchone()[0] == 0
