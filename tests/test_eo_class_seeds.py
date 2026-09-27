"""The EO challenge class's seeds, held against the sentences that count them.

RULING (a) OF THE EO 14399 UNIT (Corey, 2026-09-26): each seed records the order it
challenges, and a check fails if a held row's order is not the one the sentence names,
so seeding a 14248 docket later forces the sentence to widen. Two sentences count the
class -- tab 1's `eo-challenges` and tab 2's `eo-challenges-held`, both produced by
eoLawsuits (docs/gates.yaml) -- and both name their order in words, "the mail-ballot
executive order", because a derived entry may hold no digit outside a placeholder. So
the order they mean is carried beside each as `names_order`, and the two must agree.

GUARDS BESIDE IT, from the unit's reviews (docs/status.md, *The EO 14399 dockets*):

- THE CATEGORY SPELLING. The class is read off `category` alone (web/lib/stands.ts,
  isEoChallenge), so a seed spelled `executive_order` would fall silently into the
  related suits -- the defect the unit closed -- and an order check that reads the
  class would never see it. So a seed names an `order` exactly when it is marked.
- NO STATE. A challenge seed carrying `state` would join the campaign rows
  (getCampaignRows filters only on `state IS NOT NULL`) and with them DOJ-scoped figures:
  the grid, "DOJ has sued {sued} of {total}", the rejection evidence.
- THE PINS. Every challenge seed pins its CourtListener id, and no id is pinned twice.
  (Whether a pin names the right docket is not checkable offline; status.md records the
  read that confirmed each.)
- THE COURT STRING. The sentences count lawsuits, the class's trial-court dockets, by
  excluding appellate courts on the court STRING (isAppellate). Config courts are typed
  by hand and coverage_audit's vocabulary alarm (section 5) reads only the tracker
  artifact, so a seed typed "1st Cir." would be counted as a lawsuit. So a challenge
  seed's court must be appellate exactly when its docket number is an appeal's, and must
  not be an alias the page rewrites (canonicalCourt) before classifying.

The helpers return problems rather than asserting, so each rule is tested twice: on the
real config, where it must find nothing, and on a constructed mutation, where it must
find the one thing planted. A check never seen to fail is not known to work.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import yaml

from collectors.tracker_uw import COURT_ALIASES

ROOT = Path(__file__).resolve().parent.parent
EO = "executive-order"
# schema.sql, cases.category: "voter-data | executive-order | registration-law |
# redistricting | other".
VOCABULARY = {"voter-data", "executive-order", "registration-law", "redistricting", "other"}
# web/lib/stands.ts isAppellate: isCircuit (web/lib/campaign.ts: /\bcircuit\b/i after
# canonicalCourt) or /\bSupreme Court\b/i. The alias guard below keeps canonicalCourt
# the identity on every challenge seed's court, so the raw string is what the page reads.
APPELLATE = re.compile(r"\bcircuit\b|\bSupreme Court\b", re.IGNORECASE)
TRIAL_DOCKET = re.compile(r"^\d+:\d{2}-cv-\d+$")
LAWSUITS = "web/lib/stands.ts#eoLawsuits"


def _seeds() -> list[dict]:
    doc = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    return doc["litigation"]["seed_cases"]


def _gates() -> list[dict]:
    return yaml.safe_load((ROOT / "docs" / "gates.yaml").read_text(encoding="utf-8"))


def _held() -> list[dict]:
    return json.loads((ROOT / "data" / "cases.json").read_text(encoding="utf-8"))


def sentence_problems(gates: list[dict]) -> list[str]:
    """Every sentence produced by eoLawsuits names an order, and they all name the same."""
    counting = [g for g in gates if g.get("produced_by") == LAWSUITS]
    if not counting:
        return ["no sentence counts eoLawsuits"]
    out = [f"{g.get('id')}: no names_order" for g in counting
           if not isinstance(g.get("names_order"), str) or not g.get("names_order")]
    orders = {g["names_order"] for g in counting if isinstance(g.get("names_order"), str) and g["names_order"]}
    if len(orders) > 1:
        out.append(f"the sentences name different orders: {sorted(map(str, orders))}")
    return out


def _sentence_order(gates: list[dict]) -> str:
    assert sentence_problems(gates) == []
    return next(g["names_order"] for g in gates if g.get("produced_by") == LAWSUITS)


def category_problems(seeds: list[dict]) -> list[str]:
    out = []
    for s in seeds:
        cat = s.get("category")
        if cat not in VOCABULARY:
            out.append(f"{s.get('docket_number')}: category {cat!r} is not in the schema's vocabulary")
        if ("order" in s) != (cat == EO):
            out.append(f"{s.get('docket_number')}: names an order without the class mark, or the reverse")
    return out


def state_problems(seeds: list[dict]) -> list[str]:
    return [f"{s.get('docket_number')}: a challenge seed carries state {s.get('state')!r}; it would join "
            f"the campaign rows" for s in seeds if s.get("category") == EO and s.get("state")]


def order_problems(seeds: list[dict], held: list[dict], sentence_order: str) -> list[str]:
    out = []
    by_id = {str(s["case_id"]): s for s in seeds if s.get("case_id") is not None}
    for s in seeds:
        if s.get("category") == EO and s.get("order") != sentence_order:
            out.append(f"seed {s.get('docket_number')}: order {s.get('order')!r}, the sentence names {sentence_order!r}")
    for r in held:
        if r.get("category") != EO:
            continue
        seed = by_id.get(str(r.get("case_id")))
        if seed is None:
            out.append(f"held row {r.get('case_id')}: marked a challenge, but no seed pins it")
        elif seed.get("order") != sentence_order:
            out.append(f"held row {r.get('case_id')}: its seed names {seed.get('order')!r}, the sentence {sentence_order!r}")
    return out


def pin_problems(seeds: list[dict]) -> list[str]:
    out = [f"{s.get('docket_number')}: a challenge seed must pin its CourtListener id"
           for s in seeds if s.get("category") == EO and not re.fullmatch(r"\d+", str(s.get("case_id") or ""))]
    counts = Counter(str(s["case_id"]) for s in seeds if s.get("case_id") is not None)
    out += [f"case_id {c} is pinned on {n} seeds" for c, n in sorted(counts.items()) if n > 1]
    return out


def court_problems(seeds: list[dict]) -> list[str]:
    out = []
    for s in seeds:
        if s.get("category") != EO:
            continue
        court = s.get("court") or ""
        if court in COURT_ALIASES:
            out.append(f"{s.get('docket_number')}: court {court!r} is an alias the page rewrites before classifying")
            continue
        appellate = bool(APPELLATE.search(court))
        trial = bool(TRIAL_DOCKET.match(s.get("docket_number") or ""))
        if appellate == trial:
            out.append(f"{s.get('docket_number')}: court {court!r} reads "
                       f"{'appellate' if appellate else 'trial'}, the docket number the other")
    return out


# --- on the real config: nothing ----------------------------------------------------

def test_both_counting_sentences_name_one_order():
    assert sentence_problems(_gates()) == []


def test_every_seed_category_is_in_the_vocabulary_and_orders_go_with_the_mark():
    assert category_problems(_seeds()) == []


def test_no_challenge_seed_carries_a_state():
    assert state_problems(_seeds()) == []


def test_every_challenge_seed_and_held_challenge_row_names_the_sentences_order():
    assert order_problems(_seeds(), _held(), _sentence_order(_gates())) == []


def test_every_challenge_seed_pins_its_id_and_no_id_is_pinned_twice():
    assert pin_problems(_seeds()) == []


def test_every_challenge_seeds_court_agrees_with_its_docket_shape():
    assert court_problems(_seeds()) == []


def test_the_python_appellate_rule_is_the_pages():
    # The page's own rule, line for line, so this copy cannot drift from it unseen: a
    # third disjunct in isAppellate or a change to isCircuit's body turns this red.
    stands = (ROOT / "web" / "lib" / "stands.ts").read_text(encoding="utf-8")
    campaign = (ROOT / "web" / "lib" / "campaign.ts").read_text(encoding="utf-8")
    assert 'return isCircuit(court) || /\\bSupreme Court\\b/i.test(court ?? "");' in stands
    assert "const name = canonicalCourt(court);" in campaign
    assert "return !!name && /\\bcircuit\\b/i.test(name);" in campaign


# --- on constructed mutations: exactly the planted defect ---------------------------

def _eo(**over) -> dict:
    s = {"caption": "X v. Y", "docket_number": "1:26-cv-00001", "court": "D. Mass.", "court_id": "mad",
         "category": EO, "order": "EO 14399", "case_id": "1"}
    s.update(over)
    return s


def _gate(id_, order="EO 14399"):
    g = {"id": id_, "kind": "derived", "produced_by": LAWSUITS, "renders_as": "x"}
    if order is not None:
        g["names_order"] = order
    return g


def test_two_sentences_naming_different_orders_fail():
    assert len(sentence_problems([_gate("a"), _gate("b", "EO 14248")])) == 1


def test_a_sentence_with_no_names_order_fails():
    assert sentence_problems([_gate("a"), _gate("b", None)]) == ["b: no names_order"]


def test_a_14248_seed_forces_the_sentence_to_widen():
    probs = order_problems([_eo(order="EO 14248")], [], "EO 14399")
    assert len(probs) == 1 and "EO 14248" in probs[0]


def test_a_held_challenge_row_with_no_seed_fails():
    probs = order_problems([], [{"case_id": "99", "category": EO}], "EO 14399")
    assert probs == ["held row 99: marked a challenge, but no seed pins it"]


def test_a_misspelled_category_fails_twice_over():
    assert len(category_problems([_eo(category="executive_order")])) == 2


def test_an_order_without_the_mark_fails():
    assert len(category_problems([_eo(category="voter-data")])) == 1


def test_a_challenge_seed_with_a_state_fails():
    assert len(state_problems([_eo(state="California")])) == 1


def test_an_unpinned_challenge_seed_fails():
    assert len(pin_problems([_eo(case_id=None)])) == 1


def test_an_id_pinned_twice_fails():
    assert pin_problems([_eo(case_id="7"), _eo(docket_number="1:26-cv-00002", case_id="7")]) == \
        ["case_id 7 is pinned on 2 seeds"]


def test_an_abbreviated_circuit_counts_as_a_lawsuit_and_fails():
    probs = court_problems([_eo(docket_number="26-2029", court="1st Cir.")])
    assert len(probs) == 1 and "trial" in probs[0]


def test_a_circuit_court_on_a_trial_docket_fails():
    assert len(court_problems([_eo(court="First Circuit")])) == 1


def test_an_alias_court_string_fails():
    assert len(court_problems([_eo(docket_number="26-2679", court="Eighth District")])) == 1
