"""Offline tests for the litigation substantive-entry classifier and helpers.

Pure functions only -- no network, no DB. Uses the real config term lists so the
test guards the actual promotion rule. Run:  pytest tests/test_litigation.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.chdir(REPO)

import config  # noqa: E402
import db  # noqa: E402
from collectors import litigation as lit  # noqa: E402


def _lists():
    l = config.load_sources()["litigation"]
    return l.get("substantive_entry_types", []), l.get("excluded_entry_phrases", [])


def test_substantive_promoted():
    types, ex = _lists()
    S = lambda d: lit.is_substantive(d, types, ex)
    assert S("COMPLAINT against All Defendants filed by COMMON CAUSE")
    assert S("MOTION to Dismiss, MOTION for Summary Judgment by TODD BLANCHE, U.S. DEPARTMENT OF JUSTICE.")
    assert S("Memorandum in opposition to re 32 MOTION to Dismiss filed by COMMON CAUSE")
    assert S("Joint MOTION for Order for Expedited Dispositive Motion Briefing Schedule")
    assert S("ORDER granting motion to dismiss")
    assert S("NOTICE OF APPEAL by COMMON CAUSE")


def test_noise_excluded():
    types, ex = _lists()
    S = lambda d: lit.is_substantive(d, types, ex)
    assert not S("NOTICE of Appearance by Jane Petersen Bentrott on behalf of COMMON CAUSE")
    assert not S("MOTION for Leave to Appear Pro Hac Vice :Attorney Name- Sara Chimene-Weiss")
    assert not S("LCvR 26.1 CERTIFICATE OF DISCLOSURE of Corporate Affiliations and Financial Interests")
    assert not S("SUMMONS (3) Issued Electronically as to All Defendants")
    assert not S("RETURN OF SERVICE/AFFIDAVIT of Summons and Complaint Executed")
    assert not S("ORDER granting 4 Motion for Leave to Appear Pro Hac Vice")  # order, but pro-hac noise
    assert not S("")


def test_helpers():
    assert lit.slugify("United States v. Weber") == "united-states-v-weber"
    assert lit.split_caption("Common Cause v. U.S. Department of Justice") == ("Common Cause", "U.S. Department of Justice")
    assert lit.split_caption("No versus here") == (None, None)


def _raise_rate_limit(*args, **kwargs):
    raise RuntimeError("GET failed after 4 attempts: https://www.courtlistener.com/api/rest/v4/dockets/")


def test_resolve_rate_limit_skips_without_raising(tmp_path, monkeypatch):
    """A rate-limited resolve is caught per case: a skip dict, no exception, and
    nothing half-written -- the same graceful treatment the poll guard gives."""
    dbp = str(tmp_path / "t.db")
    db.init_db(dbp)
    conn = db.connect(dbp)
    monkeypatch.setattr(lit, "resolve_docket", _raise_rate_limit)
    seed = {"caption": "United States v. Delaware", "docket_number": "1:25-cv-01453",
            "court": "District of Delaware", "court_id": "ded", "category": "voter-data", "notes": "n"}
    r = lit.collect_case(conn, "base", {}, seed, [], [])          # must NOT raise
    assert r["resolved"] is False and r.get("resolve_failed") is True
    assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0   # nothing half-seeded
    conn.close()


def test_loop_continues_past_a_resolve_failure(tmp_path, monkeypatch):
    """First case's resolve rate-limits (skipped); the loop goes on and the second
    resolves normally -- and its caption takes the CourtListener case_name."""
    dbp = str(tmp_path / "t.db")
    db.init_db(dbp)
    conn = db.connect(dbp)
    lit.register_sources(conn)          # the B2 item's source_id FKs to sources
    conn.commit()
    calls = {"n": 0}

    def fake_resolve(base, headers, dn, court_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("GET failed after 4 attempts")
        return {"id": 777, "absolute_url": "/docket/777/us-v-real/",
                "date_filed": "2026-02-01", "date_terminated": None,
                "case_name": "United States v. RealName"}

    monkeypatch.setattr(lit, "resolve_docket", fake_resolve)
    monkeypatch.setattr(lit, "poll_entries", lambda *a, **k: [])
    seeds = [
        {"caption": "United States v. First", "docket_number": "1:25-cv-00001",
         "court": "District of Delaware", "court_id": "ded", "category": "voter-data", "notes": "n"},
        {"caption": "United States v. Second", "docket_number": "1:25-cv-00002",
         "court": "District of Colorado", "court_id": "cod", "category": "voter-data", "notes": "n"},
    ]
    results = [lit.collect_case(conn, "base", {}, s, [], []) for s in seeds]   # no crash
    assert results[0].get("resolve_failed") is True and results[0]["resolved"] is False
    assert results[1]["resolved"] is True
    rows = [row["caption"] for row in conn.execute("SELECT caption FROM cases").fetchall()]
    assert rows == ["United States v. RealName"]   # only the resolved one, case_name applied
    conn.close()


def test_main_exits_zero_when_every_resolve_rate_limits(tmp_path, monkeypatch):
    """The whole point of the guard: a rate-limited resolve no longer crashes main()."""
    monkeypatch.setattr(config, "load_env", lambda *a, **k: None)   # never read a real .env (no Turso creds leak in)
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "m.db"))      # local temp DB, not the repo's
    monkeypatch.setenv("COURTLISTENER_TOKEN", "test-token")
    monkeypatch.setattr(lit, "load_tracker_seeds", lambda *a, **k: [])
    monkeypatch.setattr(lit, "resolve_docket", _raise_rate_limit)
    assert lit.main() == 0


if __name__ == "__main__":
    test_substantive_promoted()
    test_noise_excluded()
    test_helpers()
    print("ok")
