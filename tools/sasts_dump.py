"""Dump the `sasts` relations of every bill in the state_bills dimension to a
byte-stable corpus, for the OFFLINE sasts probe (handoff 11, 5b-b).

`sasts` is LegiScan's asserted relation from a held voting bill outward. A sast
target that FAILS the election filter is the one high-precision state-vehicle
candidate the 5b-b spike left open: the tool's own claim that a voting bill is
related to a bill that isn't about voting. This dump is Part A; tools/sasts_join
joins it offline against the dimension and the masterlist title snapshot.

Input is data/state_bills.json (the committed snapshot, 455 bills) -- NOT Turso.
Using the snapshot means this whole unit needs no database connection anywhere.
One getBill per bill (reuses collectors.state.get_bill), ~455 queries once,
against a 30k/month tier. Steady-state collection is untouched.

Live sasts element shape, confirmed off the first probe (kept VERBATIM in the
artifact, no field-name assumption):
  {type_id, type, sast_bill_number, sast_bill_id}   -- sast_bill_id is an int.

Byte-stability: states sorted, bills sorted by bill_id, sast elements sorted by
(type_id, sast_bill_id), no wall-clock stamp. Re-running against unchanged
upstream relations is byte-identical. The one exception is `skipped`: a run with
a different ERROR set will diff there, and that is a real difference worth
surfacing, not a byte-stability bug to swallow (a skip must be distinguishable
from a bill that genuinely has no relations).

Run from the repo root:  python -m tools.sasts_dump
"""
from __future__ import annotations

import json
import os
from collections import Counter

import config
from collectors.state import get_bill, THROTTLE

IN = "data/state_bills.json"
OUT = "data/sasts_corpus.json"


def load_ids(path: str = IN) -> list[str]:
    """The 455 dimension ids -- state_bill_id is the LegiScan numeric bill_id as
    text; kept as text here so the skipped list matches the input verbatim."""
    return [str(b["state_bill_id"]) for b in json.load(open(path, encoding="utf-8"))]


def dump(base: str, key: str, ids: list[str], throttle: float) -> dict:
    """getBill each id, keep only carriers (non-empty sasts). Per-bill try/except:
    an ERROR-status payload (get_bill raises) or a malformed/empty response is
    recorded in `skipped` and never sinks the run. Returns
    {carriers: {state: [ {bill_id, bill_number, sasts:[...]} ]}, skipped: [...]}."""
    carriers: dict[str, list[dict]] = {}
    skipped: list[str] = []
    for bid in ids:
        try:
            bill = get_bill(base, key, bid, throttle)
        except Exception:
            skipped.append(bid)
            continue
        if not bill or not bill.get("bill_id"):
            skipped.append(bid)          # empty/malformed -- not the same as "no relations"
            continue
        sasts = bill.get("sasts") or []
        if not sasts:
            continue                     # genuinely no relations: dropped, not skipped
        state = bill.get("state") or ""
        carriers.setdefault(state, []).append({
            "bill_id": bill["bill_id"],
            "bill_number": bill.get("bill_number") or "",
            # verbatim relation fields, deterministically ordered for byte-stability
            "sasts": sorted(sasts, key=lambda s: (s.get("type_id") or 0, s.get("sast_bill_id") or 0)),
        })
    for state in carriers:
        carriers[state].sort(key=lambda b: b["bill_id"])
    skipped.sort(key=lambda x: int(x) if x.isdigit() else x)
    return {"carriers": carriers, "skipped": skipped}


def write(corpus: dict, out: str = OUT) -> None:
    """sorted keys + no wall-clock stamp -> byte-stable; trailing newline for POSIX."""
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(corpus, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")


def report(corpus: dict, total_ids: int) -> None:
    carriers = corpus["carriers"]
    skipped = corpus["skipped"]
    relations = [s for bills in carriers.values() for b in bills for s in b["sasts"]]
    n_carriers = sum(len(bills) for bills in carriers.values())
    distinct_targets = {s.get("sast_bill_id") for s in relations}
    types = Counter(s.get("type") or f"type_id={s.get('type_id')}" for s in relations)

    print(f"wrote {OUT}")
    print(f"  {n_carriers} carriers / {total_ids} bills "
          f"({100 * n_carriers / total_ids:.0f}%; spike predicts ~28%), "
          f"{len(skipped)} skipped")
    print(f"  {len(relations)} relations, {len(distinct_targets)} distinct targets")
    print("  relation-type histogram:")
    for t, n in types.most_common():
        print(f"    {n:>4}  {t}")
    size = os.path.getsize(OUT)
    print(f"  artifact {size/1000:.1f} KB")


def main() -> int:
    config.load_env()
    st = config.load_sources()["state"]
    base = st["api"]["base"].rstrip("/") + "/"
    key = config.require_env(st["api"]["key_env"])

    ids = load_ids()
    corpus = dump(base, key, ids, THROTTLE)
    write(corpus)
    report(corpus, len(ids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
