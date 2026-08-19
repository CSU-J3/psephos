"""The five pre-work reads for handoff 87's board homepage, in one pass. Writes nothing.

    python -m tools.board_prework

Handoff 87 section 2 asks for five reads against Turso before any of the board is
planned, because each one fills something the mock currently hardcodes: the map's fill
and the chart's cumulative red series (2a), a null-safety check on the scrub (2b), the
literal `cases.state` vocabulary the abbreviation map must resolve (2c), the map's
violet dots and the chart's monthly bars (2d), and the passed-bill list (2e). Running
them as five separate prompts costs five approvals and leaves the results in
scrollback rather than in the repo; this is the same five reads under one.

EXIT CODE IS ALWAYS 0. That is deliberate, and it is the opposite of
tools/coverage_audit, whose exit code IS its alarm. A disagreement here is not a
failure of the system -- it is a disagreement between live Turso and a figure the
handoff author read at authoring time, and handoff 87 section 2 already says which one
wins: "the query wins and the mock is wrong; report the difference before building on
it." That is a build decision and it belongs to a reader, so this tool reports and
exits 0. Do not wire it into CI expecting a non-zero signal.

What it measures: whether today's Turso rows match the specific figures section 2 states,
for 2a, 2b and 2d; and, for 2c, whether every stored `cases.state` resolves to a feature
the map actually draws. The value list under 2c is still a report -- it is the two set
differences beneath it that carry the verdict, because an unresolvable value is a
jurisdiction that disappears from a 51-cell map with no error, which is the one failure
such a map cannot show you.

What it CANNOT do, and must not be read as doing:

  - It cannot validate the mock. It compares Turso against the HANDOFF's numbers. Where
    the mock and the handoff disagree the handoff already wins by its own front matter;
    where the handoff and Turso disagree the query wins. This locates only the second
    kind of disagreement.

  - It cannot tell you a drift is wrong. Every count here moves: the cron runs every six
    hours and adds bills, entries and cases. Section 2a's figures and 2d's nine counts
    were read once, when the handoff was written. A larger number is the expected shape
    of a live system, not a defect. Read a FAIL as "the handoff's literal is now stale",
    then decide.

  - It cannot judge 2e, which states no expectation: the handoff itself calls that list
    untrustworthy as a count, since several status='4' rows are ceremonial resolutions.
    It prints in full and gets no verdict.

  - It does NOT test for the "Georgia (1)" / "Georgia (2)" suffixes, and section 6 should
    not either. Those live in `data/doj_cases.json`, which carries one row per DOCKET, and
    `collectors.litigation.normalize_state` strips them with `\\s*\\(\\d+\\)\\s*$` at the
    boundary where the artifact enters the database -- so `cases.state` holds a bare
    "Georgia" and has never held a suffixed value. 32 artifact rows collapse to 31 stored
    values. A map test asserting the suffix resolves would be asserting against data the
    schema cannot produce. "DC" is the real special case: it is stored as the code, while
    its feature is named "District of Columbia", which is why resolution tries both forms.

  - It cannot check anything that is not a database fact. The label anchors, the Albers
    geometry and the 51-jurisdiction coverage assertion in section 7 are geometry, not
    rows, and no query reaches them.

Read-only by construction: SELECT only, no --apply, no artifact written. Unlike
tools/status_audit it makes no network request beyond the database connection itself.
"""
from __future__ import annotations

import json
import os

import config
import db

# The 51 features the map draws. Section 4.1 moves this file into web/lib/us-states.json;
# until that commit lands it is the copy under docs/design/, so both are tried and the
# one actually read is printed. A missing file degrades 2c to the plain value dump rather
# than failing the run -- the geometry is not a database fact and 2c has other work.
GEOMETRY_PATHS = ("web/lib/us-states.json", "docs/design/psephos-us-states-albers.json")

# --- the expectations, quoted from handoff 87 section 2 ----------------------------
# Kept as literals beside the reads they judge, so a stale figure is visible here rather
# than buried in prose. These are the handoff's numbers, not the truth.
EXPECT_2A_PENDING = 25          # jurisdictions with at least one pending case
EXPECT_2A_NO_PENDING = 6        # jurisdictions with none
EXPECT_2A_CHAINED = 12          # jurisdictions with at least one superseded row
EXPECT_2A_EARLIEST = "2025-09-16"
EXPECT_2A_EARLIEST_STATE = "Oregon"
EXPECT_2A_ROWS = 31             # stated as "~31", so reported on, never failed on
EXPECT_2B = 0
EXPECT_2D = {"TX": 198, "WI": 59, "PA": 52, "AZ": 41, "GA": 39,
             "MI": 32, "OH": 24, "FL": 20, "NC": 19}

