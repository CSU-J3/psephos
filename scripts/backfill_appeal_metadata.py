"""One-off backfill: fill the docket-derived columns the reuse path can never write,
on the two Unit A appeal rows (gate 4.5).

    python -m scripts.backfill_appeal_metadata            # dry-run, writes nothing
    python -m scripts.backfill_appeal_metadata --apply    # fetch, update, commit

APPLIED 2026-09-07 (Unit A, gate 4.5). One-time and already run against Turso: the trio
landed on both rows, status / date_terminated / status_checked_at verified unmoved. DO
NOT SCHEDULE IT. Re-running is harmless rather than idempotent-by-luck -- the guards
re-fetch and the UPDATE rewrites the same values -- but it spends two CourtListener
requests to change nothing.

WHY THESE COLUMNS ARE EMPTY, AND WHY NO CRON WILL EVER FILL THEM
================================================================
`upsert_case` gates `caption`, `filed_at`, `source_url`, `status`, `date_terminated`
and `status_checked_at` behind `if docket is not None:` -- i.e. it writes them only on
a FRESH RESOLVE. The re-key (scripts/rekey_slug_cases.py) put these two rows under
their CourtListener ids precisely so the collector's reuse lookup would bind them, and
it does: `str(existing["case_id"]).isdigit()` is now true, so `docket` stays None and
the collector polls entries without ever resolving. That is the intended steady state
and it is cheap -- but it means these two rows are the only numeric-keyed rows in
`cases` never populated by a resolve, and reuse will never populate them.

Three of those six columns are handled elsewhere and are NOT this script's job:
`status`, `date_terminated` and `status_checked_at` are written by `refresh_status`,
which exists for exactly this write-once gap and probes `/dockets/{id}/` on its own
schedule. Both rows sort to the head of its due list (never-checked first), so the
cron stamps them without help. This script therefore LEAVES THOSE COLUMNS ALONE --
and asserts them unchanged rather than merely omitting them from the statement.

What remains is the trio no pass reaches: `caption` (with `plaintiff`/`defendant`
derived from it), `filed_at`, and `source_url`.

PROVENANCE OF THE VALUES -- A RE-FETCH, AND WHY IT IS NOT FREE
==============================================================
Two requests, one `/dockets/{id}/` per row. They are a RE-FETCH of a response this
system already received and discarded, which is worth stating plainly rather than
hiding behind "only two calls":

  - The out-of-band resolve that produced these ids on 2026-09-06 was not retained.
    Its response bodies exist nowhere on disk; only the ids and an `appeal_from_str`
    corroboration survived, in the re-key script's comment.
  - `refresh_status` fetches this exact endpoint on this exact pair, and the response
    it parses CONTAINS all three values -- it reads the status bit and
    `date_terminated` and drops the rest on the floor.

So the cheapest theoretical path is to widen that probe to carry these fields through.
Considered and DECLINED: it would put a backfill's concern inside a pass whose single
job is re-reading one bit, on every row, forever, to serve two rows once. A one-off
script paying two requests is the smaller thing to be wrong about. If a third such row
ever appears, revisit -- that is the signal, not this one.

`absolute_url` is why a fetch is needed at all rather than a literal UPDATE. Its form
is predictable (`/docket/{id}/{slug}/`) and that is exactly why it is not
reconstructed here: a guessed slug that happens to resolve is indistinguishable from a
correct one until it does not.

REFUSE-FIRST. Every row is fetched and every guard evaluated before anything is
written; one failure abandons the whole run. Expected values are asserted EXACTLY --
they were established out of band, and a different value means the world moved and
this plan should be re-read rather than forced through. The dry-run prints every
fetched value BEFORE evaluating the guards, so one dry-run is informative even when it
refuses.
"""
from __future__ import annotations

import sys

import common
import config
import db
from collectors.litigation import CL_BASE_WEB, PAGE_THROTTLE, USER_AGENT, split_caption

# case_id -> (label, expected token in CourtListener's case_name, expected date_filed)
# The token is a substring test, not an equality test: CourtListener's `case_name` is
# authoritative for the caption and this script does not presume its exact formatting.
# The date is asserted exactly, because it is a date.
ROWS = [
    ("74671625", "DC", "Evans", "2026-08-19"),
    ("74687843", "Minnesota", "Simon", "2026-08-21"),
]

# Written by refresh_status, never here. Captured before and re-read after --apply.
UNTOUCHED = ("status", "date_terminated", "status_checked_at")


def fetch(base: str, headers: dict, case_id: str) -> dict:
    return common.http_get(f"{base}/dockets/{case_id}/",
                           headers=headers, throttle=PAGE_THROTTLE)


