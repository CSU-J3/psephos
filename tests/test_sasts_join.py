"""Offline tests for the sasts bucket join (handoff 11, 5b-b Part B).

No network, no DB, no corpus files -- synthetic sasts corpus + synthetic held set
+ synthetic title index + a small term list, driving tools.sasts_join.bucketize
and iter_relations directly. The regression that matters: a join bug that leaks an
unresolvable target into the `candidate` bucket would manufacture a false vehicle,
and the id-coercion bug (int target vs text dimension id) would fake the finding by
dumping every relation into `candidate`. Both are asserted here.

Run:  pytest tests/test_sasts_join.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools import sasts_join as j  # noqa: E402

TERMS = ["voter", "voting", "early voting"]
EXCLUDES = ["voter approval"]

# One carrier per relation type we want to exercise. sast_bill_id is an INT, as
# LegiScan returns it -- the mixed-type case (int target vs text held/index ids).
CORPUS = {
    "carriers": {
        "TX": [
            {"bill_id": 100, "bill_number": "HB1", "sasts": [
                {"type_id": 1, "type": "Same As", "sast_bill_number": "SB1", "sast_bill_id": 200},   # held
                {"type_id": 5, "type": "Replaces", "sast_bill_number": "HB9", "sast_bill_id": 300},  # candidate
            ]},
            {"bill_id": 101, "bill_number": "HB2", "sasts": [
                {"type_id": 3, "type": "Similar To", "sast_bill_number": "HB4", "sast_bill_id": 400},  # straggler
                {"type_id": 1, "type": "Same As", "sast_bill_number": "ZZ9", "sast_bill_id": 999},     # unresolvable
                {"type_id": 1, "type": "Same As", "sast_bill_number": "HB2", "sast_bill_id": 101},     # self-ref -> dropped
            ]},
        ],
    }
}

# held set is TEXT (as state_bill_id comes off data/state_bills.json).
HELD = {"100", "101", "200"}

# title index keys are TEXT (numeric strings, as masterlist_corpus keys are).
TITLE_INDEX = {
    "300": {"title": "An act relating to municipal drainage districts", "description": ""},   # fails -> candidate
    "400": {"title": "An act relating to early voting hours", "description": ""},              # passes -> straggler
    # 999 is deliberately ABSENT -> unresolvable
}


def _bucketed():
    rels = list(j.iter_relations(CORPUS))
    return j.bucketize(rels, HELD, TITLE_INDEX, TERMS, EXCLUDES)


def _by_target(bucketed, tid):
    return next(r for r in bucketed if r["target_bill_id"] == tid)


def test_self_reference_is_dropped_before_bucketing():
    rels = list(j.iter_relations(CORPUS))
    # 5 sast elements authored, one is a self-reference (101 -> 101) -> 4 relations.
    assert len(rels) == 4
    assert all(not (r["source_bill_id"] == r["target_bill_id"]) for r in rels)


def test_held_matches_across_int_target_vs_text_dimension_id():
    # The defect that would fake the whole finding: sast_bill_id 200 (int in the
    # corpus) must resolve as held against the text id "200". If coercion is wrong,
    # this lands in `candidate` and `held` collapses to near-zero.
    assert _by_target(_bucketed(), "200")["bucket"] == "held"


def test_candidate_is_unheld_and_fails_election_match():
    r = _by_target(_bucketed(), "300")
    assert r["bucket"] == "candidate"
    assert r["type"] == "Replaces"


def test_straggler_is_unheld_but_passes_election_match():
    assert _by_target(_bucketed(), "400")["bucket"] == "straggler"


def test_unresolvable_target_stays_out_of_candidate():
    # 999 is absent from the title index. It MUST bucket unresolvable, never
    # candidate -- the leak that would manufacture a false vehicle.
    r = _by_target(_bucketed(), "999")
    assert r["bucket"] == "unresolvable"
    assert r["bucket"] != "candidate"


def test_bucket_tally():
    from collections import Counter
    counts = Counter(r["bucket"] for r in _bucketed())
    assert counts == {"held": 1, "candidate": 1, "straggler": 1, "unresolvable": 1}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("ok")
