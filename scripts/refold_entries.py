"""Refold every case: bring the items' fold columns (collectors/cl_fold.py) to what the
object table says now (R1 step d, Corey's rulings of 2026-09-30). Dry-run by default.

The collector refolds a case whenever its entries change, the id backfill refolds each
docket it walks, and link_entry_twins refolds what it links. This pass exists for what
none of those reach: items written before the fold columns existed, on dockets whose walk
ran before the fold, and a check that the columns and the table agree.

No page reads the fold before the switch, so --apply before it moves nothing public. The
counts it prints are the entries the switch will show.

Usage (repo root):
    python -m scripts.refold_entries            # dry run: what would change, per case
    python -m scripts.refold_entries --apply    # write, commit per case
"""

from __future__ import annotations

import sys

import config
import db
from collectors import cl_fold


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    apply = "--apply" in argv
    config.load_env()
    conn = db.connect()
    try:
        cases = [r["case_id"] for r in conn.execute(
            "SELECT DISTINCT case_id FROM items WHERE channel = 'litigation' ORDER BY case_id").fetchall()]
        total = {"items": 0, "changed": 0, "merged": 0}
        for case in cases:
            if apply:
                c = cl_fold.refold_case(conn, case)
                conn.commit()
            else:
                want = cl_fold.plan_case(conn, case)
                have = {r["id"]: tuple(r[k] for k in cl_fold.COLS) for r in conn.execute(
                    "SELECT id, " + ", ".join(cl_fold.COLS) + " FROM items WHERE case_id = ? "
                    "AND channel = 'litigation'", (case,)).fetchall()}
                c = {"items": len(want), "changed": sum(1 for i, v in want.items() if have.get(i) != v),
                     "merged": sum(1 for v in want.values() if v[0] is not None)}
            for k in total:
                total[k] += c[k]
            if c["changed"]:
                print(f"  {case:>10}  {c['items']:>4} items  {c['merged']:>3} folded  "
                      f"{c['changed']:>4} to write")
        print(f"litigation items {total['items']}, folded into another {total['merged']}, "
              f"presenting {total['items'] - total['merged']}; "
              f"{total['changed']} {'written' if apply else 'to write'}")
        if not apply:
            print("  DRY-RUN -- nothing written. Re-run with --apply.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
