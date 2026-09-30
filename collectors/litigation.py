"""Litigation collector — CourtListener (Free Law Project) v4 API.

Two grades, two sources, per case:
  * A1 = docket entries, summarized from the entry text alone (the PACER text names
    the motion type and moving party). One A1 `items` row per NEW substantive entry.
  * B2 = the case subject/significance (what it is about, the category, the
    funding-threat angle) -- this lives in seed metadata / trackers, never in the
    docket text. One B2 `items` row per case.

`case_entries` keeps EVERY docket entry (full record); only substantive types reach
`items` (config: substantive_entry_types minus excluded_entry_phrases).

Resolution is exact (docket_number + court id) and strict (exactly one match, else
no binding) -- a wrong docket would produce authoritative A1 entries about the wrong
case. Resolved docket IDs persist in `cases`, so a known case is never re-resolved.

Run from the repo root:  python -m collectors.litigation
(Tracker-scrape discovery of the full DOJ-suit list is a separate, gated entrypoint,
 not part of this module yet.)
"""

from __future__ import annotations

import json
import math
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

import common
import config
import db
import run_signals
from collectors import cl_fold, cl_objects

CHANNEL = "litigation"
API_SOURCE_ID = "courtlistener"   # A1 docket records
SEED_SOURCE_ID = "seed-cases"     # B2 hand/tracker case metadata
CL_BASE_WEB = "https://www.courtlistener.com"
USER_AGENT = "psephos/0.1 (+https://github.com/CSU-J3/psephos)"
TRACKER_ARTIFACT = "data/doj_cases.json"   # the full DOJ-suit list (collectors.tracker_uw)

# Seconds between CourtListener requests, paced against the 20/min throttle measured
# 2026-08-09 on the EDU membership (Developer Tools -> API Usage; 1,000/hour is the
# other stat, and no daily is shown at this tier).
#
# The arithmetic: DRF's window is a rolling 60s, so it refuses request 21 if request 1
# was under 60s ago. The safe condition is 20 * cycle >= 60, i.e. cycle >= 3.0s. 3.0
# therefore sits EXACTLY on the boundary at zero latency, and only network round-trip
# time keeps it off. Handoff 25 measured this directly on the 2026-08-10 runs: the
# minimum observed spacing was 3.39s and the median 3.54-3.74s across 57 one-request
# dockets, so every bit of the margin was CourtListener's round trip rather than
# anything this code controls. 3.2 buys the margin from the constant instead: twenty
# requests SPAN 64s against a 60s window, so the clearance is FOUR SECONDS, not 64.
# Read the other way it looks like room to tighten the constant, and there is none.
# Costs ~7s on a ~35-request run.
#
# This does not exist to stop the abort (20/min clears MAX_RETRY_AFTER on its own);
# it exists so the throttle is never tripped. If the tier changes, this number changes
# with it: re-read the API Usage panel, and a 429 in the log will name the new scope
# in its body via common._log_429.
PAGE_THROTTLE = 3.2
EMPTY_RETRIES = 5     # retries for an unexpectedly empty page before giving up

# The one heavy field write_entries never reads: recap_documents' full `plain_text`.
# Dropped via `omit=` on every poll -- the difference between a walk that takes minutes
# and one that takes an hour on a 2s-throttled connection. `omit` (not an enumerated
# `fields=`) fails safe: if the server ignores it we get MORE data than asked and
# correctness holds, whereas a `fields=` list that missed recap_documents__short_description
# would silently stop write_entries finding descriptions on document-only entries and lose
# A1 items with no error. Target the bloat, don't enumerate the keeps. Does NOT reduce the
# request count. (`omit=recap_documents__plain_text` is CourtListener's own changelog
# example for nested omission.)
ENTRY_OMIT = "recap_documents__plain_text"

GATES_PATH = Path("docs/gates.yaml")


class Spend:
    """CourtListener requests this run, so the id backfill can be reported against the
    rest of the day's litigation spend (Corey, 2026-09-30, ruling 6).

    Counts ATTEMPTS: `hit` is passed to common.http_get as `on_attempt`, which fires
    before every HTTP attempt, retries on a 429, a 5xx or a transport failure included.
    Those are the requests CourtListener sees, and an outage is exactly when calls and
    attempts part company (a failed page is one call and four attempts)."""

    def __init__(self):
        self.total = 0
        self.backfill = 0
        self.walking = False

    def hit(self) -> None:
        self.total += 1
        if self.walking:
            self.backfill += 1


SPEND = Spend()


