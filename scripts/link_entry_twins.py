"""Link tier-2 twins: two CourtListener objects that describe one minute entry (R1 step c,
Corey's rulings of 2026-09-30, ruling 3). Dry-run by default.

What it does, in order:
  1. Runs the D0's strict-B rule (collectors/cl_twins.py) over every held row, entry-aware,
     and dates each pair's two rows to collector runs by the id bracket.
  2. Maps each pair to its CourtListener objects (the id backfill's work).
       one object     -> no link: one entry re-described (tier 1), already folded
       an id missing  -> waits: a row the walk has not reached or left unattached
       two objects    -> a candidate
  3. A same-run candidate is linked by the rule, unless config/entry_links.yaml refuses it.
     A cross-run or undetermined one waits for a person and is linked only when listed
     under `asserted` there. So does a 'first-load' one: same-run, but in a run the
     docket's first load may have been, which fetched the whole docket at once and so says
     nothing about the pair (cl_twins.pair_relation; Corey, 2026-10-02). A candidate that
     would make a chain (its short side is already another pair's entry, or two candidates
     share an object) waits for a person too.
  4. The long-form object is the entry; the short form's `twin_of` names it (ruling 2's
     hybrid: the long form survives a tier-2 pair). The pair's items then fold as one entry.

THE READER'S CHECK (ruling 3: "before relying on the rule, a reader checks a random 20 of
the 256 and the result is recorded"):
  * --sample refuses until every docket holding a same-run pair has been walked, so the 20
    come from the pairs the rule will link. It draws from EVERY same-run two-object pair,
    linked or not, sorted by row ids, so the recorded seed redraws the same 20 after --apply.
    It prints the `checked` stub to record in config/entry_links.yaml.
  * --sample all reads the whole pool in place of a draw: Corey's ruling of 2026-10-02 for
    the 7 later-poll pairs, too few to draw 20 from. Its `checked` stub is `full: true`
    with no seed, and names every pair in row order.
  * --apply refuses unless `checked.result` is "pass", the check still describes the pool
    (a full read names every pair in it; a sample is what its seed redraws), and no docket
    has been walked since the check.

Refusals otherwise: an existing link is never overwritten; `asserted` entries that match
no pair the rule sees now refuse --apply (something moved under a person's ruling);
--unlink clears one link and refolds (the reversal ruling 3 requires); add the pair to
`refused` so the rule does not remake it. Everything that writes, or writes the reader's
or the person's list, runs against Turso only.

Usage (repo root):
    python -m scripts.link_entry_twins                    # dry run: counts and the plan
    python -m scripts.link_entry_twins --sample 20 OUT.json [--seed N]
    python -m scripts.link_entry_twins --sample all OUT.json   # the whole pool, no draw
    python -m scripts.link_entry_twins --person OUT.json  # the pairs that wait for a person
    python -m scripts.link_entry_twins --apply            # link, refold, commit
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
from collectors import cl_fold
from collectors import cl_twins as tw

LINKS = Path("config/entry_links.yaml")
DEFAULT_SEED = 20260930


def load_links(path: Path = LINKS) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _root(pair: dict) -> tuple[int, int]:
    """(twin, entry): the long form is the entry. Two long forms: the longer text, then
    the lower id."""
    (a, b), (ta, tb) = pair["objects"], pair["texts"]
    if pair["kind"] in ("short_long", "type_only"):
        return a, b                      # edges are (short, long)
    la, lb = len(tw.ntext(ta)), len(tw.ntext(tb))
    return (a, b) if (la, -a) < (lb, -b) else (b, a)


def plan(conn, links: dict) -> dict:
    """Everything the rule sees, classified. Reads only."""
    rows = [dict(r) for r in conn.execute(
        "SELECT id, case_id, entry_at, description, document_url, cl_entry_id "
        "FROM case_entries ORDER BY id").fetchall()]
    byid = {r["id"]: r for r in rows}
    first_row: dict = {}                 # each docket's lowest id: its first load wrote it
    for r in rows:
        first_row.setdefault(r["case_id"], r["id"])
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
    rule = links.get("rule") or tw.RULE

    def obj_key(row_pair):
        ids = [byid[r]["cl_entry_id"] for r in row_pair if r in byid]
        return frozenset(ids) if len(ids) == 2 and None not in ids else None

    refused_rows = {tuple(sorted(p["rows"])) for p in links.get("refused") or []}
    refused_objs = {k for k in (obj_key(p["rows"]) for p in links.get("refused") or []) if k}
    asserted = links.get("asserted") or []
    asserted_objs = {obj_key(p["rows"]): p.get("ruled") for p in asserted if obj_key(p["rows"])}

    def relation(a, b):
        return tw.pair_relation(clock, first_row[byid[a]["case_id"]], a, b)

    kept, amb = tw.strict_b(rows)
    out = {"edges": len(kept), "ambiguous_short": len(amb), "one_object": [], "unattached": [],
           "refused": [], "link": [], "person": [], "would_chain": [], "linked_already": [],
           "ruled_missing": []}
    seen_objs = set()
    for a, b, kind in kept:
        ra, rb = byid[a], byid[b]
        pair = {"rows": [a, b], "kind": kind, "case_id": ra["case_id"], "entry_at": ra["entry_at"],
                "relation": relation(a, b),
                "objects": [ra["cl_entry_id"], rb["cl_entry_id"]],
                "texts": [ra["description"], rb["description"]]}
        key = obj_key((a, b))
        if key is None:
            out["unattached"].append(pair)
            continue
        if len(key) == 1:
            out["one_object"].append(pair)
            continue
        seen_objs.add(key)
        twin, entry = _root(pair)
        pair["twin"], pair["entry"] = twin, entry
        if tuple(sorted((a, b))) in refused_rows or key in refused_objs:
            out["refused"].append(pair)
        elif objects.get(twin, {}).get("twin_of") == entry:
            pair["by"] = objects[twin]["twin_rule"]
            out["linked_already"].append(pair)
        elif pair["relation"] == "same-run":
            pair["by"] = rule
            out["link"].append(pair)
        elif key in asserted_objs:
            pair["by"] = f"asserted: {asserted_objs[key]}"
            out["link"].append(pair)
        else:
            out["person"].append(pair)

    # No chains: a twin must not already be an entry, an entry must not be a twin, and no
    # object may be in two links this run. Those go to a person instead.
    roots = {o["twin_of"] for o in objects.values() if o["twin_of"] is not None}
    twins = {cid for cid, o in objects.items() if o["twin_of"] is not None}
    uses: dict = {}
    for x in out["link"]:
        for o in (x["twin"], x["entry"]):
            uses[o] = uses.get(o, 0) + 1
    keep = []
    for x in out["link"]:
        if (x["twin"] in roots or x["twin"] in twins or x["entry"] in twins
                or uses[x["twin"]] > 1 or uses[x["entry"]] > 1):
            out["would_chain"].append(x)
        else:
            keep.append(x)
    out["link"] = keep
    out["ruled_missing"] = [p for p in asserted if obj_key(p["rows"]) not in seen_objs]
    out["objects"] = objects
    out["same_run_cases"] = sorted({byid[a]["case_id"] for a, b, _ in kept
                                    if relation(a, b) == "same-run"})
    return out


def sample_pool(p: dict, rule: str) -> list[dict]:
    """Every same-run two-object pair the rule links or has linked, in row order: the pool
    a recorded seed redraws from, before and after --apply."""
    pool = [x for x in p["link"] if x["by"] == rule] + \
        [x for x in p["linked_already"] if x.get("by") == rule]
    return sorted(pool, key=lambda x: tuple(sorted(x["rows"])))


def draw(pool: list[dict], n: int, seed: int) -> list[list[int]]:
    return [sorted(x["rows"]) for x in random.Random(seed).sample(pool, min(n, len(pool)))]


def covers(pool: list[dict], chk: dict) -> bool:
    """Whether a recorded check still describes the rule's pool: a full read names every
    pair in it, in row order; a sample is what its seed redraws from it."""
    pairs = [sorted(x) for x in chk.get("pairs") or []]
    if chk.get("full"):
        return [sorted(x["rows"]) for x in pool] == pairs
    return draw(pool, len(pairs), chk.get("seed", DEFAULT_SEED)) == pairs


def unwalked(conn, cases: list[str]) -> list[str]:
    walked = {r["case_id"] for r in conn.execute("SELECT case_id FROM cl_backfill").fetchall()}
    return [c for c in cases if c not in walked]


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
        rule = links.get("rule") or tw.RULE
        if "--unlink" in argv:
            cl_id = int(argv[argv.index("--unlink") + 1])
            o = conn.execute("SELECT case_id, twin_of, twin_rule, twin_at FROM cl_entries "
                             "WHERE cl_entry_id = ?", (cl_id,)).fetchone()
            if o is None or o["twin_of"] is None:
                print(f"{cl_id}: not linked; nothing to undo")
                return 0
            print(f"{cl_id}: twin of {o['twin_of']} by '{o['twin_rule']}' at {o['twin_at']}")
            if not apply:
                print("  DRY-RUN -- re-run with --apply to clear it. Add the pair to `refused` "
                      "in config/entry_links.yaml so the rule does not remake it.")
                return 0
            db.require_remote(conn, "unlinking a tier-2 twin")
            conn.execute("UPDATE cl_entries SET twin_of = NULL, twin_rule = NULL, twin_at = NULL "
                         "WHERE cl_entry_id = ?", (cl_id,))
            cl_fold.recompute_latest(conn, o["case_id"])
            conn.commit()
            cl_fold.refold_quietly(conn, o["case_id"])   # the two entries present apart again
            print("  cleared, refolded, committed")
            return 0

        p = plan(conn, links)
        print(f"strict-B edges {p['edges']} (ambiguous short rows {p['ambiguous_short']})")
        for k in ("one_object", "unattached", "refused", "linked_already", "link", "would_chain",
                  "person", "ruled_missing"):
            print(f"  {k:15} {len(p[k])}")
        waiting = unwalked(conn, p["same_run_cases"])
        if waiting:
            print(f"  {len(waiting)} docket(s) holding a same-run pair not yet walked")

        if "--sample" in argv:
            db.require_remote(conn, "the reader's sample")
            if waiting:
                print("\n  REFUSED: the sample waits for every docket holding a same-run pair "
                      "to be walked, so it is drawn from the pairs --apply would link.")
                return 2
            arg = argv[argv.index("--sample") + 1]
            path = Path(argv[argv.index("--sample") + 2])
            full = arg == "all"
            seed = None if full else (int(argv[argv.index("--seed") + 1]) if "--seed" in argv
                                      else DEFAULT_SEED)
            pool = sample_pool(p, rule)
            picked = [sorted(x["rows"]) for x in pool] if full else draw(pool, int(arg), seed)
            by_rows = {tuple(sorted(x["rows"])): x for x in pool}
            pairs = []
            for rows_ in picked:
                x = dict(by_rows[tuple(rows_)])
                x["fingerprints"] = [_fingerprint(p["objects"].get(o)) for o in x["objects"]]
                pairs.append(x)
            through = conn.execute("SELECT MAX(walked_at) FROM cl_backfill").fetchone()[0]
            stub = {"seed": seed, "pool": len(pool), "pairs": picked,
                    "walks_through": through, "result": None, "read_by": None, "on": None}
            if full:
                stub = {"full": True, **stub}
            path.write_text(json.dumps({"checked_stub": stub, "pairs": pairs}, indent=1,
                                       ensure_ascii=False), encoding="utf-8")
            print(f"  {'all' if full else f'sample of {len(picked)} from'} {len(pool)} "
                  f"({'no draw' if full else f'seed {seed}'}) -> {path}")
            print("  record in config/entry_links.yaml as `checked:` with result pass|fail:")
            print("  " + json.dumps(stub))
        if "--person" in argv:
            db.require_remote(conn, "the person's list")
            path = Path(argv[argv.index("--person") + 1])
            wait = p["person"] + p["would_chain"]
            for x in wait:
                x["fingerprints"] = [_fingerprint(p["objects"].get(o)) for o in x["objects"]]
            path.write_text(json.dumps(wait, indent=1, ensure_ascii=False), encoding="utf-8")
            print(f"  {len(wait)} pair(s) for a person -> {path}")

        if not apply:
            print("\n  DRY-RUN -- nothing written.")
            return 0
        chk = links.get("checked") or {}
        through = conn.execute("SELECT MAX(walked_at) FROM cl_backfill").fetchone()[0]
        why = None
        if chk.get("result") != "pass":
            why = "no reader's check recorded as a pass"
        elif not covers(sample_pool(p, rule), chk):
            why = ("the recorded pairs are no longer the rule's whole pool" if chk.get("full")
                   else "the recorded seed no longer draws the recorded pairs from the rule's pool")
        elif through and chk.get("walks_through") and through > chk["walks_through"]:
            why = "a docket was walked after the check; draw and read it again"
        elif p["ruled_missing"]:
            why = f"{len(p['ruled_missing'])} asserted pair(s) match nothing the rule sees now"
        if why:
            print(f"\n  REFUSED: {why} (ruling 3; config/entry_links.yaml).")
            return 2
        db.require_remote(conn, "linking tier-2 twins")
        cases = sorted({x["case_id"] for x in p["link"]})
        count = lambda c: conn.execute("SELECT COUNT(*) FROM record_entries WHERE case_id = ?",
                                       (c,)).fetchone()[0]  # noqa: E731
        before = {c: count(c) for c in cases}
        now = common.now_iso()
        n = 0
        for x in p["link"]:
            cur = conn.execute(
                "UPDATE cl_entries SET twin_of = ?, twin_rule = ?, twin_at = ? "
                "WHERE cl_entry_id = ? AND twin_of IS NULL "
                "AND ? NOT IN (SELECT cl_entry_id FROM cl_entries WHERE twin_of IS NOT NULL) "
                "AND ? NOT IN (SELECT twin_of FROM cl_entries WHERE twin_of IS NOT NULL)",
                (x["entry"], x["by"], now, x["twin"], x["entry"], x["twin"]))
            n += cur.rowcount
        for case in sorted({x["case_id"] for x in p["link"]}):
            cl_fold.recompute_latest(conn, case)    # a twin leaves record_entries
        conn.commit()
        for case in sorted({x["case_id"] for x in p["link"]}):
            cl_fold.refold_quietly(conn, case)      # the pair now presents as one entry
        print(f"\n  linked {n} of {len(p['link'])}, refolded, committed")
        # A link after the switch moves a docket's public count: the before and after
        # its dated note needs (ruling 5), printed for the record.
        for c in cases:
            print(f"  {c}: {before[c]} entries before, {count(c)} after")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
