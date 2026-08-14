"""One-time backfill: fill `cases.state` for rows that predate the column (handoff 53).

WHY THIS IS ONE-TIME, AND WHY THE COLUMN DOES NOT NEED A STANDING JOB. From now on
`upsert_case` writes `state` on every seeded row, every run, off the tracker artifact.
A state's row is seeded for as long as the UW tracker carries it; when the tracker
rewrites that row to point at a successor docket, the predecessor drops out of the
seed set and nothing upserts it again -- so whatever `state` it was last written keeps
sitting there, exactly the way `superseded_by` does. Every FUTURE predecessor is
therefore filled while it is still seeded, before it ever goes quiet. Only the rows
that were already out of the seed set when the column landed can never be reached by
the collector, and there are six of them, listed below. After this runs there is no
second population to catch.

WHAT IT WRITES. Two passes, in one transaction, over the same authority the collector
uses:

  1. ARTIFACT -- every row matching data/doj_cases.json on (docket_number, court) gets
     `normalize_state(seed["state"])`, the identical value `upsert_case` will write on
     the next cron. This pass is a HEAD START, not a second authority: without it the
     column sits NULL on 32 of 40 rows until the next scheduled run, and a half-filled
     column is the kind of thing a reader takes for a finding.
  2. CHAIN -- every row with no artifact match but a `superseded_by` pointing at a row
     resolved in pass 1 inherits that successor's state. This is the pass that only
     ever has to run once, and it is the whole reason the script exists.

Measured against Turso 2026-08-13, before the column existed: 40 rows = 32 artifact +
6 chain + 2 unresolved. The six are the unpolled predecessors PA `71453026`, NH
`71453646`, MD `71980724`, NM `71982149`, VA `72156765`, KY `72334676`. Georgia's
M.D. Ga. predecessor `72053306` is NOT among them -- the tracker carries two Georgia
rows (`Georgia (1)` gamd, `Georgia (2)` gand), so it is superseded AND still seeded,
and pass 1 reaches it like any other seeded row.

THE TWO UNRESOLVED ROWS ARE THE CORRECT ANSWER, NOT A GAP. Common Cause v. DOJ and
LWV v. DHS come from config/sources.yaml, sue federal agencies, and have no state. A
NULL there is what keeps them out of every per-state view. The guard below does not
hardcode their ids: it rebuilds the config seed key set from sources.yaml and refuses
if anything ELSE fails to resolve, which is what would fire on a real orphan.

Do not read "unmatched against the artifact" as "unseeded" -- the seed set litigation
iterates is the UNION of config and artifact (34), and against the artifact alone 8
rows read unmatched. See the ordering trap in tools/coverage_audit.

Dry-run by default: prints every row AS QUERIED beside the value it would take, and
writes nothing. --apply writes and commits. Refusal-first: any guard failure aborts
the whole run with zero writes, because a half-keyed table is worse than an unkeyed one.

Run from the repo root as a module (puts the repo root on sys.path, like the collectors):
    python -m scripts.backfill_case_state            # dry-run, writes nothing
    python -m scripts.backfill_case_state --apply     # fill and commit
"""
from __future__ import annotations

import json
import sys

import config
import db
from collectors.litigation import TRACKER_ARTIFACT, normalize_state


def load_artifact(path: str = TRACKER_ARTIFACT) -> dict[tuple[str, str], dict]:
    """(docket_number, court) -> seed. Exact by construction: `upsert_case` writes
    `court` straight off the seed, so the artifact's key and the row's agree byte for
    byte. Same join key as tools/coverage_audit, for the same reason."""
    rows = json.load(open(path, encoding="utf-8"))
    return {(r.get("docket_number"), r.get("court")): r for r in rows}


def config_seed_keys() -> set[tuple[str, str]]:
    """(docket_number, court) for the config seeds only -- NOT the union seed set.
    Rebuilt from sources.yaml rather than listed here, so a third config seed is
    absorbed without editing this file and a genuine orphan still refuses."""
    seeds = config.load_sources()["litigation"].get("seed_cases", []) or []
    return {(s.get("docket_number"), s.get("court")) for s in seeds}


def resolve(conn, artifact: dict[tuple[str, str], dict]) -> list[dict]:
    """One record per `cases` row: what it holds now, what it would take, and where
    that came from. Reads only; the caller decides whether anything is written.

    Pass 2 reads the successor's resolution rather than the successor's stored column,
    so the two passes are independent of the order rows come back in and of whether
    the column has ever been written."""
    rows = conn.execute(
        "SELECT case_id, court, docket_number, status, state, superseded_by FROM cases"
    ).fetchall()
    by_id = {r["case_id"]: r for r in rows}

    # Pass 1: the artifact.
    proposed: dict[str, tuple[str | None, str]] = {}
    for r in rows:
        seed = artifact.get((r["docket_number"], r["court"]))
        if seed is not None:
            proposed[r["case_id"]] = (normalize_state(seed.get("state")), "artifact")

    # Pass 2: inherit along superseded_by, from the successor that pass 1 resolved.
    for r in rows:
        if r["case_id"] in proposed:
            continue
        succ = r["superseded_by"]
        if succ and succ in proposed and proposed[succ][0]:
            proposed[r["case_id"]] = (proposed[succ][0], f"chain <- {succ}")

    out = []
    for r in rows:
        value, source = proposed.get(r["case_id"], (None, "unresolved"))
        out.append({
            "case_id": r["case_id"],
            "court": r["court"],
            "docket_number": r["docket_number"],
            "status": r["status"],
            "current": r["state"],
            "proposed": value,
            "source": source,
            "superseded_by": r["superseded_by"],
        })
    out.sort(key=lambda x: (x["source"] == "unresolved", x["source"].startswith("chain"),
                            x["proposed"] or "", x["case_id"]))
    return out