def slugify(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def split_caption(caption: str) -> tuple[str | None, str | None]:
    """'A v. B' -> ('A', 'B'); best-effort, None if no ' v. '."""
    m = re.split(r"\s+v\.?\s+", caption, maxsplit=1)
    return (m[0].strip(), m[1].strip()) if len(m) == 2 else (None, None)


_STATE_SUFFIX = re.compile(r"\s*\(\d+\)\s*$")


def normalize_state(value: str | None) -> str | None:
    """The tracker's state label with its disambiguation suffix stripped.

    `data/doj_cases.json` carries one row per DOCKET, so a state with two dockets
    disambiguates inside the state field itself: `Georgia (1)` is the M.D. Ga. suit
    and `Georgia (2)` the N.D. Ga. refile that replaced it. That suffix is the
    tracker's bookkeeping, not part of the state's name, and a per-state view that
    joins on the raw value renders two Georgia cells for one jurisdiction. Strip it
    once, here, at the boundary where the artifact enters the database, so no
    consumer has to know the artifact's row convention.

    Returns None when the seed carries no `state` at all. That is not a gap: the two
    `config/sources.yaml` seeds (Common Cause v. DOJ, LWV v. DHS) are suits against
    federal agencies, so they have no state by construction and the NULL is what
    keeps them out of any per-state grouping. See schema.sql cases.state."""
    if not value:
        return None
    return _STATE_SUFFIX.sub("", value).strip() or None


def is_substantive(description: str, types: list[str], excludes: list[str]) -> bool:
    """True if the entry should be promoted to an A1 items row."""
    d = (description or "").lower()
    if any(x in d for x in excludes):
        return False
    return any(t in d for t in types)


# --------------------------------------------------------------------------- #
# CourtListener API
# --------------------------------------------------------------------------- #
def resolve_docket(base: str, headers: dict, docket_number: str, court_id: str) -> dict | None:
    """Exact lookup by docket_number + court. Returns the docket, or None unless
    exactly one matches (strict: 0 or >1 -> do not bind)."""
    data = common.http_get(
        f"{base}/dockets/",
        params={"docket_number": docket_number, "court": court_id},
        headers=headers, throttle=PAGE_THROTTLE, on_attempt=SPEND.hit,
    )
    results = data.get("results") or []
    if len(results) != 1:
        print(f"  {docket_number}/{court_id}: expected 1 docket, got {len(results)} "
              f"-- NOT binding", file=sys.stderr)
        return None
    return results[0]


def fetch_docket(base: str, headers: dict, cl_id: str) -> dict:
    """One docket by CourtListener id, for a seed that PINS one.

    WHY A PIN EXISTS AT ALL. `resolve_docket` binds only on exactly one match and
    that strictness is the property, not the obstacle -- relaxing it would trade a
    loud refusal on one row for a silent arbitrary bind on every future collision.
    But CourtListener can hold two records for one docket, and when it does, the
    search can never return one. `6:25-cv-01666`/ord is the first such case here:
    `71363789` carries `date_terminated 2026-02-05` and the real entries, while
    `71956700` carries neither and would have bound as a permanently empty row.

    A PIN IS A SEED-LEVEL OVERRIDE WITH ITS EVIDENCE IN THE SEED, never a global
    rule. The refusal stays exactly as strict for every unpinned seed.

    Fetched rather than short-circuited to the reuse path, and the difference is
    load-bearing: reuse leaves `docket` None, `upsert_case` writes status/filed_at/
    source_url only when a docket is present, and a row with a NULL status renders
    as ACTIVE on /campaign -- which is precisely wrong for a terminated predecessor.
    One request buys the same fidelity a normal resolve has."""
    return common.http_get(f"{base}/dockets/{cl_id}/", headers=headers, throttle=PAGE_THROTTLE,
                           on_attempt=SPEND.hit)


def _fetch_page(url: str, params: dict | None, headers: dict,
                retry_empty: bool = True) -> dict:
    """Fetch one page, retrying defensively on an empty result set.

    A rate limit can return an empty 200; a real docket has no empty middle pages.
    So: retry empties with backoff; if still empty AND a `next` cursor exists, that's
    a rate-limit failure -> raise (the caller skips the case, leaving nothing
    half-written). Empty with no `next` is accepted as a genuinely empty page.

    `retry_empty=False` is for the FIRST page of an incremental window (date_modified
    high-water mark): there, an empty first page is the normal steady state -- nothing
    changed on this docket since the last run -- so retrying it 5x would cost 5 requests
    and ~45s per quiet docket, worse than the full walk this fix replaces. Pages reached
    by following a `next` cursor keep the retry (an empty middle page mid-pagination is
    still anomalous), and full bootstrap walks keep it too.
    """
    if not retry_empty:
        return common.http_get(url, params=params, headers=headers, throttle=PAGE_THROTTLE,
                               on_attempt=SPEND.hit)
    data = {}
    for attempt in range(EMPTY_RETRIES):
        data = common.http_get(url, params=params, headers=headers, throttle=PAGE_THROTTLE,
                               on_attempt=SPEND.hit)
        if data.get("results"):
            return data
        time.sleep(PAGE_THROTTLE * (attempt + 1) + 1)
    if data.get("next"):
        raise RuntimeError(f"persistent empty pages from {url} (rate-limited?)")
    return data


def poll_entries(base: str, headers: dict, docket_id: str,
                 since: str | None = None, page_counter: list[int] | None = None
                 ) -> tuple[list[dict], str | None]:
    """Poll a docket for entries; return (entries, new_high_water_mark) or raise.

    `since` is the case's stored `entries_synced_at` (max CourtListener date_modified
    ingested so far), or None to bootstrap:

      * since is None  -> full walk, ordered by entry_number. Every page retries an
        empty result (a real docket has no empty middle pages). This seeds the mark.
        A full walk is now the EXCEPTION -- only for a docket whose history we don't
        already hold (see collect_case: probe_mark handles the common case). When set,
        `page_counter[0]` accumulates the pages fetched (~= requests, retries aside),
        so the caller can draw the full-walk cost down from a per-run request budget.
      * since is set   -> incremental window: date_modified__gt=<since>, ordered
        date_modified,id (the id tie-breaks a non-unique date_modified; both are on
        CourtListener's short list of cursor-deep-pagination orderings). The FIRST
        page passes retry_empty=False -- an empty incremental window is the normal
        steady state and must cost one request, not five. Pages past a `next` cursor
        keep the retry.

    Why date_modified and not date_filed/entry_number: RECAP backfills old filings
    late (an entry filed in Oct can land in the DB in Jul), so a date_filed/entry_number
    mark would step past a late arrival permanently; entry_number also goes null on
    minute entries, which a `__gt` filter drops. date_modified is "new to me since I
    last looked" and also catches edits to entries we already hold.

    A *modified* description still inserts a second `case_entries` row and a second A1
    item, because both are keyed on the text (R1 keeps every text it has seen). Since
    2026-09-30 each row carries the CourtListener entry id it was served on, so the object
    table (`cl_entries`, collectors/cl_objects.py) knows the two are one entry. The D0 is
    docs/status.md, "Duplicate rows at the source".

    On a rate-limit failure mid-pagination it raises, so the caller writes nothing for
    the case (no half-seeded table) and the mark does not move. Returns the max
    date_modified across the returned entries as the new mark, or None on an empty
    window (mark unchanged)."""
    out: list[dict] = []
    url = f"{base}/docket-entries/"
    if since is None:
        params: dict | None = {"docket": docket_id, "order_by": "entry_number",
                               "omit": ENTRY_OMIT}
    else:
        params = {"docket": docket_id, "date_modified__gt": since,
                  "order_by": "date_modified,id", "omit": ENTRY_OMIT}
    first = True
    latest_mod: str | None = None
    while url:
        # Skip the empty-retry ONLY on the first page of an incremental window.
        data = _fetch_page(url, params, headers, retry_empty=(since is None or not first))
        if page_counter is not None:
            page_counter[0] += 1
        results = data.get("results") or []
        if since is None and not first and not results:
            # Past a `next` cursor there is always more; an empty page there, after
            # _fetch_page's retries, is a throttle, not the docket's end. Returning what
            # came before would hand a full walk -- and the id backfill's one-time
            # receipt -- a docket with its tail missing.
            raise RuntimeError(f"empty page past a cursor on docket {docket_id} "
                               f"(rate-limited?)")
        first = False
        params = None  # the `next` URL carries its own query string
        out.extend(results)
        for e in results:
            dm = e.get("date_modified")
            if dm and (latest_mod is None or dm > latest_mod):
                latest_mod = dm
        url = data.get("next")
    return out, latest_mod


def probe_mark(base: str, headers: dict, docket_id: str) -> tuple[list[dict], str | None]:
    """Seed the high-water mark from ONE descending page -- for a docket whose full
    history we ALREADY hold in case_entries (walked 4x/day for weeks), so only the
    starting timestamp is missing. GET ...?order_by=-date_modified,-id, page 1 only:
    exactly one request, no pagination follow. This replaces the full bootstrap walk,
    which at ~11 pages/docket blew the 250/day cap during the multi-day drain to reach
    a state a single request reaches in one run.

    Returns (page entries, MIN date_modified on the page). The minimum is load-bearing:
    the first incremental window (date_modified__gt=<min>) then re-covers this ENTIRE
    page, so the only entries that could slip are ones modified longer ago than the
    ~20th-most-recent modification on the docket -- and prior full walks captured those.
    The maximum would open a gap between the last walk and the newest modification.

    retry_empty=False: the caller only probes dockets known to hold entries, so an empty
    page is a transient blip -- return (_, None), don't retry; the mark stays NULL and
    the docket re-probes next run at one request. Entries are written through the normal
    idempotent write_entries by the caller, so re-covering the page costs nothing."""
    data = _fetch_page(
        f"{base}/docket-entries/",
        {"docket": docket_id, "order_by": "-date_modified,-id", "omit": ENTRY_OMIT},
        headers, retry_empty=False,
    )
    entries = data.get("results") or []
    mods = [e.get("date_modified") for e in entries if e.get("date_modified")]
    return entries, (min(mods) if mods else None)


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
def register_sources(conn) -> None:
    db.upsert(conn, "sources", {
        "id": API_SOURCE_ID, "name": "CourtListener (Free Law Project)", "channel": CHANNEL,
        "kind": "api", "url": "https://www.courtlistener.com/api/rest/v4",
        "admiralty_source": "A", "admiralty_info": "1", "enabled": 1,
        "notes": "Primary court record; docket entries.",
    }, pk="id")
    db.upsert(conn, "sources", {
        "id": SEED_SOURCE_ID, "name": "Seed/tracker case metadata", "channel": CHANNEL,
        "kind": "tracker", "url": None, "admiralty_source": "B", "admiralty_info": "2",
        "enabled": 1, "notes": "Case subject/category/significance; docket text never supplies it.",
    }, pk="id")


def _existing_caption(conn, case_id: str) -> str | None:
    r = conn.execute("SELECT caption FROM cases WHERE case_id = ?", (case_id,)).fetchone()
    return r["caption"] if r else None


def case_status(docket: dict) -> str:
    """The `cases.status` value for a docket JSON: CourtListener's `date_terminated`
    is the whole mapping.

    Named so `tools/status_audit` can evaluate the SAME expression the collector
    stores rather than a copy of it -- the audit measures whether stored values have
    gone stale, and a paraphrase here would let the two drift and turn a stale-row
    measurement into a mapping mismatch. Same reason tools/sasts_dump imports
    `get_bill` from collectors.state instead of reimplementing it."""
    return "pending" if not docket.get("date_terminated") else "terminated"


def upsert_case(conn, case_id: str, seed: dict, docket: dict | None) -> str | None:
    """Upsert the case row. API-derived fields are written only when we have the
    docket JSON (a fresh resolve), so a reuse run never clobbers them with None.
    Returns the API date_filed when available.

    The caption is authoritative only from the fresh docket's CourtListener
    `case_name` (e.g. "United States v. Wisconsin Elections Commission"), which
    replaces the provisional seed caption ("United States v. Wisconsin"). On a
    reuse run (docket is None) we keep the stored caption rather than reverting it
    to the seed; the seed caption is used only when nothing better exists yet."""
    if docket is not None:
        caption = docket.get("case_name") or seed["caption"]
    else:
        caption = _existing_caption(conn, case_id) or seed["caption"]
    plaintiff, defendant = split_caption(caption)
    # `superseded_by` is deliberately absent from this dict. It is asserted out of band
    # (scripts/backfill_supersession.py) and db.upsert only writes the columns listed
    # here, so a seeded terminated source (e.g. the M.D. Ga. refile) keeps its link
    # across every reuse run. Do not add it here without moving the assertion too.
    row = {
        "case_id": case_id,
        "caption": caption,
        # COURT AND DOCKET_NUMBER COME STRAIGHT OFF THE SEED, NEVER OFF THE DOCKET,
        # and three separate things depend on that being true. It reads like a
        # detail and it is load-bearing, so changing it means changing them:
        #   1. The reuse lookup in collect_case, `WHERE docket_number = ? AND
        #      court = ?` against the seed's own values. Write CourtListener's
        #      spelling here instead and every seed re-resolves every run -- one
        #      wasted request per seed forever, silently, and for a PINNED seed it
        #      also means the pin fires every run rather than once.
        #   2. tools/coverage_audit section 1, whose seed join is `(docket_number,
        #      court)` and is exact by construction for this reason. A mismatch
        #      turns healthy rows into reconciliation-alarm firings.
        #   3. The charter's claim that a tracker rewrite overwrites a config seed
        #      byte-identically -- true only because both write the same two fields
        #      from their own seed dict. If this took the docket's spelling, the
        #      artifact row and the config row would differ and `cases.case_id`
        #      would stop collapsing them into one row.
        # No test asserts the property directly; it is enforced by the three
        # consumers failing in three different ways, which is why it is written down.
        "court": seed.get("court"),
        "docket_number": seed.get("docket_number"),
        "category": seed.get("category"),
        # Seed-derived like court/docket/category, so it belongs in the base dict and
        # not behind the `docket is not None` gate -- the artifact is the only source
        # of it and CourtListener never supplies one. A seed that carries no state
        # writes NULL, which is correct for the two federal-defendant config seeds.
        "state": normalize_state(seed.get("state")),
        "plaintiff": plaintiff,
        "defendant": defendant,
        "seeded_from": SEED_SOURCE_ID,
        "updated_at": common.now_iso(),
    }
    filed_at = None
    if docket is not None:
        filed_at = common.to_iso(docket.get("date_filed"))
        row["filed_at"] = filed_at
        row["status"] = case_status(docket)
        # The date `status` is derived FROM, kept beside the bit derived from it. Same
        # branch, same read, no extra request -- `case_status(docket)` on the line above
        # is already looking at this value and discarding everything but its truthiness.
        # NULL on a pending docket, which is what CourtListener sends and what makes
        # `status` read 'pending'; the two can never disagree because they are one read.
        row["date_terminated"] = common.to_iso(docket.get("date_terminated"))
        row["source_url"] = CL_BASE_WEB + docket["absolute_url"] if docket.get("absolute_url") else None
        # Stamped HERE, in the docket branch only, because this branch is the one that
        # actually read status off CourtListener -- `case_status(docket)` on the line
        # above is that read. The reuse path (docket is None) re-reads nothing, so it
        # must not stamp, or the receipt would claim a check that never happened.
        #
        # This closes the handoff-27 deferral, which was carried on the argument that
        # the cost was bounded and unmeasured. It is measured now: the 2026-08-15
        # 00:00Z run seeded CT and NY, and the refresh pass that followed read 26 due
        # against the 24 it would otherwise have had -- one redundant request per newly
        # resolved case, against the docket the resolve had just read, in the same run.
        # Small, but it is pure waste on a contended budget and the fix is one line.
        row["status_checked_at"] = common.now_iso()
    db.upsert(conn, "cases", row, pk="case_id")
    return filed_at


def write_b2_item(conn, case_id: str, seed: dict, filed_at: str | None, source_url: str | None) -> bool:
    """One B2 items row carrying the case subject/significance (from seed/tracker)."""
    notes = seed.get("notes") or ""
    return db.insert_ignore(conn, "items", {
        "channel": CHANNEL, "source_id": SEED_SOURCE_ID,
        "source_url": source_url or CL_BASE_WEB, "title": f"{seed['caption']} — {seed.get('category')}",
        "summary": notes, "occurred_at": filed_at, "fetched_at": common.now_iso(),
        "admiralty_source": "B", "admiralty_info": "2", "confidence": None,
        "bill_id": None, "case_id": case_id,
        "content_hash": common.content_hash(case_id, "b2-subject", notes),
        "raw_json": json.dumps({k: seed.get(k) for k in ("caption", "category", "notes")},
                               separators=(",", ":")),
    })


def write_entries(conn, case_id: str, caption: str, source_url: str | None,
                  entries: list[dict], types: list[str], excludes: list[str]) -> dict:
    """Write ALL entries to case_entries; promote substantive ones to A1 items.
    Single transaction at the call site -- caller commits on success only.

    `cases.latest_entry_at` is DERIVED, not assigned: it equals
    MAX(record_entries.entry_at) for the case -- the latest ENTRY at its date now, since the
    R1 switch -- and it is recomputed at the bottom of this function. This is the ONLY code
    path that inserts into `case_entries`, and `collect_case` is its only caller, so all
    three poll modes reach the recompute by construction. The other paths that change what
    record_entries holds recompute too, through cl_fold.recompute_latest: the id backfill
    walk and link_entry_twins' link and unlink. A new such path needs its own.

    Why derived rather than assigned from this batch (the defect this replaces).
    The line here used to be `UPDATE cases SET latest_entry_at = <max date_filed in
    this batch>`, which was correct when written in a9ba643 because every poll was a
    full walk and the batch WAS the docket. c8b8b6f made polling incremental on
    2026-07-22 and the batch became a window, at which point the assignment could
    move the column BACKWARDS: an incremental window ordered by date_modified can
    legitimately contain only an old filing, because RECAP backfills late -- which
    poll_entries' own docstring says twenty lines above the line it broke. Measured
    2026-08-14, 12 of 40 rows had drifted, always behind, up to 83 days; West
    Virginia read 2026-05-15 while holding an entry from 2026-08-06. Repaired once by
    scripts/repair_latest_entry.py and alarmed by tools/coverage_audit section 4."""
    counts = {"new_entries": 0, "new_items": 0, "adopted": 0, "cosmetic": 0,
              "revised": 0, "apart": 0}
    now = common.now_iso()
    # (day, document number) pairs more than one entry in this batch serves: no stamp or
    # spacing adoption on them (cl_objects.resolve_polled).
    served: dict = {}
    for e in entries:
        d = cl_objects.derive(e)
        if d is not None and e.get("id") is not None:
            key = (d[0], cl_objects.doc_token(d[2]))
            if key[1] is not None:
                # Distinct ids: a window can serve one entry twice across a page boundary.
                served.setdefault(key, set()).add(e["id"])
    shared = frozenset(k for k, ids in served.items() if len(ids) > 1)
    for e in entries:
        # Document-only entries have an empty entry-level description; the PACER text
        # then lives on the document (e.g. "Order on Motion for Briefing Schedule").
        # cl_objects.derive falls back to it so the record is complete and such orders
        # still classify.
        d = cl_objects.derive(e)
        if d is None:
            continue
        entry_at, desc, doc_url = d
        cl_id = e.get("id")
        if cl_id is None:
            # No CourtListener id: the pre-R1 path, kept for any caller that has none.
            if db.insert_ignore(conn, "case_entries", {
                "case_id": case_id, "entry_at": entry_at, "description": desc,
                "document_url": doc_url, "seen_at": now,
            }):
                counts["new_entries"] += 1
            text_at, text = entry_at, desc
        else:
            # R1 (Corey, 2026-09-30): the row carries the entry id it was served on, and
            # a stamp or spacing re-render lands on the row already held rather than
            # making a new one. cl_objects.resolve_polled holds the rules.
            row_id, how = cl_objects.resolve_polled(conn, case_id, cl_id, entry_at, desc,
                                                    doc_url, now, shared)
            if how == "inserted":
                counts["new_entries"] += 1
            elif how.startswith("adopted"):
                counts["adopted"] += 1
            elif how == "cosmetic":
                counts["cosmetic"] += 1
            elif how == "apart":
                counts["apart"] += 1
            if cl_objects.record_object(conn, case_id, e, entry_at, desc, row_id, how, now):
                counts["revised"] += 1
            if row_id is None:
                continue   # held apart: another object's row carries this text today
            # The item follows the ROW's text, which a cosmetic or adopted match keeps.
            r = conn.execute("SELECT entry_at, description FROM case_entries WHERE id = ?",
                             (row_id,)).fetchone()
            text_at, text = r["entry_at"], r["description"]
        if is_substantive(text, types, excludes):
            if db.insert_ignore(conn, "items", {
                "channel": CHANNEL, "source_id": API_SOURCE_ID,
                "source_url": doc_url or source_url or CL_BASE_WEB,
                "title": f"{caption}: {text[:180]}", "summary": text,
                "occurred_at": text_at, "fetched_at": now,
                "admiralty_source": "A", "admiralty_info": "1", "confidence": None,
                "bill_id": None, "case_id": case_id,
                "content_hash": common.content_hash(case_id, text_at, text),
                "raw_json": json.dumps({k: e.get(k) for k in ("id", "entry_number", "date_filed", "description")},
                                       separators=(",", ":")),
                "cl_entry_id": cl_id,
            }):
                counts["new_items"] += 1
    # Recompute from the ENTRIES (record_entries, the switch), gated on something that
    # can move them: a new row, an entry adopting a row, a revision (a re-date moves its
    # entry's date), or an entry held apart. Zero of those means the MAX cannot have
    # moved, so the write stays necessary-and-sufficient rather than a no-op UPDATE on
    # every docket every run. It also self-heals -- a row that drifted corrects itself on
    # its next such poll, which is why the repair script is one-time, not scheduled.
    if any(counts[k] for k in ("new_entries", "adopted", "revised", "apart")):
        cl_fold.recompute_latest(conn, case_id)
    return counts


# --------------------------------------------------------------------------- #
# Per-case orchestration
# --------------------------------------------------------------------------- #
def collect_case(conn, base: str, headers: dict, seed: dict,
                 types: list[str], excludes: list[str],
                 bootstrap_requests: int = 0) -> dict:
    caption = seed["caption"]
    dn, court_id = seed.get("docket_number"), seed.get("court_id")

    # B2-only seed (no docket_number/court_id): record subject, no polling.
    if not (dn and court_id):
        case_id = slugify(caption)
        filed_at = upsert_case(conn, case_id, seed, None)
        noted = write_b2_item(conn, case_id, seed, filed_at, None)
        conn.commit()
        if noted:
            cl_fold.refold_quietly(conn, case_id)
        return {"caption": caption, "resolved": False, "new_entries": 0, "new_items": 0}

    # Reuse a persisted resolution; only hit the API for unknown cases.
    existing = conn.execute(
        "SELECT case_id, source_url FROM cases WHERE docket_number = ? AND court = ?",
        (dn, seed.get("court")),
    ).fetchone()
    # END THE READ BEFORE ANY HTTP (2026-09-27, the state.py precedent). db._Conn marks
    # itself pending on EVERY statement, reads included, and a pending connection
    # refuses the one-shot stale-stream reopen -- so a Hrana stream that expired during
    # the resolve would fail the first write below instead of reopening. A commit with
    # only reads pending is a no-op on both backends; the quiet-docket path already
    # makes one every run.
    conn.commit()
    docket = None
    if existing and str(existing["case_id"]).isdigit():
        case_id = str(existing["case_id"])
        source_url = existing["source_url"]
    else:
        # Resolution hits the API, so it can hit the rate limit too. http_get raises
        # RuntimeError only after exhausting its retries (a rate-limit/network give-up);
        # catch that ONE failure per case -- log, skip, let the loop continue -- exactly
        # as the poll guard below does. Nothing is written before this point, so a skip
        # leaves nothing half-seeded and the case re-resolves next run. A genuine bug is
        # NOT swallowed: an unresolved lookup returns None (handled next), and a malformed
        # seed raises KeyError, which is not a RuntimeError and still surfaces.
        # A seed may PIN a CourtListener id when the docket-number search cannot
        # return exactly one -- see fetch_docket. Only the pinned seed skips the
        # search; every other seed resolves exactly as strictly as before.
        pinned = str(seed.get("case_id") or "").strip()
        try:
            docket = (fetch_docket(base, headers, pinned) if pinned
                      else resolve_docket(base, headers, dn, court_id))
        except RuntimeError as exc:
            print(f"  {caption} ({dn}/{court_id}): resolve failed, skipped -- "
                  f"{run_signals.safe(exc)}", file=sys.stderr)
            return {"caption": caption, "resolved": False, "new_entries": 0,
                    "new_items": 0, "resolve_failed": True, "error": exc}
        if not docket:
            return {"caption": caption, "resolved": False, "new_entries": 0, "new_items": 0}
        case_id = str(docket["id"])
        source_url = CL_BASE_WEB + docket["absolute_url"] if docket.get("absolute_url") else None

    # Persist resolution + B2 subject first (so resolution survives a later poll failure).
    filed_at = upsert_case(conn, case_id, seed, docket)
    noted = write_b2_item(conn, case_id, seed, filed_at, source_url)
    conn.commit()
    if noted:
        cl_fold.refold_quietly(conn, case_id)  # a notes edit: the subject shows its latest

    # The stored high-water mark and last-seen filing date (both NULL on a fresh row;
    # upsert_case never writes entries_synced_at, so a fresh resolve reads NULL here).
    r = conn.execute(
        "SELECT entries_synced_at, latest_entry_at FROM cases WHERE case_id = ?", (case_id,)
    ).fetchone()
    since = r["entries_synced_at"] if r else None
    latest_entry_at = r["latest_entry_at"] if r else None

    # Pick the poll shape. Three paths:
    #   * mark set         -> incremental window (steady state, one request/quiet docket).
    #   * no mark, history  -> single descending PROBE to seed the mark from the page min:
    #     we already hold this docket's entries, so we need the timestamp, not a re-walk.
    #   * no mark, no history -> genuine full walk (a never-cleanly-polled or brand-new
    #     docket), gated by the per-run REQUEST budget since its cost is what varies. A
    #     deferred full walk keeps its NULL mark and runs on a later run.
    walk_requests = 0
    if since is not None:
        mode = "incremental"
        poll = lambda: poll_entries(base, headers, case_id, since=since)
    else:
        have_history = bool(latest_entry_at) and conn.execute(
            "SELECT COUNT(*) FROM case_entries WHERE case_id = ?", (case_id,)
        ).fetchone()[0] > 0
        if have_history:
            mode = "probe"
            poll = lambda: probe_mark(base, headers, case_id)
        elif bootstrap_requests <= 0:
            print(f"  {caption} (docket {case_id}): full-walk deferred (request budget spent)",
                  file=sys.stderr)
            return {"caption": caption, "resolved": True, "new_entries": 0, "new_items": 0,
                    "deferred": True}
        else:
            mode = "full-walk"
            _pages = [0]
            poll = lambda: poll_entries(base, headers, case_id, since=None, page_counter=_pages)

    # The mark and history reads above are ended before the poll, for the reason given
    # at the reuse lookup: a full walk is the longest idle stretch this collector has
    # (1:26-cv-11549 is 19 pages, over a minute at PAGE_THROTTLE), and a stream that
    # expires inside it must still reopen at the first write.
    conn.commit()

    # On failure skip the case with nothing half-written and the mark unmoved.
    try:
        entries, new_mark = poll()
    except common.RateBudgetExhausted:
        db.recover(conn)           # nothing half-written; docket keeps its NULL mark.
        raise                      # recover not rollback: a dead stream makes rollback raise,
                                   # which would crash instead of letting main() abort cleanly.
    except Exception as exc:
        db.recover(conn)           # recover not rollback: a dead stream makes rollback raise
        print(f"  {caption} (docket {case_id}): poll failed, skipped -- "
              f"{run_signals.safe(exc)}", file=sys.stderr)
        return {"caption": caption, "resolved": True, "new_entries": 0, "new_items": 0,
                "poll_failed": True, "error": exc}
    if mode == "full-walk":
        walk_requests = _pages[0]

    try:
        counts = write_entries(conn, case_id, caption, source_url, entries, types, excludes)
        # Advance the mark in the SAME transaction as the writes: if write_entries raised
        # we never reach here (mark unmoved), and if the commit fails the UPDATE rolls back
        # with the entries -- so the next run re-fetches exactly this window. This ordering
        # is the invariant that makes unattended polling safe. (probe returns the page MIN
        # so the next window re-covers the page; walk/incremental return the max.)
        if new_mark:
            conn.execute("UPDATE cases SET entries_synced_at = ? WHERE case_id = ?",
                         (new_mark, case_id))
        conn.commit()
        # The fold (R1 step d), after the commit and in its own transaction: which item
        # presents each entry, when something that decides it moved.
        if any(counts[k] for k in ("new_entries", "new_items", "adopted", "revised", "apart")):
            cl_fold.refold_quietly(conn, case_id)
    except Exception:
        # recover() over rollback() keeps the invariant AND survives a dead stream:
        # reopening abandons the open transaction, so neither the entries nor the
        # entries_synced_at UPDATE land and the mark stays unmoved -- the same
        # outcome rollback() produced, minus the crash when rollback() hits a dead
        # stream. Safe under reset()'s docstring warning only because this site
        # re-raises rather than swallowing: losing this batch is intended here.
        db.recover(conn)
        raise
    return {"caption": caption, "resolved": True, "docket_id": case_id,
            "total_entries": len(entries), "mode": mode, "since": since,
            "walk_requests": walk_requests, **counts}


def gate_listed_dockets(path: Path = GATES_PATH) -> set[str]:
    """The dockets an authored, unfalsified gate lists in `record_instruments`: the
    backfill walks these first (ruling 6), since their watermarks and verdicts point at
    rows. A missing or unreadable register is not an error -- the walk still runs, in
    case_id order."""
    try:
        gates = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    except (OSError, yaml.YAMLError):
        return set()
    return {str(c) for g in gates
            if g.get("kind") == "authored" and g.get("status") != "falsified"
            for c in (g.get("record_instruments") or [])}


BACKFILL_LOUD_AFTER = 3   # failed walks of one docket before main() notes it CUT


def backfill_due(conn, listed: set[str]) -> list[tuple[str, int]]:
    """(case_id, held rows) for every docket the id backfill has not walked that holds a
    row without an id.

    Order: gate-listed first; within that, dockets that have never failed a walk before
    ones that have (cl_backfill_attempts), then live before superseded, then fewest
    failures, then case_id. A docket that fails every time therefore moves behind the
    ones that do not, instead of heading the queue and ending every run's walk at itself.

    A docket is walked once. What a walk leaves unattached stays unattached until a
    person or a later unit ties it; re-walking would find the same answer."""
    rows = conn.execute(
        """SELECT c.case_id, c.superseded_by, COUNT(e.id) AS n,
                  SUM(e.cl_entry_id IS NULL) AS bare, COALESCE(a.failures, 0) AS failures
             FROM cases c JOIN case_entries e ON e.case_id = c.case_id
             LEFT JOIN cl_backfill_attempts a ON a.case_id = c.case_id
            WHERE c.case_id NOT IN (SELECT case_id FROM cl_backfill)
            GROUP BY c.case_id, c.superseded_by, a.failures""").fetchall()
    due = [r for r in rows if str(r["case_id"]).isdigit() and r["bare"]]
    due.sort(key=lambda r: (str(r["case_id"]) not in listed, r["failures"] > 0,
                            r["superseded_by"] is not None, r["failures"], str(r["case_id"])))
    return [(str(r["case_id"]), int(r["n"])) for r in due]


def _walk_failed(conn, case_id: str, why: str) -> None:
    """One more failed walk on the docket's record (cl_backfill_attempts), committed now:
    it is what moves the docket behind the healthy ones next run."""
    db.increment(conn, "cl_backfill_attempts", "case_id", case_id, {"failures": 1},
                 {"last_error": why[:300], "last_at": common.now_iso()})
    conn.commit()


def backfill_walk(conn, base: str, headers: dict, budget: int, listed: set[str]) -> dict:
    """The CourtListener id backfill (R1 step b, Corey 2026-09-30, ruling 6): one full
    walk per docket, up to `budget` requests a run, attaching entry ids to held rows.

    A docket is walked only if its estimated pages (held rows / 20, the measured page
    size) fit what is left; the walk stops at the first that does not, so gate-listed
    dockets finish before any other starts. A docket bigger than a whole run's budget
    starts on a fresh run.

    A failed walk writes nothing for its docket, records the failure, and the docket is
    walked again on a later run, behind the dockets that have not failed. What ends the
    run's walk is evidence that the UPSTREAM is failing, not one docket: two systemic
    failures in a row (retries spent on a 5xx or a timeout, a persistent empty page, a
    docket served empty), a 401, the same 4xx twice running, or the daily cap. A lone
    4xx or a lone systemic failure costs that docket only. Nothing here moves
    `entries_synced_at`."""
    out = {"walked": 0, "requests": 0, "left": 0, "failed": 0, "stopped": None,
           "daily_cap": False, "errors": [], "stuck": [], "attached": 0, "unattached": 0,
           "never_held": 0, "stale": 0, "apart": 0}
    due = backfill_due(conn, listed)
    conn.commit()
    left = budget
    streak = 0            # systemic failures in a row this run
    last_4xx = None       # the previous docket's 4xx status, if it had one
    for case_id, n in due:
        est = max(1, math.ceil(n / 20))
        if est > left and left < budget:
            out["stopped"] = f"next docket {case_id} needs ~{est} request(s), {left} left"
            break
        pages = [0]
        before = SPEND.backfill
        SPEND.walking = True
        try:
            entries, _ = poll_entries(base, headers, case_id, since=None, page_counter=pages)
        except common.RateBudgetExhausted as exc:
            out["daily_cap"] = True
            out["stopped"] = f"daily cap hit on {case_id} ({run_signals.safe(exc)})"
            break
        except Exception as exc:
            out["failed"] += 1
            why = run_signals.safe(exc)
            print(f"  backfill {case_id}: walk failed, walks again later -- {why}",
                  file=sys.stderr)
            status = exc.status_code if isinstance(exc, common.HttpError) else None
            _walk_failed(conn, case_id, why)
            if status is not None and 400 <= status < 500:
                # A 4xx is one docket's (gone, sealed) unless it is the credential or it
                # repeats: a 401 is always the token, and the same refusal twice running
                # is the query or the account, not two dockets.
                out["errors"].append(exc)
                if status == 401 or status == last_4xx:
                    out["stopped"] = f"walk of {case_id} refused, HTTP {status} ({why})"
                    break
                last_4xx = status
                continue
            streak += 1
            if streak >= 2:
                out["stopped"] = f"walk of {case_id} failed, the second in a row ({why})"
                break
            continue
        finally:
            SPEND.walking = False
            spent = SPEND.backfill - before
            left -= spent
            out["requests"] += spent
        if n and not any(cl_objects.derive(e) and e.get("id") is not None for e in entries):
            # Nothing served for a docket that holds rows: a throttle's empty 200, or a
            # docket upstream now serves empty. A receipt would end its backfill for good.
            out["failed"] += 1
            print(f"  backfill {case_id}: walk served no entries over {n} held row(s), "
                  f"walks again later", file=sys.stderr)
            _walk_failed(conn, case_id, f"served no entries over {n} held row(s)")
            streak += 1
            if streak >= 2:
                out["stopped"] = (f"walk of {case_id} served no entries, the second failure "
                                  f"in a row")
                break
            continue
        try:
            c = cl_objects.backfill_docket(conn, case_id, entries, common.now_iso())
            conn.execute(
                "INSERT INTO cl_backfill (case_id, walked_at, requests, rows, objects, exact, "
                "adopted, token, token_shared, unattached, never_held, stale, apart) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (case_id, common.now_iso(), spent, n, c["objects"], c["exact"],
                 c["adopted"], c["token"], c["token_shared"], c["unattached"],
                 c["never_held"], c["stale"], c["apart"]))
            conn.execute("DELETE FROM cl_backfill_attempts WHERE case_id = ?", (case_id,))
            # The walk ties stale rows to their entries, which can move the docket's date
            # (Nevada). Same transaction as the ids that move it.
            cl_fold.recompute_latest(conn, case_id)
            conn.commit()
            cl_fold.refold_quietly(conn, case_id)   # its own transaction, after the receipt
        except Exception as exc:
            # recover() may itself raise on a dead remote; that ends the walk in main()'s
            # guarded handler rather than walking on into writes that cannot land.
            db.recover(conn)
            out["failed"] += 1
            print(f"  backfill {case_id}: write failed, walks again later -- "
                  f"{run_signals.safe(exc)}", file=sys.stderr)
            continue
        streak, last_4xx = 0, None
        out["walked"] += 1
        out["attached"] += c["exact"] + c["adopted"] + c["token"]
        for k in ("unattached", "never_held", "stale", "apart"):
            out[k] += c[k]
        print(f"  backfill {case_id}{' (gate-listed)' if case_id in listed else ''}: "
              f"{spent}req  {c['objects']} objects over {n} rows  attached "
              f"{c['exact']} exact + {c['adopted']} adopted + {c['token']} token  "
              f"unattached {c['unattached']}  never held {c['never_held']}  "
              f"stale {c['stale']}  apart {c['apart']}")
    # Every docket this run did not receipt is still due, the failed ones included.
    out["left"] = len(due) - out["walked"]
    out["stuck"] = [(r["case_id"], r["failures"], r["last_error"]) for r in conn.execute(
        "SELECT case_id, failures, last_error FROM cl_backfill_attempts "
        "WHERE failures >= ? ORDER BY case_id", (BACKFILL_LOUD_AFTER,)).fetchall()]
    conn.commit()
    return out


