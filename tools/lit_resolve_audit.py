"""Litigation docket-resolution audit (read-only, keeper).

Diagnoses why the litigation channel sits below the full 32-suit DOJ tracker list:
for every seed not yet bound to a real CourtListener docket, probe CourtListener the
same way the collector does and classify the miss, so it's clear whether Cases climbs
to 32 on its own (pending / RECAP-absent) or needs a follow-up (court-map fix or a
tie-breaker). That follow-up is a separate unit, not this tool.

The resolved-set baseline is read LIVE from Turso, not the committed data/cases.json
snapshot. The snapshot can lag Turso by up to one 6h cron; reading it on a stale local
checkout would misclassify already-resolved suits as unbound and double the
CourtListener probes. (This is the "live truth" alternative the handoff noted -- pick
one, not both.) It is a single read-only SELECT, not a collect run, so it does not
re-throttle CourtListener.

Budget: CourtListener's token is capped at 250 requests/day, shared with the
litigation collector (which spends most of it polling docket entries every 6h). This
audit spends up to 2 probes per unbound seed, so run it sparingly and ideally when the
collector has spare budget. If the daily cap is already hit, the first probe aborts the
run with the reset time rather than grinding every seed through pointless retries --
common.http_get now surfaces a daily-cap 429 as common.RateBudgetExhausted (while still
retrying a transient burst 429), so this tool just lets that propagate.

Run:  python -m tools.lit_resolve_audit
"""
from __future__ import annotations

import json
import os
import sys
import time

import common
import config
import db
from collectors import litigation

DOJ_CASES_PATH = "data/doj_cases.json"


def resolved_docket_numbers() -> set[str]:
    """Docket numbers already bound to a real CourtListener docket, read live from
    Turso. A numeric case_id marks a genuine resolution (stubs carry a slug case_id);
    this mirrors the snapshot's `str(case_id).isdigit()` test exactly."""
    if not os.environ.get("TURSO_DATABASE_URL"):
        print("WARNING: TURSO_DATABASE_URL is unset -- the resolved baseline is coming "
              "from the LOCAL SQLite db, which may be stale and skew the unbound set. "
              "Set it to audit against live Turso.", file=sys.stderr)
    conn = db.connect()
    rows = conn.execute("SELECT docket_number, case_id FROM cases").fetchall()
    return {dn for (dn, cid) in rows if dn and str(cid).isdigit()}


def load_seeds() -> list[dict]:
    with open(DOJ_CASES_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def probe(base: str, headers: dict, docket_number: str, court_id: str | None = None) -> list[dict]:
    """The collector's docket probe (see litigation.resolve_docket): strict when
    court_id is given, loose when it is dropped. Returns the raw results list.

    Via common.http_get, which throttles (PAGE_THROTTLE), surfaces a daily-cap 429 as
    common.RateBudgetExhausted for the caller to abort on, and retries a transient burst
    429. Any other persistent bad status raises for the caller to flag as a per-seed
    transient."""
    params = {"docket_number": docket_number}
    if court_id is not None:
        params["court"] = court_id
    data = common.http_get(f"{base}/dockets/", params=params, headers=headers,
                           throttle=litigation.PAGE_THROTTLE)
    return data.get("results") or []


def court_of(result: dict) -> str:
    """The court id of a docket result: the `court_id` field, else the tail of the
    `court` API URL (.../courts/<id>/)."""
    cid = result.get("court_id")
    if cid:
        return cid
    url = result.get("court") or ""
    return url.rstrip("/").rsplit("/", 1)[-1] or "?"


def main() -> int:
    config.load_env()
    sources = config.load_sources()
    lit = sources["litigation"]
    base = lit["api"]["base"].rstrip("/")
    token = config.require_env(lit["api"]["key_env"])
    headers = {"Authorization": f"Token {token}", "User-Agent": litigation.USER_AGENT}

    resolved = resolved_docket_numbers()
    seeds = load_seeds()
    unbound = [s for s in seeds if s.get("docket_number") not in resolved]

    print(f"{len(seeds)} seeds, {len(resolved)} resolved (live Turso), "
          f"{len(unbound)} unbound -- probing CourtListener\n")

    header = f"{'state':<16} {'docket':<15} {'court':<6} {'strict':>6} {'loose':>6}  verdict"
    print(header)
    print("-" * len(header))

    tally: dict[str, int] = {}
    for s in sorted(unbound, key=lambda x: x.get("state", "")):
        dn = s.get("docket_number")
        court_id = s.get("court_id")

        # Probe defensively. Two failure modes, handled differently:
        #  - daily budget spent (429) -> pointless to continue; abort with the reset.
        #  - one transient blip on this seed -> flag it and move on, don't kill the table.
        try:
            strict = len(probe(base, headers, dn, court_id))
            loose = strict
            courts: set[str] = set()
            if strict != 1:
                loose_results = probe(base, headers, dn)  # drop the court filter
                loose = len(loose_results)
                courts = {court_of(r) for r in loose_results}
        except common.RateBudgetExhausted as exc:
            secs = exc.reset_seconds
            when = f"~{secs:.0f}s (~{secs / 3600:.1f}h)" if secs else "unknown"
            classified = sum(tally.values())
            print(f"\nCourtListener daily budget (250/day) exhausted at {s.get('state','')} "
                  f"-- aborting. Resets in {when}; re-run then. "
                  f"{classified} seed(s) classified before the wall.")
            tally["budget-exhausted"] = tally.get("budget-exhausted", 0) + 1
            break
        except Exception as exc:
            tally["probe-error"] = tally.get("probe-error", 0) + 1
            print(f"{s.get('state',''):<16} {dn:<15} {court_id:<6} {'ERR':>6} {'ERR':>6}  "
                  f"probe-error: CourtListener failed ({type(exc).__name__}); re-run")
            time.sleep(litigation.PAGE_THROTTLE * 3)
            continue

        if strict == 1:
            cat, note = "would-bind", "pending poll / rate-limit skip; resolves next run"
        elif strict == 0 and loose == 0:
            cat, note = "recap-absent", "not in CourtListener yet (RECAP); appears on upload"
        elif strict == 0 and loose > 0:
            cat, note = "court-mismatch", f"found under {sorted(courts)}; fix the court map"
        else:
            cat, note = "ambiguous", f"{strict} matches; strict won't bind; needs a tie-breaker"
        tally[cat] = tally.get(cat, 0) + 1

        loose_disp = "-" if strict == 1 else str(loose)
        print(f"{s.get('state',''):<16} {dn:<15} {court_id:<6} {strict:>6} {loose_disp:>6}  "
              f"{cat}: {note}")

    print("\nsummary:")
    for cat, n in sorted(tally.items()):
        print(f"  {n:>2}  {cat}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
