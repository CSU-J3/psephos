"""State-legislation collector -- LegiScan API (channel 5).

Items-only, mirroring the executive channel: state bills are leaf items with no
bill/case reference (bill_id/case_id null) and their own data/state.json. There is
no bills/cases linkage in this unit -- a state_bills dimension with per-bill
timelines is the noted 5b follow-on.

The change-hash pattern is the whole game (the free public tier is 30k
queries/month, and this stays in the tens per run):

  1. getMasterList(state) -- ONE query per state. Each bill carries a change_hash
     (the gate signal) plus title/description (the election filter needs them) and
     its LegiScan bill_id. NOT getMasterListRaw: the Raw variant omits
     title/description, so the title-based filter would match nothing live.
  2. Election filter on the raw title (phrase-aware; see election_match).
  3. change-hash gate: compare each kept bill's change_hash to the stored value
     (state_seen). Only bills whose hash MOVED (or are new) earn a getBill.
  4. getBill(id) on those -- the full record including the `history` array. One
     items row per history action (content_hash over bill_id + date + action;
     insert_ignore dedups, so re-running never double-writes).
  5. Store the new change_hash. A per-run getBill budget caps the work; the stored
     hash means the next run resumes exactly where this one stopped, no loss.

LegiScan calls are GET {base}?key={KEY}&op={OP}&...; success is {"status":"OK",...},
failure is {"status":"ERROR","alert":{...}} -- an ERROR is treated as a skip (it
surfaces through the per-state try/except in main), not a crash.

Run from the repo root:  python -m collectors.state
"""

from __future__ import annotations

import json
import sys

import common
import config
import db

SOURCE_ID = "legiscan"
CHANNEL = "state"
THROTTLE = 0.3  # courteous spacing; LegiScan caps by monthly volume, not a strict rate


def register_source(conn, base: str, gsource: str, ginfo: str) -> None:
    db.upsert(conn, "sources", {
        "id": SOURCE_ID,
        "name": "LegiScan API",
        "channel": CHANNEL,
        "kind": "api",
        "url": base,
        "admiralty_source": gsource,
        "admiralty_info": ginfo,
        "enabled": 1,
        "notes": "State legislation, election-filtered; change-hash polled to stay under the free-tier cap.",
    }, pk="id")


# --- mapping (the pure unit the tests drive) --------------------------------

def to_item(bill: dict, action: dict, gsource: str, ginfo: str) -> dict:
    """Map one getBill history action to an `items` row. `bill` is the normalized
    dict {bill_id, state, bill_number, url}; `action` is a history entry
    {date, action, chamber, ...}. content_hash keys on bill_id + date + action so
    the same action never lands twice (across runs or overlapping polls)."""
    action_text = action.get("action")
    return {
        "channel": CHANNEL,
        "source_id": SOURCE_ID,
        "source_url": bill.get("url") or "",
        "title": f"{bill['state']} {bill['bill_number']}: {action_text}"[:300],
        "summary": action_text,
        "occurred_at": common.to_iso(action.get("date")),
        "fetched_at": common.now_iso(),
        "admiralty_source": gsource,
        "admiralty_info": ginfo,
        "confidence": None,
        "bill_id": None,
        "case_id": None,
        "content_hash": common.content_hash(CHANNEL, bill["bill_id"], action.get("date"), action_text),
        "raw_json": json.dumps(action, separators=(",", ":")),
    }


# --- election filter (phrase-aware) -----------------------------------------

def election_match(bill: dict, terms: list[str]) -> bool:
    """Keep a bill iff its title (or description, if present) contains one of the
    WHOLE-PHRASE terms, casefolded. Whole-phrase, never word-split: "voter
    registration" is matched as a phrase, so a bill titled only "alien
    registration" does NOT match (bare "registration" is not a term). Same
    over-widening trap the executive relevance lens hit -- match on the title,
    don't loosen the phrases into their component words."""
    haystack = " ".join(
        str(bill.get(k) or "") for k in ("title", "description")
    ).casefold()
    return any(term.casefold() in haystack for term in terms)


# --- change-hash bookkeeping ------------------------------------------------

def seen_hash(conn, bill_id) -> str | None:
    row = conn.execute(
        "SELECT change_hash FROM state_seen WHERE bill_id = ?", (bill_id,)
    ).fetchone()
    return row["change_hash"] if row else None


def remember_hash(conn, bill_id, change_hash: str) -> None:
    db.upsert(conn, "state_seen", {
        "bill_id": bill_id,
        "change_hash": change_hash,
        "updated_at": common.now_iso(),
    }, pk="bill_id")


# --- LegiScan HTTP ----------------------------------------------------------