def _recover_quietly(conn) -> None:
    """db.recover, which can itself raise on a dead remote, where a raise would turn the
    collector's exit 0 into a lost cycle (run_signals.flush guards its own the same way)."""
    try:
        db.recover(conn)
    except Exception:
        pass


def record_spend(conn) -> str:
    """Add this run's requests to today's ledger row and say where the day stands."""
    day = datetime.now(timezone.utc).date().isoformat()
    db.increment(conn, "cl_usage", "day", day,
                 {"requests": SPEND.total, "backfill": SPEND.backfill},
                 {"updated_at": common.now_iso()})
    conn.commit()
    r = conn.execute("SELECT requests, backfill FROM cl_usage WHERE day = ?", (day,)).fetchone()
    return (f"litigation: {SPEND.total} CourtListener request(s) this run, {SPEND.backfill} "
            f"of them the id backfill; {day} so far {r['requests']}, backfill {r['backfill']}")


def load_tracker_seeds(path: str = TRACKER_ARTIFACT) -> list[dict]:
    """The DOJ-suit seeds discovered by collectors.tracker_uw, if the artifact
    exists. Each entry already matches the collect_case seed contract (caption,
    docket_number, court, court_id, category, notes). A missing artifact is not an
    error -- the config seed_cases still run."""
    p = Path(path)
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def due_for_status_refresh(conn, stale_before: str) -> list:
    """Non-terminated rows whose `status` has not been read since `stale_before`.

    `terminated` is absorbing on the court's clock -- a docket does not un-terminate
    -- so a terminated row never needs re-reading and the refresh set shrinks as rows
    flip. That is what keeps this pass at ~+17% on the daily draw instead of doubling
    it. NULL status is included: it means the row was never resolved, not that it is
    terminated.

    Ordering is never-checked first, then oldest-checked: a pass that hits the cap or
    the daily budget still makes progress on the LEAST fresh rows rather than
    re-walking the same head of the list every run."""
    return conn.execute(
        """SELECT case_id, caption, status, status_checked_at, date_terminated
             FROM cases
            WHERE (status IS NULL OR status <> 'terminated')
              AND (status_checked_at IS NULL OR status_checked_at < ?)
            ORDER BY status_checked_at IS NOT NULL, status_checked_at, case_id""",
        (stale_before,),
    ).fetchall()


