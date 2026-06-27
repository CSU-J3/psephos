"""News + administrative-coercion collector — RSS feeds and Google News.

Pulls every configured RSS feed and Google News query, runs two-stage dedup, and
writes survivors to `items`. The cross-reference is the point: a surviving item
that names a movement term AND a SAVE subject term attaches to the current
vehicle bill (S. 1383) so the timeline can assemble the maneuver -- because the
legislation channel never names the payload (see docs/psephos.md and the project
notes on why S. 1383's own metadata is a decoy).

Matching is deliberately conservative; over-tagging unrelated reporting is the
failure mode. See `classify` for the exact rule.

Run from the repo root:  python -m collectors.news
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

import feedparser
import requests
from rapidfuzz import fuzz

import common
import config
import db

CHANNEL = "news"
GNEWS_SOURCE_ID = "google-news"
USER_AGENT = "psephos/0.1 (+https://github.com/CSU-J3/psephos)"
FEED_TIMEOUT = 30
LEDE_CHARS = 300  # how much of the lede feeds the content hash

_TAG_RE = re.compile(r"<[^>]+>")
_NONALNUM_RE = re.compile(r"[^a-z0-9]+")

# bill_type -> dotted label used in citations (e.g. 's' -> 's.', 'hr' -> 'h.r.')
_DOTTED = {
    "hr": "h.r.", "s": "s.", "hjres": "h.j.res.", "sjres": "s.j.res.",
    "hconres": "h.con.res.", "sconres": "s.con.res.", "hres": "h.res.", "sres": "s.res.",
}


@dataclass
class MatchCtx:
    movement_terms: list[str]           # procedural_terms + news_movement_terms (union)
    subject_terms: list[str]
    bill_numbers: dict[str, set[str]]   # bill_id -> citation forms (lowercased)
    vehicle_bill_id: str | None
    threshold: float                    # rapidfuzz token_sort_ratio, 0..1


# --------------------------------------------------------------------------- #
# Text + URL normalization
# --------------------------------------------------------------------------- #
def clean_html(text: str) -> str:
    return _TAG_RE.sub(" ", text or "").strip()


def normalize_text(text: str) -> str:
    """Lowercase, strip tags and punctuation, collapse whitespace."""
    return _NONALNUM_RE.sub(" ", clean_html(text).lower()).strip()


def canonical_url(url: str) -> str | None:
    """Strip utm_* params, fragments, and trailing slash; unwrap Google News links."""
    if not url:
        return None
    parts = urlsplit(url)
    query_pairs = parse_qsl(parts.query, keep_blank_values=True)
    # Google News RSS sometimes wraps the real article as ?url=...; unwrap it.
    if parts.netloc.endswith("news.google.com"):
        for k, v in query_pairs:
            if k == "url" and v:
                return canonical_url(v)
    kept = [(k, v) for k, v in query_pairs if not k.lower().startswith("utm_")]
    return urlunsplit((
        parts.scheme,
        parts.netloc.lower(),
        parts.path.rstrip("/"),
        urlencode(kept),
        "",  # drop fragment
    ))


def number_forms(bill_type: str, number: int) -> set[str]:
    """Citation forms for a bill, lowercased: 's3752' -> s. 3752 / s.3752 / s 3752 / s3752."""
    dotted = _DOTTED.get(bill_type.lower(), bill_type.lower())
    nodot = dotted.replace(".", "")
    return {f"{dotted} {number}", f"{dotted}{number}", f"{nodot} {number}", f"{nodot}{number}"}


def _cites(text_lower: str, forms: set[str]) -> bool:
    """True if any citation form appears as a token (not embedded in a larger word)."""
    for form in forms:
        if re.search(r"(?<![a-z0-9])" + re.escape(form) + r"(?![a-z0-9])", text_lower):
            return True
    return False


# --------------------------------------------------------------------------- #
# The matcher
# --------------------------------------------------------------------------- #
def classify(text: str, ctx: MatchCtx, source_grade: tuple[str, str]):
    """Decide bill attachment + grade for a news item.

    Returns (bill_id_or_None, (admiralty_source, admiralty_info), confidence_or_None).

    Rule (conservative -- over-tagging unrelated reporting is the failure mode):
      * A movement term MUST be present, or nothing attaches.
      * If the text cites a watchlist bill by NUMBER, attach to that specific bill
        (vehicle -> C3/low; any other bill -> its source grade). Citation wins
        because it is unambiguous, so cluster news about S. 3752 isn't mis-routed.
      * Otherwise, movement term + a SAVE subject term -> attach to the vehicle
        bill at C3/low (asserted inference; never self-promotes past C3).
      * No movement term, or no bill/subject signal -> no attach; source grade.
    """
    t = text.lower()
    if not any(m.lower() in t for m in ctx.movement_terms):
        return None, source_grade, None
    for bill_id, forms in ctx.bill_numbers.items():
        if _cites(t, forms):
            if bill_id == ctx.vehicle_bill_id:
                return bill_id, ("C", "3"), "low"
            return bill_id, source_grade, None
    if ctx.vehicle_bill_id and any(s.lower() in t for s in ctx.subject_terms):
        return ctx.vehicle_bill_id, ("C", "3"), "low"
    return None, source_grade, None


# --------------------------------------------------------------------------- #
# Dedup + persist
# --------------------------------------------------------------------------- #
def process_entry(conn, raw: dict, source_id: str, source_grade: tuple[str, str],
                  ctx: MatchCtx) -> str:
    """Two-stage dedup a single raw entry, then persist survivors.

    `raw` is a plain dict {title, link, summary, published} so this is testable
    without a live feed. Returns a short status string.
    """
    title = (raw.get("title") or "").strip()
    if not title:
        return "skip"
    link = (raw.get("link") or "").strip()
    summary = clean_html(raw.get("summary") or "")
    canon = canonical_url(link)
    title_norm = normalize_text(title)
    lede_norm = normalize_text(summary)[:LEDE_CHARS]
    chash = common.content_hash(title_norm, lede_norm)

    # Stage 1: canonical URL.
    if canon and conn.execute(
        "SELECT 1 FROM dedup_seen WHERE canonical_url = ?", (canon,)
    ).fetchone():
        return "dup_url"
    # Stage 2a: exact content hash.
    if conn.execute("SELECT 1 FROM dedup_seen WHERE content_hash = ?", (chash,)).fetchone():
        return "dup_hash"
    # Stage 2b: fuzzy title similarity against everything seen.
    cutoff = ctx.threshold * 100
    for (seen,) in conn.execute(
        "SELECT title_norm FROM dedup_seen WHERE title_norm IS NOT NULL AND title_norm != ''"
    ):
        if fuzz.token_sort_ratio(title_norm, seen) >= cutoff:
            return "dup_fuzzy"

    bill_id, (gsource, ginfo), conf = classify(f"{title} {summary}", ctx, source_grade)
    cur = conn.execute(
        "INSERT INTO items (channel, source_id, source_url, title, summary, occurred_at, "
        "fetched_at, admiralty_source, admiralty_info, confidence, bill_id, case_id, "
        "content_hash, raw_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            CHANNEL, source_id, canon or link or "", title, summary or None,
            common.to_iso(raw.get("published")), common.now_iso(),
            gsource, ginfo, conf, bill_id, None, chash,
            json.dumps(
                {"title": title, "link": link, "summary": summary,
                 "published": raw.get("published")},
                separators=(",", ":"),
            ),
        ),
    )
    conn.execute(
        "INSERT INTO dedup_seen (canonical_url, content_hash, title_norm, first_seen, item_id) "
        "VALUES (?,?,?,?,?)",
        (canon, chash, title_norm, common.now_iso(), cur.lastrowid),
    )
    return f"attached:{bill_id}" if bill_id else "new"


# --------------------------------------------------------------------------- #
# Feed fetching
# --------------------------------------------------------------------------- #
def fetch_feed(url: str) -> list[dict]:
    """Fetch and parse a feed into raw dicts; return [] on any network/parse error."""
    try:
        resp = requests.get(url, timeout=FEED_TIMEOUT, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  feed fetch failed: {url} ({exc})", file=sys.stderr)
        return []
    parsed = feedparser.parse(resp.content)
    return [
        {
            "title": e.get("title", ""),
            "link": e.get("link", ""),
            "summary": e.get("summary", e.get("description", "")),
            "published": e.get("published", e.get("updated")),
        }
        for e in parsed.entries
    ]


def gnews_url(base: str, query: str) -> str:
    return f"{base}?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"


def register_sources(conn, news_cfg: dict) -> None:
    for feed in news_cfg.get("feeds", []):
        gs, gi = config.grade(feed.get("grade"))
        db.upsert(conn, "sources", {
            "id": feed["id"], "name": feed["id"], "channel": CHANNEL, "kind": "rss",
            "url": feed.get("url"), "admiralty_source": gs, "admiralty_info": gi,
            "enabled": 1, "notes": "RSS feed.",
        }, pk="id")
    gn = news_cfg.get("google_news", {})
    gs, gi = config.grade(gn.get("grade"))
    db.upsert(conn, "sources", {
        "id": GNEWS_SOURCE_ID, "name": "Google News RSS", "channel": CHANNEL, "kind": "rss",
        "url": gn.get("base"), "admiralty_source": gs, "admiralty_info": gi,
        "enabled": 1, "notes": "Aggregated; C3 until corroborated.",
    }, pk="id")


def build_ctx(sources: dict) -> MatchCtx:
    leg = sources["legislation"]
    news = sources["news"]
    watchlist = leg.get("watchlist", [])
    # Subject vocab = config list + watchlist short_titles (deduped, order-stable).
    subject_terms = list(dict.fromkeys(
        (leg.get("subject_terms") or [])
        + [b["short_title"] for b in watchlist if b.get("short_title")]
    ))
    vehicles = [b["bill_id"] for b in watchlist if b.get("is_vehicle")]
    vehicle_bill_id = vehicles[0] if len(vehicles) == 1 else None
    if len(vehicles) != 1:
        print(
            f"  WARNING: expected exactly one is_vehicle bill, found {vehicles}; "
            f"subject-term routing to the vehicle is DISABLED.",
            file=sys.stderr,
        )
    bill_numbers = {b["bill_id"]: number_forms(b["type"], b["number"]) for b in watchlist}
    threshold = float(news.get("dedup", {}).get("near_dupe_threshold", 0.90))
    movement_terms = list(dict.fromkeys(
        (leg.get("procedural_terms") or []) + (leg.get("news_movement_terms") or [])
    ))
    return MatchCtx(
        movement_terms=movement_terms,
        subject_terms=subject_terms,
        bill_numbers=bill_numbers,
        vehicle_bill_id=vehicle_bill_id,
        threshold=threshold,
    )


def main() -> int:
    config.load_env()
    db.init_db()
    sources = config.load_sources()
    news = sources["news"]
    ctx = build_ctx(sources)

    conn = db.connect()
    try:
        register_sources(conn, news)
        conn.commit()

        tally: dict[str, int] = {}

        def run_source(source_id, grade, entries):
            gs, gi = config.grade(grade)
            for raw in entries:
                status = process_entry(conn, raw, source_id, (gs, gi), ctx)
                key = "attached" if status.startswith("attached") else status
                tally[key] = tally.get(key, 0) + 1
            conn.commit()

        for feed in news.get("feeds", []):
            run_source(feed["id"], feed.get("grade"), fetch_feed(feed["url"]))

        gn = news.get("google_news", {})
        for query in gn.get("queries", []):
            run_source(GNEWS_SOURCE_ID, gn.get("grade"), fetch_feed(gnews_url(gn["base"], query)))

        attached = conn.execute(
            "SELECT bill_id, COUNT(*) n FROM items WHERE channel='news' AND bill_id IS NOT NULL "
            "GROUP BY bill_id"
        ).fetchall()
        print("  news run:", {k: tally[k] for k in sorted(tally)})
        print("  attached:", {r["bill_id"]: r["n"] for r in attached} or "none")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
