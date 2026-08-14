"""One-time repair: reset `cases.latest_entry_at` to its derivation (handoff 55/56).

`latest_entry_at` is DERIVED -- it equals MAX(case_entries.entry_at) for the case.
Between 2026-07-22 and 2026-08-14 it was not. `write_entries` assigned it the max
`date_filed` of the POLLED BATCH, which was correct while every poll was a full walk
and the batch was the docket, and became wrong the moment polling went incremental
(c8b8b6f): a date_modified window can legitimately contain only a late-backfilled old
filing, because RECAP backfills late, so the assignment walked the column BACKWARDS.

Measured against Turso 2026-08-14, before the repair: 12 of 40 rows disagreed with
their own derivation, every one of them BEHIND, by 1 to 83 days. West Virginia
`72335259` read 2026-05-15 while `case_entries` held an entry from 2026-08-06 -- which
is what put it in the campaign grid's quiet set as a false positive, and what sent a
conflict investigation looking at CourtListener for something the local table already
answered.

WHY THIS IS ONE-TIME. `write_entries` now recomputes from `case_entries` on any poll
that inserted a row, so a drifted row self-heals on its next non-empty poll. This
script exists because self-healing is not prompt -- a quiet docket may not take a new
entry for months, and until it does the row stays wrong on the live site. It repairs
all of them now instead. The standing check afterwards is
`python -m tools.coverage_audit` section 4, which reads this same comparison and
expects 0; if it ever reports non-zero again, that is a NEW defect at an insert site,
not this one recurring.

The repair is safe to re-run and is a no-op once clean, but it should not be
scheduled. A recurring repair script is a way of not fixing a bug.

Dry-run by default: prints every disagreeing row with both values and the delta in
days, and writes nothing. --apply writes and commits. Unlike the other two backfills
there is no refusal gate, and the reason is worth stating: this asserts nothing. It
copies a value the database already computes from rows the database already holds, so
there is no external claim that could be wrong -- the only failure available is a
column that already disagrees with its own definition, which is the condition being
repaired.

Run from the repo root as a module (puts the repo root on sys.path, like the collectors):
    python -m scripts.repair_latest_entry            # dry-run, writes nothing
    python -m scripts.repair_latest_entry --apply     # repair and commit
"""
from __future__ import annotations

import sys
from datetime import date

import config
import db

# One row per case, with the stored value beside the derived one. LEFT JOIN so a case
# with no entries at all appears rather than vanishing -- its derived value is NULL,
# and a stored non-NULL against that would be its own (different) defect.
DRIFT_SQL = """
SELECT c.case_id,
       c.state,
       c.court,
       c.docket_number,
       c.status,
       c.latest_entry_at            AS stored,
       MAX(e.entry_at)              AS derived,
       COUNT(e.id)                  AS n_entries
FROM cases c
LEFT JOIN case_entries e ON e.case_id = c.case_id
GROUP BY c.case_id
"""


def _days(stored: str | None, derived: str | None) -> int | None:
    """Whole days from stored to derived. Both are naive ISO; compare the date parts
    only, which is what the column carries (entry_at is a date at midnight)."""
    if not stored or not derived:
        return None
    try:
        return (date.fromisoformat(derived[:10]) - date.fromisoformat(stored[:10])).days
    except ValueError:
        return None


def find_drift(conn) -> list[dict]:
    """Every row whose stored value disagrees with its derivation, worst drift first.
    Compares the full stored string against MAX(entry_at) exactly: these are written
    from the same source in the same format, so a difference is a real difference and
    not a formatting artifact."""
    out = []
    for r in conn.execute(DRIFT_SQL).fetchall():
        stored, derived = r["stored"], r["derived"]
        if stored == derived:
            continue
        out.append({
            "case_id": r["case_id"],
            "state": r["state"],
            "court": r["court"],
            "docket_number": r["docket_number"],
            "status": r["status"],
            "stored": stored,
            "derived": derived,
            "n_entries": r["n_entries"],
            "days": _days(stored, derived),
        })
    out.sort(key=lambda x: -(x["days"] or 0))
    return out


def describe(rows: list[dict]) -> list[str]:
    lines = [
        f"    {'case_id':<9}  {'state':<15} {'status':<11} {'stored':<12} {'derived':<12} "
        f"{'drift':>7}  {'n':>4}  court",
    ]
    for r in rows:
        d = f"{r['days']:+}d" if r["days"] is not None else "-"
        lines.append(
            f"    {r['case_id']:<9}  {str(r['state']):<15} {str(r['status']):<11} "
            f"{str(r['stored'])[:10]:<12} {str(r['derived'])[:10]:<12} {d:>7}  "
            f"{r['n_entries']:>4}  {r['court']}")
    return lines


def apply_repair(conn, rows: list[dict]) -> int:
    """Set each drifted row to its derivation. Idempotent: a second run finds no drift
    and writes nothing. Returns the count now agreeing."""
    for r in rows:
        conn.execute(
            "UPDATE cases SET latest_entry_at = "
            "(SELECT MAX(entry_at) FROM case_entries WHERE case_id = ?) WHERE case_id = ?",
            (r["case_id"], r["case_id"]),
        )
    return sum(
        1 for r in rows
        if (conn.execute("SELECT latest_entry_at FROM cases WHERE case_id = ?",
                         (r["case_id"],)).fetchone() or [None])[0] == r["derived"]
    )


def run(conn, apply: bool) -> tuple[list[dict], int]:
    """Find, then (only if apply) write. conn-parameterized so tests drive it against a
    temp DB and never touch Turso."""
    rows = find_drift(conn)
    if not apply:
        return rows, 0
    return rows, apply_repair(conn, rows)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    apply = "--apply" in argv

    config.load_env()
    db.init_db()
    conn = db.connect()
    try:
        total = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        rows, fixed = run(conn, apply)
        print(f"  {len(rows)} of {total} row(s) disagree with MAX(case_entries.entry_at).")
        print("  `stored` is what cases.latest_entry_at holds; `derived` is what the table")
        print("  says it should be. A positive drift means the column is BEHIND the docket.\n")
        if rows:
            for line in describe(rows):
                print(line)
            print()
        if not apply:
            print("  DRY-RUN -- nothing written. Re-run with --apply.")
            return 0
        conn.commit()
        print(f"  APPLIED -- {fixed} of {len(rows)} row(s) now equal their derivation.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
