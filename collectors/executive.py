"""Executive collector — Federal Register API.

Queries /documents.json for the configured agencies and terms (config/sources.yaml
-> executive) and writes each new document to `items` as an A1 record. This is the
channel that catches the election executive order and the agency rulemaking behind
the DOJ voter-data effort -- changes that never touch Congress and so are invisible
to the legislation collector.

Idempotency: content_hash is keyed on the Federal Register `document_number`, which
is globally unique and immutable. With items.content_hash UNIQUE + db.insert_ignore
that dedups both across overlapping term queries (a doc matching two terms hashes
identically) and across runs -- no dedup bookkeeping table needed.

A `since` floor (executive.since; default 2025-01-01) bounds the first-run backfill:
the FR archive spans decades, and a broad term like "election" without a floor would
hit FR's deep-pagination cap. The FR API needs no key.

Run from the repo root:  python -m collectors.executive
"""

from __future__ import annotations

import json
import sys

import common
import config
import db

SOURCE_ID = "federal-register"
CHANNEL = "executive"
PER_PAGE = 1000  # Federal Register documents.json max page size
DOCS_PATH = "/documents.json"
DEFAULT_SINCE = "2025-01-01"  # fallback publication-date floor if executive.since absent
# Explicit field projection keeps raw_json small and the response stable. The
# superset is shared by both query shapes: the agency shape uses `action`, the
# presidential shape uses subtype / executive_order_number / signing_date /
# citation. Fields absent from a given document just come back null.
# NOTE: `presidential_document_type` is a valid query *condition* (it's the EO
# filter on the presidential shape) but NOT a returnable field -- FR 400s if it
# appears in fields[]. We don't need it back anyway; EO detection keys on
# executive_order_number.
FIELDS = [
    "document_number",
    "title",
    "abstract",
    "type",
    "subtype",
    "executive_order_number",
    "publication_date",
    "signing_date",
    "html_url",
    "pdf_url",
    "citation",
    "agencies",
    "action",
]


def register_source(conn, base: str, gsource: str, ginfo: str) -> None:
    db.upsert(conn, "sources", {
        "id": SOURCE_ID,
        "name": "Federal Register API",
        "channel": CHANNEL,
        "kind": "api",
        "url": base,
        "admiralty_source": gsource,
        "admiralty_info": ginfo,
        "enabled": 1,
        "notes": "Primary government record; executive orders, rules, and notices on elections.",
    }, pk="id")


def build_params(agencies: list[str], term: str, since: str | None) -> dict:
    """Agency-shape first-page query dict. `requests` repeats list values, which is
    exactly FR's bracket-array convention: agencies -> conditions[agencies][] (OR'd),
    fields[]. Catches rules and notices from the configured cabinet agencies."""
    params = {
        "conditions[term]": term,
        "conditions[agencies][]": agencies,
        "per_page": PER_PAGE,
        "order": "newest",
        "fields[]": FIELDS,
    }
    if since:
        params["conditions[publication_date][gte]"] = since
    return params


def build_presidential_params(term: str, since: str | None) -> dict:
    """Presidential-shape first-page query dict. Filters by document *type* rather
    than agency: executive orders are attributed to the EOP slug, not a cabinet
    agency, so the type filter is what catches them (and keeps the agency list clean
    for the regulatory channel). No agencies filter on this shape."""
    params = {
        "conditions[term]": term,
        "conditions[type][]": "PRESDOCU",
        "conditions[presidential_document_type][]": "executive_order",
        "per_page": PER_PAGE,
        "order": "newest",
        "fields[]": FIELDS,
    }
    if since:
        params["conditions[publication_date][gte]"] = since
    return params


def fetch_documents(base: str, params: dict, throttle: float) -> list[dict]:
    """All documents for a pre-built first-page query. Follows next_page_url, which
    is an absolute, self-contained URL carrying the full query string."""
    url = f"{base}{DOCS_PATH}"
    page_params: dict | None = params
    out: list[dict] = []
    while True:
        data = common.http_get(url, params=page_params, throttle=throttle)
        out.extend(data.get("results") or [])
        nxt = data.get("next_page_url")
        if not nxt:
            break
        url, page_params = nxt, None  # next_page_url already encodes the query
    return out


