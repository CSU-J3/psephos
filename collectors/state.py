"""State-legislation collector -- LegiScan API (channel 5).

State bills are first-class (5b-a): each getBill upserts a `state_bills` dimension
row and stamps `items.state_bill_id`, so the export renders per-bill timelines in
data/state_bills.json (parallel to bills/cases). bill_id/case_id stay null -- the
state channel keys on state_bill_id. State-level vehicle detection (is_vehicle,
via the getBill `sasts` array) is the deferred 5b-b follow-on; is_vehicle stays 0.

The change-hash pattern is the whole game (the public tier is 10,000 queries a
month from 2026-10-01, every HTTP attempt counted; off-season this spends ~10 a
run, nine of them masterlists -- see "Monthly budget" below for what bounds the
rest):

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

Monthly budget (handoff 98). Every HTTP attempt is counted by a UsageMeter hooked
into common._get and written to the Turso `legiscan_usage` ledger in the same
per-state commit as the data. Each run reads the month's ledger total and prorates
what is left of `cron_ceiling` over the collect.yml slots left in the month
(run_budget): masterlists are paid first, getBill gets the remainder up to
`max_getbill_per_run`, and a run that cannot afford its masterlists plus one
getBill skips the channel and exits 0. Nothing is lost by skipping: an unfetched
bill has no stored hash, so the gate re-fetches it on the next run that can pay. If LegiScan itself says the
allowance is spent (cap_signal_body), the run stops calling it for the rest of the
run, prints the body once, and still exits 0.

Run from the repo root:  python -m collectors.state
"""

from __future__ import annotations

import calendar
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

import common
import config
import db

SOURCE_ID = "legiscan"
CHANNEL = "state"
# ~1.6 req/s ceiling before latency, under the ~2 req/s sliding window LegiScan
# enforces from 2026-10-01. 0.3 targeted ~3.3 req/s, over the window on a fast
# upstream day. A window 429 still takes common._get's retry path, which is right:
# the window moves. Every retry is a query against the monthly allowance, which is
# why this spacing is set to stay under the window rather than lean on the retry.
THROTTLE = 0.6

# collect.yml's four cron lines (`17 0 * * *`, `17 6 ...`, `17 12 ...`, `17 18 ...`)
# as (hour, minute) UTC. run_budget prorates over the slots left in the month, so
# this has to agree with the workflow; tests/test_legiscan_budget.py reads collect.yml and
# fails if the two drift apart.
CRON_SLOTS = ((0, 17), (6, 17), (12, 17), (18, 17))


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
        "notes": "State legislation, election-filtered; change-hash polled, every query "
                 "ledgered in legiscan_usage against the monthly allowance.",
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
    word or phrase, never inside a larger word.

    PHRASE terms (those with a space) also tolerate a plural on the last word --
    `election official` matches `election officials` too -- while BARE single-word
    tokens stay exact: `voter` never matches `voters`. The predicate is the space,
    not a whitelist. A phrase carries its own context, so pluralizing its head noun
    widens recall without widening the collision surface; a bare token has none, so
    `voters` collides with bond-referral, referendum, and civic-resolution language
    the singular never touched (handoff 12, measured: phrase plurals +19 at ~95%,
    bare `voters` +56 at ~45%)."""
    alt = "|".join(
        re.escape(t.casefold()) + (r"(?:es|s)?" if " " in t else "")
        for t in terms
    )
    return re.compile(r"\b(?:" + alt + r")\b")


@lru_cache(maxsize=None)
def _exclude_pattern(excludes: tuple[str, ...]) -> "re.Pattern":
    """Compile exclusion phrases into one alternation, cached. Internal whitespace
    matches a space OR hyphen so "voter approval" and "voter-approval" (a TX tax
    term of art that appears both ways) both redact from the haystack.

    Phrase excludes also tolerate a plural on the last word, symmetric with
    _term_pattern (handoff 12): "voter approvals" redacts like "voter approval".
    Zero plural excludes occur in today's corpus, so this has no behavior effect
    now -- it closes the term/exclude asymmetry before the corpus moves."""
    parts = [
        r"\b"
        + r"[\s\-]+".join(re.escape(t) for t in re.split(r"\s+", e.casefold()))
        + (r"(?:es|s)?" if " " in e else "")
        + r"\b"
        for e in excludes
    ]
    return re.compile("|".join(parts))


def election_match(bill: dict, terms: list[str],
                   excludes: "tuple[str, ...] | list[str]" = ()) -> bool:
    """Keep a bill iff its title (or description) contains one of the terms as a
    WHOLE WORD/PHRASE, casefolded. Word-boundary, NOT substring: "absentee" does not
    match "absenteeism", "voter registration" matches only the phrase. Phrase terms
    are plural-tolerant on the last word ("election officials"); bare tokens are not
    ("voters" does not match "voter") -- see _term_pattern for the why.

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


