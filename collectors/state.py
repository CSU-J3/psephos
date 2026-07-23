"""State-legislation collector -- LegiScan API (channel 5).

State bills are first-class (5b-a): each getBill upserts a `state_bills` dimension
row and stamps `items.state_bill_id`, so the export renders per-bill timelines in
data/state_bills.json (parallel to bills/cases). bill_id/case_id stay null -- the
state channel keys on state_bill_id. State-level vehicle detection (is_vehicle,
via the getBill `sasts` array) is the deferred 5b-b follow-on; is_vehicle stays 0.

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
import re
import sys
from functools import lru_cache

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
        "state_bill_id": str(bill["bill_id"]),
        "content_hash": common.content_hash(CHANNEL, bill["bill_id"], action.get("date"), action_text),
        "raw_json": json.dumps(action, separators=(",", ":")),
    }


# --- election filter (phrase-aware) -----------------------------------------

@lru_cache(maxsize=None)
def _term_pattern(terms: tuple[str, ...]) -> "re.Pattern":
    """Compile the terms into one word-boundary alternation, cached per unique term
    tuple. The wrapping \\b...\\b is the whole point: a term matches only as a whole
    word or phrase, never inside a larger word."""
    alt = "|".join(re.escape(t.casefold()) for t in terms)
    return re.compile(r"\b(?:" + alt + r")\b")


@lru_cache(maxsize=None)
def _exclude_pattern(excludes: tuple[str, ...]) -> "re.Pattern":
    """Compile exclusion phrases into one alternation, cached. Internal whitespace
    matches a space OR hyphen so "voter approval" and "voter-approval" (a TX tax
    term of art that appears both ways) both redact from the haystack."""
    parts = [
        r"\b" + r"[\s\-]+".join(re.escape(t) for t in re.split(r"\s+", e.casefold())) + r"\b"
        for e in excludes
    ]
    return re.compile("|".join(parts))


def election_match(bill: dict, terms: list[str],
                   excludes: "tuple[str, ...] | list[str]" = ()) -> bool:
    """Keep a bill iff its title (or description) contains one of the terms as a
    WHOLE WORD/PHRASE, casefolded. Word-boundary, NOT substring: "absentee" does not
    match "absenteeism", "voter registration" matches only the phrase.

    Recall was measured against a nine-state masterlist corpus (handoff 9). Bare
    "election"/"ballot" stay OUT of `terms` -- their floods (ad-valorem-tax/bond
    elections, legislative-officer elections; tax propositions, corporate ballot-issue
    spending) are too large to redact around. Bare "voter"/"voting" ARE in `terms`
    (~80-85% real), so their residual noise is handled by REDACTION: each phrase in
    `excludes` is blanked from the haystack BEFORE the term match, so a bill matching
    ONLY via a noise phrase drops while one also carrying a real term survives. "voter
    approval of early voting" keeps on "early voting"; a bare "voter-approval tax rate"
    has nothing left to match."""
    if not terms:
        return False
    hay = (str(bill.get("title") or "") + " " + str(bill.get("description") or "")).casefold()
    if excludes:
        hay = _exclude_pattern(tuple(excludes)).sub(" ", hay)
    return bool(_term_pattern(tuple(terms)).search(hay))


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


# --- state_bills dimension --------------------------------------------------

def upsert_state_bill(conn, bill: dict, raw: dict, state: str) -> None:
    """Write or refresh the state_bills row. `raw` is the masterlist entry (always
    present); `bill` is the getBill payload when we fetched it, else {}. Prefer the
    richer getBill fields, fall back to masterlist. `state` is the polled state
    abbreviation, threaded in because the masterlist entry carries NO `state` key
    (only getBill does) -- without it the backfill (bill={}) would write state=''
    and its `state || ' ' || bill_number` title-prefix link would match nothing.
    `session` and `description` only exist on getBill, so they fill in on the poll
    that first fetches the bill; null before that is fine."""
    lid = raw.get("bill_id") or bill.get("bill_id")
    sess = bill.get("session")
    db.upsert(conn, "state_bills", {
        "state_bill_id": str(lid),
        "state": bill.get("state") or state or "",
        "bill_number": bill.get("bill_number") or raw.get("number") or "",
        "session": sess.get("session_name") if isinstance(sess, dict) else None,
        "title": bill.get("title") or raw.get("title"),
        "description": bill.get("description") or raw.get("description"),
        "status": str(bill.get("status") or raw.get("status") or "") or None,
        "url": bill.get("url") or bill.get("state_link") or raw.get("url") or "",
        "last_action": raw.get("last_action"),
        "last_action_at": common.to_iso(raw.get("last_action_date")),
        "change_hash": raw.get("change_hash") or bill.get("change_hash"),
        "updated_at": common.now_iso(),
    }, pk="state_bill_id")


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
            grade: tuple[str, str], budget: int, throttle: float,
            excludes: "tuple[str, ...] | list[str]" = ()) -> dict:
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
            if not election_match(raw, terms, excludes):
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
            # Fill/refresh the state_bills dimension from the fetched record before
            # writing its action items (items.state_bill_id references it).
            upsert_state_bill(conn, bill, raw, state)
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
    excludes = st.get("exclude_terms", [])
    budget = st.get("max_getbill_per_run", 500)
    grade = config.grade(st.get("default_grade"))
    key = config.require_env(st["api"]["key_env"])

    conn = db.connect()
    try:
        register_source(conn, base, grade[0], grade[1])
        conn.commit()
        results = collect(conn, base, key, states, terms, grade, budget, THROTTLE, excludes)
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