def document_item_row(doc: dict, gsource: str, ginfo: str) -> dict:
    """Map a Federal Register document to an `items` row. content_hash is keyed on
    the document_number so the same doc never lands twice (across terms or runs)."""
    docnum = doc.get("document_number")
    title = doc.get("title") or f"(untitled Federal Register document {docnum})"
    eo_num = doc.get("executive_order_number")
    if eo_num:
        title = f"EO {eo_num}: {title}"  # surface the EO number in the timeline
    return {
        "channel": CHANNEL,
        "source_id": SOURCE_ID,
        "source_url": doc.get("html_url") or doc.get("pdf_url") or "",
        "title": title[:300],
        "summary": doc.get("abstract"),
        # EOs carry a signing_date that precedes publication; date by it so they sort
        # by when they took effect, not when FR printed them. Rules have no
        # signing_date and fall back to publication_date.
        "occurred_at": common.to_iso(doc.get("signing_date") or doc.get("publication_date")),
        "fetched_at": common.now_iso(),
        "admiralty_source": gsource,
        "admiralty_info": ginfo,
        "confidence": None,
        "bill_id": None,
        "case_id": None,
        "content_hash": common.content_hash(SOURCE_ID, docnum),
        "raw_json": json.dumps(doc, separators=(",", ":")),
    }


def collect(conn, base: str, params: dict, throttle: float,
            gsource: str, ginfo: str) -> dict:
    """Fetch a pre-built query, ingest every new document, return a counts summary.
    Shared by both query shapes -- insert_ignore on content_hash(document_number)
    dedups across shapes and runs."""
    docs = fetch_documents(base, params, throttle)
    counts = {"fetched": len(docs), "new_items": 0}
    for doc in docs:
        if not doc.get("document_number"):
            continue  # cannot form a stable dedup key
        if db.insert_ignore(conn, "items", document_item_row(doc, gsource, ginfo)):
            counts["new_items"] += 1
    return counts


def collect_term(conn, base: str, agencies: list[str], term: str, since: str | None,
                 throttle: float, gsource: str, ginfo: str) -> dict:
    """Agency-shape wrapper: collect one term across all agencies."""
    params = build_params(agencies, term, since)
    return {"term": term, **collect(conn, base, params, throttle, gsource, ginfo)}


def main() -> int:
    config.load_env()
    db.init_db()
    sources = config.load_sources()
    ex = sources["executive"]
    base = ex["api"]["base"].rstrip("/")
    agencies = ex.get("agencies", [])
    terms = ex.get("terms", [])
    since = ex.get("since") or DEFAULT_SINCE
    rate = ex["api"].get("rate_limit_per_hour")
    throttle = (3600.0 / rate) if rate else 0.0
    gsource, ginfo = config.grade(ex.get("default_grade"))
    # No config.require_env: the Federal Register API needs no key (api.key_env is null).

    conn = db.connect()
    totals = {"agency": 0, "presidential": 0}
    try:
        register_source(conn, base, gsource, ginfo)
        conn.commit()
        for term in terms:
            # Two query shapes per term: agency (rules/notices) and presidential
            # (executive orders). Each is wrapped so one bad query doesn't sink the run.
            try:
                counts = collect_term(conn, base, agencies, term, since, throttle, gsource, ginfo)
                conn.commit()
                totals["agency"] += counts["new_items"]
                print(f"  agency        {term:<22} fetched {counts['fetched']:>4}  +{counts['new_items']} items")
            except Exception as exc:
                conn.rollback()
                print(f"  agency        {term:<22} ERROR: {exc}", file=sys.stderr)

            try:
                params = build_presidential_params(term, since)
                counts = collect(conn, base, params, throttle, gsource, ginfo)
                conn.commit()
                totals["presidential"] += counts["new_items"]
                print(f"  presidential  {term:<22} fetched {counts['fetched']:>4}  +{counts['new_items']} items")
            except Exception as exc:
                conn.rollback()
                print(f"  presidential  {term:<22} ERROR: {exc}", file=sys.stderr)
        print(f"  total: agency +{totals['agency']}, presidential +{totals['presidential']}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
