"""State-legislation collector -- LegiScan API (channel 5).

State bills are first-class (5b-a): each getBill upserts a `state_bills` dimension
row and stamps `items.state_bill_id`, so the export renders per-bill timelines in
data/state_bills.json (parallel to bills/cases). bill_id/case_id stay null -- the
state channel keys on state_bill_id. State-level vehicle detection (is_vehicle,
via the getBill `sasts` array) is the deferred 5b-b follow-on; is_vehicle stays 0.

ONE SLOT A DAY, BY SESSION (handoff 98b §4, ruled 2026-09-24). The channel runs on
the 06:17Z collect.yml slot only; the other three print `state: not this slot`. A
cadence cut for waste, not a compliance fix: the manual rates getMasterList at 1 hour
and calls daily sufficient, and the old 6-hourly poll was inside both -- but 86% of
September's requests found nothing new and still spent the allowance.

  0. The state_id bootstrap, once: getSessionList&state=XX per watched state not yet
     measured (nine on the first run after deploy). The manual's example session
     names its state only by state_id and publishes no mapping, so the ids are
     MEASURED and stored in state_sessions, never typed here; the table is printed
     once. (The live reply also carries state_abbr, which checks the mapping on every
     call -- see _abbr_conflicts.) A state whose bootstrap fails is polled by `state=`
     meanwhile.
  1. getSessionList, national and bare, once a day: sine_die / prefile / prior /
     dataset_hash for every session of every watched state, into state_sessions.
  2. Plan, per non-prior session: ACTIVE (sine_die = 0, or prefile = 1) sessions poll
     when the previous ET day was Mon-Fri, so the Tue-Sat slots poll and Sun/Mon skip;
     ADJOURNED sessions poll only when their dataset_hash has moved since the last
     master list fully processed for them, and otherwise cost ZERO calls.
  3. getMasterList&id=SESSION_ID per planned session -- "Invocation A" (page 9); the
     `state=` form is "current session only (use with caution)". By id, a special
     session beside the regular one is covered. Each list must pass the URL tripwire:
     a session whose bill URLs (or session block) name another state is refused and
     nothing is written for it. NOT getMasterListRaw: the Raw variant omits
     title/description, so the title-based filter would match nothing live.
  4. Election filter on the raw title (phrase-aware; see election_match), then the
     change-hash gate against state_seen: only bills whose hash MOVED (or are new)
     earn a getBill -- the full record with its `history`, one items row per action
     (content_hash dedup, so re-running never double-writes).
  5. Store the new change_hash. The getBill budget caps the work; an unfetched bill
     keeps no stored hash, so a later run resumes exactly where this one stopped.

LegiScan calls are GET {base}?key={KEY}&op={OP}&...; success is {"status":"OK",...},
failure is {"status":"ERROR","alert":{...}} -- an ERROR is treated as a skip (it
surfaces through the per-target try/except in collect), not a crash.

Monthly budget (handoff 98). Every HTTP attempt is counted by a UsageMeter hooked
into common._get and written to the Turso `legiscan_usage` ledger in the same
commit as the data, beside the cache-hit proxy (answered master lists, and those
that moved no stored hash). Each run reads the month's ledger total and prorates
what is left of `cron_ceiling` over the daily state slots left in the month
(run_budget): the session calls and master lists are paid first, getBill gets the
remainder up to `max_getbill_per_run`, and a run that cannot afford them plus one
getBill skips its master lists and exits 0. Nothing is lost by skipping. If
LegiScan itself says the allowance is spent (cap_signal_body), the run stops calling
it for the rest of the run, prints the body once, and still exits 0.

Run from the repo root:  python -m collectors.state
"""

from __future__ import annotations

import calendar
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

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

# THE STATE COLLECTOR RUNS ON ONE SLOT A DAY (handoff 98b §4a). collect.yml fires
# four times a day and passes the firing cron line as SLOT; every other slot skips
# the channel. run_budget prorates over these slots only, so STATE_SLOTS has to agree
# with STATE_SLOT, and STATE_SLOT has to be one of collect.yml's cron lines --
# tests/test_legiscan_budget.py reads the workflow and fails if they drift apart.
# 06:17Z is the brief's fallback: the manual names no refresh time (page 7, read
# 2026-09-24), so there is no "first slot after LegiScan's refresh" to pick.
STATE_SLOT = "17 6 * * *"
STATE_SLOTS = ((6, 17),)

