"""R1 step c: the tier-2 rule (collectors/cl_twins.py) and the link script
(scripts/link_entry_twins.py). Corey's ruling 3, 2026-09-30: the same-run rule for the
256 pairs, the rest to a person, a reader's check of 20 before the rule is relied on,
every link psephos's recorded and reversible assertion, and the DSCC pair never linked.

The port was checked against the D0's own output on the 2026-09-30 00:38Z dump: 279 edges,
the same set as dup_d0/work2_ab/ident.json, 147 ambiguous short rows, 173 runs, and 256
same-run / 12 cross-run / 11 undetermined (docs/status.md). The dump is not in the repo;
these tests pin the rule's shapes."""
from __future__ import annotations

import json
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
FIRST = ("COMPLAINT for declaratory and injunctive relief against all defendants, filed by "
         "the plaintiffs")


def _db(tmp_path):
    """The docket's first load is row 0, a run before the pairs below: so a same-run pair
    in those tests is a later poll's, the kind the rule links (ruling 1a, 2026-10-02)."""
    dbp = str(tmp_path / "t.db")
    db.init_db(dbp)
    conn = db.connect(dbp)
    conn.execute("INSERT INTO sources (id, name, channel, kind, admiralty_source, admiralty_info)"
                 " VALUES ('courtlistener', 'CL', 'litigation', 'api', 'A', '1')")
    conn.execute("INSERT INTO cases (case_id, caption, status) VALUES ('71499795', 'c', 'pending')")
    conn.commit()
    _hold(conn, 0, FIRST, 100, fetched="2026-07-19T10:00:00Z", day="2026-07-01T00:00:00")
    return conn


def _hold(conn, rid, desc, cl_id, fetched="2026-07-20T19:31:18Z", day=DAY, case="71499795"):
    conn.execute("INSERT INTO case_entries (id, case_id, entry_at, description, cl_entry_id) "
                 "VALUES (?, ?, ?, ?, ?)", (rid, case, day, desc, cl_id))
    conn.execute("INSERT INTO items (channel, source_id, source_url, title, summary, occurred_at, "
                 "fetched_at, admiralty_source, admiralty_info, case_id, content_hash, cl_entry_id) "
                 "VALUES ('litigation', 'courtlistener', 'u', ?, ?, ?, ?, 'A', '1', ?, ?, ?)",
                 (f"c: {desc}", desc, day, fetched, case, common.content_hash(case, day, desc), cl_id))
    if cl_id is not None:
        conn.execute("INSERT OR IGNORE INTO cl_entries (cl_entry_id, case_id, entry_at, description, "
                     "current_row, held) VALUES (?, ?, ?, ?, ?, 1)", (cl_id, case, day, desc, rid))
    conn.commit()


def _docket(conn, case="72000000"):
    conn.execute("INSERT INTO cases (case_id, caption, status) VALUES (?, 'c', 'pending')", (case,))
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
    presenting = "SELECT COUNT(*) FROM items WHERE merged_into IS NULL AND occurred_at = ?"
    assert c.execute(presenting, (DAY,)).fetchone()[0] == 1
    p = L.plan(c, LINKS)
    assert L.draw(L.sample_pool(p, tw.RULE), len(chk["pairs"]), chk["seed"]) == chk["pairs"]
    c.close()
    assert L.main(["--apply"]) == 0                                # idempotent: nothing more
    assert L.main(["--unlink", "101", "--apply"]) == 0
    c = get()
    assert tuple(c.execute("SELECT twin_of, twin_rule, twin_at FROM cl_entries "
                           "WHERE cl_entry_id = 101").fetchone()) == (None, None, None)
    assert c.execute(presenting, (DAY,)).fetchone()[0] == 2


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


def test_the_committed_config_refuses_the_dscc_pair_and_pair_22():
    links = L.load_links()
    assert links["rule"] == tw.RULE
    assert [sorted(p["rows"]) for p in links["refused"]] == [[92515, 92572], [91090, 91356]]
    assert links["refused"][0]["ruled"].startswith("Corey, 2026-09-30")
    assert links["refused"][1]["ruled"].startswith("Corey, 2026-10-03")   # its text changed


