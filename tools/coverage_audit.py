"""Three read-only coverage questions about `cases`, in one pass. Writes nothing.

This is what survived the handoff 17 supersession-generator unit. That unit proposed a
two-input pair detector behind a three-predicate cascade; it was measured (handoff 40-42)
and declined as REDUNDANT, not ineffective -- see docs/status.md. The measurement that
killed the detector is the same one that found the gaps in section 2, so the regex below
is not new code on an untested idea: it is the one component of that work with known
behaviour, kept because it was measured on this exact corpus.

    python -m tools.coverage_audit

Exit code is the ALARM in sections 1 and 4: 1 if any row is unreconciled OR any row's
`latest_entry_at` disagrees with its derivation, 0 otherwise. Both expect 0. Sections
2 and 3 are REPORTS and are expected to be non-empty -- 7 and 1 as of 2026-08-13. Do
not read a non-zero count there as a failure.

(Section 4 was added 2026-08-14 and the exit code widened with it. It used to read
"the ALARM in section 1 only", which is why this line is restated rather than left to
be inferred from the code.)

--- section 1, the reconciliation alarm --------------------------------------
A row in `cases` matching no seed AND carrying no `superseded_by` is a row nothing
polls and nothing links. That is exactly the state KY, VA and NM sat in: the UW
tracker rewrote each state's row to point at its circuit appeal, the district row
stopped being seeded, and nothing noticed for weeks. This alarm would have fired on
07-28 and 07-31, days after each rewrite.

It replaces the cross-reference pair detector on the merits. That rule found 5 pairs,
all 5 real -- and all 5 already asserted, with zero rewrite signals across the nine
unlinked terminated rows. One join against a cascade of three predicates, a regex and
a corpus decision. Redundant against a cheaper instrument.

THE ORDERING TRAP (handoff 26 section 3, shipped as a bug once). The seed set is the
UNION of both sources: config/sources.yaml -> litigation.seed_cases (2) plus
data/doj_cases.json (32) = 34, which is the list `litigation.main()` actually
iterates. Against the ARTIFACT ALONE the numbers change and both are easy to misquote:
8 rows read unseeded rather than 6, and the ALARM reads 2 rather than 0 -- the two
extras being the config seeds, which are polled every run. 8 is the unseeded count and
2 is the alarm count; they are different questions and neither is the other. Reuse
`status_audit.seeded_keys` rather than rebuilding the join, so there is one definition
to be wrong in.

Join key is `(docket_number, court)`, exact by construction: `upsert_case` writes
`"court": seed.get("court")` straight off the seed.

--- section 2, unresolvable docket references --------------------------------
A docket number named in `case_entries.description` that matches no row psephos holds.
Every one on this corpus is a real reference to a real case, and four are coverage
defects worth acting on: `26-5243` is a D.C. Circuit appeal the project does not hold,
and `2:25-cv-09149` / `6:25-cv-01666` / `2:26-cv-00066` are the CA, OR and AZ DISTRICT
ORIGINALS sitting behind Ninth Circuit rows psephos does hold. Holding an appeal
without its underlying case is a gap nothing else in the project reports.

Corpus is `case_entries`, NEVER data/cases.json. The snapshot's `timeline` is built
from `items`, not `case_entries` -- half the rows (1,958 against 4,043) and the
survivors truncated near 200 characters -- so the text this rule reads is not in it.

DATES ARE STRIPPED FIRST, and they have to be. `held on 10-28-2025` yields `28-2025`
under the docket pattern, and `Date of Issuance: 10-30-2025` yields `30-2025`; both
appeared as "coverage gaps" before this filter. Residual risk is stated rather than
solved: a real circuit docket of the form `26-2025` sitting inside a date-shaped
string would be stripped with it. Full MM-DD-YYYY context is strong enough evidence to
take that trade, but it is a trade.

No cascade here. The pair-forming logic that used to sit on top of this regex is the
part that was declined; the parsing was never the weak half.

--- section 3, the cert watch list -------------------------------------------
Terminated circuit rows with no successor. A terminated DISTRICT row continues as an
appeal; a terminated CIRCUIT row's only continuation is a cert petition, and nothing
in psephos resolves one. Michigan `72347022` (6th Cir. 26-1225, AFFIRMED 06-24, en
banc petition 07-10) is the standing case -- en banc stays on the same docket, so it
is not a supersession, and no cert petition exists yet, so its NULL is correct today.

The shape IS reachable if it ever needs building: CourtListener carries 2,548 SCOTUS
dockets filed since 2026-01-01 with clean `docket_number` and `date_filed`. INSTRUMENT
NOTE -- query them with `date_filed__gte`. An unfiltered `order_by=-date_filed` returns
historical imports with NULL dates and duplicated ids, which reads as dead coverage.
"""
from __future__ import annotations