def plan(conn, base: str, headers: dict) -> tuple[list[str], list[dict], list[str]]:
    """Fetch every row and evaluate every guard before anything is written."""
    errs: list[str] = []
    plans: list[dict] = []
    shown: list[str] = []

    for case_id, label, want_token, want_filed in ROWS:
        row = conn.execute(
            "SELECT case_id, caption, plaintiff, defendant, filed_at, source_url, "
            "status, date_terminated, status_checked_at, updated_at "
            "FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        if row is None:
            errs.append(f"{case_id} ({label}): no such row -- has the re-key been applied?")
            continue

        docket = fetch(base, headers, case_id)
        case_name = docket.get("case_name") or ""
        date_filed = common.to_iso(docket.get("date_filed"))
        abs_url = docket.get("absolute_url")
        source_url = CL_BASE_WEB + abs_url if abs_url else None
        plaintiff, defendant = split_caption(case_name)

        shown.append(f"    {case_id}  ({label})")
        shown.append(f"       caption      {row['caption']!r}")
        shown.append(f"                 -> {case_name!r}")
        shown.append(f"       plaintiff    {row['plaintiff']!r} -> {plaintiff!r}")
        shown.append(f"       defendant    {row['defendant']!r} -> {defendant!r}")
        shown.append(f"       filed_at     {row['filed_at']!r} -> {date_filed!r}")
        shown.append(f"       source_url   {row['source_url']!r}")
        shown.append(f"                 -> {source_url!r}")
        shown.append(f"       UNTOUCHED    status={row['status']!r} "
                     f"date_terminated={row['date_terminated']!r} "
                     f"status_checked_at={row['status_checked_at']!r}")
        shown.append("")

        if want_token.lower() not in case_name.lower():
            errs.append(f"{case_id} ({label}): case_name {case_name!r} does not contain "
                        f"{want_token!r} -- expected mapping may be inverted, re-read the plan")
        # Compare NORMALIZED against NORMALIZED. The constant below is written as a bare
        # date because that is how a person states one; `common.to_iso` renders it
        # '2026-08-19T00:00:00', which is also the form `upsert_case` stores on every
        # other row, so the fetched value is right and the first draft of this guard was
        # wrong. Normalizing both sides keeps the constant readable without asserting a
        # format this script does not own.
        if date_filed != common.to_iso(want_filed):
            errs.append(f"{case_id} ({label}): date_filed {date_filed!r}, expected "
                        f"{common.to_iso(want_filed)!r} (from {want_filed!r})")
        if not abs_url:
            errs.append(f"{case_id} ({label}): docket carries no absolute_url; source_url is "
                        f"not reconstructable and must not be guessed")
        if plaintiff is None or defendant is None:
            errs.append(f"{case_id} ({label}): split_caption found no ' v. ' in {case_name!r}")

        plans.append({"case_id": case_id, "label": label, "caption": case_name,
                      "plaintiff": plaintiff, "defendant": defendant,
                      "filed_at": date_filed, "source_url": source_url,
                      "before": {c: row[c] for c in UNTOUCHED}})

    if len(plans) != len(ROWS):
        errs.append(f"planned {len(plans)} row(s), expected exactly {len(ROWS)}")
    return errs, plans, shown


def apply_rows(conn, plans: list[dict]) -> int:
    """One targeted UPDATE per row. The caption and the two names it decomposes into
    move in the SAME statement -- split them across two and a failure between leaves a
    caption whose plaintiff/defendant were derived from the previous one."""
    updated = 0
    for p in plans:
        cur = conn.execute(
            "UPDATE cases SET caption = ?, plaintiff = ?, defendant = ?, "
            "filed_at = ?, source_url = ?, updated_at = ? WHERE case_id = ?",
            (p["caption"], p["plaintiff"], p["defendant"], p["filed_at"],
             p["source_url"], common.now_iso(), p["case_id"]))
        if cur.rowcount != 1:
            raise RuntimeError(f"{p['case_id']}: UPDATE touched {cur.rowcount} rows, "
                               f"expected exactly 1 -- rolling back")
        updated += 1
    conn.commit()
    return updated


def verify(conn, plans: list[dict]) -> list[str]:
    """Read the rows back: the trio landed, updated_at moved, and the three columns
    this script must not touch are identical to what they were before it ran."""
    errs: list[str] = []
    for p in plans:
        row = conn.execute(
            "SELECT caption, plaintiff, defendant, filed_at, source_url, updated_at, "
            + ", ".join(UNTOUCHED) + " FROM cases WHERE case_id = ?",
            (p["case_id"],)).fetchone()
        for col in ("caption", "plaintiff", "defendant", "filed_at", "source_url"):
            if row[col] != p[col]:
                errs.append(f"{p['case_id']}: {col} read back {row[col]!r}, wrote {p[col]!r}")
        if not row["updated_at"]:
            errs.append(f"{p['case_id']}: updated_at not stamped")
        for col in UNTOUCHED:
            if row[col] != p["before"][col]:
                errs.append(f"{p['case_id']}: {col} MOVED {p['before'][col]!r} -> "
                            f"{row[col]!r} -- this script must not touch it")
    return errs


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    apply = "--apply" in argv

    config.load_env()
    sources = config.load_sources()
    lit = sources["litigation"]
    base = lit["api"]["base"].rstrip("/")
    token = config.require_env(lit["api"]["key_env"])
    headers = {"Authorization": f"Token {token}", "User-Agent": USER_AGENT}

    conn = db.connect()
    try:
        print(f"  {len(ROWS)} row(s), {len(ROWS)} request(s) -- a re-fetch of what "
              f"refresh_status already reads and discards (see module docstring).")
        print("  status / date_terminated / status_checked_at are NOT written here.\n")

        errs, plans, shown = plan(conn, base, headers)
        for line in shown:
            print(line)
        if errs:
            print("  REFUSED -- guard failures, nothing written:", file=sys.stderr)
            for e in errs:
                print(f"    - {e}", file=sys.stderr)
            return 1
        if not apply:
            print("  DRY-RUN -- all guards pass, nothing written. Re-run with --apply.")
            return 0

        updated = apply_rows(conn, plans)
        bad = verify(conn, plans)
        if bad:
            print(f"  VERIFY FAILED after {updated} update(s):", file=sys.stderr)
            for e in bad:
                print(f"    - {e}", file=sys.stderr)
            return 1
        print(f"  APPLIED -- {updated} row(s) updated, updated_at stamped, "
              f"status/date_terminated/status_checked_at unchanged.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
