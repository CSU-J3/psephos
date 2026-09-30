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
    # Two rows of one entry are never an edge: the rule is by entry, so rows 3 and 4 (one
    # object, re-described) reach no bucket at all.
    assert got == {"link": [[1, 2]], "one_object": [], "unattached": [[5, 6]], "person": [[7, 8]]}


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


def _env(tmp_path, monkeypatch, links):
    real = db.connect
    monkeypatch.setattr(L.config, "load_env", lambda *a, **k: None)
    monkeypatch.setattr(L.db, "connect", lambda *a, **k: real(str(tmp_path / "t.db")))
    monkeypatch.setattr(L.db, "require_remote", lambda *a, **k: None)
    monkeypatch.setattr(L, "load_links", lambda *a, **k: links)
    return lambda: real(str(tmp_path / "t.db"))


def _walked(conn, case="71499795", at="2026-10-01T06:30:00Z"):
    conn.execute("INSERT INTO cl_backfill (case_id, walked_at, requests, rows, objects, exact, adopted, "
                 "token, token_shared, unattached, never_held, stale, apart) "
                 "VALUES (?, ?, 1, 2, 2, 2, 0, 0, 0, 0, 0, 0, 0)", (case, at))
    conn.commit()


def _passing_check(conn, n=20):
    p = L.plan(conn, LINKS)
    pool = L.sample_pool(p, tw.RULE)
    return {"seed": L.DEFAULT_SEED, "pool": len(pool), "pairs": L.draw(pool, n, L.DEFAULT_SEED),
            "walks_through": conn.execute("SELECT MAX(walked_at) FROM cl_backfill").fetchone()[0],
            "result": "pass", "read_by": "reader", "on": "2026-10-01"}


