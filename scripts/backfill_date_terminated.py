"""One-off backfill: populate `cases.date_terminated` on the rows that terminated
before the column existed (handoff 97 H1b).

WHY A BACKFILL IS NEEDED AT ALL, and it is not "because the column is new". The
collector writes this value in two places and NEITHER can reach these rows:

  * `upsert_case` writes it only inside `if docket is not None:` -- a FRESH resolve --
    and a resolved case is never re-resolved.
  * `refresh_status` re-reads dockets, but `due_for_status_refresh` excludes
    `terminated` rows, deliberately and correctly: termination is absorbing on the
    court's clock, and re-reading those rows is what would double the daily draw.

So a docket that terminated before this column arrived would read `terminated` with a
NULL date forever. That is the same write-once shape handoff 27 fixed for `status`
itself, and the same fix does not apply -- un-excluding terminated rows would spend
the budget the exclusion exists to protect. A one-time pass is the proportionate
answer, and after it the collector covers every docket that terminates from now on.

THE STORED VALUE IS A1, READ LIVE. This script does not transcribe the dates from the
handoff-97 H0 table: it fetches each docket and writes CourtListener's own
`date_terminated`. The H0 table is the GUARD, not the source -- if a live value
disagrees with the value H0 eyeballed against the docket, the whole run refuses. That
ordering matters, because a table of twenty dates typed into a file is exactly the
editorial artifact this column exists to avoid needing.

Dry-run by default: fetches, compares, prints the table, writes no ROW DATA.
--apply writes and commits. Refusal-first: if ANY row fails a guard, nothing is
written -- a half-populated column is worse than an empty one, since the read layer
cannot tell "no date" from "not backfilled yet".

ONE THING THE DRY RUN DOES DO, said plainly because "writes nothing" would be false:
it runs the MIGRATION in both modes. `db.init_db()` -> `_apply_migrations` adds the
column, and it has to happen before the dry run can SELECT `date_terminated` at all.
The ALTER is idempotent and additive, every collector already calls `init_db()` at
start, and no row data moves. What --apply gates is the twenty-one UPDATEs.

Idempotent: re-running writes the same values. Safe to re-run after --apply, and the
dry-run is the check for it.

Cost: one request per terminated row, 21 today, at PAGE_THROTTLE against a measured
20/min and 1,000/hour EDU tier. Not a collection run and not scheduled -- like
backfill_supersession, this is applied once and then left in the tree as the record
of how the column was filled.

Run from the repo root as a module:
    python -m scripts.backfill_date_terminated            # dry-run, writes nothing
    python -m scripts.backfill_date_terminated --apply     # write and commit
"""
from __future__ import annotations

import os
import sys

import common
import db
from collectors import litigation as lit

CL_BASE = "https://www.courtlistener.com/api/rest/v4"

# The handoff-97 H0 classification, eyeballed once per case against the docket window
# at each row's own termination date. Used ONLY as a guard against the live read.
# Twenty campaign rows; the terminated non-campaign row (LWV v. DHS) is not in H0's
# scope and is reported rather than guarded.
H0_DATES = {
    "72110941": "2026-04-28",  # AZ
    "71452580": "2026-01-15",  # CA
    "72021508": "2026-08-04",  # CO
    "72110170": "2026-07-23",  # CT
    "72055344": "2026-08-06",  # DC
    "72053306": "2026-01-23",  # GA
    "72054244": "2026-07-31",  # IL
    "72334676": "2026-07-23",  # KY
    "71980724": "2026-06-18",  # MD
    "72347022": "2026-06-24",  # MI
    "71453336": "2026-08-17",  # MN
    "72026664": "2026-08-14",  # NV
    "71453646": "2026-06-30",  # NH
    "72333329": "2026-07-29",  # NJ
    "71982149": "2026-07-14",  # NM
    "71457474": "2026-07-10",  # NY
    "72336804": "2026-04-17",  # OK
    "71363789": "2026-02-05",  # OR
    "71453026": "2026-06-27",  # PA
    "72156765": "2026-07-14",  # VA
}


def terminated_rows(conn):
    """Every terminated row, guarded and unguarded alike, ordered for a readable table."""
    return conn.execute(
        """SELECT case_id, state, caption, status, date_terminated
             FROM cases
            WHERE status = 'terminated'
            ORDER BY (state IS NULL), state, case_id"""
    ).fetchall()


