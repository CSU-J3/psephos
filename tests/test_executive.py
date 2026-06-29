"""Suite for the executive collector (collectors/executive.py).

Deterministic and offline: builds a temp SQLite DB and monkeypatches
common.http_get with canned Federal Register-shaped pages, then drives the real
build_params / document_item_row / collect_term pipeline. No network, and it does
not touch data/psephos.db.

Run:  pytest tests/test_executive.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from contextlib import contextmanager

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)  # config / db use repo-relative paths

import common  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
from collectors import executive  # noqa: E402

BASE = "https://www.federalregister.gov/api/v1"
AGENCIES = ["justice-department", "homeland-security-department"]
SINCE = "2025-01-01"


def _doc(docnum, title="A voter-roll rule", abstract="abstract text",
         pubdate="2026-02-01", type_="Rule"):
    return {
        "document_number": docnum,
        "title": title,
        "abstract": abstract,
        "type": type_,
        "publication_date": pubdate,
        "html_url": f"https://www.federalregister.gov/d/{docnum}",
        "pdf_url": f"https://example.gov/{docnum}.pdf",
        "agencies": [{"slug": "justice-department"}],
        "action": "Final rule.",
    }


def _pages(*doc_lists):
    """Build FR-shaped pages from one list of docs per page, chaining next_page_url
    via a sentinel the fake recognizes on follow-up calls."""
    pages = []
    for i, docs in enumerate(doc_lists):
        nxt = f"PAGE::{i + 1}" if i + 1 < len(doc_lists) else None
        pages.append({"count": 0, "total_pages": len(doc_lists),
                      "next_page_url": nxt, "results": docs})
    # Rewrite sentinels to include the term at fake-build time (done in _fake).
    return pages


@contextmanager
def _patched(pages_by_term, raise_on=None):
    """Patch common.http_get with a fake dispatching on conditions[term] (first
    page) and on the PAGE::<term>::<idx> sentinel (follow-ups)."""
    # Bake the term into each page's next_page_url sentinel.
    baked = {}
    for term, pages in pages_by_term.items():
        bp = []
        for i, p in enumerate(pages):
            p = dict(p)
            if p["next_page_url"]:
                p["next_page_url"] = f"PAGE::{term}::{i + 1}"
            bp.append(p)
        baked[term] = bp

    def fake(url, params=None, headers=None, timeout=common.DEFAULT_TIMEOUT, throttle=0.0):
        if params is not None:
            term = params["conditions[term]"]
            if raise_on is not None and term == raise_on:
                raise RuntimeError("simulated FR failure")
            return baked[term][0]
        _, term, idx = url.split("::")
        return baked[term][int(idx)]

    orig = common.http_get
    common.http_get = fake
    try:
        yield
    finally:
        common.http_get = orig


def _env():
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    db.init_db(path)
    conn = db.connect(path)
    executive.register_source(conn, BASE, "A", "1")
    conn.commit()
    return conn


def _count(conn, where="1=1", params=()):
    return conn.execute(f"SELECT COUNT(*) AS n FROM items WHERE {where}", params).fetchone()["n"]


# --- pure helpers (no DB, no network) ---------------------------------------

def test_build_params():
    p = executive.build_params(AGENCIES, "voter roll", SINCE)
    assert p["conditions[term]"] == "voter roll"
    assert p["conditions[agencies][]"] == AGENCIES        # list -> repeated -> OR
    assert p["conditions[publication_date][gte]"] == SINCE
    assert p["per_page"] == executive.PER_PAGE
    assert p["order"] == "newest"
    assert p["fields[]"] == executive.FIELDS
    # No floor -> no publication_date condition.
    assert "conditions[publication_date][gte]" not in executive.build_params(AGENCIES, "x", None)


def test_document_item_row():
    row = executive.document_item_row(_doc("2026-12345"), "A", "1")
    assert row["channel"] == "executive"
    assert row["source_id"] == "federal-register"
    assert (row["admiralty_source"], row["admiralty_info"]) == ("A", "1")
    assert row["bill_id"] is None and row["case_id"] is None
    assert row["source_url"] == "https://www.federalregister.gov/d/2026-12345"  # html_url wins
    assert row["summary"] == "abstract text"
    assert row["occurred_at"].startswith("2026-02-01")  # date-only -> ISO midnight
    assert row["content_hash"] == common.content_hash("federal-register", "2026-12345")

    # Title fallback fires when the FR title is missing/empty (items.title is NOT NULL).
    fb = executive.document_item_row(_doc("2026-99999", title=""), "A", "1")
    assert fb["title"].startswith("(untitled Federal Register document 2026-99999")


# --- pipeline (temp DB + faked FR) ------------------------------------------

def test_pagination():
    conn = _env()
    pages = _pages([_doc("d1"), _doc("d2")], [_doc("d3")])  # 2 pages -> 3 docs
    with _patched({"voter roll": pages}):
        counts = executive.collect_term(conn, BASE, AGENCIES, "voter roll", SINCE, 0.0, "A", "1")
    assert counts == {"term": "voter roll", "fetched": 3, "new_items": 3}
    assert _count(conn) == 3
    conn.close()


def test_cross_term_dedup():
    conn = _env()
    shared = _doc("shared-1")
    by_term = {
        "election": _pages([shared, _doc("e-only")]),
        "voter roll": _pages([shared, _doc("v-only")]),  # 'shared' appears under both terms
    }
    with _patched(by_term):
        c1 = executive.collect_term(conn, BASE, AGENCIES, "election", SINCE, 0.0, "A", "1")
        c2 = executive.collect_term(conn, BASE, AGENCIES, "voter roll", SINCE, 0.0, "A", "1")
    assert c1["new_items"] == 2
    assert c2["new_items"] == 1                       # 'shared' already seen, not re-counted
    assert _count(conn) == 3                          # 3 distinct documents total
    assert _count(conn, "content_hash = ?", (common.content_hash("federal-register", "shared-1"),)) == 1
    conn.close()


def test_idempotency_across_runs():
    conn = _env()
    by_term = {"election": _pages([_doc("d1"), _doc("d2")])}
    with _patched(by_term):
        first = executive.collect_term(conn, BASE, AGENCIES, "election", SINCE, 0.0, "A", "1")
        second = executive.collect_term(conn, BASE, AGENCIES, "election", SINCE, 0.0, "A", "1")
    assert first["new_items"] == 2
    assert second["new_items"] == 0
    assert _count(conn) == 2
    conn.close()


def test_persisted_mapping():
    conn = _env()
    with _patched({"election": _pages([_doc("d1")])}):
        executive.collect_term(conn, BASE, AGENCIES, "election", SINCE, 0.0, "A", "1")
    row = conn.execute("SELECT * FROM items ORDER BY id DESC LIMIT 1").fetchone()
    assert row["channel"] == "executive"
    assert row["source_id"] == "federal-register"
    assert (row["admiralty_source"], row["admiralty_info"]) == ("A", "1")
    assert row["bill_id"] is None and row["case_id"] is None
    conn.close()


def test_per_term_error_isolation():
    """Mirror main()'s per-term try/except: a failing term commits nothing while the
    others land. main() uses the default DB path, so the loop is reproduced here."""
    conn = _env()
    terms = ["election", "boom", "voter roll"]
    by_term = {
        "election": _pages([_doc("e1")]),
        "voter roll": _pages([_doc("v1")]),
        # "boom" has no pages; the fake raises before lookup.
    }
    with _patched(by_term, raise_on="boom"):
        for term in terms:
            try:
                executive.collect_term(conn, BASE, AGENCIES, term, SINCE, 0.0, "A", "1")
                conn.commit()
            except Exception:
                conn.rollback()
    assert _count(conn) == 2  # election + voter roll survived; boom contributed nothing
    hashes = {r["content_hash"] for r in conn.execute("SELECT content_hash FROM items").fetchall()}
    assert common.content_hash("federal-register", "e1") in hashes
    assert common.content_hash("federal-register", "v1") in hashes
    conn.close()


if __name__ == "__main__":
    test_build_params()
    test_document_item_row()
    test_pagination()
    test_cross_term_dedup()
    test_idempotency_across_runs()
    test_persisted_mapping()
    test_per_term_error_isolation()
    print("ok")
