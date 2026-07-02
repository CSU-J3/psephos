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

PAGE_THROTTLE = 2.0   # seconds between CourtListener requests (rate limit is real)
EMPTY_RETRIES = 5     # retries for an unexpectedly empty page before giving up


def slugify(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def split_caption(caption: str) -> tuple[str | None, str | None]:
    """'A v. B' -> ('A', 'B'); best-effort, None if no ' v. '."""
    m = re.split(r"\s+v\.?\s+", caption, maxsplit=1)
    return (m[0].strip(), m[1].strip()) if len(m) == 2 else (None, None)


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


def _fetch_page(url: str, params: dict | None, headers: dict) -> dict:
    """Fetch one page, retrying defensively on an empty result set.

    A rate limit can return an empty 200; a real docket has no empty middle pages.
    So: retry empties with backoff; if still empty AND a `next` cursor exists, that's
    a rate-limit failure -> raise (the caller skips the case, leaving nothing
    half-written). Empty with no `next` is accepted as a genuinely empty page.
    """
    data = {}
    for attempt in range(EMPTY_RETRIES):
        data = common.http_get(url, params=params, headers=headers, throttle=PAGE_THROTTLE)
        if data.get("results"):
            return data
        time.sleep(PAGE_THROTTLE * (attempt + 1) + 1)
    if data.get("next"):
        raise RuntimeError(f"persistent empty pages from {url} (rate-limited?)")
    return data


def poll_entries(base: str, headers: dict, docket_id: str) -> list[dict]:
    """Return ALL docket entries (paginated via the `next` cursor) or raise.

    Returns the full list only on success; on a rate-limit failure mid-pagination
    it raises, so the caller writes nothing for the case (no half-seeded table)."""
    out: list[dict] = []
    url = f"{base}/docket-entries/"
    params: dict | None = {"docket": docket_id, "order_by": "entry_number"}
    while url:
        data = _fetch_page(url, params, headers)
        params = None  # the `next` URL carries its own query string
        out.extend(data.get("results") or [])
        url = data.get("next")
    return out


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
    row = {
        "case_id": case_id,
        "caption": caption,
        "court": seed.get("court"),
        "docket_number": seed.get("docket_number"),
        "category": seed.get("category"),
        "plaintiff": plaintiff,
        "defendant": defendant,
        "seeded_from": SEED_SOURCE_ID,
        "updated_at": common.now_iso(),
    }
    filed_at = None
    if docket is not None:
        filed_at = common.to_iso(docket.get("date_filed"))
        row["filed_at"] = filed_at
        row["status"] = "pending" if not docket.get("date_terminated") else "terminated"
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
    Single transaction at the call site -- caller commits on success only."""
    counts = {"new_entries": 0, "new_items": 0}
    latest = None
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
        if entry_at and (latest is None or entry_at > latest):
            latest = entry_at
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
    if latest:
        conn.execute("UPDATE cases SET latest_entry_at = ? WHERE case_id = ?", (latest, case_id))
    return counts


# --------------------------------------------------------------------------- #
# Per-case orchestration
# --------------------------------------------------------------------------- #
def collect_case(conn, base: str, headers: dict, seed: dict,
                 types: list[str], excludes: list[str]) -> dict:
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

    # Poll the full docket; on failure skip the case with nothing half-written.
    try:
        entries = poll_entries(base, headers, case_id)
    except Exception as exc:
        conn.rollback()
        print(f"  {caption} (docket {case_id}): poll failed, skipped -- {exc}", file=sys.stderr)
        return {"caption": caption, "resolved": True, "new_entries": 0, "new_items": 0, "poll_failed": True}

    try:
        counts = write_entries(conn, case_id, caption, source_url, entries, types, excludes)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"caption": caption, "resolved": True, "docket_id": case_id,
            "total_entries": len(entries), **counts}


def load_tracker_seeds(path: str = TRACKER_ARTIFACT) -> list[dict]:
    """The DOJ-suit seeds discovered by collectors.tracker_uw, if the artifact
    exists. Each entry already matches the collect_case seed contract (caption,
    docket_number, court, court_id, category, notes). A missing artifact is not an
    error -- the config seed_cases still run."""
    p = Path(path)
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


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

    conn = db.connect()
    try:
        register_sources(conn)
        conn.commit()
        config_seeds = lit.get("seed_cases", [])
        tracker_seeds = load_tracker_seeds()
        print(f"litigation: {len(config_seeds)} config seed(s) + {len(tracker_seeds)} "
              f"tracker case(s) from {TRACKER_ARTIFACT}")
        for seed in config_seeds + tracker_seeds:
            r = collect_case(conn, base, headers, seed, types, excludes)
            if r.get("resolved"):
                tag = (f"docket {r.get('docket_id')}  {r.get('total_entries', 0)} entries  "
                       f"+{r['new_entries']} entries  +{r['new_items']} A1 items")
            elif r.get("resolve_failed"):
                tag = "resolve failed, skipped (retries next run)"
            else:
                tag = "B2-only (no docket_number)"
            print(f"  {r['caption'][:46]:<46} {tag}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