def test_apply_refuses_without_a_passing_check(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    _hold(conn, 1, SHORT, 101)
    _hold(conn, 2, LONG, 102)
    _walked(conn)
    chk = _passing_check(conn)
    conn.close()
    for checked in (None, {**chk, "result": "fail"}, {**chk, "result": None}):
        get = _env(tmp_path, monkeypatch, {**LINKS, "checked": checked})
        assert L.main(["--apply"]) == 2
        assert get().execute("SELECT COUNT(*) FROM cl_entries WHERE twin_of IS NOT NULL").fetchone()[0] == 0


def test_apply_refuses_a_check_taken_before_a_later_walk(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    _hold(conn, 1, SHORT, 101)
    _hold(conn, 2, LONG, 102)
    _walked(conn, at="2026-10-01T06:30:00Z")
    chk = _passing_check(conn)
    conn.execute("INSERT INTO cases (case_id, caption, status) VALUES ('999', 'c', 'pending')")
    _walked(conn, case="999", at="2026-10-02T06:30:00Z")
    conn.close()
    _env(tmp_path, monkeypatch, {**LINKS, "checked": chk})
    assert L.main(["--apply"]) == 2


def test_apply_links_the_short_form_to_the_long_and_unlink_reverses_it(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    _hold(conn, 1, SHORT, 101)
    _hold(conn, 2, LONG, 102)
    _walked(conn)
    chk = _passing_check(conn)
    conn.close()
    get = _env(tmp_path, monkeypatch, {**LINKS, "checked": chk})
    assert L.main(["--apply"]) == 0
    c = get()
    o = c.execute("SELECT twin_of, twin_rule, twin_at FROM cl_entries WHERE cl_entry_id = 101").fetchone()
    assert (o["twin_of"], o["twin_rule"]) == (102, tw.RULE) and o["twin_at"]
    assert c.execute("SELECT twin_of FROM cl_entries WHERE cl_entry_id = 102").fetchone()[0] is None
    # The pair now presents as one entry, and the recorded seed still draws the same 20.
    assert c.execute("SELECT COUNT(*) FROM items WHERE merged_into IS NULL").fetchone()[0] == 1
    p = L.plan(c, LINKS)
    assert L.draw(L.sample_pool(p, tw.RULE), len(chk["pairs"]), chk["seed"]) == chk["pairs"]
    c.close()
    assert L.main(["--apply"]) == 0                                # idempotent: nothing more
    assert L.main(["--unlink", "101", "--apply"]) == 0
    c = get()
    assert tuple(c.execute("SELECT twin_of, twin_rule, twin_at FROM cl_entries "
                           "WHERE cl_entry_id = 101").fetchone()) == (None, None, None)
    assert c.execute("SELECT COUNT(*) FROM items WHERE merged_into IS NULL").fetchone()[0] == 2


def test_the_sample_waits_for_the_walk(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    _hold(conn, 1, SHORT, 101)
    _hold(conn, 2, LONG, 102)
    conn.close()
    _env(tmp_path, monkeypatch, LINKS)
    assert L.main(["--sample", "20", str(tmp_path / "s.json")]) == 2
    assert not (tmp_path / "s.json").exists()


def test_a_pair_that_would_make_a_chain_goes_to_a_person(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    _hold(conn, 1, SHORT, 101)
    _hold(conn, 2, LONG, 102)
    conn.execute("UPDATE cl_entries SET twin_of = 101, twin_rule = 'asserted: x' WHERE cl_entry_id = 102")
    conn.execute("INSERT INTO cl_entries (cl_entry_id, case_id, held) VALUES (500, '71499795', 1)")
    conn.commit()
    p = L.plan(conn, LINKS)
    # 101 is already 102's entry; linking 101 as 102's twin would make a cycle.
    assert [x["rows"] for x in p["would_chain"]] == [[1, 2]] and p["link"] == []


def test_a_ruled_pair_survives_a_revision_row_on_its_long_form(tmp_path):
    """Ruling 2's own case: the long form is re-described FILED IN ERROR. R1 keeps the old
    row, so the long object now holds two rows; the pair must stay one pair."""
    conn = _db(tmp_path)
    _hold(conn, 1, SHORT, 101)
    _hold(conn, 2, LONG, 102)
    _hold(conn, 3, "***FILED IN ERROR*** " + LONG, 102, fetched="2026-07-20T19:31:40Z")
    p = L.plan(conn, LINKS)
    assert len(p["link"]) == 1 and p["link"][0]["objects"] == [101, 102]


def test_refused_and_asserted_match_by_entry_not_by_row(tmp_path):
    conn = _db(tmp_path)
    _hold(conn, 1, SHORT, 101)
    _hold(conn, 2, LONG, 102)
    _hold(conn, 3, "***FILED IN ERROR*** " + LONG, 102, fetched="2026-07-20T19:31:40Z")
    p = L.plan(conn, {**LINKS, "refused": [{"rows": [1, 3]}]})    # a row pair of the same entries
    assert len(p["refused"]) == 1 and p["link"] == []


def test_an_asserted_pair_that_matches_nothing_refuses_apply(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    _hold(conn, 1, SHORT, 101)
    _hold(conn, 2, LONG, 102)
    _walked(conn)
    chk = _passing_check(conn)
    conn.close()
    _env(tmp_path, monkeypatch, {**LINKS, "checked": chk,
                                 "asserted": [{"rows": [77, 78], "ruled": "Corey, 2026-10-01"}]})
    assert L.main(["--apply"]) == 2


def test_unlink_apply_runs_against_turso_only(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    _hold(conn, 1, SHORT, 101)
    _hold(conn, 2, LONG, 102)
    conn.execute("UPDATE cl_entries SET twin_of = 102, twin_rule = 'x' WHERE cl_entry_id = 101")
    conn.commit()
    conn.close()
    real_guard = db.require_remote
    get = _env(tmp_path, monkeypatch, LINKS)
    monkeypatch.setattr(L.db, "require_remote", real_guard)            # the real guard
    with pytest.raises(RuntimeError):
        L.main(["--unlink", "101", "--apply"])
    assert get().execute("SELECT twin_of FROM cl_entries WHERE cl_entry_id = 101").fetchone()[0] == 102


def test_the_committed_config_refuses_the_dscc_pair_and_is_unchecked():
    links = L.load_links()
    assert links["rule"] == tw.RULE
    assert [sorted(p["rows"]) for p in links["refused"]] == [[92515, 92572]]
    assert links["refused"][0]["ruled"].startswith("Corey, 2026-09-30")


def test_a_pair_is_unique_by_entry_when_the_long_forms_revision_also_pairs(tmp_path):
    """The long form re-described with a clerk's note, a text the short form still pairs
    with: counted by row, the short form has two partners and the pair drops out."""
    conn = _db(tmp_path)
    _hold(conn, 1, SHORT, 101)
    _hold(conn, 2, LONG, 102)
    _hold(conn, 3, LONG + " Modified on 9/30/2026 (nms)", 102, fetched="2026-07-20T19:31:40Z")
    p = L.plan(conn, LINKS)
    assert len(p["link"]) == 1 and p["link"][0]["objects"] == [101, 102]
