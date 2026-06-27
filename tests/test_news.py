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


def test_pure_helpers():
    assert news.canonical_url("https://x.org/a?utm_source=t&keep=1#frag") == "https://x.org/a?keep=1"
    assert news.canonical_url("https://x.org/a/") == "https://x.org/a"
    assert news._cites("the bill s. 128 stalled", news.number_forms("s", 128))
    assert not news._cites("a class 128 locomotive", news.number_forms("s", 128))


def test_acceptance_and_pipeline():
    conn, ctx, gn = _env()

    # 1) ACCEPTANCE: Feb 11 218-213, procedural + subject (+ cites S.1383) -> vehicle at C3/low
    assert news.process_entry(conn, FIXTURES["acceptance"], "google-news", gn, ctx) == "attached:s1383-119"
    row = _row(conn, "House adopts proof-of-citizenship")
    assert row["bill_id"] == "s1383-119"
    assert (row["admiralty_source"], row["admiralty_info"]) == ("C", "3")
    assert row["confidence"] == "low"
    assert row["source_url"] == "https://example.org/save-vote"  # utm + fragment stripped

    # 2) DEDUP stage 1: same canonical URL
    assert news.process_entry(conn, FIXTURES["dup_url"], "google-news", gn, ctx) == "dup_url"

    # 3) DEDUP stage 2b: different URL, near-identical title
    assert news.process_entry(conn, FIXTURES["dup_fuzzy"], "google-news", gn, ctx) == "dup_fuzzy"

    # 4) OVER-TAG NEGATIVE: loose terms only -> no attach, source grade kept
    assert news.process_entry(conn, FIXTURES["overtag"], "google-news", gn, ctx) == "new"
    row = _row(conn, "election integrity and voter fraud")
    assert row["bill_id"] is None
    assert (row["admiralty_source"], row["admiralty_info"]) == ("C", "3")

    # 5) SUBJECT-ONLY (no movement term) -> no attach
    news.process_entry(conn, FIXTURES["subject_only"], "google-news", gn, ctx)
    assert _row(conn, "Senate to consider the SAVE America Act")["bill_id"] is None

    # 6) BILL-NUMBER DISAMBIGUATION: S. 3752 + cloture from a B2 tracker -> s3752 at SOURCE grade
    assert news.process_entry(conn, FIXTURES["disambiguation"], "votebeat", ("B", "2"), ctx) == "attached:s3752-119"
    row = _row(conn, "S. 3752 faces a cloture vote")
    assert (row["admiralty_source"], row["admiralty_info"]) == ("B", "2")

    # 7) SUBJECT INFERENCE (no bill number): movement + subject -> vehicle at C3
    assert news.process_entry(conn, FIXTURES["inference"], "google-news", gn, ctx) == "attached:s1383-119"
    assert (_row(conn, "Discharge petition filed over documentary proof")["admiralty_source"]) == "C"

    # 7b) NEWS-REGISTER movement word ("passed") + subject -> vehicle at C3
    assert news.process_entry(conn, FIXTURES["news_register"], "google-news", gn, ctx) == "attached:s1383-119"
    row = _row(conn, "House passed sweeping proof-of-citizenship")
    assert (row["admiralty_source"], row["admiralty_info"]) == ("C", "3")

    # 7c) NEGATIVE: subject + a non-movement word ("debate") -> no attach
    news.process_entry(conn, FIXTURES["negative_nonmovement"], "google-news", gn, ctx)
    assert _row(conn, "Lawmakers debate the SAVE America Act")["bill_id"] is None

    conn.close()


if __name__ == "__main__":
    test_pure_helpers()
    test_acceptance_and_pipeline()
    print("ok")
