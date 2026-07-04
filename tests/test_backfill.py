"""Suite for the state-bills backfill (scripts/backfill_state_bills.py).

Offline and deterministic: temp SQLite DB, no network, never touches Turso. The
script's main() is deliberately NOT exercised here -- it calls config.load_env()
and db.connect(), which would route to the PRODUCTION Turso when the env is set.
Tests drive the conn-parameterized pieces (populate_dimension, LINK_SQL) against
a temp DB instead, so the suite can never write to the remote.

Run:  pytest tests/test_backfill.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)  # config / db use repo-relative paths

import common  # noqa: E402
import db  # noqa: E402
from collectors import state  # noqa: E402

# Load the script by path -- scripts/ is not a package. Module-level imports run
# (config, db, collectors.state); main() is under an __main__ guard, so importing
# executes nothing that connects to Turso.
_spec = importlib.util.spec_from_file_location(
    "backfill_state_bills", os.path.join(REPO, "scripts", "backfill_state_bills.py"))
backfill = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backfill)

TERMS = ["voter registration", "voter roll", "proof of citizenship", "mail ballot",
         "absentee", "provisional ballot", "same-day registration", "voter id", "redistricting"]


def _conn():
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    db.init_db(path)
    conn = db.connect(path)
    state.register_source(conn, "https://api.legiscan.com/", "B", "2")
    conn.commit()
    return conn


def _seed_state_item(conn, *, st_abbrev, number, action, date="2026-01-01"):
    """Insert an items row exactly as the collector would (title
    '{state} {number}: {action}'), but UNLINKED (state_bill_id null) to mimic a
    pre-5b row the backfill has to link."""
    bill = {"bill_id": 0, "state": st_abbrev, "bill_number": number, "url": ""}
    row = state.to_item(bill, {"date": date, "action": action}, "B", "2")
    row["state_bill_id"] = None
    db.insert_ignore(conn, "items", row)
    conn.commit()


def test_backfill_prefix_match_sb16_not_sb160():
    """The trailing ':' in the link pattern makes 'TX SB16:' a key that does NOT
    capture 'TX SB160:' -- the exact regression a bare number prefix would cause."""
    conn = _conn()
    state.upsert_state_bill(conn, {}, {"bill_id": 16, "number": "SB16"}, "TX")
    state.upsert_state_bill(conn, {}, {"bill_id": 160, "number": "SB160"}, "TX")
    _seed_state_item(conn, st_abbrev="TX", number="SB16", action="Introduced")
    _seed_state_item(conn, st_abbrev="TX", number="SB160", action="Filed")

    conn.execute(backfill.LINK_SQL)
    conn.commit()

    links = {r["title"]: r["state_bill_id"] for r in
             conn.execute("SELECT title, state_bill_id FROM items WHERE channel='state'").fetchall()}
    assert links["TX SB16: Introduced"] == "16"      # SB16 links to SB16, not SB160
    assert links["TX SB160: Filed"] == "160"         # SB160 links to SB160, not SB16
    conn.close()


def test_backfill_populate_dimension_then_link():
    """populate_dimension upserts one state_bills row per ELECTION bill from the
    masterlist (never getBill), and LINK_SQL then links the matching pre-5b items.
    An off-topic bill gets no row, so its item stays null -- the expected leftover."""
    conn = _conn()
    masterlist = {
        "status": "OK",
        "masterlist": {
            "session": {"session_id": 1, "session_name": "2026 Regular Session"},
            "0": {"bill_id": 1700001, "number": "SB100", "change_hash": "a",
                  "title": "Relating to voter registration procedures",
                  "last_action": "Introduced", "last_action_date": "2026-01-20"},
            "1": {"bill_id": 1700003, "number": "HB999", "change_hash": "c",
                  "title": "Relating to alien registration of nonresident business agents"},
        },
    }

    def fake(url, params=None, headers=None, timeout=common.DEFAULT_TIMEOUT, throttle=0.0):
        assert params["op"] == "getMasterList"       # the backfill must never getBill
        return masterlist

    orig = common.http_get
    common.http_get = fake
    try:
        n = backfill.populate_dimension(conn, "https://api.legiscan.com/", "k", ["TX"], TERMS, throttle=0.0)
    finally:
        common.http_get = orig
    conn.commit()

    assert n == 1                                    # only the voter-registration bill matched
    ids = [r["state_bill_id"] for r in conn.execute(
        "SELECT state_bill_id FROM state_bills").fetchall()]
    assert ids == ["1700001"]                        # off-topic HB999 got no dimension row

    _seed_state_item(conn, st_abbrev="TX", number="SB100", action="Committee report favorable")
    _seed_state_item(conn, st_abbrev="TX", number="HB999", action="Introduced")

    linked = conn.execute(backfill.LINK_SQL).rowcount
    conn.commit()
    assert linked == 1                               # only SB100 links; HB999 has no bill row
    got = {r["title"]: r["state_bill_id"] for r in conn.execute(
        "SELECT title, state_bill_id FROM items WHERE channel='state'").fetchall()}
    assert got["TX SB100: Committee report favorable"] == "1700001"
    assert got["TX HB999: Introduced"] is None       # off-topic bill: item stays null, expected
    conn.close()


if __name__ == "__main__":
    test_backfill_prefix_match_sb16_not_sb160()
    test_backfill_populate_dimension_then_link()
    print("ok")
