"""One-off backfill: link a terminated docket to the successor that replaced it (a
circuit appeal, or a refile in the correct venue), via cases.superseded_by (handoff 13, 14).

Forward-pointing on the DEAD row. The circuit-appeal predecessors are terminated and
seedless, so `upsert_case` never rewrites them. The Georgia refile is different: its
M.D. Ga. source is terminated but still a live seed in data/doj_cases.json, so the
collector calls `upsert_case` on it every run -- the asserted value survives anyway
because that function's row dict omits `superseded_by` and `db.upsert` only sets listed
columns. The reverse lookup (successor -> predecessor) is a query, not a column. See
schema.sql cases.superseded_by.

There is no automatic detection here and there shouldn't be. The signal that a tracker
row moved to a successor docket is a diff in data/doj_cases.json, committed and
deterministic since handoff 4. Procedure for the next one:
  1. spot the docket change in the artifact's git history (a state's row gaining a new
     court_id / docket_number), OR a new tracker row for a state that already has one
     (the `Georgia (1)` / `Georgia (2)` refile pattern),
  2. confirm both rows in `cases`: the source row is `terminated`, the successor row is
     live and carries the new docket,
  3. add the (source_id, source_docket, successor_id, successor_docket) pair to PAIRS,
  4. dry-run, paste the table, then --apply.

Dry-run by default: prints the intended mapping and writes nothing. --apply writes and
commits. Refusal-first: if ANY pair fails a guard, the whole run refuses and writes
nothing -- a partial mapping is worse than none.

Run from the repo root as a module (like the collectors: puts the repo root on
sys.path so `import config` resolves; `python scripts/...py` would not):
    python -m scripts.backfill_supersession            # dry-run, writes nothing
    python -m scripts.backfill_supersession --apply     # link and commit
"""
from __future__ import annotations

import sys

import config
import db

# (source case_id, source docket, successor case_id, successor docket). Asserted from
# the handoff-13/14 recon, not derived -- captions differ at each level so no string
# match links them. Each source row is `terminated`; each successor row is live and
# carries the docket below.
PAIRS = [
    ("71453026", "2:25-cv-01481", "73582123", "26-2684"),   # PA -> 3d Cir.
    ("71453646", "1:25-cv-00371", "73607684", "26-1783"),   # NH -> 1st Cir.
    ("71980724", "1:25-cv-03934", "73608654", "26-1878"),   # MD -> 4th Cir.
    ("72053306", "5:25-cv-00548", "72193752", "1:26-cv-00485"),  # GA venue refile, M.D. Ga. -> N.D. Ga.
]


def _case(conn, case_id):
    return conn.execute(
        "SELECT case_id, status, docket_number FROM cases WHERE case_id = ?", (case_id,)
    ).fetchone()


def verify(conn, pairs) -> list[str]:
    """Guard every pair BEFORE any write, so one bad pair refuses the whole run. Returns
    the list of failures (empty = all pass): source present and terminated, target
    present and not terminated, and both dockets matching the asserted numbers."""
    errs: list[str] = []
    for src_id, src_dock, tgt_id, tgt_dock in pairs:
        src, tgt = _case(conn, src_id), _case(conn, tgt_id)
        if src is None:
            errs.append(f"{src_id}: source row missing")
            continue
        if tgt is None:
            errs.append(f"{tgt_id}: target row missing")
            continue
        if (src["status"] or "").lower() != "terminated":
            errs.append(f"{src_id}: source status {src['status']!r}, expected 'terminated'")
        if (tgt["status"] or "").lower() == "terminated":
            errs.append(f"{tgt_id}: target status is 'terminated', expected a live docket")
        if src["docket_number"] != src_dock:
            errs.append(f"{src_id}: source docket {src['docket_number']!r} != expected {src_dock!r}")
        if tgt["docket_number"] != tgt_dock:
            errs.append(f"{tgt_id}: target docket {tgt['docket_number']!r} != expected {tgt_dock!r}")
    return errs


def apply_links(conn, pairs) -> int:
    """Set superseded_by on each district row. Idempotent -- rewriting the same value has
    no effect. Returns the count of district rows now pointing at their circuit row."""
    for src_id, _sd, tgt_id, _td in pairs:
        conn.execute("UPDATE cases SET superseded_by = ? WHERE case_id = ?", (tgt_id, src_id))
    return sum(
        1 for src_id, _sd, tgt_id, _td in pairs
        if (conn.execute("SELECT superseded_by FROM cases WHERE case_id = ?", (src_id,))
            .fetchone() or [None])[0] == tgt_id
    )


def run(conn, pairs, apply: bool) -> tuple[list[str], int]:
    """Verify, then (only if all pass and apply) write. Refusal-first: any guard failure
    aborts with zero writes. Returns (errs, linked). conn-parameterized so tests drive it
    against a temp DB and never touch Turso."""
    errs = verify(conn, pairs)
    if errs:
        return errs, 0
    if not apply:
        return [], 0
    return [], apply_links(conn, pairs)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    apply = "--apply" in argv

    config.load_env()
    db.init_db()
    conn = db.connect()
    try:
        print("  source (terminated)            ->  successor (live)")
        for src_id, src_dock, tgt_id, tgt_dock in PAIRS:
            print(f"    {src_id} {src_dock:<15}  ->  {tgt_id} {tgt_dock}")
        errs, linked = run(conn, PAIRS, apply)
        if errs:
            print("\n  REFUSED -- guard failures, nothing written:", file=sys.stderr)
            for e in errs:
                print(f"    - {e}", file=sys.stderr)
            return 1
        if not apply:
            print("\n  DRY-RUN -- all guards pass, nothing written. Re-run with --apply.")
            return 0
        conn.commit()
        print(f"\n  APPLIED -- {linked} of {len(PAIRS)} source rows linked to their successor.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
