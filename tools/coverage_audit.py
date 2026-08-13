"""Three read-only coverage questions about `cases`, in one pass. Writes nothing.

This is what survived the handoff 17 supersession-generator unit. That unit proposed a
two-input pair detector behind a three-predicate cascade; it was measured (handoff 40-42)
and declined as REDUNDANT, not ineffective -- see docs/status.md. The measurement that
killed the detector is the same one that found the gaps in section 2, so the regex below
is not new code on an untested idea: it is the one component of that work with known
behaviour, kept because it was measured on this exact corpus.

    python -m tools.coverage_audit

Exit code is the ALARM in section 1 only: 1 if any row is unreconciled, 0 otherwise.
Sections 2 and 3 are REPORTS and are expected to be non-empty -- 7 and 1 as of
2026-08-13. Do not read a non-zero count there as a failure.

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


def cert_watch(rows) -> list:
    """Section 3. Terminated circuit rows with no successor."""
    return [r for r in rows
            if (r["court"] or "").strip().endswith("Circuit")
            and (r["status"] or "").lower() == "terminated"
            and r["superseded_by"] is None]


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
        for tok, occ in sorted(refs.items()):
            named = sorted({c for c, _ in occ})
            print(f"        {tok:<18} x{len(occ):<3} named by {','.join(named)}")
            print(f"            {occ[0][1][:150]}")

        print(f"\n  [3] CERT WATCH -- terminated circuit rows, no successor: {len(watch)}")
        for r in watch:
            print(f"        {r['case_id']:<10} {str(r['docket_number']):<16} "
                  f"{r['court']}  {r['caption'][:40]}")

        return 1 if alarm else 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