# Active sessions poll when the PREVIOUS ET day was Mon-Fri, so the Tue-Sat slots poll
# and Sun/Mon skip (handoff 98b §4c, ruled). The zone, not a fixed offset: 06:17Z is
# 02:17 EDT or 01:17 EST, and the tests cross the 2026-11-01 change. tzdata supplies
# the zone on Windows (requirements.txt).
ET = ZoneInfo("America/New_York")


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

    COUNTERS = ("queries", "masterlists", "unchanged_masterlists")

    def __init__(self):
        # month -> {counter: n}. A month is present only while something is owed, so
        # `if meter.pending` still reads "is there anything to flush".
        self.pending: dict[str, dict[str, int]] = {}
        self.run_total = 0
        self.cap_signal: str | None = None

    def _bump(self, counter: str, n: int = 1) -> None:
        month = ledger_month(_now())
        row = self.pending.setdefault(month, {c: 0 for c in self.COUNTERS})
        row[counter] += n

    def __call__(self) -> None:
        self._bump("queries")
        self.run_total += 1

    def masterlist(self, unchanged: bool) -> None:
        """One ANSWERED getMasterList, and whether it moved no stored change_hash --
        the client-side proxy for the API Status page's cache hits (handoff 98b §4d).
        Not an HTTP attempt; those are counted by __call__."""
        self._bump("masterlists")
        if unchanged:
            self._bump("unchanged_masterlists")

    def pending_queries(self) -> int:
        return sum(row["queries"] for row in self.pending.values())

    def flush(self, conn) -> dict[str, dict[str, int]]:
        written = {m: dict(row) for m, row in self.pending.items() if any(row.values())}
        stamp = common.now_iso()
        for month, row in sorted(written.items()):
            db.increment(conn, LEDGER_TABLE, "month", month, row, {"updated_at": stamp})
        return written

    def settle(self, written: dict[str, dict[str, int]]) -> None:
        for month, row in written.items():
            left = self.pending.get(month)
            if left is None:
                continue
            for c, n in row.items():
                left[c] = max(0, left[c] - n)
            if not any(left.values()):
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
                print(f"  {what}: ledger flush failed; {meter.pending_queries()} "
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
    """This run, plus every STATE slot (STATE_SLOTS, one a day) still to come in
    now's UTC month -- not all four collect.yml slots, since the other three skip
    the channel (handoff 98b, ceiling arithmetic revised).

    Counted from the clock rather than from "which slot is this run". `1 + slots
    strictly after now` is exact for a scheduled 06:17Z run, which lands 2-6 hours
    after its slot and so always before the next day's. A dispatched run is extra
    and uncounted, which the ceiling check still bounds."""
    now = now.astimezone(timezone.utc)
    last_day = calendar.monthrange(now.year, now.month)[1]
    later = sum(
        1
        for day in range(now.day, last_day + 1)
        for hour, minute in STATE_SLOTS
        if datetime(now.year, now.month, day, hour, minute, tzinfo=timezone.utc) > now
    )
    return 1 + later


def run_budget(used: int, cron_ceiling: int, n_masterlists: int, max_getbill: int,
               now: datetime, spent: int = 0) -> Budget:
    """Prorate the rest of the month's cron ceiling over the state slots left in it.

    allowance = floor((cron_ceiling - used) / runs_left), where `used` is the ledger
    as read at the start of the run. `spent` is what this run has already spent
    before its master lists -- the day's getSessionList and, once, the state-id
    bootstrap -- and `n_masterlists` is the number of SESSIONS it will poll, known
    only after that getSessionList. Both are paid first, because without them
    nothing is detected and getBill has nothing to fetch; getBill gets
    `allowance - spent - n_masterlists`, capped by `max_getbill`, floored at 0.

    PRORATION IS THE POINT. A flat per-run cap lets an in-session storm spend the
    month in its first week and blind the channel for the rest of it. Prorated, a
    storm is metered out over the month, and a quiet run's unspent share rolls
    forward into every later run's allowance.

    `used` is the whole month's ledger, tools included, so the cron yields to a
    tool run rather than the two together overrunning the ceiling. The allowance
    is in queries but getBill is budgeted in calls; retries can overshoot a run's
    allowance, and because they are ledgered, the next run's allowance absorbs
    it."""
    left = runs_left(now)
    allowance = max(0, (cron_ceiling - used) // left)
    if used + spent + n_masterlists > cron_ceiling:
        skip = "ceiling"
    elif n_masterlists and allowance - spent - n_masterlists < 1:
        # AMENDMENT TO THE HANDOFF'S RULE (review of this unit, 2026-09-23). A run whose
        # share cannot buy one getBill spends its master lists and STORES NOTHING:
        # hashes, dimension rows and items are all written only after a getBill.
        # Worse, each such run lowers the next run's share, so the channel spends a run
        # after run to learn nothing. Skipping instead lets the share accumulate until
        # a run can afford at least one bill. Fires only in an already-overspent month.
        skip = "share"
    else:
        skip = None
    getbill = 0 if skip else max(0, min(max_getbill, allowance - spent - n_masterlists))
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


def get_masterlist_session(base: str, key: str, session_id: int, throttle: float,
                           meter: UsageMeter | None = None) -> tuple[list[dict], dict]:
    """getMasterList by SESSION ID -- the manual's "Invocation A" (page 9), where
    `state=` is Invocation B, "current" session only, "(use with caution)". Polling
    by id is what covers a special session running beside the regular one (handoff
    98b rulings). Returns the bills and the payload's own `session` block, which
    carries `state_id` for the tripwire in collect()."""
    data = _api(base, key, "getMasterList", {"id": session_id}, throttle, meter)
    master = data.get("masterlist") or {}
    block = master.get("session") if isinstance(master.get("session"), dict) else {}
    return [v for k, v in master.items() if k != "session" and isinstance(v, dict)], block


# --- sessions: the daily national gate (handoff 98b §4 revised, ruled) ------

@dataclass(frozen=True)
class Target:
    """One getMasterList this run will make. `session_id` None is the `state=`
    invocation: the first-run default for a state with no measured sessions, and
    the shape every pre-session caller (tests, tools) still uses."""
    state: str
    session_id: int | None
    why: str
    done_marker: str | None = None   # what masterlist_hash becomes if fully processed

    @property
    def label(self) -> str:
        return self.state if self.session_id is None else f"{self.state}/{self.session_id}"


def measured_state_ids(conn, states: list[str]) -> dict[str, int]:
    """{state: state_id} for the watched states whose id has been MEASURED, i.e.
    stored in state_sessions by the bootstrap. A state holding two different ids is
    left out and said so: two answers is not a measurement, and the URL tripwire in
    collect() would refuse its sessions anyway."""
    out: dict[str, int] = {}
    for st in states:
        ids = {r["state_id"] for r in conn.execute(
            "SELECT DISTINCT state_id FROM state_sessions WHERE state = ?", (st,)).fetchall()}
        if len(ids) == 1:
            out[st] = ids.pop()
        elif len(ids) > 1:
            print(f"  {st:<3} state_sessions holds conflicting state_ids {sorted(ids)}; "
                  f"left unmapped", file=sys.stderr)
    return out


def _flag(session: dict, name: str) -> int:
    try:
        return int(session.get(name) or 0)
    except (TypeError, ValueError):
        return 0


def _session_row(state: str, session: dict) -> dict:
    return {
        "state": state,
        "session_id": int(session["session_id"]),
        "state_id": int(session["state_id"]),
        "sine_die": _flag(session, "sine_die"),
        "prefile": _flag(session, "prefile"),
        "prior": _flag(session, "prior"),
        "special": _flag(session, "special"),
        "session_name": session.get("session_name") or session.get("session_title"),
        "dataset_hash": str(session.get("dataset_hash") or ""),
    }


def store_sessions(conn, rows: "list[tuple[str, dict]]", now_iso: str) -> int:
    """Write getSessionList sessions for watched states into the OPEN transaction,
    and return how many rows changed. The caller commits, or recovers.

    ONE read of what is stored, then an upsert ONLY for a new or changed session.
    The national reply carries every session a watched state ever had (176 rows for
    the nine, on 2026-09-25), and upserting each daily would be ~350 Turso statements
    for the handful that moved. `hash_seen_at` is OUR observation time of the
    current dataset_hash, rewritten only when the hash changes; `updated_at` is the
    last time anything about the row changed. `masterlist_hash` is never touched
    here -- collect() owns it."""
    states = sorted({st for st, _ in rows})
    existing = {}
    if states:
        marks = ", ".join("?" for _ in states)
        for r in conn.execute(
                "SELECT state, session_id, state_id, sine_die, prefile, prior, special, "
                f"session_name, dataset_hash, hash_seen_at FROM state_sessions "
                f"WHERE state IN ({marks})", states).fetchall():
            existing[(r["state"], r["session_id"])] = r
    changed = 0
    for st, session in rows:
        new = _session_row(st, session)
        old = existing.get((st, new["session_id"]))
        if old is not None and all(old[k] == v for k, v in new.items()):
            continue
        seen = (old["hash_seen_at"] if old is not None and old["dataset_hash"] == new["dataset_hash"]
                else now_iso)
        db.upsert(conn, "state_sessions", {**new, "hash_seen_at": seen, "updated_at": now_iso},
                  pk="state, session_id")
        changed += 1
    return changed


def upsert_session(conn, state: str, session: dict, now_iso: str) -> None:
    """One session through store_sessions (tests and single-row callers)."""
    store_sessions(conn, [(state, session)], now_iso)


def _is_outage(exc: BaseException) -> bool:
    """A transport failure or a 5xx that outlasted every retry: LegiScan is not
    answering, not saying no. On a SESSION call this stops the run's LegiScan calls
    (see main) -- a bootstrap day under an outage would otherwise spend 19 full retry
    ladders, ~43 minutes, against a 45-minute job. The change-hash gate resumes the
    next day, so stopping loses nothing."""
    return isinstance(exc, common.RetriesExhausted) and (exc.status is None or exc.status >= 500)


def _abbr_conflicts(rows: "list[tuple[str, dict]]") -> "list[tuple[str, dict]]":
    """The rows whose own `state_abbr` names a DIFFERENT state than the one they are
    about to be filed under.

    THE MANUAL'S EXAMPLE IS OUT OF DATE HERE. Page 8 shows a session with `state_id`
    and no abbreviation, which is why the ids had to be bootstrapped. The LIVE reply
    (2026-09-25) also carries `state_abbr`, `session_hash` and `name`, and state_abbr
    agreed with all nine measured ids, one id per abbreviation across all 52
    jurisdictions. So every getSessionList now checks the measured mapping for free,
    the same refuse-don't-guess rule as the URL tripwire in collect(). A row with no
    state_abbr is not a conflict: the field is undocumented and may go away."""
    return [(st, x) for st, x in rows
            if x.get("state_abbr") and str(x["state_abbr"]).upper() != st.upper()]


def _write_sessions(conn, meter: UsageMeter, rows: "list[tuple[str, dict]]",
                    what: str) -> bool:
    """store_sessions + the meter's pending spend, in ONE guarded commit. Runs only
    after the HTTP it follows, so no write is pending across a request. On any
    failure the rows are discarded (db.recover, never a bare rollback) and the spend
    stays pending for the next commit -- the same rule as collect()'s per-target
    write path, and for the same reason: an unhandled Turso error here would exit
    non-zero and cost the whole cycle its Export and Commit."""
    try:
        store_sessions(conn, rows, common.now_iso())
        written = meter.flush(conn)
        conn.commit()
        meter.settle(written)
        return True
    except Exception as exc:
        db.recover(conn)
        print(f"  state: {what} write discarded after a failure: {exc}", file=sys.stderr)
        return False


def bootstrap_state_ids(conn, base: str, key: str, states: list[str], throttle: float,
                        meter: UsageMeter) -> "tuple[dict[str, int], bool]":
    """MEASURE the state_id of each watched state LegiScan has not yet told us about:
    one getSessionList&state=XX each, once (nine on the first run after deploy, one
    per state added later). The manual documents getSessionList naming states only
    by state_id and publishes no mapping, so the ids come from LegiScan, never from
    a table typed here (Corey, 2026-09-24). The live reply turned out to carry
    state_abbr too; it cross-checks the measurement (_abbr_conflicts), it does not
    replace it.

    Every session a reply returns belongs to XX, so its state_id is XX's. A reply
    naming zero or several ids is refused and nothing is stored for the state.
    ALL the HTTP happens first; the replies are then written in one guarded commit.
    The measured table is printed on this run whatever the write did -- the
    measurement was paid for -- and says whether it was stored. Returns (the ids
    that were STORED, whether an outage stopped it). Unstored ids are not returned,
    so those states take the first-run default and are re-measured next run."""
    measured: dict[str, int] = {}
    replies: list[tuple[str, dict]] = []
    queried = 0
    outage = False
    for st in states:
        queried += 1
        try:
            data = _api(base, key, "getSessionList", {"state": st}, throttle, meter)
        except Exception as exc:
            body = cap_signal_body(exc)
            if body is not None:
                meter.cap_signal = body
                break
            print(f"  {st:<3} state_id bootstrap ERROR: {exc}", file=sys.stderr)
            if _is_outage(exc):
                outage = True
                break
            continue
        sessions = [x for x in (data.get("sessions") or [])
                    if isinstance(x, dict) and x.get("session_id") is not None]
        ids = {x.get("state_id") for x in sessions}
        if _abbr_conflicts([(st, x) for x in sessions]):
            print(f"  {st:<3} state_id bootstrap refused: getSessionList&state={st} returned "
                  f"sessions whose state_abbr names another state; nothing stored",
                  file=sys.stderr)
            continue
        if len(ids) != 1 or None in ids:
            print(f"  {st:<3} state_id bootstrap refused: getSessionList&state={st} named "
                  f"{len(ids)} state_id value(s) across {len(sessions)} session(s); nothing "
                  f"stored", file=sys.stderr)
            continue
        measured[st] = int(ids.pop())
        replies += [(st, x) for x in sessions]
    if not measured:
        return {}, outage
    stored = _write_sessions(conn, meter, replies, "state_id bootstrap")
    print(f"state: state_id bootstrap, MEASURED from {queried} getSessionList&state= "
          f"quer{'y' if queried == 1 else 'ies'} (printed once): "
          f"{json.dumps(dict(sorted(measured.items())))}"
          + ("" if stored else " -- NOT STORED (write failed); re-measured next run"))
    return (measured if stored else {}), outage


def refresh_sessions(conn, base: str, key: str, state_ids: dict[str, int], throttle: float,
                     meter: UsageMeter) -> str:
    """The day's ONE national getSessionList (no `state`: every session, rated Daily
    on page 7), stored for the watched states' sessions in one guarded write.
    Returns "landed", "failed" (plan from what state_sessions already holds), or
    "outage" (stop calling LegiScan this run)."""
    try:
        data = _api(base, key, "getSessionList", {}, throttle, meter)
    except Exception as exc:
        body = cap_signal_body(exc)
        if body is not None:
            meter.cap_signal = body
            return "failed"
        print(f"  state: national getSessionList ERROR: {exc}", file=sys.stderr)
        return "outage" if _is_outage(exc) else "failed"
    by_id = {v: k for k, v in state_ids.items()}
    rows = [(by_id[x.get("state_id")], x) for x in (data.get("sessions") or [])
            if isinstance(x, dict) and x.get("session_id") is not None
            and x.get("state_id") in by_id]
    bad = _abbr_conflicts(rows)
    if bad:
        for st in sorted({st for st, _ in bad}):
            named = sorted({str(x["state_abbr"]).upper() for s2, x in bad if s2 == st})
            print(f"  {st:<3} REFUSED: the measured state_id {state_ids[st]} names {named} in "
                  f"the national getSessionList; its sessions are not stored this run",
                  file=sys.stderr)
        refused = {st for st, _ in bad}
        rows = [(st, x) for st, x in rows if st not in refused]
    return "landed" if _write_sessions(conn, meter, rows, "national getSessionList") else "failed"


def filter_fingerprint(terms, excludes) -> str:
    """A short fingerprint of the election FILTER: its terms, its exclusions, and the
    source of the functions that apply them.

    WHY IT IS PART OF THE DONE-MARKER. An adjourned session is polled only when its
    done-marker is stale, and a marker holding only the dataset_hash would never go
    stale on a FILTER change: a broadened term would then never reach an adjourned
    session already marked done, and CLAUDE.md's standing rule -- a term broadening
    self-stamps on the next cron, no backfill -- would be silently false for most of
    the watched states (the review of this unit, reproduced offline). With the
    filter in the marker, any change to terms, exclusions or election_match re-polls
    each adjourned session ONCE (~14 master lists), and the self-stamp holds.
    Comment-only edits to those functions also move it; that costs the same ~14
    queries once, which is cheaper than a rule a person has to remember."""
    import hashlib
    import inspect
    src = "".join(inspect.getsource(f) for f in (_term_pattern, _exclude_pattern, election_match))
    blob = json.dumps({"terms": sorted(terms), "excludes": sorted(excludes), "code": src})
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def done_marker(dataset_hash: str | None, fingerprint: str) -> str:
    """What masterlist_hash holds for a session fully processed at this dataset_hash
    under this filter."""
    return f"{dataset_hash or ''}|{fingerprint}"


def session_active(sine_die: int, prefile: int, prior: int) -> bool:
    """The ruled test: a session is active when it has not adjourned sine die and is
    not a prior session, or when prefiling is open."""
    return (sine_die == 0 and prior == 0) or prefile == 1


def poll_day(now: datetime) -> bool:
    """True when the PREVIOUS ET calendar day was Mon-Fri: the Tue-Sat slots poll
    active sessions, Sun/Mon skip (a Sun slot follows Sat, a Mon slot follows Sun)."""
    prev = now.astimezone(ET).date() - timedelta(days=1)
    return prev.weekday() < 5


def plan_targets(conn, states: list[str], now: datetime,
                 fingerprint: str = "") -> tuple[list[Target], list[str]]:
    """This run's master lists, and a line for everything deliberately not polled.

    Per watched state, over its NON-PRIOR sessions only:
      active    -> polled when poll_day(now) (Tue-Sat), one master list per session,
                   so a special session beside the regular one is its own target;
      adjourned -> polled only when its done-marker (masterlist_hash) is stale: the
                   dataset_hash has moved since the last master list fully
                   processed for it, or the election filter has (filter_fingerprint);
      no stored sessions at all -> the first-run default: active, by `state=`.
    """
    targets: list[Target] = []
    notes: list[str] = []
    weekday = poll_day(now)
    for st in states:
        rows = conn.execute(
            "SELECT session_id, sine_die, prefile, prior, dataset_hash, masterlist_hash "
            "FROM state_sessions WHERE state = ? ORDER BY session_id", (st,)).fetchall()
        if not rows:
            if weekday:
                targets.append(Target(st, None, "no measured sessions: active by default, state="))
            else:
                notes.append(f"{st}: no measured sessions, active by default; Sun/Mon slot, skip")
            continue
        current = [r for r in rows if r["prior"] == 0]
        if not current:
            notes.append(f"{st}: every stored session is prior; nothing to poll")
            continue
        for r in current:
            sid = r["session_id"]
            marker = done_marker(r["dataset_hash"], fingerprint)
            if session_active(r["sine_die"], r["prefile"], r["prior"]):
                if weekday:
                    targets.append(Target(st, sid, "active", marker))
                else:
                    notes.append(f"{st}/{sid}: active; Sun/Mon slot, skip")
            elif r["masterlist_hash"] != marker:
                stored = r["masterlist_hash"] or ""
                why = ("adjourned, dataset_hash moved"
                       if stored.split("|")[0] != (r["dataset_hash"] or "")
                       else "adjourned, election filter changed")
                targets.append(Target(st, sid, why, marker))
            else:
                notes.append(f"{st}/{sid}: adjourned, dataset_hash unmoved; zero calls")
    return targets, notes


_URL_STATE = re.compile(r"legiscan\.com/([A-Za-z]{2})/", re.IGNORECASE)


def url_states(master: list[dict]) -> set[str]:
    """The state segments named by a master list's bill URLs."""
    out = set()
    for raw in master:
        m = _URL_STATE.search(str(raw.get("url") or ""))
        if m:
            out.add(m.group(1).upper())
    return out


# --- collect ----------------------------------------------------------------

def collect(conn, base: str, key: str, states: list[str], terms: list[str],
            grade: tuple[str, str], budget: int, throttle: float,
            excludes: "tuple[str, ...] | list[str]" = (),
            meter: UsageMeter | None = None,
            targets: "list[Target] | None" = None,
            state_ids: "dict[str, int] | None" = None) -> dict:
    """Poll each target on the change-hash pattern, write action items, return
    per-target counts keyed by Target.label (the bare state for a `state=` target).

    `targets` is the session plan from plan_targets(); without it every entry of
    `states` is one `state=` target, which is what callers that predate sessions
    pass. A SESSION target is fetched by id and must pass the URL tripwire: if any
    of its bills' URLs names another state, or its session block's state_id differs
    from the measured one, the session is refused and nothing is written for it.
    A session target fully processed -- every changed bill fetched -- has its
    `masterlist_hash` set to the dataset_hash it was planned at, in the same
    commit, which is what lets an adjourned session go quiet until its hash moves.

    Per-state try/except so one bad state doesn't sink the run; Per-state try/except so one bad state doesn't sink the run;
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
    if targets is None:
        targets = [Target(s, None, "state") for s in states]
    state_ids = state_ids or {}
    results: dict[str, dict] = {}
    getbill_used = 0
    for t in targets:
        state = t.state
        counts = {"election_bills": 0, "changed": 0, "getbills": 0,
                  "new_items": 0, "errors": 0, "error_msg": None, "skipped": None,
                  "why": t.why}
        try:
            if t.session_id is None:
                master, block = get_masterlist(base, key, state, throttle, meter), {}
            else:
                master, block = get_masterlist_session(base, key, t.session_id, throttle, meter)
        except Exception as exc:
            counts["error_msg"] = str(exc)
            results[t.label] = counts
            body = cap_signal_body(exc)
            if body is not None:
                meter.cap_signal = body
                break
            continue

        if t.session_id is not None:
            # THE TRIPWIRE (Corey, 2026-09-24). The state_id -> state mapping is
            # measured, but a wrong one would file a session's bills under the wrong
            # state. A master list names its own state twice -- in its session block and
            # in every bill URL -- so check both before writing anything. Free: it reads
            # the response already paid for.
            foreign = url_states(master) - {state.upper()}
            want_id = state_ids.get(state)
            got_id = block.get("state_id")
            if foreign or (want_id is not None and got_id is not None and int(got_id) != want_id):
                meter.masterlist(unchanged=False)
                named = sorted(foreign) if foreign else f"state_id {got_id}"
                counts["error_msg"] = (
                    f"refused: session {t.session_id} was mapped to {state} (state_id "
                    f"{want_id}) but its master list names {named}; nothing written")
                results[t.label] = counts
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
        capped_here = False
        recorded = False
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
                        capped_here = True
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
            # The cache-hit proxy: an answered master list that moved no stored hash.
            meter.masterlist(unchanged=counts["changed"] == 0)
            recorded = True
            # A session is DONE only when every changed bill was fetched: no budget
            # deferral, no bill error, no cap signal mid-list. Anything less leaves
            # masterlist_hash alone, so an adjourned session is polled again next day
            # rather than going quiet with bills unfetched.
            if (t.session_id is not None and t.done_marker is not None and not capped_here
                    and counts["errors"] == 0 and counts["getbills"] == counts["changed"]):
                conn.execute(
                    "UPDATE state_sessions SET masterlist_hash = ?, updated_at = ? "
                    "WHERE state = ? AND session_id = ?",
                    (t.done_marker, common.now_iso(), state, t.session_id))
            # The ledger rides in the state's own commit: same boundary as the data.
            written = meter.flush(conn)
            conn.commit()
            meter.settle(written)
        except Exception as exc:
            db.recover(conn)
            if not recorded:
                meter.masterlist(unchanged=False)
            # new_items is zeroed rather than reported: those rows were rolled back,
            # and a count claiming rows that no longer exist is the kind of plausible
            # wrong number this project keeps finding. The attempt counters stay --
            # they describe work done, and the API calls were really spent. So does
            # the meter's pending count, which was never settled: it goes out with
            # the next commit that succeeds.
            counts["new_items"] = 0
            counts["error_msg"] = f"batch discarded after a write failure: {exc}"

        results[t.label] = counts
        if meter.cap_signal is not None:
            break

    for t in targets:
        if t.label not in results:
            results[t.label] = {"election_bills": 0, "changed": 0, "getbills": 0,
                                "new_items": 0, "errors": 0, "error_msg": None,
                                "why": t.why,
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
    # THE SLOT GATE (handoff 98b §4a). collect.yml passes the firing cron line as SLOT;
    # this channel runs on STATE_SLOT only. A dispatch ("dispatch") or a local run (no
    # SLOT) is a deliberate request and runs -- the budget still applies to it.
    slot = os.environ.get("SLOT", "").strip()
    if slot and slot != "dispatch" and slot != STATE_SLOT:
        print(f"state: not this slot ({slot}); the state collector runs on {STATE_SLOT} only")
        return 0
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
    meter = UsageMeter()
    try:
        register_source(conn, base, grade[0], grade[1])
        conn.commit()
        if slot != STATE_SLOT:
            print(f"state: no schedule slot ({slot or 'local run'}); running as requested")

        now = _now()
        used = ledger_used(conn, ledger_month(now))
        state_ids = measured_state_ids(conn, states)
        missing = [s for s in states if s not in state_ids]
        # End the read before any HTTP. _Conn marks itself _pending on EVERY statement,
        # reads included, and a pending connection refuses the one-shot stale-stream
        # reopen -- so without this, a Hrana stream that expires during the first HTTP
        # call fails the first write instead of reopening.
        conn.commit()

        # The session calls are paid before anything else; if the ceiling cannot pay
        # even for them, the run makes no request at all.
        pre = run_budget(used, cron_ceiling, 0, max_getbill, now, spent=1 + len(missing))
        if pre.skip == "ceiling":
            print(f"state: monthly ceiling reached (used {used} of {cron_ceiling}), skipping")
            return 0

        outage = False
        if missing:
            stored_ids, outage = bootstrap_state_ids(conn, base, key, missing, THROTTLE, meter)
            state_ids.update(stored_ids)
        national = "not attempted"
        if meter.cap_signal is None and not outage:
            national = refresh_sessions(conn, base, key, state_ids, THROTTLE, meter)
            outage = national == "outage"
        if meter.cap_signal is not None or outage:
            targets, notes = [], []
        else:
            targets, notes = plan_targets(conn, states, now,
                                          filter_fingerprint(terms, excludes))
        # plan_targets READS state_sessions after the last commit; end that read too,
        # or collect() starts on a pending connection and loses the stale-stream
        # reopen (the review finding test_main_ends_the_ledger_read_* pins).
        conn.commit()
        for note in notes:
            print(f"  {note}")

        plan = run_budget(used, cron_ceiling, len(targets), max_getbill, now,
                          spent=meter.run_total)
        prev_et = (now.astimezone(ET).date() - timedelta(days=1)).strftime("%a")
        print(f"  ledger {plan.month}: {plan.used} of {cron_ceiling} cron ceiling used "
              f"({monthly_cap} monthly cap); {plan.runs_left} state slot(s) left incl. this "
              f"one -> allowance {plan.allowance}; {meter.run_total} spent on sessions "
              f"(national getSessionList {national}); "
              f"{len(targets)} master list(s) planned (previous ET day {prev_et}); "
              f"getBill budget {plan.getbill}")

        results: dict[str, dict] = {}
        if outage:
            print("state: LegiScan is not answering the session calls (transport or 5xx "
                  "after every retry); no master lists this run -- the change-hash gate "
                  "resumes on the next state slot")
        elif meter.cap_signal is None:
            if plan.skip == "ceiling":
                print(f"state: monthly ceiling reached (used {plan.used} of {cron_ceiling} "
                      f"before master lists), skipping")
                return 0
            if plan.skip == "share":
                # Exit 0 on purpose: nothing is lost -- no hash is stored for a bill
                # this run did not fetch, so a later run that can pay picks it up.
                print(f"state: this run's prorated share ({plan.allowance}) cannot pay for "
                      f"{len(targets)} master list(s) plus one getBill after "
                      f"{meter.run_total} spent on sessions (used {plan.used} of "
                      f"{cron_ceiling}, {plan.runs_left} state slot(s) left), skipping")
                return 0
            if not targets:
                print("state: no session to poll this slot")
            else:
                results = collect(conn, base, key, states, terms, grade, plan.getbill,
                                  THROTTLE, excludes, meter=meter, targets=targets,
                                  state_ids=state_ids)
                # collect() commits per target, so this is a no-op tail that still
                # closes any transaction a future edit opens after the last one.
                conn.commit()

        total = 0
        for label, c in results.items():
            if c["skipped"]:
                print(f"  {label:<10} skipped: {c['skipped']}")
                continue
            if c["error_msg"]:
                print(f"  {label:<10} ERROR: {c['error_msg']}", file=sys.stderr)
                continue
            total += c["new_items"]
            extra = f", {c['errors']} bill error(s)" if c["errors"] else ""
            print(f"  {label:<10} {c['election_bills']:>3} election bills, "
                  f"{c['changed']:>3} changed, {c['getbills']:>3} getBill  "
                  f"+{c['new_items']} items{extra}  [{c.get('why', '')}]")
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
        # Every attempt reaches the ledger, on every path out of this function,
        # including the early returns above and a raise.
        if meter.pending:
            record_spend_or_warn(conn, meter, "state")
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