import re

import config
import db
from tools.status_audit import seeded_keys

# Year-dash forms only. District: 1:25-cv-03934. Circuit: 26-2684. The {3,5} tail is
# what excludes docket-entry brackets -- [6], [32] carry no dash and never match.
DISTRICT_DOCKET = re.compile(r"\b\d:\d{2}-[a-z]{2}-\d{4,5}\b", re.I)
CIRCUIT_DOCKET = re.compile(r"\b\d{2}-\d{3,5}\b")
DATE_LIKE = re.compile(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b")


def unreconciled(rows, seeded) -> list:
    """Section 1. Rows matching no seed and carrying no `superseded_by`."""
    return [r for r in rows
            if (r["docket_number"], r["court"]) not in seeded
            and r["superseded_by"] is None]


def unresolvable_refs(conn, held: set[str]) -> dict[str, list[tuple[str, str]]]:
    """Section 2. token -> [(naming case_id, the entry text)], dates stripped first."""
    found: dict[str, list[tuple[str, str]]] = {}
    for e in conn.execute("SELECT case_id, description FROM case_entries").fetchall():
        text = DATE_LIKE.sub(" ", e["description"] or "")
        for tok in set(DISTRICT_DOCKET.findall(text)) | set(CIRCUIT_DOCKET.findall(text)):
            if tok not in held:
                found.setdefault(tok, []).append(
                    (e["case_id"], " ".join((e["description"] or "").split())))
    return found


def classify_ref(tok: str, naming_courts: list[str], naming_dockets: list[str]) -> str:
    """Which KIND of gap a section-2 reference is. Three, not one.

    THE LIST USED TO BE UNDIFFERENTIATED AND WAS READ AS ONE CANDIDATE, which is
    what this exists to prevent. The distinction was already written down -- in this
    module's docstring -- and the docstring is not what a reader of the output sees.
    Information in the wrong place is not available.

      predecessor  a DISTRICT-form token named by a CIRCUIT row: psephos holds the
                   appeal and not the case under it. Seed and supersede FORWARD.
      successor    a CIRCUIT-form token named by a district row: psephos holds the
                   original and not what continued it. Seed and supersede BACKWARD.
      self-ref     the token is the naming row's OWN docket in another notation.
                   Arizona's local `CV-26-00066-PHX-SMB` renders the held
                   `2:26-cv-00066` as the token `26-00066`. Noise, not a gap.

    Self-reference is matched on DIGITS ONLY, after dropping the court-division
    prefix, so `26-00066` matches `2:26-cv-00066`. Residual risk is stated rather
    than solved, the same trade DATE_LIKE takes above: a genuine circuit docket
    whose digits happen to be a suffix of its naming row's district number would be
    dismissed as noise. Both regexes and both fields were already in hand.
    """
    digits = lambda s: re.sub(r"\D", "", s or "")
    if any(digits(d).endswith(digits(tok)) for d in naming_dockets if d):
        return "self-ref"
    is_district = bool(DISTRICT_DOCKET.fullmatch(tok))
    named_by_circuit = any((c or "").strip().endswith("Circuit") for c in naming_courts)
    if is_district and named_by_circuit:
        return "predecessor"
    if not is_district and not named_by_circuit:
        return "successor"
    return "reference"


def cert_watch(rows) -> list:
    """Section 3. Terminated circuit rows with no successor."""
    return [r for r in rows
            if (r["court"] or "").strip().endswith("Circuit")
            and (r["status"] or "").lower() == "terminated"
            and r["superseded_by"] is None]


def derived_drift(conn) -> list:
    """Section 4: rows where `cases.latest_entry_at` disagrees with its own derivation,
    MAX(case_entries.entry_at). An ALARM, expected 0.

    A derived column acquired 12 disagreements silently and nothing noticed for three
    weeks. `write_entries` assigned the max date_filed of the POLLED BATCH, correct
    while every poll was a full walk and wrong from c8b8b6f (2026-07-22) onward, when
    the batch became a date_modified window that can hold only a late-backfilled old
    filing. The column walked BACKWARDS -- West Virginia read 2026-05-15 while holding
    an entry from 2026-08-06 -- and the first thing to notice was a dormancy display
    built on it three weeks later, which reported a false positive on its first render.

    The check costs one statement and existed all along, which is the whole argument
    for it being here: the same alarm philosophy as section 1, applied to a column
    whose correctness nothing else asserts. The write path is fixed and the historical
    drift is repaired (scripts/repair_latest_entry.py), so a non-zero here is a NEW
    defect at an insert site, not the old one recurring.

    LEFT JOIN so a case with no entries appears rather than vanishing: NULL derived
    against a non-NULL stored is its own defect and should fire, not hide."""
    out = []
    for r in conn.execute(
        "SELECT c.case_id, c.court, c.docket_number, c.latest_entry_at AS stored, "
        "       MAX(e.entry_at) AS derived "
        "FROM cases c LEFT JOIN case_entries e ON e.case_id = c.case_id "
        "GROUP BY c.case_id ORDER BY c.case_id"
    ).fetchall():
        if r["stored"] != r["derived"]:
            out.append(r)
    return out


def main(argv=None) -> int:
    config.load_env()
    seeded = seeded_keys()
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT case_id, caption, court, docket_number, status, superseded_by "
            "FROM cases ORDER BY case_id").fetchall()
        held = {(r["docket_number"] or "").strip() for r in rows}
        unseeded = [r for r in rows if (r["docket_number"], r["court"]) not in seeded]
        alarm = unreconciled(rows, seeded)
        refs = unresolvable_refs(conn, held)
        watch = cert_watch(rows)
        drift = derived_drift(conn)

        print(f"coverage_audit: {len(rows)} cases, {len(seeded)} seed keys "
              f"(union of config seed_cases + the tracker artifact)\n")

        print(f"  [1] RECONCILIATION ALARM -- unseeded and unlinked: {len(alarm)}  (expect 0)")
        print(f"      {len(unseeded)} row(s) match no seed; the alarm is the subset of those")
        print("      with superseded_by IS NULL, i.e. polled by nothing and linked to nothing.")
        for r in alarm:
            print(f"        FIRES  {r['case_id']:<10} {str(r['docket_number']):<16} "
                  f"{r['court']}  {r['caption'][:40]}")
        for r in unseeded:
            if r["superseded_by"] is not None:
                print(f"        ok     {r['case_id']:<10} {str(r['docket_number']):<16} "
                      f"-> {r['superseded_by']}  {r['court']}")

        print(f"\n  [2] UNRESOLVABLE DOCKET REFERENCES: {len(refs)} distinct  (a report, not an alarm)")
        print("      predecessor = we hold the appeal, not the case under it (seed + supersede forward)")
        print("      successor   = we hold the original, not what continued it (seed + supersede back)")
        print("      self-ref    = the naming row's own docket in another notation; noise, not a gap")
        print("      NOT MONOTONIC UNDER SEEDING: holding a docket removes its token AND adds that")
        print("      docket's own entries to the corpus, which can surface further references.")
        by_case = {r["case_id"]: r for r in rows}
        for tok, occ in sorted(refs.items()):
            named = sorted({c for c, _ in occ})
            kind = classify_ref(
                tok,
                [by_case[c]["court"] for c in named if c in by_case],
                [by_case[c]["docket_number"] for c in named if c in by_case],
            )
            print(f"        {tok:<18} x{len(occ):<3} {kind:<12} named by {','.join(named)}")
            print(f"            {occ[0][1][:150]}")

        print(f"\n  [3] CERT WATCH -- terminated circuit rows, no successor: {len(watch)}")
        for r in watch:
            print(f"        {r['case_id']:<10} {str(r['docket_number']):<16} "
                  f"{r['court']}  {r['caption'][:40]}")

        print(f"\n  [4] DERIVED-COLUMN ALARM -- latest_entry_at != MAX(case_entries.entry_at): "
              f"{len(drift)}  (expect 0)")
        for r in drift:
            print(f"        FIRES  {r['case_id']:<10} {str(r['docket_number']):<16} "
                  f"stored {str(r['stored'])[:10]} != derived {str(r['derived'])[:10]}  "
                  f"{r['court']}")

        return 1 if (alarm or drift) else 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
