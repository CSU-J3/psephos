"""The recheck flags (Corey's ruling (3), 2026-09-29): the order-like test, the id
watermark, the measurement, and the standing-issue comment worded as a flag.

THE TEST IS PINNED TO ITS MEASUREMENT. The D0 labelled every row of its window
(2026-09-15..09-28, 251 held entries, public docket text) and measured its proposed test,
V4, at 15 flags, 8 true, 7 false, 0 missed, against the naive test's 51 flags and 1 miss.
tools/recheck_flags.py ports V4 verbatim; the fixture is that window, so a change to the
patterns that moves those numbers fails here and has to be argued as a re-measurement.

Pure: no database, no network. Run: pytest tests/test_recheck_flags.py
"""
from __future__ import annotations

import collections
import copy
import json
from pathlib import Path

import pytest

from tools import recheck_flags as rf

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "recheck_flags_window.json")
                     .read_text(encoding="utf-8"))
ROWS = FIXTURE["rows"]
OPERATIVE = set(FIXTURE["operative"])


def _by_docket(rows):
    out = collections.defaultdict(list)
    for r in rows:
        out[str(r["case_id"])].append(r)
    return out


# --- the test, against its measurement ---------------------------------------------------

def test_v4_reproduces_the_d0_measurement_on_its_window():
    by = _by_docket(ROWS)
    flagged = {r["id"] for r in ROWS if rf.classify(r, by[str(r["case_id"])])}
    assert len(ROWS) == 251
    assert len(flagged) == 15
    assert len(flagged & OPERATIVE) == 8          # every operative entry in the window
    assert len(flagged - OPERATIVE) == 7
    assert not OPERATIVE - flagged                  # 0 missed


def test_the_naive_count_is_the_d0s_baseline():
    naive = {r["id"] for r in ROWS if rf.naive(r["description"])}
    assert len(naive) == 51
    assert OPERATIVE - naive == {91411}            # the Supreme Court stay it cannot see


def test_the_supreme_court_stay_letter_flags_through_the_disposition_pattern():
    r = next(r for r in ROWS if r["id"] == 91411)
    assert not rf._headed(r["description"])        # not headed as an order ...
    assert rf.order_like_text(r["description"])     # ... but a disposition


NOA_92175 = (
    "NOTICE OF APPEAL as to 156 Memorandum & ORDER by Derek Kan, Amber McReynolds, David "
    "Steiner, Ronald Stroman, Daniel Tangherlini, Doug Tulino, United States Postal Service. "
    "Fee Status: US Government. NOTICE TO COUNSEL: A Transcript Report/Order Form, which can "
    "be downloaded from the First Circuit Court of Appeals web site at "
    "http://www.ca1.uscourts.gov MUST be completed and submitted to the Court of Appeals.")


def test_the_notice_of_appeal_exemption_is_what_keeps_a_real_notice():
    n = rf.norm(NOA_92175)
    assert rf.PROCEDURAL.search(n) and not rf.PROTECT.search(n)   # trimmed but for it
    assert rf.order_like_text(NOA_92175)


@pytest.mark.parametrize("desc, expected", [
    ("ORDER granting motion to dismiss", True),
    ("Judge Indira Talwani: ELECTRONIC ORDER entered granting preliminary injunction", True),
    ("NOTICE OF APPEAL TO DC CIRCUIT COURT as to 217 Order", True),
    (NOA_92175, True),                    # kept only by the notice-of-appeal exemption
    ("NOTICE OF Interlocutory APPEAL (26-1429) to Ninth Circuit re 126 Order", True),
    ("PER CURIAM: the district court's decision is summarily affirmed", True),  # bare head
    ("MINUTE ORDER admitting counsel pro hac vice", False),
    ("ORDER extending time to file the reply brief", False),
    ("ORDER denying motion for extension, and staying the injunction", True),        # protected
    ("MOTION for Order to Show Cause", False),       # a party's motion, not an order
    ("Transcript report/order form filed", False),
    ("This entry has been removed from the docket. ORDER granting", False),
    ("ENTERED IN ERROR. Application for stay was granted", False),  # the guard, on DISPO
    ("LETTER received from the Clerk of the Supreme Court: application for stay was granted", True),
])
def test_order_like_text(desc, expected):
    assert rf.order_like_text(desc) is expected