# --- LegiScan spend ledger --------------------------------------------------

LEDGER_TABLE = "legiscan_usage"


def _now() -> datetime:
    """The clock the ledger and the budget read. One function so tests can pin it."""
    return datetime.now(timezone.utc)


def ledger_month(now: datetime) -> str:
    """The ledger key for an instant: YYYY-MM of the UTC calendar month.

    THE RESET CLOCK IS AN ASSUMPTION UNTIL THE API STATUS PAGE IS READ (handoff 98
    D0.2). Neither the manual nor the 2026-09-23 email says whether the allowance
    resets on the UTC calendar month, a local one, or a rolling 30 days. This is
    the one function to change when that reading lands; the budget and the ledger
    both key on it, so they cannot disagree with each other."""
    return now.astimezone(timezone.utc).strftime("%Y-%m")


def ledger_used(conn, month: str) -> int:
    """Queries recorded against `month` so far -- by the cron and by every tool."""
    row = conn.execute(
        f"SELECT queries FROM {LEDGER_TABLE} WHERE month = ?", (month,)
    ).fetchone()
    return int(row["queries"]) if row else 0


class UsageMeter:
    """One process's LegiScan spend: every HTTP attempt, held in memory until a
    commit writes it to `legiscan_usage`.

    Passed to common._get as `on_attempt`, so it fires before EVERY attempt,
    retries and failures included -- LegiScan bills the request, not the logical
    call, and the 2026-08-28..09-07 exhaustion runs spent 36 attempts each on nine
    logical masterlists. Counts are keyed by ledger_month at the moment of the
    attempt, so a run straddling 00:00Z on the 1st books each attempt to the month
    it was spent in.

    flush() writes the pending counts into the caller's OPEN transaction and
    returns what it wrote; settle() forgets exactly that once the commit has
    succeeded. They are split so a failed commit leaves the counts pending for the
    next one: a discarded state loses its data, which the change-hash gate
    re-derives, but its spend really happened and has nowhere else to be recorded.

    KNOWN OVER-COUNT, accepted: a COMMIT that applies on Turso but whose response is
    lost (a transport reset, an edge 502) raises here, so settle() never runs and the
    next flush adds the same attempts again -- db.increment is additive. At most one
    state's attempts, and only ever on the safe side: later runs get a smaller share.
    An idempotent ledger (rows per run, SUM on read) would close it at the cost of a
    second table shape; not worth it for an error that cannot overspend.

    `cap_signal` holds the verbatim body of LegiScan saying the allowance is spent
    (see cap_signal_body). It lives here because this object is the run's account
    of its dealings with LegiScan, and main() prints it once."""

    def __init__(self):
        self.pending: dict[str, int] = {}
        self.run_total = 0
        self.cap_signal: str | None = None

    def __call__(self) -> None:
        month = ledger_month(_now())
        self.pending[month] = self.pending.get(month, 0) + 1
        self.run_total += 1

    def flush(self, conn) -> dict[str, int]:
        written = {m: n for m, n in self.pending.items() if n}
        stamp = common.now_iso()
        for month, n in sorted(written.items()):
            db.increment(conn, LEDGER_TABLE, "month", month, "queries", n,
                         {"updated_at": stamp})
        return written

    def settle(self, written: dict[str, int]) -> None:
        for month, n in written.items():
            left = self.pending.get(month, 0) - n
            if left > 0:
                self.pending[month] = left
            else:
                self.pending.pop(month, None)


