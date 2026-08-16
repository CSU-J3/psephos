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
  3. look for a DOCKET CROSS-REFERENCE, the strongest signal available and A1 when it
     exists: does either row's case_entries text name the other's docket number? The
     circuit side prints `Originating case number: <district docket>` when it dockets
     the appeal, and the district side prints `USCA Case Number <circuit docket>` when
     it transmits the record. Measured against the four pairs asserted before handoff
     36, this finds three (PA both directions, NH forward, MD reverse) and correctly
     finds nothing for the Georgia venue refile -- no court transmits a record to a
     refile, so the rule abstains rather than misfiring. Where it is silent, step 1's
     artifact diff is the B2 fallback,
  4. CHECK THE CIRCUIT MAP. A district's appeals go to exactly one circuit by statute,
     so a successor in the wrong circuit is a bad mapping whatever the dockets say.
     Costs nothing -- no API call, no artifact -- and it is the only check here that is
     independent of BOTH CourtListener and the UW tracker, so it is the one that still
     catches an error the two of them agree on. All seven asserted pairs pass: W.D. Pa.
     -> 3d, D.N.H. -> 1st, D. Md. -> 4th, E.D. Ky. -> 6th, E.D. Va. -> 4th, D.N.M. ->
     10th. Run it in the right direction, though: a VENUE REFILE has no circuit step and
     must stay intra-state, which is what makes M.D. Ga. -> N.D. Ga. correct and would
     make an 11th Cir. successor there the error. Settle which kind of successor you
     have (step 2) before applying this, or it fires backwards,
  5. add the (source_id, source_docket, successor_id, successor_docket) pair to PAIRS,
  6. READ THE FIVE COLUMNS FIRST -- case_id, status, superseded_by, updated_at,
     status_checked_at -- and keep the output. apply_links is supposed to touch
     superseded_by and nothing else, and the only way to show that is to diff the after
     against a before. Do not substitute "updated_at doesn't show today's date": the
     seeded Georgia row is upserted by every collector run and already read today's date
     before the handoff-37 apply, so that test flags a clean write as a defect and
     passes vacuously on any row nothing else writes to,
  7. dry-run, paste the table, then --apply, then re-run the dry-run for idempotence.

Dry-run by default: prints each row AS QUERIED against the assertion and writes nothing.
--apply writes and commits. Refusal-first: if ANY pair fails a guard, the whole run
refuses and writes nothing -- a partial mapping is worse than none.

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
    # The three unseeded district orphans, unblocked by the status-refresh pass: all
    # three read `pending` until 2026-08-10, when refresh_status flipped them on the
    # court's clock, and verify() refused them until it did. Evidence per pair, since
    # they are not all the same strength (step 3 above):
    ("72334676", "3:26-cv-00019", "73674243", "26-5657"),   # KY -> 6th Cir.  B2: no
    #   cross-reference either way. The UW tracker's single Kentucky row was rewritten
    #   in place in 7dbda24 (2026-07-28), kyed/3:26-cv-00019 -> ca6/26-5657, its notes
    #   naming the appeal. Docket corroborates: dismissal with prejudice 07-23, NOA
    #   07-24, circuit `Civil Case Docketed` 07-24, Kentucky appellees on the appeal.
    ("72156765", "3:26-cv-00042", "73690636", "26-2002"),   # VA -> 4th Cir.  A1, reverse:
    #   73690636's first entry, 07-29, reads `Originating case number: 3:26-cv-00042-RCY`.
    ("71982149", "1:25-cv-01193", "73678095", "26-2126"),   # NM -> 10th Cir. A1, forward:
    #   71982149, 07-27, `USCA Information Letter with Case Number 26-2126 for 123 Notice
    #   of Appeal`. This is also the caption-collision pair -- both rows read `United
    #   States v. Oliver`, which is why nothing here matches or displays on caption.
    # The two Second Circuit appeals, 2026-08-15. UNLIKE every pair above, these
    # successors were not acquired from the tracker artifact -- the UW rows still name
    # the district dockets, so the circuit rows exist only because config/sources.yaml
    # seeds them (see the second-role comment there). Evidence per pair is A1 on BOTH
    # sides and independent of the tracker prose that raised the question:
    ("72110170", "3:26-cv-00021", "73686333", "26-2064"),   # CT -> 2d Cir.  Forward, from
    #   72110170's own entries: judgment for defendants and `NOTICE OF APPEAL ... by USA`
    #   both 07-23, plus a clerk's certificate of the record on appeal. Reverse, from the
    #   circuit row's metadata: `appeal_from_str` reads `DISTRICT OF CONNECTICUT (NEW
    #   HAVEN)`. Circuit map agrees -- D. Conn. appeals lie to ca2 and nowhere else.
    ("71457474", "1:25-cv-01338", "73682036", "26-2060"),   # NY -> 2d Cir.  Forward:
    #   71457474 holds judgment 07-10, `NOTICE OF APPEAL` 07-23, and `ELECTRONIC NOTICE
    #   AND CERTIFICATION sent to US Court of Appeals re 103 Notice of Appeal` 07-27.
    #   Reverse: `appeal_from_str` reads `NDNY (SYRACUSE)`. Note the district is the
    #   NORTHERN district of New York, not the Southern -- the caption says only "State
    #   of New York", so the originating court comes from the metadata, not the name.

    # The three Ninth Circuit pairs, and these run the OPPOSITE DIRECTION from every
    # pair above. Elsewhere psephos held the district row and acquired the successor;
    # here it held the CIRCUIT row and acquired the predecessor, because the tracker
    # had already moved each state to its appeal and stopped naming the original
    # (handoff 84/85). So the source rows below were seeded specifically to be
    # superseded, which is why they land unlinked and this step is separate.
    #
    # Evidence is A1 FORWARD from the successor's own record in all three, which is
    # the strongest shape available: the circuit row's `CASE OPENED` entry names the
    # district docket it came from, verbatim and with judge initials. Corroborated by
    # the tracker's per-state `Key decisions: District Court's <date> dismissal`, and
    # by CourtListener's own `date_terminated` on each district row once resolved --
    # three instruments, and the second and third differ in kind from the first.
    # Circuit map: C.D. Cal., D. Or. and D. Ariz. all appeal to the Ninth and nowhere
    # else, so these are appeals rather than venue refiles.
    ("71452580", "2:25-cv-09149", "72356732", "26-1232"),   # CA -> 9th Cir. Entry
    #   2026-03-03 on 72356732: `notice of appeal / petition filed in
    #   2:25-cv-09149-DOC-ADS`. Tracker: District Court's 1/15/26 dismissal.
    ("71363789", "6:25-cv-01666", "72356772", "26-1231"),   # OR -> 9th Cir. Entry
    #   2026-03-03 on 72356772: `... filed in 6:25-cv-01666-MTK`. Tracker: 2/5/26
    #   dismissal, matching this row's own date_terminated exactly -- which is also
    #   the discriminator that picked 71363789 over CourtListener's empty twin
    #   71956700. See the pin comment in config/sources.yaml.
    ("72110941", "2:26-cv-00066", "73443024", "26-3609"),   # AZ -> 9th Cir. Entry
    #   2026-06-04 on 73443024: `... filed in 2:26-cv-00066-SMB`. Tracker: 4/28/26
    #   dismissal, and separately that ca9 stayed THIS appeal on 6/22/26 pending the
    #   CA and OR appeals -- a fact about the appeal, not about the dismissal.

    # The first pair with NO state on either side, and nothing here depends on one:
    # both rows sue federal agencies, so `state` is NULL by construction and neither
    # appears on /campaign. It is a litigation-channel link only. A1 forward from the
    # predecessor's own record; circuit map: D.D.C. appeals lie to the D.C. Circuit.
    ("71499795", "1:25-cv-03501", "73544809", "26-5243"),   # LWV v. DHS -> D.C. Cir.
    #   Entry 2026-06-29 on 71499795: `USCA Case Number 26-5243 for 113 Notice of
    #   Appeal to DC Circuit Court`. Unlike CT/NY there was no tracker-lag argument
    #   to make -- UW carries neither row -- so this was seeded on the entry alone.
]


