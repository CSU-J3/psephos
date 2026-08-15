"""Collapse the news pairs the ` - Publisher` suffix let through dedup.

THE DEFECT, for anyone reading this after the fact. Google News appends
` - Publisher` to every headline. `process_entry` hashed and fuzzy-compared the
RAW title, so the same article arriving from an outlet's own RSS feed and from
Google News differed by two or three tokens -- enough to hold token_sort_ratio
under the 0.90 cutoff -- and landed as two rows, one graded B2 (the outlet's
pipe) and one C3 (the aggregator's). Measured 2026-08-15: 30 such pairs.

`collectors/news.py` now strips the suffix before hashing, so no NEW pair can
form. This clears the ones already stored. It is one-time: after a successful
apply, do not schedule it.

WHICH ROW DIES. The aggregator's copy. The outlet's own feed carries the bare
headline, the real article URL rather than a `news.google.com/rss/articles/...`
redirect, and the grade the spec actually intends for that outlet. Nothing in the
C3 copy is evidence the B2 copy lacks.

THIS DELETES ROWS. Dry-run by default; read the pairs it prints before `--apply`.
`dedup_seen` rows referencing a deleted item go with it, or the next run's stage-1
and stage-2a lookups would still match a link to nothing.

Run:  python -m scripts.dedupe_suffixed_news            # dry run
      python -m scripts.dedupe_suffixed_news --apply
"""
from __future__ import annotations

import sys

from rapidfuzz import fuzz

import config
import db
from collectors.news import normalize_text, strip_outlet_suffix

# The cutoff `process_entry` itself uses, read from config rather than restated,
# so this script cannot drift from the collector it is cleaning up after.
GNEWS = "google-news"


def _key(value: str | None) -> str:
    """`Democracy Docket`, `democracydocket.com`, `democracy-docket` -> comparable."""
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def _same_outlet(outlet: str | None, source_id: str) -> bool:
    """Does this outlet name refer to the feed `source_id` carries?

    PREFIX, NOT EQUALITY, and the difference is 22 rows. One outlet writes its own
    name at least three ways across the corpus -- `Democracy Docket` (106),
    `democracydocket.com` (20) -- and States United arrives as `States United
    Democracy Center` against a `states-united` feed id. An equality test silently
    drops every variant, which is exactly how the first pass at measuring this
    cohort undercounted it by 20."""
    k, f = _key(outlet), _key(source_id)
    return bool(k) and bool(f) and k.startswith(f)


def find_pairs(conn, threshold: float) -> list[dict]:
    """Aggregator rows that duplicate a non-aggregator row of the SAME PUBLISHER.

    THE PUBLISHER CONSTRAINT IS NOT OPTIONAL, and the dry run is what showed it.
    Matching on headline alone found 54 pairs, and reading them turned up at least
    one that is not a duplicate at all: `DOJ threatens ARIZONA election officials
    with prosecution...` scored 92 against Democracy Docket's `Trump DOJ threatens
    election officials with criminal prosecution...` -- similar headlines, different
    stories, and a delete would have destroyed a row psephos holds nothing else of.
    Two articles are the same article only if the same outlet published both, and
    `items.outlet` is exactly the field that says so. Fuzzy similarity picks the
    candidate; the publisher decides."""
    direct = conn.execute(
        "SELECT id, title, source_id FROM items "
        "WHERE channel = 'news' AND source_id != ?", (GNEWS,)
    ).fetchall()
    direct_norm = [(r["id"], r["source_id"], r["title"], normalize_text(r["title"]))
                   for r in direct]

    out = []
    rows = conn.execute(
        "SELECT id, title, outlet FROM items WHERE channel = 'news' AND source_id = ?",
        (GNEWS,)
    ).fetchall()
    for r in rows:
        if not _key(r["outlet"]):
            continue
        norm = normalize_text(strip_outlet_suffix(r["title"]))
        # Candidates restricted to the same publisher's own feed BEFORE scoring.
        same_outlet = [(did, dsid, dt, dn) for did, dsid, dt, dn in direct_norm
                       if _same_outlet(r["outlet"], dsid)]
        best = max(((fuzz.token_sort_ratio(norm, dn), did, dsid, dt)
                    for did, dsid, dt, dn in same_outlet), default=(0, None, None, ""))
        if best[0] >= threshold * 100:
            out.append({"gn_id": r["id"], "gn_title": r["title"], "outlet": r["outlet"],
                        "score": best[0], "keep_id": best[1], "keep_source": best[2],
                        "keep_title": best[3]})
    return out


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    apply = "--apply" in argv

    config.load_env()
    sources = config.load_sources()
    threshold = float(sources["news"].get("dedup", {}).get("title_similarity", 0.90))

    conn = db.connect()
    try:
        db.require_remote(conn, "the suffixed-news cleanup")
        pairs = find_pairs(conn, threshold)
        print(f"  threshold: {threshold} (from config, the collector's own cutoff)")
        print(f"  duplicate pairs found: {len(pairs)}")
        for p in pairs:
            print(f"    [{p['score']:.0f}] delete #{p['gn_id']} «{p['gn_title'][:72]}»")
            print(f"           keep #{p['keep_id']} ({p['keep_source']}) «{p['keep_title'][:66]}»")

        if not apply:
            print("  DRY-RUN -- nothing deleted. Read the pairs above, then --apply.")
            return 0

        ids = [p["gn_id"] for p in pairs]
        for i in range(0, len(ids), 200):
            chunk = ids[i:i + 200]
            marks = ",".join("?" * len(chunk))
            # dedup_seen first: it references items(id), and leaving the row behind
            # would keep a stage-1/2a hit pointing at a deleted item.
            conn.execute(f"DELETE FROM dedup_seen WHERE item_id IN ({marks})", tuple(chunk))
            conn.execute(f"DELETE FROM items WHERE id IN ({marks})", tuple(chunk))
        conn.commit()
        print(f"  APPLIED -- deleted {len(ids)} aggregator duplicates.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
