"""One-off migration: re-key the two unresolved slug `cases` rows onto the CourtListener
docket ids they should always have had, carrying their items with them (Unit A).

    python -m scripts.rekey_slug_cases            # dry-run, writes nothing
    python -m scripts.rekey_slug_cases --apply    # migrate and commit

APPLIED 2026-09-07 (Unit A). One-time and already run against Turso: both rows are
numeric-keyed, their items carried, the slug rows dropped. DO NOT SCHEDULE IT and do
not re-run it -- the guards would refuse anyway, since the slug rows it names no longer
exist, but the reason to leave it alone is that it has no work left to do.

WHY THESE ROWS EXIST AT ALL
===========================
`collect_case` opens with a B2-only branch: `if not (dn and court_id)` -> slugify the
caption, upsert, write one B2 subject item, return WITHOUT touching the API. The two
rows below take that branch on every run, because `tracker_uw.COURT_IDS` is closed over
the names courts actually have ("Eighth Circuit", "D.C. Circuit") while the UW artifact
carries the names UW types ('Eighth District', 'DC Circuit'). The lookup misses, court_id
comes back null, and the row can never be polled. They are not failed resolves; no
request was ever made for them.

THE ORDERING TRAP, AND WHY THE ALIASES CANNOT LAND FIRST
========================================================
Fixing COURT_IDS alone would make this worse rather than better. With court_id populated
the B2 branch is skipped and `collect_case` reaches its reuse lookup,

    SELECT case_id, source_url FROM cases WHERE docket_number = ? AND court = ?
    if existing and str(existing["case_id"]).isdigit():

which FINDS the slug row -- the lookup joins on the seed's own `docket_number` and
`court`, both of which the slug row already carries verbatim -- and then REJECTS it,
because a slug is not `isdigit()`. The collector would resolve via the API and upsert
under a fresh numeric case_id, leaving the slug row and its items stranded beside a
duplicate. So the re-key runs FIRST; after it, `isdigit()` is true, the reuse path binds,
and the row polls with no resolve request at all.

WHY INSERT-REPOINT-DELETE RATHER THAN TWO UPDATEs
=================================================
The plan for this unit was first sketched as `UPDATE cases SET case_id=...` followed by
`UPDATE items SET case_id=...` in one transaction. That fails as written, and it was the
review layer that caught it before anything ran. `items.case_id` is a declared foreign
key (`schema.sql:35`, `TEXT REFERENCES cases(case_id)`) and enforcement is live --
`PRAGMA foreign_keys` reads 1 on this connection, set per-connection in db.py. With no
ON UPDATE CASCADE, re-keying the parent while children reference it fails, and repointing
the children first would dangle them at a row that does not exist yet.

So each row migrates as: INSERT the successor row under the CL id, copying every column
verbatim -> UPDATE items onto it -> DELETE the slug row, in that order, inside one
transaction. This needs no pragma and behaves identically on local SQLite and on Turso.
(`PRAGMA defer_foreign_keys=ON` would also work; it reads 0 here and would have to be set
deliberately, which is a second thing to be right about for no gain.)

WHAT IS COPIED, AND WHAT IS DELIBERATELY NOT REFRESHED
======================================================
Every column is copied verbatim except `case_id`, which is the point of the exercise. In
particular `court` stays 'DC Circuit' / 'Eighth District' and `docket_number` is
untouched: `upsert_case` writes those two off the SEED and never off the docket, and
three separate consumers depend on it (the reuse lookup above, coverage_audit's
`(docket_number, court)` seed join, and the byte-identical-overwrite property between a
tracker row and a config seed). Rewriting them here would break the very lookup this
migration exists to satisfy.

The caption is carried AS-IS, because writing an API-derived value here would duplicate
the collector's work inside a migration that is otherwise pure bookkeeping.

    FALSIFIED, 2026-09-07, corrected in place rather than deleted, because the wrong
    reason is instructive. This paragraph used to continue: "the next cron's fresh
    resolve replaces it from CourtListener's `case_name`, turning 'United States v.
    Minnesota' into 'United States v. Steve Simon' ... `source_url` is NULL on both
    rows and stays NULL; the reuse path reads it and tolerates None, and the next
    resolve fills it."

    THERE IS NO NEXT FRESH RESOLVE, and this migration's own success is what removes
    it. After the re-key `isdigit()` is true, so `collect_case` binds on the reuse
    path and `docket` stays None forever -- which is the entire point of running this
    script. `upsert_case` writes `caption`, `filed_at` and `source_url` only inside
    `if docket is not None:`, so the very condition this migration creates is the
    condition under which those three are never written again. The prediction was not
    merely wrong; it was the negation of what the change guarantees.

    Two independent things hid it. The claim describes a FUTURE state, so nothing at
    apply time could contradict it -- the same shape as the dated-absence class in
    docs/status.md. And `status` genuinely does get filled, by `refresh_status`, which
    made the paragraph look half-confirmed by the first cron that ran after it.

    The trio is filled once, deliberately, by scripts/backfill_appeal_metadata.py
    (gate 4.5). `status`, `date_terminated` and `status_checked_at` are not its job:
    `refresh_status` writes those and both rows sort to the head of its due list.

REFUSE-FIRST. Every guard runs over both rows before anything is written; a single
failure abandons the whole run rather than half of it. The item counts are asserted
EXACTLY, not as a minimum -- they were measured at 1 (DC) and 3 (MN) before this script
existed, and a different number means the world moved and this plan should be re-read
rather than forced through.
"""
from __future__ import annotations

