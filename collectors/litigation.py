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
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import common
import config
import db

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
        headers=headers, throttle=PAGE_THROTTLE,
    )
    results = data.get("results") or []
    if len(results) != 1:
        print(f"  {docket_number}/{court_id}: expected 1 docket, got {len(results)} "
              f"-- NOT binding", file=sys.stderr)
        return None
    return results[0]


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
        return common.http_get(url, params=params, headers=headers, throttle=PAGE_THROTTLE)
    data = {}
    for attempt in range(EMPTY_RETRIES):
        data = common.http_get(url, params=params, headers=headers, throttle=PAGE_THROTTLE)
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

    Caveat (latent, NOT fixed here): content_hash(case_id, entry_at, desc) keys an A1
    item on its description, so a *modified* description now surfaces as a SECOND item
    rather than updating the first. Incremental polling makes that live; note it, don't
    fix it in this change.

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
        first = False
        params = None  # the `next` URL carries its own query string
        results = data.get("results") or []
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
        row["source_url"] = CL_BASE_WEB + docket["absolute_url"] if docket.get("absolute_url") else None
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
    MAX(case_entries.entry_at) for the case, and it is recomputed at the bottom of
    this function. This is the ONLY code path that inserts into `case_entries`, and
    `collect_case` is its only caller, so all three poll modes -- incremental, probe
    and full-walk -- reach the recompute by construction rather than by enumeration.
    Keep it that way: a second insert site would need its own recompute.

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
    counts = {"new_entries": 0, "new_items": 0}
    for e in entries:
        entry_at = common.to_iso(e.get("date_filed"))
        docs = e.get("recap_documents") or []
        # Document-only entries have an empty entry-level description; the PACER text
        # then lives on the document (e.g. "Order on Motion for Briefing Schedule").
        # Fall back to it so the record is complete and such orders still classify.
        desc = (e.get("description") or "").strip()
        if not desc and docs:
            desc = (docs[0].get("description") or docs[0].get("short_description") or "").strip()
        if not desc:
            continue
        doc_url = None
        if docs and docs[0].get("absolute_url"):
            doc_url = CL_BASE_WEB + docs[0]["absolute_url"]
        if db.insert_ignore(conn, "case_entries", {
            "case_id": case_id, "entry_at": entry_at, "description": desc, "document_url": doc_url,
        }):
            counts["new_entries"] += 1
        if is_substantive(desc, types, excludes):
            if db.insert_ignore(conn, "items", {
                "channel": CHANNEL, "source_id": API_SOURCE_ID,
                "source_url": doc_url or source_url or CL_BASE_WEB,
                "title": f"{caption}: {desc[:180]}", "summary": desc,
                "occurred_at": entry_at, "fetched_at": common.now_iso(),
                "admiralty_source": "A", "admiralty_info": "1", "confidence": None,
                "bill_id": None, "case_id": case_id,
                "content_hash": common.content_hash(case_id, entry_at, desc),
                "raw_json": json.dumps({k: e.get(k) for k in ("entry_number", "date_filed", "description")},
                                       separators=(",", ":")),
            }):
                counts["new_items"] += 1
    # Recompute from the table, gated on having inserted something: insert_ignore
    # returns False on a duplicate, so zero new rows means case_entries did not change
    # and neither can its MAX. That makes the write necessary-and-sufficient rather
    # than a no-op UPDATE on all 34 dockets every run. It also self-heals -- a row that
    # drifted before this change corrects itself on its next non-empty poll, which is
    # why the repair script is one-time rather than scheduled.
    if counts["new_entries"]:
        conn.execute(
            "UPDATE cases SET latest_entry_at = "
            "(SELECT MAX(entry_at) FROM case_entries WHERE case_id = ?) WHERE case_id = ?",
            (case_id, case_id),
        )
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
        write_b2_item(conn, case_id, seed, filed_at, None)
        conn.commit()
        return {"caption": caption, "resolved": False, "new_entries": 0, "new_items": 0}

    # Reuse a persisted resolution; only hit the API for unknown cases.
    existing = conn.execute(
        "SELECT case_id, source_url FROM cases WHERE docket_number = ? AND court = ?",
        (dn, seed.get("court")),
    ).fetchone()
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
        try:
            docket = resolve_docket(base, headers, dn, court_id)
        except RuntimeError as exc:
            print(f"  {caption} ({dn}/{court_id}): resolve failed, skipped -- {exc}", file=sys.stderr)
            return {"caption": caption, "resolved": False, "new_entries": 0,
                    "new_items": 0, "resolve_failed": True}
        if not docket:
            return {"caption": caption, "resolved": False, "new_entries": 0, "new_items": 0}
        case_id = str(docket["id"])
        source_url = CL_BASE_WEB + docket["absolute_url"] if docket.get("absolute_url") else None

    # Persist resolution + B2 subject first (so resolution survives a later poll failure).
    filed_at = upsert_case(conn, case_id, seed, docket)
    write_b2_item(conn, case_id, seed, filed_at, source_url)
    conn.commit()

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

    # On failure skip the case with nothing half-written and the mark unmoved.
    try:
        entries, new_mark = poll()
    except common.RateBudgetExhausted:
        db.recover(conn)           # nothing half-written; docket keeps its NULL mark.
        raise                      # recover not rollback: a dead stream makes rollback raise,
                                   # which would crash instead of letting main() abort cleanly.
    except Exception as exc:
        db.recover(conn)           # recover not rollback: a dead stream makes rollback raise
        print(f"  {caption} (docket {case_id}): poll failed, skipped -- {exc}", file=sys.stderr)
        return {"caption": caption, "resolved": True, "new_entries": 0, "new_items": 0, "poll_failed": True}
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
        """SELECT case_id, caption, status, status_checked_at
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
              "changed": 0, "failed": 0, "capped": False, "aborted": False}

    print(f"litigation: status refresh, {len(due)} row(s) due "
          f"({len(skipped)} skipped, non-numeric case_id)")
    if len(due) > cap:
        counts["capped"] = True
        print(f"  capped at {cap}/{len(due)}; the rest are the freshest and resume next run")
        due = due[:cap]

    for row in due:
        case_id, caption = str(row["case_id"]), row["caption"]
        try:
            docket = common.http_get(f"{base}/dockets/{case_id}/",
                                     headers=headers, throttle=PAGE_THROTTLE)
            live = case_status(docket)
            now = common.now_iso()
            if live != row["status"]:
                # Value moved: stamp updated_at too, since something on the row changed.
                conn.execute(
                    "UPDATE cases SET status = ?, status_checked_at = ?, updated_at = ? "
                    "WHERE case_id = ?", (live, now, now, case_id))
                counts["changed"] += 1
                print(f"  {caption[:46]:<46} status {row['status']} -> {live}"
                      f"  (date_terminated {docket.get('date_terminated')})")
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
            print(f"  {caption[:46]} (docket {case_id}): status refresh failed, "
                  f"skipped -- {exc}", file=sys.stderr)

    print(f"  status refresh: {counts['checked']} checked, {counts['changed']} changed, "
          f"{counts['skipped']} skipped, {counts['failed']} failed")
    return counts


def main() -> int:
    config.load_env()
    db.init_db()
    sources = config.load_sources()
    lit = sources["litigation"]
    base = lit["api"]["base"].rstrip("/")
    token = config.require_env(lit["api"]["key_env"])
    headers = {"Authorization": f"Token {token}", "User-Agent": USER_AGENT}
    types = lit.get("substantive_entry_types", [])
    excludes = lit.get("excluded_entry_phrases", [])
    bootstrap_requests = lit.get("max_bootstrap_requests_per_run", 30)
    refresh_hours = lit.get("status_refresh_hours", 24)
    refresh_cap = lit.get("max_status_refresh_per_run", 40)

    conn = db.connect()
    try:
        register_sources(conn)
        conn.commit()
        config_seeds = lit.get("seed_cases", [])
        tracker_seeds = load_tracker_seeds()
        print(f"litigation: {len(config_seeds)} config seed(s) + {len(tracker_seeds)} "
              f"tracker case(s) from {TRACKER_ARTIFACT}  (full-walk req budget {bootstrap_requests})")
        cap_hit = False
        for seed in config_seeds + tracker_seeds:
            try:
                r = collect_case(conn, base, headers, seed, types, excludes, bootstrap_requests)
            except common.RateBudgetExhausted as exc:
                # Expected budget condition, not an error: abort THIS collector at one
                # request, exit 0 (below) so executive/news/state still run. Un-probed
                # dockets keep their NULL mark and retry next run.
                print(f"litigation: daily cap hit ({exc}); aborting run. Un-probed dockets "
                      f"keep their NULL mark and retry next run.", file=sys.stderr)
                cap_hit = True
                break
            bootstrap_requests -= r.get("walk_requests", 0)   # only full walks draw the budget
            if r.get("deferred"):
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
                refresh_status(conn, base, headers, stale_before, refresh_cap)
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
                print(f"litigation: status refresh pass failed, skipped -- {exc}",
                      file=sys.stderr)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