def refresh_status(conn, base: str, headers: dict, stale_before: str, cap: int) -> dict:
    """Re-read `cases.status` from CourtListener for every due row. One request each.

    This exists because `status` is otherwise write-once: upsert_case sets it only
    inside `if docket is not None:`, i.e. only on a fresh resolve, and a resolved case
    is never re-resolved. So a case that terminates AFTER its first resolve reads
    `pending` indefinitely -- 9 of 40 rows on 2026-08-10, six of them actively seeded
    and polled every six hours the whole time. Polling never re-read status; this pass
    is the only thing that does.

    It iterates `cases`, not the seed list, which is the point: the three district
    orphans that dropped out of the seed artifact (NM, VA, KY) are in the due set and
    get covered with no seeding change at all.

    Non-numeric case_ids are skipped without a request. All 40 rows are numeric today,
    but that is a property of today's data, not of the schema -- collect_case slugifies
    a caption for a B2-only seed with no docket_number, and such a row has no docket to
    look up. Counting the skips keeps that visible rather than assumed.

    Returns counts; writes are targeted UPDATEs (never db.upsert, which would rewrite
    the whole row) and commit per row, matching the seed loop."""
    rows = due_for_status_refresh(conn, stale_before)
    skipped = [r for r in rows if not str(r["case_id"]).isdigit()]
    due = [r for r in rows if str(r["case_id"]).isdigit()]
    counts = {"due": len(due), "skipped": len(skipped), "checked": 0,
              "changed": 0, "failed": 0, "capped": False, "aborted": False,
              "errors": []}

    print(f"litigation: status refresh, {len(due)} row(s) due "
          f"({len(skipped)} skipped, non-numeric case_id)")
    if len(due) > cap:
        counts["capped"] = True
        print(f"  capped at {cap}/{len(due)}; the rest are the freshest and resume next run")
        due = due[:cap]
    counts["taken"] = len(due)   # this pass's work, the denominator the abort line prints

    for row in due:
        case_id, caption = str(row["case_id"]), row["caption"]
        try:
            docket = common.http_get(f"{base}/dockets/{case_id}/",
                                     headers=headers, throttle=PAGE_THROTTLE,
                                     on_attempt=SPEND.hit)
            live = case_status(docket)
            live_terminated = common.to_iso(docket.get("date_terminated"))
            now = common.now_iso()
            # THE DATE IS PART OF THE COMPARISON, not a passenger on the status change.
            # `status` is one bit of this value, so a row can be right about the bit and
            # wrong about the date -- a corrected or amended termination date moves the
            # date and not the bit, and comparing only `status` would hold the stale one
            # while the receipt above kept claiming the row was checked.
            #
            # WHAT THIS DOES NOT REACH, stated here because the obvious reading is that
            # it does: `terminated` is absorbing in due_for_status_refresh, so the rows
            # ALREADY terminated when this column arrived are never in the due set and
            # this pass will never see them. Their dates come from the one-time backfill
            # (handoff 97 H1b), not from here. What this branch covers is every docket
            # that terminates FROM NOW ON: it is pending, so it is due, and when it
            # flips, the bit and the date land in the same UPDATE.
            moved = live != row["status"] or live_terminated != row["date_terminated"]
            if moved:
                # Value moved: stamp updated_at too, since something on the row changed.
                conn.execute(
                    "UPDATE cases SET status = ?, date_terminated = ?, "
                    "status_checked_at = ?, updated_at = ? "
                    "WHERE case_id = ?", (live, live_terminated, now, now, case_id))
                counts["changed"] += 1
                print(f"  {caption[:46]:<46} status {row['status']} -> {live}"
                      f"  (date_terminated {row['date_terminated']} -> {live_terminated})")
            else:
                # No-op: the receipt moves, `updated_at` does NOT. Stamping it on a
                # daily no-op would make all 33 rows look freshly touched and destroy
                # the instrument that exposed both the starvation and the orphan class.
                conn.execute("UPDATE cases SET status_checked_at = ? WHERE case_id = ?",
                             (now, case_id))
            conn.commit()
            counts["checked"] += 1
        except common.RateBudgetExhausted as exc:
            # Raised by http_get before any write, so nothing is half-written and no
            # recover() is needed. Return rather than raise: main()'s exit-0 invariant
            # keeps executive/news/state running, and the unchecked rows are the
            # least-fresh ones, so next run's ordering picks up exactly here.
            counts["aborted"] = True
            print(f"litigation: status refresh aborted, daily cap hit ({exc}); "
                  f"{counts['checked']}/{len(due)} checked, rest retry next run",
                  file=sys.stderr)
            break
        except Exception as exc:
            # recover() not rollback(): a dead Hrana stream makes rollback() raise and
            # would take down the pass this handler exists to keep alive (handoff 15).
            db.recover(conn)
            counts["failed"] += 1
            counts["errors"].append(exc)
            print(f"  {caption[:46]} (docket {case_id}): status refresh failed, "
                  f"skipped -- {run_signals.safe(exc)}", file=sys.stderr)

    print(f"  status refresh: {counts['checked']} checked, {counts['changed']} changed, "
          f"{counts['skipped']} skipped, {counts['failed']} failed")
    return counts


