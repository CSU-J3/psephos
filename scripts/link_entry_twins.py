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

LINKS THE RULE DID NOT PROPOSE (Corey's rulings, 2026-10-03, R1 plans and splits, ruling 4):
  * `read_links` in config/entry_links.yaml names a link by its rows, twin first, with its
    kind (the rule's own kind when the rule makes the pair, else 'plan') and the blind read
    that passed it: a run record in docs/reads/ and the link's label there. It links only
    when that run passed tools.reader_launch's check, under the stored launcher, and reads
    the link unanimous. Its twin_rule names its kind and its read.
  * A `ruled` entry is evidence in place of that read (Corey's rulings of 2026-10-03, a
    ruling as evidence, ruling 1): who ruled, the date, the criterion in one sentence, the
    exact links it covers by their rows, twin first, and the blind reads it stands over. A
    read link that its run read but did not pass links when a ruled entry names it and
    stands over its read; its twin_rule names the ruling and the read. A ruled entry is
    refused, and --apply with it, when it does not say who ruled, when and by what
    criterion, names no reads, a read with no run record or no links, or names a link it
    does not cover (none of its reads read it) or one no read link carries.
  * Several links may share one root in a run when the root is docket text and every link
    to it carries a passing read or a ruled entry naming it. If any link to that root lacks
    both, the whole group waits, and --apply refuses while any read link lacks both.
  * `hold` in the config, when set, refuses --apply and says why (ruling 5: nothing is
    applied until Corey's line on his ten, then everything ruled in one move).

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
from collections import Counter
from pathlib import Path

import yaml

import common
import config
import db
from collectors import cl_fold
from collectors import cl_twins as tw
from tools import reader_launch as RL

LINKS = Path("config/entry_links.yaml")
REPO = Path(__file__).resolve().parents[1]
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


def _read_path(path: str) -> str:
    """A run record's path as one string, however the config spells it."""
    p = Path(path)
    return str((p if p.is_absolute() else REPO / p).resolve())


def _load_read(path: str | None) -> dict | None:
    """A blind run's record (tools.reader_launch check --out), or None."""
    if not path:
        return None
    try:
        return json.loads(Path(_read_path(path)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _label_rows(label: str | None, rows: list[int]) -> bool:
    """A read's label names the link's rows: 'TWIN>ROOT' in that order, or 'A/B' either way."""
    try:
        if ">" in label:
            return [int(x) for x in label.split(">")] == list(rows)
        return sorted(int(x) for x in label.split("/")) == sorted(rows)
    except (TypeError, ValueError):
        return False


def ruling(spec: dict, carried: set) -> dict:
    """One `ruled` entry. `why` is set when it is refused. `carried` holds every read link's
    rows, twin first."""
    r = {"by": spec.get("by"), "date": spec.get("date"), "criterion": spec.get("criterion"),
         "links": [tuple(x) if isinstance(x, (list, tuple)) else (x,) for x in spec.get("links") or []],
         "reads": sorted(_read_path(p) for p in spec.get("reads") or []), "why": None}
    recs = [_load_read(p) for p in spec.get("reads") or []]
    if not all(str(r[k] or "").strip() for k in ("by", "date", "criterion")):
        r["why"] = "it does not say who ruled, when and by what criterion"
    elif not recs:
        r["why"] = "it names no reads"
    elif None in recs:
        r["why"] = "it names a read with no run record"
    elif not r["links"]:
        r["why"] = "it names no links"
    for rows in r["links"]:
        if r["why"]:
            break
        name = ">".join(map(str, rows))
        if not any(_label_rows(label, list(rows)) for rec in recs for label in rec.get("pairs") or {}):
            r["why"] = f"it names a link it does not cover: {name}"
        elif rows not in carried:
            r["why"] = f"it names a link no read link carries: {name}"
    return r


def read_link(spec: dict, byid: dict, launcher_sha: str, rulings: list | tuple = ()) -> dict:
    """One `read_links` entry as a link. `why` is set when it carries neither a passing read
    nor a ruled entry that names it and stands over its read."""
    rows = list(spec.get("rows") or [])
    x = {"rows": rows, "kind": spec.get("kind"), "read": spec.get("read"),
         "label": spec.get("label"), "ruled": spec.get("ruled"), "why": None}
    a, b = (byid.get(r) for r in rows) if len(rows) == 2 else (None, None)
    if a is None or b is None or a["cl_entry_id"] is None or b["cl_entry_id"] is None:
        x["why"] = "a row not held, or not attached to an object"
        return x
    x.update(case_id=a["case_id"], entry_at=a["entry_at"], relation=None,
             objects=[a["cl_entry_id"], b["cl_entry_id"]], texts=[a["description"], b["description"]],
             twin=a["cl_entry_id"], entry=b["cl_entry_id"])
    x["by"] = f"{x['kind']}: blind read {Path(x['read'] or '').name} {x['label']}"
    rule_kind = next((k for s, l, k in tw.edges_for_day([a, b]) if {s, l} == set(rows)), None) or "plan"
    rec = _load_read(x["read"])
    if x["twin"] == x["entry"]:
        x["why"] = "one object"
    elif (a["case_id"], a["entry_at"]) != (b["case_id"], b["entry_at"]):
        x["why"] = "not one docket and day"
    elif x["kind"] != rule_kind:
        x["why"] = f"kind {x['kind']}, where the rule's is {rule_kind}"
    elif rec is None:
        x["why"] = "no run record"
    elif rec.get("ok") is not True:
        x["why"] = "its run failed the check"
    elif (rec.get("launcher") or {}).get("sha256") != launcher_sha:
        x["why"] = "not read under the stored launcher"
    elif not _label_rows(x["label"], rows):
        x["why"] = "its label names other rows"
    elif x["label"] not in (rec.get("pairs") or {}):
        x["why"] = "its run did not read it"
    elif rec["pairs"][x["label"]].get("outcome") != "unanimous":
        named = [r for r in rulings if r["why"] is None and tuple(rows) in r["links"]]
        over = [r for r in named if _read_path(x["read"]) in r["reads"]]
        if over:
            x["ruling"] = f"{over[0]['by']}, {over[0]['date']}"
            x["by"] = (f"{x['kind']}: ruled by {x['ruling']}, over blind read "
                       f"{Path(x['read']).name} {x['label']}")
        elif named:
            x["why"] = "its read did not pass, and the ruling naming it stands over other reads"
        else:
            x["why"] = "its read did not pass"
    return x


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

    # Links the rule did not propose, each carrying a passing blind read or a ruled entry in
    # its place. A refusal wins, then an existing link; a link with neither waits; a read link
    # settles a rule pair that waited for a person.
    out["unread"] = []
    launcher_sha = RL.launcher()["sha256"]
    carried = {tuple(s.get("rows") or []) for s in links.get("read_links") or []}
    rulings = [ruling(s, carried) for s in links.get("ruled") or []]
    out["ruled_refused"] = [r for r in rulings if r["why"]]
    rule_links = {frozenset(x["objects"]) for x in out["link"]}
    for spec in links.get("read_links") or []:
        x = read_link(spec, byid, launcher_sha, rulings)
        key = frozenset(x.get("objects") or [])
        if x.get("twin") is None:
            out["unread"].append(x)
        elif tuple(sorted(x["rows"])) in refused_rows or key in refused_objs:
            out["refused"].append(x)
        elif objects.get(x["twin"], {}).get("twin_of") == x["entry"]:
            x["by"] = objects[x["twin"]]["twin_rule"]
            out["linked_already"].append(x)
        elif x["why"]:
            out["unread"].append(x)
        elif key not in rule_links:
            x["relation"] = relation(*x["rows"])
            out["person"] = [p for p in out["person"] if frozenset(p["objects"]) != key]
            out["link"].append(x)
    # A group of links sharing one root waits whole when any link to that root lacks both.
    held_roots = {x["entry"] for x in out["unread"] if x.get("entry") is not None}
    for x in [y for y in out["link"] if y.get("read") and y["entry"] in held_roots]:
        out["link"].remove(x)
        x["why"] = "another link to its root lacks a passing read or a ruling"
        out["unread"].append(x)

    # No chains: a twin must not already be an entry, an entry must not be a twin, and no
    # object may be in two links this run. Those go to a person instead. The one exception:
    # several links may share a root that is docket text when every one carries a passing read
    # or a ruled entry naming it.
    roots = {o["twin_of"] for o in objects.values() if o["twin_of"] is not None}
    twins = {cid for cid, o in objects.items() if o["twin_of"] is not None}
    as_twin = Counter(x["twin"] for x in out["link"])
    as_root = Counter(x["entry"] for x in out["link"])
    keep = []
    for x in out["link"]:
        t, r = x["twin"], x["entry"]
        chain = (t in roots or t in twins or r in twins
                 or as_twin[t] > 1 or as_root[t] > 0 or as_twin[r] > 0)
        if not chain and as_root[r] > 1:
            group = [y for y in out["link"] if y["entry"] == r]
            chain = not (all(y.get("read") for y in group)
                         and objects.get(r, {}).get("desc_source") == "entry")
        (out["would_chain"] if chain else keep).append(x)
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
                  "person", "ruled_missing", "ruled_refused", "unread"):
            print(f"  {k:15} {len(p[k])}")
        for r in p["ruled_refused"]:
            print(f"    ruled entry ({r['by']}, {r['date']}): {r['why']}")
        for x in p["unread"]:
            print(f"    read link {x.get('label')}: {x['why']}")
        if links.get("hold"):
            print(f"  HELD: {links['hold']}")
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
        if links.get("hold"):
            why = f"held: {links['hold']}"
        elif chk.get("result") != "pass":
            why = "no reader's check recorded as a pass"
        elif not covers(sample_pool(p, rule), chk):
            why = ("the recorded pairs are no longer the rule's whole pool" if chk.get("full")
                   else "the recorded seed no longer draws the recorded pairs from the rule's pool")
        elif through and chk.get("walks_through") and through > chk["walks_through"]:
            why = "a docket was walked after the check; draw and read it again"
        elif p["ruled_missing"]:
            why = f"{len(p['ruled_missing'])} asserted pair(s) match nothing the rule sees now"
        elif p["ruled_refused"]:
            why = f"ruled entries refused: {len(p['ruled_refused'])}"
        elif p["unread"]:
            why = f"{len(p['unread'])} read link(s) lack a passing blind read or a ruling"
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
