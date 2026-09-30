"""tools/merge_notes.py: every public figure the R1 switch moves, rows against entries,
read from one state of the record (Corey's rulings 5 and d, 2026-09-30)."""
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
    w = f["wire"]["litigation"]
    # The first poll sits exactly on the +24h edge (the anchor less a day), which counts.
    assert (w["total"], w["day"], w["week"], w["tracker_notes"]) == ([2, 1], [2, 1], [2, 1], 0)
    assert f["map"] == {"entries": [2, 1], "dockets_changed": 1, "apart": 0}
    assert f["cases"]["72026664"] == {"entries": [2, 1], "ledger": [2, 1], "timeline": [2, 1],
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
    f = M.figures(conn)
    assert f["map"]["dockets_changed"] == 0 and f["wire"]["litigation"]["total"] == [2, 1]
    assert f["wire"]["litigation"]["tracker_notes"] == 1


def test_an_entry_held_apart_is_recorded_as_a_rise_not_hidden(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    _poll(conn, monkeypatch, "2026-08-25T00:00:00+00:00",
          [{"id": 1, "date_filed": "2026-08-24", "description": "CORRECTING ENTRY", "recap_documents": []},
           {"id": 2, "date_filed": "2026-08-24", "description": "CORRECTING ENTRY", "recap_documents": []}])
    f = M.figures(conn)
    assert f["cases"]["72026664"]["entries"] == [1, 2] and f["cases"]["72026664"]["apart"] == 1
    assert f["map"]["apart"] == 1


def test_the_older_than_7_days_clause_is_recorded_both_ways(tmp_path, monkeypatch):
    """An old entry the court re-described inside the last 24 hours: before the switch the
    re-description counts in the clause; after, it is folded and does not."""
    conn = _db(tmp_path)
    _poll(conn, monkeypatch, "2026-09-01T00:00:00+00:00",
          [{"id": 5, "date_filed": "2026-06-01", "description": "ORDER old", "recap_documents": []}])
    _poll(conn, monkeypatch, "2026-09-30T00:00:00+00:00",
          [{"id": 5, "date_filed": "2026-06-01", "description": "ORDER old, re-described", "recap_documents": []}])
    assert M.figures(conn)["wire"]["litigation"]["history"] == [1, 0]


def test_a_clerks_strike_moves_the_rejected_outcome_and_it_is_recorded(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    e = {"id": 7, "date_filed": "2026-08-20", "recap_documents": []}
    _poll(conn, monkeypatch, "2026-08-21T00:00:00+00:00",
          [{**e, "description": "ORDER granting Motions to Dismiss. This case is dismissed."}])
    _poll(conn, monkeypatch, "2026-08-22T00:00:00+00:00",
          [{**e, "description": "***FILED IN ERROR*** Document removed from the docket."}])
    f = M.figures(conn)
    assert f["rejected"] == {"count": [1, 0], "states": {"Nevada": ["2026-08-20", None]}}


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