class AuthTally:
    """CourtListener's answers this run, for unit 99's credential line.

    A dead token has never been captured (the D0 searched the repo and the docs); an
    anonymous request gets 401 (CourtListener's v4.3 change log). So: any 401 is a
    credential failure, its body quoted, and a 403 is one only when EVERY request this
    run was refused -- a lone 403 among good replies stays a per-docket skip."""

    def __init__(self):
        self.ok = 0
        self.first_401: common.HttpError | None = None
        self.n_403 = 0
        self.first_403: common.HttpError | None = None

    def failed(self, exc) -> None:
        if isinstance(exc, common.HttpError):
            if exc.status_code == 401 and self.first_401 is None:
                self.first_401 = exc
            elif exc.status_code == 403:
                self.n_403 += 1
                if self.first_403 is None:
                    self.first_403 = exc

    def verdict(self, secrets) -> str | None:
        if self.first_401 is not None:
            return f"HTTP 401 {run_signals.quote(self.first_401.body, secrets)}"
        if self.n_403 and not self.ok:
            return (f"every request refused, HTTP 403 x{self.n_403} "
                    f"{run_signals.quote(self.first_403.body, secrets)}")
        return None


def main() -> int:
    config.load_env()
    db.init_db()
    sources = config.load_sources()
    lit = sources["litigation"]
    base = lit["api"]["base"].rstrip("/")
    key_env = lit["api"]["key_env"]
    token = run_signals.secret(key_env)
    sig = run_signals.RunSignals("litigation", secrets=(token,))
    if not token:
        # R5 (Corey, 2026-09-28): skip this channel, print its line; the rest of the run
        # goes on and the verdict step turns it red.
        sig.note(run_signals.MISSING, f"{key_env} is not set")
        conn = db.connect()
        try:
            sig.flush(conn)
        finally:
            conn.close()
        return 0
    headers = {"Authorization": f"Token {token}", "User-Agent": USER_AGENT}
    auth = AuthTally()
    types = lit.get("substantive_entry_types", [])
    excludes = lit.get("excluded_entry_phrases", [])
    bootstrap_requests = lit.get("max_bootstrap_requests_per_run", 30)
    refresh_hours = lit.get("status_refresh_hours", 24)
    refresh_cap = lit.get("max_status_refresh_per_run", 40)
    backfill_budget = lit.get("max_backfill_requests_per_run", 0)

    conn = db.connect()
    try:
        register_sources(conn)
        conn.commit()
        config_seeds = lit.get("seed_cases", [])
        tracker_seeds = load_tracker_seeds()
        print(f"litigation: {len(config_seeds)} config seed(s) + {len(tracker_seeds)} "
              f"tracker case(s) from {TRACKER_ARTIFACT}  (full-walk req budget {bootstrap_requests})")
        cap_hit = False
        refresh_aborted = False
        seeds = config_seeds + tracker_seeds
        for i, seed in enumerate(seeds):
            try:
                r = collect_case(conn, base, headers, seed, types, excludes, bootstrap_requests)
            except common.RateBudgetExhausted as exc:
                # Expected budget condition, not an error: abort THIS collector at one
                # request, exit 0 (below) so executive/news/state still run. Un-probed
                # dockets keep their NULL mark and retry next run.
                print(f"litigation: daily cap hit ({exc}); aborting run. Un-probed dockets "
                      f"keep their NULL mark and retry next run.", file=sys.stderr)
                # R6 (Corey, 2026-09-28): a skip. The window is rolling and the loop order
                # fixed, so nothing guarantees the next run reaches the same tail.
                sig.note(run_signals.CUT, f"daily cap hit ({exc}); {len(seeds) - i} of "
                                          f"{len(seeds)} seeds unpolled, status refresh skipped")
                cap_hit = True
                break
            bootstrap_requests -= r.get("walk_requests", 0)   # only full walks draw the budget
            if r.get("error") is not None:
                auth.failed(r["error"])
            elif r.get("resolved") and not r.get("deferred"):
                auth.ok += 1
            if r.get("deferred"):
                # A planned deferral (R6): printed, never loud.
                sig.note(run_signals.DEFERRED, "full walk deferred, request budget spent; "
                                               "walks next run")
                tag = "full-walk deferred (request budget spent; walks next run)"
            elif r.get("resolved"):
                win = "bootstrap" if r.get("since") is None else f"since={r.get('since')}"
                cost = f" [{r['walk_requests']}req]" if r.get("walk_requests") else ""
                tag = (f"docket {r.get('docket_id')}  {r.get('mode', '?')}  {win}{cost}  "
                       f"{r.get('total_entries', 0)} entries  +{r['new_entries']} entries  "
                       f"+{r['new_items']} A1 items")
            elif r.get("resolve_failed"):
                tag = "resolve failed, skipped (retries next run)"
            else:
                tag = "B2-only (no docket_number)"
            print(f"  {r['caption'][:46]:<46} {tag}")

        # After the seed loop, so a refresh failure can never cost the polling that
        # has already committed per case. Skipped outright when the loop broke on the
        # cap -- the budget is spent, so every refresh request would 429 immediately.
        # Tracked with a flag rather than inferred from the loop's end state.
        if cap_hit:
            print("litigation: status refresh skipped (daily cap already hit this run)",
                  file=sys.stderr)
        else:
            stale_before = (datetime.now(timezone.utc)
                            - timedelta(hours=refresh_hours)).isoformat()
            try:
                # BOUND, not discarded (R6, R11): the cap-abort flag used to be computed
                # here and thrown away, so a refresh the daily cap cut short exited 0.
                refreshed = refresh_status(conn, base, headers, stale_before, refresh_cap)
                refresh_aborted = refreshed["aborted"]
                auth.ok += refreshed["checked"]
                for exc in refreshed["errors"]:
                    auth.failed(exc)
                if refreshed["aborted"]:
                    sig.note(run_signals.CUT, f"status refresh aborted, daily cap hit; "
                                              f"{refreshed['checked']}/{refreshed['taken']} checked"
                                              + (f" ({refreshed['due']} due, capped at "
                                                 f"{refresh_cap})" if refreshed["capped"] else ""))
                elif refreshed["capped"]:
                    sig.note(run_signals.DEFERRED, f"status refresh capped at {refresh_cap} of "
                                                   f"{refreshed['due']} due; the rest resume next run")
            except Exception as exc:
                # Exit-0 invariant. The collectors run as sequential lines in one `-e`
                # step, so a raise here costs export and the data commit for the WHOLE
                # cycle -- a lost run that looks like an empty diff. The seed loop has
                # already committed per case; the refresh is the optional half and must
                # never take the half that worked down with it.
                #
                # The unguarded line was refresh_status's first: due_for_status_refresh
                # runs its SELECT before any per-row handler exists. Two live ways in --
                # a missing status_checked_at if the migration hasn't applied, and a dead
                # Hrana stream on that query, the failure family handoff 15 closed
                # everywhere else in this file.
                print(f"litigation: status refresh pass failed, skipped -- "
                      f"{run_signals.safe(exc)}", file=sys.stderr)
        # The id backfill (R1 step b) runs last, on its own budget, and never costs the
        # run: polling and the status refresh have already committed. Skipped when the
        # seed loop OR the refresh hit the daily cap, for the reason the refresh is.
        if backfill_budget > 0 and (cap_hit or refresh_aborted):
            print("litigation: id backfill skipped (daily cap already hit this run)",
                  file=sys.stderr)
        elif backfill_budget > 0:
            try:
                listed = gate_listed_dockets()
                print(f"litigation: id backfill, budget {backfill_budget} request(s)")
                walked = backfill_walk(conn, base, headers, backfill_budget, listed)
                print(f"  id backfill: {walked['walked']} docket(s) walked, "
                      f"{walked['failed']} failed, {walked['requests']} request(s), "
                      f"{walked['attached']} row(s) attached, {walked['unattached']} "
                      f"unattached, {walked['left']} docket(s) left"
                      + (f"; stopped: {walked['stopped']}" if walked["stopped"] else ""))
                for exc in walked["errors"]:
                    auth.failed(exc)
                if walked["daily_cap"]:
                    sig.note(run_signals.CUT, f"id backfill stopped, daily cap hit; "
                                              f"{walked['left']} docket(s) left")
                for case_id, failures, why in walked["stuck"]:
                    # Nothing guarantees a later run gets past it: R6's cut short.
                    sig.note(run_signals.CUT, f"id backfill: docket {case_id} has failed "
                                              f"{failures} walks, last: {why}")
                if walked["left"]:
                    # R6: a planned deferral prints its line, with why the walk stopped.
                    sig.note(run_signals.DEFERRED,
                             f"id backfill: {walked['left']} docket(s) left"
                             + (f", {walked['failed']} failed" if walked["failed"] else "")
                             + (f"; stopped: {walked['stopped']}" if walked["stopped"]
                                else "") + "; walks next run")
            except Exception as exc:
                _recover_quietly(conn)
                print(f"litigation: id backfill failed, skipped -- {run_signals.safe(exc)}",
                      file=sys.stderr)
        # The fold sweep: any case holding an item a refold has not reached (a refold that
        # failed, or items from before the fold). Each refolds in its own transaction.
        try:
            swept = cl_fold.unfolded(conn)
            conn.commit()
            for case_id in swept:
                cl_fold.refold_quietly(conn, case_id)
            if swept:
                print(f"litigation: fold sweep refolded {len(swept)} case(s)")
        except Exception as exc:
            _recover_quietly(conn)
            print(f"litigation: fold sweep failed, skipped -- {run_signals.safe(exc)}",
                  file=sys.stderr)
        credential = auth.verdict((token,))
        if credential is not None:
            sig.note(run_signals.CREDENTIAL, credential)
        sig.reached(auth.ok)
        sig.flush(conn)
    except BaseException:
        # A raise can leave a write open (a walk between its ids and its receipt, a case
        # between upsert_case and its B2 item). The ledger's commit below would land it,
        # where a bare close() used to throw it away; discard it first. Every phase has
        # already committed its own finished work.
        _recover_quietly(conn)
        raise
    finally:
        # The day's ledger, in `finally` so a run that raised still records what it spent.
        try:
            print(record_spend(conn))
        except Exception as exc:
            _recover_quietly(conn)
            print(f"litigation: request ledger not written -- {run_signals.safe(exc)}",
                  file=sys.stderr)
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
