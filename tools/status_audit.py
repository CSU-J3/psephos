"""Measure how far `cases.status` has drifted from CourtListener.

`cases.status` is write-once. It is set in exactly one place --
`collectors.litigation.upsert_case`, inside the `if docket is not None:` branch --
so it is written only on a FRESH RESOLVE and never again. Every reuse run leaves it
untouched, and reuse is the steady state, not an edge case: both 2026-08-10 runs
polled 34 dockets and printed `incremental` for all 34 with zero resolve lines, so
`status` was not written once across either run. A case that terminated after its
first resolve therefore still reads `pending` today, indefinitely. This tool measures
how many, and by how much.

It measures ONLY that: whether the stored value still matches what the mapping would
produce today. It shares `case_status` with the collector rather than paraphrasing it,
so it CANNOT catch a bug in the mapping itself -- if `date_terminated` were the wrong
field to key on, audit and collector would be wrong together and this would report
clean. That is the right trade here because this is a one-shot measurement feeding a
decision about write policy, and the failure mode it targets is stale rows, not a
wrong mapping. Do not read a clean result as evidence the expression is correct.

Input is data/cases.json (the committed snapshot, 40 rows) -- NOT Turso. Like
tools/sasts_dump, the property is no database CONNECTION, not no import:
`collectors.litigation` pulls in `db` at module level, and importing it for
`case_status` and `PAGE_THROTTLE` is the point -- a copied constant or a copied
expression is the thing being avoided.

One request per row, 40 once, against the 20/min throttle. The route is the by-id
detail form, `GET {base}/dockets/{id}/`, confirmed live on the first response:
unlike the list form `resolve_docket` uses (`/dockets/?docket_number=&court=`, which
wraps in `results`), the detail route returns the docket object FLAT at the top level
with `id`, `date_terminated` and `date_filed` as direct keys. Every case_id in the
snapshot is numeric, so all 40 are reachable by this route.

The `seeded` column is the union of config/sources.yaml -> litigation.seed_cases and
data/doj_cases.json -- the list `litigation.main()` actually iterates -- joined on
`(docket_number, court)`. Not the tracker artifact alone: that returns 32 seeded and
shows the two config seeds as unseeded, which reads as abandonment when they are
polled every run. The join key is exact by construction, since `upsert_case` writes
`"court": seed.get("court")` straight off the seed.

Byte-stability is NOT a property of this artifact, unlike tools/sasts_dump. It
measures a moving upstream value: re-running it after a docket terminates SHOULD
diff, and that diff is the measurement rather than a bug to swallow.

Run from the repo root:  python -m tools.status_audit
"""
from __future__ import annotations

import json
import os

import common
import config
from collectors.litigation import PAGE_THROTTLE, USER_AGENT, case_status

IN_CASES = "data/cases.json"
IN_TRACKER = "data/doj_cases.json"
OUT = "data/status_audit.json"

# Handoff 26's independently-derived unseeded set, as a join-key cross-check. If the
# derived set differs from this, the (docket_number, court) join is wrong and the
# status numbers below it are not worth reading.
EXPECTED_UNSEEDED = {"71453026", "71453646", "71980724", "71982149", "72156765", "72334676"}


def load_cases(path: str = IN_CASES) -> list[dict]:
    """The snapshot rows, minus `timeline` -- this unit needs only the case fields."""
    keep = ("case_id", "caption", "court", "docket_number", "status", "superseded_by")
    return [{k: row.get(k) for k in keep}
            for row in json.load(open(path, encoding="utf-8"))]


def seeded_keys(tracker_path: str = IN_TRACKER) -> set[tuple[str, str]]:
    """(docket_number, court) for every seed `litigation.main()` iterates: the config
    seed_cases plus the tracker artifact. 2 + 32 = 34."""
    seeds = list(config.load_sources()["litigation"].get("seed_cases", []))
    seeds += json.load(open(tracker_path, encoding="utf-8"))
    return {(s.get("docket_number"), s.get("court")) for s in seeds}


def fetch_docket(base: str, headers: dict, case_id: str) -> dict:
    """One request, by-id detail route -- returns the docket object flat (no
    `results` envelope; see the module docstring)."""
    return common.http_get(f"{base}/dockets/{case_id}/",
                           headers=headers, throttle=PAGE_THROTTLE)


