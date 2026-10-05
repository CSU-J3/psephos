"""tools/merge_notes.py: every public figure the R1 switch moves, read from one state of the
record (Corey's rulings 5 and d, 2026-09-30) as dated moves: the merge of duplicate rows
(rows -> tier 1), then any tier-2 links (tier 1 -> objects), each with its own note (Corey,
2026-10-02)."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import common  # noqa: E402
import db  # noqa: E402
from collectors import cl_fold  # noqa: E402
from collectors import litigation as lit  # noqa: E402
from tools import merge_notes as M  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _db(tmp_path, case="72026664", state="Nevada", terminated="2026-08-20"):
    dbp = str(tmp_path / "m.db")
    db.init_db(dbp)
    conn = db.connect(dbp)
    for sid, a, i in (("courtlistener", "A", "1"), ("seed-cases", "B", "2")):
        conn.execute("INSERT INTO sources (id, name, channel, kind, admiralty_source, admiralty_info)"
                     " VALUES (?, ?, 'litigation', 'api', ?, ?)", (sid, sid, a, i))
    conn.execute("INSERT INTO cases (case_id, caption, status, state, date_terminated) "
                 "VALUES (?, 'c', 'terminated', ?, ?)", (case, state, terminated))
    conn.commit()
    return conn


def _poll(conn, monkeypatch, at, entries, case="72026664", types=("order",)):
    monkeypatch.setattr(common, "now_iso", lambda: at)
    lit.write_entries(conn, case, "c", None, entries, list(types), [])
    conn.commit()
    cl_fold.refold_quietly(conn, case)


def test_the_figures_pair_rows_with_entries(tmp_path, monkeypatch):
    """Nevada: one entry the court re-dated Aug 24 -> Aug 20. Two rows, one entry."""
    conn = _db(tmp_path)
    e = {"id": 9, "description": "USCA ORDER time schedule", "recap_documents": []}
    _poll(conn, monkeypatch, "2026-08-25T00:00:00+00:00", [{**e, "date_filed": "2026-08-24"}])
    _poll(conn, monkeypatch, "2026-08-26T00:00:00+00:00", [{**e, "date_filed": "2026-08-20"}])
    conn.execute("UPDATE cases SET latest_entry_at = '2026-08-24T00:00:00'")   # as stored before the repair
    conn.commit()
    f = M.figures(conn, on="2026-10-02")
    assert f["on"] == "2026-10-02" and f["clock"] == "2026-08-26T00:00:00+00:00"
    assert [m["kind"] for m in f["moves"]] == ["merge"] and f["unfolded"] == []   # no link
    m = f["moves"][0]
    w = m["wire"]["litigation"]
    # The first poll sits exactly on the +24h edge. The page compares the stamp as a string
    # with the edge as lib/activity.windowStarts writes it, in milliseconds
    # ("2026-08-25T00:00:00.000+00:00"), and a stamp with no fraction sorts before it: so on
    # the page it is outside the 24 hours, and so here. The entry presents by that first
    # poll, its earliest fetch, so the merge takes the 24-hour count from 1 to 0.
    assert (w["total"], w["day"], w["week"], w["tracker_notes"]) == ([2, 1], [1, 0], [2, 1], 0)
    assert m["map"] == {"entries": [2, 1], "dockets_changed": 1, "apart": 0}
    assert m["cases"]["72026664"] == {"entries": [2, 1], "ledger": [2, 1], "timeline": [2, 1],
                                      "latest_entry_at": ["2026-08-24T00:00:00", "2026-08-20T00:00:00"]}


def test_tracker_note_repeats_are_counted_as_their_own_share(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    seed = {"caption": "c", "category": "voter-data", "notes": "first"}
    monkeypatch.setattr(common, "now_iso", lambda: "2026-09-25T00:00:00+00:00")
    lit.write_b2_item(conn, "72026664", seed, None, None)
    monkeypatch.setattr(common, "now_iso", lambda: "2026-09-29T00:00:00+00:00")
    lit.write_b2_item(conn, "72026664", {**seed, "notes": "second"}, None, None)
    conn.commit()
    cl_fold.refold_quietly(conn, "72026664")
    m = M.figures(conn)["moves"][0]
    assert m["map"]["dockets_changed"] == 0 and m["wire"]["litigation"]["total"] == [2, 1]
    assert m["wire"]["litigation"]["tracker_notes"] == 1


def test_an_entry_held_apart_is_recorded_as_a_rise_not_hidden(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    _poll(conn, monkeypatch, "2026-08-25T00:00:00+00:00",
          [{"id": 1, "date_filed": "2026-08-24", "description": "CORRECTING ENTRY", "recap_documents": []},
           {"id": 2, "date_filed": "2026-08-24", "description": "CORRECTING ENTRY", "recap_documents": []}])
    m = M.figures(conn)["moves"][0]
    assert m["cases"]["72026664"]["entries"] == [1, 2] and m["cases"]["72026664"]["apart"] == 1
    assert m["map"]["apart"] == 1


def test_the_older_than_7_days_clause_is_recorded_both_ways(tmp_path, monkeypatch):
    """An old entry the court re-described inside the last 24 hours: before the switch the
    re-description counts in the clause; after, it is folded and does not."""
    conn = _db(tmp_path)
    _poll(conn, monkeypatch, "2026-09-01T00:00:00+00:00",
          [{"id": 5, "date_filed": "2026-06-01", "description": "ORDER old", "recap_documents": []}])
    _poll(conn, monkeypatch, "2026-09-30T00:00:00+00:00",
          [{"id": 5, "date_filed": "2026-06-01", "description": "ORDER old, re-described", "recap_documents": []}])
    assert M.figures(conn)["moves"][0]["wire"]["litigation"]["history"] == [1, 0]


def test_a_clerks_strike_moves_the_rejected_outcome_and_it_is_recorded(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    e = {"id": 7, "date_filed": "2026-08-20", "recap_documents": []}
    _poll(conn, monkeypatch, "2026-08-21T00:00:00+00:00",
          [{**e, "description": "ORDER granting Motions to Dismiss. This case is dismissed."}])
    _poll(conn, monkeypatch, "2026-08-22T00:00:00+00:00",
          [{**e, "description": "***FILED IN ERROR*** Document removed from the docket."}])
    assert M.figures(conn)["moves"][0]["rejected"] == {"count": [1, 0], "states": {"Nevada": ["2026-08-20", None]}}


def test_the_ported_outcome_patterns_are_the_webs_own():
    """tools/merge_notes.py reads the rejected-states outcome both ways with a port of
    web/lib/outcomes.ts. Its patterns must be the web's, character for character."""
    src = (ROOT / "web" / "lib" / "outcomes.ts").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("//"))
    lit_re = r"/((?:[^/\n\\]|\\.)+)/i"
    filing = re.search(r"const FILING =\s*" + lit_re, code).group(1)
    juris = re.search(r"const JURISDICTIONAL =\s*" + lit_re, code).group(1)
    block = code[code.index("const REJECT"):code.index("];", code.index("const REJECT"))]
    reject = re.findall(r"\[\s*\"[\w-]+\",\s*" + lit_re, block)
    assert M.FILING.pattern == filing
    assert M.JURISDICTIONAL.pattern == juris
    assert [p.pattern for p in M.REJECT] == reject and len(reject) == 6