def main() -> int:
    apply = "--apply" in sys.argv[1:]
    token = os.environ.get("COURTLISTENER_TOKEN")
    if not token:
        print("COURTLISTENER_TOKEN is not set", file=sys.stderr)
        return 2
    headers = {"Authorization": f"Token {token}"}

    # The ALTER. init_db runs _apply_migrations first, so this is what adds the column
    # to the live table; on a re-run it is a no-op. Every collector already calls it at
    # start, so the cron would eventually do this on its own -- doing it here makes the
    # migration part of the deliberate run rather than a side effect of the next poll.
    db.init_db()
    conn = db.connect()

    rows = terminated_rows(conn)
    print(f"terminated rows: {len(rows)}  ({len(H0_DATES)} guarded by the H0 table)\n")

    refusals, writes = [], []
    print(f"{'case_id':<11}{'st':<16}{'stored':<22}{'live':<22}{'H0':<12}verdict")
    for r in rows:
        cid = str(r["case_id"])
        try:
            docket = common.http_get(f"{CL_BASE}/dockets/{cid}/", headers=headers,
                                     throttle=lit.PAGE_THROTTLE)
        except Exception as exc:                      # noqa: BLE001 -- report, refuse, continue
            refusals.append((cid, f"fetch failed: {exc}"))
            print(f"{cid:<11}{(r['state'] or '-'):<16}{'':<22}{'':<22}{'':<12}FETCH FAILED")
            continue

        live_raw = docket.get("date_terminated")
        live = common.to_iso(live_raw)
        stored = r["date_terminated"]
        h0 = H0_DATES.get(cid)

        verdict = "write"
        if not live:
            # A row this table calls terminated, that CourtListener no longer dates.
            # Refuse rather than write NULL: it means `status` and the live docket
            # disagree, which is a finding about the row and not a backfill decision.
            refusals.append((cid, "status is 'terminated' but live date_terminated is empty"))
            verdict = "REFUSE (live date empty)"
        elif h0 and (live_raw or "")[:10] != h0:
            refusals.append((cid, f"live {live_raw} != H0-verified {h0}"))
            verdict = "REFUSE (disagrees with H0)"
        elif stored == live:
            verdict = "already correct"
        elif stored is not None:
            verdict = "overwrite"

        if verdict in ("write", "overwrite"):
            writes.append((cid, live))
        print(f"{cid:<11}{(r['state'] or '-'):<16}{str(stored):<22}{str(live):<22}"
              f"{str(h0 or '-'):<12}{verdict}")

    unguarded = [str(r["case_id"]) for r in rows if str(r["case_id"]) not in H0_DATES]
    if unguarded:
        print(f"\nnot in the H0 table, read live and reported rather than guarded: "
              f"{', '.join(unguarded)}")

    if refusals:
        print(f"\nREFUSED -- {len(refusals)} row(s) failed a guard; nothing written:")
        for cid, why in refusals:
            print(f"  {cid}: {why}")
        return 1

    if not apply:
        print(f"\ndry-run: {len(writes)} row(s) would be written. Re-run with --apply.")
        return 0

    for cid, value in writes:
        # date_terminated ONLY. Not updated_at: this is a column being filled in from
        # the same upstream read the row already reflects, not the record changing its
        # mind about anything, and updated_at is the instrument that shows which rows
        # the collector actually touched. Same discipline as backfill_supersession.
        conn.execute("UPDATE cases SET date_terminated = ? WHERE case_id = ?", (value, cid))
    conn.commit()
    print(f"\napplied: {len(writes)} row(s) written.")

    after = {str(r["case_id"]): r["date_terminated"] for r in terminated_rows(conn)}
    nulls = [cid for cid, v in after.items() if not v]
    bad = [cid for cid, want in H0_DATES.items()
           if (after.get(cid) or "")[:10] != want]
    print(f"re-read: {len(after) - len(nulls)}/{len(after)} non-null; "
          f"{len(H0_DATES) - len(bad)}/{len(H0_DATES)} equal to the H0-verified set")
    if nulls or bad:
        print(f"  STILL NULL: {nulls}\n  DISAGREE: {bad}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
