"""Dump the configured states' LegiScan masterlists to a byte-stable corpus for
OFFLINE election-filter tuning. Re-run whenever the term list is revisited -- after
this one dump, every filter variant is a zero-API experiment against a fixed corpus.

Stripped to the four fields election_match reads: bill_id, number, title, description.
Deliberately NOT the full masterlist entry -- status / status_date / last_action /
last_action_date churn as bills advance, so committing them would re-diff the artifact
on nearly every dump even when nothing filter-relevant moved. Title/description are
stable, so the stripped corpus diffs only when the upstream sessions actually change.

One getMasterList per state (reuses collectors.state.get_masterlist, which handles the
numeric-string-key iteration and the `session` skip). Nine queries, up to 36 with retries.

GATED ON THE LEGISCAN LEDGER (handoff 98). Before any call it prints its declared worst
case against the month's remaining headroom in the Turso `legiscan_usage` ledger and
refuses (exit 1, nothing called) if it does not fit; every attempt it makes is written
back to that ledger, success or failure. So it needs Turso -- see collectors.state.open_ledger.
That ledger row is the ONE database write a tools/ file makes: it records spend against
an external allowance the cron shares, which is not the same thing as mutating the record.

Run from the repo root:  python -m tools.masterlist_corpus
"""
from __future__ import annotations

import json
import os
import sys

import config
from collectors.state import (THROTTLE, UsageMeter, cap_signal_body, get_masterlist,
                              open_ledger, record_spend_or_warn, tool_gate)

OUT = "data/masterlist_corpus.json"
FIELDS = ("bill_id", "number", "title", "description")


def build(base: str, key: str, states: list[str], meter: UsageMeter | None = None) -> dict:
    """{state: [ {bill_id, number, title, description}, ... sorted by bill_id ]}."""
    corpus: dict[str, list[dict]] = {}
    for state in states:
        master = get_masterlist(base, key, state, THROTTLE, meter)
        bills = [{f: m.get(f) for f in FIELDS} for m in master if m.get("bill_id") is not None]
        bills.sort(key=lambda b: b["bill_id"])
        corpus[state] = bills
    return corpus


def gated_build(conn, base: str, key: str, states: list[str], monthly_cap: int) -> dict | None:
    """build(), admitted by the ledger and written back to it. None when refused."""
    if not tool_gate(conn, len(states), monthly_cap, "masterlist_corpus"):
        return None
    meter = UsageMeter()
    try:
        return build(base, key, states, meter)
    finally:
        record_spend_or_warn(conn, meter, "masterlist_corpus")
        print(f"  masterlist_corpus: {meter.run_total} LegiScan attempt(s) this run")


def main() -> int:
    config.load_env()
    st = config.load_sources()["state"]
    base = st["api"]["base"].rstrip("/") + "/"
    states = st.get("states", [])
    key = config.require_env(st["api"]["key_env"])

    conn = open_ledger("masterlist_corpus")
    try:
        corpus = gated_build(conn, base, key, states, st["monthly_cap"])
    except Exception as exc:
        # build() has no per-state handler, so any failure already stops it before
        # the next call; this only says so plainly when the failure is the cap.
        body = cap_signal_body(exc)
        if body is None:
            raise
        print(f"  masterlist_corpus: LegiScan signalled its allowance is spent; stopped, "
              f"no artifact written. Body verbatim:\n{body}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    if corpus is None:
        return 1

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