def record_spend(conn, meter: UsageMeter) -> None:
    """Flush `meter` in a commit of its own. For callers with no per-state commit
    to ride on: the end of collect(), and the tools and scripts, whose data
    transaction may be rolled back (a dry run) while the spend still has to land."""
    written = meter.flush(conn)
    if written:
        conn.commit()
        meter.settle(written)


def record_spend_or_warn(conn, meter: UsageMeter, what: str) -> None:
    """record_spend, guarded: a ledger write that fails must not take down a run
    whose data is already durable, or mask the exception a tool is already
    raising. The one thing it may cost is these attempts' entry in the ledger, so
    it says so, with the count, on stderr.

    One retry after db.recover, because this flush typically follows the longest
    idle stretch the connection has -- minutes of HTTP with no statement -- which
    is exactly when a Hrana stream expires, and recover() hands back a fresh
    connection. The retry is safe: the flush is its own transaction and settle()
    runs only after a commit that returned."""
    for attempt in (1, 2):
        try:
            record_spend(conn, meter)
            return
        except Exception as exc:
            db.recover(conn)
            if attempt == 2:
                print(f"  {what}: ledger flush failed; {sum(meter.pending.values())} "
                      f"LegiScan attempt(s) are NOT in {LEDGER_TABLE}: {exc}",
                      file=sys.stderr)


def open_ledger(what: str):
    """Connect for a tool or script that spends LegiScan queries, and refuse unless
    the connection reached Turso. The ledger is only meaningful where the cron
    writes it: a tool reading a local SQLite ledger sees zero spent, admits itself
    against a full allowance, and records its spend where nothing else will ever
    count it. The queries are production spend whichever database the tool's own
    output goes to."""
    config.load_env()
    db.init_db()
    conn = db.connect()
    try:
        db.require_remote(conn, f"{what}'s LegiScan ledger")
    except Exception:
        conn.close()
        raise
    return conn


# --- monthly budget ---------------------------------------------------------

@dataclass(frozen=True)
class Budget:
    month: str
    used: int
    runs_left: int
    allowance: int     # this run's prorated share of the ceiling, masterlists included
    getbill: int       # what is left for getBill after the masterlists
    skip: str | None   # why this run spends nothing, or None to run: "ceiling" when the
                       # ceiling cannot pay for the masterlists, "share" when this run's
                       # prorated share cannot pay for the masterlists plus one getBill


def runs_left(now: datetime) -> int:
    """This run, plus every collect.yml slot still to come in now's UTC month.

    Counted from the clock rather than from "which slot is this run", because a
    scheduled run lands 2-6 hours after its slot and the clock cannot say which
    slot it was dispatched for. `1 + slots strictly after now` is exact for a run
    landing between its own slot and the next, over-counts by one for a previous
    month's run landing after 00:00Z on the 1st (a smaller allowance, the safe
    side), and under-counts by one only for a run landing more than six hours
    late, which the ceiling check still bounds."""
    now = now.astimezone(timezone.utc)
    last_day = calendar.monthrange(now.year, now.month)[1]
    later = sum(
        1
        for day in range(now.day, last_day + 1)
        for hour, minute in CRON_SLOTS
        if datetime(now.year, now.month, day, hour, minute, tzinfo=timezone.utc) > now
    )
    return 1 + later