Q_2A = """SELECT state, MIN(filed_at) AS first_filed,
       SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
       COUNT(*) AS n,
       SUM(CASE WHEN superseded_by IS NOT NULL THEN 1 ELSE 0 END) AS chained
FROM cases WHERE state IS NOT NULL GROUP BY state ORDER BY first_filed"""

Q_2B = "SELECT COUNT(*) AS n FROM cases WHERE state IS NOT NULL AND filed_at IS NULL"

Q_2C = "SELECT DISTINCT state FROM cases WHERE state IS NOT NULL ORDER BY state"

Q_2D = """SELECT state, COUNT(*) AS bills,
       MIN(SUBSTR(last_action_at,1,7)) AS earliest,
       MAX(SUBSTR(last_action_at,1,7)) AS latest
FROM state_bills GROUP BY state ORDER BY bills DESC"""

Q_2E = """SELECT state, bill_number, status, last_action_at, SUBSTR(title,1,70) AS title
FROM state_bills WHERE status='4' ORDER BY last_action_at"""


def verdict(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def read_2a(conn) -> list:
    rows = conn.execute(Q_2A).fetchall()
    print("[2a] cases by state -- the map's fill and the chart's cumulative red series"
          f"   ({len(rows)} rows, handoff says ~{EXPECT_2A_ROWS})\n")
    print(f"      {'state':<18} {'first_filed':<12} {'pending':>7} {'n':>4} {'chained':>7}")
    for r in rows:
        print(f"      {str(r['state']):<18} {str(r['first_filed'] or '-'):<12} "
              f"{r['pending']:>7} {r['n']:>4} {r['chained']:>7}")

    pending = sum(1 for r in rows if r["pending"] > 0)
    no_pending = sum(1 for r in rows if r["pending"] == 0)
    chained = sum(1 for r in rows if r["chained"] > 0)
    earliest = rows[0]["first_filed"] if rows else None
    earliest_state = rows[0]["state"] if rows else None

    checks = [
        (pending == EXPECT_2A_PENDING,
         f"pending>0 {pending} (expect {EXPECT_2A_PENDING})"),
        (no_pending == EXPECT_2A_NO_PENDING,
         f"none {no_pending} (expect {EXPECT_2A_NO_PENDING})"),
        (chained == EXPECT_2A_CHAINED,
         f"chained>0 {chained} (expect {EXPECT_2A_CHAINED})"),
        (str(earliest or "").startswith(EXPECT_2A_EARLIEST),
         f"earliest {earliest} (expect {EXPECT_2A_EARLIEST})"),
        (EXPECT_2A_EARLIEST_STATE in str(earliest_state or ""),
         f"earliest state {earliest_state} (expect {EXPECT_2A_EARLIEST_STATE})"),
    ]
    ok = all(c[0] for c in checks)
    print(f"\n  {verdict(ok)} 2a -- " + "; ".join(m for _, m in checks))
    if len(rows) != EXPECT_2A_ROWS:
        print(f"       note: {len(rows)} rows against a stated '~{EXPECT_2A_ROWS}'; "
              "approximate by the handoff's own\n"
              "       wording, so reported and not failed on.")
    return rows


def read_2b(conn) -> None:
    n = conn.execute(Q_2B).fetchall()[0]["n"]
    print("\n[2b] cases with a state but no filed_at -- a NULL drops a jurisdiction out "
          f"of the scrub\n     with no error\n\n      {n}")
    print(f"\n  {verdict(n == EXPECT_2B)} 2b -- {n} (expect {EXPECT_2B})")


def load_geometry() -> tuple[list[dict], str | None]:
    """The map's 51 features, from whichever copy exists. Returns ([], None) if neither."""
    for path in GEOMETRY_PATHS:
        if os.path.exists(path):
            return json.load(open(path, encoding="utf-8")), path
    return [], None


def read_2c(conn) -> None:
    rows = conn.execute(Q_2C).fetchall()
    values = [r["state"] for r in rows]
    print("\n[2c] distinct cases.state -- the literal vocabulary the abbreviation map "
          f"must resolve\n     ({len(values)} values)\n")
    for v in values:
        print(f"      {v}")

    geom, path = load_geometry()
    if not geom:
        print("\n  geometry not found at either "
              f"{' or '.join(GEOMETRY_PATHS)}; set difference skipped.")
        return

    # A jurisdiction resolves if its stored value matches a feature's full name or its
    # two-letter code. Both forms are live: cases.state holds "Maine" but also "DC",
    # whose feature is named "District of Columbia".
    by_name = {f["name"]: f for f in geom}
    by_ab = {f["ab"]: f for f in geom}
    resolved = {}
    unresolved = []
    for v in values:
        f = by_name.get(v) or by_ab.get(v)
        if f is None:
            unresolved.append(v)
        else:
            resolved[f["ab"]] = v
    never_sued = sorted(f["ab"] for f in geom if f["ab"] not in resolved)

    print(f"\n  geometry: {len(geom)} features from {path}\n")
    print(f"  [2c-i]  state values with NO geometry: {len(unresolved)}  (must be 0)")
    for v in unresolved:
        print(f"            UNMAPPED  {v!r} -- would vanish from the map with no error")
    if not unresolved:
        print("            none; every stored value resolves to a drawn feature.")
    print(f"\n  [2c-ii] geometry with NO state value: {len(never_sued)}  (expect 20, "
          "the never-sued)")
    print("            " + " ".join(never_sued))
    ok = not unresolved and len(never_sued) == 20
    print(f"\n  {verdict(ok)} 2c -- {len(resolved)} sued + {len(never_sued)} never-sued "
          f"= {len(resolved) + len(never_sued)} of {len(geom)} features")
    print("\n  (the value list itself carries no expectation. the two set differences do: "
          "an\n   unmapped value is a jurisdiction the map drops silently, which is the "
          "one failure\n   a 51-cell map cannot show you.)")


def read_2d(conn) -> list:
    rows = conn.execute(Q_2D).fetchall()
    print("\n[2d] state_bills by state -- the map's violet dots and the chart's monthly "
          f"bars\n     ({len(rows)} rows, handoff says 9)\n")
    print(f"      {'state':<8} {'bills':>6}  {'earliest':<9} {'latest':<9}  handoff")
    got = {}
    for r in rows:
        want = EXPECT_2D.get(r["state"])
        if want is None:
            mark = "-"
        elif want == r["bills"]:
            mark = str(want)
        else:
            mark = f"{want}  <-- differs"
        got[r["state"]] = r["bills"]
        print(f"      {str(r['state']):<8} {r['bills']:>6}  {str(r['earliest']):<9} "
              f"{str(r['latest']):<9}  {mark}")

    missing = sorted(set(EXPECT_2D) - set(got))
    extra = sorted(set(got) - set(EXPECT_2D))
    differ = sorted(s for s in EXPECT_2D if s in got and got[s] != EXPECT_2D[s])
    ok = not (missing or extra or differ)
    detail = []
    if missing:
        detail.append("missing " + ",".join(missing))
    if extra:
        detail.append("unexpected " + ",".join(extra))
    if differ:
        detail.append("counts moved " + ", ".join(
            f"{s} {EXPECT_2D[s]}->{got[s]}" for s in differ))
    print(f"\n  {verdict(ok)} 2d -- {len(rows)} states (expect 9)"
          + ("; " + "; ".join(detail) if detail else "; all nine counts match"))
    return rows


def read_2e(conn) -> None:
    rows = conn.execute(Q_2E).fetchall()
    print("\n[2e] state_bills with status='4' (passed) -- for the record and for later "
          f"gate work\n     ({len(rows)} rows, handoff says ~26)\n")
    for r in rows:
        print(f"      {str(r['state']):<4} {str(r['bill_number']):<10} "
              f"{str(r['last_action_at']):<12} {r['title']}")
    print("\n  (no expectation enforced. the handoff states several of these are "
          "ceremonial\n   resolutions, which is why no count over this list is "
          "trustworthy without curation.)")


def main(argv=None) -> int:
    config.load_env()
    conn = db.connect()
    try:
        print("board_prework: handoff 87 section 2, five read-only reads against Turso.")
        print("Every count below moves with the cron. A FAIL means the handoff's literal "
              "is stale,\nnot that the system is broken. Exit code is 0 either way.\n")
        read_2a(conn)
        read_2b(conn)
        read_2c(conn)
        read_2d(conn)
        read_2e(conn)
        print("\nboard_prework: done. Nothing written.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