def audit(base: str, headers: dict, rows: list[dict], seeded: set[tuple[str, str]]) -> dict:
    """One request per row. Per-row try/except so a single failed lookup is recorded
    and never sinks the run (same discipline as tools/sasts_dump). `date_terminated`
    is kept verbatim, including None."""
    out: list[dict] = []
    failed: list[str] = []
    for row in rows:
        cid = str(row["case_id"])
        try:
            docket = fetch_docket(base, headers, cid)
        except Exception as exc:
            failed.append(cid)
            print(f"  {cid} {row['caption'][:40]}: lookup failed -- {exc}")
            continue
        live = case_status(docket)
        out.append({
            "case_id": cid,
            "caption": row.get("caption"),
            "court": row.get("court"),
            "docket_number": row.get("docket_number"),
            "stored_status": row.get("status"),
            "live_status": live,
            "date_terminated": docket.get("date_terminated"),
            "agrees": row.get("status") == live,
            "seeded": (row.get("docket_number"), row.get("court")) in seeded,
            "superseded_by": row.get("superseded_by"),
        })
    out.sort(key=lambda r: r["case_id"])
    failed.sort()
    return {"rows": out, "failed": failed}


def write(result: dict, out: str = OUT) -> None:
    """Sorted by case_id; trailing newline for POSIX. Not byte-stable by design --
    `date_terminated` moves upstream."""
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")


def report(result: dict, total: int) -> None:
    rows, failed = result["rows"], result["failed"]
    disagree = [r for r in rows if not r["agrees"]]
    stale_pending = [r for r in disagree
                     if r["stored_status"] == "pending" and r["live_status"] == "terminated"]
    other = [r for r in disagree if r not in stale_pending]
    derived_unseeded = {r["case_id"] for r in rows if not r["seeded"]}

    print(f"wrote {OUT}")
    print(f"  {len(rows)}/{total} rows read, {len(failed)} lookup failure(s)"
          + (f": {', '.join(failed)}" if failed else ""))

    print("\n  join-key cross-check (handoff 26 predicts 6 unseeded):")
    print(f"    {len(rows) - len(derived_unseeded)} seeded / {len(derived_unseeded)} unseeded")
    if derived_unseeded == EXPECTED_UNSEEDED:
        print("    MATCHES the expected set -- join key is right")
    else:
        print("    *** MISMATCH -- join key is wrong, do NOT read the status numbers below")
        print(f"    derived-only: {sorted(derived_unseeded - EXPECTED_UNSEEDED)}")
        print(f"    expected-only: {sorted(EXPECTED_UNSEEDED - derived_unseeded)}")

    print(f"\n  {len(disagree)}/{len(rows)} disagree "
          f"({len(stale_pending)} stored pending -> live terminated, "
          f"{len(other)} other direction)")

    print("\n  THE DEFECT -- stored `pending`, CourtListener has a date_terminated:")
    if not stale_pending:
        print("    (none)")
    for r in sorted(stale_pending, key=lambda r: r["date_terminated"] or ""):
        print(f"    {r['case_id']:10} terminated {r['date_terminated']}  "
              f"seeded={str(r['seeded']):5} sup={str(r['superseded_by'] or '-'):9} "
              f"{r['court'][:30]:30} {r['caption'][:34]}")
    if other:
        print("\n  other direction (stored terminated, live pending):")
        for r in other:
            print(f"    {r['case_id']:10} {r['court'][:30]:30} {r['caption'][:40]}")

    print("\n  full table:")
    print(f"    {'case_id':10} {'stored':11} {'live':11} {'date_term':11} "
          f"{'seed':5} {'sup':9} caption")
    for r in rows:
        flag = "  " if r["agrees"] else "<<"
        print(f" {flag} {r['case_id']:10} {r['stored_status'] or '-':11} {r['live_status']:11} "
              f"{r['date_terminated'] or '-':11} {str(r['seeded']):5} "
              f"{str(r['superseded_by'] or '-'):9} {(r['caption'] or '')[:38]}")

    print("\n  rows of interest:")
    for cid, why in (("72334676", "KY district, handoff-25 orphan"),
                     ("72156765", "VA district, handoff-25 orphan"),
                     ("71982149", "NM district, handoff-25 orphan"),
                     ("72053306", "the row handoff 14's verify() passed on")):
        r = next((x for x in rows if x["case_id"] == cid), None)
        if r is None:
            print(f"    {cid}  NOT IN SNAPSHOT ({why})")
            continue
        verdict = "agrees" if r["agrees"] else "STALE"
        print(f"    {cid}  stored={r['stored_status']:10} live={r['live_status']:10} "
              f"date_terminated={r['date_terminated'] or '-':11} {verdict:6}  -- {why}")

    print(f"\n  artifact {os.path.getsize(OUT) / 1000:.1f} KB")


def main() -> int:
    config.load_env()
    lit = config.load_sources()["litigation"]
    base = lit["api"]["base"].rstrip("/")
    headers = {"Authorization": f"Token {config.require_env(lit['api']['key_env'])}",
               "User-Agent": USER_AGENT}

    rows = load_cases()
    seeded = seeded_keys()
    print(f"status_audit: {len(rows)} snapshot rows, {len(seeded)} seed keys, "
          f"1 request each at {PAGE_THROTTLE}s spacing")
    result = audit(base, headers, rows, seeded)
    write(result)
    report(result, len(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
