"""R1 step c: the tier-2 rule (collectors/cl_twins.py) and the link script
(scripts/link_entry_twins.py). Corey's ruling 3, 2026-09-30: the same-run rule for the
256 pairs, the rest to a person, a reader's check of 20 before the rule is relied on,
every link psephos's recorded and reversible assertion, and the DSCC pair never linked.

The port was checked against the D0's own output on the 2026-09-30 00:38Z dump: 279 edges,
the same set as dup_d0/work2_ab/ident.json, 147 ambiguous short rows, 173 runs, and 256
same-run / 12 cross-run / 11 undetermined (docs/status.md). The dump is not in the repo;
these tests pin the rule's shapes."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import common  # noqa: E402
import db  # noqa: E402
from collectors import cl_twins as tw  # noqa: E402
from scripts import link_entry_twins as L  # noqa: E402

DAY = "2026-07-20T00:00:00"
URL = "https://www.courtlistener.com/docket/71499795/{}/lwv/"
SHORT = "Order on Motion to Enforce Judgment AND Set/Reset Deadlines"
LONG = ("MINUTE ORDER: The Court has reviewed the Parties' briefing on the 128 Motion to "
        "Enforce Judgment and sets deadlines as follows")


def _row(i, desc, day=DAY, url=None, case="71499795"):
    return {"id": i, "case_id": case, "entry_at": day, "description": desc, "document_url": url}


def test_short_to_long_on_one_day_is_an_edge():
    kept, amb = tw.strict_b([_row(1, SHORT), _row(2, LONG)])
    assert kept == [(1, 2, "short_long")] and amb == []


def test_a_short_form_with_two_long_twins_is_ambiguous_not_linked():
    kept, amb = tw.strict_b([_row(1, SHORT), _row(2, LONG), _row(3, LONG + " again, entered twice")])
    assert kept == [] and amb == [1]


def test_a_tokened_pair_is_tier_one_not_tier_two():
    kept, _ = tw.strict_b([_row(1, SHORT, url=URL.format(5)), _row(2, LONG, url=URL.format(5))])
    assert kept == []


def test_an_order_and_a_non_order_never_pair():
    kept, _ = tw.strict_b([_row(1, "Order on Motion to Enforce"),
                           _row(2, "NOTICE of supplemental authority on the motion to enforce "
                                   "judgment, filed by the plaintiffs")])
    assert kept == []


def test_the_run_clock_brackets_rows_without_items():
    clock = tw.RunClock(["2026-07-20T10:00:00Z", "2026-07-20T10:05:00Z", "2026-07-20T16:00:00Z"],
                        {10: "2026-07-20T10:00:00Z", 30: "2026-07-20T16:00:00Z"})
    assert clock.relation(10, 10) == "same-run"
    assert clock.relation(10, 30) == "cross-run"
    assert clock.relation(10, 20) == "undetermined"      # 20 lies between the two runs


# --------------------------------------------------------------------------- #
# The link script
# --------------------------------------------------------------------------- #
def _db(tmp_path):
    dbp = str(tmp_path / "t.db")
    db.init_db(dbp)
    conn = db.connect(dbp)
    conn.execute("INSERT INTO sources (id, name, channel, kind, admiralty_source, admiralty_info)"
                 " VALUES ('courtlistener', 'CL', 'litigation', 'api', 'A', '1')")
    conn.execute("INSERT INTO cases (case_id, caption, status) VALUES ('71499795', 'c', 'pending')")
    conn.commit()
    return conn


def _hold(conn, rid, desc, cl_id, fetched="2026-07-20T19:31:18Z", day=DAY):
    conn.execute("INSERT INTO case_entries (id, case_id, entry_at, description, cl_entry_id) "
                 "VALUES (?, '71499795', ?, ?, ?)", (rid, day, desc, cl_id))
    conn.execute("INSERT INTO items (channel, source_id, source_url, title, summary, occurred_at, "
                 "fetched_at, admiralty_source, admiralty_info, case_id, content_hash, cl_entry_id) "
                 "VALUES ('litigation', 'courtlistener', 'u', ?, ?, ?, ?, 'A', '1', '71499795', ?, ?)",
                 (f"c: {desc}", desc, day, fetched, common.content_hash("71499795", day, desc), cl_id))
    if cl_id is not None:
        conn.execute("INSERT OR IGNORE INTO cl_entries (cl_entry_id, case_id, entry_at, description, "
                     "current_row, held) VALUES (?, '71499795', ?, ?, ?, 1)", (cl_id, day, desc, rid))
    conn.commit()


LINKS = {"rule": tw.RULE, "checked": None, "refused": [], "asserted": []}


def test_the_plan_classifies_every_pair(tmp_path):
    conn = _db(tmp_path)
    _hold(conn, 1, SHORT, 101)                                   # two objects, same run
    _hold(conn, 2, LONG, 102)
    _hold(conn, 3, "Scheduling Order", 103, day="2026-07-21T00:00:00")          # one object
    _hold(conn, 4, "MINUTE ORDER: scheduling order setting the hearing and the briefing "
                   "schedule for the pending motions", 103, day="2026-07-21T00:00:00")
    _hold(conn, 5, "Order on Motion for Leave to File Amicus", None, day="2026-07-22T00:00:00")
    _hold(conn, 6, "MINUTE ORDER granting the 24 Motion for Leave to File Amicus Brief "
                   "filed by the amici, whose brief is deemed filed", 106, day="2026-07-22T00:00:00")
    _hold(conn, 7, SHORT, 107, day="2026-07-23T00:00:00", fetched="2026-07-23T10:00:00Z")
    _hold(conn, 8, LONG, 108, day="2026-07-23T00:00:00", fetched="2026-07-23T18:00:00Z")
    p = L.plan(conn, LINKS)
    got = {k: [x["rows"] for x in p[k]] for k in ("link", "one_object", "unattached", "person")}
    assert got == {"link": [[1, 2]], "one_object": [[3, 4]], "unattached": [[5, 6]], "person": [[7, 8]]}


def test_a_refused_pair_is_never_linked_and_an_asserted_one_is(tmp_path):
    conn = _db(tmp_path)
    _hold(conn, 1, SHORT, 101)
    _hold(conn, 2, LONG, 102)
    _hold(conn, 7, SHORT, 107, day="2026-07-23T00:00:00", fetched="2026-07-23T10:00:00Z")
    _hold(conn, 8, LONG, 108, day="2026-07-23T00:00:00", fetched="2026-07-23T18:00:00Z")
    links = {**LINKS, "refused": [{"rows": [2, 1]}],
             "asserted": [{"rows": [7, 8], "ruled": "Corey, 2026-10-01"}]}
    p = L.plan(conn, links)
    assert [x["rows"] for x in p["refused"]] == [[1, 2]]
    assert [(x["rows"], x["by"]) for x in p["link"]] == [([7, 8], "asserted: Corey, 2026-10-01")]


def test_apply_refuses_without_the_readers_check(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    _hold(conn, 1, SHORT, 101)
    _hold(conn, 2, LONG, 102)
    conn.close()
    monkeypatch.setattr(L.config, "load_env", lambda *a, **k: None)
    real = db.connect
    monkeypatch.setattr(L.db, "connect", lambda *a, **k: real(str(tmp_path / "t.db")))
    monkeypatch.setattr(L, "load_links", lambda *a, **k: LINKS)
    assert L.main(["--apply"]) == 2
    c = real(str(tmp_path / "t.db"))
    assert c.execute("SELECT COUNT(*) FROM cl_entries WHERE twin_of IS NOT NULL").fetchone()[0] == 0


def test_apply_links_the_short_form_to_the_long_and_unlink_reverses_it(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    _hold(conn, 1, SHORT, 101)
    _hold(conn, 2, LONG, 102)
    conn.close()
    monkeypatch.setattr(L.config, "load_env", lambda *a, **k: None)
    real = db.connect
    monkeypatch.setattr(L.db, "connect", lambda *a, **k: real(str(tmp_path / "t.db")))
    monkeypatch.setattr(L.db, "require_remote", lambda *a, **k: None)
    monkeypatch.setattr(L, "load_links", lambda *a, **k: {**LINKS, "checked": {"on": "2026-10-01"}})
    assert L.main(["--apply"]) == 0
    c = real(str(tmp_path / "t.db"))
    o = c.execute("SELECT twin_of, twin_rule, twin_at FROM cl_entries WHERE cl_entry_id = 101").fetchone()
    assert (o["twin_of"], o["twin_rule"]) == (102, tw.RULE) and o["twin_at"]
    assert c.execute("SELECT twin_of FROM cl_entries WHERE cl_entry_id = 102").fetchone()[0] is None
    c.close()
    assert L.main(["--apply"]) == 0                                # idempotent: nothing more
    assert L.main(["--unlink", "101", "--apply"]) == 0
    c = real(str(tmp_path / "t.db"))
    assert tuple(c.execute("SELECT twin_of, twin_rule, twin_at FROM cl_entries "
                           "WHERE cl_entry_id = 101").fetchone()) == (None, None, None)


def test_the_committed_config_refuses_the_dscc_pair_and_is_unchecked():
    links = L.load_links()
    assert links["rule"] == tw.RULE
    assert [sorted(p["rows"]) for p in links["refused"]] == [[92515, 92572]]
    assert links["refused"][0]["ruled"].startswith("Corey, 2026-09-30")
