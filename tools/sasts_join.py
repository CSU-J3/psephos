"""Offline join for the sasts probe (handoff 11, 5b-b Part B/C). Zero API queries.

Takes the sasts corpus (tools/sasts_dump), the state_bills dimension (the held
set), the masterlist title snapshot (tools/masterlist_corpus, for target titles),
and the LIVE election filter, and buckets every outward relation:

  1. held        -- target already in state_bills (a companion/related election
                    bill). The spike predicts this dominates.
  2. straggler   -- target not held, but its masterlist title PASSES election_match:
                    a recall miss in the current term list. Feeds a later term tweak
                    (handoff-9 methodology), not this unit.
  3. candidate   -- target not held and its masterlist title FAILS election_match:
                    the payload of the whole probe -- a voting bill asserting a
                    relation to a bill that isn't about voting.
  4. unresolvable-- target absent from the masterlist corpus (prior session,
                    out-of-scope state, withdrawn). Counted separately; folding it
                    into any other bucket would corrupt both.

The bucket order below is load-bearing: held, THEN unresolvable, THEN the
title-based split -- so a target with no title snapshot can never fall through to
`candidate` and manufacture a false vehicle.

Id normalization is the other load-bearing detail: state_bill_id is text,
getBill's sast_bill_id is an int, masterlist keys are numeric strings. All three
are coerced with str() at their load boundary; comparing them raw would miss every
held/resolvable match and dump every relation into `candidate`. (A near-zero
`held` count in the report is the signature of that bug -- read it as a coercion
error to rule out before it is a finding to report.)

Run from the repo root:  python -m tools.sasts_join
"""
from __future__ import annotations

import json
import subprocess
from collections import Counter, defaultdict

import config
from collectors.state import election_match

SASTS = "data/sasts_corpus.json"
DIMENSION = "data/state_bills.json"
MASTERLIST = "data/masterlist_corpus.json"

BUCKETS = ("held", "straggler", "candidate", "unresolvable")


# --- pure join (the unit the tests drive) -----------------------------------

def iter_relations(sasts_corpus: dict):
    """Yield one normalized relation per sast element, dropping self-references
    (target == source), so a bill asserting a relation to itself never buckets.
    Every id is coerced to str at this boundary."""
    for state, bills in sasts_corpus.get("carriers", {}).items():
        for b in bills:
            src_id = str(b["bill_id"])
            for s in b.get("sasts") or []:
                tgt_id = str(s.get("sast_bill_id"))
                if tgt_id == src_id:
                    continue
                yield {
                    "source_state": state,
                    "source_bill_id": src_id,
                    "source_bill_number": b.get("bill_number") or "",
                    "type": s.get("type") or f"type_id={s.get('type_id')}",
                    "type_id": s.get("type_id"),
                    "target_bill_id": tgt_id,
                    "target_bill_number": s.get("sast_bill_number") or "",
                }


def bucketize(relations, held_ids: set, title_index: dict,
              terms: list, excludes) -> list[dict]:
    """Tag each relation with a `bucket`. held_ids: set[str]. title_index:
    {str(bill_id): {title, description, ...}}. Order guarantees an unresolvable
    target (no title snapshot) can never be classified `candidate`."""
    out = []
    for r in relations:
        tgt = r["target_bill_id"]
        if tgt in held_ids:
            bucket = "held"
        elif tgt not in title_index:
            bucket = "unresolvable"
        elif election_match(title_index[tgt], terms, excludes):
            bucket = "straggler"
        else:
            bucket = "candidate"
        out.append({**r, "bucket": bucket})
    return out


# --- loaders (str() coercion happens here) ----------------------------------

def load_held_ids(path: str = DIMENSION) -> set:
    return {str(b["state_bill_id"]) for b in json.load(open(path, encoding="utf-8"))}


def load_title_index(path: str = MASTERLIST) -> dict:
    """Flatten {state: [{bill_id, number, title, description}]} to
    {str(bill_id): {title, description, number, state}} across all states."""
    corpus = json.load(open(path, encoding="utf-8"))
    idx: dict[str, dict] = {}
    for state, bills in corpus.items():
        for b in bills:
            if b.get("bill_id") is None:
                continue
            idx[str(b["bill_id"])] = {
                "title": b.get("title"),
                "description": b.get("description"),
                "number": b.get("number"),
                "state": state,
            }
    return idx