import sys

import config
import db

# (slug case_id, resolved CourtListener docket id, expected item count)
# CL ids resolved out of band 2026-09-06 via litigation.resolve_docket, which binds only
# on exactly one match: 26-5296/cadc -> 74671625, 26-2679/ca8 -> 74687843. Both dockets
# report `appeal_from_str` naming the district we already hold, which is corroboration
# independent of the UW tracker.
ROWS = [
    ("united-states-v-dc", "74671625", 1),
    ("united-states-v-minnesota", "74687843", 3),
]


def columns(conn) -> list[str]:
    """Read the column list from the table rather than hardcoding it, so a schema
    addition is carried by this migration instead of silently dropped by it."""
    return [r[0] for r in conn.execute("SELECT name FROM pragma_table_info('cases')").fetchall()]


def check(conn, rows) -> tuple[list[str], list[dict]]:
    """Every guard, over every row, before anything is written."""
    errs: list[str] = []
    plans: list[dict] = []
    for slug, cl_id, expected in rows:
        src = conn.execute("SELECT * FROM cases WHERE case_id = ?", (slug,)).fetchone()
        if src is None:
            errs.append(f"{slug}: no such row")
            continue
        if not cl_id.isdigit():
            errs.append(f"{slug}: target id {cl_id!r} is not all-digits, which is the "
                        f"whole property the reuse path tests")
        clash = conn.execute("SELECT case_id FROM cases WHERE case_id = ?", (cl_id,)).fetchone()
        if clash is not None:
            errs.append(f"{slug}: target {cl_id} already exists as a row -- merge, do not migrate")
        n = conn.execute("SELECT COUNT(*) FROM items WHERE case_id = ?", (slug,)).fetchone()[0]
        if n != expected:
            errs.append(f"{slug}: {n} items, expected exactly {expected}")
        ce = conn.execute("SELECT COUNT(*) FROM case_entries WHERE case_id = ?", (slug,)).fetchone()[0]
        if ce:
            errs.append(f"{slug}: {ce} case_entries -- this row was polled after all, re-read the plan")
        ref = conn.execute("SELECT COUNT(*) FROM cases WHERE superseded_by = ?", (slug,)).fetchone()[0]
        if ref:
            errs.append(f"{slug}: {ref} row(s) point at it via superseded_by")
        plans.append({"slug": slug, "cl_id": cl_id, "items": n, "src": src})
    return errs, plans


def describe(plans, cols) -> list[str]:
    out = []
    for p in plans:
        src = p["src"]
        out.append(f"    {p['slug']}  ->  {p['cl_id']}")
        for col in cols:
            val = src[col]
            marker = "  <- REKEYED" if col == "case_id" else ""
            out.append(f"       {col:<18} {str(val)[:48]!r}{marker}")
        out.append(f"       items to repoint   {p['items']}")
        out.append("")
    return out


def migrate(conn, plans, cols) -> int:
    """One transaction per row: insert under the new key, repoint items, drop the slug."""
    moved = 0
    for p in plans:
        src, cl_id, slug = p["src"], p["cl_id"], p["slug"]
        vals = [cl_id if c == "case_id" else src[c] for c in cols]
        conn.execute(
            f"INSERT INTO cases ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            tuple(vals),
        )
        cur = conn.execute("UPDATE items SET case_id = ? WHERE case_id = ?", (cl_id, slug))
        n = cur.rowcount
        if n != p["items"]:
            raise RuntimeError(f"{slug}: repointed {n} items, expected {p['items']} -- rolling back")
        conn.execute("DELETE FROM cases WHERE case_id = ?", (slug,))
        conn.commit()
        moved += 1
    return moved


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    apply = "--apply" in argv

    config.load_env()
    conn = db.connect()
    try:
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        cols = columns(conn)
        print(f"  foreign_keys = {fk} (1 is why this is insert-repoint-delete, not two UPDATEs)")
        print(f"  {len(cols)} columns on `cases`, all copied verbatim except case_id.")
        print(f"  {len(ROWS)} row(s). Every value below is READ from the database.\n")

        errs, plans = check(conn, ROWS)
        for line in describe(plans, cols):
            print(line)
        if errs:
            print("  REFUSED -- guard failures, nothing written:", file=sys.stderr)
            for e in errs:
                print(f"    - {e}", file=sys.stderr)
            return 1
        if not apply:
            print("  DRY-RUN -- all guards pass, nothing written. Re-run with --apply.")
            return 0

        moved = migrate(conn, plans, cols)
        bad = conn.execute("PRAGMA foreign_key_check").fetchall()
        if bad:
            print(f"  FK VIOLATIONS AFTER MIGRATION: {len(bad)}", file=sys.stderr)
            return 1
        print(f"  APPLIED -- {moved} row(s) re-keyed, items carried, slug rows dropped, "
              f"0 foreign-key violations.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