def _case(conn, case_id):
    """The row as the guards see it. `court` is display-only; verify() ignores it."""
    return conn.execute(
        "SELECT case_id, status, docket_number, court FROM cases WHERE case_id = ?",
        (case_id,),
    ).fetchone()


def describe(conn, pairs) -> list[str]:
    """The dry-run table: every value READ from `cases`, checked against the assertion.

    This is not a reprint of PAIRS, and the distinction is the whole point. Until
    handoff 36 main() printed the constant, so the review gate showed only its own
    input -- the four pairs already applied went through a dry-run that verified
    nothing, and a `--apply` that silently corrupted a docket number would have looked
    identical to one that worked. `!=` marks a field disagreeing with the assertion,
    which is the same condition verify() refuses on, shown per field instead of only in
    aggregate.

    No captions, deliberately. Two rows in `cases` share `United States v. Oliver` and
    they are the two halves of the NM pair, so a caption column renders that pair as a
    row linked to itself. Match and display on case_id -- the standing invariant."""
    lines: list[str] = []
    for src_id, src_dock, tgt_id, tgt_dock in pairs:
        for role, cid, asserted in (("source", src_id, src_dock), ("target", tgt_id, tgt_dock)):
            row = _case(conn, cid)
            if row is None:
                lines.append(f"    {role:<6} {cid:<9}  ROW MISSING (asserted docket {asserted})")
                continue
            dock = row["docket_number"] or "-"
            dock_note = "" if dock == asserted else f"!= {asserted}"
            status = (row["status"] or "").lower()
            if role == "source":
                status_note = "" if status == "terminated" else "!= terminated"
            else:
                status_note = "" if status != "terminated" else "!= a live docket"
            lines.append(
                f"    {role:<6} {cid:<9}  docket {dock:<15} {dock_note:<18}"
                f"status {row['status'] or '-':<11} {status_note:<17}{row['court'] or '-'}")
        lines.append("")
    return lines


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
        print(f"  {len(PAIRS)} pair(s). Every value below is READ from `cases`; `!=` marks a")
        print("  field disagreeing with the assertion in PAIRS, which is what verify() refuses")
        print("  on. Each pair prints source (must be terminated) then target (must be live);")
        print("  `court` appears in no tuple, so reading it here is the proof of a real read.\n")
        for line in describe(conn, PAIRS):
            print(line)
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
