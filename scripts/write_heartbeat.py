"""Write one `runs` row for the current collect.yml run. Invoked as the workflow's
final step, with `if: always()`.

THIS IS THE FIRST TABLE THE WORKFLOW WRITES RATHER THAN A COLLECTOR, and the reason is
structural rather than stylistic. `collect.yml` invokes six separate
`python -m collectors.X` processes in one `bash -e` step, so NO PROCESS SPANS THE RUN
and no collector can know the run's total, its conclusion, or that it finished at all.
`export/snapshots.py` does run once per run, and was the obvious home until the shape
was read: it sits behind the collectors with no `if: always()`, so a heartbeat written
there would be ABSENT on a failed run -- indistinguishable, from the page's side, from a
run that never fired. The whole point of this table is to tell those two apart.

AND IT IS THE ONE ENTRY IN `scripts/` THAT IS MEANT TO BE SCHEDULED. Every other file
there is a one-time backfill, dry-run-by-default behind an `--apply` gate, and CLAUDE.md
says in as many words not to schedule any of them. This one runs four times a day and
carries no `--apply`, because it is not a migration: it appends a fact about a run that
just happened, it is idempotent on `run_id` (upsert, so a GitHub re-run replaces rather
than duplicates), and a dry-run default would mean the scheduled invocation silently
wrote nothing. The convention line in CLAUDE.md is amended to say so.

WHY NOT `MAX(fetched_at)`. That anchor cannot answer "has collection stopped". P0,
2026-09-17: `items.fetched_at` is written once on first insert and never updated --
four collectors go through `db.insert_ignore`, an `INSERT OR IGNORE` against
`UNIQUE(content_hash)` that drops a re-encountered item whole, and `db.upsert` is never
called on `items` -- so a healthy run that collected nothing new leaves the anchor
exactly where a missed run would. Three of 51 scheduled runs since `58c6aca` committed
nothing at all; for the two after `data/generated_at.json` was staged, the absence of a
commit PROVES the anchor did not move.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import common  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402


def normalize(raw: str) -> str:
    """Re-emit an ISO timestamp in the exact shape `common.now_iso()` produces.

    THE COMPARISON BELOW IS A STRING COMPARISON, which is why this is not decoration.
    `now_iso()` renders `+00:00`; GitHub renders `Z`. Lexically `"Z"` (0x5A) sorts
    ABOVE `"."` (0x2E), so an unnormalized `...:32Z` compares greater than
    `...:32.123456+00:00` and the count would silently drop every item written in the
    first second of the run. Parsing both ends into the same rendering removes the
    question rather than reasoning about it.
    """
    return datetime.fromisoformat(raw.strip().replace("Z", "+00:00")).astimezone(
        timezone.utc
    ).isoformat()


def build_row(conn, run_id: str, slot: str, started_at: str, conclusion: str) -> dict:
    """The row, with `items_written` read off the record rather than reported.

    No collector counts what it wrote, and asking six processes to agree on a total
    through a file or an env var would be six places for the number to go wrong.
    `fetched_at` is stamped at insert and never updated, so the items this run wrote
    are exactly the items whose stamp falls at or after the run's start -- the same
    write-once property that makes the anchor useless for staleness makes this count
    exact.
    """
    start = normalize(started_at)
    written = conn.execute(
        "SELECT COUNT(*) FROM items WHERE fetched_at >= ?", (start,)
    ).fetchone()[0]
    return {
        "run_id": run_id,
        "slot": slot,
        "started_at": start,
        "finished_at": common.now_iso(),
        "items_written": int(written),
        "conclusion": conclusion,
    }


def main(argv: list[str] | None = None) -> int:
    config.load_env()
    run_id = os.environ.get("GITHUB_RUN_ID") or "local"
    slot = os.environ.get("SLOT") or "dispatch"
    started_at = os.environ.get("RUN_STARTED_AT") or common.now_iso()
    conclusion = os.environ.get("JOB_STATUS") or "unknown"

    # init_db here and not only in the collectors: this step carries `if: always()`, so
    # it can be reached on a run whose collector step died before any main() ran.
    db.init_db()
    conn = db.connect()
    try:
        row = build_row(conn, run_id, slot, started_at, conclusion)
        # Upsert, not insert: a GitHub re-run reuses the run id, and a second row for
        # one run would make the page's per-slot lookup ambiguous.
        db.upsert(conn, "runs", row, "run_id")
        conn.commit()
    finally:
        conn.close()

    print(
        f"heartbeat: run {row['run_id']} slot {row['slot']} "
        f"{row['started_at']} -> {row['finished_at']} "
        f"items_written={row['items_written']} conclusion={row['conclusion']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