def run_budget(used: int, cron_ceiling: int, n_states: int, max_getbill: int,
               now: datetime) -> Budget:
    """Prorate the rest of the month's cron ceiling over the runs left in it.

    allowance = floor((cron_ceiling - used) / runs_left). Masterlists are paid
    first, because without them nothing is detected and getBill has nothing to
    fetch; getBill gets `allowance - n_states`, capped by `max_getbill`, floored at
    0. If the ceiling cannot cover even this run's masterlists, or this run's share
    cannot buy them plus one getBill (the amendment below), skip the channel.

    PRORATION IS THE POINT. A flat per-run cap (500 x ~124 runs = 62,000) lets an
    in-session storm spend the month in its first week and blind the channel for
    the rest of it. Prorated, a storm is metered out over the month instead, and
    a quiet run's unspent share rolls forward into every later run's allowance.

    `used` is the whole month's ledger, tools included, so the cron yields to a
    tool run rather than the two together overrunning the ceiling. The allowance
    is in queries but getBill is budgeted in calls; retries can overshoot a run's
    allowance, and because they are ledgered, the next run's allowance absorbs
    it."""
    left = runs_left(now)
    allowance = max(0, (cron_ceiling - used) // left)
    if used + n_states > cron_ceiling:
        skip = "ceiling"
    elif allowance - n_states < 1:
        # AMENDMENT TO THE HANDOFF'S RULE (review of this unit, 2026-09-23). A run whose
        # share cannot buy one getBill spends its masterlists and STORES NOTHING: hashes,
        # dimension rows and items are all written only after a getBill. Worse, each
        # such run lowers the next run's share, so the channel spends ~9 a run for the
        # rest of the month to learn nothing. Skipping instead lets the share accumulate
        # until a run can afford at least one bill. Fires only in an already-overspent
        # month: a normal one prorates to ~64 a run.
        skip = "share"
    else:
        skip = None
    getbill = 0 if skip else max(0, min(max_getbill, allowance - n_states))
    return Budget(ledger_month(now), used, left, allowance, getbill, skip)


def tool_gate(conn, calls: int, monthly_cap: int, what: str) -> bool:
    """Admit or refuse a tool or script run against the month's remaining headroom.

    Prints the declared worst case -- `calls` logical calls times common.MAX_RETRIES
    attempts, since every attempt is a query -- against `monthly_cap - used`, and
    returns False (having said why) when it does not fit. Measured against the CAP,
    not the cron ceiling: the 1,500 the ceiling leaves free is exactly what tools
    are for. sasts_dump is ~484 calls, ~1,936 worst case: fine once a month, bad
    by accident, which is what this is for."""
    month = ledger_month(_now())
    used = ledger_used(conn, month)
    conn.commit()     # end the read: a tool's HTTP window is minutes long (see main())
    headroom = monthly_cap - used
    worst = calls * common.MAX_RETRIES
    print(f"  {what}: declared worst case {worst} LegiScan queries "
          f"({calls} call(s) x {common.MAX_RETRIES} attempts) against headroom "
          f"{headroom} ({used} of {monthly_cap} used in {month})")
    if worst > headroom:
        print(f"  {what}: REFUSED -- the worst case does not fit this month's "
              f"remaining LegiScan allowance. Nothing was called.", file=sys.stderr)
        return False
    return True


# --- LegiScan HTTP ----------------------------------------------------------

class LegiScanError(RuntimeError):
    """A {"status": "ERROR"} payload. The message keeps the shape it always had;
    `body` carries the whole payload verbatim, because the monthly-allowance
    response has never been seen and has to be printed as received (A4)."""

    def __init__(self, op: str, data: dict):
        # The manual documents `alert` as {"message": ...}; tolerate a bare string too,
        # since the response this exists for has never been seen, and failing to build
        # the exception would lose the one body worth classifying.
        alert = data.get("alert")
        message = alert.get("message") if isinstance(alert, dict) else alert
        self.alert_message = str(message or "")
        self.body = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        super().__init__(f"LegiScan {op} status={data.get('status')}: {message}")


def names_allowance_limit(text: str) -> bool:
    """Does this response text name LegiScan's monthly or query allowance?
    Case-insensitive: "limit" together with "month" or "query".

    THE REAL RESPONSE SHAPE HAS NOT BEEN SEEN YET. Neither the API manual (rev.
    20250317) nor the 2026-09-23 email says what an exhausted allowance returns: an
    HTTP 429, a status=ERROR alert, or both, and in what words. This predicate is
    the brief's (Corey, 2026-09-23), chosen to name the thing without guessing its
    exact string. It is CONFIRMED ON FIRST SIGHTING: the first body that trips it,
    or that should have and did not, is recorded verbatim in docs/status.md with
    its run id, and this function is corrected against it then.

    Two words, not one. "month" alone fires on an unrelated parameter error;
    "limit" alone fires on the ~2 req/s window's own 429 -- which is harmless only
    because that 429 clears on retry and cap_signal_body never consults a response
    that cleared."""
    t = text.casefold()
    return "limit" in t and ("month" in t or "query" in t)


def cap_signal_body(exc: BaseException) -> str | None:
    """The verbatim body to print if `exc` means LegiScan's allowance is spent, else
    None. ONLY TWO SHAPES stop the run, and everything else keeps its old meaning
    (a bill-level failure skips the bill, a state-level one skips the state):

      (a) a 429 or 5xx that has used up EVERY retry, whose LAST body names the limit.
          RetriesExhausted carries that last status and body. A RateBudgetExhausted
          counts here too: common raises it on a 429 whose scope cannot clear inside
          the retry ladder, which is the same judgment -- retrying is futile -- made
          before the ladder instead of at its end. It is still held to the body test.
      (b) a status=ERROR payload whose ALERT MESSAGE names the limit. The message,
          not the whole payload: the verdict is what LegiScan said, not what some
          other field happens to contain.

    Not on the list, deliberately: a 4xx HttpError (a 403 is per-item, whatever it
    says), a transport exhaustion (no body at all), and any 429 that cleared on
    retry -- that is the ~2 req/s window, and it never raises in the first place."""
    if isinstance(exc, common.RetriesExhausted):
        status = exc.status
        if status is not None and (status == 429 or status >= 500) \
                and names_allowance_limit(exc.body):
            return exc.body
        return None
    if isinstance(exc, common.RateBudgetExhausted):
        return exc.body if names_allowance_limit(exc.body) else None
    if isinstance(exc, LegiScanError):
        return exc.body if names_allowance_limit(exc.alert_message) else None
    return None


class AllowanceSpent(RuntimeError):
    """Raised by a tool or script that got a cap signal: stop calling LegiScan now.
    The collector does not raise it -- it records the signal on its meter and ends
    the run with exit 0 -- but a tool has no next run to resume, and an artifact
    written from a half-finished dump would read as complete. So the tool stops,
    its finally still ledgers the spend, and main() prints the body and exits 1."""

    def __init__(self, body: str):
        self.body = body
        super().__init__("LegiScan signalled its allowance is spent")


def _api(base: str, key: str, op: str, params: dict, throttle: float,
         meter: UsageMeter | None = None) -> dict:
    """One LegiScan call. Raises on a non-OK status so the caller's try/except
    turns it into a skip (per-state in main, per-bill in collect). `meter` counts
    every HTTP attempt the call makes; pass one wherever the spend should reach
    the ledger, which is everywhere outside a test."""
    query = {"key": key, "op": op, **params}
    data = common.http_get(base, params=query, throttle=throttle, on_attempt=meter)
    if data.get("status") != "OK":
        raise LegiScanError(op, data)
    return data


def get_masterlist(base: str, key: str, state: str, throttle: float,
                   meter: UsageMeter | None = None) -> list[dict]:
    """getMasterList for a state. Each bill carries a change_hash (the gate signal)
    AND title/description (what election_match filters on) at one query per state.
    NOT getMasterListRaw: the Raw variant is leaner but returns only
    bill_id/number/change_hash -- no title/description -- so the title-based filter
    would match nothing live. The payload nests bills under numeric string keys
    with a `session` key mixed in; iterate the dict values, skip `session`."""
    data = _api(base, key, "getMasterList", {"state": state}, throttle, meter)
    master = data.get("masterlist") or {}
    return [v for k, v in master.items() if k != "session" and isinstance(v, dict)]


def get_bill(base: str, key: str, bill_id, throttle: float,
             meter: UsageMeter | None = None) -> dict:
    """getBill -- the full record including the `history` array."""
    data = _api(base, key, "getBill", {"id": bill_id}, throttle, meter)
    return data.get("bill") or {}


# --- collect ----------------------------------------------------------------

def collect(conn, base: str, key: str, states: list[str], terms: list[str],
            grade: tuple[str, str], budget: int, throttle: float,
            excludes: "tuple[str, ...] | list[str]" = (),
            meter: UsageMeter | None = None) -> dict:
    """Poll each state on the change-hash pattern, write action items, return
    per-state counts. Per-state try/except so one bad state doesn't sink the run;
    per-bill try/except on getBill so one bad bill doesn't skip the rest of its
    state. `budget` caps getBill calls across the whole run -- an unfetched bill's
    hash is left unstored so the next run resumes it.

    `meter` counts every LegiScan attempt (one is made if none is passed), and its
    pending count rides in each state's commit, so the ledger shares the data's
    boundary. A state whose commit fails keeps its count PENDING rather than losing
    it: the next state's commit carries it, and a final flush after the loop
    catches whatever is left -- including a run whose every masterlist failed,
    which commits no state at all and is exactly the run that spends the most.

    A cap signal (cap_signal_body) stops the run calling LegiScan: the current
    state's completed bills still commit, every later state is reported as
    `skipped` without a request, and the body is left on `meter.cap_signal`.

    THIS FUNCTION OWNS ITS TRANSACTION BOUNDARY and commits once per state; it used
    to commit nothing and leave that to main(). A caller should not assume it can
    still wrap the whole poll in one transaction. The failure mode that buys is
    per-state partials: completed states are durable, the failing state is
    discarded whole, later states are still attempted. That is safe because the
    change-hash gate makes it resumable -- a bill whose hash never committed has no
    stored hash, so the next run re-fetches it, and items dedup on content_hash."""
    gsource, ginfo = grade
    meter = meter if meter is not None else UsageMeter()
    results: dict[str, dict] = {}
    getbill_used = 0
    for state in states:
        counts = {"election_bills": 0, "changed": 0, "getbills": 0,
                  "new_items": 0, "errors": 0, "error_msg": None, "skipped": None}
        try:
            master = get_masterlist(base, key, state, throttle, meter)
        except Exception as exc:
            counts["error_msg"] = str(exc)
            results[state] = counts
            body = cap_signal_body(exc)
            if body is not None:
                meter.cap_signal = body
                break
            continue

        # THE BATCH BOUNDARY IS THE STATE (handoff 81). Everything below writes to
        # the database, and none of it was guarded: the two handlers in this
        # function wrap getMasterList and getBill, which are pure HTTP, so a stream
        # failure here propagated out of collect(), past main()'s except-less
        # try/finally, and exited non-zero. That is not merely this collector's
        # batch -- state runs last of six lines in one `bash -e` step, and Export
        # and Commit are separate steps with no `if: always()`, so the run loses
        # its snapshot and data commit too. (Not its data: the other five
        # collectors have already committed to Turso.)
        #
        # The 2026-08-15 incident is the near miss that shows the shape. All nine
        # states failed -- at getMasterList, inside a handler, so the run survived
        # and printed nine ERROR lines. Four lines further down it would have taken
        # the whole run.
        #
        # Committing per state bounds the loss to one state. db.recover, never a
        # bare rollback: here `conn` IS the failure, and rollback() on a dead Hrana
        # stream raises and takes down the run this handler exists to keep alive.
        try:
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
                # Charged BEFORE the call, succeed or fail. The budget is the monthly
                # spend guard now, and a failed getBill spends up to MAX_RETRIES queries:
                # charging only successes let a getBill-side outage walk the whole
                # changed backlog at 4 attempts a bill (review of this unit, measured
                # offline: 200 changed bills, budget 128, 801 attempts). counts["getbills"]
                # still counts successes only.
                getbill_used += 1
                try:
                    bill = get_bill(base, key, bill_id, throttle, meter)
                except Exception as exc:
                    counts["errors"] += 1
                    body = cap_signal_body(exc)
                    if body is not None:
                        # Stop fetching, but fall through to the commit below: the
                        # bills this state already fetched are good and stay.
                        meter.cap_signal = body
                        break
                    continue
                counts["getbills"] += 1
                norm = {
                    "bill_id": bill_id,
                    "state": bill.get("state") or state,
                    "bill_number": bill.get("bill_number") or raw.get("number"),
                    "url": bill.get("url") or bill.get("state_link") or raw.get("url") or "",
                }
                # Fill/refresh the state_bills dimension from the fetched record
                # before writing its action items (items.state_bill_id references it).
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
            # The ledger rides in the state's own commit: same boundary as the data.
            written = meter.flush(conn)
            conn.commit()
            meter.settle(written)
        except Exception as exc:
            db.recover(conn)
            # new_items is zeroed rather than reported: those rows were rolled back,
            # and a count claiming rows that no longer exist is the kind of plausible
            # wrong number this project keeps finding. The attempt counters stay --
            # they describe work done, and the API calls were really spent. So does
            # the meter's pending count, which was never settled: it goes out with
            # the next commit that succeeds.
            counts["new_items"] = 0
            counts["error_msg"] = f"batch discarded after a write failure: {exc}"

        results[state] = counts
        if meter.cap_signal is not None:
            break

    for state in states:
        if state not in results:
            results[state] = {"election_bills": 0, "changed": 0, "getbills": 0,
                              "new_items": 0, "errors": 0, "error_msg": None,
                              "skipped": "LegiScan signalled its allowance is spent "
                                         "earlier in this run; no request made"}

    # Whatever no state commit carried: failed masterlists after the last good
    # state, a discarded last state, or a run in which nothing committed at all.
    # Guarded like the per-state write path, and for the same reason -- a dead
    # stream here must not take down a run whose data is already durable.
    if meter.pending:
        record_spend_or_warn(conn, meter, "state")
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
    max_getbill = st.get("max_getbill_per_run", 500)
    monthly_cap = st["monthly_cap"]
    cron_ceiling = st["cron_ceiling"]
    grade = config.grade(st.get("default_grade"))
    key = config.require_env(st["api"]["key_env"])

    conn = db.connect()
    try:
        register_source(conn, base, grade[0], grade[1])
        conn.commit()

        now = _now()
        used = ledger_used(conn, ledger_month(now))
        # End the read before any HTTP. _Conn marks itself _pending on EVERY statement,
        # reads included, and a pending connection refuses the one-shot stale-stream
        # reopen -- so without this, a Hrana stream that expires during TX's masterlist
        # (or during a long all-states-failing run) fails the first write instead of
        # reopening. collect() used to start straight after a commit; this restores that.
        conn.commit()
        plan = run_budget(used, cron_ceiling, len(states), max_getbill, now)
        print(f"  ledger {plan.month}: {plan.used} of {cron_ceiling} cron ceiling used "
              f"({monthly_cap} monthly cap); {plan.runs_left} run(s) left incl. this one "
              f"-> allowance {plan.allowance}, getBill budget {plan.getbill}")
        if plan.skip:
            # Exit 0 on purpose: nothing is wrong, and nothing is lost -- no hash is
            # stored for a bill this run did not fetch, so the gate picks every one
            # of them up on the next run that can pay (at the latest, the 1st).
            if plan.skip == "ceiling":
                print(f"state: monthly ceiling reached (used {plan.used} of {cron_ceiling}), "
                      f"skipping")
            else:
                print(f"state: this run's prorated share ({plan.allowance}) cannot pay for "
                      f"{len(states)} masterlists plus one getBill (used {plan.used} of "
                      f"{cron_ceiling}, {plan.runs_left} run(s) left), skipping")
            return 0

        meter = UsageMeter()
        results = collect(conn, base, key, states, terms, grade, plan.getbill, THROTTLE,
                          excludes, meter=meter)
        # collect() now commits per state, so this is a no-op tail rather than the
        # run's only commit. Kept because it costs nothing and still closes any
        # transaction a future edit opens between the last state and here.
        conn.commit()
        total = 0
        for state, c in results.items():
            if c["skipped"]:
                print(f"  {state:<3} skipped: {c['skipped']}")
                continue
            if c["error_msg"]:
                print(f"  {state:<3} ERROR: {c['error_msg']}", file=sys.stderr)
                continue
            total += c["new_items"]
            extra = f", {c['errors']} bill error(s)" if c["errors"] else ""
            print(f"  {state:<3} {c['election_bills']:>3} election bills, "
                  f"{c['changed']:>3} changed, {c['getbills']:>3} getBill  "
                  f"+{c['new_items']} items{extra}")
        print(f"  total: +{total} items")
        print(f"  LegiScan queries this run: {meter.run_total} HTTP attempt(s), "
              f"retries included")
        if meter.cap_signal is not None:
            # Printed ONCE, verbatim. Nobody has seen this response yet; the first
            # one is how it gets classified, so it must arrive unedited.
            print("state: LegiScan signalled its allowance is spent; remaining states "
                  "skipped. Body verbatim:")
            print(meter.cap_signal)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