def _api(base: str, key: str, op: str, params: dict, throttle: float) -> dict:
    """One LegiScan call. Raises on a non-OK status so the caller's try/except
    turns it into a skip (per-state in main, per-bill in collect)."""
    query = {"key": key, "op": op, **params}
    data = common.http_get(base, params=query, throttle=throttle)
    if data.get("status") != "OK":
        alert = data.get("alert") or {}
        raise RuntimeError(f"LegiScan {op} status={data.get('status')}: {alert.get('message')}")
    return data


def get_masterlist(base: str, key: str, state: str, throttle: float) -> list[dict]:
    """getMasterList for a state. Each bill carries a change_hash (the gate signal)
    AND title/description (what election_match filters on) at one query per state.
    NOT getMasterListRaw: the Raw variant is leaner but returns only
    bill_id/number/change_hash -- no title/description -- so the title-based filter
    would match nothing live. The payload nests bills under numeric string keys
    with a `session` key mixed in; iterate the dict values, skip `session`."""
    data = _api(base, key, "getMasterList", {"state": state}, throttle)
    master = data.get("masterlist") or {}
    return [v for k, v in master.items() if k != "session" and isinstance(v, dict)]


def get_bill(base: str, key: str, bill_id, throttle: float) -> dict:
    """getBill -- the full record including the `history` array."""
    data = _api(base, key, "getBill", {"id": bill_id}, throttle)
    return data.get("bill") or {}


# --- collect ----------------------------------------------------------------

def collect(conn, base: str, key: str, states: list[str], terms: list[str],
            grade: tuple[str, str], budget: int, throttle: float) -> dict:
    """Poll each state on the change-hash pattern, write action items, return
    per-state counts. Per-state try/except so one bad state doesn't sink the run;
    per-bill try/except on getBill so one bad bill doesn't skip the rest of its
    state. `budget` caps getBill calls across the whole run -- an unfetched bill's
    hash is left unstored so the next run resumes it."""
    gsource, ginfo = grade
    results: dict[str, dict] = {}
    getbill_used = 0
    for state in states:
        counts = {"election_bills": 0, "changed": 0, "getbills": 0,
                  "new_items": 0, "errors": 0, "error_msg": None}
        try:
            master = get_masterlist(base, key, state, throttle)
        except Exception as exc:
            counts["error_msg"] = str(exc)
            results[state] = counts
            continue

        for raw in master:
            if not election_match(raw, terms):
                continue
            counts["election_bills"] += 1
            bill_id = raw.get("bill_id")
            change_hash = raw.get("change_hash")
            if bill_id is None:
                continue
            # change-hash gate: unchanged since last run -> no getBill.
            if change_hash is not None and seen_hash(conn, bill_id) == change_hash:
                continue
            counts["changed"] += 1
            if getbill_used >= budget:
                continue  # budget exhausted; leave hash unstored, resume next run
            try:
                bill = get_bill(base, key, bill_id, throttle)
            except Exception:
                counts["errors"] += 1
                continue
            getbill_used += 1
            counts["getbills"] += 1
            norm = {
                "bill_id": bill_id,
                "state": bill.get("state") or state,
                "bill_number": bill.get("bill_number") or raw.get("number"),
                "url": bill.get("url") or bill.get("state_link") or raw.get("url") or "",
            }
            for action in bill.get("history") or []:
                if db.insert_ignore(conn, "items", to_item(norm, action, gsource, ginfo)):
                    counts["new_items"] += 1
            # Store the masterlist change_hash -- the same value the gate compares
            # against next run -- so unchanged bills gate cleanly. (LegiScan's
            # masterlist and getBill hashes match; prefer the gate's own signal.)
            new_hash = change_hash or bill.get("change_hash")
            if new_hash:
                remember_hash(conn, bill_id, new_hash)

        results[state] = counts
    return results


def main() -> int:
    config.load_env()
    db.init_db()
    sources = config.load_sources()
    st = sources["state"]
    base = st["api"]["base"].rstrip("/") + "/"
    states = st.get("states", [])
    terms = st.get("terms", [])
    budget = st.get("max_getbill_per_run", 500)
    grade = config.grade(st.get("default_grade"))
    key = config.require_env(st["api"]["key_env"])

    conn = db.connect()
    try:
        register_source(conn, base, grade[0], grade[1])
        conn.commit()
        results = collect(conn, base, key, states, terms, grade, budget, THROTTLE)
        conn.commit()
        total = 0
        for state, c in results.items():
            if c["error_msg"]:
                print(f"  {state:<3} ERROR: {c['error_msg']}", file=sys.stderr)
                continue
            total += c["new_items"]
            extra = f", {c['errors']} bill error(s)" if c["errors"] else ""
            print(f"  {state:<3} {c['election_bills']:>3} election bills, "
                  f"{c['changed']:>3} changed, {c['getbills']:>3} getBill  "
                  f"+{c['new_items']} items{extra}")
        print(f"  total: +{total} items")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