def test_the_snapshot_is_refused_while_the_walk_or_the_rule_links_are_unfinished(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    conn.execute("INSERT INTO case_entries (case_id, entry_at, description) "
                 "VALUES ('72026664', '2026-08-20T00:00:00', 'legacy row, never walked')")
    conn.commit()
    assert any("not yet walked" in w for w in M.incomplete(conn))


def test_a_tier2_link_is_its_own_dated_move_after_the_merge(tmp_path, monkeypatch):
    """Two CourtListener objects for one minute entry, linked: tier 1 counts them apart, so
    the merge move does not touch them, and the link move takes them from two to one."""
    conn = _db(tmp_path)
    _poll(conn, monkeypatch, "2026-09-25T12:00:00.500000+00:00",
          [{"id": 1, "date_filed": "2026-09-25", "description": "Order on Motion to Stay", "recap_documents": []},
           {"id": 2, "date_filed": "2026-09-25", "recap_documents": [],
            "description": "MINUTE ORDER granting the 40 Motion to Stay pending appeal. Signed by Judge X."}])
    conn.execute("UPDATE cl_entries SET twin_of = 2, twin_rule = 'r' WHERE cl_entry_id = 1")
    conn.commit()
    cl_fold.refold_quietly(conn, "72026664")
    f = M.figures(conn, on="2026-10-03")
    assert f["unfolded"] == [] and [m["kind"] for m in f["moves"]] == ["merge", "link"]
    merge, link = f["moves"]
    assert merge["cases"] == {} and merge["map"]["dockets_changed"] == 0
    assert merge["wire"]["litigation"]["total"] == [2, 2]
    assert (link["on"], link["links"], link["why"]) == ("2026-10-03", 1, M.WHY_LINK)
    assert link["wire"]["litigation"]["total"] == [2, 1]
    assert link["map"] == {"entries": [2, 1], "dockets_changed": 1}
    assert link["cases"]["72026664"] == {"entries": [2, 1], "ledger": [2, 1], "timeline": [2, 1]}


def test_a_case_the_fold_has_not_reached_refuses_the_snapshot(tmp_path, monkeypatch):
    """Its record_items still lists every row's item, so a note written now would state an
    'after' the page does not show."""
    conn = _db(tmp_path)
    e = {"id": 9, "date_filed": "2026-08-24", "recap_documents": []}
    monkeypatch.setattr(common, "now_iso", lambda: "2026-08-25T00:00:00.5+00:00")
    lit.write_entries(conn, "72026664", "c", None, [{**e, "description": "ORDER one"}], ["order"], [])
    lit.write_entries(conn, "72026664", "c", None, [{**e, "description": "ORDER one, re-described"}], ["order"], [])
    conn.commit()                                       # written, and never refolded
    assert M.figures(conn)["unfolded"] == ["72026664"]


# --------------------------------------------------------------------------- #
# A later link batch appends its own move (Corey's rulings, 2026-10-04, R1 tier 2 closes
# conservatively, ruling 4)
# --------------------------------------------------------------------------- #
import json  # noqa: E402

import pytest  # noqa: E402

from scripts import link_entry_twins as L  # noqa: E402

STAY = [{"id": 1, "date_filed": "2026-09-25", "description": "Order on Motion to Stay", "recap_documents": []},
        {"id": 2, "date_filed": "2026-09-25", "recap_documents": [],
         "description": "MINUTE ORDER granting the 40 Motion to Stay pending appeal. Signed by Judge X."}]
RECORDED = "where the move recorded 1 after"


def _two_objects(tmp_path, monkeypatch, entries=STAY, at="2026-09-25T12:00:00.500000+00:00"):
    """Two CourtListener objects for one minute entry, held and folded, not yet linked."""
    conn = _db(tmp_path)
    _poll(conn, monkeypatch, at, entries)
    return conn


def _link(conn, twin, root, fold=True):
    conn.execute("UPDATE cl_entries SET twin_of = ?, twin_rule = 'r' WHERE cl_entry_id = ?", (root, twin))
    conn.commit()
    if fold:
        cl_fold.refold_quietly(conn, "72026664")


def test_a_later_link_batch_is_its_own_move_read_from_one_state_before_it_links(tmp_path, monkeypatch):
    conn = _two_objects(tmp_path, monkeypatch)
    move, unfolded = M.link_move(conn, [{"twin": 1, "entry": 2}], on="2026-10-04")
    assert unfolded == []
    assert (move["kind"], move["on"], move["links"], move["why"]) == ("link", "2026-10-04", 1, M.WHY_LINK)
    assert move["wire"]["litigation"] == {"total": [2, 1], "day": [2, 1], "week": [2, 1], "history": [0, 0]}
    assert move["map"] == {"entries": [2, 1], "dockets_changed": 1}
    assert move["cases"] == {"72026664": {"entries": [2, 1], "ledger": [2, 1], "timeline": [2, 1]}}
    # Before the link the record reads the move's 'before', figure by figure ...
    assert M.check_move(conn, move) == ([
        f"72026664 entries: 2, {RECORDED}", f"72026664 ledger: 2, {RECORDED}",
        f"72026664 timeline: 2, {RECORDED}", f"map entries: 2, {RECORDED}",
        f"Wire litigation total: 2, {RECORDED}", f"Wire litigation day: 2, {RECORDED}",
        f"Wire litigation week: 2, {RECORDED}"], True)
    # ... linked but not yet folded, the views lag the objects ...
    _link(conn, 1, 2, fold=False)
    assert M.check_move(conn, move)[0] == ["72026664: its fold does not match the views"]
    # ... and linked and folded, its 'after'.
    cl_fold.refold_quietly(conn, "72026664")
    assert M.check_move(conn, move) == ([], True)


def test_a_link_move_is_dated_by_the_records_clock(tmp_path, monkeypatch):
    conn = _two_objects(tmp_path, monkeypatch)
    assert M.link_move(conn, [{"twin": 1, "entry": 2}])[0]["on"] == "2026-09-25"


def test_a_link_that_folds_a_rejection_into_its_root_moves_the_outcome(tmp_path, monkeypatch):
    """Read as made, the twin leaves the entries the outcome reads. Here the twin's text was
    the rejection and its root's is not, so Nevada's outcome moves with the link."""
    conn = _two_objects(tmp_path, monkeypatch, at="2026-08-21T00:00:00+00:00", entries=[
        {"id": 7, "date_filed": "2026-08-20", "recap_documents": [],
         "description": "ORDER granting Motions to Dismiss. This case is dismissed."},
        {"id": 8, "date_filed": "2026-08-20", "recap_documents": [],
         "description": "MINUTE ORDER setting a status conference on the remaining motions for the parties."}])
    move, _ = M.link_move(conn, [{"twin": 7, "entry": 8}], on="2026-10-04")
    assert move["rejected"] == {"count": [1, 0], "states": {"Nevada": ["2026-08-20", None]}}
    assert f"rejected states: 1, {RECORDED.replace('1 after', '0 after')}" in M.check_move(conn, move)[0]
    _link(conn, 7, 8)
    assert M.check_move(conn, move) == ([], True)


def test_after_a_later_run_the_check_leaves_the_wire_out(tmp_path, monkeypatch):
    conn = _two_objects(tmp_path, monkeypatch)
    move, _ = M.link_move(conn, [{"twin": 1, "entry": 2}], on="2026-10-04")
    _link(conn, 1, 2)
    conn.execute("INSERT INTO items (channel, source_id, source_url, title, occurred_at, fetched_at, "
                 "admiralty_source, admiralty_info, content_hash) VALUES ('news', 'courtlistener', 'u', "
                 "'t', '2026-09-26', '2026-09-26T00:00:00+00:00', 'A', '1', 'later')")
    conn.commit()
    assert M.check_move(conn, move) == ([], False)


def _plan(monkeypatch, due=(), **change):
    p = {"link": [{"twin": 1, "entry": 2}], "unread": [], "ruled_refused": [], "ruled_missing": [],
         "person": [], **change}
    monkeypatch.setattr(L, "load_links", lambda *a, **k: {})
    monkeypatch.setattr(L, "plan", lambda *a, **k: p)
    monkeypatch.setattr(lit, "backfill_due", lambda *a, **k: list(due))


def test_appending_keeps_every_recorded_move_and_adds_the_batch_last(tmp_path, monkeypatch):
    conn = _two_objects(tmp_path, monkeypatch)
    f = M.figures(conn, on="2026-10-02")
    del f["unfolded"]
    path = tmp_path / "entry-merge.json"
    path.write_text(json.dumps(f, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _plan(monkeypatch)
    assert M.append_link_move(conn, path, "2026-10-04") == 0
    after = json.loads(path.read_text(encoding="utf-8"))
    assert {k: v for k, v in after.items() if k != "moves"} == {k: v for k, v in f.items() if k != "moves"}
    assert after["moves"][:-1] == f["moves"] and [m["kind"] for m in f["moves"]] == ["merge"]
    assert (after["moves"][-1]["kind"], after["moves"][-1]["on"], after["moves"][-1]["links"]) == ("link", "2026-10-04", 1)
    # The record has not moved, so it still reads the 'before'; linked, the check passes.
    assert M.check_last_move(conn, path) == 2
    _link(conn, 1, 2)
    assert M.check_last_move(conn, path) == 0


@pytest.mark.parametrize("due, change", [
    ((), {"link": []}),
    ((), {"unread": [{"rows": [1, 2]}]}),
    ((), {"ruled_refused": [{"why": "x"}]}),
    ((), {"ruled_missing": [{"rows": [1, 2]}]}),
    (("72026664",), {}),
])
def test_the_append_refuses_a_batch_apply_would_not_make(tmp_path, monkeypatch, capsys, due, change):
    conn = _two_objects(tmp_path, monkeypatch)
    path = tmp_path / "entry-merge.json"
    text = '{\n "clock": null,\n "moves": [],\n "on": null\n}\n'
    path.write_text(text, encoding="utf-8", newline="\n")
    _plan(monkeypatch, due, **change)
    assert M.append_link_move(conn, path) == 2 and "REFUSED" in capsys.readouterr().out
    assert path.read_text(encoding="utf-8") == text


def test_the_append_refuses_while_a_case_is_unfolded(tmp_path, monkeypatch, capsys):
    conn = _two_objects(tmp_path, monkeypatch)
    _link(conn, 1, 2, fold=False)              # a link the fold has not reached
    path = tmp_path / "entry-merge.json"
    text = '{\n "clock": null,\n "moves": [],\n "on": null\n}\n'
    path.write_text(text, encoding="utf-8", newline="\n")
    _plan(monkeypatch)
    assert M.append_link_move(conn, path) == 2
    assert "1 case(s) whose fold does not match the views (72026664)" in capsys.readouterr().out
    assert path.read_text(encoding="utf-8") == text
