"""Acceptance + negative suite for the news matcher (collectors/news.py).

Deterministic and offline: builds a temp DB, loads synthetic feed entries from
tests/fixtures/news_entries.json, and drives the real process_entry/classify
pipeline. No network, and it does not touch data/psephos.db.

Run:  pytest tests/test_news.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.chdir(REPO)  # config.load_sources / db.init_db use repo-relative paths

import config  # noqa: E402
import db  # noqa: E402
from collectors import news  # noqa: E402

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "news_entries.json").read_text("utf-8"))


def _env():
    """Fresh temp DB + ctx + seeded bills (so items.bill_id FK is satisfied)."""
    sources = config.load_sources()
    ctx = news.build_ctx(sources)
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    db.init_db(path)
    conn = db.connect(path)
    news.register_sources(conn, sources["news"])
    for b in sources["legislation"]["watchlist"]:
        db.upsert(conn, "bills", {
            "bill_id": b["bill_id"], "congress": b["congress"],
            "bill_type": b["type"], "number": b["number"],
        }, pk="bill_id")
    conn.commit()
    gn_grade = config.grade(sources["news"]["google_news"]["grade"])
    return conn, ctx, gn_grade


def _row(conn, like):
    return conn.execute(
        "SELECT * FROM items WHERE title LIKE ? ORDER BY id DESC LIMIT 1", (f"%{like}%",)
    ).fetchone()


def _entry(title, link, summary="", **extra):
    return {"title": title, "link": link, "summary": summary,
            "published": "2026-06-01T00:00:00Z", **extra}


def _count(conn, like):
    return conn.execute(
        "SELECT COUNT(*) AS n FROM items WHERE title LIKE ?", (f"%{like}%",)
    ).fetchone()["n"]


class _CountingConn:
    """Proxy that counts executions of one SQL fragment and delegates everything
    else to the real connection -- the standing alarm for the hoisted stage-2b
    scan (assert it runs once, not once per entry)."""

    def __init__(self, inner, needle):
        self._inner = inner
        self._needle = needle
        self.count = 0

    def execute(self, sql, params=()):
        if self._needle in sql:
            self.count += 1
        return self._inner.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def test_pure_helpers():
    assert news.canonical_url("https://x.org/a?utm_source=t&keep=1#frag") == "https://x.org/a?keep=1"
    assert news.canonical_url("https://x.org/a/") == "https://x.org/a"
    assert news._cites("the bill s. 128 stalled", news.number_forms("s", 128))
    assert not news._cites("a class 128 locomotive", news.number_forms("s", 128))


def test_acceptance_and_pipeline():
    conn, ctx, gn = _env()
    seen = news.load_seen_titles(conn)  # run's fuzzy-dedup cache, threaded through every call

    # 1) ACCEPTANCE: Feb 11 218-213, procedural + subject (+ cites S.1383) -> vehicle at C3/low
    assert news.process_entry(conn, FIXTURES["acceptance"], "google-news", gn, ctx, seen) == "attached:s1383-119"
    row = _row(conn, "House adopts proof-of-citizenship")
    assert row["bill_id"] == "s1383-119"
    assert (row["admiralty_source"], row["admiralty_info"]) == ("C", "3")
    assert row["confidence"] == "low"
    assert row["source_url"] == "https://example.org/save-vote"  # utm + fragment stripped

    # 2) DEDUP stage 1: same canonical URL
    assert news.process_entry(conn, FIXTURES["dup_url"], "google-news", gn, ctx, seen) == "dup_url"

    # 3) DEDUP stage 2b: different URL, near-identical title (folded via the in-memory cache)
    assert news.process_entry(conn, FIXTURES["dup_fuzzy"], "google-news", gn, ctx, seen) == "dup_fuzzy"

    # 4) OVER-TAG NEGATIVE: loose terms only -> no attach, source grade kept
    assert news.process_entry(conn, FIXTURES["overtag"], "google-news", gn, ctx, seen) == "new"
    row = _row(conn, "election integrity and voter fraud")
    assert row["bill_id"] is None
    assert (row["admiralty_source"], row["admiralty_info"]) == ("C", "3")

    # 5) SUBJECT-ONLY (no movement term) -> no attach
    news.process_entry(conn, FIXTURES["subject_only"], "google-news", gn, ctx, seen)
    assert _row(conn, "Senate to consider the SAVE America Act")["bill_id"] is None

    # 6) BILL-NUMBER DISAMBIGUATION: S. 3752 + cloture from a B2 tracker -> s3752 at SOURCE grade
    assert news.process_entry(conn, FIXTURES["disambiguation"], "votebeat", ("B", "2"), ctx, seen) == "attached:s3752-119"
    row = _row(conn, "S. 3752 faces a cloture vote")
    assert (row["admiralty_source"], row["admiralty_info"]) == ("B", "2")

    # 7) SUBJECT INFERENCE (no bill number): movement + subject -> vehicle at C3
    assert news.process_entry(conn, FIXTURES["inference"], "google-news", gn, ctx, seen) == "attached:s1383-119"
    assert (_row(conn, "Discharge petition filed over documentary proof")["admiralty_source"]) == "C"

    # 7b) NEWS-REGISTER movement word ("passed") + subject -> vehicle at C3
    assert news.process_entry(conn, FIXTURES["news_register"], "google-news", gn, ctx, seen) == "attached:s1383-119"
    row = _row(conn, "House passed sweeping proof-of-citizenship")
    assert (row["admiralty_source"], row["admiralty_info"]) == ("C", "3")

    # 7c) NEGATIVE: subject + a non-movement word ("debate") -> no attach
    news.process_entry(conn, FIXTURES["negative_nonmovement"], "google-news", gn, ctx, seen)
    assert _row(conn, "Lawmakers debate the SAVE America Act")["bill_id"] is None

    conn.close()


def _grade_dict():
    """The raw {source, info} grade dict run_source parses via config.grade -- what
    process_source/run_source expect (process_entry takes the parsed tuple)."""
    return config.load_sources()["news"]["google_news"]["grade"]


def test_stage2b_scan_runs_once_regardless_of_entry_count():
    # The perf claim, promoted to a standing alarm: the fuzzy-dedup title scan runs
    # exactly ONCE per run (load_seen_titles), never per entry. Reintroducing the
    # per-entry scan inside process_entry makes count jump to 1+N and fails here.
    conn, ctx, gn = _env()
    counter = _CountingConn(conn, "SELECT title_norm FROM dedup_seen")
    seen = news.load_seen_titles(counter)          # the one and only scan
    for i in range(25):
        news.process_entry(counter, _entry(f"Distinct weather headline number {i}",
                                           f"https://ex.org/w{i}"), "google-news", gn, ctx, seen)
    assert counter.count == 1
    conn.close()


def test_source_isolation_middle_source_fails():
    # Three sources, the middle one raises on every entry: 1 and 3 both land, the
    # failure is reported (not raised), so main() would still reach export.
    conn, ctx, gn = _env()
    graw = _grade_dict()
    seen, tally = news.load_seen_titles(conn), {}

    real_pe = news.process_entry

    def flaky(conn_, raw, sid, grade, ctx_, seen_):
        if raw.get("boom"):
            raise RuntimeError("Hrana: stream not found")
        return real_pe(conn_, raw, sid, grade, ctx_, seen_)

    news.process_entry = flaky
    try:
        e1 = news.process_source(conn, "google-news", graw,
                                 [_entry("First source lands a real story on voter rolls", "https://ex.org/s1")],
                                 ctx, seen, tally)
        e2 = news.process_source(conn, "google-news", graw,
                                 [_entry("doomed", "https://ex.org/boom", boom=True)],
                                 ctx, seen, tally)
        e3 = news.process_source(conn, "votebeat", graw,
                                 [_entry("Third source lands a distinct story on redistricting maps", "https://ex.org/s3")],
                                 ctx, seen, tally)
    finally:
        news.process_entry = real_pe

    assert e1 is None and e3 is None          # good sources succeeded
    assert e2 is not None                     # middle failed twice -> reported, not raised
    assert tally.get("source_errors") == 1
    assert _count(conn, "First source lands a real story") == 1
    assert _count(conn, "Third source lands a distinct story") == 1
    conn.close()


def test_source_retry_once_then_succeeds():
    # A source that raises on its first attempt and succeeds on the second lands its
    # entries -- and the retry re-runs the SAME already-fetched entry (no re-fetch).
    conn, ctx, gn = _env()
    graw = _grade_dict()
    seen, tally = news.load_seen_titles(conn), {}
    n = {"i": 0}
    real_pe = news.process_entry

    def flaky(conn_, raw, sid, grade, ctx_, seen_):
        if raw.get("flaky"):
            n["i"] += 1
            if n["i"] == 1:
                raise RuntimeError("Hrana: stream not found")
        return real_pe(conn_, raw, sid, grade, ctx_, seen_)

    news.process_entry = flaky
    try:
        err = news.process_source(conn, "google-news", graw,
                                  [_entry("Retryable source recovers with a story on mail ballots",
                                          "https://ex.org/r1", flaky=True)],
                                  ctx, seen, tally)
    finally:
        news.process_entry = real_pe

    assert err is None                        # succeeded on the retry
    assert n["i"] == 2                         # failed once, re-ran the same entry once
    assert _count(conn, "Retryable source recovers") == 1
    conn.close()


def test_cache_truncated_on_failure_so_retry_writes_own_entries():
    # THE regression that matters most. One source, two entries: A (real, unique) is
    # processed and its title appended to the in-memory cache, THEN B raises. The fix
    # truncates the cache back and rolls back, so on retry A is neither in the DB nor
    # in the cache and is written -- not dropped as a fuzzy duplicate of its own
    # cached title. Without the truncation, A would be lost (count 0).
    conn, ctx, gn = _env()
    graw = _grade_dict()
    seen, tally = news.load_seen_titles(conn), {}
    A = _entry("Alpha story about voter registration deadlines statewide", "https://ex.org/A")
    B = _entry("Beta story about early voting hours downtown", "https://ex.org/B", boomonce=True)
    n = {"i": 0}
    real_pe = news.process_entry

    def flaky(conn_, raw, sid, grade, ctx_, seen_):
        if raw.get("boomonce"):
            n["i"] += 1
            if n["i"] == 1:
                raise RuntimeError("Hrana: stream not found")
        return real_pe(conn_, raw, sid, grade, ctx_, seen_)

    news.process_entry = flaky
    try:
        err = news.process_source(conn, "google-news", graw, [A, B], ctx, seen, tally)
    finally:
        news.process_entry = real_pe

    assert err is None
    assert _count(conn, "Alpha story about voter registration") == 1   # written on the retry, not self-deduped
    assert _count(conn, "Beta story about early voting") == 1
    conn.close()


def test_db_reset_swaps_connection_and_clears_pending():
    import sqlite3

    reopened = {"n": 0}

    def reopen():
        reopened["n"] += 1
        return sqlite3.connect(":memory:")

    c = db._Conn(sqlite3.connect(":memory:"), reopen=reopen)
    c.execute("CREATE TABLE t (x)")
    assert c._pending is True
    first_raw = c._raw
    c.reset()
    assert c._pending is False
    assert reopened["n"] == 1
    assert c._raw is not first_raw                 # rebuilt via _reopen

    # _reopen None (local SQLite / tests): clears _pending, no swap.
    c2 = db._Conn(sqlite3.connect(":memory:"), reopen=None)
    c2.execute("CREATE TABLE t (x)")
    assert c2._pending is True
    raw2 = c2._raw
    c2.reset()
    assert c2._pending is False
    assert c2._raw is raw2                          # no-op


if __name__ == "__main__":
    test_pure_helpers()
    test_acceptance_and_pipeline()
    test_stage2b_scan_runs_once_regardless_of_entry_count()
    test_source_isolation_middle_source_fails()
    test_source_retry_once_then_succeeds()
    test_cache_truncated_on_failure_so_retry_writes_own_entries()
    test_db_reset_swaps_connection_and_clears_pending()
    print("ok")


# --------------------------------------------------------------------------- #
# The outlet is a stored fact (handoff 82, Part A)
#
# `source_id` is the DELIVERY PIPE, not the publisher: one aggregator carries
# hundreds of outlets. The spec grades outlets, so storing only the pipe answers
# the wrong question -- which is how the same journalism ended up B2 or C3 by
# which feed carried it. fetch_feed used to drop the feed's own <source> element,
# leaving the title suffix as the only signal.
# --------------------------------------------------------------------------- #
def test_outlet_from_title_takes_the_last_separator():
    """A headline can contain its own ' - '. The four `Court Cases - <name> -
    Democracy Docket` items in the live corpus parse correctly only this way."""
    assert news.outlet_from_title("Headline here - Votebeat") == "Votebeat"
    assert news.outlet_from_title(
        "Court Cases - Idaho DOJ Voter Data Access Challenge - Democracy Docket"
    ) == "Democracy Docket"


def test_outlet_from_title_is_none_when_there_is_no_suffix():
    """Plain RSS titles carry no publisher suffix, and inventing one from a
    hyphenated headline would be worse than leaving the column NULL."""
    assert news.outlet_from_title("No separator at all") is None
    assert news.outlet_from_title("") is None
    assert news.outlet_from_title("Trailing separator - ") is None


def test_outlet_parse_survives_an_outlet_renaming_itself_only_by_luck():
    """Two live items arrive as `votebeat.org` rather than `Votebeat`. The parse
    returns what the feed said -- it is not the parser's job to canonicalise -- so
    any promotion rule keyed on this must match aliases, not exact names."""
    assert news.outlet_from_title("Some headline - votebeat.org") == "votebeat.org"


def test_fetch_feed_keeps_the_structured_source_element(monkeypatch):
    """The authoritative field. It was being parsed and thrown away on every item,
    which is what left the title suffix as the only signal in the first place."""
    class _Resp:
        content = b"<rss/>"
        def raise_for_status(self): pass

    class _Parsed:
        entries = [
            {"title": "A headline - Votebeat", "link": "https://x/1",
             "summary": "s", "published": "2026-08-01",
             "source": {"title": "Votebeat", "href": "https://votebeat.org"}},
            {"title": "Plain RSS item", "link": "https://y/2",
             "summary": "s", "published": "2026-08-01"},          # no <source>
        ]

    monkeypatch.setattr(news.requests, "get", lambda *a, **k: _Resp())
    monkeypatch.setattr(news.feedparser, "parse", lambda _c: _Parsed())
    got = news.fetch_feed("https://feed")
    assert got[0]["outlet"] == "Votebeat"
    assert got[1]["outlet"] is None       # plain RSS: source_id already names it


def test_process_entry_stores_the_outlet_preferring_the_structured_field(tmp_path):
    """Structured beats parsed when both exist, and the parse fills in when it
    does not -- which is the whole backfill story in one row."""
    conn, ctx, gn_grade = _env()
    news.process_entry(conn, _entry("Headline one - Some Wire", "https://a/1",
                                    outlet="Votebeat"),
                       "google-news", gn_grade, ctx, [])
    news.process_entry(conn, _entry("Headline two - Democracy Docket", "https://a/2"),
                       "google-news", gn_grade, ctx, [])
    got = {r["title"]: r["outlet"] for r in
           conn.execute("SELECT title, outlet FROM items").fetchall()}
    assert got["Headline one - Some Wire"] == "Votebeat"        # structured wins
    assert got["Headline two - Democracy Docket"] == "Democracy Docket"   # parsed
    conn.close()


# --------------------------------------------------------------------------- #
# The suffix defeated fuzzy dedup (handoff 82, Part B)
#
# Google News appends ` - Publisher`, inflating the title by two or three tokens
# -- enough to hold token_sort_ratio under the 0.90 cutoff, so the same article
# from an outlet's own feed and from Google News did not collapse. 30 such pairs
# were sitting in the database when this was measured, one B2 and one C3.
# --------------------------------------------------------------------------- #
def test_strip_outlet_suffix_leaves_the_headline():
    assert news.strip_outlet_suffix("A headline - Votebeat") == "A headline"
    assert news.strip_outlet_suffix("No suffix here") == "No suffix here"
    # The stored title is NOT rewritten; only the dedup key is computed from this.
    assert news.strip_outlet_suffix("Court Cases - Idaho Thing - Democracy Docket") \
        == "Court Cases - Idaho Thing"


def test_the_same_article_collapses_across_the_two_pipes():
    """THE DEFECT. The outlet's own feed carries the bare headline; Google News
    carries it with a publisher tag. Before this they were two rows."""
    conn, ctx, gn_grade = _env()
    seen: list[str] = []
    headline = ("Trump DOJ loses again, now 0 for 5 on voter roll cases, as court "
                "rejects Rhode Island lawsuit")
    a = news.process_entry(conn, _entry(headline, "https://democracydocket.com/x", "same lede"),
                           "democracy-docket", ("B", "2"), ctx, seen)
    b = news.process_entry(conn, _entry(f"{headline} - Democracy Docket",
                                        "https://news.google.com/rss/articles/CBMi123",
                                        "same lede"),
                           "google-news", gn_grade, ctx, seen)
    assert a == "new"
    # Stage 2a, not 2b: with the suffix stripped the two hash IDENTICALLY, so the
    # collapse happens at the cheap exact-match stage and never reaches the fuzzy
    # scan. Before Part B this was a second row.
    assert b == "dup_hash"
    assert _count(conn, "Rhode Island") == 1

    # The realistic shape too: the two pipes rarely carry the same lede, so the
    # hashes differ and the fuzzy stage is what has to catch it. That is the path
    # the suffix was actually defeating.
    c = news.process_entry(conn, _entry("Court blocks USPS from implementing the order",
                                        "https://democracydocket.com/y", "lede from the feed"),
                           "democracy-docket", ("B", "2"), ctx, seen)
    d = news.process_entry(conn, _entry("Court blocks USPS from implementing the order"
                                        " - Democracy Docket",
                                        "https://news.google.com/rss/articles/CBMi456",
                                        "a different lede entirely"),
                           "google-news", gn_grade, ctx, seen)
    assert c == "new" and d == "dup_fuzzy"
    assert _count(conn, "Court blocks USPS") == 1
    conn.close()


def test_a_plain_rss_headline_ending_in_a_dash_phrase_is_not_truncated():
    """The stripping is scoped to the aggregator on purpose. `- explained` is not a
    publisher, and truncating it would collapse two genuinely different articles
    that happen to share a prefix."""
    conn, ctx, gn_grade = _env()
    seen: list[str] = []
    news.process_entry(conn, _entry("Voter roll purges - explained", "https://votebeat.org/1"),
                       "votebeat", ("B", "2"), ctx, seen)
    r = news.process_entry(conn, _entry("Voter roll purges - what comes next",
                                        "https://votebeat.org/2"),
                           "votebeat", ("B", "2"), ctx, seen)
    assert r == "new"                              # not folded into the first
    assert _count(conn, "Voter roll purges") == 2
    conn.close()