def test_a_pair_is_unique_by_entry_when_the_long_forms_revision_also_pairs(tmp_path):
    """The long form re-described with a clerk's note, a text the short form still pairs
    with: counted by row, the short form has two partners and the pair drops out."""
    conn = _db(tmp_path)
    _hold(conn, 1, SHORT, 101)
    _hold(conn, 2, LONG, 102)
    _hold(conn, 3, LONG + " Modified on 9/30/2026 (nms)", 102, fetched="2026-07-20T19:31:40Z")
    p = L.plan(conn, LINKS)
    assert len(p["link"]) == 1 and p["link"][0]["objects"] == [101, 102]


# --------------------------------------------------------------------------- #
# The first load (Corey, 2026-10-02, ruling 1a)
# --------------------------------------------------------------------------- #
def test_a_same_run_pair_its_dockets_first_load_held_waits_for_a_person(tmp_path):
    """The first load fetched the whole docket at once, so its run says nothing about how a
    pair's two objects relate. Rows 11 and 12 are docket 72000000's first rows."""
    conn = _db(tmp_path)
    _docket(conn)
    _hold(conn, 11, SHORT, 111, case="72000000")
    _hold(conn, 12, LONG, 112, case="72000000")
    p = L.plan(conn, LINKS)
    assert p["link"] == []
    assert [(x["rows"], x["relation"]) for x in p["person"]] == [([11, 12], "first-load")]
    assert p["same_run_cases"] == []          # a first-load pair is not the rule's to link


def test_a_first_load_whose_opening_row_the_clock_cannot_pin_still_counts(tmp_path):
    """The first load's opening row carries no item, so the clock brackets it across the run
    before and its own: the pair's run may be the first load's, and the run cannot tell.
    Five dockets held 39 such pairs on 2026-10-02, which a pinned-row test missed."""
    conn = _db(tmp_path)                      # row 0 pins the run before (2026-07-19)
    _docket(conn)
    conn.execute("INSERT INTO case_entries (id, case_id, entry_at, description) "
                 "VALUES (10, '72000000', '2026-06-01T00:00:00', 'Summons issued as to all defendants')")
    conn.commit()
    _hold(conn, 11, SHORT, 111, case="72000000")
    _hold(conn, 12, LONG, 112, case="72000000")
    assert tw.RunClock(["2026-07-19T10:00:00Z", "2026-07-20T19:31:18Z"],
                       {0: "2026-07-19T10:00:00Z", 11: "2026-07-20T19:31:18Z"}).bracket(10) == (0, 1)
    p = L.plan(conn, LINKS)
    assert [(x["rows"], x["relation"]) for x in p["person"]] == [([11, 12], "first-load")]


def test_a_later_polls_same_run_pair_on_the_same_docket_is_the_rules(tmp_path):
    conn = _db(tmp_path)
    _docket(conn)
    _hold(conn, 11, FIRST, 111, case="72000000", day="2026-06-01T00:00:00")     # the first load
    _hold(conn, 21, SHORT, 121, case="72000000", fetched="2026-07-21T19:31:18Z")
    _hold(conn, 22, LONG, 122, case="72000000", fetched="2026-07-21T19:31:18Z")
    p = L.plan(conn, LINKS)
    assert [(x["rows"], x["relation"]) for x in p["link"]] == [([21, 22], "same-run")]
    assert p["same_run_cases"] == ["72000000"]


def _full_check(conn):
    pool = L.sample_pool(L.plan(conn, LINKS), tw.RULE)
    return {"full": True, "seed": None, "pool": len(pool), "pairs": [sorted(x["rows"]) for x in pool],
            "walks_through": conn.execute("SELECT MAX(walked_at) FROM cl_backfill").fetchone()[0],
            "result": "pass", "read_by": "reader", "on": "2026-10-02"}