def test_a_short_form_takes_its_twins_verdict_either_way_or_is_unreadable():
    url1 = "https://www.courtlistener.com/docket/1/305/x/"
    url2 = "https://www.courtlistener.com/docket/1/306/x/"
    pos_long = {"id": 1, "case_id": "1", "entry_at": "2026-09-29", "document_url": url1,
                "description": "ORDER granting defendants' emergency motion to stay the "
                               "preliminary injunction pending appeal"}
    pos_short = {"id": 2, "case_id": "1", "entry_at": "2026-09-29", "document_url": url1,
                 "description": "Order on Motion to Stay"}
    neg_long = {"id": 3, "case_id": "1", "entry_at": "2026-09-29", "document_url": url2,
                "description": "ORDER denying the non-party's motion to intervene as a "
                               "defendant in this action"}
    neg_short = {"id": 4, "case_id": "1", "entry_at": "2026-09-29", "document_url": url2,
                 "description": "Order filed"}
    lone = {"id": 5, "case_id": "1", "entry_at": "2026-09-29",
            "description": "Order on Motion to Enforce Judgment", "document_url": None}
    rows = [pos_long, pos_short, neg_long, neg_short, lone]
    assert not rf.is_short(pos_long["description"]) and not rf.is_short(neg_long["description"])
    assert rf.order_like_text(pos_short["description"])
    assert rf.order_like_text(neg_short["description"])
    assert rf.classify(pos_short, rows) == "flag"     # inherits a positive twin
    assert rf.classify(neg_short, rows) is None        # inherits a negative twin
    assert rf.classify(lone, rows) == "unreadable"     # no twin: flagged, content in the PDF


# --- the watermark ----------------------------------------------------------------------

def _reading(docket="1", through=10, verdicts=None):
    return {"gate": "g", "docket": docket, "read_on": "2026-09-29", "through_entry_id": through,
            "through_entry_at": "2026-09-28", "verdicts": verdicts or {}}


def test_only_entries_above_the_watermark_flag_and_a_twin_below_it_still_counts():
    rows = {"1": [
        {"id": 5, "case_id": "1", "entry_at": "2026-09-01", "description": "ORDER granting stay",
         "document_url": None},
        {"id": 9, "case_id": "1", "entry_at": "2026-09-28", "description":
         "ORDER granting the States' motion for leave to file an amicus brief supporting "
         "appellees", "document_url":
         "https://www.courtlistener.com/docket/1/40/x/"},
        {"id": 11, "case_id": "1", "entry_at": "2026-09-28", "description": "Order filed",
         "document_url": "https://www.courtlistener.com/docket/1/40/x/"},
        {"id": 12, "case_id": "1", "entry_at": "2026-09-29", "description":
         "MEMORANDUM OPINION AND ORDER vacating the injunction", "document_url": None},
    ]}
    [res] = rf.flags([_reading()], rows)
    assert [x["id"] for x in res["flagged"]] == [12]  # 5 is read; 11's twin (9) is noise
    assert res["above"] == 2 and res["naive"] == 2 and res["max_id"] == 12
    assert res["max_entry_at"] == "2026-09-29" and res["ahead"] is False


def test_the_entry_at_the_watermark_is_read_not_flagged():
    rows = {"1": [
        {"id": 10, "case_id": "1", "entry_at": "2026-09-28",
         "description": "ORDER granting stay pending appeal", "document_url": None},
        {"id": 12, "case_id": "1", "entry_at": "2026-09-29",
         "description": "MEMORANDUM OPINION AND ORDER vacating the injunction", "document_url": None},
    ]}
    [res] = rf.flags([_reading()], rows)             # through_entry_id == 10
    assert [x["id"] for x in res["flagged"]] == [12]


def test_a_watermark_above_the_held_record_is_named_not_silent():
    rows = {"1": [{"id": 5, "case_id": "1", "entry_at": "2026-09-01",
                   "description": "ORDER granting stay", "document_url": None}]}
    [res] = rf.flags([_reading(through=900)], rows)
    assert res["ahead"] is True and res["flagged"] == []
    lines = rf.report_lines([res], collections.Counter())
    assert any("WATERMARK AHEAD OF THE RECORD" in ln for ln in lines)


# --- the register's readings ------------------------------------------------------------

