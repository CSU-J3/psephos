"""One-off backfill: link existing state items to their first-class state bill.

The state channel shipped items-only, so the existing `items` rows have
state_bill_id null. This populates the state_bills dimension for every CURRENT
election bill -- one getMasterList per state, no getBill storm -- then links each
null state item to its bill by an exact title-prefix match.

Every state item title is "{state} {bill_number}: {action}", and a state_bills
row carries the same state and bill_number from the same source, so
"{state} {bill_number}:" is an exact key. The trailing ':' stops SB16 from
capturing SB160:.

Dry-run by default: it reports how many state items WOULD link and how many would
stay null, then rolls back untouched. Pass --apply to write. Same review-gated
discipline as the other one-off (the Weber cleanup): look, then apply. A few null
leftovers are expected -- bills no longer in the current session's masterlist.

GATED ON THE LEGISCAN LEDGER (handoff 98), dry-run included: the dry run makes the
same nine getMasterList calls, so it is admitted against the month's headroom in
`legiscan_usage` first (nine calls, 36 worst case) and refused if that does not fit.
Its attempts are written to the ledger in a commit of their own AFTER the rollback --
the dry run writes nothing to the record, but the queries were really spent. So it
needs Turso; see collectors.state.open_ledger.

Run from the repo root:
    python scripts/backfill_state_bills.py            # dry-run, writes nothing but the ledger
    python scripts/backfill_state_bills.py --apply     # link and commit
"""
from __future__ import annotations

import sys

import config
import db
from collectors.state import (THROTTLE, AllowanceSpent, UsageMeter, cap_signal_body,
                              election_match, get_masterlist, open_ledger,
                              record_spend_or_warn, tool_gate, upsert_state_bill)

# The link is scoped by EXISTS so rowcount counts only rows that actually match a
# bill (without it, the SET subquery would write NULL back onto unmatched rows and
# inflate the count). COUNT mirrors the same predicate for the dry-run preview.
_MATCH = ("EXISTS (SELECT 1 FROM state_bills sb "
          "WHERE items.title LIKE sb.state || ' ' || sb.bill_number || ':%')")

LINK_SQL = f"""
UPDATE items
   SET state_bill_id = (
       SELECT sb.state_bill_id FROM state_bills sb
        WHERE items.title LIKE sb.state || ' ' || sb.bill_number || ':%'
   )
 WHERE channel = 'state' AND state_bill_id IS NULL AND {_MATCH}
"""

COUNT_NULL = "SELECT COUNT(*) FROM items WHERE channel='state' AND state_bill_id IS NULL"
COUNT_WOULD_LINK = (f"SELECT COUNT(*) FROM items "
                    f"WHERE channel='state' AND state_bill_id IS NULL AND {_MATCH}")


def populate_dimension(conn, base, key, states, terms, throttle=THROTTLE, excludes=(),
                       meter=None) -> int:
    """One getMasterList per state; upsert a state_bills row for each election
    bill. No getBill -- the masterlist carries everything the LINK needs (state
    threaded in, bill_number from `number`). description/session stay null until a
    normal poll fetches the bill. Per-state try/except so one bad state doesn't
    sink the backfill. Returns the number of dimension upserts."""
    n = 0
    for state in states:
        try:
            master = get_masterlist(base, key, state, throttle, meter)
        except Exception as exc:
            body = cap_signal_body(exc)
            if body is not None:
                raise AllowanceSpent(body) from exc   # stop: every later state is wasted
            print(f"  {state:<3} ERROR: {exc}", file=sys.stderr)
            continue
        for raw in master:
            if not election_match(raw, terms, excludes):
                continue
            if raw.get("bill_id") is None:
                continue
            upsert_state_bill(conn, {}, raw, state)
            n += 1
    return n


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    apply = "--apply" in argv

    config.load_env()
    sources = config.load_sources()
    st = sources["state"]
    base = st["api"]["base"].rstrip("/") + "/"
    states = st.get("states", [])
    terms = st.get("terms", [])
    excludes = st.get("exclude_terms", [])
    key = config.require_env(st["api"]["key_env"])

    conn = open_ledger("backfill_state_bills")
    meter = UsageMeter()
    try:
        if not tool_gate(conn, len(states), st["monthly_cap"], "backfill_state_bills"):
            return 1
        before_null = conn.execute(COUNT_NULL).fetchone()[0]
        try:
            dim = populate_dimension(conn, base, key, states, terms, excludes=excludes,
                                     meter=meter)
        except AllowanceSpent as exc:
            print(f"  {exc}; stopped before linking, nothing written but the ledger. "
                  f"Body verbatim:\n{exc.body}", file=sys.stderr)
            return 1
        would_link = conn.execute(COUNT_WOULD_LINK).fetchone()[0]
        print(f"  state_bills upserted this run:        {dim}")
        print(f"  state items with null state_bill_id:  {before_null}")
        print(f"  would link:                           {would_link}")
        print(f"  would stay null:                      {before_null - would_link}"
              f"  (bills no longer in the current masterlist)")

        if not apply:
            conn.rollback()
            print("  DRY-RUN -- rolled back, nothing written. Re-run with --apply.")
            return 0

        linked = conn.execute(LINK_SQL).rowcount
        conn.commit()
        remaining = conn.execute(COUNT_NULL).fetchone()[0]
        print(f"  APPLIED -- linked {linked} items; {remaining} state items still null.")
    finally:
        # After the rollback or the commit, never inside either: the dry run's
        # rollback must not take the spend with it. A run that raised mid-populate
        # has an open transaction still, so discard it first -- flushing into it
        # would commit half a dimension under the ledger's name.
        if meter.pending:
            db.recover(conn)
            record_spend_or_warn(conn, meter, "backfill_state_bills")
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
