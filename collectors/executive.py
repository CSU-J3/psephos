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
# Explicit field projection keeps raw_json small and the response stable.
FIELDS = [
    "document_number",
    "title",
    "abstract",
    "type",
    "publication_date",
    "html_url",
    "pdf_url",
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
    """First-page query dict. `requests` repeats list values, which is exactly FR's
    bracket-array convention: agencies -> conditions[agencies][] (OR'd), fields[]."""
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


def fetch_documents(base: str, agencies: list[str], term: str,
                    since: str | None, throttle: float) -> list[dict]:
    """All documents for one term across all agencies. Follows next_page_url, which
    is an absolute, self-contained URL carrying the full query string."""
    url = f"{base}{DOCS_PATH}"
    params: dict | None = build_params(agencies, term, since)
    out: list[dict] = []
    while True:
        data = common.http_get(url, params=params, throttle=throttle)
        out.extend(data.get("results") or [])
        nxt = data.get("next_page_url")
        if not nxt:
            break
        url, params = nxt, None  # next_page_url already encodes the query
    return out


def document_item_row(doc: dict, gsource: str, ginfo: str) -> dict:
    """Map a Federal Register document to an `items` row. content_hash is keyed on
    the document_number so the same doc never lands twice (across terms or runs)."""
    docnum = doc.get("document_number")
    return {
        "channel": CHANNEL,
        "source_id": SOURCE_ID,
        "source_url": doc.get("html_url") or doc.get("pdf_url") or "",
        "title": (doc.get("title") or f"(untitled Federal Register document {docnum})")[:300],
        "summary": doc.get("abstract"),
        "occurred_at": common.to_iso(doc.get("publication_date")),
        "fetched_at": common.now_iso(),
        "admiralty_source": gsource,
        "admiralty_info": ginfo,
        "confidence": None,
        "bill_id": None,
        "case_id": None,
        "content_hash": common.content_hash(SOURCE_ID, docnum),
        "raw_json": json.dumps(doc, separators=(",", ":")),
    }


def collect_term(conn, base: str, agencies: list[str], term: str, since: str | None,
                 throttle: float, gsource: str, ginfo: str) -> dict:
    """Collect one term across all agencies. Returns a per-term counts summary."""
    docs = fetch_documents(base, agencies, term, since, throttle)
    counts = {"term": term, "fetched": len(docs), "new_items": 0}
    for doc in docs:
        if not doc.get("document_number"):
            continue  # cannot form a stable dedup key
        if db.insert_ignore(conn, "items", document_item_row(doc, gsource, ginfo)):
            counts["new_items"] += 1
    return counts


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
    try:
        register_source(conn, base, gsource, ginfo)
        conn.commit()
        for term in terms:
            try:
                counts = collect_term(conn, base, agencies, term, since, throttle, gsource, ginfo)
                conn.commit()
                print(f"  {term:<22} fetched {counts['fetched']:>4}  +{counts['new_items']} items")
            except Exception as exc:  # one bad term shouldn't sink the run
                conn.rollback()
                print(f"  {term:<22} ERROR: {exc}", file=sys.stderr)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
