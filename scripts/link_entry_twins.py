"""Link tier-2 twins: two CourtListener objects that describe one minute entry (R1 step c,
Corey's rulings of 2026-09-30, ruling 3). Dry-run by default.

What it does, in order:
  1. Runs the D0's strict-B rule (collectors/cl_twins.py) over every held row, and dates
     each pair's two rows to collector runs by the id bracket.
  2. Maps each pair's rows to their CourtListener objects (the id backfill's work).
       one object    -> no link: it is one entry re-described (tier 1), already folded
       an id missing -> no link yet: a row the walk has not reached or left unattached
       two objects   -> a candidate
  3. A same-run candidate is linked by the rule, unless config/entry_links.yaml refuses it.
     A cross-run or undetermined one waits for a person, and is linked only when listed
     under `asserted` there.
  4. The long-form object is the entry; the short form's `twin_of` names it (ruling 2's
     hybrid: the long form survives a tier-2 pair).

Refusals:
  * --apply refuses while `checked` in config/entry_links.yaml is empty: the reader's check
    of a random 20 is what the rule is relied on after (ruling 3). --sample writes those 20.
  * an existing link is never overwritten; --unlink clears one (and its rule and time),
    the reversal ruling 3 requires. Add the pair to `refused` so the rule does not remake it.

Usage (repo root):
    python -m scripts.link_entry_twins                    # dry run: counts and the plan
    python -m scripts.link_entry_twins --sample 20 OUT.json [--seed N]
    python -m scripts.link_entry_twins --person OUT.json  # the pairs that wait for a person
    python -m scripts.link_entry_twins --apply            # link, commit
    python -m scripts.link_entry_twins --unlink CL_ENTRY_ID [--apply]
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import yaml

import common
import config
import db
from collectors import cl_twins as tw

LINKS = Path("config/entry_links.yaml")


def load_links(path: Path = LINKS) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def plan(conn, links: dict) -> dict:
    """Everything the rule sees, classified. Reads only."""
    rows = [dict(r) for r in conn.execute(
        "SELECT id, case_id, entry_at, description, document_url, cl_entry_id "
        "FROM case_entries ORDER BY id").fetchall()]
    byid = {r["id"]: r for r in rows}
    # The four channels the D0 dated runs by (news was not dumped), so the rule's 256
    # same-run pairs are the D0's own.
    fetched = [r["fetched_at"] for r in conn.execute(
        "SELECT fetched_at FROM items WHERE channel IN "
        "('litigation', 'state', 'legislation', 'executive')").fetchall()]
    item_time = {r["content_hash"]: r["fetched_at"] for r in conn.execute(
        "SELECT content_hash, fetched_at FROM items WHERE channel = 'litigation'").fetchall()}
    irt = {}
    for r in rows:
        h = common.content_hash(r["case_id"], r["entry_at"], r["description"])
        if h in item_time:
            irt[r["id"]] = item_time[h]
    clock = tw.RunClock(fetched, irt)
    objects = {r["cl_entry_id"]: dict(r) for r in conn.execute(
        "SELECT cl_entry_id, case_id, description, current_row, held, twin_of, twin_rule, "
        "entry_number, time_filed, date_created, desc_source FROM cl_entries").fetchall()}

    refused = {tuple(sorted(p["rows"])) for p in links.get("refused") or []}
    asserted = {tuple(sorted(p["rows"])): p.get("ruled") for p in links.get("asserted") or []}
    kept, amb = tw.strict_b(rows)
    out = {"edges": len(kept), "ambiguous_short": len(amb), "one_object": [], "unattached": [],
           "refused": [], "link": [], "person": [], "linked_already": []}
    for a, b, kind in kept:
        ra, rb = byid[a], byid[b]
        pair = {"rows": [a, b], "kind": kind, "case_id": ra["case_id"], "entry_at": ra["entry_at"],
                "relation": clock.relation(a, b),
                "objects": [ra["cl_entry_id"], rb["cl_entry_id"]],
                "texts": [ra["description"], rb["description"]]}
        if ra["cl_entry_id"] is None or rb["cl_entry_id"] is None:
            out["unattached"].append(pair)
        elif ra["cl_entry_id"] == rb["cl_entry_id"]:
            out["one_object"].append(pair)
        elif tuple(sorted((a, b))) in refused:
            out["refused"].append(pair)
        elif objects.get(ra["cl_entry_id"], {}).get("twin_of") or \
                objects.get(rb["cl_entry_id"], {}).get("twin_of"):
            out["linked_already"].append(pair)
        elif pair["relation"] == "same-run":
            pair["by"] = links.get("rule") or tw.RULE
            out["link"].append(pair)
        elif tuple(sorted((a, b))) in asserted:
            pair["by"] = f"asserted: {asserted[tuple(sorted((a, b)))]}"
            out["link"].append(pair)
        else:
            out["person"].append(pair)
    out["objects"] = objects
    return out


def _root(pair: dict, objects: dict) -> tuple[int, int]:
    """(twin, entry): the long form is the entry. Two long forms: the longer text, then
    the lower id."""
    (a, b), (ta, tb) = pair["objects"], pair["texts"]
    if pair["kind"] in ("short_long", "type_only"):
        return a, b                      # edges are (short, long)
    la, lb = len(tw.ntext(ta)), len(tw.ntext(tb))
    return (a, b) if (la, -a) < (lb, -b) else (b, a)


def _fingerprint(o: dict | None) -> dict:
    if not o:
        return {}
    return {k: o.get(k) for k in ("cl_entry_id", "entry_number", "time_filed", "date_created",
                                  "desc_source", "held", "current_row")}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    apply = "--apply" in argv
    config.load_env()
    conn = db.connect()
    try:
        links = load_links()
        if "--unlink" in argv:
            cl_id = int(argv[argv.index("--unlink") + 1])
            o = conn.execute("SELECT twin_of, twin_rule, twin_at FROM cl_entries "
                             "WHERE cl_entry_id = ?", (cl_id,)).fetchone()
            if o is None or o["twin_of"] is None:
                print(f"{cl_id}: not linked; nothing to undo")
                return 0
            print(f"{cl_id}: twin of {o['twin_of']} by '{o['twin_rule']}' at {o['twin_at']}")
            if not apply:
                print("  DRY-RUN -- re-run with --apply to clear it. Add the pair to `refused` "
                      "in config/entry_links.yaml so the rule does not remake it.")
                return 0
            conn.execute("UPDATE cl_entries SET twin_of = NULL, twin_rule = NULL, twin_at = NULL "
                         "WHERE cl_entry_id = ?", (cl_id,))
            conn.commit()
            print("  cleared, committed")
            return 0

        p = plan(conn, links)
        print(f"strict-B edges {p['edges']} (ambiguous short rows {p['ambiguous_short']})")
        for k in ("one_object", "unattached", "refused", "linked_already", "link", "person"):
            print(f"  {k:15} {len(p[k])}")
        rel = {}
        for x in p["link"] + p["person"]:
            rel[x["relation"]] = rel.get(x["relation"], 0) + 1
        print(f"  two-object candidates by run: {rel}")

        if "--sample" in argv:
            n = int(argv[argv.index("--sample") + 1])
            path = Path(argv[argv.index("--sample") + 2])
            seed = int(argv[argv.index("--seed") + 1]) if "--seed" in argv else 20260930
            pool = [x for x in p["link"] if x["by"] == (links.get("rule") or tw.RULE)]
            pick = random.Random(seed).sample(pool, min(n, len(pool)))
            for x in pick:
                x["fingerprints"] = [_fingerprint(p["objects"].get(o)) for o in x["objects"]]
            path.write_text(json.dumps({"seed": seed, "pool": len(pool), "pairs": pick},
                                       indent=1, ensure_ascii=False), encoding="utf-8")
            print(f"  sample of {len(pick)} from {len(pool)} (seed {seed}) -> {path}")
        if "--person" in argv:
            path = Path(argv[argv.index("--person") + 1])
            for x in p["person"]:
                x["fingerprints"] = [_fingerprint(p["objects"].get(o)) for o in x["objects"]]
            path.write_text(json.dumps(p["person"], indent=1, ensure_ascii=False), encoding="utf-8")
            print(f"  {len(p['person'])} pair(s) for a person -> {path}")

        if not apply:
            print("\n  DRY-RUN -- nothing written.")
            return 0
        if not links.get("checked"):
            print("\n  REFUSED: config/entry_links.yaml has no recorded reader's check "
                  "(ruling 3: a random 20 is read before the rule is relied on).")
            return 2
        db.require_remote(conn, "linking tier-2 twins")
        now = common.now_iso()
        n = 0
        for x in p["link"]:
            twin, entry = _root(x, p["objects"])
            cur = conn.execute(
                "UPDATE cl_entries SET twin_of = ?, twin_rule = ?, twin_at = ? "
                "WHERE cl_entry_id = ? AND twin_of IS NULL AND ? NOT IN "
                "(SELECT cl_entry_id FROM cl_entries WHERE twin_of IS NOT NULL)",
                (entry, x["by"], now, twin, entry))
            n += cur.rowcount
        conn.commit()
        print(f"\n  linked {n} of {len(p['link'])}, committed")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