def test_sample_all_names_the_whole_pool_with_no_seed(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    _hold(conn, 1, SHORT, 101)
    _hold(conn, 2, LONG, 102)
    _walked(conn)
    conn.close()
    _env(tmp_path, monkeypatch, LINKS)
    out = tmp_path / "all.json"
    assert L.main(["--sample", "all", str(out)]) == 0
    stub = json.loads(out.read_text(encoding="utf-8"))["checked_stub"]
    assert (stub["full"], stub["seed"], stub["pool"], stub["pairs"]) == (True, None, 1, [[1, 2]])


def test_a_full_read_links_its_pool_and_refuses_once_the_pool_grows(tmp_path, monkeypatch):
    """Ruling 1b: the 7 later-poll pairs are read in full in place of a draw. A pair the rule
    meets after the read is one the read never covered, so --apply refuses until it is read."""
    conn = _db(tmp_path)
    _hold(conn, 1, SHORT, 101)
    _hold(conn, 2, LONG, 102)
    _walked(conn)
    chk = _full_check(conn)
    _hold(conn, 7, SHORT, 107, day="2026-07-23T00:00:00", fetched="2026-07-23T10:00:00Z")
    _hold(conn, 8, LONG, 108, day="2026-07-23T00:00:00", fetched="2026-07-23T10:00:05Z")
    grown = _full_check(conn)
    conn.close()
    get = _env(tmp_path, monkeypatch, {**LINKS, "checked": chk})
    assert L.main(["--apply"]) == 2
    assert get().execute("SELECT COUNT(*) FROM cl_entries WHERE twin_of IS NOT NULL").fetchone()[0] == 0
    get = _env(tmp_path, monkeypatch, {**LINKS, "checked": grown})
    assert grown["pairs"] == [[1, 2], [7, 8]]
    assert L.main(["--apply"]) == 0
    assert get().execute("SELECT COUNT(*) FROM cl_entries WHERE twin_of IS NOT NULL").fetchone()[0] == 2
    assert L.main(["--apply"]) == 0               # and the full read still covers its pool after


# --------------------------------------------------------------------------- #
# Links the rule did not propose (Corey's rulings, 2026-10-03, R1 plans and splits, ruling 4)
# --------------------------------------------------------------------------- #
from tools import reader_launch as RL  # noqa: E402

PHV = "Order on Motion to Appear Pro Hac Vice"
AMICUS = "Order on Motion to File Amicus Brief"
# Docket text the rule never pairs with either: "ENDORSED" is no order head it knows.
ENDORSED = ("ENDORSED ORDER granting 7 Motion for A to Appear Pro Hac Vice; granting 8 Motion for B "
            "to Appear Pro Hac Vice; granting 9 Motion to File Amicus Brief")
EMPTY_POOL = {"full": True, "seed": None, "pool": 0, "pairs": [], "walks_through": None,
              "result": "pass", "read_by": "reader", "on": "2026-10-03"}


def _read(tmp_path, outcomes, ok=True, sha=None, name="run.json"):
    """A blind run's record as tools.reader_launch writes it, reduced to what the script reads."""
    path = tmp_path / name
    path.write_text(json.dumps({"ok": ok, "launcher": {"sha256": sha or RL.launcher()["sha256"]},
                                "pairs": {k: {"outcome": v} for k, v in outcomes.items()}}), encoding="utf-8")
    return str(path)


def _read_link(rows, read, kind="plan", label=None):
    return {"rows": rows, "kind": kind, "read": read, "label": label or f"{rows[0]}>{rows[1]}",
            "ruled": "Corey, 2026-10-03"}


def _trio(tmp_path, root_source="entry"):
    """Two descriptions and the docket text, on one day the docket's first load did not hold."""
    conn = _db(tmp_path)
    _hold(conn, 1, PHV, 101)
    _hold(conn, 2, AMICUS, 102)
    _hold(conn, 3, ENDORSED, 103)
    conn.execute("UPDATE cl_entries SET desc_source = ? WHERE cl_entry_id = 103", (root_source,))
    conn.commit()
    assert tw.strict_b([dict(_row(1, PHV)), dict(_row(2, AMICUS)), dict(_row(3, ENDORSED))])[0] == []
    return conn


def test_a_read_link_the_rule_did_not_propose_links_by_its_kind(tmp_path, monkeypatch):
    conn = _trio(tmp_path)
    read = _read(tmp_path, {"1>3": "unanimous"})
    links = {**LINKS, "checked": EMPTY_POOL, "read_links": [_read_link([1, 3], read)]}
    p = L.plan(conn, links)
    assert [(x["rows"], x["by"]) for x in p["link"]] == [([1, 3], "plan: blind read run.json 1>3")]
    assert p["unread"] == [] and p["person"] == []
    conn.close()
    get = _env(tmp_path, monkeypatch, links)
    assert L.main(["--apply"]) == 0
    o = get().execute("SELECT twin_of, twin_rule FROM cl_entries WHERE cl_entry_id = 101").fetchone()
    assert tuple(o) == (103, "plan: blind read run.json 1>3")
    assert L.main(["--apply"]) == 0                                # idempotent: linked already


@pytest.mark.parametrize("change, why", [
    ({"outcome": "split"}, "its read did not pass"),
    ({"ok": False}, "its run failed the check"),
    ({"sha": "0" * 64}, "not read under the stored launcher"),
    ({"label": "2>3"}, "its label names other rows"),
    ({"kind": "short_long"}, "kind short_long, where the rule's is plan"),
    ({"read": "missing.json"}, "no run record"),
    ({"outcome": None}, "its run did not read it"),
])
def test_a_read_link_without_a_passing_read_waits_and_refuses_apply(tmp_path, monkeypatch, change, why):
    conn = _trio(tmp_path)
    outcomes = {"1>3": change.get("outcome", "unanimous"), "2>3": "unanimous"}
    read = _read(tmp_path, {k: v for k, v in outcomes.items() if v},
                 ok=change.get("ok", True), sha=change.get("sha"))
    spec = _read_link([1, 3], str(tmp_path / change["read"]) if "read" in change else read,
                      kind=change.get("kind", "plan"), label=change.get("label"))
    links = {**LINKS, "checked": EMPTY_POOL, "read_links": [spec]}
    p = L.plan(conn, links)
    assert p["link"] == [] and [(x["rows"], x["why"]) for x in p["unread"]] == [([1, 3], why)]
    conn.close()
    get = _env(tmp_path, monkeypatch, links)
    assert L.main(["--apply"]) == 2
    assert get().execute("SELECT COUNT(*) FROM cl_entries WHERE twin_of IS NOT NULL").fetchone()[0] == 0


def test_several_read_links_share_one_docket_text_root(tmp_path, monkeypatch):
    conn = _trio(tmp_path)
    read = _read(tmp_path, {"1>3": "unanimous", "2>3": "unanimous"})
    links = {**LINKS, "checked": EMPTY_POOL,
             "read_links": [_read_link([1, 3], read), _read_link([2, 3], read)]}
    p = L.plan(conn, links)
    assert sorted(x["rows"] for x in p["link"]) == [[1, 3], [2, 3]] and p["would_chain"] == []
    conn.close()
    get = _env(tmp_path, monkeypatch, links)
    assert L.main(["--apply"]) == 0
    c = get()
    assert [tuple(r) for r in c.execute("SELECT cl_entry_id, twin_of FROM cl_entries "
                                        "WHERE cl_entry_id IN (101, 102, 103) ORDER BY 1")] == \
        [(101, 103), (102, 103), (103, None)]
    # The three objects present as one entry, the docket text's.
    assert c.execute("SELECT COUNT(*) FROM items WHERE merged_into IS NULL AND occurred_at = ?",
                     (DAY,)).fetchone()[0] == 1


def test_apply_refuses_while_the_config_holds(tmp_path, monkeypatch):
    conn = _trio(tmp_path)
    read = _read(tmp_path, {"1>3": "unanimous"})
    links = {**LINKS, "checked": EMPTY_POOL, "read_links": [_read_link([1, 3], read)],
             "hold": "until Corey's line on his ten"}
    assert [x["rows"] for x in L.plan(conn, links)["link"]] == [[1, 3]]     # planned, not applied
    conn.close()
    get = _env(tmp_path, monkeypatch, links)
    assert L.main(["--apply"]) == 2
    assert get().execute("SELECT COUNT(*) FROM cl_entries WHERE twin_of IS NOT NULL").fetchone()[0] == 0


def test_a_shared_group_waits_whole_when_one_link_lacks_a_passing_read(tmp_path, monkeypatch):
    conn = _trio(tmp_path)
    read = _read(tmp_path, {"1>3": "unanimous", "2>3": "split"})
    links = {**LINKS, "checked": EMPTY_POOL,
             "read_links": [_read_link([1, 3], read), _read_link([2, 3], read)]}
    p = L.plan(conn, links)
    assert p["link"] == []
    assert sorted((x["rows"], x["why"]) for x in p["unread"]) == [
        ([1, 3], "another link to its root lacks a passing read or a ruling"),
        ([2, 3], "its read did not pass")]
    conn.close()
    get = _env(tmp_path, monkeypatch, links)
    assert L.main(["--apply"]) == 2
    assert get().execute("SELECT COUNT(*) FROM cl_entries WHERE twin_of IS NOT NULL").fetchone()[0] == 0


def test_a_read_link_joins_two_objects_of_one_docket_and_day(tmp_path):
    conn = _trio(tmp_path)
    _hold(conn, 4, PHV + " (re-described)", 101, fetched="2026-07-20T19:31:40Z")   # 101's second row
    _hold(conn, 5, ENDORSED, 105, day="2026-07-21T00:00:00")
    read = _read(tmp_path, {"1>4": "unanimous", "1>5": "unanimous"})
    p = L.plan(conn, {**LINKS, "read_links": [_read_link([1, 4], read), _read_link([1, 5], read)]})
    assert p["link"] == [] and sorted((x["rows"], x["why"]) for x in p["unread"]) == [
        ([1, 4], "one object"), ([1, 5], "not one docket and day")]


def test_a_refusal_wins_over_a_passing_read(tmp_path):
    conn = _trio(tmp_path)
    read = _read(tmp_path, {"1>3": "unanimous"})
    p = L.plan(conn, {**LINKS, "refused": [{"rows": [3, 1]}], "read_links": [_read_link([1, 3], read)]})
    assert p["link"] == [] and [x["rows"] for x in p["refused"]] == [[1, 3]]


def test_a_shared_root_must_be_docket_text(tmp_path):
    conn = _trio(tmp_path, root_source="document")
    read = _read(tmp_path, {"1>3": "unanimous", "2>3": "unanimous"})
    p = L.plan(conn, {**LINKS, "read_links": [_read_link([1, 3], read), _read_link([2, 3], read)]})
    assert p["link"] == [] and sorted(x["rows"] for x in p["would_chain"]) == [[1, 3], [2, 3]]


def test_a_rule_link_never_shares_a_root_with_a_read_link_in_one_run(tmp_path):
    conn = _db(tmp_path)
    _hold(conn, 1, SHORT, 101)                                    # the rule's same-run pair
    _hold(conn, 2, LONG, 102)
    _hold(conn, 3, PHV, 103)
    conn.execute("UPDATE cl_entries SET desc_source = 'entry' WHERE cl_entry_id = 102")
    conn.commit()
    read = _read(tmp_path, {"3>2": "unanimous"})
    p = L.plan(conn, {**LINKS, "read_links": [_read_link([3, 2], read)]})
    assert p["link"] == [] and sorted(x["rows"] for x in p["would_chain"]) == [[1, 2], [3, 2]]


def test_a_read_link_settles_a_rule_pair_that_waited_for_a_person(tmp_path):
    """A first-load pair the rule makes waits for a person; a passing blind read links it,
    labelled by the rule's own kind."""
    conn = _db(tmp_path)
    _docket(conn)
    _hold(conn, 11, SHORT, 111, case="72000000")
    _hold(conn, 12, LONG, 112, case="72000000")
    read = _read(tmp_path, {"11/12": "unanimous"})
    p = L.plan(conn, {**LINKS, "read_links": [_read_link([11, 12], read, kind="short_long", label="11/12")]})
    assert p["person"] == []
    assert [(x["rows"], x["by"]) for x in p["link"]] == [([11, 12], "short_long: blind read run.json 11/12")]


# --------------------------------------------------------------------------- #
# A ruling as evidence (Corey's rulings, 2026-10-03, a ruling as evidence, ruling 1)
# --------------------------------------------------------------------------- #
def _ruled(links, reads):
    return {"by": "Corey", "date": "2026-10-03",
            "criterion": "The clocks reader's only dissent is on a short form with no filing time.",
            "links": links, "reads": reads}


def _split_group(tmp_path):
    """The trio sharing the docket-text root 3: 1>3 read unanimous, 2>3 split. The run also
    read 2>1, which no read link carries."""
    conn = _trio(tmp_path)
    read = _read(tmp_path, {"1>3": "unanimous", "2>3": "split", "2>1": "split"})
    return conn, read, [_read_link([1, 3], read), _read_link([2, 3], read)]


GROUP_WAITS = [([1, 3], "another link to its root lacks a passing read or a ruling"),
               ([2, 3], "its read did not pass")]


def _apply_refused(tmp_path, monkeypatch, links):
    get = _env(tmp_path, monkeypatch, links)
    assert L.main(["--apply"]) == 2
    assert get().execute("SELECT COUNT(*) FROM cl_entries WHERE twin_of IS NOT NULL").fetchone()[0] == 0


def test_a_ruled_entry_stands_in_for_a_read_in_a_shared_group(tmp_path, monkeypatch):
    conn, read, read_links = _split_group(tmp_path)
    links = {**LINKS, "checked": EMPTY_POOL, "read_links": read_links,
             "ruled": [_ruled([[2, 3]], [read])]}
    p = L.plan(conn, links)
    assert p["unread"] == [] and p["ruled_refused"] == [] and p["would_chain"] == []
    ruled_by = "plan: ruled by Corey, 2026-10-03, over blind read run.json 2>3"
    assert sorted((x["rows"], x["by"]) for x in p["link"]) == [
        ([1, 3], "plan: blind read run.json 1>3"), ([2, 3], ruled_by)]
    conn.close()
    get = _env(tmp_path, monkeypatch, links)
    assert L.main(["--apply"]) == 0
    assert [tuple(r) for r in get().execute(
        "SELECT cl_entry_id, twin_of, twin_rule FROM cl_entries "
        "WHERE cl_entry_id IN (101, 102, 103) ORDER BY 1")] == [
        (101, 103, "plan: blind read run.json 1>3"), (102, 103, ruled_by), (103, None, None)]


def test_removing_the_ruled_entry_refuses_its_group(tmp_path, monkeypatch):
    conn, read, read_links = _split_group(tmp_path)
    links = {**LINKS, "checked": EMPTY_POOL, "read_links": read_links,
             "ruled": [_ruled([[2, 3]], [read])]}
    assert sorted(x["rows"] for x in L.plan(conn, links)["link"]) == [[1, 3], [2, 3]]
    del links["ruled"]
    p = L.plan(conn, links)
    assert p["link"] == [] and sorted((x["rows"], x["why"]) for x in p["unread"]) == GROUP_WAITS
    conn.close()
    _apply_refused(tmp_path, monkeypatch, links)


@pytest.mark.parametrize("change, why", [
    ({"reads": ["other.json"]}, "it names a link it does not cover: 2>3"),
    ({"reads": []}, "it names no reads"),
    ({"reads": ["run.json", "missing.json"]}, "it names a read with no run record"),
    ({"links": []}, "it names no links"),
    ({"links": [[2, 3], [2, 1]]}, "it names a link no read link carries: 2>1"),
    ({"by": None}, "it does not say who ruled, when and by what criterion"),
    ({"date": ""}, "it does not say who ruled, when and by what criterion"),
    ({"criterion": " "}, "it does not say who ruled, when and by what criterion"),
])
def test_a_refused_ruled_entry_leaves_its_group_waiting(tmp_path, monkeypatch, change, why):
    conn, read, read_links = _split_group(tmp_path)
    _read(tmp_path, {"1>3": "unanimous"}, name="other.json")      # a run that never read 2>3
    if "reads" in change:
        change = {"reads": [str(tmp_path / f) for f in change["reads"]]}
    links = {**LINKS, "checked": EMPTY_POOL, "read_links": read_links,
             "ruled": [{**_ruled([[2, 3]], [read]), **change}]}
    p = L.plan(conn, links)
    assert [r["why"] for r in p["ruled_refused"]] == [why]
    assert p["link"] == [] and sorted((x["rows"], x["why"]) for x in p["unread"]) == GROUP_WAITS
    conn.close()
    _apply_refused(tmp_path, monkeypatch, links)


def test_a_refused_ruled_entry_refuses_apply_though_every_link_passes(tmp_path, monkeypatch, capsys):
    conn = _trio(tmp_path)
    read = _read(tmp_path, {"1>3": "unanimous"})
    links = {**LINKS, "checked": EMPTY_POOL, "read_links": [_read_link([1, 3], read)],
             "ruled": [{**_ruled([[1, 3]], [read]), "reads": []}]}
    p = L.plan(conn, links)
    assert [x["rows"] for x in p["link"]] == [[1, 3]] and p["unread"] == []
    conn.close()
    _apply_refused(tmp_path, monkeypatch, links)
    out = capsys.readouterr().out
    assert "ruled entry (Corey, 2026-10-03): it names no reads" in out
    assert "REFUSED: ruled entries refused: 1" in out


def test_a_ruling_over_other_reads_is_no_evidence_for_a_link(tmp_path):
    conn, read, read_links = _split_group(tmp_path)
    other = _read(tmp_path, {"2>3": "split"}, name="other.json")   # 2>3 read in another run
    p = L.plan(conn, {**LINKS, "read_links": read_links, "ruled": [_ruled([[2, 3]], [other])]})
    assert p["ruled_refused"] == [] and p["link"] == []
    assert sorted((x["rows"], x["why"]) for x in p["unread"]) == [
        GROUP_WAITS[0], ([2, 3], "its read did not pass, and the ruling naming it stands over other reads")]


def test_a_ruling_is_evidence_only_for_the_links_it_names(tmp_path):
    conn, read, read_links = _split_group(tmp_path)
    p = L.plan(conn, {**LINKS, "read_links": read_links, "ruled": [_ruled([[1, 3]], [read])]})
    assert p["ruled_refused"] == [] and p["link"] == []
    assert sorted((x["rows"], x["why"]) for x in p["unread"]) == GROUP_WAITS


def test_the_committed_read_links_carry_passing_blind_reads():
    """No DB: every committed read link names a run that passed the check under the stored
    launcher and read the link, unanimous or under a committed ruled entry that names it and
    stands over that run; no committed ruled entry is refused."""
    links = L.load_links()
    sha = RL.launcher()["sha256"]
    carried = {tuple(s["rows"]) for s in links.get("read_links") or []}
    rulings = [L.ruling(s, carried) for s in links.get("ruled") or []]
    assert [r["why"] for r in rulings if r["why"]] == []
    for spec in links.get("read_links") or []:
        rec = L._load_read(spec["read"])
        assert rec and rec["ok"] is True and rec["launcher"]["sha256"] == sha, spec
        assert L._label_rows(spec["label"], spec["rows"]), spec
        assert rec["pairs"][spec["label"]]["outcome"] == "unanimous" or any(
            tuple(spec["rows"]) in r["links"] and L._read_path(spec["read"]) in r["reads"]
            for r in rulings), spec