def verify(records: list[dict], config_keys: set[tuple[str, str]]) -> list[str]:
    """Guard every row BEFORE any write. Returns the failures (empty = all pass).

    Three refusals, each for a failure that would otherwise land silently:
      * an unresolved row that is not a config seed -- a real orphan, or a chain whose
        successor did not resolve. Either way the grid would show a hole and nothing
        would say why,
      * a row matched in the artifact whose `state` is empty -- a tracker defect, and
        the one case where "resolved" and "has a value" come apart,
      * a row whose stored value already disagrees with the proposal. Re-running after
        the tracker renamed a state should stop and be looked at, not overwrite.
    """
    errs: list[str] = []
    for rec in records:
        key = (rec["docket_number"], rec["court"])
        if rec["source"] == "unresolved":
            if key not in config_keys:
                errs.append(
                    f"{rec['case_id']}: no artifact match and no resolvable successor "
                    f"({rec['court']} {rec['docket_number']}); not a config seed either")
            continue
        if not rec["proposed"]:
            errs.append(f"{rec['case_id']}: matched the artifact but its state is empty")
            continue
        if rec["current"] is not None and rec["current"] != rec["proposed"]:
            errs.append(
                f"{rec['case_id']}: stored state {rec['current']!r} != proposed "
                f"{rec['proposed']!r}; refusing to overwrite")
    return errs


def describe(records: list[dict]) -> list[str]:
    """The dry-run table: every field READ from `cases`, beside the value it would
    take and the pass that produced it. `court` and `status` appear in no input to
    this script, so printing them is the proof that the row was really read."""
    lines = [
        f"    {'case_id':<9}  {'court':<34} {'docket':<15} {'status':<11} "
        f"{'stored':<15} {'->':<3} {'proposed':<15} source",
    ]
    for r in records:
        mark = "==" if r["current"] == r["proposed"] else "->"
        lines.append(
            f"    {r['case_id']:<9}  {(r['court'] or '-'):<34} "
            f"{(r['docket_number'] or '-'):<15} {(r['status'] or '-'):<11} "
            f"{str(r['current']):<15} {mark:<3} {str(r['proposed']):<15} {r['source']}")
    return lines


def apply_states(conn, records: list[dict]) -> int:
    """Write `state` on every resolved row. Idempotent -- rewriting the same value has
    no effect, and the unresolved rows are skipped rather than written NULL, so a row
    that already carries a hand-set value cannot be cleared by a later run. Returns
    the count of rows reading their proposed value afterwards."""
    resolved = [r for r in records if r["source"] != "unresolved"]
    for r in resolved:
        conn.execute("UPDATE cases SET state = ? WHERE case_id = ?",
                     (r["proposed"], r["case_id"]))
    return sum(
        1 for r in resolved
        if (conn.execute("SELECT state FROM cases WHERE case_id = ?", (r["case_id"],))
            .fetchone() or [None])[0] == r["proposed"]
    )


def run(conn, artifact, config_keys, apply: bool) -> tuple[list[dict], list[str], int]:
    """Resolve, verify, then (only if all pass and apply) write. Refusal-first: any
    guard failure aborts with zero writes. conn-parameterized so tests drive it against
    a temp DB and never touch Turso."""
    records = resolve(conn, artifact)
    errs = verify(records, config_keys)
    if errs or not apply:
        return records, errs, 0
    return records, [], apply_states(conn, records)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    apply = "--apply" in argv

    config.load_env()
    db.init_db()
    conn = db.connect()
    try:
        artifact = load_artifact()
        config_keys = config_seed_keys()
        print(f"  {len(artifact)} artifact row(s), {len(config_keys)} config seed(s). Every")
        print("  value below is READ from `cases`; `->` marks a row this would change and")
        print("  `==` one already holding the proposed value. `court` and `status` are in no")
        print("  input to this script, so reading them here is the proof of a real read.\n")
        records, errs, filled = run(conn, artifact, config_keys, apply)
        for line in describe(records):
            print(line)
        counts: dict[str, int] = {}
        for r in records:
            key = "chain" if r["source"].startswith("chain") else r["source"]
            counts[key] = counts.get(key, 0) + 1
        print("\n  " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))
        if errs:
            print("\n  REFUSED -- guard failures, nothing written:", file=sys.stderr)
            for e in errs:
                print(f"    - {e}", file=sys.stderr)
            return 1
        if not apply:
            print("  DRY-RUN -- all guards pass, nothing written. Re-run with --apply.")
            return 0
        conn.commit()
        print(f"  APPLIED -- {filled} row(s) now carry their resolved state.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
