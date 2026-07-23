"""Dump the configured states' LegiScan masterlists to a byte-stable corpus for
OFFLINE election-filter tuning. Re-run whenever the term list is revisited -- after
this one dump, every filter variant is a zero-API experiment against a fixed corpus.

Stripped to the four fields election_match reads: bill_id, number, title, description.
Deliberately NOT the full masterlist entry -- status / status_date / last_action /
last_action_date churn as bills advance, so committing them would re-diff the artifact
on nearly every dump even when nothing filter-relevant moved. Title/description are
stable, so the stripped corpus diffs only when the upstream sessions actually change.

One getMasterList per state (reuses collectors.state.get_masterlist, which handles the
numeric-string-key iteration and the `session` skip). Nine queries.

Run from the repo root:  python -m tools.masterlist_corpus
"""
from __future__ import annotations

import json
import os

import config
from collectors.state import get_masterlist, THROTTLE

OUT = "data/masterlist_corpus.json"
FIELDS = ("bill_id", "number", "title", "description")


def build(base: str, key: str, states: list[str]) -> dict:
    """{state: [ {bill_id, number, title, description}, ... sorted by bill_id ]}."""
    corpus: dict[str, list[dict]] = {}
    for state in states:
        master = get_masterlist(base, key, state, THROTTLE)
        bills = [{f: m.get(f) for f in FIELDS} for m in master if m.get("bill_id") is not None]
        bills.sort(key=lambda b: b["bill_id"])
        corpus[state] = bills
    return corpus


def main() -> int:
    config.load_env()
    st = config.load_sources()["state"]
    base = st["api"]["base"].rstrip("/") + "/"
    states = st.get("states", [])
    key = config.require_env(st["api"]["key_env"])

    corpus = build(base, key, states)

    # sorted keys + no wall-clock stamp -> byte-stable; a trailing newline for POSIX.
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(corpus, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")

    total = 0
    print(f"wrote {OUT}")
    print(f"  {'st':<3} {'bills':>6} {'w/desc':>7} {'desc!=title':>12}")
    for state in sorted(corpus):
        bills = corpus[state]
        total += len(bills)
        with_desc = sum(1 for b in bills if (b.get("description") or "").strip())
        diff_desc = sum(
            1 for b in bills
            if (b.get("description") or "").strip()
            and (b.get("description") or "").strip() != (b.get("title") or "").strip()
        )
        print(f"  {state:<3} {len(bills):>6} {with_desc:>7} {diff_desc:>12}")
    size = os.path.getsize(OUT)
    print(f"  total: {total} bills across {len(corpus)} states; artifact {size/1_000_000:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