def load_sasts(path: str = SASTS) -> dict:
    return json.load(open(path, encoding="utf-8"))


# --- reporting --------------------------------------------------------------

def _snapshot_provenance() -> str:
    """The commit the held set was read at, so a mid-probe data commit is visible.
    Kept in the report, never the artifact, so the bytes stay stable."""
    try:
        head = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                       text=True).strip()
        last = subprocess.check_output(
            ["git", "log", "-1", "--format=%h %ci", "--", DIMENSION], text=True).strip()
        return f"HEAD {head}; {DIMENSION} last written at {last}"
    except Exception:
        return "(git provenance unavailable)"


def _stratified_sample(cands: list[dict], n: int = 25) -> list[dict]:
    """Deterministic stratified sample by relation type: proportional per type,
    each stratum sorted by (state, target_bill_number). Used only when the
    candidate bucket exceeds n."""
    by_type: dict[str, list] = defaultdict(list)
    for c in cands:
        by_type[c["type"]].append(c)
    total = len(cands)
    picked: list[dict] = []
    for t in sorted(by_type, key=lambda k: (-len(by_type[k]), k)):
        grp = sorted(by_type[t], key=lambda c: (c["target_state"] or "", c["target_bill_number"]))
        take = max(1, round(n * len(grp) / total))
        picked.extend(grp[:take])
    return sorted(picked, key=lambda c: (c["type"], c["target_state"] or "", c["target_bill_number"]))[:n]


def report(bucketed: list[dict], title_index: dict) -> None:
    counts = Counter(r["bucket"] for r in bucketed)
    distinct_targets = {r["target_bill_id"] for r in bucketed}

    print(f"input snapshot: {_snapshot_provenance()}")
    print(f"{len(bucketed)} relations (self-refs dropped), "
          f"{len(distinct_targets)} distinct targets\n")

    print("four-bucket table:")
    for b in BUCKETS:
        print(f"  {b:<13} {counts.get(b, 0):>4}")
    if counts.get("held", 0) <= 1:
        print("  !! held is near-zero -- suspect an id-coercion bug BEFORE reporting a finding")

    # cross-tab bucket x relation type
    types = [t for t, _ in Counter(r["type"] for r in bucketed).most_common()]
    print("\ncross-tab (bucket x relation type):")
    print("  " + " " * 13 + "".join(f"{t[:11]:>13}" for t in types) + f"{'total':>13}")
    for b in BUCKETS:
        row = [sum(1 for r in bucketed if r["bucket"] == b and r["type"] == t) for t in types]
        print(f"  {b:<13}" + "".join(f"{n:>13}" for n in row) + f"{sum(row):>13}")

    # candidates -- attach target title (the evidence), state, number, source bill
    cands = []
    for r in bucketed:
        if r["bucket"] != "candidate":
            continue
        ti = title_index.get(r["target_bill_id"], {})
        cands.append({**r,
                      "target_state": ti.get("state"),
                      "target_title": ti.get("title") or ""})
    print(f"\ncandidates (bucket 3): {len(cands)}")
    shown = cands if len(cands) <= 25 else _stratified_sample(cands)
    if len(cands) > 25:
        print(f"  (stratified sample of {len(shown)} by relation type)")
    for c in sorted(shown, key=lambda c: (c["type"], c["target_state"] or "", c["target_bill_number"])):
        src = f"{c['source_state']} {c['source_bill_number']}"
        print(f"  [{c['type']}] {c['target_state']} {c['target_bill_number']} "
              f"(from {src}): {c['target_title']}")


def main() -> int:
    config.load_env()
    st = config.load_sources()["state"]
    terms = st.get("terms", [])
    excludes = st.get("exclude_terms", [])

    sasts_corpus = load_sasts()
    held_ids = load_held_ids()
    title_index = load_title_index()

    relations = list(iter_relations(sasts_corpus))
    bucketed = bucketize(relations, held_ids, title_index, terms, excludes)
    report(bucketed, title_index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