def test_the_real_registers_readings_are_well_formed():
    gates = rf.load_gates()
    assert rf.reading_problems(gates) == []
    listed = {(g["id"], str(c)) for g in rf.listed_gates(gates) for c in g["record_instruments"]}
    assert {(r["gate"], r["docket"]) for r in rf.readings(gates)} == listed


@pytest.mark.parametrize("plant, needle", [
    (lambda g: g.pop("record_read"), "carries no record_read"),
    (lambda g: g["record_read"].append(dict(g["record_read"][0])), "has 2 readings"),
    (lambda g: g["record_read"][0].update(docket="1"), "is not in record_instruments"),
    (lambda g: g["record_read"][0].update(through_entry_id="9"), "non-negative integer"),
    (lambda g: g["record_read"][0].update(verdicts={5: "maybe"}), "verdict 5"),
    (lambda g: g["record_read"][0].update(extra=1), "unknown keys"),
    (lambda g: g["record_read"][0].update(read_on="2026-9-29"), "YYYY-MM-DD"),
    (lambda g: g["record_read"][0].pop("through_entry_at"), "missing"),
])
def test_a_malformed_reading_is_named(plant, needle):
    gates = copy.deepcopy(rf.load_gates())
    g = next(g for g in gates if g.get("record_instruments"))
    plant(g)
    problems = rf.reading_problems(gates)
    assert any(needle in p for p in problems), problems
    with pytest.raises(ValueError):
        rf.compute(None, gates)                     # refuses before touching a connection


def test_the_tally_counts_every_recorded_verdict():
    gates = [{"record_read": [{"verdicts": {1: "operative", 2: "noise"}}, {"verdicts": {}}]},
             {"record_read": [{"verdicts": {3: "noise", 4: "missed"}}]}, {"id": "x"}]
    assert rf.tally(gates) == collections.Counter(operative=1, noise=2, missed=1)


# --- the report and the comment -----------------------------------------------------------

def _result(flagged_ids, kind="flag"):
    return [{**_reading(), "held": 3, "max_id": 12, "max_entry_at": "2026-09-29", "above": 2,
             "naive": 1, "flagged": [{"id": i, "case_id": "1", "entry_at": "2026-09-29",
                                       "description": "ORDER vacating | the injunction",
                                       "document_url": None, "kind": kind}
                                      for i in flagged_ids]}]


def test_the_report_line_says_report_not_alarm_and_carries_the_naive_count():
    lines = rf.report_lines(_result([12]), collections.Counter(noise=2))
    assert lines[0].startswith("  [9] RECHECK FLAGS")
    assert "a report, not an alarm" in lines[0] and "naive count beside it: 1" in lines[0]
    assert "verdicts so far: 2" in lines[1] and rf.PERIOD_END in lines[1]
    assert any("FLAG 12" in ln for ln in lines)


def test_the_comment_is_worded_as_a_flag_and_posts_only_what_is_new():
    body = rf.comment_body(_result([12, 13]), set(), "https://example.invalid/run/1")
    assert body.startswith("cc @CSU-J3")
    assert "not a failure" in body and "never turns a run red" in body
    assert "fail" not in body.lower().replace("not a failure", "")
    assert rf.posted_ids(body) == {12, 13}
    assert "ORDER vacating / the injunction" in body  # a pipe cannot break the table
    # Posted once, not again; a new id alone is posted next time.
    assert rf.comment_body(_result([12, 13]), rf.posted_ids(body)) is None
    again = rf.comment_body(_result([12, 13, 14]), rf.posted_ids(body))
    assert rf.posted_ids(again) == {14}


def test_an_unreadable_flag_says_its_content_is_only_in_the_pdf():
    body = rf.comment_body(_result([12], kind="unreadable"), set())
    assert "content only in the PDF" in body


def test_the_fragment_carries_the_held_record_and_a_verdict_slot_per_flag():
    frag = rf.fragment(_result([12]))
    assert '  - docket: "1"' in frag and "through_entry_id: 12" in frag
    assert "12: operative | noise" in frag


def test_verdicts_accumulate_when_a_reading_moves():
    """The measurement is the period's: a moved reading keeps the verdicts its docket
    already carries, and a flag already given a verdict gets no second slot."""
    result = _result([12, 13])
    result[0]["verdicts"] = {7: "operative", 12: "noise"}
    frag = rf.fragment(result)
    assert "      7: operative" in frag and "      12: noise" in frag
    assert "12: operative | noise" not in frag and "13: operative | noise" in frag
